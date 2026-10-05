"""Seed third-party integration evidence onto a handful of demo runs.

The live assurance pipeline only calls the four Microsoft IQ planes today, so the agent map's
Integrations bubble is empty on the demo site. This command adds an **Oracle ERP** evidence lane
(Oracle Database@Azure) to the latest decision of a few chosen invoices so the demo can show a
third-party source next to Microsoft IQ.

What it writes, per invoice
---------------------------
* ``case_recommendations.payload.metadata.expert_evidence``: read by the invoice panel's
  "Evidence by source" and the register's expert/citation counts. The recommendation's
  ``content_hash`` is recomputed so it still matches the stored payload.
* ``agent_runs.payload.metadata.fanout`` on the case's latest run: read by Agent Details and the
  agent map.

Every claim is built from that invoice's own record (number, supplier, due date, PO, the amount
the decision already puts at risk) and phrased to corroborate the existing decision, never to
change it. Seeded lanes carry ``"seeded": "demo-integrations"`` so ``--remove`` can take them out
again. Re-running is safe: an invoice that already has the lane is left alone.

Run it with::

    python -m app.demo_integrations [--invoice INV-2026-08034 ...] [--remove] [--dry-run]

It uses ``APP_DATABASE_CONNECTION`` and runs in a single transaction.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .common.settings import get_settings
from .modules.cases.schemas import CaseRecommendationCreate
from .modules.records.service import _content_hash

logger = logging.getLogger(__name__)

SEED_MARKER = "demo-integrations"
ORACLE_AGENT = "oracle-erp-connector"
ORACLE_PLANE = "oracle-erp"
ORACLE_SOURCE = "Oracle ERP"

# Each invoice was picked because an ERP record is a natural, non-contradicting source for its
# existing decision. The payment-status and supplier claims apply to every invoice; a few get a
# third, invoice-specific claim.
DEFAULT_INVOICES: tuple[str, ...] = (
    "INV-2026-08034",
    "INV-2026-08462",
    "INV-2026-08273",
    "INV-2026-08140",
    "INV-2026-08602",
)


@dataclass(frozen=True)
class InvoiceFacts:
    invoice_number: str
    supplier_id: str
    supplier_name: str
    due_date: date | None
    currency: str
    purchase_order: str | None
    decision: str
    money_at_risk: Decimal


def format_money(amount: Decimal, currency: str) -> str:
    symbol = "$" if currency == "USD" else f"{currency} "
    return f"{symbol}{amount:,.0f}" if amount == amount.to_integral() else f"{symbol}{amount:,.2f}"


def _specific_claim(facts: InvoiceFacts) -> dict[str, Any] | None:
    money = format_money(facts.money_at_risk, facts.currency)
    if facts.invoice_number == "INV-2026-08462" and facts.money_at_risk > 0:
        return {
            "claim": (
                f"Oracle Payables already shows {money} paid to {facts.supplier_name} for the "
                "same service on an earlier invoice, so this charge would be paid twice."
            ),
            "source_ref": f"Oracle Payables · paid lines for {facts.supplier_id}",
            "confidence": 0.9,
            "classification": "supporting",
            "supports": facts.decision,
        }
    if facts.invoice_number == "INV-2026-08273":
        return {
            "claim": (
                f"No open purchase order in Oracle Purchasing matches this invoice from "
                f"{facts.supplier_name}, so it can't be three-way matched."
            ),
            "source_ref": f"Oracle Purchasing · open POs for {facts.supplier_id}",
            "confidence": 0.88,
            "classification": "supporting",
            "supports": facts.decision,
        }
    if facts.invoice_number == "INV-2026-08140" and facts.purchase_order:
        return {
            "claim": (
                f"{facts.purchase_order} is approved in Oracle Purchasing and the goods are "
                "received, so the invoice three-way matches."
            ),
            "source_ref": f"Oracle Purchasing · {facts.purchase_order}",
            "confidence": 0.92,
            "classification": "supporting",
            "supports": facts.decision,
        }
    return None


def build_oracle_lane(facts: InvoiceFacts) -> dict[str, Any]:
    """The Oracle ERP evidence lane for one invoice, in the shape the pipeline records."""

    due = f", due {facts.due_date:%b} {facts.due_date.day}" if facts.due_date else ""
    if facts.decision == "approve" or facts.money_at_risk <= 0:
        payment = "No holds are applied, so it will pay on schedule."
    else:
        money = format_money(facts.money_at_risk, facts.currency)
        payment = f"A hold on the disputed {money} would stop it at the next payment run."
    evidence: list[dict[str, Any]] = [
        {
            "claim": (
                f"{facts.invoice_number} is open and unpaid in Oracle Payables{due}. {payment}"
            ),
            "source_ref": f"Oracle Payables · {facts.invoice_number}",
            "confidence": 0.95,
            "classification": "supporting",
            "supports": facts.decision,
        },
        {
            "claim": (
                f"{facts.supplier_name} is an active supplier in Oracle with one approved "
                "remit-to site; its bank details haven't changed in the last 12 months."
            ),
            "source_ref": f"Oracle supplier master · {facts.supplier_id}",
            "confidence": 0.9,
            "classification": "context",
        },
    ]
    specific = _specific_claim(facts)
    if specific:
        evidence.insert(1, specific)
    return {
        "agent": ORACLE_AGENT,
        "plane": ORACLE_PLANE,
        "summary": (
            f"Checked payment status, purchase orders and the supplier record for "
            f"{facts.supplier_name}."
        ),
        "evidence": evidence,
        "seeded": SEED_MARKER,
    }


def with_lane(lanes: Any, lane: dict[str, Any]) -> tuple[list[Any], bool]:
    """Append ``lane`` unless an Oracle lane is already present. Returns (lanes, changed)."""

    current = list(lanes) if isinstance(lanes, list) else []
    if any(isinstance(item, dict) and item.get("agent") == ORACLE_AGENT for item in current):
        return current, False
    return [*current, lane], True


def without_seeded(lanes: Any) -> tuple[list[Any], bool]:
    """Drop lanes this command seeded. Returns (lanes, changed)."""

    current = list(lanes) if isinstance(lanes, list) else []
    kept = [
        item
        for item in current
        if not (isinstance(item, dict) and item.get("seeded") == SEED_MARKER)
    ]
    return kept, len(kept) != len(current)


def recommendation_hash(payload: dict[str, Any]) -> str:
    """Recompute ``content_hash`` exactly as the API does when a recommendation is created."""

    create = CaseRecommendationCreate.model_validate(payload)
    return _content_hash(create.model_dump(mode="json"))


def _decimal(value: Any) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return Decimal("0")


def _date(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _created(row: dict[str, Any]) -> datetime:
    raw = str(row["payload"].get("created_at") or "")
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return datetime.min.replace(tzinfo=UTC)


async def _latest(
    connection: psycopg.AsyncConnection[Any], table: str, column: str, value: str
) -> dict[str, Any] | None:
    cursor = await connection.execute(
        f"select id, payload from {table} where {column} = %s for update", (value,)
    )
    rows = list(await cursor.fetchall())
    return max(rows, key=_created) if rows else None


async def _facts(
    connection: psycopg.AsyncConnection[Any], invoice_id: str, recommendation: dict[str, Any]
) -> InvoiceFacts | None:
    cursor = await connection.execute("select payload from invoices where id = %s", (invoice_id,))
    row = await cursor.fetchone()
    if not row:
        return None
    invoice = row["payload"]
    supplier_id = str(invoice.get("supplier_id") or "")
    supplier_name = str((invoice.get("metadata") or {}).get("supplier_name") or "")
    if not supplier_name and supplier_id:
        cursor = await connection.execute(
            "select payload->>'name' as name from suppliers where id = %s", (supplier_id,)
        )
        supplier_row = await cursor.fetchone()
        supplier_name = (supplier_row or {}).get("name") or supplier_id
    cursor = await connection.execute(
        "select payload->>'purchase_order' as po from invoice_lines"
        " where invoice_id = %s and coalesce(payload->>'purchase_order', '') <> '' order by id",
        (invoice_id,),
    )
    po_row = await cursor.fetchone()
    payload = recommendation["payload"]
    return InvoiceFacts(
        invoice_number=str(invoice.get("invoice_number") or invoice_id),
        supplier_id=supplier_id,
        supplier_name=supplier_name or "the supplier",
        due_date=_date(invoice.get("due_date")),
        currency=str(invoice.get("currency") or "USD"),
        purchase_order=(po_row or {}).get("po"),
        decision=str(payload.get("decision") or "review"),
        money_at_risk=_decimal(payload.get("money_at_risk")),
    )


async def seed(
    connection_string: str,
    *,
    invoices: tuple[str, ...] = DEFAULT_INVOICES,
    remove: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    connection = await psycopg.AsyncConnection.connect(connection_string, row_factory=dict_row)
    results: list[dict[str, Any]] = []
    async with connection, connection.transaction(force_rollback=dry_run):
        for invoice_id in invoices:
            result: dict[str, Any] = {"invoice": invoice_id}
            results.append(result)
            assurance_case = await _latest(connection, "assurance_cases", "invoice_id", invoice_id)
            if not assurance_case:
                result["skipped"] = "no assurance case"
                continue
            recommendation = await _latest(
                connection, "case_recommendations", "case_id", assurance_case["id"]
            )
            if not recommendation:
                result["skipped"] = "no recommendation"
                continue
            run = await _latest(connection, "agent_runs", "case_id", assurance_case["id"])
            result.update(
                case=assurance_case["id"],
                recommendation=recommendation["id"],
                run=run["id"] if run else None,
                decision=recommendation["payload"].get("decision"),
            )

            lane: dict[str, Any] | None = None
            if not remove:
                facts = await _facts(connection, invoice_id, recommendation)
                if not facts:
                    result["skipped"] = "invoice not found"
                    continue
                lane = build_oracle_lane(facts)
                result["citations"] = [item["claim"] for item in lane["evidence"]]

            rec_payload = dict(recommendation["payload"])
            rec_meta = dict(rec_payload.get("metadata") or {})
            if lane:
                lanes, rec_changed = with_lane(rec_meta.get("expert_evidence"), lane)
            else:
                lanes, rec_changed = without_seeded(rec_meta.get("expert_evidence"))
            if rec_changed:
                rec_meta["expert_evidence"] = lanes
                rec_payload["metadata"] = rec_meta
                rec_payload["content_hash"] = recommendation_hash(rec_payload)
                await connection.execute(
                    "update case_recommendations set payload = %s, updated_at = now()"
                    " where id = %s",
                    (Jsonb(rec_payload), recommendation["id"]),
                )
            result["recommendation_updated"] = rec_changed

            run_changed = False
            if run:
                run_payload = dict(run["payload"])
                run_meta = dict(run_payload.get("metadata") or {})
                if lane:
                    fanout, run_changed = with_lane(run_meta.get("fanout"), lane)
                else:
                    fanout, run_changed = without_seeded(run_meta.get("fanout"))
                if run_changed:
                    run_meta["fanout"] = fanout
                    run_payload["metadata"] = run_meta
                    # Leave the run's own timestamps alone so the Activity timeline doesn't
                    # treat a demo-data fix-up as new agent activity.
                    await connection.execute(
                        "update agent_runs set payload = %s where id = %s",
                        (Jsonb(run_payload), run["id"]),
                    )
            result["run_updated"] = run_changed

    return {
        "dry_run": dry_run,
        "mode": "remove" if remove else "seed",
        "integration": ORACLE_SOURCE,
        "recommendations_updated": sum(1 for r in results if r.get("recommendation_updated")),
        "runs_updated": sum(1 for r in results if r.get("run_updated")),
        "invoices": results,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--invoice",
        action="append",
        dest="invoices",
        help="Invoice id to seed (repeatable). Defaults to the curated demo set.",
    )
    parser.add_argument("--remove", action="store_true", help="Remove seeded lanes instead.")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)
    connection = get_settings().database_connection
    if not connection:
        parser.error("APP_DATABASE_CONNECTION must be set")
    summary = asyncio.run(
        seed(
            _psycopg_conninfo(connection),
            invoices=tuple(args.invoices) if args.invoices else DEFAULT_INVOICES,
            remove=args.remove,
            dry_run=args.dry_run,
        )
    )
    print(json.dumps(summary, indent=2, default=str))


def _psycopg_conninfo(connection: str) -> str:
    from .common.repository import _normalize_postgres_connection_string

    return _normalize_postgres_connection_string(connection)


if __name__ == "__main__":
    main()
