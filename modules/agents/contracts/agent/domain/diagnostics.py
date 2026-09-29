"""Deterministic diagnostics used by Activity slash commands."""

from __future__ import annotations

import os
from typing import Any

import httpx
from azure.identity.aio import DefaultAzureCredential

from agent.config import foundry_agent_version, foundry_project_endpoint, local_fixture_enabled
from agent.integrations.activity_identity import (
    activity_from,
    agentic_user_id,
    call_or_none,
    has_agentic_user_identity,
)
from agent.toolsets import Toolsets


def version_response(agent_name: str, *, live_foundry_agent_version: str | None = None) -> str:
    configured_version = foundry_agent_version()
    return format_debug(
        "Contracts version",
        {
            "agent": agent_name,
            "foundry_agent_version": live_foundry_agent_version or configured_version,
            "foundry_agent_version_source": "live" if live_foundry_agent_version else "configured-env",
            "configured_foundry_agent_version": configured_version,
            "m365_app_version": os.environ.get("CONTRACTS_M365_APP_VERSION", "<unset>"),
            "model": os.environ.get("AZURE_AI_MODEL_DEPLOYMENT_NAME", "<unset>"),
            "foundry_project_configured": bool(foundry_project_endpoint()),
            "hosted_instance_client_id": os.environ.get(
                "FOUNDRY_AGENT_INSTANCE_CLIENT_ID",
                os.environ.get("FOUNDRY_AGENT_DEFAULT_INSTANCE_CLIENT_ID", "<unset>"),
            ),
            "blueprint_client_id": os.environ.get("FOUNDRY_AGENT_BLUEPRINT_CLIENT_ID", "<unset>"),
        },
    )


async def get_live_foundry_agent_version(agent_name: str) -> str | None:
    endpoint = foundry_project_endpoint()
    if not endpoint:
        return None

    credential = DefaultAzureCredential(exclude_interactive_browser_credential=True)
    try:
        token = (await credential.get_token("https://ai.azure.com/.default")).token
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(
                f"{endpoint}/agents/{agent_name}",
                params={"api-version": "2025-11-15-preview"},
                headers={"Authorization": f"Bearer {token}"},
            )
        response.raise_for_status()
        body = response.json()
        latest = (body.get("versions") or {}).get("latest") or {}
        version = latest.get("version")
        return str(version) if version else None
    except Exception:
        return None
    finally:
        await credential.close()


def state_response(activity: Any = None) -> str:
    raw = activity_from(activity)
    return format_debug(
        "Contracts state",
        {
            "contracts_inbox_configured": bool(os.environ.get("CONTRACTS_INBOX_ADDRESS")),
            "waypoint_api_configured": bool(os.environ.get("WAYPOINT_API_BASE_URL")),
            "waypoint_scope_configured": bool(os.environ.get("WAYPOINT_API_SCOPE")),
            "local_fixture_mode": local_fixture_enabled(),
            "activity_identity_present": raw is not None,
            "graph_tools_registered": True,
            "agentic_user_identity_present": has_agentic_user_identity(activity),
        },
    )


def whoami_response(activity: Any = None) -> str:
    raw = activity_from(activity)
    sender = getattr(raw, "from_property", None) if raw else None
    recipient = getattr(raw, "recipient", None) if raw else None
    conversation = getattr(raw, "conversation", None) if raw else None
    return format_debug(
        "Contracts identity",
        {
            "activity_present": raw is not None,
            "channel": getattr(raw, "channel", None) if raw else "<none>",
            "tenant_id": call_or_none(raw, "get_agentic_tenant_id")
            or getattr(conversation, "tenant_id", None)
            or "<unset>",
            "sender_aad_object_id": getattr(sender, "aad_object_id", None) or "<unset>",
            "recipient_id": getattr(recipient, "id", None) or "<unset>",
            "recipient_role": getattr(recipient, "role", None) or "<unset>",
            "recipient_agentic_user_id_present": bool(
                getattr(recipient, "agentic_user_id", None)
            ),
            "message_agentic_user_id_present": bool(
                getattr(activity, "agentic_user_id", None)
            ),
            "agentic_request": call_or_none(raw, "is_agentic_request") if raw else False,
            "agentic_user_id_present": has_agentic_user_identity(activity),
            "agentic_instance_id_present": bool(call_or_none(raw, "get_agentic_instance_id")),
        },
    )


def tools_response(toolsets: Toolsets) -> str:
    return format_debug(
        "Contracts tools",
        {
            "responses_tools": ", ".join(
                tool.name for tool in toolsets.responses if hasattr(tool, "name")
            ),
            "activity_tools": ", ".join(
                tool.name for tool in toolsets.activity if hasattr(tool, "name")
            ),
            "graph_scopes": "Mail.Read, Mail.Send, Files.ReadWrite",
        },
    )


def health_response(activity: Any = None) -> str:
    raw = activity_from(activity)
    recipient = getattr(raw, "recipient", None) if raw else None
    identity_ready = has_agentic_user_identity(activity)
    return format_debug(
        "Contracts health",
        {
            "ok": True,
            "activity_protocol": "registered",
            "responses_protocol": "registered",
            "invocations_protocol": "registered",
            "model_configured": bool(os.environ.get("AZURE_AI_MODEL_DEPLOYMENT_NAME")),
            "graph_tools_registered": True,
            "agentic_user_identity_present": identity_ready,
            "recipient_role": getattr(recipient, "role", None) or "<unset>",
            "graph_status": (
                "ready for mailbox/OneDrive actions on this turn"
                if identity_ready
                else "registered; waiting for recipient.role=agenticUser on an Agent 365 Activity turn"
            ),
        },
    )


def trace_response(activity: Any = None) -> str:
    raw = activity_from(activity)
    conversation = getattr(raw, "conversation", None) if raw else None
    return format_debug(
        "Contracts trace",
        {
            "activity_id": getattr(raw, "id", None) if raw else "<none>",
            "reply_to_id": getattr(raw, "reply_to_id", None) if raw else "<none>",
            "conversation_id": getattr(conversation, "id", None) or "<unset>",
            "activity_type": getattr(raw, "type", None) if raw else "<none>",
            "activity_name": getattr(raw, "name", None) if raw else "<none>",
        },
    )


def format_debug(title: str, values: dict[str, Any]) -> str:
    lines = [f"**{title}**", ""]
    lines.extend(f"- `{key}`: {value}" for key, value in values.items())
    return "\n".join(lines)
