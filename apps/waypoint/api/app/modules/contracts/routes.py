"""API routes for the Waypoint Contracts API (email intake, artifacts, evidence, reports)."""

from collections.abc import Awaitable
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from ...common.auth import UserContext, require_reader, require_writer
from ...common.database import get_waypoint_repository
from ...common.repository import WaypointRepository
from ...common.tracer import trace_span
from ..runs.schemas import AgentRun
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
    IntakeMessageResult,
    IntakeMessageUpsert,
)
from .service import ContractNotFoundError, ContractsService

router = APIRouter(prefix="/contracts", tags=["contracts"])

# Principals minted for app-only callers (service principals, managed identities, API keys) are
# not people, so they cannot stand in for "the signed-in user" in a latest-artifact lookup.
_NON_USER_PRINCIPAL_SUFFIXES = ("@msal-app.waypoint.local", "@api-key.waypoint.local")


async def get_contracts_service(
    repository: Annotated[WaypointRepository, Depends(get_waypoint_repository)],
) -> ContractsService:
    return ContractsService(repository)


Service = Annotated[ContractsService, Depends(get_contracts_service)]
Reader = Annotated[UserContext, Depends(require_reader)]
Writer = Annotated[UserContext, Depends(require_writer)]


@router.post("/intake/messages/upsert", response_model=IntakeMessageResult)
async def upsert_intake_message(
    message: IntakeMessageUpsert, user: Writer, service: Service
) -> IntakeMessageResult:
    """Register each attachment of a mailbox message as an artifact (idempotent)."""

    with trace_span(
        "contracts_upsert_intake_message_endpoint",
        attributes={"attachment_count": len(message.attachments)},
    ):
        return await service.upsert_intake_message(message, actor=_actor(user))


@router.get("/artifacts/latest", response_model=Artifact)
async def get_latest_artifact(
    user: Reader,
    service: Service,
    owner_user_id: str | None = Query(
        default=None, description="Owner to resolve. Defaults to the signed-in user."
    ),
    artifact_type: ArtifactType = Query(default="contract"),
) -> Artifact:
    owner = owner_user_id or _signed_in_user(user)
    with trace_span("contracts_get_latest_artifact_endpoint", attributes={"type": artifact_type}):
        artifact = await service.get_latest_artifact(owner, artifact_type)
    if artifact is None:
        raise HTTPException(
            status_code=404, detail=f"No {artifact_type} artifact found for '{owner}'."
        )
    return artifact


@router.get("/artifacts/{artifact_id}", response_model=ArtifactDetail)
async def get_artifact(artifact_id: str, _user: Reader, service: Service) -> ArtifactDetail:
    with trace_span("contracts_get_artifact_endpoint", attributes={"artifact_id": artifact_id}):
        return await _not_found_as_404(service.get_artifact_detail(artifact_id))


@router.patch("/artifacts/{artifact_id}", response_model=Artifact)
async def update_artifact(
    artifact_id: str, update: ArtifactUpdate, _user: Writer, service: Service
) -> Artifact:
    with trace_span("contracts_update_artifact_endpoint", attributes={"artifact_id": artifact_id}):
        return await _not_found_as_404(service.update_artifact(artifact_id, update))


@router.post(
    "/artifacts/{artifact_id}/extractions", response_model=ArtifactExtraction, status_code=201
)
async def add_extraction(
    artifact_id: str, extraction: ArtifactExtractionCreate, user: Writer, service: Service
) -> ArtifactExtraction:
    with trace_span("contracts_add_extraction_endpoint", attributes={"artifact_id": artifact_id}):
        return await _not_found_as_404(
            service.add_extraction(artifact_id, extraction, actor=_actor(user))
        )


@router.post("/artifacts/{artifact_id}/evidence", response_model=ArtifactEvidence, status_code=201)
async def add_evidence(
    artifact_id: str, evidence: ArtifactEvidenceCreate, user: Writer, service: Service
) -> ArtifactEvidence:
    with trace_span("contracts_add_evidence_endpoint", attributes={"artifact_id": artifact_id}):
        return await _not_found_as_404(
            service.add_evidence(artifact_id, evidence, actor=_actor(user))
        )


@router.post("/artifacts/{artifact_id}/runs", response_model=AgentRun, status_code=201)
async def start_run(
    artifact_id: str, run: ArtifactRunCreate, user: Writer, service: Service
) -> AgentRun:
    with trace_span("contracts_start_run_endpoint", attributes={"artifact_id": artifact_id}):
        return await _not_found_as_404(service.start_run(artifact_id, run, actor=_actor(user)))


@router.post("/artifacts/{artifact_id}/reports", response_model=ArtifactReport, status_code=201)
async def add_report(
    artifact_id: str, report: ArtifactReportCreate, user: Writer, service: Service
) -> ArtifactReport:
    with trace_span("contracts_add_report_endpoint", attributes={"artifact_id": artifact_id}):
        return await _not_found_as_404(service.add_report(artifact_id, report, actor=_actor(user)))


@router.post("/artifacts/{artifact_id}/reports/{report_id}/shares", response_model=ArtifactReport)
async def record_report_share(
    artifact_id: str,
    report_id: str,
    update: ArtifactReportShareUpdate,
    user: Writer,
    service: Service,
) -> ArtifactReport:
    with trace_span(
        "contracts_record_report_share_endpoint",
        attributes={"artifact_id": artifact_id, "report_id": report_id},
    ):
        return await _not_found_as_404(
            service.record_report_share(artifact_id, report_id, update, actor=_actor(user))
        )


async def _not_found_as_404[T](awaitable: Awaitable[T]) -> T:
    try:
        return await awaitable
    except ContractNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def _actor(user: UserContext) -> str:
    assert user.email is not None
    return user.email


def _signed_in_user(user: UserContext) -> str:
    email = user.email or ""
    if not email or email.endswith(_NON_USER_PRINCIPAL_SUFFIXES):
        raise HTTPException(
            status_code=422,
            detail="owner_user_id is required when the caller is not a signed-in user.",
        )
    return email
