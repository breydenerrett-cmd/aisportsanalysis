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
  // A STRONG pick already carries a STRONG chip and a sentence reading "The
  // market makes Yankees a 74% bet to win and our own numbers agree at 64%".
  // Printing "The market and our numbers both make this side a clear
  // favourite" under that says the same thing a third time in vaguer words.
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

  // Two reads, and the record must never take the card down with it: a
  // failed record fetch is not a night with no picks, and the picks are the
  // thing the reader came for.
  let payload;
  let record = null;
  let servingOlderCard = null;
  try {
    [payload, record] = await Promise.all([
      apiGet(`/card/${encodeURIComponent(date || "")}`),
      apiGet("/card/record").catch(() => null),
    ]);
  } catch (err) {
    // THE PAGE MUST NOT SHOW AN ERROR WHERE THE BETS GO.
    //
    // After the slate rolls in the evening this asks for TOMORROW's card,
    // and tomorrow's card does not exist until the morning pass publishes
    // it. On 2026-09-10 at 10:23pm that rendered "REQUEST FAILED — We could
    // not reach the board" directly beneath the record strip: the honest
    // message for a timeout, and the wrong one for a card that simply has
    // not been written yet.
    //
    // The owner's standing rule is that this product always has bets on it.
    // So: fall back to the most recently published card and SAY that is what
    // it is. Old and labelled beats an error where the picks should be, and
    // it beats inventing a card for a slate nobody has looked at.
    try {
      const history = await apiGet("/card/history?limit=1");
      const last = ((history && history.days) || [])[0];
      if (last && (last.picks || []).length) {
        payload = last;
        servingOlderCard = last.date || null;
        record = await apiGet("/card/record").catch(() => null);
      } else {
        renderError(wrap, err);
        return false;
      }
    } catch (_fallbackErr) {
      // Both failed -- this really is unreachable, and the original error is
      // the one worth showing, not the fallback's.
      renderError(wrap, err);
      return false;
    }
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
  // Named for what it is. A card from an earlier slate must never sit under
  // a heading that says TONIGHT'S.
  wrap.appendChild(sectionHead(
    servingOlderCard ? "LAST PUBLISHED CARD" : "TONIGHT'S CARD", meta));
  if (servingOlderCard) {
    wrap.appendChild(el("p", { class: "card2lede", "data-hook": "card-older",
      text: `Tomorrow's card posts in the morning. These are the bets from `
          + `${servingOlderCard}, already graded on the record.` }));
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

  wrap.appendChild(recordLine(record));
  wrap.appendChild(standingNote(payload));
  return true;
}
