"""The statistics of the learning loop: Student's t, the clustered paired mean, the look boundaries,
the false-discovery procedure, and that the pre-registration states every number the code uses.

No FastAPI, no network, no ledger: pure functions and one read of docs/PREREG_LEARNING_LOOP.md.
"""

from __future__ import annotations

import random
import re
import unittest
from pathlib import Path

from src.hounds.learning import rules, sequential as seq

ROOT = Path(__file__).resolve().parents[1]
PREREG = (ROOT / "docs" / "PREREG_LEARNING_LOOP.md").read_text(encoding="utf-8")


def slots(n_days, per_day, mean, sd, seed):
    rng = random.Random(seed)
    out = []
    for d in range(n_days):
        day = f"2026-11-{d + 1:02d}" if d < 30 else f"2026-12-{d - 29:02d}"
        shock = rng.gauss(0, sd / 2)       # a shared per-day move, so the clustering matters
        for _ in range(per_day):
            out.append((day, mean + shock + rng.gauss(0, sd)))
    return out


class StudentT(unittest.TestCase):
    def test_published_values(self):
        # t(0.975, 19) = 2.093024; Cauchy (df 1) upper tail at 1 is exactly 0.25; t(0.975, 1) = 12.7062
        self.assertAlmostEqual(seq.t_sf(2.093024, 19), 0.025, places=6)
        self.assertAlmostEqual(seq.t_sf(1.0, 1), 0.25, places=9)
        self.assertAlmostEqual(seq.t_sf(12.7062, 1), 0.025, places=5)
        self.assertAlmostEqual(seq.t_sf(0.0, 7), 0.5, places=12)
        self.assertAlmostEqual(seq.t_sf(-1.5, 12) + seq.t_sf(1.5, 12), 1.0, places=12)

    def test_large_df_approaches_the_normal(self):
        # P(Z > 1.96) = 0.0249979
        self.assertAlmostEqual(seq.t_sf(1.96, 100000), 0.0249979, places=5)

    def test_quantile_inverts_the_tail(self):
        for df in (4, 19, 60):
            for alpha in (0.002, 0.025, 0.4):
                q = seq.t_quantile_upper(alpha, df)
                self.assertAlmostEqual(seq.t_sf(q, df), alpha, places=7)


class ClusteredPaired(unittest.TestCase):
    def test_hand_worked_example(self):
        # two dates: d1 = [2, 4], d2 = [6]; mean 4; resid d1 = 6 - 4*2 = -2, d2 = 6 - 4*1 = 2
        # var = (2/1) * (4 + 4) / 9 ; se = sqrt(16/9) = 4/3 ; t = 3 ; df 1
        st = seq.clustered_paired([("2026-11-01", 2), ("2026-11-01", 4), ("2026-11-02", 6)])
        self.assertEqual((st.n, st.dates), (3, 2))
        self.assertAlmostEqual(st.mean, 4.0)
        self.assertAlmostEqual(st.se, 4 / 3)
        self.assertAlmostEqual(st.t, 3.0)
        self.assertEqual(st.df, 1)
        self.assertAlmostEqual(st.p_better, seq.t_sf(3.0, 1))
        self.assertAlmostEqual(st.p_better + st.p_worse, 1.0)

    def test_one_date_or_zero_variance_gives_no_p_value(self):
        one = seq.clustered_paired([("2026-11-01", 1), ("2026-11-01", 3)])
        self.assertIsNone(one.p_better)
        same = seq.clustered_paired([("2026-11-01", 1), ("2026-11-02", 1)])
        self.assertIsNone(same.p_better)
        self.assertEqual(seq.clustered_paired([]).n, 0)

    def test_bounds_bracket_the_mean(self):
        st = seq.clustered_paired(slots(25, 4, 1.0, 3.0, seed=3))
        lo, hi = seq.bound(st, 0.025, "lower"), seq.bound(st, 0.025, "upper")
        self.assertLess(lo, st.mean)
        self.assertGreater(hi, st.mean)


class LookBoundaries(unittest.TestCase):
    def test_spending_table_is_the_preregistered_one_and_sums_to_the_total(self):
        self.assertEqual(rules.LOOKS, (100, 150, 200, 250, 300))
        self.assertEqual(rules.ALPHA_SPEND, (0.002, 0.003, 0.005, 0.007, 0.008))
        self.assertAlmostEqual(sum(rules.ALPHA_SPEND), rules.ALPHA_TOTAL, places=12)
        self.assertEqual(rules.ALPHA_TOTAL, 0.025)

    def test_a_clear_improvement_crosses_at_look_one(self):
        sample = slots(25, 4, 2.0, 2.0, seed=11)
        res = seq.evaluate_look(1, sample)
        self.assertEqual(res.n_target, 100)
        self.assertTrue(res.crossed_better)
        self.assertFalse(res.crossed_worse)
        self.assertGreater(res.lower, 0)           # the lower (1 - alpha) bound is above 0

    def test_a_clear_harm_crosses_the_harm_boundary(self):
        res = seq.evaluate_look(1, slots(25, 4, -2.0, 2.0, seed=12))
        self.assertTrue(res.crossed_worse)
        self.assertFalse(res.crossed_better)
        self.assertLess(res.upper, 0)

    def test_no_difference_crosses_neither(self):
        res = seq.evaluate_look(3, slots(30, 7, 0.0, 3.0, seed=13))
        self.assertFalse(res.crossed_better or res.crossed_worse)

    def test_the_boundary_is_exactly_alpha_k(self):
        # Build a sample whose one-sided p sits just either side of look 1's alpha (0.002) by scaling
        # the mean; the decision must flip where p crosses 0.002, not before and not after.
        base = slots(25, 4, 0.0, 2.0, seed=5)
        crossed = []
        for shift in [x / 20 for x in range(0, 60)]:
            sample = [(d, v + shift) for d, v in base]
            res = seq.evaluate_look(1, sample)
            crossed.append((res.crossed_better, res.stats.p_better))
        flags = [c for c, _p in crossed]
        self.assertEqual(flags, sorted(flags))        # monotone: once crossed, stays crossed
        for c, p in crossed:
            self.assertEqual(c, p <= rules.ALPHA_SPEND[0])
        self.assertIn(True, flags)
        self.assertIn(False, flags)

    def test_a_negative_mean_never_crosses_better_even_with_a_small_p_worse(self):
        res = seq.evaluate_look(2, slots(25, 6, -3.0, 1.5, seed=2))
        self.assertFalse(res.crossed_better)

    def test_look_needs_both_the_size_and_enough_dates(self):
        self.assertTrue(seq.look_reached(100, 20, 1))
        self.assertFalse(seq.look_reached(99, 30, 1))
        self.assertFalse(seq.look_reached(150, 19, 1))      # many slots, too few dates

    def test_analyst_looks_are_the_larger_table(self):
        self.assertEqual(seq.look_sizes(analyst=True), (150, 225, 300, 375, 450))
        self.assertTrue(seq.look_reached(150, 20, 1, analyst=True))
        self.assertFalse(seq.look_reached(149, 20, 1, analyst=True))

    def test_type_one_error_across_all_looks_stays_under_the_total(self):
        """2,000 null challengers, each examined at all five looks over a growing sample: the share
        that EVER cross the promotion boundary must stay at or under 0.025 (union bound; in practice
        well under)."""
        rng = random.Random(20261018)
        hits = 0
        trials = 2000
        for _ in range(trials):
            days = []
            for d in range(60):
                shock = rng.gauss(0, 1.0)
                days.append([(f"2026-11-{d + 1:02d}" if d < 30 else f"2026-12-{d - 29:02d}",
                              shock + rng.gauss(0, 2.5)) for _ in range(5)])
            flat = [x for day in days for x in day]
            crossed = False
            for k, n in enumerate(rules.LOOKS, start=1):
                sample = flat[:n]
                st = seq.clustered_paired(sample)
                if st.dates >= rules.MIN_DATES_PER_LOOK and st.p_better is not None \
                        and st.p_better <= rules.ALPHA_SPEND[k - 1] and st.mean > 0:
                    crossed = True
                    break
            hits += crossed
        self.assertLessEqual(hits / trials, rules.ALPHA_TOTAL)


class BenjaminiHochberg(unittest.TestCase):
    # Benjamini and Hochberg (1995), the 15 p-values of their worked example.
    P = [0.0001, 0.0004, 0.0019, 0.0095, 0.0201, 0.0278, 0.0298, 0.0344, 0.0459, 0.3240,
         0.4262, 0.5719, 0.6528, 0.7590, 1.000]

    def family(self):
        return {f"c{i:02d}": p for i, p in enumerate(self.P)}

    def test_the_published_example_at_q_005_rejects_four(self):
        self.assertEqual(seq.benjamini_hochberg(self.family(), 0.05), ["c00", "c01", "c02", "c03"])

    def test_the_same_family_at_q_010_rejects_nine(self):
        self.assertEqual(len(seq.benjamini_hochberg(self.family(), 0.10)), 9)

    def test_step_up_rejects_a_larger_p_below_an_earlier_failure(self):
        # p_(1) = 0.04 fails 1 * q / 3 = 0.0333 alone, but p_(3) = 0.09 <= 3 * q / 3 = 0.10 rejects all three
        fam = {"a": 0.04, "b": 0.05, "c": 0.09}
        self.assertEqual(seq.benjamini_hochberg(fam, 0.10), ["a", "b", "c"])

    def test_nothing_rejected_when_nothing_clears(self):
        self.assertEqual(seq.benjamini_hochberg({"a": 0.5, "b": 0.9}, 0.10), [])
        self.assertEqual(seq.benjamini_hochberg({}, 0.10), [])

    def test_order_of_the_dict_never_matters(self):
        a = seq.benjamini_hochberg({"x": 0.01, "y": 0.012, "z": 0.8}, 0.10)
        b = seq.benjamini_hochberg({"z": 0.8, "y": 0.012, "x": 0.01}, 0.10)
        self.assertEqual(a, b)

    def test_adjusted_p_is_five_times_p_capped_at_one(self):
        self.assertAlmostEqual(seq.adjusted_p(0.004), 0.02)
        self.assertEqual(seq.adjusted_p(0.4), 1.0)
        self.assertIsNone(seq.adjusted_p(None))


class PreregStatesEveryNumber(unittest.TestCase):
    """The code's constants are quoted from the pre-registration; if a number moves, this fails."""

    def test_numbers_appear_in_the_prereg(self):
        text = re.sub(r"\s+", " ", PREREG)
        must = [
            "100, 150, 200, 250 and 300", "0.002", "0.003", "0.005", "0.007", "0.008", "0.025",
            "at least 20 distinct slate dates", "Benjamini-Hochberg at q = 0.10",
            "`p_adj = min(1, 5 * p)`", "at most 3 promotions system-wide per calendar month",
            "at most ONE promotion per hound per 30 days", "at least 50 measurable bets",
            "at least 50% as many", "at least 50 graded forward bets", "ONE accepted proposal per hound lineage per 7 days",
            "at most 3 live challengers per hound and 30 live", "last 90 days", "0.40", "**10 promotions have matured**",
            "**last 60 daily scorecards**", "180 days", "within 0.10 decimal odds",
            "150, 225, 300, 375 and 450",
        ]
        lowered = text.lower()
        for needle in must:
            self.assertTrue(needle.lower() in lowered, f"the pre-registration does not state: {needle}")
        self.assertEqual(rules.BH_Q, 0.10)
        self.assertEqual(rules.MAX_PROMOTIONS_PER_MONTH, 3)
        self.assertEqual(rules.PROMOTION_COOLDOWN_DAYS, 30)
        self.assertEqual((rules.MAX_LIVE_PER_HOUND, rules.MAX_LIVE_PER_SCOPE), (3, 30))
        self.assertEqual((rules.HIT_RATE_FLOOR, rules.MIN_MATURED_FOR_FLOOR, rules.TRAIL_DAYS), (0.40, 10, 60))
        self.assertEqual((rules.VOLUME_FLOOR_MIN_BETS, rules.VOLUME_FLOOR_SHARE), (50, 0.5))
        self.assertEqual((rules.MIN_GRADED_BEFORE_PROPOSAL, rules.PROPOSAL_COOLDOWN_DAYS, rules.DEDUPE_DAYS),
                         (50, 7, 90))

    def test_the_prereg_predates_the_code(self):
        """The pre-registration is committed before src/hounds/learning/ is (git history)."""
        import subprocess
        try:
            first_prereg = subprocess.run(
                ["git", "log", "--diff-filter=A", "--format=%ct", "--", "docs/PREREG_LEARNING_LOOP.md"],
                cwd=ROOT, capture_output=True, text=True, timeout=30).stdout.split()
            first_code = subprocess.run(
                ["git", "log", "--diff-filter=A", "--format=%ct", "--", "src/hounds/learning/rules.py"],
                cwd=ROOT, capture_output=True, text=True, timeout=30).stdout.split()
        except (OSError, subprocess.SubprocessError):
            self.skipTest("git not available")
        if not first_prereg or not first_code:
            self.skipTest("not committed yet, or no git history in this checkout")
        self.assertLessEqual(int(first_prereg[-1]), int(first_code[-1]))


if __name__ == "__main__":
    unittest.main()
