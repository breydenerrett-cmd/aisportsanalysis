/**
 * web/learning.html: how the hounds learn, and whether it helps.
 *
 * Reads GET /hounds/learning (src/hounds/learning/views.py: learning_payload) and, for the lessons beyond
 * the five it carries, GET /hounds/learning/lessons?page=. The top section, "Is the coach any good?", reads
 * GET /hounds/coach/report (src/hounds/coach_report.py): {computed, message, summary: {suggestions, refused,
 * graded_forward, helped, hurt, no_difference, too_early, forward_units_diff, hindsight_units_diff},
 * items: [{issue, hound_name, line, mode, hypothesis, recorded_utc, hindsight, forward: {label, n_paired,
 * units_diff}}], chain_ok, fans: {computed, message, summary: {tips, sent, helped, hurt, no_difference,
 * too_early, graded_forward, forward_units_diff, hindsight_units_diff}, items: [{issue, tip_id, nickname,
 * fan_name, count, hound_name, line, hindsight, forward}], versus: {line, hindsight_line, coach, fans}}}.
 * The "Fans vs the coach" block sits under the coach's list and is built from `fans` alone: fan tips are graded
 * by the same code and never counted in the coach's own numbers. Shapes of the scorecard:
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
import { h, clearNode, signed, isNum, fmtWhen, fmtUnits, describeError, NOT_REPORTED } from "./hounds-core.js";
import { friendlyLesson, campWords } from "./hounds-voice.js";
import { renderLineChart } from "./hounds-chart.js";

export const CHAMPION_COLOR = "#00E0FF";
export const CONTROL_COLOR = "#FFB020";
export const MIN_BETS_TEXT = "A comparison needs 50 measurable bets on each side.";

/** The coach report card's four live verdicts (src/hounds/coach_grade.py), as badges: always a word beside the emoji. */
export const COACH_BADGES = {
  "HELPED": { word: "HELPED", emoji: "✅", tone: "good" },
  "HURT": { word: "HURT", emoji: "❌", tone: "bad" },
  "NO DIFFERENCE": { word: "NO DIFFERENCE", emoji: "🪙", tone: "flat" },
  "TOO EARLY": { word: "TOO EARLY", emoji: "🐣", tone: "early" },
};

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

// ---- the coach report card (GET /hounds/coach/report) ----------------------------------------------------

/** The badge for a live verdict label; an unknown label gets a neutral one, never a guess. */
export function coachBadge(label) {
  const found = COACH_BADGES[String(label || "").trim().toUpperCase()];
  if (!found) return { text: "NOT GRADED 🐾", tone: "unknown", label: "" };
  return { text: `${found.word} ${found.emoji}`, tone: found.tone, label: found.word };
}

function plural(n, one, many) {
  return `${n} ${n === 1 ? one : many}`;
}

/** The headline sentence of the report card, from the server's summary counts. */
export function coachSummaryText(s) {
  if (!s || !isNum(s.suggestions) || (s.suggestions === 0 && !(s.refused > 0))) {
    return "No tips yet. The coach gets a shot every week, and every tip it makes is graded by code the day it lands.";
  }
  const decided = (s.helped || 0) + (s.hurt || 0) + (s.no_difference || 0);
  const bits = [`${plural(s.suggestions, "tip", "tips")} so far.`];
  bits.push(decided
    ? `${decided} graded live: ${s.helped || 0} helped, ${s.hurt || 0} hurt, ${s.no_difference || 0} no difference.`
    : "None has been graded live yet.");
  if (s.too_early > 0) bits.push(`${s.too_early} still too early to call (a verdict needs 20 settled bets).`);
  if (s.refused > 0) bits.push(`${plural(s.refused, "suggestion was", "suggestions were")} refused for breaking the rules.`);
  return bits.join(" ");
}

/** The two unit totals, hindsight labelled as a rehearsal. */
export function coachTotalsText(s) {
  if (!s) return "";
  const live = isNum(s.forward_units_diff) ? fmtUnits(s.forward_units_diff) : null;
  const hind = isNum(s.hindsight_units_diff) ? fmtUnits(s.hindsight_units_diff) : null;
  const parts = [];
  parts.push(live === null ? "Live: no settled games yet." : `Live, all tips together: ${live} against leaving the dogs alone (paper).`);
  if (hind !== null) {
    parts.push(`Hindsight: ${hind}. The coach could see that stretch before it spoke, so that one is a rehearsal, not a result.`);
  }
  return parts.join(" ");
}

export function coachItem(it) {
  const f = it.forward || {};
  const badge = coachBadge(f.label);
  const bits = [h("div", { class: "hd-badgeline" }, [
    h("span", { class: `hd-chip hd-chip--${badge.tone}`, "data-hook": "coach-badge", text: badge.text }),
    h("strong", { text: it.hound_name || it.hound || "A dog" }),
    it.recorded_utc ? h("span", { class: "hd-fine", text: fmtWhen(it.recorded_utc) }) : null,
  ]), h("p", { class: "hd-lesson__line", "data-hook": "coach-line", text: it.line || NOT_REPORTED })];
  if (it.hypothesis) {
    bits.push(h("p", { class: "hd-fine", text: `The coach's pitch, quoted: "${it.hypothesis}"` }));
  }
  if (it.mode === "challenger") {
    bits.push(h("p", { class: "hd-fine", text: "This one also made the rookie tryouts, where the rulebook decides." }));
  }
  return h("li", { class: "hd-lesson hd-coach-item", "data-label": badge.label, "data-issue": it.issue }, bits);
}

// ---- the fans (the fan lane of the same report card) -----------------------------------------------------------

/** The scoreboard line, from the server's `versus` block; hindsight is a second, labelled line. */
export function fanVersusText(v) {
  if (!v || typeof v.line !== "string") return "";
  return v.line;
}

export function fanSummaryText(s) {
  if (!s || !isNum(s.tips) || s.tips === 0) {
    return "No fan tips yet. Open any dog, tweak a dial under Coach this dog, and send it. It gets graded the same way the coach's tips do.";
  }
  const decided = (s.helped || 0) + (s.hurt || 0) + (s.no_difference || 0);
  const bits = [`${plural(s.tips, "fan tip", "fan tips")} graded so far.`];
  bits.push(decided
    ? `${decided} with a live verdict: ${s.helped || 0} helped, ${s.hurt || 0} hurt, ${s.no_difference || 0} no difference.`
    : "None has a live verdict yet.");
  if (s.too_early > 0) bits.push(`${s.too_early} still too early to call.`);
  return bits.join(" ");
}

export function fanItem(it) {
  const f = it.forward || {};
  const badge = coachBadge(f.label);
  const bits = [h("div", { class: "hd-badgeline" }, [
    h("span", { class: `hd-chip hd-chip--${badge.tone}`, "data-hook": "fan-badge", text: badge.text }),
    h("strong", { text: it.hound_name || it.hound || "A dog" }),
    it.tip_created_utc ? h("span", { class: "hd-fine", text: fmtWhen(it.tip_created_utc) }) : null,
  ]), h("p", { class: "hd-lesson__line", "data-hook": "fan-line", text: it.line || NOT_REPORTED })];
  return h("li", { class: "hd-lesson hd-fan-item", "data-label": badge.label, "data-tip": it.tip_id || "" }, bits);
}

function renderFans(box, report) {
  const fans = report && report.fans;
  if (!fans) return;     // an older server without the fan lane: the coach's card stands alone
  const block = h("div", { class: "hd-fans", "data-hook": "fans-block" });
  block.appendChild(h("h3", { "data-hook": "fans-title", text: "Fans vs the coach 🧠🆚🐶" }));
  block.appendChild(h("p", { class: "hd-muted", "data-hook": "fans-intro",
    text: "Anybody can tweak a dog's dials from its page. Code grades those tips exactly like the coach's: hindsight first, then live on new games. A fan tip never changes a dog, and it never counts in the coach's own numbers above." }));
  const v = fans.versus || {};
  const line = fanVersusText(v);
  if (line) block.appendChild(h("p", { "data-hook": "fans-versus", text: line }));
  if (v.hindsight_line) block.appendChild(h("p", { class: "hd-fine", "data-hook": "fans-versus-hindsight", text: v.hindsight_line }));
  const s = fans.summary || {};
  block.appendChild(h("p", { "data-hook": "fans-summary", text: fanSummaryText(s) }));
  const items = Array.isArray(fans.items) ? fans.items : [];
  if (!items.length) {
    block.appendChild(h("p", { class: "hd-muted", "data-hook": "fans-empty", text: campWords(fans.message) || fanSummaryText(null) }));
  } else {
    block.appendChild(h("ol", { class: "hd-lessons", "data-hook": "fans-list" }, items.map(fanItem)));
  }
  box.appendChild(block);
}

function renderCoach(result) {
  const box = q("coach-body");
  if (!box) return;
  clearNode(box);
  if (!result || !result.ok) {
    const e = describeError(result && result.error, "the coach report card");
    box.appendChild(h("div", { class: `hd-state hd-state--${e.kind}`, role: "status", "data-hook": "coach-state",
      "data-kind": e.kind }, [h("p", { text: e.text })]));
    return;
  }
  const report = result.value || {};
  const s = report.summary || {};
  box.appendChild(h("p", { "data-hook": "coach-summary", text: coachSummaryText(s) }));
  const facts = [["Tips made", s.suggestions], ["Tips refused", s.refused], ["HELPED ✅", s.helped],
    ["HURT ❌", s.hurt], ["NO DIFFERENCE 🪙", s.no_difference], ["TOO EARLY 🐣", s.too_early]];
  box.appendChild(h("dl", { class: "hd-row__facts", "data-hook": "coach-facts" },
    facts.map(([k, v]) => h("div", {}, [h("dt", { text: k }), h("dd", { text: isNum(v) ? String(v) : NOT_REPORTED })]))));
  const totals = coachTotalsText(s);
  if (totals) box.appendChild(h("p", { class: "hd-fine", "data-hook": "coach-totals", text: totals }));
  const items = Array.isArray(report.items) ? report.items : [];
  if (!items.length) {
    box.appendChild(h("p", { class: "hd-muted", "data-hook": "coach-empty",
      text: campWords(report.message) || "The coach has not made a tip yet. The first one shows up here, graded." }));
  } else {
    box.appendChild(h("ol", { class: "hd-lessons", "data-hook": "coach-list" }, items.map(coachItem)));
  }
  if (report.chain_ok === false) {
    box.appendChild(h("p", { class: "hd-state hd-state--down", "data-hook": "coach-chain",
      text: "The coach ledger failed its integrity check. Do not trust these numbers until it is looked at." }));
  }
  renderFans(box, report);
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
      text: campWords(payload.message) || "No daily scorecard has been stored yet." }));
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
    box.appendChild(h("p", { class: "hd-muted", text: campWords(payload.message) || "Not computed yet." }));
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

/** Fetch without throwing: ``{ok, value}`` or ``{ok: false, error}``. */
async function settle(promise) {
  try {
    return { ok: true, value: await promise };
  } catch (error) {
    return { ok: false, error };
  }
}

export async function boot() {
  // The coach report card is its own request: an older server without it, or a slow one, never blanks the
  // scorecard below it, and the scorecard being down never hides the card.
  const coachResult = settle(apiGet("/hounds/coach/report"));
  let payload;
  try {
    payload = await apiGet("/hounds/learning");
    if (!payload || typeof payload !== "object") throw Object.assign(new Error("empty"), { status: 502 });
  } catch (err) {
    renderCoach(await coachResult);
    const e = describeError(err, "the scorecard");
    for (const hook of ["learning-chance", "learning-hold", "learning-activity", "learning-rules", "learning-lessons"]) {
      const box = q(hook);
      if (box) { clearNode(box); box.appendChild(stateBox(e.kind, e.text, () => { boot(); })); }
    }
    return;
  }
  render(payload);
  renderCoach(await coachResult);
}

if (typeof document !== "undefined" && typeof window !== "undefined") {
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();
}
