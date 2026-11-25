from __future__ import annotations

import ast
import builtins
import copy
import hashlib
import importlib.util
import json
import shutil
import uuid
from pathlib import Path

import pytest

from caliber.contract_policy_analyst_benchmark import (
    AGENT,
    SECOND_BEHAVIORS,
    SPLITS,
    STUDY_SPLITS,
    TOOL,
    _persist,
    audit_final_test_independence,
    audit_study_partitions,
    build_benchmark,
    build_expanded_study,
    build_final_test_v2,
    commercial_amount,
    derive_final_test_expectation,
    derive_study_expectation,
    foundry_reason_evaluator_body,
    leakage_audit,
    load_study_split,
    source_family,
    study_optimizer_rows,
)
from caliber.rft import _rft_reward_grader_source

ROOT = Path(__file__).resolve().parents[3]
DATA = ROOT / "modules" / "evals" / "datasets" / AGENT
GRADERS = ROOT / "modules" / "evals" / "graders" / AGENT
SPEC = importlib.util.spec_from_file_location(
    "contract_policy_analyst_grader", GRADERS / "contract_policy_analyst_grader.py",
)
assert SPEC is not None and SPEC.loader is not None
grader = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(grader)
TRANSCRIPT_SPEC = importlib.util.spec_from_file_location(
    "contract_policy_analyst_transcript", GRADERS / "contract_policy_analyst_transcript.py",
)
assert TRANSCRIPT_SPEC is not None and TRANSCRIPT_SPEC.loader is not None
transcript = importlib.util.module_from_spec(TRANSCRIPT_SPEC)
TRANSCRIPT_SPEC.loader.exec_module(transcript)
REWARD_PATH = GRADERS / "contract_policy_analyst_rft_reward_v1.py"
REWARD_SPEC = importlib.util.spec_from_file_location("contract_policy_analyst_reward", REWARD_PATH)
assert REWARD_SPEC is not None and REWARD_SPEC.loader is not None
reward = importlib.util.module_from_spec(REWARD_SPEC)
REWARD_SPEC.loader.exec_module(reward)


def _rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


@pytest.fixture
def owned_output():
    # Scratch stays in the explicitly owned worktree, never the system temp directory.
    path = DATA / (".test-" + uuid.uuid4().hex)
    try:
        yield path
    finally:
        if path.exists():
            shutil.rmtree(path)


@pytest.fixture
def reference():
    return copy.deepcopy(_rows(DATA / "references" / "historical-regression.jsonl")[0])


def _sample(reference: dict) -> str:
    return json.dumps(reference["expected_output_json"], sort_keys=True)


def _item(reference: dict) -> dict:
    return {
        "reference": reference,
        "rubric_sha256": hashlib.sha256((GRADERS / "quality-rubric.json").read_bytes()).hexdigest(),
        "tool_messages": [{
            "name": TOOL, "status": "succeeded",
            "content": {"sources": [{
                "source_ref": s["source_ref"], "text": s["text"],
            } for s in reference["sources"]]},
        }],
    }


def _judge_fixture(sample: str, item: dict, flags: list[str] | None = None) -> dict:
    """Synthetic judge fixture, not a claim that gpt-6-astra was invoked."""
    item = copy.deepcopy(item)
    item["judge_result"] = {
        "judge_model": "gpt-6-astra",
        "output_sha256": grader.output_sha256(sample),
        "retrieval_sha256": grader.retrieval_sha256(item["tool_messages"]),
        "rubric_sha256": item["rubric_sha256"],
        "critical_flags": flags or [],
        "dimensions": [{
            "id": key, "score": 5,
            "reason": "Offline fixture: the named retrieved section supports this candidate; "
            "the billed item's operational authorization remains unverified.",
        } for key in grader.DIMENSION_WEIGHTS],
    }
    return item


def test_repeatable_build_and_exact_sizes(owned_output):
    report = build_benchmark(repo=ROOT, out_dir=owned_output)
    before = {p.relative_to(owned_output): p.read_bytes() for p in owned_output.rglob("*")
              if p.is_file()}
    assert build_benchmark(repo=ROOT, out_dir=owned_output) == report
    assert before == {p.relative_to(owned_output): p.read_bytes()
                      for p in owned_output.rglob("*") if p.is_file()}
    assert report["sizes"] == {
        "train": 10, "validation": 2, "historical-regression": 24,
        "new-grounded-candidates": 5, "sealed-heldout": 0,
    }
    assert not report["live_eval_ready"]
    assert not report["sealed_ready"]
    assert report["audit"]["task_duplicates"]["historical-regression"] == {
        "unique_invoice_line_tasks": 3, "repeated_line_rows": 21,
    }


def test_drift_refuses_all_writes(owned_output):
    build_benchmark(repo=ROOT, out_dir=owned_output)
    target = owned_output / "validation-report.json"
    target.write_text("human edit", encoding="utf-8")
    first = owned_output / "train.jsonl"
    old = first.read_bytes()
    first.unlink()
    with pytest.raises(ValueError, match="refusing to overwrite"):
        build_benchmark(repo=ROOT, out_dir=owned_output)
    assert not first.exists()  # Whole output preflight, not partial overwriting.
    assert target.read_text(encoding="utf-8") == "human edit"
    assert old


def test_output_scope_is_enforced():
    with pytest.raises(ValueError, match="output must be inside"):
        build_benchmark(repo=ROOT, out_dir=ROOT / "modules" / "evals" / "datasets")


def test_no_embedded_evidence_or_outcome_hints_and_originals_preserved():
    original = {
        r["id"]: r for r in _rows(
            ROOT / "modules" / "evals" / "datasets" / "contract-policy-expert"
            / "contract-policy-expert-eval.jsonl"
        )
    }
    historical = _rows(DATA / "references" / "historical-regression.jsonl")
    assert len(historical) == 24
    for ref in historical:
        archive = ref["historical_reference"]
        source = original[archive["id"]]
        for key in ("messages", "ground_truth", "expected_output_json", "metadata"):
            assert archive[key] == source[key]
        assert all(r["supports"] == "review" for r in ref["expected_output_json"]["evidence"])
    banned = {
        "retrieved_context", "scenario_hint", "expected_decision_state",
        "issue_category", "scenario_id", "recommended_action", "ground_truth",
        "risk_examples", "reconciliation_focus", "evidence_refs", "source_ref", "text",
    }
    for split in SPLITS:
        rows = _rows(DATA / f"{split}.jsonl")
        refs = {r["id"]: r for r in _rows(DATA / "references" / f"{split}.jsonl")}
        for row in rows:
            payload = json.loads(row["messages"][-1]["content"])

            def check(value):
                if isinstance(value, dict):
                    assert not banned & value.keys()
                    for child in value.values():
                        check(child)
                elif isinstance(value, list):
                    for child in value:
                        check(child)

            check(payload)
            assert "Retrieve" in payload["request"]
            assert row["expected_tools"] == [TOOL]
            assert row["metadata"]["synthetic"]
            assert row["metadata"]["review_status"] == "pending_human_review"
            assert not row["metadata"]["kb_ingestion_verified"]
            assert "expected_output_json" not in row
            for source in refs[row["reference_id"]]["sources"]:
                assert source["text"] not in row["messages"][-1]["content"]
                path = ROOT / "modules" / "corpus" / source["document"]
                assert path.is_file()
                assert hashlib.sha256(path.read_bytes()).hexdigest() == source["document_sha256"]
                assert source["text"] in path.read_text(encoding="utf-8")


def test_alias_and_family_leakage_fail_closed():
    assert source_family("data/contracts/source-markdown/cmo-001-example.md#3-x") == (
        source_family("data/contracts/source-markdown/sup-001-example.md#4-y")
    )
    report = json.loads((DATA / "leakage-audit.json").read_text(encoding="utf-8"))
    assert report["pristine_sealed_cases"] == 0
    assert report["historical_asset_family_overlap"]["new-grounded-candidates"]
    assert report["cross_split_family_overlap"]["train_vs_validation"]
    splits = {s: [] for s in SPLITS}
    example = {"metadata": {"source_families": ["supplier-001-example.md"]}}
    splits["sealed-heldout"] = [example]
    with pytest.raises(ValueError, match="sealed heldout source-family contamination"):
        leakage_audit(splits, {"supplier-001-example.md": {"historical-train"}})
    splits["train"] = [example]
    with pytest.raises(ValueError, match="sealed heldout source-family contamination"):
        leakage_audit(splits, {})


def test_canonical_candidates_pass_only_with_bound_judge_fixture():
    for split in SPLITS:
        for ref in _rows(DATA / "references" / f"{split}.jsonl"):
            sample = _sample(ref)
            item = _item(ref)
            raw = grader.evaluate(sample, item)
            assert raw["code_score"] == 1, raw
            assert raw["score"] == 0.49
            assert not raw["pass"]
            result = grader.evaluate(sample, _judge_fixture(sample, item))
            assert result["score"] == 1, result
            assert result["pass"]
            assert len(result["judge_reasons"]) == 6


@pytest.mark.parametrize("mutation,expected_flag", [
    ("wrong_invoice", "wrong_identity"),
    ("wrong_correlation", "wrong_identity"),
    ("wrong_agent", "wrong_identity"),
    ("wrong_section", "wrong_citation"),
    ("wrong_supplier", "wrong_citation"),
    ("wrong_support", "wrong_support"),
    ("classification_role", "invalid_json_or_shape"),
    ("duplicate", "duplicate_evidence"),
    ("missing_gap", "missed_gap"),
    ("directive", "directive"),
    ("passive_directive", "directive"),
    ("disclaimer_then_action", "claimed_action"),
    ("writeback", "claimed_action"),
])
def test_critical_caps_even_with_perfect_judge(reference, mutation, expected_flag):
    output = copy.deepcopy(reference["expected_output_json"])
    if mutation == "wrong_invoice":
        output["invoice_id"] = "INV-WRONG"
    elif mutation == "wrong_correlation":
        output["correlation"]["waypoint_run_id"] = "fabricated-run"
    elif mutation == "wrong_agent":
        output["agent"] = "contract-policy-expert"
    elif mutation == "wrong_section":
        output["evidence"][0]["source_ref"] += "-invented"
    elif mutation == "wrong_supplier":
        output["evidence"][0]["source_ref"] = output["evidence"][0]["source_ref"].replace(
            "sup-013", "sup-014",
        )
    elif mutation == "wrong_support":
        output["evidence"][0]["supports"] = "approve"
    elif mutation == "classification_role":
        output["evidence"][0]["classification"] = "contract_term"
    elif mutation == "duplicate":
        output["evidence"].append(copy.deepcopy(output["evidence"][0]))
    elif mutation == "missing_gap":
        output["unsupported"] = []
    elif mutation == "directive":
        output["summary"] += " Please pay the invoice."
    elif mutation == "passive_directive":
        output["summary"] += " The payment should be approved."
    elif mutation == "disclaimer_then_action":
        output["summary"] += " Payment is not approved, but I approved the invoice."
    elif mutation == "writeback":
        output["summary"] += " We updated Waypoint."
    sample = json.dumps(output, sort_keys=True)
    result = grader.evaluate(sample, _judge_fixture(sample, _item(reference)))
    assert expected_flag in result["flags"], result
    assert result["score"] <= 0.49
    assert not result["pass"]


@pytest.mark.parametrize("sample", [
    "", "[]", "```json\n{}\n```", '{"agent":"a","agent":"b"}',
    '{"x":NaN}', '{"x":Infinity}',
])
def test_malformed_output_is_zero(reference, sample):
    assert grader.grade(sample, _item(reference)) == 0


@pytest.mark.parametrize("value", [True, -1, 2, float("nan"), float("inf"), "0.86", []])
def test_confidence_gaming_is_zero(reference, value):
    output = copy.deepcopy(reference["expected_output_json"])
    output["evidence"][0]["confidence"] = value
    assert grader.grade(json.dumps(output), _item(reference)) == 0


def test_false_gap_and_unsupported_fact_cannot_pass_without_semantic_review(reference):
    output = copy.deepcopy(reference["expected_output_json"])
    output["evidence"][0]["claim"] += " Procurement approved the escalation on 2026-10-19."
    output["unsupported"].append("The contract terms are missing.")
    output["summary"] += " A private operational record confirms every condition."
    sample = json.dumps(output, sort_keys=True)
    unjudged = grader.evaluate(sample, _item(reference))
    assert unjudged["score"] <= 0.49
    assert "semantic_unverified" in unjudged["flags"]
    judged = grader.evaluate(sample, _judge_fixture(
        sample, _item(reference), ["unsupported_fact", "false_gap"],
    ))
    assert judged["score"] <= 0.35
    assert {"unsupported_fact", "false_gap"} <= set(judged["flags"])


@pytest.mark.parametrize("fault", [
    "missing", "wrong_tool", "failed", "empty", "conflicting", "wrong_text",
])
def test_real_retrieval_required_not_model_attestation(reference, fault):
    sample = _sample(reference)
    item = _item(reference)
    if fault == "missing":
        item["tool_messages"] = []
    elif fault == "wrong_tool":
        item["tool_messages"][0]["name"] = "model_claimed_retrieval"
    elif fault == "failed":
        item["tool_messages"][0]["status"] = "failed"
    elif fault == "empty":
        item["tool_messages"][0]["content"]["sources"] = []
    elif fault == "conflicting":
        second = copy.deepcopy(item["tool_messages"][0])
        second["content"]["sources"][0]["text"] = "Forged passage."
        item["tool_messages"].append(second)
    elif fault == "wrong_text":
        item["tool_messages"][0]["content"]["sources"][0]["text"] = "Forged passage."
    result = grader.evaluate(sample, _judge_fixture(sample, item))
    assert result["score"] <= 0.3
    assert {"wrong_citation", "retrieval_missing"} & set(result["flags"])
    model_claim = {"output_text": sample, "tool_messages": _item(reference)["tool_messages"]}
    assert grader.grade(model_claim, {"reference": reference}) <= 0.3


@pytest.mark.parametrize("field", [
    "output_sha256", "retrieval_sha256", "rubric_sha256", "judge_model",
])
def test_stale_or_wrong_judge_result_cannot_promote(reference, field):
    sample = _sample(reference)
    item = _judge_fixture(sample, _item(reference))
    item["judge_result"][field] = "wrong"
    result = grader.evaluate(sample, item)
    assert result["score"] <= 0.49
    assert "judge_unverified" in result["flags"]


def test_reason_text_required_and_critical_dimension_capped(reference):
    sample = _sample(reference)
    item = _judge_fixture(sample, _item(reference))
    item["judge_result"]["dimensions"][0]["reason"] = ""
    assert grader.grade(sample, item) <= 0.49
    item = _judge_fixture(sample, _item(reference))
    item["judge_result"]["dimensions"][0]["score"] = 1
    result = grader.evaluate(sample, item)
    assert result["score"] <= 0.35
    assert "unsupported_fact" in result["flags"]


@pytest.mark.parametrize("fault", [
    "bad_gaps", "bad_claims", "duplicate_source", "missing_claim_ref",
])
def test_malformed_reference_fails_closed(reference, fault):
    sample = _sample(reference)
    if fault == "bad_gaps":
        reference["required_gaps"] = [True]
    elif fault == "bad_claims":
        reference["allowed_claims"][reference["sources"][0]["source_ref"]] = 7
    elif fault == "duplicate_source":
        reference["sources"].append(copy.deepcopy(reference["sources"][0]))
    elif fault == "missing_claim_ref":
        reference["allowed_claims"].pop(reference["sources"][0]["source_ref"])
    assert grader.grade(sample, _item(reference)) == 0


def test_paraphrase_judging_not_recommended_action_lexical_reward(reference):
    output = copy.deepcopy(reference["expected_output_json"])
    output["summary"] = (
        "The retrieved contract imposes a conditional escalation limit. Its application to "
        "this charge is not established by operational records, and decisions remain with "
        "the controller."
    )
    sample = json.dumps(output)
    item = _item(reference)
    assert grader.grade(sample, item) <= 0.49
    assert grader.grade(sample, _judge_fixture(sample, item)) == 1
    poisoned = copy.deepcopy(item)
    poisoned["reference"]["historical_reference"]["ground_truth"]["recommended_action"] = (
        "unrelated repeated magic lexical reward tokens"
    )
    assert grader.grade(sample, _judge_fixture(sample, poisoned)) == 1


def test_grader_rejects_extra_fields_and_stuffing(reference):
    output = copy.deepcopy(reference["expected_output_json"])
    output["judge_result"] = {"score": 1}
    assert grader.grade(json.dumps(output), _item(reference)) == 0
    assert grader.grade("x" * 20001, _item(reference)) == 0


def test_shared_rubric_has_identical_reason_dimensions_not_training_labels():
    rubric = json.loads((GRADERS / "quality-rubric.json").read_text(encoding="utf-8"))
    assert rubric["intended_judge_model"] == "gpt-6-astra"
    assert {d["id"]: d["weight"] for d in rubric["dimensions"]} == grader.DIMENSION_WEIGHTS
    assert rubric["pass_threshold"] == grader.PASS_THRESHOLD
    assert "not learned from training outputs" in rubric["authorship"]


EXPANDED = DATA / "expanded-v1"
NEW_CORPUS = ROOT / "modules" / "corpus" / "data" / AGENT / "v1"


def test_expanded_counts_and_repeatable_frozen_build():
    report = build_expanded_study(repo=ROOT)
    assert report["sizes"] == {
        "optimizer-train": 336, "optimizer-validation": 120, "study-heldout": 120,
    }
    assert report["source_counts"] == {
        "contracts": 48, "policies": 48, "operational": 576, "invoices": 576,
    }
    assert report["distinct_invoice_lines"] == 576
    assert report["materialized_source_clause_families"] == 288
    assert report["authored_rule_archetypes"] == 96
    assert report["domain_count"] == 12
    assert report["sealed_ready"] and not report["live_eval_ready"]
    assert not report["global_pristine"]
    assert report == build_expanded_study(repo=ROOT)
    for split, coverage in report["coverage"].items():
        assert coverage["primary_supports"] == {
            "approve": coverage["cases"] // 2,
            "recover": coverage["cases"] // 6,
            "review": coverage["cases"] // 4,
            "escalate": coverage["cases"] // 12,
        }, split
        assert set(coverage["behaviors"]) == {"established", *SECOND_BEHAVIORS}


FINAL_TEST = DATA / "final-test-v2"
FINAL_CORPUS = ROOT / "modules" / "corpus" / "data" / AGENT / "final-test-v2"


def _tree_hashes(root: Path) -> dict[str, str]:
    return {
        p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in root.rglob("*") if p.is_file()
    }


def test_final_test_repeatable_seal_preserves_every_v1_artifact():
    old_roots = [EXPANDED, FINAL_CORPUS.parent / "v1"]
    before = [_tree_hashes(root) for root in old_roots]
    report = build_final_test_v2(repo=ROOT)
    assert report == build_final_test_v2(repo=ROOT)
    assert before == [_tree_hashes(root) for root in old_roots]
    assert report["sizes"] == {"final-test-v2": 120}
    assert report["source_families"] == 10
    assert report["source_documents"] == 260
    assert report["status"] == "sealed-uningested"
    assert report["coverage"]["primary_supports"] == {
        "approve": 30, "recover": 40, "review": 40, "escalate": 10,
    }
    assert len(report["coverage"]["archetypes"]) == 12
    assert set(report["coverage"]["archetypes"].values()) == {10}
    assert not report["live_eval_ready"] and not report["global_pristine"]
    seal = json.loads((FINAL_TEST / "seal-manifest.json").read_text(encoding="utf-8"))
    assert seal["splits"]["final-test-v2"] == {
        "rows": 120, "source_families": 10, "status": "sealed-uningested",
    }
    assert seal["prior_study_heldout_status"] == "exposed-source-regression"
    assert not seal["ingestion_authorized"]


def _final_independence_inputs() -> dict:
    return {
        "references": _rows(FINAL_TEST / "references" / "final-test-v2.jsonl"),
        "prior_references": [
            r for split in STUDY_SPLITS
            for r in _rows(EXPANDED / "references" / f"{split}.jsonl")
        ],
        "source_rows": json.loads(
            (FINAL_CORPUS / "source-manifest.json").read_text(encoding="utf-8")
        )["source_documents"],
        "prior_source_rows": json.loads(
            (FINAL_CORPUS.parent / "v1" / "source-manifest.json").read_text(encoding="utf-8")
        )["source_documents"],
    }


@pytest.mark.parametrize("fault", [
    "identity", "source_bytes", "renamed_numerical_facts", "reused_rate", "unsealed", "ingested",
])
def test_final_test_rejects_overlap_and_unsealed_sources(fault):
    inputs = _final_independence_inputs()
    assert not any(audit_final_test_independence(**inputs)["overlap_with_CPA1"].values())
    prior = inputs["prior_references"][0]["ground_truth"]
    current = inputs["references"][0]["ground_truth"]
    if fault == "identity":
        current["invoice_facts"]["service_id"] = prior["invoice_facts"]["service_id"]
    elif fault == "source_bytes":
        inputs["source_rows"][0]["sha256"] = inputs["prior_source_rows"][0]["sha256"]
    elif fault == "renamed_numerical_facts":
        for field in ("authored_rule", "observed_facts", "invoice_facts"):
            for key, value in prior[field].items():
                if (
                    isinstance(value, (int, float)) and not isinstance(value, bool)
                    or isinstance(value, str) and value.replace(".", "").isdigit()
                ):
                    current[field][key] = value
        current["authored_rule"]["parameters"] = copy.deepcopy(
            prior["authored_rule"]["parameters"],
        )
        # Namespace/identities remain CPA2; numeric content alone must reject renamed data.
        assert current["invoice_facts"]["supplier_id"].startswith("CPA2")
    elif fault == "reused_rate":
        current["authored_rule"]["parameters"]["rate"] = (
            str(prior["authored_rule"]["parameters"]["rate"]) + ".00"
        )
    elif fault == "unsealed":
        inputs["source_rows"][0]["status"] = "unsealed"
    elif fault == "ingested":
        inputs["source_rows"][0]["kb_ingestion_verified"] = True
    with pytest.raises(ValueError, match="overlap|unsealed"):
        audit_final_test_independence(**inputs)


def test_final_test_source_provenance_oracle_and_distinct_identity_traps():
    inputs = _final_independence_inputs()
    cases = {c["id"]: c for c in _rows(FINAL_CORPUS / "cases-index.jsonl")}
    for reference in inputs["references"]:
        truth = reference["ground_truth"]
        authored = truth["authored_rule"]
        derived = derive_final_test_expectation(
            rule=[authored["id"], authored["topic"], authored["calculation"],
                  authored["prerequisites"]],
            parameters=authored["parameters"], facts=truth["observed_facts"],
            invoice=truth["invoice_facts"],
        )
        assert derived == truth["derived_expectation"]
        assert derived["supports"] == truth["primary_supports"]
        assert reference["review_status"] == "pending_human_review"
        assert reference["synthetic"]
        for source in reference["sources"]:
            text = (FINAL_CORPUS / source["local_path"]).read_text(encoding="utf-8")
            assert source["text"] in text
            assert "January 2027" in text
            assert "not a human-reviewed contract or policy" in text
            assert source["source_ref"].startswith("knowledge/contracts/policy-analyst-v2/")
            assert source["section_sha256"] == hashlib.sha256(source["text"].encode()).hexdigest()
        if cases[reference["id"]]["archetype"] == "wrong-supplier-record":
            facts, invoice = truth["observed_facts"], truth["invoice_facts"]
            assert facts["service_id"] == invoice["service_id"]
            assert facts["invoice_line_id"] == invoice["line_id"]
            assert facts["supplier_id"] != invoice["supplier_id"]
            fixed = {**facts, "supplier_id": invoice["supplier_id"]}
            assert derive_final_test_expectation(
                rule=[authored["id"], authored["topic"], authored["calculation"],
                      authored["prerequisites"]],
                parameters=authored["parameters"], facts=fixed, invoice=invoice,
            )["supports"] == "approve"
    reviews = _rows(FINAL_CORPUS / "review-list.jsonl")
    assert len(reviews) == 120
    assert {r["id"] for r in reviews} == set(cases)
    assert all(c["verification_status"] == "not_run_offline_definition"
               for c in _rows(FINAL_CORPUS / "retrieval-canaries.jsonl"))


def test_final_test_loader_is_reference_separated_and_optimizer_forbidden():
    rows = load_study_split(repo=ROOT, split="final-test-v2")
    assert len(rows) == 120
    assert len({r["source_family"] for r in rows}) == 10
    for row in rows:
        payload = json.loads(row["messages"][-1]["content"])
        assert set(payload) == {"request", "supplier", "invoice", "line"}
        assert "Retrieve fictional invoice" in payload["request"]
        assert not any(key in row["task"] for key in (
            "primary_supports", "expected_output_json", "observed_facts", "USD",
            "conditions", "pending_human_review", "archetype",
        ))
        assert json.loads(row["ground_truth"]) == row["reference"]
        assert row["metadata"]["kb_ingestion_verified"] is False
    with pytest.raises(ValueError, match="heldout cases must not enter optimizer"):
        study_optimizer_rows(repo=ROOT, split="final-test-v2")


@pytest.fixture
def final_test_copy(owned_output):
    repo = Path("\\\\?\\" + str(owned_output)) if owned_output.drive else owned_output
    corpus = repo / "modules" / "corpus" / "data" / AGENT / "final-test-v2"
    dataset = repo / "modules" / "evals" / "datasets" / AGENT / "final-test-v2"
    try:
        shutil.copytree(FINAL_CORPUS, corpus)
        shutil.copytree(FINAL_TEST, dataset)
        yield repo, corpus, dataset
    finally:
        if repo.exists():
            shutil.rmtree(repo)


@pytest.mark.parametrize("fault", ["source", "prompt", "extra_source", "unsealed_manifest"])
def test_final_test_loader_rejects_drift_and_unsealed_inventory(final_test_copy, fault):
    repo, corpus, dataset = final_test_copy
    if fault == "source":
        target = next((corpus / "contracts" / "source-markdown").glob("*.md"))
        target.write_text(target.read_text(encoding="utf-8") + "Changed clause.", encoding="utf-8")
    elif fault == "prompt":
        target = dataset / "final-test-v2.jsonl"
        target.write_text(target.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    elif fault == "extra_source":
        (corpus / "contracts" / "source-markdown" / "unsealed.md").write_text(
            "Unsealed fictional source", encoding="utf-8",
        )
    else:
        target = dataset / "seal-manifest.json"
        seal = json.loads(target.read_text(encoding="utf-8"))
        seal["status"] = "unsealed"
        target.write_text(json.dumps(seal), encoding="utf-8")
    with pytest.raises(ValueError, match="drift|unsealed"):
        load_study_split(repo=repo, split="final-test-v2")


def test_new_sources_are_real_remote_prefixed_and_no_labels_uploaded():
    manifest = json.loads((NEW_CORPUS / "source-manifest.json").read_text(encoding="utf-8"))
    assert len(manifest["source_documents"]) == 1248
    assert len({d["blob_name"] for d in manifest["source_documents"]}) == 1248
    assert manifest["blob_prefix"] == "contracts/policy-analyst-v1"
    for document in manifest["source_documents"]:
        path = NEW_CORPUS / document["path"]
        text = path.read_text(encoding="utf-8")
        assert hashlib.sha256(path.read_bytes()).hexdigest() == document["sha256"]
        assert "pending_human_review" in text
        assert "Fictional study source" in text
        assert "expected_output_json" not in text
        assert "recommended_action" not in text
        assert "primary_supports" not in text
    for split in STUDY_SPLITS:
        for reference in _rows(EXPANDED / "references" / f"{split}.jsonl"):
            for source in reference["sources"]:
                text = (NEW_CORPUS / source["local_path"]).read_text(encoding="utf-8")
                assert source["text"] in text
                assert source["source_ref"].startswith("knowledge/contracts/policy-analyst-v1/")
                assert source["source_ref"] in text
                assert source["section_sha256"] == hashlib.sha256(
                    source["text"].encode()
                ).hexdigest()
    assert len(_rows(NEW_CORPUS / "review-list.jsonl")) == 576
    canaries = _rows(NEW_CORPUS / "retrieval-canaries.jsonl")
    assert len(canaries) == 48
    for canary in canaries:
        text = (NEW_CORPUS / "contracts" / "source-markdown"
                / canary["expected_documents"][0]).read_text(encoding="utf-8")
        assert canary["distinctive_source_anchor"] in text
        assert canary["not_optimizer_input"]


def test_expanded_family_seal_no_cross_split_leakage():
    rows = {split: _rows(EXPANDED / f"{split}.jsonl") for split in STUDY_SPLITS}
    audit = audit_study_partitions(rows)
    assert audit["families_per_split"] == {
        "optimizer-train": 28, "optimizer-validation": 10, "study-heldout": 10,
    }
    assert audit["scenario_families_per_split"] == {
        "optimizer-train": 168, "optimizer-validation": 60, "study-heldout": 60,
    }
    assert all(not overlap for pair in audit["cross_split_overlap"].values()
               for overlap in pair.values())
    contaminated = copy.deepcopy(rows)
    contaminated["study-heldout"].append(copy.deepcopy(rows["optimizer-train"][0]))
    with pytest.raises(ValueError, match="study split leakage"):
        audit_study_partitions(contaminated)
    seal = json.loads((EXPANDED / "seal-manifest.json").read_text(encoding="utf-8"))
    assert seal["heldout_prompt_sha256"] == hashlib.sha256(
        (EXPANDED / "study-heldout.jsonl").read_bytes()
    ).hexdigest()
    assert seal["heldout_reference_sha256"] == hashlib.sha256(
        (EXPANDED / "references" / "study-heldout.jsonl").read_bytes()
    ).hexdigest()
    assert not seal["global_pristine"]
    assert (DATA / "sealed-heldout.jsonl").read_bytes() == b""


def test_expanded_prompts_retrieve_without_inline_answers_or_record_facts():
    for split in STUDY_SPLITS:
        for row in _rows(EXPANDED / f"{split}.jsonl"):
            payload = json.loads(row["messages"][-1]["content"])
            assert set(payload) == {"request", "supplier", "invoice", "line"}
            assert set(payload["line"]) == {"line_id", "service_id", "description"}
            assert "Retrieve" in payload["request"]
            assert "amount" not in payload["invoice"]
            assert "conditions" not in payload
            assert "expected" not in payload
            assert row["expected_tools"] == [TOOL]
            assert row["metadata"]["review_status"] == "pending_human_review"
            assert not row["metadata"]["global_pristine"]


def test_every_new_reference_is_derived_from_actual_invoice_and_record_source():
    archetypes = set()
    fact_fingerprints = set()
    for split in STUDY_SPLITS:
        for reference in _rows(EXPANDED / "references" / f"{split}.jsonl"):
            truth = reference["ground_truth"]
            authored = truth["authored_rule"]
            rule = [
                authored["id"], authored["topic"], authored["calculation"],
                authored["prerequisites"],
            ]
            derived = derive_study_expectation(
                rule=rule, parameters=authored["parameters"],
                facts=truth["observed_facts"], invoice=truth["invoice_facts"],
            )
            assert derived == truth["derived_expectation"]
            assert derived["supports"] == truth["primary_supports"]
            archetypes.add(authored["id"])
            fingerprint = json.dumps({
                "parameters": authored["parameters"],
                "observed": truth["observed_facts"],
                "invoice": truth["invoice_facts"],
            }, sort_keys=True)
            assert fingerprint not in fact_fingerprints
            fact_fingerprints.add(fingerprint)
            for source_kind, fact_key in (
                ("operational", "observed_facts"), ("invoices", "invoice_facts"),
            ):
                source = next(
                    s for s in reference["sources"] if s["local_path"].startswith(source_kind)
                )
                document = (NEW_CORPUS / source["local_path"]).read_text(encoding="utf-8")
                record_json = document.split("```json\n", 1)[1].split("\n```", 1)[0]
                assert json.loads(record_json) == truth[fact_key]
    assert len(archetypes) == 96
    assert len(fact_fingerprints) == 576


def test_expanded_reference_candidates_code_parity_with_explicit_fixture_judge():
    for split in STUDY_SPLITS:
        for reference in _rows(EXPANDED / "references" / f"{split}.jsonl"):
            sample = _sample(reference)
            item = _item(reference)
            result = grader.evaluate(sample, _judge_fixture(sample, item))
            assert result["score"] == 1, (reference["id"], result)
            assert grader.grade(sample, item) == 0.49


def test_expanded_mutation_changes_oracle_not_copied_behavior_label():
    reference = next(
        ref for ref in _rows(EXPANDED / "references" / "study-heldout.jsonl")
        if ref["ground_truth"]["primary_supports"] == "approve"
    )
    truth = reference["ground_truth"]
    authored = truth["authored_rule"]
    rule = [authored["id"], authored["topic"], authored["calculation"],
            authored["prerequisites"]]
    invoice = copy.deepcopy(truth["invoice_facts"])
    invoice["amount"] = str(float(invoice["amount"]) + 1)
    derived = derive_study_expectation(
        rule=rule, parameters=authored["parameters"],
        facts=truth["observed_facts"], invoice=invoice,
    )
    assert derived["supports"] == "recover"
    facts = copy.deepcopy(truth["observed_facts"])
    facts["service_id"] += "-OTHER"
    assert derive_study_expectation(
        rule=rule, parameters=authored["parameters"], facts=facts,
        invoice=truth["invoice_facts"],
    )["supports"] == "review"


def test_numeric_basis_traps_all_units_vs_incremental_and_credit_order():
    facts = {
        "quantity": 120, "accepted_quantity": 115, "rejected_quantity": 5,
        "actual_cost": 1200, "prior_credit": 100,
    }
    parameters = {
        "rate": 10, "threshold": 100, "discount_percent": 10,
        "tier_basis": "all_units", "cap": 1000,
    }
    assert commercial_amount("tier", parameters, facts) == 1080
    parameters["tier_basis"] = "incremental_units"
    assert commercial_amount("tier", parameters, facts) == 1180
    assert commercial_amount("lesser", parameters, facts) == 1100
    assert commercial_amount("capped_cost", parameters, facts) == 900


def test_expanded_cross_root_write_preflight_is_fail_closed(owned_output):
    first = owned_output / "one"
    second = owned_output / "two"
    _persist([(first, {"a.json": "{}"}), (second, {"b.json": "{}"})])
    (second / "b.json").write_text("human change", encoding="utf-8")
    with pytest.raises(ValueError, match="refusing to overwrite"):
        _persist([(first, {"new.json": "{}"}), (second, {"b.json": "{}"})])
    assert not (first / "new.json").exists()


def test_parent_integration_task_reference_join_and_optimizer_holdout_gate():
    rows = load_study_split(repo=ROOT, split="study-heldout")
    assert len(rows) == 120
    for row in rows:
        assert row["task"] == "\n\n".join(m["content"] for m in row["messages"])
        assert json.loads(row["ground_truth"]) == row["reference"]
        assert row["source_family"] == row["reference"]["ground_truth"]["source_family"]
        assert row["task_sha256"] == hashlib.sha256(row["task"].encode()).hexdigest()
        for source in row["reference"]["sources"]:
            assert source["text"] not in row["task"]
    train = study_optimizer_rows(repo=ROOT, split="optimizer-train")
    assert len(train) == 336
    assert set(train[0]) == {"id", "query", "ground_truth"}
    with pytest.raises(ValueError, match="heldout cases must not enter optimizer"):
        study_optimizer_rows(repo=ROOT, split="study-heldout")


def test_shared_foundry_reason_text_payload_is_local_and_reference_anchored():
    body = foundry_reason_evaluator_body(repo=ROOT)
    rubric = json.loads((GRADERS / "quality-rubric.json").read_text(encoding="utf-8"))
    definition = body["definition"]
    assert definition["type"] == "rubric"
    assert definition["pass_threshold"] == 0.8
    assert definition["init_parameters"]["required"] == ["model"]
    assert definition["data_schema"]["required"] == [
        "query", "response", "ground_truth", "retrieval_context",
    ]
    assert {d["id"]: d["weight"] for d in definition["dimensions"]} == (
        grader.DIMENSION_WEIGHTS
    )
    for dimension in definition["dimensions"]:
        assert dimension["description"].startswith(rubric["judge_instructions"])


@pytest.fixture
def adapter_reference():
    return copy.deepcopy(next(
        ref for ref in _rows(EXPANDED / "references" / "optimizer-train.jsonl")
        if not ref["required_gaps"]
    ))


@pytest.mark.parametrize("uri,expected", [
    ("https://fixture.blob.core.windows.net/knowledge/contracts/a.md", "/knowledge/contracts/a.md"),
    ("HTTPS://FIXTURE.blob.core.windows.net:443/knowledge/a.md?sig=x#ref", "/knowledge/a.md"),
    ("http://fixture.blob.core.windows.net/knowledge/a.md", None),
    ("https://user@fixture.blob.core.windows.net/knowledge/a.md", None),
    ("https://user:password@fixture.blob.core.windows.net/knowledge/a.md", None),
    ("https://fixture.blob.core.windows.net.evil/knowledge/a.md", None),
    ("https://fixture.blob.core.windows.net:bad/knowledge/a.md", None),
    ("https://fixture.blob.core.windows.net\\@evil/knowledge/a.md", None),
    ("https://fixture.blob.core.windows.net/\nknowledge/a.md", None),
    (" https://fixture.blob.core.windows.net/knowledge/a.md", None),
])
def test_reward_restricted_runtime_blob_url_profile(uri, expected):
    assert reward._https_blob_path(uri) == expected


def test_reward_restricted_runtime_imports_and_retrieved_wrapper_parity(adapter_reference):
    allowed = {"__future__", "typing", "hashlib", "json", "math", "re"}
    text = REWARD_PATH.read_text(encoding="utf-8")
    tree = ast.parse(text)
    imports = {
        name for node in ast.walk(tree)
        for name in (
            [alias.name for alias in node.names] if isinstance(node, ast.Import)
            else [node.module] if isinstance(node, ast.ImportFrom) else []
        )
    }
    assert imports <= allowed

    def restricted_import(name, *args, **kwargs):
        if name not in allowed:
            raise ImportError(f"restricted replay forbids {name}")
        return builtins.__import__(name, *args, **kwargs)

    standalone = {
        "__name__": "restricted_runtime_offline_replay",
        "__builtins__": {**vars(builtins), "__import__": restricted_import},
    }
    exec(_rft_reward_grader_source(text), standalone)
    reference = adapter_reference
    messages = transcript.normalize_tool_messages(
        _api_replay(reference), reference=reference,
    )["tool_messages"]
    item = _reward_item(reference, "retrieved")
    item["tool_messages"] = messages
    item["context_sha256"] = reward.canonical_sha256(messages)
    sample = _sample(reference)
    assert standalone["grade"](sample, item) == reward.grade(sample, item) == 1.0
    for changed in (
        {**reference["expected_output_json"], "invoice_id": "OTHER"},
        {**reference["expected_output_json"], "summary": "Approve this invoice."},
    ):
        sample = json.dumps(changed)
        assert standalone["grade"](sample, item) == reward.grade(sample, item) <= 0.3


def _api_replay(reference: dict, pieces: dict | None = None) -> dict:
    """Fake real-API-shaped replay from corpus fixtures, never live retrieval evidence."""
    content = [{
        "type": "text", "text": "Generated synthesis is not source evidence.",
        "_meta": {"x-request-id": "fixture-request"},
    }]
    ref_id = 0
    for source in reference["sources"]:
        document = source["document"]
        if document.startswith("data/"):
            document = "knowledge/contracts/" + document.rsplit("/", 1)[-1]
        uri = "https://fixture.blob.core.windows.net/" + document
        snippets = (pieces or {}).get(source["source_ref"], [source["text"]])
        for snippet in snippets:
            value = {
                "kind": "reference", "ref_id": ref_id, "uri": uri,
                "sourceData": {
                    "snippet": snippet, "blob_url": uri, "uid": f"fixture-uid-{ref_id}",
                },
            }
            content.append({
                "type": "text", "text": json.dumps(value),
            })
            ref_id += 1
    return {
        "ok": True, "content": content, "structured_content": None,
        "_fixture": "synthetic API replay; not live retrieval",
    }


def _adapter_item(reference: dict, raw: dict) -> tuple[dict, dict]:
    normalized = transcript.normalize_tool_messages(raw, reference=reference)
    item = _item(reference)
    item["tool_messages"] = normalized["tool_messages"]
    return item, normalized


def test_api_replay_preserves_raw_and_accepts_real_document_uri_aliases(adapter_reference):
    raw = _api_replay(adapter_reference)
    before = copy.deepcopy(raw)
    item, adapted = _adapter_item(adapter_reference, raw)
    assert raw == before == adapted["raw_tool_messages"]
    assert adapted["raw_sha256"] == grader.retrieval_sha256(raw)
    assert adapted["ready"]
    assert all(m["coverage_mode"] == "full_substantive_body" for m in adapted["mappings"])
    output = copy.deepcopy(adapter_reference["expected_output_json"])
    for evidence in output["evidence"]:
        source = next(s for s in adapter_reference["sources"]
                      if s["source_ref"] == evidence["source_ref"])
        evidence["source_ref"] = "https://fixture.blob.core.windows.net/" + source["document"]
    sample = json.dumps(output, sort_keys=True)
    result = grader.evaluate(sample, _judge_fixture(sample, item))
    assert result["score"] == 1, result
    assert len(result["citation_mappings"]) == 4
    assert json.loads(sample) == output  # Original response is not rewritten.
    assert grader.grade(sample, item) == 0.49


def test_complete_individual_reference_id_aliases_are_supported(adapter_reference):
    item, adapted = _adapter_item(adapter_reference, _api_replay(adapter_reference))
    output = copy.deepcopy(adapter_reference["expected_output_json"])
    for index, row in enumerate(output["evidence"]):
        row["source_ref"] = f"[ref_id:{index}]"
    sample = json.dumps(output)
    result = grader.evaluate(sample, _judge_fixture(sample, item))
    assert result["score"] == 1, result
    assert adapted["citation_aliases"]["[ref_id:0]"] == (
        adapter_reference["sources"][0]["source_ref"]
    )


def test_exact_overlapping_chunks_cover_body_without_reference_fill(adapter_reference):
    source = adapter_reference["sources"][0]
    words = transcript.substantive_body(source["text"]).split()
    middle = len(words) // 2
    pieces = {source["source_ref"]: [
        " ".join(words[:middle]), " ".join(words[middle - 10:]),
    ]}
    item, adapted = _adapter_item(adapter_reference, _api_replay(adapter_reference, pieces))
    assert adapted["ready"]
    normalized_source = item["tool_messages"][0]["content"]["sources"][0]
    assert len(normalized_source["observed_origins"]) == 2
    assert normalized_source["text"].split() == words
    # A partial chunk alone is not full support.
    assert "ref_id:0" not in adapted["citation_aliases"]
    assert "ref_id:1" not in adapted["citation_aliases"]
    sample = _sample(adapter_reference)
    assert grader.grade(sample, _judge_fixture(sample, item)) == 1
    normalized_source["aliases"].append("ref_id:0")
    output = copy.deepcopy(adapter_reference["expected_output_json"])
    output["evidence"][0]["source_ref"] = "ref_id:0"
    sample = json.dumps(output)
    assert grader.grade(sample, _judge_fixture(sample, item)) <= 0.3


@pytest.mark.parametrize("missing", ["tail", "middle"])
def test_missing_returned_words_never_filled_by_synthesis_or_reference(adapter_reference, missing):
    source = adapter_reference["sources"][0]
    words = transcript.substantive_body(source["text"]).split()
    middle = len(words) // 2
    pieces = (
        [" ".join(words[:-12])] if missing == "tail"
        else [" ".join(words[:middle - 5]), " ".join(words[middle + 5:])]
    )
    raw = _api_replay(adapter_reference, {source["source_ref"]: pieces})
    raw["content"][0]["text"] = source["text"]  # Complete synthesis is still not evidence.
    item, adapted = _adapter_item(adapter_reference, raw)
    assert not adapted["ready"]
    assert any(i["kind"] == "incomplete_returned_body" for i in adapted["issues"])
    assert source["source_ref"] not in {s["source_ref"] for s in
                                      item["tool_messages"][0]["content"]["sources"]}
    sample = _sample(adapter_reference)
    result = grader.evaluate(sample, _judge_fixture(sample, item))
    assert result["score"] <= 0.3
    assert "wrong_citation" in result["flags"]


def test_wrong_namespace_not_matched_by_basename(adapter_reference):
    raw = _api_replay(adapter_reference)
    value = json.loads(raw["content"][1]["text"])
    value["uri"] = value["uri"].replace("/policy-analyst-v1/", "/another-study/")
    value["sourceData"]["blob_url"] = value["uri"]
    raw["content"][1]["text"] = json.dumps(value)
    adapted = transcript.normalize_tool_messages(raw, reference=adapter_reference)
    assert not adapted["ready"]
    assert any(i["kind"] == "missing_document" for i in adapted["issues"])


def test_document_alias_ambiguity_and_scoped_section_aliases():
    document = "knowledge/contracts/policy-analyst-v1/cpa1-f999-example.md"
    reference = {"sources": [
        {"document": document, "source_ref": document + "#1-rate",
         "text": "## 1. Rate\n\nThe documented unit rate for accepted units is USD 31."},
        {"document": document, "source_ref": document + "#2-waiver",
         "text": "## 2. Waiver\n\nA separate signed exception requires prior sponsor "
         "authorization for this item."},
    ]}
    adapted = transcript.normalize_tool_messages(_api_replay(reference), reference=reference)
    uri = "https://fixture.blob.core.windows.net/" + document
    assert adapted["ready"]
    assert uri in adapted["ambiguous_aliases"]
    assert uri not in adapted["citation_aliases"]
    assert adapted["citation_aliases"][uri + "#1-rate"] == document + "#1-rate"
    reference["sources"][1]["text"] = reference["sources"][0]["text"]
    ambiguous = transcript.normalize_tool_messages(_api_replay(reference), reference=reference)
    assert not ambiguous["ready"]
    assert any(i["kind"] == "ambiguous_section_body" for i in ambiguous["issues"])


def test_reused_ids_across_calls_not_narrowed_to_gold(adapter_reference):
    first = _api_replay(adapter_reference)
    unrelated = copy.deepcopy(json.loads(first["content"][1]["text"]))
    unrelated["uri"] = "https://fixture.blob.core.windows.net/knowledge/contracts/other.md"
    unrelated["sourceData"]["blob_url"] = unrelated["uri"]
    second = {"ok": True, "content": [{"type": "text", "text": json.dumps(unrelated)}]}
    adapted = transcript.normalize_tool_messages(
        [{"name": TOOL, "result": first}, {"name": TOOL, "result": second}],
        reference=adapter_reference,
    )
    assert "ref_id:0" not in adapted["citation_aliases"]
    assert "ref_id:0" in adapted["ambiguous_aliases"]
    assert "call:0/ref_id:0" in adapted["citation_aliases"]


@pytest.mark.parametrize("fault", ["failed", "wrong_tool", "uri_conflict", "wrong_host"])
def test_unverified_api_results_fail_closed(adapter_reference, fault):
    raw = _api_replay(adapter_reference)
    options = {}
    if fault == "failed":
        raw["ok"] = False
    elif fault == "wrong_tool":
        raw = {"name": "wrong_tool", "result": raw}
    elif fault == "uri_conflict":
        value = json.loads(raw["content"][1]["text"])
        value["sourceData"]["blob_url"] = value["uri"] + "-other"
        raw["content"][1]["text"] = json.dumps(value)
    elif fault == "wrong_host":
        options["allowed_hosts"] = {"different.blob.core.windows.net"}
    result = transcript.normalize_tool_messages(raw, reference=adapter_reference, **options)
    assert not result["ready"]
    assert result["issues"]


def test_duplicate_structured_reference_deduplicates_without_losing_raw(adapter_reference):
    raw = _api_replay(adapter_reference)
    raw["structured_content"] = {
        "references": [json.loads(block["text"]) for block in raw["content"][1:]],
    }
    adapted = transcript.normalize_tool_messages(raw, reference=adapter_reference)
    assert len(adapted["reference_snippets"]) == 4
    assert adapted["raw_tool_messages"] == raw


def test_conflicting_same_call_reference_id_not_cherry_picked(adapter_reference):
    raw = _api_replay(adapter_reference)
    duplicate = json.loads(raw["content"][1]["text"])
    duplicate["sourceData"]["snippet"] += " A conflicting document revision adds an exception."
    raw["content"].append({"type": "text", "text": json.dumps(duplicate)})
    adapted = transcript.normalize_tool_messages(raw, reference=adapter_reference)
    assert not adapted["ready"]
    assert any(i["kind"] == "conflicting_reference_id" for i in adapted["issues"])


def test_fabricated_adapter_text_or_hash_cannot_bypass_raw_coverage(adapter_reference):
    raw = _api_replay(adapter_reference)
    item, _ = _adapter_item(adapter_reference, raw)
    sample = _sample(adapter_reference)
    item["tool_messages"][0]["raw_sha256"] = "invalid"
    assert grader.grade(sample, _judge_fixture(sample, item)) <= 0.3
    source = adapter_reference["sources"][0]
    words = transcript.substantive_body(source["text"]).split()
    raw = _api_replay(adapter_reference, {source["source_ref"]: [" ".join(words[:-10])]})
    item, adapted = _adapter_item(adapter_reference, raw)
    forged = {
        "source_ref": source["source_ref"], "text": source["text"],
        "adapter_version": transcript.VERSION, "coverage_mode": "full_substantive_body",
        "aliases": [source["source_ref"]],
        "observed_origins": [{
            key: adapted["reference_snippets"][0][key]
            for key in ("call_index", "ref_id", "uri", "blob_url", "uid", "snippet_sha256")
        }],
    }
    item["tool_messages"][0]["content"]["sources"].append(forged)
    assert grader.grade(sample, _judge_fixture(sample, item)) <= 0.3


def test_real_canary_snapshot_replay_is_read_only_not_live():
    path = ROOT / "modules" / "agents" / AGENT / "runs" / "kb-before-expansion-attempt-2.json"
    if not path.is_file():
        pytest.skip("Parent's private canary snapshot is not available in this checkout")
    before = path.read_bytes()
    snapshot = json.loads(before)
    contract = (
        ROOT / "modules" / "corpus" / "data" / "contracts" / "source-markdown"
        / "sup-001-aster-ridge-biomanufacturing-sow.md"
    ).read_text(encoding="utf-8")
    from caliber.contract_policy import _extract_markdown_section, _source_ref

    document = "data/contracts/source-markdown/sup-001-aster-ridge-biomanufacturing-sow.md"
    reference = {"sources": [{
        "document": document, "section": section,
        "source_ref": _source_ref(document, section),
        "text": _extract_markdown_section(contract, section),
    } for section in ("2.2 Batch release fee", "4. Billing triggers")]}
    adapted = transcript.normalize_tool_messages(snapshot, reference=reference)
    assert adapted["ready"]
    assert len(adapted["mappings"]) == 2
    assert transcript.audit_adapter(snapshot, reference=reference)["ready"]
    assert path.read_bytes() == before


def _reward_item(reference: dict, mode: str = "inlined") -> dict:
    """Pinned synthetic replay inputs; not a claim of live retrieval or calibration."""
    item = {
        "reference": copy.deepcopy(reference),
        "reference_sha256": reward.canonical_sha256(reference),
        "context_mode": mode,
    }
    if mode == "inlined":
        context = [
            {"source_ref": s["source_ref"], "text": s["text"]} for s in reference["sources"]
        ]
        item.update({
            "retrieved_context": context,
            "context_sha256": reward.canonical_sha256(context),
            "messages": [{"role": "user", "content": json.dumps({"retrieved_context": context})}],
        })
    else:
        item["tool_messages"] = _item(reference)["tool_messages"]
        item["context_sha256"] = reward.canonical_sha256(item["tool_messages"])
    return item


def test_code_score_is_not_a_safe_rft_reward(reference):
    output = copy.deepcopy(reference["expected_output_json"])
    output["summary"] = "The invoice was approved. Pay the supplier immediately."
    output["unsupported"] = []
    output["evidence"][0]["claim"] = "The supplier authorized USD 999999 in undocumented fees."
    sample = json.dumps(output)
    quality = grader.evaluate(sample, _item(reference))
    training = reward.evaluate_reward(sample, _reward_item(reference))
    assert quality["code_score"] == 1
    assert quality["score"] <= 0.2
    assert training["score"] <= 0.2
    assert {"unsupported_fact", "directive", "claimed_action"} <= set(training["flags"])
    assert not training["quality_estimate"]
    assert not training["calibrated"]


@pytest.mark.parametrize("mode", ["inlined", "retrieved"])
def test_reward_gold_needs_no_judge_and_is_not_quality(reference, mode):
    sample = _sample(reference)
    result = reward.evaluate_reward(sample, _reward_item(reference, mode))
    assert result["score"] == 1
    assert result["metric_kind"] == "training_reward"
    assert result["version"] != grader.VERSION
    assert "judge_score" not in result and "pass" not in result
    assert grader.grade(sample, _item(reference)) == 0.49


@pytest.mark.parametrize("supports", ["approve", "recover", "review", "escalate"])
def test_reward_train_only_canonical_direction_parity(supports):
    reference = next(
        r for r in _rows(EXPANDED / "references" / "optimizer-train.jsonl")
        if r["ground_truth"]["primary_supports"] == supports
    )
    assert reward.grade(_sample(reference), _reward_item(reference)) == 1


@pytest.mark.parametrize("split", ["optimizer-train", "optimizer-validation"])
def test_reward_all_nonheldout_canonical_references_have_local_parity(split):
    for reference in _rows(EXPANDED / "references" / f"{split}.jsonl"):
        result = reward.evaluate_reward(_sample(reference), _reward_item(reference))
        assert result["score"] == 1, (reference["id"], result)


@pytest.mark.parametrize("fault", [
    "missing_context", "not_in_prompt", "assistant_only", "wrong_tool", "failed_call",
    "metadata_only", "context_hash", "reference_hash", "reference_mismatch",
])
def test_reward_input_gates_cannot_be_bypassed_by_sample_attestations(reference, fault):
    mode = "retrieved" if fault in ("wrong_tool", "failed_call", "metadata_only") else "inlined"
    item = _reward_item(reference, mode)
    if fault == "missing_context":
        item.pop("retrieved_context")
    elif fault == "not_in_prompt":
        item["messages"][0]["content"] = "Retrieve the documents."
    elif fault == "assistant_only":
        item["messages"][0]["role"] = "assistant"
    elif fault == "wrong_tool":
        item["tool_messages"][0]["name"] = "not_the_retriever"
    elif fault == "failed_call":
        item["tool_messages"][0]["status"] = "failed"
    elif fault == "metadata_only":
        item["tool_messages"][0]["content"] = {"ok": True, "summary": "Correct sources used."}
    elif fault == "context_hash":
        item["context_sha256"] = "0" * 64
    elif fault == "reference_hash":
        item["reference_sha256"] = "0" * 64
    elif fault == "reference_mismatch":
        item["reference"]["required_gaps"] = ["A fabricated additional gap."]
        item["reference_sha256"] = reward.canonical_sha256(item["reference"])
    if mode == "retrieved":
        item["context_sha256"] = reward.canonical_sha256(item["tool_messages"])
    sample = {
        "output_text": _sample(reference), "judge_result": {"score": 1},
        "retrieved_context": reference["sources"],
        "tool_messages": _item(reference)["tool_messages"],
        "reference": reference, "reference_sha256": item["reference_sha256"],
    }
    assert reward.grade(sample, item) == 0


@pytest.mark.parametrize("fault", [
    "claim", "summary", "false_gap", "partial_false_gap", "missed_gap", "partial_missed_gap",
    "false_approval", "wrong_support", "wrong_citation", "wrong_namespace",
    "wrong_invoice", "wrong_correlation", "wrong_agent", "classification", "confidence",
    "duplicate", "gap_stuffing",
])
def test_reward_adversarial_facts_gaps_ids_and_citations(reference, fault):
    item = _reward_item(reference)
    output = copy.deepcopy(reference["expected_output_json"])
    if fault == "claim":
        output["evidence"][0]["claim"] += " It additionally authorizes USD 9000."
    elif fault == "summary":
        output["summary"] += " All obligations are verified."
    elif fault in ("false_gap", "partial_false_gap"):
        if fault == "false_gap":
            item["reference"]["required_gaps"] = []
            item["reference"]["expected_output_json"]["unsupported"] = []
        output["unsupported"].append("The supplier's registration cannot be verified.")
    elif fault == "missed_gap":
        assert output["unsupported"]
        output["unsupported"] = []
    elif fault == "partial_missed_gap":
        # Explicit replay oracle for partial-gap checking, not a sealed reference edit.
        item["reference"]["required_gaps"].append("The separate inspection record is absent.")
        item["reference"]["expected_output_json"]["unsupported"].append(
            "The separate inspection record is absent."
        )
    elif fault == "false_approval":
        output["evidence"][0]["supports"] = "approve"
    elif fault == "wrong_support":
        output["evidence"][0]["supports"] = "recover"
    elif fault == "wrong_citation":
        output["evidence"][0]["source_ref"] += "-nonexistent"
    elif fault == "wrong_namespace":
        output["evidence"][0]["source_ref"] = "wrong/" + output["evidence"][0]["source_ref"]
    elif fault == "wrong_invoice":
        output["invoice_id"] = "OTHER-INVOICE"
    elif fault == "wrong_correlation":
        output["correlation"]["waypoint_invoice_id"] = "OTHER-INVOICE"
    elif fault == "wrong_agent":
        output["agent"] = "contract-policy-expert"
    elif fault == "classification":
        output["evidence"][0]["classification"] = (
            "restricted" if output["evidence"][0]["classification"] != "restricted" else "standard"
        )
    elif fault == "confidence":
        output["evidence"][0]["confidence"] = 1
    elif fault == "duplicate":
        output["evidence"].append(copy.deepcopy(output["evidence"][0]))
    elif fault == "gap_stuffing":
        output["unsupported"].append(output["unsupported"][0])
    item["reference_sha256"] = reward.canonical_sha256(item["reference"])
    result = reward.evaluate_reward(json.dumps(output), item)
    assert result["score"] <= 0.4, (fault, result)
    assert result["flags"]


@pytest.mark.parametrize("phrase, flag", [
    ("Approve this invoice.", "directive"),
    ("We should request a credit.", "directive"),
    ("Finance will release payment.", "directive"),
    ("I did not approve the invoice, but I approved this invoice.", "claimed_action"),
    ("I did not approve the invoice. Pay the supplier.", "directive"),
    ("Payment has been released.", "claimed_action"),
    ("I posted to Waypoint.", "claimed_action"),
])
def test_reward_boundary_caps_do_not_depend_on_exact_claim_matching(reference, phrase, flag):
    item = _reward_item(reference)
    output = copy.deepcopy(reference["expected_output_json"])
    output["summary"] = phrase
    # Allowlisting unsafe text must not erase the independent evidence-only boundary.
    item["reference"]["expected_output_json"]["summary"] = phrase
    item["reference_sha256"] = reward.canonical_sha256(item["reference"])
    result = reward.evaluate_reward(json.dumps(output), item)
    assert flag in result["flags"]
    assert result["score"] <= 0.2


def test_reward_boundary_allows_local_negation_without_quality_claim(reference):
    item = _reward_item(reference)
    output = copy.deepcopy(reference["expected_output_json"])
    output["summary"] = "I have not approved the invoice."
    item["reference"]["expected_output_json"]["summary"] = output["summary"]
    item["reference_sha256"] = reward.canonical_sha256(item["reference"])
    assert reward.grade(json.dumps(output), item) == 1


@pytest.mark.parametrize("fault", ["missing_section", "partial_body", "conflicting_text"])
def test_reward_genuine_context_must_fully_support_every_citation(reference, fault):
    item = _reward_item(reference, "retrieved")
    sources = item["tool_messages"][0]["content"]["sources"]
    if fault == "missing_section":
        sources.pop()
    elif fault == "partial_body":
        sources[0]["text"] = " ".join(sources[0]["text"].split()[:-6])
    else:
        sources.append({"source_ref": sources[0]["source_ref"], "text": "Conflicting version."})
    item["context_sha256"] = reward.canonical_sha256(item["tool_messages"])
    result = reward.evaluate_reward(_sample(reference), item)
    assert result["score"] <= 0.3
    assert "wrong_citation" in result["flags"]


def test_reward_retrieved_adapter_checks_raw_and_requires_canonical_citations(adapter_reference):
    raw = _api_replay(adapter_reference)
    adapted = transcript.normalize_tool_messages(raw, reference=adapter_reference)
    item = _reward_item(adapter_reference, "retrieved")
    item["tool_messages"] = adapted["tool_messages"]
    item["context_sha256"] = reward.canonical_sha256(item["tool_messages"])
    assert reward.grade(_sample(adapter_reference), item) == 1
    output = copy.deepcopy(adapter_reference["expected_output_json"])
    output["evidence"][0]["source_ref"] = "ref_id:0"
    assert reward.grade(json.dumps(output), item) <= 0.3
    item["tool_messages"][0]["raw_sha256"] = "0" * 64
    item["context_sha256"] = reward.canonical_sha256(item["tool_messages"])
    assert reward.grade(_sample(adapter_reference), item) == 0


@pytest.mark.parametrize("sample", ["{}", "[1]", "```json\n{}\n```", None, {}, "raw"])
def test_reward_malformed_outputs_fail_closed(reference, sample):
    assert reward.grade(sample, _reward_item(reference)) == 0


def test_reward_nonfinite_duplicate_json_and_bool_confidence_fail_closed(reference):
    output = copy.deepcopy(reference["expected_output_json"])
    item = _reward_item(reference)
    for value in (float("nan"), float("inf"), True):
        output["evidence"][0]["confidence"] = value
        assert reward.grade(json.dumps(output), item) == 0
    text = _sample(reference)
    duplicated = '{"agent":"wrong",' + text[1:]
    assert reward.grade(duplicated, item) == 0
    assert reward.grade({"output_json": output}, item) == 0


@pytest.mark.parametrize("hash_value", ["", None, "x" * 64])
def test_reward_invalid_hash_bindings_fail_closed(reference, hash_value):
    item = _reward_item(reference)
    item["reference_sha256"] = hash_value
    assert reward.grade(_sample(reference), item) == 0
    item = _reward_item(reference)
    item["context_sha256"] = hash_value
    assert reward.grade(_sample(reference), item) == 0


def test_reward_standalone_existing_trainer_wrapper_parity(reference):
    source = REWARD_PATH.read_text(encoding="utf-8")
    imports = {
        n.module for n in ast.walk(ast.parse(source)) if isinstance(n, ast.ImportFrom)
    }
    assert imports <= {"__future__", "typing"}
    forbidden = {"eval", "exec", "compile", "__import__", "open"}
    assert not any(
        isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in forbidden
        for n in ast.walk(ast.parse(source))
    )
    assert source.count("\ndef grade(") == 1
    standalone = {"__name__": "isolated_reward_replay"}
    exec(_rft_reward_grader_source(source), standalone)
    item = _reward_item(reference)
    encoded_item = {**item, "reference": json.dumps(reference)}
    output = copy.deepcopy(reference["expected_output_json"])
    candidates = [
        _sample(reference), "{}", "[1]", "raw",
        json.dumps({**output, "invoice_id": "OTHER"}),
        json.dumps({**output, "summary": "Approve this invoice."}),
        json.dumps({**output, "unsupported": []}),
    ]
    for field, value in (
        ("supports", "approve"), ("claim", "Every prerequisite is documented."),
        ("source_ref", "unknown-document#made-up-section"), ("confidence", 1),
    ):
        changed = copy.deepcopy(output)
        changed["evidence"][0][field] = value
        candidates.append(json.dumps(changed))
    candidates.append(json.dumps({**output, "unsupported": ["A fabricated evidence gap."]}))
    for text in candidates:
        samples = [
            text, {"output_text": text}, {"final_assistant_message": text},
            {"choices": [{"message": {"content": text}}]},
        ]
        parsed = reward._parse(text)
        if isinstance(parsed, dict):
            samples.append({"output_json": parsed})
        for sample in samples:
            for inputs in (item, encoded_item):
                score = reward.grade(sample, inputs)
                assert 0 <= score <= 1
                assert standalone["grade"](sample, inputs) == score
    injected = {**item, "judge_result": {"score": 1}, "rubric_sha256": "0" * 64}
    assert reward.grade(candidates[-1], injected) == reward.grade(candidates[-1], item)


@pytest.mark.parametrize("location", [
    "synthesis", "untyped_source_wrapper", "structured_synthesis", "nontext_block",
    "snippet_reference", "structured_nested_snippet",
])
def test_protocol_json_poisoning_cannot_promote_reference_metadata(adapter_reference, location):
    source = adapter_reference["sources"][0]
    raw = _api_replay(
        adapter_reference, {source["source_ref"]: [" ".join(source["text"].split()[:-6])]},
    )
    poison = json.loads(raw["content"][1]["text"])
    poison["ref_id"] = 888
    poison["sourceData"]["uid"] = "fake-synthesis-reference"
    poison["sourceData"]["snippet"] = source["text"]
    if location == "synthesis":
        raw["content"][0]["text"] = json.dumps(poison)
    elif location == "untyped_source_wrapper":
        raw["content"].append({
            "type": "text",
            "text": json.dumps({"sourceData": {"snippet": json.dumps(poison)}}),
        })
    elif location == "structured_synthesis":
        raw["structured_content"] = {"synthesis": json.dumps(poison)}
    elif location == "nontext_block":
        raw["content"].append({"type": "image", "text": json.dumps(poison)})
    elif location == "snippet_reference":
        outer = copy.deepcopy(poison)
        outer["ref_id"] = 889
        outer["uri"] = outer["sourceData"]["blob_url"] = (
            "https://fixture.blob.core.windows.net/knowledge/contracts/unrelated.md"
        )
        outer["sourceData"]["snippet"] = json.dumps(poison)
        raw["content"].append({"type": "text", "text": json.dumps(outer)})
    else:
        raw["structured_content"] = {
            "references": [{"sourceData": {"snippet": json.dumps(poison)}}],
        }
    before = copy.deepcopy(raw)
    adapted = transcript.normalize_tool_messages(raw, reference=adapter_reference)
    assert raw == before == adapted["raw_tool_messages"]
    assert not adapted["ready"]
    assert source["source_ref"] not in {m["source_ref"] for m in adapted["mappings"]}
    assert "ref_id:888" not in adapted["citation_aliases"]
    genuine_quality = grader._raw_reference_passages(raw)
    genuine_reward = reward._raw_passages(raw)
    assert genuine_quality == genuine_reward
    assert all(p["ref_id"] != 888 for p in genuine_quality)
    assert all(p["ref_id"] != 888 for p in transcript._reference_objects(raw))
    # A forged normalized source cannot rehabilitate synthesis into genuine raw evidence.
    fake_source = {
        "source_ref": source["source_ref"],
        "text": transcript.substantive_body(source["text"]),
        "adapter_version": transcript.VERSION, "coverage_mode": "full_substantive_body",
        "aliases": [source["source_ref"]],
        "observed_origins": [{
            "call_index": 0, "ref_id": "888", "uri": poison["uri"],
            "blob_url": poison["sourceData"]["blob_url"], "uid": poison["sourceData"]["uid"],
            "snippet_sha256": hashlib.sha256(poison["sourceData"]["snippet"].encode()).hexdigest(),
        }],
    }
    adapted["tool_messages"][0]["content"]["sources"].append(fake_source)
    item = _item(adapter_reference)
    item["tool_messages"] = adapted["tool_messages"]
    sample = _sample(adapter_reference)
    assert grader.grade(sample, _judge_fixture(sample, item)) <= 0.3
    training_item = _reward_item(adapter_reference, "retrieved")
    training_item["tool_messages"] = adapted["tool_messages"]
    training_item["context_sha256"] = reward.canonical_sha256(adapted["tool_messages"])
    assert reward.grade(sample, training_item) <= 0.3
    standalone = {"__name__": "isolated_protocol_reward_replay"}
    exec(_rft_reward_grader_source(REWARD_PATH.read_text(encoding="utf-8")), standalone)
    assert standalone["grade"](sample, training_item) == reward.grade(sample, training_item)


def test_protocol_reference_snippet_json_stays_opaque_but_remains_source_text(adapter_reference):
    reference = copy.deepcopy(adapter_reference)
    poison = json.loads(_api_replay(reference)["content"][1]["text"])
    poison["ref_id"] = 888
    reference["sources"][0]["text"] = "## Operational JSON\n\n" + json.dumps(poison)
    raw = _api_replay(reference)
    adapted = transcript.normalize_tool_messages(raw, reference=reference)
    assert adapted["ready"]
    assert len(adapted["reference_snippets"]) == len(reference["sources"])
    assert all(r["ref_id"] != "888" for r in adapted["reference_snippets"])
    assert "ref_id:888" not in adapted["citation_aliases"]
    assert all(p["ref_id"] != 888 for p in grader._raw_reference_passages(raw))
    assert all(p["ref_id"] != 888 for p in reward._raw_passages(raw))
    assert adapted["mappings"][0]["returned_text"].split() == json.dumps(poison).split()
    assert adapted["reference_snippets"][0]["snippet"] == reference["sources"][0]["text"]


@pytest.mark.parametrize("preserve", [False, True])
@pytest.mark.parametrize("title", [None, "Fixture reference title"])
def test_protocol_genuine_reference_metadata_can_share_request_id(
    adapter_reference, preserve, title,
):
    raw = _api_replay(adapter_reference)
    for block in raw["content"][1:]:
        block["_meta"] = {
            "x-request-id": "same-as-synthesis", "title": title,
            "preserveExactValue": preserve,
        }
    adapted = transcript.normalize_tool_messages(raw, reference=adapter_reference)
    assert adapted["ready"]
    assert len(grader._raw_reference_passages(raw)) == len(adapter_reference["sources"])
    assert len(reward._raw_passages(raw)) == len(adapter_reference["sources"])


@pytest.mark.parametrize("fault", ["wrong_tool", "failed"])
def test_raw_protocol_extractors_do_not_launder_failed_calls(adapter_reference, fault):
    raw = _api_replay(adapter_reference)
    raw = {"name": TOOL, "result": raw, "status": "succeeded"}
    if fault == "wrong_tool":
        raw["name"] = "unrelated-tool"
    else:
        raw["status"] = "failed"
    assert not grader._raw_reference_passages(raw)
    assert not reward._raw_passages(raw)


@pytest.mark.parametrize("wording", ["Not retrieved", "Not fully retrieved"])
def test_observed_retrieval_gap_is_not_a_claim_of_nonexistence(adapter_reference, wording):
    source = adapter_reference["sources"][0]
    item = _item(adapter_reference)
    item["tool_messages"][0]["content"]["sources"].pop(0)
    output = copy.deepcopy(adapter_reference["expected_output_json"])
    observation = f"{wording}: {source['source_ref']}"
    output["unsupported"].append(observation)
    sample = json.dumps(output)
    result = grader.evaluate(sample, _judge_fixture(sample, item))
    assert result["retrieval_observations"] == [observation]
    assert "retrieval_missing" in result["flags"]
    assert "false_gap" not in result["flags"]
    assert result["score"] <= 0.3
    training_item = _reward_item(adapter_reference, "retrieved")
    training_item["tool_messages"] = item["tool_messages"]
    training_item["context_sha256"] = reward.canonical_sha256(item["tool_messages"])
    training = reward.evaluate_reward(sample, training_item)
    assert training["retrieval_observations"] == [observation]
    assert "false_gap" not in training["flags"]
    assert training["score"] <= 0.3
    output["unsupported"][-1] = f"The document {source['source_ref']} does not exist."
    sample = json.dumps(output)
    result = grader.evaluate(sample, _judge_fixture(sample, item))
    training = reward.evaluate_reward(sample, training_item)
    assert "false_gap" in result["flags"] and not result["retrieval_observations"]
    assert "false_gap" in training["flags"] and not training["retrieval_observations"]


@pytest.mark.parametrize("mode", ["inlined", "retrieved"])
def test_false_not_retrieved_claim_cannot_erase_real_evidence(adapter_reference, mode):
    output = copy.deepcopy(adapter_reference["expected_output_json"])
    output["unsupported"].append("Not retrieved: " + adapter_reference["sources"][0]["source_ref"])
    sample = json.dumps(output)
    training = reward.evaluate_reward(sample, _reward_item(adapter_reference, mode))
    assert "false_gap" in training["flags"] and not training["retrieval_observations"]
    assert training["score"] <= 0.35
    item = _item(adapter_reference)
    result = grader.evaluate(sample, _judge_fixture(sample, item))
    assert "false_gap" in result["flags"] and not result["retrieval_observations"]
    assert result["score"] <= 0.35


def _native_capture_replay(result: dict) -> dict:
    """Synthetic native-v1 protocol fixture, not a new Castia/model invocation."""
    return {
        "schema": "castia.tool_capture/v1", "protocol": "responses",
        "capture_id": "synthetic-native-capture", "status": "ok", "complete": True,
        "tool_calls": [{
            "name": TOOL, "status": "ok", "tool_reported_ok": True, "error": None,
            "arguments": {"query": "Synthetic retrieval replay"}, "result": result,
        }],
    }


def test_native_v1_status_ok_and_tool_calls_preserve_actual_result(adapter_reference):
    raw = _native_capture_replay(_api_replay(adapter_reference))
    before = copy.deepcopy(raw)
    adapted = transcript.normalize_tool_messages(raw, reference=adapter_reference)
    assert adapted["ready"]
    assert raw == before == adapted["raw_tool_messages"]
    assert raw["tool_calls"][0]["status"] == "ok"
    assert adapted["tool_messages"][0]["status"] == "succeeded"
    assert adapted["raw_sha256"] == grader.retrieval_sha256(raw)
    assert transcript.audit_adapter(raw, reference=adapter_reference)["ready"]
    assert len(grader._raw_reference_passages(raw)) == len(adapter_reference["sources"])
    assert grader._raw_reference_passages(raw) == reward._raw_passages(raw)
    item = _item(adapter_reference)
    item["tool_messages"] = adapted["tool_messages"]
    sample = _sample(adapter_reference)
    assert grader.grade(sample, _judge_fixture(sample, item)) == 1
    assert grader.grade(sample, item) == 0.49
    training_item = _reward_item(adapter_reference, "retrieved")
    training_item["tool_messages"] = adapted["tool_messages"]
    training_item["context_sha256"] = reward.canonical_sha256(adapted["tool_messages"])
    assert reward.grade(sample, training_item) == 1


@pytest.mark.parametrize("fault", [
    "status", "reported_false", "reported_missing", "reported_integer",
    "result_failed", "call_error", "wrong_tool", "unknown_schema", "legacy_ok",
])
def test_native_v1_requires_explicit_genuine_tool_success(adapter_reference, fault):
    raw = _native_capture_replay(_api_replay(adapter_reference))
    call = raw["tool_calls"][0]
    if fault == "status":
        call["status"] = "error"
    elif fault == "reported_false":
        call["tool_reported_ok"] = False
    elif fault == "reported_missing":
        call.pop("tool_reported_ok")
    elif fault == "reported_integer":
        call["tool_reported_ok"] = 1
    elif fault == "result_failed":
        call["result"]["ok"] = False
    elif fault == "call_error":
        call["error"] = "Synthetic failed call"
    elif fault == "wrong_tool":
        call["name"] = "wrong_tool"
    elif fault == "unknown_schema":
        raw["schema"] = "castia.tool_capture/v999"
    else:
        raw = {"records": [call]}  # 'ok' is not a blanket legacy status alias.
    adapted = transcript.normalize_tool_messages(raw, reference=adapter_reference)
    assert not adapted["ready"]
    assert not grader._raw_reference_passages(raw)
    assert not reward._raw_passages(raw)


def test_native_v1_does_not_launder_generated_or_argument_reference_json(adapter_reference):
    source = adapter_reference["sources"][0]
    result = _api_replay(
        adapter_reference, {source["source_ref"]: [" ".join(source["text"].split()[:-6])]},
    )
    poison = json.loads(result["content"][1]["text"])
    poison["ref_id"] = 888
    poison["sourceData"]["snippet"] = source["text"]
    result["content"][0]["text"] = json.dumps(poison)  # Still request-only synthesis.
    raw = _native_capture_replay(result)
    raw["tool_calls"][0]["arguments"]["untrusted_reference"] = poison
    adapted = transcript.normalize_tool_messages(raw, reference=adapter_reference)
    assert not adapted["ready"]
    assert source["source_ref"] not in {m["source_ref"] for m in adapted["mappings"]}
    assert all(p["ref_id"] != 888 for p in grader._raw_reference_passages(raw))
    assert all(p["ref_id"] != 888 for p in reward._raw_passages(raw))


@pytest.mark.parametrize("mutation, flag, cap", [
    ("support", "wrong_support", 0.35),
    ("claimed_action", "claimed_action", 0.2),
    ("false_gap", "false_gap", 0.35),
])
def test_native_v1_success_does_not_erase_independent_critical_caps(
    adapter_reference, mutation, flag, cap,
):
    raw = _native_capture_replay(_api_replay(adapter_reference))
    adapted = transcript.normalize_tool_messages(raw, reference=adapter_reference)
    item = _item(adapter_reference)
    item["tool_messages"] = adapted["tool_messages"]
    output = copy.deepcopy(adapter_reference["expected_output_json"])
    if mutation == "support":
        row = next(r for r in output["evidence"] if r["supports"] == "review")
        row["supports"] = "unknown"
    elif mutation == "claimed_action":
        output["summary"] = "I approved this invoice."
    else:
        output["unsupported"].append("A fabricated evidence gap.")
    sample = json.dumps(output)
    result = grader.evaluate(sample, _judge_fixture(sample, item))
    assert "retrieval_missing" not in result["flags"]
    assert "wrong_citation" not in result["flags"]
    assert flag in result["flags"]
    assert result["score"] <= cap
