/**
 * The Gematria Hound's part of web/hound.html: "Evidence", behind a tap.
 *
 * WHAT THE HOUND IS. A hound in the category `numerology` (config/ai_hounds.json, family "gematria"; src/hounds/gematria) works out,
 * for each side of a game, the numerical coincidences that side's win would produce (name values, the date, founding-date spans,
 * counts from our stored results), and bets the side with the larger total only when it leads by a set margin and the price is fair.
 * It claims nothing: the page says it is experimental, its record is shown like any hound's, and the search size sits beside every
 * score so a number of matches is never read without the number of chances it had.
 *
 * THE SHAPE READ HERE is src/hounds/gematria/view.py's, from GET /hounds/{id}/gematria:
 *   `{hound_id, started, copy, picks: [{event_id, date, sport, start_utc, away, home, selection, side, price, result, rules_version,
 *   hound_version, scores: {home, away}, margin, threshold, comparisons: {home, away}, search_space, matches: {home, away}, history,
 *   evidence: {home: [item], away: [item]}}]}`, an item being `{kind, value, weight, a: {label, value, cipher?}, b?: {...}, note?}`.
 *
 * EVERY STRING IS PLAIN TEXT. Labels carry team, coach and school names from feeds; they are put on the page with textContent only
 * (the `h()` builder's `text`), never as markup.
 */

import { apiGet } from "./api.js";
import { h, clearNode, categoryOf, describeError, fmtPrice, shortDate, isNum } from "./hounds-core.js";

export const NUMEROLOGY = "numerology";
export const EXPERIMENTAL_LINE = "Experimental numerology hound. Paper picks, graded in public like every hound.";
export const NO_PICKS_TEXT =
  "No pick yet. It weighs every game an hour before it starts and passes unless one side's numbers clearly lead; "
  + "each pick it makes will show its evidence for both sides here.";

export const KIND_WORDS = {
  headline_milestone: "headline count matches",
  milestone_eq_name: "count equals a name value",
  milestone_eq_state: "count equals a state's order of statehood",
  milestone_eq_date: "count equals a number of the date",
  milestone_eq_span: "count equals a span from a founding date",
  milestone_eq_count: "count equals a game or meeting number",
  milestone_eq_milestone: "two counts are equal",
  prime_link: "prime-number link",
  triangular_link: "triangular-number link",
  special_33_47: "a count of 33 or 47",
  own_name_eq_date: "a name value equals a number of the date",
};

const q = (hook) => document.querySelector(`[data-hook='${hook}']`);

function show(node, on) {
  if (!node) return;
  node.hidden = !on;
  if (on) node.removeAttribute("hidden"); else node.setAttribute("hidden", "");
}

export function isNumerologyHound(hound) {
  return categoryOf(hound) === NUMEROLOGY;
}

function sideName(pick, which) {
  return which === "home" ? pick.home : pick.away;
}

function quantityText(x) {
  if (!x || typeof x !== "object") return "";
  return String(x.label || "");
}

/** One evidence item as a list row: its kind in words, the two quantities, and the weight. */
export function evidenceRow(item) {
  const it = item && typeof item === "object" ? item : {};
  const parts = [quantityText(it.a)];
  if (it.b) parts.push(quantityText(it.b));
  const kind = KIND_WORDS[it.kind] || String(it.kind || "match");
  return h("li", { class: "hd-ev__item", "data-kind": String(it.kind || "") }, [
    h("span", { class: "hd-ev__kind", text: kind }),
    h("span", { class: "hd-ev__what", text: `${parts.filter(Boolean).join("  =  ")}${it.note ? ` (${it.note})` : ""}` }),
    h("span", { class: "hd-fine hd-ev__w", text: isNum(it.weight) ? `weight ${it.weight}` : "" }),
  ]);
}

function sideBlock(pick, which) {
  const items = pick.evidence && Array.isArray(pick.evidence[which]) ? pick.evidence[which] : [];
  const score = pick.scores && isNum(pick.scores[which]) ? pick.scores[which] : null;
  const total = pick.matches && isNum(pick.matches[which]) ? pick.matches[which] : items.length;
  const tried = pick.comparisons && isNum(pick.comparisons[which]) ? pick.comparisons[which] : null;
  const picked = pick.side === which;
  const head = `${sideName(pick, which) || which}${picked ? " (picked)" : ""}: ${score === null ? "no score" : score} from ${total} matches`
    + `${tried === null ? "" : ` of ${tried} comparisons`}`;
  return h("div", { class: "hd-ev__side", "data-side": which, "data-picked": picked ? "yes" : "no" }, [
    h("h4", { class: "hd-ev__sidehead", text: head }),
    items.length
      ? h("ul", { class: "hd-ev__list" }, items.map(evidenceRow))
      : h("p", { class: "hd-muted", text: "No matches were found for this side." }),
    total > items.length ? h("p", { class: "hd-fine", text: `Showing the ${items.length} heaviest of ${total}.` }) : null,
  ]);
}

/** One pick: a summary line you can tap, and inside it both sides' evidence, the margin and the price. */
export function renderPick(pick) {
  const when = shortDate(pick.start_utc || pick.date) || "";
  const result = pick.result ? String(pick.result) : "open";
  const price = isNum(pick.price) ? fmtPrice(pick.price) : "price not reported";
  const margin = isNum(pick.margin) ? Math.abs(pick.margin) : null;
  return h("details", { class: "hd-ev__pick", "data-hook": "evidence-pick", "data-result": result.toLowerCase() }, [
    h("summary", {}, [
      h("span", { class: "hd-ev__game", text: `${when}  ${pick.away || "?"} at ${pick.home || "?"}` }),
      h("span", { class: "hd-ev__sel", text: `${pick.selection || "pick"}  ${price}` }),
      h("span", { class: "hd-chip hd-ev__result", text: result }),
    ]),
    h("p", { class: "hd-ev__line", "data-hook": "evidence-summary", text:
      `Margin ${margin === null ? "not reported" : margin}${isNum(pick.threshold) ? ` (it needs ${pick.threshold})` : ""}. `
      + `${isNum(pick.search_space) ? `${pick.search_space} comparisons tried in all. ` : ""}`
      + `Rules ${pick.rules_version || "?"}${pick.history ? `; counts from ${pick.history}` : ""}.` }),
    // the picked side first, then the other: the other side's matches are the posts' warning bullets
    ...(pick.side === "home" ? ["home", "away"] : ["away", "home"]).map((w) => sideBlock(pick, w)),
  ]);
}

export function renderEvidence(payload) {
  const wrap = h("div", { "data-hook": "evidence-body" });
  wrap.appendChild(h("p", { class: "hd-muted", "data-hook": "evidence-copy", text: EXPERIMENTAL_LINE }));
  const picks = payload && Array.isArray(payload.picks) ? payload.picks : [];
  if (!picks.length) {
    wrap.appendChild(h("p", { class: "hd-muted", "data-hook": "evidence-none", text: NO_PICKS_TEXT }));
    return wrap;
  }
  wrap.appendChild(h("p", { class: "hd-fine", text:
    "Matches are numbers that happen to be equal. With this many numbers in play, some match by chance, so each score is shown "
    + "with the comparisons it came from." }));
  picks.forEach((p) => wrap.appendChild(renderPick(p)));
  return wrap;
}

/** Show the Evidence fold for a numerology hound and fill it. Every other hound never sees it. */
export async function bootGematria(hound) {
  const fold = q("hound-evidence");
  const on = isNumerologyHound(hound);
  show(fold, on);
  if (!fold || !on) return;
  const box = q("hound-evidence-box");
  clearNode(box);
  try {
    const payload = await apiGet(`/hounds/${encodeURIComponent(hound.id)}/gematria`);
    box.appendChild(renderEvidence(payload));
  } catch (err) {
    const e = describeError(err, "the evidence");
    box.appendChild(h("div", { class: `hd-state hd-state--${e.kind}`, role: "status", "data-hook": "section-state", "data-kind": e.kind },
      [h("p", { text: e.text })]));
  }
  if (/[?&]open=evidence\b/.test(window.location.search)) fold.open = true;
}
