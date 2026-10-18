/**
 * web/hound.html?id=<hound id>: one hound.
 *
 * Reads GET /hounds/{id} (a HoundSummary plus `series` and the first page of `bets`, an object
 * {items, page, page_size, total, pages}), GET /hounds/{id}/bets?page=&segment= for the other pages, and
 * GET /hounds/series?ids=<id> when the detail payload does not carry the series. The shapes are
 * src/hounds/contract.py's. Each part loads on its own and says honestly what happened when its endpoint
 * is missing.
 *
 * What it shows: the rule in a box with a Copy button (and a link that opens the builder pre-filled from
 * /hounds/{id}/spec); the verdict with its meaning in plain words; FORWARD results as the headline and the
 * REPLAY block as a separate, smaller line; a units chart with two lines (the AVERAGE price, the headline,
 * and the BEST price, small) and a running-mean-CLV chart with its zero line, both forward only; the bets,
 * paged by the server, saying who decided each; and, for a retired hound, the cause.
 */

import { apiGet } from "./api.js";
import {
  h, clearNode, avatarSvg, categoryOf, categoryLabel, houndColor, verdictLabel, verdictTone, verdictGlyph,
  VERDICT_MEANING, fmtRecord, fmtClv, fmtUnits, fmtPrice, fmtWhen, shortDate, signed, isNum, whoLabel,
  normalizeSeries, pointsFor, hasForwardData, toChartPoints, segmentView, describeError, noticeLine,
  FUN_CATEGORIES, FUN_TAG, REPLAY_NOTE, NO_FORWARD_TEXT, NOT_REPORTED, dayKey, unitsPairText,
  AVERAGE_PRICE_WORDS, BEST_PRICE_WORDS, isWarming, retryWhileWarming, stopWarmingRetry, WARMING_FALLBACK_TEXT,
} from "./hounds-core.js";
import { renderLineChart } from "./hounds-chart.js";

export const PAGE_SIZE = 20;
const AVG_COLOR = "#00E0FF";
const BEST_COLOR = "#FFB020";

const state = { id: "", hound: null, bets: null, betsError: null, betSegment: "", series: null, seriesError: null };

const q = (hook) => document.querySelector(`[data-hook='${hook}']`);

function stateBox(kind, text, retry) {
  const box = h("div", { class: `hd-state hd-state--${kind}`, role: kind === "down" ? "alert" : "status",
    "data-hook": "section-state", "data-kind": kind }, [h("p", { text })]);
  if (retry) box.appendChild(h("button", { type: "button", class: "btn btn--ghost hd-retry", text: "Try again",
    on: { click: retry } }));
  return box;
}

// ---- copy -----------------------------------------------------------------------------------------

/** Copy text; resolves true/false. Uses the async clipboard, then the old textarea route. */
export async function copyText(text) {
  try {
    if (typeof navigator !== "undefined" && navigator.clipboard && navigator.clipboard.writeText) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch (err) { /* fall through */ }
  try {
    const area = h("textarea", { "aria-hidden": "true", readonly: "", style: "position:fixed;opacity:0;top:0;left:0" });
    area.value = text;
    document.body.appendChild(area);
    if (area.select) area.select();
    const ok = document.execCommand ? document.execCommand("copy") : false;
    document.body.removeChild(area);
    return !!ok;
  } catch (err) {
    return false;
  }
}

// ---- header, verdict, rule ------------------------------------------------------------------------

function renderHeader(hound) {
  const box = q("hound-header");
  clearNode(box);
  const cat = categoryOf(hound);
  document.title = `${hound.name || "Hound"} — LINEHOUND`;
  const verified = hound.verified === true
    ? h("span", { class: "hd-verified" }, [h("span", { "aria-hidden": "true", text: "✓ " }), "verified"])
    : hound.verified === false && isNum(hound.verified_share) ? h("span", { class: "hd-unverified", text: "not verified" }) : null;
  box.appendChild(avatarSvg(hound.name, { size: 72, category: cat }));
  box.appendChild(h("div", {}, [
    h("h1", { "data-hook": "hound-name", text: hound.name || NOT_REPORTED }),
    hound.tagline ? h("p", { class: "hd-row__tagline", text: hound.tagline }) : null,
    h("p", { class: "hd-badges" }, [
      cat ? h("span", { class: "hd-chip-cat", "data-category": cat, text: categoryLabel(cat) }) : null,
      FUN_CATEGORIES.includes(cat) ? h("span", { class: "hd-tag", text: FUN_TAG }) : null,
      hound.style ? h("span", { class: "hd-style", text: hound.style }) : null,
      h("span", { class: "hd-badge", text: hound.kind === "user"
        ? (hound.owner_display ? `Built by ${hound.owner_display}` : "Builder hound") : "House hound" }),
      h("span", { class: `hd-status hd-status--${hound.status || "unknown"}`, "data-hook": "hound-status",
        text: { running: "Running", benched: "Benched", retired: "Retired" }[hound.status] || "Status not reported" }),
      verified,
    ]),
  ]));
  // Contract: a retired hound carries `retired: {date, cause}`.
  const retired = hound.retired && typeof hound.retired === "object" ? hound.retired : null;
  const causeBox = q("hound-cause");
  clearNode(causeBox);
  if (hound.status === "retired") {
    causeBox.hidden = false;
    causeBox.removeAttribute("hidden");
    causeBox.appendChild(h("p", {}, [h("strong", { text: "Retired. Cause: " }),
      (retired && retired.cause) || "the server did not state one",
      retired && retired.date ? h("span", { class: "hd-fine", text: ` (${fmtWhen(retired.date)})` }) : null]));
  } else if (hound.status === "benched" && hound.last_bet_utc) {
    causeBox.hidden = false;
    causeBox.removeAttribute("hidden");
    causeBox.appendChild(h("p", {}, [h("strong", { text: "Benched. Why: " }),
      `its last bet was ${fmtWhen(hound.last_bet_utc)}, and a hound with no bet for more than 7 days is benched.`]));
  }
}

function resultLines(hound) {
  const box = q("hound-results");
  clearNode(box);
  const fwd = segmentView(hound, "forward");
  const fRec = fwd && fwd.record;
  const fClv = fmtClv(fwd && fwd.clv);
  box.appendChild(h("dl", { class: "hd-row__facts hd-facts--big", "data-hook": "forward-facts" }, [
    h("div", {}, [h("dt", { text: "Forward record" }), h("dd", { text: fRec && fRec.bets > 0 ? fmtRecord(fRec) : NO_FORWARD_TEXT })]),
    h("div", {}, [h("dt", { text: "Forward price vs the close (CLV)" }), h("dd", {}, [
      fRec && fRec.bets > 0 ? fClv.main : "not measured yet",
      fRec && fRec.bets > 0 && fClv.detail ? h("span", { class: "hd-fine", text: ` (${fClv.detail})` }) : null])]),
    h("div", {}, [h("dt", { text: "First / last bet" }), h("dd", { text:
      `${fmtWhen(hound.first_bet_utc) || "none yet"} / ${fmtWhen(hound.last_bet_utc) || "none yet"}` })]),
  ]));
  if (fRec && fRec.bets > 0) {
    box.appendChild(h("p", { class: "hd-row__units", "data-hook": "row-units",
      text: `Units, small print: ${unitsPairText(fRec)}. Units over a few weeks are mostly luck.` }));
  }
  const rep = hound.replay && typeof hound.replay === "object" ? hound.replay : null;
  if (rep) {
    box.appendChild(h("p", { class: "hd-row__replay", "data-hook": "replay-line" }, [
      h("strong", { text: REPLAY_NOTE }), ": ", rep.bets > 0 ? fmtRecord(rep) : "no replay result reported",
      rep.bets > 0 ? `; units, small print: ${fmtUnits(rep.units_recorded_price)} ${BEST_PRICE_WORDS}` : ""]));
    if (rep.note) box.appendChild(h("p", { class: "hd-fine", "data-hook": "replay-note", text: rep.note }));
  }
}

function renderVerdict(hound) {
  const box = q("hound-verdict");
  clearNode(box);
  const label = verdictLabel(hound);
  const tone = verdictTone(label);
  box.appendChild(h("span", { class: `hd-chip hd-chip--${tone} hd-chip--lg`, "data-hook": "verdict-chip" }, [
    h("span", { "aria-hidden": "true", text: verdictGlyph(tone) + " " }), label || "NO VERDICT YET"]));
  if (hound.verdict && hound.verdict.sentence) {
    box.appendChild(h("p", { class: "hd-verdict__sentence", "data-hook": "verdict-sentence", text: hound.verdict.sentence }));
  }
  box.appendChild(h("p", { class: "hd-verdict__meaning", "data-hook": "verdict-meaning",
    text: VERDICT_MEANING[label] || "The server sent a verdict this page has no plain-language note for. Read the sentence above, and treat the result as unproven." }));
  const rec = hound.record || (segmentView(hound, "forward") || {}).record;
  if (rec && isNum(rec.bets)) {
    box.appendChild(h("p", { class: "hd-fine", text: `Sample size: ${rec.bets} settled forward ${rec.bets === 1 ? "bet" : "bets"}.${rec.bets < 100 ? " That is a small sample." : ""}` }));
  }
  if (hound.verdict && hound.verdict.units_note) {
    box.appendChild(h("p", { class: "hd-fine", "data-hook": "units-note", text: hound.verdict.units_note }));
  }
}

function renderRule(hound, specHref) {
  const box = q("hound-rule");
  clearNode(box);
  const text = hound.rule_text || "";
  box.appendChild(h("pre", { class: "hd-rule", "data-hook": "rule-text", tabindex: "0",
    text: text || "The server did not send this hound's rule text." }));
  const status = h("span", { class: "hd-fine", role: "status", "data-hook": "copy-status" });
  const btn = h("button", { type: "button", class: "btn btn--ghost", "data-hook": "copy-rule", text: "Copy rule",
    "aria-label": "Copy this hound's rule to the clipboard", on: { click: async () => {
      status.textContent = (await copyText(text)) ? "Copied." : "Could not copy. Select the rule text and copy it by hand.";
    } } });
  if (!text) btn.setAttribute("disabled", "");
  box.appendChild(h("div", { class: "hd-rule__actions" }, [btn,
    h("a", { class: "btn btn--primary", href: specHref, "data-hook": "build-from", text: "Build one like this" }), status]));
}

// ---- charts ---------------------------------------------------------------------------------------

function chartWidth(panel) {
  const box = panel && panel.getBoundingClientRect ? panel.getBoundingClientRect() : null;
  const w = box && box.width ? box.width : 640;
  return Math.max(300, Math.min(760, Math.round(w)));
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
    ? "Forward results: paper bets placed after the rule was written."
    : "Forward results: none yet. This hound's replay result, if it has one, is in the results above and is never drawn here.";
  const width = chartWidth(units);
  units.appendChild(renderLineChart({
    hook: "units-chart",
    series: [
      { id: "avg", name: "Average price", color: AVG_COLOR, points: toChartPoints(pts, "cum_units_average_price") },
      { id: "best", name: "Best price", color: BEST_COLOR, points: toChartPoints(pts, "cum_units_recorded_price") },
    ],
    dashes: [undefined, "7 4"], width, height: width < 480 ? 240 : 300, unit: "units",
    label: "Cumulative paper units, forward results, at the average price and at the best price",
    zeroLabel: "0 units",
    emptyText: hasPoints ? "No settled bets to draw yet."
      : "No forward results yet. A replay result is not drawn here.",
  }));
  units.appendChild(h("ul", { class: "hd-legend hd-legend--static" }, [
    h("li", {}, [h("span", { class: "hd-tip__swatch", style: `background:${AVG_COLOR}` }),
      ` Average price: the mean price across the books when the bet was locked (the headline)`]),
    h("li", {}, [h("span", { class: "hd-tip__swatch", style: `background:${BEST_COLOR}` }),
      ` Best price: the single best quote recorded at the lock (small print)`]),
  ]));
  clv.appendChild(h("h3", { class: "hd-h3", text: "Running mean price vs the close (CLV)" }));
  const clvPts = toChartPoints(pts, "cum_clv_mean_pts");
  clv.appendChild(renderLineChart({
    hook: "clv-chart",
    series: [{ id: "clv", name: "Running mean CLV", color: houndColor(state.hound || {}), points: clvPts }],
    width, height: 190, unit: "pts",
    label: "Running mean of price versus the closing price, in points, forward results",
    zeroLabel: "0 = same as the close",
    emptyText: "No CLV measured yet for this view.",
  }));
  clv.appendChild(h("p", { class: "hd-fine", text: "Above zero means the prices taken were better than the closing price, on average so far. A mean from few bets can swing either way; the verdict above uses the interval, not this line." }));
}

// ---- bets -----------------------------------------------------------------------------------------

export function resultCell(result) {
  const r = String(result || "pending").toLowerCase();
  const map = { win: ["W", "Win", "win"], won: ["W", "Win", "win"], w: ["W", "Win", "win"],
    loss: ["L", "Loss", "loss"], lost: ["L", "Loss", "loss"], l: ["L", "Loss", "loss"],
    push: ["P", "Push", "push"], p: ["P", "Push", "push"], void: ["V", "Void", "void"], v: ["V", "Void", "void"],
    pending: ["...", "Pending", "pending"], open: ["...", "Pending", "pending"] };
  const [glyph, word, tone] = map[r] || ["?", r ? r : "Not reported", "unknown"];
  return h("span", { class: `hd-result hd-result--${tone}`, "data-result": tone }, [
    h("span", { "aria-hidden": "true", text: glyph + " " }), word]);
}

/** A page of bets as the server sends it: {items, page, page_size, total, pages}. */
function betsPageOf(data) {
  if (Array.isArray(data)) return { items: data, page: 1, page_size: data.length || PAGE_SIZE, total: data.length, pages: 1 };
  const items = Array.isArray(data && data.items) ? data.items : [];
  const total = isNum(data && data.total) ? data.total : items.length;
  const size = isNum(data && data.page_size) && data.page_size > 0 ? data.page_size : PAGE_SIZE;
  return { items, page: isNum(data && data.page) ? data.page : 1, page_size: size, total,
    pages: isNum(data && data.pages) ? data.pages : Math.max(1, Math.ceil(total / size)) };
}

function renderSegmentBar() {
  const bar = q("bets-segment");
  if (!bar) return;
  clearNode(bar);
  for (const [key, text] of [["", "All bets"], ["forward", "Forward"], ["replay", "Replay"]]) {
    bar.appendChild(h("button", { type: "button", class: "hd-seg", "data-segment": key || "all",
      "aria-pressed": state.betSegment === key ? "true" : "false",
      on: { click: () => { state.betSegment = key; loadBets(1); } } }, text));
  }
}

function renderBets() {
  const box = q("hound-bets");
  clearNode(box);
  renderSegmentBar();
  if (state.betsError) {
    const e = describeError(state.betsError, "the bets list");
    box.appendChild(stateBox(e.kind, e.text, () => { loadBets(state.bets ? state.bets.page : 1); }));
    return;
  }
  if (state.bets === null) { box.appendChild(h("p", { class: "hd-muted", text: "Loading the bets..." })); return; }
  const page = state.bets;
  if (page.total === 0) {
    box.appendChild(h("p", { class: "hd-muted", "data-hook": "bets-empty",
      text: state.betSegment ? `No ${state.betSegment} bets for this hound.` : "No bets yet. This hound has not placed a paper bet." }));
    return;
  }
  const head = ["Date", "Game", "Market", "Selection", "Average price", "Best price (book)", "Market fair value", "Result",
    "Units at best price", "CLV", "Decided by", "Why"];
  const rows = page.items.map((b) => h("tr", { "data-who": String(b.who_decided || ""), "data-segment": String(b.segment || "") }, [
    h("td", { text: shortDate(b.date) || NOT_REPORTED }),
    h("td", { text: b.game || NOT_REPORTED }),
    h("td", { text: b.market || NOT_REPORTED }),
    h("td", { text: b.selection || NOT_REPORTED }),
    h("td", { text: fmtPrice(b.price_average) }),
    h("td", { text: `${fmtPrice(b.price)}${b.book ? ` (${b.book})` : ""}` }),
    h("td", { text: isNum(b.consensus_fair) ? (b.consensus_fair > 1 || b.consensus_fair < -1 ? fmtPrice(b.consensus_fair) : `${(b.consensus_fair * 100).toFixed(1)}%`) : NOT_REPORTED }),
    h("td", {}, [resultCell(b.result), b.segment ? h("span", { class: "hd-fine", text: ` ${b.segment}` }) : null]),
    h("td", { text: isNum(b.units) ? fmtUnits(b.units) : NOT_REPORTED }),
    h("td", { text: isNum(b.clv_pts) ? `${signed(b.clv_pts, 1)} pts` : "not measured" }),
    h("td", {}, [h("span", { class: `hd-who hd-who--${String(b.who_decided || "unknown").toLowerCase()}`, text: whoLabel(b.who_decided) })]),
    h("td", { class: "hd-td-reason", text: b.reason || "" }),
  ]));
  box.appendChild(h("div", { class: "hd-tablewrap", tabindex: "0", role: "region", "aria-label": "Bets table, scrolls sideways on a phone" }, [
    h("table", { class: "hd-table", "data-hook": "bets-table" }, [
      h("caption", { class: "hd-sr-only", text: "This hound's paper bets, newest first as sent by the server" }),
      h("thead", {}, [h("tr", {}, head.map((t) => h("th", { scope: "col", text: t })))]),
      h("tbody", {}, rows)])]));
  box.appendChild(h("div", { class: "hd-pager", "data-hook": "bets-pager" }, [
    h("button", { type: "button", class: "btn btn--ghost", "data-hook": "bets-prev", text: "Newer",
      disabled: page.page <= 1 ? "" : undefined, on: { click: () => { loadBets(page.page - 1); } } }),
    h("span", { class: "hd-fine", "data-hook": "bets-page", role: "status",
      text: `Page ${page.page} of ${page.pages} (${page.total} bets)` }),
    h("button", { type: "button", class: "btn btn--ghost", "data-hook": "bets-next", text: "Older",
      disabled: page.page >= page.pages ? "" : undefined, on: { click: () => { loadBets(page.page + 1); } } }),
  ]));
}

/** One page of bets from the server (the server pages: a hound can have hundreds). */
async function loadBets(pageNo = 1) {
  state.betsError = null;
  renderBets();
  const size = state.bets ? state.bets.page_size : PAGE_SIZE;
  const seg = state.betSegment ? `&segment=${state.betSegment}` : "";
  try {
    const data = await apiGet(`/hounds/${encodeURIComponent(state.id)}/bets?page=${pageNo}&page_size=${size}${seg}`);
    state.bets = betsPageOf(data);
  } catch (err) {
    state.betsError = err;
  }
  renderBets();
}

// ---- boot -----------------------------------------------------------------------------------------

export async function boot() {
  const params = new URLSearchParams(window.location.search || "");
  state.id = params.get("id") || "";
  const hero = q("hound-header");
  if (!state.id) {
    hero.appendChild(stateBox("missing", "No hound was chosen. Pick one from the race."));
    return;
  }
  let hound;
  try {
    hound = await apiGet(`/hounds/${encodeURIComponent(state.id)}`);
    if (!hound || typeof hound !== "object") throw Object.assign(new Error("empty"), { status: 404 });
  } catch (err) {
    clearNode(hero);
    const e = describeError(err, "this hound");
    hero.appendChild(stateBox(err && err.status === 404 ? "missing" : e.kind,
      err && err.status === 404 ? "There is no hound with this id. It may have been removed, or the link is wrong." : e.text,
      err && err.status === 404 ? null : () => { boot(); }));
    for (const hook of ["hound-verdict-section", "hound-rule-section", "hound-chart-section", "hound-bets-section"]) {
      const sec = q(hook); if (sec) sec.setAttribute("hidden", "");
    }
    return;
  }
  if (isWarming(hound)) {
    // the server is still working out the numbers for the first time: say so, ask again, show nothing made up
    clearNode(hero);
    hero.appendChild(stateBox("warming", hound.message || WARMING_FALLBACK_TEXT));
    for (const hook of ["hound-verdict-section", "hound-rule-section", "hound-chart-section", "hound-bets-section"]) {
      const sec = q(hook); if (sec) sec.setAttribute("hidden", "");
    }
    retryWhileWarming("hound", () => {
      stopWarmingRetry("hound");
      for (const hook of ["hound-verdict-section", "hound-rule-section", "hound-chart-section", "hound-bets-section"]) {
        const sec = q(hook); if (sec) sec.removeAttribute("hidden");
      }
      clearNode(hero);
      boot();
    }, hound);
    return;
  }
  state.hound = hound;
  renderHeader(hound);
  resultLines(hound);
  renderVerdict(hound);
  renderRule(hound, `build-a-hound.html?from=${encodeURIComponent(state.id)}`);
  const notice = noticeLine(hound);
  if (notice) q("hound-notice").textContent = notice;

  // bets: the first page rides with the detail payload; the rest are the server's pages
  if (hound.bets && typeof hound.bets === "object") { state.bets = betsPageOf(hound.bets); renderBets(); } else { loadBets(1); }

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

export const __state = state;
export { dayKey, AVERAGE_PRICE_WORDS };

if (typeof document !== "undefined" && typeof window !== "undefined") {
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();
}
