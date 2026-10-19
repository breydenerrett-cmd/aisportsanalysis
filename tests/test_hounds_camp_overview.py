"""The training camp after the round-2 critic (2026-10-19): a strip of four figures, ten sections collapsed to a headline and one number.

The critic: "4,700px of identical cards". The page now opens on coach tips graded, helped / hurt, the next breeding cycle and your dogs
in training; each section is a closed <details> showing its headline and one figure; the long copy stays behind each section's own
"How this works". The figures come from the endpoints the sections already read (web/js/camp-overview.js) and a figure the server did
not send is a dash, never a zero.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from tests.hounds_web_runner import HAS_NODE, run_js

ROOT = Path(__file__).resolve().parent.parent
HTML = (ROOT / "web" / "learning.html").read_text(encoding="utf-8")


class CollapsedSections(unittest.TestCase):
    def test_the_page_opens_on_four_figures(self):
        strip = re.search(r'<ul class="cp-strip".*?</ul>', HTML, re.S).group(0)
        self.assertEqual(strip.count('class="cp-stat"'), 4)
        for hook in ("camp-stat-tips", "camp-stat-helped", "camp-stat-next", "camp-stat-dogs"):
            self.assertIn(f'data-hook="{hook}"', strip)
        for label in ("Coach tips graded", "Helped / hurt", "Next breeding cycle", "Your dogs in training"):
            self.assertIn(label, strip)

    def test_every_section_is_a_closed_details_with_a_headline_and_one_number(self):
        panels = re.findall(r'<section class="hd-panel".*?</section>', HTML, re.S)
        self.assertEqual(len(panels), 10)
        for panel in panels:
            self.assertEqual(panel.count('<details class="cp-sec"'), 1, panel[:90])
            self.assertNotRegex(panel, r'<details class="cp-sec"[^>]*\sopen')
            self.assertRegex(panel, r'<summary class="cp-sec__sum"><h2 id="[a-z]+-h">[^<]+</h2><span class="cp-sec__num" data-hook="camp-num-[a-z]+">&mdash;</span></summary>')
        self.assertEqual(len(re.findall(r'class="cp-sec__num"', HTML)), 10)

    def test_the_page_is_short_the_long_copy_sits_behind_how_this_works(self):
        # the always-visible part of each section is the summary; everything else is in the collapsed body
        visible = re.sub(r'<div class="cp-sec__body">.*?</details>\s*</section>', "", HTML, flags=re.S)
        self.assertLess(len(re.findall(r"<p[ >]", visible.split("<main", 1)[1])), 6, "the main column shows almost no paragraphs until a section opens")
        self.assertGreaterEqual(HTML.count('<details class="lh-how"><summary>How this works</summary>'), 8)

    def test_every_hook_the_camp_scripts_fill_is_still_there(self):
        for hook in ("camp-dogs", "coach-body", "camp-drill", "camp-events", "learning-chance", "learning-chance-chart", "learning-hold",
                     "learning-activity", "learning-rules", "learning-lessons", "learning-breeding", "learning-paused", "paper-only-notice"):
            self.assertIn(f'data-hook="{hook}"', HTML, hook)
        self.assertIn('src="js/camp-overview.js"', HTML)

    def test_the_paper_only_not_advice_line_is_still_static_markup(self):
        self.assertIn("Paper bets only. Not advice. 21+.", HTML)
        self.assertIn("1-800-GAMBLER", HTML)


@unittest.skipUnless(HAS_NODE, "node not installed")
class TheFigures(unittest.TestCase):
    def figures(self, args: str):
        return run_js(f'const C = await import("./camp-overview.js");\nconsole.log(JSON.stringify(C.campFigures({args})));')

    def test_with_no_answers_every_figure_is_a_dash_or_sign_in_never_a_zero(self):
        got = self.figures("{ signedInNow: false }")
        self.assertEqual(got["strip"], {"tips": "—", "helpedHurt": "—", "nextCycle": "—", "dogs": "Sign in"})
        self.assertEqual(got["nums"]["coach"], "not graded yet")
        self.assertEqual(got["nums"]["coin"], "—")
        self.assertEqual(got["nums"]["hold"], "—")
        self.assertEqual(got["nums"]["breeding"], "—")

    def test_the_server_figures_are_shown_as_sent(self):
        got = self.figures('''{ signedInNow: true, nowMs: Date.parse("2026-10-19T00:00:00Z"),
          coach: { computed: true, summary: { graded_forward: 12, helped: 5, hurt: 3 } },
          learning: { live_challengers: 4, lessons: { count: 9 }, system: { paused: false,
            vs_random: { windows: { "30": { enough: true, difference: 0.41 } } },
            promotion_hit_rate: { matured: 6, hits: 4 }, activity: { promotions: 2, retirements: 3 } } },
          breeding: { enabled: true, paused: false, next_cycle_utc: "2026-10-20T06:00:00Z" },
          mine: { dogs: [{}, {}] } }''')
        self.assertEqual(got["strip"], {"tips": "12", "helpedHurt": "5 / 3", "nextCycle": "in 1d 6h", "dogs": "2"})
        self.assertEqual(got["nums"]["coach"], "12 graded")
        self.assertEqual(got["nums"]["dogs"], "2 dogs")
        self.assertEqual(got["nums"]["cuts"], "4 trying out")
        self.assertEqual(got["nums"]["coin"], "+0.41 pts")
        self.assertEqual(got["nums"]["hold"], "4 of 6")
        self.assertEqual(got["nums"]["activity"], "2 promoted, 3 cut")
        self.assertEqual(got["nums"]["lessons"], "9 lessons")

    def test_a_comparison_without_enough_bets_says_so_instead_of_showing_a_number(self):
        got = self.figures('{ signedInNow: true, learning: { system: { vs_random: { windows: { "30": { enough: false, difference: 1.7 } } }, promotion_hit_rate: { matured: 0 } } } }')
        self.assertEqual(got["nums"]["coin"], "too few bets")
        self.assertEqual(got["nums"]["hold"], "none yet")

    def test_a_paused_breeding_program_and_camp_say_paused(self):
        got = self.figures('{ signedInNow: true, breeding: { enabled: true, paused: true }, learning: { system: { paused: true } } }')
        self.assertEqual(got["strip"]["nextCycle"], "paused")
        self.assertEqual(got["nums"]["activity"], "paused")

    def test_until_text(self):
        got = run_js('''const C = await import("./camp-overview.js"); const now = Date.parse("2026-10-19T00:00:00Z");
console.log(JSON.stringify([C.untilText("2026-10-19T00:40:00Z", now), C.untilText("2026-10-19T05:00:00Z", now), C.untilText("2026-10-18T00:00:00Z", now), C.untilText("", now)]));''')
        self.assertEqual(got, ["in 40m", "in 5h", "due now", "—"])

    def test_a_link_or_a_drill_opens_the_collapsed_section(self):
        got = run_js('''const C = await import("./camp-overview.js");
const acc = { open: false }; const root = { getElementById: (id) => (id === "drills" ? { querySelector: () => acc } : null) };
console.log(JSON.stringify([C.openSectionFor("#nowhere", root), acc.open, C.openSectionFor("#drills", root), acc.open]));''')
        self.assertEqual(got, [False, False, True, True])
        drill = (ROOT / "web" / "js" / "dog-camp.js").read_text(encoding="utf-8")
        self.assertIn('section.querySelector("details.cp-sec")', drill)


if __name__ == "__main__":
    unittest.main()
