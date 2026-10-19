/**
 * web/hound.html?id=<model id>: one model.
 *
 * Reads GET /hounds/{id} (a HoundSummary plus `series` and the first page of `bets`),
 * GET /hounds/{id}/bets?status=open|graded&segment=&page= for the ticket tables, and
 * GET /hounds/series?ids=<id> when the detail payload does not carry the series. The shapes are
 * src/hounds/contract.py's. Each part loads on its own and says honestly what happened when its endpoint is
 * missing.
 *
 * TOP TO BOTTOM
 *   - the header: initials badge, name, status in plain words, type, sports and markets. Its catchphrase, if it
 *     has one, is a single small italic line; nothing else from a persona is shown;
 *   - Follow, Share and Download card (a star kept in this browser; a link; a PNG);
 *   - the KPI strip: Units, ROI, Record, Bets, CLV, Streak. Every figure is one the server sent, and a figure it
 *     did not send reads "n/a";
 *   - OPEN TICKETS (recorded, not yet graded; refreshed every minute while the tab is open) and GRADED TICKETS
 *     (paged by the server; Live, or Rehearsal which is never counted). Each row: date, game, pick, price, CLV
 *     points, status, units, the rule's reason line, and when it went on the record against the start;
 *   - the Rule: its exact text and, where it has any, its dials with their current values;
 *   - the bankroll chart (live bets only) and the status (the referee's verdict in plain words);
 *   - versions, the AI desk's argument (desk models only) and "Coach this model" (tunable models only).
 *
 * One disclosure bar (static markup in the page) carries paper-only / not-advice / 21+; this script never
 * repeats it. The page never claims an edge, never calls units profit, and says "n/a" before it guesses.
 */

import { apiGet } from "./api.js";
import {
  h, clearNode, monogram, categoryOf, houndColor, fmtRecord, fmtWhen, isNum, signed,
  normalizeSeries, pointsFor, hasForwardData, toChartPoints, segmentView, describeError, createPoller,
  REPLAY_NOTE, NOT_REPORTED, dayKey, unitsPairText, isWarming, retryWhileWarming, stopWarmingRetry,
  WARMING_FALLBACK_TEXT, VERDICT_MEANING, verdictLabel, fmtUnits, BEST_PRICE_WORDS, AVERAGE_PRICE_WORDS,
} from "./hounds-core.js";
import { unitsOf, causeText, personaOf } from "./hounds-voice.js";
import {
  NA, betsOf, roiOf, fmtRoi, fmtUnitsPlain, clvOf, statusOf, typeText, sportLabel, sportsOf, marketsText, recordText,
  streakText,
} from "./hounds-board.js";
import { ticketTable } from "./hounds-tickets.js";
import { renderLineChart } from "./hounds-chart.js";
import { bootDesk } from "./hounds-desk.js";
import { bootLineage } from "./hounds-lineage.js";
import { copyText, shareDog, downloadCard } from "./hounds-share.js";
import { isFollowed, toggleFollow } from "./hounds-follow.js";
import { loadRulebook, renderDials, renderCoach } from "./hounds-rulebook.js";

export const PAGE_SIZE = 20;
export const OPEN_POLL_MS = 60000;
const AVG_COLOR = "#E6EAF0";
const BEST_COLOR = "#8A93A3";

const SECTIONS = ["hound-actions", "hound-scoreboard-section", "hound-today-section", "hound-bets-section",
  "hound-rule-section", "hound-chart-section", "hound-verdict-section"];

const state = { id: "", hound: null, open: null, openError: null, graded: null, gradedError: null, segment: "forward",
  series: null, seriesError: null, rulebook: null, rulebookFailed: false, poller: null };

const q = (hook) => document.querySelector(`[data-hook='${hook}']`);

function stateBox(kind, text, retry) {
  const box = h("div", { class: `hd-state hd-state--${kind}`, role: kind === "down" ? "alert" : "status",
    "data-hook": "section-state", "data-kind": kind }, [h("p", { text })]);
  if (retry) box.appendChild(h("button", { type: "button", class: "btn btn--ghost hd-retry", text: "Try again",
    on: { click: retry } }));
  return box;
}

// ---- header ----------------------------------------------------------------------------------------

function renderHeader(hound) {
  const box = q("hound-header");
  clearNode(box);
  const cat = categoryOf(hound);
  const dead = hound.status === "retired";
  const persona = personaOf(hound);
  const st = statusOf(hound);
  document.title = `${hound.name || "Model"} — LINEHOUND`;
  const verified = hound.verified === true
    ? h("span", { class: "hd-verified", "data-hook": "verified", text: "Verified" })
    : hound.verified === false && isNum(hound.verified_share) ? h("span", { class: "hd-unverified", text: "Not verified" }) : null;
  const line = persona && persona.catchphrase ? persona.catchphrase : "";
  box.appendChild(monogram(hound.name, { size: 56, category: cat, muted: dead }));
  box.appendChild(h("div", { class: "hd-modelhead__text" }, [
    h("h1", { "data-hook": "hound-name", text: hound.name || NOT_REPORTED }),
    line ? h("p", { class: "hd-catch", "data-hook": "catchphrase", text: line }) : null,
    h("p", { class: "hd-chips" }, [
      h("span", { class: `hd-st hd-st--${st.tone}`, "data-hook": "hound-status", "data-status": st.key, title: st.title, text: st.text }),
      h("span", { class: "hd-typechip", "data-category": cat, text: typeText(hound) }),
      sportsOf(hound).length ? h("span", { class: "hd-chip-plain", text: sportsOf(hound).map(sportLabel).join(", ") }) : null,
      marketsText(hound) ? h("span", { class: "hd-chip-plain", text: marketsText(hound) }) : null,
      h("span", { class: "hd-chip-plain", text: hound.kind === "user"
        ? (hound.owner_display ? `Built by ${hound.owner_display}` : "Builder model") : hound.kind === "baseline" ? "Baseline" : "House model" }),
      verified,
    ]),
  ]));
  const retired = hound.retired && typeof hound.retired === "object" ? hound.retired : null;
  const causeBox = q("hound-cause");
  clearNode(causeBox);
  if (hound.status === "retired") {
    causeBox.hidden = false;
    causeBox.removeAttribute("hidden");
    causeBox.appendChild(h("p", {}, [h("strong", { text: "Retired. " }),
      (retired && retired.cause) ? causeText(retired.cause) : "No reason was given.",
      retired && retired.date ? h("span", { class: "hd-fine", text: ` (${fmtWhen(retired.date)})` }) : null]));
  } else if (hound.status === "benched" && hound.last_bet_utc) {
    causeBox.hidden = false;
    causeBox.removeAttribute("hidden");
    causeBox.appendChild(h("p", {}, [h("strong", { text: "Idle. " }),
      `Its last ticket was ${fmtWhen(hound.last_bet_utc)}; a model with no ticket for more than 7 days is marked idle.`]));
  }
}

// ---- follow, share, download -----------------------------------------------------------------------

export function renderActions(hound) {
  const box = q("hound-actions");
  if (!box) return;
  clearNode(box);
  const status = h("span", { class: "hd-fine", role: "status", "data-hook": "action-status" });
  const follow = h("button", { type: "button", class: "btn btn--ghost hd-follow", "data-hook": "follow-btn" });
  const paintFollow = (note) => {
    const on = isFollowed(state.id);
    follow.textContent = on ? "Following" : "Follow";
    follow.setAttribute("aria-pressed", on ? "true" : "false");
    follow.setAttribute("aria-label", on ? `Stop following ${hound.name || "this model"}` : `Follow ${hound.name || "this model"} in My models`);
    if (note) status.textContent = note;
  };
  follow.addEventListener("click", () => {
    const res = toggleFollow(state.id);
    paintFollow(res.followed
      ? (res.saved ? "Followed. It shows under My models on the leaderboard." : "Followed for this visit. This browser will not remember it.")
      : "Unfollowed.");
  });
  const share = h("button", { type: "button", class: "btn btn--ghost", "data-hook": "share-btn", text: "Share",
    on: { click: async () => { await shareDog(hound, state.id); } } });
  const card = h("button", { type: "button", class: "btn btn--ghost", "data-hook": "card-btn", text: "Download card",
    on: { click: async () => { await downloadCard(hound, state.id); } } });
  box.appendChild(follow);
  box.appendChild(share);
  box.appendChild(card);
  box.appendChild(status);
  paintFollow("");
}

// ---- KPI strip -------------------------------------------------------------------------------------

function kpi(slot, label, big, small, tone) {
  return h("div", { class: `hd-kpi hd-kpi--${tone || "plain"}`, "data-slot": slot }, [
    h("span", { class: "hd-kpi__label", text: label }),
    h("span", { class: "hd-kpi__big hd-num", text: big }),
    small ? h("span", { class: "hd-kpi__small", text: small }) : null,
  ]);
}

export function renderScoreboard(hound) {
  const box = q("hound-scoreboard");
  clearNode(box);
  const bets = betsOf(hound);
  const units = unitsOf(hound);
  const roi = roiOf(hound);
  const clv = clvOf(hound);
  const rec = hound.record || {};
  const toneOf = (n) => (n === null ? "plain" : n > 0 ? "up" : n < 0 ? "down" : "plain");
  const open = isNum(hound.open_bets) ? hound.open_bets : 0;
  const clvBig = clv && clv.beatPct !== null ? `${Math.round(clv.beatPct)}% beat` : (clv && clv.mean !== null ? `${signed(clv.mean, 1)} pts` : NA);
  const clvSmall = clv ? [clv.mean !== null ? `${signed(clv.mean, 1)} pts average` : "", clv.n ? `${clv.n} measurable bets` : ""].filter(Boolean).join(", ")
    : "no bet has a measurable closing price yet";
  const streak = streakText(hound);
  box.appendChild(h("div", { class: "hd-kpis", "data-hook": "scoreboard-tiles" }, [
    kpi("units", "Units", units === null ? NA : fmtUnitsPlain(units),
      units === null ? "nothing graded yet" : `${AVERAGE_PRICE_WORDS}; ${fmtUnitsPlain(rec.units_recorded_price)} at ${BEST_PRICE_WORDS}`, toneOf(units)),
    kpi("roi", "ROI", fmtRoi(roi), roi === null ? "" : "units per bet", toneOf(roi)),
    kpi("record", "Record", recordText(hound), bets > 0 ? "wins-losses" + (rec.pushes ? "-pushes" : "") : "no graded bets"),
    kpi("bets", "Bets", String(bets), open > 0 ? `${open} open` : (bets < 100 && bets > 0 ? "small sample" : "")),
    kpi("clv", "CLV", clvBig, clvSmall),
    kpi("streak", "Streak", streak || NA, streak ? (streak.startsWith("W") ? "wins in a row" : "losses in a row") : "no graded bets"),
  ]));
}

// ---- the status, the numbers, the rule -------------------------------------------------------------

function renderVerdict(hound) {
  const box = q("hound-verdict");
  clearNode(box);
  const st = statusOf(hound);
  box.appendChild(h("div", { class: "hd-badgeline" }, [
    h("span", { class: `hd-st hd-st--${st.tone} hd-st--lg`, "data-hook": "badge", "data-badge": st.key, text: st.text }),
    h("p", { class: "hd-badgeline__explain", "data-hook": "badge-explain", text: st.title }),
  ]));
  box.appendChild(h("p", { class: "hd-verdict__meaning", "data-hook": "verdict-meaning",
    text: VERDICT_MEANING[verdictLabel(hound)] || "This model has no verdict. Treat the result as unproven." }));
  const graded = betsOf(hound);
  box.appendChild(h("p", { class: "hd-fine", "data-hook": "verdict-sample",
    text: `Based on ${graded} graded live ${graded === 1 ? "bet" : "bets"}.${graded < 100 ? " That is a small sample." : ""}` }));
  if (hound.verdict && hound.verdict.sentence) {
    box.appendChild(h("p", { class: "hd-verdict__sentence", "data-hook": "verdict-sentence", text: hound.verdict.sentence }));
  }
  if (hound.verdict && hound.verdict.units_note) {
    box.appendChild(h("p", { class: "hd-fine", "data-hook": "units-note", text: hound.verdict.units_note }));
  }
}

function resultLines(hound) {
  const box = q("hound-results");
  clearNode(box);
  const fwd = segmentView(hound, "forward");
  const fRec = fwd && fwd.record;
  box.appendChild(h("dl", { class: "hd-defs hd-defs--row", "data-hook": "forward-facts" }, [
    h("div", {}, [h("dt", { text: "Live record" }), h("dd", { text: fRec && fRec.bets > 0 ? fmtRecord(fRec) : "no graded bets" })]),
    h("div", {}, [h("dt", { text: "First / last ticket" }), h("dd", { text:
      `${fmtWhen(hound.first_bet_utc) || NA} / ${fmtWhen(hound.last_bet_utc) || NA}` })]),
    fRec && fRec.bets > 0 ? h("div", {}, [h("dt", { text: "Units, two ways" }), h("dd", { "data-hook": "units-pair", text: unitsPairText(fRec) })]) : null,
  ]));
  const rep = hound.replay && typeof hound.replay === "object" ? hound.replay : null;
  if (rep) {
    box.appendChild(h("p", { class: "hd-fine", "data-hook": "replay-line" }, [
      h("strong", { text: REPLAY_NOTE }), ": ", rep.bets > 0 ? fmtRecord(rep) : "no rehearsal reported",
      rep.bets > 0 ? `; ${fmtUnits(rep.units_recorded_price)} ${BEST_PRICE_WORDS}` : ""]));
  }
}

function renderRule(hound, specHref) {
  const box = q("hound-rule");
  clearNode(box);
  const text = hound.rule_text || "";
  box.appendChild(h("pre", { class: "hd-rule", "data-hook": "rule-text", tabindex: "0",
    text: text || "The rule text was not sent for this model." }));
  const status = h("span", { class: "hd-fine", role: "status", "data-hook": "copy-status" });
  const btn = h("button", { type: "button", class: "btn btn--ghost", "data-hook": "copy-rule", text: "Copy rule",
    "aria-label": "Copy this model's rule to the clipboard",
    on: { click: async () => { status.textContent = (await copyText(text)) ? "Copied the rule." : "Could not copy. Select the text and copy it by hand."; } } });
  if (!text) btn.setAttribute("disabled", "");
  box.appendChild(h("div", { class: "hd-rule__actions" }, [btn,
    h("a", { class: "btn btn--ghost", href: specHref, "data-hook": "build-from", text: "Build one like this" }), status]));
}

async function startRulebook(hound) {
  const { rb, failed } = await loadRulebook(state.id);
  state.rulebook = rb;
  state.rulebookFailed = failed;
  renderDials(q("hound-dials"), rb, failed);
  const coach = q("hound-coach-section");
  if (coach) {
    const live = rb && rb.tunable && hound.status !== "retired";
    if (live) {
      coach.removeAttribute("hidden");
      renderCoach(coach, { houndId: state.id, rb });
    } else {
      coach.setAttribute("hidden", "");
    }
  }
}

// ---- charts ----------------------------------------------------------------------------------------

function chartWidth(panel) {
  const box = panel && panel.getBoundingClientRect ? panel.getBoundingClientRect() : null;
  const w = box && box.width ? box.width : 640;
  return Math.max(300, Math.min(900, Math.round(w)));
}

export function renderCharts() {
  const units = q("hound-units-chart");
  const clv = q("hound-clv-chart");
  clearNode(units); clearNode(clv);
  if (state.seriesError) {
    const e = describeError(state.seriesError, "the charts");
    units.appendChild(stateBox(e.kind, e.text));
    return;
  }
  if (state.series === null) {
    units.appendChild(h("p", { class: "hd-muted", text: "Loading the charts..." }));
    return;
  }
  const title = q("hound-chart-title");
  const pts = pointsFor(state.series, state.id, "forward");
  const hasPoints = pts.length > 0 || hasForwardData(state.series);
  title.textContent = hasPoints
    ? "Live bets only: placed after the rule was written. Cumulative units, one unit a bet."
    : "No graded live bets yet, so there is nothing to draw. A rehearsal result is never drawn here.";
  const width = chartWidth(units);
  units.appendChild(renderLineChart({
    hook: "units-chart",
    series: [
      { id: "avg", name: "Average price", color: AVG_COLOR, points: toChartPoints(pts, "cum_units_average_price") },
      { id: "best", name: "Best price", color: BEST_COLOR, points: toChartPoints(pts, "cum_units_recorded_price") },
    ],
    dashes: [undefined, "7 4"], width, height: width < 480 ? 240 : 300, unit: "units",
    label: "Cumulative units, live bets, at the average price and at the best price",
    zeroLabel: "0 units",
    emptyText: hasPoints ? "No graded bets to draw yet." : "No graded live bets yet.",
  }));
  units.appendChild(h("ul", { class: "hd-legend hd-legend--static" }, [
    h("li", {}, [h("span", { class: "hd-tip__swatch", style: `background:${AVG_COLOR}` }),
      " Average price: the mean price across books when the bet was placed (the headline)"]),
    h("li", {}, [h("span", { class: "hd-tip__swatch", style: `background:${BEST_COLOR}` }),
      " Best price: the single best quote recorded when the bet was placed"]),
  ]));
  clv.appendChild(h("h3", { class: "hd-h3", text: "CLV, running average" }));
  clv.appendChild(renderLineChart({
    hook: "clv-chart",
    series: [{ id: "clv", name: "Running average vs the close", color: houndColor(state.hound || {}), points: toChartPoints(pts, "cum_clv_mean_pts") }],
    width, height: 190, unit: "pts",
    label: "Running average of price versus the closing price, in points, live bets",
    zeroLabel: "0 = same as the close",
    emptyText: "Nothing measured against the close yet.",
  }));
  clv.appendChild(h("p", { class: "hd-fine", text: "Above zero means the prices taken beat the closing line, on average so far. A handful of bets can swing it either way; the status looks at the whole run." }));
}

// ---- tickets ---------------------------------------------------------------------------------------

/** A page of bets as the server sends it: {items, page, page_size, total, pages}. */
function betsPageOf(data) {
  if (Array.isArray(data)) return { items: data, page: 1, page_size: data.length || PAGE_SIZE, total: data.length, pages: 1 };
  const items = Array.isArray(data && data.items) ? data.items : [];
  const total = isNum(data && data.total) ? data.total : items.length;
  const size = isNum(data && data.page_size) && data.page_size > 0 ? data.page_size : PAGE_SIZE;
  return { items, page: isNum(data && data.page) ? data.page : 1, page_size: size, total,
    pages: isNum(data && data.pages) ? data.pages : Math.max(1, Math.ceil(total / size)) };
}

function renderOpen() {
  const box = q("hound-today");
  if (!box) return;
  clearNode(box);
  if (state.openError && !state.open) {
    const e = describeError(state.openError, "the open tickets");
    box.appendChild(stateBox(e.kind, e.text, () => { loadOpen(); }));
    return;
  }
  if (state.open === null) { box.appendChild(h("p", { class: "hd-muted", text: "Checking open tickets..." })); return; }
  const note = q("today-note");
  if (note) note.textContent = "";
  if (state.open.items.length === 0) {
    const trigger = state.rulebook && state.rulebook.trigger;
    box.appendChild(h("p", { class: "hd-muted", "data-hook": "open-empty",
      text: state.hound && state.hound.status === "retired" ? "This model is retired. It has no open tickets."
        : `No open tickets. This model bets when ${trigger || "its rule fires"}; boards refresh through the day.` }));
    return;
  }
  box.appendChild(ticketTable(state.open.items, { graded: false, hook: "open-table", caption: "Open tickets, recorded and waiting to be graded" }));
  if (state.open.total > state.open.items.length && note) {
    note.textContent = `Showing the newest ${state.open.items.length} of ${state.open.total} open tickets.`;
  }
}

async function loadOpen() {
  state.openError = null;
  try {
    const data = await apiGet(`/hounds/${encodeURIComponent(state.id)}/bets?status=open&segment=forward&page=1&page_size=50`);
    state.open = betsPageOf(data);
  } catch (err) {
    state.openError = err;
  }
  renderOpen();
}

function renderSegmentBar() {
  const bar = q("bets-segment");
  if (!bar) return;
  clearNode(bar);
  for (const [key, text] of [["forward", "Live"], ["replay", "Rehearsal (not counted)"]]) {
    bar.appendChild(h("button", { type: "button", class: "hd-seg", "data-segment": key,
      "aria-pressed": state.segment === key ? "true" : "false",
      on: { click: () => { state.segment = key; loadGraded(1); } } }, text));
  }
}

function renderGraded() {
  const box = q("hound-bets");
  clearNode(box);
  renderSegmentBar();
  if (state.gradedError) {
    const e = describeError(state.gradedError, "the graded tickets");
    box.appendChild(stateBox(e.kind, e.text, () => { loadGraded(state.graded ? state.graded.page : 1); }));
    return;
  }
  if (state.graded === null) { box.appendChild(h("p", { class: "hd-muted", text: "Loading the tickets..." })); return; }
  const page = state.graded;
  if (page.total === 0) {
    box.appendChild(h("p", { class: "hd-muted", "data-hook": "bets-empty",
      text: state.segment === "replay" ? "No rehearsal tickets for this model." : "No graded tickets yet." }));
    return;
  }
  box.appendChild(ticketTable(page.items, { graded: true, hook: "bets-table", caption: "Graded tickets, newest first" }));
  box.appendChild(h("div", { class: "hd-pager", "data-hook": "bets-pager" }, [
    h("button", { type: "button", class: "btn btn--ghost", "data-hook": "bets-prev", text: "Newer",
      disabled: page.page <= 1 ? "" : undefined, on: { click: () => { loadGraded(page.page - 1); } } }),
    h("span", { class: "hd-fine", "data-hook": "bets-page", role: "status",
      text: `Page ${page.page} of ${page.pages} (${page.total} tickets)` }),
    h("button", { type: "button", class: "btn btn--ghost", "data-hook": "bets-next", text: "Older",
      disabled: page.page >= page.pages ? "" : undefined, on: { click: () => { loadGraded(page.page + 1); } } }),
  ]));
}

/** One page of graded tickets from the server (a model can have hundreds). */
async function loadGraded(pageNo = 1) {
  state.gradedError = null;
  renderGraded();
  const size = state.graded ? state.graded.page_size : PAGE_SIZE;
  try {
    const data = await apiGet(`/hounds/${encodeURIComponent(state.id)}/bets?status=graded&segment=${state.segment}&page=${pageNo}&page_size=${size}`);
    state.graded = betsPageOf(data);
  } catch (err) {
    state.gradedError = err;
  }
  renderGraded();
}

// ---- boot ------------------------------------------------------------------------------------------

function setSections(hidden) {
  for (const hook of SECTIONS) {
    const sec = q(hook);
    if (!sec) continue;
    if (hidden) sec.setAttribute("hidden", ""); else sec.removeAttribute("hidden");
  }
}

export async function boot() {
  const params = new URLSearchParams(window.location.search || "");
  state.id = params.get("id") || "";
  const hero = q("hound-header");
  if (!state.id) {
    hero.appendChild(stateBox("missing", "No model was chosen. Pick one from the leaderboard."));
    setSections(true);
    return;
  }
  let hound;
  try {
    hound = await apiGet(`/hounds/${encodeURIComponent(state.id)}`);
    if (!hound || typeof hound !== "object") throw Object.assign(new Error("empty"), { status: 404 });
  } catch (err) {
    clearNode(hero);
    const e = describeError(err, "this model");
    hero.appendChild(stateBox(err && err.status === 404 ? "missing" : e.kind,
      err && err.status === 404 ? "There is no model with this id. It may have been removed, or the link is wrong." : e.text,
      err && err.status === 404 ? null : () => { boot(); }));
    setSections(true);
    return;
  }
  if (isWarming(hound)) {
    clearNode(hero);
    hero.appendChild(stateBox("warming", hound.message || WARMING_FALLBACK_TEXT));
    setSections(true);
    retryWhileWarming("hound", () => {
      stopWarmingRetry("hound");
      setSections(false);
      clearNode(hero);
      boot();
    }, hound);
    return;
  }
  state.hound = hound;
  renderHeader(hound);
  renderScoreboard(hound);
  resultLines(hound);
  renderVerdict(hound);
  renderRule(hound, `build-a-hound.html?from=${encodeURIComponent(state.id)}`);
  renderActions(hound);
  startRulebook(hound);           // loads on its own: the dials and the coach never hold the page up

  // the AI desk's models also show how they argued their newest game (every other model never sees this)
  bootDesk(hound);
  // versions and challengers (the learning loop): loads on its own and never takes this page down
  bootLineage(hound);

  loadOpen();
  if (state.poller) state.poller.stop();
  if (hound.status !== "retired") {
    state.poller = createPoller({ run: () => { loadOpen(); }, intervalMs: OPEN_POLL_MS });
    state.poller.start();
  }
  loadGraded(1);

  renderCharts();
  if (Array.isArray(hound.series)) {
    state.series = normalizeSeries({ series: { [state.id]: hound.series } });
    state.seriesError = null;
  } else {
    try {
      state.series = normalizeSeries(await apiGet(`/hounds/series?ids=${encodeURIComponent(state.id)}`));
      state.seriesError = null;
    } catch (err) {
      state.series = null;
      state.seriesError = err;
    }
  }
  renderCharts();
}

export { copyText };
export const __state = state;
export { dayKey, verdictLabel };

if (typeof document !== "undefined" && typeof window !== "undefined") {
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();
}
