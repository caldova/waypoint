#!/usr/bin/env python3
"""Create an admin-controlled Waypoint repository and bootstrap Azure OIDC."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path


REPO_PART = re.compile(r"^[A-Za-z0-9_.-]+$")
UUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
ROOT = Path(__file__).resolve().parents[3]


class SetupError(RuntimeError):
    pass


def run(args: list[str], *, allow_failure: bool = False) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(args, text=True, capture_output=True, check=False)
    if result.returncode and not allow_failure:
        detail = result.stderr.strip() or result.stdout.strip() or f"exit {result.returncode}"
        raise SetupError(f"{' '.join(args[:3])} failed: {detail}")
    return result


def repository(target: str) -> dict[str, object] | None:
    result = run(
        ["gh", "repo", "view", target, "--json", "nameWithOwner,viewerPermission,isFork,parent"],
        allow_failure=True,
    )
    if result.returncode:
        return None
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise SetupError("gh repo view returned invalid JSON") from exc


def wait_for_repository(target: str) -> dict[str, object] | None:
    for attempt in range(5):
        current = repository(target)
        if current is not None:
            return current
        if attempt < 4:
            time.sleep(2)
    return None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--owner", required=True)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--source", default="caldova/waypoint")
    parser.add_argument("--visibility", choices=("private", "public", "internal"), default="private")
    parser.add_argument("--subscription-id", required=True)
    parser.add_argument("--branch", default="main")
    parser.add_argument("--location", default="swedencentral")
    parser.add_argument("--azd-env-name", default="waypoint-agents")
    parser.add_argument("--oidc-app-name", default="")
    parser.add_argument("--waypoint-app-name", default="")
    parser.add_argument("--oidc-script", type=Path, default=ROOT / "tools/deploy/scripts/oidc.sh")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        for label, value in (
            ("owner", args.owner),
            ("repository", args.repo),
            ("branch", args.branch),
            ("azd environment", args.azd_env_name),
        ):
            if not REPO_PART.fullmatch(value):
                raise SetupError(f"{label} contains unsupported characters")
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", args.source):
            raise SetupError("source must be owner/name")
        if not UUID.fullmatch(args.subscription_id):
            raise SetupError("subscription ID must be a UUID")
        if not args.oidc_script.is_file():
            raise SetupError(f"OIDC bootstrap script not found: {args.oidc_script}")

        run(["gh", "auth", "status"])
        target = f"{args.owner}/{args.repo}"
        current = wait_for_repository(target)
        creation = "existing"
        if current is None:
            source_template = run(["gh", "api", f"repos/{args.source}", "--jq", ".is_template"]).stdout.strip()
            if source_template == "true":
                run(["gh", "repo", "create", target, "--template", args.source, f"--{args.visibility}"])
                creation = "template"
            else:
                login = run(["gh", "api", "user", "--jq", ".login"]).stdout.strip()
                fork_args = [
                    "gh",
                    "repo",
                    "fork",
                    args.source,
                    "--fork-name",
                    args.repo,
                    "--clone=false",
                ]
                if args.owner != login:
                    fork_args.extend(["--org", args.owner])
                run(fork_args)
                creation = "fork"
            current = repository(target)

        if current is None or current.get("viewerPermission") != "ADMIN":
            raise SetupError(f"authenticated GitHub user does not administer {target}")

        oidc_app_name = args.oidc_app_name or f"waypoint-{args.repo}-gha-oidc"
        waypoint_app_name = args.waypoint_app_name or f"waypoint-{args.repo}"
        run(
            [
                "bash",
                str(args.oidc_script),
                "--owner",
                args.owner,
                "--repo",
                args.repo,
                "--subscription-id",
                args.subscription_id,
                "--app-name",
                oidc_app_name,
                "--waypoint-app-name",
                waypoint_app_name,
                "--branch",
                args.branch,
                "--location",
                args.location,
                "--azd-env-name",
                args.azd_env_name,
                "--pull-request",
            ]
        )
        print(
            json.dumps(
                {
                    "repository": target,
                    "repository_mode": creation,
                    "viewer_permission": "ADMIN",
                    "source": args.source,
                    "oidc_bootstrap": "complete",
                    "note": (
                        "Created from the source template."
                        if creation == "template"
                        else "Created as a GitHub fork; it remains in the source fork network."
                        if creation == "fork"
                        else "Reused the existing admin-controlled repository."
                    ),
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    except (OSError, SetupError) as exc:
        print(f"repository-setup: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
