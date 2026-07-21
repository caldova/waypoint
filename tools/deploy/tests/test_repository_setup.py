from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "tools/deploy/scripts/repository_setup.py"
SUBSCRIPTION = "11111111-1111-1111-1111-111111111111"


def run_setup(tmp_path: Path, state: dict, *extra: str) -> tuple[subprocess.CompletedProcess[str], dict]:
    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps(state), encoding="utf-8")
    gh = tmp_path / "gh"
    gh.write_text(fake_gh(), encoding="utf-8")
    gh.chmod(0o755)
    oidc = tmp_path / "oidc.sh"
    oidc.write_text("#!/usr/bin/env bash\nprintf '%s\\n' \"$@\" > \"$FAKE_OIDC_ARGS\"\n", encoding="utf-8")
    oidc.chmod(0o755)
    oidc_args = tmp_path / "oidc-args"
    env = {
        **os.environ,
        "PATH": f"{tmp_path}:{os.environ['PATH']}",
        "FAKE_STATE": str(state_path),
        "FAKE_OIDC_ARGS": str(oidc_args),
    }
    result = subprocess.run(
        [
            "python3",
            str(SCRIPT),
            "--owner",
            "seller",
            "--repo",
            "waypoint-demo",
            "--subscription-id",
            SUBSCRIPTION,
            "--oidc-script",
            str(oidc),
            *extra,
        ],
        text=True,
        capture_output=True,
        env=env,
    )
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["oidc_args"] = oidc_args.read_text(encoding="utf-8").splitlines() if oidc_args.exists() else []
    return result, state


class RepositorySetupTests(unittest.TestCase):
    def run_case(self, state: dict, *extra: str) -> tuple[subprocess.CompletedProcess[str], dict]:
        with tempfile.TemporaryDirectory() as directory:
            return run_setup(Path(directory), state, *extra)

    def test_prefers_template_then_verifies_admin_and_bootstraps_oidc(self) -> None:
        result, state = self.run_case({"template": True, "login": "operator", "repos": {}, "calls": []})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(any(call[:3] == ["repo", "create", "seller/waypoint-demo"] for call in state["calls"]))
        self.assertIn("--template", next(call for call in state["calls"] if call[:2] == ["repo", "create"]))
        self.assertEqual(state["oidc_args"][0:4], ["--owner", "seller", "--repo", "waypoint-demo"])
        self.assertIn("--azd-env-name", state["oidc_args"])
        self.assertEqual(json.loads(result.stdout)["repository_mode"], "template")

    def test_falls_back_to_real_fork_with_clear_result(self) -> None:
        result, state = self.run_case({"template": False, "login": "operator", "repos": {}, "calls": []})
        self.assertEqual(result.returncode, 0, result.stderr)
        fork = next(call for call in state["calls"] if call[:2] == ["repo", "fork"])
        self.assertEqual(fork[2], "caldova/waypoint")
        self.assertEqual(fork[fork.index("--org") + 1], "seller")
        output = json.loads(result.stdout)
        self.assertEqual(output["repository_mode"], "fork")
        self.assertIn("fork network", output["note"])

    def test_existing_repository_requires_admin(self) -> None:
        state = {
            "template": True,
            "login": "operator",
            "repos": {"seller/waypoint-demo": {"viewerPermission": "WRITE", "isFork": False, "parent": None}},
            "calls": [],
        }
        result, state = self.run_case(state)
        self.assertEqual(result.returncode, 1)
        self.assertFalse(state["oidc_args"])

    def test_rejects_argument_injection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            marker = tmp_path / "owned"
            result, _ = run_setup(
                tmp_path,
                {"template": True, "login": "operator", "repos": {}, "calls": []},
                "--repo",
                f"demo;touch{marker}",
            )
            self.assertEqual(result.returncode, 1)
            self.assertFalse(marker.exists())


def fake_gh() -> str:
    return """#!/usr/bin/env python3
import json, os, sys
path = os.environ["FAKE_STATE"]
state = json.load(open(path, encoding="utf-8"))
args = sys.argv[1:]
state["calls"].append(args)
code = 0
if args[:2] == ["auth", "status"]:
    pass
elif args[:2] == ["repo", "view"]:
    target = args[2]
    if target not in state["repos"]:
        code = 1
    else:
        print(json.dumps({"nameWithOwner": target, **state["repos"][target]}))
elif args[:2] == ["api", "repos/caldova/waypoint"]:
    print(str(state["template"]).lower())
elif args[:2] == ["api", "user"]:
    print(state["login"])
elif args[:2] == ["repo", "create"]:
    state["repos"][args[2]] = {"viewerPermission": "ADMIN", "isFork": False, "parent": None}
elif args[:2] == ["repo", "fork"]:
    owner = args[args.index("--org") + 1] if "--org" in args else state["login"]
    name = args[args.index("--fork-name") + 1]
    state["repos"][f"{owner}/{name}"] = {
        "viewerPermission": "ADMIN",
        "isFork": True,
        "parent": {"nameWithOwner": args[2]},
    }
else:
    code = 2
    print(f"unsupported gh invocation: {args}", file=sys.stderr)
json.dump(state, open(path, "w", encoding="utf-8"), sort_keys=True)
raise SystemExit(code)
"""


if __name__ == "__main__":
    unittest.main()
