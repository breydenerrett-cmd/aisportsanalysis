"""Wiring test: settle_props' rules actually live in settle's registry.

Two things this file exists to catch:

1. Importing src.board (the package, not either submodule directly) must
   register every prop and first-inning settlement rule so that any code
   walking MARKET_CATALOGUE and looking up SETTLEMENT_RULES[spec.settlement_rule]
   finds a real callable -- never `collection_blocked` for a market that
   claims otherwise, and never a KeyError.
2. Going through that registry has to produce the exact same grade as
   calling src.board.settle_props.settle directly -- registration must not
   be a second, silently-diverging implementation of the same rule.
"""

import json
import unittest
from pathlib import Path

import src.board  # noqa: F401  (import-time side effect: registers prop rules)
from src.board.ids import MARKET_CATALOGUE
from src.board.settle import COLLECTION_BLOCKED, SETTLEMENT_RULES
from src.board.settle_props import settle as settle_props_settle

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _load(name):
    with open(FIXTURES / name, encoding="utf-8") as handle:
        return json.load(handle)


def _find(rows, player_id):
    return next(r for r in rows if r.get("player_id") == player_id)


class CatalogueResolvesToCallableTests(unittest.TestCase):
    def test_every_declared_rule_resolves_to_a_real_callable(self):
        """Every catalogue entry that is not deliberately blocked must
        resolve, through the shared registry, to something callable."""
        for key, spec in MARKET_CATALOGUE.items():
            rule = spec.settlement_rule
            self.assertIn(
                rule, SETTLEMENT_RULES,
                msg=f"{key} points at unregistered rule {rule!r}",
            )
            resolved = SETTLEMENT_RULES[rule]
            if resolved == COLLECTION_BLOCKED:
                self.assertEqual(
                    key, "same_game_parlay",
                    msg=f"{key} unexpectedly still collection_blocked",
                )
                continue
            self.assertTrue(
                callable(resolved),
                msg=f"{key} -> {rule!r} does not resolve to a callable",
            )

    def test_prop_markets_are_no_longer_collection_blocked(self):
        prop_keys = [
            key for key, spec in MARKET_CATALOGUE.items()
            if spec.subject_kind in ("pitcher", "batter")
        ]
        self.assertTrue(prop_keys)
        for key in prop_keys:
            spec = MARKET_CATALOGUE[key]
            self.assertNotEqual(spec.settlement_rule, COLLECTION_BLOCKED)
            self.assertEqual(spec.status, "DECLARED")
            self.assertTrue(callable(SETTLEMENT_RULES[spec.settlement_rule]))


class TenGradedExamplesThroughTheRegistryTests(unittest.TestCase):
    """Re-run the graded examples from test_board_settle_props.py through
    SETTLEMENT_RULES[market_key](row, selection) and check the grade matches
    calling settle_props.settle directly -- the registry path must not
    diverge from the pure function it wraps."""

    @classmethod
    def setUpClass(cls):
        from src.providers import mlb

        box_688 = mlb.parse_boxscore(822688, _load("mlb_boxscore_822688.json"))
        box_766 = mlb.parse_boxscore(822766, _load("mlb_boxscore_822766.json"))
        cls.alvarez = dict(_find(box_688["pitchers"], 674841), type="pitcher")
        cls.springer = dict(_find(box_766["batters"], 543807), type="batter")

    def _assert_registry_matches_direct(self, market_key, row, selection):
        spec = MARKET_CATALOGUE[market_key]
        registry_fn = SETTLEMENT_RULES[spec.settlement_rule]
        direct = settle_props_settle(row, selection)
        via_registry = registry_fn(row, selection)
        self.assertEqual(via_registry, direct)
        return via_registry

    # 1-2: pitcher strikeouts (win, then push)
    def test_1_pitcher_k_over_wins(self):
        sel = {"subject_id": 674841, "stat": "k", "line": "5.5", "side": "over"}
        grade = self._assert_registry_matches_direct(
            "pitcher_strikeouts", self.alvarez, sel)
        self.assertEqual(grade, "win")

    def test_2_pitcher_k_exact_line_pushes(self):
        sel = {"subject_id": 674841, "stat": "k", "line": "6.0", "side": "under"}
        grade = self._assert_registry_matches_direct(
            "pitcher_strikeouts", self.alvarez, sel)
        self.assertEqual(grade, "push")

    # 3-4: pitcher outs recorded (win, then loss)
    def test_3_pitcher_outs_over_wins(self):
        sel = {"subject_id": 674841, "stat": "outs", "line": "17.5", "side": "over"}
        grade = self._assert_registry_matches_direct(
            "pitcher_outs", self.alvarez, sel)
        self.assertEqual(grade, "win")

    def test_4_pitcher_outs_under_loses(self):
        sel = {"subject_id": 674841, "stat": "outs", "line": "17.5", "side": "under"}
        grade = self._assert_registry_matches_direct(
            "pitcher_outs", self.alvarez, sel)
        self.assertEqual(grade, "loss")

    # 5-6: batter hits (win, then loss on the other side of the same line)
    def test_5_batter_hits_over_wins(self):
        sel = {"subject_id": 543807, "stat": "h", "line": "1.5", "side": "over"}
        grade = self._assert_registry_matches_direct(
            "batter_hits", self.springer, sel)
        self.assertEqual(grade, "win")

    def test_6_batter_hits_under_loses(self):
        sel = {"subject_id": 543807, "stat": "h", "line": "1.5", "side": "under"}
        grade = self._assert_registry_matches_direct(
            "batter_hits", self.springer, sel)
        self.assertEqual(grade, "loss")

    # 7: batter total bases (win)
    def test_7_batter_total_bases_over_wins(self):
        sel = {"subject_id": 543807, "stat": "total_bases", "line": "2.5",
               "side": "over"}
        grade = self._assert_registry_matches_direct(
            "batter_total_bases", self.springer, sel)
        self.assertEqual(grade, "win")

    # 8: batter hits+runs+rbi, exact line pushes
    def test_8_batter_hits_runs_rbi_pushes(self):
        sel = {"subject_id": 543807, "stat": "hits_runs_rbi", "line": "3",
               "side": "over"}
        grade = self._assert_registry_matches_direct(
            "batter_hits_runs_rbis", self.springer, sel)
        self.assertEqual(grade, "push")

    # 9-10: first-inning yes/no -- graded directly against the linescore row
    # via settle_props.settle (the box-row grading path), matching
    # test_board_settle_props.py exactly; the first_inning_* MARKET_CATALOGUE
    # entries settle a different (GameResult-shaped) input in settle.py and
    # are covered by test_board_settle.py's catalogue-coverage test instead.
    def test_9_first_inning_yes_wins_on_a_game_that_scored_in_the_first(self):
        from src.providers import mlb

        line_766 = mlb.parse_linescore(822766, _load("mlb_linescore_822766.json"))
        line_766["type"] = "linescore"
        sel = {"subject_id": None, "stat": "first_inning_scored",
               "line": "0", "side": "over"}
        self.assertEqual(settle_props_settle(line_766, sel), "win")

    def test_10_first_inning_yes_loses_on_a_scoreless_first(self):
        from src.providers import mlb

        line_688 = mlb.parse_linescore(822688, _load("mlb_linescore_822688.json"))
        line_688["type"] = "linescore"
        sel = {"subject_id": None, "stat": "first_inning_scored",
               "line": "0", "side": "over"}
        self.assertEqual(settle_props_settle(line_688, sel), "loss")


if __name__ == "__main__":
    unittest.main()
