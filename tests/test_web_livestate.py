"""web/js/livestate.js, linemarkets.js and their wiring (tiles.js, games.js), RUN
under node with a fake DOM and a stubbed apiGet -- behaviour, not text scans.

What this proves that a text scan cannot:
  - a started game's pregame price is never shown without the last-pregame label
    and its capture time (tile, game page, run line / total block);
  - a pregame game, an unavailable feed (null), and an `available: false` payload
    all render exactly as before: no strip, no label, no throw;
  - the browser asks /live/{date} once per window however many sections want it;
  - run line and total render only when the odds entry carries them (switch on).

The node tests skip when node is not installed (the GitHub runner has it).
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

from tests.test_customer_language import HARD_BANNED, NEGATION_ONLY, NEGATORS

ROOT = Path(__file__).resolve().parent.parent
WEB_JS = ROOT / "web" / "js"
NODE = shutil.which("node")

API_STUB = r"""
export class ApiError extends Error {
  constructor(status, detail) { super(String(detail)); this.status = status; this.detail = detail; }
}
export const TOKEN_STORAGE_KEY = "t"; export const TOKEN_CHANGED_EVENT = "t";
export const FREE_CHECK_TOKEN_STORAGE_KEY = "t"; export const DEFAULT_TIMEOUT_MS = 1;
export function getToken() { return "x"; } export function setToken() {} export function clearToken() {}
export function getFreeCheckToken() { return null; } export function setFreeCheckToken() {}
export function setPublicDemo() {} export function isPublicDemo() { return false; }
export function apiFetch(p, o) { return globalThis.__apiGet(p, o); }
export function apiGet(p, o) { return globalThis.__apiGet(p, o); }
export function apiPost() { throw new Error("no POST"); } export function apiDelete() { throw new Error("no DELETE"); }
export function trackFunnelEvent() {}
"""

RUNNER = r"""
import fs from "node:fs";
import { ApiError } from "./js/api.js";

class FakeNode {
  constructor(tag, text) {
    this.nodeType = tag ? 1 : 3;
    this.tagName = tag ? String(tag).toUpperCase() : "#text";
    this._text = text == null ? "" : String(text);
    this.attributes = {}; this.childNodes = []; this.parentNode = null; this.style = {};
    const self = this;
    const names = () => (self.attributes.class || "").split(/\s+/).filter(Boolean);
    this.classList = {
      add(...n) { const s = new Set(names()); n.forEach((x) => s.add(x)); self.attributes.class = [...s].join(" "); },
      remove(...n) { const s = new Set(names()); n.forEach((x) => s.delete(x)); self.attributes.class = [...s].join(" "); },
      contains(n) { return names().includes(n); },
    };
  }
  get firstChild() { return this.childNodes[0] || null; }
  set hidden(v) { if (v) this.attributes.hidden = ""; else delete this.attributes.hidden; }
  get hidden() { return "hidden" in this.attributes; }
  appendChild(c) {
    if (!(c instanceof FakeNode)) throw new TypeError("not a Node");
    if (c.parentNode) c.parentNode.removeChild(c);
    c.parentNode = this; this.childNodes.push(c); return c;
  }
  insertBefore(c, ref) {
    if (!ref) return this.appendChild(c);
    if (c.parentNode) c.parentNode.removeChild(c);
    c.parentNode = this; this.childNodes.splice(this.childNodes.indexOf(ref), 0, c); return c;
  }
  removeChild(c) { const i = this.childNodes.indexOf(c); if (i >= 0) this.childNodes.splice(i, 1); c.parentNode = null; return c; }
  remove() { if (this.parentNode) this.parentNode.removeChild(this); }
  setAttribute(k, v) { this.attributes[k] = String(v); }
  getAttribute(k) { return k in this.attributes ? this.attributes[k] : null; }
  removeAttribute(k) { delete this.attributes[k]; }
  addEventListener() {}
  _d(out) { for (const c of this.childNodes) { if (c.nodeType === 1) { out.push(c); c._d(out); } } return out; }
  matches(sel) {
    if (this.nodeType !== 1) return false;
    if (sel.startsWith(".")) return (this.attributes.class || "").split(/\s+/).includes(sel.slice(1));
    const m = sel.match(/^\[([\w-]+)(?:="([^"]*)")?\]$/);
    if (m) return m[1] in this.attributes && (m[2] === undefined || this.attributes[m[1]] === m[2]);
    return this.tagName.toLowerCase() === sel.toLowerCase();
  }
  querySelectorAll(sel) { return this._d([]).filter((n) => n.matches(sel)); }
  querySelector(sel) { return this.querySelectorAll(sel)[0] || null; }
  get textContent() { return this.nodeType === 3 ? this._text : this.childNodes.map((c) => c.textContent).join(""); }
  set textContent(v) {
    if (this.nodeType === 3) { this._text = String(v); return; }
    this.childNodes = []; if (v !== "" && v != null) this.appendChild(new FakeNode(null, v));
  }
}
globalThis.document = {
  createElement: (t) => new FakeNode(t), createTextNode: (t) => new FakeNode(null, t),
  querySelector: () => null, querySelectorAll: () => [], addEventListener() {},
};
const store = new Map();
globalThis.window = {
  location: { hash: "", search: "", host: "x.test", pathname: "/" },
  localStorage: { getItem: (k) => (store.has(k) ? store.get(k) : null), setItem: (k, v) => store.set(k, String(v)), removeItem: (k) => store.delete(k) },
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

const text = (n) => (n ? n.textContent : null);
const hook = (root, name) => root.querySelector(`[data-hook="${name}"]`);
const live = await import(new URL("./js/livestate.js", import.meta.url));
const out = { calls };

if (scenario.kind === "model") {
  out.models = scenario.games.map((g) => live.liveStripModel(g));
  out.labels = scenario.games.map((g) => live.pregameLabel(g, scenario.observed));
  out.shortLabels = scenario.games.map((g) => live.pregameShortLabel(g, scenario.observed));
  out.tileTexts = scenario.games.map((g) => live.tileLiveText(g));
  out.indexNull = [null, undefined, { available: false, games: [] }, { available: true }].map((p) => live.liveIndexOf(p));
  out.byPk = (() => { const idx = live.liveIndexOf({ available: true, games: scenario.games }); const g = live.liveByPk(idx, (scenario.games[1] || scenario.games[0]).game_pk); return g && g.game_id; })();
}

if (scenario.kind === "fetch") {
  live._resetLiveCache();
  let t = 1000;
  const now = () => t;
  const results = [];
  const fetcher = async (p) => { calls.push(p); if (scenario.fail) throw new Error("down"); return scenario.payload; };
  for (let i = 0; i < 5; i++) results.push(await live.fetchLiveIndex("2026-10-03", { fetcher, now }));
  out.afterBurst = calls.length;
  t += 31000;
  results.push(await live.fetchLiveIndex("2026-10-03", { fetcher, now }));
  out.afterWindow = calls.length;
  out.resultsNull = results.map((r) => r === null);
  out.size = results[0] ? results[0].size : null;
}

if (scenario.kind === "tile") {
  const { slateTile } = await import(new URL("./js/tiles.js", import.meta.url));
  const tile = slateTile(scenario.game, scenario.opts);
  out.live = text(hook(tile, "tile-live"));
  out.liveClass = hook(tile, "tile-live") ? hook(tile, "tile-live").attributes.class : null;
  out.pregame = text(hook(tile, "tile-pregame"));
  out.pregameTitle = hook(tile, "tile-pregame") ? hook(tile, "tile-pregame").attributes.title : null;
  out.prices = text(hook(tile, "tile-prices"));
}

if (scenario.kind === "lines") {
  const lm = await import(new URL("./js/linemarkets.js", import.meta.url));
  out.model = lm.lineMarketsModel(scenario.entry);
  const el = lm.renderLineMarkets(scenario.entry, scenario.live || null);
  out.rendered = el ? el.textContent : null;
  out.pregame = el && hook(el, "pregame-label") ? text(hook(el, "pregame-label")) : null;
  out.fmt = [lm.formatLine(-1.5), lm.formatLine(1.5), lm.formatLine(7, { signed: false }), lm.formatLine(null)];
}

if (scenario.kind === "game") {
  const { renderGameDetail } = await import(new URL("./js/games.js", import.meta.url));
  const host = new FakeNode("main");
  let rejected = null;
  try { await renderGameDetail(host, ...scenario.args); } catch (e) { rejected = `${e && e.name}: ${e && e.message}`; }
  out.rejected = rejected;
  out.text = host.textContent;
  out.hooks = host._d([]).map((n) => n.attributes["data-hook"]).filter(Boolean);
  out.strip = text(hook(host, "live-strip"));
  out.captured = text(hook(host, "prices-captured"));
  out.pregameLabels = host.querySelectorAll('[data-hook="pregame-label"]').map((n) => n.textContent);
  out.lineMarkets = text(hook(host, "line-markets"));
  out.mlPanel = text(hook(host, "price"));
}

if (scenario.kind === "today") {
  const { renderToday } = await import(new URL("./js/today.js", import.meta.url));
  const host = new FakeNode("main");
  let rejected = null;
  try { await renderToday(host); } catch (e) { rejected = `${e && e.name}: ${e && e.message}`; }
  out.rejected = rejected;
  out.text = host.textContent;
  const tiles = host.querySelectorAll('[data-hook="slate-tile"]');
  out.tiles = tiles.map((t) => ({ id: t.attributes["data-game-id"], live: text(hook(t, "tile-live")),
    pregame: text(hook(t, "tile-pregame")), prices: text(hook(t, "tile-prices")) }));
  out.heroPregame = host.querySelectorAll('[data-hook="pregame-label"]').map((n) => n.textContent);
}

process.stdout.write("@@" + JSON.stringify(out));
"""

OBSERVED = "2026-10-03T22:41:00Z"


def live_row(status="in_progress", **kw):
    row = {"game_id": "BOS-NYY-2026-10-03-1", "game_pk": 11, "away_team": "BOS",
           "home_team": "NYY", "status": status, "detailed_state": "In Progress",
           "away_score": 3, "home_score": 2, "inning": 6, "half": "top",
           "inning_text": "Top 6th", "outs": 1, "pitcher": "Gerrit Cole"}
    row.update(kw)
    return row


def entry_with_lines(spreads=True, totals=True):
    staleness = {"observed_utc": OBSERVED, "age_seconds": 100, "has_board": True}
    markets = {"h2h": {"board_available": True}}
    if spreads:
        markets["spreads"] = {
            "board_available": True, "main_line": {"home": -1.5, "away": 1.5},
            "books_at_main_line": 9,
            "best": {"away": {"price": -150, "books": ["fanduel"], "line": 1.5},
                     "home": {"price": 135, "books": ["lowvig", "betrivers"], "line": -1.5}},
            "consensus": {"books": 9, "away": {"implied_price": -158},
                          "home": {"implied_price": 140}},
            "other_lines": [{"home_line": -2.5, "books": 1}], "staleness": staleness}
    if totals:
        markets["totals"] = {
            "board_available": True, "main_line": {"total": 8.5}, "books_at_main_line": 4,
            "best": {"over": {"price": -105, "books": ["bovada"], "total": 8.5},
                     "under": {"price": -112, "books": ["fanduel"], "total": 8.5}},
            "consensus": None,
            "consensus_unavailable_reason": "4 books quoted the main line; below the 6-book floor "
                                            "a consensus means nothing",
            "other_lines": [], "staleness": staleness}
    return {"game_id": "BOS-NYY-2026-10-03-1", "away_team": "BOS", "home_team": "NYY",
            "markets": markets}


@unittest.skipUnless(NODE, "node is not installed")
class WebLiveStateTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
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
        cls._tmp.cleanup()

    def run_node(self, scenario: dict) -> dict:
        path = self._root / "scenario.json"
        path.write_text(json.dumps(scenario), encoding="utf-8")
        env = dict(os.environ, TZ="America/Los_Angeles")
        proc = subprocess.run([NODE, str(self._root / "run.mjs"), str(path)], capture_output=True,
                              text=True, timeout=90, encoding="utf-8", env=env)
        if proc.returncode != 0:
            self.fail(f"node harness failed:\n{proc.stderr[-3000:]}")
        line = [ln for ln in proc.stdout.splitlines() if ln.startswith("@@")][-1]
        return json.loads(line[2:])

    # ---- the model -------------------------------------------------------

    def test_strip_model_for_each_status(self):
        games = [
            live_row("pregame"),
            live_row("in_progress"),
            live_row("delayed", detailed_state="Delayed: Rain", inning_text="Bot 5th", outs=None),
            live_row("final", inning_text=None, outs=None, pitcher=None),
            live_row("postponed", away_score=None, home_score=None, detailed_state="Postponed"),
        ]
        out = self.run_node({"kind": "model", "games": games, "observed": OBSERVED})
        pregame, live, delayed, final, postponed = out["models"]
        self.assertIsNone(pregame)
        self.assertEqual(live, {"kind": "live", "label": "LIVE", "score": "BOS 3 · NYY 2",
                                "detail": "TOP 6TH · 1 OUT · P Gerrit Cole"})
        self.assertEqual(delayed["label"], "DELAYED")
        self.assertIn("Delayed: Rain", delayed["detail"])
        self.assertEqual(final, {"kind": "final", "label": "FINAL", "score": "BOS 3 · NYY 2",
                                 "detail": None})
        self.assertEqual(postponed["label"], "POSTPONED")
        self.assertIsNone(postponed["score"])

    def test_pregame_label_only_once_the_game_has_started(self):
        games = [live_row(s) for s in ("pregame", "in_progress", "delayed", "final", "postponed")]
        out = self.run_node({"kind": "model", "games": games, "observed": OBSERVED})
        self.assertIsNone(out["labels"][0])
        for label in out["labels"][1:]:
            self.assertRegex(label, r"^LAST PRE-GAME PRICE · \d{1,2}:\d{2} [AP]M")
        self.assertIsNone(out["shortLabels"][0])
        self.assertRegex(out["shortLabels"][1], r"^LAST PRE-GAME · \d{1,2}:\d{2} [AP]M")

    def test_label_without_a_capture_time_still_says_what_the_price_is(self):
        out = self.run_node({"kind": "model", "games": [live_row("final")], "observed": None})
        self.assertEqual(out["labels"][0], "LAST PRE-GAME PRICE")

    def test_unavailable_payloads_give_no_index(self):
        out = self.run_node({"kind": "model", "games": [live_row(), live_row(game_pk=12,
                             game_id="X-Y-2026-10-03-1")], "observed": OBSERVED})
        self.assertEqual(out["indexNull"], [None, None, None, None])
        self.assertEqual(out["byPk"], "X-Y-2026-10-03-1")

    # ---- the fetch -------------------------------------------------------

    def test_one_request_per_window_however_many_sections_ask(self):
        payload = {"available": True, "games": [live_row()]}
        out = self.run_node({"kind": "fetch", "payload": payload})
        self.assertEqual(out["afterBurst"], 1)
        self.assertEqual(out["afterWindow"], 2)
        self.assertEqual(out["calls"], ["/live/2026-10-03", "/live/2026-10-03"])
        self.assertEqual(out["size"], 1)

    def test_a_failing_feed_is_null_and_never_throws(self):
        out = self.run_node({"kind": "fetch", "payload": {}, "fail": True})
        self.assertTrue(all(out["resultsNull"]))

    def test_an_unavailable_payload_is_null(self):
        out = self.run_node({"kind": "fetch", "payload": {"available": False, "games": []}})
        self.assertTrue(all(out["resultsNull"]))

    # ---- the tile --------------------------------------------------------

    TILE_GAME = {"date": "2026-10-03", "away_team": "BOS", "home_team": "NYY",
                 "first_pitch_utc": "2026-10-03T22:10:00Z", "venue": "Yankee Stadium",
                 "game_id": "BOS-NYY-2026-10-03-1"}

    def tile(self, live):
        return self.run_node({"kind": "tile", "game": self.TILE_GAME,
                              "opts": {"awayPrice": 130, "homePrice": -150, "live": live,
                                       "priceObservedUtc": OBSERVED}})

    def test_in_progress_tile_shows_score_and_labels_the_price(self):
        out = self.tile(live_row("in_progress"))
        self.assertEqual(out["live"], "LIVE · BOS 3 · NYY 2 · TOP 6TH")
        self.assertRegex(out["pregame"], r"^LAST PRE-GAME · \d{1,2}:\d{2} [AP]M")
        self.assertRegex(out["pregameTitle"], r"^LAST PRE-GAME PRICE · ")
        self.assertIn("+130", out["prices"])

    def test_final_tile_shows_final_and_labels_the_price(self):
        out = self.tile(live_row("final"))
        self.assertTrue(out["live"].startswith("FINAL · BOS 3 · NYY 2"))
        self.assertIsNotNone(out["pregame"])

    def test_pregame_and_unavailable_tiles_are_unchanged(self):
        for live in (live_row("pregame"), None):
            out = self.tile(live)
            self.assertIsNone(out["live"])
            self.assertIsNone(out["pregame"])
            self.assertIn("+130", out["prices"])

    # ---- run line and total ----------------------------------------------

    def test_switch_off_entry_renders_nothing(self):
        entry = {"game_id": "g", "away_team": "BOS", "home_team": "NYY",
                 "markets": {"h2h": {"board_available": True}}}
        out = self.run_node({"kind": "lines", "entry": entry})
        self.assertIsNone(out["model"])
        self.assertIsNone(out["rendered"])
        self.run_node({"kind": "lines", "entry": None})

    def test_run_line_and_total_render_best_price_books_and_lines(self):
        out = self.run_node({"kind": "lines", "entry": entry_with_lines()})
        text = out["rendered"]
        self.assertIn("RUN LINE", text)
        self.assertIn("BOS +1.5", text)
        self.assertIn("NYY -1.5", text)
        self.assertIn("-150", text)
        self.assertIn("+135", text)
        self.assertIn("LowVig, BetRivers", text)
        self.assertIn("fair price +140", text)
        self.assertIn("9 books at this line", text)
        self.assertIn("also quoted: -2.5 (1 book)", text)
        self.assertIn("OVER 8.5", text)
        self.assertIn("UNDER 8.5", text)
        self.assertIn("-105", text)
        self.assertIn("4 books at this line", text)
        self.assertIn("6-book floor", text)       # no fair price below the floor, said why
        self.assertEqual(text.count("fair price"), 2)   # run line only; none for the total
        self.assertEqual(out["fmt"], ["-1.5", "+1.5", "7.0", None])

    def test_an_unavailable_market_says_so(self):
        entry = entry_with_lines(spreads=False)
        entry["markets"]["spreads"] = {"board_available": False,
                                       "reason": "no run line / total observations recorded for this game"}
        out = self.run_node({"kind": "lines", "entry": entry})
        self.assertIn("no run line / total observations recorded", out["rendered"])
        self.assertIn("OVER 8.5", out["rendered"])

    def test_a_started_game_labels_the_block_with_its_capture_time(self):
        out = self.run_node({"kind": "lines", "entry": entry_with_lines(),
                             "live": live_row("in_progress")})
        self.assertRegex(out["pregame"], r"^LAST PRE-GAME PRICE · \d{1,2}:\d{2} [AP]M")

    def test_a_pregame_game_shows_a_plain_capture_time_not_the_label(self):
        out = self.run_node({"kind": "lines", "entry": entry_with_lines(),
                             "live": live_row("pregame")})
        self.assertIsNone(out["pregame"])
        self.assertRegex(out["rendered"], r"CAPTURED \d{1,2}:\d{2} [AP]M")

    # ---- the game page ---------------------------------------------------

    def game_scenario(self, live_body, odds_body):
        quick = {"game_id": "BOS-NYY-2026-10-03-1", "away_team": "BOS", "home_team": "NYY",
                 "verdict": "no_play", "top_findings": [],
                 "price": {"available": True,
                           "sides": {"away": {"best_price": 130, "best_book": "fanduel"},
                                     "home": {"best_price": -150, "best_book": "lowvig"}},
                           "staleness": {"observed_utc": OBSERVED, "age_seconds": 60}}}
        responses = [
            ["/game/", {"body": {"quick": quick, "advanced": {"sections": {}, "gaps": {}},
                                 "engine": None}}],
            ["/card/", {"body": {"picks": []}}],
            ["/live/", live_body],
            ["/odds/", odds_body],
        ]
        return {"kind": "game", "args": ["2026-10-03", "BOS", "NYY"], "responses": responses}

    def test_game_page_for_a_game_in_progress(self):
        out = self.run_node(self.game_scenario(
            {"body": {"available": True, "games": [live_row("in_progress")]}},
            {"body": {"games": [entry_with_lines()]}}))
        self.assertIsNone(out["rejected"], out["rejected"])
        self.assertIn("LIVE", out["strip"])
        self.assertIn("BOS 3 · NYY 2", out["strip"])
        self.assertIn("TOP 6TH", out["strip"])
        self.assertTrue(out["captured"].startswith("LAST PRE-GAME PRICES"))
        # one label on the moneyline panel, one on the run line / total block
        self.assertEqual(len(out["pregameLabels"]), 2)
        for label in out["pregameLabels"]:
            self.assertRegex(label, r"^LAST PRE-GAME PRICE · ")
        self.assertIn("RUN LINE", out["lineMarkets"])
        self.assertIn("-150", out["lineMarkets"])
        self.assertEqual(sorted(set(c.split("/")[1] for c in out["calls"])),
                         ["card", "game", "live", "odds"])

    def test_game_page_pregame_has_no_strip_and_no_label(self):
        out = self.run_node(self.game_scenario(
            {"body": {"available": True, "games": [live_row("pregame")]}},
            {"body": {"games": [entry_with_lines()]}}))
        self.assertIsNone(out["rejected"], out["rejected"])
        self.assertIsNone(out["strip"])
        self.assertTrue(out["captured"].startswith("PRICES CAPTURED"))
        self.assertEqual(len(out["pregameLabels"]), 0)
        self.assertIn("RUN LINE", out["lineMarkets"])

    def test_game_page_survives_every_optional_feed_failing(self):
        out = self.run_node(self.game_scenario(
            {"error": {"status": 502, "detail": "down"}},
            {"error": {"status": 502, "detail": "down"}}))
        self.assertIsNone(out["rejected"], out["rejected"])
        self.assertIsNone(out["strip"])
        self.assertIsNone(out["lineMarkets"])
        self.assertTrue(out["captured"].startswith("PRICES CAPTURED"))
        self.assertIn("PRICE · MONEYLINE", out["mlPanel"])

    def test_game_page_with_the_switch_off_shows_no_run_line_block(self):
        entry = entry_with_lines(spreads=False, totals=False)
        out = self.run_node(self.game_scenario(
            {"body": {"available": False, "games": []}}, {"body": {"games": [entry]}}))
        self.assertIsNone(out["rejected"], out["rejected"])
        self.assertIsNone(out["lineMarkets"])
        self.assertIsNone(out["strip"])


    # ---- the Today slate -------------------------------------------------

    def today_scenario(self, live_body):
        def row(game_id, away, home):
            return {"game_id": game_id, "away_team": away, "home_team": home,
                    "date": "2026-10-03", "first_pitch_utc": "2026-10-03T22:10:00Z",
                    "venue": "Park", "verdict": "no_play",
                    "board_summary": {"has_board": True, "books": 8, "observed_utc": OBSERVED}}

        def odds_entry(game_id, away, home):
            board = {"board_available": True, "best": {"away": {"price": 130, "books": ["fanduel"]},
                                                       "home": {"price": -150, "books": ["lowvig"]}},
                     "board": [{}] * 8, "staleness": {"observed_utc": OBSERVED}}
            return {"game_id": game_id, "away_team": away, "home_team": home,
                    "markets": {"h2h": board}}
        ids = [("BOS-NYY-2026-10-03-1", "BOS", "NYY"), ("SD-MIL-2026-10-03-1", "SD", "MIL")]
        slate = {"date": "2026-10-03", "checked_games": 2, "games": [row(*i) for i in ids]}
        return {"kind": "today", "responses": [
            ["/today", {"body": {"date": "2026-10-03", "games": [], "notes": []}}],
            ["/games/", {"body": slate}],
            ["/odds/", {"body": {"date": "2026-10-03", "games": [odds_entry(*i) for i in ids]}}],
            ["/changed/", {"body": {"items": []}}],
            ["/live/", live_body],
        ]}

    def test_today_slate_marks_the_started_game_and_leaves_the_other_alone(self):
        started = live_row("in_progress")
        pregame = live_row("pregame", game_id="SD-MIL-2026-10-03-1", away_team="SD",
                           home_team="MIL", away_score=None, home_score=None)
        out = self.run_node(self.today_scenario(
            {"body": {"available": True, "games": [started, pregame]}}))
        self.assertIsNone(out["rejected"], out["rejected"])
        by_id = {t["id"]: t for t in out["tiles"]}
        self.assertEqual(set(by_id), {"BOS-NYY-2026-10-03-1", "SD-MIL-2026-10-03-1"})
        bos, sd = by_id["BOS-NYY-2026-10-03-1"], by_id["SD-MIL-2026-10-03-1"]
        # the hero price panel features the (started) first game: labelled too
        self.assertEqual(len(out["heroPregame"]), 1)
        self.assertRegex(out["heroPregame"][0], r"^LAST PRE-GAME PRICE · ")
        self.assertEqual(bos["live"], "LIVE · BOS 3 · NYY 2 · TOP 6TH")
        self.assertRegex(bos["pregame"], r"^LAST PRE-GAME · ")
        self.assertIsNone(sd["live"])
        self.assertIsNone(sd["pregame"])
        self.assertIn("+130", sd["prices"])

    def test_today_slate_renders_when_live_state_is_down(self):
        out = self.run_node(self.today_scenario({"error": {"status": 502, "detail": "down"}}))
        self.assertIsNone(out["rejected"], out["rejected"])
        self.assertEqual(len(out["tiles"]), 2)
        for tile in out["tiles"]:
            self.assertIsNone(tile["live"])
            self.assertIsNone(tile["pregame"])
            self.assertIn("+130", tile["prices"])
        self.assertEqual(out["heroPregame"], [])

    def test_today_asks_for_live_state_once(self):
        out = self.run_node(self.today_scenario(
            {"body": {"available": True, "games": [live_row("in_progress")]}}))
        self.assertEqual([c for c in out["calls"] if c.startswith("/live/")], ["/live/2026-10-03"])


class WebLiveStateVocabulary(unittest.TestCase):
    """The new modules obey the same customer-language rules as the rest of web/js."""

    def test_no_banned_phrases(self):
        for name in ("livestate.js", "linemarkets.js"):
            text = (WEB_JS / name).read_text(encoding="utf-8")
            for pattern, label in HARD_BANNED:
                self.assertIsNone(re.search(pattern, text, re.IGNORECASE), f"{name}: {label}")
            for pattern, label in NEGATION_ONLY:
                for match in re.finditer(pattern, text, re.IGNORECASE):
                    window = text[max(0, match.start() - 80):match.start()]
                    self.assertTrue(NEGATORS.search(window), f"{name}: {label} outside a negation")


if __name__ == "__main__":
    unittest.main()
