"""Pydantic schemas for agent run anchors and telemetry references."""

from datetime import datetime

from pydantic import BaseModel, Field

from ..records.schemas import JsonObject


class AgentRunCreate(BaseModel):
    case_id: str | None = None
    name: str
    status: str = "running"
    summary: str = ""
    foundry_agent_name: str | None = None
    foundry_conversation_id: str | None = None
    app_insights_operation_id: str | None = None
    metadata: JsonObject = Field(default_factory=dict)
    idempotency_key: str | None = None


class AgentRunUpdate(BaseModel):
    """Partial lifecycle update for an existing run."""

    status: str | None = None
    summary: str | None = None
    foundry_agent_name: str | None = None
    foundry_conversation_id: str | None = None
    foundry_response_id: str | None = None
    app_insights_operation_id: str | None = None
    metadata: JsonObject | None = None


class AgentRun(BaseModel):
    id: str
    case_id: str | None = None
    name: str
    status: str = "running"
    foundry_agent_name: str | None = None
    foundry_conversation_id: str | None = None
    foundry_response_id: str | None = None
    app_insights_operation_id: str | None = None
    summary: str = ""
    created_by: str
    created_at: datetime
    updated_at: datetime
    metadata: JsonObject = Field(default_factory=dict)
    idempotency_key: str | None = None
