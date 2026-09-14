"""Pure-function tests for scripts/probe_prop_calibration.py: bucketing,
Brier/log-loss scoring, and the contract-to-box-row join. Every test here
fails against the pre-fix code for the reason stated in its docstring
(dated 2026-09-14) and none of them touches a store on disk -- synthetic
rows only, per `a-test-that-reads-the-disk`.
"""

from __future__ import annotations

import importlib.util
import math
import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "scripts", "probe_prop_calibration.py")


def _load():
    spec = importlib.util.spec_from_file_location(
        "probe_prop_calibration", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


probe = _load()


def _contract(market, line, side, probability, market_probability=0.5,
              player="Test Batter", expected_pa_source="season_average"):
    return {
        "player": player, "market": market, "line": line, "side": side,
        "probability": probability, "market_probability": market_probability,
        "expected_pa_source": expected_pa_source, "event_id": "e1",
    }


def _box(date, **stats):
    row = {"type": "batter", "player_name": "Test Batter", "date": date}
    row.update(stats)
    return row


class BucketLabelTests(unittest.TestCase):
    """The brief's four buckets are 0.5-0.6, 0.6-0.7, 0.7-0.8, 0.8+, each
    edge belonging to the bucket it starts (half-open [lo, hi)) -- a naive
    `int(p * 10)` bucketer used by a neighbouring script rounds 0.6 down
    into the wrong bucket under float noise, which is exactly the class of
    bug these boundary checks are here to catch.
    """

    def test_below_the_floor_is_excluded(self):
        # A probability under 0.5 is the disfavoured side of some other
        # contract's pair and does not belong on a "how good are our
        # favourites" table at all. Returning a bucket for it (e.g. by
        # clamping) would silently pull the disfavoured arm into the report.
        self.assertIsNone(probe.bucket_label(0.499999))
        self.assertIsNone(probe.bucket_label(0.1))

    def test_each_lower_edge_belongs_to_its_own_bucket(self):
        self.assertEqual(probe.bucket_label(0.5), "50%-60%")
        self.assertEqual(probe.bucket_label(0.6), "60%-70%")
        self.assertEqual(probe.bucket_label(0.7), "70%-80%")
        self.assertEqual(probe.bucket_label(0.8), "80%+")

    def test_just_under_an_edge_stays_in_the_lower_bucket(self):
        self.assertEqual(probe.bucket_label(0.5999999999), "50%-60%")
        self.assertEqual(probe.bucket_label(0.7999999999), "70%-80%")

    def test_a_perfect_prediction_lands_in_the_top_bucket(self):
        self.assertEqual(probe.bucket_label(1.0), "80%+")

    def test_none_is_not_a_bucket(self):
        self.assertIsNone(probe.bucket_label(None))


class ScoringTests(unittest.TestCase):
    """Brier and log-loss against a hand-computed answer, not just "runs
    without crashing" -- a sign error in either (e.g. `(p - y)` vs
    `(y - p) ** 2` used elsewhere, or scoring `1 - p` for a win) produces a
    plausible-looking number that is quietly wrong in every report this
    script prints, and only a fixed expected value catches that.
    """

    def test_brier_score_matches_hand_computation(self):
        # (0.8-1)^2=0.04, (0.3-0)^2=0.09, (0.5-1)^2=0.25 -> mean 0.12667
        pairs = [(0.8, 1), (0.3, 0), (0.5, 1)]
        self.assertAlmostEqual(probe.brier_score(pairs), 0.38 / 3, places=9)

    def test_brier_score_zero_for_perfect_predictions(self):
        self.assertEqual(probe.brier_score([(1.0, 1), (0.0, 0)]), 0.0)

    def test_brier_score_none_on_empty_input(self):
        # Not 0.0 -- a 0.0 "score" for zero data reads as a perfect model,
        # which is the opposite of an honest "there is nothing to measure".
        self.assertIsNone(probe.brier_score([]))

    def test_log_loss_matches_hand_computation(self):
        pairs = [(0.8, 1), (0.4, 0)]
        expected = -(math.log(0.8) + math.log(0.6)) / 2
        self.assertAlmostEqual(probe.log_loss(pairs), expected, places=9)

    def test_log_loss_clamps_instead_of_diverging(self):
        # p=1.0 on a loss is -inf under a raw log(1-p); the EPS clamp this
        # module shares with backtest_player_props.py must keep it finite.
        result = probe.log_loss([(1.0, 0)])
        self.assertTrue(math.isfinite(result))


class OutcomeForContractTests(unittest.TestCase):
    """The join: a propboard contract plus a boxscore row settles to the
    right win/loss/push/void, INCLUDING `batter_runs_scored`, which is the
    one market `src.board.settle_props`'s own registry keys under a
    different name (`"batter_runs"`) -- see daily_card.py's 2026-09-12
    incident note. Going through that registry by market name would raise
    or silently refuse this market; calling `settle()` directly with the
    stat this module names is what makes it gradeable at all.
    """

    def test_batter_hits_over_wins_when_the_stat_clears_the_line(self):
        contract = _contract("batter_hits", 0.5, "Over", 0.7)
        row = _box("2026-09-05", h=1, total_bases=1, r=0)
        self.assertEqual(probe.outcome_for_contract(contract, row), "win")

    def test_batter_hits_under_wins_when_the_stat_stays_below_the_line(self):
        contract = _contract("batter_hits", 0.5, "Under", 0.3)
        row = _box("2026-09-05", h=0, total_bases=0, r=0)
        self.assertEqual(probe.outcome_for_contract(contract, row), "win")

    def test_batter_runs_scored_settles_by_name_despite_the_registry_gap(self):
        # This is the regression test for the mismatch: `market` here is
        # "batter_runs_scored", which is not a key in
        # `settle_props.PROP_STAT_RULES` at all. A version of
        # `outcome_for_contract` that looked the stat up through that
        # registry (or through `PROP_STAT_RULES[market]`) would raise
        # KeyError right here instead of returning "win".
        contract = _contract("batter_runs_scored", 0.5, "Over", 0.55)
        row = _box("2026-09-05", h=1, total_bases=1, r=1)
        self.assertEqual(probe.outcome_for_contract(contract, row), "win")

    def test_batter_total_bases_grades_the_total_bases_stat_not_hits(self):
        # A batter can have a hit (h=1) without clearing 1.5 total bases
        # (a single). Grading this market off `h` instead of `total_bases`
        # would wrongly call this a win.
        contract = _contract("batter_total_bases", 1.5, "Over", 0.4)
        row = _box("2026-09-05", h=1, total_bases=1, r=0)
        self.assertEqual(probe.outcome_for_contract(contract, row), "loss")

    def test_a_missing_box_row_is_void_not_a_loss(self):
        contract = _contract("batter_hits", 0.5, "Over", 0.7)
        self.assertEqual(probe.outcome_for_contract(contract, None), "void")

    def test_a_whole_number_line_can_push(self):
        contract = _contract("batter_hits", 1.0, "Over", 0.5)
        row = _box("2026-09-05", h=1, total_bases=1, r=0)
        self.assertEqual(probe.outcome_for_contract(contract, row), "push")


class ToYTests(unittest.TestCase):

    def test_win_is_one_loss_is_zero(self):
        self.assertEqual(probe.to_y("win"), 1)
        self.assertEqual(probe.to_y("loss"), 0)

    def test_push_and_void_are_excluded_not_scored_as_a_loss(self):
        # Folding a push/void into `0` would silently make the model look
        # worse than it is on exactly the lines it could not have graded.
        self.assertIsNone(probe.to_y("push"))
        self.assertIsNone(probe.to_y("void"))


class PreFirstPitchFilterTests(unittest.TestCase):
    """The mission's "LAST pre-first-pitch quote" requirement: a quote
    observed AT OR AFTER its own game's first pitch must never enter the
    board, because that is priced with the outcome already partly known.
    """

    def test_a_quote_after_commence_time_is_dropped(self):
        rows = [
            {"observed_utc": "2026-09-05T22:00:00Z",
             "commence_time": "2026-09-05T23:00:00Z"},   # before -- kept
            {"observed_utc": "2026-09-06T00:30:00Z",
             "commence_time": "2026-09-05T23:00:00Z"},   # after -- dropped
        ]
        kept = probe._pre_first_pitch(rows)
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0]["observed_utc"], "2026-09-05T22:00:00Z")


class SlotsForDateLeakageTests(unittest.TestCase):
    """Regression for Opus checker finding #1: a lineup row observed AFTER
    its own game's first pitch is the order that actually took the field,
    not the one posted pregame -- using it leaks the outcome's own inputs
    into that game's prediction. `_slots_for_date` must drop such rows
    (falling back to season_average) and keep only rows provably observed
    before commence_time.
    """

    def _entry(self, observed_utc):
        return {
            "date": "2026-09-09", "game_pk": 823090,
            "away": [{"name": "Ezequiel Duran", "order": 1}],
            "home": [{"name": "J.P. Crawford", "order": 1}],
            "observed_utc": observed_utc,
        }

    def test_a_lineup_observed_after_commence_time_is_dropped(self):
        # This is this store's own real shape (2026-09-14): the game's
        # commence_time was 2026-09-09T22:10Z but the lineup row was not
        # fetched until the next morning.
        lineup_index = {"g1": self._entry("2026-09-10T10:11:12Z")}
        commence = {"823090": "2026-09-09T22:10:00Z"}
        slots = probe._slots_for_date("2026-09-09", lineup_index, commence)
        self.assertEqual(slots, {})

    def test_a_lineup_observed_before_commence_time_is_kept(self):
        lineup_index = {"g1": self._entry("2026-09-09T20:00:00Z")}
        commence = {"823090": "2026-09-09T22:10:00Z"}
        slots = probe._slots_for_date("2026-09-09", lineup_index, commence)
        self.assertEqual(slots.get("Ezequiel Duran"), 1)
        self.assertEqual(slots.get("J.P. Crawford"), 1)

    def test_an_unresolvable_game_pk_is_dropped_not_trusted(self):
        # No entry in the game_pk->commence_time index at all: this probe
        # cannot PROVE the lineup predates first pitch, so it must not use
        # it, rather than assuming it is safe.
        lineup_index = {"g1": self._entry("2026-09-09T20:00:00Z")}
        slots = probe._slots_for_date("2026-09-09", lineup_index, {})
        self.assertEqual(slots, {})

    def test_missing_observed_utc_is_dropped_not_trusted(self):
        entry = self._entry(None)
        del entry["observed_utc"]
        lineup_index = {"g1": entry}
        commence = {"823090": "2026-09-09T22:10:00Z"}
        slots = probe._slots_for_date("2026-09-09", lineup_index, commence)
        self.assertEqual(slots, {})


class BoxRowForTests(unittest.TestCase):

    def test_finds_the_row_for_the_right_date_not_just_the_right_player(self):
        by_name = {"Test Batter": [
            _box("2026-09-04", h=0, total_bases=0, r=0),
            _box("2026-09-05", h=2, total_bases=3, r=1),
        ]}
        row = probe._box_row_for(by_name, "Test Batter", "2026-09-05")
        self.assertEqual(row["h"], 2)

    def test_unknown_player_returns_none(self):
        self.assertIsNone(probe._box_row_for({}, "Nobody", "2026-09-05"))

    def test_same_name_different_game_picks_the_team_that_was_actually_playing(self):
        # Regression for Opus checker finding #6: the box store holds two
        # different players named "Max Muncy" on the same date (this
        # project's real store: person_id 691777 and 571970, both with rows
        # on 2026-09-09). Pre-fix, `_box_row_for` returned whichever of the
        # two sat first in `by_name`'s list -- file order, not fact -- and
        # would silently grade a contract against the WRONG Muncy's stats
        # whenever that happened to be the other one. This test constructs
        # exactly that collision and asserts the team-matched row wins.
        wrong_team_first = _box("2026-09-09", h=0, total_bases=0, r=0)
        wrong_team_first["team_name"] = "Los Angeles Dodgers"
        right_team_second = _box("2026-09-09", h=3, total_bases=5, r=2)
        right_team_second["team_name"] = "Arizona Diamondbacks"
        by_name = {"Test Batter": [wrong_team_first, right_team_second]}
        row = probe._box_row_for(by_name, "Test Batter", "2026-09-09",
                                  home_team="Colorado Rockies",
                                  away_team="Arizona Diamondbacks")
        self.assertEqual(row["h"], 3)

    def test_no_row_matches_the_event_teams_returns_none_not_a_guess(self):
        # Same collision, but NEITHER stored row's team was in tonight's
        # game -- the join must void this contract rather than return the
        # first row it finds, which pre-fix it would have done.
        row_a = _box("2026-09-09", h=0, total_bases=0, r=0)
        row_a["team_name"] = "Los Angeles Dodgers"
        row_b = _box("2026-09-09", h=3, total_bases=5, r=2)
        row_b["team_name"] = "Oakland Athletics"
        by_name = {"Test Batter": [row_a, row_b]}
        result = probe._box_row_for(by_name, "Test Batter", "2026-09-09",
                                     home_team="Colorado Rockies",
                                     away_team="Arizona Diamondbacks")
        self.assertIsNone(result)


class BigGapQuestionTests(unittest.TestCase):
    """The owner's specific question, on a synthetic population where the
    right answer is known by construction: ours beats the market by 20
    points on every row, and the true hit rate is 50% -- so ours should be
    overconfident by 30 points and the market by 10.
    """

    def _records(self):
        records = []
        for i in range(25):
            y = 1 if i % 2 == 0 else 0
            records.append({"p_model": 0.8, "p_market": 0.6, "y": y,
                            "coors": False})
        return records

    def test_hit_rate_and_gaps_match_the_construction(self):
        result = probe.big_gap_question(self._records(), 0.10)
        self.assertEqual(result["n"], 25)
        self.assertAlmostEqual(result["actual_hit_rate"], 0.52, places=6)
        self.assertAlmostEqual(result["gap_vs_ours"], 0.28, places=6)
        self.assertAlmostEqual(result["gap_vs_market"], 0.08, places=6)

    def test_below_the_row_floor_refuses_rather_than_printing_a_thin_number(self):
        result = probe.big_gap_question(self._records()[:5], 0.10)
        self.assertIn("verdict", result)
        self.assertEqual(result["n"], 5)


class BootstrapDeterminismTests(unittest.TestCase):
    """Same seed, same data, same interval -- the pre-registered seed
    (20260914) is only meaningful if re-running the script reproduces the
    reported CI rather than re-rolling it."""

    def _records(self):
        records = []
        for d in range(6):
            date = f"2026-09-0{d + 1}"
            for i in range(15):
                y = 1 if (i + d) % 3 else 0
                records.append({"date": date, "p_model": 0.65,
                                "p_market": 0.55, "y": y})
        return records

    def test_two_runs_with_the_same_seed_agree(self):
        a = probe.bootstrap_brier_diff(self._records(), iterations=200)
        b = probe.bootstrap_brier_diff(self._records(), iterations=200)
        self.assertEqual(a, b)

    def test_point_estimate_is_the_unresampled_difference(self):
        result = probe.bootstrap_brier_diff(self._records(), iterations=50)
        pairs_our = [(r["p_model"], r["y"]) for r in self._records()]
        pairs_mkt = [(r["p_market"], r["y"]) for r in self._records()]
        expected = probe.brier_score(pairs_our) - probe.brier_score(pairs_mkt)
        self.assertAlmostEqual(result["point_estimate"], round(expected, 5),
                               places=5)


if __name__ == "__main__":
    unittest.main()
