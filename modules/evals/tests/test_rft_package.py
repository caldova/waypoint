from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

from caliber.calibration import (
    build_model_output_calibration_plan,
    build_threshold_failure_report,
    calibrate_grader,
    write_gold_answer_outputs,
)
from caliber.rft import (
    build_grader_validation_request,
    build_integration_preflight,
    package_rft_assets,
)


def test_rft_package_emits_python_grader_endpoint_fallback_and_response_schema(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    row = _contract_policy_row()
    manifest = _package_rows(tmp_path, [row])
    assert manifest["gold_answer_parity"]["ready"] is True
    assert manifest["gold_answer_parity"]["scored_rows"] == 2
    assert manifest["gold_answer_parity"]["score_summary"] == {
        "min": 1.0,
        "max": 1.0,
        "avg": 1.0,
    }

    endpoint_path = Path(manifest["artifacts"]["endpoint_grader"]["path"])
    response_format_path = Path(manifest["artifacts"]["response_format"]["path"])
    job_spec_path = Path(manifest["artifacts"]["job_spec"])
    assert endpoint_path.exists()
    assert response_format_path.exists()

    response_format = json.loads(response_format_path.read_text(encoding="utf-8"))
    assert response_format["json_schema"]["name"] == "expert_evidence"
    assert response_format["json_schema"]["strict"] is True
    assert (
        response_format["json_schema"]["schema"]["properties"]["evidence"]["items"][
            "additionalProperties"
        ]
        is False
    )

    job_spec = json.loads(job_spec_path.read_text(encoding="utf-8"))
    grader_config = job_spec["method"]["reinforcement"]["grader"]
    assert job_spec["method"]["reinforcement"]["pass_threshold"] == 0.9
    assert manifest["pass_threshold"] == 0.9
    assert grader_config["type"] == "python"
    assert "def grade(" in grader_config["source"]
    fallback_config = job_spec["method"]["reinforcement"]["endpoint_grader_fallback"]
    assert fallback_config["type"] == "endpoint"
    assert "Authorization" in fallback_config["headers"]
    assert job_spec["method"]["reinforcement"]["response_format"] == response_format

    grader_module = _load_module(Path(manifest["artifacts"]["grader"]["path"]))
    assert grader_module.grade(
        {"output_json": row["expected_output_json"]},
        row,
    ) == 1.0

    endpoint_module = _load_module(endpoint_path)
    monkeypatch.setenv("BLOSSOM_GRADER_SECRET", "local-secret")
    result = endpoint_module.handle_blossom_request(
        {
            "sample": {"output_text": json.dumps(row["expected_output_json"])},
            "item": row,
        },
        headers={"Authorization": "Bearer local-secret"},
    )
    assert result == {"score": 1.0}


def test_blossom_endpoint_diagnostics_reward_exact_contract_and_penalize_failures(
    tmp_path: Path,
) -> None:
    row = _contract_policy_row()
    manifest = _package_rows(tmp_path, [row])
    endpoint_module = _load_module(Path(manifest["artifacts"]["endpoint_grader"]["path"]))

    perfect = endpoint_module.score_with_diagnostics(
        {"output_text": json.dumps(row["expected_output_json"])},
        row,
    )
    assert perfect["score"] == 1.0
    assert all(value == 1.0 for value in perfect["diagnostics"].values())

    wrong_citation = json.loads(json.dumps(row["expected_output_json"]))
    wrong_citation["evidence"][0]["source_ref"] = "made-up.md#unsupported"
    wrong_citation_result = endpoint_module.score_with_diagnostics(
        {"output_text": json.dumps(wrong_citation)},
        row,
    )
    assert wrong_citation_result["score"] < 0.9
    assert wrong_citation_result["diagnostics"]["evidence"] < 1.0

    fake_action = json.loads(json.dumps(row["expected_output_json"]))
    fake_action["summary"] = "I approved for payment and wrote to Waypoint."
    fake_action_result = endpoint_module.score_with_diagnostics(
        {"output_text": json.dumps(fake_action)},
        row,
    )
    assert fake_action_result["score"] < perfect["score"]
    assert fake_action_result["diagnostics"]["boundary"] == 0.0


def test_blossom_endpoint_scores_committed_contract_policy_target_at_parity(
    tmp_path: Path,
) -> None:
    project_root = Path(__file__).resolve().parents[1]
    dataset = (
        project_root
        / "datasets"
        / "contract-policy-expert"
        / "contract-policy-expert-train.jsonl"
    )
    real_row = json.loads(dataset.read_text(encoding="utf-8").splitlines()[0])
    manifest = _package_rows(tmp_path, [real_row])
    assert manifest["gold_answer_parity"]["ready"] is True
    endpoint_module = _load_module(Path(manifest["artifacts"]["endpoint_grader"]["path"]))

    result = endpoint_module.score_with_diagnostics(
        {"output_text": json.dumps(real_row["expected_output_json"])},
        real_row,
    )
    assert result["score"] == 1.0
    assert result["diagnostics"]["evidence"] == 1.0


def test_gold_answer_outputs_establish_calibration_ceiling(tmp_path: Path) -> None:
    row = _contract_policy_row()
    dataset = tmp_path / "validation.jsonl"
    outputs = tmp_path / "gold-output-items.jsonl"
    _write_jsonl(dataset, [row])

    exported = write_gold_answer_outputs(dataset_path=dataset, out_path=outputs)
    assert exported["ready"] is True
    assert exported["out"]["rows"] == 1

    project_root = Path(__file__).resolve().parents[1]
    grader = (
        project_root
        / "graders"
        / "contract-policy-expert"
        / "contract_policy_evidence_grader.py"
    )
    calibration = calibrate_grader(
        dataset_path=dataset,
        outputs_path=outputs,
        grader_path=grader,
    )
    assert calibration["ready"] is True
    assert calibration["score_summary"] == {"min": 1.0, "max": 1.0, "avg": 1.0}
    assert all(rate == 1.0 for rate in calibration["pass_rates"].values())
    assert calibration["recommendation"].startswith("Gold-answer ceiling established.")


def test_model_output_plan_blocks_until_teacher_and_base_outputs_exist(tmp_path: Path) -> None:
    row = _contract_policy_row()
    dataset = tmp_path / "validation.jsonl"
    gold_outputs = tmp_path / "gold-output-items.jsonl"
    teacher_outputs = tmp_path / "optimized-teacher-output-items.jsonl"
    base_outputs = tmp_path / "mai-base-output-items.jsonl"
    _write_jsonl(dataset, [row])
    write_gold_answer_outputs(dataset_path=dataset, out_path=gold_outputs)

    project_root = Path(__file__).resolve().parents[1]
    grader = (
        project_root
        / "graders"
        / "contract-policy-expert"
        / "contract_policy_evidence_grader.py"
    )
    missing_plan = build_model_output_calibration_plan(
        dataset_path=dataset,
        grader_path=grader,
        gold_outputs_path=gold_outputs,
        teacher_outputs_path=teacher_outputs,
        base_outputs_path=base_outputs,
    )
    assert missing_plan["ready_for_threshold_selection"] is False
    assert set(missing_plan["missing_outputs"]) == {"optimized_teacher", "mai_base"}
    assert missing_plan["scored"]["gold_answer_ceiling"]["score_summary"]["avg"] == 1.0

    _write_jsonl(
        teacher_outputs,
        [{"id": row["id"], "output_text": json.dumps(row["expected_output_json"])}],
    )
    teacher_only_plan = build_model_output_calibration_plan(
        dataset_path=dataset,
        grader_path=grader,
        gold_outputs_path=gold_outputs,
        teacher_outputs_path=teacher_outputs,
        base_outputs_path=base_outputs,
    )
    assert teacher_only_plan["ready_for_threshold_selection"] is False
    assert set(teacher_only_plan["missing_outputs"]) == {"mai_base"}

    base_outputs.with_name("mai-base-capture-blocker.json").write_text(
        json.dumps(
            {
                "blocked": True,
                "model": "MAI-Code-1-Flash",
                "reason": (
                    "MAI-Code-1-Flash is available only as an RFT target, not as a "
                    "serving deployment for pre-RFT base-output capture."
                ),
            }
        ),
        encoding="utf-8",
    )
    waived_plan = build_model_output_calibration_plan(
        dataset_path=dataset,
        grader_path=grader,
        gold_outputs_path=gold_outputs,
        teacher_outputs_path=teacher_outputs,
        base_outputs_path=base_outputs,
    )
    assert waived_plan["ready_for_threshold_selection"] is True
    assert waived_plan["missing_outputs"] == {}
    assert waived_plan["unavailable_outputs"]["mai_base"]["model"] == "MAI-Code-1-Flash"
    assert "provisional pass_threshold" in waived_plan["next_step"]

    weak_output = json.loads(json.dumps(row["expected_output_json"]))
    weak_output["evidence"][0]["source_ref"] = "made-up.md#unsupported"
    _write_jsonl(base_outputs, [{"id": row["id"], "output_text": json.dumps(weak_output)}])
    ready_plan = build_model_output_calibration_plan(
        dataset_path=dataset,
        grader_path=grader,
        gold_outputs_path=gold_outputs,
        teacher_outputs_path=teacher_outputs,
        base_outputs_path=base_outputs,
    )
    assert ready_plan["ready_for_threshold_selection"] is True
    assert ready_plan["scored"]["optimized_teacher"]["score_summary"]["avg"] == 1.0
    assert ready_plan["scored"]["mai_base"]["score_summary"]["avg"] < 1.0


def test_threshold_failure_report_includes_diagnostics(tmp_path: Path) -> None:
    row = _contract_policy_row()
    manifest = _package_rows(tmp_path, [row])
    dataset = tmp_path / "validation.jsonl"
    outputs = tmp_path / "teacher-output-items.jsonl"
    endpoint_grader = Path(manifest["artifacts"]["endpoint_grader"]["path"])
    weak_output = json.loads(json.dumps(row["expected_output_json"]))
    weak_output["evidence"][0]["source_ref"] = "made-up.md#unsupported"
    _write_jsonl(dataset, [row])
    _write_jsonl(outputs, [{"id": row["id"], "output_text": json.dumps(weak_output)}])

    report_path = tmp_path / "threshold-report.json"
    report = build_threshold_failure_report(
        dataset_path=dataset,
        outputs_path=outputs,
        grader_path=endpoint_grader,
        threshold=0.9,
        out_path=report_path,
    )

    assert report["ready"] is True
    assert report["failed_rows"] == 1
    assert report_path.exists()
    failure = report["failures"][0]
    assert failure["id"] == row["id"]
    assert failure["diagnostics"]["evidence"] < 1.0
    assert failure["expected"]["support"] == "recover"
    assert "made-up.md#unsupported" in failure["output"]["citations"]


def test_integration_preflight_reports_env_risks_without_live_side_effects(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    row = _contract_policy_row()
    manifest = _package_rows(tmp_path, [row])
    package_dir = Path(manifest["artifacts"]["job_spec"]).parent
    monkeypatch.delenv("FOUNDRY_PROJECT_ENDPOINT", raising=False)
    monkeypatch.delenv("AZURE_AI_PROJECT_ENDPOINT", raising=False)
    monkeypatch.delenv("BLOSSOM_GRADER_ENDPOINT", raising=False)
    monkeypatch.delenv("BLOSSOM_GRADER_SECRET", raising=False)

    blocked = build_integration_preflight(
        package_dir=package_dir,
        base_model="MAI-Code-1-Flash",
    )
    assert blocked["ready_for_integration_dry_run"] is False
    assert blocked["live_side_effects"] == "none"
    failed = {check["name"] for check in blocked["checks"] if not check["ok"]}
    assert failed == {"project_endpoint_configured"}

    ready = build_integration_preflight(
        package_dir=package_dir,
        base_model="MAI-Code-1-Flash",
        project_endpoint="https://example.services.ai.azure.com/api/projects/demo",
    )
    assert ready["ready_for_integration_dry_run"] is True
    assert ready["grader_type"] == "python"


def test_grader_validation_request_uses_python_grader_without_job_submit(tmp_path: Path) -> None:
    row = _contract_policy_row()
    manifest = _package_rows(tmp_path, [row])
    package_dir = Path(manifest["artifacts"]["job_spec"]).parent

    request_path = package_dir / "grader-validation-request.json"
    result = build_grader_validation_request(package_dir=package_dir, out=request_path)

    assert result["route"] == "/openai/v1/fine_tuning/alpha/graders/run"
    assert result["live_side_effects"] == "grader_validation_only_no_file_upload_no_job_submission"
    assert result["expected_score"] == 1.0
    assert request_path.exists()

    payload = result["request"]
    assert payload["grader"]["type"] == "python"
    assert "def grade(" in payload["grader"]["source"]
    assert payload["model_sample"].startswith("{")
    assert payload["item"]["expected_output_json"]


def _package_rows(tmp_path: Path, rows: list[dict[str, Any]]) -> dict[str, Any]:
    train = tmp_path / "train.jsonl"
    validation = tmp_path / "validation.jsonl"
    _write_jsonl(train, rows)
    _write_jsonl(validation, rows)

    project_root = Path(__file__).resolve().parents[1]
    grader = (
        project_root
        / "graders"
        / "contract-policy-expert"
        / "contract_policy_evidence_grader.py"
    )
    return package_rft_assets(
        train_path=train,
        validation_path=validation,
        grader_path=grader,
        out_dir=tmp_path / "rft",
        agent="contract-policy-expert",
        base_model="MAI-Code-1-Flash",
        suffix="contract-policy-expert-v2-mai",
        pass_threshold=0.9,
    )


def _load_module(path: Path) -> Any:
    spec = importlib.util.spec_from_file_location("generated_blossom_grader", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def _contract_policy_row() -> dict[str, Any]:
    expected_output = {
        "agent": "contract-policy-expert",
        "plane": "foundryiq",
        "invoice_id": "INV-CMO-001-2026-10",
        "output_type": "expert_evidence",
        "evidence": [
            {
                "claim": "Request packaging authorization or supplier credit.",
                "supports": "recover",
                "source_ref": "contract.md#packaging",
                "classification": "confidential",
                "confidence": 0.86,
            }
        ],
        "unsupported": [],
        "summary": "Request packaging authorization or supplier credit.",
        "correlation": {
            "waypoint_run_id": "ledgerfield-seed",
            "waypoint_invoice_id": "INV-CMO-001-2026-10",
        },
    }
    return {
        "id": "contract-policy:test",
        "messages": [
            {
                "role": "developer",
                "content": "Return strict expert_evidence JSON only.",
            },
            {
                "role": "user",
                "content": "Review invoice INV-CMO-001-2026-10.",
            },
        ],
        "expected": {"text": json.dumps(expected_output)},
        "expected_output_json": expected_output,
        "ground_truth": {
            "acceptable_citations": ["contract.md#packaging"],
            "expected_supports": "recover",
            "recommended_action": "Request packaging authorization or supplier credit.",
        },
        "metadata": {
            "training_agent": "contract-policy-expert",
            "invoice_id": "INV-CMO-001-2026-10",
        },
    }
