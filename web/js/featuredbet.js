/**
 * FEATURED BET -- the Tier A "bet standing" hero card (V2-32's body,
 * design/linehound-v2/'LINEHOUND V2 Full Product.dc.html' lines
 * 6999-7132: the price hero beneath "01 · THE BET"). Wave 0, Group F --
 * ONE shared definition three Wave-1 screens place as a slot, per
 * design/linehound-v2/IMPLEMENTATION_PLAN.md:
 *
 *   - Bet Check (web/js/betcheck.js), V2-32 block 01 -- replaces the
 *     current "01 YOUR BET" block's price panel with this card. TODO for
 *     that screen's owner: after POST /betcheck resolves, call
 *     `renderFeaturedBet(mountNode, mapBetCheckPayloadToStanding(payload,
 *     {verdict}), {})` where `mountNode` is block 01's body and `verdict`
 *     is that game's real verdict string if the screen already has it
 *     from another fetch (see "VERDICT" below -- POST /betcheck itself
 *     does not carry one).
 *   - Gameday (web/js/today.js), V2-33 carousel head -- TODO: same call,
 *     mounted at the carousel head's featured slot, once that screen has
 *     both a matched game and a Bet Check-shaped payload for it (e.g. by
 *     also calling POST /betcheck for the slate's featured game, or a
 *     future dedicated endpoint -- not decided here).
 *   - Game (web/js/games.js), V2-34 spotlight -- TODO: same call, mounted
 *     in the game spotlight panel.
 *
 * This module never fetches anything itself and never mutates anything
 * outside the container it is given -- it is a pure renderer over data
 * the caller already fetched, exactly like every other `renderX(host,
 * data)` view builder in this codebase.
 *
 * FIELDS BOUND -- ONLY THESE, ONLY FROM POST /betcheck's real shape
 * (docs/API_CONTRACTS.md's `POST /betcheck` section, verified against
 * src/analysis/contracts.py's BetCheckContract):
 *
 *   query.{raw,parsed,parse_error,market,price,line,side,team} -- BetQuery
 *   game.{away,home,start_time_utc}                            -- GameRef
 *   your_price_beats_consensus                                  -- bool|null
 *   price_improvement.{best,consensus,improvement_points,
 *                       improvement_return_pct,label}           -- PriceImprovement|null
 *   market_consensus.books                                      -- int, only when market_consensus present
 *   thesis_support.length / counterargument.length              -- real counts (NOT counterargument_lines,
 *                                                                  see SUPPORT VS CONCERN below)
 *   evidence_status                                              -- string|null
 *   best_available_price.observed_utc                           -- string|null
 *
 * FIELDS THE ARTBOARD SHOWS THAT THIS ENDPOINT DOES NOT HAVE -- rendered
 * as the artboard's own NOT AVAILABLE treatment, never invented, never
 * computed here (per this lane's boundary: "never invent a value, never
 * compute a probability, rating, rank or edge"):
 *
 *   1. PRICE STANDING ("Better than 9 of 11 books"). This needs the
 *      game's raw per-book board (one row per book) to count how many
 *      books the stated price beats. BetCheckContract carries no such
 *      array -- only `best_available_price` (ONE book) and
 *      `market_consensus` (an aggregate). Computing a "rank" from those
 *      two would mean either fabricating a count or silently redefining
 *      what "price standing" means (e.g. reducing it to a single
 *      best-price comparison) -- both refused. This segment renders NOT
 *      AVAILABLE unless the caller supplies `priceStanding` explicitly
 *      (reserved for a future join with the odds board's raw rows,
 *      which is an engineering request, not something this component
 *      does on its own).
 *   2. VERDICT (the oversized word -- "FLAGGED" in the artboard's own
 *      example). `no_play`/`flagged`/`market_unavailable` lives on the
 *      GAMES/TODAY payloads' `verdict` field, never on POST /betcheck's
 *      response (grepped: BetCheckContract has no `verdict` field at
 *      all). A caller that already knows this game's verdict from
 *      another fetch may pass it in; this component never fetches it
 *      and never guesses "no_play" as a default when it is absent --
 *      absent renders NOT AVAILABLE, not the majority case dressed up
 *      as a real answer.
 *
 * DELIBERATE DEVIATION FROM THE ARTBOARD'S "X OF 5 SEGMENTS MET" -- short
 * version: the artboard's own example dims the SUPPORT VS CONCERN
 * segment (0 thesis_support / 2 counterargument) despite it carrying
 * real, present data, which proves "met" there means "favourable", not
 * "has data". Computing a favourability verdict per segment (and
 * aggregating it into "N of 5") is exactly the kind of derived rating
 * this lane's boundary forbids. This component instead shows every
 * segment's REAL value (or NOT AVAILABLE with a reason) uniformly, with
 * only the verdict's own colour unifying the card (Reference Principle
 * #5, "state-driven accent") -- no per-segment pass/fail, no aggregate
 * count. Flagged for the orchestrator to confirm or override.
 *
 * DEVIATION FROM THE ARTBOARD'S RESERVED-COLOR USE -- the artboard paints
 * "FLAGGED" and its segment bars in the reserved hot-red/money family,
 * which conflicts with this codebase's own reserved-color rule stated
 * repeatedly elsewhere (tokens.css's V2 addendum; web/js/odds.js's
 * docstring: "hot red marks only a genuinely-best price ... never a
 * category or a warning") and with dom.js's own `verdictChipClass`
 * (flagged -> the cyan "live/analytical" treatment, not red). This
 * component follows the shipped `verdictChipClass` convention instead of
 * the artboard's pixels: no_play -> neutral, flagged -> cyan,
 * market_unavailable -> amber. Flagged for the orchestrator.
 *
 * COPY RULES ENFORCED HERE (never violate these -- tests/test_web_structure.py
 * and tests/test_customer_language.py's banned-vocabulary lists apply to
 * this file too):
 *   - `price_improvement` is always introduced with its own mandatory
 *     `label` string (line-shopping value; never "edge", never "EV").
 *   - `your_price_beats_consensus` is a decimal-payout comparison, never
 *     phrased as a probability or a prediction.
 *   - No numeral on this card is a rating, a probability, or a rank.
 */

import { el, clear, verdictLabel,
  formatAmerican, formatConsensusShare, formatEasternClock } from "./dom.js";
import { teamColors } from "./teamcolors.js";
import { teamName } from "./labels.js";

const MIN_BOOKS = 6; // src/analysis/prices.py's MIN_BOOKS -- the real consensus floor, repeated
                      // here only for the "above the N-book floor" caption, never re-derived as a check.

/* ---------------------------------------------------------------------
 * Pure mapper: raw POST /betcheck JSON -> this component's `standing`
 * shape. No DOM, no network -- safe for any Wave-1 caller to reuse so
 * three screens do not each hand-roll slightly different field
 * extraction (exactly the risk IMPLEMENTATION_PLAN.md's Group F note
 * calls out: "ONE definition, not copy-pasted").
 * ------------------------------------------------------------------- */

/** @param {object} payload  Raw JSON from POST /betcheck or /betcheck/free.
 *  @param {object} [extra]  Context this endpoint does not carry:
 *    - verdict: "no_play"|"flagged"|"market_unavailable"|null -- from a
 *      separate fetch of this same game (GET /games or GET /today), if
 *      the caller already has one. Never guessed.
 *    - priceStanding: {betterThan, total} -- from a future join with the
 *      raw per-book board. Never computed here.
 */
export function mapBetCheckPayloadToStanding(payload, extra = {}) {
  const p = payload || {};
  const query = p.query || null;
  const game = p.game || null;
  const priceImprovement = p.price_improvement ? {
    book: p.price_improvement.best && p.price_improvement.best.book,
    americanPrice: p.price_improvement.best && p.price_improvement.best.american_price,
    consensusImpliedProbability: p.price_improvement.consensus
      && p.price_improvement.consensus.implied_probability,
    improvementPoints: p.price_improvement.improvement_points,
    improvementReturnPct: p.price_improvement.improvement_return_pct,
    label: p.price_improvement.label,
  } : null;

  return {
    query: query ? {
      raw: query.raw, parsed: !!query.parsed, parseError: query.parse_error || null,
      market: query.market || null, price: typeof query.price === "number" ? query.price : null,
      line: typeof query.line === "number" ? query.line : null,
      side: query.side || null, team: query.team || null,
    } : null,
    game: game ? { away: game.away, home: game.home, firstPitchUtc: game.start_time_utc || null } : null,
    verdict: extra.verdict || null,
    priceStanding: extra.priceStanding || null,
    yourPriceBeatsConsensus: typeof p.your_price_beats_consensus === "boolean"
      ? p.your_price_beats_consensus : null,
    priceImprovement,
    boardDepthBooks: p.market_consensus && typeof p.market_consensus.books === "number"
      ? p.market_consensus.books : null,
    thesisSupportCount: Array.isArray(p.thesis_support) ? p.thesis_support.length : 0,
    // Raw `counterargument`, never `counterargument_lines` -- the lines
    // array is always padded to one placeholder string when empty (see
    // contracts.py's NO_COUNTERARGUMENTS_TEXT fallback, which the
    // constructor enforces unconditionally), so counting it would print
    // "1 counterargument" for a bet with zero.
    counterargumentCount: Array.isArray(p.counterargument) ? p.counterargument.length : 0,
    evidenceStatus: p.evidence_status || null,
    observedUtc: (p.best_available_price && p.best_available_price.observed_utc)
      || (p.market_consensus && p.market_consensus.observed_utc) || null,
  };
}

/* ---------------------------------------------------------------------
 * Verdict -> accent. See the long module-docstring comment on why this
 * follows dom.js's shipped `verdictChipClass` mapping rather than the
 * artboard's own (reserved-red) pixels.
 * ------------------------------------------------------------------- */

function verdictAccent(verdict) {
  if (verdict === "flagged") return "live";
  if (verdict === "market_unavailable") return "warn";
  if (verdict === "no_play") return "neutral";
  return null; // absent -- NOT AVAILABLE, never defaulted to "neutral" as if it were a real no_play answer
}

/* ---------------------------------------------------------------------
 * Small building blocks
 * ------------------------------------------------------------------- */

function notAvailable(reason) {
  const wrap = el("span", { class: "fb-na", "data-hook": "fb-not-available" });
  wrap.appendChild(el("span", { class: "fb-na__chip", text: "NOT AVAILABLE" }));
  if (reason) wrap.appendChild(el("span", { class: "fb-na__reason", text: reason }));
  return wrap;
}

function specCell(label, valueNode) {
  const cell = el("div", { class: "fb-spec__cell" });
  cell.appendChild(el("div", { class: "fb-spec__label", text: label }));
  cell.appendChild(el("div", { class: "fb-spec__value" }, [valueNode]));
  return cell;
}

/** One of the five named, checkable rows -- always the same five, in the
 * same order, per V2-32's body. `present` distinguishes "this segment has
 * a real value to show" from "NOT AVAILABLE", and is the ONLY thing that
 * changes the marker's fill -- never a favourability judgement (see
 * module docstring). */
function segmentRow({ label, present, node, hook }) {
  const row = el("div", { class: `fb-row${present ? " fb-row--present" : " fb-row--absent"}`,
    "data-hook": hook });
  row.appendChild(el("span", { class: "fb-row__mark", "aria-hidden": "true" }));
  row.appendChild(el("span", { class: "fb-row__label", text: label }));
  row.appendChild(el("span", { class: "fb-row__detail" }, [node]));
  return row;
}

function trustItem(label, sub) {
  return el("div", { class: "fb-trust__item" }, [
    el("span", { class: "fb-trust__label", text: label }),
    el("span", { class: "fb-trust__sub", text: sub }),
  ]);
}

/* ---------------------------------------------------------------------
 * Main render
 * ------------------------------------------------------------------- */

/** Mounts the Featured Bet card into `container` (a slot the calling
 * screen owns -- see the TODOs in the module docstring for where each
 * Wave-1 screen places it). Clears `container` first, like every other
 * `renderX(container, ...)` builder in this codebase.
 *
 * @param {HTMLElement} container
 * @param {object} standing  See `mapBetCheckPayloadToStanding` above for
 *   the exact shape, or build one by hand for a fixture/test.
 * @param {object} [opts]  Reserved for future use (e.g. an id prefix for
 *   more than one card on a page); currently unused.
 */
export function renderFeaturedBet(container, standing, opts = {}) {
  clear(container);
  const s = standing || {};

  const accent = verdictAccent(s.verdict);
  const card = el("article", {
    class: `fb-card panel chamfer${accent ? ` fb-card--${accent}` : " fb-card--na"}`,
    "data-hook": "featured-bet", "data-verdict": s.verdict || "unavailable",
  });
  container.appendChild(card);

  // Could-not-parse: the query itself failed, so none of the derived
  // fields below would exist either. Render the honest-absence panel and
  // stop -- never guess at a market/line/side the parser could not read.
  if (!s.query || !s.query.parsed) {
    card.appendChild(el("div", { class: "fb-parsefail", "data-hook": "fb-parse-failed" }, [
      el("span", { class: "fb-parsefail__label", text: "COULD NOT READ THIS BET" }),
      el("p", { class: "fb-parsefail__raw", text: (s.query && s.query.raw) || "" }),
      el("p", { class: "fb-parsefail__reason",
        text: (s.query && s.query.parseError) || "No reason given." }),
    ]));
    return;
  }

  const marketLabel = s.query.market ? String(s.query.market).toUpperCase() : null;

  // ---- spine (rotated label) -------------------------------------
  card.appendChild(el("div", { class: "fb-spine", "aria-hidden": "true" },
    [el("span", { text: marketLabel || "BET" })]));

  // ---- head: team badge + matchup + first pitch -------------------
  const head = el("div", { class: "fb-head" });
  const sideAbbr = s.query.team
    || (s.query.side === "home" ? (s.game && s.game.home)
      : s.query.side === "away" ? (s.game && s.game.away)
      : null)
    || null;
  if (sideAbbr) {
    const colors = teamColors(sideAbbr);
    const badge = el("span", { class: "fb-badge", "aria-hidden": "true", text: sideAbbr });
    badge.style.background = colors.known ? colors.primary : "#232830";
    badge.style.color = colors.known ? colors.accent : "#D5D7DE";
    head.appendChild(badge);
  }
  if (s.game && s.game.away && s.game.home) {
    head.appendChild(el("span", { class: "fb-matchup", text: `${s.game.away} @ ${s.game.home}` }));
  }
  const firstPitch = s.game && formatEasternClock(s.game.firstPitchUtc);
  if (firstPitch) head.appendChild(el("span", { class: "fb-clock", text: `${firstPitch} ET` }));
  card.appendChild(head);

  // ---- spec strip: MARKET | LINE | SIDE ---------------------------
  const spec = el("div", { class: "fb-spec" });
  spec.appendChild(specCell("MARKET", marketLabel
    ? el("span", { text: marketLabel }) : notAvailable()));
  spec.appendChild(specCell("LINE", typeof s.query.price === "number"
    ? el("span", { text: formatAmerican(s.query.price) }) : notAvailable()));
  const sideLabel = sideAbbr ? (teamName(sideAbbr, "full") || sideAbbr) : null;
  spec.appendChild(specCell("SIDE", sideLabel
    ? el("span", { class: "fb-spec__pill", text: sideLabel.toUpperCase() })
    : notAvailable("no side singled out for this bet")));
  card.appendChild(spec);

  // ---- BET STANDING · TIER A --------------------------------------
  const standingHead = el("div", { class: "fb-standinghead" });
  const axis = el("div", { class: "fb-axis" });
  axis.appendChild(el("div", { class: "fb-axis__label", text: "BET STANDING · TIER A" }));
  axis.appendChild(el("div", { class: "fb-axis__scale",
    text: "THIN → WELL-SUPPORTED" }));
  standingHead.appendChild(axis);
  const verdictBox = el("div", { class: "fb-verdict" });
  if (s.verdict) {
    verdictBox.appendChild(el("div", { class: "fb-verdict__word", "data-hook": "fb-verdict",
      text: verdictLabel(s.verdict) }));
  } else {
    verdictBox.appendChild(notAvailable("this endpoint does not carry a verdict for the checked bet"));
  }
  standingHead.appendChild(verdictBox);
  card.appendChild(standingHead);

  // ---- five named segments, exactly as V2-32 specifies ------------
  const segments = el("div", { class: "fb-segments" });

  segments.appendChild(segmentRow({
    label: "PRICE STANDING", hook: "fb-segment-price-standing",
    present: !!s.priceStanding,
    node: s.priceStanding
      ? el("span", { text: `Better than ${s.priceStanding.betterThan} of ${s.priceStanding.total} books` })
      : notAvailable("requires the full per-book board; POST /betcheck does not return one"),
  }));

  segments.appendChild(segmentRow({
    label: "BEATS CONSENSUS", hook: "fb-segment-beats-consensus",
    present: s.yourPriceBeatsConsensus !== null && s.yourPriceBeatsConsensus !== undefined,
    node: (s.yourPriceBeatsConsensus === null || s.yourPriceBeatsConsensus === undefined)
      ? notAvailable("no priceable consensus for this side")
      : el("span", { text: `your_price_beats_consensus = ${s.yourPriceBeatsConsensus}` }),
  }));

  segments.appendChild(segmentRow({
    label: "IMPROVEMENT", hook: "fb-segment-improvement",
    present: !!s.priceImprovement,
    node: s.priceImprovement ? (() => {
      const wrap = el("span", {});
      const pts = typeof s.priceImprovement.improvementPoints === "number"
        ? `${s.priceImprovement.improvementPoints >= 0 ? "+" : ""}${(s.priceImprovement.improvementPoints * 100).toFixed(2)} pts` : null;
      const book = s.priceImprovement.book;
      const bookPrice = formatAmerican(s.priceImprovement.americanPrice);
      const consensusPct = formatConsensusShare(s.priceImprovement.consensusImpliedProbability);
      const bits = [];
      if (pts) bits.push(pts);
      if (bookPrice) bits.push(`best ${bookPrice}${book ? ` (${book})` : ""}`);
      if (consensusPct) bits.push(`vs de-vigged consensus ${consensusPct}`);
      wrap.textContent = bits.length ? bits.join(" ") : "present, no figures to show";
      return wrap;
    })() : notAvailable("no priceable consensus for this side"),
  }));

  segments.appendChild(segmentRow({
    label: "BOARD DEPTH", hook: "fb-segment-board-depth",
    present: typeof s.boardDepthBooks === "number",
    node: typeof s.boardDepthBooks === "number"
      ? el("span", { text: `${s.boardDepthBooks} books, above the ${MIN_BOOKS}-book floor` })
      : notAvailable("no consensus on this board (below the floor, or no board)"),
  }));

  segments.appendChild(segmentRow({
    label: "SUPPORT VS CONCERN", hook: "fb-segment-support-concern",
    present: true, // thesis_support / counterargument are structurally always present, even when empty
    node: el("span", { text: `${s.thesisSupportCount} thesis_support / ${s.counterargumentCount} counterargument` }),
  }));

  if (s.priceImprovement && s.priceImprovement.label) {
    segments.appendChild(el("p", { class: "fb-improvement-label", "data-hook": "fb-improvement-label",
      text: s.priceImprovement.label }));
  }

  card.appendChild(segments);

  // ---- trust strip --------------------------------------------------
  const trust = el("div", { class: "fb-trust" });
  trust.appendChild(trustItem(
    typeof s.boardDepthBooks === "number" ? `${s.boardDepthBooks} BOOKS COMPARED` : "BOOKS COMPARED: NOT AVAILABLE",
    "Board depth behind the read"));
  const captured = formatEasternClock(s.observedUtc);
  trust.appendChild(trustItem(
    captured ? `CAPTURED ${captured} ET` : "CAPTURED: NOT AVAILABLE",
    "Hourly, never streamed"));
  trust.appendChild(trustItem(
    s.evidenceStatus ? s.evidenceStatus.toUpperCase() : "EVIDENCE STATUS: NOT AVAILABLE",
    "Max evidence tier today"));
  card.appendChild(trust);
}
