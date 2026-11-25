"""Gold-derived perturbation checks for contract-policy RFT graders.

These fixtures are mechanical edits of committed gold answers. They test grader
robustness (does a known-bad answer fall below the pass threshold?) and are not
model outputs, so they cannot be used to pick a pass threshold on their own.
"""

from __future__ import annotations

import copy
import json
import re
import statistics
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .grading import load_grader
from .schemas import read_jsonl

Perturbation = Callable[[dict[str, Any]], Any]

# expect: "pass" means the variant is still a correct answer and must score
# >= threshold; "fail" means it must score < threshold.
PERTURBATIONS: dict[str, tuple[str, str]] = {
    "gold": ("pass", "Reference answer, which may still be pending human review."),
    "gold_reordered_keys": ("pass", "Reference answer with keys in reverse order."),
    "negated_boundary": ("pass", "Gold plus an explicit 'not approved for payment' disclaimer."),
    "wrong_agent": ("fail", "The response identifies the wrong agent."),
    "wrong_plane": ("fail", "The response identifies the wrong knowledge plane."),
    "wrong_output_type": ("fail", "The response identifies the wrong output type."),
    "wrong_correlation_invoice": ("fail", "The correlation references another invoice."),
    "wrong_run_id": ("fail", "The correlation invents a different run identifier."),
    "missing_run_id": ("fail", "The correlation has no run identifier."),
    "extra_correlation_field": ("fail", "An extra correlation property violates the schema."),
    "wrong_supports": ("fail", "Every evidence row uses the wrong supports label."),
    "one_wrong_support": ("fail", "Only one evidence row uses the wrong supports label."),
    "invalid_support": ("fail", "A non-contract reject label is used."),
    "wrong_invoice": ("fail", "Invoice id and correlation point at another invoice."),
    "drop_required_citation": ("fail", "One required citation row removed."),
    "fabricated_section": ("fail", "A citation points at a section never retrieved."),
    "retrieved_distractor": ("fail", "Adds a retrieved but irrelevant citation."),
    "shotgun_citations": ("fail", "Gold rows plus rows citing unrelated documents."),
    "duplicate_rows": ("fail", "Gold rows repeated to inflate evidence count."),
    "wrong_classification": ("fail", "A cited source is assigned the wrong classification."),
    "extra_evidence_field": ("fail", "An evidence row has an extra field."),
    "missing_claim": ("fail", "An evidence row lacks its required claim."),
    "irrelevant_claim": ("fail", "The claims do not relate to the cited evidence."),
    "contradicted_claim": ("fail", "Negates a reference claim while retaining its keywords."),
    "irrelevant_summary": ("fail", "The summary is unrelated to the requested recommendation."),
    "contradicted_summary": ("fail", "Negates the recommendation while retaining its keywords."),
    "bool_confidence": ("fail", "confidence=true instead of a number."),
    "nonfinite_confidence": ("fail", "A non-JSON NaN confidence is used."),
    "invalid_nested_types": ("fail", "Nested enum and reference fields are arrays."),
    "boundary_violation": ("fail", "Summary claims payment was approved and released."),
    "cross_sentence_negation": ("fail", "A preceding negation does not negate an approval."),
    "not_only_approval": ("fail", "'Not only approved' asserts rather than negates approval."),
    "hedge_when_no_gap": ("fail", "Adds a 'missing' caveat when labels expect none."),
    "missing_expected_gap": ("fail", "Omits a known evidence gap."),
    "all_unsupported": ("fail", "Asserts every fact is unsupported without identifying the gap."),
    "denied_gap": ("fail", "Denies that any known evidence is missing."),
    "affirmed_gap": ("fail", "Claims that the missing evidence was actually supplied."),
    "invented_gap": ("fail", "Adds an unrelated invented evidence gap."),
    "stuffed_summary": ("fail", "Summary repeats the recommendation 30 times."),
    "keyword_stuffing": ("fail", "Repeats recommendation keywords to game summary matching."),
    "extra_decision_key": ("fail", "Adds a top-level decision key outside the contract."),
    "missing_top_level_key": ("fail", "A required top-level key is missing."),
    "empty_evidence": ("fail", "Evidence array is empty."),
    "markdown_fenced": ("fail", "Gold JSON wrapped in a markdown code fence."),
    "duplicate_json_key": ("fail", "The response has duplicate JSON object keys."),
    "prose": ("fail", "Non-JSON prose answer."),
    "empty": ("fail", "Empty output."),
    "json_array": ("fail", "A JSON array instead of an object."),
    "directive_summary": ("fail", "v3 only: the summary is the historical finance directive."),
    "directive_claim": ("fail", "v3 only: an evidence claim instructs a finance action."),
    "should_directive": ("fail", "v3 only: the summary says the controller should pay."),
}


_AFFIRMATIONS = (
    (re.compile(r"\bare not visible\b"), "are visible"),
    (re.compile(r"\bis not visible\b"), "is visible"),
    (re.compile(r"\bis not shown\b"), "is shown"),
    (re.compile(r"\bwere not supplied\b"), "were supplied"),
    (re.compile(r"\bwas not supplied\b"), "was supplied"),
    (re.compile(r"\bnot supplied\b"), "supplied"),
    (re.compile(r"\bwas not provided\b"), "was provided"),
    (re.compile(r"\bnot provided\b"), "provided"),
    (re.compile(r"^No (.+?) (was|were) supplied"), r"The \1 \2 supplied"),
    (re.compile(r"^No (.+?) is visible"), r"The \1 is visible"),
)


def _affirm_gap(gap: str) -> str:
    """Turn a stated evidence gap into a claim that the evidence was present."""
    for pattern, replacement in _AFFIRMATIONS:
        gap = pattern.sub(replacement, gap)
    return gap


def _other_support(expected: str | None) -> str:
    return "approve" if expected != "approve" else "recover"


def build_perturbations(row: dict[str, Any]) -> dict[str, str]:
    """Return {name: output_text} for one gold row."""
    gold = row.get("expected_output_json")
    if not isinstance(gold, dict) or not isinstance(gold.get("evidence"), list):
        raise ValueError(f"row {row.get('id')} has no expected_output_json evidence")
    expected_support = row.get("ground_truth", {}).get("expected_supports")

    def edit(fn: Callable[[dict[str, Any]], None]) -> str:
        variant = copy.deepcopy(gold)
        fn(variant)
        return json.dumps(variant)

    def wrong_supports(v: dict[str, Any]) -> None:
        for e in v["evidence"]:
            e["supports"] = _other_support(expected_support)

    def wrong_invoice(v: dict[str, Any]) -> None:
        v["invoice_id"] = "INV-PERTURBED-0000"
        if isinstance(v.get("correlation"), dict):
            v["correlation"]["waypoint_invoice_id"] = "INV-PERTURBED-0000"

    def wrong_correlation(v: dict[str, Any]) -> None:
        v["correlation"]["waypoint_invoice_id"] = "INV-PERTURBED-0000"

    def fabricated(v: dict[str, Any]) -> None:
        ref = str(v["evidence"][0]["source_ref"]).split("#", 1)[0]
        v["evidence"][0]["source_ref"] = ref + "#99-perturbed-section"

    def shotgun(v: dict[str, Any]) -> None:
        template = copy.deepcopy(v["evidence"][0])
        for n in range(4):
            extra = dict(template)
            extra["source_ref"] = f"data/policies/source-markdown/unrelated-{n}.md#1-scope"
            v["evidence"].append(extra)

    context = row.get("retrieved_context")
    sections = context.get("contract_policy_sections", []) if isinstance(context, dict) else context
    acceptable = set(row.get("ground_truth", {}).get("acceptable_citations", []))
    distractors = [
        section for section in (sections if isinstance(sections, list) else [])
        if isinstance(section, dict)
        and isinstance(section.get("source_ref"), str)
        and section["source_ref"] not in acceptable
    ]
    classified = {
        section["source_ref"]: section["classification"]
        for section in (sections if isinstance(sections, list) else [])
        if isinstance(section, dict)
        and isinstance(section.get("source_ref"), str)
        and section.get("classification") in {
            "standard", "confidential", "restricted", "ip_sensitive"
        }
    }

    def add_distractor(v: dict[str, Any]) -> None:
        evidence = copy.deepcopy(v["evidence"][0])
        evidence["source_ref"] = distractors[0]["source_ref"]
        evidence["classification"] = distractors[0].get("classification", "standard")
        v["evidence"].append(evidence)

    variants = {
        "gold": json.dumps(gold),
        "gold_reordered_keys": json.dumps(dict(reversed(list(gold.items())))),
        "negated_boundary": edit(
            lambda v: v.__setitem__("summary", f"{v['summary']} This is not approved for payment.")
        ),
        "wrong_agent": edit(lambda v: v.__setitem__("agent", "different-agent")),
        "wrong_plane": edit(lambda v: v.__setitem__("plane", "different-plane")),
        "wrong_output_type": edit(lambda v: v.__setitem__("output_type", "decision")),
        "wrong_correlation_invoice": edit(wrong_correlation),
        "wrong_run_id": edit(
            lambda v: v["correlation"].__setitem__("waypoint_run_id", "invented-run")
        ),
        "missing_run_id": edit(lambda v: v["correlation"].pop("waypoint_run_id")),
        "extra_correlation_field": edit(lambda v: v["correlation"].__setitem__("extra", "x")),
        "wrong_supports": edit(wrong_supports),
        "one_wrong_support": edit(
            lambda v: v["evidence"][0].__setitem__("supports", _other_support(expected_support))
        ),
        "invalid_support": edit(lambda v: v["evidence"][0].__setitem__("supports", "reject")),
        "wrong_invoice": edit(wrong_invoice),
        "drop_required_citation": edit(lambda v: v.__setitem__("evidence", v["evidence"][:-1])),
        "fabricated_section": edit(fabricated),
        "retrieved_distractor": edit(add_distractor) if distractors else "",
        "shotgun_citations": edit(shotgun),
        "duplicate_rows": edit(
            lambda v: v.__setitem__("evidence", v["evidence"] + v["evidence"][:1] * 4)
        ),
        "wrong_classification": edit(
            lambda v: v["evidence"][0].__setitem__(
                "classification",
                "standard" if v["evidence"][0]["classification"] != "standard" else "confidential",
            )
        ),
        "extra_evidence_field": edit(lambda v: v["evidence"][0].__setitem__("decision", "approve")),
        "missing_claim": edit(lambda v: v["evidence"][0].pop("claim")),
        "irrelevant_claim": edit(
            lambda v: [
                e.__setitem__("claim", "The moon has purple bicycles.") for e in v["evidence"]
            ]
        ),
        "contradicted_claim": edit(
            lambda v: [
                e.__setitem__("claim", f"It is false that {e['claim']}") for e in v["evidence"]
            ]
        ),
        "irrelevant_summary": edit(
            lambda v: v.__setitem__("summary", "The moon has purple bicycles.")
        ),
        "contradicted_summary": edit(
            lambda v: v.__setitem__("summary", f"Do not {v['summary']}")
        ),
        "bool_confidence": edit(
            lambda v: [e.__setitem__("confidence", True) for e in v["evidence"]]
        ),
        "nonfinite_confidence": edit(
            lambda v: v["evidence"][0].__setitem__("confidence", float("nan"))
        ),
        "invalid_nested_types": edit(
            lambda v: v["evidence"][0].update({"source_ref": [], "supports": []})
        ),
        "boundary_violation": edit(
            lambda v: v.__setitem__("summary", "Invoice approved; payment released.")
        ),
        "cross_sentence_negation": edit(
            lambda v: v.__setitem__("summary", "The document was not reviewed. Invoice approved.")
        ),
        "not_only_approval": edit(
            lambda v: v.__setitem__("summary", "Not only approved for payment, but processed.")
        ),
        "hedge_when_no_gap": edit(
            lambda v: v.__setitem__("unsupported", ["Missing supplier confirmation."])
        ),
        "missing_expected_gap": edit(lambda v: v.__setitem__("unsupported", [])),
        "all_unsupported": edit(
            lambda v: v.__setitem__("unsupported", ["Everything is unsupported."])
        ),
        "denied_gap": edit(
            lambda v: v.__setitem__(
                "unsupported", ["No evidence is missing; all documents were supplied."]
            )
        ),
        "affirmed_gap": edit(
            lambda v: v.__setitem__("unsupported", [_affirm_gap(gap) for gap in v["unsupported"]])
        ),
        "invented_gap": edit(
            lambda v: v["unsupported"].append("The supplier's bank account is compromised.")
        ),
        "stuffed_summary": edit(lambda v: v.__setitem__("summary", f"{v['summary']} " * 30)),
        "keyword_stuffing": edit(lambda v: v.__setitem__("summary", f"{v['summary']} " * 4)),
        "extra_decision_key": edit(lambda v: v.__setitem__("decision", "approve")),
        "missing_top_level_key": edit(lambda v: v.pop("unsupported")),
        "empty_evidence": edit(lambda v: v.__setitem__("evidence", [])),
        "markdown_fenced": "```json\n" + json.dumps(gold) + "\n```",
        "duplicate_json_key": json.dumps(gold)[:-1] + ', "invoice_id": "OTHER"}',
        "prose": "The contract supports recovery of the surcharge.",
        "empty": "",
        "json_array": "[]",
    }
    # Only keep perturbations that actually differ from gold for this row.
    if len(gold["evidence"]) < 2:
        variants.pop("drop_required_citation")
    if not distractors:
        variants.pop("retrieved_distractor")
    if gold["evidence"][0].get("source_ref") not in classified:
        variants.pop("wrong_classification")
    if gold.get("unsupported"):
        variants.pop("hedge_when_no_gap")
    else:
        variants.pop("missing_expected_gap")
        variants.pop("denied_gap")
        variants.pop("affirmed_gap")
        variants.pop("invented_gap")
    if variants.get("affirmed_gap") == json.dumps(gold):
        variants.pop("affirmed_gap")
    # Directive perturbations only apply to evidence-only (v3) references; the
    # historical labels are themselves directives.
    metadata = row.get("metadata", {})
    if isinstance(metadata, dict) and isinstance(
        metadata.get("evidence_only_reference"), dict
    ):
        historical = metadata.get("historical_reference", {})
        action = historical.get("recommended_action") if isinstance(historical, dict) else None
        directive = action or "Withhold the disputed amount until the supplier responds."
        variants["directive_summary"] = edit(lambda v: v.__setitem__("summary", directive))
        variants["directive_claim"] = edit(
            lambda v: v["evidence"][0].__setitem__(
                "claim", f"{v['evidence'][0]['claim']} Dispute the line with the supplier."
            )
        )
        variants["should_directive"] = edit(
            lambda v: v.__setitem__(
                "summary", f"{v['summary']} The controller should pay the full amount."
            )
        )
    return variants


def run_grader_robustness(
    *,
    dataset_paths: list[Path],
    grader_path: Path,
    pass_threshold: float,
    out: Path | None = None,
) -> dict[str, Any]:
    if not 0.0 < pass_threshold <= 1.0:
        raise ValueError(f"pass_threshold must be in (0, 1]: {pass_threshold}")
    grader = load_grader(grader_path)
    scores: dict[str, list[float]] = {}
    violations: list[dict[str, Any]] = []
    row_count = 0
    for path in dataset_paths:
        for row in read_jsonl(path):
            row_count += 1
            for name, text in build_perturbations(row).items():
                score = float(grader({"output_text": text}, row))
                if not 0.0 <= score <= 1.0:
                    raise ValueError(f"grader returned out-of-range score {score} for {name}")
                scores.setdefault(name, []).append(score)
                expect = PERTURBATIONS[name][0]
                passed = score >= pass_threshold
                if (expect == "pass") != passed:
                    violations.append(
                        {"row_id": row.get("id"), "perturbation": name, "score": score}
                    )

    summary = {
        name: {
            "expect": PERTURBATIONS[name][0],
            "description": PERTURBATIONS[name][1],
            "n": len(values),
            "mean": round(statistics.fmean(values), 4),
            "min": round(min(values), 4),
            "max": round(max(values), 4),
            "pass_rate_at_threshold": round(
                sum(v >= pass_threshold for v in values) / len(values), 4
            ),
        }
        for name, values in scores.items()
    }
    result = {
        "grader": str(grader_path),
        "datasets": [str(p) for p in dataset_paths],
        "rows": row_count,
        "pass_threshold": pass_threshold,
        "ready": not violations,
        "violation_count": len(violations),
        "violations": violations[:50],
        "perturbations": summary,
        "evidence_kind": "gold_derived_perturbations_not_model_outputs",
        "note": (
            "Robustness evidence only. Threshold selection still needs scored base/teacher "
            "model outputs, and trainer-side grader parity needs remote grader validation."
        ),
    }
    if out is not None:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
        result["path"] = str(out)
    return result
