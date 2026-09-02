/**
 * BET CHECK V2 (#/betcheck) -- POST /betcheck (api/betcheck.py, authed/paid)
 * and POST /betcheck/free (api/betcheck.py, anonymous, three lifetime
 * checks). Composed from design/linehound-v2/'LINEHOUND V2 Full Product
 * .dc.html' -- V2-04 (desktop ten-block skeleton, lines 3017-3391), V2-24
 * (mobile, all ten blocks as peers, lines 5738-5843), V2-25 (the closeup on
 * blocks 05/06/08/09 -- the USUAL render, lines 5846-5941), V2-26 (free
 * checks used up / 402, lines 5941-6032) and V2-32 (the Featured Bet hero
 * as block 01, lines 6999-7178). Wave 1, Group Bet Check --
 * design/linehound-v2/IMPLEMENTATION_PLAN.md.
 *
 * TEN BLOCKS, FIXED ORDER, ALWAYS AS PEERS (the artboards' own rule, and
 * this product's honesty mechanism -- docs/PRODUCT_DESIGN_HANDOFF.md: "an
 * omission becomes visible only if the shape never changes"):
 *
 *   01 THE BET              (data-hook="bet-check-your-bet") -- the Featured
 *      Bet Tier-A hero (web/js/featuredbet.js), NOT a plain price readout
 *   02 THE MARKET           (data-hook="bet-check-prices")
 *   03 THE CASE             (data-hook="bet-check-support")
 *   04 COUNTERARGUMENT      (data-hook="bet-check-counterargument")
 *   05 WHAT CHANGED         -- usually NOT YET AVAILABLE
 *   06 HISTORICAL SUPPORT   -- usually NOT YET AVAILABLE
 *   07 EVIDENCE STATUS      -- always "Observation" today
 *   08 SIMILAR BETS         -- NOT YET AVAILABLE, no field exists at all
 *   09 YOUR HISTORY         -- NOT YET AVAILABLE, no field exists at all
 *   10 BOTTOM LINE          (data-hook="bet-check-bottom-line")
 *
 * tests/test_web_structure.py's BetCheckSkeletonOrder pins the five
 * data-hook markers above in this exact TEXTUAL order in this file's
 * source. Function declarations are hoisted, so `renderResult` below calls
 * them in the true visual (01->10) order while their definitions keep the
 * textual order the test expects (your-bet, support, counterargument,
 * prices, bottom-line) -- do not reorder either without checking that
 * test.
 *
 * V1 -> V2 CHANGES TO THE SKELETON ITSELF (flagged for the orchestrator)
 * -------------------------------------------------------------------
 * The V1 skeleton (this file, until this change) carried STRONGEST THE
 * PART / WEAKEST THE PART as blocks 05/06, reading `strongest_reason` /
 * `weakest_reason` (both real, ENGINEERING_REQUIRED fields the API can
 * still return). V2-04/24/25/32's artboards replace those two slots with
 * WHAT CHANGED and HISTORICAL SUPPORT at 05/06, and add two entirely new
 * NOT-YET-AVAILABLE slots -- SIMILAR BETS (08) and YOUR HISTORY (09) --
 * that have no backing field anywhere in the contract. Matching the
 * artboards exactly, `strongest_reason`/`weakest_reason` are no longer
 * rendered as their own blocks. Both are still real, non-fabricated
 * fields the server can send; dropping their dedicated blocks is a
 * design decision (this lane implements the artboard as given), not a
 * contract violation -- flagged here for confirmation rather than
 * silently discarded.
 *
 * TWO ENDPOINTS, ONE SCREEN (unchanged from V1)
 * -------------------------------------------------------------------
 * A signed-in reader posts to /betcheck. An anonymous visitor posts to
 * /betcheck/free, capped at three introductory checks FOR LIFE (not per
 * day). The two responses are field-identical apart from the extra
 * `free_check` block, so the ten-block skeleton renders from either one
 * unchanged. The free identity rides a header (X-Free-Check-Token), never
 * an Authorization bearer.
 *
 * WHY THE TICKET IS A COMPOSED PANEL, NOT ONE FREE-TEXT FIELD (unchanged
 * from V1 -- the artboards' own "NYY ML -125" field is illustrative of a
 * parser that does not exist: the API states plainly that "team-name
 * resolution is the client's job"). The ticket carries the real
 * date/away/home/side/price fields at display scale inside the same
 * geometry instead. The one deliberate composition deviation on this
 * screen, same as V1's.
 *
 * FIELDS THE ARTBOARD SHOWS THAT THIS ENDPOINT DOES NOT HAVE (never
 * invented -- rendered as the artboard's own NOT AVAILABLE / NOT YET
 * AVAILABLE treatment):
 *   - Block 02's "-119 DE-VIGGED CONSENSUS" example is an American price
 *     converted from a probability. `market_consensus` on this endpoint
 *     carries only `implied_probability` (a fraction) -- no `implied_price`
 *     counterpart (unlike GET /odds's consensus objects, which DO carry a
 *     server-computed `implied_price`). Converting a probability to an
 *     American price ourselves would be exactly the kind of derived number
 *     this lane's boundary forbids ("never compute a probability"), so
 *     this block shows the consensus as a PERCENTAGE via the existing
 *     `formatConsensusShare` helper instead -- the same choice the V1
 *     implementation already made, now carried into V2.
 *   - Block 02's "CONSENSUS BEATS YOUR PRICE -6c" chip is folded into the
 *     `your_price_beats_consensus` boolean line (rendered verbatim) plus
 *     the contract's own mandatory `price_improvement.label` sentence,
 *     rather than duplicated as a second, differently-worded chip not
 *     present in the API's vocabulary.
 *   - Blocks 08 (SIMILAR BETS) and 09 (YOUR HISTORY): no field, no
 *     endpoint, anywhere in the contract. Always NOT YET AVAILABLE.
 *   - Block 01's price-standing rank and verdict word: POST /betcheck
 *     carries neither (see web/js/featuredbet.js's docstring in full) --
 *     rendered as that module's own honest-absence treatment, never
 *     guessed at here.
 *
 * BUG FIX CARRIED FORWARD FROM V1: `Claim` objects (thesis_support and
 * counterargument) serialize their sentence under the key `statement`
 * (src/analysis/contracts.py's Claim.to_json via `asdict`), not `text` /
 * `claim` / `headline` / `summary`. V1's `claimText()` never actually
 * matched a real API response and always fell through to `renderUnknown`.
 * Fixed here to read `claim.statement` first.
 */

import { apiFetch, apiPost, getToken, getFreeCheckToken, setFreeCheckToken } from "./api.js";
import { el, clear, renderUnknown, renderError, renderLoading, notYetAvailable,
  formatAmerican, formatConsensusShare, formatEasternClock } from "./dom.js";
import { bookLabel } from "./labels.js";
import { setShellStatus } from "./shell.js";
import { armEntrances } from "./motion.js";
import { renderFeaturedBet, mapBetCheckPayloadToStanding } from "./featuredbet.js";

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

/** "4:12pm ET" -- the compact clock style every V2 screen uses. */
function et(isoUtc) {
  const clock = formatEasternClock(isoUtc);
  return clock ? `${clock} ET` : null;
}

/** A `Claim` (thesis_support / counterargument) rendered as its own
 * sentence plus the sample it is required to carry alongside any number
 * (src/analysis/contracts.py's Claim.__post_init__: a quantitative claim
 * without sample_n/sample_unit is refused server-side). See the module
 * docstring's "BUG FIX" note -- `statement` is the real wire key. */
function claimText(claim) {
  if (typeof claim === "string") return { text: claim, sample: null, raw: claim };
  if (!claim || typeof claim !== "object") return { text: String(claim), sample: null, raw: claim };
  const text = claim.statement || claim.text || claim.claim || claim.headline || claim.summary || null;
  let sample = null;
  if (claim.sample_n !== undefined && claim.sample_n !== null) {
    sample = claim.sample_unit ? `n = ${claim.sample_n} ${claim.sample_unit}` : `n = ${claim.sample_n}`;
  }
  return { text, sample, raw: claim };
}

/* ---------------------------------------------------------------------
 * Block chrome -- one numbered, titled, bannered section per V2-04/24.
 * ------------------------------------------------------------------- */

function blockChip(chip) {
  return el("span", { class: `bc2-chip bc2-chip--${chip.tone || "live"}`, text: chip.text });
}

function block(no, title, opts = {}) {
  const section = el("section", Object.assign({
    class: `bc2-block chamfer${opts.tone ? ` bc2-block--${opts.tone}` : ""}`,
    "data-rise": "",
  }, opts.attrs || {}));
  const head = el("div", { class: "bc2-block__head" });
  head.appendChild(el("span", { class: "bc2-block__no", text: no }));
  head.appendChild(el("span", { class: "bc2-block__title", text: title }));
  if (opts.chip) head.appendChild(blockChip(opts.chip));
  head.appendChild(el("span", { class: "bc2-block__hair" }));
  if (opts.meta) head.appendChild(el("span", { class: "bc2-block__meta-tag", text: opts.meta }));
  section.appendChild(head);
  return section;
}

/** The connector labels between narrative blocks (V2-04's "SO WHAT DOES
 * THE MARKET SAY?" etc, verbatim) -- cheap, and they narrate the ten
 * blocks as one argument rather than ten unrelated cards. */
function connector(text) {
  return el("div", { class: "bc2-connector" }, [
    el("span", { class: "bc2-connector__bar", "aria-hidden": "true" }),
    el("span", { class: "bc2-connector__text", text }),
  ]);
}

/** A whole block rendered as NOT YET AVAILABLE (V2-25's amber treatment):
 * same number, same title, same full width as every other block -- a
 * block that is usually empty is still a peer, never demoted or hidden
 * (V2-25's own verbatim rule). */
function naBlock(no, title, reason, opts = {}) {
  const section = block(no, title, Object.assign({
    tone: "na",
    chip: { text: "NOT YET AVAILABLE", tone: "warn" },
  }, opts));
  section.appendChild(el("p", { class: "bc2-na__body", text: reason }));
  return section;
}

function line(text, kind, sample) {
  const row = el("li", { class: `bc2-line bc2-line--${kind}` });
  row.appendChild(el("span", { class: "bc2-line__mark", "aria-hidden": "true" }));
  row.appendChild(el("span", { class: "bc2-line__body", text }));
  if (sample) row.appendChild(el("span", { class: "bc2-line__sample", text: sample }));
  return row;
}

/* ---------------------------------------------------------------------
 * 01 -- THE BET (the Featured Bet Tier-A hero; V2-32)
 * ------------------------------------------------------------------- */

function renderTheBet(result) {
  const section = block("01", "THE BET", {
    attrs: { "data-hook": "bet-check-your-bet" },
    chip: { text: "TIER A", tone: "live" },
  });
  const mount = el("div", { class: "bc2-fbmount" });
  section.appendChild(mount);
  // Neither `verdict` nor `priceStanding` is supplied: this screen has no
  // second fetch to source a verdict from, and no per-book board to count
  // a rank against -- both render as that module's own honest NOT
  // AVAILABLE, exactly as its docstring requires. Never guessed here.
  renderFeaturedBet(mount, mapBetCheckPayloadToStanding(result, {}));
  return section;
}

/* ---------------------------------------------------------------------
 * 03 -- THE CASE (thesis_support, may be empty)
 * ------------------------------------------------------------------- */

function renderCase(result) {
  const support = Array.isArray(result.thesis_support) ? result.thesis_support : [];
  const section = block("03", "THE CASE", {
    attrs: { "data-hook": "bet-check-support" }, tone: "case",
    meta: `${support.length} POINT${support.length === 1 ? "" : "S"}`,
  });
  if (support.length === 0) {
    section.appendChild(el("div", { class: "bc2-case__empty" }, [
      el("span", { class: "bc2-case__rule", "aria-hidden": "true" }),
      el("p", { class: "bc2-case__headline",
        text: "Nothing in our data supports this bet. That is not the same as it being wrong." }),
    ]));
    section.appendChild(el("p", { class: "bc2-block__note",
      text: "thesis_support came back empty -- the usual case, not a fabricated finding." }));
    return section;
  }
  const list = el("ul", { class: "bc2-lines" });
  for (const claim of support) {
    const { text, sample, raw } = claimText(claim);
    if (text) list.appendChild(line(text, "for", sample));
    else list.appendChild(el("li", { class: "bc2-line" }, [renderUnknown(raw)]));
  }
  section.appendChild(list);
  return section;
}

/* ---------------------------------------------------------------------
 * 04 -- COUNTERARGUMENT (never empty by constructor)
 * ------------------------------------------------------------------- */

function renderCounterargument(result) {
  const raw = Array.isArray(result.counterargument) ? result.counterargument : [];
  const lines = Array.isArray(result.counterargument_lines) ? result.counterargument_lines : [];
  const section = block("04", "COUNTERARGUMENT", {
    attrs: { "data-hook": "bet-check-counterargument" }, tone: "counter",
    chip: { text: "NEVER EMPTY BY CONSTRUCTOR", tone: "money" },
  });
  const list = el("ul", { class: "bc2-lines", "data-hook": "counterargument-lines" });
  if (raw.length) {
    // The raw `counterargument` Claim array carries each item's sample_n /
    // sample_unit -- read from it when present so the reader sees the "n ="
    // figure the artboard shows beside each line.
    for (const claim of raw) {
      const { text, sample, raw: original } = claimText(claim);
      if (text) list.appendChild(line(text, "against", sample));
      else list.appendChild(el("li", { class: "bc2-line" }, [renderUnknown(original)]));
    }
  } else {
    // `counterargument` came back empty -- the ONLY way `counterargument_lines`
    // is non-empty here is the server's own required, structurally
    // enforced padding string. Printed verbatim, no sample (there is no
    // claim behind it), never composed client-side
    // (tests/test_web_structure.py pins this).
    for (const text of lines) list.appendChild(line(text, "against", null));
  }
  section.appendChild(list);
  return section;
}

/* ---------------------------------------------------------------------
 * 02 -- THE MARKET (price / consensus / improvement)
 *
 * Defined here, textually AFTER blocks 03/04, purely so this file's
 * data-hook literals stay in the exact order
 * tests/test_web_structure.py's BetCheckSkeletonOrder pins (your-bet,
 * support, counterargument, prices, bottom-line) -- function
 * declarations are hoisted, so `renderResult` below still CALLS this in
 * the true visual order (02, straight after block 01). Do not move this
 * definition without re-checking that test.
 * ------------------------------------------------------------------- */

function renderMarket(result) {
  const section = block("02", "THE MARKET", { attrs: { "data-hook": "bet-check-prices" } });
  const best = result.best_available_price;
  const consensus = result.market_consensus;
  const yours = result.query && typeof result.query.price === "number" ? result.query.price : null;

  if (!best && !consensus) {
    section.appendChild(notYetAvailable(
      "No book has posted a price on this game yet, so there is nothing to compare your price against.",
      "NO PRICE CAPTURED"));
    return section;
  }

  const cells = el("div", { class: "bc2-market" });
  if (typeof yours === "number") {
    const cell = el("div", { class: "bc2-market__cell" });
    cell.appendChild(el("div", { class: "bc2-market__label", text: "YOUR PRICE" }));
    cell.appendChild(el("div", { class: "bc2-market__figure", text: formatAmerican(yours) }));
    cells.appendChild(cell);
  }
  if (consensus && typeof consensus.implied_probability === "number") {
    const cell = el("div", { class: "bc2-market__cell bc2-market__cell--accent" });
    cell.appendChild(el("div", { class: "bc2-market__label", text: "DE-VIGGED CONSENSUS" }));
    const row = el("div", { class: "bc2-market__row" });
    row.appendChild(el("span", { class: "bc2-market__figure", "data-hook": "market-consensus",
      text: formatConsensusShare(consensus.implied_probability) }));
    if (typeof consensus.books === "number") {
      row.appendChild(el("span", { class: "bc2-market__sample", text: `n = ${consensus.books} books` }));
    }
    cell.appendChild(row);
    cells.appendChild(cell);
  }
  if (best) {
    const cell = el("div", { class: "bc2-market__cell bc2-market__cell--pill" });
    cell.appendChild(el("div", { class: "bc2-market__label", text: "BEST AVAILABLE" }));
    const pill = el("div", { class: "bc2-market__pill", "data-hook": "best-available-price" });
    pill.appendChild(el("span", { text: formatAmerican(best.american_price) }));
    if (best.book) pill.appendChild(el("span", { class: "bc2-market__pill-book", text: bookLabel(best.book) }));
    cell.appendChild(pill);
    // A checkable line-shopping tip: a real, named, better price at a
    // named book -- never expected value, never an edge. Absent entirely
    // when the reader's own price already is the best one.
    const better = yours !== null ? paysBetter(best.american_price, yours) : null;
    const cents = centsBetween(best.american_price, yours);
    if (better && cents) {
      cell.appendChild(el("div", { class: "bc2-market__advantage", "data-hook": "price-improvement",
        text: `${cents}c BETTER AT ${bookLabel(best.book)}` }));
    }
    cells.appendChild(cell);
  }
  section.appendChild(cells);

  section.appendChild(el("p", { class: "bc2-block__note", "data-hook": "your-price-beats-consensus",
    text: result.your_price_beats_consensus === null || result.your_price_beats_consensus === undefined
      ? "YOUR PRICE VS MARKET-IMPLIED CONSENSUS: NOT AVAILABLE"
      : `YOUR PRICE BEATS THE MARKET-IMPLIED CONSENSUS: ${result.your_price_beats_consensus ? "YES" : "NO"}` }));

  if (result.price_improvement && result.price_improvement.label) {
    section.appendChild(el("p", { class: "bc2-block__note bc2-block__note--muted",
      text: String(result.price_improvement.label) }));
  }

  // No age_seconds field exists on this payload at all (design/linehound-v2/
  // RECONCILED_CONTRACT_CURRENT_HEAD.md, priority answer 4) -- only a
  // capture instant. Shown as a clock, never as a fabricated "X min ago".
  const observed = et(best && best.observed_utc);
  section.appendChild(el("p", { class: "bc2-block__foot",
    text: observed ? `OBSERVED ${observed} · NO age_seconds FIELD ON THIS PAYLOAD`
      : "NO FRESHNESS FIGURE ON THIS PAYLOAD" }));
  return section;
}

/* ---------------------------------------------------------------------
 * 05 -- WHAT CHANGED (usually NOT YET AVAILABLE)
 * ------------------------------------------------------------------- */

function renderWhatChanged(result) {
  const events = Array.isArray(result.what_changed) ? result.what_changed : [];
  if (events.length === 0) {
    return naBlock("05", "WHAT CHANGED",
      "No capture-to-capture comparison on this bet. There is no time-series endpoint, so there is no "
      + "movement chart either.");
  }
  const section = block("05", "WHAT CHANGED", { meta: `${events.length} EVENT${events.length === 1 ? "" : "S"}` });
  const stream = el("div", { class: "bc2-changed" });
  for (const event of events) {
    const row = el("article", { class: "bc2-changed__row" });
    const meta = el("div", { class: "bc2-changed__meta" });
    const seen = et(event.seen_utc);
    if (seen) meta.appendChild(el("span", { text: seen }));
    if (event.tier) meta.appendChild(el("span", { text: `RELEVANCE ${event.tier}` }));
    row.appendChild(meta);
    row.appendChild(el("p", { class: "bc2-changed__headline", text: event.headline || "" }));
    // The market reaction is printed only when the API carried one -- an
    // absent reaction is an absent line, never an invented arrow.
    if (event.market_reaction) {
      const reaction = el("p", { class: "bc2-changed__reaction" });
      reaction.appendChild(renderUnknown(event.market_reaction));
      row.appendChild(reaction);
    }
    stream.appendChild(row);
  }
  section.appendChild(stream);
  return section;
}

/* ---------------------------------------------------------------------
 * 06 -- HISTORICAL SUPPORT (usually NOT YET AVAILABLE)
 * ------------------------------------------------------------------- */

const SUPPORT_STEPS = ["LIMITED", "MODERATE", "STRONG"];

function renderHistorical(result) {
  const value = result.historical_support ? String(result.historical_support).toUpperCase() : null;
  const index = value ? SUPPORT_STEPS.indexOf(value) : -1;
  if (index < 0) {
    return naBlock("06", "HISTORICAL SUPPORT",
      "No historical store for this pattern. Max reachable evidence tier is 1.");
  }
  const section = block("06", "HISTORICAL SUPPORT");
  const meter = el("div", { class: "bc2-meterbar" });
  for (let i = 0; i < SUPPORT_STEPS.length; i += 1) {
    meter.appendChild(el("span", { class: `bc2-meterbar__seg${i <= index ? " bc2-meterbar__seg--on" : ""}` }));
  }
  section.appendChild(meter);
  const readout = el("div", { class: "bc2-block__note", "data-hook": "historical-support" });
  readout.appendChild(el("span", { text: value }));
  readout.appendChild(el("span", { class: "bc2-block__foot", text: ` · ${SUPPORT_STEPS.join(" · ")}` }));
  section.appendChild(readout);
  return section;
}

/* ---------------------------------------------------------------------
 * 07 -- EVIDENCE STATUS (always "Observation" today)
 * ------------------------------------------------------------------- */

function renderEvidenceStatus(result) {
  const value = result.evidence_status ? String(result.evidence_status).toUpperCase() : null;
  if (!value) {
    return naBlock("07", "EVIDENCE STATUS",
      "No evidence rung was reported for this bet, so none is shown -- a rung is never assumed. Twenty-seven "
      + "pre-registered hypotheses have been measured and none has survived.");
  }
  const section = block("07", "EVIDENCE STATUS");
  section.appendChild(el("span", { class: "bc2-pill", "data-hook": "evidence-status", text: value }));
  section.appendChild(el("p", { class: "bc2-block__note",
    text: value === "OBSERVATION"
      ? "The only reachable value today. No badge -- a badge is reserved for tested and failed."
      : "" }));
  return section;
}

/* ---------------------------------------------------------------------
 * 08 -- SIMILAR BETS (no field anywhere -- always NOT YET AVAILABLE)
 * ------------------------------------------------------------------- */

function renderSimilarBets() {
  return naBlock("08", "SIMILAR BETS", "No similarity index ingested.");
}

/* ---------------------------------------------------------------------
 * 09 -- YOUR HISTORY (no field anywhere -- always NOT YET AVAILABLE)
 * ------------------------------------------------------------------- */

function renderYourHistory() {
  return naBlock("09", "YOUR HISTORY",
    "Requires settled outcomes on comparable saved bets, joined against My Bets. Not built on this endpoint.");
}

/* ---------------------------------------------------------------------
 * 10 -- BOTTOM LINE (mechanical, verbatim)
 * ------------------------------------------------------------------- */

function renderBottomLine(result) {
  const section = block("10", "BOTTOM LINE", { attrs: { "data-hook": "bet-check-bottom-line" } });
  const text = el("p", { class: "bc2-bottom__text", "data-hook": "bottom-line-text" });
  text.appendChild(result.bottom_line
    ? document.createTextNode(result.bottom_line)
    : renderUnknown(null));
  section.appendChild(text);
  section.appendChild(el("p", { class: "bc2-block__note",
    text: "Observation only. This is not advice and not a prediction, and we never tell you to place a bet." }));

  const actions = el("div", { class: "bc2-bottom__actions" });
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
  section.appendChild(actions);

  // recommendation is contractually always null (Ranker Engine 2 gate) --
  // rendered verbatim, never interpreted into a pick.
  const recommendation = el("p", { class: "bc2-block__foot", "data-hook": "recommendation" });
  recommendation.appendChild(document.createTextNode("RECOMMENDATION: "));
  recommendation.appendChild(renderUnknown(result.recommendation));
  section.appendChild(recommendation);
  section.appendChild(el("p", { class: "bc2-block__foot",
    text: "MECHANICALLY COMPOSED FROM FINDING COUNT + PRICE CLAUSE + DISCLAIMER -- NOT EDITORIAL" }));
  return section;
}

/* ---------------------------------------------------------------------
 * The free tier: meter, 402 exhaustion wall, 429 rate limit
 * ------------------------------------------------------------------- */

/** `limit`/`remaining` filled segments left-to-right represent CHECKS
 * LEFT, matching V2-04/24/26's own bars (a "2 of 3 left" ticket shows two
 * lit segments and one dim one, not one lit for "one used"). Real server
 * counters only -- never a hardcoded count (handoff's free-access rule). */
function meterBar(remaining, limit) {
  const bar = el("div", { class: "bc2-freebar" });
  for (let i = 0; i < limit; i += 1) {
    bar.appendChild(el("span", { class: `bc2-freebar__seg${i < remaining ? " bc2-freebar__seg--on" : ""}` }));
  }
  return bar;
}

/** Mounted once inside the sticky ticket; updated after every response
 * rather than rebuilt, so a signed-out visitor sees their real count
 * update in place without the ticket's inputs being touched. Pre-first-
 * check, no per-visitor count is knowable yet (the server has not minted
 * an identity), so this shows the fixed product fact only -- never a
 * fabricated "3 of 3" before anyone has spent one. */
function renderFreeMeter(host, freeCheck) {
  clear(host);
  if (freeCheck && typeof freeCheck.remaining === "number" && typeof freeCheck.limit === "number") {
    const row = el("div", { class: "bc2-freemeter__row" });
    row.appendChild(el("span", { class: "bc2-freemeter__label", "data-hook": "free-checks-remaining",
      text: `${freeCheck.remaining} OF ${freeCheck.limit} LEFT` }));
    row.appendChild(el("span", { class: "bc2-freemeter__spacer" }));
    row.appendChild(el("span", { class: "bc2-freemeter__note", text: "TOTAL, NOT DAILY" }));
    host.appendChild(row);
    host.appendChild(meterBar(freeCheck.remaining, freeCheck.limit));
  } else {
    host.appendChild(el("p", { class: "bc2-freemeter__static",
      text: "THREE FREE CHECKS, FOR LIFE -- NOT DAILY" }));
  }
}

/** The budget is spent (402 free_checks_exhausted). V2-26's amber wall --
 * hot red is reserved for the one primary action (GET FOUNDING ACCESS)
 * per the reserved-color rule, never used to signal the paywall itself as
 * a risk. The server's own message is rendered verbatim; the identity it
 * hands back is kept so nothing resets someone's count. */
function renderExhausted(container, detail) {
  clear(container);
  const wall = el("section", { class: "bc2-wall chamfer", role: "alert",
    "data-hook": "free-checks-exhausted" });
  const main = el("div", { class: "bc2-wall__main" });
  main.appendChild(el("p", { class: "bc2-wall__eyebrow", text: "CHECKS USED UP" }));
  const remaining = detail && typeof detail.remaining === "number" ? detail.remaining : 0;
  const limit = detail && typeof detail.limit === "number" ? detail.limit : 3;
  main.appendChild(el("span", { class: "bc2-wall__eyebrow-note",
    text: `${remaining} OF ${limit} REMAINING · LIMIT ${limit}, LIFETIME` }));
  main.appendChild(el("p", { class: "bc2-wall__title", text: "That was the third one." }));
  main.appendChild(el("p", { class: "bc2-wall__body",
    text: detail && detail.message
      ? String(detail.message)
      : "Three in total, for the life of the account -- you've used them. You've seen what it does, "
        + "including the nights it says there's nothing there." }));
  main.appendChild(meterBar(remaining, limit));
  const actions = el("div", { class: "bc2-wall__actions" });
  actions.appendChild(el("a", { href: "#/signup", class: "btn btn--primary chamfer chamfer--btn",
    "data-hook": "signup-link", text: "GET FOUNDING ACCESS · $19.99/MO" }));
  actions.appendChild(el("a", { href: "#/signup", class: "btn btn--ghost chamfer chamfer--btn",
    "data-hook": "keep-using-board", text: "KEEP USING THE BOARD" }));
  main.appendChild(actions);
  main.appendChild(el("p", { class: "bc2-wall__fine",
    text: "$19.99 a month, cancel whenever you like -- it schedules at the end of the period and you keep "
        + "access until then. The board stays open either way." }));
  wall.appendChild(main);

  const still = el("aside", { class: "bc2-wall__still" });
  still.appendChild(el("p", { class: "bc2-wall__still-label", text: "STILL FREE WITHOUT FOUNDING ACCESS" }));
  const items = ["The full odds board", "Every capture time", "Team records and splits",
    "Saving and settling your bets"];
  for (const text of items) {
    still.appendChild(el("div", { class: "bc2-wall__still-item" }, [
      el("span", { class: "bc2-wall__still-mark", "aria-hidden": "true" }),
      el("span", { text }),
    ]));
  }
  still.appendChild(el("p", { class: "bc2-wall__still-foot",
    text: "AMBER, NOT RED -- A PAYWALL IS NOT A RISK · 402 ON POST /betcheck" }));
  wall.appendChild(still);
  container.appendChild(wall);
}

/** Rate limited (10/hour/IP). A plain wait message and a full stop --
 * this client never retries a 429 on its own. */
function renderRateLimited(container) {
  clear(container);
  const wall = el("section", { class: "bc2-wall chamfer", role: "alert",
    "data-hook": "free-checks-rate-limited" });
  const main = el("div", { class: "bc2-wall__main" });
  main.appendChild(el("p", { class: "bc2-wall__eyebrow", text: "TOO MANY CHECKS" }));
  main.appendChild(el("p", { class: "bc2-wall__title", text: "Give it an hour." }));
  main.appendChild(el("p", { class: "bc2-wall__body",
    text: "Free checks are limited by the hour. Try this one again a little later." }));
  wall.appendChild(main);
  container.appendChild(wall);
}

/* ---------------------------------------------------------------------
 * Assembly
 * ------------------------------------------------------------------- */

function renderResult(container, result) {
  clear(container);
  const blocks = el("div", { class: "bc2-blocks", "data-view": "bet-check-result" });

  if (result.note) {
    blocks.appendChild(el("p", { class: "bc2-note chamfer", "data-hook": "doubleheader-note",
      text: result.note }));
  }

  // Fixed order -- see module docstring. Do not reorder.
  blocks.appendChild(renderTheBet(result));
  blocks.appendChild(connector("SO WHAT DOES THE MARKET SAY?"));
  blocks.appendChild(renderMarket(result));
  blocks.appendChild(connector("IS THERE A CASE FOR IT?"));
  blocks.appendChild(renderCase(result));
  blocks.appendChild(connector("AND THE OTHER SIDE OF IT?"));
  blocks.appendChild(renderCounterargument(result));
  blocks.appendChild(connector("DID ANYTHING MOVE?"));
  blocks.appendChild(renderWhatChanged(result));
  blocks.appendChild(renderHistorical(result));
  blocks.appendChild(renderEvidenceStatus(result));
  blocks.appendChild(renderSimilarBets());
  blocks.appendChild(renderYourHistory());
  blocks.appendChild(connector("SO WHERE DOES THAT LEAVE IT?"));
  blocks.appendChild(renderBottomLine(result));

  container.appendChild(blocks);
  armEntrances(blocks);

  // "PRICES CAPTURED <time> ET" in the shell strip, derived client-side
  // from the one capture instant this payload actually carries -- never a
  // seconds-level "updated N sec ago" (there is no age_seconds field here
  // at all to draw one from).
  const observed = (result.best_available_price && result.best_available_price.observed_utc)
    || (result.market_consensus && result.market_consensus.observed_utc) || null;
  const clock = et(observed);
  setShellStatus(clock ? `PRICES CAPTURED ${clock}` : null);
}

/* ---------------------------------------------------------------------
 * The ticket (sticky on desktop, a collapsing summary bar on mobile --
 * V2-24's own mobile note)
 * ------------------------------------------------------------------- */

function part(kind, labelText, inputEl) {
  const wrap = el("div", { class: `bc2-ticket__part bc2-ticket__part--${kind}` });
  wrap.appendChild(el("label", { for: inputEl.id, text: labelText }));
  wrap.appendChild(inputEl);
  return wrap;
}

export async function renderBetCheck(container, prefill = {}) {
  clear(container);
  const screen = el("div", { class: "screen bc2-screen", "data-view": "betcheck" });
  container.appendChild(screen);

  const layout = el("div", { class: "bc2-layout" });
  screen.appendChild(layout);

  /* ---- ticket ---------------------------------------------------- */
  const ticket = el("aside", { class: "bc2-ticket panel chamfer", "data-hook": "bet-check-form-host" });
  ticket.appendChild(el("span", { class: "tex-carbon" }));
  ticket.appendChild(el("div", { class: "bc2-ticket__eyebrow", text: "YOUR BET · MONEYLINE ONLY" }));

  const summary = el("div", { class: "bc2-ticket__summary", hidden: "" });
  const summaryText = el("span", { class: "bc2-ticket__summary-text" });
  const editBtn = el("button", { type: "button", class: "bc2-ticket__edit", text: "EDIT" });
  summary.appendChild(summaryText);
  summary.appendChild(editBtn);
  ticket.appendChild(summary);

  const form = el("form", { class: "bc2-ticket__form", "data-hook": "bet-check-form" });
  const field = el("div", { class: "bc2-ticket__field chamfer" });
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

  form.appendChild(el("button", { type: "submit", class: "btn btn--primary chamfer chamfer--btn bc2-ticket__submit",
    text: "CHECK IT" }));
  ticket.appendChild(form);

  const freeMeterHost = el("div", { class: "bc2-freemeter" });
  const authed = !!getToken();
  if (!authed) {
    renderFreeMeter(freeMeterHost, null);
    ticket.appendChild(freeMeterHost);
  }

  const foot = el("p", { class: "bc2-ticket__foot", text: "NO FRESHNESS FIGURE ON THIS PAYLOAD · CAPTURE IS HOURLY" });
  ticket.appendChild(foot);
  layout.appendChild(ticket);

  editBtn.addEventListener("click", () => {
    ticket.classList.remove("bc2-ticket--collapsed");
    summary.hidden = true;
  });

  /* ---- results host ------------------------------------------------ */
  const resultHost = el("div", { class: "bc2-results", "data-hook": "bet-check-result-host" });
  // Empty state: the ten-block skeleton is not drawn until a bet exists
  // (handoff section 10) -- a plain sentence, not a blank pane.
  const empty = el("div", { class: "bc2-empty chamfer", "data-hook": "bet-check-empty" }, [
    el("p", { class: "bc2-empty__title", text: "Paste a bet to begin." }),
    el("p", { class: "bc2-empty__body",
      text: "Fill in the game, the side and the price you are looking at. The ten-block check appears here." }),
  ]);
  resultHost.appendChild(empty);
  layout.appendChild(resultHost);

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
    resultHost.appendChild(renderLoading("CHECKING THIS BET"));

    // Mobile: the ticket collapses to a compact summary bar once a check
    // is in flight (V2-24's own mobile note) -- desktop stays untouched by
    // CSS (the collapsed modifier only takes visual effect at <=899px).
    summaryText.textContent = `${submitted.away} @ ${submitted.home} · ${submitted.side.toUpperCase()} `
      + `${formatAmerican(submitted.american_price) || ""}`;
    summary.hidden = false;
    ticket.classList.add("bc2-ticket--collapsed");

    // Signed in -> the paid path, untouched. Signed out -> the public
    // free path, so a visitor meets the product rather than a wall.
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
        renderFreeMeter(freeMeterHost, result && result.free_check ? result.free_check : null);
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
      renderError(resultHost, err);
      return;
    }
    renderResult(resultHost, result);
  });

  armEntrances(ticket);
}
