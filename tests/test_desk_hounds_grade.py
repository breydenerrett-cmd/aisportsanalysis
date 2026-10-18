"""Grading, and the leaderboard's own reader reading the desk ledger. Offline: the results are injected."""

from __future__ import annotations

import unittest

from src.hounds import ledgers
from src.hounds.desk import cli, ledger, risk, roles
from tests import _desk_hounds_fixtures as H
from tests import analyst_fixtures as F
from tests._desk_hounds_fixtures import Flow


class GradingAndTheReader(Flow):
    def setUp(self):
        super().setUp()
        self.prepare_mlb()
        underdog = lambda p: H.take(p, "moneyline", "NYY", H.just_above_fair(p, "moneyline", "NYY"))
        under = lambda p: H.take(p, "total", "Under 7", H.just_above_fair(p, "total", "Under 7"))
        self.takes = {"head": [underdog, under]}
        self.drive()
        self.assertEqual(self.publish(), 0, self.text)

    def grade(self, results):
        return cli.main(["--root", str(self.root), "grade", "--date", F.DATE], out=self.out.append,
                        now=self.clock(), results=lambda d: results)

    def test_grading_settles_at_both_prices_and_is_idempotent(self):
        self.assertEqual(self.grade(({849835: {"away_score": "5", "home_score": "3"}}, [])), 0)
        graded = [r for r in ledger.rows(self.root) if r["kind"] == ledger.KIND_GRADED]
        by = {r["market"]: r for r in graded}
        ml = by["moneyline"]
        opt = self.mlb_game().packet["markets"]["moneyline"]["options"][1]
        self.assertEqual(ml["result"], "win")
        self.assertAlmostEqual(ml["units_best_price"], opt["best"]["price"] / 100, places=2)
        avg = risk.board_average(opt)
        self.assertAlmostEqual(ml["units_average_price"], avg / 100, places=2)
        self.assertEqual(ml["units"], ml["units_best_price"])
        self.assertIsNone(ml["close_price"])
        self.assertIsNone(ml["clv_pts"])
        self.assertEqual(by["total"]["result"], "loss")        # 8 runs against an Under 7
        self.assertEqual(by["total"]["units_best_price"], -1.0)
        before = len(ledger.rows(self.root))
        self.out.clear()
        self.grade(({849835: {"away_score": "5", "home_score": "3"}}, []))
        self.assertEqual(len(ledger.rows(self.root)), before)
        self.assertTrue(ledger.verify(self.root).ok)

    def test_a_game_with_no_result_stays_ungraded_never_a_loss(self):
        self.grade(({}, []))
        self.assertEqual([r for r in ledger.rows(self.root) if r["kind"] == ledger.KIND_GRADED], [])
        self.assertIn("still waiting", self.text)

    def test_the_leaderboards_own_reader_reads_the_desk_ledger(self):
        self.grade(({849835: {"away_score": "5", "home_score": "3"}}, []))
        bets, defs = ledgers.pack_ledger_rows(ledger.path(self.root))
        self.assertEqual(set(defs), {h["id"] for h in roles.HOUNDS})
        self.assertEqual({d["category"] for d in defs.values()}, {"ai-desk", "persona"})
        self.assertEqual(len(bets), 2)
        ml = next(b for b in bets if b.market_key == "h2h")
        opt = self.mlb_game().packet["markets"]["moneyline"]["options"][1]
        self.assertEqual((ml.hound_id, ml.side, ml.price, ml.price_average, ml.who_decided, ml.segment,
                          ml.result, ml.event_id),
                         ("desk_ai", "away", opt["best"]["price"], risk.board_average(opt), "model",
                          "forward", "win", "evt-nyy-tb"))
        self.assertAlmostEqual(ml.units, opt["best"]["price"] / 100, places=2)
        total = next(b for b in bets if b.market_key == "totals")
        self.assertEqual((total.side, total.line, total.result), ("under", "7.0", "loss"))
        self.assertTrue(all(b.decision_utc and b.decision_utc < b.start_utc for b in bets))


if __name__ == "__main__":
    unittest.main()
