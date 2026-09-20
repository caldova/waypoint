"""FoundryIQ toolbox wiring for the Contract Policy Expert."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from castia import (
    resolve_toolbox_endpoint,
    toolbox_mcp_tool,
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
    "Exactly one complete natural-language contract or policy question naming "
    "the supplier, term, fee, or invoice condition at issue."
)


def _foundryiq_spec(endpoint: str, *, token: str | None = None) -> dict[str, Any]:
    spec = toolbox_mcp_tool(
        endpoint,
        server_label="foundryiq",
        allowed_tools=(_KB_TOOL_NAME,),
        token=token,
        descriptions={_KB_TOOL_NAME: _KB_TOOL_DESCRIPTION},
        param_guidance={_KB_TOOL_NAME: {"query_variants": _KB_QUERY_GUIDANCE}},
    )
    assert spec is not None
    return spec


def foundryiq_toolbox_tools() -> list[dict[str, Any]]:
    """Optimizer-visible baseline for the FoundryIQ MCP tool."""
    return [_foundryiq_spec(_OPTIMIZER_ENDPOINT)]


def is_foundryiq_configured() -> bool:
    return bool(resolve_toolbox_endpoint())


def _optimized_guidance(
    tool_definitions: Sequence[dict[str, Any]] = (),
) -> dict[str, str]:
    descriptions = {_KB_TOOL_NAME: _KB_TOOL_DESCRIPTION}
    for tool in tool_definitions:
        function = tool.get("function", {})
        if function.get("name") != _KB_TOOL_NAME:
            continue
        if function.get("description"):
            descriptions[_KB_TOOL_NAME] = str(function["description"])
    return descriptions


async def foundryiq_toolbox_preflight() -> object:
    from castia.prompty import toolbox_preflight

    return await toolbox_preflight((_KB_TOOL_NAME,))


async def foundryiq_prompty_tool_definitions(
    tool_definitions: Sequence[dict[str, Any]] = (),
    *,
    client: object | None = None,
) -> list[object]:
    from castia.prompty import ToolboxMcpClient, toolbox_prompty_tools_from_mcp

    return await toolbox_prompty_tools_from_mcp(
        (_KB_TOOL_NAME,),
        client=client if isinstance(client, ToolboxMcpClient) else None,
        descriptions=_optimized_guidance(tool_definitions),
    )


def foundryiq_tool_functions(*, client: object | None = None) -> dict[str, object]:
    from castia.prompty import ToolboxMcpClient, register_toolbox_function

    resolved_client = client if isinstance(client, ToolboxMcpClient) else ToolboxMcpClient()
    return {
        _KB_TOOL_NAME: register_toolbox_function(_KB_TOOL_NAME, client=resolved_client)
    }
