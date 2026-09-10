"""The player-prop model: its arithmetic, and the two markets it refuses.

WHY THIS MODEL EXISTS
---------------------
The team moneyline is the most heavily priced market in baseball and this
project's model beats a home-field base rate on it by 0.004 nats —
essentially nothing. A hitter's chance of getting a hit is a far more
tractable question, and measured over 16,741 real batter games the prop
model gains **+0.0107 nats**, roughly 2.7 times as much.

WHAT THIS FILE GUARDS
---------------------
Mostly invariants, because there is no ground truth to assert a probability
against — `scripts/backtest_player_props.py` is what says whether the model
is any good. What is tested here is that it cannot contradict itself, that
it refuses rather than guesses, and that the two markets measured worse than
a base rate stay unpublishable.
"""

from __future__ import annotations

import unittest

from src.analysis import playerprops


def _line(pa=4, h=1, doubles=0, triples=0, hr=0, r=0, rbi=0, hrr=None):
    return {"pa": pa, "h": h, "doubles": doubles, "triples": triples,
            "hr": hr, "r": r, "rbi": rbi,
            "hits_runs_rbi": h + r + rbi if hrr is None else hrr}


def _season(games=50, **per_game):
    return [_line(**per_game) for _ in range(games)]


LEAGUE = {"pa": 100000, "hit": 0.22, "single": 0.15, "double": 0.045,
          "triple": 0.005, "home_run": 0.02, "run": 0.12, "rbi": 0.115}


class Rates(unittest.TestCase):
    def test_a_batter_with_no_history_is_refused_not_guessed(self):
        """A batter the model has no opinion about must not be published
        under a league-average number wearing his name."""
        with self.assertRaises(playerprops.PropError):
            playerprops.batter_rates([_line(pa=4)], LEAGUE)

    def test_a_thin_sample_is_pulled_toward_the_league(self):
        thin = playerprops.batter_rates(_season(games=12, pa=4, h=3), LEAGUE)
        thick = playerprops.batter_rates(_season(games=200, pa=4, h=3), LEAGUE)
        self.assertLess(thin["hit"], thick["hit"],
                        "48 plate appearances of a .750 hitter should be "
                        "regressed much harder than 800 of one")

    def test_the_component_rates_sum_to_the_hit_rate(self):
        rates = playerprops.batter_rates(
            _season(games=60, pa=4, h=1, doubles=1), LEAGUE)
        self.assertAlmostEqual(
            rates["hit"],
            rates["single"] + rates["double"] + rates["triple"]
            + rates["home_run"], places=9)

    def test_league_rates_refuse_an_empty_pile(self):
        with self.assertRaises(playerprops.PropError):
            playerprops.league_rates([])


class TheCountDistributions(unittest.TestCase):
    def setUp(self):
        self.rates = playerprops.batter_rates(
            _season(games=100, pa=4, h=1, doubles=1), LEAGUE)

    def test_total_bases_is_a_distribution(self):
        dist = playerprops.total_bases_distribution(self.rates, 4.2)
        self.assertAlmostEqual(1.0, sum(dist), places=6)
        self.assertTrue(all(p >= 0 for p in dist))

    def test_more_plate_appearances_never_lowers_the_chance(self):
        low = playerprops.probability_over("batter_hits", 0.5, self.rates, 3.0)
        high = playerprops.probability_over("batter_hits", 0.5, self.rates, 5.0)
        self.assertLess(low, high)

    def test_a_harder_line_is_always_less_likely(self):
        one = playerprops.probability_over("batter_total_bases", 0.5,
                                           self.rates, 4.2)
        two = playerprops.probability_over("batter_total_bases", 1.5,
                                           self.rates, 4.2)
        self.assertLess(two, one)

    def test_a_hit_is_at_least_as_likely_as_a_home_run(self):
        """The markets come off one set of per-PA rates, so they cannot
        contradict each other. A batter cannot be likelier to homer than to
        reach on any hit at all."""
        hit = playerprops.probability_over("batter_hits", 0.5, self.rates, 4.2)
        hr = playerprops.probability_over("batter_home_runs", 0.5,
                                          self.rates, 4.2)
        self.assertGreaterEqual(hit, hr)

    def test_a_tougher_pitcher_lowers_every_offensive_market(self):
        easy = playerprops.probability_over("batter_hits", 0.5, self.rates,
                                            4.2, pitcher_factor=1.15)
        hard = playerprops.probability_over("batter_hits", 0.5, self.rates,
                                            4.2, pitcher_factor=0.85)
        self.assertGreater(easy, hard)

    def test_fractional_plate_appearances_sit_between_the_whole_ones(self):
        """4.3 plate appearances is not 4 and not 5, and rounding either way
        moves a tenth of a hit's worth of chance across a whole slate."""
        four = playerprops.probability_over("batter_hits", 0.5, self.rates, 4.0)
        mixed = playerprops.probability_over("batter_hits", 0.5, self.rates, 4.3)
        five = playerprops.probability_over("batter_hits", 0.5, self.rates, 5.0)
        self.assertLess(four, mixed)
        self.assertLess(mixed, five)

    def test_an_unknown_market_is_refused(self):
        with self.assertRaises(playerprops.PropError):
            playerprops.probability_over("batter_stolen_bases", 0.5,
                                         self.rates, 4.2)


class ThePitcherFactor(unittest.TestCase):
    def test_a_pitcher_with_no_history_is_neutral(self):
        self.assertEqual(1.0, playerprops.pitcher_hit_factor(None, None, 0.22))

    def test_it_is_bounded_both_ways(self):
        wild = playerprops.pitcher_hit_factor(500, 600, 0.22)
        elite = playerprops.pitcher_hit_factor(1, 600, 0.22)
        self.assertLessEqual(wild, playerprops.MAX_PITCHER_FACTOR)
        self.assertGreaterEqual(elite, playerprops.MIN_PITCHER_FACTOR)


class TheTwoBrokenMarkets(unittest.TestCase):
    """Measured worse than a base rate over 16,741 games. They stay priceable
    so the backtest keeps watching them, and refused for publication."""

    def test_rbis_and_hits_runs_rbis_are_not_publishable(self):
        self.assertFalse(playerprops.publishable("batter_rbis"))
        self.assertFalse(playerprops.publishable("batter_hits_runs_rbis"))

    def test_the_four_measured_positive_are_publishable(self):
        for market in ("batter_hits", "batter_total_bases",
                       "batter_home_runs", "batter_runs_scored"):
            self.assertTrue(playerprops.publishable(market), market)

    def test_a_broken_market_can_still_be_priced(self):
        """Switching off the measurement is how a known-broken thing stops
        being known."""
        rates = playerprops.batter_rates(_season(games=100, pa=4, h=1), LEAGUE)
        value = playerprops.probability_over("batter_rbis", 0.5, rates, 4.2)
        self.assertGreater(value, 0.0)

    def test_every_refusal_says_why_in_a_sentence_a_person_can_read(self):
        for market, reason in playerprops.NOT_PUBLISHABLE.items():
            self.assertIn(market, playerprops.SUPPORTED_MARKETS)
            self.assertGreater(len(reason), 60,
                               f"{market}'s reason has to explain the "
                               f"mechanism, not just assert a number")

    def test_price_prop_carries_the_publishable_flag(self):
        priced = playerprops.price_prop(
            market="batter_rbis", line=0.5,
            batter_lines=_season(games=100, pa=4, h=1, rbi=1), league=LEAGUE)
        self.assertFalse(priced["publishable"])
        self.assertTrue(priced["not_publishable_because"])


class TheWithinGameCorrelation(unittest.TestCase):
    """Plate appearances are not independent coin flips. `RHO` carries how
    much they are not, and `rho = 0` must reproduce the old model exactly so
    the correction stays switchable and comparable."""

    def setUp(self):
        self.rates = playerprops.batter_rates(
            _season(games=120, pa=4, h=1, doubles=1), LEAGUE)

    def test_rho_zero_is_exactly_the_binomial(self):
        p = self.rates["hit"]
        for n in (1, 3, 4, 7):
            self.assertAlmostEqual(
                (1 - p) ** n,
                playerprops._beta_binomial_none(p, n, 0.0), places=12,
                msg=f"rho=0 must be the plain binomial at n={n}")

    def test_correlation_makes_a_zero_more_likely(self):
        """Clustering means more 0-fers AND more multi-hit games, and 'at
        least one hit' is exactly the quantity the extra 0-fers come out
        of. If this ever inverts, the correction has the sign backwards and
        would make an already-overconfident model worse."""
        p = self.rates["hit"]
        independent = playerprops._beta_binomial_none(p, 4, 0.0)
        correlated = playerprops._beta_binomial_none(p, 4, 0.05)
        self.assertGreater(correlated, independent)

    def test_it_lowers_the_published_probability(self):
        plain = playerprops.probability_over("batter_hits", 0.5, self.rates,
                                             4.2, rho=0.0)
        corrected = playerprops.probability_over("batter_hits", 0.5,
                                                 self.rates, 4.2, rho=0.05)
        self.assertLess(corrected, plain)

    def test_total_bases_is_deliberately_left_alone(self):
        """It measured calibrated to about one point already, so a
        correction fitted for the hits market has nothing to fix there and
        applying it would move a number that is right."""
        plain = playerprops.probability_over("batter_total_bases", 1.5,
                                             self.rates, 4.2, rho=0.0)
        corrected = playerprops.probability_over("batter_total_bases", 1.5,
                                                 self.rates, 4.2, rho=0.20)
        self.assertAlmostEqual(plain, corrected, places=12)

    def test_a_probability_stays_a_probability(self):
        for rho in (0.0, 0.01, 0.05, 0.3, 0.9):
            value = playerprops.probability_over("batter_hits", 0.5,
                                                 self.rates, 4.2, rho=rho)
            self.assertGreaterEqual(value, 0.0)
            self.assertLessEqual(value, 1.0)


class TonightsBattingSlot(unittest.TestCase):
    """Measured to beat the batter's own season average by 13% on plate
    appearances (0.608 mean absolute error against 0.699, over 3,417
    batter-games with both a posted lineup and a boxscore)."""

    def setUp(self):
        self.lines = _season(games=100, pa=4, h=1)

    def test_the_table_falls_monotonically_down_the_order(self):
        """Leadoff bats most, ninth bats least, every step of the way. A
        table that is not monotone is a measurement error, not a discovery
        about baseball."""
        values = [playerprops.SLOT_PLATE_APPEARANCES[s] for s in range(1, 10)]
        for earlier, later in zip(values, values[1:]):
            self.assertGreater(earlier, later)

    def test_the_spread_is_about_a_full_plate_appearance(self):
        top = playerprops.SLOT_PLATE_APPEARANCES[1]
        bottom = playerprops.SLOT_PLATE_APPEARANCES[9]
        self.assertGreater(top - bottom, 0.8)
        self.assertLess(top - bottom, 1.4)

    def test_a_slot_outside_the_order_falls_back_rather_than_guessing(self):
        for bad in (0, 10, -1, None, "leadoff", 2.7):
            self.assertIsNone(playerprops.expected_pa_for_slot(bad), bad)

    def test_the_slot_is_preferred_over_the_season_average(self):
        priced = playerprops.price_prop(
            market="batter_hits", line=0.5, batter_lines=self.lines,
            league=LEAGUE, batting_slot=1)
        self.assertEqual("batting_slot", priced["expected_pa_source"])
        self.assertAlmostEqual(playerprops.SLOT_PLATE_APPEARANCES[1],
                               priced["expected_pa"], places=3)

    def test_no_lineup_still_prices_and_says_so(self):
        """A card built before the lineup posts is still worth pricing. It
        just has to name the weaker estimate it used."""
        priced = playerprops.price_prop(
            market="batter_hits", line=0.5, batter_lines=self.lines,
            league=LEAGUE)
        self.assertEqual("season_average", priced["expected_pa_source"])

    def test_an_explicit_override_wins_over_both(self):
        priced = playerprops.price_prop(
            market="batter_hits", line=0.5, batter_lines=self.lines,
            league=LEAGUE, batting_slot=9, expected_pa=5.0)
        self.assertEqual("explicit", priced["expected_pa_source"])
        self.assertEqual(5.0, priced["expected_pa"])

    def test_batting_leadoff_beats_batting_ninth(self):
        top = playerprops.price_prop(
            market="batter_hits", line=0.5, batter_lines=self.lines,
            league=LEAGUE, batting_slot=1)["probability"]
        bottom = playerprops.price_prop(
            market="batter_hits", line=0.5, batter_lines=self.lines,
            league=LEAGUE, batting_slot=9)["probability"]
        self.assertGreater(top, bottom)


class NothingIsFitted(unittest.TestCase):
    """One fitted constant now, and it took a held-out window to adopt."""

    def test_the_regression_priors_are_stated_constants(self):
        self.assertEqual(200.0, playerprops.PA_REGRESSION)
        self.assertEqual(300.0, playerprops.BF_REGRESSION)
        self.assertEqual(40, playerprops.MIN_PA_FOR_A_RATE)

    def test_rho_is_the_value_the_pre_registered_test_adopted(self):
        self.assertEqual(0.05065, playerprops.RHO)


if __name__ == "__main__":
    unittest.main()
