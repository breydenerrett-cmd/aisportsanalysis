/**
 * The landing page's first screen: a live mini leaderboard (the top five models by units, with record, ROI and
 * bets) and the latest five tickets.
 *
 * Reads the PUBLIC GET /hounds and GET /hounds/stream (the same payloads the leaderboard page reads) and fills
 * [data-hook='lb-board'], [data-hook='lb-tickets'] and [data-hook='lb-asof'] in web/landing.html. Nothing is
 * typed into the markup: with no answer a panel says so and names no figure, and a server still working the
 * numbers out says that and tries once more. The ranking is by units at the average price, graded bets only
 * (the same order as the leaderboard page), baselines left to the leaderboard, and every row carries its bet
 * count, so a hot start on a handful of bets never reads as more than it is. The voice guide is docs/VOICE.md.
 */

import { apiGet } from "./api.js";
import {
  h, clearNode, monogram, categoryOf, houndHref, isWarming, NOT_REPORTED, fmtPrice,
} from "./hounds-core.js";
import { sortByUnits, unitsOf } from "./hounds-voice.js";
import {
  recordText, roiOf, fmtRoi, fmtUnitsPlain, betsOf, onlyTickets, ticketState, RESULT_WORDS, ticketPrice, pickOf,
  marketLabel, recordedText, freshness, NA,
} from "./hounds-board.js";

export const TOP_MODELS = 5;
export const LATEST_TICKETS = 5;
export const WARMING_RETRY_MS = 6000;

const q = (hook) => document.querySelector(`[data-hook='${hook}']`);

/** The models that earn a place on the landing board: running, not a baseline, with a graded bet. */
export function topModels(hounds, n = TOP_MODELS) {
  const eligible = (Array.isArray(hounds) ? hounds : []).filter((x) => x
    && x.status !== "retired" && x.status !== "not_started" && categoryOf(x) !== "baseline" && unitsOf(x) !== null);
  return sortByUnits(eligible).slice(0, n);
}

function tone(n) {
  return n === null || n === undefined ? "flat" : n > 0 ? "up" : n < 0 ? "down" : "flat";
}

function boardRow(hound, rank) {
  const units = unitsOf(hound);
  const roi = roiOf(hound);
  return h("tr", { class: "lbrow", "data-hound": hound.id }, [
    h("td", { class: "lbnum lbrank", text: String(rank) }),
    h("td", { class: "lbmodel" }, [
      monogram(hound.name, { size: 26, category: categoryOf(hound) }),
      h("a", { class: "lbname", href: houndHref(hound.id), text: hound.name || NOT_REPORTED })]),
    h("td", { class: "lbnum", "data-hook": "lb-record", text: recordText(hound) }),
    h("td", { class: `lbnum lbtone--${tone(units)}`, "data-hook": "lb-units", text: fmtUnitsPlain(units) }),
    h("td", { class: `lbnum lbtone--${tone(roi)}`, "data-hook": "lb-roi", text: fmtRoi(roi) }),
    h("td", { class: "lbnum", "data-hook": "lb-bets", text: String(betsOf(hound)) }),
  ]);
}

export function renderBoard(body, hounds) {
  clearNode(body);
  const top = topModels(hounds);
  if (top.length === 0) {
    body.appendChild(h("tr", {}, [h("td", { colspan: 6, class: "lbempty", "data-hook": "lb-empty",
      text: "No model has a graded bet yet. Come back after the next slate." })]));
    return;
  }
  top.forEach((hound, i) => body.appendChild(boardRow(hound, i + 1)));
}

function ticketRow(t) {
  const status = ticketState(t);
  const price = ticketPrice(t);
  const rec = recordedText(t);
  return h("li", { class: "lbticket", "data-status": status, "data-hook": "lb-ticket" }, [
    h("div", { class: "lbticket__main" }, [
      t.hound_id !== undefined
        ? h("a", { class: "lbticket__model", href: houndHref(t.hound_id), text: t.hound_name || NOT_REPORTED })
        : h("span", { class: "lbticket__model", text: t.hound_name || NOT_REPORTED }),
      h("span", { class: "lbticket__pick" }, [h("strong", { text: pickOf(t) }),
        ` ${marketLabel(t.market)}${price === null ? "" : ` ${fmtPrice(price)}`}`]),
      h("span", { class: "lbticket__game", text: [t.game || "", rec.kind === "before" ? rec.text.replace(/^.*?, /, "recorded ") : ""]
        .filter(Boolean).join(" · ") }),
    ]),
    h("span", { class: `lbres lbres--${status}`, "data-hook": "lb-status", text: RESULT_WORDS[status] }),
  ]);
}

export function renderTickets(list, items) {
  clearNode(list);
  const tickets = onlyTickets(items).slice(0, LATEST_TICKETS);
  if (tickets.length === 0) {
    list.appendChild(h("li", { class: "lbempty", "data-hook": "lb-tickets-empty", text: "No tickets recorded yet." }));
    return;
  }
  for (const t of tickets) list.appendChild(ticketRow(t));
}

let retried = false;

export async function fillBoard() {
  const body = q("lb-board");
  const list = q("lb-tickets");
  if (!body) return;
  const [boardResult, streamResult] = await Promise.allSettled([
    apiGet("/hounds"), apiGet(`/hounds/stream?page=1&page_size=${LATEST_TICKETS * 3}`)]);
  const data = boardResult.status === "fulfilled" ? boardResult.value : null;
  if (!data || typeof data !== "object") {
    clearNode(body);
    body.appendChild(h("tr", {}, [h("td", { colspan: 6, class: "lbempty", "data-hook": "lb-down",
      text: "The leaderboard is not answering right now. The leaderboard page will have it." })]));
    if (list) { clearNode(list); list.appendChild(h("li", { class: "lbempty", text: "The ticket feed is not answering right now." })); }
    return;
  }
  if (isWarming(data)) {
    clearNode(body);
    body.appendChild(h("tr", {}, [h("td", { colspan: 6, class: "lbempty", "data-hook": "lb-warming",
      text: "The leaderboard is warming up. Numbers in a few seconds." })]));
    if (!retried && typeof setTimeout === "function") {
      retried = true;
      setTimeout(() => { fillBoard(); }, WARMING_RETRY_MS);
    }
    return;
  }
  renderBoard(body, data.hounds);
  const asOf = q("lb-asof");
  if (asOf) {
    const fresh = freshness(data);
    asOf.textContent = fresh.label ? `Data as of ${fresh.label}${fresh.stale ? ", updating" : ""}` : "";
    asOf.setAttribute("data-stale", fresh.stale ? "true" : "false");
  }
  if (list) {
    const stream = streamResult.status === "fulfilled" && streamResult.value && !isWarming(streamResult.value) ? streamResult.value : null;
    if (stream) renderTickets(list, stream.items);
    else {
      clearNode(list);
      list.appendChild(h("li", { class: "lbempty", "data-hook": "lb-tickets-down", text: "The ticket feed is not answering right now." }));
    }
  }
}

export { NA };
