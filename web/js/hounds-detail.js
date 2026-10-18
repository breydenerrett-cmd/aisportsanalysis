/**
 * web/hound.html?id=<hound id>: one hound.
 *
 * Reads GET /hounds/{id} (the summary, and bets[] when it carries them), GET /hounds/{id}/bets when it
 * does not, and GET /hounds/series?ids=<id> for the charts. Each part loads on its own and says honestly
 * what happened when its endpoint is missing.
 *
 * What it shows: the rule in a box with a Copy button (and a link that opens the builder pre-filled from
 * /hounds/{id}/spec); the verdict with its meaning in plain words; FORWARD results as the headline and the
 * REPLAY result as a separate, smaller line; a units chart with two lines (recorded price and average
 * price) and a running-mean-CLV chart with its zero line; the bets, paged, saying who decided each;
 * and, for a retired hound, the cause.
 */

import { apiGet } from "./api.js";
import {
  h, clearNode, avatarSvg, categoryOf, categoryLabel, houndColor, verdictLabel, verdictTone, verdictGlyph,
  VERDICT_MEANING, fmtRecord, fmtClv, fmtUnits, fmtPrice, fmtWhen, shortDate, signed, isNum, whoLabel,
  normalizeSeries, pointsFor, hasForwardData, toChartPoints, segmentView, describeError, noticeLine,
  FUN_CATEGORIES, FUN_TAG, REPLAY_NOTE, NO_FORWARD_TEXT, NOT_REPORTED, dayKey,
} from "./hounds-core.js";
import { renderLineChart } from "./hounds-chart.js";

export const PAGE_SIZE = 20;
const AVG_COLOR = "#00E0FF";
const REC_COLOR = "#FFB020";

const state = { id: "", hound: null, bets: null, betsError: null, page: 0, series: null, seriesError: null,
  segment: null };

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
    : hound.verified === false ? h("span", { class: "hd-unverified", text: "not verified" }) : null;
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
  const cause = hound.cause || hound.retired_cause || hound.status_reason;
  const causeBox = q("hound-cause");
  clearNode(causeBox);
  if (hound.status === "retired") {
    causeBox.hidden = false;
    causeBox.removeAttribute("hidden");
    causeBox.appendChild(h("p", {}, [h("strong", { text: "Retired. Cause: " }), cause || "the server did not state one"]));
  } else if (hound.status === "benched" && cause) {
    causeBox.hidden = false;
    causeBox.removeAttribute("hidden");
    causeBox.appendChild(h("p", {}, [h("strong", { text: "Benched. Why: " }), cause]));
  }
}

function resultLines(hound) {
  const box = q("hound-results");
  clearNode(box);
  const fwd = segmentView(hound, "forward");
  const rep = segmentView(hound, "replay");
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
      text: `Units, small print: ${fmtUnits(fRec.units_recorded_price)} recorded price, ${fmtUnits(fRec.units_average_price)} average price. Units over a few weeks are mostly luck.` }));
  }
  if (rep && rep.record) {
    const c = fmtClv(rep.clv);
    box.appendChild(h("p", { class: "hd-row__replay", "data-hook": "replay-line" }, [
      h("strong", { text: REPLAY_NOTE }), ": ", rep.record.bets > 0 ? fmtRecord(rep.record) : "no replay result reported",
      rep.record.bets > 0 ? `; price vs the close ${c.main}${c.detail ? ` (${c.detail})` : ""}` : "",
      rep.record.bets > 0 ? `; units, small print: ${fmtUnits(rep.record.units_recorded_price)} recorded, ${fmtUnits(rep.record.units_average_price)} average` : ""]));
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

function effectiveSegment() {
  if (state.segment) return state.segment;
  return state.series && hasForwardData(state.series) ? "forward" : "replay";
}

function chartWidth(panel) {
  const box = panel && panel.getBoundingClientRect ? panel.getBoundingClientRect() : null;
  const w = box && box.width ? box.width : 640;
  return Math.max(300, Math.min(760, Math.round(w)));
}

export function renderCharts() {
  const units = q("hound-units-chart");
  const clv = q("hound-clv-chart");
  const bar = q("hound-segment");
  clearNode(bar); clearNode(units); clearNode(clv);
  if (state.seriesError) {
    const e = describeError(state.seriesError, "the charts");
    units.appendChild(stateBox(e.kind, e.text));
    return;
  }
  if (state.series === null) {
    units.appendChild(h("p", { class: "hd-muted", text: "Loading the charts..." }));
    return;
  }
  const seg = effectiveSegment();
  for (const [key, text] of [["forward", "Forward"], ["replay", "Replay"]]) {
    bar.appendChild(h("button", { type: "button", class: "hd-seg", "data-segment": key,
      "aria-pressed": seg === key ? "true" : "false", on: { click: () => { state.segment = key; renderCharts(); } } }, text));
  }
  const title = q("hound-chart-title");
  title.textContent = seg === "replay"
    ? (hasForwardData(state.series) ? `Replay: ${REPLAY_NOTE}.` : `Replay only for now: ${REPLAY_NOTE}. No forward results exist yet.`)
    : "Forward results: paper bets placed after the rule was written.";
  const pts = pointsFor(state.series, state.id, seg);
  const width = chartWidth(units);
  units.appendChild(renderLineChart({
    hook: "units-chart",
    series: [
      { id: "avg", name: "Average price", color: AVG_COLOR, points: toChartPoints(pts, "cum_units_average_price") },
      { id: "rec", name: "Recorded price", color: REC_COLOR, points: toChartPoints(pts, "cum_units_recorded_price") },
    ],
    dashes: [undefined, "7 4"], width, height: width < 480 ? 240 : 300, unit: "units",
    label: `Cumulative paper units, ${seg} results, at the recorded price and at the average price`,
    zeroLabel: "0 units",
    emptyText: seg === "forward" ? "No forward results yet. Switch to Replay to see the rule on earlier boards." : "No settled bets to draw yet.",
  }));
  units.appendChild(h("ul", { class: "hd-legend hd-legend--static" }, [
    h("li", {}, [h("span", { class: "hd-tip__swatch", style: `background:${AVG_COLOR}` }), " Average price: the market's typical price when the bet was made"]),
    h("li", {}, [h("span", { class: "hd-tip__swatch", style: `background:${REC_COLOR}` }), " Recorded price: the price this hound was graded at"]),
  ]));
  clv.appendChild(h("h3", { class: "hd-h3", text: "Running mean price vs the close (CLV)" }));
  const clvPts = toChartPoints(pts, "cum_clv_mean_pts");
  clv.appendChild(renderLineChart({
    hook: "clv-chart",
    series: [{ id: "clv", name: "Running mean CLV", color: houndColor(state.hound || {}), points: clvPts }],
    width, height: 190, unit: "pts",
    label: `Running mean of price versus the closing price, in points, ${seg} results`,
    zeroLabel: "0 = same as the close",
    emptyText: "No CLV measured yet for this view.",
  }));
  clv.appendChild(h("p", { class: "hd-fine", text: "Above zero means the prices taken were better than the closing price, on average so far. A mean from few bets can swing either way; the verdict above uses the interval, not this line." }));
}

// ---- bets -----------------------------------------------------------------------------------------

export function resultCell(result) {
  const r = String(result || "").toLowerCase();
  const map = { win: ["W", "Win", "win"], won: ["W", "Win", "win"], w: ["W", "Win", "win"],
    loss: ["L", "Loss", "loss"], lost: ["L", "Loss", "loss"], l: ["L", "Loss", "loss"],
    push: ["P", "Push", "push"], p: ["P", "Push", "push"], void: ["V", "Void", "void"], v: ["V", "Void", "void"],
    pending: ["...", "Pending", "pending"], open: ["...", "Pending", "pending"] };
  const [glyph, word, tone] = map[r] || ["?", r ? r : "Not reported", "unknown"];
  return h("span", { class: `hd-result hd-result--${tone}`, "data-result": tone }, [
    h("span", { "aria-hidden": "true", text: glyph + " " }), word]);
}

function renderBets() {
  const box = q("hound-bets");
  clearNode(box);
  if (state.betsError) {
    const e = describeError(state.betsError, "the bets list");
    box.appendChild(stateBox(e.kind, e.text, () => { loadBets(); }));
    return;
  }
  if (state.bets === null) { box.appendChild(h("p", { class: "hd-muted", text: "Loading the bets..." })); return; }
  if (state.bets.length === 0) {
    box.appendChild(h("p", { class: "hd-muted", "data-hook": "bets-empty",
      text: "No bets yet. This hound has not placed a paper bet." }));
    return;
  }
  const pages = Math.ceil(state.bets.length / PAGE_SIZE);
  state.page = Math.max(0, Math.min(pages - 1, state.page));
  const slice = state.bets.slice(state.page * PAGE_SIZE, (state.page + 1) * PAGE_SIZE);
  const head = ["Date", "Game", "Market", "Selection", "Price (book)", "Market fair value", "Result", "Units", "CLV", "Decided by", "Why"];
  const rows = slice.map((b) => h("tr", { "data-who": String(b.who_decided || "") }, [
    h("td", { text: shortDate(b.date) || NOT_REPORTED }),
    h("td", { text: b.game || NOT_REPORTED }),
    h("td", { text: b.market || NOT_REPORTED }),
    h("td", { text: b.selection || NOT_REPORTED }),
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
      disabled: state.page === 0 ? "" : undefined, on: { click: () => { state.page -= 1; renderBets(); } } }),
    h("span", { class: "hd-fine", "data-hook": "bets-page", role: "status",
      text: `Page ${state.page + 1} of ${pages} (${state.bets.length} bets)` }),
    h("button", { type: "button", class: "btn btn--ghost", "data-hook": "bets-next", text: "Older",
      disabled: state.page >= pages - 1 ? "" : undefined, on: { click: () => { state.page += 1; renderBets(); } } }),
  ]));
}

async function loadBets() {
  state.betsError = null;
  state.bets = null;
  renderBets();
  try {
    const data = await apiGet(`/hounds/${encodeURIComponent(state.id)}/bets`);
    state.bets = Array.isArray(data) ? data : Array.isArray(data && data.bets) ? data.bets : [];
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
  state.hound = hound;
  renderHeader(hound);
  resultLines(hound);
  renderVerdict(hound);
  renderRule(hound, `build-a-hound.html?from=${encodeURIComponent(state.id)}`);
  const notice = noticeLine(hound);
  if (notice) q("hound-notice").textContent = notice;

  // bets: from the detail payload when it carries them, else their own endpoint
  if (Array.isArray(hound.bets)) { state.bets = hound.bets; renderBets(); } else { loadBets(); }

  renderCharts();
  try {
    state.series = normalizeSeries(await apiGet(`/hounds/series?ids=${encodeURIComponent(state.id)}`));
    state.seriesError = null;
  } catch (err) {
    state.series = null;
    state.seriesError = err;
  }
  renderCharts();
}

export const __state = state;
export { dayKey };

if (typeof document !== "undefined" && typeof window !== "undefined") {
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();
}
