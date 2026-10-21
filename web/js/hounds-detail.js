/**
 * web/hound.html?id=<model id>: one model.
 *
 * Reads GET /hounds/{id} (a HoundSummary plus `series` and the first page of `bets`),
 * GET /hounds/{id}/bets?status=open|ungraded|graded&segment=&page= for the ticket tables, and
 * GET /hounds/series?ids=<id> when the detail payload does not carry the series. The shapes are
 * src/hounds/contract.py's. Each part loads on its own and says honestly what happened when its endpoint is
 * missing.
 *
 * TOP TO BOTTOM
 *   - the header: initials badge, name, status in plain words, type, sports and markets. Its catchphrase, if it
 *     has one, is a single small italic line; nothing else from a persona is shown;
 *   - Follow, Share and Download card (a star kept in this browser; a link; a PNG);
 *   - the season toggle (Season 2 | Season 1 | All-time; the URL's ?season=, then localStorage, then Season 2) for
 *     the numbers below it, and the KPI strip: Bankroll (the $1,000 paper account now), Return (24h / 7d / 30d / Season tabs), Units, Record,
 *     Max drawdown, Yield ("profit per $ bet", the old ROI), Bets, CLV, Streak, all for that season. The
 *     referee's status stays all-time and says so. Every figure is one the server sent, and a figure it
 *     did not send reads "n/a";
 *   - OPEN TICKETS (recorded, not yet graded and not stale; refreshed every minute while the tab is open),
 *     UNGRADED TICKETS (more than 36 hours past the start with no grade: listed apart with a count, never open,
 *     never in the record; the section is hidden when there are none) and GRADED TICKETS
 *     (paged by the server; Live, or Rehearsal which is never counted; its own season chip, which defaults to
 *     every season). Each row: date, game, pick, price, CLV
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
  NA, betsOf, fmtUnitsPlain, clvOf, statusOf, typeText, sportLabel, sportsOf, marketsText, recordText,
  streakText, ungradedBetsOf, bankrollOf, bankrollRules, bankrollNow, windowOf, totalUnitsOf, yieldOf, drawdownOf,
  isSmallSample, smallSampleTitle, settledOf, fmtUsd, fmtSignedUsd, fmtPct, WINDOW_LABELS, WINDOW_WORDS,
  basisOf, basisWords,
} from "./hounds-board.js";
import { ticketTable } from "./hounds-tickets.js";
import { settleGrades } from "./first-grade.js";
import { playReveal, MAX_FLIPS } from "./reveal-fx.js";
import { celebrate } from "./dog-common.js";
import { ALL_SEASON, seasonOptions, chooseSeason, saveSeason, seasonParam } from "./hounds-season.js";
import { renderLineChart } from "./hounds-chart.js";
import { bootDesk } from "./hounds-desk.js";
import { bootLineage } from "./hounds-lineage.js";
import { copyText, shareDog, downloadCard } from "./hounds-share.js";
import { isFollowed, toggleFollow } from "./hounds-follow.js";
import { loadRulebook, renderDials, renderCoach } from "./hounds-rulebook.js";
import { bootDogKit } from "./dog-kit.js";
import { dogFace, poseOfHound } from "./dog-avatar.js";

export const PAGE_SIZE = 20;
export const OPEN_POLL_MS = 60000;
const AVG_COLOR = "#E6EAF0";
const BEST_COLOR = "#8A93A3";

const SECTIONS = ["hound-actions", "hound-scoreboard-section", "hound-today-section", "hound-bets-section",
  "hound-rule-section", "hound-chart-section", "hound-verdict-section"];

const state = { id: "", season: "", seasonMeta: null, betsSeason: ALL_SEASON, hound: null, open: null, openError: null, ungraded: null, graded: null, gradedError: null, segment: "forward",
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
  const face = dogFace(hound, { size: 84, pose: dead ? "sad" : poseOfHound(hound) });
  face.setAttribute("data-hook", "header-badge");
  if (dead) face.setAttribute("style", "opacity:.6");
  box.appendChild(face);
  box.appendChild(h("div", { class: "hd-modelhead__text" }, [
    h("h1", { "data-hook": "hound-name", text: hound.name || NOT_REPORTED }),
    line ? h("p", { class: "hd-catch", "data-hook": "catchphrase", text: line }) : null,
    h("p", { class: "hd-chips" }, [
      h("span", { class: `hd-st hd-st--${st.tone}`, "data-hook": "hound-status", "data-status": st.key, title: st.title, text: st.text }),
      h("span", { class: "hd-typechip", "data-category": cat, text: typeText(hound) }),
      sportsOf(hound).length || marketsText(hound) ? h("span", { class: "hd-chip-plain", "data-hook": "where",
        text: [sportsOf(hound).map(sportLabel).join(", "), marketsText(hound)].filter(Boolean).join(" · ") }) : null,
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
    const buried = !!(retired && /^buried/i.test(String(retired.cause || "")));
    causeBox.appendChild(h("p", {}, [h("strong", { text: buried ? "Buried. " : "Retired. " }),
      (retired && retired.cause) ? causeText(retired.cause) : "No reason was given.",
      retired && retired.date ? h("span", { class: "hd-fine", text: ` (${fmtWhen(retired.date)})` }) : null,
      // an owner's removal keeps the whole record; say so, since the dog is gone from the lists but not from the ledger
      retired && /retired by the owner/i.test(String(retired.cause || "")) ? h("span", { class: "hd-fine", "data-hook": "retired-record-stays",
        text: " Its tickets and record stay on the ledger." }) : null]));
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

// ---- the season the numbers cover ------------------------------------------------------------------

/** The toggle above the KPI strip (Season 2 | Season 1 | All-time) and one line saying what the figures cover. */
export function renderSeasonBar() {
  const bar = q("hound-season");
  if (bar) {
    clearNode(bar);
    for (const o of seasonOptions(state.seasonMeta)) {
      bar.appendChild(h("button", { type: "button", class: "hd-seg", "data-season": o.id,
        "aria-pressed": state.season === o.id ? "true" : "false", on: { click: () => { switchSeason(o.id); } } }, o.text));
    }
  }
  const line = q("hound-season-line");
  if (line) {
    const meta = state.hound && state.hound.season;
    line.textContent = state.season === ALL_SEASON
      ? "The numbers below cover every forward bet. The status is the referee's all-time verdict."
      : `The numbers below cover ${meta && meta.label ? meta.label : "this season"} only. The status is the referee's all-time verdict.`;
  }
}

/** Show another season's figures: the model's summary and series again from the server; the ticket lists stay as they are. */
async function switchSeason(id) {
  if (id === state.season) return;
  state.season = id;
  saveSeason(id);
  renderSeasonBar();
  try {
    const data = await apiGet(`/hounds/${encodeURIComponent(state.id)}?${seasonParam(id)}`);
    if (id !== state.season || !data || typeof data !== "object" || isWarming(data)) return;
    state.hound = data;
    if (data.season && typeof data.season === "object") state.seasonMeta = data.season;
    state.series = Array.isArray(data.series) ? normalizeSeries({ series: { [state.id]: data.series } }) : state.series;
    state.seriesError = null;
  } catch (err) {
    return;           // keep what is on screen; the toggle stays where the reader put it
  }
  renderSeasonBar();
  renderScoreboard(state.hound);
  resultLines(state.hound);
  renderVerdict(state.hound);
  renderCharts();
}

// ---- KPI strip -------------------------------------------------------------------------------------

function kpi(slot, label, big, small, tone) {
  return h("div", { class: `hd-kpi hd-kpi--${tone || "plain"}`, "data-slot": slot }, [
    h("span", { class: "hd-kpi__label", text: label }),
    h("span", { class: "hd-kpi__big hd-num", "data-count": "1", text: big }),
    small ? h("span", { class: "hd-kpi__small", text: small }) : null,
  ]);
}

export const RETURN_TABS = ["h24", "d7", "d30", "season"];

/**
 * The Return tile: one big percent (profit as a share of the $1,000 start) with 24h / 7d / 30d / Season tabs.
 * The tabs switch the figure in place; "Season" is the whole view the page is showing. A window with no settled
 * bet says so ("n/a") instead of a flat 0.0%.
 */
function returnTile(hound) {
  const tone = (n) => (n === null ? "plain" : n > 0 ? "up" : n < 0 ? "down" : "plain");
  const tile = h("div", { class: "hd-kpi hd-kpi--plain", "data-slot": "return" });
  const big = h("span", { class: "hd-kpi__big hd-num", "data-count": "1", "data-hook": "return-big" });
  const small = h("span", { class: "hd-kpi__small", "data-hook": "return-small" });
  const bar = h("div", { class: "hd-kpitabs", role: "tablist", "aria-label": "Return window", "data-hook": "return-tabs" });
  const show = (key) => {
    const w = windowOf(hound, key);
    const has = !!w && w.bets > 0;
    big.textContent = has ? fmtPct(w.pct) : NA;
    small.textContent = !w ? "nothing graded yet"
      : has ? `${fmtSignedUsd(w.pnl, true)} from ${w.bets} graded ${w.bets === 1 ? "bet" : "bets"} settled in ${WINDOW_WORDS[key]}`
        : `no bet settled in ${WINDOW_WORDS[key]}`;
    tile.setAttribute("class", `hd-kpi hd-kpi--${tone(has ? w.pct : null)}`);
    for (const b of bar.children) b.setAttribute("aria-selected", b.getAttribute("data-window") === key ? "true" : "false");
    tile.setAttribute("data-window", key);
  };
  for (const key of RETURN_TABS) {
    bar.appendChild(h("button", { type: "button", role: "tab", class: "hd-kpitab", "data-window": key,
      "data-hook": `return-tab-${key}`, "aria-selected": "false", on: { click: () => show(key) } }, WINDOW_LABELS[key]));
  }
  tile.appendChild(h("span", { class: "hd-kpi__label", text: "Return" }));
  tile.appendChild(bar);
  tile.appendChild(big);
  tile.appendChild(small);
  show("season");
  return tile;
}

/** The money tiles (bankroll, units, drawdown, yield): everything the server worked out in `hound.bankroll`. */
function bankrollTiles(hound) {
  const b = bankrollOf(hound);
  const rules = bankrollRules(hound);
  const toneOf = (n) => (n === null ? "plain" : n > 0 ? "up" : n < 0 ? "down" : "plain");
  const now = bankrollNow(hound);
  const units = totalUnitsOf(hound);
  const dd = drawdownOf(hound);
  const yld = yieldOf(hound);
  const small = isSmallSample(hound);
  const stake = b && Number.isFinite(b.avg_stake_units) ? b.avg_stake_units : 1;
  const ret = b ? b.return_pct : null;
  return {
    bankroll: kpi("bankroll", "Bankroll", fmtUsd(now, true),
      now === null || b.bets <= 0 ? "nothing graded yet" : `from ${fmtUsd(rules.start)}${b.peak > now ? `, peak ${fmtUsd(b.peak, true)}` : ""}`
        + (basisOf(hound) ? `. Settled ${basisWords(hound)}.` : ""),
      toneOf(ret)),
    units: kpi("units", "Units", units === null ? NA : fmtUnitsPlain(units),
      units === null ? "nothing graded yet"
        : `1 unit = ${fmtUsd(rules.unit)}${stake !== 1 ? `; this model bets ${stake} units a bet` : ""}`, toneOf(units)),
    drawdown: kpi("drawdown", "Max drawdown", dd ? fmtUsd(dd.usd, true) : NA,
      dd ? (dd.usd === 0 ? "never below a previous high" : `${dd.pct === null ? "" : `${dd.pct.toFixed(1)}% `}below the peak at its worst`) : "nothing graded yet"),
    yield: kpi("yield", "Yield", fmtPct(yld), yld === null ? "" : "profit per $ bet", toneOf(yld)),
  };
}

export function renderScoreboard(hound) {
  const box = q("hound-scoreboard");
  clearNode(box);
  const bets = betsOf(hound);
  const money = bankrollTiles(hound);
  const clv = clvOf(hound);
  const rec = hound.record || {};
  const toneOf = (n) => (n === null ? "plain" : n > 0 ? "up" : n < 0 ? "down" : "plain");
  const open = isNum(hound.open_bets) ? hound.open_bets : 0;
  const ungraded = ungradedBetsOf(hound);
  const clvBig = clv && clv.beatPct !== null ? `${Math.round(clv.beatPct)}% beat` : (clv && clv.mean !== null ? `${signed(clv.mean, 1)} pts` : NA);
  const clvSmall = clv ? [clv.mean !== null ? `${signed(clv.mean, 1)} pts average` : "", clv.n ? `${clv.n} measurable bets` : ""].filter(Boolean).join(", ")
    : "no bet has a measurable closing price yet";
  const streak = streakText(hound);
  // ONE HERO, THEN A TIDY ROW (critic round 2, 2026-10-19). The bankroll is the hero tile: the big dollar figure, the return beside
  // it with its small 24h / 7d / 30d / Season tabs. Everything else is one secondary row of equal compact tiles. Document order is
  // unchanged (bankroll, return, units, record, drawdown, yield, bets, clv, streak).
  box.appendChild(h("div", { class: "hd-kpis hd-kpis--v2", "data-hook": "scoreboard-tiles" }, [
    h("div", { class: "hd-bankhero", "data-hook": "bank-hero" }, [money.bankroll, returnTile(hound)]),
    h("div", { class: "hd-kpirow", "data-hook": "kpi-row" }, [
      money.units,
      kpi("record", "Record", recordText(hound), bets > 0 ? "wins-losses" + (rec.pushes ? "-pushes" : "") : "no graded bets"),
      money.drawdown,
      money.yield,
      kpi("bets", "Bets", String(bets), [open > 0 ? `${open} open` : "", ungraded > 0 ? `${ungraded} ungraded` : ""].filter(Boolean).join(", ")
        || ""),
      kpi("clv", "CLV", clvBig, clvSmall),
      kpi("streak", "Streak", streak || NA, streak ? (streak.startsWith("W") ? "wins in a row" : "losses in a row") : "no graded bets"),
    ]),
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
    text: VERDICT_MEANING[verdictLabel(hound)] || "This model has no verdict yet. Its record is shown as it stands." }));
  const graded = betsOf(hound);
  const windowed = hound.season && typeof hound.season === "object" && !hound.season.all_time;
  box.appendChild(h("p", { class: "hd-fine", "data-hook": "verdict-sample",
    text: windowed
      ? `This is the referee's all-time verdict. ${hound.season.label || "This season"}: ${graded} graded live ${graded === 1 ? "bet" : "bets"}.`
      : `Based on ${graded} graded live ${graded === 1 ? "bet" : "bets"}.` }));
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
    h("div", {}, [h("dt", { text: hound.season && !hound.season.all_time && hound.season.label ? `Live record, ${hound.season.label}` : "Live record" }),
      h("dd", { text: fRec && fRec.bets > 0 ? fmtRecord(fRec) : "no graded bets" })]),
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
  const rules = bankrollRules(state.hound);
  title.textContent = hasPoints
    ? `Live bets only: placed after the rule was written. The paper account in dollars, from the shared ${fmtUsd(rules.start)} start (1 unit = ${fmtUsd(rules.unit)}).`
    : "No graded live bets yet, so there is nothing to draw. A rehearsal result is never drawn here.";
  const width = chartWidth(units);
  // The server's balance after each slate day. The chart draws dollars ABOVE the start, so its zero line is the
  // starting bankroll, and words every tick and tooltip as the balance (hounds-chart.js `offset`).
  const balance = toChartPoints(pts, "bankroll_usd").map((p) => ({ ...p, value: p.value - rules.start }));
  units.appendChild(renderLineChart({
    hook: "units-chart",
    series: [{ id: "bankroll", name: "Bankroll", color: houndColor(state.hound || {}), points: balance }],
    width, height: width < 480 ? 240 : 300, unit: "usd", offset: rules.start,
    label: `Paper bankroll in dollars, live bets, from ${fmtUsd(rules.start)}`,
    zeroLabel: `${fmtUsd(rules.start)} start`,
    emptyText: hasPoints ? "No graded bets to draw yet." : "No graded live bets yet.",
  }));
  units.appendChild(h("p", { class: "hd-fine", "data-hook": "chart-basis",
    text: `Bets are settled ${basisWords(state.hound) || "at the average price across books"}.${
      basisOf(state.hound) === "recorded_price" ? " This model's average-price board is missing for more than 10% of its bets, so it is settled at the price it took; other models are settled at the average price." : ""
    } A member's model counts the units its owner chose.` }));
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

/**
 * The ungraded section: tickets more than 36 hours past their start with no grade, listed apart with a count in
 * the heading. It is built into its slot only when there is at least one (and removed when there are none), so a
 * model with a clean record shows no empty box.
 */
function renderUngraded() {
  let section = q("hound-ungraded-section");
  const page = state.ungraded;
  if (!page || page.total === 0) { if (section) section.remove(); return; }
  if (!section) {
    const slot = q("hound-ungraded-slot");
    if (!slot) return;
    section = h("section", { class: "hd-panel", "aria-labelledby": "ungraded-h", "data-hook": "hound-ungraded-section" }, [
      h("h2", { id: "ungraded-h", "data-hook": "ungraded-heading" }),
      h("p", { class: "hd-fine", "data-hook": "ungraded-note",
        text: "These games started more than 36 hours ago and nothing has graded them yet. They are not open, and they are not in the record." }),
      h("div", { "data-hook": "hound-ungraded", "aria-live": "polite" })]);
    slot.appendChild(section);
  }
  q("ungraded-heading").textContent = `Ungraded tickets (${page.total})`;
  const box = q("hound-ungraded");
  clearNode(box);
  box.appendChild(ticketTable(page.items, { graded: false, hook: "ungraded-table",
    caption: "Ungraded tickets, more than 36 hours past the start with no grade" }));
  if (page.total > page.items.length) {
    box.appendChild(h("p", { class: "hd-fine", text: `Showing the newest ${page.items.length} of ${page.total} ungraded tickets.` }));
  }
}

async function loadUngraded() {
  try {
    const data = await apiGet(`/hounds/${encodeURIComponent(state.id)}/bets?status=ungraded&segment=forward&page=1&page_size=50`);
    // belt and braces: only rows the server itself stamped UNGRADED are listed, whatever the route answered
    const page = betsPageOf(data);
    const items = page.items.filter((t) => String(t && t.status).toUpperCase() === "UNGRADED");
    state.ungraded = { ...page, items, total: items.length === page.items.length ? page.total : items.length };
  } catch (err) {
    state.ungraded = null;           // the section stays hidden: it only ever shows what the server sent
  }
  renderUngraded();
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

/** "All seasons | Season 2 | Season 1": narrows the graded ticket list. Tickets default to every season. */
function renderBetsSeasonBar() {
  const bar = q("bets-season");
  if (!bar) return;
  clearNode(bar);
  const options = [{ id: ALL_SEASON, label: "All seasons" }].concat(seasonOptions(state.seasonMeta).filter((o) => o.id !== ALL_SEASON));
  for (const o of options) {
    bar.appendChild(h("button", { type: "button", class: "hd-seg", "data-bets-season": o.id,
      "aria-pressed": state.betsSeason === o.id ? "true" : "false",
      on: { click: () => { state.betsSeason = o.id; loadGraded(1); } } }, o.label));
  }
}

function renderGraded() {
  const box = q("hound-bets");
  clearNode(box);
  renderSegmentBar();
  renderBetsSeasonBar();
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
  // R6: tickets graded since this browser last looked at its own hound flip from PENDING to their grade, once, and the hound's FIRST
  // grade gets the one celebration burst. `state.fresh` was set by loadGraded and is spent here, so a re-render never replays it.
  const fresh = state.fresh;
  state.fresh = null;
  const flip = fresh ? Math.min(fresh.fresh, MAX_FLIPS, page.items.length) : 0;
  box.appendChild(ticketTable(page.items, { graded: true, hook: "bets-table", caption: "Graded tickets, newest first", flip }));
  if (flip) {
    playReveal(box);
    if (fresh.burst) celebrate(box, "first-grade");
  }
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
    const within = state.betsSeason && state.betsSeason !== ALL_SEASON ? `&${seasonParam(state.betsSeason)}` : "";
    const data = await apiGet(`/hounds/${encodeURIComponent(state.id)}/bets?status=graded&segment=${state.segment}&page=${pageNo}&page_size=${size}${within}`);
    state.graded = betsPageOf(data);
    // the live tickets, newest page, every season: the only view where "graded since I last looked" means anything
    if (pageNo === 1 && state.segment === "forward" && (!state.betsSeason || state.betsSeason === ALL_SEASON)) {
      state.fresh = settleGrades(state.id, state.graded.total);
    }
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
    if (!state.season) state.season = chooseSeason(state.seasonMeta);
    hound = await apiGet(`/hounds/${encodeURIComponent(state.id)}?${seasonParam(state.season)}`);
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
  if (hound.season && typeof hound.season === "object") state.seasonMeta = hound.season;
  renderHeader(hound);
  renderSeasonBar();
  renderScoreboard(hound);
  resultLines(hound);
  renderVerdict(hound);
  renderRule(hound, `build-a-hound.html?from=${encodeURIComponent(state.id)}`);
  renderActions(hound);
  startRulebook(hound);           // loads on its own: the dials and the coach never hold the page up
  // fire now, ask, manual picks, ratings and (owner) the locker room: its own request, hidden until real
  bootDogKit(hound).catch(() => null);

  // the AI desk's models also show how they argued their newest game (every other model never sees this)
  bootDesk(hound);
  // versions and challengers (the learning loop): loads on its own and never takes this page down
  bootLineage(hound);

  loadOpen();
  loadUngraded();
  if (state.poller) state.poller.stop();
  if (hound.status !== "retired") {
    state.poller = createPoller({ run: () => { loadOpen(); loadUngraded(); }, intervalMs: OPEN_POLL_MS });
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
