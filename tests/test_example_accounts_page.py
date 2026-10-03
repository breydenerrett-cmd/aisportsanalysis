"""The "If you had followed every pick" section of the record page
(web/js/exampleaccounts.js, mounted by web/js/cardrecord.js).

Two halves, like the other record-page tests: static checks on the source, and
a behavioural half that runs the REAL modules under node against a small fake
DOM (skipped when node is missing). The payloads fed to the page are built by
the real src/appstate/example_accounts.py from the fixture copies of the real
ledger rows, so the page is exercised against the exact shape the server sends.

What is pinned: the headline is the payload's own numbers, switching account
and sport redraws, a loss reads as a loss, an unavailable payload is one plain
sentence and no balance, and no percentage is printed for a small sample.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

from src.appstate import example_accounts as ea
from tests._example_accounts_fixtures import fixture_ledgers
from tests.test_example_accounts_reconcile import config, sources

ROOT = Path(__file__).resolve().parent.parent
JS = ROOT / "web" / "js"
MODULE_JS = (JS / "exampleaccounts.js").read_text(encoding="utf-8")
RECORD_JS = (JS / "cardrecord.js").read_text(encoding="utf-8")
CARD_CSS = (ROOT / "web" / "css" / "card.css").read_text(encoding="utf-8")

TITLE = "If you had followed every pick"
ONE_SENTENCE = "Example account balances are not available right now, so none are shown."

BANNED = (
    (r"\bedge\b", "edge"),
    (r"\bprofit(?:s|able)?\b", "profit"),
    (r"\bwinning\b", "winning"),
    (r"beat(?:s|ing)? the market", "beat the market"),
    (r"(?i)bet[\s-]*check", "Bet Check"),
    (r"\block(?:s|ed|ing)?\b", "lock"),
    (r"\bguarantee[sd]?\b", "guaranteed"),
    (r"!", "exclamation mark"),
    (r"—", "em dash"),
)


def _string_literals(source: str) -> list:
    code = re.sub(r"/\*.*?\*/", " ", source, flags=re.S)
    code = "\n".join(line for line in code.splitlines() if not line.strip().startswith("//"))
    literals = re.findall(r'"(?:[^"\\\n]|\\.)*"|`(?:[^`\\]|\\.)*`', code)
    return [lit[1:-1] for lit in literals]


def dollars(x) -> str:
    """Dollars to the cent, half up, from the exact decimal the payload carries."""
    d = Decimal(repr(x)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    sign = "-" if d < 0 else ""
    return f"{sign}${abs(d):,.2f}"


def whole_or_cents(x) -> str:
    d = Decimal(repr(x))
    return f"${d:,.0f}" if d == d.to_integral_value() else dollars(x)


class StaticChecks(unittest.TestCase):
    def test_the_record_page_mounts_it_and_the_landing_page_does_not(self):
        self.assertIn('from "./exampleaccounts.js"', RECORD_JS)
        for name in ("landing.js", "landing-live.js"):
            self.assertNotIn("exampleaccounts", (JS / name).read_text(encoding="utf-8"))
            self.assertNotIn("/card/accounts", (JS / name).read_text(encoding="utf-8"))
        landing = (ROOT / "web" / "landing.html").read_text(encoding="utf-8")
        self.assertNotIn("followed every pick", landing)
        self.assertNotIn("/card/accounts", landing)

    def test_no_claim_word_in_anything_the_section_can_say(self):
        for literal in _string_literals(MODULE_JS):
            for pattern, label in BANNED:
                self.assertIsNone(re.search(pattern, literal, re.I if label != "lock" else 0),
                                  f"{label!r} in {literal!r}")

    def test_the_wording_the_page_falls_back_to_is_the_servers(self):
        for note in ea.NOTES:
            self.assertIn(json.dumps(note), MODULE_JS)
        self.assertIn(json.dumps(TITLE), MODULE_JS)
        self.assertIn(json.dumps(ONE_SENTENCE), MODULE_JS)
        self.assertEqual(ea.UNAVAILABLE_SENTENCE, ONE_SENTENCE)
        self.assertIn(f"MIN_GRADED_FOR_PERCENT = {ea.MIN_GRADED_FOR_PERCENT};", MODULE_JS)

    def test_no_chart_library_and_the_svg_scales_to_its_box(self):
        self.assertNotRegex(MODULE_JS, r"(?i)\bimport\b[^;]*(chart|d3|plotly|canvas)")
        self.assertIn('viewBox: `0 0 ${CHART.width} ${CHART.height}`', MODULE_JS)
        self.assertNotIn("width:", re.search(r"svgNode\(\"svg\", \{.*?\}\);", MODULE_JS, re.S).group(0))
        self.assertRegex(CARD_CSS, r"\.acct-chart \{[^}]*width: 100%")

    def test_the_table_has_five_columns_at_fixed_widths_so_a_phone_does_not_scroll(self):
        self.assertIn('["DATE", "PICKS", "W-L", "DAY", "BALANCE"]', MODULE_JS)
        self.assertRegex(CARD_CSS, r"\.acct-table \{[^}]*table-layout: fixed")
        widths = [int(w) for w in re.findall(
            r"\.acct-table th:nth-child\(\d\), \.acct-table td:nth-child\(\d\) \{ width: (\d+)%", CARD_CSS)]
        self.assertEqual(len(widths), 5)
        self.assertEqual(sum(widths), 100)
        self.assertNotRegex(CARD_CSS.split("EXAMPLE ACCOUNTS (web/js/exampleaccounts.js")[1],
                            r"min-width: ?[3-9]\d\dpx")

    def test_the_nfl_and_ufc_pages_link_to_it_with_one_link(self):
        self.assertEqual(RECORD_JS.count('"record-accounts-link"'), 1)
        self.assertIn("#/record-card?accounts=", RECORD_JS)

    def test_the_router_hands_the_accounts_query_to_the_record_page(self):
        self.assertIn("query.accounts", (JS / "main.js").read_text(encoding="utf-8"))


HARNESS = r"""
class TextNode {
  constructor(t) { this.nodeType = 3; this.textContent = String(t); this.parentNode = null; }
}
class Elem {
  constructor(tag, ns) {
    this.nodeType = 1; this.tagName = String(tag).toUpperCase(); this.ns = ns || null; this.attrs = {};
    this.childNodes = []; this.parentNode = null; this.style = {}; this.handlers = {};
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
  set textContent(v) { const t = new TextNode(v); t.parentNode = this; this.childNodes = [t]; }
  get textContent() { return this.childNodes.map((c) => c.textContent).join(""); }
  get classList() { const self = this; return { add(c) { self.attrs.class = ((self.attrs.class || "") + " " + c).trim(); }, remove() {} }; }
  addEventListener(type, fn) { (this.handlers[type] ||= []).push(fn); }
  fire(type) { for (const fn of this.handlers[type] || []) fn({ type, preventDefault() {} }); }
  _all(out) { for (const c of this.children) { out.push(c); c._all(out); } return out; }
  querySelectorAll(sel) {
    const m = sel.match(/^\[([\w-]+)(?:=(?:'([^']*)'|"([^"]*)"))?\]$/);
    if (!m) throw new Error("unsupported selector " + sel);
    const name = m[1]; const val = m[2] !== undefined ? m[2] : m[3];
    return this._all([]).filter((n) => name in n.attrs && (val === undefined || n.attrs[name] === val));
  }
  querySelector(sel) { return this.querySelectorAll(sel)[0] || null; }
}

const body = new Elem("body");
globalThis.document = {
  createElement: (t) => new Elem(t),
  createElementNS: (ns, t) => new Elem(t, ns),
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
  addEventListener() {}, dispatchEvent() { return true; }, scrollTo() {},
  crypto: globalThis.crypto,
};

const scenario = JSON.parse(process.env.SCENARIO);
const text = (n) => (n.nodeType === 3 ? n.textContent : n.childNodes.map(text).join("\n"));
const hook = (root, name) => root._all([]).filter((n) => n.attrs["data-hook"] === name);
const one = (root, name) => { const f = hook(root, name)[0]; return f ? f.textContent : null; };

function snapshot(host) {
  const buttons = host._all([]).filter((n) => n.tagName === "BUTTON").map((b) => ({
    kind: b.attrs["data-acct-account"] !== undefined ? "account" : "sport",
    value: b.attrs["data-acct-account"] !== undefined ? b.attrs["data-acct-account"] : b.attrs["data-acct-sport"],
    pressed: b.attrs["aria-pressed"], label: b.textContent,
  }));
  const rows = hook(host, "example-accounts-row").map((tr) => {
    const cells = tr.children.map((td) => td.childNodes.map(text).join("|"));
    const day = hook(tr, "example-accounts-day-result")[0];
    return { date: tr.attrs["data-date"], postseason: tr.attrs["data-postseason"], cells,
             dayClass: day.attrs.class, dayText: day.textContent,
             tags: hook(tr, "example-accounts-postseason-tag").concat(hook(tr, "example-accounts-partial-tag")).map((n) => n.textContent) };
  });
  const svg = hook(host, "example-accounts-chart")[0] || null;
  const body = hook(host, "example-accounts-body")[0] || null;
  return {
    state: (host.children[0] && host.children[0].attrs["data-state"]) || null,
    fullText: text(host),
    bodyText: body ? text(body) : null,
    title: one(host, "example-accounts-title"),
    headline: one(host, "example-accounts-headline"),
    change: one(host, "example-accounts-change"),
    counts: one(host, "example-accounts-counts"),
    percent: one(host, "example-accounts-percent"),
    small: one(host, "example-accounts-small-sample"),
    postseasonNote: one(host, "example-accounts-postseason-note"),
    pending: one(host, "example-accounts-pending"),
    low: one(host, "example-accounts-low"),
    unavailable: one(host, "example-accounts-unavailable"),
    notes: hook(host, "example-accounts-notes").flatMap((n) => n.children.map((p) => p.textContent)),
    buttons, rows, tables: hook(host, "example-accounts-table").length,
    chart: svg ? { aria: svg.attrs["aria-label"], viewBox: svg.attrs.viewBox, width: svg.attrs.width || null,
                   points: (svg.children.find((c) => c.tagName === "POLYLINE").attrs.points || "").split(" ").length,
                   role: svg.attrs.role } : null,
  };
}

const out = {};
if (scenario.kind === "section") {
  const mod = await import("./exampleaccounts.js");
  const host = new Elem("div");
  const getJson = async () => { if (scenario.fail) throw new Error("down"); return scenario.payload; };
  await mod.mountExampleAccounts(host, scenario.selection || {}, getJson);
  out.steps = [snapshot(host)];
  for (const click of scenario.clicks || []) {
    const b = host._all([]).find((n) => n.tagName === "BUTTON" && n.attrs[`data-acct-${click.kind}`] === click.value);
    if (!b) throw new Error("no such button " + JSON.stringify(click));
    b.fire("click");
    out.steps.push(snapshot(host));
  }
  out.pure = {
    money: scenario.money.map((v) => mod.money(v)),
    moneyWhole: scenario.money.map((v) => mod.money(v, { whole: true })),
    signed: scenario.money.map((v) => mod.signedMoney(v)),
    date: ["2026-09-22", "2026-10-01", "2026-11-05", "2026-06-01", "bad"].map((d) => mod.dateLabel(d)),
  };
} else if (scenario.kind === "page") {
  const { renderCardRecord } = await import("./cardrecord.js");
  const calls = [];
  globalThis.fetch = async (url) => {
    url = String(url); calls.push(url);
    let payload = {};
    if (url.startsWith("/card/record")) payload = scenario.record;
    else if (url.startsWith("/card/history")) payload = scenario.history;
    else if (url.startsWith("/card/accounts")) payload = scenario.accounts;
    if (scenario.accountsFails && url.startsWith("/card/accounts")) throw new Error("down");
    const t = JSON.stringify(payload);
    return { ok: true, status: 200, text: async () => t, json: async () => payload };
  };
  const container = new Elem("div");
  await renderCardRecord(container, scenario.options);
  await new Promise((r) => setTimeout(r, 80));
  const hooks = container._all([]).map((n) => n.attrs["data-hook"]).filter(Boolean);
  const link = hook(container, "record-accounts-link")[0] || null;
  out.hooks = hooks;
  out.calls = calls;
  out.link = link ? { href: link.attrs.href, text: link.textContent } : null;
  out.snapshot = snapshot(hook(container, "record-accounts-host")[0] || new Elem("div"));
  out.hasHost = hook(container, "record-accounts-host").length;
}
console.log("@@" + JSON.stringify(out));
"""


def _payload():
    with fixture_ledgers():
        return ea.build_payload(config(), sources(), pending=[{"sport": "mlb", "picks": 8},
                                                               {"sport": "ufc", "picks": 3}])


RECORD = {"days": 6, "wins": 16, "losses": 17, "pushes": 0, "voids": 5, "n_staked": 33,
          "profit_units": -5.0463, "win_rate": 0.4848, "roi_pct": -15.3, "chain_ok": True,
          "rows_checked": 93, "rule": "v2", "disclaimer": "d",
          "by_kind": {"game": {"n_staked": 0}, "prop": {"n_staked": 33, "wins": 16, "losses": 17}},
          "postseason": {"wins": 0, "losses": 2, "pushes": 0, "voids": 0, "n_staked": 2,
                         "profit_units": -2.0, "days": 3}}
HISTORY = {"days": [], "pending_days": [], "truncated": False, "total_days": 0, "limit": 60}
SMALL_RECORD = dict(RECORD, days=1, wins=1, losses=0, voids=0, n_staked=1, profit_units=0.9259)


@unittest.skipUnless(shutil.which("node"), "node not installed")
class TheSectionUnderNode(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        for path in JS.glob("*.js"):
            shutil.copy(path, cls._tmp.name)
        Path(cls._tmp.name, "package.json").write_text('{"type": "module"}', encoding="utf-8")
        Path(cls._tmp.name, "harness.mjs").write_text(HARNESS, encoding="utf-8")
        cls.payload = _payload()

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def run_scenario(self, **scenario):
        scenario.setdefault("money", [0])
        proc = subprocess.run(["node", "harness.mjs"], cwd=self._tmp.name,
                              env=dict(os.environ, SCENARIO=json.dumps(scenario)),
                              capture_output=True, text=True, encoding="utf-8", timeout=90)
        self.assertEqual(proc.returncode, 0, proc.stderr[-2500:])
        line = [ln for ln in proc.stdout.splitlines() if ln.startswith("@@")][-1]
        return json.loads(line[2:])

    def section(self, payload=None, **scenario):
        return self.run_scenario(kind="section", payload=self.payload if payload is None else payload, **scenario)

    # ---- the headline is the payload's own numbers -------------------------

    def test_the_headline_sentence_uses_the_numbers_in_the_payload_for_every_account_and_sport(self):
        by_id = {a["id"]: a for a in self.payload["accounts"]}
        clicks = [c for a in self.payload["accounts"] for c in (
            {"kind": "account", "value": a["id"]},
            *({"kind": "sport", "value": s} for s in ("mlb", "nfl", "ufc", "all")))]
        out = self.section(selection={"account": "flat100", "sport": "mlb"}, clicks=clicks)
        account, view, seen = "flat100", "mlb", set()
        for click, step in zip(clicks, out["steps"][1:]):
            if click["kind"] == "account":
                account = click["value"]
            else:
                view = click["value"]
            series = by_id[account]["series"][view]
            expected = (f"Started with {whole_or_cents(series['start_balance'])} on Sept 22. "
                        f"Now {dollars(series['final_balance'])}.")
            self.assertEqual(step["headline"], expected, (account, view))
            seen.add((account, view))
        self.assertEqual(len(seen), 16)

    def test_the_headline_matches_the_owners_example_shape_with_the_real_balance(self):
        out = self.section(selection={"account": "flat100", "sport": "mlb"})
        self.assertEqual(out["steps"][0]["headline"], "Started with $10,000 on Sept 22. Now $9,295.37.")

    def test_the_starter_account_says_its_own_start(self):
        out = self.section(selection={"account": "starter", "sport": "all"})
        self.assertEqual(out["steps"][0]["headline"], "Started with $1,000 on Sept 22. Now $963.82.")

    def test_a_half_cent_rounds_up_at_display_and_the_balance_itself_is_not_rounded(self):
        # flat $250 over all sports ends at exactly $9,095.575
        series = [a for a in self.payload["accounts"] if a["id"] == "flat250"][0]["series"]["all"]
        self.assertEqual(series["final_balance"], 9095.575)
        out = self.section(selection={"account": "flat250", "sport": "all"})
        self.assertEqual(out["steps"][0]["headline"], "Started with $10,000 on Sept 22. Now $9,095.58.")

    def test_money_formatting_is_cents_with_commas_and_an_explicit_sign(self):
        values = [0, 1234.5, -354.43, 9295.375, 10000, -0.004, 1000000.1]
        out = self.section(money=values)["pure"]
        self.assertEqual(out["money"], ["$0.00", "$1,234.50", "-$354.43", "$9,295.38", "$10,000.00",
                                        "$0.00", "$1,000,000.10"])
        self.assertEqual(out["moneyWhole"][4], "$10,000")
        self.assertEqual(out["moneyWhole"][1], "$1,234.50")
        self.assertEqual(out["signed"], ["$0.00", "+$1,234.50", "-$354.43", "+$9,295.38", "+$10,000.00",
                                         "$0.00", "+$1,000,000.10"])
        self.assertEqual(out["date"], ["Sept 22", "Oct 1", "Nov 5", "June 1", "bad"])

    # ---- switching redraws -------------------------------------------------

    def test_it_opens_on_all_sports_for_the_first_account_by_default(self):
        step = self.section()["steps"][0]
        self.assertEqual(step["title"], TITLE)
        pressed = {(b["kind"], b["value"]) for b in step["buttons"] if b["pressed"] == "true"}
        self.assertEqual(pressed, {("account", "flat100"), ("sport", "all")})
        self.assertEqual(step["headline"], "Started with $10,000 on Sept 22. Now $9,638.23.")

    def test_the_selection_in_the_address_opens_that_sport(self):
        step = self.section(selection={"sport": "ufc"})["steps"][0]
        self.assertEqual(step["headline"], "Started with $10,000 on Sept 22. Now $10,250.27.")
        step = self.section(selection={"sport": "not-a-sport", "account": "nope"})["steps"][0]
        pressed = {(b["kind"], b["value"]) for b in step["buttons"] if b["pressed"] == "true"}
        self.assertEqual(pressed, {("account", "flat100"), ("sport", "all")})

    def test_clicking_an_account_or_a_sport_redraws_the_numbers_and_the_pressed_buttons(self):
        out = self.section(clicks=[{"kind": "sport", "value": "mlb"},
                                   {"kind": "account", "value": "flat250"},
                                   {"kind": "sport", "value": "nfl"},
                                   {"kind": "account", "value": "pct1"}])
        heads = [s["headline"] for s in out["steps"]]
        self.assertEqual(heads, [
            "Started with $10,000 on Sept 22. Now $9,638.23.",       # flat100, all
            "Started with $10,000 on Sept 22. Now $9,295.37.",       # flat100, mlb
            "Started with $10,000 on Sept 22. Now $8,238.43.",       # flat250, mlb: $8,238.425, half a cent up
            "Started with $10,000 on Sept 22. Now $10,231.48.",      # flat250, nfl
            "Started with $10,000 on Sept 22. Now $10,092.59.",      # pct1, nfl (one win, compounding irrelevant)
        ])
        last = out["steps"][-1]
        pressed = {(b["kind"], b["value"]) for b in last["buttons"] if b["pressed"] == "true"}
        self.assertEqual(pressed, {("account", "pct1"), ("sport", "nfl")})
        self.assertEqual(len([b for b in last["buttons"] if b["pressed"] == "true"]), 2)
        self.assertEqual(len(last["buttons"]), 8)      # four accounts, four sports: plain buttons

    def test_the_day_table_is_redrawn_for_the_sport_chosen(self):
        out = self.section(clicks=[{"kind": "sport", "value": "mlb"}, {"kind": "sport", "value": "ufc"}])
        all_rows, mlb_rows, ufc_rows = (len(s["rows"]) for s in out["steps"])
        self.assertEqual((all_rows, mlb_rows, ufc_rows), (7, 5, 2))
        self.assertEqual([r["date"] for r in out["steps"][2]["rows"]], ["2026-09-22", "2026-09-26"])

    # ---- a loss is a loss --------------------------------------------------

    def test_a_losing_account_reads_down_with_a_minus_sign_and_the_same_weight_as_a_gain(self):
        step = self.section(selection={"account": "flat100", "sport": "mlb"})["steps"][0]
        self.assertEqual(step["change"], "Down $704.63 since the start.")
        self.assertEqual(step["counts"], "40 picks over 5 days: 16 won, 19 lost, 5 void.")
        by_date = {r["date"]: r for r in step["rows"]}
        loss = by_date["2026-09-22"]
        self.assertEqual(loss["dayText"], "-$514.40")
        self.assertIn("acct-neg", loss["dayClass"])
        self.assertNotIn("acct-pos", loss["dayClass"])
        gain = by_date["2026-09-23"]
        self.assertEqual(gain["dayText"], "+$19.27")
        self.assertIn("acct-pos", gain["dayClass"])
        # same element, same class family, no smaller type for the loss
        self.assertTrue(loss["dayClass"].startswith("acct-table__day") and gain["dayClass"].startswith("acct-table__day"))
        self.assertEqual(by_date["2026-10-01"]["dayText"], "-$200.00")

    def test_a_winning_sport_reads_up(self):
        step = self.section(selection={"account": "flat100", "sport": "ufc"})["steps"][0]
        self.assertEqual(step["change"], "Up $250.27 since the start.")

    def test_a_row_shows_wins_losses_and_pushes_or_voids_only_when_there_are_some(self):
        rows = {r["date"]: r for r in self.section(selection={"sport": "mlb"})["steps"][0]["rows"]}
        self.assertEqual(rows["2026-09-22"]["cells"][2], "8-11|2 void")
        self.assertEqual(rows["2026-10-01"]["cells"][2], "0-2")          # nothing to add

    def test_the_lowest_balance_is_stated_and_a_never_below_start_is_said_plainly(self):
        steps = self.section(selection={"sport": "mlb"}, clicks=[{"kind": "sport", "value": "ufc"}])["steps"]
        self.assertEqual(steps[0]["low"], "Lowest balance at the end of a day: $9,295.37 on Oct 1.")
        self.assertEqual(steps[1]["low"], "The balance never fell below the starting balance at the end of a day.")

    # ---- postseason, pending, notes ---------------------------------------

    def test_postseason_days_are_tagged_and_the_one_sentence_says_why_the_total_differs(self):
        mlb = self.section(selection={"sport": "mlb"})["steps"][0]
        tagged = [r["date"] for r in mlb["rows"] if r["postseason"] == "true"]
        self.assertEqual(tagged, ["2026-10-01"])
        self.assertEqual([r["tags"] for r in mlb["rows"] if r["postseason"] == "true"], [["Postseason"]])
        self.assertEqual(mlb["postseasonNote"], ea.POSTSEASON_NOTE)
        for view in ("nfl", "ufc"):
            step = self.section(selection={"sport": view})["steps"][0]
            self.assertIsNone(step["postseasonNote"], view)
            self.assertTrue(all(r["postseason"] == "false" for r in step["rows"]))
        self.assertEqual(self.section(selection={"sport": "all"})["steps"][0]["postseasonNote"], ea.POSTSEASON_NOTE)

    def test_the_three_notes_are_always_on_the_page(self):
        for sport in ("mlb", "nfl", "ufc", "all"):
            with self.subTest(sport=sport):
                notes = self.section(selection={"sport": sport})["steps"][0]["notes"]
                self.assertEqual(notes, list(ea.NOTES))

    def test_the_notes_survive_a_payload_that_forgot_them(self):
        payload = {k: v for k, v in self.payload.items() if k != "notes"}
        self.assertEqual(self.section(payload=payload)["steps"][0]["notes"], list(ea.NOTES))

    def test_pending_picks_are_a_count_in_the_view_they_belong_to(self):
        steps = self.section(selection={"sport": "all"}, clicks=[
            {"kind": "sport", "value": "mlb"}, {"kind": "sport", "value": "nfl"}])["steps"]
        self.assertEqual(steps[0]["pending"],
                         "Published and waiting on their games, so in no balance yet: 8 MLB picks, 3 UFC picks.")
        self.assertEqual(steps[1]["pending"],
                         "Published and waiting on their games, so in no balance yet: 8 MLB picks.")
        self.assertIsNone(steps[2]["pending"])

    def test_a_partly_settled_day_is_tagged(self):
        payload = json.loads(json.dumps(self.payload))
        for a in payload["accounts"]:
            for s in a["series"].values():
                s["daily"][-1]["partial"] = True
        step = self.section(payload=payload, selection={"sport": "mlb"})["steps"][0]
        self.assertEqual(step["rows"][-1]["tags"][-1], "Some picks still waiting")

    # ---- the one sentence --------------------------------------------------

    def _assert_only_the_sentence(self, step):
        self.assertEqual(step["state"], "unavailable")
        self.assertEqual(step["unavailable"], ONE_SENTENCE)
        self.assertEqual(step["title"], TITLE)
        self.assertEqual(step["buttons"], [])
        self.assertEqual(step["rows"], [])
        self.assertEqual(step["tables"], 0)
        self.assertIsNone(step["chart"])
        self.assertIsNone(step["headline"])
        self.assertIsNone(step["notes"] and step["notes"][0] if step["notes"] else None)
        self.assertNotIn("$", step["fullText"])
        self.assertEqual(step["fullText"].replace("\n", " ").strip(), f"{TITLE} {ONE_SENTENCE}")

    def test_an_unavailable_payload_is_one_plain_sentence_and_no_balance(self):
        for payload in (
            {"available": False, "reason": "The account totals did not match the published record for MLB, "
                                           "so nothing is shown.",
             "reconciled": {"mlb": {"ok": False, "problems": ["counted record: wins 16 against 17"]}}},
            {"available": False},
            {},
            None,
            {"available": "yes"},
            {"available": True, "accounts": []},
        ):
            with self.subTest(payload=payload):
                self._assert_only_the_sentence(self.run_scenario(kind="section", payload=payload)["steps"][0])

    def test_the_reason_is_never_shown_to_a_reader(self):
        step = self.run_scenario(kind="section", payload={
            "available": False, "reason": "wins 16 against 17 in the record"})["steps"][0]
        self.assertNotIn("against", step["fullText"])
        self.assertNotIn("wins", step["fullText"])

    def test_a_failed_request_is_the_same_one_sentence(self):
        self._assert_only_the_sentence(self.run_scenario(kind="section", payload=None, fail=True)["steps"][0])

    def test_a_payload_missing_a_series_is_the_one_sentence_not_a_half_drawn_page(self):
        payload = json.loads(json.dumps(self.payload))
        del payload["accounts"][0]["series"]
        self._assert_only_the_sentence(self.section(payload=payload)["steps"][0])

    # ---- no percentage for a small sample ----------------------------------

    def test_ufc_and_nfl_say_how_few_have_been_graded_and_print_no_percentage(self):
        ufc = self.section(selection={"sport": "ufc"})["steps"][0]
        self.assertEqual(ufc["small"],
                         "Only 6 UFC picks have been graded. That is too few to show a return as a "
                         "percentage, so read the dollars and the count until there are more.")
        nfl = self.section(selection={"sport": "nfl"})["steps"][0]
        self.assertEqual(nfl["small"],
                         "Only 1 NFL pick has been graded. That is too few to show a return as a "
                         "percentage, so read the dollars and the count until there are more.")
        for step in (ufc, nfl):
            self.assertIsNone(step["percent"])
            self.assertNotIn("%", step["bodyText"])

    def test_a_percentage_is_printed_once_there_are_thirty_graded_picks(self):
        mlb = self.section(selection={"sport": "mlb"})["steps"][0]
        self.assertEqual(mlb["percent"], "Return on the starting balance: -7.05%.")
        self.assertIsNone(mlb["small"])
        allsports = self.section(selection={"sport": "all"})["steps"][0]
        self.assertEqual(allsports["percent"], "Return on the starting balance: -3.62%.")
        self.assertIsNone(allsports["small"])

    def test_the_page_checks_the_floor_itself_even_if_the_server_sent_a_percentage(self):
        payload = json.loads(json.dumps(self.payload))
        for a in payload["accounts"]:
            a["series"]["ufc"]["return_pct"] = 2.5          # a server that forgot the rule
            a["series"]["nfl"]["return_pct"] = 9.26
        for view in ("ufc", "nfl"):
            step = self.section(payload=payload, selection={"sport": view})["steps"][0]
            self.assertIsNone(step["percent"], view)
            self.assertNotIn("%", step["bodyText"])
            self.assertIsNotNone(step["small"])

    def test_the_floor_is_the_payloads_when_it_sends_one(self):
        payload = json.loads(json.dumps(self.payload))
        payload["min_graded_for_percent"] = 50
        step = self.section(payload=payload, selection={"sport": "mlb"})["steps"][0]
        self.assertIsNone(step["percent"])
        self.assertIn("Only 35 MLB picks have been graded.", step["small"])

    def test_an_empty_sport_says_nothing_has_been_graded_and_draws_no_chart(self):
        payload = json.loads(json.dumps(self.payload))
        for a in payload["accounts"]:
            s = a["series"]["nfl"]
            s.update(daily=[], picks=0, wins=0, losses=0, pushes=0, voids=0, graded=0, days=0,
                     final_balance=s["start_balance"], total_units=0.0, return_pct=None)
        step = self.section(payload=payload, selection={"sport": "nfl"})["steps"][0]
        self.assertEqual(step["headline"], "Started with $10,000 on Sept 22. Now $10,000.00.")
        self.assertEqual(step["change"], "No change since the start.")
        self.assertEqual(step["counts"], "No pick has been graded in this view yet.")
        self.assertIsNone(step["chart"])
        self.assertEqual(step["rows"], [])
        self.assertIsNone(step["percent"])
        self.assertIsNone(step["small"])

    # ---- the balance line --------------------------------------------------

    def test_the_balance_line_is_an_inline_svg_that_scales_and_says_what_it_shows(self):
        step = self.section(selection={"account": "flat100", "sport": "mlb"})["steps"][0]
        chart = step["chart"]
        self.assertEqual(chart["viewBox"], "0 0 320 120")
        self.assertIsNone(chart["width"])
        self.assertEqual(chart["role"], "img")
        self.assertEqual(chart["points"], 6)                    # the start, then five days
        self.assertEqual(chart["aria"], "Balance after each day, from $10,000 to $9,295.37.")


@unittest.skipUnless(shutil.which("node"), "node not installed")
class TheRecordPageCarriesIt(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        for path in JS.glob("*.js"):
            shutil.copy(path, cls._tmp.name)
        Path(cls._tmp.name, "package.json").write_text('{"type": "module"}', encoding="utf-8")
        Path(cls._tmp.name, "harness.mjs").write_text(HARNESS, encoding="utf-8")
        cls.payload = _payload()

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def page(self, options=None, record=None, **extra):
        scenario = dict(kind="page", options=options or {}, record=record or RECORD, history=HISTORY,
                        accounts=self.payload, money=[0], **extra)
        proc = subprocess.run(["node", "harness.mjs"], cwd=self._tmp.name,
                              env=dict(os.environ, SCENARIO=json.dumps(scenario)),
                              capture_output=True, text=True, encoding="utf-8", timeout=90)
        self.assertEqual(proc.returncode, 0, proc.stderr[-2500:])
        line = [ln for ln in proc.stdout.splitlines() if ln.startswith("@@")][-1]
        return json.loads(line[2:])

    def test_the_mlb_record_page_has_the_section_under_the_record_numbers(self):
        out = self.page()
        hooks = out["hooks"]
        self.assertEqual(out["hasHost"], 1)
        self.assertIn("/card/accounts", out["calls"])
        self.assertEqual(out["snapshot"]["title"], TITLE)
        self.assertEqual(out["snapshot"]["headline"], "Started with $10,000 on Sept 22. Now $9,638.23.")
        self.assertLess(hooks.index("record-headline"), hooks.index("record-accounts-host"))
        self.assertLess(hooks.index("record-voids-note"), hooks.index("record-accounts-host"))
        self.assertLess(hooks.index("record-accounts-host"), hooks.index("record-chain"))
        self.assertNotIn("record-accounts-link", hooks)

    def test_the_page_asks_for_the_accounts_after_the_record_so_it_reads_what_is_cached(self):
        calls = self.page()["calls"]
        self.assertLess(max(i for i, c in enumerate(calls) if c.startswith("/card/record")),
                        calls.index("/card/accounts"))
        self.assertLess(max(i for i, c in enumerate(calls) if c.startswith("/card/history")),
                        calls.index("/card/accounts"))

    def test_the_address_can_open_it_on_a_sport(self):
        out = self.page({"accounts": "nfl"})
        self.assertEqual(out["snapshot"]["headline"], "Started with $10,000 on Sept 22. Now $10,092.59.")
        out = self.page({"accounts": "garbage"})
        self.assertEqual(out["snapshot"]["headline"], "Started with $10,000 on Sept 22. Now $9,638.23.")

    def test_a_failing_accounts_request_cannot_break_the_record_page(self):
        out = self.page(accountsFails=True)
        self.assertIn("record-headline", out["hooks"])
        self.assertEqual(out["snapshot"]["state"], "unavailable")
        self.assertEqual(out["snapshot"]["unavailable"], ONE_SENTENCE)

    def test_the_nfl_and_ufc_record_pages_carry_one_link_and_not_the_section(self):
        for options, key in (({"sport": "nfl"}, "nfl"), ({"sport": "mma"}, "ufc")):
            with self.subTest(sport=key):
                out = self.page(options, record=SMALL_RECORD)
                self.assertEqual(out["link"], {"href": f"#/record-card?accounts={key}",
                                               "text": "IF YOU HAD FOLLOWED EVERY PICK →"})
                self.assertEqual(out["hooks"].count("record-accounts-link"), 1)
                self.assertEqual(out["hasHost"], 0)
                self.assertNotIn("/card/accounts", out["calls"])

    def test_the_retired_rules_pages_have_neither(self):
        for options in ({"rule": "v1"}, {"sport": "nfl", "rule": "NFL_CARD_V1"}):
            with self.subTest(options=options):
                out = self.page(options, record=dict(RECORD, rule=options["rule"]))
                self.assertEqual(out["hasHost"], 0)
                self.assertIsNone(out["link"])


if __name__ == "__main__":
    unittest.main()
