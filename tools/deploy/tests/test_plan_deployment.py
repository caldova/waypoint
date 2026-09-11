from __future__ import annotations

import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "tools" / "deploy" / "scripts" / "plan_deployment.py"
MANIFEST = ROOT / "tools" / "deploy" / "deployment.manifest.json"
SPEC = importlib.util.spec_from_file_location("plan_deployment", SCRIPT)
assert SPEC and SPEC.loader
planner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(planner)


class DeploymentPlannerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))

    def plan(self, paths: list[str], **kwargs):
        return planner.build_plan(
            self.manifest,
            paths,
            base=kwargs.pop("base", "base"),
            head=kwargs.pop("head", "head"),
            **kwargs,
        )

    def test_app_path_maps_to_app_wiring_and_acceptance(self) -> None:
        plan = self.plan(["apps/waypoint/api/app/main.py"])

        self.assertTrue(plan["stages"]["app"]["run"])
        self.assertTrue(plan["stages"]["wiring"]["run"])
        self.assertTrue(plan["stages"]["acceptance"]["run"])
        self.assertFalse(plan["stages"]["foundry_infrastructure"]["run"])

    def test_shared_workflow_and_manifest_changes_force_full(self) -> None:
        for path in (
            ".github/workflows/deploy.yml",
            "tools/deploy/deployment.manifest.json",
        ):
            with self.subTest(path=path):
                plan = self.plan([path])
                self.assertTrue(plan["full_deployment"])
                self.assertTrue(all(stage["run"] for stage in plan["stages"].values()))
                self.assertEqual(
                    set(plan["selected_agents"]),
                    set(self.manifest["deployment_impact"]["agents"]),
                )

    def test_agent_path_selects_only_that_agent(self) -> None:
        plan = self.plan(
            ["modules/agents/contract-policy-expert/prompt.md"]
        )

        self.assertEqual(plan["selected_agents"], ["contract-policy-expert"])
        self.assertTrue(plan["stages"]["deploy_agents"]["run"])
        self.assertTrue(plan["stages"]["acceptance"]["run"])
        self.assertFalse(plan["stages"]["foundry_infrastructure"]["run"])

    def test_contract_corpus_change_skips_waypoint_seed(self) -> None:
        plan = self.plan(
            [
                "modules/corpus/data/contracts/source-markdown/"
                "sup-001-aster-ridge-biomanufacturing-sow.md"
            ]
        )

        self.assertTrue(plan["stages"]["contracts_kb"]["run"])
        self.assertFalse(plan["stages"]["corpus_seed"]["run"])
        self.assertFalse(plan["stages"]["seed_import"]["run"])

    def test_invoice_corpus_change_generates_seed_without_contracts_kb(self) -> None:
        plan = self.plan(
            ["modules/corpus/data/invoices/supplier-invoices.json"]
        )

        self.assertTrue(plan["stages"]["corpus_seed"]["run"])
        self.assertTrue(plan["stages"]["seed_import"]["run"])
        self.assertFalse(plan["stages"]["contracts_kb"]["run"])

    def test_unknown_path_uses_conservative_full_deployment(self) -> None:
        plan = self.plan(["new-platform/component/config.toml"])

        self.assertEqual(plan["mode"], "conservative_full")
        self.assertTrue(plan["full_deployment"])
        self.assertEqual(plan["unknown_paths"], ["new-platform/component/config.toml"])

    def test_eval_and_optimization_assets_are_non_deployable_stages(self) -> None:
        eval_plan = self.plan(["modules/evals/graders/caliber_default.py"])
        optimization_plan = self.plan(["modules/optimization/docs/TUNE.md"])

        self.assertTrue(eval_plan["stages"]["evals"]["run"])
        self.assertFalse(eval_plan["stages"]["evals"]["deployable"])
        self.assertFalse(eval_plan["has_deployment_work"])
        self.assertTrue(optimization_plan["stages"]["optimization"]["run"])
        self.assertFalse(optimization_plan["stages"]["optimization"]["deployable"])
        self.assertFalse(optimization_plan["has_deployment_work"])

    def test_first_deployment_runs_every_stage(self) -> None:
        plan = self.plan([], base=None, initial=True)

        self.assertEqual(plan["mode"], "initial")
        self.assertTrue(plan["full_deployment"])
        self.assertTrue(all(stage["run"] for stage in plan["stages"].values()))

    def test_force_full_runs_every_stage(self) -> None:
        plan = self.plan([], force_full=True)

        self.assertEqual(plan["mode"], "forced_full")
        self.assertTrue(plan["full_deployment"])
        self.assertTrue(all(stage["run"] for stage in plan["stages"].values()))

    def test_explicit_full_mode_runs_every_stage(self) -> None:
        plan = self.plan([], full=True)

        self.assertEqual(plan["mode"], "full")
        self.assertTrue(plan["full_deployment"])
        self.assertTrue(all(stage["run"] for stage in plan["stages"].values()))

    def test_live_drift_adds_stage_and_agent_work(self) -> None:
        plan = self.plan(
            [],
            drift={
                "stages": {"app": {"drifted": True}},
                "agents": {"waypoint-recorder": "missing"},
            },
        )

        self.assertTrue(plan["stages"]["app"]["run"])
        self.assertTrue(plan["stages"]["wiring"]["run"])
        self.assertTrue(plan["stages"]["deploy_agents"]["run"])
        self.assertEqual(plan["selected_agents"], ["waypoint-recorder"])

    def test_recorded_missing_stage_forces_reconciliation(self) -> None:
        plan = self.plan(
            [],
            recorded_state={
                "initialized": True,
                "stages": {"contracts_kb": {"deployed": False}},
            },
        )

        self.assertTrue(plan["stages"]["contracts_kb"]["run"])
        self.assertTrue(plan["stages"]["acceptance"]["run"])

    def test_git_diff_reads_base_to_head_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            (repo / "tracked.txt").write_text("before\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(repo), "add", "tracked.txt"], check=True)
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(repo),
                    "-c",
                    "user.name=Test",
                    "-c",
                    "user.email=test@example.invalid",
                    "commit",
                    "-qm",
                    "base",
                ],
                check=True,
            )
            base = subprocess.check_output(
                ["git", "-C", str(repo), "rev-parse", "HEAD"], text=True
            ).strip()
            (repo / "tracked.txt").write_text("after\n", encoding="utf-8")
            subprocess.run(
                ["git", "-C", str(repo), "commit", "-qam", "head"],
                check=True,
                env={
                    **dict(__import__("os").environ),
                    "GIT_AUTHOR_NAME": "Test",
                    "GIT_AUTHOR_EMAIL": "test@example.invalid",
                    "GIT_COMMITTER_NAME": "Test",
                    "GIT_COMMITTER_EMAIL": "test@example.invalid",
                },
            )
            head = subprocess.check_output(
                ["git", "-C", str(repo), "rev-parse", "HEAD"], text=True
            ).strip()

            self.assertEqual(
                planner.git_changed_paths(repo, base, head),
                ["tracked.txt"],
            )
            (repo / "tracked.txt").rename(repo / "moved.txt")
            subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
            subprocess.run(
                ["git", "-C", str(repo), "commit", "-qm", "rename"],
                check=True,
                env={
                    **dict(__import__("os").environ),
                    "GIT_AUTHOR_NAME": "Test",
                    "GIT_AUTHOR_EMAIL": "test@example.invalid",
                    "GIT_COMMITTER_NAME": "Test",
                    "GIT_COMMITTER_EMAIL": "test@example.invalid",
                },
            )
            renamed_head = subprocess.check_output(
                ["git", "-C", str(repo), "rev-parse", "HEAD"], text=True
            ).strip()
            self.assertEqual(
                planner.git_changed_paths(repo, head, renamed_head),
                ["moved.txt", "tracked.txt"],
            )


if __name__ == "__main__":
    unittest.main()
