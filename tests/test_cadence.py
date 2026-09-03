"""Tests for src/capture/cadence.py. Hermetic: every store is a tempfile
fixture, never data/processed/odds_multibook.jsonl, data/watch/*, or
data/processed/weather_forecast.jsonl."""

import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path

from src.capture import cadence

NOW = dt.datetime(2026, 9, 3, 12, 0, tzinfo=dt.timezone.utc)


def _write_jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")


class GradeFromGapTests(unittest.TestCase):
    def test_twenty_minutes_or_less_is_b(self):
        self.assertEqual(cadence.grade_from_gap(0), "B")
        self.assertEqual(cadence.grade_from_gap(20 * 60), "B")

    def test_just_over_twenty_minutes_is_c(self):
        self.assertEqual(cadence.grade_from_gap(20 * 60 + 1), "C")

    def test_two_hours_or_less_is_c(self):
        self.assertEqual(cadence.grade_from_gap(2 * 60 * 60), "C")

    def test_over_two_hours_is_d(self):
        self.assertEqual(cadence.grade_from_gap(2 * 60 * 60 + 1), "D")

    def test_a_six_hour_hole_is_d_never_a_silent_b(self):
        # F10's exact scenario: a schedule that claims 15-minute cadence but
        # actually left a six-hour hole must grade D on that gap, not
        # inherit the schedule's asserted grade.
        self.assertEqual(cadence.grade_from_gap(6 * 60 * 60), "D")

    def test_none_or_negative_is_refused(self):
        with self.assertRaises(ValueError):
            cadence.grade_from_gap(None)
        with self.assertRaises(ValueError):
            cadence.grade_from_gap(-1)


class SourceCadenceTests(unittest.TestCase):
    def test_evenly_spaced_polls_grade_b(self):
        timestamps = [
            "2026-09-03T10:00:00Z", "2026-09-03T10:15:00Z",
            "2026-09-03T10:30:00Z", "2026-09-03T10:45:00Z",
        ]
        result = cadence.source_cadence("2026-09-03", timestamps)
        self.assertEqual(result["attempted"], 4)
        self.assertEqual(result["succeeded"], 4)
        self.assertEqual(result["longest_gap_seconds"], 900)
        self.assertEqual(result["grade"], "B")

    def test_a_single_timestamp_has_no_gap_and_no_grade(self):
        result = cadence.source_cadence("2026-09-03", ["2026-09-03T10:00:00Z"])
        self.assertEqual(result["attempted"], 1)
        self.assertIsNone(result["longest_gap_seconds"])
        self.assertIsNone(result["grade"])

    def test_no_timestamps_is_zero_attempted(self):
        result = cadence.source_cadence("2026-09-03", [])
        self.assertEqual(result["attempted"], 0)
        self.assertIsNone(result["grade"])

    def test_a_hole_in_the_middle_grades_on_the_longest_gap(self):
        timestamps = [
            "2026-09-03T10:00:00Z", "2026-09-03T10:15:00Z",
            # six-hour hole here
            "2026-09-03T16:20:00Z",
        ]
        result = cadence.source_cadence("2026-09-03", timestamps)
        self.assertEqual(result["grade"], "D")
        self.assertGreater(result["longest_gap_seconds"], 2 * 60 * 60)


class ComputeAndWriteTests(unittest.TestCase):
    def test_compute_reads_each_configured_source_on_its_own_field(self):
        with tempfile.TemporaryDirectory() as folder:
            multibook = Path(folder) / "odds_multibook.jsonl"
            lineups = Path(folder) / "lineups_watch.jsonl"
            umpires = Path(folder) / "umpires_watch.jsonl"
            weather = Path(folder) / "weather_forecast.jsonl"

            _write_jsonl(multibook, [
                {"observed_utc": "2026-09-03T10:00:00Z"},
                {"observed_utc": "2026-09-03T10:15:00Z"},
            ])
            _write_jsonl(lineups, [
                {"poll": True, "fetched_utc": "2026-09-03T10:00:00Z"},
                {"fetched_utc": "2026-09-03T10:05:00Z"},  # not a poll marker
                {"poll": True, "fetched_utc": "2026-09-03T10:20:00Z"},
            ])
            _write_jsonl(umpires, [
                {"poll": True, "observed_utc": "2026-09-03T09:00:00Z"},
            ])
            _write_jsonl(weather, [
                {"observed_utc": "2026-09-03T08:00:00Z"},
                {"observed_utc": "2026-09-02T08:00:00Z"},  # different date
            ])

            sources = {
                "odds_multibook": {"path": multibook, "field": "observed_utc",
                                    "poll_only": False},
                "rosterwatch_lineups": {"path": lineups, "field": "fetched_utc",
                                         "poll_only": True},
                "umpirewatch": {"path": umpires, "field": "observed_utc",
                                 "poll_only": True},
                "weather_forecast": {"path": weather, "field": "observed_utc",
                                      "poll_only": False},
            }
            result = cadence.compute("2026-09-03", sources=sources, now=NOW)

        self.assertEqual(result["sources"]["odds_multibook"]["attempted"], 2)
        # Only the two poll:true rows count, not the plain data row.
        self.assertEqual(result["sources"]["rosterwatch_lineups"]["attempted"], 2)
        self.assertEqual(result["sources"]["umpirewatch"]["attempted"], 1)
        # Only the 09-03 row counts, not the 09-02 one.
        self.assertEqual(result["sources"]["weather_forecast"]["attempted"], 1)

    def test_write_appends_one_row_per_source_and_never_rewrites(self):
        with tempfile.TemporaryDirectory() as folder:
            multibook = Path(folder) / "odds_multibook.jsonl"
            _write_jsonl(multibook, [{"observed_utc": "2026-09-03T10:00:00Z"}])
            empty = Path(folder) / "empty.jsonl"
            sources = {
                "odds_multibook": {"path": multibook, "field": "observed_utc",
                                    "poll_only": False},
                "rosterwatch_lineups": {"path": empty, "field": "fetched_utc",
                                         "poll_only": True},
                "umpirewatch": {"path": empty, "field": "observed_utc",
                                 "poll_only": True},
                "weather_forecast": {"path": empty, "field": "observed_utc",
                                      "poll_only": False},
            }
            store = Path(folder) / "cadence_slo.jsonl"

            first = cadence.write("2026-09-03", sources=sources, now=NOW, store=store)
            second = cadence.write("2026-09-03", sources=sources, now=NOW, store=store)

            rows = cadence.read(store=store)

        self.assertEqual(first["written"], 4)
        self.assertEqual(second["written"], 4)
        # Both calls appended -- nothing was rewritten in place.
        self.assertEqual(len(rows), 8)

    def test_an_interrupted_append_does_not_corrupt_the_next_write(self):
        with tempfile.TemporaryDirectory() as folder:
            empty = Path(folder) / "empty.jsonl"
            sources = {
                "odds_multibook": {"path": empty, "field": "observed_utc",
                                    "poll_only": False},
                "rosterwatch_lineups": {"path": empty, "field": "fetched_utc",
                                         "poll_only": True},
                "umpirewatch": {"path": empty, "field": "observed_utc",
                                 "poll_only": True},
                "weather_forecast": {"path": empty, "field": "observed_utc",
                                      "poll_only": False},
            }
            store = Path(folder) / "cadence_slo.jsonl"
            cadence.write("2026-09-03", sources=sources, now=NOW, store=store)
            # Simulate a killed append: no trailing newline.
            with store.open("a", encoding="utf-8") as handle:
                handle.write('{"ragged": true')
            cadence.write("2026-09-04", sources=sources, now=NOW, store=store)
            rows = cadence.read(store=store)
        # The ragged fragment is skipped, not merged into the next row.
        self.assertTrue(all(isinstance(r, dict) for r in rows))
        self.assertIn("2026-09-04", [r.get("date") for r in rows])


if __name__ == "__main__":
    unittest.main()
