/**
 * web/learning.html: how the hounds learn, and whether it helps.
 *
 * Reads GET /hounds/learning (src/hounds/learning/views.py: learning_payload) and, for the lessons beyond
 * the five it carries, GET /hounds/learning/lessons?page=. Shapes:
 *
 *   {computed, message, as_of, system: {promotion_hit_rate: {promotions, matured, hits, rate, floor,
 *      min_matured_for_floor}, vs_random: {windows: {"30": W, "90": W}, controls, basis, trailing_days},
 *      activity: {...}, false_discovery_budget: {...}, paused, pause_reasons: [{scope, reason, since}]},
 *    history: [{date, champion_mean_30, control_mean_30, difference_30, ...}], rule_summary, caps,
 *    lessons: {count, latest: [Lesson]}, chain: {house: bool, user: bool}, live_challengers}
 *   W = {days, games, champion_bets, control_bets, champion_mean, control_mean, difference, enough}
 *
 * HONESTY RULES. A scorecard that has not been computed is a sentence, not a zero. A comparison with fewer
 * than 50 bets on a side says so and shows the counts, not a number. The "random-control line" chart draws
 * the champions' and the controls' rolling 30-day mean closing-line value only where both were reported.
 * Nothing here calls a number profit or claims an advantage; "better than chance" is the claim being
 * tested, and a quiet page is the loop working as designed.
 */

import { apiGet } from "./api.js";
import { h, clearNode, signed, isNum, fmtWhen, describeError, NOT_REPORTED } from "./hounds-core.js";
import { renderLineChart } from "./hounds-chart.js";

export const CHAMPION_COLOR = "#00E0FF";
export const CONTROL_COLOR = "#FFB020";
export const MIN_BETS_TEXT = "A comparison needs 50 measurable bets on each side.";

const q = (hook) => document.querySelector(`[data-hook='${hook}']`);

function stateBox(kind, text, retry) {
  const box = h("div", { class: `hd-state hd-state--${kind}`, role: kind === "down" ? "alert" : "status",
    "data-hook": "section-state", "data-kind": kind }, [h("p", { text })]);
  if (retry) box.appendChild(h("button", { type: "button", class: "btn btn--ghost hd-retry", text: "Try again",
    on: { click: retry } }));
  return box;
}

// ---- pure text ----------------------------------------------------------------------------------------

/** One rolling window of the chance comparison, in words. */
export function chanceLine(w) {
  if (!w) return "Not reported.";
  const counts = `${w.champion_bets || 0} champion bets and ${w.control_bets || 0} control bets on ${w.games || 0} shared games`;
  if (!w.enough || !isNum(w.difference)) {
    return `Not enough bets yet (${counts}). ${MIN_BETS_TEXT}`;
  }
  const where = w.difference > 0 ? "above" : w.difference < 0 ? "below" : "level with";
  const gap = w.difference === 0 ? "" : `${Math.abs(w.difference).toFixed(2)} points `;
  return `The champions' prices averaged ${signed(w.champion_mean, 2)} points against the close and the controls' ${signed(w.control_mean, 2)}: `
    + `${gap}${where} the controls (${counts}). Averages from this many bets move a lot; this is a measurement, not a result.`;
}

export function holdText(hit) {
  if (!hit || !isNum(hit.promotions) || hit.promotions === 0) {
    return "No challenger has been promoted yet, so there is nothing to hold up. That is expected for a loop that promotes only on evidence.";
  }
  if (!isNum(hit.matured) || hit.matured === 0) {
    return `${hit.promotions} ${hit.promotions === 1 ? "challenger has" : "challengers have"} been promoted; none has made 100 bets as champion yet, so there is no hit rate to report.`;
  }
  const pct = isNum(hit.rate) ? `${Math.round(hit.rate * 100)}%` : NOT_REPORTED;
  return `${hit.hits} of ${hit.matured} matured promotions priced at least as well as the champion they replaced (${pct}). `
    + `The loop pauses itself below ${Math.round((hit.floor || 0.4) * 100)}% once ${hit.min_matured_for_floor || 10} have matured.`;
}

export function budgetText(fd) {
  if (!fd) return "Not reported.";
  return `False-discovery level ${fd.q}. Promotions this month: ${fd.promotions_this_month} (cap ${fd.monthly_cap_per_scope || fd.monthly_cap} per scope). `
    + `Expected number of those that are flukes, at most: ${isNum(fd.expected_false_promotions_bound) ? fd.expected_false_promotions_bound.toFixed(2) : NOT_REPORTED}.`;
}

/** The two lines of the chart: only the days both means were reported. */
export function historySeries(history) {
  const rows = (Array.isArray(history) ? history : []).filter(
    (r) => r && isNum(r.champion_mean_30) && isNum(r.control_mean_30));
  return [
    { id: "champions", name: "Champions (30-day mean)", color: CHAMPION_COLOR,
      points: rows.map((r) => ({ date: r.date, value: r.champion_mean_30, bets: r.champion_bets_30 })) },
    { id: "controls", name: "Random controls (30-day mean)", color: CONTROL_COLOR,
      points: rows.map((r) => ({ date: r.date, value: r.control_mean_30 })) },
  ];
}

// ---- sections -----------------------------------------------------------------------------------------

function renderPaused(system) {
  const box = q("learning-paused");
  clearNode(box);
  if (system && system.paused) {
    box.hidden = false;
    box.removeAttribute("hidden");
    const reasons = Array.isArray(system.pause_reasons) ? system.pause_reasons : [];
    box.appendChild(h("p", {}, [h("strong", { text: "The loop has paused itself. " }),
      "No new challenger is accepted and none is promoted until the owner turns it back on."]));
    for (const r of reasons) {
      box.appendChild(h("p", { class: "hd-fine", "data-hook": "pause-reason",
        text: `${r.scope}: ${r.reason || "no reason recorded"}${r.since ? ` (since ${fmtWhen(r.since)})` : ""}` }));
    }
  } else {
    box.hidden = true;
    box.setAttribute("hidden", "");
  }
}

function renderChance(payload) {
  const box = q("learning-chance");
  const chart = q("learning-chance-chart");
  clearNode(box);
  clearNode(chart);
  const system = payload.system || {};
  const vr = system.vs_random;
  if (!payload.computed || !vr) {
    box.appendChild(h("p", { class: "hd-muted", "data-hook": "not-computed",
      text: payload.message || "No daily scorecard has been stored yet." }));
    return;
  }
  const wins = vr.windows || {};
  const rows = [["30", "Last 30 days"], ["90", "Last 90 days"]].map(([key, title]) => {
    const w = wins[key];
    return h("div", { "data-window": key }, [h("dt", { text: title }), h("dd", { "data-hook": `chance-${key}`, text: chanceLine(w) })]);
  });
  box.appendChild(h("dl", { class: "hd-row__facts hd-facts--big", "data-hook": "chance-windows" }, rows));
  if (vr.basis) box.appendChild(h("p", { class: "hd-fine", text: vr.basis }));
  if (isNum(vr.trailing_days) && vr.trailing_days > 0) {
    box.appendChild(h("p", { class: "hd-fine", "data-hook": "trailing",
      text: `The champions have trailed the controls on the last ${vr.trailing_days} daily scorecards in a row. The loop pauses itself at 60.` }));
  }
  const series = historySeries(payload.history);
  chart.appendChild(renderLineChart({
    hook: "chance-chart", series, width: 640, height: 260, unit: "pts",
    label: "Rolling 30-day mean price against the closing price, in points: the champions and the two random controls, same games",
    zeroLabel: "0 = the closing price",
    emptyText: "No daily scorecards with both lines yet.",
  }));
  chart.appendChild(h("ul", { class: "hd-legend hd-legend--static" }, [
    h("li", {}, [h("span", { class: "hd-tip__swatch", style: `background:${CHAMPION_COLOR}` }), " Champions: every running hound that is not a baseline, a control or a for-fun hound"]),
    h("li", {}, [h("span", { class: "hd-tip__swatch", style: `background:${CONTROL_COLOR}` }), " Random controls: Coin-Flip Collie and Dartboard Dalmatian"]),
  ]));
  chart.appendChild(h("p", { class: "hd-fine",
    text: "Both lines sit below zero because every price taken carries the book's margin and the close does not. What matters is the gap between them." }));
}

function renderHold(payload) {
  const box = q("learning-hold");
  clearNode(box);
  const hit = payload.system && payload.system.promotion_hit_rate;
  box.appendChild(h("p", { "data-hook": "hold-text", text: holdText(hit) }));
}

function renderActivity(payload) {
  const box = q("learning-activity");
  clearNode(box);
  const system = payload.system || {};
  const act = system.activity;
  if (!act) {
    box.appendChild(h("p", { class: "hd-muted", text: payload.message || "Not computed yet." }));
    return;
  }
  const items = [["Challengers proposed", act.proposals], ["Proposals refused", act.refusals],
    ["Rounds where the coach held", act.held_rounds], ["Promoted", act.promotions], ["Retired", act.retirements],
    ["Closed undecided", act.undecided], ["Coach changes the owner undid", act.undos],
    ["Running in shadow now", payload.live_challengers]];
  box.appendChild(h("dl", { class: "hd-row__facts", "data-hook": "activity-facts" },
    items.map(([k, v]) => h("div", {}, [h("dt", { text: k }), h("dd", { text: isNum(v) ? String(v) : NOT_REPORTED })]))));
  box.appendChild(h("p", { "data-hook": "budget-text", text: budgetText(system.false_discovery_budget) }));
  const chain = payload.chain || {};
  const broken = Object.entries(chain).filter(([, ok]) => ok === false).map(([k]) => k);
  box.appendChild(h("p", { class: broken.length ? "hd-state hd-state--down" : "hd-fine", "data-hook": "chain-status",
    text: broken.length ? `A ledger failed its integrity check (${broken.join(", ")}). Do not trust the numbers above until it is looked at.`
      : "Every ledger of the loop passes its hash-chain check." }));
}

function renderRules(payload) {
  const box = q("learning-rules");
  clearNode(box);
  const r = payload.rule_summary || {};
  const caps = payload.caps || {};
  const lines = [
    `Who decides: ${r.who_decides || "the referee, never a model"}.`,
    `The test: ${r.test || "paired closing-line value, challenger minus champion"}.`,
    r.looks ? `Looks at ${r.looks.join(", ")} paired games, with the error spent across them (${(r.alpha_spend || []).join(", ")}).` : null,
    r.false_discovery_control ? `Across all challengers: ${r.false_discovery_control}.` : null,
    caps.live_per_hound ? `At most ${caps.live_per_hound} challengers per hound and ${caps.live_per_scope} at once; one proposal per hound per ${caps.proposals_per_hound_days} days; at most ${caps.promotions_per_month_per_scope} promotions a month.` : null,
    r.auto_pause ? `It pauses itself if fewer than ${Math.round(r.auto_pause.hit_rate_floor * 100)}% of matured promotions hold up (after ${r.auto_pause.after_matured_promotions}), or if the champions trail the random controls for ${r.auto_pause.trailing_the_random_controls_days} days.` : null,
  ].filter(Boolean);
  box.appendChild(h("ul", { class: "hd-list-plain", "data-hook": "rules-list" }, lines.map((t) => h("li", { text: t }))));
}

export function lessonItem(l) {
  const when = l.utc ? fmtWhen(l.utc) : "";
  return h("li", { class: "hd-lesson", "data-outcome": l.outcome || "" }, [
    h("p", { class: "hd-lesson__line", text: l.lesson || NOT_REPORTED }),
    h("p", { class: "hd-fine", text: `${when ? `${when}. ` : ""}Coach's reason, quoted: ${l.hypothesis ? `"${l.hypothesis}"` : NOT_REPORTED}` }),
  ]);
}

function renderLessons(payload) {
  const box = q("learning-lessons");
  clearNode(box);
  const info = payload.lessons || { count: 0, latest: [] };
  if (!info.count) {
    box.appendChild(h("p", { class: "hd-muted", "data-hook": "lessons-empty",
      text: "No challenger has ended yet, so there are no lessons. They appear here the day one does." }));
    return;
  }
  box.appendChild(h("ol", { class: "hd-lessons", "data-hook": "lessons-list" }, info.latest.map(lessonItem)));
  const total = info.count;
  if (total > info.latest.length) {
    let page = 1;
    const more = h("button", { type: "button", class: "btn btn--ghost", "data-hook": "lessons-more", text: "Show older lessons" });
    more.addEventListener("click", async () => {
      page += 1;
      try {
        const data = await apiGet(`/hounds/learning/lessons?page=${page}&page_size=5`);
        const list = q("lessons-list");
        for (const l of (data.items || [])) list.appendChild(lessonItem(l));
        if (page >= (data.pages || 1)) more.setAttribute("hidden", "");
      } catch (err) {
        box.appendChild(stateBox("down", describeError(err, "the older lessons").text));
      }
    });
    box.appendChild(more);
  }
}

export function render(payload) {
  renderPaused(payload.system);
  renderChance(payload);
  renderHold(payload);
  renderActivity(payload);
  renderRules(payload);
  renderLessons(payload);
}

export async function boot() {
  let payload;
  try {
    payload = await apiGet("/hounds/learning");
    if (!payload || typeof payload !== "object") throw Object.assign(new Error("empty"), { status: 502 });
  } catch (err) {
    const e = describeError(err, "the scorecard");
    for (const hook of ["learning-chance", "learning-hold", "learning-activity", "learning-rules", "learning-lessons"]) {
      const box = q(hook);
      if (box) { clearNode(box); box.appendChild(stateBox(e.kind, e.text, () => { boot(); })); }
    }
    return;
  }
  render(payload);
}

if (typeof document !== "undefined" && typeof window !== "undefined") {
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();
}
