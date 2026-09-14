"""THE MERGED CARD -- "TODAY'S BETS" (web/js/card.js), 2026-09-14.

The owner's note today, verbatim in substance: "merge the today bets for
ALL BETS not just MLs include all best bets like player props." This is the
new track's own test module for that merge -- structural, plain-text scans
of the source, the same shape as tests/test_web_card_props.py (there is no
JS runtime in this repo's test suite, so every assertion here is either a
literal string that must appear, or a slice of a function body checked for
the shape it must have).

FOUR DEFECTS, FOUND BY AN OPUS CHECKER READING THE FIRST VERSION OF THIS
FILE, dated 2026-09-14 -- each class below is named for the one it guards
against, and each test is written so it would have FAILED against that
first version:

  1. The merged sub-line named totals and player props unconditionally,
     even over a card with neither (today's own: five moneylines, zero
     totals, zero props -- no lineup has posted) -- and the reason props
     are missing (`payload.prop_reason`) disappeared under the merged
     branch entirely.
  2. LINEUP NOT POSTED was a trailing chip, appended LAST in `.card2__top`,
     11px -- the smallest text on the card -- and one more flex item the
     row's own wrap could drop onto a second line and lose.
  3. The page still decided "is there anything on this card" from
     `payload.picks` alone, so a card with real bets in `all_bets` but zero
     game picks was walked back to yesterday's card or `emptyCard`.
  4. The section count and every "N OF M" were taken from the raw
     `all_bets` array, unresolved entries included, while the render loop
     silently skipped any entry it could not resolve -- a gap in the
     numbering where the dropped entry used to be, and a game pick and a
     prop able to both show "1 OF 8".
"""

from __future__ import annotations

import unittest
from pathlib import Path

from tests.test_customer_language import _violations_in
from tests.test_no_developer_notes_on_screen import _rendered_strings
from tests.test_web_register_sweep import RETIRED

ROOT = Path(__file__).resolve().parent.parent
JS = ROOT / "web" / "js"
CSS = ROOT / "web" / "css" / "card.css"


def _read(name: str) -> str:
    return (JS / name).read_text(encoding="utf-8")


def _function_body(text: str, signature: str) -> str:
    """Same slicing convention as test_web_card_props.py's own helper: from
    the signature to the next line that starts a new top-level
    declaration."""
    after = text.split(signature, 1)[1]
    for marker in ("\nfunction ", "\nexport function ", "\nexport async function "):
        after = after.split(marker)[0]
    return after


class Card(unittest.TestCase):
    def setUp(self):
        self.text = _read("card.js")


# ---------------------------------------------------------------------------
# DEFECT 1 -- the sub-line named kinds that were not on the card, and the
# prop_reason line disappeared.
# ---------------------------------------------------------------------------

class TheSubLineNamesOnlyWhatIsActuallyOnTheCard(Card):
    def test_the_headline_function_takes_the_kinds_actually_present(self):
        """The first version took only a count: `allBetsSectionHead(count)`.
        A second argument naming what is actually rendered is the whole
        fix -- a signature scan this simple would have failed outright
        against that version."""
        self.assertIn("function allBetsSectionHead(count, kindsPresent)", self.text)

    def test_it_branches_on_which_kinds_are_present_not_a_fixed_sentence(self):
        body = _function_body(self.text, "function allBetsSectionHead(")
        self.assertIn('kindsPresent.has("game")', body)
        self.assertIn('kindsPresent.has("total")', body)
        self.assertIn('kindsPresent.has("prop")', body)
        # The old, unconditional sentence must now sit behind a branch that
        # requires all three kinds -- never printed just because the
        # section rendered at all.
        self.assertIn("if (g && t && p) {", body)

    def test_a_game_only_card_never_claims_totals_or_props(self):
        """Today's own case: five moneylines, no totals, no props. The
        all-three sentence must not be the only sentence available."""
        body = _function_body(self.text, "function allBetsSectionHead(")
        game_only_branch = body.split("else if (g) {", 1)[1].split("} else if", 1)[0]
        self.assertNotIn("totals", game_only_branch.lower())
        self.assertNotIn("player props", game_only_branch.lower())

    def test_kinds_present_is_computed_from_what_actually_resolved(self):
        """`kindsPresent` must come from the RESOLVED list (only entries
        that will actually render), not the raw `all_bets` array -- an
        entry that fails to resolve must not be able to claim its kind is
        on the card."""
        self.assertIn("const kindsPresent = new Set(resolvedBets.map((r) => r.item.kind));", self.text)
        self.assertIn("allBetsSectionHead(resolvedBets.length, kindsPresent)", self.text)

    def test_the_prop_reason_survives_inside_the_merged_branch(self):
        """The old branch's own `payload.prop_reason && picks.length` line
        is untouched below (test_web_card_props.py already checks it); the
        merged branch above it must carry its OWN reachable prop_reason
        line, keyed on the resolved kinds rather than on `picks.length`
        (which can be legitimately zero on an all_bets-only card -- see
        DEFECT 3)."""
        merged_branch = self.text.split("if (resolvedBets.length) {", 1)[1] \
                                  .split("\n  } else {", 1)[0]
        self.assertIn('!kindsPresent.has("prop") && payload.prop_reason', merged_branch)
        self.assertIn('"data-hook": "card-prop-reason"', merged_branch)
        self.assertIn("text: payload.prop_reason", merged_branch)


# ---------------------------------------------------------------------------
# DEFECT 2 -- LINEUP NOT POSTED as a trailing chip.
# ---------------------------------------------------------------------------

class LineupNotPostedIsUnmissable(Card):
    def test_it_is_its_own_warn_line_not_a_chip(self):
        """`.card2lede--warn` is the same class/size the stale-price
        warning above it already uses -- not `.card2__kind--warn`, which
        was the small mono chip."""
        body = _function_body(self.text, "function lineupNotPostedWarning(")
        self.assertIn('class: "card2lede card2lede--warn"', body)
        self.assertNotIn("card2__kind", body)

    def test_it_goes_above_the_bet_sentence_not_into_the_top_row(self):
        """The old version appended a span into `.card2__top`, last, after
        the rank/label/grade/time/kind tag. The fix inserts a paragraph
        before `.card2__bet` instead."""
        merged_card_body = _function_body(self.text, "function mergedBetCard(")
        self.assertIn('card.querySelector(".card2__bet")', merged_card_body)
        self.assertIn("card.insertBefore(warning, bet)", merged_card_body)
        # The kind tag is still appended to `.card2__top` -- only the
        # lineup warning moved.
        self.assertIn('top.appendChild(kindTagEl(kindTagText(item.kind, full)));', merged_card_body)
        # The old call site (`top.appendChild(lineupNotPostedTag())`) must
        # be entirely gone.
        self.assertNotIn("lineupNotPostedTag", self.text)

    def test_the_dead_chip_css_is_gone(self):
        """`.card2__kind--warn` was the trailing-chip's only consumer;
        once nothing appends it, the rule has no reason to still claim
        the chip is amber."""
        css = CSS.read_text(encoding="utf-8")
        self.assertNotIn(".card2__kind--warn {", css)

    def test_the_warning_text_says_what_it_means(self):
        body = _function_body(self.text, "function lineupNotPostedWarning(")
        self.assertIn("LINEUP NOT POSTED", body)
        # 2026-09-14 (integrator): the fallback is season-average plate
        # appearances, never "the player's last game" -- that was untrue.
        self.assertIn("season-average plate appearances", body)
        self.assertNotIn("last game", body.lower())


# ---------------------------------------------------------------------------
# DEFECT 3 -- emptiness decided from payload.picks alone.
# ---------------------------------------------------------------------------

class AllBetsAloneCountsAsANonEmptyCard(Card):
    def test_a_shared_helper_checks_picks_or_all_bets(self):
        self.assertIn("function payloadHasBets(payload)", self.text)
        body = _function_body(self.text, "function payloadHasBets(")
        self.assertIn("payload.picks", body)
        self.assertIn("payload.all_bets", body)

    def test_the_walk_back_check_uses_the_shared_helper(self):
        """`lastPublishedCard`'s own `(older.picks || []).length` check was
        the first place this broke -- a fallback card with bets only in
        `all_bets` was treated as having none and discarded."""
        walk_back = _function_body(self.text, "async function lastPublishedCard(")
        self.assertIn("payloadHasBets(older)", walk_back)
        self.assertNotIn("(older.picks || []).length ? older", walk_back)

    def test_both_render_time_emptiness_checks_use_the_shared_helper(self):
        self.assertEqual(self.text.count("if (!payloadHasBets(payload)) {"), 2,
                          "both the walk-back trigger and the final "
                          "empty-card gate must use the same helper")

    def test_the_final_empty_gate_no_longer_reads_picks_length_alone(self):
        """The literal defect: `const picks = payload.picks || []; if "
        "(!picks.length) { ... emptyCard ... }` -- a card with zero game "
        "picks but real totals/props in all_bets hit this and was thrown "
        "away."""
        self.assertNotIn("const picks = payload.picks || [];\n  if (!picks.length) {", self.text)


# ---------------------------------------------------------------------------
# DEFECT 4 -- count and numbering from the raw (unresolved) all_bets array.
# ---------------------------------------------------------------------------

class NumberingComesFromTheResolvedRenderedListOnly(Card):
    def test_the_list_is_resolved_before_anything_is_counted(self):
        self.assertIn("function resolveAllBets(payload, allBets)", self.text)
        body = _function_body(self.text, "function resolveAllBets(")
        self.assertIn("if (full) resolved.push({ item, full });", body)

    def test_the_render_loop_resolves_once_up_front(self):
        self.assertIn(
            "const resolvedBets = allBets.length ? resolveAllBets(payload, allBets) : [];",
            self.text)
        # The old call passed the RAW array's own length as the total and
        # re-resolved (and could still return null) inside the loop.
        self.assertNotIn("mergedBetCard(item, payload, allBets.length, servingOlderCard)", self.text)

    def test_the_count_and_every_card_share_the_same_total(self):
        self.assertIn("allBetsSectionHead(resolvedBets.length, kindsPresent)", self.text)
        self.assertIn(
            "mergedBetCard(item, full, resolvedBets.length, index, servingOlderDate));"
                .replace("servingOlderDate", "servingOlderCard"),
            self.text)

    def test_mergedbetcard_no_longer_resolves_or_returns_null(self):
        """The first version's `mergedBetCard` called `resolveAllBetsItem`
        itself and returned null on a miss, which is exactly how an
        unresolved entry could still occupy a numbered slot the caller
        counted but never rendered."""
        body = _function_body(self.text, "function mergedBetCard(")
        self.assertNotIn("resolveAllBetsItem(item, payload)", body)
        self.assertNotIn("if (!full) return null;", body)

    def test_position_falls_back_to_the_resolved_loop_index_not_the_kinds_own_rank(self):
        """The literal defect: `item.position || full.position` -- when the
        server's own `item.position` was falsy, this fell back to the
        pick's position WITHIN ITS OWN KIND'S ARRAY, so a game pick and a
        prop could both read "1 OF 8". The fix falls back to the entry's
        own place in the RESOLVED merged list instead."""
        body = _function_body(self.text, "function mergedBetCard(")
        # 2026-09-14 (integrator): always the resolved index -- the server's
        # item.position counts unresolved entries, so preferring it left gaps.
        self.assertIn("const position = index + 1;", body)
        self.assertNotIn("Number.isInteger(item.position) ? item.position", body)
        # The old fallback expression itself must be gone from the CODE --
        # checked against the one line that assigns `position`, not the
        # comment two lines above it that names the old defect on purpose
        # (`item.position || full.position` appears there deliberately, as
        # the thing being explained).
        assignment_line = [ln for ln in body.splitlines()
                            if ln.strip().startswith("const position = ")][0]
        self.assertNotIn("item.position || full.position", assignment_line)


# ---------------------------------------------------------------------------
# Register sweep -- same scan test_web_card_props.py already runs over
# card.js, re-checked here with its own found-something guard so a change
# that stops rendering this section's own strings cannot pass silently.
# ---------------------------------------------------------------------------

class AllBetsStringsPassTheRegisterSweep(unittest.TestCase):
    def test_no_retired_phrase_is_rendered(self):
        offenders = []
        for line_no, text in _rendered_strings(JS / "card.js"):
            lowered = text.lower()
            for phrase in RETIRED:
                if phrase in lowered:
                    offenders.append(f"card.js:{line_no}: {phrase!r} in {text[:70]!r}")
        self.assertEqual(offenders, [])

    def test_no_banned_tout_or_edge_language_is_rendered(self):
        violations = []
        for line_no, text in _rendered_strings(JS / "card.js"):
            violations.extend(_violations_in(text, f"card.js:{line_no}"))
        self.assertEqual(violations, [])

    def test_the_new_strings_were_actually_scanned(self):
        rendered = " ".join(t for _n, t in _rendered_strings(JS / "card.js"))
        self.assertIn("LINEUP NOT POSTED", rendered)
        self.assertIn("Every bet we can price and grade, ranked by how likely it is.", rendered)
        # The kind-specific SECOND sentence of each branch is a second
        # `+`-concatenated segment -- same limit test_web_card_props.py's
        # own comment already documents ("Multi-line `+`-concatenated
        # `text:` values are only captured up to their first quoted
        # segment"), so the second sentence is checked directly against the
        # source below rather than through the rendered-string scanner.
        text = _read("card.js")
        self.assertIn("Game picks, and only game picks, so far today.", text)
        self.assertIn("Totals, and only totals, so far today.", text)
        self.assertIn("Player props, and only player props, so far today.", text)


if __name__ == "__main__":
    unittest.main()
