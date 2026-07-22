"""Tests for the guided setup/deploy helper (tools/deploy/scripts/guided_setup_deploy.py)."""

from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).parents[1] / "scripts" / "guided_setup_deploy.py"
SPEC = importlib.util.spec_from_file_location("guided_setup_deploy", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
guided_setup_deploy = importlib.util.module_from_spec(SPEC)
# Dataclasses introspect sys.modules[cls.__module__] at class-creation time,
# so the module must be registered before exec_module runs.
sys.modules[SPEC.name] = guided_setup_deploy
SPEC.loader.exec_module(guided_setup_deploy)


def cmd(returncode=0, stdout="", stderr=""):
    return guided_setup_deploy.CommandResult(returncode=returncode, stdout=stdout, stderr=stderr)


class DeriveNamesTests(unittest.TestCase):
    def test_deterministic_for_same_inputs(self):
        a = guided_setup_deploy.derive_names("sub-1", "swedencentral", "caldova/waypoint")
        b = guided_setup_deploy.derive_names("sub-1", "swedencentral", "caldova/waypoint")
        self.assertEqual(a, b)
        self.assertEqual(a["azure_location"], "swedencentral")
        self.assertEqual(a["app_location"], "northeurope")

    def test_differs_when_subscription_differs(self):
        a = guided_setup_deploy.derive_names("sub-1", "swedencentral", "caldova/waypoint")
        b = guided_setup_deploy.derive_names("sub-2", "swedencentral", "caldova/waypoint")
        self.assertNotEqual(a["azd_env_name"], b["azd_env_name"])
        self.assertNotEqual(a["key_vault_name"], b["key_vault_name"])

    def test_differs_when_repo_differs(self):
        a = guided_setup_deploy.derive_names("sub-1", "swedencentral", "caldova/waypoint")
        b = guided_setup_deploy.derive_names("sub-1", "swedencentral", "caldova/waypoint-fork")
        self.assertNotEqual(a["azd_env_name"], b["azd_env_name"])

    def test_key_vault_name_respects_azure_constraints(self):
        names = guided_setup_deploy.derive_names(
            "11111111-2222-3333-4444-555555555555", "swedencentral", "some-org/a-very-long-repository-name-indeed"
        )
        kv_name = names["key_vault_name"]
        self.assertLessEqual(len(kv_name), 24)
        self.assertTrue(kv_name[0].isalpha())
        self.assertRegex(kv_name, r"^[a-z0-9-]+$")

    def test_rejects_missing_inputs(self):
        with self.assertRaises(ValueError):
            guided_setup_deploy.derive_names("", "swedencentral", "caldova/waypoint")
        with self.assertRaises(ValueError):
            guided_setup_deploy.derive_names("sub-1", "", "caldova/waypoint")
        with self.assertRaises(ValueError):
            guided_setup_deploy.derive_names("sub-1", "swedencentral", "")
        with self.assertRaises(ValueError):
            guided_setup_deploy.derive_names(
                "sub-1", "swedencentral", "caldova/waypoint", ""
            )

    def test_owner_and_repo_split_out(self):
        names = guided_setup_deploy.derive_names("sub-1", "swedencentral", "caldova/waypoint")
        self.assertEqual(names["owner"], "caldova")
        self.assertEqual(names["repo"], "waypoint")

    def test_sanitizes_hostile_repo_name(self):
        names = guided_setup_deploy.derive_names("sub-1", "swedencentral", "caldova/../../etc; rm -rf")
        for key in ("azd_env_name", "app_resource_group", "key_vault_name"):
            self.assertRegex(names[key], r"^[a-z0-9-]+$")


class CommandConstructionTests(unittest.TestCase):
    def test_oidc_args_is_list_no_shell_string(self):
        args = guided_setup_deploy.build_oidc_args(
            owner="caldova", repo="waypoint", subscription_id="sub-1", region="swedencentral"
        )
        self.assertIsInstance(args, list)
        self.assertEqual(args[0], "bash")
        self.assertIn("--subscription-id", args)
        self.assertIn("sub-1", args)
        self.assertIn(str(guided_setup_deploy.OIDC_SCRIPT), args)

    def test_dispatch_args_includes_ref_and_workflow(self):
        names = guided_setup_deploy.derive_names("sub-1", "swedencentral", "caldova/waypoint")
        args = guided_setup_deploy.build_dispatch_args(owner="caldova", repo="waypoint", names=names, ref="main")
        self.assertEqual(args[:4], ["gh", "workflow", "run", guided_setup_deploy.DEPLOY_WORKFLOW])
        self.assertIn("--ref", args)
        self.assertIn("app_location=northeurope", args)
        self.assertIn("main", args)
        self.assertIn("--repo", args)
        self.assertIn("caldova/waypoint", args)

    def test_dispatch_args_only_includes_nonempty_fields(self):
        args = guided_setup_deploy.build_dispatch_args(
            owner="caldova", repo="waypoint", names={"azure_location": "swedencentral"}, ref="main"
        )
        joined = " ".join(args)
        self.assertIn("azure_location=swedencentral", joined)
        self.assertNotIn("key_vault_name=", joined)

    def test_list_runs_args_scopes_workflow_and_repo(self):
        args = guided_setup_deploy.build_list_runs_args(owner="caldova", repo="waypoint", limit=3)
        self.assertIn("--workflow", args)
        self.assertIn(guided_setup_deploy.DEPLOY_WORKFLOW, args)
        self.assertIn("caldova/waypoint", args)
        self.assertIn("3", args)

    def test_run_view_args_uses_run_id_as_own_argument(self):
        args = guided_setup_deploy.build_run_view_args(owner="caldova", repo="waypoint", run_id="12345")
        self.assertIn("12345", args)

    def test_group_show_args_uses_resource_group(self):
        args = guided_setup_deploy.build_group_show_args(resource_group="rg-test")
        self.assertIn("rg-test", args)

    def test_default_runner_rejects_string_command(self):
        with self.assertRaises(TypeError):
            guided_setup_deploy.default_runner("gh workflow run deploy.yml")


class ConfirmationGatingTests(unittest.TestCase):
    """No mutating action may run without confirm being the literal boolean True."""

    def test_require_confirmation_rejects_false(self):
        with self.assertRaises(guided_setup_deploy.ConfirmationRequiredError):
            guided_setup_deploy.require_confirmation(False, "test action")

    def test_require_confirmation_rejects_truthy_string(self):
        with self.assertRaises(guided_setup_deploy.ConfirmationRequiredError):
            guided_setup_deploy.require_confirmation("true", "test action")

    def test_require_confirmation_rejects_truthy_int(self):
        with self.assertRaises(guided_setup_deploy.ConfirmationRequiredError):
            guided_setup_deploy.require_confirmation(1, "test action")

    def test_require_confirmation_accepts_literal_true(self):
        guided_setup_deploy.require_confirmation(True, "test action")  # must not raise

    def test_bootstrap_refuses_without_confirmation_and_never_calls_runner(self):
        calls = []

        def fake_run(args):
            calls.append(args)
            return cmd()

        with self.assertRaises(guided_setup_deploy.ConfirmationRequiredError):
            guided_setup_deploy.run_bootstrap(
                owner="caldova", repo="waypoint", subscription_id="sub-1", region="swedencentral",
                confirm=False, run=fake_run,
            )
        self.assertEqual(calls, [], "bootstrap must not invoke the runner without confirmation")

    def test_deploy_refuses_without_confirmation_and_never_calls_runner(self):
        calls = []

        def fake_run(args):
            calls.append(args)
            return cmd()

        with self.assertRaises(guided_setup_deploy.ConfirmationRequiredError):
            guided_setup_deploy.run_deploy(
                owner="caldova", repo="waypoint", names={}, confirm=False, run=fake_run,
            )
        self.assertEqual(calls, [], "deploy must not invoke the runner without confirmation")

    def test_bootstrap_runs_when_confirmed(self):
        calls = []

        def fake_run(args):
            calls.append(args)
            return cmd(stdout="Done.")

        result = guided_setup_deploy.run_bootstrap(
            owner="caldova", repo="waypoint", subscription_id="sub-1", region="swedencentral",
            confirm=True, run=fake_run,
        )
        self.assertTrue(result["ok"])
        self.assertEqual(len(calls), 1)


class FindNewestRunTests(unittest.TestCase):
    def test_returns_none_on_command_failure(self):
        self.assertIsNone(guided_setup_deploy.find_newest_run(cmd(returncode=1), 0.0))

    def test_returns_none_on_non_json(self):
        self.assertIsNone(guided_setup_deploy.find_newest_run(cmd(stdout="not json"), 0.0))

    def test_prefers_workflow_dispatch_event_and_newest(self):
        runs = [
            {"databaseId": 1, "event": "push", "createdAt": "2026-01-03T00:00:00Z", "status": "completed"},
            {"databaseId": 2, "event": "workflow_dispatch", "createdAt": "2026-01-01T00:00:00Z", "status": "completed"},
            {"databaseId": 3, "event": "workflow_dispatch", "createdAt": "2026-01-02T00:00:00Z", "status": "queued"},
        ]
        result = guided_setup_deploy.find_newest_run(cmd(stdout=json.dumps(runs)), 0.0)
        self.assertEqual(result["databaseId"], 3)

    def test_ignores_non_dispatch_runs(self):
        runs = [{"databaseId": 9, "event": "push", "createdAt": "2026-01-01T00:00:00Z"}]
        result = guided_setup_deploy.find_newest_run(cmd(stdout=json.dumps(runs)), 0.0)
        self.assertIsNone(result)

    def test_ignores_dispatch_runs_created_before_current_dispatch(self):
        runs = [
            {"databaseId": 8, "event": "workflow_dispatch", "createdAt": "2026-01-01T00:00:00Z"},
            {"databaseId": 9, "event": "workflow_dispatch", "createdAt": "2026-01-02T00:00:00Z"},
        ]
        result = guided_setup_deploy.find_newest_run(
            cmd(stdout=json.dumps(runs)),
            1767268800.0,  # 2026-01-01T12:00:00Z
        )
        self.assertEqual(result["databaseId"], 9)

    def test_returns_none_when_only_previous_dispatch_exists(self):
        runs = [
            {"databaseId": 8, "event": "workflow_dispatch", "createdAt": "2025-12-31T23:59:59Z"},
        ]
        result = guided_setup_deploy.find_newest_run(
            cmd(stdout=json.dumps(runs)),
            1767225600.0,  # 2026-01-01T00:00:00Z
        )
        self.assertIsNone(result)


class RunDeployPollingTests(unittest.TestCase):
    def test_deploy_dispatches_then_polls_until_run_found(self):
        calls = []
        sleeps = []

        responses = [
            cmd(stdout=""),  # dispatch
            cmd(stdout=json.dumps([])),  # first list: nothing yet
            cmd(
                stdout=json.dumps(
                    [{"databaseId": 42, "event": "workflow_dispatch", "createdAt": "2026-01-01T00:00:00Z",
                      "status": "in_progress", "conclusion": None, "url": "https://example/runs/42"}]
                )
            ),  # second list: found
        ]

        def fake_run(args):
            calls.append(args)
            return responses[len(calls) - 1]

        result = guided_setup_deploy.run_deploy(
            owner="caldova",
            repo="waypoint",
            names={"azure_location": "swedencentral"},
            confirm=True,
            run=fake_run,
            sleep=lambda seconds: sleeps.append(seconds),
            clock=lambda: 0.0,
            max_attempts=5,
            interval_seconds=1.0,
        )
        self.assertTrue(result["dispatched"])
        self.assertTrue(result["run_found"])
        self.assertEqual(result["run_id"], 42)
        self.assertEqual(len(sleeps), 1, "should sleep exactly once between the two list attempts")

    def test_deploy_does_not_attach_to_previous_dispatch(self):
        calls = []
        sleeps = []
        responses = [
            cmd(stdout=""),
            cmd(
                stdout=json.dumps(
                    [{"databaseId": 41, "event": "workflow_dispatch",
                      "createdAt": "2025-12-31T23:59:59Z", "status": "completed"}]
                )
            ),
            cmd(
                stdout=json.dumps(
                    [{"databaseId": 42, "event": "workflow_dispatch",
                      "createdAt": "2026-01-01T00:00:00Z", "status": "queued"}]
                )
            ),
        ]

        def fake_run(args):
            calls.append(args)
            return responses[len(calls) - 1]

        result = guided_setup_deploy.run_deploy(
            owner="caldova",
            repo="waypoint",
            names={},
            confirm=True,
            run=fake_run,
            sleep=lambda seconds: sleeps.append(seconds),
            clock=lambda: 1767225600.5,
            max_attempts=3,
            interval_seconds=1.0,
        )

        self.assertTrue(result["run_found"])
        self.assertEqual(result["run_id"], 42)
        self.assertEqual(len(sleeps), 1)

    def test_deploy_reports_dispatch_failure_without_polling(self):
        calls = []

        def fake_run(args):
            calls.append(args)
            return cmd(returncode=1, stderr="workflow not found")

        result = guided_setup_deploy.run_deploy(
            owner="caldova", repo="waypoint", names={}, confirm=True, run=fake_run,
        )
        self.assertFalse(result["dispatched"])
        self.assertEqual(len(calls), 1, "must not poll after a failed dispatch")

    def test_deploy_bounds_polling_and_reports_not_found(self):
        calls = []

        def fake_run(args):
            calls.append(args)
            if len(calls) == 1:
                return cmd(stdout="")  # dispatch
            return cmd(stdout=json.dumps([]))  # never finds a run

        result = guided_setup_deploy.run_deploy(
            owner="caldova", repo="waypoint", names={}, confirm=True, run=fake_run,
            sleep=lambda seconds: None, max_attempts=3, interval_seconds=0.01,
        )
        self.assertTrue(result["dispatched"])
        self.assertFalse(result["run_found"])
        # 1 dispatch call + max_attempts list calls, never unbounded.
        self.assertEqual(len(calls), 1 + 3)


class RunStatusTests(unittest.TestCase):
    def test_status_parses_payload(self):
        payload = {"status": "completed", "conclusion": "success", "url": "https://x", "displayTitle": "Deploy Azure"}

        def fake_run(args):
            return cmd(stdout=json.dumps(payload))

        result = guided_setup_deploy.run_status(owner="caldova", repo="waypoint", run_id="1", run=fake_run)
        self.assertTrue(result["ok"])
        self.assertEqual(result["conclusion"], "success")

    def test_status_reports_error_on_failure(self):
        def fake_run(args):
            return cmd(returncode=1, stderr="not found")

        result = guided_setup_deploy.run_status(owner="caldova", repo="waypoint", run_id="1", run=fake_run)
        self.assertFalse(result["ok"])


class LinksTests(unittest.TestCase):
    def test_evaluate_links_builds_https_urls(self):
        tags = {"keystone_web_fqdn": "web.example.com", "keystone_api_fqdn": "api.example.com"}
        result = guided_setup_deploy.evaluate_links(cmd(stdout=json.dumps(tags)))
        self.assertTrue(result["ok"])
        self.assertEqual(result["app_url"], "https://web.example.com")
        self.assertEqual(result["api_url"], "https://api.example.com")

    def test_evaluate_links_handles_missing_tags(self):
        result = guided_setup_deploy.evaluate_links(cmd(stdout="null"))
        self.assertTrue(result["ok"])
        self.assertEqual(result["app_url"], "")

    def test_evaluate_links_reports_error_on_command_failure(self):
        result = guided_setup_deploy.evaluate_links(cmd(returncode=1, stderr="not found"))
        self.assertFalse(result["ok"])


if __name__ == "__main__":
    unittest.main()
