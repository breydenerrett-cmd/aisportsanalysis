"""Tests for src/pipeline/snapshots.py.

The behaviours that matter: append-only storage never mutates, a missing closing line stays
missing rather than being substituted, and CLV arithmetic is right in both directions.
"""

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from src.pipeline import snapshots
from src.pipeline.snapshots import SnapshotError
from src.providers import odds as odds_provider

FAKE_KEY = "sk-not-real"


def observation(observed, home_price=-130, away_price=110,
                commence="2026-08-27T23:05:00Z", market="h2h",
                away="Houston Astros", home="New York Yankees"):
    return {
        "observed_utc": observed,
        "event_id": "e1",
        "commence_time": commence,
        "away_team": away,
        "home_team": home,
        "market": market,
        "book": "fanduel",
        "prices": {"home_price": home_price, "away_price": away_price},
        "book_last_update": observed,
    }


class TestAppendOnly(unittest.TestCase):
    def test_append_writes_one_line_per_observation(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "snaps.jsonl"
            snapshots.append([observation("2026-08-27T12:00:00+00:00"),
                              observation("2026-08-27T16:00:00+00:00")], path)
            lines = path.read_text().strip().splitlines()
        self.assertEqual(len(lines), 2)
        self.assertEqual(json.loads(lines[0])["observed_utc"], "2026-08-27T12:00:00+00:00")

    def test_second_append_adds_without_rewriting(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "snaps.jsonl"
            snapshots.append([observation("2026-08-27T12:00:00+00:00")], path)
            first = path.read_text()
            snapshots.append([observation("2026-08-27T16:00:00+00:00")], path)
            second = path.read_text()
        # The original content must still be a prefix -- nothing was rewritten.
        self.assertTrue(second.startswith(first))
        self.assertEqual(len(second.strip().splitlines()), 2)

    def test_empty_append_writes_nothing_and_creates_no_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "snaps.jsonl"
            self.assertEqual(snapshots.append([], path), 0)
            self.assertFalse(path.exists())

    def test_creates_parent_directories(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "deep" / "nested" / "snaps.jsonl"
            snapshots.append([observation("2026-08-27T12:00:00+00:00")], path)
            self.assertTrue(path.exists())

    def test_round_trip_preserves_prices(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "snaps.jsonl"
            snapshots.append([observation("2026-08-27T12:00:00+00:00", home_price=-175)], path)
            back = snapshots.read(path)
        self.assertEqual(back[0]["prices"]["home_price"], -175)


class TestReadResilience(unittest.TestCase):
    def test_missing_file_returns_empty_not_an_error(self):
        self.assertEqual(snapshots.read("/nonexistent/snaps.jsonl"), [])

    def test_truncated_final_line_costs_one_observation_not_the_file(self):
        # The signature of a run killed mid-write.
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "snaps.jsonl"
            snapshots.append([observation("2026-08-27T12:00:00+00:00"),
                              observation("2026-08-27T16:00:00+00:00")], path)
            with path.open("a") as handle:
                handle.write('{"observed_utc":"2026-08-27T20:00')  # truncated
            rows = snapshots.read(path)
        self.assertEqual(len(rows), 2)

    def test_corrupt_line_can_be_made_fatal_when_asked(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "snaps.jsonl"
            snapshots.append([observation("2026-08-27T12:00:00+00:00")], path)
            with path.open("a") as handle:
                handle.write("{not json}\n")
            with self.assertRaises(SnapshotError):
                snapshots.read(path, skip_corrupt=False)

    def test_blank_lines_are_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "snaps.jsonl"
            snapshots.append([observation("2026-08-27T12:00:00+00:00")], path)
            with path.open("a") as handle:
                handle.write("\n\n")
            self.assertEqual(len(snapshots.read(path)), 1)


class TestGrouping(unittest.TestCase):
    def test_groups_by_game_and_sorts_oldest_first(self):
        rows = [
            observation("2026-08-27T20:00:00+00:00"),
            observation("2026-08-27T12:00:00+00:00"),
            observation("2026-08-27T16:00:00+00:00"),
        ]
        grouped = snapshots.group_by_game(rows)
        self.assertEqual(len(grouped), 1)
        series = list(grouped.values())[0]
        self.assertEqual([r["observed_utc"] for r in series],
                         ["2026-08-27T12:00:00+00:00",
                          "2026-08-27T16:00:00+00:00",
                          "2026-08-27T20:00:00+00:00"])

    def test_separates_distinct_games(self):
        rows = [
            observation("2026-08-27T12:00:00+00:00", away="Houston Astros",
                        home="New York Yankees"),
            observation("2026-08-27T12:00:00+00:00", away="Colorado Rockies",
                        home="Washington Nationals"),
        ]
        self.assertEqual(len(snapshots.group_by_game(rows)), 2)

    def test_filters_to_the_requested_market(self):
        rows = [
            observation("2026-08-27T12:00:00+00:00", market="h2h"),
            observation("2026-08-27T12:00:00+00:00", market="totals"),
        ]
        self.assertEqual(len(snapshots.group_by_game(rows, market="h2h")), 1)
        self.assertEqual(len(snapshots.group_by_game(rows, market="totals")), 1)
        self.assertEqual(len(snapshots.group_by_game(rows, market="spreads")), 0)

    def test_same_teams_on_different_days_are_different_games(self):
        rows = [
            observation("2026-08-27T12:00:00+00:00", commence="2026-08-27T23:05:00Z"),
            observation("2026-08-28T12:00:00+00:00", commence="2026-08-28T23:05:00Z"),
        ]
        self.assertEqual(len(snapshots.group_by_game(rows)), 2)


class TestClosingObservation(unittest.TestCase):
    START = "2026-08-27T23:05:00Z"

    def test_picks_the_last_observation_before_first_pitch(self):
        series = [
            observation("2026-08-27T12:00:00+00:00", home_price=-130),
            observation("2026-08-27T22:00:00+00:00", home_price=-145),
            observation("2026-08-27T22:55:00+00:00", home_price=-150),
        ]
        closing = snapshots.closing_observation(series)
        self.assertEqual(closing["prices"]["home_price"], -150)

    def test_ignores_observations_taken_after_first_pitch(self):
        # In-play pricing is a different product and is not a closing line.
        series = [
            observation("2026-08-27T22:55:00+00:00", home_price=-150),
            observation("2026-08-27T23:30:00+00:00", home_price=-400),
        ]
        closing = snapshots.closing_observation(series)
        self.assertEqual(closing["prices"]["home_price"], -150)

    def test_no_observation_before_start_returns_none_not_a_substitute(self):
        # This is the important one. A job that started mid-season has no closing line for
        # earlier games, and quietly using the nearest available price would corrupt CLV.
        series = [observation("2026-08-27T23:30:00+00:00", home_price=-400)]
        self.assertIsNone(snapshots.closing_observation(series))

    def test_empty_series_returns_none(self):
        self.assertIsNone(snapshots.closing_observation([]))

    def test_missing_commence_time_returns_none(self):
        series = [observation("2026-08-27T12:00:00+00:00", commence=None)]
        self.assertIsNone(snapshots.closing_observation(series))


class TestMovement(unittest.TestCase):
    def test_reports_opening_closing_and_drift(self):
        series = [
            observation("2026-08-27T12:00:00+00:00", home_price=-130),
            observation("2026-08-27T22:00:00+00:00", home_price=-150),
        ]
        result = snapshots.movement(series)
        self.assertEqual(result["opening"], -130)
        self.assertEqual(result["closing"], -150)
        self.assertEqual(result["moved"], -20)
        self.assertEqual(result["observations"], 2)

    def test_direction_toward_when_price_shortens(self):
        series = [
            observation("2026-08-27T12:00:00+00:00", home_price=-130),
            observation("2026-08-27T22:00:00+00:00", home_price=-160),
        ]
        self.assertEqual(snapshots.movement(series)["direction"], "toward")

    def test_direction_away_when_price_lengthens(self):
        series = [
            observation("2026-08-27T12:00:00+00:00", home_price=-160),
            observation("2026-08-27T22:00:00+00:00", home_price=-130),
        ]
        self.assertEqual(snapshots.movement(series)["direction"], "away")

    def test_flat_when_unchanged(self):
        series = [
            observation("2026-08-27T12:00:00+00:00", home_price=-130),
            observation("2026-08-27T22:00:00+00:00", home_price=-130),
        ]
        result = snapshots.movement(series)
        self.assertEqual(result["direction"], "flat")
        self.assertEqual(result["moved"], 0)

    def test_implied_probability_shift_is_reported(self):
        series = [
            observation("2026-08-27T12:00:00+00:00", home_price=-100),
            observation("2026-08-27T22:00:00+00:00", home_price=-300),
        ]
        result = snapshots.movement(series)
        # -100 is 0.50, -300 is 0.75, so the shift is +0.25.
        self.assertAlmostEqual(result["implied_prob_shift"], 0.25, places=5)

    def test_observation_count_is_surfaced(self):
        # A move seen across 2 samples is weaker evidence than across 20.
        series = [observation(f"2026-08-27T{h:02d}:00:00+00:00", home_price=-130 - h)
                  for h in range(10, 22)]
        self.assertEqual(snapshots.movement(series)["observations"], 12)

    def test_empty_series_reports_zero_observations(self):
        result = snapshots.movement([])
        self.assertEqual(result["observations"], 0)
        self.assertIsNone(result["opening"])

    def test_can_track_the_away_side(self):
        series = [
            observation("2026-08-27T12:00:00+00:00", away_price=110),
            observation("2026-08-27T22:00:00+00:00", away_price=135),
        ]
        result = snapshots.movement(series, side="away_price")
        self.assertEqual(result["opening"], 110)
        self.assertEqual(result["closing"], 135)


class TestClosingLineValue(unittest.TestCase):
    def test_beating_the_close_is_positive(self):
        # Took +150, market closed at +120: the price got worse, so the bet was ahead of it.
        result = snapshots.closing_line_value(150, 120)
        self.assertTrue(result["beat_close"])
        self.assertGreater(result["prob_edge"], 0)

    def test_losing_to_the_close_is_negative(self):
        # Took +120, market closed at +150: the number moved against the bet.
        result = snapshots.closing_line_value(120, 150)
        self.assertFalse(result["beat_close"])
        self.assertLess(result["prob_edge"], 0)

    def test_identical_prices_do_not_beat_the_close(self):
        result = snapshots.closing_line_value(-130, -130)
        self.assertFalse(result["beat_close"])
        self.assertAlmostEqual(result["prob_edge"], 0.0, places=9)

    def test_works_on_favorites(self):
        # Took -130, closed -160: the bet was in at the better number.
        result = snapshots.closing_line_value(-130, -160)
        self.assertTrue(result["beat_close"])

    def test_prob_edge_is_comparable_across_favorites_and_dogs(self):
        # Both moves are 0.50 -> 0.60 in implied terms and must score identically.
        fav = snapshots.closing_line_value(100, -150)
        self.assertAlmostEqual(fav["prob_edge"], 0.10, places=6)


class TestCapture(unittest.TestCase):
    def test_no_key_writes_nothing_and_reports_why(self):
        # Safe to schedule before setup is finished.
        result = snapshots.capture(env={}, path="/tmp/should-not-exist.jsonl")
        self.assertEqual(result["captured"], 0)
        self.assertFalse(result["configured"])
        self.assertIn("ODDS_API_KEY", result["message"])
        self.assertFalse(Path("/tmp/should-not-exist.jsonl").exists())

    def test_captures_one_row_per_market_per_event(self):
        payload = {
            "event_count": 1,
            "events": [{
                "event_id": "e1", "commence_time": "2026-08-27T23:05:00Z",
                "away_team": "Houston Astros", "home_team": "New York Yankees",
                "markets": {
                    "h2h": {"book": "fanduel", "away_price": 136, "home_price": -162},
                    "totals": {"book": "fanduel", "total": 8.0,
                               "over_price": -122, "under_price": 100},
                },
            }],
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "snaps.jsonl"
            with mock.patch.object(odds_provider, "fetch_normalized",
                                   return_value=payload):
                result = snapshots.capture(env={"ODDS_API_KEY": FAKE_KEY}, path=path)
            rows = snapshots.read(path)
        self.assertEqual(result["captured"], 2)
        self.assertEqual({r["market"] for r in rows}, {"h2h", "totals"})

    def test_provider_failure_writes_nothing_and_reports(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "snaps.jsonl"
            with mock.patch.object(
                odds_provider, "fetch_normalized",
                side_effect=odds_provider.OddsProviderError("quota exhausted"),
            ):
                result = snapshots.capture(env={"ODDS_API_KEY": FAKE_KEY}, path=path)
            self.assertFalse(path.exists())
        self.assertEqual(result["captured"], 0)
        self.assertIn("quota", result["error"])

    def test_every_row_carries_the_capture_timestamp(self):
        payload = {"event_count": 1, "events": [{
            "event_id": "e1", "commence_time": "2026-08-27T23:05:00Z",
            "away_team": "A", "home_team": "B",
            "markets": {"h2h": {"book": "fanduel", "away_price": 110, "home_price": -130}},
        }]}
        fixed = datetime(2026, 8, 27, 18, 30, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "snaps.jsonl"
            with mock.patch.object(odds_provider, "fetch_normalized",
                                   return_value=payload):
                snapshots.capture(env={"ODDS_API_KEY": FAKE_KEY}, path=path, now=fixed)
            rows = snapshots.read(path)
        self.assertTrue(rows[0]["observed_utc"].startswith("2026-08-27T18:30"))


class TestCoverage(unittest.TestCase):
    def test_empty_history_reports_zeros(self):
        report = snapshots.coverage([])
        self.assertEqual(report["observations"], 0)
        self.assertEqual(report["closing_rate"], 0.0)

    def test_reports_how_many_games_have_a_closing_line(self):
        rows = [
            observation("2026-08-27T12:00:00+00:00", away="A", home="B"),
            observation("2026-08-27T22:00:00+00:00", away="A", home="B"),
            # This game only observed AFTER first pitch -- no closing line.
            observation("2026-08-27T23:30:00+00:00", away="C", home="D"),
        ]
        report = snapshots.coverage(rows)
        self.assertEqual(report["games"], 2)
        self.assertEqual(report["with_closing"], 1)
        self.assertAlmostEqual(report["closing_rate"], 0.5)

    def test_reports_the_observation_window(self):
        rows = [
            observation("2026-08-27T12:00:00+00:00"),
            observation("2026-08-27T22:00:00+00:00"),
        ]
        report = snapshots.coverage(rows)
        self.assertEqual(report["first_utc"], "2026-08-27T12:00:00+00:00")
        self.assertEqual(report["last_utc"], "2026-08-27T22:00:00+00:00")


class TestCrashMidWrite(unittest.TestCase):
    """A run killed mid-write must cost one observation, not two."""

    def test_the_capture_after_a_killed_run_is_not_eaten_by_its_fragment(self):
        # The store ends with the half-written line a SIGKILL left behind. The
        # next scheduled capture appends a perfectly good observation -- one
        # that can never be taken again -- and it used to be welded onto the
        # fragment and skipped by read() along with it: one crash, two losses.
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "snaps.jsonl"
            snapshots.append([observation("2026-08-27T12:00:00+00:00")], path)
            with path.open("a", encoding="utf-8") as handle:
                handle.write('{"observed_utc":"2026-08-27T12:15:00+00:00","pri')

            snapshots.append([observation("2026-08-27T12:30:00+00:00")], path)

            recovered = [r["observed_utc"] for r in snapshots.read(path)]
        self.assertEqual(recovered, ["2026-08-27T12:00:00+00:00",
                                     "2026-08-27T12:30:00+00:00"])

    def test_the_fragment_itself_is_still_the_only_thing_lost(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "snaps.jsonl"
            path.write_text('{"observed_utc":"a","mar', encoding="utf-8")
            snapshots.append([observation("2026-08-27T12:30:00+00:00")], path)
            self.assertEqual(len(snapshots.read(path)), 1)
            with self.assertRaises(SnapshotError):
                snapshots.read(path, skip_corrupt=False)


class TestOfficialDateIdentity(unittest.TestCase):
    """A game is identified by MLB's date, not by the UTC date of first pitch."""

    # Saturday night in the Bronx: 20:10 ET on the 30th is 00:10 UTC on the 31st.
    SATURDAY = "2026-08-31T00:10:00Z"
    # The Sunday matinee of the same series, same two teams.
    SUNDAY = "2026-08-31T17:35:00Z"

    def _series(self):
        return [
            observation("2026-08-30T22:00:00Z", commence=self.SATURDAY,
                        home_price=-130),
            observation("2026-08-31T00:00:00Z", commence=self.SATURDAY,
                        home_price=-140),
            observation("2026-08-31T16:00:00Z", commence=self.SUNDAY,
                        home_price=115),
            observation("2026-08-31T17:30:00Z", commence=self.SUNDAY,
                        home_price=120),
        ]

    def test_a_night_game_and_the_next_days_matinee_are_two_games(self):
        # Keyed by UTC date these shared one bucket -- and every three-game
        # series contains that pair.
        grouped = snapshots.group_by_game(self._series())
        self.assertEqual(len(grouped), 2)
        self.assertEqual(
            snapshots.game_key("Houston Astros", "New York Yankees",
                               self.SATURDAY)[2], "2026-08-30")

    def test_each_of_the_two_gets_its_own_closing_line(self):
        grouped = snapshots.group_by_game(self._series())
        closes = sorted(
            snapshots.closing_observation(s)["prices"]["home_price"]
            for s in grouped.values())
        self.assertEqual(closes, [-140, 120])

    def test_an_unsnapshotted_game_is_never_handed_last_nights_close(self):
        # The one that mattered. Sunday was never captured; asking for its
        # close returned SATURDAY's price, which cli._settlement_closing would
        # then write onto Sunday's settlement row as evidence.
        saturday_only = self._series()[:2]
        grouped = snapshots.group_by_game(saturday_only)
        key = snapshots.game_key("Houston Astros", "New York Yankees",
                                 self.SUNDAY)
        self.assertNotIn(key, grouped)

    def test_coverage_counts_both_games_and_both_closes(self):
        report = snapshots.coverage(self._series())
        self.assertEqual(report["games"], 2)
        self.assertEqual(report["with_closing"], 2)

    def test_a_bare_date_or_an_unparseable_start_is_left_alone(self):
        self.assertEqual(snapshots.official_date("2026-08-30"), "2026-08-30")
        self.assertEqual(snapshots.official_date("not a timestamp"), "not a time")
        self.assertEqual(snapshots.official_date(None), "")


if __name__ == "__main__":
    unittest.main()
