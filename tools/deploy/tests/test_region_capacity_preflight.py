"""Tests for the region+capacity preflight
(tools/deploy/scripts/region_capacity_preflight.py)."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).parents[1] / "scripts" / "region_capacity_preflight.py"
SPEC = importlib.util.spec_from_file_location("region_capacity_preflight", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
rcp = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = rcp
SPEC.loader.exec_module(rcp)


def proc(returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


def _models(names):
    return json.dumps([{"model": {"name": n}} for n in names])


def _usage(pairs):
    # pairs: list of (metric, limit, current)
    return json.dumps(
        [{"name": {"value": m}, "limit": lim, "currentValue": cur} for m, lim, cur in pairs]
    )


class CommandConstructionTests(unittest.TestCase):
    def test_all_build_helpers_return_lists(self):
        self.assertIsInstance(rcp.build_model_list_args("eastus"), list)
        self.assertIsInstance(rcp.build_usage_list_args("eastus"), list)
        self.assertIsInstance(rcp.build_postgres_skus_args("eastus"), list)
        put = rcp.build_search_probe_put_args("sub", "rg", "svc", "eastus", "basic")
        self.assertIsInstance(put, list)
        # Region and body are discrete argv elements, never interpolated into a shell string.
        self.assertIn("put", put)
        self.assertTrue(any('"location": "eastus"' in a for a in put))
        self.assertIsInstance(rcp.build_search_probe_delete_args("sub", "rg", "svc"), list)


class AllowlistTests(unittest.TestCase):
    def test_allowed_region_passes(self):
        status, _ = rcp.evaluate_foundry_allowlist("swedencentral")
        self.assertEqual(status, rcp.STATUS_PASS)

    def test_disallowed_region_fails(self):
        status, _ = rcp.evaluate_foundry_allowlist("northeurope")
        self.assertEqual(status, rcp.STATUS_FAIL)


class ModelAvailabilityTests(unittest.TestCase):
    def test_all_present(self):
        req = rcp.Requirements().models
        status, _ = rcp.evaluate_model_availability(
            _models(["gpt-5.5", "gpt-5-mini", "text-embedding-3-large", "gpt-4o"]), req
        )
        self.assertEqual(status, rcp.STATUS_PASS)

    def test_missing_model_fails(self):
        req = rcp.Requirements().models
        status, detail = rcp.evaluate_model_availability(_models(["gpt-4o"]), req)
        self.assertEqual(status, rcp.STATUS_FAIL)
        self.assertIn("gpt-5.5", detail)


class ModelQuotaTests(unittest.TestCase):
    def test_sufficient_quota_passes_and_reports_headroom(self):
        req = rcp.Requirements().models
        usage = _usage(
            [
                ("OpenAI.GlobalStandard.gpt-5.5", 30000, 25000),  # 5000 free / 200
                ("OpenAI.GlobalStandard.gpt-5-mini", 30000, 25000),  # 5000 free / 200
                ("OpenAI.Standard.text-embedding-3-large", 1000, 500),  # 500 free / 50
            ]
        )
        status, _, ratio = rcp.evaluate_model_quota(usage, req)
        self.assertEqual(status, rcp.STATUS_PASS)
        self.assertGreater(ratio, 1.0)

    def test_insufficient_gpt_quota_fails(self):
        req = rcp.Requirements().models
        usage = _usage(
            [
                ("OpenAI.GlobalStandard.gpt-5.5", 30000, 29900),  # 100 free < 200
                ("OpenAI.GlobalStandard.gpt-5-mini", 30000, 25000),
                ("OpenAI.Standard.text-embedding-3-large", 1000, 0),
            ]
        )
        status, detail, ratio = rcp.evaluate_model_quota(usage, req)
        self.assertEqual(status, rcp.STATUS_FAIL)
        self.assertEqual(ratio, 0.0)

    def test_missing_metric_fails(self):
        req = rcp.Requirements().models
        status, _, _ = rcp.evaluate_model_quota(_usage([]), req)
        self.assertEqual(status, rcp.STATUS_FAIL)


class SearchProbeTests(unittest.TestCase):
    def test_insufficient_resources_fails(self):
        status, _ = rcp.evaluate_search_probe(
            1, "", "ERROR: (InsufficientResourcesAvailable) region out of resources"
        )
        self.assertEqual(status, rcp.STATUS_FAIL)

    def test_success_passes(self):
        status, _ = rcp.evaluate_search_probe(
            0, json.dumps({"properties": {"provisioningState": "provisioning"}}), ""
        )
        self.assertEqual(status, rcp.STATUS_PASS)

    def test_other_error_is_warn(self):
        status, _ = rcp.evaluate_search_probe(1, "", "some transient 429")
        self.assertEqual(status, rcp.STATUS_WARN)


class SelectRegionTests(unittest.TestCase):
    """End-to-end selection with a fake runner (no az binary)."""

    def _make_runner(self, *, no_search_regions):
        def runner(args):
            joined = " ".join(args)
            region = args[args.index("-l") + 1] if "-l" in args else None
            if "model" in args and "list" in args:
                return proc(stdout=_models(["gpt-5.5", "gpt-5-mini", "text-embedding-3-large"]))
            if "usage" in args and "list" in args:
                return proc(
                    stdout=_usage(
                        [
                            ("OpenAI.GlobalStandard.gpt-5.5", 30000, 25000),
                            ("OpenAI.GlobalStandard.gpt-5-mini", 30000, 25000),
                            ("OpenAI.Standard.text-embedding-3-large", 1000, 0),
                        ]
                    )
                )
            if "rest" in args and "put" in args:
                # region is embedded in the URL/body
                bad = any(r in joined for r in no_search_regions)
                if bad:
                    return proc(1, "", "(InsufficientResourcesAvailable) no capacity")
                return proc(0, json.dumps({"properties": {"provisioningState": "provisioning"}}))
            if "rest" in args and "delete" in args:
                return proc(0)
            if "postgres" in args:
                return proc(stdout=json.dumps([{"name": "Standard_D2s_v3"}]))
            if "group" in args:
                return proc(0)
            return proc(0)

        return runner

    def test_prefers_requested_region_when_qualified(self):
        runner = self._make_runner(no_search_regions=[])
        report = rcp.select_region(
            "sub", prefer="swedencentral", runner=runner, probe_rg="rg-probe"
        )
        self.assertEqual(report["selected"], "swedencentral")

    def test_skips_region_without_search_capacity(self):
        # eastus2 has no Search capacity; preflight must pick another region.
        runner = self._make_runner(no_search_regions=["searchServices/wpcapz"])
        # Force ALL regions to fail the search probe -> no selection.
        report = rcp.select_region("sub", runner=runner, probe_rg="rg-probe")
        self.assertIsNone(report["selected"])

    def test_eastus2_excluded_but_others_selected(self):
        # Only regions whose name appears in the PUT url containing 'eastus2' fail.
        def runner(args):
            joined = " ".join(args)
            if "model" in args and "list" in args:
                return proc(stdout=_models(["gpt-5.5", "gpt-5-mini", "text-embedding-3-large"]))
            if "usage" in args and "list" in args:
                return proc(
                    stdout=_usage(
                        [
                            ("OpenAI.GlobalStandard.gpt-5.5", 30000, 25000),
                            ("OpenAI.GlobalStandard.gpt-5-mini", 30000, 25000),
                            ("OpenAI.Standard.text-embedding-3-large", 1000, 0),
                        ]
                    )
                )
            if "rest" in args and "put" in args:
                if '"location": "eastus2"' in joined:
                    return proc(1, "", "(InsufficientResourcesAvailable) no capacity")
                return proc(0, json.dumps({"properties": {"provisioningState": "provisioning"}}))
            return proc(0)

        report = rcp.select_region(
            "sub", prefer="eastus2", runner=runner, probe_rg="rg-probe"
        )
        self.assertIsNotNone(report["selected"])
        self.assertNotEqual(report["selected"], "eastus2")

    def test_dry_run_skips_probe(self):
        runner = self._make_runner(no_search_regions=[])
        report = rcp.select_region(
            "sub", prefer="swedencentral", runner=runner, probe_search=False, probe_rg="rg-probe"
        )
        self.assertEqual(report["selected"], "swedencentral")
        self.assertFalse(report["probed"])


if __name__ == "__main__":
    unittest.main()
