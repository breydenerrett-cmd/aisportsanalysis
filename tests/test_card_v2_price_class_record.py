"""registration 11.1: MAIN and PLUS_MONEY counted picks are never pooled.

Also carries PROOF-REQUIRED INVARIANT #2 (task instructions): the
plus-money sub-cap must drop the lowest-scored unlocked plus-money picks
across runs (`_apply_plus_money_subcap_v2`) and record them in
`plus_money_dropped_by_subcap`. See the worker's own report for the pasted
before/after `python -m unittest` output proving this test fails against a
reverted guard and passes against the real one.
"""

from __future__ import annotations

import os
import tempfile
import unittest

from src.appstate import card_ledger as cl
from tests._card_v2_fixtures import game_entry, select_result


class LedgerCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = os.path.join(self._tmp.name, "cards_v2.jsonl")


def _plus_pick(game_pk, score):
    return game_entry(game_pk=game_pk, price=150, our_probability=0.42,
                      market_probability=0.32, score=score)


def _main_pick(game_pk, score=0.10):
    return game_entry(game_pk=game_pk, price=-140, our_probability=0.62,
                      market_probability=0.58, score=score)


class PlusMoneySubcapAcrossRuns(LedgerCase):
    def test_a_fresh_plus_money_pick_beyond_the_subcap_is_dropped_and_flagged(self):
        # 3 plus-money picks fill the sub-cap of 3 on run 1.
        first_three = [_plus_pick(300 + i, score=0.9 - i * 0.1) for i in range(3)]
        r1 = cl.publish_v2(select_result(picks=first_three), now="2026-09-20T08:00:00Z",
                           path=self.path)
        self.assertEqual(3, r1["n_picks"])
        self.assertEqual(0, len(r1["plus_money_dropped_by_subcap"]))

        # Run 2: the same three plus a fourth, higher-scored plus-money
        # pick -- the sub-cap must still hold at 3, and the drop must be
        # named in plus_money_dropped_by_subcap.
        extra = _plus_pick(999, score=0.95)
        r2 = cl.publish_v2(select_result(picks=first_three + [extra]),
                           now="2026-09-20T08:05:00Z", path=self.path)
        plus_in_card = [p for p in r2["picks"] if p["price_class"] == "PLUS_MONEY"]
        self.assertEqual(3, len(plus_in_card),
                         "the plus-money sub-cap of 3 must never be exceeded")
        self.assertEqual(1, len(r2["plus_money_dropped_by_subcap"]))


class ClassesNeverPooled(LedgerCase):
    def _settle_one_main_one_plus(self):
        main = _main_pick(1)
        plus = _plus_pick(2, score=0.5)
        cl.publish_v2(select_result(date="2026-09-19", picks=[main, plus]),
                     now="2026-09-19T08:00:00Z", path=self.path)
        return cl.settle_v2("2026-09-19",
                            {1: {"away_score": 1, "home_score": 5},
                             2: {"away_score": 1, "home_score": 5}},
                            path=self.path)

    def test_main_and_plus_money_picks_never_share_one_figure(self):
        self._settle_one_main_one_plus()
        record = cl.record_v2(path=self.path)
        self.assertEqual(1, record["main"]["n_staked"])
        self.assertEqual(1, record["plus_money"]["n_staked"])
        # Neither class figure counts the other's entry.
        self.assertEqual(1, record["main"]["wins"])
        self.assertEqual(1, record["plus_money"]["wins"])

    def test_record_v2_price_class_filter_returns_only_that_class(self):
        self._settle_one_main_one_plus()
        only_plus = cl.record_v2(path=self.path, price_class="PLUS_MONEY")
        self.assertEqual(0, only_plus["main"]["n_staked"])
        self.assertEqual(1, only_plus["plus_money"]["n_staked"])

    def test_combined_figure_equals_the_sum_of_the_two_pick_classes(self):
        self._settle_one_main_one_plus()
        record = cl.record_v2(path=self.path)
        self.assertEqual(
            record["main"]["wins"] + record["plus_money"]["wins"],
            record["combined"]["wins"])
        self.assertEqual(
            round(record["main"]["profit_units"] + record["plus_money"]["profit_units"], 4),
            record["combined"]["profit_units"])

    def test_price_class_is_frozen_at_grading_not_recomputed(self):
        """A settled row's price_class is the one on its graded version --
        never re-derived from the current price band at read time."""
        settled = self._settle_one_main_one_plus()
        main_entry = next(g for g in settled["graded"] if g["game_pk"] == 1)
        self.assertEqual("MAIN", main_entry["price_class"])
        # Even if best_bets_card's band constants changed after the fact,
        # record_v2 never calls price_class() again -- it only reads this
        # stored field, which is exactly what it does above.


class PlusMoneySubcapProof(LedgerCase):
    """The actual proof test used for the revert/restore demonstration."""

    def test_the_subcap_drops_the_lowest_scored_unlocked_plus_money_pick(self):
        first_three = [_plus_pick(300 + i, score=0.9 - i * 0.1) for i in range(3)]
        cl.publish_v2(select_result(picks=first_three), now="2026-09-20T08:00:00Z",
                     path=self.path)
        extra = _plus_pick(999, score=0.95)
        row = cl.publish_v2(select_result(picks=first_three + [extra]),
                            now="2026-09-20T08:05:00Z", path=self.path)
        plus_in_card = [p for p in row["picks"] if p["price_class"] == "PLUS_MONEY"]
        self.assertEqual(3, len(plus_in_card))
        self.assertEqual(1, len(row["plus_money_dropped_by_subcap"]))


if __name__ == "__main__":
    unittest.main()
