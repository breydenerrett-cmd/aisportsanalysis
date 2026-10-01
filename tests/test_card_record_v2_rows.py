"""The public record page lists every pick of the current rule, day by day.

Written 2026-10-01. The record page (web/index.html#/record-card, rendered by
web/js/cardrecord.js) is the product's proof: every pick, graded, losses
included. For the current rule (V2) it showed each night's header and an empty
table, because `dayBlock` read `day.picks` / `prop_picks` / `total_picks` (the
retired rule's shape) while GET /card/history?rule=v2 sends each day as
`graded: [...]` (src/appstate/card_ledger.history_v2): one entry per published
item, `entry_class` "pick" or "fill", no `bet` sentence, no single `book`, no
`published_row_hash` on the day.

Two halves:

  * static checks -- the one shared wording module (web/js/entrytext.js) is
    what both landing.js and cardrecord.js import, the banned words stay out
    of it, and the V2 branch never prints the word "unavailable";
  * a behavioural half that runs the real web/js/cardrecord.js under node
    against a small fake DOM (the pattern of tests/test_landing_what_you_get.py
    and tests/test_checkout_copy_states.py). Skipped when node is missing. It
    imports nothing from `api.*`.
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
RECORD_JS = (JS / "cardrecord.js").read_text(encoding="utf-8")
LANDING_JS = (JS / "landing.js").read_text(encoding="utf-8")
ENTRY_JS = (JS / "entrytext.js").read_text(encoding="utf-8")

BANNED = (
    (r"\bedge\b", "edge"),
    (r"\bprofit(?:s|able)?\b", "profit"),
    (r"\block(?:s|ed|ing)?\b", "lock"),
    (r"\bsharp\b", "sharp"),
    (r"\bwinning\b", "winning"),
    (r"\bguarantee[sd]?\b", "guaranteed"),
    (r"(?i)bet[\s-]*check", "Bet Check"),
    (r"!", "exclamation mark"),
)


def _string_literals(source: str) -> list:
    code = re.sub(r"/\*.*?\*/", " ", source, flags=re.S)
    code = "\n".join(line for line in code.splitlines() if not line.strip().startswith("//"))
    literals = re.findall(r'"(?:[^"\\\n]|\\.)*"|`(?:[^`\\]|\\.)*`', code)
    return [lit[1:-1] for lit in literals]


class OneSharedWordingModule(unittest.TestCase):
    def test_both_pages_import_the_shared_module(self):
        self.assertRegex(RECORD_JS, r'from "\./entrytext\.js"')
        self.assertRegex(LANDING_JS, r'from "\./entrytext\.js"')

    def test_the_wording_functions_live_in_one_place_only(self):
        for name in ("betText", "entryRow", "unitsText", "tallyText", "dayEntries",
                     "propNoun", "signedLine", "isHeavyFavourite"):
            self.assertRegex(ENTRY_JS, r"export function %s\(" % name)
        for source, label in ((LANDING_JS, "landing.js"), (RECORD_JS, "cardrecord.js")):
            for old in ("function lastCardBetText", "function lastCardRow", "function lastCardUnits",
                        "function propNoun", "function signedLine", "function tallyText",
                        "function lastCardDayEntries"):
                self.assertNotIn(old, source, f"{label} still carries its own copy: {old}")

    def test_entrytext_touches_no_dom(self):
        for token in ("document.", "window.", "createElement"):
            self.assertNotIn(token, ENTRY_JS)
        self.assertIsNone(re.search(r"(?<![A-Za-z])el\(", ENTRY_JS))

    def test_no_banned_word_in_the_shared_strings(self):
        for literal in _string_literals(ENTRY_JS):
            for pattern, label in BANNED:
                self.assertIsNone(re.search(pattern, literal, re.I), f"{label!r} in {literal!r}")

    def test_the_v2_branch_never_says_unavailable(self):
        start = RECORD_JS.index("V2 DAYS. GET /card/history")
        end = RECORD_JS.index("export function dayBlock")
        for literal in _string_literals(RECORD_JS[start:end]):
            self.assertNotIn("unavailable", literal.lower())
            for pattern, label in BANNED:
                self.assertIsNone(re.search(pattern, literal, re.I), f"{label!r} in {literal!r}")

    def test_the_retired_rule_path_is_still_there(self):
        for hook in ("record-pick-row", "record-prop-pick-row", "record-total-pick-row"):
            self.assertIn(hook, RECORD_JS)
        self.assertIn("Published receipt hash: ${day.published_row_hash || \"unavailable\"}", RECORD_JS)


# ---------------------------------------------------------------------------
# Behavioural half -- the real cardrecord.js under node.
# ---------------------------------------------------------------------------

HARNESS = r"""
class TextNode {
  constructor(t) { this.nodeType = 3; this.textContent = String(t); this.parentNode = null; }
}
class Elem {
  constructor(tag) {
    this.nodeType = 1; this.tagName = String(tag).toUpperCase(); this.attrs = {};
    this.childNodes = []; this.parentNode = null; this.isRoot = false; this.style = {};
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
  querySelectorAll(sel) {
    const m = sel.match(/^\[([\w-]+)(?:=(?:'([^']*)'|"([^"]*)"))?\]$/);
    if (!m) throw new Error("unsupported selector " + sel);
    const name = m[1]; const val = m[2] !== undefined ? m[2] : m[3];
    return this._all([]).filter((n) => name in n.attrs && (val === undefined || n.attrs[name] === val));
  }
  querySelector(sel) { return this.querySelectorAll(sel)[0] || null; }
}

const body = new Elem("body"); body.isRoot = true;
globalThis.document = {
  createElement: (t) => new Elem(t),
  createTextNode: (t) => new TextNode(t),
  body, referrer: "",
  addEventListener() {},
  querySelector: (s) => body.querySelector(s),
  querySelectorAll: (s) => body.querySelectorAll(s),
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

const { dayBlock, dayRows } = await import("./cardrecord.js");
const out = { days: [] };
for (const day of scenario.days) {
  const card = dayBlock(day);
  const all = card._all([]);
  const rowNodes = all.filter((n) => "data-hook" in n.attrs
    && ["record-entry-row", "record-pick-row", "record-prop-pick-row", "record-total-pick-row"].includes(n.attrs["data-hook"]));
  const inside = (n, hook) => { for (let p = n.parentNode; p; p = p.parentNode) { if (p.attrs && p.attrs["data-hook"] === hook) return true; } return false; };
  out.days.push({
    date: day.date,
    text: text(card),
    hooks: all.map((n) => n.attrs["data-hook"]).filter(Boolean),
    tables: all.filter((n) => n.tagName === "TABLE").length,
    rows: rowNodes.map((tr) => ({
      hook: tr.attrs["data-hook"], kind: tr.attrs["data-kind"], result: tr.attrs["data-result"],
      group: inside(tr, "record-fills") ? "fills" : inside(tr, "record-picks") ? "picks" : null,
      cells: tr.children.map((td) => text(td)),
      tags: tr._all([]).filter((n) => n.attrs["data-hook"] && n.attrs["data-hook"].endsWith("-tag")).map((n) => n.textContent),
    })),
    one: (() => { const w = all.find((n) => n.attrs["data-hook"] === "record-day-withdrawn"); return w ? w.textContent : null; })(),
    model: (() => { const m = dayRows(day); return { shape: m.shape, picks: (m.picks || []).length, fills: (m.fills || []).length, withdrawn: m.withdrawn || 0 }; })(),
  });
}
console.log("@@" + JSON.stringify(out));
"""


def _entry(**fields):
    base = {"entry_class": "pick", "kind": "game", "market": "moneyline", "withdrawn": False,
            "book": None, "books": 11, "line": None, "player": None, "side": None,
            "away_team": None, "home_team": None, "away_score": None, "home_score": None,
            "bet": None, "game_type": "R", "team_name": None}
    base.update(fields)
    return base


# (entries in stored order) -- a won pick, a lost pick, a void pick with a
# reason, a won fill, a withdrawn entry, a postseason fill, a prop pick, an
# entry priced at -210.
ENTRIES = [
    _entry(team_name="Yankees", side="home", price=-135, result="WIN", profit_units=0.7407,
           away_team="BOS", home_team="NYY", away_score=2, home_score=9),
    _entry(entry_class="fill", team_name="Padres", side="home", price=-134, result="WIN",
           profit_units=0.7463),
    _entry(kind="prop", market="batter_hits", player="Michael Busch", side="Over", line=0.5,
           price=-130, books=4, result="LOSS", profit_units=-1.0),
    _entry(kind="prop", market="batter_runs_scored", player="Ethan Salas", side="Over", line=0.5,
           price=110, books=4, result="VOID", profit_units=None,
           reason="no box score found for this player in this game"),
    _entry(kind="prop", market="batter_hits", player="Withdrawn Guy", side="Over", line=0.5,
           price=120, result="WIN", profit_units=1.2, withdrawn=True),
    _entry(entry_class="fill", team_name="Cubs", side="away", price=105, result="LOSS",
           profit_units=-1.0, game_type="F", away_team="CHC", home_team="SD",
           away_score=1, home_score=4),
    _entry(kind="prop", market="batter_total_bases", player="Xander Bogaerts", side="Over", line=0.5,
           price=-155, books=4, result="WIN", profit_units=0.6452),
    _entry(team_name="Dodgers", side="home", price=-210, result="WIN", profit_units=0.4762),
]


def _v2_day(entries=None, **extra):
    day = {"date": "2026-09-30", "rule": "DAILY_CARD_BEST_BETS_V2", "wins": 4, "losses": 2,
           "pushes": 0, "voids": 1, "profit_units": 0.9, "graded": list(ENTRIES if entries is None else entries)}
    day.update(extra)
    return day


V1_DAY = {
    "date": "2026-09-12", "wins": 1, "losses": 1, "pushes": 0, "voids": 0, "profit_units": -0.33,
    "published_row_hash": "abc123",
    "picks": [
        {"bet": "Take Cubs to win at -150", "price": -150, "book": "draftkings", "books": 9,
         "result": "WIN", "profit_units": 0.6667, "away_team": "CHC", "home_team": "SD",
         "away_score": 4, "home_score": 1},
    ],
    "prop_picks": [
        {"bet": "Take Busch over 0.5 hits at -120", "price": -120, "book": "fanduel", "books": 5,
         "result": "LOSS", "profit_units": -1.0},
    ],
    "total_picks": [],
}


@unittest.skipUnless(shutil.which("node"), "node not installed")
class TheRecordRowsRenderUnderNode(unittest.TestCase):
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

    def render(self, *days):
        env = dict(os.environ, SCENARIO=json.dumps({"days": list(days)}))
        proc = subprocess.run(["node", "harness.mjs"], cwd=self._tmp.name, env=env,
                              capture_output=True, text=True, encoding="utf-8", timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr[-2000:])
        line = [ln for ln in proc.stdout.splitlines() if ln.startswith("@@")][-1]
        return json.loads(line[2:])["days"]

    def v2(self, entries=None, **extra):
        return self.render(_v2_day(entries, **extra))[0]

    def by_bet(self, out):
        return {row["cells"][0].split("\n")[0]: row for row in out["rows"]}

    # ---- rows exist, in two separate groups -----------------------------

    def test_a_v2_day_lists_one_row_per_entry_not_an_empty_table(self):
        out = self.v2()
        # 8 entries, 1 withdrawn -> 7 rows; this is the defect: an empty table.
        self.assertEqual(len(out["rows"]), 7)
        self.assertEqual(out["model"], {"shape": "v2", "picks": 5, "fills": 2, "withdrawn": 1})

    def test_picks_and_fills_are_in_separate_groups_in_stored_order(self):
        out = self.v2()
        picks = [r["cells"][0].split("\n")[0] for r in out["rows"] if r["group"] == "picks"]
        fills = [r["cells"][0].split("\n")[0] for r in out["rows"] if r["group"] == "fills"]
        self.assertEqual(picks, ["Yankees to win", "Michael Busch over 0.5 hits",
                                 "Ethan Salas over 0.5 runs scored",
                                 "Xander Bogaerts over 0.5 total bases", "Dodgers to win"])
        self.assertEqual(fills, ["Padres to win", "Cubs to win"])
        self.assertTrue(all(r["kind"] == "pick" for r in out["rows"] if r["group"] == "picks"))
        self.assertTrue(all(r["kind"] == "fill" for r in out["rows"] if r["group"] == "fills"))
        self.assertIn("Fills, not picks", out["text"])
        self.assertIn("never counted in the record", out["text"])
        # picks come first, then the fills group
        self.assertLess(out["hooks"].index("record-picks"), out["hooks"].index("record-fills"))

    def test_a_fill_is_labelled_and_a_pick_is_not(self):
        out = self.v2()
        rows = self.by_bet(out)
        self.assertEqual(rows["Padres to win"]["tags"][0], "Fill, not a pick")
        self.assertNotIn("Fill, not a pick", rows["Yankees to win"]["cells"][0])
        self.assertNotIn("Fill", " ".join(" ".join(r["tags"]) for r in out["rows"] if r["kind"] == "pick"))

    # ---- what each row says ---------------------------------------------

    def test_a_won_pick_says_won_its_price_its_book_count_and_its_return(self):
        row = self.by_bet(self.v2())["Yankees to win"]
        bet, result, price, book, ret = row["cells"]
        self.assertIn("Won", result)
        self.assertIn("BOS 2, NYY 9", result)
        self.assertEqual(price, "-135")
        self.assertEqual(book, "best of 11 books")
        self.assertEqual(ret, "+0.74u")

    def test_a_lost_pick_says_lost_with_its_negative_return(self):
        row = self.by_bet(self.v2())["Michael Busch over 0.5 hits"]
        self.assertIn("Lost", row["cells"][1])
        self.assertEqual(row["cells"][4], "-1.00u")
        self.assertEqual(row["cells"][3], "best of 4 books")

    def test_a_void_shows_its_stored_reason_and_no_units(self):
        row = self.by_bet(self.v2())["Ethan Salas over 0.5 runs scored"]
        self.assertIn("Void", row["cells"][1])
        self.assertIn("no box score found for this player in this game", row["cells"][1])
        self.assertEqual(row["cells"][4], "—")
        self.assertNotIn("u", row["cells"][4])
        self.assertNotIn("Won", row["cells"][1])

    def test_a_fill_shows_its_own_return(self):
        row = self.by_bet(self.v2())["Padres to win"]
        self.assertEqual(row["cells"][4], "+0.75u")
        self.assertIn("Won", row["cells"][1])

    def test_an_entry_priced_at_minus_210_is_shown_not_hidden(self):
        out = self.v2()
        row = self.by_bet(out)["Dodgers to win"]
        self.assertEqual(row["cells"][2], "-210")
        self.assertIn("Won", row["cells"][1])

    def test_the_postseason_tag_is_on_the_postseason_entry_only(self):
        out = self.v2()
        rows = self.by_bet(out)
        self.assertIn("Postseason, graded, not counted", rows["Cubs to win"]["tags"])
        self.assertEqual(rows["Cubs to win"]["tags"], ["Fill, not a pick", "Postseason, graded, not counted"])
        for name, row in rows.items():
            if name != "Cubs to win":
                self.assertNotIn("Postseason, graded, not counted", row["tags"], name)

    def test_a_book_name_is_shown_only_when_the_entry_has_one(self):
        entries = [_entry(team_name="Mets", price=-120, result="WIN", profit_units=0.8333,
                          book="draftkings", books=9),
                   _entry(team_name="Braves", price=-125, result="LOSS", profit_units=-1.0,
                          books=None)]
        rows = self.by_bet(self.v2(entries))
        self.assertIn("best of 9 books", rows["Mets to win"]["cells"][3])
        self.assertTrue(rows["Mets to win"]["cells"][3].lower().startswith("draftkings")
                        or "draft" in rows["Mets to win"]["cells"][3].lower())
        self.assertEqual(rows["Braves to win"]["cells"][3], "—")

    # ---- withdrawn ------------------------------------------------------

    def test_a_withdrawn_entry_is_not_a_row_and_one_line_counts_it(self):
        out = self.v2()
        self.assertNotIn("Withdrawn Guy", out["text"].replace(out["one"] or "", ""))
        self.assertNotIn("Withdrawn Guy", " ".join(r["cells"][0] for r in out["rows"]))
        self.assertEqual(out["one"], "1 entry was withdrawn before the game and is not counted in the record.")
        self.assertIn("1 entry was withdrawn before the game and is not counted", out["text"])

    def test_no_withdrawn_line_when_nothing_was_withdrawn(self):
        entries = [e for e in ENTRIES if not e["withdrawn"]]
        out = self.v2(entries)
        self.assertIsNone(out["one"])
        self.assertNotIn("withdrawn", out["text"])

    def test_two_withdrawn_entries_read_in_the_plural(self):
        entries = ENTRIES + [_entry(team_name="Reds", price=100, result="LOSS", profit_units=-1.0,
                                    withdrawn=True)]
        self.assertEqual(self.v2(entries)["one"],
                         "2 entries were withdrawn before the game and are not counted in the record.")

    # ---- the reader can reconcile the rows with the header ---------------

    def test_the_header_is_the_day_rows_own_figure_not_recomputed(self):
        out = self.v2()
        head = out["text"].split("\n")
        self.assertIn("4-2-0", head)
        self.assertIn("+0.90u", head)   # the stored 0.9, not the listed rows' sum

    def test_the_reconcile_line_matches_the_listed_rows(self):
        out = self.v2()
        listed = [e for e in ENTRIES if not e["withdrawn"]]
        picks = [e for e in listed if e["entry_class"] == "pick"]
        fills = [e for e in listed if e["entry_class"] == "fill"]

        def tally(es):
            w = sum(e["result"] == "WIN" for e in es)
            l = sum(e["result"] == "LOSS" for e in es)
            v = sum(e["result"] == "VOID" for e in es)
            u = round(sum(e["profit_units"] for e in es if e["result"] in ("WIN", "LOSS")), 4)
            return w, l, v, u

        pw, pl, pv, pu = tally(picks)
        fw, fl, fv, fu = tally(fills)
        sign = lambda n: ("+" if n > 0 else "") + f"{n:.2f}"
        expected_picks = f"Picks: {pw}-{pl}-0, {pv} void, {sign(pu)}u."
        expected_fills = f"Fills (never counted in the record): {fw}-{fl}-0, {sign(fu)}u."
        line = next(ln for ln in out["text"].split("\n") if ln.startswith("Picks:"))
        self.assertIn(expected_picks, line)
        self.assertIn(expected_fills, line)
        self.assertIn("The figure above also includes the 1 withdrawn entry.", line)
        # and the groups really hold those rows
        self.assertEqual(sum(1 for r in out["rows"] if r["group"] == "picks"), len(picks))
        self.assertEqual(sum(1 for r in out["rows"] if r["group"] == "fills"), len(fills))

    def test_fill_units_are_never_in_the_pick_total(self):
        entries = [_entry(team_name="Mets", price=-120, result="WIN", profit_units=0.8333),
                   _entry(entry_class="fill", team_name="Braves", price=-125, result="WIN",
                          profit_units=0.8)]
        line = next(ln for ln in self.v2(entries)["text"].split("\n") if ln.startswith("Picks:"))
        self.assertIn("Picks: 1-0-0, +0.83u.", line)
        self.assertIn("Fills (never counted in the record): 1-0-0, +0.80u.", line)

    # ---- nothing empty, nothing invented ---------------------------------

    def test_no_row_is_empty_and_unavailable_never_appears(self):
        weird = ENTRIES + [
            _entry(result="UNRESOLVED", price=None),                    # nothing readable at all
            _entry(team_name="Mets", price=-120, result="UNRESOLVED"),  # not graded yet
        ]
        out = self.v2(weird)
        self.assertNotIn("unavailable", out["text"].lower())
        for row in out["rows"]:
            self.assertTrue(row["cells"][0].strip(), row)
            self.assertEqual(len(row["cells"]), 5)
            self.assertTrue(all(c.strip() for c in row["cells"]), row)
        rows = self.by_bet(out)
        self.assertIn("Not graded yet", rows["Mets to win"]["cells"][1])
        self.assertEqual(rows["Mets to win"]["cells"][4], "—")
        unnamed = [r for r in out["rows"] if r["cells"][0].startswith("Entry could not be named")]
        self.assertEqual(len(unnamed), 1)
        self.assertEqual(unnamed[0]["cells"][2], "—")

    def test_the_banned_words_do_not_appear_in_the_rendered_day(self):
        out = self.v2()
        for pattern, label in BANNED:
            self.assertIsNone(re.search(pattern, out["text"], re.I), label)

    def test_a_receipt_hash_is_printed_only_when_the_payload_has_one(self):
        without = self.v2()
        self.assertNotIn("receipt", without["text"].lower())
        self.assertNotIn("record-day-hash", without["hooks"])
        with_hash = self.v2(published_row_hash="deadbeef")
        self.assertIn("Published receipt hash: deadbeef", with_hash["text"])

    def test_a_day_of_fills_only_says_so_and_has_no_picks_table(self):
        out = self.v2([ENTRIES[1], ENTRIES[5]])
        self.assertIn("No pick passed every check that night, so the card listed fills only.", out["text"])
        self.assertEqual({r["group"] for r in out["rows"]}, {"fills"})
        self.assertEqual(out["tables"], 1)
        self.assertIn("Picks: none.", out["text"])

    # ---- the other shapes -----------------------------------------------

    def test_an_empty_graded_list_says_nothing_was_published(self):
        out = self.v2([])
        self.assertIn("No entries were published this day.", out["text"])
        self.assertEqual(out["tables"], 0)
        self.assertEqual(out["rows"], [])
        self.assertNotIn("unavailable", out["text"].lower())
        self.assertNotIn("BET", out["text"].split("\n"))

    def test_a_v1_day_renders_the_old_row_shape(self):
        out = self.render(V1_DAY)[0]
        self.assertEqual(out["model"]["shape"], "v1")
        self.assertEqual([r["hook"] for r in out["rows"]], ["record-pick-row", "record-prop-pick-row"])
        game, prop = out["rows"]
        self.assertEqual(game["cells"][0].split("\n")[0], "Take Cubs to win at -150")
        self.assertIn("WIN", game["cells"][1])
        self.assertEqual(game["cells"][2], "-150")
        self.assertIn("best of 9", game["cells"][3])
        self.assertEqual(game["cells"][4], "+0.67u")
        self.assertIn("PROP", prop["cells"][0])
        self.assertEqual(out["tables"], 1)
        self.assertIn("Published receipt hash: abc123", out["text"])
        self.assertNotIn("record-fills", out["hooks"])
        self.assertNotIn("record-entry-row", out["hooks"])

    def test_a_v1_day_without_a_hash_still_says_unavailable_as_before(self):
        day = dict(V1_DAY)
        day.pop("published_row_hash")
        self.assertIn("Published receipt hash: unavailable", self.render(day)[0]["text"])

    def test_an_nfl_or_ufc_style_day_with_picks_only_is_untouched(self):
        day = {"date": "2026-09-21", "wins": 1, "losses": 0, "pushes": 0, "profit_units": 0.9,
               "picks": [{"bet": "Take Chiefs to win at -140", "price": -140, "book": "fanduel",
                          "result": "WIN", "profit_units": 0.7143}]}
        out = self.render(day)[0]
        self.assertEqual(out["model"]["shape"], "v1")
        self.assertEqual(len(out["rows"]), 1)
        self.assertEqual(out["rows"][0]["hook"], "record-pick-row")

    def test_a_v1_day_with_no_lists_at_all_keeps_its_empty_table(self):
        out = self.render({"date": "2026-09-01", "wins": 0, "losses": 0, "pushes": 0})[0]
        self.assertEqual(out["model"]["shape"], "v1")
        self.assertEqual(out["tables"], 1)


if __name__ == "__main__":
    unittest.main()
