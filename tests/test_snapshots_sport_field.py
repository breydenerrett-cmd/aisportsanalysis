"""Tests for sport-aware odds snapshots with MLB byte-identity.

Captures the contract: MLB rows carry no "sport" field, non-MLB rows carry
"sport": <key>, and readers default to MLB-only via sport="mlb" unless
sport=None is explicitly passed.
"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from src.analysis import prices
from src.pipeline import snapshots


class TestSportFieldInMultibook(unittest.TestCase):
    def test_read_multibook_filters_to_mlb_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "multibook.jsonl"

            # Write two legacy (MLB) rows and two NFL rows
            rows = [
                {"observed_utc": "2026-08-27T12:00:00Z", "event_id": "e1",
                 "away_price": 110, "home_price": -130},
                {"observed_utc": "2026-08-27T13:00:00Z", "event_id": "e2",
                 "away_price": 110, "home_price": -130},
                {"observed_utc": "2026-08-27T12:00:00Z", "event_id": "e3",
                 "away_price": 110, "home_price": -130, "sport": "nfl"},
                {"observed_utc": "2026-08-27T13:00:00Z", "event_id": "e4",
                 "away_price": 110, "home_price": -130, "sport": "nfl"},
            ]
            snapshots.append(rows, path)

            # Default (MLB): only 2 rows
            mlb_only = snapshots.read_multibook(path)
            self.assertEqual(len(mlb_only), 2)
            self.assertNotIn("sport", mlb_only[0])
            self.assertNotIn("sport", mlb_only[1])

            # sport="nfl": only 2 rows
            nfl_only = snapshots.read_multibook(path, sport="nfl")
            self.assertEqual(len(nfl_only), 2)
            self.assertEqual(nfl_only[0].get("sport"), "nfl")
            self.assertEqual(nfl_only[1].get("sport"), "nfl")

            # sport=None: all 4 rows
            all_rows = snapshots.read_multibook(path, sport=None)
            self.assertEqual(len(all_rows), 4)

    def test_iter_multibook_filters_to_mlb_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "multibook.jsonl"

            rows = [
                {"observed_utc": "2026-08-27T12:00:00Z", "event_id": "e1",
                 "away_price": 110, "home_price": -130},
                {"observed_utc": "2026-08-27T13:00:00Z", "event_id": "e2",
                 "away_price": 110, "home_price": -130, "sport": "nfl"},
            ]
            snapshots.append(rows, path)

            # Default (MLB): only 1 row
            mlb_only = list(snapshots.iter_multibook(path))
            self.assertEqual(len(mlb_only), 1)

            # sport="nfl": only 1 row
            nfl_only = list(snapshots.iter_multibook(path, sport="nfl"))
            self.assertEqual(len(nfl_only), 1)
            self.assertEqual(nfl_only[0].get("sport"), "nfl")

            # sport=None: all 2 rows
            all_rows = list(snapshots.iter_multibook(path, sport=None))
            self.assertEqual(len(all_rows), 2)


class TestMultibookRowsSportTag(unittest.TestCase):
    def test_multibook_rows_tags_nfl_rows_not_mlb(self):
        observed = "2026-08-27T12:00:00Z"
        event = {
            "event_id": "e1", "commence_time": "2026-08-27T23:05:00Z",
            "away_team": "Houston Astros", "home_team": "New York Yankees",
            "all_books": {
                "h2h": [
                    {"book": "fanduel", "home_price": -130, "away_price": 110},
                ]
            }
        }

        # sport=None: no "sport" field
        rows_no_sport = snapshots.multibook_rows(observed, [event], sport=None)
        self.assertEqual(len(rows_no_sport), 1)
        self.assertNotIn("sport", rows_no_sport[0])

        # sport="mlb": no "sport" field
        rows_mlb = snapshots.multibook_rows(observed, [event], sport="mlb")
        self.assertEqual(len(rows_mlb), 1)
        self.assertNotIn("sport", rows_mlb[0])

        # sport="nfl": "sport" field present
        rows_nfl = snapshots.multibook_rows(observed, [event], sport="nfl")
        self.assertEqual(len(rows_nfl), 1)
        self.assertEqual(rows_nfl[0].get("sport"), "nfl")


class TestCaptureWithSport(unittest.TestCase):
    def test_capture_with_nfl_sport_tags_rows_and_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            snapshot_path = Path(tmp) / "snaps.jsonl"
            multibook_path = Path(tmp) / "multibook.jsonl"

            payload = {
                "events": [{
                    "event_id": "e1", "commence_time": "2026-08-27T23:05:00Z",
                    "away_team": "Houston Texans", "home_team": "Dallas Cowboys",
                    "markets": {
                        "h2h": {"book": "fanduel", "home_price": -130, "away_price": 110}
                    },
                    "all_books": {
                        "h2h": [{"book": "fanduel", "home_price": -130, "away_price": 110}]
                    }
                }],
                "event_count": 1
            }

            with mock.patch("src.providers.odds.status") as mock_status, \
                 mock.patch("src.providers.odds.fetch_normalized") as mock_fetch:
                mock_status.return_value = {"configured": True}
                mock_fetch.return_value = payload

                summary = snapshots.capture(
                    path=snapshot_path, multibook_path=multibook_path, sport="nfl")

                # Summary should have sport field
                self.assertEqual(summary.get("sport"), "nfl")

                # Snapshot rows should have "sport": "nfl"
                snap_rows = snapshots.read(snapshot_path, sport=None)
                self.assertEqual(len(snap_rows), 1)
                self.assertEqual(snap_rows[0].get("sport"), "nfl")

                # Multibook rows should have "sport": "nfl"
                mb_rows = snapshots.read_multibook(multibook_path, sport=None)
                self.assertEqual(len(mb_rows), 1)
                self.assertEqual(mb_rows[0].get("sport"), "nfl")

    def test_capture_with_mlb_does_not_add_sport_field(self):
        with tempfile.TemporaryDirectory() as tmp:
            snapshot_path = Path(tmp) / "snaps.jsonl"
            multibook_path = Path(tmp) / "multibook.jsonl"

            payload = {
                "events": [{
                    "event_id": "e1", "commence_time": "2026-08-27T23:05:00Z",
                    "away_team": "Houston Astros", "home_team": "New York Yankees",
                    "markets": {
                        "h2h": {"book": "fanduel", "home_price": -130, "away_price": 110}
                    },
                    "all_books": {
                        "h2h": [{"book": "fanduel", "home_price": -130, "away_price": 110}]
                    }
                }],
                "event_count": 1
            }

            with mock.patch("src.providers.odds.status") as mock_status, \
                 mock.patch("src.providers.odds.fetch_normalized") as mock_fetch:
                mock_status.return_value = {"configured": True}
                mock_fetch.return_value = payload

                summary = snapshots.capture(
                    path=snapshot_path, multibook_path=multibook_path)

                # Summary should have sport field (always)
                self.assertEqual(summary.get("sport"), "mlb")

                # Snapshot rows should NOT have "sport" field (byte-identical)
                snap_rows = snapshots.read(snapshot_path, sport=None)
                self.assertEqual(len(snap_rows), 1)
                self.assertNotIn("sport", snap_rows[0])

                # Multibook rows should NOT have "sport" field
                mb_rows = snapshots.read_multibook(multibook_path, sport=None)
                self.assertEqual(len(mb_rows), 1)
                self.assertNotIn("sport", mb_rows[0])

    def test_capture_calls_fetch_normalized_correctly_for_mlb(self):
        with tempfile.TemporaryDirectory() as tmp:
            snapshot_path = Path(tmp) / "snaps.jsonl"

            payload = {
                "events": [],
                "event_count": 0
            }

            with mock.patch("src.providers.odds.status") as mock_status, \
                 mock.patch("src.providers.odds.fetch_normalized") as mock_fetch:
                mock_status.return_value = {"configured": True}
                mock_fetch.return_value = payload

                # Default call (no sport)
                snapshots.capture(path=snapshot_path)

                # fetch_normalized should be called without sport keyword
                mock_fetch.assert_called_once_with(env=None, timeout=20)

    def test_capture_calls_fetch_normalized_with_sport_for_nfl(self):
        with tempfile.TemporaryDirectory() as tmp:
            snapshot_path = Path(tmp) / "snaps.jsonl"

            payload = {
                "events": [],
                "event_count": 0
            }

            with mock.patch("src.providers.odds.status") as mock_status, \
                 mock.patch("src.providers.odds.fetch_normalized") as mock_fetch:
                mock_status.return_value = {"configured": True}
                mock_fetch.return_value = payload

                # Call with sport="nfl"
                snapshots.capture(path=snapshot_path, sport="nfl")

                # fetch_normalized should be called WITH sport keyword
                mock_fetch.assert_called_once_with(env=None, timeout=20, sport="nfl")


class TestMultibookQuotesSport(unittest.TestCase):
    def test_multibook_quotes_filters_to_mlb_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "multibook.jsonl"

            rows = [
                {"observed_utc": "2026-08-27T12:00:00Z", "commence_time": "2026-08-27T23:05:00Z",
                 "event_id": "e1", "book": "fanduel",
                 "away_team": "Houston Astros", "home_team": "New York Yankees",
                 "away_price": 110, "home_price": -130},
                {"observed_utc": "2026-08-27T12:00:00Z", "commence_time": "2026-08-27T23:05:00Z",
                 "event_id": "e2", "book": "fanduel",
                 "away_team": "Dallas Cowboys", "home_team": "Houston Texans",
                 "away_price": 110, "home_price": -130, "sport": "nfl"},
            ]
            snapshots.append(rows, path)

            # Default (MLB): only MLB quotes
            quotes_mlb = snapshots.multibook_quotes(
                date="2026-08-27", path=path)
            self.assertEqual(len(quotes_mlb), 1)

            # sport="nfl": only NFL quotes
            quotes_nfl = snapshots.multibook_quotes(
                date="2026-08-27", path=path, sport="nfl")
            self.assertEqual(len(quotes_nfl), 1)

    def test_multibook_quotes_with_rows_param_filters_sport(self):
        rows = [
            {"observed_utc": "2026-08-27T12:00:00Z", "commence_time": "2026-08-27T23:05:00Z",
             "event_id": "e1", "book": "fanduel",
             "away_team": "Houston Astros", "home_team": "New York Yankees",
             "away_price": 110, "home_price": -130},
            {"observed_utc": "2026-08-27T12:00:00Z", "commence_time": "2026-08-27T23:05:00Z",
             "event_id": "e2", "book": "fanduel",
             "away_team": "Dallas Cowboys", "home_team": "Houston Texans",
             "away_price": 110, "home_price": -130, "sport": "nfl"},
        ]

        # Default (MLB): only MLB quotes
        quotes_mlb = snapshots.multibook_quotes(
            date="2026-08-27", rows=rows)
        self.assertEqual(len(quotes_mlb), 1)

        # sport="nfl": only NFL quotes
        quotes_nfl = snapshots.multibook_quotes(
            date="2026-08-27", rows=rows, sport="nfl")
        self.assertEqual(len(quotes_nfl), 1)


class TestBoardsByMatchupSport(unittest.TestCase):
    def test_boards_by_matchup_filters_to_mlb_by_default(self):
        # Both rows are MLB because team_abbrev_from_name only recognizes MLB teams.
        # Test that sport filtering correctly applies to the rows as they flow through.
        rows = [
            {"observed_utc": "2026-08-27T12:00:00Z", "event_id": "e1",
             "commence_time": "2026-08-27T23:05:00Z",
             "away_team": "Houston Astros", "home_team": "New York Yankees",
             "book": "fanduel", "away_price": 110, "home_price": -130},
            {"observed_utc": "2026-08-27T12:00:00Z", "event_id": "e2",
             "commence_time": "2026-08-28T23:05:00Z",
             "away_team": "Los Angeles Dodgers", "home_team": "San Francisco Giants",
             "book": "fanduel", "away_price": 110, "home_price": -130, "sport": "nfl"},
        ]

        # Default (MLB): only MLB boards
        boards_mlb = prices.boards_by_matchup(rows)
        self.assertEqual(len(boards_mlb), 1)

        # sport="nfl": the second row is tagged nfl but names MLB clubs, so
        # the NFL translator (src.sports.nfl_teams) does not recognize it and
        # it is dropped -- 0 boards, not 1. Before the fix that put the
        # sport behind the translator choice, this row would have resolved
        # anyway (team_abbrev_from_name recognizes "Dodgers"/"Giants"
        # regardless of the sport tag), which is exactly the bug: an NFL
        # lookup silently accepting an MLB name.
        boards_nfl = prices.boards_by_matchup(rows, sport="nfl")
        self.assertEqual(len(boards_nfl), 0)


if __name__ == "__main__":
    unittest.main()
