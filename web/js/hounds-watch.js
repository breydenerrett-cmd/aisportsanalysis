/**
 * "🔴 Today's action": what this dog has on the board today, with a status chip on every pick.
 *
 * WATCHABLE MEANS TRUE RIGHT NOW. A chip is only ever as strong as what the row says:
 *   WON / LOST / PUSH / VOID  the bet is graded (the server's `result`)
 *   PASSED                    the dog looked at the game and said no (a row marked `refused`)
 *   LIVE                      the game has started and the bet is not graded yet (start time <= now)
 *   GRADING                   the game started over five hours ago and the bet is still not graded: the
 *                             game is almost surely over, so calling it LIVE would be false
 *   PENDING                   the game has not started (or the row carries no start time to say it has)
 * `start_utc` rides on each bet row (src/hounds/contract.py BetRow); a row without one is PENDING, never
 * LIVE: no timestamp, no live claim.
 *
 * WHAT COUNTS AS TODAY. The slate day on the row (`date`) is today's date for the viewer, in UTC or in
 * US Eastern (MLB's slate day), or the bet is ungraded and its game starts between 12 hours ago and 36
 * hours ahead. Rehearsal rows (`segment: "replay"`) are old boards written after the fact and never show.
 *
 * THE "ON THE RECORD" STAMP is the proof the bet was written before the game: `recorded_utc` earlier than
 * `start_utc`. When the row has no write stamp or no start the stamp says less, never more; a rehearsal row
 * says plainly that it was written after the games were played.
 *
 * Pure helpers first (no DOM, easy to test), then the renderer, then the 60-second refresh that only runs
 * while the tab is visible (hounds-core.js createPoller).
 */

import { h, clearNode, fmtPrice, isNum, createPoller } from "./hounds-core.js";

export const REFRESH_MS = 60000;
export const GRADING_AFTER_MS = 5 * 3600 * 1000;
export const GENERIC_TRIGGER = "its rule fires on a game";

export const CHIP_TEXT = {
  pending: "PENDING", live: "LIVE", grading: "GRADING", won: "WON", lost: "LOST", push: "PUSH", void: "VOID",
  passed: "PASSED",
};

function parseMs(value) {
  const ms = Date.parse(String(value || ""));
  return Number.isFinite(ms) ? ms : null;
}

function localDay(ms) {
  const d = new Date(ms);
  const p = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

function utcDay(ms) {
  return new Date(ms).toISOString().slice(0, 10);
}

function easternDay(ms) {
  try {
    return new Intl.DateTimeFormat("en-CA", { timeZone: "America/New_York", year: "numeric", month: "2-digit",
      day: "2-digit" }).format(new Date(ms));
  } catch (err) {
    return utcDay(ms);
  }
}

/** The slate days that count as "today" for a viewer at `nowMs`. */
export function todayKeys(nowMs) {
  return new Set([localDay(nowMs), utcDay(nowMs), easternDay(nowMs)]);
}

/** The chip a bet row wears at `nowMs`: one of the keys of CHIP_TEXT. */
export function statusOf(bet, nowMs) {
  const res = String((bet && bet.result) || "").toLowerCase();
  if (res === "win" || res === "won" || res === "w") return "won";
  if (res === "loss" || res === "lost" || res === "l") return "lost";
  if (res === "push" || res === "p") return "push";
  if (res === "void" || res === "v") return "void";
  if (bet && (bet.refused === true || res === "passed" || res === "pass")) return "passed";
  const start = parseMs(bet && bet.start_utc);
  if (start === null || nowMs < start) return "pending";
  return nowMs - start > GRADING_AFTER_MS ? "grading" : "live";
}

/** Today's picks, soonest game first (undated rows last), rehearsal rows never. */
export function todaysPicks(bets, nowMs) {
  const keys = todayKeys(nowMs);
  const out = [];
  for (const b of bets || []) {
    if (!b || b.segment === "replay") continue;
    const day = String(b.date || "").slice(0, 10);
    const start = parseMs(b.start_utc);
    const graded = statusOf(b, nowMs);
    const open = graded === "pending" || graded === "live" || graded === "grading";
    const nearby = open && start !== null && start > nowMs - 12 * 3600 * 1000 && start < nowMs + 36 * 3600 * 1000;
    if (keys.has(day) || nearby) out.push(b);
  }
  out.sort((a, b) => (parseMs(a.start_utc) ?? Infinity) - (parseMs(b.start_utc) ?? Infinity));
  return out;
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** "7:05 PM" in the viewer's own time zone, or "" for a time that cannot be read. */
export function localTime(value) {
  const ms = parseMs(value);
  if (ms === null) return "";
  const d = new Date(ms);
  const hr = d.getHours();
  return `${hr % 12 === 0 ? 12 : hr % 12}:${String(d.getMinutes()).padStart(2, "0")} ${hr < 12 ? "AM" : "PM"}`;
}

/** "Oct 18, 7:05 PM" in the viewer's own time zone. */
export function localStamp(value) {
  const ms = parseMs(value);
  if (ms === null) return "";
  const d = new Date(ms);
  return `${MONTHS[d.getMonth()]} ${d.getDate()}, ${localTime(value)}`;
}

/**
 * The proof line under a bet: { kind, text }. `kind` is "before" (written before the game, the good case),
 * "after" (written at or after the start: say so), "rehearsal", "recorded" (a write time but no start to
 * compare) or "none".
 */
export function recordStamp(bet) {
  const b = bet || {};
  if (b.segment === "replay") {
    return { kind: "rehearsal", text: "🔁 Rehearsal: written after the games were played, so it never counts." };
  }
  const rec = parseMs(b.recorded_utc);
  const start = parseMs(b.start_utc);
  if (rec === null) return { kind: "none", text: "" };
  if (start === null) return { kind: "recorded", text: `Recorded ${localStamp(b.recorded_utc)}.` };
  if (rec < start) {
    return { kind: "before", text: `🔒 On the record before the game (recorded ${localStamp(b.recorded_utc)})` };
  }
  return { kind: "after", text: `Recorded ${localStamp(b.recorded_utc)}, after the game started.` };
}

/** The pick in words: "Red Sox ML at -115". */
export function pickText(bet) {
  const price = isNum(bet.price_average) ? bet.price_average : bet.price;
  return `${bet.selection || "a pick"}${isNum(price) ? ` at ${fmtPrice(price)}` : ""}`;
}

export function emptyText(trigger) {
  return `No pick yet today. This dog bets when ${trigger || GENERIC_TRIGGER}; boards refresh through the day.`;
}

/** One pick as a row: chip, the pick, the game and its time, why, the proof stamp. */
export function pickRow(bet, nowMs) {
  const status = statusOf(bet, nowMs);
  const time = localTime(bet.start_utc);
  const stamp = recordStamp(bet);
  return h("li", { class: "hd-pick", "data-hook": "today-pick", "data-status": status }, [
    h("span", { class: `hd-pickchip hd-pickchip--${status}`, "data-hook": "today-chip", text: CHIP_TEXT[status] }),
    h("div", { class: "hd-pick__body" }, [
      h("p", { class: "hd-pick__main" }, [
        h("strong", { "data-hook": "today-pick-text", text: pickText(bet) }),
        bet.game ? h("span", { class: "hd-pick__game", text: ` · ${bet.game}` }) : null,
        time ? h("time", { class: "hd-pick__time", "data-hook": "today-time", datetime: String(bet.start_utc), text: ` · ${time}` }) : null,
      ]),
      bet.reason ? h("p", { class: "hd-pick__why", "data-hook": "today-why", text: `Why: ${bet.reason}` }) : null,
      stamp.text ? h("p", { class: `hd-pick__stamp hd-pick__stamp--${stamp.kind}`, "data-hook": "today-stamp",
        text: stamp.text }) : null,
    ]),
  ]);
}

/**
 * Fill `box` with today's action for `bets` (a list of bet rows, newest first as the server sends them).
 * `ctx`: { trigger, retired, nowMs }.
 */
export function renderToday(box, bets, ctx = {}) {
  clearNode(box);
  const nowMs = ctx.nowMs ?? Date.now();
  if (ctx.retired) {
    box.appendChild(h("p", { class: "hd-muted", "data-hook": "today-empty", text:
      "This dog is put down. No picks today, and none coming." }));
    return 0;
  }
  const picks = todaysPicks(bets, nowMs);
  if (picks.length === 0) {
    box.appendChild(h("p", { class: "hd-muted", "data-hook": "today-empty", text: emptyText(ctx.trigger) }));
    return 0;
  }
  box.appendChild(h("ul", { class: "hd-picks", "data-hook": "today-list" }, picks.map((b) => pickRow(b, nowMs))));
  return picks.length;
}

/**
 * Keep it fresh: call `load` (returns the newest bets) now and every 60 s while the tab is visible, and
 * re-render. Returns the poller (stop() it on unmount). A failed refresh leaves what was on screen and says
 * so in the small print; it never blanks the picks.
 */
export function watchToday(box, note, { load, ctx, intervalMs = REFRESH_MS }) {
  let lastBets = [];
  const paint = () => renderToday(box, lastBets, typeof ctx === "function" ? ctx() : ctx);
  const run = async () => {
    try {
      lastBets = await load();
      if (note) note.textContent = "Refreshes every minute while this tab is open.";
    } catch (err) {
      if (note) note.textContent = "Couldn't refresh just now. Showing the last picks we had.";
    }
    paint();
  };
  const poller = createPoller({ run, intervalMs });
  poller.start();
  return { poller, run, paint, setBets(bets) { lastBets = bets; paint(); } };
}
