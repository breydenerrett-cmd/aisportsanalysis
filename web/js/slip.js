/**
 * THE ENGINE'S SLIP (src/engine/slip.py) -- the ranked, evidence-tiered
 * picks list the engine freezes for a date, independent of THE CARD.
 *
 * MOVED HERE FROM today.js, 2026-09-12 (docs/DECISION_TODAY_ONE_ANSWER.md,
 * option A1, owner-approved). Two different answers to "what do I bet
 * tonight" were rendering on the same screen: THE CARD (market-confidence
 * ranked, src/analysis/daily_card.py) led #/today, and this slip
 * (agreement-ranked, a stricter and usually much shorter list) sat right
 * below it. On the two nights checked, the two #1 picks named a different
 * game. A customer does not reconcile that; they pick the one they read
 * first and act on it as if it were the other one's confidence.
 *
 * The slip has real research value -- it is the engine's own output, kept
 * honest about its own tier of evidence -- but it has published only seven
 * bets tagged "published" ever, as of this decision. Seven is too few for
 * any track record, and this module does not invent one: the honesty note
 * is a dated fact about the decision that moved this page, not a live
 * count this file recomputes (nothing on GET /today exposes a running
 * total of tagged slip picks, and if it did, hardcoding today's number here
 * would go stale the next time one more got tagged). THE CARD's own record
 * -- separately kept, never pooled with this one -- is what leads Today
 * now; this slip moved to #/performance ("RESEARCH -- NOT THE CARD"),
 * under its own heading saying plainly what it is.
 *
 * Rendering is otherwise UNCHANGED from what shipped on Today: same cards,
 * same evidence-tier chips, same collapsed-thesis teaser, same gv2-picks
 * CSS (screens.css). Only the caller and the surrounding copy are new.
 */

import { el, formatAmerican } from "./dom.js";
import { bookLabel } from "./labels.js";

// Renders NOTHING (host stays untouched) when:
//   - `slip` is null: `engine slip` has not reached this date yet. This is
//     an operational gap, not a customer fact.
//   - `slip.read_as === "NOTHING_CLEARED"`: the honest empty case -- no
//     published pick cleared the evidence floor. Nothing to show; nothing
//     to apologise for either.
const EVIDENCE_TIER_TONE = {
  STRONG: "green", BUILDING: "yellow", THIN: "orange", MINIMAL: "red",
};

function evidenceTierChip(pick) {
  const tier = pick.evidence_tier || "MINIMAL";
  const tone = EVIDENCE_TIER_TONE[tier] || "red";
  return el("span", { class: `gv2-picks__tier gv2-picks__tier--${tone}`,
    title: pick.evidence_tier_label || "" }, [tier]);
}

// src/engine/slate.py's SCOPE_MARKETS, spelled out -- a plain lookup rather
// than a generic word-capitalizer, because a generic one reads "h2h" as
// "H2h" and "1st" as "1St" (CSS text-transform:capitalize breaks on any
// token starting with a digit, which several of these do).
const MARKET_LABEL = {
  h2h: "Moneyline",
  spreads: "Run line",
  totals: "Total",
  h2h_1st_5_innings: "First 5 innings moneyline",
};

function pickWagerLine(pick) {
  // The server renders the club, the side and the book into one sentence
  // (src/board/readable.py's `wager_text`, joined through the event map).
  // The fallback below is for a payload that lacks it: no event_id -> game
  // join is attempted here, because guessing one risks the silent-mismatch
  // bug the stand-down telemetry join had before it was keyed correctly on
  // game_pk -- see src/report/stand_downs.py's own history.
  if (pick.wager_text) return pick.wager_text;
  const market = MARKET_LABEL[pick.market_key] || String(pick.market_key || "market");
  const price = formatAmerican(pick.price_american);
  const bits = [market];
  if (price) bits.push(`at ${price}`);
  if (pick.book) bits.push(`(${bookLabel(pick.book) || pick.book})`);
  return bits.join(" ");
}

function pickCard(pick) {
  const card = el("article", { class: "gv2-picks__card panel chamfer",
    "data-hook": "tonights-pick", "data-rank": String(pick.rank) });
  const head = el("div", { class: "gv2-picks__card-head" });
  head.appendChild(el("span", { class: "gv2-picks__rank" }, [`#${pick.rank}`]));
  head.appendChild(evidenceTierChip(pick));
  card.appendChild(head);
  card.appendChild(el("p", { class: "gv2-picks__wager" }, [pickWagerLine(pick)]));
  if (pick.thesis) {
    // The real mechanism text, in full -- src/engine/explain.py's own
    // percentile-and-sample-size prose (owner directive: "the thesis is the
    // product"). Long enough that showing all of it on every card by
    // default would bury the scannable part; collapsed to a short teaser
    // with the rest one click away, never shortened or paraphrased.
    //
    // Cut by a character budget, not by "first sentence": this prose is
    // parenthetical-heavy ("(each side's number describes ...): away 36.9%,
    // home 61.4% (... away over 176 batted balls; home over 1,563 ...)"),
    // so the first period-or-semicolon lands deep inside an aside, not at a
    // real sentence break -- a punctuation-based split produced a "teaser"
    // that was most of the paragraph.
    const full = String(pick.thesis);
    const TEASER_CHARS = 92;
    let teaser = full;
    if (full.length > TEASER_CHARS + 20) {
      const cut = full.lastIndexOf(" ", TEASER_CHARS);
      teaser = full.slice(0, cut > 40 ? cut : TEASER_CHARS) + "…";
    }
    if (teaser === full) {
      card.appendChild(el("p", { class: "gv2-picks__thesis" }, [full]));
    } else {
      const details = el("details", { class: "gv2-picks__thesis-details" });
      details.appendChild(el("summary", { class: "gv2-picks__thesis" }, [teaser]));
      details.appendChild(el("p", { class: "gv2-picks__thesis gv2-picks__thesis--rest" },
        [full]));
      card.appendChild(details);
    }
  }
  // "Agree" implies more than one; a single system has fired, not agreed
  // with itself. n_systems > n_families only when near-duplicate genomes
  // were folded into one independent source (doctrine amendment 9) -- named
  // here so the discount stays auditable rather than a silent subtraction.
  const agreementLine = pick.n_families === 1
    ? "1 system's signal"
    : `${pick.n_families} independent systems agree`;
  const meta = el("p", { class: "gv2-picks__meta" },
    [agreementLine
     + (pick.n_systems > pick.n_families ? ` (${pick.n_systems} systems, family-discounted)` : "")
     + ` · ${pick.books_at_decision} books at decision`]);
  card.appendChild(meta);
  if (pick.evidence_tier_label) {
    card.appendChild(el("p", { class: "gv2-picks__tier-label" }, [pick.evidence_tier_label]));
  }
  return card;
}

/** THE SLIP, standalone -- same cards this rendered on Today, same rule
 * ("ranked by how many independent systems agree"). This function renders
 * only the picks grid plus (optionally) its own short eyebrow/headline/sub;
 * it carries no fixed opinion about where it sits on the page -- the
 * caller supplies `copy` to say that.
 *
 * `copy` (all optional; omit a field to render nothing for it):
 *   eyebrow / headline / sub -- override text, or `null` to render none.
 *     Default is undefined, which falls back to the copy this rendered on
 *     Today ("TONIGHT'S PICKS" etc) -- kept only so a future caller that
 *     wants that framing does not have to retype it, NOT because anything
 *     calls it that way today (performance.js, the only caller, always
 *     passes its own research-framed copy; see renderEngineSlipSection).
 *   nested -- true drops the `gutter` class, which pads a section meant to
 *     span the full browser width. The one caller mounts this inside an
 *     already-padded
 *     panel; a second full gutter inside that panel is what made the
 *     research slip render as double-padded amber-callout box (checker
 *     finding, 2026-09-12) -- `gutter` was copied from Today's top-level
 *     placement along with everything else and never revisited for a
 *     nested one. */
export function renderTonightsPicks(slip, copy) {
  if (!slip || slip.read_as === "NOTHING_CLEARED") return null;
  const picks = Array.isArray(slip.picks) ? slip.picks : [];
  if (picks.length === 0) return null;

  const light = slip.read_as === "LIGHT";
  const nested = Boolean(copy && copy.nested);
  const wrap = el("section", { class: `gv2-picks gv2-picks--${light ? "light" : "notable"}${nested ? "" : " gutter"}`,
    "data-hook": "tonights-picks", "data-rise": "" });

  const defaultEyebrow = light ? "TONIGHT'S LEAN" : "TONIGHT'S PICKS";
  const defaultHeadline = light
    ? "Thin night. If you're betting anyway, here's where the evidence points."
    : "Where our systems currently see the strongest case.";
  const defaultSub = light
    ? "None of tonight's evidence is strong. We'd sit tonight out — but " +
      "these are the real, floor-cleared plays, honestly labelled thin."
    : "Ranked by how many independent systems agree and how deep their " +
      "signal cleared — never by a promised outcome. No system here claims " +
      "a guaranteed winner.";
  const eyebrow = copy && "eyebrow" in copy ? copy.eyebrow : defaultEyebrow;
  const headline = copy && "headline" in copy ? copy.headline : defaultHeadline;
  const sub = copy && "sub" in copy ? copy.sub : defaultSub;

  if (eyebrow) wrap.appendChild(el("span", { class: "gv2-picks__eyebrow" }, [eyebrow]));
  if (headline) wrap.appendChild(el("h2", { class: "gv2-picks__headline" }, [headline]));
  if (sub) wrap.appendChild(el("p", { class: "gv2-picks__sub" }, [sub]));

  const top3 = picks.filter((p) => (p.cohorts || []).includes("TOP_3"));
  const rest = picks.filter((p) => !(p.cohorts || []).includes("TOP_3"));

  const grid = el("div", { class: "gv2-picks__grid" });
  for (const pick of top3) grid.appendChild(pickCard(pick));
  wrap.appendChild(grid);

  if (rest.length) {
    const details = el("details", { class: "gv2-picks__more" });
    details.appendChild(el("summary", {}, [`${rest.length} more published pick${rest.length === 1 ? "" : "s"}`]));
    const moreGrid = el("div", { class: "gv2-picks__grid" });
    for (const pick of rest) moreGrid.appendChild(pickCard(pick));
    details.appendChild(moreGrid);
    wrap.appendChild(details);
  }

  return wrap;
}
