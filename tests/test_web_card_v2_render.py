"""The signed-in Today page shows the nightly V2 card the way a person reads it
(web/js/card.js), 2026-10-03.

WHAT A TESTER SAW
-----------------
Local server, signed in, `#/today`, on the night of 2026-10-03. GET /card
served the frozen V2 row: 8 picks and 2 fills, every one a player prop. The
page said "TONIGHT'S CARD 0 picks" above "TODAY'S BETS 10 bets", then drew ten
cards that were all "Ty France", each with an empty bet line, and the
breakdown read "Needs 61%% to break even at -155".

THE CAUSE, IN ONE SENTENCE EACH
-------------------------------
  * A V2 `all_bets` entry is the FULL candidate (player, market, side, line,
    price, entry_class ...) with `bet: null`; the resolver written for V1's
    `{kind, index, bet}` references matched `list.find(p => p.bet === item.bet)`
    and `null === null` returned the FIRST prop every time.
  * The V2 ledger has never stored a `bet` sentence (or `why`, or `book`), so
    nothing on the entry said what the bet was.
  * The headline counted `payload.picks` (game picks only; empty on a card made
    of props) instead of the card's own picks.
  * `pct0()` already returns "61%", and the template added a second "%".

These tests RUN the real web/js/card.js under node (fake DOM, stubbed apiGet,
the pattern of tests/test_web_nfl_tennis_truth.py) and read back what a reader
sees. They are fed the REAL ledger rows, copied verbatim into
tests/fixtures/ (never the live ledger):

  * card_v2_row_2026-10-03.json  8 picks + 2 fills, all props, all with no
                                 lineup posted (the night above)
  * card_v2_row_2026-09-25.json  a mixed night: 2 moneyline picks, 3 prop
                                 picks, 5 fills of both kinds

plus a V1-shaped payload (`{kind, index, bet}` references) that must render
exactly as it always has.

The node tests skip when node is not installed (the GitHub runner has it).
The route test skips when FastAPI is not installed.
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
from unittest import mock

try:
    import fastapi  # noqa: F401 -- CI runs the suite without it; route tests skip
    HAS_FASTAPI = True
except ImportError:  # pragma: no cover
    HAS_FASTAPI = False

ROOT = Path(__file__).resolve().parent.parent
WEB_JS = ROOT / "web" / "js"
FIXTURES = ROOT / "tests" / "fixtures"
NODE = shutil.which("node")

# Replaces web/js/api.js inside the scratch copy: every export the real module
# has, so any import in the module graph resolves; the fetchers hand the
# request to the scenario's stubbed responses.
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

# A fake DOM with what card.js, dom.js, layout.js need: children, attributes,
# textContent, classList, insertBefore, nextSibling, and querySelector for
# `.class`, `[attr]`, `[attr="value"]` and `tag` selectors (mergedBetCard looks
# up `.card2__top` and `.card2__bet`). appendChild throws on a non-node, as a
# browser does. Date.now is frozen so no assertion depends on the clock; the
# text of a collapsed breakdown is part of textContent, as in a browser.
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
    const self = this;
    const names = () => (self.attributes.class || "").split(/\s+/).filter(Boolean);
    this.classList = {
      add(...n) { const s = new Set(names()); n.forEach((x) => s.add(x)); self.attributes.class = [...s].join(" "); },
      remove(...n) { const s = new Set(names()); n.forEach((x) => s.delete(x)); self.attributes.class = [...s].join(" "); },
      contains(n) { return names().includes(n); },
    };
  }
  get firstChild() { return this.childNodes[0] || null; }
  get nextSibling() {
    const p = this.parentNode;
    if (!p) return null;
    return p.childNodes[p.childNodes.indexOf(this) + 1] || null;
  }
  set hidden(v) { if (v) this.attributes.hidden = ""; else delete this.attributes.hidden; }
  get hidden() { return "hidden" in this.attributes; }
  appendChild(child) {
    if (!(child instanceof FakeNode)) throw new TypeError("parameter 1 is not of type 'Node'.");
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
  setAttribute(k, v) { this.attributes[k] = String(v); }
  getAttribute(k) { return k in this.attributes ? this.attributes[k] : null; }
  removeAttribute(k) { delete this.attributes[k]; }
  addEventListener() {}
  _descendants(out) {
    for (const c of this.childNodes) { if (c.nodeType === 1) { out.push(c); c._descendants(out); } }
    return out;
  }
  matches(sel) {
    if (this.nodeType !== 1) return false;
    if (sel.startsWith(".")) return (this.attributes.class || "").split(/\s+/).includes(sel.slice(1));
    const m = sel.match(/^\[([\w-]+)(?:="([^"]*)")?\]$/);
    if (m) return m[1] in this.attributes && (m[2] === undefined || this.attributes[m[1]] === m[2]);
    return this.tagName.toLowerCase() === sel.toLowerCase();
  }
  querySelectorAll(sel) { return this._descendants([]).filter((n) => n.matches(sel)); }
  querySelector(sel) { return this.querySelectorAll(sel)[0] || null; }
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
  localStorage: { getItem: (k) => (store.has(k) ? store.get(k) : null),
                  setItem: (k, v) => store.set(k, String(v)), removeItem: (k) => store.delete(k) },
  scrollTo() {},
  matchMedia: () => ({ matches: false }),
  addEventListener() {},
  dispatchEvent() { return true; },
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

const CARD_HOOKS = ["card-pick", "card-prop-pick", "card-total-pick"];
const BET_HOOKS = ["card-bet", "card-prop-bet", "card-total-bet"];
const text = (node) => (node ? node.textContent : null);
const hook = (root, name) => root.querySelector(`[data-hook="${name}"]`);

const { renderCard } = await import(new URL("./js/card.js", import.meta.url));
const host = new FakeNode("main");
let rejected = null;
let result = null;
try {
  result = await renderCard(host, ...scenario.args);
} catch (err) {
  rejected = `${err && err.name}: ${err && err.message}`;
}

const all = host._descendants([]);
const cards = all.filter((n) => CARD_HOOKS.includes(n.attributes["data-hook"])).map((card) => {
  const bet = BET_HOOKS.map((h) => hook(card, h)).find(Boolean) || null;
  const fillTag = hook(card, "card-fill-tag");
  const fillNote = hook(card, "card-fill-note");
  const toggle = card.querySelector("button");
  const panel = card.querySelector(".disclosure__body");
  return {
    hook: card.attributes["data-hook"],
    rank: card.attributes["data-rank"],
    market: card.attributes["data-market"],
    entryClass: card.attributes["data-entry-class"] ?? null,
    top: text(card.querySelector(".card2__rank")),
    kind: text(hook(card, "card-kind-tag")),
    bet: bet ? bet.textContent : null,
    fillTag: fillTag ? fillTag.textContent : null,
    fillNote: fillNote ? fillNote.textContent : null,
    lineupWarning: text(hook(card, "card-lineup-tag")),
    controls: toggle ? toggle.attributes["aria-controls"] : null,
    panelId: panel ? panel.attributes.id : null,
    breakdown: panel ? panel.textContent : "",
    text: card.textContent,
  };
});
const heads = all.filter((n) => (n.attributes.class || "").split(/\s+/).includes("sechead")).map((h) => ({
  label: text(h.querySelector(".sechead__label")),
  meta: text(h.querySelector(".sechead__meta")),
}));
const hrefs = all.filter((n) => n.tagName === "A" && n.attributes.href).map((n) => n.attributes.href);

process.stdout.write("@@" + JSON.stringify({
  rejected, rendered: result ? result.rendered : null,
  text: host.textContent, cards, heads, hrefs, calls,
  hooks: all.map((n) => n.attributes["data-hook"]).filter(Boolean),
}));
"""


def fixture_row(date: str) -> dict:
    return json.loads((FIXTURES / f"card_v2_row_{date}.json").read_text(encoding="utf-8"))


def served_payload(row: dict) -> dict:
    """What `card_v2.frozen_card_v2` hands the route for a published row:
    the row itself, nothing decorated, plus the three fields it stamps."""
    payload = dict(row)
    payload["date"] = row["date"]
    payload["frozen"] = True
    payload["frozen_at"] = row.get("published_utc")
    payload["generated_at"] = "2026-10-03T16:00:00+00:00"
    return payload


class _CardHarness(unittest.TestCase):
    """Copies web/js into a scratch dir once per class, swaps api.js for the
    stub, and renders one card per call in a fresh node process."""

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

    def render(self, payload: dict, *, date: str = None, sport: str = "mlb", record: dict = None) -> dict:
        suffix = "" if sport == "mlb" else f"?sport={sport}"
        date = date or payload.get("date")
        scenario = {
            "args": [{"date": date, "sport": sport}],
            "responses": [
                [f"/card/record{suffix}", {"body": record or {"days": 0, "n_staked": 0}}],
                [f"/card/{date}{suffix}", {"body": payload}],
            ],
        }
        path = self._root / "scenario.json"
        path.write_text(json.dumps(scenario), encoding="utf-8")
        env = dict(os.environ, TZ="America/Los_Angeles")
        proc = subprocess.run([NODE, str(self._root / "run.mjs"), str(path)], capture_output=True,
                              text=True, timeout=60, encoding="utf-8", env=env)
        if proc.returncode != 0:
            self.fail(f"node harness failed:\n{proc.stderr[-3000:]}")
        line = [ln for ln in proc.stdout.splitlines() if ln.startswith("@@")][-1]
        out = json.loads(line[2:])
        self.assertIsNone(out["rejected"], out["rejected"])
        return out

    @staticmethod
    def head(out, label):
        return next(h for h in out["heads"] if h["label"] == label)

    @staticmethod
    def who(card):
        """The first thing after the position on a card's top line: a player's
        name on a prop, "BAL at NYY" on a game."""
        return card["top"].split(" · ")[1]


def _entry_players(entries):
    return [e["player"] or e["team_name"] for e in entries]


# ---------------------------------------------------------------------------
# 2026-10-03: ten props, eight picks and two fills, the card the tester saw.
# ---------------------------------------------------------------------------

class TheTenPropNightRendersTenDistinctCards(_CardHarness):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.row = fixture_row("2026-10-03")
        cls.entries = cls.row["all_bets"]

    def setUp(self):
        self.out = self.render(served_payload(self.row))
        self.cards = self.out["cards"]

    def test_the_fixture_is_the_shape_the_defect_needs(self):
        """Guards the guard: if the fixture stops being a V2 row with no
        server-written sentence, the tests below stop proving anything."""
        self.assertEqual(self.row["rule"], "DAILY_CARD_BEST_BETS_V2")
        self.assertEqual((len(self.row["picks"]), len(self.row["prop_picks"]),
                          len(self.entries), self.row["n_picks"], self.row["n_fills"]),
                         (0, 8, 10, 8, 2))
        self.assertTrue(all(e["bet"] is None and e["why"] is None and e["book"] is None
                            for e in self.entries))
        self.assertTrue(all("index" not in e for e in self.entries))

    def test_ten_cards_ten_distinct_players_in_the_payloads_order(self):
        self.assertEqual(len(self.cards), 10)
        shown = [self.who(c) for c in self.cards]
        self.assertEqual(shown, _entry_players(self.entries))
        self.assertEqual(len(set(shown)), 10)

    def test_each_card_carries_its_own_market(self):
        self.assertEqual([c["market"] for c in self.cards], [e["market"] for e in self.entries])
        self.assertEqual({c["market"] for c in self.cards}, {"batter_hits", "batter_total_bases"})

    def test_each_card_has_its_own_bet_sentence(self):
        for card, entry in zip(self.cards, self.entries):
            with self.subTest(player=entry["player"]):
                sentence = card["bet"]
                self.assertTrue(sentence and sentence.strip(), "empty bet sentence")
                noun = "hits" if entry["market"] == "batter_hits" else "total bases"
                price = f"{entry['price']:+d}" if entry["price"] > 0 else str(entry["price"])
                self.assertIn(entry["player"], sentence)
                self.assertIn(entry["side"].lower(), sentence)
                self.assertIn(str(entry["line"]), sentence)
                self.assertIn(noun, sentence)
                self.assertTrue(sentence.endswith(f" at {price}"), sentence)
                self.assertNotIn("batter_", sentence)
        self.assertEqual(len({c["bet"] for c in self.cards}), 10)

    def test_the_first_two_sentences_a_tester_reads(self):
        # entry 0 is a fill (Rocchio), entry 1 the number-one pick (Ty France)
        self.assertEqual(self.cards[0]["bet"], "Brayan Rocchio over 0.5 total bases at -135")
        self.assertEqual(self.cards[1]["bet"], "Take Ty France over 0.5 hits at -155")

    def test_a_pick_says_take_and_a_fill_never_does(self):
        for card, entry in zip(self.cards, self.entries):
            with self.subTest(player=entry["player"]):
                self.assertEqual(card["bet"].startswith("Take "), entry["entry_class"] == "pick")

    def test_fills_are_labelled_as_fills_and_picks_are_not(self):
        fills = [c for c in self.cards if c["fillTag"]]
        self.assertEqual([self.who(c) for c in fills], ["Brayan Rocchio", "Will Smith"])
        for card, entry in zip(self.cards, self.entries):
            with self.subTest(player=entry["player"]):
                self.assertEqual(card["entryClass"], entry["entry_class"])
                if entry["entry_class"] == "fill":
                    self.assertEqual(card["fillTag"], "Fill, not a pick")
                    self.assertIn("not a pick", card["fillNote"])
                else:
                    self.assertIsNone(card["fillTag"])
                    self.assertIsNone(card["fillNote"])

    def test_the_headline_agrees_with_the_cards_under_it(self):
        meta = self.head(self.out, "TONIGHT'S CARD")["meta"]
        rendered_picks = sum(1 for c in self.cards if c["entryClass"] == "pick")
        rendered_fills = sum(1 for c in self.cards if c["entryClass"] == "fill")
        # the numbers are the payload's own
        self.assertEqual((rendered_picks, rendered_fills), (self.row["n_picks"], self.row["n_fills"]))
        self.assertEqual(meta, "8 picks · 2 fills")
        self.assertNotIn("0 picks", meta)
        self.assertEqual(self.head(self.out, "TODAY'S BETS")["meta"], "10 bets")

    def test_no_double_percent_anywhere_on_the_page(self):
        self.assertNotIn("%%", self.out["text"])
        france = self.cards[1]
        self.assertIn("Market says 58%", france["breakdown"])
        self.assertIn("Needs 61% to break even at -155", france["breakdown"])
        # every card that prints a break-even line prints it with one sign
        for card, entry in zip(self.cards, self.entries):
            needs = round(entry["breakeven"] * 100)
            self.assertIn(f"Needs {needs}% to break even at ", card["breakdown"])
            self.assertNotIn("%%", card["breakdown"])

    def test_every_breakdown_panel_has_an_id_of_its_own(self):
        """Several props sit on one game, and `game_pk` alone named every one
        of them the same: aria-controls then points at the wrong panel."""
        ids = [c["panelId"] for c in self.cards]
        self.assertEqual(len(set(ids)), 10, ids)
        self.assertEqual(ids, [c["controls"] for c in self.cards])

    def test_the_lineup_warning_and_kind_tag_are_still_on_every_prop(self):
        # LINEUP NOT POSTED is registered copy for every prop without a lineup,
        # pick or fill; this night none had one.
        for card in self.cards:
            self.assertEqual(card["kind"], "PLAYER PROP")
            self.assertIn("LINEUP NOT POSTED", card["lineupWarning"])

    def test_owner_rulings_hold_on_this_page(self):
        # no pick at -200 or worse is shown as a pick; Bet Check is never linked
        for card, entry in zip(self.cards, self.entries):
            if entry["entry_class"] == "pick":
                self.assertGreater(entry["price"], -200)
        self.assertFalse([h for h in self.out["hrefs"] if "betcheck" in h.lower()])
        self.assertNotIn("bet check", self.out["text"].lower())
        # no profit or edge claim in anything this page printed for the cards
        for card in self.cards:
            self.assertIsNone(re.search(r"\b(edge|profit|guarantee[sd]?)\b", card["text"], re.I))

    def test_the_new_copy_has_no_em_dash(self):
        for card in self.cards:
            for field in ("bet", "fillTag", "fillNote"):
                self.assertNotIn("—", card[field] or "")


# ---------------------------------------------------------------------------
# 2026-09-25: a mixed night. Two moneyline picks on one team, three prop picks,
# five fills of both kinds.
# ---------------------------------------------------------------------------

class TheMixedGameAndPropNightRendersEachEntryOnce(_CardHarness):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.row = fixture_row("2026-09-25")
        cls.entries = cls.row["all_bets"]

    def setUp(self):
        self.out = self.render(served_payload(self.row))
        self.cards = self.out["cards"]

    def test_the_fixture_is_a_mixed_night(self):
        self.assertEqual({e["kind"] for e in self.entries}, {"game", "prop"})
        self.assertEqual((len(self.row["picks"]), len(self.row["prop_picks"]), len(self.entries)),
                         (2, 3, 10))
        self.assertTrue(all(e["bet"] is None for e in self.entries))
        self.assertEqual({e["entry_class"] for e in self.entries}, {"pick", "fill"})

    def test_one_card_per_entry_in_the_payloads_order(self):
        self.assertEqual(len(self.cards), 10)
        self.assertEqual([c["market"] for c in self.cards], [e["market"] for e in self.entries])
        self.assertEqual([c["hook"] for c in self.cards],
                         ["card-pick" if e["kind"] == "game" else "card-prop-pick" for e in self.entries])

    def test_the_two_moneyline_picks_on_one_team_are_two_cards_with_two_prices(self):
        """The doubleheader: two Yankees picks, -118 and -130. The old resolver
        drew the first one twice, and drew the Blue Jays fill as it too."""
        games = [c for c in self.cards if c["hook"] == "card-pick"]
        self.assertEqual([c["bet"] for c in games],
                         ["Take Yankees to win at -118", "Take Yankees to win at -130",
                          "Blue Jays to win at -130"])
        self.assertEqual([c["fillTag"] for c in games], [None, None, "Fill, not a pick"])
        self.assertEqual([c["kind"] for c in games], ["MONEYLINE"] * 3)

    def test_every_prop_sentence_is_its_own(self):
        props = [(c, e) for c, e in zip(self.cards, self.entries) if e["kind"] == "prop"]
        self.assertEqual(len(props), 7)
        for card, entry in props:
            with self.subTest(player=entry["player"]):
                self.assertIn(entry["player"], card["bet"])
                self.assertIn(entry["side"].lower(), card["bet"])
        self.assertEqual(len({c["bet"] for c in self.cards}), 10)

    def test_fills_are_labelled_and_the_headline_counts_the_picks_and_fills(self):
        n_fill = sum(1 for e in self.entries if e["entry_class"] == "fill")
        self.assertEqual(sum(1 for c in self.cards if c["fillTag"]), n_fill)
        self.assertEqual(self.head(self.out, "TONIGHT'S CARD")["meta"],
                         f"{self.row['n_picks']} picks · {self.row['n_fills']} fills")
        self.assertEqual(self.head(self.out, "TONIGHT'S CARD")["meta"], "5 picks · 5 fills")
        self.assertNotIn("%%", self.out["text"])


class AFillsOnlyNightStillShowsItsFillsLabelled(_CardHarness):
    """2026-09-26, 09-27, 09-29 and 09-30 had no pick at all. With a null
    `bet` the old resolver found no pick to match, dropped every entry, and the
    page walked back to yesterday or printed NO CARD TODAY."""

    def test_every_fill_renders_and_none_reads_as_a_pick(self):
        row = fixture_row("2026-09-25")
        fills = [e for e in row["all_bets"] if e["entry_class"] == "fill"]
        payload = served_payload(dict(row, date="2026-09-26", picks=[], prop_picks=[],
                                      all_bets=fills, n_picks=0, n_fills=len(fills)))
        out = self.render(payload)
        self.assertEqual(len(out["cards"]), len(fills))
        self.assertTrue(all(c["fillTag"] == "Fill, not a pick" for c in out["cards"]))
        self.assertFalse(any(c["bet"].startswith("Take ") for c in out["cards"]))
        self.assertEqual(self.head(out, "TONIGHT'S CARD")["meta"], f"0 picks · {len(fills)} fills")
        self.assertEqual(self.head(out, "TONIGHT'S CARD")["label"], "TONIGHT'S CARD")
        self.assertNotIn("NO CARD TODAY", out["text"])


# ---------------------------------------------------------------------------
# V1-shaped payloads render exactly as they always have.
# ---------------------------------------------------------------------------

def _v1_payload():
    game = {"rank": 1, "game_pk": 777, "away_team": "BOS", "home_team": "NYY",
            "first_pitch_utc": "2099-09-27T23:05:00Z", "bet": "Take Yankees at -140",
            "price": -140, "book": "draftkings", "books": 8, "label": "LEAN",
            "market_probability": 0.57, "model_probability": 0.6,
            "why": ["The market makes the Yankees the favourite."], "locked": True}
    props = [
        {"rank": 1, "game_pk": 777, "player": "Rafael Devers", "team": "BOS", "market": "batter_hits",
         "first_pitch_utc": "2099-09-27T23:05:00Z", "bet": "Take Rafael Devers over 0.5 hits at -150",
         "price": -150, "book": "fanduel", "books": 6, "label": "LEAN", "lineup_posted": True,
         "market_probability": 0.61, "probability": 0.66, "breakeven": 0.6,
         "why": ["He has a hit in most of his recent games."], "locked": True},
        {"rank": 2, "game_pk": 777, "player": "Jarren Duran", "team": "BOS", "market": "batter_total_bases",
         "first_pitch_utc": "2099-09-27T23:05:00Z", "bet": "Take Jarren Duran over 0.5 total bases at -120",
         "price": -120, "book": "fanduel", "books": 6, "label": "LEAN", "lineup_posted": True,
         "market_probability": 0.56, "probability": 0.6, "breakeven": 0.5455,
         "why": ["He reaches base often."], "locked": True},
    ]
    total = {"rank": 1, "game_pk": 777, "away_team": "BOS", "home_team": "NYY", "market": "total",
             "first_pitch_utc": "2099-09-27T23:05:00Z", "bet": "Take Under 8.5 at -110", "price": -110,
             "book": "betmgm", "books": 7, "label": "SLIGHT", "market_probability": 0.52, "locked": True,
             "why": ["Both starters keep runs down."]}
    # daily_card.merge_all_bets: references, in the merged order; `index` is the
    # position in the pick's own array. Props first here to prove the order is
    # the server's, not the arrays'.
    all_bets = [
        {"kind": "prop", "index": 1, "probability": 0.7, "label": "LEAN", "bet": props[1]["bet"],
         "first_pitch_utc": props[1]["first_pitch_utc"], "lineup_posted": True, "position": 1},
        {"kind": "game", "index": 0, "probability": 0.6, "label": "LEAN", "bet": game["bet"],
         "first_pitch_utc": game["first_pitch_utc"], "lineup_posted": None, "position": 2},
        {"kind": "total", "index": 0, "probability": 0.55, "label": "SLIGHT", "bet": total["bet"],
         "first_pitch_utc": total["first_pitch_utc"], "lineup_posted": None, "position": 3},
        {"kind": "prop", "index": 0, "probability": 0.5, "label": "LEAN", "bet": props[0]["bet"],
         "first_pitch_utc": props[0]["first_pitch_utc"], "lineup_posted": True, "position": 4},
    ]
    return {"date": "2099-09-27", "rule": "DAILY_CARD_V1", "frozen": False, "calibrated": True,
            "games_on_slate": 12, "filled": 0, "picks": [game], "total_picks": [total],
            "prop_picks": props, "all_bets": all_bets,
            "disclaimer": "This is analysis, not advice.", "basis": "The fair price comes from the market."}


class AV1ShapedPayloadRendersAsItAlwaysDid(_CardHarness):
    def setUp(self):
        self.out = self.render(_v1_payload())
        self.cards = self.out["cards"]

    def test_references_resolve_to_their_own_picks_in_the_servers_order(self):
        self.assertEqual([c["bet"] for c in self.cards],
                         ["Take Jarren Duran over 0.5 total bases at -120",
                          "Take Yankees at -140",
                          "Take Under 8.5 at -110",
                          "Take Rafael Devers over 0.5 hits at -150"])
        self.assertEqual([c["hook"] for c in self.cards],
                         ["card-prop-pick", "card-pick", "card-total-pick", "card-prop-pick"])
        self.assertEqual([c["kind"] for c in self.cards],
                         ["PLAYER PROP", "MONEYLINE", "TOTAL", "PLAYER PROP"])

    def test_the_headline_is_still_the_game_picks_of_the_slate(self):
        self.assertEqual(self.head(self.out, "TONIGHT'S CARD")["meta"], "1 of 12 games")
        self.assertEqual(self.head(self.out, "TODAY'S BETS")["meta"], "4 bets")

    def test_no_fill_label_appears_on_a_v1_card(self):
        self.assertNotIn("card-fill-tag", self.out["hooks"])
        self.assertNotIn("card-fill-note", self.out["hooks"])
        self.assertNotIn("Fill, not a pick", self.out["text"])

    def test_the_server_written_book_line_is_still_printed(self):
        self.assertIn("-120 at FanDuel", self.cards[0]["text"])
        self.assertIn("-140 at DraftKings", self.cards[1]["text"])

    def test_the_break_even_line_has_one_percent_sign_on_both_paths(self):
        # a prop carrying `breakeven` (pct0) and a game pick without one (price)
        self.assertIn("Needs 55% to break even at -120", self.cards[0]["breakdown"])
        self.assertIn("Needs 58% to break even at -140", self.cards[1]["breakdown"])
        self.assertIn("Needs 60% to break even at -150", self.cards[3]["breakdown"])
        self.assertNotIn("%%", self.out["text"])

    def test_a_reference_whose_sentence_is_missing_is_never_matched_to_another_pick(self):
        """null === null is not an identity. A reference with no sentence and no
        usable index is dropped; it must not resolve to the first pick."""
        payload = _v1_payload()
        payload["all_bets"].append({"kind": "prop", "bet": None, "position": 5})
        payload["all_bets"].append({"kind": "game", "index": 7, "bet": None, "position": 6})
        out = self.render(payload)
        self.assertEqual(len(out["cards"]), 4)
        self.assertEqual(self.head(out, "TODAY'S BETS")["meta"], "4 bets")


class TheOtherSportsPagesAreNotTheSameDefect(_CardHarness):
    """NFL and UFC cards carry `picks` only (no `all_bets`), so the resolver is
    never reached, and their picks carry no `breakeven` field, so the break-even
    line comes from the price and printed one percent sign before this fix."""

    def _nfl_pick(self, **extra):
        pick = {"sport": "nfl", "rank": 1, "market": "spread", "line": 6.5, "side": "away",
                "game_id": "2026_03_NYJ_DET", "away_team": "New York Jets",
                "home_team": "Detroit Lions", "first_pitch_utc": "2099-09-27T17:00:00Z",
                "bet": "Take New York Jets +6.5 at +105", "price": 105, "book": "fanduel",
                "books": 6, "label": "LEAN", "market_probability": 0.51,
                "why": ["At +105 the price is better than the rest of the market."]}
        pick.update(extra)
        return pick

    def test_an_nfl_card_with_two_picks_renders_two_different_picks(self):
        picks = [self._nfl_pick(),
                 self._nfl_pick(rank=2, game_id="2026_03_KC_BUF", away_team="Kansas City Chiefs",
                                home_team="Buffalo Bills", line=-2.5, price=-110,
                                bet="Take Kansas City Chiefs -2.5 at -110")]
        payload = {"date": "2099-09-27", "sport": "nfl", "rule": "NFL_CARD_V2", "frozen": False,
                   "has_model": False, "picks": picks, "disclaimer": "d", "basis": "b"}
        out = self.render(payload, sport="nfl")
        self.assertEqual([c["bet"] for c in out["cards"]],
                         ["Take New York Jets +6.5 at +105", "Take Kansas City Chiefs -2.5 at -110"])
        self.assertIn("Needs 49% to break even at +105", out["cards"][0]["breakdown"])
        self.assertIn("Needs 52% to break even at -110", out["cards"][1]["breakdown"])
        self.assertNotIn("%%", out["text"])

    def test_a_ufc_card_renders_its_picks_without_a_double_percent(self):
        picks = [{"sport": "mma", "rank": 1, "market": "moneyline", "side": "home",
                  "away_team": "A. Fighter", "home_team": "B. Fighter",
                  "first_pitch_utc": "2099-09-27T22:00:00Z",
                  "bet": "B. Fighter to win at -150 (consensus)", "price": -150, "books": 5,
                  "label": "LEAN", "market_probability": 0.6, "why": []}]
        payload = {"date": "2099-09-27", "sport": "mma", "rule": "UFC_CARD_V1", "frozen": False,
                   "picks": picks, "disclaimer": "d", "basis": "b"}
        out = self.render(payload, sport="mma")
        self.assertEqual(len(out["cards"]), 1)
        self.assertIn("Needs 60% to break even at -150", out["cards"][0]["breakdown"])
        self.assertNotIn("%%", out["text"])


# ---------------------------------------------------------------------------
# The page is fed what the route serves, not a hand-built look-alike.
# ---------------------------------------------------------------------------

@unittest.skipUnless(HAS_FASTAPI, "fastapi not installed")
class TheRouteServesTheRowUndecorated(unittest.TestCase):
    """The fix is display-only: GET /card/{date} (rule v2) returns the frozen
    row's stored fields, `row_hash` and `prev_hash` exactly as published. The
    only keys that differ from the row are the three `frozen_card_v2` stamps and
    `generated_at`."""

    def test_the_served_payload_is_the_frozen_row_plus_its_stamps(self):
        from api import card as card_api
        from src.appstate import card_ledger

        for date in ("2026-10-03", "2026-09-25"):
            row = fixture_row(date)
            with self.subTest(date=date), tempfile.TemporaryDirectory() as tmp:
                store = Path(tmp) / "cards_v2.jsonl"
                store.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")
                with mock.patch.object(card_ledger, "CARD_STORE_V2", str(store)):
                    served = card_api.get_card_for_date(date, None, sport="mlb", rule="v2")
                self.assertEqual({k: v for k, v in served.items()
                                  if k not in ("frozen", "frozen_at", "generated_at")}, row)
                self.assertEqual(served["row_hash"], row["row_hash"])
                self.assertEqual(served["prev_hash"], row["prev_hash"])
                expected = served_payload(row)
                self.assertEqual({k: v for k, v in served.items() if k != "generated_at"},
                                 {k: v for k, v in expected.items() if k != "generated_at"})


if __name__ == "__main__":
    unittest.main()
