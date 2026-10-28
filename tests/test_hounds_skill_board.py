"""The leaderboard ranks by skill, not luck (owner ask 2026-10-28).

Coin-Flip Collie sat on top at +4.9u over 13 bets. The default order is now "Beats the close": the average points a hound
beat the closing price by, shrunk toward zero for small samples (mean x n / (n + 30)), units as the tiebreak, hounds with no
measurable close last. "Hot streak" (units) and "Most bets" stay one click away. Each row says in plain words what it beat
and how early it is, and a random control wears a tag saying what it is for.
"""
from __future__ import annotations

import copy
import json
import unittest

from tests import hounds_web_fixtures as F
from tests.hounds_web_runner import HAS_NODE, run_js, run_page
from tests.test_hounds_board_pages import mk, routes

ROW = "[data-hook='hounds-list'] .hd-tr"


def clv(n, mean):
    return {"n": n, "mean_pts": mean, "ci_low": mean - 1, "ci_high": mean + 1}


def board(hs):
    """A leaderboard payload from hand-made hounds (all ranked: 10+ settled bets)."""
    p = copy.deepcopy(F.leaderboard())
    p["hounds"] = hs
    return p


def field():
    return [
        mk("luck", "Lucky Six", bets=30, units=9.0, clv=clv(6, 3.0)),                    # shrunk 3.0 * 6/36  = 0.50
        mk("steady", "Steady Sixty-Seven", bets=67, units=1.0, clv=clv(67, 1.0)),        # shrunk 1.0 * 67/97 = 0.69
        mk("coin", "Coin-Flip Collie", bets=13, units=4.9, category="random", clv=clv(13, -0.2)),
        mk("worse", "Worse Prices", bets=80, units=-2.0, clv=clv(80, -1.5)),
        mk("blank", "No Close", bets=40, units=20.0, clv=None),
    ]


@unittest.skipUnless(HAS_NODE, "node not installed")
class TheScore(unittest.TestCase):
    def js(self, body):
        return run_js('import * as B from "./hounds-board.js";\n' + body)

    def test_shrinkage_puts_a_six_bet_streak_below_a_steady_sixty_seven(self):
        got = self.js(f"console.log(JSON.stringify(B.sortHounds({json.dumps(field())}, 'skill').map(h => h.id)));")
        self.assertEqual(got, ["steady", "luck", "coin", "worse", "blank"])     # no close = last, whatever its units

    def test_the_constant_and_the_score(self):
        got = self.js("console.log(JSON.stringify([B.SKILL_SHRINK_K, B.skillScore({clv:{n:30,mean_pts:2}}), B.skillScore({clv:null})]));")
        self.assertEqual(got, [30, 1, None])

    def test_units_break_a_tie(self):
        a, b = mk("a", "A", units=1.0, clv=clv(30, 1.0)), mk("b", "B", units=5.0, clv=clv(30, 1.0))
        got = self.js(f"console.log(JSON.stringify(B.sortHounds({json.dumps([a, b])}, 'skill').map(h => h.id)));")
        self.assertEqual(got, ["b", "a"])

    def test_copy_rules(self):
        def f(expr):
            return self.js(f"console.log(JSON.stringify({expr}));")
        self.assertEqual(f("B.skillLine({clv:{n:67,mean_pts:1.04}})"), "Beat the closing price by 1.0 pts over 67 bets")
        self.assertEqual(f("B.skillLine({clv:{n:80,mean_pts:-1.5}})"), "Got worse prices than the close by 1.5 pts over 80 bets")
        self.assertEqual(f("B.skillLine({clv:{n:1,mean_pts:0.4}})"), "Beat the closing price by 0.4 pts over 1 bet")
        self.assertIsNone(f("B.skillLine({clv:null})"))
        self.assertEqual(f("B.luckMeter({clv:{n:6,mean_pts:3}})"), "Too early: 6 of 150 bets")
        self.assertEqual(f("B.luckMeter({clv:{n:150,mean_pts:3}})"), "")
        self.assertEqual(f("B.luckMeter({clv:null})"), "Too early: 0 of 150 bets")
        self.assertTrue(f("B.isRandomPicker({category:'random'})"))
        self.assertFalse(f("B.isRandomPicker({category:'stats'})"))


@unittest.skipUnless(HAS_NODE, "node not installed")
class ThePage(unittest.TestCase):
    def page(self, **kw):
        r = routes()
        r["/hounds"] = (200, board(field()))
        return run_page("hounds", routes=r, **kw)

    def test_default_is_beats_the_close_and_the_toggle_reorders(self):
        def cap():
            return dict(name="ids", sel=ROW, mode="attrs", attr="data-hound")
        out = self.page(queries=[cap(), dict(name="pressed", sel="[data-hook='hounds-sortmode'] [aria-pressed='true']", mode="texts")],
                        actions=[dict(do="click", sel="[data-sortmode='units']", label="hot", capture=[cap()]),
                                 dict(do="click", sel="[data-sortmode='bets']", label="bets", capture=[cap()]),
                                 dict(do="click", sel="[data-sortmode='skill']", label="skill", capture=[cap()])])
        self.assertEqual(out["final"]["ids"][:2], ["steady", "luck"])
        self.assertEqual(out["captures"]["hot"]["ids"][0], "blank")             # 20 units
        self.assertEqual(out["captures"]["bets"]["ids"][0], "worse")            # 80 bets
        self.assertEqual(out["captures"]["skill"]["ids"], ["steady", "luck", "coin", "worse", "blank"])

    def test_rows_carry_the_plain_line_the_luck_meter_and_the_random_tag(self):
        out = self.page(queries=[
            dict(name="lines", sel=f"{ROW} [data-hook='row-skill-line']", mode="texts"),
            dict(name="luck", sel=f"{ROW} [data-hook='row-luck']", mode="texts"),
            dict(name="tags", sel=f"{ROW} [data-hook='row-random']", mode="texts"),
            dict(name="explain", sel="[data-hook='skill-explainer']", mode="text")])
        f = out["final"]
        self.assertIn("Beat the closing price by 1.0 pts over 67 bets", f["lines"])
        self.assertIn("Got worse prices than the close by 1.5 pts over 80 bets", f["lines"])
        self.assertIn("Too early: 6 of 150 bets", " ".join(f["luck"]))
        self.assertEqual(f["tags"], ["random picker — here to show what luck looks like"])
        self.assertIn("closing price", f["explain"])
        blob = " ".join(f["lines"] + f["luck"] + f["tags"] + [f["explain"]]).lower()
        for banned in ("beta", "nothing cleared the bar", "profit", "guarantee"):
            self.assertNotIn(banned, blob)
        self.assertNotRegex(blob, r"\bnew\b|\bdog\b")


if __name__ == "__main__":
    unittest.main()
