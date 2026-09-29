"""Invocations protocol handlers."""

from __future__ import annotations

from castia import Agent

from agent.domain.modes import respond
from agent.toolsets import Toolsets


def register_invocations(app: Agent, toolsets: Toolsets) -> None:
    @app.invocations()
    async def invoked(text: str) -> str:
        return await respond(text, toolsets=toolsets)

