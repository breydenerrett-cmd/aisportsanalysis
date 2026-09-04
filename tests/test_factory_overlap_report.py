"""scripts/factory_overlap_report.py: must run to completion (exit 0) whether
or not sweep output exists, and must never fabricate an overlap number it
cannot support. See docs/FACTORY_SCALE_DESIGN.md section 7.
"""

import importlib.util
import json
import os
import sys
import tempfile
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT_PATH = os.path.join(REPO_ROOT, "scripts", "factory_overlap_report.py")

_spec = importlib.util.spec_from_file_location("factory_overlap_report", SCRIPT_PATH)
report_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(report_mod)


class TestRenderNoArtifacts(unittest.TestCase):

    def test_renders_absence_honestly(self):
        body = report_mod._render([], "2026-01-01 00:00 UTC")
        self.assertIn("No sweep output found", body)

    def test_never_claims_a_numeric_overlap_with_no_input(self):
        body = report_mod._render([], "2026-01-01 00:00 UTC")
        self.assertNotIn("dedup_ratio", body)


class TestRenderWithArtifacts(unittest.TestCase):

    def test_renders_counts_and_states_overlap_gap(self):
        fake_report = {
            "_source_path": "data/research/evolab/sweep-fake.json",
            "real_world_id": "REAL",
            "n_strategies_real": 11088,
            "n_games_real": 4800,
            "real_champion": "abc123",
        }
        body = report_mod._render([fake_report], "2026-01-01 00:00 UTC")
        self.assertIn("11088", body)
        self.assertIn("4800", body)
        self.assertIn("not yet computable", body.lower())
        # Never asserts a dedup number it did not compute.
        self.assertNotIn("dedup_ratio", body)


class TestLoadSweepReports(unittest.TestCase):

    def test_loads_and_sorts_by_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            for name, world in [("sweep-b.json", "B"), ("sweep-a.json", "A")]:
                with open(os.path.join(tmp, name), "w") as fh:
                    json.dump({"real_world_id": world}, fh)
            pattern = os.path.join(tmp, "sweep-*.json")
            reports = report_mod._load_sweep_reports(pattern)
        self.assertEqual([r["real_world_id"] for r in reports], ["A", "B"])

    def test_empty_directory_returns_empty_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            pattern = os.path.join(tmp, "sweep-*.json")
            reports = report_mod._load_sweep_reports(pattern)
        self.assertEqual(reports, [])


class TestMainExitsCleanly(unittest.TestCase):

    def test_main_returns_zero_and_writes_doc(self):
        # Exercise the real main() against whatever exists in the repo today
        # (present or absent) -- either way it must exit 0 and write the doc.
        rc = report_mod.main([])
        self.assertEqual(rc, 0)
        self.assertTrue(os.path.exists(report_mod.OUT_PATH))
        with open(report_mod.OUT_PATH) as fh:
            content = fh.read()
        self.assertIn("Factory overlap report", content)


if __name__ == "__main__":
    unittest.main()
