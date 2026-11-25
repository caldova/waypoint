"""Grader v3 / RFT reward v2 behavior over the versioned v3 references (offline)."""

import copy
import hashlib
import importlib.util
import json
import re
from pathlib import Path

import pytest

AGENT = "contract-policy-analyst"
TOOL = "contracts-kb-mcp___knowledge_base_retrieve"
ROOT = Path(__file__).resolve().parents[3]
GRADERS = ROOT / "modules" / "evals" / "graders" / AGENT
REFS = ROOT / "modules" / "evals" / "datasets" / AGENT / "expanded-v1" / "references-v3"
RUBRIC_V3 = GRADERS / "quality-rubric-v3.json"


def _load(name: str, file: str):
    spec = importlib.util.spec_from_file_location(name, GRADERS / file)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


grader = _load("cpa_grader_v3_test", "contract_policy_analyst_grader_v3.py")
reward = _load("cpa_reward_v2_test", "contract_policy_analyst_rft_reward_v2.py")


def _all_refs() -> list[dict]:
    return [
        json.loads(line)
        for split in ("optimizer-train", "optimizer-validation", "study-heldout")
        for line in (REFS / f"{split}.jsonl").read_text(encoding="utf-8").splitlines()
    ]


REFERENCES = _all_refs()
BY_ID = {r["id"]: r for r in REFERENCES}


def _first(category: str) -> dict:
    return copy.deepcopy(next(r for r in REFERENCES if r["v3_contract"]["category"] == category))


def _item(reference: dict) -> dict:
    return {
        "reference": reference,
        "rubric_sha256": hashlib.sha256(RUBRIC_V3.read_bytes()).hexdigest(),
        "tool_messages": [{
            "name": TOOL, "status": "succeeded",
            "content": {"sources": [
                {"source_ref": s["source_ref"], "text": s["text"]} for s in reference["sources"]
            ]},
        }],
    }


def _judged(sample: str, item: dict, flags: list[str] | None = None) -> dict:
    """Synthetic perfect-judge fixture; no model was invoked."""
    item = copy.deepcopy(item)
    item["judge_result"] = {
        "judge_model": "gpt-6-astra",
        "output_sha256": grader.output_sha256(sample),
        "retrieval_sha256": grader.retrieval_sha256(item["tool_messages"]),
        "rubric_sha256": item["rubric_sha256"],
        "critical_flags": flags or [],
        "dimensions": [{
            "id": key, "score": 5,
            "reason": "Offline fixture: the named retrieved section supports this claim.",
        } for key in grader._base.DIMENSION_WEIGHTS],
    }
    return item


def _reward_item(reference: dict) -> dict:
    context = [{"source_ref": s["source_ref"], "text": s["text"]} for s in reference["sources"]]
    return {
        "reference": copy.deepcopy(reference),
        "reference_sha256": reward.canonical_sha256(reference),
        "context_mode": "inlined",
        "retrieved_context": context,
        "context_sha256": reward.canonical_sha256(context),
        "messages": [{"role": "user", "content": json.dumps({"retrieved_context": context})}],
    }


def _both(reference: dict, output: dict) -> tuple[dict, dict]:
    sample = json.dumps(output)
    return (
        grader.evaluate(sample, _judged(sample, _item(reference))),
        reward.evaluate_reward(sample, _reward_item(reference)),
    )


def test_every_v3_fixture_reaches_full_score_and_passes():
    assert len(REFERENCES) == 576
    for reference in REFERENCES:
        sample = json.dumps(reference["expected_output_json"])
        quality = grader.evaluate(sample, _judged(sample, _item(reference)))
        training = reward.evaluate_reward(sample, _reward_item(reference))
        assert quality["score"] == 1.0 and quality["pass"], (reference["id"], quality["flags"])
        assert quality["code_flags"] == []
        assert training["score"] == 1.0 and training["flags"] == [], (
            reference["id"], training["flags"],
        )


def test_f008_l012_reference_math_is_corrected_to_accepted_units():
    reference = BY_ID["cpa-expanded:CPA1-F008-L012"]
    terms = reference["v3_contract"]
    assert terms["category"] == "recover"
    assert terms["amount_readings"] == {"accepted_quantity": "13986.00"}
    assert "13986.00" in reference["expected_output_json"]["summary"]
    assert {c["field"] for c in terms["corrections"]} == {"record_supports", "expected_amount"}
    assert reference["synthetic"] is True
    assert reference["review_status"] == "pending_human_review"


@pytest.mark.parametrize("text", [
    "The cost and credit records were not returned by retrieval.",
    "Credit treatment for the variance remains unverified.",
    "Applying the cap and credit gives USD 1463.00.",
    "The approver must attest to the request before release.",
    "The policy requires escalation when quality status conflicts.",
    "Payment status is not established by the retrieved sources.",
    "Do not pay or dispute this invoice; the controller decides.",
    "Recovery applicability depends on the accepted quantity.",
])
def test_boundary_screen_allows_neutral_evidence_language(text):
    assert grader.boundary_flags(text) == set()
    assert reward._boundary(text) == set()


@pytest.mark.parametrize(("text", "flag"), [
    ("Pay the supplier USD 84.00.", "directive"),
    ("Finance should dispute the overbilled amount.", "directive"),
    ("We recommend that AP withhold payment.", "directive"),
    ("Review the records and recover the difference.", "directive"),
    ("The invoice must be escalated to procurement.", "directive"),
    ("We have approved the invoice.", "claimed_action"),
    ("The payment was released yesterday.", "claimed_action"),
    ("Updated the Waypoint record with this result.", "claimed_action"),
])
def test_boundary_screen_still_flags_directives_and_claimed_actions(text, flag):
    assert flag in grader.boundary_flags(text)
    assert flag in reward._boundary(text)


def test_reward_boundary_vocabulary_is_identical_to_grader_v3():
    for name in ("ACTION", "IMPERATIVE", "NOUN_FOLLOW", "OBJECT", "DIRECTIVES", "CLAIMED",
                 "NEGATION"):
        assert getattr(reward, name) == getattr(grader, name), name
    shared = reward.CAPS.keys() & grader.CAPS.keys()
    assert {"false_approval", "missed_approval", "wrong_support", "directive"} <= shared
    assert {flag: reward.CAPS[flag] for flag in shared} == {
        flag: grader.CAPS[flag] for flag in shared
    }


def test_distinct_claims_on_one_source_are_not_duplicates_but_copies_are():
    reference = _first("recover")
    output = copy.deepcopy(reference["expected_output_json"])
    row = output["evidence"][0]
    output["evidence"].append({
        **row, "claim": "A second, distinct condition in the same section limits billable scope.",
    })
    quality, training = _both(reference, output)
    assert "duplicate_evidence" not in quality["flags"]
    assert "duplicate_evidence" not in training["flags"]
    output["evidence"][-1] = {**row, "claim": row["claim"] + " "}
    quality, training = _both(reference, output)
    assert "duplicate_evidence" in quality["flags"]
    assert "duplicate_evidence" in training["flags"]


def test_specific_extra_gap_is_not_a_deterministic_false_gap():
    reference = _first("approve")
    output = copy.deepcopy(reference["expected_output_json"])
    output["unsupported"] = [
        *output["unsupported"], "The delivery acceptance certificate itself was not retrieved.",
    ]
    quality, training = _both(reference, output)
    assert "false_gap" not in quality["flags"] and quality["pass"]
    assert "false_gap" not in training["flags"] and training["score"] == 1.0


def test_required_gap_is_enforced_only_when_contract_requires_it():
    reference = _first("missing_condition")
    assert reference["v3_contract"]["gap_required"]
    output = copy.deepcopy(reference["expected_output_json"])
    output["unsupported"] = []
    quality, training = _both(reference, output)
    assert "missed_gap" in quality["flags"] and not quality["pass"]
    assert "missed_gap" in training["flags"]


def test_classification_mismatch_is_recorded_not_capped():
    reference = _first("approve")
    output = copy.deepcopy(reference["expected_output_json"])
    row = output["evidence"][0]
    row["classification"] = next(c for c in reward.CLASSIFICATIONS if c != row["classification"])
    quality, training = _both(reference, output)
    assert quality["pass"] and quality["classification_mismatches"]
    assert "wrong_citation" not in quality["flags"]
    assert training["score"] == 1.0 and training["classification_mismatches"]


@pytest.mark.parametrize("category", ["wrong_entity", "escalate", "recover"])
def test_forbidden_approval_is_a_false_approval(category):
    reference = _first(category)
    assert "approve" in reference["v3_contract"]["forbidden_supports"] or category == "recover"
    output = copy.deepcopy(reference["expected_output_json"])
    for row in output["evidence"]:
        row["supports"] = "approve"
    quality, training = _both(reference, output)
    if "approve" in reference["v3_contract"]["forbidden_supports"]:
        assert "false_approval" in quality["flags"] and "false_approval" in training["flags"]
    assert "wrong_support" in quality["flags"] and "wrong_support" in training["flags"]
    assert not quality["pass"] and training["score"] <= 0.35


def test_withholding_required_approval_evidence_is_missed_approval():
    reference = _first("approve")
    output = copy.deepcopy(reference["expected_output_json"])
    for row in output["evidence"]:
        row["supports"] = "review"
    quality, training = _both(reference, output)
    assert "missed_approval" in quality["flags"] and "missed_approval" in training["flags"]
    assert not quality["pass"] and training["score"] <= 0.35


def test_neutral_sources_accept_review_or_unknown():
    reference = _first("ambiguous")
    output = copy.deepcopy(reference["expected_output_json"])
    terms = reference["v3_contract"]
    swapped = False
    for row in output["evidence"]:
        allowed = set(terms["allowed_supports"][row["source_ref"]])
        if {"review", "unknown"} <= allowed:
            row["supports"] = "unknown" if row["supports"] == "review" else "review"
            swapped = True
    assert swapped
    quality, training = _both(reference, output)
    assert "wrong_support" not in quality["flags"] and quality["pass"]
    assert training["score"] == 1.0


def test_reward_does_not_require_reference_wording_but_flags_invented_numbers():
    reference = _first("recover")
    output = copy.deepcopy(reference["expected_output_json"])
    for row in output["evidence"]:
        row["claim"] = "Paraphrased: " + row["claim"].lower()
    output["summary"] = "Evidence is summarized neutrally; the controller retains the decision."
    training = reward.evaluate_reward(json.dumps(output), _reward_item(reference))
    assert training["score"] == 1.0, training["flags"]
    output["evidence"][0]["claim"] = "The supplier separately authorized USD 987654.00 in fees."
    training = reward.evaluate_reward(json.dumps(output), _reward_item(reference))
    assert "unsupported_fact" in training["flags"] and training["score"] <= 0.35


def test_reward_accepts_derived_arithmetic_but_not_fabricated_figures():
    grounding = {"297.00", "280.00", "97.00", "3.00", "28759.53", "363.00", "372.00", "132.00"}
    derived = (
        "280 x USD 97 + 17 x USD 97 x 0.97 = USD 28,759.53; 363 x 132 = USD 47,916.00, "
        "9 units or USD 1,188.00 above min(372,363)."
    )
    assert reward._ungrounded_text(derived, grounding) == set()
    assert reward._ungrounded_text("A credit of USD 41,250.17 applies.", grounding) == {
        "41250.17",
    }
    assert reward._ungrounded_text("Billed 419 units.", grounding) == {"419.00"}
    # Documented limitation: a coincidentally derivable small figure (280 + 132) passes.
    assert reward._ungrounded_text("Billed 412 units.", grounding) == set()


def _capture(snippet: str, uri: str, **call_overrides) -> dict:
    call = {
        "name": TOOL, "status": "ok", "tool_reported_ok": True, "error": None,
        "result": {"ok": True, "content": [{"type": "text", "text": json.dumps({
            "kind": "reference", "ref_id": "2", "uri": uri,
            "sourceData": {"snippet": snippet, "blob_url": uri},
        })}]},
    }
    call.update(call_overrides)
    return {"schema": "castia.tool_capture/v1", "tool_calls": [call]}


def _blob(ref: str) -> str:
    return "https://acct.blob.core.windows.net/" + ref.split("#", 1)[0]


def _excerpt_case(snippet_fn=None, uri_fn=None, sha_fn=None, **call_overrides):
    """A retrieval where the SOW section is only quoted as an excerpt in a raw passage."""
    reference = copy.deepcopy(BY_ID["cpa-expanded:CPA1-F001-L001"])
    sow = next(s for s in reference["sources"] if "-sow.md#" in s["source_ref"])
    words = reward._body(sow["text"]).split()
    snippet = (
        f"Earlier section tail.\n\n## 5. Commercial rule\n\n**Source ref:** {sow['source_ref']}"
        f"\n\n{' '.join(words[:30])} partialwo"
    )
    snippet = snippet_fn(snippet, sow["source_ref"]) if snippet_fn else snippet
    uri = uri_fn(sow["source_ref"]) if uri_fn else _blob(sow["source_ref"])
    raw = _capture(snippet, uri, **call_overrides)
    message = {
        "name": TOOL, "status": "succeeded",
        "content": {"sources": [
            {"source_ref": s["source_ref"], "text": s["text"]}
            for s in reference["sources"] if s is not sow
        ]},
        "raw_tool_messages": raw,
        "raw_sha256": sha_fn(raw) if sha_fn else reward.canonical_sha256(raw),
    }
    sample = json.dumps(reference["expected_output_json"])
    quality_item = _item(reference)
    quality_item["tool_messages"] = [message]
    reward_item = {
        "reference": reference, "reference_sha256": reward.canonical_sha256(reference),
        "context_mode": "retrieved", "tool_messages": [message],
        "context_sha256": reward.canonical_sha256([message]),
        "messages": [{"role": "user", "content": "Review invoice CPA1-F001-INV001."}],
    }
    return (
        sow["source_ref"],
        grader.evaluate(sample, _judged(sample, quality_item)),
        reward.evaluate_reward(sample, reward_item),
    )


def test_verified_excerpt_under_explicit_source_ref_makes_a_ref_citable():
    ref, quality, training = _excerpt_case()
    assert quality["excerpt_covered_refs"] == [ref] and training["excerpt_covered_refs"] == [ref]
    assert "wrong_citation" not in quality["code_flags"]
    assert "wrong_citation" not in training["flags"]


@pytest.mark.parametrize("variant", [
    {"sha_fn": lambda raw: "0" * 64},
    {"error": "boom"},
    {"status": "error"},
    {"result": {"ok": False, "content": []}},
    {"uri_fn": lambda ref: _blob(ref.replace("-sow.md", "-evidence-policy.md"))},
    {"uri_fn": lambda ref: "https://evil.example.com/" + ref.split("#")[0]},
    {"snippet_fn": lambda s, ref: s.replace("**Source ref:** ", "Query: ")},
    {"snippet_fn": lambda s, ref: s.replace(" the ", " a ", 1)},
    {"snippet_fn": lambda s, ref: s.split(ref)[0] + ref + "\n\nThe fee is USD 5. x"},
])
def test_excerpt_coverage_requires_provenance_and_verbatim_body(variant):
    _, quality, training = _excerpt_case(**variant)
    assert quality["excerpt_covered_refs"] == [] and training["excerpt_covered_refs"] == []
    assert "wrong_citation" in quality["code_flags"]
    assert "wrong_citation" in training["flags"]


def test_reward_grounds_numbers_only_in_verified_successful_raw_retrieval():
    raw = _capture("SOW excerpt: base price is USD 6,417.31.", _blob("knowledge/contracts/x.md"))
    message = {"raw_tool_messages": raw, "raw_sha256": reward.canonical_sha256(raw)}
    texts = reward._raw_retrieval_texts(message)
    assert texts and all("6,417.31" in t for t in texts)
    grounding = set().union(*(reward._numbers(t) for t in texts))
    assert reward._ungrounded_text("Price USD 6,417.31.", grounding) == set()
    for bad in (
        {"raw_sha256": "0" * 64},
        {"raw_tool_messages": _capture("USD 6,417.31", "u", result={"ok": False, "content": [
            {"type": "text", "text": "USD 6,417.31"}]})},
        {"raw_tool_messages": _capture("USD 6,417.31", "u", status="error")},
        {"raw_tool_messages": _capture("USD 6,417.31", "u", error="boom")},
    ):
        broken = {**message, **bad}
        if "raw_tool_messages" in bad:
            broken["raw_sha256"] = reward.canonical_sha256(bad["raw_tool_messages"])
        assert reward._raw_retrieval_texts(broken) == [], bad


def test_hidden_reference_text_never_grounds_numbers():
    reference = _first("recover")
    reference["expected_output_json"]["summary"] += " Hidden total USD 812345.67."
    reference["required_gaps"] = [*reference.get("required_gaps", []), "USD 723456.78 gap."]
    output = copy.deepcopy(reference["expected_output_json"])
    output["summary"] = "The evidence shows a total of USD 812345.67."
    training = reward.evaluate_reward(json.dumps(output), _reward_item(reference))
    assert "unsupported_fact" in training["flags"] and training["score"] <= 0.35
    output["summary"] = "The evidence shows a gap of USD 723456.78."
    training = reward.evaluate_reward(json.dumps(output), _reward_item(reference))
    assert "unsupported_fact" in training["flags"]


def test_assistant_and_tool_argument_text_never_grounds_numbers():
    reference = _first("recover")
    item = _reward_item(reference)
    item["messages"].append({"role": "assistant", "content": "Earlier I said USD 555444.33."})
    output = copy.deepcopy(reference["expected_output_json"])
    output["summary"] = "The evidence shows USD 555444.33."
    assert "unsupported_fact" in reward.evaluate_reward(json.dumps(output), item)["flags"]


@pytest.mark.parametrize(("claim", "flagged"), [
    ("The billed item meets every acceptance condition.", True),
    ("All acceptance conditions were satisfied for this item.", True),
    ("The line is billable as invoiced.", True),
    ("It is not established that the billed item meets every acceptance condition.", False),
    ("Whether all acceptance conditions were met remains unverified.", False),
    ("The item is billable only if both conditions are confirmed.", False),
    ("The line is not billable on the retrieved evidence.", False),
    ("Only excess units are billable at USD 154 each.", False),
    ("Of the 289 observed units, 17 are billable, supporting USD 1,445.00.", False),
    ("The other item's values cannot establish that USD 1402.00 is billable.", False),
    ("The evidence does not explain the difference or establish that it is billable.", False),
])
def test_claim_level_approval_assertions_are_false_approval(claim, flagged):
    reference = copy.deepcopy(BY_ID["cpa-expanded:CPA1-F001-L009"])
    assert reference["v3_contract"]["category"] == "missing_condition"
    output = copy.deepcopy(reference["expected_output_json"])
    output["evidence"][0]["claim"] = claim
    quality, training = _both(reference, output)
    assert ("false_approval" in quality["flags"]) is flagged
    assert ("false_approval" in training["flags"]) is flagged
    if flagged:
        assert not quality["pass"] and training["score"] <= 0.2


def test_approval_language_is_allowed_where_the_contract_permits_it():
    recover = _first("recover")
    assert reward.approval_flags("Both prerequisites were confirmed.", "recover") == set()
    assert reward.approval_flags("The line is billable as invoiced.", "recover") == {
        "false_approval",
    }
    assert reward.approval_flags("The line is billable as invoiced.", "approve") == set()
    assert reward.approval_flags("All conditions are met.", "approve") == set()
    assert recover["v3_contract"]["category"] == "recover"


def test_distinct_quantities_on_one_source_are_not_duplicates():
    assert not reward.exact_duplicate(
        "Accepted 12 units on day 3.", ["Accepted 13 units on day 3."],
    )
    assert reward.exact_duplicate("Accepted 12 units, on day 3!", ["accepted 12 units on day 3"])


@pytest.mark.parametrize(("text", "flagged"), [
    ("The policy says the invoice must be escalated to procurement.", False),
    ("The SOW states that the supplier should credit unaccepted units.", False),
    ("Per the SOW, finance must recover the overcharge.", True),
    ("The invoice must be escalated to procurement.", True),
    ("The policy states that evidence is required, but finance must recover the overcharge.", True),
    ("The SOW states that logs are required; finance must recover the overcharge.", True),
    ("The policy says evidence is needed, however the controller should withhold payment.", True),
    ("The policy states that logs are required \u2014 finance must recover the overcharge.", True),
    ("The policy states that logs are required - finance must recover the overcharge.", True),
    ("The policy states that logs are required (finance must recover the overcharge).", True),
    ("The policy states that logs are required\nFinance must recover the overcharge.", True),
])
def test_source_attributed_modal_obligations_are_not_directives(text, flagged):
    assert ("directive" in grader.boundary_flags(text)) is flagged
    assert ("directive" in reward._boundary(text)) is flagged


def test_attribution_cannot_launder_a_directive_into_full_reward():
    reference = _first("recover")
    output = copy.deepcopy(reference["expected_output_json"])
    output["summary"] = (
        "The policy states that evidence is required, but finance must recover the overcharge."
    )
    training = reward.evaluate_reward(json.dumps(output), _reward_item(reference))
    assert "directive" in training["flags"] and training["score"] <= 0.2


def test_excerpt_coverage_rejects_non_native_failed_captures():
    def legacy(raw):
        call = raw["tool_calls"][0]
        call.update(status="succeeded", tool_reported_ok=False, error="boom")
        return {"records": [call]}

    reference = copy.deepcopy(BY_ID["cpa-expanded:CPA1-F001-L001"])
    sow = next(s for s in reference["sources"] if "-sow.md#" in s["source_ref"])
    words = reward._body(sow["text"]).split()
    snippet = f"## 5. Rule\n\n**Source ref:** {sow['source_ref']}\n\n{' '.join(words[:30])}"
    raw = legacy(_capture(snippet, _blob(sow["source_ref"])))
    message = {
        "name": TOOL, "status": "succeeded", "content": {"sources": []},
        "raw_tool_messages": raw, "raw_sha256": reward.canonical_sha256(raw),
    }
    bodies = {s["source_ref"]: reward._body(s["text"]) for s in reference["sources"]}
    assert reward.excerpt_covered_refs([message], bodies) == set()


def test_rounded_quotients_are_derivable():
    assert reward._ungrounded_text("1000/3000 = 0.33", {"1000.00", "3000.00"}) == set()
    assert reward._ungrounded_text("ratio 0.47", {"1000.00", "3000.00"}) == {"0.47"}


def test_fixed_fee_with_zero_accepted_items_supports_no_fee():
    fixed = [
        r for r in REFERENCES
        if r["ground_truth"]["authored_rule"]["calculation"] == "fixed"
        and r["v3_contract"]["category"] not in {"wrong_entity"}
    ]
    assert fixed
    for reference in fixed:
        readings = reference["v3_contract"]["amount_readings"]
        if reference["ground_truth"]["observed_facts"]["accepted_quantity"] == 0 and readings:
            assert readings == {"accepted_items": "0.00"}, reference["id"]
            assert reference["v3_contract"]["category"] != "ambiguous", reference["id"]


def test_reward_rejects_v1_references_and_gaming_shapes():
    reference = _first("approve")
    legacy = copy.deepcopy(reference)
    legacy.pop("v3_contract")
    sample = json.dumps(reference["expected_output_json"])
    assert reward.evaluate_reward(sample, _reward_item(legacy))["flags"] == ["invalid_reference"]
    item = _reward_item(reference)
    item["reference_sha256"] = "0" * 64
    assert reward.evaluate_reward(sample, item)["flags"] == ["reference_hash_mismatch"]
    for gamed in ("", "not json", sample + sample, json.dumps({"evidence": []})):
        assert reward.evaluate_reward(gamed, _reward_item(reference))["score"] == 0.0
    stuffed = copy.deepcopy(reference["expected_output_json"])
    stuffed["unsupported"] = [*stuffed["unsupported"], *stuffed["unsupported"]]
    if stuffed["unsupported"]:
        result = reward.evaluate_reward(json.dumps(stuffed), _reward_item(reference))
        assert "stuffing" in result["flags"]


def test_rubric_v3_keeps_dimension_contract_and_caps_flags():
    rubric = json.loads(RUBRIC_V3.read_text(encoding="utf-8"))
    assert {d["id"]: d["weight"] for d in rubric["dimensions"]} == grader._base.DIMENSION_WEIGHTS
    assert rubric["review_status"] == "pending_human_review"
    named = re.search(r"Use critical_flags (.+?) when applicable", rubric["judge_instructions"])
    assert named is not None
    flags = set(re.findall(r"[a-z_]+", named.group(1))) - {"or"}
    assert flags <= grader.CAPS.keys()
    assert {"false_approval", "missed_approval"} <= flags
