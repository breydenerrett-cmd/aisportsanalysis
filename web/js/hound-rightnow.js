/**
 * "WHAT I'D PLAY RIGHT NOW": the hound page's headline card (owner request 2026-10-21).
 *
 * A bettor who opens a hound wants to hear what it likes at this moment. GET /hounds/{id}/right-now
 * (src/hounds/interact/right_now.py) runs the hound's OWN rule over the CURRENT board and sends the games that fit and have not
 * started, best first by the hound's OWN rank_by. This file only draws that answer, in the hound's voice (web/js/hound-lines.js).
 *
 *   THE METER. "How sure it is" is how strongly the game fits ITS rule: its place among the games that fit, ranked by what the
 *   hound ranks by. It is shown as pips and a phrase, never as a percentage, and an expandable line says what it is and that it is
 *   not a chance of winning. Nothing here is a win probability, an edge or a value estimate.
 *   THE PRICE. The average price across books, never -200 or worse (the server drops those, and this file drops them again).
 *   THE MONEY. The stake is shown at the viewer's own sizing (web/js/unitsize.js): "$50", or "2% of bankroll".
 *   BUTTONS. "Add as a manual pick" is the existing manual path (POST /hounds/{id}/manual; the owner only, the daily limit and the
 *   one-side-per-game guard are the server's). "Show me another" walks the candidates and wraps.
 *   NOTHING FITS. The hound says so in its voice and names the next game it will look at and when.
 *
 * Every string from the server goes in through textContent (the `h` helper), so nothing is ever parsed as markup.
 */

import { apiGet } from "./api.js";
import { h, clearNode, fmtPrice, isNum, createPoller } from "./hounds-core.js";
import { post, errorText } from "./dog-common.js";
import { stakeWords } from "./unitsize.js";
import { pickLine, nothingLine, voiceOf } from "./hound-lines.js";

export const NOW_POLL_MS = 90000;
export const CAP = -200;
export const PAPER_LINE = "Paper pick, not advice · 21+";
export const PIPS = 5;

/** "2 h 10 min" / "35 min" / "now". */
export function spanWords(minutes) {
  if (!isNum(minutes)) return "";
  const m = Math.round(minutes);
  if (m <= 0) return "now";
  if (m < 90) return `${m} min`;
  const hours = Math.floor(m / 60);
  if (hours >= 48) return `${Math.floor(hours / 24)} days`;
  const rest = m % 60;
  return rest ? `${hours} h ${String(rest).padStart(2, "0")} min` : `${hours} h`;
}

/** "7:10 PM" in the viewer's own clock, "" when the stamp is unreadable. */
export function localClock(stamp) {
  const d = new Date(stamp);
  if (!stamp || Number.isNaN(d.getTime())) return "";
  try { return d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" }); } catch (err) { return ""; }
}

/** "Starts in 2 h 10 min (7:10 PM)". */
export function startsText(c) {
  const rel = isNum(c && c.minutes_to_start) ? (c.minutes_to_start <= 0 ? "Starting now" : `Starts in ${spanWords(c.minutes_to_start)}`) : "Start time not reported";
  const clock = localClock(c && c.start_utc);
  return clock ? `${rel} (${clock})` : rel;
}

/** How many of the five pips are lit for a fit of 0-100. */
export function pipsLit(fit) {
  return isNum(fit) ? Math.max(1, Math.min(PIPS, Math.round((fit / 100) * PIPS))) : 0;
}

/** The candidates this card may show: a price, nothing at -200 or worse. The server already dropped those; this is the second lock on that door. */
export function usableCandidates(data) {
  const list = data && Array.isArray(data.candidates) ? data.candidates : [];
  return list.filter((c) => c && isNum(c.price_average) && c.price_average > CAP && c.event_id);
}

/** The index "Show me another" moves to: the next candidate, wrapping to the first. */
export function nextIndex(index, count) {
  return count > 0 ? (index + 1) % count : 0;
}

const keyOf = (c) => `${c.event_id}|${c.market}|${c.player || ""}`;

function meter(c, defId) {
  const lit = pipsLit(c.fit);
  const pips = [];
  for (let i = 0; i < PIPS; i += 1) pips.push(h("span", { class: `hn-pip${i < lit ? " hn-pip--on" : ""}`, "aria-hidden": "true" }));
  return h("div", { class: "hn-meter", "data-hook": "now-meter", "data-fit": String(c.fit) }, [
    h("div", { class: "hn-meter__row" }, [
      h("span", { class: "hn-meter__label", id: `${defId}-l`, text: "How sure it is" }),
      h("span", { class: "hn-pips", role: "meter", "aria-valuemin": "0", "aria-valuemax": "100", "aria-valuenow": String(c.fit),
        "aria-labelledby": `${defId}-l`, "aria-describedby": defId }, pips),
      h("span", { class: "hn-meter__text", "data-hook": "now-fit-text", text: c.fit_text || "" }),
    ]),
  ]);
}

function whyFold(c, data, defId) {
  const bits = [h("p", { id: defId, "data-hook": "now-fit-def", text: `${data.fit_definition || "How strongly this game fits the hound's own rule."} It is not a win probability.` })];
  if (c.lead) bits.push(h("p", { "data-hook": "now-lead", text: c.lead }));
  if (c.reason) bits.push(h("p", { class: "hn-reason", "data-hook": "now-reason", text: c.reason }));
  if (isNum(c.n_books)) bits.push(h("p", { text: `${c.n_books} ${c.n_books === 1 ? "book is" : "books are"} quoting it${c.best_book && isNum(c.price_best) && c.price_best !== c.price_average ? `; best price ${fmtPrice(c.price_best)} at ${c.best_book}` : ""}.` }));
  return h("details", { class: "hn-why" }, [h("summary", { text: "What does that mean?" }), ...bits]);
}

/**
 * Draw the card body into `body`. `ctx` = { id, data, index, viewer, onAnother, onRecorded }. Exported so a test can draw it
 * from a fixture without a network.
 */
export function renderNow(body, ctx) {
  clearNode(body);
  const data = ctx.data;
  const voice = voiceOf(data && data.voice);
  const list = usableCandidates(data);
  const chips = h("p", { class: "hn-chips" }, [
    h("span", { class: "hn-chip", "data-hook": "now-voice", text: (data && data.voice_label) || "Hound" }),
    h("span", { class: "hn-chip hn-chip--quiet", text: data && data.bets_in_play ? "Games not started, or in play" : "Games that haven't started" }),
  ]);
  body.appendChild(chips);
  if (list.length === 0) {
    const next = data && data.next_look;
    const whenText = next && isNum(next.starts_in_minutes) ? `${next.starts_in_minutes <= 0 ? "starting now" : `starts in ${spanWords(next.starts_in_minutes)}`}${localClock(next.start_utc) ? ` (${localClock(next.start_utc)})` : ""}` : "";
    body.appendChild(h("p", { class: "hn-quote", "data-hook": "now-nothing", text: nothingLine(voice, next && next.game ? { game: next.game, whenText } : null, ctx.id) }));
    if (next && isNum(next.locks_in_minutes)) {
      body.appendChild(h("p", { class: "hn-fine", "data-hook": "now-next", text: next.locks_in_minutes <= 0 ? "I'm already looking at it." : `I'll start looking at it in ${spanWords(next.locks_in_minutes)}.` }));
    } else if (data && data.next_game) {
      body.appendChild(h("p", { class: "hn-fine", "data-hook": "now-next", text: String(data.next_game) }));
    }
    body.appendChild(h("p", { class: "hn-paper", "data-hook": "now-paper", text: PAPER_LINE }));
    return null;
  }
  const index = Math.min(Math.max(0, ctx.index || 0), list.length - 1);
  const c = list[index];
  const defId = `now-def-${index}`;
  body.appendChild(h("p", { class: "hn-quote", "data-hook": "now-quote", text: pickLine(voice, { selection: c.selection, priceText: fmtPrice(c.price_average) }, `${ctx.id}|${keyOf(c)}`) }));
  body.appendChild(h("div", { class: "hn-bet", "data-hook": "now-bet", "data-event": c.event_id, "data-market": c.market }, [
    h("p", { class: "hn-bet__game", "data-hook": "now-game", text: c.game || "" }),
    h("p", { class: "hn-bet__pick" }, [
      h("strong", { class: "hn-bet__sel", "data-hook": "now-selection", text: c.selection || "" }),
      h("span", { class: "hn-bet__price hd-num", "data-hook": "now-price", text: fmtPrice(c.price_average) }),
    ]),
    h("p", { class: "hn-bet__meta" }, [
      h("span", { text: c.market_label || "" }),
      h("span", { "data-hook": "now-start", text: startsText(c) }),
      h("span", { "data-hook": "now-stake", text: `Stake ${stakeWords(isNum(c.stake_units) ? c.stake_units : 1)}` }),
      c.in_play ? h("span", { class: "hn-flag", "data-hook": "now-inplay", text: "In play" }) : null,
      c.stale ? h("span", { class: "hn-flag hn-flag--warn", "data-hook": "now-stale", text: `Board is ${spanWords(c.board_age_minutes)} old` }) : null,
    ]),
  ]));
  body.appendChild(meter(c, defId));
  body.appendChild(whyFold(c, data, defId));
  const status = h("p", { class: "hn-status", role: "status", "data-hook": "now-status" });
  const actions = h("div", { class: "hn-actions" });
  if (data.viewer_is_owner && c.manual && c.manual.can_record) {
    const add = h("button", { type: "button", class: "btn btn--primary hn-add", "data-hook": "now-add", text: "Add as a manual pick",
      "aria-label": `Add ${c.selection} as a manual pick` });
    add.addEventListener("click", async () => {
      add.setAttribute("disabled", "");
      status.textContent = "Adding...";
      try {
        const body2 = { event_id: c.event_id, market: c.market };
        if (c.player) body2.player = c.player;
        const out = await post(`/hounds/${encodeURIComponent(ctx.id)}/manual`, body2);
        clearNode(actions);
        status.textContent = `Added as a manual pick at ${fmtPrice(out && out.ticket && out.ticket.price_average)}. It sits apart from the record. ${out && isNum(out.remaining_today) ? `${out.remaining_today} left today.` : ""}`.trim();
        status.setAttribute("data-state", "ok");
        if (ctx.onRecorded) ctx.onRecorded(out);
      } catch (err) {
        add.removeAttribute("disabled");
        status.textContent = errorText(err);
        status.setAttribute("data-state", "error");
      }
    });
    actions.appendChild(add);
  } else if (data.viewer_is_owner && c.manual && c.manual.blocked) {
    status.textContent = `Can't add this one: ${c.manual.blocked}.`;
    status.setAttribute("data-hook", "now-blocked");
  }
  if (list.length > 1) {
    actions.appendChild(h("button", { type: "button", class: "btn btn--ghost hn-another", "data-hook": "now-another", text: "Show me another",
      on: { click: () => { if (ctx.onAnother) ctx.onAnother(nextIndex(index, list.length)); } } }));
  }
  if (actions.childNodes.length) body.appendChild(actions);
  body.appendChild(status);
  if (list.length > 1) body.appendChild(h("p", { class: "hn-count", "data-hook": "now-count", text: `${index + 1} of ${list.length} that fit` }));
  body.appendChild(h("p", { class: "hn-paper", "data-hook": "now-paper", text: PAPER_LINE }));
  return c;
}

/**
 * Mount the card in `section` (which starts hidden). Resolves with { refresh, state } once drawn, or null when the hound has no rule
 * to run (the server answers 422) or the request fails: the section then stays hidden and the rest of the page is untouched.
 * `onData(data)` is called with every answer so the hero can use the voice.
 */
export async function mountRightNow(section, { id, onData = null, onRecorded = null, poll = true } = {}) {
  const body = section && section.querySelector("[data-hook='right-now-body']");
  if (!body || !id) return null;
  const state = { data: null, index: 0, key: "" };
  const draw = () => {
    renderNow(body, { id, data: state.data, index: state.index, onRecorded,
      onAnother: (i) => { state.index = i; draw(); const el = body.querySelector("[data-hook='now-another']"); if (el && el.focus) el.focus(); } });
    const list = usableCandidates(state.data);
    state.key = list[state.index] ? keyOf(list[state.index]) : "";
  };
  async function refresh() {
    let data = null;
    try { data = await apiGet(`/hounds/${encodeURIComponent(id)}/right-now`); } catch (err) { data = null; }
    if (!data || typeof data !== "object" || !Array.isArray(data.candidates)) { section.setAttribute("hidden", ""); return null; }
    const previous = state.key;
    const before = state.data ? usableCandidates(state.data).map(keyOf).join(",") : null;
    state.data = data;
    const list = usableCandidates(data);
    const same = previous ? list.findIndex((c) => keyOf(c) === previous) : -1;
    state.index = same >= 0 ? same : 0;
    // a refresh that finds the same games leaves the card (and an open "what does that mean?") alone
    if (before === null || before !== list.map(keyOf).join(",")) draw();
    section.removeAttribute("hidden");
    if (onData) onData(data);
    return data;
  }
  const first = await refresh();
  if (first === null) return null;
  if (poll) createPoller({ run: () => { refresh(); }, intervalMs: NOW_POLL_MS }).start();
  return { refresh, state };
}
