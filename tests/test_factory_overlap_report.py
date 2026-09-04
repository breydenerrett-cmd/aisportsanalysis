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


class TestOverlapFromCombinedMasks(unittest.TestCase):
    """`_overlap_from_combined` against small, hand-built combined ints --
    the popcount path documented in the module docstring as mathematically
    identical to `overlap.jaccard`'s string-set method, exercised here
    without needing a real sweep artifact or masks file."""

    def test_identical_strategies_form_one_family_and_zero_dedup(self):
        # 2 games, both strategies bet home on game 0 and away on game 1:
        # away bits = 0b10 (game 1), home bits = 0b01 (game 0).
        n_games = 2
        combined = 0b01 | (0b10 << n_games)
        strategies = {"a": combined, "b": combined, "c": combined}
        dedup, families, eff = report_mod._overlap_from_combined(strategies)
        self.assertEqual(dedup.unique_wagers, 2)
        self.assertEqual(dedup.total_decisions, 6)
        self.assertAlmostEqual(dedup.dedup_ratio, 2 / 6)
        self.assertEqual(len(families), 1)
        self.assertEqual(sorted(families[0]), ["a", "b", "c"])
        self.assertEqual(eff.n_families, 1)

    def test_disjoint_strategies_never_join_a_family(self):
        n_games = 4
        a = 0b0001 | (0b0000 << n_games)   # away game 0 only
        b = 0b0000 | (0b1000 << n_games)   # home game 3 only
        dedup, families, eff = report_mod._overlap_from_combined({"a": a, "b": b})
        self.assertEqual(dedup.unique_wagers, 2)
        self.assertEqual(dedup.total_decisions, 2)
        self.assertEqual(dedup.dedup_ratio, 1.0)
        self.assertEqual(len(families), 2)
        self.assertEqual(eff.n_families, 2)

    def test_matches_overlap_module_on_the_same_scenario(self):
        """The popcount path and `overlap.py`'s own string-set path agree --
        the performance rewrite changed representation, not the answer."""
        from src.evolab import overlap as overlap_mod
        n_games = 6
        raw = {
            "s1": (0b000011, 0b000000),
            "s2": (0b000010, 0b000001),
            "s3": (0b100000, 0b000000),
        }
        combined = {sid: away | (home << n_games)
                   for sid, (away, home) in raw.items()}
        dedup_fast, families_fast, eff_fast = report_mod._overlap_from_combined(combined)

        def bits(mask, offset):
            return {f"{offset}:{i}" for i in range(n_games) if mask & (1 << i)}

        selections = {sid: frozenset(bits(away, "away") | bits(home, "home"))
                     for sid, (away, home) in raw.items()}
        dedup_slow = overlap_mod.dedup_stats(selections)
        families_slow = overlap_mod.cluster_families(selections)
        eff_slow = overlap_mod.effective_n(families_slow)

        self.assertEqual(dedup_fast.unique_wagers, dedup_slow.unique_wagers)
        self.assertEqual(dedup_fast.total_decisions, dedup_slow.total_decisions)
        self.assertEqual([sorted(f) for f in families_fast],
                         [sorted(f) for f in families_slow])
        self.assertEqual(eff_fast.n_families, eff_slow.n_families)
        self.assertAlmostEqual(eff_fast.credit, eff_slow.credit)


class TestMasksPathsFor(unittest.TestCase):

    def test_returns_none_when_files_absent(self):
        self.assertIsNone(report_mod._masks_paths_for("0" * 64))

    def test_finds_the_real_backfilled_masks_when_present(self):
        # This is the actual artifact this slice backfilled; skip honestly
        # if a checkout/CI environment doesn't carry the (untracked-size)
        # masks files rather than failing a test on their absence.
        spec_hash = "0014914df78666b9a024677b8fb02a27d8ae70432c5898944c8120c3d3b56823"
        found = report_mod._masks_paths_for(spec_hash)
        if found is None:
            self.skipTest("backfilled masks-*.bin/.index.json not present "
                          "in this checkout")
        index_path, bin_path = found
        self.assertTrue(index_path.endswith(".index.json"))
        self.assertTrue(bin_path.endswith(".bin"))


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
