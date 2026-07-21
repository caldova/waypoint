"""Tests for the admin readiness preflight (tools/deploy/scripts/admin_preflight.py)."""

from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).parents[1] / "scripts" / "admin_preflight.py"
SPEC = importlib.util.spec_from_file_location("admin_preflight", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
admin_preflight = importlib.util.module_from_spec(SPEC)
# Dataclasses introspect sys.modules[cls.__module__] at class-creation time,
# so the module must be registered before exec_module runs.
sys.modules[SPEC.name] = admin_preflight
SPEC.loader.exec_module(admin_preflight)


def cmd(returncode=0, stdout="", stderr=""):
    return admin_preflight.CommandResult(returncode=returncode, stdout=stdout, stderr=stderr)


class CommandConstructionTests(unittest.TestCase):
    """Every build_* helper must return a plain argv list — never a shell string —
    with user-supplied values passed as discrete elements (no interpolation)."""

    def test_azure_auth_args_is_list(self):
        args = admin_preflight.build_azure_auth_args()
        self.assertIsInstance(args, list)
        self.assertEqual(args, ["az", "account", "show", "-o", "json"])

    def test_gh_auth_args_is_list(self):
        self.assertEqual(admin_preflight.build_gh_auth_args(), ["gh", "auth", "status"])

    def test_repo_admin_args_embeds_repo_as_discrete_segment(self):
        args = admin_preflight.build_repo_admin_args("caldova/waypoint")
        self.assertIsInstance(args, list)
        self.assertIn("repos/caldova/waypoint", args)
        # The repo value must never be concatenated into a shell-executable string.
        self.assertNotIn("; rm -rf /", " ".join(args))

    def test_provider_args_uses_namespace_as_own_argument(self):
        args = admin_preflight.build_provider_args("Microsoft.App")
        self.assertEqual(
            args,
            ["az", "provider", "show", "--namespace", "Microsoft.App", "--query", "registrationState", "-o", "tsv"],
        )

    def test_role_assignment_args_scopes_to_subscription(self):
        args = admin_preflight.build_role_assignment_args("principal-1", "sub-1")
        self.assertIn("/subscriptions/sub-1", args)
        self.assertIn("principal-1", args)

    def test_foundry_usage_args_uses_region(self):
        args = admin_preflight.build_foundry_usage_args("swedencentral")
        self.assertIn("swedencentral", args)

    def test_fabric_capacity_args_uses_subscription(self):
        args = admin_preflight.build_fabric_capacity_args("sub-1")
        self.assertIn("sub-1", args)

    def test_default_runner_rejects_string_command(self):
        with self.assertRaises(TypeError):
            admin_preflight.default_runner("az account show")


class EvaluateAzureAuthTests(unittest.TestCase):
    def test_fail_closed_on_nonzero_exit(self):
        check, account = admin_preflight.evaluate_azure_auth(cmd(returncode=1, stderr="not logged in"))
        self.assertEqual(check.status, admin_preflight.STATUS_FAIL)
        self.assertIsNone(account)

    def test_pass_on_valid_account(self):
        payload = json.dumps({"id": "sub-1", "tenantId": "tenant-1", "user": {"name": "a@b.com"}})
        check, account = admin_preflight.evaluate_azure_auth(cmd(stdout=payload))
        self.assertEqual(check.status, admin_preflight.STATUS_PASS)
        self.assertEqual(account["id"], "sub-1")

    def test_warn_on_unparseable_payload(self):
        check, account = admin_preflight.evaluate_azure_auth(cmd(stdout="not json"))
        self.assertEqual(check.status, admin_preflight.STATUS_WARN)
        self.assertIsNone(account)


class EvaluateTenantSubscriptionMatchTests(unittest.TestCase):
    def _ctx(self, **overrides):
        defaults = dict(subscription_id="sub-1", tenant_id="tenant-1", repo="o/r", region="swedencentral")
        defaults.update(overrides)
        return admin_preflight.Context(**defaults)

    def test_fail_when_account_missing(self):
        result = admin_preflight.evaluate_tenant_subscription_match(None, self._ctx())
        self.assertEqual(result.status, admin_preflight.STATUS_FAIL)

    def test_fail_on_tenant_mismatch(self):
        account = {"id": "sub-1", "tenantId": "other-tenant"}
        result = admin_preflight.evaluate_tenant_subscription_match(account, self._ctx())
        self.assertEqual(result.status, admin_preflight.STATUS_FAIL)

    def test_warn_on_subscription_mismatch_only(self):
        account = {"id": "other-sub", "tenantId": "tenant-1"}
        result = admin_preflight.evaluate_tenant_subscription_match(account, self._ctx())
        self.assertEqual(result.status, admin_preflight.STATUS_WARN)

    def test_pass_when_both_match_case_insensitively(self):
        account = {"id": "SUB-1", "tenantId": "TENANT-1"}
        result = admin_preflight.evaluate_tenant_subscription_match(account, self._ctx())
        self.assertEqual(result.status, admin_preflight.STATUS_PASS)


class EvaluateRepoAdminAndOidcTests(unittest.TestCase):
    def test_repo_admin_pass(self):
        result = admin_preflight.evaluate_repo_admin_access(cmd(stdout="true\n"), "o/r")
        self.assertEqual(result.status, admin_preflight.STATUS_PASS)

    def test_repo_admin_fail_when_false(self):
        result = admin_preflight.evaluate_repo_admin_access(cmd(stdout="false\n"), "o/r")
        self.assertEqual(result.status, admin_preflight.STATUS_FAIL)

    def test_repo_admin_fail_on_error(self):
        result = admin_preflight.evaluate_repo_admin_access(cmd(returncode=1, stderr="404"), "o/r")
        self.assertEqual(result.status, admin_preflight.STATUS_FAIL)

    def test_oidc_write_access_mirrors_repo_admin_pass(self):
        admin_check = admin_preflight.evaluate_repo_admin_access(cmd(stdout="true"), "o/r")
        result = admin_preflight.evaluate_oidc_write_access(admin_check, "o/r")
        self.assertEqual(result.status, admin_preflight.STATUS_PASS)

    def test_oidc_write_access_fails_when_admin_fails(self):
        admin_check = admin_preflight.evaluate_repo_admin_access(cmd(stdout="false"), "o/r")
        result = admin_preflight.evaluate_oidc_write_access(admin_check, "o/r")
        self.assertEqual(result.status, admin_preflight.STATUS_FAIL)


class EvaluateRequiredProvidersTests(unittest.TestCase):
    def test_pass_when_all_registered(self):
        states = {ns: cmd(stdout="Registered\n") for ns in admin_preflight.REQUIRED_RESOURCE_PROVIDERS}
        result = admin_preflight.evaluate_required_providers(states)
        self.assertEqual(result.status, admin_preflight.STATUS_PASS)

    def test_warn_when_some_unregistered(self):
        states = {ns: cmd(stdout="Registered\n") for ns in admin_preflight.REQUIRED_RESOURCE_PROVIDERS}
        first = admin_preflight.REQUIRED_RESOURCE_PROVIDERS[0]
        states[first] = cmd(stdout="NotRegistered\n")
        result = admin_preflight.evaluate_required_providers(states)
        self.assertEqual(result.status, admin_preflight.STATUS_WARN)
        self.assertIn(first, result.remediation)

    def test_warn_when_probe_errors(self):
        states = {ns: cmd(returncode=1) for ns in admin_preflight.REQUIRED_RESOURCE_PROVIDERS}
        result = admin_preflight.evaluate_required_providers(states)
        self.assertEqual(result.status, admin_preflight.STATUS_WARN)


class EvaluateRbacRoleAssignmentTests(unittest.TestCase):
    def test_warn_when_principal_unresolved(self):
        result = admin_preflight.evaluate_rbac_role_assignment_ability(cmd(returncode=1), None)
        self.assertEqual(result.status, admin_preflight.STATUS_WARN)

    def test_warn_when_roles_probe_fails(self):
        result = admin_preflight.evaluate_rbac_role_assignment_ability(cmd(stdout="principal-1"), cmd(returncode=1))
        self.assertEqual(result.status, admin_preflight.STATUS_WARN)

    def test_pass_when_owner_role_present(self):
        roles = cmd(stdout=json.dumps(["Owner", "Reader"]))
        result = admin_preflight.evaluate_rbac_role_assignment_ability(cmd(stdout="principal-1"), roles)
        self.assertEqual(result.status, admin_preflight.STATUS_PASS)

    def test_fail_when_no_capable_role(self):
        roles = cmd(stdout=json.dumps(["Reader", "Contributor"]))
        result = admin_preflight.evaluate_rbac_role_assignment_ability(cmd(stdout="principal-1"), roles)
        self.assertEqual(result.status, admin_preflight.STATUS_FAIL)


class EvaluateGraphAdminConsentBoundaryTests(unittest.TestCase):
    def test_never_fails_only_warns_or_passes_on_error(self):
        result = admin_preflight.evaluate_graph_admin_consent_boundary(cmd(returncode=1))
        self.assertEqual(result.status, admin_preflight.STATUS_WARN)

    def test_pass_when_privileged_role_present(self):
        roles = cmd(stdout=json.dumps(["Global Administrator", "Some Other Role"]))
        result = admin_preflight.evaluate_graph_admin_consent_boundary(roles)
        self.assertEqual(result.status, admin_preflight.STATUS_PASS)

    def test_warn_never_fail_when_no_privileged_role(self):
        roles = cmd(stdout=json.dumps(["Reader", "Guest"]))
        result = admin_preflight.evaluate_graph_admin_consent_boundary(roles)
        self.assertEqual(result.status, admin_preflight.STATUS_WARN)
        self.assertNotEqual(result.status, admin_preflight.STATUS_FAIL)


class EvaluateFoundryModelQuotaTests(unittest.TestCase):
    def test_warn_on_probe_error(self):
        result = admin_preflight.evaluate_foundry_model_quota(cmd(returncode=1), "swedencentral")
        self.assertEqual(result.status, admin_preflight.STATUS_WARN)

    def test_warn_on_empty_usage(self):
        result = admin_preflight.evaluate_foundry_model_quota(cmd(stdout="[]"), "swedencentral")
        self.assertEqual(result.status, admin_preflight.STATUS_WARN)

    def test_pass_with_headroom(self):
        usage = json.dumps([{"name": {"value": "OpenAI.Standard.gpt-5.5"}, "currentValue": 1, "limit": 100}])
        result = admin_preflight.evaluate_foundry_model_quota(cmd(stdout=usage), "swedencentral")
        self.assertEqual(result.status, admin_preflight.STATUS_PASS)

    def test_fail_when_quota_exhausted(self):
        usage = json.dumps([{"name": {"value": "OpenAI.Standard.gpt-5.5"}, "currentValue": 100, "limit": 100}])
        result = admin_preflight.evaluate_foundry_model_quota(cmd(stdout=usage), "swedencentral")
        self.assertEqual(result.status, admin_preflight.STATUS_FAIL)


class EvaluateFabricCapacityPermissionsTests(unittest.TestCase):
    def test_warn_on_probe_error(self):
        result = admin_preflight.evaluate_fabric_capacity_permissions(cmd(returncode=1))
        self.assertEqual(result.status, admin_preflight.STATUS_WARN)

    def test_warn_when_no_capacity_exists(self):
        result = admin_preflight.evaluate_fabric_capacity_permissions(cmd(stdout="[]"))
        self.assertEqual(result.status, admin_preflight.STATUS_WARN)

    def test_pass_when_capacity_exists(self):
        result = admin_preflight.evaluate_fabric_capacity_permissions(cmd(stdout=json.dumps([{"name": "cap1"}])))
        self.assertEqual(result.status, admin_preflight.STATUS_PASS)


class ClassifyOverallTests(unittest.TestCase):
    def _check(self, status):
        return admin_preflight.CheckResult("id", "label", status, "detail")

    def test_empty_is_warn(self):
        self.assertEqual(admin_preflight.classify_overall([]), admin_preflight.STATUS_WARN)

    def test_all_pass_is_pass(self):
        checks = [self._check(admin_preflight.STATUS_PASS) for _ in range(3)]
        self.assertEqual(admin_preflight.classify_overall(checks), admin_preflight.STATUS_PASS)

    def test_any_warn_without_fail_is_warn(self):
        checks = [self._check(admin_preflight.STATUS_PASS), self._check(admin_preflight.STATUS_WARN)]
        self.assertEqual(admin_preflight.classify_overall(checks), admin_preflight.STATUS_WARN)

    def test_any_fail_dominates(self):
        checks = [
            self._check(admin_preflight.STATUS_PASS),
            self._check(admin_preflight.STATUS_WARN),
            self._check(admin_preflight.STATUS_FAIL),
        ]
        self.assertEqual(admin_preflight.classify_overall(checks), admin_preflight.STATUS_FAIL)

    def test_invalid_status_rejected(self):
        with self.assertRaises(ValueError):
            admin_preflight.CheckResult("id", "label", "bogus", "detail")


class RunAllChecksOrchestrationTests(unittest.TestCase):
    """End-to-end with a fully fake runner: confirms the orchestrator issues the
    expected sequence of read-only commands and never mutates anything."""

    def test_run_all_checks_never_issues_write_commands(self):
        calls: list[list[str]] = []

        def fake_run(args):
            calls.append(list(args))
            if args[:3] == ["az", "account", "show"]:
                return cmd(stdout=json.dumps({"id": "sub-1", "tenantId": "tenant-1", "user": {"name": "a@b.com"}}))
            if args[:2] == ["gh", "auth"]:
                return cmd(returncode=0)
            if args[:2] == ["gh", "api"] and "permissions.admin" in args[-1]:
                return cmd(stdout="true")
            if args[:3] == ["az", "provider", "show"]:
                return cmd(stdout="Registered")
            if args[:4] == ["az", "ad", "signed-in-user", "show"]:
                return cmd(stdout="principal-1")
            if args[:4] == ["az", "role", "assignment", "list"]:
                return cmd(stdout=json.dumps(["Owner"]))
            if any("graph.microsoft.com/v1.0/me/memberOf" in part for part in args):
                return cmd(stdout=json.dumps(["Global Administrator"]))
            if args[:3] == ["az", "cognitiveservices", "usage"]:
                return cmd(stdout="[]")
            if args[:3] == ["az", "resource", "list"]:
                return cmd(stdout="[]")
            raise AssertionError(f"unexpected command: {args}")

        ctx = admin_preflight.Context(
            subscription_id="sub-1", tenant_id="tenant-1", repo="o/r", region="swedencentral"
        )
        checks = admin_preflight.run_all_checks(fake_run, ctx)
        self.assertEqual(len(checks), 10)

        mutating_verbs = {"create", "set", "delete", "update", "register", "assign"}
        for call in calls:
            self.assertFalse(
                mutating_verbs & set(call),
                f"admin_preflight must never issue a mutating command, saw: {call}",
            )


if __name__ == "__main__":
    unittest.main()
