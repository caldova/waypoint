"""Schemas for user-triggered invoice assurance."""

from pydantic import BaseModel

from ..runs.schemas import AgentRun


class AssuranceRunTriggerResult(BaseModel):
    run: AgentRun
    reused: bool
    foundry_response_id: str | None = None
