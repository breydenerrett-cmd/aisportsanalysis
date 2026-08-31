"""Interaction features: two matrix columns joined by "*".

V4's premise is that the market prices clubs while games are decided by a
unit meeting a specific weakness, so the compiler must express "this lineup
times what it faces tonight" as a first-class spec feature. These tests pin
the three properties that make an interaction honest:

- the per-side value is the PRODUCT, taken on each side BEFORE the
  away-minus-home differential (a product of differentials would be a
  different, wrong experiment);
- a missing component makes the side None, never zero -- half an interaction
  is not an interaction, and zero would silently count "unknown" as "no
  signal", the exact guess-over-blank move this project bans;
- a negative component flips the product's sign, because a "weakness" that
  is really a strength counts against the side claiming to exploit it.
"""

from __future__ import annotations

import unittest

from src.research import funnel
from tests.test_funnel import World, _spec

A, B = "lineup_platoon_share", "starter_platoon_gap"
INTERACTION = f"{A}*{B}"


def _row(away_a, away_b, home_a, home_b):
    return {"away_" + A: away_a, "away_" + B: away_b,
            "home_" + A: home_a, "home_" + B: home_b}


class ValidationTests(unittest.TestCase):
    def test_an_interaction_of_two_known_features_validates(self):
        spec = funnel.validate_spec(_spec("i", INTERACTION))
        self.assertEqual(spec["feature"], INTERACTION)

    def test_an_unknown_component_is_rejected_by_name(self):
        with self.assertRaises(funnel.FunnelError) as caught:
            funnel.validate_spec(_spec("i", f"{A}*not_a_column"))
        self.assertIn("not_a_column", str(caught.exception))

    def test_a_feature_times_itself_is_rejected(self):
        """x*x is x**2 -- a re-thresholded single feature, not an
        interaction, and letting it through would double-count one idea."""
        with self.assertRaises(funnel.FunnelError):
            funnel.validate_spec(_spec("i", f"{A}*{A}"))

    def test_three_way_products_are_rejected(self):
        with self.assertRaises(funnel.FunnelError):
            funnel.validate_spec(_spec("i", f"{A}*{B}*{A}"))


class SignalTests(unittest.TestCase):
    def test_the_differential_is_of_products_not_a_product_of_differentials(self):
        # away 0.8*0.10 = 0.08, home 0.5*0.02 = 0.01 -> +0.07. A product of
        # differentials would give (0.3)*(0.08) = 0.024: same sign here, but
        # a different experiment; the exact value is what pins the order.
        signal = funnel._signal(_row(0.8, 0.10, 0.5, 0.02), INTERACTION)
        self.assertAlmostEqual(signal, 0.07)

    def test_a_missing_component_silences_the_side_entirely(self):
        self.assertIsNone(funnel._signal(_row(0.8, None, 0.5, 0.02),
                                         INTERACTION))
        self.assertIsNone(funnel._signal(_row(0.8, 0.10, None, 0.02),
                                         INTERACTION))

    def test_a_negative_component_counts_against_the_side(self):
        # The away lineup is stacked (0.8) against a starter whose "platoon
        # weakness" is actually a strength (-0.10): the away product is
        # negative, so the signal favours home.
        signal = funnel._signal(_row(0.8, -0.10, 0.0, 0.0), INTERACTION)
        self.assertAlmostEqual(signal, -0.08)

    def test_single_features_still_read_exactly_as_before(self):
        self.assertAlmostEqual(
            funnel._signal(_row(0.8, 0.1, 0.5, 0.1), A), 0.3)


class EndToEndTests(unittest.TestCase):
    """One interaction spec through the whole funnel on the World fixture."""

    def test_an_interaction_spec_runs_the_funnel_end_to_end(self):
        world = World()
        for season in (2023, 2024):
            for day in range(40):
                # Backed club away; win 26 of 40 -> effect +0.15 vs 0.5.
                world.add_game(season, day, "Cincinnati Reds",
                               "Miami Marlins", home_won=(day % 20) >= 13,
                               fired_feature=None)
                row = world.matrix[season][-1]
                for name in funnel.NUMERIC_FEATURES:
                    row["away_" + name] = 0.0
                    row["home_" + name] = 0.0
                # away product 0.8 * 0.5 = 0.4, home product 0: fires at any
                # threshold up to 0.4 and backs the away side.
                row["away_" + A], row["away_" + B] = 0.8, 0.5
        rows = world.run([_spec("interaction_e2e", INTERACTION)])
        row = rows[0]
        self.assertGreaterEqual(row["level_reached"], 2)
        self.assertEqual(row["n_2023"], 40)
        self.assertAlmostEqual(row["effect_2023"], 0.15)


if __name__ == "__main__":
    unittest.main()
