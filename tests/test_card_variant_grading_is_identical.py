"""T3v: paper arms use the identical grading machinery as A1 -- no shortcut.

Registration 17.6: "grading a paper arm uses identical machinery and no
shortcuts ... freezes its own price from the shared board and never assumes
the published card's price ... paper arms produce fills too, graded and
published, and counted fills stay outside every metric exactly as 11.1
requires."
"""

from __future__ import annotations

import os
import tempfile
import unittest

from src.appstate import card_ledger as cl
from tests._card_v2_fixtures import game_entry, select_result, result_row


class TestGradingIsIdentical(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.a1_path = os.path.join(self._tmp.name, "a1.jsonl")
        self.a3_path = os.path.join(self._tmp.name, "a3.jsonl")
        self.fp = "2026-09-20T23:00:00Z"
        self.t_minus_4h = "2026-09-20T19:00:00Z"

    def test_identical_frozen_pick_settles_to_identical_graded_row(self):
        # Same price on both arms (the arms happened to agree here) --
        # this pins that grading itself carries no per-arm special case.
        pick = game_entry(game_pk=1, price=-140, side="home",
                          first_pitch_utc=self.fp, observed_utc=self.t_minus_4h)
        cl.publish_v2(select_result(picks=[pick]), now=self.t_minus_4h, path=self.a1_path,
                     family_id="F", arm="A1", pool_hash="H", published=True)
        cl.publish_v2(select_result(picks=[dict(pick)]), now=self.t_minus_4h, path=self.a3_path,
                     family_id="F", arm="A3", pool_hash="H", published=False)

        results = {1: result_row(away_score=2, home_score=5)}
        settled_a1 = cl.settle_v2("2026-09-20", results, path=self.a1_path)
        settled_a3 = cl.settle_v2("2026-09-20", results, path=self.a3_path)

        graded_a1 = settled_a1["graded"][0]
        graded_a3 = settled_a3["graded"][0]
        for key in ("result", "profit_units", "price", "entry_class", "price_class"):
            self.assertEqual(graded_a1[key], graded_a3[key])

    def test_paper_arm_freezes_its_own_price_not_a1s(self):
        a1_pick = game_entry(game_pk=1, price=-140, side="home",
                             first_pitch_utc=self.fp, observed_utc=self.t_minus_4h)
        a3_pick = game_entry(game_pk=1, price=-125, side="home",
                             first_pitch_utc=self.fp, observed_utc=self.t_minus_4h)
        cl.publish_v2(select_result(picks=[a1_pick]), now=self.t_minus_4h, path=self.a1_path)
        cl.publish_v2(select_result(picks=[a3_pick]), now=self.t_minus_4h, path=self.a3_path)

        results = {1: result_row(away_score=2, home_score=5)}
        settled_a1 = cl.settle_v2("2026-09-20", results, path=self.a1_path)
        settled_a3 = cl.settle_v2("2026-09-20", results, path=self.a3_path)

        self.assertEqual(settled_a1["graded"][0]["price"], -140)
        self.assertEqual(settled_a3["graded"][0]["price"], -125)
        self.assertNotEqual(
            settled_a1["graded"][0]["profit_units"],
            settled_a3["graded"][0]["profit_units"],
        )

    def test_paper_fill_is_graded_but_excluded_from_every_counted_figure(self):
        fill = game_entry(game_pk=2, price=130, entry_class="fill",
                          failed_gates=["G7_VALUE"],
                          first_pitch_utc=self.fp, observed_utc=self.t_minus_4h)
        cl.publish_v2(select_result(fills=[fill]), now=self.t_minus_4h, path=self.a3_path)
        results = {2: result_row(away_score=1, home_score=6)}
        settled = cl.settle_v2("2026-09-20", results, path=self.a3_path)

        graded_fill = settled["graded"][0]
        self.assertEqual(graded_fill["entry_class"], "fill")
        self.assertIn(graded_fill["result"], (cl.RESULT_WIN, cl.RESULT_LOSS, cl.RESULT_PUSH, cl.RESULT_VOID))

        record = cl.record_v2(path=self.a3_path)
        self.assertEqual(record["main"]["n_staked"], 0)
        self.assertEqual(record["plus_money"]["n_staked"], 0)
        self.assertEqual(record["combined"]["n_staked"], 0)
        self.assertGreaterEqual(record["fills"]["n_staked"], 1)


if __name__ == "__main__":
    unittest.main()
