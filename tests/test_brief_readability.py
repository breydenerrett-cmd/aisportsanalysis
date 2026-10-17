"""The sample brief and the analyst section, read as a person reads them.

Owner brief 2026-10-17. The published text of a brief is frozen and must not
change, but a reader met "a 2.4712 ERA and 3.5027 FIP", "98.33 innings", "the
wind is 12.1 mph from 306 degrees" and "the books' 0.5511". The display layer
(web/js/numfmt.js, used by web/js/analyst.js and web/js/sample.js) now shows the
figure a person would say, keeps the exact published text on the element's
`title`, and never changes a word of the stored brief. Also pinned here: the call
comes first in each call's heading with its result badge beside it, "What the
analysis could not use" reads as a short list in plain words, and the sample
page's live-sports sentence comes from the one constant in web/js/dom.js.

The real modules run under node against a small fake DOM (the pattern of
tests/test_analyst_web.py and tests/test_sample_brief.py); every input is a
fixture in this file, so no store on disk decides the result.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
JS = WEB / "js"

HARNESS = r"""
class TextNode {
  constructor(t) { this.nodeType = 3; this.textContent = String(t); this.parentNode = null; }
}
class Elem {
  constructor(tag) {
    this.nodeType = 1; this.tagName = String(tag).toUpperCase(); this.attrs = {};
    this.childNodes = []; this.parentNode = null;
  }
  get children() { return this.childNodes.filter((c) => c.nodeType === 1); }
  get firstChild() { return this.childNodes[0] || null; }
  appendChild(c) { if (c.parentNode) c.parentNode.removeChild(c); c.parentNode = this; this.childNodes.push(c); return c; }
  removeChild(c) { const i = this.childNodes.indexOf(c); if (i >= 0) this.childNodes.splice(i, 1); c.parentNode = null; return c; }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; }
  set textContent(v) { const t = new TextNode(v); t.parentNode = this; this.childNodes = [t]; }
  get textContent() { return this.childNodes.map((c) => c.textContent).join(""); }
  addEventListener() {}
  _all(out) { for (const c of this.children) { out.push(c); c._all(out); } return out; }
}
globalThis.document = {
  createElement: (t) => new Elem(t), createTextNode: (t) => new TextNode(t),
  querySelector: () => null, querySelectorAll: () => [], addEventListener() {},
};
globalThis.window = { location: { search: "", host: "t", pathname: "/", hash: "" }, addEventListener() {} };

const scenario = JSON.parse(process.env.SCENARIO);
const out = {};
if (scenario.kind === "prose") {
  const { formatProse, proseText } = await import("./numfmt.js");
  out.rows = scenario.texts.map((t) => ({ text: proseText(t), pieces: formatProse(t) }));
} else {
  const { renderSample } = await import("./sample.js");
  const { SPORTS_LIVE_TODAY } = await import("./dom.js");
  const page = renderSample(scenario.data);
  const all = page._all([]);
  const byHook = (h) => all.filter((n) => n.attrs["data-hook"] === h);
  const calls = byHook("analyst-call").map((call) => {
    const head = call.children.find((c) => c.attrs.class === "an-call__head");
    return {
      verdict: call.attrs["data-verdict"],
      headParts: head.children.map((c) => ({ hook: c.attrs["data-hook"] || c.attrs.class, text: c.textContent, title: c.attrs.title || null })),
      afterHead: call.children.filter((c) => c !== head).map((c) => c.attrs.class || c.attrs["data-hook"]),
      text: call.textContent,
    };
  });
  out.calls = calls;
  out.summaries = byHook("analyst-summary").map((n) => ({ text: n.textContent, spans: n.children.map((s) => ({ text: s.textContent, title: s.attrs.title })) }));
  out.missing = byHook("analyst-missing").flatMap((m) => m._all([]).filter((n) => n.tagName === "LI").map((li) => ({ text: li.textContent, title: li.attrs.title || null })));
  out.pageText = page.textContent;
  out.live = byHook("sample-live-today").map((n) => n.textContent);
  out.liveConstant = SPORTS_LIVE_TODAY;
  out.offer = byHook("sample-offer").map((n) => n.textContent);
  out.rounding = byHook("sample-rounding").map((n) => n.textContent);
}
console.log("@@" + JSON.stringify(out));
"""

# The wording below is the published wording of the SD at MIL brief (frozen), copied as fixtures.
SUMMARY = (
    "I lean Milwaukee at -128. Logan Henderson has the better numbers going in, with a 2.4712 ERA and "
    "3.5027 FIP against 3.2108 and 4.1311 for Michael King, and Milwaukee's run differential per game is "
    "1.319 against San Diego's 0.259. I put Milwaukee a few points above the books' 0.5511, so my number "
    "is only a little off the price. Henderson has only 98.33 innings this year.\n\n"
    "Both starters are strong, the wind is 12.1 mph from 306 degrees, and the packet does not say if the "
    "roof is open."
)


def _call(slot="moneyline", verdict="TAKE", selection="MIL", price=-128, fair=0.58, result=None, **extra):
    call = {
        "slot_id": slot, "market": slot, "family": slot, "selection": selection, "verdict": verdict,
        "price": price, "book": "lowvig", "fair_estimate": fair, "confidence": "medium",
        "reasons": [{"claim": "Henderson's ERA is 2.4712 against 3.2108 for King.", "evidence": [
            {"path": "sections.starters.values.home_sp_era", "value": 2.4712}]}],
        "case_against": None, "pass_price": None, "what_would_change_it": None,
        "verification": {"status": "verified", "problems": []},
    }
    if result:
        call["result"] = result
    call.update(extra)
    return call


def _brief(calls, missing, graded=False):
    return {
        "available": True, "label": "Written by an AI model in a supervised session. Unproven. Analysis, not advice.",
        "first_pitch_utc": "2026-10-04T20:00:00Z", "published_utc": "2026-10-04T16:54:32Z", "reason": None,
        "analysis": {
            "game_id": "SD-MIL-2026-10-04-1", "date": "2026-10-04", "away": "SD", "home": "MIL",
            "published_utc": "2026-10-04T16:54:32Z", "summary": SUMMARY, "summary_status": "ok",
            "summary_derivations": [], "calls": calls, "missing": missing, "graded": graded,
            "final": {"away_score": 2, "home_score": 3} if graded else None,
        },
    }


MISSING = [
    {"item": "props", "kind": "thin",
     "reason": "4 prop contracts were priced; 0 are analyzed (the rest are left out by the per-game cap)"},
    {"item": "standings", "kind": "absent", "reason": "no standings snapshot stored for 2026-10-04"},
    {"item": "lineups.away", "kind": "absent", "reason": "lineup not posted yet"},
    {"item": "team_totals", "kind": "stale", "reason": "team-total prices are hours old"},
]


@unittest.skipUnless(shutil.which("node"), "node not installed")
class TheBriefReadsLikeAPersonWroteIt(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        for path in JS.glob("*.js"):
            shutil.copy(path, cls._tmp.name)
        Path(cls._tmp.name, "package.json").write_text('{"type": "module"}', encoding="utf-8")
        Path(cls._tmp.name, "harness.mjs").write_text(HARNESS, encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def run_scenario(self, **scenario):
        env = dict(os.environ, SCENARIO=json.dumps(scenario))
        proc = subprocess.run(["node", "harness.mjs"], cwd=self._tmp.name, env=env,
                              capture_output=True, text=True, encoding="utf-8", timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr[-2000:])
        line = [ln for ln in proc.stdout.splitlines() if ln.startswith("@@")][-1]
        return json.loads(line[2:])

    def prose(self, *texts):
        return self.run_scenario(kind="prose", texts=list(texts))["rows"]

    # ---- the formatter ----------------------------------------------------

    def test_stat_lines_come_out_at_two_decimals(self):
        row, = self.prose("with a 2.4712 ERA and 3.5027 FIP against 3.2108 and 4.1311 for Michael King")
        self.assertEqual(row["text"], "with a 2.47 ERA and 3.50 FIP against 3.21 and 4.13 for Michael King")

    def test_run_differential_and_woba_at_two_decimals(self):
        a, b, c = self.prose("run differential per game is 1.319 against San Diego's 0.259",
                             "a lead of 1.0315 runs", "the lineup's wOBA of 0.3797 against the sinker")
        self.assertEqual(a["text"], "run differential per game is 1.32 against San Diego's 0.26")
        self.assertEqual(b["text"], "a lead of 1.03 runs")
        self.assertEqual(c["text"], "the lineup's wOBA of 0.38 against the sinker")

    def test_a_probability_becomes_a_whole_percent(self):
        a, b, c = self.prose("I put Milwaukee a few points above the books' 0.5511",
                             "with the over at 0.5092 fair probability",
                             "ATL at +199 sits close to the books' own fair probability of 0.3323")
        self.assertEqual(a["text"], "I put Milwaukee a few points above the books' 55%")
        self.assertEqual(b["text"], "with the over at 51% fair probability")
        self.assertTrue(c["text"].endswith("fair probability of 33%"))

    def test_innings_are_written_as_thirds_not_as_a_decimal_that_baseball_reads_wrong(self):
        a, b = self.prose("Henderson has only 98.33 innings this year", "he threw 61.67 innings")
        self.assertEqual(a["text"], "Henderson has only 98⅓ innings this year")
        self.assertEqual(b["text"], "he threw 61⅔ innings")

    def test_wind_degrees_become_a_compass_direction(self):
        a, b, c = self.prose("the wind is 12.1 mph from 306 degrees", "wind from 90 degrees", "from 190 degrees")
        self.assertEqual(a["text"], "the wind is 12.1 mph from the northwest")
        self.assertEqual(b["text"], "wind from the east")
        self.assertEqual(c["text"], "from the south")
        self.assertEqual([p.get("title") for p in a["pieces"] if p.get("title")], ["from 306 degrees"])

    def test_the_exact_value_is_kept_on_a_title(self):
        row, = self.prose("a 2.4712 ERA, the books' 0.5511 and 98.33 innings")
        titles = [p["title"] for p in row["pieces"] if p.get("title")]
        self.assertEqual(titles, ["2.4712", "0.5511", "98.33 innings"])

    def test_the_published_words_are_never_lost(self):
        """Putting every title back where its figure stands rebuilds the published text exactly."""
        texts = [SUMMARY, "no figure here at all", "-185 and 7.5 and 11.9 mph and 98.1 innings and 55%"]
        for text, row in zip(texts, self.prose(*texts)):
            rebuilt = "".join(p.get("title", p["text"]) for p in row["pieces"])
            self.assertEqual(rebuilt, text)

    def test_numbers_already_short_are_left_alone(self):
        text = "SD +1.5 at -185, a total of 7.5, wind 11.9 mph, 98.1 innings, 55% and 29 games"
        row, = self.prose(text)
        self.assertEqual(row["text"], text)
        self.assertTrue(all("title" not in p for p in row["pieces"]))

    def test_a_two_decimal_probability_becomes_a_percent_only_beside_plain_probability_words(self):
        a, b, c = self.prose("the books' own de-vigged numbers put SD +1.5 near 0.63 and MIL -1.5 near 0.37",
                             "a closer with a 0.95 ERA", "a lead of 0.25 runs after the books close")
        self.assertEqual(a["text"], "the books' own de-vigged numbers put SD +1.5 near 63% and MIL -1.5 near 37%")
        self.assertEqual(b["text"], "a closer with a 0.95 ERA")
        self.assertEqual(c["text"], "a lead of 0.25 runs after the books close")

    def test_a_decimal_with_no_probability_words_is_never_turned_into_a_percent(self):
        row, = self.prose("his strikeout-minus-walk gap is 0.1176 here, and a mystery 0.4321 appears")
        # The first has words around it; the second has none and stays a decimal.
        self.assertIn("0.43", row["text"])
        self.assertNotIn("43%", row["text"])

    # ---- the rendered brief -------------------------------------------------

    def render(self, calls, missing=None, graded=False):
        return self.run_scenario(kind="sample", data=_brief(calls, MISSING if missing is None else missing, graded))

    def test_the_summary_shows_readable_figures_with_exact_values_on_hover(self):
        out = self.render([_call()])
        text = "\n".join(s["text"] for s in out["summaries"])
        for expected in ("a 2.47 ERA and 3.50 FIP against 3.21 and 4.13", "1.32 against San Diego's 0.26",
                         "above the books' 55%", "98⅓ innings", "12.1 mph from the northwest"):
            self.assertIn(expected, text)
        titles = {span["title"] for s in out["summaries"] for span in s["spans"]}
        self.assertTrue({"2.4712", "3.5027", "0.5511", "98.33 innings", "from 306 degrees"} <= titles, titles)
        self.assertIsNone(re.search(r"\d\.\d{3,}", out["pageText"]), out["pageText"])

    def test_the_call_leads_its_heading_and_the_result_sits_beside_it(self):
        out = self.render([_call(result="WIN")], graded=True)
        call, = out["calls"]
        kinds = [p["hook"] for p in call["headParts"]]
        self.assertEqual(kinds, ["analyst-verdict", "an-call__what", "analyst-price", "analyst-estimate",
                                 "analyst-result"])
        parts = {p["hook"]: p["text"] for p in call["headParts"]}
        self.assertEqual(parts["analyst-verdict"], "Take")
        self.assertEqual(parts["an-call__what"], "MIL moneyline")
        self.assertEqual(parts["analyst-price"], "-128 at Lowvig" if "Lowvig" in parts["analyst-price"] else parts["analyst-price"])
        self.assertTrue(parts["analyst-price"].startswith("-128"))
        self.assertEqual(parts["analyst-estimate"], "analyst 58% vs price needs 56%")
        self.assertEqual(parts["analyst-result"], "Won")
        # Nothing about the result is left for the bottom of the call.
        self.assertNotIn("an-call__result", call["afterHead"])
        self.assertNotIn("analyst-result", call["afterHead"])

    def test_a_pass_and_a_plus_money_take_get_the_same_heading(self):
        calls = [_call("run_line", "PASS", "SD +1.5", -185, 0.64), _call("total", "TAKE", "Over 7", 135, 0.5)]
        out = self.render(calls)
        first, second = out["calls"]
        self.assertEqual({p["hook"]: p["text"] for p in first["headParts"]}["analyst-estimate"],
                         "analyst 64% vs price needs 65%")
        self.assertEqual({p["hook"]: p["text"] for p in second["headParts"]}["analyst-estimate"],
                         "analyst 50% vs price needs 43%")
        self.assertEqual({p["hook"]: p["text"] for p in first["headParts"]}["an-call__what"], "SD +1.5 run line")

    def test_no_estimate_means_no_comparison_is_invented(self):
        out = self.render([_call(fair=None, price=None)])
        hooks = [p["hook"] for p in out["calls"][0]["headParts"]]
        self.assertNotIn("analyst-estimate", hooks)

    def test_what_the_analysis_could_not_use_is_a_short_list_in_plain_words(self):
        out = self.render([_call()])
        lines = [m["text"] for m in out["missing"]]
        self.assertEqual(lines, ["Player props: too little to go on.", "Standings: not available.",
                                 "Lineups (away): not available.", "Team totals: out of date."])
        by_text = {m["text"]: m["title"] for m in out["missing"]}
        self.assertEqual(by_text["Standings: not available."], "no standings snapshot stored for 2026-10-04")
        self.assertIn("4 prop contracts were priced", by_text["Player props: too little to go on."])

    def test_the_page_says_the_numbers_are_rounded_and_where_to_find_the_exact_ones(self):
        out = self.render([_call()])
        self.assertEqual(len(out["rounding"]), 1)
        self.assertIn("rounded for reading", out["rounding"][0])
        self.assertIn("exact", out["rounding"][0])

    def test_the_sample_page_names_no_season_and_takes_live_sports_from_the_one_constant(self):
        out = self.render([_call()])
        self.assertEqual(out["live"], [out["liveConstant"]])
        self.assertIn("MLB postseason", out["liveConstant"])
        self.assertNotIn("postseason", out["offer"][0].lower())
        self.assertNotIn("(MLB postseason)", out["pageText"])
        self.assertIn("A brief for every game we cover, posted before it starts.", out["offer"][0])


if __name__ == "__main__":
    unittest.main()
