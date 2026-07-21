#!/usr/bin/env python3
"""Admin readiness preflight for the guided Waypoint setup/deploy flow.

Runs a battery of non-mutating checks against the operator's local `az`/`gh`
sessions and the target Azure subscription/GitHub repository, and classifies
each as pass / warn / fail with a remediation hint. This is deliberately
read-only: it never writes GitHub repo config, never runs `oidc.sh`, and
never dispatches a workflow. Those mutating steps live in
`guided_setup_deploy.py` and always require an explicit `--confirm`.

Design notes for testability:
  - Every check is split into a pure `build_*_args()` (the exact argv list
    that would be executed — no shell strings, ever) and a pure
    `evaluate_*()` (classification logic given already-captured output).
    Tests exercise both without touching a real `az`/`gh` binary.
  - The only impure glue is `default_runner`, a thin `subprocess.run`
    wrapper, and `run_all_checks`, which sequences build -> run -> evaluate.

Usage:
  python3 admin_preflight.py \
    --subscription-id <SUBSCRIPTION_ID> \
    --tenant-id <TENANT_ID> \
    --repo owner/name \
    --region swedencentral \
    --json
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from typing import Callable, Sequence

STATUS_PASS = "pass"
STATUS_WARN = "warn"
STATUS_FAIL = "fail"
_STATUS_RANK = {STATUS_PASS: 0, STATUS_WARN: 1, STATUS_FAIL: 2}

# Resource providers the Waypoint deploy relies on (Container Apps, Key Vault,
# Foundry/Cognitive Services, Postgres, Fabric, monitoring). Kept in sync by
# hand with tools/deploy/scripts/*.sh; there is no single source-of-truth
# manifest for provider registration today.
REQUIRED_RESOURCE_PROVIDERS: tuple[str, ...] = (
    "Microsoft.App",
    "Microsoft.OperationalInsights",
    "Microsoft.Insights",
    "Microsoft.KeyVault",
    "Microsoft.CognitiveServices",
    "Microsoft.DBforPostgreSQL",
    "Microsoft.ContainerRegistry",
    "Microsoft.Fabric",
)

# Subscription-scope RBAC roles that can grant other role assignments
# (required so the OIDC service principal / operator can hand out roles to
# downstream managed identities during deploy).
SUBSCRIPTION_ROLE_ASSIGNMENT_ROLES: frozenset[str] = frozenset(
    {"Owner", "User Access Administrator"}
)

# Entra directory roles that can grant admin consent for the Graph
# application permission (Application.ReadWrite.OwnedBy) oidc.sh requests.
PRIVILEGED_DIRECTORY_ROLES: frozenset[str] = frozenset(
    {
        "Global Administrator",
        "Privileged Role Administrator",
        "Application Administrator",
        "Cloud Application Administrator",
    }
)


@dataclass(frozen=True)
class CheckResult:
    id: str
    label: str
    status: str
    detail: str
    remediation: str = ""

    def __post_init__(self) -> None:
        if self.status not in _STATUS_RANK:
            raise ValueError(f"invalid status {self.status!r} for check {self.id!r}")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "label": self.label,
            "status": self.status,
            "detail": self.detail,
            "remediation": self.remediation,
        }


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str = ""
    stderr: str = ""

    @property
    def ok(self) -> bool:
        return self.returncode == 0


@dataclass(frozen=True)
class Context:
    subscription_id: str
    tenant_id: str
    repo: str
    region: str = ""


Runner = Callable[[Sequence[str]], CommandResult]


def default_runner(args: Sequence[str], timeout: float = 30.0) -> CommandResult:
    """Execute `args` as an argv list. Never uses shell=True and never
    accepts a pre-joined command string — callers always pass a list."""
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


def classify_overall(checks: Sequence[CheckResult]) -> str:
    if not checks:
        return STATUS_WARN
    return max((check.status for check in checks), key=lambda s: _STATUS_RANK[s])


def _parse_json(text: str) -> object | None:
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None


# ---- 1. Azure CLI auth ------------------------------------------------------


def build_azure_auth_args() -> list[str]:
    return ["az", "account", "show", "-o", "json"]


def evaluate_azure_auth(result: CommandResult) -> tuple[CheckResult, dict | None]:
    if not result.ok:
        return (
            CheckResult(
                "azure_auth",
                "Azure CLI authentication",
                STATUS_FAIL,
                "`az account show` failed; the Azure CLI is not logged in.",
                "Run `az login` (or `az login --use-device-code`) and retry.",
            ),
            None,
        )
    account = _parse_json(result.stdout)
    if not isinstance(account, dict) or not account.get("id") or not account.get("tenantId"):
        return (
            CheckResult(
                "azure_auth",
                "Azure CLI authentication",
                STATUS_WARN,
                "`az account show` succeeded but returned an unexpected payload.",
                "Run `az account show` manually to confirm the active session.",
            ),
            None,
        )
    return (
        CheckResult(
            "azure_auth",
            "Azure CLI authentication",
            STATUS_PASS,
            f"Signed in as {account.get('user', {}).get('name', 'unknown')}.",
        ),
        account,
    )


# ---- 2. GitHub CLI auth ------------------------------------------------------


def build_gh_auth_args() -> list[str]:
    return ["gh", "auth", "status"]


def evaluate_gh_auth(result: CommandResult) -> CheckResult:
    if result.ok:
        return CheckResult(
            "gh_auth", "GitHub CLI authentication", STATUS_PASS, "`gh auth status` succeeded."
        )
    return CheckResult(
        "gh_auth",
        "GitHub CLI authentication",
        STATUS_FAIL,
        "`gh auth status` failed; the GitHub CLI is not logged in.",
        "Run `gh auth login` with a token that has repo admin scope and retry.",
    )


# ---- 3. Tenant/subscription match -------------------------------------------


def evaluate_tenant_subscription_match(
    account: dict | None, ctx: Context
) -> CheckResult:
    if account is None:
        return CheckResult(
            "tenant_subscription_match",
            "Tenant/subscription match",
            STATUS_FAIL,
            "Cannot verify tenant/subscription because Azure CLI auth failed.",
            "Fix Azure CLI authentication first, then re-run preflight.",
        )
    actual_tenant = str(account.get("tenantId") or "")
    actual_sub = str(account.get("id") or "")
    if ctx.tenant_id and actual_tenant.lower() != ctx.tenant_id.lower():
        return CheckResult(
            "tenant_subscription_match",
            "Tenant/subscription match",
            STATUS_FAIL,
            f"Signed-in tenant {actual_tenant} does not match requested tenant {ctx.tenant_id}.",
            f"Run `az login --tenant {ctx.tenant_id}` and retry.",
        )
    if ctx.subscription_id and actual_sub.lower() != ctx.subscription_id.lower():
        return CheckResult(
            "tenant_subscription_match",
            "Tenant/subscription match",
            STATUS_WARN,
            f"Active subscription {actual_sub} differs from requested {ctx.subscription_id}.",
            f"Run `az account set --subscription {ctx.subscription_id}` and retry.",
        )
    return CheckResult(
        "tenant_subscription_match",
        "Tenant/subscription match",
        STATUS_PASS,
        f"Tenant {actual_tenant} and subscription {actual_sub} match the request.",
    )


# ---- 4. Repo admin access -----------------------------------------------------


def build_repo_admin_args(repo: str) -> list[str]:
    return ["gh", "api", f"repos/{repo}", "--jq", ".permissions.admin"]


def evaluate_repo_admin_access(result: CommandResult, repo: str) -> CheckResult:
    if not result.ok:
        return CheckResult(
            "repo_admin_access",
            "Repository admin access",
            STATUS_FAIL,
            f"Could not read permissions for {repo} ({result.stderr.strip() or 'gh api failed'}).",
            "Confirm the repo name and that your GitHub token can read it.",
        )
    value = result.stdout.strip().lower()
    if value == "true":
        return CheckResult(
            "repo_admin_access",
            "Repository admin access",
            STATUS_PASS,
            f"You have admin access on {repo}.",
        )
    return CheckResult(
        "repo_admin_access",
        "Repository admin access",
        STATUS_FAIL,
        f"You do not have admin access on {repo} (required to set repo vars/secrets and OIDC).",
        "Ask a repo owner to grant admin access, or target a repo you administer.",
    )


# ---- 5. OIDC write access ------------------------------------------------------


def evaluate_oidc_write_access(repo_admin: CheckResult, repo: str) -> CheckResult:
    # Writing OIDC subject-claim customization and repo vars/secrets both
    # require repo admin; there is no narrower scope to probe independently,
    # so this check is derived from the admin-access result rather than
    # issuing a second network call.
    if repo_admin.status == STATUS_PASS:
        return CheckResult(
            "oidc_write_access",
            "OIDC / repo config write access",
            STATUS_PASS,
            f"Admin access on {repo} implies OIDC customization and repo var/secret write access.",
        )
    if repo_admin.status == STATUS_FAIL:
        return CheckResult(
            "oidc_write_access",
            "OIDC / repo config write access",
            STATUS_FAIL,
            "OIDC subject customization and repo vars/secrets require repo admin, which is missing.",
            "Resolve the repository admin access check first.",
        )
    return CheckResult(
        "oidc_write_access",
        "OIDC / repo config write access",
        STATUS_WARN,
        "Repo admin access could not be confirmed; OIDC write access is unverified.",
        "Re-run preflight once repo admin access can be confirmed.",
    )


# ---- 6. Required resource providers --------------------------------------------


def build_provider_args(namespace: str) -> list[str]:
    return ["az", "provider", "show", "--namespace", namespace, "--query", "registrationState", "-o", "tsv"]


def evaluate_required_providers(
    provider_states: dict[str, CommandResult],
) -> CheckResult:
    unregistered: list[str] = []
    unknown: list[str] = []
    for namespace, result in provider_states.items():
        if not result.ok:
            unknown.append(namespace)
            continue
        state = result.stdout.strip()
        if state != "Registered":
            unregistered.append(namespace)
    if unknown:
        return CheckResult(
            "required_providers",
            "Required resource providers",
            STATUS_WARN,
            f"Could not read registration state for: {', '.join(sorted(unknown))}.",
            "Re-run once Azure CLI can reach the subscription, or check manually with `az provider show`.",
        )
    if unregistered:
        commands = "; ".join(f"az provider register --namespace {ns}" for ns in sorted(unregistered))
        return CheckResult(
            "required_providers",
            "Required resource providers",
            STATUS_WARN,
            f"Not yet registered: {', '.join(sorted(unregistered))}.",
            f"Register before deploy: {commands}",
        )
    return CheckResult(
        "required_providers",
        "Required resource providers",
        STATUS_PASS,
        f"All {len(provider_states)} required resource providers are registered.",
    )


# ---- 7. RBAC role-assignment ability --------------------------------------------


def build_signed_in_principal_args() -> list[str]:
    return ["az", "ad", "signed-in-user", "show", "--query", "id", "-o", "tsv"]


def build_role_assignment_args(principal_id: str, subscription_id: str) -> list[str]:
    return [
        "az",
        "role",
        "assignment",
        "list",
        "--assignee",
        principal_id,
        "--scope",
        f"/subscriptions/{subscription_id}",
        "--query",
        "[].roleDefinitionName",
        "-o",
        "json",
    ]


def evaluate_rbac_role_assignment_ability(
    principal_result: CommandResult, roles_result: CommandResult | None
) -> CheckResult:
    if not principal_result.ok or not principal_result.stdout.strip():
        return CheckResult(
            "rbac_role_assignment",
            "RBAC role-assignment ability",
            STATUS_WARN,
            "Could not resolve the signed-in principal (may be a service principal, not a user).",
            "If deploying as a service principal, confirm it holds Owner or User Access "
            "Administrator on the subscription out of band.",
        )
    if roles_result is None or not roles_result.ok:
        return CheckResult(
            "rbac_role_assignment",
            "RBAC role-assignment ability",
            STATUS_WARN,
            "Could not list subscription role assignments for the signed-in principal.",
            "Check manually with `az role assignment list --assignee <you> --scope /subscriptions/<sub>`.",
        )
    roles = _parse_json(roles_result.stdout)
    role_names = set(roles) if isinstance(roles, list) else set()
    if role_names & SUBSCRIPTION_ROLE_ASSIGNMENT_ROLES:
        return CheckResult(
            "rbac_role_assignment",
            "RBAC role-assignment ability",
            STATUS_PASS,
            f"Signed-in principal holds: {', '.join(sorted(role_names & SUBSCRIPTION_ROLE_ASSIGNMENT_ROLES))}.",
        )
    return CheckResult(
        "rbac_role_assignment",
        "RBAC role-assignment ability",
        STATUS_FAIL,
        "Signed-in principal has neither Owner nor User Access Administrator on the subscription, "
        "so it cannot grant the role assignments the deploy needs.",
        "Ask a subscription Owner to grant you Owner or User Access Administrator, then re-run.",
    )


# ---- 8. Microsoft Graph admin-consent boundary ----------------------------------


def build_graph_member_of_args() -> list[str]:
    return [
        "az",
        "rest",
        "--method",
        "GET",
        "--url",
        "https://graph.microsoft.com/v1.0/me/memberOf",
        "--query",
        "value[].displayName",
        "-o",
        "json",
    ]


def evaluate_graph_admin_consent_boundary(result: CommandResult) -> CheckResult:
    # This boundary can only ever be a warn, never a fail: Copilot cannot grant
    # tenant-wide admin consent itself, and lacking a privileged role here is a
    # normal, expected state for most operators, not a broken environment.
    if not result.ok:
        return CheckResult(
            "graph_admin_consent_boundary",
            "Microsoft Graph admin-consent boundary",
            STATUS_WARN,
            "Could not read your Entra directory role memberships.",
            "Assume you will need a tenant admin to grant consent for "
            "Application.ReadWrite.OwnedBy during bootstrap.",
        )
    roles = _parse_json(result.stdout)
    role_names = set(roles) if isinstance(roles, list) else set()
    granted = role_names & PRIVILEGED_DIRECTORY_ROLES
    if granted:
        return CheckResult(
            "graph_admin_consent_boundary",
            "Microsoft Graph admin-consent boundary",
            STATUS_PASS,
            f"You hold a directory role that can grant admin consent: {', '.join(sorted(granted))}.",
        )
    return CheckResult(
        "graph_admin_consent_boundary",
        "Microsoft Graph admin-consent boundary",
        STATUS_WARN,
        "You do not hold a directory role that can grant admin consent "
        "(Global Administrator, Privileged Role Administrator, Application "
        "Administrator, or Cloud Application Administrator).",
        "Ask a tenant admin to grant consent for the Application.ReadWrite.OwnedBy "
        "Graph permission during bootstrap, or run bootstrap as/with that admin.",
    )


# ---- 9. Foundry model availability/quota ----------------------------------------


def build_foundry_usage_args(region: str) -> list[str]:
    return ["az", "cognitiveservices", "usage", "list", "--location", region, "-o", "json"]


def evaluate_foundry_model_quota(result: CommandResult, region: str) -> CheckResult:
    if not result.ok:
        return CheckResult(
            "foundry_model_quota",
            "Foundry model availability/quota",
            STATUS_WARN,
            f"Could not read Cognitive Services usage/quota for {region}.",
            "Verify model quota manually in the Azure AI Foundry portal before deploying.",
        )
    usage = _parse_json(result.stdout)
    if not isinstance(usage, list):
        return CheckResult(
            "foundry_model_quota",
            "Foundry model availability/quota",
            STATUS_WARN,
            f"Unexpected usage payload for {region}; quota could not be classified.",
            "Verify model quota manually in the Azure AI Foundry portal before deploying.",
        )
    if not usage:
        return CheckResult(
            "foundry_model_quota",
            "Foundry model availability/quota",
            STATUS_WARN,
            f"No Cognitive Services quota entries were returned for {region}.",
            "Confirm the subscription has Azure AI Foundry model quota in this region.",
        )
    exhausted = [
        entry
        for entry in usage
        if isinstance(entry, dict)
        and entry.get("limit") is not None
        and entry.get("currentValue") is not None
        and float(entry["currentValue"]) >= float(entry["limit"]) > 0
    ]
    if exhausted:
        names = ", ".join(str(entry.get("name", {}).get("value", "unknown")) for entry in exhausted)
        return CheckResult(
            "foundry_model_quota",
            "Foundry model availability/quota",
            STATUS_FAIL,
            f"Quota is exhausted in {region} for: {names}.",
            "Request a quota increase or choose a different region before deploying.",
        )
    return CheckResult(
        "foundry_model_quota",
        "Foundry model availability/quota",
        STATUS_PASS,
        f"Cognitive Services quota in {region} has headroom for {len(usage)} tracked SKUs.",
    )


# ---- 10. Fabric capacity/permissions --------------------------------------------


def build_fabric_capacity_args(subscription_id: str) -> list[str]:
    return [
        "az",
        "resource",
        "list",
        "--resource-type",
        "Microsoft.Fabric/capacities",
        "--subscription",
        subscription_id,
        "-o",
        "json",
    ]


def evaluate_fabric_capacity_permissions(result: CommandResult) -> CheckResult:
    if not result.ok:
        return CheckResult(
            "fabric_capacity_permissions",
            "Fabric capacity/permissions",
            STATUS_WARN,
            "Could not list Microsoft.Fabric/capacities in the subscription.",
            "Confirm you can reach Fabric capacities with `az resource list "
            "--resource-type Microsoft.Fabric/capacities`.",
        )
    capacities = _parse_json(result.stdout)
    if not isinstance(capacities, list) or not capacities:
        return CheckResult(
            "fabric_capacity_permissions",
            "Fabric capacity/permissions",
            STATUS_WARN,
            "No Fabric capacity exists yet in this subscription.",
            "Deploy will need to create one; confirm you (or the deploy identity) hold "
            "Fabric capacity-admin/creation rights in the Fabric admin portal.",
        )
    return CheckResult(
        "fabric_capacity_permissions",
        "Fabric capacity/permissions",
        STATUS_PASS,
        f"Found {len(capacities)} existing Fabric capacity/capacities in the subscription.",
    )


# ---- orchestration ---------------------------------------------------------------


def run_all_checks(run: Runner, ctx: Context) -> list[CheckResult]:
    checks: list[CheckResult] = []

    azure_auth_result = run(build_azure_auth_args())
    azure_auth_check, account = evaluate_azure_auth(azure_auth_result)
    checks.append(azure_auth_check)

    checks.append(evaluate_gh_auth(run(build_gh_auth_args())))
    checks.append(evaluate_tenant_subscription_match(account, ctx))

    repo_admin_check = evaluate_repo_admin_access(run(build_repo_admin_args(ctx.repo)), ctx.repo)
    checks.append(repo_admin_check)
    checks.append(evaluate_oidc_write_access(repo_admin_check, ctx.repo))

    provider_states = {ns: run(build_provider_args(ns)) for ns in REQUIRED_RESOURCE_PROVIDERS}
    checks.append(evaluate_required_providers(provider_states))

    principal_result = run(build_signed_in_principal_args())
    principal_id = principal_result.stdout.strip() if principal_result.ok else ""
    roles_result = (
        run(build_role_assignment_args(principal_id, ctx.subscription_id)) if principal_id else None
    )
    checks.append(evaluate_rbac_role_assignment_ability(principal_result, roles_result))

    checks.append(evaluate_graph_admin_consent_boundary(run(build_graph_member_of_args())))
    checks.append(evaluate_foundry_model_quota(run(build_foundry_usage_args(ctx.region)), ctx.region))
    checks.append(evaluate_fabric_capacity_permissions(run(build_fabric_capacity_args(ctx.subscription_id))))

    return checks


def render_report(checks: Sequence[CheckResult], ctx: Context) -> dict:
    return {
        "overall": classify_overall(checks),
        "subscription_id": ctx.subscription_id,
        "tenant_id": ctx.tenant_id,
        "repo": ctx.repo,
        "region": ctx.region,
        "checks": [check.to_dict() for check in checks],
    }


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--subscription-id", required=True)
    parser.add_argument("--tenant-id", required=True)
    parser.add_argument("--repo", required=True, help="owner/name")
    parser.add_argument("--region", required=True)
    parser.add_argument("--json", action="store_true", help="print machine-readable JSON only")
    return parser.parse_args()


def main() -> int:
    args = _arguments()
    ctx = Context(
        subscription_id=args.subscription_id,
        tenant_id=args.tenant_id,
        repo=args.repo,
        region=args.region,
    )
    checks = run_all_checks(default_runner, ctx)
    report = render_report(checks, ctx)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"Overall: {report['overall']}")
        for check in report["checks"]:
            print(f"[{check['status'].upper():4}] {check['label']}: {check['detail']}")
            if check["remediation"]:
                print(f"        -> {check['remediation']}")
    return 0 if report["overall"] != STATUS_FAIL else 1


if __name__ == "__main__":
    sys.exit(main())
