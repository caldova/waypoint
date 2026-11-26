"""Code-only training reward v2, aligned to quality grader v3. NOT the quality evaluator.

Stdlib only; no inference, retrieval, I/O, dynamic execution or judge attestation.
References (contract-policy-analyst-reference-v3) and genuine context are
trainer-owned, hash-pinned inputs. Changes from reward v1, mirroring grader v3:

* per-source acceptable direction sets (``v3_contract``) replace one exact label;
* forbidden directions, unmet require_any, false/missed approval are deterministic;
* classification is not graded; confidence is not compared to a synthetic label;
* no exact claim, summary, gap or recommended_action lexical matching is rewarded;
* false_gap is never a deterministic flag; missed_gap only when a gap is required;
* duplicate_evidence fires only for an exact normalized repeat on the same source;
* the directive screen is grader v3's (a lexical backstop, not semantic proof) and
  exempts modal obligations explicitly attributed to a source ("the policy says ...");
* claim-level approval assertions ("is billable", "meets all conditions") are
  false_approval where the contract forbids them, independent of the support label;
* a ref is citable when its full body was retrieved or when a provenance-verified
  retrieval passage quotes a contiguous excerpt under an explicit Source ref line.

Because there is no judge here, a numeric-grounding backstop flags
unsupported_fact when a claim or summary states a number that appears in no
model-visible input (system/developer/user messages and hash-verified successful
retrieval output) or the evidence-derived amount readings, and is not derivable
from them by chained single arithmetic steps or percent forms. Hidden free-text
reference fields (expected summary, claims, gaps) never ground numbers. Two-step
arithmetic with an unprinted intermediate is a known false-positive limitation.
"""

from __future__ import annotations

import bisect
import hashlib
import json
import math
import re
from typing import Any

VERSION = "contract-policy-analyst-code-rft-reward-v2"
REFERENCE_VERSION = "contract-policy-analyst-reference-v3"
TOOL = "contracts-kb-mcp___knowledge_base_retrieve"
EXCERPT_MIN_WORDS = 12
MAX_GROUNDING_NUMBERS = 5000
TOP_KEYS = {
    "agent", "plane", "invoice_id", "output_type", "evidence", "unsupported",
    "summary", "correlation",
}
EVIDENCE_KEYS = {"claim", "supports", "source_ref", "classification", "confidence"}
SUPPORTS = {"approve", "recover", "escalate", "review", "unknown"}
CLASSIFICATIONS = {"standard", "confidential", "ip_sensitive", "restricted"}
CAPS = {
    "wrong_identity": 0.3, "wrong_citation": 0.3, "retrieval_missing": 0.3,
    "wrong_support": 0.35, "false_approval": 0.2, "unsupported_fact": 0.35,
    "false_gap": 0.35, "missed_gap": 0.4, "directive": 0.2,
    "claimed_action": 0.2, "duplicate_evidence": 0.4, "stuffing": 0.3,
    "missed_approval": 0.35,
}
WEIGHTS = {
    "schema": 0.1, "identity": 0.15, "citations": 0.25, "support": 0.3,
    "coverage": 0.1, "gaps": 0.1,
}
# Quality grader v3 phrase vocabulary, copied verbatim (parity is tested).
ACTION = (
    r"(?:pay|approv\w*|disput\w*|reject\w*|hold|withhold|recover\w*|credit\w*|"
    r"refund\w*|reconcil\w*|escalat\w*|deduct\w*|offset|short-pay|rebill|"
    r"reprice|recalculate|release\s+payment|request\w*|contact\w*|notify\w*|"
    r"creat\w*\s+(?:a\s+)?case|open\w*\s+(?:a\s+)?case|write\s+back)"
)
IMPERATIVE = (
    r"(?:pay|approve|dispute|reject|hold|withhold|recover|credit|refund|reconcile|"
    r"escalate|deduct|offset|short-pay|rebill|reprice|recalculate|release\s+payment|"
    r"request|contact|notify|create\s+(?:a\s+)?case|open\s+(?:a\s+)?case|write\s+back)"
)
NOUN_FOLLOW = (
    r"(?:-|\s+(?:rule|rules|instrument|instruments|adjustment|adjustments|amount|amounts|"
    r"note|notes|memo|memos|transaction|transactions|balance|balances|record|records|"
    r"request|requests|id|ids|identifier|status|statuses|treatment|terms?|limit|cap|"
    r"policy|period|line|lines|value|values|documentation|document|documents|evidence|"
    r"history|application|applicability|applied|eligibility|"
    r"is|are|was|were|has|have|had|remains?|of|for|"
    r"can|cannot|could|would|will|may|might|does|do|did)\b)"
)
OBJECT = (
    r"\s+(?:(?:the|this|that|these|those|a|an|all|any|it|them|usd|payment|"
    r"invoice|invoices|supplier|vendor|charge|line|amount)\b|\$|\d)"
)
DIRECTIVES = (
    rf"(?:^|[.!?;:]\s*){IMPERATIVE}\b(?!{NOUN_FOLLOW})",
    rf"\b(?:then|please|and|or)\s+{IMPERATIVE}\b(?={OBJECT})",
    rf"\b(?:should|ought\s+to)\s+(?:\w+ly\s+)?(?:be\s+)?{ACTION}\b(?!{NOUN_FOLLOW})",
    rf"\b(?:must|need\s+to|needs\s+to)\s+(?:\w+ly\s+)?{ACTION}\b(?!{NOUN_FOLLOW})",
    rf"\b(?:must|need\s+to|needs\s+to)\s+be\s+{ACTION}\b(?!\s+by\b)(?!{NOUN_FOLLOW})",
    rf"\b(?:recommend\w*|suggest\w*|advise\w*)\s+(?:that\s+)?(?:(?:the\s+)?\w+\s+)?"
    rf"(?:\w+ly\s+)?{ACTION}\b(?!{NOUN_FOLLOW})",
    rf"\b(?:i|we|you|finance|controller|ap)\s+(?:will|shall)\s+{ACTION}\b",
)
CLAIMED = (
    r"\b(?:i|we)\s+(?:have\s+|already\s+)?"
    r"(?:approved|paid|disputed|reconciled|credited|notified|contacted|"
    r"withheld|recovered|updated|submitted|posted|created|opened|released)\b",
    r"\b(?:payment|invoice|case|credit|dispute)\s+(?:was\s+|is\s+|has\s+been\s+)?"
    r"(?:approved|paid|released|created|opened|submitted|requested|filed)\b",
    r"\b(?:updated|wrote\s+to|posted\s+to|submitted\s+to)\s+(?:the\s+)?waypoint\b",
    r"\b(?:marked\s+as\s+paid|write-back\s+complete)\b",
)
NEGATION = r"\b(?:not|never|no|cannot|can't|without|mustn't|won't)\b(?:\W+\w+){0,4}\W*$"
# Indices of the modal DIRECTIVES that a source attribution can exempt.
MODAL_DIRECTIVES = (2, 3, 4)
ATTRIBUTION = (
    r"\b(?:policy|policies|sow|contract|agreement|clause|section|schedule|terms|rule|"
    r"statement\s+of\s+work|procedure)\b[^.!?;:]{0,60}?\b(?:says|states|stated|provides|"
    r"specifies|stipulates|requires\s+that|required\s+that)\b(?:\s+that)?[^.!?;:]*$"
)
APPROVAL_BILLABLE = (
    r"\b(?:line|invoice(?:\s+line)?|item|charge|amount|fee|it|total)\s+"
    r"(?:is|was|remains)\s+(?:fully\s+|therefore\s+|thus\s+)?billable\b"
    r"(?!\s+(?:only|if|when|once|upon|provided|subject|unless|until|at)\b)",
    r"\bbillable\s+(?:as\s+invoiced|in\s+full)\b",
)
APPROVAL_CONDITIONS = (
    r"\b(?:meets|met|satisfies|satisfied|fulfils|fulfills|fulfilled)\s+(?:all|every|each|both)"
    r"\b[^.!?;]{0,60}?\b(?:conditions?|prerequisites?|requirements?|criteria)\b",
    r"\b(?:all|every|each|both)\b[^.!?;]{0,60}?\b(?:conditions?|prerequisites?|"
    r"requirements?|criteria)\s+(?:is|are|was|were|has\s+been|have\s+been)\s+(?:all\s+)?"
    r"(?:met|satisfied|confirmed|fulfilled|verified)\b",
)
APPROVAL_HEDGE = (
    r"\b(?:whether|if|unless|until|once|when|cannot\s+(?:confirm|verify|establish)|"
    r"(?:does|do|did)\s+not\s+\w+|"
    r"not\s+(?:confirmed|established|shown|demonstrated|evidenced|verified|clear)|"
    r"unverified|unconfirmed|no\s+evidence|unclear)\b(?:\W+\w+){0,8}\W*$"
)
# Categories where an approval assertion contradicts the contract.
BILLABLE_FORBIDDEN = {"recover", "missing_condition", "escalate", "wrong_entity"}
CONDITIONS_FORBIDDEN = {"missing_condition", "wrong_entity"}
SOURCE_REF_LINE = re.compile(r"^\*\*Source ref:\*\*\s*`?([^\s`]+)`?\s*$", re.IGNORECASE | re.M)


def _unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


def _constant(value: str) -> None:
    raise ValueError("non-finite JSON")


def _parse(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value, object_pairs_hook=_unique, parse_constant=_constant)
    except (ValueError, TypeError, RecursionError):
        return None


def canonical_sha256(value: Any) -> str:
    """Canonical JSON value hash, not authentication or proof of human review."""
    try:
        text = json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)
        return hashlib.sha256(text.encode()).hexdigest()
    except (ValueError, TypeError, RecursionError, UnicodeError):
        return ""


def _hash_matches(value: Any, pinned: Any) -> bool:
    return (
        isinstance(pinned, str) and re.fullmatch(r"[0-9a-f]{64}", pinned) is not None
        and pinned == canonical_sha256(value)
    )


def _text(sample: Any) -> str:
    if isinstance(sample, str):
        return sample
    if isinstance(sample, dict):
        for key in ("output_text", "final_assistant_message"):
            if isinstance(sample.get(key), str):
                return sample[key]
        if isinstance(sample.get("output_json"), dict):
            try:
                return json.dumps(sample["output_json"], allow_nan=False)
            except (ValueError, TypeError, RecursionError):
                return ""
        choices = sample.get("choices")
        if isinstance(choices, list) and len(choices) == 1 and isinstance(choices[0], dict):
            message = choices[0].get("message")
            if isinstance(message, dict) and isinstance(message.get("content"), str):
                return message["content"]
    return ""


def _string(value: Any, limit: int = 1200) -> bool:
    return isinstance(value, str) and bool(value.strip()) and len(value) <= limit


def _shape(output: Any) -> bool:
    if not isinstance(output, dict) or set(output) != TOP_KEYS:
        return False
    if not all(_string(output[k]) for k in (
        "agent", "plane", "invoice_id", "output_type", "summary",
    )):
        return False
    correlation = output["correlation"]
    if not isinstance(correlation, dict) or set(correlation) != {
        "waypoint_invoice_id", "waypoint_run_id",
    } or not all(_string(v) for v in correlation.values()):
        return False
    evidence, gaps = output["evidence"], output["unsupported"]
    if not isinstance(evidence, list) or not 1 <= len(evidence) <= 12:
        return False
    if not isinstance(gaps, list) or len(gaps) > 8 or not all(_string(g) for g in gaps):
        return False
    for row in evidence:
        if not isinstance(row, dict) or set(row) != EVIDENCE_KEYS:
            return False
        if not _string(row["claim"]) or not _string(row["source_ref"]):
            return False
        if not isinstance(row["supports"], str) or row["supports"] not in SUPPORTS:
            return False
        if (
            not isinstance(row["classification"], str)
            or row["classification"] not in CLASSIFICATIONS
        ):
            return False
        confidence = row["confidence"]
        if (
            type(confidence) not in (int, float) or not 0 <= confidence <= 1
            or not math.isfinite(confidence)
        ):
            return False
    return True


def _norm(value: str) -> str:
    return " ".join(value.lower().split())


def _body(text: str) -> str:
    lines = text.strip().splitlines()
    if lines and re.match(r"^#{1,6}\s+", lines[0]):
        lines = lines[1:]
    body = " ".join(
        line for line in lines if not re.match(r"^\*\*Source ref:\*\*\s*", line)
    )
    return " ".join(body.split())


def _boundary(text: str) -> set[str]:
    """Lexical directive/claimed-action backstop; not a semantic guarantee."""
    flags = set()
    for patterns, flag in ((CLAIMED, "claimed_action"), (DIRECTIVES, "directive")):
        for index, pattern in enumerate(patterns):
            for match in re.finditer(pattern, text, re.IGNORECASE):
                prefix = re.split(r"[.!?;:]|\bbut\b|\band\b", text[:match.start()])[-1]
                if re.search(NEGATION, prefix, re.IGNORECASE):
                    continue
                if flag == "directive" and index in MODAL_DIRECTIVES:
                    # Attribution covers only its own clause; contrast or a new clause resets it.
                    clause = re.split(
                        r"[.!?;:](?=\s|$)|[,\u2014\u2013()\[\]\n]|\s-{1,2}\s|"
                        r"\b(?:but|however|nevertheless|yet|although|"
                        r"though|whereas|while|and|so|therefore|thus|hence)\b",
                        text[:match.start()], flags=re.IGNORECASE,
                    )[-1]
                    if re.search(ATTRIBUTION, clause, re.IGNORECASE):
                        continue
                flags.add(flag)
    return flags


def approval_flags(text: str, category: Any) -> set[str]:
    """Claim-level approval assertions the contract forbids; a lexical backstop."""
    patterns = [
        *(APPROVAL_BILLABLE if category in BILLABLE_FORBIDDEN else ()),
        *(APPROVAL_CONDITIONS if category in CONDITIONS_FORBIDDEN else ()),
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            prefix = re.split(r"[.!?;:](?=\s|$)|\bbut\b", text[:match.start()])[-1]
            if not (
                re.search(NEGATION, prefix, re.IGNORECASE)
                or re.search(APPROVAL_HEDGE, prefix, re.IGNORECASE)
            ):
                return {"false_approval"}
    return set()


def _claim_key(claim: str) -> tuple[str, ...]:
    return tuple(re.findall(r"[a-z0-9]+(?:\.[0-9]+)?", claim.lower()))


def exact_duplicate(claim: str, previous: list[str]) -> bool:
    """Only an exact normalized repeat; distinct quantities or facts never collide."""
    return _claim_key(claim) in {_claim_key(other) for other in previous}


NUMBER = r"(?<![\w.])\d[\d,]*(?:\.\d+)?(?![\w])"


def _numbers(text: str) -> set[str]:
    found = set()
    for raw in re.findall(NUMBER, text):
        try:
            found.add(f"{float(raw.replace(',', '')):.2f}")
        except ValueError:
            continue
    return found


def _ungrounded_text(text: str, grounding: set[str]) -> set[str]:
    """Comma-joined tokens such as min(373,364) count if either reading is grounded."""
    missing = _ungrounded(_numbers(text), grounding)
    for raw in re.findall(NUMBER, text):
        if "," not in raw.strip(","):
            continue
        joined = _numbers(raw)
        if joined & missing and not _ungrounded(_numbers(raw.replace(",", " ")), grounding):
            missing -= joined
    return missing


def _derivable(c: float, values: list[float]) -> bool:
    """True when c = a op b (within 0.01) for some a, b in the sorted values.

    The operand search window for x and / scales with the target so that a
    rounded quotient such as 1000/3000 = 0.33 is still found.
    """
    for a in values:
        for target, value_of, scaled in (
            (c - a, lambda b, a=a: a + b, False), (a - c, lambda b, a=a: a - b, False),
            (c / a if a else None, lambda b, a=a: a * b, True),
            (a / c if c else None, lambda b, a=a: a / b if b else math.inf, True),
        ):
            if target is None:
                continue
            window = max(0.011, 0.011 * abs(target) / abs(c)) if scaled and c else 0.011
            index = bisect.bisect_left(values, target - window)
            while index < len(values) and values[index] <= target + window:
                if abs(value_of(values[index]) - c) <= 0.01:
                    return True
                index += 1
    return False


def _ungrounded(found: set[str], grounding: set[str]) -> set[str]:
    """Numbers not stated in, or derivable by chained single +,-,*,/ steps from, grounding.

    Percent forms (n/100, 1-n/100, 1+n/100) count as grounded so that a stated
    "3% discount" may appear as 0.97. Small invented numbers can still be
    derivable by coincidence; this is a backstop, not a semantic proof.
    """
    pool = set(grounding)
    for value in list(grounding):
        n = float(value)
        if 0 < n <= 100:
            pool |= {f"{n / 100:.2f}", f"{1 - n / 100:.2f}", f"{1 + n / 100:.2f}"}
    remaining = set(found) - pool
    changed = True
    while remaining and changed:
        changed = False
        values = sorted(float(v) for v in pool)
        for candidate in sorted(remaining):
            if _derivable(float(candidate), values):
                pool.add(candidate)
                remaining.discard(candidate)
                changed = True
    return remaining


def _strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for v in value.values() for s in _strings(v)]
    if isinstance(value, list):
        return [s for v in value for s in _strings(v)]
    return []


def _valid_contract(reference: dict[str, Any]) -> bool:
    terms = reference.get("v3_contract")
    if reference.get("version") != REFERENCE_VERSION or not isinstance(terms, dict):
        return False
    refs = {s["source_ref"] for s in reference["sources"]}
    allowed = terms.get("allowed_supports")
    require = terms.get("require_any")
    return (
        isinstance(allowed, dict) and set(allowed) == refs
        and all(isinstance(v, list) and v and set(v) <= SUPPORTS for v in allowed.values())
        and isinstance(terms.get("forbidden_supports"), list)
        and set(terms["forbidden_supports"]) <= SUPPORTS
        and isinstance(terms.get("gap_required"), bool)
        and isinstance(terms.get("approval_expected"), bool)
        and (
            require is None or isinstance(require, dict)
            and bool(require.get("supports")) and bool(require.get("source_refs"))
            and set(require["supports"]) <= SUPPORTS and set(require["source_refs"]) <= refs
        )
    )


def _valid_reference(reference: Any) -> bool:
    if not isinstance(reference, dict) or not _shape(reference.get("expected_output_json")):
        return False
    sources = reference.get("sources")
    if (
        not isinstance(sources, list) or not sources
        or not all(
            isinstance(s, dict) and _string(s.get("source_ref"))
            and _string(s.get("text"), 30000) and bool(_body(s["text"]))
            for s in sources
        )
    ):
        return False
    refs = {s["source_ref"] for s in sources}
    expected = reference["expected_output_json"]
    return (
        len(refs) == len(sources)
        and refs == {r["source_ref"] for r in expected["evidence"]}
        and _valid_contract(reference)
    )


def _reference_metadata(metadata: Any) -> bool:
    return (
        not isinstance(metadata, dict) or "x-request-id" not in metadata
        or "title" in metadata
        and type(metadata.get("preserveExactValue")) is bool
    )


def _raw_passages(value: Any) -> list[dict[str, Any]]:
    """Only successful retrieval protocol slots can supply raw reference metadata."""
    native = isinstance(value, dict) and value.get("schema") == "castia.tool_capture/v1"
    calls = (
        value.get("tool_calls", []) if native
        else value.get("records", [value]) if isinstance(value, dict) else value
    )
    found = []
    for call in calls if isinstance(calls, list) else []:
        if (
            not isinstance(call, dict) or call.get("name", call.get("tool_name", TOOL)) != TOOL
        ):
            continue
        successful = (
            call.get("status") == "ok" and call.get("tool_reported_ok") is True
            and call.get("error") is None
            if native else call.get("status") in (None, "succeeded")
        )
        if not successful:
            continue
        result = _parse(call.get("result", call))
        if not isinstance(result, dict) or result.get("ok") is not True:
            continue
        refs = []
        content = result.get("content")
        for block in content if isinstance(content, list) else []:
            if not isinstance(block, dict) or block.get("type") != "text":
                continue
            metadata = block.get("_meta")
            if not _reference_metadata(metadata):
                continue
            parsed = _parse(block.get("text"))
            if isinstance(parsed, dict) and parsed.get("kind") == "reference":
                refs.append(parsed)
        structured = result.get("structured_content")
        if isinstance(structured, dict):
            structured = (
                [structured] if structured.get("kind") == "reference"
                else structured.get("references", [])
            )
        for ref in structured if isinstance(structured, list) else []:
            if not isinstance(ref, dict) or ref.get("kind") != "reference":
                continue
            metadata = ref.get("_meta")
            if _reference_metadata(metadata):
                refs.append(ref)
        found.extend(
            ref for ref in refs if isinstance(ref.get("sourceData"), dict)
            and _string(ref["sourceData"].get("snippet"), 30000)
        )
    return found


def _expected_path(ref: str) -> str:
    document = ref.split("#", 1)[0]
    if document.startswith("knowledge/contracts/"):
        return "/" + document
    for kind in ("contracts", "policies"):
        prefix = f"data/{kind}/source-markdown/"
        if document.startswith(prefix):
            return "/knowledge/contracts/" + document[len(prefix):]
    return ""


def _https_blob_path(uri: str) -> str | None:
    # Only the HTTPS Azure blob profile used by the adapter; never decode or repair a URL.
    if any(ord(character) <= 32 or ord(character) == 127 for character in uri):
        return None
    match = re.fullmatch(
        r"(?i:https)://([A-Za-z0-9.-]+)(?::[0-9]+)?"
        r"(/[^?#]*)(?:\?[^#]*)?(?:#.*)?",
        uri,
    )
    if not match or not match[1].lower().endswith(".blob.core.windows.net"):
        return None
    return match[2]


def _adapter_verified(source: dict[str, Any], message: dict[str, Any]) -> bool:
    if (
        message.get("adapter_version") != "contract-policy-analyst-transcript-v1"
        or not _hash_matches(message.get("raw_tool_messages"), message.get("raw_sha256"))
        or source.get("coverage_mode") != "full_substantive_body"
    ):
        return False
    origins = source.get("observed_origins")
    path = _expected_path(source["source_ref"])
    if not isinstance(origins, list) or not origins or not path:
        return False
    try:
        passages = _raw_passages(message.get("raw_tool_messages"))
    except RecursionError:
        return False
    snippets = []
    for origin in origins:
        if not isinstance(origin, dict) or not isinstance(origin.get("uri"), str):
            return False
        if _https_blob_path(origin["uri"]) != path:
            return False
        matches = [
            p["sourceData"]["snippet"] for p in passages
            if (p.get("uri") or p["sourceData"].get("blob_url")) == origin["uri"]
            and str(p.get("ref_id")) == origin.get("ref_id")
            and p["sourceData"].get("blob_url", origin["uri"]) == origin.get("blob_url")
            and hashlib.sha256(p["sourceData"]["snippet"].encode()).hexdigest()
            == origin.get("snippet_sha256")
        ]
        if not matches:
            return False
        snippets.extend(s.split() for s in matches)
    tokens = source["text"].split()
    width = min(8, len(tokens))
    windows = {
        tuple(s[i:i + width]) for s in snippets for i in range(len(s) - width + 1)
    }
    return bool(tokens) and all(
        tuple(tokens[i:i + width]) in windows for i in range(len(tokens) - width + 1)
    )


def _context(item: dict[str, Any]) -> tuple[dict[str, str], str | None, list[str]]:
    """Return unambiguous text per ref, any issue, and every verified retrieved text."""
    mode = item.get("context_mode")
    value = item.get("tool_messages") if mode == "retrieved" else item.get("retrieved_context")
    if mode not in ("retrieved", "inlined") or not isinstance(value, list) or not value:
        return {}, "missing_context", []
    if not _hash_matches(value, item.get("context_sha256")):
        return {}, "context_hash_mismatch", []
    if mode == "inlined":
        messages = item.get("messages")
        if not isinstance(messages, list) or not any(
            isinstance(m, dict) and m.get("role") in ("developer", "user")
            and isinstance(m.get("content"), str)
            and isinstance(payload := _parse(m["content"]), dict)
            and payload.get("retrieved_context") == value
            for m in messages
        ):
            return {}, "context_not_in_prompt", []
        records = value
    else:
        records, raw_texts = [], []
        for message in value:
            if (
                not isinstance(message, dict) or message.get("name") != TOOL
                or message.get("status") != "succeeded"
            ):
                continue
            raw_texts.extend(_raw_retrieval_texts(message))
            content = _parse(message.get("content"))
            if not isinstance(content, dict) or not isinstance(content.get("sources"), list):
                continue
            for source in content["sources"]:
                if not isinstance(source, dict) or not _string(source.get("source_ref")):
                    continue
                if not _string(source.get("text"), 30000):
                    continue
                if message.get("adapter_version") and not _adapter_verified(source, message):
                    continue
                records.append(source)
    found, conflicts = {}, set()
    for source in records:
        if (
            not isinstance(source, dict) or not _string(source.get("source_ref"))
            or not _string(source.get("text"), 30000)
        ):
            return {}, "invalid_context", []
        ref, text = source["source_ref"], source["text"]
        if ref in conflicts or ref in found and found[ref] != text:
            conflicts.add(ref)
            found.pop(ref, None)
        else:
            found[ref] = text
    texts = [source["text"] for source in records]
    if mode == "retrieved":
        texts.extend(raw_texts)
    return found, None if found else "missing_context", texts


def _raw_retrieval_texts(message: dict[str, Any]) -> list[str]:
    """Model-visible text of successful, hash-verified retrieval calls (grounding only).

    Adapters keep only full-body sources as records; excerpt hits (a SOW section
    quoted in the tool's answer) still put figures in front of the model, so they
    ground numbers. Failed, unverified or argument text never grounds.
    """
    raw = message.get("raw_tool_messages")
    if not _hash_matches(raw, message.get("raw_sha256")):
        return []
    native = isinstance(raw, dict) and raw.get("schema") == "castia.tool_capture/v1"
    calls = raw.get("tool_calls") if native else None
    texts = []
    for call in calls if isinstance(calls, list) else []:
        if (
            not isinstance(call, dict) or call.get("name") != TOOL
            or call.get("status") != "ok" or call.get("tool_reported_ok") is not True
            or call.get("error") is not None
        ):
            continue
        result = _parse(call.get("result"))
        if not isinstance(result, dict) or result.get("ok") is not True:
            continue
        content = result.get("content")
        for part in content if isinstance(content, list) else []:
            if isinstance(part, dict) and _string(part.get("text"), 200000):
                texts.append(part["text"])
    return texts


def excerpt_covered_refs(tool_messages: Any, bodies: dict[str, str]) -> set[str]:
    """Refs quoted as a contiguous excerpt in a provenance-verified retrieval passage.

    The passage must come from a successful, hash-pinned call, its blob path must be
    the cited document, and the excerpt must follow an explicit Source ref line for
    that ref and be at least EXCERPT_MIN_WORDS words of the reference body, verbatim
    after whitespace normalization. Queries, echoed filenames and bare refs never count.
    """
    covered: set[str] = set()
    for message in tool_messages if isinstance(tool_messages, list) else []:
        if (
            not isinstance(message, dict) or message.get("name") != TOOL
            or message.get("status") != "succeeded"
        ):
            continue
        raw = message.get("raw_tool_messages")
        if (
            not isinstance(raw, dict) or raw.get("schema") != "castia.tool_capture/v1"
            or not _hash_matches(raw, message.get("raw_sha256"))
        ):
            continue
        try:
            passages = _raw_passages(raw)
        except RecursionError:
            continue
        for passage in passages:
            uri = passage.get("uri") or passage["sourceData"].get("blob_url")
            path = _https_blob_path(uri) if isinstance(uri, str) else None
            snippet = passage["sourceData"]["snippet"]
            marks = list(SOURCE_REF_LINE.finditer(snippet))
            for index, mark in enumerate(marks):
                ref = mark[1]
                if ref in covered or ref not in bodies or path != _expected_path(ref):
                    continue
                end = marks[index + 1].start() if index + 1 < len(marks) else len(snippet)
                section = snippet[mark.end():end]
                parts = re.split(r"^#{1,6}\s", section, maxsplit=1, flags=re.M)
                words = parts[0].split()
                if len(parts) == 1 and end == len(snippet):
                    words = words[:-1]  # the passage may cut the final word
                if len(words) < EXCERPT_MIN_WORDS:
                    continue
                if f" {' '.join(words)} " in f" {_body(bodies[ref])} ":
                    covered.add(ref)
    return covered


def evaluate_reward(sample: Any, item: dict[str, Any]) -> dict[str, Any]:
    """Deterministic training surrogate; never a quality pass or judge substitute."""
    result = {
        "version": VERSION, "metric_kind": "training_reward", "score": 0.0,
        "components": {}, "flags": [], "context_mode": None,
        "calibrated": False, "quality_estimate": False,
        "retrieval_observations": [], "classification_mismatches": [],
        "excerpt_covered_refs": [],
    }
    if not isinstance(item, dict):
        result["flags"] = ["invalid_item"]
        return result
    reference = _parse(item.get("reference"))
    if not _valid_reference(reference):
        result["flags"] = ["invalid_reference"]
        return result
    if not _hash_matches(reference, item.get("reference_sha256")):
        result["flags"] = ["reference_hash_mismatch"]
        return result
    result["context_mode"] = item.get("context_mode")
    context, issue, retrieved_texts = _context(item)
    if issue:
        result["flags"] = [issue, "retrieval_missing"]
        return result
    text = _text(sample)
    if len(text) > 20000:
        result["flags"] = ["stuffing"]
        return result
    output = _parse(text)
    if not _shape(output):
        result["flags"] = ["invalid_json_or_shape"]
        return result
    terms = reference["v3_contract"]
    expected = reference["expected_output_json"]
    targets = {r["source_ref"]: r for r in expected["evidence"]}
    sources = {s["source_ref"]: s for s in reference["sources"]}
    covered_refs = {
        ref for ref, source in sources.items()
        if _body(source["text"]) in " ".join(context.get(ref, "").split())
    }
    if item.get("context_mode") == "retrieved":
        excerpts = excerpt_covered_refs(
            item.get("tool_messages"), {ref: s["text"] for ref, s in sources.items()},
        ) - covered_refs
        covered_refs |= excerpts
        result["excerpt_covered_refs"] = sorted(excerpts)
    allowed = {ref: set(v) for ref, v in terms["allowed_supports"].items()}
    forbidden = set(terms["forbidden_supports"])
    visible = [
        m.get("content") for m in item.get("messages") or []
        if isinstance(m, dict) and m.get("role") in ("system", "developer", "user")
    ]
    grounding: set[str] = set()
    # amount_readings are computed from the authored rule and observed facts, so a
    # model stating one states an evidence-derived figure (often multi-step, e.g.
    # tiers). Free-text hidden fields (expected summary, gaps) never ground.
    for value in [
        *retrieved_texts, *_strings(visible),
        *_strings(terms.get("amount_readings")), *_strings(terms.get("billed_amount")),
    ]:
        grounding |= _numbers(value)
    grounding = set(sorted(grounding)[:MAX_GROUNDING_NUMBERS])
    flags = set()
    identity = all(output[k] == expected[k] for k in (
        "agent", "plane", "invoice_id", "output_type", "correlation",
    ))
    if not identity:
        flags.add("wrong_identity")
    citation_count = support_count = 0
    claims_by_ref: dict[str, list[str]] = {}
    supports_by_ref: dict[str, set[str]] = {}
    for row in output["evidence"]:
        ref = row["source_ref"]
        if exact_duplicate(row["claim"], claims_by_ref.get(ref, [])):
            flags.add("duplicate_evidence")
        claims_by_ref.setdefault(ref, []).append(row["claim"])
        supports_by_ref.setdefault(ref, set()).add(row["supports"])
        if ref in sources and ref in covered_refs:
            citation_count += 1
        else:
            flags.add("wrong_citation")
        if row["supports"] in forbidden:
            flags.add("wrong_support")
            if row["supports"] == "approve":
                flags.add("false_approval")
        elif ref in allowed and row["supports"] in allowed[ref]:
            support_count += 1
        else:
            flags.add("wrong_support")
        target = targets.get(ref)
        if target and row["classification"] != target["classification"]:
            result["classification_mismatches"].append(ref)
        if _ungrounded_text(row["claim"], grounding):
            flags.add("unsupported_fact")
    coverage = set(targets) <= set(claims_by_ref)
    if not coverage:
        flags.add("wrong_citation")
    require = terms.get("require_any")
    if require and not any(
        supports_by_ref.get(ref, set()) & set(require["supports"])
        for ref in require["source_refs"]
    ):
        flags.add("missed_approval" if terms["approval_expected"] else "wrong_support")
    known = {_norm(g) for g in expected["unsupported"]}
    asserted = []
    for gap in output["unsupported"]:
        observation = re.fullmatch(r"Not (?:fully )?retrieved:\s*(.+)", gap, re.IGNORECASE)
        ref = observation.group(1) if observation else None
        if _norm(gap) not in known and ref in sources and ref not in covered_refs:
            result["retrieval_observations"].append(gap)
            flags.add("retrieval_missing")
        else:
            asserted.append(gap)
    gaps_ok = bool(asserted) or not terms["gap_required"]
    if not gaps_ok:
        flags.add("missed_gap")
    if len({_norm(g) for g in output["unsupported"]}) != len(output["unsupported"]):
        flags.add("stuffing")
    if _ungrounded_text(output["summary"], grounding):
        flags.add("unsupported_fact")
    for value in [
        output["summary"], *output["unsupported"], *[r["claim"] for r in output["evidence"]],
    ]:
        flags.update(_boundary(value))
        flags.update(approval_flags(value, terms.get("category")))
        if len(value.split()) > 180:
            flags.add("stuffing")
    count = len(output["evidence"])
    components = {
        "schema": 1.0, "identity": float(identity),
        "citations": citation_count / count, "support": support_count / count,
        "coverage": float(coverage), "gaps": float(gaps_ok),
    }
    uncapped = sum(WEIGHTS[k] * v for k, v in components.items())
    result.update({
        "score": round(min([uncapped, *[CAPS[f] for f in flags]]), 3),
        "components": components, "flags": sorted(flags),
    })
    return result


def grade(sample: Any, item: dict[str, Any]) -> float:
    return float(evaluate_reward(sample, item)["score"])
