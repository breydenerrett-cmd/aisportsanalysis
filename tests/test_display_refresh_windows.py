"""The refresh's date windows (2026-10-03, review items 4 and 5).

ITEM 4, SLIDING WINDOWS AGE OUT. The 21-day pitcher window and the 75-day
bullpen window were relative to TODAY, not to what the committed copy covers.
Once the gap since the copy's last date outgrew a window, the oldest part of the
gap stopped being fetched while /health (which counts the newest date or
marker anywhere in a file) said the store was current. The anchor is now each
store's own coverage end, with a small overlap:

  bullpen   from min(the 75-day window start, the log's newest date - 2 days)
  pitchers  a starter whose results show a start on or after his OWN log's
            coverage end - 2 days (his refresh marker, in Eastern time, or his
            newest start); one never checked only if he started in the last 21
            days (a full-season backfill is daily_bootstrap.sh's job)

ITEM 5, THE SEALED WINDOW. 2026-01-01..2026-08-27 outcomes are sealed. The
bullpen window reached back to 2026-07-20. No step may request a date before
2026-08-28 (`_unsealed_start`), however old a store's coverage is, and rows
already stored in the window are left exactly as they are: the pitcher game-log
endpoint answers with a whole season, so the refresh puts the committed
sealed-window starts back over whatever the feed now says for them.

Temp data roots and the fake Stats API (tests/_fake_statsapi.py). No network.
"""

from __future__ import annotations

import json
import unittest
from datetime import date, datetime, timezone
from unittest import mock

from src.pipeline import bullpen, display_refresh as dr, history, pitchers
from src.providers import mlb_news
from tests._fake_statsapi import raw_game
from tests.test_display_refresh import Base, NOW


def _appearance(pid, day, innings=6.0, **extra):
    row = {"person_id": pid, "date": day, "season": day[:4], "games_started": 1,
           "innings_pitched": innings, "earned_runs": 2, "runs": 2, "hits": 5, "walks": 1,
           "strikeouts": 6, "home_runs": 1, "batters_faced": 24, "pitches": 90}
    row.update(extra)
    return row


def _marker(pid, checked):
    return {"person_id": pid, "season": "2026", "date": None, "empty": False, "checked_utc": checked}


def _add_results_game(hist, pk, day, away_sp=None, home_sp=None, game_type="R"):
    store = history.read_results(hist / "mlb_results.csv")
    row = {c: None for c in history.RESULT_COLUMNS}
    row.update(game_pk=str(pk), date=day, game_type=game_type, away_team="NYY", home_team="BOS",
               away_score="3", home_score="2", winner="NYY", home_won="0", total_runs="5",
               run_differential="1", away_probable_id=str(away_sp) if away_sp else None,
               home_probable_id=str(home_sp) if home_sp else None)
    store[str(pk)] = row
    history.write_results(store, hist / "mlb_results.csv")


def _gamelog_calls(fake, pid):
    return [c for c in fake.calls if c[0] == f"people/{pid}/stats" and c[1].get("stats") == "gameLog"]


class ThePitcherWindowIsAnchoredOnEachPitchersOwnCoverage(Base):

    LATER = datetime(2026, 10, 14, 16, 0, tzinfo=timezone.utc)      # 12:00 Eastern; 21 days back is 09-23

    def test_a_start_the_log_missed_is_fetched_though_it_is_older_than_21_days(self):
        # 555 was last checked on 09-07 with starts through 09-01; the results
        # show a start of his on 09-10, 34 days before "today": outside the
        # old window, after his own coverage.
        pitchers.write_logs({"555": [_appearance(555, "2026-09-01"),
                                     _marker(555, "2026-09-07T10:00:00+00:00")]},
                            self.hist / "pitcher_logs.jsonl")
        _add_results_game(self.hist, 70, "2026-09-10", away_sp=555)
        self.fake.game_logs = {555: [{"date": "2026-09-01", "gameType": "R"},
                                     {"date": "2026-09-10", "gameType": "R"}]}
        report = self.run_refresh(only=["pitchers"], now=self.LATER)
        self.assertTrue(_gamelog_calls(self.fake, 555), "his log was never asked for")
        dates = [a["date"] for a in pitchers.read_logs(self.hist / "pitcher_logs.jsonl")["555"] if a.get("date")]
        self.assertEqual(dates, ["2026-09-01", "2026-09-10"])
        self.assertEqual(report["steps"]["pitchers"]["status"], "ok")

    def test_a_starter_whose_log_already_covers_his_last_start_is_left_alone(self):
        pitchers.write_logs({"556": [_appearance(556, "2026-09-05"),
                                     _marker(556, "2026-09-12T10:00:00+00:00")]},
                            self.hist / "pitcher_logs.jsonl")
        _add_results_game(self.hist, 71, "2026-09-05", away_sp=556)
        self.run_refresh(only=["pitchers"], now=self.LATER)
        self.assertEqual(_gamelog_calls(self.fake, 556), [])

    def test_the_overlap_catches_a_start_on_the_day_the_log_was_checked(self):
        # checked on the 12th (Eastern), started that evening: asked again
        pitchers.write_logs({"557": [_appearance(557, "2026-09-05"),
                                     _marker(557, "2026-09-12T14:00:00+00:00")]},
                            self.hist / "pitcher_logs.jsonl")
        _add_results_game(self.hist, 72, "2026-09-12", away_sp=557)
        self.fake.game_logs = {557: [{"date": "2026-09-12", "gameType": "R"}]}
        self.run_refresh(only=["pitchers"], now=self.LATER)
        self.assertTrue(_gamelog_calls(self.fake, 557))

    def test_a_starter_never_checked_who_started_long_ago_is_not_backfilled(self):
        _add_results_game(self.hist, 73, "2026-09-05", away_sp=558)          # no log at all
        self.run_refresh(only=["pitchers"], now=self.LATER)
        self.assertEqual(_gamelog_calls(self.fake, 558), [])

    def test_a_starter_never_checked_who_started_lately_is_fetched(self):
        _add_results_game(self.hist, 74, "2026-10-10", away_sp=559)
        self.fake.game_logs = {559: [{"date": "2026-10-10", "gameType": "F"}]}
        self.run_refresh(only=["pitchers"], now=self.LATER)
        self.assertTrue(_gamelog_calls(self.fake, 559))

    def test_a_log_with_no_marker_is_covered_through_its_newest_start(self):
        self.assertEqual(dr._pitcher_covered_through([_appearance(1, "2026-09-05")], "2026"), "2026-09-05")
        self.assertIsNone(dr._pitcher_covered_through([], "2026"))
        # another season's rows say nothing about this one
        self.assertIsNone(dr._pitcher_covered_through([_appearance(1, "2025-09-05")], "2026"))

    def test_the_marker_is_read_in_eastern_time(self):
        # 01:30 UTC on the 13th is 21:30 Eastern on the 12th
        self.assertEqual(dr._eastern_day("2026-09-13T01:30:00+00:00"), "2026-09-12")
        self.assertIsNone(dr._eastern_day("not a time"))
        self.assertIsNone(dr._eastern_day(None))


class TheBullpenWindowIsAnchoredOnTheLogsOwnEnd(Base):

    # yesterday is 11-24, so the 75-day window starts 09-11; the log ends 09-06.
    LATER = datetime(2026, 11, 25, 17, 0, tzinfo=timezone.utc)

    def test_a_gap_older_than_the_window_is_still_fetched(self):
        self.fake.schedule["2026-09-10"] = [raw_game(41, "2026-09-10", "NYY", "BOS", 3, 1, "R")]
        self.run_refresh(only=["bullpen"], now=self.LATER)
        asked = [p["date"] for path, p in self.fake.calls if path == "schedule"]
        self.assertIn("2026-09-10", asked, "the gap since the log's last date was not fetched")
        rows = [r for r in bullpen.read_log(self.hist / "bullpen_log.jsonl") if r["date"] == "2026-09-10"]
        self.assertTrue(rows and not rows[0].get("empty"))

    def test_the_window_is_still_a_floor_when_the_log_is_current(self):
        # a log current to the day before yesterday: the 75-day window still
        # heals a hole inside it
        self.fake.schedule["2026-10-01"] = [raw_game(42, "2026-10-01", "NYY", "BOS", 3, 1, "F")]
        (self.hist / "bullpen_log.jsonl").write_text(
            "\n".join(json.dumps(r) for r in (
                {"date": "2026-09-05", "game_pk": 5, "team": "NYY", "person_id": 7, "started": False,
                 "innings": 1.0, "pitches": 12},
                {"date": "2026-10-02", "empty": True})) + "\n", encoding="utf-8")
        self.run_refresh(only=["bullpen"], now=NOW)             # 10-03: yesterday is 10-02
        asked = [p["date"] for path, p in self.fake.calls if path == "schedule"]
        self.assertIn("2026-10-01", asked)

    def test_a_date_the_log_already_holds_costs_no_request(self):
        self.run_refresh(only=["bullpen"], now=NOW)
        first = len(self.fake.calls)
        self.run_refresh(only=["bullpen"], now=NOW)
        second = len(self.fake.calls) - first
        # the probe and yesterday's whole re-fetch; nothing else is asked twice
        self.assertLessEqual(second, 6, second)


class TheSealedWindowIsNeverRequested(Base):

    SEALED = ("2026-01-01", "2026-08-27")

    def seed_old_coverage(self):
        """Stores whose coverage ends INSIDE the sealed window, so every
        window anchored on them reaches into it."""
        (self.hist / "bullpen_log.jsonl").write_text(
            json.dumps({"date": "2026-07-10", "game_pk": 4, "team": "NYY", "person_id": 7,
                        "started": False, "innings": 1.0, "pitches": 10}) + "\n"
            + json.dumps({"date": "2026-09-05", "game_pk": 5, "team": "NYY", "person_id": 7,
                          "started": False, "innings": 1.0, "pitches": 12}) + "\n", encoding="utf-8")
        entry = {"total": 1, "final": 1, "pending": 0, "cancelled": 0, "stored": 1, "skipped_game_type": 0}
        history.write_manifest({"2026-07-04": entry, "2026-08-01": entry},
                               self.hist / "mlb_results.manifest.json")
        (self.hist / "standings.jsonl").write_text(json.dumps(
            {"date": "2026-07-20", "season": "2026", "team_abbrev": "NYY", "team_id": 147,
             "captured_at": "2026-07-20T20:00:00+00:00", "wins": 50, "losses": 40}) + "\n", encoding="utf-8")
        # games exist in the window, so a request for one would be visible
        for pk, day in ((51, "2026-07-25"), (52, "2026-08-15"), (53, "2026-08-27"), (54, "2026-08-28")):
            self.fake.schedule[day] = [raw_game(pk, day, "NYY", "BOS", 3, 1, "R")]
        self.fake.standings_dates |= {"2026-07-21", "2026-08-12", "2026-08-27"}

    def sealed_calls(self):
        low, high = self.SEALED
        out = []
        for path, params in self.fake.calls:
            day = str(params.get("date") or "")
            if low <= day <= high:
                out.append((path, day))
            if path in ("game/51/boxscore", "game/52/boxscore", "game/53/boxscore"):
                out.append((path, "boxscore of a sealed game"))
        return out

    def test_no_step_asks_for_a_sealed_date(self):
        self.seed_old_coverage()
        asked_transactions = []
        original = mlb_news.fetch
        with mock.patch.object(mlb_news, "fetch", side_effect=lambda start, end=None, **kw: (
                asked_transactions.append((start, end)) or original(start, end, **kw))):
            self.run_refresh()
        self.assertEqual(self.sealed_calls(), [])
        for start, _end in asked_transactions:
            self.assertGreaterEqual(str(start)[:10], "2026-08-28")

    def test_the_first_date_a_step_may_ask_for_is_the_floor(self):
        self.seed_old_coverage()
        self.run_refresh(only=["bullpen"])
        asked = sorted({p["date"] for path, p in self.fake.calls if path == "schedule"
                        and p["date"] < "2026-09-05"})
        self.assertEqual(asked[0], "2026-08-28")

    def test_the_floor_helper(self):
        floor = dr.SEALED_FLOOR
        self.assertEqual(floor, date(2026, 8, 28))
        # a start inside the window, or before it with an end inside or after it
        self.assertEqual(dr._unsealed_start(date(2026, 7, 20), date(2026, 10, 2)), floor)
        self.assertEqual(dr._unsealed_start(date(2025, 10, 1), date(2026, 10, 2)), floor)
        self.assertEqual(dr._unsealed_start(date(2026, 1, 1), date(2026, 10, 2)), floor)
        # at or after the floor, untouched
        self.assertEqual(dr._unsealed_start(floor, date(2026, 10, 2)), floor)
        self.assertEqual(dr._unsealed_start(date(2026, 9, 9), date(2026, 10, 2)), date(2026, 9, 9))
        # a range wholly inside the window leaves nothing to ask for
        self.assertIsNone(dr._unsealed_start(date(2026, 7, 20), date(2026, 8, 27)))
        self.assertIsNone(dr._unsealed_start(date(2026, 2, 1), date(2026, 3, 1)))
        # 2025 is not sealed
        self.assertEqual(dr._unsealed_start(date(2025, 9, 1), date(2025, 10, 1)), date(2025, 9, 1))
        # the empty range stays empty
        self.assertIsNone(dr._unsealed_start(date(2026, 10, 3), date(2026, 10, 2)))

    def test_the_window_edges(self):
        self.assertTrue(dr._in_sealed_window("2026-01-01"))
        self.assertTrue(dr._in_sealed_window("2026-08-27"))
        self.assertFalse(dr._in_sealed_window("2026-08-28"))
        self.assertFalse(dr._in_sealed_window("2025-12-31"))
        self.assertFalse(dr._in_sealed_window(None))
        self.assertFalse(dr._in_sealed_window("garbage"))


class RowsAlreadyStoredInTheWindowAreLeftAsTheyAre(Base):

    def test_nothing_in_the_window_is_purged_or_rewritten_by_the_date_steps(self):
        bullpen_rows = [{"date": "2026-07-10", "game_pk": 4, "team": "NYY", "person_id": 7,
                         "started": False, "innings": 1.0, "pitches": 10}]
        old_line = json.dumps(bullpen_rows[0], sort_keys=True)
        (self.hist / "bullpen_log.jsonl").write_text(old_line + "\n", encoding="utf-8")
        _add_results_game(self.hist, 60, "2026-07-04", away_sp=1, home_sp=2)
        csv_before = {k: v for k, v in history.read_results(self.hist / "mlb_results.csv").items()
                      if v["date"] < "2026-08-28"}
        self.run_refresh()
        self.assertIn(old_line, (self.hist / "bullpen_log.jsonl").read_text(encoding="utf-8"))
        csv_after = {k: v for k, v in history.read_results(self.hist / "mlb_results.csv").items()
                     if v["date"] < "2026-08-28"}
        self.assertEqual(csv_after, csv_before)

    def test_the_feed_does_not_rewrite_a_stored_sealed_window_start(self):
        # The game-log endpoint answers with a whole season. 111 has a sealed
        # window start on file at 5.0 innings; the feed now says 6.0 for the
        # same appearance, and has a new start after the floor.
        pitchers.write_logs({"111": [_appearance(111, "2026-07-15", innings=5.0),
                                     _marker(111, "2026-09-07T10:00:00+00:00")]},
                            self.hist / "pitcher_logs.jsonl")
        self.fake.game_logs = {111: [{"date": "2026-07-15", "gameType": "R", "ip": "6.0"},
                                     {"date": "2026-09-29", "gameType": "F"}]}
        report = self.run_refresh(only=["pitchers"])
        rows = {a["date"]: a for a in pitchers.read_logs(self.hist / "pitcher_logs.jsonl")["111"] if a.get("date")}
        self.assertEqual(rows["2026-07-15"]["innings_pitched"], 5.0, "a sealed row was rewritten")
        self.assertIn("2026-09-29", rows, "an appearance after the floor still arrives")
        self.assertEqual(report["steps"]["pitchers"]["sealed_rows_kept"], 1)

    def test_an_appearance_the_store_does_not_hold_is_not_invented_or_dropped(self):
        pitchers.write_logs({"111": [_marker(111, "2026-09-07T10:00:00+00:00")]},
                            self.hist / "pitcher_logs.jsonl")
        self.fake.game_logs = {111: [{"date": "2026-07-15", "gameType": "R"}]}
        self.run_refresh(only=["pitchers"])
        dates = [a["date"] for a in pitchers.read_logs(self.hist / "pitcher_logs.jsonl")["111"] if a.get("date")]
        self.assertEqual(dates, ["2026-07-15"], "a hole in the store is filled as the feed gave it")


if __name__ == "__main__":
    unittest.main()
