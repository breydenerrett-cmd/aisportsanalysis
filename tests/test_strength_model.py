"""The run model's arithmetic, and the properties it must never violate.

Most of these are INVARIANTS rather than expected values, because there is
no ground truth to assert a probability against -- `scripts/backtest_card.py`
is what says whether the model is any good. What this file guards is that
the model is internally coherent: that its markets agree with each other,
that its distribution sums to one, and that a missing input produces a
refusal rather than a confident-looking 50/50.

The four run-line cases get the most attention here. They are easy to get
backwards, the mistake is invisible on inspection, and getting one wrong
would misprice roughly a fifth of every card this product ever publishes.
"""

from __future__ import annotations

import math
import unittest

from src.analysis import calibrate, strength

LEAGUE = 4.5


def _features(**over):
    base = {
        "away_runs_scored_pg": 4.5, "away_runs_allowed_pg": 4.5,
        "home_runs_scored_pg": 4.5, "home_runs_allowed_pg": 4.5,
        "away_games_played": 140, "home_games_played": 140,
    }
    base.update(over)
    return base


class TheJointDistribution(unittest.TestCase):
    def test_the_grid_sums_to_one(self):
        grid = strength.outcome_grid(4.2, 4.8)
        total = sum(sum(row) for row in grid)
        self.assertAlmostEqual(1.0, total, places=6)

    def test_no_tie_mass_survives(self):
        """Baseball plays extra innings. Tie probability has to be
        redistributed, not dropped -- dropping it would renormalise every
        downstream probability upward without anything saying so."""
        grid = strength.outcome_grid(4.2, 4.8)
        diagonal = sum(grid[k][k] for k in range(1, strength.MAX_RUNS))
        self.assertAlmostEqual(0.0, diagonal, places=9)

    def test_the_better_side_is_more_likely(self):
        probs = strength.market_probabilities(3.5, 5.0)
        self.assertGreater(probs["p_home"], 0.5)
        self.assertAlmostEqual(1.0, probs["p_home"] + probs["p_away"], places=9)


class TheRunLineCases(unittest.TestCase):
    """Four cover cases, two complementary pairs. Both pairs must sum to 1."""

    def setUp(self):
        self.probs = strength.market_probabilities(4.0, 5.0, run_line=1.5)

    def test_home_minus_and_away_plus_are_complements(self):
        self.assertAlmostEqual(
            1.0, self.probs["p_home_minus"] + self.probs["p_away_plus"],
            places=9,
            msg="home -1.5 and away +1.5 are the two sides of one bet")

    def test_home_plus_and_away_minus_are_complements(self):
        self.assertAlmostEqual(
            1.0, self.probs["p_home_plus"] + self.probs["p_away_minus"],
            places=9)

    def test_giving_runs_is_harder_than_winning(self):
        """P(win by 2+) < P(win). If this ever inverts the model is broken
        in a way that would make every favourite run line look like value."""
        self.assertLess(self.probs["p_home_minus"], self.probs["p_home"])

    def test_taking_runs_is_easier_than_winning(self):
        self.assertGreater(self.probs["p_away_plus"], self.probs["p_away"])

    def test_run_line_probability_picks_the_right_case(self):
        line = strength.market_probabilities(4.0, 5.0, run_line=1.5)
        self.assertEqual(
            line["p_home_minus"],
            strength.run_line_probability(line, "home", underdog=False))
        self.assertEqual(
            line["p_home_plus"],
            strength.run_line_probability(line, "home", underdog=True))
        self.assertEqual(
            line["p_away_minus"],
            strength.run_line_probability(line, "away", underdog=False))
        self.assertEqual(
            line["p_away_plus"],
            strength.run_line_probability(line, "away", underdog=True))


class TheMeans(unittest.TestCase):
    def test_two_average_clubs_produce_the_league_average(self):
        """The odds-ratio construction has to be neutral on neutral inputs,
        or every game on the slate is biased the same way and no per-game
        check can see it."""
        means = strength.run_means(_features(), league_rpg=LEAGUE)
        self.assertAlmostEqual(LEAGUE, means["away_mean"], places=6)
        self.assertAlmostEqual(LEAGUE + strength.HOME_FIELD_RUNS,
                               means["home_mean"], places=6)

    def test_home_field_favours_the_home_club_on_identical_inputs(self):
        line = strength.model_line(_features(), league_rpg=LEAGUE)
        self.assertGreater(line["p_home"], 0.5)

    def test_a_better_offence_scores_more(self):
        means = strength.run_means(
            _features(away_runs_scored_pg=5.5), league_rpg=LEAGUE)
        self.assertGreater(means["away_mean"], LEAGUE)

    def test_a_good_starter_lowers_the_runs_his_club_allows(self):
        weak = strength.run_means(
            _features(home_sp_fip=5.5, home_sp_innings=160,
                      home_sp_ip_per_start=6.0), league_rpg=LEAGUE)
        strong = strength.run_means(
            _features(home_sp_fip=2.5, home_sp_innings=160,
                      home_sp_ip_per_start=6.0), league_rpg=LEAGUE)
        self.assertLess(strong["home_defence"], weak["home_defence"])
        self.assertLess(strong["away_mean"], weak["away_mean"])

    def test_an_unknown_starter_leaves_the_team_rate_untouched(self):
        with_none = strength.run_means(_features(), league_rpg=LEAGUE)
        self.assertFalse(with_none["home_starter_known"])
        self.assertAlmostEqual(with_none["home_defence"],
                               with_none["home_team_defence"], places=9)

    def test_a_thin_starter_sample_is_pulled_toward_the_league(self):
        """Two innings of a 1.00 FIP is not a 1.00 FIP starter."""
        thin = strength.run_means(
            _features(home_sp_fip=1.0, home_sp_innings=2,
                      home_sp_ip_per_start=6.0), league_rpg=LEAGUE)
        full = strength.run_means(
            _features(home_sp_fip=1.0, home_sp_innings=180,
                      home_sp_ip_per_start=6.0), league_rpg=LEAGUE)
        self.assertGreater(thin["home_starter_rate"], full["home_starter_rate"])

    def test_no_team_rates_refuses_rather_than_guessing_a_coin_flip(self):
        """A game the model has NO opinion about must not be flattened into
        a considered 50/50 -- the two are different answers and only one of
        them belongs on a card."""
        with self.assertRaises(strength.StrengthError):
            strength.run_means({}, league_rpg=LEAGUE)

    def test_no_league_rate_refuses(self):
        with self.assertRaises(strength.StrengthError):
            strength.run_means(_features(), league_rpg=0)

    def test_absurd_inputs_cannot_produce_certainty(self):
        line = strength.model_line(
            _features(home_runs_scored_pg=40.0, away_runs_scored_pg=0.01,
                      home_runs_allowed_pg=0.01, away_runs_allowed_pg=40.0),
            league_rpg=LEAGUE)
        self.assertLess(line["p_home"], 1.0)
        self.assertGreater(line["p_home"], 0.0)


class NothingIsFitted(unittest.TestCase):
    """The model's main defence is that it has no free parameters. A future
    edit that starts tuning one has to trip over this."""

    def test_the_inflation_term_is_off(self):
        self.assertEqual(1.0, strength.MARGIN_INFLATION,
                         "MARGIN_INFLATION is a correction that must be "
                         "measured out of sample before it is switched on; "
                         "a value chosen alongside the model is a fitted "
                         "parameter wearing a constant's clothes")

    def test_home_field_is_a_published_constant_not_an_estimate(self):
        self.assertEqual(0.20, strength.HOME_FIELD_RUNS)


class Calibration(unittest.TestCase):
    def test_platt_recovers_a_known_distortion(self):
        """Generate labels from a TRUE probability, feed the model an
        overconfident version of it, and check the fit pulls it back."""
        rows = []
        for i in range(2000):
            true_p = 0.30 + 0.4 * ((i % 100) / 99.0)
            # Deterministic pseudo-outcome: no RNG, so this test cannot flake.
            y = 1 if ((i * 37) % 100) / 100.0 < true_p else 0
            over = 1.0 / (1.0 + math.exp(-2.0 * math.log(true_p / (1 - true_p))))
            rows.append((over, y))
        cal = calibrate.fit(rows)
        self.assertTrue(cal.n >= calibrate.MIN_FIT_GAMES)
        self.assertLess(cal.b, 1.0,
                        "an overconfident model must be told to shrink")

    def test_too_few_games_falls_back_to_the_base_rate(self):
        rows = [(0.9, 1)] * 10
        cal = calibrate.fit(rows)
        self.assertFalse(cal.to_dict()["fitted"])
        self.assertEqual(1.0, cal.apply(0.9))  # the base rate of that sample

    def test_walk_forward_never_calibrates_a_game_on_itself(self):
        """The ordering property the whole backtest rests on."""
        wf = calibrate.WalkForward()
        for i in range(calibrate.MIN_FIT_GAMES + 50):
            wf.add("2026-05-01", 0.6, 1)
        # Everything added is dated 2026-05-01, so a game ON that date sees
        # NOTHING before it and must fall back rather than use its own day.
        same_day = wf.calibration_for("2026-05-01")
        self.assertEqual(0, same_day.n)
        later = wf.calibration_for("2026-05-02")
        self.assertEqual(calibrate.MIN_FIT_GAMES + 50, later.n)

    def test_apply_preserves_ordering(self):
        cal = calibrate.Calibration(0.03, 0.51, 2000, 0.52)
        self.assertLess(cal.apply(0.40), cal.apply(0.60))
        self.assertLess(cal.apply(0.60), cal.apply(0.80))

    def test_apply_shrinks_toward_the_middle_when_b_is_below_one(self):
        cal = calibrate.Calibration(0.0, 0.5, 2000, 0.5)
        self.assertLess(cal.apply(0.80), 0.80)
        self.assertGreater(cal.apply(0.20), 0.20)


if __name__ == "__main__":
    unittest.main()
