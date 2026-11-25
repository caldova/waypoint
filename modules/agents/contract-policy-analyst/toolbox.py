"""Expert-compatible FoundryIQ dispatch with optimizer/runtime schema parity."""

from __future__ import annotations

import uuid
import hashlib
import json
from collections.abc import Sequence
from typing import Any

import httpx
from castia import (
    resolve_toolbox_endpoint,
    toolbox_token,
)
from castia.inference.tools import Tool
from opentelemetry import trace

from retrieval_audit import record_tool

_KB_TOOL_NAME = "contracts-kb-mcp___knowledge_base_retrieve"
# Telemetry label for the execute_tool span's gen_ai.tool.type. Castia 0.10 has
# no Tool.kind, so the impl stamps it onto the active execute_tool span.
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


def foundryiq_toolbox_tools() -> list[Tool]:
    """Pure provider: expose precisely the function schema used by every arm."""
    return [_runtime_tool({})]


def _runtime_tool(optimized: dict[str, Any]) -> Tool:
    return Tool(
        name=_KB_TOOL_NAME,
        description=optimized.get("description") or _KB_TOOL_DESCRIPTION,
        parameters=_runtime_parameters(optimized.get("parameters")),
        impl=_call_foundryiq_toolbox,
        kind=FOUNDRY_IQ,
    )


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
    if tool_definitions:
        validate_tool_definitions(tool_definitions)
    return [_runtime_tool(optimized)]


def validate_tool_definitions(tool_definitions: Sequence[dict[str, Any]]) -> None:
    """Candidates may change wording, not silently change the dispatched schema."""
    function = _optimized_function(tool_definitions)
    if len(tool_definitions) != 1 or not function:
        raise ValueError("Exactly one FoundryIQ knowledge_base_retrieve tool is required.")
    item = tool_definitions[0]
    expected_fields = (
        {"type", "function"} if "function" in item
        else {"type", "name", "description", "parameters"}
    )
    if item.get("type") != "function" or set(item) - expected_fields:
        raise ValueError("Candidate changed the function-tool envelope.")
    description = function.get("description")
    if not isinstance(description, str) or not description.strip():
        raise ValueError("Tool description must be non-empty text.")
    parameters = function.get("parameters")
    if parameters != _runtime_parameters(parameters):
        raise ValueError("Candidate changed the FoundryIQ query schema, not just its description.")
    if set(function) - {"name", "description", "parameters"}:
        raise ValueError("Candidate contains unsupported function fields.")


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
    result = await _dispatch_foundryiq_toolbox(activity, **kwargs)
    record_tool(kwargs.get("query"), result)
    return result


async def _dispatch_foundryiq_toolbox(activity: Any, **kwargs: Any) -> dict[str, Any]:
    # Stamp before binding arguments so malformed calls are still labeled.
    del activity
    span = trace.get_current_span()
    span.set_attribute("gen_ai.tool.type", FOUNDRY_IQ)
    # Model-facing name stays the trained KB name; only the span is renamed.
    span.update_name(FOUNDRY_IQ_SPAN_NAME)
    query = kwargs.get("query")
    endpoint = resolve_toolbox_endpoint()
    if not endpoint:
        return {"ok": False, "error": "FoundryIQ toolbox endpoint is not configured."}

    cleaned = str(query or "").strip()
    if not cleaned:
        return {"ok": False, "error": "query is required."}
    span.set_attribute("cpa.retrieval.query", cleaned[:400])

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

    returned = {
        "ok": not bool(result.get("isError")),
        "content": result.get("content", []),
        "structured_content": result.get("structuredContent"),
    }
    span.set_attribute("cpa.retrieval.ok", returned["ok"])
    span.set_attribute(
        "cpa.retrieval.sha256",
        hashlib.sha256(json.dumps(returned, sort_keys=True).encode("utf-8")).hexdigest(),
    )
    return returned
