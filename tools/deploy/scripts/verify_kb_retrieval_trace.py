#!/usr/bin/env python3
"""Verify an E2E assurance run used contracts-kb retrieval instead of fallback."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable

KB_MARKERS = (
    "knowledge_base___knowledge_base_retrieve",
    "knowledge_base_retrieve",
)
FALLBACK_MARKERS = (
    "gather_contract_policy_evidence",
    "Fallback retrieval",
    "fallback retrieval",
    "Local fallback evidence",
    "Primary knowledge-base retrieval failed",
)
KB_ERROR_MARKERS = (
    "BadRequest",
    "retrieval failed",
    "knowledge-base retrieval failed",
    "Function tools with reasoning_effort are not supported",
)
RETRIEVAL_SOURCE_REF_PATTERN = re.compile(
    r"\b(?:(?:KB|Foundry|retrieved)\s+)?ref_id\s*:\s*\d+\b",
    re.IGNORECASE,
)


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-base-url", required=True)
    parser.add_argument("--api-key", required=True)
    parser.add_argument("--terminal-run-json", type=Path, required=True)
    parser.add_argument("--workspace-id", required=True)
    parser.add_argument("--lookback-hours", type=int, default=24)
    parser.add_argument("--timeout-seconds", type=float, default=15.0)
    parser.add_argument("--log-query-timeout-seconds", type=float, default=60.0)
    parser.add_argument("--poll-timeout-seconds", type=float, default=300.0)
    parser.add_argument("--poll-interval-seconds", type=float, default=15.0)
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def _load_terminal_run(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Unable to read terminal run evidence '{path}': {exc}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"Terminal run evidence '{path}' did not contain an object.")
    return payload


def _load_run_from_api(
    *,
    api_base_url: str,
    api_key: str,
    run_id: str,
    timeout_seconds: float,
) -> dict[str, Any]:
    request = urllib.request.Request(
        f"{api_base_url.rstrip('/')}/api/runs",
        headers={"Accept": "application/json", "X-API-Key": api_key},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as error:
        raise RuntimeError(f"Runs endpoint returned HTTP {error.code}.") from error
    except (TimeoutError, urllib.error.URLError) as error:
        reason = getattr(error, "reason", error)
        raise RuntimeError(f"Runs endpoint request failed: {reason}.") from error
    if not isinstance(payload, list):
        raise RuntimeError("Runs endpoint did not return an array.")
    for run in payload:
        if isinstance(run, dict) and run.get("id") == run_id:
            return run
    raise RuntimeError(f"Run '{run_id}' was not found in /api/runs.")


def _kql(operation_id: str, lookback_hours: int) -> str:
    escaped_operation_id = operation_id.replace("'", "''")
    lookback = max(1, lookback_hours)
    markers = sorted(set(KB_MARKERS + FALLBACK_MARKERS + KB_ERROR_MARKERS))
    marker_list = ", ".join("'" + marker.replace("'", "''") + "'" for marker in markers)
    return f"""
let op = '{escaped_operation_id}';
let markers = dynamic([{marker_list}]);
union isfuzzy=true AppTraces, traces
| where TimeGenerated > ago({lookback}h)
| extend operation_id = tostring(column_ifexists('OperationId', ''))
| extend operation_id = iff(isempty(operation_id), tostring(column_ifexists('operation_Id', '')), operation_id)
| extend message_text = tostring(column_ifexists('Message', ''))
| extend message_text = iff(isempty(message_text), tostring(column_ifexists('message', '')), message_text)
| extend property_text = tostring(column_ifexists('Properties', ''))
| extend property_text = iff(isempty(property_text), tostring(column_ifexists('customDimensions', '')), property_text)
| where operation_id == op or property_text has op
| where message_text has_any (markers) or property_text has_any (markers)
| project TimeGenerated, message_text, property_text
| order by TimeGenerated asc
| take 200
""".strip()


def _run_log_query(
    *,
    workspace_id: str,
    query: str,
    timeout_seconds: float,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> list[dict[str, Any]]:
    completed = runner(
        [
            "az",
            "monitor",
            "log-analytics",
            "query",
            "-w",
            workspace_id,
            "--analytics-query",
            query,
            "-o",
            "json",
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=max(1.0, timeout_seconds),
    )
    return _parse_log_query_output(completed.stdout)


def _parse_log_query_output(raw: str) -> list[dict[str, Any]]:
    payload = json.loads(raw or "{}")
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if not isinstance(payload, dict):
        return []
    tables = payload.get("tables")
    if isinstance(tables, list) and tables:
        table = tables[0]
        columns = [
            str(column.get("name"))
            for column in table.get("columns", [])
            if isinstance(column, dict)
        ]
        rows = []
        for row in table.get("rows", []):
            if isinstance(row, list):
                rows.append(
                    {
                        columns[index]: value
                        for index, value in enumerate(row)
                        if index < len(columns)
                    }
                )
        return rows
    value = payload.get("value")
    if isinstance(value, list):
        return [row for row in value if isinstance(row, dict)]
    return []


def _flatten_text(value: Any) -> str:
    if isinstance(value, dict):
        return " ".join(_flatten_text(item) for item in value.values())
    if isinstance(value, list):
        return " ".join(_flatten_text(item) for item in value)
    if value is None:
        return ""
    return str(value)


def _contains_any(text: str, markers: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(marker.lower() in lowered for marker in markers)


def _kb_source_refs(value: Any) -> list[str]:
    if isinstance(value, dict):
        refs = []
        for key, item in value.items():
            if key in {"source_ref", "source", "id"} and isinstance(item, str):
                if RETRIEVAL_SOURCE_REF_PATTERN.search(item):
                    refs.append(item)
            elif key == "source_refs" and isinstance(item, list):
                refs.extend(
                    str(ref)
                    for ref in item
                    if isinstance(ref, str) and RETRIEVAL_SOURCE_REF_PATTERN.search(ref)
                )
            else:
                refs.extend(_kb_source_refs(item))
        return refs
    if isinstance(value, list):
        refs = []
        for item in value:
            refs.extend(_kb_source_refs(item))
        return refs
    return []


def _evaluate(run: dict[str, Any], trace_rows: list[dict[str, Any]]) -> dict[str, Any]:
    metadata = run.get("metadata") if isinstance(run.get("metadata"), dict) else {}
    run_text = _flatten_text(metadata)
    trace_texts = [_flatten_text(row) for row in trace_rows]
    trace_text = " ".join(trace_texts)

    has_kb_trace = _contains_any(trace_text, KB_MARKERS)
    kb_runtime_source_refs = sorted(set(_kb_source_refs(metadata)))
    has_kb_runtime_evidence = bool(kb_runtime_source_refs)
    fallback_in_trace = _contains_any(trace_text, FALLBACK_MARKERS)
    fallback_in_metadata = _contains_any(run_text, FALLBACK_MARKERS)
    kb_error_in_trace = _contains_any(trace_text, KB_ERROR_MARKERS)
    kb_error_in_metadata = _contains_any(run_text, KB_ERROR_MARKERS)

    failures = []
    if not has_kb_trace and not has_kb_runtime_evidence:
        failures.append(
            "no knowledge_base_retrieve trace event or KB-cited runtime evidence was found"
        )
    if fallback_in_trace:
        failures.append("fallback evidence tool or fallback summary appeared in the trace")
    if fallback_in_metadata:
        failures.append("the recorded run metadata contains fallback evidence")
    if kb_error_in_trace:
        failures.append("the trace contains a knowledge-base retrieval error")
    if kb_error_in_metadata:
        failures.append("the recorded run metadata contains a knowledge-base retrieval error")

    if has_kb_trace:
        success_detail = "KB retrieval proof passed from trace telemetry."
    else:
        success_detail = "KB retrieval proof passed from recorded runtime evidence."

    return {
        "passed": not failures,
        "run_id": run.get("id"),
        "operation_id": run.get("app_insights_operation_id"),
        "trace_event_count": len(trace_rows),
        "has_knowledge_base_retrieve": has_kb_trace,
        "has_kb_runtime_evidence": has_kb_runtime_evidence,
        "kb_runtime_source_refs": kb_runtime_source_refs[:20],
        "fallback_in_trace": fallback_in_trace,
        "fallback_in_metadata": fallback_in_metadata,
        "kb_error_in_trace": kb_error_in_trace,
        "kb_error_in_metadata": kb_error_in_metadata,
        "detail": "; ".join(failures) if failures else success_detail,
    }


def _verify(
    *,
    api_base_url: str,
    api_key: str,
    terminal_run_json: Path,
    workspace_id: str,
    lookback_hours: int,
    timeout_seconds: float,
    log_query_timeout_seconds: float,
    poll_timeout_seconds: float,
    poll_interval_seconds: float,
) -> dict[str, Any]:
    terminal = _load_terminal_run(terminal_run_json)
    run_id = str(terminal.get("run_id") or "")
    operation_id = str(terminal.get("app_insights_operation_id") or "")
    if not run_id:
        return {"passed": False, "detail": "terminal run evidence did not include run_id"}
    if not operation_id:
        return {
            "passed": False,
            "run_id": run_id,
            "detail": "terminal run evidence did not include app_insights_operation_id",
        }
    run = _load_run_from_api(
        api_base_url=api_base_url,
        api_key=api_key,
        run_id=run_id,
        timeout_seconds=timeout_seconds,
    )
    query = _kql(operation_id, lookback_hours)
    deadline = time.monotonic() + max(0.0, poll_timeout_seconds)
    last_error = ""
    while True:
        try:
            trace_rows = _run_log_query(
                workspace_id=workspace_id,
                query=query,
                timeout_seconds=log_query_timeout_seconds,
            )
        except (
            subprocess.CalledProcessError,
            subprocess.TimeoutExpired,
            json.JSONDecodeError,
        ) as exc:
            last_error = str(exc)
            trace_rows = []
        result = _evaluate(run, trace_rows)
        observed_terminal_failure = (
            result["fallback_in_trace"]
            or result["fallback_in_metadata"]
            or result["kb_error_in_trace"]
        )
        if result["passed"] or observed_terminal_failure or time.monotonic() >= deadline:
            if not result["passed"] and last_error:
                result["log_query_error"] = last_error
            return result
        time.sleep(max(0.0, poll_interval_seconds))


def main() -> int:
    args = _arguments()
    result = _verify(
        api_base_url=args.api_base_url,
        api_key=args.api_key,
        terminal_run_json=args.terminal_run_json,
        workspace_id=args.workspace_id,
        lookback_hours=args.lookback_hours,
        timeout_seconds=args.timeout_seconds,
        log_query_timeout_seconds=args.log_query_timeout_seconds,
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
