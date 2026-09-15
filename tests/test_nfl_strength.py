"""Tests for src.analysis.nfl_strength."""

import unittest
from src.analysis.nfl_strength import (
    _offense_epa_per_play,
    team_ratings,
    expected_margin,
    win_probability,
    game_probability,
    model_side,
    MARGIN_SIGMA,
    THIN_BELOW_GAMES,
)


class TestOffenseEpaPerPlay(unittest.TestCase):
    """Tests for _offense_epa_per_play function."""

    def test_basic_calculation(self):
        """Test basic EPA per play calculation."""
        row = {
            "passing_epa": 20.0,
            "rushing_epa": 10.0,
            "attempts": 30,
            "carries": 20,
        }
        epa = _offense_epa_per_play(row)
        # (20 + 10) / (30 + 20) = 30 / 50 = 0.6
        self.assertAlmostEqual(epa, 0.6)

    def test_missing_epa_column(self):
        """Test that missing EPA column returns None."""
        row = {
            "passing_epa": 20.0,
            # missing rushing_epa
            "attempts": 30,
            "carries": 20,
        }
        epa = _offense_epa_per_play(row)
        self.assertIsNone(epa)

    def test_missing_play_column(self):
        """Test that missing play column returns None."""
        row = {
            "passing_epa": 20.0,
            "rushing_epa": 10.0,
            "attempts": 30,
            # missing carries
        }
        epa = _offense_epa_per_play(row)
        self.assertIsNone(epa)

    def test_zero_plays(self):
        """Test that zero total plays returns None."""
        row = {
            "passing_epa": 20.0,
            "rushing_epa": 10.0,
            "attempts": 0,
            "carries": 0,
        }
        epa = _offense_epa_per_play(row)
        self.assertIsNone(epa)

    def test_negative_epa(self):
        """Test that negative EPA values are handled correctly."""
        row = {
            "passing_epa": -10.0,
            "rushing_epa": 5.0,
            "attempts": 20,
            "carries": 10,
        }
        epa = _offense_epa_per_play(row)
        # (-10 + 5) / (20 + 10) = -5 / 30 ≈ -0.167
        self.assertAlmostEqual(epa, -5.0 / 30.0)


class TestTeamRatings(unittest.TestCase):
    """Tests for team_ratings function."""

    def setUp(self):
        """Create a fixture with two weeks for four teams with hand-computable EPA."""
        self.rows = [
            # Week 1: KC vs SF, DAL vs PHI
            {
                "season": 2024,
                "week": 1,
                "team": "KC",
                "opponent_team": "SF",
                "passing_epa": 20.0,
                "rushing_epa": 10.0,
                "attempts": 30,
                "carries": 20,
            },
            {
                "season": 2024,
                "week": 1,
                "team": "SF",
                "opponent_team": "KC",
                "passing_epa": 10.0,
                "rushing_epa": 5.0,
                "attempts": 20,
                "carries": 10,
            },
            {
                "season": 2024,
                "week": 1,
                "team": "DAL",
                "opponent_team": "PHI",
                "passing_epa": 18.0,
                "rushing_epa": 12.0,
                "attempts": 24,
                "carries": 26,
            },
            {
                "season": 2024,
                "week": 1,
                "team": "PHI",
                "opponent_team": "DAL",
                "passing_epa": 15.0,
                "rushing_epa": 10.0,
                "attempts": 20,
                "carries": 20,
            },
            # Week 2: KC vs DAL, SF vs PHI
            {
                "season": 2024,
                "week": 2,
                "team": "KC",
                "opponent_team": "DAL",
                "passing_epa": 18.0,
                "rushing_epa": 12.0,
                "attempts": 30,
                "carries": 20,
            },
            {
                "season": 2024,
                "week": 2,
                "team": "DAL",
                "opponent_team": "KC",
                "passing_epa": 18.0,
                "rushing_epa": 12.0,
                "attempts": 30,
                "carries": 20,
            },
            {
                "season": 2024,
                "week": 2,
                "team": "SF",
                "opponent_team": "PHI",
                "passing_epa": 10.0,
                "rushing_epa": 5.0,
                "attempts": 20,
                "carries": 10,
            },
            {
                "season": 2024,
                "week": 2,
                "team": "PHI",
                "opponent_team": "SF",
                "passing_epa": 10.0,
                "rushing_epa": 5.0,
                "attempts": 20,
                "carries": 10,
            },
        ]

    def test_ratings_hand_computable(self):
        """Test that ratings match hand arithmetic."""
        ratings = team_ratings(self.rows, season=2024, through_week=3)

        # KC: Week 1 = 0.6, Week 2 = 0.6, avg = 0.6
        #     Def allowed: SF (0.5) + DAL (0.6) = avg 0.55
        # Rating = 0.6 - 0.55 = 0.05, games = 2
        self.assertIn("KC", ratings)
        self.assertAlmostEqual(ratings["KC"]["off_epa"], 0.6)
        self.assertAlmostEqual(ratings["KC"]["def_epa_allowed"], 0.55)
        self.assertAlmostEqual(ratings["KC"]["rating"], 0.05)
        self.assertEqual(ratings["KC"]["games"], 2)

        # SF: Week 1 = 0.5, Week 2 = 0.5, avg = 0.5
        #     Def allowed: KC (0.6) + PHI (0.5) = avg 0.55
        # Rating = 0.5 - 0.55 = -0.05, games = 2
        self.assertIn("SF", ratings)
        self.assertAlmostEqual(ratings["SF"]["off_epa"], 0.5)
        self.assertAlmostEqual(ratings["SF"]["def_epa_allowed"], 0.55)
        self.assertAlmostEqual(ratings["SF"]["rating"], -0.05)
        self.assertEqual(ratings["SF"]["games"], 2)

    def test_point_in_time_filtering(self):
        """Test that only rows with week < through_week are used."""
        # Through week 2: only week 1 games count (week < 2)
        ratings = team_ratings(self.rows, season=2024, through_week=2)

        # KC and SF should each have 1 game from week 1
        self.assertEqual(ratings["KC"]["games"], 1)
        self.assertEqual(ratings["SF"]["games"], 1)
        self.assertEqual(ratings["DAL"]["games"], 1)
        self.assertEqual(ratings["PHI"]["games"], 1)

        # Through week 3: weeks 1 and 2 games count
        ratings2 = team_ratings(self.rows, season=2024, through_week=3)
        self.assertEqual(ratings2["KC"]["games"], 2)
        self.assertEqual(ratings2["SF"]["games"], 2)

    def test_missing_team_not_in_ratings(self):
        """Test that teams without prior rows are absent."""
        rows = [
            {
                "season": 2024,
                "week": 1,
                "team": "KC",
                "opponent_team": "GB",
                "passing_epa": 20.0,
                "rushing_epa": 10.0,
                "attempts": 30,
                "carries": 20,
            },
            # GB row is missing
        ]
        ratings = team_ratings(rows, season=2024, through_week=2)

        # KC is in ratings, but GB is not (no row for GB)
        self.assertIn("KC", ratings)
        self.assertNotIn("GB", ratings)

    def test_season_filtering(self):
        """Test that only matching season is used."""
        rows = self.rows + [
            {
                "season": 2025,
                "week": 1,
                "team": "KC",
                "opponent_team": "PHI",
                "passing_epa": 25.0,
                "rushing_epa": 15.0,
                "attempts": 40,
                "carries": 30,
            },
            {
                "season": 2025,
                "week": 1,
                "team": "PHI",
                "opponent_team": "KC",
                "passing_epa": 25.0,
                "rushing_epa": 15.0,
                "attempts": 40,
                "carries": 30,
            },
        ]

        # 2024 season: KC rating = 0.05
        ratings_2024 = team_ratings(rows, season=2024, through_week=3)
        self.assertAlmostEqual(ratings_2024["KC"]["rating"], 0.05)

        # 2025 season: KC would have different rating if included
        # But we're filtering to 2025, and KC only has 1 game in 2025
        ratings_2025 = team_ratings(rows, season=2025, through_week=2)
        self.assertIn("KC", ratings_2025)
        # KC's 2025 EPA = (25+15)/(40+30) = 40/70 ≈ 0.571
        self.assertAlmostEqual(ratings_2025["KC"]["off_epa"], 40.0/70.0)


class TestExpectedMargin(unittest.TestCase):
    """Tests for expected_margin function."""

    def test_home_field_advantage(self):
        """Test that home field advantage is added."""
        ratings = {
            "KC": {"rating": 1.0},
            "PHI": {"rating": 0.0},
        }
        # (1.0 - 0.0) * 63 + 1.5 = 64.5
        margin = expected_margin("KC", "PHI", ratings)
        self.assertAlmostEqual(margin, 64.5)

    def test_neutral_site_no_home_field(self):
        """Test that neutral site removes home field advantage."""
        ratings = {
            "KC": {"rating": 1.0},
            "PHI": {"rating": 0.0},
        }
        # (1.0 - 0.0) * 63 = 63.0
        margin = expected_margin("KC", "PHI", ratings, neutral_site=True)
        self.assertAlmostEqual(margin, 63.0)

    def test_away_team_favored(self):
        """Test negative margin when away is favored."""
        ratings = {
            "KC": {"rating": 0.0},
            "PHI": {"rating": 1.0},
        }
        # (0.0 - 1.0) * 63 + 1.5 = -61.5
        margin = expected_margin("KC", "PHI", ratings)
        self.assertAlmostEqual(margin, -61.5)

    def test_missing_home_team(self):
        """Test that missing home team returns None."""
        ratings = {"PHI": {"rating": 0.0}}
        margin = expected_margin("KC", "PHI", ratings)
        self.assertIsNone(margin)

    def test_missing_away_team(self):
        """Test that missing away team returns None."""
        ratings = {"KC": {"rating": 1.0}}
        margin = expected_margin("KC", "PHI", ratings)
        self.assertIsNone(margin)


class TestWinProbability(unittest.TestCase):
    """Tests for win_probability function."""

    def test_zero_margin_is_half(self):
        """Test that zero margin gives 0.5 probability."""
        prob = win_probability(0.0)
        self.assertAlmostEqual(prob, 0.5)

    def test_symmetry(self):
        """Test that win probability is symmetric: P(m) + P(-m) = 1."""
        prob_pos = win_probability(10.0)
        prob_neg = win_probability(-10.0)
        self.assertAlmostEqual(prob_pos + prob_neg, 1.0, places=9)

    def test_at_one_sigma(self):
        """Test win probability at one sigma (13.5 points)."""
        prob = win_probability(MARGIN_SIGMA)
        # At one sigma, CDF ≈ 0.8413
        self.assertAlmostEqual(prob, 0.8413, places=3)

    def test_large_positive_margin(self):
        """Test that large positive margin approaches 1.0."""
        prob = win_probability(50.0)
        self.assertGreater(prob, 0.99988)

    def test_large_negative_margin(self):
        """Test that large negative margin approaches 0.0."""
        prob = win_probability(-50.0)
        self.assertLess(prob, 0.00012)

    def test_custom_sigma(self):
        """Test that custom sigma parameter works."""
        prob1 = win_probability(13.5, sigma=13.5)
        prob2 = win_probability(13.5, sigma=27.0)
        # Larger sigma means less probability at the same margin
        self.assertGreater(prob1, prob2)


class TestGameProbability(unittest.TestCase):
    """Tests for game_probability function."""

    def test_returns_dict(self):
        """Test that game_probability returns expected dict structure."""
        ratings = {
            "KC": {"rating": 1.0, "games": 5},
            "PHI": {"rating": 0.0, "games": 5},
        }

        result = game_probability("KC", "PHI", ratings)

        self.assertIsNotNone(result)
        self.assertIn("p_home", result)
        self.assertIn("p_away", result)
        self.assertIn("expected_margin", result)
        self.assertIn("games_home", result)
        self.assertIn("games_away", result)
        self.assertIn("thin", result)

    def test_probabilities_sum_to_one(self):
        """Test that home and away probabilities sum to 1."""
        ratings = {
            "KC": {"rating": 1.0, "games": 5},
            "PHI": {"rating": 0.0, "games": 5},
        }

        result = game_probability("KC", "PHI", ratings)
        self.assertAlmostEqual(result["p_home"] + result["p_away"], 1.0)

    def test_thin_flag_low_games(self):
        """Test that thin=True when either team has < 3 games."""
        ratings = {
            "KC": {"rating": 1.0, "games": 1},
            "PHI": {"rating": 0.0, "games": 5},
        }

        result = game_probability("KC", "PHI", ratings)
        self.assertTrue(result["thin"])

    def test_thin_flag_sufficient_games(self):
        """Test that thin=False when both teams have >= 3 games."""
        ratings = {
            "KC": {"rating": 1.0, "games": 5},
            "PHI": {"rating": 0.0, "games": 3},
        }

        result = game_probability("KC", "PHI", ratings)
        self.assertFalse(result["thin"])

    def test_missing_home_returns_none(self):
        """Test that missing home team returns None."""
        ratings = {"PHI": {"rating": 0.0, "games": 5}}
        result = game_probability("KC", "PHI", ratings)
        self.assertIsNone(result)

    def test_missing_away_returns_none(self):
        """Test that missing away team returns None."""
        ratings = {"KC": {"rating": 1.0, "games": 5}}
        result = game_probability("KC", "PHI", ratings)
        self.assertIsNone(result)

    def test_games_counts(self):
        """Test that games_home and games_away are correct."""
        ratings = {
            "KC": {"rating": 1.0, "games": 7},
            "PHI": {"rating": 0.0, "games": 3},
        }

        result = game_probability("KC", "PHI", ratings)
        self.assertEqual(result["games_home"], 7)
        self.assertEqual(result["games_away"], 3)


class TestModelSide(unittest.TestCase):
    """Tests for model_side function."""

    def test_home_favored(self):
        """Test model_side when home is favored."""
        prob_dict = {"p_home": 0.6}
        side = model_side(prob_dict)
        self.assertEqual(side, "home")

    def test_away_favored(self):
        """Test model_side when away is favored."""
        prob_dict = {"p_home": 0.4}
        side = model_side(prob_dict)
        self.assertEqual(side, "away")

    def test_exactly_half(self):
        """Test model_side at exactly 0.5."""
        prob_dict = {"p_home": 0.5}
        side = model_side(prob_dict)
        self.assertIsNone(side)

    def test_none_input(self):
        """Test model_side with None input."""
        side = model_side(None)
        self.assertIsNone(side)

    def test_slight_home_edge(self):
        """Test model_side with slight home edge."""
        prob_dict = {"p_home": 0.5001}
        side = model_side(prob_dict)
        self.assertEqual(side, "home")

    def test_slight_away_edge(self):
        """Test model_side with slight away edge."""
        prob_dict = {"p_home": 0.4999}
        side = model_side(prob_dict)
        self.assertEqual(side, "away")


if __name__ == "__main__":
    unittest.main()
