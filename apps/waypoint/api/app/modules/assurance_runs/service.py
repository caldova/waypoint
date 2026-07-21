"""Business logic for starting invoice assurance without blocking the API."""

from __future__ import annotations

import asyncio
import logging
from uuid import uuid4

from ...common.foundry_responses import FoundryInvocationError, FoundryResponsesClient
from ...common.repository import WaypointRepository
from ...common.settings import Settings
from ...common.tracer import trace
from ..runs.schemas import AgentRunCreate, AgentRunUpdate
from ..runs.service import RunsService
from .schemas import (
    AssuranceRunTriggerResult,
    BatchAssuranceItemResult,
    BatchAssuranceTriggerResult,
)

logger = logging.getLogger(__name__)

# Keep hosted-agent startup pressure bounded even when the API accepts the full batch.
BATCH_ASSURANCE_CONCURRENCY = 4


class InvoiceNotFoundError(ValueError):
    """Raised when a trigger references an invoice outside Waypoint truth."""


class AssuranceTriggerUnavailableError(RuntimeError):
    """Raised when the deployment cannot start the configured orchestrator."""


class AssuranceRunsService:
    def __init__(
        self,
        repository: WaypointRepository,
        settings: Settings,
        foundry_client: FoundryResponsesClient,
    ) -> None:
        self.repository = repository
        self.settings = settings
        self.foundry_client = foundry_client
        self.runs = RunsService(repository)

    @trace
    async def trigger(self, *, invoice_id: str, actor: str) -> AssuranceRunTriggerResult:
        invoice = await self.repository.get_invoice_detail(invoice_id)
        if invoice is None:
            raise InvoiceNotFoundError(f"Invoice '{invoice_id}' not found.")
        if not self.settings.foundry_endpoint:
            raise AssuranceTriggerUnavailableError(
                "Foundry invoice assurance is not configured for this deployment."
            )

        agent_name = self.settings.foundry_orchestrator_agent_name
        run, created = await self.runs.create_or_reuse_agent_run(
            AgentRunCreate(
                name=f"assurance:{invoice_id}",
                status="pending",
                summary=f"Invoice assurance requested for {invoice.invoice_number}.",
                foundry_agent_name=agent_name,
                metadata={
                    "invoice_id": invoice_id,
                    "invoice_number": invoice.invoice_number,
                    "trigger": "waypoint-user",
                },
                idempotency_key=f"user-trigger:{invoice_id}:{uuid4().hex}",
            ),
            actor=actor,
        )
        if not created:
            return AssuranceRunTriggerResult(
                run=run,
                reused=True,
                foundry_response_id=run.foundry_response_id,
            )

        try:
            started = await self.foundry_client.start_background(
                agent_name=agent_name,
                prompt=f"Run the full invoice-assurance review for invoice {invoice_id}.",
            )
        except FoundryInvocationError as exc:
            failed = await self.runs.update_agent_run(
                run.id,
                AgentRunUpdate(
                    status="failed",
                    summary="Foundry rejected invoice assurance startup.",
                    metadata={
                        **run.metadata,
                        "trigger_error": str(exc),
                    },
                ),
            )
            if failed is None:
                raise RuntimeError(
                    f"Reserved run '{run.id}' disappeared after Foundry startup failed."
                ) from exc
            raise AssuranceTriggerUnavailableError(str(exc)) from exc

        running = await self.runs.update_agent_run(
            run.id,
            AgentRunUpdate(
                status="running",
                foundry_response_id=started.response_id,
                summary=f"Invoice assurance is {started.status}.",
                metadata={
                    **run.metadata,
                    "foundry_start_status": started.status,
                },
            ),
        )
        if running is None:
            raise RuntimeError(f"Reserved run '{run.id}' disappeared after Foundry startup.")
        return AssuranceRunTriggerResult(
            run=running,
            reused=False,
            foundry_response_id=started.response_id,
        )

    @trace
    async def trigger_batch(
        self,
        *,
        invoice_ids: list[str],
        actor: str,
    ) -> BatchAssuranceTriggerResult:
        semaphore = asyncio.Semaphore(BATCH_ASSURANCE_CONCURRENCY)

        async def trigger_one(invoice_id: str) -> BatchAssuranceItemResult:
            async with semaphore:
                try:
                    result = await self.trigger(invoice_id=invoice_id, actor=actor)
                except InvoiceNotFoundError:
                    return BatchAssuranceItemResult(
                        invoice_id=invoice_id,
                        outcome="not_found",
                    )
                except AssuranceTriggerUnavailableError:
                    logger.warning(
                        "Batch assurance startup failed for invoice %s",
                        invoice_id,
                    )
                    return BatchAssuranceItemResult(
                        invoice_id=invoice_id,
                        outcome="start_failed",
                    )
                except Exception:
                    logger.exception(
                        "Unexpected batch assurance startup failure for invoice %s",
                        invoice_id,
                    )
                    return BatchAssuranceItemResult(
                        invoice_id=invoice_id,
                        outcome="start_failed",
                    )

                invoice_number = result.run.metadata.get("invoice_number")
                return BatchAssuranceItemResult(
                    invoice_id=invoice_id,
                    invoice_number=(invoice_number if isinstance(invoice_number, str) else None),
                    outcome="reused" if result.reused else "accepted",
                    run_id=result.run.id,
                    run_status=result.run.status,
                    foundry_response_id=result.foundry_response_id,
                )

        items = await asyncio.gather(*(trigger_one(invoice_id) for invoice_id in invoice_ids))
        counts = {
            outcome: sum(item.outcome == outcome for item in items)
            for outcome in ("accepted", "reused", "not_found", "start_failed")
        }
        return BatchAssuranceTriggerResult(
            items=items,
            total=len(items),
            accepted=counts["accepted"],
            reused=counts["reused"],
            not_found=counts["not_found"],
            start_failed=counts["start_failed"],
        )
