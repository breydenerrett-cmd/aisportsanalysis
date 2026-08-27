"""Tests for src/pipeline/pitchers.py and the innings-notation conversion.

Two things get the most attention: the same lookahead proof applied to pitcher logs,
and the baseball-specific trap that innings pitched are written in THIRDS.
"""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from src.pipeline import pitchers
from src.pipeline.pitchers import PitcherError
from src.providers import mlb
from src.providers.mlb import MLBError


def appearance(person, day, ip=6.0, er=2, k=6, bb=2, h=5, hr=1, bf=24,
               started=1, season="2025"):
    return {
        "person_id": int(person), "date": day, "season": season,
        "is_home": False, "games_started": started,
        "innings_pitched": ip, "earned_runs": er, "runs": er,
        "hits": h, "walks": bb, "strikeouts": k, "home_runs": hr,
        "batters_faced": bf, "pitches": 95,
    }


def log_for(person, days, **kwargs):
    return {str(person): [appearance(person, d, **kwargs) for d in days]}


MAY = [f"2025-05-{d:02d}" for d in (1, 6, 11, 16, 21, 26)]


class TestInningsNotation(unittest.TestCase):
    """Innings pitched are written in thirds. "5.1" is five and ONE THIRD.

    Reading it as a float understates ERA, WHIP, and K/9 by a few percent --
    consistently, invisibly, and in the flattering direction for rate stats.
    """

    def test_thirds_are_converted_correctly(self):
        self.assertAlmostEqual(mlb._innings_to_float("5.0"), 5.0)
        self.assertAlmostEqual(mlb._innings_to_float("5.1"), 5 + 1 / 3)
        self.assertAlmostEqual(mlb._innings_to_float("5.2"), 5 + 2 / 3)

    def test_a_naive_float_read_would_differ(self):
        # Pins the actual bug: float("5.2") is 5.2, the truth is 5.667.
        self.assertNotAlmostEqual(mlb._innings_to_float("5.2"), 5.2, places=2)

    def test_whole_innings_without_a_decimal(self):
        self.assertAlmostEqual(mlb._innings_to_float("7"), 7.0)

    def test_zero_innings(self):
        self.assertAlmostEqual(mlb._innings_to_float("0.0"), 0.0)

    def test_none_and_blank_are_none(self):
        self.assertIsNone(mlb._innings_to_float(None))
        self.assertIsNone(mlb._innings_to_float("   "))

    def test_an_impossible_fraction_raises_rather_than_guessing(self):
        # .3 does not exist in thirds notation. If it appears, our understanding
        # of the format is wrong and silently coercing it would skew every rate.
        with self.assertRaises(MLBError):
            mlb._innings_to_float("5.3")

    def test_unparseable_value_is_none(self):
        self.assertIsNone(mlb._innings_to_float("abc"))


class TestAppearancesBefore(unittest.TestCase):
    def test_excludes_the_cutoff_date(self):
        logs = log_for(1, ["2025-05-01", "2025-05-06"])
        self.assertEqual(len(pitchers.appearances_before(logs, 1, "2025-05-06")), 1)

    def test_excludes_future_appearances(self):
        logs = log_for(1, MAY)
        self.assertEqual(len(pitchers.appearances_before(logs, 1, "2025-05-12")), 3)

    def test_empty_markers_are_skipped(self):
        logs = {"1": [{"person_id": 1, "season": "2025", "date": None,
                       "empty": True}]}
        self.assertEqual(pitchers.appearances_before(logs, 1, "2025-06-01"), [])

    def test_unknown_pitcher_returns_empty(self):
        self.assertEqual(pitchers.appearances_before({}, 999, "2025-06-01"), [])

    def test_accepts_string_or_int_ids(self):
        logs = log_for(1, MAY)
        self.assertEqual(len(pitchers.appearances_before(logs, "1", "2025-06-01")),
                         len(pitchers.appearances_before(logs, 1, "2025-06-01")))


class TestNoLookahead(unittest.TestCase):
    """Same proof as team features: inject absurd future data, assert nothing moves."""

    def test_a_future_disaster_start_does_not_change_features(self):
        clean = log_for(1, MAY)
        poisoned = {"1": clean["1"] + [
            appearance(1, "2025-06-01", ip=0.1, er=12, k=0, bb=8, h=14, hr=5),
            appearance(1, "2025-09-01", ip=0.1, er=15, k=0, bb=9, h=16, hr=6),
        ]}
        self.assertEqual(
            pitchers.pitcher_features(clean, 1, "2025-05-28", fip_constant=3.1),
            pitchers.pitcher_features(poisoned, 1, "2025-05-28", fip_constant=3.1),
        )

    def test_an_appearance_on_the_cutoff_date_does_not_leak(self):
        clean = log_for(1, MAY)
        same_day = {"1": clean["1"] + [
            appearance(1, "2025-05-28", ip=0.1, er=20, k=0, bb=9, h=18, hr=7)]}
        self.assertEqual(
            pitchers.pitcher_features(clean, 1, "2025-05-28", fip_constant=3.1),
            pitchers.pitcher_features(same_day, 1, "2025-05-28", fip_constant=3.1),
        )

    def test_matchup_features_are_leak_free(self):
        clean = {**log_for(1, MAY), **log_for(2, MAY)}
        poisoned = {"1": clean["1"] + [appearance(1, "2025-06-01", er=20)],
                    "2": clean["2"]}
        self.assertEqual(
            pitchers.matchup_pitcher_features(clean, 1, 2, "2025-05-28",
                                              fip_constant=3.1),
            pitchers.matchup_pitcher_features(poisoned, 1, 2, "2025-05-28",
                                              fip_constant=3.1),
        )

    def test_league_constant_ignores_the_future(self):
        clean = log_for(1, MAY)
        poisoned = {"1": clean["1"] + [appearance(1, "2025-06-01", ip=200, er=900)]}
        self.assertEqual(
            pitchers.league_fip_constant(clean, "2025-05-28"),
            pitchers.league_fip_constant(poisoned, "2025-05-28"),
        )


class TestRateComputation(unittest.TestCase):
    def features(self, days=MAY, cutoff="2025-06-01", **kwargs):
        return pitchers.pitcher_features(log_for(1, days, **kwargs), 1, cutoff,
                                         fip_constant=3.1)

    def test_era_matches_hand_computation(self):
        # 6 starts, 6 IP each = 36 IP; 2 ER each = 12 ER. ERA = 12*9/36 = 3.00
        self.assertAlmostEqual(self.features()["sp_era"], 3.0)

    def test_whip_matches_hand_computation(self):
        # (5 hits + 2 walks) * 6 = 42 over 36 IP = 1.1667
        self.assertAlmostEqual(self.features()["sp_whip"], 42 / 36, places=4)

    def test_k9_matches_hand_computation(self):
        # 36 strikeouts over 36 IP = 9.00
        self.assertAlmostEqual(self.features()["sp_k9"], 9.0)

    def test_k_bb_pct_matches_hand_computation(self):
        # (36 K - 12 BB) / 144 batters faced = 0.1667
        self.assertAlmostEqual(self.features()["sp_k_bb_pct"], 24 / 144, places=4)

    def test_ip_per_start(self):
        self.assertAlmostEqual(self.features()["sp_ip_per_start"], 6.0)

    def test_fip_is_computed_and_is_not_labelled_xfip(self):
        result = self.features()
        self.assertIsNotNone(result["sp_fip"])
        # xFIP needs fly-ball data this feed lacks. Nothing may claim to be xFIP.
        self.assertFalse(any("xfip" in k.lower() for k in result))

    def test_fip_formula_matches_hand_computation(self):
        # (13*6 HR + 3*12 BB - 2*36 K) / 36 IP + 3.1
        expected = ((13 * 6) + (3 * 12) - (2 * 36)) / 36 + 3.1
        self.assertAlmostEqual(self.features()["sp_fip"], round(expected, 4), places=3)

    def test_a_strikeout_pitcher_has_a_better_fip(self):
        power = self.features(k=12, bb=1, hr=0)["sp_fip"]
        contact = self.features(k=3, bb=4, hr=2)["sp_fip"]
        self.assertLess(power, contact)


class TestThinSamples(unittest.TestCase):
    def test_rates_are_suppressed_below_the_innings_threshold(self):
        # Two starts is not a rate. A 1.50 ERA over 9 innings is two good outings.
        result = pitchers.pitcher_features(log_for(1, MAY[:2]), 1, "2025-06-01",
                                           fip_constant=3.1)
        self.assertTrue(result["sp_thin"])
        self.assertIsNone(result["sp_era"])
        self.assertIsNone(result["sp_fip"])
        # The count is still reported, so the caller knows why.
        self.assertEqual(result["sp_appearances"], 2)

    def test_rates_appear_once_the_threshold_is_met(self):
        result = pitchers.pitcher_features(log_for(1, MAY), 1, "2025-06-01",
                                           fip_constant=3.1)
        self.assertFalse(result["sp_thin"])
        self.assertIsNotNone(result["sp_era"])

    def test_unknown_pitcher_reports_not_known(self):
        result = pitchers.pitcher_features({}, 999, "2025-06-01", fip_constant=3.1)
        self.assertFalse(result["sp_known"])
        self.assertEqual(result["sp_appearances"], 0)
        self.assertIsNone(result["sp_era"])

    def test_none_pitcher_id_is_handled(self):
        result = pitchers.pitcher_features({}, None, "2025-06-01", fip_constant=3.1)
        self.assertFalse(result["sp_known"])


class TestRecentFormAndRest(unittest.TestCase):
    def test_recent_era_uses_only_the_last_three_starts(self):
        days = MAY[:3] + MAY[3:]
        logs = {"1": [appearance(1, d, er=0) for d in MAY[:3]]
                     + [appearance(1, d, er=6) for d in MAY[3:]]}
        result = pitchers.pitcher_features(logs, 1, "2025-06-01", fip_constant=3.1)
        # Last three starts allowed 6 ER each over 6 IP: 6*9/6 = 9.00
        self.assertAlmostEqual(result["sp_recent_era"], 9.0)
        # Season ERA is the blend and must be lower.
        self.assertLess(result["sp_era"], result["sp_recent_era"])

    def test_recent_form_is_none_with_too_few_starts(self):
        result = pitchers.pitcher_features(log_for(1, MAY[:2]), 1, "2025-06-01",
                                           fip_constant=3.1)
        self.assertIsNone(result["sp_recent_era"])
        self.assertEqual(result["sp_recent_starts"], 2)

    def test_days_rest_is_measured_from_the_last_appearance(self):
        result = pitchers.pitcher_features(log_for(1, ["2025-05-26"]), 1,
                                           "2025-05-31", fip_constant=3.1)
        self.assertEqual(result["sp_days_rest"], 5)

    def test_days_rest_is_capped(self):
        result = pitchers.pitcher_features(log_for(1, ["2025-05-01"]), 1,
                                           "2025-09-01", fip_constant=3.1)
        self.assertEqual(result["sp_days_rest"], 14)

    def test_relief_appearances_do_not_count_as_recent_starts(self):
        logs = {"1": [appearance(1, d, started=0) for d in MAY]}
        result = pitchers.pitcher_features(logs, 1, "2025-06-01", fip_constant=3.1)
        self.assertEqual(result["sp_recent_starts"], 0)


class TestLeagueFipConstant(unittest.TestCase):
    def test_falls_back_to_the_default_on_thin_history(self):
        self.assertEqual(pitchers.league_fip_constant(log_for(1, MAY), "2025-06-01"),
                         pitchers.DEFAULT_FIP_CONSTANT)

    def test_is_derived_once_enough_innings_exist(self):
        logs = {str(p): [appearance(p, f"2025-05-{d:02d}") for d in range(1, 20)]
                for p in range(1, 10)}
        constant = pitchers.league_fip_constant(logs, "2025-06-01")
        self.assertNotEqual(constant, pitchers.DEFAULT_FIP_CONSTANT)


class TestMatchupFeatures(unittest.TestCase):
    def test_both_starters_are_present(self):
        logs = {**log_for(1, MAY), **log_for(2, MAY)}
        result = pitchers.matchup_pitcher_features(logs, 1, 2, "2025-06-01",
                                                   fip_constant=3.1)
        self.assertIn("away_sp_era", result)
        self.assertIn("home_sp_era", result)

    def test_differential_is_home_minus_away(self):
        logs = {**log_for(1, MAY, er=1), **log_for(2, MAY, er=5)}
        result = pitchers.matchup_pitcher_features(logs, 1, 2, "2025-06-01",
                                                   fip_constant=3.1)
        # Home starter is worse, so home-minus-away ERA is positive.
        self.assertGreater(result["diff_sp_era"], 0)

    def test_differential_is_none_when_a_starter_is_unknown(self):
        result = pitchers.matchup_pitcher_features(log_for(1, MAY), 1, 999,
                                                   "2025-06-01", fip_constant=3.1)
        self.assertIsNone(result["diff_sp_era"])
        self.assertFalse(result["both_sp_known"])


class TestLogStore(unittest.TestCase):
    def test_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "logs.jsonl"
            pitchers.write_logs(log_for(1, MAY), path)
            self.assertEqual(len(pitchers.read_logs(path)["1"]), len(MAY))

    def test_missing_file_reads_empty(self):
        self.assertEqual(pitchers.read_logs("/nonexistent/logs.jsonl"), {})

    def test_truncated_line_costs_one_appearance(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "logs.jsonl"
            pitchers.write_logs(log_for(1, MAY), path)
            with path.open("a") as handle:
                handle.write('{"person_id":1,"date":"2025-06')
            self.assertEqual(len(pitchers.read_logs(path)["1"]), len(MAY))

    def test_resume_skips_cached_pitchers(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "logs.jsonl"
            pitchers.write_logs(log_for(1, MAY), path)
            with mock.patch.object(mlb, "fetch_pitcher_game_log",
                                   return_value=[]) as fake:
                report = pitchers.build_log_store(["1"], 2025, path, resume=True)
        fake.assert_not_called()
        self.assertEqual(report["skipped_cached"], 1)

    def test_a_pitcher_with_no_appearances_is_cached_as_empty(self):
        # Otherwise an injured pitcher is re-fetched forever, indistinguishable
        # from one never attempted.
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "logs.jsonl"
            with mock.patch.object(mlb, "fetch_pitcher_game_log", return_value=[]):
                pitchers.build_log_store(["7"], 2025, path, resume=False)
            with mock.patch.object(mlb, "fetch_pitcher_game_log",
                                   return_value=[]) as fake:
                pitchers.build_log_store(["7"], 2025, path, resume=True)
        fake.assert_not_called()

    def test_a_failing_pitcher_does_not_abort_the_run(self):
        def side_effect(person, season, timeout=20):
            if str(person) == "2":
                raise MLBError("HTTP 500")
            return [appearance(person, "2025-05-01")]

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "logs.jsonl"
            with mock.patch.object(mlb, "fetch_pitcher_game_log",
                                   side_effect=side_effect):
                report = pitchers.build_log_store(["1", "2", "3"], 2025, path,
                                                  resume=False)
        self.assertEqual(report["processed"], 2)
        self.assertEqual(report["failed"], 1)

    def test_probable_pitcher_ids_collects_both_sides(self):
        store = {
            "1": {"away_probable_id": "10", "home_probable_id": "20"},
            "2": {"away_probable_id": "10", "home_probable_id": None},
        }
        self.assertEqual(pitchers.probable_pitcher_ids(store), {"10", "20"})


class TestValidation(unittest.TestCase):
    def test_bad_cutoff_date_rejected(self):
        with self.assertRaises(PitcherError):
            pitchers.appearances_before(log_for(1, MAY), 1, "not-a-date")

    def test_non_string_date_rejected(self):
        with self.assertRaises(PitcherError):
            pitchers.appearances_before(log_for(1, MAY), 1, 20250601)


if __name__ == "__main__":
    unittest.main()
