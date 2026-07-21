"""Hermetic tests for deployment recovery and bounded drift verification."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).parents[1] / "scripts" / "verify_recovery_drift.py"
SPEC = importlib.util.spec_from_file_location("verify_recovery_drift", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
verify_recovery_drift = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(verify_recovery_drift)

FIXTURES = Path(__file__).parent / "fixtures" / "recovery"


def fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class VerifyRecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.baseline = fixture("baseline.json")
        self.interrupted = fixture("interrupted.json")
        self.rerun = fixture("rerun.json")
        self.scenarios = fixture("scenarios.json")

    def test_interrupted_stages_recover_and_inventory_converges(self) -> None:
        report = verify_recovery_drift.verify_recovery(
            self.baseline,
            self.interrupted,
            self.rerun,
            scenarios=self.scenarios,
        )

        self.assertTrue(report["passed"])
        self.assertEqual(
            report["recovered_stages"],
            ["acceptance", "agents", "contracts_kb", "seed"],
        )
        self.assertIn(
            "managed_inventory_convergence",
            [check["name"] for check in report["checks"]],
        )
        self.assertEqual(
            report["interrupted_inventory_changes"],
            [
                "hosted_agents",
                "knowledge_bases",
                "role_assignments",
                "seed_sets",
            ],
        )

    def test_rerun_fails_when_managed_inventory_does_not_converge(self) -> None:
        rerun = copy.deepcopy(self.rerun)
        rerun["inventory"]["models"][0]["state"]["version"] = "drifted"

        report = verify_recovery_drift.verify_recovery(
            self.baseline,
            self.interrupted,
            rerun,
            scenarios=self.scenarios,
        )

        self.assertFalse(report["passed"])
        self.assertIn(
            "Rerun managed inventory did not converge to the baseline.",
            report["issues"],
        )

    def test_duplicate_ids_and_logical_resources_are_detected(self) -> None:
        for collection, label in verify_recovery_drift.COLLECTION_LABELS.items():
            with self.subTest(collection=collection):
                snapshot = copy.deepcopy(self.rerun)
                duplicate = copy.deepcopy(snapshot["inventory"][collection][0])
                snapshot["inventory"][collection].append(duplicate)

                issues = verify_recovery_drift.duplicate_issues(snapshot)

                self.assertTrue(
                    any(f"Duplicate {label} ids" in issue for issue in issues),
                    issues,
                )
                self.assertTrue(
                    any(f"Duplicate {label} names" in issue for issue in issues),
                    issues,
                )

    def test_duplicate_seed_records_are_detected(self) -> None:
        snapshot = copy.deepcopy(self.rerun)
        seed_state = snapshot["inventory"]["seed_sets"][0]["state"]
        seed_state["record_ids"].append(seed_state["record_ids"][0])

        issues = verify_recovery_drift.duplicate_issues(snapshot)

        self.assertIn(
            "Duplicate seed record ids: invoice:INV-001.",
            issues,
        )

    def test_rerun_duplicates_produce_a_failed_recovery_report(self) -> None:
        rerun = copy.deepcopy(self.rerun)
        rerun["inventory"]["container_apps"].append(
            copy.deepcopy(rerun["inventory"]["container_apps"][0])
        )

        report = verify_recovery_drift.verify_recovery(
            self.baseline,
            self.interrupted,
            rerun,
            scenarios=self.scenarios,
        )

        self.assertFalse(report["passed"])
        self.assertTrue(
            any(
                issue.startswith("rerun: Duplicate container apps ids")
                for issue in report["issues"]
            ),
            report["issues"],
        )

    def test_interrupted_attempt_must_also_be_duplicate_free(self) -> None:
        interrupted = copy.deepcopy(self.interrupted)
        interrupted["inventory"]["models"].append(
            copy.deepcopy(interrupted["inventory"]["models"][0])
        )

        report = verify_recovery_drift.verify_recovery(
            self.baseline,
            interrupted,
            self.rerun,
            scenarios=self.scenarios,
        )

        self.assertFalse(report["passed"])
        self.assertTrue(
            any(
                issue.startswith("interrupted: Duplicate models ids")
                for issue in report["issues"]
            ),
            report["issues"],
        )

    def test_drift_plan_is_bounded_to_five_exact_resources(self) -> None:
        plan = verify_recovery_drift.build_drift_plan(
            self.baseline,
            fixture("drifted.json"),
            self.scenarios,
        )

        self.assertTrue(plan["safe_to_apply"])
        self.assertEqual(len(plan["operations"]), 5)
        self.assertEqual(
            {operation["action"] for operation in plan["operations"]},
            {"replace_value", "restore_resource"},
        )
        self.assertEqual(
            {operation["target_id"] for operation in plan["operations"]},
            {
                scenario["target"]["resource_id"]
                for scenario in self.scenarios["scenarios"]
            },
        )
        self.assertEqual(
            plan["required_confirmation"],
            "APPLY "
            + self.baseline["environment"]["scope_id"]
            + " "
            + plan["plan_digest"],
        )

    def test_apply_refuses_without_exact_confirmation_then_converges(self) -> None:
        drifted = fixture("drifted.json")
        plan = verify_recovery_drift.build_drift_plan(
            self.baseline,
            drifted,
            self.scenarios,
        )

        with self.assertRaisesRegex(
            verify_recovery_drift.VerificationError,
            "confirmation must exactly equal",
        ):
            verify_recovery_drift.apply_drift_plan(
                self.baseline,
                drifted,
                self.scenarios,
                plan,
                confirmation=plan["plan_digest"],
            )

        applied = verify_recovery_drift.apply_drift_plan(
            self.baseline,
            drifted,
            self.scenarios,
            plan,
            confirmation=plan["required_confirmation"],
        )

        self.assertEqual(
            verify_recovery_drift._managed_inventory(applied),
            verify_recovery_drift._managed_inventory(self.baseline),
        )
        self.assertEqual(
            verify_recovery_drift.build_drift_plan(
                self.baseline,
                applied,
                self.scenarios,
            )["operations"],
            [],
        )

    def test_apply_refuses_a_plan_changed_after_preview(self) -> None:
        drifted = fixture("drifted.json")
        plan = verify_recovery_drift.build_drift_plan(
            self.baseline,
            drifted,
            self.scenarios,
        )
        plan["operations"][1]["managed_path"] = [
            "name",
        ]
        plan["evaluated_scenarios"][1]["managed_path"] = "name"
        plan_body = {
            "schema_version": plan["schema_version"],
            "environment_scope_id": plan["environment_scope_id"],
            "evaluated_scenarios": plan["evaluated_scenarios"],
            "operations": plan["operations"],
        }
        forged_digest = hashlib.sha256(
            json.dumps(
                plan_body,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
        plan["plan_digest"] = forged_digest
        plan["required_confirmation"] = (
            f"APPLY {plan['environment_scope_id']} {forged_digest}"
        )

        with self.assertRaisesRegex(
            verify_recovery_drift.VerificationError,
            "plan contents do not match the bounded preview",
        ):
            verify_recovery_drift.apply_drift_plan(
                self.baseline,
                drifted,
                self.scenarios,
                plan,
                confirmation=plan["required_confirmation"],
            )

    def test_planner_never_resolves_a_target_by_loose_name(self) -> None:
        scenarios = copy.deepcopy(self.scenarios)
        scenarios["scenarios"][1]["target"]["resource_id"] = (
            "azure://containerApps/not-the-api-id"
        )

        with self.assertRaisesRegex(
            verify_recovery_drift.VerificationError,
            "is not declared in the baseline",
        ):
            verify_recovery_drift.build_drift_plan(
                self.baseline,
                fixture("drifted.json"),
                scenarios,
            )

    def test_sanitizer_redacts_secret_keys_and_secret_shaped_values(self) -> None:
        raw = copy.deepcopy(self.baseline)
        raw["capture"] = {
            "api_key": "do-not-persist",
            "headers": {"Authorization": "Bearer abc.def.ghi"},
            "note": "AccountKey=also-do-not-persist",
            "sas_url": "https://storage.example/blob?sv=1&sig=TOPSECRET",
        }

        sanitized = verify_recovery_drift.sanitize_payload(raw)

        self.assertEqual(sanitized["capture"]["api_key"], "[REDACTED]")
        self.assertEqual(
            sanitized["capture"]["headers"]["Authorization"],
            "[REDACTED]",
        )
        self.assertEqual(sanitized["capture"]["note"], "[REDACTED]")
        self.assertEqual(sanitized["capture"]["sas_url"], "[REDACTED]")
        self.assertEqual(verify_recovery_drift.sensitive_paths(sanitized), [])

    def test_every_controlled_drift_type_is_required(self) -> None:
        scenarios = copy.deepcopy(self.scenarios)
        scenarios["scenarios"] = scenarios["scenarios"][:-1]

        with self.assertRaisesRegex(
            verify_recovery_drift.VerificationError,
            "missing: seed_count_drift",
        ):
            verify_recovery_drift.build_drift_plan(
                self.baseline,
                fixture("drifted.json"),
                scenarios,
            )

    def test_skipped_rerun_stage_does_not_count_as_recovered(self) -> None:
        rerun = copy.deepcopy(self.rerun)
        rerun["stages"]["agents"] = "skipped"

        report = verify_recovery_drift.verify_recovery(
            self.baseline,
            self.interrupted,
            rerun,
            scenarios=self.scenarios,
        )

        self.assertFalse(report["passed"])
        self.assertIn(
            "Rerun stage 'agents' did not recover: status='skipped'.",
            report["issues"],
        )

    def test_unsanitized_snapshot_is_rejected(self) -> None:
        snapshot = copy.deepcopy(self.baseline)
        snapshot["metadata"] = {"client_secret": "not-sanitized"}

        with self.assertRaisesRegex(
            verify_recovery_drift.VerificationError,
            "is not sanitized",
        ):
            verify_recovery_drift.validate_snapshot(snapshot, label="snapshot")


if __name__ == "__main__":
    unittest.main()
