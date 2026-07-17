"""Waypoint persistence implementations."""

import asyncio
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, Protocol, cast
from uuid import uuid4

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool

from ..modules.cases.schemas import (
    ActionType,
    AssuranceCase,
    AuthorizedIntent,
    CaseApproval,
    CaseDraft,
    CaseRecommendation,
    DecisionAuditEvent,
    ProposedAction,
)
from ..modules.records.schemas import (
    AuditEvent,
    ContractDocument,
    EvidenceReference,
    FindingValidation,
    Invoice,
    InvoiceDetail,
    InvoiceLine,
    LedgerfieldSeedImport,
    Policy,
    ReconciliationFinding,
    Scenario,
    SeedImportResult,
    Supplier,
)
from ..modules.runs.schemas import AgentRun

# FabricIQ typed analytics projection.
#
# Fabric Mirroring for Azure Database for PostgreSQL cannot replicate `jsonb` columns and
# does not guarantee replication of generated columns, so the financial/transactional core
# is projected onto PLAIN physical columns (declared in _SCHEMA_SQL) that the application
# populates on every write. Each entry maps a table to the (column, kind) pairs pulled out
# of its JSON payload; `kind` drives the Python-side type coercion so psycopg binds real
# numeric/date/text values (not JSON text) into the typed columns.
_PROJECTED_COLUMNS: dict[str, tuple[tuple[str, str], ...]] = {
    "suppliers": (
        ("name", "text"),
        ("status", "text"),
        ("category", "text"),
    ),
    "invoices": (
        ("supplier_id", "text"),
        ("scenario_id", "text"),
        ("invoice_number", "text"),
        ("invoice_date", "date"),
        ("due_date", "date"),
        ("status", "text"),
        ("currency", "text"),
        ("total_amount", "numeric"),
    ),
    "invoice_lines": (
        ("invoice_id", "text"),
        ("quantity", "numeric"),
        ("unit_price", "numeric"),
        ("amount", "numeric"),
        ("sku", "text"),
        ("purchase_order", "text"),
    ),
    "reconciliation_findings": (
        ("invoice_id", "text"),
        ("scenario_id", "text"),
        ("category", "text"),
        ("severity", "text"),
        ("status", "text"),
        ("overpayment_amount", "numeric"),
    ),
}


def _coerce_projected_value(raw: Any, kind: str) -> Any:
    """Coerce a JSON payload value into the type of its projected column so psycopg binds
    a real numeric/date/text (mirrors cleanly to Fabric). Missing/empty -> NULL."""
    if raw is None or raw == "":
        return None
    if kind == "numeric":
        return Decimal(str(raw))
    if kind == "date":
        return date.fromisoformat(str(raw)[:10])
    return str(raw)


DEFAULT_LEDGERFIELD_SEED = LedgerfieldSeedImport(
    suppliers=[
        Supplier(id="sup-009", name="BluePeak Biologics"),
        Supplier(id="sup-nova-pack", name="NovaPack Sterile Fill"),
    ],
    contract_documents=[
        ContractDocument(
            id="doc-cap-bluepeak-2026",
            supplier_id="sup-009",
            title="BluePeak Biologics Capacity Agreement",
            uri="https://github.com/caldova/waypoint",
        ),
    ],
    policies=[
        Policy(
            id="policy-supplier-caused-cost",
            name="Supplier-caused deviation cost recovery",
            description=(
                "Investigation and deviation costs attributable to supplier-caused "
                "contamination are non-billable and are disputed and escalated for quality review."
            ),
            severity="high",
        ),
    ],
    scenarios=[
        Scenario(
            id="scn-sup-009-supplier-caused-investigation",
            name="Supplier-caused contamination investigation assurance",
            description="Ledgerfield-generated contract manufacturing invoice scenario.",
            source_uri="https://github.com/caldova/waypoint",
        )
    ],
    invoices=[
        InvoiceDetail(
            id="inv-2026-08034",
            supplier_id="sup-009",
            scenario_id="scn-sup-009-supplier-caused-investigation",
            invoice_number="INV-2026-08034",
            status="escalate",
            total_amount=Decimal("250250"),
            html_uri="ledgerfield://generated/invoices/INV-2026-08034.html",
            pdf_uri="ledgerfield://generated/invoices/INV-2026-08034.pdf",
            lines=[
                InvoiceLine(
                    id="line-08034-1",
                    invoice_id="inv-2026-08034",
                    description="Cell culture run logs for sponsor-accepted campaign BP-1026",
                    quantity=Decimal("1"),
                    unit_price=Decimal("139250"),
                    amount=Decimal("139250"),
                    sku="BATCH-BP-1026",
                    purchase_order="PO-CMO-009-2026-Q4",
                ),
                InvoiceLine(
                    id="line-08034-2",
                    invoice_id="inv-2026-08034",
                    description=(
                        "Contamination investigation billed where deviation record "
                        "indicates supplier-caused contamination"
                    ),
                    quantity=Decimal("1"),
                    unit_price=Decimal("111000"),
                    amount=Decimal("111000"),
                    sku="DEV-BP-1026",
                    purchase_order="PO-CMO-009-2026-Q4",
                ),
            ],
            findings=[
                ReconciliationFinding(
                    id="finding-08034-investigation",
                    invoice_id="inv-2026-08034",
                    scenario_id="scn-sup-009-supplier-caused-investigation",
                    category="Quality deviation",
                    severity="high",
                    status="escalate",
                    summary=(
                        "Contamination investigation charge is billed although the deviation "
                        "record indicates supplier-caused contamination."
                    ),
                    overpayment_amount=Decimal("111000"),
                    contract_document_ids=["doc-cap-bluepeak-2026"],
                    policy_ids=["policy-supplier-caused-cost"],
                    basis_summary=(
                        "BluePeak capacity agreement contamination and deviation cost terms "
                        "plus supplier-caused deviation cost recovery policy"
                    ),
                    evidence_ids=["evidence-08034-deviation", "evidence-08034-contract"],
                )
            ],
            evidence=[
                EvidenceReference(
                    id="evidence-08034-deviation",
                    invoice_id="inv-2026-08034",
                    finding_id="finding-08034-investigation",
                    title="Deviation record",
                    evidence_type="deviation-record",
                    uri="ledgerfield://evidence/dev-bp-1026-supplier",
                ),
                EvidenceReference(
                    id="evidence-08034-contract",
                    invoice_id="inv-2026-08034",
                    finding_id="finding-08034-investigation",
                    title="Contamination and deviation costs clause",
                    evidence_type="contract-clause",
                    uri="ledgerfield://evidence/bluepeak-capacity-agreement-section-4",
                ),
            ],
        )
    ],
)

DEFAULT_ACTION_TYPES = [
    ActionType(
        id="recommend_recover",
        name="Recommend recovery",
        description="Stage a recovery recommendation for finance review.",
        approval_gate="finance",
    ),
    ActionType(
        id="draft_supplier_dispute",
        name="Draft supplier dispute",
        description="Prepare a supplier dispute note without sending it.",
        approval_gate="procurement",
    ),
    ActionType(
        id="request_legal_escalation",
        name="Request legal escalation",
        description="Stage legal review for IP-sensitive or contractual risk.",
        approval_gate="legal",
        external_side_effect=True,
    ),
    ActionType(
        id="request_quality_review",
        name="Request quality review",
        description="Stage a quality review for batch, QA release, or GMP-sensitive issues.",
        approval_gate="quality",
        external_side_effect=True,
    ),
]


class WaypointRepository(Protocol):
    """Persistence boundary shared by in-memory and PostgreSQL implementations."""

    async def initialize(self, load_default_seed: bool = True) -> None: ...

    async def close(self) -> None: ...

    async def remove_default_seed(self) -> None: ...

    async def list_suppliers(self) -> list[Supplier]: ...

    async def list_scenarios(self) -> list[Scenario]: ...

    async def list_contract_documents(self) -> list[ContractDocument]: ...

    async def get_contract_document(self, document_id: str) -> ContractDocument | None: ...

    async def list_policies(self) -> list[Policy]: ...

    async def get_policy(self, policy_id: str) -> Policy | None: ...

    async def list_invoices(
        self,
        supplier_id: str | None = None,
        invoice_number: str | None = None,
    ) -> list[Invoice]: ...

    async def get_invoice_detail(self, invoice_id: str) -> InvoiceDetail | None: ...

    async def list_findings(self, invoice_id: str | None = None) -> list[ReconciliationFinding]: ...

    async def create_finding_validation(self, validation: FindingValidation) -> None: ...

    async def list_finding_validations(self, finding_id: str) -> list[FindingValidation]: ...

    async def list_evidence(
        self,
        invoice_id: str | None = None,
        finding_id: str | None = None,
    ) -> list[EvidenceReference]: ...

    async def list_audit_events(self) -> list[AuditEvent]: ...

    async def list_action_types(self) -> list[ActionType]: ...

    async def get_action_type(self, action_type_id: str) -> ActionType | None: ...

    async def list_cases(
        self,
        invoice_id: str | None = None,
        finding_id: str | None = None,
    ) -> list[AssuranceCase]: ...

    async def get_case(self, case_id: str) -> AssuranceCase | None: ...

    async def get_case_by_idempotency_key(self, idempotency_key: str) -> AssuranceCase | None: ...

    async def save_case(self, assurance_case: AssuranceCase) -> None: ...

    async def list_case_recommendations(self, case_id: str) -> list[CaseRecommendation]: ...

    async def save_case_recommendation(self, recommendation: CaseRecommendation) -> None: ...

    async def get_case_draft(self, draft_id: str) -> CaseDraft | None: ...

    async def list_case_drafts(self, case_id: str) -> list[CaseDraft]: ...

    async def save_case_draft(self, draft: CaseDraft) -> None: ...

    async def get_proposed_action(self, action_id: str) -> ProposedAction | None: ...

    async def list_case_proposed_actions(self, case_id: str) -> list[ProposedAction]: ...

    async def save_proposed_action(self, action: ProposedAction) -> None: ...

    async def get_case_approval_by_idempotency_key(
        self, case_id: str, idempotency_key: str
    ) -> CaseApproval | None: ...

    async def get_case_approval(self, approval_id: str) -> CaseApproval | None: ...

    async def list_case_approvals(self, case_id: str) -> list[CaseApproval]: ...

    async def save_case_approval(self, approval: CaseApproval) -> None: ...

    async def get_authorized_intent_by_idempotency_key(
        self, proposed_action_id: str, idempotency_key: str
    ) -> AuthorizedIntent | None: ...

    async def save_authorized_intent(self, intent: AuthorizedIntent) -> None: ...

    async def list_decision_audit_events(self) -> list[DecisionAuditEvent]: ...

    async def save_decision_audit_event(self, event: DecisionAuditEvent) -> None: ...

    async def create_agent_run(self, run: AgentRun) -> None: ...

    async def create_or_reuse_agent_run(
        self, run: AgentRun, active_statuses: tuple[str, ...]
    ) -> tuple[AgentRun, bool]: ...

    async def update_agent_run(self, run: AgentRun) -> None: ...

    async def compare_and_swap_agent_run(self, run: AgentRun, expected: AgentRun) -> bool: ...

    async def reap_agent_run(
        self, run: AgentRun, cutoff: datetime, reapable_statuses: tuple[str, ...]
    ) -> bool: ...

    async def get_agent_run(self, run_id: str) -> AgentRun | None: ...

    async def get_agent_run_by_idempotency_key(self, idempotency_key: str) -> AgentRun | None: ...

    async def get_active_run_by_name(
        self, name: str, active_statuses: tuple[str, ...]
    ) -> AgentRun | None: ...

    async def list_stale_active_runs(
        self, cutoff: datetime, active_statuses: tuple[str, ...]
    ) -> list[AgentRun]: ...

    async def list_agent_runs(self, case_id: str | None = None) -> list[AgentRun]: ...

    async def save_audit_event(self, payload: dict[str, Any]) -> None: ...

    async def import_seed(self, seed: LedgerfieldSeedImport) -> SeedImportResult: ...


class InMemoryWaypointRepository:
    """In-memory repository used when no PostgreSQL connection is configured."""

    def __init__(self) -> None:
        self.suppliers: dict[str, Supplier] = {}
        self.contract_documents: dict[str, ContractDocument] = {}
        self.policies: dict[str, Policy] = {}
        self.scenarios: dict[str, Scenario] = {}
        self.invoices: dict[str, Invoice] = {}
        self.invoice_lines: dict[str, InvoiceLine] = {}
        self.findings: dict[str, ReconciliationFinding] = {}
        self.finding_validations: dict[str, FindingValidation] = {}
        self.evidence: dict[str, EvidenceReference] = {}
        self.audit_events: dict[str, AuditEvent] = {}
        self.action_types: dict[str, ActionType] = {
            action_type.id: action_type for action_type in DEFAULT_ACTION_TYPES
        }
        self.assurance_cases: dict[str, AssuranceCase] = {}
        self.case_recommendations: dict[str, CaseRecommendation] = {}
        self.case_drafts: dict[str, CaseDraft] = {}
        self.proposed_actions: dict[str, ProposedAction] = {}
        self.case_approvals: dict[str, CaseApproval] = {}
        self.authorized_intents: dict[str, AuthorizedIntent] = {}
        self.decision_audit_events: dict[str, DecisionAuditEvent] = {}
        self.agent_runs: dict[str, AgentRun] = {}
        self._agent_run_create_lock = asyncio.Lock()

    async def initialize(self, load_default_seed: bool = True) -> None:
        if load_default_seed and not self.suppliers and not self.invoices:
            await self.import_seed(DEFAULT_LEDGERFIELD_SEED)

    async def close(self) -> None:
        return None

    async def remove_default_seed(self) -> None:
        """Remove built-in fallback records before loading a richer external seed."""

        for invoice in DEFAULT_LEDGERFIELD_SEED.invoices:
            self.invoices.pop(invoice.id, None)
            for line in invoice.lines:
                self.invoice_lines.pop(line.id, None)
            for finding in invoice.findings:
                self.findings.pop(finding.id, None)
            for evidence in invoice.evidence:
                self.evidence.pop(evidence.id, None)
        for finding in DEFAULT_LEDGERFIELD_SEED.findings:
            self.findings.pop(finding.id, None)
        for evidence in DEFAULT_LEDGERFIELD_SEED.evidence:
            self.evidence.pop(evidence.id, None)
        for scenario in DEFAULT_LEDGERFIELD_SEED.scenarios:
            self.scenarios.pop(scenario.id, None)
        for policy in DEFAULT_LEDGERFIELD_SEED.policies:
            self.policies.pop(policy.id, None)
        for document in DEFAULT_LEDGERFIELD_SEED.contract_documents:
            self.contract_documents.pop(document.id, None)
        for supplier in DEFAULT_LEDGERFIELD_SEED.suppliers:
            self.suppliers.pop(supplier.id, None)

    async def list_suppliers(self) -> list[Supplier]:
        return sorted(self.suppliers.values(), key=lambda supplier: supplier.name)

    async def list_scenarios(self) -> list[Scenario]:
        return sorted(self.scenarios.values(), key=lambda scenario: scenario.name)

    async def list_contract_documents(self) -> list[ContractDocument]:
        return sorted(self.contract_documents.values(), key=lambda document: document.title)

    async def get_contract_document(self, document_id: str) -> ContractDocument | None:
        return self.contract_documents.get(document_id)

    async def list_policies(self) -> list[Policy]:
        return sorted(self.policies.values(), key=lambda policy: policy.name)

    async def get_policy(self, policy_id: str) -> Policy | None:
        return self.policies.get(policy_id)

    async def list_invoices(
        self,
        supplier_id: str | None = None,
        invoice_number: str | None = None,
    ) -> list[Invoice]:
        invoices = list(self.invoices.values())
        if supplier_id:
            invoices = [invoice for invoice in invoices if invoice.supplier_id == supplier_id]
        if invoice_number:
            invoices = [invoice for invoice in invoices if invoice.invoice_number == invoice_number]
        return sorted(invoices, key=lambda invoice: invoice.invoice_number)

    async def get_invoice_detail(self, invoice_id: str) -> InvoiceDetail | None:
        invoice = self.invoices.get(invoice_id)
        if not invoice:
            return None
        lines = [line for line in self.invoice_lines.values() if line.invoice_id == invoice_id]
        findings = [
            finding for finding in self.findings.values() if finding.invoice_id == invoice_id
        ]
        evidence = [item for item in self.evidence.values() if item.invoice_id == invoice_id]
        return InvoiceDetail(
            **invoice.model_dump(),
            supplier=self.suppliers.get(invoice.supplier_id),
            scenario=self.scenarios.get(invoice.scenario_id or ""),
            lines=sorted(lines, key=lambda line: line.id),
            findings=sorted(findings, key=lambda finding: finding.id),
            evidence=sorted(evidence, key=lambda item: item.id),
        )

    async def list_findings(self, invoice_id: str | None = None) -> list[ReconciliationFinding]:
        findings = list(self.findings.values())
        if invoice_id:
            findings = [finding for finding in findings if finding.invoice_id == invoice_id]
        return sorted(findings, key=lambda finding: finding.id)

    async def create_finding_validation(self, validation: FindingValidation) -> None:
        self.finding_validations[validation.id] = validation

    async def list_finding_validations(self, finding_id: str) -> list[FindingValidation]:
        validations = [
            validation
            for validation in self.finding_validations.values()
            if validation.finding_id == finding_id
        ]
        return sorted(validations, key=lambda item: (item.created_at, item.id))

    async def list_evidence(
        self,
        invoice_id: str | None = None,
        finding_id: str | None = None,
    ) -> list[EvidenceReference]:
        evidence = list(self.evidence.values())
        if invoice_id:
            evidence = [item for item in evidence if item.invoice_id == invoice_id]
        if finding_id:
            evidence = [item for item in evidence if item.finding_id == finding_id]
        return sorted(evidence, key=lambda item: item.id)

    async def list_audit_events(self) -> list[AuditEvent]:
        return sorted(self.audit_events.values(), key=lambda event: event.created_at, reverse=True)

    async def list_action_types(self) -> list[ActionType]:
        return sorted(self.action_types.values(), key=lambda action_type: action_type.id)

    async def get_action_type(self, action_type_id: str) -> ActionType | None:
        return self.action_types.get(action_type_id)

    async def list_cases(
        self,
        invoice_id: str | None = None,
        finding_id: str | None = None,
    ) -> list[AssuranceCase]:
        cases = list(self.assurance_cases.values())
        if invoice_id:
            cases = [case for case in cases if case.invoice_id == invoice_id]
        if finding_id:
            cases = [case for case in cases if case.finding_id == finding_id]
        return sorted(cases, key=lambda case: case.updated_at, reverse=True)

    async def get_case(self, case_id: str) -> AssuranceCase | None:
        return self.assurance_cases.get(case_id)

    async def get_case_by_idempotency_key(self, idempotency_key: str) -> AssuranceCase | None:
        matches = [
            case
            for case in self.assurance_cases.values()
            if case.idempotency_key == idempotency_key
        ]
        if not matches:
            return None
        return max(matches, key=lambda case: case.created_at)

    async def save_case(self, assurance_case: AssuranceCase) -> None:
        self.assurance_cases[assurance_case.id] = assurance_case

    async def list_case_recommendations(self, case_id: str) -> list[CaseRecommendation]:
        recommendations = [
            recommendation
            for recommendation in self.case_recommendations.values()
            if recommendation.case_id == case_id
        ]
        return sorted(recommendations, key=lambda item: (item.created_at, item.id))

    async def save_case_recommendation(self, recommendation: CaseRecommendation) -> None:
        self.case_recommendations[recommendation.id] = recommendation

    async def get_case_draft(self, draft_id: str) -> CaseDraft | None:
        return self.case_drafts.get(draft_id)

    async def list_case_drafts(self, case_id: str) -> list[CaseDraft]:
        drafts = [draft for draft in self.case_drafts.values() if draft.case_id == case_id]
        return sorted(drafts, key=lambda item: (item.created_at, item.id))

    async def save_case_draft(self, draft: CaseDraft) -> None:
        self.case_drafts[draft.id] = draft

    async def get_proposed_action(self, action_id: str) -> ProposedAction | None:
        return self.proposed_actions.get(action_id)

    async def list_case_proposed_actions(self, case_id: str) -> list[ProposedAction]:
        actions = [action for action in self.proposed_actions.values() if action.case_id == case_id]
        return sorted(actions, key=lambda item: (item.created_at, item.id))

    async def save_proposed_action(self, action: ProposedAction) -> None:
        self.proposed_actions[action.id] = action

    async def get_case_approval_by_idempotency_key(
        self, case_id: str, idempotency_key: str
    ) -> CaseApproval | None:
        return next(
            (
                approval
                for approval in self.case_approvals.values()
                if approval.case_id == case_id and approval.idempotency_key == idempotency_key
            ),
            None,
        )

    async def get_case_approval(self, approval_id: str) -> CaseApproval | None:
        return self.case_approvals.get(approval_id)

    async def list_case_approvals(self, case_id: str) -> list[CaseApproval]:
        approvals = [
            approval for approval in self.case_approvals.values() if approval.case_id == case_id
        ]
        return sorted(approvals, key=lambda item: (item.approved_at, item.id))

    async def save_case_approval(self, approval: CaseApproval) -> None:
        self.case_approvals[approval.id] = approval

    async def get_authorized_intent_by_idempotency_key(
        self, proposed_action_id: str, idempotency_key: str
    ) -> AuthorizedIntent | None:
        return next(
            (
                intent
                for intent in self.authorized_intents.values()
                if intent.proposed_action_id == proposed_action_id
                and intent.idempotency_key == idempotency_key
            ),
            None,
        )

    async def save_authorized_intent(self, intent: AuthorizedIntent) -> None:
        self.authorized_intents[intent.id] = intent

    async def list_decision_audit_events(self) -> list[DecisionAuditEvent]:
        return sorted(
            self.decision_audit_events.values(),
            key=lambda event: event.created_at,
            reverse=True,
        )

    async def save_decision_audit_event(self, event: DecisionAuditEvent) -> None:
        self.decision_audit_events[event.id] = event

    async def create_agent_run(self, run: AgentRun) -> None:
        self.agent_runs[run.id] = run

    async def create_or_reuse_agent_run(
        self, run: AgentRun, active_statuses: tuple[str, ...]
    ) -> tuple[AgentRun, bool]:
        async with self._agent_run_create_lock:
            if run.idempotency_key:
                existing = await self.get_agent_run_by_idempotency_key(run.idempotency_key)
                if existing is not None:
                    return existing, False
            active = await self.get_active_run_by_name(run.name, active_statuses)
            if active is not None:
                return active, False
            self.agent_runs[run.id] = run
            return run, True

    async def update_agent_run(self, run: AgentRun) -> None:
        self.agent_runs[run.id] = run

    async def compare_and_swap_agent_run(self, run: AgentRun, expected: AgentRun) -> bool:
        current = self.agent_runs.get(run.id)
        if current is None or current.updated_at != expected.updated_at:
            return False
        self.agent_runs[run.id] = run
        return True

    async def reap_agent_run(
        self, run: AgentRun, cutoff: datetime, reapable_statuses: tuple[str, ...]
    ) -> bool:
        # Compare-and-swap: re-check the CURRENT stored row right before writing, so a finalize
        # or heartbeat that landed after the stale-list read wins and this reap becomes a no-op.
        current = self.agent_runs.get(run.id)
        if (
            current is None
            or current.status not in reapable_statuses
            or current.updated_at >= cutoff
        ):
            return False
        self.agent_runs[run.id] = run
        return True

    async def get_agent_run(self, run_id: str) -> AgentRun | None:
        return self.agent_runs.get(run_id)

    async def get_agent_run_by_idempotency_key(self, idempotency_key: str) -> AgentRun | None:
        matches = [
            run for run in self.agent_runs.values() if run.idempotency_key == idempotency_key
        ]
        if not matches:
            return None
        return max(matches, key=lambda run: run.updated_at)

    async def get_active_run_by_name(
        self, name: str, active_statuses: tuple[str, ...]
    ) -> AgentRun | None:
        matches = [
            run
            for run in self.agent_runs.values()
            if run.name == name and run.status in active_statuses
        ]
        if not matches:
            return None
        return max(matches, key=lambda run: run.updated_at)

    async def list_stale_active_runs(
        self, cutoff: datetime, active_statuses: tuple[str, ...]
    ) -> list[AgentRun]:
        return [
            run
            for run in self.agent_runs.values()
            if run.status in active_statuses and run.updated_at < cutoff
        ]

    async def list_agent_runs(self, case_id: str | None = None) -> list[AgentRun]:
        runs = list(self.agent_runs.values())
        if case_id:
            runs = [run for run in runs if run.case_id == case_id]
        return sorted(runs, key=lambda run: run.updated_at, reverse=True)

    async def save_audit_event(self, payload: dict[str, Any]) -> None:
        audit_event = AuditEvent(
            id=f"audit-{uuid4().hex}",
            created_at=datetime.now(UTC),
            caller=str(payload["caller"]),
            auth_source=str(payload["auth_source"]),
            key_label=payload.get("key_label"),
            method=str(payload["method"]),
            route=str(payload["route"]),
            status=int(payload["status"]),
            resource_ids=dict(payload.get("resource_ids", {})),
            metadata={"duration_ms": payload.get("duration_ms")},
        )
        self.audit_events[audit_event.id] = audit_event

    async def import_seed(self, seed: LedgerfieldSeedImport) -> SeedImportResult:
        for supplier in seed.suppliers:
            self.suppliers[supplier.id] = supplier
        for document in seed.contract_documents:
            self.contract_documents[document.id] = document
        for policy in seed.policies:
            self.policies[policy.id] = policy
        for scenario in seed.scenarios:
            self.scenarios[scenario.id] = scenario
        for invoice_detail in seed.invoices:
            invoice = Invoice(
                **invoice_detail.model_dump(
                    exclude={"supplier", "scenario", "lines", "findings", "evidence"}
                )
            )
            self.invoices[invoice.id] = invoice
            for line in invoice_detail.lines:
                self.invoice_lines[line.id] = line
            for finding in invoice_detail.findings:
                self.findings[finding.id] = finding
            for evidence in invoice_detail.evidence:
                self.evidence[evidence.id] = evidence
        for finding in seed.findings:
            self.findings[finding.id] = finding
        for evidence in seed.evidence:
            self.evidence[evidence.id] = evidence
        return _seed_import_result(seed)


class PostgresWaypointRepository:
    """PostgreSQL-backed repository using HorizonDB-compatible SQL."""

    def __init__(
        self,
        connection_string: str,
        *,
        min_pool_size: int = 1,
        max_pool_size: int = 10,
    ) -> None:
        self.connection_string = _normalize_postgres_connection_string(connection_string)
        self._pool = AsyncConnectionPool(
            self.connection_string,
            min_size=min_pool_size,
            max_size=max_pool_size,
            kwargs={"autocommit": True, "row_factory": dict_row},
            open=False,
        )

    async def initialize(self, load_default_seed: bool = True) -> None:
        await self._pool.open(wait=True)
        async with self._pool.connection() as connection:
            await connection.execute(_SCHEMA_SQL)
        for action_type in DEFAULT_ACTION_TYPES:
            await self._upsert_payload(
                "action_types", action_type.id, action_type.model_dump(mode="json")
            )
        if load_default_seed and not await self.list_suppliers():
            await self.import_seed(DEFAULT_LEDGERFIELD_SEED)

    async def close(self) -> None:
        await self._pool.close()

    async def remove_default_seed(self) -> None:
        async with self._pool.connection() as connection:
            await connection.execute(
                "delete from evidence_references where id = any(%s)",
                (
                    [
                        evidence.id
                        for invoice in DEFAULT_LEDGERFIELD_SEED.invoices
                        for evidence in invoice.evidence
                    ],
                ),
            )
            await connection.execute(
                "delete from reconciliation_findings where id = any(%s)",
                (
                    [
                        finding.id
                        for invoice in DEFAULT_LEDGERFIELD_SEED.invoices
                        for finding in invoice.findings
                    ],
                ),
            )
            await connection.execute(
                "delete from invoice_lines where id = any(%s)",
                (
                    [
                        line.id
                        for invoice in DEFAULT_LEDGERFIELD_SEED.invoices
                        for line in invoice.lines
                    ],
                ),
            )
            await connection.execute(
                "delete from invoices where id = any(%s)",
                ([invoice.id for invoice in DEFAULT_LEDGERFIELD_SEED.invoices],),
            )
            await connection.execute(
                "delete from scenarios where id = any(%s)",
                ([scenario.id for scenario in DEFAULT_LEDGERFIELD_SEED.scenarios],),
            )
            await connection.execute(
                "delete from policies where id = any(%s)",
                ([policy.id for policy in DEFAULT_LEDGERFIELD_SEED.policies],),
            )
            await connection.execute(
                "delete from contract_documents where id = any(%s)",
                ([document.id for document in DEFAULT_LEDGERFIELD_SEED.contract_documents],),
            )
            await connection.execute(
                "delete from suppliers where id = any(%s)",
                ([supplier.id for supplier in DEFAULT_LEDGERFIELD_SEED.suppliers],),
            )

    async def _fetch_payloads(
        self, table: str, where: str = "", params: tuple[object, ...] = ()
    ) -> list[dict[str, Any]]:
        async with self._pool.connection() as connection:
            cursor = connection.cursor(row_factory=dict_row)
            await cursor.execute(f"select payload from {table} {where}", params)
            rows = await cursor.fetchall()
        return [dict(row["payload"]) for row in rows]

    async def _upsert_payload(self, table: str, item_id: str, payload: dict[str, Any]) -> None:
        projected = _PROJECTED_COLUMNS.get(table, ())
        columns = ["id", "payload"]
        values: list[Any] = [item_id, Jsonb(payload)]
        for name, kind in projected:
            columns.append(name)
            values.append(_coerce_projected_value(payload.get(name), kind))
        columns.append("updated_at")
        placeholders = ", ".join(["%s"] * len(values) + ["now()"])
        conflict_sets = ["payload = excluded.payload"]
        conflict_sets += [f"{name} = excluded.{name}" for name, _ in projected]
        conflict_sets.append("updated_at = now()")
        async with self._pool.connection() as connection:
            await connection.execute(
                f"""
                insert into {table} ({", ".join(columns)})
                values ({placeholders})
                on conflict (id) do update set {", ".join(conflict_sets)}
                """,
                tuple(values),
            )

    async def _get_payload(self, table: str, item_id: str) -> dict[str, Any] | None:
        payloads = await self._fetch_payloads(table, "where id = %s", (item_id,))
        return payloads[0] if payloads else None

    async def list_suppliers(self) -> list[Supplier]:
        return [
            Supplier(**payload)
            for payload in await self._fetch_payloads("suppliers", "order by payload->>'name'")
        ]

    async def list_scenarios(self) -> list[Scenario]:
        return [
            Scenario(**payload)
            for payload in await self._fetch_payloads("scenarios", "order by payload->>'name'")
        ]

    async def list_contract_documents(self) -> list[ContractDocument]:
        return [
            ContractDocument(**payload)
            for payload in await self._fetch_payloads(
                "contract_documents", "order by payload->>'title'"
            )
        ]

    async def get_contract_document(self, document_id: str) -> ContractDocument | None:
        payloads = await self._fetch_payloads("contract_documents", "where id = %s", (document_id,))
        return ContractDocument(**payloads[0]) if payloads else None

    async def list_policies(self) -> list[Policy]:
        return [
            Policy(**payload)
            for payload in await self._fetch_payloads("policies", "order by payload->>'name'")
        ]

    async def get_policy(self, policy_id: str) -> Policy | None:
        payloads = await self._fetch_payloads("policies", "where id = %s", (policy_id,))
        return Policy(**payloads[0]) if payloads else None

    async def list_invoices(
        self,
        supplier_id: str | None = None,
        invoice_number: str | None = None,
    ) -> list[Invoice]:
        where = "order by payload->>'invoice_number'"
        params: list[object] = []
        clauses: list[str] = []
        if supplier_id:
            clauses.append("supplier_id = %s")
            params.append(supplier_id)
        if invoice_number:
            clauses.append("invoice_number = %s")
            params.append(invoice_number)
        if clauses:
            where = f"where {' and '.join(clauses)} order by payload->>'invoice_number'"
        return [
            Invoice(**payload)
            for payload in await self._fetch_payloads("invoices", where, tuple(params))
        ]

    async def get_invoice_detail(self, invoice_id: str) -> InvoiceDetail | None:
        invoices = await self._fetch_payloads("invoices", "where id = %s", (invoice_id,))
        if not invoices:
            return None
        invoice = Invoice(**invoices[0])
        supplier_payloads = await self._fetch_payloads(
            "suppliers", "where id = %s", (invoice.supplier_id,)
        )
        scenario_payloads = await self._fetch_payloads(
            "scenarios", "where id = %s", (invoice.scenario_id or "",)
        )
        line_payloads = await self._fetch_payloads(
            "invoice_lines", "where invoice_id = %s order by id", (invoice_id,)
        )
        finding_payloads = await self._fetch_payloads(
            "reconciliation_findings", "where invoice_id = %s order by id", (invoice_id,)
        )
        evidence_payloads = await self._fetch_payloads(
            "evidence_references", "where invoice_id = %s order by id", (invoice_id,)
        )
        return InvoiceDetail(
            **invoice.model_dump(),
            supplier=Supplier(**supplier_payloads[0]) if supplier_payloads else None,
            scenario=Scenario(**scenario_payloads[0]) if scenario_payloads else None,
            lines=[InvoiceLine(**payload) for payload in line_payloads],
            findings=[ReconciliationFinding(**payload) for payload in finding_payloads],
            evidence=[EvidenceReference(**payload) for payload in evidence_payloads],
        )

    async def list_findings(self, invoice_id: str | None = None) -> list[ReconciliationFinding]:
        where = "order by id"
        params: tuple[object, ...] = ()
        if invoice_id:
            where = "where invoice_id = %s order by id"
            params = (invoice_id,)
        return [
            ReconciliationFinding(**payload)
            for payload in await self._fetch_payloads("reconciliation_findings", where, params)
        ]

    async def create_finding_validation(self, validation: FindingValidation) -> None:
        async with self._pool.connection() as connection:
            await connection.execute(
                """
                insert into finding_validations (id, payload, updated_at)
                values (%s, %s, now())
                """,
                (validation.id, Jsonb(validation.model_dump(mode="json"))),
            )

    async def list_finding_validations(self, finding_id: str) -> list[FindingValidation]:
        return [
            FindingValidation(**payload)
            for payload in await self._fetch_payloads(
                "finding_validations",
                "where finding_id = %s order by created_at, id",
                (finding_id,),
            )
        ]

    async def list_evidence(
        self,
        invoice_id: str | None = None,
        finding_id: str | None = None,
    ) -> list[EvidenceReference]:
        clauses: list[str] = []
        params: list[object] = []
        if invoice_id:
            clauses.append("invoice_id = %s")
            params.append(invoice_id)
        if finding_id:
            clauses.append("finding_id = %s")
            params.append(finding_id)
        where = f"where {' and '.join(clauses)} order by id" if clauses else "order by id"
        return [
            EvidenceReference(**payload)
            for payload in await self._fetch_payloads("evidence_references", where, tuple(params))
        ]

    async def list_audit_events(self) -> list[AuditEvent]:
        return [
            AuditEvent(**payload)
            for payload in await self._fetch_payloads(
                "audit_events", "order by created_at desc limit 250"
            )
        ]

    async def save_audit_event(self, payload: dict[str, Any]) -> None:
        audit_event = AuditEvent(
            id=f"audit-{uuid4().hex}",
            created_at=datetime.now(UTC),
            caller=str(payload["caller"]),
            auth_source=str(payload["auth_source"]),
            key_label=payload.get("key_label"),
            method=str(payload["method"]),
            route=str(payload["route"]),
            status=int(payload["status"]),
            resource_ids=dict(payload.get("resource_ids", {})),
            metadata={"duration_ms": payload.get("duration_ms")},
        )
        async with self._pool.connection() as connection:
            await connection.execute(
                """
                insert into audit_events
                    (
                        id, caller, auth_source, key_label, method, route,
                        status, resource_ids, payload
                    )
                values (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    audit_event.id,
                    audit_event.caller,
                    audit_event.auth_source,
                    audit_event.key_label,
                    audit_event.method,
                    audit_event.route,
                    audit_event.status,
                    Jsonb(audit_event.resource_ids),
                    Jsonb(audit_event.model_dump(mode="json")),
                ),
            )

    async def list_action_types(self) -> list[ActionType]:
        return [
            ActionType(**payload)
            for payload in await self._fetch_payloads("action_types", "order by id")
        ]

    async def get_action_type(self, action_type_id: str) -> ActionType | None:
        payload = await self._get_payload("action_types", action_type_id)
        return ActionType(**payload) if payload else None

    async def list_cases(
        self,
        invoice_id: str | None = None,
        finding_id: str | None = None,
    ) -> list[AssuranceCase]:
        clauses: list[str] = []
        params: list[object] = []
        if invoice_id:
            clauses.append("invoice_id = %s")
            params.append(invoice_id)
        if finding_id:
            clauses.append("finding_id = %s")
            params.append(finding_id)
        where = (
            f"where {' and '.join(clauses)} order by updated_at desc"
            if clauses
            else "order by updated_at desc"
        )
        return [
            AssuranceCase(**payload)
            for payload in await self._fetch_payloads("assurance_cases", where, tuple(params))
        ]

    async def get_case(self, case_id: str) -> AssuranceCase | None:
        payload = await self._get_payload("assurance_cases", case_id)
        return AssuranceCase(**payload) if payload else None

    async def get_case_by_idempotency_key(self, idempotency_key: str) -> AssuranceCase | None:
        payloads = await self._fetch_payloads(
            "assurance_cases",
            "where payload->>'idempotency_key' = %s order by updated_at desc limit 1",
            (idempotency_key,),
        )
        return AssuranceCase(**payloads[0]) if payloads else None

    async def save_case(self, assurance_case: AssuranceCase) -> None:
        await self._upsert_payload(
            "assurance_cases", assurance_case.id, assurance_case.model_dump(mode="json")
        )

    async def list_case_recommendations(self, case_id: str) -> list[CaseRecommendation]:
        return [
            CaseRecommendation(**payload)
            for payload in await self._fetch_payloads(
                "case_recommendations",
                "where case_id = %s order by created_at, id",
                (case_id,),
            )
        ]

    async def save_case_recommendation(self, recommendation: CaseRecommendation) -> None:
        await self._upsert_payload(
            "case_recommendations", recommendation.id, recommendation.model_dump(mode="json")
        )

    async def get_case_draft(self, draft_id: str) -> CaseDraft | None:
        payload = await self._get_payload("case_drafts", draft_id)
        return CaseDraft(**payload) if payload else None

    async def list_case_drafts(self, case_id: str) -> list[CaseDraft]:
        return [
            CaseDraft(**payload)
            for payload in await self._fetch_payloads(
                "case_drafts",
                "where case_id = %s order by created_at, id",
                (case_id,),
            )
        ]

    async def save_case_draft(self, draft: CaseDraft) -> None:
        await self._upsert_payload("case_drafts", draft.id, draft.model_dump(mode="json"))

    async def get_proposed_action(self, action_id: str) -> ProposedAction | None:
        payload = await self._get_payload("proposed_actions", action_id)
        return ProposedAction(**payload) if payload else None

    async def list_case_proposed_actions(self, case_id: str) -> list[ProposedAction]:
        return [
            ProposedAction(**payload)
            for payload in await self._fetch_payloads(
                "proposed_actions",
                "where case_id = %s order by created_at, id",
                (case_id,),
            )
        ]

    async def save_proposed_action(self, action: ProposedAction) -> None:
        await self._upsert_payload("proposed_actions", action.id, action.model_dump(mode="json"))

    async def get_case_approval_by_idempotency_key(
        self, case_id: str, idempotency_key: str
    ) -> CaseApproval | None:
        payloads = await self._fetch_payloads(
            "case_approvals",
            "where case_id = %s and idempotency_key = %s order by approved_at desc limit 1",
            (case_id, idempotency_key),
        )
        return CaseApproval(**payloads[0]) if payloads else None

    async def get_case_approval(self, approval_id: str) -> CaseApproval | None:
        payload = await self._get_payload("case_approvals", approval_id)
        return CaseApproval(**payload) if payload else None

    async def list_case_approvals(self, case_id: str) -> list[CaseApproval]:
        return [
            CaseApproval(**payload)
            for payload in await self._fetch_payloads(
                "case_approvals",
                "where case_id = %s order by approved_at, id",
                (case_id,),
            )
        ]

    async def save_case_approval(self, approval: CaseApproval) -> None:
        await self._upsert_payload("case_approvals", approval.id, approval.model_dump(mode="json"))

    async def get_authorized_intent_by_idempotency_key(
        self, proposed_action_id: str, idempotency_key: str
    ) -> AuthorizedIntent | None:
        payloads = await self._fetch_payloads(
            "authorized_intents",
            """
            where proposed_action_id = %s and idempotency_key = %s
            order by authorized_at desc limit 1
            """,
            (proposed_action_id, idempotency_key),
        )
        return AuthorizedIntent(**payloads[0]) if payloads else None

    async def save_authorized_intent(self, intent: AuthorizedIntent) -> None:
        await self._upsert_payload("authorized_intents", intent.id, intent.model_dump(mode="json"))

    async def list_decision_audit_events(self) -> list[DecisionAuditEvent]:
        return [
            DecisionAuditEvent(**payload)
            for payload in await self._fetch_payloads(
                "decision_audit_events",
                "order by created_at desc limit 250",
            )
        ]

    async def save_decision_audit_event(self, event: DecisionAuditEvent) -> None:
        await self._upsert_payload("decision_audit_events", event.id, event.model_dump(mode="json"))

    async def create_agent_run(self, run: AgentRun) -> None:
        await self._upsert_payload("agent_runs", run.id, run.model_dump(mode="json"))

    async def create_or_reuse_agent_run(
        self, run: AgentRun, active_statuses: tuple[str, ...]
    ) -> tuple[AgentRun, bool]:
        lock_keys = [f"run-name:{run.name}"]
        if run.idempotency_key:
            lock_keys.append(f"run-idempotency:{run.idempotency_key}")
        async with self._pool.connection() as connection, connection.transaction():
            for lock_key in sorted(lock_keys):
                await connection.execute(
                    "select pg_advisory_xact_lock(hashtextextended(%s, 0))",
                    (lock_key,),
                )
            if run.idempotency_key:
                cursor = await connection.execute(
                    """
                    select payload from agent_runs
                    where payload->>'idempotency_key' = %s
                    order by updated_at desc limit 1
                    """,
                    (run.idempotency_key,),
                )
                row = await cursor.fetchone()
                if row is not None:
                    payload = cast(dict[str, Any], row)["payload"]
                    return AgentRun(**payload), False
            cursor = await connection.execute(
                """
                select payload from agent_runs
                where payload->>'name' = %s and status = any(%s)
                order by updated_at desc limit 1
                """,
                (run.name, list(active_statuses)),
            )
            row = await cursor.fetchone()
            if row is not None:
                payload = cast(dict[str, Any], row)["payload"]
                return AgentRun(**payload), False
            await connection.execute(
                """
                insert into agent_runs (id, payload, updated_at)
                values (%s, %s, now())
                """,
                (run.id, Jsonb(run.model_dump(mode="json"))),
            )
            return run, True

    async def update_agent_run(self, run: AgentRun) -> None:
        await self._upsert_payload("agent_runs", run.id, run.model_dump(mode="json"))

    async def compare_and_swap_agent_run(self, run: AgentRun, expected: AgentRun) -> bool:
        expected_updated_at = expected.model_dump(mode="json")["updated_at"]
        async with self._pool.connection() as connection:
            cursor = await connection.execute(
                """
                update agent_runs
                set payload = %s, updated_at = now()
                where id = %s and updated_at_payload = %s
                """,
                (
                    Jsonb(run.model_dump(mode="json")),
                    run.id,
                    expected_updated_at,
                ),
            )
        return cursor.rowcount > 0

    async def reap_agent_run(
        self, run: AgentRun, cutoff: datetime, reapable_statuses: tuple[str, ...]
    ) -> bool:
        # Conditional (compare-and-swap) UPDATE: only flip the anchor to its reaped payload if it
        # is STILL reapable and STILL older than the cutoff. The predicate uses the generated
        # 'status' column and the physical 'updated_at' timestamptz, both of which a concurrent
        # finalize/heartbeat bumps (status -> terminal and/or updated_at -> now()), so a real
        # write that races the sweep wins and this UPDATE matches 0 rows. Safe under multiple
        # replicas for the same reason.
        async with self._pool.connection() as connection:
            cursor = await connection.execute(
                """
                update agent_runs
                set payload = %s, updated_at = now()
                where id = %s and status = any(%s) and updated_at < %s
                """,
                (
                    Jsonb(run.model_dump(mode="json")),
                    run.id,
                    list(reapable_statuses),
                    cutoff,
                ),
            )
        return cursor.rowcount > 0

    async def get_agent_run(self, run_id: str) -> AgentRun | None:
        payload = await self._get_payload("agent_runs", run_id)
        return AgentRun(**payload) if payload else None

    async def get_agent_run_by_idempotency_key(self, idempotency_key: str) -> AgentRun | None:
        payloads = await self._fetch_payloads(
            "agent_runs",
            "where payload->>'idempotency_key' = %s order by updated_at desc limit 1",
            (idempotency_key,),
        )
        return AgentRun(**payloads[0]) if payloads else None

    async def get_active_run_by_name(
        self, name: str, active_statuses: tuple[str, ...]
    ) -> AgentRun | None:
        payloads = await self._fetch_payloads(
            "agent_runs",
            "where payload->>'name' = %s and status = any(%s) order by updated_at desc limit 1",
            (name, list(active_statuses)),
        )
        return AgentRun(**payloads[0]) if payloads else None

    async def list_stale_active_runs(
        self, cutoff: datetime, active_statuses: tuple[str, ...]
    ) -> list[AgentRun]:
        payloads = await self._fetch_payloads(
            "agent_runs",
            "where status = any(%s) and updated_at < %s order by updated_at asc",
            (list(active_statuses), cutoff),
        )
        return [AgentRun(**payload) for payload in payloads]

    async def list_agent_runs(self, case_id: str | None = None) -> list[AgentRun]:
        where = "order by updated_at desc"
        params: tuple[object, ...] = ()
        if case_id:
            where = "where case_id = %s order by updated_at desc"
            params = (case_id,)
        return [
            AgentRun(**payload)
            for payload in await self._fetch_payloads("agent_runs", where, params)
        ]

    async def import_seed(self, seed: LedgerfieldSeedImport) -> SeedImportResult:
        for supplier in seed.suppliers:
            await self._upsert_payload("suppliers", supplier.id, supplier.model_dump(mode="json"))
        for document in seed.contract_documents:
            await self._upsert_payload(
                "contract_documents", document.id, document.model_dump(mode="json")
            )
        for policy in seed.policies:
            await self._upsert_payload("policies", policy.id, policy.model_dump(mode="json"))
        for scenario in seed.scenarios:
            await self._upsert_payload("scenarios", scenario.id, scenario.model_dump(mode="json"))
        for invoice_detail in seed.invoices:
            invoice = Invoice(
                **invoice_detail.model_dump(
                    exclude={"supplier", "scenario", "lines", "findings", "evidence"}
                )
            )
            await self._upsert_payload("invoices", invoice.id, invoice.model_dump(mode="json"))
            for line in invoice_detail.lines:
                await self._upsert_payload("invoice_lines", line.id, line.model_dump(mode="json"))
            for finding in invoice_detail.findings:
                await self._upsert_payload(
                    "reconciliation_findings", finding.id, finding.model_dump(mode="json")
                )
            for evidence in invoice_detail.evidence:
                await self._upsert_payload(
                    "evidence_references", evidence.id, evidence.model_dump(mode="json")
                )
        for finding in seed.findings:
            await self._upsert_payload(
                "reconciliation_findings", finding.id, finding.model_dump(mode="json")
            )
        for evidence in seed.evidence:
            await self._upsert_payload(
                "evidence_references", evidence.id, evidence.model_dump(mode="json")
            )
        return _seed_import_result(seed)


def _seed_import_result(seed: LedgerfieldSeedImport) -> SeedImportResult:
    finding_ids = {finding.id for finding in seed.findings}
    finding_ids.update(finding.id for invoice in seed.invoices for finding in invoice.findings)
    evidence_ids = {evidence.id for evidence in seed.evidence}
    evidence_ids.update(evidence.id for invoice in seed.invoices for evidence in invoice.evidence)
    return SeedImportResult(
        source=seed.source,
        suppliers=len(seed.suppliers),
        contract_documents=len(seed.contract_documents),
        policies=len(seed.policies),
        scenarios=len(seed.scenarios),
        invoices=len(seed.invoices),
        invoice_lines=sum(len(invoice.lines) for invoice in seed.invoices),
        findings=len(finding_ids),
        evidence=len(evidence_ids),
    )


_SCHEMA_SQL = """
create table if not exists suppliers (
    id text primary key,
    payload jsonb not null,
    updated_at timestamptz not null default now()
);
create table if not exists contract_documents (
    id text primary key,
    supplier_id text generated always as (payload->>'supplier_id') stored,
    payload jsonb not null,
    updated_at timestamptz not null default now()
);
create table if not exists policies (
    id text primary key,
    payload jsonb not null,
    updated_at timestamptz not null default now()
);
create table if not exists scenarios (
    id text primary key,
    payload jsonb not null,
    updated_at timestamptz not null default now()
);
create table if not exists invoices (
    id text primary key,
    supplier_id text,
    scenario_id text,
    invoice_number text,
    payload jsonb not null,
    updated_at timestamptz not null default now()
);
create table if not exists invoice_lines (
    id text primary key,
    invoice_id text,
    payload jsonb not null,
    updated_at timestamptz not null default now()
);
create table if not exists reconciliation_findings (
    id text primary key,
    invoice_id text,
    scenario_id text,
    payload jsonb not null,
    updated_at timestamptz not null default now()
);
create table if not exists finding_validations (
    id text primary key,
    finding_id text generated always as (payload->>'finding_id') stored,
    invoice_id text generated always as (payload->>'invoice_id') stored,
    run_id text generated always as (payload->>'run_id') stored,
    case_id text generated always as (payload->>'case_id') stored,
    outcome text generated always as (payload->>'outcome') stored,
    created_at text generated always as (payload->>'created_at') stored,
    payload jsonb not null,
    updated_at timestamptz not null default now()
);
create table if not exists evidence_references (
    id text primary key,
    invoice_id text generated always as (payload->>'invoice_id') stored,
    finding_id text generated always as (payload->>'finding_id') stored,
    payload jsonb not null,
    updated_at timestamptz not null default now()
);
create table if not exists audit_events (
    id text primary key,
    created_at timestamptz not null default now(),
    caller text not null,
    auth_source text not null,
    key_label text,
    method text not null,
    route text not null,
    status integer not null,
    resource_ids jsonb not null default '{}',
    payload jsonb not null
);
create table if not exists action_types (
    id text primary key,
    payload jsonb not null,
    updated_at timestamptz not null default now()
);
create table if not exists assurance_cases (
    id text primary key,
    invoice_id text generated always as (payload->>'invoice_id') stored,
    finding_id text generated always as (payload->>'finding_id') stored,
    status text generated always as (payload->>'status') stored,
    payload jsonb not null,
    updated_at timestamptz not null default now()
);
create table if not exists case_recommendations (
    id text primary key,
    case_id text generated always as (payload->>'case_id') stored,
    created_at text generated always as (payload->>'created_at') stored,
    payload jsonb not null,
    updated_at timestamptz not null default now()
);
create table if not exists case_drafts (
    id text primary key,
    case_id text generated always as (payload->>'case_id') stored,
    created_at text generated always as (payload->>'created_at') stored,
    payload jsonb not null,
    updated_at timestamptz not null default now()
);
create table if not exists proposed_actions (
    id text primary key,
    case_id text generated always as (payload->>'case_id') stored,
    action_type_id text generated always as (payload->>'action_type_id') stored,
    status text generated always as (payload->>'status') stored,
    created_at text generated always as (payload->>'created_at') stored,
    payload jsonb not null,
    updated_at timestamptz not null default now()
);
create table if not exists case_approvals (
    id text primary key,
    case_id text generated always as (payload->>'case_id') stored,
    proposed_action_id text generated always as (payload->>'proposed_action_id') stored,
    idempotency_key text generated always as (payload->>'idempotency_key') stored,
    approved_at text generated always as (payload->>'approved_at') stored,
    payload jsonb not null,
    updated_at timestamptz not null default now()
);
create table if not exists authorized_intents (
    id text primary key,
    case_id text generated always as (payload->>'case_id') stored,
    proposed_action_id text generated always as (payload->>'proposed_action_id') stored,
    action_type_id text generated always as (payload->>'action_type_id') stored,
    idempotency_key text generated always as (payload->>'idempotency_key') stored,
    authorized_at text generated always as (payload->>'authorized_at') stored,
    payload jsonb not null,
    updated_at timestamptz not null default now()
);
create table if not exists decision_audit_events (
    id text primary key,
    case_id text generated always as (payload->>'case_id') stored,
    event_type text generated always as (payload->>'event_type') stored,
    created_at text generated always as (payload->>'created_at') stored,
    payload jsonb not null,
    updated_at timestamptz not null default now()
);
create table if not exists agent_runs (
    id text primary key,
    case_id text generated always as (payload->>'case_id') stored,
    status text generated always as (payload->>'status') stored,
    updated_at_payload text generated always as (payload->>'updated_at') stored,
    payload jsonb not null,
    updated_at timestamptz not null default now()
);
-- Partial unique indexes for idempotency. CREATE INDEX (even with IF NOT EXISTS)
-- requires table ownership and Postgres checks that ownership BEFORE evaluating
-- IF NOT EXISTS, so on a database whose tables are owned by a separate provisioning
-- role these must be guarded (create only when missing) and tolerate
-- insufficient_privilege, otherwise a non-owner app role crash-loops on startup.
do $$
begin
    if not exists (
        select 1 from pg_indexes
        where schemaname = 'public' and indexname = 'case_approvals_idempotency_idx'
    ) then
        create unique index case_approvals_idempotency_idx
            on case_approvals (case_id, idempotency_key)
            where idempotency_key is not null;
    end if;

    if not exists (
        select 1 from pg_indexes
        where schemaname = 'public' and indexname = 'authorized_intents_idempotency_idx'
    ) then
        create unique index authorized_intents_idempotency_idx
            on authorized_intents (proposed_action_id, idempotency_key)
            where idempotency_key is not null;
    end if;
exception
    when insufficient_privilege then
        raise notice
            'waypoint: skipping idempotency index creation (role "%" is not owner): %',
            current_user, sqlerrm;
end $$;

-- FabricIQ typed analytics projection (plain, replication-safe columns).
--
-- The operational store is JSONB-document shaped (id/payload/updated_at), but the
-- FabricIQ Direct Lake semantic model + Fabric Data Agent need TYPED, columnar data
-- (numeric measures, real dates, low-cardinality text dimensions + join keys) to
-- aggregate and reason over. That projection is mirrored into OneLake via Fabric
-- Mirroring for Azure Database for PostgreSQL, which imposes two hard constraints:
--   * `jsonb`/`json` columns cannot be mirrored, so the raw `payload` never replicates
--     -- these projected columns are the ONLY way the financial data reaches Fabric.
--   * generated columns are not guaranteed to be replicated by the mirroring CDC path,
--     so the projection uses PLAIN physical columns instead. They are populated by the
--     application on every write (see PostgresWaypointRepository._upsert_payload and
--     _PROJECTED_COLUMNS) and backfilled once here for rows written before this schema.
--
-- Scope: the financial/transactional reconciliation core only
-- (suppliers, invoices, invoice_lines, reconciliation_findings).
--
-- Ordering matters: the projection must be fully materialized BEFORE mirroring starts,
-- because DDL on a mirrored table (add/drop column) forces a stop + full reseed.

-- IMPORTANT: this projection runs on EVERY application startup, and the role in
-- `APP_DATABASE_CONNECTION` is not guaranteed to OWN these tables (e.g. they may have
-- been created by a separate provisioning/admin role, or by an earlier deployment run
-- under a different identity). `ALTER TABLE` requires table ownership, and Postgres
-- checks that ownership BEFORE it evaluates `IF NOT EXISTS` -- so an unconditional
-- `alter table suppliers add column if not exists ...` raises
-- `InsufficientPrivilege: must be owner of table suppliers` even when the column is
-- already present, which aborts startup and crash-loops the container.
--
-- To stay non-owner-safe every ALTER below is:
--   * guarded by an information_schema existence check, so a database that is already
--     projected issues ZERO ddl (no ownership needed for a plain SELECT), and
--   * wrapped so a residual `insufficient_privilege` degrades to a NOTICE instead of
--     aborting startup.
-- The one-time backfills need only UPDATE privilege (which the app role has, since it
-- writes these tables at runtime) and run guarded by column existence.
--
-- 1) Normalize any pre-existing GENERATED join keys on the mirrored tables to plain
--    columns (older deployments created these as `generated always`). Idempotent: on a
--    re-run there are no generated columns left, so the loop body does not execute.
--    Values are preserved by re-deriving them from `payload` after the type change.
do $$
declare projected record;
begin
    for projected in
        select table_name, column_name
        from information_schema.columns
        where table_schema = 'public'
          and is_generated = 'ALWAYS'
          and (table_name, column_name) in (
              ('invoices', 'supplier_id'),
              ('invoices', 'scenario_id'),
              ('invoices', 'invoice_number'),
              ('invoice_lines', 'invoice_id'),
              ('reconciliation_findings', 'invoice_id'),
              ('reconciliation_findings', 'scenario_id')
          )
    loop
        execute format(
            'alter table %I drop column %I',
            projected.table_name, projected.column_name
        );
        execute format(
            'alter table %I add column %I text',
            projected.table_name, projected.column_name
        );
        execute format(
            'update %I set %I = payload->>%L',
            projected.table_name, projected.column_name, projected.column_name
        );
    end loop;
exception
    when insufficient_privilege then
        raise notice
            'waypoint: skipping generated-column normalization (role "%" is not owner): %',
            current_user, sqlerrm;
end $$;

-- 2) Plain typed projection columns (idempotent, non-owner-safe) + a one-time backfill
--    for rows that predate them. Ongoing writes populate these in the application write
--    path. The ALTER is only issued when the column is genuinely missing, so an already
--    projected database owned by another role runs no ddl at all.
do $$
declare
    col record;
begin
    for col in
        select * from (values
            ('suppliers', 'name', 'text'),
            ('suppliers', 'status', 'text'),
            ('suppliers', 'category', 'text'),
            ('invoices', 'invoice_date', 'date'),
            ('invoices', 'due_date', 'date'),
            ('invoices', 'status', 'text'),
            ('invoices', 'currency', 'text'),
            ('invoices', 'total_amount', 'numeric'),
            ('invoice_lines', 'quantity', 'numeric'),
            ('invoice_lines', 'unit_price', 'numeric'),
            ('invoice_lines', 'amount', 'numeric'),
            ('invoice_lines', 'sku', 'text'),
            ('invoice_lines', 'purchase_order', 'text'),
            ('reconciliation_findings', 'category', 'text'),
            ('reconciliation_findings', 'severity', 'text'),
            ('reconciliation_findings', 'status', 'text'),
            ('reconciliation_findings', 'overpayment_amount', 'numeric')
        ) as c(table_name, column_name, column_type)
    loop
        if not exists (
            select 1 from information_schema.columns
            where table_schema = 'public'
              and table_name = col.table_name
              and column_name = col.column_name
        ) then
            begin
                execute format(
                    'alter table %I add column %I %s',
                    col.table_name, col.column_name, col.column_type
                );
            exception
                when insufficient_privilege then
                    raise notice
                        'waypoint: skipping add column %.% (role "%" is not owner): %',
                        col.table_name, col.column_name, current_user, sqlerrm;
            end;
        end if;
    end loop;
end $$;

-- 3) One-time backfills, each guarded so a column that could not be added (missing on a
--    non-owned database) does not abort startup with `undefined_column`.
do $$
begin
    if exists (
        select 1 from information_schema.columns
        where table_schema = 'public' and table_name = 'suppliers' and column_name = 'name'
    ) then
        update suppliers set
            name = payload->>'name',
            status = payload->>'status',
            category = payload->>'category'
        where name is null and status is null and category is null;
    end if;

    if exists (
        select 1 from information_schema.columns
        where table_schema = 'public' and table_name = 'invoices' and column_name = 'total_amount'
    ) then
        update invoices set
            invoice_date = nullif(payload->>'invoice_date', '')::date,
            due_date = nullif(payload->>'due_date', '')::date,
            status = payload->>'status',
            currency = payload->>'currency',
            total_amount = nullif(payload->>'total_amount', '')::numeric
        where status is null and currency is null and total_amount is null;
    end if;

    if exists (
        select 1 from information_schema.columns
        where table_schema = 'public' and table_name = 'invoice_lines' and column_name = 'amount'
    ) then
        update invoice_lines set
            quantity = nullif(payload->>'quantity', '')::numeric,
            unit_price = nullif(payload->>'unit_price', '')::numeric,
            amount = nullif(payload->>'amount', '')::numeric,
            sku = payload->>'sku',
            purchase_order = payload->>'purchase_order'
        where quantity is null and unit_price is null and amount is null;
    end if;

    if exists (
        select 1 from information_schema.columns
        where table_schema = 'public'
          and table_name = 'reconciliation_findings' and column_name = 'category'
    ) then
        update reconciliation_findings set
            category = payload->>'category',
            severity = payload->>'severity',
            status = payload->>'status',
            overpayment_amount = nullif(payload->>'overpayment_amount', '')::numeric
        where category is null and severity is null and status is null;
    end if;
exception
    when insufficient_privilege then
        raise notice
            'waypoint: skipping projection backfill (role "%" lacks update privilege): %',
            current_user, sqlerrm;
end $$;
"""


def _normalize_postgres_connection_string(connection_string: str) -> str:
    if "://" in connection_string:
        return connection_string
    key_map = {
        "host": "host",
        "port": "port",
        "database": "dbname",
        "username": "user",
        "user id": "user",
        "password": "password",
        "ssl mode": "sslmode",
    }
    parts: list[str] = []
    for segment in connection_string.split(";"):
        key, separator, value = segment.partition("=")
        if not separator or not key.strip():
            continue
        normalized_key = key_map.get(key.strip().lower(), key.strip().lower())
        parts.append(f"{normalized_key}={value.strip()}")
    return " ".join(parts)
