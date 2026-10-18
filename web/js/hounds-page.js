/**
 * web/hounds.html: the race.
 *
 * WHAT IT SHOWS, TOP TO BOTTOM
 *   - a multi-line chart of cumulative paper units at the AVERAGE price, one line per hound, with a zero
 *     baseline, a hover tooltip and a Forward / Replay toggle. It defaults to REPLAY until forward data
 *     exists and says so in its title;
 *   - the leaderboard, ORDERED BY VERDICT (hounds-core.js sortByVerdict), never by units. Every hound's
 *     headline is its FORWARD result; the replay result (the same rule applied to earlier boards) is a
 *     separate, smaller line. Units are small print. A sparkline per row;
 *   - category chips and a House / Builders' filter; esoteric and random hounds carry a small
 *     "for fun / control" tag in the same type size as their name and are never hidden; baselines sit in a
 *     collapsed "Baselines" group below the race, also never hidden;
 *   - the decision stream (polled every 60 s, only while the page is visible), each item saying who
 *     decided: the rule, the code or the model;
 *   - the graveyard with causes; the basis sentence; the "Build your own hound" call to action.
 *
 * EVERY SECTION LOADS ON ITS OWN. A failed or missing endpoint puts an honest sentence in that section
 * (describeError) and leaves the others alone. Nothing is invented to fill a gap. The page never claims
 * an edge, never calls units profit, and the "paper only, not advice" line is static markup in the HTML so
 * it is there with scripts off.
 */

import { apiGet } from "./api.js";
import {
  h, s, clearNode, sortByVerdict, filterHounds, splitBaselines, presentCategories, categoryOf, categoryLabel,
  houndColor, verdictLabel, verdictTone, verdictGlyph, avatarSvg, fmtRecord, fmtClv, fmtUnits, fmtWhen,
  houndHref, whoLabel, normalizeSeries, pointsFor, hasForwardData, toChartPoints, sparkValues, segmentView,
  describeError, noticeLine, createPoller, FUN_CATEGORIES, FUN_TAG, REPLAY_NOTE, NO_FORWARD_TEXT, NOT_REPORTED,
} from "./hounds-core.js";
import { renderLineChart, renderSparkline } from "./hounds-chart.js";

export const STREAM_POLL_MS = 60000;
export const CHART_LABEL =
  "Paper results. Units over a few weeks are mostly luck; the verdict below each hound is the test.";
const DASHES = [undefined, "7 4", "2 3", "10 3 2 3", "14 4", "1 4"];

const state = {
  hounds: [],
  filter: "all",          // all | house | user
  category: "all",
  hidden: new Set(),      // hound ids off the chart
  hiddenInitialised: false,
  series: null,           // { id: [points] } once loaded
  seriesError: null,
  segment: null,          // "forward" | "replay"; null until chosen or defaulted
  payload: null,
};

const q = (hook) => document.querySelector(`[data-hook='${hook}']`);

function stateBox(kind, text, retry) {
  const box = h("div", { class: `hd-state hd-state--${kind}`, role: kind === "down" ? "alert" : "status",
    "data-hook": "section-state", "data-kind": kind }, [h("p", { text })]);
  if (retry) box.appendChild(h("button", { type: "button", class: "btn btn--ghost hd-retry", text: "Try again",
    on: { click: retry } }));
  return box;
}

function effectiveSegment() {
  if (state.segment) return state.segment;
  return state.series && hasForwardData(state.series) ? "forward" : "replay";
}

// ---- chart ----------------------------------------------------------------------------------------

function chartWidth(panel) {
  const box = panel && panel.getBoundingClientRect ? panel.getBoundingClientRect() : null;
  const w = box && box.width ? box.width : 640;
  return Math.max(300, Math.min(760, Math.round(w)));
}

function chartTitle(segment) {
  const forwardExists = state.series && hasForwardData(state.series);
  if (segment === "replay") {
    return forwardExists
      ? `Replay results: ${REPLAY_NOTE}.`
      : `Replay only for now: ${REPLAY_NOTE}. No forward results exist yet.`;
  }
  return "Forward results: paper bets placed after each rule was written.";
}

function lineSample(color, dash) {
  return s("svg", { class: "hd-legend__line", viewBox: "0 0 22 6", width: 22, height: 6, "aria-hidden": "true",
    focusable: "false" }, [s("line", { x1: 1, x2: 21, y1: 3, y2: 3, stroke: color, "stroke-width": 2.25,
    "stroke-dasharray": dash || undefined, "stroke-linecap": "round" })]);
}

function renderSegmentToggle() {
  const bar = q("hounds-segment");
  if (!bar) return;
  clearNode(bar);
  const active = effectiveSegment();
  for (const [key, text] of [["forward", "Forward"], ["replay", "Replay"]]) {
    bar.appendChild(h("button", { type: "button", class: "hd-seg", "data-segment": key,
      "aria-pressed": active === key ? "true" : "false",
      on: { click: () => { state.segment = key; renderChartPanel(); } } }, text));
  }
}

function renderChartPanel() {
  const panel = q("hounds-chart-panel");
  if (!panel) return;
  clearNode(panel);
  renderSegmentToggle();
  const titleNode = q("hounds-chart-title");
  const segment = effectiveSegment();
  if (titleNode) titleNode.textContent = state.series ? chartTitle(segment) : "";
  if (state.seriesError) {
    const e = describeError(state.seriesError, "the results chart");
    panel.appendChild(stateBox(e.kind, e.text));
    return;
  }
  if (state.series === null) {
    panel.appendChild(h("p", { class: "hd-muted", "data-hook": "chart-loading", text: "Loading the chart..." }));
    return;
  }
  const shown = sortByVerdict(filterHounds(state.hounds, state.filter, state.category));
  // baselines stay selectable but start off the chart; they are listed under the race, not hidden
  const shownAll = shown.concat(sortByVerdict(splitBaselines(filterHounds(state.hounds, state.filter)).baselines)
    .filter((x) => !shown.includes(x)));
  const legend = h("ul", { class: "hd-legend", "data-hook": "chart-legend", "aria-label": "Hounds on the chart" });
  const lines = [];
  const perCategory = {};
  shownAll.forEach((hound) => {
    const cat = categoryOf(hound);
    const color = houndColor(hound);
    const dash = DASHES[(perCategory[cat] = (perCategory[cat] === undefined ? 0 : perCategory[cat] + 1)) % DASHES.length];
    const off = state.hidden.has(String(hound.id));
    legend.appendChild(h("li", {}, [h("button", {
      type: "button", class: "hd-legend__item", "aria-pressed": off ? "false" : "true",
      "data-hound": hound.id,
      "aria-label": `${hound.name}: ${off ? "show on" : "hide from"} the chart`,
      on: { click: () => { toggle(String(hound.id)); } },
    }, [avatarSvg(hound.name, { size: 22, category: cat }), lineSample(color, dash),
      h("span", { class: "hd-legend__name", text: hound.name })])]));
    if (!off) {
      lines.push({ id: String(hound.id), name: hound.name, color, dash,
        points: toChartPoints(pointsFor(state.series, hound.id, segment), "cum_units_average_price") });
    }
  });
  const anyPoints = lines.some((l) => l.points.length > 0);
  const chart = renderLineChart({
    series: lines, width: chartWidth(panel), height: chartWidth(panel) < 480 ? 230 : 280, unit: "units",
    label: `Cumulative paper units at the average price, ${segment} results, one line per hound`,
    zeroLabel: "0 units",
    dashes: lines.map((l) => l.dash),
    emptyText: state.hounds.length === 0 ? "No hounds yet, so there is nothing to draw."
      : shown.length === 0 ? "No hounds in this filter."
      : segment === "forward" && !anyPoints ? "No forward results yet. Switch to Replay to see the rules on earlier boards."
        : "No settled bets to draw yet.",
  });
  panel.appendChild(chart);
  panel.appendChild(legend);
}

function toggle(id) {
  if (state.hidden.has(id)) state.hidden.delete(id); else state.hidden.add(id);
  renderChartPanel();
}

// ---- leaderboard ----------------------------------------------------------------------------------

function statusLine(hound) {
  const word = { running: "Running", benched: "Benched", retired: "Retired" }[hound.status] || "Status not reported";
  return h("span", { class: `hd-status hd-status--${hound.status || "unknown"}`, text: word });
}

function resultFacts(view, { replay = false } = {}) {
  const rec = (view && view.record) || null;
  if (!rec || !(rec.bets > 0)) {
    return { record: replay ? "no replay result reported" : NO_FORWARD_TEXT, clv: null, units: null };
  }
  return { record: fmtRecord(rec), clv: fmtClv(view.clv),
    units: `${fmtUnits(rec.units_recorded_price)} recorded price, ${fmtUnits(rec.units_average_price)} average price` };
}

function row(hound) {
  const label = verdictLabel(hound);
  const tone = verdictTone(label);
  const cat = categoryOf(hound);
  const forward = resultFacts(segmentView(hound, "forward"));
  const replayView = segmentView(hound, "replay");
  const replay = replayView ? resultFacts(replayView, { replay: true }) : null;
  const verified = hound.verified === true
    ? h("span", { class: "hd-verified", "data-hook": "verified" }, [
      h("span", { "aria-hidden": "true", text: "✓ " }), "verified"])
    : hound.verified === false ? h("span", { class: "hd-unverified", text: "not verified" }) : null;
  const seg = effectiveSegment();
  const seriesPts = state.series ? pointsFor(state.series, hound.id, seg) : null;
  const fun = FUN_CATEGORIES.includes(cat);
  return h("li", { class: "hd-row", "data-hound": hound.id, "data-kind": hound.kind || "", "data-category": cat,
    "data-verdict": tone }, [
    h("div", { class: "hd-row__who" }, [
      avatarSvg(hound.name, { size: 44, category: cat }),
      h("div", { class: "hd-row__id" }, [
        h("span", { class: "hd-row__namebar" }, [
          h("a", { class: "hd-row__name", href: houndHref(hound.id), text: hound.name || NOT_REPORTED }),
          fun ? h("span", { class: "hd-tag", "data-hook": "fun-tag", text: FUN_TAG }) : null,
        ]),
        h("span", { class: "hd-badges" }, [
          cat ? h("span", { class: "hd-chip-cat", "data-category": cat, text: categoryLabel(cat) }) : null,
          hound.style ? h("span", { class: "hd-style", "data-hook": "style", text: hound.style }) : null,
          h("span", { class: "hd-badge", text: hound.kind === "user"
            ? (hound.owner_display ? `Built by ${hound.owner_display}` : "Builder hound") : "House hound" }),
        ]),
        hound.tagline ? h("p", { class: "hd-row__tagline", text: hound.tagline }) : null,
      ]),
    ]),
    h("div", { class: "hd-row__verdict" }, [
      h("span", { class: `hd-chip hd-chip--${tone}`, "data-hook": "verdict-chip" }, [
        h("span", { "aria-hidden": "true", text: verdictGlyph(tone) + " " }), label || "NO VERDICT YET"]),
      hound.verdict && hound.verdict.sentence
        ? h("p", { class: "hd-row__vsent", text: hound.verdict.sentence }) : null,
    ]),
    h("dl", { class: "hd-row__facts", "data-hook": "forward-facts" }, [
      h("div", {}, [h("dt", { text: "Forward record" }), h("dd", { text: forward.record })]),
      h("div", {}, [h("dt", { text: "Forward price vs the close (CLV)" }), h("dd", {},
        forward.clv ? [forward.clv.main, forward.clv.detail ? h("span", { class: "hd-fine", text: ` (${forward.clv.detail})` }) : null]
          : [h("span", { class: "hd-fine", text: "not measured yet" })])]),
      h("div", {}, [h("dt", { text: "Status" }), h("dd", {}, [statusLine(hound), verified ? " " : null, verified])]),
    ]),
    h("div", { class: "hd-row__line" }, [
      renderSparkline({ values: sparkValues(hound, seriesPts), color: houndColor(hound),
        label: `${hound.name}: paper units over the last 30 points` }),
      h("p", { class: "hd-row__units", "data-hook": "row-units",
        text: forward.units ? `Units, small print: ${forward.units}` : "Units: none yet" }),
    ]),
    replay ? h("p", { class: "hd-row__replay", "data-hook": "replay-line" }, [
      h("strong", { text: REPLAY_NOTE }), ": ",
      replay.record,
      replay.clv ? `; price vs the close ${replay.clv.main}${replay.clv.detail ? ` (${replay.clv.detail})` : ""}` : "",
      replay.units ? `; units, small print: ${replay.units}` : ""]) : null,
  ]);
}

function filterButtons(bar, entries, current, onPick, dataKey) {
  clearNode(bar);
  for (const [key, text] of entries) {
    bar.appendChild(h("button", { type: "button", class: "hd-seg", "aria-pressed": current === key ? "true" : "false",
      [dataKey]: key, on: { click: () => onPick(key) } }, text));
  }
}

function renderFilter() {
  const bar = q("hounds-filter");
  if (!bar) return;
  const count = (f) => filterHounds(state.hounds, f).length;
  filterButtons(bar, [["all", `All (${count("all")})`], ["house", `House (${count("house")})`],
    ["user", `Builders' (${count("user")})`]], state.filter, (k) => { state.filter = k; renderAll(); }, "data-filter");
  const cats = q("hounds-categories");
  if (!cats) return;
  clearNode(cats);
  const present = presentCategories(filterHounds(state.hounds, state.filter));
  if (state.category !== "all" && !present.includes(state.category)) state.category = "all";
  const base = filterHounds(state.hounds, state.filter);
  const n = (c) => base.filter((x) => categoryOf(x) === c).length;
  cats.appendChild(h("button", { type: "button", class: "hd-seg", "data-category": "all",
    "aria-pressed": state.category === "all" ? "true" : "false",
    on: { click: () => { state.category = "all"; renderAll(); } } }, "All kinds"));
  for (const c of present) {
    cats.appendChild(h("button", { type: "button", class: "hd-seg hd-seg--cat", "data-category": c,
      style: `--cat:${houndColor({ name: "", category: c })}`,
      "aria-pressed": state.category === c ? "true" : "false",
      on: { click: () => { state.category = c; renderAll(); } } }, `${categoryLabel(c)} (${n(c)})`));
  }
}

function renderBoard() {
  const list = q("hounds-list");
  const baseBox = q("hounds-baselines-list");
  if (!list) return;
  clearNode(list);
  const filtered = filterHounds(state.hounds, state.filter, state.category);
  const race = sortByVerdict(splitBaselines(filtered).race);
  if (race.length === 0) {
    list.appendChild(h("li", { class: "hd-empty", "data-hook": "board-empty" }, [
      h("p", { text: state.hounds.length === 0
        ? "No hounds are racing yet. When the first one places a paper bet it will appear here."
        : "No hounds match this filter." }),
      h("a", { class: "btn btn--primary", href: "build-a-hound.html", text: "Build your own hound" }),
    ]));
  }
  for (const hound of race) list.appendChild(row(hound));
  // baselines: below the race, collapsed, always listed (the house/builder filter applies; the category filter does not)
  const group = q("hounds-baselines");
  if (group && baseBox) {
    clearNode(baseBox);
    const baselines = sortByVerdict(splitBaselines(filterHounds(state.hounds, state.filter)).baselines);
    group.hidden = baselines.length === 0;
    if (baselines.length === 0) group.setAttribute("hidden", ""); else group.removeAttribute("hidden");
    const sum = q("hounds-baselines-summary");
    if (sum) sum.textContent = `Baselines (${baselines.length}): the yardsticks every other hound is measured against`;
    for (const hound of baselines) baseBox.appendChild(row(hound));
  }
}

function renderMeta() {
  const basis = q("hounds-basis");
  if (basis) {
    const p = state.payload || {};
    const notice = noticeLine(p);
    basis.textContent = [
      p.basis ? `Basis: ${p.basis}` : "Basis: the server did not send a basis sentence.",
      p.as_of ? `As of ${fmtWhen(p.as_of) || p.as_of}.` : "",
      notice,
    ].filter(Boolean).join(" ");
  }
}

function renderAll() {
  renderFilter();
  renderChartPanel();
  renderBoard();
  renderMeta();
}

// ---- stream ---------------------------------------------------------------------------------------

function streamItem(item) {
  const who = String(item.who_decided || "").toLowerCase();
  const name = item.hound_name || item.name || "";
  const when = fmtWhen(item.at || item.ts || item.time_utc || item.created_utc || item.date);
  const text = item.summary || item.text || item.reason || item.message || "";
  return h("li", { class: "hd-stream__item", "data-who": who || "unknown" }, [
    h("span", { class: `hd-who hd-who--${who || "unknown"}`, "data-hook": "stream-who" }, `Decided by: ${whoLabel(who)}`),
    name ? h("span", { class: "hd-stream__hound" }, [avatarSvg(name, { size: 18, category: item.category }),
      item.hound_id !== undefined ? h("a", { href: houndHref(item.hound_id), text: name }) : h("span", { text: name })]) : null,
    h("span", { class: "hd-stream__text", text }),
    when ? h("span", { class: "hd-fine hd-stream__when", text: when }) : null,
  ]);
}

let streamInflight = false;

export async function loadStream() {
  const box = q("hounds-stream");
  if (!box || streamInflight) return;
  streamInflight = true;
  try {
    const data = await apiGet("/hounds/stream");
    clearNode(box);
    const items = Array.isArray(data && data.items) ? data.items : [];
    if (items.length === 0) {
      box.appendChild(h("p", { class: "hd-muted", "data-hook": "stream-empty",
        text: "No decisions yet. Each one will show here with who made it: the rule, the code or the model." }));
    } else {
      const ul = h("ul", { class: "hd-stream__list", "data-hook": "stream-list" });
      for (const item of items.slice(0, 40)) ul.appendChild(streamItem(item || {}));
      box.appendChild(ul);
    }
  } catch (err) {
    const e = describeError(err, "the decision stream");
    if (box.querySelector("[data-hook='stream-list']")) {
      if (!box.querySelector("[data-hook='stream-stale']")) {
        box.appendChild(h("p", { class: "hd-fine", "data-hook": "stream-stale",
          text: "Could not refresh just now; this is the previous list." }));
      }
    } else {
      clearNode(box);
      box.appendChild(stateBox(e.kind, e.text, () => { loadStream(); }));
    }
  } finally {
    streamInflight = false;
  }
}

// ---- graveyard ------------------------------------------------------------------------------------

function graveRow(hound) {
  const fwd = segmentView(hound, "forward");
  return h("li", { class: "hd-grave__item", "data-hound": hound.id }, [
    avatarSvg(hound.name, { size: 36, gray: true }),
    h("div", {}, [
      h("a", { class: "hd-row__name", href: houndHref(hound.id), text: hound.name || NOT_REPORTED }),
      hound.last_bet_utc ? h("span", { class: "hd-fine", text: ` last bet ${fmtWhen(hound.last_bet_utc)}` }) : null,
      h("p", { class: "hd-grave__cause", "data-hook": "grave-cause" }, [h("strong", { text: "Cause: " }),
        hound.cause || hound.retired_cause || "not stated by the server"]),
      h("p", { class: "hd-fine", text: [fwd && fwd.record ? `forward ${fmtRecord(fwd.record)}` : "",
        hound.verdict && hound.verdict.label ? `verdict at the end: ${hound.verdict.label}` : ""].filter(Boolean).join("; ") }),
    ]),
  ]);
}

export async function loadGraveyard() {
  const box = q("hounds-graveyard");
  if (!box) return;
  try {
    const data = await apiGet("/hounds/graveyard");
    clearNode(box);
    const list = Array.isArray(data && data.hounds) ? data.hounds : [];
    if (list.length === 0) {
      box.appendChild(h("p", { class: "hd-muted", "data-hook": "grave-empty",
        text: "Nobody has been retired yet. When a hound is retired, or retires itself, it is listed here with the cause." }));
      return;
    }
    const ul = h("ul", { class: "hd-grave__list", "data-hook": "grave-list" });
    for (const hound of list) ul.appendChild(graveRow(hound));
    box.appendChild(ul);
  } catch (err) {
    clearNode(box);
    const e = describeError(err, "the graveyard");
    box.appendChild(stateBox(e.kind, e.text, () => { loadGraveyard(); }));
  }
}

// ---- boot -----------------------------------------------------------------------------------------

export async function loadBoard() {
  const list = q("hounds-list");
  if (list) { clearNode(list); list.appendChild(h("li", { class: "hd-muted", text: "Loading the race..." })); }
  try {
    const data = await apiGet("/hounds");
    state.payload = data || {};
    state.hounds = Array.isArray(data && data.hounds) ? data.hounds : [];
    state.seriesError = null;
  } catch (err) {
    state.hounds = [];
    state.payload = null;
    if (list) {
      clearNode(list);
      const e = describeError(err, "the leaderboard");
      list.appendChild(h("li", {}, [stateBox(e.kind, e.text, () => { boot(); })]));
    }
    renderFilter();
    const panel = q("hounds-chart-panel");
    if (panel) { clearNode(panel); panel.appendChild(h("p", { class: "hd-muted", "data-hook": "chart-needs-board",
      text: "The chart needs the leaderboard, which is not available right now." })); }
    return false;
  }
  if (!state.hiddenInitialised) {
    for (const x of state.hounds) if (categoryOf(x) === "baseline") state.hidden.add(String(x.id));
    state.hiddenInitialised = true;
  }
  renderAll();
  // the chart's data loads after the board so the board is never held up by it
  const ids = state.hounds.map((x) => encodeURIComponent(String(x.id)));
  if (ids.length) {
    try {
      state.series = normalizeSeries(await apiGet(`/hounds/series?ids=${ids.join(",")}`));
      state.seriesError = null;
    } catch (err) {
      state.series = null;
      state.seriesError = err;
    }
  } else {
    state.series = {};
  }
  renderAll();
  return true;
}

export async function boot() {
  await Promise.all([loadBoard(), loadStream(), loadGraveyard()]);
}

function main() {
  boot();
  const poller = createPoller({ run: () => { loadStream(); }, intervalMs: STREAM_POLL_MS });
  poller.start();
  let resizeTimer = null;
  if (typeof window !== "undefined" && window.addEventListener) {
    window.addEventListener("resize", () => {
      if (resizeTimer !== null) clearTimeout(resizeTimer);
      resizeTimer = setTimeout(() => { resizeTimer = null; if (state.series) renderChartPanel(); }, 150);
    });
  }
  globalThis.__houndsPoller = poller;
}

export const __state = state;

if (typeof document !== "undefined" && typeof window !== "undefined") {
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", main);
  else main();
}
