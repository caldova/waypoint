#!/usr/bin/env python3
"""Intelligent region + capacity preflight for the one-click Waypoint deploy.

The Waypoint stack co-locates Azure AI Search (the ``contracts-kb`` knowledge
base) with the Foundry account and its ``gpt-5.5`` deployment. When the chosen
Foundry region lacks *Azure AI Search* capacity, the deploy previously fell
back to provisioning Search in the app region, producing a **cross-region**
Search -> model topology in which the knowledge base's agentic retrieval call
into ``gpt-5.5`` fails (``reasoning_effort``/``/v1/responses`` errors) and the
expert silently falls back to ungrounded local evidence.

For a one-click deploy meant to run for tens of thousands of sellers, region
and capacity must be resolved **before** provisioning, not discovered by a
mid-deploy failure. This module scores every candidate Foundry region and
selects the best single region where the whole stack can provision, or fails
fast with an actionable report.

Checks, cheapest-first (so we only run the create/delete Search probe for the
few top-ranked candidates):

  1. Foundry capability allow-list  (static: Hosted Agents + Content
     Understanding GA). Hard gate.
  2. Model availability             (``az cognitiveservices model list``):
     ``gpt-5.5`` and ``text-embedding-3-large`` must be offered. Hard gate.
  3. Model quota headroom           (``az cognitiveservices usage list``):
     enough GlobalStandard ``gpt-5.5`` and Standard embedding quota. Hard gate.
  4. Azure AI Search capacity       (real, non-destructive ARM probe: PUT a
     ``basic`` search service, read provisioningState, DELETE it). This is the
     only reliable capacity signal Azure exposes for Search. Hard gate.
  5. Postgres Flexible Server       (``az postgres flexible-server list-skus``):
     offered in region. Soft gate (warn).

Design notes for testability (mirrors ``admin_preflight.py``):
  - Every check is split into a pure ``build_*_args()`` (the exact argv list,
    never a shell string) and a pure ``evaluate_*()`` (classification given
    already-captured output). Tests exercise both without a real ``az`` binary.
  - The only impure glue is ``default_runner`` (a thin ``subprocess.run``
    wrapper) and the orchestration in ``select_region``.

Usage:
  python3 region_capacity_preflight.py \
    --subscription-id <SUB> \
    --prefer swedencentral \
    --json
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Sequence

# Foundry regions that support both Hosted Agents and Content Understanding GA.
# Kept in sync by hand with the region gate in .github/workflows/deploy.yml.
FOUNDRY_ALLOWLIST: tuple[str, ...] = (
    "australiaeast",
    "eastus",
    "eastus2",
    "japaneast",
    "southcentralus",
    "southeastasia",
    "swedencentral",
    "uksouth",
    "westeurope",
    "westus",
    "westus3",
)

# Default preference order used to break ties among fully-qualified regions.
# Front of the list wins. A caller ``--prefer`` region is always tried first.
DEFAULT_PREFERENCE: tuple[str, ...] = (
    "swedencentral",
    "westeurope",
    "eastus",
    "eastus2",
    "westus3",
    "uksouth",
    "southcentralus",
    "westus",
    "japaneast",
    "australiaeast",
    "southeastasia",
)

STATUS_PASS = "pass"
STATUS_WARN = "warn"
STATUS_FAIL = "fail"

SEARCH_MGMT_API_VERSION = "2023-11-01"


@dataclass(frozen=True)
class ModelRequirement:
    """A required model deployment and the quota it needs."""

    model_name: str
    sku: str  # e.g. GlobalStandard / Standard
    capacity: int  # tokens-per-minute in thousands, matching az usage units


@dataclass(frozen=True)
class Requirements:
    gpt: ModelRequirement = ModelRequirement("gpt-5.5", "GlobalStandard", 200)
    embedding: ModelRequirement = ModelRequirement(
        "text-embedding-3-large", "Standard", 50
    )
    search_sku: str = "basic"

    @property
    def models(self) -> tuple[ModelRequirement, ModelRequirement]:
        return (self.gpt, self.embedding)


@dataclass
class RegionEvaluation:
    region: str
    checks: dict[str, dict[str, Any]] = field(default_factory=dict)
    qualified: bool = False
    score: float = 0.0
    reason: str = ""

    def record(self, name: str, status: str, detail: str, **extra: Any) -> None:
        self.checks[name] = {"status": status, "detail": detail, **extra}

    def worst_status(self) -> str:
        rank = {STATUS_PASS: 0, STATUS_WARN: 1, STATUS_FAIL: 2}
        worst = STATUS_PASS
        for check in self.checks.values():
            if rank[check["status"]] > rank[worst]:
                worst = check["status"]
        return worst


# --------------------------------------------------------------------------- #
# 1. Foundry capability allow-list (static, no I/O)
# --------------------------------------------------------------------------- #
def evaluate_foundry_allowlist(region: str) -> tuple[str, str]:
    if region in FOUNDRY_ALLOWLIST:
        return STATUS_PASS, "Region supports Hosted Agents + Content Understanding GA."
    return (
        STATUS_FAIL,
        "Region is not on the Foundry Hosted-Agents/Content-Understanding allow-list.",
    )


# --------------------------------------------------------------------------- #
# 2. Model availability
# --------------------------------------------------------------------------- #
def build_model_list_args(region: str) -> list[str]:
    return [
        "az",
        "cognitiveservices",
        "model",
        "list",
        "-l",
        region,
        "-o",
        "json",
    ]


def evaluate_model_availability(
    models_json: str, required: Sequence[ModelRequirement]
) -> tuple[str, str]:
    try:
        models = json.loads(models_json) if models_json else []
    except json.JSONDecodeError:
        return STATUS_FAIL, "Could not parse model catalog response."
    available = {
        (m.get("model") or {}).get("name")
        for m in models
        if isinstance(m, dict)
    }
    missing = [r.model_name for r in required if r.model_name not in available]
    if missing:
        return STATUS_FAIL, f"Missing model(s): {', '.join(missing)}."
    return STATUS_PASS, "All required models are offered in region."


# --------------------------------------------------------------------------- #
# 3. Model quota headroom
# --------------------------------------------------------------------------- #
def build_usage_list_args(region: str) -> list[str]:
    return [
        "az",
        "cognitiveservices",
        "usage",
        "list",
        "-l",
        region,
        "-o",
        "json",
    ]


def _usage_available(usage: list[dict[str, Any]], metric: str) -> float | None:
    for entry in usage:
        name = (entry.get("name") or {}).get("value")
        if name == metric:
            limit = float(entry.get("limit") or 0)
            current = float(entry.get("currentValue") or 0)
            return limit - current
    return None


def evaluate_model_quota(
    usage_json: str, required: Sequence[ModelRequirement]
) -> tuple[str, str, float]:
    """Return (status, detail, min_headroom_ratio).

    ``min_headroom_ratio`` is the tightest available/required ratio across the
    required models and is used to rank regions (more headroom ranks higher).
    """

    try:
        usage = json.loads(usage_json) if usage_json else []
    except json.JSONDecodeError:
        return STATUS_FAIL, "Could not parse quota usage response.", 0.0
    details: list[str] = []
    min_ratio = float("inf")
    for req in required:
        metric = f"OpenAI.{req.sku}.{req.model_name}"
        avail = _usage_available(usage, metric)
        if avail is None:
            return STATUS_FAIL, f"No quota metric found for {metric}.", 0.0
        details.append(f"{metric}: {avail:.0f} free (need {req.capacity})")
        if avail < req.capacity:
            return (
                STATUS_FAIL,
                f"Insufficient quota for {metric}: {avail:.0f} free < {req.capacity} required.",
                0.0,
            )
        min_ratio = min(min_ratio, avail / max(req.capacity, 1))
    return STATUS_PASS, "; ".join(details), (0.0 if min_ratio == float("inf") else min_ratio)


# --------------------------------------------------------------------------- #
# 4. Azure AI Search capacity probe (real, non-destructive)
# --------------------------------------------------------------------------- #
def _search_resource_id(subscription: str, rg: str, name: str) -> str:
    return (
        f"/subscriptions/{subscription}/resourceGroups/{rg}"
        f"/providers/Microsoft.Search/searchServices/{name}"
    )


def build_search_probe_put_args(
    subscription: str, rg: str, name: str, region: str, sku: str
) -> list[str]:
    body = {
        "location": region,
        "sku": {"name": sku},
        "properties": {"replicaCount": 1, "partitionCount": 1},
    }
    resource_id = _search_resource_id(subscription, rg, name)
    return [
        "az",
        "rest",
        "--method",
        "put",
        "--url",
        f"https://management.azure.com{resource_id}?api-version={SEARCH_MGMT_API_VERSION}",
        "--headers",
        "Content-Type=application/json",
        "--body",
        json.dumps(body),
    ]


def build_search_probe_delete_args(
    subscription: str, rg: str, name: str
) -> list[str]:
    resource_id = _search_resource_id(subscription, rg, name)
    return [
        "az",
        "rest",
        "--method",
        "delete",
        "--url",
        f"https://management.azure.com{resource_id}?api-version={SEARCH_MGMT_API_VERSION}",
    ]


def evaluate_search_probe(returncode: int, stdout: str, stderr: str) -> tuple[str, str]:
    combined = f"{stdout}\n{stderr}"
    if "InsufficientResourcesAvailable" in combined:
        return STATUS_FAIL, "Azure AI Search has no capacity in this region."
    if returncode == 0:
        state = ""
        try:
            data = json.loads(stdout) if stdout.strip() else {}
            state = (data.get("properties") or {}).get("provisioningState", "")
        except json.JSONDecodeError:
            state = ""
        return STATUS_PASS, f"Azure AI Search capacity available (provisioningState={state or 'accepted'})."
    # Any other failure is inconclusive; treat as a warning so it does not
    # silently disqualify a region that may only have hit a transient error.
    snippet = combined.strip().splitlines()[-1] if combined.strip() else "unknown error"
    return STATUS_WARN, f"Search probe inconclusive: {snippet[:180]}"


# --------------------------------------------------------------------------- #
# 5. Postgres Flexible Server availability (soft)
# --------------------------------------------------------------------------- #
def build_postgres_skus_args(region: str) -> list[str]:
    return [
        "az",
        "postgres",
        "flexible-server",
        "list-skus",
        "-l",
        region,
        "-o",
        "json",
    ]


def evaluate_postgres(skus_json: str) -> tuple[str, str]:
    try:
        skus = json.loads(skus_json) if skus_json else []
    except json.JSONDecodeError:
        return STATUS_WARN, "Could not parse Postgres SKU response."
    if skus:
        return STATUS_PASS, "Azure Database for PostgreSQL Flexible Server is offered."
    return STATUS_WARN, "No Postgres Flexible Server SKUs returned for region."


# --------------------------------------------------------------------------- #
# Runner
# --------------------------------------------------------------------------- #
def default_runner(args: Sequence[str]) -> subprocess.CompletedProcess:
    return subprocess.run(  # noqa: S603 - args is always a list, never a shell string
        list(args),
        capture_output=True,
        text=True,
        check=False,
    )


Runner = Callable[[Sequence[str]], subprocess.CompletedProcess]


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #
def _preference_key(prefer: str | None) -> Callable[[str], tuple[int, int]]:
    order = list(DEFAULT_PREFERENCE)

    def key(region: str) -> tuple[int, int]:
        preferred = 0 if prefer and region == prefer else 1
        try:
            rank = order.index(region)
        except ValueError:
            rank = len(order)
        return (preferred, rank)

    return key


def evaluate_region_cheap(
    region: str, requirements: Requirements, runner: Runner
) -> RegionEvaluation:
    """Run the read-only gates (allow-list, model availability, quota)."""

    ev = RegionEvaluation(region=region)

    status, detail = evaluate_foundry_allowlist(region)
    ev.record("foundry_allowlist", status, detail)
    if status == STATUS_FAIL:
        ev.reason = detail
        return ev

    proc = runner(build_model_list_args(region))
    status, detail = evaluate_model_availability(proc.stdout, requirements.models)
    ev.record("model_availability", status, detail)
    if status == STATUS_FAIL:
        ev.reason = detail
        return ev

    proc = runner(build_usage_list_args(region))
    status, detail, headroom = evaluate_model_quota(proc.stdout, requirements.models)
    ev.record("model_quota", status, detail, headroom_ratio=headroom)
    if status == STATUS_FAIL:
        ev.reason = detail
        return ev

    ev.score = headroom
    return ev


def probe_region_capacity(
    ev: RegionEvaluation,
    requirements: Requirements,
    subscription: str,
    probe_rg: str,
    runner: Runner,
    check_postgres: bool = True,
) -> RegionEvaluation:
    """Run the create/delete Search probe (+ soft Postgres) for one region."""

    region = ev.region
    name = f"wpcapz{int(time.time())}{region}"[:60].lower()
    put = runner(
        build_search_probe_put_args(
            subscription, probe_rg, name, region, requirements.search_sku
        )
    )
    status, detail = evaluate_search_probe(put.returncode, put.stdout, put.stderr)
    ev.record("search_capacity", status, detail)
    # Best-effort teardown whenever the PUT may have created something.
    if status == STATUS_PASS:
        runner(build_search_probe_delete_args(subscription, probe_rg, name))
    if status == STATUS_FAIL:
        ev.reason = detail
        return ev

    if check_postgres:
        pg = runner(build_postgres_skus_args(region))
        pg_status, pg_detail = evaluate_postgres(pg.stdout)
        ev.record("postgres", pg_status, pg_detail)

    ev.qualified = ev.worst_status() != STATUS_FAIL
    if ev.qualified:
        ev.reason = "All hard capacity gates passed."
    return ev


def _ensure_probe_rg(subscription: str, probe_rg: str, location: str, runner: Runner) -> None:
    runner(
        [
            "az",
            "group",
            "create",
            "-n",
            probe_rg,
            "-l",
            location,
            "--subscription",
            subscription,
            "-o",
            "none",
        ]
    )


def _delete_probe_rg(subscription: str, probe_rg: str, runner: Runner) -> None:
    runner(
        [
            "az",
            "group",
            "delete",
            "-n",
            probe_rg,
            "--subscription",
            subscription,
            "--yes",
            "--no-wait",
            "-o",
            "none",
        ]
    )


def select_region(
    subscription: str,
    *,
    candidates: Sequence[str] | None = None,
    prefer: str | None = None,
    requirements: Requirements | None = None,
    runner: Runner | None = None,
    probe_search: bool = True,
    probe_rg: str | None = None,
) -> dict[str, Any]:
    """Select the best region for a co-located Waypoint deploy.

    Returns a report dict with ``selected`` (region or None) and ``evaluations``
    (per-region detail). Only the read-only gates run for every candidate; the
    create/delete Search probe runs lazily in preference order until a region
    passes, minimizing probes.
    """

    requirements = requirements or Requirements()
    runner = runner or default_runner
    candidates = list(candidates or FOUNDRY_ALLOWLIST)
    probe_rg = probe_rg or f"rg-waypoint-capacity-probe-{int(time.time())}"

    # Cheap gates for everyone.
    cheap = [evaluate_region_cheap(r, requirements, runner) for r in candidates]
    passing = [ev for ev in cheap if ev.checks.get("model_quota", {}).get("status") == STATUS_PASS
               and ev.checks.get("model_availability", {}).get("status") == STATUS_PASS
               and ev.checks.get("foundry_allowlist", {}).get("status") == STATUS_PASS]

    # Rank: preference first, then model-quota headroom (desc).
    pref_key = _preference_key(prefer)
    passing.sort(key=lambda ev: (pref_key(ev.region), -ev.score))

    selected: str | None = None
    evaluated_by_region = {ev.region: ev for ev in cheap}

    if not probe_search:
        # Dry-run: pick the top-ranked cheap-qualified region without probing.
        if passing:
            selected = passing[0].region
            passing[0].qualified = True
        return _report(selected, list(evaluated_by_region.values()), probe_rg, probed=False)

    probe_rg_created = False
    try:
        for ev in passing:
            if not probe_rg_created:
                _ensure_probe_rg(subscription, probe_rg, ev.region, runner)
                probe_rg_created = True
            probe_region_capacity(ev, requirements, subscription, probe_rg, runner)
            if ev.qualified:
                selected = ev.region
                break
    finally:
        if probe_rg_created:
            _delete_probe_rg(subscription, probe_rg, runner)

    return _report(selected, list(evaluated_by_region.values()), probe_rg, probed=True)


def _report(
    selected: str | None,
    evaluations: list[RegionEvaluation],
    probe_rg: str,
    *,
    probed: bool,
) -> dict[str, Any]:
    return {
        "selected": selected,
        "probed": probed,
        "probe_resource_group": probe_rg,
        "evaluations": [
            {
                "region": ev.region,
                "qualified": ev.qualified,
                "score": ev.score,
                "reason": ev.reason,
                "checks": ev.checks,
            }
            for ev in evaluations
        ],
    }


def _print_human(report: dict[str, Any]) -> None:
    sel = report.get("selected")
    print("Region capacity preflight", file=sys.stderr)
    for ev in report["evaluations"]:
        marks = " ".join(
            f"{k}={v['status']}" for k, v in ev["checks"].items()
        )
        flag = "SELECTED" if ev["region"] == sel else ("ok" if ev["qualified"] else "--")
        print(f"  [{flag:>8}] {ev['region']:<16} {marks}", file=sys.stderr)
    if sel:
        print(f"\nSelected region: {sel}", file=sys.stderr)
    else:
        print("\nNo region satisfied all capacity requirements.", file=sys.stderr)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--subscription-id", required=True)
    parser.add_argument(
        "--prefer",
        default=None,
        help="Region to try first when it fully qualifies (e.g. swedencentral).",
    )
    parser.add_argument(
        "--candidates",
        default=None,
        help="Comma-separated candidate regions (default: full Foundry allow-list).",
    )
    parser.add_argument("--gpt-capacity", type=int, default=200)
    parser.add_argument("--embedding-capacity", type=int, default=50)
    parser.add_argument(
        "--no-search-probe",
        action="store_true",
        help="Skip the create/delete Search capacity probe (read-only dry run).",
    )
    parser.add_argument("--probe-resource-group", default=None)
    parser.add_argument("--json", action="store_true", help="Emit the full JSON report to stdout.")
    parser.add_argument(
        "--github-output",
        action="store_true",
        help="Append selected_region=<region> to $GITHUB_OUTPUT.",
    )
    args = parser.parse_args(argv)

    requirements = Requirements(
        gpt=ModelRequirement("gpt-5.5", "GlobalStandard", args.gpt_capacity),
        embedding=ModelRequirement(
            "text-embedding-3-large", "Standard", args.embedding_capacity
        ),
    )
    candidates = (
        [c.strip() for c in args.candidates.split(",") if c.strip()]
        if args.candidates
        else None
    )

    report = select_region(
        args.subscription_id,
        candidates=candidates,
        prefer=args.prefer,
        requirements=requirements,
        probe_search=not args.no_search_probe,
        probe_rg=args.probe_resource_group,
    )

    _print_human(report)
    if args.json:
        print(json.dumps(report, indent=2))

    if args.github_output:
        import os

        out = os.environ.get("GITHUB_OUTPUT")
        if out and report.get("selected"):
            with open(out, "a", encoding="utf-8") as handle:
                handle.write(f"selected_region={report['selected']}\n")

    return 0 if report.get("selected") else 2


if __name__ == "__main__":
    raise SystemExit(main())
