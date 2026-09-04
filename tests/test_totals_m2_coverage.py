"""Synthetic-fixture unit test for scripts/totals_m2_coverage.py.

Builds a tiny in-memory odds archive + results CSV + matrix jsonl (no real
gitignored store touched) and checks the join/drop/tercile arithmetic by
hand.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.test_totals_rows import _Fixture, _add_default_game  # noqa: E402

_SPEC = importlib.util.spec_from_file_location(
    "totals_m2_coverage",
    Path(__file__).resolve().parents[1] / "scripts" / "totals_m2_coverage.py")
m2 = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(m2)


def _write_matrix(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


class TestCombinedFeature(unittest.TestCase):
    def test_both_sides_required(self):
        self.assertEqual(m2.combined_feature(0.4, 0.6), 0.5)
        self.assertIsNone(m2.combined_feature(None, 0.6))
        self.assertIsNone(m2.combined_feature(0.4, None))
        self.assertIsNone(m2.combined_feature(None, None))


class TestTercileEdges(unittest.TestCase):
    def test_fit_and_assign(self):
        vals = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6]
        edges = m2.fit_tercile_edges(vals)
        self.assertEqual(m2.assign_tercile(0.05, edges), 0)
        self.assertEqual(m2.assign_tercile(0.6, edges), 2)


class TestMDE(unittest.TestCase):
    def test_known_value(self):
        # matches PREREG_F5_FAMILIES / M1's documented n=1316 -> 2.71pp
        self.assertAlmostEqual(m2.mde(1316), 0.0271, places=3)
        self.assertIsNone(m2.mde(0))


class TestComputeCoverageSynthetic(unittest.TestCase):
    def test_end_to_end_join_and_drop_counts(self):
        with TemporaryDirectory() as td:
            fx = _Fixture(td)
            # 2023: 3 gradeable games -- one full both-sides, one one-sided
            # (dropped), one no matrix row at all.
            _add_default_game(fx, season="2023", event_id="e1", game_pk="1001",
                               date="2023-04-01", total_runs=8, home_won=True)
            _add_default_game(fx, season="2023", event_id="e2", game_pk="1002",
                               date="2023-04-02", total_runs=7, home_won=False)
            _add_default_game(fx, season="2023", event_id="e3", game_pk="1003",
                               date="2023-04-03", total_runs=9, home_won=True)
            # 2024: 2 gradeable games, both both-sides present.
            _add_default_game(fx, season="2024", event_id="e4", game_pk="2001",
                               date="2024-04-01", total_runs=6, home_won=True)
            _add_default_game(fx, season="2024", event_id="e5", game_pk="2002",
                               date="2024-04-02", total_runs=5, home_won=False)
            fx.write()

            matrix_2023 = fx.root / "matchup_matrix_2023.jsonl"
            matrix_2024 = fx.root / "matchup_matrix_2024.jsonl"
            _write_matrix(matrix_2023, [
                {"game_pk": "1001", "away_starter_groundball_share": 0.3,
                 "home_starter_groundball_share": 0.5},
                {"game_pk": "1002", "away_starter_groundball_share": None,
                 "home_starter_groundball_share": 0.5},
                # 1003: no matrix row at all (join failure).
            ])
            _write_matrix(matrix_2024, [
                {"game_pk": "2001", "away_starter_groundball_share": 0.4,
                 "home_starter_groundball_share": 0.6},
                {"game_pk": "2002", "away_starter_groundball_share": 0.2,
                 "home_starter_groundball_share": 0.2},
            ])

            result = m2.compute_coverage(
                archive_root=fx.archive_root, results_path=fx.results_csv,
                matrix_paths={"2023": matrix_2023, "2024": matrix_2024})

            rec23 = result["per_season"]["2023"]
            self.assertEqual(rec23["joint_denominator_n"], 3)
            self.assertEqual(rec23["rows_with_both_starters_feature_present"], 1)
            self.assertEqual(rec23["dropped_both_sides_or_none_rule"], 1)
            self.assertEqual(rec23["join_failures"]["no_matrix_row_for_game_pk"], 1)
            self.assertEqual(rec23["join_failures"]["feature_missing_away_only"], 1)

            rec24 = result["per_season"]["2024"]
            self.assertEqual(rec24["joint_denominator_n"], 2)
            self.assertEqual(rec24["rows_with_both_starters_feature_present"], 2)
            self.assertEqual(rec24["dropped_both_sides_or_none_rule"], 0)

            # edges fit on 2023's single both-sides value (0.4) -> both
            # edges equal 0.4, so that same value lands in the mid tercile.
            self.assertEqual(result["tercile_edges_fit_on_2023"],
                              {"low_edge": 0.4, "high_edge": 0.4})

            report = m2.render_report(result)
            self.assertIn("Joint denominator n (price-gradeable universe): 3", report)
            self.assertIn("Joint denominator n (price-gradeable universe): 2", report)


if __name__ == "__main__":
    unittest.main()
