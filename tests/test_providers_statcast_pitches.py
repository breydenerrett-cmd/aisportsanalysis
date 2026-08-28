"""Tests for src/providers/statcast_pitches.py iter_rows. No network -- the
store is a temp directory of gzipped windows built by hand.

The strictly-before gate is the point-in-time boundary for every rebuilt
feature, so it must hold for every cutoff type a caller can plausibly pass:
dates, ISO strings, and datetimes (dossier information_times are datetimes).
"""

import gzip
import json
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path

from src.providers import statcast_pitches as sp


def make_store(root, windows):
    """windows: {'start..end': [row, ...]} written the way build() writes."""
    manifest = {"windows": {}}
    for key, rows in windows.items():
        name = f"pitches_{key}.jsonl.gz"
        with gzip.open(Path(root) / name, "wt", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row) + "\n")
        manifest["windows"][key] = {"rows": len(rows), "file": name}
    (Path(root) / "manifest.json").write_text(json.dumps(manifest),
                                              encoding="utf-8")


class TestIterRowsCutoff(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.store = self._tmp.name
        make_store(self.store, {
            "2023-04-02..2023-04-05": [
                {"game_date": "2023-04-04", "game_pk": 1},
                {"game_date": "2023-04-05", "game_pk": 2},
            ],
        })

    def tearDown(self):
        self._tmp.cleanup()

    def dates(self, before):
        return [r["game_date"] for r in sp.iter_rows(self.store, before=before)]

    def test_date_cutoff_excludes_the_cutoff_day(self):
        self.assertEqual(self.dates(date(2023, 4, 5)), ["2023-04-04"])

    def test_string_cutoff_excludes_the_cutoff_day(self):
        self.assertEqual(self.dates("2023-04-05"), ["2023-04-04"])

    def test_datetime_cutoff_excludes_the_cutoff_day(self):
        # str(datetime) is 'YYYY-MM-DD 00:00:00', which sorts after the bare
        # date; without normalization the cutoff day's own pitches leak in.
        self.assertEqual(self.dates(datetime(2023, 4, 5)), ["2023-04-04"])

    def test_datetime_with_game_time_still_excludes_the_whole_day(self):
        # A first-pitch information_time is mid-day; the gate is day-granular
        # and must still exclude every pitch from that calendar day.
        self.assertEqual(self.dates(datetime(2023, 4, 5, 19, 5)), ["2023-04-04"])

    def test_no_cutoff_yields_everything(self):
        self.assertEqual(self.dates(None), ["2023-04-04", "2023-04-05"])


if __name__ == "__main__":
    unittest.main()
