"""Tests for src/core/calibration.py.

Every expected value here is derived from the definition of the metric, not
read back from the implementation. Synthetic cases with known answers -- a
perfect predictor, a coin flip, a confidently wrong predictor -- are the point:
they prove the instruments read correctly before any real model is measured.
"""

import math
import unittest

from src.core import calibration as cal


class TestBrierScore(unittest.TestCase):
    def test_perfect_predictor_scores_zero(self):
        preds = [1.0, 0.0, 1.0, 0.0]
        obs = [1, 0, 1, 0]
        self.assertAlmostEqual(cal.brier_score(preds, obs), 0.0)

    def test_always_half_scores_quarter(self):
        # (0.5 - o)^2 == 0.25 for either outcome.
        self.assertAlmostEqual(cal.brier_score([0.5] * 4, [1, 0, 1, 0]), 0.25)

    def test_confidently_wrong_scores_one(self):
        self.assertAlmostEqual(cal.brier_score([1.0, 0.0], [0, 1]), 1.0)

    def test_matches_hand_computation(self):
        # ((0.8-1)^2 + (0.3-0)^2) / 2 = (0.04 + 0.09) / 2 = 0.065
        self.assertAlmostEqual(cal.brier_score([0.8, 0.3], [1, 0]), 0.065)

    def test_better_predictions_score_lower(self):
        obs = [1, 1, 0, 0]
        good = cal.brier_score([0.9, 0.8, 0.2, 0.1], obs)
        bad = cal.brier_score([0.6, 0.5, 0.5, 0.4], obs)
        self.assertLess(good, bad)


class TestLogLoss(unittest.TestCase):
    def test_perfect_predictor_is_near_zero(self):
        self.assertLess(cal.log_loss([1.0, 0.0], [1, 0]), 1e-9)

    def test_always_half_equals_ln_two(self):
        self.assertAlmostEqual(cal.log_loss([0.5] * 4, [1, 0, 1, 0]), math.log(2))

    def test_matches_hand_computation(self):
        # -(ln(0.8) + ln(0.7)) / 2
        expected = -(math.log(0.8) + math.log(0.7)) / 2
        self.assertAlmostEqual(cal.log_loss([0.8, 0.3], [1, 0]), expected)

    def test_confident_miss_is_clamped_not_infinite(self):
        # A 0.0 prediction on a 1 outcome would be infinite without clamping.
        value = cal.log_loss([0.0], [1])
        self.assertTrue(math.isfinite(value))
        self.assertGreater(value, 30.0)

    def test_punishes_confident_errors_harder_than_brier(self):
        # Same Brier ordering, but log loss opens a much wider gap.
        obs = [1, 1]
        timid = cal.log_loss([0.6, 0.6], obs)
        confident_wrong = cal.log_loss([0.99, 0.01], obs)
        self.assertGreater(confident_wrong, timid)


class TestReliabilityCurve(unittest.TestCase):
    def test_returns_one_entry_per_bin_including_empty(self):
        curve = cal.reliability_curve([0.05, 0.95], [0, 1], bins=10)
        self.assertEqual(len(curve), 10)
        self.assertEqual(sum(b["count"] for b in curve), 2)
        self.assertTrue(any(b["count"] == 0 for b in curve))

    def test_perfectly_calibrated_data_has_no_gap(self):
        # 100 predictions at 0.60; exactly 60 succeed.
        preds = [0.6] * 100
        obs = [1] * 60 + [0] * 40
        curve = cal.reliability_curve(preds, obs, bins=10)
        populated = [b for b in curve if b["count"] > 0]
        self.assertEqual(len(populated), 1)
        self.assertAlmostEqual(populated[0]["observed_rate"], 0.6)
        self.assertAlmostEqual(populated[0]["gap"], 0.0)

    def test_overconfident_model_shows_negative_gap(self):
        # Says 90%, only wins 50%. Negative gap == overconfidence.
        preds = [0.9] * 10
        obs = [1] * 5 + [0] * 5
        curve = cal.reliability_curve(preds, obs, bins=10)
        bucket = next(b for b in curve if b["count"] > 0)
        self.assertLess(bucket["gap"], 0)
        self.assertAlmostEqual(bucket["gap"], 0.5 - 0.9)

    def test_probability_of_one_lands_in_top_bin(self):
        curve = cal.reliability_curve([1.0], [1], bins=10)
        self.assertEqual(curve[-1]["count"], 1)

    def test_probability_of_zero_lands_in_bottom_bin(self):
        curve = cal.reliability_curve([0.0], [0], bins=10)
        self.assertEqual(curve[0]["count"], 1)

    def test_bin_count_is_respected(self):
        self.assertEqual(len(cal.reliability_curve([0.5], [1], bins=4)), 4)

    def test_invalid_bin_count_rejected(self):
        for bad in (0, -1, 2.5, "ten"):
            with self.subTest(bad=bad):
                with self.assertRaises(cal.CalibrationError):
                    cal.reliability_curve([0.5], [1], bins=bad)

    def test_formatter_produces_a_row_per_bin_plus_header(self):
        curve = cal.reliability_curve([0.2, 0.8], [0, 1], bins=5)
        text = cal.format_reliability_curve(curve)
        self.assertEqual(len(text.splitlines()), 7)  # header + rule + 5 bins


class TestCalibrationErrors(unittest.TestCase):
    def test_perfect_calibration_has_zero_ece(self):
        preds = [0.6] * 100
        obs = [1] * 60 + [0] * 40
        self.assertAlmostEqual(cal.expected_calibration_error(preds, obs), 0.0)

    def test_ece_matches_hand_computation(self):
        # One bin, says 0.9, observes 0.5 -> gap 0.4.
        preds = [0.9] * 10
        obs = [1] * 5 + [0] * 5
        self.assertAlmostEqual(cal.expected_calibration_error(preds, obs), 0.4)

    def test_ece_is_weighted_by_bin_population(self):
        # 90 well-calibrated at 0.5, 10 badly calibrated at 0.95.
        preds = [0.5] * 90 + [0.95] * 10
        obs = [1] * 45 + [0] * 45 + [0] * 10
        ece = cal.expected_calibration_error(preds, obs)
        # The small bad bin contributes 10/100 * 0.95 = 0.095
        self.assertAlmostEqual(ece, 0.095, places=6)

    def test_max_error_exceeds_or_equals_average(self):
        preds = [0.5] * 90 + [0.95] * 10
        obs = [1] * 45 + [0] * 45 + [0] * 10
        self.assertGreaterEqual(
            cal.max_calibration_error(preds, obs),
            cal.expected_calibration_error(preds, obs),
        )


class TestBaselines(unittest.TestCase):
    def test_always_half_baseline_matches_direct_scores(self):
        obs = [1, 0, 1, 0]
        result = cal.baseline_always(0.5, obs)
        self.assertAlmostEqual(result["brier"], 0.25)
        self.assertAlmostEqual(result["log_loss"], math.log(2))

    def test_base_rate_baseline_uses_observed_frequency(self):
        obs = [1] * 60 + [0] * 40
        result = cal.baseline_base_rate(obs)
        self.assertAlmostEqual(result["mean_predicted"], 0.6, places=5)

    def test_base_rate_survives_a_degenerate_all_ones_set(self):
        # Would be log(0) without the boundary nudge.
        result = cal.baseline_base_rate([1, 1, 1])
        self.assertTrue(math.isfinite(result["log_loss"]))

    def test_score_all_reports_every_metric(self):
        result = cal.score_all([0.6] * 10, [1] * 6 + [0] * 4)
        for key in ("n", "brier", "log_loss", "ece", "max_ce",
                    "mean_predicted", "observed_rate"):
            self.assertIn(key, result)
        self.assertEqual(result["n"], 10)


class TestModelVersusMarket(unittest.TestCase):
    def test_better_model_is_reported_as_beating_the_market(self):
        obs = [1] * 60 + [0] * 40
        model = [0.6] * 100          # perfectly calibrated
        market = [0.5] * 100         # uninformative
        result = cal.compare(model, market, obs)
        self.assertTrue(result["model_beats_market"])
        self.assertGreater(result["log_loss_delta"], 0)

    def test_worse_model_is_reported_as_losing(self):
        obs = [1] * 60 + [0] * 40
        model = [0.5] * 100
        market = [0.6] * 100
        result = cal.compare(model, market, obs)
        self.assertFalse(result["model_beats_market"])
        self.assertLess(result["log_loss_delta"], 0)

    def test_identical_predictions_do_not_beat_the_market(self):
        # A tie is not a win. This guards against a >= creeping in.
        obs = [1, 0, 1, 0]
        preds = [0.5] * 4
        self.assertFalse(cal.compare(preds, preds, obs)["model_beats_market"])


class TestValidation(unittest.TestCase):
    def test_length_mismatch_rejected(self):
        with self.assertRaises(cal.CalibrationError):
            cal.brier_score([0.5, 0.5], [1])

    def test_empty_input_rejected(self):
        with self.assertRaises(cal.CalibrationError):
            cal.brier_score([], [])

    def test_out_of_range_prediction_rejected(self):
        for bad in (-0.1, 1.1):
            with self.subTest(bad=bad):
                with self.assertRaises(cal.CalibrationError):
                    cal.brier_score([bad], [1])

    def test_non_binary_outcome_rejected(self):
        for bad in (2, 0.5, "win", None):
            with self.subTest(bad=bad):
                with self.assertRaises(cal.CalibrationError):
                    cal.brier_score([0.5], [bad])

    def test_boolean_outcomes_are_accepted(self):
        self.assertAlmostEqual(cal.brier_score([1.0, 0.0], [True, False]), 0.0)

    def test_nan_prediction_rejected(self):
        with self.assertRaises(cal.CalibrationError):
            cal.brier_score([float("nan")], [1])

    def test_boundary_predictions_are_allowed(self):
        # 0.0 and 1.0 are legal predictions; log loss clamps them internally.
        self.assertAlmostEqual(cal.brier_score([0.0, 1.0], [0, 1]), 0.0)


if __name__ == "__main__":
    unittest.main()
