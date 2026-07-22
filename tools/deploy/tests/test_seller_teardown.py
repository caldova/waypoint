from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "tools/deploy/scripts/seller_teardown.py"
SUBSCRIPTION = "11111111-1111-1111-1111-111111111111"
DEPLOY_CLIENT = "22222222-2222-2222-2222-222222222222"
MSAL_CLIENT = "33333333-3333-3333-3333-333333333333"


def run_teardown(tmp_path: Path, state: dict, *extra: str) -> tuple[subprocess.CompletedProcess[str], dict]:
    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps(state), encoding="utf-8")
    for name, content in (("az", fake_az()), ("azd", fake_azd())):
        executable = tmp_path / name
        executable.write_text(content, encoding="utf-8")
        executable.chmod(0o755)
    env = {
        **os.environ,
        "PATH": f"{tmp_path}:{os.environ['PATH']}",
        "FAKE_STATE": str(state_path),
        "WAYPOINT_TEARDOWN_POLL_ATTEMPTS": "2",
        "WAYPOINT_TEARDOWN_POLL_SECONDS": "0",
    }
    result = subprocess.run(
        [
            "python3",
            str(SCRIPT),
            "--subscription-id",
            SUBSCRIPTION,
            "--app-resource-group",
            "rg-app",
            "--state-resource-group",
            "rg-state",
            "--azd-env",
            "seller-test",
            "--deployment-client-id",
            DEPLOY_CLIENT,
            "--repository",
            "seller/demo",
            *extra,
        ],
        text=True,
        capture_output=True,
        env=env,
    )
    return result, json.loads(state_path.read_text(encoding="utf-8"))


def base_state() -> dict:
    return {
        "subscription": SUBSCRIPTION,
        "groups": {
            "rg-app": {
                "location": "eastus",
                "tags": {},
                "resources": [
                    {"name": "api", "type": "Microsoft.App/containerApps"},
                    {"name": "web", "type": "Microsoft.App/containerApps"},
                    {"name": "starter-env", "type": "Microsoft.App/managedEnvironments"},
                    {
                        "name": "ai-seller",
                        "type": "Microsoft.CognitiveServices/accounts",
                        "location": "swedencentral",
                    },
                ],
                "components": {"starter-env": ["aspire-dashboard"]},
            },
            "rg-state": {
                "location": "eastus",
                "tags": {"waypoint_msal_client_id": MSAL_CLIENT},
                "resources": [{"name": "vault", "type": "Microsoft.KeyVault/vaults"}],
            },
            "rg-unrelated": {
                "location": "eastus",
                "tags": {},
                "resources": [{"name": "keep", "type": "Microsoft.Storage/storageAccounts"}],
            },
        },
        "azd": {"seller-test": {"WAYPOINT_MSAL_CLIENT_ID": MSAL_CLIENT}},
        "deploy_object_id": "deploy-object",
        "apps": [
            {
                "appId": MSAL_CLIENT,
                "id": "msal-object",
                "displayName": "waypoint-seller",
                "tags": [
                    "waypoint-managed",
                    "waypoint-environment=seller-test",
                    "waypoint-repository=seller/demo",
                ],
                "owners": ["deploy-object"],
            },
            {
                "appId": "44444444-4444-4444-4444-444444444444",
                "id": "unrelated-object",
                "displayName": "waypoint-seller",
                "tags": [],
                "owners": ["deploy-object"],
            },
        ],
        "deleted_cognitive": [],
        "deleted_vaults": [],
        "calls": [],
    }


class SellerTeardownTests(unittest.TestCase):
    def run_case(self, state: dict, *extra: str) -> tuple[subprocess.CompletedProcess[str], dict]:
        with tempfile.TemporaryDirectory() as directory:
            return run_teardown(Path(directory), state, *extra)

    def test_dry_run_inventory_is_sanitized_and_non_destructive(self) -> None:
        result, state = self.run_case(base_state())
        self.assertEqual(result.returncode, 0, result.stderr)
        plan = json.loads(result.stdout)
        self.assertEqual(plan["mode"], "dry-run")
        self.assertNotIn(SUBSCRIPTION, result.stdout)
        self.assertNotIn(MSAL_CLIENT, result.stdout)
        self.assertEqual(
            [item["name"] for item in plan["app_resource_group"]["resources"]],
            ["api", "web", "starter-env", "ai-seller"],
        )
        self.assertFalse(any(call[:3] == ["group", "delete", "--name"] for call in state["calls"]))
        self.assertIn("rg-unrelated", state["groups"])

    def test_apply_requires_typed_environment_confirmation(self) -> None:
        result, state = self.run_case(base_state(), "--apply", "--confirm-environment", "wrong")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(state["groups"].keys(), base_state()["groups"].keys())

    def test_apply_deletes_exact_groups_in_order_but_preserves_apps_without_flag(self) -> None:
        result, state = self.run_case(
            base_state(),
            "--apply",
            "--confirm-environment",
            "seller-test",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        deletes = [call for call in state["calls"] if call[:2] == ["group", "delete"]]
        self.assertEqual(deletes[0][deletes[0].index("--name") + 1], "rg-app")
        self.assertEqual(deletes[1][deletes[1].index("--name") + 1], "rg-state")
        ordered = []
        for call in state["calls"]:
            if call[:2] == ["containerapp", "delete"]:
                ordered.append(f"app:{call[call.index('--name') + 1]}")
            elif call[:4] == ["containerapp", "env", "dotnet-component", "delete"]:
                ordered.append(f"component:{call[call.index('--name') + 1]}")
            elif call[:3] == ["containerapp", "env", "delete"]:
                ordered.append(f"environment:{call[call.index('--name') + 1]}")
            elif call[:2] == ["group", "delete"]:
                ordered.append(f"group:{call[call.index('--name') + 1]}")
        self.assertEqual(
            ordered,
            [
                "app:api",
                "app:web",
                "component:aspire-dashboard",
                "environment:starter-env",
                "group:rg-app",
                "group:rg-state",
            ],
        )
        self.assertIn("rg-unrelated", state["groups"])
        self.assertEqual(len(state["apps"]), 2)
        self.assertNotIn("seller-test", state["azd"])
        self.assertEqual(state["deleted_cognitive"], [])
        self.assertEqual(state["deleted_vaults"], [])

    def test_app_deletion_requires_state_or_tags_and_deploy_owner(self) -> None:
        state = base_state()
        state["apps"].append(
            {
                "appId": "55555555-5555-5555-5555-555555555555",
                "id": "tagged-not-owned",
                "displayName": "other",
                "tags": [
                    "waypoint-managed",
                    "waypoint-environment=seller-test",
                    "waypoint-repository=seller/demo",
                ],
                "owners": ["someone-else"],
            }
        )
        result, state = self.run_case(
            state,
            "--apply",
            "--confirm-environment",
            "seller-test",
            "--delete-app-registrations",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual({app["id"] for app in state["apps"]}, {"unrelated-object", "tagged-not-owned"})

    def test_recorded_unTagged_app_is_deleted_only_when_owned(self) -> None:
        state = base_state()
        state["apps"][0]["tags"] = []
        result, state = self.run_case(
            state,
            "--apply",
            "--confirm-environment",
            "seller-test",
            "--delete-app-registrations",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual({app["id"] for app in state["apps"]}, {"unrelated-object"})

    def test_partial_app_group_failure_preserves_state_and_azd(self) -> None:
        state = base_state()
        state["fail_group"] = "rg-app"
        result, state = self.run_case(
            state,
            "--apply",
            "--confirm-environment",
            "seller-test",
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("rg-state", state["groups"])
        self.assertIn("seller-test", state["azd"])

    def test_app_group_deletion_timeout_preserves_state_and_azd(self) -> None:
        state = base_state()
        state["stuck_group"] = "rg-app"
        result, state = self.run_case(
            state,
            "--apply",
            "--confirm-environment",
            "seller-test",
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("timed out", result.stderr)
        self.assertIn("rg-app", state["groups"])
        self.assertIn("rg-state", state["groups"])
        self.assertIn("seller-test", state["azd"])

    def test_partial_app_registration_failure_preserves_state_and_azd(self) -> None:
        state = base_state()
        state["fail_app"] = MSAL_CLIENT
        result, state = self.run_case(
            state,
            "--apply",
            "--confirm-environment",
            "seller-test",
            "--delete-app-registrations",
        )
        self.assertEqual(result.returncode, 1)
        self.assertNotIn("rg-app", state["groups"])
        self.assertIn("rg-state", state["groups"])
        self.assertIn("seller-test", state["azd"])

    def test_missing_resources_are_idempotent(self) -> None:
        state = base_state()
        state["groups"] = {"rg-unrelated": state["groups"]["rg-unrelated"]}
        state["azd"] = {}
        state["apps"] = []
        result, state = self.run_case(
            state,
            "--apply",
            "--confirm-environment",
            "seller-test",
            "--delete-app-registrations",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("rg-unrelated", state["groups"])

    def test_rejects_shell_metacharacters_before_calling_cli(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            marker = tmp_path / "owned"
            result, _ = run_teardown(
                tmp_path,
                base_state(),
                "--app-resource-group",
                f"rg-app;touch{marker}",
            )
            self.assertEqual(result.returncode, 1)
            self.assertFalse(marker.exists())


def fake_az() -> str:
    return """#!/usr/bin/env python3
import json, os, sys
path = os.environ["FAKE_STATE"]
state = json.load(open(path, encoding="utf-8"))
args = sys.argv[1:]
state["calls"].append(args)
out = ""
code = 0
if args[:2] == ["account", "show"]:
    out = json.dumps({"id": state["subscription"], "tenantId": "masked"})
elif args[:2] == ["group", "exists"]:
    out = str(args[args.index("--name") + 1] in state["groups"]).lower()
elif args[:2] == ["group", "show"]:
    group = state["groups"][args[args.index("--name") + 1]]
    out = json.dumps({"location": group["location"], "tags": group["tags"]})
elif args[:2] == ["resource", "list"]:
    out = json.dumps(state["groups"][args[args.index("--resource-group") + 1]]["resources"])
elif args[:2] == ["containerapp", "delete"]:
    group = state["groups"][args[args.index("--resource-group") + 1]]
    name = args[args.index("--name") + 1]
    group["resources"] = [item for item in group["resources"] if item["name"] != name]
elif args[:2] == ["containerapp", "show"]:
    group = state["groups"].get(args[args.index("--resource-group") + 1], {})
    name = args[args.index("--name") + 1]
    if not any(item["name"] == name for item in group.get("resources", [])):
        code = 3
elif args[:4] == ["containerapp", "env", "dotnet-component", "list"]:
    group = state["groups"][args[args.index("--resource-group") + 1]]
    environment = args[args.index("--environment") + 1]
    out = json.dumps([{"name": name} for name in group.get("components", {}).get(environment, [])])
elif args[:4] == ["containerapp", "env", "dotnet-component", "delete"]:
    group = state["groups"][args[args.index("--resource-group") + 1]]
    environment = args[args.index("--environment") + 1]
    name = args[args.index("--name") + 1]
    group["components"][environment] = [
        item for item in group.get("components", {}).get(environment, []) if item != name
    ]
elif args[:3] == ["containerapp", "env", "delete"]:
    group = state["groups"][args[args.index("--resource-group") + 1]]
    name = args[args.index("--name") + 1]
    group["resources"] = [item for item in group["resources"] if item["name"] != name]
elif args[:3] == ["containerapp", "env", "show"]:
    group = state["groups"].get(args[args.index("--resource-group") + 1], {})
    name = args[args.index("--name") + 1]
    if not any(item["name"] == name for item in group.get("resources", [])):
        code = 3
elif args[:3] == ["ad", "sp", "show"]:
    out = state["deploy_object_id"]
elif args[:3] == ["ad", "app", "list"]:
    out = json.dumps([{k: v for k, v in app.items() if k != "owners"} for app in state["apps"]])
elif args[:4] == ["ad", "app", "owner", "list"]:
    object_id = args[args.index("--id") + 1]
    out = json.dumps(next(app["owners"] for app in state["apps"] if app["id"] == object_id))
elif args[:3] == ["ad", "app", "delete"]:
    app_id = args[args.index("--id") + 1]
    if state.get("fail_app") == app_id:
        code = 1
        print("simulated app deletion failure", file=sys.stderr)
    else:
        state["apps"] = [app for app in state["apps"] if app["appId"] != app_id]
elif args[:2] == ["group", "delete"]:
    name = args[args.index("--name") + 1]
    if state.get("fail_group") == name:
        code = 1
        print("simulated failure", file=sys.stderr)
    elif state.get("stuck_group") == name:
        pass
    else:
        group = state["groups"].pop(name, None)
        for resource in (group or {}).get("resources", []):
            if resource["type"].lower() == "microsoft.keyvault/vaults":
                state["deleted_vaults"].append(resource["name"])
            elif resource["type"].lower() == "microsoft.cognitiveservices/accounts":
                state["deleted_cognitive"].append(resource["name"])
elif args[:2] == ["keyvault", "list-deleted"]:
    name = args[args.index("--query") + 1].split("'")[1]
    out = json.dumps([item for item in state["deleted_vaults"] if item == name])
elif args[:2] == ["keyvault", "purge"]:
    name = args[args.index("--name") + 1]
    state["deleted_vaults"] = [item for item in state["deleted_vaults"] if item != name]
elif args[:3] == ["cognitiveservices", "account", "list-deleted"]:
    name = args[args.index("--query") + 1].split("'")[1]
    out = json.dumps([item for item in state["deleted_cognitive"] if item == name])
elif args[:3] == ["cognitiveservices", "account", "purge"]:
    name = args[args.index("--name") + 1]
    state["deleted_cognitive"] = [item for item in state["deleted_cognitive"] if item != name]
else:
    code = 2
    print(f"unsupported az invocation: {args}", file=sys.stderr)
json.dump(state, open(path, "w", encoding="utf-8"), sort_keys=True)
if out:
    print(out)
raise SystemExit(code)
"""


def fake_azd() -> str:
    return """#!/usr/bin/env python3
import json, os, sys
path = os.environ["FAKE_STATE"]
state = json.load(open(path, encoding="utf-8"))
args = sys.argv[1:]
state["calls"].append(["azd", *args])
if args[:2] == ["env", "get-values"]:
    name = args[args.index("--environment") + 1]
    if name not in state["azd"]:
        code = 1
    else:
        print(json.dumps(state["azd"][name]))
        code = 0
elif args[:2] == ["env", "remove"]:
    state["azd"].pop(args[2], None)
    code = 0
else:
    code = 2
json.dump(state, open(path, "w", encoding="utf-8"), sort_keys=True)
raise SystemExit(code)
"""


if __name__ == "__main__":
    unittest.main()
