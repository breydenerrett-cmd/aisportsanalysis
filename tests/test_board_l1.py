"""L1 backfill: projects the real store shapes into PriceObservation rows.

Fixture rows below are copied verbatim (field names and nesting) from real
rows sampled out of this worktree's own odds_multibook.jsonl,
odds_snapshots.jsonl and f5_close.jsonl -- not invented shapes.
"""

from __future__ import annotations

import gzip
import json
import tempfile
import unittest
from pathlib import Path

from src.board import l1
from src.board.record import price_observation_from_dict

MULTIBOOK_ROW = {
    "observed_utc": "2026-08-31T10:08:30.424365+00:00",
    "event_id": "07d39d9ad653030c4c89d9a08c4071f5",
    "commence_time": "2026-08-31T22:05:00Z",
    "home_team": "Atlanta Braves", "away_team": "San Francisco Giants",
    "book": "fanduel", "book_last_update": "2026-08-31T10:08:23Z",
    "home_price": -158, "away_price": 146,
}

SNAPSHOT_H2H_ROW = {
    "observed_utc": "2026-08-27T10:26:48.519723+00:00",
    "event_id": "484411acaf382c9b99aa08d6e6ccd79f",
    "commence_time": "2026-08-27T17:06:00Z",
    "away_team": "Colorado Rockies", "home_team": "Washington Nationals",
    "market": "h2h", "book": "fanduel",
    "prices": {"home_price": -120, "away_price": 110},
    "book_last_update": "2026-08-27T10:26:30Z",
}

SNAPSHOT_SPREADS_ROW = {
    "observed_utc": "2026-08-27T10:26:48.519723+00:00",
    "event_id": "484411acaf382c9b99aa08d6e6ccd79f",
    "commence_time": "2026-08-27T17:06:00Z",
    "away_team": "Colorado Rockies", "home_team": "Washington Nationals",
    "market": "spreads", "book": "fanduel",
    "prices": {"home_line": -1.5, "home_price": 168, "away_line": 1.5, "away_price": -205},
    "book_last_update": "2026-08-27T10:26:30Z",
}

SNAPSHOT_TOTALS_ROW = {
    "observed_utc": "2026-08-27T10:26:48.519723+00:00",
    "event_id": "484411acaf382c9b99aa08d6e6ccd79f",
    "commence_time": "2026-08-27T17:06:00Z",
    "away_team": "Colorado Rockies", "home_team": "Washington Nationals",
    "market": "totals", "book": "fanduel",
    "prices": {"total": 9.5, "over_price": -105, "under_price": -115},
    "book_last_update": "2026-08-27T10:26:30Z",
}

F5_CLOSE_ROW = {
    "away_price": 132, "away_team": "San Francisco Giants", "book": "fanduel",
    "book_last_update": "2026-08-31T22:01:02Z", "commence_time": "2026-08-31T22:05:00Z",
    "event_id": "07d39d9ad653030c4c89d9a08c4071f5", "home_price": -166,
    "home_team": "Atlanta Braves", "market": "h2h_1st_5_innings",
    "observed_utc": "2026-08-31T22:01:44.931694Z",
}


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")


class L1BackfillTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.multibook = self.root / "odds_multibook.jsonl"
        self.snapshots = self.root / "odds_snapshots.jsonl"
        self.f5_close = self.root / "f5_close.jsonl"
        self.output = self.root / "l1_observations.jsonl"
        self.raw_root = self.root / "raw" / "oddsapi"

    def _sources(self):
        return [
            {"name": "odds_multibook", "path": self.multibook, "kind": "multibook", "is_close": False},
            {"name": "odds_snapshots", "path": self.snapshots, "kind": "snapshot", "is_close": False},
            {"name": "f5_close", "path": self.f5_close, "kind": "h2h_flat", "is_close": True},
        ]

    def _run(self, **kwargs):
        # game_map_path defaults to a nonexistent file in this test's own
        # tmpdir -- never the real data/processed/event_game_map.jsonl --
        # so every test here is hermetic unless it explicitly builds a map.
        kwargs.setdefault("game_map_path", self.root / "event_game_map.jsonl")
        return l1.run(output_path=self.output, raw_root=self.raw_root,
                      sources=self._sources(), **kwargs)

    # -- shape coverage -----------------------------------------------

    def test_multibook_h2h_row_yields_two_valid_observations(self):
        _write_jsonl(self.multibook, [MULTIBOOK_ROW])
        report = self._run()
        self.assertEqual(report["written"], 2)
        self.assertEqual(report["by_market_key"]["h2h"]["written"], 2)
        rows = [json.loads(l) for l in self.output.read_text().splitlines()]
        sides = {r["side"] for r in rows}
        self.assertEqual(sides, {"home", "away"})
        for row in rows:
            obs = price_observation_from_dict(row)
            self.assertEqual(obs.market_key, "h2h")
            self.assertIsNone(obs.line)
            self.assertFalse(obs.l0_available)
            self.assertFalse(obs.is_close)

    def test_snapshot_spreads_row_uses_per_side_line_not_shared(self):
        # This is the assumption project_line_market_row's docstring flagged
        # as unverified: a spreads row's home_line and away_line are NOT the
        # same value, and folding one onto the other would corrupt identity.
        _write_jsonl(self.snapshots, [SNAPSHOT_SPREADS_ROW])
        self._run()
        rows = [json.loads(l) for l in self.output.read_text().splitlines()]
        self.assertEqual(len(rows), 2)
        by_side = {r["side"]: r for r in rows}
        self.assertEqual(by_side["home"]["line"], "-1.5")
        self.assertEqual(by_side["away"]["line"], "1.5")
        self.assertNotEqual(by_side["home"]["selection_id"], by_side["away"]["selection_id"])
        for row in rows:
            price_observation_from_dict(row)  # raises on an invalid record

    def test_snapshot_totals_row_uses_total_field_as_shared_line(self):
        _write_jsonl(self.snapshots, [SNAPSHOT_TOTALS_ROW])
        self._run()
        rows = [json.loads(l) for l in self.output.read_text().splitlines()]
        lines = {r["line"] for r in rows}
        self.assertEqual(lines, {"9.5"})
        sides = {r["side"] for r in rows}
        self.assertEqual(sides, {"over", "under"})

    def test_snapshot_h2h_row_flattens_nested_prices(self):
        _write_jsonl(self.snapshots, [SNAPSHOT_H2H_ROW])
        report = self._run()
        self.assertEqual(report["written"], 2)

    def test_f5_close_row_projects_as_h2h_1st_5_innings(self):
        _write_jsonl(self.f5_close, [F5_CLOSE_ROW])
        self._run()
        rows = [json.loads(l) for l in self.output.read_text().splitlines()]
        self.assertEqual({r["market_key"] for r in rows}, {"h2h_1st_5_innings"})
        for row in rows:
            self.assertTrue(row["is_close"])
            price_observation_from_dict(row)

    # -- required fields ------------------------------------------------

    def test_every_row_carries_market_selection_line_price_book_and_clocks(self):
        _write_jsonl(self.multibook, [MULTIBOOK_ROW])
        self._run()
        row = json.loads(self.output.read_text().splitlines()[0])
        for field in ("market_key", "selection_id", "line", "price_american",
                      "book", "observed_utc", "book_last_update", "known_at",
                      "known_at_grade"):
            self.assertIn(field, row)
        self.assertIn(row["known_at_grade"], ("A", "B", "C", "D"))

    # -- idempotency ------------------------------------------------------

    def test_rerun_over_unchanged_store_writes_zero_new_rows(self):
        _write_jsonl(self.multibook, [MULTIBOOK_ROW])
        first = self._run()
        self.assertEqual(first["written"], 2)
        second = self._run()
        self.assertEqual(second["written"], 0)
        self.assertEqual(second["skipped_existing"], 2)
        lines = self.output.read_text().splitlines()
        self.assertEqual(len(lines), 2)

    def test_byte_stable_ids_across_runs(self):
        _write_jsonl(self.multibook, [MULTIBOOK_ROW])
        self._run()
        first_ids = sorted(
            json.loads(l)["observation_id"] for l in self.output.read_text().splitlines()
        )
        # Wipe the output and rebuild from the same source -- ids must match.
        self.output.unlink()
        self._run()
        second_ids = sorted(
            json.loads(l)["observation_id"] for l in self.output.read_text().splitlines()
        )
        self.assertEqual(first_ids, second_ids)

    # -- refusal reporting --------------------------------------------------

    def test_malformed_row_is_refused_and_reported_not_dropped(self):
        broken = dict(MULTIBOOK_ROW)
        del broken["home_price"]
        _write_jsonl(self.multibook, [broken])
        report = self._run()
        self.assertEqual(report["written"], 0)
        self.assertGreaterEqual(report["refused"], 1)
        self.assertTrue(any(r.startswith("missing_field") for r in report["refusals"]))

    # -- since filter -----------------------------------------------------

    def test_since_filters_out_earlier_rows(self):
        _write_jsonl(self.multibook, [MULTIBOOK_ROW])  # observed 2026-08-31
        report = self._run(since="2026-09-01")
        self.assertEqual(report["written"], 0)
        report2 = self._run(since="2026-08-31")
        self.assertEqual(report2["written"], 2)

    # -- raw-first precedence -----------------------------------------------

    def test_raw_match_sets_l0_available_and_capture_id(self):
        _write_jsonl(self.multibook, [MULTIBOOK_ROW])
        raw_payload = [{
            "id": MULTIBOOK_ROW["event_id"],
            "bookmakers": [{
                "key": "fanduel",
                "last_update": "2026-08-31T10:08:23Z",
                "markets": [{
                    "key": "h2h",
                    "outcomes": [
                        {"name": "Atlanta Braves", "price": -158},
                        {"name": "San Francisco Giants", "price": 146},
                    ],
                }],
            }],
        }]
        raw_dir = self.raw_root / "2026" / "08" / "31"
        raw_dir.mkdir(parents=True, exist_ok=True)
        capture_id = "20260831T100825Z-deadbeef"
        record = {"captured_utc": "2026-08-31T10:08:25+00:00", "kind": "featured",
                   "payload": raw_payload}
        with gzip.open(raw_dir / f"{capture_id}.jsonl.gz", "wt", encoding="utf-8") as handle:
            handle.write(json.dumps(record) + "\n")

        report = self._run()
        self.assertEqual(report["raw_matched"], 2)
        rows = [json.loads(l) for l in self.output.read_text().splitlines()]
        for row in rows:
            self.assertTrue(row["l0_available"])
            self.assertEqual(row["capture_id"], capture_id)

    def test_no_raw_file_present_stamps_l0_available_false(self):
        _write_jsonl(self.multibook, [MULTIBOOK_ROW])
        self._run()
        rows = [json.loads(l) for l in self.output.read_text().splitlines()]
        for row in rows:
            self.assertFalse(row["l0_available"])
            self.assertTrue(row["capture_id"].startswith("backfill:"))

    # -- S1: game_pk from the event_id -> game_pk map ----------------------

    def test_no_map_leaves_game_pk_null_and_counts_not_in_map(self):
        _write_jsonl(self.multibook, [MULTIBOOK_ROW])
        report = self._run()  # default helper points at a nonexistent map
        rows = [json.loads(l) for l in self.output.read_text().splitlines()]
        self.assertTrue(all(r["game_pk"] is None for r in rows))
        self.assertEqual(report["game_pk"]["not_in_map"], 2)
        self.assertEqual(report["game_pk"]["resolved"], 0)
        for row in rows:
            price_observation_from_dict(row)  # game_pk=None is still valid

    def test_resolved_map_entry_populates_game_pk(self):
        _write_jsonl(self.multibook, [MULTIBOOK_ROW])
        map_path = self.root / "event_game_map.jsonl"
        _write_jsonl(map_path, [{
            "event_id": MULTIBOOK_ROW["event_id"], "game_pk": 777123,
            "resolved": True, "ambiguous": False,
        }])
        report = self._run(game_map_path=map_path)
        rows = [json.loads(l) for l in self.output.read_text().splitlines()]
        self.assertTrue(all(r["game_pk"] == 777123 for r in rows))
        self.assertEqual(report["game_pk"]["resolved"], 2)
        self.assertEqual(report["game_pk"]["ambiguous"], 0)

    def test_ambiguous_map_entry_still_carries_its_best_guess_game_pk(self):
        _write_jsonl(self.multibook, [MULTIBOOK_ROW])
        map_path = self.root / "event_game_map.jsonl"
        _write_jsonl(map_path, [{
            "event_id": MULTIBOOK_ROW["event_id"], "game_pk": 777123,
            "resolved": True, "ambiguous": True,
        }])
        report = self._run(game_map_path=map_path)
        rows = [json.loads(l) for l in self.output.read_text().splitlines()]
        self.assertTrue(all(r["game_pk"] == 777123 for r in rows))
        self.assertEqual(report["game_pk"]["ambiguous"], 2)
        self.assertEqual(report["game_pk"]["resolved"], 0)

    def test_genuinely_unresolvable_map_entry_leaves_game_pk_null(self):
        _write_jsonl(self.multibook, [MULTIBOOK_ROW])
        map_path = self.root / "event_game_map.jsonl"
        _write_jsonl(map_path, [{
            "event_id": MULTIBOOK_ROW["event_id"], "game_pk": None,
            "resolved": False, "ambiguous": False,
            "reason": "no schedule game matched",
        }])
        report = self._run(game_map_path=map_path)
        rows = [json.loads(l) for l in self.output.read_text().splitlines()]
        self.assertTrue(all(r["game_pk"] is None for r in rows))
        self.assertEqual(report["game_pk"]["map_null"], 2)

    def test_game_map_path_none_skips_lookup_entirely(self):
        _write_jsonl(self.multibook, [MULTIBOOK_ROW])
        map_path = self.root / "event_game_map.jsonl"
        _write_jsonl(map_path, [{
            "event_id": MULTIBOOK_ROW["event_id"], "game_pk": 777123,
            "resolved": True, "ambiguous": False,
        }])
        # A caller that explicitly asks for no game_pk lookup at all -- the
        # map exists but game_map_path=None must never read it.
        report = self._run(game_map_path=None)
        rows = [json.loads(l) for l in self.output.read_text().splitlines()]
        self.assertTrue(all(r["game_pk"] is None for r in rows))
        self.assertEqual(report["game_pk"]["not_in_map"], 2)


if __name__ == "__main__":
    unittest.main()
