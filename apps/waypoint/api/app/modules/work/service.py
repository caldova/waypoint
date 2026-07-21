"""Business logic for derived operational work views."""

import asyncio

from ...common.onelake import OneLakeClient
from ...common.repository import WaypointRepository
from ...common.tracer import trace
from ..records.schemas import Classification, InvoiceDetail
from ..records.service import build_contract_document_detail, build_policy_detail
from .schemas import ContextRedaction, InvoiceContextBundle, WorkQueueItem


class WorkService:
    """Service boundary for derived work and context views."""

    def __init__(
        self,
        repository: WaypointRepository,
        onelake: OneLakeClient | None = None,
    ) -> None:
        self.repository = repository
        self.onelake = onelake

    @trace
    async def list_work_queue(self) -> list[WorkQueueItem]:
        items: list[WorkQueueItem] = []
        for invoice in await self.repository.list_invoices():
            detail = await self.repository.get_invoice_detail(invoice.id)
            if not detail:
                continue
            supplier_name = detail.supplier.name if detail.supplier else detail.supplier_id
            for finding in detail.findings:
                if finding.status == "closed":
                    continue
                cases = await self.repository.list_cases(
                    invoice_id=detail.id,
                    finding_id=finding.id,
                )
                case = cases[0] if cases else None
                items.append(
                    WorkQueueItem(
                        invoice_id=detail.id,
                        invoice_number=detail.invoice_number,
                        supplier_id=detail.supplier_id,
                        supplier_name=supplier_name,
                        finding_id=finding.id,
                        case_id=case.id if case else None,
                        severity=finding.severity,
                        status=case.status if case else finding.status,
                        category=finding.category,
                        summary=finding.summary,
                        currency=detail.currency,
                        money_at_risk=finding.overpayment_amount,
                        classification=case.classification if case else "standard",
                    )
                )
        return sorted(items, key=lambda item: (item.severity != "high", item.invoice_number))

    @trace
    async def get_invoice_context(
        self,
        invoice_id: str,
        *,
        include_sensitive: bool = False,
    ) -> InvoiceContextBundle | None:
        detail = await self.repository.get_invoice_detail(invoice_id)
        if not detail:
            return None

        contract_ids = {
            document_id
            for finding in detail.findings
            for document_id in finding.contract_document_ids
        }
        policy_ids = {policy_id for finding in detail.findings for policy_id in finding.policy_ids}
        contracts = [
            await asyncio.to_thread(
                build_contract_document_detail,
                document,
                self.onelake,
                True,
            )
            for document_id in sorted(contract_ids)
            if (document := await self.repository.get_contract_document(document_id))
        ]
        policies = [
            await asyncio.to_thread(
                build_policy_detail,
                policy,
                self.onelake,
                True,
            )
            for policy_id in sorted(policy_ids)
            if (policy := await self.repository.get_policy(policy_id))
        ]
        redactions: list[ContextRedaction] = []
        if not include_sensitive:
            visible_evidence = []
            for evidence in detail.evidence:
                classification = str(evidence.metadata.get("classification", "standard"))
                if classification in {"ip_sensitive", "restricted"}:
                    redaction_classification: Classification = (
                        "ip_sensitive" if classification == "ip_sensitive" else "restricted"
                    )
                    redactions.append(
                        ContextRedaction(
                            section=f"evidence:{evidence.id}",
                            reason="Caller is not cleared for IP-sensitive evidence.",
                            classification=redaction_classification,
                        )
                    )
                else:
                    visible_evidence.append(evidence)
            detail = InvoiceDetail(**{**detail.model_dump(), "evidence": visible_evidence})
        return InvoiceContextBundle(
            invoice=detail,
            contract_documents=contracts,
            policies=policies,
            cases=await self.repository.list_cases(invoice_id=invoice_id),
            allowed_actions=await self.repository.list_action_types(),
            redactions=redactions,
            metadata={"snapshot_policy": "decision-relevant data must be copied before approval"},
        )
