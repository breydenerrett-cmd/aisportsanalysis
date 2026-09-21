/**
 * THE CARD (GET /card/{date}) -- tonight's three to five bets, at the very
 * top of Gameday, in the plainest English this product can manage.
 *
 * WHY IT LOOKS LIKE THIS
 * ----------------------
 * The owner's note on 2026-09-10, verbatim in substance: the slate board
 * looks like a lot of random numbers, nobody knows what "de-vig" means, and
 * if the game is Nationals-Padres there needs to be a bet that says take the
 * Padres. So every card here leads with ONE sentence in the imperative --
 * "Take Padres -1.5 at -140" -- and everything else is underneath it, in
 * order of how much a reader has to care.
 *
 * There is no jargon in the customer-visible strings of this file. Not
 * "de-vig", not "consensus", not "expected value", not "closing line", not
 * "basis points". The server composes the sentences (src/analysis/
 * daily_card.py) so the frozen ledger and the page say the same words; this
 * module lays them out and adds nothing.
 *
 * WHAT IT WILL NOT DO
 * -------------------
 * It never renders an empty state that describes OUR confidence. The
 * payload's `reason` is always a fact about the world -- no games, all
 * started, no prices yet -- and it is rendered verbatim. The sentence
 * "nothing clears the bar" cannot appear on this surface, and
 * tests/test_no_nothing_clears_the_bar.py enforces that across all of web/.
 *
 * It also never hides the DISAGREEMENT. A pick our own model disagrees with
 * is on the card because the slate was thin, and it says so on its own face.
 *
 * CORRECTED 2026-09-17: this paragraph used to promise the reader "still
 * sees the word" SPLIT. D1 removed the STRONG/LEAN/SPLIT chips from the
 * card's face on purpose -- they were driven by MARKET confidence, so a
 * short-priced favourite wore the same badge as real value -- and the
 * promise was left behind, describing a page that no longer exists. The
 * DISCLOSURE survives and is what actually matters: the thin-slate sentence
 * still states plainly that our numbers do not agree with the market on
 * those picks. The label's explanatory copy remains inside the breakdown.
 */

import { apiGet } from "./api.js";
import { el, renderError, formatAmerican, formatEasternTime } from "./dom.js";
import { bookLabel } from "./labels.js";
import { experimentalNotice, disclosure, chip } from "./layout.js";
import { NFL_RETIRED_RULE } from "./sport.js";

// Mirrors src/analysis/daily_card.py's labels. Kept as a lookup rather than
// rendered raw so the page controls its own typography, and so a label the
// server adds later renders as itself instead of breaking the layout.
const LABEL_TONE = {
  STRONG: "strong",
  LEAN: "lean",
  SLIGHT: "slight",
  SPLIT: "split",
};

const LABEL_MEANING = {
  STRONG: "The market and our numbers both make this side a clear favourite.",
  LEAN: "The market and our numbers both favour this side, without much in it.",
  SLIGHT: "Close to a coin flip. Both reads point the same way, barely.",
  SPLIT: "Our numbers do not agree with the market here. It is on the card "
       + "because tonight's slate was thin, and you should weigh it lower.",
};

// Four hours is roughly how long a major-league moneyline holds its shape
// on a quiet board. Past that a reader quoting our number at a book is
// likely to find a different one.
const STALE_PRICE_HOURS = 4;

// Below this many graded picks, a sport's win rate or ROI is noise dressed
// as a track record -- recordLine() shows the raw count and units instead
// of a percentage for sports below this floor. NFL published and graded
// its first pick on 2026-09-17 (n=1 today); this floor is a round,
// conservative number, not derived from that one pick.
const NFL_SAMPLE_FLOOR = 10;

/** How long the last-published-card fallback may hold up the page.
 *
 * Much shorter than api.js's DEFAULT_TIMEOUT_MS, and deliberately so: this
 * request is a courtesy, not the page. It runs inside the render path, so
 * every second it spends is a second of blank screen. If it cannot answer
 * quickly the honest empty state is better than a longer wait for a nicer
 * one. */
const FALLBACK_TIMEOUT_MS = 5000;

/** Hours since an ISO timestamp, or null if it cannot be read. */
function hoursSince(iso) {
  if (!iso) return null;
  const then = Date.parse(String(iso).replace(" ", "T"));
  if (Number.isNaN(then)) return null;
  return Math.max((Date.now() - then) / 3600000, 0);
}

// Mirrors card_ledger.LOCK_LEAD_HOURS (src/appstate/card_ledger.py) -- a
// pick locks four hours before its own first pitch. The server does not
// hand this number over the wire, so it is kept here, named against its
// source, the same way STALE_PRICE_HOURS above already mirrors a server
// constant rather than guessing at one.
const LOCK_LEAD_HOURS = 4;

/** A whole-percent string from a 0-1 fraction, or null. Never invents a
 * number for a missing probability -- the caller must not render this
 * line at all when the underlying figure is absent. */
function pct0(fraction) {
  if (typeof fraction !== "number" || !Number.isFinite(fraction)) return null;
  return `${Math.round(fraction * 100)}%`;
}

/** The win rate an American price needs to break even, as a whole percent.
 * Arithmetic on the stated price alone (the same de-vig-free formula
 * landing-live.js's own breakevenPct uses) -- not a fabricated number, the
 * price's own implied probability. */
function breakevenPct(price) {
  const n = Number(price);
  if (!Number.isFinite(n) || n === 0) return null;
  const p = n < 0 ? Math.abs(n) / (Math.abs(n) + 100) : 100 / (n + 100);
  return Math.round(p * 100);
}

/** Word chips naming the real conditions behind a pick -- never a claim
 * about our confidence, only facts the payload actually carries.
 * `pick.knowledge.core` (game/total picks, src/analysis/grade.py) names
 * whether lineups and starters were in when the pick was frozen;
 * `pick.lineup_posted` (prop picks) is the same fact under its own name.
 * The lock state reads `pick.locked` and the first-pitch clock against
 * LOCK_LEAD_HOURS -- never a guess, since a pick that has not locked yet
 * really can still move. */
function conditionChips(pick) {
  const chips = [];
  const core = pick.knowledge && pick.knowledge.core;
  if (core) {
    chips.push(core.lineups
      ? chip("Lineup posted", "confirmed")
      : chip("Lineup not posted", "waiting"));
    chips.push(core.starters
      ? chip("Starters confirmed", "confirmed")
      : chip("Starter unconfirmed", "waiting"));
  }
  // A prop's own `lineup_posted === false` gets the fuller, named-detail
  // sentence (`lineupNotPostedWarning`, above the bet line) rather than a
  // bare chip here -- see that function's own comment for why the detail
  // (season-average plate appearances, not tonight's order) has to survive
  // as prose, not a three-word tag.

  if (pick.locked) {
    chips.push(chip("Locked", "neutral"));
  } else if (pick.first_pitch_utc) {
    const hoursLeft = hoursUntil(pick.first_pitch_utc);
    if (hoursLeft !== null && hoursLeft <= LOCK_LEAD_HOURS) {
      // Past the lock cutoff but not yet stamped locked -- the gap between
      // a publish run passing the cutoff and the next one stamping it.
      chips.push(chip("Lock pending · graded as published", "neutral"));
    } else if (hoursLeft !== null) {
      chips.push(chip(`Provisional until ${formatEasternTime(
        new Date(Date.parse(pick.first_pitch_utc) - LOCK_LEAD_HOURS * 3600000).toISOString()
      )}`, "neutral"));
    }
  }
  return chips;
}

/** Hours from now until an ISO timestamp, or null if it cannot be read.
 * The mirror of `hoursSince` above, for a first-pitch clock still ahead of
 * us rather than behind. */
function hoursUntil(iso) {
  if (!iso) return null;
  const then = Date.parse(String(iso).replace(" ", "T"));
  if (Number.isNaN(then)) return null;
  return (then - Date.now()) / 3600000;
}

/** Whether a card carries probabilities of its own (2026-09-20).
 * NFL_CARD_V2 prices every pick off the market's own consensus -- there is
 * no model, so nothing of ours can be miscalibrated or disagree with the
 * market -- and its payload says so with `has_model: false`
 * (src/report/nfl_card.py). A live V2 card used to tell readers "Our own
 * probabilities are running uncalibrated", which was false. MLB never
 * sends the key, so every MLB card reads as having its model, exactly as
 * before. */
function cardHasOwnModel(payload) {
  return !(payload && payload.has_model === false);
}

/** The "View breakdown" body every kind of pick shares: what the market
 * says, what our own number says, what the price needs, the rest of the
 * why (why[0] already sits above, unsplit), the alternate bet for a game
 * pick, and the knowledge grade with its served legend. Every figure here
 * is a real payload field or plain arithmetic on one -- nothing here is
 * invented to fill a box. `hasModel: false` drops "Our number" (see
 * cardHasOwnModel); `sport` decides whether the matchup link applies. */
function breakdownBody(pick, { ourLabel = "Our number", showAlternative = false, payload,
                               sport = null, hasModel = true } = {}) {
  const nodes = [];
  const figures = el("div", { class: "card2bd__figures" });
  const market = pct0(pick.market_probability);
  if (market !== null) {
    figures.appendChild(el("p", { class: "card2bd__figure",
      text: `Market says ${market}` }));
  }
  const ours = hasModel
    ? pct0(typeof pick.probability === "number" ? pick.probability : pick.model_probability)
    : null;
  if (ours !== null) {
    figures.appendChild(el("p", { class: "card2bd__figure",
      text: `${ourLabel} ${ours}` }));
  }
  const needs = typeof pick.breakeven === "number" ? pct0(pick.breakeven) : breakevenPct(pick.price);
  if (needs !== null && pick.price !== undefined) {
    figures.appendChild(el("p", { class: "card2bd__figure",
      text: `Needs ${needs}% to break even at ${formatAmerican(pick.price)}` }));
  }
  if (figures.childNodes.length) nodes.push(figures);

  for (const sentence of (pick.why || []).slice(1)) {
    nodes.push(el("p", { class: "card2bd__why", text: sentence }));
  }

  if (showAlternative && pick.alternative && pick.alternative.bet) {
    const alt = el("div", { class: "card2__alt", "data-hook": "card-alternative" });
    alt.appendChild(el("span", { class: "card2__alt-label", text: "OR" }));
    const body = el("div", { class: "card2__alt-body" });
    body.appendChild(el("span", { class: "card2__alt-bet", text: pick.alternative.bet }));
    if (pick.alternative.book) {
      body.appendChild(el("span", { class: "card2__alt-book",
        text: bookLabel(pick.alternative.book) || pick.alternative.book }));
    }
    alt.appendChild(body);
    nodes.push(alt);
  }

  const knowledge = pick.knowledge || null;
  if (knowledge && knowledge.grade) {
    const gradeRow = el("div", { class: "card2bd__grade" });
    gradeRow.appendChild(el("span", {
      class: `card2__grade card2__grade--${String(knowledge.letter || "").toLowerCase()}`,
      "data-hook": "card-grade",
      title: knowledge.why || "",
      text: knowledge.grade,
    }));
    gradeRow.appendChild(el("span", { class: "card2bd__grade-why", text: knowledge.why || "" }));
    nodes.push(gradeRow);
    for (const line of (payload && payload.knowledge_legend) || []) {
      nodes.push(el("p", { class: "card2note__body card2note__body--mute",
        "data-hook": "card-grade-legend", text: line }));
    }
  }

  // MLB ONLY (2026-09-20). #/game/{date}/{away}/{home} is MLB's game page
  // and looks the teams up in MLB's schedule; an NFL pick's link opened it
  // and got a 404 ("no game found") under MLB's menu. NFL has no game page
  // yet, so its picks carry no link rather than a dead one. `pick.sport`
  // rides every NFL pick (V1 and V2); MLB picks carry none.
  const pickSport = sport || pick.sport || "mlb";
  const gameDate = pick.date || (pick.first_pitch_utc ? String(pick.first_pitch_utc).slice(0, 10) : null);
  if (pickSport === "mlb" && gameDate && pick.away_team && pick.home_team) {
    nodes.push(el("a", { class: "btn btn--text", "data-hook": "card-open-matchup",
      href: `#/game/${encodeURIComponent(gameDate)}/${encodeURIComponent(pick.away_team)}/${encodeURIComponent(pick.home_team)}`,
      text: "Open this matchup" }));
  }
  return nodes;
}

function sectionHead(label, meta) {
  const head = el("div", { class: "sechead" });
  head.appendChild(el("span", { class: "sechead__label", text: label }));
  head.appendChild(el("span", { class: "sechead__hair" }));
  if (meta) head.appendChild(el("span", { class: "sechead__meta", text: meta }));
  return head;
}

/** One pick, in the compact anatomy: rank · away at home · local first
 * pitch; the instruction sentence; price at book · published time; the
 * conditions behind it as word chips; the first reason sentence; then
 * "View breakdown" for everything else -- the market number, our number,
 * what the price needs, the rest of the reasoning, the alternate bet and
 * the knowledge grade. Nothing here is invented; every figure comes from
 * `pick` or `payload` as served.
 *
 * `compactPickCard` is the one export other screens (landing-live.js) use;
 * `pickCard` stays the name this file's own render path and tests call.
 */
export function compactPickCard(pick, opts = {}) {
  const { total = 1, payload = null, kindTag = null, sport = null } = opts;
  const hasModel = opts.hasModel !== undefined ? opts.hasModel : cardHasOwnModel(payload);
  const tone = LABEL_TONE[pick.label] || "slight";
  const rank1 = (pick.position || pick.rank) === 1;
  const card = el("article", {
    class: `card2 panel chamfer card2--${tone}${rank1 ? " card2--rank1" : ""}`,
    "data-hook": "card-pick",
    "data-rank": String(pick.rank || ""),
    "data-label": pick.label || "",
    "data-market": pick.market || "",
  });

  const top = el("div", { class: "card2__top" });
  // `position` is where this pick sits on the card being served; `rank` is
  // the slot it was frozen in. They differ on a card assembled through the
  // day -- picks lock against their own first pitch and keep their frozen
  // rank, so a nine-pick card carried ranks [3,2,3,1,2,4,5,5,4] and the
  // page printed "3 OF 9" twice (2026-09-11). The server orders and numbers;
  // this only prints.
  top.appendChild(el("span", { class: "card2__rank",
    text: `#${pick.position || pick.rank} · ${pick.away_team} at ${pick.home_team}`
        + `${pick.first_pitch_utc ? ` · ${formatEasternTime(pick.first_pitch_utc) || ""}` : ""}` }));
  if (kindTag) top.appendChild(kindTag);
  card.appendChild(top);

  // THE SENTENCE. Server-composed, rendered verbatim, and the largest thing
  // on the card.
  card.appendChild(el("p", { class: "card2__bet", "data-hook": "card-bet",
    text: pick.bet || "" }));

  if (pick.book) {
    card.appendChild(el("p", { class: "card2__book",
      text: `${formatAmerican(pick.price)} at ${bookLabel(pick.book) || pick.book}`
          + `${pick.published_utc ? ` · published ${formatEasternTime(pick.published_utc) || ""}`
             : pick.observed_utc ? ` · published ${formatEasternTime(pick.observed_utc) || ""}` : ""}`
          + `${pick.books ? ` · best of ${pick.books} books` : ""}` }));
  }

  // THE ONE REASON SENTENCE. why[0], rendered whole and never split
  // client-side -- the rest of `pick.why` moves into the breakdown below.
  const firstWhy = (pick.why || [])[0];
  if (firstWhy) {
    card.appendChild(el("p", { class: "card2__whyline card2__whyline--lead",
      "data-hook": "card-why", text: firstWhy }));
  }

  // CONDITION CHIPS, under the reason line -- outside "View breakdown" so
  // the real facts behind a pick (lineup posted, starters confirmed, lock
  // state) are visible without a tap.
  const chipsRow = conditionChips(pick);
  if (chipsRow.length) {
    const chipsWrap = el("div", { class: "card2__chips", "data-hook": "card-conditions" });
    for (const c of chipsRow) chipsWrap.appendChild(c);
    card.appendChild(chipsWrap);
  }

  card.appendChild(disclosure({
    summary: "View breakdown",
    id: `card-breakdown-${pick.game_pk || pick.event_id || pick.rank || Math.random().toString(36).slice(2)}`,
    body: breakdownBody(pick, { showAlternative: true, payload, sport, hasModel }),
  }));

  return card;
}

/** Legacy name this file's own render path and tests call -- see
 * `compactPickCard`, the one implementation. `extra` carries the card's
 * `sport` and `hasModel` (2026-09-20) -- never the payload itself, which
 * would add the grade legend to every breakdown on this path and change
 * MLB's page. */
function pickCard(pick, total, extra = {}) {
  return compactPickCard(pick, { total, ...extra });
}

/* -----------------------------------------------------------------------
 * PLAYER PROPS ON THE CARD, 2026-09-12.
 *
 * The owner's note this morning, verbatim in substance: the card is
 * moneyline-first by rule, and it was "still showing ML's" -- so the
 * likeliest player props that also clear their price join it here, as
 * frozen, graded picks. Same card2 shell the game picks use, same rules
 * (probability before price, no verdict language) -- see this module's own
 * docstring and src/analysis/daily_card.select_props, which is the one
 * place the selection itself happens. This file only lays out what that
 * function already decided.
 *
 * NO CHECK THIS PRICE LINK. Bet Check only ever checked a moneyline
 * (src/analysis/betcheck.py reads game-level markets), so pointing a prop
 * pick at it would send a reader to a page that cannot answer about their
 * bet. The action here goes to the prop board instead (#/props), which
 * carries every price this pick could be checked against.
 * -------------------------------------------------------------------- */

/** "PLAYER PROPS", plus the one-line sub-heading explaining the ordering
 * rule in the reader's own words -- never rendered without at least one
 * of a pick list or a reason under it (see the caller in `renderCard`).
 *
 * `servingOlderDate` carries the same fact the game-picks head already
 * acts on (renderCard's `servingOlderCard`): when set, `payload` -- and so
 * every prop pick under this heading -- came from an earlier slate's
 * frozen card, not tonight's. A checker caught the sub-head saying
 * "tonight" over picks whose own first_pitch_utc was a prior day, twelve
 * lines below a game-picks head that had already switched off "TONIGHT'S"
 * for the same reason (2026-09-12). Dropping "tonight" here keeps the two
 * headings telling the same story about which night this is. */
function propSectionHead(servingOlderDate, withSubhead = true) {
  const wrap = el("div", { "data-hook": "card-prop-divider" });
  wrap.appendChild(sectionHead("PLAYER PROPS"));
  // No sub-heading over an EMPTY section (2026-09-12, seen on the local
  // build of today's frozen card): "The likeliest props tonight that also
  // clear their price" sat directly above "Player props were not part of
  // this card when it was frozen." The sub-heading describes picks; when
  // the only line under the head is the reason there are none, the head
  // alone is the honest amount of framing.
  if (!withSubhead) return wrap;
  // Two literal branches, not a ternary inside `text:` -- kept this shape
  // (same as the frozen/live ledes above) so each sentence still starts
  // right at `text: "` for the register sweep to find, the way this file's
  // own scanning convention requires (test_web_card_props.py's
  // EveryRenderedStringPassesTheRegisterSweep). A ternary value handed to
  // `text:` -- `text: subhead` -- would be a variable like sectionHead's
  // own `label`, invisible to that scan.
  if (servingOlderDate) {
    wrap.appendChild(el("p", { class: "card2lede card2lede--mute",
      "data-hook": "card-prop-subhead",
      text: "The likeliest props that night that also cleared their price. "
          + "Ranked by how strongly the market favoured each, never by the price." }));
  } else {
    wrap.appendChild(el("p", { class: "card2lede card2lede--mute",
      "data-hook": "card-prop-subhead",
      text: "The likeliest props tonight that also clear their price. "
          + "Ranked by how strongly the market favours each, never by the price." }));
  }
  return wrap;
}

/** "Rafael Devers · BOS · KC at BOS · FanDuel · best of 7 books" -- one
 * line, everything a reader needs to place the bet against a real matchup,
 * in the order a person would say it. */
function propMetaLine(pick) {
  const bits = [];
  if (pick.player) bits.push(pick.player);
  if (pick.team) bits.push(pick.team);
  if (pick.away_team && pick.home_team) bits.push(`${pick.away_team} at ${pick.home_team}`);
  if (pick.book) bits.push(bookLabel(pick.book) || pick.book);
  if (pick.books) bits.push(`best of ${pick.books} books`);
  return bits.join(" · ");
}

/** One player-prop pick, in the same card2 shell as `pickCard` above --
 * "N OF M" counts against the OTHER prop picks on the card, never mixed
 * with the game picks' own count. `servingOlderDate` sends the board link
 * to that same earlier date (#/props/<date>, routed in main.js) instead of
 * tonight's board, which would show different games than the ones these
 * picks were frozen against. */
function propPickCard(pick, total, servingOlderDate) {
  const tone = LABEL_TONE[pick.label] || "slight";
  const rank1 = (pick.position || pick.rank || 1) === 1;
  const card = el("article", {
    class: `card2 panel chamfer card2--${tone}${rank1 ? " card2--rank1" : ""}`,
    "data-hook": "card-prop-pick",
    "data-rank": String(pick.position || pick.rank || ""),
    "data-label": pick.label || "",
    "data-market": pick.market || "",
  });

  const top = el("div", { class: "card2__top" });
  top.appendChild(el("span", { class: "card2__rank",
    text: `#${pick.position || pick.rank || 1} · ${propMetaLine(pick)}` }));
  card.appendChild(top);

  // THE SENTENCE. Server-composed, same as the game picks' own bet line.
  card.appendChild(el("p", { class: "card2__bet", "data-hook": "card-prop-bet",
    text: pick.bet || "" }));

  if (pick.book) {
    card.appendChild(el("p", { class: "card2__book",
      text: `${formatAmerican(pick.price)} at ${bookLabel(pick.book) || pick.book}`
          + `${pick.observed_utc ? ` · published ${formatEasternTime(pick.observed_utc) || ""}` : ""}`
          + `${pick.books ? ` · best of ${pick.books} books` : ""}` }));
  }

  const firstWhy = (pick.why || [])[0];
  if (firstWhy) {
    card.appendChild(el("p", { class: "card2__whyline card2__whyline--lead",
      "data-hook": "card-prop-why", text: firstWhy }));
  }

  const chipsRow = conditionChips(pick);
  if (chipsRow.length) {
    const chipsWrap = el("div", { class: "card2__chips", "data-hook": "card-conditions" });
    for (const c of chipsRow) chipsWrap.appendChild(c);
    card.appendChild(chipsWrap);
  }

  const boardLink = el("a", { class: "btn btn--text", "data-hook": "card-prop-board-link",
    href: servingOlderDate ? `#/props/${servingOlderDate}` : "#/props",
    text: "SEE THE PROP BOARD" });

  card.appendChild(disclosure({
    summary: "View breakdown",
    id: `card-prop-breakdown-${pick.game_pk || pick.player || pick.rank || Math.random().toString(36).slice(2)}`,
    body: [...breakdownBody(pick, { ourLabel: "Our number" }), boardLink],
  }));
  return card;
}

/* -----------------------------------------------------------------------
 * TOTALS ON THE CARD, 2026-09-14.
 *
 * The owner's note today, verbatim in substance: merge the card for ALL
 * bets, not just moneylines -- run lines, totals and the rest, whenever
 * their own analysis is ready, no fixed time of day for any one market.
 * `payload.total_picks` is the run-line/moneyline-shaped sibling of
 * `prop_picks`: same frozen, graded picks, same card2 shell, read from a
 * game-level market instead of a per-player one.
 * -------------------------------------------------------------------- */

/** Bet Check (POST /betcheck, api/betcheck.py's `BetCheckRequest`) validates
 * `side: Literal["away", "home"]` -- there is no totals shape on that
 * endpoint at all, checked directly against the source rather than
 * assumed. A total card gets no CHECK THIS PRICE link while this stays
 * false; flip it the day that endpoint grows a totals body and
 * `totalPickCard` picks the link back up on its own. */
const BETCHECK_SUPPORTS_TOTALS = false;

/** One total pick, in the same card2 shell as `pickCard` -- a total is a
 * game-level bet like a moneyline, not a per-player bet like a prop, so it
 * gets the same "AWAY at HOME · Book" matchup line `pickCard` uses rather
 * than `propPickCard`'s player-first meta line. "N OF M" counts against
 * the OTHER total picks on the card, never mixed with the game picks' or
 * the props' own count -- same convention `propPickCard` already follows. */
function totalPickCard(pick, total) {
  const tone = LABEL_TONE[pick.label] || "slight";
  const rank1 = (pick.position || pick.rank || 1) === 1;
  const card = el("article", {
    class: `card2 panel chamfer card2--${tone}${rank1 ? " card2--rank1" : ""}`,
    "data-hook": "card-total-pick",
    "data-rank": String(pick.position || pick.rank || ""),
    "data-label": pick.label || "",
    "data-market": pick.market || "",
  });

  const top = el("div", { class: "card2__top" });
  top.appendChild(el("span", { class: "card2__rank",
    text: `#${pick.position || pick.rank || 1} · ${pick.away_team} at ${pick.home_team}`
        + `${pick.first_pitch_utc ? ` · ${formatEasternTime(pick.first_pitch_utc) || ""}` : ""}` }));
  card.appendChild(top);

  // THE SENTENCE. Server-composed, same as the game picks' own bet line.
  card.appendChild(el("p", { class: "card2__bet", "data-hook": "card-total-bet",
    text: pick.bet || "" }));

  if (pick.book) {
    card.appendChild(el("p", { class: "card2__book",
      text: `${formatAmerican(pick.price)} at ${bookLabel(pick.book) || pick.book}`
          + `${pick.observed_utc ? ` · published ${formatEasternTime(pick.observed_utc) || ""}` : ""}`
          + `${pick.books ? ` · best of ${pick.books} books` : ""}` }));
  }

  const firstWhy = (pick.why || [])[0];
  if (firstWhy) {
    card.appendChild(el("p", { class: "card2__whyline card2__whyline--lead",
      "data-hook": "card-total-why", text: firstWhy }));
  }

  const chipsRow = conditionChips(pick);
  if (chipsRow.length) {
    const chipsWrap = el("div", { class: "card2__chips", "data-hook": "card-conditions" });
    for (const c of chipsRow) chipsWrap.appendChild(c);
    card.appendChild(chipsWrap);
  }

  // NO CHECK-THIS-PRICE LINK while BETCHECK_SUPPORTS_TOTALS is false -- see
  // that constant's own comment. "Open this matchup" still works: it needs
  // no Bet Check support, only the game route.
  card.appendChild(disclosure({
    summary: "View breakdown",
    id: `card-total-breakdown-${pick.game_pk || pick.rank || Math.random().toString(36).slice(2)}`,
    body: breakdownBody(pick, { ourLabel: "Our number" }),
  }));
  return card;
}

/* -----------------------------------------------------------------------
 * THE MERGED CARD -- "TODAY'S BETS", 2026-09-14.
 *
 * The owner's note today, verbatim in substance: "merge the today bets
 * for ALL BETS not just MLs include all best bets like player props."
 * `payload.all_bets` is the server's own merged order across
 * `payload.picks` / `payload.total_picks` / `payload.prop_picks` -- this
 * file renders that order, it never re-sorts or re-selects anything.
 *
 * FOUND DEFENSIVELY, NOT TRUSTED BLINDLY. The backend track's own notes on
 * the exact shape of `item.key` were not available to this track (see this
 * file's git history / the integrator's brief) -- `resolveAllBetsItem`
 * treats `item.key` as a hint (an index into the pick's own array) and
 * only trusts it once the pick found there actually carries the same
 * `bet` sentence the merged entry named; otherwise it falls back to a
 * straight scan of that array for a matching `bet` string, which is the
 * one field every pick kind serializes identically.
 * -------------------------------------------------------------------- */

/** Which of the three type-specific arrays a merged entry's full pick
 * lives in. Never `prop_picks` for a "total" entry or vice versa -- each
 * kind reads its own array only. */
function allBetsSourceArray(kind, payload) {
  if (kind === "game") return payload.picks;
  if (kind === "total") return payload.total_picks;
  if (kind === "prop") return payload.prop_picks;
  return null;
}

function resolveAllBetsItem(item, payload) {
  const list = allBetsSourceArray(item.kind, payload);
  if (!Array.isArray(list)) return null;
  // `item.index`, not `item.key` (2026-09-14, integrator): the backend
  // (daily_card.merge_all_bets) emits `index`; `key` never existed, so this
  // hint never hit and every entry went through the scan below.
  if (Number.isInteger(item.index) && list[item.index] && list[item.index].bet === item.bet) {
    return list[item.index];
  }
  return list.find((p) => p && p.bet === item.bet) || null;
}

/** Every `payload.all_bets` entry that actually resolves to a full pick,
 * in order, paired with that pick -- an entry whose `bet` string cannot be
 * found in its own kind's array (a mismatch between the merged list and
 * the arrays it was built from) is dropped here rather than rendered
 * broken.
 *
 * RESOLVED ONCE, UP FRONT, 2026-09-14. An Opus checker caught the count and
 * numbering ("N OF M") being computed from `allBets.length` -- the RAW
 * array, unresolved entries included -- while the render loop skipped any
 * entry `mergedBetCard` could not resolve. An 8-item list with one
 * unresolved entry rendered 7 cards under "8 bets", numbered 1, 3, 4 ... 8:
 * a gap where the dropped entry's number used to be. Resolving first means
 * the count and every "N OF M" are both taken from the SAME list that
 * actually renders -- see the loop in `renderCard` below. */
function resolveAllBets(payload, allBets) {
  const resolved = [];
  for (const item of allBets) {
    const full = resolveAllBetsItem(item, payload);
    if (full) resolved.push({ item, full });
  }
  return resolved;
}

/** The small kind tag every merged card carries, beside its rank and
 * label -- MONEYLINE / RUN LINE / TOTAL / PLAYER PROP. A "game" entry can
 * be either of the first two (`pick.market === "run_line"` names the
 * alternative-turned-pick case); "total" and "prop" are each always one
 * word, because payload.total_picks and payload.prop_picks never carry
 * anything else. */
function kindTagText(kind, pick) {
  if (kind === "game") return (pick && pick.market === "run_line") ? "RUN LINE" : "MONEYLINE";
  if (kind === "total") return "TOTAL";
  if (kind === "prop") return "PLAYER PROP";
  return "";
}

function kindTagEl(text) {
  return el("span", { class: "card2__kind", "data-hook": "card-kind-tag", text });
}

/** A prop whose lineup has not posted yet -- `expected_pa_source` is still
 * read from the last game log, not tonight's actual batting order, and a
 * reader is told so on the card face rather than left to notice only if
 * they click through.
 *
 * NOT A TRAILING CHIP, 2026-09-14. An Opus checker caught the first version:
 * a small amber chip appended LAST in `.card2__top`, after the rank, label,
 * grade, first-pitch time and kind tag -- 11px, the smallest text on the
 * card, and one more flex item that `.card2__top`'s own wrap could push onto
 * a second line and lose. This is its own warn line instead, the same size
 * and colour as the stale-price warning above (`.card2lede--warn`), and it
 * goes ABOVE the bet sentence -- the first thing read, not the last thing
 * noticed. */
function lineupNotPostedWarning() {
  return el("p", { class: "card2lede card2lede--warn",
    "data-hook": "card-lineup-tag",
    // WORDING FIXED 2026-09-14 (integrator): it claimed the pick read his
    // most recent game, which is untrue -- the fallback is his season-average
    // plate appearances per game (playerprops.py pa_source "season_average").
    text: "LINEUP NOT POSTED — priced off his season-average plate appearances, "
        + "not tonight's batting order." });
}

/** The merged head's second sentence, built from the kinds ACTUALLY
 * rendered under it, never a fixed claim about all three.
 *
 * THE DEFECT, 2026-09-14: this always printed "Game picks, totals and
 * player props together," even on today's own card -- five moneylines,
 * zero totals, zero props (no lineup has posted) -- naming two kinds of
 * bet that were nowhere on the page under it. EIGHT LITERAL BRANCHES, not
 * a computed sentence handed to `text:` -- same reasoning as
 * `propSectionHead`'s own comment above: each sentence must start right at
 * `text: "` for the register sweep (tests/test_web_register_sweep.py,
 * tests/test_customer_language.py) to find it. */
function allBetsSectionHead(count, kindsPresent) {
  const wrap = el("div", { "data-hook": "card-all-bets-divider" });
  wrap.appendChild(sectionHead("TODAY'S BETS",
    count ? `${count} bet${count === 1 ? "" : "s"}` : null));
  const g = kindsPresent.has("game");
  const t = kindsPresent.has("total");
  const p = kindsPresent.has("prop");
  if (g && t && p) {
    wrap.appendChild(el("p", { class: "card2lede card2lede--mute",
      "data-hook": "card-all-bets-subhead",
      text: "Every bet we can price and grade, ranked by how likely it is. "
          + "Game picks, totals and player props together." }));
  } else if (g && t) {
    wrap.appendChild(el("p", { class: "card2lede card2lede--mute",
      "data-hook": "card-all-bets-subhead",
      text: "Every bet we can price and grade, ranked by how likely it is. "
          + "Game picks and totals together." }));
  } else if (g && p) {
    wrap.appendChild(el("p", { class: "card2lede card2lede--mute",
      "data-hook": "card-all-bets-subhead",
      text: "Every bet we can price and grade, ranked by how likely it is. "
          + "Game picks and player props together." }));
  } else if (t && p) {
    wrap.appendChild(el("p", { class: "card2lede card2lede--mute",
      "data-hook": "card-all-bets-subhead",
      text: "Every bet we can price and grade, ranked by how likely it is. "
          + "Totals and player props together." }));
  } else if (g) {
    wrap.appendChild(el("p", { class: "card2lede card2lede--mute",
      "data-hook": "card-all-bets-subhead",
      text: "Every bet we can price and grade, ranked by how likely it is. "
          + "Game picks, and only game picks, so far today." }));
  } else if (t) {
    wrap.appendChild(el("p", { class: "card2lede card2lede--mute",
      "data-hook": "card-all-bets-subhead",
      text: "Every bet we can price and grade, ranked by how likely it is. "
          + "Totals, and only totals, so far today." }));
  } else if (p) {
    wrap.appendChild(el("p", { class: "card2lede card2lede--mute",
      "data-hook": "card-all-bets-subhead",
      text: "Every bet we can price and grade, ranked by how likely it is. "
          + "Player props, and only player props, so far today." }));
  }
  return wrap;
}

/** One entry of `payload.all_bets`, rendered from the kind's own renderer
 * -- `pickCard` for a game pick, `totalPickCard` for a total,
 * `propPickCard` for a prop -- with the merged list's own position/count
 * (never the type-specific array's), the kind tag, and the LINEUP NOT
 * POSTED warning where a prop's lineup has not posted.
 *
 * `full` and `index` come from the caller's already-`resolveAllBets`-ed
 * list (see that function's own comment) -- this never re-resolves and
 * never returns null, because an entry that could not be resolved was
 * already left out before numbering happened. */
function mergedBetCard(item, full, allBetsTotal, index, servingOlderDate) {
  // THE POSITION, 2026-09-14. `item.position || full.position` was the
  // defect an Opus checker caught: when the server's own `item.position`
  // was falsy, this fell back to `full.position` -- the pick's position
  // WITHIN ITS OWN KIND'S ARRAY -- so a game pick and a prop could both
  // read "1 OF 8" on the same card. The merged list is already in rank
  // order (the server's own doing, never re-sorted here -- see this
  // section's own docstring), so the position within the RESOLVED list
  // (`index`, 0-based) is always a safe, contiguous fallback.
  // ALWAYS the resolved index (2026-09-14, integrator): the server sets
  // `item.position` over the UNRESOLVED list, so one dropped entry still
  // read "1, 3, 4 ... 8 OF 7". The resolved list keeps the server's order.
  const position = index + 1;
  const positioned = Object.assign({}, full, { position });
  let card;
  if (item.kind === "prop") {
    card = propPickCard(positioned, allBetsTotal, servingOlderDate);
  } else if (item.kind === "total") {
    card = totalPickCard(positioned, allBetsTotal);
  } else {
    card = pickCard(positioned, allBetsTotal);
  }
  const top = card.querySelector(".card2__top");
  if (top) top.appendChild(kindTagEl(kindTagText(item.kind, full)));
  if (item.kind === "prop" && full.lineup_posted === false) {
    // ABOVE THE BET SENTENCE, not a trailing chip in `.card2__top` -- see
    // `lineupNotPostedWarning`'s own comment for why.
    const bet = card.querySelector(".card2__bet");
    const warning = lineupNotPostedWarning();
    if (bet) card.insertBefore(warning, bet);
    else card.appendChild(warning);
  }
  return card;
}

/** "N of tonight's picks are here because the slate was thin ... marked
 * SPLIT." Shared by both the merged (`all_bets`) and the original render
 * paths in `renderCard` below -- same sentence either way, read from
 * `payload.filled`, which counts game picks only and does not change
 * shape when totals or props join the card beside them. Returns null
 * rather than an empty string so both callers can `if (note)` rather than
 * appending an empty paragraph. */
function filledNote(payload) {
  if (!payload.filled) return null;
  // "Our own numbers do not agree with the market" needs numbers of our
  // own -- a card with none (has_model: false, 2026-09-20) cannot say it.
  if (!cardHasOwnModel(payload)) return null;
  // Named out loud. A reader is entitled to know that the last pick is on
  // the card because it was the next best thing available, not because
  // anything about it was convincing.
  // 2026-09-17: this used to end "and they are marked SPLIT". The D1 rebuild
  // removed the STRONG/LEAN/SPLIT chips from the card's face, so that clause
  // pointed a reader at a marking that is no longer anywhere on the page --
  // a dangling reference, which is worse than the label itself was. The
  // sentence now states the fact directly instead of naming a vanished
  // badge. Nothing about what it discloses has been softened.
  return el("p", { class: "card2lede card2lede--mute",
    text: `${payload.filled} of tonight's picks are here because the slate `
        + `was thin — our own numbers do not agree with the market on `
        + `${payload.filled === 1 ? "it" : "them"}.` });
}

/** The card's own running record, or an honest statement that there is none.
 *
 * THIS IS THE SENTENCE THE PRODUCT IS SOLD ON, so it sits directly under
 * the picks rather than on a page nobody clicks. It reports the losses at
 * the same size as the wins and it reports VOIDS, because a record that
 * silently omits postponed games has a hole in it that nobody can see.
 *
 * "No record yet" is rendered rather than hidden. A brand-new product with
 * an empty record is a fact about how new it is; a product that hides the
 * empty record is making a different, worse impression on purpose.
 */
function recordLine(rec, sport = "mlb") {
  const wrap = el("div", { class: "card2rec chamfer", "data-hook": "card-record" });
  // NFL's record counts the current rule only (2026-09-20) -- named here,
  // or "Nothing graded yet" under a card the old rule made reads as a
  // claim about THAT card, whose picks are graded on their own record.
  wrap.appendChild(el("span", { class: "card2rec__label",
    text: sport === "nfl" ? "THE RECORD SO FAR · CURRENT NFL RULE" : "THE RECORD SO FAR" }));

  // EVERY DAY, INCLUDING THE ONES WITH NOTHING GRADED YET -- this is the
  // one link off the page that sells the product on its own past, so it
  // sits here whether or not this pooled summary has numbers to show yet.
  // Sport-aware since 2026-09-19 (NFL went live): MLB's record lives at
  // #/record-card, NFL's at #/nfl/record -- pointing an NFL reader at
  // MLB's own record page would show them the wrong sport's numbers under
  // a link they clicked from an NFL screen.
  const recordHref = sport === "nfl" ? "#/nfl/record" : "#/record-card";
  const seeFullRecord = () => el("a", { class: "card2rec__link", href: recordHref,
    "data-hook": "card-record-link", text: "SEE THE FULL RECORD, DAY BY DAY →" });

  if (!rec || !rec.n_staked) {
    wrap.appendChild(el("p", { class: "card2rec__body",
      text: `${sport === "nfl" ? "Nothing graded yet under the current NFL rule." : "Nothing graded yet."} `
          + "Every card is settled the morning after, "
          + "win or lose, and the running record appears here from then on." }));
    wrap.appendChild(seeFullRecord());
    return wrap;
  }

  const line = el("p", { class: "card2rec__figures" });
  line.appendChild(el("span", { class: "card2rec__wl",
    text: `${rec.wins}-${rec.losses}${rec.pushes ? `-${rec.pushes}` : ""}` }));

  // SAMPLE SIZE, NOT SPIN. NFL has published and graded exactly one pick as
  // of 2026-09-19 -- "100% of bets won" off n=1 reads like a track record
  // and is not one. Below NFL_SAMPLE_FLOOR picks, NFL shows the raw count
  // and the units won (a plain sum, not a rate) instead of a win-rate or
  // ROI percentage, plus an explicit line naming the sample size so nobody
  // has to do the division themselves to notice it is tiny. MLB is
  // unaffected -- it has never had a sample this small since this page
  // shipped, and the moment it did this same guard would apply to it too.
  const tooSmallForARate = sport === "nfl" && rec.n_staked < NFL_SAMPLE_FLOOR;
  line.appendChild(el("span", { class: "card2rec__meta",
    text: tooSmallForARate
      ? `${rec.days} day${rec.days === 1 ? "" : "s"} · `
        + `${rec.profit_units > 0 ? "+" : ""}${rec.profit_units.toFixed(2)} units `
        + `at 1 unit a bet`
      : `${rec.days} day${rec.days === 1 ? "" : "s"} · `
        + `${(rec.win_rate * 100).toFixed(0)}% of bets won · `
        + `${rec.profit_units > 0 ? "+" : ""}${rec.profit_units.toFixed(2)} units `
        + `at 1 unit a bet` }));
  wrap.appendChild(line);

  if (tooSmallForARate) {
    wrap.appendChild(el("p", { class: "card2rec__warn", "data-hook": "card-record-small-sample",
      text: `Only ${rec.n_staked} NFL pick${rec.n_staked === 1 ? " has" : "s have"} been graded. `
          + `That is too few to show a win rate or a return -- read the count above, not a `
          + `percentage, until there are more.` }));
  }

  if (rec.voids) {
    wrap.appendChild(el("p", { class: "card2rec__body",
      text: `${rec.voids} pick${rec.voids === 1 ? "" : "s"} could not be `
          + `graded (game postponed or no final score). They count as neither `
          + `a win nor a loss and are left out of the return above.` }));
  }
  if (rec.chain_ok === false) {
    wrap.appendChild(el("p", { class: "card2rec__warn",
      text: "The record's hash chain does not currently verify, so treat "
          + "the numbers above as unconfirmed until it does." }));
  }
  wrap.appendChild(seeFullRecord());
  return wrap;
}

/** The one honest line about what a card is and is not -- now a disclosure
 * ("How this card works") at the bottom of the page rather than a fixed
 * panel between the picks and the record, so it stops competing with the
 * picks for a reader's first look while staying one tap away. Holds the
 * same server-composed disclaimer/basis/legend as before, verbatim. */
function standingNote(payload) {
  const note = el("div", { class: "card2note", "data-hook": "card-standing-note" });
  note.appendChild(el("p", { class: "card2note__body card2note__body--label",
    text: "Note stored with this card" }));
  note.appendChild(el("p", { class: "card2note__body", text: payload.disclaimer || "" }));
  note.appendChild(el("p", { class: "card2note__body card2note__body--mute",
    text: payload.basis || "" }));
  // What the letter beside each pick means -- served, never typed here, so
  // the page and the grader cannot disagree about it.
  for (const line of payload.knowledge_legend || []) {
    note.appendChild(el("p", { class: "card2note__body card2note__body--mute",
      "data-hook": "card-grade-legend", text: line }));
  }
  if (payload.calibrated === false && cardHasOwnModel(payload)) {
    // A card built without the calibration file publishes the raw model's
    // numbers, which run about twice as confident as they should. That is a
    // deploy fault and the reader is told rather than shown a number the
    // page cannot stand behind. A card with no model at all (has_model:
    // false -- NFL_CARD_V2, 2026-09-20) has nothing to calibrate, and the
    // warning would be false there.
    note.appendChild(el("p", { class: "card2note__warn",
      text: "Our own probabilities are running uncalibrated right now, which "
          + "makes them read more confident than they should. The market "
          + "numbers beside them are unaffected." }));
  }
  return note;
}

function emptyCard(payload, sport = "mlb") {
  const wrap = el("section", { class: "gutter", "data-hook": "card-empty" });
  const panel = el("div", { class: "panel chamfer card2empty" });
  panel.appendChild(el("span", { class: "card2empty__label", text: "NO CARD TODAY" }));
  // VERBATIM. Every `reason` the server produces names a fact about the
  // world; composing a substitute here is how a page starts describing its
  // own confidence instead.
  panel.appendChild(el("p", { class: "card2empty__body",
    text: payload.reason || "Today's card is not available." }));
  const actions = el("div", { class: "card2empty__actions" });
  // Bet Check and the Odds board are MLB tools -- neither reads a `sport`
  // parameter. Sending an NFL reader with no NFL card today to either would
  // quietly hand them MLB's board under an NFL empty state, which is a
  // worse answer than the plain truth: NFL's picks are the live MLB card
  // and its own graded record, nothing else, so those are what this state
  // points at instead.
  if (sport === "nfl") {
    actions.appendChild(el("a", { class: "btn btn--primary chamfer chamfer--btn",
      href: "#/today", text: "SEE TONIGHT'S MLB PICKS" }));
    actions.appendChild(el("a", { class: "btn btn--ghost chamfer chamfer--btn",
      href: "#/nfl/record", text: "VIEW THE NFL RECORD" }));
  } else {
    actions.appendChild(el("a", { class: "btn btn--primary chamfer chamfer--btn",
      href: "#/betcheck", text: "CHECK A BET OF YOUR OWN" }));
    actions.appendChild(el("a", { class: "btn btn--ghost chamfer chamfer--btn",
      href: "#/odds", text: "OPEN THE FULL BOARD" }));
  }
  panel.appendChild(actions);
  wrap.appendChild(panel);
  return wrap;
}

/** Whether a card payload has anything to render at all -- game picks OR a
 * non-empty `payload.all_bets`.
 *
 * THE DEFECT, 2026-09-14: every emptiness check on this page read
 * `payload.picks` alone, a leftover from before totals and props could
 * lead the card on their own. A slate with zero moneylines but real totals
 * or props in `all_bets` -- read: today's, whenever a moneyline card
 * SPLITs out entirely but a total or a prop still clears its price -- was
 * treated as a night with nothing, walked back to yesterday's card or
 * `emptyCard`'s "NO CARD TODAY", and every bet actually available was
 * thrown away along with it. Checked once, here, and reused everywhere
 * this page decides "is there anything on this card". */
function payloadHasBets(payload) {
  if (!payload) return false;
  if ((payload.picks || []).length) return true;
  const allBets = Array.isArray(payload.all_bets) ? payload.all_bets : [];
  if (!allBets.length) return false;
  // A RESOLVED count, not just a non-empty array -- an `all_bets` list
  // whose entries cannot be matched to any pick in their own kind's array
  // (a backend/frontend mismatch, not this night's actual bets) must not
  // itself count as "has bets"; that is exactly the reasoning
  // `resolveAllBets` already applies to what gets rendered, reused here so
  // the emptiness check and the render agree.
  return resolveAllBets(payload, allBets).length > 0;
}

/** The card's own #1 pick, by the position it is actually SERVED at (see
 * `pickCard`'s own comment on `position` vs `rank`) -- falls back to `rank`
 * for a live (not-yet-frozen) card, whose picks carry `rank` only.
 * `docs/DECISION_TODAY_ONE_ANSWER.md` option B1: this is what the Today
 * hero leads with now, never a price-gap computation. */
function firstPickOf(payload) {
  const picks = (payload && payload.picks) || [];
  return picks.find((p) => (p.position || p.rank) === 1) || picks[0] || null;
}

/** Mount the card into `host`. Returns `{ rendered, firstPick }`:
 * `rendered` is true when picks actually rendered, so the caller can decide
 * what the rest of the screen says beneath it; `firstPick` is the served
 * #1 pick (or null on an empty/failed card) for the Today hero to read.
 *
 * A fetch failure renders the error and returns `rendered: false` -- it
 * must never look like a night with no picks, which is a different and
 * real condition.
 */
export async function renderCard(host, options = {}) {
  // Support both old signature renderCard(host, date) and new
  // renderCard(host, {sport, date}) for backward compatibility
  let sport = "mlb";
  let date;
  if (typeof options === "string") {
    // Old signature: date passed as string
    date = options;
  } else if (typeof options === "object" && options !== null) {
    // New signature: options object
    sport = options.sport || "mlb";
    date = options.date;
  }

  const wrap = el("section", { class: "gutter", "data-hook": "card" });
  host.appendChild(wrap);

  // THE ONE EXPERIMENTAL NOTICE, above every pick and kept through the
  // empty and error branches (GC-2, 2026-09-16) -- the empty-card branch
  // below used to call clear(wrap) before rendering emptyCard(), which
  // wiped this notice along with everything else. Every later clear() in
  // this function must clear the CONTENT past this point, never this node.
  // It already reads exactly NFL_NOTICE's sentence, so NFL gets no second
  // copy here -- the go-live pass (2026-09-20) printed it twice in a row.
  wrap.appendChild(experimentalNotice());

  // Two reads, and the record must never take the card down with it: a
  // failed record fetch is not a night with no picks, and the picks are the
  // thing the reader came for.
  // THE PAGE MUST NEVER SHOW NOTHING WHERE THE BETS GO.
  //
  // The owner's standing rule, in his words: "never, ever, not once, ever
  // let this LINEHOUND site say 'We check the slate and nothing clears the
  // bar.' ... You need to have 3-5 bets every day, no matter what."
  //
  // TWO WAYS THIS SCREEN BROKE THAT RULE on the evening of 2026-09-10, and
  // they arrive by different routes, so both are handled here:
  //
  //   1. The request FAILED. After the slate rolls in the evening the page
  //      asks for TOMORROW's card; while the box was struggling that timed
  //      out and rendered "REQUEST FAILED — We could not reach the board"
  //      directly beneath the record strip.
  //
  //   2. The request SUCCEEDED AND WAS EMPTY. Once the box was fast the same
  //      request returned 200 with zero picks, and the page rendered "NO CARD
  //      TODAY — The books have not posted prices for today's games yet."
  //      True, and the same forbidden sentence in different words.
  //
  // Tomorrow's card does not exist until the morning pass publishes it.
  // Falling back to the most recently published card and SAYING SO is old
  // but honest, and it beats both an error and an empty state. It never
  // invents a card for a slate nobody has looked at.
  // WALK BACK A DAY AT A TIME, and NOT through /card/history.
  //
  // /card/history was the obvious source and it is the wrong one: it lists
  // SETTLED days, so tonight's card -- published this morning, graded
  // tomorrow -- is not in it. On staging at 10:45pm it returned zero days
  // while /card/2026-09-10 served three picks, and the fallback silently did
  // nothing. Checked rather than assumed, after it failed once.
  //
  // ONE DAY BACK, AND ON A SHORT LEASH. Both limits were paid for.
  //
  // The first version walked back three days, awaiting each in turn. This
  // runs inside the page's render path, so on a container where a cold card
  // takes seconds that is three sequential stalls before anything appears --
  // and #/today rendered as a bare nav and footer, 336 characters, while it
  // waited. A fallback whose job is to stop the page looking broken must not
  // be the thing that breaks it.
  //
  // One day back is also all a reader wants: "last night's card" means last
  // night, not last week. FALLBACK_TIMEOUT_MS bounds the worst case; the
  // normal case is a frozen row and returns in about 200ms.
  // `rule`: the card being replaced's own rule id. A card published under a
  // DIFFERENT rule is never shown as the fallback (2026-09-20): the NFL card
  // switched from favourites (NFL_CARD_V1) to value lines (NFL_CARD_V2), and
  // on V2's first quiet day this used to put V1's -950 card back on screen.
  async function lastPublishedCard(fromDate, rule = null) {
    const start = fromDate ? new Date(`${fromDate}T12:00:00Z`) : new Date();
    if (Number.isNaN(start.getTime())) return null;
    const day = new Date(start.getTime() - 86400000).toISOString().slice(0, 10);
    try {
      const url = `/card/${day}${sport !== "mlb" ? `?sport=${sport}` : ""}`;
      const older = await apiGet(url,
                                 { timeoutMs: FALLBACK_TIMEOUT_MS });
      if (rule && older && older.rule && older.rule !== rule) return null;
      return older && payloadHasBets(older) ? older : null;
    } catch (_err) {
      // A fallback that cannot load is not an error worth showing. The
      // caller falls through to its own empty state, which is honest.
      return null;
    }
  }

  let payload;
  let record = null;
  let servingOlderCard = null;
  try {
    const cardUrl = date
      ? `/card/${encodeURIComponent(date)}${sport !== "mlb" ? `?sport=${sport}` : ""}`
      : `/card${sport !== "mlb" ? `?sport=${sport}` : ""}`;
    const recordUrl = `/card/record${sport !== "mlb" ? `?sport=${sport}` : ""}`;
    [payload, record] = await Promise.all([
      apiGet(cardUrl),
      apiGet(recordUrl).catch(() => null),
    ]);
  } catch (err) {
    const last = await lastPublishedCard(date);
    if (!last) {
      // Both the card and the fallback are unreachable. This really is an
      // outage, and the ORIGINAL error is the one that describes it -- not
      // the fallback's.
      const errBody = el("div", { "data-hook": "card-error-body" });
      wrap.appendChild(errBody);
      renderError(errBody, err);
      return { rendered: false, firstPick: null };
    }
    payload = last;
    servingOlderCard = last.date || null;
    const recordUrl = `/card/record${sport !== "mlb" ? `?sport=${sport}` : ""}`;
    record = await apiGet(recordUrl).catch(() => null);
  }

  if (!payloadHasBets(payload)) {
    const last = await lastPublishedCard(payload.date || date, payload.rule || null);
    if (last) {
      payload = last;
      servingOlderCard = last.date || null;
    }
    // If there is no published card anywhere either -- a first deploy, the
    // off-season -- `emptyCard` below still runs and states that plainly.
    // Saying nothing at all would be worse than saying there is nothing yet.
  }

  if (!payloadHasBets(payload)) {
    // Re-append past the notice mounted at the top of this function -- do
    // not clear(wrap), which would wipe it along with everything else
    // (GC-2, 2026-09-16; the same defect this comment already described
    // before this rewrite).
    wrap.appendChild(emptyCard(payload, sport));
    return { rendered: false, firstPick: null };
  }
  // `picks` (game picks only) can still be empty here -- a card can be
  // non-empty on `all_bets` alone (totals or props, no moneyline that
  // clears). Every place below that used to assume `picks.length > 0`
  // reads `payload.all_bets` too, from here down.
  const picks = payload.picks || [];

  const meta = payload.games_on_slate
    ? `${picks.length} of ${payload.games_on_slate} games`
    : `${picks.length} picks`;
  // Named for what it is. A card from an earlier slate must never sit under
  // a heading that says TONIGHT'S.
  wrap.appendChild(sectionHead(
    servingOlderCard ? "LAST PUBLISHED CARD" : "TONIGHT'S CARD", meta));
  // A frozen NFL card from before 2026-09-20 was made by the retired
  // favourites rule. Its picks stay in the ledger as published -- evidence
  // is never edited -- but it must not read as today's method.
  // CORRECTED 2026-09-20: this said the old rule "stays on the record",
  // while the NFL record page (and the record line under this card) had
  // just switched to counting the current rule only -- the old rule's
  // results were nowhere a reader could see them. It now says where they
  // are, and links there.
  if (sport === "nfl" && payload.rule === NFL_RETIRED_RULE) {
    wrap.appendChild(el("p", { class: "card2lede card2lede--notice",
      "data-hook": "card-retired-rule",
      text: "This card was made by our old NFL rule, which simply took the "
        + "favourite. Its picks stay in the ledger exactly as published and are "
        + "graded on a record of their own; the NFL record below counts only "
        + "the current rule. The current rule takes spreads, totals and "
        + "moneylines only where one book's price beats the rest of the "
        + "market's by a set margin, and never at -200 or worse." }));
    // In its own lede paragraph, so it takes the lede spacing rather than
    // running into the "Locked at" line below it.
    wrap.appendChild(el("p", { class: "card2lede" }, [el("a", { class: "card2rec__link",
      href: `#/nfl/record?rule=${NFL_RETIRED_RULE}`,
      "data-hook": "card-retired-rule-link", text: "SEE THE OLD RULE'S RECORD →" })]));
  }
  if (servingOlderCard) {
    wrap.appendChild(el("p", { class: "card2lede", "data-hook": "card-older",
      // "already graded" was wrong and shipped for about ten minutes. A card
      // is published in the morning and graded after its games settle, so at
      // 10:52pm the card being shown here is frozen but NOT yet graded. It
      // is a small claim and it was still a false one, on the page whose
      // whole pitch is that the claims are checkable.
      text: `Tomorrow's card posts in the morning. These are the bets from `
          + `${servingOlderCard}, published before those games started.` }));
  }

  // TWO DIFFERENT PROMISES, AND THE PAGE MUST NOT MAKE THE WRONG ONE.
  //
  // Once the afternoon pass has published, this card is the frozen ledger
  // row -- the exact bets, at the exact prices, that were committed before
  // first pitch and cannot be edited afterwards. That is the product, and
  // it is the sentence that earns the record page's credibility.
  //
  // Before that, the page is building from live prices and the card can
  // still change. Saying "frozen before first pitch" then would be claiming
  // a commitment that has not been made yet, which is the small dishonesty
  // that makes the large one possible.
  if (payload.frozen) {
    const at = payload.frozen_at ? formatEasternTime(payload.frozen_at) : null;
    // FORTY WORDS CUT TO TEN, 2026-09-10. It read: "Frozen at 10:36 AM ET --
    // these are the exact bets and prices we committed to before first
    // pitch, and they have not been touched since. Every one is graded win
    // or lose on the record page, including the ones that lose."
    //
    // Every clause was true and the whole paragraph stood between a reader
    // and the first bet on the page. The claim survives intact -- locked
    // before first pitch, graded either way -- in a line someone will
    // actually read. "Keep it minimal, to the point."
    // "first pitch" on an NFL card (seen on #/nfl, 2026-09-20) -- the
    // same sentence, in the sport's own word.
    wrap.appendChild(el("p", { class: "card2lede", "data-hook": "card-frozen",
      text: `Locked${at ? ` at ${at}` : ""}, before ${sport === "nfl" ? "kickoff" : "first pitch"}. `
          + "Graded after — win or lose." }));

    // A FROZEN PRICE IS A HISTORICAL FACT, NOT A QUOTE. On a slate with an
    // early game the card freezes in the morning, and a reader arriving at
    // 4pm would otherwise take "-149 at DraftKings" as a number they can
    // still get. Told plainly at the point of confusion rather than left to
    // the reader to work out from the timestamp.
    // `prices_as_of` (NFL, 2026-09-21): the OLDEST lock on a card built
    // across several publishes, so the warning never understates how old a
    // price is. MLB's payload has no such field and keeps using frozen_at.
    const ageHours = hoursSince(payload.prices_as_of || payload.frozen_at);
    if (ageHours !== null && ageHours >= STALE_PRICE_HOURS) {
      wrap.appendChild(el("p", { class: "card2lede card2lede--warn",
        "data-hook": "card-stale-prices",
        text: `These prices are ${Math.round(ageHours)} hours old — check the `
            + `current number before you bet.` }));
    }
  } else {
    wrap.appendChild(el("p", { class: "card2lede", "data-hook": "card-live",
      text: "Live prices — tonight's card is not locked in yet. It freezes "
          + `before ${sport === "nfl" ? "kickoff" : "first pitch"}, and from that point the bets and prices `
          + "below cannot change. Every one is then graded win or lose on "
          + "the record page, including the ones that lose." }));
  }

  // THE MERGED CARD, 2026-09-14. `payload.all_bets` is the server's own
  // ranked merge of picks/total_picks/prop_picks -- when it is a non-empty
  // array, IT leads the card as one list, and the old two-grid layout
  // below does not also run (a bet must appear once, not twice). When it
  // is absent -- every row written before 2026-09-14, or a backend that
  // has not shipped it on this deploy yet -- the `else` branch renders
  // exactly what this file has always rendered. Do not fold the two
  // branches together; the `else` branch is this file's whole
  // compatibility story for those older rows.
  const allBets = Array.isArray(payload.all_bets) ? payload.all_bets : [];
  // RESOLVED ONCE, before the count or a single card is rendered -- see
  // `resolveAllBets`'s own comment for the gap-numbering defect this fixes.
  const resolvedBets = allBets.length ? resolveAllBets(payload, allBets) : [];
  if (resolvedBets.length) {
    const kindsPresent = new Set(resolvedBets.map((r) => r.item.kind));
    wrap.appendChild(allBetsSectionHead(resolvedBets.length, kindsPresent));
    const mergedGrid = el("div", { class: "card2grid", "data-hook": "card-all-bets-grid" });
    resolvedBets.forEach(({ item, full }, index) => {
      mergedGrid.appendChild(
        mergedBetCard(item, full, resolvedBets.length, index, servingOlderCard));
    });
    wrap.appendChild(mergedGrid);
    const note = filledNote(payload);
    if (note) wrap.appendChild(note);
    // THE REASON PROPS ARE MISSING MUST NOT DISAPPEAR, 2026-09-14. The old
    // branch below (`payload.prop_reason && picks.length`) said why there
    // are no player props on nights there are none -- "no lineup has
    // posted yet" and the like. The first version of this merged branch
    // dropped that sentence entirely whenever `all_bets` existed, even on
    // a card with zero props in it, which is exactly the case the sentence
    // exists for. Same condition, same wording, just reached from here
    // too: only when the RENDERED list has no prop in it, never when one
    // is already on the card above.
    if (!kindsPresent.has("prop") && payload.prop_reason) {
      wrap.appendChild(propSectionHead(servingOlderCard, false));
      wrap.appendChild(el("p", { class: "card2lede card2lede--mute",
        "data-hook": "card-prop-reason", text: payload.prop_reason }));
    }
  } else {
    const grid = el("div", { class: "card2grid", "data-hook": "card-grid" });
    const pickOpts = { sport, hasModel: cardHasOwnModel(payload) };
    for (const pick of picks) grid.appendChild(pickCard(pick, picks.length, pickOpts));
    wrap.appendChild(grid);

    const note = filledNote(payload);
    if (note) wrap.appendChild(note);

    // PLAYER PROPS, after the game picks. `prop_picks` is absent on every
    // ledger row written before 2026-09-12 -- `|| []` is the whole
    // compatibility story for those rows, and an empty array here renders
    // nothing beyond this point, same as an absent key. `prop_reason` only
    // ever gets a line when there ARE game picks above it (this point is
    // never reached otherwise -- see the early `emptyCard` return above): a
    // reason with nothing else on the
    // screen would read as the forbidden "nothing clears the bar" in a
    // different key.
    const propPicks = payload.prop_picks || [];
    if (propPicks.length) {
      wrap.appendChild(propSectionHead(servingOlderCard));
      const propGrid = el("div", { class: "card2grid", "data-hook": "card-prop-grid" });
      for (const pick of propPicks) {
        propGrid.appendChild(propPickCard(pick, propPicks.length, servingOlderCard));
      }
      wrap.appendChild(propGrid);
    } else if (payload.prop_reason && picks.length) {
      wrap.appendChild(propSectionHead(servingOlderCard, false));
      wrap.appendChild(el("p", { class: "card2lede card2lede--mute",
        "data-hook": "card-prop-reason", text: payload.prop_reason }));
    }
  }

  wrap.appendChild(recordLine(record, sport));
  wrap.appendChild(disclosure({
    summary: "How this card works",
    id: "card-standing-note-panel",
    body: standingNote(payload),
  }));
  return { rendered: true, firstPick: firstPickOf(payload) };
}
