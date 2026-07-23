"""Business logic for Waypoint invoice assurance data."""

import asyncio
import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal
from uuid import uuid4

from ...common.onelake import OneLakeClient, ResolvedBytes
from ...common.repository import WaypointRepository
from ...common.tracer import trace
from .schemas import (
    AuditEvent,
    ContractDocument,
    ContractDocumentDetail,
    EvidenceReference,
    FindingValidation,
    FindingValidationCreate,
    Invoice,
    InvoiceDecision,
    InvoiceDetail,
    LedgerfieldSeedImport,
    Policy,
    PolicyDetail,
    ReconciliationFinding,
    Scenario,
    SeedImportResult,
    Supplier,
)


@dataclass
class _AgentAttribution:
    """Newest agent-run decision joined to a seed-corpus invoice row."""

    has_agent_decision: bool = False
    decision_label: str | None = None
    money_at_risk: Decimal | None = None
    confidence: Decimal | None = None
    confidence_calibrated: bool = False
    title: str | None = None
    source_count: int = 0
    plane_count: int = 0
    run_count: int = 0
    run_index: int | None = None
    run_at: datetime | None = None
    case_id: str | None = None


_TERMINAL_RUN_STATUSES = frozenset(
    {
        "completed",
        "complete",
        "succeeded",
        "success",
        "failed",
        "error",
        "errored",
        "cancelled",
        "canceled",
        "closed",
        "done",
    }
)


def _run_is_active(status: str | None) -> bool:
    """A run counts as in-flight until it reaches a terminal status."""
    if not status:
        return False
    return status.strip().lower() not in _TERMINAL_RUN_STATUSES


class WaypointService:
    """Service boundary for Waypoint-owned runtime data."""

    def __init__(
        self,
        repository: WaypointRepository,
        onelake: OneLakeClient | None = None,
    ) -> None:
        self.repository = repository
        self.onelake = onelake

    @trace
    async def list_suppliers(self) -> list[Supplier]:
        return await self.repository.list_suppliers()

    @trace
    async def list_scenarios(self) -> list[Scenario]:
        return await self.repository.list_scenarios()

    @trace
    async def get_contract_document(self, document_id: str) -> ContractDocument | None:
        return await self.repository.get_contract_document(document_id)

    @trace
    async def get_contract_document_detail(
        self,
        document_id: str,
        include_content: bool = False,
    ) -> ContractDocumentDetail | None:
        document = await self.repository.get_contract_document(document_id)
        if not document:
            return None
        return await asyncio.to_thread(
            build_contract_document_detail,
            document,
            self.onelake,
            include_content,
        )

    @trace
    async def get_policy(self, policy_id: str) -> Policy | None:
        return await self.repository.get_policy(policy_id)

    @trace
    async def get_policy_detail(
        self,
        policy_id: str,
        include_content: bool = False,
    ) -> PolicyDetail | None:
        policy = await self.repository.get_policy(policy_id)
        if not policy:
            return None
        return await asyncio.to_thread(
            build_policy_detail,
            policy,
            self.onelake,
            include_content,
        )

    @trace
    async def get_invoice_pdf(self, invoice_id: str) -> ResolvedBytes | None:
        """Resolve an invoice's PDF bytes from the corpus lake.

        Returns ``None`` when the invoice does not exist or has no ``pdf_uri``. When the
        invoice exists but the bytes cannot be read (OneLake unconfigured or the file is
        missing), a :class:`ResolvedBytes` with ``data=None`` and a ``uri-only`` content
        source is returned so callers can surface a graceful fallback.
        """

        detail = await self.repository.get_invoice_detail(invoice_id)
        if not detail or not detail.pdf_uri:
            return None
        if self.onelake is None:
            return ResolvedBytes(data=None, content_source="uri-only", path=detail.pdf_uri)
        return await asyncio.to_thread(
            self.onelake.resolve_document_bytes,
            detail.pdf_uri,
            "invoice-pdf",
        )

    @trace
    async def list_invoices(
        self,
        supplier_id: str | None = None,
        invoice_number: str | None = None,
    ) -> list[Invoice]:
        return await self.repository.list_invoices(supplier_id, invoice_number)

    @trace
    async def list_invoice_decisions(self) -> list[InvoiceDecision]:
        invoices = await self.repository.list_invoices()
        active_keys = await self._active_review_keys()
        decisions: list[InvoiceDecision] = []
        for invoice in invoices:
            detail = await self.repository.get_invoice_detail(invoice.id)
            if not detail:
                continue
            attribution = await self._resolve_agent_attribution(detail.id)
            has_active_run = detail.id in active_keys or detail.invoice_number in active_keys
            # The register includes the complete invoice work queue so every imported invoice can
            # be selected for assurance. Seed findings are expected outcomes, not runtime evidence;
            # withhold them until an agent recommendation exists.
            finding = (
                detail.findings[0] if attribution.has_agent_decision and detail.findings else None
            )
            basis_summary = _basis_summary(finding) if finding else None
            meaningful_title = _meaningful_case_title(attribution.title, detail.invoice_number)
            evidence = (
                [
                    item
                    for item in detail.evidence
                    if item.id in finding.evidence_ids or not finding.evidence_ids
                ]
                if finding
                else []
            )
            if attribution.has_agent_decision:
                decision_label = attribution.decision_label or (
                    _decision_label(finding.status) if finding else "Review"
                )
            elif has_active_run:
                decision_label = "Pending"
            else:
                decision_label = "Not run"
            if attribution.has_agent_decision:
                overpayment_amount = (
                    attribution.money_at_risk
                    if attribution.money_at_risk is not None
                    else (finding.overpayment_amount if finding else Decimal("0"))
                )
            else:
                # In-flight review: withhold any money claim until a decision is recorded.
                overpayment_amount = Decimal("0")
            decisions.append(
                InvoiceDecision(
                    invoice_id=detail.id,
                    invoice_number=detail.invoice_number,
                    supplier_id=detail.supplier_id,
                    supplier_name=detail.supplier.name if detail.supplier else detail.supplier_id,
                    scenario_id=detail.scenario_id,
                    scenario_name=detail.scenario.name if detail.scenario else None,
                    decision=decision_label,
                    category=finding.category if finding else "",
                    reasoning=(
                        finding.summary
                        if finding
                        else (
                            "Assurance review is in progress."
                            if has_active_run
                            else "Ready for assurance."
                        )
                    ),
                    severity=finding.severity if finding else "",
                    status=(
                        finding.status
                        if finding
                        else ("pending" if has_active_run else "not_started")
                    ),
                    currency=detail.currency,
                    overpayment_amount=overpayment_amount,
                    overpayment_display=_format_money(overpayment_amount, detail.currency),
                    source=_evidence_source_summary(evidence),
                    evidence_count=len(evidence),
                    contract_document_ids=finding.contract_document_ids if finding else [],
                    policy_ids=finding.policy_ids if finding else [],
                    basis_summary=basis_summary,
                    basis_types=_basis_types(finding) if finding else [],
                    html_uri=detail.html_uri,
                    pdf_uri=detail.pdf_uri,
                    has_agent_decision=attribution.has_agent_decision,
                    agent_decision=attribution.decision_label,
                    agent_run_count=attribution.run_count,
                    agent_run_index=attribution.run_index,
                    agent_run_at=attribution.run_at,
                    agent_case_id=attribution.case_id,
                    confidence=attribution.confidence,
                    confidence_calibrated=attribution.confidence_calibrated,
                    agent_title=meaningful_title,
                    agent_source_count=attribution.source_count,
                    agent_plane_count=attribution.plane_count,
                    has_active_run=has_active_run,
                    metadata={
                        "invoice_status": detail.status,
                        "line_count": len(detail.lines),
                    },
                )
            )
        return decisions

    async def _active_review_keys(self) -> set[str]:
        """Invoice ids/numbers with an in-flight (non-terminal) agent run.

        Runs carry ``metadata.invoice_id`` / ``metadata.invoice_number`` and are created at run
        start, before any recommendation is written, so this lets the register surface an invoice
        as "Pending" while the pipeline is still working it.
        """
        runs = await self.repository.list_agent_runs()
        keys: set[str] = set()
        for run in runs:
            if not _run_is_active(run.status):
                continue
            meta = run.metadata or {}
            for value in (meta.get("invoice_id"), meta.get("invoice_number")):
                if value:
                    keys.add(str(value))
        return keys

    async def _resolve_agent_attribution(self, invoice_id: str) -> "_AgentAttribution":
        """Join the newest agent case decision onto a seed-corpus invoice row.

        Reuses the shared case/recommendation reads so the decision-graph list reflects the
        same newest agent run that the invoice drawer leads with, plus the per-row run count
        and timestamp used for the attribution badge. Invoices with no agent case are left
        untouched (empty attribution).
        """
        cases = await self.repository.list_cases(invoice_id=invoice_id)
        if not cases:
            return _AgentAttribution()
        ordered = sorted(cases, key=lambda case: (case.created_at, case.id))
        newest = ordered[-1]
        recommendations = await self.repository.list_case_recommendations(newest.id)
        latest = recommendations[-1] if recommendations else None
        if latest is None:
            return _AgentAttribution()
        plane_count, source_count = _expert_evidence_counts(latest.metadata)
        confidence_calibrated = latest.metadata.get("confidence_calibrated") is True
        return _AgentAttribution(
            has_agent_decision=True,
            decision_label=_agent_decision_label(latest.decision),
            money_at_risk=latest.money_at_risk,
            confidence=latest.confidence if confidence_calibrated else None,
            confidence_calibrated=confidence_calibrated,
            title=newest.title,
            source_count=source_count,
            plane_count=plane_count,
            run_count=len(ordered),
            run_index=len(ordered),
            run_at=latest.created_at or newest.updated_at,
            case_id=newest.id,
        )

    @trace
    async def get_invoice_detail(self, invoice_id: str) -> InvoiceDetail | None:
        return await self.repository.get_invoice_detail(invoice_id)

    @trace
    async def list_findings(self, invoice_id: str | None = None) -> list[ReconciliationFinding]:
        return await self.repository.list_findings(invoice_id)

    @trace
    async def create_finding_validation(
        self,
        finding_id: str,
        validation_create: FindingValidationCreate,
        *,
        actor: str,
        auth_source: str,
    ) -> FindingValidation:
        finding = await self._require_finding(finding_id)
        if not await self.repository.get_agent_run(validation_create.run_id):
            raise ValueError(f"Run '{validation_create.run_id}' not found.")
        if validation_create.case_id:
            assurance_case = await self.repository.get_case(validation_create.case_id)
            if not assurance_case:
                raise ValueError(f"Case '{validation_create.case_id}' not found.")
            if assurance_case.invoice_id != finding.invoice_id or assurance_case.finding_id not in (
                None,
                finding.id,
            ):
                raise ValueError(
                    f"Case '{validation_create.case_id}' is not linked to finding "
                    f"'{finding.id}' on invoice '{finding.invoice_id}'."
                )
        await self._validate_validation_evidence(finding, validation_create.evidence_ids)

        payload = validation_create.model_dump(
            mode="json",
            exclude={"validator", "evidence_hash"},
        )
        evidence_hash = validation_create.evidence_hash or _content_hash(
            {
                "finding_id": finding.id,
                "invoice_id": finding.invoice_id,
                "run_id": validation_create.run_id,
                "evidence_ids": validation_create.evidence_ids,
                "basis_summary": validation_create.basis_summary,
                "evidence_snapshot": validation_create.evidence_snapshot,
            }
        )
        validation = FindingValidation(
            id=f"finding-validation-{uuid4().hex}",
            finding_id=finding.id,
            invoice_id=finding.invoice_id,
            validator=validation_create.validator or actor,
            evidence_hash=evidence_hash,
            created_by=actor,
            auth_source=auth_source,
            created_at=_now(),
            **payload,
        )
        await self.repository.create_finding_validation(validation)
        return validation

    @trace
    async def list_finding_validations(self, finding_id: str) -> list[FindingValidation]:
        await self._require_finding(finding_id)
        return await self.repository.list_finding_validations(finding_id)

    @trace
    async def list_evidence(
        self,
        invoice_id: str | None = None,
        finding_id: str | None = None,
    ) -> list[EvidenceReference]:
        return await self.repository.list_evidence(invoice_id, finding_id)

    @trace
    async def list_audit_events(self) -> list[AuditEvent]:
        return await self.repository.list_audit_events()

    @trace
    async def import_ledgerfield_seed(self, seed: LedgerfieldSeedImport) -> SeedImportResult:
        await self._validate_seed(seed)
        return await self.repository.import_seed(seed)

    async def _validate_seed(self, seed: LedgerfieldSeedImport) -> None:
        supplier_ids = {supplier.id for supplier in await self.repository.list_suppliers()}
        supplier_ids.update(supplier.id for supplier in seed.suppliers)
        scenario_ids = {scenario.id for scenario in await self.repository.list_scenarios()}
        scenario_ids.update(scenario.id for scenario in seed.scenarios)
        contract_document_ids = {
            document.id for document in await self.repository.list_contract_documents()
        }
        contract_document_ids.update(document.id for document in seed.contract_documents)
        policy_ids = {policy.id for policy in await self.repository.list_policies()}
        policy_ids.update(policy.id for policy in seed.policies)
        existing_invoices = await self.repository.list_invoices()
        invoice_ids = {invoice.id for invoice in existing_invoices}
        invoice_numbers = {invoice.invoice_number for invoice in existing_invoices}
        invoice_ids.update(invoice.id for invoice in seed.invoices)
        invoice_numbers.update(invoice.invoice_number for invoice in seed.invoices)
        finding_ids = {finding.id for finding in await self.repository.list_findings()}

        errors: list[str] = []
        for invoice in seed.invoices:
            if invoice.supplier_id not in supplier_ids:
                errors.append(
                    f"Invoice '{invoice.id}' references unknown supplier '{invoice.supplier_id}'."
                )
            if invoice.scenario_id and invoice.scenario_id not in scenario_ids:
                errors.append(
                    f"Invoice '{invoice.id}' references unknown scenario '{invoice.scenario_id}'."
                )
            for line in invoice.lines:
                if line.invoice_id != invoice.id and line.invoice_id not in invoice_ids:
                    errors.append(
                        f"Line '{line.id}' references unknown invoice '{line.invoice_id}'."
                    )
            for finding in invoice.findings:
                finding_ids.add(finding.id)
                if finding.invoice_id != invoice.id and finding.invoice_id not in invoice_ids:
                    errors.append(
                        f"Finding '{finding.id}' references unknown invoice '{finding.invoice_id}'."
                    )
                if finding.scenario_id and finding.scenario_id not in scenario_ids:
                    errors.append(
                        f"Finding '{finding.id}' references unknown scenario "
                        f"'{finding.scenario_id}'."
                    )
                errors.extend(_validate_finding_basis(finding, contract_document_ids, policy_ids))
            for evidence in invoice.evidence:
                if (
                    evidence.invoice_id
                    and evidence.invoice_id != invoice.id
                    and evidence.invoice_id not in invoice_ids
                ):
                    errors.append(
                        f"Evidence '{evidence.id}' references unknown invoice "
                        f"'{evidence.invoice_id}'."
                    )

        for finding in seed.findings:
            finding_ids.add(finding.id)
            if finding.invoice_id not in invoice_ids:
                errors.append(
                    f"Finding '{finding.id}' references unknown invoice '{finding.invoice_id}'."
                )
            if finding.scenario_id and finding.scenario_id not in scenario_ids:
                errors.append(
                    f"Finding '{finding.id}' references unknown scenario '{finding.scenario_id}'."
                )
            errors.extend(_validate_finding_basis(finding, contract_document_ids, policy_ids))

        for evidence in seed.evidence:
            if evidence.invoice_id and evidence.invoice_id not in invoice_ids:
                errors.append(
                    f"Evidence '{evidence.id}' references unknown invoice '{evidence.invoice_id}'."
                )
            if evidence.finding_id and evidence.finding_id not in finding_ids:
                errors.append(
                    f"Evidence '{evidence.id}' references unknown finding '{evidence.finding_id}'."
                )

        duplicate_invoice_numbers = _duplicates(invoice.invoice_number for invoice in seed.invoices)
        if duplicate_invoice_numbers:
            errors.append(
                f"Duplicate invoice numbers in seed: {', '.join(duplicate_invoice_numbers)}."
            )

        if errors:
            raise ValueError("; ".join(errors))

    async def _require_finding(self, finding_id: str) -> ReconciliationFinding:
        findings = await self.repository.list_findings()
        finding = next((item for item in findings if item.id == finding_id), None)
        if not finding:
            raise LookupError(f"Finding '{finding_id}' not found.")
        return finding

    async def _validate_validation_evidence(
        self,
        finding: ReconciliationFinding,
        evidence_ids: list[str],
    ) -> None:
        if not evidence_ids:
            return
        evidence_by_id = {
            item.id: item
            for item in await self.repository.list_evidence(
                invoice_id=finding.invoice_id,
                finding_id=finding.id,
            )
        }
        missing = [evidence_id for evidence_id in evidence_ids if evidence_id not in evidence_by_id]
        if missing:
            raise ValueError(
                f"Evidence ids do not belong to finding '{finding.id}': {', '.join(missing)}."
            )


def _policy_document_uri(policy: Policy) -> str:
    """Resolve a corpus document reference for a policy.

    Prefers an explicit ``uri``/``source_uri`` in policy metadata; otherwise falls back to the
    ``{policy_id}.md`` convention under the corpus ``policies`` folder.
    """

    for key in ("uri", "source_uri", "document_uri"):
        value = policy.metadata.get(key)
        if isinstance(value, str) and value:
            return value
    return f"{policy.id}.md"


def build_contract_document_detail(
    document: ContractDocument,
    onelake: OneLakeClient | None,
    include_content: bool,
) -> ContractDocumentDetail:
    """Build a contract document detail, resolving text from OneLake when requested."""

    text: str | None = None
    content_source = "uri-only"
    if include_content and onelake is not None:
        resolved = onelake.resolve_document(document.uri, "contract")
        text = resolved.text
        content_source = resolved.content_source
    return ContractDocumentDetail(
        **document.model_dump(),
        text=text,
        content_source=content_source,  # type: ignore[arg-type]
    )


def build_policy_detail(
    policy: Policy,
    onelake: OneLakeClient | None,
    include_content: bool,
) -> PolicyDetail:
    """Build a policy detail, resolving text from OneLake when requested."""

    text: str | None = None
    content_source = "uri-only"
    if include_content and onelake is not None:
        resolved = onelake.resolve_document(_policy_document_uri(policy), "policy")
        text = resolved.text
        content_source = resolved.content_source
    return PolicyDetail(
        **policy.model_dump(),
        text=text,
        content_source=content_source,  # type: ignore[arg-type]
    )


def _decision_label(status: str) -> str:
    return {
        "approved": "Approve",
        "recover": "Recover",
        "escalate": "Escalate",
        "review": "Review",
        "closed": "Closed",
        "open": "Review",
    }.get(status, status.title())


_AGENT_DECISION_LABELS = {
    "approve": "Approve",
    "recover": "Recover",
    "escalate": "Escalate",
    "review": "Review",
}


def _agent_decision_label(decision: str) -> str:
    return _AGENT_DECISION_LABELS.get(decision, decision.title())


def _meaningful_case_title(title: str | None, invoice_number: str) -> str | None:
    """Return a human-authored case title, or None for the server's fallback title.

    ``AssuranceCaseService.create_case`` fabricates a placeholder title when the
    recorder opens a case without one — either the bare ``invoice_number`` or the
    ``"{invoice_number}: {category}"`` form. This happens for every case the
    orchestrator early-opens (the descriptive title from the decision does not exist
    yet at fan-out time, and ``title`` is set-once at create). Those placeholders are
    not reasoning, so the register should fall through to the finding summary rather
    than echo the invoice number. A genuine title (e.g. "Recover duplicate QA release
    testing charge for INV-…") passes through untouched — even when it *ends* with the
    invoice number — because only a leading ``invoice_number`` marks the fallback.
    """
    if title is None:
        return None
    stripped = title.strip()
    if not stripped:
        return None
    if stripped == invoice_number or stripped.startswith(f"{invoice_number}:"):
        return None
    return stripped


def _expert_evidence_counts(metadata: dict[str, object]) -> tuple[int, int]:
    """Count corroborating expert planes and their underlying sources.

    Mirrors the per-expert evidence lanes the invoice drawer renders from
    ``recommendation.metadata.expert_evidence`` so the list's source/plane summary agrees
    with the drawer. Returns ``(plane_count, source_count)``; missing/malformed metadata
    yields zeros.
    """

    planes = metadata.get("expert_evidence")
    if not isinstance(planes, list):
        return 0, 0
    plane_count = 0
    source_count = 0
    for plane in planes:
        if not isinstance(plane, dict):
            continue
        plane_count += 1
        evidence = plane.get("evidence")
        if isinstance(evidence, list):
            source_count += len(evidence)
    return plane_count, source_count


def _format_money(amount: Decimal, currency: str) -> str:
    numeric = float(amount)
    symbol = "$" if currency == "USD" else f"{currency} "
    return f"{symbol}{numeric:,.0f}" if numeric.is_integer() else f"{symbol}{numeric:,.2f}"


def _evidence_source_summary(evidence: list[EvidenceReference]) -> str:
    if not evidence:
        return "No evidence"
    labels = [item.title or item.evidence_type for item in evidence[:3]]
    suffix = f" + {len(evidence) - 3} more" if len(evidence) > 3 else ""
    return " + ".join(labels) + suffix


def _now() -> datetime:
    return datetime.now(UTC)


def _content_hash(payload: dict[str, object]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


def _basis_summary(finding: ReconciliationFinding) -> str | None:
    if finding.basis_summary:
        return finding.basis_summary
    metadata_summary = finding.metadata.get("basis_summary")
    return str(metadata_summary) if metadata_summary else None


def _basis_types(finding: ReconciliationFinding) -> list[Literal["contract", "policy"]]:
    basis_types: list[Literal["contract", "policy"]] = []
    if finding.contract_document_ids:
        basis_types.append("contract")
    if finding.policy_ids:
        basis_types.append("policy")
    return basis_types


def _validate_finding_basis(
    finding: ReconciliationFinding,
    contract_document_ids: set[str],
    policy_ids: set[str],
) -> list[str]:
    errors: list[str] = []
    for document_id in finding.contract_document_ids:
        if document_id not in contract_document_ids:
            errors.append(
                f"Finding '{finding.id}' references unknown contract document '{document_id}'."
            )
    for policy_id in finding.policy_ids:
        if policy_id not in policy_ids:
            errors.append(f"Finding '{finding.id}' references unknown policy '{policy_id}'.")
    return errors


def _duplicates(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for value in values:
        text = str(value)
        if text in seen:
            duplicates.add(text)
        seen.add(text)
    return sorted(duplicates)
