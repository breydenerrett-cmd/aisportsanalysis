"""src/hounds/user_engine.py: selection, lock timing, average pricing, idempotency, the ledger chain."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from src.hounds import user_engine as eng
from src.hounds import user_spec
from src.ledger.chain import HashChainLedger
from tests._hounds_user_fixtures import (BOOKS, DATE, EVENT, T_LATE, T_LOCK, T_OPEN, board_rows,
                                         hound, standard_rows, utc)

BEFORE_LOCK = utc("2026-10-20T20:00:00Z")
AT_LOCK = utc("2026-10-20T21:10:00Z")
AFTER_LOCK = utc("2026-10-20T22:30:00Z")        # the late capture exists by now
AT_START = utc("2026-10-20T23:10:00Z")


class EngineCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.ledger = os.path.join(self._tmp.name, "hounds.jsonl")

    def tearDown(self):
        self._tmp.cleanup()

    def run_at(self, now, hounds, rows=None, mode="live", **kw):
        return eng.run(DATE, hounds, standard_rows() if rows is None else rows, ledger=self.ledger,
                       now=now, mode=mode, **kw)

    def bets(self):
        return [r for r in eng.read_ledger(self.ledger) if r["kind"] == eng.KIND_BET]


class LockTiming(EngineCase):
    def test_no_bet_before_the_lock(self):
        report = self.run_at(BEFORE_LOCK, [hound()])
        self.assertEqual(report["bets_written"], 0)
        self.assertEqual(report["skipped"].get("not_locked_yet"), 1)

    def test_a_bet_at_the_lock_uses_the_board_at_lock(self):
        self.assertEqual(self.run_at(AT_LOCK, [hound()])["bets_written"], 1)
        bet = self.bets()[0]
        self.assertEqual(bet["board_observed_utc"], T_LOCK)
        self.assertEqual(bet["lock_utc"], "2026-10-20T21:10:00Z")
        self.assertEqual(bet["price"], 120)                      # not the late board's +150

    def test_a_late_run_makes_the_same_bet_as_an_on_time_run(self):
        other = os.path.join(self._tmp.name, "other.jsonl")
        self.run_at(AT_LOCK, [hound()])
        eng.run(DATE, [hound()], standard_rows(), ledger=other, now=AFTER_LOCK)
        keep = ("bet_id", "side", "price", "best_price", "board_observed_utc", "selection", "line")
        a, b = self.bets()[0], eng.read_ledger(other)[0]
        self.assertEqual({k: a[k] for k in keep}, {k: b[k] for k in keep})

    def test_no_bet_at_or_after_the_start(self):
        for t in (AT_START, utc("2026-10-20T23:40:00Z")):
            report = self.run_at(t, [hound()])
            self.assertEqual(report["bets_written"], 0)
            self.assertEqual(report["skipped"].get("game_started"), 1)

    def test_the_last_guard_uses_the_clock_at_write_time(self):
        # First read admits the candidate (still before the start); the read taken just before the
        # write is past the start, so nothing may be written.
        ticks = iter([AFTER_LOCK, AT_START, AT_START])
        report = eng.run(DATE, [hound()], standard_rows(), ledger=self.ledger, now=None,
                         clock=lambda: next(ticks))
        self.assertEqual(report["bets_written"], 0)

    def test_in_play_rows_are_never_a_board(self):
        rows = standard_rows() + board_rows("2026-10-20T23:30:00Z",
                                            moneyline=[(b, -900, 600) for b in BOOKS])
        self.run_at(AFTER_LOCK, [hound()], rows=rows)
        self.assertEqual(self.bets()[0]["price"], 120)

    def test_a_hound_made_after_the_lock_does_not_back_fill(self):
        late = hound(created_at="2026-10-20T21:30:00Z")
        report = self.run_at(AFTER_LOCK, [late])
        self.assertEqual(report["skipped"].get("hound_created_after_lock"), 1)
        self.assertEqual(self.bets(), [])

    def test_a_stale_board_is_skipped_not_guessed(self):
        rows = board_rows("2026-10-20T19:00:00Z", moneyline=[(b, -140, 120) for b in BOOKS])
        report = self.run_at(AT_LOCK, [hound()], rows=rows)
        self.assertEqual(report["skipped"].get("board_too_old"), 1)

    def test_lock_minutes_changes_which_board_is_used(self):
        rows = standard_rows()
        eng.run(DATE, [hound(lock_minutes=60, min_books=3)], rows, ledger=self.ledger,
                now=utc("2026-10-20T22:15:00Z"))
        self.assertEqual(self.bets()[0]["lock_utc"], "2026-10-20T22:10:00Z")
        self.assertEqual(self.bets()[0]["board_observed_utc"], T_LOCK)


class SelectionAndPrice(EngineCase):
    def test_price_is_the_decimal_average_not_the_mean_of_american_prices(self):
        rows = board_rows(T_LOCK, moneyline=[("book_a", -130, -110), ("book_b", -150, 120),
                                             ("book_c", -140, 120)])
        self.run_at(AT_LOCK, [hound(price_min=-120, price_max=150, min_books=3)], rows=rows)
        bet = self.bets()[0]
        # decimals 1.909091, 2.2, 2.2 -> 2.103030 -> +110; a naive mean of (-110, 120, 120) is +43
        self.assertEqual(bet["price"], 110)
        self.assertEqual(bet["best_price"], 120)
        self.assertEqual(bet["n_books"], 3)

    def test_underdog_favourite_home_away(self):
        rows = standard_rows()
        for rule, selection in (("underdog", "Boston Red Sox to win"),
                                ("favourite", "Seattle Mariners to win"),
                                ("home", "Seattle Mariners to win"),
                                ("away", "Boston Red Sox to win")):
            with self.subTest(rule=rule):
                path = os.path.join(self._tmp.name, f"{rule}.jsonl")
                eng.run(DATE, [hound(side_rule=rule, price_min=-150, price_max=150)], rows,
                        ledger=path, now=AT_LOCK)
                self.assertEqual(eng.read_ledger(path)[0]["selection"], selection)

    def test_spread_selection_carries_the_line_from_the_picked_sides_view(self):
        h = hound(markets=["spread"], side_rule="underdog", price_min=-200 + 1, price_max=150)
        self.run_at(AT_LOCK, [h])
        bet = self.bets()[0]
        self.assertEqual((bet["side"], bet["line"], bet["selection"]),
                         ("away", 1.5, "Boston Red Sox +1.5"))
        self.assertEqual(bet["price"], -190)

    def test_totals_over_and_under_use_the_consensus_line(self):
        self.run_at(AT_LOCK, [hound(markets=["total"], side_rule="under", price_min=-130,
                                    price_max=-100)])
        bet = self.bets()[0]
        self.assertEqual((bet["side"], bet["line"], bet["selection"], bet["price"]),
                         ("under", 8.5, "Under 8.5", -115))

    def test_the_consensus_line_is_the_one_most_books_quote(self):
        rows = board_rows(T_LOCK, total=(8.5, [("book_a", -110, -110), ("book_b", -110, -110),
                                                ("book_c", -110, -110)]))
        rows += board_rows(T_LOCK, total=(9.0, [("book_d", -150, 130)]))
        self.run_at(AT_LOCK, [hound(markets=["total"], side_rule="over", price_min=-130,
                                    price_max=-100, min_books=3)], rows=rows)
        bet = self.bets()[0]
        self.assertEqual((bet["line"], bet["n_books"]), (8.5, 3))

    def test_market_moved_toward_and_away_since_the_first_capture(self):
        # Moneyline open -125/+105, lock -140/+120: the market moved toward the home side.
        for rule, side in (("market_moved_toward", "home"), ("market_moved_away", "away")):
            with self.subTest(rule=rule):
                path = os.path.join(self._tmp.name, f"{rule}.jsonl")
                eng.run(DATE, [hound(side_rule=rule, price_min=-150, price_max=150)],
                        standard_rows(), ledger=path, now=AT_LOCK)
                self.assertEqual(eng.read_ledger(path)[0]["side"], side)

    def test_a_totals_line_move_is_a_move_toward_the_over(self):
        # open 8.0, lock 8.5
        self.run_at(AT_LOCK, [hound(markets=["total"], side_rule="market_moved_toward",
                                    price_min=-130, price_max=-100)])
        self.assertEqual(self.bets()[0]["side"], "over")

    def test_no_move_places_no_bet_and_one_capture_cannot_move(self):
        flat = (board_rows(T_OPEN, moneyline=[(b, -140, 120) for b in BOOKS])
                + board_rows(T_LOCK, moneyline=[(b, -140, 120) for b in BOOKS]))
        h = hound(side_rule="market_moved_toward", price_min=-150, price_max=150)
        report = self.run_at(AT_LOCK, [h], rows=flat)
        self.assertEqual(report["skipped"].get("rule_has_no_side"), 1)
        single = board_rows(T_LOCK, moneyline=[(b, -140, 120) for b in BOOKS])
        self.assertEqual(self.run_at(AT_LOCK, [h], rows=single)["bets_written"], 0)

    def test_price_band_min_books_and_sport_filters(self):
        self.assertEqual(self.run_at(AT_LOCK, [hound(price_min=150, price_max=300)])["skipped"]
                         .get("outside_price_band"), 1)
        report = self.run_at(AT_LOCK, [hound(hid="u-b", min_books=6)])
        self.assertEqual(report["skipped"].get("too_few_books"), 1)
        report = self.run_at(AT_LOCK, [hound(hid="u-c", sports=["NFL"])])
        self.assertEqual(report["bets_written"], 0)

    def test_the_minus_200_cap_holds_even_for_a_hand_edited_spec(self):
        rows = board_rows(T_LOCK, moneyline=[(b, -260, 210) for b in BOOKS])
        h = hound(side_rule="favourite", price_min=-190, price_max=150)
        h["spec"] = dict(h["spec"], price_min=-400)               # bypasses validation on purpose
        report = self.run_at(AT_LOCK, [h], rows=rows)
        self.assertEqual(report["bets_written"], 0)
        self.assertEqual(report["skipped"].get("price_cap"), 1)

    def test_nfl_rows_are_a_separate_sport(self):
        rows = standard_rows(sport="nfl")
        report = self.run_at(AT_LOCK, [hound(sports=["NFL"], price_min=100, price_max=250)], rows=rows)
        self.assertEqual(report["bets_written"], 1)
        self.assertEqual(self.bets()[0]["sport"], "NFL")
        self.assertEqual(self.run_at(AT_LOCK, [hound(hid="u-m")], rows=rows)["skipped"], {})


class QuotaAndDeterminism(EngineCase):
    def many_games(self):
        rows = []
        for i, start in enumerate(("23:10", "00:10", "01:10", "02:10")):
            day = "2026-10-20" if i == 0 else "2026-10-21"
            commence = f"{day}T{start}:00Z"
            # lock (120 min) = 21:10Z, 22:10Z, 23:10Z, 00:10Z; one capture just before each
            lock_hour = ("21:05", "22:05", "23:05", "00:05")[i]
            lock_day = "2026-10-21" if i == 3 else "2026-10-20"
            rows += board_rows(f"{lock_day}T{lock_hour}:00Z", event_id=f"evt{i}", start=commence,
                               moneyline=[(b, -140, 120) for b in BOOKS])
        return rows

    def test_max_bets_per_day_takes_the_earliest_locks_first_across_runs(self):
        rows = self.many_games()
        h = hound(max_bets_per_day=2)
        eng.run(DATE, [h], rows, ledger=self.ledger, now=utc("2026-10-20T22:20:00Z"))
        self.assertEqual([b["event_id"] for b in self.bets()], ["evt0", "evt1"])
        report = eng.run(DATE, [h], rows, ledger=self.ledger, now=utc("2026-10-20T23:20:00Z"))
        self.assertEqual(report["bets_written"], 0)
        self.assertEqual(len(self.bets()), 2)

    def test_the_quota_is_per_hound_and_per_day(self):
        rows = self.many_games()
        eng.run(DATE, [hound("u-1", max_bets_per_day=1), hound("u-2", max_bets_per_day=3)], rows,
                ledger=self.ledger, now=utc("2026-10-20T22:20:00Z"))
        counts = {}
        for b in self.bets():
            counts[b["hound_id"]] = counts.get(b["hound_id"], 0) + 1
        self.assertEqual(counts, {"u-1": 1, "u-2": 2})

    def test_idempotent_per_hound_game_market(self):
        h = hound(markets=["moneyline", "spread", "total"], side_rule="market_moved_toward",
                  price_min=-190, price_max=150, max_bets_per_day=5)
        first = self.run_at(AT_LOCK, [h])
        second = self.run_at(AT_LOCK, [h])
        third = self.run_at(AFTER_LOCK, [h])
        self.assertGreaterEqual(first["bets_written"], 1)
        self.assertEqual((second["bets_written"], third["bets_written"]), (0, 0))
        ids = [b["bet_id"] for b in self.bets()]
        self.assertEqual(len(ids), len(set(ids)))

    def test_input_order_and_hound_order_do_not_change_the_output(self):
        rows = standard_rows()
        hs = [hound("u-1"), hound("u-2", side_rule="favourite", price_min=-150, price_max=150)]
        a = os.path.join(self._tmp.name, "a.jsonl")
        b = os.path.join(self._tmp.name, "b.jsonl")
        eng.run(DATE, hs, rows, ledger=a, now=AT_LOCK)
        eng.run(DATE, list(reversed(hs)), list(reversed(rows)), ledger=b, now=AT_LOCK)
        keep = ("bet_id", "hound_id", "side", "price", "best_price", "selection")
        norm = lambda p: [{k: r[k] for k in keep} for r in eng.read_ledger(p)]
        self.assertEqual(norm(a), norm(b))


class LedgerChain(EngineCase):
    def test_rows_are_hash_chained_and_verify(self):
        self.run_at(AT_LOCK, [hound(), hound("u-2", side_rule="favourite", price_min=-150,
                                              price_max=150)])
        rows = eng.read_ledger(self.ledger)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1]["prev_hash"], rows[0]["row_hash"])
        result = eng.verify_ledger(self.ledger)
        self.assertTrue(result.ok)
        self.assertEqual(result.rows_checked, 2)

    def test_an_edited_row_breaks_the_chain_and_names_the_line(self):
        self.run_at(AT_LOCK, [hound(), hound("u-2", side_rule="favourite", price_min=-150,
                                              price_max=150)])
        text = Path(self.ledger).read_text(encoding="utf-8").splitlines()
        row = json.loads(text[0])
        row["price"] = 999
        text[0] = json.dumps(row, sort_keys=True)
        Path(self.ledger).write_text("\n".join(text) + "\n", encoding="utf-8")
        result = eng.verify_ledger(self.ledger)
        self.assertFalse(result.ok)
        self.assertEqual(result.broken_at_line, 1)

    def test_rows_say_paper_only_and_carry_both_prices_and_provenance(self):
        self.run_at(AT_LOCK, [hound()])
        bet = self.bets()[0]
        self.assertIs(bet["paper_only"], True)
        self.assertEqual((bet["provenance"], bet["units"]), ("live", 1))
        self.assertGreaterEqual(bet["best_price"], bet["price"])

    def test_replay_mode_backfills_at_each_games_lock_into_a_scratch_ledger(self):
        report = eng.run(DATE, [hound()], standard_rows(), ledger=self.ledger,
                         now=utc("2026-11-01T00:00:00Z"), mode="replay")
        self.assertEqual(report["bets_written"], 1)
        self.assertEqual(self.bets()[0]["provenance"], "replay")
        self.assertEqual(self.bets()[0]["price"], 120)

    def test_ledger_verified_reflects_the_file_and_caches_on_its_stat(self):
        self.run_at(AT_LOCK, [hound()])
        self.assertTrue(eng.ledger_verified(self.ledger))
        text = Path(self.ledger).read_text(encoding="utf-8").replace('"price": 120', '"price": 121')
        Path(self.ledger).write_text(text, encoding="utf-8")
        self.assertFalse(eng.ledger_verified(self.ledger))


class Helpers(unittest.TestCase):
    def test_average_price_across_even_money(self):
        self.assertEqual(eng.average_price([-110, 120]), 105)
        self.assertEqual(eng.average_price([100, 200]), 150)
        self.assertEqual(eng.average_price([-110, -110]), -110)

    def test_best_price_prefers_the_longest(self):
        self.assertEqual(eng.best_price([("b", -110), ("a", 105), ("c", 100)]), (105, "a"))

    def test_auto_dates_are_eastern_today_and_tomorrow(self):
        self.assertEqual(eng.auto_dates(utc("2026-10-21T02:00:00Z")), ["2026-10-20", "2026-10-21"])


if __name__ == "__main__":
    unittest.main()
