/**
 * Shared, mostly pure helpers for the three Hounds pages (web/hounds.html, web/hound.html,
 * web/build-a-hound.html). Nothing in here fetches; nothing claims anything the server did not send.
 *
 * WHAT THE PAGES ASSUME ABOUT THE API (built against the contract, in parallel with the API workers):
 *   GET /hounds            {hounds[], as_of, basis, paper_only, <not-advice line>}
 *   GET /hounds/series?ids=a,b  per hound [{date, cum_units_average_price, cum_units_recorded_price,
 *                                           bets_settled, cum_clv_mean_pts}] -- `normalizeSeries` accepts
 *                          {series:{id:[...]}}, {id:[...]}, {series:[{id,points}]} or [{id,points}].
 *   GET /hounds/stream     {items[], page}      GET /hounds/graveyard {hounds[] with cause}
 *   GET /hounds/{id}       summary (+ bets[])   GET /hounds/{id}/bets {bets[]}
 *   GET /hounds/menu       {sports[], markets[], side_rules[], price_band{min,max}, books{min,max},
 *                          max_bets_per_day{min,max}, lock_minutes[]}
 *   GET /hounds/{id}/spec, POST /hounds, GET /hounds/mine
 * Every field is read defensively: a missing field renders as "not reported", never as a made-up value.
 *
 * ORDER IS BY VERDICT, NEVER BY UNITS. See VERDICT_ORDER / sortByVerdict.
 */

export const PAPER_LINE = "Paper only. No real bet is ever placed. Not advice. 21+.";
export const CAP_LINE = "The -200-or-worse cap is always on.";
export const HOUND_LIMIT = 3;

/** Best verdict first. Anything the server sends that is not in this list sorts after all of them. */
export const VERDICT_ORDER = [
  "BEATING THE CLOSE",
  "NO DIFFERENT FROM THE MARKET",
  "TOO EARLY",
  "PAYING THE VIG",
];

export const UNITS_EXPLAINER =
  "Units over a few weeks are mostly luck. The verdict asks whether a hound beat the closing price, "
  + "using a test written before the race started.";

/** What each verdict means in plain words. The server's own sentence is always shown first. */
export const VERDICT_MEANING = {
  "BEATING THE CLOSE":
    "The test written before the race says this hound's prices have beaten the closing prices by more "
    + "than chance alone usually produces. That is a statement about price against the close. "
    + "It is not a profit claim, and it does not say what happens next.",
  "NO DIFFERENT FROM THE MARKET":
    "The prices this hound took cannot be told apart from the closing prices. The test can show neither "
    + "better nor worse yet.",
  "TOO EARLY":
    "Not enough settled bets for the test to say anything. At this size, a run of wins or losses is "
    + "mostly luck.",
  "PAYING THE VIG":
    "The test finds the prices this hound took were worse than the closing prices, the way betting into "
    + "a bookmaker's margin is. Results so far, good or bad, are mostly luck.",
};

export const NOT_REPORTED = "not reported";

// ---- tiny DOM builders (no dependency on dom.js: these pages load light) --------------------------

export const SVG_NS = "http://www.w3.org/2000/svg";

function applyAttrs(node, attrs) {
  for (const [key, value] of Object.entries(attrs || {})) {
    if (value === undefined || value === null || value === false) continue;
    if (key === "text") node.textContent = String(value);
    else if (key === "on") {
      for (const [evt, fn] of Object.entries(value)) node.addEventListener(evt, fn);
    } else node.setAttribute(key, value === true ? "" : String(value));
  }
}

function append(node, kids) {
  for (const kid of (Array.isArray(kids) ? kids : [kids])) {
    if (kid === undefined || kid === null || kid === false) continue;
    node.appendChild(typeof kid === "string" || typeof kid === "number"
      ? document.createTextNode(String(kid)) : kid);
  }
  return node;
}

/** HTML element. */
export function h(tag, attrs = {}, kids = []) {
  const node = document.createElement(tag);
  applyAttrs(node, attrs);
  return append(node, kids);
}

/** SVG element. */
export function s(tag, attrs = {}, kids = []) {
  const node = document.createElementNS(SVG_NS, tag);
  applyAttrs(node, attrs);
  return append(node, kids);
}

export function clearNode(node) {
  while (node.firstChild) node.removeChild(node.firstChild);
  return node;
}

// ---- numbers --------------------------------------------------------------------------------------

export function isNum(v) {
  return typeof v === "number" && Number.isFinite(v);
}

/** "+3.20" / "-1.05" / "0.00"; null/undefined -> "not reported". */
export function signed(n, digits = 2) {
  if (!isNum(n)) return NOT_REPORTED;
  const fixed = Math.abs(n).toFixed(digits);
  if (Number(fixed) === 0) return (0).toFixed(digits);
  return (n > 0 ? "+" : "-") + fixed;
}

export function fmtUnits(n) {
  return isNum(n) ? `${signed(n, 2)}u` : NOT_REPORTED;
}

export function fmtPrice(p) {
  if (!isNum(p)) return NOT_REPORTED;
  return p > 0 ? `+${p}` : String(p);
}

/** The record as W-L-P with the bet count first so the sample size is never hidden. */
export function fmtRecord(rec) {
  const r = rec || {};
  if (!isNum(r.bets)) return NOT_REPORTED;
  const parts = [`${r.wins ?? 0}-${r.losses ?? 0}`];
  if (r.pushes) parts[0] += `-${r.pushes}`;
  let text = `${r.bets} ${r.bets === 1 ? "bet" : "bets"} (${parts[0]})`;
  if (r.voids) text += `, ${r.voids} void`;
  return text;
}

/** CLV with its interval and sample size. Null means "not measured yet", never zero. */
export function fmtClv(clv) {
  if (!clv || !isNum(clv.mean_pts)) return { main: "not measured yet", detail: "" };
  const main = `${signed(clv.mean_pts, 1)} pts`;
  const hasInterval = isNum(clv.ci_low) && isNum(clv.ci_high);
  const interval = hasInterval
    ? `interval ${signed(clv.ci_low, 1)} to ${signed(clv.ci_high, 1)}` : "no interval yet";
  const n = isNum(clv.n) ? `n=${clv.n}` : "n not reported";
  return { main, detail: `${interval}, ${n}` };
}

export function dayKey(value) {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(value || ""));
  return m ? `${m[1]}-${m[2]}-${m[3]}` : "";
}

/** Whole days since the epoch for an ISO date or timestamp; NaN when unreadable. */
export function dayNumber(value) {
  const key = dayKey(value);
  if (!key) return NaN;
  const [y, mo, d] = key.split("-").map(Number);
  return Date.UTC(y, mo - 1, d) / 86400000;
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** "Oct 17" from a day number or an ISO string. */
export function shortDate(value) {
  const n = typeof value === "number" ? value : dayNumber(value);
  if (!isNum(n)) return "";
  const d = new Date(n * 86400000);
  return `${MONTHS[d.getUTCMonth()]} ${d.getUTCDate()}`;
}

export function fmtWhen(value) {
  const text = String(value || "");
  const m = /^(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2})/.exec(text);
  if (m) return `${shortDate(m[1])} ${m[2]} UTC`;
  return dayKey(text) ? shortDate(text) : "";
}

// ---- verdict ordering -----------------------------------------------------------------------------

export function verdictLabel(h_) {
  const v = h_ && h_.verdict;
  return String((v && v.label) || "").trim().toUpperCase();
}

export function verdictRank(label) {
  const i = VERDICT_ORDER.indexOf(String(label || "").trim().toUpperCase());
  return i === -1 ? VERDICT_ORDER.length : i;
}

/**
 * Leaderboard order: the VERDICT first. Inside one verdict, the hound with more settled bets first (a
 * bigger sample is the better-supported row), then name. Units are never a sort key.
 */
export function sortByVerdict(hounds) {
  const betsOf = (x) => (x && x.record && isNum(x.record.bets) ? x.record.bets : 0);
  return (hounds || []).slice().sort((a, b) =>
    verdictRank(verdictLabel(a)) - verdictRank(verdictLabel(b))
    || betsOf(b) - betsOf(a)
    || String(a.name || "").localeCompare(String(b.name || "")));
}

export function filterHounds(hounds, filter, category = "all") {
  let list = hounds || [];
  if (filter === "house" || filter === "user") list = list.filter((x) => x.kind === filter);
  if (category && category !== "all") list = list.filter((x) => categoryOf(x) === category);
  return list;
}

/** Baselines are shown in their own collapsed group below the race, never mixed into it and never hidden. */
export function splitBaselines(hounds) {
  const race = [], baselines = [];
  for (const x of hounds || []) (categoryOf(x) === "baseline" ? baselines : race).push(x);
  return { race, baselines };
}

/** Categories present among these hounds (not baseline), in the house order. */
export function presentCategories(hounds) {
  const seen = new Set((hounds || []).map(categoryOf).filter((c) => c && c !== "baseline"));
  const known = Object.keys(CATEGORY_LABELS).filter((c) => seen.has(c));
  return known.concat([...seen].filter((c) => !known.includes(c)).sort());
}

/** "chip modifier" for a verdict; colour is never the only signal (the chip always carries the words). */
export function verdictTone(label) {
  switch (String(label || "").trim().toUpperCase()) {
    case "BEATING THE CLOSE": return "good";
    case "NO DIFFERENT FROM THE MARKET": return "flat";
    case "TOO EARLY": return "early";
    case "PAYING THE VIG": return "bad";
    default: return "unknown";
  }
}

export function verdictGlyph(tone) {
  return { good: "▲", flat: "▬", early: "◌", bad: "▼", unknown: "?" }[tone] || "?";
}

// ---- avatars --------------------------------------------------------------------------------------

export const AVATAR_COLORS = [
  "#FF7A7A", "#FFB020", "#F2E34B", "#2ED47A", "#00E0FF", "#6E9BFF", "#B58CFF", "#FF8AD8",
];

/** Categories the house pack uses. The avatar colour follows the category; the words are always written too. */
export const CATEGORY_COLORS = {
  stats: "#6E9BFF", history: "#FFB020", market: "#00E0FF", math: "#B58CFF", intangibles: "#FF8AD8",
  esoteric: "#F2E34B", random: "#FF7A7A", mixed: "#2ED47A", simple: "#7FD6C2", baseline: "#A3A9B5",
};
export const CATEGORY_LABELS = {
  stats: "Stats", history: "History", market: "Market", math: "Math", intangibles: "Intangibles",
  esoteric: "Esoteric", random: "Random", mixed: "Mixed", simple: "Simple", baseline: "Baseline",
};
/** Hounds in these categories carry a small tag, in the same type size as their name, and are never hidden. */
export const FUN_CATEGORIES = ["esoteric", "random"];
export const FUN_TAG = "for fun / control";

export function categoryOf(hound) {
  return String((hound && hound.category) || "").trim().toLowerCase();
}

export function categoryLabel(cat) {
  return CATEGORY_LABELS[cat] || (cat ? cat.charAt(0).toUpperCase() + cat.slice(1) : "");
}

/** FNV-1a, so the same name is the same dog on every page and every reload. */
export function hashName(name) {
  let hash = 0x811c9dc5;
  const text = String(name || "");
  for (let i = 0; i < text.length; i++) {
    hash ^= text.charCodeAt(i);
    hash = Math.imul(hash, 0x01000193) >>> 0;
  }
  return hash >>> 0;
}

/** Colour by category when the hound has one; otherwise one of 8 by name. Ears always vary by name. */
export function avatarSpec(name, category) {
  const hash = hashName(name);
  const cat = String(category || "").toLowerCase();
  const color = CATEGORY_COLORS[cat] || AVATAR_COLORS[hash % AVATAR_COLORS.length];
  return { colorIndex: hash % AVATAR_COLORS.length, color, ears: (hash >>> 3) % 2 ? "floppy" : "pointy" };
}

export function houndColor(hound) {
  return avatarSpec(hound && hound.name, categoryOf(hound)).color;
}

/** A dog-head silhouette in one of 8 colours. Decorative: the name is always written beside it. */
export function avatarSvg(name, { size = 40, gray = false, category = "" } = {}) {
  const spec = avatarSpec(name, category);
  const fill = gray ? "#6A707B" : spec.color;
  const ink = "#0B0C0E";
  const ears = spec.ears === "floppy"
    ? [s("path", { d: "M10 14 C4 14 3 28 8 33 C12 30 14 22 15 16 Z", fill: ink }),
       s("path", { d: "M38 14 C44 14 45 28 40 33 C36 30 34 22 33 16 Z", fill: ink })]
    : [s("path", { d: "M11 8 L19 15 L11 24 Z", fill: ink }), s("path", { d: "M37 8 L29 15 L37 24 Z", fill: ink })];
  return s("svg", { class: "hd-avatar", viewBox: "0 0 48 48", width: size, height: size,
    "aria-hidden": "true", focusable: "false", "data-avatar-color": fill }, [
    s("circle", { cx: 24, cy: 24, r: 24, fill }),
    ...ears,
    s("path", { d: "M14 17 C14 12 34 12 34 17 L34 28 C34 35 29 40 24 40 C19 40 14 35 14 28 Z", fill: ink }),
    s("ellipse", { cx: 24, cy: 31, rx: 6, ry: 5, fill }),
    s("ellipse", { cx: 24, cy: 29, rx: 2.4, ry: 1.7, fill: ink }),
    s("circle", { cx: 19, cy: 22, r: 1.8, fill }),
    s("circle", { cx: 29, cy: 22, r: 1.8, fill }),
  ]);
}

// ---- series ---------------------------------------------------------------------------------------

export const REPLAY_NOTE = "replay (rule written 2026-10-18, applied to earlier boards)";
export const NO_FORWARD_TEXT = "No forward bets yet";

/**
 * A hound's results for one segment. FORWARD is the headline: bets placed after the rule was written.
 * REPLAY is the same rule applied to earlier boards. Accepts `hound.forward` / `hound.replay`,
 * `hound.segments.{forward,replay}`, or (no segments sent) the top-level record/clv as the forward view.
 */
export function segmentView(hound, segment) {
  if (!hound) return null;
  const seg = hound[segment] || (hound.segments && hound.segments[segment]) || null;
  if (seg && typeof seg === "object") {
    return { record: seg.record || (isNum(seg.bets) ? seg : null), clv: seg.clv !== undefined ? seg.clv : null };
  }
  const topLevel = { record: hound.record || null, clv: hound.clv !== undefined ? hound.clv : null };
  if (segment === "forward" && hound.segment !== "replay" && (hound.record || hound.clv)) return topLevel;
  if (hound.segment === segment && (hound.record || hound.clv)) return topLevel;
  return null;
}

/**
 * Whatever shape the series endpoint answers in -> { id: [point, ...] }, sorted by date, one point per
 * (segment, date) (the last one wins), rows without a readable date dropped. Every point comes out with
 * a `segment`: its own, else "forward".
 */
export function normalizeSeries(payload) {
  const out = {};
  const put = (id, list, forcedSegment) => {
    if (!Array.isArray(list)) return;
    const byKey = new Map();
    for (const raw of list) {
      const key = dayKey(raw && raw.date);
      if (!key) continue;
      const segment = forcedSegment || (raw.segment === "replay" ? "replay" : "forward");
      byKey.set(`${segment}|${key}`, Object.assign({}, raw, { segment }));
    }
    const merged = (out[String(id)] || []).concat([...byKey.values()]);
    out[String(id)] = merged.sort((x, y) => (dayKey(x.date) < dayKey(y.date) ? -1 : dayKey(x.date) > dayKey(y.date) ? 1 : 0));
  };
  const putEntry = (id, entry) => {
    if (Array.isArray(entry)) put(id, entry);
    else if (entry && typeof entry === "object") {
      if (Array.isArray(entry.points)) put(id, entry.points);
      if (Array.isArray(entry.series)) put(id, entry.series);
      if (Array.isArray(entry.forward)) put(id, entry.forward, "forward");
      if (Array.isArray(entry.replay)) put(id, entry.replay, "replay");
    }
  };
  if (Array.isArray(payload)) {
    for (const entry of payload) if (entry && entry.id !== undefined) putEntry(entry.id, entry);
    return out;
  }
  if (!payload || typeof payload !== "object") return out;
  const body = payload.series !== undefined ? payload.series : payload;
  if (Array.isArray(body)) return normalizeSeries(body);
  if (body && typeof body === "object") for (const [id, entry] of Object.entries(body)) putEntry(id, entry);
  return out;
}

/** The points of one segment. */
export function pointsFor(series, id, segment) {
  return ((series || {})[String(id)] || []).filter((p) => p.segment === segment);
}

/** True when any hound has a forward point with at least one settled bet. */
export function hasForwardData(series) {
  for (const list of Object.values(series || {})) {
    for (const p of list) {
      if (p.segment === "forward" && (isNum(p.bets_settled) ? p.bets_settled > 0 : true)) return true;
    }
  }
  return false;
}

/** Points -> [{date, value, bets}] for one field, dropping rows where the field is null. */
export function toChartPoints(points, key) {
  const out = [];
  for (const p of points || []) {
    if (!p || !isNum(p[key])) continue;
    out.push({ date: dayKey(p.date), value: p[key], bets: isNum(p.bets_settled) ? p.bets_settled : null });
  }
  return out;
}

/** The numbers behind a row's sparkline: the hound's `spark` (last 30), else the tail of its series. */
export function sparkValues(hound, seriesPoints) {
  const spark = hound && hound.spark;
  let values = [];
  if (Array.isArray(spark)) {
    values = spark.map((p) => (isNum(p) ? p : (p && (isNum(p.cum_units_average_price) ? p.cum_units_average_price
      : isNum(p.value) ? p.value : isNum(p.units) ? p.units : null)))).filter(isNum);
  } else if (Array.isArray(seriesPoints)) {
    values = toChartPoints(seriesPoints, "cum_units_average_price").map((p) => p.value);
  }
  return values.slice(-30);
}

// ---- chart geometry (pure; tested without a DOM) --------------------------------------------------

function niceStep(range, target) {
  const raw = range / target;
  const pow = 10 ** Math.floor(Math.log10(raw));
  const f = raw / pow;
  return (f <= 1 ? 1 : f <= 2 ? 2 : f <= 5 ? 5 : 10) * pow;
}

function tickLabel(v, step) {
  const digits = step >= 1 ? 0 : Math.min(3, Math.ceil(-Math.log10(step)));
  const fixed = Math.abs(v).toFixed(digits);
  return Number(fixed) === 0 ? (0).toFixed(digits) : (v < 0 ? "-" : "") + fixed;
}

/** A smooth curve through the points that never overshoots them (monotone cubic). */
export function monotonePath(pts) {
  const n = pts.length;
  const f = (v) => Math.round(v * 10) / 10;
  if (n === 0) return "";
  if (n === 1) return `M${f(pts[0].x)},${f(pts[0].y)}`;
  if (n === 2) return `M${f(pts[0].x)},${f(pts[0].y)}L${f(pts[1].x)},${f(pts[1].y)}`;
  const dx = [], m = [];
  for (let i = 0; i < n - 1; i++) {
    dx.push(pts[i + 1].x - pts[i].x);
    m.push(dx[i] === 0 ? 0 : (pts[i + 1].y - pts[i].y) / dx[i]);
  }
  const t = [m[0]];
  for (let i = 1; i < n - 1; i++) t.push(m[i - 1] * m[i] <= 0 ? 0 : (m[i - 1] + m[i]) / 2);
  t.push(m[n - 2]);
  for (let i = 0; i < n - 1; i++) {
    if (m[i] === 0) { t[i] = 0; t[i + 1] = 0; continue; }
    const a = t[i] / m[i], b = t[i + 1] / m[i], r = a * a + b * b;
    if (r > 9) { const tau = 3 / Math.sqrt(r); t[i] = tau * a * m[i]; t[i + 1] = tau * b * m[i]; }
  }
  let d = `M${f(pts[0].x)},${f(pts[0].y)}`;
  for (let i = 0; i < n - 1; i++) {
    const w = dx[i] / 3;
    d += `C${f(pts[i].x + w)},${f(pts[i].y + t[i] * w)},${f(pts[i + 1].x - w)},${f(pts[i + 1].y - t[i + 1] * w)},`
      + `${f(pts[i + 1].x)},${f(pts[i + 1].y)}`;
  }
  return d;
}

/**
 * Lay out a multi-line chart. `series` is [{id, name, color, points:[{date, value, bets}]}] (points from
 * toChartPoints). The y domain ALWAYS contains zero, so the zero baseline is always drawn. Returns plain
 * numbers and path strings; the renderer only has to draw them.
 */
export function layoutChart(series, { width = 640, height = 280, margin } = {}) {
  const m = Object.assign({ l: 44, r: 14, t: 12, b: 26 }, margin || {});
  const plot = { x0: m.l, x1: width - m.r, y0: m.t, y1: height - m.b };
  const all = [];
  for (const sr of series) for (const p of sr.points) {
    const day = dayNumber(p.date);
    if (isNum(day) && isNum(p.value)) all.push({ day, value: p.value });
  }
  if (all.length === 0) {
    return { empty: true, width, height, plot, lines: [], yTicks: [], xTicks: [], zeroY: null,
      days: [], x: () => plot.x0, y: () => plot.y1 };
  }
  const dayMin = Math.min(...all.map((p) => p.day));
  const dayMax = Math.max(...all.map((p) => p.day));
  let lo = Math.min(0, ...all.map((p) => p.value));
  let hi = Math.max(0, ...all.map((p) => p.value));
  if (hi - lo < 1e-9) { lo = -1; hi = 1; }
  const pad = (hi - lo) * 0.06;
  lo -= lo < 0 ? pad : 0;
  hi += hi > 0 ? pad : 0;
  const step = niceStep(hi - lo, 4);
  const yMin = Math.floor(lo / step + 1e-9) * step;
  const yMax = Math.ceil(hi / step - 1e-9) * step;
  const x = (day) => (dayMax === dayMin
    ? (plot.x0 + plot.x1) / 2
    : plot.x0 + ((day - dayMin) / (dayMax - dayMin)) * (plot.x1 - plot.x0));
  const y = (v) => plot.y1 - ((v - yMin) / (yMax - yMin)) * (plot.y1 - plot.y0);
  const yTicks = [];
  for (let v = yMin; v <= yMax + step / 2; v += step) {
    const val = Math.round(v / step) * step;
    yTicks.push({ value: val, y: y(val), label: tickLabel(val, step) });
  }
  const days = [...new Set(all.map((p) => p.day))].sort((a, b) => a - b);
  const wanted = Math.min(days.length, 5);
  const xTicks = [];
  for (let i = 0; i < wanted; i++) {
    const day = wanted === 1 ? days[0] : days[Math.round((i * (days.length - 1)) / (wanted - 1))];
    if (!xTicks.some((t) => t.day === day)) xTicks.push({ day, x: x(day), label: shortDate(day) });
  }
  const lines = series.map((sr) => {
    const pts = sr.points
      .map((p) => ({ day: dayNumber(p.date), value: p.value, bets: p.bets, date: p.date }))
      .filter((p) => isNum(p.day) && isNum(p.value))
      .map((p) => Object.assign(p, { x: x(p.day), y: y(p.value) }));
    return { id: sr.id, name: sr.name, color: sr.color, points: pts, single: pts.length === 1,
      empty: pts.length === 0, d: pts.length >= 2 ? monotonePath(pts) : "" };
  });
  return { empty: false, width, height, plot, lines, yTicks, xTicks, zeroY: y(0), days, x, y,
    yMin, yMax, dayMin, dayMax };
}

/** The day (from the chart's own dates) nearest to a pixel x. */
export function nearestDay(layout, px) {
  if (layout.empty || layout.days.length === 0) return null;
  let best = layout.days[0], bestDist = Infinity;
  for (const day of layout.days) {
    const dist = Math.abs(layout.x(day) - px);
    if (dist < bestDist) { best = day; bestDist = dist; }
  }
  return best;
}

/** For a day: each line's most recent point on or before it (a hound that has not started has none). */
export function valuesAtDay(layout, day) {
  const rows = [];
  for (const line of layout.lines) {
    let last = null;
    for (const p of line.points) if (p.day <= day) last = p;
    if (last) rows.push({ id: line.id, name: line.name, color: line.color, value: last.value, bets: last.bets,
      date: last.date, exact: last.day === day });
  }
  return rows;
}

/** A tiny polyline layout for a leaderboard row: values -> path, zero line when the range spans it. */
export function layoutSparkline(values, { width = 96, height = 28, pad = 3 } = {}) {
  const vals = (values || []).filter(isNum);
  if (vals.length < 2) return { empty: true, width, height, d: "", zeroY: null, end: null };
  let lo = Math.min(0, ...vals), hi = Math.max(0, ...vals);
  if (hi - lo < 1e-9) { lo = -1; hi = 1; }
  const x = (i) => pad + (i / (vals.length - 1)) * (width - 2 * pad);
  const y = (v) => height - pad - ((v - lo) / (hi - lo)) * (height - 2 * pad);
  const pts = vals.map((v, i) => ({ x: x(i), y: y(v) }));
  return { empty: false, width, height, d: monotonePath(pts), zeroY: y(0),
    end: pts[pts.length - 1], first: vals[0], last: vals[vals.length - 1], n: vals.length };
}

// ---- polling that stops when nobody is looking ----------------------------------------------------

/**
 * Call `run` every `intervalMs` while the page is visible. When the page is hidden the timer is cleared
 * and nothing fires; when it becomes visible again `run` fires once straight away and the timer restarts.
 * `doc`, `setTimer` and `clearTimer` are injectable so a test can drive it without waiting a minute.
 */
export function createPoller({ run, intervalMs = 60000, doc, setTimer, clearTimer }) {
  const d = doc || document;
  const set = setTimer || ((fn, ms) => globalThis.setInterval(fn, ms));
  const clear = clearTimer || ((id) => globalThis.clearInterval(id));
  let timer = null;
  let on = false;
  const visible = () => d.visibilityState !== "hidden";
  const tick = () => { if (visible()) run(); };
  const arm = () => { if (timer === null) timer = set(tick, intervalMs); };
  const disarm = () => { if (timer !== null) { clear(timer); timer = null; } };
  const onVisibility = () => { if (visible()) { run(); arm(); } else disarm(); };
  return {
    start() {
      if (on) return;
      on = true;
      d.addEventListener("visibilitychange", onVisibility);
      if (visible()) arm();
    },
    stop() {
      on = false;
      d.removeEventListener("visibilitychange", onVisibility);
      disarm();
    },
    get armed() { return timer !== null; },
  };
}

// ---- errors ---------------------------------------------------------------------------------------

/** One honest sentence for a failed load; `what` is e.g. "the leaderboard". */
export function describeError(err, what) {
  const status = err && err.status;
  if (status === 404) return { kind: "missing", text: `${cap(what)} is not switched on yet on this server. Nothing is hidden and nothing is made up; check back later.` };
  if (status === 401 || status === 403) return { kind: "auth", text: `${cap(what)} needs you to be signed in.` };
  if (status === null || status === undefined) return { kind: "down", text: `Could not reach ${what}. It could be your connection or an outage, and it does not mean there is nothing to show. Try again in a minute.` };
  return { kind: "down", text: `${cap(what)} could not be loaded (the server answered ${status}). Try again in a minute.` };
}

function cap(text) {
  return text ? text.charAt(0).toUpperCase() + text.slice(1) : text;
}

/** The server's own not-advice line, when it sent one under a name we recognise. */
export function noticeLine(payload) {
  if (!payload || typeof payload !== "object") return "";
  for (const key of ["not_advice", "not_advice_line", "disclaimer", "notice"]) {
    if (typeof payload[key] === "string" && payload[key].trim()) return payload[key].trim();
  }
  return "";
}

export function houndHref(id) {
  return `hound.html?id=${encodeURIComponent(String(id))}`;
}

export function whoLabel(who) {
  return { code: "Code", model: "Model", rule: "Rule" }[String(who || "").toLowerCase()] || "Not stated";
}

// ---- the build form: menu -> options, spec <-> form ------------------------------------------------

/** A menu option is either a bare string or {id|value|key, label|name}. */
export function optionOf(opt) {
  if (opt && typeof opt === "object") {
    const id = opt.id ?? opt.value ?? opt.key ?? opt.name ?? opt.label;
    return { id: String(id), label: String(opt.label ?? opt.name ?? id) };
  }
  return { id: String(opt), label: String(opt) };
}

export const NAME_MAX = 32;
export const TAGLINE_MAX = 80;

/** The body POSTed to /hounds. One place, so aligning it with the API is a one-line change. */
export function buildSpec(form) {
  return {
    name: form.name,
    tagline: form.tagline,
    sports: form.sports,
    markets: form.markets,
    side_rule: form.side_rule,
    price_min: form.price_min,
    price_max: form.price_max,
    min_books: form.min_books,
    max_bets_per_day: form.max_bets_per_day,
    lock_minutes: form.lock_minutes,
  };
}

/** A spec from GET /hounds/{id}/spec -> form values (accepts the obvious variants of each field). */
export function specToForm(spec) {
  const sp = spec && typeof spec === "object" ? (spec.spec && typeof spec.spec === "object" ? spec.spec : spec) : {};
  const list = (v) => (Array.isArray(v) ? v.map((x) => optionOf(x).id) : v ? [optionOf(v).id] : []);
  const band = sp.price_band || {};
  return {
    sports: list(sp.sports ?? sp.sport),
    markets: list(sp.markets ?? sp.market),
    side_rule: sp.side_rule !== undefined ? optionOf(sp.side_rule).id : "",
    price_min: sp.price_min ?? band.min,
    price_max: sp.price_max ?? band.max,
    min_books: sp.min_books ?? (sp.books && typeof sp.books === "object" ? sp.books.min : sp.books),
    max_bets_per_day: sp.max_bets_per_day,
    lock_minutes: sp.lock_minutes,
  };
}

function joinWords(items) {
  if (items.length <= 1) return items.join("");
  return `${items.slice(0, -1).join(", ")} and ${items[items.length - 1]}`;
}

/** The rule sentence, written by this page from the form values. It is a preview, not the server's text. */
export function previewRuleSentence(form, menu) {
  const labelFor = (list, id) => {
    const found = (list || []).map(optionOf).find((o) => o.id === String(id));
    return found ? found.label : String(id);
  };
  const sports = (form.sports || []).map((id) => labelFor(menu && menu.sports, id));
  const markets = (form.markets || []).map((id) => labelFor(menu && menu.markets, id).toLowerCase());
  if (!sports.length || !markets.length || !form.side_rule) {
    return "Choose a sport, a market and a side rule to see the rule in words.";
  }
  const parts = [`Bet ${labelFor(menu && menu.side_rules, form.side_rule)} in ${joinWords(markets)} (${joinWords(sports)})`];
  if (isNum(form.price_min) && isNum(form.price_max)) {
    parts.push(`only when the best price is between ${fmtPrice(form.price_min)} and ${fmtPrice(form.price_max)}`);
  }
  if (isNum(form.min_books)) parts.push(`at least ${form.min_books} ${form.min_books === 1 ? "book" : "books"} must be posting a price`);
  if (isNum(form.max_bets_per_day)) parts.push(`at most ${form.max_bets_per_day} ${form.max_bets_per_day === 1 ? "bet" : "bets"} a day`);
  if (isNum(form.lock_minutes)) parts.push(`the price is locked ${form.lock_minutes} minutes before the start`);
  parts.push("it never takes a price of -200 or worse");
  return parts.join("; ") + ".";
}
