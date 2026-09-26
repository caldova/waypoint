"""Business logic for the Waypoint Contracts API."""

import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from ...common.repository import WaypointRepository
from ...common.tracer import trace
from ..runs.schemas import AgentRun, AgentRunCreate
from ..runs.service import RunsService
from .schemas import (
    Artifact,
    ArtifactDetail,
    ArtifactEvidence,
    ArtifactEvidenceCreate,
    ArtifactExtraction,
    ArtifactExtractionCreate,
    ArtifactReport,
    ArtifactReportCreate,
    ArtifactReportShareUpdate,
    ArtifactRunCreate,
    ArtifactType,
    ArtifactUpdate,
    IntakeAttachmentResult,
    IntakeMessageCheckpoint,
    IntakeMessageResult,
    IntakeMessageUpsert,
    ShareEvent,
)

_CAS_ATTEMPTS = 5


class ContractNotFoundError(LookupError):
    """Raised when an artifact or report does not exist."""


def intake_key(mailbox_id: str, message_id: str, attachment_id: str, sha256: str) -> str:
    """Stable idempotency identity for a mailbox attachment.

    Hashing a JSON array (rather than joining with a separator) keeps the key unambiguous even
    when Graph ids contain separator characters.
    """

    identity = json.dumps([mailbox_id, message_id, attachment_id, sha256.lower()])
    return f"intake-{hashlib.sha256(identity.encode()).hexdigest()}"


class ContractsService:
    """Service boundary for contract/invoice artifacts and their append-only records."""

    def __init__(self, repository: WaypointRepository) -> None:
        self.repository = repository

    @trace
    async def upsert_intake_message(
        self, message: IntakeMessageUpsert, *, actor: str
    ) -> IntakeMessageResult:
        now = _now()
        received_at = _utc(message.received_at) if message.received_at else now
        owner = message.owner_user_id or message.sender
        results: list[IntakeAttachmentResult] = []
        for attachment in message.attachments:
            key = intake_key(
                message.mailbox_id, message.message_id, attachment.attachment_id, attachment.sha256
            )
            candidate = Artifact(
                id=f"artifact-{uuid4().hex}",
                type=attachment.artifact_type,
                owner_user_id=owner,
                source=message.source,
                source_mailbox_id=message.mailbox_id,
                source_message_id=message.message_id,
                source_attachment_id=attachment.attachment_id,
                source_attachment_sha256=attachment.sha256,
                intake_key=key,
                file_name=attachment.file_name,
                content_type=attachment.content_type,
                size_bytes=attachment.size_bytes,
                sender=message.sender,
                subject=message.subject,
                original_file_uri=attachment.original_file_uri,
                received_at=received_at,
                created_by=actor,
                created_at=now,
                updated_at=now,
                metadata={**message.metadata, **attachment.metadata},
            )
            checkpoint = IntakeMessageCheckpoint(
                id=key,
                mailbox_id=message.mailbox_id,
                message_id=message.message_id,
                attachment_id=attachment.attachment_id,
                attachment_sha256=attachment.sha256,
                artifact_id=candidate.id,
                processed_at=now,
            )
            artifact, created = await self.repository.register_contract_intake(
                checkpoint, candidate
            )
            results.append(
                IntakeAttachmentResult(
                    attachment_id=attachment.attachment_id,
                    attachment_sha256=attachment.sha256,
                    created=created,
                    artifact=artifact,
                )
            )
        return IntakeMessageResult(
            mailbox_id=message.mailbox_id, message_id=message.message_id, results=results
        )

    @trace
    async def get_latest_artifact(
        self, owner_user_id: str, artifact_type: ArtifactType
    ) -> Artifact | None:
        return await self.repository.get_latest_contract_artifact(
            owner_user_id.strip().lower(), artifact_type
        )

    @trace
    async def get_artifact_detail(self, artifact_id: str) -> ArtifactDetail:
        artifact = await self._require_artifact(artifact_id)
        return ArtifactDetail(
            artifact=artifact,
            extractions=await self.repository.list_contract_extractions(artifact_id),
            evidence=await self.repository.list_contract_evidence(artifact_id),
            reports=await self.repository.list_contract_reports(artifact_id),
        )

    @trace
    async def update_artifact(self, artifact_id: str, update: ArtifactUpdate) -> Artifact:
        changes: dict[str, object] = {}
        if update.processing_status is not None:
            changes["processing_status"] = update.processing_status

        def apply(current: Artifact) -> dict[str, object]:
            patch = dict(changes)
            if update.metadata:
                patch["metadata"] = {**current.metadata, **update.metadata}
            return patch

        return await self._update_artifact(artifact_id, apply)

    @trace
    async def add_extraction(
        self, artifact_id: str, extraction_create: ArtifactExtractionCreate, *, actor: str
    ) -> ArtifactExtraction:
        await self._require_artifact(artifact_id)
        extraction = ArtifactExtraction(
            id=f"extraction-{uuid4().hex}",
            artifact_id=artifact_id,
            created_by=actor,
            created_at=_now(),
            **extraction_create.model_dump(),
        )
        await self.repository.save_contract_extraction(extraction)

        def apply(_current: Artifact) -> dict[str, object]:
            patch: dict[str, object] = {
                "extraction_status": extraction.status,
                "latest_extraction_id": extraction.id,
            }
            # Only a usable extraction replaces the artifact's structured values; a failed
            # attempt is recorded (append-only) without discarding earlier good values.
            if extraction.status in ("succeeded", "partial"):
                patch["extracted_json"] = extraction.values
            return patch

        await self._update_artifact(artifact_id, apply)
        return extraction

    @trace
    async def add_evidence(
        self, artifact_id: str, evidence_create: ArtifactEvidenceCreate, *, actor: str
    ) -> ArtifactEvidence:
        await self._require_artifact(artifact_id)
        evidence = ArtifactEvidence(
            id=f"evidence-{uuid4().hex}",
            artifact_id=artifact_id,
            created_by=actor,
            created_at=_now(),
            **evidence_create.model_dump(),
        )
        await self.repository.save_contract_evidence(evidence)
        return evidence

    @trace
    async def start_run(
        self, artifact_id: str, run_create: ArtifactRunCreate, *, actor: str
    ) -> AgentRun:
        """Open (or reuse the active) agent run anchor for an artifact."""

        await self._require_artifact(artifact_id)
        run, _created = await RunsService(self.repository).create_or_reuse_agent_run(
            AgentRunCreate(
                name=f"contracts:{artifact_id}",
                status=run_create.status,
                summary=run_create.summary,
                foundry_agent_name=run_create.foundry_agent_name,
                foundry_conversation_id=run_create.foundry_conversation_id,
                app_insights_operation_id=run_create.app_insights_operation_id,
                idempotency_key=run_create.idempotency_key,
                metadata={**run_create.metadata, "artifact_id": artifact_id},
            ),
            actor=actor,
        )

        def apply(current: Artifact) -> dict[str, object]:
            if run.id in current.run_ids:
                return {}
            return {"run_ids": [*current.run_ids, run.id]}

        await self._update_artifact(artifact_id, apply)
        return run

    @trace
    async def add_report(
        self, artifact_id: str, report_create: ArtifactReportCreate, *, actor: str
    ) -> ArtifactReport:
        await self._require_artifact(artifact_id)
        now = _now()
        data = report_create.model_dump(mode="json")
        share_events = []
        if report_create.share_status != "not_shared":
            share_events.append(
                ShareEvent(
                    share_status=report_create.share_status,
                    shared_with=report_create.shared_with,
                    recorded_by=actor,
                    recorded_at=now,
                )
            )
        report = ArtifactReport(
            id=f"report-{uuid4().hex}",
            artifact_id=artifact_id,
            share_events=share_events,
            created_by=actor,
            created_at=now,
            updated_at=now,
            **data,
        )
        await self.repository.save_contract_report(report)
        return report

    @trace
    async def record_report_share(
        self,
        artifact_id: str,
        report_id: str,
        update: ArtifactReportShareUpdate,
        *,
        actor: str,
    ) -> ArtifactReport:
        for _attempt in range(_CAS_ATTEMPTS):
            current = await self.repository.get_contract_report(report_id)
            if current is None or current.artifact_id != artifact_id:
                raise ContractNotFoundError(
                    f"Report '{report_id}' not found for artifact '{artifact_id}'."
                )
            now = _now()
            event = ShareEvent(
                share_status=update.share_status,
                shared_with=update.shared_with,
                share_url=str(update.share_url) if update.share_url else None,
                approved_by=update.approved_by,
                recorded_by=actor,
                recorded_at=now,
                note=update.note,
            )
            updated = current.model_copy(
                update={
                    "share_status": update.share_status,
                    "shared_with": update.shared_with or current.shared_with,
                    "share_events": [*current.share_events, event],
                    "updated_at": _after(now, current.updated_at),
                }
            )
            if await self.repository.compare_and_swap_contract_report(updated, current):
                return updated
        raise RuntimeError(f"Report '{report_id}' changed repeatedly during share update.")

    async def _require_artifact(self, artifact_id: str) -> Artifact:
        artifact = await self.repository.get_contract_artifact(artifact_id)
        if artifact is None:
            raise ContractNotFoundError(f"Artifact '{artifact_id}' not found.")
        return artifact

    async def _update_artifact(
        self, artifact_id: str, apply: Callable[[Artifact], dict[str, object]]
    ) -> Artifact:
        for _attempt in range(_CAS_ATTEMPTS):
            current = await self._require_artifact(artifact_id)
            patch = apply(current)
            if not patch:
                return current
            updated = current.model_copy(
                update={**patch, "updated_at": _after(_now(), current.updated_at)}
            )
            if await self.repository.compare_and_swap_contract_artifact(updated, current):
                return updated
        raise RuntimeError(f"Artifact '{artifact_id}' changed repeatedly during update.")


def _now() -> datetime:
    return datetime.now(UTC)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _after(candidate: datetime, previous: datetime) -> datetime:
    """Guarantee a strictly newer timestamp so compare-and-swap tokens always change."""

    return candidate if candidate > previous else previous + timedelta(microseconds=1)
