"""Pydantic schemas for the Waypoint Contracts API.

Contracts artifacts are deliberately independent of the invoice-assurance schema: an artifact is a
durable record of a document that arrived through an intake channel (email, Teams upload, API),
with append-only extraction, evidence, and report records hanging off it.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, HttpUrl, field_validator

from ..records.schemas import JsonObject

ArtifactType = Literal["contract", "invoice"]
ArtifactSource = Literal["email", "teams_upload", "api"]
ExtractionStatus = Literal["pending", "succeeded", "partial", "failed"]
ProcessingStatus = Literal["received", "processing", "processed", "failed"]
Extractor = Literal["content_understanding", "manual", "other"]
EvidenceSourceType = Literal["foundryiq", "webiq", "workiq", "fabriciq", "waypoint", "user_file"]
ShareStatus = Literal["not_shared", "pending_approval", "shared", "failed"]


def normalize_identity(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip().lower()
    return value or None


class IntakeAttachment(BaseModel):
    """One attachment on an intake message. Identity is (attachment_id, sha256)."""

    attachment_id: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    file_name: str = ""
    content_type: str = ""
    size_bytes: int | None = Field(default=None, ge=0)
    original_file_uri: str = Field(
        min_length=1,
        description="Where the original file is stored (SharePoint/OneDrive/blob URI).",
    )
    artifact_type: ArtifactType = "contract"
    metadata: JsonObject = Field(default_factory=dict)

    @field_validator("sha256")
    @classmethod
    def _lower_sha(cls, value: str) -> str:
        return value.lower()


class IntakeMessageUpsert(BaseModel):
    """A mailbox message and its attachments, as seen by the intake poller."""

    mailbox_id: str = Field(min_length=1)
    message_id: str = Field(min_length=1)
    source: ArtifactSource = "email"
    received_at: datetime | None = None
    sender: str | None = None
    subject: str = ""
    owner_user_id: str | None = Field(
        default=None,
        description="Artifact owner. Defaults to the sender address.",
    )
    attachments: list[IntakeAttachment] = Field(min_length=1)
    metadata: JsonObject = Field(default_factory=dict)

    @field_validator("sender", "owner_user_id")
    @classmethod
    def _normalize(cls, value: str | None) -> str | None:
        return normalize_identity(value)


class Artifact(BaseModel):
    id: str
    type: ArtifactType
    owner_user_id: str | None = None
    source: ArtifactSource
    source_mailbox_id: str | None = None
    source_message_id: str | None = None
    source_attachment_id: str | None = None
    source_attachment_sha256: str | None = None
    intake_key: str | None = None
    file_name: str = ""
    content_type: str = ""
    size_bytes: int | None = None
    sender: str | None = None
    subject: str = ""
    original_file_uri: str
    extracted_json: JsonObject | None = None
    latest_extraction_id: str | None = None
    extraction_status: ExtractionStatus = "pending"
    processing_status: ProcessingStatus = "received"
    run_ids: list[str] = Field(default_factory=list)
    received_at: datetime
    created_by: str
    created_at: datetime
    updated_at: datetime
    metadata: JsonObject = Field(default_factory=dict)


class ArtifactUpdate(BaseModel):
    """Status/metadata update. Metadata keys are merged, not replaced."""

    processing_status: ProcessingStatus | None = None
    metadata: JsonObject | None = None


class IntakeMessageCheckpoint(BaseModel):
    id: str
    mailbox_id: str
    message_id: str
    attachment_id: str
    attachment_sha256: str
    artifact_id: str
    status: Literal["registered"] = "registered"
    processed_at: datetime


class IntakeAttachmentResult(BaseModel):
    attachment_id: str
    attachment_sha256: str
    created: bool
    artifact: Artifact


class IntakeMessageResult(BaseModel):
    mailbox_id: str
    message_id: str
    results: list[IntakeAttachmentResult]


class ArtifactExtractionCreate(BaseModel):
    extractor: Extractor = "content_understanding"
    schema_version: str = "1"
    status: ExtractionStatus = "succeeded"
    values: JsonObject = Field(default_factory=dict)
    confidence: JsonObject = Field(default_factory=dict)
    source_spans: JsonObject = Field(default_factory=dict)
    error: str | None = None
    metadata: JsonObject = Field(default_factory=dict)


class ArtifactExtraction(ArtifactExtractionCreate):
    id: str
    artifact_id: str
    created_by: str
    created_at: datetime


class ArtifactEvidenceCreate(BaseModel):
    source_type: EvidenceSourceType
    claim: str = Field(min_length=1)
    citation: str = Field(min_length=1)
    confidence: float | None = Field(default=None, ge=0, le=1)
    metadata: JsonObject = Field(default_factory=dict)


class ArtifactEvidence(ArtifactEvidenceCreate):
    id: str
    artifact_id: str
    created_by: str
    created_at: datetime


class ArtifactRunCreate(BaseModel):
    status: str = "running"
    summary: str = ""
    foundry_agent_name: str | None = None
    foundry_conversation_id: str | None = None
    app_insights_operation_id: str | None = None
    idempotency_key: str | None = None
    metadata: JsonObject = Field(default_factory=dict)


class ShareEvent(BaseModel):
    share_status: ShareStatus
    shared_with: list[str] = Field(default_factory=list)
    share_url: str | None = None
    approved_by: str | None = None
    recorded_by: str
    recorded_at: datetime
    note: str = ""


class ArtifactReportCreate(BaseModel):
    """Metadata for a report that already exists at ``file_url``.

    ``file_url`` is required so the agent cannot record a report without a concrete file.
    """

    report_type: str = Field(min_length=1)
    file_url: HttpUrl
    title: str = ""
    share_status: ShareStatus = "not_shared"
    shared_with: list[str] = Field(default_factory=list)
    metadata: JsonObject = Field(default_factory=dict)


class ArtifactReportShareUpdate(BaseModel):
    """Record the outcome of sharing a report (for example after user approval)."""

    share_status: ShareStatus
    shared_with: list[str] = Field(default_factory=list)
    share_url: HttpUrl | None = None
    approved_by: str | None = None
    note: str = ""


class ArtifactReport(BaseModel):
    id: str
    artifact_id: str
    report_type: str
    file_url: str
    title: str = ""
    share_status: ShareStatus = "not_shared"
    shared_with: list[str] = Field(default_factory=list)
    share_events: list[ShareEvent] = Field(default_factory=list)
    created_by: str
    created_at: datetime
    updated_at: datetime
    metadata: JsonObject = Field(default_factory=dict)


class ArtifactDetail(BaseModel):
    artifact: Artifact
    extractions: list[ArtifactExtraction] = Field(default_factory=list)
    evidence: list[ArtifactEvidence] = Field(default_factory=list)
    reports: list[ArtifactReport] = Field(default_factory=list)
