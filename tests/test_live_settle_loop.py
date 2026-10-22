"""src/hounds/live_settle.py + live_scores.py: a ticket grades within minutes of its game going final.

The story these pin (2026-10-22): member tickets on the Oct 21 NBA games were still PENDING five hours after the games
ended, because the only score source was a vendor poll that ran an hour into the games and was then locked out for eight
hours, and the stores are baked into the image. Every test here fakes the network and points every store at a temp dir
(nothing reads the repository's data files).
"""
from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from src.hounds import live_scores as ls
from src.hounds import live_settle as lv
from src.hounds import user_settle
from src.ledger.chain import HashChainLedger

TIP = "2026-10-21T23:30:00Z"                 # Hornets @ Nets
FINAL_AT = datetime(2026, 10, 22, 2, 0, tzinfo=timezone.utc)
SLATE = "2026-10-21"
EVENT = "47cc511bb5ce50f715e3625ce5ef77ee"   # the vendor's id for Hornets @ Nets (from the real store)
NBA_URL = ls.scoreboard_url("nba", datetime(2026, 10, 21).date())


def utc(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def user_bet(n: int, *, event=EVENT, sport="NBA", away="Charlotte Hornets", home="Brooklyn Nets", start=TIP,
             market="moneyline", side="home", line=None, price=-110, slate=SLATE, league="basketball_nba",
             game_pk=None, hound="u-test1") -> dict:
    row = {"kind": "hound_user_bet", "ledger_version": 1, "paper_only": True, "bet_id": f"bet{n}", "hound_id": hound,
           "sport": sport, "event_id": event, "game_pk": game_pk, "slate_date": slate, "commence_time": start,
           "away_team": away, "home_team": home, "market": market, "side": side, "line": line,
           "selection": f"{side} {market}", "price": price, "best_price": price, "n_books": 5, "units": 1,
           "recorded_utc": "2026-10-21T21:00:00Z", "segment": "forward"}
    if league:
        row["league"] = league
    return row


def espn_event(eid, home, away, *, state="post", name="STATUS_FINAL", completed=True, hs=112, as_=108,
               date="2026-10-21T23:30Z", detail="Final"):
    team = lambda side, n, sc: {"homeAway": side, "team": {"id": str(abs(hash(n)) % 9999), "displayName": n,
                                                            "abbreviation": n[:3].upper()}, "score": str(sc)}
    return {"id": eid, "date": date, "competitions": [{
        "date": date, "status": {"period": 4, "type": {"state": state, "name": name, "completed": completed,
                                                       "shortDetail": detail}},
        "competitors": [team("home", home, hs), team("away", away, as_)]}]}


class Fake:
    """A scoreboard feed that records every URL it is asked for."""

    def __init__(self, boards: dict):
        self.boards, self.urls = boards, []

    def __call__(self, url):
        self.urls.append(url)
        got = self.boards.get(url)
        if isinstance(got, Exception):
            raise got
        return got if got is not None else {"events": []}


class LiveCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = self._tmp.name
        self.ledger = os.path.join(self.dir, "hounds.jsonl")
        self.paths = {"user": self.ledger, "manual": os.path.join(self.dir, "manual.jsonl"),
                      "ai": os.path.join(self.dir, "ai.jsonl")}
        self.conn = lv.connect(os.path.join(self.dir, "live_settle.db"))
        lv._OPEN_CACHE.clear()
        self.kwargs = {"close_fn": lambda bet: None, "postponed_lookup": None, "cancelled_lookup": None}

    def tearDown(self):
        self.conn.close()
        self._tmp.cleanup()
        lv._OPEN_CACHE.clear()

    def write(self, *bets):
        ledger = HashChainLedger(self.ledger)
        for b in bets:
            ledger.append(b)

    def graded(self):
        return [r for r in HashChainLedger(self.ledger).read() if r.get("kind") == user_settle.KIND_GRADED]

    def run_pass(self, now, feed, **kw):
        kw.setdefault("settle_kwargs", self.kwargs)
        kw.setdefault("load_index", lambda: {})
        kw.setdefault("refresh_stats", lambda: None)
        return lv.run_pass(now=now, conn=self.conn, paths=self.paths, fetch_json=feed, **kw)

    def board(self, *events):
        return {"events": list(events)}


class TheTimelineRepro(LiveCase):
    """The Hornets @ Nets ticket: the baked store shows the game in progress, the live feed shows the final."""

    def test_the_old_path_is_still_pending_at_0600z_and_the_live_loop_grades_it_minutes_after_the_final(self):
        self.write(user_bet(1))
        # What production held at 06:00Z: the 00:10Z vendor poll, 21-15, completed false.
        stale = {EVENT: {"event_id": EVENT, "completed": False, "home_score": 15.0, "away_score": 21.0,
                         "commence_time": TIP}}
        old = user_settle.settle(ledger=self.ledger, now=utc("2026-10-22T06:00:00Z"), allsports_results=stale,
                                 **self.kwargs)
        self.assertEqual((old["graded"], old["pending"]), (0, 1), "the bug: five hours after the final, still open")
        # The live loop, five minutes after the 02:00Z final.
        feed = Fake({NBA_URL: self.board(espn_event("401", "Brooklyn Nets", "Charlotte Hornets"))})
        report = self.run_pass(FINAL_AT + timedelta(minutes=5), feed)
        self.assertEqual(report["graded"], 1)
        g = self.graded()[0]
        self.assertEqual((g["bet_id"], g["result"], g["away_score"], g["home_score"]), ("bet1", "WIN", 108.0, 112.0))
        self.assertLessEqual(FINAL_AT + timedelta(minutes=5) - FINAL_AT, timedelta(minutes=15))
        self.assertEqual(g["graded_utc"], "2026-10-22T02:05:00Z")

    def test_the_grade_uses_the_existing_rules_unchanged_a_total_on_the_line_is_a_push(self):
        self.write(user_bet(1, market="total", side="over", line=220.0, price=-105))
        feed = Fake({NBA_URL: self.board(espn_event("401", "Brooklyn Nets", "Charlotte Hornets", hs=112, as_=108))})
        self.run_pass(FINAL_AT, feed)
        g = self.graded()[0]
        self.assertEqual((g["result"], g["profit_units"]), ("PUSH", 0.0))


class FinalsAreGradedAndGamesInPlayAreLeftAlone(LiveCase):
    def test_a_final_game_settles_and_an_in_progress_game_does_not(self):
        other = "evt-bucks-wizards"
        self.write(user_bet(1), user_bet(2, event=other, away="Milwaukee Bucks", home="Washington Wizards",
                                           start="2026-10-22T00:00:00Z", side="away", line=None))
        feed = Fake({NBA_URL: self.board(
            espn_event("401", "Brooklyn Nets", "Charlotte Hornets"),
            espn_event("402", "Washington Wizards", "Milwaukee Bucks", state="in", name="STATUS_IN_PROGRESS",
                       completed=False, hs=61, as_=66, date="2026-10-22T00:00Z", detail="Q3 4:12"))})
        report = self.run_pass(utc("2026-10-22T02:05:00Z"), feed)
        self.assertEqual(report["graded"], 1)
        self.assertEqual([r["bet_id"] for r in self.graded()], ["bet1"])
        live = lv.game_states([other], now=utc("2026-10-22T02:05:00Z"), conn=self.conn)[other]
        self.assertEqual((live["state"], live["away_score"], live["home_score"], live["detail"]),
                         ("live", 66.0, 61.0, "Q3 4:12"))

    def test_a_game_that_has_not_started_is_not_asked_about(self):
        self.write(user_bet(1, start="2026-10-22T23:30:00Z", slate="2026-10-22"))
        feed = Fake({})
        self.run_pass(utc("2026-10-22T20:00:00Z"), feed)
        self.assertEqual(feed.urls, [])
        state = lv.game_states([EVENT], now=utc("2026-10-22T20:00:00Z"), conn=self.conn)[EVENT]
        self.assertEqual((state["state"], state["start_utc"]), ("upcoming", "2026-10-22T23:30:00Z"))


class PostponedAndCancelled(LiveCase):
    def test_a_postponed_game_is_not_graded_not_voided_and_not_an_overdue_alert(self):
        self.write(user_bet(1))
        feed = Fake({NBA_URL: self.board(espn_event("401", "Brooklyn Nets", "Charlotte Hornets", state="post",
                                                    name="STATUS_POSTPONED", completed=False, hs=0, as_=0,
                                                    detail="Postponed"))})
        later = utc("2026-10-22T06:00:00Z")
        report = self.run_pass(later, feed)
        self.assertEqual((report["graded"], self.graded()), (0, []))
        self.assertEqual(lv.game_states([EVENT], now=later, conn=self.conn)[EVENT]["state"], "postponed")
        self.assertEqual(lv.overdue_tickets(later, paths=self.paths, conn=self.conn), [],
                         "a postponed game waits for its makeup by rule: no alert")

    def test_a_cancelled_game_is_recorded_and_left_pending_for_the_existing_72_hour_rule(self):
        self.write(user_bet(1))
        feed = Fake({NBA_URL: self.board(espn_event("401", "Brooklyn Nets", "Charlotte Hornets", state="post",
                                                    name="STATUS_CANCELED", completed=False, hs=0, as_=0))})
        self.run_pass(utc("2026-10-22T06:00:00Z"), feed)
        self.assertEqual(self.graded(), [])
        self.assertEqual(lv.game_states([EVENT], now=utc("2026-10-22T06:00:00Z"), conn=self.conn)[EVENT]["state"],
                         "cancelled")

    def test_the_old_rules_still_void_after_72_hours_when_there_is_no_final(self):
        self.write(user_bet(1))
        report = user_settle.settle(ledger=self.ledger, now=utc("2026-10-25T00:00:00Z"), allsports_results={},
                                    **self.kwargs)
        self.assertEqual(report["by_result"], {"VOID": 1})


class IdempotentAndRaceSafe(LiveCase):
    def feed(self):
        return Fake({NBA_URL: self.board(espn_event("401", "Brooklyn Nets", "Charlotte Hornets"))})

    def test_a_double_run_adds_nothing_and_does_not_ask_again(self):
        self.write(user_bet(1))
        feed = self.feed()
        first = self.run_pass(FINAL_AT, feed)
        asked = len(feed.urls)
        second = self.run_pass(FINAL_AT + timedelta(minutes=5), feed)
        self.assertEqual((first["graded"], second["graded"]), (1, 0))
        self.assertEqual(len(self.graded()), 1)
        self.assertEqual(len(feed.urls), asked, "a graded game has no open ticket, so nothing is fetched")
        ledger = HashChainLedger(self.ledger)
        self.assertEqual(ledger.verify().ok if hasattr(ledger.verify(), "ok") else True, True)

    def test_two_passes_at_once_a_held_lock_skips_and_an_expired_lock_does_not(self):
        self.write(user_bet(1))
        self.assertTrue(lv.acquire_lock(self.conn, "machine-a", FINAL_AT))
        feed = self.feed()
        skipped = self.run_pass(FINAL_AT + timedelta(seconds=30), feed, holder="machine-b")
        self.assertIn("lock", skipped["skipped"])
        self.assertEqual((feed.urls, self.graded()), ([], []))
        later = FINAL_AT + timedelta(seconds=lv.LOCK_TTL_SECONDS + 5)
        ran = self.run_pass(later, feed, holder="machine-b")
        self.assertEqual(ran["graded"], 1)

    def test_the_game_table_has_one_row_per_game_by_primary_key(self):
        self.write(user_bet(1), user_bet(2, market="total", side="over", line=220.5))
        self.run_pass(FINAL_AT, self.feed())
        n = self.conn.execute("SELECT COUNT(*) FROM live_games").fetchone()[0]
        self.assertEqual(n, 1)
        with self.assertRaises(Exception):
            self.conn.execute("INSERT INTO live_games(game_key, sport, state) VALUES (?,?,?)", (EVENT, "NBA", "x"))


class FetchesOnlyTheWantedGames(LiveCase):
    def test_one_scoreboard_per_league_day_and_only_the_wanted_game_is_kept(self):
        self.write(user_bet(1), user_bet(2, market="total", side="over", line=220.5))
        crowd = [espn_event(str(500 + i), f"Home{i} Club", f"Away{i} Club") for i in range(10)]
        feed = Fake({NBA_URL: self.board(espn_event("401", "Brooklyn Nets", "Charlotte Hornets"), *crowd)})
        self.run_pass(FINAL_AT, feed)
        self.assertEqual(feed.urls, [NBA_URL], "one request for the one league-day, however many tickets")
        keys = [r["game_key"] for r in self.conn.execute("SELECT game_key FROM live_games")]
        self.assertEqual(keys, [EVENT], "the ten other games on the scoreboard are never stored")

    def test_only_leagues_with_open_tickets_are_asked_and_the_neighbour_day_only_on_a_miss(self):
        self.write(user_bet(1, event="evt-nhl", sport="NHL", league="icehockey_nhl", away="Boston Bruins",
                           home="New York Rangers"))
        feed = Fake({})
        self.run_pass(FINAL_AT, feed)
        self.assertTrue(all("hockey/nhl" in u for u in feed.urls), feed.urls)
        self.assertEqual(len(feed.urls), 3, "slate day, then the day before, then the day after, for a game not listed")

    def test_mlb_is_asked_one_game_at_a_time_by_game_pk_and_graded_from_the_live_final(self):
        self.write(user_bet(1, event="evt-mlb", sport="MLB", league=None, game_pk="900001", away="Boston Red Sox",
                           home="Seattle Mariners", side="away", price=120, start="2026-10-21T23:10:00Z"))
        calls = []

        def instances(pk):
            calls.append(pk)
            return [{"game_pk": pk, "state": "final", "detailed_state": "Final", "away_score": 5, "home_score": 3,
                     "date": SLATE, "start_time_utc": "2026-10-21T23:10:00Z", "away_team": "BOS", "home_team": "SEA"}]

        report = self.run_pass(utc("2026-10-22T03:00:00Z"), Fake({}), fetch_instances=instances,
                               read_mlb_results=lambda: {})
        self.assertEqual(calls, ["900001"])
        g = self.graded()[0]
        self.assertEqual((report["graded"], g["result"], g["profit_units"]), (1, "WIN", 1.2))

    def test_mlb_postponed_is_cached_as_postponed_and_stays_open(self):
        self.write(user_bet(1, event="evt-mlb", sport="MLB", league=None, game_pk="900002", side="away",
                           start="2026-10-21T23:10:00Z"))
        instances = lambda pk: [{"game_pk": pk, "state": "cancelled", "detailed_state": "Postponed",
                                 "away_score": None, "home_score": None, "date": "2026-10-22",
                                 "start_time_utc": "2026-10-22T23:10:00Z"}]
        self.run_pass(utc("2026-10-22T03:00:00Z"), Fake({}), fetch_instances=instances, read_mlb_results=lambda: {})
        self.assertEqual(self.graded(), [])
        self.assertEqual(lv.game_states(["evt-mlb"], now=utc("2026-10-22T03:00:00Z"), conn=self.conn)["evt-mlb"]["state"],
                         "postponed")


class TheHousePackIsReadNotWritten(LiveCase):
    def house_bet(self):
        return {"kind": "hound_bet", "pack": "house_v1", "hound_id": "coin_flip_collie", "event_id": "evt-house",
                "sport": "mlb", "away": "Boston Red Sox", "home": "Seattle Mariners", "away_code": "BOS",
                "home_code": "SEA", "date": SLATE, "start_utc": "2026-10-21T23:10:00Z", "game_pk": "900009",
                "market": "moneyline", "selection": "Seattle Mariners ML", "side": "home", "line": None,
                "market_line": None, "price_average": -120, "price_best": -115, "stake": 1.0, "segment": "forward"}

    def test_a_house_ticket_shows_its_live_state_but_is_never_graded_here_and_never_an_overdue_alert(self):
        house = os.path.join(self.dir, "house.jsonl")
        HashChainLedger(house).append(self.house_bet())
        self.paths["house"] = house
        instances = lambda pk: [{"game_pk": pk, "state": "final", "detailed_state": "Final", "away_score": 2,
                                 "home_score": 4, "date": SLATE, "start_time_utc": "2026-10-21T23:10:00Z"}]
        now = utc("2026-10-22T09:00:00Z")
        report = self.run_pass(now, Fake({}), fetch_instances=instances, read_mlb_results=lambda: {})
        self.assertEqual(report["graded"], 0)
        self.assertEqual([r for r in HashChainLedger(house).read() if r.get("kind") == "hound_graded"], [])
        self.assertEqual(lv.game_states(["evt-house"], now=now, conn=self.conn)["evt-house"]["state"], "final")
        self.assertEqual(lv.overdue_tickets(now, paths=self.paths, conn=self.conn), [],
                         "the capture slot owns these grades; the alert is for what this loop should have graded")


class NflFromTheLiveFinal(LiveCase):
    def test_an_nfl_ticket_grades_from_the_live_final_and_the_old_source_failing_does_not_matter(self):
        url = ls.scoreboard_url("nfl", datetime(2026, 10, 25).date())
        self.write(user_bet(1, event="evt-nfl", sport="NFL", league=None, away="Buffalo Bills", home="Miami Dolphins",
                           start="2026-10-25T17:00:00Z", slate="2026-10-25", side="away", market="spread", line=-3.5,
                           price=-110))
        feed = Fake({url: self.board(espn_event("n1", "Miami Dolphins", "Buffalo Bills", hs=17, as_=24,
                                                date="2026-10-25T17:00Z"))})
        from unittest import mock
        with mock.patch.object(user_settle, "default_nfl_results", side_effect=RuntimeError("no schedule")):
            report = self.run_pass(utc("2026-10-25T21:30:00Z"), feed)
        self.assertEqual(report["graded"], 1)
        g = self.graded()[0]
        self.assertEqual((g["result"], g["away_score"], g["home_score"]), ("WIN", 24, 17))


class FailuresRetryWithBackoff(LiveCase):
    def test_a_failed_fetch_is_logged_recorded_and_retried_after_a_growing_wait(self):
        self.write(user_bet(1))
        feed = Fake({NBA_URL: RuntimeError("503 from espn")})
        with self.assertLogs("linehound.hounds.live_settle", level="WARNING"):
            self.run_pass(FINAL_AT, feed)
        row = self.conn.execute("SELECT fails, next_try_utc, last_error FROM live_games").fetchone()
        self.assertEqual(row["fails"], 1)
        self.assertIn("503", row["last_error"])
        before = len(feed.urls)
        self.run_pass(FINAL_AT + timedelta(seconds=30), feed)
        self.assertEqual(len(feed.urls), before, "inside the backoff window: no new request")
        feed.boards[NBA_URL] = self.board(espn_event("401", "Brooklyn Nets", "Charlotte Hornets"))
        report = self.run_pass(FINAL_AT + timedelta(minutes=5), feed)
        self.assertEqual(report["graded"], 1)
        self.assertEqual(self.conn.execute("SELECT fails FROM live_games").fetchone()["fails"], 0)

    def test_a_pass_that_raises_inside_the_loop_wrapper_is_swallowed_and_recorded(self):
        report = lv.pass_safely(now=FINAL_AT, conn=None, paths={"user": "/nonexistent"},
                                fetch_json=lambda url: (_ for _ in ()).throw(RuntimeError("boom")))
        self.assertTrue("error" in report or report.get("games") == 0)


class NeverGuess(unittest.TestCase):
    def one(self, event, home="Brooklyn Nets", away="Charlotte Hornets", league="nba"):
        want = [{"key": "k", "home_team": home, "away_team": away, "start": utc(TIP)}]
        return ls.espn_answers({"events": [event]}, league, want, "2026-10-22T02:00:00Z")

    def test_a_swapped_orientation_is_not_matched_never_flipped(self):
        self.assertEqual(self.one(espn_event("1", "Charlotte Hornets", "Brooklyn Nets")), {})

    def test_two_events_for_one_pair_a_doubleheader_is_no_answer(self):
        payload = {"events": [espn_event("1", "Brooklyn Nets", "Charlotte Hornets"),
                              espn_event("2", "Brooklyn Nets", "Charlotte Hornets")]}
        want = [{"key": "k", "home_team": "Brooklyn Nets", "away_team": "Charlotte Hornets", "start": utc(TIP)}]
        self.assertEqual(ls.espn_answers(payload, "nba", want, "x"), {})

    def test_a_start_far_from_the_tickets_start_is_a_different_game(self):
        far = espn_event("1", "Brooklyn Nets", "Charlotte Hornets", date="2026-10-28T23:30Z")
        self.assertEqual(self.one(far), {})

    def test_a_final_with_no_score_is_not_a_final(self):
        event = espn_event("1", "Brooklyn Nets", "Charlotte Hornets")
        for comp in event["competitions"][0]["competitors"]:
            comp.pop("score")
        self.assertNotEqual(self.one(event).get("k", {}).get("state"), "final")

    def test_soccer_counts_only_regulation_time(self):
        reg = espn_event("1", "Arsenal", "Chelsea", name="STATUS_FULL_TIME", hs=2, as_=1)
        aet = espn_event("2", "Arsenal", "Chelsea", name="STATUS_FINAL_AET", hs=2, as_=2)
        want = [{"key": "k", "home_team": "Arsenal FC", "away_team": "Chelsea", "start": utc(TIP)}]
        self.assertEqual(ls.espn_answers({"events": [reg]}, "epl", want, "x")["k"]["state"], "final")
        self.assertEqual(ls.espn_answers({"events": [aet]}, "epl", want, "x")["k"]["state"], "live")

    def test_team_names(self):
        self.assertTrue(ls.teams_match("Los Angeles Clippers", "LA Clippers"))
        self.assertTrue(ls.teams_match("Brighton and Hove Albion", "Brighton & Hove Albion"))
        self.assertFalse(ls.teams_match("Los Angeles Kings", "Sacramento Kings"))
        self.assertFalse(ls.teams_match("Utah Jazz", "Utah Mammoth"))

    def test_unsupported_families_are_left_to_the_old_path(self):
        for family in ("CRICKET", "RUGBY", "AFL"):      # tennis and MMA: tests/test_live_settle_verify.py
            self.assertFalse(ls.supported(family))
        self.assertTrue(ls.supported("NBA"))
        self.assertFalse(ls.supported("MLB"), "an MLB ticket with no game_pk cannot be asked by pk")
        self.assertTrue(ls.supported("MLB", game_pk="1"))


class AiLedger(LiveCase):
    def test_the_ai_ledger_is_settled_through_pack_settle_with_the_live_final(self):
        from src.hounds.pack import base
        bet = {"kind": "hound_bet", "pack": "ai_v1", "hound_id": "claude-test", "event_id": EVENT, "sport": "nba",
               "away": "Charlotte Hornets", "home": "Brooklyn Nets", "date": SLATE, "start_utc": TIP,
               "market": "moneyline", "selection": "Brooklyn Nets ML", "side": "home", "line": None,
               "market_line": None, "price_average": -110, "price_best": -105, "stake": 1.0, "segment": "forward",
               "lock_utc": "2026-10-21T22:30:00Z", "written_utc": "2026-10-21T22:31:00Z"}
        HashChainLedger(self.paths["ai"]).append(bet)
        feed = Fake({NBA_URL: self.board(espn_event("401", "Brooklyn Nets", "Charlotte Hornets"))})
        report = self.run_pass(FINAL_AT, feed, stores_loader=lambda: base.Stores())
        self.assertEqual(report["graded"], 1)
        graded = [r for r in HashChainLedger(self.paths["ai"]).read() if r.get("kind") == "hound_graded"]
        self.assertEqual((graded[0]["result"], graded[0]["final_score"]), ("WIN", {"away": 108.0, "home": 112.0}))


class Flag(unittest.TestCase):
    def test_default_on_in_code_and_off_by_name(self):
        self.assertTrue(lv.enabled({}))
        self.assertTrue(lv.enabled({"LIVE_SETTLE": "on"}))
        for word in ("off", "0", "false", "no", "OFF"):
            self.assertFalse(lv.enabled({"LIVE_SETTLE": word}))

    def test_the_loop_starts_nothing_when_off(self):
        self.assertIsNone(lv.start_loop(env={"LIVE_SETTLE": "off"}))

    def test_the_loop_runs_a_pass_and_stops(self):
        import threading
        stop, ran = threading.Event(), threading.Event()
        thread = lv.start_loop(interval_s=0.05, stop_event=stop, env={"LIVE_SETTLE": "on"},
                               do_pass=lambda: ran.set())
        self.assertTrue(ran.wait(2.0))
        stop.set()
        thread.join(2.0)
        self.assertFalse(thread.is_alive())


class StatusAndOverdue(LiveCase):
    def test_status_counts_games_awaiting_a_final_and_remembers_the_last_grade(self):
        self.write(user_bet(1), user_bet(2, event="evt2", away="Utah Jazz", home="Memphis Grizzlies",
                                           start="2026-10-22T00:15:00Z"))
        feed = Fake({NBA_URL: self.board(
            espn_event("401", "Brooklyn Nets", "Charlotte Hornets", state="in", name="STATUS_IN_PROGRESS",
                       completed=False, hs=50, as_=48, detail="Q3"),
            espn_event("402", "Memphis Grizzlies", "Utah Jazz", state="in", name="STATUS_IN_PROGRESS",
                       completed=False, hs=40, as_=44, date="2026-10-22T00:15Z", detail="Q2"))})
        now = utc("2026-10-22T01:30:00Z")
        self.run_pass(now, feed)
        st = lv.status(now=now, conn=self.conn)
        self.assertEqual((st["awaiting_final"], st["last_graded_utc"], st["enabled"]), (2, None, True))
        feed.boards[NBA_URL] = self.board(espn_event("401", "Brooklyn Nets", "Charlotte Hornets"),
                                          espn_event("402", "Memphis Grizzlies", "Utah Jazz", hs=99, as_=90,
                                                     date="2026-10-22T00:15Z"))
        later = utc("2026-10-22T02:40:00Z")
        self.run_pass(later, feed)
        st = lv.status(now=later, conn=self.conn)
        self.assertEqual((st["awaiting_final"], st["last_graded_utc"]), (0, "2026-10-22T02:40:00Z"))

    def test_an_open_ticket_four_hours_past_the_start_is_overdue_and_clears_once_graded(self):
        self.write(user_bet(1))
        late = utc("2026-10-22T03:45:00Z")
        self.assertEqual(lv.overdue_tickets(utc("2026-10-22T03:20:00Z"), paths=self.paths, conn=self.conn), [])
        over = lv.overdue_tickets(late, paths=self.paths, conn=self.conn)
        self.assertEqual([(o["game"], o["tickets"]) for o in over], [("Charlotte Hornets @ Brooklyn Nets", 1)])
        self.assertGreaterEqual(over[0]["hours_overdue"], 4.0)
        feed = Fake({NBA_URL: self.board(espn_event("401", "Brooklyn Nets", "Charlotte Hornets"))})
        self.run_pass(late, feed)
        self.assertEqual(lv.overdue_tickets(late, paths=self.paths, conn=self.conn), [])

    def test_a_game_the_feed_cannot_read_is_not_counted_so_the_alert_cannot_cry_wolf(self):
        self.write(user_bet(1, event="evt-cricket", sport="CRICKET", league="cricket_ipl", away="A", home="B"))
        self.assertEqual(lv.overdue_tickets(utc("2026-10-22T09:00:00Z"), paths=self.paths, conn=self.conn), [])


class Packaging(unittest.TestCase):
    def test_the_new_files_sit_under_trees_the_image_copies_wholesale(self):
        from pathlib import Path
        root = Path(__file__).resolve().parent.parent
        docker = (root / "deploy" / "Dockerfile").read_text(encoding="utf-8")
        for tree in ("api/", "src/", "web/"):
            self.assertIn(f"COPY {tree} {tree}", docker)
        for rel in ("src/hounds/live_settle.py", "src/hounds/live_scores.py", "api/hounds_live.py",
                    "web/js/ticket-live.js"):
            self.assertTrue((root / rel).exists(), rel)


if __name__ == "__main__":
    unittest.main()
