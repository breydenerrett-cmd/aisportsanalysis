"""Projection round trip on real captured rows: no loss on existing h2h data."""

import json
import unittest
from pathlib import Path

from src.board.project import (
    project_h2h_row,
    project_line_market_row,
    unproject_h2h_row,
)
from src.board.record import price_observation_from_dict

DATA_PATH = Path(__file__).resolve().parents[1] / "data" / "processed" / "odds_multibook.jsonl"
MIN_ROWS = 1000


def _load_rows(limit=None):
    rows = []
    with open(DATA_PATH, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
            if limit and len(rows) >= limit:
                break
    return rows


@unittest.skipUnless(DATA_PATH.exists(), "odds_multibook.jsonl not present")
class RealRowRoundTripTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = _load_rows(limit=2000)
        assert len(cls.rows) >= MIN_ROWS, (
            f"need >= {MIN_ROWS} real rows for this test, found {len(cls.rows)}"
        )

    def test_round_trips_at_least_1000_rows_with_no_loss(self):
        checked = 0
        for row in self.rows[:MIN_ROWS]:
            home, away = project_h2h_row(row)
            reconstructed = unproject_h2h_row(home, away)
            self.assertEqual(reconstructed, {
                "observed_utc": row["observed_utc"],
                "event_id": row["event_id"],
                "book": row["book"],
                "book_last_update": row.get("book_last_update"),
                "home_price": row["home_price"],
                "away_price": row["away_price"],
            })
            checked += 1
        self.assertGreaterEqual(checked, MIN_ROWS)

    def test_projected_rows_construct_valid_price_observations(self):
        # Fill in the fields the legacy row doesn't carry (capture_id,
        # region, known_at/grade) with placeholders -- this test proves the
        # SHAPE survives validation, not that capture wiring exists yet.
        for row in self.rows[:50]:
            home, away = project_h2h_row(row)
            for side_dict in (home, away):
                filled = dict(
                    side_dict,
                    known_at=side_dict["observed_utc"],
                    known_at_grade="C",
                    capture_id="test-capture",
                    source="odds_api",
                    region="us",
                )
                obs = price_observation_from_dict(filled)
                self.assertEqual(obs.market_key, "h2h")
                self.assertIsNone(obs.line)

    def test_selection_ids_are_consistent_across_rows(self):
        # Every home-side projection for h2h/mlb must carry the same
        # selection_id, since selection identity does not depend on event.
        ids = set()
        for row in self.rows[:200]:
            home, _ = project_h2h_row(row)
            ids.add(home["selection_id"])
        self.assertEqual(len(ids), 1)


class LineMarketProjectionTests(unittest.TestCase):
    def test_accepts_point_field(self):
        row = {
            "event_id": "e1", "market_key": "totals", "book": "fanduel",
            "observed_utc": "2026-08-31T10:00:00Z",
            "book_last_update": "2026-08-31T09:59:00Z",
            "point": "8.5", "over_price": -110, "under_price": -110,
        }
        obs = project_line_market_row(row)
        self.assertEqual(len(obs), 2)
        lines = {o["line"] for o in obs}
        self.assertEqual(lines, {"8.5"})

    def test_accepts_line_field(self):
        row = {
            "event_id": "e1", "market_key": "totals", "book": "fanduel",
            "observed_utc": "2026-08-31T10:00:00Z",
            "book_last_update": None,
            "line": "8.5", "over_price": -110, "under_price": -105,
        }
        obs = project_line_market_row(row)
        self.assertEqual({o["line"] for o in obs}, {"8.5"})

    def test_coerces_numeric_point_to_string(self):
        row = {
            "event_id": "e1", "market_key": "totals", "book": "fanduel",
            "observed_utc": "2026-08-31T10:00:00Z", "book_last_update": None,
            "point": 8.5, "over_price": -110, "under_price": -110,
        }
        obs = project_line_market_row(row)
        for o in obs:
            self.assertIsInstance(o["line"], str)

    def test_spreads_home_away_sides(self):
        row = {
            "event_id": "e1", "market_key": "spreads", "book": "draftkings",
            "observed_utc": "2026-08-31T10:00:00Z", "book_last_update": None,
            "point": "-1.5", "home_price": -110, "away_price": -110,
        }
        obs = project_line_market_row(row)
        sides = {o["side"] for o in obs}
        self.assertEqual(sides, {"home", "away"})

    def test_prop_row_carries_subject(self):
        row = {
            "event_id": "e1", "market_key": "batter_hits", "book": "fanduel",
            "observed_utc": "2026-08-31T10:00:00Z", "book_last_update": None,
            "point": "1.5", "over_price": -120, "under_price": 100,
            "subject_kind": "batter", "subject_id": "player-123",
        }
        obs = project_line_market_row(row)
        for o in obs:
            self.assertEqual(o["subject_kind"], "batter")
            self.assertEqual(o["subject_id"], "player-123")


if __name__ == "__main__":
    unittest.main()
