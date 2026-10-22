"""The Gematria analysis the page plays while Unleash (or Ask) runs (web/js/dog-gematria-stream.js), and the compact day it sits above.

Owner, 2026-10-22: the Gematria hound "took like 30 seconds; a real gematria hound would do better ... the analysis should feel deep and
real", and the day view "dumps every game by name ... way too long and looks sloppy". What must stay true:

  * THE STREAM IS THE COMPUTED EVIDENCE. Every line on screen is a line of the server's payload (each formatted from a value the engine
    computed), in its order; the only lines the page adds are frames made of the payload's own counts and names. The payload here is a
    REAL one: the engine weighs a fixture day and ``gematria_analysis.build`` formats it.
  * IT NEVER BLOCKS THE REAL REQUEST. The caller starts Unleash first; the stream waits on it, not the other way round, and a payload that
    cannot be had ends the stream quietly.
  * PACING IS STAGING. About 15 to 30 seconds for a full day, a Skip after two seconds, no timer and nothing drawn under reduced motion.
  * ESCAPING. A team name that is markup stays text.
  * THE DAY IS COUNTS. One tidy block, the games folded behind "See all games", the next game once, the live link once, one reasons line.
  * A PHONE. At 375 and 390 nothing scrolls sideways.
"""

from __future__ import annotations

import http.server
import json
import re
import threading
import unittest
from pathlib import Path

from tests.hounds_web_runner import HAS_NODE, run_js, run_page
from tests.test_gematria_v2 import BIG_DAY, analysis_payload
from tests.test_hounds_interact_web import HID, dog_routes, hook, q, unleash_day
from tests.test_no_horizontal_overflow import CHROME, HERE, make_handler

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
PAYLOAD = analysis_payload()

# a small DOM that can run the module for real (the same one the diagnosis tests use)
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
const lineText = (n) => n.childNodes[1].textContent;
const sleep = (ms) => new Promise((r) => realSetTimeout(r, ms));
'''


def js(body: str):
    return run_js(DOM + 'const Gs = await import("./dog-gematria-stream.js");\n' + body)


def expected_frames(payload):
    n = len(payload["games"])
    w = payload["weighed"]
    picks = payload["picks_total"]
    out = [f"Weighing {w} {'game' if w == 1 else 'games'} on today's board"]
    for i, g in enumerate(payload["games"]):
        out.append(f"Game {i + 1} of {n}: {g['game']} ({g['start_et']})")
    out.append(f"Done: {w} {'game' if w == 1 else 'games'} weighed, {picks} {'pick' if picks == 1 else 'picks'}")
    return out


def lines_of(payload):
    return [l["text"] for g in payload["games"] for l in g["lines"]]


def run_stream(extra: str, payload=PAYLOAD):
    return js(f'''
const payload = {json.dumps(payload)};
const body = document.createElement("div");
{extra}''')


@unittest.skipUnless(HAS_NODE, "node not installed")
class TheStreamIsTheComputedEvidence(unittest.TestCase):
    def test_the_payload_is_a_real_one(self):
        self.assertEqual(len(PAYLOAD["games"]), 12)
        self.assertGreater(PAYLOAD["picks_total"], 0)
        self.assertGreater(len(lines_of(PAYLOAD)), 60)

    def test_every_non_frame_step_is_a_server_line_in_order_and_the_frames_are_the_payloads_counts(self):
        got = js(f'''
const payload = {json.dumps(PAYLOAD)};
const steps = Gs.streamSteps(payload);
console.log(JSON.stringify({{ steps: steps.map((s) => [s.kind, s.text]) }}));''')
        steps = got["steps"]
        frames = [t for k, t in steps if k == "frame"]
        self.assertEqual(frames, expected_frames(PAYLOAD))
        date = [t for k, t in steps if k == "date"]
        self.assertEqual(date, [PAYLOAD["date_numbers"]["text"]])
        server = [t for k, t in steps if k not in ("frame", "date")]
        self.assertEqual(server, [re.sub(r"\s+", " ", t).strip() for t in lines_of(PAYLOAD)])
        self.assertEqual(steps[0][0], "frame")
        self.assertEqual(steps[-1][0], "frame")

    def test_the_rendered_log_is_those_steps_and_the_meters_are_the_payloads(self):
        got = run_stream('''
const out = await Gs.runGematriaStream({ body, load: async () => payload, speed: 0 });
const lines = byHook(body, "gematria-line").map((n) => [n.attrs["data-kind"], lineText(n)]);
console.log(JSON.stringify({ ok: out.ok, lines, steps: out.steps.map((s) => [s.kind, s.text]),
  weighed: byHook(body, "gematria-weighed")[0].textContent, picks: byHook(body, "gematria-picks")[0].textContent,
  count: byHook(body, "gematria-count")[0].textContent }));''')
        self.assertTrue(got["ok"])
        self.assertEqual(got["lines"], got["steps"])
        self.assertEqual(got["weighed"], str(PAYLOAD["weighed"]))
        self.assertEqual(got["picks"], str(sum(1 for g in PAYLOAD["games"] if g["status"] == "bet")))
        self.assertEqual(got["count"], "done")

    def test_a_decision_line_is_a_pick_or_a_pass_and_nothing_else(self):
        got = run_stream('''
await Gs.runGematriaStream({ body, load: async () => payload, speed: 0 });
const tones = byHook(body, "gematria-line").filter((n) => n.attrs["data-kind"] === "decision").map((n) => n.attrs["data-tone"] + ":" + lineText(n).split(":")[0]);
console.log(JSON.stringify({ tones }));''')
        self.assertEqual(len(got["tones"]), len(PAYLOAD["games"]))
        for tone in got["tones"]:
            self.assertIn(tone, ("good:Pick", "pass:Pass"))

    def test_the_folded_log_after_the_day_has_the_same_lines(self):
        got = run_stream('''
const fold = Gs.analysisLog(payload);
const lines = find(fold, (n) => n.attrs["data-hook"] === "gematria-line").map((n) => lineText(n));
console.log(JSON.stringify({ tag: fold.tag, lines, steps: Gs.streamSteps(payload).map((s) => s.text), summary: find(fold, (n) => n.tag === "summary")[0].textContent }));''')
        self.assertEqual(got["tag"], "details")
        self.assertEqual(got["lines"], got["steps"])
        self.assertIn("How it analysed today's games", got["summary"])


@unittest.skipUnless(HAS_NODE, "node not installed")
class ItNeverBlocksTheRealRequest(unittest.TestCase):
    def test_it_finishes_its_lines_then_waits_on_the_request_it_was_given(self):
        got = run_stream('''
let release; const request = new Promise((r) => { release = r; });
let settled = false;
const run = Gs.runGematriaStream({ body, load: async () => payload, waitFor: request, speed: 0 }).then((o) => { settled = true; return o; });
await sleep(60);
const waiting = { settled, lastState: byHook(body, "gematria-line").slice(-1)[0].attrs["data-state"], lastText: lineText(byHook(body, "gematria-line").slice(-1)[0]) };
release("answer"); const out = await run;
console.log(JSON.stringify({ waiting, settled, ok: out.ok, lastStateAfter: byHook(body, "gematria-line").slice(-1)[0].attrs["data-state"] }));''')
        self.assertEqual(got["waiting"]["settled"], False)
        self.assertEqual(got["waiting"]["lastState"], "pending")
        self.assertTrue(got["waiting"]["lastText"].startswith("Placing what fit"))
        self.assertTrue(got["settled"] and got["ok"])
        self.assertEqual(got["lastStateAfter"], "done")

    def test_a_request_that_fails_does_not_trip_the_stream(self):
        got = run_stream('''
const request = Promise.reject(new Error("boom")); request.catch(() => null);
const out = await Gs.runGematriaStream({ body, load: async () => payload, waitFor: request, speed: 0 });
console.log(JSON.stringify({ ok: out.ok }));''')
        self.assertTrue(got["ok"])

    def test_a_payload_that_cannot_be_had_ends_the_stream_quietly_and_still_waits_for_the_request(self):
        for load in ("async () => { throw new Error('404'); }", "async () => ({ games: [] })", "async () => null"):
            got = run_stream('''
let done = false; const request = sleep(40).then(() => { done = true; });
const out = await Gs.runGematriaStream({ body, load: LOAD, waitFor: request, speed: 0 });
console.log(JSON.stringify({ ok: out.ok, requestDone: done, drawn: byHook(body, "gematria-stream").length }));'''.replace("LOAD", load))
            self.assertEqual((got["ok"], got["requestDone"], got["drawn"]), (False, True, 0), load)


@unittest.skipUnless(HAS_NODE, "node not installed")
class PacingSkipAndReducedMotion(unittest.TestCase):
    def test_a_full_day_aims_for_about_fifteen_to_thirty_seconds(self):
        got = js(f'''
const T = Gs.TIMING;
const n = Gs.streamSteps({json.dumps(PAYLOAD)}).length;
const per = Math.max(T.lineMin, Math.min(T.lineMax, T.target / n));
console.log(JSON.stringify({{ n, total: T.start + per * n + T.gamePause * {len(PAYLOAD["games"])}, skipAfter: T.skipAfter, per }}));''')
        self.assertGreaterEqual(got["total"], 15000)
        self.assertLessEqual(got["total"], 32000)
        self.assertEqual(got["skipAfter"], 2000)
        src = (WEB / "js" / "dog-gematria-stream.js").read_text(encoding="utf-8")
        self.assertRegex(src, r"skipAfter:\s*2000")

    def test_a_short_day_is_simply_shorter_not_padded(self):
        got = js(f'''
const T = Gs.TIMING;
const small = {json.dumps(analysis_payload(matches=BIG_DAY[:2], limit=2))};
const n = Gs.streamSteps(small).length;
const per = Math.max(T.lineMin, Math.min(T.lineMax, T.target / n));
console.log(JSON.stringify({{ n, per, total: per * n }}));''')
        self.assertLessEqual(got["per"], 650)
        self.assertLess(got["total"], 22000)

    def test_a_skip_button_shows_after_the_wait_and_fast_forwards_every_line(self):
        got = run_stream('''
const t = { ...Gs.TIMING, lineMin: 40, lineMax: 40, gamePause: 0, start: 5, skipAfter: 120 };
const run = Gs.runGematriaStream({ body, load: async () => payload, speed: 1, timing: t });
await sleep(60);
const early = byHook(body, "gematria-skip")[0].hasAttribute("hidden");
await sleep(120);
const late = byHook(body, "gematria-skip")[0].hasAttribute("hidden");
const partial = byHook(body, "gematria-line").length;
byHook(body, "gematria-skip")[0].click();
const out = await run;
console.log(JSON.stringify({ early, late, partial, total: out.steps.length, drawn: byHook(body, "gematria-line").length, skipped: out.skipped }));''')
        self.assertEqual((got["early"], got["late"]), (True, False))
        self.assertLess(got["partial"], got["total"])
        self.assertEqual(got["drawn"], got["total"], "a skip still draws every real line")
        self.assertTrue(got["skipped"])

    def test_reduced_motion_draws_nothing_here_waits_on_no_timer_and_hands_back_the_payload(self):
        got = run_stream('''
globalThis.timerCount = 0;
const out = await Gs.runGematriaStream({ body, load: async () => payload, reduced: true });
console.log(JSON.stringify({ ok: out.ok, static: out.static, timers: globalThis.timerCount, drawn: byHook(body, "gematria-stream").length, hasPayload: !!out.payload }));''')
        self.assertEqual((got["ok"], got["static"], got["timers"], got["drawn"], got["hasPayload"]), (True, True, 0, 0, True))

    def test_every_motion_rule_sits_inside_a_no_preference_query(self):
        css = (WEB / "css" / "gematria-stream.css").read_text(encoding="utf-8")
        self.assertNotRegex(css, r"\banimation\s*:")
        self.assertNotRegex(css, r"@keyframes")
        self.assertIn('@import url("gematria-stream.css")', (WEB / "css" / "dog-kit.css").read_text(encoding="utf-8"))


@unittest.skipUnless(HAS_NODE, "node not installed")
class EscapingAndWords(unittest.TestCase):
    EVIL = "<img src=x onerror=alert(1)> & <script>alert(2)</script>"

    def test_a_team_name_that_is_markup_stays_text(self):
        evil = json.loads(json.dumps(PAYLOAD))
        evil["games"] = evil["games"][:2]
        evil["games"][0]["game"] = self.EVIL
        evil["games"][0]["lines"][0]["text"] = self.EVIL
        evil["games"][1]["lines"][-1]["text"] = "Pass: " + self.EVIL
        got = run_stream('''
await Gs.runGematriaStream({ body, load: async () => payload, speed: 0 });
const fold = Gs.analysisLog(payload);
const tags = new Set(); walk(body, (n) => tags.add(n.tag)); walk(fold, (n) => tags.add(n.tag));
const texts = []; walk(body, (n) => { n.childNodes.forEach((c) => { if (c.nodeType === 3) texts.push(c.text); }); });
const titles = []; walk(body, (n) => { if (n.attrs.title) titles.push(n.attrs.title); });
console.log(JSON.stringify({ tags: [...tags], evilText: texts.filter((t) => t.includes("<img")).length, titles: titles.filter((t) => t.includes("<img")).length }));''', payload=evil)
        self.assertNotIn("img", got["tags"])
        self.assertNotIn("script", got["tags"])
        self.assertGreaterEqual(got["evilText"], 2, "the markup is on screen as plain text")
        self.assertEqual(got["titles"], 0)

    def test_the_module_builds_nothing_from_html_strings(self):
        for name in ("dog-gematria-stream.js", "dog-fire.js", "dog-ask.js"):
            src = (WEB / "js" / name).read_text(encoding="utf-8")
            for banned in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function"):
                self.assertNotIn(banned, src, f"{name}: {banned}")

    def test_the_words_make_no_claim_and_never_say_dog(self):
        src = (WEB / "js" / "dog-gematria-stream.js").read_text(encoding="utf-8")
        lits = re.findall(r'"((?:[^"\\\n]|\\.)*)"|`((?:[^`\\]|\\.)*)`', src)
        text = " ".join(a or b for a, b in lits)
        self.assertIsNone(re.search(r"\b(better|improve\w*|stronger|smarter|profit\w*|edge|ROI|proven|will win|guarantee\w*|Bet Check)\b", text, re.I))
        self.assertIsNone(re.search(r"\bdogs?\b(?!-)", re.sub(r"data-[a-z-]+|\.dk-|dog-avatar|dogBadge|dog\.", "", text)))


# ---------------------------------------------------------------------------------------------------
# through the hound page: the real script, the real HTML skeleton
# ---------------------------------------------------------------------------------------------------

def counts_day(n_started=12, n_checked=48):
    games = lambda tag, n: [{"game": f"{tag} Away {i} @ {tag} Home {i}", "start_utc": "2026-10-22T23:10:00Z", "start_et": "7:10 pm ET"} for i in range(n)]   # noqa: E731
    counts = {"total": n_started + n_checked, "started": n_started, "later": 0, "checked_now": n_checked}
    return {"counts": counts, "counts_line": f"{n_started + n_checked} games today · {n_started} started · {n_checked} checked now",
            "groups": [{"key": "started", "label": "Started", "games": games("S", n_started), "more": 0},
                       {"key": "checked_now", "label": "Checked now", "games": games("C", min(n_checked, 40)), "more": max(0, n_checked - 40)}]}


def day_payload(**over):
    why = {"checked": 60, "placed": 0, "counts": [{"code": "no_numbers", "label": "numbers didn't line up", "count": 52},
                                                  {"code": "too_few_books", "label": "too few books", "count": 8}],
           "text": "60 checked: 52 numbers didn't line up · 8 too few books", "by_event": {}}
    base = dict(picks=[], placed_now=0, before=[], headline="Nothing new fit just now; the reasons are below.", day=counts_day(), why=why,
                next_check={"game": "Boston Celtics @ New York Knicks", "when_utc": "2026-10-22T22:10:00Z", "what": "its rule is checked 60 minutes before the start"},
                slate={"today_state": "open", "line": "12 started today. 48 games still ahead today. 14 inside my placing window now.",
                       "started": [], "in_window": []},
                next_game=None, live_elsewhere="Live now in other sports: 14 games (tennis, cricket)")
    base.update(over)
    return unleash_day(**base)


@unittest.skipUnless(HAS_NODE, "node not installed")
class TheCompactDay(unittest.TestCase):
    def day(self, **over):
        return run_page("hound", routes=dog_routes(unleash_payload=day_payload(**over)), search=f"?id={HID}", stored={"aisportsanalysis.invite_token": "tok"},
                        actions=[dict(do="click", sel=hook("fire-btn"), wait=150, capture=[
                            q("counts", hook("fire-counts")), q("fold", hook("fire-games"), "count"), q("toggle", hook("fire-games-toggle")),
                            q("items", ".dk-games__item", "count"), q("groups", ".dk-games__head", "texts"),
                            q("why", hook("unleash-why")), q("why_list", hook("unleash-why-list"), "count"),
                            q("next", hook("unleash-next"), "texts"), q("fire_next", hook("fire-next-game"), "count"),
                            q("link", hook("fire-live-link"), "texts"), q("links", hook("fire-live-link"), "count"),
                            q("heads", ".dk-headline", "texts"), q("slate", hook("fire-slate"), "count"),
                            q("prose", hook("dog-fire")), q("lists", ".dk-misses", "count")])])["captures"]["0"]

    def test_the_day_is_one_tidy_counts_block_with_the_games_folded_away(self):
        c = self.day()
        self.assertEqual(c["counts"], "60 games today · 12 started · 48 checked now")
        self.assertEqual(c["fold"], 1)
        self.assertEqual(c["toggle"], "See all games")
        self.assertEqual(c["groups"], ["Started (12)", "Checked now (48)"])
        self.assertEqual(c["items"], 12 + 40 + 1, "every listed game once, and one line for the games past the cap")

    def test_no_game_is_named_outside_the_fold(self):
        c = self.day()
        for line in c["heads"] + [c["counts"], c["why"], c["link"][0]]:
            self.assertNotIn("@", line)
        self.assertNotIn("Already started today", c["prose"])
        self.assertNotIn("Inside my placing window now:", c["prose"])
        self.assertEqual(c["slate"], 0, "an open day's sentence only repeated the counts")

    def test_the_reasons_are_one_line_with_no_list_under_it(self):
        c = self.day()
        self.assertEqual(c["why"], "60 checked: 52 numbers didn't line up · 8 too few books")
        self.assertEqual(c["why_list"], 0)

    def test_the_next_game_is_said_once_and_the_live_line_is_one_small_link(self):
        c = self.day(next_game="Next game: Thu 7:10 PM — A at B")
        self.assertEqual(len(c["next"]), 1)
        self.assertTrue(c["next"][0].startswith("Next game it checks: Boston Celtics @ New York Knicks"))
        self.assertEqual(c["fire_next"], 0, "the second 'Next game' line is dropped")
        self.assertEqual((c["links"], c["link"]), (1, ["Live now in other sports: 14 games (tennis, cricket)"]))

    def test_a_day_that_waits_for_another_day_keeps_its_sentence(self):
        c = self.day(slate={"today_state": "started", "line": "Tonight's games already started (12). Next games I can bet: Thursday.", "started": [], "in_window": []})
        self.assertEqual(c["slate"], 1)

    def test_no_counts_no_block(self):
        c = self.day(day={"counts": {"total": 0, "started": 0, "later": 0, "checked_now": 0}, "counts_line": "", "groups": []})
        self.assertEqual((c["fold"], c["items"]), (0, 0))


@unittest.skipUnless(HAS_NODE, "node not installed")
class OnTheHoundPage(unittest.TestCase):
    def go(self, gematria, reduced=True):
        kit = {"dog_id": HID, "kind": "user", "name": "Closer", "status": "running", "is_owner": True, "signed_in": True, "can_fire": True,
               "can_record_manual": True, "can_customize": True, "can_suggest": False, "look": None, "gematria": gematria,
               "feedback": {"good": 0, "bad": 0, "notes": 0, "by_kind": {}, "by_target": {}, "suggestions": 0},
               "manual": {"limit_per_day": 5, "remaining_today": 5}, "builder_href": f"build-a-hound.html?from={HID}", "paper_only": True}
        routes = dog_routes(kit=kit, unleash_payload=day_payload())
        routes[f"/hounds/{HID}/analysis"] = [200, PAYLOAD]
        return run_page("hound", routes=routes, search=f"?id={HID}", stored={"aisportsanalysis.invite_token": "tok"}, reducedMotion=reduced,
                        actions=[dict(do="click", sel=hook("fire-btn"), wait=200, capture=[
                            q("fold", hook("gematria-fold"), "count"), q("lines", hook("gematria-line"), "count"), q("headline", hook("unleash-headline")),
                            q("stream", hook("gematria-stream"), "count"), q("counts", hook("fire-counts"))])])

    def test_a_gematria_hounds_unleash_fetches_the_analysis_and_folds_it_under_the_day(self):
        out = self.go(True)
        c = out["captures"]["0"]
        self.assertIn(f"/hounds/{HID}/analysis", out["gets"])
        self.assertEqual(c["fold"], 1)
        self.assertEqual(c["lines"], len(lines_of(PAYLOAD)) + len(expected_frames(PAYLOAD)) + 1)
        self.assertEqual(c["stream"], 0, "reduced motion: nothing is played, the day is shown at once")
        self.assertTrue(c["headline"])
        self.assertTrue(any(p["url"] == f"/hounds/{HID}/unleash" for p in out["posts"]))

    def test_any_other_hound_never_asks_for_it(self):
        out = self.go(False)
        self.assertNotIn(f"/hounds/{HID}/analysis", out["gets"])
        self.assertEqual(out["captures"]["0"]["fold"], 0)


# ---------------------------------------------------------------------------------------------------
# a phone
# ---------------------------------------------------------------------------------------------------

PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Gematria fixture</title><link rel="stylesheet" href="/web/css/base.css"><link rel="stylesheet" href="/web/css/hound-page.css"><link rel="stylesheet" href="/web/css/dog-kit.css"></head>
<body><main id="box" style="padding:0 16px"></main>
<script type="module">
import { renderUnleashDay } from "/web/js/dog-fire.js";
import { runGematriaStream, analysisLog } from "/web/js/dog-gematria-stream.js";
const payload = %s; const day = %s;
const box = document.getElementById("box");
const host = document.createElement("div"); const dayBox = document.createElement("div");
box.appendChild(dayBox); box.appendChild(host);
renderUnleashDay(dayBox, day, { name: "Closer", id: "closer" });
const played = await runGematriaStream({ body: host, load: async () => payload, speed: 0 });
box.appendChild(analysisLog(payload)).setAttribute("open", "");
document.querySelector("[data-hook='fire-games']").setAttribute("open", "");
</script></body></html>"""


@unittest.skipUnless(HAS_NODE and CHROME, "node and a Chrome/Chromium binary are needed")
class AtPhoneWidths(unittest.TestCase):
    WIDTHS = (375, 390)

    @classmethod
    def setUpClass(cls):
        import subprocess
        long_names = json.loads(json.dumps(PAYLOAD))
        for g in long_names["games"][:3]:
            g["game"] = "Wolverhampton Wanderers Football Club of the Midlands " + "Supercalifragilisticexpialidocious" * 2
            g["lines"][0]["text"] += " " + "Pneumonoultramicroscopicsilicovolcanoconiosis" * 3
        day = day_payload(day=counts_day(30, 40))
        day["day"]["groups"][0]["games"][0]["game"] = "Wolverhampton Wanderers Football Club " + "Supercalifragilisticexpialidocious" * 2
        html = (PAGE % (json.dumps(long_names), json.dumps(day))).encode("utf-8")
        inner = make_handler({})

        class Handler(inner):
            def do_GET(self):
                if self.path.split("?")[0] == "/fixture.html":
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(html)))
                    self.end_headers()
                    self.wfile.write(html)
                    return
                return super().do_GET()

        cls.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{cls.server.server_address[1]}"
        proc = subprocess.run(["node", str(HERE / "overflow_widths.mjs"), CHROME, base, ",".join(str(w) for w in cls.WIDTHS), "/fixture.html"],
                              capture_output=True, text=True, encoding="utf-8", timeout=240)
        lines = [ln for ln in proc.stdout.splitlines() if ln.startswith("[")]
        if proc.returncode != 0 or not lines:
            raise AssertionError(f"overflow script failed ({proc.returncode}): {proc.stderr[-1500:]}")
        cls.results = json.loads(lines[-1])

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def test_measured_at_375_and_390(self):
        self.assertEqual([r["iw"] for r in self.results], list(self.WIDTHS))
        for r in self.results:
            self.assertGreater(r["h"], 600, f"the fixture rendered almost nothing: {r}")

    def test_nothing_scrolls_sideways(self):
        bad = [r for r in self.results if r["sw"] > r["iw"] + 1]
        self.assertEqual(bad, [], "wider than the phone: " + json.dumps(bad, indent=1))


if __name__ == "__main__":
    unittest.main()
