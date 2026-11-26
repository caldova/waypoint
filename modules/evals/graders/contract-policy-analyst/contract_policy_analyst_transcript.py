"""Lossless reference-snippet adapter, not a retrieval or entailment service.

Raw tool results are retained verbatim as JSON values. Generated synthesis never
supplies evidence. Pinned text is used only to compare coverage, never to fill a
gap or create returned passage text. No model answer or reference is rewritten.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from collections import defaultdict
from typing import Any
from urllib.parse import unquote, urlsplit

VERSION = "contract-policy-analyst-transcript-v1"
TOOL = "contracts-kb-mcp___knowledge_base_retrieve"
MIN_OVERLAP_TOKENS = 8


def _sha(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()


def substantive_body(text: str) -> str:
    """Remove only the leading heading and explicit non-factual source-ref marker."""
    lines = text.strip().splitlines()
    if lines and re.match(r"^#{1,6}\s+", lines[0]):
        lines = lines[1:]
    return "\n".join(
        line for line in lines if not re.match(r"^\*\*Source ref:\*\*\s*", line)
    ).strip()


def _unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for key, value in pairs:
        if key in output:
            raise ValueError("duplicate JSON key")
        output[key] = value
    return output


def _invalid(value: str) -> None:
    raise ValueError("non-finite JSON")


def _parse(text: str) -> Any:
    try:
        return json.loads(text, object_pairs_hook=_unique, parse_constant=_invalid)
    except (ValueError, TypeError, RecursionError):
        return None


def _reference_metadata(metadata: Any) -> bool:
    return (
        not isinstance(metadata, dict) or "x-request-id" not in metadata
        or "title" in metadata
        and type(metadata.get("preserveExactValue")) is bool
    )


def _reference_objects(value: Any) -> list[dict[str, Any]]:
    """Read protocol reference slots only; synthesis and snippet values are opaque."""
    if not isinstance(value, dict):
        return []
    found = []
    content = value.get("content")
    for block in content if isinstance(content, list) else []:
        if not isinstance(block, dict) or block.get("type") != "text":
            continue
        metadata = block.get("_meta")
        if not _reference_metadata(metadata):
            continue
        parsed = _parse(block.get("text"))
        if isinstance(parsed, dict) and parsed.get("kind") == "reference":
            found.append(parsed)
    structured = value.get("structured_content")
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
            found.append(ref)
    return found


def _expected_path(source: dict[str, Any]) -> str | None:
    if source.get("blob_name") and source.get("container"):
        return str(source["container"]) + "/" + str(source["blob_name"])
    document = source.get("document", "").replace("\\", "/")
    if document.startswith("knowledge/contracts/"):
        return document
    # Established original-corpus mapping, not a general basename match.
    if document.startswith(("data/contracts/source-markdown/", "data/policies/source-markdown/")):
        return "knowledge/contracts/" + document.rsplit("/", 1)[-1]
    return None


def _uri_path(uri: Any, allowed_hosts: set[str] | None) -> str | None:
    if not isinstance(uri, str):
        return None
    try:
        parsed = urlsplit(uri)
    except ValueError:
        return None
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or parsed.username or parsed.password:
        return None
    if allowed_hosts is not None:
        if host not in {h.lower() for h in allowed_hosts}:
            return None
    elif not host.endswith(".blob.core.windows.net"):
        return None
    path = unquote(parsed.path).lstrip("/")
    if ".." in path.split("/") or "\\" in path:
        return None
    return path


def _contains(tokens: list[str], target: list[str]) -> tuple[int, int] | None:
    if not target:
        return None
    locations = [
        index for index in range(len(tokens) - len(target) + 1)
        if tokens[index:index + len(target)] == target
    ]
    if len(locations) != 1:
        return None
    return locations[0], locations[0] + len(target)


def _cover(
    snippets: list[dict[str, Any]], body: str,
) -> tuple[str | None, list[int]]:
    """Only observed tokens enter a candidate; joins require exact observed overlaps."""
    target = body.split()
    if not target:
        return None, []
    candidates = [(record["snippet"].split(), [index]) for index, record in enumerate(snippets)]
    candidates.sort(key=lambda pair: (len(pair[0]), pair[1]))
    for tokens, origins in candidates:
        span = _contains(tokens, target)
        if span:
            return " ".join(tokens[span[0]:span[1]]), origins
    # Conservative bounded exact-overlap assembly. No reference-guided insertion/order.
    for _ in range(min(len(candidates), 32)):
        merges = []
        for left_index, (left, left_origins) in enumerate(candidates):
            for right_index, (right, right_origins) in enumerate(candidates):
                if left_index == right_index or set(left_origins) & set(right_origins):
                    continue
                maximum = min(len(left), len(right))
                overlaps = [
                    size for size in range(MIN_OVERLAP_TOKENS, maximum + 1)
                    if left[-size:] == right[:size]
                ]
                if not overlaps:
                    continue
                overlap = max(overlaps)
                merged = left + right[overlap:]
                origins = left_origins + right_origins
                span = _contains(merged, target)
                if span:
                    return " ".join(merged[span[0]:span[1]]), origins
                merges.append((overlap, left_index, right_index, merged, origins))
        if not merges:
            break
        merges.sort(key=lambda merge: (-merge[0], merge[1], merge[2]))
        _, left_index, right_index, merged, origins = merges[0]
        candidates = [
            candidate for index, candidate in enumerate(candidates)
            if index not in {left_index, right_index}
        ] + [(merged, origins)]
    return None, []


def normalize_tool_messages(
    tool_messages: list[dict[str, Any]] | dict[str, Any],
    *,
    reference: dict[str, Any],
    allowed_hosts: set[str] | None = None,
) -> dict[str, Any]:
    """Return raw payload, normalized messages, mappings, aliases and audit issues.

    Accept a raw ``{ok,content,structured_content}``, tool envelopes with
    ``name`` and ``result``, the canary's ``{records:[...]}``, or a native
    ``castia.tool_capture/v1`` document with ``tool_calls``. Native calls require
    status ``ok``, explicit ``tool_reported_ok=True``, no call error and result ``ok=True``.
    Raw-result/canary callers are explicitly asserting trusted retrieval origin;
    an envelope bearing another tool name is never promoted into retrieval.
    """
    raw = copy.deepcopy(tool_messages)
    native = (
        isinstance(tool_messages, dict)
        and tool_messages.get("schema") == "castia.tool_capture/v1"
    )
    calls = (
        tool_messages.get("tool_calls", []) if native
        else tool_messages.get("records", [tool_messages])
        if isinstance(tool_messages, dict) else tool_messages
    )
    issues: list[dict[str, Any]] = []
    records: list[dict[str, Any]] = []
    if not isinstance(calls, list):
        calls = []
        issues.append({"kind": "invalid_calls"})
    for call_index, call in enumerate(calls):
        if not isinstance(call, dict):
            issues.append({"kind": "invalid_call", "call_index": call_index})
            continue
        if call.get("name", call.get("tool_name", TOOL)) != TOOL:
            issues.append({"kind": "wrong_tool", "call_index": call_index})
            continue
        result = call.get("result", call)
        result = _parse(result) if isinstance(result, str) else result
        successful = (
            call.get("status") == "ok" and call.get("tool_reported_ok") is True
            and call.get("error") is None
            if native else call.get("status") in (None, "succeeded")
        )
        if (
            not successful
            or not isinstance(result, dict) or result.get("ok") is not True
        ):
            issues.append({"kind": "failed_or_unverified_call", "call_index": call_index})
            continue
        objects = _reference_objects(result)
        seen = set()
        for reference_object in objects:
            digest = _sha(reference_object)
            if digest in seen:
                continue
            seen.add(digest)
            data = reference_object.get("sourceData")
            if not isinstance(data, dict) or not isinstance(data.get("snippet"), str):
                issues.append({"kind": "missing_snippet", "call_index": call_index})
                continue
            uri = reference_object.get("uri") or data.get("blob_url")
            uri_path = _uri_path(uri, allowed_hosts)
            blob_path = _uri_path(data.get("blob_url", uri), allowed_hosts)
            if not uri_path or uri_path != blob_path:
                issues.append({"kind": "invalid_or_conflicting_uri", "call_index": call_index})
                continue
            ref_id = reference_object.get("ref_id")
            if not (
                type(ref_id) is int or isinstance(ref_id, str) and bool(ref_id.strip())
            ) or not data["snippet"].strip():
                issues.append({"kind": "invalid_reference", "call_index": call_index})
                continue
            records.append({
                "call_index": call_index, "ref_id": str(ref_id), "uri": uri,
                "blob_url": data.get("blob_url"), "uid": data.get("uid"),
                "document_path": uri_path, "snippet": data["snippet"],
                "snippet_sha256": hashlib.sha256(data["snippet"].encode()).hexdigest(),
                "raw_reference": copy.deepcopy(reference_object),
            })
    by_path: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        by_path[record["document_path"]].append(record)
    sources = reference.get("sources", []) if isinstance(reference, dict) else []
    if not isinstance(sources, list):
        sources = []
    aliases: dict[str, set[str]] = defaultdict(set)
    normalized_sources = []
    mappings = []
    # Reused ids across calls or conflicting fragments under one id must not alias silently.
    id_paths: dict[tuple[int, str], set[str]] = defaultdict(set)
    id_snippets: dict[tuple[int, str], set[str]] = defaultdict(set)
    for record in records:
        id_paths[(record["call_index"], record["ref_id"])].add(record["document_path"])
        id_snippets[(record["call_index"], record["ref_id"])].add(record["snippet_sha256"])
    blocked_paths = {
        path for key, paths in id_paths.items()
        if len(paths) > 1 or len(id_snippets[key]) > 1 for path in paths
    }
    if blocked_paths:
        issues.append({"kind": "conflicting_reference_id", "document_paths": sorted(blocked_paths)})
    for source in sources:
        if not isinstance(source, dict) or not isinstance(source.get("text"), str):
            issues.append({"kind": "invalid_pinned_source"})
            continue
        canonical = source.get("source_ref")
        path = _expected_path(source)
        if not isinstance(canonical, str) or not path:
            issues.append({"kind": "unmapped_pinned_document", "source_ref": canonical})
            continue
        body = substantive_body(source["text"])
        if path in blocked_paths:
            issues.append({"kind": "ambiguous_document_records", "source_ref": canonical})
            continue
        peers = [
            peer for peer in sources if isinstance(peer, dict) and _expected_path(peer) == path
            and isinstance(peer.get("text"), str)
            and substantive_body(peer["text"]).split() == body.split()
        ]
        if len(peers) != 1:
            issues.append({"kind": "ambiguous_section_body", "source_ref": canonical})
            continue
        snippets = by_path.get(path, [])
        returned_text, origins = _cover(snippets, body)
        if returned_text is None:
            issues.append({
                "kind": "incomplete_returned_body" if snippets else "missing_document",
                "source_ref": canonical,
            })
            continue
        mapping = {
            "source_ref": canonical, "coverage_mode": "full_substantive_body",
            "returned_text": returned_text,
            "observed_origins": [{
                key: snippets[index][key] for key in (
                    "call_index", "ref_id", "uri", "blob_url", "uid", "snippet_sha256",
                )
            } for index in origins],
        }
        mappings.append(mapping)
        source_aliases = {canonical}
        for record in snippets:
            uri = record["uri"]
            # A document URI cites all actual chunks from that document.
            parsed = urlsplit(uri)
            slug = canonical.split("#", 1)[-1]
            if not parsed.fragment or parsed.fragment == slug:
                aliases[uri].add(canonical)
            document_uri = parsed._replace(query="", fragment="").geturl()
            aliases[document_uri].add(canonical)
            aliases[document_uri + "#" + slug].add(canonical)
            individual, _ = _cover([record], body)
            if (
                individual is not None
                and len(id_paths[(record["call_index"], record["ref_id"])]) == 1
            ):
                number = record["ref_id"]
                for alias in (f"ref_id:{number}", f"[ref_id:{number}]", f"ref_id={number}"):
                    aliases[alias].add(canonical)
                aliases[f"call:{record['call_index']}/ref_id:{number}"].add(canonical)
        normalized_sources.append({
            "source_ref": canonical, "text": returned_text,
            "adapter_version": VERSION, "coverage_mode": "full_substantive_body",
            "aliases": source_aliases,
            "observed_origins": mapping["observed_origins"],
        })
    # An id that points to another document in another call is ambiguous even if that
    # document has no pinned section; narrowing to gold must not hide the collision.
    global_id_paths: dict[str, set[str]] = defaultdict(set)
    for record in records:
        global_id_paths[record["ref_id"]].add(record["document_path"])
    ambiguous_aliases = {alias: sorted(targets) for alias, targets in aliases.items()
                         if len(targets) != 1}
    for number, paths in global_id_paths.items():
        if len(paths) > 1:
            for alias in (f"ref_id:{number}", f"[ref_id:{number}]", f"ref_id={number}"):
                if alias in aliases:
                    ambiguous_aliases[alias] = sorted(paths)
    unambiguous = {
        alias: next(iter(targets)) for alias, targets in aliases.items()
        if len(targets) == 1 and alias not in ambiguous_aliases
    }
    for source in normalized_sources:
        source["aliases"] = sorted(
            alias for alias, canonical in unambiguous.items()
            if canonical == source["source_ref"]
        )
    if ambiguous_aliases:
        issues.append({"kind": "ambiguous_aliases", "aliases": ambiguous_aliases})
    normalized = [{
        "name": TOOL, "status": "succeeded" if records else "failed",
        "content": {"sources": normalized_sources},
        "adapter_version": VERSION,
        "raw_tool_messages": raw,
        "raw_sha256": _sha(raw),
    }]
    return {
        "version": VERSION, "tool_messages": normalized,
        "raw_tool_messages": raw, "raw_sha256": _sha(raw),
        "reference_snippets": records, "mappings": mappings,
        "citation_aliases": unambiguous, "ambiguous_aliases": ambiguous_aliases,
        "issues": issues,
        "ready": len(mappings) == len(sources) and bool(sources),
    }


def audit_adapter(
    tool_messages: list[dict[str, Any]] | dict[str, Any],
    *,
    reference: dict[str, Any],
    allowed_hosts: set[str] | None = None,
) -> dict[str, Any]:
    """Recompute the adapter audit from raw retrieval, not a model-authored attestation."""
    result = normalize_tool_messages(
        tool_messages, reference=reference, allowed_hosts=allowed_hosts,
    )
    return {
        key: result[key] for key in (
            "version", "raw_sha256", "ready", "mappings",
            "citation_aliases", "ambiguous_aliases", "issues",
        )
    }
