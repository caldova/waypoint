"""Derive RFT inputs that do not reveal historical labels in model prompts."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

from .rft import _with_expert_evidence_schema_prompt
from .schemas import read_jsonl, validate_jsonl

PREPARATION_VERSION = "contract-policy-no-label-hints-v1"
LABEL_KEYS = {
    "decision_state",
    "expected_decision_state",
    "expected_supports",
    "expected_output_json",
    "expected_behavior",
    "ground_truth",
    "recommended_action",
    "reference_output",
    "scenario_hint",
}


def prepare_rft_prompts(*, source: Path, out: Path) -> dict[str, Any]:
    validate_jsonl(source)
    source_sha = hashlib.sha256(source.read_bytes()).hexdigest()
    rows = [prepare_row(row, source, source_sha) for row in read_jsonl(source)]
    content = "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows)
    if out.exists():
        if out.read_text(encoding="utf-8") != content:
            raise ValueError(f"refusing to overwrite existing prepared data: {out}")
    else:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(content, encoding="utf-8", newline="\n")
    return {
        "source": str(source),
        "source_sha256": source_sha,
        "out": str(out),
        "out_sha256": hashlib.sha256(out.read_bytes()).hexdigest(),
        "rows": len(rows),
        "rows_with_label_hints_removed": sum(
            bool(row["metadata"]["prompt_preparation"]["removed_paths"]) for row in rows
        ),
        "preparation_version": PREPARATION_VERSION,
    }


def prepare_row(row: dict[str, Any], source: Path, source_sha: str) -> dict[str, Any]:
    prepared = copy.deepcopy(row)
    metadata = prepared.get("metadata")
    if not isinstance(metadata, dict):
        raise ValueError(f"{row.get('id')}: metadata must be an object")
    if "prompt_preparation" in metadata:
        raise ValueError(f"{row.get('id')}: input is already prepared")
    messages = prepared.get("messages")
    if not isinstance(messages, list) or not messages:
        raise ValueError(f"{row.get('id')}: messages must be a non-empty list")
    removed: list[str] = []
    visible_run_ids: set[str] = set()
    for message in messages:
        if not isinstance(message, dict):
            raise ValueError(f"{row.get('id')}: messages must contain objects")
        if message.get("role") != "user":
            continue
        try:
            payload = json.loads(message.get("content", ""))
        except (json.JSONDecodeError, TypeError) as exc:
            raise ValueError(f"{row.get('id')}: user message must contain JSON") from exc
        if not isinstance(payload, dict):
            raise ValueError(f"{row.get('id')}: user message JSON must be an object")
        _strip_labels(payload, "", removed)
        line = payload.get("line")
        if isinstance(line, dict):
            for key in ("issue_category", "scenario_id"):
                if key in line:
                    del line[key]
                    removed.append(f"line.{key}")
        supplier = payload.get("supplier")
        if isinstance(supplier, dict) and "risk_examples" in supplier:
            del supplier["risk_examples"]
            removed.append("supplier.risk_examples")
        _collect_run_ids(payload, visible_run_ids)
        message["content"] = json.dumps(payload, indent=2, sort_keys=True)
    prepared["messages"] = _with_expert_evidence_schema_prompt(messages)
    expected = prepared.get("expected_output_json")
    expected_correlation = expected.get("correlation") if isinstance(expected, dict) else None
    normalized_run_id = False
    if isinstance(expected_correlation, dict):
        source_run = expected_correlation.get("waypoint_run_id")
        if source_run and source_run != "unknown" and source_run not in visible_run_ids:
            expected_correlation["waypoint_run_id"] = "unknown"
            if not isinstance(prepared.get("expected"), dict):
                raise ValueError(f"{row.get('id')}: expected must be an object")
            prepared["expected"]["text"] = json.dumps(expected, sort_keys=True)
            normalized_run_id = True
    metadata["prompt_preparation"] = {
        "version": PREPARATION_VERSION,
        "source_path": str(source),
        "source_sha256": source_sha,
        "source_id": row.get("id"),
        "removed_paths": sorted(removed),
        "unprovided_run_id_normalized_to_unknown": normalized_run_id,
    }
    return prepared


def _strip_labels(value: Any, prefix: str, removed: list[str]) -> None:
    if isinstance(value, dict):
        for key in list(value):
            path = f"{prefix}.{key}" if prefix else key
            if key in LABEL_KEYS:
                del value[key]
                removed.append(path)
            else:
                _strip_labels(value[key], path, removed)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _strip_labels(item, f"{prefix}[{index}]", removed)


def _collect_run_ids(value: Any, result: set[str]) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if key in {"run_id", "waypoint_run_id"} and isinstance(item, str):
                result.add(item)
            else:
                _collect_run_ids(item, result)
    elif isinstance(value, list):
        for item in value:
            _collect_run_ids(item, result)
