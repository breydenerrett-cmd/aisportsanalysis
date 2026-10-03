"""The "Situation" block in the MLB written read and the UFC fight-night read.

THREE PROMISES
--------------
1. A read built without a situation record has exactly the keys and the sentences it always had (the
   block is its own key, added only when a record is handed in), so no existing read, golden file or
   shape test moves.
2. Every sentence in the block is a sentence of the record, shown with the sample in its words, and
   its evidence path resolves in the payload the page holds.
3. The words are plain: nothing the product's wording sweeps ban, nothing about EQ.

The JS half runs the real `matchupread.js` and `ufcfights.js` under node (skipped when node is
missing).
"""

from __future__ import annotations

import ast
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from src import paths
from src.analysis import matchup_read as mr
from src.analysis import ufc_read as ur
from src.situation import mlb as situation_mlb
from src.situation import record as rec
from tests import situation_fixtures as F
from tests import test_customer_language as language
from tests.test_matchup_read import plain
from tests.test_ufc_read import read_of

ROOT = Path(paths.repo_root())
JS = ROOT / "web" / "js"


def mlb_record():
    return situation_mlb.situation_for_game(F.division_game(1), F.world(), strict=True)


def ufc_record():
    """A small hand-built UFC record in the shape `situation_for_bout` writes."""
    factors = [
        rec.factor("stakes", "card_position", 1, "bout number", sample={}, as_of="2026-10-09T23:00:00Z",
                   source="the schedule", sentence="The main event, main card, scheduled for 5 rounds.",
                   detail={"scheduled_rounds": 5}),
        rec.factor("rest_and_rhythm", "days_since_last_fight", 119, "days", sample={"fights": 5}, side="a",
                   as_of="2026-06-13T22:00:00Z", source="UFC data store",
                   sentence="Alex Archer last fought 119 days before this bout (2026-06-13): a win on the scorecards."),
        rec.factor("form", "streak", 1, "fights", sample={"fights": 5}, side="b", as_of="2026-08-08T22:00:00Z",
                   source="UFC data store", sentence="Ben Brawler lost the last UFC fight on file.",
                   detail={"type": "loss"}),
    ]
    return rec.build(sport="ufc", subject={"bout_id": "9101"}, as_of="2026-10-10T23:00:00Z", as_of_basis="t",
                     families=("rest_and_rhythm", "form", "stakes"), sides=("a", "b"), factors=factors,
                     missing=[rec.gap("stakes", "rankings", "rankings are not in the data")],
                     display=[("stakes", "card_position", "game"), ("rest_and_rhythm", "days_since_last_fight", "a"),
                              ("form", "streak", "b")])


# ---------------------------------------------------------------------------
# the MLB read
# ---------------------------------------------------------------------------

class TheMlbBlock(unittest.TestCase):
    def payload(self, **extra):
        p = plain()
        p.update(extra)
        return p

    def test_a_read_without_a_record_is_the_read_it_always_was(self):
        base = mr.build_read(plain())
        self.assertNotIn("situation", base)
        for none in (None, {}, "nope", []):
            self.assertEqual(mr.build_read(self.payload(situation=none)), base, repr(none))

    def test_with_a_record_the_only_difference_is_the_one_new_key(self):
        base = mr.build_read(plain())
        withit = mr.build_read(self.payload(situation=mlb_record()))
        block = withit.pop("situation")
        self.assertEqual(withit, base)
        self.assertEqual(set(block), {"label", "as_of", "lines", "missing"})
        self.assertEqual(block["label"], mr.SITUATION_LABEL)
        self.assertEqual(block["as_of"], "2025-10-04")

    def test_the_lines_are_the_records_sentences_with_evidence_that_resolves(self):
        record = mlb_record()
        payload = self.payload(situation=record)
        block = mr.build_read(payload)["situation"]
        self.assertLessEqual(len(block["lines"]), mr.SITUATION_LINES)
        self.assertGreaterEqual(len(block["lines"]), 4)
        sentences = {f["sentence"] for f in record["factors"]}
        for line in block["lines"]:
            self.assertIn(line["sentence"], sentences)
            found, value = mr.resolve_path(payload, line["evidence"]["path"])
            self.assertTrue(found, line["evidence"])
            self.assertEqual(value, line["evidence"]["value"])

    def test_a_division_series_game_leads_with_the_series_and_the_rest_picture(self):
        block = mr.build_read(self.payload(situation=mlb_record()))["situation"]
        text = [ln["sentence"] for ln in block["lines"]]
        self.assertEqual(text[0], "Game 1 of the Division Series (best of 5).")
        self.assertIn("NYY had a bye: it did not play in the Wild Card Series.", text)
        self.assertTrue(any(t.startswith("TB won the Wild Card Series 2-1 over BOS") for t in text))

    def test_the_sample_is_in_the_words(self):
        block = mr.build_read(self.payload(situation=mlb_record()))["situation"]
        self.assertTrue(any("over its last 10 games" in ln["sentence"] for ln in block["lines"]))

    def test_what_the_record_could_not_say_is_listed_in_the_reads_own_shape(self):
        block = mr.build_read(self.payload(situation=mlb_record()))["situation"]
        self.assertTrue(block["missing"])
        for item in block["missing"]:
            self.assertEqual(set(item), {"input", "status", "detail"})
            self.assertIn(item["status"], ("absent", "stale"))
        self.assertTrue(any("manager" in m["input"] for m in block["missing"]))

    def test_a_stale_store_shows_as_stale(self):
        record = situation_mlb.situation_for_game(F.game(601, "2025-10-20", "NYY", "TB", "L"), F.world(), strict=True)
        block = mr.build_read(self.payload(situation=record))["situation"]
        self.assertIn("stale", [m["status"] for m in block["missing"]])

    def test_a_record_that_cannot_be_shown_costs_the_block_not_the_read(self):
        broken = {"factors": [{"family": "form"}], "display": [0], "missing": [{"name": "x"}]}
        read = mr.build_read(self.payload(situation=broken))
        self.assertIn("headline", read)
        self.assertNotIn("situation", read)

    def test_the_read_stays_deterministic_and_json_clean(self):
        p = self.payload(situation=mlb_record())
        self.assertEqual(json.dumps(mr.build_read(p), sort_keys=True), json.dumps(mr.build_read(p), sort_keys=True))

    def test_a_record_with_nothing_to_show_shows_no_block(self):
        empty = rec.build(sport="mlb", subject={}, as_of="2025-10-04", as_of_basis="t", families=("form",),
                          sides=("away", "home"), factors=[], missing=[])
        self.assertNotIn("situation", mr.build_read(self.payload(situation=empty)))


# ---------------------------------------------------------------------------
# the UFC read
# ---------------------------------------------------------------------------

class TheUfcBlock(unittest.TestCase):
    def test_a_read_without_a_record_has_exactly_the_keys_it_always_had(self):
        base = read_of()
        self.assertNotIn("situation", base)
        self.assertEqual(set(base), {"version", "label", "as_of", "headline", "headline_trait", "notices",
                                     "data_depth", "a", "b", "context", "history", "market_view",
                                     "what_would_change_it", "missing"})

    def test_with_a_record_the_only_difference_is_the_one_new_key(self):
        base = read_of()
        from tests.test_ufc_read import make_sheet
        withit = ur.build_read(make_sheet(), situation=ufc_record())
        block = withit.pop("situation")
        self.assertEqual(withit, base)
        self.assertEqual(block["label"], ur.SITUATION_LABEL)
        self.assertEqual([ln["sentence"] for ln in block["lines"]],
                         ["The main event, main card, scheduled for 5 rounds.",
                          "Alex Archer last fought 119 days before this bout (2026-06-13): a win on the scorecards.",
                          "Ben Brawler lost the last UFC fight on file."])
        self.assertEqual(block["missing"], [{"input": "stakes: rankings", "status": "absent",
                                             "detail": "rankings are not in the data"}])

    def test_the_evidence_resolves_in_the_bout_that_holds_the_record(self):
        record = ufc_record()
        bout = {"situation": record}
        from tests.test_ufc_read import make_sheet
        block = ur.build_read(make_sheet(), situation=record)["situation"]
        for line in block["lines"]:
            found, value = ur.resolve_path(bout, line["evidence"]["path"])
            self.assertTrue(found, line["evidence"])
            self.assertEqual(value, line["evidence"]["value"])

    def test_a_record_that_cannot_be_shown_costs_the_block_not_the_read(self):
        from tests.test_ufc_read import make_sheet
        read = ur.build_read(make_sheet(), situation={"factors": [{"family": "form"}], "display": [0], "missing": [{}]})
        self.assertIn("headline", read)
        self.assertNotIn("situation", read)

    def test_the_golden_reads_are_untouched_because_they_carry_no_record(self):
        golden = json.loads((ROOT / "tests" / "fixtures" / "ufc_read_golden.json").read_text(encoding="utf-8"))
        self.assertTrue(golden)
        self.assertNotIn("situation", json.dumps(golden))


# ---------------------------------------------------------------------------
# the words
# ---------------------------------------------------------------------------

def literals(path: Path):
    return [(n, s) for n, s in language._string_literals(path)]


class TheWords(unittest.TestCase):
    """Every sentence the situation layer can put in front of a reader passes the product's own
    customer-language rules (tests/test_customer_language.py scans src/analysis and src/report; the
    sentences come from here, so this scans src/situation the same way)."""

    FILES = sorted((ROOT / "src" / "situation").glob("*.py"))

    def test_the_scan_found_the_package(self):
        self.assertGreaterEqual(len(self.FILES), 6)
        self.assertGreater(sum(len(literals(p)) for p in self.FILES), 200)

    def test_no_literal_uses_a_phrase_the_product_bans_outright(self):
        offenders = []
        for path in self.FILES:
            for line, text in literals(path):
                for pattern, label in language.HARD_BANNED:
                    if re.search(pattern, text, re.I):
                        offenders.append(f"{path.name}:{line}: {label}: {text[:60]!r}")
        self.assertEqual(offenders, [])

    def test_no_literal_affirms_edge_guarantee_or_win_probability(self):
        offenders = []
        for path in self.FILES:
            for line, text in literals(path):
                for pattern, label in language.NEGATION_ONLY:
                    for m in re.finditer(pattern, text, re.I):
                        window = text[max(0, m.start() - 60):m.start()]
                        if not language.NEGATORS.search(window):
                            offenders.append(f"{path.name}:{line}: {label}: {text[:60]!r}")
        self.assertEqual(offenders, [])

    def test_the_sentences_never_use_emotional_intelligence_as_a_word(self):
        for path in self.FILES:
            for line, text in literals(path):
                self.assertNotRegex(text, r"(?i)\bemotional intelligence\b|\bEQ\b", f"{path.name}:{line}")

    def test_every_factor_the_builders_write_is_free_of_banned_words(self):
        records = [mlb_record(), situation_mlb.situation_for_game(F.regular_game(), F.world(), strict=True),
                   ufc_record()]
        for record in records:
            for item in record["factors"]:
                for pattern, label in language.HARD_BANNED + language.NEGATION_ONLY:
                    self.assertIsNone(re.search(pattern, item["sentence"], re.I), (label, item["sentence"]))


# ---------------------------------------------------------------------------
# the JS, under node
# ---------------------------------------------------------------------------

STUB_API = """
export class ApiError extends Error { constructor(status, detail) { super(String(detail)); this.status = status; } }
export const TOKEN_STORAGE_KEY = "t"; export const TOKEN_CHANGED_EVENT = "t";
export const FREE_CHECK_TOKEN_STORAGE_KEY = "t"; export const DEFAULT_TIMEOUT_MS = 1;
export function getToken() { return "x"; } export function setToken() {} export function clearToken() {}
export function getFreeCheckToken() { return null; } export function setFreeCheckToken() {}
export function setPublicDemo() {} export function isPublicDemo() { return false; }
export function apiFetch() { throw new Error("no network"); } export function apiGet() { throw new Error("no network"); }
export function apiPost() { throw new Error("no network"); } export function apiDelete() { throw new Error("no network"); }
export function trackFunnelEvent() {}
"""

HARNESS = r"""
class TextNode { constructor(t) { this.nodeType = 3; this.textContent = String(t); this.parentNode = null; } }
class Elem {
  constructor(tag) { this.nodeType = 1; this.tagName = String(tag).toUpperCase(); this.attrs = {};
    this.childNodes = []; this.parentNode = null; this.style = {}; }
  get children() { return this.childNodes.filter((c) => c.nodeType === 1); }
  appendChild(c) { if (c.parentNode) c.parentNode.removeChild(c); c.parentNode = this; this.childNodes.push(c); return c; }
  removeChild(c) { const i = this.childNodes.indexOf(c); if (i >= 0) this.childNodes.splice(i, 1); c.parentNode = null; return c; }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; }
  set textContent(v) { const t = new TextNode(v); t.parentNode = this; this.childNodes = [t]; }
  get textContent() { return this.childNodes.map((c) => c.textContent).join(""); }
  addEventListener() {}
  _all(out) { for (const c of this.children) { out.push(c); c._all(out); } return out; }
}
globalThis.document = { createElement: (t) => new Elem(t), createTextNode: (t) => new TextNode(t),
  body: new Elem("body"), addEventListener() {}, querySelector: () => null, querySelectorAll: () => [] };
const store = new Map();
globalThis.window = { localStorage: { getItem: (k) => (store.has(k) ? store.get(k) : null), setItem: (k, v) => store.set(k, String(v)),
  removeItem: (k) => store.delete(k) }, location: { search: "", host: "x", pathname: "/", hash: "" },
  history: { replaceState() {} }, addEventListener() {}, dispatchEvent() { return true; } };
globalThis.fetch = async () => ({ ok: true, status: 200, text: async () => "{}" });

const scenario = JSON.parse(process.env.SCENARIO);
const mr = await import("./matchupread.js");
const uf = await import("./ufcfights.js");
const describe = (node) => {
  if (node === null) return null;
  const all = node._all([]);
  const hook = (h) => all.filter((n) => n.attrs["data-hook"] === h);
  return {
    tag: node.tagName, hook: node.attrs["data-hook"],
    lines: all.filter((n) => /situation-line$/.test(n.attrs["data-hook"] || "")).map((n) => n.textContent),
    subheads: all.filter((n) => /subhead$/.test(n.attrs.class || "")).map((n) => n.textContent),
    evidenceRows: all.filter((n) => /evidence__row$/.test(n.attrs.class || "")).length,
    detailsSummaries: all.filter((n) => n.tagName === "SUMMARY").map((n) => n.textContent),
    missingRows: all.filter((n) => /__item$/.test(n.attrs.class || "")).length,
    hooks: all.map((n) => n.attrs["data-hook"]).filter(Boolean),
    tables: all.filter((n) => ["TABLE", "TR", "TD"].includes(n.tagName)).length,
  };
};
const out = { mlb: scenario.mlb.map((s) => describe(mr.situationView(s))),
              ufc: scenario.ufc.map((s) => describe(uf.situationView(s))),
              read: scenario.reads.map((r) => { const n = mr.renderMatchupRead(r); return n === null ? null : n._all([]).map((x) => x.attrs["data-hook"]).filter(Boolean); }) };
console.log("@@" + JSON.stringify(out));
"""


def block_for(record, label="L"):
    return rec.page_block(record, label=label)


@unittest.skipUnless(shutil.which("node"), "node not installed")
class TheBlocksRenderUnderNode(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        for path in JS.glob("*.js"):
            shutil.copy(path, cls._tmp.name)
        Path(cls._tmp.name, "api.js").write_text(STUB_API, encoding="utf-8")        # no network under test
        Path(cls._tmp.name, "package.json").write_text('{"type": "module"}', encoding="utf-8")
        Path(cls._tmp.name, "harness.mjs").write_text(HARNESS, encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def render(self, mlb=(), ufc=(), reads=()):
        env = dict(os.environ, SCENARIO=json.dumps({"mlb": list(mlb), "ufc": list(ufc), "reads": list(reads)}))
        proc = subprocess.run(["node", "harness.mjs"], cwd=self._tmp.name, env=env, capture_output=True,
                              text=True, encoding="utf-8", timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr[-2000:])
        return json.loads([ln for ln in proc.stdout.splitlines() if ln.startswith("@@")][-1][2:])

    def test_nothing_to_show_renders_nothing(self):
        out = self.render(mlb=[None, {}, {"lines": [], "missing": []}, "x"], ufc=[None, {}, {"lines": []}])
        self.assertEqual(out["mlb"], [None, None, None, None])
        self.assertEqual(out["ufc"], [None, None, None])

    def test_the_mlb_block_prints_the_servers_sentences_and_nothing_of_its_own(self):
        block = mr.build_read({**plain(), "situation": mlb_record()})["situation"]
        out = self.render(mlb=[block])["mlb"][0]
        self.assertEqual(out["tag"], "DIV")
        self.assertEqual(out["hook"], "read-situation")
        self.assertEqual(out["lines"], [ln["sentence"] for ln in block["lines"]])
        self.assertEqual(out["subheads"], ["SITUATION"])
        self.assertEqual(out["evidenceRows"], len(block["lines"]))
        self.assertIn(f"EVIDENCE ({len(block['lines'])})", out["detailsSummaries"])
        self.assertIn(f"WHAT THE SITUATION COULD NOT SAY ({len(block['missing'])})", out["detailsSummaries"])
        self.assertEqual(out["missingRows"], len(block["missing"]))
        self.assertEqual(out["tables"], 0)                                     # no tables: it has to hold at 390px

    def test_the_ufc_block_prints_the_servers_sentences(self):
        block = ur.build_read(__import__("tests.test_ufc_read", fromlist=["make_sheet"]).make_sheet(),
                              situation=ufc_record())["situation"]
        out = self.render(ufc=[block])["ufc"][0]
        self.assertEqual(out["hook"], "ufc-situation")
        self.assertEqual(out["lines"], [ln["sentence"] for ln in block["lines"]])
        self.assertEqual(out["subheads"], ["SITUATION"])
        self.assertEqual(out["evidenceRows"], 3)
        self.assertEqual(out["missingRows"], 1)
        self.assertEqual(out["tables"], 0)

    def test_a_stale_item_is_drawn_in_the_warning_tone_and_a_block_with_only_gaps_still_shows(self):
        only_gaps = {"label": "L", "as_of": "x", "lines": [],
                     "missing": [{"input": "results store", "status": "stale", "detail": "ends days before"}]}
        out = self.render(mlb=[only_gaps], ufc=[only_gaps])
        for key in ("mlb", "ufc"):
            self.assertEqual(out[key][0]["lines"], [])
            self.assertEqual(out[key][0]["missingRows"], 1)

    def test_the_read_places_the_block_after_the_factors_and_before_the_expected_runs(self):
        read = mr.build_read({**plain(), "situation": mlb_record()})
        hooks = self.render(reads=[read])["read"][0]
        self.assertIn("read-situation", hooks)
        self.assertLess(hooks.index("read-situation"), hooks.index("read-runs"))
        if "read-factor" in hooks:
            self.assertLess(max(i for i, h in enumerate(hooks) if h == "read-factor"), hooks.index("read-situation"))

    def test_a_read_with_no_situation_has_no_situation_hook(self):
        hooks = self.render(reads=[mr.build_read(plain())])["read"][0]
        self.assertNotIn("read-situation", hooks)

    def test_the_fight_night_panel_places_the_block_after_the_history_and_before_the_price(self):
        text = (JS / "ufcfights.js").read_text(encoding="utf-8")
        body = text.split("function readBlocks(panel, bout) {")[1].split("\nfunction ")[0]
        self.assertLess(body.index("historyBlock(read.history)"), body.index("situationView(read.situation)"))
        self.assertLess(body.index("situationView(read.situation)"), body.index("marketBlock(read.market_view)"))


class TheJsWords(unittest.TestCase):
    def test_the_situation_blocks_strings_pass_the_developer_and_retired_phrase_sweeps(self):
        from tests.test_no_developer_notes_on_screen import DEVELOPER_WORDS, _rendered_strings
        from tests.test_web_register_sweep import RETIRED
        for name in ("matchupread.js", "ufcfights.js"):
            for line_no, text in _rendered_strings(JS / name):
                low = text.lower()
                for word, _why in DEVELOPER_WORDS:
                    self.assertIsNone(re.search(rf"\b{re.escape(word)}\b", low), f"{name}:{line_no}: {word}")
                for phrase in RETIRED:
                    self.assertNotIn(phrase, low, f"{name}:{line_no}")

    def test_both_modules_export_the_view_and_neither_computes_a_view_of_its_own(self):
        for name in ("matchupread.js", "ufcfights.js"):
            text = (JS / name).read_text(encoding="utf-8")
            self.assertIn("export function situationView(situation)", text)
            body = text.split("export function situationView(situation)")[1].split("\n}\n")[0]
            for banned in ("Math.", "toFixed", "reduce(", "sort("):
                self.assertNotIn(banned, body, f"{name}: the view only prints what the server wrote")

    def test_the_read_module_names_nothing_with_a_capital_block(self):
        """tests/test_matchup_read_web.py strips the lowercase word `block` from matchupread.js and
        then forbids `lock`. The first draft named the view `situationBlock`: the capital B slipped
        past that strip, left `lock` behind, and failed the full suite on 2026-10-03. The view is
        `situationView`, and this pins the story where the next person to add a helper will see it."""
        text = (JS / "matchupread.js").read_text(encoding="utf-8")
        self.assertNotIn("situationBlock", text)
        self.assertNotIn("lock", text.replace("block", "").lower())


if __name__ == "__main__":
    unittest.main()
