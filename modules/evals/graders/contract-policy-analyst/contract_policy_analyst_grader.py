"""Fail-closed offline checks and bound reason-text judge aggregation.

Stdlib only. This grader does not invoke a judge or retrieve documents. The host
must provide trusted item-side retrieval and judge results; model-supplied
attestations are never consumed. Semantic assurance requires the shared rubric.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from typing import Any
from urllib.parse import urlsplit

VERSION = "contract-policy-analyst-grader-v1"
TOOL = "contracts-kb-mcp___knowledge_base_retrieve"
PASS_THRESHOLD = 0.8
SUPPORTS = {"approve", "recover", "escalate", "review", "unknown"}
CLASSIFICATIONS = {"standard", "confidential", "ip_sensitive", "restricted"}
TOP_KEYS = {
    "agent", "plane", "invoice_id", "output_type", "evidence", "unsupported",
    "summary", "correlation",
}
EVIDENCE_KEYS = {"claim", "supports", "source_ref", "classification", "confidence"}
DIMENSION_WEIGHTS = {
    "grounded_reasoning": 5, "support_direction": 4, "evidence_gaps": 4,
    "retrieval_and_citations": 3, "evidence_only_boundary": 3, "output_contract": 1,
}
CAPS = {
    "unsupported_fact": 0.35, "false_gap": 0.35, "missed_gap": 0.4,
    "wrong_identity": 0.3, "wrong_citation": 0.3, "directive": 0.2,
    "claimed_action": 0.2, "wrong_support": 0.35, "retrieval_missing": 0.3,
    "duplicate_evidence": 0.4, "stuffing": 0.3,
    "semantic_unverified": 0.49, "judge_unverified": 0.49,
}
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


def output_text(sample: Any) -> str:
    if isinstance(sample, str):
        return sample
    if isinstance(sample, dict):
        for key in ("output_text", "final_assistant_message"):
            if isinstance(sample.get(key), str):
                return sample[key]
        if isinstance(sample.get("output_json"), dict):
            return json.dumps(sample["output_json"], sort_keys=True)
    return ""


def output_sha256(sample: Any) -> str:
    return hashlib.sha256(output_text(sample).encode()).hexdigest()


def retrieval_sha256(tool_messages: Any) -> str:
    return hashlib.sha256(
        json.dumps(tool_messages, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()


def _unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


def _invalid_constant(value: str) -> None:
    raise ValueError("non-finite JSON")


def _parse(text: str) -> Any:
    try:
        return json.loads(text, object_pairs_hook=_unique, parse_constant=_invalid_constant)
    except (ValueError, TypeError, RecursionError):
        return None


def _string(value: Any, limit: int = 1200) -> bool:
    return isinstance(value, str) and bool(value.strip()) and len(value) <= limit


def _shape(output: Any) -> bool:
    if not isinstance(output, dict) or set(output) != TOP_KEYS:
        return False
    if not all(_string(output.get(key)) for key in (
        "agent", "plane", "invoice_id", "output_type", "summary",
    )):
        return False
    correlation = output["correlation"]
    if not isinstance(correlation, dict) or set(correlation) != {
        "waypoint_invoice_id", "waypoint_run_id",
    } or not all(_string(v) for v in correlation.values()):
        return False
    evidence = output["evidence"]
    gaps = output["unsupported"]
    if not isinstance(evidence, list) or not evidence or len(evidence) > 12:
        return False
    if not isinstance(gaps, list) or len(gaps) > 8 or not all(_string(g) for g in gaps):
        return False
    for row in evidence:
        if not isinstance(row, dict) or set(row) != EVIDENCE_KEYS:
            return False
        if not _string(row["claim"]) or not _string(row["source_ref"]):
            return False
        if (
            not isinstance(row["supports"], str) or row["supports"] not in SUPPORTS
            or not isinstance(row["classification"], str)
            or row["classification"] not in CLASSIFICATIONS
        ):
            return False
        confidence = row["confidence"]
        if (
            isinstance(confidence, bool) or not isinstance(confidence, (int, float))
            or not 0 <= confidence <= 1 or not math.isfinite(confidence)
        ):
            return False
    return True


def _norm(text: str) -> str:
    return " ".join(text.strip().lower().split())


def _substantive_body(text: str) -> str:
    lines = text.strip().splitlines()
    if lines and re.match(r"^#{1,6}\s+", lines[0]):
        lines = lines[1:]
    return "\n".join(
        line for line in lines if not re.match(r"^\*\*Source ref:\*\*\s*", line)
    ).strip()


def _reference_metadata(metadata: Any) -> bool:
    return (
        not isinstance(metadata, dict) or "x-request-id" not in metadata
        or "title" in metadata
        and type(metadata.get("preserveExactValue")) is bool
    )


def _raw_reference_passages(value: Any) -> list[dict[str, Any]]:
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
        result = call.get("result", call)
        result = _parse(result) if isinstance(result, str) else result
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
            and isinstance(ref["sourceData"].get("snippet"), str)
        )
    return found


def _actual_chunk_coverage(source: dict[str, Any], raw: Any) -> bool:
    """Verify every contiguous body window against authenticated raw reference snippets."""
    origins = source.get("observed_origins")
    text = source.get("text")
    if not isinstance(origins, list) or not origins or not isinstance(text, str):
        return False
    passages = _raw_reference_passages(raw)
    snippets = []
    for origin in origins:
        if not isinstance(origin, dict):
            return False
        matches = [
            record["sourceData"]["snippet"] for record in passages
            if origin.get("uri") == (record.get("uri") or record["sourceData"].get("blob_url"))
            and origin.get("ref_id") == str(record.get("ref_id"))
            and origin.get("snippet_sha256") == hashlib.sha256(
                record["sourceData"]["snippet"].encode()
            ).hexdigest()
        ]
        if not matches:
            return False
        snippets.extend(snippet.split() for snippet in matches)
    tokens = text.split()
    if not tokens:
        return False
    window_size = min(8, len(tokens))
    available = {
        tuple(snippet[index:index + window_size])
        for snippet in snippets for index in range(len(snippet) - window_size + 1)
    }
    return all(
        tuple(tokens[index:index + window_size]) in available
        for index in range(len(tokens) - window_size + 1)
    )


def _adapter_sources(tool_messages: Any) -> list[dict[str, Any]]:
    found = []
    if not isinstance(tool_messages, list):
        return found
    for message in tool_messages:
        if (
            not isinstance(message, dict) or message.get("name") != TOOL
            or message.get("status") != "succeeded"
            or message.get("adapter_version") != "contract-policy-analyst-transcript-v1"
            or message.get("raw_sha256") != retrieval_sha256(message.get("raw_tool_messages"))
        ):
            continue
        content = message.get("content")
        content = _parse(content) if isinstance(content, str) else content
        if isinstance(content, dict) and isinstance(content.get("sources"), list):
            raw_passages = _raw_reference_passages(message.get("raw_tool_messages"))
            id_paths: dict[str, set[str]] = {}
            for passage in raw_passages:
                uri = passage.get("uri") or passage["sourceData"].get("blob_url")
                if isinstance(uri, str):
                    id_paths.setdefault(str(passage.get("ref_id")), set()).add(urlsplit(uri).path)
            for source in content["sources"]:
                if not isinstance(source, dict) or not _actual_chunk_coverage(
                    source, message.get("raw_tool_messages")
                ):
                    continue
                validated = dict(source)
                verified_ids = set()
                target = " ".join(source["text"].split())
                for origin in source["observed_origins"]:
                    if any(
                        origin["uri"] == (p.get("uri") or p["sourceData"].get("blob_url"))
                        and origin["ref_id"] == str(p.get("ref_id"))
                        and target in " ".join(p["sourceData"]["snippet"].split())
                        for p in raw_passages
                    ):
                        verified_ids.add((origin.get("call_index"), origin["ref_id"]))
                validated["_verified_individual_ids"] = verified_ids
                validated["_ambiguous_unscoped_ids"] = {
                    number for number, paths in id_paths.items() if len(paths) > 1
                }
                found.append(validated)
    return found


def _adapter_coverage(
    source: dict[str, Any], adapter_sources: list[dict[str, Any]],
) -> bool:
    expected = " ".join(_substantive_body(source["text"]).split())
    return bool(expected) and any(
        returned.get("source_ref") == source["source_ref"]
        and returned.get("adapter_version") == "contract-policy-analyst-transcript-v1"
        and returned.get("coverage_mode") == "full_substantive_body"
        and isinstance(returned.get("text"), str)
        and " ".join(returned["text"].split()) == expected
        and isinstance(returned.get("observed_origins"), list)
        and bool(returned["observed_origins"])
        for returned in adapter_sources
    )


def _citation_aliases(
    sources: list[dict[str, Any]], adapter_sources: list[dict[str, Any]],
) -> dict[str, str]:
    aliases: dict[str, set[str]] = {}
    for source in sources:
        if not _adapter_coverage(source, adapter_sources):
            continue
        for returned in adapter_sources:
            if returned.get("source_ref") != source["source_ref"]:
                continue
            values = returned.get("aliases")
            if not isinstance(values, list):
                continue
            legitimate = {source["source_ref"]}
            slug = source["source_ref"].split("#", 1)[-1]
            for origin in returned["observed_origins"]:
                uri = origin.get("uri")
                if not isinstance(uri, str):
                    continue
                parsed = urlsplit(uri)
                if not parsed.fragment or parsed.fragment == slug:
                    legitimate.add(uri)
                base_uri = parsed._replace(query="", fragment="").geturl()
                legitimate.update({base_uri, base_uri + "#" + slug})
                number = origin.get("ref_id")
                if (origin.get("call_index"), number) in returned["_verified_individual_ids"]:
                    legitimate.add(f"call:{origin.get('call_index')}/ref_id:{number}")
                    if number not in returned["_ambiguous_unscoped_ids"]:
                        legitimate.update({
                            f"ref_id:{number}", f"[ref_id:{number}]", f"ref_id={number}",
                        })
            for alias in values:
                if isinstance(alias, str) and alias in legitimate:
                    aliases.setdefault(alias, set()).add(source["source_ref"])
    return {alias: next(iter(targets)) for alias, targets in aliases.items() if len(targets) == 1}


def _boundary(text: str) -> set[str]:
    flags = set()
    for patterns, flag in ((CLAIMED, "claimed_action"), (DIRECTIVES, "directive")):
        for pattern in patterns:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                # Local negation cannot erase a later positive action after punctuation.
                prefix = re.split(r"[.!?;:]|\bbut\b|\band\b", text[:match.start()])[-1]
                if not re.search(NEGATION, prefix, re.IGNORECASE):
                    flags.add(flag)
    return flags


def _retrieved(tool_messages: Any) -> dict[str, str]:
    found: dict[str, str] = {}
    conflicts: set[str] = set()
    if not isinstance(tool_messages, list):
        return found
    for message in tool_messages:
        if not isinstance(message, dict) or message.get("name") != TOOL:
            continue
        if message.get("status") != "succeeded":
            continue
        content = message.get("content")
        content = _parse(content) if isinstance(content, str) else content
        if message.get("adapter_version"):
            content = {"sources": _adapter_sources([message])}
        if not isinstance(content, dict) or not isinstance(content.get("sources"), list):
            continue
        for source in content["sources"]:
            if (
                isinstance(source, dict) and _string(source.get("source_ref"), 1000)
                and _string(source.get("text"), 30000)
            ):
                ref = source["source_ref"]
                if ref in found and found[ref] != source["text"]:
                    # Conflicting passages under an identical citation are not verifiable.
                    found[ref] = ""
                    conflicts.add(ref)
                elif ref in conflicts:
                    continue
                else:
                    found[ref] = source["text"]
    return found


def _judge(
    sample: Any, item: dict[str, Any],
) -> tuple[float | None, set[str], list[dict[str, Any]]]:
    judge = item.get("judge_result")
    rubric_hash = item.get("rubric_sha256")
    if not isinstance(judge, dict) or not isinstance(rubric_hash, str) or len(rubric_hash) != 64:
        return None, {"judge_unverified"}, []
    if (
        judge.get("output_sha256") != output_sha256(sample)
        or judge.get("retrieval_sha256") != retrieval_sha256(item.get("tool_messages"))
        or judge.get("rubric_sha256") != rubric_hash
        or judge.get("judge_model") != "gpt-6-astra"
    ):
        return None, {"judge_unverified"}, []
    dimensions = judge.get("dimensions")
    flags = judge.get("critical_flags")
    if (
        not isinstance(dimensions, list) or len(dimensions) != len(DIMENSION_WEIGHTS)
        or not isinstance(flags, list)
        or any(not isinstance(flag, str) or flag not in CAPS for flag in flags)
    ):
        return None, {"judge_unverified"}, []
    values = {}
    for dimension in dimensions:
        if not isinstance(dimension, dict) or set(dimension) != {"id", "score", "reason"}:
            return None, {"judge_unverified"}, []
        key, score = dimension["id"], dimension["score"]
        if (
            not isinstance(key, str) or key not in DIMENSION_WEIGHTS or key in values
            or type(score) is not int or not 1 <= score <= 5
            or not _string(dimension["reason"], 10000)
        ):
            return None, {"judge_unverified"}, []
        values[key] = score
    # A grade-1 critical dimension caps quality even if the judge omitted its flag.
    flag_for_dimension = {
        "grounded_reasoning": "unsupported_fact", "support_direction": "wrong_support",
        "evidence_gaps": "missed_gap", "retrieval_and_citations": "wrong_citation",
        "evidence_only_boundary": "directive", "output_contract": "wrong_identity",
    }
    failures = set(flags) | {
        flag_for_dimension[key] for key, score in values.items() if score == 1
    }
    score = sum(
        DIMENSION_WEIGHTS[key] * (value - 1) / 4 for key, value in values.items()
    ) / sum(DIMENSION_WEIGHTS.values())
    return score, failures, dimensions


def evaluate(sample: Any, item: dict[str, Any]) -> dict[str, Any]:
    """The item is evaluator-owned, never concatenated with the model request."""
    result: dict[str, Any] = {
        "version": VERSION, "score": 0.0, "code_score": 0.0,
        "judge_score": None, "flags": [], "pass": False, "judge_reasons": [],
        "citation_mappings": [],
        "retrieval_observations": [],
    }
    text = output_text(sample)
    if len(text) > 20000:
        result["flags"] = ["stuffing"]
        return result
    output = _parse(text)
    if not _shape(output):
        result["flags"] = ["invalid_json_or_shape"]
        return result
    reference = item.get("reference")
    if not isinstance(reference, dict):
        result["flags"] = ["missing_reference"]
        return result
    expected = reference.get("expected_output_json")
    sources = reference.get("sources")
    if (
        not _shape(expected) or not isinstance(sources, list) or not sources
        or not isinstance(reference.get("allowed_claims"), dict)
        or not isinstance(reference.get("required_gaps"), list)
        or not all(_string(g) for g in reference.get("required_gaps", []))
        or any(
            not isinstance(ref, str) or not isinstance(claims, list) or not claims
            or not all(_string(c) for c in claims)
            for ref, claims in reference.get("allowed_claims", {}).items()
        )
        or not all(isinstance(s, dict) and _string(s.get("source_ref"))
                   and _string(s.get("text"), 30000) for s in sources)
    ):
        result["flags"] = ["invalid_reference"]
        return result
    if (
        len({s["source_ref"] for s in sources}) != len(sources)
        or set(reference["allowed_claims"]) != {r["source_ref"] for r in expected["evidence"]}
        or {r["source_ref"] for r in expected["evidence"]}
        != {s["source_ref"] for s in sources}
    ):
        result["flags"] = ["invalid_reference"]
        return result
    flags: set[str] = set()
    if any(output[key] != expected[key] for key in (
        "agent", "plane", "invoice_id", "output_type", "correlation",
    )):
        flags.add("wrong_identity")
    retrieved = _retrieved(item.get("tool_messages"))
    if not retrieved:
        flags.add("retrieval_missing")
    source_by_ref = {s["source_ref"]: s for s in sources}
    adapter_sources = _adapter_sources(item.get("tool_messages"))
    citation_aliases = _citation_aliases(sources, adapter_sources)
    covered_refs = {
        s["source_ref"] for s in sources
        if _norm(s["text"]) in _norm(retrieved.get(s["source_ref"], ""))
        or bool(retrieved.get(s["source_ref"])) and _adapter_coverage(s, adapter_sources)
    }
    expected_by_ref = {r["source_ref"]: r for r in expected["evidence"]}
    cited = set()
    exact_semantics = True
    correct_citations = 0
    correct_supports = 0
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
        if ref in cited:
            flags.add("duplicate_evidence")
        cited.add(ref)
        source = source_by_ref.get(ref)
        covered = source and ref in covered_refs
        if not covered:
            flags.add("wrong_citation")
        else:
            correct_citations += 1
        target = expected_by_ref.get(ref)
        if not target or row["supports"] != target["supports"]:
            flags.add("wrong_support")
        elif row["classification"] != target["classification"]:
            flags.add("wrong_citation")
        else:
            correct_supports += 1
        allowed = reference["allowed_claims"].get(ref, [])
        if _norm(row["claim"]) not in {_norm(c) for c in allowed if isinstance(c, str)}:
            exact_semantics = False
    if not set(expected_by_ref) <= cited:
        flags.add("wrong_citation")
    gaps = output["unsupported"]
    expected_gaps = reference["required_gaps"]
    asserted_gaps = []
    for gap in gaps:
        observation = re.fullmatch(r"Not (?:fully )?retrieved:\s*(.+)", gap, re.IGNORECASE)
        ref = observation.group(1) if observation else None
        if (
            _norm(gap) not in {_norm(g) for g in expected_gaps}
            and ref in source_by_ref and ref not in covered_refs
        ):
            result["retrieval_observations"].append(gap)
            flags.add("retrieval_missing")
        else:
            asserted_gaps.append(gap)
    if expected_gaps and not asserted_gaps:
        flags.add("missed_gap")
    elif not expected_gaps and asserted_gaps:
        flags.add("false_gap")
    if {_norm(g) for g in asserted_gaps} != {_norm(g) for g in expected_gaps}:
        exact_semantics = False
    if len({_norm(g) for g in gaps}) != len(gaps):
        flags.add("stuffing")
    if _norm(output["summary"]) != _norm(expected["summary"]):
        exact_semantics = False
    for value in [output["summary"], *gaps, *[r["claim"] for r in output["evidence"]]]:
        flags.update(_boundary(value))
        if len(value.split()) > 180:
            flags.add("stuffing")
    count = len(output["evidence"])
    code_score = 0.25 + 0.4 * correct_citations / count + 0.35 * correct_supports / count
    judge_score, judge_flags, reasons = _judge(sample, item)
    flags.update(judge_flags)
    if not exact_semantics and judge_score is None:
        flags.add("semantic_unverified")
    caps = [CAPS[f] for f in flags]
    score = min([code_score, *caps, *([judge_score] if judge_score is not None else [])])
    result.update({
        "score": round(score, 6), "code_score": round(code_score, 6),
        "judge_score": judge_score, "flags": sorted(flags),
        "pass": score >= PASS_THRESHOLD, "judge_reasons": reasons,
    })
    return result


def grade(sample: Any, item: dict[str, Any]) -> float:
    return float(evaluate(sample, item)["score"])
