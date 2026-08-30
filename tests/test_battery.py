"""Tests for the automated falsification battery.

Every fatal rule gets a synthetic row set built to trip it and nothing else
where possible, plus one set built to survive the whole battery. The clustering
test is the one that guards the statistics: a correlated-date construction must
come out with a wider p than the naive per-row computation would give.
"""

import datetime as dt
import unittest

from src.model import discovery
from src.research import battery


def _dates(start, count):
    return [(start + dt.timedelta(days=i)).isoformat() for i in range(count)]


def _survivor_rows():
    """240 rows, hit 75% at implied 0.5, spread evenly across seasons, sides,
    teams, books and doses so no concentration or split can kill it."""
    rows = []
    idx = 0
    for year in (2023, 2024):
        for date in _dates(dt.date(year, 4, 1), 40):
            for _ in range(3):
                rows.append({
                    "date": date,
                    "won": idx % 4 != 3,
                    "implied": 0.5,
                    "season": year,
                    "side": "home" if idx % 2 == 0 else "away",
                    "team": f"T{idx % 6}",
                    "book": f"B{idx % 5}",
                    "price": -110,
                    "dose": 0.02 + 0.002 * (idx % 8),
                })
                idx += 1
    return rows


def _correlated_rows():
    """Eight dates, 25 identical rows each: five all-win, three all-loss.

    Naively this is n=200 and a tiny p; clustered it is eight draws and the
    effect is nowhere near significant. The gap is the whole point."""
    rows = []
    for i, date in enumerate(_dates(dt.date(2024, 6, 1), 8)):
        for _ in range(25):
            rows.append({"date": date, "won": i < 5, "implied": 0.5})
    return rows


def _carried_rows(key, carrier, others):
    """One slice wins everything; four balanced slices carry nothing."""
    rows = []
    dates = _dates(dt.date(2024, 5, 1), 80)
    for i in range(40):
        rows.append({"date": dates[i], "won": True, "implied": 0.5,
                     key: carrier})
    for j, name in enumerate(others):
        for i in range(10):
            rows.append({"date": dates[40 + j * 10 + i], "won": i % 2 == 0,
                         "implied": 0.5, key: name})
    return rows


def _dose_rows(band_specs):
    """band_specs: (dose, wins, losses) per intended band, one row per date."""
    rows = []
    dates = iter(_dates(dt.date(2024, 8, 1), 200))
    for dose, wins, losses in band_specs:
        for i in range(wins + losses):
            rows.append({"date": next(dates), "won": i < wins,
                         "implied": 0.5, "dose": dose})
    return rows


class BaselineTests(unittest.TestCase):
    def test_effect_is_mean_won_minus_implied(self):
        result = battery.run(_correlated_rows())
        # 125 wins and 75 losses at implied 0.5: (125 - 75) * 0.5 / 200.
        self.assertAlmostEqual(result["report"]["baseline"]["effect"], 0.125)

    def test_below_the_sample_floor_everything_skips(self):
        rows = [{"date": d, "won": i % 2 == 0, "implied": 0.5}
                for i, d in enumerate(_dates(dt.date(2024, 6, 1), 10))]
        result = battery.run(rows)
        self.assertIn("skipped", result["report"]["baseline"])
        self.assertEqual(result["fatal"], [])
        for check in result["report"].values():
            self.assertIn("skipped", check)

    def test_caller_rows_are_never_mutated(self):
        rows = _correlated_rows()
        keys_before = set(rows[0])
        battery.run(rows)
        self.assertEqual(set(rows[0]), keys_before)
        self.assertNotIn("_diff", rows[0])

    def test_a_row_missing_a_required_key_raises(self):
        rows = [{"date": "2024-06-01", "won": True}] * 40
        with self.assertRaises(battery.BatteryError):
            battery.run(rows)


class ClusteringTests(unittest.TestCase):
    def test_correlated_dates_widen_p_versus_the_naive_computation(self):
        rows = _correlated_rows()
        clustered_p = battery.run(rows)["report"]["baseline"]["p"]
        diffs = [(1.0 if r["won"] else 0.0) - r["implied"] for r in rows]
        naive_p = discovery.two_sided_p(sum(diffs) / len(diffs), diffs)
        self.assertLess(naive_p, 0.01)      # naively this looks like a result
        self.assertGreater(clustered_p, 0.1)  # clustered, it is eight coin flips
        self.assertGreater(clustered_p, naive_p)


class FatalRuleTests(unittest.TestCase):
    def test_opposite_season_signs_are_fatal(self):
        rows = []
        for date in _dates(dt.date(2023, 5, 1), 40):
            rows.append({"date": date, "won": False, "implied": 0.5,
                         "season": 2023})
        for date in _dates(dt.date(2024, 5, 1), 40):
            rows.append({"date": date, "won": True, "implied": 0.5,
                         "season": 2024})
        result = battery.run(rows)
        self.assertIn("season_split", result["fatal"])
        self.assertFalse(result["survives"])
        seasons = result["report"]["season_split"]["seasons"]
        self.assertLess(seasons["2023"]["effect"], 0)
        self.assertGreater(seasons["2024"]["effect"], 0)

    def test_one_team_carrying_the_effect_is_fatal(self):
        rows = _carried_rows("team", "NYY", ("BAL", "BOS", "TB", "TOR"))
        result = battery.run(rows)
        self.assertEqual(result["fatal"], ["team_concentration"])
        self.assertEqual(
            result["report"]["team_concentration"]["killed_by"], ["NYY"])

    def test_one_book_carrying_the_effect_is_fatal(self):
        rows = _carried_rows("book", "fanduel", ("circa", "dk", "mgm", "rivers"))
        result = battery.run(rows)
        self.assertEqual(result["fatal"], ["book_concentration"])
        self.assertEqual(
            result["report"]["book_concentration"]["killed_by"], ["fanduel"])

    def test_a_few_extreme_dates_carrying_the_effect_is_fatal(self):
        # Three 10-win slates on top of 57 mildly losing single-row dates:
        # positive overall, negative once the three slates are removed.
        rows = []
        dates = _dates(dt.date(2024, 7, 1), 60)
        for date in dates[:3]:
            for _ in range(10):
                rows.append({"date": date, "won": True, "implied": 0.5})
        for i, date in enumerate(dates[3:]):
            rows.append({"date": date, "won": i < 26, "implied": 0.5})
        result = battery.run(rows)
        self.assertGreater(result["report"]["baseline"]["effect"], 0)
        self.assertEqual(result["fatal"], ["extreme_removal"])
        self.assertLess(result["report"]["extreme_removal"]["effect"], 0)

    def test_the_m3_dose_signature_is_fatal(self):
        # Flat below the threshold, a spike just above it, fading on top --
        # the exact shape that killed M3.
        rows = _dose_rows([(0.010, 20, 20), (0.021, 32, 8), (0.027, 22, 18)])
        result = battery.run(rows, dose_key="dose",
                             dose_bands=[0.0, 0.02, 0.025, 0.03])
        self.assertEqual(result["fatal"], ["dose_response"])
        self.assertIn("M3 signature", result["report"]["dose_response"]["note"])

    def test_a_rising_dose_response_is_not_fatal(self):
        # Same bands, but the effect grows with the dose: a real mechanism's
        # shape, so the battery must let it live.
        rows = _dose_rows([(0.010, 20, 20), (0.021, 28, 12), (0.027, 36, 4)])
        result = battery.run(rows, dose_key="dose",
                             dose_bands=[0.0, 0.02, 0.025, 0.03])
        self.assertNotIn("dose_response", result["fatal"])
        self.assertTrue(result["survives"])


class SkipBehaviourTests(unittest.TestCase):
    def test_checks_skip_when_their_key_is_absent(self):
        rows = [{"date": d, "won": i % 2 == 0, "implied": 0.5}
                for i, d in enumerate(_dates(dt.date(2024, 6, 1), 40))]
        report = battery.run(rows, dose_key="dose")["report"]
        for name in ("season_split", "home_away", "team_concentration",
                     "book_concentration", "dose_response",
                     "threshold_sensitivity"):
            self.assertIn("skipped", report[name], name)
        # implied is required, so these always run.
        self.assertNotIn("skipped", report["favorite_underdog"])
        self.assertNotIn("skipped", report["price_bands"])

    def test_dose_checks_skip_without_a_dose_key(self):
        report = battery.run(_correlated_rows())["report"]
        self.assertIn("skipped", report["dose_response"])
        self.assertIn("skipped", report["threshold_sensitivity"])


class SurvivorTests(unittest.TestCase):
    def test_a_clean_candidate_survives_the_whole_battery(self):
        result = battery.run(_survivor_rows(), dose_key="dose")
        self.assertEqual(result["fatal"], [])
        self.assertTrue(result["survives"])
        report = result["report"]
        for name in report:
            self.assertNotIn("skipped", report[name], name)
        self.assertGreater(report["baseline"]["effect"], 0.2)
        self.assertLess(report["baseline"]["p"], 0.01)

    def test_threshold_sensitivity_reports_both_scales(self):
        report = battery.run(_survivor_rows(), dose_key="dose")["report"]
        scaled = report["threshold_sensitivity"]["scaled"]
        self.assertEqual(set(scaled), {"0.8x", "1.25x"})
        # No rows sit below the current threshold, so 0.8x matches baseline.
        self.assertEqual(scaled["0.8x"]["n"], report["baseline"]["n"])
        self.assertLess(scaled["1.25x"]["n"], report["baseline"]["n"])


if __name__ == "__main__":
    unittest.main()
