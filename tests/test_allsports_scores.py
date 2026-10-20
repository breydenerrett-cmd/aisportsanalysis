"""src/pipeline/allsports_scores.py and the all-sports branch of src/hounds/user_settle.py.

Injected fetchers and temp stores only: no network, no real data store.
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from src.capture import budget
from src.hounds import user_engine as eng
from src.hounds import user_settle as st
from src.pipeline import allsports_scores as S
from tests._allsports_fixtures import ENV, NOW, Paths, config, iso, minutes, read_jsonl
from tests._hounds_user_fixtures import DATE, EVENT, HOME, AWAY, START, hound, standard_rows, utc

START_DT = utc(START)
FINAL = START_DT + timedelta(hours=4)               # a settle pass well after the game
LATE = START_DT + timedelta(hours=80)               # past the 72 hour void line


def vendor_event(event_id=EVENT, home=HOME, away=AWAY, home_score=None, away_score=None, completed=True,
                 start=START):
    scores = None if home_score is None else [{"name": home, "score": str(home_score)},
                                              {"name": away, "score": str(away_score)}]
    return {"id": event_id, "sport_key": "basketball_nba", "commence_time": start, "completed": completed,
            "home_team": home, "away_team": away, "scores": scores, "last_update": start}


def result(home_score, away_score, completed=True, **kw):
    return S.score_row(vendor_event(home_score=home_score, away_score=away_score, completed=completed, **kw),
                       "2026-10-21T02:00:00Z", "basketball_nba")


def bet(market="moneyline", side="home", line=None, sport="NBA", start=START, price=-120):
    return {"sport": sport, "market": market, "side": side, "line": line, "price": price, "best_price": price,
            "commence_time": start, "event_id": EVENT}


class ParsingAndOutcomes(unittest.TestCase):
    def test_scores_parse_as_numbers(self):
        self.assertEqual(S.parse_score("112"), 112.0)
        self.assertEqual(S.parse_score(3), 3.0)
        self.assertEqual(S.parse_score("152/6"), 152.0)          # cricket: runs / wickets
        self.assertEqual(S.parse_score("152/6 (20 ov)"), 152.0)
        for unreadable in (None, "", "abc", "212 & 180/4", True):
            self.assertIsNone(S.parse_score(unreadable), unreadable)

    def test_every_outcome_is_stored_the_draw_included(self):
        self.assertEqual(result(2, 1)["outcome"], "home")
        self.assertEqual(result(1, 2)["outcome"], "away")
        self.assertEqual(result(2, 2)["outcome"], "draw")
        row = S.score_row(vendor_event(completed=False), "2026-10-20T20:00:00Z", "basketball_nba")
        self.assertIsNone(row["outcome"])
        self.assertIs(row["completed"], False)
        self.assertEqual((row["home_score"], row["away_score"]), (None, None))

    def test_the_vendors_scores_list_is_kept_verbatim(self):
        row = result(100, 99)
        self.assertEqual(row["scores"], [{"name": HOME, "score": "100"}, {"name": AWAY, "score": "99"}])


class Store(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = os.path.join(self._tmp.name, "scores.jsonl")

    def test_a_row_is_appended_only_when_the_state_changes(self):
        live = vendor_event(home_score=50, away_score=48, completed=False)
        final = vendor_event(home_score=101, away_score=99, completed=True)
        self.assertEqual(S.append_scores([live], "t1", "k", self.path), 1)
        self.assertEqual(S.append_scores([live], "t2", "k", self.path), 0)          # unchanged: nothing written
        self.assertEqual(S.append_scores([final], "t3", "k", self.path), 1)
        self.assertEqual(S.append_scores([final], "t4", "k", self.path), 0)
        rows = read_jsonl(self.path)
        self.assertEqual([r["completed"] for r in rows], [False, True])             # history kept, nothing rewritten

    def test_a_finished_game_is_never_unfinished_by_a_later_row(self):
        S._append(self.path, [result(101, 99), {**result(101, 99, completed=False), "observed_utc": "later"}])
        self.assertIs(S.load_index(self.path)[EVENT]["completed"], True)

    def test_the_store_is_append_only(self):
        S.append_scores([vendor_event(home_score=1, away_score=0, completed=False)], "t1", "k", self.path)
        before = open(self.path, "rb").read()
        S.append_scores([vendor_event(home_score=2, away_score=0, completed=True)], "t2", "k", self.path)
        self.assertTrue(open(self.path, "rb").read().startswith(before))


class Grading(unittest.TestCase):
    def grade(self, b, res, now=FINAL):
        return S.grade_bet(b, res, now)

    def test_a_team_moneyline_wins_and_loses_on_the_higher_score(self):
        self.assertEqual(self.grade(bet(side="home"), result(101, 99))["result"], "WIN")
        self.assertEqual(self.grade(bet(side="away"), result(101, 99))["result"], "LOSS")
        self.assertEqual(self.grade(bet(side="away"), result(99, 101))["result"], "WIN")

    def test_a_soccer_draw_loses_a_team_moneyline(self):
        for side in ("home", "away"):
            g = self.grade(bet(sport="SOCCER", side=side), result(1, 1))
            self.assertEqual(g["result"], "LOSS", side)
            self.assertIn("draw", g["reason"])

    def test_cricket_rugby_and_afl_draws_lose_too(self):
        for sport in ("CRICKET", "RUGBY", "AFL"):
            self.assertEqual(self.grade(bet(sport=sport), result(150, 150))["result"], "LOSS", sport)

    def test_a_level_score_in_a_two_way_sport_is_a_push_not_an_invented_loss(self):
        g = self.grade(bet(sport="NBA"), result(100, 100))
        self.assertEqual(g["result"], "PUSH")

    def test_spreads_use_the_picked_sides_own_line(self):
        # home -4.5 covers a 10 point win and fails a 4 point win; away +4.5 is the mirror image
        self.assertEqual(self.grade(bet("spread", "home", -4.5), result(110, 100))["result"], "WIN")
        self.assertEqual(self.grade(bet("spread", "home", -4.5), result(104, 100))["result"], "LOSS")
        self.assertEqual(self.grade(bet("spread", "away", 4.5), result(104, 100))["result"], "WIN")
        self.assertEqual(self.grade(bet("spread", "away", 4.5), result(110, 100))["result"], "LOSS")
        self.assertEqual(self.grade(bet("spread", "home", -4.0), result(104, 100))["result"], "PUSH")

    def test_totals_over_under_and_push(self):
        self.assertEqual(self.grade(bet("total", "over", 200.5), result(101, 100))["result"], "WIN")
        self.assertEqual(self.grade(bet("total", "under", 200.5), result(101, 100))["result"], "LOSS")
        self.assertEqual(self.grade(bet("total", "over", 201.0), result(101, 100))["result"], "PUSH")

    def test_soccer_total_counts_both_teams_goals(self):
        self.assertEqual(self.grade(bet("total", "over", 2.5, sport="SOCCER"), result(2, 1))["result"], "WIN")
        self.assertEqual(self.grade(bet("total", "under", 2.5, sport="SOCCER"), result(1, 1))["result"], "WIN")

    def test_a_game_not_yet_complete_stays_pending_inside_the_window(self):
        self.assertIsNone(self.grade(bet(), None)["result"])
        self.assertIsNone(self.grade(bet(), result(50, 48, completed=False))["result"])

    def test_no_completed_score_72_hours_after_the_start_is_a_named_void(self):
        for res in (None, result(50, 48, completed=False)):
            g = self.grade(bet(), res, now=LATE)
            self.assertEqual(g["result"], "VOID")
            self.assertIn("72 hours", g["reason"])

    def test_exactly_72_hours_is_the_line(self):
        self.assertIsNone(self.grade(bet(), None, now=START_DT + timedelta(hours=71, minutes=59))["result"])
        self.assertEqual(self.grade(bet(), None, now=START_DT + timedelta(hours=72))["result"], "VOID")

    def test_a_completed_game_with_no_readable_score_is_void(self):
        res = S.score_row(vendor_event(completed=True), "t", "k")
        self.assertEqual(self.grade(bet(), res)["result"], "VOID")

    def test_a_family_with_no_result_source_voids_by_name(self):
        g = self.grade(bet(sport="TENNIS"), None, now=LATE)
        self.assertEqual(g["result"], "VOID")
        self.assertIn("no result source", g["reason"])

    def test_a_late_result_still_grades_normally(self):
        self.assertEqual(self.grade(bet(), result(101, 99), now=LATE)["result"], "WIN")

    def test_unusable_bets_void_rather_than_guess(self):
        self.assertEqual(self.grade(bet("spread", "home", None), result(1, 0))["result"], "VOID")
        self.assertEqual(self.grade(bet("prop", "over", 1.5), result(1, 0))["result"], "VOID")


class WhichKeysToPoll(unittest.TestCase):
    def done(self, key, event, start):
        return {"kind": "phase", "sport_key": key, "event_id": event, "phase": "t2h",
                "commence_utc": iso(start), "observed_utc": iso(start - minutes(100))}

    def test_only_keys_with_unresolved_finished_games_are_due_most_unresolved_first(self):
        cap = config()["capture"]
        done = [self.done("k_a", "e1", NOW - timedelta(hours=5)), self.done("k_b", "e2", NOW - timedelta(hours=5)),
                self.done("k_b", "e3", NOW - timedelta(hours=6)),
                self.done("k_c", "e4", NOW - minutes(20)),                    # not over yet
                self.done("k_d", "e5", NOW - timedelta(days=5))]              # beyond the daysFrom window
        keys = S.keys_to_poll(done, [], NOW, cap)
        self.assertEqual(keys, [("k_b", 2), ("k_a", 1)])

    def test_a_key_with_every_game_completed_is_not_polled(self):
        cap = config()["capture"]
        done = [self.done("k_a", "e1", NOW - timedelta(hours=5))]
        scores = [{"kind": "score", "event_id": "e1", "completed": True, "observed_utc": iso(NOW)}]
        self.assertEqual(S.keys_to_poll(done, scores, NOW, cap), [])

    def test_a_key_polled_recently_waits_for_the_interval(self):
        cap = config()["capture"]
        done = [self.done("k_a", "e1", NOW - timedelta(hours=5))]
        polled = [{"kind": "poll", "sport_key": "k_a", "observed_utc": iso(NOW - timedelta(hours=2))}]
        self.assertEqual(S.keys_to_poll(done, polled, NOW, cap), [])
        self.assertEqual(S.keys_to_poll(done, polled, NOW + timedelta(hours=7), cap), [("k_a", 1)])


class RunPolls(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.paths = Paths(self._tmp.name)
        with open(self.paths.done, "w", encoding="utf-8") as fh:
            fh.write(json.dumps({"kind": "phase", "sport_key": "basketball_nba", "event_id": EVENT, "phase": "t2h",
                                 "commence_utc": iso(NOW - timedelta(hours=5))}) + "\n")
        self.calls = []

    def fetch(self, key, days_from):
        self.calls.append((key, days_from))
        return [vendor_event(start=iso(NOW - timedelta(hours=5)), home_score=101, away_score=99)], \
            {"remaining": 80000, "last": 2}

    def run_it(self, **kw):
        return S.run(now=NOW, env=ENV, fetch_scores=self.fetch, quota=lambda: {"remaining": 80002},
                     done_path=self.paths.done, store_path=self.paths.scores, credit_store=self.paths.credit, **kw)

    def test_a_poll_stores_the_result_and_logs_two_credits_in_the_allsports_band(self):
        result_ = self.run_it()
        self.assertEqual(self.calls, [("basketball_nba", 3)])
        self.assertEqual(result_["credits"], 2)
        kinds = [r["kind"] for r in read_jsonl(self.paths.scores)]
        self.assertEqual(kinds, ["score", "poll"])
        logged = read_jsonl(self.paths.credit)
        self.assertEqual(len(logged), 1)
        self.assertEqual((logged[0]["budget_band"], logged[0]["credits_used_last"], logged[0]["caller"]),
                         (budget.ALLSPORTS, 2, "allsports_scores.poll"))
        self.assertIs(S.load_index(self.paths.scores)[EVENT]["completed"], True)

    def test_the_finished_game_is_not_polled_again(self):
        self.run_it()
        self.run_it()
        self.assertEqual(len(self.calls), 1)

    def test_the_scores_sub_cap_stops_polling(self):
        with open(self.paths.credit, "w", encoding="utf-8") as fh:
            fh.write(json.dumps({"utc": "2026-10-20T10:00:00Z", "credits_remaining": 80000,
                                 "credits_used_last": 299, "caller": "allsports_scores.poll",
                                 "budget_band": "allsports_capture"}) + "\n")
        result_ = self.run_it()
        self.assertEqual(self.calls, [])
        self.assertIn("sub-cap", result_["skipped"]["basketball_nba"])

    def test_the_credit_floor_stops_polling(self):
        result_ = S.run(now=NOW, env=ENV, fetch_scores=self.fetch, quota=lambda: {"remaining": 5001},
                        done_path=self.paths.done, store_path=self.paths.scores, credit_store=self.paths.credit)
        self.assertEqual(self.calls, [])
        self.assertIn("credit floor", result_["halt"])

    def test_plan_only_spends_and_writes_nothing(self):
        result_ = self.run_it(plan_only=True)
        self.assertEqual(result_["keys"], ["basketball_nba"])
        self.assertEqual((self.calls, read_jsonl(self.paths.scores), read_jsonl(self.paths.credit)), ([], [], []))


class SettlesMemberDogBets(unittest.TestCase):
    """user_settle.settle over bets the engine wrote on an all-sports family."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.ledger = os.path.join(self._tmp.name, "hounds.jsonl")

    def board(self, sport="nba"):
        rows = standard_rows(sport=sport)
        for r in rows:
            r["league"] = "basketball_nba" if sport == "nba" else "soccer_epl"
            r["league_title"] = "NBA" if sport == "nba" else "EPL"
        return rows

    def bet(self, sport_code="NBA", **over):
        rows = self.board(sport_code.lower())
        eng.run(DATE, [hound(sports=[sport_code], **over)], rows, ledger=self.ledger,
                now=utc("2026-10-20T21:10:00Z"))

    def bets(self):
        return [r for r in eng.read_ledger(self.ledger) if r["kind"] == eng.KIND_BET]

    def graded(self):
        return [r for r in eng.read_ledger(self.ledger) if r["kind"] == st.KIND_GRADED]

    def settle(self, results, now=FINAL):
        return st.settle(ledger=self.ledger, now=now, close_fn=lambda b: None, allsports_results=results)

    def test_the_bet_row_carries_the_league_so_a_scores_feed_can_be_chosen(self):
        self.bet(price_min=100, price_max=250)
        b = self.bets()[0]
        self.assertEqual((b["sport"], b["league"], b["league_title"]), ("NBA", "basketball_nba", "NBA"))

    def test_an_nba_bet_settles_from_the_scores_store(self):
        self.bet(price_min=100, price_max=250)                      # the away dog at +120
        report = self.settle({EVENT: result(99, 101)})
        self.assertEqual(report["graded"], 1)
        g = self.graded()[0]
        self.assertEqual((g["result"], g["profit_units"]), ("WIN", 1.2))
        self.assertEqual((g["away_score"], g["home_score"]), (101, 99))

    def test_a_soccer_draw_loses_the_dogs_team_moneyline(self):
        self.bet("SOCCER", price_min=100, price_max=250)
        self.settle({EVENT: result(1, 1)})
        g = self.graded()[0]
        self.assertEqual((g["result"], g["profit_units"]), ("LOSS", -1.0))

    def test_a_game_with_no_result_stays_pending_then_voids_after_72_hours(self):
        self.bet(price_min=100, price_max=250)
        report = self.settle({}, now=FINAL)
        self.assertEqual((report["graded"], report["pending"]), (0, 1))
        self.assertEqual(self.graded(), [])
        report = self.settle({}, now=LATE)
        self.assertEqual(report["graded"], 1)
        g = self.graded()[0]
        self.assertEqual((g["result"], g["profit_units"]), ("VOID", 0.0))
        self.assertIn("72 hours", g["reason"])

    def test_a_graded_bet_is_never_graded_twice(self):
        self.bet(price_min=100, price_max=250)
        self.settle({EVENT: result(99, 101)})
        again = self.settle({EVENT: result(99, 101)})
        self.assertEqual((again["considered"], len(self.graded())), (0, 1))

    def test_the_default_reads_the_scores_store_lazily_and_only_when_a_bet_needs_it(self):
        self.bet(price_min=100, price_max=250)
        called = []
        original = S.load_index
        S.load_index = lambda *a, **k: called.append(1) or {EVENT: result(99, 101)}
        try:
            st.settle(ledger=self.ledger, now=FINAL, close_fn=lambda b: None)
        finally:
            S.load_index = original
        self.assertEqual(called, [1])
        self.assertEqual(self.graded()[0]["result"], "WIN")

    def test_mlb_bets_still_go_to_the_mlb_results_store(self):
        from tests._hounds_user_fixtures import result_row
        eng.run(DATE, [hound(price_min=100, price_max=250)], standard_rows(), ledger=self.ledger,
                now=utc("2026-10-20T21:10:00Z"), game_pk_index={EVENT: {"game_pk": "900001"}})
        report = st.settle(ledger=self.ledger, now=utc("2026-10-21T12:00:00Z"), close_fn=lambda b: None,
                           mlb_results={"900001": result_row("900001", DATE, "BOS", "SEA", 5, 3)},
                           game_pk_index={EVENT: {"game_pk": "900001"}},
                           allsports_results=lambda: self.fail("the all-sports store must not be read for MLB"))
        self.assertEqual(report["graded"], 1)


if __name__ == "__main__":
    unittest.main()
