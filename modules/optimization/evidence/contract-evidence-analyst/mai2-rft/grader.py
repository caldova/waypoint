"""Code grader for the contract-evidence-analyst evidence-only output contract.

Stdlib only and free of ``compile``/``eval`` so it runs in the Foundry RFT
python-grader sandbox. ``grade(sample, item)`` returns a score in [0, 1].

Gold lives in ``item["reference"]`` (dict or JSON string) with per-ref roles
and allowed supports, required gap predicates, supplied-record predicates and
the numeric tokens present in the task.

The decision-language screen is a phrase screen, not a semantic guarantee.
"""

from __future__ import annotations

import json
import re
from typing import Any

GRADER_VERSION = "contract-evidence-analyst-v1"

WEIGHTS = {
    "refs": 0.25,
    "supports": 0.30,
    "gaps": 0.25,
    "claims": 0.10,
    "classification": 0.05,
    "summary": 0.05,
}

SUPPORTS = {"approve", "recover", "escalate", "review", "unknown"}
CLASSIFICATIONS = {"contract_term", "policy_term", "operational_record", "supplier_assertion"}
PREFIX_CLASS = {
    "C": "contract_term",
    "P": "policy_term",
    "R": "operational_record",
    "S": "supplier_assertion",
}

MAX_OUTPUT_CHARS = 20000
MAX_EVIDENCE_ITEMS = 12
MAX_GAP_ITEMS = 8
MAX_CLAIM_WORDS = 60
MAX_SUMMARY_WORDS = 90
FREE_EXTRA_GAPS = 2
EXTRA_GAP_PENALTY = 0.05
APPROVE_EXTRA_GAP_PENALTY = 0.1
FALSE_GAP_PENALTY = 0.25
DISTRACTOR_PENALTY = 0.1

INVALID_SCORE = 0.0
OVERSIZE_CAP = 0.3
WRONG_LINE_CAP = 0.3
FABRICATED_REF_CAP = 0.35
BOUNDARY_CAP = 0.2
FALSE_APPROVAL_CAP = 0.4
UNFLAGGED_GAP_CAP = 0.4
MISSED_GAP_CAP = 0.5
FALSE_GAP_CAP = 0.6
PRIMARY_MISREAD_CAP = 0.7
STUFFING_CAP = 0.5
MISSED_ESCALATION_CAP = 0.6
MISSED_APPROVAL_CAP = 0.6

EMPTY_GAP_MARKERS = ("none", "n/a", "nothing", "no missing", "no gaps", "not applicable")

CLAIMED_ACTIONS = (
    "approved for payment",
    "payment approved",
    "payment released",
    "released payment",
    "released the payment",
    "invoice approved",
    "approved the invoice",
    "approved this invoice",
    "approved this line",
    "marked as paid",
    "i approved",
    "i have approved",
    "we approved",
    "i disputed",
    "we disputed",
    "dispute filed",
    "dispute opened",
    "opened a dispute",
    "filed a dispute",
    "credit requested",
    "requested a credit",
    "notified the supplier",
    "case created",
    "created a case",
    "payment withheld",
    "withheld payment",
)
ACTION_STEMS = (
    r"(?:pay|paid|paying|approv\w*|disput\w*|reject\w*|withh\w*|recover\w*|credit\w*"
    r"|refund\w*|deduct\w*|short-pa\w*|hold|held)"
)
DIRECTIVE_PATTERNS = (
    r"\b(?:invoice|line|amount|payment|it|supplier|this\s+charge|the\s+charge)\s+"
    r"(?:should|must|ought\s+to|needs?\s+to)\s+(?:not\s+)?(?:be\s+)?" + ACTION_STEMS + r"\b",
    r"\b(?:recommend\w*|suggest\w*|advis\w*|propose\w*)\s+(?:that\s+)?(?:\w+\s+){0,3}?"
    + ACTION_STEMS
    + r"\b",
    r"(?:^|[.!?;:]\s+)(?:pay|approve|dispute|reject|withhold|recover|refund|deduct|short-pay|hold)"
    r"\s+(?:the|this|it|payment|all)\b",
    r"\b(?:i|we)\s+(?:will|have|'ve|shall)\s+(?:\w+\s+)?" + ACTION_STEMS + r"\b",
    r"\b(?:finance|ap|you)\s+should\s+(?:\w+\s+)?" + ACTION_STEMS + r"\b",
)
NEGATED_ACTION = r"\b(?:not|no|never|cannot|without|reserved)\b(?:\W+\w+){0,4}\W*$"


def grade(sample: Any, item: dict[str, Any]) -> float:
    return float(evaluate(sample, item)["score"])


def evaluate(sample: Any, item: dict[str, Any]) -> dict[str, Any]:
    """Score plus component breakdown and critical-failure flags."""
    reference = _reference(item)
    text = _output_text(sample)
    result: dict[str, Any] = {"score": INVALID_SCORE, "components": {}, "flags": []}
    if not reference:
        result["flags"].append("missing_reference")
        return result
    output = _parse(text)
    if output is None:
        result["flags"].append("invalid_json")
        return result
    if not _valid_shape(output):
        result["flags"].append("invalid_shape")
        return result

    refs: dict[str, dict[str, Any]] = reference.get("refs") or {}
    required = [ref for ref, spec in refs.items() if spec.get("role") == "required"]
    cited: dict[str, dict[str, Any]] = {}
    conflicting: set[str] = set()
    for row in output["evidence"]:
        ref = _norm_ref(row["source_ref"])
        if ref in cited:
            if cited[ref]["supports"] != row["supports"]:
                conflicting.add(ref)
            continue
        cited[ref] = row

    flags: list[str] = result["flags"]
    caps: list[float] = []
    penalty = 0.0

    if len(text) > MAX_OUTPUT_CHARS:
        caps.append(OVERSIZE_CAP)
        flags.append("oversize")
    if len(output["evidence"]) > MAX_EVIDENCE_ITEMS or len(output["unsupported"]) > MAX_GAP_ITEMS:
        caps.append(STUFFING_CAP)
        flags.append("stuffing")
    if str(output["invoice_line_id"]).strip() != reference.get("invoice_line_id"):
        caps.append(WRONG_LINE_CAP)
        flags.append("wrong_invoice_line")

    if any(ref not in refs for ref in cited):
        caps.append(FABRICATED_REF_CAP)
        flags.append("fabricated_ref")

    refs_score = sum(1 for ref in required if ref in cited) / len(required) if required else 1.0

    graded = list(required) + [ref for ref in cited if refs.get(ref, {}).get("role") == "optional"]
    correct = 0
    for ref in graded:
        row = cited.get(ref)
        if row and ref not in conflicting and row["supports"] in refs[ref].get("supports", []):
            correct += 1
    supports_score = correct / len(graded) if graded else 1.0

    primary = next((ref for ref, spec in refs.items() if spec.get("primary")), None)
    gold_primary = refs.get(primary, {}).get("supports", []) if primary else []
    if primary and primary in cited:
        given = cited[primary]["supports"]
        if given == "approve" and "approve" not in gold_primary:
            caps.append(FALSE_APPROVAL_CAP)
            flags.append("false_approval")
        elif "approve" in gold_primary and given != "approve":
            caps.append(MISSED_APPROVAL_CAP)
            flags.append("missed_approval")
        elif given not in gold_primary or primary in conflicting:
            caps.append(PRIMARY_MISREAD_CAP)
            flags.append("primary_term_misread")

    approve_row = "approve" in gold_primary
    for ref, row in cited.items():
        spec = refs.get(ref)
        if not spec or spec.get("role") != "distractor":
            continue
        if row["supports"] not in spec.get("supports", []):
            penalty += DISTRACTOR_PENALTY
            flags.append("distractor_misused")
            if row["supports"] == "approve" and not approve_row:
                caps.append(FALSE_APPROVAL_CAP)
                flags.append("false_approval")

    if reference.get("escalation_expected") and not any(
        row["supports"] == "escalate" for row in cited.values()
    ):
        caps.append(MISSED_ESCALATION_CAP)
        flags.append("missed_escalation")

    gaps_score, gap_flags, gap_caps = _score_gaps(output["unsupported"], reference, approve_row)
    flags.extend(gap_flags)
    caps.extend(gap_caps)

    classification_score = (
        sum(
            1
            for ref, row in cited.items()
            if row["classification"] in CLASSIFICATIONS
            and row["classification"] == PREFIX_CLASS.get(ref[:1], row["classification"])
        )
        / len(cited)
        if cited
        else 0.0
    )

    claims_score = _score_claims(cited, reference)
    summary = output["summary"].strip()
    summary_score = 1.0 if summary and len(summary.split()) <= MAX_SUMMARY_WORDS else 0.0

    if _boundary_violation(output):
        caps.append(BOUNDARY_CAP)
        flags.append("boundary_violation")

    components = {
        "refs": refs_score,
        "supports": supports_score,
        "gaps": gaps_score,
        "claims": claims_score,
        "classification": classification_score,
        "summary": summary_score,
    }
    raw = sum(WEIGHTS[key] * value for key, value in components.items()) - penalty
    score = max(0.0, min(1.0, raw))
    if caps:
        score = min(score, min(caps))
    result["score"] = round(score, 6)
    result["components"] = {key: round(value, 4) for key, value in components.items()}
    result["flags"] = sorted(set(flags))
    return result


def _score_gaps(
    gaps: list[str], reference: dict[str, Any], approve_row: bool
) -> tuple[float, list[str], list[float]]:
    flags: list[str] = []
    caps: list[float] = []
    real = [gap for gap in gaps if not _is_empty_marker(gap)]
    required = reference.get("required_gaps") or []
    supplied = reference.get("supplied_predicates") or []
    matched_required: set[str] = set()
    false_gaps = 0
    extra = 0
    for gap in real:
        hits = [spec["id"] for spec in required if _matches(gap, spec.get("kw") or [])]
        if hits:
            matched_required.update(hits)
            continue
        supplied_hits = [spec for spec in supplied if _matches(gap, spec.get("kw") or [])]
        if any(not spec.get("contradicted") for spec in supplied_hits):
            false_gaps += 1
            continue
        if supplied_hits:
            continue
        extra += 1

    if false_gaps:
        flags.append("false_gap")
        caps.append(FALSE_GAP_CAP)
    if required:
        if not real:
            caps.append(UNFLAGGED_GAP_CAP)
            flags.append("missing_evidence_not_flagged")
        elif not matched_required:
            caps.append(MISSED_GAP_CAP)
            flags.append("required_gap_missed")
        score = len(matched_required) / len(required)
    else:
        score = 1.0
    score -= FALSE_GAP_PENALTY * false_gaps
    if approve_row and not required:
        score -= APPROVE_EXTRA_GAP_PENALTY * extra
    else:
        score -= EXTRA_GAP_PENALTY * max(0, extra - FREE_EXTRA_GAPS)
    return max(0.0, score), flags, caps


def _matches(text: str, groups: list[list[str]]) -> bool:
    if not groups:
        return False
    lowered = text.lower()
    return all(any(_term_in(term.lower(), lowered) for term in group) for group in groups)


def _term_in(term: str, text: str) -> bool:
    escaped = re.escape(term)
    pattern = r"\b" + escaped + r"\b" if len(term) <= 3 else r"\b" + escaped
    return re.search(pattern, text) is not None


def _is_empty_marker(gap: str) -> bool:
    lowered = gap.strip().lower().rstrip(".")
    return not lowered or any(
        lowered == marker or lowered.startswith(marker + " ") for marker in EMPTY_GAP_MARKERS
    )


def _score_claims(cited: dict[str, dict[str, Any]], reference: dict[str, Any]) -> float:
    if not cited:
        return 0.0
    allowed = set(reference.get("allowed_numbers") or [])
    good = 0
    for row in cited.values():
        claim = row["claim"].strip()
        if not claim or len(claim.split()) > MAX_CLAIM_WORDS:
            continue
        if allowed and any(token not in allowed for token in _numbers(claim)):
            continue
        good += 1
    return good / len(cited)


def _numbers(text: str) -> set[str]:
    tokens = set()
    for raw in re.findall(r"\d[\d,]*(?:\.\d+)?", text):
        token = raw.replace(",", "")
        if "." in token:
            token = token.rstrip("0").rstrip(".")
        tokens.add(token)
    return tokens


def _boundary_violation(output: dict[str, Any]) -> bool:
    texts = [output["summary"]]
    texts.extend(row["claim"] for row in output["evidence"])
    texts.extend(output["unsupported"])
    for text in texts:
        lowered = text.lower()
        for phrase in CLAIMED_ACTIONS:
            start = lowered.find(phrase)
            while start != -1:
                prefix = re.split(r"[.;?!]", lowered[max(0, start - 60) : start])[-1]
                if not re.search(NEGATED_ACTION, prefix):
                    return True
                start = lowered.find(phrase, start + 1)
        for pattern in DIRECTIVE_PATTERNS:
            if re.search(pattern, lowered):
                return True
    return False


def _norm_ref(value: str) -> str:
    return value.strip().strip("[]").strip().upper()


def _valid_shape(output: Any) -> bool:
    if not isinstance(output, dict):
        return False
    for key in ("invoice_line_id", "evidence", "unsupported", "summary"):
        if key not in output:
            return False
    if not isinstance(output["invoice_line_id"], str) or not isinstance(output["summary"], str):
        return False
    if not isinstance(output["evidence"], list) or not output["evidence"]:
        return False
    if not isinstance(output["unsupported"], list) or not all(
        isinstance(gap, str) for gap in output["unsupported"]
    ):
        return False
    for row in output["evidence"]:
        if not isinstance(row, dict):
            return False
        for key in ("source_ref", "classification", "supports", "claim"):
            if not isinstance(row.get(key), str):
                return False
        if row["supports"] not in SUPPORTS:
            return False
    return True


def _parse(text: str) -> Any:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    if not stripped.startswith("{"):
        return None
    try:
        return json.loads(
            stripped, object_pairs_hook=_no_duplicates, parse_constant=_reject_constant
        )
    except (ValueError, TypeError):
        return None


def _no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate key {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError(f"invalid constant {value}")


def _reference(item: Any) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    reference = item.get("reference")
    if isinstance(reference, str):
        try:
            reference = json.loads(reference)
        except ValueError:
            return None
    return reference if isinstance(reference, dict) else None


def _output_text(sample: Any) -> str:
    if isinstance(sample, dict):
        output_json = sample.get("output_json")
        if isinstance(output_json, dict):
            return json.dumps(output_json)
        if isinstance(output_json, str) and output_json.strip():
            return output_json.strip()
        for key in ("output_text", "response"):
            value = sample.get(key)
            if isinstance(value, str):
                return value.strip()
        choices = sample.get("choices")
        if isinstance(choices, list) and choices and isinstance(choices[0], dict):
            message = choices[0].get("message")
            if isinstance(message, dict):
                return _content_text(message.get("content"))
        output = sample.get("output")
        if isinstance(output, str):
            return output.strip()
        if isinstance(output, list):
            return _content_text(output)
    return str(sample or "").strip()


def _content_text(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, dict):
                value = part.get("text")
                if value is None and isinstance(part.get("content"), (list, str)):
                    value = _content_text(part.get("content"))
                if value is not None:
                    parts.append(str(value))
        return "\n".join(parts).strip()
    return str(content or "").strip()
