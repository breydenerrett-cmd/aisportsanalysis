"""Every record a customer reads must be the same cohort, or say which.

WHY THIS FILE EXISTS
---------------------
src/report/daily_record.py's `record_strip` was fixed to report FORWARD_TEST
only, and captioned "Our forward-test systems only -- not the null baselines
or the market-reference republishers." That fix was correct and it moved the
customer-visible 30-day figure from -21.79u to +19.71u, because CONTROL and
MARKET_REFERENCE were roughly 90% of measured positions.

Then, on the same screen:

  * two inches below the strip, `ALL SYSTEMS COMBINED` rendered as an
    equal-weight tile with the same large win/loss-coloured UNITS NET and
    RETURN ON UNITS figures -- the pooled number the caption had just
    disowned, with no caption of its own;
  * below that, the Daily Recap gallery printed thirty daily cards computed
    the old pooled way. On 2026-09-05 and 2026-09-06 those cards read
    45-52-2 and 47-40-3 and NOT ONE of those positions came from a system
    anybody is sold -- both days were entirely null baselines and
    market-reference republishers. Same for the 2023 backtest day.

So a reader met "our forward-test systems only", then a pooled headline,
then thirty pooled day cards, and nothing on the page said they were
different things. A losing pooled day reads as our loss; a winning one reads
as our win. Neither is true.
"""

from __future__ import annotations

import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
JS = REPO / "web" / "js"


def _code(name):
    """Comments stripped -- both files now document this incident at length,
    quoting the very figures under test."""
    text = (JS / name).read_text(encoding="utf-8")
    out, in_block = [], False
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("/*"):
            in_block = True
        if in_block:
            if "*/" in s:
                in_block = False
            continue
        if s.startswith("//") or s.startswith("*"):
            continue
        out.append(line)
    return "\n".join(out)


class TheRollupCarriesAPerClassDenominator(unittest.TestCase):
    """The gallery could not show the forward-test slice because by_class
    had no stake count to divide by."""

    def test_by_class_buckets_carry_units_staked(self):
        from src.report import daily_record as dr
        source = Path(dr.__file__).read_text(encoding="utf-8")
        self.assertIn('"units_staked": 0.0', source,
                      "by_class buckets have no denominator, so no caller "
                      "can compute a per-class return")

    def test_the_gallery_payload_forwards_by_class(self):
        from src.report import daily_record as dr
        source = Path(dr.__file__).read_text(encoding="utf-8")
        code = "\n".join(l for l in source.splitlines()
                         if not l.lstrip().startswith("#"))
        self.assertIn('"by_class": r["by_class"]', code,
                      "the daily gallery payload drops by_class, leaving the "
                      "client nothing to render but the pooled figures")


class TheGalleryNeverShowsAPooledRecordAsOurs(unittest.TestCase):

    def setUp(self):
        self.code = _code("dayrecap.js")

    def test_it_reads_the_forward_test_slice(self):
        self.assertIn("FORWARD_TEST", self.code,
                      "the day card still renders the pooled figures")

    def test_a_day_with_no_forward_test_settlements_shows_no_record(self):
        """The worst case, and the one that was live: falling back to pooled
        here put a 45-52-2 in front of a reader when zero of those positions
        were ours."""
        self.assertIn("No forward-test positions settled", self.code,
                      "a day with no forward-test settlements falls back to "
                      "the pooled record instead of saying there is none")

    def test_every_rendered_record_states_its_cohort(self):
        self.assertIn("day-record-cohort", self.code,
                      "the day card prints a record with no cohort label")


class ThePerformanceScreenHasOneHeadline(unittest.TestCase):

    def setUp(self):
        self.code = _code("performance.js")

    def test_the_summary_block_has_a_single_tile(self):
        """ALL SYSTEMS COMBINED must not sit beside FORWARD-TEST SYSTEM at
        equal weight. It belongs with the other per-class rollups."""
        summary = self.code.split("function renderSummaryTiles", 1)
        self.assertEqual(2, len(summary), "renderSummaryTiles not found")
        block = summary[1].split("\n}", 1)[0]
        self.assertIn("FORWARD-TEST SYSTEM", block)
        self.assertNotIn("classes.ALL", block,
                         "the pooled rollup is still a headline tile beside "
                         "the forward-test one")

    def test_the_headline_states_its_cohort(self):
        self.assertIn("performance-summary-note", self.code,
                      "the headline tile carries no caption saying which "
                      "systems it counts")

    def test_the_pooled_rollup_is_still_reported_somewhere(self):
        """Removing it entirely would be its own dishonesty -- it is the
        check that the measurement works."""
        self.assertIn('"data-class": "ALL"', self.code,
                      "ALL SYSTEMS COMBINED was dropped rather than moved; "
                      "it belongs in the research section")


if __name__ == "__main__":
    unittest.main()
