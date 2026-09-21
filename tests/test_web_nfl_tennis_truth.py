"""What the NFL and Tennis pages SAY, run for real (review fixes, 2026-09-20).

NFL and Tennis were routed live on 2026-09-19/20. A review of that change
found ten places where the page either broke or printed something false.
Every other web test in this directory is a static text scan -- which is
how these got through: the source said the right words, and nobody ran
the code that decides whether a reader sees them. So the behavioural
checks in this file RUN the real modules (card.js, cardrecord.js,
tennis.js) under node, against a fake DOM and a stubbed `apiGet`, and read
back what a reader would see:

  * the NFL record page printed WIN RATE 100.0% / ROI +105.0% off one pick
    in its "EVERYTHING TOGETHER" panel, under a note saying the sample was
    too small for a percentage -- and it showed MLB's props/totals panels,
    whose sentences are false for NFL;
  * its intro said "every card we have ever published" while the page
    counts only the current NFL rule, and the retired rule's label said
    that rule "stays on the record" when this page no longer shows it;
  * tennis.js called `renderError(err)` instead of `renderError(main,
    err)`, so any failure (401, 5xx, timeout) threw and left a blank page;
  * the tennis board said "No tennis matches are priced for this date"
    when the store held zero tennis rows at all -- no capture, not no
    matches;
  * every NFL pick's "Open this matchup" opened MLB's game page (a 404);
  * a live NFL_CARD_V2 card, which has no probabilities of its own,
    warned that "our own probabilities are running uncalibrated".

Two smaller things seen while checking those pages in the browser are
pinned here too: an NFL card said "before first pitch", and the tennis
board sat flush against the screen edge on a phone.

Each MLB control case beside an NFL one is there on purpose: the fixes are
scoped to NFL, and MLB's page must render exactly as before.

The node checks skip when `node` is not installed (the GitHub
ubuntu-latest runner has it). The static checks below them always run.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB_JS = ROOT / "web" / "js"
WEB_CSS = ROOT / "web" / "css"
NODE = shutil.which("node")

# Replaces web/js/api.js inside the scratch copy. Every name the real
# module exports is kept, so any import in the module graph resolves; the
# two fetchers hand the request to the scenario's stubbed responses.
API_STUB = r"""
export class ApiError extends Error {
  constructor(status, detail) {
    super(typeof detail === "string" ? detail : JSON.stringify(detail));
    this.status = status;
    this.detail = detail;
  }
}
export const TOKEN_STORAGE_KEY = "test.invite_token";
export const FREE_CHECK_TOKEN_STORAGE_KEY = "test.free_check_token";
export const DEFAULT_TIMEOUT_MS = 20000;
export function getToken() { return null; }
export function setToken() {}
export function clearToken() {}
export function getFreeCheckToken() { return null; }
export function setFreeCheckToken() {}
export function setPublicDemo() {}
export function isPublicDemo() { return true; }
export function apiFetch(path, options) { return globalThis.__apiGet(path, options); }
export function apiGet(path, options) { return globalThis.__apiGet(path, options); }
export function apiPost() { throw new Error("no POST in these tests"); }
export function apiDelete() { throw new Error("no DELETE in these tests"); }
export function trackFunnelEvent() {}
"""

# A fake DOM just big enough for el()/clear()/renderError(): nodes with
# children, attributes, textContent and a classList. appendChild throws on
# a non-node exactly as a browser does -- that is the tennis.js failure.
RUNNER = r"""
import fs from "node:fs";
import { ApiError } from "./js/api.js";

class FakeNode {
  constructor(tag, text) {
    this.nodeType = tag ? 1 : 3;
    this.tagName = tag ? String(tag).toUpperCase() : "#text";
    this._text = text == null ? "" : String(text);
    this.attributes = {};
    this.childNodes = [];
    this.parentNode = null;
    this.style = {};
    const self = this;
    this.classList = {
      add(...names) {
        const set = new Set((self.attributes.class || "").split(/\s+/).filter(Boolean));
        names.forEach((n) => set.add(n));
        self.attributes.class = [...set].join(" ");
      },
      remove(...names) {
        const set = new Set((self.attributes.class || "").split(/\s+/).filter(Boolean));
        names.forEach((n) => set.delete(n));
        self.attributes.class = [...set].join(" ");
      },
      contains(name) {
        return (self.attributes.class || "").split(/\s+/).includes(name);
      },
    };
  }
  get firstChild() { return this.childNodes[0] || null; }
  appendChild(child) {
    if (!(child instanceof FakeNode)) {
      throw new TypeError("Failed to execute 'appendChild': parameter 1 is not of type 'Node'.");
    }
    if (child.parentNode) child.parentNode.removeChild(child);
    child.parentNode = this;
    this.childNodes.push(child);
    return child;
  }
  insertBefore(child, ref) {
    if (!ref) return this.appendChild(child);
    if (child.parentNode) child.parentNode.removeChild(child);
    child.parentNode = this;
    this.childNodes.splice(this.childNodes.indexOf(ref), 0, child);
    return child;
  }
  removeChild(child) {
    const i = this.childNodes.indexOf(child);
    if (i >= 0) this.childNodes.splice(i, 1);
    child.parentNode = null;
    return child;
  }
  setAttribute(key, value) { this.attributes[key] = String(value); }
  getAttribute(key) { return key in this.attributes ? this.attributes[key] : null; }
  removeAttribute(key) { delete this.attributes[key]; }
  addEventListener() {}
  querySelector() { return null; }
  querySelectorAll() { return []; }
  get offsetWidth() { return 0; }
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
globalThis.window = {
  location: { hash: "" },
  scrollTo() {},
  matchMedia: () => ({ matches: false }),
  addEventListener() {},
};

const scenario = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const calls = [];
globalThis.__apiGet = async (path) => {
  calls.push(path);
  for (const [prefix, resp] of scenario.responses) {
    if (path.startsWith(prefix)) {
      if (resp.error) throw new ApiError(resp.error.status, resp.error.detail);
      return JSON.parse(JSON.stringify(resp.body));
    }
  }
  throw new ApiError(404, `no stub for ${path}`);
};

function walk(node, out) {
  if (node.nodeType !== 1) return;
  out.push({
    tag: node.tagName.toLowerCase(),
    hook: node.getAttribute("data-hook"),
    href: node.getAttribute("href"),
    cls: node.getAttribute("class"),
    text: node.textContent,
  });
  for (const child of node.childNodes) walk(child, out);
}

const mod = await import(new URL(`./js/${scenario.module}`, import.meta.url));
const container = new FakeNode("main");
let rejected = null;
try {
  const args = scenario.passContainer ? [container, ...scenario.args] : scenario.args;
  const result = await mod[scenario.export](...args);
  if (!scenario.passContainer && result instanceof FakeNode) container.appendChild(result);
} catch (err) {
  rejected = `${err && err.name}: ${err && err.message}`;
}
const nodes = [];
walk(container, nodes);
process.stdout.write(JSON.stringify({ rejected, text: container.textContent, nodes, calls }));
"""


class _JsHarness(unittest.TestCase):
    """Copies web/js into a scratch dir once per class, swaps api.js for
    the stub, and runs one scenario per call in a fresh node process."""

    _tmp = None

    @classmethod
    def setUpClass(cls):
        if not NODE:
            raise unittest.SkipTest("node is not installed")
        cls._tmp = tempfile.TemporaryDirectory()
        root = Path(cls._tmp.name)
        (root / "js").mkdir()
        for path in WEB_JS.glob("*.js"):
            shutil.copy(path, root / "js" / path.name)
        (root / "js" / "api.js").write_text(API_STUB, encoding="utf-8")
        (root / "package.json").write_text('{"type": "module"}', encoding="utf-8")
        (root / "run.mjs").write_text(RUNNER, encoding="utf-8")
        cls._root = root

    @classmethod
    def tearDownClass(cls):
        if cls._tmp is not None:
            cls._tmp.cleanup()

    def run_js(self, module, export, args, responses=(), pass_container=True):
        scenario = {"module": module, "export": export, "args": list(args),
                    "responses": [list(r) for r in responses],
                    "passContainer": pass_container}
        path = self._root / "scenario.json"
        path.write_text(json.dumps(scenario), encoding="utf-8")
        proc = subprocess.run([NODE, str(self._root / "run.mjs"), str(path)],
                              capture_output=True, text=True, timeout=60,
                              encoding="utf-8")
        if proc.returncode != 0:
            self.fail(f"node harness failed:\n{proc.stderr}")
        return json.loads(proc.stdout)

    @staticmethod
    def hooks(out):
        return {n["hook"] for n in out["nodes"] if n["hook"]}

    @staticmethod
    def hrefs(out):
        return [n["href"] for n in out["nodes"] if n["tag"] == "a" and n["href"]]

    @staticmethod
    def stat_tiles(out):
        """Every headline tile's text, e.g. 'WIN RATE—' or 'WIN RATE100.0%'."""
        return [n["text"] for n in out["nodes"] if n["cls"] == "crp-stat"]


def _kind(n_staked, wins=0, losses=0, profit=0.0):
    return {"n_staked": n_staked, "wins": wins, "losses": losses, "pushes": 0,
            "voids": 0, "win_rate": (wins / n_staked) if n_staked else None,
            "profit_units": profit,
            "roi_pct": round(profit / n_staked * 100.0, 3) if n_staked else None}


def _one_pick_record(sport, rule):
    """card_ledger.record()'s shape for one settled day: one spread pick
    that won at +105 -- exactly the verifier's reproduction."""
    rec = {"days": 1, "wins": 1, "losses": 0, "pushes": 0, "voids": 0,
           "n_staked": 1, "win_rate": 1.0, "profit_units": 1.05, "roi_pct": 105.0,
           "by_kind": {"game": _kind(1, wins=1, profit=1.05),
                       "prop": _kind(0), "total": _kind(0)},
           "chain_ok": True, "rows_checked": 9}
    if sport == "nfl":
        rec.update({"sport": "nfl", "rule": rule,
                    "notice": "Experimental selections. Performance is still being evaluated."})
    return rec


_ONE_DAY_HISTORY = {
    "days": [{"date": "2026-09-27", "wins": 1, "losses": 0, "pushes": 0, "voids": 0,
              "profit_units": 1.05, "published_row_hash": "abc123",
              "picks": [{"bet": "Take New York Jets +6.5 at +105", "result": "WIN",
                         "price": 105, "book": "fanduel", "profit_units": 1.05,
                         "market": "spread"}]}],
    "pending_days": [], "truncated": False, "total_days": 1,
}


class NflRecordPageShowsOnlyWhatAppliesToNfl(_JsHarness):
    """Findings 7, 11, 15: no MLB-only panel, and no percentage below the
    NFL sample floor anywhere on the page."""

    def _render(self, sport, rule="NFL_CARD_V2"):
        return self.run_js("cardrecord.js", "renderCardRecord", [{"sport": sport}], responses=[
            ("/card/record", {"body": _one_pick_record(sport, rule)}),
            ("/card/history", {"body": _ONE_DAY_HISTORY}),
        ])

    def test_no_win_rate_or_roi_figure_below_the_floor(self):
        out = self._render("nfl")
        self.assertIsNone(out["rejected"])
        rate_tiles = [t for t in self.stat_tiles(out)
                      if t.startswith("WIN RATE") or t.startswith("ROI PER UNIT STAKED")]
        self.assertTrue(rate_tiles, "the headline rendered no rate tiles at all")
        for tile in rate_tiles:
            self.assertTrue(tile.endswith("—"), f"NFL printed a rate off one pick: {tile!r}")
        self.assertNotIn("100.0%", out["text"])
        self.assertNotIn("105.0%", out["text"])
        self.assertIn("record-nfl-sample-note", self.hooks(out))

    def test_no_prop_total_or_combined_panel_on_nfl(self):
        out = self._render("nfl")
        hooks = self.hooks(out)
        for hook in ("record-prop-headline", "record-total-headline",
                     "record-combined-headline", "record-prop-none", "record-total-none"):
            self.assertNotIn(hook, hooks)
        self.assertNotIn("Props are on the card from", out["text"])
        self.assertNotIn("Totals are on the card from", out["text"])
        self.assertNotIn("player props and totals added together", out["text"])

    def test_nfl_headline_says_every_market_is_counted_in_it(self):
        out = self._render("nfl")
        self.assertTrue(any(t.startswith("ALL PICKS (W-L-P)") for t in self.stat_tiles(out)))
        self.assertIn("record-nfl-markets-note", self.hooks(out))

    def test_mlb_record_page_is_unchanged(self):
        # Control: MLB keeps all three panels and its combined rate.
        out = self._render("mlb")
        hooks = self.hooks(out)
        for hook in ("record-prop-headline", "record-total-headline",
                     "record-combined-headline"):
            self.assertIn(hook, hooks)
        self.assertTrue(any(t.startswith("GAME PICKS (W-L-P)") for t in self.stat_tiles(out)))
        self.assertIn("WIN RATE100.0%", self.stat_tiles(out))


class NflRecordPageSaysWhichRuleItCounts(_JsHarness):
    """Finding 20: the page counts the current NFL rule only, so it must
    not say 'every card we have ever published'; the retired rule's
    record is reachable, and never shown under the wrong rule's name."""

    def test_current_rule_intro(self):
        out = self.run_js("cardrecord.js", "renderCardRecord", [{"sport": "nfl"}], responses=[
            ("/card/record", {"body": {"days": 0, "n_staked": 0, "rule": "NFL_CARD_V2",
                                       "sport": "nfl", "chain_ok": True, "rows_checked": 9}}),
            ("/card/history", {"body": {"days": [], "pending_days": []}}),
        ])
        self.assertIsNone(out["rejected"])
        self.assertNotIn("EVERY CARD WE HAVE EVER PUBLISHED", out["text"])
        self.assertNotIn("Every pick this product has made", out["text"])
        self.assertIn("CURRENT NFL RULE", out["text"])
        self.assertIn("#/nfl/record?rule=NFL_CARD_V1", self.hrefs(out))

    def test_mlb_intro_is_unchanged(self):
        out = self.run_js("cardrecord.js", "renderCardRecord", [{}], responses=[
            ("/card/record", {"body": {"days": 0, "n_staked": 0, "chain_ok": True,
                                       "rows_checked": 9}}),
            ("/card/history", {"body": {"days": [], "pending_days": []}}),
        ])
        self.assertIn("EVERY CARD WE HAVE EVER PUBLISHED", out["text"])
        self.assertNotIn("#/nfl/record?rule=NFL_CARD_V1", self.hrefs(out))

    def test_retired_rule_view_asks_for_that_rule_and_names_it(self):
        out = self.run_js("cardrecord.js", "renderCardRecord",
                          [{"sport": "nfl", "rule": "NFL_CARD_V1"}], responses=[
            ("/card/record", {"body": _one_pick_record("nfl", "NFL_CARD_V1")}),
            ("/card/history", {"body": _ONE_DAY_HISTORY}),
        ])
        self.assertIsNone(out["rejected"])
        self.assertEqual(len(out["calls"]), 2)
        for call in out["calls"]:
            self.assertIn("sport=nfl", call)
            self.assertIn("rule=NFL_CARD_V1", call)
        self.assertIn("OLD NFL RULE", out["text"])
        self.assertIn("record-headline", self.hooks(out))
        self.assertIn("record-nfl-sample-note", self.hooks(out))
        self.assertIn("#/nfl/record", self.hrefs(out))

    def test_retired_rule_view_refuses_another_rules_numbers(self):
        # A server that ignores ?rule= answers with the live rule's record.
        # Printing it under the old rule's heading would be a false page.
        out = self.run_js("cardrecord.js", "renderCardRecord",
                          [{"sport": "nfl", "rule": "NFL_CARD_V1"}], responses=[
            ("/card/record", {"body": _one_pick_record("nfl", "NFL_CARD_V2")}),
            ("/card/history", {"body": _ONE_DAY_HISTORY}),
        ])
        self.assertIsNone(out["rejected"])
        hooks = self.hooks(out)
        self.assertIn("record-rule-unavailable", hooks)
        self.assertNotIn("record-headline", hooks)
        self.assertNotIn("record-days", hooks)
        self.assertNotIn("1-0-0", out["text"])

    def test_an_unknown_rule_is_never_forwarded(self):
        out = self.run_js("cardrecord.js", "renderCardRecord",
                          [{"sport": "nfl", "rule": "anything&else"}], responses=[
            ("/card/record", {"body": {"days": 0, "n_staked": 0, "rule": "NFL_CARD_V2"}}),
            ("/card/history", {"body": {"days": [], "pending_days": []}}),
        ])
        for call in out["calls"]:
            self.assertNotIn("rule=", call)


def _nfl_v2_pick(**extra):
    pick = {"sport": "nfl", "rank": 1, "market": "spread", "line": 6.5, "side": "away",
            "game_id": "2026_03_NYJ_DET", "away_team": "New York Jets",
            "home_team": "Detroit Lions", "first_pitch_utc": "2099-09-27T17:00:00Z",
            "bet": "Take New York Jets +6.5 at +105", "price": 105, "book": "fanduel",
            "books": 6, "label": "LEAN", "market_probability": 0.51,
            "model_probability": None, "probability": None,
            "why": ["At +105 with fanduel the price is better than the rest of the market."]}
    pick.update(extra)
    return pick


def _mlb_pick(**extra):
    pick = {"rank": 1, "game_pk": 777, "away_team": "Boston Red Sox",
            "home_team": "New York Yankees", "first_pitch_utc": "2099-09-27T23:05:00Z",
            "bet": "Take New York Yankees at -140", "price": -140, "book": "draftkings",
            "books": 8, "label": "LEAN", "market_probability": 0.57,
            "model_probability": 0.6, "why": ["The market makes the Yankees the favourite."]}
    pick.update(extra)
    return pick


class NflCardCopy(_JsHarness):
    """Findings 16, 17, 20 on the NFL card page itself."""

    def test_nfl_pick_has_no_open_this_matchup_link(self):
        out = self.run_js("card.js", "compactPickCard", [_nfl_v2_pick(), {}],
                          pass_container=False)
        self.assertIsNone(out["rejected"])
        self.assertNotIn("card-open-matchup", self.hooks(out))
        self.assertFalse([h for h in self.hrefs(out) if h.startswith("#/game/")])

    def test_mlb_pick_keeps_its_matchup_link(self):
        out = self.run_js("card.js", "compactPickCard", [_mlb_pick(), {}],
                          pass_container=False)
        self.assertIn("card-open-matchup", self.hooks(out))

    def _live_card(self, sport, payload):
        suffix = "?sport=nfl" if sport == "nfl" else ""
        return self.run_js("card.js", "renderCard", [{"sport": sport}], responses=[
            (f"/card/record{suffix}", {"body": {"days": 0, "n_staked": 0}}),
            (f"/card{suffix}", {"body": payload}),
        ])

    def test_a_card_without_a_model_prints_no_model_or_calibration_copy(self):
        payload = {"date": "2099-09-27", "sport": "nfl", "rule": "NFL_CARD_V2",
                   "frozen": False, "has_model": False, "calibrated": False,
                   "filled": 1, "picks": [_nfl_v2_pick(model_probability=0.6)],
                   "disclaimer": "This is analysis, not advice.",
                   "basis": "The fair price comes from the market itself."}
        out = self._live_card("nfl", payload)
        self.assertIsNone(out["rejected"])
        self.assertIn("card-pick", self.hooks(out))
        self.assertNotIn("uncalibrated", out["text"])
        self.assertNotIn("Our number", out["text"])
        self.assertNotIn("our own numbers do not agree", out["text"])

    def test_mlb_card_still_warns_when_uncalibrated(self):
        # Control: MLB sends no has_model key; its warning is unchanged.
        payload = {"date": "2099-09-27", "frozen": False, "calibrated": False,
                   "picks": [_mlb_pick()], "disclaimer": "d", "basis": "b"}
        out = self._live_card("mlb", payload)
        self.assertIn("uncalibrated", out["text"])
        self.assertIn("Our number 60%", out["text"])
        self.assertIn("before first pitch", out["text"])

    def test_retired_rule_label_is_true_about_where_its_record_is(self):
        payload = {"date": "2026-09-20", "sport": "nfl", "rule": "NFL_CARD_V1",
                   "frozen": True, "picks": [_nfl_v2_pick(market="moneyline",
                                                          bet="Take Detroit Lions to win at -278",
                                                          price=-278, locked=True)]}
        out = self._live_card("nfl", payload)
        self.assertIsNone(out["rejected"])
        label = [n["text"] for n in out["nodes"] if n["hook"] == "card-retired-rule"]
        self.assertEqual(len(label), 1)
        self.assertNotIn("stays on the record", label[0])
        self.assertIn("ledger exactly as published", label[0])
        self.assertIn("#/nfl/record?rule=NFL_CARD_V1", self.hrefs(out))
        # The record line under it is the CURRENT rule's -- it must say so,
        # or "Nothing graded yet" reads as a claim about this card.
        record = [n["text"] for n in out["nodes"] if n["hook"] == "card-record"]
        self.assertEqual(len(record), 1)
        self.assertIn("CURRENT NFL RULE", record[0])
        # Seen on #/nfl the same night: an NFL card said "before first pitch".
        self.assertIn("before kickoff", out["text"])
        self.assertNotIn("first pitch", out["text"])


class TennisBoardFailureAndEmptyStates(_JsHarness):
    """Findings 12 and 22."""

    def _board(self, response):
        return self.run_js("tennis.js", "renderTennisBoard", [],
                           responses=[("/tennis/board", response)])

    def test_401_renders_the_sign_in_gate_not_a_blank_page(self):
        out = self._board({"error": {"status": 401, "detail": "invite token required"}})
        self.assertIsNone(out["rejected"])
        self.assertIn("auth-required", self.hooks(out))

    def test_500_renders_request_failed(self):
        out = self._board({"error": {"status": 500, "detail": "boom"}})
        self.assertIsNone(out["rejected"])
        self.assertIn("view-error", self.hooks(out))

    def test_unreachable_server_renders_request_failed(self):
        out = self._board({"error": {"status": None, "detail": "timed out"}})
        self.assertIsNone(out["rejected"])
        self.assertIn("view-error", self.hooks(out))

    def test_no_tennis_prices_captured_at_all_is_said_as_that(self):
        out = self._board({"body": {"date": "2026-09-21", "tournaments": [],
                                    "captured_any": False, "last_captured_utc": None,
                                    "notice": "Research only. No tennis picks until "
                                              "results grading is connected."}})
        self.assertIsNone(out["rejected"])
        self.assertNotIn("No tennis matches are priced for this date", out["text"])
        self.assertIn("No tennis prices have been captured yet", out["text"])

    def test_board_sits_inside_the_page_gutter(self):
        # Seen at 375px on 2026-09-20: the board's text touched the screen
        # edge (DESIGN_SYSTEM.md section 7: a 16px gutter everywhere).
        out = self._board({"body": {"date": "2026-09-21", "tournaments": [],
                                    "captured_any": False, "notice": "Research only."}})
        boards = [n["cls"] for n in out["nodes"] if n["cls"] and "tennis-board" in n["cls"].split()]
        self.assertEqual(len(boards), 1)
        self.assertIn("gutter", boards[0].split())

    def test_none_for_this_date_names_our_capture_not_the_market(self):
        out = self._board({"body": {"date": "2026-09-21", "tournaments": [],
                                    "captured_any": True,
                                    "last_captured_utc": "2026-09-19T10:00:00+00:00",
                                    "notice": "Research only."}})
        self.assertNotIn("No tennis matches are priced", out["text"])
        self.assertNotIn("captured yet", out["text"])
        self.assertIn("on this date", out["text"])


# ---------------------------------------------------------------------
# Static checks -- always run, node or not.
# ---------------------------------------------------------------------

def _css_rules(css):
    """(selector, body) for every innermost rule, comments stripped --
    rules inside an @media block come out with their own selector."""
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    return [(m.group(1).strip(), m.group(2)) for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", css)]


class EverySportTabStaysReachableOnPhones(unittest.TestCase):
    """Finding 10: below 400px app.css hid every `.sportlevel__tab`. That
    was written when only MLB was a tab (and the bottom tab bar covered
    it); with NFL and Tennis as tabs too it removed the only chrome link to
    either sport on every phone narrower than 400px."""

    def test_no_stylesheet_hides_a_sport_tab(self):
        offenders = []
        for path in sorted(WEB_CSS.glob("*.css")):
            for selector, body in _css_rules(path.read_text(encoding="utf-8")):
                if "sportlevel__tab" in selector and re.search(r"display\s*:\s*none", body):
                    offenders.append(f"{path.name}: {selector}")
        self.assertEqual(offenders, [])


class DesignSystemDescribesThePerSportMenus(unittest.TestCase):
    """Finding 18: the doc said NFL/Tennis keep MLB's menu, which invites a
    'fix' back to the bug main.js's mountNav removed on 2026-09-20."""

    def setUp(self):
        text = (ROOT / "docs" / "DESIGN_SYSTEM.md").read_text(encoding="utf-8")
        start = text.index("**NFL and Tennis**")
        end = text.index("<summary>Pre-2026-09-19 text (history)</summary>", start)
        self.section = text[start:end]

    def test_no_longer_says_mlbs_menu_stays(self):
        self.assertNotIn("neither sport got its own rail wired", self.section)
        self.assertNotIn("making the record 1-0", self.section)

    def test_names_each_sports_own_menu(self):
        self.assertIn("mountNav", self.section)
        self.assertIn("`#/nfl/record`", self.section)
        self.assertIn("BOARD", self.section)

    def test_main_js_still_mounts_each_live_sports_own_submenu(self):
        # The code the doc now describes -- pinned so a revert is caught
        # by a test, not by a reader landing on MLB's record from NFL.
        main = (WEB_JS / "main.js").read_text(encoding="utf-8")
        self.assertIn("function mountNav(rail, tabbar, activeHash, sport", main)
        self.assertIn("own ? own.submenu", main)
        self.assertIn("mountNav(rail, tabbar, activeHash, sport);", main)


class TennisNewsItemIsTrue(unittest.TestCase):
    """Finding 22: the banner advertised a board that has shown nothing
    since tennis capture stalled on 2026-09-16."""

    def test_tennis_item_says_the_board_fills_as_prices_are_captured(self):
        news = (WEB_JS / "news.js").read_text(encoding="utf-8")
        start = news.index('href: "#/tennis"')
        item = news[news.rindex("{", 0, start):start]
        self.assertIn("as prices are captured", item)
        self.assertIn("No picks", item)


if __name__ == "__main__":
    unittest.main()
