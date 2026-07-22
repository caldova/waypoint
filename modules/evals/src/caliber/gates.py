"""Fail-closed fine-tuning/eval promotion gates.

This module only evaluates whether an operation (an optimizer candidate
apply, an RFT submission, a model-checkpoint deploy, or a promotion) *would*
be allowed. It never performs the operation itself: there is no code path
here that applies a candidate, deploys a checkpoint, promotes a model, or
mutates any production state.

Every gate defaults closed: if a required input is missing or unconfirmed,
the gate fails. Callers must explicitly supply evidence that a gate is
satisfied (an approval, a verified-fresh lineage snapshot, a confirmed spend
flag, etc.) for it to pass.
"""

from __future__ import annotations

from typing import Any

#: Only re-verifiable current lineage can authorize a governed mutation.
#: Reference-only evidence remains useful for historical comparison, but its
#: source assets cannot qualify an optimizer apply, RFT submit, or promotion.
ACCEPTABLE_LINEAGE_STATUSES = {"current"}

GATE_NAMES = (
    "review_approved",
    "lineage_fresh",
    "model_ready",
    "quota_ready",
    "spend_confirmed",
    "protected_approval",
)

GUARANTEES = (
    "This command only evaluates gates; it never applies a candidate, deploys a model "
    "checkpoint, promotes a model, or mutates production state.",
)


def evaluate_gates(
    *,
    operation: str,
    review_approved: bool = False,
    lineage_status: str = "unverifiable",
    model_ready: bool = False,
    quota_ready: bool = False,
    spend_confirmed: bool = False,
    protected_approver: str | None = None,
    required_approver_role: str | None = None,
    approvals: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Evaluate all fail-closed gates for one named operation.

    `operation` is a free-form label (e.g. `optimizer_apply`, `rft_submit`,
    `candidate_promote`, `checkpoint_deploy`) describing what the caller is
    asking permission to do next, purely for reporting; this function never
    performs it.
    """
    if not operation.strip():
        raise ValueError("operation is required")
    if lineage_status not in {"current", "stale", "reference_only", "unverifiable"}:
        raise ValueError(
            "lineage_status must be one of: current, stale, reference_only, unverifiable"
        )

    approvals = approvals or []
    lineage_ok = lineage_status in ACCEPTABLE_LINEAGE_STATUSES
    protected_ok = _protected_approval_satisfied(
        protected_approver=protected_approver,
        required_approver_role=required_approver_role,
        approvals=approvals,
    )

    checks = {
        "review_approved": _gate(
            "review_approved",
            review_approved,
            "A human reviewer has explicitly approved this operation."
            if review_approved
            else "Missing explicit human review approval.",
        ),
        "lineage_fresh": _gate(
            "lineage_fresh",
            lineage_ok,
            f"Lineage status is '{lineage_status}'."
            if lineage_ok
            else f"Lineage status '{lineage_status}' is not current.",
        ),
        "model_ready": _gate(
            "model_ready",
            model_ready,
            "Target model/deployment readiness was explicitly confirmed."
            if model_ready
            else "Target model/deployment readiness was not confirmed.",
        ),
        "quota_ready": _gate(
            "quota_ready",
            quota_ready,
            "Quota/capacity for the target model/deployment was explicitly confirmed."
            if quota_ready
            else "Quota/capacity for the target model/deployment was not confirmed.",
        ),
        "spend_confirmed": _gate(
            "spend_confirmed",
            spend_confirmed,
            "Live spend for this operation was explicitly confirmed."
            if spend_confirmed
            else "Live spend for this operation was not explicitly confirmed.",
        ),
        "protected_approval": _gate(
            "protected_approval",
            protected_ok,
            _protected_approval_message(
                protected_ok=protected_ok,
                required_approver_role=required_approver_role,
            ),
        ),
    }

    allowed = all(check["ok"] for check in checks.values())
    return {
        "operation": operation,
        "mode": "fail_closed",
        "allowed": allowed,
        "gates": checks,
        "blocking_reasons": [name for name, check in checks.items() if not check["ok"]],
        "guarantees": list(GUARANTEES),
    }


def _gate(name: str, ok: bool, message: str) -> dict[str, Any]:
    return {"name": name, "ok": bool(ok), "message": message}


def _protected_approval_message(*, protected_ok: bool, required_approver_role: str | None) -> str:
    if not required_approver_role:
        return "No protected-approval role is required for this operation."
    if protected_ok:
        return f"A protected approver with role '{required_approver_role}' signed off."
    return f"Missing a protected approval from role '{required_approver_role}'."


def _protected_approval_satisfied(
    *,
    protected_approver: str | None,
    required_approver_role: str | None,
    approvals: list[dict[str, Any]],
) -> bool:
    if not required_approver_role:
        return True
    if protected_approver:
        return any(
            approval.get("approver") == protected_approver
            and approval.get("role") == required_approver_role
            for approval in approvals
        )
    return any(approval.get("role") == required_approver_role for approval in approvals)
