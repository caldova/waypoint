"""Pydantic schemas for Waypoint invoice assurance data."""

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field

JsonObject = dict[str, Any]
Classification = Literal["standard", "confidential", "ip_sensitive", "restricted"]
FindingValidationOutcome = Literal[
    "validated_existing_finding",
    "not_validated",
    "needs_review",
]


class Supplier(BaseModel):
    id: str
    name: str
    status: str = "active"
    category: str = "contract-manufacturer"
    metadata: JsonObject = Field(default_factory=dict)


class ContractDocument(BaseModel):
    id: str
    supplier_id: str
    title: str
    document_type: str = "contract"
    effective_date: date | None = None
    uri: str | None = None
    metadata: JsonObject = Field(default_factory=dict)


class Policy(BaseModel):
    id: str
    name: str
    description: str = ""
    severity: str = "medium"
    metadata: JsonObject = Field(default_factory=dict)


class Scenario(BaseModel):
    id: str
    name: str
    description: str = ""
    generated_at: datetime | None = None
    source_uri: str | None = None
    metadata: JsonObject = Field(default_factory=dict)


class InvoiceLine(BaseModel):
    id: str
    invoice_id: str
    description: str
    quantity: Decimal = Decimal("1")
    unit_price: Decimal = Decimal("0")
    amount: Decimal = Decimal("0")
    sku: str | None = None
    purchase_order: str | None = None
    metadata: JsonObject = Field(default_factory=dict)


class EvidenceReference(BaseModel):
    id: str
    title: str
    evidence_type: str = "document"
    invoice_id: str | None = None
    finding_id: str | None = None
    uri: str | None = None
    excerpt: str | None = None
    metadata: JsonObject = Field(default_factory=dict)


class ReconciliationFinding(BaseModel):
    id: str
    invoice_id: str
    scenario_id: str | None = None
    category: str
    severity: str = "medium"
    status: Literal["open", "review", "approved", "recover", "escalate", "closed"] = "open"
    summary: str
    overpayment_amount: Decimal = Decimal("0")
    contract_document_ids: list[str] = Field(default_factory=list)
    policy_ids: list[str] = Field(default_factory=list)
    basis_summary: str | None = None
    evidence_ids: list[str] = Field(default_factory=list)
    metadata: JsonObject = Field(default_factory=dict)


class FindingValidationCreate(BaseModel):
    run_id: str
    case_id: str | None = None
    validator: str | None = None
    source: str = "pacioli"
    outcome: FindingValidationOutcome = "validated_existing_finding"
    confidence: Decimal | None = Field(default=None, ge=0, le=1)
    evidence_ids: list[str] = Field(default_factory=list)
    basis_summary: str | None = None
    evidence_snapshot: JsonObject = Field(default_factory=dict)
    evidence_hash: str | None = None
    metadata: JsonObject = Field(default_factory=dict)


class FindingValidation(BaseModel):
    id: str
    finding_id: str
    invoice_id: str
    run_id: str
    case_id: str | None = None
    validator: str
    source: str = "pacioli"
    outcome: FindingValidationOutcome = "validated_existing_finding"
    confidence: Decimal | None = None
    evidence_ids: list[str] = Field(default_factory=list)
    basis_summary: str | None = None
    evidence_snapshot: JsonObject = Field(default_factory=dict)
    evidence_hash: str
    created_by: str
    auth_source: str
    created_at: datetime
    metadata: JsonObject = Field(default_factory=dict)


class Invoice(BaseModel):
    id: str
    supplier_id: str
    scenario_id: str | None = None
    invoice_number: str
    invoice_date: date | None = None
    due_date: date | None = None
    status: str = "review"
    currency: str = "USD"
    total_amount: Decimal = Decimal("0")
    html_uri: str | None = None
    pdf_uri: str | None = None
    metadata: JsonObject = Field(default_factory=dict)


class InvoiceDetail(Invoice):
    supplier: Supplier | None = None
    scenario: Scenario | None = None
    lines: list[InvoiceLine] = Field(default_factory=list)
    findings: list[ReconciliationFinding] = Field(default_factory=list)
    evidence: list[EvidenceReference] = Field(default_factory=list)


class ContractDocumentDetail(ContractDocument):
    """Contract document metadata plus resolved document text from the corpus lake."""

    text: str | None = None
    content_source: Literal["onelake", "uri-only"] = "uri-only"


class PolicyDetail(Policy):
    """Policy metadata plus resolved document text from the corpus lake."""

    text: str | None = None
    content_source: Literal["onelake", "uri-only"] = "uri-only"


class InvoiceDecision(BaseModel):
    invoice_id: str
    invoice_number: str
    supplier_id: str
    supplier_name: str
    scenario_id: str | None = None
    scenario_name: str | None = None
    decision: str
    category: str
    reasoning: str
    severity: str
    status: str
    currency: str = "USD"
    overpayment_amount: Decimal = Decimal("0")
    overpayment_display: str
    source: str
    evidence_count: int = 0
    contract_document_ids: list[str] = Field(default_factory=list)
    policy_ids: list[str] = Field(default_factory=list)
    basis_summary: str | None = None
    basis_types: list[Literal["contract", "policy"]] = Field(default_factory=list)
    html_uri: str | None = None
    pdf_uri: str | None = None
    has_agent_decision: bool = False
    has_active_run: bool = False
    agent_decision: str | None = None
    agent_run_count: int = 0
    agent_run_index: int | None = None
    agent_run_at: datetime | None = None
    agent_case_id: str | None = None
    confidence: Decimal | None = None
    confidence_calibrated: bool = False
    agent_title: str | None = None
    agent_source_count: int = 0
    agent_plane_count: int = 0
    metadata: JsonObject = Field(default_factory=dict)


class AuditEvent(BaseModel):
    id: str
    created_at: datetime
    caller: str
    auth_source: str
    key_label: str | None = None
    method: str
    route: str
    status: int
    resource_ids: JsonObject = Field(default_factory=dict)
    metadata: JsonObject = Field(default_factory=dict)


class LedgerfieldSeedImport(BaseModel):
    schema_version: str = Field(
        default="1.0",
        description="Ledgerfield Waypoint seed schema version.",
    )
    source: str = Field(
        default="ledgerfield",
        description="Seed source label or Ledgerfield output URI",
    )
    suppliers: list[Supplier] = Field(default_factory=list)
    contract_documents: list[ContractDocument] = Field(default_factory=list)
    policies: list[Policy] = Field(default_factory=list)
    scenarios: list[Scenario] = Field(default_factory=list)
    invoices: list[InvoiceDetail] = Field(default_factory=list)
    findings: list[ReconciliationFinding] = Field(default_factory=list)
    evidence: list[EvidenceReference] = Field(default_factory=list)


class SeedImportResult(BaseModel):
    source: str
    suppliers: int
    contract_documents: int
    policies: int
    scenarios: int
    invoices: int
    invoice_lines: int
    findings: int
    evidence: int
