/**
 * "WHAT I'VE BEEN UP TO": the hound's recent action as a short feed in its own chill voice (owner request 2026-10-21).
 *
 * ALL OF IT IS REAL DATA. The lines are made from tickets the server sent (the open ones, and the newest graded ones from the
 * hound's own payload) and its streak; nothing is invented, and a hound with no tickets says so instead of filling the space. The
 * wording is web/js/hound-lines.js; the paper dollars on a settled ticket are at the viewer's own sizing (web/js/hound-money.js).
 * The feed shows what happened. It never says what to do, and it never calls a streak a reason to expect the next one.
 */

import { h, clearNode, fmtPrice, isNum, shortDate } from "./hounds-core.js";
import { ticketState, ticketPrice, pickOf } from "./hounds-board.js";
import { settledLine, openLine, streakLine, voiceOf } from "./hound-lines.js";
import { signedMoney } from "./hound-money.js";

export const MAX_OPEN = 4;
export const MAX_SETTLED = 5;
export const EMPTY_TEXT = "Nothing on the card yet. Still sniffing around the board.";

const isForward = (t) => !t || t.segment === undefined || t.segment === "forward";

/** "7:10 PM" or "" for a start stamp, in the viewer's own clock. */
function clockOf(stamp) {
  const d = new Date(stamp);
  if (!stamp || Number.isNaN(d.getTime())) return "";
  try { return d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" }); } catch (err) { return ""; }
}

/**
 * The feed's items, newest first within each group: { kind: "open"|"won"|"lost"|"push"|"streak", text, when }.
 *   open    = tickets on the card now (recorded, not yet graded);
 *   settled = the newest graded live tickets;
 *   streak  = one line when the form says two or more in a row.
 */
export function buildFeed({ voice = "generic", open = [], graded = [], streak = null, sizing, seed = "" } = {}) {
  const v = voiceOf(voice);
  const items = [];
  const openRows = (Array.isArray(open) ? open : []).filter((t) => t && isForward(t) && ticketState(t) === "pending").slice(0, MAX_OPEN);
  for (const t of openRows) {
    const price = ticketPrice(t);
    const clock = clockOf(t.start_utc);
    items.push({ kind: "open", when: "On the card",
      text: openLine(v, { selection: pickOf(t), priceText: price === null ? "" : fmtPrice(price), game: t.game || "", whenText: clock ? `First pitch or kickoff ${clock}.` : "" }, `${seed}|${t.selection}|${t.date}`) });
  }
  if (streak && isNum(streak.length) && streak.length >= 2 && (streak.kind === "W" || streak.kind === "L")) {
    items.push({ kind: "streak", when: "Form", text: streakLine(v, streak.kind, streak.length) });
  }
  const settled = (Array.isArray(graded) ? graded : []).filter((t) => t && isForward(t) && ["won", "lost", "push"].includes(ticketState(t))).slice(0, MAX_SETTLED);
  for (const t of settled) {
    const state = ticketState(t);
    const price = ticketPrice(t);
    items.push({ kind: state, when: shortDate(t.date) || "",
      text: settledLine(v, { result: state, selection: pickOf(t), priceText: price === null ? "" : fmtPrice(price),
        moneyText: state === "push" ? "" : signedMoney(t.units, sizing) }, `${seed}|${t.selection}|${t.date}`) });
  }
  return items;
}

/** Draw the feed into `box`. An empty feed says so in the hound's own words. */
export function renderFeed(box, items) {
  clearNode(box);
  if (!items.length) {
    box.appendChild(h("p", { class: "hf-empty", "data-hook": "feed-empty", text: EMPTY_TEXT }));
    return;
  }
  box.appendChild(h("ul", { class: "hf-feed", "data-hook": "feed-list" }, items.map((it) => h("li", { class: "hf-item", "data-kind": it.kind, "data-hook": "feed-item" }, [
    h("span", { class: "hf-when", text: it.when }),
    h("span", { class: "hf-text", text: it.text }),
  ]))));
}
