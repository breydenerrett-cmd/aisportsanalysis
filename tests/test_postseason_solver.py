"""tests/test_postseason_solver.py -- C1a: the exact absorbing-recursion
series solver (src/analysis/postseason.py) and its Monte Carlo cross-check.

Every test here targets one of the REQUIRED behaviours named in the C1a
task: symmetric fairness, the p=0/p=1 degenerate cases, the closed-form
best-of-three identity, the reversed-home/away mirror identity, clinching
stopping the series, the length distribution summing to one, exact-vs-Monte
Carlo agreement under a reproducible seed, and Monte Carlo sampling error
being reported separately from (never blended with) model/scenario
uncertainty.

`HistoricalMechanicsValidationTests` additionally checks the solver's own
notion of "first to k wins, clinch stops the series" against what actually
happened in 131 real postseason games / 33 series, 2023-2025
(data/historical/mlb_results.csv). This is historical observation used for
MECHANICS validation only -- no probability anywhere in this file is fitted,
estimated, or tuned from that data, and the read is explicitly bounded to
dates before 2026-01-01 so it can never start silently reading sealed 2026
rows once the 2026 postseason lands in the same file.
"""

from __future__ import annotations

import csv
import unittest
from pathlib import Path

from src.analysis import postseason as ps

REPO = Path(__file__).resolve().parent.parent
HISTORICAL_RESULTS = REPO / "data" / "historical" / "mlb_results.csv"


class FairSeriesTests(unittest.TestCase):
    """Fair, equal teams under symmetric assumptions -> 0.5, for every
    series length this project uses."""

    def test_symmetric_p_half_gives_half_for_every_k(self):
        for k in (1, 2, 3, 4):
            probs = [0.5] * (2 * k - 1)
            result = ps.exact_series_probability(probs, k)
            self.assertAlmostEqual(0.5, result["p_win"], places=9, msg=f"k={k}")
            self.assertAlmostEqual(0.5, result["p_loss"], places=9, msg=f"k={k}")


class DegenerateTests(unittest.TestCase):
    """p=0 and p=1 degenerate cases: a certainty every game is a certainty
    over the series, clinched in exactly k games."""

    def test_p_one_every_game_wins_in_exactly_k_games(self):
        for k in (1, 2, 3, 4):
            probs = [1.0] * (2 * k - 1)
            result = ps.exact_series_probability(probs, k)
            self.assertEqual(1.0, result["p_win"], f"k={k}")
            self.assertEqual(0.0, result["p_loss"], f"k={k}")
            self.assertEqual({k: 1.0}, result["length_probs"], f"k={k}")

    def test_p_zero_every_game_loses_in_exactly_k_games(self):
        for k in (1, 2, 3, 4):
            probs = [0.0] * (2 * k - 1)
            result = ps.exact_series_probability(probs, k)
            self.assertEqual(0.0, result["p_win"], f"k={k}")
            self.assertEqual(1.0, result["p_loss"], f"k={k}")
            self.assertEqual({k: 1.0}, result["length_probs"], f"k={k}")


class ConstantPFormulaTests(unittest.TestCase):
    """Constant-p best-of-three equals 3p^2 - 2p^3 exactly (the standard
    closed form: win in 2 (p^2) or win in 3 after splitting the first two
    (2p^2(1-p)))."""

    def test_matches_closed_form_across_p(self):
        for p in (0.01, 0.1, 0.3, 0.5, 0.6, 0.65, 0.9, 0.99):
            result = ps.exact_series_probability([p, p, p], 2)
            expected = 3 * p**2 - 2 * p**3
            self.assertAlmostEqual(expected, result["p_win"], places=12,
                                   msg=f"p={p}")


class ReversedHomeAwayTests(unittest.TestCase):
    """Reversed home/away identities mirror correctly: swapping which team
    is 'designated' AND flipping the home pattern must produce exactly
    complementary per-game probabilities, and therefore exactly
    complementary series outcomes."""

    def test_per_game_probabilities_are_exact_complements(self):
        pattern = (True, True, False, False, True)  # DS 2-2-1, team A's view
        p_neutral, home_edge = 0.55, 0.04
        probs_a = ps.game_probs_from_pattern(p_neutral, pattern, home_edge=home_edge)
        reversed_pattern = tuple(not f for f in pattern)
        probs_b = ps.game_probs_from_pattern(1.0 - p_neutral, reversed_pattern,
                                             home_edge=home_edge)
        for a, b in zip(probs_a, probs_b):
            self.assertAlmostEqual(a, 1.0 - b, places=12)

    def test_series_outcomes_mirror(self):
        pattern = (True, True, False, False, True)
        p_neutral, home_edge = 0.55, 0.04
        probs_a = ps.game_probs_from_pattern(p_neutral, pattern, home_edge=home_edge)
        probs_b = ps.game_probs_from_pattern(1.0 - p_neutral,
                                             tuple(not f for f in pattern),
                                             home_edge=home_edge)
        result_a = ps.exact_series_probability(probs_a, k=3)
        result_b = ps.exact_series_probability(probs_b, k=3)
        self.assertAlmostEqual(result_a["p_win"], result_b["p_loss"], places=9)
        self.assertAlmostEqual(result_a["p_loss"], result_b["p_win"], places=9)

    def test_all_true_home_pattern_reverses_to_all_false(self):
        # Wild Card: every game at the higher seed. The lower seed's mirror
        # pattern must be all-road.
        probs_a = ps.game_probs_from_pattern(0.6, (True, True, True), home_edge=0.03)
        probs_b = ps.game_probs_from_pattern(0.4, (False, False, False), home_edge=0.03)
        for a, b in zip(probs_a, probs_b):
            self.assertAlmostEqual(a, 1.0 - b, places=12)


class ClinchTests(unittest.TestCase):
    """Clinching stops the series: no games played after k wins.

    Proven by planting float('nan') at every index a correct implementation
    must never reach -- exact_series_probability raises PostseasonError the
    instant it reads an out-of-[0,1] value (NaN included), so if the code
    ever touched a poisoned index these tests would fail loudly instead of
    silently passing.
    """

    def test_exact_solver_never_touches_a_game_past_an_early_clinch(self):
        for k in (2, 3, 4):
            probs = [1.0] * k + [float("nan")] * (k - 1)
            result = ps.exact_series_probability(probs, k)
            self.assertEqual(1.0, result["p_win"])
            self.assertEqual({k: 1.0}, result["length_probs"])

    def test_exact_solver_never_touches_the_tail_after_a_mid_series_clinch(self):
        # Best-of-five: win, lose, win, win -> clinched 3-1 in 4 games; the
        # 5th game's (poisoned) probability must never be read.
        probs = [1.0, 0.0, 1.0, 1.0, float("nan")]
        result = ps.exact_series_probability(probs, 3)
        self.assertEqual(1.0, result["p_win"])
        self.assertEqual({4: 1.0}, result["length_probs"])

    def test_monte_carlo_never_touches_a_game_past_the_clinch(self):
        for k in (2, 3, 4):
            probs = [1.0] * k + [float("nan")] * (k - 1)
            result = ps.simulate_series(probs, k, n_sims=500, seed=1)
            self.assertEqual(1.0, result["p_win"])
            self.assertEqual({k: 1.0}, result["length_probs"])


class LengthDistributionTests(unittest.TestCase):
    """Series-length probabilities sum to 1, and the win/loss split of the
    length distribution is internally consistent with p_win/p_loss."""

    CASES = (
        ([0.5] * 7, 4),
        ([0.6, 0.4, 0.55, 0.5, 0.5, 0.45, 0.6], 4),
        ([0.7, 0.3, 0.65], 2),
        ([0.9, 0.1, 0.5, 0.5, 0.5], 3),
        ([0.15, 0.85, 0.5, 0.5, 0.5], 3),
    )

    def test_length_probabilities_sum_to_one(self):
        for probs, k in self.CASES:
            result = ps.exact_series_probability(probs, k)
            total = sum(result["length_probs"].values())
            self.assertAlmostEqual(1.0, total, places=9, msg=f"{probs}, k={k}")

    def test_win_loss_length_split_is_internally_consistent(self):
        for probs, k in self.CASES:
            result = ps.exact_series_probability(probs, k)
            self.assertAlmostEqual(result["p_win"],
                                   sum(result["length_probs_win"].values()),
                                   places=9)
            self.assertAlmostEqual(result["p_loss"],
                                   sum(result["length_probs_loss"].values()),
                                   places=9)
            self.assertAlmostEqual(1.0, result["p_win"] + result["p_loss"], places=9)
            for n in result["length_probs"]:
                self.assertAlmostEqual(
                    result["length_probs"][n],
                    result["length_probs_win"].get(n, 0.0)
                    + result["length_probs_loss"].get(n, 0.0),
                    places=9)

    def test_no_length_below_k_or_above_2k_minus_1(self):
        for probs, k in self.CASES:
            result = ps.exact_series_probability(probs, k)
            for n in result["length_probs"]:
                self.assertGreaterEqual(n, k)
                self.assertLessEqual(n, 2 * k - 1)


class ExactVsMonteCarloTests(unittest.TestCase):
    """Exact vs Monte Carlo agree within a stated numerical tolerance, under
    a reproducible seed."""

    TOLERANCE = 0.01
    N_SIMS = 60000

    def test_agree_within_tolerance_best_of_five_varying_p(self):
        probs = [0.62, 0.58, 0.40, 0.55, 0.50]
        exact = ps.exact_series_probability(probs, 3)
        mc = ps.simulate_series(probs, 3, n_sims=self.N_SIMS, seed=20260924)
        self.assertLess(abs(exact["p_win"] - mc["p_win"]), self.TOLERANCE)

    def test_agree_within_tolerance_best_of_seven_constant_p(self):
        probs = [0.53] * 7
        exact = ps.exact_series_probability(probs, 4)
        mc = ps.simulate_series(probs, 4, n_sims=self.N_SIMS, seed=42)
        self.assertLess(abs(exact["p_win"] - mc["p_win"]), self.TOLERANCE)

    def test_agree_within_tolerance_best_of_three(self):
        probs = [0.3, 0.7, 0.45]
        exact = ps.exact_series_probability(probs, 2)
        mc = ps.simulate_series(probs, 2, n_sims=self.N_SIMS, seed=99)
        self.assertLess(abs(exact["p_win"] - mc["p_win"]), self.TOLERANCE)

    def test_reproducible_seed_gives_bit_identical_output(self):
        probs = [0.5, 0.55, 0.45, 0.6, 0.4]
        r1 = ps.simulate_series(probs, 3, n_sims=5000, seed=7)
        r2 = ps.simulate_series(probs, 3, n_sims=5000, seed=7)
        self.assertEqual(r1, r2)

    def test_different_seeds_generally_disagree(self):
        probs = [0.5, 0.55, 0.45, 0.6, 0.4]
        r1 = ps.simulate_series(probs, 3, n_sims=200, seed=1)
        r2 = ps.simulate_series(probs, 3, n_sims=200, seed=2)
        self.assertNotEqual(r1["p_win"], r2["p_win"])


class MonteCarloErrorIsSeparateFromModelUncertaintyTests(unittest.TestCase):
    """Monte Carlo error is reported SEPARATELY from model uncertainty: the
    only error this module can measure is its own sampling error, and nea
    caller could accidentally read it as anything richer than that."""

    def test_standard_error_shrinks_like_one_over_sqrt_n(self):
        probs = [0.55, 0.45, 0.6, 0.4, 0.5, 0.5, 0.5]
        small = ps.simulate_series(probs, 4, n_sims=1000, seed=3)
        big = ps.simulate_series(probs, 4, n_sims=100000, seed=3)
        ratio = small["standard_error"] / big["standard_error"]
        # sampling error scales as 1/sqrt(n); 100x the sims -> ~10x smaller
        # error. Wide bounds because this is one fixed-seed draw, not a
        # limit -- the point is the right order of magnitude, not a precise
        # constant.
        self.assertGreater(ratio, 5.0)
        self.assertLess(ratio, 20.0)

    def test_result_carries_no_field_claiming_to_be_model_uncertainty(self):
        result = ps.simulate_series([0.5] * 3, 2, n_sims=100, seed=1)
        self.assertIn("standard_error", result)
        for forbidden in ("model_uncertainty", "combined_error", "total_error",
                          "confidence"):
            self.assertNotIn(forbidden, result)


class GameProbsFromPatternTests(unittest.TestCase):
    def test_home_edge_moves_probability_the_right_direction(self):
        probs = ps.game_probs_from_pattern(0.5, [True, False], home_edge=0.05)
        self.assertAlmostEqual(0.55, probs[0], places=9)
        self.assertAlmostEqual(0.45, probs[1], places=9)

    def test_clips_to_avoid_fabricated_certainty(self):
        probs = ps.game_probs_from_pattern(0.98, [True, True, True], home_edge=0.10)
        self.assertTrue(all(p <= 0.99 for p in probs))
        probs = ps.game_probs_from_pattern(0.02, [False, False], home_edge=0.10)
        self.assertTrue(all(p >= 0.01 for p in probs))

    def test_rejects_p_neutral_out_of_range(self):
        with self.assertRaises(ps.PostseasonError):
            ps.game_probs_from_pattern(1.5, [True], home_edge=0.02)


class ValidationTests(unittest.TestCase):
    def test_k_must_be_a_positive_integer(self):
        for bad_k in (0, -1, 1.5, "2", True):
            with self.assertRaises(ps.PostseasonError):
                ps.exact_series_probability([0.5, 0.5, 0.5], bad_k)

    def test_too_few_probabilities_raises(self):
        with self.assertRaises(ps.PostseasonError):
            ps.exact_series_probability([0.5, 0.5], 3)  # best-of-5 needs 5

    def test_out_of_range_probability_raises_when_actually_read(self):
        with self.assertRaises(ps.PostseasonError):
            ps.exact_series_probability([1.5, 0.5, 0.5], 2)

    def test_n_sims_must_be_a_positive_integer(self):
        with self.assertRaises(ps.PostseasonError):
            ps.simulate_series([0.5, 0.5, 0.5], 2, n_sims=0, seed=1)


class HistoricalMechanicsValidationTests(unittest.TestCase):
    """MECHANICS validation against 131 real postseason games / 33 series,
    2023-2025 (data/historical/mlb_results.csv): does 'first to k wins,
    clinch stops the series' correctly describe what actually happened.

    Historical observation only -- nothing here is fitted or tuned, and the
    date filter (< 2026-01-01) is a hard bound, not a game_type filter, so
    this test cannot start silently reading 2026 postseason rows once they
    land in the same file.
    """

    ROUND_K = {"F": 2, "D": 3, "L": 4, "W": 4}

    @classmethod
    def setUpClass(cls):
        if not HISTORICAL_RESULTS.exists():
            raise unittest.SkipTest(f"{HISTORICAL_RESULTS} not present in this checkout")
        with open(HISTORICAL_RESULTS, newline="", encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        cls.postseason_rows = [
            r for r in rows
            if r["game_type"] in cls.ROUND_K and r["date"] < "2026-01-01"
        ]

    def _series_groups(self):
        groups = {}
        for row in self.postseason_rows:
            season = row["date"][:4]
            pair = frozenset((row["away_team_id"], row["home_team_id"]))
            key = (season, row["game_type"], pair)
            groups.setdefault(key, []).append(row)
        for games in groups.values():
            games.sort(key=lambda r: (r["date"], r["game_number"]))
        return groups

    def test_game_and_series_counts_match_the_recorded_total(self):
        self.assertEqual(131, len(self.postseason_rows))
        self.assertEqual(33, len(self._series_groups()))

    def test_no_series_exceeds_its_round_max_length(self):
        for (season, game_type, _pair), games in self._series_groups().items():
            k = self.ROUND_K[game_type]
            self.assertLessEqual(len(games), 2 * k - 1,
                                 f"{season} {game_type} series has {len(games)} games")

    def test_every_series_winner_reached_exactly_k_wins_and_no_more_games_follow(self):
        for (season, game_type, _pair), games in self._series_groups().items():
            k = self.ROUND_K[game_type]
            wins = {}
            for i, row in enumerate(games):
                winner = row["winner"]
                wins[winner] = wins.get(winner, 0) + 1
                if wins[winner] == k:
                    self.assertEqual(
                        i, len(games) - 1,
                        f"{season} {game_type} {sorted(wins)}: a game was "
                        f"recorded after a team already had {k} wins")
            self.assertTrue(any(v == k for v in wins.values()),
                            f"{season} {game_type}: no team reached {k} wins")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
