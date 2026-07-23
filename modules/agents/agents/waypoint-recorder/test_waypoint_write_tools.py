"""Unit tests for the waypoint_recorder write tool's invoice-reference recovery.

The model occasionally omits the top-level ``invoice_id`` from the
``waypoint_record_assurance`` payload even though the invoice is referenced in the
finding id, evidence ids, fan-out, or reasoning. Recovery keeps the write from
silently no-opping. Run directly (``python test_waypoint_write_tools.py``) or via
pytest.
"""

from __future__ import annotations

import json
from unittest.mock import patch

from waypoint_write_client import WaypointWriteClient, WaypointWriteConfig
from waypoint_write_tools import (
    _derive_decision,
    _govern_decision,
    _lane_is_grounded,
    _normalize_fanout,
    _normalize_result_contract,
    _recover_invoice_ref,
    _waypoint_fail_run_inner,
    _waypoint_open_run_inner,
    _waypoint_record_assurance_inner,
    waypoint_enroll_batch,
)


class FakeWaypointReadClient:
    def resolve_invoice(self, invoice_ref: str) -> dict:
        return {
            "id": "invoice-001",
            "invoice_number": invoice_ref.upper(),
            "findings": [],
            "evidence": [],
        }

    def list_findings(self, invoice_id: str) -> list[dict]:
        return [
            {
                "id": "finding-inv-2026-08034",
                "category": "duplicate_charge",
                "summary": "Duplicate service charge.",
                "overpayment_amount": "25.00",
                "evidence_ids": ["evidence-001"],
                "contract_document_ids": ["contract-001"],
                "policy_ids": ["policy-001"],
            }
        ]

    def list_evidence(self, invoice_id: str) -> list[dict]:
        return [{"id": "evidence-002", "title": "Invoice attachment"}]


class FakeWaypointWriteClient:
    calls: list[tuple[str, dict]]

    def __init__(self) -> None:
        self.calls = []

    def create_case(self, invoice_id: str, **kwargs) -> dict:
        self.calls.append(("create_case", {"invoice_id": invoice_id, **kwargs}))
        return {"id": "case-001"}

    def open_run(self, name: str, **kwargs) -> dict:
        self.calls.append(("open_run", {"name": name, **kwargs}))
        return {"id": "run-001"}

    def update_run(self, run_id: str, **kwargs) -> dict:
        self.calls.append(("update_run", {"run_id": run_id, **kwargs}))
        return {"id": run_id}

    def create_recommendation(self, case_id: str, **kwargs) -> dict:
        self.calls.append(("create_recommendation", {"case_id": case_id, **kwargs}))
        return {"id": "recommendation-001"}

    def create_draft(self, case_id: str, **kwargs) -> dict:
        self.calls.append(("create_draft", {"case_id": case_id, **kwargs}))
        return {"id": "draft-001"}

    def open_assurance_run(self, invoice_ref: str, *, operation_id: str, status: str = "running", **kwargs) -> dict:
        self.calls.append(
            ("open_assurance_run", {"invoice_ref": invoice_ref, "operation_id": operation_id, "status": status, **kwargs})
        )
        return {
            "case_id": "case-001",
            "run_id": "run-001",
            "case_key": f"assurance-case:{invoice_ref}:{operation_id}",
            "run_key": f"assurance:{invoice_ref}:{operation_id}",
        }


def test_direct_invoice_id() -> None:
    assert _recover_invoice_ref({"invoice_id": "INV-2026-08034"}) == "INV-2026-08034"


def test_invoice_number_fallback() -> None:
    assert _recover_invoice_ref({"invoice_number": "INV-2026-08055"}) == "INV-2026-08055"


def test_from_finding_id() -> None:
    assert _recover_invoice_ref({"finding_id": "finding-inv-2026-08102"}) == "INV-2026-08102"


def test_from_evidence_ids() -> None:
    payload = {"evidence_ids": ["ev-inv-2026-08273-01", "ev-inv-2026-08273-02"]}
    assert _recover_invoice_ref(payload) == "INV-2026-08273"


def test_from_fanout_source_ref() -> None:
    payload = {
        "fanout": [
            {
                "summary": "No workplace matches for INV-2026-08140.",
                "evidence": [{"source_ref": "finding-inv-2026-08140"}],
            }
        ]
    }
    assert _recover_invoice_ref(payload) == "INV-2026-08140"


def test_from_reasoning_lowercase() -> None:
    payload = {"reasoning": "FabricIQ flagged inv-2026-08462 as a duplicate submission."}
    assert _recover_invoice_ref(payload) == "INV-2026-08462"


def test_no_reference_returns_empty() -> None:
    assert _recover_invoice_ref({"decision": "recover", "confidence": 0.9}) == ""


def test_assurance_orchestrator_future_payload_normalizes_to_waypoint_recorder_contract() -> None:
    payload = {
        "read_only": True,
        "side_effects_performed": False,
        "future_payloads": [
            {
                "invoice_id": "INV-2026-08034",
                "waypoint_case_id": "case-preview",
                "recommendation": {
                    "decision": "recover",
                    "reasoning": "Duplicate service charge.",
                    "confidence": 0.92,
                    "money_at_risk": "25.00",
                    "evidence_ids": ["evidence-001"],
                    "proposed_next_actions": ["request_supplier_credit"],
                    "metadata": {
                        "expert_evidence": [
                            {
                                "agent": "operations-data-expert",
                                "plane": "fabriciq",
                                "summary": "Duplicate charge found.",
                                "output_quality": "valid",
                                "unsupported": [],
                                "evidence": [
                                    {
                                        "claim": "Line already paid.",
                                        "supports": "recover",
                                        "source_ref": "finding-inv-2026-08034",
                                        "classification": "standard",
                                        "confidence": 0.9,
                                    }
                                ],
                            }
                        ],
                    },
                },
            }
        ],
    }

    normalized = _normalize_result_contract(payload)

    assert normalized["invoice_id"] == "INV-2026-08034"
    assert normalized["decision"] == "recover"
    assert normalized["reasoning"] == "Duplicate service charge."
    assert normalized["money_at_risk"] == "25.00"
    assert normalized["evidence_ids"] == ["evidence-001"]
    assert normalized["proposed_next_actions"] == ["request_supplier_credit"]
    assert normalized["fanout"][0]["plane"] == "fabriciq"
    assert normalized["fanout"][0]["output_quality"] == "valid"


def test_assurance_orchestrator_write_plan_rejects_multi_invoice_payload() -> None:
    payload = {
        "future_payloads": [
            {"invoice_id": "INV-2026-08034", "recommendation": {"decision": "recover"}},
            {"invoice_id": "INV-2026-08035", "recommendation": {"decision": "review"}},
        ]
    }

    try:
        _normalize_result_contract(payload)
    except ValueError as exc:
        assert "exactly one object" in str(exc)
    else:
        raise AssertionError("multi-invoice future_payloads should be rejected")


def test_assurance_orchestrator_future_payload_writes_through_fake_waypoint_clients() -> None:
    fake_writer = FakeWaypointWriteClient()
    payload = {
        "future_payloads": [
            {
                "invoice_id": "INV-2026-08034",
                "recommendation": {
                    "decision": "recover",
                    "reasoning": "Duplicate service charge.",
                    "confidence": 0.92,
                    "money_at_risk": "25.00",
                    "evidence_ids": ["evidence-001"],
                    "proposed_next_actions": ["request_supplier_credit"],
                },
            }
        ],
    }

    with patch("waypoint_write_tools.is_waypoint_configured", return_value=True), patch(
        "waypoint_write_tools.WaypointReadClient",
        return_value=FakeWaypointReadClient(),
    ), patch("waypoint_write_tools.WaypointWriteClient", return_value=fake_writer):
        result = json.loads(_waypoint_record_assurance_inner(json.dumps(payload)))

    assert result["ok"] is True
    assert result["decision"] == "recover"
    assert result["correlation"]["waypoint_case_id"] == "case-001"
    assert result["correlation"]["waypoint_run_id"] == "run-001"
    assert result["correlation"]["waypoint_recommendation_id"] == "recommendation-001"
    assert [name for name, _ in fake_writer.calls] == [
        "create_case",
        "open_run",
        "create_recommendation",
        "update_run",
    ]
    open_run_call = fake_writer.calls[1][1]
    assert open_run_call["status"] == "running"
    assert open_run_call["idempotency_key"].startswith("assurance:INV-2026-08034:")
    recommendation = fake_writer.calls[2][1]
    assert recommendation["decision"] == "recover"
    assert recommendation["evidence_ids"] == ["evidence-001", "evidence-002"]
    assert recommendation["proposed_next_actions"] == ["request_supplier_credit"]
    update_run_call = fake_writer.calls[3][1]
    assert update_run_call["run_id"] == "run-001"
    assert update_run_call["status"] == "completed"


def test_run_is_patched_to_failed_when_a_later_write_raises() -> None:
    class FailingWriter(FakeWaypointWriteClient):
        def create_recommendation(self, case_id: str, **kwargs) -> dict:
            self.calls.append(("create_recommendation", {"case_id": case_id, **kwargs}))
            raise RuntimeError("boom")

    fake_writer = FailingWriter()
    payload = {
        "invoice_id": "INV-2026-08034",
        "decision": "recover",
        "reasoning": "Duplicate service charge.",
    }

    with patch("waypoint_write_tools.is_waypoint_configured", return_value=True), patch(
        "waypoint_write_tools.WaypointReadClient",
        return_value=FakeWaypointReadClient(),
    ), patch("waypoint_write_tools.WaypointWriteClient", return_value=fake_writer):
        result = json.loads(_waypoint_record_assurance_inner(json.dumps(payload)))

    assert result["ok"] is False
    assert "boom" in result["error"]
    # The run was opened, so it must be advanced to "failed" rather than left running.
    assert [name for name, _ in fake_writer.calls] == [
        "create_case",
        "open_run",
        "create_recommendation",
        "update_run",
    ]
    failed_call = fake_writer.calls[3][1]
    assert failed_call["run_id"] == "run-001"
    assert failed_call["status"] == "failed"
    assert "boom" in failed_call["metadata"]["error"]


def _open_run_patches(fake_writer):
    return (
        patch("waypoint_write_tools.is_waypoint_configured", return_value=True),
        patch("waypoint_write_tools.WaypointWriteClient", return_value=fake_writer),
    )


def test_waypoint_open_run_opens_running_with_shared_keys() -> None:
    fake_writer = FakeWaypointWriteClient()
    cfg, writer = _open_run_patches(fake_writer)
    with cfg, writer:
        result = json.loads(_waypoint_open_run_inner("INV-2026-08034", "op-abc", "running"))

    assert result["ok"] is True
    assert result["status"] == "running"
    assert result["operation_id"] == "op-abc"
    assert result["correlation"]["waypoint_run_id"] == "run-001"
    assert result["correlation"]["waypoint_case_id"] == "case-001"
    assert [name for name, _ in fake_writer.calls] == ["open_assurance_run"]
    call = fake_writer.calls[0][1]
    assert call["invoice_ref"] == "INV-2026-08034"
    assert call["operation_id"] == "op-abc"
    assert call["status"] == "running"


def test_waypoint_open_run_normalizes_bad_status_and_generates_op() -> None:
    fake_writer = FakeWaypointWriteClient()
    cfg, writer = _open_run_patches(fake_writer)
    with cfg, writer:
        result = json.loads(_waypoint_open_run_inner("INV-2026-08034", "", "bogus"))

    # Unknown status collapses to "running"; an empty operation id is derived, not blank.
    assert result["status"] == "running"
    assert result["operation_id"]
    assert fake_writer.calls[0][1]["status"] == "running"
    assert fake_writer.calls[0][1]["operation_id"] == result["operation_id"]


def test_waypoint_open_run_requires_invoice_id() -> None:
    fake_writer = FakeWaypointWriteClient()
    cfg, writer = _open_run_patches(fake_writer)
    with cfg, writer:
        result = json.loads(_waypoint_open_run_inner("   ", "op-abc", "running"))
    assert result["ok"] is False
    assert "invoice_id is required" in result["error"]
    assert fake_writer.calls == []


def test_waypoint_fail_run_marks_failed_with_shared_keys() -> None:
    fake_writer = FakeWaypointWriteClient()
    cfg, writer = _open_run_patches(fake_writer)
    with cfg, writer:
        result = json.loads(_waypoint_fail_run_inner("INV-2026-08034", "op-abc", "expert timeout"))

    assert result["ok"] is True
    assert result["status"] == "failed"
    assert result["operation_id"] == "op-abc"
    assert result["reason"] == "expert timeout"
    assert result["correlation"]["waypoint_run_id"] == "run-001"
    assert result["correlation"]["waypoint_case_id"] == "case-001"
    # Reuses the SAME idempotency key as open_run (shared invoice_ref + operation_id),
    # so a failed finalize targets the run the early-open opened, not a new one.
    assert [name for name, _ in fake_writer.calls] == ["open_assurance_run"]
    call = fake_writer.calls[0][1]
    assert call["invoice_ref"] == "INV-2026-08034"
    assert call["operation_id"] == "op-abc"
    assert call["status"] == "failed"


def test_waypoint_fail_run_defaults_reason_and_operation_id() -> None:
    fake_writer = FakeWaypointWriteClient()
    cfg, writer = _open_run_patches(fake_writer)
    with cfg, writer:
        result = json.loads(_waypoint_fail_run_inner("INV-2026-08034", "", ""))

    assert result["status"] == "failed"
    assert result["operation_id"]  # derived, never blank
    assert result["reason"]  # a default reason is always recorded
    assert fake_writer.calls[0][1]["status"] == "failed"
    assert fake_writer.calls[0][1]["operation_id"] == result["operation_id"]


def test_waypoint_fail_run_requires_invoice_id() -> None:
    fake_writer = FakeWaypointWriteClient()
    cfg, writer = _open_run_patches(fake_writer)
    with cfg, writer:
        result = json.loads(_waypoint_fail_run_inner("   ", "op-abc", "reason"))
    assert result["ok"] is False
    assert "invoice_id is required" in result["error"]
    assert fake_writer.calls == []


def _real_client_with_captured_transport(
    *, config_op_id: str | None, post_status: str = "running"
) -> tuple[WaypointWriteClient, list[tuple[str, str, dict]]]:
    """Build a REAL WaypointWriteClient whose HTTP transport is captured, not sent.

    ``config_op_id`` seeds the env-sourced ``app_insights_operation_id`` (the prod hosted
    recorder leaves this null). ``post_status`` is what ``POST /api/runs`` echoes back as
    the run status, so a value != the requested status forces the status-advancing PATCH.
    """
    calls: list[tuple[str, str, dict]] = []
    config = WaypointWriteConfig(
        api_base_url="https://waypoint.test",
        api_scope=None,
        api_key=None,
        verify_ssl=True,
        agent_name="waypoint-recorder",
        app_insights_operation_id=config_op_id,
    )
    client = WaypointWriteClient(config=config)

    def fake_post(path: str, body: dict) -> dict:
        calls.append(("POST", path, body))
        if path == "/api/cases":
            return {"id": "case-001"}
        return {"id": "run-001", "status": post_status}

    def fake_patch(path: str, body: dict) -> dict:
        calls.append(("PATCH", path, body))
        return {"id": "run-001", "status": body.get("status")}

    client._post = fake_post  # type: ignore[assignment]
    client._patch = fake_patch  # type: ignore[assignment]
    return client, calls


def test_open_assurance_run_threads_operation_id_as_app_insights_id() -> None:
    # F2: the orchestrator's per-invoice operation id must ride onto the run at open time
    # as app_insights_operation_id, overriding the (null in prod) env-configured value.
    client, calls = _real_client_with_captured_transport(config_op_id=None)
    client.open_assurance_run("INV-2026-08034", operation_id="op-xyz")

    open_posts = [b for method, path, b in calls if method == "POST" and path == "/api/runs"]
    assert len(open_posts) == 1
    run_body = open_posts[0]
    assert run_body["app_insights_operation_id"] == "op-xyz"
    # The run name is the stable W2 reuse key (server-side reuse resolves duplicates to it).
    assert run_body["name"] == "assurance:INV-2026-08034"


def test_open_assurance_run_patch_carries_operation_id() -> None:
    # F2: when the idempotent re-open returns an existing run at a different status, the
    # status-advancing PATCH must ALSO carry the correlation id (so W3 can backfill from it).
    client, calls = _real_client_with_captured_transport(config_op_id=None, post_status="pending")
    client.open_assurance_run("INV-2026-08034", operation_id="op-xyz", status="running")

    patches = [b for method, path, b in calls if method == "PATCH"]
    assert len(patches) == 1
    assert patches[0]["status"] == "running"
    assert patches[0]["app_insights_operation_id"] == "op-xyz"


def test_open_assurance_run_stable_name_across_operation_ids() -> None:
    # F2: two SEPARATE turns for one invoice (different operation ids) both open with the
    # SAME run name, which is what lets Waypoint's server-side reuse (W2) converge them onto
    # one active run instead of minting a parallel one.
    client_a, calls_a = _real_client_with_captured_transport(config_op_id=None)
    client_a.open_assurance_run("INV-2026-08034", operation_id="op-turn-1")
    client_b, calls_b = _real_client_with_captured_transport(config_op_id=None)
    client_b.open_assurance_run("INV-2026-08034", operation_id="op-turn-2")

    name_a = next(b["name"] for m, p, b in calls_a if m == "POST" and p == "/api/runs")
    name_b = next(b["name"] for m, p, b in calls_b if m == "POST" and p == "/api/runs")
    assert name_a == name_b == "assurance:INV-2026-08034"
    # Distinct per-execution correlation ids still flow through (they are the idempotency +
    # app_insights ids); convergence is by name, not by collapsing the operation id.
    op_a = next(b["app_insights_operation_id"] for m, p, b in calls_a if m == "POST" and p == "/api/runs")
    op_b = next(b["app_insights_operation_id"] for m, p, b in calls_b if m == "POST" and p == "/api/runs")
    assert op_a == "op-turn-1"
    assert op_b == "op-turn-2"


def test_open_assurance_run_falls_back_to_env_operation_id() -> None:
    # Back-compat: when no operation id is threaded through open_run (None), the run still
    # carries the env-configured app_insights_operation_id rather than dropping correlation.
    client, calls = _real_client_with_captured_transport(config_op_id="env-op-id")
    client.open_run(name="assurance:INV-2026-08034", status="running")

    run_body = next(b for m, p, b in calls if m == "POST" and p == "/api/runs")
    assert run_body["app_insights_operation_id"] == "env-op-id"


def test_enroll_batch_opens_each_invoice_pending() -> None:
    fake_writer = FakeWaypointWriteClient()
    cfg, writer = _open_run_patches(fake_writer)
    invoices = [
        {"invoice_id": "INV-2026-08034", "operation_id": "op-1"},
        {"invoice_id": "INV-2026-08120", "operation_id": "op-2"},
    ]
    with cfg, writer:
        result = json.loads(waypoint_enroll_batch(json.dumps(invoices)))

    assert result["ok"] is True
    assert result["enrolled"] == 2
    opened = [c[1] for c in fake_writer.calls if c[0] == "open_assurance_run"]
    assert [o["invoice_ref"] for o in opened] == ["INV-2026-08034", "INV-2026-08120"]
    assert all(o["status"] == "pending" for o in opened)
    assert [o["operation_id"] for o in opened] == ["op-1", "op-2"]


def test_final_write_reuses_bundle_operation_id_for_shared_keys() -> None:
    fake_writer = FakeWaypointWriteClient()
    payload = {
        "invoice_id": "INV-2026-08034",
        "operation_id": "op-xyz",
        "decision": "recover",
        "reasoning": "Duplicate service charge.",
    }
    with patch("waypoint_write_tools.is_waypoint_configured", return_value=True), patch(
        "waypoint_write_tools.WaypointReadClient",
        return_value=FakeWaypointReadClient(),
    ), patch("waypoint_write_tools.WaypointWriteClient", return_value=fake_writer):
        result = json.loads(_waypoint_record_assurance_inner(json.dumps(payload)))

    assert result["ok"] is True
    calls = {name: kwargs for name, kwargs in fake_writer.calls}
    # The final write must key on the raw invoice_ref + the bundle operation id so the
    # case + run resolve to whatever the orchestrator opened early (no duplicates).
    assert calls["create_case"]["idempotency_key"] == "assurance-case:INV-2026-08034:op-xyz"
    assert calls["open_run"]["idempotency_key"] == "assurance:INV-2026-08034:op-xyz"


def test_missing_fanout_does_not_synthesize_expert_participation() -> None:
    grounding = {
        "findings": [{"contract_document_ids": ["contract-001"], "policy_ids": ["policy-001"]}],
        "evidence": [{"id": "email-001", "evidence_type": "email"}],
    }

    assert _normalize_fanout(None, grounding) == []


def test_normalize_fanout_rejects_pipeline_agent_masquerading_as_expert() -> None:
    fanout = _normalize_fanout(
        [
            {
                "agent": "contract-policy-expert",
                "plane": "foundryiq",
                "summary": "Contract clause governs the charge.",
                "evidence": [{"claim": "Clause 4.2 applies", "source_ref": "contract-001"}],
            },
            {
                "agent": "assurance-orchestrator",
                "plane": "workiq",
                "summary": "Deterministic line-math checks.",
                "evidence": [
                    {
                        "claim": "Line math matched.",
                        "source_ref": "deterministic_checks:INV-2026-08411:line_math",
                    }
                ],
            },
        ],
        {},
    )

    assert [lane["agent"] for lane in fanout] == ["contract-policy-expert"]


# ── deterministic policy-check (decision governance) ─────────────────────────


class HighSeverityReadClient(FakeWaypointReadClient):
    """Grounds the invoice on a high-severity / escalate finding (hero shape)."""

    def list_findings(self, invoice_id: str) -> list[dict]:
        return [
            {
                "id": "finding-inv-2026-08034",
                "category": "surge_capacity",
                "severity": "high",
                "status": "escalate",
                "summary": "Unauthorized surge capacity premium billed before approval.",
                "overpayment_amount": "118000.00",
                "evidence_ids": ["evidence-001"],
            }
        ]


class CleanReadClient(FakeWaypointReadClient):
    """Grounds the invoice on a clean, non-actionable finding."""

    def list_findings(self, invoice_id: str) -> list[dict]:
        return [
            {
                "id": "finding-clean",
                "category": "no_known_exception",
                "severity": "low",
                "status": "approved",
                "overpayment_amount": "0.00",
                "evidence_ids": [],
            }
        ]


class NoFindingsReadClient(FakeWaypointReadClient):
    def list_findings(self, invoice_id: str) -> list[dict]:
        return []

    def list_evidence(self, invoice_id: str) -> list[dict]:
        return []


def test_derive_decision_high_severity_escalates() -> None:
    decision, status = _derive_decision(
        [{"severity": "high", "status": "escalate", "overpayment_amount": "118000.00"}]
    )
    assert decision == "escalate"
    assert status == "escalated"


def test_derive_decision_overpayment_recovers() -> None:
    decision, status = _derive_decision(
        [{"severity": "medium", "status": "variance", "overpayment_amount": "25.00"}]
    )
    assert decision == "recover"
    assert status == "variance"


def test_derive_decision_review_status_holds_over_recover() -> None:
    """A curated ``status: review`` finding stays review even with money at risk."""
    decision, status = _derive_decision(
        [{"severity": "medium", "status": "review", "overpayment_amount": "11900.00"}]
    )
    assert decision == "review"
    assert status == "variance"


def test_derive_decision_high_severity_review_still_escalates() -> None:
    """The high/critical escalate rail wins over an explicit review disposition."""
    decision, status = _derive_decision(
        [{"severity": "high", "status": "review", "overpayment_amount": "11900.00"}]
    )
    assert decision == "escalate"
    assert status == "escalated"


def test_derive_decision_clean_finding_approves() -> None:
    decision, status = _derive_decision(
        [{"severity": "low", "status": "approved", "overpayment_amount": "0.00"}]
    )
    assert decision == "approve"
    assert status == "matched"


def test_govern_decision_no_findings_honours_model() -> None:
    decision, governance = _govern_decision([], "escalate")
    assert decision == "escalate"
    assert governance["source"] == "model"
    assert governance["overridden"] is False


def test_govern_decision_overrides_model_recover_to_escalate() -> None:
    findings = [{"severity": "high", "status": "escalate", "overpayment_amount": "118000.00"}]
    decision, governance = _govern_decision(findings, "recover")
    assert decision == "escalate"
    assert governance["source"] == "policy_override"
    assert governance["overridden"] is True
    assert governance["model_decision"] == "recover"


def test_high_severity_finding_forces_escalate_write() -> None:
    """The hero regression: model proposes recover, corpus says escalate -> escalate."""
    fake_writer = FakeWaypointWriteClient()
    payload = {
        "invoice_id": "INV-2026-08034",
        "decision": "recover",
        "reasoning": "Surge premium looks recoverable.",
        "confidence": 0.86,
        "money_at_risk": "118000.00",
    }

    with patch("waypoint_write_tools.is_waypoint_configured", return_value=True), patch(
        "waypoint_write_tools.WaypointReadClient",
        return_value=HighSeverityReadClient(),
    ), patch("waypoint_write_tools.WaypointWriteClient", return_value=fake_writer):
        result = json.loads(_waypoint_record_assurance_inner(json.dumps(payload)))

    assert result["ok"] is True
    assert result["decision"] == "escalate"
    recommendation = next(kwargs for name, kwargs in fake_writer.calls if name == "create_recommendation")
    assert recommendation["decision"] == "escalate"
    governance = recommendation["metadata"]["decision_governance"]
    assert governance["overridden"] is True
    assert governance["model_decision"] == "recover"
    assert governance["policy_decision"] == "escalate"


def test_no_findings_preserves_model_decision_write() -> None:
    fake_writer = FakeWaypointWriteClient()
    payload = {"invoice_id": "INV-2026-09999", "decision": "escalate", "reasoning": "Degraded run."}

    with patch("waypoint_write_tools.is_waypoint_configured", return_value=True), patch(
        "waypoint_write_tools.WaypointReadClient",
        return_value=NoFindingsReadClient(),
    ), patch("waypoint_write_tools.WaypointWriteClient", return_value=fake_writer):
        result = json.loads(_waypoint_record_assurance_inner(json.dumps(payload)))

    assert result["ok"] is True
    assert result["decision"] == "escalate"
    recommendation = next(kwargs for name, kwargs in fake_writer.calls if name == "create_recommendation")
    assert recommendation["metadata"]["decision_governance"]["source"] == "model"


def test_lane_is_grounded_requires_a_citation() -> None:
    # A lane with a summary but zero citations grounded on nothing (e.g. the market /
    # web lane when the public web has nothing on this supplier).
    empty_web_lane = {
        "agent": "market-evidence-expert",
        "plane": "webiq",
        "summary": "External corroboration; no contradicting public signal found.",
        "evidence": [],
    }
    assert _lane_is_grounded(empty_web_lane) is False

    grounded_web_lane = {
        "agent": "market-evidence-expert",
        "plane": "webiq",
        "summary": "Rush manufacturing premiums run 20-35% above base rate.",
        "evidence": [
            {"claim": "Surge premium benchmark", "source_ref": "https://example.com/rates"}
        ],
    }
    assert _lane_is_grounded(grounded_web_lane) is True

    # An evidence item with no source_ref is not a citation.
    uncited_lane = {"agent": "x", "plane": "webiq", "evidence": [{"claim": "hearsay"}]}
    assert _lane_is_grounded(uncited_lane) is False


def test_experts_consulted_excludes_ungrounded_web_lane() -> None:
    fake_writer = FakeWaypointWriteClient()
    payload = {
        "invoice_id": "INV-2026-08034",
        "decision": "review",
        "reasoning": "Mixed evidence.",
        "fanout": [
            {
                "agent": "contract-policy-expert",
                "plane": "foundryiq",
                "summary": "Contract clause governs the charge.",
                "evidence": [{"claim": "Clause 4.2 applies", "source_ref": "contract-001"}],
            },
            {
                "agent": "market-evidence-expert",
                "plane": "webiq",
                "summary": "No public signal found.",
                "evidence": [],
            },
        ],
    }

    with patch("waypoint_write_tools.is_waypoint_configured", return_value=True), patch(
        "waypoint_write_tools.WaypointReadClient",
        return_value=FakeWaypointReadClient(),
    ), patch("waypoint_write_tools.WaypointWriteClient", return_value=fake_writer):
        result = json.loads(_waypoint_record_assurance_inner(json.dumps(payload)))

    assert result["ok"] is True
    # The ungrounded market/web lane grounded on nothing, so it is NOT counted...
    assert result["correlation"]["experts_consulted"] == ["contract-policy-expert"]
    # ...but the full fan-out trail is preserved on the run for auditability.
    run_metadata = fake_writer.calls[1][1]["metadata"]
    assert len(run_metadata["fanout"]) == 2
    assert run_metadata["experts_consulted"] == ["contract-policy-expert"]



    test_direct_invoice_id()
    test_invoice_number_fallback()
    test_from_finding_id()
    test_from_evidence_ids()
    test_from_fanout_source_ref()
    test_from_reasoning_lowercase()
    test_no_reference_returns_empty()
    test_assurance_orchestrator_future_payload_normalizes_to_waypoint_recorder_contract()
    test_assurance_orchestrator_write_plan_rejects_multi_invoice_payload()
    test_assurance_orchestrator_future_payload_writes_through_fake_waypoint_clients()
    test_run_is_patched_to_failed_when_a_later_write_raises()
    test_waypoint_open_run_opens_running_with_shared_keys()
    test_waypoint_open_run_normalizes_bad_status_and_generates_op()
    test_waypoint_open_run_requires_invoice_id()
    test_waypoint_fail_run_marks_failed_with_shared_keys()
    test_waypoint_fail_run_defaults_reason_and_operation_id()
    test_waypoint_fail_run_requires_invoice_id()
    test_open_assurance_run_threads_operation_id_as_app_insights_id()
    test_open_assurance_run_patch_carries_operation_id()
    test_open_assurance_run_stable_name_across_operation_ids()
    test_open_assurance_run_falls_back_to_env_operation_id()
    test_enroll_batch_opens_each_invoice_pending()
    test_final_write_reuses_bundle_operation_id_for_shared_keys()
    test_missing_fanout_does_not_synthesize_expert_participation()
    test_normalize_fanout_rejects_pipeline_agent_masquerading_as_expert()
    test_derive_decision_high_severity_escalates()
    test_derive_decision_overpayment_recovers()
    test_derive_decision_review_status_holds_over_recover()
    test_derive_decision_high_severity_review_still_escalates()
    test_derive_decision_clean_finding_approves()
    test_govern_decision_no_findings_honours_model()
    test_govern_decision_overrides_model_recover_to_escalate()
    test_high_severity_finding_forces_escalate_write()
    test_no_findings_preserves_model_decision_write()
    test_lane_is_grounded_requires_a_citation()
    test_experts_consulted_excludes_ungrounded_web_lane()
    print("all recovery tests passed")
