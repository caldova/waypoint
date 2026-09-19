"""FoundryIQ-only Contract Policy Expert for grounded contract Q&A."""

from __future__ import annotations

from pathlib import Path

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
from dotenv import load_dotenv

from toolbox import foundryiq_specs, foundryiq_toolbox_tools

load_dotenv(Path(__file__).resolve().parent / ".env", override=True)

app = Agent(name="contract-policy-expert")

_config = load_agent_config(Path(__file__).resolve().parent / ".agent_configs")
chat_model = configured_model(_config)
_CHAT_MODEL_DEPENDENCY = Depends(chat_model)

_FOLLOWUPS = (
    "What does Aster Ridge's contract say about rejected batch fees?",
    "Which policy governs invoice approval evidence?",
)

app.tools(foundryiq_toolbox_tools)


@app.responses()
async def reply(text: str, model: Model = _CHAT_MODEL_DEPENDENCY) -> str:
    specs = await foundryiq_specs(_config.tool_definitions)
    if not specs:
        return (
            "FoundryIQ is not configured. Set TOOLBOX_NAME and the matching "
            "TOOLBOX_<NAME>_MCP_ENDPOINT."
        )
    return await model.respond_with_tools(text, tools=[], activity=None, extra_specs=specs)


@app.activity(Teams.direct, Teams.group, Teams.channel_mention)
async def ask(msg: Message, model: Model = _CHAT_MODEL_DEPENDENCY) -> None:
    specs = await foundryiq_specs(_config.tool_definitions)
    if not specs:
        await msg.say(
            "FoundryIQ is not configured. Set TOOLBOX_NAME and the matching "
            "TOOLBOX_<NAME>_MCP_ENDPOINT.",
            ai_generated=True,
        )
        return
    answer = await model.respond_with_tools(
        msg.text, tools=[], activity=None, extra_specs=specs
    )
    await msg.say(answer, ai_generated=True, attachments=[action_chips(*_FOLLOWUPS)])


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8088)
