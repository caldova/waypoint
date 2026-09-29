"""Shared response-mode router for protocol adapters."""

from __future__ import annotations

from typing import Any

from agent.config import foundry_project_endpoint
from agent.domain.capabilities import (
    capabilities_response,
    is_capabilities_prompt,
)
from agent.domain.contracts import fixture_response
from agent.domain.invoices import is_latest_invoices_prompt, latest_invoices_response
from agent.integrations.activity_identity import has_agentic_user_identity
from agent.toolsets import Toolsets


async def respond(text: str, *, toolsets: Toolsets, activity: Any = None) -> str:
    answer, _ = await respond_with_mode(text, toolsets=toolsets, activity=activity)
    return answer


async def respond_with_mode(
    text: str, *, toolsets: Toolsets, activity: Any = None
) -> tuple[str, str]:
    if is_capabilities_prompt(text):
        return capabilities_response(activity=activity), "capabilities"
    if is_latest_invoices_prompt(text):
        return latest_invoices_response(), "invoices"
    if foundry_project_endpoint():
        model = toolsets.chat_model()
        tools = toolsets.activity if has_agentic_user_identity(activity) else toolsets.responses
        return await model.respond_with_tools(text, tools=tools, activity=activity), "model"
    return await fixture_response(text), "fixture"
