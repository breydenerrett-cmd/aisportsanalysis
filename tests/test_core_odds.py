"""Tests for src/core/odds.py -- conversions, margin measurement, de-vigging.

Reference values are hand-computed from the definitions, not copied from the
implementation, so a wrong implementation cannot make these pass.
"""

import unittest

from src.core import odds


class TestAmericanToDecimal(unittest.TestCase):
    def test_even_money_both_signs(self):
        self.assertAlmostEqual(odds.american_to_decimal(100), 2.0)
        self.assertAlmostEqual(odds.american_to_decimal(-100), 2.0)

    def test_underdog(self):
        # +150 pays 1.5x profit, so 2.5 total return.
        self.assertAlmostEqual(odds.american_to_decimal(150), 2.5)

    def test_favorite(self):
        # -200 requires 2 units to win 1, so 1.5 total return.
        self.assertAlmostEqual(odds.american_to_decimal(-200), 1.5)

    def test_round_trip_through_american(self):
        for price in (-500, -250, -110, 100, 135, 400):
            decimal = odds.american_to_decimal(price)
            self.assertAlmostEqual(odds.decimal_to_american(decimal), price, places=9)


class TestAmericanToProbability(unittest.TestCase):
    def test_even_money_is_half(self):
        self.assertAlmostEqual(odds.american_to_probability(100), 0.5)
        self.assertAlmostEqual(odds.american_to_probability(-100), 0.5)

    def test_favorite_probability(self):
        # -150 -> 150/250 = 0.60
        self.assertAlmostEqual(odds.american_to_probability(-150), 0.6)

    def test_underdog_probability(self):
        # +130 -> 100/230 = 0.4347826...
        self.assertAlmostEqual(odds.american_to_probability(130), 100.0 / 230.0)

    def test_probability_to_american_round_trip(self):
        for p in (0.25, 0.4, 0.5, 0.6, 0.75):
            price = odds.probability_to_american(p)
            self.assertAlmostEqual(odds.american_to_probability(price), p, places=9)


class TestMarginMeasurement(unittest.TestCase):
    def test_the_canonical_example_from_the_docstring(self):
        # -150 / +130 is the example used throughout this project.
        total = odds.booksum([-150, 130])
        self.assertAlmostEqual(total, 0.6 + 100.0 / 230.0)
        self.assertGreater(total, 1.0)

    def test_margin_is_booksum_minus_one(self):
        self.assertAlmostEqual(
            odds.margin([-150, 130]), odds.booksum([-150, 130]) - 1.0
        )

    def test_fair_market_has_zero_margin(self):
        # +100 / +100 is a perfectly fair two-way book.
        self.assertAlmostEqual(odds.margin([100, 100]), 0.0)

    def test_standard_minus_110_both_sides(self):
        # The classic -110/-110 spread price: 0.5238 * 2 = 1.0476
        total = odds.booksum([-110, -110])
        self.assertAlmostEqual(total, 2 * (110.0 / 210.0))
        self.assertAlmostEqual(odds.margin([-110, -110]), 2 * (110.0 / 210.0) - 1.0)

    def test_hold_is_smaller_than_margin(self):
        # Hold divides by the booksum, so it is always below the raw margin.
        self.assertLess(
            odds.hold_percentage([-110, -110]) / 100.0, odds.margin([-110, -110])
        )


class TestDevig(unittest.TestCase):
    METHODS = ("proportional", "power", "shin", "additive")

    def test_every_method_sums_to_one(self):
        for method in self.METHODS:
            with self.subTest(method=method):
                fair = odds.devig([-150, 130], method=method)
                self.assertAlmostEqual(sum(fair), 1.0, places=9)

    def test_every_method_reduces_the_favorite(self):
        # De-vigging must lower the favorite's probability below its raw value.
        raw_favorite = odds.american_to_probability(-150)
        for method in self.METHODS:
            with self.subTest(method=method):
                fair, _ = odds.devig_two_way(-150, 130, method=method)
                self.assertLess(fair, raw_favorite)

    def test_proportional_math_is_exact(self):
        raw = [odds.american_to_probability(-150), odds.american_to_probability(130)]
        total = sum(raw)
        fair = odds.devig([-150, 130], method="proportional")
        self.assertAlmostEqual(fair[0], raw[0] / total, places=12)
        self.assertAlmostEqual(fair[1], raw[1] / total, places=12)

    def test_symmetric_market_devigs_to_even(self):
        for method in self.METHODS:
            with self.subTest(method=method):
                a, b = odds.devig_two_way(-110, -110, method=method)
                self.assertAlmostEqual(a, 0.5, places=9)
                self.assertAlmostEqual(b, 0.5, places=9)

    def test_already_fair_market_is_unchanged(self):
        for method in self.METHODS:
            with self.subTest(method=method):
                a, b = odds.devig_two_way(100, 100, method=method)
                self.assertAlmostEqual(a, 0.5, places=9)
                self.assertAlmostEqual(b, 0.5, places=9)

    def test_ordering_is_preserved(self):
        fair = odds.devig([-300, 250], method="proportional")
        self.assertGreater(fair[0], fair[1])

    def test_three_way_market(self):
        fair = odds.devig([150, 250, 200], method="proportional")
        self.assertEqual(len(fair), 3)
        self.assertAlmostEqual(sum(fair), 1.0, places=9)

    def test_methods_disagree_on_lopsided_markets(self):
        # If every method returned the same answer the choice would not matter.
        # On a lopsided book they must diverge, which is why the project
        # computes edge under more than one.
        prop, _ = odds.devig_two_way(-2000, 1200, method="proportional")
        shin, _ = odds.devig_two_way(-2000, 1200, method="shin")
        self.assertNotAlmostEqual(prop, shin, places=4)

    def test_unknown_method_is_rejected(self):
        with self.assertRaises(odds.OddsError):
            odds.devig([-150, 130], method="magic")

    def test_single_outcome_is_rejected(self):
        with self.assertRaises(odds.OddsError):
            odds.devig([-150])

    def test_additive_is_safe_on_any_two_way_market(self):
        # Worth pinning down: on a two-outcome book, additive can never drive a
        # side negative. Doing so would require p2 < p1 - 1, and p1 <= 1. So no
        # matter how lopsided a two-way market is, additive returns valid
        # probabilities -- it is only unsafe once there are 3+ outcomes.
        fair = odds.devig([-10000, 3000], method="additive")
        self.assertAlmostEqual(sum(fair), 1.0, places=9)
        self.assertTrue(all(0.0 < p < 1.0 for p in fair))

    def test_additive_rejects_a_three_way_market_it_cannot_handle(self):
        # With three outcomes the flat subtraction CAN push a longshot below
        # zero. The module must raise rather than return an invalid probability.
        # p ~= (0.97, 0.30, 0.02) -> excess/3 exceeds the smallest outcome.
        with self.assertRaises(odds.OddsError):
            odds.devig([-3233, 233, 4900], method="additive")


class TestEdgeAndValue(unittest.TestCase):
    def test_fair_price_has_zero_expected_value(self):
        # At the fair price for 60%, EV must be zero.
        price = odds.probability_to_american(0.6)
        self.assertAlmostEqual(odds.expected_value(0.6, price), 0.0, places=9)

    def test_positive_expected_value_when_model_beats_price(self):
        # Model says 60%, price implies 50%.
        self.assertGreater(odds.expected_value(0.6, 100), 0.0)

    def test_negative_expected_value_when_price_beats_model(self):
        self.assertLess(odds.expected_value(0.4, -200), 0.0)

    def test_expected_value_matches_hand_computation(self):
        # p=0.55 at +100: 0.55*1 - 0.45 = 0.10
        self.assertAlmostEqual(odds.expected_value(0.55, 100), 0.10, places=9)

    def test_edge_is_a_plain_difference(self):
        self.assertAlmostEqual(odds.edge(0.58, 0.52), 0.06, places=12)

    def test_break_even_probability_equals_raw_implied(self):
        self.assertAlmostEqual(
            odds.break_even_probability(-110), odds.american_to_probability(-110)
        )

    def test_edge_against_raw_implied_overstates_versus_devigged(self):
        # This is the bug the module exists to prevent, demonstrated.
        model_p = 0.62
        raw = odds.american_to_probability(-150)
        fair, _ = odds.devig_two_way(-150, 130)
        naive_edge = odds.edge(model_p, raw)
        true_edge = odds.edge(model_p, fair)
        self.assertGreater(true_edge, naive_edge)


class TestValidation(unittest.TestCase):
    def test_odds_inside_plus_minus_100_are_rejected(self):
        for bad in (0, 50, -50, 99.9):
            with self.subTest(bad=bad):
                with self.assertRaises(odds.OddsError):
                    odds.american_to_probability(bad)

    def test_exactly_plus_or_minus_100_is_accepted(self):
        self.assertAlmostEqual(odds.american_to_probability(100), 0.5)
        self.assertAlmostEqual(odds.american_to_probability(-100), 0.5)

    def test_non_numeric_odds_rejected(self):
        for bad in ("-150", None, [1]):
            with self.subTest(bad=bad):
                with self.assertRaises(odds.OddsError):
                    odds.american_to_probability(bad)

    def test_booleans_are_not_numbers_here(self):
        with self.assertRaises(odds.OddsError):
            odds.american_to_probability(True)

    def test_probability_bounds_are_exclusive(self):
        for bad in (0.0, 1.0, -0.1, 1.1):
            with self.subTest(bad=bad):
                with self.assertRaises(odds.OddsError):
                    odds.probability_to_american(bad)

    def test_nan_is_rejected(self):
        with self.assertRaises(odds.OddsError):
            odds.american_to_probability(float("nan"))


if __name__ == "__main__":
    unittest.main()
