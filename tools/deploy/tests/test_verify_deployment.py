"""Tests for the deployment acceptance probe runner."""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

MODULE_PATH = Path(__file__).parents[1] / "scripts" / "verify_deployment.py"
SPEC = importlib.util.spec_from_file_location("verify_deployment", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
verify_deployment = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(verify_deployment)


class VerifyDeploymentTests(unittest.TestCase):
    def test_public_probe_passes(self) -> None:
        response = MagicMock()
        response.__enter__.return_value = response
        response.status = 200
        response.read.return_value = b"Healthy"

        with patch.object(verify_deployment.urllib.request, "urlopen", return_value=response):
            result = verify_deployment._probe(
                {
                    "name": "health",
                    "base": "api",
                    "path": "/health",
                    "expected_status": 200,
                    "expected_body": "Healthy",
                    "auth": "none",
                },
                bases={"api": "https://api.example", "web": "https://web.example"},
                api_key=None,
                require_authenticated=False,
                timeout_seconds=1,
            )

        self.assertEqual(result["status"], "passed")

    def test_authenticated_probe_is_skipped_without_key_by_default(self) -> None:
        result = verify_deployment._probe(
            {
                "name": "runs",
                "base": "api",
                "path": "/api/runs",
                "expected_status": 200,
                "expected_json_type": "array",
                "auth": "api_key",
            },
            bases={"api": "https://api.example", "web": "https://web.example"},
            api_key=None,
            require_authenticated=False,
            timeout_seconds=1,
        )

        self.assertEqual(result["status"], "skipped")

    def test_authenticated_probe_fails_without_required_key(self) -> None:
        result = verify_deployment._probe(
            {
                "name": "runs",
                "base": "api",
                "path": "/api/runs",
                "expected_status": 200,
                "expected_json_type": "array",
                "auth": "api_key",
            },
            bases={"api": "https://api.example", "web": "https://web.example"},
            api_key=None,
            require_authenticated=True,
            timeout_seconds=1,
        )

        self.assertEqual(result["status"], "failed")


if __name__ == "__main__":
    unittest.main()
