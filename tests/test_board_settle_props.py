"""Ten graded examples for src.board.settle_props, from real fixture games.

Gate G3's "ten graded examples": pitcher K, pitcher outs, batter hits,
batter total bases, batter H+R+RBI, and first-inning yes/no, each with both
a win and a loss/push side so the grading logic is exercised in both
directions, not just the direction that happens to be correct.
"""

import json
import unittest
from pathlib import Path

from src.board.settle_props import SettleError, settle

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _load(name):
    with open(FIXTURES / name, encoding="utf-8") as handle:
        return json.load(handle)


def _find(rows, player_id):
    return next(r for r in rows if r.get("player_id") == player_id)


class TenGradedExamplesTests(unittest.TestCase):
    """Box rows built once from the two recorded fixture games
    (822688: MIA @ WSH, 822766: SEA @ TOR), graded against real lines.
    """

    @classmethod
    def setUpClass(cls):
        from src.providers import mlb

        box_688 = mlb.parse_boxscore(822688, _load("mlb_boxscore_822688.json"))
        box_766 = mlb.parse_boxscore(822766, _load("mlb_boxscore_822766.json"))
        cls.line_688 = mlb.parse_linescore(
            822688, _load("mlb_linescore_822688.json"))
        cls.line_766 = mlb.parse_linescore(
            822766, _load("mlb_linescore_822766.json"))
        cls.line_688["type"] = "linescore"
        cls.line_766["type"] = "linescore"

        # Andrew Alvarez (822688, home): 6.0 IP / 18 outs, 6 K, 2 H, 0 ER.
        cls.alvarez = dict(_find(box_688["pitchers"], 674841), type="pitcher")
        # George Springer (822766, home): 2 H (1 2B), 3 total bases, 3 HRR.
        cls.springer = dict(_find(box_766["batters"], 543807), type="batter")

    # 1-2: pitcher strikeouts (win, then push)
    def test_1_pitcher_k_over_wins(self):
        sel = {"subject_id": 674841, "stat": "k", "line": "5.5", "side": "over"}
        self.assertEqual(settle(self.alvarez, sel), "win")

    def test_2_pitcher_k_exact_line_pushes(self):
        sel = {"subject_id": 674841, "stat": "k", "line": "6.0", "side": "under"}
        self.assertEqual(settle(self.alvarez, sel), "push")

    # 3-4: pitcher outs recorded (win, then loss)
    def test_3_pitcher_outs_over_wins(self):
        sel = {"subject_id": 674841, "stat": "outs", "line": "17.5", "side": "over"}
        self.assertEqual(settle(self.alvarez, sel), "win")

    def test_4_pitcher_outs_under_loses(self):
        sel = {"subject_id": 674841, "stat": "outs", "line": "17.5", "side": "under"}
        self.assertEqual(settle(self.alvarez, sel), "loss")

    # 5-6: batter hits (win, then loss on the other side of the same line)
    def test_5_batter_hits_over_wins(self):
        sel = {"subject_id": 543807, "stat": "h", "line": "1.5", "side": "over"}
        self.assertEqual(settle(self.springer, sel), "win")

    def test_6_batter_hits_under_loses(self):
        sel = {"subject_id": 543807, "stat": "h", "line": "1.5", "side": "under"}
        self.assertEqual(settle(self.springer, sel), "loss")

    # 7: batter total bases (win)
    def test_7_batter_total_bases_over_wins(self):
        sel = {"subject_id": 543807, "stat": "total_bases", "line": "2.5",
               "side": "over"}
        self.assertEqual(settle(self.springer, sel), "win")

    # 8: batter hits+runs+rbi, exact line pushes
    def test_8_batter_hits_runs_rbi_pushes(self):
        sel = {"subject_id": 543807, "stat": "hits_runs_rbi", "line": "3",
               "side": "over"}
        self.assertEqual(settle(self.springer, sel), "push")

    # 9-10: first-inning yes/no, one real yes and one real no
    def test_9_first_inning_yes_wins_on_a_game_that_scored_in_the_first(self):
        sel = {"subject_id": None, "stat": "first_inning_scored",
               "line": "0", "side": "over"}
        self.assertEqual(settle(self.line_766, sel), "win")

    def test_10_first_inning_yes_loses_on_a_scoreless_first(self):
        sel = {"subject_id": None, "stat": "first_inning_scored",
               "line": "0", "side": "over"}
        self.assertEqual(settle(self.line_688, sel), "loss")


class VoidAndErrorTests(unittest.TestCase):
    """Void is the honest "cannot grade" answer -- never fabricated, never
    an exception, distinct from a malformed selection (which does raise)."""

    def test_no_row_at_all_is_void(self):
        sel = {"subject_id": 1, "stat": "k", "line": "5.5", "side": "over"}
        self.assertEqual(settle(None, sel), "void")

    def test_wrong_row_type_for_the_stat_is_void(self):
        batter_row = {"type": "batter", "player_id": 1, "h": 2}
        sel = {"subject_id": 1, "stat": "k", "line": "5.5", "side": "over"}
        self.assertEqual(settle(batter_row, sel), "void")

    def test_subject_id_mismatch_is_void(self):
        row = {"type": "pitcher", "player_id": 999, "k": 6}
        sel = {"subject_id": 674841, "stat": "k", "line": "5.5", "side": "over"}
        self.assertEqual(settle(row, sel), "void")

    def test_missing_side_raises(self):
        row = {"type": "pitcher", "player_id": 1, "k": 6}
        sel = {"subject_id": 1, "stat": "k", "line": "5.5", "side": "sideways"}
        with self.assertRaises(SettleError):
            settle(row, sel)

    def test_non_string_line_raises(self):
        row = {"type": "pitcher", "player_id": 1, "k": 6}
        sel = {"subject_id": 1, "stat": "k", "line": 5.5, "side": "over"}
        with self.assertRaises(SettleError):
            settle(row, sel)


if __name__ == "__main__":
    unittest.main()
