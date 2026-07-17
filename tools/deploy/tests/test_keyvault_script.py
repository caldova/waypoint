from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "tools" / "deploy" / "scripts" / "keyvault.sh"


def test_composed_api_keys_secret_is_not_rewritten_when_current(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "state.json"
    state_path.write_text(
        json.dumps(
            {
                "set_counts": {},
                "secrets": {
                    "waypoint-writer-key": "writer",
                    "waypoint-reader-key": "reader",
                    "waypoint-admin-key": "admin",
                    "postgres-app-password": "app-password",
                    "postgres-admin-password": "admin-password",
                },
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
        "AZURE_LOCATION": "swedencentral",
        "FAKE_AZ_STATE": str(state_path),
        "KV_NAME": "kv-test",
        "STATE_RG": "rg-test-state",
    }
    subprocess.run(["bash", str(SCRIPT)], check=True, env=env)
    first = json.loads(state_path.read_text(encoding="utf-8"))
    subprocess.run(["bash", str(SCRIPT)], check=True, env=env)
    second = json.loads(state_path.read_text(encoding="utf-8"))

    assert second == first
    assert second["set_counts"] == {"waypoint-api-keys": 1}
    assert second["secrets"]["waypoint-api-keys"] == (
        "aggregator:writer:writer;concierge:reader:reader;seed:admin:admin"
    )


def _fake_az() -> str:
    return """#!/usr/bin/env python3
import json
import os
import sys

path = os.environ["FAKE_AZ_STATE"]
with open(path, encoding="utf-8") as handle:
    state = json.load(handle)
args = sys.argv[1:]

if args[:2] == ["group", "create"]:
    pass
elif args[:2] == ["keyvault", "show"]:
    query = args[args.index("--query") + 1] if "--query" in args else None
    if query == "properties.vaultUri":
        print("https://kv-test.vault.azure.net/")
    elif query == "id":
        print("/subscriptions/test/resourceGroups/rg-test-state/providers/Microsoft.KeyVault/vaults/kv-test")
elif args[:3] == ["keyvault", "secret", "show"]:
    name = args[args.index("--name") + 1]
    value = state["secrets"].get(name)
    if value is None:
        raise SystemExit(1)
    print(value)
elif args[:3] == ["keyvault", "secret", "set"]:
    name = args[args.index("--name") + 1]
    value = args[args.index("--value") + 1]
    state["secrets"][name] = value
    state["set_counts"][name] = state["set_counts"].get(name, 0) + 1
else:
    raise SystemExit(f"unsupported fake az invocation: {args}")

with open(path, "w", encoding="utf-8") as handle:
    json.dump(state, handle, sort_keys=True)
"""
