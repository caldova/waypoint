from __future__ import annotations

import hashlib
import json
import math
import os
import re
from pathlib import Path
from typing import Any

from .grader_robustness import PERTURBATIONS, build_perturbations
from .grading import load_grader, require_score_range
from .schemas import read_jsonl, validate_jsonl

EXPERT_EVIDENCE_SCHEMA_PROMPT = (
    "\n\nReturn exactly this JSON object shape and no other top-level keys: "
    '{"agent":"contract-policy-expert","plane":"foundryiq","invoice_id":"<invoice_id>",'
    '"output_type":"expert_evidence","evidence":[{"claim":"<grounded claim>",'
    '"supports":"approve|recover|escalate|review|unknown",'
    '"source_ref":"<exact retrieved_context source_ref>",'
    '"classification":"standard|confidential|ip_sensitive|restricted","confidence":0.0}],'
    '"unsupported":["<evidence gap>"],'
    '"summary":"<recommended action summary>",'
    '"correlation":{"waypoint_invoice_id":"<invoice_id>","waypoint_run_id":"unknown"}}. '
    "Each evidence row must use exact source_ref values from retrieved_context. "
    "Choose the supports label that best matches the cited evidence and requested "
    "recommendation. Use an empty unsupported array only when retrieved_context contains "
    "all evidence needed for the recommendation."
)

THRESHOLD_PLACEMENTS = {"both", "grader", "reinforcement"}
KNOWN_HYPERPARAMETERS = {
    "n_epochs",
    "batch_size",
    "learning_rate_multiplier",
    "compute_multiplier",
    "eval_interval",
    "eval_samples",
    "reasoning_effort",
}
# Alaska e6 MAI-2 payload (alaska-ata-agent/mai2-rft/payload.e6.json). Starting
# point only: it was tuned for a different task and grader.
MAI2_ALASKA_E6_PRESET: dict[str, Any] = {
    "base_model": "mai-code-2-flash-2026-11-17",
    "training_type": "developerTier",
    "seed": 1266282111,
    "hyperparameters": {
        "n_epochs": 3,
        "learning_rate_multiplier": 2,
        "compute_multiplier": 1,
        "eval_interval": 2,
        "eval_samples": 50,
        "reasoning_effort": "low",
    },
    "grader_image_tag": "2025-05-08",
    "threshold_placement": "grader",
    "include_response_format": False,
}
MAI2_WAYPOINT_PRESET: dict[str, Any] = {
    **MAI2_ALASKA_E6_PRESET,
    "hyperparameters": {**MAI2_ALASKA_E6_PRESET["hyperparameters"], "eval_samples": 16},
}
PACKAGE_PRESETS = {
    "mai2-alaska-e6": MAI2_ALASKA_E6_PRESET,
    "mai2-waypoint-local": MAI2_WAYPOINT_PRESET,
}
GRADER_VALIDATION_VARIANTS = (
    "gold",
    "wrong_supports",
    "wrong_invoice",
    "fabricated_section",
    "boundary_violation",
    "empty",
)


def build_rft_plan(
    train_path: Path,
    validation_path: Path,
    grader_path: Path,
    base_model: str,
    suffix: str | None = None,
    project_endpoint: str | None = None,
) -> dict[str, Any]:
    train = validate_jsonl(train_path)
    validation = validate_jsonl(validation_path)
    if not grader_path.exists():
        raise ValueError(f"grader file does not exist: {grader_path}")
    if grader_path.suffix != ".py":
        raise ValueError(f"grader must be a Python file: {grader_path}")

    endpoint = project_endpoint or os.environ.get("FOUNDRY_PROJECT_ENDPOINT") or os.environ.get(
        "AZURE_AI_PROJECT_ENDPOINT"
    )
    return {
        "ready_to_submit": bool(endpoint),
        "base_model": base_model,
        "suffix": suffix or "caliber-rft",
        "goal": "cost_optimization_after_agent_optimizer",
        "project_endpoint_configured": bool(endpoint),
        "train": train,
        "validation": validation,
        "grader": {"path": str(grader_path), "bytes": grader_path.stat().st_size},
        "next_step": (
            "Submit through Foundry only after optimizer establishes the quality target and "
            "reviewed datasets/graders confirm the cheaper model can preserve it."
            if endpoint
            else "Set FOUNDRY_PROJECT_ENDPOINT before submitting a real Foundry job."
        ),
    }


def package_rft_assets(
    *,
    train_path: Path,
    validation_path: Path,
    grader_path: Path,
    out_dir: Path,
    agent: str,
    base_model: str,
    suffix: str | None = None,
    optimizer_job_id: str | None = None,
    optimizer_candidate_id: str | None = None,
    pass_threshold: float | None = None,
    include_response_format: bool = True,
    training_type: str | None = None,
    seed: int | None = None,
    hyperparameters: dict[str, Any] | None = None,
    grader_image_tag: str | None = None,
    threshold_placement: str = "both",
    preset: str | None = None,
) -> dict[str, Any]:
    """Package reviewed Caliber rows into Foundry RFT-ready local artifacts."""

    if not agent.strip():
        raise ValueError("agent is required")
    if pass_threshold is not None and (
        isinstance(pass_threshold, bool)
        or not math.isfinite(pass_threshold)
        or pass_threshold < 0.0
        or pass_threshold > 1.0
    ):
        raise ValueError(f"pass_threshold must be between 0.0 and 1.0: {pass_threshold}")
    if threshold_placement not in THRESHOLD_PLACEMENTS:
        raise ValueError(
            f"threshold_placement must be one of {sorted(THRESHOLD_PLACEMENTS)}: "
            f"{threshold_placement}"
        )
    if hyperparameters is not None:
        unknown = set(hyperparameters) - KNOWN_HYPERPARAMETERS
        if unknown:
            raise ValueError(f"unknown hyperparameters: {sorted(unknown)}")

    train = _package_split(source_path=train_path, split="train")
    validation = _package_split(source_path=validation_path, split="validation")

    if not grader_path.exists():
        raise ValueError(f"grader file does not exist: {grader_path}")
    if grader_path.suffix != ".py":
        raise ValueError(f"grader must be a Python file: {grader_path}")

    out_dir.mkdir(parents=True, exist_ok=True)
    train_out = out_dir / f"{agent}-rft-train.jsonl"
    validation_out = out_dir / f"{agent}-rft-validation.jsonl"
    grader_out = out_dir / f"{agent}-rft-grader.py"
    endpoint_grader_out = out_dir / f"{agent}-rft-blossom-endpoint-grader.py"
    response_format_out = out_dir / f"{agent}-rft-response-format.json"
    job_spec_out = out_dir / f"{agent}-rft-job.dry-run.json"
    submit_template_out = out_dir / f"{agent}-rft-job.submit-template.json"
    manifest_out = out_dir / "manifest.json"

    _write_jsonl(train_out, train["rows"])
    _write_jsonl(validation_out, validation["rows"])
    grader_source = _self_contained_grader_source(grader_path)
    rft_grader_source = _rft_reward_grader_source(grader_source)
    grader_out.write_text(rft_grader_source, encoding="utf-8")
    gold_answer_parity = _gold_answer_parity(
        train_rows=train["rows"],
        validation_rows=validation["rows"],
        grader_path=grader_path,
    )
    endpoint_grader_out.write_text(
        _blossom_endpoint_grader_source(grader_source),
        encoding="utf-8",
    )
    response_format = _expert_evidence_response_format() if include_response_format else None
    if response_format is not None:
        response_format_out.write_text(
            json.dumps(response_format, indent=2, sort_keys=True),
            encoding="utf-8",
        )
    elif response_format_out.exists():
        response_format_out.unlink()

    resolved_suffix = suffix or f"{agent}-cost"
    outer_threshold = pass_threshold if threshold_placement in {"both", "reinforcement"} else None
    grader_threshold = pass_threshold if threshold_placement in {"both", "grader"} else None
    grader_config: dict[str, Any] = {
        "type": "python",
        "name": f"{_safe_name(agent)}_evidence_grader",
        "source": rft_grader_source,
        **({"pass_threshold": grader_threshold} if grader_threshold is not None else {}),
        **({"image_tag": grader_image_tag} if grader_image_tag else {}),
    }
    job_spec = {
        "status": "dry_run_not_submitted",
        "model": base_model,
        "suffix": resolved_suffix,
        "training_file": "<upload " + str(train_out) + ">",
        "validation_file": "<upload " + str(validation_out) + ">",
        **({"trainingType": training_type} if training_type else {}),
        **({"seed": seed} if seed is not None else {}),
        "method": {
            "type": "reinforcement",
            "reinforcement": {
                **({"pass_threshold": outer_threshold} if outer_threshold is not None else {}),
                "grader": grader_config,
                **({"hyperparameters": dict(hyperparameters)} if hyperparameters else {}),
                "endpoint_grader_fallback": {
                    "type": "endpoint",
                    "name": f"{_safe_name(agent)}_blossom_endpoint_grader",
                    "endpoint": "<deploy and review endpoint URL if python grader is unavailable>",
                    "headers": {
                        "Authorization": "Bearer <grader endpoint token>",
                    },
                    "source_file": str(endpoint_grader_out),
                },
                **({"response_format": response_format} if response_format is not None else {}),
            },
        },
    }
    job_spec_out.write_text(json.dumps(job_spec, indent=2, sort_keys=True), encoding="utf-8")
    submit_template = _submit_template(job_spec)
    submit_template_out.write_text(
        json.dumps(submit_template, indent=2, sort_keys=True), encoding="utf-8"
    )

    if pass_threshold is not None:
        next_step = (
            "Review the frozen dry-run payload, then upload/import files only after "
            "explicit approval."
        )
    elif optimizer_candidate_id:
        next_step = (
            "Use the selected optimizer candidate as the gold quality target, confirm the "
            "RFT base model is supported, then submit live RFT only after approval."
        )
    else:
        next_step = (
            "Wait for Agent Optimizer to finish, apply the selected candidate after review, "
            "rerun the calibration eval, then recalibrate this grader before live RFT submit."
        )

    manifest = {
        "agent": agent,
        "base_model": base_model,
        "suffix": resolved_suffix,
        "pass_threshold": pass_threshold,
        "threshold_placement": threshold_placement if pass_threshold is not None else None,
        "threshold_placement_rationale": (
            (
                "Provisional Alaska e6 shape: threshold inside the grader only. "
                "MAI-1.1 used both placements; remote acceptance and calibration are pending."
            )
            if pass_threshold is not None and threshold_placement == "grader"
            else (
                "Explicit local threshold placement; remote acceptance and calibration are pending."
                if pass_threshold is not None
                else None
            )
        ),
        "training_type": training_type,
        "seed": seed,
        "hyperparameters": dict(hyperparameters) if hyperparameters else None,
        "grader_image_tag": grader_image_tag,
        "preset": preset,
        "remote_grader_validation": "pending_not_run",
        "grader_version": _grader_version(grader_source),
        "grader_source_sha256": hashlib.sha256(rft_grader_source.encode("utf-8")).hexdigest(),
        "goal": "cost_optimization_after_agent_optimizer",
        "response_format_mode": "strict" if response_format is not None else "omitted",
        "ready_for_live_submit": False,
        "blocked_until": _rft_submission_gates(
            optimizer_job_id=optimizer_job_id,
            optimizer_candidate_id=optimizer_candidate_id,
            pass_threshold_selected=pass_threshold is not None,
            include_response_format=response_format is not None,
        ),
        "optimizer_job_id": optimizer_job_id,
        "optimizer_candidate_id": optimizer_candidate_id,
        "gold_standard": (
            {
                "source": "agent_optimizer_candidate",
                "optimizer_job_id": optimizer_job_id,
                "optimizer_candidate_id": optimizer_candidate_id,
            }
            if optimizer_job_id or optimizer_candidate_id
            else None
        ),
        "source": {
            "train": str(train_path),
            "validation": str(validation_path),
            "grader": str(grader_path),
        },
        "source_sha256": {
            "train": _sha256_file(train_path),
            "validation": _sha256_file(validation_path),
            "grader": _sha256_file(grader_path),
        },
        "artifact_sha256": {
            "train": _sha256_file(train_out),
            "validation": _sha256_file(validation_out),
            "grader": _sha256_file(grader_out),
            "endpoint_grader": _sha256_file(endpoint_grader_out),
            "job_spec": _sha256_file(job_spec_out),
            "submit_template": _sha256_file(submit_template_out),
            "response_format": (
                _sha256_file(response_format_out) if response_format is not None else None
            ),
        },
        "artifacts": {
            "train": {"path": str(train_out), "rows": train["count"]},
            "validation": {"path": str(validation_out), "rows": validation["count"]},
            "grader": {"path": str(grader_out), "bytes": grader_out.stat().st_size},
            "endpoint_grader": {
                "path": str(endpoint_grader_out),
                "bytes": endpoint_grader_out.stat().st_size,
            },
            "response_format": (
                {
                    "path": str(response_format_out),
                    "schema": "expert_evidence",
                    "mode": "strict",
                }
                if response_format is not None
                else {
                    "path": None,
                    "schema": None,
                    "mode": "omitted",
                    "reason": (
                        "Historical-shape diagnostic package: rely on prompt/reference JSON "
                        "contract and Python grader reward instead of schema-constrained "
                        "trainer rollouts."
                    ),
                }
            ),
            "job_spec": str(job_spec_out),
            "submit_template": str(submit_template_out),
        },
        "checks": [
            _check("train_rft_format", train["count"] > 0, "Training rows end with user turns."),
            _check(
                "validation_rft_format",
                validation["count"] > 0,
                "Validation rows end with user turns.",
            ),
            _check(
                "self_contained_grader",
                "from caliber" not in rft_grader_source,
                "Packaged grader does not import Caliber package modules.",
            ),
            _check(
                "strict_evidence_schema_gate",
                "REQUIRED_TOP_LEVEL_KEYS" in rft_grader_source
                and "REQUIRED_EVIDENCE_KEYS" in rft_grader_source,
                (
                    "Grader rewards the strict expert_evidence JSON contract and evidence-item "
                    "metadata surfaced by optimizer runs."
                ),
            ),
            _check(
                "gold_answer_parity",
                gold_answer_parity["ready"],
                (
                    "Known corpus answers score at strict parity across packaged train "
                    "and validation rows."
                ),
            ),
            _check(
                "submission_gate",
                False,
                "Live submission remains gated on optimizer completion, eval comparison, "
                "RFT base-model support, and explicit spend approval.",
            ),
            _check(
                "python_grader_payload",
                "def grade(" in rft_grader_source
                and job_spec["method"]["reinforcement"]["grader"]["type"] == "python",
                "Dry-run payload uses a self-contained Python grader source.",
            ),
            _check(
                "endpoint_grader_fallback",
                endpoint_grader_out.exists(),
                "Endpoint-grader fallback is packaged but not required for the Python-grader path.",
            ),
            _check(
                "response_format_schema",
                response_format is not None,
                (
                    "Packaged response_format JSON schema is aligned with the evidence "
                    "grader contract."
                    if response_format is not None
                    else (
                        "response_format intentionally omitted for a historical-shape "
                        "MAI diagnostic."
                    )
                ),
            ),
        ],
        "gold_answer_parity": gold_answer_parity,
        "warnings": _package_warnings(
            hyperparameters=hyperparameters,
            validation_rows=validation["count"],
            include_response_format=response_format is not None,
        ),
        "next_step": next_step,
    }
    manifest_out.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    return manifest


def _package_warnings(
    *,
    hyperparameters: dict[str, Any] | None,
    validation_rows: int,
    include_response_format: bool,
) -> list[str]:
    warnings = []
    eval_samples = (hyperparameters or {}).get("eval_samples")
    if isinstance(eval_samples, int) and eval_samples > validation_rows:
        warnings.append(
            f"eval_samples={eval_samples} exceeds {validation_rows} validation rows; the "
            "trainer may resample or reject it. Confirm behavior before submit."
        )
    if not include_response_format:
        warnings.append(
            "response_format omitted: JSON shape is enforced only by prompt and grader reward."
        )
    return warnings


def _grader_version(source: str) -> str | None:
    match = re.search(r'^GRADER_VERSION\s*=\s*["\']([^"\']+)["\']', source, re.MULTILINE)
    return match.group(1) if match else None


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _submit_template(job_spec: dict[str, Any]) -> dict[str, Any]:
    """API-shaped POST /openai/v1/fine_tuning/jobs body with file-id placeholders.

    Drops dry-run-only fields (status, endpoint_grader_fallback). Never submitted here.
    """

    reinforcement = {
        key: value
        for key, value in job_spec["method"]["reinforcement"].items()
        if key != "endpoint_grader_fallback"
    }
    body = {
        key: value
        for key, value in job_spec.items()
        if key not in {"status", "method", "training_file", "validation_file"}
    }
    body["training_file"] = "<file-id of uploaded training jsonl>"
    body["validation_file"] = "<file-id of uploaded validation jsonl>"
    body["method"] = {"type": "reinforcement", "reinforcement": reinforcement}
    return body


def read_rft_status(state_path: Path) -> dict[str, Any]:
    if not state_path.exists():
        return {
            "status": "missing",
            "path": str(state_path),
            "message": "No local RFT job metadata file exists.",
        }
    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid RFT state file: {state_path}") from exc
    return {"status": "found", "path": str(state_path), "job": data}


def build_integration_preflight(
    *,
    package_dir: Path,
    base_model: str,
    project_endpoint: str | None = None,
    grader_endpoint: str | None = None,
) -> dict[str, Any]:
    """Check integration readiness without uploading files or submitting jobs."""

    manifest_path = package_dir / "manifest.json"
    job_spec_path = package_dir / "contract-policy-expert-rft-job.dry-run.json"
    response_format_path = package_dir / "contract-policy-expert-rft-response-format.json"
    endpoint_grader_path = package_dir / "contract-policy-expert-rft-blossom-endpoint-grader.py"
    grader_validation_result_path = (
        package_dir / "contract-policy-expert-rft-grader-validation-result.json"
    )
    manifest = _read_optional_json(manifest_path)
    response_format_required = manifest.get("response_format_mode", "strict") != "omitted"
    resolved_project_endpoint = (
        project_endpoint
        or os.environ.get("FOUNDRY_PROJECT_ENDPOINT")
        or os.environ.get("AZURE_AI_PROJECT_ENDPOINT")
        or ""
    )
    resolved_grader_endpoint = grader_endpoint or os.environ.get("BLOSSOM_GRADER_ENDPOINT") or ""
    grader_type = _job_spec_grader_type(job_spec_path)
    endpoint_required = grader_type == "endpoint"
    checks = [
        _check("package_manifest", manifest_path.exists(), f"Package manifest: {manifest_path}"),
        _check("dry_run_job_spec", job_spec_path.exists(), f"Dry-run job spec: {job_spec_path}"),
        _check(
            "response_format_artifact",
            (
                response_format_path.exists()
                if response_format_required
                else not response_format_path.exists()
            ),
            (
                f"Response format artifact: {response_format_path}"
                if response_format_required
                else "response_format intentionally omitted for this diagnostic package."
            ),
        ),
        _check(
            "endpoint_grader_artifact",
            endpoint_grader_path.exists(),
            f"Endpoint grader artifact: {endpoint_grader_path}",
        ),
        _check(
            "project_endpoint_configured",
            _is_https_url(resolved_project_endpoint),
            "Set FOUNDRY_PROJECT_ENDPOINT or AZURE_AI_PROJECT_ENDPOINT to the target project.",
        ),
        _check(
            "grader_endpoint_configured",
            (not endpoint_required) or _is_https_url(resolved_grader_endpoint),
            (
                "Not required for python grader."
                if not endpoint_required
                else "Set BLOSSOM_GRADER_ENDPOINT or pass --grader-endpoint after deploying grader."
            ),
        ),
        _check(
            "grader_secret_configured",
            (not endpoint_required) or bool(os.environ.get("BLOSSOM_GRADER_SECRET")),
            (
                "Not required for python grader."
                if not endpoint_required
                else "Set BLOSSOM_GRADER_SECRET for deployed endpoint header authentication."
            ),
        ),
        _check(
            "python_grader_source",
            grader_type == "python",
            "Dry-run job spec should use grader.type=python unless endpoint fallback is required.",
        ),
        _check(
            "base_model_named",
            bool(base_model.strip()) and not base_model.strip().startswith("<"),
            "Pass the exact allowlisted MAI/RFT base model name.",
        ),
    ]
    ready = all(check["ok"] for check in checks)
    grader_validation_passed = _grader_validation_passed(grader_validation_result_path)
    next_step = _integration_preflight_next_step(
        ready=ready,
        grader_type=grader_type,
        grader_validation_passed=grader_validation_passed,
    )
    return {
        "ready_for_integration_dry_run": ready,
        "live_side_effects": "none",
        "package_dir": str(package_dir),
        "base_model": base_model,
        "grader_type": grader_type,
        "endpoint_required": endpoint_required,
        "grader_validation_passed": grader_validation_passed,
        "project_endpoint_configured": _is_https_url(resolved_project_endpoint),
        "grader_endpoint_configured": _is_https_url(resolved_grader_endpoint),
        "checks": checks,
        "next_step": next_step,
    }


def build_grader_validation_request(
    *,
    package_dir: Path,
    out: Path | None = None,
    variant: str = "gold",
) -> dict[str, Any]:
    """Build a no-job grader-run request for Foundry's pre-submit grader validation API."""

    job_spec_path = package_dir / "contract-policy-expert-rft-job.dry-run.json"
    validation_path = package_dir / "contract-policy-expert-rft-validation.jsonl"
    if not job_spec_path.exists():
        raise ValueError(f"dry-run job spec does not exist: {job_spec_path}")
    if not validation_path.exists():
        raise ValueError(f"validation JSONL does not exist: {validation_path}")

    job_spec = json.loads(job_spec_path.read_text(encoding="utf-8-sig"))
    grader = job_spec.get("method", {}).get("reinforcement", {}).get("grader")
    if not isinstance(grader, dict):
        raise ValueError(
            f"dry-run job spec does not contain a reinforcement grader: {job_spec_path}"
        )
    if grader.get("type") != "python":
        raise ValueError("grader validation request builder currently supports grader.type=python")

    validation_rows = read_jsonl(validation_path)
    if not validation_rows:
        raise ValueError(f"validation JSONL is empty: {validation_path}")
    item = validation_rows[0]
    expected_output = item.get("expected_output_json")
    if expected_output is None:
        raise ValueError("validation row does not contain expected_output_json")

    variants = build_perturbations(item)
    if variant not in variants:
        raise ValueError(f"grader validation variant is unavailable for this row: {variant}")
    model_sample = variants[variant]
    grader_path = package_dir / "contract-policy-expert-rft-grader.py"
    expected_score = require_score_range(float(load_grader(grader_path)(model_sample, item)))
    request = {
        "grader": grader,
        "item": item,
        "model_sample": model_sample,
    }
    result = {
        "route": "/openai/v1/fine_tuning/alpha/graders/run",
        "method": "POST",
        "live_side_effects": "grader_validation_only_no_file_upload_no_job_submission",
        "package_dir": str(package_dir),
        "variant": variant,
        "expected_result": PERTURBATIONS[variant][0],
        "request": request,
        "expected_score": expected_score,
        "next_step": (
            "After approval, compare the remote grader-run result with this local score; "
            "do not upload files or submit a job until positive and negative cases agree."
        ),
    }
    if out is not None:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
        result["path"] = str(out)
    return result


def build_grader_validation_suite(*, package_dir: Path, out: Path | None = None) -> dict[str, Any]:
    """Prepare positive and negative grader requests without executing any of them."""
    requests = {
        variant: build_grader_validation_request(package_dir=package_dir, variant=variant)
        for variant in GRADER_VALIDATION_VARIANTS
    }
    result = {
        "execution": "not_run",
        "requests": requests,
        "note": "Local expectations only; remote grader acceptance and parity are unverified.",
    }
    if out is not None:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
        result["path"] = str(out)
    return result


def _grader_validation_passed(path: Path) -> bool:
    if not path.exists():
        return False
    try:
        result = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError:
        return False
    return bool(result.get("passed")) and float(result.get("reward", 0.0)) == 1.0


def _read_optional_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _integration_preflight_next_step(
    *,
    ready: bool,
    grader_type: str,
    grader_validation_passed: bool,
) -> str:
    if not ready:
        return "Resolve failed checks before any file upload/import or Blossom job submission."
    if grader_type != "python":
        return "Run endpoint golden/load tests; do not upload files or submit the job yet."
    if grader_validation_passed:
        return (
            "Select the provisional pass_threshold from gold and optimized-teacher "
            "calibration evidence; do not upload files or submit the job yet."
        )
    return "Run Python grader validation; do not upload files or submit the job yet."


def _package_split(*, source_path: Path, split: str) -> dict[str, Any]:
    validate_jsonl(source_path)
    rows = [
        _to_rft_row(row, source_path=source_path, line_number=index, split=split)
        for index, row in enumerate(read_jsonl(source_path), 1)
    ]
    return {"count": len(rows), "rows": rows}


def _to_rft_row(
    row: dict[str, Any],
    *,
    source_path: Path,
    line_number: int,
    split: str,
) -> dict[str, Any]:
    messages = row.get("messages")
    if not isinstance(messages, list) or not messages:
        raise ValueError(f"{source_path}:{line_number}: messages must be a non-empty list")
    if messages[-1].get("role") != "user":
        raise ValueError(f"{source_path}:{line_number}: RFT row must end with a user message")
    if any(message.get("role") == "assistant" for message in messages):
        raise ValueError(
            f"{source_path}:{line_number}: RFT package rows must not include assistant messages"
        )

    expected = row.get("expected", {})
    expected_text = expected.get("text") if isinstance(expected, dict) else None
    packaged = {
        "messages": _with_expert_evidence_schema_prompt(messages),
        "expected_output_json": row.get("expected_output_json", {}),
        "ground_truth": row.get("ground_truth", {}),
        "metadata": {
            **dict(row.get("metadata", {})),
            "caliber_source_id": row.get("id"),
            "caliber_rft_split": split,
        },
    }
    if row.get("id") is not None:
        packaged["id"] = row["id"]
    if expected_text is not None:
        packaged["reference_output"] = expected_text
    if "retrieved_context" in row:
        packaged["retrieved_context"] = row["retrieved_context"]
    if "expected_tools" in row:
        packaged["expected_tools"] = row["expected_tools"]
    return packaged


def _with_expert_evidence_schema_prompt(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    packaged_messages = [dict(message) for message in messages]
    developer = next(
        (message for message in packaged_messages if message.get("role") == "developer"),
        None,
    )
    if developer is None:
        packaged_messages.insert(
            0,
            {
                "role": "developer",
                "content": EXPERT_EVIDENCE_SCHEMA_PROMPT.strip(),
            },
        )
        return packaged_messages

    content = str(developer.get("content") or "")
    if "output_type\":\"expert_evidence" not in content:
        developer["content"] = content.rstrip() + EXPERT_EVIDENCE_SCHEMA_PROMPT
    return packaged_messages


def _self_contained_grader_source(grader_path: Path) -> str:
    source = grader_path.read_text(encoding="utf-8")
    if "from caliber.evidence_grader import grade_evidence_contract" not in source:
        return source

    evidence_source = (Path(__file__).parent / "evidence_grader.py").read_text(encoding="utf-8")
    return (
        evidence_source
        + "\n\n"
        + "def grade(sample: dict[str, Any], item: dict[str, Any]) -> float:\n"
        + "    return grade_evidence_contract(sample, item)\n"
    )


def _rft_reward_grader_source(grader_source: str) -> str:
    """Expose Caliber's 0-1 grader for Foundry RFT."""
    marker = "\ndef grade("
    if marker not in grader_source:
        raise ValueError("grader source must define def grade(sample, item)")
    reward_source = grader_source.replace(marker, "\ndef _grade_unit(", 1)
    return (
        reward_source.rstrip()
        + "\n\n"
        + "def grade(sample: Any, item: dict[str, Any]) -> float:\n"
        + "    unit_score = float(_grade_unit(sample, item))\n"
        + "    return round(max(0.0, min(unit_score, 1.0)), 3)\n"
    )


def _blossom_endpoint_grader_source(grader_source: str) -> str:
    return (
        grader_source.rstrip()
        + "\n\n"
        + "import os\n\n"
        + "BLOSSOM_ENDPOINT_ADAPTER_VERSION = \"contract-policy-expert-v2\"\n\n"
        + "def handle_blossom_request(\n"
        + "    body: dict[str, Any] | str,\n"
        + "    headers: dict[str, str] | None = None,\n"
        + ") -> dict[str, float]:\n"
        + "    \"\"\"Adapt a Blossom endpoint-grader request into the local evidence grader.\n\n"
        + "    Credentials must arrive in headers. For local offline tests, leave\n"
        + "    BLOSSOM_GRADER_SECRET unset. In deployed environments, set it and pass\n"
        + "    either Authorization: Bearer <secret> or X-Grader-Secret: <secret>.\n"
        + "    \"\"\"\n"
        + "    request = _parse_blossom_body(body)\n"
        + "    _require_header_secret(headers or {})\n"
        + "    sample = _extract_blossom_sample(request)\n"
        + "    item = _extract_blossom_item(request)\n"
        + "    diagnostics = score_with_diagnostics(sample, item)\n"
        + "    return {\"score\": float(diagnostics[\"score\"])}\n\n"
        + "def score_with_diagnostics(\n"
        + "    sample: dict[str, Any],\n"
        + "    item: dict[str, Any],\n"
        + ") -> dict[str, Any]:\n"
        + "    \"\"\"Score locally with per-dimension diagnostics for preflight review.\"\"\"\n"
        + "    output_text = _output_text(sample)\n"
        + "    try:\n"
        + "        output = json.loads(output_text)\n"
        + "    except json.JSONDecodeError:\n"
        + "        return {\n"
        + "            \"score\": 0.0,\n"
        + "            \"diagnostics\": {\"parse\": 0.0},\n"
        + "            \"reason\": \"invalid_json\",\n"
        + "        }\n"
        + "    if not isinstance(output, dict):\n"
        + "        return {\n"
        + "            \"score\": 0.0,\n"
        + "            \"diagnostics\": {\"parse\": 1.0, \"schema\": 0.0},\n"
        + "            \"reason\": \"output_must_be_object\",\n"
        + "        }\n"
        + "    score = float(grade(sample, item))\n"
        + "    required_functions = (\n"
        + "        \"_score_schema\",\n"
        + "        \"_score_identity\",\n"
        + "        \"_score_correlation\",\n"
        + "        \"_score_evidence\",\n"
        + "        \"_score_unsupported_claims\",\n"
        + "        \"_score_summary\",\n"
        + "        \"_score_boundary\",\n"
        + "        \"_score_expected_shape\",\n"
        + "    )\n"
        + "    if not all(name in globals() for name in required_functions):\n"
        + "        return {\"score\": score, \"diagnostics\": {\"grade\": score}}\n"
        + "    expected = item.get(\"expected_output_json\", {})\n"
        + "    ground_truth = item.get(\"ground_truth\", {})\n"
        + "    metadata = item.get(\"metadata\", {})\n"
        + "    diagnostics = {\n"
        + "        \"parse\": 1.0,\n"
        + "        \"schema\": round(float(_score_schema(output)), 3),\n"
        + "        \"identity\": round(float(_score_identity(output, metadata)), 3),\n"
        + "        \"correlation\": round(float(_score_correlation(output, metadata)), 3),\n"
        + "        \"evidence\": round(float(_score_evidence(output, ground_truth)), 3),\n"
        + "        \"unsupported\": round(float(_score_unsupported_claims(output, item)), 3),\n"
        + "        \"summary\": round(float(_score_summary(output, ground_truth)), 3),\n"
        + "        \"boundary\": round(float(_score_boundary(output_text)), 3),\n"
        + "        \"expected_shape\": round(float(_score_expected_shape(output, expected)), 3),\n"
        + "    }\n"
        + "    return {\"score\": score, \"diagnostics\": diagnostics}\n\n"
        + "def _parse_blossom_body(body: dict[str, Any] | str) -> dict[str, Any]:\n"
        + "    if isinstance(body, dict):\n"
        + "        return body\n"
        + "    if isinstance(body, str):\n"
        + "        try:\n"
        + "            parsed = json.loads(body)\n"
        + "        except json.JSONDecodeError as exc:\n"
        + "            raise ValueError(\n"
        + "                \"Blossom grader request body must be valid JSON\"\n"
        + "            ) from exc\n"
        + "        if isinstance(parsed, dict):\n"
        + "            return parsed\n"
        + "    raise ValueError(\"Blossom grader request body must be a JSON object\")\n\n"
        + "def _require_header_secret(headers: dict[str, str]) -> None:\n"
        + "    expected_secret = os.environ.get(\"BLOSSOM_GRADER_SECRET\")\n"
        + "    if not expected_secret:\n"
        + "        return\n"
        + "    normalized = {key.lower(): value for key, value in headers.items()}\n"
        + "    bearer = normalized.get(\"authorization\", \"\")\n"
        + "    supplied_secret = normalized.get(\"x-grader-secret\", \"\")\n"
        + "    if bearer.startswith(\"Bearer \"):\n"
        + "        supplied_secret = bearer.removeprefix(\"Bearer \").strip()\n"
        + "    if supplied_secret != expected_secret:\n"
        + "        raise PermissionError(\n"
        + "            \"Blossom grader request is missing valid header credentials\"\n"
        + "        )\n\n"
        + "def _extract_blossom_sample(request: dict[str, Any]) -> dict[str, Any]:\n"
        + "    sample = request.get(\"sample\")\n"
        + "    if isinstance(sample, dict):\n"
        + "        return sample\n"
        + "    output_text = (\n"
        + "        request.get(\"output_text\")\n"
        + "        or request.get(\"response\")\n"
        + "        or request.get(\"final_output\")\n"
        + "    )\n"
        + "    if output_text is None and isinstance(request.get(\"output\"), dict):\n"
        + "        output_text = request[\"output\"].get(\"text\")\n"
        + "    if output_text is None:\n"
        + "        raise ValueError(\n"
        + "            \"Blossom grader request must include sample.output_text or output_text\"\n"
        + "        )\n"
        + "    return {\n"
        + "        \"output_text\": str(output_text),\n"
        + "        \"output_tools\": request.get(\"output_tools\", []),\n"
        + "    }\n\n"
        + "def _extract_blossom_item(request: dict[str, Any]) -> dict[str, Any]:\n"
        + "    item = request.get(\"item\") or request.get(\"input\")\n"
        + "    if isinstance(item, dict):\n"
        + "        return item\n"
        + "    for key in (\"expected_output_json\", \"ground_truth\", \"metadata\"):\n"
        + "        if key in request:\n"
        + "            return {\n"
        + "                \"expected_output_json\": request.get(\"expected_output_json\", {}),\n"
        + "                \"ground_truth\": request.get(\"ground_truth\", {}),\n"
        + "                \"metadata\": request.get(\"metadata\", {}),\n"
        + "            }\n"
        + "    raise ValueError(\n"
        + "        \"Blossom grader request must include item/input or \"\n"
        + "        \"expected_output_json metadata\"\n"
        + "    )\n"
    )


def _expert_evidence_response_format() -> dict[str, Any]:
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "expert_evidence",
            "strict": True,
            "schema": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "agent",
                    "plane",
                    "invoice_id",
                    "output_type",
                    "evidence",
                    "unsupported",
                    "summary",
                    "correlation",
                ],
                "properties": {
                    "agent": {"type": "string"},
                    "plane": {"type": "string", "const": "foundryiq"},
                    "invoice_id": {"type": "string"},
                    "output_type": {"type": "string", "const": "expert_evidence"},
                    "evidence": {
                        "type": "array",
                        "minItems": 1,
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": [
                                "claim",
                                "supports",
                                "source_ref",
                                "classification",
                                "confidence",
                            ],
                            "properties": {
                                "claim": {"type": "string", "minLength": 1},
                                "supports": {
                                    "type": "string",
                                    "enum": ["approve", "recover", "escalate", "review", "unknown"],
                                },
                                "source_ref": {"type": "string", "minLength": 1},
                                "classification": {
                                    "type": "string",
                                    "enum": [
                                        "standard",
                                        "confidential",
                                        "ip_sensitive",
                                        "restricted",
                                    ],
                                },
                                "confidence": {
                                    "type": "number",
                                    "minimum": 0,
                                    "maximum": 1,
                                },
                            },
                        },
                    },
                    "unsupported": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "summary": {"type": "string", "minLength": 1},
                    "correlation": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["waypoint_run_id", "waypoint_invoice_id"],
                        "properties": {
                            "waypoint_run_id": {"type": "string", "minLength": 1},
                            "waypoint_invoice_id": {"type": "string", "minLength": 1},
                        },
                    },
                },
            },
        },
    }


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def _gold_answer_parity(
    *,
    train_rows: list[dict[str, Any]],
    validation_rows: list[dict[str, Any]],
    grader_path: Path,
) -> dict[str, Any]:
    grader = load_grader(grader_path)
    scored: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []

    for split, rows in (("train", train_rows), ("validation", validation_rows)):
        for index, row in enumerate(rows, 1):
            expected_output = row.get("expected_output_json")
            if not isinstance(expected_output, dict):
                failures.append(
                    {
                        "split": split,
                        "index": index,
                        "id": row.get("id"),
                        "reason": "missing_expected_output_json",
                    }
                )
                continue
            score = require_score_range(
                float(grader({"output_text": json.dumps(expected_output)}, row))
            )
            scored_row = {
                "split": split,
                "index": index,
                "id": row.get("id"),
                "score": score,
            }
            scored.append(scored_row)
            if score < 1.0:
                failures.append(scored_row)

    scores = [row["score"] for row in scored]
    return {
        "ready": bool(scored) and not failures,
        "scored_rows": len(scored),
        "failures": failures[:20],
        "failure_count": len(failures),
        "score_summary": _score_summary(scores),
    }


def _check(name: str, ok: bool, message: str) -> dict[str, Any]:
    return {"name": name, "ok": ok, "message": message}


def _score_summary(scores: list[float]) -> dict[str, Any]:
    if not scores:
        return {"min": None, "max": None, "avg": None}
    return {
        "min": min(scores),
        "max": max(scores),
        "avg": round(sum(scores) / len(scores), 3),
    }


def _rft_submission_gates(
    *,
    optimizer_job_id: str | None,
    optimizer_candidate_id: str | None,
    pass_threshold_selected: bool,
    include_response_format: bool,
) -> list[str]:
    grader_validation_gate = (
        "v2 Python grader is validated and aligned with response_format"
        if include_response_format
        else "v2 Python grader is validated without relying on response_format"
    )
    if pass_threshold_selected:
        return [
            "frozen dry-run payload is reviewed",
            "train and validation files are uploaded/imported after approval",
            "uploaded file IDs are processed and substituted into the final payload",
            "RFT base model support is verified",
            "live RFT spend is explicitly approved",
        ]
    if optimizer_candidate_id:
        return [
            "optimizer candidate is selected as the gold quality target",
            "gold candidate outputs are calibrated with the RFT grader",
            grader_validation_gate,
            "RFT base model support is verified",
            "live RFT spend is explicitly approved",
        ]
    if optimizer_job_id:
        return [
            "optimizer job completes or recoverable candidate artifacts are selected",
            "optimizer candidate is selected as the gold quality target",
            "optimized hosted agent passes the calibration eval",
            "RFT grader threshold is recalibrated against optimized outputs",
            grader_validation_gate,
        ]
    return [
        "optimizer job completes",
        "optimizer candidate is selected and applied after review",
        "optimized hosted agent passes the calibration eval",
        "RFT grader threshold is recalibrated against optimized outputs",
        grader_validation_gate,
    ]


def _safe_name(value: str) -> str:
    return "".join(char if char.isalnum() else "_" for char in value).strip("_")


def _is_https_url(value: str) -> bool:
    stripped = value.strip()
    return stripped.startswith("https://") and " " not in stripped


def _job_spec_grader_type(job_spec_path: Path) -> str:
    if not job_spec_path.exists():
        return "missing"
    try:
        job_spec = json.loads(job_spec_path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError:
        return "invalid"
    grader = job_spec.get("method", {}).get("reinforcement", {}).get("grader", {})
    if not isinstance(grader, dict):
        return "missing"
    return str(grader.get("type", "missing"))
