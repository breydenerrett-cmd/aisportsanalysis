"""The wait screen of a fine-tune or a rebuild: a game of fetch, or a loading screen (web/js/fetch-game.js, web/css/fetch-game.css).

Owner request 2026-10-29: the training waits showed one line of text for a minute or two. "Have a game for fetch ready and show the
option to remove the waiting game ... tell the user here's a waiting game while the advanced AI thinks ... but show the option to just
have a loading screen that's better and engaging still."

  * IT RUNS FOR REAL under node over a small fake DOM with a controllable requestAnimationFrame, so a throw, a run and a catch are
    stepped frame by frame and the score is read back.
  * NOTHING IS LEFT RUNNING. destroy() leaves no animation frame, no timer and no interval pending, mid-throw or idle, and an idle
    game asks for no frames at all. There is no network call anywhere.
  * THE CHOICE PERSISTS (localStorage "lh.waitMode"), the best score is the session's (sessionStorage), and storage that throws is
    no storage: the game is the default; with reduced motion the loading screen is.
  * IT IS TOLD THE TRUTH about what the page is doing: the heading, the one polite status line, the box's label, the keyboard throw.
  * THE TRAINING SHEET uses it: it appears beside the status line while a plan or proposal is in flight and is gone the moment the
    server answers, whether the answer is a card or a refusal (tests below, run on the real kennel page).
"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

from tests import test_hounds_interact_web as interact_web
from tests import test_hounds_rites_web as rites_web
from tests.hounds_web_runner import HAS_NODE, run_js, run_page

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
hook, q = interact_web.hook, interact_web.q
click, kennel_routes, dog, SIGNED = rites_web.click, rites_web.kennel_routes, rites_web.dog, rites_web.SIGNED

# A small DOM that can run the module for real, with an animation-frame queue the test steps by hand and counters for everything that
# could be left running. ``OPTS`` (set by the test) chooses the storage behaviour and the reduced-motion answer.
PRELUDE = r'''
class Txt { constructor(t) { this.nodeType = 3; this.text = String(t); this.parentNode = null; } get textContent() { return this.text; } set textContent(v) { this.text = String(v); } }
class El {
  constructor(tag, ns) { this.nodeType = 1; this.tag = tag; this.localName = String(tag).toLowerCase(); this.attrs = {}; this.childNodes = []; this.parentNode = null; this.listeners = {}; this.style = {}; this.rect = null; }
  get children() { return this.childNodes.filter((c) => c.nodeType === 1); }
  get firstChild() { return this.childNodes[0] || null; }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; }
  removeAttribute(k) { delete this.attrs[k]; }
  hasAttribute(k) { return k in this.attrs; }
  get hidden() { return "hidden" in this.attrs; }
  set hidden(v) { if (v) this.attrs.hidden = ""; else delete this.attrs.hidden; }
  appendChild(c) { if (c.parentNode) c.parentNode.removeChild(c); c.parentNode = this; this.childNodes.push(c); return c; }
  insertBefore(c, ref) { if (c.parentNode) c.parentNode.removeChild(c); const i = ref ? this.childNodes.indexOf(ref) : -1; c.parentNode = this; if (i < 0) this.childNodes.push(c); else this.childNodes.splice(i, 0, c); return c; }
  removeChild(c) { const i = this.childNodes.indexOf(c); if (i >= 0) this.childNodes.splice(i, 1); c.parentNode = null; return c; }
  set textContent(v) { this.childNodes = []; if (String(v) !== "") { const t = new Txt(v); t.parentNode = this; this.childNodes.push(t); } }
  get textContent() { return this.childNodes.map((c) => c.textContent).join(""); }
  addEventListener(t, f) { (this.listeners[t] ||= []).push(f); }
  removeEventListener(t, f) { this.listeners[t] = (this.listeners[t] || []).filter((x) => x !== f); }
  fire(type, evt = {}) { const e = Object.assign({ type, target: this, preventDefault() { e.defaultPrevented = true; } }, evt); (this.listeners[type] || []).forEach((f) => f(e)); return e; }
  click() { return this.fire("click"); }
  getBoundingClientRect() { return this.rect || { left: 0, top: 0, width: 360, height: 220 }; }
}
globalThis.document = { createElement: (t) => new El(t), createElementNS: (ns, t) => new El(t, ns), createTextNode: (t) => new Txt(t) };
document.body = new El("body");
document.documentElement = new El("html");
document.querySelector = () => null;
const walk = (n, f) => { if (n && n.nodeType === 1) { f(n); n.childNodes.forEach((k) => walk(k, f)); } };
const find = (root, pred) => { const out = []; walk(root, (n) => { if (pred(n)) out.push(n); }); return out; };
const byHook = (root, name) => find(root, (n) => n.attrs["data-hook"] === name);
const one = (root, name) => byHook(root, name)[0] || null;

// ---- everything that could be left running -----------------------------------------------------------------------
const raf = new Map(); let rafId = 0; let clock = 0;
globalThis.requestAnimationFrame = (fn) => { rafId += 1; raf.set(rafId, fn); return rafId; };
globalThis.cancelAnimationFrame = (id) => { raf.delete(id); };
const timers = new Map(); let timerId = 0; const realSetTimeout = globalThis.setTimeout;
globalThis.setTimeout = (fn, ms) => { timerId += 1; const id = timerId; timers.set(id, { fn, ms }); return id; };
globalThis.clearTimeout = (id) => { timers.delete(id); };
const intervals = new Map();
globalThis.setInterval = (fn, ms) => { timerId += 1; intervals.set(timerId, fn); return timerId; };
globalThis.clearInterval = (id) => { intervals.delete(id); };
const runTimers = () => { for (const [id, t] of [...timers]) { timers.delete(id); t.fn(); } };
const frames = (n, dt = 16) => { for (let i = 0; i < n; i += 1) { clock += dt; const due = [...raf]; raf.clear(); due.forEach(([, fn]) => fn(clock)); } };
let fetchCalls = 0;
globalThis.fetch = () => { fetchCalls += 1; throw new Error("the wait screen must not touch the network"); };
const pending = () => ({ raf: raf.size, timers: timers.size, intervals: intervals.size });

// ---- the window, its storage and its events ----------------------------------------------------------------------
const mem = (seed) => { const m = new Map(Object.entries(seed || {})); return { getItem: (k) => (m.has(k) ? m.get(k) : null), setItem: (k, v) => { m.set(k, String(v)); }, removeItem: (k) => { m.delete(k); }, m }; };
const OPTS = globalThis.OPTS || {};
const local = mem(OPTS.local), session = mem(OPTS.session);
const events = []; const winListeners = {};
globalThis.window = {
  addEventListener: (t, f) => { (winListeners[t] ||= []).push(f); }, removeEventListener: (t, f) => { winListeners[t] = (winListeners[t] || []).filter((x) => x !== f); },
  dispatchEvent: (e) => { events.push(e); return true; }, location: { href: "", pathname: "/web/kennel.html" },
};
if (OPTS.storage === "methods") {
  const boom = () => { throw new Error("storage blocked"); };
  for (const s of [local, session]) { s.getItem = boom; s.setItem = boom; }
}
if (OPTS.storage === "accessor") {
  for (const key of ["localStorage", "sessionStorage"]) Object.defineProperty(globalThis.window, key, { configurable: true, get() { throw new Error("storage denied"); } });
} else { window.localStorage = local; window.sessionStorage = session; }
const HOST = new El("div"); document.body.appendChild(HOST);
const LOOK = { coat: "golden", style: "mascot", breed: "retriever" };
const DOG = { id: "u-1", name: "Rusty Pup", look: LOOK, version_no: 1 };
const FG = await import("./fetch-game.js");
const tapAt = (box, x, y) => box.fire("pointerdown", { clientX: x, clientY: y, button: 0 });
const ball = (root) => { const b = one(root, "wait-ball"); return { x: Number(b.attrs["data-x"]), y: Number(b.attrs["data-y"]) }; };
const out = (o) => console.log(JSON.stringify(o));
'''


def js(body: str, **opts):
    """Run ``body`` after the prelude. ``opts`` become ``OPTS`` (``local`` / ``session`` seeds, ``storage``: "methods" or "accessor")."""
    head = f"globalThis.OPTS = {json.dumps(opts)};\n"
    return run_js(head + PRELUDE + body, viewer=None)


def stage(root_js="root"):
    return f"one({root_js}, 'wait-stage').textContent"


@unittest.skipUnless(HAS_NODE, "node is not installed")
class TheGame(unittest.TestCase):
    def test_it_mounts_with_the_heading_the_status_line_and_the_boxs_label(self):
        got = js('''
const w = FG.mountWait(HOST, { dog: DOG, stageText: "Starting..." });
const root = one(HOST, "wait-ui");
const box = one(root, "wait-game");
out({ mode: root.attrs["data-mode"], heading: one(root, "wait-heading").textContent, stage: one(root, "wait-stage").textContent,
  role: one(root, "wait-stage").attrs.role, live: one(root, "wait-stage").attrs["aria-live"],
  box: { role: box.attrs.role, label: box.attrs["aria-label"], tabindex: box.attrs.tabindex },
  toggle: one(root, "wait-toggle").textContent, toggleTag: one(root, "wait-toggle").tag, toggleType: one(root, "wait-toggle").attrs.type,
  face: find(root, (n) => n.tag === "svg").length, score: one(root, "wait-score").textContent, best: one(root, "wait-best").textContent,
  statusRegions: find(root, (n) => n.attrs.role === "status").length, pending: pending() });''')
        self.assertEqual(got["mode"], "game")
        self.assertEqual(got["heading"], "Here's a game while the AI coach works through your request. This can take a moment.")
        self.assertEqual((got["stage"], got["role"], got["live"]), ("Starting...", "status", "polite"))
        self.assertEqual(got["statusRegions"], 1)                                    # one region speaks, not two
        self.assertEqual((got["box"]["role"], got["box"]["tabindex"]), ("button", "0"))
        self.assertIn("Tap anywhere in the box", got["box"]["label"])
        self.assertIn("Enter or Space", got["box"]["label"])
        self.assertEqual((got["toggle"], got["toggleTag"], got["toggleType"]), ("Just show the loading screen", "button", "button"))
        self.assertGreaterEqual(got["face"], 1)                                      # the hound's own avatar is drawn
        self.assertEqual((got["score"], got["best"]), ("Score 0", "Best 0"))
        self.assertEqual(got["pending"], {"raf": 0, "timers": 0, "intervals": 0})    # an idle game asks for nothing

    def test_a_throw_runs_the_hound_to_the_ball_and_back_for_one_point(self):
        got = js('''
const w = FG.mountWait(HOST, { dog: DOG });
const root = one(HOST, "wait-ui"); const box = one(root, "wait-game");
const states = new Set([box.attrs["data-state"]]);
tapAt(box, 250, 60);
const afterTap = { state: box.attrs["data-state"], pending: pending() };
const xs = [];
for (let i = 0; i < 400 && box.attrs["data-state"] !== "ready"; i += 1) { frames(1); states.add(box.attrs["data-state"]); xs.push(ball(root).x); }
out({ afterTap, states: [...states], score: one(root, "wait-score").textContent, best: one(root, "wait-best").textContent,
  pop: one(root, "wait-pop").textContent, popKind: one(root, "wait-pop").attrs["data-kind"], maxX: Math.max(...xs), distinctX: new Set(xs).size,
  pendingAtEnd: pending() });''')
        self.assertEqual(got["afterTap"]["state"], "flying")
        self.assertEqual(got["afterTap"]["pending"]["raf"], 1)                       # one frame requested because something moves
        self.assertEqual(got["states"][0], "ready")
        for s in ("flying", "chasing", "carrying", "ready"):
            self.assertIn(s, got["states"])
        self.assertEqual((got["score"], got["best"]), ("Score 1", "Best 1"))
        self.assertEqual((got["pop"], got["popKind"]), ("+1", "fetch"))
        self.assertGreaterEqual(got["maxX"], 200)                                    # the ball really went out toward the tap
        self.assertGreater(got["distinctX"], 20)                                     # tweened, not jumped
        self.assertEqual(got["pendingAtEnd"]["raf"], 1)                              # only the "+1" is still fading: then the loop stops

    def test_the_loop_stops_asking_for_frames_once_the_hound_is_idle_and_the_pop_is_gone(self):
        got = js('''
FG.mountWait(HOST, { dog: DOG });
const box = one(HOST, "wait-game");
tapAt(box, 220, 90); frames(400);
out({ pending: pending(), state: box.attrs["data-state"], popHidden: one(HOST, "wait-pop").hidden });''')
        self.assertEqual(got["state"], "ready")
        self.assertTrue(got["popHidden"])
        self.assertEqual(got["pending"], {"raf": 0, "timers": 0, "intervals": 0})

    def test_the_arc_peaks_where_the_tap_was_and_lands_on_the_ground_at_its_side(self):
        got = js('''
const from = { x: 60, y: 150 };
const arc = FG.throwArc(from, 280, 70, 200);
const pts = Array.from({ length: 101 }, (_, i) => FG.arcPoint(arc.from, arc.c, arc.to, i / 100));
const top = pts.reduce((a, b) => (b.y < a.y ? b : a));
out({ topY: Math.round(top.y), land: arc.to, start: pts[0], end: pts[100], peak: arc.peak, low: FG.throwArc(from, 280, 190, 200).peak });''')
        self.assertAlmostEqual(got["topY"], 70, delta=1)
        self.assertEqual(got["land"]["x"], 280)
        self.assertEqual(got["end"], {"x": 280, "y": got["land"]["y"]})
        self.assertEqual(got["start"], {"x": 60, "y": 150})
        self.assertLess(got["low"], 150)                                             # a tap near the ground is still a lob, never a throw into the dirt

    def test_tapping_the_ball_while_it_is_in_the_air_is_a_catch_for_three(self):
        got = js('''
FG.mountWait(HOST, { dog: DOG });
const root = one(HOST, "wait-ui"); const box = one(root, "wait-game");
tapAt(box, 300, 50);
frames(12);
const at = ball(root); const during = box.attrs["data-state"];
tapAt(box, at.x + 4, at.y - 3);                      // a finger near the ball
const afterCatch = { state: box.attrs["data-state"], score: one(root, "wait-score").textContent, pop: one(root, "wait-pop").textContent, kind: one(root, "wait-pop").attrs["data-kind"] };
frames(200);
out({ during, afterCatch, end: box.attrs["data-state"], score: one(root, "wait-score").textContent, best: one(root, "wait-best").textContent, pending: pending() });''')
        self.assertEqual(got["during"], "flying")
        self.assertEqual(got["afterCatch"], {"state": "catching", "score": "Score 3", "pop": "+3", "kind": "catch"})
        self.assertEqual((got["end"], got["score"], got["best"]), ("ready", "Score 3", "Best 3"))      # the catch is the whole fetch: no extra +1
        self.assertEqual(got["pending"]["raf"], 0)

    def test_a_tap_that_misses_the_ball_in_the_air_does_not_catch_and_does_not_throw_a_second_ball(self):
        got = js('''
FG.mountWait(HOST, { dog: DOG });
const root = one(HOST, "wait-ui"); const box = one(root, "wait-game");
tapAt(box, 300, 50); frames(12);
const at = ball(root);
tapAt(box, at.x + 120, at.y + 90);
const after = { state: box.attrs["data-state"], score: one(root, "wait-score").textContent };
frames(400);
out({ after, score: one(root, "wait-score").textContent });''')
        self.assertEqual(got["after"], {"state": "flying", "score": "Score 0"})
        self.assertEqual(got["score"], "Score 1")

    def test_enter_and_space_throw_from_the_keyboard_and_do_not_scroll_the_sheet(self):
        got = js('''
FG.mountWait(HOST, { dog: DOG });
const box = one(HOST, "wait-game");
const e1 = box.fire("keydown", { key: "Enter" });
const s1 = box.attrs["data-state"]; frames(400);
const e2 = box.fire("keydown", { key: " " }); const s2 = box.attrs["data-state"]; frames(400);
const e3 = box.fire("keydown", { key: "a" });
out({ s1, s2, prevented: [e1.defaultPrevented, e2.defaultPrevented, e3.defaultPrevented === true], score: one(HOST, "wait-score").textContent, state: box.attrs["data-state"] });''')
        self.assertEqual((got["s1"], got["s2"]), ("flying", "flying"))
        self.assertEqual(got["prevented"], [True, True, False])
        self.assertEqual((got["score"], got["state"]), ("Score 2", "ready"))

    def test_a_tap_that_lands_beside_the_hound_still_throws_a_real_throw(self):
        got = js('''
FG.mountWait(HOST, { dog: DOG });
const root = one(HOST, "wait-ui"); const box = one(root, "wait-game");
tapAt(box, 5, 5); const xs = []; for (let i = 0; i < 200 && box.attrs["data-state"] === "flying"; i += 1) { frames(1); xs.push(ball(root).x); }
out({ landX: xs[xs.length - 1] });''')
        self.assertGreaterEqual(got["landX"], 100)                                   # never dropped at the hound's feet

    def test_the_score_survives_a_switch_to_the_loading_screen_and_back(self):
        got = js('''
FG.mountWait(HOST, { dog: DOG });
const box = one(HOST, "wait-game");
tapAt(box, 220, 80); frames(400);
one(HOST, "wait-toggle").click(); const mid = { mode: one(HOST, "wait-ui").attrs["data-mode"], game: byHook(HOST, "wait-game").length, pending: pending() };
one(HOST, "wait-toggle").click();
out({ mid, mode: one(HOST, "wait-ui").attrs["data-mode"], score: one(HOST, "wait-score").textContent, best: one(HOST, "wait-best").textContent });''')
        self.assertEqual(got["mid"], {"mode": "loading", "game": 0, "pending": {"raf": 0, "timers": 0, "intervals": 0}})
        self.assertEqual((got["mode"], got["score"], got["best"]), ("game", "Score 1", "Best 1"))

    def test_switching_away_in_the_middle_of_a_throw_cancels_the_frame(self):
        got = js('''
FG.mountWait(HOST, { dog: DOG });
tapAt(one(HOST, "wait-game"), 250, 60); frames(5);
const during = pending(); one(HOST, "wait-toggle").click();
out({ during, after: pending() });''')
        self.assertEqual(got["during"]["raf"], 1)
        self.assertEqual(got["after"], {"raf": 0, "timers": 0, "intervals": 0})


@unittest.skipUnless(HAS_NODE, "node is not installed")
class NothingIsLeftRunning(unittest.TestCase):
    def test_destroy_mid_throw_leaves_no_frame_no_timer_and_no_interval(self):
        got = js('''
const w = FG.mountWait(HOST, { dog: DOG, delay: 5000 });
const early = { hidden: one(HOST, "wait-ui").hidden, pending: pending() };      // the reveal timer is the only thing waiting
runTimers();
tapAt(one(HOST, "wait-game"), 250, 60); frames(6);
const during = pending();
w.destroy();
const after = pending(); frames(10);
out({ early, during, after, later: pending(), inPage: byHook(document.body, "wait-ui").length + byHook(HOST, "wait-ui").length, fetchCalls });''')
        self.assertEqual(got["early"], {"hidden": True, "pending": {"raf": 0, "timers": 1, "intervals": 0}})
        self.assertEqual(got["during"]["raf"], 1)
        self.assertEqual(got["after"], {"raf": 0, "timers": 0, "intervals": 0})
        self.assertEqual(got["later"], {"raf": 0, "timers": 0, "intervals": 0})
        self.assertEqual(got["inPage"], 0)
        self.assertEqual(got["fetchCalls"], 0)

    def test_destroy_before_the_delayed_reveal_cancels_the_timer(self):
        got = js('''
const w = FG.mountWait(HOST, { dog: DOG, delay: 1500 });
const before = pending(); w.destroy(); w.destroy();
runTimers();
out({ before, after: pending(), inPage: byHook(HOST, "wait-ui").length });''')
        self.assertEqual(got["before"]["timers"], 1)
        self.assertEqual(got["after"], {"raf": 0, "timers": 0, "intervals": 0})
        self.assertEqual(got["inPage"], 0)

    def test_the_loading_screen_runs_no_script_at_all(self):
        got = js('''
const w = FG.mountWait(HOST, { dog: DOG });
one(HOST, "wait-toggle").click();
const mode = one(HOST, "wait-ui").attrs["data-mode"]; const p = pending(); w.destroy();
out({ mode, p, after: pending(), fetchCalls });''', local={"lh.waitMode": "loading"})
        self.assertEqual(got["p"], {"raf": 0, "timers": 0, "intervals": 0})
        self.assertEqual(got["after"], {"raf": 0, "timers": 0, "intervals": 0})
        self.assertEqual(got["fetchCalls"], 0)

    def test_a_box_taken_out_of_the_page_stops_its_own_loop(self):
        got = js('''
FG.mountWait(HOST, { dog: DOG });
const box = one(HOST, "wait-game");
tapAt(box, 250, 60); frames(3);
HOST.removeChild(one(HOST, "wait-ui"));                 // the caller cleared the sheet without calling destroy()
const during = pending(); frames(3);
out({ during, after: pending() });''')
        self.assertEqual(got["during"]["raf"], 1)
        self.assertEqual(got["after"], {"raf": 0, "timers": 0, "intervals": 0})

    def test_setting_the_stage_after_destroy_is_harmless(self):
        got = js('''
const w = FG.mountWait(HOST, { dog: DOG }); w.destroy(); w.setStage("late"); w.destroy();
out({ ok: true, inPage: byHook(HOST, "wait-ui").length });''')
        self.assertEqual(got["inPage"], 0)

    def test_a_missing_container_gives_a_do_nothing_handle_and_never_throws(self):
        got = js('''
const w = FG.mountWait(null, { dog: DOG }); w.setStage("x"); w.destroy();
const bad = FG.mountWait({ appendChild() { throw new Error("boom"); } }, { dog: DOG }); bad.setStage("x"); bad.destroy();
out({ ok: typeof w.destroy === "function" && typeof bad.destroy === "function" });''')
        self.assertTrue(got["ok"])


@unittest.skipUnless(HAS_NODE, "node is not installed")
class TheChoice(unittest.TestCase):
    def test_the_toggle_switches_and_remembers_the_choice(self):
        got = js('''
FG.mountWait(HOST, { dog: DOG, stageText: "Rehearsing the rules it has now..." });
const root = one(HOST, "wait-ui");
const game = { mode: root.attrs["data-mode"], toggle: one(root, "wait-toggle").textContent, heading: one(root, "wait-heading").textContent };
one(root, "wait-toggle").click();
const loading = { mode: root.attrs["data-mode"], toggle: one(root, "wait-toggle").textContent, heading: one(root, "wait-heading").textContent,
  stage: one(root, "wait-stage").textContent, trot: byHook(root, "wait-trot").length, bar: byHook(root, "wait-bar").length, box: byHook(root, "wait-game").length,
  barHidden: one(root, "wait-bar").attrs["aria-hidden"], saved: local.m.get("lh.waitMode") };
one(root, "wait-toggle").click();
out({ game, loading, again: root.attrs["data-mode"], saved: local.m.get("lh.waitMode") });''')
        self.assertEqual(got["game"]["toggle"], "Just show the loading screen")
        self.assertEqual(got["loading"]["mode"], "loading")
        self.assertEqual(got["loading"]["toggle"], "Play fetch while I wait")
        self.assertEqual(got["loading"]["stage"], "Rehearsing the rules it has now...")         # the same line, now the big one
        self.assertEqual((got["loading"]["trot"], got["loading"]["bar"], got["loading"]["box"]), (1, 1, 0))
        self.assertEqual((got["loading"]["barHidden"], got["loading"]["saved"]), ("true", "loading"))
        self.assertIn("working through your request", got["loading"]["heading"])
        self.assertNotIn("game", got["loading"]["heading"].lower())                              # the loading screen does not promise a game
        self.assertEqual((got["again"], got["saved"]), ("game", "game"))

    def test_the_saved_choice_wins_at_the_next_mount(self):
        loading = js('''FG.mountWait(HOST, { dog: DOG }); out({ mode: one(HOST, "wait-ui").attrs["data-mode"] });''', local={"lh.waitMode": "loading"})
        game = js('''FG.mountWait(HOST, { dog: DOG, reduced: true }); out({ mode: one(HOST, "wait-ui").attrs["data-mode"] });''', local={"lh.waitMode": "game"})
        junk = js('''FG.mountWait(HOST, { dog: DOG }); out({ mode: one(HOST, "wait-ui").attrs["data-mode"] });''', local={"lh.waitMode": "pinball"})
        self.assertEqual((loading["mode"], game["mode"], junk["mode"]), ("loading", "game", "game"))

    def test_storage_that_throws_means_the_game_and_the_toggle_still_works(self):
        for kind in ("methods", "accessor"):
            with self.subTest(storage=kind):
                got = js('''
FG.mountWait(HOST, { dog: DOG });
const root = one(HOST, "wait-ui");
const first = root.attrs["data-mode"];
tapAt(one(root, "wait-game"), 220, 80); frames(400);
one(root, "wait-toggle").click();
out({ first, second: root.attrs["data-mode"], score: FG.readBest(), mode: FG.readMode(false) });''', storage=kind)
                self.assertEqual(got["first"], "game")
                self.assertEqual(got["second"], "loading")                              # the switch works for this visit
                self.assertEqual((got["score"], got["mode"]), (0, "game"))

    def test_reduced_motion_defaults_to_the_loading_screen_without_bobbing(self):
        got = js('''
FG.mountWait(HOST, { dog: DOG, reduced: true });
const root = one(HOST, "wait-ui");
out({ mode: root.attrs["data-mode"], motion: root.attrs["data-motion"], cls: one(root, "wait-trot").attrs.class, pending: pending() });''')
        self.assertEqual((got["mode"], got["motion"]), ("loading", "reduced"))
        self.assertNotIn("bob", got["cls"])
        self.assertEqual(got["pending"], {"raf": 0, "timers": 0, "intervals": 0})

    def test_the_hound_bobs_on_the_loading_screen_unless_motion_is_reduced(self):
        got = js('''FG.mountWait(HOST, { dog: DOG }); out({ cls: one(HOST, "wait-trot") ? "" : "x", full: byHook(HOST, "wait-trot").length });''', local={"lh.waitMode": "loading"})
        full = js('''FG.mountWait(HOST, { dog: DOG }); out({ cls: one(HOST, "wait-trot").attrs.class });''', local={"lh.waitMode": "loading"})
        self.assertIn("bob", full["cls"])
        self.assertEqual(got["full"], 1)

    def test_reduced_motion_players_get_no_tween_the_ball_hangs_then_jumps(self):
        got = js('''
FG.mountWait(HOST, { dog: DOG, reduced: true });
const root = one(HOST, "wait-ui"); const box = one(root, "wait-game");
tapAt(box, 280, 70);
const seen = []; const pos = new Set(); const dogs = new Set();
for (let i = 0; i < 300 && box.attrs["data-state"] !== "ready"; i += 1) { frames(1); seen.push(box.attrs["data-state"]); const b = ball(root); pos.add(b.x + "," + b.y); dogs.add(one(root, "wait-dog").style.transform); }
frames(100);
out({ states: [...new Set(seen)], balls: pos.size, dogs: dogs.size, score: one(root, "wait-score").textContent, pending: pending() });''', local={"lh.waitMode": "game"})
        self.assertEqual(got["states"], ["flying", "chasing", "carrying", "settling", "ready"])
        self.assertLessEqual(got["balls"], 6)                                          # a handful of resting places, not a path
        self.assertLessEqual(got["dogs"], 4)                                           # the hound jumps, it does not run
        self.assertEqual(got["score"], "Score 1")
        self.assertEqual(got["pending"]["raf"], 0)

    def test_reduced_motion_can_still_catch_the_hanging_ball(self):
        got = js('''
FG.mountWait(HOST, { dog: DOG, reduced: true });
const root = one(HOST, "wait-ui"); const box = one(root, "wait-game");
tapAt(box, 280, 70); frames(5);
const at = ball(root); tapAt(box, at.x, at.y);
out({ score: one(root, "wait-score").textContent });''', local={"lh.waitMode": "game"})
        self.assertEqual(got["score"], "Score 3")

    def test_the_best_score_is_the_sessions_and_is_kept_in_session_storage(self):
        got = js('''
FG.mountWait(HOST, { dog: DOG });
const box = one(HOST, "wait-game");
const start = one(HOST, "wait-best").textContent;
tapAt(box, 220, 80); frames(400); tapAt(box, 220, 80); frames(400);
out({ start, best: one(HOST, "wait-best").textContent, saved: session.m.get("lh.fetchBest"), onDisk: local.m.has("lh.fetchBest") });''', session={"lh.fetchBest": "7"})
        self.assertEqual(got["start"], "Best 7")                                         # a better score than this visit's earlier one is still on show
        self.assertEqual(got["best"], "Best 7")                                          # 2 does not beat 7
        self.assertEqual(got["saved"], "7")
        self.assertFalse(got["onDisk"])                                                  # sessionStorage only

    def test_a_new_best_is_written_as_it_is_earned(self):
        got = js('''
FG.mountWait(HOST, { dog: DOG });
const box = one(HOST, "wait-game");
tapAt(box, 220, 80); frames(400); tapAt(box, 220, 80); frames(400);
out({ best: one(HOST, "wait-best").textContent, saved: session.m.get("lh.fetchBest") });''', session={"lh.fetchBest": "1"})
        self.assertEqual((got["best"], got["saved"]), ("Best 2", "2"))

    def test_a_junk_best_is_ignored(self):
        got = js('''out({ a: FG.readBest(), b: FG.readMode(true), c: FG.readMode(false) });''', session={"lh.fetchBest": "lots"}, local={"lh.waitMode": ""})
        self.assertEqual((got["a"], got["b"], got["c"]), (0, "loading", "game"))


@unittest.skipUnless(HAS_NODE, "node is not installed")
class TheStageLine(unittest.TestCase):
    def test_set_stage_changes_the_one_line_and_ignores_a_repeat(self):
        got = js('''
const w = FG.mountWait(HOST, { dog: DOG, stageText: "Starting..." });
const line = one(HOST, "wait-stage");
const first = line.childNodes[0];
w.setStage("Rehearsing the rules it has now..."); const second = line.childNodes[0];
w.setStage("Rehearsing the rules it has now..."); const third = line.childNodes[0];
w.setStage(null);
out({ text: line.textContent, sameNode: second === third });''')
        self.assertEqual(got["text"], "")                                              # null clears it rather than printing "null"
        self.assertTrue(got["sameNode"])                                                # a poll repeating the stage does not re-announce it

    def test_the_callers_own_status_line_is_hidden_while_this_shows_and_back_after(self):
        got = js('''
const mine = new El("p"); mine.setAttribute("data-hook", "training-plan-status"); mine.textContent = "Starting..."; HOST.appendChild(mine);
const w = FG.mountWait(HOST, { dog: DOG, stageText: mine.textContent, replaces: mine });
const during = { hidden: mine.hidden, text: mine.textContent };
w.destroy();
out({ during, after: mine.hidden, text: mine.textContent });''')
        self.assertEqual(got["during"], {"hidden": True, "text": "Starting..."})        # still in the page, with its words, for whoever reads it
        self.assertFalse(got["after"])

    def test_a_delayed_wait_shows_the_callers_line_until_it_appears(self):
        got = js('''
const mine = new El("p"); mine.textContent = "Preparing the proposal..."; HOST.appendChild(mine);
const w = FG.mountWait(HOST, { dog: DOG, replaces: mine, delay: 1500 });
const before = { mine: mine.hidden, wait: one(HOST, "wait-ui").hidden };
runTimers();
out({ before, after: { mine: mine.hidden, wait: one(HOST, "wait-ui").hidden }, pending: pending() });''')
        self.assertEqual(got["before"], {"mine": False, "wait": True})
        self.assertEqual(got["after"], {"mine": True, "wait": False})
        self.assertEqual(got["pending"]["timers"], 0)


class TheWordsAndTheStyles(unittest.TestCase):
    SRC = (WEB / "js" / "fetch-game.js").read_text(encoding="utf-8")
    CSS = (WEB / "css" / "fetch-game.css").read_text(encoding="utf-8")

    def test_the_copy_follows_the_owners_rules(self):
        quoted = re.findall(r'"((?:[^"\\\n]|\\.)*)"', self.SRC)
        text = " ".join(quoted).lower()
        for word in ("beta", "edge", "guarantee", "profit", "bet check"):
            self.assertNotIn(word, text)
        self.assertNotRegex(text, r"\bnew\b")
        self.assertNotRegex(text, r"\block\b")
        self.assertNotRegex(text, r"\bwin(?:s|ning)?\b")

    def test_no_network_no_storage_reached_for_outside_try_and_no_leftover_timers_by_construction(self):
        self.assertNotRegex(self.SRC, r"\bfetch\s*\(|XMLHttpRequest|sendBeacon|WebSocket|EventSource")
        self.assertNotIn("setInterval", self.SRC)
        for m in re.finditer(r"window\.(?:local|session)Storage", self.SRC):
            head = self.SRC[:m.start()]
            self.assertGreater(head.rfind("try {"), head.rfind("}\n"), "storage is touched outside a try at offset %d" % m.start())

    def test_text_is_always_text_content(self):
        self.assertNotIn("innerHTML", self.SRC)
        self.assertNotIn("insertAdjacentHTML", self.SRC)

    def test_every_animation_sits_inside_a_no_preference_media_query(self):
        outside = re.sub(r"@media \(prefers-reduced-motion: no-preference\) \{.*?\n\}\n", "", self.CSS, flags=re.S)
        outside = re.sub(r"@keyframes [\w-]+ \{.*?\}\s*\}", "", outside, flags=re.S)
        self.assertNotRegex(outside, r"\banimation\s*:")
        self.assertNotRegex(outside, r"\btransition\s*:")

    def test_the_box_is_full_width_about_220_tall_and_the_toggle_is_a_44px_target(self):
        box = re.search(r"\.fg__box \{(.*?)\}", self.CSS, flags=re.S).group(1)
        self.assertIn("width: 100%", box)
        self.assertIn("height: 220px", box)
        self.assertIn("touch-action: manipulation", box)
        self.assertRegex(re.search(r"\.fg__toggle \{(.*?)\}", self.CSS, flags=re.S).group(1), r"min-height: 44px")
        self.assertIn("focus-visible", self.CSS)

    def test_dog_kit_pulls_it_in_before_any_rule(self):
        kit = (WEB / "css" / "dog-kit.css").read_text(encoding="utf-8")
        at = kit.index('@import url("fetch-game.css")')
        first_rule = re.search(r"^[.#\w\[][^\n]*\{", kit, flags=re.M).start()
        self.assertLess(at, first_rule)                                                  # an @import after a rule is ignored by the browser
        for page in ("kennel.html", "hound.html"):
            self.assertIn("css/dog-kit.css", (WEB / page).read_text(encoding="utf-8"), page)


# ---------------------------------------------------------------------------------------------------------------
# the training sheet, on the real kennel page
OPEN = "[data-hook='dog-action-train']"
SHEET_Q = [q("ui", hook("wait-ui"), "count"), q("stage", hook("wait-stage")), q("hidden", hook("wait-ui"), "hidden"),
           q("status", hook("training-plan-status")), q("statusHidden", hook("training-plan-status"), "hidden"),
           q("proposing", hook("training-proposing")), q("proposingHidden", hook("training-proposing"), "hidden"),
           q("heading", hook("wait-heading")), q("toggle", hook("wait-toggle")), q("sheet", ".rt-sheet", "attr", attr="data-hook")]


def routes(**over):
    r = kennel_routes([dog("u-1")])
    r["/hounds/u-1/train/options"] = [200, {"fine_tune": {"available": True}, "rebuild": {"available": True, "reason": None, "used_today": 0,
                                                                                               "limit_per_day": 1, "left_today": 1}}]
    r.update(over)
    return r


def job(state="done", stage="Working", result=None, error=None):
    return [200, {"job_id": "j" * 24, "kind": "rebuild", "state": state, "stage": stage, "result": result, "error": error}]


def idle(label, ms, capture=None):
    """Let the page run ``ms`` more (the held server answer arrives meanwhile), touching nothing."""
    return {"do": "fire_timers", "label": label, "wait": ms, "capture": capture or []}


def flow(rts, actions, **scenario):
    return run_page("kennel", routes=rts, **SIGNED, **scenario, actions=actions)


CARD = {"kind": "minor", "found": False, "name": "Rusty Pup", "message": "None of the small changes did better.", "rebuild_offer": True,
        "rehearsal": {"label": "Rehearsal (hindsight, not counted in the record)", "days": 30, "counted": False, "before": None, "after": None,
                      "sample_text": "", "note": ""}}


@unittest.skipUnless(HAS_NODE, "node is not installed")
class OnTheTrainingSheet(unittest.TestCase):
    def test_the_plan_wait_shows_the_game_beside_the_status_line_and_both_go_when_the_card_arrives(self):
        rts = routes(**{"POST /hounds/u-1/train/fine-tune": job("done", result=CARD)})
        out = flow(rts, [click(OPEN, "a"), click(hook("training-fine-tune"), "during", wait=900, capture=SHEET_Q),
                         idle("after", 1500, SHEET_Q)], delay={"POST /hounds/u-1/train/fine-tune": 1800})
        during = out["captures"]["during"]
        self.assertEqual(during["ui"], 1)                                              # the wait screen is up (after its short delay)
        self.assertEqual(during["status"], "Starting...")                              # the status line is still in the page, with its words
        self.assertTrue(during["statusHidden"])                                        # ... and not said twice
        self.assertEqual(during["stage"], "Starting...")
        self.assertIn("Here's a game while the AI coach works", during["heading"])
        self.assertEqual(during["toggle"], "Just show the loading screen")
        self.assertEqual(during["sheet"], "training-planning")
        self.assertEqual(out["captures"]["after"]["ui"], 0)                            # the card came and took the wait screen with it
        self.assertEqual(out["captures"]["after"]["sheet"], "training-plan-sheet")

    def test_the_wait_is_gone_the_moment_the_server_answers_with_a_card(self):
        rts = routes(**{"POST /hounds/u-1/train/fine-tune": job("done", result=CARD)})
        out = flow(rts, [click(OPEN, "a"), click(hook("training-fine-tune"), "card", wait=1400, capture=SHEET_Q + [q("none", hook("plan-none"))])],
                   delay={"POST /hounds/u-1/train/fine-tune": 700})
        cap = out["captures"]["card"]
        self.assertEqual(cap["ui"], 0)
        self.assertEqual(cap["sheet"], "training-plan-sheet")
        self.assertIn("None of the", cap["none"])

    def test_the_wait_is_gone_when_the_server_refuses(self):
        refusal = [429, {"detail": {"error": "daily_limit", "message": "You have used today's 1 full rebuild. Fine-tune is still open, and the rebuild resets tomorrow (UTC)."}}]
        out = flow(routes(**{"POST /hounds/u-1/train/rebuild": refusal}),
                   [click(OPEN, "a"), click(hook("training-rebuild"), "r", wait=900, capture=SHEET_Q + [q("text", hook("training-refused"))])],
                   delay={"POST /hounds/u-1/train/rebuild": 300})
        cap = out["captures"]["r"]
        self.assertEqual(cap["ui"], 0)
        self.assertEqual(cap["sheet"], "training-refused-sheet")
        self.assertIn("used today's 1 full rebuild", cap["text"])

    def test_a_job_that_fails_ends_the_wait_too(self):
        failed = job("failed", error={"code": "job_failed", "message": "That step could not finish just now. Nothing was changed."})
        out = flow(routes(**{"POST /hounds/u-1/train/fine-tune": failed}),
                   [click(OPEN, "a"), click(hook("training-fine-tune"), "r", wait=700, capture=SHEET_Q + [q("text", hook("training-refused"))])])
        cap = out["captures"]["r"]
        self.assertEqual(cap["ui"], 0)
        self.assertIn("could not finish", cap["text"])

    def test_the_stage_text_the_server_reports_reaches_the_screen_and_the_status_line(self):
        # the job is still running on the first answer and says what it is doing; the status line gets the same words with its dots
        running = job("running", stage="Rehearsing the rules it has now")
        out = flow(routes(**{"POST /hounds/u-1/train/rebuild": running, "/hounds/u-1/train/job/" + "j" * 24: running}),
                   [click(OPEN, "a"), click(hook("training-rebuild"), "w", wait=1000, capture=SHEET_Q)])
        cap = out["captures"]["w"]
        self.assertEqual(cap["status"], "Rehearsing the rules it has now...")
        self.assertEqual(cap["stage"], "Rehearsing the rules it has now...")
        self.assertEqual(cap["ui"], 1)

    def test_reduced_motion_shows_the_loading_screen_on_the_sheet(self):
        rts = routes(**{"POST /hounds/u-1/train/rebuild": job("running", stage="Working")})
        out = flow(rts, [click(OPEN, "a"), click(hook("training-rebuild"), "w", wait=900, capture=SHEET_Q + [q("mode", hook("wait-ui"), "attr", attr="data-mode"),
                                                                                                          q("game", hook("wait-game"), "count")])],
                   reducedMotion=True)
        cap = out["captures"]["w"]
        self.assertEqual((cap["mode"], cap["game"]), ("loading", 0))
        self.assertEqual(cap["toggle"], "Play fetch while I wait")

    def test_the_game_toggle_works_on_the_sheet_and_is_remembered(self):
        rts = routes(**{"POST /hounds/u-1/train/rebuild": job("running", stage="Working")})
        out = flow(rts, [click(OPEN, "a"), click(hook("training-rebuild"), "w", wait=900),
                         click(hook("wait-toggle"), "t", wait=100, capture=[q("mode", hook("wait-ui"), "attr", attr="data-mode"), q("toggle", hook("wait-toggle"))])])
        self.assertEqual(out["captures"]["t"]["mode"], "loading")
        self.assertEqual(out["storedAfter"].get("lh.waitMode"), "loading")

    def test_the_proposal_wait_appears_after_its_short_delay_and_goes_with_the_answer(self):
        # Coach's usual check-up -> (diagnose / assess answer 404 here, so that phase is skipped) -> the proposal request is held, then refused
        rts = routes(**{"POST /hounds/u-1/train/propose": [409, {"detail": {"error": "open_tickets", "message": "It has an open ticket."}}]})
        out = flow(rts, [click(OPEN, "a"), click(hook("training-go"), "held", wait=2200, capture=SHEET_Q), idle("gone", 2200, SHEET_Q)],
                   delay={"POST /hounds/u-1/train/propose": 3400}, reducedMotion=True)
        held = out["captures"]["held"]
        self.assertEqual(held["ui"], 1)
        self.assertEqual(held["proposing"], "Preparing the proposal...")
        self.assertTrue(held["proposingHidden"])
        self.assertEqual(out["captures"]["gone"]["ui"], 0)
        self.assertEqual(out["captures"]["gone"]["sheet"], "training-refused-sheet")

    def test_a_quick_proposal_never_flashes_the_wait_screen(self):
        rts = routes(**{"POST /hounds/u-1/train/propose": [409, {"detail": {"error": "open_tickets", "message": "It has an open ticket."}}]})
        out = flow(rts, [click(OPEN, "a"), click(hook("training-go"), "quick", wait=900, capture=SHEET_Q)], reducedMotion=True)
        cap = out["captures"]["quick"]
        self.assertEqual((cap["ui"], cap["sheet"]), (0, "training-refused-sheet"))

if __name__ == "__main__":
    unittest.main()
