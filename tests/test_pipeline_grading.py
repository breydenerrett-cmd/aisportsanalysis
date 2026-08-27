"""Tests for src/pipeline/grading.py.

What matters most: the log cannot be rewritten, a pending game is never counted as a
loss, a missing closing line is never substituted, and no verdict is drawn below the
pre-registered sample threshold no matter how flattering the numbers look.
"""

import json
import tempfile
import unittest
from pathlib import Path

from src.pipeline import grading


def prediction(pk=1, home_prob=0.60, away="MIL", home="NYM",
               away_price=-225, home_price=188, favours="home",
               day="2026-08-27"):
    return {
        "usable": True, "game_pk": pk, "date": day,
        "away_team": away, "home_team": home,
        "home_probability": home_prob,
        "away_price": away_price, "home_price": home_price,
        "market_home_fair": 0.334, "disagreement_home": home_prob - 0.334,
        "model_favours": favours, "comparable": True,
    }


def result_game(pk=1, home_won=1, day="2026-08-27"):
    return {"game_pk": pk, "date": day, "home_won": home_won,
            "away_team": "MIL", "home_team": "NYM", "winner": "NYM"}


def snapshot(observed, home_price=150, away_price=-180,
             away="Milwaukee Brewers", home="New York Mets",
             commence="2026-08-27T23:10:00Z"):
    return {
        "observed_utc": observed, "commence_time": commence,
        "away_team": away, "home_team": home, "market": "h2h",
        "book": "fanduel",
        "prices": {"home_price": home_price, "away_price": away_price},
    }


class TestLogging(unittest.TestCase):
    def test_appends_without_rewriting(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "log.jsonl"
            grading.log_predictions([prediction(1)], path)
            first = path.read_text()
            grading.log_predictions([prediction(2)], path)
            second = path.read_text()
        self.assertTrue(second.startswith(first))
        self.assertEqual(len(second.strip().splitlines()), 2)

    def test_records_the_price_at_prediction_time(self):
        # This price cannot be recovered once the market moves, so it must be
        # captured now or CLV is impossible later.
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "log.jsonl"
            grading.log_predictions([prediction(home_price=188)], path)
            entry = grading.read_log(path)[0]
        self.assertEqual(entry["home_price_at_prediction"], 188)
        self.assertEqual(entry["away_price_at_prediction"], -225)

    def test_unusable_predictions_are_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "log.jsonl"
            report = grading.log_predictions(
                [{**prediction(), "usable": False}], path)
        self.assertEqual(report["logged"], 0)
        self.assertEqual(report["skipped"], 1)

    def test_model_version_is_recorded(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "log.jsonl"
            grading.log_predictions([prediction()], path, model_version="v1")
            self.assertEqual(grading.read_log(path)[0]["model_version"], "v1")

    def test_truncated_line_costs_one_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "log.jsonl"
            grading.log_predictions([prediction(1), prediction(2)], path)
            with path.open("a") as handle:
                handle.write('{"game_pk": 3, "date": "2026-08')
            self.assertEqual(len(grading.read_log(path)), 2)

    def test_missing_log_reads_empty(self):
        self.assertEqual(grading.read_log("/nonexistent/log.jsonl"), [])


class TestDeduplication(unittest.TestCase):
    def test_keeps_the_first_prediction_for_a_game(self):
        # The first was made with the least information and the earliest price.
        # Keeping the last would let a prediction be improved after a market move.
        entries = [
            {"game_pk": 1, "model_version": "v1", "home_probability": 0.60},
            {"game_pk": 1, "model_version": "v1", "home_probability": 0.75},
        ]
        kept = grading.deduplicate(entries)
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0]["home_probability"], 0.60)

    def test_different_model_versions_are_kept_separately(self):
        entries = [
            {"game_pk": 1, "model_version": "v1"},
            {"game_pk": 1, "model_version": "v2"},
        ]
        self.assertEqual(len(grading.deduplicate(entries)), 2)


class TestSettlement(unittest.TestCase):
    def settle(self, entries, store, snaps=None):
        return grading.settle(entries, store, snapshot_rows=snaps)

    def test_a_correct_prediction_is_graded_correct(self):
        entries = [{"game_pk": 1, "home_probability": 0.60, "date": "2026-08-27",
                    "away_team": "MIL", "home_team": "NYM",
                    "model_favours": "home", "home_price_at_prediction": 188}]
        result = self.settle(entries, {"1": result_game(home_won=1)})
        self.assertEqual(result["counts"]["graded"], 1)
        self.assertTrue(result["graded"][0]["correct"])

    def test_an_incorrect_prediction_is_graded_incorrect(self):
        entries = [{"game_pk": 1, "home_probability": 0.60, "date": "2026-08-27",
                    "away_team": "MIL", "home_team": "NYM",
                    "model_favours": "home", "home_price_at_prediction": 188}]
        result = self.settle(entries, {"1": result_game(home_won=0)})
        self.assertFalse(result["graded"][0]["correct"])

    def test_a_game_not_in_the_store_is_pending_not_wrong(self):
        # Conflating "not finished" with "wrong" makes the record look worse or
        # better depending on when the report happened to run.
        entries = [{"game_pk": 99, "home_probability": 0.6}]
        result = self.settle(entries, {})
        self.assertEqual(result["counts"]["pending"], 1)
        self.assertEqual(result["counts"]["graded"], 0)

    def test_a_game_with_no_winner_is_unresolved(self):
        entries = [{"game_pk": 1, "home_probability": 0.6}]
        result = self.settle(entries, {"1": {**result_game(), "home_won": None}})
        self.assertEqual(result["counts"]["unresolved"], 1)

    def test_brier_is_computed(self):
        entries = [{"game_pk": 1, "home_probability": 0.75, "date": "2026-08-27",
                    "away_team": "MIL", "home_team": "NYM",
                    "model_favours": "home", "home_price_at_prediction": 188}]
        result = self.settle(entries, {"1": result_game(home_won=1)})
        self.assertAlmostEqual(result["graded"][0]["brier"], 0.0625, places=6)


class TestClosingLineValue(unittest.TestCase):
    def entry(self, price=188, favours="home"):
        return {"game_pk": 1, "home_probability": 0.60, "date": "2026-08-27",
                "away_team": "MIL", "home_team": "NYM",
                "model_favours": favours,
                "home_price_at_prediction": price,
                "away_price_at_prediction": -225}

    def test_no_snapshots_means_ungraded_not_substituted(self):
        # Substituting a stand-in price would corrupt the primary metric.
        result = grading.settle([self.entry()], {"1": result_game()})
        graded = result["graded"][0]
        self.assertFalse(graded["clv_graded"])
        self.assertIn("no odds snapshots", graded["clv_reason"])

    def test_a_snapshot_after_first_pitch_does_not_count_as_closing(self):
        snaps = [snapshot("2026-08-28T01:00:00+00:00")]
        result = grading.settle([self.entry()], {"1": result_game()}, snaps)
        graded = result["graded"][0]
        self.assertFalse(graded["clv_graded"])
        self.assertIn("before first pitch", graded["clv_reason"])

    def test_no_price_recorded_means_ungraded(self):
        entry = {**self.entry(), "home_price_at_prediction": None}
        result = grading.settle([entry], {"1": result_game()})
        self.assertIn("no price recorded", result["graded"][0]["clv_reason"])

    def test_clv_grades_when_a_closing_snapshot_exists(self):
        # The happy path, which the two bugs below both silently prevented.
        snaps = [snapshot("2026-08-27T12:00:00+00:00", home_price=150),
                 snapshot("2026-08-27T22:00:00+00:00", home_price=120)]
        result = grading.settle([self.entry(price=188)],
                                {"1": result_game()}, snaps)
        graded = result["graded"][0]
        self.assertTrue(graded["clv_graded"])
        self.assertEqual(graded["clv_closing_price"], 120)
        # Took +188, market closed +120: the number moved in, so the bet was ahead.
        self.assertTrue(graded["clv_beat_close"])

    def test_snapshots_are_matched_by_abbreviation_not_club_name(self):
        # BUG 1: snapshots store the odds feed's full club names while predictions
        # store abbreviations. Comparing them directly never matches, so CLV --
        # the primary validation metric -- would silently never grade at all.
        snaps = [snapshot("2026-08-27T22:00:00+00:00",
                          away="Milwaukee Brewers", home="New York Mets")]
        result = grading.settle([self.entry()], {"1": result_game()}, snaps)
        self.assertTrue(result["graded"][0]["clv_graded"])

    def test_a_west_coast_night_game_still_matches(self):
        # BUG 2: the odds feed timestamps in UTC, MLB assigns a local official
        # date. A game starting 01:45 UTC on the 28th has official date the 27th,
        # so keying snapshots by UTC date misses EVERY West Coast night game.
        snaps = [snapshot("2026-08-28T01:00:00+00:00",
                          away="Arizona Diamondbacks", home="San Francisco Giants",
                          commence="2026-08-28T01:45:00Z", home_price=120)]
        entry = {"game_pk": 1, "home_probability": 0.60,
                 "date": "2026-08-27",          # official date
                 "away_team": "AZ", "home_team": "SF",
                 "model_favours": "home", "home_price_at_prediction": 188}
        result = grading.settle([entry], {"1": result_game()}, snaps)
        self.assertTrue(result["graded"][0]["clv_graded"])

    def test_a_genuinely_different_date_does_not_match(self):
        # Tolerance is one day, not unlimited. A week-old snapshot must not be
        # attached, because a wrong closing price is worse than none.
        snaps = [snapshot("2026-08-20T22:00:00+00:00",
                          commence="2026-08-20T23:10:00Z")]
        result = grading.settle([self.entry()], {"1": result_game()}, snaps)
        self.assertFalse(result["graded"][0]["clv_graded"])

    def test_ungraded_reasons_are_counted_in_the_report(self):
        settled = grading.settle([self.entry()], {"1": result_game()})
        summary = grading.report(settled)
        self.assertEqual(summary["clv_ungraded"], 1)
        self.assertTrue(summary["clv_ungraded_reasons"])


class TestReportHonesty(unittest.TestCase):
    """No verdict below the pre-registered threshold, however good it looks."""

    @staticmethod
    def graded_entries(n, beat=True, edge=0.05):
        return {
            "graded": [{
                "correct": True, "brier": 0.2, "clv_graded": True,
                "clv_beat_close": beat, "clv_prob_edge": edge,
            } for _ in range(n)],
            "pending": [], "unresolved": [],
            "counts": {"graded": n, "pending": 0, "unresolved": 0},
        }

    def test_no_predictions_says_so_plainly(self):
        summary = grading.report({"graded": [], "pending": [], "unresolved": [],
                                  "counts": {}})
        self.assertEqual(summary["n"], 0)
        self.assertFalse(summary["can_conclude"])

    def test_a_tiny_sample_refuses_a_verdict_despite_perfect_numbers(self):
        # 10 for 10 beating the close is not evidence, and saying so is the point.
        summary = grading.report(self.graded_entries(10))
        self.assertFalse(summary["can_conclude"])
        self.assertFalse(summary["can_describe_trend"])
        self.assertIn("far too few", summary["verdict"])

    def test_a_hundred_allows_a_trend_but_not_a_verdict(self):
        summary = grading.report(self.graded_entries(100))
        self.assertTrue(summary["can_describe_trend"])
        self.assertFalse(summary["can_conclude"])
        self.assertIn("trend only", summary["verdict"])

    def test_the_threshold_sample_allows_a_verdict(self):
        summary = grading.report(
            self.graded_entries(grading.MIN_SAMPLE_FOR_ANY_VERDICT))
        self.assertTrue(summary["can_conclude"])
        self.assertIn("met", summary["verdict"])

    def test_a_failing_large_sample_reports_criteria_not_met(self):
        summary = grading.report(
            self.graded_entries(grading.MIN_SAMPLE_FOR_ANY_VERDICT,
                                beat=False, edge=-0.02))
        self.assertTrue(summary["can_conclude"])
        self.assertIn("NOT met", summary["verdict"])

    def test_thresholds_match_the_pre_registered_document(self):
        summary = grading.report(self.graded_entries(5))
        self.assertEqual(summary["thresholds"]["min_sample"], 300)
        self.assertEqual(summary["thresholds"]["beat_rate"], 0.55)

    def test_accuracy_is_reported_but_flagged_as_not_the_criterion(self):
        summary = grading.report(self.graded_entries(50))
        self.assertIsNotNone(summary["accuracy"])
        self.assertIn("NOT the", summary["note"])

    def test_clv_beat_rate_is_computed(self):
        summary = grading.report(self.graded_entries(20, beat=True))
        self.assertEqual(summary["clv_beat_rate"], 1.0)


if __name__ == "__main__":
    unittest.main()
