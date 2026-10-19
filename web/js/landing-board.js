/**
 * The landing page's first screen: a live mini leaderboard (the top five models by paper bankroll, with record,
 * the account balance, its return and bets) and the latest five tickets. Every model is a $1,000 paper account
 * and one unit is $10 (docs/BANKROLL.md); the panel says so in the server's own words.
 *
 * Reads the PUBLIC GET /hounds and GET /hounds/stream (the same payloads the leaderboard page reads) and fills
 * [data-hook='lb-board'], [data-hook='lb-tickets'] and [data-hook='lb-asof'] in web/landing.html. Nothing is
 * typed into the markup: with no answer a panel says so and names no figure, and a server still working the
 * numbers out says that and tries once more. The ranking is by the account balance (priced at the average price),
 * graded bets only (the same order as the leaderboard page), baselines left to the leaderboard, and every row carries its bet
 * count, so a hot start on a handful of bets never reads as more than it is. The voice guide is docs/VOICE.md.
 *
 * SEASONS. The board is the newest season's (the server's default, Season 2 since Oct 18) and only RANKED models
 * count: 10 settled bets in the season. A season a few days old has few of them, so the board shows whoever has
 * qualified, topped up to five with the best of the QUALIFYING ROUND (not numbered, return greyed, each with an
 * "x/10 bets" pill), and one line saying how old the season is and that more models qualify at 10 bets; the
 * latest tickets beside it are every model's, newest first.
 */

import { apiGet } from "./api.js";
import {
  h, clearNode, monogram, categoryOf, houndHref, isWarming, NOT_REPORTED, fmtPrice,
} from "./hounds-core.js";
import { unitsOf } from "./hounds-voice.js";
import { dogFace, poseOfHound } from "./dog-avatar.js";
import {
  recordText, betsOf, onlyTickets, ticketState, ticketStatus, RESULT_WORDS, ticketPrice, pickOf,
  marketLabel, recordedText, freshness, isRanked, qualifyingRows, progressText, NA,
  sortByBankroll, bankrollNow, returnPctOf, fmtUsd, fmtPct, bankrollRules, isSmallSample, smallSampleTitle,
  basisTagText, RECORDED_TITLE, isOldRule, OLD_RULE_TAG, OLD_RULE_TITLE,
} from "./hounds-board.js";
import { minRanked, seasonAgeText } from "./hounds-season.js";

export const TOP_MODELS = 5;
export const LATEST_TICKETS = 5;
export const WARMING_RETRY_MS = 6000;

const q = (hook) => document.querySelector(`[data-hook='${hook}']`);

/** The models that earn a place on the landing board: running, not a baseline, and RANKED (`min` settled bets in the season). */
export function topModels(hounds, n = TOP_MODELS, min) {
  const eligible = (Array.isArray(hounds) ? hounds : []).filter((x) => x
    && x.status !== "retired" && x.status !== "not_started" && categoryOf(x) !== "baseline" && unitsOf(x) !== null
    && isRanked(x, min));
  return sortByBankroll(eligible).slice(0, n);
}

function tone(n) {
  return n === null || n === undefined ? "flat" : n > 0 ? "up" : n < 0 ? "down" : "flat";
}

/** Models that count for the landing board but are short of the ranking bar: the QUALIFYING ROUND, best first. */
export function qualifyingModels(hounds, n = TOP_MODELS, min) {
  const eligible = (Array.isArray(hounds) ? hounds : []).filter((x) => x
    && x.status !== "retired" && x.status !== "not_started" && categoryOf(x) !== "baseline" && unitsOf(x) !== null
    && !isRanked(x, min));
  return qualifyingRows(eligible).slice(0, n);
}

/**
 * `qual`: not ranked yet, so no rank number, a greyed return ("small sample") and a "3/10 bets" pill in the Bets
 * column. A ranked model with under 20 settled bets is greyed the same way, with the reason as its tooltip. The
 * balance is the paper account from the shared start; the return is the % that balance moved.
 */
function boardRow(hound, rank, qual, min) {
  const balance = bankrollNow(hound);
  const ret = returnPctOf(hound);
  const small = qual || isSmallSample(hound);
  const grey = small ? { class: "lbnum lbtone--small", title: smallSampleTitle(hound) } : null;
  return h("tr", { class: qual ? "lbrow lbrow--qual" : "lbrow", "data-hound": hound.id }, [
    h("td", { class: "lbnum lbrank", text: qual ? "-" : String(rank) }),
    h("td", { class: "lbmodel" }, [
      h("span", { class: "lbdog", "data-hook": "lb-dog" }, [dogFace(hound, { size: 30, pose: poseOfHound(hound) })]),
      h("a", { class: "lbname", href: houndHref(hound.id), text: hound.name || NOT_REPORTED })]),
    h("td", { class: "lbnum", "data-hook": "lb-record", text: recordText(hound) }),
    h("td", { ...(grey || { class: "lbnum" }), "data-hook": "lb-bankroll" }, [fmtUsd(balance),
      basisTagText(hound) ? h("small", { class: "lbbasis", "data-hook": "lb-basis", title: RECORDED_TITLE, text: basisTagText(hound) }) : null]),
    h("td", { ...(grey || { class: `lbnum lbtone--${tone(ret)}` }), "data-hook": "lb-return", text: fmtPct(ret) }),
    qual
      ? h("td", { class: "lbnum" }, [h("span", { class: "lbpill", "data-hook": "lb-progress",
        title: `Needs ${min} settled bets to be ranked`, text: progressText(hound, min) })])
      : h("td", { class: "lbnum", "data-hook": "lb-bets", text: String(betsOf(hound)) }),
  ]);
}

/**
 * Fill the board. `meta` is the payload's `season` block. Fewer than five ranked models: show those, then the best
 * of the qualifying round with "x/10 bets" pills to make five, and, in `note` (when given), the season's age and
 * the bar for qualifying. `today` is a YYYY-MM-DD for the age line.
 */
export function renderBoard(body, hounds, meta, note, today) {
  clearNode(body);
  const min = minRanked(meta);
  const top = topModels(hounds, TOP_MODELS, min);
  const label = (meta && meta.label) || "this season";
  // Fewer than five ranked: the best of the qualifying round fill the board, each with its progress pill.
  const filler = top.length < TOP_MODELS ? qualifyingModels(hounds, TOP_MODELS - top.length, min) : [];
  if (top.length === 0 && filler.length === 0) {
    body.appendChild(h("tr", {}, [h("td", { colspan: 6, class: "lbempty", "data-hook": "lb-empty",
      text: `No model has ${min} settled bets in ${label} yet. Come back after the next slate.` })]));
  } else {
    top.forEach((hound, i) => body.appendChild(boardRow(hound, i + 1, false, min)));
    filler.forEach((hound) => body.appendChild(boardRow(hound, 0, true, min)));
  }
  if (note) {
    const age = top.length < TOP_MODELS && meta && !meta.all_time ? seasonAgeText(meta, today) : "";
    note.textContent = age ? `${age}: more models qualify at ${min} bets.` : "";
    if (age) note.removeAttribute("hidden"); else note.setAttribute("hidden", "");
  }
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
        ` ${marketLabel(t.market)}${price === null ? "" : ` ${fmtPrice(price)}`}`,
        isOldRule(t) ? h("small", { class: "lbold", "data-hook": "lb-old-rule", title: OLD_RULE_TITLE, text: OLD_RULE_TAG }) : null]),
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
  const seasonMeta = data.season && typeof data.season === "object" ? data.season : null;
  renderBoard(body, data.hounds, seasonMeta, q("lb-season-note"));
  const rulesNote = q("lb-bankroll-note");
  if (rulesNote) rulesNote.textContent = bankrollRules(data).label;          // the server's sentence, never typed here
  const seasonTag = q("lb-season");
  if (seasonTag) seasonTag.textContent = seasonMeta && seasonMeta.label ? ` · ${seasonMeta.label}` : "";
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
