"""Tools for the Waypoint Contracts scaffold.

The production tools will call the Waypoint Contracts API. Until that API lands,
these tools run in a local fixture mode by default so the agent can be exercised
end-to-end in the Foundry playground without pretending it touched email,
SharePoint, or live Waypoint state.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
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


def _local_fixture_enabled() -> bool:
    raw = _usable_env("CONTRACTS_LOCAL_FIXTURE_MODE")
    if raw is not None:
        return raw.lower() not in {"0", "false", "no", "off"}
    return _waypoint_base_url() is None


def _state_dir() -> Path:
    configured = _usable_env("CONTRACTS_LOCAL_STATE_DIR")
    if configured:
        return Path(configured)
    return Path(__file__).resolve().parent / ".contracts-state"


def _state_file() -> Path:
    return _state_dir() / "state.json"


def _load_state() -> dict[str, Any]:
    path = _state_file()
    if not path.exists():
        return {"artifacts": [], "checkpoints": [], "reports": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"artifacts": [], "checkpoints": [], "reports": []}
    if not isinstance(data, dict):
        return {"artifacts": [], "checkpoints": [], "reports": []}
    data.setdefault("artifacts", [])
    data.setdefault("checkpoints", [])
    data.setdefault("reports", [])
    return data


def _save_state(state: dict[str, Any]) -> None:
    path = _state_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _mock_artifact(owner_user_id: str = "local.user@contracts.local") -> dict[str, Any]:
    created_at = _now()
    return {
        "id": "contract-local-aster-ridge-sow",
        "type": "contract",
        "title": "Aster Ridge Biomanufacturing Statement of Work",
        "owner_user_id": owner_user_id,
        "source": "email",
        "source_mailbox_id": _contracts_inbox(),
        "source_message_id": "local-fixture-message-001",
        "source_attachment_id": "local-fixture-attachment-001",
        "source_attachment_sha256": (
            "8bc8ef4e35c7d7f509b31d3b50a7e0a6c6f798ab617f5bba61583c0d79e64e9c"
        ),
        "original_file_uri": "local-fixture://contracts/aster-ridge-sow.pdf",
        "extraction_status": "completed",
        "processing_status": "ready",
        "created_at": created_at,
        "updated_at": created_at,
        "extracted_json": {
            "supplier": "Aster Ridge Biomanufacturing",
            "document_type": "statement_of_work",
            "effective_date": "2026-01-15",
            "governing_terms": [
                "batch release administration",
                "quality deviation cost recovery",
                "sponsor approval before pass-through fees",
            ],
            "commercial_values": {
                "currency": "USD",
                "monthly_minimum": 125000,
                "release_administration_fee": 3750,
            },
        },
        "evidence": [
            {
                "id": "evidence-local-001",
                "source_type": "content_understanding",
                "claim": "The fixture contract includes a release administration fee.",
                "citation": "local-fixture://contracts/aster-ridge-sow.pdf#release-fees",
                "confidence": 0.82,
            },
            {
                "id": "evidence-local-002",
                "source_type": "policy",
                "claim": "Pass-through fees require sponsor approval before recovery.",
                "citation": "local-fixture://policies/invoice-reconciliation-policy.md",
                "confidence": 0.78,
            },
        ],
        "metadata": {
            "fixture": True,
            "note": "Local scaffold artifact for playground testing only.",
        },
    }


def _ensure_mock_artifact(state: dict[str, Any], owner_user_id: str = "") -> dict[str, Any]:
    artifact_id = "contract-local-aster-ridge-sow"
    artifacts = [item for item in state["artifacts"] if isinstance(item, dict)]
    for artifact in artifacts:
        if artifact.get("id") == artifact_id:
            return artifact
    artifact = _mock_artifact(owner_user_id or "local.user@contracts.local")
    artifacts.append(artifact)
    state["artifacts"] = artifacts
    _save_state(state)
    return artifact


def _latest_artifact(state: dict[str, Any], owner_user_id: str = "") -> dict[str, Any] | None:
    artifacts = [item for item in state["artifacts"] if isinstance(item, dict)]
    if owner_user_id:
        artifacts = [item for item in artifacts if item.get("owner_user_id") == owner_user_id]
    if not artifacts:
        return None
    return max(artifacts, key=lambda item: str(item.get("created_at") or ""))


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
            "POST /api/contracts/artifacts/{artifact_id}/runs",
            "POST /api/contracts/artifacts/{artifact_id}/reports",
        ],
        "inbox": _contracts_inbox(),
        "waypoint_configured": _waypoint_base_url() is not None,
        "local_fixture_mode": _local_fixture_enabled(),
        "local_state_dir": str(_state_dir()) if _local_fixture_enabled() else None,
    }


async def _poll_contracts_inbox_impl(activity: Any, *, lookback_minutes: int = 15) -> dict[str, Any]:
    if _local_fixture_enabled():
        state = _load_state()
        artifact = _ensure_mock_artifact(state)
        checkpoint = {
            "mailbox_id": _contracts_inbox(),
            "message_id": artifact["source_message_id"],
            "attachment_id": artifact["source_attachment_id"],
            "attachment_sha256": artifact["source_attachment_sha256"],
            "artifact_id": artifact["id"],
            "processed_at": _now(),
            "status": "processed_local_fixture",
        }
        checkpoints = [item for item in state["checkpoints"] if isinstance(item, dict)]
        key = (
            checkpoint["mailbox_id"],
            checkpoint["message_id"],
            checkpoint["attachment_id"],
            checkpoint["attachment_sha256"],
        )
        if not any(
            (
                item.get("mailbox_id"),
                item.get("message_id"),
                item.get("attachment_id"),
                item.get("attachment_sha256"),
            )
            == key
            for item in checkpoints
        ):
            checkpoints.append(checkpoint)
            state["checkpoints"] = checkpoints
            _save_state(state)
        return {
            "ok": True,
            "status": "local_fixture",
            "inbox": _contracts_inbox(),
            "lookback_minutes": max(1, lookback_minutes),
            "processed_count": 1,
            "artifact": artifact,
            "checkpoint": checkpoint,
            "note": "Local fixture mode only; no email mailbox was read.",
        }

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
    if _local_fixture_enabled():
        state = _load_state()
        artifact = _latest_artifact(state, owner_user_id) or _ensure_mock_artifact(
            state, owner_user_id
        )
        return {
            "ok": True,
            "status": "local_fixture",
            "artifact": artifact,
            "note": "Local fixture mode only; this is not live Waypoint data.",
        }

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
    if _local_fixture_enabled():
        state = _load_state()
        artifact = (
            next(
                (
                    item
                    for item in state["artifacts"]
                    if isinstance(item, dict) and item.get("id") == artifact_id
                ),
                None,
            )
            if artifact_id
            else None
        )
        artifact = artifact or _latest_artifact(state) or _ensure_mock_artifact(state)
        report_id = f"report-{artifact['id']}-{report_type}"
        report_path = _state_dir() / "reports" / f"{report_id}.md"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_body = "\n".join(
            [
                f"# {artifact['title']} - {report_type.replace('_', ' ').title()}",
                "",
                "> Local scaffold report. No SharePoint file was created or shared.",
                "",
                f"- Artifact: `{artifact['id']}`",
                f"- Supplier: {artifact['extracted_json'].get('supplier')}",
                f"- Document type: {artifact['extracted_json'].get('document_type')}",
                f"- Evidence records: {len(artifact.get('evidence', []))}",
            ]
        )
        report_path.write_text(report_body, encoding="utf-8")
        report = {
            "id": report_id,
            "artifact_id": artifact["id"],
            "report_type": report_type,
            "file_url": report_path.as_uri(),
            "share_status": "not_shared_local_fixture",
            "created_at": _now(),
            "metadata": {"fixture": True},
        }
        reports = [item for item in state["reports"] if isinstance(item, dict)]
        reports = [item for item in reports if item.get("id") != report_id]
        reports.append(report)
        state["reports"] = reports
        _save_state(state)
        return {
            "ok": True,
            "status": "local_fixture",
            "report": report,
            "note": "Local fixture mode only; no SharePoint document was created or shared.",
        }

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
