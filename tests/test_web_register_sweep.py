"""The developer register and the retired price-comparison register, swept
off the screens that were opened and read on 2026-09-11/12: #/odds, #/day,
the sign-in gate, the signup page, the landing page and the bottom nav.

Every phrase below was on a live page. Plain-text scans of what a renderer
sees, the same shape as the other web structure tests -- a test that ran
the page would pass or fail by browser, and this only has to notice the
words coming back.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from tests.test_no_developer_notes_on_screen import _rendered_strings

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
JS = WEB / "js"


def _rendered(name: str):
    return list(_rendered_strings(JS / name))


def _offenders(pairs, phrases, where):
    out = []
    for line_no, text in pairs:
        lowered = text.lower()
        for phrase in phrases:
            if phrase in lowered:
                out.append(f"{where}:{line_no}: {phrase!r} in {text[:70]!r}")
    return out


class TheOddsBoardSpeaksToAReader(unittest.TestCase):
    # Field names, a null, and the engineering rule behind a sentence --
    # all rendered on #/odds on 2026-09-11.
    LEAKS = ("spread_cents", "has_board", "key absent", "observed_utc",
             "never “no odds”", "consensus_unavailable_reason:")

    def test_no_field_name_or_engineering_rule_is_rendered(self):
        self.assertEqual(_offenders(_rendered("odds.js"), self.LEAKS, "odds.js"), [])

    def test_the_scanner_saw_the_page(self):
        self.assertGreater(len(_rendered("odds.js")), 20)


class TheDayPageSpeaksToAReader(unittest.TestCase):
    def setUp(self):
        self.text = (JS / "dayrecap.js").read_text(encoding="utf-8")

    def test_the_system_id_aside_is_gone(self):
        self.assertEqual(_offenders(_rendered("dayrecap.js"),
                                    ("system id was stored",), "dayrecap.js"), [])

    def test_a_total_carries_no_sign(self):
        """"Under +8" is not a bet anyone places."""
        self.assertIn('signed: marketKey !== "totals"', self.text)

    def test_first_five_innings_has_a_noun(self):
        noun_block = self.text.split("const MARKET_NOUN = {")[1].split("};")[0]
        self.assertIn("h2h_1st_5_innings", noun_block)
        body = self.text.split("function humanizeBetLabel(")[1].split("\nfunction ")[0]
        self.assertIn('marketKey === "h2h_1st_5_innings"', body)


class TheGateNamesNoRoute(unittest.TestCase):
    def test_it_does_not_promise_a_board(self):
        """One gate serves every signed-in route; on #/billing it said
        "view tonight's board"."""
        self.assertEqual(_offenders(_rendered("dom.js"), ("tonight's board",), "dom.js"), [])


RETIRED = (
    "line shopping", "line-shopping", "market-implied consensus", "never a tip",
    "recommendation field", "not one line, not one book", "checking every book",
    "predicted winner", "better number", "price improvement",
)


def _signup_copy():
    """Every sentence the signup page renders. The benefits list is a
    `const BENEFITS = [...]` fed to `text: line`, so the rendered-string
    scanner never sees it -- which is how the old list ("every book we can
    reach", "never a tip") stayed invisible to every tripwire. Scanned by
    hand here, line-numbered against the file."""
    text = (JS / "signup.js").read_text(encoding="utf-8")
    pairs = _rendered("signup.js")
    start = text.index("const BENEFITS = [")
    block = text[start:text.index("];", start)]
    first_line = text[:start].count("\n") + 1
    for offset, line in enumerate(block.splitlines()):
        stripped = line.strip().strip(",").strip('"')
        if stripped and not stripped.startswith("//") and not stripped.startswith("const "):
            pairs.append((first_line + offset, stripped))
    return pairs


class TheSignupPageSellsThePicks(unittest.TestCase):
    def test_no_retired_phrase_is_rendered(self):
        self.assertEqual(_offenders(_signup_copy(), RETIRED, "signup.js"), [])

    def test_it_leads_with_likelihood_then_the_price(self):
        copy = " ".join(t for _n, t in _signup_copy()).lower()
        self.assertIn("more likely", copy)
        self.assertIn("break even", copy)

    def test_the_benefits_were_actually_read(self):
        self.assertGreaterEqual(
            len([t for _n, t in _signup_copy() if "first pitch" in t.lower()]), 2)


def _visible_html(path: Path) -> str:
    html = path.read_text(encoding="utf-8")
    html = re.sub(r"<!--.*?-->", " ", html, flags=re.S)
    html = re.sub(r"<script\b.*?</script>", " ", html, flags=re.S)
    html = re.sub(r"<style\b.*?</style>", " ", html, flags=re.S)
    return re.sub(r"<[^>]+>", " ", html).lower()


class TheLandingPageAgreesWithTheProduct(unittest.TestCase):
    """The card says "the market makes Brewers a 64% bet to win"; the page
    that sold it said "nothing here states a win probability or a predicted
    winner". Both were live at once on 2026-09-11."""

    def setUp(self):
        self.text = _visible_html(WEB / "landing.html")

    def test_it_no_longer_denies_what_the_card_says(self):
        for phrase in ("nothing here states a win probability",
                       "recommendation field",
                       "do not publish a win probability",
                       "predicted winner anywhere"):
            self.assertNotIn(phrase, self.text, phrase)

    def test_the_line_shopping_section_is_gone(self):
        for phrase in ("what line shopping is actually worth",
                       "find the better number", "better numbers",
                       "another book had"):
            self.assertNotIn(phrase, self.text, phrase)

    def test_it_says_what_the_price_needs(self):
        self.assertIn("break even", self.text)
        self.assertIn("more likely", self.text)


class TheSlipLineNamesTheClub(unittest.TestCase):
    def test_the_server_sentence_is_printed_when_present(self):
        text = (JS / "today.js").read_text(encoding="utf-8")
        body = text.split("function pickWagerLine(")[1].split("\nfunction ")[0]
        self.assertIn("pick.wager_text", body)
        self.assertIn("bookLabel(pick.book)", body)


class TheLandingHeroLeadsWithTheCard(unittest.TestCase):
    """The hero was filled at runtime from GET /opportunities -- the
    price-gap ranker -- and read "Best of 11 books · Caesars +175, +160
    Everywhere else" over the copy that had just been rewritten."""

    def setUp(self):
        raw = (WEB / "js" / "landing-live.js").read_text(encoding="utf-8")
        # Code only: the module docstring quotes the old hero as history.
        raw = re.sub(r"/\*.*?\*/", " ", raw, flags=re.S)
        self.text = "\n".join(line for line in raw.splitlines()
                              if not line.strip().startswith("//"))

    def test_it_reads_the_card_not_the_price_board(self):
        self.assertIn('apiGet("/card")', self.text)
        self.assertNotIn('apiGet("/opportunities")', self.text)

    def test_no_everywhere_else_comparison(self):
        for phrase in ("Everywhere else", "Best of ${", "worstRealPrice", "hero-price-was"):
            self.assertNotIn(phrase, self.text, phrase)

    def test_it_says_what_the_price_needs(self):
        self.assertIn("to break even", self.text)
        self.assertIn("the market makes it", self.text)
        html = (WEB / "landing.html").read_text(encoding="utf-8")
        self.assertIn('data-hook="hero-price-needs"', html)


class TheGamePageAdvancedLayerIsNotAPriceBoard(unittest.TestCase):
    """SHOW ADVANCED ANALYSIS on 2026-09-11 was, in order: SPOTLIGHT · PRICE
    STANDING, BEATS CONSENSUS, IMPROVEMENT -1.38 pts, "price improvement /
    line-shopping value", 11 BOOKS COMPARED, MODEL vs MARKET "ranked by
    price against the fair price only", BOOK VERSUS BOOK "the comparison
    that is real", and a MARKET REFUSAL that said player props were refused
    -- false since the prop board shipped."""

    RETIRED_HERE = ("beats consensus", "line-shopping", "books compared",
                    "comparison that is real", "book versus book",
                    "market refusal", "price standing", "fair price only",
                    "player props and the rest", "no independent model")

    def setUp(self):
        self.text = (JS / "games.js").read_text(encoding="utf-8")

    def test_no_retired_phrase_is_rendered(self):
        self.assertEqual(_offenders(_rendered("games.js"), self.RETIRED_HERE, "games.js"), [])

    def test_the_tile_and_meter_are_not_imported(self):
        self.assertNotIn('from "./featuredbet.js"', self.text)
        self.assertNotIn('from "./valuemeter.js"', self.text)

    def test_other_markets_points_at_the_prop_board(self):
        body = self.text.split("function gavMarketRefusal(")[1].split("\nfunction ")[0]
        self.assertIn('href: "#/props"', body)
        self.assertIn("OTHER MARKETS", body)


class TheSupportPageSaysWhatItIsFor(unittest.TestCase):
    def test_one_sentence_above_the_form(self):
        rendered = " ".join(t for _n, t in _rendered("support.js")).lower()
        self.assertIn("we reply by email", rendered)
        text = (JS / "support.js").read_text(encoding="utf-8")
        self.assertIn('"support-intro"', text)


class ThePerformancePageNamesSystemsInWords(unittest.TestCase):
    def test_system_ids_go_through_the_humanizer(self):
        text = (JS / "performance.js").read_text(encoding="utf-8")
        self.assertIn("humanizeKey(s.system_id)", text)
        self.assertNotIn('text: s.system_id }', text)


class PropsHaveTheTab(unittest.TestCase):
    def test_props_replaced_odds_in_the_bottom_nav(self):
        text = (JS / "main.js").read_text(encoding="utf-8")
        nav = text.split("const NAV_ITEMS = [")[1].split("];")[0]
        self.assertIn('hash: "#/props", label: "PROPS"', nav)
        self.assertNotIn('label: "ODDS"', nav)

    def test_the_odds_board_is_still_reachable(self):
        """Leaving the nav must not orphan the route (the #/performance
        lesson: an unlinked page is a page nobody reaches)."""
        linked = [p.name for p in JS.glob("*.js")
                  if p.name != "main.js" and "#/odds" in p.read_text(encoding="utf-8")]
        self.assertTrue(linked, "#/odds is linked from nowhere but the nav it just left")


if __name__ == "__main__":
    unittest.main()
