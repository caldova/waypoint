"""Tests for successful terminal run verification."""

from __future__ import annotations

import importlib.util
import io
import json
import unittest
import urllib.error
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

MODULE_PATH = Path(__file__).parents[1] / "scripts" / "verify_terminal_run.py"
SPEC = importlib.util.spec_from_file_location("verify_terminal_run", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
verify_terminal_run = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(verify_terminal_run)


class VerifyTerminalRunTests(unittest.TestCase):
    def test_selects_latest_matching_run(self) -> None:
        selected = verify_terminal_run._select_run(
            [
                {
                    "id": "old",
                    "name": "assurance:INV-1",
                    "status": "failed",
                    "updated_at": "2026-01-01T00:00:00Z",
                },
                {
                    "id": "new",
                    "name": "assurance:INV-1",
                    "status": "completed",
                    "updated_at": "2026-01-02T00:00:00Z",
                },
            ],
            "INV-1",
        )

        self.assertEqual(selected["id"], "new")

    def test_completed_run_passes(self) -> None:
        response = MagicMock()
        response.__enter__.return_value = response
        response.read.return_value = json.dumps(
            [
                {
                    "id": "run-1",
                    "name": "assurance:INV-1",
                    "status": "completed",
                    "foundry_agent_name": "assurance-orchestrator",
                    "app_insights_operation_id": "operation-1",
                    "updated_at": "2026-01-02T00:00:00Z",
                }
            ]
        ).encode()

        with patch.object(verify_terminal_run.urllib.request, "urlopen", return_value=response):
            result = verify_terminal_run._verify(
                api_base_url="https://api.example",
                api_key="reader",
                invoice_id="INV-1",
                updated_after=datetime(2026, 1, 1, tzinfo=UTC),
                timeout_seconds=1,
            )

        self.assertTrue(result["passed"])
        self.assertTrue(result["has_operation_id"])

    def test_running_run_fails(self) -> None:
        response = MagicMock()
        response.__enter__.return_value = response
        response.read.return_value = json.dumps(
            [
                {
                    "id": "run-1",
                    "name": "assurance:INV-1",
                    "status": "running",
                    "updated_at": "2026-01-02T00:00:00Z",
                }
            ]
        ).encode()

        with patch.object(verify_terminal_run.urllib.request, "urlopen", return_value=response):
            result = verify_terminal_run._verify(
                api_base_url="https://api.example",
                api_key="reader",
                invoice_id="INV-1",
                updated_after=datetime(2026, 1, 1, tzinfo=UTC),
                timeout_seconds=1,
            )

        self.assertFalse(result["passed"])

    def test_old_completed_run_fails(self) -> None:
        response = MagicMock()
        response.__enter__.return_value = response
        response.read.return_value = json.dumps(
            [
                {
                    "id": "run-1",
                    "name": "assurance:INV-1",
                    "status": "completed",
                    "app_insights_operation_id": "operation-1",
                    "updated_at": "2025-12-31T23:59:59Z",
                }
            ]
        ).encode()

        with patch.object(verify_terminal_run.urllib.request, "urlopen", return_value=response):
            result = verify_terminal_run._verify(
                api_base_url="https://api.example",
                api_key="reader",
                invoice_id="INV-1",
                updated_after=datetime(2026, 1, 1, tzinfo=UTC),
                timeout_seconds=1,
            )

        self.assertFalse(result["passed"])

    def test_transient_timeout_is_retried(self) -> None:
        response = MagicMock()
        response.__enter__.return_value = response
        response.read.return_value = json.dumps(
            [
                {
                    "id": "run-1",
                    "name": "assurance:INV-1",
                    "status": "completed",
                    "app_insights_operation_id": "operation-1",
                    "updated_at": "2026-01-02T00:00:00Z",
                }
            ]
        ).encode()

        with patch.object(
            verify_terminal_run.urllib.request,
            "urlopen",
            side_effect=[TimeoutError("slow response"), response],
        ):
            result = verify_terminal_run._verify(
                api_base_url="https://api.example",
                api_key="reader",
                invoice_id="INV-1",
                updated_after=datetime(2026, 1, 1, tzinfo=UTC),
                timeout_seconds=1,
                poll_timeout_seconds=1,
                poll_interval_seconds=0,
            )

        self.assertTrue(result["passed"])

    def test_missing_run_is_retried_until_visible(self) -> None:
        missing = MagicMock()
        missing.__enter__.return_value = missing
        missing.read.return_value = b"[]"
        completed = MagicMock()
        completed.__enter__.return_value = completed
        completed.read.return_value = json.dumps(
            [
                {
                    "id": "run-1",
                    "name": "assurance:INV-1",
                    "status": "completed",
                    "app_insights_operation_id": "operation-1",
                    "updated_at": "2026-01-02T00:00:00Z",
                }
            ]
        ).encode()

        with patch.object(
            verify_terminal_run.urllib.request,
            "urlopen",
            side_effect=[missing, completed],
        ):
            result = verify_terminal_run._verify(
                api_base_url="https://api.example",
                api_key="reader",
                invoice_id="INV-1",
                updated_after=datetime(2026, 1, 1, tzinfo=UTC),
                timeout_seconds=1,
                poll_timeout_seconds=1,
                poll_interval_seconds=0,
            )

        self.assertTrue(result["passed"])

    def test_running_run_is_retried_until_terminal(self) -> None:
        running = MagicMock()
        running.__enter__.return_value = running
        running.read.return_value = json.dumps(
            [
                {
                    "id": "run-1",
                    "name": "assurance:INV-1",
                    "status": "running",
                    "updated_at": "2026-01-02T00:00:00Z",
                }
            ]
        ).encode()
        completed = MagicMock()
        completed.__enter__.return_value = completed
        completed.read.return_value = json.dumps(
            [
                {
                    "id": "run-1",
                    "name": "assurance:INV-1",
                    "status": "completed",
                    "app_insights_operation_id": "operation-1",
                    "updated_at": "2026-01-02T00:01:00Z",
                }
            ]
        ).encode()

        with patch.object(
            verify_terminal_run.urllib.request,
            "urlopen",
            side_effect=[running, completed],
        ):
            result = verify_terminal_run._verify(
                api_base_url="https://api.example",
                api_key="reader",
                invoice_id="INV-1",
                updated_after=datetime(2026, 1, 1, tzinfo=UTC),
                timeout_seconds=1,
                poll_timeout_seconds=1,
                poll_interval_seconds=0,
            )

        self.assertTrue(result["passed"])

    def test_permanent_http_failure_is_not_retried(self) -> None:
        error = urllib.error.HTTPError(
            "https://api.example/api/runs",
            401,
            "Unauthorized",
            {},
            io.BytesIO(),
        )

        with patch.object(
            verify_terminal_run.urllib.request,
            "urlopen",
            side_effect=error,
        ) as urlopen:
            result = verify_terminal_run._verify(
                api_base_url="https://api.example",
                api_key="reader",
                invoice_id="INV-1",
                updated_after=datetime(2026, 1, 1, tzinfo=UTC),
                timeout_seconds=1,
                poll_timeout_seconds=10,
                poll_interval_seconds=0,
            )

        self.assertFalse(result["passed"])
        self.assertEqual(urlopen.call_count, 1)

    def test_deadline_exhaustion_returns_last_failure(self) -> None:
        response = MagicMock()
        response.__enter__.return_value = response
        response.read.return_value = b"[]"

        with (
            patch.object(
                verify_terminal_run.urllib.request,
                "urlopen",
                return_value=response,
            ) as urlopen,
            patch.object(
                verify_terminal_run.time,
                "monotonic",
                side_effect=[0.0, 1.0],
            ),
        ):
            result = verify_terminal_run._verify(
                api_base_url="https://api.example",
                api_key="reader",
                invoice_id="INV-1",
                updated_after=datetime(2026, 1, 1, tzinfo=UTC),
                timeout_seconds=1,
                poll_timeout_seconds=1,
                poll_interval_seconds=0,
            )

        self.assertFalse(result["passed"])
        self.assertIn("was found", result["detail"])
        self.assertEqual(urlopen.call_count, 1)


if __name__ == "__main__":
    unittest.main()
