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
 * It also never hides the SPLIT label. A pick our own model disagrees with
 * is on the card because the slate was thin, it says so on its own face, and
 * a reader who only reads the big sentence still sees the word.
 */

import { apiGet } from "./api.js";
import { el, clear, renderError, formatAmerican, formatEasternTime } from "./dom.js";
import { bookLabel } from "./labels.js";

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

function sectionHead(label, meta) {
  const head = el("div", { class: "sechead" });
  head.appendChild(el("span", { class: "sechead__label", text: label }));
  head.appendChild(el("span", { class: "sechead__hair" }));
  if (meta) head.appendChild(el("span", { class: "sechead__meta", text: meta }));
  return head;
}

function betCheckHref(pick) {
  const params = new URLSearchParams();
  if (pick.date) params.set("date", pick.date);
  if (pick.bet) params.set("q", pick.bet.replace(/^Take\s+/i, ""));
  return `#/betcheck?${params.toString()}`;
}

/** One pick. The instruction is the biggest thing in it, deliberately. */
function pickCard(pick, total) {
  const tone = LABEL_TONE[pick.label] || "slight";
  const card = el("article", {
    class: `card2 panel chamfer card2--${tone}`,
    "data-hook": "card-pick",
    "data-rank": String(pick.rank || ""),
    "data-label": pick.label || "",
    "data-market": pick.market || "",
    "data-rise": "",
  });

  const top = el("div", { class: "card2__top" });
  // `position` is where this pick sits on the card being served; `rank` is
  // the slot it was frozen in. They differ on a card assembled through the
  // day -- picks lock against their own first pitch and keep their frozen
  // rank, so a nine-pick card carried ranks [3,2,3,1,2,4,5,5,4] and the
  // page printed "3 OF 9" twice (2026-09-11). The server orders and numbers;
  // this only prints.
  top.appendChild(el("span", { class: "card2__rank",
    text: `${pick.position || pick.rank} OF ${total}` }));
  top.appendChild(el("span", { class: `card2__label card2__label--${tone}`,
    text: pick.label || "" }));
  // THE KNOWLEDGE GRADE (src/analysis/grade.py): how complete our read of
  // this game was when the pick was frozen. A letter beside the label, the
  // one-line reason on hover, the legend once under READ THIS ONCE. It is
  // not a forecast and the legend says so; the "+" is the only place a
  // price enters.
  const knowledge = pick.knowledge || null;
  if (knowledge && knowledge.grade) {
    top.appendChild(el("span", {
      class: `card2__grade card2__grade--${String(knowledge.letter || "").toLowerCase()}`,
      "data-hook": "card-grade",
      title: knowledge.why || "",
      text: knowledge.grade,
    }));
  }
  if (pick.first_pitch_utc) {
    top.appendChild(el("span", { class: "card2__time",
      text: formatEasternTime(pick.first_pitch_utc) || "" }));
  }
  card.appendChild(top);

  // THE SENTENCE. Server-composed, rendered verbatim, and the only thing on
  // this card set in the display face.
  card.appendChild(el("p", { class: "card2__bet", "data-hook": "card-bet",
    text: pick.bet || "" }));

  const matchup = el("div", { class: "card2__matchup" });
  matchup.appendChild(el("span", { class: "card2__teams",
    text: `${pick.away_team} at ${pick.home_team}` }));
  if (pick.book) {
    matchup.appendChild(el("span", { class: "card2__book",
      text: `${bookLabel(pick.book) || pick.book}${pick.books ? ` · best of ${pick.books} books` : ""}` }));
  }
  card.appendChild(matchup);

  const why = el("div", { class: "card2__why", "data-hook": "card-why" });
  for (const sentence of pick.why || []) {
    why.appendChild(el("p", { class: "card2__whyline", text: sentence }));
  }
  card.appendChild(why);

  // THE ALTERNATIVE. Offered, never recommended, and visually quieter than
  // the pick so it cannot be mistaken for one. It exists because the run
  // line is a genuinely different bet on the same opinion and a reader is
  // better served choosing it themselves than having a model choose for
  // them -- especially this model, whose run distribution is measured wrong
  // (see src/analysis/daily_card.py's RUNLINE_AS_ALTERNATIVE).
  if (pick.alternative && pick.alternative.bet) {
    const alt = el("div", { class: "card2__alt", "data-hook": "card-alternative" });
    alt.appendChild(el("span", { class: "card2__alt-label", text: "OR" }));
    const body = el("div", { class: "card2__alt-body" });
    body.appendChild(el("span", { class: "card2__alt-bet",
      text: pick.alternative.bet }));
    if (pick.alternative.book) {
      body.appendChild(el("span", { class: "card2__alt-book",
        text: bookLabel(pick.alternative.book) || pick.alternative.book }));
    }
    alt.appendChild(body);
    card.appendChild(alt);
  }

  // THE LABEL MEANING LINE IS GONE, 2026-09-10.
  //
  // A STRONG pick already carries a STRONG chip and a sentence naming both
  // probabilities and which way they differ (src/analysis/daily_card.py's
  // `_why`). Printing "The market and our numbers both make this side a
  // clear favourite" under that says the same thing a third time in vaguer
  // words -- and on most picks it is not even true: the model usually sits
  // BELOW the de-vigged market number, which is why that sentence stopped
  // saying "our own numbers agree at X" on 2026-09-11.
  // LABEL_MEANING stays in this file for the tooltip and the legend, where
  // explaining the vocabulary is the whole point.

  const actions = el("div", { class: "card2__actions" });
  actions.appendChild(el("a", {
    class: "btn btn--ghost chamfer chamfer--btn",
    href: betCheckHref(pick),
    "data-hook": "card-check-this",
    text: "CHECK THIS PRICE YOURSELF" }));
  card.appendChild(actions);
  return card;
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
          + "Ranked by how likely we made them, never by the price." }));
  } else {
    wrap.appendChild(el("p", { class: "card2lede card2lede--mute",
      "data-hook": "card-prop-subhead",
      text: "The likeliest props tonight that also clear their price. "
          + "Ranked by how likely we make them, never by the price." }));
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
  const card = el("article", {
    class: `card2 panel chamfer card2--${tone}`,
    "data-hook": "card-prop-pick",
    "data-rank": String(pick.position || pick.rank || ""),
    "data-label": pick.label || "",
    "data-market": pick.market || "",
  });

  const top = el("div", { class: "card2__top" });
  top.appendChild(el("span", { class: "card2__rank",
    text: `${pick.position || pick.rank || 1} OF ${total}` }));
  top.appendChild(el("span", { class: `card2__label card2__label--${tone}`,
    text: pick.label || "" }));
  if (pick.first_pitch_utc) {
    top.appendChild(el("span", { class: "card2__time",
      text: formatEasternTime(pick.first_pitch_utc) || "" }));
  }
  card.appendChild(top);

  // THE SENTENCE. Server-composed, same as the game picks' own bet line.
  card.appendChild(el("p", { class: "card2__bet", "data-hook": "card-prop-bet",
    text: pick.bet || "" }));

  card.appendChild(el("p", { class: "card2__meta", "data-hook": "card-prop-meta",
    text: propMetaLine(pick) }));

  const why = el("div", { class: "card2__why", "data-hook": "card-prop-why" });
  for (const sentence of pick.why || []) {
    why.appendChild(el("p", { class: "card2__whyline", text: sentence }));
  }
  card.appendChild(why);

  const actions = el("div", { class: "card2__actions" });
  actions.appendChild(el("a", {
    class: "btn btn--ghost chamfer chamfer--btn",
    href: servingOlderDate ? `#/props/${servingOlderDate}` : "#/props",
    "data-hook": "card-prop-board-link",
    text: "SEE THE PROP BOARD" }));
  card.appendChild(actions);
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
  const card = el("article", {
    class: `card2 panel chamfer card2--${tone}`,
    "data-hook": "card-total-pick",
    "data-rank": String(pick.position || pick.rank || ""),
    "data-label": pick.label || "",
    "data-market": pick.market || "",
  });

  const top = el("div", { class: "card2__top" });
  top.appendChild(el("span", { class: "card2__rank",
    text: `${pick.position || pick.rank || 1} OF ${total}` }));
  top.appendChild(el("span", { class: `card2__label card2__label--${tone}`,
    text: pick.label || "" }));
  if (pick.first_pitch_utc) {
    top.appendChild(el("span", { class: "card2__time",
      text: formatEasternTime(pick.first_pitch_utc) || "" }));
  }
  card.appendChild(top);

  // THE SENTENCE. Server-composed, same as the game picks' own bet line.
  card.appendChild(el("p", { class: "card2__bet", "data-hook": "card-total-bet",
    text: pick.bet || "" }));

  const matchup = el("div", { class: "card2__matchup" });
  matchup.appendChild(el("span", { class: "card2__teams",
    text: `${pick.away_team} at ${pick.home_team}` }));
  if (pick.book) {
    matchup.appendChild(el("span", { class: "card2__book",
      text: `${bookLabel(pick.book) || pick.book}${pick.books ? ` · best of ${pick.books} books` : ""}` }));
  }
  card.appendChild(matchup);

  const why = el("div", { class: "card2__why", "data-hook": "card-total-why" });
  for (const sentence of pick.why || []) {
    why.appendChild(el("p", { class: "card2__whyline", text: sentence }));
  }
  card.appendChild(why);

  // NO ACTION ROW while BETCHECK_SUPPORTS_TOTALS is false -- see that
  // constant's own comment. Unlike a prop pick, a total has no board of
  // its own to fall back to either, so nothing renders here at all until
  // Bet Check itself can take a totals ticket.
  if (BETCHECK_SUPPORTS_TOTALS) {
    const actions = el("div", { class: "card2__actions" });
    actions.appendChild(el("a", {
      class: "btn btn--ghost chamfer chamfer--btn",
      href: betCheckHref(pick),
      "data-hook": "card-check-this",
      text: "CHECK THIS PRICE YOURSELF" }));
    card.appendChild(actions);
  }
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
  // Named out loud. A reader is entitled to know that the last pick is on
  // the card because it was the next best thing available, not because
  // anything about it was convincing.
  return el("p", { class: "card2lede card2lede--mute",
    text: `${payload.filled} of tonight's picks are here because the slate `
        + `was thin — our own numbers do not agree with the market on `
        + `${payload.filled === 1 ? "it" : "them"}, and ${payload.filled === 1 ? "it is" : "they are"} `
        + `marked SPLIT.` });
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
function recordLine(rec) {
  const wrap = el("div", { class: "card2rec chamfer", "data-hook": "card-record" });
  wrap.appendChild(el("span", { class: "card2rec__label", text: "THE RECORD SO FAR" }));

  // EVERY DAY, INCLUDING THE ONES WITH NOTHING GRADED YET -- this is the
  // one link off the page that sells the product on its own past, so it
  // sits here whether or not this pooled summary has numbers to show yet.
  const seeFullRecord = () => el("a", { class: "card2rec__link", href: "#/record-card",
    "data-hook": "card-record-link", text: "SEE THE FULL RECORD, DAY BY DAY →" });

  if (!rec || !rec.n_staked) {
    wrap.appendChild(el("p", { class: "card2rec__body",
      text: "Nothing graded yet. Every card is settled the morning after, "
          + "win or lose, and the running record appears here from then on." }));
    wrap.appendChild(seeFullRecord());
    return wrap;
  }

  const line = el("p", { class: "card2rec__figures" });
  line.appendChild(el("span", { class: "card2rec__wl",
    text: `${rec.wins}-${rec.losses}${rec.pushes ? `-${rec.pushes}` : ""}` }));
  line.appendChild(el("span", { class: "card2rec__meta",
    text: `${rec.days} day${rec.days === 1 ? "" : "s"} · `
        + `${(rec.win_rate * 100).toFixed(0)}% of bets won · `
        + `${rec.profit_units > 0 ? "+" : ""}${rec.profit_units.toFixed(2)} units `
        + `at 1 unit a bet` }));
  wrap.appendChild(line);

  if (rec.voids) {
    wrap.appendChild(el("p", { class: "card2rec__body",
      text: `${rec.voids} pick${rec.voids === 1 ? "" : "s"} could not be `
          + `graded (game postponed or no final score). They count as neither `
          + `a win nor a loss and are left out of the return above.` }));
  }
  if (rec.chain_ok === false) {
    wrap.appendChild(el("p", { class: "card2rec__warn",
      text: "The record's tamper-proof chain does not currently verify, so "
          + "treat the numbers above as unconfirmed until it does." }));
  }
  wrap.appendChild(seeFullRecord());
  return wrap;
}

/** The one honest line about what a card is and is not, always rendered. */
function standingNote(payload) {
  const note = el("div", { class: "card2note chamfer", "data-hook": "card-standing-note" });
  note.appendChild(el("span", { class: "card2note__label", text: "READ THIS ONCE" }));
  note.appendChild(el("p", { class: "card2note__body", text: payload.disclaimer || "" }));
  note.appendChild(el("p", { class: "card2note__body card2note__body--mute",
    text: payload.basis || "" }));
  // What the letter beside each pick means -- served, never typed here, so
  // the page and the grader cannot disagree about it.
  for (const line of payload.knowledge_legend || []) {
    note.appendChild(el("p", { class: "card2note__body card2note__body--mute",
      "data-hook": "card-grade-legend", text: line }));
  }
  if (payload.calibrated === false) {
    // A card built without the calibration file publishes the raw model's
    // numbers, which run about twice as confident as they should. That is a
    // deploy fault and the reader is told rather than shown a number the
    // page cannot stand behind.
    note.appendChild(el("p", { class: "card2note__warn",
      text: "Our own probabilities are running uncalibrated right now, which "
          + "makes them read more confident than they should. The market "
          + "numbers beside them are unaffected." }));
  }
  return note;
}

function emptyCard(payload) {
  const wrap = el("section", { class: "gutter", "data-hook": "card-empty" });
  const panel = el("div", { class: "panel chamfer card2empty" });
  panel.appendChild(el("span", { class: "card2empty__label", text: "NO CARD TODAY" }));
  // VERBATIM. Every `reason` the server produces names a fact about the
  // world; composing a substitute here is how a page starts describing its
  // own confidence instead.
  panel.appendChild(el("p", { class: "card2empty__body",
    text: payload.reason || "Today's card is not available." }));
  const actions = el("div", { class: "card2empty__actions" });
  actions.appendChild(el("a", { class: "btn btn--primary chamfer chamfer--btn",
    href: "#/betcheck", text: "CHECK A BET OF YOUR OWN" }));
  actions.appendChild(el("a", { class: "btn btn--ghost chamfer chamfer--btn",
    href: "#/odds", text: "OPEN THE FULL BOARD" }));
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
export async function renderCard(host, date) {
  const wrap = el("section", { class: "gutter", "data-hook": "card" });
  host.appendChild(wrap);

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
  async function lastPublishedCard(fromDate) {
    const start = fromDate ? new Date(`${fromDate}T12:00:00Z`) : new Date();
    if (Number.isNaN(start.getTime())) return null;
    const day = new Date(start.getTime() - 86400000).toISOString().slice(0, 10);
    try {
      const older = await apiGet(`/card/${day}`,
                                 { timeoutMs: FALLBACK_TIMEOUT_MS });
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
    [payload, record] = await Promise.all([
      apiGet(`/card/${encodeURIComponent(date || "")}`),
      apiGet("/card/record").catch(() => null),
    ]);
  } catch (err) {
    const last = await lastPublishedCard(date);
    if (!last) {
      // Both the card and the fallback are unreachable. This really is an
      // outage, and the ORIGINAL error is the one that describes it -- not
      // the fallback's.
      renderError(wrap, err);
      return { rendered: false, firstPick: null };
    }
    payload = last;
    servingOlderCard = last.date || null;
    record = await apiGet("/card/record").catch(() => null);
  }

  if (!payloadHasBets(payload)) {
    const last = await lastPublishedCard(payload.date || date);
    if (last) {
      payload = last;
      servingOlderCard = last.date || null;
    }
    // If there is no published card anywhere either -- a first deploy, the
    // off-season -- `emptyCard` below still runs and states that plainly.
    // Saying nothing at all would be worse than saying there is nothing yet.
  }

  if (!payloadHasBets(payload)) {
    clear(wrap);
    wrap.appendChild(emptyCard(payload));
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
  if (servingOlderCard) {
    wrap.appendChild(el("p", { class: "card2lede", "data-hook": "card-older",
      // "already graded" was wrong and shipped for about ten minutes. A card
      // is published in the morning and graded after its games settle, so at
      // 10:52pm the card being shown here is frozen but NOT yet graded. It
      // is a small claim and it was still a false one, on the page whose
      // whole pitch is that the claims are checkable.
      text: `Tomorrow's card posts in the morning. These are the bets from `
          + `${servingOlderCard}, frozen before those games started.` }));
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
    wrap.appendChild(el("p", { class: "card2lede", "data-hook": "card-frozen",
      text: `Locked${at ? ` at ${at}` : ""}, before first pitch. Graded after — win or lose.` }));

    // A FROZEN PRICE IS A HISTORICAL FACT, NOT A QUOTE. On a slate with an
    // early game the card freezes in the morning, and a reader arriving at
    // 4pm would otherwise take "-149 at DraftKings" as a number they can
    // still get. Told plainly at the point of confusion rather than left to
    // the reader to work out from the timestamp.
    const ageHours = hoursSince(payload.frozen_at);
    if (ageHours !== null && ageHours >= STALE_PRICE_HOURS) {
      wrap.appendChild(el("p", { class: "card2lede card2lede--warn",
        "data-hook": "card-stale-prices",
        text: `These prices are ${Math.round(ageHours)} hours old — check the `
            + `current number before you bet.` }));
    }
  } else {
    wrap.appendChild(el("p", { class: "card2lede", "data-hook": "card-live",
      text: "Live prices — tonight's card is not locked in yet. It freezes "
          + "before first pitch, and from that point the bets and prices "
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
    for (const pick of picks) grid.appendChild(pickCard(pick, picks.length));
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

  wrap.appendChild(recordLine(record));
  wrap.appendChild(standingNote(payload));
  return { rendered: true, firstPick: firstPickOf(payload) };
}
