"""House pack settlement: grades, pending makeup for a postponed game, voids, CLV, the clustered CI."""

from __future__ import annotations

import os
import tempfile
import unittest
from datetime import timedelta

from src.hounds import pack_run, pack_settle
from src.hounds.pack import base
from src.ledger.chain import HashChainLedger
from tests.test_house_pack_hounds import START, basic_stores, game_rows, mlb_game


class GradeTests(unittest.TestCase):
    def test_grade_score(self):
        g = pack_settle.grade_score
        self.assertEqual(g("moneyline", "home", None, 2, 3), "WIN")
        self.assertEqual(g("moneyline", "away", None, 2, 3), "LOSS")
        self.assertEqual(g("spread", "home", -1.5, 2, 3), "LOSS")       # home -1.5 wins by one
        self.assertEqual(g("spread", "away", -1.5, 2, 3), "WIN")
        self.assertEqual(g("spread", "home", -3.0, 17, 20), "PUSH")
        self.assertEqual(g("total", "over", 8.5, 4, 5), "WIN")
        self.assertEqual(g("total", "under", 9.0, 4, 5), "PUSH")

    def test_units(self):
        self.assertEqual(base.units_for("WIN", 150), 1.5)
        self.assertEqual(base.units_for("WIN", -125, 2.0), 1.6)
        self.assertEqual(base.units_for("LOSS", -125, 0.5), -0.5)
        self.assertEqual(base.units_for("VOID", None), 0.0)

    def test_clustered_ci(self):
        mean, lo, hi, g = pack_settle.clustered_ci([("d1", 1.0), ("d1", 3.0), ("d2", -1.0), ("d3", 1.0)])
        self.assertAlmostEqual(mean, 1.0)
        self.assertEqual(g, 3)
        self.assertLess(lo, mean)
        self.assertGreater(hi, mean)
        self.assertEqual(pack_settle.clustered_ci([("d1", 1.0)])[1], None)


class SettleTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = os.path.join(self._tmp.name, "hounds.jsonl")
        self.st = basic_stores()
        pack_run.run(self.st, ["2026-09-20"], replay=True, now=START + timedelta(hours=5), path=self.path)
        self.bets = [r for r in HashChainLedger(self.path).read() if r["kind"] == "hound_bet"]
        self.assertTrue(self.bets)

    def graded(self):
        return [r for r in HashChainLedger(self.path).read() if r["kind"] == "hound_graded"]

    def test_postponed_game_is_pending_then_void(self):
        c = pack_settle.settle(self.st, now=START + timedelta(days=1), path=self.path)
        self.assertEqual(c["graded"], 0)
        self.assertEqual(c["pending"], len(self.bets))
        # the makeup is played two days later under the same game_pk: VOID, not graded on its score
        self.st.mlb_games.append(dict(mlb_game(900001, "2026-09-22", "NYY", "BOS", 1, 9),
                                      start_utc="2026-09-22T23:05:00Z"))
        pack_settle.settle(self.st, now=START + timedelta(days=3), path=self.path)
        g = self.graded()
        self.assertEqual(len(g), len(self.bets))
        self.assertTrue(all(r["result"] == "VOID" and r["units_average_price"] == 0.0 for r in g))
        self.assertTrue(pack_run.verify(self.path)[0])

    def test_no_result_after_four_days_is_void(self):
        pack_settle.settle(self.st, now=START + timedelta(days=4, minutes=1), path=self.path)
        self.assertTrue(all(r["result"] == "VOID" for r in self.graded()))

    def test_final_grades_with_units_and_clv_and_is_idempotent(self):
        self.st.mlb_games.append(mlb_game(900001, "2026-09-20", "NYY", "BOS", 7, 2))
        pack_settle.settle(self.st, now=START + timedelta(hours=5), path=self.path)
        g = {(r["hound_id"], r["market"]): r for r in self.graded()}
        self.assertEqual(len(g), len(self.bets))
        for bet in self.bets:
            r = g[(bet["hound_id"], bet["market"])]
            self.assertIn(r["result"], ("WIN", "LOSS", "PUSH"))
            self.assertEqual(r["units_average_price"], base.units_for(r["result"], bet["price_average"], bet["stake"]))
            # the close is the last capture before the start: the same -130/+110 board as the lock
            self.assertIsNotNone(r["clv_pts"])
        ml = [r for r in self.graded() if r["market"] == "moneyline" and r["side"] == "away"]
        self.assertTrue(ml and all(r["result"] == "WIN" for r in ml))
        again = pack_settle.settle(self.st, now=START + timedelta(hours=6), path=self.path)
        self.assertEqual(again["graded"], 0)

    def test_unresolved_is_replaced_when_the_score_arrives(self):
        self.st.mlb_games.append(mlb_game(900001, "2026-09-20", "NYY", "BOS", None, None))
        pack_settle.settle(self.st, now=START + timedelta(hours=5), path=self.path)
        self.assertTrue(all(r["result"] == "UNRESOLVED" for r in self.graded()))
        self.st.mlb_games[-1] = mlb_game(900001, "2026-09-20", "NYY", "BOS", 3, 2)
        pack_settle.settle(self.st, now=START + timedelta(hours=6), path=self.path)
        summ = {s["hound_id"]: s for s in pack_settle.summary(HashChainLedger(self.path).read())}
        for bet in self.bets:
            rec = summ[bet["hound_id"]]["record"]
            self.assertEqual(rec["U"] + rec["pending"], 0)


if __name__ == "__main__":
    unittest.main()
