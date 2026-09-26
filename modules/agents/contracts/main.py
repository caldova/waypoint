"""Waypoint Contracts — Teams-first contract intake autopilot stub."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from castia import (
    Agent,
    Message,
    Teams,
    action_chips,
    configured_model,
    load_agent_config,
)
from castia.inference.tools import Tool
from dotenv import load_dotenv

from toolbox import foundryiq_specs, foundryiq_toolbox_tools
from tools import contracts_tools

load_dotenv()
logging.basicConfig(
    level=os.environ.get("CONTRACTS_LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logging.getLogger("azure.core.pipeline.policies.http_logging_policy").setLevel(logging.WARNING)
logging.getLogger("azure.monitor.opentelemetry.exporter").setLevel(logging.WARNING)
_LOGGER = logging.getLogger("contracts.app")

app = Agent(name="contracts")

_config = load_agent_config(Path(__file__).resolve().parent / ".agent_configs")
chat_model = configured_model(_config)

app.tools(contracts_tools, foundryiq_toolbox_tools)

_TOOL_BASE: list[Tool | dict[str, Any]] = [*contracts_tools()]
_TOOLS = _config.apply_tools(_TOOL_BASE)

_FOLLOWUPS = (
    "What can Contracts do right now?",
    "Check the Contracts inbox",
    "Find the last contract I sent",
)


@app.responses()
async def work(text: str) -> str:
    _LOGGER.info("contracts.telemetry %s", json.dumps({"event": "contracts_responses_received"}))
    return await _respond(text)


@app.invocations()
async def invoked(payload: Any) -> str:
    _LOGGER.info("contracts.telemetry %s", json.dumps({"event": "contracts_invocation_received"}))
    command = _coerce_invocation_command(payload)
    if command:
        return await _run_invocation_command(command)
    return await _respond(str(payload or ""))


@app.activity(Teams.direct, Teams.group, Teams.channel_mention)
async def ask(msg: Message | str) -> str | None:
    text = msg.text if hasattr(msg, "text") else str(msg)
    answer = await _respond(text)
    if hasattr(msg, "say"):
        await msg.say(answer, ai_generated=True, attachments=[action_chips(*_FOLLOWUPS)])
        return None
    return answer


async def _respond(text: str) -> str:
    if os.environ.get("FOUNDRY_PROJECT_ENDPOINT"):
        model = chat_model()
        return await model.respond_with_tools(
            text,
            tools=_TOOLS,
            activity=None,
            extra_specs=await foundryiq_specs(_config.tool_definitions),
        )
    return await _fixture_response(text)


def _coerce_invocation_command(payload: Any) -> dict[str, Any] | None:
    value = payload
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped.startswith("{"):
            return None
        try:
            value = json.loads(stripped)
        except json.JSONDecodeError:
            return None
    if not isinstance(value, dict):
        return None
    nested = value.get("input")
    if isinstance(nested, str) and nested.strip().startswith("{"):
        try:
            nested = json.loads(nested)
        except json.JSONDecodeError:
            nested = None
    if isinstance(nested, dict):
        value = nested
    operation = value.get("operation")
    return value if isinstance(operation, str) and operation else None


async def _run_invocation_command(command: dict[str, Any]) -> str:
    operation = str(command["operation"]).strip()
    tool_by_name = {tool.name: tool.impl for tool in contracts_tools()}
    result: dict[str, Any]

    if operation == "get_contracts_capabilities":
        result = await tool_by_name["get_contracts_capabilities"](None)
    elif operation == "get_deployment_diagnostics":
        result = await tool_by_name["get_deployment_diagnostics"](None)
    elif operation == "poll_contracts_inbox":
        result = await tool_by_name["poll_contracts_inbox"](
            None,
            lookback_minutes=_positive_int(command.get("lookback_minutes"), default=15),
            artifact_type=str(command.get("artifact_type") or ""),
        )
    elif operation == "get_last_contract":
        result = await tool_by_name["get_last_contract"](
            None,
            owner_user_id=str(command.get("owner_user_id") or ""),
            artifact_type=str(command.get("artifact_type") or ""),
        )
    elif operation == "draft_contract_report":
        result = await tool_by_name["draft_contract_report"](
            None,
            artifact_id=str(command.get("artifact_id") or ""),
            report_type=str(command.get("report_type") or "contract_brief"),
            artifact_type=str(command.get("artifact_type") or ""),
        )
    elif operation == "query_invoices":
        result = await tool_by_name["query_invoices"](
            None,
            invoice_id=str(command.get("invoice_id") or ""),
            supplier_id=str(command.get("supplier_id") or ""),
            invoice_number=str(command.get("invoice_number") or ""),
            include_context=_bool(command.get("include_context"), default=True),
            limit=_positive_int(command.get("limit"), default=5),
        )
    else:
        result = {
            "ok": False,
            "status": "unknown_invocation_operation",
            "operation": operation,
            "supported_operations": [
                "get_contracts_capabilities",
                "get_deployment_diagnostics",
                "poll_contracts_inbox",
                "get_last_contract",
                "draft_contract_report",
                "query_invoices",
            ],
        }

    return json.dumps(
        {
            "protocol": "invocations",
            "command": command,
            "result": result,
        },
        indent=2,
        sort_keys=True,
    )


def _positive_int(value: Any, *, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _bool(value: Any, *, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    return default


async def _fixture_response(text: str) -> str:
    """Deterministic no-model path for local playground scaffold testing."""

    normalized = text.lower()
    tool_by_name = {tool.name: tool.impl for tool in contracts_tools()}

    if "draft" in normalized or "report" in normalized or "brief" in normalized:
        result = await tool_by_name["draft_contract_report"](
            None,
            report_type="contract_brief",
        )
        return _format_fixture_result(
            "I drafted a local fixture contract brief. This is not a SharePoint document and it was not shared.",
            result,
        )

    if "last contract" in normalized or "latest contract" in normalized:
        result = await tool_by_name["get_last_contract"](None)
        artifact = result.get("artifact", {}) if isinstance(result, dict) else {}
        title = artifact.get("title", "the local fixture contract")
        return _format_fixture_result(
            f"The latest local fixture contract is **{title}**.",
            result,
        )

    if "inbox" in normalized or "poll" in normalized or "email" in normalized:
        result = await tool_by_name["poll_contracts_inbox"](None)
        return _format_fixture_result(
            "I ran the local fixture inbox path. No mailbox was read.",
            result,
        )

    if "invoice" in normalized:
        result = await tool_by_name["query_invoices"](None, limit=3)
        return _format_fixture_result(
            "I queried Waypoint for invoices.",
            result,
        )

    result = await tool_by_name["get_contracts_capabilities"](None)
    return _format_fixture_result(
        "Contracts is running in local fixture mode because `FOUNDRY_PROJECT_ENDPOINT` is not configured.",
        result,
    )


def _format_fixture_result(summary: str, result: dict[str, Any]) -> str:
    return (
        f"{summary}\n\n"
        "**Fixture result:**\n"
        "```json\n"
        f"{json.dumps(result, indent=2, sort_keys=True)}\n"
        "```"
    )


if __name__ == "__main__":
    app.run()
