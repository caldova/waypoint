from __future__ import annotations

import json
import re
from typing import Any

# Contract Policy Expert grader, v2 (MAI-2 RFT candidate)
# ======================================================
#
# v2 keeps v1's 100-point scorecard and gold-answer parity, and closes
# reward-gaming paths that an RL policy can find:
#   - bool confidence (True is an int in Python) no longer counts as valid
#   - extra top-level keys reduce the schema score
#   - duplicate evidence rows no longer inflate precision or evidence count
#   - fabricated sections of an allowed document get no source credit when the
#     item carries retrieved_context
#   - keyword-stuffed summaries/unsupported lists are length-capped
#   - "missing ..." hedges when no gap is expected no longer earn full credit
#   - boundary terms are broader and negation-aware ("not approved for payment")
#   - oversized outputs are capped
# v1 (contract_policy_evidence_grader.py) stays unchanged so historical
# MAI-1.1 RFT rewards remain reproducible.
GRADER_VERSION = "contract-policy-evidence-v3"
#
# The grader answers one business question:
#
#   "Did the agent return the right evidence, in the expected format, without
#    pretending to approve, reconcile, or write back to the Caldova API?"
#
# It returns a score from 0.0 to 1.0. Higher is better.
#
# The score is intentionally dense enough for RFT: wrong-but-near answers should
# usually earn partial credit instead of collapsing every rollout to zero.

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
    "payment approved",
    "invoice approved",
    "approved the invoice",
    "approved this invoice",
    "released payment",
    "payment released",
    "marked as paid",
    "reconciled the invoice",
    "invoice reconciled",
    "opened a case",
    "case created",
    "posted to waypoint",
    "submitted to waypoint",
    "write-back complete",
    "written back to waypoint",
)
NEGATION_PATTERN = (
    r"\b(not|no|never|cannot|can't|don't|do not|does not|won't|without|must not|"
    r"should not|unable to)\b(?:\W+\w+){0,5}\W*$"
)
# v3: the expert describes evidence; imperative finance dispositions are a
# boundary violation even when no action is claimed as taken.
DIRECTIVE_VERBS = (
    r"(?:pay|approve|dispute|reject|deny|hold|withhold|short-pay|reconcile|recover|"
    r"escalate|request|release\s+payment|recalculate|reprice|re-price|rebill|credit|"
    r"refund|deduct|offset|present|route)"
)
DIRECTIVE_PATTERN = (
    r"(?:^\s*|[.!?;:]\s*|\b(?:and|or|then|please)\s+)" + DIRECTIVE_VERBS + r"\b"
    r"|\b(?:should|must|recommend(?:s|ed)?(?:\s+to)?|we\s+will|i\s+will|you\s+should)\s+"
    + DIRECTIVE_VERBS + r"\b"
)
MAX_OUTPUT_CHARS = 20000
MAX_SUMMARY_WORDS = 80
MAX_UNSUPPORTED_ITEMS = 8
OVERSIZE_SCORE_CAP = 0.4
HEDGE_WHEN_NO_GAP_SCORE = 0.25
# Severe known-bad cases remain below 0.5 while retaining differentiated reward.
BOUNDARY_VIOLATION_CAP = 0.2
WRONG_IDENTITY_CAP = 0.35
WRONG_SUPPORT_CAP = 0.4
FABRICATED_CITATION_CAP = 0.35
MISSING_CITATION_CAP = 0.45
DUPLICATE_ROW_CAP = 0.45
INVALID_CONFIDENCE_CAP = 0.45
CONTRACT_VIOLATION_CAP = 0.45
UNSUPPORTED_CITATION_CAP = 0.4
MISSING_GAP_CAP = 0.4
IRRELEVANT_CLAIM_CAP = 0.45
INVALID_CONTRACT_SCORE = 0.1

COMMON_TERMS = {
    "about", "after", "because", "before", "being", "contract", "evidence",
    "identifying", "invoice", "items", "policy", "request", "review", "should",
    "sponsor", "supplier", "their", "there", "these", "this", "those", "using",
    "which", "with", "would",
}

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
    sample string directly. Foundry RFT with response_format may pass
    structured generations as `{"output_json": ...}`.
    `item` supplies the expected JSON, ground truth citations, and metadata.
    """
    output_text = _output_text(sample)
    expected = item.get("expected_output_json", {})
    ground_truth = item.get("ground_truth", {})
    metadata = item.get("metadata", {})

    try:
        output = json.loads(
            output_text,
            object_pairs_hook=_unique_object,
            parse_constant=_invalid_json_constant,
        )
    except ValueError:
        return 0.02 if output_text else 0.0
    if not isinstance(output, dict):
        return 0.0
    if not _valid_contract_shape(output):
        return INVALID_CONTRACT_SCORE

    schema_score = _score_schema(output)

    points = 0.0
    points += _award(SCHEMA_POINTS, schema_score)
    points += _award(IDENTITY_POINTS, _score_identity(output, metadata))
    points += _award(CORRELATION_POINTS, _score_correlation(output, metadata, expected))
    points += _award(
        EVIDENCE_POINTS,
        _score_evidence(output, ground_truth, _retrieved_refs(item)),
    )
    points += _award(UNSUPPORTED_CLAIMS_POINTS, _score_unsupported_claims(output, item))
    points += _award(SUMMARY_POINTS, _score_summary(output, ground_truth))
    points += _award(BOUNDARY_POINTS, _score_boundary(output_text))
    points += _award(EXPECTED_SHAPE_POINTS, _score_expected_shape(output, expected))

    # Foundry graders expect 0.0 to 1.0, so convert the 100-point score back.
    score = min(_as_fraction(points), *_critical_caps(output, output_text, item))
    if len(output_text) > MAX_OUTPUT_CHARS:
        score = min(score, OVERSIZE_SCORE_CAP)
    return round(score, 3)


def _critical_caps(output: dict[str, Any], output_text: str, item: dict[str, Any]) -> list[float]:
    """Business-critical errors cap the reward below any sensible pass threshold.

    The 100-point scorecard is dense, so in v1 a well-formatted answer with the
    wrong decision label or invoice still scored ~0.94-0.97. Caps keep partial
    credit (gradient) while making the pass threshold mean "correct".
    """
    caps = [1.0]
    metadata = item.get("metadata", {})
    ground_truth = item.get("ground_truth", {})
    evidence = output.get("evidence")
    rows = [row for row in evidence if isinstance(row, dict)] if isinstance(evidence, list) else []

    if _score_boundary(output_text) < 1.0 or _has_directive(output):
        caps.append(BOUNDARY_VIOLATION_CAP)
    if _score_identity(output, metadata) < 1.0 or _score_correlation(
        output, metadata, item.get("expected_output_json")
    ) < 1.0:
        caps.append(WRONG_IDENTITY_CAP)
    expected_support = ground_truth.get("expected_supports")
    if expected_support and (
        not rows or any(row.get("supports") != expected_support for row in rows)
    ):
        caps.append(WRONG_SUPPORT_CAP)
    retrieved = _retrieved_refs(item)
    allowed = set(ground_truth.get("acceptable_citations", []))
    cited = {row.get("source_ref") for row in rows}
    if retrieved is not None and any(ref not in retrieved | allowed for ref in cited):
        caps.append(FABRICATED_CITATION_CAP)
    if allowed and any(ref not in allowed for ref in cited):
        caps.append(UNSUPPORTED_CITATION_CAP)
    if allowed and not allowed <= cited:
        caps.append(MISSING_CITATION_CAP)
    if len({_evidence_row_key(row) for row in rows}) < len(rows):
        caps.append(DUPLICATE_ROW_CAP)
    if any(
        isinstance(row.get("confidence"), bool) or not _is_valid_confidence(row.get("confidence"))
        for row in rows
    ):
        caps.append(INVALID_CONFIDENCE_CAP)
    if _contract_violation(output, item):
        caps.append(CONTRACT_VIOLATION_CAP)
    expected_output = item.get("expected_output_json", {})
    expected_unsupported = expected_output.get("unsupported", [])
    if expected_unsupported and (
        _score_unsupported_claims(output, item) < 0.6
        or len(output["unsupported"]) > len(expected_unsupported)
        or _denies_missing_evidence(output["unsupported"])
        or _affirms_available_evidence(output["unsupported"])
        or not _identifies_missing_evidence(output["unsupported"])
    ):
        caps.append(MISSING_GAP_CAP)
    if (
        _has_irrelevant_claim(output, item)
        or _score_summary(output, ground_truth) == 0
        or _contradicts_reference(output, item)
    ):
        caps.append(IRRELEVANT_CLAIM_CAP)
    classifications = _retrieved_classifications(item)
    if any(
        row["source_ref"] in classifications
        and row["classification"] != classifications[row["source_ref"]]
        for row in rows
    ):
        caps.append(CONTRACT_VIOLATION_CAP)
    return caps


def _contract_violation(output: dict[str, Any], item: dict[str, Any]) -> bool:
    """Shape games that the dense scorecard only lightly penalizes."""
    if set(output) - REQUIRED_TOP_LEVEL_KEYS:
        return True
    if len(str(output.get("summary", "") or "").split()) > MAX_SUMMARY_WORDS:
        return True
    if _repeats_terms(output["summary"]) or any(
        _repeats_terms(row["claim"]) for row in output["evidence"]
    ):
        return True
    unsupported = output.get("unsupported")
    expected_output = item.get("expected_output_json", {})
    expected_unsupported = (
        expected_output.get("unsupported") if isinstance(expected_output, dict) else None
    )
    if isinstance(unsupported, list):
        if len(unsupported) > MAX_UNSUPPORTED_ITEMS:
            return True
        if isinstance(expected_unsupported, list) and not expected_unsupported and unsupported:
            return True
    return False


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _invalid_json_constant(value: str) -> None:
    raise ValueError(f"invalid JSON constant: {value}")


def _valid_contract_shape(output: dict[str, Any]) -> bool:
    if set(output) != REQUIRED_TOP_LEVEL_KEYS:
        return False
    if any(
        not isinstance(output[key], str) or not output[key].strip()
        for key in ("agent", "plane", "invoice_id", "output_type", "summary")
    ):
        return False
    evidence = output["evidence"]
    if not isinstance(evidence, list) or not evidence:
        return False
    for row in evidence:
        if not isinstance(row, dict) or set(row) != REQUIRED_EVIDENCE_KEYS:
            return False
        if any(
            not isinstance(row[key], str) or not row[key].strip()
            for key in ("claim", "supports", "source_ref", "classification")
        ):
            return False
        if row["supports"] not in ALLOWED_SUPPORTS:
            return False
        if row["classification"] not in ALLOWED_CLASSIFICATIONS:
            return False
        if not _is_valid_confidence(row["confidence"]):
            return False
    unsupported = output["unsupported"]
    if not isinstance(unsupported, list) or any(
        not isinstance(value, str) or not value.strip() for value in unsupported
    ):
        return False
    correlation = output["correlation"]
    return (
        isinstance(correlation, dict)
        and set(correlation) == {"waypoint_run_id", "waypoint_invoice_id"}
        and all(isinstance(value, str) and value.strip() for value in correlation.values())
    )


def _terms(text: str) -> set[str]:
    return {
        term for term in re.findall(r"[a-z0-9]+", text.lower())
        if len(term) > 3 and term not in COMMON_TERMS
    }


def _repeats_terms(text: str) -> bool:
    terms = [
        term for term in re.findall(r"[a-z0-9]+", text.lower())
        if len(term) > 3 and term not in COMMON_TERMS
    ]
    return any(terms.count(term) > 3 for term in set(terms))


def _denies_missing_evidence(gaps: list[str]) -> bool:
    return any(
        re.search(
            r"\b(?:not missing|nothing (?:is )?missing|no (?:evidence |documents? |"
            r"information |gaps? (?:are )?)?missing|no gaps?|fully supported|"
            r"all (?:the )?(?:evidence|documents?|approvals?) (?:were |are |was |is )?"
            r"(?:provided|supplied|available))\b",
            gap.lower(),
        )
        for gap in gaps
    )


AVAILABILITY_PATTERN = (
    r"\b(?:is|are|was|were)\s+(?:visible|shown|supplied|provided|available|attached)\b"
)
CLAUSE_NEGATION_PATTERN = r"\b(?:no|not|never|without|neither|nor)\b"


def _affirms_available_evidence(gaps: list[str]) -> bool:
    """A gap entry asserts the missing evidence is actually present."""
    for gap in gaps:
        text = gap.lower()
        for match in re.finditer(AVAILABILITY_PATTERN, text):
            clause = re.split(r"[,;.]|\bso\b", text[: match.start()])[-1]
            if not re.search(CLAUSE_NEGATION_PATTERN, clause):
                return True
    return False


def _identifies_missing_evidence(gaps: list[str]) -> bool:
    return bool(gaps) and all(
        re.search(
            r"\b(?:missing|unknown|unavailable|absent|unverified|unconfirmed|outstanding|"
            r"unclear|incomplete|no|lack(?:s|ing)?|not)\b",
            gap.lower(),
        )
        for gap in gaps
    )


def _has_directive(output: dict[str, Any]) -> bool:
    texts = [output.get("summary")]
    texts.extend(row.get("claim") for row in output.get("evidence", []) if isinstance(row, dict))
    unsupported = output.get("unsupported")
    if isinstance(unsupported, list):
        texts.extend(unsupported)
    return any(
        isinstance(text, str) and re.search(DIRECTIVE_PATTERN, text, re.IGNORECASE)
        for text in texts
    )


def _reference_summary(ground_truth: dict[str, Any]) -> str:
    return str(
        ground_truth.get("reference_summary") or ground_truth.get("recommended_action") or ""
    ).lower()


def _contradicts_reference(output: dict[str, Any], item: dict[str, Any]) -> bool:
    if any(re.search(r"\b(?:it is false that|not true that)\b", row["claim"].lower())
           for row in output["evidence"]):
        return True
    expected = _reference_summary(item.get("ground_truth", {}))
    actual = output["summary"].lower().strip()
    return (
        actual.startswith(("do not ", "don't ", "never "))
        and not expected.startswith(("do not ", "don't ", "never "))
    )


def _has_irrelevant_claim(output: dict[str, Any], item: dict[str, Any]) -> bool:
    expected = item.get("expected_output_json", {})
    reference = {
        row.get("source_ref"): row.get("claim", "")
        for row in expected.get("evidence", [])
        if isinstance(row, dict) and isinstance(row.get("source_ref"), str)
    }
    context = item.get("retrieved_context", {})
    sections = (
        context.get("contract_policy_sections", [])
        if isinstance(context, dict) else context
    )
    if isinstance(sections, list):
        for section in sections:
            if isinstance(section, dict) and isinstance(section.get("source_ref"), str):
                ref = section["source_ref"]
                reference[ref] = f"{reference.get(ref, '')} {section.get('text', '')}"
    return any(
        reference.get(row["source_ref"])
        and not (_terms(row["claim"]) & _terms(str(reference[row["source_ref"]])))
        for row in output["evidence"]
    )


def _retrieved_classifications(item: dict[str, Any]) -> dict[str, str]:
    context = item.get("retrieved_context", {})
    sections = context.get("contract_policy_sections", []) if isinstance(context, dict) else context
    if not isinstance(sections, list):
        return {}
    return {
        row["source_ref"]: row["classification"]
        for row in sections
        if isinstance(row, dict)
        and isinstance(row.get("source_ref"), str)
        and isinstance(row.get("classification"), str)
        and row["classification"] in ALLOWED_CLASSIFICATIONS
    }


def _score_schema(output: dict[str, Any]) -> float:
    """Does the answer look like the evidence contract at all?"""
    top_level_key_score = len(REQUIRED_TOP_LEVEL_KEYS & set(output)) / len(
        REQUIRED_TOP_LEVEL_KEYS | set(output)
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

    unsupported_field_score = 1.0 if isinstance(output.get("unsupported"), list) else 0.0
    correlation_field_score = 1.0 if isinstance(output.get("correlation"), dict) else 0.0
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


def _score_correlation(
    output: dict[str, Any], metadata: dict[str, Any], expected: Any = None
) -> float:
    """Can we trace this answer back to the Caldova invoice run?"""
    correlation = output.get("correlation")
    if not isinstance(correlation, dict):
        return 0.0
    expected_correlation = expected.get("correlation", {}) if isinstance(expected, dict) else {}
    expected_run = (
        expected_correlation.get("waypoint_run_id")
        if isinstance(expected_correlation, dict) else None
    )
    run_id = correlation.get("waypoint_run_id")
    checks = [
        isinstance(run_id, str)
        and bool(run_id.strip())
        and (not expected_run or run_id == expected_run),
        correlation.get("waypoint_invoice_id") == metadata.get("invoice_id"),
    ]
    return sum(checks) / len(checks)


def _score_evidence(
    output: dict[str, Any],
    ground_truth: dict[str, Any],
    retrieved_refs: set[str] | None = None,
) -> float:
    """Did the answer cite the right sources for the right business outcome?"""
    evidence = output.get("evidence")
    if not isinstance(evidence, list) or not evidence:
        return 0.0

    allowed_refs = set(ground_truth.get("acceptable_citations", []))
    expected_support = ground_truth.get("expected_supports")
    total_row_score = 0.0
    seen_allowed_refs = set()
    seen_row_keys: set[str] = set()

    for evidence_row in evidence:
        if not isinstance(evidence_row, dict):
            continue
        row_key = _evidence_row_key(evidence_row)
        if row_key in seen_row_keys:
            # Repeating a correct row must not raise precision.
            continue
        seen_row_keys.add(row_key)
        row_score = 0.0
        row_score += _award(
            EVIDENCE_ROW_REQUIRED_FIELDS_POINTS,
            _yes(set(evidence_row) >= REQUIRED_EVIDENCE_KEYS),
        )
        row_score += _award(
            EVIDENCE_ROW_ALLOWED_SOURCE_POINTS,
            _score_source_ref(evidence_row.get("source_ref"), allowed_refs, retrieved_refs),
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


def _evidence_row_key(evidence_row: dict[str, Any]) -> str:
    return json.dumps(
        [
            str(evidence_row.get("source_ref", "")).strip(),
            str(evidence_row.get("supports", "")).strip(),
        ]
    )


def _retrieved_refs(item: dict[str, Any]) -> set[str] | None:
    """Return source_refs actually supplied to the model, if the item carries them."""
    context = item.get("retrieved_context")
    sections: Any = None
    if isinstance(context, dict):
        sections = context.get("contract_policy_sections")
    elif isinstance(context, list):
        sections = context
    if not isinstance(sections, list):
        return None
    refs = {
        section["source_ref"]
        for section in sections
        if isinstance(section, dict) and isinstance(section.get("source_ref"), str)
    }
    return refs or None


def _score_source_ref(
    source_ref: Any,
    allowed_refs: set[str],
    retrieved_refs: set[str] | None = None,
) -> float:
    """Reward exact citations most, but preserve signal for near citations."""
    if not isinstance(source_ref, str) or not source_ref.strip():
        return 0.0
    if source_ref in allowed_refs:
        return 1.0
    if retrieved_refs is not None and source_ref not in retrieved_refs:
        # A section the model was never shown is fabricated, even if its
        # document prefix looks plausible.
        return 0.0

    source_doc = source_ref.split("#", 1)[0]
    allowed_docs = {allowed.split("#", 1)[0] for allowed in allowed_refs}
    if source_doc in allowed_docs:
        return 0.65

    source_family = _source_family(source_doc)
    allowed_families = {_source_family(allowed_doc) for allowed_doc in allowed_docs}
    if source_family and source_family in allowed_families:
        return 0.35
    return 0.0


def _source_family(path: str) -> str:
    normalized = path.replace("\\", "/")
    if "/contracts/" in normalized:
        return "contracts"
    if "/policies/" in normalized:
        return "policies"
    return ""


def _score_unsupported_claims(output: dict[str, Any], item: dict[str, Any]) -> float:
    """Does the agent admit what it cannot prove instead of guessing?"""
    unsupported = output.get("unsupported")
    if not isinstance(unsupported, list):
        return 0.0
    if any(not isinstance(value, str) for value in unsupported):
        return 0.0
    if len(unsupported) > MAX_UNSUPPORTED_ITEMS:
        return 0.0

    expected_output = item.get("expected_output_json", {})
    expected_unsupported = (
        expected_output.get("unsupported") if isinstance(expected_output, dict) else None
    )
    if isinstance(expected_unsupported, list) and expected_unsupported:
        if not unsupported:
            return 0.0
        actual_terms = _terms(" ".join(unsupported))
        scores = []
        for expected_gap in expected_unsupported:
            expected_terms = _terms(str(expected_gap))
            scores.append(
                len(expected_terms & actual_terms) / len(expected_terms) if expected_terms else 0.0
            )
        return min(scores)

    if not unsupported:
        return 1.0
    if isinstance(expected_unsupported, list):
        # Labels say nothing is missing; reflexive "missing ..." hedges are noise.
        return HEDGE_WHEN_NO_GAP_SCORE
    gap_terms = ("missing", "not retrieved", "unavailable", "unknown", "not supplied")
    return 1.0 if any(term in " ".join(unsupported).lower() for term in gap_terms) else 0.5


def _score_summary(output: dict[str, Any], ground_truth: dict[str, Any]) -> float:
    """Does the plain-English summary match the expected recommendation?"""
    summary = str(output.get("summary", "") or "").lower()
    expected = _reference_summary(ground_truth)
    if not summary or not expected:
        return 0.0
    if len(summary.split()) > MAX_SUMMARY_WORDS:
        return 0.0
    expected_terms = {term for term in expected.replace(".", "").split() if len(term) > 4}
    if not expected_terms:
        return 0.0
    overlap = sum(1 for term in expected_terms if term in summary)
    return min(overlap / max(4, len(expected_terms)), 1.0)


def _score_boundary(output_text: str) -> float:
    """The expert can recommend; it must not claim it took final business action."""
    lowered = output_text.lower()
    for term in FORBIDDEN_TERMS:
        start = lowered.find(term)
        while start != -1:
            prefix = lowered[max(0, start - 80) : start]
            prefix = re.split(r"[.;?!]", prefix)[-1]
            if not re.search(NEGATION_PATTERN, prefix) or re.search(
                r"\bnot\s+only\b", prefix
            ):
                return 0.0
            start = lowered.find(term, start + 1)
    return 1.0


def _score_expected_shape(output: dict[str, Any], expected: dict[str, Any]) -> float:
    """Does the answer resemble the expected format and evidence count?"""
    expected_keys = set(expected)
    if not expected_keys:
        return 0.0
    key_score = len(expected_keys & set(output)) / len(expected_keys)
    evidence = output.get("evidence")
    expected_evidence = expected.get("evidence")
    if isinstance(evidence, list) and isinstance(expected_evidence, list):
        unique_rows = {_evidence_row_key(row) for row in evidence if isinstance(row, dict)}
        evidence_count_score = min(len(unique_rows), len(expected_evidence)) / max(
            len(expected_evidence), 1
        )
    else:
        evidence_count_score = 0.0
    expected_shape_points = _award(60, key_score) + _award(40, evidence_count_score)
    return _as_fraction(expected_shape_points)


def _is_valid_confidence(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool) and 0 <= float(value) <= 1


def _output_text(sample: Any) -> str:
    if isinstance(sample, dict):
        output_json = sample.get("output_json")
        if output_json is not None:
            if isinstance(output_json, str):
                return output_json.strip()
            return json.dumps(output_json, sort_keys=True)
        output_text = sample.get("output_text")
        if output_text is not None:
            return str(output_text or "").strip()
        output = sample.get("output")
        if isinstance(output, str):
            return output.strip()
        if isinstance(output, dict):
            if "text" in output:
                return str(output.get("text") or "").strip()
            if "content" in output:
                return _content_text(output.get("content"))
        response = sample.get("response")
        if isinstance(response, str):
            return response.strip()
        choices = sample.get("choices")
        if isinstance(choices, list) and choices:
            first = choices[0]
            if isinstance(first, dict):
                message = first.get("message")
                if isinstance(message, dict):
                    return _content_text(message.get("content"))
                if "text" in first:
                    return str(first.get("text") or "").strip()
    return str(sample or "").strip()


def _content_text(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                value = item.get("text") or item.get("content")
                if value is not None:
                    parts.append(str(value))
        return "\n".join(parts).strip()
    return str(content or "").strip()


def _award(points_available: int, earned_fraction: float) -> float:
    """Award some of the available points based on a 0.0-to-1.0 subscore."""
    return points_available * max(0.0, min(float(earned_fraction), 1.0))


def _as_fraction(points: float) -> float:
    """Convert points out of 100 into the 0.0-to-1.0 score Foundry expects."""
    return max(0.0, min(points, 100.0)) / 100


def _yes(condition: object) -> float:
    """Turn a plain yes/no check into a score."""
    return 1.0 if condition else 0.0
