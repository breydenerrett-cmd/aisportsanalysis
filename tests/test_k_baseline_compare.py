"""Tests for the strikeout baseline comparison, on SYNTHETIC rows only.

`src/research/k_baseline.py` and `scripts/k_baseline_compare.py` implement the
comparison registered in `docs/PREREG_K_BASELINE.md`. Nothing here opens a real
store: every row is built in this file, so the harness is proven before any
outcome-bearing data is touched.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import math
import os
import random
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from src.model import discovery  # noqa: E402
from src.research import k_baseline as kb  # noqa: E402


def _load_script():
    spec = importlib.util.spec_from_file_location(
        "k_baseline_compare", REPO_ROOT / "scripts" / "k_baseline_compare.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _log(pid, date, k, bf, gs=1):
    return {"person_id": pid, "date": date, "season": date[:4], "is_home": True,
            "games_started": gs, "innings_pitched": 5.0, "earned_runs": 2,
            "runs": 2, "hits": 5, "walks": 1, "strikeouts": k,
            "home_runs": 0, "batters_faced": bf, "pitches": 90}


class World:
    """Ten pitchers, one start each every fifth day, over `days` days."""

    def __init__(self, season=2023, seed=5, days=60, pitchers=10):
        rng = random.Random(seed)
        self.season = season
        self.rows = []
        self.pids = list(range(700, 700 + pitchers))
        base = {pid: rng.uniform(0.15, 0.32) for pid in self.pids}
        for day in range(days):
            date = f"{season}-{4 + day // 28:02d}-{day % 28 + 1:02d}"
            for i, pid in enumerate(self.pids):
                if (day + i) % 5:
                    continue
                bf = rng.randint(14, 30)
                k = sum(rng.random() < base[pid] for _ in range(bf))
                self.rows.append(_log(pid, date, k, bf))
        self.dates = sorted({r["date"] for r in self.rows})

    def starts(self, rows=None):
        return kb.extract_starts(self.rows if rows is None else rows)["starts"]

    def build(self, rows=None, **overrides):
        kwargs = dict(season=self.season, starts=self.starts(rows),
                      min_league_starts=20)
        kwargs.update(overrides)
        return kb.build_comparison_rows(**kwargs)


class WindowGuardTests(unittest.TestCase):
    def test_in_window_boundaries(self):
        self.assertTrue(kb.in_window("2023-01-01"))
        self.assertTrue(kb.in_window("2024-12-31"))
        for bad in ("2022-12-31", "2025-01-01", "2025-06-15", "2026-01-01",
                    "2026-09-09", "", None, 20230330, "garbage"):
            self.assertFalse(kb.in_window(bad), bad)

    def test_assert_allowed_date_is_a_hard_error_for_2025_and_2026(self):
        for bad in ("2025-04-01", "2025-12-31", "2026-01-01", "2026-08-27",
                    "2026-10-03"):
            with self.assertRaises(kb.SealedDataError):
                kb.assert_allowed_date(bad)
        self.assertEqual(kb.assert_allowed_date("2024-09-29"), "2024-09-29")

    def test_season_guard(self):
        for bad in (2025, 2026, "2025", 2022, "x", None, True):
            with self.assertRaises(kb.SealedDataError):
                kb.assert_allowed_season(bad)
        self.assertEqual(kb.assert_allowed_season("2023"), 2023)
        self.assertEqual(kb.assert_allowed_season(2024), 2024)

    def test_allowed_seasons_match_the_matrix_guard(self):
        from src.research import matrix
        self.assertEqual(kb.ALLOWED_SEASONS, matrix.ALLOWED_SEASONS)

    def test_build_refuses_2025_and_2026(self):
        world = World()
        for bad in (2025, 2026):
            with self.assertRaises(kb.SealedDataError):
                world.build(season=bad)

    def test_a_sealed_dated_start_handed_in_directly_is_a_hard_error(self):
        starts = World().starts() + [
            {"person_id": 1, "date": "2025-04-01", "k": 5, "bf": 24}]
        with self.assertRaises(kb.SealedDataError):
            kb.build_comparison_rows(season=2023, starts=starts,
                                     min_league_starts=20)

    def test_sealed_rows_are_dropped_on_read_not_kept_or_counted(self):
        world = World()
        poisoned = world.rows + [
            _log(700, "2025-05-01", 99, 99), _log(701, "2026-05-01", 98, 98),
            _log(702, "2022-05-01", 97, 97),
            dict(_log(703, "2023-05-01", 1, 1), date=None), {"person_id": 5, "date": "garbage"}]
        clean = kb.extract_starts(world.rows)
        dirty = kb.extract_starts(poisoned)
        self.assertEqual(clean["starts"], dirty["starts"])
        self.assertEqual(clean["counts"], dirty["counts"])

    def test_script_refuses_other_seasons_before_touching_any_file(self):
        script = _load_script()
        with mock.patch("sys.stderr"), mock.patch.object(
                script, "run", side_effect=AssertionError("must not run")):
            for bad in ("2025", "2026", "2022"):
                self.assertEqual(script.main(["--season", bad]), 2)

    def test_script_never_opens_a_path_for_a_refused_season(self):
        script = _load_script()
        with mock.patch.object(script, "in_window_rows",
                               side_effect=AssertionError("opened")):
            for bad in (2025, 2026):
                with self.assertRaises(kb.SealedDataError):
                    script.run(bad)

    def test_a_2023_run_never_reads_2024_rows(self):
        w23, w24 = World(2023), World(2024, seed=11)
        alone = w23.build(rows=w23.rows)
        mixed = w23.build(rows=w23.rows + w24.rows)
        self.assertEqual(alone["rows"], mixed["rows"])
        poisoned = [dict(r, strikeouts=r["batters_faced"]) for r in w24.rows]
        self.assertEqual(alone["rows"], w23.build(rows=w23.rows + poisoned)["rows"])


class ExtractStartsTests(unittest.TestCase):
    def test_a_start_is_games_started_one_and_relief_is_not_used(self):
        rows = [_log(1, "2023-05-01", 6, 24),
                _log(1, "2023-05-03", 3, 4, gs=0),
                _log(2, "2023-05-02", 0, 3, gs=1)]     # a one-inning opener
        out = kb.extract_starts(rows)
        self.assertEqual([(s["person_id"], s["date"]) for s in out["starts"]],
                         [(1, "2023-05-01"), (2, "2023-05-02")])
        self.assertEqual(out["counts"]["relief_appearances"], 1)
        self.assertEqual(out["counts"]["starts"], 2)

    def test_duplicate_person_date_is_dropped_entirely_and_counted(self):
        rows = [_log(1, "2023-05-01", 6, 24), _log(1, "2023-05-01", 2, 9),
                _log(1, "2023-05-07", 5, 22)]
        out = kb.extract_starts(rows)
        self.assertEqual([s["date"] for s in out["starts"]], ["2023-05-07"])
        self.assertEqual(out["counts"]["duplicate_person_date"], 2)

    def test_missing_or_impossible_figures_are_excluded_not_zero_filled(self):
        rows = [_log(1, "2023-05-01", None, 24), _log(2, "2023-05-01", 5, None),
                _log(3, "2023-05-01", 30, 24), _log(4, "2023-05-01", -1, 24),
                _log(5, "2023-05-01", 5, 24)]
        out = kb.extract_starts(rows)
        self.assertEqual([s["person_id"] for s in out["starts"]], [5])
        self.assertEqual(out["counts"]["missing_or_invalid_k_bf"], 4)

    def test_other_games_started_values_are_excluded_and_counted(self):
        rows = [_log(1, "2023-05-01", 5, 24, gs=2), _log(2, "2023-05-01", 5, 24, gs=None)]
        out = kb.extract_starts(rows)
        self.assertEqual(out["starts"], [])
        self.assertEqual(out["counts"]["games_started_other_value"], 2)


class StrictlyBeforeTests(unittest.TestCase):
    def _find(self, built, pid, date):
        for r in built["rows"]:
            if r["person_id"] == pid and r["date"] == date:
                return r
        raise AssertionError("row not scored")

    def test_changing_the_target_start_or_the_future_changes_nothing_before_it(self):
        world = World()
        base = world.build()
        target = base["rows"][len(base["rows"]) // 2]
        pid, date = target["person_id"], target["date"]
        changed = copy.deepcopy(world.rows)
        for r in changed:
            if r["date"] >= date and r["person_id"] == pid:
                r["strikeouts"] = min(r["batters_faced"], 25)
            if r["date"] > date:
                r["strikeouts"] = r["batters_faced"]
                r["batters_faced"] = max(r["batters_faced"], 1)
        again = world.build(rows=changed)
        for key in [k for k in target if k not in ("k", "bf") and not k.startswith(
                ("y_", "d_", "short"))]:
            self.assertEqual(self._find(again, pid, date)[key], target[key], key)
        # Every row up to and including that date has identical predictions.
        for r in base["rows"]:
            if r["date"] <= date:
                twin = self._find(again, r["person_id"], r["date"])
                for key in ("e_base", "e_cand", "p_base_4.5", "p_cand_4.5",
                            "prior_starts"):
                    self.assertEqual(twin[key], r[key], (r["date"], key))

    def test_a_start_on_the_date_never_counts_for_a_same_day_start(self):
        # Two pitchers start on the same date: neither is history for the other
        # or for the pool on that date.
        rows = [_log(1, f"2023-04-{d:02d}", 5, 24) for d in range(1, 8)]
        rows += [_log(2, f"2023-04-{d:02d}", 5, 24) for d in range(1, 8)]
        a = kb.build_comparison_rows(season=2023, starts=kb.extract_starts(rows)["starts"],
                                     min_league_starts=4)
        bumped = [dict(r) for r in rows]
        for r in bumped:
            if r["date"] == "2023-04-06":
                r["strikeouts"] = 15
        b = kb.build_comparison_rows(season=2023, starts=kb.extract_starts(bumped)["starts"],
                                     min_league_starts=4)
        on_date = [r for r in a["rows"] if r["date"] == "2023-04-06"]
        self.assertTrue(on_date)
        for x, y in zip(a["rows"], b["rows"]):
            if x["date"] <= "2023-04-06":
                self.assertEqual(x["e_base"], y["e_base"])
                self.assertEqual(x["e_cand"], y["e_cand"])
            else:
                self.assertNotEqual((x["e_base"], x["e_cand"]),
                                    (y["e_base"], y["e_cand"]))
                break

    def test_pitcher_history_is_same_season_only(self):
        # A pitcher with huge 2023 strikeouts and ordinary 2024: the 2024
        # prediction must not see 2023.
        rows = [_log(9, f"2023-05-{d:02d}", 14, 25) for d in range(1, 10)]
        rows += [_log(9, f"2024-05-{d:02d}", 4, 25) for d in range(1, 6)]
        rows += [_log(p, f"2023-05-{d:02d}", 5, 25)
                 for p in range(20, 24) for d in range(1, 10)]
        rows += [_log(p, f"2024-05-{d:02d}", 5, 25)
                 for p in range(20, 24) for d in range(1, 6)]
        starts = kb.extract_starts(rows)["starts"]
        out = kb.build_comparison_rows(season=2024, starts=starts,
                                       min_league_starts=10)
        mine = [r for r in out["rows"] if r["person_id"] == 9]
        self.assertTrue(mine)
        self.assertTrue(all(r["prior_starts"] <= 4 for r in mine))
        self.assertLess(mine[-1]["k_rate"], 0.3)         # not pulled to 14/25

    def test_prior_starts_count_grows_with_each_earlier_start(self):
        world = World()
        counts = {}
        for r in world.build()["rows"]:
            counts.setdefault(r["person_id"], []).append(r["prior_starts"])
        for series in counts.values():
            self.assertEqual(series, sorted(series))
            self.assertEqual(len(set(series)), len(series))


class PoolRuleTests(unittest.TestCase):
    def _rows(self, season, n_days, per_day, k=5, bf=24, pid_base=0):
        rows = []
        for d in range(n_days):
            date = f"{season}-04-{d + 1:02d}"
            for i in range(per_day):
                rows.append(_log(pid_base + i, date, k, bf))
        return rows

    def test_early_season_without_a_pool_is_excluded_in_both_arms(self):
        rows = self._rows(2023, 10, 5)               # 5 starts a day
        out = kb.build_comparison_rows(season=2023,
                                       starts=kb.extract_starts(rows)["starts"],
                                       min_league_starts=20)
        # The pool reaches 20 on the date after four days; day 5 is the first scored.
        self.assertEqual(out["rows"][0]["date"], "2023-04-05")
        self.assertEqual(out["counts"]["excluded_no_league_pool"], 20)
        self.assertEqual(out["counts"]["scored"], len(out["rows"]))
        self.assertTrue(all(r["pool"] == "same_season" for r in out["rows"]))

    def test_2024_falls_back_to_the_whole_prior_season_until_enough_exist(self):
        rows = self._rows(2023, 10, 5, k=6) + self._rows(2024, 10, 5, k=3)
        out = kb.build_comparison_rows(season=2024,
                                       starts=kb.extract_starts(rows)["starts"],
                                       min_league_starts=20)
        first_two = [r for r in out["rows"] if r["date"] <= "2024-04-04"]
        # Day 1 has no prior start for any pitcher; day 2 is scored from the
        # prior-season pool (k = 6 everywhere), not from one day of 2024.
        day2 = [r for r in out["rows"] if r["date"] == "2024-04-02"]
        self.assertTrue(day2 and all(r["pool"] == "prior_season" for r in day2))
        self.assertAlmostEqual(day2[0]["e_base"], 6.0)
        late = [r for r in out["rows"] if r["pool"] == "same_season"]
        self.assertTrue(late)
        self.assertAlmostEqual(late[0]["e_base"], 3.0)
        self.assertEqual(out["counts"]["prior_season_pool_starts"], 50)
        self.assertGreaterEqual(len(first_two), 1)

    def test_2023_has_no_prior_season_to_fall_back_on(self):
        rows = self._rows(2023, 3, 5)
        out = kb.build_comparison_rows(season=2023,
                                       starts=kb.extract_starts(rows)["starts"],
                                       min_league_starts=20)
        self.assertEqual(out["rows"], [])
        self.assertEqual(out["counts"]["prior_season_pool_starts"], 0)

    def test_pitcher_with_no_prior_start_is_excluded_in_both_arms(self):
        rows = self._rows(2023, 8, 5)
        rows.append(_log(999, "2023-04-08", 7, 25))         # a debut
        out = kb.build_comparison_rows(season=2023,
                                       starts=kb.extract_starts(rows)["starts"],
                                       min_league_starts=10)
        self.assertEqual(out["counts"]["excluded_no_prior_start"] >= 1, True)
        self.assertFalse([r for r in out["rows"] if r["person_id"] == 999])
        # ... but the debut still happened: it is history for his next start.
        rows.append(_log(999, "2023-04-09", 4, 25))
        rows += self._rows(2023, 1, 0)
        out2 = kb.build_comparison_rows(season=2023,
                                        starts=kb.extract_starts(rows)["starts"],
                                        min_league_starts=10)
        later = [r for r in out2["rows"] if r["person_id"] == 999]
        self.assertEqual([r["prior_starts"] for r in later], [1])

    def test_an_excluded_start_still_feeds_the_pool(self):
        rows = self._rows(2023, 8, 5, k=5)
        extra = _log(999, "2023-04-07", 17, 25)             # excluded debut, huge K
        a = kb.build_comparison_rows(season=2023, min_league_starts=10,
                                     starts=kb.extract_starts(rows)["starts"])
        b = kb.build_comparison_rows(season=2023, min_league_starts=10,
                                     starts=kb.extract_starts(rows + [extra])["starts"])
        after_a = [r for r in a["rows"] if r["date"] == "2023-04-08"]
        after_b = [r for r in b["rows"] if r["date"] == "2023-04-08"]
        self.assertGreater(after_b[0]["e_base"], after_a[0]["e_base"])

    def test_short_start_is_a_scored_start_and_counted(self):
        rows = self._rows(2023, 8, 5)
        rows.append(_log(0, "2023-04-09", 1, 4))            # a four-batter opener
        out = kb.build_comparison_rows(season=2023, min_league_starts=10,
                                       starts=kb.extract_starts(rows)["starts"])
        shorts = [r for r in out["rows"] if r["short_start"]]
        self.assertEqual(len(shorts), 1)
        self.assertEqual(out["counts"]["short_starts_scored"], 1)


class OneRowPerStartTests(unittest.TestCase):
    def test_one_row_per_person_date_and_every_row_has_both_arms(self):
        world = World()
        built = world.build()
        keys = [(r["person_id"], r["date"]) for r in built["rows"]]
        self.assertEqual(len(keys), len(set(keys)))
        c = built["counts"]
        self.assertEqual(c["scored"] + c["excluded_no_league_pool"]
                         + c["excluded_no_prior_start"], c["starts_in_season"])
        for r in built["rows"]:
            for L in kb.LINES:
                key = kb.line_key(L)
                self.assertIsNotNone(r[f"p_base_{key}"])
                self.assertIsNotNone(r[f"p_cand_{key}"])
                self.assertIn(r[f"y_{key}"], (0, 1))

    def test_label_is_the_count_over_the_half_point_line(self):
        world = World()
        for r in world.build()["rows"]:
            for L in kb.LINES:
                self.assertEqual(r[f"y_{kb.line_key(L)}"], int(r["k"] > L))

    def test_limit_scores_a_slice_only(self):
        world = World()
        self.assertEqual(len(world.build(limit=7)["rows"]), 7)


class TwoModelTests(unittest.TestCase):
    def _pool(self):
        pool = kb.LeaguePool()
        for k, bf in [(3, 22), (5, 25), (7, 27), (4, 20), (6, 26), (5, 24),
                      (8, 28), (2, 18), (5, 25), (6, 25)]:
            pool.add(k, bf)
        return pool

    def test_baseline_needs_only_the_pool_and_is_the_empirical_tail(self):
        pool = self._pool()
        base = kb.baseline_prediction(pool)
        # K values: 3,5,7,4,6,5,8,2,5,6 -> over 4.5 means K>=5: 7 of 10
        self.assertAlmostEqual(base["over"]["4.5"], 0.7)
        self.assertAlmostEqual(base["over"]["6.5"], 0.2)        # K>=7: the 7 and the 8
        self.assertAlmostEqual(base["expected"], 5.1)

    def test_candidate_formula_by_hand(self):
        pool = self._pool()
        rate_league = pool.k_per_bf()
        mean_bf = pool.mean_bf()
        cand = kb.candidate_prediction(pool, (4, 28, 100))
        rate = (28 + 70 * rate_league) / (100 + 70)
        exp_bf = (100 + 3 * mean_bf) / (4 + 3)
        self.assertAlmostEqual(cand["k_rate"], rate)
        self.assertAlmostEqual(cand["expected_bf"], exp_bf)
        self.assertAlmostEqual(cand["expected"], rate * exp_bf)
        self.assertAlmostEqual(cand["over"]["4.5"],
                               kb.poisson_over(rate * exp_bf, 4.5))

    def test_the_fixed_weights_are_the_registered_ones(self):
        self.assertEqual(kb.PRIOR_WEIGHT_BF, 70.0)
        self.assertEqual(kb.PRIOR_WEIGHT_STARTS, 3.0)
        self.assertEqual(kb.MIN_LEAGUE_STARTS, 500)
        self.assertEqual(kb.MIN_PRIOR_STARTS, 1)
        self.assertEqual(kb.LINES, (3.5, 4.5, 5.5, 6.5))
        self.assertEqual(kb.DECISIVE_LINES, (4.5, 5.5))

    def test_no_data_shrinks_to_the_league_and_lots_of_data_overrides_it(self):
        pool = self._pool()
        none = kb.candidate_prediction(pool, (0, 0, 0))
        self.assertAlmostEqual(none["k_rate"], pool.k_per_bf())
        self.assertAlmostEqual(none["expected_bf"], pool.mean_bf())
        big = kb.candidate_prediction(pool, (200, 9000, 40000))     # 22.5% each
        self.assertAlmostEqual(big["k_rate"], 0.225, places=2)

    def test_models_differ_only_in_what_is_specified(self):
        # (1) Changing the pitcher's own history moves the candidate only.
        pool = self._pool()
        a, b = (kb.baseline_prediction(pool), kb.candidate_prediction(pool, (3, 10, 70)))
        a2 = kb.baseline_prediction(pool)
        b2 = kb.candidate_prediction(pool, (3, 25, 70))
        self.assertEqual(a, a2)
        self.assertNotEqual(b["expected"], b2["expected"])
        # (2) Changing the league pool moves both.
        other = self._pool()
        other.add(15, 30)
        self.assertNotEqual(kb.baseline_prediction(other)["expected"], a["expected"])
        self.assertNotEqual(kb.candidate_prediction(other, (3, 10, 70))["expected"],
                            b["expected"])

    def test_in_a_full_build_the_baseline_is_identical_for_every_pitcher_on_a_date(self):
        world = World()
        by_date = {}
        for r in world.build()["rows"]:
            by_date.setdefault((r["date"], r["pool"]), set()).add(
                (r["e_base"], r["p_base_4.5"], r["p_base_5.5"]))
        self.assertTrue(by_date)
        self.assertTrue(all(len(v) == 1 for v in by_date.values()))

    def test_pitcher_specific_probabilities_differ_across_pitchers(self):
        world = World()
        rows = world.build()["rows"]
        last = world.dates[-1]
        same_day = {}
        for r in rows:
            same_day.setdefault(r["date"], set()).add(r["p_cand_4.5"])
        self.assertTrue(any(len(v) > 1 for v in same_day.values()), last)

    def test_shape_control_is_the_candidate_without_pitcher_information(self):
        pool = self._pool()
        ctrl = kb.control_prediction(pool)
        empty = kb.candidate_prediction(pool, (0, 0, 0))
        self.assertAlmostEqual(ctrl["expected"], empty["expected"])
        for key in ctrl["over"]:
            self.assertAlmostEqual(ctrl["over"][key], empty["over"][key])

    def test_shape_and_information_effects_sum_to_the_registered_difference(self):
        for r in World().build()["rows"]:
            for L in kb.LINES:
                key = kb.line_key(L)
                self.assertAlmostEqual(
                    r[f"d_shape_{key}"] + r[f"d_info_{key}"], r[f"d_{key}"],
                    places=12)

    def test_poisson_tail_known_values_and_monotone(self):
        # P(K > 4.5) = 1 - P(K <= 4), mean 5
        pmf = [math.exp(-5) * 5 ** j / math.factorial(j) for j in range(5)]
        self.assertAlmostEqual(kb.poisson_over(5.0, 4.5), 1 - sum(pmf))
        self.assertEqual(kb.poisson_over(0.0, 3.5), 0.0)
        tails = [kb.poisson_over(5.0, L) for L in kb.LINES]
        self.assertEqual(tails, sorted(tails, reverse=True))
        self.assertLess(kb.poisson_over(3.0, 4.5), kb.poisson_over(7.0, 4.5))
        with self.assertRaises(kb.KBaselineError):
            kb.poisson_over(float("nan"), 4.5)


class SignAndDecisionTests(unittest.TestCase):
    def test_sign_convention_positive_means_candidate_is_better(self):
        # y = 1: the candidate gave the higher probability, so it is better.
        self.assertGreater(kb.paired_difference(0.3, 0.7, 1), 0)
        self.assertLess(kb.paired_difference(0.7, 0.3, 1), 0)
        # y = 0: the candidate gave the lower probability.
        self.assertGreater(kb.paired_difference(0.7, 0.3, 0), 0)
        self.assertEqual(kb.paired_difference(0.4, 0.4, 1), 0.0)
        # absolute error: closer candidate is positive
        self.assertGreater(kb.paired_abs_error(8.0, 5.5, 5), 0)
        self.assertLess(kb.paired_abs_error(5.0, 8.0, 5), 0)

    def test_the_row_difference_is_baseline_minus_candidate(self):
        world = World()
        for r in world.build()["rows"][:50]:
            for L in kb.LINES:
                key = kb.line_key(L)
                want = (kb.log_loss_one(r[f"p_base_{key}"], r[f"y_{key}"])
                        - kb.log_loss_one(r[f"p_cand_{key}"], r[f"y_{key}"]))
                self.assertAlmostEqual(r[f"d_{key}"], want, places=12)

    def test_log_loss_clips_and_stays_finite(self):
        self.assertTrue(math.isfinite(kb.log_loss_one(0.0, 1)))
        self.assertTrue(math.isfinite(kb.log_loss_one(1.0, 0)))
        self.assertAlmostEqual(kb.log_loss_one(0.5, 1), math.log(2))

    @staticmethod
    def _iv(est, lo, hi):
        return {"estimate": est, "low": lo, "high": hi}

    def _both(self, a, b):
        return {"4.5": a, "5.5": b}

    def test_decision_rule_as_registered(self):
        iv, both = self._iv, self._both
        good, bad_below, straddle = iv(0.01, 0.002, 0.02), iv(-0.01, -0.02, -0.002), iv(0.0, -0.01, 0.01)
        first_pos = both(iv(0.005, 0.0, 0.01), iv(0.004, 0.0, 0.01))
        # SUPPORTED: both decisive lines above zero in 2024, positive in 2023.
        self.assertEqual(kb.decide(first_pos, both(good, good))["verdict"], kb.SUPPORTED)
        # One line straddles: not supported.
        self.assertEqual(kb.decide(first_pos, both(good, straddle))["verdict"],
                         kb.NOT_SUPPORTED)
        # 2023 sign disagrees on one line: not supported.
        self.assertEqual(kb.decide(both(iv(-0.001, -0.01, 0.01), iv(0.004, 0, 0.01)),
                                   both(good, good))["verdict"], kb.NOT_SUPPORTED)
        # 2023 estimate of exactly zero is not the same sign.
        self.assertEqual(kb.decide(both(iv(0.0, -0.01, 0.01), iv(0.004, 0, 0.01)),
                                   both(good, good))["verdict"], kb.NOT_SUPPORTED)
        # An interval that merely touches zero is not entirely above it.
        touch = iv(0.01, 0.0, 0.02)
        self.assertEqual(kb.decide(first_pos, both(touch, good))["verdict"],
                         kb.NOT_SUPPORTED)
        # WORSE: both entirely below zero in 2024, whatever 2023 did.
        self.assertEqual(kb.decide(first_pos, both(bad_below, bad_below))["verdict"],
                         kb.WORSE)
        self.assertEqual(kb.decide(both(iv(-1, -2, -0.5), iv(-1, -2, -0.5)),
                                   both(bad_below, bad_below))["verdict"], kb.WORSE)
        # One below, one above: neither.
        self.assertEqual(kb.decide(first_pos, both(bad_below, good))["verdict"],
                         kb.NOT_SUPPORTED)
        # Missing input is a refusal to support.
        self.assertEqual(kb.decide(first_pos, both(good, None))["verdict"],
                         kb.NOT_SUPPORTED)
        self.assertEqual(kb.decide(None, None)["verdict"], kb.NOT_SUPPORTED)
        self.assertEqual(kb.decide(first_pos, both(good, iv(None, None, None)))["verdict"],
                         kb.NOT_SUPPORTED)

    def test_the_3_5_and_6_5_lines_cannot_change_the_verdict(self):
        iv = self._iv
        first = {"4.5": iv(0.005, 0, 0.01), "5.5": iv(0.004, 0, 0.01),
                 "3.5": iv(-1, -2, 0), "6.5": iv(-1, -2, 0)}
        second = {"4.5": iv(0.01, 0.002, 0.02), "5.5": iv(0.01, 0.002, 0.02),
                  "3.5": iv(-1, -2, -0.5), "6.5": iv(-1, -2, -0.5)}
        self.assertEqual(kb.decide(first, second)["verdict"], kb.SUPPORTED)


class BootstrapTests(unittest.TestCase):
    def _rows(self, seed=3, dates=25):
        rng = random.Random(seed)
        out = []
        for i in range(dates):
            for _ in range(rng.randint(3, 9)):
                out.append({"date": f"2023-05-{i + 1:02d}",
                            "d": rng.gauss(0.001, 0.02)})
        return out

    def test_seeded_and_deterministic(self):
        rows = self._rows()
        agg = kb.per_date_aggregates(rows, "d")
        a = kb.clustered_mean_interval(agg, seed=11)
        self.assertEqual(a, kb.clustered_mean_interval(agg, seed=11))
        self.assertNotEqual(a["low"], kb.clustered_mean_interval(agg, seed=12)["low"])
        shuffled = list(rows)
        random.Random(0).shuffle(shuffled)
        c = kb.clustered_mean_interval(kb.per_date_aggregates(shuffled, "d"), seed=11)
        self.assertAlmostEqual(a["low"], c["low"], places=12)
        self.assertAlmostEqual(a["high"], c["high"], places=12)

    def test_the_registered_seed_and_size(self):
        self.assertEqual(kb.BOOTSTRAP_SEED, 20261004)
        self.assertEqual(kb.BOOTSTRAP_RESAMPLES, 2000)

    def test_matches_the_repos_own_date_clustered_bootstrap(self):
        rows = self._rows()
        mine = kb.clustered_mean_interval(
            kb.per_date_aggregates(rows, "d"), resamples=500, seed=99)
        theirs = discovery.clustered_bootstrap(
            rows, lambda sample: sum(r["d"] for r in sample) / len(sample),
            resamples=500, seed=99)
        self.assertAlmostEqual(mine["low"], theirs["low"], places=5)
        self.assertAlmostEqual(mine["high"], theirs["high"], places=5)

    def test_estimate_is_the_plain_mean_and_interval_brackets_it(self):
        rows = self._rows()
        out = kb.clustered_mean_interval(kb.per_date_aggregates(rows, "d"))
        mean = sum(r["d"] for r in rows) / len(rows)
        self.assertAlmostEqual(out["estimate"], mean, places=12)
        self.assertLessEqual(out["low"], mean)
        self.assertGreaterEqual(out["high"], mean)
        self.assertEqual(out["clusters"], 25)
        self.assertEqual(out["n"], len(rows))
        self.assertAlmostEqual(out["se"], (out["high"] - out["low"]) / 3.92)

    def test_resamples_dates_not_rows(self):
        rows = [{"date": "2023-05-01", "d": 1.0} for _ in range(200)]
        rows += [{"date": f"2023-06-{i:02d}", "d": 0.0} for i in range(1, 21)]
        clustered = kb.clustered_mean_interval(kb.per_date_aggregates(rows, "d"))
        row_level = kb.clustered_mean_interval(
            [(f"r{i}", r["d"], 1) for i, r in enumerate(rows)])
        self.assertGreater(clustered["high"] - clustered["low"],
                           2 * (row_level["high"] - row_level["low"]))

    def test_fewer_than_two_dates_is_a_refusal_not_an_interval(self):
        out = kb.clustered_mean_interval([("2023-05-01", 1.0, 5)])
        self.assertIsNone(out["low"])
        self.assertIsNone(out["estimate"])


class SummaryTests(unittest.TestCase):
    def test_summary_shape_and_values_on_a_fixture_season(self):
        world = World(days=90)
        rows = world.build()["rows"]
        s = kb.summarise_season(rows)
        lines = s["all_scored"]["lines"]
        self.assertEqual(set(lines), {"3.5", "4.5", "5.5", "6.5"})
        for key, block in lines.items():
            self.assertEqual(block["n"], len(rows))
            mean_d = sum(r[f"d_{key}"] for r in rows) / len(rows)
            self.assertAlmostEqual(block["paired"]["estimate"], mean_d, places=12)
            self.assertAlmostEqual(
                block["log_loss_baseline"] - block["log_loss_candidate"],
                mean_d, places=10)
            self.assertAlmostEqual(
                block["paired"]["minimum_detectable_effect_80pct"],
                2.8 * block["paired"]["se"])
        for block in lines.values():
            self.assertAlmostEqual(
                block["shape_effect_descriptive"]["estimate"]
                + block["information_effect_descriptive"]["estimate"],
                block["paired"]["estimate"], places=10)
        mae = s["all_scored"]["expected_strikeouts_mae"]
        self.assertAlmostEqual(mae["mae_baseline"] - mae["mae_candidate"],
                               mae["paired"]["estimate"], places=10)
        self.assertEqual(len(s["reliability"]["4.5"]["base"]), 10)
        self.assertLessEqual(s["experienced_pitchers_descriptive"]["lines"]["4.5"]["n"],
                             len(rows))

    def test_empty_rows_summarise_without_raising(self):
        s = kb.summarise_season([])
        self.assertEqual(s["all_scored"]["lines"]["4.5"], {"line": 4.5, "n": 0})


class ScriptArtifactTests(unittest.TestCase):
    def test_script_writes_an_artifact_and_refuses_to_overwrite_it(self):
        script = _load_script()
        world = World(days=90)
        built = world.build()
        meta = {"rule_id": "x", "season": 2023, "inputs": {}}
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "nested", "k.json")
            with mock.patch.object(script, "run", return_value=(
                    built["rows"], built["counts"], meta)), \
                    mock.patch("builtins.print"):
                self.assertEqual(script.main(["--season", "2023", "--out", out]), 0)
                artifact = json.loads(Path(out).read_text(encoding="utf-8"))
                self.assertEqual(artifact["season"], 2023)
                self.assertIn("sign_convention", artifact)
                self.assertEqual(artifact["counts"]["scored"], len(built["rows"]))
                self.assertEqual(artifact["bootstrap"]["seed"], kb.BOOTSTRAP_SEED)
                self.assertEqual(artifact["fixed_parameters"]["prior_weight_bf"], 70.0)
                with mock.patch("sys.stderr"):
                    self.assertEqual(
                        script.main(["--season", "2023", "--out", out]), 2)

    def test_run_streams_only_in_window_rows_end_to_end(self):
        script = _load_script()
        world = World(days=90)
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "pitcher_logs.jsonl")
            rows = world.rows + [_log(700, "2025-05-01", 99, 99),
                                 _log(701, "2026-05-01", 98, 98),
                                 {"person_id": 5, "marker": True}]
            with open(path, "w", encoding="utf-8") as fh:
                for r in rows:
                    fh.write(json.dumps(r) + "\n")
            scored, counts, meta = script.run(2023, logs_path=path)
            clean = kb.build_comparison_rows(
                season=2023, starts=world.starts(), min_league_starts=500)
            self.assertEqual(scored, clean["rows"])
            self.assertEqual(meta["inputs"]["pitcher_logs_in_window_digest"]["rows"],
                             len(world.rows))
            with self.assertRaises(kb.SealedDataError):
                script.run(2025, logs_path=path)

    def test_verdict_mode_applies_the_rule_to_the_two_artifacts(self):
        script = _load_script()
        with tempfile.TemporaryDirectory() as tmp:
            for season, est, lo in ((2023, 0.004, 0.001), (2024, 0.004, 0.001)):
                lines = {k: {"paired": {"estimate": est, "low": lo, "high": 0.01}}
                         for k in ("3.5", "4.5", "5.5", "6.5")}
                Path(tmp, f"k_baseline_{season}.json").write_text(json.dumps(
                    {"summary": {"all_scored": {"lines": lines}}}), encoding="utf-8")
            self.assertEqual(script.apply_rule(tmp)["verdict"], kb.SUPPORTED)


if __name__ == "__main__":
    unittest.main()
