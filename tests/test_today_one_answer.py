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

UPDATED 2026-09-10, and the update is a reversal worth naming. The first fix
made the hero's verdict CONDITIONAL, so it could not contradict the slip.
`TheHeroNeverContradictsTheSlip` enforced that, and two of its tests
required the hero to carry NO DEMONSTRATED EDGE and to branch its headline.

What shipped instead was THE CARD at the top of the screen, which answers
the question outright. The hero below it therefore states no verdict at all,
and those two tests now assert the opposite of what they used to. A page
with one answer needs no rule about which of its answers wins.
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

    def test_the_price_board_view_is_gone(self):
        """opportunities.js -- the board ranked by value points, whose top
        row was labelled TOP PLAY and misled a real reader -- was deleted on
        2026-09-12 with the rest of the price-comparison register. Nothing
        routes to it and nothing may bring it back under the same name."""
        self.assertFalse((JS / "opportunities.js").exists())
        self.assertNotIn("opportunities.js", _code("main.js"))

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

    def test_the_hero_states_no_verdict_at_all(self):
        """SUPERSEDES two tests, 2026-09-10.

        This class used to require the opposite of what it requires now, and
        the change is worth recording rather than quietly rewriting.

        The old design had the hero carry the verdict: a standing
        NO DEMONSTRATED EDGE chip, and a headline that branched between
        "TONIGHT'S PICKS ARE ABOVE" and "WE CHECKED THE SLATE. NOTHING CLEARS
        THE BAR." Two tests here enforced exactly that, and both were right
        about the problem they were written for -- the hero must not
        contradict the slip.

        The fix they encoded was to make the contradiction conditional. The
        fix that shipped instead removes the competition: THE CARD answers
        "what should I bet tonight" at the top of the screen, so the hero
        below it has no verdict to state and states none. A page with one
        answer needs no rule about which of its two answers wins.

        The banned strings themselves are enforced repo-wide by
        tests/test_no_nothing_clears_the_bar.py. What this test guards is the
        structural property: the hero renders no verdict word of its own.
        """
        for phrase in ("NOTHING CLEARS THE BAR", "NO DEMONSTRATED EDGE",
                       "WE CHECKED THE SLATE"):
            self.assertNotIn(phrase, self.code,
                             f"the hero still renders {phrase!r}")

    def test_the_card_renders_above_the_hero(self):
        """Order is the whole point. A reader who reads exactly one thing on
        this screen must read a bet, not a description of the board."""
        # Scoped to renderToday's BODY. Searching the whole module would find
        # `function renderHero(...)`'s definition, which sits above every
        # call site and would make this test pass or fail on where the
        # helpers happen to be declared rather than on render order.
        body_at = self.code.find("export async function renderToday")
        self.assertNotEqual(-1, body_at, "renderToday is gone")
        body = self.code[body_at:]
        card_at = body.find("renderCard(host, date)")
        hero_at = body.find("renderHero(host,")
        self.assertNotEqual(-1, card_at, "renderToday never mounts the card")
        self.assertNotEqual(-1, hero_at, "renderToday never mounts the hero")
        self.assertLess(card_at, hero_at,
                        "the hero mounts before the card, so the first thing "
                        "on the screen is context rather than an answer")

    def test_the_hero_is_told_whether_anything_answered_the_question(self):
        """Still passed, and now it means "did the card OR the slip speak" --
        either one makes the hero's job purely descriptive."""
        self.assertTrue(
            re.search(r"renderHero\((?:.|\n)*?hasCard", self.code),
            "renderToday does not tell renderHero whether the card rendered")


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
