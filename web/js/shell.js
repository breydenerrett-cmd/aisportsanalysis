/**
 * Shell-level wiring owned by the chrome group: the status line every
 * view reports into (DESIGN_SYSTEM.md section 3, "Status line"), and
 * mounting the sport-level bar (section 3's `renderSportLevel`).
 *
 * Kept in its own module so a view can report freshness / mount the
 * sport bar without importing the router (main.js imports the views; the
 * views must not import it back).
 */

import { formatAge } from "./dom.js";
import { renderSportLevel } from "./sport.js";

/**
 * THE STATUS LINE MOVED (DESIGN_SYSTEM.md section 3).
 *
 * It used to live in a permanent topstrip node (`[data-hook='board-status']`)
 * that existed for the whole page lifetime. It now lives inside each
 * route's own `pageHeader()` (`web/js/layout.js`, foundation-owned) --
 * a `<p data-hook="page-status" role="status">` that is destroyed and
 * rebuilt every time a route mounts a new header. `setShellStatus` keeps
 * its exact signature (both `games.js`'s `setShellStatusFromStaleness`
 * and several views' direct `setShellStatus(text)` calls depend on that),
 * but writes into whichever such node is live right now, with two
 * failure modes handled that a plain, uncached `querySelector` write
 * would not handle:
 *
 * 1. "A header mounted after the call." `main.js`'s router calls
 *    `setShellStatus(null)` at the top of each route dispatch, BEFORE the
 *    view it is about to render has called `pageHeader()` -- at that
 *    instant no `[data-hook='page-status']` node exists yet, so a plain
 *    `if (!host) return;` write would silently drop the call. A
 *    `MutationObserver` on the shared `[data-hook='app-outlet']` (the one
 *    router-mount point every builder in this redesign shares -- see the
 *    fixed data-hook list) notices the moment a new status node lands and
 *    re-applies whatever was last requested.
 * 2. "A late call that lands after a route change bleeds into the wrong
 *    page." A view's own async status update (`today.js`'s
 *    `setShellStatus(...)` after a fetch resolves, for example) can land
 *    after the visitor has already navigated elsewhere. This module
 *    cannot know, from the call alone, which page a given call was
 *    "for" -- no caller passes a page identity, and that is not something
 *    this task can add without editing files it does not own. What it
 *    CAN do without touching another file: clear the cached status the
 *    instant the hash changes, so a call that resolves before the new
 *    page reports its own status does not keep showing the old page's
 *    text past the moment of navigation. This narrows the window; it
 *    does not claim to close it perfectly, which would require the
 *    caller itself to say which page it belongs to.
 *
 * TWO BUGS FIXED HERE (checker findings, CHR-8):
 *
 * (high) `writeStatus` used to assign `host.textContent` unconditionally
 * on every observer callback, including when the desired text was
 * already on screen. Setting `.textContent` always replaces the text
 * node even when the string is unchanged, which is itself a childList
 * mutation the observer is watching for -- so every write queued another
 * callback that wrote again, forever (confirmed live: 201 childList
 * records in 300ms from a single `setShellStatus` call). `writeStatus`
 * now skips the assignment when the node's text already matches, which
 * lets each real update settle after one harmless extra callback instead
 * of looping.
 *
 * (medium) The observer used to replay `cachedStatus` -- including a
 * cached `null` -- into ANY status node that appeared, which blanked a
 * status a page had set through its own mounted header (`pageHeader({
 * status })` or `header.setStatus(...)` directly), since `main.js` calls
 * `setShellStatus(null)` at the top of every route dispatch before the
 * new view has mounted its header. `writeStatus` now never writes a
 * falsy status at all: a `null`/cleared cache only resets what THIS
 * module will apply later, it never actively erases text a header set
 * for itself. There is nothing to reconcile a header's own status back
 * out through `setShellStatus` for -- a caller that wants the line
 * blank should not call this module with real text, not rely on a
 * stale cache doing it.
 */
let cachedStatus = null; // {text, options} | null -- only ever holds real (non-empty) text
let observerStarted = false;

function statusHost() {
  return document.querySelector("[data-hook='page-status']");
}

function writeStatus(host, status) {
  if (!host || !status) return; // never blank a header; only ever apply a real, named fact
  const text = status.text || "";
  if (host.textContent !== text) {
    host.textContent = text; // guarded: an unconditional write here is what looped the observer
  }
  host.classList.toggle("pagehead__status--stale", Boolean(status.options && status.options.stale));
}

function applyCachedStatus() {
  writeStatus(statusHost(), cachedStatus);
}

function ensureObserver() {
  if (observerStarted || typeof MutationObserver === "undefined") return;
  const outlet = document.querySelector("[data-hook='app-outlet']");
  if (!outlet) return;
  observerStarted = true;
  new MutationObserver(applyCachedStatus).observe(outlet, { childList: true, subtree: true });
}

if (typeof window !== "undefined") {
  window.addEventListener("hashchange", () => {
    // The page that owned this status just left -- see failure mode 2
    // above. The new page starts silent until it reports its own status.
    cachedStatus = null;
  });
}

export function setShellStatus(text, options = {}) {
  ensureObserver();
  cachedStatus = text ? { text, options: { ...options } } : null;
  applyCachedStatus();
}

/** Above this age the board reads as stale rather than fresh in the
 * status line -- a DISPLAY threshold only, never a payload edit, and the
 * exact age is always printed alongside it (`formatAge`).
 *
 * NOT a flat 90 minutes (DESIGN_SYSTEM.md section 3). The real capture
 * cadence (`.github/workflows/forward-capture.yml`, `scripts/
 * capture_slot.sh`) runs roughly every 13 minutes during game hours and
 * roughly hourly in quiet hours -- a flat 90-minute threshold would let a
 * 75-minute outage during game hours read as fresh. Two thresholds:
 * ~30 minutes (about two missed slots) when a game's first pitch is
 * within a few hours, 90 minutes otherwise.
 *
 * `setShellStatusFromStaleness` keeps its existing two required
 * parameters (`games.js` calls it as `setShellStatusFromStaleness(
 * first.board_summary)` and `setShellStatusFromStaleness(advanced.
 * staleness)`, with no per-game first-pitch field in either object --
 * verified directly against `src/analysis/gamepayload.py`'s
 * `_board_summary`/`_board_staleness` and `docs/API_CONTRACTS.md`'s
 * table). This function has no way to know from those objects alone
 * whether a first pitch is close, so it accepts an OPTIONAL third
 * `options.gameHoursSoon` a caller may supply once one exists with real
 * per-game timing to pass; until then it defaults to the tighter,
 * game-hours threshold rather than the lenient one -- the design intent
 * named above is specifically to stop a real outage from reading as
 * fresh, so the safer default when this function does not know which
 * regime applies is the shorter window, not the longer one. */
const STALE_GAME_HOURS_SECONDS = 30 * 60;
const STALE_QUIET_HOURS_SECONDS = 90 * 60;

export function setShellStatusFromStaleness(staleness, label = "BOARD UPDATED", options = {}) {
  if (!staleness || typeof staleness !== "object") {
    setShellStatus(null);
    return;
  }
  const age = staleness.age_seconds;
  if (age === null || age === undefined) {
    setShellStatus("NO BOARD YET", { stale: true });
    return;
  }
  const threshold = options.gameHoursSoon === false ? STALE_QUIET_HOURS_SECONDS : STALE_GAME_HOURS_SECONDS;
  const stale = Number(age) > threshold;
  const readable = formatAge(age);
  setShellStatus(`${stale ? "LAST UPDATED" : label} ${readable || ""}`.trim(), { stale });
}

/**
 * Mount the sport-level bar (DESIGN_SYSTEM.md section 3) into the shared
 * `[data-hook='sport-level-host']` host, replacing the old
 * `mountSportSwitcher`/`renderSportSwitcher` pair entirely. Called from
 * `main.js`'s `_renderRouteInner` on every route change so the selected
 * tab / coming-soon link tracks the active sport.
 */
export function mountSportLevel(activeSport = "mlb", options = {}) {
  const host = document.querySelector("[data-hook='sport-level-host']");
  if (host) renderSportLevel(host, activeSport, options);
}
