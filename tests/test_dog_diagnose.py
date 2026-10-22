"""The analysis phase of Send to training (web/js/dog-diagnose.js, web/css/diagnose.css).

Owner request 2026-10-21: training should feel "MATRIX-LEVEL complicated, AI assessing and analyzing... expensive and well thought
out", and every line on screen must be a real check with its real result. What must stay true while it does:

  * THE STEPS ARE THE ROWS. The log has exactly one line per row of the server's diagnosis, in its order and in its own words, plus a
    handful of framing lines (asking the coach, the answer, the cause). Nothing is added, nothing is computed in the browser.
  * THE AI IS LABELLED FOR WHAT IT WAS. "AI read" only when the model answered; "Coach's read (rules engine)" when it is capped, down
    or its reasons were dropped. A coach that cannot be reached still lets the training go on.
  * ESCAPING. Every word from the server goes in as text; a hostile label or reason never becomes an element.
  * SKIP AFTER THREE SECONDS; REDUCED MOTION IS ONE STATIC SUMMARY with no timer in it.
  * A PHONE. At 390 px nothing scrolls sideways at any beat.
"""

from __future__ import annotations

import json
import re
import tempfile
import threading
import unittest
from pathlib import Path

from src.hounds import user_store
from src.hounds.interact import coach as coach_mod, coach_ai, diagnosis as D, rites, training
from tests import test_hounds_rites_web as rites_web
from tests._hounds_rites_fixtures import NOW, RitesCase, rows_for
from tests.hounds_web_runner import HAS_NODE, run_js, run_page
from tests.test_hounds_coach import PLAN, FakeAdapter, good_reply, real_router
from tests.test_hounds_diagnosis import HID, build, context
from tests.test_no_horizontal_overflow import CHROME, HERE
from tests._hounds_user_fixtures import spec_dict

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"

# a small DOM that can run the module for real: elements with children, attributes, text, click listeners
DOM = r'''
class Txt { constructor(t) { this.nodeType = 3; this.text = String(t); this.parentNode = null; } get textContent() { return this.text; } set textContent(v) { this.text = String(v); } }
class El {
  constructor(tag) { this.nodeType = 1; this.tag = tag; this.attrs = {}; this.childNodes = []; this.parentNode = null; this.listeners = {}; this.scrollTop = 0; this.scrollHeight = 0; }
  get kids() { return this.childNodes; }
  get firstChild() { return this.childNodes[0] || null; }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; }
  removeAttribute(k) { delete this.attrs[k]; }
  hasAttribute(k) { return k in this.attrs; }
  appendChild(c) { if (c.parentNode) c.parentNode.removeChild(c); c.parentNode = this; this.childNodes.push(c); return c; }
  insertBefore(c, ref) { if (c.parentNode) c.parentNode.removeChild(c); const i = ref ? this.childNodes.indexOf(ref) : -1; c.parentNode = this; if (i < 0) this.childNodes.push(c); else this.childNodes.splice(i, 0, c); return c; }
  removeChild(c) { const i = this.childNodes.indexOf(c); if (i >= 0) this.childNodes.splice(i, 1); c.parentNode = null; return c; }
  set textContent(v) { this.childNodes = []; if (String(v) !== "") { const t = new Txt(v); t.parentNode = this; this.childNodes.push(t); } }
  get textContent() { return this.childNodes.map((c) => c.textContent).join(""); }
  addEventListener(t, f) { (this.listeners[t] ||= []).push(f); }
  click() { (this.listeners.click || []).forEach((f) => f({ stopPropagation() {}, target: this })); }
}
globalThis.document = { createElement: (t) => new El(t), createElementNS: (ns, t) => new El(t), createTextNode: (t) => new Txt(t) };
globalThis.timerCount = 0;
const realSetTimeout = globalThis.setTimeout;
globalThis.setTimeout = (...a) => { globalThis.timerCount += 1; return realSetTimeout(...a); };
const walk = (n, f) => { if (n && n.nodeType === 1) { f(n); n.childNodes.forEach((k) => walk(k, f)); } };
const find = (root, pred) => { const out = []; walk(root, (n) => { if (pred(n)) out.push(n); }); return out; };
const byHook = (root, hook) => find(root, (n) => n.attrs["data-hook"] === hook);
const LOOK = { coat: "golden", style: "mascot", breed: "retriever" };
const lineText = (n) => n.childNodes[1].textContent;
const sleep = (ms) => new Promise((r) => realSetTimeout(r, ms));
'''


def js(body: str):
    return run_js(DOM + 'const Dx = await import("./dog-diagnose.js");\n' + body)


def fixture():
    """A real diagnosis and a real AI read of it, as the routes would send them (computed, not typed)."""
    rows, ids = build()
    spec = spec_dict(name="Diag Pup", sports=["MLB"])
    bets = rites.forward_bets(HID, rows)
    table = D.diagnose(bets, spec, rows=rows, context=context(ids))
    analysis = training.analyse(bets, spec)
    entries = training.menu(spec, analysis, table)
    with tempfile.TemporaryDirectory() as tmp:
        ai = coach_ai.assess(table, entries, router=real_router(tmp, FakeAdapter(good_reply)))
    rules = coach_ai.rules_read(table, status="capped")
    return {"diagnosis": coach_mod.public_view(table), "ai": training.coach_view(ai), "rules": training.coach_view(rules), "table": table}


FIX = fixture()


def run_dx(extra: str, *, coach="ai", reduced="false", speed=0, diag=None):
    d = json.dumps(diag or FIX["diagnosis"])
    c = json.dumps(FIX[coach] if coach else None)
    return js(f'''
const diagnosis = {d};
const coachRead = {c};
const calls = {{ diagnose: 0, assess: 0 }};
const steps = {{ diagnose: async () => {{ calls.diagnose++; return {{ diagnosis }}; }}, assess: async () => {{ calls.assess++; return {{ coach: coachRead }}; }} }};
const body = document.createElement("div");
const layer = document.createElement("div");
{extra}''')


@unittest.skipUnless(HAS_NODE, "node not installed")
class TheStepsAreTheRowsOfTheDiagnosis(unittest.TestCase):
    def test_one_step_per_row_in_the_servers_order_and_words(self):
        got = js(f'''
const diagnosis = {json.dumps(FIX["diagnosis"])};
const steps = Dx.rowSteps(diagnosis);
console.log(JSON.stringify({{ ids: steps.map((s) => s.id), texts: steps.map((s) => s.text), rows: diagnosis.rows.map((r) => r.id), lines: diagnosis.rows.map((r) => r.line) }}));''')
        self.assertEqual(got["ids"], got["rows"])
        self.assertEqual(len(got["ids"]), len(FIX["diagnosis"]["rows"]))
        for text, line, rid in zip(got["texts"], got["lines"], got["ids"]):
            if rid == "overall":
                self.assertTrue(text.startswith("Scanning 12 settled tickets: 5-6-1, -1.0u"), text)
            else:
                self.assertTrue(text.startswith(line), (text, line))

    def test_too_few_bets_is_said_on_the_line_itself(self):
        got = js(f'''
const diagnosis = {json.dumps(FIX["diagnosis"])};
console.log(JSON.stringify(Dx.rowSteps(diagnosis).filter((s) => /too few bets to say/.test(s.text)).map((s) => s.id)));''')
        thin = [f["id"] for f in FIX["diagnosis"]["rows"] if f["kind"] in ("segment", "combo") and f["level"] == "too_few"]
        self.assertTrue(thin)
        self.assertEqual(got, thin)

    def test_the_screen_draws_exactly_one_line_per_row_plus_the_framing_lines_and_one_tile_per_row_but_the_overall(self):
        got = run_dx('''
const out = await Dx.runDiagnosis({ body, dog: { id: "u-1", name: "Gus", look: LOOK }, steps, layer, speed: 0 });
const lines = byHook(body, "diagnose-line");
const rowLines = lines.filter((n) => n.attrs["data-kind"] === "row");
const frames = lines.filter((n) => n.attrs["data-kind"] === "frame");
console.log(JSON.stringify({ ok: out.ok, calls, nRows: rowLines.length, ids: rowLines.map((n) => n.attrs["data-id"]),
  texts: rowLines.map(lineText), frames: frames.map(lineText), tiles: byHook(body, "diagnose-tile").length,
  tilesOn: byHook(body, "diagnose-tile").filter((n) => n.attrs["data-state"] === "on").length, count: byHook(body, "diagnose-count")[0].textContent,
  phase: byHook(body, "diagnose")[0].attrs["data-phase"], layerPhase: layer.attrs["data-diagnose"] }));''')
        rows = FIX["diagnosis"]["rows"]
        self.assertTrue(got["ok"])
        self.assertEqual(got["calls"], {"diagnose": 1, "assess": 1})
        self.assertEqual(got["nRows"], len(rows))
        self.assertEqual(got["ids"], [r["id"] for r in rows])
        self.assertEqual(got["tiles"], len(rows) - 1)
        self.assertEqual(got["tilesOn"], len(rows) - 1)
        self.assertEqual(got["count"], f"{len(rows)}/{len(rows)} checks")
        self.assertEqual(got["phase"], "done")
        # the framing lines: asking, the answer, and the cause(s)
        self.assertEqual(got["frames"][0], f"Claude Haiku answered: {len(FIX['ai']['reasons'])} reasons ranked.")
        self.assertTrue(got["frames"][1].startswith("Most likely cause: "))
        self.assertEqual(len(got["frames"]), 2 + (len(FIX["ai"]["reasons"]) - 1))

    def test_the_ask_line_says_what_is_being_asked_while_it_waits(self):
        got = run_dx('''
let release; const gate = new Promise((r) => { release = r; });
const slow = { diagnose: steps.diagnose, assess: async () => { await gate; return { coach: coachRead }; } };
const run = Dx.runDiagnosis({ body, dog: { id: "u-1", name: "Gus", look: LOOK }, steps: slow, layer, speed: 0 });
await sleep(30);
const waiting = byHook(body, "diagnose-line").filter((n) => n.attrs["data-kind"] === "frame").map((n) => [lineText(n), n.attrs["data-state"]]);
const phaseWaiting = byHook(body, "diagnose")[0].attrs["data-phase"];
release(); const out = await run;
console.log(JSON.stringify({ waiting, phaseWaiting, ok: out.ok }));''')
        self.assertEqual(got["waiting"], [["Asking the coach...", "pending"]])
        self.assertEqual(got["phaseWaiting"], "ask")
        self.assertTrue(got["ok"])

    def test_the_ask_line_never_names_haiku_before_the_answer_and_the_answer_names_who_read(self):
        # owner honesty rule: never claim AI ran when it did not
        for key, must, must_not in (("ai", "Claude Haiku answered", "rules engine"), ("rules", "rules engine", "Claude Haiku")):
            with self.subTest(key=key):
                coach = json.dumps({**FIX[key], "why": None if key == "ai" else "resting"})
                got = run_dx(f'''
let release; const gate = new Promise((r) => {{ release = r; }});
const slow = {{ diagnose: steps.diagnose, assess: async () => {{ await gate; return {{ coach: {coach} }}; }} }};
const run = Dx.runDiagnosis({{ body, dog: {{ id: "u-1", name: "Gus", look: LOOK }}, steps: slow, layer, speed: 0 }});
await sleep(30);
const frames = () => byHook(body, "diagnose-line").filter((n) => n.attrs["data-kind"] === "frame").map(lineText);
const before = frames();
release(); await run;
console.log(JSON.stringify({{ before, after: frames()[0] }}));''')
                self.assertEqual(got["before"], ["Asking the coach..."])
                self.assertNotIn("Haiku", got["before"][0])
                self.assertIn(must, got["after"])
                self.assertNotIn(must_not, got["after"])

    def test_the_read_is_labelled_ai_only_when_the_model_answered(self):
        ai = run_dx('''
await Dx.runDiagnosis({ body, dog: { id: "u-1", name: "Gus", look: LOOK }, steps, layer, speed: 0 });
console.log(JSON.stringify({ label: byHook(body, "diagnose-label").map((n) => n.textContent), source: byHook(body, "diagnose-read").map((n) => n.attrs["data-source"]),
  reasons: byHook(body, "diagnose-reason").length, cites: byHook(body, "diagnose-cite").map((n) => n.textContent) }));''')
        self.assertEqual(ai["label"], ["AI read - Claude Haiku"])
        self.assertEqual(ai["source"], ["ai"])
        self.assertEqual(ai["reasons"], len(FIX["ai"]["reasons"]))
        table = D.by_id(FIX["table"])
        for text in ai["cites"]:
            self.assertIn(text, [f["line"] for f in table.values()])
        rules = run_dx('''
await Dx.runDiagnosis({ body, dog: { id: "u-1", name: "Gus", look: LOOK }, steps, layer, speed: 0 });
console.log(JSON.stringify({ label: byHook(body, "diagnose-label").map((n) => n.textContent), source: byHook(body, "diagnose-read").map((n) => n.attrs["data-source"]),
  frames: byHook(body, "diagnose-line").filter((n) => n.attrs["data-kind"] === "frame").map(lineText),
  cites: byHook(body, "diagnose-cite").length }));''', coach="rules")
        self.assertEqual(rules["cites"], 0, "a rules reason is the table's own line, so it is not printed twice")
        self.assertEqual(rules["label"], ["Coach's read (rules engine)"])
        self.assertEqual(rules["source"], ["rules"])
        self.assertEqual(rules["frames"][0], "The AI coach is resting. Reading the table with the rules engine.")

    def test_the_answer_line_says_why_the_rules_engine_read_it(self):
        for why, expect in (("too_few", "Too few settled bets for an AI read. Reading the table with the rules engine."),
                            ("dropped", "None of the AI's reasons held up against the table. Reading it with the rules engine."),
                            ("resting", "The AI coach is resting. Reading the table with the rules engine.")):
            with self.subTest(why=why):
                diag = json.dumps(FIX["diagnosis"])
                coach = json.dumps({**FIX["rules"], "why": why})
                got = js(f'''
const diagnosis = {diag};
const coachRead = {coach};
const steps = {{ diagnose: async () => ({{ diagnosis }}), assess: async () => ({{ coach: coachRead }}) }};
const body = document.createElement("div");
await Dx.runDiagnosis({{ body, dog: {{ id: "u-1", name: "Gus", look: LOOK }}, steps, layer: null, speed: 0 }});
console.log(JSON.stringify(byHook(body, "diagnose-line").filter((n) => n.attrs["data-kind"] === "frame").map(lineText)[0]));''')
                self.assertEqual(got, expect)

    def test_a_coach_that_cannot_be_reached_still_ends_in_a_read_from_the_table(self):
        got = run_dx('''
const down = { diagnose: steps.diagnose, assess: async () => { throw { status: 500 }; } };
const out = await Dx.runDiagnosis({ body, dog: { id: "u-1", name: "Gus", look: LOOK }, steps: down, layer, speed: 0 });
console.log(JSON.stringify({ ok: out.ok, coach: out.coach, label: byHook(body, "diagnose-label").map((n) => n.textContent),
  frames: byHook(body, "diagnose-line").filter((n) => n.attrs["data-kind"] === "frame").map(lineText),
  reasons: byHook(body, "diagnose-reason").map((n) => n.attrs["data-rank"]) }));''')
        self.assertTrue(got["ok"])
        self.assertIsNone(got["coach"])
        self.assertEqual(got["label"], ["Coach's read (rules engine)"])
        self.assertEqual(got["frames"][0], "The coach could not be reached. Reading the table with the rules engine.")
        self.assertEqual(got["reasons"], ["1", "2", "3"][:len(got["reasons"])])
        self.assertTrue(got["reasons"])

    def test_nothing_settled_is_said_plainly_and_hands_off(self):
        empty = {"version": 1, "settled": 0, "overall": {"n": 0, "wins": 0, "losses": 0, "pushes": 0, "units": 0}, "rows": [], "ranked": [], "holding": [],
                 "meta": {"cuts_examined": 0, "min_factor_bets": 5, "note": ""}}
        got = run_dx('''
const out = await Dx.runDiagnosis({ body, dog: { id: "u-1", name: "Gus", look: LOOK }, steps, layer, speed: 0 });
console.log(JSON.stringify({ ok: out.ok, calls, lines: byHook(body, "diagnose-line").map(lineText) }));''', diag=empty)
        self.assertTrue(got["ok"])
        self.assertEqual(got["lines"], ["No settled tickets to read yet."])
        self.assertEqual(got["calls"]["assess"], 0, "nothing to read, so the model is not asked")


@unittest.skipUnless(HAS_NODE, "node not installed")
class ARefusalEndsItAndAMissingStepIsSkipped(unittest.TestCase):
    def outcome(self, error):
        return run_dx(f'''
const failing = {{ diagnose: async () => {{ throw {json.dumps(error)}; }}, assess: async () => {{ calls.assess++; return {{ coach: coachRead }}; }} }};
const out = await Dx.runDiagnosis({{ body, dog: {{ id: "u-1", name: "Gus", look: LOOK }}, steps: failing, layer, speed: 0 }});
console.log(JSON.stringify({{ ok: out.ok, refused: !!out.refused, skipped: !!out.skipped, assess: calls.assess, lines: byHook(body, "diagnose-line").length }}));''')

    def test_a_refusal_the_server_means_is_handed_back_to_be_shown(self):
        for code in ("open_tickets", "training_too_soon", "not_found", "not_a_member_dog"):
            with self.subTest(code=code):
                got = self.outcome({"status": 409, "detail": {"error": code, "message": "x"}})
                self.assertEqual((got["ok"], got["refused"], got["skipped"], got["assess"]), (False, True, False, 0))

    def test_a_route_that_is_not_there_or_a_dead_network_skips_the_phase_so_the_training_goes_on(self):
        for error in ({"status": 404, "detail": "not in the fixture"}, {"status": None}, {"status": 500, "detail": "boom"}, {"status": 429}):
            with self.subTest(error=error):
                got = self.outcome(error)
                self.assertEqual((got["ok"], got["refused"], got["skipped"], got["assess"], got["lines"]), (False, False, True, 0, 0))


@unittest.skipUnless(HAS_NODE, "node not installed")
class EveryWordFromTheServerIsText(unittest.TestCase):
    EVIL = '<img src=x onerror="alert(1)"><script>alert(2)</script>'

    def test_a_hostile_label_line_and_reason_never_become_elements(self):
        diag = json.loads(json.dumps(FIX["diagnosis"]))
        for f in diag["rows"]:
            if f["id"] == "venue:away":
                f["label"] = self.EVIL
                f["line"] = f"{self.EVIL}: 1-5, -3.5u"
        coach = json.loads(json.dumps(FIX["ai"]))
        coach["reasons"][0]["text"] = self.EVIL
        coach["reasons"][0]["cited"][0]["line"] = self.EVIL
        coach["summary"] = self.EVIL
        got = js(f'''
const diagnosis = {json.dumps(diag)};
const coachRead = {json.dumps(coach)};
const steps = {{ diagnose: async () => ({{ diagnosis }}), assess: async () => ({{ coach: coachRead }}) }};
const body = document.createElement("div");
await Dx.runDiagnosis({{ body, dog: {{ id: "u-1", name: "Gus", look: LOOK }}, steps, layer: null, speed: 0 }});
const tags = new Set(); walk(body, (n) => tags.add(n.tag));
const texts = []; walk(body, (n) => {{ n.childNodes.forEach((c) => {{ if (c.nodeType === 3) texts.push(c.text); }}); }});
const titles = []; walk(body, (n) => {{ if (n.attrs.title) titles.push(n.attrs.title); }});
console.log(JSON.stringify({{ tags: [...tags], hasEvilText: texts.some((t) => t.includes("<img")), titles: titles.filter((t) => t.includes("<img")).length }}));''')
        self.assertNotIn("img", got["tags"])
        self.assertNotIn("script", got["tags"])
        self.assertTrue(got["hasEvilText"], "the markup is on screen as plain text")

    def test_the_module_builds_nothing_from_html_strings(self):
        src = (WEB / "js" / "dog-diagnose.js").read_text(encoding="utf-8")
        for banned in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function"):
            self.assertNotIn(banned, src)
        self.assertNotRegex(src, r"<script|import\(\s*[\"']http|https?://(?!www\.w3\.org)")


@unittest.skipUnless(HAS_NODE, "node not installed")
class SkipAndReducedMotion(unittest.TestCase):
    def test_a_skip_button_appears_after_three_seconds_not_before(self):
        src = (WEB / "js" / "dog-diagnose.js").read_text(encoding="utf-8")
        self.assertRegex(src, r"skipAfter:\s*3000")
        got = run_dx('''
const t = { ...Dx.TIMING, rowMin: 40, rowMax: 40, pending: 5, skipAfter: 120, askMin: 10, reasonGap: 10, hold: 100000 };
const run = Dx.runDiagnosis({ body, dog: { id: "u-1", name: "Gus", look: LOOK }, steps, layer, speed: 1, timing: t });
await sleep(60);
const early = byHook(body, "diagnose-skip")[0].hasAttribute("hidden");
await sleep(120);
const late = byHook(body, "diagnose-skip")[0].hasAttribute("hidden");
byHook(body, "diagnose-skip")[0].click();
const out = await run;
console.log(JSON.stringify({ early, late, ok: out.ok, skipped: out.skipped, assess: calls.assess, lines: byHook(body, "diagnose-line").filter((n) => n.attrs["data-kind"] === "row").length }));''')
        self.assertEqual((got["early"], got["late"]), (True, False))
        self.assertEqual((got["ok"], got["skipped"], got["assess"]), (True, True, 1))
        self.assertEqual(got["lines"], len(FIX["diagnosis"]["rows"]), "a skip fast-forwards the lines: every row still resolves")

    def test_the_default_pacing_is_about_twenty_to_thirty_five_seconds_for_a_real_table(self):
        got = js(f'''
const diagnosis = {json.dumps(FIX["diagnosis"])};
const T = Dx.TIMING;
const n = Dx.rowSteps(diagnosis).length;
const per = Math.max(T.rowMin, Math.min(T.rowMax, T.rowTarget / n));
const bigPer = Math.max(T.rowMin, Math.min(T.rowMax, T.rowTarget / 48));
console.log(JSON.stringify({{ n, rows: per * n, big: bigPer * 48, tail: T.askMin + T.reasonGap * 3 + T.hold }}));''')
        # a 12-bet fixture is a small table; the pacing still adds up to a readable run, and a 48-row table is bounded by the target
        self.assertLessEqual(got["big"], 17000 + 48 * 20)
        self.assertGreaterEqual(got["tail"], 8000)

    def test_reduced_motion_is_one_static_summary_with_no_timer_and_a_continue_button(self):
        got = run_dx('''
globalThis.timerCount = 0;
const run = Dx.runDiagnosis({ body, dog: { id: "u-1", name: "Gus", look: LOOK }, steps, layer, reduced: true });
await sleep(30);
const before = { timers: globalThis.timerCount, phase: byHook(body, "diagnose")[0].attrs["data-phase"], motion: byHook(body, "diagnose")[0].attrs["data-motion"],
  continues: byHook(body, "diagnose-continue").length, skips: byHook(body, "diagnose-skip").length, weak: byHook(body, "diagnose-weak")[0].childNodes.length,
  folded: byHook(body, "diagnose-all").length, allLines: byHook(body, "diagnose-all")[0].childNodes[1].childNodes.length,
  label: byHook(body, "diagnose-label").map((n) => n.textContent), tilesOn: byHook(body, "diagnose-tile").filter((n) => n.attrs["data-state"] === "on").length };
byHook(body, "diagnose-continue")[0].click();
const out = await run;
console.log(JSON.stringify({ before, ok: out.ok, timersAfter: globalThis.timerCount }));''', reduced="true")
        b = got["before"]
        self.assertEqual(b["phase"], "static")
        self.assertEqual(b["motion"], "reduced")
        self.assertEqual((b["continues"], b["skips"], b["folded"]), (1, 0, 1))
        self.assertEqual(b["weak"], min(5, len(FIX["diagnosis"]["ranked"])))
        self.assertEqual(b["allLines"], len(FIX["diagnosis"]["rows"]) + 1, "every check is in the folded list, plus the one framing line")
        self.assertEqual(b["label"], ["AI read - Claude Haiku"])
        self.assertEqual(b["tilesOn"], len(FIX["diagnosis"]["rows"]) - 1)
        self.assertEqual(b["timers"], 0, "nothing in the reduced path waits on a timer")
        self.assertTrue(got["ok"])

    def test_every_keyframe_sits_inside_a_no_preference_media_query(self):
        css = (WEB / "css" / "diagnose.css").read_text(encoding="utf-8")
        outside = re.sub(r"@media \(prefers-reduced-motion: no-preference\) \{.*?\n\}\n", "", css, flags=re.S)
        outside = re.sub(r"@keyframes [\w-]+ \{.*?\}\s*\}", "", outside, flags=re.S)
        self.assertNotRegex(outside, r"\banimation\s*:")
        self.assertNotRegex(outside, r"\banimation-name\s*:")
        self.assertIn('@import url("diagnose.css")', (WEB / "css" / "dog-kit.css").read_text(encoding="utf-8"))


class TheWordsAreTrueAboutThePast(unittest.TestCase):
    def shown(self, path):
        src = path.read_text(encoding="utf-8")
        lits = re.findall(r'"((?:[^"\\\n]|\\.)*)"|`((?:[^`\\]|\\.)*)`', src)
        return " ".join(a or b for a, b in lits)

    def test_no_shown_word_promises_improvement_or_says_dog(self):
        for name in ("dog-diagnose.js",):
            text = self.shown(WEB / "js" / name)
            self.assertIsNone(re.search(r"\b(better|improve\w*|stronger|smarter|profit\w*|edge|ROI|will win|guarantee\w*|Bet Check)\b", text, re.I), name)
            self.assertIsNone(re.search(r"\bdogs?\b(?!-)", re.sub(r"data-[a-z-]+|\.dk-|dog-avatar|dogBadge|dog\.", "", text)), name)

    def test_the_card_says_these_are_facts_about_the_past_and_the_new_record_starts_now(self):
        src = (WEB / "js" / "dog-rites.js").read_text(encoding="utf-8")
        self.assertIn("These are facts about the past, not a forecast. The new version starts with a new record.", src)

    def test_the_two_labels_are_the_ones_the_owner_asked_for(self):
        self.assertEqual((coach_ai.AI_LABEL, coach_ai.RULES_LABEL), ("AI read", "Coach's read (rules engine)"))


# ---------------------------------------------------------------------------------------------------
# through the kennel page: the real script, the real HTML skeleton
# ---------------------------------------------------------------------------------------------------

def page_routes(coach_key="ai", diagnose=None, assess=None):
    routes = rites_web.kennel_routes([rites_web.dog("u-1")])
    routes["POST /hounds/u-1/train/diagnose"] = diagnose or [200, {"stage": "diagnose", "diagnosis": FIX["diagnosis"], "paper_only": True}]
    routes["POST /hounds/u-1/train/assess"] = assess or [200, {"stage": "assess", "diagnosis": FIX["diagnosis"], "coach": FIX[coach_key], "paper_only": True}]
    trained = json.loads(json.dumps(rites_web.payloads()["trained"]))
    trained["coach"] = FIX[coach_key]
    routes["POST /hounds/u-1/train"] = [200, trained]
    return routes


def hook(name):
    return f"[data-hook='{name}']"


@unittest.skipUnless(HAS_NODE, "node not installed")
class OnTheKennelPage(unittest.TestCase):
    OPEN = "[data-hook='dog-action-train']"

    def flow(self, routes, actions, reduced=True, **kw):
        return run_page("kennel", routes=routes, **rites_web.SIGNED, reducedMotion=reduced, actions=actions, **kw)

    def test_diagnose_then_assess_then_the_training_and_the_card_cites_the_reasons(self):
        click, q = rites_web.click, rites_web.q
        out = self.flow(page_routes(), [
            click(self.OPEN, "ask"),
            click(hook("training-go"), "static", wait=500, capture=[
                q("phase", hook("diagnose"), "attr", attr="data-phase"), q("label", hook("diagnose-label")), q("weak", hook("diagnose-weak") + " li", "count"),
                q("title", hook("rites-title")), q("kind", ".rt-sheet", "attr", attr="data-hook"), q("posts_card", hook("training-card"), "count")]),
            click(hook("diagnose-continue"), "review", wait=250), click(hook("review-apply"), "card", wait=500, capture=[
                q("card", hook("training-card"), "count"), q("coach", hook("training-coach")), q("coach_label", hook("training-coach-label")),
                q("reasons", hook("training-reason"), "count"), q("cites", hook("training-cite"), "count"), q("fold", hook("evolve-why"), "attr", attr="open"),
                q("version", hook("training-version"))])])
        urls = [p["url"] for p in out["posts"]]
        self.assertEqual(urls, ["/hounds/u-1/train/diagnose", "/hounds/u-1/train/assess", "/hounds/u-1/train/propose", "/hounds/u-1/train"])
        static = out["captures"]["static"]
        self.assertEqual((static["phase"], static["posts_card"]), ("static", 0), "the training has not run while the summary is up")
        self.assertIn("AI read", static["label"])
        self.assertEqual(static["weak"], min(5, len(FIX["diagnosis"]["ranked"])))
        card = out["captures"]["card"]
        self.assertEqual(card["card"], 1)
        self.assertIn("AI read", card["coach_label"])
        self.assertEqual(card["reasons"], len(FIX["ai"]["reasons"]))
        self.assertGreaterEqual(card["cites"], card["reasons"])
        self.assertIsNotNone(card["fold"], "the fold that holds the reasons is open")
        self.assertIn("Version 2", card["version"])

    def test_the_rules_engine_read_is_labelled_as_such_on_the_summary_and_the_card(self):
        click, q = rites_web.click, rites_web.q
        out = self.flow(page_routes("rules"), [
            click(self.OPEN, "ask"),
            click(hook("training-go"), "static", wait=500, capture=[q("label", hook("diagnose-label")), q("source", hook("diagnose-read"), "attr", attr="data-source")]),
            click(hook("diagnose-continue"), "review", wait=250), click(hook("review-apply"), "card", wait=500, capture=[q("coach_label", hook("training-coach-label")), q("source", hook("training-coach"), "attr", attr="data-source")])])
        self.assertEqual(out["captures"]["static"]["label"], "Coach's read (rules engine)")
        self.assertEqual(out["captures"]["static"]["source"], "rules")
        self.assertEqual(out["captures"]["card"]["coach_label"], "Coach's read (rules engine)")
        self.assertEqual(out["captures"]["card"]["source"], "rules")

    def test_a_refusal_at_the_diagnosis_is_shown_and_the_training_is_never_asked(self):
        click, q = rites_web.click, rites_web.q
        refusal = [409, {"detail": {"error": "open_tickets", "message": "Underdog Gus has 1 open ticket. Wait until its open tickets settle."}}]
        out = self.flow(page_routes(diagnose=refusal), [
            click(self.OPEN, "ask"),
            click(hook("training-go"), "refused", wait=500, capture=[q("refused", hook("training-refused")), q("code", hook("training-refused"), "attr", attr="data-code"),
                                                                  q("title", hook("rites-title")), q("evolve", hook("evolve"), "count")])])
        self.assertEqual([p["url"] for p in out["posts"]], ["/hounds/u-1/train/diagnose"])
        got = out["captures"]["refused"]
        self.assertIn("Wait until its open tickets settle", got["refused"])
        self.assertEqual((got["code"], got["evolve"]), ("open_tickets", 0))
        self.assertIn("stays as it is", got["title"])

    def test_a_coach_that_fails_still_trains(self):
        click, q = rites_web.click, rites_web.q
        out = self.flow(page_routes(assess=[500, {"detail": "boom"}]), [
            click(self.OPEN, "ask"),
            click(hook("training-go"), "static", wait=500, capture=[q("label", hook("diagnose-label"))]),
            click(hook("diagnose-continue"), "review", wait=250), click(hook("review-apply"), "card", wait=500, capture=[q("card", hook("training-card"), "count")])])
        self.assertEqual(out["captures"]["static"]["label"], "Coach's read (rules engine)")
        self.assertEqual(out["captures"]["card"]["card"], 1)
        self.assertEqual([p["url"] for p in out["posts"]][-1], "/hounds/u-1/train")


# ---------------------------------------------------------------------------------------------------
# a phone: a real Chrome plays it at 390 px
# ---------------------------------------------------------------------------------------------------

@unittest.skipUnless(HAS_NODE and CHROME, "node and a Chrome/Chromium binary are needed")
class TheDiagnosisFitsAPhoneAtEveryBeat(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import subprocess
        from tests import test_dog_evolve as evolve
        routes = page_routes()
        cls.server = evolve.FixtureServer(("127.0.0.1", 0), evolve.make_handler(routes))      # a deep backlog: see FixtureServer
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"
        cls.play = staticmethod(lambda mode: json.loads([ln for ln in subprocess.run(
            ["node", str(HERE / "diagnose_390.mjs"), CHROME, cls.base, "-", mode], capture_output=True, text=True, encoding="utf-8", timeout=150).stdout.splitlines()
            if ln.startswith("{")][-1]))

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def test_every_beat_of_the_full_run_fits_390_and_all_of_them_play(self):
        out = self.play("full")
        self.assertEqual(out["errors"], [])
        for phase in ("scan", "ask", "read", "done", "review"):
            self.assertIn(phase, out["phases"], out["phases"])
        bad = [s for s in out["samples"] if s["sw"] > s["iw"] + 1 or s["sheetSw"] > s["sheetCw"] + 1 or s["wide"]]
        self.assertEqual(bad, [], json.dumps(bad[:3]))
        self.assertGreaterEqual(out["lines"], len(FIX["diagnosis"]["rows"]))

    def test_the_static_summary_fits_390(self):
        out = self.play("reduced")
        self.assertEqual(out["errors"], [])
        self.assertIn("static", out["phases"])
        self.assertNotIn("scan", out["phases"])
        bad = [s for s in out["samples"] if s["sw"] > s["iw"] + 1 or s["sheetSw"] > s["sheetCw"] + 1 or s["wide"]]
        self.assertEqual(bad, [], json.dumps(bad[:3]))


if __name__ == "__main__":
    unittest.main()
