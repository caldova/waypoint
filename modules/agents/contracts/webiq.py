"""WebIQ public-web evidence, dispatched through the contracts-toolbox lane.

The WebIQ API key lives only in the ``contracts-webiq-mcp`` Foundry project
connection; the toolbox injects it as ``x-apikey``. This agent authenticates to
the toolbox with its own identity and never sees the key.
"""

from __future__ import annotations

import json
from typing import Any

from castia import resolve_toolbox_endpoint
from castia.inference.tools import Tool

from toolbox import call_toolbox_tool

# Castia stamps Tool.kind onto the execute_tool span as gen_ai.tool.type.
WEB_IQ = "web_iq"
WEB_IQ_SEARCH = "web_iq_search"
WEB_IQ_BROWSE = "web_iq_browse"
_LANE = "contracts-webiq-mcp"
_SNIPPET_CHARS = 600
_MAX_RESULTS = 8
_BROWSE_CHARS = 8000


def webiq_tools() -> list[Tool]:
    if not resolve_toolbox_endpoint():
        return []
    return [
        Tool(
            name=WEB_IQ_SEARCH,
            description=(
                "Search the public web (or recent news) with WebIQ for external "
                "context: supplier background, market pricing benchmarks, "
                "regulatory or recall notices. Never use it for what a "
                "contract or Caldova policy says; use foundry_iq_retrieve."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Specific web search query."},
                    "news": {
                        "type": "boolean",
                        "description": "Search recent news articles instead of web pages.",
                    },
                    "max_results": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": _MAX_RESULTS,
                        "description": "Number of results (default 5).",
                    },
                },
                "required": ["query"],
                "additionalProperties": False,
            },
            impl=_search,
            kind=WEB_IQ,
        ),
        Tool(
            name=WEB_IQ_BROWSE,
            description=(
                "Read one public web page found by web_iq_search when its "
                "snippet is not enough to support a claim."
            ),
            parameters={
                "type": "object",
                "properties": {"url": {"type": "string", "description": "Page URL."}},
                "required": ["url"],
                "additionalProperties": False,
            },
            impl=_browse,
            kind=WEB_IQ,
        ),
    ]


async def _search(
    activity: Any, *, query: str, news: bool = False, max_results: int = 5
) -> dict[str, Any]:
    del activity
    cleaned = str(query or "").strip()
    if not cleaned:
        return {"ok": False, "error": "query is required."}
    try:
        count = max(1, min(int(max_results or 5), _MAX_RESULTS))
    except (TypeError, ValueError):
        return {"ok": False, "error": "max_results must be an integer."}
    vertical = "news" if news else "web"
    result = await call_toolbox_tool(
        f"{_LANE}___{vertical}",
        {
            "query": cleaned[:1000],
            "maxResults": count,
            "contentFormat": "text",
            "maxLength": _SNIPPET_CHARS,
        },
    )
    if not result.get("ok"):
        return result
    body = _first_json(result)
    if body is None:
        return {"ok": False, "error": "WebIQ returned no parseable result."}
    items = body.get("newsResults" if news else "webResults") or []
    return {
        "ok": True,
        "source": "webiq",
        "vertical": vertical,
        "results": [
            {
                "title": item.get("title"),
                "url": item.get("url"),
                "snippet": item.get("content"),
                "updated": item.get("lastUpdatedAt") or item.get("datePublished"),
            }
            for item in items[:count]
            if isinstance(item, dict)
        ],
    }


async def _browse(activity: Any, *, url: str) -> dict[str, Any]:
    del activity
    cleaned = str(url or "").strip()
    if not cleaned.lower().startswith(("http://", "https://")):
        return {"ok": False, "error": "url must be an http(s) URL."}
    result = await call_toolbox_tool(
        f"{_LANE}___browse",
        {"url": cleaned, "maxLength": _BROWSE_CHARS, "contentFormat": "markdown"},
    )
    if not result.get("ok"):
        return result
    body = _first_json(result)
    if body is None:
        return {"ok": False, "error": "WebIQ returned no parseable result."}
    return {
        "ok": True,
        "source": "webiq",
        "url": body.get("url") or cleaned,
        "title": body.get("title"),
        "content": body.get("content"),
    }


def _first_json(result: dict[str, Any]) -> dict[str, Any] | None:
    for part in result.get("content") or []:
        if isinstance(part, dict) and part.get("type") == "text":
            try:
                parsed = json.loads(part.get("text") or "")
            except ValueError:
                continue
            if isinstance(parsed, dict):
                return parsed
    structured = result.get("structured_content")
    return structured if isinstance(structured, dict) else None
