#!/usr/bin/env python3
"""Create or update the Foundry waypoint-iq toolbox from the curated OpenAPI spec."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from copy import deepcopy
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


IQ_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SPEC = IQ_ROOT / "openapi.json"
DEFAULT_TOOLBOX_NAME = "waypoint-iq"
DEFAULT_TOOL_NAME = "waypoint_iq"
DEFAULT_DESCRIPTION = "WaypointIQ managed-identity OpenAPI toolbox for Caldova Waypoint."
DEFAULT_AUDIENCE = os.environ.get("WAYPOINT_AUDIENCE") or os.environ.get("WAYPOINT_API_SCOPE") or ""
AI_SCOPE = "https://ai.azure.com"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--project-endpoint",
        default=_first_env("PROJECT_ENDPOINT", "AZURE_AI_PROJECT_ENDPOINT", "FOUNDRY_PROJECT_ENDPOINT"),
        help="Foundry project endpoint. Defaults to PROJECT_ENDPOINT/AZURE_AI_PROJECT_ENDPOINT/FOUNDRY_PROJECT_ENDPOINT.",
    )
    parser.add_argument("--toolbox-name", default=DEFAULT_TOOLBOX_NAME)
    parser.add_argument("--tool-name", default=DEFAULT_TOOL_NAME)
    parser.add_argument("--spec", default=str(DEFAULT_SPEC), help="Curated OpenAPI JSON path")
    parser.add_argument(
        "--waypoint-endpoint",
        help="Override the OpenAPI servers[0].url before publishing, e.g. the hosted Waypoint API endpoint.",
    )
    parser.add_argument("--audience", default=DEFAULT_AUDIENCE, help="Waypoint API audience for managed identity")
    parser.add_argument("--description", default=DEFAULT_DESCRIPTION)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Build and compare the payload but do not create or publish toolbox versions.",
    )
    args = parser.parse_args()

    if not args.project_endpoint:
        raise SystemExit("--project-endpoint or PROJECT_ENDPOINT/AZURE_AI_PROJECT_ENDPOINT/FOUNDRY_PROJECT_ENDPOINT is required")

    project_endpoint = args.project_endpoint.rstrip("/")
    desired = _build_payload(
        spec_path=Path(args.spec),
        tool_name=args.tool_name,
        audience=args.audience,
        description=args.description,
        waypoint_endpoint=args.waypoint_endpoint,
    )
    current = _show_toolbox(project_endpoint, args.toolbox_name)
    if current is None:
        if args.dry_run:
            print(f"would create toolbox {args.toolbox_name}")
            print(json.dumps(desired, indent=2))
            return 0
        created = _create_toolbox(project_endpoint, args.toolbox_name, desired)
        print(f"created toolbox {args.toolbox_name} version {created.get('version')}")
        print(created.get("endpoint", _default_endpoint(project_endpoint, args.toolbox_name)))
        return 0

    current_payload = _version_payload(current)
    if _canonical(current_payload) == _canonical(desired):
        version = str(current.get("version", {}).get("version") or current.get("toolbox", {}).get("default_version") or "")
        print(f"toolbox {args.toolbox_name} already up to date at version {version}")
        print(current.get("endpoint", _default_endpoint(project_endpoint, args.toolbox_name)))
        return 0

    if args.dry_run:
        print(f"would create and publish a new version for toolbox {args.toolbox_name}")
        return 0

    version = _create_version(project_endpoint, args.toolbox_name, desired)
    version_number = str(version.get("version") or version.get("version_number") or "")
    if not version_number and isinstance(version.get("id"), str) and ":" in version["id"]:
        version_number = version["id"].rsplit(":", maxsplit=1)[-1]
    if not version_number:
        raise SystemExit(f"Could not determine created toolbox version: {json.dumps(version, indent=2)}")
    _publish_version(project_endpoint, args.toolbox_name, version_number)
    print(f"published toolbox {args.toolbox_name} version {version_number}")
    print(_default_endpoint(project_endpoint, args.toolbox_name))
    return 0


def _build_payload(
    *,
    spec_path: Path,
    tool_name: str,
    audience: str,
    description: str,
    waypoint_endpoint: str | None,
) -> dict[str, Any]:
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    if waypoint_endpoint:
        spec["servers"] = [{"url": waypoint_endpoint.rstrip("/"), "description": "Waypoint API endpoint selected at deploy time"}]
    _validate_spec(spec)
    return {
        "description": description,
        "tools": [
            {"type": "toolbox_search_preview"},
            {
                "type": "openapi",
                "openapi": {
                    "name": tool_name,
                    "auth": {
                        "type": "managed_identity",
                        "security_scheme": {"audience": audience},
                    },
                    "spec": spec,
                },
            },
        ],
    }


def _validate_spec(spec: dict[str, Any]) -> None:
    if spec.get("info", {}).get("title") != "waypoint-iq":
        raise SystemExit("OpenAPI spec info.title must be waypoint-iq")
    servers = spec.get("servers")
    if not isinstance(servers, list) or not servers or not isinstance(servers[0], dict) or not servers[0].get("url"):
        raise SystemExit("OpenAPI spec must include a server URL")
    operations = [
        operation
        for methods in spec.get("paths", {}).values()
        if isinstance(methods, dict)
        for operation in methods.values()
        if isinstance(operation, dict)
    ]
    if not operations:
        raise SystemExit("OpenAPI spec has no operations")
    missing_authority = [op.get("operationId") for op in operations if not op.get("x-waypoint-iq-authority")]
    if missing_authority:
        raise SystemExit(f"Operations missing x-waypoint-iq-authority: {missing_authority}")


def _show_toolbox(project_endpoint: str, toolbox_name: str) -> dict[str, Any] | None:
    command = [
        "azd",
        "ai",
        "toolbox",
        "show",
        toolbox_name,
        "--project-endpoint",
        project_endpoint,
        "--output",
        "json",
        "--no-prompt",
    ]
    completed = subprocess.run(command, check=False, capture_output=True, text=True)  # noqa: S603 - fixed executable/args.
    if completed.returncode != 0:
        if "not found" in completed.stderr.lower() or "not found" in completed.stdout.lower():
            return None
        raise SystemExit(completed.stderr or completed.stdout)
    return json.loads(completed.stdout)


def _create_toolbox(project_endpoint: str, toolbox_name: str, payload: dict[str, Any]) -> dict[str, Any]:
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
        path = handle.name
    try:
        command = [
            "azd",
            "ai",
            "toolbox",
            "create",
            toolbox_name,
            "--from-file",
            path,
            "--project-endpoint",
            project_endpoint,
            "--output",
            "json",
            "--no-prompt",
        ]
        completed = subprocess.run(command, check=False, capture_output=True, text=True)  # noqa: S603 - fixed executable/args.
        if completed.returncode != 0:
            raise SystemExit(completed.stderr or completed.stdout)
        return json.loads(completed.stdout)
    finally:
        Path(path).unlink(missing_ok=True)


def _create_version(project_endpoint: str, toolbox_name: str, payload: dict[str, Any]) -> dict[str, Any]:
    token = _access_token()
    request = Request(
        f"{project_endpoint}/toolboxes/{toolbox_name}/versions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Foundry-Features": "Toolboxes=V1Preview",
        },
        method="POST",
    )
    return _json_request(request)


def _publish_version(project_endpoint: str, toolbox_name: str, version: str) -> None:
    command = [
        "azd",
        "ai",
        "toolbox",
        "publish",
        toolbox_name,
        version,
        "--project-endpoint",
        project_endpoint,
        "--no-prompt",
    ]
    completed = subprocess.run(command, check=False, capture_output=True, text=True)  # noqa: S603 - fixed executable/args.
    if completed.returncode != 0:
        raise SystemExit(completed.stderr or completed.stdout)


def _access_token() -> str:
    az_command = shutil.which("az") or shutil.which("az.cmd") or "az"
    completed = subprocess.run(
        [az_command, "account", "get-access-token", "--resource", AI_SCOPE, "--query", "accessToken", "-o", "tsv"],
        check=False,
        capture_output=True,
        text=True,
    )  # noqa: S603 - fixed executable/args.
    if completed.returncode != 0:
        raise SystemExit(completed.stderr or completed.stdout)
    token = completed.stdout.strip()
    if not token:
        raise SystemExit("az account get-access-token returned an empty token")
    return token


def _json_request(request: Request) -> dict[str, Any]:
    try:
        with urlopen(request, timeout=60) as response:  # noqa: S310 - URL is a resolved Foundry project endpoint.
            payload = response.read().decode("utf-8")
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"{request.method} {request.full_url} failed with HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        raise SystemExit(f"{request.method} {request.full_url} failed: {exc.reason}") from exc
    parsed = json.loads(payload) if payload else {}
    return parsed if isinstance(parsed, dict) else {"value": parsed}


def _version_payload(show_result: dict[str, Any]) -> dict[str, Any]:
    version = show_result.get("version", {})
    return {
        "description": version.get("description", ""),
        "tools": deepcopy(version.get("tools", [])),
    }


def _canonical(value: Any) -> str:
    value = _normalize_json_numbers(value)
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _normalize_json_numbers(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _normalize_json_numbers(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_normalize_json_numbers(item) for item in value]
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def _default_endpoint(project_endpoint: str, toolbox_name: str) -> str:
    return f"{project_endpoint}/toolboxes/{toolbox_name}/mcp?api-version=v1"


def _first_env(*names: str) -> str | None:
    for name in names:
        value = os.getenv(name)
        if value:
            return value
    return None


if __name__ == "__main__":
    raise SystemExit(main())
