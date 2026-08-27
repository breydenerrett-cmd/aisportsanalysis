"""Tests for src/pipeline/scanlog.py.

The centrepiece is TestPushHandling. Every book offers the first-five moneyline
two-way, so a tie refunds -- which means the de-vigged price is P(win | no push).
Scoring pushes as losses, or keeping them in the denominator, compares a conditional
prediction against an unconditional outcome and biases the measured edge downward by
about the push rate. That rate is 15.9%, which is more than large enough to turn a
real effect into no effect and send the thresholds back to the drawing board for
nothing.

TestReportRefusesToOverclaim matters nearly as much: flags arrive at roughly one a
day, so the tempting failure is announcing a verdict on forty games.
"""

import json
import tempfile
import unittest
from pathlib import Path

from src.pipeline import scanlog


def flag(game_pk=1, side="home", implied=0.60, market="first_five_totals"):
    return {
        "game_pk": game_pk, "date": "2026-08-27", "away_team": "MIL",
        "home_team": "NYM", "side": side, "market": market,
        "signals": {
            "market": {"away_price": 150, "home_price": -170,
                       "detail": {"side_fair_prob": implied,
                                  "conditional_on_no_push": True}},
            "starters": {"reason": "clear starter edge", "magnitude": 1.8},
            "roster": {"reason": "clear roster edge", "magnitude": 1.2},
        },
    }


def final(away5, home5, complete=True, state="final", reason=None):
    return {
        "state": state,
        "first_five": {
            "complete": complete,
            "away_runs": away5 if complete else None,
            "home_runs": home5 if complete else None,
            "total_runs": (away5 + home5) if complete else None,
            "winner": (None if not complete or away5 == home5
                       else ("home" if home5 > away5 else "away")),
            "reason": reason,
        },
    }


class TestLogging(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = Path(self.dir.name) / "flags.jsonl"

    def tearDown(self):
        self.dir.cleanup()

    def test_only_flagged_games_are_logged(self):
        result = scanlog.log_flags(
            {"flagged": [flag(1)], "candidates": [flag(2)], "scans": []},
            path=self.path)
        self.assertEqual(result["logged"], 1)
        self.assertEqual(scanlog.read_log(self.path)[0]["game_pk"], 1)

    def test_a_candidate_is_never_logged(self):
        # A candidate could not be priced, so it can never resolve. Logging it would
        # pad the sample with entries that permanently sit in "unresolved".
        scanlog.log_flags({"flagged": [], "candidates": [flag(2)]}, path=self.path)
        self.assertEqual(scanlog.read_log(self.path), [])

    def test_the_price_at_flag_time_is_recorded(self):
        scanlog.log_flags({"flagged": [flag(1, implied=0.61)]}, path=self.path)
        entry = scanlog.read_log(self.path)[0]
        self.assertEqual(entry["implied_side_prob"], 0.61)
        self.assertEqual(entry["home_price"], -170)
        self.assertTrue(entry["conditional_on_no_push"])

    def test_the_log_is_append_only(self):
        scanlog.log_flags({"flagged": [flag(1)]}, path=self.path)
        scanlog.log_flags({"flagged": [flag(2)]}, path=self.path)
        self.assertEqual(len(scanlog.read_log(self.path)), 2)

    def test_a_missing_log_is_empty_not_an_error(self):
        self.assertEqual(scanlog.read_log(Path(self.dir.name) / "nope.jsonl"), [])

    def test_corrupt_lines_are_named_not_skipped(self):
        self.path.write_text('{"game_pk": 1}\nnot json\n', encoding="utf-8")
        with self.assertRaises(scanlog.ScanLogError) as ctx:
            scanlog.read_log(self.path)
        self.assertIn(":2", str(ctx.exception))

    def test_deduplicate_keeps_the_earliest_flag(self):
        # A later re-scan carries a price recorded closer to first pitch, which is
        # better for reasons that have nothing to do with the scanner.
        entries = [
            {"game_pk": 1, "side": "home", "market": "f5", "implied_side_prob": 0.60},
            {"game_pk": 1, "side": "home", "market": "f5", "implied_side_prob": 0.64},
        ]
        kept = scanlog.deduplicate(entries)
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0]["implied_side_prob"], 0.60)


class TestSettlement(unittest.TestCase):

    def entries(self, *flags):
        return [scanlog._entry(f, "2026-08-27T12:00:00+00:00") for f in flags]

    def test_the_flagged_side_leading_through_five_is_a_win(self):
        settled = scanlog.settle(self.entries(flag(1, side="home")),
                                 {1: final(1, 4)})
        self.assertEqual(settled["settled"][0]["outcome"], scanlog.WON)

    def test_the_flagged_side_trailing_through_five_is_a_loss(self):
        settled = scanlog.settle(self.entries(flag(1, side="home")),
                                 {1: final(4, 1)})
        self.assertEqual(settled["settled"][0]["outcome"], scanlog.LOST)

    def test_the_full_game_result_is_irrelevant(self):
        # 2-4 through five and 10-9 the other way at the end is a real game
        # (CIN @ SF, 26 Aug 2026). Grading on the final score would invert it.
        game = final(2, 4)
        game.update({"away_score": 10, "home_score": 9, "winner": "away"})
        settled = scanlog.settle(self.entries(flag(1, side="home")), {1: game})
        self.assertEqual(settled["settled"][0]["outcome"], scanlog.WON)

    def test_an_unfinished_game_is_unresolved_not_lost(self):
        settled = scanlog.settle(self.entries(flag(1)),
                                 {1: final(0, 0, state="in_progress")})
        self.assertEqual(settled["settled"][0]["outcome"], scanlog.UNRESOLVED)

    def test_a_game_missing_from_results_is_unresolved(self):
        settled = scanlog.settle(self.entries(flag(1)), {})
        self.assertEqual(settled["settled"][0]["outcome"], scanlog.UNRESOLVED)

    def test_a_shortened_game_is_void_not_lost(self):
        settled = scanlog.settle(
            self.entries(flag(1, side="home")),
            {1: final(0, 0, complete=False, reason="rain in the fifth")})
        self.assertEqual(settled["settled"][0]["outcome"], scanlog.VOID)


class TestPushHandling(unittest.TestCase):
    """A tie through five refunds, and must leave the sample entirely.

    The de-vigged two-way price is P(win | no push). Comparing it against a hit rate
    that includes pushes in the denominator subtracts two different quantities and
    understates the scanner by roughly the push rate -- 15.9%, which is enough on its
    own to turn a real effect into no effect.
    """

    def entries(self, *flags):
        return [scanlog._entry(f, "2026-08-27T12:00:00+00:00") for f in flags]

    def test_a_tie_through_five_is_a_push(self):
        settled = scanlog.settle(self.entries(flag(1)), {1: final(2, 2)})
        self.assertEqual(settled["settled"][0]["outcome"], scanlog.PUSHED)

    def test_a_push_is_not_in_the_decided_sample(self):
        entries = self.entries(flag(1, implied=0.60), flag(2, implied=0.60))
        settled = scanlog.settle(entries, {1: final(1, 4), 2: final(2, 2)})
        result = scanlog.report(settled)
        self.assertEqual(result["decided"], 1)
        self.assertEqual(result["counts"][scanlog.PUSHED], 1)

    def test_pushes_do_not_depress_the_hit_rate(self):
        # Two wins and eight pushes is a 100% hit rate, not 20%. Getting this wrong
        # is the single largest available source of false pessimism.
        flags = [flag(i, implied=0.60) for i in range(10)]
        results = {0: final(0, 3), 1: final(0, 3)}
        results.update({i: final(1, 1) for i in range(2, 10)})
        result = scanlog.report(scanlog.settle(self.entries(*flags), results))
        self.assertEqual(result["decided"], 2)
        self.assertEqual(result["hit_rate"], 1.0)

    def test_voids_are_excluded_on_the_same_principle(self):
        flags = [flag(1, implied=0.60), flag(2, implied=0.60)]
        results = {1: final(0, 3), 2: final(0, 0, complete=False, reason="rain")}
        result = scanlog.report(scanlog.settle(self.entries(*flags), results))
        self.assertEqual(result["decided"], 1)
        self.assertEqual(result["counts"][scanlog.VOID], 1)


class TestReportMeasuresEdgeNotHitRate(unittest.TestCase):
    """A hit rate alone says only that favourites win more often than underdogs."""

    def entries(self, *flags):
        return [scanlog._entry(f, "2026-08-27T12:00:00+00:00") for f in flags]

    def build(self, n, wins, implied):
        flags = [flag(i, implied=implied) for i in range(n)]
        results = {i: (final(0, 3) if i < wins else final(3, 0)) for i in range(n)}
        return scanlog.report(scanlog.settle(self.entries(*flags), results))

    def test_edge_is_hit_rate_minus_the_price(self):
        result = self.build(250, 175, 0.60)
        self.assertEqual(result["hit_rate"], 0.7)
        self.assertEqual(result["mean_implied"], 0.6)
        self.assertAlmostEqual(result["edge"], 0.10, places=4)

    def test_a_high_hit_rate_that_only_matches_the_price_is_not_an_edge(self):
        # 70% winners looks superb and is worth nothing if the price said 70%.
        result = self.build(250, 175, 0.70)
        self.assertEqual(result["hit_rate"], 0.7)
        self.assertEqual(result["edge"], 0.0)
        self.assertEqual(result["verdict"], "does not beat the price")

    def test_beating_the_price_is_not_reported_as_profit(self):
        result = self.build(250, 175, 0.60)
        self.assertEqual(result["verdict"], "beats the price")
        self.assertIn("NOT evidence of profitability", result["verdict_detail"])

    def test_failing_says_the_thresholds_must_not_be_retuned_here(self):
        result = self.build(250, 150, 0.60)
        self.assertEqual(result["verdict"], "does not beat the price")
        self.assertIn("description of it", result["verdict_detail"])


class TestReportRefusesToOverclaim(unittest.TestCase):
    """At about one flag a day, the tempting failure is a verdict on forty games."""

    def entries(self, *flags):
        return [scanlog._entry(f, "2026-08-27T12:00:00+00:00") for f in flags]

    def build(self, n, wins, implied=0.60):
        flags = [flag(i, implied=implied) for i in range(n)]
        results = {i: (final(0, 3) if i < wins else final(3, 0)) for i in range(n)}
        return scanlog.report(scanlog.settle(self.entries(*flags), results))

    def test_an_empty_log_reports_no_verdict(self):
        result = scanlog.report(scanlog.settle([], {}))
        self.assertEqual(result["verdict"], "insufficient sample")
        self.assertIsNone(result["hit_rate"])

    def test_a_perfect_small_sample_is_still_not_a_trend(self):
        result = self.build(20, 20)
        self.assertEqual(result["hit_rate"], 1.0)
        self.assertEqual(result["verdict"], "insufficient sample")
        self.assertIn("what a coin looks like", result["verdict_detail"])

    def test_a_medium_sample_leans_without_calling_it(self):
        result = self.build(120, 90)
        self.assertEqual(result["verdict"], "leaning")
        self.assertIn("Not a verdict", result["verdict_detail"])

    def test_a_verdict_needs_the_pre_registered_sample(self):
        self.assertEqual(self.build(199, 160)["verdict"], "leaning")
        self.assertEqual(self.build(200, 160)["verdict"], "beats the price")

    def test_a_small_edge_over_a_large_sample_does_not_pass(self):
        # 2 points of edge on 250 games is inside the noise a 250-game sample
        # carries, and the margin is pre-registered above it at 3.
        result = self.build(250, 155, 0.60)
        self.assertLess(result["edge"], scanlog.EDGE_PASS_MARGIN)
        self.assertEqual(result["verdict"], "does not beat the price")

    def test_thresholds_are_pre_registered(self):
        self.assertEqual(scanlog.MIN_FLAGS_FOR_VERDICT, 200)
        self.assertEqual(scanlog.MIN_FLAGS_FOR_TREND, 50)
        self.assertEqual(scanlog.EDGE_PASS_MARGIN, 0.03)


if __name__ == "__main__":
    unittest.main()
