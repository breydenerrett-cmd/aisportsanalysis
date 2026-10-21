"""The landing page's record headline, run under node against the real markup.

Owner brief 2026-10-17. The page used to show "CURRENT METHOD 16-17, -5.05
units, 6 nights" with the postseason "27-33, -9.22u" as a one-line aside, and
right beneath it the retired method's "151-79, +7.98 units" at the same size and
with no caveat: a stranger reads the 6-night counted figure as a bad week, the
postseason as noise and the old method as the one that worked.

What docs/PREREG_CARD_V2.md allows (11.1, R3-R5): a pick is counted only if its
game is a regular-season game; postseason picks are "published, graded and shown
on the record, but not counted"; V1 is a separate, closed shadow record "kept as
it was, and not added to rule v2's numbers"; no number adds two populations. So
the page shows the counted regular-season figure and the postseason figure as the
same component at the same size, never a sum, with one sentence on why only one
counts, and keeps the retired method off the first screen (on the MLB tile it
carries the registration's own caveat).

No JS test runner exists in this repo: the real landing.js runs under node
against a small fake DOM filled with the real data-hooks of web/landing.html.
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
    this.childNodes = []; this.parentNode = null; this.listeners = {}; this.style = {};
    const self = this;
    this.classList = {
      add(c) { const set = new Set((self.attrs.class || "").split(/\s+/).filter(Boolean)); set.add(c); self.attrs.class = [...set].join(" "); },
      contains(c) { return (self.attrs.class || "").split(/\s+/).includes(c); },
    };
  }
  get children() { return this.childNodes.filter((c) => c.nodeType === 1); }
  get firstChild() { return this.childNodes[0] || null; }
  appendChild(c) { if (c.parentNode) c.parentNode.removeChild(c); c.parentNode = this; this.childNodes.push(c); return c; }
  removeChild(c) { const i = this.childNodes.indexOf(c); if (i >= 0) this.childNodes.splice(i, 1); c.parentNode = null; return c; }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; }
  set hidden(v) { if (v) this.attrs.hidden = ""; else delete this.attrs.hidden; }
  get hidden() { return "hidden" in this.attrs; }
  set textContent(v) { const t = new TextNode(v); t.parentNode = this; this.childNodes = [t]; }
  get textContent() { return this.childNodes.map((c) => c.textContent).join(""); }
  addEventListener() {}
  _all(out) { for (const c of this.children) { out.push(c); c._all(out); } return out; }
  querySelectorAll(sel) {
    const m = sel.match(/^\[([\w-]+)(?:(\^?=)'([^']*)')?\]$/);
    if (!m) throw new Error("unsupported selector " + sel);
    const [, name, op, val] = m;
    return this._all([]).filter((n) => {
      if (!(name in n.attrs)) return false;
      if (!op) return true;
      return op === "=" ? n.attrs[name] === val : n.attrs[name].startsWith(val);
    });
  }
  querySelector(sel) { return this.querySelectorAll(sel)[0] || null; }
}

const body = new Elem("body");
globalThis.document = {
  createElement: (t) => new Elem(t), createTextNode: (t) => new TextNode(t),
  body, referrer: "", addEventListener() {},
  querySelector: (s) => body.querySelector(s), querySelectorAll: (s) => body.querySelectorAll(s),
};
const store = new Map();
globalThis.window = {
  localStorage: { getItem: (k) => (store.has(k) ? store.get(k) : null), setItem: (k, v) => store.set(k, String(v)), removeItem: (k) => store.delete(k) },
  location: { search: "", host: "linehound.test", pathname: "/", hash: "" },
  history: { replaceState() {} }, addEventListener() {}, dispatchEvent() { return true; }, crypto: globalThis.crypto,
};
const scenario = JSON.parse(process.env.SCENARIO);
globalThis.fetch = async (url) => {
  url = String(url);
  const json = (status, b) => ({ ok: status < 400, status, text: async () => JSON.stringify(b) });
  if (url.startsWith("/meta")) return json(200, scenario.meta);
  return json(200, {});
};

function build(parent, specs) {
  const root = new Elem("div"); parent.appendChild(root);
  for (const spec of specs) {
    const node = new Elem(spec.tag || "div");
    node.setAttribute("data-hook", spec.hook);
    if (spec.hidden) node.hidden = true;
    root.appendChild(node);
  }
  return root;
}
const hero = build(body, scenario.hero); hero.setAttribute("data-hook", "hero-proof");
const host = new Elem("div"); host.setAttribute("data-hook", "sport-record-tiles"); body.appendChild(host);
const tile = build(host, scenario.tile); tile.setAttribute("data-hook", "sport-tile-mlb");

const { fillProofPanel, fillSportTiles, provenRecordSentence } = await import("./landing.js");
await fillProofPanel();
await fillSportTiles();

const snap = (root) => {
  const out = {};
  for (const n of root._all([])) {
    const hook = n.attrs["data-hook"];
    if (hook) out[hook] = { text: n.textContent, hidden: n.hidden, cls: n.attrs.class || "" };
  }
  return out;
};
const sports = scenario.meta.effective_record.sports;
console.log("@@" + JSON.stringify({
  hero: snap(hero), tile: snap(tile),
  proven: provenRecordSentence(sports.mlb.current),
}));
"""

CURRENT = {
    "available": True, "grading_state": "graded", "label": "Rule v2", "reason": None,
    "wins": 16, "losses": 17, "pushes": 0, "profit_units": -5.05, "days": 6, "n_staked": 33,
    "date_span": {"first": "2026-09-22", "last": "2026-09-27"},
    "postseason": {"wins": 27, "losses": 33, "pushes": 0, "profit_units": -9.22, "days": 16,
                   "n_staked": 60, "label": "Postseason (graded, not counted)"},
}
PREVIOUS = {
    "available": True, "grading_state": "graded", "label": "Rule v1", "reason": None,
    "wins": 151, "losses": 79, "pushes": 0, "profit_units": 7.98, "days": 41, "n_staked": 230,
    "date_span": {"first": "2026-09-10", "last": "2026-09-14"}, "postseason": None,
}


def _meta(current=CURRENT, previous=PREVIOUS):
    return {"effective_record": {"sports": {"mlb": {"current": current, "previous": previous}}}}


def _hooks(markup: str):
    """(hook, tag, hidden) for every data-hook in a markup slice."""
    found = []
    for tag, attrs in re.findall(r"<(\w+)([^>]*data-hook=\"[^\"]+\"[^>]*)>", markup):
        hook = re.search(r'data-hook="([^"]+)"', attrs).group(1)
        found.append({"tag": tag, "hook": hook, "hidden": bool(re.search(r"\bhidden\b", attrs))})
    return found


def _slice(html: str, start_marker: str, end_marker: str) -> str:
    start = html.index(start_marker)
    return html[start:html.index(end_marker, start)]


@unittest.skipUnless(shutil.which("node"), "node not installed")
class TheRecordHeadlineCannotBeMisread(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        for path in JS.glob("*.js"):
            shutil.copy(path, cls._tmp.name)
        Path(cls._tmp.name, "package.json").write_text('{"type": "module"}', encoding="utf-8")
        Path(cls._tmp.name, "harness.mjs").write_text(HARNESS, encoding="utf-8")
        html = (WEB / "desk.html").read_text(encoding="utf-8")
        cls.hero = _hooks(_slice(html, 'data-hook="hero-proof"', "</aside>"))
        cls.tile = _hooks(_slice(html, 'data-hook="sport-tile-mlb"', 'data-hook="sport-tile-mlb-link"'))

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def run_scenario(self, meta):
        env = dict(os.environ, SCENARIO=json.dumps(
            {"meta": meta, "hero": self.hero, "tile": self.tile}))
        proc = subprocess.run(["node", "harness.mjs"], cwd=self._tmp.name, env=env,
                              capture_output=True, text=True, encoding="utf-8", timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr[-2000:])
        line = [ln for ln in proc.stdout.splitlines() if ln.startswith("@@")][-1]
        return json.loads(line[2:])

    def test_counted_and_postseason_figures_sit_together_at_equal_weight(self):
        out = self.run_scenario(_meta())["hero"]
        self.assertEqual(out["hero-current-label"]["text"],
                         "Current method · regular season, counted")
        self.assertEqual(out["hero-current-wl"]["text"], "16–17")
        self.assertEqual(out["hero-current-units"]["text"], "−5.05")
        self.assertEqual(out["hero-current-days"]["text"], "6")
        box = out["hero-current-postseason"]
        self.assertFalse(box["hidden"])
        self.assertEqual(out["hero-current-postseason-label"]["text"],
                         "Postseason · graded, not counted")
        self.assertEqual(out["hero-current-postseason-wl"]["text"], "27–33")
        self.assertEqual(out["hero-current-postseason-units"]["text"], "−9.22")
        self.assertEqual(out["hero-current-postseason-days"]["text"], "16")
        # Same component, same colour rule: both are losses, both are is-down.
        for hook in ("hero-current-postseason-wl", "hero-current-postseason-units",
                     "hero-current-postseason-days"):
            self.assertIn("hero__stat-value", out[hook]["cls"])  # the counted cells' own class
        for hook in ("hero-current-units", "hero-current-postseason-units"):
            self.assertIn("is-down", out[hook]["cls"])

    def test_one_sentence_says_why_only_one_counts_and_nothing_adds_them(self):
        out = self.run_scenario(_meta())["hero"]
        why = out["hero-current-postseason-why"]["text"]
        self.assertEqual(why, "The registered test counts only regular-season games, a sample fixed "
                              "before play began; postseason games are graded and shown here but "
                              "never added to it.")
        everything = " ".join(v["text"] for v in out.values())
        # No pooled figure: 16+27 wins, 17+33 losses, -5.05-9.22 units.
        for pooled in ("43–50", "43-50", "−14.27", "-14.27"):
            self.assertNotIn(pooled, everything)

    def test_a_profitable_postseason_gets_the_same_component_and_the_is_up_colour(self):
        current = dict(CURRENT, postseason=dict(CURRENT["postseason"], wins=33, losses=27,
                                                profit_units=4.5))
        out = self.run_scenario(_meta(current))["hero"]
        self.assertEqual(out["hero-current-postseason-wl"]["text"], "33–27")
        self.assertIn("is-up", out["hero-current-postseason-units"]["cls"])
        self.assertIn("hero__stat-value", out["hero-current-postseason-units"]["cls"])

    def test_no_postseason_means_no_postseason_block_and_the_plain_label(self):
        out = self.run_scenario(_meta(dict(CURRENT, postseason=None)))["hero"]
        self.assertTrue(out["hero-current-postseason"]["hidden"])
        self.assertEqual(out["hero-current-label"]["text"], "Current method")
        self.assertNotIn("hero-current-postseason-wl", out)

    def test_fills_only_postseason_nights_read_as_no_picks_not_as_a_result(self):
        current = dict(CURRENT, postseason={"wins": 0, "losses": 0, "pushes": 0, "profit_units": 0,
                                            "days": 2, "n_staked": 0})
        out = self.run_scenario(_meta(current))["hero"]
        self.assertEqual(out["hero-current-postseason"]["text"],
                         "Postseason: no picks on 2 nights so far. Graded, not counted.")

    def test_the_retired_method_is_off_the_first_screen(self):
        out = self.run_scenario(_meta())["hero"]
        self.assertTrue(out["hero-previous-block"]["hidden"])
        html = (WEB / "desk.html").read_text(encoding="utf-8")
        pointer = re.search(r'data-hook="hero-previous-pointer">([^<]*)<', html).group(1)
        self.assertIn("separate shadow record", pointer)
        self.assertIn("not evidence for the current one", pointer)
        self.assertNotRegex(pointer, r"\d")  # a pointer, not a figure

    def test_on_the_tile_the_retired_method_carries_the_registrations_caveat(self):
        out = self.run_scenario(_meta())["tile"]
        self.assertFalse(out["sport-tile-mlb-previous-block"]["hidden"])
        self.assertEqual(out["sport-tile-mlb-previous-wl"]["text"], "151–79")
        state = out["sport-tile-mlb-previous-state"]
        self.assertIn("Shadow record, not a public record", state["text"])
        self.assertIn("nightly refit read games it should not have", state["text"])
        self.assertIn("not evidence that it worked", state["text"])
        self.assertIn("never added to the current method's numbers", state["text"])
        self.assertIn("hero__proof-sub--caveat", state["cls"])
        # The current block's state line carries no such caveat.
        self.assertNotIn("Shadow record", out["sport-tile-mlb-current-state"]["text"])
        # The tile gets the same counted/postseason pair as the hero.
        self.assertEqual(out["sport-tile-mlb-current-postseason-wl"]["text"], "27–33")

    def test_the_proven_line_names_the_scope_and_carries_the_postseason_figure(self):
        text = self.run_scenario(_meta())["proven"]
        self.assertEqual(
            text,
            "The record so far is negative for the current method: 16–17, −5.05 units over 6 nights "
            "graded (regular season only). Postseason games, graded but not counted by the "
            "registration: 27–33, −9.22 units over 16 nights.")

    def test_the_caveat_stylesheet_rule_is_full_contrast_not_grey_fine_print(self):
        css = (WEB / "css" / "landing.css").read_text(encoding="utf-8")
        rule = re.search(r"\.hero__proof-sub--caveat\s*\{([^}]*)\}", css).group(1)
        self.assertRegex(rule, r"font-size:\s*1[5-9]px")
        self.assertIn("rgba(255, 255, 255, .92)", rule)


if __name__ == "__main__":
    unittest.main()
