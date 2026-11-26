"""Grader v3: claim-level evidence-direction contract over versioned v3 references.

v1 and v2 stay frozen. This revision reuses v1's hash-pinned parsing, retrieval,
citation-alias and judge-binding helpers and replaces only the scoring rules that
the hand audit found defective:

* per-source acceptable direction sets from ``reference["v3_contract"]`` replace a
  single exact label, so neutral sources accept review or unknown;
* classification is recorded but never graded as a citation error;
* duplicate_evidence fires only for an exact normalized repeat on the same source;
* claim-level approval assertions the contract forbids are false_approval;
* a provenance-verified contiguous excerpt under an explicit Source ref line
  makes a ref citable, alongside full-body coverage;
* false_gap is not a deterministic flag (the judge may still raise it);
* missed_gap fires only when the contract requires a gap and none is asserted;
* false_approval/missed_approval are deterministic where the contract decides them;
* the directive screen no longer fires on coordinated or clause-initial nouns
  ("and credit records", "Credit treatment ..."), on nouns after a modal's verb, or
  on modal obligations explicitly attributed to a source ("the policy says ...").

The phrase, approval, duplicate and excerpt helpers are shared with RFT reward v2
(loaded from its file) so the quality and training layers cannot drift apart.

The phrase screen is a lexical backstop, not a semantic guarantee; the shared
reason-text judge remains the semantic layer.
"""

from __future__ import annotations

import hashlib
import importlib.util
import re
from pathlib import Path
from typing import Any

BASE_PATH = Path(__file__).with_name("contract_policy_analyst_grader.py")
BASE_SHA256 = "267d5f6c7cebe3baaf8b243d97ea6bc4a8befbdb95b9ee85a3a07f8bc5bf6f62"
if hashlib.sha256(BASE_PATH.read_bytes()).hexdigest() != BASE_SHA256:
    raise ValueError("Frozen analyst grader v1 changed; create a new grader revision.")
spec = importlib.util.spec_from_file_location("_contract_policy_analyst_grader_v3_base", BASE_PATH)
if spec is None or spec.loader is None:
    raise ValueError("Cannot load frozen analyst grader v1.")
_base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(_base)
REWARD_PATH = Path(__file__).with_name("contract_policy_analyst_rft_reward_v2.py")
_reward_spec = importlib.util.spec_from_file_location(
    "_contract_policy_analyst_grader_v3_reward", REWARD_PATH,
)
if _reward_spec is None or _reward_spec.loader is None:
    raise ValueError("Cannot load RFT reward v2 helpers.")
_reward = importlib.util.module_from_spec(_reward_spec)
_reward_spec.loader.exec_module(_reward)

VERSION = "contract-policy-analyst-grader-v3"
REFERENCE_VERSION = "contract-policy-analyst-reference-v3"
PASS_THRESHOLD = _base.PASS_THRESHOLD
CAPS = {**_base.CAPS, "false_approval": 0.2, "missed_approval": 0.35}
_base.CAPS = CAPS
_base.VERSION = VERSION
JUDGE_LAYER_FLAGS = {"judge_unverified", "semantic_unverified"}

ACTION = _base.ACTION
IMPERATIVE = _base.IMPERATIVE
NOUN_FOLLOW = _reward.NOUN_FOLLOW
OBJECT = _reward.OBJECT
DIRECTIVES = _reward.DIRECTIVES
CLAIMED = _base.CLAIMED
NEGATION = _base.NEGATION


def output_sha256(sample: Any) -> str:
    return _base.output_sha256(sample)


def retrieval_sha256(tool_messages: Any) -> str:
    return _base.retrieval_sha256(tool_messages)


def boundary_flags(text: str) -> set[str]:
    """Lexical directive/claimed-action backstop; not a semantic guarantee."""
    return _reward._boundary(text)

def _valid_contract(reference: dict[str, Any]) -> bool:
    terms = reference.get("v3_contract")
    if reference.get("version") != REFERENCE_VERSION or not isinstance(terms, dict):
        return False
    refs = {s["source_ref"] for s in reference["sources"]}
    allowed = terms.get("allowed_supports")
    require = terms.get("require_any")
    return (
        isinstance(allowed, dict) and set(allowed) == refs
        and all(
            isinstance(v, list) and v and set(v) <= _base.SUPPORTS for v in allowed.values()
        )
        and isinstance(terms.get("forbidden_supports"), list)
        and set(terms["forbidden_supports"]) <= _base.SUPPORTS
        and isinstance(terms.get("gap_required"), bool)
        and isinstance(terms.get("approval_expected"), bool)
        and (
            require is None or isinstance(require, dict)
            and set(require.get("supports", [])) <= _base.SUPPORTS
            and set(require.get("source_refs", [])) <= refs
            and bool(require.get("supports")) and bool(require.get("source_refs"))
        )
    )


def evaluate(sample: Any, item: dict[str, Any]) -> dict[str, Any]:
    """The item is evaluator-owned, never concatenated with the model request."""
    result: dict[str, Any] = {
        "version": VERSION, "score": 0.0, "code_score": 0.0, "code_only_score": 0.0,
        "judge_score": None, "flags": [], "code_flags": [], "pass": False,
        "judge_reasons": [], "citation_mappings": [], "retrieval_observations": [],
        "classification_mismatches": [], "category": None, "excerpt_covered_refs": [],
    }
    text = _base.output_text(sample)
    if len(text) > 20000:
        result["flags"] = result["code_flags"] = ["stuffing"]
        return result
    output = _base._parse(text)
    if not _base._shape(output):
        result["flags"] = result["code_flags"] = ["invalid_json_or_shape"]
        return result
    reference = item.get("reference")
    if not isinstance(reference, dict):
        result["flags"] = ["missing_reference"]
        return result
    expected = reference.get("expected_output_json")
    sources = reference.get("sources")
    if (
        not _base._shape(expected) or not isinstance(sources, list) or not sources
        or not isinstance(reference.get("allowed_claims"), dict)
        or not isinstance(reference.get("required_gaps"), list)
        or not all(_base._string(g) for g in reference.get("required_gaps", []))
        or not all(isinstance(s, dict) and _base._string(s.get("source_ref"))
                   and _base._string(s.get("text"), 30000) for s in sources)
        or len({s["source_ref"] for s in sources}) != len(sources)
        or set(reference["allowed_claims"]) != {s["source_ref"] for s in sources}
        or {r["source_ref"] for r in expected["evidence"]}
        != {s["source_ref"] for s in sources}
        or not _valid_contract(reference)
    ):
        result["flags"] = ["invalid_reference"]
        return result
    terms = reference["v3_contract"]
    result["category"] = terms.get("category")
    flags: set[str] = set()
    if any(output[key] != expected[key] for key in (
        "agent", "plane", "invoice_id", "output_type", "correlation",
    )):
        flags.add("wrong_identity")
    retrieved = _base._retrieved(item.get("tool_messages"))
    if not retrieved:
        flags.add("retrieval_missing")
    source_by_ref = {s["source_ref"]: s for s in sources}
    adapter_sources = _base._adapter_sources(item.get("tool_messages"))
    citation_aliases = _base._citation_aliases(sources, adapter_sources)
    norm = _base._norm
    covered_refs = {
        s["source_ref"] for s in sources
        if norm(s["text"]) in norm(retrieved.get(s["source_ref"], ""))
        or bool(retrieved.get(s["source_ref"])) and _base._adapter_coverage(s, adapter_sources)
    }
    excerpts = _reward.excerpt_covered_refs(
        item.get("tool_messages"), {s["source_ref"]: s["text"] for s in sources},
    ) - covered_refs
    covered_refs |= excerpts
    result["excerpt_covered_refs"] = sorted(excerpts)
    expected_by_ref = {r["source_ref"]: r for r in expected["evidence"]}
    allowed_by_ref = {ref: set(v) for ref, v in terms["allowed_supports"].items()}
    forbidden = set(terms["forbidden_supports"])
    claims_by_ref: dict[str, list[str]] = {}
    supports_by_ref: dict[str, set[str]] = {}
    exact_semantics = True
    correct_citations = correct_supports = 0
    for row in output["evidence"]:
        original_ref = row["source_ref"]
        ref = (
            original_ref if original_ref in source_by_ref
            else citation_aliases.get(original_ref, original_ref)
        )
        if ref != original_ref:
            result["citation_mappings"].append({
                "original_source_ref": original_ref, "canonical_source_ref": ref,
            })
        if _reward.exact_duplicate(row["claim"], claims_by_ref.get(ref, [])):
            flags.add("duplicate_evidence")
        claims_by_ref.setdefault(ref, []).append(row["claim"])
        supports_by_ref.setdefault(ref, set()).add(row["supports"])
        if ref in source_by_ref and ref in covered_refs:
            correct_citations += 1
        else:
            flags.add("wrong_citation")
        if row["supports"] in forbidden:
            flags.add("wrong_support")
            if row["supports"] == "approve":
                flags.add("false_approval")
        elif ref in allowed_by_ref and row["supports"] in allowed_by_ref[ref]:
            correct_supports += 1
        else:
            flags.add("wrong_support")
        target = expected_by_ref.get(ref)
        if target and row["classification"] != target["classification"]:
            result["classification_mismatches"].append({
                "source_ref": ref, "output": row["classification"],
                "source": target["classification"],
            })
        allowed = reference["allowed_claims"].get(ref, [])
        if norm(row["claim"]) not in {norm(c) for c in allowed if isinstance(c, str)}:
            exact_semantics = False
        if target is None or row["supports"] != target["supports"]:
            exact_semantics = False
    if not set(expected_by_ref) <= set(claims_by_ref):
        flags.add("wrong_citation")
    require = terms.get("require_any")
    if require and not any(
        supports_by_ref.get(ref, set()) & set(require["supports"])
        for ref in require["source_refs"]
    ):
        flags.add("missed_approval" if terms["approval_expected"] else "wrong_support")
    gaps = output["unsupported"]
    asserted = []
    known_gaps = {norm(g) for g in expected["unsupported"]}
    for gap in gaps:
        observation = re.fullmatch(r"Not (?:fully )?retrieved:\s*(.+)", gap, re.IGNORECASE)
        ref = observation.group(1) if observation else None
        if norm(gap) not in known_gaps and ref in source_by_ref and ref not in covered_refs:
            result["retrieval_observations"].append(gap)
            flags.add("retrieval_missing")
        else:
            asserted.append(gap)
    if terms["gap_required"] and not asserted:
        flags.add("missed_gap")
    if {norm(g) for g in asserted} != known_gaps:
        exact_semantics = False
    if len({norm(g) for g in gaps}) != len(gaps):
        flags.add("stuffing")
    if norm(output["summary"]) != norm(expected["summary"]):
        exact_semantics = False
    for value in [output["summary"], *gaps, *[r["claim"] for r in output["evidence"]]]:
        flags.update(boundary_flags(value))
        flags.update(_reward.approval_flags(value, terms.get("category")))
        if len(value.split()) > 180:
            flags.add("stuffing")
    count = len(output["evidence"])
    code_score = 0.25 + 0.4 * correct_citations / count + 0.35 * correct_supports / count
    code_flags = set(flags)
    if not exact_semantics:
        code_flags.add("semantic_unverified")
    judge_score, judge_flags, reasons = _base._judge(sample, item)
    flags.update(judge_flags)
    if not exact_semantics and judge_score is None:
        flags.add("semantic_unverified")
    score = min([
        code_score, *[CAPS[f] for f in flags],
        *([judge_score] if judge_score is not None else []),
    ])
    code_only = min([
        code_score, *[CAPS[f] for f in code_flags - JUDGE_LAYER_FLAGS],
    ])
    result.update({
        "score": round(score, 6), "code_score": round(code_score, 6),
        "code_only_score": round(code_only, 6), "judge_score": judge_score,
        "flags": sorted(flags), "code_flags": sorted(code_flags),
        "pass": score >= PASS_THRESHOLD, "judge_reasons": reasons,
    })
    return result


def grade(sample: Any, item: dict[str, Any]) -> float:
    return float(evaluate(sample, item)["score"])
