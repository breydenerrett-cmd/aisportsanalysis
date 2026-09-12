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

UPDATED AGAIN 2026-09-12 (docs/DECISION_TODAY_ONE_ANSWER.md, options A1+B1,
owner-approved). THE CARD leading the screen did not retire the OTHER two
answers this file's own header names -- TONIGHT'S PICKS (the slip) still
rendered below the card, and the hero still led with a price-gap pick
(`chooseGapCandidate`) that neither the card nor the slip had chosen. Two
checks, not fixed the first time:

  - the slip moved OFF Today entirely, to #/performance under a heading
    that says plainly it is research (`web/js/slip.js`'s
    `renderTonightsPicks`, now called from performance.js, not today.js);
  - the hero's featured game is now THE CARD's own #1 pick (or, absent a
    card, the earliest first pitch) -- `chooseGapCandidate` is deleted.

`ThePriceGapRuleIsGone` and `TheSlipIsNotOnToday` below are the tests that
would have caught the first pass calling itself done while both of those
were still true.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from src.analysis import gamepayload
from src.report import card as card_report

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
        """Still passed. UPDATED 2026-09-12: this used to mean "did the card
        OR the slip speak" -- the slip is gone from this screen entirely now
        (see `TheSlipIsNotOnToday` below), so it means only "did the card",
        which is also the only thing left that could make the hero's job
        purely descriptive."""
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


class TheSlipIsNotOnToday(unittest.TestCase):
    """A1: the slip moved to #/performance. This screen must not mount it,
    define it, or import the module it now lives in."""

    def setUp(self):
        self.code = _code("today.js")

    def test_today_does_not_mount_the_tonights_picks_hook(self):
        self.assertNotIn("tonights-picks", self.code,
                         "today.js still mounts data-hook=\"tonights-picks\" -- "
                         "the slip belongs on #/performance now")
        self.assertNotIn("tonights-pick", self.code,
                         "today.js still renders individual slip pick cards")

    def test_today_no_longer_imports_or_defines_the_slip_renderer(self):
        self.assertNotIn('from "./slip.js"', self.code)
        self.assertNotRegex(self.code, r"\bfunction\s+renderTonightsPicks\s*\(",
                            "today.js must not keep its own copy of the slip renderer")

    def test_today_js_reads_no_slip_field_from_the_today_payload(self):
        self.assertNotIn("today.slip", self.code)


class ThePriceGapRuleIsGone(unittest.TestCase):
    """B1: the hero leads with THE CARD's own #1 pick, never a price-gap
    computation. `chooseGapCandidate` and its exclusive helpers are deleted
    outright, not left dormant for something to call again by accident."""

    def setUp(self):
        self.code = _code("today.js")

    def test_choose_gap_candidate_is_deleted(self):
        self.assertNotRegex(self.code, r"\bfunction\s+chooseGapCandidate\s*\(")
        self.assertNotIn("chooseGapCandidate(", self.code)

    def test_its_exclusive_price_gap_math_is_deleted_too(self):
        # pointsBetter/impliedShare existed only to feed chooseGapCandidate;
        # bestOn survives (priceContextPanel and the slate rail still use
        # it to show a real price, which is a different thing from CHOOSING
        # the hero by a gap) so it is deliberately not asserted gone here.
        for name in ("pointsBetter", "impliedShare"):
            self.assertNotRegex(self.code, rf"\bfunction\s+{name}\s*\(",
                                f"{name} survives with no caller left")

    def test_the_hero_row_is_the_cards_first_pick(self):
        """renderToday must read `cardResult.firstPick`'s `game_id` and use
        it to choose the featured row -- not a `gap` field anywhere."""
        body_at = self.code.find("export async function renderToday")
        self.assertNotEqual(-1, body_at, "renderToday is gone")
        body = self.code[body_at:]
        self.assertIn("cardResult.firstPick", body,
                      "renderToday never reads the card's own #1 pick")
        self.assertIn("cardResult.rendered", body,
                      "renderToday never reads whether the card rendered")
        # The featured object must not carry a real gap value forward --
        # the price-gap rule computed one; the card-first-pick rule never
        # does, so this must stay a literal null everywhere it is built.
        self.assertNotRegex(body, r"gap:\s*(?!null)\S")

    def test_the_card_is_read_before_the_hero_is_chosen(self):
        """Order matters: `renderCard`'s return value is what the hero
        selection now depends on, so the await must land first."""
        body_at = self.code.find("export async function renderToday")
        body = self.code[body_at:]
        card_at = body.find("await renderCard(host, date)")
        first_pick_at = body.find("cardResult.firstPick")
        self.assertNotEqual(-1, card_at)
        self.assertNotEqual(-1, first_pick_at)
        self.assertLess(card_at, first_pick_at,
                        "the hero's featured row is chosen before the card "
                        "that is supposed to supply it has been read")


class TheHeroReadsTheCardPicksOwnSide(unittest.TestCase):
    """B1's hero features THE CARD's #1 pick's GAME -- but a game has two
    sides, and the card's pick is a bet on exactly one of them
    (card_ledger.FROZEN_FIELDS includes "side"). Checker finding,
    2026-09-12: the hero threaded that game through but not the side, so
    every price panel under the hero showed a hardcoded "away" moneyline
    regardless of which side the card's #1 pick actually named -- the
    wrong side of the bet the reader was just told to make, when the pick
    was on the home side."""

    def setUp(self):
        self.code = _code("today.js")

    def test_the_featured_object_reads_the_cards_own_side(self):
        # `featured.side` must come from `cardResult.firstPick.side`, not
        # a literal null (the retired rule's vestige) or a literal "away"
        # (which would just move the same bug one line up).
        body_at = self.code.find("export async function renderToday")
        body = self.code[body_at:]
        self.assertIn("cardResult.firstPick.side", body,
                      "the featured row's side is never read off the "
                      "card's own #1 pick")
        self.assertNotRegex(body, r"side:\s*null\s*,\s*gap:\s*null",
                            "featured.side is still hardcoded null, the "
                            "vestige of the deleted price-gap rule")

    def test_heronoplay_and_herofagged_take_a_real_side_not_a_hardcoded_one(self):
        # Both hero builders must accept `side` as a parameter and pass it
        # (or a stated, commented fallback) into priceContextPanel -- never
        # the bare string "away" standing in for "whatever side the pick
        # names", which is only ever right by accident.
        self.assertRegex(self.code, r"function\s+heroNoPlay\(\s*row\s*,\s*side\b",
                         "heroNoPlay no longer takes a side parameter")
        self.assertRegex(self.code, r"function\s+heroFlagged\(\s*row\s*,\s*side\b",
                         "heroFlagged no longer takes a side parameter")
        # The hardcoded away-side price panel this finding was filed
        # against must be gone.
        self.assertNotIn('priceContextPanel(row, "away", h2h, null)', self.code)
        self.assertNotIn('priceContextPanel(row, "away", h2h)', self.code)


class ThePriceGapPillIsFullyDeleted(unittest.TestCase):
    """B1 retired the price-gap rule for good (`ThePriceGapRuleIsGone`
    above). Checker finding, 2026-09-12: the pill that RENDERED a gap --
    "N PTS BETTER · best price vs. the fair price" -- survived as dormant
    markup in priceContextPanel, one non-null `gap` argument away from
    printing again. `gap` must not exist as a parameter anywhere in this
    file any more, not just always be called with null."""

    def setUp(self):
        self.code = _code("today.js")

    def test_no_function_in_this_file_takes_a_gap_parameter(self):
        self.assertNotRegex(self.code, r"\(\s*[\w, ]*\bgap\b[\w, ]*\)",
                            "a function here still accepts a gap parameter "
                            "-- the retired pill can render again with one "
                            "non-null value passed to it")

    def test_the_points_better_pill_markup_is_gone(self):
        self.assertNotIn("gameday-points-better", self.code)
        self.assertNotIn("PTS BETTER", self.code)


class TheHeroJoinKeyMatchesTheSlateRows(unittest.TestCase):
    """B1's join is silent, not loud: today.js matches
    `cardResult.firstPick.game_id` against `/games/{date}` rows by string
    equality (see `ThePriceGapRuleIsGone.test_the_hero_row_is_the_cards_
    first_pick` above) and falls back to the earliest first pitch, with no
    signal on screen, when nothing matches. That fallback is meant for
    "the pick's game genuinely is not on tonight's slate" -- not for "the
    two id builders spelled the same game differently".

    Checker finding, 2026-09-12: the two builders are
    `src/report/card.py::_game_identity` (which the served card's
    `game_id` comes from) and `src/analysis/gamepayload.py::game_id`
    (which `/games/{date}` rows use, per test_gamepayload.py). They build
    the id from the same fields by two different, independently-maintained
    format strings, and agree only because both treat `game_number` the
    same way. Nothing enforced that before this test -- a change to either
    format string, made without knowing about the other, would silently
    break the join and this repo would find out from the hero quietly
    reverting to the chronological fallback, on real nights, with no
    failing test anywhere.
    """

    def test_card_and_slate_game_ids_agree_when_game_number_is_set(self):
        # `game_number` set (1, the ordinary single-game case) is the case
        # every published card pick actually carries -- MLB's schedule
        # feed always supplies it, doubleheaders included. This is the
        # case the B1 join depends on every night, so it is the one this
        # test locks down. (The two builders are known to diverge when
        # `game_number` is falsy and gamepayload.py falls back to
        # `game_pk` while card.py falls back to the literal `1` -- see
        # this class's own docstring; that gap is a separate, pre-existing
        # risk this test does not paper over, only refuses to let a second
        # one land on top of unnoticed.)
        date = "2026-08-31"
        away, home, game_pk, game_number = "BOS", "NYY", 880001, 1

        card_entry = {"dossier": {"game": {
            "away_team": away, "home_team": home,
            "game_number": game_number, "game_pk": game_pk,
        }}}
        card_game_id = card_report._game_identity(card_entry, date=date)["game_id"]

        slate_game_id = gamepayload.game_id({
            "away_team": away, "home_team": home, "date": date,
            "game_number": game_number, "game_pk": game_pk,
        })

        self.assertEqual(card_game_id, slate_game_id,
                         "the card's own game_identity and gamepayload's "
                         "game_id disagree on the SAME game -- the B1 hero "
                         "join in today.js would silently miss it and fall "
                         "back to the chronological pick with no signal on "
                         "screen")


if __name__ == "__main__":
    unittest.main()
