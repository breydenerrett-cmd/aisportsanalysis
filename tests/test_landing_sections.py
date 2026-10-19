"""The landing page after the round-2 critic (2026-10-19): three sections with one visual each, the heavy blocks behind accordions.

The critic: "hero is strong, then ~3,500px of dense legacy blocks". So below the hero the page is exactly three sections (build your
dog, how it works in three steps, the AI desk in one compact card); the free-versus-subscribers lists, the last graded card (the fills
table), pricing and the per-sport record tiles are native <details> accordions, closed by default and opened by a link to them. The
facts and the hard lines stay: the MLB pause sentence, the paper-only / 21+ / not-advice lines (the shared footer, said once, as the
owner's 2026-10-18 voice pass requires), every data-hook the fills write into.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from tests.hounds_web_runner import HAS_NODE, run_js

ROOT = Path(__file__).resolve().parent.parent
HTML = (ROOT / "web" / "landing.html").read_text(encoding="utf-8")
MAIN = re.search(r"<main>.*?</main>", HTML, re.S).group(0)


class ThreeSections(unittest.TestCase):
    def test_below_the_hero_there_are_exactly_three_feature_sections_in_order(self):
        marks = re.findall(r'<section[^>]*data-landing-section="([a-z]+)"', MAIN)
        self.assertEqual(marks, ["build", "how", "desk"])

    def test_the_three_sections_come_right_after_the_hero_and_before_every_accordion(self):
        at = lambda s: MAIN.index(s)  # noqa: E731
        self.assertLess(at('data-hook="lb-hero"'), at('data-landing-section="build"'))
        self.assertLess(at('data-landing-section="build"'), at('data-landing-section="how"'))
        self.assertLess(at('data-landing-section="how"'), at('data-landing-section="desk"'))
        for hook in ("what-you-get", "last-card", "pricing", "sports-covered"):
            self.assertLess(at('data-landing-section="desk"'), at(f'data-hook="{hook}"'), hook)

    def test_how_it_works_is_three_steps_each_with_a_dog(self):
        how = re.search(r'<section[^>]*data-hook="landing-steps".*?</section>', MAIN, re.S).group(0)
        self.assertEqual(how.count('class="lv-step"'), 3)
        self.assertEqual(how.count("data-step-dog="), 3)
        self.assertEqual(how.count("<h3>"), 3)
        self.assertIn("No real money is ever staked", how)
        self.assertIn("past results do not promise future ones", how)

    def test_the_build_band_has_one_primary_action_and_keeps_the_kennel_links(self):
        band = re.search(r'<section class="kncard".*?</section>', MAIN, re.S).group(0)
        self.assertEqual(band.count("btn--primary"), 1)
        for hook in ("kennels-card-build", "kennels-card-browse", "kennels-card-mine", "kennels-card-faces"):
            self.assertIn(f'data-hook="{hook}"', band)


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
        self.assertRegex(MAIN, r'data-hook="kennel-straight">We stopped publishing MLB value picks on Oct 16, 2026')
        self.assertIn("Analysis, not advice.", MAIN)
        self.assertIn("Early access: the first 20 testers get 7 days free, no card. Not on sale yet; planned price $19.99 a month.", MAIN)
        self.assertIn('data-hook="disclaimer-host"', HTML)          # 21+, the helpline and the not-advice summary: the shared footer, said once
        self.assertIn("paper bets", MAIN.lower())
        self.assertEqual(MAIN.count('data-hook="hero-paused"'), 1)   # the paused module the live script reveals


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


@unittest.skipUnless(HAS_NODE, "node not installed")
class StepDogsAreTheRealDogs(unittest.TestCase):
    def test_each_step_dog_is_the_breed_its_name_spells(self):
        steps = re.findall(r'data-step-dog="([^"|]+)\|([^"|]+)\|([a-z]+)"', HTML)
        self.assertEqual(len(steps), 3)
        got = run_js('const Rig = await import("./dog-rig.js");\nconsole.log(JSON.stringify(%s.map(([id, name]) => Rig.breedFor({ id, name }))));' % str([list(s[:2]) for s in steps]).replace("'", '"'))
        self.assertEqual(got, ["poodle", "beagle", "chihuahua"])


if __name__ == "__main__":
    unittest.main()
