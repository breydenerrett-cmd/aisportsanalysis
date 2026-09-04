"""Unit tests for scripts/totals_reschedule_audit.py on a synthetic
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
    "totals_reschedule_audit", REPO / "scripts" / "totals_reschedule_audit.py"
)
tra = importlib.util.module_from_spec(SPEC)
sys.modules["totals_reschedule_audit"] = tra
SPEC.loader.exec_module(tra)  # type: ignore[union-attr]

import totals_population_audit as tpa  # type: ignore  # noqa: E402


def _event(eid, commence_time, books):
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


class TestRescheduleAuditFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.data_root = Path(self.tmp.name)
        odds_dir = self.data_root / "data" / "historical" / "odds_history"
        odds_dir.mkdir(parents=True)
        self.season_path = odds_dir / "mlb_2023.jsonl"

        books = {"book_a": {8.5: (-110, -110)}, "book_b": {8.5: (-110, -110)}}

        # Event "jitter": commence_time drifts by 5 minutes between two
        # snapshots -- provider-jitter shape, not a real reschedule.
        rows = [
            _snapshot(
                "2023-04-01T10:00:00Z",
                [_event("jitter", "2023-04-02T00:00:00Z", books)],
            ),
            _snapshot(
                "2023-04-01T20:00:00Z",
                [_event("jitter", "2023-04-02T00:05:00Z", books)],
            ),
            # Event "stable": no commence_time drift at all.
            _snapshot(
                "2023-04-01T10:00:00Z",
                [_event("stable", "2023-04-02T01:00:00Z", books)],
            ),
        ]
        with self.season_path.open("w") as f:
            for row in rows:
                f.write(json.dumps(row) + "\n")

    def test_multi_commence_and_delta_bucket(self):
        orig_root = tpa.DATA_ROOT
        tpa.DATA_ROOT = self.data_root
        try:
            result = tra.audit_season(2023)
        finally:
            tpa.DATA_ROOT = orig_root

        self.assertEqual(result["n_events"], 2)
        self.assertEqual(result["n_multi_commence"], 1)
        self.assertEqual(result["total_deltas"], 1)
        # 5-minute forward jitter falls in the "1-5m" bucket, forward sign.
        self.assertEqual(result["bucket_counts"].get("1-5m"), 1)
        self.assertEqual(result["sign_counts"]["forward"], 1)
        self.assertEqual(result["sign_counts"]["backward"], 0)
        self.assertEqual(result["cluster_hits"].get(5), 1)

    def test_render_is_deterministic(self):
        orig_root = tpa.DATA_ROOT
        tpa.DATA_ROOT = self.data_root
        try:
            results = {season: tra.audit_season(season) for season in tra.SEASONS}
        finally:
            tpa.DATA_ROOT = orig_root
        out1 = tra.render(results)
        out2 = tra.render(results)
        self.assertEqual(out1, out2)
        self.assertNotIn("total_runs", out1)
        self.assertNotIn("won", out1)


if __name__ == "__main__":
    unittest.main()
