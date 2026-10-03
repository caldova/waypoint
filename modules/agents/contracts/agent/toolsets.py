"""Toolset composition for each protocol surface."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace

from castia import Agent, load_agent_config
from castia.inference.tools import Tool, graph_tools
from castia.prompty import PromptyRunner, prompty_runner_provider

from agent.config import AGENT_ROOT
from agent.tools.contracts import contracts_tools
from toolbox import foundryiq_runtime_tools, foundryiq_toolbox_tools, is_toolbox_configured

# Castia stamps Tool.kind onto the execute_tool span as gen_ai.tool.type.
# New IQ-backed tools must set kind="<source>_iq" and use a "<source>_iq_" name
# prefix so the span name shows the IQ source (see README "IQ tool telemetry").
WORK_IQ = "work_iq"
# Report turns gather (contract, invoices, KB) then draft; leave room for one retry.
MAX_TOOL_ITERATIONS = 6
# contracts-toolbox MCP tools projected straight to the model (exact names from
# tools/list). The KB lane is excluded: it runs through foundry_iq_retrieve.
# Empty keeps projection off; add a lane's tool names here to expose it.
CONTRACTS_TOOLBOX_TOOLS: tuple[str, ...] = ()


RunnerProvider = Callable[[], Awaitable[PromptyRunner]]


@dataclass(frozen=True)
class Toolsets:
    responses: list[Tool | dict]
    activity: list[Tool | dict]
    responses_runner: RunnerProvider
    activity_runner: RunnerProvider


def work_iq_tools() -> list[Tool]:
    """Castia's agentic-user Graph tools, labeled as WorkIQ in telemetry."""
    return [replace(tool, kind=WORK_IQ) for tool in graph_tools()]


def build_toolsets() -> Toolsets:
    config = load_agent_config(AGENT_ROOT / ".agent_configs")
    base: list[Tool | dict] = [*contracts_tools()]
    # Added after apply_tools: the runtime wrapper folds in optimized wording
    # itself and keeps a strict query schema.
    foundry_iq = foundryiq_runtime_tools(config.tool_definitions)
    responses = [*config.apply_tools(base), *foundry_iq]
    activity = [*config.apply_tools([*base, *work_iq_tools()]), *foundry_iq]
    toolbox = toolbox_projection()
    return Toolsets(
        responses=responses,
        activity=activity,
        responses_runner=prompty_runner_provider(
            config, tools=responses, toolbox=toolbox, max_iterations=MAX_TOOL_ITERATIONS
        ),
        activity_runner=prompty_runner_provider(
            config, tools=activity, toolbox=toolbox, max_iterations=MAX_TOOL_ITERATIONS
        ),
    )


def toolbox_projection() -> list[str] | bool:
    """Castia toolbox arg: the allowlist when set and configured, else off."""
    if CONTRACTS_TOOLBOX_TOOLS and is_toolbox_configured():
        return list(CONTRACTS_TOOLBOX_TOOLS)
    return False


def register_tools(app: Agent) -> None:
    app.tools(contracts_tools, foundryiq_toolbox_tools)