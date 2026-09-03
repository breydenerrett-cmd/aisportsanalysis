"""Tests for the raw (L0) odds-payload capture layer.

WHY THIS EXISTS
---------------
`normalize_event` is a projection: it picks outcome shapes it recognizes and
drops everything else. Before this layer, the only copy of a provider
response was the in-memory dict handed to that projection -- a projection bug
was a permanent hole, because nothing kept what the provider actually said.

This proves three properties:

1. The verbatim payload lands on disk, gzip-readable, from the featured and
   the per-event fetch paths.
2. It lands BEFORE the projection runs -- proven by making the projection
   raise and asserting the raw file exists anyway.
3. It costs no extra API call: one `_get_json`/`_get_json_with_usage` call
   still produces exactly one raw file.
"""

from __future__ import annotations

import gzip
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from src.providers import odds as odds_provider

FAKE_KEY = "sk-not-real"


def _event(event_id="evt1"):
    return {
        "id": event_id,
        "commence_time": "2026-08-30T23:05:00Z",
        "home_team": "New York Yankees",
        "away_team": "Houston Astros",
        "bookmakers": [{
            "key": "fanduel", "last_update": "2026-08-30T14:58:00Z",
            "markets": [
                {"key": "h2h", "outcomes": [
                    {"name": "New York Yankees", "price": -162},
                    {"name": "Houston Astros", "price": 136},
                ]},
            ],
        }],
    }


class TestRawCaptureWritesVerbatimPayload(unittest.TestCase):
    def test_featured_fetch_writes_a_readable_gzip_file_with_the_payload(self):
        events = [_event()]
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(odds_provider, "raw_path",
                                   side_effect=lambda *p: Path(tmp).joinpath(*p)), \
                 mock.patch.object(odds_provider, "fetch_odds", return_value=events):
                result = odds_provider.fetch_normalized(
                    env={"ODDS_API_KEY": FAKE_KEY})
            self.assertEqual(result["event_count"], 1)
            files = list(Path(tmp).glob("oddsapi/**/*.jsonl.gz"))
            self.assertEqual(len(files), 1)
            with gzip.open(files[0], "rt", encoding="utf-8") as handle:
                record = json.loads(handle.readline())
        self.assertEqual(record["kind"], "featured")
        self.assertEqual(record["payload"], events)

    def test_event_fetch_writes_a_readable_gzip_file_with_the_payload(self):
        payload = {"id": "evt1", "bookmakers": [_event()["bookmakers"][0]]}
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(odds_provider, "raw_path",
                                   side_effect=lambda *p: Path(tmp).joinpath(*p)), \
                 mock.patch.object(odds_provider, "_get_json", return_value=payload):
                out = odds_provider.fetch_event_odds(
                    "evt1", markets=("h2h_1st_5_innings",),
                    env={"ODDS_API_KEY": FAKE_KEY})
            self.assertEqual(out, payload)
            files = list(Path(tmp).glob("oddsapi/**/*.jsonl.gz"))
            self.assertEqual(len(files), 1)
            with gzip.open(files[0], "rt", encoding="utf-8") as handle:
                record = json.loads(handle.readline())
        self.assertEqual(record["kind"], "event")
        self.assertEqual(record["payload"], payload)

    def test_raw_file_exists_even_when_projection_then_raises(self):
        """Order proof: the raw write happens before normalize() runs."""
        events = [_event()]
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(odds_provider, "raw_path",
                                   side_effect=lambda *p: Path(tmp).joinpath(*p)), \
                 mock.patch.object(odds_provider, "fetch_odds", return_value=events), \
                 mock.patch.object(odds_provider, "normalize",
                                   side_effect=RuntimeError("projection blew up")):
                with self.assertRaises(RuntimeError):
                    odds_provider.fetch_normalized(env={"ODDS_API_KEY": FAKE_KEY})
            files = list(Path(tmp).glob("oddsapi/**/*.jsonl.gz"))
        self.assertEqual(len(files), 1,
                          "the raw payload must survive a projection failure")

    def test_one_api_call_produces_exactly_one_raw_file(self):
        events = [_event(), _event("evt2")]
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(odds_provider, "raw_path",
                                   side_effect=lambda *p: Path(tmp).joinpath(*p)), \
                 mock.patch.object(odds_provider, "fetch_odds",
                                   return_value=events) as fetch:
                odds_provider.fetch_normalized(env={"ODDS_API_KEY": FAKE_KEY})
            files = list(Path(tmp).glob("oddsapi/**/*.jsonl.gz"))
        self.assertEqual(fetch.call_count, 1)
        self.assertEqual(len(files), 1)

    def test_capture_ids_are_unique_across_two_calls_same_second(self):
        events = [_event()]
        events2 = [_event("evt-different")]
        fixed = datetime(2026, 9, 3, 1, 2, 3, tzinfo=timezone.utc)
        # Different payload bytes at the identical second -> different hash
        # suffix -> different filename; same payload+second would collide,
        # which is why the id is derived from the body, not just the clock.
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(odds_provider, "raw_path",
                                   side_effect=lambda *p: Path(tmp).joinpath(*p)):
                path_a = odds_provider._write_raw_capture(events, "featured", now=fixed)
                path_b = odds_provider._write_raw_capture(events2, "featured", now=fixed)
        self.assertNotEqual(path_a, path_b)


if __name__ == "__main__":
    unittest.main()
