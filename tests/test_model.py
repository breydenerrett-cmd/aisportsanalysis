"""Tests for src/model/dataset.py and src/model/logistic.py.

Two properties get the most attention: a time split must never leak, and the
missing-value strategy must surface the temporal bias it can introduce.
"""

import math
import tempfile
import unittest
from pathlib import Path

from src.model import dataset, logistic
from src.model.dataset import DatasetError
from src.model.logistic import ModelError


def row(pk, day, a=0.5, b=1.0, label=1, extra=None):
    base = {
        "game_pk": pk, "date": day, "away_team": "AAA", "home_team": "BBB",
        "feat_a": a, "feat_b": b,
        "away_sample_is_thin": False, "home_sample_is_thin": False,
        "either_sample_thin": False,
        "home_won": label,
    }
    if extra:
        base.update(extra)
    return base


def rows_over(n, start_day=1, month="05"):
    return [row(i, f"2025-{month}-{start_day + i:02d}", a=i / n, b=1 - i / n,
                label=i % 2) for i in range(n)]


class TestCandidateFeatures(unittest.TestCase):
    def test_identity_and_label_columns_are_excluded(self):
        features = dataset.candidate_features([row(1, "2025-05-01")])
        for excluded in ("game_pk", "date", "away_team", "home_team", "home_won"):
            self.assertNotIn(excluded, features)

    def test_quality_flags_are_excluded(self):
        # These describe data quality, not baseball. Including them lets the model
        # key on "this row is early season" instead of on the teams.
        features = dataset.candidate_features([row(1, "2025-05-01")])
        for flag in dataset.QUALITY_FLAG_COLUMNS:
            self.assertNotIn(flag, features)

    def test_real_features_survive(self):
        features = dataset.candidate_features([row(1, "2025-05-01")])
        self.assertEqual(sorted(features), ["feat_a", "feat_b"])

    def test_empty_rows_rejected(self):
        with self.assertRaises(DatasetError):
            dataset.candidate_features([])


class TestMissingValueStrategy(unittest.TestCase):
    def gapped(self):
        # feat_b is missing in the EARLY rows only -- the real pattern in this
        # dataset, where split rates are undefined until enough games are played.
        rows = []
        for i in range(20):
            value = None if i < 6 else float(i)
            rows.append(row(i, f"2025-05-{i + 1:02d}", a=i / 20.0,
                            b=value, label=i % 2))
        return rows

    def test_drop_columns_keeps_every_row(self):
        prepared = dataset.prepare(self.gapped(), strategy="drop_columns")
        self.assertEqual(prepared["report"]["rows_kept"], 20)
        self.assertEqual(prepared["features"], ["feat_a"])
        self.assertIn("feat_b", prepared["report"]["columns_dropped"])

    def test_drop_rows_keeps_every_column(self):
        prepared = dataset.prepare(self.gapped(), strategy="drop_rows")
        self.assertEqual(sorted(prepared["features"]), ["feat_a", "feat_b"])
        self.assertEqual(prepared["report"]["rows_kept"], 14)

    def test_drop_rows_flags_the_temporal_bias_it_introduces(self):
        # This is the point of the report. Dropping incomplete rows here deletes
        # exclusively early-season games, which silently biases the training set.
        prepared = dataset.prepare(self.gapped(), strategy="drop_rows")
        profile = prepared["report"]["dropped_date_profile"]
        self.assertEqual(profile["dropped"], 6)
        self.assertTrue(profile["biased"])
        self.assertEqual(profile["share_in_first_half"], 1.0)

    def test_drop_columns_introduces_no_temporal_bias(self):
        prepared = dataset.prepare(self.gapped(), strategy="drop_columns")
        self.assertFalse(prepared["report"]["dropped_date_profile"]["biased"])

    def test_missingness_report_counts_per_column(self):
        gaps = dataset.missingness(self.gapped())
        self.assertEqual(gaps["per_column"]["feat_b"], 6)
        self.assertEqual(gaps["per_column"]["feat_a"], 0)
        self.assertEqual(gaps["columns_with_gaps"], ["feat_b"])

    def test_unknown_strategy_rejected(self):
        with self.assertRaises(DatasetError):
            dataset.prepare(rows_over(5), strategy="impute")

    def test_all_columns_gapped_raises(self):
        rows = [row(i, f"2025-05-{i + 1:02d}", a=None, b=None) for i in range(3)]
        with self.assertRaises(DatasetError):
            dataset.prepare(rows, strategy="drop_columns")

    def test_row_without_a_label_is_rejected(self):
        bad = row(1, "2025-05-01")
        bad["home_won"] = None
        with self.assertRaises(DatasetError):
            dataset.prepare([bad])


class TestTimeSplit(unittest.TestCase):
    def split(self, n=100):
        return dataset.time_split(dataset.prepare(rows_over(n)))

    def test_splits_are_chronological_and_do_not_overlap(self):
        splits = self.split()
        self.assertLessEqual(splits["train"]["last_date"], splits["val"]["first_date"])
        self.assertLessEqual(splits["val"]["last_date"], splits["test"]["first_date"])

    def test_no_training_date_exceeds_any_test_date(self):
        # The leak this whole design exists to prevent.
        splits = self.split()
        latest_train = max(m["date"] for m in splits["train"]["meta"])
        earliest_test = min(m["date"] for m in splits["test"]["meta"])
        self.assertLessEqual(latest_train, earliest_test)

    def test_every_row_lands_in_exactly_one_split(self):
        splits = self.split(100)
        seen = [m["game_pk"] for k in ("train", "val", "test")
                for m in splits[k]["meta"]]
        self.assertEqual(len(seen), 100)
        self.assertEqual(len(set(seen)), 100)

    def test_fractions_are_respected(self):
        splits = dataset.time_split(dataset.prepare(rows_over(100)),
                                    train_frac=0.6, val_frac=0.2)
        self.assertEqual(splits["train"]["n"], 60)
        self.assertEqual(splits["val"]["n"], 20)
        self.assertEqual(splits["test"]["n"], 20)

    def test_base_rate_is_reported_per_split(self):
        for split in ("train", "val", "test"):
            self.assertIsNotNone(self.split()[split]["base_rate"])

    def test_fractions_leaving_no_test_split_are_rejected(self):
        with self.assertRaises(DatasetError):
            dataset.time_split(dataset.prepare(rows_over(50)),
                               train_frac=0.8, val_frac=0.2)

    def test_an_empty_split_is_rejected(self):
        with self.assertRaises(DatasetError):
            dataset.time_split(dataset.prepare(rows_over(4)),
                               train_frac=0.9, val_frac=0.05)


class TestScaler(unittest.TestCase):
    def test_scaled_training_data_has_zero_mean(self):
        matrix = [[1.0], [2.0], [3.0], [4.0]]
        scaled = dataset.apply_scaler(matrix, dataset.fit_scaler(matrix))
        self.assertAlmostEqual(sum(r[0] for r in scaled) / 4, 0.0, places=9)

    def test_scaled_training_data_has_unit_variance(self):
        matrix = [[1.0], [2.0], [3.0], [4.0]]
        scaled = dataset.apply_scaler(matrix, dataset.fit_scaler(matrix))
        mean = sum(r[0] for r in scaled) / 4
        variance = sum((r[0] - mean) ** 2 for r in scaled) / 4
        self.assertAlmostEqual(variance, 1.0, places=9)

    def test_a_constant_column_does_not_divide_by_zero(self):
        matrix = [[5.0], [5.0], [5.0]]
        scaled = dataset.apply_scaler(matrix, dataset.fit_scaler(matrix))
        self.assertTrue(all(math.isfinite(r[0]) for r in scaled))

    def test_scaler_fitted_on_train_applies_unchanged_to_test(self):
        # Refitting on test would leak its distribution into the transform.
        train = [[0.0], [10.0]]
        scaler = dataset.fit_scaler(train)
        scaled = dataset.apply_scaler([[5.0]], scaler)
        self.assertAlmostEqual(scaled[0][0], 0.0)

    def test_width_mismatch_is_rejected(self):
        scaler = dataset.fit_scaler([[1.0, 2.0]])
        with self.assertRaises(DatasetError):
            dataset.apply_scaler([[1.0]], scaler)

    def test_empty_matrix_rejected(self):
        with self.assertRaises(DatasetError):
            dataset.fit_scaler([])


class TestSigmoid(unittest.TestCase):
    def test_zero_maps_to_half(self):
        self.assertAlmostEqual(logistic.sigmoid(0.0), 0.5)

    def test_is_monotonic(self):
        values = [logistic.sigmoid(z) for z in (-5, -1, 0, 1, 5)]
        self.assertEqual(values, sorted(values))

    def test_does_not_overflow_at_extremes(self):
        # The naive form overflows around z = -750.
        for z in (-1000.0, 1000.0, -1e6, 1e6):
            with self.subTest(z=z):
                value = logistic.sigmoid(z)
                self.assertTrue(math.isfinite(value))
                self.assertTrue(0.0 <= value <= 1.0)

    def test_symmetry(self):
        self.assertAlmostEqual(logistic.sigmoid(2.0) + logistic.sigmoid(-2.0), 1.0)


class TestFit(unittest.TestCase):
    @staticmethod
    def separable(n=200):
        """A cleanly separable problem the model must be able to solve."""
        matrix, labels = [], []
        for i in range(n):
            x = -2.0 + 4.0 * i / n
            matrix.append([x])
            labels.append(1 if x > 0 else 0)
        return matrix, labels

    def test_learns_a_separable_problem(self):
        matrix, labels = self.separable()
        model = logistic.fit(matrix, labels, epochs=2000, l2=0.0)
        predictions = logistic.predict(model, matrix)
        accuracy = sum(
            (p > 0.5) == bool(y) for p, y in zip(predictions, labels)
        ) / len(labels)
        self.assertGreater(accuracy, 0.95)

    def test_learns_the_correct_direction(self):
        matrix, labels = self.separable()
        model = logistic.fit(matrix, labels, epochs=2000, l2=0.0)
        self.assertGreater(model["weights"][0], 0)

    def test_training_loss_decreases(self):
        matrix, labels = self.separable()
        model = logistic.fit(matrix, labels, epochs=500, l2=0.0)
        history = model["history"]
        self.assertLess(history[-1]["train_loss"], history[0]["train_loss"])

    def test_pure_noise_stays_near_the_base_rate(self):
        # No signal means predictions should sit close to the base rate rather
        # than becoming confident about nothing.
        matrix = [[float(i % 3)] for i in range(300)]
        labels = [i % 2 for i in range(300)]
        model = logistic.fit(matrix, labels, epochs=1500)
        predictions = logistic.predict(model, matrix)
        self.assertLess(max(predictions) - min(predictions), 0.25)

    def test_stronger_regularization_shrinks_weights(self):
        matrix, labels = self.separable()
        weak = logistic.fit(matrix, labels, epochs=800, l2=0.0)
        strong = logistic.fit(matrix, labels, epochs=800, l2=5.0)
        self.assertLess(abs(strong["weights"][0]), abs(weak["weights"][0]))

    def test_validation_selects_the_best_epoch_not_the_last(self):
        matrix, labels = self.separable(100)
        model = logistic.fit(matrix, labels, epochs=1200,
                             val_matrix=matrix, val_labels=labels, patience=100)
        self.assertIsNotNone(model["best_val_loss"])
        self.assertLessEqual(model["best_epoch"], model["epochs_run"] - 1)

    def test_reports_its_hyperparameters(self):
        matrix, labels = self.separable(50)
        model = logistic.fit(matrix, labels, learning_rate=0.25, l2=0.5, epochs=50)
        self.assertEqual(model["hyperparameters"]["learning_rate"], 0.25)
        self.assertEqual(model["hyperparameters"]["l2"], 0.5)

    def test_empty_matrix_rejected(self):
        with self.assertRaises(ModelError):
            logistic.fit([], [])

    def test_mismatched_lengths_rejected(self):
        with self.assertRaises(ModelError):
            logistic.fit([[1.0], [2.0]], [1])

    def test_bad_hyperparameters_rejected(self):
        matrix, labels = self.separable(20)
        for kwargs in ({"learning_rate": 0.0}, {"learning_rate": -1},
                       {"learning_rate": 50}, {"l2": -1}):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(ModelError):
                    logistic.fit(matrix, labels, **kwargs)

    def test_defaults_are_the_swept_values_not_the_broken_originals(self):
        # The original defaults (lr=0.1, patience=20) stopped at epoch 3 with
        # near-zero weights, which is indistinguishable from "no signal exists".
        self.assertEqual(logistic.DEFAULT_LEARNING_RATE, 0.3)
        self.assertGreaterEqual(logistic.DEFAULT_PATIENCE, 100)


class TestPredictAndScore(unittest.TestCase):
    def test_predictions_are_probabilities(self):
        model = {"weights": [1.0, -2.0], "intercept": 0.5}
        for p in logistic.predict(model, [[0.0, 0.0], [3.0, -3.0], [-9.0, 9.0]]):
            self.assertTrue(0.0 < p < 1.0)

    def test_feature_count_mismatch_is_rejected(self):
        with self.assertRaises(ModelError):
            logistic.predict_one([1.0, 2.0], 0.0, [1.0])

    def test_log_loss_of_a_perfect_prediction_is_near_zero(self):
        self.assertLess(logistic.log_loss([0.999999, 0.000001], [1, 0]), 1e-4)

    def test_log_loss_of_a_coin_flip_is_ln_two(self):
        self.assertAlmostEqual(logistic.log_loss([0.5] * 4, [1, 0, 1, 0]),
                               math.log(2))

    def test_log_loss_clamps_rather_than_returning_infinity(self):
        self.assertTrue(math.isfinite(logistic.log_loss([0.0], [1])))

    def test_log_loss_rejects_mismatched_lengths(self):
        with self.assertRaises(ModelError):
            logistic.log_loss([0.5], [1, 0])


class TestCoefficients(unittest.TestCase):
    def test_sorted_by_absolute_magnitude(self):
        model = {"weights": [0.1, -0.9, 0.4], "intercept": 0.0}
        names = ["small", "big_negative", "medium"]
        result = logistic.coefficients(model, names)
        self.assertEqual([c["feature"] for c in result],
                         ["big_negative", "medium", "small"])

    def test_sign_is_preserved(self):
        model = {"weights": [-0.9], "intercept": 0.0}
        self.assertLess(logistic.coefficients(model, ["x"])[0]["weight"], 0)

    def test_name_count_mismatch_rejected(self):
        with self.assertRaises(ModelError):
            logistic.coefficients({"weights": [1.0, 2.0], "intercept": 0.0}, ["x"])


class TestPersistence(unittest.TestCase):
    def payload(self):
        return ({"weights": [0.5, -0.25], "intercept": 0.1,
                 "hyperparameters": {"l2": 1.0}, "best_epoch": 42,
                 "best_val_loss": 0.68},
                {"means": [1.0, 2.0], "stds": [0.5, 1.5]},
                ["feat_a", "feat_b"])

    def test_round_trip_preserves_weights_and_scaler(self):
        model, scaler, features = self.payload()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "model.json"
            logistic.save(model, scaler, features, path)
            loaded = logistic.load(path)
        self.assertEqual(loaded["weights"], model["weights"])
        self.assertEqual(loaded["scaler"], scaler)
        self.assertEqual(loaded["features"], features)

    def test_saved_model_is_flagged_uncalibrated_against_the_market(self):
        # Beating a base rate is not beating a market. Anything consuming these
        # probabilities must be able to see that distinction.
        model, scaler, features = self.payload()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "model.json"
            logistic.save(model, scaler, features, path)
            loaded = logistic.load(path)
        self.assertFalse(loaded["calibrated"])
        self.assertIn("market", loaded["calibration_note"])

    def test_missing_file_raises(self):
        with self.assertRaises(ModelError):
            logistic.load("/nonexistent/model.json")

    def test_corrupt_file_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "model.json"
            path.write_text("{not json}")
            with self.assertRaises(ModelError):
                logistic.load(path)

    def test_incomplete_model_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "model.json"
            path.write_text('{"weights": [1.0]}')
            with self.assertRaises(ModelError):
                logistic.load(path)


if __name__ == "__main__":
    unittest.main()
