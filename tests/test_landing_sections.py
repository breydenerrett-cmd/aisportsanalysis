"""The desk page (web/desk.html: the house pack, the AI desk, pricing, the questions), the old landing page moved whole on 2026-10-20.

Round-2 critic (2026-10-19): "hero is strong, then ~3,500px of dense legacy blocks". So below the hero the free-versus-subscribers lists,
the last graded card (the fills table), pricing and the per-sport record tiles are native <details> accordions, closed by default and
opened by a link to them. The facts and the hard lines stay: the coverage sentence, the paper-only / 21+ / not-advice lines (the shared
footer, said once, as the owner's 2026-10-18 voice pass requires), every data-hook the fills write into.

The kennel-first landing page that replaced it at web/landing.html is pinned in tests/test_landing_kennel_first.py.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from tests.hounds_web_runner import HAS_NODE, run_js

ROOT = Path(__file__).resolve().parent.parent
HTML = (ROOT / "web" / "desk.html").read_text(encoding="utf-8")
MAIN = re.search(r"<main>.*?</main>", HTML, re.S).group(0)


class TheDeskPageKeepsItsOrder(unittest.TestCase):
    def test_the_hero_comes_first_then_the_ai_desk_then_every_accordion(self):
        at = lambda x: MAIN.index(x)  # noqa: E731
        self.assertLess(at('data-hook="lb-hero"'), at('data-landing-section="desk"'))
        for hook in ("what-you-get", "last-card", "pricing", "sports-covered"):
            self.assertLess(at('data-landing-section="desk"'), at(f'data-hook="{hook}"'), hook)

    def test_the_build_band_and_the_three_steps_moved_to_the_landing_page(self):
        for gone in ('data-hook="kennels-card"', 'data-hook="landing-steps"', "data-step-dog="):
            self.assertNotIn(gone, HTML)


class HeavyBlocksAreAccordions(unittest.TestCase):
    ACCORDIONS = {
        "what-you-get": ("wyg-free", "wyg-subscribers", "wyg-sub-card"),
        "last-card": ("last-card-date", "last-card-body"),     # its title (last-card-title) is the summary, so it shows while the card is closed
        "pricing": ("pricing-host", "pricing-tier-note", "cta-signup"),
        "sports-covered": ("sport-record-tiles", "sport-tile-mlb", "sport-tile-nfl", "sport-tile-ufc", "postseason-link"),
    }

    def section(self, hook):
        start = MAIN.rindex("<section", 0, MAIN.index(f'data-hook="{hook}"'))
        return MAIN[start:MAIN.index("</section>", start)]

    def test_each_heavy_block_sits_inside_one_closed_details(self):
        for hook, inner in self.ACCORDIONS.items():
            with self.subTest(block=hook):
                sec = self.section(hook)
                self.assertEqual(sec.count('<details class="lv-acc"'), 1)
                self.assertNotRegex(sec, r'<details class="lv-acc"[^>]*\sopen')
                body = sec[sec.index('class="lv-acc__body"'):]
                for h in inner:
                    self.assertIn(f'data-hook="{h}"', body, f"{h} must still exist (the fills write into it) and sit in the body")
                self.assertRegex(sec, r"<summary class=\"lv-acc__sum\"><h2")
                if hook == "last-card":
                    self.assertRegex(sec, r'<summary class="lv-acc__sum"><h2 class="section__title" data-hook="last-card-title">')

    def test_the_free_versus_subscribers_lists_in_the_desk_are_an_accordion_too(self):
        desk = re.search(r'<section class="hero lv-desk".*?</section>', MAIN, re.S).group(0)
        self.assertRegex(desk, r'<details class="lv-acc lv-acc--inline"[^>]*>\s*<summary[^>]*>[^<]*<span[^>]*>Free, and for subscribers')
        self.assertNotRegex(desk, r'<details class="lv-acc lv-acc--inline"[^>]*\sopen')
        self.assertEqual(desk.count('data-hook="hero-wyg"'), 1)

    def test_the_faq_is_still_a_list_of_closed_details(self):
        faq = re.search(r'<section[^>]*data-hook="faq".*?</section>', MAIN, re.S).group(0)
        self.assertEqual(faq.count('<details class="faq-item'), 6)
        self.assertNotRegex(faq, r'<details class="faq-item[^>]*\sopen')

    def test_the_facts_and_the_hard_lines_are_still_on_the_page(self):
        # owner ruling 2026-10-20, complete-product positioning: the pause line is a coverage line now
        self.assertRegex(MAIN, r'data-hook="kennel-straight">Tennis, cricket, soccer, NBA, NHL, college, MLB, NFL, MMA and more\.')
        self.assertIn("Analysis, not advice.", MAIN)
        self.assertNotIn("Invite round", MAIN)                       # 2026-10-20: off the first screen; the FAQ still states the offer
        self.assertIn("the first 20 testers get 7 days", MAIN)
        self.assertIn('data-hook="disclaimer-host"', HTML)          # 21+, the helpline and the not-advice summary: the shared footer, said once
        self.assertIn("paper bets", MAIN.lower())
        self.assertEqual(MAIN.count('data-hook="hero-paused"'), 1)   # the desk-only module the live script reveals


@unittest.skipUnless(HAS_NODE, "node not installed")
class AccordionsOpenForALink(unittest.TestCase):
    def test_a_hash_opens_the_accordion_it_points_at_and_only_that_one(self):
        got = run_js('''
const mk = (id) => { const acc = { open: false }; const el = { id, scrolled: false, querySelector: (s) => (s === "details.lv-acc" ? acc : null), scrollIntoView() { this.scrolled = true; } }; return [el, acc]; };
const [pricing, pAcc] = mk("pricing"), [sample, sAcc] = mk("free-sample");
const plain = { id: "faq", querySelector: () => null };
globalThis.document = { getElementById: (id) => ({ pricing, "free-sample": sample, faq: plain })[id] || null, addEventListener() {} };
globalThis.window = { addEventListener() {} };
globalThis.location = { hash: "" };
const { openAccordionForHash } = await import("./landing.js");
const r = [openAccordionForHash("#pricing"), openAccordionForHash("#faq"), openAccordionForHash("#nowhere"), openAccordionForHash("")];
console.log(JSON.stringify([r, pAcc.open, sAcc.open, pricing.scrolled]));''')
        self.assertEqual(got, [[True, False, False, False], True, False, True])


if __name__ == "__main__":
    unittest.main()
