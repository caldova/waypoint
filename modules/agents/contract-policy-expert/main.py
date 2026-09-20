"""Prompty-backed Contract Policy Expert for grounded contract Q&A."""

from __future__ import annotations

import os
from pathlib import Path

from castia import Agent, Message, Teams, action_chips, load_agent_config
from dotenv import load_dotenv

from toolbox import (
    foundryiq_prompty_tool_definitions,
    foundryiq_tool_functions,
    foundryiq_toolbox_preflight,
    foundryiq_toolbox_tools,
    is_foundryiq_configured,
)

AGENT_ROOT = Path(__file__).resolve().parent
CONFIG_ROOT = AGENT_ROOT / ".agent_configs"

load_dotenv(AGENT_ROOT / ".env", override=True)

app = Agent(name="contract-policy-expert")
app.require_env("FOUNDRY_PROJECT_ENDPOINT", "AZURE_AI_MODEL_DEPLOYMENT_NAME")

_FOLLOWUPS = (
    "What does Aster Ridge's contract say about rejected batch fees?",
    "Which policy governs invoice approval evidence?",
)

app.tools(foundryiq_toolbox_tools)


class ToolboxRuntimeConfigError(RuntimeError):
    """FoundryIQ toolbox configuration or readiness failed before model use."""


def resolved_agent_config():
    config = load_agent_config(CONFIG_ROOT)
    if not (config.instructions or "").strip():
        raise RuntimeError(
            "No baseline instructions were loaded from .agent_configs/baseline. "
            "Keep metadata.yaml and instructions.md with the agent."
        )
    return config


def validate_agent_config() -> None:
    resolved_agent_config()


app.startup_check(validate_agent_config)


def configure_prompty_tracing() -> None:
    from castia.prompty import register_prompty_otel_tracing

    register_prompty_otel_tracing()


app.startup_check(configure_prompty_tracing)


async def runner_provider():
    from castia.prompty import (
        ToolboxMcpClient,
        configured_prompty_runner,
        register_foundry_default_connection,
    )

    register_foundry_default_connection()
    config = resolved_agent_config()
    tools = []
    tool_functions = {}
    if is_foundryiq_configured():
        preflight = await foundryiq_toolbox_preflight()
        if not preflight.ok:
            diagnostics = preflight.diagnostics or (
                "FoundryIQ toolbox preflight failed.",
            )
            raise ToolboxRuntimeConfigError(" ".join(diagnostics))
        client = ToolboxMcpClient()
        tools = await foundryiq_prompty_tool_definitions(
            config.tool_definitions,
            client=client,
        )
        tool_functions = foundryiq_tool_functions(client=client)
    return configured_prompty_runner(
        config,
        tools=tools,
        tool_functions=tool_functions,
    )


def _missing_runtime_config() -> list[str]:
    missing = [
        name
        for name in ("FOUNDRY_PROJECT_ENDPOINT", "AZURE_AI_MODEL_DEPLOYMENT_NAME")
        if not os.environ.get(name, "").strip()
    ]
    if not is_foundryiq_configured():
        missing.append("TOOLBOX_NAME and TOOLBOX_<NAME>_MCP_ENDPOINT")
    return missing


def _missing_runtime_config_message(missing: list[str]) -> str:
    return "FoundryIQ runtime is not configured. Set " + ", ".join(missing) + "."


@app.responses()
async def reply(text: str) -> str:
    missing = _missing_runtime_config()
    if missing:
        return _missing_runtime_config_message(missing)
    try:
        runner = await runner_provider()
    except ToolboxRuntimeConfigError as exc:
        return str(exc)
    return await runner.turn(text)


@app.activity(Teams.direct, Teams.group, Teams.channel_mention)
async def ask(msg: Message) -> None:
    missing = _missing_runtime_config()
    if missing:
        await msg.say(
            _missing_runtime_config_message(missing),
            ai_generated=True,
        )
        return
    try:
        runner = await runner_provider()
    except ToolboxRuntimeConfigError as exc:
        await msg.say(str(exc), ai_generated=True)
        return
    answer = await runner.turn(msg.text)
    await msg.say(answer, ai_generated=True, attachments=[action_chips(*_FOLLOWUPS)])


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8088")))
