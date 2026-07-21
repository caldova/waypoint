"""Tests for caliber.gates: fail-closed FT/eval promotion gates."""

from __future__ import annotations

import pytest

from caliber.gates import GATE_NAMES, evaluate_gates


def test_all_gates_default_closed() -> None:
    result = evaluate_gates(operation="rft_submit")
    assert result["allowed"] is False
    assert result["mode"] == "fail_closed"
    assert set(result["blocking_reasons"]) == {
        "review_approved",
        "lineage_fresh",
        "model_ready",
        "quota_ready",
        "spend_confirmed",
    }
    assert result["gates"]["protected_approval"]["ok"] is True  # no role required by default
    assert set(result["gates"]) == set(GATE_NAMES)


def test_operation_is_required() -> None:
    with pytest.raises(ValueError, match="operation is required"):
        evaluate_gates(operation="")


def test_invalid_lineage_status_rejected() -> None:
    with pytest.raises(ValueError, match="lineage_status must be one of"):
        evaluate_gates(operation="rft_submit", lineage_status="not-a-real-status")


@pytest.mark.parametrize("status", ["current", "reference_only"])
def test_lineage_fresh_passes_for_current_or_reference_only(status: str) -> None:
    result = evaluate_gates(operation="rft_submit", lineage_status=status)
    assert result["gates"]["lineage_fresh"]["ok"] is True


@pytest.mark.parametrize("status", ["stale", "unverifiable"])
def test_lineage_fresh_fails_for_stale_or_unverifiable(status: str) -> None:
    result = evaluate_gates(operation="rft_submit", lineage_status=status)
    assert result["gates"]["lineage_fresh"]["ok"] is False


def test_all_gates_open_allows_operation() -> None:
    result = evaluate_gates(
        operation="rft_submit",
        review_approved=True,
        lineage_status="current",
        model_ready=True,
        quota_ready=True,
        spend_confirmed=True,
    )
    assert result["allowed"] is True
    assert result["blocking_reasons"] == []


def test_protected_approval_requires_matching_role() -> None:
    base_kwargs = dict(
        operation="candidate_promote",
        review_approved=True,
        lineage_status="current",
        model_ready=True,
        quota_ready=True,
        spend_confirmed=True,
        required_approver_role="eng-lead",
    )

    denied = evaluate_gates(**base_kwargs)
    assert denied["allowed"] is False
    assert "protected_approval" in denied["blocking_reasons"]

    denied_wrong_role = evaluate_gates(
        **base_kwargs, approvals=[{"approver": "alice", "role": "pm"}]
    )
    assert denied_wrong_role["gates"]["protected_approval"]["ok"] is False

    allowed = evaluate_gates(
        **base_kwargs, approvals=[{"approver": "alice", "role": "eng-lead"}]
    )
    assert allowed["allowed"] is True
    assert allowed["gates"]["protected_approval"]["ok"] is True


def test_protected_approval_can_require_specific_approver_and_role() -> None:
    kwargs = dict(
        operation="candidate_promote",
        protected_approver="alice",
        required_approver_role="eng-lead",
    )
    # Right role, wrong approver name -> not satisfied when a specific approver is required.
    wrong_approver = evaluate_gates(
        **kwargs, approvals=[{"approver": "bob", "role": "eng-lead"}]
    )
    assert wrong_approver["gates"]["protected_approval"]["ok"] is False

    right_approver = evaluate_gates(
        **kwargs, approvals=[{"approver": "alice", "role": "eng-lead"}]
    )
    assert right_approver["gates"]["protected_approval"]["ok"] is True


def test_guarantees_state_no_mutation() -> None:
    result = evaluate_gates(operation="checkpoint_deploy")
    guarantees_text = " ".join(result["guarantees"])
    assert "never applies" in guarantees_text
    assert "deploys a model checkpoint" in guarantees_text
    assert "promotes a model" in guarantees_text
    assert "mutates production" in guarantees_text


def test_operation_label_is_echoed_back_but_never_executed() -> None:
    result = evaluate_gates(operation="optimizer_apply")
    assert result["operation"] == "optimizer_apply"
    # The gate module has no side effects: allowed reflects only supplied booleans.
    assert result["allowed"] is False
