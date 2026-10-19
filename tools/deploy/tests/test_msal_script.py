from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "tools" / "deploy" / "scripts" / "msal.sh"


class MsalScriptTests(unittest.TestCase):
    def test_ensure_reconciles_scopes_roles_and_tags_idempotently(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            state_path = tmp_path / "state.json"
            state_path.write_text(
                json.dumps(
                    {
                        "appId": "00000000-0000-0000-0000-000000000001",
                        "id": "00000000-0000-0000-0000-000000000002",
                        "identifierUris": [],
                        "identifierPatchFailures": 1,
                        "api": {"oauth2PermissionScopes": []},
                        "appRoles": [],
                        "servicePrincipal": False,
                        "tags": [],
                    }
                ),
                encoding="utf-8",
            )
            az_path = tmp_path / "az"
            az_path.write_text(_fake_az(), encoding="utf-8")
            az_path.chmod(0o755)

            env = {
                **os.environ,
                "PATH": f"{tmp_path}:{os.environ['PATH']}",
                "AZURE_TENANT_ID": "00000000-0000-0000-0000-000000000003",
                "MSAL_DISPLAY_NAME": "waypoint-test",
                "FAKE_AZ_STATE": str(state_path),
                "AZD_ENV_NAME": "seller-test",
                "GITHUB_REPOSITORY": "seller/waypoint-demo",
                "MSAL_GRAPH_RETRY_DELAY_SECONDS": "0",
            }
            subprocess.run(["bash", str(SCRIPT), "ensure"], check=True, env=env)
            first = json.loads(state_path.read_text(encoding="utf-8"))
            subprocess.run(["bash", str(SCRIPT), "ensure"], check=True, env=env)
            second = json.loads(state_path.read_text(encoding="utf-8"))

            self.assertEqual(second, first)
            self.assertEqual(first["identifierUris"], [f"api://{first['appId']}"])
            self.assertEqual(first["api"]["requestedAccessTokenVersion"], 2)
            self.assertTrue(first["servicePrincipal"])
            self.assertEqual(
                {scope["value"] for scope in first["api"]["oauth2PermissionScopes"]},
                {"user_impersonation"},
            )
            self.assertEqual(
                {role["value"] for role in first["appRoles"]},
                {"Waypoint.Admin", "Waypoint.Read", "Waypoint.Write"},
            )
            self.assertEqual(
                set(first["tags"]),
                {
                    "waypoint-environment=seller-test",
                    "waypoint-managed",
                    "waypoint-repository=seller/waypoint-demo",
                },
            )
    def test_redirect_and_unredirect_touch_only_one_host(self) -> None:
        prod = ["https://app.example.com/auth/msal/callback", "https://app.example.com/login"]
        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            state_path = tmp_path / "state.json"
            state_path.write_text(
                json.dumps(
                    {
                        "appId": "00000000-0000-0000-0000-000000000001",
                        "id": "00000000-0000-0000-0000-000000000002",
                        "spa": list(prod),
                    }
                ),
                encoding="utf-8",
            )
            az_path = tmp_path / "az"
            az_path.write_text(_fake_az(), encoding="utf-8")
            az_path.chmod(0o755)
            env = {
                **os.environ,
                "PATH": f"{tmp_path}:{os.environ['PATH']}",
                "FAKE_AZ_STATE": str(state_path),
                "MSAL_CLIENT_ID": "00000000-0000-0000-0000-000000000001",
                "WEB_FQDN": "web-pr-7.preview.example.io",
                "MSAL_GRAPH_RETRY_DELAY_SECONDS": "0",
            }
            env.pop("GITHUB_OUTPUT", None)

            def spa() -> list[str]:
                return json.loads(state_path.read_text(encoding="utf-8"))["spa"]

            subprocess.run(["bash", str(SCRIPT), "redirect"], check=True, env=env)
            subprocess.run(["bash", str(SCRIPT), "redirect"], check=True, env=env)
            self.assertEqual(
                sorted(spa()),
                sorted(
                    prod
                    + [
                        "https://web-pr-7.preview.example.io/auth/msal/callback",
                        "https://web-pr-7.preview.example.io/login",
                    ]
                ),
            )

            subprocess.run(["bash", str(SCRIPT), "unredirect"], check=True, env=env)
            self.assertEqual(sorted(spa()), sorted(prod))
            # Idempotent: removing an absent host is a no-op.
            subprocess.run(["bash", str(SCRIPT), "unredirect"], check=True, env=env)
            self.assertEqual(sorted(spa()), sorted(prod))


def _fake_az() -> str:
    return """#!/usr/bin/env python3
import json
import os
import sys

path = os.environ["FAKE_AZ_STATE"]
with open(path, encoding="utf-8") as handle:
    state = json.load(handle)
args = sys.argv[1:]

if args[:3] == ["ad", "app", "list"]:
    print(state["appId"])
elif args[:3] == ["ad", "app", "show"]:
    query = args[args.index("--query") + 1]
    if query == "id":
        print(state["id"])
    elif query == "identifierUris":
        print(json.dumps(state["identifierUris"]))
elif args[:3] == ["ad", "sp", "show"]:
    if not state["servicePrincipal"]:
        raise SystemExit(3)
elif args[:3] == ["ad", "sp", "create"]:
    state["servicePrincipal"] = True
elif args[0] == "rest" and args[args.index("--method") + 1] == "GET":
    query = args[args.index("--query") + 1] if "--query" in args else ""
    if query == "spa.redirectUris":
        print(json.dumps(state.get("spa", [])))
    elif query == "length(api.oauth2PermissionScopes[?value == 'user_impersonation'])":
        print(sum(scope.get("value") == "user_impersonation" for scope in state["api"]["oauth2PermissionScopes"]))
    else:
        print(json.dumps({
            "appRoles": state["appRoles"],
            "scopes": state["api"]["oauth2PermissionScopes"],
            "tags": state["tags"],
        }))
elif args[0] == "rest" and args[args.index("--method") + 1] == "PATCH":
    body = json.loads(args[args.index("--body") + 1])
    if "identifierUris" in body and state["identifierPatchFailures"]:
        state["identifierPatchFailures"] -= 1
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(state, handle, sort_keys=True)
        print("Request_ResourceNotFound", file=sys.stderr)
        raise SystemExit(1)
    if "identifierUris" in body:
        state["identifierUris"] = body["identifierUris"]
    if "api" in body:
        state["api"] = body["api"]
    if "appRoles" in body:
        state["appRoles"] = body["appRoles"]
    if "tags" in body:
        state["tags"] = body["tags"]
    if "spa" in body:
        state["spa"] = body["spa"]["redirectUris"]
else:
    raise SystemExit(f"unsupported fake az invocation: {args}")

with open(path, "w", encoding="utf-8") as handle:
    json.dump(state, handle, sort_keys=True)
"""


if __name__ == "__main__":
    unittest.main()
