"""THE READ on the game page: web/js/matchupread.js, wired into games.js.

Two halves, the pattern of tests/test_card_record_v2_rows.py:

  * static checks: the read sits above every table on the game route, the page
    imports one renderer, the stylesheet holds at 390px (no fixed widths, no
    nowrap, wrapping on every text node), and nothing in the module renders a
    developer word or the retired price-comparison register;
  * a behavioural half that runs the real matchupread.js under node against a
    small fake DOM, on the real read for 2026-10-03's CWS@CLE and ATL@LAD
    (frozen in tests/fixtures/). Skipped when node is missing. It checks what a
    person would see: the headline, the factors in order with their chips, the
    evidence under a native toggle, the run estimate, the market paragraph, what
    would change it, and the list of what we could not use.
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
JS = ROOT / "web" / "js"
CSS = ROOT / "web" / "css" / "gamestory.css"
FIXTURES = ROOT / "tests" / "fixtures"
READ_JS = (JS / "matchupread.js").read_text(encoding="utf-8")
GAMES_JS = (JS / "games.js").read_text(encoding="utf-8")


def _fixture_read(away, home):
    path = FIXTURES / f"matchup_read_2026-10-03_{away}_{home}.json"
    return json.loads(path.read_text(encoding="utf-8"))["read"]


# ---------------------------------------------------------------------------
# Static
# ---------------------------------------------------------------------------

class TheReadIsWiredAboveTheTables(unittest.TestCase):
    def test_games_js_imports_the_one_renderer(self):
        self.assertIn('import { renderMatchupRead } from "./matchupread.js";', GAMES_JS)

    def test_the_read_is_appended_before_every_table_on_the_game_route(self):
        body = GAMES_JS.split("export async function renderGameDetail(")[1]
        read_at = body.index("renderMatchupRead(payload.read)")
        for later in ("gqvPrice(quick, live)", "renderLineMarkets(oddsEntry, live)",
                      "renderGameStory(advanced, quick)",
                      "gqvTeams(advanced, quick)", "gqvActions(date, away, home)",
                      "renderAdvancedV2(advanced, quick)"):
            self.assertLess(read_at, body.index(later), later)

    def test_the_read_follows_the_pick_so_the_bet_still_leads(self):
        body = GAMES_JS.split("export async function renderGameDetail(")[1]
        self.assertLess(body.index("gqvTonightsPick(cardPick, quick)"),
                        body.index("renderMatchupRead(payload.read)"))

    def test_a_missing_read_renders_nothing_and_does_not_break_the_page(self):
        self.assertIn("if (matchupRead) body.appendChild(matchupRead);", GAMES_JS)

    def test_the_module_touches_no_network_and_no_script_tag(self):
        for token in ("apiGet", "fetch(", "<script", "innerHTML", "eval("):
            self.assertNotIn(token, READ_JS, token)

    def test_the_evidence_toggle_is_a_native_details_element(self):
        self.assertIn('el("details"', READ_JS)
        self.assertIn('el("summary"', READ_JS)

    def test_no_table_is_rendered(self):
        for token in ('"table"', '"tr"', '"td"', '"th"'):
            self.assertNotIn(token, READ_JS, token)


class TheReadHoldsAt390Pixels(unittest.TestCase):
    def setUp(self):
        css = CSS.read_text(encoding="utf-8")
        start = css.index("THE READ -- web/js/matchupread.js")
        self.block = css[start:]

    def test_every_text_node_wraps(self):
        self.assertIn(".mr-read, .mr-read * { overflow-wrap: anywhere;", self.block)

    def test_no_rule_forbids_wrapping_or_fixes_a_wide_width(self):
        self.assertNotIn("nowrap", self.block)
        for match in re.finditer(r"(?<![-\w])(?:min-)?width:\s*(\d+)px", self.block):
            self.assertLess(int(match.group(1)), 300, match.group(0))

    def test_no_horizontal_scroll_container_is_introduced(self):
        self.assertNotIn("overflow-x", self.block)
        self.assertNotIn("overflow: auto", self.block)
        self.assertNotIn("grid-template-columns", self.block)

    def test_the_layout_is_a_single_column_flow(self):
        self.assertIn("flex-direction: column", self.block)

    def test_the_narrow_breakpoint_tightens_the_padding(self):
        self.assertIn("@media (max-width: 899px)", self.block)


class TheReadSpeaksToAReader(unittest.TestCase):
    def test_the_developer_and_retired_registers_stay_out_of_the_module(self):
        from tests.test_no_developer_notes_on_screen import DEVELOPER_WORDS, _rendered_strings
        from tests.test_web_register_sweep import RETIRED
        offenders = []
        for line_no, text in _rendered_strings(JS / "matchupread.js"):
            lowered = text.lower()
            for word, _why in DEVELOPER_WORDS:
                if re.search(rf"\b{re.escape(word)}\b", lowered):
                    offenders.append((line_no, word))
            for phrase in RETIRED:
                if phrase in lowered:
                    offenders.append((line_no, phrase))
        self.assertEqual(offenders, [])

    def test_the_static_strings_carry_no_dash_no_lock_and_no_guarantee(self):
        for pattern in ("—", "–", "lock", "guarantee", "profit", "win probability"):
            self.assertNotIn(pattern, READ_JS.replace("block", "").lower(), pattern)


# ---------------------------------------------------------------------------
# Behavioural: the real matchupread.js under node
# ---------------------------------------------------------------------------

HARNESS = r"""
class TextNode {
  constructor(t) { this.nodeType = 3; this.textContent = String(t); this.parentNode = null; }
}
class Elem {
  constructor(tag) {
    this.nodeType = 1; this.tagName = String(tag).toUpperCase(); this.attrs = {};
    this.childNodes = []; this.parentNode = null; this.style = {};
  }
  get children() { return this.childNodes.filter((c) => c.nodeType === 1); }
  get firstChild() { return this.childNodes[0] || null; }
  appendChild(c) {
    if (c.parentNode) c.parentNode.removeChild(c);
    c.parentNode = this; this.childNodes.push(c); return c;
  }
  removeChild(c) {
    const i = this.childNodes.indexOf(c); if (i >= 0) this.childNodes.splice(i, 1);
    c.parentNode = null; return c;
  }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; }
  set hidden(v) { if (v) this.attrs.hidden = ""; else delete this.attrs.hidden; }
  get hidden() { return "hidden" in this.attrs; }
  set textContent(v) { const t = new TextNode(v); t.parentNode = this; this.childNodes = [t]; }
  get textContent() { return this.childNodes.map((c) => c.textContent).join(""); }
  get classList() { const self = this; return { add(c) { self.attrs.class = ((self.attrs.class || "") + " " + c).trim(); }, remove() {} }; }
  addEventListener() {}
  _all(out) { for (const c of this.children) { out.push(c); c._all(out); } return out; }
}

const body = new Elem("body");
globalThis.document = {
  createElement: (t) => new Elem(t),
  createTextNode: (t) => new TextNode(t),
  body, referrer: "",
  addEventListener() {},
  querySelector: () => null,
  querySelectorAll: () => [],
};
const store = new Map();
globalThis.window = {
  localStorage: {
    getItem: (k) => (store.has(k) ? store.get(k) : null),
    setItem: (k, v) => store.set(k, String(v)),
    removeItem: (k) => store.delete(k),
  },
  location: { search: "", host: "linehound.test", pathname: "/", hash: "" },
  history: { replaceState() {} },
  addEventListener() {}, dispatchEvent() { return true; },
  crypto: globalThis.crypto,
};
globalThis.fetch = async () => ({ ok: true, status: 200, text: async () => "{}" });

const scenario = JSON.parse(process.env.SCENARIO);
const text = (n) => (n.nodeType === 3 ? n.textContent : n.childNodes.map(text).join("\n"));
const inside = (n, pred) => { for (let p = n.parentNode; p; p = p.parentNode) { if (p.attrs && pred(p)) return true; } return false; };

const { renderMatchupRead, FACTORS_SHOWN } = await import("./matchupread.js");
const out = { factorsShown: FACTORS_SHOWN, results: [] };
for (const read of scenario.reads) {
  const node = renderMatchupRead(read);
  if (node === null) { out.results.push(null); continue; }
  const all = node._all([]);
  const hook = (h) => all.filter((n) => n.attrs["data-hook"] === h);
  const factors = hook("read-factor");
  out.results.push({
    tag: node.tagName,
    cls: node.attrs.class,
    rootHook: node.attrs["data-hook"],
    text: text(node),
    headline: (hook("read-headline")[0] || { textContent: null }).textContent,
    notices: hook("read-notice").map((n) => n.textContent),
    factorKeys: factors.map((n) => n.attrs["data-factor"]),
    topFactorKeys: factors.filter((n) => !inside(n, (p) => p.attrs["data-hook"] === "read-more-factors")).map((n) => n.attrs["data-factor"]),
    moreSummary: (hook("read-more-factors")[0] ? hook("read-more-factors")[0].children[0].textContent : null),
    tables: all.filter((n) => ["TABLE", "TR", "TD", "TH"].includes(n.tagName)).length,
    scripts: all.filter((n) => n.tagName === "SCRIPT").length,
    detailsCount: all.filter((n) => n.tagName === "DETAILS").length,
    allDetailsHaveSummary: all.filter((n) => n.tagName === "DETAILS").every((d) => d.children[0] && d.children[0].tagName === "SUMMARY"),
    evidenceSummaries: hook("read-evidence").map((d) => d.children[0].textContent),
    evidenceRows: hook("read-evidence").map((d) => d._all([]).filter((n) => n.attrs.class === "mr-evidence__row").length),
    factorChips: factors.map((f) => f._all([]).filter((n) => (n.attrs.class || "").split(" ").includes("mr-chip")).map((n) => n.textContent)),
    factorWarnChips: factors.map((f) => f._all([]).filter((n) => (n.attrs.class || "").includes("mr-chip--warn")).length),
    factorSentences: factors.map((f) => f._all([]).filter((n) => n.attrs.class === "mr-factor__sentence").map((n) => n.textContent)[0]),
    factorCaveats: factors.map((f) => f._all([]).filter((n) => n.attrs.class === "mr-factor__caveat").map((n) => n.textContent)[0] || null),
    hooks: all.map((n) => n.attrs["data-hook"]).filter(Boolean),
    runsText: (hook("read-runs")[0] ? text(hook("read-runs")[0]) : null),
    arithmeticLines: (hook("read-arithmetic")[0] ? hook("read-arithmetic")[0]._all([]).filter((n) => n.tagName === "P").length : 0),
    marketText: (hook("read-market")[0] ? text(hook("read-market")[0]) : null),
    changeItems: (hook("read-change")[0] ? hook("read-change")[0]._all([]).filter((n) => n.attrs.class === "mr-list__item").length : 0),
    missingItems: (hook("read-missing")[0] ? hook("read-missing")[0]._all([]).filter((n) => n.attrs.class === "mr-list__item").length : 0),
    missingText: (hook("read-missing")[0] ? text(hook("read-missing")[0]) : null),
  });
}
console.log("@@" + JSON.stringify(out));
"""


@unittest.skipUnless(shutil.which("node"), "node not installed")
class TheReadRendersUnderNode(unittest.TestCase):
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

    def render(self, *reads):
        env = dict(os.environ, SCENARIO=json.dumps({"reads": list(reads)}))
        proc = subprocess.run(["node", "harness.mjs"], cwd=self._tmp.name, env=env,
                              capture_output=True, text=True, encoding="utf-8", timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr[-2000:])
        line = [ln for ln in proc.stdout.splitlines() if ln.startswith("@@")][-1]
        out = json.loads(line[2:])
        self.shown = out["factorsShown"]
        return out["results"]

    # ---- nothing to show ------------------------------------------------

    def test_no_read_renders_nothing(self):
        for empty in (None, {}, {"factors": []}, "nope", 7):
            with self.subTest(empty=empty):
                self.assertEqual(self.render(empty), [None])

    # ---- the real read for CWS@CLE --------------------------------------

    def cle(self):
        read = _fixture_read("CWS", "CLE")
        return read, self.render(read)[0]

    def test_it_is_one_section_with_the_read_hooks(self):
        _, out = self.cle()
        self.assertEqual(out["tag"], "SECTION")
        self.assertIn("mr-read", out["cls"])
        self.assertEqual(out["rootHook"], "matchup-read")
        for hook in ("read-headline", "read-runs", "read-market",
                     "read-change", "read-missing", "read-arithmetic"):
            self.assertIn(hook, out["hooks"], hook)

    def test_the_headline_is_the_servers_sentence_verbatim(self):
        read, out = self.cle()
        self.assertEqual(out["headline"], read["headline"])

    def test_the_notices_print(self):
        read, out = self.cle()
        self.assertEqual(out["notices"], read["notices"])
        self.assertTrue([n for n in out["notices"] if "under way" in n])

    def test_factors_print_in_the_servers_rank_order(self):
        read, out = self.cle()
        self.assertEqual(out["factorKeys"], [f["factor"] for f in read["factors"]])

    def test_only_the_top_factors_print_open_and_the_rest_fold_into_one_toggle(self):
        read, out = self.cle()
        n = len(read["factors"])
        self.assertGreater(n, self.shown)
        self.assertEqual(out["topFactorKeys"], [f["factor"] for f in read["factors"]][:self.shown])
        self.assertEqual(out["moreSummary"], f"SMALLER FACTORS ({n - self.shown})")

    def test_each_factor_prints_its_sentence_and_its_caveat_outside_the_toggle(self):
        read, out = self.cle()
        self.assertEqual(out["factorSentences"], [f["sentence"] for f in read["factors"]])
        self.assertEqual(out["factorCaveats"], [f["caveat"] for f in read["factors"]])

    def test_each_factor_carries_side_size_and_confidence_chips(self):
        read, out = self.cle()
        for f, chips in zip(read["factors"], out["factorChips"]):
            self.assertEqual(len(chips), 3, f["factor"])
            self.assertEqual(chips[1], f["size"].upper())
            self.assertEqual(chips[2], f["confidence"].upper() + " CONFIDENCE")
            if f["favours"] == "even":
                self.assertEqual(chips[0], "NO SIDE")
            else:
                self.assertTrue(chips[0].startswith("FAVOURS "), chips[0])

    def test_a_low_confidence_factor_wears_the_warning_tone_and_a_solid_one_does_not(self):
        read, out = self.cle()
        saw_low = saw_other = False
        for f, warn in zip(read["factors"], out["factorWarnChips"]):
            if f["confidence"] == "low":
                saw_low = True
                self.assertEqual(warn, 1, f["factor"])
            else:
                saw_other = True
                self.assertEqual(warn, 0, f["factor"])
        self.assertTrue(saw_low and saw_other)

    def test_evidence_sits_under_a_native_toggle_with_one_row_per_item(self):
        read, out = self.cle()
        self.assertEqual(out["evidenceSummaries"],
                         [f"EVIDENCE ({len(f['evidence'])})" for f in read["factors"]
                          if f["evidence"]])
        self.assertEqual(out["evidenceRows"],
                         [len(f["evidence"]) for f in read["factors"] if f["evidence"]])
        self.assertTrue(out["allDetailsHaveSummary"])

    def test_the_run_estimate_prints_both_clubs_and_the_total_with_ranges(self):
        read, out = self.cle()
        env = read["run_environment"]
        self.assertIn("EXPECTED RUNS, AN ESTIMATE", out["runsText"])
        self.assertIn(env["label"], out["runsText"])
        self.assertIn("White Sox: %.1f, range" % env["away"]["expected_runs"], out["runsText"])
        self.assertIn("Guardians: %.1f, range" % env["home"]["expected_runs"], out["runsText"])
        self.assertIn("Game total: %.1f, range" % env["game"]["expected_total"], out["runsText"])
        self.assertEqual(out["arithmeticLines"], len(env["arithmetic"]) + len(env["caveats"]))

    def test_the_market_paragraph_and_the_change_list_and_the_missing_list_print(self):
        read, out = self.cle()
        for sentence in read["market_view"]["sentences"]:
            self.assertIn(sentence, out["marketText"])
        self.assertEqual(out["changeItems"], len(read["what_would_change_it"]))
        self.assertEqual(out["missingItems"], len(read["missing"]))
        self.assertIn(f"WHAT WE COULD NOT USE ({len(read['missing'])})", out["missingText"])
        self.assertIn("STALE", out["missingText"])
        self.assertIn("our pitcher logs end 2026-09-07", out["missingText"])

    def test_nothing_renders_as_a_table_a_script_or_a_raw_value(self):
        _, out = self.cle()
        self.assertEqual(out["tables"], 0)
        self.assertEqual(out["scripts"], 0)
        for bad in ("undefined", "NaN", "[object", "null"):
            self.assertNotIn(bad, out["text"], bad)

    def test_no_field_name_is_shown_to_the_reader(self):
        _, out = self.cle()
        leaked = re.findall(r"\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b", out["text"])
        self.assertEqual(leaked, [])

    def test_no_dash_no_lock_no_guarantee_on_screen(self):
        for away, home in (("CWS", "CLE"), ("ATL", "LAD"), ("NYY", "TB"), ("SD", "MIL")):
            out = self.render(_fixture_read(away, home))[0]
            lowered = out["text"].lower()
            for banned in ("—", "–", "guarantee", "free money", "profit",
                           "win probability"):
                self.assertNotIn(banned, lowered, f"{away}@{home}: {banned}")
            self.assertIsNone(re.search(r"\block\b", lowered), f"{away}@{home}")

    # ---- the other three real reads ---------------------------------------

    def test_all_four_real_reads_render_with_their_own_headlines(self):
        reads = [_fixture_read(a, h) for a, h in (("CWS", "CLE"), ("ATL", "LAD"),
                                                  ("NYY", "TB"), ("SD", "MIL"))]
        outs = self.render(*reads)
        for read, out in zip(reads, outs):
            self.assertEqual(out["headline"], read["headline"])
            self.assertEqual(out["missingItems"], len(read["missing"]))
            self.assertEqual(out["tables"], 0)

    def test_a_read_with_few_factors_has_no_smaller_factors_toggle(self):
        read = _fixture_read("ATL", "LAD")
        out = self.render(read)[0]
        if len(read["factors"]) <= self.shown:
            self.assertIsNone(out["moreSummary"])
            self.assertNotIn("read-more-factors", out["hooks"])

    def test_a_read_with_no_factors_says_so_and_still_prints_the_rest(self):
        read = dict(_fixture_read("ATL", "LAD"), factors=[])
        out = self.render(read)[0]
        self.assertIn("No factor could be built from the data on this page.", out["text"])
        self.assertEqual(out["factorKeys"], [])
        self.assertIn("read-missing", out["hooks"])

    def test_an_unavailable_run_estimate_prints_its_reason_not_numbers(self):
        read = _fixture_read("ATL", "LAD")
        read["run_environment"] = {"label": "An estimate.", "available": False,
                                   "reason": "no league run rate could be measured",
                                   "arithmetic": [], "caveats": [], "evidence": []}
        out = self.render(read)[0]
        self.assertIn("no league run rate could be measured", out["runsText"])
        self.assertNotIn("Game total", out["runsText"])
        self.assertNotIn("read-arithmetic", out["hooks"])

    def test_a_factor_with_no_evidence_has_no_empty_toggle(self):
        read = _fixture_read("NYY", "TB")
        read["factors"][0] = dict(read["factors"][0], evidence=[])
        out = self.render(read)[0]
        self.assertEqual(len(out["evidenceSummaries"]),
                         len([f for f in read["factors"] if f["evidence"]]))

    def test_a_derived_evidence_item_says_it_was_worked_out(self):
        read = _fixture_read("CWS", "CLE")
        out = self.render(read)[0]
        self.assertIn("(worked out from the lines on this page)", out["text"])


if __name__ == "__main__":
    unittest.main()
