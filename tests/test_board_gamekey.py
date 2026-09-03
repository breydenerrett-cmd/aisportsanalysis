"""S1 (docs/CHECKPOINT_PHASE0_2026-09-03.md): the event_id <-> game_pk
resolver. Every test injects a fake `schedule_fn` -- nothing here touches
the network, and `src.providers.mlb.fetch_games`'s default is never called.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src.board import gamekey as gk

ATL_SF_COMMENCE = "2026-08-31T22:05:00Z"


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")


def _schedule_game(pk, away, home, start_time_utc):
    return {"game_pk": pk, "away_team": away, "home_team": home,
            "start_time_utc": start_time_utc}


def _single_game_schedule(pk, away, home, start_time_utc, on_date):
    def schedule_fn(date_str):
        if date_str == on_date:
            return [_schedule_game(pk, away, home, start_time_utc)]
        return []
    return schedule_fn


def _empty_schedule(_date_str):
    return []


# ---------------------------------------------------------------------------
# Team-name normalization (the two-step composition, not a new mapping)
# ---------------------------------------------------------------------------

class TeamKeyTests(unittest.TestCase):
    def test_full_name_and_abbreviation_normalize_to_the_same_key(self):
        self.assertEqual(gk._team_key("Boston Red Sox"), gk._team_key("BOS"))

    def test_alias_spellings_fold_together(self):
        # MLB's schedule emits ATH/AZ; odds feeds resolve full names to
        # OAK/ARI via team_abbrev_from_name -- both must land on one key.
        self.assertEqual(gk._team_key("Athletics"), gk._team_key("ATH"))
        self.assertEqual(gk._team_key("ATH"), "OAK")
        self.assertEqual(gk._team_key("Arizona Diamondbacks"), gk._team_key("AZ"))
        self.assertEqual(gk._team_key("AZ"), "ARI")

    def test_unrecognized_name_returns_none_not_a_pass_through(self):
        self.assertIsNone(gk._team_key("Not A Real Team"))
        self.assertIsNone(gk._team_key(""))
        self.assertIsNone(gk._team_key(None))


# ---------------------------------------------------------------------------
# resolve_event
# ---------------------------------------------------------------------------

class ResolveEventTests(unittest.TestCase):
    def test_resolves_a_clean_match(self):
        schedule_fn = _single_game_schedule(
            12345, "SF", "ATL", ATL_SF_COMMENCE, "2026-08-31")
        entry = gk.resolve_event(
            "evt1", "Atlanta Braves", "San Francisco Giants",
            ATL_SF_COMMENCE, schedule_fn=schedule_fn)
        self.assertTrue(entry["resolved"])
        self.assertFalse(entry["ambiguous"])
        # Canonical string form (src.core.asof.game_pk_key), not the raw int
        # `schedule_fn` handed back -- the ONE point this store's game_pk
        # column is produced (module docstring), so every downstream reader
        # gets the join-key type without a second coercion of its own.
        self.assertEqual(entry["game_pk"], "12345")
        self.assertIsInstance(entry["game_pk"], str)
        self.assertEqual(entry["schedule_commence_time"], ATL_SF_COMMENCE)
        self.assertIsNone(entry["reason"])
        self.assertEqual(entry["candidates"], [])
        # Evidence used is on the row, not just the verdict.
        self.assertEqual(entry["home_team"], "Atlanta Braves")
        self.assertEqual(entry["away_team"], "San Francisco Giants")
        self.assertEqual(entry["commence_time"], ATL_SF_COMMENCE)
        self.assertEqual(entry["source"], "mlb_schedule")
        self.assertIn("resolved_utc", entry)

    def test_doubleheader_resolves_by_nearest_commence_time_and_flags_ambiguous(self):
        def schedule_fn(date_str):
            if date_str == "2026-08-31":
                return [
                    _schedule_game(111, "SF", "ATL", "2026-08-31T18:05:00Z"),
                    _schedule_game(222, "SF", "ATL", "2026-08-31T22:05:00Z"),
                ]
            return []
        entry = gk.resolve_event(
            "evt2", "Atlanta Braves", "San Francisco Giants",
            "2026-08-31T22:00:00Z", schedule_fn=schedule_fn)
        self.assertTrue(entry["resolved"])
        self.assertTrue(entry["ambiguous"])
        self.assertEqual(entry["game_pk"], "222")  # nearest to 22:00Z, canonical string
        candidate_pks = {c["game_pk"] for c in entry["candidates"]}
        self.assertEqual(candidate_pks, {"111", "222"})
        self.assertIn("doubleheader", entry["reason"])

    def test_unresolvable_team_names_refuses_without_calling_schedule(self):
        calls = []

        def schedule_fn(date_str):
            calls.append(date_str)
            return []

        entry = gk.resolve_event(
            "evt3", "Not A Team", "Also Not A Team", ATL_SF_COMMENCE,
            schedule_fn=schedule_fn)
        self.assertFalse(entry["resolved"])
        self.assertIsNone(entry["game_pk"])
        self.assertFalse(entry["ambiguous"])
        self.assertIn("could not normalize", entry["reason"])
        # A bad join key is refused before ever touching the schedule.
        self.assertEqual(calls, [])

    def test_no_schedule_match_refuses_with_a_named_reason(self):
        entry = gk.resolve_event(
            "evt4", "Atlanta Braves", "San Francisco Giants",
            ATL_SF_COMMENCE, schedule_fn=_empty_schedule)
        self.assertFalse(entry["resolved"])
        self.assertIsNone(entry["game_pk"])
        self.assertIn("no schedule game matched", entry["reason"])

    def test_bad_commence_time_refuses_honestly(self):
        entry = gk.resolve_event(
            "evt5", "Atlanta Braves", "San Francisco Giants",
            "not-a-timestamp", schedule_fn=_empty_schedule)
        self.assertFalse(entry["resolved"])
        self.assertIn("could not normalize", entry["reason"])


# ---------------------------------------------------------------------------
# The store: idempotent build, resolved/ambiguous/unresolved counts
# ---------------------------------------------------------------------------

class BuildMapTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.multibook = self.root / "odds_multibook.jsonl"
        self.map_path = self.root / "event_game_map.jsonl"

    def _sources(self):
        return [self.multibook]

    def test_build_map_for_date_counts_and_writes_rows(self):
        _write_jsonl(self.multibook, [
            {"event_id": "evt-resolved", "home_team": "Atlanta Braves",
             "away_team": "San Francisco Giants", "commence_time": ATL_SF_COMMENCE},
            {"event_id": "evt-unresolved", "home_team": "Nowhere FC",
             "away_team": "Nobody United", "commence_time": ATL_SF_COMMENCE},
        ])
        schedule_fn = _single_game_schedule(
            999, "SF", "ATL", ATL_SF_COMMENCE, "2026-08-31")
        report = gk.build_map_for_date(
            "2026-08-31", map_path=self.map_path, event_sources=self._sources(),
            schedule_fn=schedule_fn)
        self.assertEqual(report["candidates"], 2)
        self.assertEqual(report["resolved"], 1)
        self.assertEqual(report["ambiguous"], 0)
        self.assertEqual(report["unresolved"], 1)
        self.assertEqual(report["rows_written"], 2)

        rows = {json.loads(l)["event_id"]: json.loads(l)
                for l in self.map_path.read_text().splitlines()}
        # On-disk row carries the canonical STRING game_pk (not the raw int
        # `schedule_fn` returned) -- this store is the one place that type
        # is produced, so it must never write the un-normalized form.
        self.assertEqual(rows["evt-resolved"]["game_pk"], "999")
        self.assertIsNone(rows["evt-unresolved"]["game_pk"])

    def test_rerun_over_the_same_date_is_idempotent(self):
        _write_jsonl(self.multibook, [
            {"event_id": "evt-a", "home_team": "Atlanta Braves",
             "away_team": "San Francisco Giants", "commence_time": ATL_SF_COMMENCE},
        ])
        schedule_fn = _single_game_schedule(
            999, "SF", "ATL", ATL_SF_COMMENCE, "2026-08-31")
        first = gk.build_map_for_date(
            "2026-08-31", map_path=self.map_path, event_sources=self._sources(),
            schedule_fn=schedule_fn)
        self.assertEqual(first["rows_written"], 1)
        second = gk.build_map_for_date(
            "2026-08-31", map_path=self.map_path, event_sources=self._sources(),
            schedule_fn=schedule_fn)
        self.assertEqual(second["rows_written"], 0)
        self.assertEqual(second["skipped_already_mapped"], 1)
        lines = self.map_path.read_text().splitlines()
        self.assertEqual(len(lines), 1)

    def test_force_re_resolves_and_appends_a_corrected_row(self):
        _write_jsonl(self.multibook, [
            {"event_id": "evt-a", "home_team": "Atlanta Braves",
             "away_team": "San Francisco Giants", "commence_time": ATL_SF_COMMENCE},
        ])
        gk.build_map_for_date(
            "2026-08-31", map_path=self.map_path, event_sources=self._sources(),
            schedule_fn=_empty_schedule)
        index = gk.load_map(self.map_path)
        self.assertIsNone(index["evt-a"]["game_pk"])

        schedule_fn = _single_game_schedule(
            999, "SF", "ATL", ATL_SF_COMMENCE, "2026-08-31")
        gk.build_map_for_date(
            "2026-08-31", map_path=self.map_path, event_sources=self._sources(),
            schedule_fn=schedule_fn, force=True)
        index = gk.load_map(self.map_path)
        self.assertEqual(index["evt-a"]["game_pk"], "999")
        # Append-only: both rows are still on disk, last write wins on read.
        lines = self.map_path.read_text().splitlines()
        self.assertEqual(len(lines), 2)

    def test_game_pk_for_event_returns_none_for_unknown_event(self):
        index = gk.load_map(self.map_path)  # file does not exist
        self.assertEqual(index, {})
        self.assertIsNone(gk.game_pk_for_event("nope", index))

    def test_build_map_for_range_merges_per_date_reports(self):
        _write_jsonl(self.multibook, [
            {"event_id": "evt-31", "home_team": "Atlanta Braves",
             "away_team": "San Francisco Giants",
             "commence_time": "2026-08-31T22:05:00Z"},
            {"event_id": "evt-01", "home_team": "Atlanta Braves",
             "away_team": "San Francisco Giants",
             "commence_time": "2026-09-01T22:05:00Z"},
        ])

        def schedule_fn(date_str):
            if date_str == "2026-08-31":
                return [_schedule_game(1, "SF", "ATL", "2026-08-31T22:05:00Z")]
            if date_str == "2026-09-01":
                return [_schedule_game(2, "SF", "ATL", "2026-09-01T22:05:00Z")]
            return []

        report = gk.build_map_for_range(
            "2026-08-31", "2026-09-01", map_path=self.map_path,
            event_sources=self._sources(), schedule_fn=schedule_fn)
        self.assertEqual(report["candidates"], 2)
        self.assertEqual(report["resolved"], 2)
        self.assertEqual(set(report["by_date"]),
                          {"2026-08-31", "2026-09-01"})


if __name__ == "__main__":
    unittest.main()
