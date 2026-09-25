"""Waypoint Contracts — Teams-first contract intake autopilot stub."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from castia import (
    Agent,
    Message,
    Teams,
    action_chips,
    configured_model,
    load_agent_config,
)
from castia.inference.tools import Tool
from dotenv import load_dotenv

from tools import contracts_tools

load_dotenv()

app = Agent(name="contracts")

_config = load_agent_config(Path(__file__).resolve().parent / ".agent_configs")
chat_model = configured_model(_config)

app.tools(contracts_tools)

_TOOL_BASE: list[Tool | dict[str, Any]] = [*contracts_tools()]
_TOOLS = _config.apply_tools(_TOOL_BASE)

_FOLLOWUPS = (
    "What can Contracts do right now?",
    "Check the Contracts inbox",
    "Find the last contract I sent",
)


@app.responses()
async def work(text: str) -> str:
    return await _respond(text)


@app.invocations()
async def invoked(text: str) -> str:
    return await _respond(text)


@app.activity(Teams.direct, Teams.group, Teams.channel_mention)
async def ask(msg: Message | str) -> str | None:
    text = msg.text if hasattr(msg, "text") else str(msg)
    answer = await _respond(text)
    if hasattr(msg, "say"):
        await msg.say(answer, ai_generated=True, attachments=[action_chips(*_FOLLOWUPS)])
        return None
    return answer


async def _respond(text: str) -> str:
    if os.environ.get("FOUNDRY_PROJECT_ENDPOINT"):
        model = chat_model()
        return await model.respond_with_tools(text, tools=_TOOLS, activity=None)
    return await _fixture_response(text)


async def _fixture_response(text: str) -> str:
    """Deterministic no-model path for local playground scaffold testing."""

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


def _format_fixture_result(summary: str, result: dict[str, Any]) -> str:
    return (
        f"{summary}\n\n"
        "**Fixture result:**\n"
        "```json\n"
        f"{json.dumps(result, indent=2, sort_keys=True)}\n"
        "```"
    )


if __name__ == "__main__":
    app.run()
