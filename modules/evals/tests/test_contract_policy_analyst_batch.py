import copy
import hashlib

import pytest

from caliber.contract_policy_analyst_batch import (
    cited_refs,
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
