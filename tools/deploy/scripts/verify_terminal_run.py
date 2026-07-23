#!/usr/bin/env python3
"""Verify that an invoice assurance run reached a successful terminal state."""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

SUCCESSFUL_TERMINAL_STATUS = "completed"


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-base-url", required=True)
    parser.add_argument("--api-key", required=True)
    parser.add_argument("--invoice-id", required=True)
    parser.add_argument("--updated-after", required=True)
    parser.add_argument("--timeout-seconds", type=float, default=15.0)
    parser.add_argument("--poll-timeout-seconds", type=float, default=180.0)
    parser.add_argument("--poll-interval-seconds", type=float, default=5.0)
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def _select_run(runs: list[dict[str, Any]], invoice_id: str) -> dict[str, Any] | None:
    expected_name = f"assurance:{invoice_id}"
    matches = [run for run in runs if run.get("name") == expected_name]
    if not matches:
        return None
    return max(matches, key=lambda run: str(run.get("updated_at") or run.get("created_at") or ""))


def _verify(
    *,
    api_base_url: str,
    api_key: str,
    invoice_id: str,
    updated_after: datetime,
    timeout_seconds: float,
    poll_timeout_seconds: float = 0.0,
    poll_interval_seconds: float = 5.0,
) -> dict[str, Any]:
    url = f"{api_base_url.rstrip('/')}/api/runs"
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "X-API-Key": api_key},
    )
    deadline = time.monotonic() + max(0.0, poll_timeout_seconds)
    while True:
        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                payload = json.load(response)
        except urllib.error.HTTPError as error:
            result = {
                "passed": False,
                "invoice_id": invoice_id,
                "detail": f"Runs endpoint returned HTTP {error.code}.",
            }
            retryable = error.code == 429 or error.code >= 500
        except (TimeoutError, urllib.error.URLError) as error:
            reason = getattr(error, "reason", error)
            result = {
                "passed": False,
                "invoice_id": invoice_id,
                "detail": f"Runs endpoint request failed: {reason}.",
            }
            retryable = True
        else:
            result = _evaluate_payload(payload, invoice_id, updated_after)
            retryable = not result["passed"]

        if not retryable or time.monotonic() >= deadline:
            return result
        time.sleep(max(0.0, poll_interval_seconds))


def _evaluate_payload(
    payload: Any,
    invoice_id: str,
    updated_after: datetime,
) -> dict[str, Any]:
    if not isinstance(payload, list):
        return {
            "passed": False,
            "invoice_id": invoice_id,
            "detail": "Runs endpoint did not return an array.",
        }

    run = _select_run(payload, invoice_id)
    if run is None:
        return {
            "passed": False,
            "invoice_id": invoice_id,
            "detail": f"No assurance:{invoice_id} run was found.",
        }

    status = str(run.get("status") or "")
    updated_at_raw = str(run.get("updated_at") or "")
    try:
        updated_at = datetime.fromisoformat(updated_at_raw.replace("Z", "+00:00"))
    except ValueError:
        updated_at = None
    is_current = updated_at is not None and updated_at > updated_after
    has_operation_id = bool(run.get("app_insights_operation_id"))
    result = {
        "passed": (
            status == SUCCESSFUL_TERMINAL_STATUS and is_current and has_operation_id
        ),
        "invoice_id": invoice_id,
        "run_id": run.get("id"),
        "status": status,
        "foundry_agent_name": run.get("foundry_agent_name"),
        "app_insights_operation_id": run.get("app_insights_operation_id"),
        "has_operation_id": has_operation_id,
        "updated_at": updated_at_raw,
        "updated_after": updated_after.isoformat(),
    }
    if not result["passed"]:
        failures = []
        if status != SUCCESSFUL_TERMINAL_STATUS:
            failures.append(
                f"status '{status}' is not '{SUCCESSFUL_TERMINAL_STATUS}'"
            )
        if not is_current:
            failures.append("run was not updated after the hosted invocation started")
        if not has_operation_id:
            failures.append("run has no App Insights operation id")
        result["detail"] = "; ".join(failures)
    return result


def main() -> int:
    args = _arguments()
    result = _verify(
        api_base_url=args.api_base_url,
        api_key=args.api_key,
        invoice_id=args.invoice_id,
        updated_after=datetime.fromisoformat(args.updated_after.replace("Z", "+00:00")),
        timeout_seconds=args.timeout_seconds,
        poll_timeout_seconds=args.poll_timeout_seconds,
        poll_interval_seconds=args.poll_interval_seconds,
    )
    rendered = json.dumps(result, indent=2, sort_keys=True)
    print(rendered)
    if args.output:
        args.output.write_text(f"{rendered}\n", encoding="utf-8")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
