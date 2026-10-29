/**
 * THE WAIT SCREEN: a game of fetch, or a loading screen, while the AI coach works (owner request 2026-10-29: "have a game for fetch ready
 * and show option to remove waiting game ... tell user here's waiting game while the advanced AI thinks and processes your request, this may
 * take a moment, but show the option to just have a loading screen that's better and engaging still").
 *
 * WHY IT EXISTS. A fine-tune or a full rebuild is a background job that takes a minute or two; the page used to show one line of text
 * ("Preparing the proposal...", "Rehearsing the rules it has now...") the whole time. This is shown beside that line while the server works,
 * and is taken away the moment it answers, success or refusal. It never delays the answer: nothing here waits on the game.
 *
 *   mountWait(container, { dog, stageText, reduced, replaces, delay }) -> { setStage(text), destroy() }
 *
 *   GAME      tap (or click, or Enter / Space) in the box to throw the ball; it arcs to the tap's side, the hound runs to it and brings
 *             it back (+1). Tap the ball while it is in the air and the hound's owner "catches it mid-air" (+3). The best score of the
 *             browser session is kept in sessionStorage. The hound is drawn by dogFace (dog-avatar.js), the same art as the kennel cards.
 *   LOADING   no game: the hound trotting in place, the stage text big, and a slim indeterminate bar. Still alive, nothing to play.
 *   TOGGLE    a link under either one switches to the other; the choice is kept in localStorage ("lh.waitMode"). Without storage the game
 *             is the default; with reduced motion the loading screen is.
 *
 * NOTHING LEFT RUNNING. The game moves things with requestAnimationFrame only while something is moving (a throw, a run, a score pop) and
 * stops asking for frames when the hound is idle, so a person who never throws costs nothing. destroy() cancels the pending frame and
 * the reveal timer, so no timer outlives the wait; the loop also gives up on its own if its box is taken out of the page. There is no
 * network call anywhere in this file.
 *
 * REDUCED MOTION. The default is the loading screen, with no bobbing. If the person plays anyway there are no tweened arcs: the ball
 * hangs at the top of its throw (still there to catch), jumps to where it lands, and the hound jumps to it and back.
 *
 * ACCESSIBLE. The stage line is the one role="status" / aria-live="polite" region. The box is a role="button" with a label that says
 * what it does, and Enter or Space throw the ball. The bonus catch is a pointer skill and is optional. Everything the page says is
 * textContent. Copy rule: nothing here talks about winning or odds; the score is the game's own.
 */

import { h, clearNode } from "./hounds-core.js";
import { dogFace, setPose } from "./dog-avatar.js";

export const WAIT_MODE_KEY = "lh.waitMode";
export const BEST_KEY = "lh.fetchBest";
export const GAME_HEADING = "Here's a game while the AI coach works through your request. This can take a moment.";
export const LOADING_HEADING = "The AI coach is working through your request. This can take a moment.";
export const TO_LOADING = "Just show the loading screen";
export const TO_GAME = "Play fetch while I wait";
export const BOX_LABEL = "Fetch game. Tap anywhere in the box, or press Enter or Space, to throw the ball.";
export const HINT = "Tap to throw. Tap the ball while it is in the air to catch it for a bonus.";

/** Sizes in pixels and times in seconds. The box is about 220px tall on a phone (css/fetch-game.css); everything scales to the box it is in. */
export const TUNING = {
  dog: 56,                // the hound in the game
  bigDog: 88,             // the hound on the loading screen
  ball: 18,
  catchRadius: 32,        // how near a tap must be to the ball to catch it (a finger is bigger than a ball)
  groundPad: 18,          // the ground line sits this far above the bottom of the box
  minThrow: 70,           // the ball always lands at least this far from the hound
  flyMin: 0.55, flyMax: 1.15, flyPerPx: 0.0012,
  runSpeed: 380,          // pixels a second
  runMin: 0.25,
  settle: 0.15,           // the hound turning round to face the next throw, with the ball
  hold: 0.3,              // reduced motion: how long each jump holds before the next
  flyReduced: 0.6,
  back: 0.25,             // the caught ball coming back to the hound
  pop: 0.9,               // how long "+1" stays up
  maxStep: 0.05,          // a long gap between frames (a hidden tab) is played as this much, never as a jump
  keyTargets: [0.55, 0.8, 0.65, 0.9, 0.45],     // where Enter / Space throws, in turn, as a share of the box width
};

export const SCORE = { fetch: 1, catch: 3 };

// ---- the choices that persist --------------------------------------------------------------------------------------

/** The saved wait screen ("game" or "loading"), else the default: the loading screen with reduced motion, the game otherwise. Storage that throws is no storage. */
export function readMode(reduced = false) {
  const fallback = reduced ? "loading" : "game";
  try {
    const v = window.localStorage.getItem(WAIT_MODE_KEY);
    return v === "game" || v === "loading" ? v : fallback;
  } catch (err) { return fallback; }
}

function saveMode(mode) {
  try { window.localStorage.setItem(WAIT_MODE_KEY, mode); } catch (err) { /* private mode: the choice lasts until the page does */ }
}

/** This session's best score (sessionStorage), 0 when there is none or storage is blocked. */
export function readBest() {
  try {
    const n = Number(window.sessionStorage.getItem(BEST_KEY));
    return Number.isFinite(n) && n > 0 ? Math.floor(n) : 0;
  } catch (err) { return 0; }
}

function saveBest(n) {
  try { window.sessionStorage.setItem(BEST_KEY, String(n)); } catch (err) { /* the best lasts until the page does */ }
}

// ---- the hound ---------------------------------------------------------------------------------------------------------

function face(dog, size, pose) {
  try { return dogFace(dog || {}, { size, pose, label: "", decorative: true }); } catch (err) { return h("span", { class: "fg__noface" }); }
}

function pose(svg, name) {
  try { if (svg) setPose(svg, name); } catch (err) { /* a pose is only decoration */ }
}

const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));
const lerp = (a, b, t) => a + (b - a) * t;
const round = (v) => Math.round(v * 10) / 10;

/** A point on the quadratic arc from `a` to `b` bent through `c`, at t in [0, 1]. */
export function arcPoint(a, c, b, t) {
  const u = 1 - t;
  return { x: u * u * a.x + 2 * u * t * c.x + t * t * b.x, y: u * u * a.y + 2 * u * t * c.y + t * t * b.y };
}

/**
 * The arc of a throw: from the hound's mouth to the ground at the tapped side, peaking near the tapped height. The control point is
 * chosen so the arc really peaks at `peak` (a quadratic's top is a quarter of each end plus half the control).
 */
export function throwArc(from, toX, tapY, ground, size = TUNING.ball) {
  const to = { x: toX, y: ground - size / 2 };
  const peak = Math.min(clamp(tapY, 14, ground - 40), Math.min(from.y, to.y) - 16);
  return { from, to, peak, c: { x: (from.x + to.x) / 2, y: 2 * peak - 0.5 * (from.y + to.y) } };
}

function attached(node) {
  let n = node;
  while (n && n.parentNode) n = n.parentNode;
  return !!n && (n === document.body || n === document.documentElement || n.nodeType === 9);
}

// ---- the game ----------------------------------------------------------------------------------------------------------

/**
 * Build the game in `view`. `session` is {score, best}, kept by the caller so a switch to the loading screen and back does not reset it.
 * Returns { stop }. `onGone()` runs when the box has been taken out of the page, so nothing keeps animating a node nobody can see.
 */
function buildGame(view, { dog, reduced, session, onGone }) {
  const T = TUNING;
  const dogSvg = face(dog, T.dog, "idle");
  const dogEl = h("div", { class: "fg__dog", "aria-hidden": "true", "data-hook": "wait-dog" }, [dogSvg]);
  const ballEl = h("div", { class: "fg__ball", "aria-hidden": "true", "data-hook": "wait-ball" });
  const popEl = h("div", { class: "fg__pop", "aria-hidden": "true", "data-hook": "wait-pop", hidden: true });
  const box = h("div", { class: "fg__box", role: "button", tabindex: "0", "aria-label": BOX_LABEL, "data-hook": "wait-game", "data-state": "ready" },
    [h("div", { class: "fg__ground", "aria-hidden": "true" }), dogEl, ballEl, popEl]);
  const scoreEl = h("span", { "data-hook": "wait-score", text: `Score ${session.score}` });
  const bestEl = h("span", { "data-hook": "wait-best", text: `Best ${session.best}` });
  const row = h("p", { class: "fg__score", "data-hook": "wait-score-row" }, [scoreEl, " · ", bestEl]);
  view.appendChild(box);
  view.appendChild(row);
  view.appendChild(h("p", { class: "fg__hint", text: HINT }));

  let stopped = false, frame = null, last = null, seen = false;
  let state = "ready", t = 0, dur = 0, arc = null, g = null;
  let dogX = 0, dir = 1, bx = 0, by = 0, runTo = 0, anchor = null, popLeft = 0, keyIndex = 0;

  function geom() {
    let w = 0, ht = 0;
    try { const r = box.getBoundingClientRect(); w = r.width; ht = r.height; } catch (err) { /* no layout */ }
    if (!(w > 40)) w = 320;
    if (!(ht > 40)) ht = 220;
    return { w, h: ht, ground: ht - T.groundPad, home: Math.max(T.dog / 2 + 8, w * 0.12) };
  }
  const mouth = (x, d) => ({ x: x + d * T.dog * 0.34, y: g.ground - T.dog * 0.42 });

  function place() {
    dogEl.style.transform = `translate(${round(dogX - T.dog / 2)}px, ${round(g.ground - T.dog + 4)}px) scaleX(${dir})`;
    ballEl.style.transform = `translate(${round(bx - T.ball / 2)}px, ${round(by - T.ball / 2)}px)`;
    ballEl.setAttribute("data-x", String(Math.round(bx)));
    ballEl.setAttribute("data-y", String(Math.round(by)));
  }

  function rest() {
    g = geom();
    dogX = g.home; dir = 1;
    const m = mouth(dogX, 1);
    bx = m.x; by = m.y;
    place();
  }

  function enter(next, seconds, face_) {
    state = next; t = 0; dur = seconds;
    box.setAttribute("data-state", next);
    pose(dogSvg, face_ || "idle");
  }

  function award(points, kind, x, y) {
    session.score += points;
    if (session.score > session.best) { session.best = session.score; saveBest(session.best); }
    scoreEl.textContent = `Score ${session.score}`;
    bestEl.textContent = `Best ${session.best}`;
    popEl.textContent = `+${points}`;
    popEl.setAttribute("data-kind", kind);
    popEl.style.transform = `translate(${round(clamp(x, 4, Math.max(4, g.w - 44)))}px, ${round(Math.max(4, y))}px)`;
    popEl.hidden = false;
    popLeft = T.pop;
  }

  function throwTo(tx, ty) {
    if (state !== "ready" || stopped) return;
    rest();
    const from = mouth(g.home, 1);
    const minX = g.home + T.minThrow;
    const toX = clamp(tx, minX, Math.max(minX, g.w - T.ball));
    arc = throwArc(from, toX, ty, g.ground);
    enter("flying", reduced ? T.flyReduced : clamp(T.flyMin + (toX - from.x) * T.flyPerPx, T.flyMin, T.flyMax), "happy");
    kick();
  }

  function catchBall() {
    anchor = { x: bx, y: by };
    award(SCORE.catch, "catch", bx - 14, by - 40);
    enter("catching", reduced ? T.hold : T.back, "celebrate");
  }

  function advance(dt) {
    if (popLeft > 0) {
      popLeft -= dt;
      if (popLeft <= 0) popEl.hidden = true;
    }
    if (state === "ready") return;
    t += dt;
    const p = Math.min(1, t / dur);
    if (state === "flying") {
      const at = arcPoint(arc.from, arc.c, arc.to, reduced ? (p < 1 ? 0.5 : 1) : p);
      bx = at.x; by = at.y;
      if (p >= 1) {
        runTo = arc.to.x - T.dog * 0.34;
        enter("chasing", reduced ? T.hold : Math.max(T.runMin, (runTo - g.home) / T.runSpeed), "happy");
      }
    } else if (state === "chasing") {
      dogX = lerp(g.home, runTo, reduced ? (p < 1 ? 0 : 1) : p);
      if (p >= 1) {
        dir = -1;
        anchor = { x: bx, y: by };
        enter("carrying", reduced ? T.hold : Math.max(T.runMin, (runTo - g.home) / T.runSpeed), "happy");
      }
    } else if (state === "carrying") {
      dogX = lerp(runTo, g.home, reduced ? (p < 1 ? 0 : 1) : p);
      const m = mouth(dogX, dir), k = reduced ? 1 : Math.min(1, p / 0.2);      // the ball slides into the mouth as the hound turns
      bx = lerp(anchor.x, m.x, k); by = lerp(anchor.y, m.y, k);
      if (p >= 1) {
        award(SCORE.fetch, "fetch", g.home - 10, g.ground - T.dog - 24);
        anchor = { x: bx, y: by };
        dir = 1;
        enter("settling", reduced ? 0.01 : T.settle, "idle");
      }
    } else if (state === "settling") {
      const m = mouth(g.home, 1);
      bx = lerp(anchor.x, m.x, p); by = lerp(anchor.y, m.y, p);
      if (p >= 1) { rest(); enter("ready", 0, "idle"); }
    } else if (state === "catching") {
      const m = mouth(g.home, 1);
      const q = reduced ? (p < 1 ? 0 : 1) : p;
      bx = lerp(anchor.x, m.x, q); by = lerp(anchor.y, m.y, q);
      if (p >= 1) { rest(); enter("ready", 0, "idle"); }
    }
    place();
  }

  const animating = () => state !== "ready" || popLeft > 0;

  function request(fn) {
    if (typeof requestAnimationFrame === "function") return { kind: "raf", id: requestAnimationFrame(fn) };
    return { kind: "timeout", id: setTimeout(() => fn(Date.now()), 16) };    // an engine with no animation frames: still one cancellable timer
  }
  function cancel(f) {
    if (!f) return;
    if (f.kind === "raf") { if (typeof cancelAnimationFrame === "function") cancelAnimationFrame(f.id); } else clearTimeout(f.id);
  }

  function loop(ts) {
    frame = null;
    if (stopped) return;
    if (attached(box)) seen = true;
    else if (seen) { onGone(); return; }
    advance(last == null ? 0 : Math.min(T.maxStep, Math.max(0, (ts - last) / 1000)));
    last = ts;
    if (animating()) frame = request(loop);
    else last = null;
  }
  function kick() {
    if (frame || stopped) return;
    last = null;
    frame = request(loop);
  }

  box.addEventListener("pointerdown", (evt) => {
    if (stopped || (typeof evt.button === "number" && evt.button > 0)) return;
    let r = { left: 0, top: 0 };
    try { r = box.getBoundingClientRect(); } catch (err) { /* no layout */ }
    const x = (Number(evt.clientX) || 0) - r.left, y = (Number(evt.clientY) || 0) - r.top;
    if (state === "ready") throwTo(x, y);
    else if (state === "flying" && Math.hypot(x - bx, y - by) <= T.catchRadius) catchBall();
  });
  box.addEventListener("keydown", (evt) => {
    if (stopped || !(evt.key === "Enter" || evt.key === " " || evt.key === "Spacebar")) return;
    if (evt.preventDefault) evt.preventDefault();              // Space must not scroll the sheet
    if (state !== "ready") return;
    const here = geom();
    throwTo(here.w * T.keyTargets[keyIndex++ % T.keyTargets.length], here.h * 0.35);
  });
  const onResize = () => { if (state === "ready" && !stopped) rest(); };
  try { window.addEventListener("resize", onResize); } catch (err) { /* no window */ }

  rest();
  return {
    relayout() { if (state === "ready" && !stopped) rest(); },
    stop() {
      stopped = true;
      cancel(frame);
      frame = null;
      try { window.removeEventListener("resize", onResize); } catch (err) { /* no window */ }
    },
  };
}

// ---- the loading screen ------------------------------------------------------------------------------------------------

function loadingHound(dog, reduced) {
  return h("div", { class: `fg__trot${reduced ? "" : " fg__trot--bob"}`, "aria-hidden": "true", "data-hook": "wait-trot" }, [face(dog, TUNING.bigDog, "thinking")]);
}

// ---- mount -------------------------------------------------------------------------------------------------------------

/**
 * Show the wait screen in `container` and return { setStage(text), destroy() }.
 *
 *   dog        { id, name, look, version_no, root_id } for the hound's avatar (anything dogFace accepts)
 *   stageText  what the server is doing now; setStage(text) changes it (the same text twice is ignored, so a poll every two seconds does
 *              not make a screen reader read it every two seconds)
 *   reduced    the page's reducedMotion()
 *   replaces   the caller's own one-line status element: hidden while this is showing (so the line is not said twice, and only one
 *              region speaks) and shown again by destroy(). It stays in the page with its text, for whoever reads it.
 *   delay      milliseconds before the wait screen appears, for a step that is often quick; destroy() before then cancels it
 *
 * It never throws: if it cannot be built the caller simply has no wait screen.
 */
export function mountWait(container, { dog = null, stageText = "Working...", reduced = false, replaces = null, delay = 0 } = {}) {
  const none = { setStage() {}, destroy() {} };
  if (!container) return none;
  try {
    let dead = false, mode = readMode(reduced), stageNow = String(stageText), game = null, timer = null;
    const session = { score: 0, best: readBest() };
    const heading = h("p", { class: "fg__heading", "data-hook": "wait-heading" });
    const view = h("div", { class: "fg__view", "data-hook": "wait-view" });
    const stage = h("p", { class: "fg__stage", role: "status", "aria-live": "polite", "data-hook": "wait-stage", text: stageNow });
    const bar = h("div", { class: "fg__bar", "aria-hidden": "true", "data-hook": "wait-bar" }, [h("span", { class: "fg__bar-fill" })]);
    const toggle = h("button", { type: "button", class: "fg__toggle", "data-hook": "wait-toggle" });
    const root = h("div", { class: "fg", "data-hook": "wait-ui", "data-mode": mode, "data-motion": reduced ? "reduced" : "full" },
      [heading, view, stage, bar, toggle]);

    const destroy = () => {
      if (dead) return;
      dead = true;
      if (timer != null) { clearTimeout(timer); timer = null; }
      if (game) { game.stop(); game = null; }
      if (root.parentNode) root.parentNode.removeChild(root);
      if (replaces) replaces.hidden = false;
    };
    const paint = () => {
      if (game) { game.stop(); game = null; }
      clearNode(view);
      root.setAttribute("data-mode", mode);
      heading.textContent = mode === "game" ? GAME_HEADING : LOADING_HEADING;
      toggle.textContent = mode === "game" ? TO_LOADING : TO_GAME;
      if (mode === "game") game = buildGame(view, { dog, reduced, session, onGone: destroy });
      else view.appendChild(loadingHound(dog, reduced));
    };
    toggle.addEventListener("click", () => {
      if (dead) return;
      mode = mode === "game" ? "loading" : "game";
      saveMode(mode);
      paint();
    });
    const reveal = () => {
      timer = null;
      if (dead) return;
      root.hidden = false;
      if (replaces) replaces.hidden = true;
      if (game) game.relayout();                 // measured now that it is showing
    };

    container.appendChild(root);               // in the page first, so the game measures its real box
    paint();
    if (delay > 0) { root.hidden = true; timer = setTimeout(reveal, delay); } else reveal();

    return {
      setStage(text) {
        const next = String(text == null ? "" : text);
        if (dead || next === stageNow) return;
        stageNow = next;
        stage.textContent = next;
      },
      destroy,
    };
  } catch (err) {
    return none;
  }
}
