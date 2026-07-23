import json
import unittest
import importlib.util
from pathlib import Path

MODULE_PATH = Path(__file__).parents[1] / "scripts" / "verify_kb_retrieval_trace.py"
SPEC = importlib.util.spec_from_file_location("verify_kb_retrieval_trace", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
verify = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(verify)


class VerifyKbRetrievalTraceTests(unittest.TestCase):
    def test_passes_when_kb_tool_called_without_fallback(self):
        result = verify._evaluate(
            {
                "id": "run-1",
                "app_insights_operation_id": "op-1",
                "metadata": {
                    "fanout": [
                        {
                            "summary": "Grounded contract evidence returned source refs.",
                            "evidence": [{"source_ref": "Document; KB ref_id:3"}],
                        }
                    ]
                },
            },
            [
                {
                    "message_text": "knowledge_base___knowledge_base_retrieve returned 5 records",
                    "property_text": '{"tool":"knowledge_base_retrieve"}',
                }
            ],
        )

        self.assertTrue(result["passed"])
        self.assertTrue(result["has_knowledge_base_retrieve"])
        self.assertTrue(result["has_kb_runtime_evidence"])
        self.assertFalse(result["fallback_in_metadata"])

    def test_passes_when_trace_is_empty_but_runtime_evidence_has_kb_refs(self):
        result = verify._evaluate(
            {
                "id": "run-1",
                "app_insights_operation_id": "op-1",
                "metadata": {
                    "fanout": [
                        {
                            "agent": "contract-policy-expert",
                            "plane": "foundryiq",
                            "summary": "Foundry knowledge retrieval returned grounded records.",
                            "evidence": [
                                {
                                    "source_ref": (
                                        "contract-sup-009-bluepeak-biologics-capacity-agreement"
                                        "::contamination/deviation charge allocation (KB ref_id:0)"
                                    )
                                }
                            ],
                        }
                    ]
                },
            },
            [],
        )

        self.assertTrue(result["passed"])
        self.assertFalse(result["has_knowledge_base_retrieve"])
        self.assertTrue(result["has_kb_runtime_evidence"])
        self.assertIn("KB ref_id:0", result["kb_runtime_source_refs"][0])

    def test_passes_when_runtime_evidence_has_foundry_refs(self):
        result = verify._evaluate(
            {
                "id": "run-1",
                "app_insights_operation_id": "op-1",
                "metadata": {
                    "fanout": [
                        {
                            "agent": "contract-policy-expert",
                            "plane": "foundryiq",
                            "summary": "Foundry retrieval returned grounded records.",
                            "evidence": [
                                {
                                    "source_ref": (
                                        "contract-sup-009-bluepeak-biologics-capacity-agreement"
                                        " / Contamination clause / Foundry ref_id:0"
                                    )
                                }
                            ],
                        }
                    ]
                },
            },
            [],
        )

        self.assertTrue(result["passed"])
        self.assertTrue(result["has_kb_runtime_evidence"])
        self.assertIn("Foundry ref_id:0", result["kb_runtime_source_refs"][0])

    def test_passes_when_runtime_evidence_has_retrieved_refs(self):
        result = verify._evaluate(
            {
                "id": "run-1",
                "app_insights_operation_id": "op-1",
                "metadata": {
                    "fanout": [
                        {
                            "agent": "contract-policy-expert",
                            "plane": "foundryiq",
                            "summary": "Foundry retrieval returned grounded records.",
                            "evidence": [
                                {
                                    "source_ref": (
                                        "contract-sup-009-bluepeak-biologics-capacity-agreement; "
                                        "retrieved ref_id:0; contamination/deviation billing terms"
                                    )
                                }
                            ],
                        }
                    ]
                },
            },
            [],
        )

        self.assertTrue(result["passed"])
        self.assertTrue(result["has_kb_runtime_evidence"])
        self.assertIn("retrieved ref_id:0", result["kb_runtime_source_refs"][0])

    def test_fails_when_trace_uses_local_fallback(self):
        result = verify._evaluate(
            {
                "id": "run-1",
                "app_insights_operation_id": "op-1",
                "metadata": {"fanout": [{"summary": "Grounded evidence returned."}]},
            },
            [
                {"message_text": "knowledge_base___knowledge_base_retrieve failed"},
                {"message_text": "gather_contract_policy_evidence returned fallback evidence"},
            ],
        )

        self.assertFalse(result["passed"])
        self.assertTrue(result["fallback_in_trace"])

    def test_fails_when_recorded_metadata_contains_fallback(self):
        result = verify._evaluate(
            {
                "id": "run-1",
                "app_insights_operation_id": "op-1",
                "metadata": {
                    "fanout": [
                        {
                            "summary": (
                                "Fallback retrieval identified one governing contract. "
                                "Primary knowledge-base retrieval failed."
                            )
                        }
                    ]
                },
            },
            [{"message_text": "knowledge_base___knowledge_base_retrieve returned 5 records"}],
        )

        self.assertFalse(result["passed"])
        self.assertTrue(result["fallback_in_metadata"])

    def test_fails_when_no_kb_trace_or_runtime_evidence_is_found(self):
        result = verify._evaluate(
            {"id": "run-1", "app_insights_operation_id": "op-1", "metadata": {}},
            [{"message_text": "assurance completed"}],
        )

        self.assertFalse(result["passed"])
        self.assertIn("no knowledge_base_retrieve trace event", result["detail"])

    def test_fails_when_recorded_metadata_contains_kb_error(self):
        result = verify._evaluate(
            {
                "id": "run-1",
                "app_insights_operation_id": "op-1",
                "metadata": {
                    "fanout": [
                        {
                            "summary": "Knowledge-base retrieval failed.",
                            "evidence": [{"source_ref": "Document; KB ref_id:3"}],
                        }
                    ]
                },
            },
            [],
        )

        self.assertFalse(result["passed"])
        self.assertTrue(result["kb_error_in_metadata"])

    def test_parses_azure_cli_tables_output(self):
        raw = json.dumps(
            {
                "tables": [
                    {
                        "columns": [{"name": "message_text"}, {"name": "property_text"}],
                        "rows": [["knowledge_base_retrieve returned", "{}"]],
                    }
                ]
            }
        )

        self.assertEqual(
            verify._parse_log_query_output(raw),
            [{"message_text": "knowledge_base_retrieve returned", "property_text": "{}"}],
        )


if __name__ == "__main__":
    unittest.main()
