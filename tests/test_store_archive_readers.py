"""Every reader this project has for odds_multibook.jsonl (and the other
shared-helper stores) must see rows a rotation (src.pipeline.store_archive,
2026-09-21 100MB-push incident) has already moved into a cold archive
segment -- "the LOGICAL store" is the whole point of the fix. This file
proves that for the readers the task brief names explicitly: `read_multibook`
(src.pipeline.snapshots), the L1 backfill's source-store read
(src.board.l1), the event-source read (src.board.gamekey), and the
non-MLB sport-tag read (src.engine.glue).

Every test builds its OWN rotated store in a temp directory (never the real
data/processed/ files) by writing a gzip segment directly -- this does not
call `store_archive.rotate` itself (that is tests/test_store_archive.py's
job); it only has to look exactly like what a rotation leaves behind, so a
reader test failing here can never be blamed on the rotator.
"""

from __future__ import annotations

import gzip
import json
import tempfile
import unittest
from pathlib import Path

from src.board import gamekey
from src.board import l1 as l1_module
from src.engine import glue
from src.pipeline import snapshots


def _write_rotated_store(hot_path: Path, *, archived_rows: list, hot_rows: list,
                         first_date: str, last_date: str) -> None:
    """Lay out `hot_path` exactly as store_archive.rotate would have left
    it: one segment holding `archived_rows`, plus `hot_rows` in the hot
    file. Deliberately NOT calling `rotate` -- see module docstring."""
    seg_dir = hot_path.parent / "archive" / hot_path.stem
    seg_dir.mkdir(parents=True, exist_ok=True)
    segment = seg_dir / f"0001_{first_date}_{last_date}.jsonl.gz"
    archived_bytes = "".join(json.dumps(r, separators=(",", ":")) + "\n"
                             for r in archived_rows).encode("utf-8")
    with open(segment, "wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as gz:
            gz.write(archived_bytes)
    hot_path.parent.mkdir(parents=True, exist_ok=True)
    hot_path.write_text(
        "".join(json.dumps(r, separators=(",", ":")) + "\n" for r in hot_rows),
        encoding="utf-8")


class ReadMultibookSeesArchivedRows(unittest.TestCase):
    """src.pipeline.snapshots.read_multibook / iter_multibook -- the
    most-called reader of this store in the project (src.report.card,
    src.pipeline.dense, src.pipeline.grading, and a dozen others all go
    through this)."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "odds_multibook.jsonl"
        archived = [{"observed_utc": "2026-09-01T10:00:00+00:00", "event_id": "archived-1",
                    "book": "fanduel", "home_price": -150, "away_price": 130,
                    "home_team": "Atlanta Braves", "away_team": "San Francisco Giants",
                    "commence_time": "2026-09-01T22:05:00Z"}]
        hot = [{"observed_utc": "2026-09-21T10:00:00+00:00", "event_id": "hot-1",
               "book": "fanduel", "home_price": -110, "away_price": -110,
               "home_team": "New York Mets", "away_team": "Miami Marlins",
               "commence_time": "2026-09-21T23:05:00Z"}]
        _write_rotated_store(self.path, archived_rows=archived, hot_rows=hot,
                             first_date="2026-09-01", last_date="2026-09-01")

    def test_read_multibook_returns_both_the_archived_and_hot_row(self):
        rows = snapshots.read_multibook(path=self.path, sport=None)
        event_ids = {r["event_id"] for r in rows}
        self.assertEqual(event_ids, {"archived-1", "hot-1"})

    def test_iter_multibook_streams_both_the_archived_and_hot_row(self):
        rows = list(snapshots.iter_multibook(path=self.path, sport=None))
        event_ids = {r["event_id"] for r in rows}
        self.assertEqual(event_ids, {"archived-1", "hot-1"})

    def test_iter_multibook_market_prefilter_still_applies_to_archived_lines(self):
        # `market=None` above means "every row" (moneyline rows carry no
        # market key). Confirm the text prefilter path also works against
        # an archived line, not only the hot one, by asking for a market
        # neither row has -- both must be filtered out.
        rows = list(snapshots.iter_multibook(path=self.path, market="totals", sport=None))
        self.assertEqual(rows, [])


class L1SourceReadSeesArchivedRows(unittest.TestCase):
    """src.board.l1's shared `_read_jsonl` -- the reader behind
    SOURCE_STORES (odds_multibook/odds_snapshots/f5_close) and the L1
    backfill's own output store."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "odds_multibook.jsonl"
        _write_rotated_store(
            self.path,
            archived_rows=[{"observed_utc": "2026-09-01T10:00:00+00:00", "tag": "archived"}],
            hot_rows=[{"observed_utc": "2026-09-21T10:00:00+00:00", "tag": "hot"}],
            first_date="2026-09-01", last_date="2026-09-01")

    def test_read_jsonl_returns_both_rows(self):
        rows = l1_module._read_jsonl(self.path)
        self.assertEqual({r["tag"] for r in rows}, {"archived", "hot"})

    def test_present_is_true_via_store_archive_exists(self):
        # SOURCE_STORES' own presence check (l1.run's per-source loop) --
        # see l1.py's "present": store_archive.exists(path).
        from src.pipeline import store_archive
        self.assertTrue(store_archive.exists(self.path))


class GamekeyEventsForDateSeesArchivedRows(unittest.TestCase):
    """src.board.gamekey.events_for_date over DEFAULT_EVENT_SOURCES-shaped
    input, explicit `sources=` (never the real event_game_map.jsonl)."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "odds_multibook.jsonl"
        archived = [{"event_id": "archived-evt", "commence_time": "2026-09-01T18:00:00Z",
                    "home_team": "Atlanta Braves", "away_team": "San Francisco Giants"}]
        hot = [{"event_id": "hot-evt", "commence_time": "2026-09-01T20:00:00Z",
               "home_team": "New York Mets", "away_team": "Miami Marlins"}]
        _write_rotated_store(self.path, archived_rows=archived, hot_rows=hot,
                             first_date="2026-09-01", last_date="2026-09-01")

    def test_events_for_date_includes_the_archived_event(self):
        events = gamekey.events_for_date("2026-09-01", sources=[self.path])
        self.assertEqual(set(events), {"archived-evt", "hot-evt"})


class NonMlbEventsSeesArchivedTags(unittest.TestCase):
    """src.engine.glue.non_mlb_events -- the two-tier (segment + hot)
    cache this incident forced a split cache design for (see glue.py's own
    docstring on why a single whole-file fingerprint cache would have to
    re-scan every archived segment on every hot-file append)."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "odds_multibook.jsonl"
        archived = [{"event_id": "nfl-evt", "sport": "americanfootball_nfl", "book": "fanduel"}]
        hot = [{"event_id": "tennis-evt", "sport": "tennis_wta_singapore_open", "book": "fanduel"}]
        _write_rotated_store(self.path, archived_rows=archived, hot_rows=hot,
                             first_date="2026-09-01", last_date="2026-09-01")

    def test_non_mlb_events_tags_both_the_archived_and_hot_event(self):
        tags = glue.non_mlb_events([self.path])
        self.assertEqual(tags, {"nfl-evt": "americanfootball_nfl",
                                "tennis-evt": "tennis_wta_singapore_open"})

    def test_repeated_calls_use_the_cache_without_losing_archived_tags(self):
        first = glue.non_mlb_events([self.path])
        second = glue.non_mlb_events([self.path])
        self.assertEqual(first, second)
        self.assertIn("nfl-evt", second)


if __name__ == "__main__":
    unittest.main()
