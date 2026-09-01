/**
 * BET CHECK (#/betcheck) -- POST /betcheck (api/betcheck.py), composed
 * from the frozen "Bet Check desktop" and "Bet Check mobile" artboards:
 * a seam hero carrying the input panel and the CHECK IT action, then the
 * ten-block fixed skeleton beneath it.
 *
 * FIXED SKELETON, MANDATED ORDER (docs/PRODUCT_DESIGN_HANDOFF.md, "A
 * fixed skeleton is a trust mechanism": an omission becomes visible only
 * if the shape never changes). The canvas numbers ten blocks; five of
 * them carry the data-hook markers tests/test_web_structure.py pins, and
 * they appear in this file's source in exactly that order:
 *
 *   01 YOUR BET            (data-hook="bet-check-your-bet")
 *   02 THE CASE             (data-hook="bet-check-support")
 *   03 COUNTERARGUMENT      (data-hook="bet-check-counterargument")
 *   04 PRICE CHECK          (data-hook="bet-check-prices")
 *   05 THE STRONGEST PART
 *   06 THE WEAKEST PART
 *   07 WHAT CHANGED
 *   08 HISTORICAL SUPPORT
 *   09 EVIDENCE STATUS
 *   10 BOTTOM LINE          (data-hook="bet-check-bottom-line")
 *
 * Do not reorder the `renderResult` appends or the function definitions
 * below without updating that test.
 *
 * SUPPORT AND COUNTERARGUMENT GET IDENTICAL TREATMENT -- "counterargument
 * equal standing" means structural parity, same panel, same type scale,
 * same weight; only the reserved edge color differs.
 * `counterargument_lines` is documented "never empty" (it renders its own
 * no-counterargument line) so it is printed verbatim with no
 * client-composed fallback text.
 *
 * TWO ENDPOINTS, ONE SCREEN
 * -------------------------------------------------------------------
 * A signed-in reader posts to /betcheck. An anonymous visitor posts to
 * /betcheck/free, which is open and capped at three introductory checks
 * FOR LIFE (not per day) -- so a signed-out visitor meets the product,
 * not a sign-in wall. The two responses are field-identical apart from
 * the extra `free_check` block, so the ten-block skeleton below renders
 * from either one unchanged. The free identity is a header
 * (X-Free-Check-Token), never an Authorization bearer.
 *
 * WHY THE INPUT IS A COMPOSED PANEL, NOT ONE FREE-TEXT FIELD
 * -------------------------------------------------------------------
 * The canvas shows a single "Yankees ML -125" field. The API takes a
 * structured bet and states plainly that "team-name resolution is the
 * client's job" -- there is no parser behind that field yet. Rather than
 * fake one (and mis-resolve someone's bet), the seam band carries the
 * real fields at display scale inside the same geometry. This is the one
 * deliberate composition deviation on this screen.
 */

import { apiFetch, apiPost, getToken, getFreeCheckToken, setFreeCheckToken } from "./api.js";
import { el, clear, renderUnknown, renderError, renderLoading, notYetAvailable,
  formatAmerican, formatAge, formatBook, formatConsensusShare,
  formatEasternTime, formatEasternClock } from "./dom.js";
import { setShellStatusFromStaleness } from "./shell.js";
import { armEntrances } from "./motion.js";

function todayIso() {
  return new Date().toISOString().slice(0, 10);
}

/** Cents between two American prices on the same side -- the unit the
 * API's own bottom line uses ("8 cents worse than the best available
 * -132"). Plain arithmetic on two supplied integers; countable by the
 * reader at the books. */
function centsBetween(a, b) {
  if (typeof a !== "number" || typeof b !== "number") return null;
  return Math.abs(a - b);
}

/** True when `candidate` pays strictly better than `reference` on the
 * same side. Higher payout, not "more likely" -- this client never makes
 * a probability claim. */
function paysBetter(candidate, reference) {
  if (typeof candidate !== "number" || typeof reference !== "number") return null;
  const payout = (p) => (p > 0 ? p / 100 : 100 / -p);
  return payout(candidate) > payout(reference);
}

/* ---------------------------------------------------------------------
 * Block chrome
 * ------------------------------------------------------------------- */

function block(no, title, opts = {}) {
  const section = el("section", Object.assign({
    class: `bc-block chamfer${opts.modifier ? ` bc-block--${opts.modifier}` : ""}`,
  }, opts.attrs || {}));
  const head = el("div", { class: "bc-block__head" });
  head.appendChild(el("span", { class: "bc-block__no", text: no }));
  head.appendChild(el("h2", { class: `bc-block__title${opts.tone ? ` bc-block__title--${opts.tone}` : ""}`,
    text: title }));
  head.appendChild(el("span", { class: "bc-block__hair" }));
  if (opts.meta) head.appendChild(el("span", { class: "bc-block__meta", text: opts.meta }));
  section.appendChild(head);
  return section;
}

function line(text, kind, sampleNote) {
  const row = el("li", { class: "bc-line" });
  row.appendChild(el("span", {
    class: `bc-line__mark chamfer chamfer--marker bc-line__mark--${kind}`,
    "aria-hidden": "true", text: kind === "yes" ? "✓" : "✕",
  }));
  row.appendChild(el("span", { class: "bc-line__body", text }));
  // Every rate ships with its sample size, adjacent to it. A bare rate
  // is a bug (handoff section 11).
  if (sampleNote) row.appendChild(el("span", { class: "bc-line__n", text: sampleNote }));
  return row;
}

/** A Claim object out of `thesis_support` -- rendered as its own sentence
 * plus whatever sample the API attached, never summarised. */
function claimText(claim) {
  if (typeof claim === "string") return { text: claim, sample: null };
  if (!claim || typeof claim !== "object") return { text: String(claim), sample: null };
  const text = claim.text || claim.claim || claim.headline || claim.summary || null;
  const n = claim.sample_n !== undefined && claim.sample_n !== null ? `n = ${claim.sample_n}` : null;
  const sample = claim.sample || n;
  return { text, sample, raw: claim };
}

/* ---------------------------------------------------------------------
 * The ten blocks, in order
 * ------------------------------------------------------------------- */

function renderYourBet(result, submitted) {
  const section = block("01", "YOUR BET", { attrs: { "data-hook": "bet-check-your-bet" },
    tone: "mute" });
  const query = result.query || {};
  const team = query.team || submitted.away;
  const market = (query.market || "h2h").toUpperCase() === "H2H" ? "ML" : String(query.market).toUpperCase();
  section.appendChild(el("p", { class: "bc-yourbet__figure", "data-hook": "query-raw",
    text: `${team} ${market}` }));

  const row = el("div", { class: "bc-yourbet__row" });
  const yours = typeof query.price === "number" ? query.price : submitted.american_price;
  row.appendChild(el("span", { class: "bc-yourbet__price", text: formatAmerican(yours) || "" }));
  const best = result.best_available_price;
  const better = best ? paysBetter(best.american_price, yours) : null;
  if (better === true) {
    row.appendChild(el("span", { class: "badge chamfer chamfer--chip badge--sample",
      "data-hook": "below-market", text: "BELOW BEST AVAILABLE" }));
  }
  section.appendChild(row);

  const game = result.game || null;
  const bits = [];
  if (game) {
    bits.push(`${game.away} @ ${game.home}`);
    const start = formatEasternTime(game.start_time_utc);
    if (start) bits.push(start);
    if (game.venue) bits.push(game.venue.toUpperCase());
  }
  if (result.market_consensus && typeof result.market_consensus.books === "number") {
    bits.push(`${result.market_consensus.books} BOOKS SCANNED`);
  }
  if (bits.length) {
    section.appendChild(el("p", { class: "bc-yourbet__meta", "data-hook": "bet-check-game",
      text: bits.join("  ·  ") }));
  }
  // `parsed` is part of the contract and stays visible rather than being
  // silently assumed true.
  section.appendChild(el("p", { class: "bc-yourbet__meta", "data-hook": "query-parsed",
    text: query.parsed === false ? "WE COULD NOT PARSE THAT BET" : "PARSED" }));
  return section;
}

function renderSupport(result) {
  const support = result.thesis_support || [];
  const section = block("02", "THE CASE", {
    attrs: { "data-hook": "bet-check-support" }, tone: "live", modifier: "case",
    meta: `${support.length} POINT${support.length === 1 ? "" : "S"}`,
  });
  const list = el("ul", { class: "bc-lines" });
  if (support.length === 0) {
    list.appendChild(line("The evidence gathered for this game does not make a case for this bet.", "no"));
  }
  for (const claim of support) {
    const { text, sample, raw } = claimText(claim);
    if (text) list.appendChild(line(text, "yes", sample));
    else list.appendChild(el("li", { class: "bc-line" }, [renderUnknown(raw)]));
  }
  section.appendChild(list);
  return section;
}

function renderCounterargument(result) {
  // counterargument_lines is contractually never empty -- rendered as-is,
  // never replaced with client-composed filler.
  const lines = result.counterargument_lines || [];
  const section = block("03", "COUNTERARGUMENT", {
    attrs: { "data-hook": "bet-check-counterargument" }, tone: "risk", modifier: "counter",
    meta: `${lines.length} LINE${lines.length === 1 ? "" : "S"}`,
  });
  const list = el("ul", { class: "bc-lines", "data-hook": "counterargument-lines" });
  for (const text of lines) list.appendChild(line(text, "no"));
  section.appendChild(list);
  return section;
}

function renderPrices(result) {
  const section = block("04", "PRICE CHECK", { attrs: { "data-hook": "bet-check-prices" },
    tone: "risk" });
  const best = result.best_available_price;
  const consensus = result.market_consensus;
  const yours = result.query && typeof result.query.price === "number" ? result.query.price : null;

  if (!best) {
    section.appendChild(el("p", { class: "gv-panel__body",
      text: "No book has posted a price on this game, so there is nothing to compare yours against." }));
    return section;
  }

  const panel = el("div", { class: "bc-price chamfer" });
  panel.appendChild(el("span", { class: "tex-scanline" }));
  const row = el("div", { class: "bc-price__row" });
  row.appendChild(el("span", { class: "bc-price__figure", "data-hook": "best-available-price",
    "data-beat": "", text: formatAmerican(best.american_price) }));

  if (consensus && typeof consensus.implied_probability === "number") {
    const cell = el("div", { class: "bc-price__cell", "data-hook": "market-consensus" });
    cell.appendChild(el("div", { class: "bc-price__cell-label",
      text: `MARKET-IMPLIED CONSENSUS · ${consensus.books} BOOKS` }));
    cell.appendChild(el("div", { class: "bc-price__cell-value",
      text: formatConsensusShare(consensus.implied_probability) }));
    row.appendChild(cell);
  }

  const better = yours !== null ? paysBetter(best.american_price, yours) : null;
  if (yours !== null) {
    const cell = el("div", { class: "bc-price__cell" });
    cell.appendChild(el("div", { class: "bc-price__cell-label", text: "YOUR PRICE" }));
    cell.appendChild(el("div", {
      class: `bc-price__cell-value${better ? " bc-price__cell-value--struck" : ""}`,
      text: formatAmerican(yours),
    }));
    row.appendChild(cell);
  }

  row.appendChild(el("span", { class: "bc-price__spacer" }));

  const aside = el("div", { class: "bc-price__aside" });
  // The advantage pill is a checkable statement about two named prices at
  // named books -- line-shopping value, never expected value. Absent
  // entirely when the reader's own price is already the best one.
  const cents = centsBetween(best.american_price, yours);
  if (better && cents) {
    aside.appendChild(el("span", { class: "advantage-pill chamfer chamfer--badge",
      "data-hook": "price-improvement",
      text: `${cents}c BETTER AT ${formatBook(best.book)}` }));
  }
  const parts = [];
  if (consensus && typeof consensus.books === "number") parts.push(`BEST OF ${consensus.books} BOOKS`);
  const age = formatAge(result.price_improvement && result.price_improvement.age_seconds);
  if (age) parts.push(`UPDATED ${age}`);
  if (best.observed_utc) parts.push(`OBSERVED ${formatEasternClock(best.observed_utc) || ""} ET`);
  if (parts.length) aside.appendChild(el("div", { class: "bc-price__aside-meta", text: parts.join("  ·  ") }));
  row.appendChild(aside);
  panel.appendChild(row);
  section.appendChild(panel);

  // The contract's own boolean, rendered rather than reinterpreted.
  section.appendChild(el("p", { class: "bc-block__meta", "data-hook": "your-price-beats-consensus",
    text: result.your_price_beats_consensus === null || result.your_price_beats_consensus === undefined
      ? "YOUR PRICE VS MARKET-IMPLIED CONSENSUS: NOT AVAILABLE"
      : `YOUR PRICE BEATS THE MARKET-IMPLIED CONSENSUS: ${result.your_price_beats_consensus ? "YES" : "NO"}` }));

  if (result.price_improvement && result.price_improvement.label) {
    section.appendChild(el("p", { class: "bc-block__meta",
      text: String(result.price_improvement.label).toUpperCase() }));
  }
  return section;
}

function renderReasons(result) {
  const pair = el("div", { class: "bc-pair" });
  const strongest = block("05", "THE STRONGEST PART", { tone: "live" });
  if (result.strongest_reason) {
    strongest.appendChild(el("p", { class: "bc-quote", text: result.strongest_reason }));
  } else {
    strongest.appendChild(notYetAvailable(
      "Nothing in this game's evidence stood out as the most durable factor, so no "
      + "strongest part is named rather than one being chosen for the sake of the block.",
      "NOT DISTINGUISHED"));
  }
  const weakest = block("06", "THE WEAKEST PART", { tone: "risk", modifier: "counter" });
  if (result.weakest_reason) {
    weakest.appendChild(el("p", { class: "bc-quote", text: result.weakest_reason }));
  } else {
    // Integrity Rule 1: the risk block still appears, with its heading
    // and its red edge rule. It is never padded with an invented concern
    // and never hidden.
    weakest.appendChild(notYetAvailable(
      "No material concern was identified for this bet. We do not pad this block "
      + "with a generic risk to have something in it.",
      "NONE IDENTIFIED"));
  }
  pair.appendChild(strongest);
  pair.appendChild(weakest);
  return pair;
}

function renderWhatChanged(result) {
  const events = result.what_changed || [];
  const section = block("07", "WHAT CHANGED", { tone: "live",
    meta: `${events.length} EVENT${events.length === 1 ? "" : "S"}` });
  if (events.length === 0) {
    section.appendChild(el("p", { class: "gv-panel__body",
      text: "Nothing has changed on this game since the last poll." }));
    return section;
  }
  const stream = el("div", { class: "changed__stream" });
  for (const event of events) {
    const row = el("article", { class: "changed__row" });
    const meta = el("div", { class: "changed__meta" });
    const seen = formatEasternClock(event.seen_utc);
    if (seen) meta.appendChild(el("span", { class: "changed__time", text: seen }));
    if (event.tier) meta.appendChild(el("span", { class: "changed__cat", text: `RELEVANCE ${event.tier}` }));
    row.appendChild(meta);
    row.appendChild(el("p", { class: "changed__row-headline", text: event.headline || "" }));
    // The market reaction is printed only when the API carried one --
    // an absent reaction is an absent line, never an invented arrow.
    if (event.market_reaction) {
      const reaction = el("p", { class: "changed__reaction" });
      reaction.appendChild(renderUnknown(event.market_reaction));
      row.appendChild(reaction);
    }
    stream.appendChild(row);
  }
  section.appendChild(stream);
  return section;
}

const SUPPORT_STEPS = ["LIMITED", "MODERATE", "STRONG"];

function renderHistoricalSupport(result) {
  const section = block("08", "HISTORICAL SUPPORT", { tone: "live" });
  const value = result.historical_support ? String(result.historical_support).toUpperCase() : null;
  const index = value ? SUPPORT_STEPS.indexOf(value) : -1;
  if (index < 0) {
    section.appendChild(notYetAvailable(
      "Historical support is a qualitative three-step reading and none has been "
      + "recorded for this bet. It is never converted to a percentage.",
      "NOT RECORDED"));
    return section;
  }
  const meter = el("div", { class: "meter" });
  for (let i = 0; i < SUPPORT_STEPS.length; i += 1) {
    meter.appendChild(el("span", { class: `meter__seg chamfer${i <= index ? " meter__seg--on" : ""}` }));
  }
  section.appendChild(meter);
  const readout = el("div", { class: "meter__value", "data-hook": "historical-support" });
  readout.appendChild(el("span", { class: "meter__label", text: value }));
  readout.appendChild(el("span", { class: "meter__scale", text: SUPPORT_STEPS.join(" · ") }));
  section.appendChild(readout);
  return section;
}

// Five rungs, this order, this wording (handoff section 11). Only the
// rung the API actually reports is lit; nothing is lit by default.
const LADDER = ["OBSERVATION", "EXPLORATORY", "HISTORICAL SUPPORT", "FORWARD TESTING", "VALIDATED"];

function renderEvidenceStatus(result) {
  const section = block("09", "EVIDENCE STATUS", { tone: "live" });
  const value = result.evidence_status ? String(result.evidence_status).toUpperCase() : null;
  const ladder = el("div", { class: "ladder", "data-hook": "evidence-status" });
  for (const rung of LADDER) {
    const on = value === rung;
    const row = el("div", { class: `ladder__rung${on ? " ladder__rung--on" : ""}` });
    row.appendChild(el("span", { class: "ladder__bar chamfer" }));
    row.appendChild(el("span", { class: "ladder__name", text: rung }));
    if (on) row.appendChild(el("span", { class: "ladder__current", text: "◄ CURRENT" }));
    ladder.appendChild(row);
  }
  section.appendChild(ladder);
  if (!value) {
    section.appendChild(notYetAvailable(
      "No evidence rung was reported for this bet, so none is lit. A rung is never "
      + "assumed -- 27 pre-registered hypotheses have been measured and none has survived.",
      "NOT REPORTED"));
  }
  return section;
}

function renderBottomLine(result, submitted) {
  const section = block("10", "BOTTOM LINE", { attrs: { "data-hook": "bet-check-bottom-line" },
    tone: "mute" });
  const text = el("p", { class: "bc-bottom__text", "data-hook": "bottom-line-text" });
  text.appendChild(result.bottom_line
    ? document.createTextNode(result.bottom_line)
    : renderUnknown(null));
  section.appendChild(text);

  const actions = el("div", { class: "bc-bottom__actions" });
  const game = result.game || null;
  if (game && game.date && game.away && game.home) {
    actions.appendChild(el("a", {
      class: "btn btn--secondary chamfer chamfer--btn",
      href: `#/odds/${encodeURIComponent(game.date)}/${encodeURIComponent(game.away)}/${encodeURIComponent(game.home)}`,
      "data-hook": "compare-books",
      text: result.market_consensus && result.market_consensus.books
        ? `COMPARE ${result.market_consensus.books} BOOKS`
        : "COMPARE BOOKS",
    }));
    actions.appendChild(el("a", {
      class: "btn btn--ghost chamfer chamfer--btn",
      href: `#/game/${encodeURIComponent(game.date)}/${encodeURIComponent(game.away)}/${encodeURIComponent(game.home)}`,
      text: "OPEN THIS GAME",
    }));
  }
  actions.appendChild(el("span", { class: "bc-bottom__note",
    text: "NO PICKS · NO PROBABILITIES · LINE-SHOPPING VALUE ONLY" }));
  section.appendChild(actions);

  // recommendation is contractually always null (Ranker Engine 2 gate) --
  // rendered verbatim, never interpreted into a pick.
  const recommendation = el("p", { class: "bc-bottom__note", "data-hook": "recommendation" });
  recommendation.appendChild(document.createTextNode("RECOMMENDATION: "));
  recommendation.appendChild(renderUnknown(result.recommendation));
  section.appendChild(recommendation);
  return section;
}

/* ---------------------------------------------------------------------
 * The free tier
 * ------------------------------------------------------------------- */

/** "2 OF 3 FREE CHECKS LEFT" -- the server's own counters, printed as
 * they came. Three TOTAL, for life: no copy here may imply a daily or
 * recurring allowance (handoff section 11's free-access rule). */
function freeCheckEyebrow(freeCheck) {
  if (!freeCheck || typeof freeCheck !== "object") return null;
  const { remaining, limit } = freeCheck;
  if (typeof remaining !== "number" || typeof limit !== "number") return null;
  const row = el("p", { class: "bc-hero__hint", "data-hook": "free-checks-remaining",
    text: `${remaining} OF ${limit} FREE CHECKS LEFT` });
  return row;
}

/** The budget is spent. The server sends the message; it is rendered
 * verbatim rather than replaced with a client-composed upsell, and the
 * identity it hands back is kept so nothing resets someone's count. */
function renderExhausted(container, detail) {
  clear(container);
  const host = el("div", { class: "bc-skeleton" });
  const gate = el("section", { class: "gate chamfer", role: "alert",
    "data-hook": "free-checks-exhausted" });
  gate.appendChild(el("p", { class: "gate__eyebrow", text: "INTRODUCTORY CHECKS USED" }));
  gate.appendChild(el("p", { class: "gate__title", text: "That was your third free check." }));
  gate.appendChild(el("p", { class: "gate__body",
    text: detail && detail.message
      ? String(detail.message)
      : "Your three introductory Bet Checks are used up." }));
  const actions = el("div", { class: "gate__actions" });
  actions.appendChild(el("a", { href: "#/signup", class: "btn btn--primary chamfer chamfer--btn",
    "data-hook": "signup-link", text: "Create an account" }));
  actions.appendChild(el("a", { href: "#/signin", class: "btn btn--ghost chamfer chamfer--btn",
    text: "I have an invite token" }));
  gate.appendChild(actions);
  host.appendChild(gate);
  container.appendChild(host);
}

/** Rate limited (10/hour/IP). A plain wait message and a full stop --
 * this client never retries a 429 on its own. */
function renderRateLimited(container) {
  clear(container);
  const host = el("div", { class: "bc-skeleton" });
  const gate = el("section", { class: "gate chamfer", role: "alert",
    "data-hook": "free-checks-rate-limited" });
  gate.appendChild(el("p", { class: "gate__eyebrow", text: "TOO MANY CHECKS" }));
  gate.appendChild(el("p", { class: "gate__title", text: "Give it an hour." }));
  gate.appendChild(el("p", { class: "gate__body",
    text: "Free checks are limited by the hour. Try this one again a little later." }));
  host.appendChild(gate);
  container.appendChild(host);
}

/* ---------------------------------------------------------------------
 * Assembly
 * ------------------------------------------------------------------- */

function renderResult(container, result, submitted) {
  clear(container);
  const skeleton = el("section", { class: "bc-skeleton", "data-view": "bet-check-result" });
  const remaining = freeCheckEyebrow(result.free_check);
  if (remaining) skeleton.appendChild(remaining);
  const head = el("div", { class: "sechead" });
  head.appendChild(el("span", { class: "sechead__label", text: "THE CHECK" }));
  head.appendChild(el("span", { class: "sechead__hair" }));
  head.appendChild(el("span", { class: "sechead__meta", text: "FIXED SKELETON · 10 BLOCKS" }));
  skeleton.appendChild(head);

  if (result.note) {
    skeleton.appendChild(el("p", { class: "bet-check-result__note chamfer",
      "data-hook": "doubleheader-note", text: result.note }));
  }

  // Fixed order -- see module docstring. Do not reorder.
  skeleton.appendChild(renderYourBet(result, submitted));
  skeleton.appendChild(renderSupport(result));
  skeleton.appendChild(renderCounterargument(result));
  skeleton.appendChild(renderPrices(result));
  skeleton.appendChild(renderReasons(result));
  skeleton.appendChild(renderWhatChanged(result));
  const pair = el("div", { class: "bc-pair" });
  pair.appendChild(renderHistoricalSupport(result));
  pair.appendChild(renderEvidenceStatus(result));
  skeleton.appendChild(pair);
  skeleton.appendChild(renderBottomLine(result, submitted));

  container.appendChild(skeleton);
  armEntrances(skeleton);

  // The top strip reports board freshness only when the payload carries a
  // real age. This response carries an observation timestamp but no age,
  // so the strip stays empty rather than claiming "no board yet" about a
  // board that plainly exists.
  const improvement = result.price_improvement;
  const age = improvement && typeof improvement.age_seconds === "number"
    ? improvement.age_seconds : null;
  setShellStatusFromStaleness(age === null ? null : { age_seconds: age });
}

function part(kind, labelText, inputEl) {
  const wrap = el("div", { class: `bc-form__part bc-form__part--${kind}` });
  wrap.appendChild(el("label", { for: inputEl.id, text: labelText }));
  wrap.appendChild(inputEl);
  return wrap;
}

export async function renderBetCheck(container, prefill = {}) {
  clear(container);
  const screen = el("div", { class: "screen", "data-view": "betcheck" });
  container.appendChild(screen);

  const hero = el("section", { class: "bc-hero" });
  hero.appendChild(el("span", { class: "tex-carbon" }));
  hero.appendChild(el("span", { class: "tex-scanline" }));
  hero.appendChild(el("span", { class: "bc-hero__seam" }));
  const eyebrow = el("div", { class: "bc-hero__eyebrow", "data-rise": "" });
  eyebrow.appendChild(el("span", { class: "checkband__tick" }));
  eyebrow.appendChild(el("span", { class: "bc-hero__label", text: "CHECK A BET" }));
  hero.appendChild(eyebrow);
  hero.appendChild(el("h1", { class: "bc-hero__headline", "data-rise": "", "data-delay": "80",
    text: "DOES YOUR BET HOLD UP?" }));
  hero.appendChild(el("p", { class: "bc-hero__sub", "data-rise": "", "data-delay": "140",
    text: "We show what supports it, what argues against it, and where the price is better." }));

  const form = el("form", { class: "bc-form", "data-hook": "bet-check-form",
    "data-rise": "", "data-delay": "200" });
  const field = el("div", { class: "bc-form__field chamfer" });
  field.appendChild(el("span", { class: "bc-form__bullet" }));

  const dateInput = el("input", { type: "date", id: "bc-date", name: "date",
    value: prefill.date || todayIso(), required: "required" });
  const awayInput = el("input", { type: "text", id: "bc-away", name: "away",
    value: prefill.away || "", placeholder: "SD", required: "required" });
  const homeInput = el("input", { type: "text", id: "bc-home", name: "home",
    value: prefill.home || "", placeholder: "CIN", required: "required" });
  const sideSelect = el("select", { id: "bc-side", name: "side", required: "required" });
  sideSelect.appendChild(el("option", { value: "away", text: "AWAY" }));
  sideSelect.appendChild(el("option", { value: "home", text: "HOME" }));
  const priceInput = el("input", { type: "number", id: "bc-price", name: "american_price",
    step: "1", placeholder: "-140", required: "required" });

  field.appendChild(part("date", "Date", dateInput));
  field.appendChild(part("team", "Away", awayInput));
  field.appendChild(part("team", "Home", homeInput));
  field.appendChild(part("side", "Side", sideSelect));
  field.appendChild(part("price", "Price", priceInput));
  form.appendChild(field);

  const submit = el("div", { class: "bc-form__submit" });
  submit.appendChild(el("button", { type: "submit", class: "btn btn--cyan chamfer chamfer--btn on-live",
    text: "CHECK IT" }));
  form.appendChild(submit);
  hero.appendChild(form);
  hero.appendChild(el("p", { class: "bc-hero__hint",
    text: "CLUB ABBREVIATIONS AS THE BOARD LISTS THEM · e.g. SD @ CIN · AWAY · -140" }));
  screen.appendChild(hero);

  const resultHost = el("div", { "data-hook": "bet-check-result-host" });
  // Empty state: the ten-block skeleton is not drawn until a bet exists
  // (handoff section 10) -- a plain sentence, not a blank pane.
  const empty = el("div", { class: "bc-skeleton" }, [
    el("p", { class: "gate__title", text: "Paste a bet to begin." }),
    el("p", { class: "gate__body",
      text: "Fill in the game, the side and the price you are looking at. "
          + "The ten-block check appears here." }),
  ]);
  empty.setAttribute("data-hook", "bet-check-empty");
  resultHost.appendChild(empty);
  screen.appendChild(resultHost);

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const submitted = {
      date: dateInput.value,
      away: awayInput.value.trim().toUpperCase(),
      home: homeInput.value.trim().toUpperCase(),
      side: sideSelect.value,
      american_price: Number(priceInput.value),
    };
    clear(resultHost);
    resultHost.appendChild(el("div", { class: "bc-skeleton" }, [renderLoading("CHECKING THIS BET")]));
    // Signed in -> the paid path, untouched. Signed out -> the public
    // free path, so a visitor meets the product rather than a wall.
    const authed = !!getToken();
    let result;
    try {
      if (authed) {
        result = await apiPost("/betcheck", submitted);
      } else {
        const freeToken = getFreeCheckToken();
        result = await apiFetch("/betcheck/free", {
          method: "POST",
          body: JSON.stringify(submitted),
          headers: freeToken ? { "X-Free-Check-Token": freeToken } : {},
        });
        // Persist the identity the server minted, so the next check
        // spends from the same budget instead of starting a new one.
        if (result && result.free_check && result.free_check.token) {
          setFreeCheckToken(result.free_check.token);
        }
      }
    } catch (err) {
      const detail = err && err.detail && typeof err.detail === "object" ? err.detail : null;
      if (!authed && err && err.status === 402 && detail
          && detail.error === "free_checks_exhausted") {
        if (detail.free_check_token) setFreeCheckToken(detail.free_check_token);
        renderExhausted(resultHost, detail);
        return;
      }
      if (!authed && err && err.status === 429) {
        renderRateLimited(resultHost);
        return;
      }
      clear(resultHost);
      const host = el("div", { class: "bc-skeleton" });
      resultHost.appendChild(host);
      renderError(host, err);
      return;
    }
    renderResult(resultHost, result, submitted);
  });

  armEntrances(hero);
}
