"""Bet Check no longer speaks the price-comparison register.

THE DIRECTIVE, 2026-09-10, verbatim:

    "this whole 'we do price verification and see which book has the better
     odds, dude,' that has to stop. None of that's important. Nobody fucking
     cares."

THE STATE OF THE PAGE TWO DAYS LATER, swept live on 2026-09-12 by filling in
the form for LAD -190 at MIA:

    BEATS CONSENSUS            No
    IMPROVEMENT                -1.89 pts best -190 (LowVig) vs a fair price…
    BOARD DEPTH                10 books, above the 6-book floor
    10 BOOKS COMPARED
    02  THE MARKET  ·  YOUR PRICE / FAIR PRICE / BEST AVAILABLE
    YOUR PRICE BEATS THE MARKET-IMPLIED CONSENSUS: NO
    PRICE VERDICT  ·  PASS
    "price improvement / line-shopping value — a better execution price…"  ×2
    COMPARE 10 BOOKS

It was the dominant content of the screen. This file is what keeps it gone.

Scans RENDERED strings only -- the `text:` handed to an element or chip --
so a comment explaining why a phrase was retired does not trip it. Reuses
the scanner from tests/test_no_developer_notes_on_screen.py rather than
re-declaring one; a second copy is how the two drift.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from tests.test_no_developer_notes_on_screen import _rendered_strings

ROOT = Path(__file__).resolve().parent.parent
WEB_JS = ROOT / "web" / "js"
BETCHECK = WEB_JS / "betcheck.js"

# Rendered text that belongs to the retired register. Case-insensitive.
RETIRED = (
    "beats consensus",
    "beats the market",
    "improvement",
    "price verdict",
    "books compared",
    "best available",
    "price standing",
    "board depth",
    "line-shopping",
    "line shopping",
    "compare books",
    "compare ",          # "COMPARE 10 BOOKS"
    "tier a",
    "mechanically composed",
    "not editorial",
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class TheRegisterIsGoneFromWhatARendererSees(unittest.TestCase):
    def test_no_rendered_string_speaks_it(self):
        offenders = []
        for line_no, text in _rendered_strings(BETCHECK):
            lowered = text.lower()
            for phrase in RETIRED:
                if phrase in lowered:
                    offenders.append(f"betcheck.js:{line_no}: {phrase!r} in {text[:70]!r}")
        self.assertEqual(offenders, [],
                         "the price-comparison register is back on Bet Check:\n"
                         + "\n".join(offenders))

    def test_the_scanner_saw_the_page(self):
        """A regex that stops matching would turn this file green forever."""
        self.assertGreater(len(list(_rendered_strings(BETCHECK))), 20)


class TheModulesThatCarryItAreNotImported(unittest.TestCase):
    """featuredbet.js IS the tile (PRICE STANDING / BEATS CONSENSUS /
    IMPROVEMENT / BOARD DEPTH); valuemeter.js is the bar under the verdict.
    Both still serve other screens. This one must not mount them."""

    def test_featuredbet_and_valuemeter_are_not_imported(self):
        text = _read(BETCHECK)
        self.assertNotIn('from "./featuredbet.js"', text)
        self.assertNotIn('from "./valuemeter.js"', text)

    def test_the_verdict_panel_and_market_block_no_longer_exist(self):
        text = _read(BETCHECK)
        self.assertNotRegex(text, r"\bfunction renderPriceVerdict\s*\(")
        self.assertNotRegex(text, r"\bfunction renderMarket\s*\(")
        self.assertNotIn('"bet-check-price-verdict"', text)


class WhatReplacedIt(unittest.TestCase):
    """The owner's order: is it likely, then what does the price need."""

    def setUp(self):
        self.text = _read(BETCHECK)

    def test_block_02_is_the_two_numbers_on_the_mandated_hook(self):
        self.assertIn('"THE NUMBERS"', self.text)
        body = self.text.split("function renderNumbers(")[1].split("\nfunction ")[0]
        self.assertIn('"data-hook": "bet-check-prices"', body)
        self.assertIn("THE MARKET MAKES IT", body)
        self.assertIn("THE PRICE NEEDS", body)

    def test_both_figures_come_from_the_server_never_derived_here(self):
        body = self.text.split("function renderNumbers(")[1].split("\nfunction ")[0]
        self.assertIn("stated_implied_probability", body)
        self.assertIn("market_consensus", body)
        # No client-side price-to-chance arithmetic.
        self.assertNotRegex(body, r"100\s*/\s*\(")
        self.assertNotRegex(body, r"/\s*\(\s*100")

    def test_it_says_whose_number_it_is(self):
        body = self.text.split("function renderNumbers(")[1].split("\nfunction ")[0]
        self.assertIn("do not have a number of our own", body)

    def test_the_one_execution_line_is_a_foot_not_a_section(self):
        body = self.text.split("function renderNumbers(")[1].split("\nfunction ")[0]
        self.assertIn("Best we saw", body)
        self.assertIn('"bc2-block__foot"', body)

    def test_the_bet_is_stated_in_words_not_a_tile(self):
        body = self.text.split("function renderTheBet(")[1].split("\nfunction ")[0]
        self.assertIn("to win", body)
        self.assertNotIn("renderFeaturedBet", body)
        self.assertNotIn("TIER", body)

    def test_the_connector_asks_the_owners_question(self):
        assembly = self.text.split("function renderResult(")[1].split("\nfunction ")[0]
        self.assertIn("IS IT LIKELY, AND WHAT DOES THE PRICE NEED?", assembly)
        self.assertNotIn("SO WHAT DOES THE MARKET SAY?", assembly)

    def test_no_verdict_word_anywhere_in_the_numbers(self):
        body = self.text.split("function renderNumbers(")[1].split("\nfunction ")[0]
        for word in ("PASS", "FAIL", "YES", "NO\"", "GOOD", "BAD"):
            self.assertNotIn(f'"{word}', body)


class TheRegisterIsGoneFromTodayToo(unittest.TestCase):
    """The same tile headlined the main screen as "FEATURED · LARGEST PRICE
    GAP AGAINST CONSENSUS" and fired a POST /betcheck on every load to fill
    itself. Removed 2026-09-12."""

    def test_today_does_not_mount_the_tile_or_name_the_gap_as_a_feature(self):
        today = WEB_JS / "today.js"
        text = _read(today)
        self.assertNotIn('from "./featuredbet.js"', text)
        offenders = [f"today.js:{n}: {t[:60]!r}"
                     for n, t in _rendered_strings(today)
                     if "price gap" in t.lower() or "beats consensus" in t.lower()]
        self.assertEqual(offenders, [], "\n".join(offenders))


if __name__ == "__main__":
    unittest.main()
