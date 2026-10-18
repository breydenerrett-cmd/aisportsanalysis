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
import { friendlyLesson } from "./hounds-voice.js";
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
  const counts = `${w.champion_bets || 0} starter bets and ${w.control_bets || 0} control bets on ${w.games || 0} shared games`;
  if (!w.enough || !isNum(w.difference)) {
    return `Not enough bets yet (${counts}). ${MIN_BETS_TEXT}`;
  }
  const where = w.difference > 0 ? "above" : w.difference < 0 ? "below" : "level with";
  const gap = w.difference === 0 ? "" : `${Math.abs(w.difference).toFixed(2)} points `;
  return `The starters' prices averaged ${signed(w.champion_mean, 2)} points against the closing line and the controls' ${signed(w.control_mean, 2)}: `
    + `${gap}${where} the controls (${counts}). Averages from this many bets swing a lot, so read it as a scoreboard, not a verdict.`;
}

export function holdText(hit) {
  if (!hit || !isNum(hit.promotions) || hit.promotions === 0) {
    return "No rookie has made the team yet, so there is nothing to hold up. That's what camp looks like when it only promotes on evidence.";
  }
  if (!isNum(hit.matured) || hit.matured === 0) {
    return `${hit.promotions} ${hit.promotions === 1 ? "rookie has" : "rookies have"} made the team; none has made 100 bets as the starter yet, so there is no hit rate to report.`;
  }
  const pct = isNum(hit.rate) ? `${Math.round(hit.rate * 100)}%` : NOT_REPORTED;
  return `${hit.hits} of ${hit.matured} rookies who made the team priced at least as well as the starter they replaced (${pct}). `
    + `Camp shuts itself down below ${Math.round((hit.floor || 0.4) * 100)}% once ${hit.min_matured_for_floor || 10} of them have made 100 bets.`;
}

export function budgetText(fd) {
  if (!fd) return "Not reported.";
  return `Fluke check level ${fd.q}. Rookies who made the team this month: ${fd.promotions_this_month} (cap ${fd.monthly_cap_per_scope || fd.monthly_cap} per scope). `
    + `Most of those we'd expect to be flukes: ${isNum(fd.expected_false_promotions_bound) ? fd.expected_false_promotions_bound.toFixed(2) : NOT_REPORTED}.`;
}

/** The two lines of the chart: only the days both means were reported. */
export function historySeries(history) {
  const rows = (Array.isArray(history) ? history : []).filter(
    (r) => r && isNum(r.champion_mean_30) && isNum(r.control_mean_30));
  return [
    { id: "champions", name: "Starters (30-day average)", color: CHAMPION_COLOR,
      points: rows.map((r) => ({ date: r.date, value: r.champion_mean_30, bets: r.champion_bets_30 })) },
    { id: "controls", name: "Random controls (30-day average)", color: CONTROL_COLOR,
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
    box.appendChild(h("p", {}, [h("strong", { text: "Camp has shut itself down. " }),
      "No new rookie is accepted and none makes the team until the owner turns it back on."]));
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
  // (the server's own `basis` sentence is written in the vocabulary of the rulebook; the page words this itself)
  box.appendChild(h("p", { class: "hd-fine", "data-hook": "chance-basis",
    text: "Both sides pay the book's cut, so a dog that is no better than chance sits at the controls' level. \"Enough\" means 50 measurable bets on each side." }));
  if (isNum(vr.trailing_days) && vr.trailing_days > 0) {
    box.appendChild(h("p", { class: "hd-fine", "data-hook": "trailing",
      text: `The starters have trailed the controls on the last ${vr.trailing_days} daily scorecards in a row. Camp shuts itself down at 60.` }));
  }
  const series = historySeries(payload.history);
  chart.appendChild(renderLineChart({
    hook: "chance-chart", series, width: 640, height: 260, unit: "pts",
    label: "Rolling 30-day average price against the closing price, in points: the starters and the two random controls, same games",
    zeroLabel: "0 = the closing line",
    emptyText: "No daily scorecards with both lines yet.",
  }));
  chart.appendChild(h("ul", { class: "hd-legend hd-legend--static" }, [
    h("li", {}, [h("span", { class: "hd-tip__swatch", style: `background:${CHAMPION_COLOR}` }), " Starters: every running dog that is not a baseline, a control or a for-fun dog"]),
    h("li", {}, [h("span", { class: "hd-tip__swatch", style: `background:${CONTROL_COLOR}` }), " Random controls: Coin-Flip Collie and Dartboard Dalmatian (the coin and the dart)"]),
  ]));
  chart.appendChild(h("p", { class: "hd-fine",
    text: "Both lines sit below zero because every price taken carries the book's cut and the closing line doesn't. What matters is the gap between them." }));
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
  const items = [["Rookies sent to tryouts", act.proposals], ["Tryouts turned away", act.refusals],
    ["Rounds the coach sat out", act.held_rounds], ["Made the team", act.promotions], ["Cut", act.retirements],
    ["Tryouts that ended undecided", act.undecided], ["Coach moves the owner undid", act.undos],
    ["Trying out right now", payload.live_challengers]];
  box.appendChild(h("dl", { class: "hd-row__facts", "data-hook": "activity-facts" },
    items.map(([k, v]) => h("div", {}, [h("dt", { text: k }), h("dd", { text: isNum(v) ? String(v) : NOT_REPORTED })]))));
  box.appendChild(h("p", { "data-hook": "budget-text", text: budgetText(system.false_discovery_budget) }));
  const chain = payload.chain || {};
  const broken = Object.entries(chain).filter(([, ok]) => ok === false).map(([k]) => k);
  box.appendChild(h("p", { class: broken.length ? "hd-state hd-state--down" : "hd-fine", "data-hook": "chain-status",
    text: broken.length ? `A ledger failed its integrity check (${broken.join(", ")}). Do not trust the numbers above until it is looked at.`
      : "Every ledger in camp passes its tamper check." }));
}

function renderRules(payload) {
  const box = q("learning-rules");
  clearNode(box);
  const r = payload.rule_summary || {};
  const caps = payload.caps || {};
  const fd = payload.system && payload.system.false_discovery_budget;
  const lines = [
    "Who decides: a fixed rulebook, never an AI's opinion.",
    "The test: does the rookie's price beat the closing line by more than the starter's, on the same games. A pass counts as zero.",
    r.looks ? `The bar gets checked at ${r.looks.join(", ")} games in, and the allowance for luck is split across those checks (${(r.alpha_spend || []).join(", ")}).` : null,
    fd && fd.q !== undefined ? `Fluke check across each month's finished tryouts, at level ${fd.q}.` : "A fluke check runs across each month's finished tryouts.",
    caps.live_per_hound ? `At most ${caps.live_per_hound} rookies per dog and ${caps.live_per_scope} at once; one tryout offer per dog per ${caps.proposals_per_hound_days} days; at most ${caps.promotions_per_month_per_scope} rookies a month make the team.` : null,
    r.auto_pause ? `Camp shuts itself down if fewer than ${Math.round(r.auto_pause.hit_rate_floor * 100)}% of the rookies who made the team hold up (once ${r.auto_pause.after_matured_promotions} of them have made 100 bets), or if the starters trail the random controls for ${r.auto_pause.trailing_the_random_controls_days} days.` : null,
  ].filter(Boolean);
  box.appendChild(h("ul", { class: "hd-list-plain", "data-hook": "rules-list" }, lines.map((t) => h("li", { text: t }))));
}

export function lessonItem(l) {
  const when = l.utc ? fmtWhen(l.utc) : "";
  return h("li", { class: "hd-lesson", "data-outcome": l.outcome || "" }, [
    h("p", { class: "hd-lesson__line", text: friendlyLesson(l.lesson) || NOT_REPORTED }),
    h("p", { class: "hd-fine", text: `${when ? `${when}. ` : ""}The coach's pitch, quoted: ${l.hypothesis ? `"${l.hypothesis}"` : NOT_REPORTED}` }),
  ]);
}

function renderLessons(payload) {
  const box = q("learning-lessons");
  clearNode(box);
  const info = payload.lessons || { count: 0, latest: [] };
  if (!info.count) {
    box.appendChild(h("p", { class: "hd-muted", "data-hook": "lessons-empty",
      text: "No tryout has ended yet, so there are no lessons. They show up here the day one does." }));
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
