from __future__ import annotations

import importlib.util
import json
import math
from pathlib import Path
from typing import Any

from .grading import load_grader, require_score_range
from .schemas import read_jsonl, validate_jsonl

DEFAULT_THRESHOLDS = (0.5, 0.6, 0.7, 0.8, 0.85, 0.9, 0.95)


def calibrate_grader(
    *,
    dataset_path: Path,
    outputs_path: Path,
    grader_path: Path,
    thresholds: list[float] | None = None,
) -> dict[str, Any]:
    dataset = validate_jsonl(dataset_path)
    if not outputs_path.exists():
        raise ValueError(f"outputs file does not exist: {outputs_path}")
    if outputs_path.suffix != ".jsonl":
        raise ValueError(f"outputs file must be JSONL: {outputs_path}")

    selected_thresholds = thresholds or list(DEFAULT_THRESHOLDS)
    for threshold in selected_thresholds:
        if not math.isfinite(threshold) or threshold < 0.0 or threshold > 1.0:
            raise ValueError(f"threshold must be between 0.0 and 1.0: {threshold}")

    rows = read_jsonl(dataset_path)
    outputs = read_jsonl(outputs_path)
    grader = load_grader(grader_path)
    is_gold_answer_ceiling = _is_gold_answer_ceiling(outputs)
    matches, match_details = _match_outputs(rows, outputs)

    scored = []
    for index, output_row, item in matches:
        output_text = _extract_output_text(output_row)
        score = require_score_range(float(grader({"output_text": output_text}, item)))
        usage = output_row.get("usage")
        if usage is not None and not isinstance(usage, dict):
            raise ValueError(f"{_output_identifier(output_row, index)}: usage must be an object")
        latency_ms = output_row.get("latency_ms")
        if latency_ms is not None and (
            not isinstance(latency_ms, (int, float))
            or isinstance(latency_ms, bool)
            or not math.isfinite(latency_ms)
            or latency_ms < 0
        ):
            raise ValueError(
                f"{_output_identifier(output_row, index)}: latency_ms must be non-negative"
            )
        scored.append(
            {
                "id": item.get("id"),
                "output_id": _output_identifier(output_row, index),
                "score": score,
                "has_output_text": bool(output_text.strip()),
                "usage": usage,
                "latency_ms": latency_ms,
            }
        )

    scores = [item["score"] for item in scored]
    pass_rates = {
        str(threshold): _pass_rate(scores=scores, threshold=threshold)
        for threshold in selected_thresholds
    }
    recommended_thresholds = [
        threshold
        for threshold in selected_thresholds
        if 0.25 <= (1.0 - pass_rates[str(threshold)]) <= 0.50
    ] if match_details["matched_complete"] else []

    return {
        "ready": bool(scored) and match_details["matched_complete"],
        "dataset": dataset,
        "outputs": {"path": str(outputs_path), "rows": len(outputs)},
        "grader": {"path": str(grader_path), "bytes": grader_path.stat().st_size},
        "scored_rows": len(scored),
        "scores": scored,
        **match_details,
        "score_summary": _score_summary(scores),
        "pass_rates": pass_rates,
        "recommended_thresholds": recommended_thresholds,
        "recommendation": _recommendation(
            scored,
            match_details["matched_complete"],
            recommended_thresholds,
            is_gold_answer_ceiling=is_gold_answer_ceiling,
        ),
    }


def write_gold_answer_outputs(
    *,
    dataset_path: Path,
    out_path: Path,
) -> dict[str, Any]:
    dataset = validate_jsonl(dataset_path)
    rows = read_jsonl(dataset_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    output_rows = []
    for index, row in enumerate(rows, 1):
        expected_output = row.get("expected_output_json")
        if not isinstance(expected_output, dict):
            raise ValueError(
                f"{dataset_path}:{index}: expected_output_json must be an object"
            )
        output_rows.append(
            {
                "id": row.get("id"),
                "output_text": json.dumps(expected_output, sort_keys=True),
                "metadata": {
                    "source": "expected_output_json",
                    "caliber_source_id": row.get("id"),
                },
            }
        )

    out_path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in output_rows),
        encoding="utf-8",
    )
    return {
        "ready": True,
        "dataset": dataset,
        "out": {"path": str(out_path), "rows": len(output_rows)},
        "source": "expected_output_json",
        "next_step": (
            "Run caliber grader calibrate with this output file to establish the "
            "gold-answer score ceiling before scoring model outputs."
        ),
    }


def build_model_output_calibration_plan(
    *,
    dataset_path: Path,
    grader_path: Path,
    gold_outputs_path: Path,
    teacher_outputs_path: Path,
    base_outputs_path: Path,
    thresholds: list[float] | None = None,
    require_base_signal: bool = False,
) -> dict[str, Any]:
    dataset = validate_jsonl(dataset_path)
    if not grader_path.exists():
        raise ValueError(f"grader file does not exist: {grader_path}")

    outputs = {
        "gold_answer_ceiling": gold_outputs_path,
        "optimized_teacher": teacher_outputs_path,
        "mai_base": base_outputs_path,
    }
    scored: dict[str, Any] = {}
    missing: dict[str, str] = {}
    unavailable: dict[str, Any] = {}

    for name, path in outputs.items():
        if path.exists():
            scored[name] = calibrate_grader(
                dataset_path=dataset_path,
                outputs_path=path,
                grader_path=grader_path,
                thresholds=thresholds,
            )
        elif name == "mai_base":
            base_unavailable = _base_unavailable(path)
            if base_unavailable is not None:
                unavailable[name] = base_unavailable
            else:
                missing[name] = str(path)
        else:
            missing[name] = str(path)

    base_ready = (
        ("mai_base" in scored and scored["mai_base"]["ready"])
        or "mai_base" in unavailable
    )
    base_thresholds = (
        scored.get("mai_base", {}).get("recommended_thresholds", [])
        if scored.get("mai_base", {}).get("ready")
        else []
    )
    base_signal_ready = not require_base_signal or bool(base_thresholds)
    ready_for_threshold_selection = (
        "gold_answer_ceiling" in scored
        and scored["gold_answer_ceiling"]["ready"]
        and scored["gold_answer_ceiling"]["score_summary"]["min"] == 1.0
        and "optimized_teacher" in scored
        and scored["optimized_teacher"]["ready"]
        and base_ready
        and base_signal_ready
    )
    next_step = _model_output_next_step(missing, unavailable)
    if not ready_for_threshold_selection and not missing:
        if require_base_signal and "mai_base" in unavailable:
            next_step = (
                "MAI/base outputs are required for this comparison; do not use the "
                "unavailable-base waiver."
            )
        elif require_base_signal and "mai_base" in scored and not base_thresholds:
            next_step = (
                "No tested threshold yields a 25-50% base-model failure rate; revise "
                "the grader, dataset, or thresholds before RFT submission."
            )
        else:
            next_step = (
                "Resolve incomplete or mismatched output IDs and gold-answer scores "
                "before selecting a threshold."
            )
    return {
        "ready_for_threshold_selection": ready_for_threshold_selection,
        "base_signal_required": require_base_signal,
        "base_recommended_thresholds": base_thresholds,
        "dataset": dataset,
        "grader": {"path": str(grader_path), "bytes": grader_path.stat().st_size},
        "scored": scored,
        "missing_outputs": missing,
        "unavailable_outputs": unavailable,
        "expected_outputs": {name: str(path) for name, path in outputs.items()},
        "next_step": next_step,
    }


def build_threshold_failure_report(
    *,
    dataset_path: Path,
    outputs_path: Path,
    grader_path: Path,
    threshold: float,
    out_path: Path | None = None,
) -> dict[str, Any]:
    if not math.isfinite(threshold) or threshold < 0.0 or threshold > 1.0:
        raise ValueError(f"threshold must be between 0.0 and 1.0: {threshold}")
    dataset = validate_jsonl(dataset_path)
    if not outputs_path.exists():
        raise ValueError(f"outputs file does not exist: {outputs_path}")
    scorer = _load_diagnostic_scorer(grader_path)
    rows = read_jsonl(dataset_path)
    outputs = read_jsonl(outputs_path)
    matches, match_details = _match_outputs(rows, outputs)

    scored: list[dict[str, Any]] = []
    for _, output_row, item in matches:
        output_text = _extract_output_text(output_row)
        score_result = scorer({"output_text": output_text}, item)
        score = require_score_range(float(score_result["score"]))
        output_json = _try_parse_json_object(output_text)
        scored.append(
            {
                "id": item.get("id"),
                "score": score,
                "passed": score >= threshold,
                "diagnostics": score_result.get("diagnostics", {}),
                "expected": {
                    "support": item.get("ground_truth", {}).get("expected_supports"),
                    "citations": item.get("ground_truth", {}).get("acceptable_citations", []),
                    "summary": item.get("ground_truth", {}).get("recommended_action"),
                },
                "output": _output_summary(output_json, output_text),
            }
        )

    failures = [row for row in scored if not row["passed"]]
    result = {
        "ready": bool(scored) and match_details["matched_complete"],
        "threshold": threshold,
        "dataset": dataset,
        "outputs": {"path": str(outputs_path), "rows": len(outputs)},
        "grader": {"path": str(grader_path), "bytes": grader_path.stat().st_size},
        "scored_rows": len(scored),
        "passed_rows": len(scored) - len(failures),
        "failed_rows": len(failures),
        **match_details,
        "score_summary": _score_summary([row["score"] for row in scored]),
        "failures": failures,
        "next_step": (
            _threshold_report_next_step(failures)
            if match_details["matched_complete"]
            else "Resolve incomplete or mismatched output IDs before using this report."
        ),
    }
    if out_path is not None:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
        result["path"] = str(out_path)
    return result


def _match_outputs(
    dataset_rows: list[dict[str, Any]],
    outputs: list[dict[str, Any]],
) -> tuple[list[tuple[int, dict[str, Any], dict[str, Any]]], dict[str, Any]]:
    by_id: dict[str, int] = {}
    duplicate_dataset_ids: list[str] = []
    for index, row in enumerate(dataset_rows):
        if row.get("id") is not None:
            row_id = str(row["id"])
            if row_id in by_id:
                duplicate_dataset_ids.append(row_id)
            by_id[row_id] = index

    matches = []
    unmatched: list[str] = []
    duplicate: list[str] = []
    positional: list[str] = []
    matched_indices: set[int] = set()
    for index, output in enumerate(outputs):
        identifier = _output_identifier(output, index)
        output_id = output.get("id")
        if output_id is None:
            positional.append(identifier)
            row_index = index if index < len(dataset_rows) else None
        else:
            row_index = by_id.get(str(output_id))
        if row_index is None:
            unmatched.append(identifier)
            continue
        if row_index in matched_indices:
            duplicate.append(identifier)
        matched_indices.add(row_index)
        matches.append((index, output, dataset_rows[row_index]))

    missing = [
        str(row.get("id", f"dataset-index:{index}"))
        for index, row in enumerate(dataset_rows)
        if index not in matched_indices
    ]
    return matches, {
        "matched_complete": not (
            unmatched or duplicate or positional or missing or duplicate_dataset_ids
        ),
        "unmatched_outputs": unmatched,
        "duplicate_outputs": duplicate,
        "positional_outputs": positional,
        "missing_dataset_rows": missing,
        "duplicate_dataset_ids": duplicate_dataset_ids,
    }


def _load_diagnostic_scorer(path: Path):
    if not path.exists():
        raise ValueError(f"grader file does not exist: {path}")
    spec = importlib.util.spec_from_file_location("caliber_dynamic_diagnostic_grader", path)
    if spec is None or spec.loader is None:
        raise ValueError(f"could not load grader: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    score_with_diagnostics = getattr(module, "score_with_diagnostics", None)
    if callable(score_with_diagnostics):
        return score_with_diagnostics
    grade = getattr(module, "grade", None)
    if not callable(grade):
        raise ValueError(f"grader must define score_with_diagnostics or grade: {path}")

    def _score(sample: dict[str, Any], item: dict[str, Any]) -> dict[str, Any]:
        score = require_score_range(float(grade(sample, item)))
        return {"score": score, "diagnostics": {"grade": score}}

    return _score


def _try_parse_json_object(value: str) -> dict[str, Any] | None:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _output_summary(output: dict[str, Any] | None, raw_output: str) -> dict[str, Any]:
    if output is None:
        return {
            "parseable_json": False,
            "summary": raw_output[:500],
            "evidence_count": 0,
            "citations": [],
            "supports": [],
        }
    evidence = output.get("evidence")
    evidence_rows = evidence if isinstance(evidence, list) else []
    return {
        "parseable_json": True,
        "summary": str(output.get("summary", ""))[:500],
        "correlation": output.get("correlation"),
        "evidence_count": len(evidence_rows),
        "citations": [
            row.get("source_ref")
            for row in evidence_rows
            if isinstance(row, dict) and row.get("source_ref")
        ],
        "supports": [
            row.get("supports")
            for row in evidence_rows
            if isinstance(row, dict) and row.get("supports")
        ],
        "unsupported": output.get("unsupported"),
    }


def _extract_output_text(output_row: dict[str, Any]) -> str:
    output_text = output_row.get("output_text")
    if isinstance(output_text, str):
        return output_text

    final_message = output_row.get("final_assistant_message")
    if isinstance(final_message, dict):
        content = final_message.get("content")
        if isinstance(content, str):
            return _string_content_text(content)
        if isinstance(content, list):
            return "".join(_content_part_text(part) for part in content)

    sample = output_row.get("sample")
    if isinstance(sample, dict):
        sample_output = sample.get("output")
        if isinstance(sample_output, list):
            assistant_messages = [
                message
                for message in sample_output
                if isinstance(message, dict) and message.get("role") == "assistant"
            ]
            if assistant_messages:
                return _message_content_text(assistant_messages[-1])
    return ""


def _message_content_text(message: dict[str, Any]) -> str:
    content = message.get("content")
    if isinstance(content, str):
        return _string_content_text(content)
    if isinstance(content, list):
        return "".join(_content_part_text(part) for part in content)
    return ""


def _string_content_text(content: str) -> str:
    stripped = content.strip()
    if not stripped:
        return ""
    try:
        decoded = json.loads(stripped)
    except json.JSONDecodeError:
        return content
    if isinstance(decoded, list):
        return "".join(_content_part_text(part) for part in decoded)
    if isinstance(decoded, dict):
        return _content_part_text(decoded)
    return content


def _content_part_text(part: Any) -> str:
    if isinstance(part, str):
        return part
    if not isinstance(part, dict):
        return ""
    text = part.get("text")
    if isinstance(text, str):
        return text
    if isinstance(part.get("content"), str):
        return part["content"]
    return ""


def _output_identifier(output_row: dict[str, Any], index: int) -> str:
    for key in ("id", "output_id", "datasource_item_id"):
        value = output_row.get(key)
        if value is not None:
            return str(value)
    return f"output-index:{index}"


def _is_gold_answer_ceiling(outputs: list[dict[str, Any]]) -> bool:
    if not outputs:
        return False
    for output in outputs:
        metadata = output.get("metadata")
        if not isinstance(metadata, dict) or metadata.get("source") != "expected_output_json":
            return False
    return True


def _pass_rate(*, scores: list[float], threshold: float) -> float:
    if not scores:
        return 0.0
    return round(sum(1 for score in scores if score >= threshold) / len(scores), 3)


def _score_summary(scores: list[float]) -> dict[str, Any]:
    if not scores:
        return {"min": None, "max": None, "avg": None}
    return {
        "min": min(scores),
        "max": max(scores),
        "avg": round(sum(scores) / len(scores), 3),
    }


def _base_unavailable(path: Path) -> dict[str, Any] | None:
    blocker_path = path.with_name(path.name.replace("-output-items.jsonl", "-capture-blocker.json"))
    if blocker_path == path or not blocker_path.exists():
        return None
    try:
        blocker = json.loads(blocker_path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError:
        return None
    if not blocker.get("blocked"):
        return None
    return {
        "path": str(blocker_path),
        "reason": blocker.get("reason") or "Base output capture is unavailable.",
        "model": blocker.get("model"),
        "error_type": blocker.get("error_type"),
    }


def _model_output_next_step(missing: dict[str, str], unavailable: dict[str, Any]) -> str:
    if not missing:
        if "mai_base" in unavailable:
            return (
                "Select a provisional pass_threshold from the gold ceiling and "
                "optimized_teacher lane, then use post-RFT checkpoint evals for the "
                "base-model comparison because MAI base outputs are unavailable."
            )
        return (
            "Compare optimized_teacher and mai_base pass rates against the gold ceiling, "
            "then choose a pass_threshold that preserves teacher parity while leaving "
            "useful base-model failures."
        )
    missing_names = ", ".join(missing)
    return f"Capture missing output-items before selecting pass_threshold: {missing_names}."


def _threshold_report_next_step(failures: list[dict[str, Any]]) -> str:
    if not failures:
        return "No rows failed this threshold; inspect the next stricter threshold if needed."
    return (
        "Inspect failed-row diagnostics. Keep the threshold if failures are real evidence "
        "or boundary misses; adjust only if failures are harmless schema/correlation noise."
    )


def _recommendation(
    scored: list[dict[str, Any]],
    matching_ready: bool,
    recommended_thresholds: list[float],
    *,
    is_gold_answer_ceiling: bool = False,
) -> str:
    if not matching_ready:
        return "Resolve missing, duplicate, or unmatched output IDs before using calibration."
    if not scored:
        return "No outputs were scored; export or capture model outputs first."
    if is_gold_answer_ceiling:
        return (
            "Gold-answer ceiling established. Use model-generated outputs, not answer-key "
            "outputs, to choose a pass_threshold with useful failure signal."
        )
    if recommended_thresholds:
        return (
            "Use a threshold in recommended_thresholds for a 25-50% baseline failure "
            "rate, then inspect failed rows before RFT submission."
        )
    return (
        "No tested threshold produced a 25-50% baseline failure rate; revise the "
        "grader, dataset, or thresholds before RFT submission."
    )
