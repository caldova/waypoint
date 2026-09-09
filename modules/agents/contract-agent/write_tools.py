"""Waypoint tools — the single, governed write path.

This is the pipeline's only write boundary: one tool, ``record_assurance``,
which is the sole thing allowed to mutate Waypoint. It preserves the governance
invariant the old ``waypoint-recorder`` enforced, minus the fleet:

1. **Re-ground** the invoice against the Waypoint corpus (findings + evidence),
   so the persisted decision trail carries real money-at-risk and real
   evidence-reference ids even when the model's narrated numbers drift.
2. **Govern the decision**: when corpus findings exist, a deterministic policy
   check owns the decision (``matched|variance|disputed|escalated`` →
   ``approve|recover|escalate|review``). The model narrates reasoning/summary/
   draft, but a ``severity:high`` finding can never be persisted as ``recover``
   just because the model said so.
3. **Write once**: open a case, open a run (``running``), stage a recommendation
   and optional draft, then advance the run to ``completed`` — returning the
   Waypoint correlation ids.

castia is non-MCP: this reaches the Waypoint API directly. ``respond_with_tools``
wraps the call in an ``execute_tool`` span, so there is no telemetry here.
"""

from __future__ import annotations

import json
import re
import uuid
from typing import Any

import httpx
from castia.tools import Tool

from tools import _WaypointClient, _as_list, _float, _str_list, is_waypoint_configured

# Closed vocabularies mirrored from the Waypoint API cases schemas.
DECISIONS = {"approve", "recover", "escalate", "review"}
DRAFT_TYPES = {"supplier_dispute", "escalation_packet", "approval_summary"}
CLASSIFICATIONS = {"standard", "confidential", "ip_sensitive", "restricted"}

# Deterministic policy-check vocabularies (mirror the assurance workflow).
_ESCALATE_FINDING_STATUSES = {"escalate", "escalated", "disputed"}
_CLEAN_FINDING_STATUSES = {"approved", "approve", "matched", "clean"}
_ACTIONABLE_SEVERITIES = {"high", "critical"}

_INVOICE_REF_RE = re.compile(r"inv-\d{4}-\d{3,}", re.IGNORECASE)

_RESULT_SHAPE = """{
  "invoice_id": "INV-2026-08034",
  "decision": "approve|recover|escalate|review",
  "reasoning": "Why this decision, citing the gathered evidence.",
  "confidence": 0.0,
  "money_at_risk": 0.0,
  "finding_id": "optional finding id",
  "title": "optional case title",
  "summary": "short case summary",
  "classification": "standard|confidential|ip_sensitive|restricted",
  "evidence_ids": ["optional evidence ref ids"],
  "proposed_next_actions": ["optional action labels"],
  "draft": {"draft_type": "supplier_dispute|escalation_packet|approval_summary",
            "title": "draft title", "body": "draft body"}
}"""


# ── governed write client ─────────────────────────────────────────────────────


class _WaypointWriter(_WaypointClient):
    """Adds the governed POST/PATCH write surface to the read client."""

    async def _send(self, method: str, path: str, body: dict[str, Any]) -> Any:
        headers = await self._headers()
        headers["Content-Type"] = "application/json"
        async with httpx.AsyncClient(timeout=30.0, verify=self._verify) as client:
            response = await client.request(method, self._url(path), headers=headers, json=body)
        # A run PATCH route may not be deployed on an older API — degrade to no-op.
        if method == "PATCH" and response.status_code in {404, 405}:
            return None
        if response.is_error:
            raise RuntimeError(f"Waypoint {method} {path} failed with HTTP {response.status_code}: {response.text[:300]}")
        return response.json() if response.content else None

    async def create_case(self, invoice_id: str, *, finding_id: str | None, title: str | None, summary: str, classification: str, idempotency_key: str, metadata: dict[str, Any]) -> Any:
        return await self._send("POST", "/api/cases", {
            "invoice_id": invoice_id,
            "finding_id": finding_id,
            "title": title,
            "summary": summary,
            "classification": _classification(classification),
            "idempotency_key": idempotency_key,
            "metadata": metadata,
        })

    async def open_run(self, *, name: str, case_id: str | None, status: str, summary: str, idempotency_key: str, metadata: dict[str, Any]) -> Any:
        return await self._send("POST", "/api/runs", {
            "name": name,
            "case_id": case_id,
            "foundry_agent_name": "contract-agent",
            "status": status,
            "summary": summary,
            "idempotency_key": idempotency_key,
            "metadata": metadata,
        })

    async def update_run(self, run_id: str, *, status: str, summary: str, metadata: dict[str, Any]) -> Any:
        return await self._send("PATCH", f"/api/runs/{run_id}", {"status": status, "summary": summary, "metadata": metadata})

    async def create_recommendation(self, case_id: str, *, decision: str, reasoning: str, confidence: float, money_at_risk: float, evidence_ids: list[str], proposed_next_actions: list[str], metadata: dict[str, Any]) -> Any:
        return await self._send("POST", f"/api/cases/{case_id}/recommendations", {
            "decision": _decision(decision),
            "reasoning": reasoning,
            "confidence": _clamp_unit(confidence),
            "money_at_risk": str(money_at_risk),
            "evidence_ids": evidence_ids,
            "proposed_next_actions": proposed_next_actions,
            "metadata": metadata,
        })

    async def create_draft(self, case_id: str, *, draft_type: str, title: str, body_text: str, source_recommendation_id: str | None, classification: str, metadata: dict[str, Any]) -> Any:
        return await self._send("POST", f"/api/cases/{case_id}/drafts", {
            "draft_type": _draft_type(draft_type),
            "title": title,
            "body": body_text,
            "source_recommendation_id": source_recommendation_id,
            "classification": _classification(classification),
            "metadata": metadata,
        })


# ── decision governance (deterministic policy check owns the decision) ────────


def _is_actionable_finding(finding: dict[str, Any]) -> bool:
    severity = str(finding.get("severity") or "").strip().lower()
    if severity in _ACTIONABLE_SEVERITIES:
        return True
    status = str(finding.get("status") or "").strip().lower()
    if status in _CLEAN_FINDING_STATUSES:
        return False
    if _float(finding.get("overpayment_amount")) == 0 and severity in {"", "low"}:
        return False
    return True


def _derive_decision(findings: list[dict[str, Any]]) -> tuple[str, str]:
    actionable = [f for f in findings if _is_actionable_finding(f)]
    if not actionable:
        return "approve", "matched"
    for finding in actionable:
        severity = str(finding.get("severity") or "").strip().lower()
        status = str(finding.get("status") or "").strip().lower()
        if severity in _ACTIONABLE_SEVERITIES or status in _ESCALATE_FINDING_STATUSES:
            return "escalate", "escalated"
    if any(str(f.get("status") or "").strip().lower() == "review" for f in actionable):
        return "review", "variance"
    if sum(_float(f.get("overpayment_amount")) for f in actionable) > 0:
        return "recover", "variance"
    return "review", "variance"


def _govern_decision(state: str, findings: list[dict[str, Any]], model_decision: str) -> tuple[str, dict[str, Any]]:
    proposed = (model_decision or "review").strip().lower()
    if proposed not in DECISIONS:
        proposed = "review"
    # No grounded corpus truth → never persist a model-authored verdict. Hold for
    # human review rather than let a transient corpus failure ship an approve/recover.
    if state != "grounded":
        return "review", {
            "source": "ungrounded_hold",
            "model_decision": proposed,
            "policy_decision": "review",
            "grounding_state": state,
            "overridden": proposed != "review",
        }
    # A resolved invoice with zero findings is a legitimate clean pass; the
    # deterministic policy (no actionable finding → approve) owns it, not the model.
    policy_decision, status = _derive_decision(findings)
    return policy_decision, {
        "source": "policy" if policy_decision == proposed else "policy_override",
        "model_decision": proposed,
        "policy_decision": policy_decision,
        "status": status,
        "grounding_state": state,
        "overridden": policy_decision != proposed,
    }


# ── grounding ─────────────────────────────────────────────────────────────────


async def _ground(invoice_ref: str) -> dict[str, Any]:
    """Fetch the invoice's findings + evidence from the corpus.

    Returns an explicit ``state`` so the writer can tell grounded truth apart from
    a degraded corpus: ``grounded`` (invoice resolved), ``unresolved`` (no invoice
    matched), ``unavailable`` (corpus errored), ``not_configured``. Money and
    evidence are only trustworthy when ``state == "grounded"``.
    """
    empty = {"state": "unresolved", "invoice_id": "", "invoice_number": "", "money_at_risk": 0.0, "evidence_ids": [], "finding_id": None, "finding_count": 0, "findings": []}
    if not is_waypoint_configured():
        return {**empty, "state": "not_configured"}
    try:
        reader = _WaypointClient()
        detail = await reader.resolve_invoice(invoice_ref)
        if not detail:
            return empty
        invoice_id = str(detail.get("id") or "")
        findings = await reader.list_findings(invoice_id) or _as_list(detail.get("findings"))
        evidence = await reader.list_evidence(invoice_id) or _as_list(detail.get("evidence"))
    except Exception:  # noqa: BLE001 - a corpus failure must not look like a clean invoice
        return {**empty, "state": "unavailable"}

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
        "state": "grounded",
        "invoice_id": invoice_id,
        "invoice_number": str(detail.get("invoice_number") or ""),
        "money_at_risk": round(money, 2),
        "evidence_ids": _dedupe(evidence_ids),
        "finding_id": str(findings[0].get("id")) if findings else None,
        "finding_count": len(findings),
        "findings": findings,
    }


# ── the sole write tool ───────────────────────────────────────────────────────


async def _record_assurance_impl(activity: Any, *, result_json: str) -> dict[str, Any]:
    """Write one governed assurance result to Waypoint (case + run + recommendation + draft)."""
    if not is_waypoint_configured():
        return {"ok": False, "error": "Waypoint is not configured (WAYPOINT_API_BASE_URL unset)."}

    try:
        result = _parse(result_json)
    except ValueError as exc:
        return {"ok": False, "error": f"invalid result_json: {exc}"}

    invoice_ref = _recover_invoice_ref(result)
    if not invoice_ref:
        return {"ok": False, "error": "result_json.invoice_id is required; no invoice reference was found."}

    grounding = await _ground(invoice_ref)
    state = grounding["state"]
    invoice_id = grounding["invoice_id"] or invoice_ref
    invoice_number = grounding["invoice_number"] or invoice_ref

    # The deterministic policy check owns the decision when corpus truth exists;
    # an ungrounded turn is held for review rather than trusting the model.
    decision, decision_governance = _govern_decision(state, grounding["findings"], str(result.get("decision") or ""))

    # Money and evidence come from the corpus, never the model — a grounded turn
    # uses the grounded totals; an ungrounded turn asserts nothing it can't verify.
    grounded = state == "grounded"
    money_at_risk = grounding["money_at_risk"] if grounded else 0.0
    evidence_ids = grounding["evidence_ids"] if grounded else []
    finding_id = grounding["finding_id"]
    reasoning = str(result.get("reasoning") or "").strip()
    confidence = _float(result.get("confidence"))
    classification = str(result.get("classification") or "standard")
    summary = str(result.get("summary") or "").strip()
    run_summary = _run_summary(decision=decision, invoice_number=invoice_number, money_at_risk=money_at_risk, finding_count=grounding["finding_count"])

    op_id = uuid.uuid4().hex
    correlation: dict[str, Any] = {
        "waypoint_run_id": None, "waypoint_case_id": None, "waypoint_recommendation_id": None,
        "waypoint_draft_id": None, "waypoint_invoice_id": invoice_id, "invoice_number": invoice_number,
        "money_at_risk": money_at_risk, "evidence_count": len(evidence_ids),
    }
    run_metadata = {
        "invoice_id": invoice_id, "invoice_number": invoice_number, "decision": decision,
        "confidence": confidence, "money_at_risk": money_at_risk, "finding_count": grounding["finding_count"],
    }

    writer = _WaypointWriter()
    run_id: str | None = None
    try:
        case = await writer.create_case(
            invoice_id, finding_id=finding_id, title=_opt(result.get("title")), summary=summary,
            classification=classification, idempotency_key=f"assurance-case:{invoice_ref}:{op_id}",
            metadata={"invoice_number": invoice_number},
        )
        case_id = _id(case)
        correlation["waypoint_case_id"] = case_id

        run = await writer.open_run(
            name=f"assurance:{invoice_number}", case_id=case_id, status="running",
            summary=run_summary, idempotency_key=f"assurance:{invoice_ref}:{op_id}", metadata=run_metadata,
        )
        run_id = _id(run)
        correlation["waypoint_run_id"] = run_id

        recommendation = await writer.create_recommendation(
            case_id, decision=decision, reasoning=reasoning, confidence=confidence,
            money_at_risk=money_at_risk, evidence_ids=evidence_ids,
            proposed_next_actions=_str_list(result.get("proposed_next_actions")),
            metadata={"waypoint_run_id": run_id, "invoice_number": invoice_number, "decision_governance": decision_governance},
        )
        correlation["waypoint_recommendation_id"] = _id(recommendation)

        draft = result.get("draft")
        if isinstance(draft, dict) and draft.get("body"):
            created_draft = await writer.create_draft(
                case_id, draft_type=str(draft.get("draft_type") or "supplier_dispute"),
                title=str(draft.get("title") or f"Draft for {invoice_number}"), body_text=str(draft.get("body")),
                source_recommendation_id=correlation["waypoint_recommendation_id"], classification=classification,
                metadata={"waypoint_run_id": run_id},
            )
            correlation["waypoint_draft_id"] = _id(created_draft)

        final = await writer.update_run(run_id, status="completed", summary=run_summary, metadata={
            **run_metadata, "waypoint_recommendation_id": correlation["waypoint_recommendation_id"], "waypoint_draft_id": correlation["waypoint_draft_id"],
        })
        # A run PATCH route absent on an older API degrades to None — say so rather
        # than reporting a completed run the server never actually closed.
        correlation["run_finalized"] = final is not None
    except Exception as exc:  # noqa: BLE001 - surface a structured error to the model
        if run_id is not None:
            try:
                await writer.update_run(run_id, status="failed", summary=run_summary, metadata={**run_metadata, "error": str(exc)})
            except Exception:  # noqa: BLE001
                pass
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}", "correlation": correlation}

    return {"ok": True, "decision": decision, "governance": decision_governance, "grounding_state": state, "correlation": correlation}


def write_tools() -> list[Tool]:
    """The single agent's one governed write tool — the sole path that mutates Waypoint."""
    return [
        Tool(
            name="record_assurance",
            description=(
                "Persist the FINAL governed assurance decision for ONE invoice to "
                "Waypoint. This is the only tool that writes to Waypoint — call it "
                "exactly once, after gathering evidence, with your decision and "
                "reasoning. The tool re-grounds money-at-risk and evidence ids against "
                "the corpus and lets a deterministic policy check own the decision when "
                "corpus findings exist, so pass your honest read and it will be "
                "reconciled. Pass a JSON object (as a string) shaped like:\n" + _RESULT_SHAPE
            ),
            parameters={
                "type": "object",
                "properties": {
                    "result_json": {
                        "type": "string",
                        "description": "A JSON object (serialized) describing the final decision for one invoice.",
                    },
                },
                "required": ["result_json"],
                "additionalProperties": False,
            },
            impl=_record_assurance_impl,
        ),
    ]


# ── helpers ───────────────────────────────────────────────────────────────────


def _recover_invoice_ref(result: dict[str, Any]) -> str:
    direct = str(result.get("invoice_id") or result.get("invoice_number") or "").strip()
    if direct:
        return direct
    match = _INVOICE_REF_RE.search(json.dumps(result, default=str))
    return match.group(0).upper() if match else ""


def _run_summary(*, decision: str, invoice_number: str, money_at_risk: float, finding_count: int) -> str:
    money = f"${money_at_risk:,.2f}" if money_at_risk else "$0.00"
    findings = f"{finding_count} finding{'s' if finding_count != 1 else ''}"
    return f"{decision} {invoice_number}: {money} at risk across {findings}."


def _parse(raw: str) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError(str(exc)) from exc
    if not isinstance(value, dict):
        raise ValueError("expected a JSON object")
    return value


def _id(entity: Any) -> str | None:
    if isinstance(entity, dict) and entity.get("id") is not None:
        return str(entity["id"])
    return None


def _opt(value: Any) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            out.append(value)
    return out


def _classification(value: str) -> str:
    cleaned = (value or "standard").strip().lower()
    return cleaned if cleaned in CLASSIFICATIONS else "standard"


def _decision(value: str) -> str:
    cleaned = (value or "").strip().lower()
    if cleaned not in DECISIONS:
        raise ValueError(f"decision must be one of {sorted(DECISIONS)}, got {value!r}")
    return cleaned


def _draft_type(value: str) -> str:
    cleaned = (value or "").strip().lower()
    if cleaned not in DRAFT_TYPES:
        raise ValueError(f"draft_type must be one of {sorted(DRAFT_TYPES)}, got {value!r}")
    return cleaned


def _clamp_unit(value: float) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = 0.0
    return str(max(0.0, min(1.0, number)))
