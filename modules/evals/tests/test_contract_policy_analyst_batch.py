import copy
import hashlib
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from caliber.contract_policy_analyst_batch import (
    cited_refs,
    inference_failure_record,
    record_key,
    summary,
    validate_judge,
    verify_capture,
    write_record,
)


def test_capture_binds_nonce_runtime_and_exact_payload():
    record_hash = pytest.importorskip("castia.observe.tool_capture").record_hash

    doc = {
        "schema": "castia.tool_capture/v1", "complete": True, "status": "ok",
        "tool_calls": [], "request_metadata": {"cpa_attempt_id": "nonce"},
        "input_sha256": "task",
        "output_sha256": hashlib.sha256(b"response").hexdigest(),
        "provenance": {
            "model": "model", "route": "account", "reasoning_effort": "low",
            "instructions_sha256": "instructions", "tools_sha256": "tools",
        },
    }
    doc["record_sha256"] = record_hash(doc)
    verify_capture(doc, {"output_text": "response"}, "task", "nonce", "model")
    verify_capture(
        doc, {"output_text": "response"}, "task", "nonce", "model",
        instructions_hash="instructions", tools_hash="tools",
    )
    for expected in (
        {"instructions_hash": "wrong"}, {"tools_hash": "wrong"},
    ):
        with pytest.raises(ValueError, match="frozen configuration"):
            verify_capture(doc, {"output_text": "response"}, "task", "nonce", "model",
                           **expected)
    for field, value in (("complete", False), ("output_sha256", "other")):
        changed = copy.deepcopy(doc)
        changed[field] = value
        changed["record_sha256"] = record_hash(changed)
        with pytest.raises(ValueError):
            verify_capture(changed, {"output_text": "response"}, "task", "nonce", "model")
    with pytest.raises(ValueError, match="nonce"):
        verify_capture(doc, {"output_text": "response"}, "task", "different", "model")


@pytest.mark.parametrize("score", [True, 0, 6, "5"])
def test_judge_scores_cannot_be_fabricated_from_wrong_shape(score):
    with pytest.raises(ValueError):
        validate_judge({
            "dimensions": [{"id": "dimension", "score": score, "reason": "reason"}],
            "critical_flags": [],
        }, {"dimension"})


def test_judge_requires_each_dimension_once_and_real_reasons():
    validate_judge({
        "dimensions": [{"id": "dimension", "score": 5, "reason": "Source supports the claim."}],
        "critical_flags": [],
    }, {"dimension"})
    with pytest.raises(ValueError):
        validate_judge({"dimensions": [], "critical_flags": []}, {"dimension"})


def test_partial_batch_does_not_publish_complete_quality_numbers():
    assert summary([], 600) == {
        "responses": 0, "expected_responses": 600, "status": "pending",
    }
    assert summary([{"score": 1}], 600) == {
        "responses": 1, "expected_responses": 600, "status": "incomplete",
    }


def test_records_are_create_only_and_citations_are_unique(tmp_path):
    path = tmp_path / "record.json"
    write_record(path, {"original": True})
    with pytest.raises(FileExistsError):
        write_record(path, {"replacement": True})
    assert cited_refs({
        "traceability": {"source_refs": ["source"]},
        "evidence": [{"source_ref": "source"}, {"source_ref": "second"}],
    }) == {"source", "second"}


def test_case_namespace_cannot_become_windows_alternate_data_stream(tmp_path):
    key = record_key("cpa-expanded:CPA1-F001-L001", 1)
    assert ":" not in key and "/" not in key and "\\" not in key
    path = tmp_path / f"{key}.graded.json"
    write_record(path, {"id": "cpa-expanded:CPA1-F001-L001"})
    assert list(tmp_path.glob("*.graded.json")) == [path]


def test_citation_grounding_uses_verified_mappings_not_raw_snippet_list():
    from caliber.contract_policy_analyst_batch import grounded_citation_count

    adapted = {
        "reference_snippets": [{"document_path": "contract.md", "snippet": "returned text"}],
        "mappings": [
            {"source_ref": "contract.md#clause", "coverage_mode": "full_substantive_body",
             "observed_origins": [{"ref_id": "0"}]},
            {"source_ref": "missing.md#clause", "coverage_mode": "full_substantive_body",
             "observed_origins": []},
        ],
        "citation_aliases": {"https://example.test/contract.md": "contract.md#clause"},
        "ambiguous_aliases": ["ambiguous.md"],
    }
    assert grounded_citation_count(
        {"contract.md#clause", "https://example.test/contract.md",
         "missing.md#clause", "ambiguous.md", "invented.md"},
        adapted,
    ) == 2


def test_inference_error_is_operational_failure_not_fabricated_judge_or_free_usage():
    failed = inference_failure_record({
        "id": "failed", "run": 1, "model": "gpt-6-astra", "source_family": "family",
    }, {"error": "APIConnectionError", "response_id": None, "latency_ms": 100,
        "usage": None, "output_text": ""})
    good = {
        **failed, "id": "good", "inference_error": None, "score": 0.8, "pass": True,
        "capture_sha256": "verified", "flags": [],
        "dimensions": [{"id": "grounding", "score": 4, "reason": "Supported."}],
    }
    report = summary([failed, good], 2)
    assert report["mean_score"] == 0.4
    assert report["mean_quality_on_scored_responses"] == 0.8
    assert report["pass_rate"] == 0.5
    assert report["scored_responses"] == report["inference_failures"] == 1
    assert report["rubric_dimensions"]["grounding"]["mean_score"] == 0.8
    assert report["retrieval"]["audit_complete_rate"] == 0.5
    assert report["retrieval"]["responses_with_tool_call_rate"] is None
    assert report["cost_usd_per_1k_lines"] is None
    assert failed["quality_score"] is None and failed["dimensions"] == []
    with pytest.raises(ValueError, match="explicit recorded inference error"):
        inference_failure_record({}, {"error": None})


@pytest.mark.parametrize("deep_output", [False, True])
def test_batch_preserves_failed_response_and_continues_unissued_trials(
    tmp_path, monkeypatch, deep_output,
):
    import caliber.contract_policy_analyst_batch as batch

    output_argument = tmp_path
    if deep_output:
        output_argument = tmp_path / ("nested-" + "x" * 80) / ("nested-" + "y" * 80)
        tmp_path = (
            Path("\\\\?\\" + str(output_argument)) if os.name == "nt" else output_argument
        )
    row = {
        "id": "case", "task": "Task", "task_sha256": "a" * 64,
        "reference_sha256": "b" * 64, "source_family": "family", "scenario_family": "gap",
    }
    monkeypatch.setattr(batch, "load_study_split", lambda **kwargs: [row])
    response = {
        "error": "APIConnectionError", "response_id": None, "latency_ms": 100,
        "usage": None, "output_text": "",
    }
    write_record(tmp_path / "attempts" / f"{record_key('case', 1)}.started.json",
                 {"attempt_id": "original"})
    write_record(tmp_path / "attempts" / f"{record_key('case', 1)}.response.json", response)
    calls = []

    def hosted(*args, **kwargs):
        calls.append(kwargs["metadata"]["cpa_run"])
        return response

    class Captures:
        def __init__(self, *args):
            pass

        def get(self, *args):
            pytest.fail("Failed inference must not fabricate a capture.")

        def close(self):
            pass

    monkeypatch.setattr(batch, "hosted_call", hosted)
    monkeypatch.setattr(batch, "CaptureReader", Captures)
    monkeypatch.setattr(batch, "judge_call", lambda *args: pytest.fail("No failure judge."))
    monkeypatch.setattr(sys, "argv", [
        "batch", "--repo", str(Path(__file__).resolve().parents[3]), "--endpoint", "https://test",
        "--blob-account-url", "https://test", "--version", "6", "--model", "gpt-6-astra",
        "--instructions-sha256", "a" * 64, "--tools-sha256", "b" * 64,
        "--arm", "baseline", "--split", "optimizer-validation", "--out", str(output_argument),
        "--repeats", "2", "--concurrency", "1", "--allow-live",
    ])
    assert batch.main() == 0
    assert calls == ["2"]
    assert json.loads((tmp_path / "summary.json").read_text())["inference_failures"] == 2
    assert json.loads((tmp_path / "summary.json").read_text())["rubric_dimensions"] == {}
    assert batch.main() == 0
    assert calls == ["2"]


def _judge_client(monkeypatch, outcomes):
    import azure.identity
    import openai

    import caliber.contract_policy_analyst_batch as batch

    calls = []
    iterator = iter(outcomes)

    class Credential:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def get_token(self, *args):
            return SimpleNamespace(token="fake-test-token")

    class Client(Credential):
        @property
        def responses(self):
            return self

        def create(self, **kwargs):
            calls.append(kwargs)
            outcome = next(iterator)
            if isinstance(outcome, BaseException):
                raise outcome
            return outcome

    monkeypatch.setattr(azure.identity, "AzureCliCredential", Credential)
    monkeypatch.setattr(openai, "OpenAI", Client)
    monkeypatch.setattr(batch.time, "sleep", lambda seconds: None)
    return calls


def _connection_error(cause_type):
    openai = pytest.importorskip("openai")
    httpx = pytest.importorskip("httpx2")
    error = openai.APIConnectionError(request=httpx.Request("POST", "https://test"))
    error.__cause__ = cause_type("transport failure")
    return error


def test_judge_retries_unissued_connections_and_reuses_receipt(tmp_path, monkeypatch):
    import caliber.contract_policy_analyst_batch as batch
    httpx = pytest.importorskip("httpx2")

    response = SimpleNamespace(model_dump=lambda: {"usage": None}, output_text="{}")
    calls = _judge_client(monkeypatch, [_connection_error(httpx.ConnectError), response])
    result = batch.judge_call("https://test", "prompt", "task", "output", {}, [],
                             attempt_dir=tmp_path)
    assert len(calls) == 2 and calls[0] == calls[1]
    failed = json.loads(next(tmp_path.glob("*.failed.json")).read_text())
    assert failed["status"] == "not_sent_connect_error"
    assert len(list(tmp_path.glob("*.started.json"))) == 2
    assert batch.judge_call("https://test", "prompt", "task", "output", {}, [],
                            attempt_dir=tmp_path) == result
    assert len(calls) == 2
    with pytest.raises(ValueError, match="different inputs"):
        batch.judge_call("https://test", "prompt", "task", "changed", {}, [],
                         attempt_dir=tmp_path)
    write_record(tmp_path / "uncertain.started.json", {
        "attempt_id": "uncertain", "request_sha256": result["request_sha256"],
    })
    with pytest.raises(ValueError, match="Unreconciled"):
        batch.judge_call("https://test", "prompt", "task", "output", {}, [],
                         attempt_dir=tmp_path)


@pytest.mark.parametrize("cause_type", ["ReadTimeout", "WriteError", "ConnectError"])
def test_judge_transport_budget_and_uncertainty_fail_closed(tmp_path, monkeypatch, cause_type):
    import caliber.contract_policy_analyst_batch as batch
    httpx = pytest.importorskip("httpx2")
    openai = pytest.importorskip("openai")

    calls = _judge_client(monkeypatch, [
        _connection_error(getattr(httpx, cause_type)) for _ in range(3)
    ])
    with pytest.raises(openai.APIConnectionError):
        batch.judge_call("https://test", "prompt", "task", "output", {}, [],
                         attempt_dir=tmp_path)
    assert len(calls) == (3 if cause_type == "ConnectError" else 1)
    with pytest.raises(ValueError, match="budget exhausted|Unreconciled"):
        batch.judge_call("https://test", "prompt", "task", "output", {}, [],
                         attempt_dir=tmp_path)
    assert len(calls) == (3 if cause_type == "ConnectError" else 1)
