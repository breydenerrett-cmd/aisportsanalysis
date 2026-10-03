"""src/pipeline/read_context.py: the facts about our own stores that the written
game read needs (how old each is, the league run rate, the park factor).

The point of the module is that a store that ends weeks early must be visible
to the read as a date, not inferred from a rest-day count that is really a gap
in our records. Every test here uses tiny stores written to a temp directory;
none touches data/historical/.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from src.pipeline import read_context as rc


def _game(date, away, home, away_score, home_score, pk):
    return {"game_pk": str(pk), "date": date, "away_team": away, "home_team": home,
            "away_score": str(away_score), "home_score": str(home_score)}


def _store(rows):
    return {r["game_pk"]: r for r in rows}


class ResultsSummary(unittest.TestCase):
    def test_it_finds_the_newest_scored_game_before_the_date(self):
        store = _store([_game("2026-09-20", "A", "B", 3, 2, 1),
                        _game("2026-09-23", "A", "B", 4, 4, 2),
                        _game("2026-10-03", "A", "B", 9, 9, 3)])   # the game itself
        out = rc.results_summary(store, "2026-10-03")
        self.assertEqual(out["through"], "2026-09-23")
        self.assertEqual(out["games"], 2)

    def test_the_league_run_rate_is_runs_per_team_per_game(self):
        store = _store([_game("2026-09-20", "A", "B", 3, 2, 1),
                        _game("2026-09-21", "A", "B", 5, 4, 2)])
        # 14 runs over 2 games and 4 team-games
        self.assertEqual(rc.results_summary(store, "2026-10-03")["league_runs_per_game"], 3.5)

    def test_only_the_same_season_counts_toward_the_rate(self):
        store = _store([_game("2025-09-20", "A", "B", 10, 10, 1),
                        _game("2026-04-02", "A", "B", 2, 2, 2)])
        out = rc.results_summary(store, "2026-10-03")
        self.assertEqual(out["games"], 1)
        self.assertEqual(out["league_runs_per_game"], 2.0)

    def test_unscored_rows_are_skipped_not_counted_as_zero(self):
        rows = [_game("2026-09-20", "A", "B", 3, 2, 1)]
        rows.append({"game_pk": "2", "date": "2026-09-22", "away_team": "A",
                     "home_team": "B", "away_score": None, "home_score": ""})
        out = rc.results_summary(_store(rows), "2026-10-03")
        self.assertEqual(out["through"], "2026-09-20")
        self.assertEqual(out["games"], 1)

    def test_an_empty_store_has_no_date_and_no_rate(self):
        out = rc.results_summary({}, "2026-10-03")
        self.assertIsNone(out["through"])
        self.assertIsNone(out["league_runs_per_game"])
        self.assertEqual(out["games"], 0)

    def test_scores_that_round_trip_through_csv_as_strings_still_count(self):
        # The store keeps scores as strings; an isinstance(int) guard would
        # count none of them (the fault that voided every pick on 2026-09-10).
        out = rc.results_summary(_store([_game("2026-09-20", "A", "B", 3, 2, 1)]),
                                 "2026-10-03")
        self.assertEqual(out["games"], 1)


class LogDates(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name, "log.jsonl")

    def write(self, dates):
        self.path.write_text(
            "\n".join(json.dumps({"date": d, "person_id": i}) for i, d in enumerate(dates)) + "\n",
            encoding="utf-8")

    def test_it_collects_distinct_dates_sorted(self):
        self.write(["2026-09-06", "2026-09-01", "2026-09-06"])
        self.assertEqual(rc._log_dates(self.path), ("2026-09-01", "2026-09-06"))

    def test_a_missing_file_is_empty_not_an_error(self):
        self.assertEqual(rc._log_dates(Path(self._tmp.name, "nope.jsonl")), ())

    def test_a_changed_file_is_rescanned_and_an_unchanged_one_is_not(self):
        self.write(["2026-09-01"])
        self.assertEqual(rc._log_dates(self.path), ("2026-09-01",))
        key = str(self.path)
        cached = rc._scan_cache[key]
        self.assertIs(rc._log_dates(self.path), cached[1])          # served from the cache
        self.write(["2026-09-01", "2026-09-09"])
        os.utime(self.path, (1, 2_000_000_000))                      # force a new stat
        self.assertEqual(rc._log_dates(self.path), ("2026-09-01", "2026-09-09"))

    def test_a_line_that_is_not_json_does_not_stop_the_scan(self):
        self.path.write_text('{"date": "2026-09-01"}\nnot json at all\n{"date": "2026-09-05"}\n',
                             encoding="utf-8")
        self.assertEqual(rc._log_dates(self.path), ("2026-09-01", "2026-09-05"))

    def test_newest_before_is_strictly_before(self):
        dates = ("2026-09-01", "2026-09-06", "2026-10-03")
        self.assertEqual(rc.newest_before(dates, "2026-10-03"), "2026-09-06")
        self.assertIsNone(rc.newest_before(dates, "2026-09-01"))
        self.assertIsNone(rc.newest_before((), "2026-10-03"))


class Build(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.pitchers = Path(self._tmp.name, "pitchers.jsonl")
        self.pen = Path(self._tmp.name, "pen.jsonl")
        self.pitchers.write_text('{"date": "2026-09-07"}\n', encoding="utf-8")
        self.pen.write_text('{"date": "2026-09-06"}\n', encoding="utf-8")
        rows = []
        pk = 0
        # 12 home and 12 road games for HOME, home games high-scoring.
        for i in range(12):
            pk += 1
            rows.append(_game(f"2026-08-{i + 1:02d}", "X", "HOME", 6, 6, pk))
            pk += 1
            rows.append(_game(f"2026-08-{i + 13:02d}", "HOME", "Y", 4, 4, pk))
        self.store = _store(rows)

    def build(self):
        return rc.build(self.store, "2026-10-03", "HOME",
                        pitcher_log_path=self.pitchers, bullpen_log_path=self.pen)

    def test_it_reports_the_age_of_every_store(self):
        out = self.build()
        self.assertEqual(out["results"]["through"], "2026-08-24")
        self.assertEqual(out["pitcher_logs"]["through"], "2026-09-07")
        self.assertEqual(out["bullpen_log"]["through"], "2026-09-06")

    def test_the_league_rate_is_measured(self):
        out = self.build()
        self.assertEqual(out["league_runs_per_game"]["value"], 5.0)

    def test_the_park_factor_is_the_regressed_home_road_split(self):
        out = self.build()
        pf = out["park_factor"]
        self.assertEqual(pf["team"], "HOME")
        self.assertEqual(pf["home_games"], 12)
        self.assertEqual(pf["raw_factor"], 1.5)
        # regressed hard toward neutral by the 150 game prior, so well under raw
        self.assertGreater(pf["factor"], 1.0)
        self.assertLess(pf["factor"], 1.1)
        self.assertTrue(pf["thin"])

    def test_a_club_not_in_the_results_has_no_park_factor_at_all(self):
        out = rc.build(self.store, "2026-10-03", "NOBODY",
                       pitcher_log_path=self.pitchers, bullpen_log_path=self.pen)
        self.assertIsNone(out["park_factor"])

    def test_missing_logs_leave_none_never_a_substituted_date(self):
        out = rc.build(self.store, "2026-10-03", "HOME",
                       pitcher_log_path=Path(self._tmp.name, "gone1"),
                       bullpen_log_path=Path(self._tmp.name, "gone2"))
        self.assertIsNone(out["pitcher_logs"]["through"])
        self.assertIsNone(out["bullpen_log"]["through"])

    def test_an_empty_results_store_still_builds(self):
        out = rc.build({}, "2026-10-03", "HOME",
                       pitcher_log_path=self.pitchers, bullpen_log_path=self.pen)
        self.assertIsNone(out["results"]["through"])
        self.assertIsNone(out["league_runs_per_game"]["value"])
        self.assertIsNone(out["park_factor"])

    def test_the_block_is_json_serialisable(self):
        json.dumps(self.build())


if __name__ == "__main__":
    unittest.main()
