"""Tools for the Waypoint Contracts scaffold.

The production tools will call the Waypoint Contracts API. Until that API lands,
these tools run in a local fixture mode by default so the agent can be exercised
end-to-end in the Foundry playground without pretending it touched email,
SharePoint, or live Waypoint state.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from agent.integrations.activity_identity import has_agentic_user_identity
from agent.integrations.requester import agentic_graph_token, requester_email
from azure.identity.aio import DefaultAzureCredential
from castia.inference.tools import Tool
from content_understanding import ContractExtraction, extract_contract_pdf
from contract_sources import (
    ContractAttachment,
    HostedMailboxContractSource,
    contract_source,
)
from dotenv import load_dotenv
from report_publisher import report_publisher, sharepoint_report_publishing_configured
from report_writer import render_report

from toolbox import is_toolbox_configured

load_dotenv()

_LOGGER = logging.getLogger("contracts.telemetry")


def _usable_env(name: str) -> str | None:
    value = os.environ.get(name)
    value = value.strip() if value else ""
    return value or None


def _waypoint_base_url() -> str | None:
    value = _usable_env("WAYPOINT_API_BASE_URL")
    if not value:
        return None
    return value.rstrip("/")


def _is_local_base_url(value: str) -> bool:
    return value.startswith(
        (
            "http://127.0.0.1",
            "https://127.0.0.1",
            "http://localhost",
            "https://localhost",
        )
    )


def _contracts_inbox() -> str:
    return _usable_env("CONTRACTS_INBOX_ADDRESS") or "contracts@company.example"


def _contracts_owner() -> str:
    return _usable_env("CONTRACTS_DEV_USER_EMAIL") or "local.user@contracts.local"


async def _turn_owner(activity: Any) -> str | None:
    """On a Teams turn the requester owns the data and callers cannot override it.

    Fails closed: a lookup error on a Teams turn raises rather than falling back.
    """
    if not has_agentic_user_identity(activity):
        return None
    return await requester_email(activity, await agentic_graph_token(activity))


def _env_presence(names: list[str]) -> dict[str, bool]:
    return {name: _usable_env(name) is not None for name in names}


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


def _telemetry_event(name: str, **properties: Any) -> None:
    payload = {
        "event": name,
        "agent": "contracts",
        "timestamp": _now(),
        "build_id": _usable_env("CONTRACTS_AGENT_BUILD_ID"),
        "deployment_stage": _usable_env("CONTRACTS_AGENT_DEPLOYMENT_STAGE"),
        **properties,
    }
    _LOGGER.info("contracts.telemetry %s", json.dumps(payload, sort_keys=True, default=str))


def _coerce_artifact_type(value: str | None) -> str | None:
    artifact_type = (value or "").strip().lower()
    return artifact_type if artifact_type in {"contract", "invoice"} else None


def _artifact_type_filter(value: str | None = None) -> str:
    return _coerce_artifact_type(value) or _coerce_artifact_type(
        os.environ.get("CONTRACTS_LOCAL_DOCUMENT_KIND")
    ) or "contract"


def _local_contract_attachment(
    owner_user_id: str = "local.user@contracts.local",
    *,
    artifact_type: str | None = None,
) -> ContractAttachment:
    return contract_source().next_contract(
        mailbox_id=_contracts_inbox(),
        owner_user_id=owner_user_id,
        artifact_type=artifact_type,
    )


def _mock_artifact(
    owner_user_id: str = "local.user@contracts.local",
    attachment: ContractAttachment | None = None,
    extraction: ContractExtraction | None = None,
) -> dict[str, Any]:
    attachment = attachment or _local_contract_attachment(owner_user_id)
    extracted_json = extraction.values if extraction else _local_extracted_json()
    created_at = _now()
    artifact_id = f"{attachment.artifact_type}-local-{attachment.sha256[:16]}"
    return {
        "id": artifact_id,
        "type": attachment.artifact_type,
        "title": attachment.subject,
        "owner_user_id": owner_user_id,
        "source": "email",
        "source_mailbox_id": attachment.mailbox_id,
        "source_message_id": attachment.message_id,
        "source_attachment_id": attachment.attachment_id,
        "source_attachment_sha256": attachment.sha256,
        "original_file_uri": attachment.original_file_uri,
        "extraction_status": "completed",
        "processing_status": "ready",
        "created_at": created_at,
        "updated_at": created_at,
        "extracted_json": extracted_json,
        "evidence": [
            {
                "id": "evidence-local-001",
                "source_type": "content_understanding",
                "claim": f"The fixture {attachment.artifact_type} was extracted by Content Understanding.",
                "citation": f"{attachment.original_file_uri}#content-understanding",
                "confidence": 0.82,
            }
        ],
        "metadata": {
            "fixture": True,
            "source_mode": attachment.source_mode,
            "artifact_type": attachment.artifact_type,
            "source_file_name": attachment.file_name,
            "source_size_bytes": attachment.size_bytes,
            "note": "Local scaffold artifact for playground testing only.",
        },
    }


def _local_extracted_json() -> dict[str, Any]:
    return {
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
    }


def _ensure_mock_artifact(
    state: dict[str, Any],
    owner_user_id: str = "",
    *,
    artifact_type: str | None = None,
) -> dict[str, Any]:
    attachment = _local_contract_attachment(
        owner_user_id or "local.user@contracts.local",
        artifact_type=artifact_type,
    )
    artifact_id = f"{attachment.artifact_type}-local-{attachment.sha256[:16]}"
    artifacts = [item for item in state["artifacts"] if isinstance(item, dict)]
    for artifact in artifacts:
        if artifact.get("id") == artifact_id:
            return artifact
    artifact = _mock_artifact(owner_user_id or "local.user@contracts.local", attachment)
    artifacts.append(artifact)
    state["artifacts"] = artifacts
    _save_state(state)
    return artifact


def _latest_artifact(
    state: dict[str, Any],
    owner_user_id: str = "",
    *,
    artifact_type: str | None = None,
) -> dict[str, Any] | None:
    artifacts = [item for item in state["artifacts"] if isinstance(item, dict)]
    if owner_user_id:
        artifacts = [item for item in artifacts if item.get("owner_user_id") == owner_user_id]
    artifact_type = _coerce_artifact_type(artifact_type)
    if artifact_type:
        artifacts = [item for item in artifacts if item.get("type") == artifact_type]
    if not artifacts:
        return None
    return max(artifacts, key=lambda item: str(item.get("created_at") or ""))


def _future_endpoint(path: str) -> str:
    base = _waypoint_base_url() or "https://waypoint.example"
    return f"{base}{path}"


def _report_markdown(artifact: dict[str, Any], report_type: str) -> str:
    extracted = _artifact_extracted_values(artifact)
    commercial = extracted.get("commercial_values") if isinstance(extracted, dict) else {}
    commercial = commercial if isinstance(commercial, dict) else {}
    evidence = artifact.get("evidence") if isinstance(artifact.get("evidence"), list) else []
    title = (
        artifact.get("title")
        or artifact.get("file_name")
        or artifact.get("source_file_name")
        or "Contract artifact"
    )
    return "\n".join(
        [
            f"# {title} - {report_type.replace('_', ' ').title()}",
            "",
            "## Summary",
            "",
            f"- Artifact: `{artifact.get('id', 'unknown')}`",
            f"- Supplier: {extracted.get('supplier', 'Unknown')}",
            f"- Document type: {extracted.get('document_type', 'Unknown')}",
            f"- Effective date: {extracted.get('effective_date', 'Unknown')}",
            f"- Monthly minimum: {commercial.get('currency', 'USD')} {commercial.get('monthly_minimum', 'Unknown')}",
            f"- Release administration fee: {commercial.get('currency', 'USD')} {commercial.get('release_administration_fee', 'Unknown')}",
            f"- Evidence records: {len(evidence)}",
            "",
            "## Review priorities",
            "",
            "- Confirm billing triggers and whether fees are inside or outside the monthly minimum.",
            "- Verify sponsor approval requirements before pass-through fee recovery.",
            "- Review quality deviation cost recovery support requirements.",
            "",
            "## Source",
            "",
            f"- Source URI: `{artifact.get('original_file_uri', artifact.get('file_url', 'unknown'))}`",
        ]
    )


async def _publish_rendered_report(
    *,
    rendered_docx: Path,
    rendered_markdown: Path,
    title: str,
    activity: Any = None,
) -> dict[str, Any]:
    _telemetry_event(
        "contracts_report_publish_started",
        title=title,
        docx_exists=rendered_docx.exists(),
        markdown_exists=rendered_markdown.exists(),
        publish_mode=_usable_env("CONTRACTS_REPORTS_PUBLISH_MODE") or "auto",
        sharepoint_configured=sharepoint_report_publishing_configured(),
    )
    try:
        published = await report_publisher(activity).publish(
            docx_path=rendered_docx,
            markdown_path=rendered_markdown,
            title=title,
        )
    except Exception as exc:
        _telemetry_event(
            "contracts_report_publish_failed",
            title=title,
            error_type=type(exc).__name__,
            error=str(exc),
            sharepoint_configured=sharepoint_report_publishing_configured(),
        )
        raise
    _telemetry_event(
        "contracts_report_publish_succeeded",
        title=title,
        storage=published.storage,
        share_status=published.share_status,
        has_teams_link=bool(published.teams_link_url),
        has_drive_item=published.drive_item is not None,
    )
    return {
        "file_url": published.file_url,
        "teams_link_url": published.teams_link_url,
        "share_status": published.share_status,
        "storage": published.storage,
        "web_url": published.web_url,
        "share_url": published.share_url,
        "drive_item": published.drive_item,
        "metadata": published.metadata or {},
    }


def _publication_shared_with(publication: dict[str, Any]) -> list[str]:
    object_id = (publication.get("metadata") or {}).get("shared_with_object_id")
    return [str(object_id)] if object_id else []


def _api_share_status(publication: dict[str, Any]) -> str:
    status = str(publication.get("share_status") or "")
    if status == "shared_link_created":
        return "shared"
    if status.startswith("not_shared"):
        return "not_shared"
    if status in {"pending_approval", "shared", "failed", "not_shared"}:
        return status
    return "failed"


def _artifact_extracted_values(artifact: dict[str, Any]) -> dict[str, Any]:
    extracted = artifact.get("extracted_json")
    if isinstance(extracted, dict):
        return extracted
    extractions = artifact.get("extractions")
    if isinstance(extractions, list) and extractions:
        latest = next((item for item in reversed(extractions) if isinstance(item, dict)), None)
        if latest:
            values = latest.get("values")
            if isinstance(values, dict):
                return values
    return {}


class _WaypointContractsClient:
    def __init__(self) -> None:
        base = _waypoint_base_url()
        if not base:
            raise RuntimeError("WAYPOINT_API_BASE_URL is not configured.")
        if not base.startswith(("http://", "https://")):
            base = f"https://{base}"
        self._base = base.rstrip("/")
        self._scope = _usable_env("WAYPOINT_API_SCOPE")
        self._api_key = _usable_env("WAYPOINT_API_KEY")
        self._dev_user_email = _usable_env("CONTRACTS_DEV_USER_EMAIL")
        raw_verify = _usable_env("WAYPOINT_API_VERIFY_SSL")
        self._verify = True if raw_verify is None else raw_verify.lower() not in {
            "0",
            "false",
            "no",
            "off",
        }
        self._credential: Any | None = None

    def _url(self, path: str) -> str:
        if self._base.endswith("/api") and path.startswith("/api/"):
            return f"{self._base}{path[4:]}"
        return f"{self._base}{path}"

    async def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if self._scope:
            if self._credential is None:
                self._credential = DefaultAzureCredential()
            token = await self._credential.get_token(self._scope)
            headers["Authorization"] = f"Bearer {token.token}"
        elif self._api_key:
            headers["x-api-key"] = self._api_key
        elif self._dev_user_email and _is_local_base_url(self._base):
            headers["x-dev-user-email"] = self._dev_user_email
        return headers

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any] | list[Any]:
        headers = await self._headers()
        async with httpx.AsyncClient(timeout=30.0, verify=self._verify) as client:
            response = await client.request(
                method,
                self._url(path),
                headers=headers,
                params=params,
                json=json_body,
            )
        if response.is_error:
            raise RuntimeError(
                f"Waypoint {method} {path} failed with HTTP {response.status_code}: "
                f"{response.text[:500]}"
            )
        if not response.content:
            return {}
        value = response.json()
        return value if isinstance(value, (dict, list)) else {"value": value}


async def _get_contracts_capabilities_impl(activity: Any) -> dict[str, Any]:
    result = {
        "ok": True,
        "agent": "contracts",
        "status": "api_configured" if _waypoint_base_url() else "fixture_ready",
        "wired_now": [
            "responses protocol",
            "activity protocol for Teams-style chat",
            "invocations protocol for structured routine and agent-to-agent work commands",
            (
                "Waypoint Contracts API tools"
                if _waypoint_base_url()
                else "local fixture tools for no-API playground testing"
            ),
            (
                "FoundryIQ contract/policy toolbox"
                if is_toolbox_configured()
                else "FoundryIQ toolbox declaration (endpoint not configured)"
            ),
            (
                "SharePoint report publishing"
                if sharepoint_report_publishing_configured()
                else "local DOCX report rendering (SharePoint publishing not configured)"
            ),
        ],
        "api_endpoints": [
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
        "foundryiq_toolbox_configured": is_toolbox_configured(),
        "sharepoint_report_publishing_configured": sharepoint_report_publishing_configured(),
        "local_fixture_mode": _local_fixture_enabled(),
        "document_source": (
            "local_pdf"
            if _local_fixture_enabled() or _is_local_base_url(_waypoint_base_url() or "")
            else "hosted_mailbox"
        ),
        "local_state_dir": str(_state_dir()) if _local_fixture_enabled() else None,
    }
    _telemetry_event(
        "contracts_capabilities_checked",
        waypoint_configured=result["waypoint_configured"],
        foundryiq_toolbox_configured=result["foundryiq_toolbox_configured"],
        sharepoint_report_publishing_configured=result[
            "sharepoint_report_publishing_configured"
        ],
        document_source=result["document_source"],
    )
    return result


async def _get_deployment_diagnostics_impl(activity: Any) -> dict[str, Any]:
    configured_values = {
        "waypoint_api_base_url": _waypoint_base_url(),
        "contracts_inbox_address": _contracts_inbox(),
        "reports_publish_mode": _usable_env("CONTRACTS_REPORTS_PUBLISH_MODE") or "auto",
        "reports_link_type": _usable_env("CONTRACTS_REPORTS_LINK_TYPE") or "view",
        "reports_link_scope": _usable_env("CONTRACTS_REPORTS_LINK_SCOPE") or "organization",
        "document_source_mode": _usable_env("CONTRACTS_DOCUMENT_SOURCE_MODE") or "auto",
        "local_document_kind": _artifact_type_filter(),
        "agent_build_id": _usable_env("CONTRACTS_AGENT_BUILD_ID"),
        "agent_deployment_stage": _usable_env("CONTRACTS_AGENT_DEPLOYMENT_STAGE"),
    }
    environment_presence = _env_presence(
        [
            "FOUNDRY_PROJECT_ENDPOINT",
            "AZURE_AI_MODEL_DEPLOYMENT_NAME",
            "WAYPOINT_API_BASE_URL",
            "WAYPOINT_API_SCOPE",
            "CONTRACTS_INBOX_ADDRESS",
            "CONTENT_UNDERSTANDING_ENDPOINT",
            "CONTENT_UNDERSTANDING_ANALYZER_ID",
            "TOOLBOX_NAME",
            "TOOLBOX_CONTRACTS_TOOLBOX_MCP_ENDPOINT",
            "CONTRACTS_REPORTS_DRIVE_ID",
            "CONTRACTS_REPORTS_FOLDER_ITEM_ID",
            "CONTRACTS_REPORTS_SCOPE",
            "CONTRACTS_AGENT_BUILD_ID",
            "CONTRACTS_AGENT_DEPLOYMENT_STAGE",
        ]
    )
    result = {
        "ok": True,
        "status": "diagnostics_ready",
        "agent": "contracts",
        "timestamp": _now(),
        "configured_values": configured_values,
        "environment_presence": environment_presence,
        "readiness": {
            "waypoint_configured": _waypoint_base_url() is not None,
            "foundryiq_toolbox_configured": is_toolbox_configured(),
            "sharepoint_report_publishing_configured": sharepoint_report_publishing_configured(),
            "local_fixture_mode": _local_fixture_enabled(),
        },
        "required_for_sharepoint_reports": [
            "CONTRACTS_REPORTS_DRIVE_ID",
            "CONTRACTS_REPORTS_FOLDER_ITEM_ID",
            "Graph permission to upload DriveItem content",
            "Graph permission to create a view link",
        ],
        "session_update_guidance": {
            "immutable_versions": (
                "Each azd deploy creates a new immutable hosted-agent version; sessions can remain "
                "bound to older versions until explicitly reset, stopped, or deleted."
            ),
            "recommended_smoke": (
                "After deploy, invoke responses/invocations with --new-session. For stale hosted "
                "sessions, list sessions and stop or delete the old ones before final smoke."
            ),
            "activity_protocol": (
                "Teams/hired-agent conversations should be treated as channel state; publish/install "
                "the new version and start a fresh chat for deterministic validation."
            ),
        },
    }
    _telemetry_event(
        "contracts_deployment_diagnostics_checked",
        waypoint_configured=result["readiness"]["waypoint_configured"],
        foundryiq_toolbox_configured=result["readiness"]["foundryiq_toolbox_configured"],
        sharepoint_report_publishing_configured=result["readiness"][
            "sharepoint_report_publishing_configured"
        ],
        local_fixture_mode=result["readiness"]["local_fixture_mode"],
        has_build_id=environment_presence["CONTRACTS_AGENT_BUILD_ID"],
    )
    return result


async def _poll_contracts_inbox_impl(
    activity: Any,
    *,
    lookback_minutes: int = 15,
    artifact_type: str | None = None,
) -> dict[str, Any]:
    artifact_type = _coerce_artifact_type(artifact_type)
    if _local_fixture_enabled():
        attachment = _local_contract_attachment(artifact_type=artifact_type)
        try:
            extraction = await extract_contract_pdf(attachment)
        except RuntimeError as exc:
            response = {
                "ok": False,
                "status": "content_understanding_failed",
                "inbox": _contracts_inbox(),
                "lookback_minutes": max(1, lookback_minutes),
                "error": str(exc),
                "pdf": {
                    "file_name": attachment.file_name,
                    "artifact_type": attachment.artifact_type,
                    "content_type": attachment.content_type,
                    "size_bytes": attachment.size_bytes,
                    "sha256": attachment.sha256,
                    "uri": attachment.original_file_uri,
                },
                "note": "The fixture PDF was found, but extraction failed; no completed artifact should be reported.",
            }
            _telemetry_event(
                "contracts_inbox_poll_completed",
                status=response["status"],
                artifact_type=attachment.artifact_type,
                source_mode=attachment.source_mode,
                processed_count=0,
                error_type=type(exc).__name__,
            )
            return response
        state = _load_state()
        artifact = _ensure_mock_artifact(state, artifact_type=artifact_type)
        artifact.update(
            {
                "source_mailbox_id": attachment.mailbox_id,
                "source_message_id": attachment.message_id,
                "source_attachment_id": attachment.attachment_id,
                "source_attachment_sha256": attachment.sha256,
                "original_file_uri": attachment.original_file_uri,
                "extracted_json": extraction.values,
                "evidence": _mock_artifact(owner_user_id=_contracts_owner(), attachment=attachment, extraction=extraction)[
                    "evidence"
                ],
            }
        )
        artifact.setdefault("metadata", {})
        artifact["metadata"].update(
            {
                "source_mode": attachment.source_mode,
                "source_file_name": attachment.file_name,
                "source_size_bytes": attachment.size_bytes,
                "extraction": extraction.metadata,
            }
        )
        checkpoint = {
            "mailbox_id": attachment.mailbox_id,
            "message_id": artifact["source_message_id"],
            "attachment_id": artifact["source_attachment_id"],
            "attachment_sha256": artifact["source_attachment_sha256"],
            "artifact_id": artifact["id"],
            "processed_at": _now(),
            "status": "processed_local_pdf_fixture",
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
        else:
            _save_state(state)
        response = {
            "ok": True,
            "status": "local_pdf_fixture",
            "inbox": _contracts_inbox(),
            "lookback_minutes": max(1, lookback_minutes),
            "processed_count": 1,
            "artifact": artifact,
            "checkpoint": checkpoint,
            "extraction": {
                "status": extraction.status,
                "extractor": extraction.extractor,
                "schema_version": extraction.schema_version,
                "values": extraction.values,
                "confidence": extraction.confidence,
                "source_spans": extraction.source_spans,
                "metadata": extraction.metadata,
            },
            "pdf": {
                "file_name": attachment.file_name,
                "artifact_type": attachment.artifact_type,
                "content_type": attachment.content_type,
                "size_bytes": attachment.size_bytes,
                "sha256": attachment.sha256,
                "uri": attachment.original_file_uri,
            },
            "note": "Local fixture mode read a fixture PDF from disk; no email mailbox was read.",
        }
        _telemetry_event(
            "contracts_inbox_poll_completed",
            status=response["status"],
            artifact_id=artifact["id"],
            artifact_type=attachment.artifact_type,
            source_mode=attachment.source_mode,
            processed_count=response["processed_count"],
        )
        return response

    client = _WaypointContractsClient()
    source = contract_source()
    requester: str | None = None
    try:
        if isinstance(source, HostedMailboxContractSource):
            if not has_agentic_user_identity(activity):
                return {
                    "ok": False,
                    "status": "needs_teams_turn",
                    "inbox": _contracts_inbox(),
                    "note": (
                        "The agent's mailbox can only be read on a Teams turn, as the hired "
                        f"agent. Ask in Teams after emailing a PDF to {_contracts_inbox()}."
                    ),
                }
            token = await agentic_graph_token(activity)
            requester = await requester_email(activity, token)
            attachments = await source.recent_attachments(
                token=token,
                mailbox_id=_contracts_inbox(),
                lookback_minutes=lookback_minutes,
                artifact_type=artifact_type,
                sender=requester,
            )
        else:
            attachments = [
                source.next_contract(
                    mailbox_id=_contracts_inbox(),
                    owner_user_id=_contracts_owner(),
                    artifact_type=artifact_type,
                )
            ]
    except Exception as exc:  # noqa: BLE001 - token, Graph, and lookup failures all surface to the model
        response = {
            "ok": False,
            "status": "mailbox_read_failed",
            "inbox": _contracts_inbox(),
            "lookback_minutes": max(1, lookback_minutes),
            "error": f"{type(exc).__name__}: {exc}",
        }
        _telemetry_event(
            "contracts_inbox_poll_completed",
            status=response["status"],
            artifact_type=artifact_type,
            processed_count=0,
            error_type=type(exc).__name__,
        )
        return response

    results = [
        await _ingest_attachment(client, attachment, lookback_minutes)
        for attachment in attachments
    ]
    processed = [item for item in results if item.get("created")]
    response = {
        "ok": all(item.get("ok") for item in results),
        "status": "processed" if processed else "no_new_attachments",
        "inbox": _contracts_inbox(),
        "requester": requester,
        "lookback_minutes": max(1, lookback_minutes),
        "scanned_count": len(results),
        "processed_count": len(processed),
        "results": results,
    }
    _telemetry_event(
        "contracts_inbox_poll_completed",
        status=response["status"],
        artifact_type=artifact_type,
        source_mode=attachments[0].source_mode if attachments else None,
        processed_count=len(processed),
    )
    return response


async def _ingest_attachment(
    client: _WaypointContractsClient,
    attachment: ContractAttachment,
    lookback_minutes: int,
) -> dict[str, Any]:
    """Register one attachment; extract and record evidence only when it is new."""
    fixture = attachment.source_mode == "local_pdf"
    summary: dict[str, Any] = {
        "file_name": attachment.file_name,
        "artifact_type": attachment.artifact_type,
        "sender": attachment.sender,
        "subject": attachment.subject,
        "sha256": attachment.sha256,
    }
    body = {
        "mailbox_id": attachment.mailbox_id,
        "message_id": attachment.message_id,
        "sender": attachment.sender,
        "owner_user_id": attachment.owner_user_id,
        "subject": attachment.subject,
        "source": "email",
        "attachments": [
            {
                "attachment_id": attachment.attachment_id,
                "sha256": attachment.sha256,
                "file_name": attachment.file_name,
                "content_type": attachment.content_type,
                "original_file_uri": attachment.original_file_uri,
                "artifact_type": attachment.artifact_type,
                "metadata": {
                    "fixture": fixture,
                    "source": "contracts-agent",
                    "source_mode": attachment.source_mode,
                    "artifact_type": attachment.artifact_type,
                    "size_bytes": attachment.size_bytes,
                },
            }
        ],
        "metadata": {
            "lookback_minutes": max(1, lookback_minutes),
            "source_mode": attachment.source_mode,
            "artifact_type": attachment.artifact_type,
        },
    }
    result = await client.request("POST", "/api/contracts/intake/messages/upsert", json_body=body)
    assert isinstance(result, dict)
    intake = result["results"][0]
    artifact_id = str(intake["artifact"]["id"])
    summary["artifact_id"] = artifact_id
    # The upsert is idempotent; skip only artifacts that already hold a usable extraction,
    # so a failed extraction is retried on the next check.
    existing = intake["artifact"]
    if not intake.get("created", True) and existing.get("latest_extraction_id") and existing.get(
        "extraction_status"
    ) in ("succeeded", "partial"):
        return {"ok": True, "created": False, **summary}

    try:
        extracted = await extract_contract_pdf(attachment)
    except RuntimeError as exc:
        return {
            "ok": False,
            "created": True,
            "status": "content_understanding_failed",
            "error": str(exc),
            "note": "Intake registered, but extraction failed; do not treat as processed.",
            **summary,
        }

    await client.request(
        "POST",
        f"/api/contracts/artifacts/{artifact_id}/extractions",
        json_body={
            "extractor": extracted.extractor,
            "schema_version": extracted.schema_version,
            "status": extracted.status,
            "values": extracted.values,
            "confidence": extracted.confidence,
            "source_spans": extracted.source_spans,
            "metadata": {
                **extracted.metadata,
                "fixture": fixture,
                "source_mode": attachment.source_mode,
                "artifact_type": attachment.artifact_type,
            },
        },
    )
    for evidence in _mock_artifact(attachment.owner_user_id, attachment, extracted)["evidence"]:
        await client.request(
            "POST",
            f"/api/contracts/artifacts/{artifact_id}/evidence",
            json_body={
                "source_type": (
                    "waypoint"
                    if evidence["source_type"] == "content_understanding"
                    else "user_file"
                ),
                "claim": evidence["claim"],
                "citation": evidence["citation"],
                "confidence": evidence["confidence"],
                "metadata": {"fixture": fixture, "source_type": evidence["source_type"]},
            },
        )
    return {
        "ok": True,
        "created": True,
        "extraction": {"status": extracted.status, "values": extracted.values},
        **summary,
    }


async def _get_last_contract_impl(
    activity: Any,
    *,
    owner_user_id: str = "",
    artifact_type: str | None = None,
) -> dict[str, Any]:
    artifact_type = _coerce_artifact_type(artifact_type)
    if _local_fixture_enabled():
        state = _load_state()
        artifact = _latest_artifact(
            state,
            owner_user_id,
            artifact_type=artifact_type,
        ) or _ensure_mock_artifact(
            state,
            owner_user_id,
            artifact_type=artifact_type,
        )
        return {
            "ok": True,
            "status": "local_fixture",
            "artifact": artifact,
            "note": "Local fixture mode only; this is not live Waypoint data.",
        }

    client = _WaypointContractsClient()
    owner = await _turn_owner(activity) or owner_user_id or _contracts_owner()
    latest = await client.request(
        "GET",
        "/api/contracts/artifacts/latest",
        params={"owner_user_id": owner, "artifact_type": _artifact_type_filter(artifact_type)},
    )
    assert isinstance(latest, dict)
    detail = await client.request("GET", f"/api/contracts/artifacts/{latest['id']}")
    return {
        "ok": True,
        "status": "api",
        "owner_user_id": owner,
        "artifact": latest,
        "artifact_detail": detail,
    }


async def _draft_contract_report_impl(
    activity: Any,
    *,
    artifact_id: str = "",
    report_type: str = "contract_brief",
    artifact_type: str | None = None,
    markdown: str = "",
    title: str = "",
) -> dict[str, Any]:
    artifact_type = _coerce_artifact_type(artifact_type)
    authored = markdown.strip()
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
        artifact = artifact or _latest_artifact(
            state,
            artifact_type=artifact_type,
        ) or _ensure_mock_artifact(
            state, artifact_type=artifact_type
        )
        report_id = f"report-{artifact['id']}-{report_type}"
        rendered = render_report(
            report_id=report_id,
            markdown=authored or _report_markdown(artifact, report_type),
            output_dir=_state_dir() / "reports",
        )
        title = title.strip() or f"{report_type.replace('_', ' ').title()} for {artifact['id']}"
        try:
            publication = await _publish_rendered_report(
                rendered_docx=rendered.docx_path,
                rendered_markdown=rendered.markdown_path,
                title=title,
                activity=activity,
            )
        except RuntimeError as exc:
            response = {
                "ok": False,
                "status": "report_publish_failed",
                "artifact_id": artifact["id"],
                "files": {
                    "docx": rendered.docx_path.as_uri(),
                    "markdown": rendered.markdown_path.as_uri(),
                },
                "error": str(exc),
                "note": "The report was rendered locally, but publishing failed; no Teams link should be posted.",
            }
            _telemetry_event(
                "contracts_report_draft_completed",
                status=response["status"],
                artifact_id=artifact["id"],
                report_type=report_type,
                publish_failed=True,
            )
            return response
        report = {
            "id": report_id,
            "artifact_id": artifact["id"],
            "report_type": report_type,
            "file_url": publication["file_url"],
            "teams_link_url": publication["teams_link_url"],
            "share_status": _api_share_status(publication),
            "created_at": _now(),
            "metadata": {
                "fixture": True,
                **publication["metadata"],
                "storage": publication["storage"],
                "web_url": publication["web_url"],
                "share_url": publication["share_url"],
            },
        }
        reports = [item for item in state["reports"] if isinstance(item, dict)]
        reports = [item for item in reports if item.get("id") != report_id]
        reports.append(report)
        state["reports"] = reports
        _save_state(state)
        response = {
            "ok": True,
            "status": "local_fixture",
            "report": report,
            "files": {
                "docx": rendered.docx_path.as_uri(),
                "markdown": rendered.markdown_path.as_uri(),
            },
            "publication": publication,
            "note": (
                "Local fixture mode rendered DOCX and Markdown reports. "
                f"Publication storage: {publication['storage']}."
            ),
        }
        _telemetry_event(
            "contracts_report_draft_completed",
            status=response["status"],
            artifact_id=artifact["id"],
            report_type=report_type,
            storage=publication["storage"],
            share_status=publication["share_status"],
        )
        return response

    client = _WaypointContractsClient()
    turn_owner = await _turn_owner(activity)
    if not artifact_id:
        latest = await client.request(
            "GET",
            "/api/contracts/artifacts/latest",
            params={
                "owner_user_id": turn_owner or _contracts_owner(),
                "artifact_type": _artifact_type_filter(artifact_type),
            },
        )
        assert isinstance(latest, dict)
        artifact_id = str(latest["id"])
        detail = await client.request("GET", f"/api/contracts/artifacts/{artifact_id}")
        assert isinstance(detail, dict)
    else:
        detail = await client.request("GET", f"/api/contracts/artifacts/{artifact_id}")
        assert isinstance(detail, dict)
        owner = str((detail.get("artifact") or {}).get("owner_user_id") or "").lower()
        if turn_owner and owner != turn_owner:
            raise RuntimeError("That artifact does not belong to the requester.")

    report_id = f"report-{artifact_id}-{report_type}"
    rendered = render_report(
        report_id=report_id,
        markdown=authored or _report_markdown(detail, report_type),
        output_dir=_state_dir() / "reports",
    )
    title = title.strip() or f"{report_type.replace('_', ' ').title()} for {artifact_id}"
    try:
        publication = await _publish_rendered_report(
            rendered_docx=rendered.docx_path,
            rendered_markdown=rendered.markdown_path,
            title=title,
            activity=activity,
        )
    except RuntimeError as exc:
        response = {
            "ok": False,
            "status": "report_publish_failed",
            "artifact_id": artifact_id,
            "files": {
                "docx": rendered.docx_path.as_uri(),
                "markdown": rendered.markdown_path.as_uri(),
            },
            "error": str(exc),
            "note": "The report was rendered locally, but publishing failed; no Teams link should be posted.",
        }
        _telemetry_event(
            "contracts_report_draft_completed",
            status=response["status"],
            artifact_id=artifact_id,
            report_type=report_type,
            publish_failed=True,
        )
        return response

    report = await client.request(
        "POST",
        f"/api/contracts/artifacts/{artifact_id}/reports",
        json_body={
            "report_type": report_type,
            "file_url": publication["file_url"],
            "title": title,
            "share_status": _api_share_status(publication),
            "shared_with": _publication_shared_with(publication),
            "metadata": {
                "fixture": publication["storage"] == "local",
                **publication["metadata"],
                "storage": publication["storage"],
                "teams_link_url": publication["teams_link_url"],
                "web_url": publication["web_url"],
                "share_url": publication["share_url"],
            },
        },
    )
    response = {
        "ok": True,
        "status": "report_recorded",
        "artifact_id": artifact_id,
        "report": report,
        "teams_link_url": publication["teams_link_url"],
        "publication": publication,
        "files": {
            "docx": rendered.docx_path.as_uri(),
            "markdown": rendered.markdown_path.as_uri(),
        },
        "note": (
            "Waypoint API recorded the DOCX report. "
            f"Publication storage: {publication['storage']}."
        ),
    }
    _telemetry_event(
        "contracts_report_draft_completed",
        status=response["status"],
        artifact_id=artifact_id,
        report_type=report_type,
        storage=publication["storage"],
        share_status=publication["share_status"],
    )
    return response


def _summarize_invoice_detail(detail: dict[str, Any]) -> dict[str, Any]:
    supplier = detail.get("supplier") if isinstance(detail.get("supplier"), dict) else {}
    scenario = detail.get("scenario") if isinstance(detail.get("scenario"), dict) else {}
    findings = [item for item in detail.get("findings", []) if isinstance(item, dict)]
    evidence = [item for item in detail.get("evidence", []) if isinstance(item, dict)]
    return {
        "id": detail.get("id"),
        "invoice_number": detail.get("invoice_number"),
        "supplier_id": detail.get("supplier_id"),
        "supplier_name": supplier.get("name"),
        "scenario_id": detail.get("scenario_id"),
        "scenario_name": scenario.get("name"),
        "status": detail.get("status"),
        "currency": detail.get("currency"),
        "total_amount": detail.get("total_amount"),
        "invoice_date": detail.get("invoice_date"),
        "due_date": detail.get("due_date"),
        "line_count": len(detail.get("lines", [])) if isinstance(detail.get("lines"), list) else 0,
        "finding_count": len(findings),
        "evidence_count": len(evidence),
        "findings": [
            {
                "id": finding.get("id"),
                "severity": finding.get("severity"),
                "status": finding.get("status"),
                "category": finding.get("category"),
                "summary": finding.get("summary"),
                "overpayment_amount": finding.get("overpayment_amount"),
                "contract_document_ids": finding.get("contract_document_ids", []),
                "policy_ids": finding.get("policy_ids", []),
            }
            for finding in findings
        ],
    }


async def _query_invoices_impl(
    activity: Any,
    *,
    invoice_id: str = "",
    supplier_id: str = "",
    invoice_number: str = "",
    include_context: bool = True,
    limit: int = 5,
) -> dict[str, Any]:
    if _local_fixture_enabled():
        response = {
            "ok": False,
            "status": "waypoint_api_required",
            "note": (
                "Invoice queries use the Waypoint records/work APIs; set "
                "WAYPOINT_API_BASE_URL to query seeded Aspire data."
            ),
        }
        _telemetry_event(
            "contracts_invoice_query_completed",
            status=response["status"],
            returned_count=0,
            include_context=include_context,
        )
        return response

    client = _WaypointContractsClient()
    try:
        limit = int(limit or 5)
    except (TypeError, ValueError):
        limit = 5
    limit = max(1, min(limit, 10))
    selected_id = invoice_id.strip()

    if not selected_id:
        params = {
            key: value
            for key, value in {
                "supplier_id": supplier_id.strip(),
                "invoice_number": invoice_number.strip(),
            }.items()
            if value
        }
        matches = await client.request("GET", "/api/invoices", params=params or None)
        assert isinstance(matches, list)
        selected = matches[:limit]
    else:
        selected = [{"id": selected_id}]
        matches = selected

    details: list[dict[str, Any]] = []
    for invoice in selected:
        invoice_detail_id = str(invoice.get("id") or "")
        if not invoice_detail_id:
            continue
        detail = await client.request("GET", f"/api/invoices/{invoice_detail_id}")
        assert isinstance(detail, dict)
        details.append(detail)

    context = None
    if include_context and len(details) == 1:
        context = await client.request(
            "GET",
            f"/api/invoices/{details[0]['id']}/context",
            params={"include_sensitive": "false"},
        )
        assert isinstance(context, dict)

    response = {
        "ok": True,
        "status": "api",
        "query": {
            "invoice_id": selected_id or None,
            "supplier_id": supplier_id.strip() or None,
            "invoice_number": invoice_number.strip() or None,
            "limit": limit,
        },
        "match_count": len(matches),
        "returned_count": len(details),
        "invoices": [_summarize_invoice_detail(detail) for detail in details],
        "context": context,
        "note": (
            "Invoice data came from the Waypoint records/work APIs. Contract, policy, "
            "and evidence text in context is API-backed; live contract/policy "
            "interpretation should still be grounded through the FoundryIQ toolbox."
        ),
    }
    _telemetry_event(
        "contracts_invoice_query_completed",
        status=response["status"],
        match_count=response["match_count"],
        returned_count=response["returned_count"],
        include_context=include_context,
        had_context=context is not None,
    )
    return response


def contracts_tools() -> list[Tool]:
    return [
        Tool(
            name="get_contracts_capabilities",
            description=(
                "Report what the Contracts agent can do now and whether it is using the "
                "Waypoint Contracts API or local fixture mode."
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
            name="get_deployment_diagnostics",
            description=(
                "Return non-secret deployment diagnostics for smoke testing: configured "
                "environment presence, SharePoint report readiness, build markers, and "
                "session/update rollout guidance."
            ),
            parameters={
                "type": "object",
                "properties": {},
                "required": [],
                "additionalProperties": False,
            },
            impl=_get_deployment_diagnostics_impl,
        ),
        Tool(
            name="poll_contracts_inbox",
            description=(
                "Check whether the user has emailed PDFs to the contracts inbox and register "
                "them in Waypoint. Use when the user says they sent or emailed a contract or "
                "invoice, or asks whether the agent got their email. Hosted (Teams only), it "
                "reads the agent's own mailbox for messages from the asking user over the "
                "lookback window and extracts only new attachments (intake is idempotent). "
                "Locally, it processes a fixture PDF."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "lookback_minutes": {
                        "type": "integer",
                        "minimum": 1,
                        "description": "How far back to scan the inbox (default 15).",
                    },
                    "artifact_type": {
                        "type": "string",
                        "enum": ["contract", "invoice"],
                        "description": "Force the artifact kind; otherwise inferred from subject/file name.",
                    },
                },
                "required": [],
                "additionalProperties": False,
            },
            impl=_poll_contracts_inbox_impl,
        ),
        Tool(
            name="get_last_contract",
            description=(
                "Resolve the latest contract artifact for the signed-in user or supplied "
                "owner_user_id, using the Waypoint Contracts API when configured."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "owner_user_id": {
                        "type": "string",
                        "description": "Optional user id/email whose latest contract should be resolved.",
                    },
                    "artifact_type": {
                        "type": "string",
                        "enum": ["contract", "invoice"],
                        "description": "Optional artifact kind filter.",
                    },
                },
                "required": [],
                "additionalProperties": False,
            },
            impl=_get_last_contract_impl,
        ),
        Tool(
            name="draft_contract_report",
            description=(
                "Render a Word (.docx) contract report from Markdown you write, publish it, "
                "and record it on the artifact. On a Teams turn the document is saved to the "
                "agent's own OneDrive and shared with the requesting user; elsewhere it is "
                "saved locally. Returns teams_link_url when the document is shared."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "markdown": {
                        "type": "string",
                        "description": (
                            "Full report body in Markdown (headings, lists, tables). Ground "
                            "contract claims in foundry_iq_retrieve results and cite sources "
                            "inline. If omitted, a minimal metadata summary is rendered."
                        ),
                    },
                    "title": {
                        "type": "string",
                        "description": "Document title.",
                    },
                    "artifact_id": {
                        "type": "string",
                        "description": "Contract artifact id to report on.",
                    },
                    "report_type": {
                        "type": "string",
                        "description": "Report type, such as contract_brief or diligence_memo.",
                    },
                    "artifact_type": {
                        "type": "string",
                        "enum": ["contract", "invoice"],
                        "description": "Optional artifact kind to use when artifact_id is omitted.",
                    },
                },
                "required": [],
                "additionalProperties": False,
            },
            impl=_draft_contract_report_impl,
        ),
        Tool(
            name="query_invoices",
            description=(
                "Query seeded or live invoice data through the Waypoint records/work APIs. "
                "Use this for conversation about prior invoices, findings, evidence, and invoice context."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "invoice_id": {
                        "type": "string",
                        "description": "Optional invoice id for an exact context lookup.",
                    },
                    "supplier_id": {
                        "type": "string",
                        "description": "Optional supplier id filter for invoice search.",
                    },
                    "invoice_number": {
                        "type": "string",
                        "description": "Optional exact invoice number filter.",
                    },
                    "include_context": {
                        "type": "boolean",
                        "description": (
                            "Whether to include decision-relevant context when exactly "
                            "one invoice is selected."
                        ),
                    },
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 10,
                        "description": "Maximum number of invoice details to return for list queries.",
                    },
                },
                "required": [],
                "additionalProperties": False,
            },
            impl=_query_invoices_impl,
        ),
    ]
