#!/usr/bin/env python3
"""Run the versioned HTTP acceptance probes for a Waypoint deployment."""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--api-base-url", required=True)
    parser.add_argument("--web-base-url", required=True)
    parser.add_argument("--api-key")
    parser.add_argument("--require-authenticated", action="store_true")
    parser.add_argument("--timeout-seconds", type=float, default=20.0)
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def _json_type_matches(value: Any, expected: str) -> bool:
    types: dict[str, type[Any] | tuple[type[Any], ...]] = {
        "array": list,
        "object": dict,
        "string": str,
        "number": (int, float),
        "boolean": bool,
        "null": type(None),
    }
    expected_type = types.get(expected)
    if expected_type is None:
        raise ValueError(f"Unsupported expected_json_type '{expected}'.")
    return isinstance(value, expected_type)


def _probe(
    definition: dict[str, Any],
    *,
    bases: dict[str, str],
    api_key: str | None,
    require_authenticated: bool,
    timeout_seconds: float,
) -> dict[str, Any]:
    name = str(definition["name"])
    auth = str(definition.get("auth", "none"))
    if auth == "api_key" and not api_key:
        status = "failed" if require_authenticated else "skipped"
        return {"name": name, "status": status, "detail": "API key was not provided."}
    if auth not in {"none", "api_key"}:
        raise ValueError(f"Probe '{name}' has unsupported auth mode '{auth}'.")

    base_name = str(definition["base"])
    if base_name not in bases:
        raise ValueError(f"Probe '{name}' references unknown base '{base_name}'.")
    url = f"{bases[base_name].rstrip('/')}/{str(definition['path']).lstrip('/')}"
    headers = {"Accept": "application/json"}
    if auth == "api_key":
        headers["X-API-Key"] = str(api_key)

    try:
        with urllib.request.urlopen(
            urllib.request.Request(url, headers=headers),
            timeout=timeout_seconds,
        ) as response:
            response_status = response.status
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as error:
        response_status = error.code
        body = error.read().decode("utf-8", errors="replace")
    except urllib.error.URLError as error:
        return {"name": name, "status": "failed", "url": url, "detail": str(error.reason)}

    expected_status = int(definition["expected_status"])
    if response_status != expected_status:
        return {
            "name": name,
            "status": "failed",
            "url": url,
            "detail": f"Expected HTTP {expected_status}, received {response_status}.",
        }

    expected_body = definition.get("expected_body")
    if expected_body is not None and body.strip() != str(expected_body):
        return {
            "name": name,
            "status": "failed",
            "url": url,
            "detail": "Response body did not match the manifest.",
        }

    expected_json_type = definition.get("expected_json_type")
    if expected_json_type is not None:
        try:
            payload = json.loads(body)
        except json.JSONDecodeError as error:
            return {
                "name": name,
                "status": "failed",
                "url": url,
                "detail": f"Response was not valid JSON: {error}.",
            }
        if not _json_type_matches(payload, str(expected_json_type)):
            return {
                "name": name,
                "status": "failed",
                "url": url,
                "detail": f"JSON response was not a {expected_json_type}.",
            }

    return {"name": name, "status": "passed", "url": url}


def main() -> int:
    args = _arguments()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    bases = {"api": args.api_base_url, "web": args.web_base_url}
    results = [
        _probe(
            definition,
            bases=bases,
            api_key=args.api_key,
            require_authenticated=args.require_authenticated,
            timeout_seconds=args.timeout_seconds,
        )
        for definition in manifest["probes"]
    ]
    report = {
        "schema_version": manifest["schema_version"],
        "source_manifest": str(args.manifest),
        "results": results,
        "passed": all(result["status"] in {"passed", "skipped"} for result in results),
    }
    rendered = json.dumps(report, indent=2, sort_keys=True)
    print(rendered)
    if args.output:
        args.output.write_text(f"{rendered}\n", encoding="utf-8")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
