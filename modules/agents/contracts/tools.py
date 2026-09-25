"""Placeholder tools for the future Waypoint Contracts API surface."""

from __future__ import annotations

import os
from typing import Any

from castia.inference.tools import Tool
from dotenv import load_dotenv

load_dotenv()


def _usable_env(name: str) -> str | None:
    value = os.environ.get(name)
    value = value.strip() if value else ""
    return value or None


def _waypoint_base_url() -> str | None:
    value = _usable_env("WAYPOINT_API_BASE_URL")
    if not value:
        return None
    return value.rstrip("/")


def _contracts_inbox() -> str:
    return _usable_env("CONTRACTS_INBOX_ADDRESS") or "contracts@company.example"


def _future_endpoint(path: str) -> str:
    base = _waypoint_base_url() or "https://waypoint.example"
    return f"{base}{path}"


async def _get_contracts_capabilities_impl(activity: Any) -> dict[str, Any]:
    return {
        "ok": True,
        "agent": "contracts",
        "status": "stubbed",
        "wired_now": [
            "responses protocol",
            "activity protocol for Teams-style chat",
            "invocations protocol for agent-to-agent/tool use",
            "placeholder tools describing future Waypoint Contracts API calls",
        ],
        "future_api_needed": [
            "POST /api/contracts/intake/messages/upsert",
            "GET /api/contracts/artifacts/latest",
            "GET /api/contracts/artifacts/{artifact_id}",
            "POST /api/contracts/artifacts/{artifact_id}/extractions",
            "POST /api/contracts/artifacts/{artifact_id}/evidence",
            "POST /api/contracts/artifacts/{artifact_id}/reports",
        ],
        "inbox": _contracts_inbox(),
        "waypoint_configured": _waypoint_base_url() is not None,
    }


async def _poll_contracts_inbox_impl(activity: Any, *, lookback_minutes: int = 15) -> dict[str, Any]:
    return {
        "ok": False,
        "status": "not_implemented",
        "reason": "Mailbox polling waits on the Waypoint Contracts intake API and Graph/WorkIQ mailbox connector.",
        "inbox": _contracts_inbox(),
        "lookback_minutes": max(1, lookback_minutes),
        "future_call": {
            "method": "POST",
            "url": _future_endpoint("/api/contracts/intake/messages/upsert"),
            "idempotency_keys": [
                "mailbox_id",
                "message_id",
                "attachment_id",
                "attachment_sha256",
            ],
        },
    }


async def _get_last_contract_impl(
    activity: Any,
    *,
    owner_user_id: str = "",
) -> dict[str, Any]:
    return {
        "ok": False,
        "status": "not_implemented",
        "reason": "Latest-contract lookup waits on the Waypoint Contracts artifact API.",
        "owner_user_id": owner_user_id,
        "future_call": {
            "method": "GET",
            "url": _future_endpoint("/api/contracts/artifacts/latest"),
            "query": {
                "owner_user_id": owner_user_id or "{signed_in_user}",
                "artifact_type": "contract",
            },
        },
    }


async def _draft_contract_report_impl(
    activity: Any,
    *,
    artifact_id: str = "",
    report_type: str = "contract_brief",
) -> dict[str, Any]:
    return {
        "ok": False,
        "status": "not_implemented",
        "reason": "Report generation waits on the Waypoint Contracts report writer API.",
        "artifact_id": artifact_id,
        "report_type": report_type,
        "future_call": {
            "method": "POST",
            "url": _future_endpoint(
                f"/api/contracts/artifacts/{artifact_id or '{artifact_id}'}/reports"
            ),
            "body": {
                "report_type": report_type,
                "share_after_user_approval": True,
            },
        },
    }


def contracts_tools() -> list[Tool]:
    return [
        Tool(
            name="get_contracts_capabilities",
            description=(
                "Report what the Contracts agent can do now and which future Waypoint "
                "Contracts API endpoints are required for production behavior."
            ),
            parameters={
                "type": "object",
                "properties": {},
                "required": [],
                "additionalProperties": False,
            },
            impl=_get_contracts_capabilities_impl,
        ),
        Tool(
            name="poll_contracts_inbox",
            description=(
                "Stub for the future routine-driven mailbox poll. Returns the intended "
                "intake API call and idempotency keys; does not read email yet."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "lookback_minutes": {
                        "type": "integer",
                        "minimum": 1,
                        "description": "How far back the future mailbox poll should look.",
                    }
                },
                "required": [],
                "additionalProperties": False,
            },
            impl=_poll_contracts_inbox_impl,
        ),
        Tool(
            name="get_last_contract",
            description=(
                "Stub for resolving the latest contract artifact for the signed-in user "
                "or supplied owner_user_id."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "owner_user_id": {
                        "type": "string",
                        "description": "Optional user id/email whose latest contract should be resolved.",
                    }
                },
                "required": [],
                "additionalProperties": False,
            },
            impl=_get_last_contract_impl,
        ),
        Tool(
            name="draft_contract_report",
            description=(
                "Stub for generating a contract report document from a contract artifact. "
                "Returns the future report API call; does not create or share a file yet."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "artifact_id": {
                        "type": "string",
                        "description": "Contract artifact id to report on.",
                    },
                    "report_type": {
                        "type": "string",
                        "description": "Report type, such as contract_brief or diligence_memo.",
                    },
                },
                "required": [],
                "additionalProperties": False,
            },
            impl=_draft_contract_report_impl,
        ),
    ]
