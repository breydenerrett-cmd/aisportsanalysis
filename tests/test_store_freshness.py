"""`store_freshness.report`: how current is every request-time store, from outside.

THE CLAIMS THAT MATTER
----------------------
  - "through" is COVERAGE, not the newest game: an off-day refresh counts, so
    the winter is not a permanent outage
  - the ages are the ones the owner measured on 2026-10-03 (results 09-23,
    pitchers 09-07, bullpen 09-06, standings 09-08), reproduced from a
    synthetic copy shaped like the repo's
  - a store past its tolerance is `stale`; one inside it is not; one that is
    absent or unreadable is stale with its reason -- never green by default
  - after the regular season ends the last standings snapshot is the last that
    can exist, not a stale one
  - the Eastern date rule is the same one the postseason page uses
  - a CHANGED file is re-read at once (a cached "fresh" would be the worst lie
    this report could tell) and an unchanged one is not re-read
"""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from src.pipeline import store_freshness as sf
from src.report import postseason_page

NOW = datetime(2026, 10, 3, 16, 0, tzinfo=timezone.utc)


def _write_jsonl(path: Path, rows):
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


def _results(hist: Path, rows, manifest_dates):
    import csv
    with (hist / "mlb_results.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["game_pk", "date", "game_type"])
        writer.writeheader()
        for pk, (date, gtype) in enumerate(rows, 1):
            writer.writerow({"game_pk": pk, "date": date, "game_type": gtype})
    (hist / "mlb_results.manifest.json").write_text(json.dumps({"dates": {
        d: {"total": 0, "final": 0, "pending": pending, "cancelled": 0}
        for d, pending in manifest_dates.items()}}), encoding="utf-8")


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.hist = self.root / "historical"
        self.hist.mkdir()
        sf.reset_cache_for_tests()

    def report(self, now=NOW):
        return sf.report(self.root, now)


class ThroughIsCoverage(Base):

    def test_manifest_dates_count_even_with_no_game_that_day(self):
        _results(self.hist, [("2026-09-27", "R")], {"2026-09-27": 0, "2026-09-28": 0, "2026-10-02": 0})
        entry = self.report()["stores"]["mlb_results"]
        self.assertEqual(entry["through"], "2026-10-02")
        self.assertEqual(entry["newest_row"], "2026-09-27")
        self.assertFalse(entry["stale"])

    def test_a_date_fetched_with_a_game_still_pending_is_not_covered_yet(self):
        _results(self.hist, [("2026-10-01", "F")], {"2026-10-01": 0, "2026-10-02": 1})
        self.assertEqual(self.report()["stores"]["mlb_results"]["through"], "2026-10-01")

    def test_pitcher_through_counts_a_refresh_that_found_nothing_new(self):
        _write_jsonl(self.hist / "pitcher_logs.jsonl", [
            {"person_id": 1, "date": "2026-09-27", "season": "2026"},
            {"person_id": 1, "date": None, "season": "2026", "empty": False,
             "checked_utc": "2026-10-03T09:00:00+00:00"}])
        entry = self.report()["stores"]["pitcher_logs"]
        self.assertEqual(entry["through"], "2026-10-03")
        self.assertEqual(entry["newest_row"], "2026-09-27")
        self.assertFalse(entry["stale"])

    def test_bullpen_counts_the_explicit_empty_day_markers(self):
        _write_jsonl(self.hist / "bullpen_log.jsonl", [
            {"date": "2026-09-28", "team": "NYY", "person_id": 1},
            {"date": "2026-10-02", "empty": True}])
        self.assertEqual(self.report()["stores"]["bullpen_log"]["through"], "2026-10-02")

    def test_a_torn_last_line_costs_one_row_not_the_report(self):
        (self.hist / "bullpen_log.jsonl").write_text(
            json.dumps({"date": "2026-10-02", "empty": True}) + '\n{"date": "2026-1', encoding="utf-8")
        entry = self.report()["stores"]["bullpen_log"]
        self.assertEqual(entry["through"], "2026-10-02")
        self.assertEqual(entry["rows"], 1)


class TheAgesTheOwnerMeasured(Base):

    def test_a_repo_shaped_copy_reads_as_stale_by_the_measured_amounts(self):
        _results(self.hist, [("2026-09-23", "R")], {"2026-09-23": 0})
        _write_jsonl(self.hist / "pitcher_logs.jsonl", [
            {"person_id": 1, "date": "2026-09-07", "season": "2026"}])
        _write_jsonl(self.hist / "bullpen_log.jsonl", [{"date": "2026-09-06", "empty": True}])
        _write_jsonl(self.hist / "standings.jsonl", [{"date": "2026-09-08", "team_abbrev": "NYY"}])
        data = self.report()
        stores = data["stores"]
        self.assertEqual(data["expected_through"], "2026-10-02")
        self.assertEqual(stores["mlb_results"]["lag_days"], 9)
        self.assertEqual(stores["pitcher_logs"]["lag_days"], 25)
        self.assertEqual(stores["bullpen_log"]["lag_days"], 26)
        self.assertEqual(set(data["core_stale"]),
                         {"mlb_results", "pitcher_logs", "bullpen_log", "standings"})
        self.assertEqual(data["oldest_through"], "2026-09-06")
        self.assertIn("behind 2026-10-02", stores["bullpen_log"]["reason"])

    def test_tolerance_is_a_day_not_zero(self):
        _write_jsonl(self.hist / "bullpen_log.jsonl", [{"date": "2026-10-01", "empty": True}])
        self.assertFalse(self.report()["stores"]["bullpen_log"]["stale"])      # 1 behind yesterday
        _write_jsonl(self.hist / "bullpen_log.jsonl", [{"date": "2026-09-30", "empty": True}])
        sf.reset_cache_for_tests()
        self.assertTrue(self.report()["stores"]["bullpen_log"]["stale"])       # 2 behind


class NeverGreenByDefault(Base):

    def test_absent_stores_are_stale_with_a_reason(self):
        data = self.report()
        for name in ("mlb_results", "pitcher_logs", "bullpen_log", "standings"):
            self.assertTrue(data["stores"][name]["stale"], name)
            self.assertEqual(data["stores"][name]["reason"], "store is absent")
            self.assertIsNone(data["stores"][name]["through"])
        self.assertIsNone(data["oldest_through"])

    def test_an_unreadable_store_says_why(self):
        (self.hist / "pitcher_splits.json").write_text("{broken", encoding="utf-8")
        entry = self.report()["stores"]["pitcher_splits"]
        self.assertTrue(entry["stale"])
        self.assertTrue(entry["reason"].startswith("unreadable"))

    def test_handedness_has_no_dates_and_is_never_called_stale_for_it(self):
        (self.hist / "handedness.json").write_text(json.dumps({"1": {"bats": "R"}}), encoding="utf-8")
        entry = self.report()["stores"]["handedness"]
        self.assertEqual(entry["rows"], 1)
        self.assertFalse(entry["stale"])
        self.assertIsNone(entry["through"])


class StandingsAfterTheRegularSeason(Base):

    def _seed(self, newest_regular, standings_through):
        _results(self.hist, [(newest_regular, "R"), ("2026-10-01", "F")],
                 {newest_regular: 0, "2026-10-02": 0})
        _write_jsonl(self.hist / "standings.jsonl", [{"date": standings_through, "team_abbrev": "NYY"}])

    def test_the_last_regular_season_snapshot_is_not_stale_in_october(self):
        self._seed("2026-09-27", "2026-09-27")
        entry = self.report()["stores"]["standings"]
        self.assertFalse(entry["stale"], entry)
        self.assertEqual(entry["expected_through"], "2026-09-27")

    def test_a_snapshot_that_stops_short_of_the_season_end_is_still_stale(self):
        self._seed("2026-09-27", "2026-09-08")
        self.assertTrue(self.report()["stores"]["standings"]["stale"])

    def test_during_the_season_today_is_the_target(self):
        _results(self.hist, [("2026-07-01", "R")], {"2026-07-01": 0})
        now = datetime(2026, 7, 2, 16, 0, tzinfo=timezone.utc)
        self.assertEqual(sf.standings_horizon("2026-07-01", "2026-07-02"), "2026-07-02")
        self.assertEqual(sf.standings_horizon("2026-09-27", "2026-10-03"), "2026-09-27")
        self.assertEqual(sf.standings_horizon(None, "2026-10-03"), "2026-10-03")


class TheBaseballDate(unittest.TestCase):

    def test_after_8pm_eastern_the_baseball_date_is_still_today(self):
        self.assertEqual(sf.baseball_date("2026-10-04T00:30:00Z"), "2026-10-03")   # 8:30 pm EDT
        self.assertEqual(sf.baseball_date("2026-10-04T03:59:00Z"), "2026-10-03")
        self.assertEqual(sf.baseball_date("2026-10-04T04:00:00Z"), "2026-10-04")   # midnight EDT

    def test_standard_time_uses_five_hours(self):
        self.assertEqual(sf.baseball_date("2026-12-02T04:30:00Z"), "2026-12-01")
        self.assertEqual(sf.baseball_date("2026-12-02T05:00:00Z"), "2026-12-02")

    def test_it_is_the_same_rule_the_postseason_page_uses(self):
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        for hours in range(0, 365 * 24, 5):
            moment = start + timedelta(hours=hours)
            self.assertEqual(sf.eastern_offset(moment), postseason_page.eastern_utc_offset(moment), moment)


class ChangedFilesAreReReadUnchangedOnesAreNot(Base):

    def test_an_unchanged_store_is_scanned_once(self):
        _write_jsonl(self.hist / "bullpen_log.jsonl", [{"date": "2026-10-02", "empty": True}])
        spec = next(s for s in sf._build_specs() if s.name == "bullpen_log")
        calls = []
        real = spec.scan

        def counting(path):
            calls.append(path)
            return real(path)

        with mock.patch.object(sf, "_build_specs", return_value=tuple(
                sf.StoreSpec(s.name, s.rel, s.tolerance_days, s.reads,
                             counting if s.name == "bullpen_log" else s.scan)
                for s in sf._build_specs())):
            self.report()
            self.report()
        self.assertEqual(len(calls), 1)

    def test_a_changed_store_is_re_read_immediately(self):
        path = self.hist / "bullpen_log.jsonl"
        _write_jsonl(path, [{"date": "2026-09-01", "empty": True}])
        self.assertTrue(self.report()["stores"]["bullpen_log"]["stale"])
        _write_jsonl(path, [{"date": "2026-09-01", "empty": True}, {"date": "2026-10-02", "empty": True}])
        self.assertFalse(self.report()["stores"]["bullpen_log"]["stale"])


if __name__ == "__main__":
    unittest.main()
