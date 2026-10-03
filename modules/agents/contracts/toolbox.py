"""FoundryIQ toolbox wiring for the Contracts autopilot."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

import httpx
from castia import resolve_toolbox_endpoint, toolbox_token
from castia.inference.tools import Tool

# Model-facing name; Castia names the span "execute_tool foundry_iq_retrieve".
FOUNDRY_IQ_TOOL_NAME = "foundry_iq_retrieve"
# Underlying toolbox MCP tool the call is dispatched to.
_KB_TOOL_NAME = "contracts-kb-mcp___knowledge_base_retrieve"
# Castia stamps Tool.kind onto the execute_tool span as gen_ai.tool.type.
FOUNDRY_IQ = "foundry_iq"
_KB_TOOL_DESCRIPTION = (
    "Retrieve grounding passages from Caldova's governing contracts and "
    "billing/quality policies - statements of work, rate cards, and "
    "release/billability policies. Use for questions about what a supplier's "
    "contract or a Caldova policy permits, requires, or prohibits."
)
_KB_QUERY_GUIDANCE = (
    "A specific, self-contained contract or billing-policy question naming the "
    "supplier and the fee or term at issue."
)


def is_toolbox_configured() -> bool:
    return resolve_toolbox_endpoint() is not None


def foundryiq_toolbox_tools() -> list[Tool]:
    """Optimizer-visible baseline: the same function tool the model sees."""
    return [_foundryiq_tool()]


def foundryiq_runtime_tools(
    tool_definitions: Sequence[dict[str, Any]] = (),
) -> list[Tool]:
    """Client-side FoundryIQ tool so each call gets a local ``execute_tool`` span.

    Folds in any optimized wording, then dispatches the call to the toolbox
    MCP endpoint from the hosted agent.
    """
    if not resolve_toolbox_endpoint():
        return []
    return [_foundryiq_tool(_optimized_function(tool_definitions))]


def _foundryiq_tool(optimized: dict[str, Any] | None = None) -> Tool:
    optimized = optimized or {}
    return Tool(
        name=FOUNDRY_IQ_TOOL_NAME,
        description=optimized.get("description") or _KB_TOOL_DESCRIPTION,
        parameters=_runtime_parameters(optimized.get("parameters")),
        impl=_call_foundryiq_toolbox,
        kind=FOUNDRY_IQ,
    )


def _optimized_function(tool_definitions: Sequence[dict[str, Any]]) -> dict[str, Any]:
    for item in tool_definitions:
        if not isinstance(item, dict):
            continue
        function = item.get("function")
        if isinstance(function, dict) and function.get("name") == FOUNDRY_IQ_TOOL_NAME:
            return function
        if item.get("name") == FOUNDRY_IQ_TOOL_NAME:
            return item
    return {}


def _runtime_parameters(optimized: object | None) -> dict[str, Any]:
    query_description = _KB_QUERY_GUIDANCE
    if isinstance(optimized, dict):
        properties = optimized.get("properties")
        if isinstance(properties, dict):
            query = properties.get("query")
            if isinstance(query, dict) and query.get("description"):
                query_description = str(query["description"])

    return {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": query_description},
        },
        "required": ["query"],
        "additionalProperties": False,
    }


async def _call_foundryiq_toolbox(activity: Any, *, query: str) -> dict[str, Any]:
    del activity
    cleaned = str(query or "").strip()
    if not cleaned:
        return {"ok": False, "error": "query is required."}
    return await call_toolbox_tool(_KB_TOOL_NAME, {"query_variants": [cleaned[:400]]})


async def call_toolbox_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Call one contracts-toolbox MCP tool; errors are returned, not raised."""
    endpoint = resolve_toolbox_endpoint()
    if not endpoint:
        return {"ok": False, "error": "Contracts toolbox endpoint is not configured."}

    payload = {
        "jsonrpc": "2.0",
        "id": str(uuid.uuid4()),
        "method": "tools/call",
        "params": {"name": name, "arguments": arguments},
    }
    headers = {
        "Authorization": "Bearer " + await toolbox_token(),
        "Accept": "application/json",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post(endpoint, headers=headers, json=payload)
            data = response.json()
    except Exception as exc:  # noqa: BLE001 - tool failures are fed back to the model.
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    if not isinstance(data, dict):
        return {"ok": False, "error": "Toolbox returned a non-object response."}
    if response.is_error:
        return {"ok": False, "error": {"status_code": response.status_code, "body": data}}
    if data.get("error"):
        return {"ok": False, "error": data["error"]}

    result = data.get("result")
    if not isinstance(result, dict):
        return {"ok": False, "error": "Toolbox response did not include a result."}

    return {
        "ok": not bool(result.get("isError")),
        "content": result.get("content", []),
        "structured_content": result.get("structuredContent"),
    }