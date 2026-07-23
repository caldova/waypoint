"""Unit tests for the AssuranceOrchestrator read-only workflow.

Run with:

    cd agents/assurance_orchestrator
    python scripts/test_assurance_workflow.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Callable
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from assurance_workflow import (
    AssuranceOrchestratorRunConstraints,
    ContentUnderstandingClient,
    ContentUnderstandingConfig,
    DEFAULT_MAX_RUNTIME_MINUTES,
    RetryPolicy,
    ToolboxExpertClient,
    _content_understanding_summary_payload,
    _default_max_runtime_minutes,
    normalize_workflow_request,
    run_assurance_orchestrator_invoice_assurance,
    run_assurance_orchestrator_invoice_assurance_async,
    resolve_documents,
    WorkTarget,
    _toolbox_endpoint,
)
from waypoint_tools import assurance_orchestrator_run_invoice_assurance_workflow

NO_LIVE_EXPERT_ENV = {
    "WORKIQ_EXPERT_ENDPOINT": "",
    "WEBIQ_EXPERT_ENDPOINT": "",
    "FOUNDRYIQ_EXPERT_ENDPOINT": "",
    "FABRICIQ_EXPERT_ENDPOINT": "",
    "TOOLBOX_ENDPOINT": "",
    "TOOLBOX_MCP_ENDPOINT": "",
    "CONTENT_UNDERSTANDING_ENDPOINT": "",
    "ASSURANCE_ORCHESTRATOR_EXPERT_INVOCATION_MODE": "",
    "ASSURANCE_ORCHESTRATOR_EXPERT_PROJECT_ENDPOINT": "",
    "ASSURANCE_ORCHESTRATOR_EXPERT_MODEL": "",
    "COLLABORATION_EVIDENCE_EXPERT_AGENT_NAME": "",
    "MARKET_EVIDENCE_EXPERT_AGENT_NAME": "",
    "CONTRACT_POLICY_EXPERT_AGENT_NAME": "",
    "OPERATIONS_DATA_EXPERT_AGENT_NAME": "",
}


def without_live_expert_env():
    return patch.dict("os.environ", NO_LIVE_EXPERT_ENV, clear=False)


class FakeWaypointClient:
    def __init__(self, fail_context_once: bool = False, invoice_findings: Any = None) -> None:
        self.fail_context_once = fail_context_once
        self.invoice_findings = invoice_findings
        self.context_calls = 0

    def get_work(self) -> list[dict[str, Any]]:
        return [
            {
                "invoice_id": "inv-001",
                "finding_id": "finding-001",
                "case_id": "case-001",
                "summary": "Unauthorized capacity premium requires review.",
            }
        ]

    def get_action_types(self) -> list[dict[str, Any]]:
        return [{"id": "recommend_review"}, {"id": "escalate_quality"}]

    def get_runs(self) -> list[dict[str, Any]]:
        return []

    def get_invoice_context(self, invoice_id: str) -> dict[str, Any]:
        self.context_calls += 1
        if self.fail_context_once and self.context_calls == 1:
            raise RuntimeError("transient context failure")
        return {
            "invoice": {
                "id": invoice_id,
                "invoice_number": "INV-001",
                "total_amount": "125.00",
                "lines": [{"amount": "100.00"}],
                "findings": self.invoice_findings
                if self.invoice_findings is not None
                else [
                    {
                        "id": "finding-001",
                        "severity": "high",
                        "category": "surge_capacity",
                        "summary": "Capacity premium was billed before approval.",
                        "overpayment_amount": "25.00",
                        "basis_summary": "Capacity fees require written approval.",
                        "evidence_ids": ["ev-001"],
                    }
                ],
                "evidence": [
                    {
                        "id": "ev-001",
                        "evidence_type": "approval",
                        "excerpt": "Approval is pending.",
                    }
                ],
            },
            "findings": [
                {
                    "id": "top-level-finding",
                    "severity": "critical",
                    "summary": "Should not replace an explicit empty invoice findings list.",
                }
            ],
            "contract_documents": [{"id": "contract-001"}],
            "policies": [{"id": "policy-invoice-reconciliation"}],
            "allowed_actions": [{"id": "escalate_quality"}, {"id": "recommend_review"}],
        }

    def get_invoice(self, invoice_id: str) -> dict[str, Any]:
        return {"id": invoice_id}

    def get_findings(self, invoice_id: str | None = None) -> list[dict[str, Any]]:
        return []

    def get_evidence(
        self,
        invoice_id: str | None = None,
        finding_id: str | None = None,
    ) -> list[dict[str, Any]]:
        return []


class MatchedMathWaypointClient(FakeWaypointClient):
    """Waypoint fake whose invoice line math reconciles (total == sum of lines).

    Decisions are then driven purely by the supplied findings, so tests can
    assert the approve/review/escalate mapping without a deterministic math
    variance masking the result.
    """

    def get_invoice_context(self, invoice_id: str) -> dict[str, Any]:
        return {
            "invoice": {
                "id": invoice_id,
                "invoice_number": "INV-CLEAN",
                "total_amount": "100.00",
                "lines": [{"amount": "100.00"}],
                "findings": self.invoice_findings if self.invoice_findings is not None else [],
                "evidence": [],
            },
            "contract_documents": [{"id": "contract-001"}],
            "policies": [{"id": "policy-invoice-reconciliation"}],
            "allowed_actions": [{"id": "escalate_quality"}, {"id": "recommend_review"}],
        }


class FakeExpertClient:
    def __init__(
        self,
        payload_factory: Callable[[str, dict[str, Any]], dict[str, Any]] | None = None,
    ) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self._payload_factory = payload_factory

    async def resolve_tool_name(self, validator_id: str) -> str | None:
        return f"{validator_id}_validate"

    async def call_validator(self, validator_id: str, arguments: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((validator_id, arguments))
        if self._payload_factory is not None:
            return self._payload_factory(validator_id, arguments)
        return {
            "structuredContent": {
                "status": "completed",
                "summary": f"{validator_id} live validation completed.",
                "confidence": 0.91,
                "findings": [
                    {
                        "invoice_id": arguments["targets"][0]["invoice_id"],
                        "category": validator_id,
                        "summary": "Live expert signal was incorporated.",
                    }
                ],
                "evidence_ids": [f"{validator_id}-ev-001"],
                "citations": [{"title": f"{validator_id} citation", "url": "https://example.test"}],
                "trace_id": f"trace-{validator_id}",
            }
        }


class FakeContentUnderstandingClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def analyze_invoice_pdf(
        self,
        *,
        pdf_uri: str | None = None,
        pdf_base64: str | None = None,
    ) -> dict[str, Any]:
        self.calls.append({"pdf_uri": pdf_uri, "pdf_base64": pdf_base64})
        return {
            "status": "Succeeded",
            "result": {
                "analyzerId": "prebuilt-invoice",
                "contents": [
                    {
                        "fields": {
                            "InvoiceId": {"valueString": "INV-001"},
                            "InvoiceTotal": {
                                "valueCurrency": {
                                    "amount": 125.0,
                                    "currencyCode": "USD",
                                }
                            },
                        }
                    }
                ],
            },
        }


class FakeContentUnderstandingResponse:
    def __init__(
        self,
        status_code: int,
        payload: dict[str, Any],
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status_code = status_code
        self._payload = payload
        self.headers = headers or {}
        self.text = str(payload)

    @property
    def is_error(self) -> bool:
        return self.status_code >= 400

    def json(self) -> dict[str, Any]:
        return self._payload


class FakeContentUnderstandingHttpClient:
    calls: list[dict[str, Any]] = []

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.args = args
        self.kwargs = kwargs

    async def __aenter__(self) -> "FakeContentUnderstandingHttpClient":
        return self

    async def __aexit__(self, *args: Any) -> None:
        return None

    async def post(self, url: str, **kwargs: Any) -> FakeContentUnderstandingResponse:
        self.calls.append({"url": url, **kwargs})
        return FakeContentUnderstandingResponse(
            202,
            {"status": "Running"},
            headers={"Operation-Location": "https://example.test/operation"},
        )

    async def get(self, url: str, **kwargs: Any) -> FakeContentUnderstandingResponse:
        return FakeContentUnderstandingResponse(
            200,
            {
                "status": "Succeeded",
                "result": {"analyzerId": "prebuilt-invoice", "contents": []},
            },
        )


class AssuranceOrchestratorWorkflowTests(unittest.TestCase):
    def test_normalizes_wrapped_run_manifest(self) -> None:
        request = normalize_workflow_request(
            {
                "assurance_orchestrator_request": {
                    "mode": "run",
                    "request_type": "invoice_assurance",
                    "items": [{"invoice_id": "inv-123", "pdf_uri": "https://example.test/inv.pdf"}],
                }
            }
        )

        self.assertEqual(request.mode, "run")
        self.assertEqual(request.items[0].invoice_id, "inv-123")
        self.assertEqual(request.items[0].pdf_uri, "https://example.test/inv.pdf")
        self.assertTrue(request.constraints.read_only)
        self.assertEqual(request.constraints.allowed_write_phase, "none")

    def test_normalizes_inline_pdf_base64(self) -> None:
        request = normalize_workflow_request(
            {
                "invoice_id": "inv-123",
                "pdf_base64": "data:application/pdf;base64,JVBERi0xLjQ=",
            }
        )

        self.assertEqual(request.items[0].pdf_base64, "JVBERi0xLjQ=")

    def test_rejects_invalid_inline_pdf_base64(self) -> None:
        with self.assertRaisesRegex(ValueError, "valid base64"):
            normalize_workflow_request({"invoice_id": "inv-123", "pdf_base64": "not-base64!"})

    def test_resolve_documents_invokes_content_understanding_for_url(self) -> None:
        fake_cu = FakeContentUnderstandingClient()
        with patch("assurance_workflow._content_understanding_client", return_value=fake_cu):
            documents = asyncio.run(
                resolve_documents(
                    [
                        WorkTarget(
                            invoice_id="inv-123",
                            finding_id=None,
                            waypoint_case_id=None,
                            summary=None,
                            pdf_uri="https://example.test/inv.pdf",
                        )
                    ]
                )
            )

        self.assertEqual(fake_cu.calls[0]["pdf_uri"], "https://example.test/inv.pdf")
        self.assertEqual(documents[0]["content_understanding_status"], "succeeded")
        self.assertIn("InvoiceId", documents[0]["analyzer_result"]["fields"])

    def test_resolve_documents_invokes_content_understanding_for_base64(self) -> None:
        fake_cu = FakeContentUnderstandingClient()
        with patch("assurance_workflow._content_understanding_client", return_value=fake_cu):
            documents = asyncio.run(
                resolve_documents(
                    [
                        WorkTarget(
                            invoice_id="inv-123",
                            finding_id=None,
                            waypoint_case_id=None,
                            summary=None,
                            pdf_base64="JVBERi0xLjQ=",
                        )
                    ]
                )
            )

        self.assertEqual(fake_cu.calls[0]["pdf_base64"], "JVBERi0xLjQ=")
        self.assertTrue(documents[0]["pdf_base64_present"])
        self.assertEqual(documents[0]["content_understanding_status"], "succeeded")

    def test_content_understanding_base64_uses_binary_endpoint(self) -> None:
        FakeContentUnderstandingHttpClient.calls = []
        config = ContentUnderstandingConfig(
            endpoint="https://example.test",
            api_version="2025-11-01",
            analyzer_id="prebuilt-invoice",
            scope="https://cognitiveservices.azure.com/.default",
            timeout_seconds=5.0,
            poll_interval_seconds=0.0,
            max_polls=1,
        )
        client = ContentUnderstandingClient(config=config, credential=object())

        with (
            patch(
                "assurance_workflow.get_bearer_token_provider",
                return_value=lambda: "token",
            ),
            patch(
                "assurance_workflow.httpx.AsyncClient",
                FakeContentUnderstandingHttpClient,
            ),
        ):
            asyncio.run(client.analyze_invoice_pdf(pdf_base64="JVBERi0xLjQ="))

        call = FakeContentUnderstandingHttpClient.calls[0]
        self.assertTrue(call["url"].endswith("/prebuilt-invoice:analyzeBinary"))
        self.assertEqual(call["headers"]["Content-Type"], "application/pdf")
        self.assertEqual(call["content"], b"%PDF-1.4")

    def test_content_understanding_summary_preserves_error_details(self) -> None:
        summary = _content_understanding_summary_payload(
            {
                "status": "Failed",
                "error": {
                    "code": "InvalidRequest",
                    "message": "Invalid Request.",
                    "innererror": {
                        "code": "ResourceError",
                        "message": "Configure defaults first.",
                    },
                },
                "result": {"analyzerId": "prebuilt-invoice", "contents": []},
            }
        )

        self.assertEqual(summary["status"], "Failed")
        self.assertEqual(summary["error"]["innererror"]["code"], "ResourceError")

    def test_workflow_fans_out_and_prepares_read_only_write_plan(self) -> None:
        with without_live_expert_env():
            result = run_assurance_orchestrator_invoice_assurance(
                {"invoice_id": "inv-001", "waypoint_case_id": "case-001"},
                client=FakeWaypointClient(),
            )

        self.assertEqual(result["status"], "completed")
        self.assertFalse(result["side_effects_performed"])
        self.assertEqual(result["targets"][0]["invoice_id"], "inv-001")
        self.assertEqual(
            {validator["validator_id"] for validator in result["validators"]},
            {"webiq", "fabriciq", "workiq", "foundryiq"},
        )
        self.assertEqual(
            {validator["execution_path"] for validator in result["validators"]},
            {"placeholder"},
        )
        self.assertEqual(result["auth_context"]["toolbox_endpoint_configured"], False)
        self.assertEqual(result["judgements"][0]["status"], "escalated")
        self.assertEqual(result["judgements"][0]["money_at_risk"], "25.00")
        self.assertTrue(result["write_plan"]["read_only"])
        self.assertEqual(result["write_plan"]["post_operations_prepared"], [])
        self.assertIn(
            "POST /api/cases/{case_id}/recommendations",
            result["write_plan"]["prohibited_operations"],
        )

    def test_workflow_journal_writes_redacted_json_checkpoints(self) -> None:
        pdf_base64 = "JVBERi0xLjQ="
        with tempfile.TemporaryDirectory() as journal_root:
            with without_live_expert_env(), patch.dict(
                "os.environ",
                {"ASSURANCE_ORCHESTRATOR_RUN_JOURNAL_DIR": journal_root},
                clear=False,
            ):
                result = run_assurance_orchestrator_invoice_assurance(
                    {"invoice_id": "inv-001", "pdf_base64": pdf_base64},
                    client=FakeWaypointClient(),
                )

            journal = result["journal"]
            self.assertTrue(journal["enabled"])
            run_dir = Path(journal["run_dir"])
            self.assertTrue(run_dir.is_dir())
            self.assertTrue((run_dir / "latest.json").exists())
            self.assertGreaterEqual(len(list(run_dir.glob("*.json"))), 8)

            completed = json.loads((run_dir / "latest.json").read_text(encoding="utf-8"))
            completed_text = json.dumps(completed)
            self.assertEqual(completed["label"], "completed")
            self.assertNotIn(pdf_base64, completed_text)
            self.assertIn("<redacted:pdf_base64>", completed_text)

    def test_step_retry_recovers_from_transient_context_failure(self) -> None:
        client = FakeWaypointClient(fail_context_once=True)
        with without_live_expert_env():
            result = run_assurance_orchestrator_invoice_assurance(
                {"invoice_id": "inv-001"},
                client=client,
                retry_policy=RetryPolicy(max_attempts=2, backoff_seconds=0),
            )

        resolve_context_steps = [
            step for step in result["steps"] if step["name"] == "resolve_context"
        ]
        self.assertEqual(resolve_context_steps[0]["attempts"], 2)
        self.assertEqual(resolve_context_steps[0]["status"], "completed")
        self.assertEqual(client.context_calls, 2)

    def test_explicit_empty_invoice_findings_do_not_fall_back_to_context_findings(self) -> None:
        with without_live_expert_env():
            result = run_assurance_orchestrator_invoice_assurance(
                {"invoice_id": "inv-001"},
                client=FakeWaypointClient(invoice_findings=[]),
            )

        self.assertEqual(result["invoice_contexts"][0]["findings"], [])
        self.assertEqual(result["judgements"][0]["status"], "variance")
        self.assertNotEqual(result["judgements"][0]["severity"], "critical")

    def test_clean_approved_finding_yields_approve_decision(self) -> None:
        approved_finding = [
            {
                "id": "finding-approved",
                "severity": "low",
                "status": "approved",
                "category": "reconciled",
                "summary": "Invoice reconciled with no overpayment.",
                "overpayment_amount": "0",
            }
        ]
        with without_live_expert_env():
            result = run_assurance_orchestrator_invoice_assurance(
                {"invoice_id": "inv-001"},
                client=MatchedMathWaypointClient(invoice_findings=approved_finding),
            )

        judgement = result["judgements"][0]
        self.assertEqual(judgement["status"], "matched")
        self.assertEqual(judgement["waypoint_decision"], "approve")
        self.assertEqual(judgement["money_at_risk"], "0")

    def test_real_high_severity_finding_still_escalates(self) -> None:
        high_finding = [
            {
                "id": "finding-high",
                "severity": "high",
                "category": "surge_capacity",
                "summary": "Capacity premium billed before approval.",
                "overpayment_amount": "40.00",
            }
        ]
        with without_live_expert_env():
            result = run_assurance_orchestrator_invoice_assurance(
                {"invoice_id": "inv-001"},
                client=MatchedMathWaypointClient(invoice_findings=high_finding),
            )

        judgement = result["judgements"][0]
        self.assertEqual(judgement["status"], "escalated")
        self.assertEqual(judgement["waypoint_decision"], "escalate")
        self.assertEqual(judgement["money_at_risk"], "40.00")

    def test_real_low_severity_finding_with_overpayment_yields_review(self) -> None:
        review_finding = [
            {
                "id": "finding-review",
                "severity": "low",
                "category": "rate_variance",
                "summary": "Minor rate variance requires review.",
                "overpayment_amount": "12.00",
            }
        ]
        with without_live_expert_env():
            result = run_assurance_orchestrator_invoice_assurance(
                {"invoice_id": "inv-001"},
                client=MatchedMathWaypointClient(invoice_findings=review_finding),
            )

        judgement = result["judgements"][0]
        self.assertEqual(judgement["status"], "variance")
        self.assertEqual(judgement["waypoint_decision"], "review")
        self.assertEqual(judgement["money_at_risk"], "12.00")

    def test_invalid_request_json_gets_actionable_error(self) -> None:
        with self.assertRaisesRegex(ValueError, "request_json is not valid JSON"):
            normalize_workflow_request("{not json")

    def test_max_runtime_budget_raises_timeout_and_journals_failed(self) -> None:
        class SlowExpertClient:
            async def resolve_tool_name(self, validator_id: str) -> str:
                return f"{validator_id}_validate"

            async def call_validator(self, validator_id: str, arguments: dict[str, Any]) -> dict[str, Any]:
                await asyncio.sleep(5)  # far exceeds the tiny budget below
                return {"structuredContent": {"status": "completed", "summary": "late"}}

        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict("os.environ", {"ASSURANCE_ORCHESTRATOR_RUN_JOURNAL_DIR": tmp}, clear=False):
                with self.assertRaises(TimeoutError):
                    asyncio.run(
                        run_assurance_orchestrator_invoice_assurance_async(
                            {"invoice_id": "inv-001"},
                            client=FakeWaypointClient(),
                            expert_client=SlowExpertClient(),
                            max_runtime_seconds=0.05,
                        )
                    )
            # The timeout is journaled as a terminal "failed" stage so a caller can finalize the run.
            failed = [p for p in Path(tmp).rglob("*.json") if "failed" in p.read_text(encoding="utf-8")]
            self.assertTrue(failed, "expected a journaled failed stage on timeout")

    def test_workflow_singleton_recovers_after_a_timeout(self) -> None:
        """A timed-out run must not wedge the shared @workflow singleton at is_running=True."""

        class SlowExpertClient:
            async def resolve_tool_name(self, validator_id: str) -> str:
                return f"{validator_id}_validate"

            async def call_validator(self, validator_id: str, arguments: dict[str, Any]) -> dict[str, Any]:
                await asyncio.sleep(5)
                return {"structuredContent": {"status": "completed", "summary": "late"}}

        with self.assertRaises(TimeoutError):
            run_assurance_orchestrator_invoice_assurance(
                {"invoice_id": "inv-001"},
                client=FakeWaypointClient(),
                expert_client=SlowExpertClient(),
                max_runtime_seconds=0.05,
            )

        # The very next run on the same process/singleton must succeed, not raise
        # "Workflow is already running".
        result = run_assurance_orchestrator_invoice_assurance(
            {"invoice_id": "inv-001"},
            client=FakeWaypointClient(),
            expert_client=FakeExpertClient(),
        )
        self.assertEqual(result["status"], "completed")

    def test_live_expert_client_results_are_normalized_with_auth_metadata(self) -> None:
        expert_client = FakeExpertClient()
        result = run_assurance_orchestrator_invoice_assurance(
            {"invoice_id": "inv-001"},
            client=FakeWaypointClient(),
            expert_client=expert_client,
        )

        self.assertEqual(
            [validator_id for validator_id, _ in expert_client.calls],
            ["webiq", "fabriciq", "workiq", "foundryiq"],
        )
        validators = {validator["validator_id"]: validator for validator in result["validators"]}
        self.assertEqual(validators["workiq"]["auth_mode"], "delegated_obo")
        self.assertEqual(validators["foundryiq"]["auth_mode"], "agent_identity")
        self.assertEqual(validators["fabriciq"]["execution_path"], "foundry_toolbox")
        self.assertEqual(validators["webiq"]["citations"][0]["title"], "webiq citation")
        self.assertEqual(validators["foundryiq"]["raw_reference"], "trace-foundryiq")
        self.assertEqual(
            "expert_evidence" in expert_client.calls[0][1]["instructions"],
            True,
        )
        expert_evidence = result["write_plan"]["future_payloads"][0]["recommendation"]["metadata"]["expert_evidence"]
        metadata = result["write_plan"]["future_payloads"][0]["recommendation"]["metadata"]
        self.assertEqual(metadata["confidence_basis"], "expert_evidence_mean")
        self.assertIs(metadata["confidence_calibrated"], False)
        self.assertEqual(
            {lane["plane"] for lane in expert_evidence},
            {"webiq", "fabriciq", "workiq", "foundryiq"},
        )
        self.assertEqual(
            {lane["agent"] for lane in expert_evidence},
            {
                "market-evidence-expert",
                "operations-data-expert",
                "collaboration-evidence-expert",
                "contract-policy-expert",
            },
        )
        self.assertTrue(any(lane["evidence"] for lane in expert_evidence))

    def test_expert_evidence_is_normalized_into_validator_findings(self) -> None:
        def payload(validator_id: str, arguments: dict[str, Any]) -> dict[str, Any]:
            return {
                "structuredContent": {
                    "status": "completed",
                    "summary": f"{validator_id} returned repairable expert evidence.",
                    "invoice_id": arguments["targets"][0]["invoice_id"],
                    "expert_evidence": [
                        {
                            "claim": "Approval email confirms the capacity exception.",
                            "source_refs": ["email-approval-001"],
                            "classification": "approval",
                            "confidence": 0.9,
                        }
                    ],
                    "confidence": 0.9,
                }
            }

        result = run_assurance_orchestrator_invoice_assurance(
            {"invoice_id": "inv-001"},
            client=FakeWaypointClient(),
            expert_client=FakeExpertClient(payload),
        )

        validators = {validator["validator_id"]: validator for validator in result["validators"]}
        workiq = validators["workiq"]
        self.assertEqual(workiq["status"], "completed")
        self.assertEqual(workiq["output_quality"], "valid")
        self.assertIn("email-approval-001", workiq["evidence_ids"])
        self.assertEqual(
            workiq["findings"][0]["summary"],
            "Approval email confirms the capacity exception.",
        )
        self.assertEqual(workiq["findings"][0]["classification"], "approval")

    def test_malformed_expert_text_is_marked_partial_without_breaking_workflow(self) -> None:
        def payload(validator_id: str, arguments: dict[str, Any]) -> dict[str, Any]:
            del validator_id, arguments
            return {"content": [{"type": "text", "text": "not json"}]}

        result = run_assurance_orchestrator_invoice_assurance(
            {"invoice_id": "inv-001"},
            client=FakeWaypointClient(),
            expert_client=FakeExpertClient(payload),
        )

        validators = {validator["validator_id"]: validator for validator in result["validators"]}
        self.assertEqual(result["status"], "completed")
        self.assertEqual(validators["webiq"]["status"], "partial")
        self.assertEqual(validators["webiq"]["output_quality"], "malformed")
        self.assertEqual(validators["webiq"]["findings"], [])

    def test_no_evidence_expert_output_is_marked_partial_with_unsupported_context(self) -> None:
        def payload(validator_id: str, arguments: dict[str, Any]) -> dict[str, Any]:
            del arguments
            return {
                "structuredContent": {
                    "status": "completed",
                    "summary": f"{validator_id} found no source-grounded evidence.",
                    "expert_evidence": [],
                    "unsupported": ["No live source was configured for this scenario."],
                }
            }

        result = run_assurance_orchestrator_invoice_assurance(
            {"invoice_id": "inv-001"},
            client=FakeWaypointClient(),
            expert_client=FakeExpertClient(payload),
        )

        validators = {validator["validator_id"]: validator for validator in result["validators"]}
        self.assertEqual(validators["fabriciq"]["status"], "partial")
        self.assertEqual(validators["fabriciq"]["output_quality"], "no_evidence")
        self.assertEqual(
            validators["fabriciq"]["unsupported"],
            ["No live source was configured for this scenario."],
        )

    def test_configured_responses_experts_are_used_by_default_workflow(self) -> None:
        prompts: list[tuple[str, str]] = []

        def fake_run(agent_client, prompt: str) -> str:
            prompts.append((agent_client._endpoint.name, prompt))
            return __import__("json").dumps(
                {
                    "agent": f"{agent_client._endpoint.name}-expert",
                    "plane": agent_client._endpoint.name,
                    "invoice_id": "inv-001",
                    "evidence": [
                        {
                            "claim": f"{agent_client._endpoint.name} evidence was gathered.",
                            "supports": "review",
                            "source_ref": f"{agent_client._endpoint.name}-source-001",
                            "classification": "standard",
                            "confidence": 0.82,
                        }
                    ],
                    "summary": f"{agent_client._endpoint.name} expert completed.",
                }
            )

        with patch.dict(
            "os.environ",
            {
                "WORKIQ_EXPERT_ENDPOINT": "http://localhost:8091",
                "WEBIQ_EXPERT_ENDPOINT": "http://localhost:8092",
                "FOUNDRYIQ_EXPERT_ENDPOINT": "http://localhost:8093",
                "FABRICIQ_EXPERT_ENDPOINT": "http://localhost:8094",
            },
            clear=False,
        ), patch("expert_clients._ResponsesAgentClient.run", fake_run):
            result = run_assurance_orchestrator_invoice_assurance(
                {"invoice_id": "inv-001"},
                client=FakeWaypointClient(),
            )

        self.assertCountEqual(
            [name for name, _ in prompts],
            ["webiq", "fabriciq", "workiq", "foundryiq"],
        )
        for _, prompt in prompts:
            self.assertIn("deterministic_checks", prompt)
        validators = {validator["validator_id"]: validator for validator in result["validators"]}
        self.assertEqual(
            {validator["execution_path"] for validator in validators.values()},
            {"responses_agent"},
        )
        self.assertEqual(validators["workiq"]["toolbox_tool_name"], "workiq-expert.responses")
        self.assertIn("workiq-source-001", validators["workiq"]["evidence_ids"])
        self.assertEqual(validators["webiq"]["confidence"], 0.82)

    def test_prompt_experts_are_used_when_enabled(self) -> None:
        prompts: list[tuple[str, str, str]] = []

        def fake_invoke(client, spec, prompt: str) -> str:
            prompts.append((spec.validator_id, spec.agent_name, prompt))
            return json.dumps(
                {
                    "agent": spec.agent_name,
                    "plane": spec.validator_id,
                    "invoice_id": "inv-001",
                    "evidence": [
                        {
                            "claim": f"{spec.agent_name} prompt evidence was gathered.",
                            "supports": "review",
                            "source_ref": f"{spec.agent_name}-source-001",
                            "classification": "standard",
                            "confidence": 0.86,
                        }
                    ],
                    "summary": f"{spec.agent_name} prompt expert completed.",
                }
            )

        with patch.dict(
            "os.environ",
            {
                **NO_LIVE_EXPERT_ENV,
                "ASSURANCE_ORCHESTRATOR_EXPERT_INVOCATION_MODE": "prompt",
                "ASSURANCE_ORCHESTRATOR_EXPERT_PROJECT_ENDPOINT": "https://example.services.ai.azure.com/api/projects/forge",
                "ASSURANCE_ORCHESTRATOR_EXPERT_MODEL": "gpt-5.5",
                "COLLABORATION_EVIDENCE_EXPERT_AGENT_NAME": "collaboration-evidence-expert-prompt-canary",
                "MARKET_EVIDENCE_EXPERT_AGENT_NAME": "market-evidence-expert-prompt-canary",
                "CONTRACT_POLICY_EXPERT_AGENT_NAME": "contract-policy-expert-prompt-canary",
                "OPERATIONS_DATA_EXPERT_AGENT_NAME": "operations-data-expert-prompt-canary",
            },
            clear=False,
        ), patch("expert_clients.FoundryPromptExpertClient._invoke_prompt_expert", fake_invoke):
            result = run_assurance_orchestrator_invoice_assurance(
                {"invoice_id": "inv-001"},
                client=FakeWaypointClient(),
            )

        self.assertCountEqual(
            [(validator_id, agent_name) for validator_id, agent_name, _ in prompts],
            [
                ("webiq", "market-evidence-expert-prompt-canary"),
                ("fabriciq", "operations-data-expert-prompt-canary"),
                ("workiq", "collaboration-evidence-expert-prompt-canary"),
                ("foundryiq", "contract-policy-expert-prompt-canary"),
            ],
        )
        for _, _, prompt in prompts:
            self.assertIn("Context JSON:", prompt)
        validators = {validator["validator_id"]: validator for validator in result["validators"]}
        self.assertEqual(
            {validator["execution_path"] for validator in validators.values()},
            {"foundry_prompt_agent"},
        )
        self.assertEqual(
            validators["workiq"]["toolbox_tool_name"],
            "collaboration-evidence-expert-prompt-canary.agent_reference",
        )
        self.assertIn("collaboration-evidence-expert-prompt-canary-source-001", validators["workiq"]["evidence_ids"])
        self.assertEqual(validators["foundryiq"]["confidence"], 0.86)

    def test_prompt_experts_resolve_from_env_without_repo_prompt_files(self) -> None:
        import expert_clients

        missing_paths = {
            validator_id: Path("/container-only") / validator_id / "prompt.md"
            for validator_id in expert_clients.PROMPT_EXPERT_PATHS
        }
        with patch.dict(
            "os.environ",
            {
                **NO_LIVE_EXPERT_ENV,
                "ASSURANCE_ORCHESTRATOR_EXPERT_INVOCATION_MODE": "prompt",
                "ASSURANCE_ORCHESTRATOR_EXPERT_PROJECT_ENDPOINT": "https://example.services.ai.azure.com/api/projects/forge",
                "ASSURANCE_ORCHESTRATOR_EXPERT_MODEL": "gpt-5.5",
                "COLLABORATION_EVIDENCE_EXPERT_AGENT_NAME": "collaboration-evidence-expert",
                "MARKET_EVIDENCE_EXPERT_AGENT_NAME": "market-evidence-expert",
                "CONTRACT_POLICY_EXPERT_AGENT_NAME": "contract-policy-expert",
                "OPERATIONS_DATA_EXPERT_AGENT_NAME": "operations-data-expert",
            },
            clear=False,
        ), patch.dict("expert_clients.PROMPT_EXPERT_PATHS", missing_paths, clear=True):
            client = expert_clients.FoundryPromptExpertClient.from_env()
            self.assertIsNotNone(client)
            specs = client._resolve_spec("workiq")

        self.assertEqual(specs.agent_name, "collaboration-evidence-expert")
        self.assertEqual(specs.model, "gpt-5.5")

    def test_partially_configured_responses_experts_fall_back_per_validator(self) -> None:
        def fake_run(agent_client, prompt: str) -> str:
            return __import__("json").dumps(
                {
                    "agent": f"{agent_client._endpoint.name}-expert",
                    "plane": agent_client._endpoint.name,
                    "invoice_id": "inv-001",
                    "evidence": [
                        {
                            "claim": f"{agent_client._endpoint.name} evidence was gathered.",
                            "source_ref": f"{agent_client._endpoint.name}-source-001",
                            "confidence": 0.82,
                        }
                    ],
                    "summary": f"{agent_client._endpoint.name} expert completed.",
                }
            )

        with patch.dict(
            "os.environ",
            {
                "WORKIQ_EXPERT_ENDPOINT": "http://localhost:8091",
                "WEBIQ_EXPERT_ENDPOINT": "",
                "FOUNDRYIQ_EXPERT_ENDPOINT": "",
                "FABRICIQ_EXPERT_ENDPOINT": "",
            },
            clear=False,
        ), patch("expert_clients._ResponsesAgentClient.run", fake_run):
            result = run_assurance_orchestrator_invoice_assurance(
                {"invoice_id": "inv-001"},
                client=FakeWaypointClient(),
            )

        validators = {validator["validator_id"]: validator for validator in result["validators"]}
        self.assertEqual(validators["workiq"]["execution_path"], "responses_agent")
        self.assertEqual(validators["webiq"]["execution_path"], "placeholder")
        self.assertEqual(validators["fabriciq"]["execution_path"], "placeholder")
        self.assertEqual(validators["foundryiq"]["execution_path"], "placeholder")

    def test_failed_responses_experts_keep_responses_execution_path(self) -> None:
        def fake_run(agent_client, prompt: str) -> str:
            raise RuntimeError(f"{agent_client._endpoint.name} unavailable")

        with patch.dict(
            "os.environ",
            {
                "WORKIQ_EXPERT_ENDPOINT": "http://localhost:8091",
                "WEBIQ_EXPERT_ENDPOINT": "",
                "FOUNDRYIQ_EXPERT_ENDPOINT": "",
                "FABRICIQ_EXPERT_ENDPOINT": "",
            },
            clear=False,
        ), patch("expert_clients._ResponsesAgentClient.run", fake_run):
            result = run_assurance_orchestrator_invoice_assurance(
                {"invoice_id": "inv-001"},
                client=FakeWaypointClient(),
                retry_policy=RetryPolicy(max_attempts=1, backoff_seconds=0),
            )

        validators = {validator["validator_id"]: validator for validator in result["validators"]}
        self.assertEqual(validators["workiq"]["status"], "failed")
        self.assertEqual(validators["workiq"]["execution_path"], "responses_agent")
        self.assertEqual(validators["webiq"]["execution_path"], "placeholder")

    def test_toolbox_expert_client_discovers_tools_by_descriptor(self) -> None:
        async def run_discovery() -> list[str | None]:
            client = ToolboxExpertClient("https://example.test/toolbox", credential=object())
            client._tool_descriptors = [
                {
                    "name": "ask_work_context",
                    "description": "Ask Work IQ about Microsoft 365 approvals.",
                    "_meta": {"tool_configuration": {"type": "work_iq_preview"}},
                },
                {
                    "name": "ask_fabric_model",
                    "description": "Ask Fabric IQ over a Power BI semantic model.",
                    "_meta": {"tool_configuration": {"type": "fabric_iq_preview"}},
                },
                {
                    "name": "policy_search",
                    "description": "Search invoice policies and contract knowledge.",
                    "_meta": {"tool_configuration": {"type": "azure_ai_search"}},
                },
                {
                    "name": "web_search",
                    "description": "Search the web.",
                    "_meta": {"tool_configuration": {"type": "web_search"}},
                },
            ]
            return [
                await client.resolve_tool_name("workiq"),
                await client.resolve_tool_name("fabriciq"),
                await client.resolve_tool_name("foundryiq"),
                await client.resolve_tool_name("webiq"),
            ]

        self.assertEqual(
            __import__("asyncio").run(run_discovery()),
            ["ask_work_context", "ask_fabric_model", "policy_search", "web_search"],
        )

    def test_toolbox_endpoint_prefers_canonical_env_name(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "TOOLBOX_ENDPOINT": "https://example.test/toolboxes/canonical/mcp?api-version=v1",
                "TOOLBOX_MCP_ENDPOINT": "https://example.test/toolboxes/legacy/mcp?api-version=v1",
            },
            clear=False,
        ):
            self.assertEqual(
                _toolbox_endpoint(),
                "https://example.test/toolboxes/canonical/mcp?api-version=v1",
            )

    def test_async_tool_entrypoint_can_run_inside_event_loop(self) -> None:
        async def run_tool() -> str:
            with patch(
                "waypoint_tools.run_assurance_orchestrator_invoice_assurance_async",
                return_value={"status": "completed", "side_effects_performed": False},
            ):
                return await assurance_orchestrator_run_invoice_assurance_workflow(invoice_id="inv-001")

        result = __import__("asyncio").run(run_tool())
        self.assertIn('"status": "completed"', result)


class _FakeResponse:
    def __init__(self, status_code: int, *, headers: dict[str, str] | None = None) -> None:
        self.status_code = status_code
        self.headers = headers or {}
        self.text = f"status {status_code}"

    @property
    def is_error(self) -> bool:
        return self.status_code >= 400


class ExpertRetryTests(unittest.TestCase):
    """Graceful degradation: transient downstream failures retry then degrade cleanly."""

    def _post(self, responses: list[_FakeResponse], **kwargs: Any):
        import expert_clients

        calls = {"n": 0}

        def fake_client_factory(*_a: Any, **_k: Any):
            class _Ctx:
                def __enter__(_self):
                    return _self

                def __exit__(_self, *exc: Any) -> bool:
                    return False

                def post(_self, *_a: Any, **_k: Any) -> _FakeResponse:
                    idx = min(calls["n"], len(responses) - 1)
                    calls["n"] += 1
                    return responses[idx]

            return _Ctx()

        slept: list[float] = []
        with patch.object(expert_clients.httpx, "Client", fake_client_factory):
            result = expert_clients._post_responses_with_retry(
                "https://example.test/responses",
                {},
                {"input": "x"},
                5.0,
                label="test-expert",
                sleep=slept.append,
                **kwargs,
            )
        return result, calls["n"], slept

    def test_retries_transient_then_succeeds(self) -> None:
        result, n, slept = self._post(
            [_FakeResponse(429, headers={"Retry-After": "0"}), _FakeResponse(200)],
            max_attempts=3,
        )
        self.assertEqual(result.status_code, 200)
        self.assertEqual(n, 2)
        self.assertEqual(len(slept), 1)

    def test_non_transient_does_not_retry(self) -> None:
        result, n, slept = self._post([_FakeResponse(400), _FakeResponse(200)], max_attempts=3)
        self.assertEqual(result.status_code, 400)
        self.assertEqual(n, 1)
        self.assertEqual(slept, [])

    def test_exhausts_budget_returns_last_error(self) -> None:
        result, n, slept = self._post(
            [_FakeResponse(429, headers={"Retry-After": "0"})], max_attempts=3
        )
        self.assertEqual(result.status_code, 429)
        self.assertEqual(n, 3)
        self.assertEqual(len(slept), 2)

    def test_honors_retry_after_header(self) -> None:
        import expert_clients

        delay = expert_clients._retry_after_seconds(_FakeResponse(429, headers={"Retry-After": "4"}), 1)
        self.assertEqual(delay, 4.0)


class MaxRuntimeEnvConfigTests(unittest.TestCase):
    ENV_VAR = "ASSURANCE_ORCHESTRATOR_MAX_RUNTIME_MINUTES"

    def setUp(self) -> None:
        self._saved = os.environ.get(self.ENV_VAR)
        os.environ.pop(self.ENV_VAR, None)

    def tearDown(self) -> None:
        if self._saved is None:
            os.environ.pop(self.ENV_VAR, None)
        else:
            os.environ[self.ENV_VAR] = self._saved

    def test_default_when_env_unset(self) -> None:
        self.assertEqual(_default_max_runtime_minutes(), DEFAULT_MAX_RUNTIME_MINUTES)
        self.assertEqual(
            AssuranceOrchestratorRunConstraints().max_runtime_minutes,
            30,
        )

    def test_env_overrides_default_for_dataclass(self) -> None:
        os.environ[self.ENV_VAR] = "40"
        self.assertEqual(_default_max_runtime_minutes(), 40)
        self.assertEqual(
            AssuranceOrchestratorRunConstraints().max_runtime_minutes,
            40,
        )

    def test_env_default_applies_when_request_has_no_constraints(self) -> None:
        os.environ[self.ENV_VAR] = "40"
        request = normalize_workflow_request(
            {"invoice_id": "inv-123", "pdf_uri": "https://example.test/inv.pdf"}
        )
        self.assertEqual(request.constraints.max_runtime_minutes, 40)

    def test_env_default_applies_with_empty_constraints_payload(self) -> None:
        os.environ[self.ENV_VAR] = "40"
        request = normalize_workflow_request(
            {
                "invoice_id": "inv-123",
                "pdf_uri": "https://example.test/inv.pdf",
                "constraints": {},
            }
        )
        self.assertEqual(request.constraints.max_runtime_minutes, 40)

    def test_explicit_request_constraint_wins_over_env(self) -> None:
        os.environ[self.ENV_VAR] = "40"
        request = normalize_workflow_request(
            {
                "invoice_id": "inv-123",
                "pdf_uri": "https://example.test/inv.pdf",
                "constraints": {"max_runtime_minutes": 15},
            }
        )
        self.assertEqual(request.constraints.max_runtime_minutes, 15)

    def test_invalid_env_values_fall_back_to_default(self) -> None:
        for bad in ("abc", "0", "-5", "  ", ""):
            with self.subTest(value=bad):
                os.environ[self.ENV_VAR] = bad
                self.assertEqual(_default_max_runtime_minutes(), 30)
                self.assertEqual(
                    AssuranceOrchestratorRunConstraints().max_runtime_minutes,
                    30,
                )


if __name__ == "__main__":
    unittest.main()
