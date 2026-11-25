"""Strictly local readiness checks for the contract-policy RFT package."""

from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any

from .contract_policy import _load_section_context
from .contract_policy_challenge import corpus_source_sha256
from .contract_policy_evidence_only import EVIDENCE_ONLY_VERSION
from .contract_policy_evidence_only import LABEL_SOURCE as EVIDENCE_ONLY_LABEL_SOURCE
from .grader_robustness import build_perturbations, run_grader_robustness
from .grading import load_grader
from .rft import (
    GRADER_VALIDATION_VARIANTS,
    KNOWN_HYPERPARAMETERS,
    _grader_version,
    _package_split,
    _rft_reward_grader_source,
    _self_contained_grader_source,
    _sha256_file,
    _submit_template,
    _to_rft_row,
    build_grader_validation_suite,
)
from .rft_data_audit import audit_rft_datasets
from .rft_prompt_preparation import PREPARATION_VERSION, prepare_row
from .schemas import read_jsonl

_DIRECTIVE_VERBS = (
    r"(?:pay|approve|dispute|reject|deny|hold|withhold|short-pay|reconcile|recover|"
    r"escalate|request|release\s+payment|recalculate|reprice|re-price|rebill|credit|"
    r"refund|deduct|offset|present|route)"
)
_DIRECTIVE = re.compile(
    r"(?:^\s*|[.!?;:]\s*|\b(?:and|or|then|please)\s+)" + _DIRECTIVE_VERBS + r"\b"
    r"|\b(?:should|must|recommend(?:s|ed)?(?:\s+to)?|we\s+will|i\s+will|you\s+should)\s+"
    + _DIRECTIVE_VERBS + r"\b",
    re.IGNORECASE,
)
_CHALLENGE_LABEL_SOURCE = "synthetic_counterfactual_from_corpus_clauses"


def run_offline_preflight(
    *,
    train_path: Path,
    validation_path: Path,
    eval_paths: list[Path],
    challenge_path: Path,
    grader_path: Path,
    package_dir: Path,
    grader_suite_path: Path,
    corpus_path: Path,
    source_root: Path,
    out: Path,
) -> dict[str, Any]:
    """Audit local files only; this function cannot upload, invoke, or submit."""
    if out.exists():
        raise ValueError(f"refusing to overwrite an existing preflight report: {out}")

    checks: list[dict[str, Any]] = []
    errors: list[str] = []
    warnings: list[str] = []
    reports: dict[str, Any] = {}

    def record(name: str, issues: list[str], details: dict[str, Any] | None = None) -> None:
        checks.append({"name": name, "ok": not issues, "issues": issues, **(details or {})})
        errors.extend(f"{name}: {issue}" for issue in issues)

    all_eval_paths = [*eval_paths, challenge_path]
    all_paths = [train_path, validation_path, *all_eval_paths]
    try:
        audit = audit_rft_datasets(
            train_path=train_path,
            validation_path=validation_path,
            eval_paths=all_eval_paths,
            grader_path=grader_path,
        )
        audit_issues = list(audit["errors"])
        for split, stats in audit["splits"].items():
            if stats["rows_missing_leakage_key"]:
                audit_issues.append(
                    f"{split} has missing leakage keys: {stats['rows_missing_leakage_key']}"
                )
        record("dataset_audit", audit_issues, {"splits": audit["splits"]})
        warnings.extend(audit["warnings"])
        reports["dataset_provenance"] = audit["provenance"]
    except (OSError, ValueError, TypeError, SyntaxError, ImportError) as exc:
        record("dataset_audit", [f"{type(exc).__name__}: {exc}"])

    try:
        provenance_issues, candidate = _check_candidate(challenge_path, corpus_path)
        record("candidate_provenance", provenance_issues, candidate)
        reports["candidate"] = candidate
    except (OSError, ValueError, TypeError, KeyError) as exc:
        record("candidate_provenance", [f"{type(exc).__name__}: {exc}"])

    try:
        corpus_issues, corpus = _check_corpus_alignment(all_paths, corpus_path)
        record("corpus_alignment", corpus_issues, corpus)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        record("corpus_alignment", [f"{type(exc).__name__}: {exc}"])

    try:
        row_issues = _check_reference_rows(all_paths, source_root)
        record("reference_consistency", row_issues)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        record("reference_consistency", [f"{type(exc).__name__}: {exc}"])

    try:
        boundary_issues, boundary = _check_advisory_references(all_paths)
        record("advisory_reference_boundary", boundary_issues, boundary)
        reports["reference_boundary"] = boundary
    except (OSError, ValueError, TypeError, KeyError) as exc:
        record("advisory_reference_boundary", [f"{type(exc).__name__}: {exc}"])

    try:
        package_issues, package = _check_package(
            train_path=train_path,
            validation_path=validation_path,
            grader_path=grader_path,
            package_dir=package_dir,
            grader_suite_path=grader_suite_path,
        )
        record("package_consistency", package_issues, package)
        reports["package"] = package
    except (OSError, ValueError, TypeError, KeyError, SyntaxError, ImportError) as exc:
        record("package_consistency", [f"{type(exc).__name__}: {exc}"])

    try:
        manifest = json.loads((package_dir / "manifest.json").read_text(encoding="utf-8"))
        threshold = manifest["pass_threshold"]
        if not isinstance(threshold, (float, int)) or isinstance(threshold, bool):
            raise ValueError("package pass_threshold must be numeric")
        robustness = run_grader_robustness(
            dataset_paths=all_paths,
            grader_path=grader_path,
            pass_threshold=float(threshold),
        )
        max_bad = max(
            stat["max"]
            for stat in robustness["perturbations"].values()
            if stat["expect"] == "fail"
        )
        issues = []
        if not robustness["ready"]:
            issues.append(f"{robustness['violation_count']} perturbations violated expectations")
        if max_bad > 0.5:
            issues.append(f"known-bad perturbation scored above 0.5: {max_bad}")
        details = {
            "rows": robustness["rows"],
            "variants": len(robustness["perturbations"]),
            "samples": sum(stat["n"] for stat in robustness["perturbations"].values()),
            "violations": robustness["violation_count"],
            "max_known_bad_score": max_bad,
        }
        record("grader_robustness", issues, details)
        reports["grader_scores"] = robustness["perturbations"]
    except (OSError, ValueError, TypeError, KeyError, SyntaxError, ImportError) as exc:
        record("grader_robustness", [f"{type(exc).__name__}: {exc}"])

    try:
        parity_issues, parity = _check_trainer_parity(
            dataset_paths=all_paths,
            grader_path=grader_path,
            package_dir=package_dir,
        )
        record("trainer_wrapper_parity", parity_issues, parity)
    except (OSError, ValueError, TypeError, KeyError, SyntaxError, ImportError) as exc:
        record("trainer_wrapper_parity", [f"{type(exc).__name__}: {exc}"])

    result = {
        "local_checks_passed": not errors,
        "ready_to_run_meter": False,
        "remote_checks_run": False,
        "live_side_effects": "none",
        "checks": checks,
        "errors": errors,
        "warnings": warnings,
        "reports": reports,
        "unresolved_gates": [
            "Domain-owner review of the v3 evidence-only labels (claims, gaps, summaries) and "
            "of rows with support_review_flag, which carry historical supports unchanged.",
            "Human review and acceptance of the synthetic held-out candidate labels and evidence.",
            "Human review of the synthetic v3 distractor, approval-evidence, and "
            "missing-evidence coverage rows.",
            "Approved base and teacher outputs and real-output grader calibration.",
            "Remote positive/negative grader validation and threshold-placement acceptance.",
            "Verified model availability, quota, tokenizer limits, and current pricing.",
            "Current authorization, budget, and cleanup plan for billable validation, "
            "deployment, and training.",
        ],
        "note": (
            "Synthetic perturbations and local wrapper parity do not demonstrate model quality "
            "or remote trainer parity. Historical source labels have not been "
            "independently reviewed."
        ),
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(result, handle, indent=2, sort_keys=True)
        handle.write("\n")
    result["path"] = str(out)
    return result


def _check_corpus_alignment(
    paths: list[Path], corpus_path: Path
) -> tuple[list[str], dict[str, Any]]:
    root = corpus_path.resolve()
    suppliers_path = root / "data" / "suppliers" / "suppliers.json"
    suppliers = {item["id"]: item["name"] for item in json.loads(
        suppliers_path.read_text(encoding="utf-8")
    )}
    issues: list[str] = []
    checked = 0
    sections_checked = 0
    section_cache: dict[tuple[str, str], dict[str, Any]] = {}
    for path in paths:
        for row in read_jsonl(path):
            checked += 1
            identity = f"{path.name}:{row.get('id')}"
            metadata = row["metadata"]
            supplier_id = metadata.get("supplier_id")
            messages = [m for m in row["messages"] if m.get("role") == "user"]
            if len(messages) != 1:
                issues.append(f"{identity}: expected exactly one user message")
                continue
            payload = json.loads(messages[0]["content"])
            supplier = payload.get("supplier", {})
            invoice = payload.get("invoice", {})
            if (
                supplier_id not in suppliers
                or supplier.get("id") != supplier_id
                or supplier.get("name") != suppliers.get(supplier_id)
                or invoice.get("supplier_id") != supplier_id
                or (
                    "supplier_name" in invoice
                    and invoice["supplier_name"] != suppliers.get(supplier_id)
                )
                or (
                    "supplier_name" in metadata
                    and metadata["supplier_name"] != suppliers.get(supplier_id)
                )
            ):
                issues.append(f"{identity}: supplier identity does not match corpus")
            if invoice.get("invoice_id") != metadata.get("invoice_id"):
                issues.append(f"{identity}: prompt invoice differs from metadata")
            sections = row["retrieved_context"]["contract_policy_sections"]
            if not sections:
                issues.append(f"{identity}: retrieved context is empty")
            if payload.get("retrieved_context") != sections:
                issues.append(f"{identity}: prompt and reference retrieved contexts differ")
            for section in sections:
                sections_checked += 1
                document = section["document"]
                section_name = section["section"]
                source = (root / document).resolve()
                if not source.is_relative_to(root) or not source.is_file():
                    issues.append(f"{identity}: corpus source missing or outside root: {document}")
                    continue
                key = (document, section_name)
                if key not in section_cache:
                    section_cache[key] = _load_section_context(
                        ledgerfield_root=root,
                        evidence_ref={"document": document, "section": section_name},
                    )
                if section != section_cache[key]:
                    issues.append(f"{identity}: retrieved section differs from corpus: {document}")
    return issues, {"rows": checked, "sections": sections_checked}


def _check_candidate(path: Path, corpus_path: Path) -> tuple[list[str], dict[str, Any]]:
    rows = read_jsonl(path)
    suppliers_path = corpus_path / "data" / "suppliers" / "suppliers.json"
    suppliers = {item["id"]: item["name"] for item in json.loads(suppliers_path.read_text("utf-8"))}
    issues: list[str] = []
    statuses: set[str] = set()
    supports: set[str] = set()
    gaps = distractors = 0
    for row in rows:
        identity = str(row.get("id"))
        metadata = row["metadata"]
        statuses.add(metadata.get("review_status", "missing"))
        supports.add(row["ground_truth"]["expected_supports"])
        gaps += bool(row["expected_output_json"]["unsupported"])
        if not _challenge_label_provenance(metadata):
            issues.append(f"{identity}: missing synthetic label provenance")
        if not metadata.get("expected_answer_derivation"):
            issues.append(f"{identity}: missing expected-answer derivation")
        if metadata.get("source_hash_format") != "sha256_utf8_lf":
            issues.append(f"{identity}: unknown corpus source hash format")
        if suppliers.get(metadata.get("supplier_id")) != metadata.get("supplier_name"):
            issues.append(f"{identity}: supplier identity does not match the source corpus")
        sources = metadata.get("source_sha256")
        if not isinstance(sources, dict) or not sources:
            issues.append(f"{identity}: missing source hashes")
            continue
        if "data/suppliers/suppliers.json" not in sources:
            issues.append(f"{identity}: supplier source lacks a hash")
        root = corpus_path.resolve()
        safe_sources = set()
        for relative, expected_hash in sources.items():
            source = (root / relative).resolve()
            if not source.is_relative_to(root) or not source.is_file():
                issues.append(f"{identity}: source path is absent or outside corpus: {relative}")
            else:
                safe_sources.add(relative)
                if corpus_source_sha256(source) != expected_hash:
                    issues.append(f"{identity}: source hash changed: {relative}")
        sections = row["retrieved_context"]["contract_policy_sections"]
        acceptable = set(row["ground_truth"]["acceptable_citations"])
        distractors += any(section["source_ref"] not in acceptable for section in sections)
        for section in sections:
            if section["document"] not in safe_sources:
                issues.append(f"{identity}: retrieved source is absent or unhashed")
                continue
            actual = _load_section_context(
                ledgerfield_root=corpus_path,
                evidence_ref={"document": section["document"], "section": section["section"]},
            )
            if section != actual:
                issues.append(f"{identity}: retrieved section no longer matches corpus")
        payload = json.loads(row["messages"][-1]["content"])
        if payload.get("retrieved_context") != sections:
            issues.append(f"{identity}: prompt and reference retrieved contexts differ")
        if payload.get("supplier", {}).get("id") != metadata.get("supplier_id"):
            issues.append(f"{identity}: prompt supplier differs from metadata")
        if payload.get("invoice", {}).get("invoice_id") != metadata.get("invoice_id"):
            issues.append(f"{identity}: prompt invoice differs from metadata")
    if not rows:
        issues.append("challenge dataset is empty")
    if "approve" not in supports:
        issues.append("challenge dataset lacks an approve-support case")
    if not gaps:
        issues.append("challenge dataset lacks an expected evidence gap")
    if not distractors:
        issues.append("challenge dataset lacks retrieved distractor context")
    if "missing" in statuses:
        issues.append("challenge dataset has rows with no review status")
    return issues, {
        "path": str(path),
        "sha256": _sha256_file(path),
        "rows": len(rows),
        "supplier_names": sorted({row["metadata"]["supplier_name"] for row in rows}),
        "supports": sorted(supports),
        "rows_with_expected_gap": gaps,
        "rows_with_distractors": distractors,
        "review_statuses": sorted(statuses),
    }


def _challenge_label_provenance(metadata: dict[str, Any]) -> bool:
    if metadata.get("label_source") == _CHALLENGE_LABEL_SOURCE:
        return True
    reference = metadata.get("evidence_only_reference")
    historical = metadata.get("historical_reference")
    return (
        metadata.get("label_source") == EVIDENCE_ONLY_LABEL_SOURCE
        and isinstance(reference, dict)
        and reference.get("version") == EVIDENCE_ONLY_VERSION
        and isinstance(historical, dict)
        and historical.get("label_source") == _CHALLENGE_LABEL_SOURCE
    )


def _check_reference_rows(paths: list[Path], source_root: Path) -> list[str]:
    issues = []
    allowed_root = source_root.resolve()
    source_cache: dict[Path, tuple[str, dict[str, dict[str, Any]]]] = {}
    for path in paths:
        for row in read_jsonl(path):
            identity = f"{path.name}:{row.get('id')}"
            expected = row["expected_output_json"]
            if json.loads(row["expected"]["text"]) != expected:
                issues.append(f"{identity}: expected.text differs from expected_output_json")
            metadata = row["metadata"]
            if not all(metadata.get(key) for key in ("label_source", "review_status")):
                issues.append(f"{identity}: missing label provenance or review status")
            preparation = metadata.get("prompt_preparation")
            if (
                not isinstance(preparation, dict)
                or preparation.get("version") != PREPARATION_VERSION
            ):
                issues.append(f"{identity}: missing label-hint-free prompt preparation")
            else:
                source_path = Path(preparation["source_path"])
                resolved = source_path.resolve()
                if not resolved.is_relative_to(allowed_root) or not resolved.is_file():
                    issues.append(
                        f"{identity}: preparation source is absent or outside source root"
                    )
                else:
                    if resolved not in source_cache:
                        source_cache[resolved] = (
                            _sha256_file(resolved),
                            {item["id"]: item for item in read_jsonl(resolved)},
                        )
                    source_hash, source_rows = source_cache[resolved]
                    source_row = source_rows.get(preparation.get("source_id"))
                    if source_hash != preparation.get("source_sha256") or source_row is None:
                        issues.append(f"{identity}: preparation source hash or row does not match")
                    elif prepare_row(source_row, source_path, source_hash) != row:
                        issues.append(
                            f"{identity}: prepared row differs from its source transformation"
                        )
            if expected.get("invoice_id") != metadata.get("invoice_id"):
                issues.append(f"{identity}: expected invoice differs from metadata")
            ground_truth = row["ground_truth"]
            if any(
                evidence.get("supports") != ground_truth["expected_supports"]
                for evidence in expected["evidence"]
            ):
                issues.append(f"{identity}: reference support differs from ground truth")
            if {e["source_ref"] for e in expected["evidence"]} != set(
                ground_truth["acceptable_citations"]
            ):
                issues.append(f"{identity}: reference citations differ from acceptable citations")
    return issues


def _check_advisory_references(
    paths: list[Path],
) -> tuple[list[str], dict[str, Any]]:
    checked = 0
    flagged = 0
    by_file: dict[str, int] = {}
    examples = []
    for path in paths:
        file_count = 0
        for row in read_jsonl(path):
            checked += 1
            expected = row["expected_output_json"]
            values = [
                expected["summary"],
                row["ground_truth"].get("recommended_action"),
                row["ground_truth"].get("reference_summary"),
            ]
            values.extend(evidence["claim"] for evidence in expected["evidence"])
            values.extend(expected.get("unsupported", []))
            matches = [
                value for value in values if isinstance(value, str) and _DIRECTIVE.search(value)
            ]
            if matches:
                flagged += 1
                file_count += 1
                if len(examples) < 8:
                    examples.append({"path": str(path), "id": row.get("id"), "text": matches[0]})
        by_file[str(path)] = file_count
    issues = (
        [
            f"{flagged} of {checked} reference rows contain apparent finance-disposition "
            "directives; reconcile the labels and grader with the evidence-only task."
        ]
        if flagged
        else []
    )
    return issues, {
        "rows_checked": checked,
        "rows_with_apparent_directives": flagged,
        "rows_by_file": by_file,
        "examples": examples,
        "note": (
            "Conservative phrase screen, not semantic review: it can miss other unsafe "
            "directives and does not establish that unflagged references are safe."
        ),
    }


def _check_package(
    *,
    train_path: Path,
    validation_path: Path,
    grader_path: Path,
    package_dir: Path,
    grader_suite_path: Path,
) -> tuple[list[str], dict[str, Any]]:
    manifest = json.loads((package_dir / "manifest.json").read_text(encoding="utf-8"))
    issues: list[str] = []
    sources = {"train": train_path, "validation": validation_path, "grader": grader_path}
    for name, path in sources.items():
        if Path(manifest["source"][name]).resolve() != path.resolve():
            issues.append(f"{name} source path differs from manifest")
        if manifest["source_sha256"][name] != _sha256_file(path):
            issues.append(f"{name} source hash differs from manifest")
    artifacts = manifest["artifacts"]
    artifact_paths = {
        name: Path(artifacts[name]["path"])
        for name in ("train", "validation", "grader", "endpoint_grader")
    }
    artifact_paths.update({name: Path(artifacts[name]) for name in ("job_spec", "submit_template")})
    for name, path in artifact_paths.items():
        if path.resolve().parent != package_dir.resolve():
            issues.append(f"{name} artifact is not inside the package directory")
        if manifest["artifact_sha256"][name] != _sha256_file(path):
            issues.append(f"{name} artifact hash differs from manifest")
    response = artifacts["response_format"]["path"]
    if response:
        response_path = Path(response)
        if response_path.resolve().parent != package_dir.resolve():
            issues.append("response format artifact is not inside the package directory")
        if manifest["artifact_sha256"]["response_format"] != _sha256_file(response_path):
            issues.append("response format hash differs from manifest")
    elif manifest["artifact_sha256"]["response_format"] is not None:
        issues.append("omitted response format unexpectedly has an artifact hash")

    for split, source in (("train", train_path), ("validation", validation_path)):
        expected = _package_split(source_path=source, split=split)
        if read_jsonl(artifact_paths[split]) != expected["rows"]:
            issues.append(f"packaged {split} rows differ from source transformation")
        if artifacts[split]["rows"] != expected["count"]:
            issues.append(f"packaged {split} row count differs from manifest")
    validation_count = len(read_jsonl(validation_path))
    hyperparameters = manifest.get("hyperparameters") or {}
    if not isinstance(hyperparameters, dict):
        raise ValueError("manifest hyperparameters must be an object")
    issues.extend(_hyperparameter_errors(hyperparameters))
    sample_count = hyperparameters.get("eval_samples")
    if (
        not isinstance(sample_count, int)
        or isinstance(sample_count, bool)
        or not 1 <= sample_count <= validation_count
    ):
        issues.append(f"eval_samples must be 1..{validation_count}; got {sample_count!r}")

    expected_grader = _rft_reward_grader_source(_self_contained_grader_source(grader_path))
    if artifact_paths["grader"].read_text(encoding="utf-8") != expected_grader:
        issues.append("standalone grader differs from the current source wrapper")
    if manifest["grader_source_sha256"] != _sha256_text(expected_grader):
        issues.append("standalone grader source hash differs from manifest")
    if manifest["grader_version"] != _grader_version(grader_path.read_text(encoding="utf-8")):
        issues.append("grader version differs from manifest")

    dry_run = json.loads(artifact_paths["job_spec"].read_text(encoding="utf-8"))
    template = json.loads(artifact_paths["submit_template"].read_text(encoding="utf-8"))
    reinforcement = dry_run["method"]["reinforcement"]
    grader = reinforcement["grader"]
    if dry_run.get("status") != "dry_run_not_submitted":
        issues.append("job spec is not marked as an unsubmitted dry run")
    if template != _submit_template(dry_run):
        issues.append("submit template differs from the dry-run spec")
    if grader.get("source") != expected_grader or grader.get("type") != "python":
        issues.append("dry-run grader source or type differs from standalone grader")
    for spec_key, manifest_key in (
        ("model", "base_model"), ("trainingType", "training_type"),
        ("seed", "seed"), ("suffix", "suffix")
    ):
        if dry_run.get(spec_key) != manifest.get(manifest_key):
            issues.append(f"{spec_key} differs between job spec and manifest")
    if reinforcement.get("hyperparameters") != manifest["hyperparameters"]:
        issues.append("hyperparameters differ between job spec and manifest")
    if grader.get("image_tag") != manifest.get("grader_image_tag"):
        issues.append("grader image tag differs between job spec and manifest")
    threshold = manifest["pass_threshold"]
    if (
        not isinstance(threshold, (int, float))
        or isinstance(threshold, bool)
        or not math.isfinite(threshold)
        or not 0 < threshold <= 1
    ):
        issues.append("pass_threshold must be a finite number in (0, 1]")
    placement = manifest["threshold_placement"]
    if placement not in {"grader", "reinforcement", "both"}:
        issues.append("threshold placement is missing or invalid")
    if grader.get("pass_threshold") != (threshold if placement in {"grader", "both"} else None):
        issues.append("grader pass threshold differs from the recorded placement")
    if reinforcement.get("pass_threshold") != (
        threshold if placement in {"reinforcement", "both"} else None
    ):
        issues.append("reinforcement pass threshold differs from the recorded placement")
    if not manifest.get("threshold_placement_rationale"):
        issues.append("threshold placement rationale is missing")
    has_format = "response_format" in reinforcement
    if has_format != (manifest["response_format_mode"] == "strict"):
        issues.append("response format mode differs between job spec and manifest")
    if response and json.loads(Path(response).read_text(encoding="utf-8")) != reinforcement.get(
        "response_format"
    ):
        issues.append("response format artifact differs from job spec")
    if manifest.get("ready_for_live_submit") is not False:
        issues.append("package must remain blocked from live submit")
    if manifest.get("remote_grader_validation") != "pending_not_run":
        issues.append("package incorrectly claims remote grader validation")
    if not manifest.get("gold_answer_parity", {}).get("ready"):
        issues.append("package gold-answer parity did not pass")

    suite = json.loads(grader_suite_path.read_text(encoding="utf-8"))
    if suite != build_grader_validation_suite(package_dir=package_dir):
        issues.append("grader validation suite differs from the current package")
    if suite.get("execution") != "not_run":
        issues.append("grader validation suite is not marked as unexecuted")
    requests = suite.get("requests", {})
    if set(requests) != set(GRADER_VALIDATION_VARIANTS):
        issues.append("grader validation suite is missing positive or negative cases")
    elif requests["gold"]["expected_score"] != 1.0 or any(
        requests[name]["expected_score"] > 0.5
        for name in GRADER_VALIDATION_VARIANTS if name != "gold"
    ):
        issues.append("grader validation suite does not separate positive and negative samples")
    return issues, {
        "package_dir": str(package_dir),
        "manifest_sha256": _sha256_file(package_dir / "manifest.json"),
        "grader_suite_sha256": _sha256_file(grader_suite_path),
        "validation_rows": validation_count,
        "eval_samples": sample_count,
        "pass_threshold": threshold,
        "threshold_placement": placement,
    }


def _hyperparameter_errors(values: dict[str, Any]) -> list[str]:
    issues = []
    unknown = set(values) - KNOWN_HYPERPARAMETERS
    if unknown:
        issues.append(f"unknown hyperparameters: {sorted(unknown)}")
    for key in ("n_epochs", "eval_interval", "eval_samples"):
        if key in values:
            value = values[key]
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                issues.append(f"{key} must be a positive integer")
    if "batch_size" in values:
        value = values["batch_size"]
        if (
            not isinstance(value, int)
            or isinstance(value, bool)
            or (value <= 0 and value != -1)
        ):
            issues.append("batch_size must be a positive integer or -1 for automatic")
    for key in ("learning_rate_multiplier", "compute_multiplier"):
        if key in values:
            value = values[key]
            if (
                not isinstance(value, (int, float))
                or isinstance(value, bool)
                or not math.isfinite(value)
                or value <= 0
            ):
                issues.append(f"{key} must be a positive finite number")
    if "reasoning_effort" in values:
        effort = values["reasoning_effort"]
        if not isinstance(effort, str) or effort not in {"low", "medium", "high"}:
            issues.append("reasoning_effort must be low, medium, or high")
    return issues


def _check_trainer_parity(
    *, dataset_paths: list[Path], grader_path: Path, package_dir: Path
) -> tuple[list[str], dict[str, Any]]:
    local = load_grader(grader_path)
    wrapped = load_grader(package_dir / "contract-policy-expert-rft-grader.py")
    errors = []
    samples = 0
    for path in dataset_paths:
        for index, row in enumerate(read_jsonl(path), 1):
            packaged_row = _to_rft_row(row, source_path=path, line_number=index, split="parity")
            for name, text in build_perturbations(row).items():
                for sample in (text, {"output_text": text}):
                    direct_score = float(local(sample, row))
                    packaged_score = float(wrapped(sample, packaged_row))
                    samples += 1
                    if (
                        not math.isfinite(direct_score)
                        or not math.isfinite(packaged_score)
                        or not 0 <= direct_score <= 1
                        or not 0 <= packaged_score <= 1
                        or direct_score != packaged_score
                    ):
                        errors.append(f"{row.get('id')}:{name} differs or is outside [0,1]")
    return errors[:20], {"sample_comparisons": samples, "mismatches": len(errors)}


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
