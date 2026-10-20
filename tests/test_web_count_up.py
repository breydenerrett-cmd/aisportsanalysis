"""The number count-up (web/js/fx.js `countUp`) never shows a number that was never true.

2026-10-19: a screenshot caught "$73.14" on a $1,000 paper account because every count-up started from zero and a hidden tab froze it
mid-way. Now: a dollar figure (a bankroll) counts from the $1,000 start toward its real value, a bankroll that equals the start does not
animate at all, and a hidden tab or reduced motion shows the final text at once (also mid-animation, and in the landing race).
"""

from __future__ import annotations

import unittest
from pathlib import Path

from tests.hounds_web_runner import HAS_NODE, run_js

ROOT = Path(__file__).resolve().parent.parent

SETUP = r'''
globalThis.document = { visibilityState: "visible", listeners: [], addEventListener(n, f) { this.listeners.push(f); }, removeEventListener(n, f) { this.listeners = this.listeners.filter((x) => x !== f); } };
globalThis.requestAnimationFrame = (fn) => setTimeout(() => fn(performance.now() + 5000), 0);
const mkEl = (text, attrs = {}) => { const writes = []; return { writes, text, attrs: { ...attrs }, get textContent() { return this.text; }, set textContent(v) { writes.push(v); this.text = v; },
  getAttribute(k) { return this.attrs[k] ?? null; }, setAttribute(k, v) { this.attrs[k] = v; } }; };
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
'''


def js(body: str, reduced: bool = False):
    head = f'globalThis.window = {{ matchMedia: () => ({{ matches: {str(reduced).lower()} }}) }};\n' + SETUP
    return run_js(head + 'const Fx = await import("./fx.js");\n' + body)


@unittest.skipUnless(HAS_NODE, "node not installed")
class BankrollCountUp(unittest.TestCase):
    def test_a_bankroll_counts_from_the_1000_start_never_from_zero(self):
        got = js('''
const el = mkEl("$1,073.14");
Fx.countUp(el, 700); await wait(60);
const nums = el.writes.map((w) => Number(w.replace(/[$,]/g, "")));
console.log(JSON.stringify({ first: el.writes[0], min: Math.min(...nums.slice(0, -1)), last: el.text, counted: el.attrs["data-counted"] }));''')
        self.assertEqual(got["first"], "$1000.00")
        self.assertGreaterEqual(got["min"], 1000, "no frame shows a bankroll below the $1,000 start on the way up to $1,073.14")
        self.assertEqual((got["last"], got["counted"]), ("$1,073.14", "1"))

    def test_a_bankroll_below_the_start_counts_down_from_1000_not_up_from_zero(self):
        got = js('''
const el = mkEl("$928.40");
Fx.countUp(el, 700); await wait(60);
const nums = el.writes.map((w) => Number(w.replace(/[$,]/g, "")));
console.log(JSON.stringify({ first: el.writes[0], max: Math.max(...nums), last: el.text }));''')
        self.assertEqual(got["first"], "$1000.00")
        self.assertLessEqual(got["max"], 1000)
        self.assertEqual(got["last"], "$928.40")

    def test_a_bankroll_that_equals_the_start_does_not_animate(self):
        got = js('const el = mkEl("$1,000.00"); Fx.countUp(el, 700); await wait(40); console.log(JSON.stringify([el.writes.length, el.text]));')
        self.assertEqual(got, [0, "$1,000.00"])

    def test_a_non_dollar_figure_still_counts_from_zero_and_data_count_from_wins(self):
        got = js('''
const pct = mkEl("+7.3%"); Fx.countUp(pct, 700);
const from = mkEl("$1,500.00", { "data-count-from": "1400" }); Fx.countUp(from, 700);
await wait(60);
console.log(JSON.stringify([pct.writes[0], pct.text, from.writes[0], from.text]));''')
        self.assertEqual(got, ["+0.0%", "+7.3%", "$1400.00", "$1,500.00"])


@unittest.skipUnless(HAS_NODE, "node not installed")
class HiddenTabAndReducedMotionShowTheFinalNumber(unittest.TestCase):
    def test_a_hidden_tab_gets_the_final_text_with_no_animation(self):
        got = js('''
document.visibilityState = "hidden";
const a = mkEl("$1,073.14"), b = mkEl("+7.3%");
Fx.countUp(a, 700); Fx.countUp(b, 700); await wait(40);
console.log(JSON.stringify([a.writes.length, a.text, b.writes.length, b.text, Fx.tabHidden()]));''')
        self.assertEqual(got, [0, "$1,073.14", 0, "+7.3%", True])

    def test_hiding_the_tab_mid_count_finishes_on_the_real_value(self):
        got = js('''
globalThis.requestAnimationFrame = (fn) => { globalThis.pending = fn; };
const el = mkEl("$1,073.14");
Fx.countUp(el, 700);
const midText = el.text;
document.visibilityState = "hidden";
for (const f of document.listeners) f();
console.log(JSON.stringify([midText, el.text, document.listeners.length]));''')
        self.assertEqual(got[0], "$1000.00")
        self.assertEqual(got[1], "$1,073.14")
        self.assertEqual(got[2], 0, "the visibility listener is removed once the count has finished")

    def test_reduced_motion_leaves_the_text_alone(self):
        got = js('const el = mkEl("$1,073.14"); Fx.countUp(el, 700); await wait(40); console.log(JSON.stringify([el.writes.length, el.text]));', reduced=True)
        self.assertEqual(got, [0, "$1,073.14"])

    def test_the_landing_race_shows_the_finished_race_in_a_hidden_tab(self):
        race = (ROOT / "web" / "js" / "landing-race.js").read_text(encoding="utf-8")
        self.assertIn('document.visibilityState === "hidden") { finish();', race)


if __name__ == "__main__":
    unittest.main()
