from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from caliber.contract_evidence_benchmark import audit, build_scenarios, load_split, write_benchmark
from caliber.contract_evidence_grader_checks import (
    GRADER_PATH,
    PASS_THRESHOLD,
    evaluate,
    grader_module,
    run,
)

DATASET = (
    Path(__file__).resolve().parents[1] / "datasets" / "contract-evidence-analyst" / "benchmark-v1"
)


@pytest.fixture(scope="module")
def rows():
    return build_scenarios()


def _row(rows, outcome, **extra):
    for row in rows:
        if row["outcome"] != outcome:
            continue
        if all(extra_check(row) for extra_check in extra.values()):
            return row
    raise AssertionError(f"no {outcome} row")


def test_benchmark_audit_and_splits(rows):
    report = audit(rows)
    assert report["ok"], report
    assert report["counts"] == {"train": 146, "validation": 33, "dev_eval": 38, "final_test": 44}
    families = {
        split: {row["family"] for row in rows if row["split"] == split}
        for split in report["counts"]
    }
    for split, members in families.items():
        for other, other_members in families.items():
            if split != other:
                assert not members & other_members
    for row in rows:
        assert row["metadata"]["review_status"] == "pending_human_review"
        assert row["metadata"]["operational_records"] == "synthetic"


def test_committed_benchmark_matches_generator(tmp_path):
    manifest = write_benchmark(tmp_path)
    committed = json.loads((DATASET / "manifest.json").read_text(encoding="utf-8"))
    assert committed["splits"] == manifest["splits"]
    assert len(load_split(DATASET, "validation")) == 33


def test_task_has_no_answer_hints(rows):
    for row in rows:
        task = row["task"].lower()
        assert "role:" not in task
        assert "distractor" not in task
        assert (
            row["outcome"] not in {"approve_evidence", "missing_evidence"}
            or row["outcome"] not in task
        )


def test_audit_flags_cross_split_family(rows):
    broken = copy.deepcopy(rows)
    victim = next(row for row in broken if row["split"] == "train")
    sibling = next(row for row in broken if row["family"] == victim["family"] and row is not victim)
    sibling["split"] = "final_test"
    assert not audit(broken)["ok"]


def test_gold_scores_one_everywhere(rows):
    assert all(evaluate(row["reference"]["reference_output"], row)["score"] == 1.0 for row in rows)


def test_perturbations_separate_at_frozen_threshold(rows):
    report = run(rows)
    assert report["separated"], report["misclassified"][:5]
    assert report["max_critical"] < PASS_THRESHOLD <= report["min_minor_or_gold"]


def test_grader_is_sandbox_safe():
    source = GRADER_PATH.read_text(encoding="utf-8")
    assert "compile(" not in source
    assert "eval(" not in source.replace("evaluate(", "")
    imports = {
        line.split()[1] for line in source.splitlines() if line.startswith(("import ", "from "))
    }
    assert imports <= {"__future__", "json", "re", "typing"}


def test_specific_valid_gaps_are_not_capped(rows):
    row = _row(
        rows, "missing_evidence", has_gap=lambda r: len(r["reference"]["required_gaps"]) == 1
    )
    out = copy.deepcopy(row["reference"]["reference_output"])
    out["unsupported"] = out["unsupported"] + [
        "No supplier explanation for the charge amount was provided.",
        "Purchase-order line coverage for this charge is not shown.",
    ]
    result = evaluate(out, row)
    assert result["score"] >= PASS_THRESHOLD, result


def test_negated_boundary_language_is_allowed(rows):
    row = _row(rows, "recover")
    out = copy.deepcopy(row["reference"]["reference_output"])
    out["summary"] = (
        "Evidence indicates the charge is not supported. "
        "This is not a payment decision; no dispute was opened."
    )
    assert evaluate(out, row)["score"] == 1.0


@pytest.mark.parametrize(
    "summary",
    [
        "Recommend that finance withhold payment.",
        "The supplier must be credited for this line.",
        "We have disputed the charge with the supplier.",
        "Payment released after review.",
        "Approve the invoice.",
    ],
)
def test_directives_and_claimed_actions_fail(rows, summary):
    row = _row(rows, "recover")
    out = copy.deepcopy(row["reference"]["reference_output"])
    out["summary"] = summary
    result = evaluate(out, row)
    assert result["score"] < PASS_THRESHOLD and "boundary_violation" in result["flags"]


def test_invented_numbers_reduce_claim_score(rows):
    row = _row(rows, "recover")
    out = copy.deepcopy(row["reference"]["reference_output"])
    for item in out["evidence"]:
        item["claim"] = "The contract caps this at USD 987,654.32."
    result = evaluate(out, row)
    assert result["components"]["claims"] == 0.0
    assert result["score"] < 1.0


@pytest.mark.parametrize(
    "payload",
    [
        '{"invoice_line_id": "X", "invoice_line_id": "Y", '
        '"evidence": [], "unsupported": [], "summary": ""}',
        '{"invoice_line_id": "X", "evidence": [{"source_ref": "C1", '
        '"classification": "contract_term", "supports": "maybe", "claim": "c"}], '
        '"unsupported": [], "summary": "s"}',
        '{"invoice_line_id": "X", "evidence": [], "unsupported": [], "summary": "s"}',
        '{"invoice_line_id": NaN}',
        "[1, 2, 3]",
    ],
)
def test_schema_invalid_outputs_score_zero(rows, payload):
    assert evaluate(payload, rows[0])["score"] == 0.0


def test_conflicting_duplicate_citations_do_not_hedge(rows):
    row = _row(rows, "recover")
    out = copy.deepcopy(row["reference"]["reference_output"])
    primary = next(ref for ref, spec in row["reference"]["refs"].items() if spec.get("primary"))
    out["evidence"].append(
        {
            "source_ref": primary,
            "classification": "contract_term",
            "supports": "approve",
            "claim": "x",
        }
    )
    assert evaluate(out, row)["score"] < PASS_THRESHOLD


def test_trainer_wrapper_shapes_score_identically(rows):
    row = rows[0]
    text = json.dumps(row["reference"]["reference_output"])
    item = {"reference": json.dumps(row["reference"])}
    module = grader_module()
    scores = {
        module.grade({"output_text": text}, item),
        module.grade({"output_json": row["reference"]["reference_output"]}, item),
        module.grade({"choices": [{"message": {"content": text}}]}, item),
        module.grade(text, item),
        module.grade("```json\n" + text + "\n```", item),
    }
    assert scores == {1.0}


def test_rft_package_excludes_held_out_and_caps_eval_samples(tmp_path):
    from caliber.contract_evidence_eval import AGENT_DIR
    from caliber.contract_evidence_rft import package

    manifest = package(AGENT_DIR / ".agent_configs" / "baseline" / "instructions.md", tmp_path)
    payload = json.loads((tmp_path / "payload.json").read_text(encoding="utf-8"))
    rl = payload["method"]["reinforcement"]
    held = {r["id"] for s in ("dev_eval", "final_test") for r in load_split(DATASET, s)}
    for split in ("train", "validation"):
        text = (tmp_path / f"contract-evidence-rft-{split}.jsonl").read_text(encoding="utf-8")
        rows = [json.loads(x) for x in text.splitlines()]
        assert not {r["id"] for r in rows} & held
        assert [m["role"] for m in rows[0]["messages"]] == ["developer", "user"]
    validation_rows = manifest["artifacts"]["validation"]["rows"]
    assert rl["hyperparameters"]["eval_samples"] == validation_rows == 33
    assert rl["grader"]["pass_threshold"] == PASS_THRESHOLD
    assert rl["grader"]["source"] == GRADER_PATH.read_text(encoding="utf-8")
    assert manifest["gold_parity"]["train"]["gold_below_threshold"] == 0


def _run_record(case_id, score, task_sha="t", flags=()):
    return {
        "id": case_id,
        "family": case_id.split("--")[0],
        "outcome": "approve_evidence",
        "score": score,
        "passed": score >= PASS_THRESHOLD,
        "flags": list(flags),
        "task_sha256": task_sha,
        "grader_version": "v1",
    }


def test_paired_compare_pairs_cases_and_rejects_mismatched_prompts(monkeypatch):
    from caliber import contract_evidence_eval as ev

    arms = {
        "a": [_run_record(f"f{i}--x", 0.6) for i in range(6)],
        "b": [_run_record(f"f{i}--x", 0.6) for i in range(6)],
    }
    monkeypatch.setattr(ev, "load_records", lambda arm, split: arms[arm])
    same = ev.paired_compare("a", "b", "dev_eval", resamples=200)
    assert same["mean_diff"] == 0 and same["sign_flip_p"] == 1.0
    assert same["cases_tied"] == 6 and "holdout_status" not in same

    arms["b"] = [_run_record(f"f{i}--x", 1.0, flags=["false_approval"]) for i in range(6)]
    better = ev.paired_compare("a", "b", "final_test", resamples=200)
    assert better["mean_diff"] == pytest.approx(0.4)
    assert better["sign_flip_p"] == pytest.approx(2 / 64)
    assert better["critical_flags"]["false_approval"] == {"a": 0, "b": 6}
    assert better["holdout_status"] == ev.FINAL_TEST_STATUS["label"]

    arms["b"][0]["task_sha256"] = "other"
    with pytest.raises(SystemExit):
        ev.paired_compare("a", "b", "dev_eval", resamples=10)


def test_known_label_defects_are_excluded_from_optimizer_rows_only():
    from caliber import contract_evidence_eval as ev

    known = frozenset(ev.KNOWN_LABEL_DEFECTS)
    rows = ev.optimizer_rows("train", 99, exclude=known)
    assert not {r["id"] for r in rows} & known
    items = ev.review_items()
    assert items["labels_modified"] is False
    assert {i["id"] for i in items["known_label_defects"]["items"]} == known
    for item in items["known_label_defects"]["items"]:
        row = next(r for r in load_split(DATASET, item["split"]) if r["id"] == item["id"])
        assert "wrong_entity" in row["modifiers"]
