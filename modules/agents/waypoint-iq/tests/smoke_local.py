#!/usr/bin/env python3
"""Smoke a local Waypoint endpoint against the WaypointIQ contract."""

from __future__ import annotations

import argparse
import json
import ssl
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import urlopen


IQ_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SPEC = IQ_ROOT / "openapi.json"
READ_SMOKE_PATHS = (
    "/health",
    "/api/work",
    "/api/actions/types",
    "/api/runs",
    "/api/cases",
    "/api/invoices",
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", required=True, help="Waypoint API endpoint, e.g. https://localhost:62595")
    parser.add_argument("--spec", default=str(DEFAULT_SPEC), help="Curated WaypointIQ OpenAPI JSON path")
    parser.add_argument("--allow-insecure-localhost", action="store_true")
    args = parser.parse_args()

    endpoint = args.endpoint.rstrip("/")
    context = None
    if args.allow_insecure_localhost and _is_localhost(endpoint):
        context = ssl._create_unverified_context()  # noqa: SLF001 - local Aspire dev certs only.

    spec = json.loads(Path(args.spec).read_text(encoding="utf-8"))
    _assert_contract(spec, endpoint)
    for path in READ_SMOKE_PATHS:
        body = _get_json_or_text(f"{endpoint}{path}", context=context)
        print(f"ok GET {path} ({_shape(body)})")
    print("waypoint-iq local smoke passed")
    return 0


def _assert_contract(spec: dict[str, Any], endpoint: str) -> None:
    if spec.get("info", {}).get("title") != "waypoint-iq":
        raise SystemExit("Spec title must be waypoint-iq")
    servers = spec.get("servers", [])
    if not isinstance(servers, list) or not any(server.get("url") == endpoint for server in servers if isinstance(server, dict)):
        raise SystemExit(f"Spec servers must include selected endpoint: {endpoint}")
    operations = [
        operation
        for methods in spec.get("paths", {}).values()
        for operation in methods.values()
        if isinstance(operation, dict)
    ]
    if not operations:
        raise SystemExit("Spec has no operations")
    missing_authority = [op.get("operationId") for op in operations if not op.get("x-waypoint-iq-authority")]
    if missing_authority:
        raise SystemExit(f"Operations missing x-waypoint-iq-authority: {missing_authority}")
    unknown_authority = [
        op.get("operationId")
        for op in operations
        if op.get("x-waypoint-iq-authority") not in {"read", "write", "admin"}
    ]
    if unknown_authority:
        raise SystemExit(f"Operations have unknown x-waypoint-iq-authority: {unknown_authority}")


def _get_json_or_text(url: str, *, context: ssl.SSLContext | None) -> Any:
    try:
        with urlopen(url, timeout=20, context=context) as response:  # noqa: S310 - endpoint is explicit CLI input.
            payload = response.read().decode("utf-8")
    except HTTPError as exc:
        raise SystemExit(f"GET {url} failed with HTTP {exc.code}") from exc
    except URLError as exc:
        raise SystemExit(f"GET {url} failed: {exc.reason}") from exc
    try:
        return json.loads(payload)
    except json.JSONDecodeError:
        return payload


def _shape(value: Any) -> str:
    if isinstance(value, list):
        return f"list[{len(value)}]"
    if isinstance(value, dict):
        return f"object[{len(value)}]"
    return type(value).__name__


def _is_localhost(endpoint: str) -> bool:
    normalized = endpoint.lower()
    return "://localhost" in normalized or "://127.0.0.1" in normalized


if __name__ == "__main__":
    raise SystemExit(main())
