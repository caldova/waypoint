import copy
import hashlib
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from caliber.contract_policy_analyst_batch import (
    FROZEN_GRADER_SHA256,
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


GRADERS = Path(__file__).resolve().parents[1] / "graders" / "contract-policy-analyst"
V1_SHA256 = "267d5f6c7cebe3baaf8b243d97ea6bc4a8befbdb95b9ee85a3a07f8bc5bf6f62"
V2_SHA256 = "64e8ad9af6617bd79cca2e8d83b03f9394e590494a7c0f3a51f796da1e8f7d7d"


def test_live_runner_is_pinned_to_grader_v2():
    import caliber.contract_policy_analyst_batch as batch

    assert batch.FROZEN_GRADER_FILE == "contract_policy_analyst_grader_v2.py"
    assert batch.FROZEN_GRADER_SHA256 == V2_SHA256
    assert batch.FROZEN_GRADER_BASE_SHA256 == V1_SHA256
    for name, pinned in (
        ("contract_policy_analyst_grader_v2.py", V2_SHA256),
        ("contract_policy_analyst_grader.py", V1_SHA256),
    ):
        assert hashlib.sha256((GRADERS / name).read_bytes()).hexdigest() == pinned
    grader = batch.load_frozen_grader(GRADERS)
    assert grader.VERSION == "contract-policy-analyst-grader-v2"
    assert {"false_approval", "missed_approval"} <= grader.CAPS.keys()
    anchor = Path(__file__).resolve().parents[3] / batch.COMPARISON_ANCHOR
    assert hashlib.sha256(anchor.read_bytes()).hexdigest() == batch.COMPARISON_ANCHOR_SHA256
    assert json.loads(anchor.read_text(encoding="utf-8"))["grader_v2_sha256"] == V2_SHA256


def test_frozen_grader_refuses_drift(tmp_path):
    import caliber.contract_policy_analyst_batch as batch

    for name in ("contract_policy_analyst_grader_v2.py", "contract_policy_analyst_grader.py"):
        (tmp_path / name).write_bytes((GRADERS / name).read_bytes())
    (tmp_path / "contract_policy_analyst_grader_v2.py").write_bytes(
        (GRADERS / "contract_policy_analyst_grader_v2.py").read_bytes() + b"\n",
    )
    with pytest.raises(ValueError, match="Frozen grader source changed"):
        batch.load_frozen_grader(tmp_path)


def test_comparisons_never_mix_grader_revisions():
    import caliber.contract_policy_analyst_batch as batch

    v2 = {"grader_sha256": V2_SHA256}
    assert batch.require_single_grader([v2, v2]) == V2_SHA256
    for records in ([v2, {"grader_sha256": V1_SHA256}], [{"grader_sha256": V1_SHA256}], [{}]):
        with pytest.raises(ValueError, match="frozen grader"):
            batch.require_single_grader(records)
        with pytest.raises(ValueError, match="frozen grader"):
            summary(records, len(records))


def test_code_rft_reward_caps_match_frozen_quality_grader():
    import caliber.contract_policy_analyst_batch as batch

    grader = batch.load_frozen_grader(GRADERS)
    reward = batch.load_module(GRADERS / "contract_policy_analyst_rft_reward_v1.py")
    shared = reward.CAPS.keys() & grader.CAPS.keys()
    assert {"false_approval", "wrong_support", "directive", "unsupported_fact"} <= shared
    assert {flag: reward.CAPS[flag] for flag in shared} == {
        flag: grader.CAPS[flag] for flag in shared
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
        "grader_sha256": FROZEN_GRADER_SHA256,
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
    good["judge_cost"] = {"usd": 0.5}
    retried = summary([failed, good], 2, [{"billing_status": "unknown"}])
    assert retried["judge_cost_usd"] is None
    assert retried["judge_token_estimate_known_subtotal_usd"] == 0.5
    assert retried["judge_http_retries"] == 1
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
        _connection_error(getattr(httpx, cause_type)) for _ in range(5)
    ])
    exception = (
        batch.JudgeConnectionExhausted if cause_type == "ConnectError"
        else openai.APIConnectionError
    )
    with pytest.raises(exception):
        batch.judge_call("https://test", "prompt", "task", "output", {}, [],
                         attempt_dir=tmp_path)
    assert len(calls) == (5 if cause_type == "ConnectError" else 1)
    subsequent = batch.JudgeConnectionExhausted if cause_type == "ConnectError" else ValueError
    with pytest.raises(subsequent, match="exhausted|Unreconciled"):
        batch.judge_call("https://test", "prompt", "task", "output", {}, [],
                         attempt_dir=tmp_path)
    assert len(calls) == (5 if cause_type == "ConnectError" else 1)


def test_judge_http_error_retains_server_correlation_without_issued_retry(tmp_path, monkeypatch):
    import caliber.contract_policy_analyst_batch as batch
    httpx = pytest.importorskip("httpx2")
    openai = pytest.importorskip("openai")

    response = httpx.Response(503, headers={"x-request-id": "request503"},
                              request=httpx.Request("POST", "https://test"))
    error = openai.InternalServerError("Service unavailable", response=response,
                                      body={"dimensions": []})
    calls = _judge_client(monkeypatch, [error])
    with pytest.raises(openai.InternalServerError):
        batch.judge_call("https://test", "prompt", "task", "output", {}, [],
                         attempt_dir=tmp_path)
    receipt = json.loads(next(tmp_path.glob("*.failed.json")).read_text())
    assert receipt["http_status"] == 503 and receipt["request_id"] == "request503"
    assert receipt["status"] == "unreconciled"
    with pytest.raises(ValueError, match="Unreconciled"):
        batch.judge_call("https://test", "prompt", "task", "output", {}, [],
                         attempt_dir=tmp_path)
    assert len(calls) == 1


def _http_error(status, body=None, retry_after="15"):
    openai = pytest.importorskip("openai")
    httpx = pytest.importorskip("httpx2")
    response = httpx.Response(
        status, headers={"retry-after": retry_after, "x-request-id": "request"},
        request=httpx.Request("POST", "https://test"),
    )
    return openai.APIStatusError("HTTP error", response=response,
                                body=body if body is not None else {"error": "unavailable"})


@pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
def test_authorized_http_retry_is_once_identical_and_preserves_unknown_bill(
    tmp_path, monkeypatch, status,
):
    import caliber.contract_policy_analyst_batch as batch

    response = SimpleNamespace(model_dump=lambda: {"usage": None}, output_text="{}")
    calls = _judge_client(monkeypatch, [_http_error(status), response])
    delays = []
    monkeypatch.setattr(batch.time, "sleep", delays.append)
    directory = tmp_path / "case"
    budget = batch.JudgeHTTPRetryBudget(tmp_path / "budget")
    result = batch.judge_call("https://test", "prompt", "task", "output", {}, [],
                             attempt_dir=directory, http_retry_budget=budget)
    assert len(calls) == 2 and calls[0] == calls[1]
    assert delays == [15.0]
    assert result["http_retry"] is True
    receipt = json.loads(next(directory.glob("*.failed.json")).read_text())
    assert receipt["billing_status"] == "unknown"
    assert receipt["http_status"] == status and receipt["status"] == "retryable_http_error"
    assert len(budget.snapshot()) == 1
    assert batch.judge_call("https://test", "prompt", "task", "output", {}, [],
                            attempt_dir=directory, http_retry_budget=budget) == result
    assert len(calls) == 2


@pytest.mark.parametrize("last_error", ["http", "connect", "read"])
def test_failed_http_retry_stops_without_third_request(tmp_path, monkeypatch, last_error):
    import caliber.contract_policy_analyst_batch as batch
    httpx = pytest.importorskip("httpx2")
    openai = pytest.importorskip("openai")

    error = _http_error(503) if last_error == "http" else _connection_error(
        httpx.ConnectError if last_error == "connect" else httpx.ReadTimeout,
    )
    calls = _judge_client(monkeypatch, [_http_error(503), error])
    budget = batch.JudgeHTTPRetryBudget(tmp_path / "budget")
    with pytest.raises(openai.APIError):
        batch.judge_call("https://test", "prompt", "task", "output", {}, [],
                         attempt_dir=tmp_path / "case", http_retry_budget=budget)
    with pytest.raises(ValueError, match="retry failed"):
        batch.judge_call("https://test", "prompt", "task", "output", {}, [],
                         attempt_dir=tmp_path / "case", http_retry_budget=budget)
    assert len(calls) == 2


@pytest.mark.parametrize("status,body", [
    (400, {"error": "bad input"}), (401, {"error": "unauthorized"}),
    (503, {"dimensions": []}), (502, {"error": {"output_text": "judge result"}}),
])
def test_http_errors_with_judge_body_or_other_4xx_never_retry(
    tmp_path, monkeypatch, status, body,
):
    import caliber.contract_policy_analyst_batch as batch
    openai = pytest.importorskip("openai")

    calls = _judge_client(monkeypatch, [_http_error(status, body)])
    budget = batch.JudgeHTTPRetryBudget(tmp_path / "budget")
    with pytest.raises(openai.APIError):
        batch.judge_call("https://test", "prompt", "task", "output", {}, [],
                         attempt_dir=tmp_path / "case", http_retry_budget=budget)
    assert len(calls) == 1 and budget.snapshot() == []


def test_http_retry_reservations_survive_restart_and_cannot_exceed_ten(tmp_path):
    from caliber.contract_policy_analyst_batch import JudgeHTTPRetryBudget

    budget = JudgeHTTPRetryBudget(tmp_path)
    for index in range(10):
        budget.reserve(f"case{index}", "hash", 503)
    restarted = JudgeHTTPRetryBudget(tmp_path)
    with pytest.raises(ValueError, match="budget exhausted"):
        restarted.reserve("eleventh", "hash", 503)
    with pytest.raises(ValueError, match="already reserved"):
        restarted.reserve("case0", "hash", 503)
    assert len(restarted.snapshot()) == 10


@pytest.mark.parametrize("header,expected", [
    (None, 10), ("1", 10), ("20", 20), ("nonsense", 10), ("inf", 10),
])
def test_http_retry_backoff_honors_header_and_minimum(header, expected):
    from caliber.contract_policy_analyst_batch import judge_retry_delay

    assert judge_retry_delay(header) == expected


def test_http_retry_honors_date_header():
    from datetime import UTC, datetime, timedelta
    from email.utils import format_datetime

    from caliber.contract_policy_analyst_batch import judge_retry_delay

    header = format_datetime(datetime.now(UTC) + timedelta(seconds=60), usegmt=True)
    assert 58 <= judge_retry_delay(header) <= 60


@pytest.mark.parametrize("valid_recovery", [True, False])
def test_http_recovery_binds_original_failure_and_never_overwrites_it(
    tmp_path, monkeypatch, valid_recovery,
):
    import caliber.contract_policy_analyst_batch as batch
    openai = pytest.importorskip("openai")

    response = SimpleNamespace(model_dump=lambda: {"usage": None}, output_text="{}")
    calls = _judge_client(monkeypatch, [_http_error(503), response])
    directory = tmp_path / "case"
    with pytest.raises(openai.APIError):
        batch.judge_call("https://test", "prompt", "task", "output", {}, [],
                         attempt_dir=directory)
    failure_path = next(directory.glob("*.failed.json"))
    original = failure_path.read_bytes()
    receipt = json.loads(original)
    attempt_id = failure_path.name.removesuffix(".failed.json")
    batch.write_record(directory / f"{attempt_id}.retry-recovery.json", {
        "failure_sha256": hashlib.sha256(original).hexdigest() if valid_recovery else "wrong",
        "request_sha256": receipt["request_sha256"],
        "no_judge_result": True, "http_status": 503,
    })
    budget = batch.JudgeHTTPRetryBudget(tmp_path / "budget")
    if valid_recovery:
        result = batch.judge_call("https://test", "prompt", "task", "output", {}, [],
                                 attempt_dir=directory, http_retry_budget=budget)
        assert result["http_retry"] is True and len(calls) == 2
    else:
        with pytest.raises(ValueError, match="not bound"):
            batch.judge_call("https://test", "prompt", "task", "output", {}, [],
                             attempt_dir=directory, http_retry_budget=budget)
        assert len(calls) == 1
    assert failure_path.read_bytes() == original


def test_http_retry_cap_is_atomic_across_budget_instances(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    from caliber.contract_policy_analyst_batch import JudgeHTTPRetryBudget

    budgets = [JudgeHTTPRetryBudget(tmp_path), JudgeHTTPRetryBudget(tmp_path)]
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [
            pool.submit(budgets[index % 2].reserve, f"case{index}", "hash", 503)
            for index in range(20)
        ]
        successes = 0
        for future in futures:
            try:
                future.result()
                successes += 1
            except ValueError as error:
                assert "budget exhausted" in str(error)
    assert successes == 10 and len(budgets[0].snapshot()) == 10


def test_connection_backoff_and_resume_count_prior_unissued_attempts(tmp_path, monkeypatch):
    import caliber.contract_policy_analyst_batch as batch

    request_hash = hashlib.sha256(
        ("prompt\n" + batch.judge_input("task", "output", {}, [])).encode(),
    ).hexdigest()
    for index in range(3):
        batch.write_record(tmp_path / f"{index}.started.json", {
            "attempt_id": str(index), "request_sha256": request_hash,
        })
        batch.write_record(tmp_path / f"{index}.failed.json", {
            "status": "not_sent_connect_error", "request_sha256": request_hash,
        })
    httpx = pytest.importorskip("httpx2")
    response = SimpleNamespace(model_dump=lambda: {"usage": None}, output_text="{}")
    calls = _judge_client(monkeypatch, [_connection_error(httpx.ConnectError), response])
    delays = []
    monkeypatch.setattr(batch.time, "sleep", delays.append)
    monkeypatch.setattr(batch.random, "uniform", lambda start, end: 0.5)
    batch.judge_call("https://test", "prompt", "task", "output", {}, [], attempt_dir=tmp_path)
    assert len(calls) == 2 and delays == [40.5, 60.5]
    assert len(list(tmp_path.glob("*.started.json"))) == 5


@pytest.mark.parametrize("cases", [5, 6])
def test_exhausted_judge_connections_are_explicit_zeros_and_sixth_case_stops(
    tmp_path, monkeypatch, cases,
):
    import caliber.contract_policy_analyst_batch as batch

    rows = [{
        "id": f"case{index}", "task": "task", "task_sha256": "a" * 64,
        "reference_sha256": "b" * 64, "reference": {}, "source_family": "family",
        "scenario_family": "gap",
    } for index in range(cases)]
    monkeypatch.setattr(batch, "load_study_split", lambda **kwargs: rows)
    model_calls = []
    verified = []

    def hosted(*args, **kwargs):
        model_calls.append(kwargs["metadata"]["cpa_case_id"])
        return {
            "error": None, "response_id": "response", "output_text": "{}",
            "latency_ms": 100, "usage": {"input_tokens": 1000, "output_tokens": 100},
        }

    class Captures:
        def __init__(self, *args):
            pass

        def get(self, nonce):
            return {
                "record_sha256": "capture", "provenance": {"model": "gpt-6-astra"},
                "tool_calls": [{"duration_ms": 5, "tool_reported_ok": True}],
            }

        def close(self):
            pass

    def exhausted(*args, **kwargs):
        raise batch.JudgeConnectionExhausted("five unissued")

    adapter = SimpleNamespace(normalize_tool_messages=lambda *args, **kwargs: {
        "tool_messages": [], "issues": [], "mappings": [],
        "citation_aliases": {}, "ambiguous_aliases": [],
    })
    monkeypatch.setattr(batch, "load_module", lambda path: adapter)
    monkeypatch.setattr(batch, "load_frozen_grader", lambda path: adapter)
    monkeypatch.setattr(batch, "hosted_call", hosted)
    monkeypatch.setattr(batch, "CaptureReader", Captures)
    monkeypatch.setattr(batch, "verify_capture", lambda *args, **kwargs: verified.append(True))
    monkeypatch.setattr(batch, "judge_call", exhausted)
    monkeypatch.setattr(sys, "argv", [
        "batch", "--repo", str(Path(__file__).resolve().parents[3]), "--endpoint", "https://test",
        "--blob-account-url", "https://test", "--version", "6", "--model", "gpt-6-astra",
        "--instructions-sha256", "a" * 64, "--tools-sha256", "b" * 64,
        "--arm", "baseline", "--split", "optimizer-validation", "--out", str(tmp_path),
        "--repeats", "1", "--concurrency", "1", "--allow-live",
    ])
    if cases == 6:
        with pytest.raises(RuntimeError, match="More than five"):
            batch.main()
        assert not (tmp_path / "summary.json").exists()
        with pytest.raises(ValueError, match="More than five"):
            batch.main()
    else:
        assert batch.main() == 0
        report = json.loads((tmp_path / "summary.json").read_text())
        assert report["judge_connection_exhaustions"] == 5
        assert report["scored_responses"] == 0
        assert report["mean_score"] == 0.0 and report["mean_quality_on_scored_responses"] is None
        assert report["retrieval"]["audit_complete_rate"] == 1.0
    records = [
        json.loads(path.read_text()) for path in (tmp_path / "attempts").glob("*.graded.json")
    ]
    assert len(model_calls) == len(verified) == len(records) == cases
    assert all(row["score"] == 0.0 and row["quality_score"] is None for row in records)
    assert all(row["dimensions"] == [] and row["retrieval_calls"] for row in records)
    assert all(row["cost"]["usd"] > 0 and row["judge_cost"]["usd"] == 0 for row in records)
