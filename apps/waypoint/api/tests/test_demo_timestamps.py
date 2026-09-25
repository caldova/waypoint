"""Tests for the demo timestamp refresh (``python -m app.demo_timestamps``)."""

import os
from datetime import UTC, date, datetime, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

import psycopg
import pytest
from psycopg.types.json import Jsonb

from app.common.repository import PostgresWaypointRepository
from app.demo_timestamps import (
    BusinessHours,
    build_plan,
    format_timestamp,
    parse_timestamp,
    refresh,
    shift_payload,
)

PACIFIC = BusinessHours(ZoneInfo("America/Los_Angeles"))
# Original demo activity: 18 runs about 9 minutes apart on one afternoon.
ORIGINAL = [datetime(2026, 7, 7, 22, 27, tzinfo=UTC) + timedelta(minutes=9 * i) for i in range(18)]


def _plan(now: datetime, anchors: list[datetime] = ORIGINAL, **kwargs):  # type: ignore[no-untyped-def]
    return build_plan(
        anchors,
        anchors[-1] + timedelta(minutes=3),
        kwargs.pop("latest_invoice", date(2026, 9, 23)),
        now=now,
        window_days=kwargs.pop("window_days", 7),
        hours=PACIFIC,
    )


def _local(value: datetime) -> datetime:
    return value.astimezone(PACIFIC.timezone)


@pytest.mark.parametrize(
    "now",
    [
        datetime(2026, 9, 25, 21, 0, tzinfo=UTC),  # Friday afternoon Pacific
        datetime(2026, 10, 25, 21, 0, tzinfo=UTC),  # a month later (a Sunday)
        datetime(2027, 3, 3, 3, 0, tzinfo=UTC),  # evening, across DST
    ],
)
def test_runs_land_in_the_past_week_during_business_hours(now: datetime):
    plan = _plan(now)
    new_anchors = [a + d for a, d in zip(plan.anchors, plan.deltas, strict=True)]

    assert all(now - timedelta(days=7, hours=1) <= a < now for a in new_anchors)
    assert all(_local(a).weekday() < 5 for a in new_anchors)
    assert all(
        9 <= _local(a).hour < 17 or _local(a).time().isoformat() == "17:00:00" for a in new_anchors
    )
    # Latest activity lands before now, and the spread covers most of the window.
    assert plan.shift(ORIGINAL[-1] + timedelta(minutes=3)) < now
    assert new_anchors[-1] - new_anchors[0] > timedelta(days=3)


def test_order_and_in_cluster_timing_are_preserved():
    plan = _plan(datetime(2026, 9, 25, 21, 0, tzinfo=UTC))
    deltas = plan.deltas

    assert deltas == sorted(deltas)  # gaps only grow, so order is kept
    run_start, run_end = ORIGINAL[4], ORIGINAL[4] + timedelta(minutes=2, seconds=31)
    assert plan.shift(run_end) - plan.shift(run_start) == run_end - run_start


def test_original_gaps_wider_than_the_window_are_kept():
    spread_out = [datetime(2026, 1, 1, 18, tzinfo=UTC) + timedelta(days=5 * i) for i in range(4)]
    plan = _plan(datetime(2026, 9, 25, 21, 0, tzinfo=UTC), spread_out)
    new_anchors = [a + d for a, d in zip(plan.anchors, plan.deltas, strict=True)]

    gaps = [b - a for a, b in zip(new_anchors, new_anchors[1:], strict=False)]
    assert all(gap >= timedelta(days=5) for gap in gaps)


def test_rerunning_is_stable():
    now = datetime(2026, 9, 25, 21, 0, tzinfo=UTC)
    first = _plan(now)
    moved = [a + d for a, d in zip(first.anchors, first.deltas, strict=True)]
    second = build_plan(
        moved,
        first.shift(ORIGINAL[-1] + timedelta(minutes=3)),
        None,
        now=now + timedelta(minutes=1),
        window_days=7,
        hours=PACIFIC,
    )

    assert all(abs(d) <= timedelta(minutes=2) for d in second.deltas)


def test_invoices_move_to_before_the_first_run():
    plan = _plan(datetime(2026, 9, 25, 21, 0, tzinfo=UTC))
    first_run_day = _local(plan.anchors[0] + plan.deltas[0]).date()

    assert date(2026, 9, 23) + timedelta(days=plan.invoice_day_delta) == first_run_day - timedelta(
        days=1
    )


def test_shift_payload_handles_nested_values_and_keeps_format():
    plan = _plan(datetime(2026, 9, 25, 21, 0, tzinfo=UTC))
    delta = plan.deltas[0]
    payload = {
        "created_at": "2026-07-07T22:27:10.622422Z",
        "snapshot": {"updated_at": "2026-07-07T22:27:11Z", "notes": ["2026-07-07T22:27:12+00:00"]},
        "invoice_id": "INV-2026-08034",
        "effective_date": "2026-01-01",
    }

    shifted, changed = shift_payload(payload, plan, delta)

    assert changed == 3
    assert shifted["invoice_id"] == "INV-2026-08034"
    assert shifted["effective_date"] == "2026-01-01"  # date-only reference data is untouched
    assert shifted["created_at"].endswith("Z") and "." in shifted["created_at"]
    assert "." not in shifted["snapshot"]["updated_at"]
    assert (
        parse_timestamp(shifted["snapshot"]["notes"][0])
        == parse_timestamp("2026-07-07T22:27:12Z") + delta
    )  # type: ignore[operator]


def test_format_round_trips():
    value = "2026-07-07T22:27:10.622422Z"
    parsed = parse_timestamp(value)
    assert parsed is not None
    assert format_timestamp(parsed, value) == value


@pytest.mark.asyncio
async def test_refresh_against_postgres():
    connection_string = os.environ.get("WAYPOINT_TEST_DATABASE_CONNECTION")
    if not connection_string:
        pytest.skip("WAYPOINT_TEST_DATABASE_CONNECTION is required for PostgreSQL coverage")

    repository = PostgresWaypointRepository(connection_string)
    await repository.initialize(load_default_seed=False)
    await repository.close()

    tag = uuid4().hex
    case_id, run_id = f"case-{tag}", f"run-{tag}"
    created = "2026-07-07T22:27:10.586046Z"
    async with await psycopg.AsyncConnection.connect(connection_string) as connection:
        for table in ("agent_runs", "assurance_cases", "decision_audit_events", "audit_events"):
            await connection.execute(f"delete from {table}")
        await connection.execute(
            "insert into assurance_cases (id, payload) values (%s, %s)",
            (case_id, Jsonb({"id": case_id, "created_at": created, "updated_at": created})),
        )
        await connection.execute(
            "insert into agent_runs (id, payload) values (%s, %s)",
            (
                run_id,
                Jsonb(
                    {
                        "id": run_id,
                        "case_id": case_id,
                        "name": "assurance:INV-1",
                        "status": "completed",
                        "created_at": "2026-07-07T22:27:10.622422Z",
                        "updated_at": "2026-07-07T22:29:34.806304Z",
                    }
                ),
            ),
        )

    now = datetime(2026, 10, 25, 21, 0, tzinfo=UTC)
    dry = await refresh(connection_string, now=now, dry_run=True, shift_invoice_dates=False)
    summary = await refresh(connection_string, now=now, shift_invoice_dates=False)

    async with await psycopg.AsyncConnection.connect(connection_string) as connection:
        cursor = await connection.execute(
            "select (payload->>'created_at')::timestamptz, (payload->>'updated_at')::timestamptz,"
            " updated_at_payload from agent_runs where id = %s",
            (run_id,),
        )
        run_created, run_updated, generated = await cursor.fetchone()  # type: ignore[misc]

    assert dry["dry_run"] is True and summary["rows_updated"] == 2
    assert now - timedelta(days=7) < run_created < now
    assert run_updated - run_created == timedelta(minutes=2, seconds=24, microseconds=183882)
    assert generated == format_timestamp(run_updated, "x.y")  # generated column follows payload
