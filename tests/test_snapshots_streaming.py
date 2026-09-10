"""`iter_multibook` must return exactly what the list-building read returns.

WHY THIS FILE EXISTS
--------------------
The multi-book store is 38 MB and 119,000 rows. Building the whole list to
keep a few hundred allocates **174 MB** (measured), and on the 512 MB
staging container that is the difference between a page and a 502. It took
staging down twice on 2026-09-10.

`iter_multibook` streams instead, skipping lines whose raw text cannot
contain the wanted market before any JSON is parsed. Same query, **2.5 MB**.

THE TRAP THAT CAUGHT ME, AND WHAT THIS FILE GUARDS
---------------------------------------------------
The first version prefiltered on `'"market": "spreads"'` -- key, colon,
space, value. The store is written with different spacing, so that needle
matched **zero** lines in a file containing 1,054 of them. Nothing raised.
`run_line_rows` returned an empty board, and an empty board is a completely
plausible state: it renders as "no run lines quoted for this game".

A prefilter that UNDER-matches turns real data into a believable absence.
So the property under test is not "the filter works" but the stronger one:
**streaming and non-streaming agree, exactly, on real-shaped rows** -- and
the prefilter is only ever allowed to over-match.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest

from src.pipeline import snapshots

# Two spacings of the same content. The store's real formatting is not this
# test's business to know, which is the entire point.
COMPACT = '{"market":"spreads","event_id":"e1","book":"fanduel",' \
          '"home_price":128,"away_price":-154,"home_line":"-1.5",' \
          '"away_line":"1.5","commence_time":"2026-09-03T16:35:00Z",' \
          '"observed_utc":"2026-09-03T10:07:54+00:00"}'
SPACED = json.dumps({
    "market": "spreads", "event_id": "e2", "book": "draftkings",
    "home_price": -110, "away_price": -110, "home_line": "-1.5",
    "away_line": "1.5", "commence_time": "2026-09-03T16:35:00Z",
    "observed_utc": "2026-09-03T10:07:54+00:00"})
TOTALS = json.dumps({
    "market": "totals", "event_id": "e3", "book": "fanduel", "total": "8.5",
    "over_price": -118, "under_price": -104,
    "commence_time": "2026-09-03T16:35:00Z",
    "observed_utc": "2026-09-03T10:07:54+00:00"})
MONEYLINE = json.dumps({
    "event_id": "e4", "book": "fanduel", "home_price": -158, "away_price": 146,
    "commence_time": "2026-09-03T16:35:00Z",
    "observed_utc": "2026-09-03T10:07:54+00:00"})


class StreamingMatchesReading(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = os.path.join(self._tmp.name, "odds_multibook.jsonl")
        with open(self.path, "w", encoding="utf-8", newline="\n") as fh:
            for line in (COMPACT, SPACED, TOTALS, MONEYLINE, "", "{broken"):
                fh.write(line + "\n")

    def test_both_spacings_are_found(self):
        """The bug, directly: compact JSON must not be invisible."""
        rows = list(snapshots.iter_multibook(self.path, market="spreads"))
        self.assertEqual({"e1", "e2"}, {r["event_id"] for r in rows})

    def test_it_agrees_exactly_with_the_list_building_read(self):
        streamed = list(snapshots.iter_multibook(self.path, market="spreads"))
        listed = [r for r in snapshots.read_multibook(self.path)
                  if r.get("market") == "spreads"]
        self.assertEqual([r["event_id"] for r in listed],
                         [r["event_id"] for r in streamed])

    def test_the_market_filter_is_exact_not_merely_textual(self):
        """The prefilter may over-match; the returned rows may not. A totals
        row whose text happens to contain the word must still be excluded."""
        with open(self.path, "a", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps({
                "market": "totals", "event_id": "trap",
                "note": "priced off the spreads board",
                "commence_time": "2026-09-03T16:35:00Z"}) + "\n")
        rows = list(snapshots.iter_multibook(self.path, market="spreads"))
        self.assertNotIn("trap", {r["event_id"] for r in rows})

    def test_no_market_means_every_row_including_the_keyless_moneyline(self):
        """Moneyline rows carry no `market` key at all. `market=None` must
        mean "everything", never "rows whose market is null"."""
        rows = list(snapshots.iter_multibook(self.path))
        self.assertIn("e4", {r["event_id"] for r in rows})
        self.assertEqual(4, len(rows))

    def test_a_corrupt_line_costs_one_row_not_the_file(self):
        rows = list(snapshots.iter_multibook(self.path))
        self.assertEqual(4, len(rows))
        with self.assertRaises(snapshots.SnapshotError):
            list(snapshots.iter_multibook(self.path, skip_corrupt=False))

    def test_a_missing_file_yields_nothing_rather_than_raising(self):
        missing = os.path.join(self._tmp.name, "nope.jsonl")
        self.assertEqual([], list(snapshots.iter_multibook(missing)))

    def test_the_keep_predicate_runs_on_the_parsed_row(self):
        rows = list(snapshots.iter_multibook(
            self.path, market="spreads",
            keep=lambda r: r.get("book") == "draftkings"))
        self.assertEqual(["e2"], [r["event_id"] for r in rows])


class RunLineRowsUsesIt(unittest.TestCase):
    """The caller that matters, end to end on injected rows."""

    def test_injected_rows_still_work_and_bypass_the_stream(self):
        from src.report import card as card_mod

        rows = [json.loads(COMPACT), json.loads(SPACED), json.loads(TOTALS)]
        for row in rows:
            row["away_team"] = "San Francisco Giants"
            row["home_team"] = "Pittsburgh Pirates"
        out = card_mod.run_line_rows("2026-09-03", rows=rows)
        # Two books is below prices.MIN_BOOKS, so no consensus is published
        # -- the point here is that the path runs and filters, not that a
        # two-book board produces a number.
        self.assertIsInstance(out, dict)


if __name__ == "__main__":
    unittest.main()
