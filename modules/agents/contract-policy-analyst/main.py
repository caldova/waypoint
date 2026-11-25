"""Independent Contract Policy Analyst with the expert's real FoundryIQ lane."""

import os
from pathlib import Path

from castia import (
    Agent,
    Depends,
    Message,
    Model,
    Teams,
    action_chips,
)
from configuration import config_evidence, load_release
from dotenv import load_dotenv
from model_route import routed_model
from observability import configure_project_export

from retrieval_audit import capture, persist
from toolbox import foundryiq_runtime_tools, foundryiq_toolbox_tools

load_dotenv(Path(__file__).resolve().parent / ".env", override=True)

app = Agent(name="contract-policy-analyst")

_config = load_release()
chat_model = routed_model(_config)
_CHAT_MODEL_DEPENDENCY = Depends(chat_model)

_FOLLOWUPS = (
    "What does Aster Ridge's contract say about rejected batch fees?",
    "Which policy governs invoice approval evidence?",
)

app.tools(foundryiq_toolbox_tools)


@app.responses()
async def reply(text: str, model: Model = _CHAT_MODEL_DEPENDENCY) -> str:
    output = None
    with capture(text, config_evidence(_config)) as audit:
        try:
            tools = foundryiq_runtime_tools(_config.tool_definitions)
            if not tools:
                raise RuntimeError("FoundryIQ toolbox endpoint is not configured.")
            output = await model.respond_with_tools(text, tools=tools, activity=None)
            return output
        finally:
            await persist(audit, output)


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
    configure_project_export()
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8088")))
