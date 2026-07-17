from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "tools" / "deploy" / "scripts" / "msal.sh"


def test_ensure_reconciles_scopes_and_roles_idempotently(tmp_path: Path) -> None:
    state_path = tmp_path / "state.json"
    state_path.write_text(
        json.dumps(
            {
                "appId": "00000000-0000-0000-0000-000000000001",
                "id": "00000000-0000-0000-0000-000000000002",
                "identifierUris": [],
                "api": {"oauth2PermissionScopes": []},
                "appRoles": [],
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
    }
    subprocess.run(["bash", str(SCRIPT), "ensure"], check=True, env=env)
    first = json.loads(state_path.read_text(encoding="utf-8"))
    subprocess.run(["bash", str(SCRIPT), "ensure"], check=True, env=env)
    second = json.loads(state_path.read_text(encoding="utf-8"))

    assert second == first
    assert first["identifierUris"] == [f"api://{first['appId']}"]
    assert first["api"]["requestedAccessTokenVersion"] == 2
    assert {scope["value"] for scope in first["api"]["oauth2PermissionScopes"]} == {
        "user_impersonation",
    }
    assert {role["value"] for role in first["appRoles"]} == {
        "Waypoint.Admin",
        "Waypoint.Read",
        "Waypoint.Write",
    }


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
elif args[:3] == ["ad", "app", "update"]:
    uri = args[args.index("--identifier-uris") + 1]
    state["identifierUris"] = [uri]
elif args[0] == "rest" and args[args.index("--method") + 1] == "GET":
    print(json.dumps({
        "appRoles": state["appRoles"],
        "scopes": state["api"]["oauth2PermissionScopes"],
    }))
elif args[0] == "rest" and args[args.index("--method") + 1] == "PATCH":
    body = json.loads(args[args.index("--body") + 1])
    if "api" in body:
        state["api"] = body["api"]
    if "appRoles" in body:
        state["appRoles"] = body["appRoles"]
else:
    raise SystemExit(f"unsupported fake az invocation: {args}")

with open(path, "w", encoding="utf-8") as handle:
    json.dump(state, handle, sort_keys=True)
"""
