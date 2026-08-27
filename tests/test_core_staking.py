"""Tests for src/core/staking.py.

The safety behaviour matters more than the arithmetic here: caps must hold,
negative-EV bets must size to zero, and Kelly must refuse to run on an
uncalibrated model.
"""

import unittest

from src.core import staking
from src.core.staking import StakingError


class TestFlatStake(unittest.TestCase):
    def test_one_percent_of_bankroll(self):
        self.assertAlmostEqual(staking.flat_stake(10_000), 100.0)

    def test_custom_fraction(self):
        self.assertAlmostEqual(staking.flat_stake(10_000, 0.05), 500.0)

    def test_ignores_edge_entirely(self):
        # Same stake regardless of how good the bet looks -- that is the point.
        self.assertEqual(staking.flat_stake(1_000), staking.flat_stake(1_000))

    def test_rejects_bad_bankroll(self):
        for bad in (0, -100, "1000", None, True):
            with self.subTest(bad=bad):
                with self.assertRaises(StakingError):
                    staking.flat_stake(bad)

    def test_rejects_bad_fraction(self):
        for bad in (0.0, -0.1, 1.5):
            with self.subTest(bad=bad):
                with self.assertRaises(StakingError):
                    staking.flat_stake(1_000, bad)


class TestKellyFraction(unittest.TestCase):
    def test_matches_hand_computation_at_even_money(self):
        # p=0.6, b=1.0 -> (1*0.6 - 0.4) / 1 = 0.20
        self.assertAlmostEqual(staking.kelly_fraction(0.6, 100), 0.20)

    def test_matches_hand_computation_on_an_underdog(self):
        # p=0.5, +150 -> b=1.5 -> (1.5*0.5 - 0.5)/1.5 = 0.1666...
        self.assertAlmostEqual(staking.kelly_fraction(0.5, 150), 0.25 / 1.5)

    def test_zero_when_price_is_exactly_fair(self):
        # At -150 the break-even probability is 0.60.
        self.assertAlmostEqual(staking.kelly_fraction(0.6, -150), 0.0)

    def test_zero_when_bet_is_negative_expectation(self):
        self.assertEqual(staking.kelly_fraction(0.4, -200), 0.0)

    def test_never_returns_negative(self):
        for p in (0.05, 0.1, 0.3):
            with self.subTest(p=p):
                self.assertGreaterEqual(staking.kelly_fraction(p, -500), 0.0)

    def test_bigger_edge_gives_bigger_fraction(self):
        small = staking.kelly_fraction(0.55, 100)
        large = staking.kelly_fraction(0.75, 100)
        self.assertGreater(large, small)


class TestFractionalKelly(unittest.TestCase):
    def test_quarter_kelly_is_a_quarter_of_full(self):
        full = staking.kelly_fraction(0.6, 100)
        quarter = staking.fractional_kelly(0.6, 100, kelly_multiplier=0.25,
                                           max_fraction=1.0)
        self.assertAlmostEqual(quarter, full * 0.25)

    def test_cap_binds_on_a_huge_edge(self):
        # p=0.95 at +200 is an enormous edge; the cap must still hold.
        capped = staking.fractional_kelly(0.95, 200, kelly_multiplier=1.0,
                                          max_fraction=0.02)
        self.assertAlmostEqual(capped, 0.02)

    def test_cap_is_never_exceeded_across_a_sweep(self):
        for p in (0.55, 0.7, 0.9, 0.99):
            for price in (-110, 100, 250, 900):
                with self.subTest(p=p, price=price):
                    f = staking.fractional_kelly(p, price, kelly_multiplier=1.0)
                    self.assertLessEqual(f, staking.DEFAULT_MAX_FRACTION)

    def test_rejects_bad_multiplier(self):
        for bad in (0.0, -0.5, 1.5):
            with self.subTest(bad=bad):
                with self.assertRaises(StakingError):
                    staking.fractional_kelly(0.6, 100, kelly_multiplier=bad)


class TestKellyStake(unittest.TestCase):
    def test_converts_fraction_to_currency(self):
        fraction = staking.fractional_kelly(0.6, 100)
        self.assertAlmostEqual(staking.kelly_stake(10_000, 0.6, 100),
                               10_000 * fraction)

    def test_capped_stake_on_large_bankroll(self):
        # 2% cap on 100k is 2k, no matter how good the bet looks.
        self.assertLessEqual(staking.kelly_stake(100_000, 0.99, 500), 2_000.0)


class TestSizeBet(unittest.TestCase):
    def test_kelly_is_refused_when_model_is_uncalibrated(self):
        result = staking.size_bet(10_000, 0.65, 100, method="kelly",
                                  calibrated=False)
        self.assertEqual(result["method"], "flat")
        self.assertEqual(result["requested_method"], "kelly")
        self.assertTrue(any("UNCALIBRATED" in w for w in result["warnings"]))

    def test_kelly_is_allowed_once_calibrated(self):
        result = staking.size_bet(10_000, 0.65, 100, method="kelly",
                                  calibrated=True)
        self.assertEqual(result["method"], "kelly")
        self.assertEqual(result["warnings"], [])

    def test_negative_expectation_sizes_to_zero(self):
        result = staking.size_bet(10_000, 0.40, -200, method="flat")
        self.assertEqual(result["stake"], 0.0)
        self.assertEqual(result["method"], "none")
        self.assertTrue(any("positive expected value" in w
                            for w in result["warnings"]))

    def test_fair_price_sizes_to_zero(self):
        # EV is exactly zero at the fair price, which is not a bet.
        result = staking.size_bet(10_000, 0.6, -150, method="flat")
        self.assertEqual(result["stake"], 0.0)

    def test_flat_is_the_default_method(self):
        self.assertEqual(staking.size_bet(10_000, 0.65, 100)["method"], "flat")

    def test_expected_value_is_reported(self):
        result = staking.size_bet(10_000, 0.55, 100)
        self.assertAlmostEqual(result["expected_value"], 0.10, places=9)

    def test_unknown_method_rejected(self):
        with self.assertRaises(StakingError):
            staking.size_bet(10_000, 0.65, 100, method="martingale")

    def test_rejects_invalid_probability(self):
        for bad in (0.0, 1.0, -0.2, 1.4):
            with self.subTest(bad=bad):
                with self.assertRaises(StakingError):
                    staking.size_bet(10_000, bad, 100)


class TestDefaultSizer(unittest.TestCase):
    def test_project_default_is_flat_and_says_why(self):
        cfg = staking.default_sizer()
        self.assertEqual(cfg["method"], "flat")
        self.assertIn("unvalidated", cfg["reason"])


if __name__ == "__main__":
    unittest.main()
