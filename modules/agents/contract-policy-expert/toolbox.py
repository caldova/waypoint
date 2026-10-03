"""FoundryIQ toolbox wiring for the Contract Policy Expert."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

from castia import (
    resolve_toolbox_endpoint,
    toolbox_mcp_tool,
    toolbox_token,
)
from castia.inference.tools import Tool

import httpx
from opentelemetry import trace

_OPTIMIZER_ENDPOINT = "https://example.invalid/toolboxes/contract-toolbox/mcp?api-version=v1"
_KB_TOOL_NAME = "contracts-kb-mcp___knowledge_base_retrieve"
# Castia stamps Tool.kind onto the execute_tool span as gen_ai.tool.type.
FOUNDRY_IQ = "foundry_iq"
# Matches the contracts agent's span; its tuned MAI model still calls _KB_TOOL_NAME.
FOUNDRY_IQ_SPAN_NAME = "execute_tool foundry_iq_retrieve"
_KB_TOOL_DESCRIPTION = (
    "Look up helpful contract, policy, or invoice-review context for a "
    "supplier billing question."
)
_KB_QUERY_GUIDANCE = (
    "A short search question about the supplier invoice or policy topic."
)


def _foundryiq_spec(endpoint: str, *, token: str | None = None) -> dict[str, Any]:
    spec = toolbox_mcp_tool(
        endpoint,
        server_label="foundryiq",
        allowed_tools=(_KB_TOOL_NAME,),
        token=token,
        descriptions={_KB_TOOL_NAME: _KB_TOOL_DESCRIPTION},
        param_guidance={_KB_TOOL_NAME: {"query": _KB_QUERY_GUIDANCE}},
    )
    assert spec is not None
    return spec


def foundryiq_toolbox_tools() -> list[dict[str, Any]]:
    """Optimizer-visible baseline for the FoundryIQ MCP tool."""
    return [_foundryiq_spec(_OPTIMIZER_ENDPOINT)]


def foundryiq_runtime_tools(
    tool_definitions: Sequence[dict[str, Any]] = (),
) -> list[Tool]:
    """Runtime function-tool wrapper for the FoundryIQ toolbox MCP lane.

    MAI RFT deployments currently handle ordinary Responses function tools, but
    not the server-side `type: mcp` toolbox spec used by the optimizer baseline.
    Keep the same model-visible tool name and optimized wording, then dispatch
    the call to the toolbox MCP endpoint from the hosted agent.
    """
    if not resolve_toolbox_endpoint():
        return []

    optimized = _optimized_function(tool_definitions)
    description = optimized.get("description") or _KB_TOOL_DESCRIPTION
    return [
        Tool(
            name=_KB_TOOL_NAME,
            description=description,
            parameters=_runtime_parameters(optimized.get("parameters")),
            impl=_call_foundryiq_toolbox,
            kind=FOUNDRY_IQ,
        )
    ]


def _optimized_function(tool_definitions: Sequence[dict[str, Any]]) -> dict[str, Any]:
    for item in tool_definitions:
        if not isinstance(item, dict):
            continue
        function = item.get("function")
        if isinstance(function, dict) and function.get("name") == _KB_TOOL_NAME:
            return function
        if item.get("name") == _KB_TOOL_NAME:
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
            "query": {
                "type": "string",
                "description": query_description,
            }
        },
        "required": ["query"],
        "additionalProperties": False,
    }


async def _call_foundryiq_toolbox(activity: Any, **kwargs: Any) -> dict[str, Any]:
    del activity
    # Model-facing name stays the trained KB name; only the span is renamed.
    trace.get_current_span().update_name(FOUNDRY_IQ_SPAN_NAME)
    query = kwargs.get("query")
    endpoint = resolve_toolbox_endpoint()
    if not endpoint:
        return {"ok": False, "error": "FoundryIQ toolbox endpoint is not configured."}

    cleaned = str(query or "").strip()
    if not cleaned:
        return {"ok": False, "error": "query is required."}

    payload = {
        "jsonrpc": "2.0",
        "id": str(uuid.uuid4()),
        "method": "tools/call",
        "params": {
            "name": _KB_TOOL_NAME,
            "arguments": {"query_variants": [cleaned[:400]]},
        },
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
        return {
            "ok": False,
            "error": {
                "status_code": response.status_code,
                "body": data,
            },
        }
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
