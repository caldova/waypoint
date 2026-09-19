"""FoundryIQ toolbox wiring for the Contract Policy Expert."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from castia import (
    apply_optimized_toolbox_tools,
    resolve_toolbox_endpoint,
    toolbox_mcp_tool,
    toolbox_token,
)

_OPTIMIZER_ENDPOINT = "https://example.invalid/toolboxes/contract-toolbox/mcp?api-version=v1"
_KB_TOOL_NAME = "contracts-kb-mcp___knowledge_base_retrieve"
_KB_TOOL_DESCRIPTION = (
    "Retrieve cited grounding passages from Caldova contracts and billing or "
    "quality policies. Use this for every material contract or policy claim. "
    "If the tool does not return support, say the evidence is missing rather "
    "than filling the gap."
)
_KB_QUERY_GUIDANCE = (
    "A specific contract or policy question naming the supplier, term, fee, "
    "or invoice condition at issue."
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


async def foundryiq_specs(
    tool_definitions: Sequence[dict[str, Any]] = (),
) -> list[dict[str, Any]]:
    endpoint = resolve_toolbox_endpoint()
    if not endpoint:
        return []
    spec = _foundryiq_spec(endpoint, token=await toolbox_token())
    return [apply_optimized_toolbox_tools(spec, list(tool_definitions))]
