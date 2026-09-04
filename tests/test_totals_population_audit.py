"""Unit tests for scripts/totals_population_audit.py on a synthetic
archive fixture. No real data file is touched; no outcome field exists
anywhere in the fixture or the code under test.
"""
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "totals_population_audit", REPO / "scripts" / "totals_population_audit.py"
)
tpa = importlib.util.module_from_spec(SPEC)
sys.modules["totals_population_audit"] = tpa
SPEC.loader.exec_module(tpa)  # type: ignore[union-attr]


def _event(eid, commence_time, books):
    """books: {book_key: {line: (over_price, under_price)}}"""
    bookmakers = []
    for bk, lines in books.items():
        outcomes_by_market = []
        for line, (over_p, under_p) in lines.items():
            outcomes_by_market.append({"name": "Over", "point": line, "price": over_p})
            outcomes_by_market.append({"name": "Under", "point": line, "price": under_p})
        bookmakers.append(
            {
                "key": bk,
                "title": bk,
                "markets": [{"key": "totals", "outcomes": outcomes_by_market}],
            }
        )
    return {
        "id": eid,
        "commence_time": commence_time,
        "home_team": "Home",
        "away_team": "Away",
        "bookmakers": bookmakers,
    }


def _snapshot(snapshot_at, events):
    return {"snapshot_at": snapshot_at, "requested_at": snapshot_at, "events": events}


class TestPopulationAuditFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data_root = Path(self.tmp.name)
        odds_dir = self.data_root / "data" / "historical" / "odds_history"
        odds_dir.mkdir(parents=True)
        self.season_path = odds_dir / "mlb_2023.jsonl"

        books_3 = {
            "book_a": {8.5: (-110, -110)},
            "book_b": {8.5: (-105, -115)},
            "book_c": {8.5: (-112, -108)},
        }
        books_2 = {
            "book_a": {9.0: (-110, -110)},
            "book_b": {9.0: (-105, -115)},
        }

        # Event 1: >=3 books at a half-point line (8.5), closing snapshot
        # 2h before commence -- inside the 12h window. Floor met, half-point.
        snap1 = _snapshot(
            "2023-04-01T00:00:00Z",
            [_event("game1", "2023-04-01T02:00:00Z", books_3)],
        )
        # Event 2: only 2 books at an integer line (9.0), also 2h before
        # commence. Floor NOT met, integer (not half-point).
        snap2 = _snapshot(
            "2023-04-01T00:00:00Z",
            [_event("game2", "2023-04-01T02:00:00Z", books_2)],
        )
        # Event 3: only snapshot is 20h before commence -- outside the 12h
        # window, so it must be excluded (no closing snapshot found).
        snap3 = _snapshot(
            "2023-04-02T00:00:00Z",
            [_event("game3", "2023-04-02T20:00:00Z", books_3)],
        )
        # Event 4 (rescheduled): two snapshots carry two different
        # commence_time values for the same event id. The later snapshot,
        # 1h before ITS OWN recorded commence_time, is the closing snapshot.
        snap4a = _snapshot(
            "2023-04-03T00:00:00Z",
            [_event("game4", "2023-04-03T18:00:00Z", books_3)],
        )
        snap4b = _snapshot(
            "2023-04-03T19:00:00Z",
            [_event("game4", "2023-04-03T20:00:00Z", books_3)],
        )

        with self.season_path.open("w") as f:
            for snap in (snap1, snap2, snap3, snap4a, snap4b):
                f.write(json.dumps(snap) + "\n")

        self._old_data_root = tpa.DATA_ROOT
        tpa.DATA_ROOT = self.data_root

    def tearDown(self):
        tpa.DATA_ROOT = self._old_data_root
        self.tmp.cleanup()

    def test_event_snapshot_loading(self):
        events = tpa._load_event_snapshots(2023)
        self.assertEqual(set(events.keys()), {"game1", "game2", "game3", "game4"})
        self.assertEqual(len(events["game4"]), 2)

    def test_closing_snapshot_window_and_rescheduled(self):
        result = tpa.audit_season(2023)
        # game3's only snapshot is outside the 12h window.
        self.assertEqual(result["excluded_no_closing_snapshot"], 1)
        # game4 has two distinct commence_time values recorded.
        self.assertEqual(result["rescheduled"], 1)
        # game1, game2, game4 all have a closing snapshot -> games_any_totals
        # counts all four events regardless of window.
        self.assertEqual(result["games_any_totals"], 4)

    def test_floor_and_half_point_population(self):
        result = tpa.audit_season(2023)
        # game1 (3 books, 8.5) and game4 (3 books, 8.5) meet the floor and
        # are half-point; game2 (2 books, integer) meets neither; game3 is
        # excluded entirely (no closing snapshot).
        self.assertEqual(result["games_floor_met"], 2)
        self.assertEqual(result["games_half_point"], 2)
        self.assertEqual(result["games_joint"], 2)

    def test_modal_line_tiebreak_toward_8_5(self):
        # Two lines tied on book count, one of them 8.5 -> must pick 8.5.
        lines = {8.5: {"a", "b"}, 9.5: {"c", "d"}}
        self.assertEqual(tpa._modal_line(lines), 8.5)
        # No 8.5 present, tie between 7.5 and 9.5 (equidistant) -> smaller.
        lines2 = {7.5: {"a", "b"}, 9.5: {"c", "d"}}
        self.assertEqual(tpa._modal_line(lines2), 7.5)

    def test_no_outcome_field_read_from_fixture(self):
        # The fixture never carries a total_runs/won/score field; confirm
        # the loader's parsed structure has no such key anywhere.
        events = tpa._load_event_snapshots(2023)
        for records in events.values():
            for _snap_at, _commence_time, lines in records:
                self.assertIsInstance(lines, dict)
                for line, books in lines.items():
                    self.assertIsInstance(books, set)

    def test_deterministic_rerun(self):
        r1 = tpa.render({s: tpa.audit_season(2023) for s in tpa.SEASONS})
        r2 = tpa.render({s: tpa.audit_season(2023) for s in tpa.SEASONS})
        self.assertEqual(r1, r2)


if __name__ == "__main__":
    unittest.main()
