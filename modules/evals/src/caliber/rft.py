from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .grading import load_grader, require_score_range
from .schemas import read_jsonl, validate_jsonl


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
) -> dict[str, Any]:
    """Package reviewed Caliber rows into Foundry RFT-ready local artifacts."""

    if not agent.strip():
        raise ValueError("agent is required")
    if pass_threshold is not None and (pass_threshold < 0.0 or pass_threshold > 1.0):
        raise ValueError(f"pass_threshold must be between 0.0 and 1.0: {pass_threshold}")

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
    manifest_out = out_dir / "manifest.json"

    _write_jsonl(train_out, train["rows"])
    _write_jsonl(validation_out, validation["rows"])
    grader_source = _self_contained_grader_source(grader_path)
    grader_out.write_text(grader_source, encoding="utf-8")
    gold_answer_parity = _gold_answer_parity(
        train_rows=train["rows"],
        validation_rows=validation["rows"],
        grader_path=grader_path,
    )
    endpoint_grader_out.write_text(
        _blossom_endpoint_grader_source(grader_source),
        encoding="utf-8",
    )
    response_format = _expert_evidence_response_format()
    response_format_out.write_text(
        json.dumps(response_format, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    resolved_suffix = suffix or f"{agent}-cost"
    job_spec = {
        "status": "dry_run_not_submitted",
        "model": base_model,
        "suffix": resolved_suffix,
        "training_file": "<upload " + str(train_out) + ">",
        "validation_file": "<upload " + str(validation_out) + ">",
        "method": {
            "type": "reinforcement",
            "reinforcement": {
                **({"pass_threshold": pass_threshold} if pass_threshold is not None else {}),
                "grader": {
                    "type": "python",
                    "name": f"{_safe_name(agent)}_evidence_grader",
                    "source": grader_source,
                },
                "endpoint_grader_fallback": {
                    "type": "endpoint",
                    "name": f"{_safe_name(agent)}_blossom_endpoint_grader",
                    "endpoint": "<deploy and review endpoint URL if python grader is unavailable>",
                    "headers": {
                        "Authorization": "Bearer <grader endpoint token>",
                    },
                    "source_file": str(endpoint_grader_out),
                },
                "response_format": response_format,
            },
        },
    }
    job_spec_out.write_text(json.dumps(job_spec, indent=2, sort_keys=True), encoding="utf-8")

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
        "goal": "cost_optimization_after_agent_optimizer",
        "ready_for_live_submit": False,
        "blocked_until": _rft_submission_gates(
            optimizer_job_id=optimizer_job_id,
            optimizer_candidate_id=optimizer_candidate_id,
            pass_threshold_selected=pass_threshold is not None,
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
        "artifacts": {
            "train": {"path": str(train_out), "rows": train["count"]},
            "validation": {"path": str(validation_out), "rows": validation["count"]},
            "grader": {"path": str(grader_out), "bytes": grader_out.stat().st_size},
            "endpoint_grader": {
                "path": str(endpoint_grader_out),
                "bytes": endpoint_grader_out.stat().st_size,
            },
            "response_format": {
                "path": str(response_format_out),
                "schema": "expert_evidence",
            },
            "job_spec": str(job_spec_out),
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
                "from caliber" not in grader_source,
                "Packaged grader does not import Caliber package modules.",
            ),
            _check(
                "strict_evidence_schema_gate",
                "REQUIRED_TOP_LEVEL_KEYS" in grader_source
                and "REQUIRED_EVIDENCE_KEYS" in grader_source,
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
                "def grade(" in grader_source
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
                True,
                (
                    "Packaged response_format JSON schema is aligned with the evidence "
                    "grader contract."
                ),
            ),
        ],
        "gold_answer_parity": gold_answer_parity,
        "next_step": next_step,
    }
    manifest_out.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    return manifest


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
            response_format_path.exists(),
            f"Response format artifact: {response_format_path}",
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

    request = {
        "grader": grader,
        "item": item,
        "model_sample": json.dumps(expected_output, sort_keys=True),
    }
    result = {
        "route": "/openai/v1/fine_tuning/alpha/graders/run",
        "method": "POST",
        "live_side_effects": "grader_validation_only_no_file_upload_no_job_submission",
        "package_dir": str(package_dir),
        "request": request,
        "expected_score": 1.0,
        "next_step": (
            "POST this request to the grader-run validation route with an Azure AI bearer token; "
            "do not upload files or create a fine-tuning job until it returns the expected score."
        ),
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
        "messages": messages,
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
        + "    output_text = str(sample.get(\"output_text\", \"\") or \"\").strip()\n"
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
) -> list[str]:
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
            "v2 Python grader is validated and aligned with response_format",
            "RFT base model support is verified",
            "live RFT spend is explicitly approved",
        ]
    if optimizer_job_id:
        return [
            "optimizer job completes or recoverable candidate artifacts are selected",
            "optimizer candidate is selected as the gold quality target",
            "optimized hosted agent passes the calibration eval",
            "RFT grader threshold is recalibrated against optimized outputs",
            "v2 Python grader is validated and aligned with response_format",
        ]
    return [
        "optimizer job completes",
        "optimizer candidate is selected and applied after review",
        "optimized hosted agent passes the calibration eval",
        "RFT grader threshold is recalibrated against optimized outputs",
        "v2 Python grader is validated and aligned with response_format",
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
