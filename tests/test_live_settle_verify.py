"""Verification of the live settlement loop (2026-10-22): the wrong grade found, the lock renewal, and tennis and MMA.

Network faked; every store a temp file. The fixtures are the builder's own (tests/test_live_settle_loop.py) and the free
readers' (tests/test_allsports_free_results.py), so these tests exercise the loop through the same shapes.
"""
from __future__ import annotations

import json
import unittest
from datetime import date, datetime, timedelta, timezone

from src.hounds import live_scores as ls
from src.hounds import live_settle as lv
from src.hounds import user_settle
from src.ledger.chain import HashChainLedger
from src.pipeline import ufc_autograde, ufc_results
from src.providers import espn_tennis_results as tennis_src
from tests.hounds_web_runner import HAS_NODE, run_js
from tests.test_allsports_free_results import espn_doc
from tests.test_live_settle_loop import EVENT, Fake, LiveCase, espn_event, user_bet, utc

NBA = lambda day: ls.scoreboard_url("nba", day)   # noqa: E731


class TheNeighbouringDaysFinalIsNotThisGamesFinal(LiveCase):
    """A playoff series: the same two teams, the same home side, 24 hours apart. The loop reads the day before when a game
    is not on its own day's scoreboard, and used to accept that day's FINAL (the window was 30 hours)."""

    def ticket(self):
        return user_bet(1, start="2026-10-22T23:30:00Z", slate="2026-10-22")

    def test_game_two_not_listed_on_its_day_is_not_graded_from_game_one(self):
        self.write(self.ticket())
        feed = Fake({NBA(date(2026, 10, 21)): self.board(
            espn_event("g1", "Brooklyn Nets", "Charlotte Hornets", date="2026-10-21T23:30Z"))})
        report = self.run_pass(utc("2026-10-23T03:00:00Z"), feed)
        self.assertEqual((report["graded"], self.graded()), (0, []))
        self.assertNotEqual(lv.game_states([EVENT], now=utc("2026-10-23T03:00:00Z"), conn=self.conn)[EVENT]["state"],
                            "final")

    def test_game_two_moved_to_the_next_day_is_not_graded_from_game_one(self):
        self.write(self.ticket())
        feed = Fake({
            NBA(date(2026, 10, 21)): self.board(espn_event("g1", "Brooklyn Nets", "Charlotte Hornets",
                                                           date="2026-10-21T23:30Z")),
            NBA(date(2026, 10, 23)): self.board(espn_event("g2", "Brooklyn Nets", "Charlotte Hornets", state="pre",
                                                           name="STATUS_SCHEDULED", completed=False, hs=0, as_=0,
                                                           date="2026-10-23T23:30Z"))})
        self.run_pass(utc("2026-10-23T03:00:00Z"), feed)
        self.assertEqual(self.graded(), [])

    def test_the_games_own_listing_still_grades_even_when_the_vendors_start_is_an_hour_off(self):
        self.write(self.ticket())
        feed = Fake({NBA(date(2026, 10, 22)): self.board(
            espn_event("g2", "Brooklyn Nets", "Charlotte Hornets", date="2026-10-23T00:20Z", hs=101, as_=99))})
        self.run_pass(utc("2026-10-23T03:30:00Z"), feed)
        g = self.graded()
        self.assertEqual([(r["result"], r["home_score"], r["away_score"]) for r in g], [("WIN", 101.0, 99.0)])

    def test_the_window_is_under_a_day(self):
        self.assertLess(ls.MATCH_WINDOW, timedelta(hours=24))


class AnExpiredLockIsNotSettledUnder(LiveCase):
    def test_a_pass_that_lost_the_lock_while_fetching_does_not_settle(self):
        self.write(user_bet(1))
        url = NBA(date(2026, 10, 21))
        stolen = []

        def feed(u):
            # the fetch phase outlives the lock: another machine's pass takes it meanwhile
            self.conn.execute("DELETE FROM live_lock")
            stolen.append(lv.acquire_lock(self.conn, "machine-b", utc("2026-10-22T02:05:00Z")))
            return self.board(espn_event("401", "Brooklyn Nets", "Charlotte Hornets"))

        report = self.run_pass(utc("2026-10-22T02:05:00Z"), feed, holder="machine-a")
        self.assertEqual(stolen, [True])
        self.assertIn("took the lock", report["skipped"])
        self.assertEqual((report["graded"], self.graded()), (0, []))
        del url

    def test_a_pass_that_still_holds_the_lock_renews_it_and_settles(self):
        self.write(user_bet(1))
        feed = Fake({NBA(date(2026, 10, 21)): self.board(espn_event("401", "Brooklyn Nets", "Charlotte Hornets"))})
        report = self.run_pass(utc("2026-10-22T02:05:00Z"), feed, holder="machine-a")
        self.assertEqual(report["graded"], 1)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM live_lock").fetchone()[0], 0, "released at the end")


# ---------------------------------------------------------------------------
# tennis and MMA
# ---------------------------------------------------------------------------

TENNIS_START = "2026-10-21T05:00:00Z"
TENNIS_NOW = utc("2026-10-21T09:30:00Z")
EALA, SHNAIDER = "Alexandra Eala", "Diana Shnaider"


def tennis_bet(n=1, *, side="home", event="evt-eala", home=EALA, away=SHNAIDER, start=TENNIS_START):
    return user_bet(n, event=event, sport="TENNIS", league="tennis_wta_ningbo_open", away=away, home=home, start=start,
                    slate="2026-10-21", side=side, price=138 if side == "home" else -169)


class TennisFeed:
    """ESPN tennis scoreboards by tour; counts every URL asked."""

    def __init__(self, wta=None, atp=None):
        self.docs = {"wta": wta or {"events": []}, "atp": atp or {"events": []}}
        self.urls = []

    def __call__(self, url):
        self.urls.append(url)
        return self.docs[url.split("/tennis/")[1].split("/")[0]]


class TennisFromTheFreeReader(LiveCase):
    def match(self, status="STATUS_FINAL", winner="a", sets=((6, 3), (6, 4)), players=(EALA, SHNAIDER)):
        return espn_doc(("m1", "2026-10-21T05:00Z", status, players, winner, sets))

    def test_a_finished_match_grades_a_bet_on_the_winner_and_the_other_side_loses(self):
        self.write(tennis_bet(1, side="home"), tennis_bet(2, side="away"))
        feed = TennisFeed(wta=self.match())
        report = self.run_pass(TENNIS_NOW, feed)
        self.assertEqual(report["graded"], 2)
        self.assertEqual({r["bet_id"]: r["result"] for r in self.graded()}, {"bet1": "WIN", "bet2": "LOSS"})
        self.assertEqual(len(feed.urls), 4, "wta and atp for the start day and the next, once for both tickets")
        self.assertLessEqual(report["fetch"]["requests"], 4)

    def test_the_players_listed_the_other_way_round_still_grade_by_name_not_by_position(self):
        self.write(tennis_bet(1, side="home"))
        feed = TennisFeed(wta=self.match(players=(SHNAIDER, EALA), winner="a"))      # ESPN's first player won: Shnaider
        self.run_pass(TENNIS_NOW, feed)
        self.assertEqual([r["result"] for r in self.graded()], ["LOSS"])

    def test_a_retirement_before_a_set_is_completed_and_a_walkover_are_named_voids(self):
        self.write(tennis_bet(1))
        feed = TennisFeed(wta=self.match(status="STATUS_RETIRED", sets=((3, 2),)))
        self.run_pass(TENNIS_NOW, feed)
        g = self.graded()[0]
        self.assertEqual(g["result"], "VOID")
        self.assertIn("retired before a set was completed", g["reason"])

    def test_a_walkover_is_void(self):
        self.write(tennis_bet(1))
        self.run_pass(TENNIS_NOW, TennisFeed(wta=self.match(status="STATUS_WALKOVER", winner="a", sets=())))
        g = self.graded()[0]
        self.assertEqual(g["result"], "VOID")
        self.assertIn("walkover", g["reason"])

    def test_a_retirement_after_a_completed_set_goes_to_the_player_who_advanced(self):
        self.write(tennis_bet(1, side="home"))
        self.run_pass(TENNIS_NOW, TennisFeed(wta=self.match(status="STATUS_RETIRED", sets=((6, 3), (2, 1)))))
        self.assertEqual([r["result"] for r in self.graded()], ["WIN"])

    def test_a_match_in_progress_is_not_graded_and_is_not_asked_again_for_ten_minutes(self):
        self.write(tennis_bet(1))
        feed = TennisFeed(wta=self.match(status="STATUS_IN_PROGRESS", winner=None, sets=((6, 3), (2, 1))))
        self.run_pass(TENNIS_NOW, feed)
        asked = len(feed.urls)
        self.assertEqual(self.graded(), [])
        self.run_pass(TENNIS_NOW + timedelta(minutes=5), feed)
        self.assertEqual(len(feed.urls), asked, "inside the recheck wait: no new request")
        feed.docs["wta"] = self.match()
        report = self.run_pass(TENNIS_NOW + timedelta(minutes=11), feed)
        self.assertEqual(report["graded"], 1)

    def test_names_that_do_not_agree_are_never_graded(self):
        self.write(tennis_bet(1, home="Alexandra Eala", away="Diana Shnaider"))
        feed = TennisFeed(wta=self.match(players=("Emma Navarro", "Diana Shnaider")))
        self.run_pass(TENNIS_NOW, feed)
        self.assertEqual(self.graded(), [])

    def test_a_feed_that_is_down_is_recorded_and_retried_not_graded(self):
        self.write(tennis_bet(1))

        def down(url):
            raise RuntimeError("503 from espn")

        with self.assertLogs("linehound.hounds.live_settle", level="WARNING"):
            report = self.run_pass(TENNIS_NOW, down)
        self.assertEqual((report["graded"], self.graded()), (0, []))
        row = self.conn.execute("SELECT fails, next_try_utc FROM live_games").fetchone()
        self.assertEqual(row["fails"], 1)
        self.assertIsNotNone(row["next_try_utc"])

    def test_the_graded_ticket_is_not_asked_about_again_and_the_ledger_stays_append_only(self):
        self.write(tennis_bet(1))
        feed = TennisFeed(wta=self.match())
        self.run_pass(TENNIS_NOW, feed)
        before = HashChainLedger(self.ledger).read()
        asked = len(feed.urls)
        self.run_pass(TENNIS_NOW + timedelta(minutes=5), feed)
        after = HashChainLedger(self.ledger).read()
        self.assertEqual(len(feed.urls), asked)
        self.assertEqual(before, after[:len(before)])
        self.assertEqual(len(after), len(before))
        self.assertTrue(HashChainLedger(self.ledger).verify().ok)

    def test_the_page_never_sees_the_one_zero_match_indicator_as_a_score(self):
        self.write(tennis_bet(1))
        feed = TennisFeed(wta=self.match())
        self.run_pass(TENNIS_NOW, feed)
        # graded already; look at the cache row a moment earlier by re-opening the ticket is not possible, so read the row
        row = self.conn.execute("SELECT state, home_score, away_score, detail FROM live_games").fetchone()
        self.assertEqual((row["state"], row["home_score"], row["away_score"], row["detail"]), ("final", None, None, "Final"))

    def test_the_overdue_alert_waits_longer_for_a_tennis_match_than_for_a_ball_game(self):
        self.write(tennis_bet(1))
        self.assertEqual(lv.overdue_tickets(utc("2026-10-21T09:30:00Z"), paths=self.paths, conn=self.conn), [],
                         "4.5 hours after a listed start, an order-of-play match may not have begun")
        late = lv.overdue_tickets(utc("2026-10-21T13:30:00Z"), paths=self.paths, conn=self.conn)
        self.assertEqual([o["sport"] for o in late], ["TENNIS"])


class FakeMma:
    """Stands in for EspnMmaResultsProvider: ``decide`` answers by the ticket's event id."""

    def __init__(self, decisions):
        self.decisions, self.calls = decisions, []

    def fetch_for_bouts(self, date_iso, bouts, *, now):
        self.calls.append((date_iso, [b.game_id for b in bouts]))
        return []

    def decide(self, bout, fights):
        got = self.decisions.get(bout.game_id)
        if got is not None:
            return got(bout)
        return ufc_autograde.Decision(bout, "skip", "no bout on the card by those names")


def mma_bet(n=1, *, event="evt-mma", side="home", home="Fighter Alpha", away="Fighter Bravo"):
    return user_bet(n, event=event, sport="MMA", league="mma_mixed_martial_arts", away=away, home=home,
                    start="2026-10-24T02:00:00Z", slate="2026-10-23", side=side, price=-150 if side == "home" else 130)


def record(outcome, winner=None, reason="final"):
    return lambda bout: ufc_autograde.Decision(bout, ufc_autograde.ACTION_RECORD, reason, outcome=outcome, winner=winner,
                                               provenance={"basis": "espn status", "espn_bout_id": "b1"})


class MmaFromTheFreeReader(LiveCase):
    NOW = utc("2026-10-24T06:00:00Z")

    def test_a_decided_bout_grades_both_sides(self):
        self.write(mma_bet(1, side="home"), mma_bet(2, side="away"))
        provider = FakeMma({"evt-mma": record(ufc_results.OUTCOME_WIN, "Fighter Alpha")})
        report = self.run_pass(self.NOW, Fake({}), mma_provider=provider)
        self.assertEqual(report["graded"], 2)
        self.assertEqual({r["bet_id"]: r["result"] for r in self.graded()}, {"bet1": "WIN", "bet2": "LOSS"})
        self.assertEqual(len(provider.calls), 1)

    def test_a_draw_or_no_contest_is_a_void_with_the_reason_named(self):
        self.write(mma_bet(1))
        self.run_pass(self.NOW, Fake({}), mma_provider=FakeMma({"evt-mma": record(ufc_results.OUTCOME_DRAW, None)}))
        g = self.graded()[0]
        self.assertEqual(g["result"], "VOID")
        self.assertIn("draw", g["reason"])

    def test_a_bout_not_found_or_not_final_is_not_graded_and_is_not_asked_again_at_once(self):
        self.write(mma_bet(1))
        provider = FakeMma({})
        self.run_pass(self.NOW, Fake({}), mma_provider=provider)
        self.assertEqual(self.graded(), [])
        self.run_pass(self.NOW + timedelta(minutes=5), Fake({}), mma_provider=provider)
        self.assertEqual(len(provider.calls), 1)
        provider.decisions["evt-mma"] = record(ufc_results.OUTCOME_WIN, "Fighter Bravo")
        report = self.run_pass(self.NOW + timedelta(minutes=11), Fake({}), mma_provider=provider)
        self.assertEqual(report["graded"], 1)
        self.assertEqual([r["result"] for r in self.graded()], ["LOSS"])

    def test_an_inferred_replacement_is_held_never_graded_by_this_loop(self):
        self.write(mma_bet(1))

        def replaced(bout):
            return ufc_autograde.Decision(bout, ufc_autograde.ACTION_RECORD, "Alpha fought someone else",
                                          outcome=ufc_results.OUTCOME_CANCELLED,
                                          provenance={"basis": "fighter replaced"})

        self.run_pass(self.NOW, Fake({}), mma_provider=FakeMma({"evt-mma": replaced}))
        self.assertEqual(self.graded(), [])

    def test_a_provider_error_is_recorded_with_a_backoff(self):
        self.write(mma_bet(1))

        class Down(FakeMma):
            def fetch_for_bouts(self, date_iso, bouts, *, now):
                raise ufc_autograde.ProviderError("ESPN served a browser check")

        with self.assertLogs("linehound.hounds.live_settle", level="WARNING"):
            self.run_pass(self.NOW, Fake({}), mma_provider=Down({}))
        self.assertEqual(self.graded(), [])
        self.assertEqual(self.conn.execute("SELECT fails FROM live_games").fetchone()["fails"], 1)


class SupportTable(unittest.TestCase):
    def test_tennis_and_mma_are_now_supported_and_the_rest_are_not(self):
        for family in ("TENNIS", "MMA", "tennis"):
            self.assertTrue(ls.supported(family))
        for family in ("CRICKET", "RUGBY", "AFL"):
            self.assertFalse(ls.supported(family))

    def test_an_old_cache_file_gains_the_payload_column(self):
        import os
        import sqlite3
        import tempfile
        path = os.path.join(tempfile.mkdtemp(), "old.db")
        old = sqlite3.connect(path)
        old.execute("CREATE TABLE live_games (game_key TEXT PRIMARY KEY, sport TEXT NOT NULL, state TEXT NOT NULL)")
        old.commit()
        old.close()
        conn = lv.connect(path)
        self.assertIn("payload", {r["name"] for r in conn.execute("PRAGMA table_info(live_games)")})
        conn.close()


@unittest.skipUnless(HAS_NODE, "node not installed")
class TheTicketLineSaysOnlyWhatIsTrue(unittest.TestCase):
    def js(self, body):
        return run_js('import * as L from "./ticket-live.js";\n' + body)

    def test_a_game_that_started_hours_ago_is_never_awaiting_its_start(self):
        out = self.js('const info={state:"upcoming",start_utc:"2026-10-24T19:00:00Z"};'
                      'console.log(JSON.stringify([L.liveView(info,null,Date.parse("2026-10-24T19:05:00Z")),'
                      'L.liveView(info,null,Date.parse("2026-10-24T22:00:00Z"))]));')
        self.assertEqual(out[0]["text"], "Awaiting the start", "a few minutes past the start is a pregame delay")
        self.assertIsNone(out[1], "three hours past it the feed simply has no answer: a plain PENDING chip")

    def test_last_graded_is_the_viewers_clock_and_names_the_day_when_it_was_not_today(self):
        out = self.js('process.env.TZ="America/Los_Angeles";'
                      'const now=Date.parse("2026-10-24T20:00:00Z");'
                      'console.log(JSON.stringify([L.clockText("2026-10-24T19:14:00Z",now),'
                      'L.clockText("2026-10-22T03:30:00Z",now),L.clockText("",now),L.clockText("garbage",now)]));')
        self.assertEqual(out, ["12:14", "Oct 21, 20:30", "", ""])


if __name__ == "__main__":
    unittest.main()
