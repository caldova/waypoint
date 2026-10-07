"""FoundryIQ-only Contract Policy Expert for grounded contract Q&A."""

import os
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

from castia_foundry_telemetry import configure_foundry_local_telemetry
from toolbox import foundryiq_runtime_tools, foundryiq_toolbox_tools

load_dotenv(Path(__file__).resolve().parent / ".env", override=True)
configure_foundry_local_telemetry(agent_name="contract-policy-expert")

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
    tools = foundryiq_runtime_tools(_config.tool_definitions)
    if not tools:
        return (
            "FoundryIQ is not configured. Set TOOLBOX_NAME and the matching "
            "TOOLBOX_<NAME>_MCP_ENDPOINT."
        )
    return await model.respond_with_tools(text, tools=tools, activity=None)


@app.activity(Teams.direct, Teams.group, Teams.channel_mention)
async def ask(msg: Message, model: Model = _CHAT_MODEL_DEPENDENCY) -> None:
    tools = foundryiq_runtime_tools(_config.tool_definitions)
    if not tools:
        await msg.say(
            "FoundryIQ is not configured. Set TOOLBOX_NAME and the matching "
            "TOOLBOX_<NAME>_MCP_ENDPOINT.",
            ai_generated=True,
        )
        return
    answer = await model.respond_with_tools(msg.text, tools=tools, activity=None)
    await msg.say(answer, ai_generated=True, attachments=[action_chips(*_FOLLOWUPS)])


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8088")))
