"""Foundry toolbox wiring for the contract-agent.

The workhorse only needs the live FoundryIQ lane today: the published
``contract-toolbox`` endpoint and its contract/policy
``knowledge_base_retrieve`` tool. Castia owns the MCP spec shape, endpoint
composition, token minting, and optimizer sidecar validation; this module keeps
only Waypoint-specific tool selection and wording.
"""

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
    "Retrieve grounding passages from Caldova's governing contracts and "
    "billing/quality policies - statements of work, rate cards, and "
    "release/billability policies. Use for any question about what a supplier's "
    "contract or a Caldova policy permits, requires, or prohibits: whether a "
    "fee is billable, rate or threshold lookups, and clause interpretation. "
    "Returns cited source passages; ground every contractual claim in them and "
    "never assert a term this tool does not return."
)
_KB_QUERY_GUIDANCE = (
    "A specific, self-contained contract or billing-policy question naming the "
    "supplier and the fee or term at issue (e.g. 'Aster Ridge SOW: is a batch "
    "release administration fee billable for a rejected batch?'). Prefer the "
    "contractual vocabulary on the invoice or finding over paraphrase."
)


def is_toolbox_configured() -> bool:
    return resolve_toolbox_endpoint() is not None


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


async def _runtime_foundryiq_spec(
    tool_definitions: Sequence[dict[str, Any]] = (),
) -> dict[str, Any] | None:
    endpoint = resolve_toolbox_endpoint()
    if not endpoint:
        return None
    spec = _foundryiq_spec(endpoint, token=await toolbox_token())
    return apply_optimized_toolbox_tools(spec, list(tool_definitions))


async def read_specs(tool_definitions: Sequence[dict[str, Any]] = ()) -> list[dict[str, Any]]:
    spec = await _runtime_foundryiq_spec(tool_definitions)
    return [spec] if spec else []


async def assurance_specs(
    tool_definitions: Sequence[dict[str, Any]] = (),
) -> list[dict[str, Any]]:
    return await read_specs(tool_definitions)
