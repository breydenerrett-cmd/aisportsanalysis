"""Per-value sample counts: what tonight's own feature number rests on.

WHY THIS MATTERS AND WHAT IT IS NOT
-------------------------------------
Before this, a published thesis could quote the THRESHOLD's derivation
sample ("4,048 games with both sides measured") and nothing else. That
number describes the rung. It says nothing about whether this lineup's 0.331
wOBA against that starter's primary pitch is 214 plate appearances or 11 --
two very different claims that read identically.

The counts threaded here are counts of observations strictly before the SAME
cutoff the value itself was accumulated under (`src.pipeline.rebuilt`), so
they are exactly as point-in-time-safe as the value: no new store is opened,
no new cutoff is chosen, nothing about an outcome is read. And a primitive
with no count to report emits NO count -- absence, never a zero a reader
could quote as if it meant "none".
"""

from __future__ import annotations

import unittest

from src.engine import features as F
from src.engine import mechanism_predicates as mp
from src.engine.explain import evolab_thesis
from src.engine.snapshot import PriceBlindSnapshot
from src.research import matrix as matrix_module

PITCHER = "500"
BATTERS = [str(600 + i) for i in range(9)]


def _acc():
    """A minimal `rebuilt.accumulate`-shaped dict that clears every floor.

    Built by hand rather than accumulated from fixture pitches so the counts
    the assertions below name are visible in one place."""
    return {
        "pitcher_vs": {
            (PITCHER, "L"): {"value": 96.0, "denom": 300, "bf": 320},
            (PITCHER, "R"): {"value": 90.0, "denom": 300, "bf": 410},
        },
        "arsenal": {PITCHER: {
            "FF": {"pitches": 1200, "whiffs": 100, "swings": 400,
                   "value": 30.0, "denom": 100},
            "SL": {"pitches": 800, "whiffs": 90, "swings": 300,
                   "value": 20.0, "denom": 80},
        }},
        "fastball_velocity": {PITCHER: {
            (f"2026-05-0{i}", 1000 + i): {"count": 40, "sum": 40 * 95.0}
            for i in range(1, 6)}},
        "league_fastball": {"count": 1000, "sum": 1000 * 93.0},
        "batted_balls": {PITCHER: {"ground_balls": 120, "batted": 300}},
        "batter_vs_pitch": {
            (batter, "FF"): {"value": 0.320 * (20 + index), "denom": 20 + index}
            for index, batter in enumerate(BATTERS)
        },
    }


def _slots():
    return [{"order": i + 1, "person_id": b} for i, b in enumerate(BATTERS)]


class TestSamplesComeOutOfTheSameAccumulation(unittest.TestCase):

    def setUp(self):
        acc = _acc()
        self.values, self.samples = F._starter_features_for_side(
            acc, matrix_module._batter_totals(acc), _slots(), PITCHER)

    def test_every_emitted_value_carries_a_count(self):
        self.assertTrue(self.values)
        for name in self.values:
            with self.subTest(feature=name):
                self.assertIn(name, self.samples)
                self.assertGreater(self.samples[name], 0)

    def test_the_counts_are_the_primitives_own(self):
        # 320 left-handed + 410 right-handed batters faced.
        self.assertEqual(self.samples["starter_platoon_gap"], 730)
        # 5 appearances x 40 measured fastballs.
        self.assertEqual(self.samples["starter_velocity_gap"], 200)
        self.assertEqual(self.samples["starter_groundball_share"], 300)
        # The SHARE's denominator is the whole arsenal, not the primary
        # pitch's own count.
        self.assertEqual(self.samples["primary_pitch_share"], 2000)
        # Nine hitters, 20..28 plate appearances each against FF.
        self.assertEqual(self.samples["lineup_vs_primary_pitch"],
                          sum(20 + i for i in range(9)))

    def test_a_difference_reports_the_thinner_half(self):
        """`top_minus_bottom` rests on both halves of the order, so the
        honest count is the SMALLER: summing would let four thin slots hide
        behind five thick ones."""
        top = sum(20 + i for i in range(4))
        bottom = sum(20 + i for i in range(4, 9))
        self.assertEqual(self.samples["top_minus_bottom"], min(top, bottom))

    def test_a_feature_that_misses_its_floor_emits_neither_value_nor_count(self):
        acc = _acc()
        acc["batted_balls"][PITCHER] = {"ground_balls": 4, "batted": 10}
        values, samples = F._starter_features_for_side(
            acc, matrix_module._batter_totals(acc), _slots(), PITCHER)
        self.assertNotIn("starter_groundball_share", values)
        self.assertNotIn("starter_groundball_share", samples)


class TestTheCountReachesTheReader(unittest.TestCase):

    SAMPLES = {"away_lineup_vs_primary_pitch": {"n": 214,
                                                 "unit": "plate appearances"},
               "home_lineup_vs_primary_pitch": {"n": 189,
                                                 "unit": "plate appearances"}}

    def test_the_thesis_states_what_this_games_values_rest_on(self):
        thesis = evolab_thesis(
            "genome1", "h2h", "away", (("lineup_vs_primary_pitch", 1),),
            {"away_lineup_vs_primary_pitch": 0.331,
             "home_lineup_vs_primary_pitch": 0.272},
            samples=self.SAMPLES)
        self.assertIn("away over 214 plate appearances", thesis)
        self.assertIn("home over 189 plate appearances", thesis)
        # And it still quotes the ladder's own derivation sample, which is a
        # different fact about a different thing.
        self.assertIn("4,048 games", thesis)

    def test_no_count_means_no_sentence_never_a_zero(self):
        thesis = evolab_thesis(
            "genome1", "h2h", "away", (("lineup_vs_primary_pitch", 1),),
            {"away_lineup_vs_primary_pitch": 0.331,
             "home_lineup_vs_primary_pitch": 0.272})
        self.assertNotIn("rest on", thesis)
        self.assertNotIn("over 0 ", thesis)

    def test_the_frozen_predicate_carries_the_counts_too(self):
        row = mp.predicates_for((("lineup_vs_primary_pitch", 0),), "away",
                                {"away_lineup_vs_primary_pitch": 0.331},
                                samples=self.SAMPLES)[0]
        self.assertEqual(row["away_sample"]["n"], 214)
        self.assertEqual(row["home_sample"]["n"], 189)

    def test_a_snapshot_without_counts_still_builds(self):
        snap = PriceBlindSnapshot(game_pk="1", t="2026-09-02T16:00:00+00:00",
                                  point_class="LATE_BOARD", features={})
        self.assertEqual(dict(snap.feature_samples), {})


if __name__ == "__main__":
    unittest.main()
