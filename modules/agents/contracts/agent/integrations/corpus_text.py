"""Fill contract/policy text from the FoundryIQ knowledge base.

The Caldova API returns contract and policy records by URI only. The knowledge
base indexes the same corpus markdown files, so a retrieval's reference
snippets can be matched back to those records by file name.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from toolbox import KB_TOOL_NAME, call_toolbox_tool, is_toolbox_configured

logger = logging.getLogger(__name__)
_MAX_VARIANTS = 3
_MAX_QUERY_CHARS = 400
# Clause text is optional; never hold a Teams turn longer than this for it.
_DEADLINE_SECONDS = 45.0


def document_file(document: dict[str, Any]) -> str:
    """Corpus file name for a contract or policy record ('' when unknown)."""
    metadata = (
        document.get("metadata") if isinstance(document.get("metadata"), dict) else {}
    )
    for value in (
        document.get("uri"),
        metadata.get("uri"),
        metadata.get("source_uri"),
        metadata.get("document_uri"),
    ):
        if isinstance(value, str) and value.strip():
            return value.split("?", 1)[0].rstrip("/").rsplit("/", 1)[-1].lower()
    return ""


async def fill_corpus_text(
    context: dict[str, Any] | None, findings: list[dict[str, Any]]
) -> int:
    """Set ``text_chunks``/``text`` on context contracts/policies that lack text.

    Returns how many documents were filled; stops early at the deadline.
    """
    if not isinstance(context, dict) or not is_toolbox_configured():
        return 0
    wanted: dict[str, list[dict[str, Any]]] = {}
    for key in ("contract_documents", "policies"):
        for document in context.get(key) or []:
            if not isinstance(document, dict) or document.get("text"):
                continue
            name = document_file(document)
            if name:
                wanted.setdefault(name, []).append(document)
    if not wanted:
        return 0

    filled = 0

    async def fill() -> None:
        nonlocal filled
        filled += _apply(wanted, await _retrieve(_queries(context, findings)))
        if wanted:
            titles = [
                str(docs[0].get("title") or docs[0].get("name") or "")
                for docs in wanted.values()
            ]
            filled += _apply(
                wanted, await _retrieve([t for t in titles if t][:_MAX_VARIANTS])
            )

    try:
        await asyncio.wait_for(fill(), timeout=_DEADLINE_SECONDS)
    except TimeoutError:
        logger.warning(
            "FoundryIQ clause retrieval hit the %ss deadline", _DEADLINE_SECONDS
        )
    return filled


async def _retrieve(queries: list[str]) -> dict[str, list[str]]:
    if not queries:
        return {}
    for _ in range(2):
        try:
            result = await call_toolbox_tool(KB_TOOL_NAME, {"query_variants": queries})
        except Exception:  # Clauses are optional; never block the document.
            logger.warning("FoundryIQ clause retrieval failed", exc_info=True)
            continue
        if result.get("ok"):
            return _reference_texts(result.get("content"))
    return {}


def _apply(wanted: dict[str, list[dict[str, Any]]], texts: dict[str, list[str]]) -> int:
    filled = 0
    for name, chunks in texts.items():
        for document in wanted.pop(name, []):
            document["text_chunks"] = list(chunks)
            document["text"] = "\n\n".join(chunks)
            document["content_source"] = "foundry_iq"
            filled += 1
    return filled


def _queries(context: dict[str, Any], findings: list[dict[str, Any]]) -> list[str]:
    supplier = ""
    invoice = context.get("invoice")
    if isinstance(invoice, dict) and isinstance(invoice.get("supplier"), dict):
        supplier = str(invoice["supplier"].get("name") or "")
    queries: list[str] = []
    for finding in findings:
        metadata = (
            finding.get("metadata") if isinstance(finding.get("metadata"), dict) else {}
        )
        basis = finding.get("basis_summary") or metadata.get("basis_summary") or ""
        text = " ".join(
            part
            for part in (supplier, str(finding.get("summary") or ""), str(basis))
            if part
        )
        if text.strip():
            queries.append(text.strip()[:_MAX_QUERY_CHARS])
    titles = [
        str(document.get("title") or document.get("name") or "")
        for key in ("contract_documents", "policies")
        for document in context.get(key) or []
        if isinstance(document, dict)
    ]
    if any(titles):
        queries.append("; ".join(title for title in titles if title)[:_MAX_QUERY_CHARS])
    return queries[:_MAX_VARIANTS] or ["Caldova contract and billing policy clauses"]


def _reference_texts(content: Any) -> dict[str, list[str]]:
    """Reference snippets keyed by corpus file name; chunks stay separate (order unknown)."""
    chunks: dict[str, list[str]] = {}
    for item in content or []:
        if not isinstance(item, dict) or item.get("type") != "text":
            continue
        try:
            reference = json.loads(item.get("text") or "")
        except (TypeError, ValueError):
            continue
        if not isinstance(reference, dict) or reference.get("kind") != "reference":
            continue
        source = (
            reference.get("sourceData")
            if isinstance(reference.get("sourceData"), dict)
            else {}
        )
        snippet = source.get("snippet")
        name = document_file({"uri": source.get("blob_url") or reference.get("uri")})
        if not name or not isinstance(snippet, str) or not snippet.strip():
            continue
        text = snippet.replace("\r\n", "\n").strip()
        if text not in chunks.setdefault(name, []):
            chunks[name].append(text)
    return chunks
