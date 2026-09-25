"""Re-date demo activity so it always looks recent.

The demo database holds real assurance activity from a single afternoon. This command moves that
activity onto a rolling window that ends shortly before *now* (default: the past 7 days), so the
Overview/Invoices/Activity pages show a believable recent history whenever it is run.

How it works
------------
* Each assurance run starts an **activity cluster** (its case, run, recommendation, drafts and
  decision events are written within seconds/minutes of each other). The cluster anchor is the
  earlier of the run's ``created_at`` and its case's ``created_at``.
* Clusters are spread across weekday business hours in the window, oldest first. The newest
  cluster is placed so the very last timestamp lands just before now.
* Every timestamp is shifted by the delta of the latest cluster anchor at or before it. Timing
  inside a cluster is preserved exactly and ordering between clusters never changes. Gaps between
  clusters only grow, never shrink, so re-running is safe and deterministic.
* Invoice ``invoice_date``/``due_date`` move by whole days so every invoice predates its run.
* The HTTP request audit log (``audit_events``) and static reference data are left untouched.

Run it with::

    python -m app.demo_timestamps --window-days 7 [--dry-run]

It uses ``APP_DATABASE_CONNECTION`` and runs in a single transaction.
"""

from __future__ import annotations

import argparse
import asyncio
import bisect
import json
import logging
import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .common.settings import get_settings

logger = logging.getLogger(__name__)

# Tables whose payload timestamps describe assurance activity shown in the UI. Tables missing from
# a database (for example contracts tables before that feature is deployed) are skipped.
ACTIVITY_TABLES: tuple[str, ...] = (
    "agent_runs",
    "assurance_cases",
    "case_recommendations",
    "case_drafts",
    "proposed_actions",
    "case_approvals",
    "authorized_intents",
    "decision_audit_events",
    "finding_validations",
    "contract_artifacts",
    "contract_intake_checkpoints",
    "contract_artifact_extractions",
    "contract_artifact_evidence",
    "contract_artifact_reports",
)

_ISO_DATETIME = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})$")


@dataclass(frozen=True)
class BusinessHours:
    timezone: ZoneInfo
    start: time = time(9, 0)
    end: time = time(17, 0)


def parse_timestamp(value: str) -> datetime | None:
    if not _ISO_DATETIME.match(value):
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def format_timestamp(value: datetime, template: str) -> str:
    """Format like the original string: UTC with ``Z``, keeping fractional-second presence."""

    value = value.astimezone(UTC)
    if "." in template:
        return value.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")


def business_intervals(
    start: datetime, end: datetime, hours: BusinessHours
) -> list[tuple[datetime, datetime]]:
    """Weekday business-hour intervals (UTC) intersected with [start, end]."""

    intervals: list[tuple[datetime, datetime]] = []
    day = start.astimezone(hours.timezone).date() - timedelta(days=1)
    last_day = end.astimezone(hours.timezone).date()
    while day <= last_day:
        if day.weekday() < 5:
            open_at = datetime.combine(day, hours.start, hours.timezone).astimezone(UTC)
            close_at = datetime.combine(day, hours.end, hours.timezone).astimezone(UTC)
            lo, hi = max(open_at, start), min(close_at, end)
            if lo < hi:
                intervals.append((lo, hi))
        day += timedelta(days=1)
    return intervals


def latest_business_time(at_or_before: datetime, hours: BusinessHours) -> datetime:
    """The latest instant <= ``at_or_before`` that falls inside business hours."""

    intervals = business_intervals(at_or_before - timedelta(days=10), at_or_before, hours)
    return intervals[-1][1] if intervals else at_or_before


def spread(count: int, start: datetime, end: datetime, hours: BusinessHours) -> list[datetime]:
    """``count`` instants evenly spaced over business time in [start, end], ending at ``end``."""

    if count <= 0:
        return []
    intervals = business_intervals(start, end, hours) or [(start, end)]
    total = sum((hi - lo for lo, hi in intervals), timedelta())
    if count == 1:
        return [end]
    positions: list[datetime] = []
    for index in range(count):
        offset = total * index / (count - 1)
        for lo, hi in intervals:
            length = hi - lo
            if offset <= length:
                positions.append(lo + offset)
                break
            offset -= length
        else:
            positions.append(intervals[-1][1])
    positions[-1] = end
    return positions


@dataclass(frozen=True)
class ShiftPlan:
    anchors: list[datetime]
    deltas: list[timedelta]
    invoice_day_delta: int

    def delta_for_anchor(self, anchor: datetime) -> timedelta:
        return self.deltas[self.anchors.index(anchor)]

    def shift(self, value: datetime, delta: timedelta | None = None) -> datetime:
        """Shift by a cluster's delta, or by the latest cluster at or before ``value``."""

        if delta is not None:
            return value + delta
        if not self.anchors:
            return value
        index = bisect.bisect_right(self.anchors, value) - 1
        return value + self.deltas[max(index, 0)]


def build_plan(
    cluster_anchors: Iterable[datetime],
    latest_activity: datetime,
    latest_invoice_date: date | None,
    *,
    now: datetime,
    window_days: int,
    hours: BusinessHours,
    margin: timedelta = timedelta(minutes=30),
) -> ShiftPlan:
    anchors = sorted(set(cluster_anchors))
    if not anchors:
        return ShiftPlan([], [], 0)

    # Place the newest cluster so the very last activity lands just before now (in business
    # hours), then spread the rest across the window's business hours.
    end_target = latest_business_time(now - margin, hours)
    last_delta = end_target - latest_activity
    last_new_anchor = anchors[-1] + last_delta
    window_start = now - timedelta(days=window_days)
    targets = spread(len(anchors), min(window_start, last_new_anchor), last_new_anchor, hours)

    # Walk backwards so deltas never decrease: gaps between clusters may grow, never shrink,
    # which keeps every cluster's activity before the next cluster starts.
    new_anchors = [last_new_anchor]
    for index in range(len(anchors) - 2, -1, -1):
        original_gap = anchors[index + 1] - anchors[index]
        new_anchors.append(min(targets[index], new_anchors[-1] - original_gap))
    new_anchors.reverse()
    deltas = [new - old for new, old in zip(new_anchors, anchors, strict=True)]

    invoice_day_delta = 0
    if latest_invoice_date is not None:
        first_run_day = new_anchors[0].astimezone(hours.timezone).date()
        invoice_day_delta = (first_run_day - timedelta(days=1) - latest_invoice_date).days
    return ShiftPlan(anchors, deltas, invoice_day_delta)


def shift_payload(value: Any, plan: ShiftPlan, delta: timedelta | None = None) -> tuple[Any, int]:
    """Shift every ISO datetime string in a JSON value. Returns (new value, strings changed).

    ``delta`` pins the whole value to one cluster (records linked to a case); without it each
    timestamp uses the latest cluster at or before it.
    """

    if isinstance(value, str):
        parsed = parse_timestamp(value)
        if parsed is None:
            return value, 0
        shifted = format_timestamp(plan.shift(parsed, delta), value)
        return shifted, int(shifted != value)
    if isinstance(value, dict):
        changed = 0
        result: dict[str, Any] = {}
        for key, item in value.items():
            result[key], count = shift_payload(item, plan, delta)
            changed += count
        return result, changed
    if isinstance(value, list):
        changed = 0
        items: list[Any] = []
        for item in value:
            shifted_item, count = shift_payload(item, plan, delta)
            items.append(shifted_item)
            changed += count
        return items, changed
    return value, 0


def iter_timestamps(value: Any) -> Iterable[datetime]:
    if isinstance(value, str):
        parsed = parse_timestamp(value)
        if parsed is not None:
            yield parsed
    elif isinstance(value, dict):
        for item in value.values():
            yield from iter_timestamps(item)
    elif isinstance(value, list):
        for item in value:
            yield from iter_timestamps(item)


async def _existing_tables(connection: psycopg.AsyncConnection[Any]) -> set[str]:
    cursor = await connection.execute(
        "select table_name from information_schema.tables where table_schema = 'public'"
    )
    return {row["table_name"] for row in await cursor.fetchall()}


async def refresh(
    connection_string: str,
    *,
    window_days: int = 7,
    timezone: str = "America/Los_Angeles",
    shift_invoice_dates: bool = True,
    dry_run: bool = False,
    now: datetime | None = None,
) -> dict[str, Any]:
    now = (now or datetime.now(UTC)).astimezone(UTC)
    hours = BusinessHours(ZoneInfo(timezone))
    connection = await psycopg.AsyncConnection.connect(connection_string, row_factory=dict_row)
    async with connection, connection.transaction(force_rollback=dry_run):
        tables = [t for t in ACTIVITY_TABLES if t in await _existing_tables(connection)]
        rows: dict[str, list[dict[str, Any]]] = {}
        for table in tables:
            cursor = await connection.execute(
                f"select id, payload, updated_at from {table} for update"
            )
            rows[table] = list(await cursor.fetchall())

        case_created = {
            row["id"]: parse_timestamp(str(row["payload"].get("created_at", "")))
            for row in rows.get("assurance_cases", [])
        }
        anchors: list[datetime] = []
        case_anchor: dict[str, datetime] = {}
        for run in rows.get("agent_runs", []):
            case_id = run["payload"].get("case_id")
            starts = [parse_timestamp(str(run["payload"].get("created_at", "")))]
            starts.append(case_created.get(case_id))
            valid = [start for start in starts if start is not None]
            if not valid:
                continue
            anchor = min(valid)
            anchors.append(anchor)
            if case_id and case_id not in case_anchor:
                case_anchor[case_id] = anchor
        # Cases that were never run still count as activity.
        for case_id, created in case_created.items():
            if created and case_id not in case_anchor:
                anchors.append(created)
                case_anchor[case_id] = created

        all_times = [
            timestamp
            for table_rows in rows.values()
            for row in table_rows
            for timestamp in iter_timestamps(row["payload"])
        ]
        latest_invoice: date | None = None
        if shift_invoice_dates:
            cursor = await connection.execute(
                "select max((payload->>'invoice_date')::date) as latest from invoices"
            )
            latest_invoice = (await cursor.fetchone() or {}).get("latest")

        if not anchors or not all_times:
            return {"clusters": 0, "rows_updated": 0, "dry_run": dry_run}

        plan = build_plan(
            anchors,
            max(all_times),
            latest_invoice,
            now=now,
            window_days=window_days,
            hours=hours,
        )

        updated_rows = 0
        per_table: dict[str, int] = {}
        for table, table_rows in rows.items():
            count = 0
            for row in table_rows:
                case_id = row["id"] if table == "assurance_cases" else row["payload"].get("case_id")
                row_anchor = case_anchor.get(case_id) if isinstance(case_id, str) else None
                delta = plan.delta_for_anchor(row_anchor) if row_anchor else None
                payload, changed = shift_payload(row["payload"], plan, delta)
                if not changed:
                    continue
                await connection.execute(
                    f"update {table} set payload = %s, updated_at = %s where id = %s",
                    (Jsonb(payload), plan.shift(row["updated_at"], delta), row["id"]),
                )
                count += 1
            per_table[table] = count
            updated_rows += count

        invoices_updated = 0
        if shift_invoice_dates and plan.invoice_day_delta:
            days = plan.invoice_day_delta
            # Payload is the source of truth; the plain typed columns are the FabricIQ
            # projection and must match it.
            cursor = await connection.execute(
                """
                update invoices set
                    payload = payload || jsonb_strip_nulls(jsonb_build_object(
                        'invoice_date',
                        to_char((payload->>'invoice_date')::date + %s, 'YYYY-MM-DD'),
                        'due_date',
                        to_char((payload->>'due_date')::date + %s, 'YYYY-MM-DD')
                    )),
                    invoice_date = invoice_date + %s,
                    due_date = due_date + %s,
                    updated_at = now()
                where payload->>'invoice_date' is not null
                """,
                (days, days, days, days),
            )
            invoices_updated = cursor.rowcount

        summary = {
            "dry_run": dry_run,
            "now": now.isoformat(),
            "window_days": window_days,
            "clusters": len(plan.anchors),
            "first_cluster": (plan.anchors[0] + plan.deltas[0]).isoformat(),
            "last_cluster": (plan.anchors[-1] + plan.deltas[-1]).isoformat(),
            "latest_activity_after": plan.shift(max(all_times)).isoformat(),
            "rows_updated": updated_rows,
            "rows_updated_by_table": per_table,
            "invoice_day_shift": plan.invoice_day_delta if shift_invoice_dates else 0,
            "invoices_updated": invoices_updated,
        }
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--window-days", type=int, default=7)
    parser.add_argument("--timezone", default="America/Los_Angeles")
    parser.add_argument("--no-invoice-dates", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if args.window_days < 1:
        parser.error("--window-days must be at least 1")

    logging.basicConfig(level=logging.INFO)
    connection = get_settings().database_connection
    if not connection:
        parser.error("APP_DATABASE_CONNECTION must be set")
    summary = asyncio.run(
        refresh(
            _psycopg_conninfo(connection),
            window_days=args.window_days,
            timezone=args.timezone,
            shift_invoice_dates=not args.no_invoice_dates,
            dry_run=args.dry_run,
        )
    )
    print(json.dumps(summary, indent=2))


def _psycopg_conninfo(connection: str) -> str:
    from .common.repository import _normalize_postgres_connection_string

    return _normalize_postgres_connection_string(connection)


if __name__ == "__main__":
    main()
