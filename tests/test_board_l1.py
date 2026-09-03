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
from src.board import l1_historical
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


# Real rows copied verbatim (one event/one bookmaker each, trimmed only by
# array length) from data/historical/odds_history/mlb_2023.jsonl and
# data/historical/odds_first_five/mlb_2023.jsonl -- the archive shapes
# l1_historical.py projects, not invented ones.
HISTORICAL_ODDS_HISTORY_ROW = {
    "events": [{
        "away_team": "Detroit Tigers",
        "bookmakers": [{
            "key": "mybookieag", "last_update": "2023-02-27T23:45:15Z",
            "markets": [
                {"key": "h2h", "last_update": "2023-02-27T23:45:15Z",
                 "outcomes": [{"name": "Detroit Tigers", "price": 127},
                              {"name": "New York Yankees", "price": -156}]},
                {"key": "totals", "last_update": "2023-02-27T23:45:15Z",
                 "outcomes": [{"name": "Over", "point": 9.0, "price": -112},
                              {"name": "Under", "point": 9.0, "price": -108}]},
            ],
            "title": "MyBookie.ag",
        }],
        "commence_time": "2023-02-27T23:35:00Z",
        "home_team": "New York Yankees",
        "id": "be9f3156757fe9dd5d6532e8b6e75bf8",
        "sport_key": "baseball_mlb", "sport_title": "MLB",
    }],
    "markets": ["h2h", "totals"],
    "requested_at": "2023-03-20T16:50Z",
    "snapshot_at": "2023-02-27T23:45:38Z",
}

HISTORICAL_ODDS_FIRST_FIVE_ROW = {
    "away_team": "SEA", "commence_time": "2023-05-04T19:37:00Z",
    "data": {
        "away_team": "Seattle Mariners",
        "bookmakers": [{
            "key": "pointsbetus", "last_update": "2023-05-03T22:44:50Z",
            "markets": [
                {"key": "h2h_1st_5_innings", "last_update": "2023-05-03T22:41:00Z",
                 "outcomes": [{"name": "Oakland Athletics", "price": 160},
                              {"name": "Seattle Mariners", "price": -210}]},
                {"key": "totals_1st_5_innings", "last_update": "2023-05-03T22:41:00Z",
                 "outcomes": [{"name": "Over", "point": 4.5, "price": -105},
                              {"name": "Under", "point": 4.5, "price": -125}]},
            ],
            "title": "PointsBet (US)",
        }],
        "commence_time": "2023-05-04T19:37:00Z",
        "home_team": "Oakland Athletics",
        "id": "890b4e9cf0b8e12f1fad599f656c7646",
        "sport_key": "baseball_mlb", "sport_title": "MLB",
    },
    "date": "2023-05-03", "event_id": "890b4e9cf0b8e12f1fad599f656c7646",
    "game_pk": "718319", "home_team": "OAK",
    "markets": ["h2h_1st_5_innings", "totals_1st_5_innings"],
    "snapshot_at": "2023-05-03T22:45:40Z",
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


class HistoricalArchiveIntegrationTests(unittest.TestCase):
    """`l1.run()`'s dispatch to `l1_historical` for the two archive `kind`s,
    exercised through the SAME `sources=` override every other test in this
    file uses -- the historical stores never need `historical_seasons` here
    since `sources` names them directly, exactly like a fixture live store."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.history_archive = self.root / "odds_history_2023.jsonl"
        self.f5_archive = self.root / "odds_first_five_2023.jsonl"
        self.output = self.root / "l1_observations.jsonl"

    def _sources(self):
        return [
            {"name": "odds_history_archive_2023", "path": self.history_archive,
             "kind": l1_historical.KIND_ODDS_HISTORY, "is_close": False,
             "source_label": l1_historical.HISTORICAL_SOURCE,
             "timestamp_field": "snapshot_at"},
            {"name": "odds_first_five_archive_2023", "path": self.f5_archive,
             "kind": l1_historical.KIND_ODDS_FIRST_FIVE, "is_close": False,
             "source_label": l1_historical.HISTORICAL_SOURCE,
             "timestamp_field": "snapshot_at"},
        ]

    def _run(self, **kwargs):
        kwargs.setdefault("game_map_path", self.root / "event_game_map.jsonl")
        return l1.run(output_path=self.output, raw_root=self.root / "raw",
                      sources=self._sources(), **kwargs)

    def _rows(self):
        return [json.loads(l) for l in self.output.read_text().splitlines()]

    # -- schema: every archive-projected row is a valid PriceObservation ---

    def test_odds_history_row_yields_valid_h2h_and_totals_observations(self):
        _write_jsonl(self.history_archive, [HISTORICAL_ODDS_HISTORY_ROW])
        report = self._run()
        self.assertEqual(report["written"], 4)  # h2h x2 + totals x2
        rows = self._rows()
        for row in rows:
            price_observation_from_dict(row)  # raises on an invalid record
        self.assertEqual({r["market_key"] for r in rows}, {"h2h", "totals"})
        h2h = {r["side"]: r for r in rows if r["market_key"] == "h2h"}
        self.assertEqual(h2h["home"]["price_american"], -156)  # Yankees (home)
        self.assertEqual(h2h["away"]["price_american"], 127)  # Tigers (away)
        totals = {r["side"]: r for r in rows if r["market_key"] == "totals"}
        self.assertEqual(totals["over"]["line"], "9.0")
        self.assertEqual(totals["under"]["line"], "9.0")

    def test_odds_first_five_row_yields_valid_observations(self):
        _write_jsonl(self.f5_archive, [HISTORICAL_ODDS_FIRST_FIVE_ROW])
        report = self._run()
        self.assertEqual(report["written"], 4)
        rows = self._rows()
        for row in rows:
            price_observation_from_dict(row)
        self.assertEqual({r["market_key"] for r in rows},
                         {"h2h_1st_5_innings", "totals_1st_5_innings"})

    # -- observed_utc is snapshot_at, never requested_at --------------------

    def test_observed_utc_is_snapshot_at_not_requested_at(self):
        _write_jsonl(self.history_archive, [HISTORICAL_ODDS_HISTORY_ROW])
        self._run()
        rows = self._rows()
        self.assertTrue(rows)
        for row in rows:
            self.assertEqual(row["observed_utc"], "2023-02-27T23:45:38Z")
            self.assertNotEqual(row["observed_utc"], "2023-03-20T16:50Z")

    # -- idempotence: repeated snapshot_at across many requested_at collapse -

    def test_repeated_snapshot_at_across_requested_at_collapses_to_one_set(self):
        # Same underlying snapshot, three different requested_at values --
        # measured on the real archive (module docstring): a far-future
        # game's price is re-served under many polls before it ever moves.
        copies = []
        for requested_at in ("2023-03-20T16:50Z", "2023-03-20T22:50Z",
                             "2023-03-21T01:50Z"):
            copy = dict(HISTORICAL_ODDS_HISTORY_ROW)
            copy["requested_at"] = requested_at
            copies.append(copy)
        _write_jsonl(self.history_archive, copies)
        report = self._run()
        self.assertEqual(report["written"], 4)
        self.assertEqual(report["skipped_existing"], 8)  # 3x - 1x, deduped
        self.assertEqual(len(self._rows()), 4)

    def test_rerun_over_unchanged_archive_writes_zero_new_rows(self):
        _write_jsonl(self.history_archive, [HISTORICAL_ODDS_HISTORY_ROW])
        first = self._run()
        self.assertEqual(first["written"], 4)
        second = self._run()
        self.assertEqual(second["written"], 0)
        self.assertEqual(second["skipped_existing"], 4)

    # -- source distinguishability: never mistakable for a live capture -----

    def test_archive_rows_carry_a_distinct_source_and_capture_id(self):
        _write_jsonl(self.history_archive, [HISTORICAL_ODDS_HISTORY_ROW])
        self._run()
        for row in self._rows():
            self.assertEqual(row["source"], l1_historical.HISTORICAL_SOURCE)
            self.assertNotEqual(row["source"], "odds_api")
            self.assertTrue(row["capture_id"].startswith(
                f"{l1_historical.HISTORICAL_CAPTURE_PREFIX}:"))
            self.assertFalse(row["capture_id"].startswith("backfill:"))
            self.assertFalse(row["l0_available"])
            self.assertFalse(row["is_close"])

    def test_live_and_historical_rows_for_the_same_store_are_never_confused(self):
        # A live multibook row and a historical archive row projected in
        # the SAME run must remain distinguishable purely by `source` --
        # nothing about the shared output schema may blur that line.
        multibook = self.root / "odds_multibook.jsonl"
        _write_jsonl(multibook, [{
            "observed_utc": "2026-08-31T10:08:30.424365+00:00",
            "event_id": "07d39d9ad653030c4c89d9a08c4071f5",
            "commence_time": "2026-08-31T22:05:00Z",
            "home_team": "Atlanta Braves", "away_team": "San Francisco Giants",
            "book": "fanduel", "book_last_update": "2026-08-31T10:08:23Z",
            "home_price": -158, "away_price": 146,
        }])
        _write_jsonl(self.history_archive, [HISTORICAL_ODDS_HISTORY_ROW])
        sources = self._sources() + [
            {"name": "odds_multibook", "path": multibook, "kind": "multibook",
             "is_close": False, "source_label": "odds_api"},
        ]
        report = l1.run(output_path=self.output, raw_root=self.root / "raw",
                        sources=sources,
                        game_map_path=self.root / "event_game_map.jsonl")
        self.assertEqual(report["written"], 6)  # 2 live + 4 historical
        rows = self._rows()
        live = [r for r in rows if r["source"] == "odds_api"]
        historical = [r for r in rows if r["source"] == l1_historical.HISTORICAL_SOURCE]
        self.assertEqual(len(live), 2)
        self.assertEqual(len(historical), 4)
        self.assertEqual(set(r["observation_id"] for r in live)
                         & set(r["observation_id"] for r in historical), set())

    # -- refusal on missing timestamp, never a guess -------------------------

    def test_odds_history_row_with_no_snapshot_at_is_refused_not_guessed(self):
        broken = dict(HISTORICAL_ODDS_HISTORY_ROW)
        del broken["snapshot_at"]
        _write_jsonl(self.history_archive, [broken])
        report = self._run()
        self.assertEqual(report["written"], 0)
        self.assertGreaterEqual(report["refused"], 1)
        self.assertTrue(any(r.startswith("historical_no_usable_timestamp")
                            for r in report["refusals"]))

    def test_odds_first_five_row_with_no_snapshot_at_is_refused_not_guessed(self):
        broken = dict(HISTORICAL_ODDS_FIRST_FIVE_ROW)
        del broken["snapshot_at"]
        _write_jsonl(self.f5_archive, [broken])
        report = self._run()
        self.assertEqual(report["written"], 0)
        self.assertTrue(any(r.startswith("historical_no_usable_timestamp")
                            for r in report["refusals"]))

    def test_market_outside_scope_is_refused_by_name(self):
        mutated = json.loads(json.dumps(HISTORICAL_ODDS_HISTORY_ROW))
        mutated["events"][0]["bookmakers"][0]["markets"][0]["key"] = "spreads"
        _write_jsonl(self.history_archive, [mutated])
        report = self._run()
        # totals market on the same line still succeeds -- one bad market
        # never hides a good one on the same archive line.
        self.assertEqual(report["written"], 2)
        self.assertTrue(any(r.startswith("historical_market_not_in_scope:spreads")
                            for r in report["refusals"]))

    def test_h2h_outcome_name_mismatch_is_refused_not_silently_dropped(self):
        mutated = json.loads(json.dumps(HISTORICAL_ODDS_HISTORY_ROW))
        mutated["events"][0]["bookmakers"][0]["markets"][0]["outcomes"][0]["name"] = "Some Other Team"
        _write_jsonl(self.history_archive, [mutated])
        report = self._run()
        self.assertEqual(report["written"], 2)  # totals still projects
        self.assertTrue(any(r.startswith("historical_h2h_outcome_mismatch")
                            for r in report["refusals"]))

    # -- grading: measured off snapshot_at, not silently defaulted ----------

    def test_known_at_grade_is_measured_off_snapshot_at_gap(self):
        early = dict(HISTORICAL_ODDS_HISTORY_ROW)
        early["snapshot_at"] = "2023-02-27T10:00:00Z"
        late = dict(HISTORICAL_ODDS_HISTORY_ROW)
        late["snapshot_at"] = "2023-02-27T10:05:00Z"  # 5 minutes later -> B
        _write_jsonl(self.history_archive, [early, late])
        report = self._run()
        rows = self._rows()
        by_stamp = {r["observed_utc"]: r["known_at_grade"] for r in rows}
        self.assertEqual(by_stamp["2023-02-27T10:00:00Z"], "D")  # first instant
        self.assertEqual(by_stamp["2023-02-27T10:05:00Z"], "B")  # 5min gap

    # -- game_pk resolves through the SAME map a live row would use --------

    def test_game_pk_resolves_through_the_same_event_game_map(self):
        _write_jsonl(self.history_archive, [HISTORICAL_ODDS_HISTORY_ROW])
        map_path = self.root / "event_game_map.jsonl"
        _write_jsonl(map_path, [{
            "event_id": HISTORICAL_ODDS_HISTORY_ROW["events"][0]["id"],
            "game_pk": 660123, "resolved": True, "ambiguous": False,
            "source": "mlb_results_csv",
            "schedule_commence_time": "2023-02-27T23:35:00Z",
        }])
        report = self._run(game_map_path=map_path)
        rows = self._rows()
        self.assertTrue(all(r["game_pk"] == 660123 for r in rows))
        self.assertEqual(report["game_pk"]["resolved"], 4)


class HistoricalEventMapTests(unittest.TestCase):
    """`l1_historical.ensure_historical_event_map`: resolves archive events
    against `mlb_results.csv` (no network) into the SAME `event_game_map.jsonl`
    shape `gamekey.py` owns."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.history_dir = self.root / "odds_history"
        self.f5_dir = self.root / "odds_first_five"
        self.history_dir.mkdir()
        self.f5_dir.mkdir()
        self.results_csv = self.root / "mlb_results.csv"
        self.map_path = self.root / "event_game_map.jsonl"

    def _write_results_csv(self, rows):
        header = ("game_pk,date,start_time_utc,venue,game_type,away_team,"
                  "home_team,away_team_id,home_team_id,away_probable,"
                  "home_probable,away_probable_id,home_probable_id,"
                  "away_score,home_score,winner,home_won,total_runs,"
                  "run_differential,double_header,game_number")
        lines = [header]
        for row in rows:
            lines.append(",".join(str(v) for v in row))
        self.results_csv.write_text("\n".join(lines) + "\n")

    def _patch_dirs(self):
        self._orig = (l1_historical.ODDS_HISTORY_DIR,
                     l1_historical.ODDS_FIRST_FIVE_DIR)
        l1_historical.ODDS_HISTORY_DIR = self.history_dir
        l1_historical.ODDS_FIRST_FIVE_DIR = self.f5_dir
        self.addCleanup(self._unpatch_dirs)

    def _unpatch_dirs(self):
        l1_historical.ODDS_HISTORY_DIR, l1_historical.ODDS_FIRST_FIVE_DIR = self._orig

    def test_odds_history_event_resolves_by_team_and_date(self):
        self._patch_dirs()
        _write_jsonl(self.history_dir / "mlb_2023.jsonl", [HISTORICAL_ODDS_HISTORY_ROW])
        self._write_results_csv([
            (660123, "2023-02-27", "2023-02-27T23:35:00Z", "Yankee Stadium",
             "R", "DET", "NYY", 116, 147, "", "", "", "", 3, 5, "NYY", 1, 8, 2,
             "N", 1),
        ])
        report = l1_historical.ensure_historical_event_map(
            [2023], map_path=self.map_path, results_csv=self.results_csv)
        self.assertEqual(report["resolved"], 1)
        self.assertEqual(report["unresolved"], 0)
        loaded = l1_historical.gamekey_module.load_map(self.map_path)
        entry = loaded["be9f3156757fe9dd5d6532e8b6e75bf8"]
        self.assertEqual(entry["game_pk"], "660123")
        self.assertEqual(entry["schedule_commence_time"], "2023-02-27T23:35:00Z")
        self.assertEqual(entry["source"], l1_historical.HISTORICAL_MAP_SOURCE)

    def test_odds_first_five_event_resolves_by_embedded_game_pk(self):
        self._patch_dirs()
        _write_jsonl(self.f5_dir / "mlb_2023.jsonl", [HISTORICAL_ODDS_FIRST_FIVE_ROW])
        self._write_results_csv([
            (718319, "2023-05-03", "2023-05-04T19:37:00Z", "Oakland Coliseum",
             "R", "SEA", "OAK", 136, 133, "", "", "", "", 2, 4, "OAK", 1, 6, 2,
             "N", 1),
        ])
        report = l1_historical.ensure_historical_event_map(
            [2023], map_path=self.map_path, results_csv=self.results_csv)
        self.assertEqual(report["resolved"], 1)
        loaded = l1_historical.gamekey_module.load_map(self.map_path)
        entry = loaded["890b4e9cf0b8e12f1fad599f656c7646"]
        self.assertEqual(entry["game_pk"], "718319")

    def test_unresolvable_event_is_recorded_null_not_guessed(self):
        self._patch_dirs()
        _write_jsonl(self.history_dir / "mlb_2023.jsonl", [HISTORICAL_ODDS_HISTORY_ROW])
        self._write_results_csv([])  # no games at all -- nothing can match
        report = l1_historical.ensure_historical_event_map(
            [2023], map_path=self.map_path, results_csv=self.results_csv)
        self.assertEqual(report["unresolved"], 1)
        loaded = l1_historical.gamekey_module.load_map(self.map_path)
        entry = loaded["be9f3156757fe9dd5d6532e8b6e75bf8"]
        self.assertIsNone(entry["game_pk"])
        self.assertFalse(entry["resolved"])
        self.assertIsNotNone(entry["reason"])

    def test_rerun_skips_already_mapped_events(self):
        self._patch_dirs()
        _write_jsonl(self.history_dir / "mlb_2023.jsonl", [HISTORICAL_ODDS_HISTORY_ROW])
        self._write_results_csv([
            (660123, "2023-02-27", "2023-02-27T23:35:00Z", "Yankee Stadium",
             "R", "DET", "NYY", 116, 147, "", "", "", "", 3, 5, "NYY", 1, 8, 2,
             "N", 1),
        ])
        first = l1_historical.ensure_historical_event_map(
            [2023], map_path=self.map_path, results_csv=self.results_csv)
        self.assertEqual(first["rows_written"], 1)
        second = l1_historical.ensure_historical_event_map(
            [2023], map_path=self.map_path, results_csv=self.results_csv)
        self.assertEqual(second["rows_written"], 0)
        self.assertEqual(second["skipped_already_mapped"], 1)


if __name__ == "__main__":
    unittest.main()
