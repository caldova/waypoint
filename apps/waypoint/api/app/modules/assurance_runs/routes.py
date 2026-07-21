"""API routes for tenant-authenticated invoice assurance triggers."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from ...common.auth import UserContext, require_reader
from ...common.database import get_waypoint_repository
from ...common.foundry_responses import FoundryResponsesClient
from ...common.repository import WaypointRepository
from ...common.settings import Settings, get_settings
from ...common.tracer import trace_span
from .schemas import (
    AssuranceRunTriggerResult,
    BatchAssuranceRequest,
    BatchAssuranceTriggerResult,
)
from .service import (
    AssuranceRunsService,
    AssuranceTriggerUnavailableError,
    InvoiceNotFoundError,
)

router = APIRouter(prefix="/invoices", tags=["assurance-runs"])


async def get_assurance_runs_service(
    repository: Annotated[WaypointRepository, Depends(get_waypoint_repository)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AssuranceRunsService:
    return AssuranceRunsService(
        repository,
        settings,
        FoundryResponsesClient(
            project_endpoint=settings.foundry_endpoint,
            api_version=settings.foundry_responses_api_version,
            timeout_seconds=settings.foundry_start_timeout_seconds,
        ),
    )


@router.post(
    "/assurance-runs/batch",
    response_model=BatchAssuranceTriggerResult,
    status_code=status.HTTP_202_ACCEPTED,
)
async def trigger_batch_invoice_assurance(
    request: BatchAssuranceRequest,
    user: Annotated[UserContext, Depends(require_reader)],
    service: Annotated[AssuranceRunsService, Depends(get_assurance_runs_service)],
) -> BatchAssuranceTriggerResult:
    assert user.email is not None
    with trace_span(
        "trigger_batch_invoice_assurance_endpoint",
        attributes={"invoice_count": len(request.invoice_ids)},
    ):
        return await service.trigger_batch(
            invoice_ids=request.invoice_ids,
            actor=user.email,
        )


@router.post(
    "/{invoice_id}/assurance-runs",
    response_model=AssuranceRunTriggerResult,
    status_code=status.HTTP_202_ACCEPTED,
)
async def trigger_invoice_assurance(
    invoice_id: str,
    user: Annotated[UserContext, Depends(require_reader)],
    service: Annotated[AssuranceRunsService, Depends(get_assurance_runs_service)],
) -> AssuranceRunTriggerResult:
    assert user.email is not None
    with trace_span(
        "trigger_invoice_assurance_endpoint",
        attributes={"invoice_id": invoice_id},
    ):
        try:
            return await service.trigger(invoice_id=invoice_id, actor=user.email)
        except InvoiceNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except AssuranceTriggerUnavailableError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
