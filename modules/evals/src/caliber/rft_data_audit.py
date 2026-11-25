"""Pre-submit audit for contract-policy RFT datasets.

Checks schema/RFT shape, duplicates, and leakage between training splits and an
independently held-out evaluation split, then writes a SHA-256 provenance
manifest. Read-only over the inputs: it never rewrites dataset rows or labels.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from collections import Counter
from pathlib import Path
from typing import Any

from .grading import load_grader, require_score_range
from .schemas import read_jsonl, validate_jsonl

# Leakage keys: any overlap between a training split and the held-out eval split
# on these fields means the eval is no longer independent.
LEAKAGE_KEYS = ("supplier_id", "supplier_name", "invoice_id", "line_id", "scenario_id")
# Foundry reports FineTuneTokensMaxValuePerExample=196608 for mai-code-2-flash
# (az cognitiveservices model list, swedencentral/eastus). Chars/4 is only a
# rough estimate, not an upper bound; verify the actual token count separately.
DEFAULT_MAX_TOKENS_PER_EXAMPLE = 196_608
CHARS_PER_TOKEN_ESTIMATE = 4


def audit_rft_datasets(
    *,
    train_path: Path,
    validation_path: Path,
    eval_paths: list[Path],
    grader_path: Path | None = None,
    max_tokens_per_example: int = DEFAULT_MAX_TOKENS_PER_EXAMPLE,
    out: Path | None = None,
) -> dict[str, Any]:
    splits: dict[str, list[tuple[Path, dict[str, Any]]]] = {
        "train": [(train_path, row) for row in _read(train_path)],
        "validation": [(validation_path, row) for row in _read(validation_path)],
        "eval": [(path, row) for path in eval_paths for row in _read(path)],
    }
    grader = load_grader(grader_path) if grader_path is not None else None

    errors: list[str] = []
    warnings: list[str] = []
    split_stats: dict[str, Any] = {}
    keys: dict[str, dict[str, set[str]]] = {}
    prompt_hashes: dict[str, dict[str, str]] = {}
    ids: Counter[str] = Counter()

    for split, rows in splits.items():
        if not rows:
            errors.append(f"{split}: no rows")
        keys[split] = {key: set() for key in LEAKAGE_KEYS}
        prompt_hashes[split] = {}
        supports: Counter[str] = Counter()
        max_tokens = 0
        no_distractor = 0
        empty_unsupported = 0
        gold_scores: list[float] = []
        missing_keys: Counter[str] = Counter()
        for index, (path, row) in enumerate(rows, 1):
            where = f"{split}:{path.name}:{index}"
            row_errors = _row_shape_errors(row, where)
            errors.extend(row_errors)
            if row_errors:
                continue
            row_id = str(row.get("id"))
            ids[row_id] += 1
            metadata = row.get("metadata", {}) if isinstance(row.get("metadata"), dict) else {}
            for key in LEAKAGE_KEYS:
                value = _leakage_value(row, metadata, key)
                if value:
                    keys[split][key].add(value)
                else:
                    missing_keys[key] += 1
            digest = _prompt_digest(row)
            if digest in prompt_hashes[split]:
                errors.append(
                    f"{where}: duplicate normalized prompt of {prompt_hashes[split][digest]}"
                )
            prompt_hashes[split].setdefault(digest, row_id)
            ground_truth = row.get("ground_truth")
            ground_truth = ground_truth if isinstance(ground_truth, dict) else {}
            supports[str(ground_truth.get("expected_supports"))] += 1
            max_tokens = max(max_tokens, _estimated_tokens(row))
            retrieved = _retrieved_refs(row)
            acceptable_values = ground_truth.get("acceptable_citations", [])
            acceptable = (
                {value for value in acceptable_values if isinstance(value, str)}
                if isinstance(acceptable_values, list)
                else set()
            )
            if retrieved is not None:
                if not acceptable <= retrieved:
                    errors.append(f"{where}: acceptable_citations not all in retrieved_context")
                if retrieved == acceptable:
                    no_distractor += 1
            expected_output = row.get("expected_output_json", {})
            if isinstance(expected_output, dict) and not expected_output.get("unsupported"):
                empty_unsupported += 1
            if grader is not None and isinstance(expected_output, dict):
                score = require_score_range(
                    float(grader({"output_text": json.dumps(expected_output, sort_keys=True)}, row))
                )
                gold_scores.append(score)
                if score < 1.0:
                    errors.append(f"{where}: gold answer scores {score} (< 1.0)")
        if max_tokens > max_tokens_per_example:
            errors.append(
                f"{split}: estimated {max_tokens} tokens exceeds {max_tokens_per_example}"
            )
        split_stats[split] = {
            "rows": len(rows),
            "files": sorted({str(path) for path, _ in rows}),
            "expected_supports": dict(sorted(supports.items())),
            "distinct": {key: len(values) for key, values in keys[split].items()},
            "rows_missing_leakage_key": dict(missing_keys),
            "max_estimated_tokens": max_tokens,
            "rows_without_distractor_context": no_distractor,
            "rows_with_empty_unsupported": empty_unsupported,
            "gold_min_score": min(gold_scores) if gold_scores else None,
        }
        if rows and no_distractor == len(rows):
            warnings.append(
                f"{split}: every row's retrieved_context equals its acceptable citations, so "
                "citation selection under distractors is untested."
            )
        if rows and empty_unsupported == len(rows):
            warnings.append(
                f"{split}: every gold answer has unsupported=[], so evidence-gap reporting "
                "is untested."
            )
        if len(supports) == 1 and rows:
            warnings.append(f"{split}: single expected_supports label {dict(supports)}")
        if missing_keys:
            warnings.append(f"{split}: incomplete leakage identity fields: {dict(missing_keys)}")

    duplicate_ids = sorted(row_id for row_id, count in ids.items() if count > 1)
    if duplicate_ids:
        errors.append(f"duplicate ids across splits: {duplicate_ids[:10]}")

    leakage: dict[str, Any] = {}
    for left, right in (("train", "eval"), ("validation", "eval"), ("train", "validation")):
        pair: dict[str, Any] = {}
        for key in LEAKAGE_KEYS:
            overlap = sorted(keys[left][key] & keys[right][key])
            pair[key] = overlap[:20]
            if overlap:
                errors.append(f"leakage {left}->{right} on {key}: {overlap[:5]}")
        prompt_overlap = sorted(set(prompt_hashes[left]) & set(prompt_hashes[right]))
        pair["normalized_prompt_overlap"] = len(prompt_overlap)
        if prompt_overlap:
            errors.append(f"{left} and {right} share {len(prompt_overlap)} normalized prompts")
        leakage[f"{left}_vs_{right}"] = pair

    eval_rows = len(splits["eval"])
    if eval_rows < 50:
        warnings.append(
            f"held-out eval has {eval_rows} rows; one row is {100 / max(eval_rows, 1):.1f} "
            "points of accuracy, too coarse to detect small regressions."
        )

    result = {
        "ready": not errors,
        "errors": errors,
        "warnings": warnings,
        "splits": split_stats,
        "leakage": leakage,
        "provenance": _provenance(
            [train_path, validation_path, *eval_paths]
            + ([grader_path] if grader_path is not None else []),
            rows=[row for rows in splits.values() for _, row in rows],
        ),
        "note": (
            "Local audit only. Token counts are estimates, not limits or upper bounds. It "
            "does not upload data or prove the trainer reads rows the same way; run remote "
            "grader validation before any job."
        ),
    }
    if out is not None:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
        result["path"] = str(out)
    return result


def _read(path: Path) -> list[dict[str, Any]]:
    validate_jsonl(path)
    return read_jsonl(path)


def _row_shape_errors(row: dict[str, Any], where: str) -> list[str]:
    errors = []
    messages = row.get("messages")
    if not isinstance(messages, list) or not messages:
        return [f"{where}: messages must be a non-empty list"]
    if any(not isinstance(message, dict) for message in messages):
        return [f"{where}: messages must contain objects"]
    for message in messages:
        if message.get("role") not in {"system", "developer", "user", "assistant"}:
            errors.append(f"{where}: message role is invalid")
        if not isinstance(message.get("content"), str) or not message["content"].strip():
            errors.append(f"{where}: message content must be a non-empty string")
    if messages[-1].get("role") != "user":
        errors.append(f"{where}: last message must be a user turn")
    if any(message.get("role") == "assistant" for message in messages):
        errors.append(f"{where}: RFT rows must not include assistant messages")
    if not row.get("id"):
        errors.append(f"{where}: missing id")
    ground_truth = row.get("ground_truth")
    if not isinstance(ground_truth, dict):
        errors.append(f"{where}: missing ground_truth")
    else:
        citations = ground_truth.get("acceptable_citations")
        if (
            not isinstance(citations, list)
            or not citations
            or any(not isinstance(value, str) or not value.strip() for value in citations)
            or len(citations) != len(set(citations))
        ):
            errors.append(f"{where}: ground_truth.acceptable_citations is invalid or duplicated")
        support = ground_truth.get("expected_supports")
        if not isinstance(support, str) or support not in {
            "approve", "recover", "escalate", "review", "unknown"
        }:
            errors.append(f"{where}: ground_truth.expected_supports is invalid")
    if not isinstance(row.get("expected_output_json"), dict):
        errors.append(f"{where}: expected_output_json must be an object")
    metadata = row.get("metadata")
    if not isinstance(metadata, dict) or not metadata.get("invoice_id"):
        errors.append(f"{where}: metadata.invoice_id is required")
    return errors


def _prompt_digest(row: dict[str, Any]) -> str:
    normalized = [
        [message.get("role"), re.sub(r"\s+", " ", str(message.get("content", ""))).strip().lower()]
        for message in row.get("messages", [])
        if isinstance(message, dict)
    ]
    return hashlib.sha256(json.dumps(normalized).encode("utf-8")).hexdigest()


def _estimated_tokens(row: dict[str, Any]) -> int:
    chars = sum(
        len(str(message.get("content", "")))
        for message in row.get("messages", [])
        if isinstance(message, dict)
    )
    chars += len(json.dumps(row.get("expected_output_json", {})))
    return chars // CHARS_PER_TOKEN_ESTIMATE + 1


def _retrieved_refs(row: dict[str, Any]) -> set[str] | None:
    context = row.get("retrieved_context")
    sections = context.get("contract_policy_sections") if isinstance(context, dict) else context
    if not isinstance(sections, list):
        return None
    return {
        section["source_ref"]
        for section in sections
        if isinstance(section, dict) and isinstance(section.get("source_ref"), str)
    }


def _leakage_value(row: dict[str, Any], metadata: dict[str, Any], key: str) -> str:
    value = metadata.get(key)
    if key == "supplier_name" and not value:
        for message in reversed(row.get("messages", [])):
            if not isinstance(message, dict) or message.get("role") != "user":
                continue
            try:
                payload = json.loads(message.get("content", ""))
            except (TypeError, json.JSONDecodeError):
                continue
            if not isinstance(payload, dict):
                continue
            supplier = payload.get("supplier")
            invoice = payload.get("invoice")
            if isinstance(supplier, dict):
                value = supplier.get("name")
            if not value and isinstance(invoice, dict):
                value = invoice.get("supplier_name")
            if value:
                break
    if not isinstance(value, str):
        return ""
    return re.sub(r"\s+", " ", value).strip().casefold()


def _provenance(paths: list[Path], *, rows: list[dict[str, Any]]) -> dict[str, Any]:
    files = {}
    for path in paths:
        data = path.read_bytes()
        files[str(path)] = {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
    metadata = [row.get("metadata", {}) for row in rows if isinstance(row.get("metadata"), dict)]
    return {
        "files": files,
        "git_commit": _git_commit(paths[0].parent),
        "label_sources": sorted({str(m.get("label_source")) for m in metadata}),
        "review_statuses": sorted({str(m.get("review_status")) for m in metadata}),
        "upstream_source_refs": sorted(
            {
                str(m.get("ledgerfield_source_ref"))
                for m in metadata
                if m.get("ledgerfield_source_ref")
            }
        ),
    }


def _git_commit(cwd: Path) -> str | None:
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return completed.stdout.strip() or None
