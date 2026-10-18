"""src/hounds/user_settle.py: grading from the cards' own results rules, voids, postponements, CLV."""
from __future__ import annotations

import os
import tempfile
import unittest

from src.hounds import user_engine as eng
from src.hounds import user_settle as st
from tests._hounds_user_fixtures import (BOOKS, DATE, EVENT, T_LOCK, board_rows, hound,
                                         result_row, standard_rows, utc)

AT_LOCK = utc("2026-10-20T21:10:00Z")
NEXT_DAY = utc("2026-10-21T12:00:00Z")
PK = "900001"
INDEX = {EVENT: {"game_pk": PK}}


class SettleCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.ledger = os.path.join(self._tmp.name, "hounds.jsonl")

    def tearDown(self):
        self._tmp.cleanup()

    def bet(self, rows=None, **over):
        eng.run(DATE, [hound(**over)], standard_rows() if rows is None else rows,
                ledger=self.ledger, now=AT_LOCK, game_pk_index=INDEX)

    def settle(self, results, **kw):
        kw.setdefault("close_fn", lambda bet: None)
        kw.setdefault("game_pk_index", INDEX)
        return st.settle(ledger=self.ledger, now=NEXT_DAY, mlb_results=results, **kw)

    def graded(self):
        return [r for r in eng.read_ledger(self.ledger) if r["kind"] == st.KIND_GRADED]


class Grading(SettleCase):
    def test_a_win_is_graded_at_the_average_price_with_the_best_price_beside_it(self):
        self.bet(price_min=100, price_max=250)                 # away dog at +120
        report = self.settle({PK: result_row(PK, DATE, "BOS", "SEA", 5, 3)})
        self.assertEqual(report["graded"], 1)
        g = self.graded()[0]
        self.assertEqual((g["result"], g["profit_units"], g["profit_units_best"]), ("WIN", 1.2, 1.2))
        self.assertEqual((g["away_score"], g["home_score"]), (5, 3))

    def test_average_and_best_profits_differ_when_the_books_disagree(self):
        rows = board_rows(T_LOCK, moneyline=[("a", -130, 100), ("b", -150, 200), ("c", -140, 150)])
        self.bet(rows=rows, price_min=100, price_max=300)
        self.settle({PK: result_row(PK, DATE, "BOS", "SEA", 5, 3)})
        g = self.graded()[0]
        self.assertEqual(g["profit_units"], 1.5)               # decimals 2, 3, 2.5 -> 2.5 -> +150
        self.assertEqual(g["profit_units_best"], 2.0)          # best single price was +200

    def test_a_loss_costs_one_unit(self):
        self.bet(price_min=100, price_max=250)
        self.settle({PK: result_row(PK, DATE, "BOS", "SEA", 1, 3)})
        self.assertEqual((self.graded()[0]["result"], self.graded()[0]["profit_units"]), ("LOSS", -1.0))

    def test_spread_and_total_are_graded_on_their_lines(self):
        self.bet(markets=["spread", "total"], side_rule="market_moved_toward",
                 price_min=-195, price_max=150, max_bets_per_day=5)
        bets = [r for r in eng.read_ledger(self.ledger) if r["kind"] == eng.KIND_BET]
        self.assertEqual({b["market"] for b in bets}, {"spread", "total"})
        # away +1.5 (the dog) covers in a 4-3 home win; total 8.5 'over' loses at 7 runs
        self.settle({PK: result_row(PK, DATE, "BOS", "SEA", 3, 4)})
        by_market = {g["bet_id"]: g["result"] for g in self.graded()}
        got = {b["market"]: by_market[b["bet_id"]] for b in bets}
        self.assertEqual(got["total"], "LOSS")
        self.assertIn(got["spread"], ("WIN", "LOSS"))

    def test_a_total_on_the_line_is_a_push_with_zero_units(self):
        self.bet(markets=["total"], side_rule="over", price_min=-130, price_max=-100)
        rows = [r for r in eng.read_ledger(self.ledger) if r["kind"] == eng.KIND_BET]
        self.assertEqual(rows[0]["line"], 8.5)
        # 8.5 cannot push; rebuild the bet with a whole-number line
        os.remove(self.ledger)
        whole = board_rows(T_LOCK, total=(8.0, [(b, -110, -110) for b in BOOKS]))
        self.bet(rows=whole, markets=["total"], side_rule="over", price_min=-130, price_max=-100)
        self.settle({PK: result_row(PK, DATE, "BOS", "SEA", 4, 4)})
        g = self.graded()[0]
        self.assertEqual((g["result"], g["profit_units"], g["profit_units_best"]), ("PUSH", 0.0, 0.0))

    def test_an_explicit_void_follows_the_existing_contract(self):
        self.bet(price_min=100, price_max=250)
        self.settle({PK: {"game_pk": PK, "void": True, "reason": "suspended game, not resumed"}})
        g = self.graded()[0]
        self.assertEqual((g["result"], g["profit_units"]), ("VOID", 0.0))
        self.assertIn("suspended", g["reason"])

    def test_graded_once_ever(self):
        self.bet(price_min=100, price_max=250)
        results = {PK: result_row(PK, DATE, "BOS", "SEA", 5, 3)}
        self.assertEqual(self.settle(results)["graded"], 1)
        self.assertEqual(self.settle(results)["graded"], 0)
        self.assertEqual(len(self.graded()), 1)
        self.assertTrue(eng.verify_ledger(self.ledger).ok)

    def test_a_game_that_has_not_started_is_not_graded(self):
        self.bet(price_min=100, price_max=250)
        report = st.settle(ledger=self.ledger, now=utc("2026-10-20T22:00:00Z"),
                           mlb_results={PK: result_row(PK, DATE, "BOS", "SEA", 5, 3)},
                           close_fn=lambda b: None, game_pk_index=INDEX)
        self.assertEqual((report["graded"], report["pending"]), (0, 1))

    def test_a_missing_game_pk_is_resolved_by_date_and_teams_only_when_unique(self):
        eng.run(DATE, [hound(price_min=100, price_max=250)], standard_rows(), ledger=self.ledger,
                now=AT_LOCK)                                  # no index: game_pk is None
        results = {"1": result_row("1", DATE, "BOS", "SEA", 5, 3),
                   "2": result_row("2", DATE, "BOS", "SEA", 1, 0)}      # a doubleheader
        self.assertEqual(self.settle(results, game_pk_index={})["graded"], 0)
        self.assertEqual(self.settle({"1": results["1"]}, game_pk_index={})["graded"], 1)


class Postponed(SettleCase):
    def test_a_postponed_game_is_pending_makeup_then_settles_once_from_its_final(self):
        self.bet(price_min=100, price_max=250)
        info = {"status": "pending_makeup", "makeup_date": "2026-10-22"}
        report = self.settle({}, postponed_lookup=lambda pk, day: info)
        self.assertEqual(report["graded"], 0)
        self.assertEqual(report["pending_makeup"][0]["makeup_date"], "2026-10-22")
        self.assertEqual(self.graded(), [])                   # nothing written, nothing escalated
        later = {PK: result_row(PK, "2026-10-22", "BOS", "SEA", 5, 3)}
        self.assertEqual(self.settle(later, postponed_lookup=lambda pk, day: info)["graded"], 1)
        self.assertEqual(self.settle(later)["graded"], 0)
        self.assertEqual(self.graded()[0]["result"], "WIN")

    def test_a_failed_schedule_lookup_is_never_read_as_pending(self):
        self.bet(price_min=100, price_max=250)

        def boom(pk, day):
            raise RuntimeError("schedule down")
        report = self.settle({}, postponed_lookup=boom)
        self.assertEqual((report["graded"], report["pending"], report["pending_makeup"]), (0, 1, []))

    def test_no_result_and_no_postponement_evidence_is_plain_pending(self):
        self.bet(price_min=100, price_max=250)
        report = self.settle({}, postponed_lookup=lambda pk, day: None)
        self.assertEqual((report["pending"], report["pending_makeup"]), (1, []))


class NflAndClv(SettleCase):
    def test_nfl_spread_is_graded_from_injected_scores(self):
        eng.run(DATE, [hound(sports=["NFL"], markets=["spread"], side_rule="underdog",
                             price_min=-195, price_max=150)],
                standard_rows(sport="nfl", home="Buffalo Bills", away="Miami Dolphins"),
                ledger=self.ledger, now=AT_LOCK)
        bet = [r for r in eng.read_ledger(self.ledger) if r["kind"] == eng.KIND_BET][0]
        self.assertEqual((bet["sport"], bet["side"], bet["line"]), ("NFL", "away", 1.5))
        report = st.settle(ledger=self.ledger, now=NEXT_DAY, close_fn=lambda b: None,
                           nfl_results=lambda d: {("MIA", "BUF"): {"home_score": 20, "away_score": 17}})
        self.assertEqual(report["graded"], 1)
        self.assertEqual(self.graded()[0]["result"], "LOSS")     # 17 + 1.5 < 20: the dog did not cover

    def test_clv_is_the_move_toward_the_average_close_on_the_same_line(self):
        self.bet(price_min=100, price_max=250)                  # away +120 at lock; close +150
        close = st.make_close_fn(lambda date, sport: standard_rows())
        bet = [r for r in eng.read_ledger(self.ledger) if r["kind"] == eng.KIND_BET][0]
        self.assertEqual(close(bet), 150)
        self.assertEqual(st.clv_points(120, 150), round((1 / 2.5 - 1 / 2.2) * 100, 3))
        self.assertLess(st.clv_points(120, 150), 0)             # price lengthened: the market disagreed
        self.assertGreater(st.clv_points(150, 120), 0)
        self.assertIsNone(st.clv_points(120, None))

    def test_a_moved_line_gets_no_clv(self):
        self.bet(markets=["total"], side_rule="over", price_min=-130, price_max=-100)
        bet = [r for r in eng.read_ledger(self.ledger) if r["kind"] == eng.KIND_BET][0]
        self.assertEqual(bet["line"], 8.5)
        self.assertIsNone(st.make_close_fn(lambda d, s: standard_rows())(bet))   # closed at 9.0

    def test_graded_rows_carry_close_and_clv_and_feed_the_record(self):
        self.bet(price_min=100, price_max=250)
        self.settle({PK: result_row(PK, DATE, "BOS", "SEA", 5, 3)}, close_fn=lambda b: 110)
        g = self.graded()[0]
        self.assertEqual(g["close_price"], 110)
        self.assertGreater(g["clv_pts"], 0)
        records = st.records_by_hound(eng.read_ledger(self.ledger))
        rec = records["u-test1"]
        self.assertEqual((rec["record"]["bets"], rec["record"]["wins"], rec["graded"]), (1, 1, 1))
        self.assertEqual(rec["record"]["units_average_price"], 1.2)
        self.assertEqual(rec["clv"]["n"], 1)
        self.assertIsNone(rec["clv"]["ci_low"])                 # one value has no interval


class Summaries(unittest.TestCase):
    def test_clv_summary_interval(self):
        s = st.clv_summary([1.0, 2.0, 3.0, 4.0])
        self.assertEqual((s["n"], s["mean_pts"]), (4, 2.5))
        self.assertLess(s["ci_low"], 2.5)
        self.assertGreater(s["ci_high"], 2.5)
        self.assertIsNone(st.clv_summary([]))

    def test_the_verdict_refuses_a_short_record(self):
        v = st.verdict_for({"graded": 12, "clv": {"n": 12, "mean_pts": 3.0, "ci_low": 1.0, "ci_high": 5.0}})
        self.assertEqual(v["label"], "too_early")
        self.assertIn("12", v["sentence"])

    def test_the_verdict_labels_follow_the_interval(self):
        base = {"graded": 40}
        self.assertEqual(st.verdict_for({**base, "clv": {"n": 40, "mean_pts": 1, "ci_low": 0.2,
                                                         "ci_high": 1.8}})["label"], "ahead_of_close")
        self.assertEqual(st.verdict_for({**base, "clv": {"n": 40, "mean_pts": -1, "ci_low": -1.8,
                                                         "ci_high": -0.2}})["label"], "behind_close")
        self.assertEqual(st.verdict_for({**base, "clv": {"n": 40, "mean_pts": 0, "ci_low": -1,
                                                         "ci_high": 1}})["label"], "unclear")
