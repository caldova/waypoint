"""Toolset composition for each protocol surface."""

from __future__ import annotations

from dataclasses import dataclass

from castia import Agent, configured_model, load_agent_config
from castia.inference.tools import Tool, graph_tools

from agent.config import AGENT_ROOT
from agent.tools.contracts import contracts_tools


@dataclass(frozen=True)
class Toolsets:
    chat_model: object
    responses: list[Tool | dict]
    activity: list[Tool | dict]


def build_toolsets() -> Toolsets:
    config = load_agent_config(AGENT_ROOT / ".agent_configs")
    base: list[Tool | dict] = [*contracts_tools()]
    return Toolsets(
        chat_model=configured_model(config),
        responses=config.apply_tools(base),
        activity=config.apply_tools([*base, *graph_tools()]),
    )


def register_tools(app: Agent) -> None:
    app.tools(contracts_tools)

