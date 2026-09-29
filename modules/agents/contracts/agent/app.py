"""Application composition for the Contracts hosted agent."""

from __future__ import annotations

from castia import Agent

from agent.protocols.activity.commands import register_activity_commands
from agent.protocols.activity.handlers import register_activity
from agent.protocols.invocations.handlers import register_invocations
from agent.protocols.responses.handlers import register_responses
from agent.toolsets import build_toolsets, register_tools


def build_app() -> Agent:
    app = Agent(name="contracts")
    toolsets = build_toolsets()

    register_tools(app)
    register_responses(app, toolsets)
    register_invocations(app, toolsets)
    register_activity_commands(app, toolsets)
    register_activity(app, toolsets)

    return app

