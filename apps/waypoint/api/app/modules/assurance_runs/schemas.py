"""Schemas for user-triggered invoice assurance."""

from typing import Literal

from pydantic import BaseModel, field_validator

from ..runs.schemas import AgentRun

MAX_BATCH_ASSURANCE_INVOICES = 25


class AssuranceRunTriggerResult(BaseModel):
    run: AgentRun
    reused: bool
    foundry_response_id: str | None = None


class BatchAssuranceRequest(BaseModel):
    invoice_ids: list[str]

    @field_validator("invoice_ids")
    @classmethod
    def normalize_invoice_ids(cls, invoice_ids: list[str]) -> list[str]:
        """Normalize and deduplicate IDs before enforcing the accepted batch size."""

        normalized: list[str] = []
        seen: set[str] = set()
        for invoice_id in invoice_ids:
            stripped = invoice_id.strip()
            if not stripped:
                raise ValueError("Invoice IDs must not be empty.")
            if stripped not in seen:
                normalized.append(stripped)
                seen.add(stripped)

        if not normalized:
            raise ValueError("At least one invoice ID is required.")
        if len(normalized) > MAX_BATCH_ASSURANCE_INVOICES:
            raise ValueError(
                f"Batch assurance accepts at most {MAX_BATCH_ASSURANCE_INVOICES} invoices."
            )
        return normalized


BatchAssuranceOutcome = Literal["accepted", "reused", "not_found", "start_failed"]


class BatchAssuranceItemResult(BaseModel):
    invoice_id: str
    invoice_number: str | None = None
    outcome: BatchAssuranceOutcome
    run_id: str | None = None
    run_status: str | None = None
    foundry_response_id: str | None = None


class BatchAssuranceTriggerResult(BaseModel):
    items: list[BatchAssuranceItemResult]
    total: int
    accepted: int
    reused: int
    not_found: int
    start_failed: int
