import copy
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from caliber.contract_policy_analyst_eval import hosted_call, inference_cost, paired_records


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


def test_token_estimate_uses_current_astra62_and_cached_meter():
    cost = inference_cost("gpt-6.2-astra", {
        "input_tokens": 1000, "output_tokens": 100,
        "input_tokens_details": {"cached_tokens": 500},
    })
    assert cost["usd"] == pytest.approx((500 * 8 + 500 * 0.4 + 100 * 40) / 1_000_000)
    assert "retrieval/indexing" in cost["excludes"]


def test_missing_usage_is_unknown_not_zero_cost():
    assert inference_cost("gpt-6-astra", None)["usd"] is None
    assert inference_cost(
        "unresolved-model", {"input_tokens": 1, "output_tokens": 1}
    )["usd"] is None


@pytest.mark.parametrize("metadata", [None, {"cpa_attempt_id": "nonce"}])
def test_hosted_call_omits_null_metadata_and_preserves_capture_nonce(monkeypatch, metadata):
    identity = pytest.importorskip("azure.identity")
    openai = pytest.importorskip("openai")
    credential = MagicMock()
    credential.get_token.return_value = SimpleNamespace(token="fixture-token")
    client = MagicMock()
    client.__enter__.return_value = client
    response = MagicMock(output_text="{}", id="response-fixture")
    response.model_dump.return_value = {"model": "model", "usage": None}
    client.responses.create.return_value = response
    monkeypatch.setattr(identity, "AzureCliCredential", lambda **kwargs: credential)
    monkeypatch.setattr(openai, "OpenAI", lambda **kwargs: client)

    result = hosted_call("https://example.test/api/projects/study", "1", "task",
                         metadata=metadata)

    assert result["error"] is None
    sent = client.responses.create.call_args.kwargs
    if metadata is None:
        assert "metadata" not in sent
    else:
        assert sent["metadata"] == metadata
