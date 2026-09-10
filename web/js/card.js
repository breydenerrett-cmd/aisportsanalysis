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
  top.appendChild(el("span", { class: "card2__rank",
    text: `${pick.rank} OF ${total}` }));
  top.appendChild(el("span", { class: `card2__label card2__label--${tone}`,
    text: pick.label || "" }));
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

  const meaning = LABEL_MEANING[pick.label];
  if (meaning) {
    card.appendChild(el("p", { class: "card2__meaning", text: meaning }));
  }

  const actions = el("div", { class: "card2__actions" });
  actions.appendChild(el("a", {
    class: "btn btn--ghost chamfer chamfer--btn",
    href: betCheckHref(pick),
    "data-hook": "card-check-this",
    text: "CHECK THIS PRICE YOURSELF" }));
  card.appendChild(actions);
  return card;
}

/** The one honest line about what a card is and is not, always rendered. */
function standingNote(payload) {
  const note = el("div", { class: "card2note chamfer", "data-hook": "card-standing-note" });
  note.appendChild(el("span", { class: "card2note__label", text: "READ THIS ONCE" }));
  note.appendChild(el("p", { class: "card2note__body", text: payload.disclaimer || "" }));
  note.appendChild(el("p", { class: "card2note__body card2note__body--mute",
    text: payload.basis || "" }));
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

/**
 * Mount the card into `host`. Returns true when picks rendered, so the
 * caller can decide what the rest of the screen says beneath it.
 *
 * A fetch failure renders the error and returns false -- it must never look
 * like a night with no picks, which is a different and real condition.
 */
export async function renderCard(host, date) {
  const wrap = el("section", { class: "gutter", "data-hook": "card" });
  host.appendChild(wrap);

  let payload;
  try {
    payload = await apiGet(`/card/${encodeURIComponent(date || "")}`);
  } catch (err) {
    renderError(wrap, err);
    return false;
  }

  const picks = payload.picks || [];
  if (!picks.length) {
    clear(wrap);
    wrap.appendChild(emptyCard(payload));
    return false;
  }

  const meta = payload.games_on_slate
    ? `${picks.length} of ${payload.games_on_slate} games`
    : `${picks.length} picks`;
  wrap.appendChild(sectionHead("TONIGHT'S CARD", meta));
  wrap.appendChild(el("p", { class: "card2lede",
    text: "Frozen before first pitch. Every one of these is graded win or "
        + "lose on the record page, including the ones that lose." }));

  const grid = el("div", { class: "card2grid", "data-hook": "card-grid" });
  for (const pick of picks) grid.appendChild(pickCard(pick, picks.length));
  wrap.appendChild(grid);

  if (payload.filled) {
    // Named out loud. A reader is entitled to know that the last pick is on
    // the card because it was the next best thing available, not because
    // anything about it was convincing.
    wrap.appendChild(el("p", { class: "card2lede card2lede--mute",
      text: `${payload.filled} of tonight's picks are here because the slate `
          + `was thin — our own numbers do not agree with the market on `
          + `${payload.filled === 1 ? "it" : "them"}, and ${payload.filled === 1 ? "it is" : "they are"} `
          + `marked SPLIT.` }));
  }

  wrap.appendChild(standingNote(payload));
  return true;
}
