"""Where a stale store SHOWS: the game page's own sections, and /health.

The refresh (tests/test_display_refresh.py) keeps stores current. This file
pins what is said when one is NOT, because the failure on 2026-10-03 was not
only old data but old data presented as current: "no relief appearances in the
last 7 days" from a bullpen log that stopped on Sept 6, "days rest 14" from a
pitcher log that stopped on Sept 7, a team record a week old with no date.

  - the dossier's teams / starters sections carry the date the store covers and
    whether that is too old to describe THIS game
  - the bullpen workload carries `log_through` / `log_stale`
  - a PAST game viewed after the fact is not called stale just because the
    store has since moved on
  - /health carries `data_freshness`, informational, and never flips `status`
  - the container guard is OFF in a plain test/dev process
"""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from src.appstate import apphealth
from src.detect import dossier
from src.pipeline import bullpen, display_refresh, enrichment, store_freshness
from src.providers import mlb


def _store(through="2026-09-23"):
    rows = {}
    pk = 0
    for day in range(1, 24):
        date = f"2026-09-{day:02d}"
        if date > through:
            break
        for away, home in (("NYY", "BOS"), ("LAD", "SD")):
            pk += 1
            rows[str(pk)] = {"game_pk": str(pk), "date": date, "game_type": "R", "away_team": away,
                             "home_team": home, "away_score": "3", "home_score": "2",
                             "winner": away, "home_won": "0", "total_runs": "5",
                             "run_differential": "1"}
    return rows


def _logs(last="2026-09-07"):
    return {"111": [{"person_id": 111, "date": "2026-09-01", "season": "2026", "games_started": 1,
                     "innings_pitched": 6.0, "earned_runs": 2, "runs": 2, "hits": 5, "walks": 1,
                     "strikeouts": 6, "home_runs": 1, "batters_faced": 24, "pitches": 90},
                    {"person_id": 111, "date": last, "season": "2026", "games_started": 1,
                     "innings_pitched": 5.0, "earned_runs": 1, "runs": 1, "hits": 4, "walks": 1,
                     "strikeouts": 5, "home_runs": 0, "batters_faced": 21, "pitches": 80}]}


def _game(date):
    return {"game_pk": 1, "date": date, "away_team": "NYY", "home_team": "BOS",
            "away_probable_id": 111, "home_probable_id": 111}


class TheGamePageSaysWhatItsStoresCover(unittest.TestCase):

    def test_a_game_after_the_logs_end_is_marked_stale_with_the_date(self):
        d = dossier.build(_game("2026-10-03"), _store(), pitcher_logs=_logs("2026-09-07"))
        starters = d.sections["starters"]
        self.assertEqual(starters["logs_through"], "2026-09-07")
        self.assertTrue(starters["logs_stale"])
        teams = d.sections["teams"]
        self.assertEqual(teams["results_through"], "2026-09-23")
        self.assertTrue(teams["results_stale"])

    def test_a_game_the_stores_do_cover_is_not(self):
        d = dossier.build(_game("2026-09-24"), _store(), pitcher_logs=_logs("2026-09-23"))
        self.assertFalse(d.sections["starters"]["logs_stale"])
        self.assertFalse(d.sections["teams"]["results_stale"])

    def test_yesterdays_games_are_the_newest_a_pregame_page_can_hold(self):
        d = dossier.build(_game("2026-09-24"), _store("2026-09-23"), pitcher_logs=_logs("2026-09-23"))
        self.assertFalse(d.sections["teams"]["results_stale"])

    def test_a_past_game_is_not_called_stale_because_the_store_moved_on(self):
        d = dossier.build(_game("2026-09-10"), _store(), pitcher_logs=_logs("2026-09-23"))
        self.assertFalse(d.sections["teams"]["results_stale"])
        self.assertFalse(d.sections["starters"]["logs_stale"])

    def test_no_dated_row_at_all_is_stale_never_fresh(self):
        self.assertTrue(dossier._ends_before(None, "2026-10-03"))
        self.assertTrue(dossier._ends_before("not-a-date", "2026-10-03"))


class TheBullpenWorkloadSaysWhatTheLogCovers(unittest.TestCase):

    def _inputs(self, date, log):
        games = [{"game_pk": 1, "away_team": "NYY", "home_team": "BOS"}]
        with mock.patch.object(bullpen, "read_log", return_value=log), \
                mock.patch.object(enrichment.pitchers, "read_logs", return_value={}), \
                mock.patch.object(enrichment.lineup_store, "read", return_value={}), \
                mock.patch.object(enrichment.lineups, "read_handedness", return_value={}), \
                mock.patch.object(enrichment.lineups, "read_splits", return_value={}), \
                mock.patch.object(enrichment.standings, "read", return_value={}), \
                mock.patch.object(enrichment.matchup_history, "read", return_value={}), \
                mock.patch.object(enrichment.weather_capture, "read", return_value=[]), \
                mock.patch.object(enrichment.news, "read", return_value=[]), \
                mock.patch.object(enrichment.statcast, "read", return_value={"rows": []}):
            return enrichment.enrichment_inputs(games, date, {})

    def test_a_log_that_ends_before_the_window_is_flagged_on_every_club(self):
        log = [{"date": "2026-09-06", "team": "NYY", "person_id": 1, "started": False, "innings": 1.0}]
        pens = self._inputs("2026-10-03", log)["bullpen_by_team"]
        for team in ("NYY", "BOS"):
            self.assertEqual(pens[team]["log_through"], "2026-09-06")
            self.assertTrue(pens[team]["log_stale"])
            self.assertEqual(pens[team]["reliever_count"], 0)     # the sentence the page used to print as fact

    def test_a_current_log_is_not(self):
        log = [{"date": "2026-10-02", "team": "NYY", "person_id": 1, "started": False, "innings": 1.0}]
        pens = self._inputs("2026-10-03", log)["bullpen_by_team"]
        self.assertFalse(pens["NYY"]["log_stale"])
        self.assertEqual(pens["NYY"]["reliever_count"], 1)


class TheFetcherAsksForThePostseasonOnlyWhenTold(unittest.TestCase):

    def _log(self, **kw):
        seen = {}

        def fake(path, params=None, timeout=None):
            seen["params"] = dict(params or {})
            return {"stats": [{"splits": [
                {"date": "2026-09-29", "gameType": "F", "isHome": True,
                 "stat": {"gamesStarted": 1, "inningsPitched": "6.0", "earnedRuns": 2}}]}]}

        with mock.patch.object(mlb, "_get_json", fake):
            rows = mlb.fetch_pitcher_game_log(1, 2026, **kw)
        return rows, seen["params"]

    def test_the_default_request_and_rows_are_exactly_what_they_always_were(self):
        rows, params = self._log()
        self.assertEqual(params, {"stats": "gameLog", "group": "pitching", "season": 2026})
        self.assertNotIn("game_type", rows[0])

    def test_asking_for_the_postseason_tags_rows_and_never_requests_the_aggregate_P(self):
        rows, params = self._log(game_types=mlb.DECISIVE_GAME_TYPES)
        self.assertEqual(params["gameType"], "D,F,L,R,W")
        self.assertEqual(rows[0]["game_type"], "F")

    def test_P_alone_is_still_honoured(self):
        _rows, params = self._log(game_types={"P"})
        self.assertEqual(params["gameType"], "P")


class HealthCarriesTheDataFreshness(unittest.TestCase):

    def test_it_is_present_informational_and_never_flips_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "historical").mkdir()
            store_freshness.reset_cache_for_tests()
            now = datetime(2026, 10, 3, 16, 0, tzinfo=timezone.utc)
            with mock.patch.object(apphealth, "check_app_db",
                                   return_value=apphealth.DbCheck(reachable=True, path="x")):
                data = apphealth.report(data_dir=root, now=now)
        fresh = data["data_freshness"]
        self.assertEqual(fresh["expected_through"], "2026-10-02")
        self.assertEqual(set(fresh["core_stale"]),
                         {"mlb_results", "pitcher_logs", "bullpen_log", "standings"})
        self.assertIn("guard", fresh)
        # every core store is absent here, and the site is still "ok": a stale
        # input is something the page labels, not a reason to leave rotation.
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["reasons"], [])

    def test_a_failure_inside_the_freshness_check_cannot_take_health_down(self):
        with mock.patch.object(store_freshness, "report", side_effect=RuntimeError("boom")):
            out = apphealth.check_data_freshness(Path("/nonexistent"), datetime.now(timezone.utc))
        self.assertIn("boom", out["error"])


class TheGuardIsOffByDefault(unittest.TestCase):

    def test_no_thread_starts_in_a_plain_process(self):
        with mock.patch.dict("os.environ", {}, clear=False):
            import os
            os.environ.pop(display_refresh.ENV_GUARD_INTERVAL, None)
            self.assertIsNone(display_refresh.start_background_guard())
        self.assertFalse(display_refresh.guard_status()["enabled"])


if __name__ == "__main__":
    unittest.main()
