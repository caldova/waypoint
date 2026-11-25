import copy

import pytest

from caliber.contract_policy_analyst_eval import paired_records


def rows(score):
    return [
        {
            "id": case, "run": run, "score": score,
            "task_sha256": f"task-{case}", "judge_sha256": "rubric",
            "judge_model": "gpt-6-astra", "reference_sha256": f"ref-{case}",
            "source_family": f"family-{case}",
        }
        for case in ("one", "two") for run in range(1, 6)
    ]


def test_pairs_case_means_not_repeated_runs():
    result = paired_records(rows(0.2), rows(0.4), resamples=200)
    assert result["unique_cases"] == 2
    assert result["attempts_per_arm"] == 10
    assert result["mean_difference"] == pytest.approx(0.2)


def test_missing_failed_attempt_cannot_be_silently_dropped():
    with pytest.raises(ValueError, match="identical cases"):
        paired_records(rows(0.2), rows(0.4)[:-1])


def test_duplicate_or_mismatched_judge_rejected():
    left = rows(0.2)
    with pytest.raises(ValueError, match="Duplicate"):
        paired_records(left + [left[0]], rows(0.4))
    right = copy.deepcopy(rows(0.4))
    right[0]["judge_model"] = "different-judge"
    with pytest.raises(ValueError, match="judge_model"):
        paired_records(left, right)
