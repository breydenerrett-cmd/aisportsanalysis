"""FRONTEND fix for the live contradiction on #/today, staging 2026-09-12
~16:00Z: the card's #1 pick was "Take Red Sox to win at -212 ... best of 11
books" for KC at BOS, and the Today hero directly under it for the SAME
game read "MARKET UNAVAILABLE ... NO PRICE BOARD RECORDED FOR THIS GAME"
with a paragraph claiming "Either no book posted this game at capture time,
or the club name did not match this product's map". GET /games/2026-09-12
showed board_summary {books: 11, has_board: true} for that exact row --
eleven books WERE quoting, so that paragraph was false on its face.

ROOT CAUSE (backend, out of this mission's scope): dossier["market"] is
only ever filled from a live odds fetch the API path never runs, so every
row misses "market" regardless of whether a real board exists. The full
multibook board lives on board_summary/price_board instead. A candidate
routed to a market the board does not carry (e.g. first-five when the
board is full-game h2h only) legitimately has no routed price even with a
real board on file -- that is a ROUTING gap, not a CAPTURE gap, and the
copy must say which one actually happened.

THIS MISSION: web/js/today.js's heroMarketUnavailable must branch on
row.board_summary.has_board --
  - has_board true: headline "THE PRICE THIS GAME NEEDS IS NOT ON OUR
    BOARD.", body from row.verdict_reason when present else a routing
    explanation in plain English. The old "Nothing is broken... did not
    match this product's map" paragraph and "NO PRICE BOARD RECORDED FOR
    THIS GAME." headline must NOT be reachable here -- they are false when
    a board is on file.
  - has_board false: keep the old headline/paragraph (true in that state),
    minus the trailing "there is no reason field distinguishing the two"
    clause -- a reason field now exists (row.verdict_reason,
    src/analysis/gamepayload.py:266) and this same function prints it three
    lines below in the WHY row, so that clause was no longer true.
  - the WHAT WE HOLD box's WHY row reads row.verdict_reason || gaps.market
    || "no reason recorded" in both states.

REVISION 2026-09-12 (checker pass): the first draft of this file and of
today.js had three problems, fixed together here --
  1. The has_board-false paragraph still carried the "there is no reason
     field" clause even though row.verdict_reason exists and is printed by
     this same function -- self-contradiction on one screen. Dropped.
  2. The has_board-true body was written as
     `text: row.verdict_reason ? row.verdict_reason : "<fallback>"` --
     `text:` was followed by an expression, not a quote, so
     tests/test_no_developer_notes_on_screen.py's `_rendered_strings` scan
     (which requires `text:\s*(["'`])`) never saw the fallback string at
     all. NewRenderedCopyStaysOffTheRetiredList below passed while
     checking nothing. today.js now uses an inner `if (row.verdict_reason)
     {...} else { ... text: "<fallback literal>" ... }` so the fallback is
     its own scanned literal -- see test_the_fallback_body_is_a_scanned_
     literal for the coverage that would have caught the blind spot.
  3. The true-branch headline/body were first drafted as "NO PRICE FOR THE
     MARKET THIS GAME WAS ROUTED TO." / "...cleared the talent bar and was
     routed to...", which is the exact retired-engine-note jargon
     web/js/games.js:202-231 (2026-09-10) pulled off the slate page on the
     owner's instruction to write for readers who "have a hard time
     reading English". Rewritten in plain English; today.js:721-734 carries
     the dated note recording that decision for this surface.

Structural scan, the same shape as tests/test_web_v2_gameday.py and
tests/test_web_register_sweep.py: read the function body as text and
assert on what strings sit in which branch. Never starts a server, never
imports a JS engine.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from tests.test_no_developer_notes_on_screen import _rendered_strings
from tests.test_web_register_sweep import RETIRED

ROOT = Path(__file__).resolve().parent.parent
TODAY_PATH = ROOT / "web" / "js" / "today.js"

FALSE_HEADLINE = "NO PRICE BOARD RECORDED FOR THIS GAME."
FALSE_PARAGRAPH_OPEN = "Nothing is broken. Either no book posted"
RETIRED_REASON_FIELD_CLAIM = "there is no reason field"
TRUE_HEADLINE = "THE PRICE THIS GAME NEEDS IS NOT ON OUR BOARD."
TRUE_FALLBACK_BODY = (
    "This game passed our first screen, but the board we hold has no "
    "price for the part of the game it was checked on. The full-game "
    "board is real.")
JARGON_PHRASES = ("talent bar", "routed to", "cleared the talent bar")


def _function_body(text: str, name: str) -> str:
    return text.split(f"function {name}(")[1].split("\nfunction ")[0]


def _matching_close(text: str, open_index: int) -> int:
    """Index of the `}` that closes the `{` at `open_index`, by depth --
    needed because heroMarketUnavailable nests an if/else for
    row.verdict_reason inside the outer `if (bs.has_board) {` branch, so a
    naive first-match split on "} else {" (as a flatter function could use)
    would land on the INNER else, not the outer one."""
    assert text[open_index] == "{"
    depth = 1
    i = open_index + 1
    while depth > 0:
        c = text[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
        i += 1
    return i - 1  # index of the matching "}"


def _branches(body: str):
    """Split heroMarketUnavailable's body on its outer
    `if (bs.has_board) {` conditional -- brace-depth aware so the nested
    `if (row.verdict_reason) { ... } else { ... }` inside the true branch
    does not fool the split. Returns (true_branch, false_branch)."""
    marker = "if (bs.has_board) {"
    start = body.index(marker) + len(marker) - 1  # index of that "{"
    close = _matching_close(body, start)
    true_branch = body[start + 1:close]
    rest = body[close + 1:]
    assert rest.lstrip().startswith("else {"), rest[:40]
    else_open = rest.index("{")
    else_close = _matching_close(rest, else_open)
    false_branch = rest[else_open + 1:else_close]
    return true_branch, false_branch


class HeroMarketUnavailableExists(unittest.TestCase):
    def setUp(self):
        self.text = TODAY_PATH.read_text(encoding="utf-8")
        self.body = _function_body(self.text, "heroMarketUnavailable")

    def test_it_branches_on_board_summary_has_board(self):
        # PRE-FIX: the function had no `if` at all -- one headline, one
        # paragraph, unconditionally, regardless of board_summary. This
        # assertion fails against that code because "if (bs.has_board) {"
        # does not appear in it.
        self.assertIn("const bs = row.board_summary || {};", self.body)
        self.assertIn("if (bs.has_board) {", self.body)

    def test_it_reads_row_verdict_reason(self):
        # PRE-FIX: row.verdict_reason is never read anywhere in this
        # function -- the WHY row reads only gaps.market, and the body
        # paragraph is a hardcoded constant. Fails against that code.
        self.assertIn("row.verdict_reason", self.body)

    def test_the_why_row_falls_back_through_verdict_reason_then_gaps(self):
        self.assertIn(
            'const reason = row.verdict_reason || gaps.market || "no reason recorded";',
            self.body)
        self.assertIn('field("WHY", reason)', self.body)


class TheFalseHasBoardCopyOnlyLivesInTheFalseBranch(unittest.TestCase):
    """PRE-FIX, both FALSE_HEADLINE and FALSE_PARAGRAPH_OPEN rendered
    unconditionally for every market_unavailable row -- including KC-BOS,
    which had an 11-book board on file. Splitting the function on its own
    has_board branch and asserting each string is absent from the
    has_board-true side is what would have caught staging 2026-09-12: it
    fails against the pre-fix body because there is no true branch to be
    absent from (the whole body is one undifferentiated string)."""

    def setUp(self):
        text = TODAY_PATH.read_text(encoding="utf-8")
        body = _function_body(text, "heroMarketUnavailable")
        self.true_branch, self.false_branch = _branches(body)

    def test_no_price_board_recorded_is_false_branch_only(self):
        self.assertIn(FALSE_HEADLINE, self.false_branch)
        self.assertNotIn(FALSE_HEADLINE, self.true_branch)

    def test_nothing_is_broken_paragraph_is_false_branch_only(self):
        self.assertIn(FALSE_PARAGRAPH_OPEN, self.false_branch)
        self.assertNotIn(FALSE_PARAGRAPH_OPEN, self.true_branch)

    def test_the_routed_market_headline_is_true_branch_only(self):
        self.assertIn(TRUE_HEADLINE, self.true_branch)
        self.assertNotIn(TRUE_HEADLINE, self.false_branch)

    def test_the_true_branch_reads_verdict_reason(self):
        self.assertIn("row.verdict_reason", self.true_branch)

    def test_the_false_branch_no_longer_claims_no_reason_field_exists(self):
        # A reason field exists now (row.verdict_reason) and this same
        # function prints it in the WHY row a few lines below -- the old
        # trailing clause ("...since there is no reason field
        # distinguishing the two, it does not guess...") contradicted that.
        # Fails against the pre-checker-pass body, which still had it.
        self.assertNotIn(RETIRED_REASON_FIELD_CLAIM, self.false_branch)


class TheFallbackBodyIsAScannedLiteral(unittest.TestCase):
    """The first draft wrote `text: row.verdict_reason ? row.verdict_reason
    : "<fallback>"` -- `text:` was followed by an expression, not a quote,
    so _rendered_strings (and therefore every register tripwire, including
    NewRenderedCopyStaysOffTheRetiredList below) never saw the fallback
    string. Confirms the fallback now appears as its own `text: "..."`
    literal, and pins exactly which line of today.js it lives on so this
    stops being a blind spot silently."""

    def setUp(self):
        self.pairs = _rendered_strings(TODAY_PATH)

    def test_the_fallback_body_is_among_the_scanned_rendered_strings(self):
        rendered_texts = [text for _line, text in self.pairs]
        self.assertIn(
            TRUE_FALLBACK_BODY, rendered_texts,
            "the has_board-true fallback body is not reaching the "
            "text:\\s*(quote) scanner -- it is an unguarded blind spot "
            "again")

    def test_it_covers_these_specific_today_js_lines(self):
        # Line numbers as of this pass -- 721 is the true-branch headline,
        # 740 is the fallback body literal. Restated here (rather than just
        # asserted-present-somewhere) so a future line shuffle that moved
        # the fallback back behind a ternary would show up as a line-number
        # mismatch instead of quietly losing coverage again.
        covered_lines = {line for line, _text in self.pairs}
        self.assertIn(720, covered_lines)  # true-branch headline
        self.assertIn(740, covered_lines)  # true-branch fallback body


class TheBodyParagraphCarriesItsDataHook(unittest.TestCase):
    def test_gameday_market_gap_reason_hook_present_in_both_branches(self):
        text = TODAY_PATH.read_text(encoding="utf-8")
        body = _function_body(text, "heroMarketUnavailable")
        true_branch, false_branch = _branches(body)
        self.assertIn('"data-hook": "gameday-market-gap-reason"', true_branch)
        self.assertIn('"data-hook": "gameday-market-gap-reason"', false_branch)


class NewRenderedCopyStaysOffTheRetiredList(unittest.TestCase):
    """Every string today.js hands to a reader -- old and new -- must
    still clear the price-comparison register tests/test_web_register_sweep
    retired (test_no_developer_notes_on_screen's own extraction, the same
    one that scan uses on the other lanes). Covers today.js lines 699, 720,
    721, 737, 740, 744, 746, 763, 777, 785, 787 as of this pass (see
    TheFallbackBodyIsAScannedLiteral for confirmation the fallback is
    actually among them, not a vacuous pass)."""

    def test_no_retired_phrase_among_todays_rendered_strings(self):
        offenders = []
        for line_no, rendered in _rendered_strings(TODAY_PATH):
            lowered = rendered.lower()
            for phrase in RETIRED:
                if phrase in lowered:
                    offenders.append(f"today.js:{line_no}: {phrase!r} in {rendered[:70]!r}")
        self.assertEqual(offenders, [])


class TheJargonDecisionIsRecorded(unittest.TestCase):
    """web/js/games.js:202-231 (2026-09-10) is a dated decision that pulled
    "cleared the talent bar" / "routed to" language off a customer screen
    as unreadable jargon. This mission's headline/body do not use that
    jargon (they were rewritten in plain English instead) -- confirm that
    directly, and confirm today.js carries its own dated note in case a
    future edit reintroduces it without recording why."""

    def setUp(self):
        self.text = TODAY_PATH.read_text(encoding="utf-8")
        self.body = _function_body(self.text, "heroMarketUnavailable")

    def test_no_jargon_phrase_is_rendered(self):
        offenders = []
        for line_no, rendered in _rendered_strings(TODAY_PATH):
            lowered = rendered.lower()
            for phrase in JARGON_PHRASES:
                if phrase in lowered:
                    offenders.append(f"today.js:{line_no}: {phrase!r} in {rendered[:70]!r}")
        self.assertEqual(offenders, [])

    def test_the_reversal_is_dated_in_a_comment(self):
        self.assertIn("2026-09-12", self.body)
        self.assertIn("games.js:218-221", self.body)


if __name__ == "__main__":
    unittest.main()
