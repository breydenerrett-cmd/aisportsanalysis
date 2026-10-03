"""Regression tests from the adversarial review of the display refresh
(commit d1f61b4f, 2026-10-03). Each one failed against that commit as shipped.

  1. The pitcher-log label on a game page read the newest APPEARANCE, not
     what the log covers. The day after a league-wide off day (between
     postseason rounds, after the All-Star break) every page said "PITCHER LOG
     ENDS <two days ago>" and "days rest ... counted from the log" for a log
     refreshed that morning. Coverage is the later of the newest appearance
     and the newest refresh marker -- the same definition
     `store_freshness` uses.
  2. The results manifest was promoted even when its results CSV was refused.
     The manifest is the CSV's coverage record: promoted alone it claims dates
     whose games the store does not hold, `/health` calls the store current,
     and resume never fetches those dates again.
  3. In the off-season no starter is a refresh candidate, so no refresh marker
     is ever written and `pitcher_logs` stayed "stale" from about three weeks
     after the World Series until March: a permanent core-stale flag on
     `/health` and a guard that started a refresh child every hour all winter.

No network: the fake Stats API from tests/_fake_statsapi.py, temp data roots.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from src.detect import dossier
from src.pipeline import display_refresh as dr, history, pitchers, store_freshness as sf
from tests.test_display_refresh import Base


def _appearance(pid, day, game_type=None):
    row = {"person_id": pid, "date": day, "season": day[:4], "games_started": 1,
           "innings_pitched": 6.0, "earned_runs": 2, "runs": 2, "hits": 5, "walks": 1,
           "strikeouts": 6, "home_runs": 1, "batters_faced": 24, "pitches": 90}
    if game_type:
        row["game_type"] = game_type
    return row


def _marker(pid, checked_utc):
    return {"person_id": pid, "season": checked_utc[:4], "date": None, "empty": False,
            "checked_utc": checked_utc}


class ThePitcherLogLabelReadsCoverageNotTheNewestStart(unittest.TestCase):

    GAME = {"date": "2026-10-03", "away_team": "NYY", "home_team": "BOS",
            "away_probable_id": 111, "home_probable_id": 222}

    def starters(self, logs):
        return dossier.build(self.GAME, {}, pitcher_logs=logs).to_dict()["sections"]["starters"]

    def test_a_log_refreshed_this_morning_is_not_flagged_after_an_off_day(self):
        # No games league-wide on 10-02. The log was refreshed on 10-03 and
        # holds every start through the last game day, 10-01.
        logs = {"111": [_appearance(111, "2026-09-26"), _appearance(111, "2026-10-01", "F"),
                        _marker(111, "2026-10-03T13:00:00+00:00")],
                "222": [_appearance(222, "2026-09-30", "F"),
                        _marker(222, "2026-10-03T13:00:00+00:00")]}
        section = self.starters(logs)
        self.assertFalse(section["logs_stale"], section)
        self.assertEqual(section["logs_through"], "2026-10-03")

    def test_a_log_that_really_ends_weeks_ago_is_still_flagged(self):
        logs = {"111": [_appearance(111, "2026-09-07")],
                "222": [_appearance(222, "2026-09-06"), _marker(222, "2026-09-07T10:00:00+00:00")]}
        section = self.starters(logs)
        self.assertTrue(section["logs_stale"])
        self.assertEqual(section["logs_through"], "2026-09-07")


class TheManifestTravelsWithItsResults(Base):

    def test_a_refused_results_copy_keeps_its_committed_manifest_too(self):
        # Six copies of one committed row (a union-merged or hand-edited CSV).
        # read_results keys by game_pk, so the refreshed copy holds fewer
        # physical rows than the committed one even after five new games: the
        # CSV copy is refused. Its manifest must not be promoted without it.
        csv_path = self.hist / "mlb_results.csv"
        raw = csv_path.read_bytes()
        dup = next(line for line in raw.splitlines(keepends=True) if line.startswith(b"900,"))
        csv_path.write_bytes(raw + dup * 6)
        manifest_path = self.hist / "mlb_results.manifest.json"
        manifest_before = manifest_path.read_bytes()

        report = self.run_refresh(only=["results"])

        kept = {k["file"]: k["reason"] for k in report["kept"]}
        self.assertIn("fewer rows", kept.get("mlb_results.csv", ""), report["kept"])
        self.assertIn("mlb_results.manifest.json", kept, report["promoted"])
        self.assertEqual(manifest_path.read_bytes(), manifest_before)
        stored = history.read_results(csv_path)
        self.assertNotIn("13", stored)
        self.assertNotIn("2026-10-01", history.read_manifest(manifest_path),
                         "the manifest claims a date whose game the store does not hold")
        self.assertIn("mlb_results", self.freshness()["core_stale"])

    def test_an_ordinary_refresh_still_promotes_both(self):
        report = self.run_refresh(only=["results"])
        promoted = {p["file"] for p in report["promoted"]}
        self.assertEqual(promoted, {"mlb_results.csv", "mlb_results.manifest.json"})


class AStepThatRaisesPromotesNothing(Base):

    def test_a_partial_write_inside_the_shrink_tolerance_is_not_promoted(self):
        # 100 pitchers on file. The step rewrites its work copy (write_logs
        # truncates and rewrites the whole file), gets 99 of them out, and the
        # disk fills. 99% of the rows is inside the 2% pitcher shrink
        # tolerance, so the row count cannot tell this copy is unsound; only
        # the step's own failure can.
        logs = {str(1000 + i): [_appearance(1000 + i, "2026-06-01")] for i in range(100)}
        pitchers.write_logs(logs, self.hist / "pitcher_logs.jsonl")
        before = (self.hist / "pitcher_logs.jsonl").read_bytes()

        def partial_write(person_ids, season, path=None, **kw):
            rows = pitchers.read_logs(path)
            pitchers.write_logs(dict(list(rows.items())[:99]), path)
            raise OSError(28, "No space left on device")

        with mock.patch.object(pitchers, "build_log_store", side_effect=partial_write):
            report = self.run_refresh(only=["pitchers"])
        self.assertEqual(report["steps"]["pitchers"]["status"], "failed")
        self.assertEqual((self.hist / "pitcher_logs.jsonl").read_bytes(), before)
        self.assertEqual(report["promoted"], [])


class PitcherLogsInTheOffSeason(unittest.TestCase):

    WINTER = datetime(2026, 12, 15, 17, 0, tzinfo=timezone.utc)

    def seed(self, root: Path) -> None:
        hist = root / "historical"
        hist.mkdir(parents=True)
        cols = history.RESULT_COLUMNS
        store = {}
        for pk, day, gtype in (("1", "2026-09-27", "R"), ("2", "2026-11-01", "W")):
            row = {c: None for c in cols}
            row.update(game_pk=pk, date=day, game_type=gtype, away_team="NYY", home_team="LAD",
                       away_score="3", home_score="2", away_probable_id="111",
                       home_probable_id="222")
            store[pk] = row
        history.write_results(store, hist / "mlb_results.csv")
        dates, day = {}, date(2026, 9, 27)
        while day <= date(2026, 12, 14):
            played = day.isoformat() in ("2026-09-27", "2026-11-01")
            dates[day.isoformat()] = {"total": int(played), "final": int(played), "pending": 0,
                                      "cancelled": 0, "game_types": sorted({"R", "F", "D", "L", "W", "P"})}
            day += timedelta(days=1)
        history.write_manifest(dates, hist / "mlb_results.manifest.json")
        # The last refresh that had a candidate ran three weeks after the
        # World Series; nothing has had a start since.
        pitchers.write_logs({"111": [_appearance(111, "2026-11-01", "W"),
                                     _marker(111, "2026-11-21T10:00:00+00:00")]},
                            hist / "pitcher_logs.jsonl")
        (hist / "bullpen_log.jsonl").write_text(
            json.dumps({"date": "2026-12-14", "empty": True}) + "\n", encoding="utf-8")
        (hist / "standings.jsonl").write_text(
            json.dumps({"date": "2026-09-27", "team_abbrev": "NYY"}) + "\n", encoding="utf-8")

    def test_a_winter_with_no_games_is_not_a_stale_pitcher_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.seed(root)
            sf.reset_cache_for_tests()
            report = sf.report(root, self.WINTER)
            self.assertEqual(report["core_stale"], [], report["stores"]["pitcher_logs"])
            calls = []
            decision = dr.guard_tick(now=self.WINTER, root=root,
                                     child=lambda r: calls.append(r) or {"exit": 0, "result": "ok"})
            self.assertFalse(decision["ran"], decision)
            self.assertEqual(calls, [])

    def test_in_season_a_pitcher_log_behind_the_results_is_still_stale(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.seed(root)
            hist = root / "historical"
            # Same stores, but a game was played yesterday and the log stops in November.
            store = history.read_results(hist / "mlb_results.csv")
            row = dict(store["2"], game_pk="3", date="2026-12-14", game_type="R")
            store["3"] = row
            history.write_results(store, hist / "mlb_results.csv")
            sf.reset_cache_for_tests()
            report = sf.report(root, self.WINTER)
            self.assertIn("pitcher_logs", report["core_stale"])


if __name__ == "__main__":
    unittest.main()
