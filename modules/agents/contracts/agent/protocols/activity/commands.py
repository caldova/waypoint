"""Activity slash-command registrations."""

import inspect
from collections.abc import Awaitable, Callable

from castia import Agent, Message

from agent.domain.diagnostics import (
    get_live_foundry_agent_version,
    health_response,
    state_response,
    tools_response,
    trace_response,
    version_response,
    whoami_response,
)
from agent.protocols.activity.responding import start_activity_status
from agent.toolsets import Toolsets


CommandText = str | Awaitable[str]


async def command_reply(
    msg: Message,
    text: CommandText | Callable[[], CommandText],
    *,
    status: str = "Checking...",
) -> None:
    working = await start_activity_status(msg, status=status)
    try:
        produced = text() if callable(text) else text
        resolved = await produced if inspect.isawaitable(produced) else produced
    except Exception:
        await working.cancel()
        raise
    await working.finish(str(resolved))


def register_activity_commands(app: Agent, toolsets: Toolsets) -> None:
    @app.command(
        "version",
        description="Show deployed agent version and identity metadata",
        triggers=("slash",),
    )
    async def version_command(msg: Message) -> None:
        agent_name = app.name or "contracts"
        await command_reply(
            msg,
            _version_text(agent_name),
            status="Checking deployed versions...",
        )

    @app.command(
        "state",
        description="Show Contracts feature flags and configured surfaces",
        triggers=("slash",),
    )
    async def state_command(msg: Message) -> None:
        await command_reply(
            msg,
            lambda: state_response(msg),
            status="Checking Contracts state...",
        )

    @app.command(
        "whoami",
        description="Show the Teams and Agent 365 identity shape",
        triggers=("slash",),
    )
    async def whoami_command(msg: Message) -> None:
        await command_reply(
            msg,
            lambda: whoami_response(msg),
            status="Inspecting Activity identity...",
        )

    @app.command(
        "tools",
        description="List tools available on each protocol surface",
        triggers=("slash",),
    )
    async def tools_command(msg: Message) -> None:
        await command_reply(
            msg,
            lambda: tools_response(toolsets),
            status="Listing protocol tools...",
        )

    @app.command(
        "health",
        description="Check protocol, model, and agentic-user readiness",
        triggers=("slash",),
    )
    async def health_command(msg: Message) -> None:
        await command_reply(
            msg,
            lambda: health_response(msg),
            status="Checking Contracts health...",
        )

    @app.command(
        "trace",
        description="Show Activity and conversation IDs for telemetry lookup",
        triggers=("slash",),
    )
    async def trace_command(msg: Message) -> None:
        await command_reply(
            msg,
            lambda: trace_response(msg),
            status="Reading trace context...",
        )


async def _version_text(agent_name: str) -> str:
    live_version, error = await get_live_foundry_agent_version(agent_name)
    return version_response(agent_name, live_foundry_agent_version=live_version, live_lookup_error=error)
