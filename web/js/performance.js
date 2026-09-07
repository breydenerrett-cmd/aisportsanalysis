/**
 * PAPER / RESEARCH PERFORMANCE (#/performance, GET /performance,
 * src/report/paper_performance.py's build_performance_payload).
 *
 * WHAT THIS IS -- paper accounts only, flat 1-unit stakes, settled from
 * official results. Not audited, not real-money returns, not a forecast
 * (the payload's own `disclaimer`, rendered verbatim below, is mandatory
 * and never paraphrased). Every number on this screen comes straight off
 * the payload; this module computes nothing except a bar/line WIDTH from
 * an already-supplied number and a percentage string from an already-
 * supplied fraction.
 *
 * THREE SYSTEM CLASSES, NEVER CONFLATED (see the payload's own module
 * docstring): CONTROL is a fixed-direction null baseline, never a pick.
 * MARKET REFERENCE republishes the board's own de-vigged consensus, a
 * calibration reference only. FORWARD-TEST SYSTEM is an unproven
 * directional thesis under forward test. Each per-class section below
 * carries its own one-line explanation so a reader never mistakes one
 * class's numbers for another's meaning.
 */

import { apiGet } from "./api.js";
import { el, clear, renderError, renderLoading, notYetAvailable, formatAmerican } from "./dom.js";
import { armEntrances } from "./motion.js";
import { renderRecordStrip } from "./recordstrip.js";
import { renderDayRecap } from "./dayrecap.js";

const CLASS_ORDER = ["FORWARD_TEST", "ALL", "MARKET_REFERENCE", "CONTROL"];
const CLASS_LABEL = {
  FORWARD_TEST: "FORWARD-TEST SYSTEM",
  MARKET_REFERENCE: "MARKET REFERENCE",
  CONTROL: "CONTROL",
  ALL: "ALL SYSTEMS COMBINED",
};
const CLASS_EXPLAIN = {
  CONTROL: "Fixed-direction null baselines, never picks — a floor to measure everything else against.",
  MARKET_REFERENCE: "Republishes the board's own de-vigged consensus. A calibration reference only, "
    + "never a system this product is claiming credit for.",
  FORWARD_TEST: "An unproven directional thesis, under forward test right now. Nothing here is validated "
    + "yet — these are the systems actually being tested.",
  ALL: "Every paper account rolled into one, across all three classes. A single system's own class "
    + "still tells you what kind of claim (or non-claim) it is making.",
};

/** A percentage the reader should read as a delta (return on units) --
 * carries an explicit sign so a loss is never visually ambiguous with a
 * plain magnitude. */
function pctFmt(fraction) {
  if (typeof fraction !== "number" || !Number.isFinite(fraction)) return null;
  const sign = fraction > 0 ? "+" : "";
  return `${sign}${(fraction * 100).toFixed(1)}%`;
}

/** A percentage that is always a plain non-negative magnitude (hit rate)
 * -- never signed, since "67.2% of bets won" is not a gain/loss delta. */
function pctPlain(fraction) {
  if (typeof fraction !== "number" || !Number.isFinite(fraction)) return null;
  return `${(fraction * 100).toFixed(1)}%`;
}

/** A signed unit figure (units net, profit per pick) -- the sign is the
 * whole point (won vs lost units). */
function numFmt(n, digits = 2) {
  if (typeof n !== "number" || !Number.isFinite(n)) return null;
  const sign = n > 0 ? "+" : "";
  return `${sign}${n.toFixed(digits)}`;
}

/** A plain non-negative magnitude (max drawdown) -- never signed, since
 * drawdown is always reported as a positive size, not a delta. */
function numPlain(n, digits = 2) {
  if (typeof n !== "number" || !Number.isFinite(n)) return null;
  return n.toFixed(digits);
}

function figure(value) {
  return value === null || value === undefined
    ? el("span", { class: "perf-figure__na", text: "—" })
    : el("span", { text: String(value) });
}

function sectionHead(label, meta) {
  const head = el("div", { class: "sechead" });
  head.appendChild(el("span", { class: "sechead__label", text: label }));
  head.appendChild(el("span", { class: "sechead__hair" }));
  if (meta) head.appendChild(el("span", { class: "sechead__meta", text: meta }));
  return head;
}

/* ---------------------------------------------------------------------
 * Eyebrow / disclaimer / freshness
 * ------------------------------------------------------------------- */

function renderHead(payload) {
  const wrap = el("div", { class: "perf-head" });
  const eyebrow = el("div", { class: "perf-eyebrow" });
  eyebrow.appendChild(el("span", { class: "badge badge--sample", text: "PAPER / RESEARCH PERFORMANCE" }));
  wrap.appendChild(eyebrow);
  wrap.appendChild(el("p", { class: "perf-disclaimer", "data-hook": "performance-disclaimer",
    text: payload.disclaimer || "" }));

  const freshness = payload.freshness || {};
  const settled = freshness.settled_through || "not yet available";
  const pendingN = typeof freshness.pending_wagers === "number" ? freshness.pending_wagers : 0;
  const dates = Array.isArray(freshness.pending_dates) && freshness.pending_dates.length
    ? freshness.pending_dates.join(", ") : "none";
  wrap.appendChild(el("p", { class: "perf-freshness", "data-hook": "performance-freshness",
    text: `Settled through ${settled} · ${pendingN} wagers pending (${dates})` }));
  return wrap;
}

/* ---------------------------------------------------------------------
 * Summary tiles -- FORWARD_TEST and ALL
 * ------------------------------------------------------------------- */

function summaryTile(label, cls) {
  const tile = el("div", { class: "perf-tile panel chamfer" });
  tile.appendChild(el("div", { class: "perf-tile__label", text: label }));
  if (!cls) {
    tile.appendChild(notYetAvailable("No rollup for this class yet.", "NO CLASS DATA"));
    return tile;
  }
  const rows = [
    ["N SETTLED", cls.n_settled],
    ["W-L-P", `${cls.wins}-${cls.losses}-${cls.pushes}`],
    ["UNITS NET", numFmt(cls.units_net), typeof cls.units_net === "number" ? cls.units_net : null],
    ["RETURN ON UNITS", pctFmt(cls.return_on_units), typeof cls.return_on_units === "number" ? cls.return_on_units : null],
    ["HIT RATE", pctPlain(cls.hit_rate)],
    ["MAX DRAWDOWN", numPlain(cls.drawdown_max)],
  ];
  const grid = el("div", { class: "perf-tile__grid" });
  for (const [k, v, signed] of rows) {
    const row = el("div", { class: "perf-tile__row" });
    row.appendChild(el("span", { class: "perf-tile__key", text: k }));
    // UNITS NET / RETURN ON UNITS are this tile's own headline figures --
    // large and win/loss coloured (green up, red down), same convention
    // the rest of this screen already uses for a settled outcome.
    const big = signed !== undefined;
    const tone = big && signed !== null ? (signed > 0 ? " perf-tile__value--pos" : signed < 0 ? " perf-tile__value--neg" : "") : "";
    row.appendChild(el("span", { class: `perf-tile__value${big ? " perf-tile__value--big" : ""}${tone}` },
      [v === null || v === undefined ? notYetAvailable("Field not present on this class's rollup.", "N/A") : figure(v)]));
    grid.appendChild(row);
  }
  tile.appendChild(grid);
  return tile;
}

function renderSummaryTiles(classes) {
  const wrap = el("div", { class: "perf-summary", "data-hook": "performance-summary-tiles" });
  wrap.appendChild(summaryTile("FORWARD-TEST SYSTEM", classes && classes.FORWARD_TEST));
  wrap.appendChild(summaryTile("ALL SYSTEMS COMBINED", classes && classes.ALL));
  return wrap;
}

/* ---------------------------------------------------------------------
 * Per-class sections + system tables
 * ------------------------------------------------------------------- */

function classTable(systems) {
  const wrap = el("div", { class: "ov2-table-wrap" });
  const table = el("table", { class: "ov2-table" });
  const thead = el("thead");
  const hr = el("tr");
  for (const label of ["SYSTEM ID", "N", "W-L-P", "UNITS NET", "RETURN %", "HIT RATE", "MAX DRAWDOWN", "LAST DAY"]) {
    hr.appendChild(el("th", { scope: "col", text: label }));
  }
  thead.appendChild(hr);
  table.appendChild(thead);
  const tbody = el("tbody");
  for (const s of systems) {
    const tr = el("tr");
    tr.appendChild(el("td", { text: s.system_id }));
    tr.appendChild(el("td", { text: String(s.n_settled) }));
    tr.appendChild(el("td", { text: `${s.wins}-${s.losses}-${s.pushes}` }));
    tr.appendChild(el("td", { text: numFmt(s.units_net) || "—" }));
    tr.appendChild(el("td", { text: pctFmt(s.return_on_units) || "—" }));
    tr.appendChild(el("td", { text: pctPlain(s.hit_rate) || "—" }));
    tr.appendChild(el("td", { text: numPlain(s.drawdown_max) || "—" }));
    tr.appendChild(el("td", { text: s.last_day || "—" }));
    tbody.appendChild(tr);
  }
  table.appendChild(tbody);
  wrap.appendChild(table);
  return wrap;
}

function renderClassSections(classes, systems) {
  const wrap = el("div", { class: "perf-classes", "data-hook": "performance-class-sections" });
  const byClass = new Map();
  for (const s of systems || []) {
    if (!byClass.has(s.system_class)) byClass.set(s.system_class, []);
    byClass.get(s.system_class).push(s);
  }
  for (const cls of CLASS_ORDER) {
    if (cls === "ALL") continue; // ALL has no per-system rows (it is the rollup across classes)
    const section = el("section", { class: "perf-class", "data-hook": "performance-class-section",
      "data-class": cls });
    section.appendChild(sectionHead(CLASS_LABEL[cls] || cls));
    section.appendChild(el("p", { class: "perf-class__explain", text: CLASS_EXPLAIN[cls] || "" }));
    const rollup = classes && classes[cls];
    if (rollup) {
      section.appendChild(el("p", { class: "perf-class__rollup",
        text: `${rollup.n_settled} settled · ${rollup.wins}-${rollup.losses}-${rollup.pushes} · `
          + `${numFmt(rollup.units_net) || "—"} units net · ${pctFmt(rollup.return_on_units) || "—"} return` }));
    }
    const rows = byClass.get(cls) || [];
    if (rows.length) section.appendChild(classTable(rows));
    else section.appendChild(notYetAvailable(`No individual systems reporting under ${cls} yet.`, "NO SYSTEMS"));
    wrap.appendChild(section);
  }
  return wrap;
}

/* ---------------------------------------------------------------------
 * Analytical cuts (BY MARKET / BY ODDS RANGE / BY DECISION GRADE /
 * BY CLASS + a ROLLING last-7/last-30 row) -- payload.cuts, computed by
 * src/report/paper_performance.py's cuts(). Every bucket is read
 * straight off the payload; this module computes nothing except a
 * pos/neg colour class from an already-signed number. A THIN bucket
 * (n_settled < 20) shows a THIN SAMPLE chip and is deliberately never
 * given the pos/neg colour treatment -- see this file's own docstring on
 * never conflating a tiny sample with established performance.
 * ------------------------------------------------------------------- */

const CUTS_TABLE_COLUMNS = ["BUCKET", "N", "W-L-P", "UNITS NET", "RETURN %", "HIT RATE", "AVG ODDS"];

function thinSampleChip() {
  return el("span", { class: "pv-chip pv-chip--warn perf-cuts__thin", "data-hook": "cuts-thin-chip", text: "THIN SAMPLE" });
}

/** A units-net or return-% figure, signed and coloured -- UNLESS the
 * bucket is thin, in which case it renders the same figure with no
 * colour class at all (never good/bad-coded a tiny sample). */
function cutsSignedCell(value, thin, fmt) {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    return el("td", { text: "—" });
  }
  const text = fmt(value) || "—";
  if (thin) return el("td", { text });
  const cls = value > 0 ? "perf-cuts__figure--pos" : value < 0 ? "perf-cuts__figure--neg" : null;
  return el("td", { class: cls, text });
}

function cutsTable(title, buckets) {
  const block = el("div", { class: "perf-cuts__block", "data-hook": "performance-cuts-table" });
  block.appendChild(el("h3", { class: "perf-cuts__title", text: title }));
  const list = Array.isArray(buckets) ? buckets : [];
  if (list.length === 0) {
    block.appendChild(notYetAvailable("No buckets on this payload.", "NO CUT DATA"));
    return block;
  }
  const wrap = el("div", { class: "ov2-table-wrap" });
  const table = el("table", { class: "ov2-table" });
  const thead = el("thead");
  const hr = el("tr");
  for (const label of CUTS_TABLE_COLUMNS) {
    hr.appendChild(el("th", { scope: "col", text: label }));
  }
  thead.appendChild(hr);
  table.appendChild(thead);
  const tbody = el("tbody");
  for (const b of list) {
    const tr = el("tr");
    const labelCell = el("td", { class: "perf-cuts__label" });
    labelCell.appendChild(el("span", { text: b.label || b.key || "—" }));
    if (b.thin) labelCell.appendChild(thinSampleChip());
    tr.appendChild(labelCell);
    tr.appendChild(el("td", { text: typeof b.n_settled === "number" ? String(b.n_settled) : "—" }));
    tr.appendChild(el("td", { text: `${b.wins}-${b.losses}-${b.pushes}` }));
    tr.appendChild(cutsSignedCell(b.units_net, b.thin, numFmt));
    tr.appendChild(cutsSignedCell(b.return_on_units, b.thin, pctFmt));
    tr.appendChild(el("td", { text: pctPlain(b.hit_rate) || "—" }));
    tr.appendChild(el("td", { text: numPlain(b.avg_odds_decimal) || "—" }));
    tbody.appendChild(tr);
  }
  table.appendChild(tbody);
  wrap.appendChild(table);
  block.appendChild(wrap);
  return block;
}

const ROLLING_LABEL = { last_7: "LAST 7 DAYS", last_30: "LAST 30 DAYS" };

function rollingCell(bucket) {
  const cell = el("div", { class: "perf-cuts__rolling-cell panel chamfer" });
  const head = el("div", { class: "perf-cuts__rolling-head" });
  head.appendChild(el("span", { class: "perf-cuts__rolling-label",
    text: ROLLING_LABEL[bucket.key] || bucket.label || bucket.key }));
  if (bucket.thin) head.appendChild(thinSampleChip());
  cell.appendChild(head);
  const figs = el("div", { class: "perf-cuts__rolling-figs" });
  figs.appendChild(el("span", { text: `N ${typeof bucket.n_settled === "number" ? bucket.n_settled : "—"}` }));
  figs.appendChild(el("span", { text: `${bucket.wins}-${bucket.losses}-${bucket.pushes}` }));
  const netText = typeof bucket.units_net === "number" ? `${numFmt(bucket.units_net)} units` : "—";
  const netCls = !bucket.thin && typeof bucket.units_net === "number"
    ? (bucket.units_net > 0 ? "perf-cuts__figure--pos" : bucket.units_net < 0 ? "perf-cuts__figure--neg" : null)
    : null;
  figs.appendChild(el("span", { class: netCls, text: netText }));
  figs.appendChild(el("span", { text: `${pctFmt(bucket.return_on_units) || "—"} return` }));
  cell.appendChild(figs);
  return cell;
}

function renderRolling(rolling) {
  const wrap = el("div", { class: "perf-cuts__block", "data-hook": "performance-cuts-rolling" });
  wrap.appendChild(el("h3", { class: "perf-cuts__title", text: "ROLLING" }));
  const list = Array.isArray(rolling) ? rolling : [];
  if (list.length === 0) {
    wrap.appendChild(notYetAvailable("No rolling windows on this payload.", "NO ROLLING DATA"));
    return wrap;
  }
  const row = el("div", { class: "perf-cuts__rolling-row" });
  for (const bucket of list) row.appendChild(rollingCell(bucket));
  wrap.appendChild(row);
  return wrap;
}

function renderCuts(cuts, cutsNote) {
  const section = el("section", { class: "perf-cuts", "data-hook": "performance-cuts" });
  section.appendChild(sectionHead("ANALYTICAL CUTS"));
  if (!cuts) {
    section.appendChild(notYetAvailable("No cuts on this payload.", "NO CUTS"));
    return section;
  }
  section.appendChild(cutsTable("BY MARKET", cuts.by_market));
  section.appendChild(cutsTable("BY ODDS RANGE", cuts.by_odds_range));
  section.appendChild(cutsTable("BY DECISION GRADE", cuts.by_grade));
  section.appendChild(cutsTable("BY CLASS", cuts.by_class));
  section.appendChild(renderRolling(cuts.rolling));
  if (cutsNote) section.appendChild(el("p", { class: "perf-cuts__note", text: cutsNote }));
  return section;
}

/* ---------------------------------------------------------------------
 * Recent picks
 * ------------------------------------------------------------------- */

const OUTCOME_CHIP = { win: "W", loss: "L", push: "P", pending: "PENDING" };

function outcomeChip(outcome) {
  const label = OUTCOME_CHIP[outcome] || (outcome ? String(outcome).toUpperCase() : "—");
  const tone = outcome === "win" ? "money" : outcome === "loss" ? "outline"
    : outcome === "push" ? "live" : "warn";
  return el("span", { class: `pv-chip pv-chip--${tone}`, "data-hook": "recent-pick-outcome", text: label });
}

function renderRecentPicks(picks) {
  const section = el("section", { class: "perf-picks", "data-hook": "performance-recent-picks" });
  section.appendChild(sectionHead("RECENT PICKS", `${(picks || []).length} SHOWN`));
  if (!picks || picks.length === 0) {
    section.appendChild(notYetAvailable("No wagers recorded yet.", "NO PICKS"));
    return section;
  }
  const wrap = el("div", { class: "ov2-table-wrap" });
  const table = el("table", { class: "ov2-table" });
  const thead = el("thead");
  const hr = el("tr");
  for (const label of ["DAY", "MATCHUP", "MARKET", "SIDE / LINE", "PRICE", "SYSTEM CLASS", "OUTCOME", "UNITS"]) {
    hr.appendChild(el("th", { scope: "col", text: label }));
  }
  thead.appendChild(hr);
  table.appendChild(thead);
  const tbody = el("tbody");
  for (const p of picks) {
    const tr = el("tr");
    tr.appendChild(el("td", { text: p.day || p.date || "—" }));
    tr.appendChild(el("td", { text: p.matchup || "—" }));
    tr.appendChild(el("td", { text: p.market_key || "—" }));
    const sideLine = [p.side ? String(p.side).toUpperCase() : null, p.line !== null && p.line !== undefined ? String(p.line) : null]
      .filter(Boolean).join(" ");
    tr.appendChild(el("td", { text: sideLine || "—" }));
    const price = formatAmerican(p.price_american);
    tr.appendChild(el("td", { text: price || "—" }));
    tr.appendChild(el("td", { text: p.system_class || "—" }));
    tr.appendChild(el("td", {}, [outcomeChip(p.outcome)]));
    tr.appendChild(el("td", { text: typeof p.profit_units === "number" ? numFmt(p.profit_units) : "—" }));
    tbody.appendChild(tr);
  }
  table.appendChild(tbody);
  wrap.appendChild(table);
  section.appendChild(wrap);
  return section;
}

/* ---------------------------------------------------------------------
 * BET WON vs REASONING CORRECT
 * ------------------------------------------------------------------- */

function reasoningCell(label, value) {
  const cell = el("div", { class: "perf-matrix__cell" });
  cell.appendChild(el("div", { class: "perf-matrix__value", text: typeof value === "number" ? String(value) : "—" }));
  cell.appendChild(el("div", { class: "perf-matrix__label", text: label }));
  return cell;
}

function renderReasoningSplit(split) {
  const section = el("section", { class: "perf-reasoning panel chamfer", "data-hook": "performance-reasoning-split" });
  section.appendChild(el("h3", { class: "perf-reasoning__title", text: "BET WON vs REASONING CORRECT" }));
  if (!split) {
    section.appendChild(notYetAvailable("No reasoning-outcome data on this payload.", "NO REASONING SPLIT"));
    return section;
  }
  const matrix = split.matrix || {};
  const grid = el("div", { class: "perf-matrix" });
  const header = el("div", { class: "perf-matrix__row perf-matrix__row--head" });
  header.appendChild(el("span", {}));
  header.appendChild(el("span", { class: "perf-matrix__colhead", text: "REASONING CONFIRMED" }));
  header.appendChild(el("span", { class: "perf-matrix__colhead", text: "REASONING REFUTED" }));
  grid.appendChild(header);
  const wonRow = el("div", { class: "perf-matrix__row" });
  wonRow.appendChild(el("span", { class: "perf-matrix__rowhead", text: "BET WON" }));
  wonRow.appendChild(reasoningCell("won · confirmed", matrix.won_reasoning_confirmed));
  wonRow.appendChild(reasoningCell("won · refuted", matrix.won_reasoning_refuted));
  grid.appendChild(wonRow);
  const lostRow = el("div", { class: "perf-matrix__row" });
  lostRow.appendChild(el("span", { class: "perf-matrix__rowhead", text: "BET LOST" }));
  lostRow.appendChild(reasoningCell("lost · confirmed (variance)", matrix.lost_reasoning_confirmed));
  lostRow.appendChild(reasoningCell("lost · refuted", matrix.lost_reasoning_refuted));
  grid.appendChild(lostRow);
  section.appendChild(grid);

  const untested = split.counts && typeof split.counts.UNTESTED === "number" ? split.counts.UNTESTED : matrix.untested;
  section.appendChild(el("p", { class: "perf-reasoning__untested", "data-hook": "performance-untested-count",
    text: `UNTESTED: ${typeof untested === "number" ? untested : "—"}` }));
  if (split.note) section.appendChild(el("p", { class: "perf-reasoning__note", text: split.note }));
  return section;
}

/* ---------------------------------------------------------------------
 * Sparkline -- series.ALL and series.FORWARD_TEST cumulative units
 * ------------------------------------------------------------------- */

const SPARK_W = 640;
const SPARK_H = 160;
const SPARK_PAD = 14;

function polylinePoints(series, minV, maxV) {
  if (!series.length) return "";
  const span = Math.max(maxV - minV, 0.0001);
  const stepX = series.length > 1 ? (SPARK_W - SPARK_PAD * 2) / (series.length - 1) : 0;
  return series.map((pt, i) => {
    const x = SPARK_PAD + stepX * i;
    const y = SPARK_H - SPARK_PAD - ((pt.units_net - minV) / span) * (SPARK_H - SPARK_PAD * 2);
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");
}

function renderSparkline(seriesAll, seriesForward) {
  const section = el("section", { class: "perf-spark panel chamfer", "data-hook": "performance-sparkline" });
  section.appendChild(el("h3", { class: "perf-spark__title", text: "CUMULATIVE UNITS — ALL vs FORWARD-TEST" }));
  const all = Array.isArray(seriesAll) ? seriesAll : [];
  const fwd = Array.isArray(seriesForward) ? seriesForward : [];
  if (all.length === 0 && fwd.length === 0) {
    section.appendChild(notYetAvailable("No settled series yet — nothing to chart.", "NO SERIES"));
    return section;
  }
  const values = [...all, ...fwd].map((p) => p.units_net).filter((n) => typeof n === "number");
  const minV = Math.min(0, ...values);
  const maxV = Math.max(0, ...values);

  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", `0 0 ${SPARK_W} ${SPARK_H}`);
  svg.setAttribute("class", "perf-spark__svg");
  svg.setAttribute("role", "img");
  svg.setAttribute("aria-label", "Cumulative units over time for ALL systems and FORWARD-TEST systems");

  const zeroY = SPARK_H - SPARK_PAD - ((0 - minV) / Math.max(maxV - minV, 0.0001)) * (SPARK_H - SPARK_PAD * 2);
  const zeroLine = document.createElementNS("http://www.w3.org/2000/svg", "line");
  zeroLine.setAttribute("x1", String(SPARK_PAD));
  zeroLine.setAttribute("x2", String(SPARK_W - SPARK_PAD));
  zeroLine.setAttribute("y1", zeroY.toFixed(1));
  zeroLine.setAttribute("y2", zeroY.toFixed(1));
  zeroLine.setAttribute("class", "perf-spark__zero");
  svg.appendChild(zeroLine);

  const drawSeries = (series, className) => {
    if (!series.length) return;
    const poly = document.createElementNS("http://www.w3.org/2000/svg", "polyline");
    poly.setAttribute("points", polylinePoints(series, minV, maxV));
    poly.setAttribute("class", className);
    svg.appendChild(poly);
  };
  drawSeries(all, "perf-spark__line perf-spark__line--all");
  drawSeries(fwd, "perf-spark__line perf-spark__line--forward");

  section.appendChild(svg);

  const legend = el("div", { class: "perf-spark__legend" });
  const lastOf = (series) => (series.length ? series[series.length - 1].units_net : null);
  legend.appendChild(el("span", { class: "perf-spark__legend-item perf-spark__legend-item--all",
    text: `ALL: ${numFmt(lastOf(all)) || "—"} units` }));
  legend.appendChild(el("span", { class: "perf-spark__legend-item perf-spark__legend-item--forward",
    text: `FORWARD-TEST: ${numFmt(lastOf(fwd)) || "—"} units` }));
  section.appendChild(legend);
  return section;
}

/* ---------------------------------------------------------------------
 * View
 * ------------------------------------------------------------------- */

export async function renderPerformance(container) {
  clear(container);
  const screen = el("div", { class: "screen perf-screen", "data-view": "performance" });
  container.appendChild(screen);
  screen.appendChild(renderLoading("LOADING PAPER PERFORMANCE"));

  let payload;
  try {
    payload = await apiGet("/performance?limit=50");
  } catch (err) {
    clear(screen);
    renderError(screen, err);
    return;
  }
  clear(screen);

  // RECORD STRIP + DAILY RECAP GALLERY -- mounted above the existing
  // paper-standings content (see this module's own docstring update);
  // web/js/recordstrip.js and web/js/dayrecap.js own their own
  // render/fetch, this screen only places them.
  const recordStripHost = el("div", {});
  screen.appendChild(recordStripHost);
  await renderRecordStrip(recordStripHost);

  await renderDayRecap(screen);

  screen.appendChild(renderHead(payload));
  screen.appendChild(renderSummaryTiles(payload.classes));
  screen.appendChild(renderClassSections(payload.classes, payload.systems));
  screen.appendChild(renderCuts(payload.cuts, payload.cuts_note));
  screen.appendChild(renderRecentPicks(payload.recent_picks));
  screen.appendChild(renderReasoningSplit(payload.reasoning_split));
  const series = payload.series || {};
  screen.appendChild(renderSparkline(series.ALL, series.FORWARD_TEST));

  for (const note of payload.notes || []) {
    screen.appendChild(el("p", { class: "perf-note", text: note }));
  }

  armEntrances(screen);
}
