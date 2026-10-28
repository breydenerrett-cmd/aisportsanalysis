"""The Live board's score, status, period and clock come from a fresh ESPN read, and never from an old stored score.

Owner complaint 2026-10-27: the board said Columbus 3, Philadelphia 0 "LIVE" under "Board as of 5:22 PM PT, refreshes every minute"
while ESPN had it 3-1 in the 2nd. The score was a The Odds API /scores row, hours old. These tests inject the clock and the scoreboard
fixtures (no network) and pin: status mapping (pre / in / final, OT and shootout), the staleness guard, that a fresh feed overrides
the stale stored score (the test that fails against the pre-change code), postponed games leaving the live list, and the loop wiring.
"""
from __future__ import annotations

import threading
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from src.sports import allsports_view as V
from src.sports import live_feed as F
from tests.test_allsports_view import mrow

NOW = datetime(2026, 10, 28, 0, 22, 0, tzinfo=timezone.utc)      # 5:22 PM PDT on the 27th, the owner's screenshot
START = NOW - timedelta(hours=1, minutes=12)                       # 4:10 PM PT
HOME, AWAY = "Columbus Blue Jackets", "Philadelphia Flyers"
REPO = Path(__file__).resolve().parent.parent


def event(state, completed, name, hs, as_, *, period=2, clock="6:42", short="6:42 - 2nd", start=START, home=HOME, away=AWAY, eid="401"):
    stamp = start.strftime("%Y-%m-%dT%H:%MZ")
    return {"id": eid, "date": stamp, "status": {"type": {}},
            "competitions": [{"date": stamp,
                              "status": {"period": period, "displayClock": clock,
                                         "type": {"state": state, "completed": completed, "name": name, "shortDetail": short}},
                              "competitors": [
                                  {"homeAway": "home", "id": "1", "score": str(hs), "winner": False,
                                   "team": {"id": "1", "displayName": home, "abbreviation": "CBJ"}},
                                  {"homeAway": "away", "id": "2", "score": str(as_), "winner": False,
                                   "team": {"id": "2", "displayName": away, "abbreviation": "PHI"}}]}]}


def payload(*events):
    return {"events": list(events)}


def rows(start=START, observed=None):
    return mrow("nhl_1", "nhl", start, observed or NOW - timedelta(minutes=2), home=HOME, away=AWAY, prices=((-2000, 1200),),
                league="icehockey_nhl")


STALE_STORE = {"nhl_1": {"home_score": 3, "away_score": 0, "completed": False, "observed_utc": "2026-10-27T23:50:00Z"}}


class TheBoardUsesTheFreshFeed(unittest.TestCase):
    def setUp(self):
        F.clear()
        V.clear_cache()
        self.addCleanup(F.clear)

    def board(self, ev, *, fetched=NOW - timedelta(seconds=20), r=None):
        F.store("nhl", [payload(ev)], fetched)
        return V.sports_now(NOW, rows=r if r is not None else rows(), scores_index=STALE_STORE)

    def live(self, body):
        fam = next((f for f in body["families"] if f["code"] == "NHL"), None)
        return fam["live"] if fam else []

    def test_a_fresh_feed_replaces_the_stale_stored_score_and_adds_period_and_clock(self):
        [game] = self.live(self.board(event("in", False, "STATUS_IN_PROGRESS", 3, 1)))
        self.assertEqual((game["score"]["home"], game["score"]["away"]), (3, 1))          # the stored 3-0 is gone
        self.assertEqual((game["score"]["period"], game["score"]["clock"]), (2, "6:42"))
        self.assertEqual(game["score"]["detail"], "6:42 - 2nd")
        self.assertFalse(game["score"]["completed"])
        self.assertEqual(game["score"]["as_of"], "2026-10-28T00:21:40Z")

    def test_the_board_says_when_the_scores_were_read_and_when_the_prices_were(self):
        body = self.board(event("in", False, "STATUS_IN_PROGRESS", 3, 1))
        self.assertEqual(body["scores"]["updated_utc"], "2026-10-28T00:21:40Z")
        self.assertEqual(body["scores"]["age_seconds"], 20)
        self.assertFalse(body["scores"]["delayed"])
        self.assertEqual(body["prices_observed_utc"], "2026-10-28T00:20:00Z")

    def test_a_feed_older_than_the_guard_shows_score_delayed_not_the_old_numbers(self):
        old = NOW - timedelta(seconds=F.STALE_AFTER_SECONDS + 30)
        body = self.board(event("in", False, "STATUS_IN_PROGRESS", 3, 1), fetched=old)
        [game] = self.live(body)
        self.assertTrue(game["score"]["delayed"])
        self.assertIsNone(game["score"]["home"])
        self.assertEqual(game["score"]["detail"], "Score delayed")
        self.assertTrue(body["scores"]["delayed"])
        self.assertIsNone(body["scores"]["updated_utc"])

    def test_a_feed_just_inside_the_guard_is_still_shown(self):
        body = self.board(event("in", False, "STATUS_IN_PROGRESS", 3, 1), fetched=NOW - timedelta(seconds=F.STALE_AFTER_SECONDS - 1))
        self.assertEqual(self.live(body)[0]["score"]["home"], 3)

    def test_no_feed_read_at_all_is_delayed_too_never_the_stored_score(self):
        body = V.sports_now(NOW, rows=rows(), scores_index=STALE_STORE)
        score = self.live(body)[0]["score"]
        self.assertTrue(score["delayed"])
        self.assertIsNone(score["away"])

    def test_a_game_with_no_unambiguous_match_gets_no_score_rather_than_the_stored_one(self):
        body = self.board(event("in", False, "STATUS_IN_PROGRESS", 3, 1, home="Somebody Else"))
        self.assertNotIn("score", self.live(body)[0])

    def test_final_overtime_and_shootout_finals_are_final_cards(self):
        for short, period in (("Final", 3), ("Final/OT", 4), ("Final/SO", 5)):
            with self.subTest(short=short):
                F.clear()
                [game] = self.live(self.board(event("post", True, "STATUS_FINAL", 4, 3, short=short, period=period)))
                self.assertTrue(game["score"]["completed"])
                self.assertEqual(game["score"]["detail"], short)
                self.assertEqual(game["score"]["period"], period)

    def test_a_scheduled_game_priced_after_its_listed_start_is_not_called_live(self):
        body = self.board(event("pre", False, "STATUS_SCHEDULED", 0, 0, period=0, clock="0:00", short="10/27 - 7:30 PM EDT"))
        self.assertEqual(self.live(body), [])

    def test_a_game_the_scoreboard_has_live_is_live_even_when_its_last_price_is_old(self):
        old_price = rows(observed=NOW - timedelta(hours=3))            # taken before the start: the odds file alone would say not live
        [game] = self.live(self.board(event("in", False, "STATUS_IN_PROGRESS", 1, 0, period=1, clock="9:00", short="9:00 - 1st"), r=old_price))
        self.assertEqual(game["observed_utc"], "2026-10-27T21:22:00Z")                  # the price age stays honest, per game

    def test_postponed_leaves_the_live_list(self):
        body = self.board(event("post", False, "STATUS_POSTPONED", 0, 0, period=0, clock="0:00", short="Postponed"))
        self.assertEqual(self.live(body), [])


class TheRefresh(unittest.TestCase):
    def setUp(self):
        F.clear()
        self.addCleanup(F.clear)

    def ev(self, family="NHL", league="icehockey_nhl", start=START, in_play=True):
        return {"family": family, "league": league, "_start": start, "in_play": in_play, "event_id": "x", "home": HOME, "away": AWAY}

    def test_only_leagues_with_a_game_in_play_or_about_to_start_are_read(self):
        need = F.leagues_needed([self.ev(), self.ev("NBA", "basketball_nba", NOW + timedelta(hours=5), False),
                                 self.ev("NFL", "americanfootball_nfl", NOW + timedelta(minutes=10), False),
                                 self.ev("TENNIS", "tennis_atp", START, True)], NOW)
        self.assertEqual(need, ["nfl", "nhl"])                          # NBA is hours away, tennis is not covered

    def test_a_pass_reads_two_scoreboard_days_per_league_and_stores_them(self):
        urls = []

        def fetch(url):
            urls.append(url)
            return payload()
        report = F.refresh(["nhl"], NOW, fetch_json=fetch)
        self.assertEqual(report["ok"], ["nhl"])
        self.assertEqual(len(urls), 2)
        self.assertIn("dates=20261028", urls[0])
        self.assertIn("dates=20261027", urls[1])
        self.assertIsNotNone(F.fresh_entry("nhl", NOW))

    def test_a_failed_read_keeps_the_old_entry_which_then_ages_out(self):
        F.store("nhl", [payload()], NOW - timedelta(seconds=100))

        def boom(url):
            raise OSError("down")
        report = F.refresh(["nhl"], NOW, fetch_json=boom)
        self.assertEqual(report["failed"], ["nhl"])
        self.assertIsNotNone(F.fresh_entry("nhl", NOW))
        self.assertIsNone(F.fresh_entry("nhl", NOW + timedelta(seconds=200)))

    def test_the_request_cap_bounds_a_pass(self):
        calls = []
        F.refresh(["nhl", "nba", "nfl", "epl"], NOW, fetch_json=lambda u: calls.append(u) or payload(), max_requests=3)
        self.assertEqual(len(calls), 3)

    def test_mlb_is_read_from_the_espn_baseball_scoreboard(self):
        urls = []
        F.refresh(["mlb"], NOW, fetch_json=lambda u: urls.append(u) or payload())
        self.assertIn("baseball/mlb/scoreboard", urls[0])
        self.assertEqual(F.league_for("MLB"), "mlb")


class TheLoop(unittest.TestCase):
    def test_it_does_not_start_when_switched_off_or_under_pytest(self):
        self.assertIsNone(F.start_loop(lambda: [], env={"LIVE_FEED": "off"}))
        with mock.patch.dict("os.environ", {"PYTEST_CURRENT_TEST": "x"}):
            self.assertIsNone(F.start_loop(lambda: []))

    def test_the_cadence_is_inside_the_owners_sixty_seconds_and_tolerates_missed_passes(self):
        self.assertLessEqual(F.INTERVAL_SECONDS, 60)
        self.assertGreaterEqual(F.STALE_AFTER_SECONDS, 3 * F.INTERVAL_SECONDS)

    def test_a_pass_that_raises_does_not_kill_the_loop(self):
        stop, ran = threading.Event(), []

        def provider():
            ran.append(1)
            if len(ran) == 1:
                raise RuntimeError("boom")
            stop.set()
            return []
        thread = F.start_loop(provider, interval_s=0.01, stop_event=stop, env={})
        thread.join(5)
        self.assertGreaterEqual(len(ran), 2)

    def test_app_wires_the_loop_at_startup(self):
        text = (REPO / "api" / "app.py").read_text(encoding="utf-8")
        self.assertIn("live_feed.start_loop(allsports_view.current_events", text)


if __name__ == "__main__":
    unittest.main()
