"""Waypoint Contracts — Teams-first contract intake autopilot stub."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from castia import (
    Agent,
    Depends,
    Message,
    Model,
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
_CHAT_MODEL_DEPENDENCY = Depends(chat_model)

app.tools(contracts_tools)

_TOOL_BASE: list[Tool | dict[str, Any]] = [*contracts_tools()]
_TOOLS = _config.apply_tools(_TOOL_BASE)

_FOLLOWUPS = (
    "What can Contracts do right now?",
    "Check the Contracts inbox",
    "Find the last contract I sent",
)


@app.responses()
async def work(text: str, model: Model = _CHAT_MODEL_DEPENDENCY) -> str:
    return await model.respond_with_tools(text, tools=_TOOLS, activity=None)


@app.invocations()
async def invoked(text: str, model: Model = _CHAT_MODEL_DEPENDENCY) -> str:
    return await model.respond_with_tools(text, tools=_TOOLS, activity=None)


@app.activity(Teams.direct, Teams.group, Teams.channel_mention)
async def ask(msg: Message, model: Model = _CHAT_MODEL_DEPENDENCY) -> None:
    answer = await model.respond_with_tools(msg.text, tools=_TOOLS, activity=None)
    await msg.say(answer, ai_generated=True, attachments=[action_chips(*_FOLLOWUPS)])


if __name__ == "__main__":
    app.run()
