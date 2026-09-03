"""Settlement rules: every catalogue entry maps to a rule or is blocked;
game-level rules produce correct WIN/LOSS/PUSH/VOID outcomes."""

import unittest

from src.board.ids import MARKET_CATALOGUE
from src.board.settle import (
    COLLECTION_BLOCKED,
    LOSS,
    PUSH,
    SETTLEMENT_RULES,
    VOID,
    WIN,
    GameResult,
    register_rule,
    settle,
)


class CatalogueCoverageTests(unittest.TestCase):
    def test_every_catalogue_entry_has_a_rule_or_is_blocked(self):
        for key, spec in MARKET_CATALOGUE.items():
            self.assertIn(
                spec.settlement_rule, SETTLEMENT_RULES,
                msg=f"{key} points at unregistered rule {spec.settlement_rule!r}",
            )


class H2hSettlementTests(unittest.TestCase):
    def test_home_win(self):
        result = GameResult(home_runs=5, away_runs=3)
        self.assertEqual(settle("h2h", "home", result), WIN)
        self.assertEqual(settle("h2h", "away", result), LOSS)

    def test_away_win(self):
        result = GameResult(home_runs=2, away_runs=6)
        self.assertEqual(settle("h2h", "home", result), LOSS)
        self.assertEqual(settle("h2h", "away", result), WIN)

    def test_tie_is_void(self):
        result = GameResult(home_runs=4, away_runs=4)
        self.assertEqual(settle("h2h", "home", result), VOID)


class SpreadsSettlementTests(unittest.TestCase):
    def test_favorite_covers(self):
        # home wins by 4, giving -1.5 -> adjusted margin +2.5 -> WIN
        result = GameResult(home_runs=6, away_runs=2)
        self.assertEqual(settle("spreads", "home", result, line="-1.5"), WIN)
        self.assertEqual(settle("spreads", "away", result, line="1.5"), LOSS)

    def test_underdog_covers(self):
        result = GameResult(home_runs=3, away_runs=4)  # home lost by 1
        self.assertEqual(settle("spreads", "home", result, line="1.5"), WIN)
        self.assertEqual(settle("spreads", "away", result, line="-1.5"), LOSS)

    def test_push_on_whole_number_line(self):
        result = GameResult(home_runs=5, away_runs=3)  # margin +2
        self.assertEqual(settle("spreads", "home", result, line="-2"), PUSH)
        self.assertEqual(settle("spreads", "away", result, line="2"), PUSH)


class TotalsSettlementTests(unittest.TestCase):
    def test_over(self):
        result = GameResult(home_runs=5, away_runs=5)  # total 10
        self.assertEqual(settle("totals", "over", result, line="8.5"), WIN)
        self.assertEqual(settle("totals", "under", result, line="8.5"), LOSS)

    def test_under(self):
        result = GameResult(home_runs=1, away_runs=1)  # total 2
        self.assertEqual(settle("totals", "under", result, line="8.5"), WIN)

    def test_push(self):
        result = GameResult(home_runs=4, away_runs=4)  # total 8
        self.assertEqual(settle("totals", "over", result, line="8"), PUSH)
        self.assertEqual(settle("totals", "under", result, line="8"), PUSH)


class TeamTotalsSettlementTests(unittest.TestCase):
    def test_home_team_total(self):
        result = GameResult(home_runs=5, away_runs=1)
        self.assertEqual(
            settle("team_totals", "over", result, line="3.5", team="home"), WIN
        )


class FirstFiveSettlementTests(unittest.TestCase):
    def test_h2h_1st_5_void_without_data(self):
        result = GameResult(home_runs=5, away_runs=3)
        self.assertEqual(settle("h2h_1st_5", "home", result), VOID)

    def test_h2h_1st_5_with_data(self):
        result = GameResult(
            home_runs=5, away_runs=3,
            home_runs_through_5=3, away_runs_through_5=1,
        )
        self.assertEqual(settle("h2h_1st_5", "home", result), WIN)
        self.assertEqual(settle("h2h_1st_5", "away", result), LOSS)

    def test_h2h_1st_5_tie_is_push(self):
        result = GameResult(
            home_runs=5, away_runs=5,
            home_runs_through_5=2, away_runs_through_5=2,
        )
        self.assertEqual(settle("h2h_1st_5", "home", result), PUSH)

    def test_totals_1st_5_with_data(self):
        result = GameResult(
            home_runs=6, away_runs=6,
            home_runs_through_5=3, away_runs_through_5=2,
        )
        self.assertEqual(settle("totals_1st_5", "over", result, line="3.5"), WIN)


class FirstInningSettlementTests(unittest.TestCase):
    def test_void_without_data(self):
        result = GameResult(home_runs=5, away_runs=3)
        self.assertEqual(settle("first_inning_run", "yes", result), VOID)

    def test_run_scored(self):
        result = GameResult(
            home_runs=5, away_runs=3,
            home_runs_1st_inning=1, away_runs_1st_inning=0,
        )
        self.assertEqual(settle("first_inning_run", "yes", result), WIN)
        self.assertEqual(settle("first_inning_run", "no", result), LOSS)
        self.assertEqual(settle("first_inning_score_home", "yes", result), WIN)
        self.assertEqual(settle("first_inning_score_away", "yes", result), LOSS)

    def test_no_runs(self):
        result = GameResult(
            home_runs=2, away_runs=1,
            home_runs_1st_inning=0, away_runs_1st_inning=0,
        )
        self.assertEqual(settle("first_inning_run", "yes", result), LOSS)
        self.assertEqual(settle("first_inning_run", "no", result), WIN)


class CollectionBlockedTests(unittest.TestCase):
    def test_settling_a_blocked_market_raises(self):
        result = GameResult(home_runs=1, away_runs=0)
        with self.assertRaises(ValueError):
            settle(COLLECTION_BLOCKED, "over", result, line="1.5")

    def test_same_game_parlay_is_currently_blocked(self):
        # SGP pricing is out of scope by design (guard 8) -- it must stay
        # blocked, not silently pointing at a nonexistent callable.
        spec = MARKET_CATALOGUE["same_game_parlay"]
        self.assertEqual(spec.settlement_rule, COLLECTION_BLOCKED)


class RegisterRuleTests(unittest.TestCase):
    def test_register_new_rule(self):
        def fake_rule(side, line, result):
            return WIN

        register_rule("test_only_rule_xyz", fake_rule)
        self.assertIs(SETTLEMENT_RULES["test_only_rule_xyz"], fake_rule)
        del SETTLEMENT_RULES["test_only_rule_xyz"]

    def test_register_same_callable_twice_is_ok(self):
        def fake_rule(side, line, result):
            return WIN

        register_rule("test_only_rule_dup", fake_rule)
        register_rule("test_only_rule_dup", fake_rule)  # no raise
        del SETTLEMENT_RULES["test_only_rule_dup"]

    def test_register_conflicting_rule_raises(self):
        def fake_rule_a(side, line, result):
            return WIN

        def fake_rule_b(side, line, result):
            return LOSS

        register_rule("test_only_rule_conflict", fake_rule_a)
        with self.assertRaises(ValueError):
            register_rule("test_only_rule_conflict", fake_rule_b)
        del SETTLEMENT_RULES["test_only_rule_conflict"]


if __name__ == "__main__":
    unittest.main()
