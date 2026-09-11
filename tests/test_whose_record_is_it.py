"""Two records exist. A reader must never be shown the wrong one as ours.

THE TWO
-------
THE CARD's record (`/card/record`, `#/record-card`) -- the three-to-five bets
this product publishes each day, frozen before first pitch and graded after.
On 2026-09-10 that was one day: 2-1, +0.54u.

THE FORWARD-TEST SYSTEMS' record (`/record`, `#/performance`) -- hundreds of
paper positions from the detector research, a different selection rule
entirely. On the same day it read 143-97-3, +47.48u, +19.8%.

Both are real. Only the first is the product.

WHY THIS FILE EXISTS
--------------------
The wrong one was shown as ours in THREE separate places, found in one
evening, each shipped by someone reasonable:

  1. #/today mounted the /record strip directly above TONIGHT'S CARD, so
     "+19.8%" sat immediately over three published picks.
  2. The RESULTS tab in the main nav pointed at #/performance -- the nav
     label IS the question "did your picks win?", answered with another
     system's numbers.
  3. #/performance itself opened on the figures with the distinction in
     small type underneath them.

Every one had an honest caption somewhere. Captions did not work, three times
running, because a reader takes the big number and the nearest heading. So
the rule is structural rather than editorial, and it is tested.

THE RULE
--------
A surface that shows THE CARD shows THE CARD's record. The research record
lives on the research page and says so before it says a number.
"""

from __future__ import annotations

import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JS = os.path.join(ROOT, "web", "js")


def _code(name):
    """Source with comments stripped -- these files document this very bug at
    length, quoting the strings under test."""
    with open(os.path.join(JS, name), encoding="utf-8") as fh:
        text = fh.read()
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


class ThePicksPageShowsThePicksRecord(unittest.TestCase):

    def setUp(self):
        self.today = _code("today.js")

    def test_it_mounts_the_card_record_strip(self):
        self.assertIn("renderCardRecordStrip", self.today)

    def test_it_does_not_mount_the_forward_test_strip(self):
        """THE ONE THAT SHIPPED. `renderRecordStrip` reads /record -- the
        research systems' paper standings -- and putting it above the card
        credits their +19.8% to our three picks."""
        self.assertNotRegex(
            self.today, r"\brenderRecordStrip\b",
            "the picks page is mounting the forward-test record strip again; "
            "use renderCardRecordStrip, which reads /card/record")


class TheResultsTabAnswersTheQuestionItAsks(unittest.TestCase):

    def test_results_points_at_the_cards_record(self):
        main = _code("main.js")
        match = re.search(
            r"\{\s*hash:\s*\"([^\"]+)\"\s*,\s*label:\s*\"RESULTS\"", main)
        self.assertIsNotNone(match, "no RESULTS item in the nav table")
        self.assertEqual(
            match.group(1), "#/record-card",
            "RESULTS points somewhere other than the card's record. A reader "
            "tapping RESULTS is asking whether OUR PICKS won.")


class TheResearchPageSaysSoBeforeItSaysANumber(unittest.TestCase):

    def setUp(self):
        self.perf = _code("performance.js")

    def test_it_carries_a_scope_banner(self):
        self.assertIn("performance-scope", self.perf,
                      "#/performance no longer states whose numbers it is "
                      "showing before it shows them")

    def test_the_banner_is_rendered_before_the_record_strip(self):
        """Order is the whole point. Underneath, it is a caption -- and a
        caption is what failed three times.

        Anchored on the CALL, not on any occurrence of the name: the first
        version of this test matched the import at the top of the file and
        failed against correct code.
        """
        scope = self.perf.find("performance-scope")
        call = re.search(r"await\s+renderRecordStrip\s*\(", self.perf)
        self.assertNotEqual(scope, -1, "no scope banner in performance.js")
        self.assertIsNotNone(call, "renderRecordStrip is never called")
        self.assertLess(scope, call.start(),
                        "the scope banner is rendered after the numbers it "
                        "is supposed to qualify")

    def test_it_links_to_the_cards_record(self):
        self.assertIn("#/record-card", self.perf,
                      "a reader who realises these are not the picks has "
                      "nowhere to go for the ones that are")


class TheCardRecordStripIsHonestWhenEmpty(unittest.TestCase):
    """An empty record is the normal state on day one and must not borrow a
    number from anywhere to avoid looking bare."""

    def setUp(self):
        self.strip = _code("recordstrip.js")

    def test_the_card_strip_reads_the_card_endpoint(self):
        block = self.strip.split("renderCardRecordStrip", 1)[-1]
        block = block.split("export async function renderRecordStrip", 1)[0]
        self.assertIn("/card/record", block)
        self.assertNotIn('apiGet("/record")', block,
                         "the card strip is reading the research endpoint")

    def test_no_graded_cards_is_stated_not_hidden(self):
        self.assertIn("No graded cards yet", self.strip)


if __name__ == "__main__":
    unittest.main()
