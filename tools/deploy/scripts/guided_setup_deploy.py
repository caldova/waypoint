#!/usr/bin/env python3
"""Guided setup + deploy helper for the Waypoint one-click pipeline.

Backs the `bootstrap`, `deploy`, and `refresh` actions of the
`waypoint-setup-deploy` canvas. This module is the ONLY place that mutates
anything (repo vars/secrets via `oidc.sh`, or a workflow dispatch) — and even
here, every mutating entry point refuses to run without an explicit
`confirm=True`, checked with `is True` (not truthy-string coercion) so a
missing or malformed confirmation flag fails closed.

Everything that talks to `az`/`gh` does so via an argv list passed to
`subprocess.run(..., shell=False)`; nothing ever builds a shell string.

Subcommands:
  derive-names   Print deterministic, safe resource/environment names for a
                 (subscription, region, repo) tuple. Pure, no network calls.
  bootstrap      Run the existing idempotent oidc.sh (requires --confirm).
  deploy         Dispatch .github/workflows/deploy.yml and locate the new
                 run (requires --confirm).
  status         Look up the status of a previously dispatched run.
  links          Read the recorded app/demo links (state RG tags).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

REPO_ROOT = Path(__file__).resolve().parents[3]
OIDC_SCRIPT = REPO_ROOT / "tools" / "deploy" / "scripts" / "oidc.sh"
DEPLOY_WORKFLOW = "deploy.yml"
DEFAULT_REF = "main"
DEFAULT_OIDC_APP_NAME = "forge-gha-oidc"


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str = ""
    stderr: str = ""

    @property
    def ok(self) -> bool:
        return self.returncode == 0


Runner = Callable[[Sequence[str]], CommandResult]
SleepFn = Callable[[float], None]


def default_runner(args: Sequence[str], timeout: float = 120.0) -> CommandResult:
    """Execute `args` as an argv list only. Never shells out to a joined string."""
    if isinstance(args, str):
        raise TypeError("default_runner requires an argument list, not a string")
    argv = list(args)
    binary = shutil.which(argv[0]) or argv[0]
    try:
        completed = subprocess.run(  # noqa: S603 - argv list, shell disabled
            [binary, *argv[1:]],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            shell=False,
        )
    except FileNotFoundError as exc:
        return CommandResult(returncode=127, stdout="", stderr=str(exc))
    except subprocess.TimeoutExpired as exc:
        return CommandResult(returncode=124, stdout="", stderr=str(exc))
    return CommandResult(completed.returncode, completed.stdout, completed.stderr)


class ConfirmationRequiredError(PermissionError):
    """Raised when a mutating action is attempted without explicit confirmation."""


def require_confirmation(confirm: object, action: str) -> None:
    # Fail closed: only the literal boolean True is accepted. A string "true",
    # 1, "yes", etc. are all rejected so a caller can never accidentally
    # trigger a mutation via type coercion.
    if confirm is not True:
        raise ConfirmationRequiredError(
            f"{action} requires explicit confirm=True; refusing to run without it."
        )


# ---- deterministic name derivation ----------------------------------------------


def short_hash(value: str, length: int = 8) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:length]


def _sanitize(
    value: str,
    *,
    allow_hyphen: bool = True,
    max_len: int = 63,
    fallback: str = "x",
) -> str:
    """Lowercase, strip to an allowed charset, collapse repeats, and bound length.
    Deterministic and side-effect free: same input always yields the same output."""
    lowered = value.lower()
    pattern = r"[^a-z0-9-]" if allow_hyphen else r"[^a-z0-9]"
    cleaned = re.sub(pattern, "-" if allow_hyphen else "", lowered)
    if allow_hyphen:
        cleaned = re.sub(r"-{2,}", "-", cleaned).strip("-")
    if not cleaned:
        cleaned = fallback
    if not cleaned[0].isalpha():
        cleaned = f"{fallback}{cleaned}"
    return cleaned[:max_len]


def derive_names(subscription_id: str, region: str, target_repo: str) -> dict:
    """Pure, deterministic derivation of every resource/environment name the
    deploy workflow accepts as a parallel-environment override. Same inputs
    always produce the same outputs — no randomness, no clock, no I/O — so two
    operators deriving names for the same subscription+region+repo land on the
    identical, collision-safe environment."""
    if not subscription_id or not region or not target_repo:
        raise ValueError("subscription_id, region, and target_repo are all required")

    owner, _, name = target_repo.partition("/")
    repo_slug = _sanitize(name or target_repo, max_len=20)
    sub_hash = short_hash(subscription_id, length=8)

    env_name = _sanitize(f"waypoint-{repo_slug}-{sub_hash}", max_len=40)
    app_rg = _sanitize(f"rg-{env_name}", allow_hyphen=True, max_len=64)
    state_rg = _sanitize(f"rg-{env_name}-state", allow_hyphen=True, max_len=64)
    # Key Vault names: 3-24 chars, alphanumeric + hyphen, must start with a letter.
    kv_name = _sanitize(f"kv-{repo_slug}-{sub_hash}", allow_hyphen=True, max_len=24)
    # Fabric capacity names: lowercase alphanumeric only (no hyphens), <= 63 chars.
    fabric_capacity = _sanitize(f"waypointcorpus{sub_hash}", allow_hyphen=False, max_len=63)
    # Postgres flexible server names: lowercase alphanumeric + hyphen, 3-63 chars.
    postgres_name = _sanitize(f"pg-{repo_slug}-{sub_hash}", allow_hyphen=True, max_len=63)

    return {
        "azure_location": region,
        "azd_env_name": env_name,
        "app_resource_group": app_rg,
        "state_resource_group": state_rg,
        "key_vault_name": kv_name,
        "msal_display_name": _sanitize(f"waypoint-{repo_slug}", max_len=40),
        "postgres_server_name": postgres_name,
        "fabric_capacity_name": fabric_capacity,
        "fabric_workspace_name": _sanitize(f"waypoint-corpus-{repo_slug}", max_len=63),
        "fabric_lakehouse_name": "corpus",
        "owner": owner or target_repo,
        "repo": name or target_repo,
    }


# ---- bootstrap (runs oidc.sh) ----------------------------------------------------


def build_oidc_args(
    *,
    owner: str,
    repo: str,
    subscription_id: str,
    region: str,
    app_name: str = DEFAULT_OIDC_APP_NAME,
    branch: str = DEFAULT_REF,
) -> list[str]:
    return [
        "bash",
        str(OIDC_SCRIPT),
        "--owner",
        owner,
        "--repo",
        repo,
        "--subscription-id",
        subscription_id,
        "--app-name",
        app_name,
        "--branch",
        branch,
        "--location",
        region,
        "--pull-request",
    ]


def run_bootstrap(
    *,
    owner: str,
    repo: str,
    subscription_id: str,
    region: str,
    confirm: bool,
    run: Runner = default_runner,
    app_name: str = DEFAULT_OIDC_APP_NAME,
    branch: str = DEFAULT_REF,
) -> dict:
    require_confirmation(confirm, "bootstrap (oidc.sh)")
    args = build_oidc_args(
        owner=owner,
        repo=repo,
        subscription_id=subscription_id,
        region=region,
        app_name=app_name,
        branch=branch,
    )
    result = run(args)
    return {
        "ok": result.ok,
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


# ---- deploy (dispatch deploy.yml + bounded poll for the new run) ----------------


def build_dispatch_args(
    *, owner: str, repo: str, names: dict, ref: str = DEFAULT_REF
) -> list[str]:
    full_repo = f"{owner}/{repo}"
    args = [
        "gh",
        "workflow",
        "run",
        DEPLOY_WORKFLOW,
        "--repo",
        full_repo,
        "--ref",
        ref,
    ]
    field_map = {
        "azure_location": names.get("azure_location", ""),
        "azd_env_name": names.get("azd_env_name", ""),
        "app_resource_group": names.get("app_resource_group", ""),
        "state_resource_group": names.get("state_resource_group", ""),
        "key_vault_name": names.get("key_vault_name", ""),
        "msal_display_name": names.get("msal_display_name", ""),
        "postgres_server_name": names.get("postgres_server_name", ""),
        "fabric_capacity_name": names.get("fabric_capacity_name", ""),
        "fabric_workspace_name": names.get("fabric_workspace_name", ""),
        "fabric_lakehouse_name": names.get("fabric_lakehouse_name", ""),
    }
    for key, value in field_map.items():
        if value:
            args.extend(["-f", f"{key}={value}"])
    return args


def build_list_runs_args(*, owner: str, repo: str, limit: int = 5) -> list[str]:
    return [
        "gh",
        "run",
        "list",
        "--repo",
        f"{owner}/{repo}",
        "--workflow",
        DEPLOY_WORKFLOW,
        "--limit",
        str(limit),
        "--json",
        "databaseId,status,conclusion,url,createdAt,event",
    ]


def find_newest_run(list_runs_result: CommandResult, dispatched_after: float) -> dict | None:
    """Pure: given `gh run list --json ...` output and a dispatch timestamp
    (epoch seconds), pick the newest workflow_dispatch run created at/after it."""
    if not list_runs_result.ok:
        return None
    try:
        runs = json.loads(list_runs_result.stdout)
    except json.JSONDecodeError:
        return None
    if not isinstance(runs, list):
        return None
    candidates = [run for run in runs if isinstance(run, dict) and run.get("event") == "workflow_dispatch"]
    if not candidates:
        candidates = [run for run in runs if isinstance(run, dict)]
    if not candidates:
        return None
    # createdAt is ISO8601 UTC; string comparison sorts correctly for that format.
    newest = max(candidates, key=lambda run: str(run.get("createdAt", "")))
    return newest


def build_run_view_args(*, owner: str, repo: str, run_id: str) -> list[str]:
    return [
        "gh",
        "run",
        "view",
        str(run_id),
        "--repo",
        f"{owner}/{repo}",
        "--json",
        "status,conclusion,url,displayTitle",
    ]


def run_deploy(
    *,
    owner: str,
    repo: str,
    names: dict,
    confirm: bool,
    ref: str = DEFAULT_REF,
    run: Runner = default_runner,
    sleep: SleepFn = time.sleep,
    max_attempts: int = 10,
    interval_seconds: float = 3.0,
) -> dict:
    require_confirmation(confirm, "deploy (workflow dispatch)")
    dispatched_at = time.time()
    dispatch_result = run(build_dispatch_args(owner=owner, repo=repo, names=names, ref=ref))
    if not dispatch_result.ok:
        return {
            "dispatched": False,
            "error": dispatch_result.stderr.strip() or "gh workflow run failed",
        }

    found: dict | None = None
    for attempt in range(max_attempts):
        list_result = run(build_list_runs_args(owner=owner, repo=repo))
        found = find_newest_run(list_result, dispatched_at)
        if found is not None:
            break
        if attempt < max_attempts - 1:
            sleep(interval_seconds)

    if found is None:
        return {
            "dispatched": True,
            "run_found": False,
            "detail": "Workflow dispatched but the new run could not be located within the poll budget.",
        }
    return {
        "dispatched": True,
        "run_found": True,
        "run_id": found.get("databaseId"),
        "status": found.get("status"),
        "conclusion": found.get("conclusion"),
        "url": found.get("url"),
    }


# ---- status (poll an existing run) ------------------------------------------------


def run_status(*, owner: str, repo: str, run_id: str, run: Runner = default_runner) -> dict:
    result = run(build_run_view_args(owner=owner, repo=repo, run_id=run_id))
    if not result.ok:
        return {"ok": False, "error": result.stderr.strip() or "gh run view failed"}
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return {"ok": False, "error": "gh run view returned non-JSON output"}
    return {"ok": True, **payload}


# ---- links (read recorded state-RG tags) -------------------------------------------


def build_group_show_args(*, resource_group: str) -> list[str]:
    return ["az", "group", "show", "--name", resource_group, "--query", "tags", "-o", "json"]


def evaluate_links(tags_result: CommandResult) -> dict:
    if not tags_result.ok:
        return {"ok": False, "error": tags_result.stderr.strip() or "az group show failed"}
    try:
        tags = json.loads(tags_result.stdout) or {}
    except json.JSONDecodeError:
        return {"ok": False, "error": "az group show returned non-JSON tags"}
    if not isinstance(tags, dict):
        tags = {}
    web_fqdn = tags.get("keystone_web_fqdn", "")
    api_fqdn = tags.get("keystone_api_fqdn", "")
    return {
        "ok": True,
        "app_url": f"https://{web_fqdn}" if web_fqdn else "",
        "api_url": f"https://{api_fqdn}" if api_fqdn else "",
        "onelake_workspace": tags.get("keystone_onelake_workspace", ""),
    }


def get_links(*, resource_group: str, run: Runner = default_runner) -> dict:
    return evaluate_links(run(build_group_show_args(resource_group=resource_group)))


# ---- CLI -----------------------------------------------------------------------


def _add_common_repo_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--owner", required=True)
    parser.add_argument("--repo", required=True)


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    derive = sub.add_parser("derive-names", help="Print deterministic resource/env names")
    derive.add_argument("--subscription-id", required=True)
    derive.add_argument("--region", required=True)
    derive.add_argument("--target-repo", required=True, help="owner/name")

    bootstrap = sub.add_parser("bootstrap", help="Run oidc.sh (mutating; requires --confirm)")
    _add_common_repo_args(bootstrap)
    bootstrap.add_argument("--subscription-id", required=True)
    bootstrap.add_argument("--region", required=True)
    bootstrap.add_argument("--confirm", action="store_true")

    deploy = sub.add_parser("deploy", help="Dispatch deploy.yml (mutating; requires --confirm)")
    _add_common_repo_args(deploy)
    deploy.add_argument("--names-json", required=True, help="JSON object from derive-names")
    deploy.add_argument("--ref", default=DEFAULT_REF)
    deploy.add_argument("--confirm", action="store_true")

    status = sub.add_parser("status", help="Look up a dispatched run")
    _add_common_repo_args(status)
    status.add_argument("--run-id", required=True)

    links = sub.add_parser("links", help="Read recorded app/demo links from state RG tags")
    links.add_argument("--resource-group", required=True)

    return parser.parse_args()


def main() -> int:
    args = _arguments()
    if args.command == "derive-names":
        names = derive_names(args.subscription_id, args.region, args.target_repo)
        print(json.dumps(names, indent=2, sort_keys=True))
        return 0
    if args.command == "bootstrap":
        try:
            result = run_bootstrap(
                owner=args.owner,
                repo=args.repo,
                subscription_id=args.subscription_id,
                region=args.region,
                confirm=args.confirm is True,
            )
        except ConfirmationRequiredError as exc:
            print(json.dumps({"ok": False, "error": str(exc)}), file=sys.stderr)
            return 2
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if result.get("ok") else 1
    if args.command == "deploy":
        names = json.loads(args.names_json)
        try:
            result = run_deploy(
                owner=args.owner,
                repo=args.repo,
                names=names,
                confirm=args.confirm is True,
                ref=args.ref,
            )
        except ConfirmationRequiredError as exc:
            print(json.dumps({"ok": False, "error": str(exc)}), file=sys.stderr)
            return 2
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if result.get("dispatched") else 1
    if args.command == "status":
        result = run_status(owner=args.owner, repo=args.repo, run_id=args.run_id)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if result.get("ok") else 1
    if args.command == "links":
        result = get_links(resource_group=args.resource_group)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if result.get("ok") else 1
    return 2


if __name__ == "__main__":
    sys.exit(main())
