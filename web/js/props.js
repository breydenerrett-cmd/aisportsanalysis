/**
 * PLAYER PROPS (#/props, GET /props/{date}).
 *
 * WHY THIS SCREEN EXISTS
 * ----------------------
 * THE CARD can only ever show two kinds of bet -- a moneyline or a run line
 * -- so every night it showed the same shape: whichever side the market
 * already liked most. Meanwhile seventeen thousand player-prop prices sat in
 * the store and nothing in the product read one of them.
 *
 * THE ORDER, AND IT IS THE WHOLE POINT OF THE SCREEN
 * --------------------------------------------------
 * Two numbers per row, asked in this order and never the other way round:
 *
 *   OURS  -- how likely we think it is. Built from that batter's own game
 *            log before tonight. No price is read to produce it.
 *   NEEDS -- what the best price on offer requires before it is worth
 *            taking.
 *
 * Rows are ordered by OURS. They are never ordered by the gap between the
 * two, and the server does not order them that way either: picking bets by
 * that gap was measured returning -13.4% against -9.1% for taking everything,
 * so sorting by it would put the worst rows on top while looking clever.
 *
 * So this is a BOARD. It carries no pick, no star, no label saying take
 * this. A row can be very likely and poor value at the same time -- most of
 * them are -- and both numbers are shown precisely so a reader can see that
 * for themselves.
 */

import { apiGet } from "./api.js";
import { bookLabel } from "./labels.js";
import {
  el, clear, renderError, formatAmerican, formatSlateDate,
} from "./dom.js";

/** Human names for the market keys the API returns. */
const MARKET_LABELS = {
  batter_hits: "hits",
  batter_total_bases: "total bases",
  batter_runs_scored: "runs",
  batter_home_runs: "home runs",
};

function marketLabel(market) {
  return MARKET_LABELS[market] || String(market || "").replace(/_/g, " ");
}

function percent(value) {
  if (value === null || value === undefined) return null;
  return `${(Number(value) * 100).toFixed(0)}%`;
}

/**
 * "Jeff McNeil under 1.5 hits" -- the bet as a person would say it aloud,
 * not as the feed stores it.
 */
function betSentence(row) {
  const side = String(row.side || "").toLowerCase();
  return `${row.player} ${side} ${row.line} ${marketLabel(row.market)}`;
}

/**
 * The two numbers, side by side, with the comparison spelled out rather than
 * left as arithmetic for the reader.
 *
 * A row where ours is below what the price needs is the ordinary case and is
 * stated plainly. Nothing here calls that a reason to bet or a reason not
 * to; it is the fact, and the fact is what the screen is for.
 */
function numbers(row) {
  const wrap = el("div", { class: "prop-row__numbers" });

  const mine = el("div", { class: "prop-row__stat" });
  mine.appendChild(el("span", { class: "prop-row__stat-label", text: "OURS" }));
  mine.appendChild(el("span", {
    class: "prop-row__stat-value", "data-hook": "prop-probability",
    text: percent(row.probability) || "--",
  }));
  wrap.appendChild(mine);

  const needed = el("div", { class: "prop-row__stat" });
  needed.appendChild(el("span", {
    class: "prop-row__stat-label", text: "PRICE NEEDS",
  }));
  needed.appendChild(el("span", {
    class: "prop-row__stat-value prop-row__stat-value--muted",
    "data-hook": "prop-breakeven",
    text: percent(row.breakeven) || "--",
  }));
  wrap.appendChild(needed);

  return wrap;
}

/** Where the plate-appearance estimate came from, in plain words.
 *
 * It matters and it is not decoration: batting first is about 4.5 trips to
 * the plate and batting ninth about 3.5, which is a quarter more chances at
 * the same line. Before the lineup posts we are using his season average and
 * the row says so instead of pretending to know. */
function plateAppearances(row) {
  const pa = row.expected_pa;
  if (pa === null || pa === undefined) return null;
  const slot = row.batting_slot;
  const text = slot
    ? `batting ${slot}${slot === 1 ? "st" : slot === 2 ? "nd" : slot === 3 ? "rd" : "th"} · about ${Number(pa).toFixed(1)} times up`
    : `about ${Number(pa).toFixed(1)} times up (lineup not posted yet)`;
  return el("p", { class: "prop-row__pa", "data-hook": "prop-pa", text });
}

function propRow(row) {
  const card = el("li", { class: "prop-row panel chamfer", "data-hook": "prop-row" });

  card.appendChild(el("p", {
    class: "prop-row__bet", "data-hook": "prop-bet", text: betSentence(row),
  }));

  card.appendChild(numbers(row));

  const price = formatAmerican(row.price);
  if (price !== null && price !== undefined) {
    card.appendChild(el("p", {
      class: "prop-row__price", "data-hook": "prop-price",
      // The book's name, not its feed key: "+500 at williamhill_us" was on
      // the page. labels.js is the one resolver every screen uses.
      text: `${price} at ${bookLabel(row.book) || row.book || "book"}`,
    }));
  }

  const pa = plateAppearances(row);
  if (pa) card.appendChild(pa);

  // A one-sided market (home runs: no book quotes the under) has no fair
  // price. OURS and PRICE NEEDS are both real; what is missing is the
  // market's own number, and the row says so rather than leaving a gap a
  // reader would fill with a guess.
  if (row.market_probability_absent) {
    card.appendChild(el("p", {
      class: "prop-row__pa", "data-hook": "prop-market-absent",
      text: "No book quotes the under on this one, so there is no market number to "
        + "compare against — only how often we make it, and what the price needs.",
    }));
  }

  return card;
}

/**
 * The header. It says what the list is and what it is not, once, at the top,
 * because a list of numbers with no frame reads as a list of bets.
 */
function heading(payload) {
  const head = el("header", { class: "props__head" });
  head.appendChild(el("p", {
    class: "props__eyebrow", "data-hook": "props-date",
    text: formatSlateDate(payload.date) || payload.date || "",
  }));
  head.appendChild(el("h2", {
    class: "props__title", text: "What is most likely tonight",
  }));
  head.appendChild(el("p", {
    class: "props__lede", "data-hook": "props-lede",
    text: "Ordered by how likely we think each one is. The price each one "
        + "needs is shown beside it. Winning often and being worth the price "
        + "are different things, and plenty of these are the first without "
        + "the second.",
  }));
  return head;
}

/** Counts, so a short list reads as a short list and not as a broken page. */
function counts(payload) {
  const got = payload.counts || {};
  if (!got.contracts) return null;
  const parts = [`${got.contracts} priced`];
  if (got.likely !== undefined) parts.push(`${got.likely} better than a coin`);
  if (got.markets && got.markets.length) {
    parts.push(got.markets.map(marketLabel).join(" · "));
  }
  return el("p", {
    class: "props__counts", "data-hook": "props-counts",
    text: parts.join("  ·  "),
  });
}

export async function renderProps(container, date) {
  clear(container);
  const screen = el("section", { class: "props", "data-hook": "props-screen" });
  container.appendChild(screen);

  const host = el("div", { "data-hook": "props-host" });
  screen.appendChild(host);
  host.appendChild(el("p", {
    class: "props__loading", "data-hook": "props-loading",
    text: "Reading tonight's board...",
  }));

  let payload;
  try {
    const path = date ? `/props/${encodeURIComponent(date)}` : "/props";
    payload = await apiGet(path);
  } catch (err) {
    clear(host);
    renderError(host, err);
    return;
  }

  clear(host);
  host.appendChild(heading(payload));

  const rows = payload.contracts || [];
  if (!rows.length) {
    host.appendChild(el("p", {
      class: "props__empty", "data-hook": "props-empty",
      text: payload.reason || "Nothing priced for this slate yet.",
    }));
  } else {
    const list = el("ul", { class: "props__list", "data-hook": "props-list" });
    rows.forEach((row) => list.appendChild(propRow(row)));
    host.appendChild(list);

    const tally = counts(payload);
    if (tally) host.appendChild(tally);
  }

  host.appendChild(longShots(payload));
}

/**
 * Home runs, under their own heading. A home run is a 10-20% event, so it
 * never clears the "more likely than not" list above and would never be
 * seen; the owner asked for the market by name. Same order as everything
 * else -- how likely we make it -- and the heading says plainly that none
 * of these is likely. No book quotes the under, so there is no market
 * number on any of them; each row says so.
 */
function longShots(payload) {
  const rows = payload.long_shots || [];
  const wrap = el("section", { class: "props__long-shots", "data-hook": "props-long-shots" });
  if (!rows.length) return wrap;
  wrap.appendChild(el("h3", {
    class: "props__title props__title--long-shots",
    text: "Home runs — none of these is likely",
  }));
  wrap.appendChild(el("p", {
    class: "props__lede", "data-hook": "props-long-shots-lede",
    text: "How often we make each one happen, likeliest first, and what the price "
      + "needs. These are long shots by nature; a one-in-five chance is a good "
      + "night for a home run.",
  }));
  const list = el("ul", { class: "props__list", "data-hook": "props-long-shots-list" });
  rows.forEach((row) => list.appendChild(propRow(row)));
  wrap.appendChild(list);
  return wrap;
}
