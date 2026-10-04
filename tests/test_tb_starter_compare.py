"""Tests for the starter-aware total-bases comparison, on SYNTHETIC rows only.

`src/research/tb_starter.py` and `scripts/tb_starter_compare.py` implement the
comparison registered in `docs/PREREG_TB_STARTER_AWARE.md`. Nothing here opens
a real store: every row is built in this file, so the harness is proven before
any outcome-bearing data is touched.
"""

from __future__ import annotations

import importlib.util
import json
import os
import random
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from src.analysis import playerprops  # noqa: E402
from src.model import discovery  # noqa: E402
from src.research import tb_starter as tbs  # noqa: E402

SLOT_TABLE = {1: 4.155, 2: 4.045, 3: 3.947, 4: 3.842, 5: 3.662,
              6: 3.513, 7: 3.325, 8: 3.161, 9: 2.872}   # shape of the frozen table


def _load_script():
    spec = importlib.util.spec_from_file_location(
        "tb_starter_compare", REPO_ROOT / "scripts" / "tb_starter_compare.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _batter_row(date, game_pk, pid, side, team_id, *, pa=4, h=1, doubles=0,
                triples=0, hr=0, r=0, rbi=0):
    singles = h - doubles - triples - hr
    assert singles >= 0
    return {"type": "batter", "date": date, "game_pk": game_pk,
            "player_id": pid, "side": side, "team_id": team_id, "pa": pa,
            "ab": pa, "h": h, "doubles": doubles, "triples": triples, "hr": hr,
            "r": r, "rbi": rbi,
            "total_bases": singles + 2 * doubles + 3 * triples + 4 * hr}


def _result(game_pk, date, *, away_probable=None, home_probable=None,
            game_type="R", away_team=1, home_team=2):
    return {"game_pk": game_pk, "date": date, "game_type": game_type,
            "away_team_id": str(away_team), "home_team_id": str(home_team),
            "away_probable_id": "" if away_probable is None else str(away_probable),
            "home_probable_id": "" if home_probable is None else str(home_probable)}


def _stats(rng):
    """A plausible random batter line; consistent with total_bases."""
    pa = rng.choice([3, 4, 4, 5])
    h = rng.choice([0, 0, 1, 1, 2])
    h = min(h, pa)
    doubles = 1 if h >= 1 and rng.random() < 0.25 else 0
    hr = 1 if h - doubles >= 1 and rng.random() < 0.15 else 0
    return dict(pa=pa, h=h, doubles=doubles, hr=hr, r=rng.choice([0, 1]),
                rbi=rng.choice([0, 0, 1]))


class FixtureWorld:
    """Eighteen dates, one game a day, two five-man batting sides."""

    def __init__(self, season=2023, seed=7, days=18):
        rng = random.Random(seed)
        self.season = season
        self.box, self.results, self.pitchers = [], {}, []
        self.dates = [f"{season}-04-{d:02d}" for d in range(1, days + 1)]
        self.away_batters = [100, 101, 102, 103, 104]
        self.home_batters = [200, 201, 202, 203, 204]
        self.away_starter, self.home_starter = 900, 901
        for i, date in enumerate(self.dates):
            pk = 5000 + i
            self.results[pk] = _result(
                pk, date, away_probable=self.away_starter,
                home_probable=self.home_starter)
            for pid in self.away_batters:
                self.box.append(_batter_row(date, pk, pid, "away", 1,
                                            **_stats(rng)))
            for pid in self.home_batters:
                self.box.append(_batter_row(date, pk, pid, "home", 2,
                                            **_stats(rng)))
            for pid in (self.away_starter, self.home_starter):
                self.pitchers.append({
                    "person_id": pid, "date": date, "season": str(season),
                    "hits": rng.choice([3, 5, 7, 9]),
                    "batters_faced": rng.choice([20, 24, 27])})

    def build(self, **overrides):
        kwargs = dict(season=self.season, box_rows=self.box,
                      results=self.results, slot_map={},
                      starters=tbs.StarterIndex(self.pitchers),
                      slot_table=SLOT_TABLE)
        kwargs.update(overrides)
        return tbs.build_comparison_rows(**kwargs)


class WindowGuardTests(unittest.TestCase):
    def test_in_window_boundaries(self):
        self.assertTrue(tbs.in_window("2023-01-01"))
        self.assertTrue(tbs.in_window("2024-12-31"))
        self.assertTrue(tbs.in_window("2023-03-30T23:08:00Z"))
        for bad in ("2022-12-31", "2025-01-01", "2025-06-15", "2026-01-01",
                    "2026-09-09", "", None, 20230330, "garbage"):
            self.assertFalse(tbs.in_window(bad), bad)

    def test_assert_allowed_date_is_a_hard_error_for_2025_and_2026(self):
        for bad in ("2025-04-01", "2025-12-31", "2026-01-01", "2026-08-27",
                    "2026-10-03"):
            with self.assertRaises(tbs.SealedDataError):
                tbs.assert_allowed_date(bad)
        self.assertEqual(tbs.assert_allowed_date("2024-09-29"), "2024-09-29")

    def test_season_guard(self):
        for bad in (2025, 2026, "2025", 2022, "x", None, True):
            with self.assertRaises(tbs.SealedDataError):
                tbs.assert_allowed_season(bad)
        self.assertEqual(tbs.assert_allowed_season("2023"), 2023)
        self.assertEqual(tbs.assert_allowed_season(2024), 2024)

    def test_allowed_seasons_match_the_matrix_guard(self):
        from src.research import matrix
        self.assertEqual(tbs.ALLOWED_SEASONS, matrix.ALLOWED_SEASONS)

    def test_build_refuses_2025_and_2026(self):
        world = FixtureWorld()
        for bad in (2025, 2026):
            with self.assertRaises(tbs.SealedDataError):
                world.build(season=bad)

    def test_starter_index_refuses_a_2025_or_2026_question(self):
        index = tbs.StarterIndex([{"person_id": 1, "date": "2023-05-01",
                                   "hits": 5, "batters_faced": 24}])
        for bad in ("2025-05-01", "2026-05-01"):
            with self.assertRaises(tbs.SealedDataError):
                index.before(1, bad)

    def test_sealed_rows_never_enter_the_inputs(self):
        index = tbs.StarterIndex([
            {"person_id": 1, "date": "2023-05-01", "hits": 5, "batters_faced": 24},
            {"person_id": 1, "date": "2025-05-01", "hits": 99, "batters_faced": 99},
            {"person_id": 1, "date": "2026-05-01", "hits": 77, "batters_faced": 77},
            {"person_id": 1, "date": None, "hits": 1, "batters_faced": 1}])
        self.assertEqual(index.before(1, "2023-06-01"), (5, 24))
        self.assertEqual(index.skipped["no_date_or_outside_window"], 3)
        seen, stats = tbs.build_slot_map([
            {"date": "2026-09-09", "game_pk": 1,
             "away": [{"person_id": 5, "order": 1}], "home": []},
            {"date": "2023-05-01", "game_pk": 2,
             "away": [{"person_id": 5, "order": 3}], "home": []}])
        self.assertEqual(seen, {(2, 5): 3})
        self.assertEqual(stats["lineup_rows_outside_window"], 1)

    def test_a_sealed_dated_box_row_is_dropped_not_priced(self):
        world = FixtureWorld()
        world.box.append(_batter_row("2026-04-01", 9999, 100, "away", 1))
        world.box.append(_batter_row("2025-04-01", 9998, 100, "away", 1))
        built = world.build()
        self.assertEqual(built["counts"]["excluded_wrong_season_date"], 2)
        self.assertTrue(all(tbs.in_window(r["date"]) for r in built["rows"]))

    def test_script_refuses_other_seasons_before_touching_any_file(self):
        script = _load_script()
        with mock.patch.object(script, "run",
                               side_effect=AssertionError("run was called")),                 mock.patch("sys.stderr"):
            for bad in ("2025", "2026", "2022", "abc"):
                self.assertEqual(script.main(["--season", bad]), 2)

    def test_script_never_builds_a_path_for_a_refused_season(self):
        script = _load_script()
        with mock.patch.object(script, "_open_text",
                               side_effect=AssertionError("a file was opened")):
            with self.assertRaises(tbs.SealedDataError):
                script.run(2025)


class StrictlyBeforeTests(unittest.TestCase):
    def test_a_game_on_the_date_never_counts_for_the_batter(self):
        world = FixtureWorld()
        built = world.build()
        by_key = {(r["date"], r["player_id"]): r for r in built["rows"]}
        target_date = world.dates[10]
        pid = 100
        prior = [r for r in world.box if r["player_id"] == pid
                 and r["date"] < target_date]
        league_rows = [r for r in world.box if r["date"] < target_date]
        league = playerprops.league_rates(league_rows)
        game = world.results[5010]
        totals = tbs.StarterIndex(world.pitchers).before(
            int(game["home_probable_id"]), target_date)
        expected = tbs.price_arms(
            line=1.5, batter_lines=prior, league=league, batting_slot=None,
            slot_table=SLOT_TABLE, starter_totals=totals)
        got = by_key[(target_date, pid)]
        self.assertEqual(got["p2_without"], expected["p_without"])
        self.assertEqual(got["p2_with"], expected["p_with"])

    def test_poisoning_the_game_on_the_date_changes_nothing(self):
        base = FixtureWorld()
        clean = {(r["date"], r["player_id"]): r for r in base.build()["rows"]}
        poisoned = FixtureWorld()
        target = poisoned.dates[14]
        for row in poisoned.box:
            if row["date"] == target and row["player_id"] == 100:
                row.update(h=4, hr=4, doubles=0, triples=0, total_bases=16,
                           pa=4)
        for p in poisoned.pitchers:
            if p["date"] == target:
                p.update(hits=40, batters_faced=40)
        dirty = {(r["date"], r["player_id"]): r for r in poisoned.build()["rows"]}
        # The target date's OWN predictions are untouched by its own outcomes...
        for pid in (100, 101, 200):
            a, b = clean[(target, pid)], dirty[(target, pid)]
            self.assertEqual((a["p2_without"], a["p2_with"]),
                             (b["p2_without"], b["p2_with"]))
        # ...and the NEXT date does see them.
        later = poisoned.dates[15]
        self.assertNotEqual(clean[(later, 100)]["p2_without"],
                            dirty[(later, 100)]["p2_without"])
        self.assertNotEqual(clean[(later, 100)]["starter_hits"],
                            dirty[(later, 100)]["starter_hits"])

    def test_doubleheader_second_game_does_not_see_the_first(self):
        world = FixtureWorld()
        date = world.dates[10]
        world.results[8001] = _result(8001, date, away_probable=900,
                                      home_probable=901)
        world.box.append(_batter_row(date, 8001, 100, "away", 1, h=3, hr=3,
                                     pa=4))
        built = world.build()
        rows = [r for r in built["rows"] if r["date"] == date
                and r["player_id"] == 100]
        self.assertEqual(len(rows), 2)                     # one per game
        self.assertEqual({r["game_pk"] for r in rows}, {5010, 8001})
        self.assertEqual(rows[0]["p2_without"], rows[1]["p2_without"])
        self.assertEqual(rows[0]["starter_hits"], rows[1]["starter_hits"])

    def test_starter_totals_are_same_season_and_strictly_before(self):
        pitchers = [
            {"person_id": 9, "date": "2023-04-01", "hits": 4, "batters_faced": 20},
            {"person_id": 9, "date": "2023-04-07", "hits": 6, "batters_faced": 25},
            {"person_id": 9, "date": "2023-04-13", "hits": 50, "batters_faced": 50},
            {"person_id": 9, "date": "2024-04-02", "hits": 8, "batters_faced": 30},
        ]
        index = tbs.StarterIndex(pitchers)
        self.assertEqual(index.before(9, "2023-04-13"), (10, 45))   # not the 13th
        self.assertEqual(index.before(9, "2023-04-14"), (60, 95))
        self.assertIsNone(index.before(9, "2023-04-01"))            # nothing before
        self.assertIsNone(index.before(9, "2024-04-02"))            # 2023 is not 2024
        self.assertEqual(index.before(9, "2024-04-03"), (8, 30))
        self.assertIsNone(index.before(12345, "2023-06-01"))
        self.assertIsNone(index.before(None, "2023-06-01"))

    def test_zero_batters_faced_is_no_information(self):
        index = tbs.StarterIndex([{"person_id": 9, "date": "2023-04-01",
                                   "hits": 0, "batters_faced": 0}])
        self.assertIsNone(index.before(9, "2023-05-01"))

    def test_missing_hits_or_bf_is_skipped_not_zero_filled(self):
        index = tbs.StarterIndex([
            {"person_id": 9, "date": "2023-04-01", "hits": None, "batters_faced": 20},
            {"person_id": 9, "date": "2023-04-05", "hits": 4, "batters_faced": 20}])
        self.assertEqual(index.before(9, "2023-05-01"), (4, 20))
        self.assertEqual(index.skipped["missing_hits_or_bf"], 1)

    def test_running_league_equals_the_models_own_league_rates(self):
        world = FixtureWorld()
        league = tbs.RunningLeague()
        self.assertIsNone(league.rates())
        for row in world.box:
            league.add(row)
        self.assertEqual(league.rates(), playerprops.league_rates(world.box))

    def test_first_date_has_no_league_history_and_is_counted(self):
        world = FixtureWorld()
        built = world.build()
        first = world.dates[0]
        self.assertTrue(all(r["date"] != first for r in built["rows"]))
        self.assertEqual(built["counts"]["excluded_no_league_history"], 10)


class OneRowPerBatterGameTests(unittest.TestCase):
    def test_duplicates_are_dropped_and_counted(self):
        world = FixtureWorld()
        dup = dict(world.box[-3])
        world.box.append(dup)
        world.box.append(dict(dup))
        built = world.build()
        keys = [(r["game_pk"], r["player_id"]) for r in built["rows"]]
        self.assertEqual(len(keys), len(set(keys)))
        self.assertEqual(built["counts"]["excluded_duplicate_batter_game"], 2)

    def test_non_regular_season_and_unmatched_games_are_excluded(self):
        world = FixtureWorld()
        world.results[7000] = _result(7000, world.dates[12], game_type="D",
                                      away_probable=900, home_probable=901)
        world.box.append(_batter_row(world.dates[12], 7000, 100, "away", 1))
        world.box.append(_batter_row(world.dates[12], 7777, 100, "away", 1))
        built = world.build()
        self.assertEqual(
            built["counts"]["excluded_not_regular_season_or_unmatched_game"], 2)
        self.assertNotIn(7000, {r["game_pk"] for r in built["rows"]})

    def test_pitcher_rows_and_linescore_rows_are_not_batters(self):
        world = FixtureWorld()
        world.box.append({"type": "pitcher", "date": world.dates[5],
                          "game_pk": 5005, "player_id": 900, "h": 3,
                          "batters_faced": 20})
        world.box.append({"type": "linescore", "date": world.dates[5],
                          "game_pk": 5005})
        built = world.build()
        self.assertEqual(built["counts"]["batter_rows"], len(world.box) - 2)

    def test_side_team_mismatch_is_excluded_and_counted(self):
        world = FixtureWorld()
        world.box.append(_batter_row(world.dates[12], 5012, 555, "away", 2))
        built = world.build()
        self.assertEqual(built["counts"]["excluded_side_team_mismatch"], 1)

    def test_batter_below_the_floor_is_excluded_from_both_arms_and_counted(self):
        world = FixtureWorld()
        world.box.append(_batter_row(world.dates[12], 5012, 777, "home", 2))
        built = world.build()
        self.assertNotIn(777, {r["player_id"] for r in built["rows"]})
        self.assertGreaterEqual(built["counts"]["excluded_no_rate"], 1)
        self.assertIn("below the plate-appearance floor",
                      built["counts"]["excluded_no_rate_by_cause"])
        # Every surviving row carries BOTH arms; none carries one.
        for r in built["rows"]:
            self.assertIsNotNone(r["p2_without"])
            self.assertIsNotNone(r["p2_with"])


class TwoArmTests(unittest.TestCase):
    def _kwargs(self, line=1.5):
        world = FixtureWorld()
        prior = [r for r in world.box if r["player_id"] == 100
                 and r["date"] < world.dates[12]]
        league = playerprops.league_rates(
            [r for r in world.box if r["date"] < world.dates[12]])
        return dict(line=line, batter_lines=prior, league=league,
                    batting_slot=3, slot_table=SLOT_TABLE)

    def test_arms_identical_when_the_starter_is_unknown(self):
        for line in (1.5, 0.5):
            arms = tbs.price_arms(starter_totals=None, **self._kwargs(line))
            self.assertEqual(arms["p_without"], arms["p_with"])
            self.assertEqual(arms["pitcher_factor"], 1.0)
            self.assertEqual(arms["blended_factor"], 1.0)

    def test_arms_differ_only_through_the_two_starter_arguments(self):
        kw = self._kwargs()
        arms = tbs.price_arms(starter_totals=(40, 100), **kw)
        common = dict(market="batter_total_bases", line=1.5,
                      batter_lines=kw["batter_lines"], league=kw["league"],
                      batting_slot=3, slot_table=SLOT_TABLE)
        direct_without = playerprops.price_prop(**common)
        direct_with = playerprops.price_prop(
            **common, pitcher_hits_allowed=40, pitcher_batters_faced=100)
        self.assertEqual(arms["p_without"], direct_without["probability"])
        self.assertEqual(arms["p_with"], direct_with["probability"])
        self.assertNotEqual(arms["p_with"], arms["p_without"])
        # Everything else the model reports is identical across the arms.
        self.assertEqual(direct_without["expected_pa"], direct_with["expected_pa"])
        self.assertEqual(direct_without["expected_pa_source"],
                         direct_with["expected_pa_source"])
        self.assertEqual(arms["expected_pa"], arms["expected_pa_with"])
        self.assertEqual(direct_without["batter_hit_rate"],
                         direct_with["batter_hit_rate"])

    def test_a_hit_prone_starter_raises_and_a_stingy_one_lowers(self):
        kw = self._kwargs()
        hot = tbs.price_arms(starter_totals=(45, 100), **kw)
        cold = tbs.price_arms(starter_totals=(15, 100), **kw)
        self.assertGreater(hot["p_with"], hot["p_without"])
        self.assertLess(cold["p_with"], cold["p_without"])

    def test_unknown_starter_rows_are_identical_in_a_full_build(self):
        world = FixtureWorld()
        world.results[5011]["home_probable_id"] = ""          # no probable id
        world.results[5012]["home_probable_id"] = "424242"    # never logged
        built = world.build()
        unknown = [r for r in built["rows"] if not r["starter_known"]]
        self.assertTrue(unknown)
        for r in unknown:
            self.assertEqual(r["p2_without"], r["p2_with"])
            self.assertEqual(r["p1_without"], r["p1_with"])
            self.assertEqual(r["d2"], 0.0)
            self.assertEqual(r["d1"], 0.0)
        causes = built["counts"]["starter_unknown_by_cause"]
        self.assertGreater(causes["no_probable_id"], 0)
        self.assertGreater(causes["no_prior_logged_appearance"], 0)
        known = [r for r in built["rows"] if r["starter_known"]]
        self.assertTrue(any(r["p2_without"] != r["p2_with"] for r in known))

    def test_opposing_starter_is_the_other_clubs_probable(self):
        world = FixtureWorld()
        built = world.build()
        # Away batters face the HOME starter (901), home batters the AWAY (900).
        index = tbs.StarterIndex(world.pitchers)
        for r in built["rows"]:
            opposing = 901 if r["player_id"] < 200 else 900
            self.assertEqual((r["starter_hits"], r["starter_bf"]),
                             index.before(opposing, r["date"]))

    def test_slot_comes_from_the_lineup_and_uses_the_frozen_table(self):
        world = FixtureWorld()
        slot_map = {(5015, 100): 1, (5015, 101): 9}
        built = world.build(slot_map=slot_map)
        by = {(r["game_pk"], r["player_id"]): r for r in built["rows"]}
        self.assertEqual(by[(5015, 100)]["slot"], 1)
        self.assertEqual(by[(5015, 101)]["slot"], 9)
        self.assertIsNone(by[(5015, 102)]["slot"])
        kw = self._kwargs()
        arms = tbs.price_arms(starter_totals=None, **{**kw, "batting_slot": 1})
        priced = playerprops.price_prop(
            market="batter_total_bases", line=1.5,
            batter_lines=kw["batter_lines"], league=kw["league"],
            batting_slot=1, slot_table=SLOT_TABLE)
        self.assertEqual(priced["expected_pa"], 4.155)       # frozen, not V1's 4.467
        self.assertEqual(arms["expected_pa"], 4.155)

    def test_slot_map_conflict_falls_back_and_is_counted(self):
        rows = [
            {"date": "2023-05-01", "game_pk": 1,
             "away": [{"person_id": 5, "order": 3}], "home": []},
            {"date": "2023-05-01", "game_pk": 1,
             "away": [{"person_id": 5, "order": 4}], "home": []},
            {"date": "2023-05-01", "empty": True}]
        seen, stats = tbs.build_slot_map(rows)
        self.assertIsNone(seen[(1, 5)])
        self.assertEqual(stats["conflicting_batters"], 1)
        self.assertEqual(stats["lineup_rows_empty_marker"], 1)

    def test_limit_prices_a_slice_only(self):
        world = FixtureWorld()
        full = world.build()
        part = world.build(limit=7)
        self.assertEqual(len(part["rows"]), 7)
        self.assertEqual(part["rows"], full["rows"][:7])


class SignAndDecisionTests(unittest.TestCase):
    def test_sign_convention_positive_means_with_is_better(self):
        # y = 1 and WITH is more confident: WITH has the lower loss, d > 0.
        self.assertGreater(tbs.paired_difference(0.30, 0.45, 1), 0)
        # y = 0 and WITH is more confident of an event that did not happen.
        self.assertLess(tbs.paired_difference(0.30, 0.45, 0), 0)
        # Identical probabilities are exactly zero.
        self.assertEqual(tbs.paired_difference(0.3, 0.3, 1), 0.0)
        self.assertEqual(tbs.paired_difference(0.3, 0.3, 0), 0.0)
        # And it is literally loss(without) - loss(with).
        self.assertAlmostEqual(
            tbs.paired_difference(0.2, 0.5, 1),
            tbs.log_loss_one(0.2, 1) - tbs.log_loss_one(0.5, 1))

    def test_log_loss_clips_and_stays_finite(self):
        self.assertTrue(tbs.log_loss_one(0.0, 1) < 1e3)
        self.assertTrue(tbs.log_loss_one(1.0, 0) < 1e3)
        self.assertEqual(tbs.log_loss_one(0.0, 1), tbs.log_loss_one(1e-9, 1))

    def _block(self, est, low, high):
        return {"estimate": est, "low": low, "high": high}

    def test_decision_rule_as_registered(self):
        decide = tbs.decide
        self.assertEqual(decide(self._block(0.001, -0.001, 0.003),
                                self._block(0.002, 0.0005, 0.004))["verdict"],
                         tbs.SUPPORTED)
        # 2024 interval above zero but 2023 point estimate negative or zero.
        self.assertEqual(decide(self._block(-0.001, -0.003, 0.001),
                                self._block(0.002, 0.0005, 0.004))["verdict"],
                         tbs.NOT_SUPPORTED)
        self.assertEqual(decide(self._block(0.0, -0.003, 0.003),
                                self._block(0.002, 0.0005, 0.004))["verdict"],
                         tbs.NOT_SUPPORTED)
        # 2024 interval includes zero.
        self.assertEqual(decide(self._block(0.01, 0.0, 0.02),
                                self._block(0.002, -0.0005, 0.004))["verdict"],
                         tbs.NOT_SUPPORTED)
        self.assertEqual(decide(self._block(0.01, 0.0, 0.02),
                                self._block(0.002, 0.0, 0.004))["verdict"],
                         tbs.NOT_SUPPORTED)          # touching zero is not excluding it
        # 2024 interval entirely below zero is WORSE whatever 2023 said.
        for first in (0.005, -0.005):
            self.assertEqual(decide(self._block(first, -0.01, 0.01),
                                    self._block(-0.002, -0.004, -0.0005))["verdict"],
                             tbs.WORSE)
        # Missing inputs never support.
        self.assertEqual(decide(None, self._block(0.1, 0.05, 0.2))["verdict"],
                         tbs.NOT_SUPPORTED)
        self.assertEqual(decide(self._block(0.1, 0.0, 0.2),
                                {"estimate": None, "low": None,
                                 "high": None})["verdict"], tbs.NOT_SUPPORTED)


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
        agg = tbs.per_date_aggregates(rows)
        a = tbs.clustered_mean_interval(agg, seed=11)
        b = tbs.clustered_mean_interval(agg, seed=11)
        self.assertEqual(a, b)
        self.assertNotEqual(a["low"], tbs.clustered_mean_interval(agg, seed=12)["low"])
        # Row order cannot move it.
        shuffled = list(rows)
        random.Random(0).shuffle(shuffled)
        c = tbs.clustered_mean_interval(tbs.per_date_aggregates(shuffled), seed=11)
        self.assertAlmostEqual(a["low"], c["low"], places=12)
        self.assertAlmostEqual(a["high"], c["high"], places=12)

    def test_matches_the_repos_own_date_clustered_bootstrap(self):
        rows = self._rows()
        mine = tbs.clustered_mean_interval(
            tbs.per_date_aggregates(rows), resamples=500, seed=99)
        theirs = discovery.clustered_bootstrap(
            rows, lambda sample: sum(r["d"] for r in sample) / len(sample),
            resamples=500, seed=99)
        self.assertAlmostEqual(mine["low"], theirs["low"], places=5)
        self.assertAlmostEqual(mine["high"], theirs["high"], places=5)

    def test_estimate_is_the_plain_mean_and_interval_brackets_it(self):
        rows = self._rows()
        out = tbs.clustered_mean_interval(tbs.per_date_aggregates(rows))
        mean = sum(r["d"] for r in rows) / len(rows)
        self.assertAlmostEqual(out["estimate"], mean, places=12)
        self.assertLessEqual(out["low"], mean)
        self.assertGreaterEqual(out["high"], mean)
        self.assertEqual(out["clusters"], 25)
        self.assertEqual(out["n"], len(rows))
        self.assertEqual(out["resamples"], tbs.BOOTSTRAP_RESAMPLES)

    def test_resamples_dates_not_rows(self):
        # One huge date and many quiet ones: a row-level bootstrap would give a
        # narrow interval, a date-level one a wide one.
        rows = [{"date": "2023-05-01", "d": 1.0} for _ in range(200)]
        rows += [{"date": f"2023-06-{i:02d}", "d": 0.0} for i in range(1, 21)]
        clustered = tbs.clustered_mean_interval(tbs.per_date_aggregates(rows))
        row_level = tbs.clustered_mean_interval(
            [(f"r{i}", r["d"], 1) for i, r in enumerate(rows)])
        self.assertGreater(clustered["high"] - clustered["low"],
                           2 * (row_level["high"] - row_level["low"]))

    def test_fewer_than_two_dates_is_a_refusal_not_an_interval(self):
        out = tbs.clustered_mean_interval([("2023-05-01", 1.0, 5)])
        self.assertIsNone(out["low"])
        self.assertIsNone(out["estimate"])


class SummaryTests(unittest.TestCase):
    def test_summary_shape_on_a_fixture_season(self):
        world = FixtureWorld(days=40)
        built = world.build()
        summary = tbs.summarise_season(built["rows"])
        primary = summary["all_rows"]["primary_2plus_tb"]
        self.assertEqual(primary["n"], len(built["rows"]))
        self.assertIsNotNone(primary["paired"]["estimate"])
        known = summary["starter_known_subset"]["primary_2plus_tb"]
        self.assertEqual(known["n"], built["counts"]["starter_known"])
        self.assertEqual(sum(t["n"] for t in summary["terciles"]["primary_2plus_tb"]),
                         built["counts"]["starter_known"])
        self.assertEqual(summary["factor_distribution"]["n"],
                         built["counts"]["starter_known"])
        for arm in ("without", "with"):
            table = summary["reliability"]["primary_2plus_tb"][arm]
            self.assertEqual(sum(b["count"] for b in table), primary["n"])
        # The mean of d is the difference of the two mean losses.
        self.assertAlmostEqual(
            primary["paired"]["estimate"],
            primary["log_loss_without"] - primary["log_loss_with"], places=12)
        json.dumps(summary)                      # the artifact must serialise

    def test_terciles_are_ordered_by_factor(self):
        world = FixtureWorld(days=40)
        built = world.build()
        t = tbs.tercile_table(built["rows"], "2")
        self.assertLessEqual(t[0]["factor_max"], t[1]["factor_min"])
        self.assertLessEqual(t[1]["factor_max"], t[2]["factor_min"])


class ScriptArtifactTests(unittest.TestCase):
    def test_script_writes_an_artifact_and_refuses_to_overwrite_it(self):
        script = _load_script()
        world = FixtureWorld(days=30)
        built = world.build()
        meta = {"rule_id": "x", "season": 2023, "inputs": {}}
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "nested", "tb.json")
            with mock.patch.object(script, "run", return_value=(
                    built["rows"], built["counts"], meta)),                     mock.patch("builtins.print"):
                self.assertEqual(
                    script.main(["--season", "2023", "--out", out]), 0)
                artifact = json.loads(Path(out).read_text(encoding="utf-8"))
                self.assertEqual(artifact["season"], 2023)
                self.assertIn("sign_convention", artifact)
                self.assertEqual(artifact["counts"]["scored"], len(built["rows"]))
                self.assertEqual(artifact["bootstrap"]["seed"], tbs.BOOTSTRAP_SEED)
                # A second run for the same season is refused.
                with mock.patch("sys.stderr"):
                    self.assertEqual(
                        script.main(["--season", "2023", "--out", out]), 2)

    def test_time_slice_prints_no_metric_and_writes_nothing(self):
        script = _load_script()
        world = FixtureWorld(days=30)
        built = world.build(limit=5)
        meta = {"price_seconds": 0.5, "load_seconds": 0.1}
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "never.json")
            with mock.patch.object(script, "run", return_value=(
                    built["rows"], built["counts"], meta)), \
                    mock.patch("builtins.print") as printed:
                self.assertEqual(script.main(
                    ["--season", "2023", "--time-slice", "5", "--out", out]), 0)
            self.assertFalse(os.path.exists(out))
            text = " ".join(str(c) for c in printed.call_args_list)
            self.assertNotIn("mean d", text)


if __name__ == "__main__":
    unittest.main()
