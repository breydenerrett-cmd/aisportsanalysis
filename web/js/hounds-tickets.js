/**
 * Tickets as rows. A ticket is one bet a model recorded: the game, the pick, the market, the price, how many
 * books were quoting it, when it went on the record against the first pitch, and where it stands (PENDING,
 * WON, LOST, PUSH, VOID) with the units it moved. The feed on the leaderboard page, a model's drawer, the
 * model page's two tables and the landing page's latest five all build their rows here, so a number reads the
 * same wherever it appears. Only what the server sent is shown; a missing field is "n/a", never a guess.
 */

import { h, isNum, signed, fmtPrice, shortDate, houndHref, NOT_REPORTED } from "./hounds-core.js";
import {
  ticketStatus, RESULT_WORDS, recordedText, ticketPrice, pickOf, marketLabel, booksText, NA,
} from "./hounds-board.js";

/** The status chip: the word is the signal, the colour only agrees with it. */
export function resultChip(result) {
  const key = ticketStatus(result);
  return h("span", { class: `hd-res hd-res--${key}`, "data-result": key, "data-hook": "ticket-status",
    text: RESULT_WORDS[key] });
}

/** "+0.91u" / "-1.00u" for a graded ticket, "" while it is open. */
export function ticketUnits(ticket) {
  return ticketStatus(ticket && ticket.result) !== "pending" && isNum(ticket && ticket.units)
    ? `${signed(ticket.units, 2)}u` : "";
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
export function ticketItem(ticket, { showModel = true, name = "" } = {}) {
  const t = ticket || {};
  const status = ticketStatus(t.result);
  const model = name || t.hound_name || t.name || "";
  const units = ticketUnits(t);
  return h("li", { class: "hd-ticket", "data-status": status, "data-hound": t.hound_id === undefined ? "" : String(t.hound_id),
    "data-hook": "ticket" }, [
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
      ]),
    ]),
    h("div", { class: "hd-ticket__price" }, [priceCell(t)]),
    h("div", { class: "hd-ticket__rec" }, [recordedCell(t)]),
    h("div", { class: "hd-ticket__res" }, [
      resultChip(t.result),
      units ? h("span", { class: `hd-num hd-units-text hd-units-text--${t.units > 0 ? "up" : t.units < 0 ? "down" : "flat"}`,
        text: units }) : null,
    ]),
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
  return ul;
}

/**
 * A model's tickets as a real table: date, game, pick, price, (graded only: CLV points), status,
 * (graded only: units), the rule's reason line and when it went on the record against the start. The wide
 * table scrolls inside its own box on a phone. A rehearsal row (a rule applied to old boards, written after
 * the games) says so instead of showing a recorded-before time, and is never counted anywhere.
 */
export function ticketTable(tickets, { graded = false, hook = "tickets-table", caption = "Tickets" } = {}) {
  const head = ["Date", "Game", "Pick", "Price"].concat(graded ? ["CLV pts"] : [])
    .concat(["Status"]).concat(graded ? ["Units"] : []).concat(["Rule reason", "Recorded"]);
  const rows = tickets.map((t) => {
    const status = ticketStatus(t.result);
    const rehearsal = t.segment === "replay";
    const clv = isNum(t.clv_pts) ? `${t.clv_pts > 0 ? "+" : t.clv_pts < 0 ? "-" : ""}${Math.abs(t.clv_pts).toFixed(1)}` : NA;
    const units = ticketUnits(t);
    const cells = [
      h("td", { class: "hd-num hd-nowrap", text: shortDate(t.date) || NA }),
      h("td", { text: t.game || NOT_REPORTED }),
      h("td", {}, [h("strong", { text: pickOf(t) }), h("small", { class: "hd-aux", text: marketLabel(t.market) })]),
      h("td", { class: "hd-num" }, [priceCell(t)]),
    ];
    if (graded) cells.push(h("td", { class: "hd-num", "data-hook": "ticket-clv", text: clv }));
    cells.push(h("td", {}, [resultChip(t.result), rehearsal ? h("small", { class: "hd-aux", text: "Rehearsal" }) : null]));
    if (graded) {
      cells.push(h("td", { class: `hd-num hd-tone--${!units ? "none" : t.units > 0 ? "up" : t.units < 0 ? "down" : "flat"}`,
        "data-hook": "ticket-units", text: units || NA }));
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
    return h("tr", { class: "hd-trow", "data-status": status, "data-segment": String(t.segment || "") }, cells);
  });
  return h("div", { class: "hd-tablewrap", tabindex: "0", role: "region", "aria-label": `${caption}. Scrolls sideways on a phone.` }, [
    h("table", { class: "hd-table hd-table--tickets", "data-hook": hook }, [
      h("caption", { class: "hd-sr-only", text: caption }),
      h("thead", {}, [h("tr", {}, head.map((t) => h("th", { scope: "col", text: t })))]),
      h("tbody", {}, rows)])]);
}
