/**
 * THE PRICE BOARD (GET /opportunities/{date}, src/analysis/opportunities.py's
 * build_opportunities) -- the day's best-priced sides, ranked by
 * value_points, rendered as a section wired into Gameday (#/today) between
 * the hero and the Featured Bet carousel head. See web/js/today.js's call
 * site.
 *
 * WHAT THIS IS -- price versus de-vigged consensus (line-shopping value),
 * never a prediction, never a model's picks, never expected value. Every
 * `price_verdict.independent_model` is the literal "NO INDEPENDENT MODEL
 * YET" string and is rendered verbatim, never paraphrased into a claim of
 * model confidence.
 *
 * NEVER INVENTS A CARD -- `qualifying` (server-capped at 5, words in
 * STRONG VALUE/VALUE/LEAN) is rendered as cards; when it is empty, the
 * exact literal 'NO QUALIFYING BEST BETS RIGHT NOW' renders in an amber
 * panel alongside the payload's own `basis` sentence -- never a composed
 * substitute. Every row from `rows` (qualifying or not, up to and
 * including FAIR PRICE/PASS/OVERPRICED/etc.) is ALWAYS also shown in a
 * full ranked table beneath the cards, and every `unpriced` game is listed
 * with its own reason string, verbatim -- so a reader can see the whole
 * slate's pricing picture, not just the handful that qualified.
 *
 * NOT JUST THE MONEYLINE -- the backend now prices every market, not only
 * h2h (`derivative_rows`: first-five lines, team/alternate totals,
 * alternate spreads, strikeout props). `qualifying` and `rows` already fold
 * these in for ranking/TOP PLAY purposes; this module additionally renders
 * the full derivative board in two pieces so a market that was CHECKED and
 * came up short never reads as ignored: "EVERY OTHER MARKET ON THE BOARD"
 * (the `derivative_priced` contracts that cleared the six-book floor, same
 * word-chip/value-points/tier treatment as everywhere else) and a THIN
 * BOARD summary (`derivative_thin` contracts that did not, grouped by
 * market with a per-market count and the API's own reason sentence stated
 * once, never a verdict). A thin contract never gets a word, a value, or a
 * meter -- only its price, its book count, and that reason.
 */

import { apiGet } from "./api.js";
import { el, clear, renderError, renderLoading, notYetAvailable,
  formatAmerican, formatConsensusShare, formatEasternTime, formatAge, renderWordChip } from "./dom.js";
import { bookLabel } from "./labels.js";
import { renderValueMeter } from "./valuemeter.js";

// Mirrors src/analysis/opportunities.py's EMPTY_REASON, which the payload
// normally carries; this is only the fallback when it does not. "BEST BETS"
// was the old wording and was pick language for a price board -- see that
// module's comment for why it changed.
export const EMPTY_LITERAL = "NO BETTER-THAN-CONSENSUS PRICES RIGHT NOW";

function sectionHead(label, meta) {
  const head = el("div", { class: "sechead" });
  head.appendChild(el("span", { class: "sechead__label", text: label }));
  head.appendChild(el("span", { class: "sechead__hair" }));
  if (meta) head.appendChild(el("span", { class: "sechead__meta", text: meta }));
  return head;
}

function betCheckHref(row) {
  const params = new URLSearchParams();
  if (row.first_pitch_utc) {
    // /betcheck's date field expects the calendar date the bet ticket
    // carries -- reuse the game's own first-pitch date, not the slate's
    // possibly-different UTC label.
    params.set("date", String(row.first_pitch_utc).slice(0, 10));
  }
  params.set("away", row.away_team || "");
  params.set("home", row.home_team || "");
  if (row.side) params.set("side", row.side);
  if (typeof row.best_price === "number") params.set("price", String(row.best_price));
  return `#/betcheck?${params.toString()}`;
}

function gameHref(date, row) {
  return `#/game/${encodeURIComponent(date)}/${encodeURIComponent(row.away_team || "")}`
    + `/${encodeURIComponent(row.home_team || "")}`;
}

function capturedLine(row) {
  const age = formatAge(row.age_seconds);
  return age ? `captured ${age.toLowerCase()}` : "capture age not available";
}

function reasonsRisksList(reasons, risks) {
  const wrap = el("div", { class: "opp-card__lists" });
  if (reasons && reasons.length) {
    const list = el("ul", { class: "opp-card__reasons" });
    for (const r of reasons) list.appendChild(el("li", { text: r }));
    wrap.appendChild(list);
  }
  if (risks && risks.length) {
    const list = el("ul", { class: "opp-card__risks" });
    for (const r of risks) list.appendChild(el("li", { text: r }));
    wrap.appendChild(list);
  }
  return wrap;
}

function engineInterest(engine) {
  if (!engine || !Array.isArray(engine.forward_test_plays) || engine.forward_test_plays.length === 0) {
    return null;
  }
  const n = engine.forward_test_plays.length;
  const wrap = el("div", { class: "opp-card__engine" });
  wrap.appendChild(el("p", { class: "opp-card__engine-line",
    text: `Forward-test system interest: ${n} play${n === 1 ? "" : "s"} · UNPROVEN` }));
  const first = engine.forward_test_plays[0];
  const thesis = first && first.thesis;
  if (thesis) {
    const details = el("details", { class: "opp-card__thesis" });
    details.appendChild(el("summary", { text: "First forward-test thesis" }));
    details.appendChild(el("p", { class: "opp-card__thesis-body", text: String(thesis) }));
    wrap.appendChild(details);
  }
  return wrap;
}

function opportunityCard(date, row, isHero) {
  const verdict = row.price_verdict || {};
  const card = el("article", { class: `opp-card panel chamfer${isHero ? " opp-card--hero" : ""}`,
    "data-hook": "opportunity-card", "data-rise": "" });

  // The hero (top-ranked) card gets a two-column layout on desktop --
  // everything but the value meter sits in `main`, the meter sits in
  // `side` (see screens.css's .opp-card--hero flex rule). A non-hero card
  // still gets both wrapper elements so the two markup shapes never
  // diverge -- CSS alone decides whether they lay out as one column or two.
  const main = el("div", { class: "opp-card__main" });
  card.appendChild(main);

  // NO "TOP PLAY" EYEBROW. Removed 2026-09-10.
  //
  // The top-ranked card used to carry the words TOP PLAY. That string was
  // invented here -- it appears nowhere in the backend, which calls these
  // rows `qualifying` and ranks them by `value_points`, defined in
  // src/analysis/priceverdict.py as (p_fair - p_price) * 100: how much
  // cheaper this book is than the de-vigged consensus at one capture
  // instant. src/analysis/opportunities.py says it outright -- "Not a
  // ranking by expected value, not a model's picks, not a prediction of
  // who wins." It is execution quality. It says nothing about whether the
  // bet is good.
  //
  // On 2026-09-09 a reader took the biggest price gap on the board as a
  // system recommendation and told Brey the site had called a great bet.
  // It had not. Two words in a hero eyebrow outweighed every careful
  // disclaimer on the card beneath them, including the card's own
  // "NO INDEPENDENT MODEL YET" line, because a label is read and fine
  // print is not.
  //
  // docs/PRODUCT_DOCTRINE.md's amendment 1 puts the ranked slip -- ranked
  // on case strength -- in the position this was occupying. The price
  // board stays, because a better number is genuinely worth having; it
  // just stops calling itself a pick.
  //
  // The hero KEEPS its two-column layout (screens.css .opp-card--hero):
  // largest price gap first is a fine way to order a price board.
  void isHero;

  const head = el("div", { class: "opp-card__head" });
  head.appendChild(el("a", { class: "opp-card__matchup", href: gameHref(date, row),
    text: `${row.away_team} @ ${row.home_team}` }));
  const pitch = formatEasternTime(row.first_pitch_utc);
  if (pitch) head.appendChild(el("span", { class: "opp-card__pitch", text: pitch }));
  main.appendChild(head);

  const wager = el("div", { class: "opp-card__wager" });
  wager.appendChild(el("span", { class: "opp-card__wager-text", text: row.wager_text || "" }));
  const priceText = formatAmerican(row.best_price);
  wager.appendChild(el("span", { class: "opp-card__price" },
    [priceText ? document.createTextNode(`at ${priceText}`) : document.createTextNode("")]));
  if (row.best_book) wager.appendChild(el("span", { class: "opp-card__book", text: bookLabel(row.best_book) }));
  main.appendChild(wager);

  const chipRow = el("div", { class: "opp-card__chips" });
  chipRow.appendChild(renderWordChip(verdict.word));
  if (typeof row.value_points === "number") {
    chipRow.appendChild(el("span", { class: "opp-card__vp", text: `${row.value_points >= 0 ? "+" : ""}${row.value_points.toFixed(2)} pts` }));
  }
  if (verdict.evidence_tier) {
    chipRow.appendChild(el("span", { class: "opp-card__tier", text: `EVIDENCE ${verdict.evidence_tier}` }));
  }
  main.appendChild(chipRow);

  const booksN = typeof row.books === "number" ? row.books : null;
  const marketPct = formatConsensusShare(row.market_implied_probability);
  const pricePct = formatConsensusShare(row.stated_implied_probability);
  main.appendChild(el("p", { class: "opp-card__figline" },
    [document.createTextNode(
      `FAIR PRICE (${booksN === null ? "—" : booksN} books) ${marketPct || "—"} `
      + `· your price implies ${pricePct || "—"}`)]));
  main.appendChild(el("p", { class: "opp-card__model", text: `INDEPENDENT MODEL: ${row.independent_model || "NO INDEPENDENT MODEL YET"}` }));

  main.appendChild(reasonsRisksList(row.reasons, row.risks));

  const engineNode = engineInterest(row.engine);
  if (engineNode) main.appendChild(engineNode);

  main.appendChild(el("p", { class: "opp-card__captured", text: capturedLine(row) }));

  const actions = el("div", { class: "opp-card__actions" });
  actions.appendChild(el("a", { class: "btn btn--ghost chamfer chamfer--btn",
    href: gameHref(date, row), text: "OPEN THIS GAME" }));
  actions.appendChild(el("a", { class: "btn btn--cyan chamfer chamfer--btn on-live",
    href: betCheckHref(row), "data-hook": "opportunity-check-price", text: "CHECK THIS PRICE" }));
  main.appendChild(actions);

  const side = el("div", { class: "opp-card__side" });
  side.appendChild(renderValueMeter({
    marketImplied: row.market_implied_probability,
    priceImplied: row.stated_implied_probability,
    valuePoints: row.value_points,
    word: null,
  }));
  card.appendChild(side);

  return card;
}

function rankedTable(date, rows) {
  const wrap = el("div", { class: "opp-ranked" });
  wrap.appendChild(el("h3", { class: "opp-ranked__title", text: `EVERY PRICED SIDE · ${rows.length} ROW${rows.length === 1 ? "" : "S"}` }));
  const tableWrap = el("div", { class: "ov2-table-wrap" });
  const table = el("table", { class: "ov2-table", "data-hook": "opportunities-ranked-table" });
  const thead = el("thead");
  const hr = el("tr");
  for (const label of ["MATCHUP", "SIDE", "BEST PRICE / BOOK", "BOOKS", "MARKET-IMPLIED", "VALUE PTS", "WORD", "TIER"]) {
    hr.appendChild(el("th", { scope: "col", text: label }));
  }
  thead.appendChild(hr);
  table.appendChild(thead);
  const tbody = el("tbody");
  for (const row of rows) {
    const verdict = row.price_verdict || {};
    const tr = el("tr");
    tr.appendChild(el("td", {}, [el("a", { href: gameHref(date, row), text: `${row.away_team} @ ${row.home_team}` })]));
    tr.appendChild(el("td", { text: row.side ? row.side.toUpperCase() : "—" }));
    const priceText = formatAmerican(row.best_price);
    tr.appendChild(el("td", { text: priceText ? `${priceText} · ${bookLabel(row.best_book) || "—"}` : "—" }));
    tr.appendChild(el("td", { text: typeof row.books === "number" ? String(row.books) : "—" }));
    tr.appendChild(el("td", { text: formatConsensusShare(row.market_implied_probability) || "—" }));
    tr.appendChild(el("td", { text: typeof row.value_points === "number" ? row.value_points.toFixed(2) : "—" }));
    tr.appendChild(el("td", {}, [renderWordChip(verdict.word)]));
    tr.appendChild(el("td", { text: verdict.evidence_tier || "—" }));
    tbody.appendChild(tr);
  }
  table.appendChild(tbody);
  tableWrap.appendChild(table);
  wrap.appendChild(tableWrap);
  return wrap;
}

/**
 * EVERY OTHER MARKET ON THE BOARD -- the priced half of `derivative_rows`
 * (src/analysis/opportunities.py prices every non-moneyline contract now,
 * not just h2h): first-five lines, team/alternate totals, alternate
 * spreads and strikeout props, each carrying its own price_verdict exactly
 * like a moneyline row does. Ranked by value_points across ALL markets
 * together (the day's best-priced derivative can be any of them) with a
 * MARKET badge per row so the different bet shapes stay distinguishable at
 * a glance -- never grouped into separate tables, which would hide that
 * cross-market ranking.
 */
function derivativeMarketBadge(row) {
  return el("span", { class: "opp-deriv__market", text: row.market_noun || row.market || "—" });
}

function derivativeTable(date, pricedRows) {
  const sorted = [...pricedRows].sort((a, b) => {
    const av = typeof a.value_points === "number" ? a.value_points : -Infinity;
    const bv = typeof b.value_points === "number" ? b.value_points : -Infinity;
    return bv - av;
  });
  const wrap = el("div", { class: "opp-deriv" });
  const tableWrap = el("div", { class: "ov2-table-wrap" });
  const table = el("table", { class: "ov2-table opp-deriv__table", "data-hook": "derivative-priced-table" });
  const thead = el("thead");
  const hr = el("tr");
  for (const label of ["MATCHUP", "MARKET", "WAGER", "BEST PRICE / BOOK", "BOOKS", "MARKET-IMPLIED", "VALUE PTS", "WORD", "TIER"]) {
    hr.appendChild(el("th", { scope: "col", text: label }));
  }
  thead.appendChild(hr);
  table.appendChild(thead);
  const tbody = el("tbody");
  for (const row of sorted) {
    const verdict = row.price_verdict || {};
    const tr = el("tr");
    tr.appendChild(el("td", {}, [el("a", { href: gameHref(date, row), text: `${row.away_team} @ ${row.home_team}` })]));
    tr.appendChild(el("td", {}, [derivativeMarketBadge(row)]));
    tr.appendChild(el("td", { class: "opp-deriv__wager", text: row.wager_text || "—" }));
    const priceText = formatAmerican(row.best_price);
    tr.appendChild(el("td", { text: priceText ? `${priceText} · ${bookLabel(row.best_book) || "—"}` : "—" }));
    tr.appendChild(el("td", { text: typeof row.books === "number" ? String(row.books) : "—" }));
    tr.appendChild(el("td", { text: formatConsensusShare(row.market_implied_probability) || "—" }));
    tr.appendChild(el("td", { text: typeof row.value_points === "number" ? row.value_points.toFixed(2) : "—" }));
    tr.appendChild(el("td", {}, [renderWordChip(verdict.word)]));
    tr.appendChild(el("td", { text: verdict.evidence_tier || "—" }));
    tbody.appendChild(tr);
  }
  table.appendChild(tbody);
  tableWrap.appendChild(table);
  wrap.appendChild(tableWrap);
  return wrap;
}

/**
 * The generic half of `thin_or_unavailable_reason` (src/analysis/
 * opportunities.py), lifted from whichever thin row has it first --
 * identical technique to dayrecap.js's collectLegendFacts, and for the
 * same reason: the string is "<N> book(s) quoted this line at one
 * instant; <generic policy sentence>" on every thin row, so stating the
 * generic half once here (rather than repeating the full sentence on all
 * 1,000+ rows) keeps the page from drowning in a duplicated sentence while
 * never inventing new wording -- the tail is the API's own text, verbatim.
 */
function thinBoardReason(rows) {
  for (const row of rows) {
    if (row.thin_or_unavailable_reason) {
      const reason = String(row.thin_or_unavailable_reason);
      const sepIndex = reason.indexOf(";");
      const tail = sepIndex >= 0 ? reason.slice(sepIndex + 1).trim() : reason;
      return tail ? `${tail.charAt(0).toUpperCase()}${tail.slice(1)}.` : reason;
    }
  }
  return null;
}

/**
 * THIN BOARD -- every derivative market CHECKED this slate, whether or not
 * it cleared the six-book floor, so a reader sees "0 of 12 first-five
 * totals cleared" rather than silence that reads as the market never being
 * looked at. Never a verdict for a thin contract: this only ever prints a
 * count and the API's own reason sentence, never a word/value/meter.
 */
function derivativeThinSummary(allRows) {
  if (!allRows || allRows.length === 0) return null;
  const byMarket = new Map();
  for (const row of allRows) {
    const key = row.market || "unknown";
    if (!byMarket.has(key)) {
      byMarket.set(key, { noun: row.market_noun || key, total: 0, priced: 0 });
    }
    const bucket = byMarket.get(key);
    bucket.total += 1;
    if (row.price_verdict) bucket.priced += 1;
  }
  const thinTotal = allRows.filter((r) => !r.price_verdict).length;
  if (thinTotal === 0) return null;

  const buckets = [...byMarket.values()].sort((a, b) => b.total - a.total);

  const wrap = el("div", { class: "opp-thin panel chamfer", "data-hook": "opportunities-derivative-thin" });
  const head = el("div", { class: "opp-thin__head" });
  head.appendChild(el("span", { class: "opp-thin__eyebrow", text: "THIN BOARD" }));
  head.appendChild(el("span", { class: "opp-thin__count",
    text: `${thinTotal} CONTRACT${thinTotal === 1 ? "" : "S"} CHECKED, NOT PRICED` }));
  wrap.appendChild(head);

  const reason = thinBoardReason(allRows);
  if (reason) wrap.appendChild(el("p", { class: "opp-thin__reason", text: reason }));

  const list = el("ul", { class: "opp-thin__list", "data-hook": "opportunities-derivative-thin-list" });
  for (const bucket of buckets) {
    const li = el("li", { class: "opp-thin__row" });
    li.appendChild(el("span", { class: "opp-thin__ratio", text: `${bucket.priced} OF ${bucket.total}` }));
    li.appendChild(el("span", { class: "opp-thin__market",
      text: `${bucket.noun} contract${bucket.total === 1 ? "" : "s"} cleared the six-book floor` }));
    list.appendChild(li);
  }
  wrap.appendChild(list);
  return wrap;
}

function unpricedList(unpriced) {
  if (!unpriced || unpriced.length === 0) return null;
  const wrap = el("div", { class: "opp-unpriced" });
  wrap.appendChild(el("h3", { class: "opp-unpriced__title",
    text: `UNPRICED · ${unpriced.length} GAME${unpriced.length === 1 ? "" : "S"}` }));
  const list = el("ul", { class: "opp-unpriced__list", "data-hook": "opportunities-unpriced-list" });
  for (const item of unpriced) {
    const li = el("li", { class: "opp-unpriced__row" });
    li.appendChild(el("span", { class: "opp-unpriced__matchup",
      text: `${item.away_team} @ ${item.home_team}` }));
    li.appendChild(el("span", { class: "opp-unpriced__reason", text: item.reason || "no reason given" }));
    list.appendChild(li);
  }
  wrap.appendChild(list);
  return wrap;
}

/**
 * Fetches and renders THE PRICE BOARD section for `date` into a new
 * child of `container`. Returns the section element (today.js inserts it
 * at a specific position in the DOM); never throws -- a fetch failure
 * renders dom.js's own error treatment inside the section instead of
 * bubbling up and blanking the rest of the Gameday screen.
 */
export async function renderOpportunities(container, date) {
  const section = el("section", { class: "opp-section", "data-hook": "top-opportunities" });
  container.appendChild(section);
  section.appendChild(sectionHead("THE PRICE BOARD",
                                  "BEST AVAILABLE NUMBER VS. THE FAIR PRICE"));
  const body = el("div", { class: "opp-body" });
  body.appendChild(renderLoading("LOADING TONIGHT'S OPPORTUNITIES"));
  section.appendChild(body);

  let payload;
  try {
    payload = await apiGet(`/opportunities/${encodeURIComponent(date)}`);
  } catch (err) {
    clear(body);
    renderError(body, err);
    return section;
  }
  clear(body);

  body.appendChild(el("p", { class: "opp-label", text: payload.label || "" }));

  const qualifying = payload.qualifying || [];
  if (qualifying.length === 0) {
    const panel = el("div", { class: "opp-empty panel chamfer", "data-hook": "opportunities-empty" });
    panel.appendChild(el("span", { class: "opp-empty__eyebrow", text: "THE PRICE BOARD" }));
    panel.appendChild(el("p", { class: "opp-empty__headline", text: payload.empty_reason || EMPTY_LITERAL }));
    panel.appendChild(el("p", { class: "opp-empty__basis", text: payload.basis || "" }));
    body.appendChild(panel);
  } else {
    const grid = el("div", { class: "opp-grid" });
    qualifying.forEach((row, i) => grid.appendChild(opportunityCard(date, row, i === 0)));
    body.appendChild(grid);
  }

  const rows = payload.rows || [];
  if (rows.length) body.appendChild(rankedTable(date, rows));
  else body.appendChild(notYetAvailable("No priced (game, side) rows on this slate.", "NO PRICED ROWS"));

  const unpricedNode = unpricedList(payload.unpriced);
  if (unpricedNode) body.appendChild(unpricedNode);

  // EVERY OTHER MARKET ON THE BOARD -- every non-moneyline contract the
  // backend priced this slate (first-five lines, team/alternate totals,
  // alternate spreads, strikeout props), ranked by value_points alongside
  // each other so the day's best-priced derivative surfaces regardless of
  // which market it's in. `qualifying` above already folds these in when
  // one is good enough to rank as a TOP PLAY -- this section is the full
  // priced board underneath that, the same relationship `rows`/rankedTable
  // has to the moneyline TOP PLAY.
  const derivativeRows = payload.derivative_rows || [];
  const pricedDerivative = derivativeRows.filter((row) => row.price_verdict);
  if (derivativeRows.length) {
    body.appendChild(sectionHead("EVERY OTHER MARKET ON THE BOARD",
      `${pricedDerivative.length} PRICED CONTRACT${pricedDerivative.length === 1 ? "" : "S"}`));
    if (pricedDerivative.length) {
      body.appendChild(derivativeTable(date, pricedDerivative));
    } else {
      body.appendChild(notYetAvailable(
        "No non-moneyline contract cleared the six-book consensus floor on this slate.",
        "NO PRICED DERIVATIVES"));
    }

    const thinNode = derivativeThinSummary(derivativeRows);
    if (thinNode) body.appendChild(thinNode);
  }

  // Not armed here -- today.js's own armEntrances(host) call, made once
  // after the whole screen is composed, already covers every [data-rise]
  // element in this section (see that module's single-arm-pass pattern).
  return section;
}
