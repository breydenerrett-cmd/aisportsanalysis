/**
 * The landing page's kennel panel: the three top dogs by paper units right now, and the latest dog put down.
 *
 * Reads the PUBLIC GET /hounds and GET /hounds/graveyard (the same payloads the kennel page reads) and fills
 * [data-hook='kennel-board'] and [data-hook='kennel-putdown'] in web/landing.html. Nothing is typed into the
 * markup: with no answer the board says so and names no figure, and a server still working the numbers out
 * says that and tries once more. The ranking is by paper units at the average price, forward bets (the same
 * order as the kennel page), baselines left to the kennel page, and every row carries its bet count and its
 * badge, so a hot start on a handful of bets never reads as more than it is. Paper only, not advice.
 * The voice guide is docs/VOICE.md.
 */

import { apiGet } from "./api.js";
import {
  h, clearNode, avatarSvg, vibeOf, categoryOf, fmtUnits, houndHref, fmtWhen, isWarming, NOT_REPORTED,
} from "./hounds-core.js";
import { badgeFor, sortByUnits, unitsOf, wlText, streakView, causeText, epitaphFor } from "./hounds-voice.js";

export const TOP_DOGS = 3;
export const WARMING_RETRY_MS = 6000;

const q = (hook) => document.querySelector(`[data-hook='${hook}']`);

/** The dogs that earn a place on the landing board: still in the race, not a baseline, with bets on the board. */
export function topDogs(hounds, n = TOP_DOGS) {
  const eligible = (Array.isArray(hounds) ? hounds : []).filter((x) => x
    && x.status !== "retired" && x.status !== "not_started" && categoryOf(x) !== "baseline" && unitsOf(x) !== null);
  return sortByUnits(eligible).slice(0, n);
}

/** The most recently put-down dog, by the date it was put down (then by its last bet). Null when there is none. */
export function latestPutDown(graveyard) {
  const list = (Array.isArray(graveyard) ? graveyard : []).filter((x) => x && x.status !== undefined);
  const key = (x) => `${(x.retired && x.retired.date) || ""}|${x.last_bet_utc || ""}`;
  return list.slice().sort((a, b) => (key(a) < key(b) ? 1 : key(a) > key(b) ? -1 : 0))[0] || null;
}

function dogAvatar(hound, size, extra) {
  return avatarSvg(hound.name, Object.assign({ size, category: categoryOf(hound), vibe: vibeOf(hound) }, extra || {}));
}

function boardRow(hound, rank) {
  const units = unitsOf(hound);
  const badge = badgeFor(hound);
  const rec = hound.record || {};
  const streak = streakView(hound.form);
  return h("li", { class: "kennel__row", "data-hound": hound.id }, [
    h("span", { class: "kennel__rank", text: `#${rank}` }),
    dogAvatar(hound, 44),
    h("span", { class: "kennel__who" }, [
      h("a", { class: "kennel__name", href: houndHref(hound.id), text: hound.name || NOT_REPORTED }),
      h("span", { class: "kennel__wl", text: `${wlText(rec)} in ${rec.bets} ${rec.bets === 1 ? "bet" : "bets"}${streak ? ` · ${streak.text}` : ""}` }),
    ]),
    h("span", { class: `kennel__units kennel__units--${units > 0 ? "up" : units < 0 ? "down" : "flat"}`,
      "data-hook": "kennel-units", text: fmtUnits(units) }),
    h("span", { class: `kennel__badge kennel__badge--${badge.tone}`, "data-hook": "kennel-badge", "data-badge": badge.key,
      text: badge.text }),
  ]);
}

export function renderBoard(box, hounds) {
  clearNode(box);
  const dogs = topDogs(hounds);
  if (dogs.length === 0) {
    box.appendChild(h("li", { class: "kennel__empty", "data-hook": "kennel-empty",
      text: "No dog has a bet on the board yet. Come back after the next slate." }));
    return;
  }
  dogs.forEach((hound, i) => box.appendChild(boardRow(hound, i + 1)));
}

export function renderPutDown(box, graveyard) {
  clearNode(box);
  const dog = latestPutDown(graveyard);
  if (!dog) {
    box.hidden = true;
    box.setAttribute("hidden", "");
    return;
  }
  box.hidden = false;
  box.removeAttribute("hidden");
  const retired = dog.retired || {};
  box.appendChild(h("p", { class: "kennel__putdown-label", text: "Latest put down 💀" }));
  box.appendChild(h("div", { class: "kennel__stone" }, [
    dogAvatar(dog, 40, { gray: true, dead: true }),
    h("div", {}, [
      h("a", { class: "kennel__name", href: houndHref(dog.id), "data-hook": "kennel-putdown-name", text: dog.name || NOT_REPORTED }),
      h("p", { class: "kennel__epitaph", "data-hook": "kennel-epitaph", text: `“${epitaphFor(dog)}”` }),
      h("p", { class: "kennel__cause", text: `${causeText(retired.cause)}${retired.date ? ` (${fmtWhen(retired.date)})` : ""}` }),
    ]),
  ]));
}

let retried = false;

export async function fillKennel() {
  const board = q("kennel-board");
  const putdown = q("kennel-putdown");
  if (!board) return;
  const [boardResult, graveResult] = await Promise.allSettled([apiGet("/hounds"), apiGet("/hounds/graveyard")]);
  const data = boardResult.status === "fulfilled" ? boardResult.value : null;
  if (!data || typeof data !== "object") {
    clearNode(board);
    board.appendChild(h("li", { class: "kennel__empty", "data-hook": "kennel-down",
      text: "The leaderboard isn't answering right now. The kennel page will have it." }));
    if (putdown) { putdown.hidden = true; putdown.setAttribute("hidden", ""); }
    return;
  }
  if (isWarming(data)) {
    clearNode(board);
    board.appendChild(h("li", { class: "kennel__empty", "data-hook": "kennel-warming",
      text: "The kennel is warming up. Numbers in a few seconds." }));
    if (!retried && typeof setTimeout === "function") {
      retried = true;
      setTimeout(() => { fillKennel(); }, WARMING_RETRY_MS);
    }
    return;
  }
  renderBoard(board, data.hounds);
  const grave = graveResult.status === "fulfilled" && graveResult.value && !isWarming(graveResult.value)
    ? graveResult.value.hounds : [];
  if (putdown) renderPutDown(putdown, grave);
}
