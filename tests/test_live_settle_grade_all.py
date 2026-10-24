"""The live grading loop reads European soccer (UEFA cups) from ESPN; every other sport it cannot read is COUNTED.

WHY (2026-10-24). The loop settled only the NBA, NFL, MLB, NHL, college, tennis and MMA families. Member tickets in
European soccer, EuroLeague, other hockey and cricket sat open for hours with ``awaiting_final`` at 0, so the status and
the watchdog both said nothing was wrong. Now: the UEFA cups are fetched and settled through the existing settle function
(one scoreboard request per league-day, the same match rules), every other unreadable open ticket is counted as
``unsupported`` on /hounds/live/status, and the watchdog alerts on it four hours after its start.

The grading rules are not touched by anything here, so these tests only pin what the loop asks, what it matches and what
it counts. Saved sample: tests/fixtures/live_grade_all/espn_soccer_uel_2026-10-22.json (a Europa League draw, and a reserve
side that shares a name with the senior club).
"""
from __future__ import annotations

import json
import unittest
from datetime import date
from pathlib import Path

from src.hounds import live_scores as ls
from src.hounds import live_settle as lv
from src.ops import watchdog as W
from tests.test_live_settle_loop import Fake, LiveCase, user_bet, utc

FIXTURE = Path(__file__).parent / "fixtures" / "live_grade_all" / "espn_soccer_uel_2026-10-22.json"
UEL_START = "2026-10-22T19:00:00Z"
UEL_URL = ls.scoreboard_url("uel", date(2026, 10, 22))
OBSERVED = "2026-10-23T00:30:00Z"


def saved_board() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def soccer_bet(n: int, *, event: str, home: str, away: str, league: str = "soccer_uefa_europa_league",
               sport: str = "SOCCER", start: str = UEL_START, price: int = 150) -> dict:
    return user_bet(n, event=event, sport=sport, home=home, away=away, start=start, slate="2026-10-22",
                    league=league, price=price, market="moneyline", side="home")


class SavedSample(unittest.TestCase):
    def test_a_europa_league_draw_is_a_final_at_the_level_score_from_the_saved_board(self):
        want = [{"key": "brugge", "home_team": "Club Brugge KV", "away_team": "AZ Alkmaar", "start": utc(UEL_START)}]
        got = ls.espn_answers(saved_board(), "uel", want, OBSERVED)
        self.assertEqual((got["brugge"]["state"], got["brugge"]["home_score"], got["brugge"]["away_score"]),
                         ("final", 1.0, 1.0))

    def test_the_reserve_side_is_never_graded_as_the_senior_club(self):
        # "Real Madrid" is not "Real Madrid Castilla". The saved board holds only the reserves' 3-0, so the senior club's
        # ticket must find no answer rather than take the reserves' score.
        want = [{"key": "rm", "home_team": "Real Madrid", "away_team": "Getafe", "start": utc(UEL_START)}]
        self.assertEqual(ls.espn_answers(saved_board(), "laliga", want, OBSERVED), {})

    def test_a_two_event_match_on_one_pair_is_ambiguous_and_is_not_answered(self):
        board = saved_board()
        twin = json.loads(json.dumps(board["events"][0]))
        twin["id"] = "700199"
        board["events"].append(twin)
        want = [{"key": "brugge", "home_team": "Club Brugge KV", "away_team": "AZ Alkmaar", "start": utc(UEL_START)}]
        self.assertEqual(ls.espn_answers(board, "uel", want, OBSERVED), {})

    def test_names_fold_accents_club_suffixes_and_jk(self):
        self.assertTrue(ls.teams_match("Bayern München", "Bayern Munchen FC"))
        self.assertTrue(ls.teams_match("Tammeka J.K.", "JK Tammeka"))
        self.assertTrue(ls.teams_match("Paris Saint-Germain", "Paris Saint Germain SC"))
        self.assertFalse(ls.teams_match("Real Madrid", "Real Madrid Castilla"))
        self.assertFalse(ls.teams_match("Real Madrid", "Real Madrid II"))


class TheLoopSettlesTheUefaCups(LiveCase):
    def test_a_europa_league_draw_grades_through_the_existing_settle_from_one_league_day_request(self):
        self.write(soccer_bet(1, event="evt-brugge", home="Club Brugge KV", away="AZ Alkmaar"))
        feed = Fake({UEL_URL: saved_board()})
        report = self.run_pass(utc("2026-10-22T21:30:00Z"), feed)
        self.assertEqual(feed.urls, [UEL_URL], "one scoreboard request for the league-day, nothing else")
        self.assertEqual(report["graded"], 1)
        (row,) = self.graded()
        self.assertEqual(row["bet_id"], "bet1")
        self.assertNotEqual(row["result"], "WIN", "a home moneyline on a 1-1 draw is not a win")

    def test_a_soccer_ticket_with_no_mapped_league_is_unsupported_and_never_fetched(self):
        self.write(soccer_bet(2, event="evt-porto", home="Porto", away="Benfica", league="soccer_portugal_primeira_liga"))
        feed = Fake({})
        now = utc("2026-10-22T21:30:00Z")
        self.run_pass(now, feed)
        self.assertEqual(feed.urls, [])
        self.assertEqual(lv.status(now=now, conn=self.conn, paths=self.paths)["unsupported"], 1)


class UnsupportedIsCountedNotHidden(LiveCase):
    def test_a_euroleague_final_is_not_fetched_or_graded_by_the_loop_and_is_counted(self):
        self.write(soccer_bet(3, event="evt-euro", home="Real Madrid", away="Barcelona", sport="BASKETBALL",
                              league="basketball_euroleague"))
        feed = Fake({})
        now = utc("2026-10-22T23:00:00Z")
        report = self.run_pass(now, feed)
        self.assertEqual((report["graded"], feed.urls), (0, []))
        self.assertEqual(lv.status(now=now, conn=self.conn, paths=self.paths)["unsupported"], 1)

    def test_a_cricket_no_result_stays_on_the_old_path_is_counted_and_is_overdue_at_four_hours(self):
        # A cricket match the loop has no feed for: no request, no grade, one open ticket counted, and the overdue
        # list (which feeds the watchdog) holds it once four hours have passed.
        self.write(user_bet(4, event="evt-cricket", sport="CRICKET", home="Sydney Sixers", away="Perth Scorchers",
                            league="cricket_big_bash", start="2026-10-22T08:00:00Z", slate="2026-10-22"))
        feed = Fake({})
        later = utc("2026-10-22T13:00:00Z")
        self.assertEqual(self.run_pass(later, feed)["graded"], 0)
        self.assertEqual(feed.urls, [])
        self.assertEqual(lv.status(now=later, conn=self.conn, paths=self.paths)["unsupported"], 1)
        over = lv.overdue_tickets(later, paths=self.paths, conn=self.conn)
        self.assertEqual([(o["sport"], o["tickets"]) for o in over], [("CRICKET", 1)])

    def test_the_watchdog_alerts_on_an_unsupported_ticket_past_four_hours(self):
        self.write(user_bet(5, event="evt-euro2", sport="BASKETBALL", home="Olympiacos", away="Panathinaikos",
                            league="basketball_euroleague", start="2026-10-22T17:00:00Z", slate="2026-10-22"))
        now = utc("2026-10-22T22:00:00Z")
        dog = W.Watchdog(env={}, grading=lambda moment: lv.overdue_tickets(moment, paths=self.paths, conn=self.conn))
        outcome = dog.check_grading(now)
        self.assertEqual(outcome.state, W.ALERT)
        self.assertIn("Panathinaikos @ Olympiacos", outcome.findings[0].what)

    def test_within_four_hours_the_unsupported_ticket_is_quiet_but_still_counted(self):
        self.write(user_bet(6, event="evt-euro3", sport="BASKETBALL", home="Olympiacos", away="Panathinaikos",
                            league="basketball_euroleague", start="2026-10-22T17:00:00Z", slate="2026-10-22"))
        now = utc("2026-10-22T20:30:00Z")
        self.assertEqual(lv.overdue_tickets(now, paths=self.paths, conn=self.conn), [])
        self.assertEqual(lv.status(now=now, conn=self.conn, paths=self.paths)["unsupported"], 1)
