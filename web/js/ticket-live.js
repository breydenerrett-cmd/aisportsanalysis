/**
 * Where a ticket stands right now: Upcoming (starts in X) · Live (the score) · Final, grading… · WON +$X / LOST -$X / PUSH.
 *
 * WHY (owner, 2026-10-22). Member tickets sat PENDING for hours after their games ended and the page said nothing about
 * why. The server now grades within minutes of a final (src/hounds/live_settle.py); this is the page that SHOWS the
 * stretch in between honestly, from the same cache the grader reads (GET /hounds/live), and the money in the viewer's own
 * unit (web/js/unitsize.js).
 *
 * WHAT IT NEVER DOES. It never decides a result: WON, LOST and PUSH come from the server's graded ticket. A game the
 * server does not know is left exactly as it was (a PENDING chip and nothing else), never guessed. The score is printed
 * away-home, the way the ticket's own "Away at Home" game line reads, and the title says so.
 *
 * HOW A LIST OPTS IN. The ticket builders (hounds-tickets.js) stamp each ticket node with `data-event` (the id the
 * server asks about), `data-start` and, once graded, `data-units`, and put an empty `.hd-live` span beside the status chip.
 * `watchTickets(root)` then fills those in, asks the server about the pending ones, and asks again every minute while any
 * is still pending and the list is on the page. Network failures leave the page as it was.
 *
 * DOLLARS. Fixed-dollar sizing prints the ticket's units times the viewer's unit ("+$23"). A percent-of-bankroll sizing
 * compounds bet by bet (unitsize.js `priced`), which one ticket cannot show alone, so it prints nothing here: the units
 * beside it already say how the ticket went.
 */

import { apiGet } from "./api.js";
import { getSizing, onSizingChange } from "./unitsize.js";
import { h, isNum } from "./hounds-core.js";

export const POLL_MS = 60000;
export const MAX_IDS = 60;
const AWAITING_MAX_MS = 20 * 60000;
const STATUS_WORDS = { upcoming: "UPCOMING", live: "LIVE", grading: "GRADING", postponed: "POSTPONED", cancelled: "CANCELLED" };
let lastSeen;                      // the last "last graded" stamp this page saw (undefined until the first look)

/** "2h 10m" / "35m" / "under a minute": how long until `startMs`, from `nowMs`. */
export function startsIn(startMs, nowMs) {
  const mins = Math.floor((startMs - nowMs) / 60000);
  if (!Number.isFinite(mins) || mins < 1) return "under a minute";
  if (mins < 60) return `${mins}m`;
  const hours = Math.floor(mins / 60);
  if (hours < 48) return `${hours}h${mins % 60 ? ` ${mins % 60}m` : ""}`;
  return `${Math.floor(hours / 24)}d`;
}

function score(info) {
  const a = Number(info.away_score);
  const b = Number(info.home_score);
  return info.away_score === null || info.home_score === null || info.away_score === undefined
    || info.home_score === undefined || !Number.isFinite(a) || !Number.isFinite(b) ? null : `${a}-${b}`;
}

/**
 * The live view of ONE pending ticket from the server's answer for its game: { key, chip, text, title } or null when the
 * server has nothing usable (the ticket is left alone).
 */
export function liveView(info, startIso, nowMs) {
  if (!info || typeof info !== "object" || info.supported === false) return null;
  const startMs = Date.parse(String(info.start_utc || startIso || ""));
  switch (info.state) {
    case "final": {
      const sc = score(info);
      return { key: "grading", chip: STATUS_WORDS.grading, text: sc ? `Final ${sc}, grading…` : "Final, grading…",
        title: sc ? "Final score, away then home. The ticket grades within minutes." : "Final. The ticket grades within minutes." };
    }
    case "live": {
      const sc = score(info);
      const detail = info.detail ? ` · ${info.detail}` : "";
      return { key: "live", chip: STATUS_WORDS.live, text: sc ? `Live ${sc}${detail}` : `Live${detail}`,
        title: "Current score, away then home." };
    }
    case "postponed":
      return { key: "postponed", chip: STATUS_WORDS.postponed, text: "Postponed, waits for the makeup",
        title: "The ticket stays open and grades if the game is made up." };
    case "cancelled":
      return { key: "cancelled", chip: STATUS_WORDS.cancelled, text: "Cancelled, voids by rule",
        title: "A game that is never played is a void: no win, no loss." };
    case "upcoming": {
      if (Number.isFinite(startMs) && startMs > nowMs) {
        return { key: "upcoming", chip: STATUS_WORDS.upcoming, text: `Starts in ${startsIn(startMs, nowMs)}`, title: "" };
      }
      // Started, and the feed has said nothing yet. A few minutes of that is a pregame delay; longer is a game the feed
      // could not match or read, and "awaiting the start" would be false, so the ticket is left as a plain PENDING chip.
      if (Number.isFinite(startMs) && nowMs - startMs >= AWAITING_MAX_MS) return null;
      return { key: "upcoming", chip: STATUS_WORDS.upcoming, text: "Awaiting the start", title: "" };
    }
    default:
      return null;
  }
}

/** "+$23" / "-$25" / "$0": a graded ticket's profit in the viewer's fixed unit, or null (percent sizing, or no units). */
export function dollarsText(units, sizing = getSizing()) {
  if (!isNum(units) || !sizing || sizing.mode !== "fixed" || !isNum(sizing.unit_usd)) return null;
  const usd = Math.round(units * sizing.unit_usd * 100) / 100;
  if (usd === 0) return "$0";
  const body = Math.abs(usd).toLocaleString("en-US", Number.isInteger(usd)
    ? { maximumFractionDigits: 0 } : { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return `${usd > 0 ? "+" : "-"}$${body}`;
}

/** The empty span a ticket builder puts beside the status chip. Hidden until there is something true to say. */
export function liveSpan(hook = "ticket-live") {
  return h("span", { class: "hd-live", "data-hook": hook, hidden: true });
}

/** The data attributes a ticket node carries so `watchTickets` can find and fill it. {} when there is nothing to say. */
export function liveAttrs(ticket) {
  const t = ticket || {};
  const attrs = {};
  if (t.event_id) attrs["data-event"] = String(t.event_id);
  if (t.start_utc) attrs["data-start"] = String(t.start_utc);
  if (isNum(t.units)) attrs["data-units"] = String(t.units);
  return attrs;
}

const statusOf = (node) => String(node.getAttribute("data-status") || "").toLowerCase();

function chipOf(node) {
  return node.querySelector('[data-hook="ticket-status"]') || node.querySelector('[data-hook="card-status"]');
}

function setSpan(span, text, tone, title) {
  if (!span) return;
  if (!text) {
    span.hidden = true;
    return;
  }
  span.textContent = text;
  span.setAttribute("class", `hd-live${tone ? ` hd-live--${tone}` : ""}`);
  if (title) span.setAttribute("title", title);
  span.hidden = false;
}

/** Fill the dollars on every graded ticket under `root` (no network). */
export function paintDollars(root, sizing = getSizing()) {
  for (const node of root.querySelectorAll("[data-units]")) {
    const state = statusOf(node);
    if (state !== "won" && state !== "lost" && state !== "push") continue;
    const units = Number(node.getAttribute("data-units"));
    const text = dollarsText(units, sizing);
    const label = text === null ? "" : state === "push" ? `Push, ${text}` : text;
    setSpan(node.querySelector('[data-hook="ticket-live"]'), label,
      state === "won" ? "up" : state === "lost" ? "down" : "flat", "At your unit size");
  }
}

/** Paint the live state of every PENDING ticket under `root` from `games` ({event id: server answer}). */
export function paintLive(root, games, nowMs = Date.now()) {
  for (const node of root.querySelectorAll("[data-event]")) {
    if (statusOf(node) !== "pending") continue;
    const view = liveView((games || {})[node.getAttribute("data-event")], node.getAttribute("data-start"), nowMs);
    const chip = chipOf(node);
    if (view === null) continue;
    if (chip) {
      chip.textContent = view.chip;
      chip.setAttribute("data-live", view.key);
    }
    setSpan(node.querySelector('[data-hook="ticket-live"]'), view.text, view.key, view.title);
  }
}

function pendingIds(root) {
  const ids = [];
  for (const node of root.querySelectorAll("[data-event]")) {
    const id = node.getAttribute("data-event");
    if (statusOf(node) === "pending" && id && !ids.includes(id)) ids.push(id);
  }
  return ids;
}

/**
 * Show the money on graded tickets and the live state on pending ones under `root`; keep it fresh while the list is on
 * the page. `fetchFn(path)` and `now()` are the seams the tests use. Returns a `stop()` function.
 */
export function watchTickets(root, { fetchFn = apiGet, now = () => Date.now(), pollMs = POLL_MS } = {}) {
  if (!root || typeof root.querySelectorAll !== "function") return () => {};
  let stopped = false;
  let timer = null;
  let detached = 0;
  paintDollars(root);
  onSizingChange(() => { if (!stopped) paintDollars(root); });

  async function refresh() {
    const ids = pendingIds(root);
    if (!ids.length) return false;
    const games = {};
    try {
      for (let i = 0; i < ids.length; i += MAX_IDS) {
        const out = await fetchFn(`/hounds/live?ids=${ids.slice(i, i + MAX_IDS).map(encodeURIComponent).join(",")}`);
        Object.assign(games, (out && out.games) || {});
      }
    } catch (err) {
      return true;                 // the feed is down or unreachable: leave the page as it was, try again next minute
    }
    paintLive(root, games, now());
    return true;
  }

  function stop() {
    stopped = true;
    if (timer !== null && typeof clearInterval === "function") clearInterval(timer);
    timer = null;
  }

  refresh().then((more) => {
    if (stopped || !more || typeof setInterval !== "function") return;
    timer = setInterval(async () => {
      if (root.isConnected === false) {
        detached += 1;
        if (detached >= 2) stop();
        return;
      }
      detached = 0;
      if (!(await refresh())) stop();
    }, pollMs);
  });
  return stop;
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** "02:14" in the viewer's own clock from an ISO instant ("Oct 21, 02:14" when it was not today for the viewer, so a
 * grade from yesterday never reads as one from this morning), or "" when it is missing or unreadable. */
export function clockText(iso, nowMs = Date.now()) {
  const ms = Date.parse(String(iso || ""));
  if (!Number.isFinite(ms)) return "";
  const d = new Date(ms);
  const clock = `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
  const today = new Date(nowMs);
  const sameDay = d.getFullYear() === today.getFullYear() && d.getMonth() === today.getMonth() && d.getDate() === today.getDate();
  return sameDay ? clock : `${MONTHS[d.getMonth()]} ${d.getDate()}, ${clock}`;
}

/** The badge's words from the status payload: { last, grading } (either may be empty). */
export function badgeView(status) {
  const s = status || {};
  const waiting = Number(s.awaiting_final || 0) + Number(s.final_ungraded || 0);
  const clock = clockText(s.last_graded_utc);
  return { last: clock ? `Last graded ${clock}` : "", grading: waiting > 0 ? `Grading ${waiting} game${waiting === 1 ? "" : "s"}…` : "",
    title: s.last_graded_utc ? `Last ticket graded ${s.last_graded_utc}` : "No ticket graded since this app last restarted" };
}

/**
 * A small line on a hound page or My Kennel: "Last graded 02:14" and a "Grading" pill while games are waiting on a final.
 * Asks GET /hounds/live/status now and every minute. Returns the element; a failed ask leaves it empty and hidden.
 * `onGraded(iso)` is called when a ticket has graded since this page first looked, so the page can reload its record,
 * bankroll and lists at once instead of waiting for the viewer to refresh. `pollMs: 0` is for a page that already rebuilds
 * the badge on its own timer (the hound page's open-ticket poller): no second interval.
 */
export function gradingBadge({ fetchFn = apiGet, pollMs = POLL_MS, onGraded = null } = {}) {
  const last = h("span", { class: "hd-graded__last", "data-hook": "last-graded" });
  const pill = h("span", { class: "hd-graded__pill", "data-hook": "grading-indicator", hidden: true });
  const box = h("p", { class: "hd-graded", "data-hook": "grading-badge", hidden: true }, [pill, last]);
  async function paint() {
    try {
      const status = await fetchFn("/hounds/live/status");
      const view = badgeView(status);
      const stamp = (status && status.last_graded_utc) || null;
      // the baseline is the PAGE's, not this badge's: a page that rebuilds its badge every minute still sees a new grade
      if (lastSeen !== undefined && stamp && stamp !== lastSeen && typeof onGraded === "function") {
        try { onGraded(stamp); } catch (err) { /* the page's own refresh must not break the badge */ }
      }
      lastSeen = stamp;
      last.textContent = view.last;
      last.setAttribute("title", view.title);
      pill.textContent = view.grading;
      pill.hidden = !view.grading;
      box.hidden = !(view.last || view.grading);
    } catch (err) {
      /* leave it as it was */
    }
  }
  paint();
  if (pollMs > 0 && typeof setInterval === "function") {
    const timer = setInterval(() => {
      if (box.isConnected === false) { clearInterval(timer); return; }
      paint();
    }, pollMs);
  }
  return box;
}
