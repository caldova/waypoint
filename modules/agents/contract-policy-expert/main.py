"""FoundryIQ-only Contract Policy Expert for grounded contract Q&A."""

import os
from pathlib import Path

from castia import Agent, Message, Teams, action_chips, load_agent_config
from castia.prompty import ToolboxRuntimeConfigError, prompty_runner_provider
from dotenv import load_dotenv

from toolbox import foundryiq_runtime_tools, foundryiq_toolbox_tools

AGENT_ROOT = Path(__file__).resolve().parent
CONFIG_ROOT = AGENT_ROOT / ".agent_configs"

load_dotenv(AGENT_ROOT / ".env", override=True)

app = Agent(name="contract-policy-expert")

_NOT_CONFIGURED = (
    "FoundryIQ is not configured. Set TOOLBOX_NAME and the matching "
    "TOOLBOX_<NAME>_MCP_ENDPOINT."
)
_FOLLOWUPS = (
    "What does Aster Ridge's contract say about rejected batch fees?",
    "Which policy governs invoice approval evidence?",
)

app.tools(foundryiq_toolbox_tools)


def _runner_provider():
    config = load_agent_config(CONFIG_ROOT)
    tools = foundryiq_runtime_tools(config.tool_definitions)
    if not tools:
        return None
    # The local FoundryIQ wrapper keeps the trained tool name and span label,
    # so Prompty's own toolbox projection stays off.
    return prompty_runner_provider(config, tools=tools, toolbox=False)


_runner = _runner_provider()


async def _answer(text: str) -> str:
    if _runner is None:
        return _NOT_CONFIGURED
    try:
        runner = await _runner()
    except ToolboxRuntimeConfigError as exc:
        return str(exc)
    return await runner.turn(text)


@app.responses()
async def reply(text: str) -> str:
    return await _answer(text)


@app.activity(Teams.direct, Teams.group, Teams.channel_mention)
async def ask(msg: Message) -> None:
    answer = await _answer(msg.text)
    attachments = [action_chips(*_FOLLOWUPS)] if _runner is not None else []
    await msg.say(answer, ai_generated=True, attachments=attachments)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8088")))
