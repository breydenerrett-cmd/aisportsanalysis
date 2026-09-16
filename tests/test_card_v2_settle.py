"""settle_v2 grades every shown entry exactly once, carrying entry_class and
price_class, and record_v2 reports main/plus-money/fills apart.
"""

from __future__ import annotations

import os
import tempfile
import unittest

from src.appstate import card_ledger as cl
from tests._card_v2_fixtures import game_entry, select_result, result_row


class LedgerCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = os.path.join(self._tmp.name, "cards_v2.jsonl")


class GradesEveryEntryOnce(LedgerCase):
    def test_locked_picks_and_locked_fills_are_both_graded(self):
        fp = "2026-09-20T23:00:00Z"
        t_minus_4h = "2026-09-20T19:00:00Z"
        pick = game_entry(game_pk=1, price=-140, first_pitch_utc=fp, observed_utc=t_minus_4h)
        fill = game_entry(game_pk=2, price=-140, entry_class="fill",
                          failed_gates=["G7_VALUE"], first_pitch_utc=fp, observed_utc=t_minus_4h)
        row = cl.publish_v2(select_result(picks=[pick], fills=[fill]), now=t_minus_4h,
                            path=self.path)
        self.assertTrue(row["picks"][0]["locked"])
        self.assertTrue(row["fills"][0]["locked"])

        settled = cl.settle_v2("2026-09-20",
                               {1: result_row(1, 5), 2: result_row(1, 5)}, path=self.path)
        game_pks = {g["game_pk"]: g for g in settled["graded"]}
        self.assertEqual("WIN", game_pks[1]["result"])
        self.assertEqual("WIN", game_pks[2]["result"])
        self.assertEqual("pick", game_pks[1]["entry_class"])
        self.assertEqual("fill", game_pks[2]["entry_class"])

    def test_a_provisional_entry_left_without_a_lock_run_is_flagged(self):
        far_out = game_entry(game_pk=3, price=-140, first_pitch_utc="2026-09-25T23:00:00Z")
        cl.publish_v2(select_result(date="2026-09-24", picks=[far_out]),
                     now="2026-09-24T08:00:00Z", path=self.path)
        settled = cl.settle_v2("2026-09-24", {3: result_row(1, 5)}, path=self.path)
        self.assertTrue(settled["graded_without_lock_run"])
        self.assertTrue(settled["graded"][0]["graded_without_lock_run"])

    def test_a_locked_entry_is_never_flagged_graded_without_lock_run(self):
        fp = "2026-09-20T23:00:00Z"
        pick = game_entry(game_pk=1, price=-140, first_pitch_utc=fp,
                          observed_utc="2026-09-20T19:00:00Z")
        cl.publish_v2(select_result(picks=[pick]), now="2026-09-20T19:00:00Z", path=self.path)
        settled = cl.settle_v2("2026-09-20", {1: result_row(1, 5)}, path=self.path)
        self.assertFalse(settled["graded"][0]["graded_without_lock_run"])

    def test_every_withdrawn_entry_is_graded_at_its_last_shown_price(self):
        pick = game_entry(game_pk=1, price=-140, observed_utc="2026-09-20T10:00:00Z")
        cl.publish_v2(select_result(picks=[pick]), now="2026-09-20T10:00:00Z", path=self.path)
        failing = game_entry(game_pk=1, price=-140, failed_gates=["G7_VALUE"],
                             observed_utc="2026-09-20T11:00:00Z")
        row = cl.publish_v2(select_result(picks=[failing]), now="2026-09-20T11:00:00Z",
                            path=self.path)
        self.assertEqual(1, len(row["withdrawn"]))

        settled = cl.settle_v2("2026-09-20", {1: result_row(1, 5)}, path=self.path)
        withdrawn_graded = [g for g in settled["graded"] if g.get("withdrawn")]
        self.assertEqual(1, len(withdrawn_graded))
        self.assertEqual(-140, withdrawn_graded[0]["price"])
        self.assertEqual("WIN", withdrawn_graded[0]["result"])

    def test_close_calls_not_shown_are_never_graded(self):
        pick = game_entry(game_pk=1, price=-140)
        row = cl.publish_v2(select_result(picks=[pick],
                                          close_calls_not_shown=[{"game_pk": 999}]),
                            now="2026-09-20T10:00:00Z", path=self.path)
        settled = cl.settle_v2("2026-09-20", {1: result_row(1, 5)}, path=self.path)
        graded_keys = {g.get("game_pk") for g in settled["graded"]}
        self.assertNotIn(999, graded_keys)


class RunLineGrading(LedgerCase):
    def _settle_run_line(self, line, away, home, game_pk=1):
        pick = game_entry(game_pk=game_pk, market="run_line", side="home", line=line,
                          price=-110)
        cl.publish_v2(select_result(date="2026-09-20", picks=[pick]),
                     now="2026-09-20T10:00:00Z", path=self.path)
        settled = cl.settle_v2("2026-09-20", {game_pk: result_row(away, home)}, path=self.path)
        return settled["graded"][0]["result"]

    def test_plus_one_point_five_losing_by_one_covers(self):
        self.assertEqual("WIN", self._settle_run_line(1.5, away=4, home=3))

    def test_plus_one_point_five_losing_by_two_does_not_cover(self):
        self.assertEqual("LOSS", self._settle_run_line(1.5, away=5, home=3))

    def test_minus_one_point_five_winning_by_one_does_not_cover(self):
        self.assertEqual("LOSS", self._settle_run_line(-1.5, away=3, home=4))

    def test_minus_one_point_five_winning_by_two_covers(self):
        self.assertEqual("WIN", self._settle_run_line(-1.5, away=3, home=5))


class PlusMoneyMoneylineGrading(LedgerCase):
    def test_a_plus_money_moneyline_pick_grades_and_pays_at_its_own_price(self):
        pick = game_entry(game_pk=1, market="moneyline", price=150,
                          our_probability=0.42, market_probability=0.32)
        cl.publish_v2(select_result(picks=[pick]), now="2026-09-20T10:00:00Z", path=self.path)
        settled = cl.settle_v2("2026-09-20", {1: result_row(1, 5)}, path=self.path)
        graded = settled["graded"][0]
        self.assertEqual("WIN", graded["result"])
        self.assertEqual("PLUS_MONEY", graded["price_class"])
        self.assertAlmostEqual(1.5, graded["profit_units"])


class RecordFourFigures(LedgerCase):
    def test_record_v2_separates_main_plus_money_fills_and_combined(self):
        main = game_entry(game_pk=1, price=-140, our_probability=0.62, market_probability=0.58)
        plus = game_entry(game_pk=2, price=150, our_probability=0.42, market_probability=0.32)
        fill = game_entry(game_pk=3, price=-140, entry_class="fill",
                          failed_gates=["G7_VALUE"])
        cl.publish_v2(select_result(picks=[main, plus], fills=[fill]),
                     now="2026-09-20T10:00:00Z", path=self.path)
        cl.settle_v2("2026-09-20", {
            1: result_row(1, 5), 2: result_row(1, 5), 3: result_row(1, 5)},
            path=self.path)

        record = cl.record_v2(path=self.path)
        self.assertEqual(1, record["main"]["n_staked"])
        self.assertEqual(1, record["plus_money"]["n_staked"])
        self.assertEqual(1, record["fills"]["n_staked"])
        self.assertEqual(2, record["combined"]["n_staked"])


if __name__ == "__main__":
    unittest.main()
