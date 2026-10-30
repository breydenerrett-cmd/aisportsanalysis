"""The Analyze report's screen (web/js/analyze-report.js, web/css/analyze-report.css), run for real under node against a small fake DOM.

The data is a real report built by src/hounds/analyze_report.py from the 16-7 fixture (not typed in), so the screen is held to what the
server sends: the gauge reads the server's meter and says so to a screen reader, the teaser is ONE locked panel with nothing blurred
behind it, an expand idea's button announces itself with a CustomEvent and changes nothing, and a missing sibling (the pick meters, the
grades) is a quieter screen and never an error.
"""

from __future__ import annotations

import json
import re
import unittest
from contextlib import contextmanager
from pathlib import Path

from src.hounds import analyze_report as A
from tests import hounds_web_runner as R
from tests.hounds_web_runner import HAS_NODE, run_js
from tests.test_analyze_report import NOW, ROWS, HID, clv_book, clv_pairs, counts_by_ceiling, dog

ROOT = Path(__file__).resolve().parent.parent
JS = (ROOT / "web" / "js" / "analyze-report.js").read_text(encoding="utf-8")
CSS = (ROOT / "web" / "css" / "analyze-report.css").read_text(encoding="utf-8")

DOM = r'''
class Txt { constructor(t) { this.nodeType = 3; this.text = String(t); this.parentNode = null; } get textContent() { return this.text; } set textContent(v) { this.text = String(v); } }
class El {
  constructor(tag) { this.nodeType = 1; this.tag = tag; this.attrs = {}; this.childNodes = []; this.parentNode = null; this.listeners = {}; this.style = {}; }
  get firstChild() { return this.childNodes[0] || null; }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; }
  removeAttribute(k) { delete this.attrs[k]; }
  hasAttribute(k) { return k in this.attrs; }
  appendChild(c) { if (c.parentNode) c.parentNode.removeChild(c); c.parentNode = this; this.childNodes.push(c); return c; }
  removeChild(c) { const i = this.childNodes.indexOf(c); if (i >= 0) this.childNodes.splice(i, 1); c.parentNode = null; return c; }
  set textContent(v) { this.childNodes = []; if (String(v) !== "") { const t = new Txt(v); t.parentNode = this; this.childNodes.push(t); } }
  get textContent() { return this.childNodes.map((c) => c.textContent).join(""); }
  addEventListener(t, f) { (this.listeners[t] ||= []).push(f); }
  click() { this.dispatchEvent(new Event("click")); }
  dispatchEvent(evt) {
    for (let n = this; n; n = n.parentNode) for (const f of (n.listeners && n.listeners[evt.type]) || []) f.call(n, evt);
    if (evt.bubbles) for (const f of globalThis.window.listeners[evt.type] || []) f.call(globalThis.window, evt);
    return true;
  }
  querySelectorAll(sel) { const out = []; const m = /^(?:(\w+))?(?:\[([\w-]+)(?:="([^"]*)")?\])?$/.exec(sel); if (!m) return out; walk(this, (n) => { if (n !== this && match(n, m)) out.push(n); }); return out; }
  querySelector(sel) { return this.querySelectorAll(sel)[0] || null; }
}
const match = (n, m) => (!m[1] || n.tag === m[1]) && (!m[2] || (m[2] in n.attrs && (m[3] === undefined || n.attrs[m[2]] === m[3])));
const walk = (n, f) => { if (n && n.nodeType === 1) { f(n); n.childNodes.forEach((k) => walk(k, f)); } };
const find = (root, pred) => { const out = []; walk(root, (n) => { if (pred(n)) out.push(n); }); return out; };
const byHook = (root, hook) => find(root, (n) => n.attrs["data-hook"] === hook);
const byClass = (root, cls) => find(root, (n) => (n.attrs.class || "").split(/\s+/).includes(cls));
globalThis.window = Object.assign(globalThis.window || {}, { listeners: {}, addEventListener(t, f) { (this.listeners[t] ||= []).push(f); } });
const head = new El("head");
const body = new El("body");
globalThis.document = { head, body, createElement: (t) => new El(t), createElementNS: (ns, t) => new El(t), createTextNode: (t) => new Txt(t),
  querySelector: (sel) => head.querySelector(sel) || body.querySelector(sel) };
const text = (n) => n.textContent;
'''


def report(full=True, *, owner=True, grades=None, clv=None, reviews=False, board=True, rows=ROWS, d=None):
    d = d or dog()
    base = A.build_report(d, rows, now=NOW, book=clv_book(clv) if clv else None)
    picks = base["picks"]
    kw = {}
    if grades:
        kw["grades"] = {picks[0]["bet_id"]: grades, picks[1]["bet_id"]: {"value": {"score": 40}}}
    if reviews:
        kw["postmortems"] = {picks[0]["bet_id"]: {"lesson": "The bullpen decided it late.", "luck_vs_process": "mixed"}}
    out = A.build_report(d, rows, now=NOW, full=full, book=clv_book(clv) if clv else None, board_fn=counts_by_ceiling if board else None, **kw)
    out = A.teaser_variant(out, owner=owner)
    out["viewer"] = {"signed_in": True, "is_owner": owner, "full": full}
    return out


REAL = "real"


@contextmanager
def meters_module(source=None):
    """What web/js/pick-meters.js is in the node work directory while a snippet runs: absent (``None``, the default: the report is held to
    its text-chip fallback), the real module (``REAL``: the page as it ships), or a stub's source. The real file is ALWAYS put back.

    The module exists now (src/hounds/pick_grades.py's meters). These tests were written when it did not, so they hid it by assuming it was
    missing, and a stub they wrote and then unlinked deleted the real file from the per-process work directory, which broke every
    later kennel page test in the same process (the whole sharded suite, 2026-10-29)."""
    path = R._workdir() / "pick-meters.js"
    original = path.read_bytes() if path.exists() else None
    try:
        if source is None:
            path.unlink(missing_ok=True)
        elif source != REAL:
            path.write_text(source, encoding="utf-8")
        yield
    finally:
        if original is None:
            path.unlink(missing_ok=True)
        else:
            path.write_bytes(original)


def js(body: str, rep=None, api=None, meters=None):
    with meters_module(meters):
        return _run(body, rep, api)


def _run(body: str, rep=None, api=None):
    rep_json = json.dumps(rep if rep is not None else report())
    setup = f'''
const REPORT = {rep_json};
const calls = [];
const apiGet = {api or "async (path) => { calls.push(path); return REPORT; }"};
const A = await import("./analyze-report.js");
const box = new El("div");
body.appendChild(box);
'''
    return run_js(DOM + setup + body)


GRADES = {"value": {"score": 71, "label": "Fair", "reason": "r"}, "confidence": {"score": 60, "label": "Medium"}, "clv": {"score": None}}


@unittest.skipUnless(HAS_NODE, "node not installed")
class TheFullReport(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        rep = report(grades=GRADES, clv=clv_pairs(21, 14), reviews=True)
        cls.rep = rep
        cls.out = js('''
const res = await A.mountAnalyze(box, { dogId: "u-drakeo", apiGet });
const hooks = (h) => byHook(box, h).length;
const gauge = byHook(box, "analyze-gauge")[0];
console.log(JSON.stringify({ res, calls,
  tier: byHook(box, "analyze-report")[0].attrs["data-tier"],
  headline: text(byHook(box, "analyze-headline")[0]),
  verdict: text(byHook(box, "analyze-verdict")[0]), hot: text(byHook(box, "analyze-hot-text")[0]),
  gauge: { role: gauge.attrs.role, min: gauge.attrs["aria-valuemin"], max: gauge.attrs["aria-valuemax"], now: gauge.attrs["aria-valuenow"], vt: gauge.attrs["aria-valuetext"], label: gauge.attrs["aria-label"] },
  angle: byClass(box, "ar-needle")[0].attrs["data-angle"], style: byClass(box, "ar-needle")[0].attrs.style,
  chips: byHook(box, "analyze-chips")[0].childNodes.map(text),
  winning: byHook(box, "analyze-winning")[0].textContent, losing: byHook(box, "analyze-losing-none").length,
  drivers: byHook(box, "analyze-driver").length, samples: byHook(box, "analyze-sample").map(text),
  picks: byHook(box, "analyze-pick").length, grades: byHook(box, "analyze-grade").map(text), meters: hooks("analyze-meters"),
  hind: byHook(box, "analyze-hindsight").map(text), hindNote: hooks("analyze-hindsight-note"),
  keep: text(byHook(box, "analyze-keep")[0]), expands: byHook(box, "analyze-expand").map((e) => e.attrs["data-id"]),
  today: byHook(box, "analyze-today").map(text),
  coach: text(byHook(box, "analyze-coach-text")[0]), coachLabel: text(byHook(box, "analyze-coach-label")[0]),
  locked: hooks("analyze-locked"), links: find(head, (n) => n.tag === "link").map((n) => n.attrs.href) }));
''', rep)

    def test_it_draws_the_servers_headline_verdict_and_words(self):
        o = self.out
        self.assertEqual((o["res"], o["tier"], o["calls"]), ({"ok": True, "tier": "full"}, "full", [f"/hounds/u-drakeo/report"]))
        self.assertEqual(o["headline"], self.rep["headline"])
        self.assertEqual((o["verdict"], o["hot"]), (self.rep["hot_hand"]["verdict_label"], self.rep["hot_hand"]["text"]))

    def test_the_gauge_is_a_meter_that_a_screen_reader_can_read(self):
        g = self.out["gauge"]
        hot = self.rep["hot_hand"]
        self.assertEqual((g["role"], g["min"], g["max"], g["now"]), ("meter", "0", "100", str(hot["meter"])))
        self.assertEqual(g["label"], "Hot hand or hot dice?")
        self.assertEqual(g["vt"], f"{hot['meter']} out of 100: {hot['meter_label']}")
        self.assertEqual(self.out["angle"], str(round(hot["meter"] / 100 * 180 - 90)))
        self.assertEqual(self.out["style"], f"--ar-angle:{self.out['angle']}deg")

    def test_the_chips_are_the_servers_numbers(self):
        chips = self.out["chips"]
        hot = self.rep["hot_hand"]
        self.assertIn("Wins16", chips)
        self.assertIn(f"Prices expected{hot['expected_w']:.1f}", chips)
        self.assertIn(f"A record this good, by luck1 in {hot['luck_check']['one_in']}", chips)
        self.assertIn("Beat the closing line14 of 21", chips)

    def test_drivers_tickets_keep_expand_and_coach_are_there(self):
        o = self.out
        self.assertIn("10-4", o["winning"])
        self.assertEqual(o["losing"], 1)                                   # nothing is clearly losing in this fixture
        self.assertEqual(o["drivers"], len(self.rep["drivers"]["winning"]))
        self.assertTrue(all(re.search(r"^\d+ bets? · ", s) for s in o["samples"]), o["samples"])
        self.assertEqual(o["picks"], 23)
        self.assertIn("Its rule has not changed in 23 bets", o["keep"])
        self.assertEqual(o["expands"], [i["id"] for i in self.rep["expand"]["items"]])
        self.assertTrue(all("On today's board" in t for t in o["today"]) and o["today"])
        self.assertEqual(o["coach"], self.rep["coach_read"]["text"])
        self.assertEqual(o["coachLabel"], "Coach\u2019s read \u2014 from the numbers above")
        self.assertEqual(o["locked"], 0)

    def test_grades_fall_back_to_text_chips_without_the_meters_module(self):
        self.assertEqual(self.out["meters"], 0)
        self.assertEqual(self.out["grades"], ["C 60 \u00b7 V 71", "V 40"])

    def test_a_hindsight_line_is_labelled_and_the_note_is_shown(self):
        self.assertEqual(len(self.out["hind"]), 1)
        self.assertTrue(self.out["hind"][0].startswith("Hindsight review: The bullpen decided it late."))
        self.assertEqual(self.out["hindNote"], 1)

    def test_one_stylesheet_link_is_inserted(self):
        self.assertEqual(self.out["links"], ["css/analyze-report.css"])


@unittest.skipUnless(HAS_NODE, "node not installed")
class TheTeaser(unittest.TestCase):
    def teaser(self, owner):
        rep = report(full=False, owner=owner, grades=GRADES)
        out = js('''
await A.mountAnalyze(box, { dogId: "u-drakeo", apiGet });
const locked = byHook(box, "analyze-locked")[0];
console.log(JSON.stringify({ tier: byHook(box, "analyze-report")[0].attrs["data-tier"],
  panels: byHook(box, "analyze-locked").length, keys: byHook(box, "analyze-locked-list")[0].childNodes.map((n) => n.attrs["data-key"]),
  words: byHook(box, "analyze-locked-list")[0].childNodes.map(text), line: text(byHook(box, "analyze-upgrade-line")[0]),
  upgrade: byHook(box, "analyze-upgrade").map((n) => n.attrs.href),
  paid: ["analyze-drivers", "analyze-keep", "analyze-expand-block", "analyze-coach"].map((h) => byHook(box, h).length),
  blur: find(box, (n) => /blur/.test(n.attrs.style || "") || /blur/.test(n.attrs.class || "")).length,
  headline: byHook(box, "analyze-headline").length, gauge: byHook(box, "analyze-gauge").length, picks: byHook(box, "analyze-pick").length,
  grades: byHook(box, "analyze-grade").length }));
''', rep)
        return rep, out

    def test_the_owner_sees_one_panel_that_lists_what_is_inside_and_a_way_to_the_plan(self):
        rep, o = self.teaser(True)
        self.assertEqual((o["tier"], o["panels"]), ("teaser", 1))
        self.assertEqual(o["keys"], ["drivers", "keep_it_up", "expand", "coach_read"])
        self.assertEqual(len(o["words"]), 4)
        self.assertEqual(o["line"], rep["upgrade"]["line"])
        self.assertEqual(o["upgrade"], ["index.html#/billing"])
        self.assertEqual(o["paid"], [0, 0, 0, 0])
        self.assertEqual(o["blur"], 0)
        self.assertEqual((o["headline"], o["gauge"], o["picks"]), (1, 1, 23))

    def test_a_visitor_gets_the_same_panel_without_a_sales_link(self):
        rep, o = self.teaser(False)
        self.assertEqual((o["panels"], o["upgrade"]), (1, []))
        self.assertIn("owner", o["line"])

    def test_the_free_part_still_shows_the_grades(self):
        _rep, o = self.teaser(True)
        self.assertEqual(o["grades"], 2)


@unittest.skipUnless(HAS_NODE, "node not installed")
class TheExpandButtons(unittest.TestCase):
    def test_a_button_announces_the_idea_and_changes_nothing(self):
        o = js('''
await A.mountAnalyze(box, { dogId: "u-drakeo", apiGet });
const heard = []; const onBox = [];
globalThis.window.addEventListener("linehound:analyze-expand", (e) => heard.push(e.detail));
box.addEventListener("linehound:analyze-expand", (e) => onBox.push(e.detail));
const buttons = byHook(box, "analyze-expand-go");
buttons[0].click();
const spin = buttons[buttons.length - 1];
spin.click();
console.log(JSON.stringify({ n: buttons.length, heard, onBox, labels: buttons.map(text), callsAfter: calls.length }));
''')
        ids = [i["id"] for i in report()["expand"]["items"]]
        self.assertEqual(o["n"], len(ids))
        self.assertEqual(o["heard"][0], {"dogId": "u-drakeo", "id": ids[0]})
        self.assertEqual(o["onBox"][0], {"dogId": "u-drakeo", "id": ids[0]})
        self.assertEqual(o["heard"][1], {"dogId": "u-drakeo", "id": "spin_off", "href": f"build-a-hound.html?from={HID}"})
        self.assertEqual(o["labels"][0], "Review this change")
        self.assertEqual(o["labels"][-1], "Start a copy")
        self.assertEqual(o["callsAfter"], 1)                                # a click sent nothing to the server

    def test_the_screen_never_posts_anything(self):
        self.assertNotRegex(JS, r"apiPost|apiDelete|method:\s*[\"'](POST|PUT|DELETE)")


@unittest.skipUnless(HAS_NODE, "node not installed")
class TheSiblings(unittest.TestCase):
    def test_no_grades_means_no_chips_and_no_error(self):
        o = js('''
await A.mountAnalyze(box, { dogId: "u-drakeo", apiGet });
console.log(JSON.stringify({ grades: byHook(box, "analyze-grade").length, meters: byHook(box, "analyze-meters").length, picks: byHook(box, "analyze-pick").length, err: byHook(box, "analyze-error").length }));
''')
        self.assertEqual(o, {"grades": 0, "meters": 0, "picks": 23, "err": 0})

    STUB = ('export function renderPickMeters(grades, opts) { const n = document.createElement("div"); n.setAttribute("data-compact", String(!!opts.compact)); '
            'n.textContent = "meters:" + (grades.confidence ? grades.confidence.score : "-"); return n; }')

    def test_the_pick_meters_module_is_used_when_it_exists_and_a_broken_one_falls_back(self):
        rep = report(grades=GRADES)
        o = js('''
await A.mountAnalyze(box, { dogId: "u-drakeo", apiGet });
console.log(JSON.stringify({ meters: byHook(box, "analyze-meters").map(text), compact: byHook(box, "analyze-meters").map((m) => m.firstChild.attrs["data-compact"]), grades: byHook(box, "analyze-grade").length }));
''', rep, meters=self.STUB)
        self.assertEqual(o["meters"][0], "meters:60")
        self.assertEqual(set(o["compact"]), {"true"})
        self.assertEqual(o["grades"], 0)
        o = js('''
await A.mountAnalyze(box, { dogId: "u-drakeo", apiGet });
console.log(JSON.stringify({ meters: byHook(box, "analyze-meters").length, grades: byHook(box, "analyze-grade").map(text) }));
''', rep, meters='export function renderPickMeters() { throw new Error("broken"); }')
        self.assertEqual((o["meters"], o["grades"][0]), (0, "C 60 \u00b7 V 71"))

    def test_the_real_pick_meters_module_draws_the_reports_grades_as_meters(self):
        """The page as it ships: the same web/js/pick-meters.js the tickets use, so a pick reads the same meters in the report."""
        rep = report(grades=GRADES)
        o = js('''
await A.mountAnalyze(box, { dogId: "u-drakeo", apiGet });
console.log(JSON.stringify({ meters: byHook(box, "analyze-meters").length, chips: byHook(box, "analyze-grade").length, err: byHook(box, "analyze-error").length }));
''', rep, meters=REAL)
        self.assertEqual((o["meters"], o["chips"], o["err"]), (2, 0, 0))

    def test_the_real_file_is_still_there_afterwards(self):
        before = (R._workdir() / "pick-meters.js").exists()
        js("console.log(1);", meters="export const x = 1;")
        self.assertEqual((R._workdir() / "pick-meters.js").exists(), before)
        self.assertTrue(before, "web/js/pick-meters.js is copied into the work directory")

    def test_a_phone_sees_twelve_tickets_and_a_button_for_the_rest(self):
        o = js('''
await A.mountAnalyze(box, { dogId: "u-drakeo", apiGet });
const rows = byHook(box, "analyze-pick");
const shown = () => rows.filter((r) => !r.hasAttribute("hidden")).length;
const before = { all: rows.length, shown: shown(), button: text(byHook(box, "analyze-picks-more")[0]) };
byHook(box, "analyze-picks-more")[0].click();
console.log(JSON.stringify({ before, after: { shown: shown(), button: byHook(box, "analyze-picks-more").length } }));
''')
        self.assertEqual(o["before"], {"all": 23, "shown": 12, "button": "Show all 23 tickets"})
        self.assertEqual(o["after"], {"shown": 23, "button": 0})

    def test_grades_with_only_one_score_show_only_that_score(self):
        o = js('console.log(JSON.stringify([A.gradeText(null), A.gradeText({}), A.gradeText({ value: { score: 71.4 } }), A.gradeText({ confidence: { score: 60 }, value: { score: 71 } })]));')
        self.assertEqual(o, ["", "", "V 71", "C 60 \u00b7 V 71"])


@unittest.skipUnless(HAS_NODE, "node not installed")
class TheStates(unittest.TestCase):
    def test_loading_then_the_report(self):
        o = js('''
let release; const gate = new Promise((r) => { release = r; });
const slow = async (path) => { await gate; return REPORT; };
const pending = A.mountAnalyze(box, { dogId: "u-drakeo", apiGet: slow });
const during = { loading: byHook(box, "analyze-loading").length, busy: byHook(box, "analyze-loading")[0].attrs["aria-busy"] };
release();
const res = await pending;
console.log(JSON.stringify({ during, after: byHook(box, "analyze-loading").length, report: byHook(box, "analyze-report").length, res }));
''')
        self.assertEqual(o["during"], {"loading": 1, "busy": "true"})
        self.assertEqual((o["after"], o["report"], o["res"]["ok"]), (0, 1, True))

    def test_an_error_says_so_and_can_be_retried(self):
        o = js('''
let fails = 1;
const flaky = async () => { if (fails-- > 0) { const e = new Error("x"); e.status = 503; e.detail = "warming"; throw e; } return REPORT; };
const first = await A.mountAnalyze(box, { dogId: "u-drakeo", apiGet: flaky });
const err = { n: byHook(box, "analyze-error").length, text: text(byHook(box, "analyze-error")[0]), role: byHook(box, "analyze-error")[0].attrs.role };
byHook(box, "analyze-retry")[0].click();
await new Promise((r) => setTimeout(r, 20));
console.log(JSON.stringify({ first, err, after: byHook(box, "analyze-report").length, errAfter: byHook(box, "analyze-error").length }));
''')
        self.assertEqual(o["first"], {"ok": False})
        self.assertEqual((o["err"]["n"], o["err"]["role"]), (1, "alert"))
        self.assertIn("still being worked out", o["err"]["text"])
        self.assertEqual((o["after"], o["errAfter"]), (1, 0))

    def test_the_servers_own_refusal_words_are_used(self):
        o = js('''
const refuse = async () => { const e = new Error("x"); e.status = 422; e.detail = { error: "not_a_member_dog", message: "The Analyze report is for hounds a member built." }; throw e; };
await A.mountAnalyze(box, { dogId: "chalk_chihuahua", apiGet: refuse });
console.log(JSON.stringify(text(byHook(box, "analyze-error")[0])));
''')
        self.assertIn("The Analyze report is for hounds a member built.", o)

    def test_a_hostile_string_is_text_and_never_an_element(self):
        rep = report()
        rep["headline"] = '<img src=x onerror="alert(1)"> is 16-7'
        rep["picks"][0]["selection"] = "<b>bold</b> to win"
        o = js('''
await A.mountAnalyze(box, { dogId: "u-drakeo", apiGet });
console.log(JSON.stringify({ imgs: find(box, (n) => n.tag === "img" || n.tag === "b" && n.attrs.class === undefined).length, headline: text(byHook(box, "analyze-headline")[0]) }));
''', rep)
        self.assertEqual(o["imgs"], 0)
        self.assertTrue(o["headline"].startswith("<img"))

    def test_the_dog_id_is_escaped_in_the_path(self):
        o = js('''
await A.mountAnalyze(box, { dogId: "u a/b", apiGet });
console.log(JSON.stringify(calls));
''')
        self.assertEqual(o, ["/hounds/u%20a%2Fb/report"])

    def test_the_studio_container_is_found_by_its_hook(self):
        o = js('''
const host = new El("div"); host.setAttribute("data-hook", "studio-analyze");
const shell = new El("div"); shell.appendChild(host);
const none = A.mountAnalyzeIfPresent(new El("div"), "u-drakeo", { apiGet });
const p = A.mountAnalyzeIfPresent(shell, "u-drakeo", { apiGet });
const res = await p;
console.log(JSON.stringify({ none, res, drawn: byHook(host, "analyze-report").length, noId: A.mountAnalyzeIfPresent(shell, "", { apiGet }) }));
''')
        self.assertEqual((o["none"], o["res"], o["drawn"], o["noId"]), (None, {"ok": True, "tier": "full"}, 1, None))

    def test_the_link_is_inserted_once_for_two_mounts(self):
        o = js('''
await A.mountAnalyze(box, { dogId: "u-drakeo", apiGet });
await A.mountAnalyze(box, { dogId: "u-drakeo", apiGet });
console.log(JSON.stringify(find(head, (n) => n.tag === "link").length));
''')
        self.assertEqual(o, 1)


@unittest.skipUnless(HAS_NODE, "node not installed")
class ThePureHelpers(unittest.TestCase):
    def test_the_needle_runs_from_hot_dice_to_hot_hand(self):
        o = js('console.log(JSON.stringify([0, 25, 50, 100, -20, 140, null, "x"].map(A.needleAngle)));')
        self.assertEqual(o, [-90, -45, 0, 90, -90, 90, -90, -90])

    def test_the_dial_has_three_zones_that_meet(self):
        o = js('console.log(JSON.stringify({ zones: A.ZONES, p: A.arcPath(0, 25), full: A.arcPath(0, 100) }));')
        self.assertEqual(o["zones"], [["dice", 0, 25], ["mid", 25, 50], ["hand", 50, 100]])
        self.assertTrue(o["p"].startswith("M 20 100 A 80 80 0 0 1 "), o["p"])
        self.assertEqual(o["full"], "M 20 100 A 80 80 0 0 1 180 100")


class TheStylesheetAndCopy(unittest.TestCase):
    def test_motion_lives_only_inside_the_no_preference_block(self):
        block = CSS[CSS.index("@media (prefers-reduced-motion: no-preference)"):]
        before = CSS[:CSS.index("@media (prefers-reduced-motion: no-preference)")]
        self.assertNotIn("animation", before)
        self.assertNotIn("transition", before)
        self.assertRegex(block, r"ar-sweep 700ms")
        self.assertEqual(A.__dict__.get("PURPOSE"), "analyze_report")

    def test_a_phone_gets_sixteen_pixel_gutters_and_no_sideways_scroll(self):
        self.assertRegex(CSS, r"--ar-gutter: 16px;")
        self.assertRegex(CSS, r"padding: 0 var\(--ar-gutter\)")
        self.assertRegex(CSS, r"\.ar \*, \.ar \*::before, \.ar \*::after \{ box-sizing: border-box; min-width: 0; \}")
        self.assertIn("overflow-wrap: anywhere", CSS)
        self.assertRegex(CSS, r"grid-template-columns: 1fr;")
        self.assertNotRegex(CSS, r"overflow-x:\s*scroll")

    def test_the_screen_says_hound_and_never_badges_anything_new_or_promises(self):
        words = re.sub(r"//.*|/\*.*?\*/", "", JS, flags=re.S)
        strings = " ".join(re.findall(r'"([^"\n]*)"|`([^`\n]*)`', words) and [a or b for a, b in re.findall(r'"([^"\n]*)"|`([^`\n]*)`', words)])
        self.assertNotRegex(strings, r"\b[Dd]ogs?\b")
        self.assertNotRegex(strings, r"(?<![a-z])New(?![a-z])")
        self.assertNotRegex(strings, r"(?i)\b(edge|guarantee|lock|beta|will win|keep winning|profit)\b")

    def test_it_imports_nothing_it_does_not_need(self):
        imports = re.findall(r'^import .* from "([^"]+)";', JS, flags=re.M)
        self.assertEqual(imports, ["./hounds-core.js", "./api.js", "./upgrade.js"])


if __name__ == "__main__":
    unittest.main()
