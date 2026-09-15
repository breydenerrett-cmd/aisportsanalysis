"""Sport-aware game identity resolver: gamekey.py generalized to NFL, tennis, etc.

Every test injects a fake schedule_fn and works with temp event stores.
Nothing touches the network.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src.board import gamekey as gk


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")


# ---------------------------------------------------------------------------
# events_for_date sport filtering
# ---------------------------------------------------------------------------

class EventsForDateSportFiltering(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.multibook = self.root / "odds_multibook.jsonl"

    def test_default_sport_returns_only_mlb_rows(self):
        """Default sport="mlb" filters to rows with no sport or sport="mlb"."""
        _write_jsonl(self.multibook, [
            {"event_id": "mlb1", "home_team": "Atlanta Braves",
             "away_team": "San Francisco Giants", "commence_time": "2026-08-31T22:05:00Z"},
            {"event_id": "mlb2", "home_team": "Boston Red Sox",
             "away_team": "New York Yankees", "commence_time": "2026-08-31T20:00:00Z"},
            {"event_id": "nfl1", "home_team": "Buffalo Bills",
             "away_team": "Detroit Lions", "commence_time": "2026-09-14T23:30:00Z",
             "sport": "nfl"},
            {"event_id": "nfl2", "home_team": "Dallas Cowboys",
             "away_team": "Green Bay Packers", "commence_time": "2026-09-14T20:00:00Z",
             "sport": "nfl"},
        ])
        events = gk.events_for_date(
            "2026-08-31", sources=[self.multibook], sport="mlb")
        self.assertEqual(set(events.keys()), {"mlb1", "mlb2"})

    def test_nfl_sport_returns_only_nfl_rows(self):
        """sport="nfl" filters to rows with sport="nfl"."""
        _write_jsonl(self.multibook, [
            {"event_id": "mlb1", "home_team": "Atlanta Braves",
             "away_team": "San Francisco Giants", "commence_time": "2026-08-31T22:05:00Z"},
            {"event_id": "mlb2", "home_team": "Boston Red Sox",
             "away_team": "New York Yankees", "commence_time": "2026-08-31T20:00:00Z"},
            {"event_id": "nfl1", "home_team": "Buffalo Bills",
             "away_team": "Detroit Lions", "commence_time": "2026-09-14T23:30:00Z",
             "sport": "nfl"},
            {"event_id": "nfl2", "home_team": "Dallas Cowboys",
             "away_team": "Green Bay Packers", "commence_time": "2026-09-14T20:00:00Z",
             "sport": "nfl"},
        ])
        events = gk.events_for_date(
            "2026-09-14", sources=[self.multibook], sport="nfl")
        self.assertEqual(set(events.keys()), {"nfl1", "nfl2"})

    def test_sport_none_returns_all_rows(self):
        """sport=None includes all rows regardless of sport."""
        _write_jsonl(self.multibook, [
            {"event_id": "mlb1", "home_team": "Atlanta Braves",
             "away_team": "San Francisco Giants", "commence_time": "2026-08-31T22:05:00Z"},
            {"event_id": "nfl1", "home_team": "Buffalo Bills",
             "away_team": "Detroit Lions", "commence_time": "2026-08-31T23:30:00Z",
             "sport": "nfl"},
        ])
        events = gk.events_for_date(
            "2026-08-31", sources=[self.multibook], sport=None)
        self.assertEqual(set(events.keys()), {"mlb1", "nfl1"})


# ---------------------------------------------------------------------------
# resolve_event for non-MLB sports
# ---------------------------------------------------------------------------

class ResolveEventNflTests(unittest.TestCase):
    def test_nfl_resolves_with_team_key_fn_and_game_id(self):
        """NFL event resolves to game_id (not game_pk) with sport field."""
        def nfl_schedule(date_str):
            if date_str == "2026-09-14":
                return [
                    {
                        "game_id": "2026_02_DET_BUF",
                        "away": "Detroit Lions",
                        "home": "Buffalo Bills",
                        "start_utc": "2026-09-14T23:30:00Z",
                    },
                ]
            return []

        def nfl_team_key(name):
            team_map = {
                "Buffalo Bills": "BUF",
                "Detroit Lions": "DET",
            }
            return team_map.get(name)

        entry = gk.resolve_event(
            "evt-nfl-1", "Buffalo Bills", "Detroit Lions",
            "2026-09-14T23:30:00Z",
            schedule_fn=nfl_schedule, sport="nfl", team_key_fn=nfl_team_key)

        self.assertTrue(entry["resolved"])
        self.assertFalse(entry["ambiguous"])
        self.assertEqual(entry["sport"], "nfl")
        self.assertEqual(entry["game_id"], "2026_02_DET_BUF")
        self.assertIsNone(entry["game_pk"])
        self.assertEqual(entry["source"], "mlb_schedule")  # source param unchanged
        self.assertEqual(entry["schedule_commence_time"], "2026-09-14T23:30:00Z")
        self.assertIsNone(entry["reason"])
        self.assertEqual(entry["candidates"], [])

    def test_nfl_unresolved_when_no_schedule_match(self):
        """NFL event without matching schedule game is unresolved."""
        def nfl_schedule(date_str):
            return []

        def nfl_team_key(name):
            team_map = {"Buffalo Bills": "BUF", "Detroit Lions": "DET"}
            return team_map.get(name)

        entry = gk.resolve_event(
            "evt-nfl-nomatch", "Buffalo Bills", "Detroit Lions",
            "2026-09-14T23:30:00Z",
            schedule_fn=nfl_schedule, sport="nfl", team_key_fn=nfl_team_key)

        self.assertFalse(entry["resolved"])
        self.assertIsNone(entry["game_id"])
        self.assertIsNone(entry["game_pk"])
        self.assertEqual(entry["sport"], "nfl")
        self.assertIn("no schedule game matched", entry["reason"])

    def test_nfl_ambiguous_when_multiple_candidates(self):
        """NFL event with multiple candidates is flagged ambiguous."""
        def nfl_schedule(date_str):
            if date_str == "2026-09-14":
                return [
                    {
                        "game_id": "2026_02_DET_BUF_1",
                        "away": "Detroit Lions",
                        "home": "Buffalo Bills",
                        "start_utc": "2026-09-14T18:00:00Z",
                    },
                    {
                        "game_id": "2026_02_DET_BUF_2",
                        "away": "Detroit Lions",
                        "home": "Buffalo Bills",
                        "start_utc": "2026-09-14T23:30:00Z",
                    },
                ]
            return []

        def nfl_team_key(name):
            team_map = {"Buffalo Bills": "BUF", "Detroit Lions": "DET"}
            return team_map.get(name)

        entry = gk.resolve_event(
            "evt-nfl-ambig", "Buffalo Bills", "Detroit Lions",
            "2026-09-14T23:00:00Z",
            schedule_fn=nfl_schedule, sport="nfl", team_key_fn=nfl_team_key)

        self.assertTrue(entry["resolved"])
        self.assertTrue(entry["ambiguous"])
        self.assertEqual(entry["game_id"], "2026_02_DET_BUF_2")  # nearest
        candidate_ids = {c["game_id"] for c in entry["candidates"]}
        self.assertEqual(candidate_ids, {"2026_02_DET_BUF_1", "2026_02_DET_BUF_2"})
        self.assertIn("doubleheader", entry["reason"])

    def test_nfl_bad_team_names_refuses_without_calling_schedule(self):
        """NFL with unrecognized team names refuses without fetching schedule."""
        calls = []

        def nfl_schedule(date_str):
            calls.append(date_str)
            return []

        def nfl_team_key(name):
            # Only recognizes a specific set of teams
            team_map = {"Buffalo Bills": "BUF", "Detroit Lions": "DET"}
            return team_map.get(name)

        entry = gk.resolve_event(
            "evt-nfl-badteam", "Not A Team", "Also Not A Team",
            "2026-09-14T23:30:00Z",
            schedule_fn=nfl_schedule, sport="nfl", team_key_fn=nfl_team_key)

        self.assertFalse(entry["resolved"])
        self.assertIsNone(entry["game_id"])
        self.assertIsNone(entry["game_pk"])
        # Should not have called schedule_fn for bad team names
        self.assertEqual(calls, [])


# ---------------------------------------------------------------------------
# build_map_for_date with sport
# ---------------------------------------------------------------------------

class BuildMapSportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.multibook = self.root / "odds_multibook.jsonl"
        self.map_path = self.root / "event_game_map.jsonl"

    def _nfl_schedule(self, date_str):
        if date_str == "2026-09-14":
            return [
                {
                    "game_id": "2026_02_DET_BUF",
                    "away": "Detroit Lions",
                    "home": "Buffalo Bills",
                    "start_utc": "2026-09-14T23:30:00Z",
                },
            ]
        return []

    def _nfl_team_key(self, name):
        team_map = {"Buffalo Bills": "BUF", "Detroit Lions": "DET"}
        return team_map.get(name)

    def test_build_map_for_nfl_date_writes_game_id_and_sport(self):
        """build_map_for_date with sport="nfl" writes rows with game_id and sport."""
        _write_jsonl(self.multibook, [
            {"event_id": "nfl-evt-1", "home_team": "Buffalo Bills",
             "away_team": "Detroit Lions", "commence_time": "2026-09-14T23:30:00Z",
             "sport": "nfl"},
        ])

        report = gk.build_map_for_date(
            "2026-09-14", map_path=self.map_path,
            event_sources=[self.multibook],
            schedule_fn=self._nfl_schedule,
            sport="nfl")

        self.assertEqual(report["candidates"], 1)
        self.assertEqual(report["resolved"], 1)
        self.assertEqual(report["ambiguous"], 0)
        self.assertEqual(report["rows_written"], 1)

        rows = {json.loads(l)["event_id"]: json.loads(l)
                for l in self.map_path.read_text().splitlines()}
        row = rows["nfl-evt-1"]
        self.assertEqual(row["sport"], "nfl")
        self.assertEqual(row["game_id"], "2026_02_DET_BUF")
        self.assertIsNone(row["game_pk"])

    def test_build_map_for_nfl_skips_already_mapped_ids(self):
        """build_map_for_nfl is idempotent: already-mapped event_ids are skipped."""
        _write_jsonl(self.multibook, [
            {"event_id": "nfl-evt-1", "home_team": "Buffalo Bills",
             "away_team": "Detroit Lions", "commence_time": "2026-09-14T23:30:00Z",
             "sport": "nfl"},
        ])

        first = gk.build_map_for_date(
            "2026-09-14", map_path=self.map_path,
            event_sources=[self.multibook],
            schedule_fn=self._nfl_schedule,
            sport="nfl")
        self.assertEqual(first["rows_written"], 1)

        second = gk.build_map_for_date(
            "2026-09-14", map_path=self.map_path,
            event_sources=[self.multibook],
            schedule_fn=self._nfl_schedule,
            sport="nfl")
        self.assertEqual(second["rows_written"], 0)
        self.assertEqual(second["skipped_already_mapped"], 1)


# ---------------------------------------------------------------------------
# game_id_for_event
# ---------------------------------------------------------------------------

class GameIdForEventTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.map_path = self.root / "event_game_map.jsonl"

    def test_game_id_for_event_returns_game_id_for_nfl(self):
        """game_id_for_event returns game_id field for non-MLB sports."""
        rows = [
            {"event_id": "nfl-evt-1", "sport": "nfl", "game_id": "2026_02_DET_BUF",
             "game_pk": None, "home_team": "Buffalo Bills",
             "away_team": "Detroit Lions", "commence_time": "2026-09-14T23:30:00Z",
             "resolved": True, "ambiguous": False, "candidates": [],
             "schedule_commence_time": "2026-09-14T23:30:00Z", "source": "mlb_schedule",
             "resolved_utc": "2026-09-14T00:00:00Z"},
        ]
        _write_jsonl(self.map_path, rows)

        index = gk.load_map(self.map_path)
        result = gk.game_id_for_event("nfl-evt-1", index)
        self.assertEqual(result, "2026_02_DET_BUF")

    def test_game_id_for_event_returns_game_pk_for_mlb(self):
        """game_id_for_event returns game_pk field when game_id is absent (MLB)."""
        rows = [
            {"event_id": "mlb-evt-1", "game_pk": "12345",
             "home_team": "Atlanta Braves", "away_team": "San Francisco Giants",
             "commence_time": "2026-08-31T22:05:00Z",
             "resolved": True, "ambiguous": False, "candidates": [],
             "schedule_commence_time": "2026-08-31T22:05:00Z", "source": "mlb_schedule",
             "resolved_utc": "2026-08-31T00:00:00Z"},
        ]
        _write_jsonl(self.map_path, rows)

        index = gk.load_map(self.map_path)
        result = gk.game_id_for_event("mlb-evt-1", index)
        self.assertEqual(result, "12345")

    def test_game_id_for_event_returns_none_for_unknown_event(self):
        """game_id_for_event returns None for unknown event_id."""
        index = gk.load_map(self.map_path)  # nonexistent file
        result = gk.game_id_for_event("unknown-evt", index)
        self.assertIsNone(result)

    def test_game_id_for_event_returns_none_when_both_ids_are_none(self):
        """game_id_for_event returns None when both game_id and game_pk are None (unresolved)."""
        rows = [
            {"event_id": "unresolved-evt", "game_id": None, "game_pk": None,
             "home_team": "Not A Team", "away_team": "Also Not A Team",
             "commence_time": "2026-09-14T23:30:00Z",
             "resolved": False, "ambiguous": False, "candidates": [],
             "schedule_commence_time": None, "source": "mlb_schedule",
             "resolved_utc": "2026-09-14T00:00:00Z"},
        ]
        _write_jsonl(self.map_path, rows)

        index = gk.load_map(self.map_path)
        result = gk.game_id_for_event("unresolved-evt", index)
        self.assertIsNone(result)


# ---------------------------------------------------------------------------
# MLB behavior unchanged
# ---------------------------------------------------------------------------

class MlbBackwardCompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.multibook = self.root / "odds_multibook.jsonl"
        self.map_path = self.root / "event_game_map.jsonl"

    def test_events_for_date_default_treats_missing_sport_as_mlb(self):
        """events_for_date default behavior: no sport field = MLB."""
        _write_jsonl(self.multibook, [
            {"event_id": "evt1", "home_team": "Atlanta Braves",
             "away_team": "San Francisco Giants", "commence_time": "2026-08-31T22:05:00Z"},
        ])
        events = gk.events_for_date("2026-08-31", sources=[self.multibook])
        self.assertEqual(set(events.keys()), {"evt1"})

    def test_mlb_rows_have_no_sport_field(self):
        """Resolved MLB rows do not carry a sport field."""
        def mlb_schedule(date_str):
            if date_str == "2026-08-31":
                return [
                    {
                        "game_pk": 12345,
                        "away_team": "San Francisco Giants",
                        "home_team": "Atlanta Braves",
                        "start_time_utc": "2026-08-31T22:05:00Z",
                    },
                ]
            return []

        _write_jsonl(self.multibook, [
            {"event_id": "mlb-evt", "home_team": "Atlanta Braves",
             "away_team": "San Francisco Giants", "commence_time": "2026-08-31T22:05:00Z"},
        ])

        report = gk.build_map_for_date(
            "2026-08-31", map_path=self.map_path,
            event_sources=[self.multibook],
            schedule_fn=mlb_schedule)

        rows = {json.loads(l)["event_id"]: json.loads(l)
                for l in self.map_path.read_text().splitlines()}
        row = rows["mlb-evt"]
        self.assertNotIn("sport", row)
        self.assertNotIn("game_id", row)
        self.assertEqual(row["game_pk"], "12345")


if __name__ == "__main__":
    unittest.main()
