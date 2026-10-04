"""The analyst on the page: the game section and the record table.

Two halves, the pattern of tests/test_card_record_v2_rows.py:

  * static checks on web/js/analyst.js and the three places it is wired in;
  * a behavioural half that runs the real analyst.js under node against a small
    fake DOM. Skipped when node is missing. It imports nothing from `api.*`.
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
ANALYST_JS = (JS / "analyst.js").read_text(encoding="utf-8")
LABEL = "Written by an AI model from the data on this page. Unproven. Analysis, not advice."

BANNED = (
    (r"\bedge\b", "edge"), (r"\bprofit(?:s|able)?\b", "profit"), (r"\block(?:s|ed|ing)?\b", "lock"),
    (r"\bsharp\b", "sharp"), (r"\bwinning\b", "winning"), (r"\bguarantee[sd]?\b", "guaranteed"),
    (r"(?i)bet[\s-]*check", "Bet Check"), (r"!", "exclamation mark"),
    (r"(?i)nothing clears the bar", "nothing clears the bar"),
    (r"\bpayload\b", "payload"), (r"\bendpoint\b", "endpoint"),
)


def _string_literals(source: str) -> list:
    code = re.sub(r"/\*.*?\*/", " ", source, flags=re.S)
    code = "\n".join(line for line in code.splitlines() if not line.strip().startswith("//"))
    literals = re.findall(r'"(?:[^"\\\n]|\\.)*"|`(?:[^`\\]|\\.)*`', code)
    return [lit[1:-1] for lit in literals]


class StaticChecks(unittest.TestCase):
    def test_the_label_is_the_exact_sentence(self):
        self.assertIn(f'"{LABEL}"', ANALYST_JS)

    def test_no_banned_word_is_in_any_string_the_page_can_show(self):
        offenders = []
        for literal in _string_literals(ANALYST_JS):
            for pattern, name in BANNED:
                if re.search(pattern, literal):
                    offenders.append(f"{name}: {literal[:70]!r}")
        self.assertEqual(offenders, [])

    def test_it_never_computes_a_rate_of_its_own(self):
        # the only division allowed is formatting the server's own fraction
        self.assertNotIn("wins /", ANALYST_JS)
        self.assertNotIn("losses /", ANALYST_JS)
        self.assertNotIn("/ decided", ANALYST_JS)

    def test_it_makes_no_model_call_and_reads_one_route_each(self):
        self.assertIn("/analyst/${encodeURIComponent(date)}", ANALYST_JS)
        self.assertIn('apiGet("/analyst/record")', ANALYST_JS)
        self.assertNotIn("anthropic", ANALYST_JS.lower())

    def test_the_game_page_change_is_one_import_one_fetch_one_append(self):
        games = (JS / "games.js").read_text(encoding="utf-8")
        self.assertEqual(games.count('from "./analyst.js"'), 1)
        self.assertEqual(games.count("renderAnalystSection("), 1)
        self.assertEqual(games.count("fetchAnalyst("), 1)

    def test_the_record_page_mounts_it_only_on_the_live_mlb_rule(self):
        record = (JS / "cardrecord.js").read_text(encoding="utf-8")
        self.assertIn('if (sport === "mlb" && !rule) await mountAnalystRecord(screen);', record)

    def test_the_stylesheet_is_linked_before_the_last_resort_theme(self):
        html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        self.assertLess(html.index("css/analyst.css"), html.index("css/gotcha.css"))
        self.assertTrue((ROOT / "web" / "css" / "analyst.css").exists())


HARNESS = r"""
class TextNode { constructor(t) { this.nodeType = 3; this.textContent = String(t); this.parentNode = null; } }
class Elem {
  constructor(tag) { this.nodeType = 1; this.tagName = String(tag).toUpperCase(); this.attrs = {};
    this.childNodes = []; this.parentNode = null; this.style = {}; }
  get children() { return this.childNodes.filter((c) => c.nodeType === 1); }
  get firstChild() { return this.childNodes[0] || null; }
  appendChild(c) { if (c.parentNode) c.parentNode.removeChild(c); c.parentNode = this; this.childNodes.push(c); return c; }
  removeChild(c) { const i = this.childNodes.indexOf(c); if (i >= 0) this.childNodes.splice(i, 1); c.parentNode = null; return c; }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; }
  set textContent(v) { const t = new TextNode(v); t.parentNode = this; this.childNodes = [t]; }
  get textContent() { return this.childNodes.map((c) => c.textContent).join(""); }
  get classList() { const s = this; return { add(c) { s.attrs.class = ((s.attrs.class || "") + " " + c).trim(); }, remove() {} }; }
  addEventListener() {}
  _all(out) { for (const c of this.children) { out.push(c); c._all(out); } return out; }
}
const body = new Elem("body");
globalThis.document = { createElement: (t) => new Elem(t), createTextNode: (t) => new TextNode(t), body,
  referrer: "", addEventListener() {}, querySelector: () => null, querySelectorAll: () => [] };
const store = new Map();
globalThis.window = { localStorage: { getItem: (k) => (store.has(k) ? store.get(k) : null),
  setItem: (k, v) => store.set(k, String(v)), removeItem: (k) => store.delete(k) },
  location: { search: "", host: "linehound.test", pathname: "/", hash: "" }, history: { replaceState() {} },
  addEventListener() {}, dispatchEvent() { return true; }, crypto: globalThis.crypto };
globalThis.fetch = async () => ({ ok: true, status: 200, text: async () => "{}" });

const scenario = JSON.parse(process.env.SCENARIO);
const text = (n) => (n.nodeType === 3 ? n.textContent : n.childNodes.map(text).join("\n"));
const mod = await import("./analyst.js");
const node = scenario.kind === "record" ? mod.renderAnalystRecord(scenario.data) : mod.renderAnalystSection(scenario.data);
const all = node._all([]);
const hook = (h) => all.filter((n) => n.attrs["data-hook"] === h);
const out = {
  text: text(node),
  firstParagraph: all.find((n) => n.tagName === "P") ? text(all.find((n) => n.tagName === "P")) : null,
  calls: hook("analyst-call").map((n) => ({
    verdict: n.attrs["data-verdict"], cls: n.attrs.class, slot: n.attrs["data-slot"],
    verdictWord: text(n._all([]).find((x) => x.attrs["data-hook"] === "analyst-verdict")),
    verdictCls: n._all([]).find((x) => x.attrs["data-hook"] === "analyst-verdict").attrs.class,
    price: text(n._all([]).find((x) => x.attrs["data-hook"] === "analyst-price")),
    hasPassPrice: n._all([]).some((x) => x.attrs["data-hook"] === "analyst-pass-price"),
    reasons: n._all([]).filter((x) => x.tagName === "LI").map((x) => text(x)),
    result: (n._all([]).find((x) => x.attrs["data-hook"] === "analyst-result") || { textContent: null, childNodes: [] }),
    text: text(n),
  })).map((c) => ({ ...c, result: c.result.childNodes && c.result.childNodes.length ? text(c.result) : null })),
  families: hook("analyst-family").map((n) => n.attrs["data-family"]),
  labelCount: hook("analyst-label").length,
  hooks: all.map((n) => n.attrs["data-hook"]).filter(Boolean),
  rows: hook("analyst-record-row").map((tr) => ({
    family: tr.attrs["data-family"], cells: tr.children.map((c) => text(c)),
    withheld: tr._all([]).some((x) => x.attrs["data-hook"] === "analyst-record-withheld"),
    hasRate: tr._all([]).some((x) => x.attrs["data-hook"] === "analyst-record-rate"),
  })),
};
console.log("@@" + JSON.stringify(out));
"""


def call(slot, verdict, family, **extra):
    base = {"slot_id": slot, "market": family, "family": family, "title": "Moneyline",
            "selection": "NYY", "verdict": verdict, "price": 117, "book": "fanduel",
            "fair_estimate": 0.49, "confidence": "medium",
            "reasons": [{"claim": "The books make the home side the favourite.", "evidence": []},
                        {"claim": "The starters are closer than the price suggests.", "evidence": []}],
            "pass_price": 105, "what_would_change_it": "A lineup change.",
            "verification": {"status": "verified", "problems": []}}
    base.update(extra)
    return base


def view(calls, **extra):
    base = {"game_id": "NYY-TB-2026-10-03-1", "date": "2026-10-03", "away": "NYY", "home": "TB",
            "published_utc": "2026-10-03T17:00:00Z", "model": "m", "version": 1,
            "summary": "First paragraph of the argument.\n\nSecond paragraph.",
            "summary_status": "ok", "calls": calls, "final": None, "graded": False}
    base.update(extra)
    return {"available": True, "label": LABEL, "analysis": base, "reason": None}


def family(taken=0, passes=0, graded=0, wins=0, losses=0, pushes=0, voids=0, rate=None, units=None,
           reason="fewer than 30 graded calls (0 so far)"):
    return {"taken": taken, "taken_other_side": 0, "passes": passes, "graded": graded, "wins": wins,
            "losses": losses, "pushes": pushes, "voids": voids, "unresolved": 0, "win_rate": rate,
            "units": units, "withheld_reason": None if rate is not None else reason}


@unittest.skipUnless(shutil.which("node"), "node not installed")
class TheAnalystRendersUnderNode(unittest.TestCase):
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

    def render(self, kind, data):
        env = dict(os.environ, SCENARIO=json.dumps({"kind": kind, "data": data}))
        proc = subprocess.run(["node", "harness.mjs"], cwd=self._tmp.name, env=env,
                              capture_output=True, text=True, encoding="utf-8", timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr[-2000:])
        line = [ln for ln in proc.stdout.splitlines() if ln.startswith("@@")][-1]
        return json.loads(line[2:])

    # ---- the game section ------------------------------------------------

    def test_the_label_is_the_first_thing_under_the_heading(self):
        out = self.render("section", view([call("moneyline", "TAKE_OTHER_SIDE", "moneyline")]))
        self.assertEqual(out["firstParagraph"], LABEL)
        self.assertEqual(out["labelCount"], 1)
        self.assertIn("AI ANALYST", out["text"])

    def test_the_summary_is_shown_as_paragraphs_before_the_calls(self):
        out = self.render("section", view([call("moneyline", "TAKE", "moneyline")]))
        self.assertIn("First paragraph of the argument.", out["text"])
        self.assertIn("Second paragraph.", out["text"])
        self.assertLess(out["hooks"].index("analyst-summary"), out["hooks"].index("analyst-call"))

    def test_a_pass_is_drawn_exactly_as_plainly_as_a_take(self):
        out = self.render("section", view([
            call("moneyline", "TAKE", "moneyline"),
            call("run_line", "TAKE_OTHER_SIDE", "run_line", title="Run line"),
            call("total", "PASS", "total", title="Game total", selection="Under 7")]))
        take, other, passed = out["calls"]
        self.assertEqual([c["verdictWord"] for c in out["calls"]], ["Take", "Take the other side", "Pass"])
        # same structure for all three: verdict word, price, reasons, pass price, same element classes
        for c in out["calls"]:
            self.assertTrue(c["cls"].startswith("an-call "))
            self.assertEqual(c["verdictCls"], "an-call__verdict")
            self.assertEqual(len(c["reasons"]), 2)
            self.assertTrue(c["hasPassPrice"])
            self.assertIn("117 at FanDuel", c["price"].replace("+", ""))
        self.assertEqual(passed["verdict"], "PASS")
        self.assertIn("Would start to take it at +105", passed["text"])
        self.assertIn("Stops being worth it at +105", take["text"])

    def test_calls_are_grouped_by_market_in_a_fixed_order(self):
        out = self.render("section", view([
            call("prop_01", "PASS", "prop", title="Junior Caminero hits"),
            call("total", "PASS", "total"), call("moneyline", "TAKE", "moneyline"),
            call("team_total_away", "PASS", "team_total"), call("run_line", "PASS", "run_line")]))
        self.assertEqual(out["families"], ["moneyline", "run_line", "total", "team_total", "prop"])
        self.assertIn("Player props", out["text"])
        self.assertIn("Junior Caminero hits: NYY", out["text"])

    def test_a_struck_call_reads_as_a_pass_that_could_not_be_verified(self):
        struck = call("moneyline", "PASS", "moneyline", fair_estimate=None, confidence="low",
                      pass_price=None, what_would_change_it="A call that can be checked against the data.",
                      reasons=[{"claim": "Could not be verified.", "evidence": []}],
                      verification={"status": "could not be verified", "problems": []})
        out = self.render("section", view([struck]))
        c = out["calls"][0]
        self.assertEqual(c["verdictWord"], "Pass")
        self.assertIn("Could not be verified.", c["reasons"])
        self.assertFalse(c["hasPassPrice"])
        self.assertNotIn("What would change it", c["text"])

    def test_graded_results_and_what_a_pass_would_have_done_are_shown(self):
        out = self.render("section", view([
            call("moneyline", "TAKE_OTHER_SIDE", "moneyline", result="WIN"),
            call("run_line", "TAKE", "run_line", result="LOSS"),
            call("total", "PASS", "total", result="PASS", would_have={"result": "LOSS", "price": -110}),
            call("team_total_away", "TAKE", "team_total", result="PUSH"),
            call("team_total_home", "TAKE", "team_total", result="VOID")],
            graded=True))
        self.assertEqual([c["result"] for c in out["calls"]],
                         ["Won", "Lost", "The side passed on lost.", "Push", "Void"])

    def test_an_unverifiable_summary_is_withheld_with_a_plain_notice(self):
        out = self.render("section", view([call("moneyline", "TAKE", "moneyline")],
                                          summary=None, summary_status="withheld"))
        self.assertIn("could not be verified against the data, so it is not shown", out["text"])
        self.assertNotIn("First paragraph", out["text"])
        self.assertEqual(len(out["calls"]), 1)

    def test_a_game_with_no_analysis_says_so_and_still_carries_the_label(self):
        out = self.render("section", {"available": False, "label": LABEL, "analysis": None,
                                      "reason": "No analysis has been published for this game."})
        self.assertEqual(out["firstParagraph"], LABEL)
        self.assertIn("No analysis has been published for this game.", out["text"])
        self.assertEqual(out["calls"], [])

    def test_a_missing_price_is_said_not_blanked(self):
        out = self.render("section", view([call("moneyline", "PASS", "moneyline", price=None, book=None)]))
        self.assertIn("No price named", out["calls"][0]["price"])

    # ---- the case against, what was missing, the pilot's label ------------

    def test_each_take_shows_the_case_against_under_its_reasons_and_a_pass_shows_none(self):
        against = {"claim": "The home starter has the lower ERA.", "evidence": []}
        out = self.render("section", view([
            call("moneyline", "TAKE_OTHER_SIDE", "moneyline", case_against=against),
            call("run_line", "TAKE", "run_line", case_against=against),
            call("total", "PASS", "total", case_against=None)]))
        take, other, passed = out["calls"]
        for c in (take, other):
            self.assertIn("The case against", c["text"])
            self.assertIn("The home starter has the lower ERA.", c["text"])
            self.assertLess(c["text"].index("The books make the home side"), c["text"].index("The case against"))
        self.assertNotIn("The case against", passed["text"])
        self.assertEqual(out["hooks"].count("analyst-case-against"), 2)

    def test_the_case_against_is_drawn_in_the_reasons_own_list_style(self):
        out = self.render("section", view([call("moneyline", "TAKE", "moneyline",
                                                case_against={"claim": "A weakness.", "evidence": []})]))
        c = out["calls"][0]
        self.assertEqual(c["reasons"], ["The books make the home side the favourite.",
                                        "The starters are closer than the price suggests.", "A weakness."])

    def test_a_row_without_a_case_against_and_a_struck_call_draw_none(self):
        struck = call("moneyline", "PASS", "moneyline",
                      case_against={"claim": "Should never show.", "evidence": []},
                      reasons=[{"claim": "Could not be verified.", "evidence": []}],
                      verification={"status": "could not be verified", "problems": []})
        old = call("run_line", "TAKE", "run_line")
        out = self.render("section", view([struck, old]))
        self.assertNotIn("The case against", out["text"])
        self.assertNotIn("Should never show.", out["text"])

    def test_what_the_analysis_could_not_use_is_listed_after_the_calls(self):
        missing = [{"item": "lineups", "kind": "absent", "reason": "lineup not posted yet"},
                   {"item": "bullpen", "kind": "absent", "reason": "no reliever appearances recorded"}]
        out = self.render("section", view([call("moneyline", "TAKE", "moneyline")], missing=missing))
        self.assertIn("What the analysis could not use", out["text"])
        self.assertIn("Lineup not posted yet.", out["text"])
        self.assertIn("No reliever appearances recorded.", out["text"])
        self.assertLess(out["hooks"].index("analyst-call"), out["hooks"].index("analyst-missing"))
        self.assertNotIn("analyst-missing-more", out["hooks"])

    def test_a_long_missing_list_is_capped_with_a_count(self):
        missing = [{"item": f"x{i}", "kind": "absent", "reason": f"input {i} is absent"} for i in range(9)]
        out = self.render("section", view([call("moneyline", "TAKE", "moneyline")], missing=missing))
        self.assertIn("Input 5 is absent.", out["text"])
        self.assertNotIn("Input 6 is absent.", out["text"])
        self.assertIn("And 3 more items not listed here.", out["text"])

    def test_an_empty_list_says_nothing_was_missing_and_an_unread_one_says_nothing_at_all(self):
        empty = self.render("section", view([call("moneyline", "TAKE", "moneyline")], missing=[]))
        self.assertIn("Nothing the data was expected to hold was missing.", empty["text"])
        unread = self.render("section", view([call("moneyline", "TAKE", "moneyline")], missing=None))
        self.assertNotIn("What the analysis could not use", unread["text"])
        self.assertNotIn("analyst-missing", unread["hooks"])

    def test_the_pilots_label_is_printed_as_the_server_sent_it(self):
        pilot_label = ("Written by an AI model in a supervised session, from the data frozen before the game. "
                       "Unproven. Analysis, not advice.")
        data = view([call("moneyline", "TAKE", "moneyline")])
        data["label"] = pilot_label
        out = self.render("section", data)
        self.assertEqual(out["firstParagraph"], pilot_label)
        self.assertEqual(out["labelCount"], 1)
        self.assertNotIn(LABEL, out["text"])

    # ---- the record ------------------------------------------------------

    def record(self, **fams):
        base = {name: family() for name in ("moneyline", "run_line", "total", "team_total", "prop")}
        base.update(fams)
        return {"label": LABEL, "min_graded": 30, "games_published": 12, "games_settled": 9,
                "families": base, "recent": []}

    def test_under_thirty_graded_calls_no_rate_and_no_units_are_printed(self):
        out = self.render("record", self.record(
            moneyline=family(taken=14, passes=5, graded=14, wins=9, losses=5,
                             reason="fewer than 30 graded calls (14 so far)")))
        row = next(r for r in out["rows"] if r["family"] == "moneyline")
        self.assertTrue(row["withheld"])
        self.assertFalse(row["hasRate"])
        self.assertIn("fewer than 30 graded calls (14 so far)", " ".join(row["cells"]))
        self.assertEqual(row["cells"][1:5], ["14", "5", "14", "9-5-0"])
        self.assertNotRegex(" ".join(row["cells"]), r"%|u$|[+]\d")

    def test_at_thirty_the_server_sends_a_rate_and_units_and_they_are_printed(self):
        out = self.render("record", self.record(
            moneyline=family(taken=30, graded=30, wins=18, losses=12, rate=0.6, units=2.31)))
        row = next(r for r in out["rows"] if r["family"] == "moneyline")
        self.assertTrue(row["hasRate"])
        self.assertFalse(row["withheld"])
        self.assertIn("60.0%", row["cells"])
        self.assertIn("+2.31u", row["cells"])

    def test_every_family_has_a_row_with_counts_and_the_label_leads(self):
        out = self.render("record", self.record())
        self.assertEqual([r["family"] for r in out["rows"]],
                         ["moneyline", "run_line", "total", "team_total", "prop"])
        self.assertEqual(out["firstParagraph"], LABEL)
        self.assertIn("kept apart from the card record", out["text"])
        self.assertIn("after it has 30 graded calls", out["text"])

    def test_recent_graded_calls_are_listed_with_their_results(self):
        data = self.record()
        data["recent"] = [{"date": "2026-10-02", "away": "BOS", "home": "NYM", "family": "moneyline",
                           "selection": "BOS", "player": None, "verdict": "TAKE", "price": 120,
                           "result": "WIN"},
                          {"date": "2026-10-02", "away": "BOS", "home": "NYM", "family": "prop",
                           "selection": "Over 0.5", "player": "Pete Alonso", "verdict": "TAKE",
                           "price": -130, "result": "LOSS"}]
        out = self.render("record", data)
        self.assertIn("BOS at NYM, BOS at +120 — Won", out["text"])
        self.assertIn("Pete Alonso Over 0.5 at -130 — Lost", out["text"])

    def test_the_pilot_record_is_its_own_block_under_its_own_heading(self):
        pilot_label = "Written in a supervised session. Unproven. Analysis, not advice."
        data = self.record()
        data["pilot"] = dict(self.record(moneyline=family(taken=3, passes=2, graded=1, wins=1)),
                             label=pilot_label, games_published=2, games_settled=1)
        out = self.render("record", data)
        self.assertIn("analyst-pilot-record", out["hooks"])
        self.assertIn("Supervised-session briefs", out["text"])
        self.assertIn(pilot_label, out["text"])
        self.assertIn("2 games briefed so far, 1 fully settled.", out["text"])
        self.assertIn("counted apart from the analyst record above", out["text"])
        # the main table keeps its own five rows and the pilot's five follow it, never merged
        self.assertEqual(len(out["rows"]), 10)
        self.assertEqual(out["rows"][0]["cells"][1], "0")
        self.assertEqual(out["rows"][5]["cells"][1], "3")
        self.assertLess(out["text"].index("AI ANALYST RECORD"), out["text"].index("Supervised-session briefs"))

    def test_without_a_pilot_block_the_record_is_what_it_was(self):
        absent = self.record()
        null = dict(self.record(), pilot=None)
        for data in (absent, null):
            out = self.render("record", data)
            self.assertNotIn("analyst-pilot-record", out["hooks"])
            self.assertNotIn("Supervised-session briefs", out["text"])
            self.assertEqual(len(out["rows"]), 5)

    def test_the_pilot_record_withholds_rates_under_thirty_graded_calls_too(self):
        data = self.record()
        data["pilot"] = dict(self.record(moneyline=family(taken=14, graded=14, wins=9, losses=5,
                                                          reason="fewer than 30 graded calls (14 so far)")),
                             label="x. Unproven.")
        out = self.render("record", data)
        row = out["rows"][5]
        self.assertTrue(row["withheld"])
        self.assertFalse(row["hasRate"])


if __name__ == "__main__":
    unittest.main()
