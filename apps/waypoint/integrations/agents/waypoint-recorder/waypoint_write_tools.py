"""Waypoint write FunctionTools for the waypoint-recorder agent.

These tools are the pipeline's single write boundary. The waypoint-recorder calls
`waypoint_record_assurance` with its fused decision *and* the four experts' evidence
fan-out. The tool then:

1. Re-grounds against the seeded Waypoint corpus (findings + evidence for the invoice)
   so the persisted decision trail carries real money-at-risk, real evidence-reference
   IDs, and a fan-out trail even when the model's narrated numbers drift.
2. Opens a run anchor (status/summary + the per-expert fan-out in metadata), opens an
   assurance case, stages a recommendation (with the real evidence IDs and the
   structured expert evidence in metadata), and optionally a draft.
3. Returns the Waypoint correlation IDs so they can be carried into traces.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from typing import Any

from agent_framework import FunctionTool, tool

from waypoint_read_client import WaypointReadClient
from waypoint_write_client import (
    DECISIONS,
    WaypointWriteClient,
    assurance_case_key,
    assurance_run_key,
    is_waypoint_configured,
)
from telemetry import rft_reference_attributes, operation_id, set_span_attribute, trace_span

logger = logging.getLogger("waypoint_recorder.waypoint_write_tools")

_EXPERT_AGENT_BY_PLANE = {
    "workiq": "collaboration-evidence-expert",
    "webiq": "market-evidence-expert",
    "foundryiq": "contract-policy-expert",
    "fabriciq": "operations-data-expert",
}

_RESULT_SHAPE = """{
  "invoice_id": "INV-2026-08034",
  "decision": "approve|recover|escalate|review",
  "reasoning": "Why this decision, citing the fused evidence.",
  "confidence": 0.0,
  "money_at_risk": 0.0,
  "finding_id": "optional finding id",
  "title": "optional case title",
  "summary": "short case summary",
  "classification": "standard|confidential|ip_sensitive|restricted",
  "evidence_ids": ["optional evidence ref ids"],
  "proposed_next_actions": ["optional action labels"],
  "fanout": [
    {"agent": "operations-data-expert", "plane": "fabriciq",
     "summary": "1-2 sentence plane summary",
     "evidence": [
       {"claim": "what this plane found", "supports": "approve|recover|escalate|review|unknown",
        "source_ref": "stable locator", "classification": "standard", "confidence": 0.0}
     ]}
  ],
  "draft": {
    "draft_type": "supplier_dispute|escalation_packet|approval_summary",
    "title": "draft title",
    "body": "draft body"
  }
}"""


def waypoint_record_assurance(result_json: str) -> str:
    """Write one governed assurance result to Waypoint (run + case + recommendation + draft).

    The tool re-grounds money-at-risk and evidence IDs against the Waypoint corpus, so
    pass the experts' fan-out through under `fanout` and it will be persisted with the
    decision trail.

    Args:
        result_json: A JSON object describing the final decision for one invoice. Shape:
%s
    """
    parsed_for_trace = _try_parse(result_json)
    with trace_span(
        "waypoint_recorder.record_assurance",
        {
            **rft_reference_attributes(
                agent_name="waypoint-recorder",
                task_family="invoice_assurance_decision",
                messages=[{"role": "user", "content": result_json}],
                expected_tools=["waypoint_record_assurance"],
                expected_output={
                    "ok": True,
                    "decision": parsed_for_trace.get("decision"),
                    "invoice_id": parsed_for_trace.get("invoice_id"),
                },
                grader_reference={
                    "expected_decisions": sorted(("approve", "recover", "escalate", "review")),
                    "expected_side_effect": "waypoint_write_once",
                },
            ),
            "gen_ai.agent.name": "waypoint-recorder",
            "gen_ai.operation.name": "execute_tool",
            "gen_ai.tool.name": "waypoint_record_assurance",
            "forge.invoice.id": parsed_for_trace.get("invoice_id"),
            "forge.waypoint_recorder.decision": parsed_for_trace.get("decision"),
        },
    ) as span:
        result_text = _waypoint_record_assurance_inner(result_json)
        result_payload = _try_parse(result_text)
        set_span_attribute(span, "forge.waypoint_recorder.write.ok", result_payload.get("ok"))
        set_span_attribute(span, "forge.waypoint_recorder.write.decision", result_payload.get("decision"))
        correlation = result_payload.get("correlation") if isinstance(result_payload.get("correlation"), dict) else {}
        set_span_attribute(span, "waypoint.run_id", correlation.get("waypoint_run_id"))
        set_span_attribute(span, "waypoint.case_id", correlation.get("waypoint_case_id"))
        set_span_attribute(span, "waypoint.recommendation_id", correlation.get("waypoint_recommendation_id"))
        return result_text


def _waypoint_record_assurance_inner(result_json: str) -> str:
    if not is_waypoint_configured():
        return _json(
            {
                "ok": False,
                "error": "Waypoint is not configured (WAYPOINT_API_BASE_URL unset).",
            }
        )
    try:
        result = _parse(result_json)
        # Capture the orchestrator-supplied operation id BEFORE normalization: the
        # write-plan-preview contract rebuilds the dict and would drop a top-level
        # operation_id. This id ties the recorder's final write back to the run/case
        # the orchestrator opened early (same idempotency keys).
        bundle_operation_id = str(result.get("operation_id") or "").strip()
        result = _normalize_result_contract(result)
    except ValueError as exc:
        return _json({"ok": False, "error": f"invalid result_json: {exc}"})

    invoice_ref = _recover_invoice_ref(result)
    if not invoice_ref:
        return _json(
            {
                "ok": False,
                "error": (
                    "result_json.invoice_id is required; no invoice reference was found "
                    "in invoice_id, invoice_number, finding_id, evidence_ids, or fanout."
                ),
            }
        )

    model_decision = str(result.get("decision") or "").strip().lower() or "review"
    reasoning = str(result.get("reasoning") or "").strip()

    # ── ground against the seeded corpus (best-effort) ───────────────────────
    grounding = _ground(invoice_ref)
    invoice_id = grounding["invoice_id"] or invoice_ref
    invoice_number = grounding["invoice_number"] or invoice_ref
    grounded_money = grounding["money_at_risk"]
    grounded_evidence_ids = grounding["evidence_ids"]
    grounded_finding_id = grounding["finding_id"]

    # ── deterministic policy check owns the decision when corpus truth exists ─
    # Services own the math + persistence (see docs/AGENT_PIPELINE.md and the
    # assurance-orchestrator workflow-implementation contract): the recorder maps
    # the grounded finding to the Waypoint decision so a high-severity / escalate
    # finding can never be persisted as recover/approve just because the model
    # narrated it that way.
    decision, decision_governance = _govern_decision(grounding["findings"], model_decision)
    if decision_governance.get("overridden"):
        logger.info(
            "policy check overrode model decision %s -> %s for %s",
            decision_governance.get("model_decision"),
            decision,
            invoice_ref,
        )

    money_at_risk = grounded_money if grounded_money > 0 else _float(result.get("money_at_risk"))
    evidence_ids = grounded_evidence_ids or _str_list(result.get("evidence_ids"))
    finding_id = _opt(result.get("finding_id")) or grounded_finding_id

    fanout = _normalize_fanout(result.get("fanout"), grounding)
    # "Consulted" must mean "contributed grounded evidence". A lane that returned only a
    # summary and zero citations (e.g. the market-evidence/web lane when the public web has
    # nothing on this supplier, or the stubbed operations lane) grounded on nothing, so it
    # is excluded from experts_consulted / the "N experts consulted" summary. The full
    # fanout audit trail is preserved above.
    experts = [
        str(lane.get("agent") or lane.get("plane") or "")
        for lane in fanout
        if lane and _lane_is_expert(lane) and _lane_is_grounded(lane)
    ]
    experts = [name for name in experts if name]

    confidence = _float(result.get("confidence"))
    classification = str(result.get("classification") or "standard")
    summary = str(result.get("summary") or "").strip()

    run_summary = _run_summary(
        decision=decision,
        invoice_number=invoice_number,
        money_at_risk=money_at_risk,
        finding_count=grounding["finding_count"],
        expert_count=len(experts),
    )

    client = WaypointWriteClient()
    correlation: dict[str, Any] = {
        "waypoint_run_id": None,
        "waypoint_case_id": None,
        "waypoint_recommendation_id": None,
        "waypoint_draft_id": None,
        "waypoint_invoice_id": invoice_id,
        "invoice_number": invoice_number,
        "money_at_risk": money_at_risk,
        "evidence_count": len(evidence_ids),
        "experts_consulted": experts,
    }

    run_metadata = {
        "invoice_id": invoice_id,
        "invoice_number": invoice_number,
        "decision": decision,
        "confidence": confidence,
        "money_at_risk": money_at_risk,
        "finding_count": grounding["finding_count"],
        "experts_consulted": experts,
        "fanout": fanout,
    }
    # Stable per-execution keys so the orchestrator's early-open and this final write
    # resolve to the SAME run + case (no duplicate active runs, no duplicate cases).
    # Key on the RAW invoice_ref (the id the orchestrator fanned out with), NOT the
    # grounded invoice_number, so both agents derive identical keys. operation_id comes
    # from the handoff bundle when present; otherwise fall back to this call's trace id
    # or a per-call uuid (still dedupes retries within this call).
    op_id = bundle_operation_id or operation_id() or uuid.uuid4().hex
    case_key = assurance_case_key(invoice_ref, op_id)
    run_key = assurance_run_key(invoice_ref, op_id)

    run_id: str | None = None
    try:
        case = client.create_case(
            invoice_id,
            finding_id=finding_id,
            title=_opt(result.get("title")),
            summary=summary,
            classification=classification,
            idempotency_key=case_key,
            metadata={"invoice_number": invoice_number},
        )
        case_id = _id(case)
        correlation["waypoint_case_id"] = case_id

        # Open the run EARLY as "running" so it surfaces on Waypoint's Activity page
        # while the recommendation + draft are staged, then PATCH it to "completed"
        # (or "failed") below. case_id must be set here because it is not PATCHable.
        # When the orchestrator already opened this run at fan-out start, the shared
        # run_key returns that SAME run (now flipped running->…), so no duplicate.
        run = client.open_run(
            name=f"assurance:{invoice_number}",
            case_id=case_id,
            status="running",
            summary=run_summary,
            idempotency_key=run_key,
            metadata=run_metadata,
        )
        run_id = _id(run)
        correlation["waypoint_run_id"] = run_id

        recommendation = client.create_recommendation(
            case_id,
            decision=decision,
            reasoning=reasoning,
            confidence=confidence,
            money_at_risk=money_at_risk,
            evidence_ids=evidence_ids,
            proposed_next_actions=_str_list(result.get("proposed_next_actions")),
            metadata={
                "waypoint_run_id": correlation["waypoint_run_id"],
                "expert_evidence": fanout,
                "invoice_number": invoice_number,
                "decision_governance": decision_governance,
            },
        )
        correlation["waypoint_recommendation_id"] = _id(recommendation)

        draft = result.get("draft")
        if isinstance(draft, dict) and draft.get("body"):
            created_draft = client.create_draft(
                case_id,
                draft_type=str(draft.get("draft_type") or "supplier_dispute"),
                title=str(draft.get("title") or f"Draft for {invoice_number}"),
                body_text=str(draft.get("body")),
                source_recommendation_id=correlation["waypoint_recommendation_id"],
                classification=classification,
                metadata={"waypoint_run_id": correlation["waypoint_run_id"]},
            )
            correlation["waypoint_draft_id"] = _id(created_draft)

        # Advance the run to its terminal state now that the write is complete.
        client.update_run(
            run_id,
            status="completed",
            summary=run_summary,
            metadata={
                **run_metadata,
                "waypoint_recommendation_id": correlation["waypoint_recommendation_id"],
                "waypoint_draft_id": correlation["waypoint_draft_id"],
            },
        )
    except Exception as exc:  # surface a structured error back to the model
        logger.exception("waypoint_record_assurance failed")
        # Don't leave a run stuck in "running" forever if we opened one before failing.
        if run_id is not None:
            try:
                client.update_run(
                    run_id,
                    status="failed",
                    summary=run_summary,
                    metadata={**run_metadata, "error": str(exc)},
                )
            except Exception:
                logger.warning("failed to PATCH run %s to failed", run_id, exc_info=True)
        return _json({"ok": False, "error": str(exc), "correlation": correlation})

    return _json({"ok": True, "decision": decision, "correlation": correlation})


waypoint_record_assurance.__doc__ = waypoint_record_assurance.__doc__ % _RESULT_SHAPE


_OPEN_STATUSES = {"running", "pending"}


def waypoint_open_run(invoice_id: str, operation_id: str = "", status: str = "running") -> str:
    """Open (or re-anchor) the Waypoint run + case for one invoice at fan-out START.

    This is the EARLY-open half of the run lifecycle: it makes the invoice appear on
    Waypoint's Activity page as `running` (or `pending` when queued) while the multi-
    expert fan-out is still in flight. The matching final write
    (`waypoint_record_assurance`) reuses the SAME idempotency keys and PATCHes this run
    to `completed`/`failed`, so opening early never creates a duplicate run or case.

    Call this AT MOST ONCE per invoice, and do NOT also stage a recommendation or draft
    here — that is `waypoint_record_assurance`'s job.

    Args:
        invoice_id: The invoice reference for this execution (e.g. "INV-2026-08034").
        operation_id: The shared per-execution correlation id supplied by the
            orchestrator. Pass it through verbatim so early-open and final-write agree
            on the idempotency keys. When empty, a stable id is derived locally.
        status: "running" (executing now) or "pending" (queued). Defaults to "running".
    """
    return _waypoint_open_run_inner(invoice_id, operation_id, status)


def _waypoint_open_run_inner(invoice_id: str, operation_id_arg: str, status: str) -> str:
    if not is_waypoint_configured():
        return _json({"ok": False, "error": "Waypoint is not configured (WAYPOINT_API_BASE_URL unset)."})

    invoice_ref = str(invoice_id or "").strip()
    if not invoice_ref:
        return _json({"ok": False, "error": "invoice_id is required to open a run."})

    normalized_status = str(status or "running").strip().lower()
    if normalized_status not in _OPEN_STATUSES:
        normalized_status = "running"

    op_id = str(operation_id_arg or "").strip() or operation_id() or uuid.uuid4().hex

    with trace_span(
        "waypoint_recorder.open_run",
        {
            "gen_ai.agent.name": "waypoint-recorder",
            "gen_ai.operation.name": "execute_tool",
            "gen_ai.tool.name": "waypoint_open_run",
            "forge.invoice.id": invoice_ref,
            "forge.waypoint.status": normalized_status,
        },
    ) as span:
        try:
            opened = WaypointWriteClient().open_assurance_run(
                invoice_ref,
                operation_id=op_id,
                status=normalized_status,
                run_summary=f"assurance:{invoice_ref} ({normalized_status})",
                run_metadata={"invoice_id": invoice_ref, "status": normalized_status},
                case_metadata={"invoice_id": invoice_ref},
            )
        except Exception as exc:
            logger.exception("waypoint_open_run failed for %s", invoice_ref)
            return _json({"ok": False, "error": str(exc), "invoice_id": invoice_ref})
        set_span_attribute(span, "waypoint.run_id", opened.get("run_id"))
        set_span_attribute(span, "waypoint.case_id", opened.get("case_id"))
        return _json(
            {
                "ok": True,
                "status": normalized_status,
                "operation_id": op_id,
                "correlation": {
                    "waypoint_run_id": opened.get("run_id"),
                    "waypoint_case_id": opened.get("case_id"),
                },
            }
        )


def waypoint_fail_run(invoice_id: str, operation_id: str = "", reason: str = "") -> str:
    """Mark an invoice's assurance run as terminally `failed` (never leave it `running`).

    This is the deterministic finalize-failure half of the run lifecycle. When the
    orchestrator opened a run early as `running` but the assurance turn could not produce
    a decision to hand off (an expert-fan-out timeout, a crash, a budget cut-off), the run
    would otherwise orphan at `running`. This flips that SAME run — resolved via the shared
    `assurance:{invoice_id}:{operation_id}` idempotency key — to `failed` with a reason,
    so the Activity page shows a terminal state instead of a stuck anchor.

    Idempotent: re-opening the shared run key returns the existing run and PATCHes it to
    `failed`. Safe to call even if no run was opened yet (it opens then fails one).

    Args:
        invoice_id: The invoice reference for this execution (e.g. "INV-2026-08034").
        operation_id: The shared per-execution correlation id the orchestrator used for
            the early-open. Pass it through verbatim so this resolves the SAME run.
        reason: Short human-readable failure reason recorded on the run.
    """
    return _waypoint_fail_run_inner(invoice_id, operation_id, reason)


def _waypoint_fail_run_inner(invoice_id: str, operation_id_arg: str, reason: str) -> str:
    if not is_waypoint_configured():
        return _json({"ok": False, "error": "Waypoint is not configured (WAYPOINT_API_BASE_URL unset)."})

    invoice_ref = str(invoice_id or "").strip()
    if not invoice_ref:
        return _json({"ok": False, "error": "invoice_id is required to fail a run."})

    op_id = str(operation_id_arg or "").strip() or operation_id() or uuid.uuid4().hex
    reason_text = str(reason or "").strip() or "assurance run failed before finalize"

    with trace_span(
        "waypoint_recorder.fail_run",
        {
            "gen_ai.agent.name": "waypoint-recorder",
            "gen_ai.operation.name": "execute_tool",
            "gen_ai.tool.name": "waypoint_fail_run",
            "forge.invoice.id": invoice_ref,
            "forge.waypoint.status": "failed",
        },
    ) as span:
        try:
            failed = WaypointWriteClient().open_assurance_run(
                invoice_ref,
                operation_id=op_id,
                status="failed",
                run_summary=f"assurance:{invoice_ref} (failed)",
                run_metadata={"invoice_id": invoice_ref, "status": "failed", "error": reason_text},
                case_metadata={"invoice_id": invoice_ref},
            )
        except Exception as exc:
            logger.exception("waypoint_fail_run failed for %s", invoice_ref)
            return _json({"ok": False, "error": str(exc), "invoice_id": invoice_ref})
        set_span_attribute(span, "waypoint.run_id", failed.get("run_id"))
        set_span_attribute(span, "waypoint.case_id", failed.get("case_id"))
        return _json(
            {
                "ok": True,
                "status": "failed",
                "operation_id": op_id,
                "reason": reason_text,
                "correlation": {
                    "waypoint_run_id": failed.get("run_id"),
                    "waypoint_case_id": failed.get("case_id"),
                },
            }
        )


def waypoint_enroll_batch(invoices_json: str) -> str:
    """Open every invoice in a batch as `pending` up front, before fan-out begins.

    Use this ONCE at the start of a multi-invoice run so the whole batch shows as queued
    on Waypoint's Activity page; each invoice then flips to `running` when its fan-out
    starts and to `completed`/`failed` when its final write lands. Reuses the same
    idempotency keys as `waypoint_open_run`/`waypoint_record_assurance`, so pre-enrolling
    never creates duplicates.

    Args:
        invoices_json: A JSON array of objects, one per invoice, each with an
            `invoice_id` and (optionally) the shared `operation_id`. Example:
            `[{"invoice_id": "INV-1", "operation_id": "abc"}, {"invoice_id": "INV-2"}]`
    """
    if not is_waypoint_configured():
        return _json({"ok": False, "error": "Waypoint is not configured (WAYPOINT_API_BASE_URL unset)."})
    try:
        items = json.loads(invoices_json)
    except (TypeError, json.JSONDecodeError) as exc:
        return _json({"ok": False, "error": f"invalid invoices_json: {exc}"})
    if isinstance(items, dict):
        items = items.get("invoices") if isinstance(items.get("invoices"), list) else [items]
    if not isinstance(items, list) or not items:
        return _json({"ok": False, "error": "invoices_json must be a non-empty JSON array."})

    results: list[dict[str, Any]] = []
    with trace_span(
        "waypoint_recorder.enroll_batch",
        {
            "gen_ai.agent.name": "waypoint-recorder",
            "gen_ai.operation.name": "execute_tool",
            "gen_ai.tool.name": "waypoint_enroll_batch",
            "forge.batch.size": len(items),
        },
    ) as span:
        for item in items:
            if isinstance(item, str):
                invoice_ref, op = item, ""
            elif isinstance(item, dict):
                invoice_ref = str(item.get("invoice_id") or item.get("invoice_number") or "").strip()
                op = str(item.get("operation_id") or "").strip()
            else:
                continue
            if not invoice_ref:
                continue
            results.append(_try_parse(_waypoint_open_run_inner(invoice_ref, op, "pending")))
        enrolled = sum(1 for r in results if r.get("ok"))
        set_span_attribute(span, "forge.batch.enrolled", enrolled)
    return _json({"ok": True, "enrolled": enrolled, "results": results})


def build_waypoint_write_tools() -> list[FunctionTool]:
    """Return the waypoint_recorder's write FunctionTools (empty when Waypoint is unconfigured)."""
    if not is_waypoint_configured():
        logger.info("Waypoint not configured; waypoint_recorder write tools disabled.")
        return []
    return [
        tool(waypoint_open_run),
        tool(waypoint_fail_run),
        tool(waypoint_enroll_batch),
        tool(waypoint_record_assurance),
    ]


# ── grounding ────────────────────────────────────────────────────────────────


_ESCALATE_FINDING_STATUSES = {"escalate", "escalated", "disputed"}
_CLEAN_FINDING_STATUSES = {"approved", "approve", "matched", "clean"}
_ACTIONABLE_SEVERITIES = {"high", "critical"}


def _is_actionable_finding(finding: dict[str, Any]) -> bool:
    """Return True when a finding should drive a variance/recover/escalate decision.

    Mirrors the assurance-orchestrator's ``_judgement_status`` contract: the seed
    attaches a finding to every invoice, including clean ones (``status`` approved,
    ``overpayment_amount`` 0, ``severity`` low). Those non-actionable findings must
    not force a clean invoice off ``approve``. High/critical severity findings are
    always actionable so real exceptions still escalate.
    """
    severity = str(finding.get("severity") or "").strip().lower()
    if severity in _ACTIONABLE_SEVERITIES:
        return True
    status = str(finding.get("status") or "").strip().lower()
    if status in _CLEAN_FINDING_STATUSES:
        return False
    overpayment = _float(finding.get("overpayment_amount"))
    if overpayment == 0 and severity in {"", "low"}:
        return False
    return True


def _derive_decision(findings: list[dict[str, Any]]) -> tuple[str, str]:
    """Deterministically map grounded corpus findings to a Waypoint decision.

    Implements the documented service-owned policy check
    (``status: matched|variance|disputed|escalated`` ->
    ``decision: approve|recover|escalate|review``) so the persisted decision is
    anchored to corpus truth rather than the model's free-text choice.
    """
    actionable = [finding for finding in findings if _is_actionable_finding(finding)]
    if not actionable:
        return "approve", "matched"
    for finding in actionable:
        severity = str(finding.get("severity") or "").strip().lower()
        status = str(finding.get("status") or "").strip().lower()
        if severity in _ACTIONABLE_SEVERITIES or status in _ESCALATE_FINDING_STATUSES:
            return "escalate", "escalated"
    # Honour an explicit curated "review" disposition even when money is at risk.
    # A finding the corpus marks ``status: review`` is a human-review hold (e.g. a
    # quality hold or unmatched invoice awaiting judgement), not an auto-recover, so
    # it must not collapse into ``recover`` just because overpayment > 0. The
    # high/critical escalate rail above still wins, so this only affects non-escalate
    # variance findings.
    if any(str(finding.get("status") or "").strip().lower() == "review" for finding in actionable):
        return "review", "variance"
    total_overpayment = sum(_float(finding.get("overpayment_amount")) for finding in actionable)
    if total_overpayment > 0:
        return "recover", "variance"
    return "review", "variance"


def _govern_decision(
    findings: list[dict[str, Any]], model_decision: str
) -> tuple[str, dict[str, Any]]:
    """Reconcile the model-proposed decision with the deterministic policy check.

    When corpus findings exist, the deterministic mapping is authoritative — the
    model still narrates the reasoning/summary/draft, but the persisted decision
    cannot drift off corpus truth (e.g. a ``severity:high`` finding can no longer
    be written as ``recover``). When no findings are grounded, honour the model's
    proposal so degraded/uncorpused runs still record something sensible.
    """
    proposed = (model_decision or "review").strip().lower()
    if proposed not in DECISIONS:
        proposed = "review"
    if not findings:
        return proposed, {
            "source": "model",
            "model_decision": proposed,
            "policy_decision": None,
            "overridden": False,
        }
    policy_decision, status = _derive_decision(findings)
    return policy_decision, {
        "source": "policy" if policy_decision == proposed else "policy_override",
        "model_decision": proposed,
        "policy_decision": policy_decision,
        "status": status,
        "overridden": policy_decision != proposed,
    }


def _ground(invoice_ref: str) -> dict[str, Any]:
    """Fetch the invoice's findings + evidence from the corpus (best-effort).

    Returns canonical ids, the summed money-at-risk, the real evidence-reference ids,
    a representative finding id, and a deterministic per-plane fan-out skeleton.
    """
    empty = {
        "invoice_id": "",
        "invoice_number": "",
        "money_at_risk": 0.0,
        "evidence_ids": [],
        "finding_id": None,
        "finding_count": 0,
        "findings": [],
        "evidence": [],
    }
    try:
        reader = WaypointReadClient()
    except Exception:
        return empty
    try:
        detail = reader.resolve_invoice(invoice_ref)
        if not detail:
            return empty
        invoice_id = str(detail.get("id") or "")
        findings = reader.list_findings(invoice_id) or _as_list(detail.get("findings"))
        evidence = reader.list_evidence(invoice_id) or _as_list(detail.get("evidence"))
    except Exception:
        logger.warning("grounding read failed for %s", invoice_ref, exc_info=True)
        return empty

    money = 0.0
    evidence_ids: list[str] = []
    for finding in findings:
        money += _float(finding.get("overpayment_amount"))
        evidence_ids.extend(_str_list(finding.get("evidence_ids")))
    for ev in evidence:
        ev_id = str(ev.get("id") or "")
        if ev_id:
            evidence_ids.append(ev_id)

    return {
        "invoice_id": invoice_id,
        "invoice_number": str(detail.get("invoice_number") or ""),
        "money_at_risk": round(money, 2),
        "evidence_ids": _dedupe(evidence_ids),
        "finding_id": str(findings[0].get("id")) if findings else None,
        "finding_count": len(findings),
        "findings": findings,
        "evidence": evidence,
    }


def _lane_is_grounded(lane: dict[str, Any]) -> bool:
    """A fan-out lane counts as a consulted expert only when it produced at least one
    grounded evidence item — an evidence claim carrying a source_ref (a real citation).
    A lane with only a summary and no citations grounded on nothing."""
    return any(
        isinstance(claim, dict) and str(claim.get("source_ref") or "").strip()
        for claim in _as_list(lane.get("evidence"))
    )


def _lane_is_expert(lane: dict[str, Any]) -> bool:
    plane = str(lane.get("plane") or "").strip().lower()
    agent = str(lane.get("agent") or "").strip().lower()
    return _EXPERT_AGENT_BY_PLANE.get(plane) == agent


def _normalize_fanout(raw: Any, grounding: dict[str, Any]) -> list[dict[str, Any]]:
    """Keep only canonical expert lanes from the orchestrator's runtime fan-out.

    Grounded invoice context is not proof that an optional expert ran, so missing or
    malformed fan-out must not be synthesized into expert participation.
    """
    del grounding
    lanes = _as_list(raw)
    cleaned: list[dict[str, Any]] = []
    for lane in lanes:
        if not isinstance(lane, dict):
            continue
        plane = str(lane.get("plane") or "").strip().lower()
        agent = str(lane.get("agent") or "").strip().lower()
        expected_agent = _EXPERT_AGENT_BY_PLANE.get(plane)
        if expected_agent != agent:
            logger.warning("discarding non-expert fan-out lane agent=%r plane=%r", agent, plane)
            continue
        evidence = [_clean_claim(c) for c in _as_list(lane.get("evidence")) if isinstance(c, dict)]
        cleaned.append(
            {
                "agent": expected_agent,
                "plane": plane,
                "summary": str(lane.get("summary") or "").strip(),
                "output_quality": str(lane.get("output_quality") or "").strip(),
                "unsupported": _str_list(lane.get("unsupported")),
                "evidence": evidence,
            }
        )
    cleaned = [lane for lane in cleaned if lane["evidence"] or lane["summary"]]
    return cleaned


def _clean_claim(claim: dict[str, Any]) -> dict[str, Any]:
    return {
        "claim": str(claim.get("claim") or "").strip(),
        "supports": str(claim.get("supports") or "unknown").strip().lower(),
        "source_ref": str(claim.get("source_ref") or "").strip(),
        "classification": str(claim.get("classification") or "standard").strip().lower(),
        "confidence": _float(claim.get("confidence")),
    }


def _run_summary(
    *,
    decision: str,
    invoice_number: str,
    money_at_risk: float,
    finding_count: int,
    expert_count: int,
) -> str:
    money = f"${money_at_risk:,.2f}" if money_at_risk else "$0.00"
    findings = f"{finding_count} finding{'s' if finding_count != 1 else ''}"
    experts = f"{expert_count} expert{'s' if expert_count != 1 else ''}"
    return (
        f"{decision.upper()} {invoice_number}: {money} at risk across {findings}; "
        f"{experts} consulted."
    )


# ── helpers ──────────────────────────────────────────────────────────────────


_INVOICE_REF_RE = re.compile(r"inv-\d{4}-\d{3,}", re.IGNORECASE)


def _recover_invoice_ref(result: dict[str, Any]) -> str:
    """Best-effort recovery of the invoice reference from the model payload.

    The model is non-deterministic and occasionally omits the top-level
    ``invoice_id`` even though every fan-out lane, finding id, evidence id, and the
    reasoning all reference the same invoice. Rather than silently no-op the write,
    recover the reference from any of those fields and let ``_ground`` canonicalize
    it. Each waypoint_recorder call records exactly one invoice, so the first reference
    found is the right one.
    """
    direct = str(result.get("invoice_id") or result.get("invoice_number") or "").strip()
    if direct:
        return direct
    match = _INVOICE_REF_RE.search(json.dumps(result, default=str))
    if match:
        return match.group(0).upper()
    return ""


def _normalize_result_contract(result: dict[str, Any]) -> dict[str, Any]:
    """Accept the waypoint_recorder flat contract or one AssuranceOrchestrator write-plan preview."""
    if "future_payloads" in result:
        future_payloads = _as_list(result.get("future_payloads"))
        if len(future_payloads) != 1 or not isinstance(future_payloads[0], dict):
            raise ValueError("future_payloads must contain exactly one object")
        result = future_payloads[0]

    recommendation = result.get("recommendation")
    if not isinstance(recommendation, dict):
        return result

    metadata = recommendation.get("metadata") if isinstance(recommendation.get("metadata"), dict) else {}
    normalized = {
        "invoice_id": result.get("invoice_id"),
        "invoice_number": result.get("invoice_number"),
        "waypoint_case_id": result.get("waypoint_case_id"),
        "decision": recommendation.get("decision"),
        "reasoning": recommendation.get("reasoning"),
        "confidence": recommendation.get("confidence"),
        "money_at_risk": recommendation.get("money_at_risk"),
        "finding_id": result.get("finding_id"),
        "title": result.get("title"),
        "summary": result.get("summary") or recommendation.get("reasoning"),
        "classification": result.get("classification") or "standard",
        "evidence_ids": recommendation.get("evidence_ids", []),
        "proposed_next_actions": recommendation.get("proposed_next_actions", []),
        "fanout": metadata.get("expert_evidence", result.get("fanout", [])),
        "draft": result.get("draft"),
    }
    return {key: value for key, value in normalized.items() if value is not None}


def _parse(raw: str) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError(str(exc)) from exc
    if not isinstance(value, dict):
        raise ValueError("expected a JSON object")
    return value


def _try_parse(raw: str) -> dict[str, Any]:
    try:
        return _parse(raw)
    except ValueError:
        return {}


def _id(entity: Any) -> str | None:
    if isinstance(entity, dict):
        value = entity.get("id")
        return str(value) if value is not None else None
    return None


def _opt(value: Any) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None


def _float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _str_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    return []


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            out.append(value)
    return out


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False)
