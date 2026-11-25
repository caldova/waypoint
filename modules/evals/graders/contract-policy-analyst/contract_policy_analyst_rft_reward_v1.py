"""Conservative, code-only training reward, NOT the matched quality evaluator.

Stdlib only; no inference, retrieval, I/O, dynamic execution or judge attestation.
References and genuine context are trainer-owned, hash-pinned inputs. Exact
allowlists deliberately reject unreviewed paraphrases. See the companion RFT doc.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from typing import Any

VERSION = "contract-policy-analyst-code-rft-reward-v1"
TOOL = "contracts-kb-mcp___knowledge_base_retrieve"
QUALITY_GRADER_BASELINE_SHA256 = (
    "95189aeb3fb2355963ea6a78c29528678299024b51c0631cd3652bbea966a675"
)
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
    "overconfidence": 0.35,
}
WEIGHTS = {
    "schema": 0.1, "identity": 0.15, "citations": 0.25, "support": 0.2,
    "claims": 0.15, "gaps": 0.1, "summary": 0.05,
}
# Quality v1 phrase vocabulary; training scopes negation to the action token.
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
DIRECTIVES = (
    rf"(?:^|[.!?;:]\s*|\b(?:then|please|and|or)\s+){IMPERATIVE}\b",
    rf"\b(?:should|must|ought\s+to|need\s+to|recommend\w*|suggest\w*|advise\w*)"
    rf"\s+(?:that\s+)?(?:\w+\s+){{0,4}}?{ACTION}\b",
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
    flags = set()
    for patterns, flag in ((CLAIMED, "claimed_action"), (DIRECTIVES, "directive")):
        for pattern in patterns:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                action = re.search(rf"\b{ACTION}\b", match.group(), re.IGNORECASE)
                start = match.start() + action.start() if action else match.start()
                prefix = re.split(r"[.!?;:]|\bbut\b|\band\b", text[:start])[-1]
                if not re.search(NEGATION, prefix, re.IGNORECASE):
                    flags.add(flag)
    return flags


def _valid_reference(reference: Any) -> bool:
    if not isinstance(reference, dict) or not _shape(reference.get("expected_output_json")):
        return False
    sources, allowed, gaps = (
        reference.get("sources"), reference.get("allowed_claims"), reference.get("required_gaps"),
    )
    if (
        not isinstance(sources, list) or not sources or not isinstance(allowed, dict)
        or not isinstance(gaps, list) or not all(_string(g) for g in gaps)
        or not all(
            isinstance(s, dict) and _string(s.get("source_ref"))
            and _string(s.get("text"), 30000) and bool(_body(s["text"]))
            for s in sources
        )
        or not all(
            isinstance(ref, str) and isinstance(claims, list) and claims
            and all(_string(c) for c in claims) for ref, claims in allowed.items()
        )
    ):
        return False
    expected = reference["expected_output_json"]
    refs = {s["source_ref"] for s in sources}
    if (
        len(refs) != len(sources) or len(expected["evidence"]) != len(refs)
        or refs != set(allowed) or refs != {r["source_ref"] for r in expected["evidence"]}
        or len({_norm(g) for g in gaps}) != len(gaps)
        or {_norm(g) for g in gaps} != {_norm(g) for g in expected["unsupported"]}
    ):
        return False
    return all(
        _norm(row["claim"]) in {_norm(c) for c in allowed[row["source_ref"]]}
        for row in expected["evidence"]
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


def _context(item: dict[str, Any]) -> tuple[dict[str, str], str | None]:
    mode = item.get("context_mode")
    value = item.get("tool_messages") if mode == "retrieved" else item.get("retrieved_context")
    if mode not in ("retrieved", "inlined") or not isinstance(value, list) or not value:
        return {}, "missing_context"
    if not _hash_matches(value, item.get("context_sha256")):
        return {}, "context_hash_mismatch"
    if mode == "inlined":
        messages = item.get("messages")
        if not isinstance(messages, list) or not any(
            isinstance(m, dict) and m.get("role") in ("developer", "user")
            and isinstance(m.get("content"), str)
            and isinstance(payload := _parse(m["content"]), dict)
            and payload.get("retrieved_context") == value
            for m in messages
        ):
            return {}, "context_not_in_prompt"
        records = value
    else:
        records = []
        for message in value:
            if (
                not isinstance(message, dict) or message.get("name") != TOOL
                or message.get("status") != "succeeded"
            ):
                continue
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
            return {}, "invalid_context"
        ref, text = source["source_ref"], source["text"]
        if ref in conflicts or ref in found and found[ref] != text:
            conflicts.add(ref)
            found.pop(ref, None)
        else:
            found[ref] = text
    return found, None if found else "missing_context"


def evaluate_reward(sample: Any, item: dict[str, Any]) -> dict[str, Any]:
    """Deterministic training surrogate; never a quality pass or judge substitute."""
    result = {
        "version": VERSION, "metric_kind": "training_reward", "score": 0.0,
        "components": {}, "flags": [], "context_mode": None,
        "calibrated": False, "quality_estimate": False,
        "retrieval_observations": [],
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
    context, issue = _context(item)
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
    expected = reference["expected_output_json"]
    targets = {r["source_ref"]: r for r in expected["evidence"]}
    sources = {s["source_ref"]: s for s in reference["sources"]}
    covered_refs = {
        ref for ref, source in sources.items()
        if _body(source["text"]) in " ".join(context.get(ref, "").split())
    }
    flags = set()
    identity = all(output[k] == expected[k] for k in (
        "agent", "plane", "invoice_id", "output_type", "correlation",
    ))
    if not identity:
        flags.add("wrong_identity")
    citation_count = support_count = claim_count = 0
    cited = set()
    for row in output["evidence"]:
        ref = row["source_ref"]
        if ref in cited:
            flags.add("duplicate_evidence")
        cited.add(ref)
        target = targets.get(ref)
        source = sources.get(ref)
        if not source or ref not in covered_refs:
            flags.add("wrong_citation")
        else:
            citation_count += 1
        if not target or row["supports"] != target["supports"]:
            flags.add("wrong_support")
            if row["supports"] == "approve":
                flags.add("false_approval")
        elif row["classification"] != target["classification"]:
            flags.add("wrong_citation")
        else:
            support_count += 1
        if target and row["confidence"] > target["confidence"]:
            flags.add("overconfidence")
        if _norm(row["claim"]) not in {
            _norm(c) for c in reference["allowed_claims"].get(ref, [])
        }:
            flags.add("unsupported_fact")
        else:
            claim_count += 1
    if set(targets) != cited:
        flags.add("wrong_citation")
    required = {_norm(g) for g in reference["required_gaps"]}
    gaps = set()
    for gap in output["unsupported"]:
        observation = re.fullmatch(r"Not (?:fully )?retrieved:\s*(.+)", gap, re.IGNORECASE)
        ref = observation.group(1) if observation else None
        if _norm(gap) not in required and ref in sources and ref not in covered_refs:
            result["retrieval_observations"].append(gap)
            flags.add("retrieval_missing")
        else:
            gaps.add(_norm(gap))
    if gaps - required:
        flags.add("false_gap")
    if required - gaps:
        flags.add("missed_gap")
    if len({_norm(g) for g in output["unsupported"]}) != len(output["unsupported"]):
        flags.add("stuffing")
    summary = _norm(output["summary"]) == _norm(expected["summary"])
    if not summary:
        flags.add("unsupported_fact")
    for value in [
        output["summary"], *output["unsupported"], *[r["claim"] for r in output["evidence"]],
    ]:
        flags.update(_boundary(value))
        if len(value.split()) > 180:
            flags.add("stuffing")
    count = len(output["evidence"])
    components = {
        "schema": 1.0, "identity": float(identity),
        "citations": citation_count / count, "support": support_count / count,
        "claims": claim_count / count, "gaps": float(gaps == required),
        "summary": float(summary),
    }
    uncapped = sum(WEIGHTS[k] * v for k, v in components.items())
    result.update({
        "score": round(min([uncapped, *[CAPS[f] for f in flags]]), 3),
        "components": components, "flags": sorted(flags),
    })
    return result


def grade(sample: Any, item: dict[str, Any]) -> float:
    return float(evaluate_reward(sample, item)["score"])
