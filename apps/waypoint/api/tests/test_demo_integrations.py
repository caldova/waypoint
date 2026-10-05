"""Tests for the demo integration seed (``python -m app.demo_integrations``)."""

import os
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

import psycopg
import pytest
from psycopg.types.json import Jsonb

from app.common.repository import PostgresWaypointRepository
from app.demo_integrations import (
    ORACLE_AGENT,
    SEED_MARKER,
    InvoiceFacts,
    build_oracle_lane,
    recommendation_hash,
    seed,
    with_lane,
    without_seeded,
)
from app.modules.cases.schemas import CaseRecommendation, CaseRecommendationCreate
from app.modules.records.service import _content_hash


def _facts(**overrides) -> InvoiceFacts:  # type: ignore[no-untyped-def]
    values = {
        "invoice_number": "INV-2026-08462",
        "supplier_id": "sup-012",
        "supplier_name": "Valence Cold Chain Logistics",
        "due_date": date(2026, 10, 23),
        "currency": "USD",
        "purchase_order": "PO-VCC-8462",
        "decision": "recover",
        "money_at_risk": Decimal("28500.00"),
    }
    values.update(overrides)
    return InvoiceFacts(**values)


def test_lane_is_grounded_in_the_invoice_and_backs_the_decision():
    lane = build_oracle_lane(_facts())

    assert lane["agent"] == ORACLE_AGENT and lane["seeded"] == SEED_MARKER
    claims = [item["claim"] for item in lane["evidence"]]
    assert claims[0].startswith("INV-2026-08462 is open and unpaid in Oracle Payables, due Oct 23")
    assert "hold on the disputed $28,500" in claims[0]
    assert "paid twice" in claims[1]
    assert all(item["source_ref"].startswith("Oracle ") for item in lane["evidence"])
    assert all(item.get("supports") in (None, "recover") for item in lane["evidence"])


def test_approved_invoices_get_no_hold_and_matching_po_claim():
    lane = build_oracle_lane(
        _facts(
            invoice_number="INV-2026-08140",
            purchase_order="PO-ARB-8104",
            decision="approve",
            money_at_risk=Decimal("0"),
        )
    )
    claims = [item["claim"] for item in lane["evidence"]]

    assert "No holds are applied" in claims[0]
    assert claims[1].startswith("PO-ARB-8104 is approved in Oracle Purchasing")
    assert len(claims) == 3


def test_generic_invoices_get_two_claims():
    lane = build_oracle_lane(_facts(invoice_number="INV-2026-08602", due_date=None))

    assert len(lane["evidence"]) == 2
    assert "due" not in lane["evidence"][0]["claim"].split(".")[0]


def test_with_lane_is_idempotent_and_without_seeded_only_removes_seeded():
    iq_lane = {"agent": "contract-policy-expert", "plane": "foundryiq", "evidence": []}
    lane = build_oracle_lane(_facts())

    once, changed = with_lane([iq_lane], lane)
    twice, changed_again = with_lane(once, lane)
    removed, removed_changed = without_seeded(twice)

    assert changed and not changed_again and twice == once
    assert removed == [iq_lane] and removed_changed
    assert without_seeded([iq_lane]) == ([iq_lane], False)
    assert with_lane(None, lane) == ([lane], True)


def test_recommendation_hash_matches_how_the_api_creates_it():
    create = CaseRecommendationCreate(
        decision="recover",
        reasoning="Duplicate submission",
        confidence=Decimal("0.82"),
        money_at_risk=Decimal("28500"),
        metadata={"expert_evidence": [{"agent": "x", "evidence": []}]},
    )
    stored = CaseRecommendation(
        id="rec-1",
        case_id="case-1",
        content_hash=_content_hash(create.model_dump(mode="json")),
        created_by="waypoint-recorder",
        created_at=datetime(2026, 7, 7, tzinfo=UTC),
        **create.model_dump(),
    ).model_dump(mode="json")

    assert recommendation_hash(stored) == stored["content_hash"]


@pytest.mark.asyncio
async def test_seed_and_remove_against_postgres():
    connection_string = os.environ.get("WAYPOINT_TEST_DATABASE_CONNECTION")
    if not connection_string:
        pytest.skip("WAYPOINT_TEST_DATABASE_CONNECTION is required for PostgreSQL coverage")

    repository = PostgresWaypointRepository(connection_string)
    await repository.initialize(load_default_seed=False)
    await repository.close()

    tag = uuid4().hex[:8]
    invoice_id, case_id, rec_id, run_id = (
        f"INV-T-{tag}",
        f"case-{tag}",
        f"rec-{tag}",
        f"run-{tag}",
    )
    iq_lane = {
        "agent": "contract-policy-expert",
        "plane": "foundryiq",
        "evidence": [{"claim": "Cap 4%", "source_ref": "MSA §7.2"}],
    }
    create = CaseRecommendationCreate(
        decision="recover",
        reasoning="Duplicate submission",
        money_at_risk=Decimal("28500"),
        metadata={"expert_evidence": [iq_lane]},
    )
    recommendation = CaseRecommendation(
        id=rec_id,
        case_id=case_id,
        content_hash=_content_hash(create.model_dump(mode="json")),
        created_by="waypoint-recorder",
        created_at=datetime(2026, 7, 7, tzinfo=UTC),
        **create.model_dump(),
    ).model_dump(mode="json")
    created = "2026-07-07T22:27:10Z"

    async with await psycopg.AsyncConnection.connect(connection_string) as connection:
        await connection.execute(
            "insert into invoices (id, supplier_id, invoice_number, payload)"
            " values (%s, %s, %s, %s)",
            (
                invoice_id,
                "sup-012",
                invoice_id,
                Jsonb(
                    {
                        "id": invoice_id,
                        "invoice_number": invoice_id,
                        "supplier_id": "sup-012",
                        "due_date": "2026-10-23",
                        "currency": "USD",
                        "metadata": {"supplier_name": "Valence Cold Chain Logistics"},
                    }
                ),
            ),
        )
        await connection.execute(
            "insert into invoice_lines (id, invoice_id, payload) values (%s, %s, %s)",
            (f"{invoice_id}-L1", invoice_id, Jsonb({"purchase_order": "PO-VCC-8462"})),
        )
        await connection.execute(
            "insert into assurance_cases (id, payload) values (%s, %s)",
            (case_id, Jsonb({"id": case_id, "invoice_id": invoice_id, "created_at": created})),
        )
        await connection.execute(
            "insert into case_recommendations (id, payload) values (%s, %s)",
            (rec_id, Jsonb(recommendation)),
        )
        await connection.execute(
            "insert into agent_runs (id, payload) values (%s, %s)",
            (
                run_id,
                Jsonb(
                    {
                        "id": run_id,
                        "case_id": case_id,
                        "created_at": created,
                        "updated_at": created,
                        "metadata": {"fanout": [iq_lane]},
                    }
                ),
            ),
        )

    async def read() -> tuple[dict, dict]:  # type: ignore[type-arg]
        async with await psycopg.AsyncConnection.connect(connection_string) as connection:
            rec = await (
                await connection.execute(
                    "select payload from case_recommendations where id = %s", (rec_id,)
                )
            ).fetchone()
            run = await (
                await connection.execute("select payload from agent_runs where id = %s", (run_id,))
            ).fetchone()
        return rec[0], run[0]  # type: ignore[index]

    try:
        dry = await seed(connection_string, invoices=(invoice_id,), dry_run=True)
        rec, run = await read()
        assert dry["recommendations_updated"] == 1 and len(rec["metadata"]["expert_evidence"]) == 1

        summary = await seed(connection_string, invoices=(invoice_id,))
        again = await seed(connection_string, invoices=(invoice_id,))
        rec, run = await read()

        assert summary["recommendations_updated"] == 1 and summary["runs_updated"] == 1
        assert again["recommendations_updated"] == 0 and again["runs_updated"] == 0
        assert [lane["agent"] for lane in rec["metadata"]["expert_evidence"]] == [
            "contract-policy-expert",
            ORACLE_AGENT,
        ]
        assert run["metadata"]["fanout"][-1]["agent"] == ORACLE_AGENT
        assert run["updated_at"] == created
        assert rec["content_hash"] == recommendation_hash(rec)
        assert rec["content_hash"] != recommendation["content_hash"]

        removed = await seed(connection_string, invoices=(invoice_id,), remove=True)
        rec, run = await read()
        assert removed["recommendations_updated"] == 1 and removed["runs_updated"] == 1
        assert rec["metadata"]["expert_evidence"] == [iq_lane]
        assert run["metadata"]["fanout"] == [iq_lane]
        assert rec["content_hash"] == recommendation["content_hash"]

        missing = await seed(connection_string, invoices=("INV-DOES-NOT-EXIST",))
        assert missing["invoices"][0]["skipped"] == "no assurance case"
    finally:
        async with await psycopg.AsyncConnection.connect(connection_string) as connection:
            for table, key in (
                ("agent_runs", run_id),
                ("case_recommendations", rec_id),
                ("assurance_cases", case_id),
                ("invoice_lines", f"{invoice_id}-L1"),
                ("invoices", invoice_id),
            ):
                await connection.execute(f"delete from {table} where id = %s", (key,))
