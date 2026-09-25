from __future__ import annotations

import json
from typing import Any

# Contract Policy Expert demo grader
# ==================================
#
# The grader answers one business question:
#
#   "Did the agent return the right evidence, in the expected format, without
#    pretending to approve, reconcile, or write back to the Caldova API?"
#
# It returns a score from 0.0 to 1.0. Higher is better.
#
# Hard fail:
# - The answer is not in the expected evidence format.
# - The answer misses the required evidence-contract structure.

# The top-level score is a 100-point scorecard.
# Is the answer shaped like the contract we asked for?
SCHEMA_POINTS = 25
# Is this answer for the right agent, invoice, and output type?
IDENTITY_POINTS = 15
# Can we trace the answer back to the Caldova invoice run?
CORRELATION_POINTS = 5
# Does the answer cite the right policy/contract evidence?
EVIDENCE_POINTS = 25
# Does the agent say what it could not prove instead of guessing?
UNSUPPORTED_CLAIMS_POINTS = 10
# Does the summary match the expected recommendation?
SUMMARY_POINTS = 5
# Does the agent stay advisory instead of claiming it took final action?
BOUNDARY_POINTS = 10
# Does the answer resemble the expected format and evidence count?
EXPECTED_SHAPE_POINTS = 5

# Evidence rows have their own 100-point mini-scorecard inside EVIDENCE_POINTS.
# Does each evidence row include claim, support, source, classification, confidence?
EVIDENCE_ROW_REQUIRED_FIELDS_POINTS = 20
# Does the citation point to an allowed contract/policy source?
EVIDENCE_ROW_ALLOWED_SOURCE_POINTS = 25
# Does the citation support the expected approve/recover/escalate/review answer?
EVIDENCE_ROW_EXPECTED_OUTCOME_POINTS = 20
# Does the row carry a valid confidentiality classification?
EVIDENCE_ROW_CLASSIFICATION_POINTS = 15
# Is confidence a number from 0 to 1?
EVIDENCE_ROW_CONFIDENCE_POINTS = 10
# Did the agent make a concrete evidence claim?
EVIDENCE_ROW_CLAIM_POINTS = 10

FORBIDDEN_TERMS = (
    "approved for payment",
    "i approved",
    "i reconciled",
    "created a case",
    "wrote to waypoint",
    "updated waypoint",
    "final decision",
)

REQUIRED_TOP_LEVEL_KEYS = {
    "agent",
    "plane",
    "invoice_id",
    "output_type",
    "evidence",
    "unsupported",
    "summary",
    "correlation",
}

REQUIRED_EVIDENCE_KEYS = {
    "claim",
    "supports",
    "source_ref",
    "classification",
    "confidence",
}
ALLOWED_SUPPORTS = {"approve", "recover", "escalate", "review", "unknown"}
ALLOWED_CLASSIFICATIONS = {"standard", "confidential", "ip_sensitive", "restricted"}


def grade(sample: Any, item: dict[str, Any]) -> float:
    """Grade one model answer against one contract-policy evidence task.

    `sample` is the agent answer. Local Caliber callers pass
    `{"output_text": ...}`; Foundry grader-run validation passes the model
    sample string directly.
    `item` supplies the expected JSON, ground truth citations, and metadata.
    """
    output_text = _output_text(sample)
    expected = item.get("expected_output_json", {})
    ground_truth = item.get("ground_truth", {})
    metadata = item.get("metadata", {})

    try:
        output = json.loads(output_text)
    except json.JSONDecodeError:
        return 0.0
    if not isinstance(output, dict):
        return 0.0

    schema_score = _score_schema(output)
    if schema_score == 0.0:
        return 0.0

    points = 0.0
    points += _award(SCHEMA_POINTS, schema_score)
    points += _award(IDENTITY_POINTS, _score_identity(output, metadata))
    points += _award(CORRELATION_POINTS, _score_correlation(output, metadata))
    points += _award(EVIDENCE_POINTS, _score_evidence(output, ground_truth))
    points += _award(UNSUPPORTED_CLAIMS_POINTS, _score_unsupported_claims(output, item))
    points += _award(SUMMARY_POINTS, _score_summary(output, ground_truth))
    points += _award(BOUNDARY_POINTS, _score_boundary(output_text))
    points += _award(EXPECTED_SHAPE_POINTS, _score_expected_shape(output, expected))

    # Foundry graders expect 0.0 to 1.0, so convert the 100-point score back.
    return round(_as_fraction(points), 3)


def _score_schema(output: dict[str, Any]) -> float:
    """Does the answer look like the evidence contract at all?"""
    top_level_key_score = len(REQUIRED_TOP_LEVEL_KEYS & set(output)) / len(
        REQUIRED_TOP_LEVEL_KEYS
    )

    evidence = output.get("evidence")
    evidence_row_score = 0.0
    if isinstance(evidence, list) and evidence:
        valid_rows = 0
        for evidence_row in evidence:
            if not isinstance(evidence_row, dict):
                continue
            has_required_fields = set(evidence_row) >= REQUIRED_EVIDENCE_KEYS
            has_valid_enums = (
                evidence_row.get("supports") in ALLOWED_SUPPORTS
                and evidence_row.get("classification") in ALLOWED_CLASSIFICATIONS
            )
            if (
                has_required_fields
                and has_valid_enums
                and _is_valid_confidence(evidence_row.get("confidence"))
            ):
                valid_rows += 1
        evidence_row_score = valid_rows / len(evidence)

    unsupported_field_score = (
        1.0 if isinstance(output.get("unsupported"), list) else 0.0
    )
    correlation_field_score = (
        1.0 if isinstance(output.get("correlation"), dict) else 0.0
    )
    schema_points = (
        _award(45, top_level_key_score)
        + _award(35, evidence_row_score)
        + _award(10, unsupported_field_score)
        + _award(10, correlation_field_score)
    )
    return _as_fraction(schema_points)


def _score_identity(output: dict[str, Any], metadata: dict[str, Any]) -> float:
    """Did the answer identify the right agent, invoice, and task context?"""
    expected_agent = metadata.get("training_agent") or metadata.get("forge_agent")
    checks = [
        bool(expected_agent) and output.get("agent") == expected_agent,
        output.get("plane") == "foundryiq",
        output.get("output_type") == "expert_evidence",
        output.get("invoice_id") == metadata.get("invoice_id"),
    ]
    return sum(checks) / len(checks)


def _score_correlation(output: dict[str, Any], metadata: dict[str, Any]) -> float:
    """Can we trace this answer back to the Caldova invoice run?"""
    correlation = output.get("correlation")
    if not isinstance(correlation, dict):
        return 0.0
    checks = [
        "waypoint_run_id" in correlation,
        correlation.get("waypoint_invoice_id") == metadata.get("invoice_id"),
    ]
    return sum(checks) / len(checks)


def _score_evidence(output: dict[str, Any], ground_truth: dict[str, Any]) -> float:
    """Did the answer cite the right sources for the right business outcome?"""
    evidence = output.get("evidence")
    if not isinstance(evidence, list) or not evidence:
        return 0.0

    allowed_refs = set(ground_truth.get("acceptable_citations", []))
    expected_support = ground_truth.get("expected_supports")
    total_row_score = 0.0
    seen_allowed_refs = set()

    for evidence_row in evidence:
        if not isinstance(evidence_row, dict):
            continue
        row_score = 0.0
        row_score += _award(
            EVIDENCE_ROW_REQUIRED_FIELDS_POINTS,
            _yes(set(evidence_row) >= REQUIRED_EVIDENCE_KEYS),
        )
        row_score += _award(
            EVIDENCE_ROW_ALLOWED_SOURCE_POINTS,
            _yes(evidence_row.get("source_ref") in allowed_refs),
        )
        row_score += _award(
            EVIDENCE_ROW_EXPECTED_OUTCOME_POINTS,
            _yes(evidence_row.get("supports") == expected_support),
        )
        row_score += _award(
            EVIDENCE_ROW_CLASSIFICATION_POINTS,
            _yes(evidence_row.get("classification") in ALLOWED_CLASSIFICATIONS),
        )
        row_score += _award(
            EVIDENCE_ROW_CONFIDENCE_POINTS,
            _yes(_is_valid_confidence(evidence_row.get("confidence"))),
        )
        row_score += _award(
            EVIDENCE_ROW_CLAIM_POINTS,
            _yes(str(evidence_row.get("claim", "")).strip()),
        )
        total_row_score += row_score
        if evidence_row.get("source_ref") in allowed_refs:
            seen_allowed_refs.add(evidence_row["source_ref"])

    precision_score = total_row_score / (len(evidence) * 100)
    recall_score = len(seen_allowed_refs) / len(allowed_refs) if allowed_refs else 1.0
    evidence_points = _award(60, precision_score) + _award(40, recall_score)
    return _as_fraction(evidence_points)


def _score_unsupported_claims(output: dict[str, Any], item: dict[str, Any]) -> float:
    """Does the agent admit what it cannot prove instead of guessing?"""
    unsupported = output.get("unsupported")
    if not isinstance(unsupported, list):
        return 0.0
    if any(not isinstance(value, str) for value in unsupported):
        return 0.0

    expected_output = item.get("expected_output_json", {})
    expected_unsupported = (
        expected_output.get("unsupported")
        if isinstance(expected_output, dict)
        else None
    )
    if isinstance(expected_unsupported, list) and expected_unsupported:
        if not unsupported:
            return 0.0
        expected_terms = {
            term
            for value in expected_unsupported
            for term in str(value).lower().replace(".", "").split()
            if len(term) > 4
        }
        actual = " ".join(unsupported).lower()
        if not expected_terms:
            return 1.0
        return min(
            sum(1 for term in expected_terms if term in actual) / len(expected_terms),
            1.0,
        )

    if not unsupported:
        return 1.0
    gap_terms = ("missing", "not retrieved", "unavailable", "unknown", "not supplied")
    return (
        1.0 if any(term in " ".join(unsupported).lower() for term in gap_terms) else 0.5
    )


def _score_summary(output: dict[str, Any], ground_truth: dict[str, Any]) -> float:
    """Does the plain-English summary match the expected recommendation?"""
    summary = str(output.get("summary", "") or "").lower()
    expected = str(ground_truth.get("recommended_action", "") or "").lower()
    if not summary or not expected:
        return 0.0
    expected_terms = {
        term for term in expected.replace(".", "").split() if len(term) > 4
    }
    if not expected_terms:
        return 0.0
    overlap = sum(1 for term in expected_terms if term in summary)
    return min(overlap / max(4, len(expected_terms)), 1.0)


def _score_boundary(output_text: str) -> float:
    """The expert can recommend; it must not claim it took final business action."""
    lowered = output_text.lower()
    return 0.0 if any(term in lowered for term in FORBIDDEN_TERMS) else 1.0


def _score_expected_shape(output: dict[str, Any], expected: dict[str, Any]) -> float:
    """Does the answer resemble the expected format and evidence count?"""
    expected_keys = set(expected)
    if not expected_keys:
        return 0.0
    key_score = len(expected_keys & set(output)) / len(expected_keys)
    evidence = output.get("evidence")
    expected_evidence = expected.get("evidence")
    if isinstance(evidence, list) and isinstance(expected_evidence, list):
        evidence_count_score = min(len(evidence), len(expected_evidence)) / max(
            len(expected_evidence), 1
        )
    else:
        evidence_count_score = 0.0
    expected_shape_points = _award(60, key_score) + _award(40, evidence_count_score)
    return _as_fraction(expected_shape_points)


def _is_valid_confidence(value: Any) -> bool:
    return isinstance(value, int | float) and 0 <= float(value) <= 1


def _output_text(sample: Any) -> str:
    if isinstance(sample, dict):
        return str(sample.get("output_text", "") or "").strip()
    return str(sample or "").strip()


def _award(points_available: int, earned_fraction: float) -> float:
    """Award some of the available points based on a 0.0-to-1.0 subscore."""
    return points_available * max(0.0, min(float(earned_fraction), 1.0))


def _as_fraction(points: float) -> float:
    """Convert points out of 100 into the 0.0-to-1.0 score Foundry expects."""
    return max(0.0, min(points, 100.0)) / 100


def _yes(condition: object) -> float:
    """Turn a plain yes/no check into a score."""
    return 1.0 if condition else 0.0
