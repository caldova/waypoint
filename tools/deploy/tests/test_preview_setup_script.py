from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "tools" / "deploy" / "scripts" / "preview_setup.sh"


class PreviewSetupScriptTests(unittest.TestCase):
    def run_dry(self, *args: str) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as directory:
            tmp = Path(directory)
            calls = tmp / "calls.jsonl"
            for name, body in (("az", _FAKE_AZ), ("gh", _FAKE_GH)):
                path = tmp / name
                path.write_text(body, encoding="utf-8")
                path.chmod(0o755)
            env = {**os.environ, "PATH": f"{tmp}:{os.environ['PATH']}", "FAKE_CALLS": str(calls)}
            env.pop("GITHUB_REPOSITORY", None)
            result = subprocess.run(
                ["bash", str(SCRIPT), "--dry-run", *args], env=env, capture_output=True, text=True
            )
            self.calls = [json.loads(line) for line in calls.read_text().splitlines()] if calls.exists() else []
            return result

    def test_dry_run_derives_defaults_from_production_without_writing(self) -> None:
        result = self.run_dry()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("resource group:  waypoint-preview-rg (swedencentral;", result.stderr)
        self.assertIn("production API:  https://api.example.com", result.stderr)
        self.assertIn("scope api://prod-api-app/user_impersonation", result.stderr)
        # Reuses the org's subject format (with owner/repo IDs) for the preview environment.
        self.assertIn("OIDC subject:    repo:caldova@1/waypoint@2:environment:preview", result.stderr)
        self.assertIn("dry run: no changes made", result.stderr)
        writes = [c for c in self.calls if c[:2] in (["group", "create"], ["ad", "app"]) and "create" in c]
        self.assertEqual(writes, [])

    def test_explicit_flags_override_production_defaults(self) -> None:
        result = self.run_dry(
            "--location", "westus3",
            "--environment-location", "northeurope",
            "--api-url", "https://api.other.example",
            "--subject-prefix", "repo:me/fork",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("(westus3; Container Apps environment in northeurope)", result.stderr)
        self.assertIn("production API:  https://api.other.example", result.stderr)
        self.assertIn("OIDC subject:    repo:me/fork:environment:preview", result.stderr)


_FAKE_AZ = r"""#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
with open(os.environ["FAKE_CALLS"], "a") as handle:
    handle.write(json.dumps(args) + "\n")

def arg(name):
    return args[args.index(name) + 1]

if args[:2] == ["account", "show"]:
    print({"id": "sub-id", "tenantId": "tenant-id"}[arg("--query")])
elif args[:2] == ["group", "show"]:
    if arg("-n") == "waypoint-rg":
        print("swedencentral")
    else:
        raise SystemExit(3)
elif args[:2] == ["containerapp", "show"]:
    print("https://api.example.com")
elif args[:4] == ["ad", "app", "federated-credential", "list"]:
    print("repo:caldova@1/waypoint@2:environment:caldova")
else:
    raise SystemExit(f"unexpected az call in dry run: {args}")
"""

_FAKE_GH = r"""#!/usr/bin/env python3
import sys
args = sys.argv[1:]
values = {"WAYPOINT_MSAL_CLIENT_ID": "prod-api-app", "AZURE_CLIENT_ID": "prod-deployer"}
if args[:2] == ["variable", "get"]:
    print(values[args[2]])
else:
    raise SystemExit(f"unexpected gh call in dry run: {args}")
"""


if __name__ == "__main__":
    unittest.main()
