/**
 * TOP OPPORTUNITIES (GET /opportunities/{date}, src/analysis/opportunities.py's
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
 */

import { apiGet } from "./api.js";
import { el, clear, renderError, renderLoading, notYetAvailable,
  formatAmerican, formatConsensusShare, formatEasternTime, formatAge, renderWordChip } from "./dom.js";
import { bookLabel } from "./labels.js";
import { renderValueMeter } from "./valuemeter.js";

export const EMPTY_LITERAL = "NO QUALIFYING BEST BETS RIGHT NOW";

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

  if (isHero) {
    main.appendChild(el("span", { class: "opp-card__eyebrow", text: "TOP PLAY" }));
  }

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
      `MARKET-IMPLIED (de-vigged, ${booksN === null ? "—" : booksN} books) ${marketPct || "—"} `
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
 * Fetches and renders the TOP OPPORTUNITIES section for `date` into a new
 * child of `container`. Returns the section element (today.js inserts it
 * at a specific position in the DOM); never throws -- a fetch failure
 * renders dom.js's own error treatment inside the section instead of
 * bubbling up and blanking the rest of the Gameday screen.
 */
export async function renderOpportunities(container, date) {
  const section = el("section", { class: "opp-section", "data-hook": "top-opportunities" });
  container.appendChild(section);
  section.appendChild(sectionHead("TOP OPPORTUNITIES", "PRICE VS. DE-VIGGED CONSENSUS"));
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
    panel.appendChild(el("span", { class: "opp-empty__eyebrow", text: "TOP OPPORTUNITIES" }));
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

  // Not armed here -- today.js's own armEntrances(host) call, made once
  // after the whole screen is composed, already covers every [data-rise]
  // element in this section (see that module's single-arm-pass pattern).
  return section;
}
