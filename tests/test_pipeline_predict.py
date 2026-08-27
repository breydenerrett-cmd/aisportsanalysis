"""Tests for src/pipeline/predict.py.

The centrepiece is TestIgnoranceCheck. A flat model subtracted from a confident market
produces its largest "disagreements" on the games it understands least, and that looks
exactly like finding the biggest mispricings. Catching it is the difference between a
useful tool and one that loses money with conviction.
"""

import unittest

from src.pipeline import predict


MODEL = {
    "weights": [0.5, -0.3],
    "intercept": 0.1,
    "features": ["diff_win_pct", "diff_run_diff_pg"],
    "scaler": {"means": [0.0, 0.0], "stds": [1.0, 1.0]},
}


def prediction(home_prob=0.55, away="AAA", home="BBB"):
    return {
        "game_pk": 1, "away_team": away, "home_team": home,
        "date": "2026-08-27", "home_probability": home_prob,
        "away_probability": 1 - home_prob, "usable": True, "reason": None,
    }


class TestCompareToMarket(unittest.TestCase):
    def test_market_probability_is_devigged(self):
        # -150/+130 sums to about 1.035 raw; the fair value must be below the raw.
        result = predict.compare_to_market(prediction(0.60), 130, -150)
        self.assertTrue(result["comparable"])
        self.assertLess(result["market_home_fair"], 0.60)
        self.assertGreater(result["market_margin"], 0)

    def test_fair_probabilities_sum_to_one(self):
        result = predict.compare_to_market(prediction(), 130, -150)
        self.assertAlmostEqual(
            result["market_home_fair"] + result["market_away_fair"], 1.0, places=6)

    def test_disagreement_is_model_minus_market(self):
        result = predict.compare_to_market(prediction(0.60), -110, -110)
        # A -110/-110 market de-vigs to exactly 0.50 a side.
        self.assertAlmostEqual(result["market_home_fair"], 0.5, places=6)
        self.assertAlmostEqual(result["disagreement_home"], 0.10, places=6)

    def test_model_favours_home_when_gap_is_positive(self):
        self.assertEqual(
            predict.compare_to_market(prediction(0.60), -110, -110)["model_favours"],
            "home")

    def test_model_favours_away_when_gap_is_negative(self):
        self.assertEqual(
            predict.compare_to_market(prediction(0.40), -110, -110)["model_favours"],
            "away")

    def test_field_is_named_disagreement_not_edge(self):
        # The label is what people remember. "Edge" is a claim this cannot support.
        result = predict.compare_to_market(prediction(), -110, -110)
        self.assertIn("disagreement_home", result)
        self.assertNotIn("edge", result)

    def test_unusable_prediction_is_not_comparable(self):
        bad = {**prediction(), "home_probability": None, "reason": "missing features"}
        self.assertFalse(predict.compare_to_market(bad, -110, -110)["comparable"])

    def test_invalid_prices_are_reported_not_raised(self):
        result = predict.compare_to_market(prediction(), 0, -110)
        self.assertFalse(result["comparable"])
        self.assertIn("unusable", result["reason"])


class TestRobustness(unittest.TestCase):
    def test_a_clear_disagreement_survives_every_method(self):
        result = predict.disagreement_is_robust(prediction(0.70), -110, -110)
        self.assertTrue(result["robust"])
        self.assertEqual(len(result["by_method"]), 3)

    def test_a_marginal_disagreement_flips_between_methods(self):
        # On a lopsided book the methods genuinely diverge. For 1200/-2000 the fair
        # home probability is 0.9253 (proportional), 0.9377 (shin), 0.9460 (power).
        # A model landing INSIDE that window is judged to favour home by one method
        # and away by another -- the gap is an artefact of the de-vig choice, not a
        # property of the model, and must not be treated as real.
        for probability in (0.93, 0.935, 0.94):
            with self.subTest(probability=probability):
                result = predict.disagreement_is_robust(prediction(probability),
                                                        1200, -2000)
                self.assertFalse(result["robust"])
                self.assertIn("disagree", result["reason"])

    def test_a_disagreement_outside_the_window_stays_robust(self):
        # Below every method's fair value, so all three agree the model favours away.
        result = predict.disagreement_is_robust(prediction(0.85), 1200, -2000)
        self.assertTrue(result["robust"])

    def test_spread_between_methods_is_reported(self):
        result = predict.disagreement_is_robust(prediction(0.60), 1200, -2000)
        self.assertGreater(result["spread"], 0)

    def test_unusable_prices_report_not_robust(self):
        self.assertFalse(
            predict.disagreement_is_robust(prediction(), 0, -110)["robust"])


class TestIgnoranceCheck(unittest.TestCase):
    """The failure mode: flat model minus confident market equals fake insight."""

    @staticmethod
    def slate(model_probs, market_probs):
        out = []
        for i, (m, k) in enumerate(zip(model_probs, market_probs)):
            out.append({
                "comparable": True, "game_pk": i,
                "home_probability": m, "market_home_fair": k,
                "disagreement_home": m - k, "disagreement_abs": abs(m - k),
            })
        return out

    def test_a_flat_model_against_a_spread_market_is_flagged(self):
        # The real situation: model always ~0.53, market ranges 0.33 to 0.59.
        model = [0.53, 0.55, 0.54, 0.56, 0.52, 0.55]
        market = [0.33, 0.48, 0.49, 0.53, 0.52, 0.59]
        result = predict.ignorance_check(self.slate(model, market))
        self.assertTrue(result["model_is_flat"])
        self.assertFalse(result["ranking_is_meaningful"])
        self.assertIn("barely discriminating", result["warning"])

    def test_flatness_alone_disqualifies_the_ranking(self):
        # Requiring BOTH flatness and high correlation would let a nearly-constant
        # model pass whenever one slate's correlation happened to land low -- which
        # is precisely the case that most needs the warning.
        model = [0.53] * 6
        market = [0.40, 0.45, 0.50, 0.55, 0.60, 0.65]
        result = predict.ignorance_check(self.slate(model, market))
        self.assertTrue(result["model_is_flat"])
        self.assertFalse(result["ranking_is_meaningful"])

    def test_a_discriminating_model_is_not_flagged(self):
        model = [0.35, 0.45, 0.50, 0.58, 0.65, 0.72]
        market = [0.38, 0.44, 0.51, 0.56, 0.63, 0.70]
        result = predict.ignorance_check(self.slate(model, market))
        self.assertFalse(result["model_is_flat"])
        self.assertTrue(result["ranking_is_meaningful"])
        self.assertIsNone(result["warning"])

    def test_correlation_cannot_raise_the_alarm_on_a_tiny_sample(self):
        # Six games is not a sample; correlation on it is noise.
        model = [0.50, 0.52, 0.51, 0.53, 0.50, 0.52]
        market = [0.30, 0.40, 0.50, 0.60, 0.70, 0.80]
        result = predict.ignorance_check(self.slate(model, market))
        self.assertFalse(result["correlation_is_meaningful"])
        self.assertFalse(result["disagreement_driven_by_market"])

    def test_correlation_can_raise_the_alarm_on_a_real_sample(self):
        # 24 games, model nearly constant but with enough spread to dodge the
        # flatness test, disagreement tracking market confidence exactly.
        market = [0.30 + 0.02 * i for i in range(24)]
        model = [0.55 + 0.004 * i for i in range(24)]
        result = predict.ignorance_check(self.slate(model, market))
        self.assertTrue(result["correlation_is_meaningful"])
        self.assertFalse(result["ranking_is_meaningful"])

    def test_spread_ratio_is_reported(self):
        model = [0.52, 0.53, 0.54]
        market = [0.30, 0.50, 0.70]
        result = predict.ignorance_check(self.slate(model, market))
        self.assertLess(result["spread_ratio"], 0.5)

    def test_too_few_games_is_not_checked(self):
        result = predict.ignorance_check(self.slate([0.5, 0.5], [0.5, 0.5]))
        self.assertFalse(result["checked"])
        self.assertIn("at least 3", result["reason"])

    def test_non_comparable_entries_are_excluded(self):
        rows = self.slate([0.5] * 3, [0.5] * 3) + [{"comparable": False}]
        self.assertEqual(predict.ignorance_check(rows)["games"], 3)


class TestCorrelationHelper(unittest.TestCase):
    def test_perfect_positive_correlation(self):
        self.assertAlmostEqual(
            predict._correlation([1, 2, 3, 4], [2, 4, 6, 8]), 1.0, places=9)

    def test_perfect_negative_correlation(self):
        self.assertAlmostEqual(
            predict._correlation([1, 2, 3, 4], [8, 6, 4, 2]), -1.0, places=9)

    def test_constant_series_returns_none(self):
        self.assertIsNone(predict._correlation([1, 1, 1, 1], [1, 2, 3, 4]))

    def test_too_short_returns_none(self):
        self.assertIsNone(predict._correlation([1, 2], [3, 4]))

    def test_stdev_of_a_constant_series_is_zero(self):
        self.assertEqual(predict._stdev([5, 5, 5]), 0.0)


class TestPredictGame(unittest.TestCase):
    def game(self, **kwargs):
        base = {"game_pk": 1, "away_team": "AAA", "home_team": "BBB",
                "date": "2026-08-27", "start_time_utc": "2026-08-27T23:00:00Z"}
        base.update(kwargs)
        return base

    def test_missing_features_make_a_game_unusable_rather_than_guessed(self):
        result = predict.predict_game(MODEL, {}, self.game())
        self.assertFalse(result["usable"])
        self.assertIsNone(result["home_probability"])
        self.assertIn("unavailable", result["reason"])

    def test_missing_teams_raises(self):
        with self.assertRaises(predict.PredictionError):
            predict.predict_game(MODEL, {}, self.game(home_team=None))

    def test_missing_date_raises(self):
        with self.assertRaises(predict.PredictionError):
            predict.predict_game(MODEL, {}, self.game(date=None))


class TestPredictSlate(unittest.TestCase):
    def test_warning_is_always_present(self):
        result = predict.predict_slate(MODEL, {}, [])
        self.assertIn("not edges", result["warning"])

    def test_unpredictable_games_are_separated_not_dropped(self):
        games = [{"game_pk": 1, "away_team": "AAA", "home_team": "BBB",
                  "date": "2026-08-27"}]
        result = predict.predict_slate(MODEL, {}, games)
        self.assertEqual(result["count"], 0)
        self.assertEqual(len(result["unusable"]), 1)

    def test_empty_slate_is_not_an_error(self):
        result = predict.predict_slate(MODEL, {}, [])
        self.assertEqual(result["count"], 0)
        self.assertIsNone(result["mean_disagreement"])


if __name__ == "__main__":
    unittest.main()
