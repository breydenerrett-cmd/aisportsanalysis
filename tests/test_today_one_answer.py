"""The Today screen must give ONE answer to "what should I bet tonight".

WHY THIS FILE EXISTS
---------------------
Scrolling #/today on 2026-09-09, a customer read, in this order:

  1. TONIGHT'S PICKS -- the ranked slip, "where our systems currently see
     the strongest case"
  2. the hero: NO DEMONSTRATED EDGE ·
     "WE CHECKED THE SLATE. NOTHING CLEARS THE BAR."
  3. THE PRICE BOARD (then called TOP OPPORTUNITIES), whose top card was
     labelled TOP PLAY

Three answers to the same question, in one scroll, each individually
defensible and each carrying its own careful disclaimer. A reader does not
reconcile that; they pick the half they like. Jacob picked TOP PLAY -- a
string the frontend invented, ranking price gap, which src/analysis/
opportunities.py says outright is "not a ranking by expected value, not a
model's picks, not a prediction of who wins" -- and told Brey the system had
called a great bet.

None of this was a bug in any function. Every block worked. The page as a
whole was incoherent, and no test read the page as a whole.

These tests read the source the way a customer reads the screen: what claims
can appear at the same time.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
JS = REPO / "web" / "js"


def _code(name):
    """A module's source with comments stripped.

    Every one of these files documents the failure it fixed, at length, in
    prose that repeats the exact strings under test. Matching raw text would
    pass on the documentation -- the same trap tests/test_cadence_is_deployed
    fell into and now warns about.
    """
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


class ThePriceBoardIsNotAPickList(unittest.TestCase):

    def test_no_top_play_label(self):
        """The label that misled a real reader. It was invented in the client
        and existed nowhere in the payload."""
        self.assertNotIn(
            "TOP PLAY", _code("opportunities.js"),
            "the price board is labelling its top row TOP PLAY again; it "
            "ranks value_points, which src/analysis/priceverdict.py defines "
            "as execution quality, and says nothing about who wins")

    def test_no_pick_language_in_any_heading_it_renders(self):
        code = _code("opportunities.js")
        for phrase in ("TOP OPPORTUNITIES", "BEST BETS", "TOP PICK",
                       "BEST BET", "PLAY OF THE"):
            self.assertNotIn(phrase, code,
                             f"{phrase!r} reads as a pick list on a surface "
                             f"that ranks price, not case strength")

    def test_the_gap_is_not_described_against_a_true_or_fair_price(self):
        """"better than fair" says the market is wrong and we know the right
        number. tests/test_customer_language.py bans exactly that register on
        the Python side; the JS list was weaker, which is how it shipped."""
        code = _code("valuemeter.js")
        self.assertNotIn("than fair", code)
        self.assertNotIn("at fair", code)


class TheHeroNeverContradictsTheSlip(unittest.TestCase):

    def setUp(self):
        self.code = _code("today.js")

    def test_the_no_play_headline_is_conditional_on_the_slip(self):
        """"Nothing clears the bar" is a claim about src/engine/slip.py's
        evidence threshold. When the slip published picks, things cleared it,
        so the sentence is false -- not merely awkward next to them."""
        self.assertIn("hasPicks", self.code,
                      "heroNoPlay does not know whether the slip spoke, so it "
                      "will state NOTHING CLEARS THE BAR directly beneath a "
                      "list of picks")
        headline = "WE CHECKED THE SLATE. NOTHING CLEARS THE BAR."
        self.assertIn(headline, self.code, "the honest empty-night headline "
                                           "should still exist")
        # It must sit inside a branch, not unconditionally.
        before = self.code.split(headline, 1)[0]
        self.assertIn("if (hasPicks)", before,
                      "the empty-night headline is not guarded by the "
                      "has-picks branch")

    def test_the_hero_is_told_whether_picks_rendered(self):
        self.assertTrue(
            re.search(r"renderHero\([^)]*Boolean\(picksBlock\)", self.code),
            "renderToday does not pass the picks state into renderHero")

    def test_no_demonstrated_edge_survives_both_branches(self):
        """The standing truth about this product. Publishing a pick is not a
        claim of edge, and the chip must not quietly disappear on the nights
        we do publish -- that would be the contradiction running the other
        way."""
        self.assertEqual(
            1, self.code.count('verdictChip("NO DEMONSTRATED EDGE"'),
            "NO DEMONSTRATED EDGE should be stated once, before the branch, "
            "so it cannot be dropped on a night with picks")


class NoFalseAffordances(unittest.TestCase):

    def setUp(self):
        self.code = _code("today.js")

    def test_no_swipe_promise_without_a_carousel(self):
        """renderFeaturedSection creates one slot and one card is appended to
        it. .gv2-featured__slot has no overflow, no scroll-snap and no
        handler. A control that does nothing when touched reads as a broken
        app -- and on mobile a reader will actually try it."""
        self.assertNotIn("SWIPE", self.code.upper(),
                         "the featured section promises a swipe again; there "
                         "is still only one card and no carousel")

    def test_hero_actions_always_receive_the_date(self):
        """heroActions(date) builds #/betcheck?date= and #/odds/. Called with
        no argument -- as it was at both live call sites -- the date collapses
        to empty and both fall back to the browser's own today, which is the
        WRONG slate after ~8pm ET, exactly when this screen is already showing
        its own next-slate banner."""
        bare = re.findall(r"heroActions\(\s*\)", self.code)
        self.assertEqual([], bare,
                         "heroActions() is called with no date, so the hero's "
                         "primary CTAs will silently target the wrong slate "
                         "after the rollover")


if __name__ == "__main__":
    unittest.main()
