"""Phase 2A's mechanics, pinned by hand.

The scoring run itself needs the matrix and the odds store; these tests pin
everything that must be true regardless: the optimisers are optimisers, the
market offset is never fitted, the away_/home_ crossing is undone the way
matrix.py made it, nothing from the evaluation season reaches a constant,
folds never split a slate, and the sign convention is the Elo benchmark's.
"""

import math
import random
import unittest

from src.evolab import baseline
from src.research import elobench


def _sides(**kwargs):
    """Every base quantity present, overridable one at a time."""
    out = {}
    for name, _home, _away in baseline.BASE_QUANTITIES:
        out[name] = kwargs.get(name, (0.0, 0.0))
    return out


def _row(date, home_won, market=0.5, pk=None, **kwargs):
    return {"game_pk": pk or f"{date}-{home_won}",
            "date": date,
            "cutoff": date[:7] + "-01",
            "home_won": float(home_won),
            "market_home": market,
            "offset": baseline.logit(market),
            "books": 8,
            "distinct": True,
            "sides": _sides(**kwargs)}


def _synthetic(n=600, seed=3, coefficient=0.0):
    """Rows whose single informative column has a known coefficient."""
    rng = random.Random(seed)
    rows = []
    for i in range(n):
        date = f"2023-04-{(i % 28) + 1:02d}"
        market = min(max(0.5 + rng.gauss(0.0, 0.08), 0.05), 0.95)
        value = rng.gauss(0.0, 1.0)
        eta = baseline.logit(market) + coefficient * value
        won = 1.0 if rng.random() < baseline.sigmoid(eta) else 0.0
        row = _row(date, won, market=market, pk=str(i),
                   lineup_platoon_share=(value, 0.0))
        for name, _h, _a in baseline.BASE_QUANTITIES:
            if name != "lineup_platoon_share":
                row["sides"][name] = (rng.gauss(0.0, 1.0), rng.gauss(0.0, 1.0))
        rows.append(row)
    return rows


class MathTests(unittest.TestCase):
    def test_sigmoid_survives_extreme_arguments(self):
        self.assertEqual(baseline.sigmoid(1000.0), 1.0)
        self.assertEqual(baseline.sigmoid(-1000.0), 0.0)
        self.assertAlmostEqual(baseline.sigmoid(0.0), 0.5, places=12)

    def test_logit_and_sigmoid_round_trip(self):
        for p in (0.01, 0.25, 0.5, 0.73, 0.99):
            self.assertAlmostEqual(baseline.sigmoid(baseline.logit(p)), p,
                                   places=10)

    def test_log_loss_is_the_benchmark_s_log_loss(self):
        """The clamp must match elobench, or the two are not comparable."""
        for p, y in ((0.3, True), (0.3, False), (1e-12, True), (1.0, False)):
            self.assertAlmostEqual(baseline.log_loss(p, y),
                                   elobench._log_loss(p, y), places=12)

    def test_solve_returns_the_exact_solution(self):
        self.assertEqual(baseline.solve([[2.0, 1.0], [1.0, 3.0]], [5.0, 10.0]),
                         [1.0, 3.0])

    def test_solve_pivots_past_a_zero_leading_entry(self):
        answer = baseline.solve([[0.0, 2.0], [4.0, 1.0]], [4.0, 6.0])
        self.assertAlmostEqual(answer[0], 1.0, places=12)
        self.assertAlmostEqual(answer[1], 2.0, places=12)

    def test_a_singular_system_raises_rather_than_returning_a_number(self):
        with self.assertRaises(baseline.BaselineError):
            baseline.solve([[1.0, 2.0], [2.0, 4.0]], [1.0, 2.0])


class FitTests(unittest.TestCase):
    """Both optimisers, against cases whose answer is known in advance."""

    def setUp(self):
        rng = random.Random(11)
        self.true = [0.8, -0.5, 0.0]
        self.x, self.y, self.offsets = [], [], []
        for _ in range(3000):
            row = [rng.gauss(0.0, 1.0) for _ in self.true]
            offset = rng.gauss(0.2, 0.6)
            eta = offset + 0.15 + sum(a * b for a, b in zip(row, self.true))
            self.x.append(row)
            self.offsets.append(offset)
            self.y.append(1.0 if rng.random() < baseline.sigmoid(eta) else 0.0)

    def test_l2_recovers_a_planted_coefficient_when_barely_penalised(self):
        fitted = baseline.fit_l2(self.x, self.y, self.offsets, 1e-8)
        for estimate, planted in zip(fitted["beta"], self.true):
            self.assertAlmostEqual(estimate, planted, delta=0.12)

    def test_l1_and_l2_agree_when_neither_is_penalised(self):
        left = baseline.fit_l2(self.x, self.y, self.offsets, 1e-8)
        right = baseline.fit_l1(self.x, self.y, self.offsets, 1e-8)
        self.assertAlmostEqual(left["b0"], right["b0"], places=5)
        for a, b in zip(left["beta"], right["beta"]):
            self.assertAlmostEqual(a, b, places=5)

    def test_a_huge_l2_penalty_collapses_onto_the_intercept_only_fit(self):
        heavy = baseline.fit_l2(self.x, self.y, self.offsets, 1e9)
        alone = baseline.fit_intercept_only(self.y, self.offsets)
        self.assertAlmostEqual(heavy["b0"], alone["b0"], places=6)
        for value in heavy["beta"]:
            self.assertLess(abs(value), 1e-6)

    def test_a_huge_l1_penalty_zeroes_every_coefficient_exactly(self):
        heavy = baseline.fit_l1(self.x, self.y, self.offsets, 1e7)
        self.assertEqual(heavy["beta"], [0.0, 0.0, 0.0])
        alone = baseline.fit_intercept_only(self.y, self.offsets)
        self.assertAlmostEqual(heavy["b0"], alone["b0"], places=5)

    def test_the_penalty_shrinks_monotonically(self):
        sizes = [sum(abs(v) for v in
                     baseline.fit_l2(self.x, self.y, self.offsets, lam)["beta"])
                 for lam in (1.0, 100.0, 10000.0, 1000000.0)]
        self.assertEqual(sizes, sorted(sizes, reverse=True))

    def test_fitting_zero_rows_raises_rather_than_inventing_a_fit(self):
        with self.assertRaises(baseline.BaselineError):
            baseline.fit_l2([], [], [], 1.0)


class OffsetTests(unittest.TestCase):
    """The market's log-odds enters with its coefficient pinned at 1."""

    def test_a_null_model_reproduces_the_market_exactly(self):
        markets = [0.35, 0.5, 0.62, 0.9]
        offsets = [baseline.logit(p) for p in markets]
        predicted = baseline.predict([[] for _ in markets], offsets, 0.0, [])
        for got, want in zip(predicted, markets):
            self.assertAlmostEqual(got, want, places=10)

    def test_the_offset_shifts_the_log_odds_one_for_one(self):
        base = baseline.predict([[1.0]], [0.0], 0.2, [0.4])[0]
        shifted = baseline.predict([[1.0]], [1.3], 0.2, [0.4])[0]
        self.assertAlmostEqual(baseline.logit(shifted) - baseline.logit(base),
                               1.3, places=9)

    def test_the_offset_is_not_a_parameter_and_is_never_scaled(self):
        """Doubling every offset must change the fit; if the model could
        re-weight the market it would absorb the change instead."""
        rows = _synthetic(400, seed=5, coefficient=0.0)
        y = [r["home_won"] for r in rows]
        offsets = [r["offset"] for r in rows]
        doubled = [2.0 * o for o in offsets]
        self.assertNotAlmostEqual(
            baseline.fit_intercept_only(y, offsets)["b0"],
            baseline.fit_intercept_only(y, doubled)["b0"], places=6)


class CrossingTests(unittest.TestCase):
    """matrix.py crosses sides once; this module must undo it once."""

    def test_a_lineup_quantity_is_read_on_its_own_prefix(self):
        row = {"home_lineup_platoon_share": 0.7,
               "away_lineup_platoon_share": 0.3}
        sides = baseline.sides_for_row(row)
        self.assertEqual(sides["lineup_platoon_share"], (0.7, 0.3))

    def test_a_starter_quantity_is_read_on_the_opposite_prefix(self):
        """away_starter_* describes the starter the AWAY lineup faces --
        the HOME team's starter -- so the home side of the contrast reads
        the away_ prefix."""
        row = {"away_starter_velocity_gap": 1.5,
               "home_starter_velocity_gap": -2.0}
        sides = baseline.sides_for_row(row)
        self.assertEqual(sides["starter_velocity_gap"], (1.5, -2.0))

    def test_every_base_quantity_is_covered_and_named_once(self):
        names = [q[0] for q in baseline.BASE_QUANTITIES]
        self.assertEqual(len(names), len(set(names)))
        self.assertEqual(len(baseline.COLUMN_NAMES), 2 * len(names))

    def test_no_shared_history_is_a_fact_not_a_gap(self):
        row = {"home_lineup_vs_starter_history": {"pa": 0, "woba": None},
               "away_lineup_vs_starter_history": {"pa": 12, "woba": 0.31}}
        sides = baseline.sides_for_row(row)
        self.assertEqual(sides["history_pa"], (0.0, math.log1p(12)))
        self.assertEqual(sides["history_woba"], (None, 0.31))

    def test_a_missing_history_block_is_none_rather_than_zero(self):
        sides = baseline.sides_for_row({})
        self.assertEqual(sides["history_pa"], (None, None))
        self.assertEqual(sides["history_woba"], (None, None))


class DesignTests(unittest.TestCase):
    def test_constants_pool_both_sides_and_ignore_missing_values(self):
        rows = [_row("2023-04-01", 1, lineup_platoon_share=(0.6, None)),
                _row("2023-04-02", 0, lineup_platoon_share=(0.2, 0.4))]
        constants = baseline.impute_constants(rows)
        self.assertAlmostEqual(constants["lineup_platoon_share"],
                               (0.6 + 0.2 + 0.4) / 3.0, places=12)

    def test_a_quantity_never_observed_imputes_to_zero_not_to_a_guess(self):
        rows = [_row("2023-04-01", 1, lineup_platoon_share=(None, None))]
        self.assertEqual(
            baseline.impute_constants(rows)["lineup_platoon_share"], 0.0)

    def test_the_design_is_the_contrast_then_the_level(self):
        rows = [_row("2023-04-01", 1, top_minus_bottom=(0.5, 0.1))]
        constants = {q[0]: 0.0 for q in baseline.BASE_QUANTITIES}
        built = baseline.design(rows, constants)[0]
        index = baseline.COLUMN_NAMES.index("d_top_minus_bottom")
        level = baseline.COLUMN_NAMES.index("m_top_minus_bottom")
        self.assertAlmostEqual(built[index], 0.4, places=12)
        self.assertAlmostEqual(built[level], 0.3, places=12)

    def test_a_missing_side_takes_the_training_constant(self):
        rows = [_row("2023-04-01", 1, top_minus_bottom=(None, 0.1))]
        constants = {q[0]: 0.0 for q in baseline.BASE_QUANTITIES}
        constants["top_minus_bottom"] = 0.9
        built = baseline.design(rows, constants)[0]
        index = baseline.COLUMN_NAMES.index("d_top_minus_bottom")
        self.assertAlmostEqual(built[index], 0.8, places=12)

    def test_a_column_without_training_variance_is_dropped(self):
        rows = [_row("2023-04-01", 1, top_minus_bottom=(0.5, 0.1)),
                _row("2023-04-02", 0, top_minus_bottom=(0.9, 0.1))]
        constants = baseline.impute_constants(rows)
        scaling = baseline.standardisation(baseline.design(rows, constants))
        kept = {baseline.COLUMN_NAMES[j] for j in scaling["kept"]}
        self.assertIn("d_top_minus_bottom", kept)
        self.assertNotIn("d_lineup_platoon_share", kept)

    def test_standardised_columns_have_zero_mean_and_unit_deviation(self):
        rows = _synthetic(200, seed=9)
        constants = baseline.impute_constants(rows)
        raw = baseline.design(rows, constants)
        scaling = baseline.standardisation(raw)
        scaled = baseline.standardise(raw, scaling)
        for j in range(len(scaled[0])):
            column = [r[j] for r in scaled]
            mean = sum(column) / len(column)
            variance = sum((v - mean) ** 2 for v in column) / len(column)
            self.assertAlmostEqual(mean, 0.0, places=9)
            self.assertAlmostEqual(variance, 1.0, places=9)


class FoldTests(unittest.TestCase):
    def test_a_slate_is_never_split_across_folds(self):
        rows = [_row(f"2023-04-{(i % 9) + 1:02d}", i % 2, pk=str(i))
                for i in range(90)]
        assignment = baseline.date_folds(rows)
        by_date = {}
        for row, fold in zip(rows, assignment):
            by_date.setdefault(row["date"], set()).add(fold)
        for date, folds in by_date.items():
            self.assertEqual(len(folds), 1, f"{date} spans {folds}")

    def test_folds_are_deterministic_without_a_seed(self):
        rows = [_row(f"2023-04-{(i % 9) + 1:02d}", i % 2, pk=str(i))
                for i in range(90)]
        self.assertEqual(baseline.date_folds(rows), baseline.date_folds(rows))

    def test_cross_validation_needs_more_than_one_fold(self):
        rows = [_row("2023-04-01", i % 2, pk=str(i)) for i in range(10)]
        with self.assertRaises(baseline.BaselineError):
            baseline.cross_validate(rows, (1.0,))

    def test_pure_noise_features_select_the_strongest_penalty(self):
        """Nothing to learn -> cross-validation shrinks it all away."""
        rows = _synthetic(600, seed=21, coefficient=0.0)
        chosen = baseline.cross_validate(rows, (0.1, 1000000.0))["chosen"]
        self.assertEqual(chosen, 1000000.0)

    def test_a_planted_signal_selects_a_weaker_penalty(self):
        """The validator has to be able to say yes, or its no means nothing."""
        rows = _synthetic(900, seed=22, coefficient=1.2)
        chosen = baseline.cross_validate(rows, (1.0, 1000000.0))["chosen"]
        self.assertEqual(chosen, 1.0)


class EvaluateTests(unittest.TestCase):
    def setUp(self):
        self.train = _synthetic(500, seed=31, coefficient=0.0)
        self.hold = [dict(r, date=r["date"].replace("2023", "2024"))
                     for r in _synthetic(500, seed=32, coefficient=0.0)]

    def result(self, **kwargs):
        return baseline.evaluate(self.train, self.hold,
                                 penalties=(1.0, 10000.0), **kwargs)

    def test_nothing_from_the_evaluation_season_reaches_a_constant(self):
        """Scramble every held-out feature; the fit must not move."""
        before = self.result()
        rng = random.Random(99)
        for row in self.hold:
            row["sides"] = {name: (rng.gauss(0, 5), rng.gauss(0, 5))
                            for name, _h, _a in baseline.BASE_QUANTITIES}
        after = self.result()
        self.assertEqual(before["impute_constants"], after["impute_constants"])
        self.assertEqual(before["m1_intercept"], after["m1_intercept"])
        for norm in ("l2", "l1"):
            self.assertEqual(before["models"][norm]["coefficients"],
                             after["models"][norm]["coefficients"])
            self.assertEqual(before["models"][norm]["cv"]["chosen"],
                             after["models"][norm]["cv"]["chosen"])

    def test_the_run_is_deterministic(self):
        self.assertEqual(self.result(), self.result())

    def test_a_worse_forecast_scores_positive_by_convention(self):
        """Positive = the left model is worse, as BENCHMARK_ELO froze."""
        rows = [_row("2024-05-01", 1, market=0.6, pk="a"),
                _row("2024-05-02", 0, market=0.4, pk="b")]
        losses_market = [baseline.log_loss(r["market_home"], r["home_won"])
                         for r in rows]
        losses_worse = [baseline.log_loss(1.0 - r["market_home"],
                                          r["home_won"]) for r in rows]
        diffs = [w - m for w, m in zip(losses_worse, losses_market)]
        self.assertTrue(all(d > 0 for d in diffs))

    def test_evaluation_refuses_an_empty_side(self):
        with self.assertRaises(baseline.BaselineError):
            baseline.evaluate(self.train, [], penalties=(1.0,))

    def test_the_market_row_of_the_summary_is_the_market(self):
        result = self.result()
        n = len(self.hold)
        expected = sum(baseline.log_loss(r["market_home"], r["home_won"])
                       for r in self.hold) / n
        self.assertAlmostEqual(result["summary"]["m0_market"]["log_loss"],
                               round(expected, 5), places=5)


class LeakageCheckTests(unittest.TestCase):
    def test_moving_the_price_moves_no_design_column(self):
        train = _synthetic(60, seed=41)
        hold = _synthetic(60, seed=42)
        checks = baseline.leakage_checks(train, hold)
        self.assertEqual(checks["design_columns_moved_by_price"], 0)

    def test_a_cutoff_on_the_game_s_own_date_is_counted_separately(self):
        """A game on the 1st has cutoff == date. rebuilt gates on
        `game_date < cutoff` strictly, so that is not a leak -- but it is
        also not the same as `before`, and the check must not conflate
        them."""
        row = _row("2023-04-01", 1)
        self.assertEqual(row["cutoff"], "2023-04-01")
        checks = baseline.leakage_checks([row], [_row("2023-04-15", 0)])
        self.assertEqual(checks["train_cutoff_vs_game_date"],
                         {"before": 0, "equal": 1, "after": 0})
        self.assertEqual(checks["eval_cutoff_vs_game_date"],
                         {"before": 1, "equal": 0, "after": 0})

    def test_a_cutoff_after_the_game_is_the_one_that_counts_as_a_leak(self):
        row = dict(_row("2023-04-15", 1), cutoff="2023-05-01")
        checks = baseline.leakage_checks([row], [_row("2023-04-15", 0)])
        self.assertEqual(checks["train_cutoff_vs_game_date"]["after"], 1)

    def test_a_row_that_cannot_prove_its_cutoff_is_treated_as_unsafe(self):
        row = dict(_row("2023-04-15", 1), cutoff=None)
        checks = baseline.leakage_checks([row], [_row("2023-04-15", 0)])
        self.assertEqual(checks["train_cutoff_vs_game_date"]["after"], 1)

    def test_a_game_in_both_sets_is_reported_not_ignored(self):
        row = _row("2023-04-15", 1, pk="shared")
        checks = baseline.leakage_checks([row], [dict(row)])
        self.assertEqual(checks["train_eval_overlap"], 1)
        self.assertEqual(checks["duplicate_game_pks"], 1)


class SeasonGuardTests(unittest.TestCase):
    """2025 is tuning-only and 2026 is sealed; the guard is structural."""

    def test_the_tuning_season_is_refused(self):
        with self.assertRaises(baseline.BaselineError):
            baseline.build_rows(2025)

    def test_the_sealed_season_is_refused(self):
        with self.assertRaises(baseline.BaselineError):
            baseline.build_rows(2026)

    def test_the_split_is_the_pre_registered_one(self):
        self.assertEqual(baseline.TRAIN_SEASON, 2023)
        self.assertEqual(baseline.EVAL_SEASON, 2024)
        self.assertEqual(baseline.ALLOWED_SEASONS, (2023, 2024))


class BuildRowsTests(unittest.TestCase):
    """The join, on fixtures -- no store, no network."""

    def fixture(self):
        books = [{"key": f"b{i}", "markets": [{"key": "h2h", "outcomes": [
            {"name": "New York Mets", "price": 130},
            {"name": "Miami Marlins", "price": -150}]}]} for i in range(8)]
        quote = {"snapshot_at": "2023-05-06T18:00:00Z", "gap_minutes": 20.0,
                 "bookmakers": books}
        pairs = {"e1": {"event_id": "e1",
                        "commence_time": "2023-05-06T18:20:00Z",
                        "away_team": "New York Mets",
                        "home_team": "Miami Marlins",
                        "open": quote, "close": quote, "distinct": True}}
        results = {"77": {"game_pk": "77", "date": "2023-05-06",
                          "start_time_utc": "2023-05-06T18:20:00Z",
                          "away_team": "NYM", "home_team": "MIA",
                          "home_won": "1", "game_type": "R"}}
        matrix_rows = [{"game_pk": "77", "date": "2023-05-06",
                        "cutoff": "2023-05-01",
                        "home_top_minus_bottom": 0.05,
                        "away_top_minus_bottom": -0.02}]
        return matrix_rows, results, pairs

    def test_a_joined_game_carries_its_market_offset_and_its_outcome(self):
        matrix_rows, results, pairs = self.fixture()
        built = baseline.build_rows(2023, matrix_rows=matrix_rows,
                                    results=results, price_pairs=pairs)
        self.assertEqual(len(built["rows"]), 1)
        row = built["rows"][0]
        self.assertEqual(row["home_won"], 1.0)
        self.assertEqual(row["books"], 8)
        self.assertAlmostEqual(row["offset"],
                               baseline.logit(row["market_home"]), places=12)
        self.assertEqual(row["sides"]["top_minus_bottom"], (0.05, -0.02))

    def test_a_thin_consensus_is_excluded_with_its_reason(self):
        matrix_rows, results, pairs = self.fixture()
        pairs["e1"]["close"]["bookmakers"] = \
            pairs["e1"]["close"]["bookmakers"][:2]
        built = baseline.build_rows(2023, matrix_rows=matrix_rows,
                                    results=results, price_pairs=pairs)
        self.assertEqual(built["rows"], [])
        self.assertEqual(built["excluded"]["thin_consensus"], 1)

    def test_a_game_whose_own_event_is_absent_goes_unpriced(self):
        matrix_rows, results, pairs = self.fixture()
        results["77"]["start_time_utc"] = "2023-05-06T23:59:00Z"
        built = baseline.build_rows(2023, matrix_rows=matrix_rows,
                                    results=results, price_pairs=pairs)
        self.assertEqual(built["rows"], [])
        self.assertEqual(built["excluded"]["no_price_pair"], 1)

    def test_a_matrix_row_without_a_result_is_counted_not_dropped_silently(self):
        matrix_rows, results, pairs = self.fixture()
        built = baseline.build_rows(2023, matrix_rows=matrix_rows,
                                    results={}, price_pairs=pairs)
        self.assertEqual(built["excluded"]["no_result"], 1)


class NamespaceTests(unittest.TestCase):
    def test_the_artifact_stays_inside_the_lab_s_own_directory(self):
        self.assertEqual(baseline.DEFAULT_OUT_DIR.as_posix(),
                         "data/research/evolab")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
