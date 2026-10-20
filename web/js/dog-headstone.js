/**
 * A headstone: what is left of a dog its owner took out back (src/hounds/interact/outback.py).
 *
 * The server freezes the stone when the dog is buried (a row in `hound_events`), so every number here is the dog's FINAL
 * one and never moves again: the record, the paper bankroll, the best win, the dates and the epitaph. This file only draws
 * it. The same card is the burial reveal, the headstone panel on a buried dog's page, a row of the graveyard and the
 * Graveyard section of a kennel page.
 *
 * Paper only. Nothing here is a claim about money: the bankroll is the paper account the dog finished with.
 */

import { h, isNum } from "./hounds-core.js";
import { dogBadge, lookFor } from "./dog-avatar.js";
import { fmtUsd } from "./hounds-board.js";

export const FROZEN_NOTE = "Its record is frozen. Every ticket it made stays on the ledger.";

/** "7-12" or "7-12-1". */
export function recordText(rec) {
  const r = rec || {};
  return `${r.wins || 0}-${r.losses || 0}${r.pushes ? `-${r.pushes}` : ""}`;
}

/** "Oct 18, 2026" from "2026-10-18", else the text as it came. */
export function dayText(day) {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(day || ""));
  if (!m) return String(day || "");
  const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  return `${months[Number(m[2]) - 1]} ${Number(m[3])}, ${m[1]}`;
}

/** "Trained x2" (the badge on a dog that has been sent to training), or null for a dog that has not. */
export function trainedBadge(times) {
  return isNum(times) && times > 0
    ? h("span", { class: "dk-chip dk-chip--trained", "data-hook": "trained-badge", text: `Trained ×${times}` }) : null;
}

function fact(label, value, hook) {
  return h("div", { class: "hs__fact" }, [h("dt", { text: label }), h("dd", Object.assign({ text: value }, hook ? { "data-hook": hook } : {}))]);
}

function bestWinText(win) {
  if (!win || !win.selection) return "none on the record";
  const price = isNum(win.price) ? ` at ${win.price > 0 ? "+" : ""}${win.price}` : "";
  const units = isNum(win.units) ? `, ${win.units > 0 ? "+" : ""}${win.units.toFixed(2)}u` : "";
  return `${win.selection}${price}${units}`;
}

/** The bankroll the dog finished with, "$1,023 (+2.3%)", or "n/a" when the server had none. */
export function finalBankrollText(box) {
  const b = box || {};
  if (!isNum(b.final)) return "n/a";
  const pct = isNum(b.return_pct) ? ` (${b.return_pct > 0 ? "+" : ""}${b.return_pct.toFixed(1)}%)` : "";
  return `${fmtUsd(b.final)}${pct}`;
}

/**
 * One headstone as a card. `compact` leaves out the facts list (a row in a long list); `heading` is the tag for the name.
 * Every dog on the stone is a link to its own page, where the whole record is.
 */
export function headstoneCard(stone, { compact = false, heading = "h3", showKennel = true } = {}) {
  const s = stone || {};
  const look = s.look || lookFor(s.hound_id || s.name);
  const badge = h("span", { class: "hs__badge", "aria-hidden": "true" }, [dogBadge(look, { size: 64, mood: "idle", id: s.hound_id, name: s.name })]);
  const body = h("div", { class: "hs__body" }, [
    h(heading, { class: "hs__name" }, [h("a", { href: s.page_href || `hound.html?id=${encodeURIComponent(s.hound_id || "")}`, "data-hook": "headstone-name", text: s.name || "A dog" })]),
    h("p", { class: "hs__dates", "data-hook": "headstone-dates", text: `${dayText(s.born)} to ${dayText(s.died)}` }),
    h("p", { class: "hs__epitaph", "data-hook": "headstone-epitaph", text: s.epitaph || "" }),
    h("p", { class: "hs__chips" }, [
      h("span", { class: "dk-chip", "data-hook": "headstone-frozen", text: "Record frozen" }),
      isNum(s.version_no) && s.version_no > 1 ? h("span", { class: "dk-chip", text: `Version ${s.version_no}` }) : null,
      trainedBadge(s.trained_times)])]);
  if (!compact) {
    body.appendChild(h("dl", { class: "hs__facts" }, [
      fact("Final record", recordText(s.record), "headstone-record"),
      fact("Final bankroll", finalBankrollText(s.bankroll), "headstone-bankroll"),
      fact("Best win", bestWinText(s.best_win), "headstone-bestwin"),
      s.kennel && showKennel ? h("div", { class: "hs__fact" }, [h("dt", { text: "Kennel" }),
        h("dd", {}, [h("a", { href: s.kennel.href, "data-hook": "headstone-kennel", text: s.kennel.display })])]) : null]));
  }
  const card = h("article", { class: "hs", "data-hook": "headstone", "data-id": s.hound_id || "" }, [badge, body]);
  return card;
}
