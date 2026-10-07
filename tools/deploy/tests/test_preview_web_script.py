from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "tools" / "deploy" / "scripts" / "preview_web.sh"
DOMAIN = "preview-env.westus.azurecontainerapps.io"
PROD_URIS = ["https://app.example.com/auth/msal/callback", "https://app.example.com/login"]


class PreviewWebScriptTests(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.tmp = Path(self._dir.name)
        self.state_path = self.tmp / "state.json"
        self.write_state(
            {
                "apps": {},
                "tags": [],
                "spa": list(PROD_URIS),
                "prStates": {},
                "calls": [],
            }
        )
        for name, body in (("az", _FAKE_AZ), ("gh", _FAKE_GH), ("curl", _FAKE_CURL)):
            path = self.tmp / name
            path.write_text(body, encoding="utf-8")
            path.chmod(0o755)
        self.output = self.tmp / "github_output"
        self.env = {
            **os.environ,
            "PATH": f"{self.tmp}:{os.environ['PATH']}",
            "FAKE_STATE": str(self.state_path),
            "GITHUB_OUTPUT": str(self.output),
            "GITHUB_REPOSITORY": "caldova/waypoint",
            "PREVIEW_RESOURCE_GROUP": "waypoint-preview-rg",
            "MSAL_CLIENT_ID": "00000000-0000-0000-0000-0000000000aa",
            "MSAL_TENANT_ID": "00000000-0000-0000-0000-0000000000bb",
            "MSAL_API_SCOPE": "api://prod-api/user_impersonation",
            "API_URL": "https://api.example.com",
            "MSAL_GRAPH_RETRY_DELAY_SECONDS": "0",
        }

    def tearDown(self) -> None:
        self._dir.cleanup()

    def write_state(self, state: dict) -> None:
        self.state_path.write_text(json.dumps(state), encoding="utf-8")

    def state(self) -> dict:
        return json.loads(self.state_path.read_text(encoding="utf-8"))

    def run_script(self, mode: str, **extra: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", str(SCRIPT), mode],
            env={**self.env, **extra},
            capture_output=True,
            text=True,
        )

    def outputs(self) -> dict[str, str]:
        if not self.output.exists():
            return {}
        return dict(line.split("=", 1) for line in self.output.read_text().splitlines())

    def test_deploy_runs_app_bicep_and_registers_sign_in(self) -> None:
        result = self.run_script("deploy", PR_NUMBER="36", IMAGE="reg.azurecr.io/waypoint-web:pr-36-abc")
        self.assertEqual(result.returncode, 0, result.stderr)

        app = self.state()["apps"]["web-pr-36"]
        self.assertTrue(app["template"].endswith("infra/preview/app.bicep"))
        self.assertEqual(app["deployment"], "preview-web-pr-36")
        self.assertEqual(
            app["params"],
            {
                "prNumber": "36",
                "image": "reg.azurecr.io/waypoint-web:pr-36-abc",
                "registryName": "waypointpreview",
                "location": "northeurope",
                "apiUrl": "https://api.example.com",
                "msalClientId": "00000000-0000-0000-0000-0000000000aa",
                "msalTenantId": "00000000-0000-0000-0000-0000000000bb",
                "msalApiScope": "api://prod-api/user_impersonation",
                "repository": "caldova/waypoint",
            },
        )

        self.assertEqual(
            sorted(self.state()["spa"]),
            sorted(
                PROD_URIS
                + [
                    f"https://web-pr-36.{DOMAIN}/auth/msal/callback",
                    f"https://web-pr-36.{DOMAIN}/login",
                ]
            ),
        )
        self.assertEqual(self.outputs()["url"], f"https://web-pr-36.{DOMAIN}")

    def test_redeploy_updates_the_same_app_in_place(self) -> None:
        self.run_script("deploy", PR_NUMBER="36", IMAGE="reg.azurecr.io/waypoint-web:pr-36-abc")
        result = self.run_script("deploy", PR_NUMBER="36", IMAGE="reg.azurecr.io/waypoint-web:pr-36-def")
        self.assertEqual(result.returncode, 0, result.stderr)

        self.assertEqual(list(self.state()["apps"]), ["web-pr-36"])
        self.assertEqual(self.state()["apps"]["web-pr-36"]["params"]["image"], "reg.azurecr.io/waypoint-web:pr-36-def")

    def test_destroy_removes_only_that_prs_app_redirects_and_images(self) -> None:
        self.run_script("deploy", PR_NUMBER="36", IMAGE="reg.azurecr.io/waypoint-web:pr-36-abc")
        self.run_script("deploy", PR_NUMBER="7", IMAGE="reg.azurecr.io/waypoint-web:pr-7-abc")
        state = self.state()
        state["tags"] = ["pr-36-abc", "pr-36-def", "pr-7-abc", "pr-360-abc"]
        self.write_state(state)

        result = self.run_script("destroy", PR_NUMBER="36")
        self.assertEqual(result.returncode, 0, result.stderr)

        state = self.state()
        self.assertEqual(sorted(state["apps"]), ["web-pr-7"])
        self.assertEqual(sorted(state["tags"]), ["pr-360-abc", "pr-7-abc"])
        self.assertNotIn(f"https://web-pr-36.{DOMAIN}/login", state["spa"])
        self.assertIn(f"https://web-pr-7.{DOMAIN}/login", state["spa"])
        for uri in PROD_URIS:
            self.assertIn(uri, state["spa"])

        # Destroying again is a no-op.
        self.assertEqual(self.run_script("destroy", PR_NUMBER="36").returncode, 0)

    def test_sweep_removes_previews_for_closed_prs_only(self) -> None:
        self.run_script("deploy", PR_NUMBER="36", IMAGE="reg.azurecr.io/waypoint-web:pr-36-abc")
        self.run_script("deploy", PR_NUMBER="7", IMAGE="reg.azurecr.io/waypoint-web:pr-7-abc")
        state = self.state()
        state["tags"] = ["pr-36-abc", "pr-7-abc", "pr-5-old"]
        state["prStates"] = {"36": "OPEN", "7": "MERGED", "5": "CLOSED"}
        self.write_state(state)

        result = self.run_script("sweep", GH_TOKEN="token")
        self.assertEqual(result.returncode, 0, result.stderr)

        state = self.state()
        self.assertEqual(sorted(state["apps"]), ["web-pr-36"])
        self.assertEqual(state["tags"], ["pr-36-abc"])

    def test_rejects_non_numeric_pr_numbers(self) -> None:
        result = self.run_script("destroy", PR_NUMBER="36; rm -rf /")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("must be numeric", result.stderr)
        self.assertEqual(self.state()["calls"], [])


_FAKE_AZ = r"""#!/usr/bin/env python3
import json, os, sys

path = os.environ["FAKE_STATE"]
state = json.load(open(path))
args = sys.argv[1:]
DOMAIN = "preview-env.westus.azurecontainerapps.io"

def arg(name):
    return args[args.index(name) + 1]

def save():
    json.dump(state, open(path, "w"))

if args[:2] == ["containerapp", "env"]:
    query = arg("--query")
    print({
        "[0].name": "waypoint-preview-env",
        "[0].properties.defaultDomain": DOMAIN,
        "[0].location": "northeurope",
    }[query])
    raise SystemExit(0)
if args[:2] == ["acr", "list"]:
    print({"[0].name": "waypointpreview", "[0].loginServer": "waypointpreview.azurecr.io"}[arg("--query")])
    raise SystemExit(0)
if args[:2] == ["identity", "show"]:
    print("/subscriptions/x/resourceGroups/waypoint-preview-rg/providers/identity/waypoint-preview-pull")
    raise SystemExit(0)

state["calls"].append(args[:3])
if args[:2] == ["containerapp", "show"]:
    save()
    raise SystemExit(0 if arg("-n") in state["apps"] else 3)
elif args[:3] == ["deployment", "group", "create"]:
    start = args.index("-p") + 1
    end = args.index("-o")
    params = dict(item.split("=", 1) for item in args[start:end])
    state["apps"]["web-pr-" + params["prNumber"]] = {
        "deployment": arg("-n"),
        "template": arg("-f"),
        "params": params,
    }
elif args[:2] == ["containerapp", "delete"]:
    state["apps"].pop(arg("-n"), None)
elif args[:2] == ["containerapp", "list"]:
    print("\n".join(name.removeprefix("web-pr-") for name in state["apps"]))
elif args[:3] == ["acr", "repository", "show-tags"]:
    print("\n".join(state["tags"]))
elif args[:3] == ["acr", "repository", "delete"]:
    state["tags"].remove(arg("--image").split(":", 1)[1])
elif args[:3] == ["ad", "app", "show"]:
    print("00000000-0000-0000-0000-0000000000cc")
elif args[0] == "rest" and arg("--method") == "GET":
    print(json.dumps(state["spa"]))
elif args[0] == "rest" and arg("--method") == "PATCH":
    state["spa"] = json.loads(arg("--body"))["spa"]["redirectUris"]
else:
    raise SystemExit(f"unsupported fake az invocation: {args}")
save()
"""

_FAKE_GH = r"""#!/usr/bin/env python3
import json, os, sys
state = json.load(open(os.environ["FAKE_STATE"]))
args = sys.argv[1:]
if args[:2] == ["pr", "view"]:
    print(state["prStates"].get(args[2], "UNKNOWN"))
else:
    raise SystemExit(f"unsupported fake gh invocation: {args}")
"""

_FAKE_CURL = """#!/usr/bin/env bash
printf 200
"""


if __name__ == "__main__":
    unittest.main()
