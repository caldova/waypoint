"""Toolset composition for each protocol surface."""

from __future__ import annotations

from dataclasses import dataclass, replace

from castia import Agent, configured_model, load_agent_config
from castia.inference.tools import Tool, graph_tools

from agent.config import AGENT_ROOT
from agent.tools.contracts import contracts_tools
from toolbox import foundryiq_runtime_tools, foundryiq_toolbox_tools

# Castia stamps Tool.kind onto the execute_tool span as gen_ai.tool.type.
# New IQ-backed tools must set kind="<source>_iq" and use a "<source>_iq_" name
# prefix so the span name shows the IQ source (see README "IQ tool telemetry").
WORK_IQ = "work_iq"


@dataclass(frozen=True)
class Toolsets:
    chat_model: object
    responses: list[Tool | dict]
    activity: list[Tool | dict]


def work_iq_tools() -> list[Tool]:
    """Castia's agentic-user Graph tools, labeled as WorkIQ in telemetry."""
    return [replace(tool, kind=WORK_IQ) for tool in graph_tools()]


def build_toolsets() -> Toolsets:
    config = load_agent_config(AGENT_ROOT / ".agent_configs")
    base: list[Tool | dict] = [*contracts_tools()]
    # Added after apply_tools: the runtime wrapper folds in optimized wording
    # itself and keeps a strict query schema.
    foundry_iq = foundryiq_runtime_tools(config.tool_definitions)
    return Toolsets(
        chat_model=configured_model(config),
        responses=[*config.apply_tools(base), *foundry_iq],
        activity=[*config.apply_tools([*base, *work_iq_tools()]), *foundry_iq],
    )


def register_tools(app: Agent) -> None:
    app.tools(contracts_tools, foundryiq_toolbox_tools)