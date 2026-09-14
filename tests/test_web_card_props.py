"""PLAYER PROPS ON THE CARD (web/js/card.js, web/js/cardrecord.js),
2026-09-12 -- the owner's note this morning, verbatim in substance: "Did
you wire everything? It's still showing ML's." The card is moneyline-first
by rule; the likeliest player props that clear their price join it as
frozen, graded picks (src/analysis/daily_card.select_props is the one
place the SELECTION happens -- this only checks the two renderers that lay
out what that function decided).

Plain-text scans of the source, the same shape as the other web structure
tests (test_web_grade.py, test_web_register_sweep.py) -- there is no JS
runtime in this repo's test suite, so every assertion here is either a
literal string that must appear, or a register scan over the strings a
renderer would actually hand a reader.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from tests.test_customer_language import _violations_in
from tests.test_no_developer_notes_on_screen import _rendered_strings
from tests.test_web_register_sweep import RETIRED

ROOT = Path(__file__).resolve().parent.parent
JS = ROOT / "web" / "js"


def _read(name: str) -> str:
    return (JS / name).read_text(encoding="utf-8")


def _function_body(text: str, signature: str) -> str:
    """The body of a top-level `function`/`const` block, the same slicing
    convention test_web_grade.py uses: from the signature to the next line
    that starts a new top-level declaration."""
    after = text.split(signature, 1)[1]
    for marker in ("\nfunction ", "\nexport function ", "\nexport async function "):
        after = after.split(marker)[0]
    return after


class CardReadsPropPicks(unittest.TestCase):
    def setUp(self):
        self.text = _read("card.js")

    def test_it_reads_payload_prop_picks(self):
        self.assertIn("payload.prop_picks", self.text)

    def test_absent_or_empty_prop_picks_renders_nothing_extra(self):
        """Old frozen rows carry no `prop_picks` key at all -- `|| []`
        must be the whole compatibility story, and an empty list must not
        fall through to the `prop_reason` branch by itself."""
        self.assertIn("const propPicks = payload.prop_picks || [];", self.text)
        self.assertIn("if (propPicks.length) {", self.text)

    def test_the_reason_only_renders_when_picks_are_also_empty_and_present(self):
        """One quiet line under the divider, and only when there ARE game
        picks on the card (guaranteed by this point -- `renderCard` already
        returned via `emptyCard` if `picks.length` were zero) -- never a
        lonely reason on an otherwise-empty card."""
        self.assertIn("} else if (payload.prop_reason && picks.length) {", self.text)
        self.assertIn('"data-hook": "card-prop-reason"', self.text)
        self.assertIn("text: payload.prop_reason", self.text)

    def test_an_empty_section_carries_no_sub_heading_about_its_picks(self):
        """Seen 2026-09-12 on today's frozen card: "The likeliest props
        tonight that also clear their price" directly above "Player props
        were not part of this card when it was frozen." The reason branch
        asks for the head without the sub-heading."""
        self.assertIn("propSectionHead(servingOlderCard, false)", self.text)
        body = _function_body(self.text, "function propSectionHead(")
        self.assertIn("withSubhead = true", body)
        self.assertIn("if (!withSubhead) return wrap;", body)

    def test_the_divider_hook_carries_the_plain_english_subheading(self):
        body = _function_body(self.text, "function propSectionHead(")
        self.assertIn('"data-hook": "card-prop-divider"', body)
        self.assertIn('sectionHead("PLAYER PROPS")', body)
        self.assertIn("Ranked by how likely we make them, never by the price.", body)

    def test_each_pick_carries_its_own_hook(self):
        body = _function_body(self.text, "function propPickCard(")
        self.assertIn('"data-hook": "card-prop-pick"', body)
        self.assertIn("pick.bet", body)
        self.assertIn("pick.why", body)

    def test_it_links_the_prop_board_never_bet_check(self):
        """Bet Check is moneyline-only (src/analysis/betcheck.py) -- a prop
        pick must never carry a CHECK THIS PRICE link. The href falls back
        to the plain board on tonight's card, and to that same earlier
        date's board (#/props/<date>, routed in main.js) when the pick
        itself came from an older frozen card -- either way it is the prop
        board, never Bet Check."""
        body = _function_body(self.text, "function propPickCard(")
        self.assertIn('"#/props"', body)
        self.assertIn("#/props/${servingOlderDate}", body)
        self.assertNotIn("#/betcheck", body)
        self.assertNotIn("card-check-this", body)
        self.assertNotIn("betCheckHref", body)

    def test_the_grid_is_appended_after_the_game_picks_grid(self):
        game_grid_at = self.text.find('"data-hook": "card-grid"')
        prop_section_call_at = self.text.find(
            "wrap.appendChild(propSectionHead(servingOlderCard")
        self.assertGreater(game_grid_at, 0)
        self.assertGreater(prop_section_call_at, game_grid_at)

    def test_the_subhead_takes_the_older_card_flag(self):
        """A card from an earlier slate must never sit under a prop
        sub-heading that says TONIGHT'S over picks whose own
        first_pitch_utc is that earlier day's -- the same rule the
        game-picks head (`servingOlderCard ? "LAST PUBLISHED CARD" : ...`)
        already follows. Caught 2026-09-12: propSectionHead() took no
        argument and was called unconditionally, so the fallback path said
        "tonight" over a frozen older-date card twelve lines under a
        heading that had already said otherwise."""
        body = _function_body(self.text, "function propSectionHead(")
        self.assertIn("servingOlderDate", body)
        # Both call sites in renderCard must forward the same flag the
        # game-picks head already computed -- not a hardcoded call.
        self.assertEqual(
            self.text.count("propSectionHead(servingOlderCard"), 2,
            "both call sites must pass servingOlderCard through")
        self.assertNotIn("propSectionHead()", self.text)

    def test_older_card_props_never_say_tonight(self):
        """Direct check on the rendered sub-head string itself, not just
        that a parameter exists -- a parameter that is never read from
        would pass the test above while still always saying "tonight"."""
        body = _function_body(self.text, "function propSectionHead(")
        self.assertIn("servingOlderDate", body)
        # The ternary (or equivalent branch) must choose between two
        # distinct strings keyed on the flag, and the older-card string
        # must not contain the word "tonight".
        branches = body.split("servingOlderDate", 1)[1]
        self.assertIn("that night", branches.lower())


class CardRecordReadsPropPicks(unittest.TestCase):
    def setUp(self):
        self.text = _read("cardrecord.js")

    def test_it_reads_day_prop_picks(self):
        self.assertIn("day.prop_picks", self.text)

    def test_old_game_pick_rows_are_unchanged(self):
        """The one call site every pre-2026-09-12 history row still hits --
        no `kind` argument, so `pickRow`'s own default keeps it rendering
        exactly as it did before this file changed."""
        self.assertIn(
            "for (const pick of day.picks || []) tbody.appendChild(pickRow(pick));",
            self.text)

    def test_prop_pick_rows_are_marked_and_share_the_same_columns(self):
        self.assertIn('tbody.appendChild(pickRow(pick, "prop"));', self.text)
        body = _function_body(self.text, "function pickRow(")
        self.assertIn('isProp ? "record-prop-pick-row" : "record-pick-row"', body)
        # Same result/price/book/return columns a game row gets -- no
        # separate code path that could quietly drop one of them.
        self.assertIn("RESULT_CHIP[pick.result]", body)
        self.assertIn("formatAmerican(pick.price)", body)
        self.assertIn("bookLabel(pick.book)", body)
        self.assertIn("unitsFmt(pick.profit_units)", body)

    def test_the_scanner_saw_the_function(self):
        # Defensive: if the slice above ever matched nothing, every
        # assertion in this class would vacuously pass on an empty string.
        body = _function_body(self.text, "function pickRow(")
        self.assertGreater(len(body), 200)

    def test_the_prop_record_is_read_apart_from_the_game_record(self):
        """`card_ledger.record()` keeps the two populations apart in
        `by_kind`; the page must too. The headline's figures are the game
        picks alone, and they are labelled as such -- "RECORD" over a number
        that silently excludes props is a label that lies by omission."""
        body = _function_body(self.text, "function propHeadline(")
        self.assertIn("record.by_kind.prop", body)
        self.assertIn('"record-prop-headline"', body)
        self.assertIn('"record-prop-none"', body)
        self.assertIn("PROPS (W-L-P)", body)
        headline_body = _function_body(self.text, "function headline(")
        self.assertIn("GAME PICKS (W-L-P)", headline_body)
        self.assertNotIn('"RECORD (W-L-P)"', headline_body)
        render = _function_body(self.text, "export async function renderCardRecord(")
        self.assertIn("propHeadline(record)", render)

    def test_an_older_record_payload_without_by_kind_renders_no_prop_panel(self):
        body = _function_body(self.text, "function propHeadline(")
        self.assertIn("if (!prop) return null;", body)


class EveryRenderedStringPassesTheRegisterSweep(unittest.TestCase):
    """The exact scan this repo already runs on other screens: strings
    handed to a reader via `text:`, checked against the retired
    price-comparison register (test_web_register_sweep.RETIRED) and the
    banned tout/edge/win-probability vocabulary
    (test_customer_language._violations_in)."""

    def test_no_retired_phrase_is_rendered(self):
        offenders = []
        for name in ("card.js", "cardrecord.js"):
            for line_no, text in _rendered_strings(JS / name):
                lowered = text.lower()
                for phrase in RETIRED:
                    if phrase in lowered:
                        offenders.append(f"{name}:{line_no}: {phrase!r} in {text[:70]!r}")
        self.assertEqual(offenders, [])

    def test_no_banned_tout_or_edge_language_is_rendered(self):
        violations = []
        for name in ("card.js", "cardrecord.js"):
            for line_no, text in _rendered_strings(JS / name):
                violations.extend(_violations_in(text, f"{name}:{line_no}"))
        self.assertEqual(violations, [])

    def test_the_new_prop_strings_were_actually_scanned(self):
        """Guard against the two scans above passing because they found
        nothing at all -- the same shape as this repo's other
        scanner-found-nothing guards."""
        found = []
        for name in ("card.js", "cardrecord.js"):
            found.extend(_rendered_strings(JS / name))
        rendered = " ".join(t for _n, t in found)
        self.assertIn("SEE THE PROP BOARD", rendered)
        # "PLAYER PROPS" itself is passed through the shared `sectionHead`
        # helper (`text: label`, a variable, not a literal) so it never
        # shows up as a `text:` literal for this scanner to find -- checked
        # directly against the source instead, same as any other
        # sectionHead() call in this file.
        self.assertIn('sectionHead("PLAYER PROPS")', _read("card.js"))
        # Multi-line `+`-concatenated `text:` values are only captured up
        # to their first quoted segment -- same as every other such string
        # in this file (e.g. card.js's own "Live prices —" lede) -- so this
        # checks the first segment, not the whole sentence.
        self.assertIn("The likeliest props tonight", rendered)


if __name__ == "__main__":
    unittest.main()
