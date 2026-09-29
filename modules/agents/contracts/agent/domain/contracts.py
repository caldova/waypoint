"""Contract fixture response path shared by non-model protocol handlers."""

from __future__ import annotations

import json

from agent.tools.contracts import contracts_tools


async def fixture_response(text: str) -> str:
    normalized = text.lower()
    tool_by_name = {tool.name: tool.impl for tool in contracts_tools()}

    if "draft" in normalized or "report" in normalized or "brief" in normalized:
        result = await tool_by_name["draft_contract_report"](
            None,
            report_type="contract_brief",
        )
        return _format_fixture_result(
            "I drafted a local fixture contract brief. This is not a SharePoint document and it was not shared.",
            result,
        )

    if "last contract" in normalized or "latest contract" in normalized:
        result = await tool_by_name["get_last_contract"](None)
        artifact = result.get("artifact", {}) if isinstance(result, dict) else {}
        title = artifact.get("title", "the local fixture contract")
        return _format_fixture_result(
            f"The latest local fixture contract is **{title}**.",
            result,
        )

    if "inbox" in normalized or "poll" in normalized or "email" in normalized:
        result = await tool_by_name["poll_contracts_inbox"](None)
        return _format_fixture_result(
            "I ran the local fixture inbox path. No mailbox was read.",
            result,
        )

    result = await tool_by_name["get_contracts_capabilities"](None)
    return _format_fixture_result(
        "Contracts is running in local fixture mode because `FOUNDRY_PROJECT_ENDPOINT` is not configured.",
        result,
    )


def _format_fixture_result(summary: str, result: dict) -> str:
    return (
        f"{summary}\n\n"
        "**Fixture result:**\n"
        "```json\n"
        f"{json.dumps(result, indent=2, sort_keys=True)}\n"
        "```"
    )

