/**
 * web/js/reveal-fx.js: the reveal choreography (docs/marketing/GROWTH_PLAYBOOK.md section 2, R2, R4 and R6) and the words of the
 * "Would have bet today" panel.
 *
 * THREE MOMENTS, ONE RULE. R2 "Meet {Name}" (silhouette, dog, name, rules), R4 "Would have bet today" (the count, then the tickets
 * flip in) and R6 (a hound's first graded ticket flips from PENDING to its grade). Each one:
 *   - is under 2.5 seconds end to end (REVEAL_MS is the hard stop; the CSS beats add up to 2.4);
 *   - is skippable on a tap or a key (a click anywhere on the moment, Enter or Space on it): the final state shows at once;
 *   - is dropped for `prefers-reduced-motion: reduce`, which gets the final state with a 150 ms fade (css/quiz.css, css/lh.css);
 *   - changes NO content. The words and numbers are in the page from the first frame; the motion is `data-reveal` /
 *     `data-flip` attributes that css/ animates, so a script that stops, a screenshot and a screen reader all see the final page.
 *
 * It dramatises only waits that are real. The compose call is a real server call; the silhouette beat starts when its answer lands
 * and holds 0.7 s, and nothing says "analysing". Wins and losses animate identically: nothing here takes the result as an input.
 *
 * Written against attributes only (no classList, no dataset): it runs in the node test harness's small DOM.
 */

export const REVEAL_MS = 2400;
export const COUNT_MS = 500;
export const FLIP_STAGGER_MS = 120;
export const MAX_FLIPS = 6;

/** True when the person has asked for less motion. A missing matchMedia (a test harness, an old browser) means "no preference". */
export function reducedMotion() {
  try {
    return !!(window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches);
  } catch (err) {
    return false;
  }
}

/** What a root's `data-reveal` says: "play" (animating), "done" (final state) or "" (never started). */
export function revealState(root) {
  return root && root.getAttribute ? root.getAttribute("data-reveal") || "" : "";
}

/** Show the final state now. Safe to call twice. */
export function skipReveal(root) {
  if (root && revealState(root) === "play") root.setAttribute("data-reveal", "done");
}

/**
 * Start a moment on `root`. With reduced motion the root goes straight to "done". Otherwise it is "play" until the first tap or key
 * on it, or until `ms` have passed, whichever is first. Returns "play" or "done" (what the root is now).
 */
export function playReveal(root, ms = REVEAL_MS) {
  if (!root || !root.setAttribute) return "done";
  if (revealState(root)) return revealState(root);              // one play per moment: a re-render never replays it
  if (reducedMotion()) { root.setAttribute("data-reveal", "done"); return "done"; }
  root.setAttribute("data-reveal", "play");
  const stop = () => skipReveal(root);
  root.addEventListener("click", stop);
  root.addEventListener("keydown", (evt) => { if (!evt || evt.key === "Enter" || evt.key === " " || evt.key === "Escape") stop(); });
  const timer = setTimeout(stop, Math.min(ms, REVEAL_MS));
  if (timer && typeof timer.unref === "function") timer.unref();
  return "play";
}

/**
 * Count `el` up from 0 to `value` over COUNT_MS, ending on exactly `value`. The element already holds the final number, so nothing
 * depends on the animation finishing: reduced motion, a hidden tab, a skipped moment and a browser without requestAnimationFrame
 * all leave the final number as it is.
 */
export function countTo(el, value, root = null) {
  if (!el || !Number.isFinite(value) || value <= 0) return;
  if (reducedMotion() || typeof requestAnimationFrame !== "function" || typeof performance === "undefined") return;
  if (typeof document !== "undefined" && document.visibilityState === "hidden") return;
  const start = performance.now();
  const final = String(value);
  const step = (now) => {
    if (revealState(root) === "done") { el.textContent = final; return; }
    const t = Math.min(1, (now - start) / COUNT_MS);
    if (t >= 1) { el.textContent = final; return; }
    el.textContent = String(Math.round(value * (1 - Math.pow(1 - t, 3))));
    requestAnimationFrame(step);
  };
  el.textContent = "0";
  requestAnimationFrame(step);
}

// ---- the words of "Would have bet today" ---------------------------------------------------------------------------------------

/** A price of -200 or worse is never shown (the engine does not take one; this is the belt to that brace). */
export function showable(pick) {
  return !(pick && typeof pick.price === "number" && pick.price <= -200);
}

export function priceText(price) {
  return typeof price === "number" && Number.isFinite(price) ? `${price > 0 ? "+" : ""}${price}` : "";
}

/** "3 of 41 games fit" (the number is `n`, the rest is `rest`, so the number can count up on its own). */
export function fitParts(name, fit, board) {
  return { n: String(fit), rest: ` of ${board} ${board === 1 ? "game fits" : "games fit"} ${name}'s rule today.` };
}

export function fitLine(name, fit, board) {
  const p = fitParts(name, fit, board);
  return p.n + p.rest;
}

/**
 * The three honest states of the panel, as data. `res` is the answer of POST /hounds/builder/preview, or null when the call failed
 * (`err` then carries its status).
 *   - "picks"     fit > 0: the count line, the cap line, the tickets
 *   - "zero"      the board has games and none fit: the pass, said as part of the record
 *   - "empty"     the board has no games yet
 *   - "not_loaded" the call failed: no number at all, and a retry
 * The count of games that fit comes from the server's `games_fit` and the board size from `board_size` (older answers: the number
 * of distinct events among the picks and `games_on_board`), never from anything typed here.
 */
export function previewState(res, name, err = null) {
  if (!res) {
    return { kind: "not_loaded", line: err && err.status === 503 ? "Today's board is not loaded right now." : "The preview is not available right now.",
      retry: true };
  }
  const board = Number.isFinite(res.board_size) ? res.board_size : res.games_on_board;
  const picks = (res.picks || []).filter(showable);
  // the server's own count unless a pick had to be dropped here (a price at -200 or worse), when the count is recomputed from what is shown
  const fit = Number.isFinite(res.games_fit) && picks.length === (res.picks || []).length ? res.games_fit : new Set(picks.map((p) => p.event_id)).size;
  if (!board) return { kind: "empty", line: "No games on today's board yet.", retry: false };
  if (!picks.length) {
    return { kind: "zero", line: `${name} passes today. Nothing on the board fits its rule.`, sub: "A pass is a valid day for a hound.", fit: 0, board, picks: [] };
  }
  const bets = picks.filter((p) => p.would_bet);
  const cap = res.max_bets_per_day;
  return { kind: "picks", fit, board, picks, bets, cap,
    parts: fitParts(name, fit, board),
    sub: `${name} would have bet ${bets.length}${cap ? `, with a cap of ${cap} a day` : ""}.` };
}
