/**
 * Tickets as rows. A ticket is one bet a model recorded: the game, the pick, the market, the price, how many
 * books were quoting it, when it went on the record against the first pitch, and where it stands (PENDING,
 * WON, LOST, PUSH, VOID) with the units it moved. The feed on the leaderboard page, a model's drawer, the
 * model page's two tables and the landing page's latest five all build their rows here, so a number reads the
 * same wherever it appears. Only what the server sent is shown; a missing field is "n/a", never a guess.
 */

import { h, isNum, signed, fmtPrice, shortDate, houndHref, NOT_REPORTED } from "./hounds-core.js";
import { signedMoney } from "./hound-money.js";
import { liveSpan, liveAttrs, watchTickets } from "./ticket-live.js";
import {
  ticketStatus, ticketState, RESULT_WORDS, recordedText, ticketPrice, pickOf, marketLabel, booksText, NA,
  isOldRule, OLD_RULE_TAG, OLD_RULE_TITLE,
} from "./hounds-board.js";

/** The small tag on a ticket at -200 or worse (a price the rule no longer allows): null for every other ticket. */
export function oldRuleTag(ticket) {
  return isOldRule(ticket)
    ? h("small", { class: "hd-oldrule", "data-hook": "old-rule", title: OLD_RULE_TITLE, text: OLD_RULE_TAG }) : null;
}

const UNGRADED_TITLE = "No grade yet, and the game started more than 36 hours ago. Not counted in the record.";

/**
 * Start the live view for a freshly built list (web/js/ticket-live.js): the money on graded tickets, and where each pending
 * ticket's game stands (upcoming / live / final, grading). Deferred one tick so the list is on the page first. A list with no
 * ticket the server can speak to costs nothing: no request is made.
 */
function watch(list) {
  if (typeof setTimeout === "function") setTimeout(() => { try { watchTickets(list); } catch (err) { /* decoration only */ } }, 0);
  return list;
}

/** The status chip: the word is the signal, the colour only agrees with it. Takes the whole ticket so the
 * server's UNGRADED status can show; a bare result string still works. */
export function resultChip(ticket, hook = "ticket-status") {
  const key = ticket !== null && typeof ticket === "object" ? ticketState(ticket) : ticketStatus(ticket);
  const attrs = { class: `hd-res hd-res--${key}`, "data-result": key, "data-hook": hook, text: RESULT_WORDS[key] };
  if (key === "ungraded") attrs.title = UNGRADED_TITLE;
  return h("span", attrs);
}

/** "+0.91u" / "-1.00u" for a graded ticket, "" while it is open. */
export function ticketUnits(ticket) {
  return ticketStatus(ticket && ticket.result) !== "pending" && isNum(ticket && ticket.units)
    ? `${signed(ticket.units, 2)}u` : "";
}

/** "+2.3" / "-0.4" / "n/a": closing-line value in points, as the graded table prints it. */
function clvText(ticket) {
  const v = ticket && ticket.clv_pts;
  return isNum(v) ? `${v > 0 ? "+" : v < 0 ? "-" : ""}${Math.abs(v).toFixed(1)}` : NA;
}

/**
 * One ticket as a stacked card, for a phone (CSS shows it under 640px and hides the table or the row grid).
 * Line 1: the pick and its price, bold, with the status chip on the right. Line 2: the game and the market.
 * Line 3: the date and when it went on the record against the start. A graded ticket adds line 4: its result,
 * units and closing-line value. The closing PRICE is not in the payload and is not invented; CLV points are.
 * `showModel` puts the model's name on line 2 (the cross-model feed).
 */
export function ticketCard(ticket, { showModel = false, name = "", flip = false } = {}) {
  const t = ticket || {};
  const state = ticketState(t);
  const price = ticketPrice(t);
  const rehearsal = t.segment === "replay";
  const model = name || t.hound_name || t.name || "";
  const units = ticketUnits(t);
  const graded = state !== "pending" && state !== "ungraded";
  const line2 = [h("span", { class: "hd-card__game", text: t.game || NOT_REPORTED }),
    h("span", { class: "hd-card__mkt", text: marketLabel(t.market) })];
  if (t.live_price_at_utc) line2.push(liveTag(t));
  if (showModel && model) {
    line2.push(t.hound_id !== undefined
      ? h("a", { class: "hd-card__model", href: houndHref(t.hound_id), text: model })
      : h("span", { class: "hd-card__model", text: model }));
  }
  const rec = recordedText(t);
  const books = booksText(t);
  const lines = [
    h("div", { class: "hd-card__l1" }, [
      h("span", { class: "hd-card__pick" }, [
        h("strong", { class: "hd-card__pickname", "data-hook": "card-pick", text: pickOf(t) }),
        h("strong", { class: "hd-num hd-card__price", "data-hook": "card-price", text: price === null ? NA : fmtPrice(price) }),
        oldRuleTag(t),
      ]),
      resultChip(t, "card-status"),
    ]),
    h("div", { class: "hd-card__l2", "data-hook": "card-game" }, line2.concat([liveSpan()])),
    h("div", { class: "hd-card__l3", "data-hook": "card-when" }, [
      h("span", { class: "hd-num", text: shortDate(t.date) || NA }),
      rehearsal ? h("span", { class: "hd-rec hd-rec--rehearsal", text: "Written after the games; never counted" })
        : h("span", { class: `hd-rec hd-rec--${rec.kind}`, text: rec.text }),
      books ? h("span", { class: "hd-aux", text: books }) : null,
    ]),
  ];
  if (graded) {
    const tone = !units ? "none" : t.units > 0 ? "up" : t.units < 0 ? "down" : "flat";
    lines.push(h("div", { class: "hd-card__l4", "data-hook": "card-result" }, [
      h("span", { class: "hd-card__res", text: RESULT_WORDS[state] }),
      h("span", Object.assign({ class: `hd-num hd-tone--${tone}`, "data-hook": "card-units", text: units || NA },
        flip && units ? { "data-count": "1", "data-count-ms": "500" } : {})),
      units ? h("span", { class: `hd-num hd-money hd-tone--${tone}`, "data-hook": "card-money", title: "Paper dollars at your unit size", text: signedMoney(t.units) }) : null,
      h("span", { class: "hd-num", "data-hook": "card-clv", text: `CLV ${clvText(t)}${isNum(t.clv_pts) ? " pts" : ""}` }),
    ]));
  }
  if (t.reason) {
    lines.push(h("details", { class: "hd-card__why", "data-hook": "card-why" }, [
      h("summary", { text: "Why this bet" }), h("p", { text: t.reason })]));
  }
  return h("div", Object.assign({ class: "hd-card", "data-hook": "ticket-card", "data-status": state,
    "data-segment": String(t.segment || "") }, liveAttrs(t)), lines);
}

/** The price, with the best quote and its book as small print when they differ from the headline price. */
export function priceCell(ticket) {
  const price = ticketPrice(ticket);
  const best = isNum(ticket && ticket.price) ? ticket.price : null;
  const small = booksText(ticket);
  const sub = [best !== null && best !== price ? `best ${fmtPrice(best)}` : "", small].filter(Boolean).join(" · ");
  return h("span", { class: "hd-price" }, [
    h("strong", { class: "hd-num", text: price === null ? NA : fmtPrice(price) }),
    sub ? h("small", { class: "hd-aux", text: sub }) : null,
    oldRuleTag(ticket),
  ]);
}

/** The recorded-before-the-start line. */
export function recordedCell(ticket) {
  const rec = recordedText(ticket);
  return h("span", { class: `hd-rec hd-rec--${rec.kind}`, "data-hook": "ticket-recorded", text: rec.text });
}

/**
 * One ticket as a list row. `showModel` adds the model's name (the cross-model feed); the model's own pages
 * leave it off. The row is a grid: when, the game and pick, the price, the record line and the result.
 */
/** "Live bet · price at 20:14 UTC": an in-play ticket's label (the capture time of the live price it took, in UTC like the
 *  "recorded" time on the same ticket). null on every ordinary ticket. */
export function liveTag(t) {
  if (!t || !t.live_price_at_utc) return null;
  const at = new Date(t.live_price_at_utc);
  const pad = (v) => String(v).padStart(2, "0");
  const when = Number.isNaN(at.getTime()) ? "" : ` · price at ${pad(at.getUTCHours())}:${pad(at.getUTCMinutes())} UTC`;
  return h("span", { class: "hd-ticket__live", "data-hook": "ticket-live", text: `Live bet${when}` });
}

export function ticketItem(ticket, { showModel = true, name = "" } = {}) {
  const t = ticket || {};
  const status = ticketState(t);
  const model = name || t.hound_name || t.name || "";
  const units = ticketUnits(t);
  return h("li", Object.assign({ class: "hd-ticket", "data-status": status, "data-hound": t.hound_id === undefined ? "" : String(t.hound_id),
    "data-hook": "ticket" }, liveAttrs(t)), [
    h("div", { class: "hd-ticket__when" }, [
      h("span", { class: "hd-num", text: shortDate(t.date) || NA }),
      showModel && model ? (t.hound_id !== undefined
        ? h("a", { class: "hd-ticket__model", href: houndHref(t.hound_id), text: model })
        : h("span", { class: "hd-ticket__model", text: model })) : null,
    ]),
    h("div", { class: "hd-ticket__bet" }, [
      h("span", { class: "hd-ticket__game", text: t.game || NOT_REPORTED }),
      h("span", { class: "hd-ticket__pick" }, [
        h("strong", { text: pickOf(t) }),
        h("span", { class: "hd-ticket__mkt", text: marketLabel(t.market) }),
        liveTag(t),
      ]),
    ]),
    h("div", { class: "hd-ticket__price" }, [priceCell(t)]),
    h("div", { class: "hd-ticket__rec" }, [recordedCell(t)]),
    h("div", { class: "hd-ticket__res" }, [
      resultChip(t),
      liveSpan(),
      units ? h("span", { class: `hd-num hd-units-text hd-units-text--${t.units > 0 ? "up" : t.units < 0 ? "down" : "flat"}`,
        text: units }) : null,
    ]),
    // under 640px CSS shows this card in place of the grid above (the same facts, stacked)
    ticketCard(t, { showModel, name }),
  ]);
}

/** A list of ticket rows under a header row that names the columns (hidden on a phone, where rows stack). */
export function ticketList(tickets, opts = {}) {
  const ul = h("ol", { class: "hd-tickets", "data-hook": opts.hook || "ticket-list" });
  ul.appendChild(h("li", { class: "hd-tickets__head", "aria-hidden": "true" }, [
    h("span", { text: opts.showModel === false ? "Date" : "Date / model" }), h("span", { text: "Game / pick" }),
    h("span", { text: "Price" }), h("span", { text: "Recorded" }), h("span", { text: "Status" }),
  ]));
  for (const t of tickets) ul.appendChild(ticketItem(t, opts));
  return watch(ul);
}

/**
 * A model's tickets as a real table: date, game, pick, price, (graded only: CLV points), status,
 * (graded only: units), the rule's reason line and when it went on the record against the start. The wide
 * table scrolls inside its own box between 640px and a desktop width; under 640px CSS swaps it for the same
 * tickets as stacked cards (``ticketCard``), so nothing is cut off on a phone. A rehearsal row (a rule applied to old boards, written after
 * the games) says so instead of showing a recorded-before time, and is never counted anywhere.
 */
export function ticketTable(tickets, { graded = false, hook = "tickets-table", caption = "Tickets", flip: flipCount = 0 } = {}) {
  const head = ["Date", "Game", "Pick", "Price"].concat(graded ? ["CLV pts"] : [])
    .concat(["Status"]).concat(graded ? ["Units"] : []).concat(["Rule reason", "Recorded"]);
  const rows = tickets.map((t, index) => {
    // R6 (web/js/first-grade.js): the newest `flip` tickets were graded since this person last looked. Marked here, animated by
    // css/lh.css under data-reveal="play"; the mark never reads the result, so a win, a loss and a push move the same way.
    const fresh = index < flipCount;
    const status = ticketState(t);
    const rehearsal = t.segment === "replay";
    const clv = isNum(t.clv_pts) ? `${t.clv_pts > 0 ? "+" : t.clv_pts < 0 ? "-" : ""}${Math.abs(t.clv_pts).toFixed(1)}` : NA;
    const units = ticketUnits(t);
    const cells = [
      h("td", { class: "hd-num hd-nowrap", text: shortDate(t.date) || NA }),
      h("td", { text: t.game || NOT_REPORTED }),
      h("td", {}, [h("strong", { text: pickOf(t) }), h("small", { class: "hd-aux", text: marketLabel(t.market) }), liveTag(t)]),
      h("td", { class: "hd-num" }, [priceCell(t)]),
    ];
    if (graded) cells.push(h("td", { class: "hd-num", "data-hook": "ticket-clv", text: clv }));
    cells.push(h("td", {}, [resultChip(t), liveSpan(), rehearsal ? h("small", { class: "hd-aux", text: "Rehearsal" }) : null,
      graded && units ? h("small", { class: "hd-aux hd-num", "data-hook": "ticket-money", title: "Paper dollars at your unit size", text: signedMoney(t.units) }) : null]));
    if (graded) {
      cells.push(h("td", Object.assign({ class: `hd-num hd-tone--${!units ? "none" : t.units > 0 ? "up" : t.units < 0 ? "down" : "flat"}`,
        "data-hook": "ticket-units", text: units || NA }, fresh && units ? { "data-count": "1", "data-count-ms": "500" } : {})));
    }
    // a reason can run to hundreds of characters: three lines in the table, the whole text on a click
    const why = h("td", { class: "hd-td-reason", "data-hook": "bet-why", tabindex: "0", "aria-expanded": "false",
      title: "Show the whole reason" }, [h("div", { class: "hd-why", text: t.reason || NA })]);
    const flip = () => {
      const open = why.getAttribute("aria-expanded") === "true";
      why.setAttribute("aria-expanded", open ? "false" : "true");
    };
    why.addEventListener("click", flip);
    why.addEventListener("keydown", (ev) => { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); flip(); } });
    cells.push(why);
    cells.push(h("td", { class: "hd-td-stamp", "data-hook": "bet-stamp" }, [
      rehearsal ? h("span", { class: "hd-rec hd-rec--rehearsal", text: "Written after the games; never counted" }) : recordedCell(t)]));
    return h("tr", Object.assign({ class: "hd-trow", "data-status": status, "data-segment": String(t.segment || "") },
      liveAttrs(t), fresh ? { "data-flip": "1", style: `--i:${Math.min(index, 5)}` } : {}), cells);
  });
  const cards = h("ol", { class: "hd-cards", "data-hook": `${hook}-cards`, "aria-label": caption },
    tickets.map((t, index) => h("li", Object.assign({ class: "hd-cardrow" },
      index < flipCount ? { "data-flip": "1", style: `--i:${Math.min(index, 5)}` } : {}), [ticketCard(t, { flip: index < flipCount })])));
  return watch(h("div", { class: "hd-ticketview", "data-hook": `${hook}-view` }, [
    h("div", { class: "hd-tablewrap hd-tablewrap--tickets", tabindex: "0", role: "region", "aria-label": `${caption}. Scrolls sideways on a narrow screen.` }, [
      h("table", { class: "hd-table hd-table--tickets", "data-hook": hook }, [
        h("caption", { class: "hd-sr-only", text: caption }),
        h("thead", {}, [h("tr", {}, head.map((t) => h("th", { scope: "col", text: t })))]),
        h("tbody", {}, rows)])]),
    cards]));
}
