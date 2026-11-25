from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from caliber.calibration import (
    build_model_output_calibration_plan,
    calibrate_grader,
    write_gold_answer_outputs,
)
from caliber.cli import main
from caliber.contract_policy_challenge import build_contract_policy_challenge
from caliber.grader_robustness import build_perturbations, run_grader_robustness
from caliber.grading import load_grader
from caliber.rft import (
    MAI2_WAYPOINT_PRESET,
    build_grader_validation_suite,
    package_rft_assets,
)
from caliber.rft_data_audit import audit_rft_datasets
from caliber.rft_preflight import (
    _check_advisory_references,
    _check_corpus_alignment,
    _hyperparameter_errors,
    run_offline_preflight,
)
from caliber.rft_prompt_preparation import prepare_rft_prompts
from caliber.schemas import read_jsonl

ROOT = Path(__file__).resolve().parents[1]
DATASETS = ROOT / "datasets" / "contract-policy-expert"
GRADER_V2 = ROOT / "graders" / "contract-policy-expert" / "contract_policy_evidence_grader_v2.py"
SPLITS = [
    DATASETS / f"contract-policy-expert-{name}.jsonl" for name in ("train", "validation", "eval")
]
CHALLENGE = DATASETS / "contract-policy-expert-challenge-candidates.jsonl"
CORPUS = ROOT.parent / "corpus"


def test_v2_grader_separates_gold_from_every_known_bad_variant(tmp_path: Path) -> None:
    report = run_grader_robustness(
        dataset_paths=[*SPLITS, CHALLENGE],
        grader_path=GRADER_V2,
        pass_threshold=0.9,
        out=tmp_path / "robustness.json",
    )

    assert report["ready"] is True
    assert report["rows"] == 126
    assert report["violation_count"] == 0
    assert report["perturbations"]["gold"]["min"] == 1.0
    assert report["perturbations"]["negated_boundary"]["min"] >= 0.9
    for name in ("wrong_supports", "fabricated_section", "shotgun_citations", "boundary_violation"):
        assert report["perturbations"][name]["max"] < 0.9
    assert all(
        values["max"] <= 0.5
        for values in report["perturbations"].values()
        if values["expect"] == "fail"
    )
    assert report["perturbations"]["retrieved_distractor"]["n"] == 6
    assert report["perturbations"]["missing_expected_gap"]["n"] == 2


def test_candidate_holdout_rebuilds_without_overwriting_reviewed_data(tmp_path: Path) -> None:
    out = tmp_path / "challenge.jsonl"
    report = build_contract_policy_challenge(corpus_path=CORPUS, out=out)

    assert report["rows"] == 6
    assert report["review_status"] == "pending_human_review"
    assert out.read_text(encoding="utf-8") == CHALLENGE.read_text(encoding="utf-8")
    rows = read_jsonl(out)
    assert len({row["metadata"]["scenario_id"] for row in rows}) == 6
    assert len({row["metadata"]["supplier_name"] for row in rows}) == 3
    assert {row["ground_truth"]["expected_supports"] for row in rows} == {
        "approve", "recover", "review"
    }
    assert sum(bool(row["expected_output_json"]["unsupported"]) for row in rows) == 2
    assert all(row["metadata"]["review_status"] == "pending_human_review" for row in rows)
    assert all(row["metadata"]["expected_answer_derivation"] for row in rows)
    assert all(
        "expected_supports" not in json.loads(row["messages"][-1]["content"])["line"]
        for row in rows
    )

    out.write_text("reviewer edits\n", encoding="utf-8")
    with pytest.raises(ValueError, match="refusing to overwrite"):
        build_contract_policy_challenge(corpus_path=CORPUS, out=out)
    assert out.read_text(encoding="utf-8") == "reviewer edits\n"


def test_standalone_trainer_grader_matches_local_grader_on_adversarial_samples(
    tmp_path: Path,
) -> None:
    cases = read_jsonl(CHALLENGE)
    paths = _write(tmp_path, train=[cases[0]], validation=[cases[1]])
    manifest = package_rft_assets(
        train_path=paths["train"],
        validation_path=paths["validation"],
        grader_path=GRADER_V2,
        out_dir=tmp_path / "package",
        agent="contract-policy-expert",
        base_model="mai-code-2-flash-2026-11-17",
    )
    local = load_grader(GRADER_V2)
    wrapped = load_grader(Path(manifest["artifacts"]["grader"]["path"]))
    for row in cases:
        for text in build_perturbations(row).values():
            score = local({"output_text": text}, row)
            assert 0.0 <= score <= 1.0
            assert wrapped({"output_text": text}, row) == score
            assert wrapped(text, row) == score

    assert local({"output_json": cases[2]["expected_output_json"]}, cases[2]) == 1.0
    assert local({"output_text": json.dumps(cases[0]["expected_output_json"])}, cases[2]) <= 0.5


@pytest.mark.parametrize("sample", [{}, {"output_text": None}, {"output_text": "{"}, "raw"])
def test_v2_grader_scores_malformed_samples_near_zero_without_raising(sample: Any) -> None:
    grade = load_grader(GRADER_V2)
    # Non-empty malformed output keeps a tiny inherited floor (0.02) so RFT has signal.
    assert grade(sample, _row("cmo-001", "INV-1")) <= 0.02


def test_data_audit_accepts_committed_splits_and_flags_coverage_gaps() -> None:
    report = audit_rft_datasets(
        train_path=SPLITS[0],
        validation_path=SPLITS[1],
        eval_paths=[SPLITS[2]],
        grader_path=GRADER_V2,
    )

    assert report["ready"] is True, report["errors"]
    assert report["splits"]["eval"]["gold_min_score"] == 1.0
    assert any("evidence-gap reporting is untested" in w for w in report["warnings"])
    assert len(report["provenance"]["files"]) == 4


def test_data_audit_blocks_eval_leakage_and_duplicate_prompts(tmp_path: Path) -> None:
    train = [_row("cmo-001", "INV-1", "a"), _row("cmo-001", "INV-1", "a ")]
    validation = [_row("cmo-002", "INV-2", "b")]
    leaked = _row("cmo-001", "INV-9", "c")
    paths = _write(tmp_path, train=train, validation=validation, eval=[leaked])

    report = audit_rft_datasets(
        train_path=paths["train"], validation_path=paths["validation"], eval_paths=[paths["eval"]]
    )

    assert report["ready"] is False
    assert any("duplicate normalized prompt" in e for e in report["errors"])
    assert any("leakage train->eval on supplier_id" in e for e in report["errors"])


def test_data_audit_detects_supplier_alias_leakage(tmp_path: Path) -> None:
    train = _row("cmo-001", "INV-1")
    train["metadata"]["supplier_name"] = "Aster Ridge Biomanufacturing"
    evaluation = _row("sup-001", "INV-3")
    evaluation["metadata"]["supplier_name"] = "  ASTER RIDGE   BIOMANUFACTURING "
    paths = _write(
        tmp_path, train=[train], validation=[_row("sup-002", "INV-2")], eval=[evaluation]
    )
    report = audit_rft_datasets(
        train_path=paths["train"], validation_path=paths["validation"], eval_paths=[paths["eval"]]
    )
    assert report["ready"] is False
    assert any("leakage train->eval on supplier_name" in error for error in report["errors"])


def test_prepare_prompts_removes_answer_hints_without_changing_labels(tmp_path: Path) -> None:
    row = read_jsonl(SPLITS[0])[0]
    source = _write(tmp_path, original=[row])["original"]
    original_bytes = source.read_bytes()
    out = tmp_path / "prepared.jsonl"

    report = prepare_rft_prompts(source=source, out=out)

    assert report["rows_with_label_hints_removed"] == 1
    prepared = read_jsonl(out)[0]
    payload = json.loads(prepared["messages"][-1]["content"])
    assert "expected_decision_state" not in payload["line"]
    assert "issue_category" not in payload["line"]
    assert "scenario_id" not in payload["line"]
    assert "scenario_hint" not in payload
    assert "risk_examples" not in payload["supplier"]
    assert "output_type\":\"expert_evidence" in prepared["messages"][0]["content"]
    expected = copy.deepcopy(row["expected_output_json"])
    expected["correlation"]["waypoint_run_id"] = "unknown"
    assert prepared["expected_output_json"] == expected
    assert prepared["ground_truth"] == row["ground_truth"]
    assert prepared["metadata"]["prompt_preparation"]["unprovided_run_id_normalized_to_unknown"]
    assert source.read_bytes() == original_bytes
    assert prepare_rft_prompts(source=source, out=out)["out_sha256"] == report["out_sha256"]


def test_prepare_prompts_preserves_a_supplied_run_id(tmp_path: Path) -> None:
    row = read_jsonl(SPLITS[0])[0]
    payload = json.loads(row["messages"][-1]["content"])
    payload["correlation"] = {"waypoint_run_id": "visible-run"}
    row["messages"][-1]["content"] = json.dumps(payload)
    row["expected_output_json"]["correlation"]["waypoint_run_id"] = "visible-run"
    row["expected"]["text"] = json.dumps(row["expected_output_json"])
    source = _write(tmp_path, original=[row])["original"]
    out = tmp_path / "prepared.jsonl"

    prepare_rft_prompts(source=source, out=out)

    prepared = read_jsonl(out)[0]
    assert prepared["expected_output_json"]["correlation"]["waypoint_run_id"] == "visible-run"
    assert not prepared["metadata"]["prompt_preparation"]["unprovided_run_id_normalized_to_unknown"]


def test_calibration_rejects_missing_duplicate_or_unmatched_output_ids(tmp_path: Path) -> None:
    rows = read_jsonl(SPLITS[1])[:2]
    paths = _write(tmp_path, validation=rows)
    dataset = paths["validation"]
    gold = tmp_path / "gold.jsonl"
    write_gold_answer_outputs(dataset_path=dataset, out_path=gold)
    captures = [
        {
            "id": row["id"],
            "output_text": json.dumps(row["expected_output_json"]),
            "usage": {"input_tokens": 20, "output_tokens": 10},
            "latency_ms": 123.0,
        }
        for row in rows
    ]

    def calibrate(cases: list[dict[str, Any]]) -> dict[str, Any]:
        path = _write(tmp_path, outputs=cases)["outputs"]
        return calibrate_grader(dataset_path=dataset, outputs_path=path, grader_path=GRADER_V2)

    matched = calibrate(list(reversed(captures)))
    assert matched["ready"] is True
    assert matched["scores"][0]["id"] == rows[1]["id"]
    assert matched["scores"][0]["usage"]["input_tokens"] == 20
    assert matched["scores"][0]["latency_ms"] == 123.0
    partial = calibrate(captures[:1])
    assert not partial["ready"]
    assert partial["missing_dataset_rows"] == [rows[1]["id"]]
    duplicate = calibrate([captures[0], captures[0]])
    assert not duplicate["ready"]
    assert duplicate["duplicate_outputs"] == [rows[0]["id"]]
    unknown = calibrate([captures[0], {**captures[1], "id": "unknown"}])
    assert not unknown["ready"]
    assert unknown["unmatched_outputs"] == ["unknown"]
    assert unknown["scored_rows"] == 1
    untagged = calibrate([{**captures[0], "id": None}, captures[1]])
    assert not untagged["ready"]
    assert untagged["positional_outputs"] == ["output-index:0"]
    with pytest.raises(ValueError, match="latency_ms"):
        calibrate([{**captures[0], "latency_ms": -1}, captures[1]])

    incomplete = _write(tmp_path, teacher=captures[:1])["teacher"]
    complete = _write(tmp_path, base=captures)["base"]
    plan = build_model_output_calibration_plan(
        dataset_path=dataset,
        grader_path=GRADER_V2,
        gold_outputs_path=gold,
        teacher_outputs_path=incomplete,
        base_outputs_path=complete,
    )
    assert not plan["ready_for_threshold_selection"]
    assert "mismatched output IDs" in plan["next_step"]


@pytest.mark.parametrize("value", ["nan", "inf", "1.1"])
def test_calibration_rejects_nonfinite_or_out_of_range_grader_scores(
    tmp_path: Path, value: str
) -> None:
    dataset = _write(tmp_path, validation=read_jsonl(SPLITS[1])[:1])["validation"]
    gold = tmp_path / "gold.jsonl"
    write_gold_answer_outputs(dataset_path=dataset, out_path=gold)
    grader = tmp_path / "bad_grader.py"
    grader.write_text(
        f"def grade(sample, item):\n    return float('{value}')\n", encoding="utf-8"
    )
    with pytest.raises(ValueError, match="grader score must be between"):
        calibrate_grader(dataset_path=dataset, outputs_path=gold, grader_path=grader)


@pytest.mark.parametrize("placement", ["grader", "reinforcement", "both"])
def test_threshold_placement_propagates_to_manifest_and_template(
    tmp_path: Path, placement: str
) -> None:
    paths = _write(
        tmp_path, train=[_row("cmo-001", "INV-1")], validation=[_row("cmo-002", "INV-2")]
    )
    manifest = package_rft_assets(
        train_path=paths["train"],
        validation_path=paths["validation"],
        grader_path=GRADER_V2,
        out_dir=tmp_path / "pkg",
        agent="contract-policy-expert",
        base_model="mai-code-2-flash-2026-11-17",
        pass_threshold=0.9,
        threshold_placement=placement,
    )
    template = json.loads(Path(manifest["artifacts"]["submit_template"]).read_text("utf-8"))
    reinforcement = template["method"]["reinforcement"]
    assert manifest["threshold_placement"] == placement
    assert manifest["threshold_placement_rationale"]
    assert reinforcement.get("pass_threshold") == (
        0.9 if placement in {"both", "reinforcement"} else None
    )
    assert reinforcement["grader"].get("pass_threshold") == (
        0.9 if placement in {"both", "grader"} else None
    )


@pytest.fixture
def offline_inputs(tmp_path: Path) -> dict[str, Path]:
    sources = tmp_path / "sources"
    sources.mkdir()
    prepared = tmp_path / "prepared"
    paths: dict[str, Path] = {"source_root": sources, "package": tmp_path / "package"}
    for name, source in zip(
        ("train", "validation", "eval", "challenge"), [*SPLITS, CHALLENGE], strict=True
    ):
        original = sources / f"{name}.jsonl"
        original.write_bytes(source.read_bytes())
        paths[f"original_{name}"] = original
        paths[name] = prepared / f"{name}.jsonl"
        prepare_rft_prompts(source=original, out=paths[name])

    package_rft_assets(
        train_path=paths["train"],
        validation_path=paths["validation"],
        grader_path=GRADER_V2,
        out_dir=paths["package"],
        agent="contract-policy-expert",
        pass_threshold=0.9,
        preset="mai2-waypoint-local",
        **MAI2_WAYPOINT_PRESET,
    )
    paths["suite"] = tmp_path / "grader-suite.json"
    build_grader_validation_suite(package_dir=paths["package"], out=paths["suite"])
    return paths


def test_offline_preflight_flags_directive_references_without_claiming_remote_readiness(
    offline_inputs: dict[str, Path], tmp_path: Path
) -> None:
    report = run_offline_preflight(
        train_path=offline_inputs["train"],
        validation_path=offline_inputs["validation"],
        eval_paths=[offline_inputs["eval"]],
        challenge_path=offline_inputs["challenge"],
        grader_path=GRADER_V2,
        package_dir=offline_inputs["package"],
        grader_suite_path=offline_inputs["suite"],
        corpus_path=CORPUS,
        source_root=offline_inputs["source_root"],
        out=tmp_path / "preflight.json",
    )
    assert report["local_checks_passed"] is False
    assert report["ready_to_run_meter"] is False
    assert report["remote_checks_run"] is False
    assert report["reports"]["candidate"]["review_statuses"] == ["pending_human_review"]
    checks = {check["name"]: check for check in report["checks"]}
    assert checks["advisory_reference_boundary"]["rows_with_apparent_directives"] == 126
    assert not checks["advisory_reference_boundary"]["ok"]
    assert not checks["corpus_alignment"]["ok"]
    assert all(
        check["ok"]
        for name, check in checks.items()
        if name not in {"advisory_reference_boundary", "corpus_alignment"}
    )
    assert checks["grader_robustness"]["max_known_bad_score"] <= 0.5
    assert checks["trainer_wrapper_parity"]["sample_comparisons"] > 0
    assert checks["trainer_wrapper_parity"]["mismatches"] == 0
    assert checks["package_consistency"]["eval_samples"] == checks["package_consistency"][
        "validation_rows"
    ]


def test_advisory_reference_screen_distinguishes_support_from_directives(tmp_path: Path) -> None:
    challenge = read_jsonl(CHALLENGE)
    safe = copy.deepcopy(challenge[2])
    safe["expected_output_json"]["summary"] = (
        "Do not approve payment; the cited evidence supports controller review."
    )
    safe["ground_truth"]["recommended_action"] = safe["expected_output_json"]["summary"]
    unsafe = copy.deepcopy(challenge[0])
    path = _write(tmp_path, cases=[safe, unsafe])["cases"]

    issues, details = _check_advisory_references([path])

    assert len(issues) == 1
    assert details["rows_checked"] == 2
    assert details["rows_with_apparent_directives"] == 1
    assert details["examples"][0]["id"] == unsafe["id"]


def test_offline_preflight_rejects_stale_corpus_even_with_neutral_references(
    offline_inputs: dict[str, Path], tmp_path: Path
) -> None:
    prepared: dict[str, Path] = {}
    for name in ("train", "validation", "eval", "challenge"):
        source = offline_inputs[f"original_{name}"]
        rows = read_jsonl(source)
        for row in rows:
            neutral = "Evidence supports controller review of the described charge."
            row["ground_truth"]["recommended_action"] = neutral
            row["expected_output_json"]["summary"] = neutral
            for evidence in row["expected_output_json"]["evidence"]:
                evidence["claim"] = neutral
            row["expected"]["text"] = json.dumps(row["expected_output_json"], sort_keys=True)
        source.write_text(
            "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8"
        )
        prepared[name] = tmp_path / "neutral" / f"{name}.jsonl"
        prepare_rft_prompts(source=source, out=prepared[name])

    package = tmp_path / "neutral-package"
    package_rft_assets(
        train_path=prepared["train"],
        validation_path=prepared["validation"],
        grader_path=GRADER_V2,
        out_dir=package,
        agent="contract-policy-expert",
        pass_threshold=0.9,
        preset="mai2-waypoint-local",
        **MAI2_WAYPOINT_PRESET,
    )
    suite = tmp_path / "neutral-suite.json"
    build_grader_validation_suite(package_dir=package, out=suite)
    report = run_offline_preflight(
        train_path=prepared["train"],
        validation_path=prepared["validation"],
        eval_paths=[prepared["eval"]],
        challenge_path=prepared["challenge"],
        grader_path=GRADER_V2,
        package_dir=package,
        grader_suite_path=suite,
        corpus_path=CORPUS,
        source_root=offline_inputs["source_root"],
        out=tmp_path / "neutral-preflight.json",
    )
    assert report["local_checks_passed"] is False
    checks = {check["name"]: check for check in report["checks"]}
    assert checks["advisory_reference_boundary"]["ok"]
    assert not checks["corpus_alignment"]["ok"]
    assert report["ready_to_run_meter"] is False


def test_corpus_alignment_detects_stale_and_tampered_sources(tmp_path: Path) -> None:
    row = read_jsonl(CHALLENGE)[0]
    valid = _write(tmp_path, valid=[row])["valid"]
    issues, details = _check_corpus_alignment([valid], CORPUS)
    assert not issues
    assert details["rows"] == 1

    changed = copy.deepcopy(row)
    changed["retrieved_context"]["contract_policy_sections"][0]["text"] += " altered"
    payload = json.loads(changed["messages"][-1]["content"])
    payload["retrieved_context"] = changed["retrieved_context"]["contract_policy_sections"]
    changed["messages"][-1]["content"] = json.dumps(payload)
    stale = copy.deepcopy(row)
    stale["metadata"]["supplier_id"] = "cmo-013"
    missing = copy.deepcopy(row)
    missing["retrieved_context"]["contract_policy_sections"][0]["document"] = (
        "data/contracts/source-markdown/does-not-exist.md"
    )
    outside_file = tmp_path / "outside.md"
    outside_file.write_text("# Existing outside file\n", encoding="utf-8")
    outside = copy.deepcopy(row)
    outside["retrieved_context"]["contract_policy_sections"][0]["document"] = str(outside_file)
    wrong_invoice = copy.deepcopy(row)
    wrong_invoice["metadata"]["invoice_id"] = "wrong-invoice"
    paths = _write(
        tmp_path,
        changed=[changed],
        stale=[stale],
        missing=[missing],
        outside=[outside],
        wrong_invoice=[wrong_invoice],
    )
    issues, details = _check_corpus_alignment(list(paths.values()), CORPUS)
    assert details["rows"] == 5
    assert any("retrieved section differs from corpus" in issue for issue in issues)
    assert any("supplier identity does not match corpus" in issue for issue in issues)
    assert any("corpus source missing" in issue for issue in issues)
    assert any(f"outside root: {outside_file}" in issue for issue in issues)
    assert any("prompt and reference retrieved contexts differ" in issue for issue in issues)
    assert any("prompt invoice differs from metadata" in issue for issue in issues)


def test_preflight_automatic_batch_size_requires_omitting_the_field() -> None:
    assert _hyperparameter_errors({}) == []
    assert _hyperparameter_errors({"batch_size": -1}) == [
        "batch_size must be an integer in [1, 256]; omit it for automatic"
    ]


@pytest.mark.parametrize(
    "tamper", ["artifact", "eval_samples", "bad_hyperparameter", "suite", "source"]
)
def test_offline_preflight_cli_fails_and_writes_report_for_tampering(
    offline_inputs: dict[str, Path],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    tamper: str,
) -> None:
    package = offline_inputs["package"]
    manifest_path = package / "manifest.json"
    if tamper == "artifact":
        artifact = package / "contract-policy-expert-rft-train.jsonl"
        artifact.write_bytes(artifact.read_bytes() + b"\n")
    elif tamper in {"eval_samples", "bad_hyperparameter"}:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if tamper == "eval_samples":
            manifest["hyperparameters"]["eval_samples"] = 17
        else:
            manifest["hyperparameters"]["n_epochs"] = -1
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    elif tamper == "suite":
        suite = json.loads(offline_inputs["suite"].read_text(encoding="utf-8"))
        suite["requests"]["wrong_invoice"]["expected_score"] = 1.0
        offline_inputs["suite"].write_text(json.dumps(suite), encoding="utf-8")
    else:
        original = offline_inputs["original_train"]
        original.write_bytes(original.read_bytes() + b"\n")

    report_path = tmp_path / "blocked.json"
    code = main(
        [
            "rft", "preflight",
            "--train", str(offline_inputs["train"]),
            "--validation", str(offline_inputs["validation"]),
            "--eval", str(offline_inputs["eval"]),
            "--challenge", str(offline_inputs["challenge"]),
            "--grader", str(GRADER_V2),
            "--package-dir", str(package),
            "--grader-suite", str(offline_inputs["suite"]),
            "--corpus-path", str(CORPUS),
            "--source-root", str(offline_inputs["source_root"]),
            "--out", str(report_path),
            "--json",
        ]
    )
    report = json.loads(capsys.readouterr().out)
    assert code == 1
    assert report_path.exists()
    assert report["local_checks_passed"] is False
    assert report["errors"]
    checks = {check["name"]: check for check in report["checks"]}
    failed_check = "reference_consistency" if tamper == "source" else "package_consistency"
    assert not checks[failed_check]["ok"]
    if tamper == "bad_hyperparameter":
        assert any("n_epochs must be a positive integer" in error for error in report["errors"])


def test_mai2_package_places_threshold_in_grader_and_emits_clean_submit_template(
    tmp_path: Path,
) -> None:
    paths = _write(
        tmp_path, train=[_row("cmo-001", "INV-1")], validation=[_row("cmo-002", "INV-2")]
    )

    manifest = package_rft_assets(
        train_path=paths["train"],
        validation_path=paths["validation"],
        grader_path=GRADER_V2,
        out_dir=tmp_path / "rft",
        agent="contract-policy-expert",
        base_model="mai-code-2-flash-2026-11-17",
        pass_threshold=0.9,
        include_response_format=False,
        training_type="developerTier",
        seed=7,
        hyperparameters={"n_epochs": 3, "eval_samples": 50},
        grader_image_tag="2025-05-08",
        threshold_placement="grader",
    )

    template = json.loads(Path(manifest["artifacts"]["submit_template"]).read_text("utf-8"))
    reinforcement = template["method"]["reinforcement"]
    assert "pass_threshold" not in reinforcement
    assert reinforcement["grader"]["pass_threshold"] == 0.9
    assert reinforcement["grader"]["image_tag"] == "2025-05-08"
    assert "endpoint_grader_fallback" not in reinforcement
    assert "status" not in template
    assert template["trainingType"] == "developerTier"
    assert manifest["grader_version"] == "contract-policy-evidence-v2"
    assert manifest["remote_grader_validation"] == "pending_not_run"
    assert manifest["ready_for_live_submit"] is False
    assert any("eval_samples=50 exceeds 1" in w for w in manifest["warnings"])


def test_package_rejects_unknown_hyperparameters(tmp_path: Path) -> None:
    paths = _write(
        tmp_path, train=[_row("cmo-001", "INV-1")], validation=[_row("cmo-002", "INV-2")]
    )
    with pytest.raises(ValueError, match="unknown hyperparameters"):
        package_rft_assets(
            train_path=paths["train"],
            validation_path=paths["validation"],
            grader_path=GRADER_V2,
            out_dir=tmp_path / "rft",
            agent="contract-policy-expert",
            base_model="mai-code-2-flash-2026-11-17",
            hyperparameters={"n_epoch": 3},
        )


def test_cli_preset_values_can_be_overridden(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    paths = _write(
        tmp_path, train=[_row("cmo-001", "INV-1")], validation=[_row("cmo-002", "INV-2")]
    )
    code = main(
        [
            "rft",
            "package",
            "--train",
            str(paths["train"]),
            "--validation",
            str(paths["validation"]),
            "--grader",
            str(GRADER_V2),
            "--out-dir",
            str(tmp_path / "rft"),
            "--preset",
            "mai2-alaska-e6",
            "--hyperparameter",
            "n_epochs=2",
            "--pass-threshold",
            "0.9",
            "--json",
        ]
    )

    assert code == 0
    manifest = json.loads(capsys.readouterr().out)
    assert manifest["base_model"] == "mai-code-2-flash-2026-11-17"
    assert manifest["hyperparameters"]["n_epochs"] == 2
    assert manifest["hyperparameters"]["learning_rate_multiplier"] == 2
    assert manifest["threshold_placement"] == "grader"
    assert manifest["response_format_mode"] == "omitted"


def _write(tmp_path: Path, **splits: list[dict[str, Any]]) -> dict[str, Path]:
    paths = {}
    for name, rows in splits.items():
        path = tmp_path / f"{name}.jsonl"
        path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
        paths[name] = path
    return paths


def _row(supplier: str, invoice: str, prompt: str | None = None) -> dict[str, Any]:
    ref = f"contract-{supplier}.md#packaging"
    expected = {
        "agent": "contract-policy-expert",
        "plane": "foundryiq",
        "invoice_id": invoice,
        "output_type": "expert_evidence",
        "evidence": [
            {
                "claim": "Request packaging authorization or supplier credit.",
                "supports": "recover",
                "source_ref": ref,
                "classification": "confidential",
                "confidence": 0.86,
            }
        ],
        "unsupported": [],
        "summary": "Request packaging authorization or supplier credit.",
        "correlation": {"waypoint_run_id": "ledgerfield-seed", "waypoint_invoice_id": invoice},
    }
    return copy.deepcopy(
        {
            "id": f"contract-policy:{supplier}:{invoice}:{prompt or ''}",
            "messages": [
                {"role": "developer", "content": "Return strict expert_evidence JSON only."},
                {"role": "user", "content": f"Review invoice {invoice}. {prompt or ''}"},
            ],
            "expected": {"text": json.dumps(expected)},
            "expected_output_json": expected,
            "retrieved_context": {"contract_policy_sections": [{"source_ref": ref}]},
            "ground_truth": {
                "acceptable_citations": [ref],
                "expected_supports": "recover",
                "recommended_action": "Request packaging authorization or supplier credit.",
            },
            "metadata": {
                "training_agent": "contract-policy-expert",
                "invoice_id": invoice,
                "supplier_id": supplier,
            },
        }
    )


V3_DIR = DATASETS / "evidence-only-v3"
GRADER_V3 = ROOT / "graders" / "contract-policy-expert" / "contract_policy_evidence_grader_v3.py"
V3_SPLITS = [V3_DIR / f"{name}.jsonl" for name in ("train", "validation", "eval", "challenge")]


def test_evidence_only_v3_sources_are_deterministic_and_directive_free() -> None:
    from caliber.contract_policy_evidence_only import verify_evidence_only_v3
    from caliber.rft_preflight import _DIRECTIVE

    assert verify_evidence_only_v3(dataset_dir=DATASETS, out_dir=V3_DIR) == []
    for path in V3_SPLITS:
        for row in read_jsonl(path):
            gold = row["expected_output_json"]
            texts = [gold["summary"], *gold["unsupported"]]
            texts += [item["claim"] for item in gold["evidence"]]
            assert not any(_DIRECTIVE.search(text) for text in texts), row["id"]
            assert row["metadata"]["evidence_only_reference"]["support_review_flag"] in {
                True, False
            }
            assert "recommended_action" not in row["ground_truth"]


def test_v3_grader_caps_directives_and_affirmed_gaps(tmp_path: Path) -> None:
    report = run_grader_robustness(
        dataset_paths=V3_SPLITS,
        grader_path=GRADER_V3,
        pass_threshold=0.9,
        out=tmp_path / "robustness.json",
    )

    assert report["violation_count"] == 0
    assert report["perturbations"]["gold"]["min"] == 1.0
    for name in ("directive_summary", "directive_claim", "should_directive"):
        assert report["perturbations"][name]["n"] == report["rows"]
        assert report["perturbations"][name]["max"] <= 0.2
    assert report["perturbations"]["affirmed_gap"]["max"] <= 0.4


def test_v3_grader_allows_negated_availability_but_flags_affirmed_evidence() -> None:
    affirms = load_grader(GRADER_V3).__globals__["_affirms_available_evidence"]

    assert not affirms(["No written approval identifying the lot and ship date was supplied."])
    assert not affirms(["Worksheet YLD-1 contents are not visible, so the yield is unknown."])
    assert affirms(["Worksheet YLD-1 contents are visible, so the yield is unknown."])
    assert affirms(["The written approval was supplied."])


def test_preflight_accepts_v3_challenge_provenance_only_with_historical_source() -> None:
    from caliber.rft_preflight import _challenge_label_provenance

    challenge = read_jsonl(V3_DIR / "challenge.jsonl")[0]["metadata"]
    assert _challenge_label_provenance(challenge)
    forged = copy.deepcopy(challenge)
    forged["historical_reference"]["label_source"] = "ledgerfield-seed"
    assert not _challenge_label_provenance(forged)
