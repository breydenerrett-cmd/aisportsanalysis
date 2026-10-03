"""The UFC page's fight analysis: web/js/ufcfights.js, wired into main.js under the paused notice.

Two halves, the pattern of tests/test_matchup_read_web.py:

  * STATIC: the page is wired under the paused notice and the notice is kept, the module imports one
    fetcher and touches nothing else, everything that folds does so under a native <details> with a
    <summary> (so it works from file:// with no script), no table is rendered, the stylesheet holds at
    390px (one column by default, every text node wraps, no fixed width, nothing scrolls on its own, the
    two-column layouts switch on only from 900px), and nothing the module writes itself reads as a dash,
    a pick, a lock, a profit claim or a developer note;
  * BEHAVIOURAL: the real ufcfights.js run under node against a small fake DOM, fed what the route serves
    (built here from the frozen golden sheets and reads, so no FastAPI is needed, and a second class that
    renders the real route's own output when FastAPI is installed). It checks what a person would see: a panel
    per bout in card order, both fighters with records and prices, the headline verbatim, strengths and
    weaknesses side by side with their sample chips and caveats outside any toggle, the routes, the history, the
    market sentences, the limits, the fact sheet, and an empty slot for the analyst section.

The node tests skip when node is not installed (the GitHub runner has it).
"""

from __future__ import annotations

import copy
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from src.analysis import ufc_read

try:
    import fastapi  # noqa: F401
    HAS_FASTAPI = True
except ImportError:  # pragma: no cover
    HAS_FASTAPI = False

ROOT = Path(__file__).resolve().parent.parent
JS = ROOT / "web" / "js"
CSS = ROOT / "web" / "css" / "ufcfights.css"
UF_JS = (JS / "ufcfights.js").read_text(encoding="utf-8")
MAIN_JS = (JS / "main.js").read_text(encoding="utf-8")
CARD_JS = (JS / "card.js").read_text(encoding="utf-8")
INDEX = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
GOLDEN = ROOT / "tests" / "fixtures" / "ufc_read_golden.json"
NODE = shutil.which("node")


# ---------------------------------------------------------------------------
# Static
# ---------------------------------------------------------------------------

class TheCardIsWiredUnderThePausedNotice(unittest.TestCase):
    def test_main_js_imports_one_renderer_and_calls_it_after_the_card_on_the_ufc_page(self):
        self.assertIn('import { renderFightNight } from "./ufcfights.js";', MAIN_JS)
        branch = MAIN_JS.split('} else if (sport === "ufc") {')[1].split('} else if (sport === "nba"')[0]
        self.assertIn('await renderCardRecord(main, { sport: "mma" });', branch)
        gameday = branch.split("} else {", 1)[1]
        card_at = gameday.index('await renderCard(main, { sport: "mma" });')
        night_at = gameday.index("await renderFightNight(main, { eventId: query.event });")
        self.assertLess(card_at, night_at, "the fight analysis sits UNDER the card (today the paused notice)")
        self.assertNotIn("renderFightNight", branch.split("} else {", 1)[0], "the record page is not the analysis page")

    def test_the_paused_notice_is_kept_exactly_and_the_card_module_does_not_know_about_the_analysis(self):
        self.assertIn("function pausedCard(payload)", CARD_JS)
        self.assertIn('text: "PICKS PAUSED"', CARD_JS)
        self.assertIn("wrap.appendChild(pausedCard(payload));", CARD_JS)
        self.assertNotIn("ufcfights", CARD_JS)
        self.assertNotIn("fight-night", CARD_JS)

    def test_the_stylesheet_is_linked_before_the_last_one(self):
        link = '<link rel="stylesheet" href="css/ufcfights.css">'
        self.assertIn(link, INDEX)
        self.assertLess(INDEX.index(link), INDEX.index('href="css/gotcha.css"'))
        self.assertGreater(INDEX.index(link), INDEX.index('href="css/screens.css"'), ".panel and .chamfer must exist first")

    def test_the_nav_no_longer_says_picks_for_the_page_that_shows_fights(self):
        sport_js = (JS / "sport.js").read_text(encoding="utf-8")
        self.assertIn('{ hash: "#/ufc", label: "GAMEDAY", sub: "This card, fight by fight" }', sport_js)
        self.assertNotIn("This card's picks", sport_js)


class TheModuleTouchesLittle(unittest.TestCase):
    def test_it_imports_one_fetcher_and_the_dom_helpers_and_nothing_else(self):
        imports = re.findall(r'^import .*? from "(\./[^"]+)";', UF_JS, re.M | re.S)
        self.assertEqual(sorted(imports), ["./api.js", "./dom.js"])

    def test_no_script_tag_no_inner_html_no_eval_no_direct_fetch_no_timer(self):
        code = re.sub(r"/\*.*?\*/", " ", UF_JS, flags=re.S)
        for token in ("<script", "innerHTML", "eval(", "fetch(", "setTimeout", "setInterval", "document.write",
                      "localStorage", "location.", "window."):
            self.assertNotIn(token, code, token)

    def test_the_one_request_it_makes_is_the_fight_night_route(self):
        code = re.sub(r"/\*.*?\*/", " ", UF_JS, flags=re.S)
        self.assertEqual(sorted(set(re.findall(r"/ufc/fight-night[^`\"']*", code))),
                         ["/ufc/fight-night/${encodeURIComponent(options.eventId)}?sheet=compact",
                          "/ufc/fight-night?sheet=compact"])
        self.assertEqual(UF_JS.count("apiGet("), 1)

    def test_everything_that_folds_is_a_native_details_with_a_summary(self):
        self.assertGreaterEqual(UF_JS.count('el("details"'), 6)
        self.assertGreaterEqual(UF_JS.count('el("summary"'), 6)

    def test_no_table_is_rendered(self):
        for token in ('"table"', '"tr"', '"td"', '"th"'):
            self.assertNotIn(token, UF_JS, token)

    def test_the_analyst_slots_are_named_and_documented_in_the_module(self):
        self.assertIn('export const ANALYST_SLOT_HOOK = "ufc-analyst-slot";', UF_JS)
        self.assertIn('export const ANALYST_EVENT_SLOT_HOOK = "ufc-analyst-event-slot";', UF_JS)
        self.assertIn("WHERE THE AI ANALYST GOES", UF_JS)


class TheStylesheetHoldsAt390Pixels(unittest.TestCase):
    def setUp(self):
        self.css = CSS.read_text(encoding="utf-8")
        self.code = re.sub(r"/\*.*?\*/", " ", self.css, flags=re.S)
        self.base, self.wide = self.code.split("@media (min-width: 900px)")

    def test_every_text_node_wraps(self):
        self.assertIn(".uf, .uf * { overflow-wrap: anywhere;", self.code)

    def test_nothing_forbids_wrapping_nothing_scrolls_and_no_width_above_300px_is_fixed(self):
        self.assertNotIn("nowrap", self.code)
        self.assertNotIn("overflow-x", self.code)
        self.assertNotIn("overflow: auto", self.code)
        self.assertNotIn("overflow: scroll", self.code)
        declarations = re.sub(r"@media[^{]*\{", "{", self.code)          # a media query's own width is not a fixed width
        for match in re.finditer(r"(?<![-\w])(?:min-|max-)?width:\s*(\d+)px", declarations):
            self.assertLess(int(match.group(1)), 300, match.group(0))

    def test_the_default_layout_is_one_column_and_the_two_column_layouts_start_at_900px(self):
        self.assertNotIn("grid-template-columns: minmax(0, 1fr) minmax(0, 1fr)", self.base)
        self.assertIn(".uf-cols { display: flex; flex-direction: column;", self.base)
        self.assertIn(".uf-fighters { display: flex; flex-direction: column;", self.base)
        self.assertIn("grid-template-columns: minmax(0, 1fr) minmax(0, 1fr)", self.wide)
        self.assertIn(".uf-fighters { flex-direction: row;", self.wide)

    def test_the_fact_sheet_is_three_flexible_columns_not_a_table(self):
        row = re.search(r"\.uf-fact \{[^}]*\}", self.code).group(0)
        self.assertIn("grid-template-columns: minmax(0, 1.4fr) minmax(0, 1fr) minmax(0, 1fr)", row)
        self.assertNotIn("table", self.code)

    def test_an_empty_analyst_slot_takes_no_room(self):
        self.assertIn(".uf-analyst-slot:empty { display: none; }", self.code)

    def test_it_invents_no_colour_and_never_uses_the_money_tone(self):
        self.assertIsNone(re.search(r"#[0-9a-fA-F]{3,8}\b", self.code), "a hard-coded colour")
        self.assertNotIn("--v-money", self.code)
        self.assertNotIn("--money", self.code)


class WhatTheModuleWritesItselfSpeaksToAReader(unittest.TestCase):
    def strings(self):
        from tests.test_no_developer_notes_on_screen import _rendered_strings
        return list(_rendered_strings(JS / "ufcfights.js"))

    def test_the_scanner_saw_the_module(self):
        self.assertGreater(len(self.strings()), 12)

    def test_no_developer_word_and_no_retired_phrase(self):
        from tests.test_no_developer_notes_on_screen import DEVELOPER_WORDS
        from tests.test_web_register_sweep import RETIRED
        offenders = []
        for line_no, text in self.strings():
            lowered = text.lower()
            for word, _why in DEVELOPER_WORDS:
                if re.search(rf"\b{re.escape(word)}\b", lowered):
                    offenders.append((line_no, word))
            for phrase in RETIRED:
                if phrase in lowered:
                    offenders.append((line_no, phrase))
        self.assertEqual(offenders, [])

    def test_no_dash_no_pick_no_lock_no_profit_no_probability_of_our_own(self):
        code = re.sub(r"/\*.*?\*/", " ", UF_JS, flags=re.S)
        code = "\n".join(line for line in code.splitlines() if not line.strip().startswith("//"))
        literals = re.findall(r'"([^"\n]*)"|`([^`\n]*)`', code)
        text = " ".join(a or b for a, b in literals).lower()
        for banned in ("—", "–", "guarantee", "profit", "win probability", "free money", "sure thing"):
            self.assertNotIn(banned, text, banned)
        for pattern in (r"\bpicks?\b", r"\block\b", r"\bedge\b", r"\broi\b", r"\bbet\b", r"\bpredict"):
            self.assertIsNone(re.search(pattern, text), pattern)

    def test_no_snake_case_name_is_a_rendered_literal(self):
        for line_no, text in self.strings():
            self.assertEqual(re.findall(r"\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b", text), [], (line_no, text))


# ---------------------------------------------------------------------------
# What the route serves, assembled from the frozen golden cases (no FastAPI needed)
# ---------------------------------------------------------------------------

def cases():
    return json.loads(GOLDEN.read_text(encoding="utf-8"))["cases"]


def compact_odds(sheet):
    odds = sheet.get("odds")
    if not isinstance(odds, dict) or not odds.get("moneyline"):
        return None
    ml = odds["moneyline"]
    return {"provider": odds.get("provider"), "provider_id": odds.get("provider_id"), "fetched_utc": odds.get("fetched_utc"),
            "is_closing": odds.get("is_closing"), "as_of_safe": False, "orientation": odds.get("orientation"),
            "moneyline": {"open": ml.get("open"), "current": ml.get("current")},
            "rounds_total": {"line": (odds.get("rounds_total") or {}).get("line"),
                             "current": (odds.get("rounds_total") or {}).get("current")}, "method": None}


def bout_from_case(case, bout_id, number, segment, *, status="scheduled", title=None, compact=True):
    sheet, read = case["sheet"], case["read"]
    a, b = sheet["a"], sheet["b"]

    def fighter(side):
        career = sheet["features"][side].get("career_record_incl_non_ufc") or {}
        record = ({"wins": career.get("wins"), "losses": career.get("losses"), "draws": career.get("draws")}
                  if career.get("wins") is not None else None)
        return {"fighter_id": sheet[side]["fighter_id"], "name": sheet[side]["name"], "nickname": None,
                "record": record, "stance": sheet["physical"][side].get("stance"), "weight_class": None}

    return {"bout_id": bout_id, "match_number": number, "card_segment": segment,
            "date_utc": (sheet.get("bout") or {}).get("date_utc") or "2026-10-03T20:00Z",
            "weight_class": (sheet.get("bout") or {}).get("weight_class") or "Bantamweight",
            "scheduled_rounds": (sheet.get("bout") or {}).get("scheduled_rounds") or 3, "status": status,
            "title_bout": title, "fighter_a": fighter("a"), "fighter_b": fighter("b"), "result": None,
            "odds": compact_odds(sheet), "sheet": ufc_read.compact_sheet(sheet) if compact else sheet,
            "read": copy.deepcopy(read), "unavailable": None}


def unavailable_bout(bout_id="9999", number=9, segment="prelims"):
    return {"bout_id": bout_id, "match_number": number, "card_segment": segment, "date_utc": "2026-10-03T22:00Z",
            "weight_class": "Flyweight", "scheduled_rounds": 3, "status": "scheduled", "title_bout": None,
            "fighter_a": {"fighter_id": "1", "name": "Una Known", "nickname": "The Gap", "record": {"wins": 3, "losses": 1, "draws": 0},
                          "stance": None, "weight_class": None},
            "fighter_b": {"fighter_id": "2", "name": None, "nickname": None, "record": None, "stance": None, "weight_class": None},
            "result": None, "odds": None, "sheet": None, "read": None,
            "unavailable": "A fighter is not named for this bout yet."}


def card_payload():
    c = cases()
    return {
        "event": {"event_id": "600061182", "name": "UFC 332: Silva vs. Wang", "short_name": "UFC 332", "date_utc": "2026-10-03T20:00Z",
                  "status": "scheduled", "bout_count": 4, "development_show": False},
        "bouts": [bout_from_case(c["synthetic_main_event"], "1001", 1, "main", title=True),
                  bout_from_case(c["vettori_v_naurdiev_upcoming"], "1002", 2, "main"),
                  bout_from_case(c["rosas_v_barcelos_afterwards"], "1003", 6, "prelims"),
                  unavailable_bout("1004", 9, "prelims")],
        "missing_bout_ids": [], "reason": None, "data_updated_utc": "2026-10-03T19:14:09Z",
        "other_events": [{"event_id": "600060740", "name": "Dana White's Contender Series: Season 10, Week 9", "short_name": "DWCS",
                          "date_utc": "2026-10-06T23:00Z", "status": "scheduled", "bout_count": 1, "development_show": True},
                         {"event_id": "600061541", "name": "UFC Fight Night: Allen vs. Duncan", "short_name": "UFN",
                          "date_utc": "2026-10-10T21:00Z", "status": "scheduled", "bout_count": 12, "development_show": False}],
        "label": ufc_read.LABEL, "generated_utc": "2026-10-03T19:30:00Z",
    }


# ---------------------------------------------------------------------------
# The node harness: copy web/js, stub api.js, fake DOM, dump the tree
# ---------------------------------------------------------------------------

API_STUB = r"""
export class ApiError extends Error {
  constructor(status, detail) {
    super(typeof detail === "string" ? detail : JSON.stringify(detail));
    this.status = status;
    this.detail = detail;
  }
}
export const TOKEN_STORAGE_KEY = "test.invite_token";
export const TOKEN_CHANGED_EVENT = "test:token-changed";
export const FREE_CHECK_TOKEN_STORAGE_KEY = "test.free_check_token";
export const DEFAULT_TIMEOUT_MS = 20000;
export function getToken() { return "tester-token"; }
export function setToken() {}
export function clearToken() {}
export function getFreeCheckToken() { return null; }
export function setFreeCheckToken() {}
export function setPublicDemo() {}
export function isPublicDemo() { return false; }
export function apiFetch(path, options) { return globalThis.__apiGet(path, options); }
export function apiGet(path, options) { return globalThis.__apiGet(path, options); }
export function apiPost() { throw new Error("no POST in these tests"); }
export function apiDelete() { throw new Error("no DELETE in these tests"); }
export function trackFunnelEvent() {}
"""

RUNNER = r"""
import fs from "node:fs";
import { ApiError } from "./js/api.js";

Date.now = () => Date.parse("2026-10-03T16:00:00Z");

class FakeNode {
  constructor(tag, text) {
    this.nodeType = tag ? 1 : 3;
    this.tagName = tag ? String(tag).toUpperCase() : "#text";
    this._text = text == null ? "" : String(text);
    this.attributes = {};
    this.childNodes = [];
    this.parentNode = null;
    this.style = {};
  }
  get firstChild() { return this.childNodes[0] || null; }
  appendChild(child) {
    if (!(child instanceof FakeNode)) throw new TypeError("parameter 1 is not of type 'Node'.");
    if (child.parentNode) child.parentNode.removeChild(child);
    child.parentNode = this;
    this.childNodes.push(child);
    return child;
  }
  removeChild(child) {
    const i = this.childNodes.indexOf(child);
    if (i >= 0) this.childNodes.splice(i, 1);
    child.parentNode = null;
    return child;
  }
  setAttribute(k, v) { this.attributes[k] = String(v); }
  getAttribute(k) { return k in this.attributes ? this.attributes[k] : null; }
  addEventListener() {}
  get textContent() {
    if (this.nodeType === 3) return this._text;
    return this.childNodes.map((c) => c.textContent).join("");
  }
  set textContent(value) {
    if (this.nodeType === 3) { this._text = String(value); return; }
    this.childNodes = [];
    if (value !== "" && value != null) this.appendChild(new FakeNode(null, value));
  }
}

globalThis.document = {
  createElement: (tag) => new FakeNode(tag),
  createTextNode: (text) => new FakeNode(null, text),
  querySelector: () => null,
  querySelectorAll: () => [],
  addEventListener() {},
};
const store = new Map();
globalThis.window = {
  location: { hash: "", search: "", host: "linehound.test", pathname: "/" },
  localStorage: { getItem: (k) => (store.has(k) ? store.get(k) : null), setItem: (k, v) => store.set(k, String(v)),
                  removeItem: (k) => store.delete(k) },
  scrollTo() {}, matchMedia: () => ({ matches: false }), addEventListener() {}, dispatchEvent() { return true; },
};

const scenario = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const calls = [];
globalThis.__apiGet = async (path) => {
  calls.push(path);
  for (const [prefix, resp] of scenario.responses || []) {
    if (path.startsWith(prefix)) {
      if (resp.error) throw new ApiError(resp.error.status, resp.error.detail);
      return JSON.parse(JSON.stringify(resp.body));
    }
  }
  throw new ApiError(404, `no stub for ${path}`);
};

const mod = await import(new URL("./js/ufcfights.js", import.meta.url));
const analystCalls = [];
let analyst = undefined;
if (scenario.analyst === "writes") {
  analyst = (slot, ctx) => { analystCalls.push(ctx.bout_id || (ctx.event && "event:" + ctx.event.event_id) || "?");
                             const p = new FakeNode("p"); p.textContent = "analyst section"; slot.appendChild(p); };
} else if (scenario.analyst === "throws") {
  analyst = () => { throw new Error("analyst down"); };
} else if (scenario.analyst === "rejects") {
  analyst = () => Promise.reject(new Error("analyst down"));
}

const host = new FakeNode("main");
let result = null, rejected = null;
try {
  if (scenario.mode === "mount") {
    result = await mod.renderFightNight(host, Object.assign({}, scenario.options || {}, analyst ? { analyst } : {}));
  } else {
    const node = mod.fightNightNode(scenario.payload, analyst ? { analyst } : {});
    if (node) host.appendChild(node);
    result = { rendered: !!node };
  }
} catch (err) {
  rejected = `${err && err.name}: ${err && err.message}`;
}

function dump(n) {
  if (n.nodeType === 3) return { x: n._text };
  return { t: n.tagName, a: n.attributes, c: n.childNodes.map(dump) };
}
process.stdout.write("@@" + JSON.stringify({
  rejected, result, calls, analystCalls,
  consts: { items: mod.ITEMS_SHOWN, routes: mod.ROUTES_SHOWN, shared: mod.SHARED_SHOWN, slot: mod.ANALYST_SLOT_HOOK,
            eventSlot: mod.ANALYST_EVENT_SLOT_HOOK, facts: mod.FACT_ROWS.length },
  tree: dump(host),
}));
"""


class N:
    """A node of the dumped tree, with the small queries these tests need."""

    def __init__(self, d):
        self.d = d

    @property
    def tag(self):
        return self.d.get("t")

    @property
    def attrs(self):
        return self.d.get("a") or {}

    @property
    def kids(self):
        return [N(c) for c in self.d.get("c", [])]

    @property
    def hook(self):
        return self.attrs.get("data-hook")

    @property
    def classes(self):
        return (self.attrs.get("class") or "").split()

    def text(self):
        if "x" in self.d:
            return self.d["x"]
        return "".join(k.text() for k in self.kids)

    def walk(self):
        yield self
        for k in self.kids:
            yield from k.walk()

    def hooks(self, name):
        return [n for n in self.walk() if n.hook == name]

    def one(self, name):
        found = self.hooks(name)
        assert len(found) == 1, f"{name}: {len(found)} found"
        return found[0]

    def with_class(self, cls):
        return [n for n in self.walk() if cls in n.classes]

    def tags(self, tag):
        return [n for n in self.walk() if n.tag == tag.upper()]

    def outside_details(self, name):
        """Nodes with data-hook `name` that are not inside any <details> under this node."""
        out = []

        def rec(node, inside):
            if node.hook == name and not inside:
                out.append(node)
            for k in node.kids:
                rec(k, inside or node.tag == "DETAILS")

        rec(self, False)
        return out


@unittest.skipUnless(NODE, "node is not installed")
class _Harness(unittest.TestCase):
    _tmp = None

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        root = Path(cls._tmp.name)
        (root / "js").mkdir()
        for path in JS.glob("*.js"):
            shutil.copy(path, root / "js" / path.name)
        (root / "js" / "api.js").write_text(API_STUB, encoding="utf-8")
        (root / "package.json").write_text('{"type": "module"}', encoding="utf-8")
        (root / "run.mjs").write_text(RUNNER, encoding="utf-8")
        cls._root = root

    @classmethod
    def tearDownClass(cls):
        if cls._tmp is not None:
            cls._tmp.cleanup()

    @classmethod
    def run_scenario(cls, scenario):
        path = cls._root / "scenario.json"
        path.write_text(json.dumps(scenario), encoding="utf-8")
        env = dict(os.environ, TZ="America/Los_Angeles")
        proc = subprocess.run([NODE, str(cls._root / "run.mjs"), str(path)], capture_output=True, text=True,
                              timeout=90, encoding="utf-8", env=env)
        if proc.returncode != 0:
            raise AssertionError(f"node harness failed:\n{proc.stderr[-3000:]}")
        line = [ln for ln in proc.stdout.splitlines() if ln.startswith("@@")][-1]
        out = json.loads(line[2:])
        if out["rejected"] is not None:
            raise AssertionError(out["rejected"])
        out["root"] = N(out["tree"])
        return out

    @classmethod
    def render(cls, payload, analyst=None):
        out = cls.run_scenario({"mode": "node", "payload": payload, "analyst": analyst})
        out["section"] = out["root"].kids[0] if out["root"].kids else None
        return out

    @classmethod
    def mount(cls, responses, options=None, analyst=None):
        return cls.run_scenario({"mode": "mount", "responses": responses, "options": options or {}, "analyst": analyst})


# ---------------------------------------------------------------------------
# Behavioural
# ---------------------------------------------------------------------------

class TheCardRenders(_Harness):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.payload = card_payload()
        cls.out = cls.render(cls.payload)

    def setUp(self):
        self.root = self.out["root"]
        self.section = self.out["section"]
        self.panels = self.root.hooks("ufc-bout")

    # -- the frame -----------------------------------------------------------

    def test_it_is_one_section_with_the_heading_the_event_and_the_servers_label(self):
        self.assertEqual(self.section.tag, "SECTION")
        self.assertEqual(self.section.hook, "ufc-fight-night")
        self.assertIn("FIGHT NIGHT", self.section.text())
        head = self.section.with_class("sechead__meta")[0].text()
        self.assertEqual(head, "UFC 332: Silva vs. Wang · SAT OCT 3 · 4 bouts")
        self.assertEqual(self.section.one("ufc-label").text(), ufc_read.LABEL)

    def test_one_panel_per_bout_in_card_order_with_a_heading_when_the_segment_changes(self):
        self.assertEqual([p.attrs["data-bout-id"] for p in self.panels], ["1001", "1002", "1003", "1004"])
        self.assertEqual([h.text() for h in self.root.hooks("ufc-segment")], ["MAIN CARD", "PRELIMS"])
        order = [n.hook for n in self.root.one("ufc-bouts").kids]
        self.assertEqual(order, ["ufc-segment", "ufc-bout", "ufc-bout", "ufc-segment", "ufc-bout", "ufc-bout"])

    def test_the_main_event_and_the_title_fight_are_marked(self):
        chips = [c.text() for c in self.panels[0].with_class("uf-chip")][:6]
        self.assertIn("MAIN EVENT", chips)
        self.assertIn("TITLE FIGHT", chips)
        self.assertIn("5 ROUNDS", chips)
        self.assertNotIn("MAIN EVENT", [c.text() for c in self.panels[1].with_class("uf-chip")])
        self.assertIn("WELTERWEIGHT", chips)

    def test_other_cards_are_links_that_open_that_event(self):
        links = self.root.hooks("ufc-other-event")
        self.assertEqual([l.attrs["href"] for l in links], ["#/ufc?event=600060740", "#/ufc?event=600061541"])
        self.assertIn("Contender Series", links[0].text())

    # -- one panel -------------------------------------------------------------

    def test_both_fighters_with_their_records_and_the_price_and_the_markets_own_share(self):
        fighters = self.panels[0].hooks("ufc-fighter")
        self.assertEqual([f.kids[0].text() for f in fighters], ["Alex Archer", "Ben Brawler"])
        self.assertIn("12-4-0 overall", fighters[0].text())
        self.assertIn("9-3-1 overall", fighters[1].text())
        prices = [p.text() for p in self.panels[0].hooks("ufc-price")]
        self.assertEqual(prices, ["-170 · 60.7%", "+145 · 39.3%"])
        caption = self.panels[0].one("ufc-price-caption").text()
        self.assertIn("DraftKings", caption)
        self.assertIn("margin taken out", caption)

    def test_a_bout_without_a_price_says_so_and_prints_no_percentage(self):
        panel = self.panels[2]
        self.assertEqual([p.text() for p in panel.hooks("ufc-price")], ["No price on file", "No price on file"])
        self.assertFalse(panel.hooks("ufc-price-caption"))

    def test_the_headline_and_every_server_sentence_print_verbatim(self):
        for panel, bout in zip(self.panels[:3], self.payload["bouts"][:3]):
            read = bout["read"]
            self.assertEqual(panel.one("ufc-headline").text(), read["headline"])
            for note in read["notices"]:
                self.assertIn(note, [n.text() for n in panel.hooks("ufc-notice")])
            self.assertEqual(panel.one("ufc-depth").kids[1].text(), read["data_depth"]["sentence"])
            for sentence in read["market_view"]["sentences"]:
                self.assertIn(sentence, panel.one("ufc-market").text())
            self.assertIn(read["history"]["summary"], panel.one("ufc-history").text())

    def test_a_thin_bout_wears_the_warning_chip_and_a_solid_one_does_not(self):
        thin = self.panels[1].one("ufc-depth")
        self.assertEqual(thin.kids[0].text(), "THIN DATA")
        self.assertIn("uf-chip--warn", thin.kids[0].classes)
        main = self.panels[0].one("ufc-depth")
        self.assertNotIn("uf-chip--warn", main.kids[0].classes)

    def test_strengths_and_weaknesses_sit_side_by_side_one_column_per_fighter(self):
        cols = self.panels[0].one("ufc-traits")
        self.assertEqual([c.attrs["data-side"] for c in cols.hooks("ufc-column")], ["a", "b"])
        names = [c.with_class("uf-col__name")[0].text() for c in cols.hooks("ufc-column")]
        self.assertEqual(names, ["Alex Archer", "Ben Brawler"])
        for col in cols.hooks("ufc-column"):
            subheads = [h.text() for h in col.with_class("uf-subhead")]
            self.assertEqual(subheads, ["STRENGTHS", "WEAKNESSES"])

    def test_each_list_prints_three_open_and_folds_the_rest_into_one_toggle(self):
        read = self.payload["bouts"][0]["read"]
        for col in self.panels[0].hooks("ufc-column"):
            side = col.attrs["data-side"]
            for kind, key in (("strength", "strengths"), ("weakness", "weaknesses")):
                total = len(read[side][key])
                shown = len(col.outside_details(f"ufc-{kind}"))
                folded = len(col.hooks(f"ufc-more-{kind}"))
                self.assertEqual(shown, min(total, self.out["consts"]["items"]), (side, kind))
                if total > self.out["consts"]["items"]:
                    self.assertEqual(folded, 1)
                    self.assertEqual(col.one(f"ufc-more-{kind}").kids[0].text(), f"MORE ({total - self.out['consts']['items']})")
                else:
                    self.assertEqual(folded, 0)

    def test_each_item_prints_its_sentence_size_sample_and_caveat_outside_any_toggle(self):
        read = self.payload["bouts"][0]["read"]
        col = self.panels[0].hooks("ufc-column")[0]
        items = col.outside_details("ufc-strength") + col.outside_details("ufc-weakness")
        self.assertTrue(items)
        by_sentence = {i["sentence"]: i for k in ("strengths", "weaknesses") for i in read["a"][k]}
        for node in items:
            sentence = node.with_class("uf-item__sentence")[0].text()
            item = by_sentence[sentence]
            chips = [c.text() for c in node.with_class("uf-chip")]
            self.assertEqual(chips[0], item["size"].upper())
            self.assertEqual(chips[1], {"thin": "THIN SAMPLE", "fair": "FAIR SAMPLE", "solid": "SOLID SAMPLE"}[item["sample_level"]])
            if item["sample"]:
                self.assertEqual(chips[2], ur_chip(item["sample"]))
            caveats = [c.text() for c in node.with_class("uf-item__caveat")]
            self.assertEqual(caveats, [item["caveat"]] if item["caveat"] else [])

    def test_evidence_sits_under_a_native_toggle_with_one_row_per_entry(self):
        read = self.payload["bouts"][0]["read"]
        col = self.panels[0].hooks("ufc-column")[0]
        first = col.outside_details("ufc-strength")[0]
        sentence = first.with_class("uf-item__sentence")[0].text()
        item = [i for i in read["a"]["strengths"] if i["sentence"] == sentence][0]
        toggle = first.one("ufc-evidence")
        self.assertEqual(toggle.tag, "DETAILS")
        self.assertEqual(toggle.kids[0].tag, "SUMMARY")
        self.assertEqual(toggle.kids[0].text(), f"EVIDENCE ({len(item['evidence'])})")
        self.assertEqual(len(toggle.with_class("uf-evidence__row")), len(item["evidence"]))

    def test_routes_print_per_fighter_capped_with_the_rest_folded(self):
        read = self.payload["bouts"][0]["read"]
        block = self.panels[0].one("ufc-routes")
        cols = block.with_class("uf-col")
        self.assertEqual([c.with_class("uf-col__name")[0].text() for c in cols], ["Alex Archer", "Ben Brawler"])
        for col, side in zip(cols, ("a", "b")):
            routes = read[side]["paths_to_victory"]
            shown = col.outside_details("ufc-route")
            self.assertEqual(len(shown), min(len(routes), self.out["consts"]["routes"]))
            self.assertEqual([r.with_class("uf-item__sentence")[0].text() for r in shown],
                             [r["sentence"] for r in routes[:self.out["consts"]["routes"]]])
        none = self.panels[2].one("ufc-routes")
        self.assertEqual([r.attrs["data-route"] for r in none.hooks("ufc-route")], ["none", "none"])
        self.assertFalse([c for c in none.hooks("ufc-route")[0].with_class("uf-chip")], "a no-route line wears no size chip")

    def test_history_prints_the_meetings_and_folds_shared_opponents_after_two(self):
        read = self.payload["bouts"][0]["read"]
        hist = self.panels[0].one("ufc-history")
        self.assertEqual([m.text() for m in hist.hooks("ufc-meeting")], [m["sentence"] for m in read["history"]["previous_meetings"]])
        shared = [n.text() for n in hist.hooks("ufc-shared-opponent")]
        self.assertEqual(shared, [s["sentence"] for s in read["history"]["shared_opponents"]])
        self.assertIn(read["history"]["caveat"], hist.text())
        if len(shared) > self.out["consts"]["shared"]:
            self.assertEqual(len(hist.hooks("ufc-more-shared")), 1)

    def test_the_shared_context_lines_print_with_their_caveats(self):
        read = self.payload["bouts"][0]["read"]
        lines = [n.text() for n in self.panels[0].hooks("ufc-context")]
        self.assertEqual(lines, [c["sentence"] for c in read["context"]])
        self.assertTrue([l for l in lines if l.startswith("Alex Archer fights orthodox")])
        self.assertTrue([l for l in lines if "gone to the scorecards" in l])

    def test_what_would_change_it_and_what_we_could_not_use_sit_under_one_toggle(self):
        read = self.payload["bouts"][0]["read"]
        limits = self.panels[0].one("ufc-limits")
        self.assertEqual(limits.tag, "DETAILS")
        self.assertEqual(limits.kids[0].tag, "SUMMARY")
        self.assertEqual(limits.kids[0].text(),
                         f"WHAT WOULD CHANGE THIS, AND WHAT WE COULD NOT USE ({len(read['missing'])})")
        for item in read["what_would_change_it"]:
            self.assertIn(item["fact"], limits.one("ufc-change").text())
        missing = self.panels[1].one("ufc-limits").one("ufc-missing")
        for item in self.payload["bouts"][1]["read"]["missing"]:
            self.assertIn(item["detail"], missing.text())

    def test_the_fact_sheet_is_a_native_toggle_of_rows_for_both_fighters(self):
        sheet = self.panels[0].one("ufc-fact-sheet")
        self.assertEqual(sheet.tag, "DETAILS")
        self.assertEqual(sheet.kids[0].tag, "SUMMARY")
        self.assertEqual(sheet.kids[0].text(), "FACT SHEET, SIDE BY SIDE")
        rows = [[k.text() for k in r.kids[:3]] for r in sheet.hooks("ufc-fact")]
        labels = [r[0] for r in rows]
        for label in ("Fight minutes on file", "Record on file (wins-losses-draws)", "Significant strikes landed per minute",
                      "Takedowns stopped", "Age on fight night (years)", "Reach (inches)", "Stance", "Style labels"):
            self.assertIn(label, labels)
        stance = [r for r in rows if r[0] == "Stance"][0]
        self.assertEqual(stance[1:], ["Orthodox", "Southpaw"])
        last_three = [r for r in rows if r[0] == "Last three fights, newest first"][0]
        self.assertEqual(last_three[1], "W unanimous decision R3, L unanimous decision R5, W unanimous decision R3")
        self.assertEqual(last_three[2], "L submission R3, W unanimous decision R5, W submission R1")
        thin = [n for n in sheet.hooks("ufc-fact") if n.attrs.get("data-thin")]
        self.assertTrue(thin or self.payload["bouts"][0]["sheet"]["differentials"])
        self.assertIn("A THIN tag means fewer than 3 fights or 30 fight minutes", sheet.text())

    def test_the_fact_sheet_flags_a_thin_figure_and_prints_nothing_invented_for_a_missing_one(self):
        sheet = self.panels[1].one("ufc-fact-sheet")      # Vettori v Naurdiev: no fights on file
        text = sheet.text()
        self.assertIn("not on file", text)
        self.assertNotIn("0.0", text.split("Significant strikes landed per minute")[1][:40])
        for bad in ("undefined", "NaN", "null", "[object"):
            self.assertNotIn(bad, text)

    def test_a_bout_with_no_read_lists_the_reason_and_its_fighters_and_nothing_else_made_up(self):
        panel = self.panels[3]
        self.assertEqual(panel.one("ufc-unavailable").text(), "A fighter is not named for this bout yet.")
        self.assertFalse(panel.hooks("ufc-headline"))
        self.assertFalse(panel.hooks("ufc-column"))
        self.assertFalse(panel.hooks("ufc-fact-sheet"))
        fighters = panel.hooks("ufc-fighter")
        self.assertEqual(fighters[0].kids[0].text(), "Una Known")
        self.assertIn('"The Gap"', fighters[0].text())
        self.assertEqual(fighters[1].kids[0].text(), "Name not on file")
        self.assertEqual(len(panel.hooks("ufc-analyst-slot")), 1)

    # -- slots -------------------------------------------------------------------

    def test_every_bout_has_one_empty_analyst_slot_and_the_card_has_one(self):
        for panel in self.panels:
            slots = panel.hooks(self.out["consts"]["slot"])
            self.assertEqual(len(slots), 1)
            self.assertEqual(slots[0].kids, [])
            self.assertEqual(slots[0].attrs["data-bout-id"], panel.attrs["data-bout-id"])
        self.assertEqual(len(self.root.hooks(self.out["consts"]["eventSlot"])), 1)
        self.assertEqual(self.out["consts"]["slot"], "ufc-analyst-slot")

    def test_the_slot_sits_after_the_read_and_before_the_toggles(self):
        order = [n.hook for n in self.panels[0].kids if n.hook]
        self.assertLess(order.index("ufc-market"), order.index("ufc-analyst-slot"))
        self.assertLess(order.index("ufc-analyst-slot"), order.index("ufc-limits"))
        self.assertLess(order.index("ufc-limits"), order.index("ufc-fact-sheet"))

    def test_an_analyst_callback_is_called_once_per_slot_and_may_fill_it(self):
        out = self.render(self.payload, analyst="writes")
        self.assertEqual(out["analystCalls"], ["event:600061182", "1001", "1002", "1003", "1004"])
        slots = out["root"].hooks("ufc-analyst-slot")
        self.assertEqual(len(slots), 4)
        self.assertTrue(all(s.text() == "analyst section" for s in slots))
        self.assertEqual(out["root"].one("ufc-analyst-event-slot").text(), "analyst section")

    def test_an_analyst_that_throws_or_rejects_leaves_the_slot_empty_and_the_page_whole(self):
        for mode in ("throws", "rejects"):
            out = self.render(self.payload, analyst=mode)
            self.assertEqual(len(out["root"].hooks("ufc-bout")), 4, mode)
            self.assertTrue(all(s.kids == [] for s in out["root"].hooks("ufc-analyst-slot")), mode)

    # -- hygiene ---------------------------------------------------------------------

    def test_nothing_renders_as_a_table_or_a_script(self):
        self.assertEqual([n.tag for n in self.root.walk() if n.tag in ("TABLE", "TR", "TD", "TH", "SCRIPT", "STYLE")], [])

    def test_every_details_has_a_summary_first(self):
        details = self.root.tags("details")
        self.assertGreater(len(details), 20)
        for d in details:
            self.assertEqual(d.kids[0].tag, "SUMMARY")

    def test_no_programming_value_or_field_name_reaches_the_screen(self):
        text = self.section.text()
        for bad in ("undefined", "NaN", "[object", "null", "None", "True", "False"):
            self.assertNotIn(bad, text, bad)
        self.assertEqual(re.findall(r"\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b", text), [])

    def test_no_dash_no_pick_no_lock_no_guarantee_no_profit_on_screen(self):
        text = self.section.text()
        lowered = text.lower()
        for banned in ("—", "–", "guarantee", "profit", "win probability", "free money"):
            self.assertNotIn(banned, lowered, banned)
        for pattern in (r"\bpicks?\b", r"\block\b", r"\bedge\b", r"\broi\b", r"\bbet\b"):
            self.assertIsNone(re.search(pattern, lowered), pattern)

    def test_no_gendered_pronoun_the_page_prints(self):
        self.assertIsNone(re.search(r"\b(he|his|him|she|her|hers)\b", self.section.text(), re.I))

    def test_the_only_links_are_the_other_cards_and_nothing_points_at_bet_check_or_the_odds_board(self):
        hrefs = [n.attrs["href"] for n in self.root.walk() if n.tag == "A"]
        self.assertTrue(all(h.startswith("#/ufc?event=") for h in hrefs), hrefs)


def ur_chip(sample):
    parts = [f"{sample['fights']} FIGHT" + ("" if sample["fights"] == 1 else "S")]
    if sample.get("minutes") is not None:
        parts.append(f"{round(sample['minutes'])} MIN")
    return " · ".join(parts)


def rich_payload():
    """Two bouts built from the read tests' hand-made sheets: a loud one (every rule has something to say, five
    rounds, a price, a previous meeting and a shared opponent) and a thin one (two fights for one fighter)."""
    from tests.test_ufc_read import sweep_sheets
    sheets = sweep_sheets()
    made = [{"sheet": sheets[i], "read": ufc_read.build_read(sheets[i])} for i in (1, 2)]
    payload = card_payload()
    payload["bouts"] = [bout_from_case(made[0], "2001", 1, "main"), bout_from_case(made[1], "2002", 2, "main")]
    payload["event"]["bout_count"] = 2
    return payload


class TheRichRead(_Harness):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.payload = rich_payload()
        cls.out = cls.render(cls.payload)

    def setUp(self):
        self.root = self.out["root"]
        self.loud, self.thin = self.root.hooks("ufc-bout")

    def test_a_thin_item_wears_the_warning_chip_and_a_fair_one_does_not(self):
        saw = {"thin": 0, "fair": 0}
        for panel in (self.loud, self.thin):
            for node in panel.hooks("ufc-strength") + panel.hooks("ufc-weakness"):
                chip = node.with_class("uf-chip")[1]
                if chip.text() == "THIN SAMPLE":
                    saw["thin"] += 1
                    self.assertIn("uf-chip--warn", chip.classes)
                elif chip.text() == "FAIR SAMPLE":
                    saw["fair"] += 1
                    self.assertNotIn("uf-chip--warn", chip.classes)
        self.assertGreater(saw["thin"], 0)
        self.assertGreater(saw["fair"], 0)

    def test_the_thin_caveat_is_printed_under_the_sentence_and_not_behind_a_toggle(self):
        node = [n for n in self.thin.outside_details("ufc-strength") + self.thin.outside_details("ufc-weakness")
                if "THIN SAMPLE" in [c.text() for c in n.with_class("uf-chip")]][0]
        caveat = node.with_class("uf-item__caveat")[0].text()
        self.assertTrue(caveat.startswith("Thin sample: "), caveat)

    def test_a_derived_evidence_entry_says_it_was_worked_out_from_the_figures(self):
        self.assertIn("(worked out from the figures on this page)", self.loud.text())

    def test_a_long_list_prints_three_and_folds_the_rest_into_one_labelled_toggle(self):
        read = self.payload["bouts"][0]["read"]
        col = self.loud.hooks("ufc-column")[0]
        total = len(read["a"]["strengths"])
        self.assertGreater(total, 3)
        self.assertEqual(len(col.outside_details("ufc-strength")), 3)
        more = col.one("ufc-more-strength")
        self.assertEqual(more.kids[0].text(), f"MORE ({total - 3})")
        self.assertEqual(len(more.hooks("ufc-strength")), total - 3)

    def test_every_route_sentence_the_server_wrote_is_on_the_page_or_in_its_fold(self):
        read = self.payload["bouts"][0]["read"]
        text = self.loud.one("ufc-routes").text()
        for side in ("a", "b"):
            for route in read[side]["paths_to_victory"]:
                self.assertIn(route["sentence"], text)

    def test_a_fighter_with_a_long_gap_and_the_price_line_print_what_the_server_wrote(self):
        read = self.payload["bouts"][0]["read"]
        text = self.loud.text()
        for side in ("a", "b"):
            for kind in ("strengths", "weaknesses"):
                for item in read[side][kind]:
                    self.assertIn(item["sentence"], text)
        self.assertIn("The line has moved toward", self.loud.one("ufc-market").text())


class TheCompactSheetCarriesWhatThePageDraws(unittest.TestCase):
    def test_the_fact_sheet_reads_only_keys_the_compact_sheet_keeps(self):
        used = set(re.findall(r"\bsheet\.(\w+)", UF_JS))
        self.assertTrue(used >= {"features", "differentials", "physical", "layoff", "styles"}, used)
        self.assertEqual(used - set(ufc_read.COMPACT_KEEP) - {"features"}, set(),
                         "the page reads a sheet key the compact sheet drops")
        for key in ufc_read.COMPACT_FEATURES:
            self.assertIn(key, UF_JS)
        for dropped in ("ufccom_career", "strength_of_schedule_by_fight", "career_record_incl_non_ufc"):
            self.assertNotIn(dropped, UF_JS)

    def test_the_pages_method_words_are_the_servers(self):
        block = re.search(r"export const METHOD_WORDS = \{(.*?)\};", UF_JS, re.S).group(1)
        page = dict(re.findall(r'(\w+): "([^"]+)"', block))
        self.assertEqual(page, ufc_read.METHOD_WORDS)

    def test_compacting_keeps_what_it_says_it_keeps(self):
        case = cases()["synthetic_main_event"]
        compact = ufc_read.compact_sheet(case["sheet"])
        self.assertTrue(compact["compact"])
        for side in ("a", "b"):
            self.assertEqual(set(compact["features"][side]), set(ufc_read.COMPACT_FEATURES))
        self.assertLess(len(json.dumps(compact)), len(json.dumps(case["sheet"])) / 2)
        self.assertIsNone(ufc_read.compact_sheet(None))


class TheOtherStates(_Harness):
    def test_no_event_says_when_the_data_was_last_updated_and_links_the_record(self):
        out = self.render({"event": None, "bouts": [], "missing_bout_ids": [], "reason": "No UFC event is scheduled in our data right now.",
                           "data_updated_utc": "2026-10-03T19:14:09Z", "other_events": [], "label": ufc_read.LABEL})
        root = out["root"]
        self.assertEqual(root.one("ufc-no-event-reason").text(), "No UFC event is scheduled in our data right now.")
        updated = root.one("ufc-last-updated").text()
        self.assertRegex(updated, r"^Our UFC data was last updated SAT OCT 3 \d{1,2}:\d{2} (AM|PM) P[DS]T\.$")
        link = root.one("ufc-record-link")
        self.assertEqual((link.tag, link.attrs["href"], link.text()), ("A", "#/ufc/record", "VIEW THE UFC RECORD"))
        self.assertFalse(root.hooks("ufc-bout"))

    def test_no_event_and_no_data_at_all_says_there_is_no_data_yet(self):
        out = self.render({"event": None, "bouts": [], "reason": None, "data_updated_utc": None, "other_events": []})
        self.assertEqual(out["root"].one("ufc-last-updated").text(), "We have no UFC data on file yet.")
        self.assertEqual(out["root"].one("ufc-no-event-reason").text(), "No UFC event is scheduled in our data right now.")

    def test_a_development_show_is_labelled_and_an_event_without_bouts_says_so(self):
        payload = card_payload()
        payload["event"].update({"development_show": True, "bout_count": 0})
        payload["bouts"], payload["reason"] = [], "This event has no bouts on file yet."
        root = self.render(payload)["root"]
        self.assertIn("This is a development show.", root.one("ufc-development-show").text())
        self.assertEqual(root.one("ufc-no-bouts").text(), "This event has no bouts on file yet.")

    def test_a_finished_bout_shows_its_result_as_a_plain_fact(self):
        payload = card_payload()
        payload["bouts"][0]["status"] = "final"
        payload["bouts"][0]["result"] = {"outcome": "decided", "winner_id": "102", "winner_name": "Ben Brawler", "method": "DEC_UNANIMOUS",
                                         "method_words": "unanimous decision", "detail": None, "end_round": 5, "end_time_s": 300.0}
        panel = self.render(payload)["root"].hooks("ufc-bout")[0]
        self.assertEqual(panel.one("ufc-result").text(), "Result: Ben Brawler won by unanimous decision in round 5.")
        self.assertIn("FINISHED", [c.text() for c in panel.with_class("uf-chip")])
        payload["bouts"][0]["result"] = {"outcome": "draw", "winner_name": None}
        self.assertEqual(self.render(payload)["root"].hooks("ufc-result")[0].text(), "Result: a draw.")

    def test_a_payload_that_is_not_an_object_renders_nothing(self):
        for junk in (None, "nope", 7, []):
            out = self.render(junk)
            self.assertIsNone(out["section"], junk)


class MountingFetchesTheRoute(_Harness):
    def test_it_asks_for_the_compact_sheet_and_replaces_the_loading_line_with_the_card(self):
        out = self.mount([["/ufc/fight-night", {"body": card_payload()}]])
        self.assertEqual(out["calls"], ["/ufc/fight-night?sheet=compact"])
        kids = out["root"].kids
        self.assertEqual([k.hook for k in kids], ["ufc-fight-night"], "the loading line must be gone")
        self.assertEqual(len(out["root"].hooks("ufc-bout")), 4)
        self.assertEqual(out["result"], {"rendered": True, "event": card_payload()["event"]})

    def test_an_event_id_asks_for_that_event(self):
        out = self.mount([["/ufc/fight-night/600061541", {"body": card_payload()}]], options={"eventId": "600061541"})
        self.assertEqual(out["calls"], ["/ufc/fight-night/600061541?sheet=compact"])

    def test_the_analyst_option_reaches_the_slots(self):
        out = self.mount([["/ufc/fight-night", {"body": card_payload()}]], analyst="writes")
        self.assertEqual(len(out["analystCalls"]), 5)

    def test_a_signed_out_reader_gets_the_sign_in_gate_not_a_blank(self):
        out = self.mount([["/ufc/fight-night", {"error": {"status": 401, "detail": {"error": "unauthorized", "message": "x"}}}]])
        root = out["root"]
        self.assertTrue(root.hooks("auth-required"))
        self.assertEqual(root.one("signin-link").attrs["href"], "#/signin")
        self.assertFalse(root.hooks("ufc-bout"))
        self.assertFalse(root.hooks("ufc-fight-night-holder") and [h for h in root.hooks("ufc-fight-night-holder") if "Loading" in h.text()])
        self.assertEqual(out["result"], {"rendered": False, "event": None})

    def test_a_failed_request_is_an_error_state_that_says_what_failed_and_not_an_empty_card(self):
        for status in (503, None):
            out = self.mount([["/ufc/fight-night", {"error": {"status": status, "detail": "UFC data is not readable right now"}}]])
            root = out["root"]
            self.assertTrue(root.hooks("view-error"), status)
            self.assertFalse(root.hooks("ufc-bout"))
            self.assertNotIn("No UFC event is scheduled", root.text())

    def test_a_no_event_answer_renders_the_no_event_state(self):
        body = {"event": None, "bouts": [], "reason": "No UFC event is scheduled in our data right now.",
                "data_updated_utc": "2026-10-03T19:14:09Z", "other_events": []}
        out = self.mount([["/ufc/fight-night", {"body": body}]])
        self.assertTrue(out["root"].hooks("ufc-no-event"))
        self.assertEqual(out["result"]["rendered"], False)


@unittest.skipUnless(NODE and HAS_FASTAPI, "node or fastapi not installed")
class TheRealRoutesOwnOutputRenders(_Harness):
    """The contract between the route and the page: what api/ufc_fights.py serves for the data layer's synthetic
    world, run through the real page."""

    def test_the_synthetic_card_as_the_route_serves_it(self):
        import tempfile as tf
        from datetime import datetime, timezone
        from unittest import mock

        from fastapi import FastAPI

        from api import datasvc, ufc_fights
        from src.appstate import users as users_store
        from tests.test_datasvc_ufc_api import request
        from tests.test_datasvc_ufc_features import build_store

        now = datetime(2026, 10, 3, 15, 0, tzinfo=timezone.utc)
        with tf.TemporaryDirectory() as tmp:
            data = Path(tmp) / "ufc"
            build_store(data)
            db = Path(tmp) / "app.db"
            with mock.patch.object(users_store, "db_path", lambda: db), mock.patch.object(datasvc, "_now", lambda: now):
                datasvc.use_data_dir(data)
                try:
                    user = users_store.create_user("analyst@example.com", status="active", db=db)
                    token = users_store.issue_invite_token(user.id, db=db)
                    app = FastAPI()
                    app.include_router(ufc_fights.router)
                    status, body, _ = request(app, "GET", "/ufc/fight-night?sheet=compact", {"Authorization": f"Bearer {token}"})
                finally:
                    datasvc.use_data_dir(None)
        self.assertEqual(status, 200, body)
        out = self.mount([["/ufc/fight-night", {"body": body}]])
        root = out["root"]
        panels = root.hooks("ufc-bout")
        self.assertEqual([p.attrs["data-bout-id"] for p in panels], ["9101", "9102"])
        self.assertEqual([f.kids[0].text() for f in panels[0].hooks("ufc-fighter")], ["Alex Archer", "Ben Brawler"])
        self.assertEqual([p.text() for p in panels[0].hooks("ufc-price")], ["-170 · 60.7%", "+145 · 39.3%"])
        self.assertEqual(panels[0].one("ufc-headline").text(), body["bouts"][0]["read"]["headline"])
        self.assertTrue(panels[0].hooks("ufc-fact-sheet"))
        self.assertEqual([p.text() for p in panels[1].hooks("ufc-price")], ["No price on file", "No price on file"])
        self.assertEqual(root.text().count("undefined"), 0)


if __name__ == "__main__":
    unittest.main()
