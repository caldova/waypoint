#!/usr/bin/env python3
"""Export a curated WaypointIQ OpenAPI contract from a Waypoint API endpoint."""

from __future__ import annotations

import argparse
import json
import ssl
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import urlopen


IQ_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = IQ_ROOT / "openapi.json"

Operation = tuple[str, str, str, str]

OPERATIONS: tuple[Operation, ...] = (
    ("get", "/api/work", "waypointiq_get_work", "read"),
    ("get", "/api/actions/types", "waypointiq_get_action_types", "read"),
    ("get", "/api/runs", "waypointiq_get_runs", "read"),
    ("post", "/api/runs", "waypointiq_create_run", "write"),
    ("get", "/api/cases", "waypointiq_get_cases", "read"),
    ("post", "/api/cases", "waypointiq_create_case", "write"),
    ("get", "/api/cases/{case_id}", "waypointiq_get_case", "read"),
    ("get", "/api/cases/{case_id}/recommendations", "waypointiq_get_case_recommendations", "read"),
    ("post", "/api/cases/{case_id}/recommendations", "waypointiq_create_case_recommendation", "write"),
    ("get", "/api/cases/{case_id}/drafts", "waypointiq_get_case_drafts", "read"),
    ("post", "/api/cases/{case_id}/drafts", "waypointiq_create_case_draft", "write"),
    ("post", "/api/cases/{case_id}/actions", "waypointiq_create_proposed_action", "write"),
    ("post", "/api/cases/{case_id}/approvals", "waypointiq_create_case_approval", "admin"),
    ("post", "/api/actions/{action_id}/authorize", "waypointiq_authorize_action", "admin"),
    ("get", "/api/invoices", "waypointiq_get_invoices", "read"),
    ("get", "/api/invoices/{invoice_id}", "waypointiq_get_invoice", "read"),
    ("get", "/api/invoices/{invoice_id}/context", "waypointiq_get_invoice_context", "read"),
    ("get", "/api/invoices/{invoice_id}/assurance", "waypointiq_get_invoice_assurance", "read"),
    ("get", "/api/invoice-decisions", "waypointiq_get_invoice_decisions", "read"),
    ("get", "/api/findings", "waypointiq_get_findings", "read"),
    ("get", "/api/findings/{finding_id}/validations", "waypointiq_get_finding_validations", "read"),
    ("post", "/api/findings/{finding_id}/validations", "waypointiq_create_finding_validation", "write"),
    ("get", "/api/evidence", "waypointiq_get_evidence", "read"),
    ("get", "/api/contract-documents/{document_id}", "waypointiq_get_contract_document", "read"),
    ("get", "/api/policies/{policy_id}", "waypointiq_get_policy", "read"),
    ("get", "/api/suppliers", "waypointiq_get_suppliers", "read"),
    ("get", "/api/scenarios", "waypointiq_get_scenarios", "read"),
    ("get", "/api/audit/events", "waypointiq_get_audit_events", "admin"),
    ("get", "/api/audit/decisions", "waypointiq_get_decision_audit_events", "admin"),
    ("post", "/api/admin/seed/ledgerfield", "waypointiq_import_ledgerfield_seed", "admin"),
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", required=True, help="Waypoint API endpoint, e.g. https://localhost:62595")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="Output OpenAPI JSON path")
    parser.add_argument(
        "--allow-insecure-localhost",
        action="store_true",
        help="Allow self-signed localhost HTTPS certificates while exporting local Aspire Waypoint.",
    )
    args = parser.parse_args()

    endpoint = args.endpoint.rstrip("/")
    source = _fetch_openapi(endpoint, allow_insecure_localhost=args.allow_insecure_localhost)
    curated = _curate(source, endpoint)

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(curated, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(f"wrote {output}")
    print(f"operations={sum(len(methods) for methods in curated['paths'].values())}")
    return 0


def _fetch_openapi(endpoint: str, *, allow_insecure_localhost: bool) -> dict[str, Any]:
    url = f"{endpoint}/openapi.json"
    context = None
    if allow_insecure_localhost and _is_localhost(endpoint):
        context = ssl._create_unverified_context()  # noqa: SLF001 - local Aspire dev certs only.
    try:
        with urlopen(url, timeout=20, context=context) as response:  # noqa: S310 - endpoint is explicit CLI input.
            payload = response.read().decode("utf-8")
    except HTTPError as exc:
        raise SystemExit(f"GET {url} failed with HTTP {exc.code}") from exc
    except URLError as exc:
        raise SystemExit(f"GET {url} failed: {exc.reason}") from exc

    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"GET {url} did not return JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise SystemExit(f"GET {url} returned non-object JSON")
    return parsed


def _curate(source: dict[str, Any], endpoint: str) -> dict[str, Any]:
    paths: dict[str, Any] = {}
    source_paths = source.get("paths")
    if not isinstance(source_paths, dict):
        raise SystemExit("Source OpenAPI document has no paths object")

    for method, path, operation_id, authority in OPERATIONS:
        source_path = source_paths.get(path)
        if not isinstance(source_path, dict) or method not in source_path:
            print(f"warning: source OpenAPI missing {method.upper()} {path}", file=sys.stderr)
            continue
        operation = deepcopy(source_path[method])
        operation["operationId"] = operation_id
        operation["tags"] = [f"waypoint-iq-{authority}"]
        operation["x-waypoint-iq-authority"] = authority
        operation.setdefault("description", "")
        operation["description"] = _append_authority_note(str(operation["description"]), authority)
        paths.setdefault(path, {})[method] = operation

    return {
        "openapi": source.get("openapi", "3.1.0"),
        "info": {
            "title": "waypoint-iq",
            "version": "0.1.0",
            "description": (
                "Curated Caldova Waypoint API surface for Forge agents. "
                "Read, write, and admin operations are tagged with x-waypoint-iq-authority."
            ),
        },
        "servers": [{"url": endpoint, "description": "Waypoint API endpoint selected at export time"}],
        "paths": paths,
        "components": deepcopy(source.get("components", {})),
    }


def _append_authority_note(description: str, authority: str) -> str:
    note = f"WaypointIQ authority: {authority}."
    return f"{description.rstrip()}\n\n{note}".lstrip()


def _is_localhost(endpoint: str) -> bool:
    normalized = endpoint.lower()
    return "://localhost" in normalized or "://127.0.0.1" in normalized


if __name__ == "__main__":
    raise SystemExit(main())
