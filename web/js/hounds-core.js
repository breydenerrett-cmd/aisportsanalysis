/**
 * Shared, mostly pure helpers for the three Hounds pages (web/hounds.html, web/hound.html,
 * web/build-a-hound.html). Nothing in here fetches; nothing claims anything the server did not send.
 *
 * THE SHAPES THE PAGES READ ARE THE SHAPES OF src/hounds/contract.py (the single source of truth) AND
 * OF api/hounds_create.py. They were first written against a guess; tests/test_hounds_integration.py
 * now feeds the pages payloads built by the real Python code, and tests/hounds_web_fixtures.py builds
 * its fixtures from the same builders, so a drift fails a test instead of a visitor.
 *
 *   GET /hounds                {hounds: [HoundSummary], as_of, basis, paper_only, not_advice}
 *   GET /hounds/series?ids=    {series: {id: [SeriesPoint]}} -- FORWARD points only; a zero point first
 *   GET /hounds/stream         {items: [StreamItem], page, page_size, total, pages, as_of}
 *   GET /hounds/graveyard      {hounds: [HoundSummary with status "retired" and retired {date, cause}]}
 *   GET /hounds/{id}           HoundSummary + series + bets {items, page, page_size, total, pages}
 *   GET /hounds/{id}/bets?page={items: [BetRow], page, page_size, total, pages}
 *   GET /hounds/menu           name{min,max}, tagline{max}, sports[{value,label}], markets[...],
 *                              side_rules[{value,label,markets}], price_min{presets,lowest},
 *                              price_max{presets,highest}, min_books{min,max}, max_bets_per_day{min,max},
 *                              lock_minutes{choices}, max_running_per_account
 *   GET /hounds/{id}/spec      {spec, copied_from, rule_text}
 *   POST /hounds               {spec, copied_from?} -> {hound: HoundSummary}
 *   GET /hounds/mine           {hounds: [HoundSummary], limit_running}
 *   (any of the GETs)          {warming_up: true, retry_after_seconds, message} while the stats are first built
 *
 * HoundSummary: record and clv and verdict are FORWARD only; `replay` is its own block
 * {bets, wins, losses, pushes, voids, units_recorded_price, note}; units_average_price (the board average,
 * the headline) may be null; units_recorded_price is the best quote recorded at lock (the small print).
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

/** Two prices, two words (owner grading ruling): the AVERAGE price is the headline, the BEST price small print. */
export const AVERAGE_PRICE_WORDS = "average price";
export const BEST_PRICE_WORDS = "best price";

/**
 * "+1.20u average price, +1.50u best price" for a record. The average price is the headline number a bettor
 * shopping nothing would have seen; the best price is the single best quote recorded at lock. A null
 * average is "not reported", never zero.
 */
export function unitsPairText(rec) {
  const r = rec || {};
  return `${fmtUnits(r.units_average_price)} ${AVERAGE_PRICE_WORDS}, ${fmtUnits(r.units_recorded_price)} ${BEST_PRICE_WORDS}`;
}

export const UNITS_EXPLAINER =
  "Ranked by paper units this season (each bet at the units its hound stakes, average price).";

/** What each status means, a bit longer than the one-liner on the leaderboard. Keyed on the referee's label. */
export const VERDICT_MEANING = {
  "BEATING THE CLOSE":
    "Over its bets so far, this model's prices have beaten the closing line by more than luck alone usually does. "
    + "That says it shops well. It does not say it will win, and it is not a tip.",
  "NO DIFFERENT FROM THE MARKET":
    "This model's prices cannot be told apart from the closing line: not better, not worse.",
  "TOO EARLY":
    "A verdict comes once a model has enough bets with a measurable closing price. Until then the record is shown as it stands.",
  "PAYING THE VIG":
    "This model's prices have landed worse than the closing line, the way betting into the bookmaker's cut does. "
    + "Wins and losses so far, good or bad, are mostly luck.",
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

/** Decimal odds of an American price (null for anything that is not one), for comparing two prices. */
export function americanDecimal(p) {
  if (!isNum(p) || (p > -100 && p < 100)) return null;
  return p > 0 ? 1 + p / 100 : 1 + 100 / -p;
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
 * Verdict order: the VERDICT first. Inside one verdict, the hound with more settled bets first (a
 * bigger sample is the better-supported row), then name. Units are never a sort key.
 *
 * THE KENNEL PAGE NO LONGER USES THIS ORDER (owner voice pass, 2026-10-18): its leaderboard is ranked by
 * paper units (hounds-voice.js sortByUnits) and the old verdict rides beside each dog as a badge, so a dog can
 * lead the board and still wear FEEDING THE BOOK. This helper stays for anything that still wants the
 * referee's order.
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
  "#6E9BFF", "#E0A458", "#5CC8B5", "#B58CFF", "#78B8D8", "#C9A66B", "#8FA3C0", "#D68FB3",
];

/** Categories the house pack uses. The badge colour follows the category; the words are always written too. */
export const CATEGORY_COLORS = {
  stats: "#6E9BFF", history: "#E0A458", market: "#4FC3D9", math: "#B58CFF", intangibles: "#D68FB3",
  esoteric: "#C9B458", random: "#C97B7B", mixed: "#5CC8B5", simple: "#7FB8A8", baseline: "#9AA3B2",
  "ai-desk": "#8FE9FA", persona: "#D68FB3", ai: "#7FD6A4", numerology: "#C9B458",
};
export const CATEGORY_LABELS = {
  stats: "Stats", history: "History", market: "Market", math: "Math", intangibles: "Intangibles",
  esoteric: "Esoteric", random: "Random", mixed: "Mixed", simple: "Simple", baseline: "Baseline",
  "ai-desk": "AI desk", persona: "Persona", ai: "AI", numerology: "Numerology",
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

/** Colour by category when the model has one; otherwise one of the palette by name. */
export function categoryColor(name, category) {
  const cat = String(category || "").toLowerCase();
  return CATEGORY_COLORS[cat] || AVATAR_COLORS[hashName(name) % AVATAR_COLORS.length];
}

export function houndColor(hound) {
  return categoryColor(hound && hound.name, categoryOf(hound));
}


// ---- monogram badges -----------------------------------------------------------------------------

/**
 * Two letters for a model: the first letters of its first two words ("Steamy Setter" -> "SS"), or the first
 * two letters of a one-word name ("Pointer" -> "PO"). Upper case, ASCII letters and digits only.
 */
export function initialsOf(name) {
  const words = String(name || "").split(/[^A-Za-z0-9]+/).filter(Boolean);
  if (words.length === 0) return "?";
  if (words.length === 1) return words[0].slice(0, 2).toUpperCase();
  return (words[0].charAt(0) + words[1].charAt(0)).toUpperCase();
}

/**
 * The model's badge: a rounded tile with its two initials, coloured by category (the same colour the chart
 * line uses). A plain element: no image, no drawing. Decorative: the name is always written beside it.
 */
export function monogram(name, { size = 36, category = "", muted = false } = {}) {
  const color = muted ? "#6A707B" : categoryColor(name, category);
  return h("span", { class: "hd-mono", "aria-hidden": "true", "data-monogram": initialsOf(name),
    "data-category": String(category || "") || undefined,
    style: `--mono:${color};width:${size}px;height:${size}px;font-size:${Math.round(size * 0.38)}px`,
    text: initialsOf(name) });
}

/** The same badge as an SVG node, for the share card image (the card is drawn to a canvas from SVG). */
export function monogramSvg(name, { size = 96, category = "", muted = false } = {}) {
  const color = muted ? "#6A707B" : categoryColor(name, category);
  return s("svg", { class: "hd-mono-svg", viewBox: "0 0 48 48", width: size, height: size, "aria-hidden": "true",
    focusable: "false", "data-monogram": initialsOf(name) }, [
    s("rect", { x: 1, y: 1, width: 46, height: 46, rx: 9, fill: "#171B22", stroke: color, "stroke-width": 2 }),
    s("text", { x: 24, y: 30.5, "text-anchor": "middle", "font-size": 19, "font-weight": 700,
      "font-family": "Arial, Helvetica, sans-serif", fill: color }, initialsOf(name)),
  ]);
}

// ---- series ---------------------------------------------------------------------------------------

export const REPLAY_NOTE = "old-board rehearsal (the same rule on earlier games; written after, so it never counts)";
export const NO_FORWARD_TEXT = "No live bets yet";

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
 * numbers and path strings; the renderer only has to draw them. `tickLabel(value, step)` words the y ticks (the
 * bankroll chart plots dollars above the $1,000 start and labels its ticks as balances).
 */
export function layoutChart(series, { width = 640, height = 280, margin, tickLabel: labelFn } = {}) {
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
    yTicks.push({ value: val, y: y(val), label: (labelFn || tickLabel)(val, step) });
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

/**
 * "Handler 3F2A" -> "handler-3f2a", "Bob's Dogs" -> "bobs-dogs": the public handle of a member's kennel
 * (src/hounds/kennels.py `slug` and member_profile.py `slug`, the same rule: an apostrophe is dropped, not a separator).
 */
export function kennelHandle(label) {
  return String(label || "").trim().toLowerCase().replace(/['\u2019]/g, "").replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");
}

/** The page of one member's public dogs, from the owner label a member's dog carries ("" when it has none). */
export function kennelHref(ownerDisplay) {
  const handle = kennelHandle(ownerDisplay);
  return handle ? `kennel.html?u=${encodeURIComponent(handle)}` : "";
}

/**
 * What a kennel is called: the member's own kennel name ("Bob's Dogs") once they set one, else "Handler 3F2A's kennel"
 * (the anonymous handle is the default; a kennel name can never look like one, member_profile.validate_name).
 */
export function kennelName(ownerDisplay) {
  const label = String(ownerDisplay || "").trim();
  if (!label) return "A member's kennel";
  return /^Handler [0-9A-F]{4}$/i.test(label) ? `${label}'s kennel` : label;
}

/**
 * One sentence for a stream item (contract StreamItem: a BetRow plus hound_name, verdict, refused,
 * decided_utc). A refusal is said to be a refusal ("Passed: ..."); a play names the pick, the game and
 * both prices, then the hound's own reason. Nothing is added that the item did not carry.
 */
export function streamSummary(item) {
  const it = item || {};
  const where = it.game ? ` in ${it.game}` : "";
  if (it.refused) {
    return `Passed${where}: ${it.reason || "no reason given"}`.replace(/: Refused: /, ": ");
  }
  const pick = it.selection || NOT_REPORTED;
  const prices = [];
  if (isNum(it.price_average)) prices.push(`${fmtPrice(it.price_average)} ${AVERAGE_PRICE_WORDS}`);
  if (isNum(it.price)) prices.push(`${fmtPrice(it.price)} ${BEST_PRICE_WORDS}${it.book ? ` at ${it.book}` : ""}`);
  const priced = prices.length ? ` at ${prices.join(", ")}` : "";
  return `${pick}${where}${priced}.${it.reason ? ` ${it.reason}` : ""}`;
}

/** True while the server is still working out the numbers for the first time (a 200 with `warming_up`). */
export function isWarming(payload) {
  return !!(payload && typeof payload === "object" && payload.warming_up === true);
}

export const WARMING_DEFAULT_MS = 5000;

/** How long to wait before asking again: the server's own `retry_after_seconds`, kept between 1 s and 30 s. */
export function warmingRetryMs(payload) {
  const s = payload && isNum(payload.retry_after_seconds) ? payload.retry_after_seconds : WARMING_DEFAULT_MS / 1000;
  return Math.max(1000, Math.min(30000, Math.round(s * 1000)));
}

const warmTimers = new Map();

/**
 * While a section's answer is `warming_up`, ask again on the server's own cadence. One timer per key; the
 * page calls `stopWarmingRetry(key)` as soon as a real answer arrives. (An interval, not a chain of
 * timeouts, so a test can fire it by hand like the stream's poller.)
 */
export function retryWhileWarming(key, run, payload) {
  if (warmTimers.has(key)) return;
  warmTimers.set(key, globalThis.setInterval(() => { run(); }, warmingRetryMs(payload)));
}

export function stopWarmingRetry(key) {
  if (!warmTimers.has(key)) return;
  globalThis.clearInterval(warmTimers.get(key));
  warmTimers.delete(key);
}

export const WARMING_FALLBACK_TEXT =
  "The race is warming up: the numbers are being worked out and this takes a few seconds the first time. "
  + "Nothing is wrong and nothing is missing.";

export function whoLabel(who) {
  return { code: "Code", model: "Model", rule: "Rule" }[String(who || "").toLowerCase()] || "Not stated";
}

// ---- the build form: menu -> options, spec <-> form ------------------------------------------------

/** A menu option is `{value, label}` (the real menu; `markets` rides along on side rules) or a bare string. */
export function optionOf(opt) {
  if (opt && typeof opt === "object") {
    const id = opt.value ?? opt.id ?? opt.key ?? opt.name ?? opt.label;
    return { id: String(id), label: String(opt.label ?? opt.name ?? id),
      markets: Array.isArray(opt.markets) ? opt.markets.map(String) : null };
  }
  return { id: String(opt), label: String(opt), markets: null };
}

// Defaults only: the build page reads the real limits from GET /hounds/menu (name.max, tagline.max).
export const NAME_MAX = 24;
export const TAGLINE_MAX = 80;

/**
 * The body POSTed to /hounds, exactly what api/hounds_create.py's CreateHoundRequest takes:
 * `{spec: {name, tagline, sports, markets, side_rule, price_min, price_max, min_books,
 * max_bets_per_day, lock_minutes}, copied_from?}`. `copiedFrom` is the id the form was pre-filled from
 * (GET /hounds/{id}/spec -> `copied_from`); it travels beside the spec, never inside it, so a copy is
 * recorded as one. The spec is the menu's fields and nothing else: the server refuses unknown keys.
 */
export function buildSpec(form, copiedFrom) {
  const body = {
    spec: {
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
    },
  };
  if (copiedFrom) body.copied_from = String(copiedFrom);
  return body;
}

/**
 * GET /hounds/{id}/spec -> `{spec: {...}, copied_from, rule_text}` -> form values. The server suggests a
 * fresh name for the copy (names are unique), which is pre-filled so the builder can keep or change it.
 */
export function specToForm(payload) {
  const wrapped = payload && typeof payload === "object" && payload.spec && typeof payload.spec === "object";
  const sp = wrapped ? payload.spec : (payload && typeof payload === "object" ? payload : {});
  const list = (v) => (Array.isArray(v) ? v.map((x) => optionOf(x).id) : v ? [optionOf(v).id] : []);
  return {
    name: typeof sp.name === "string" ? sp.name : "",
    tagline: typeof sp.tagline === "string" ? sp.tagline : "",
    sports: list(sp.sports),
    markets: list(sp.markets),
    side_rule: sp.side_rule !== undefined ? String(sp.side_rule) : "",
    price_min: sp.price_min,
    price_max: sp.price_max,
    min_books: sp.min_books,
    max_bets_per_day: sp.max_bets_per_day,
    lock_minutes: sp.lock_minutes,
    copied_from: wrapped && payload.copied_from ? String(payload.copied_from) : "",
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
  const side = labelFor(menu && menu.side_rules, form.side_rule);
  const parts = [`Bet ${side.charAt(0).toLowerCase()}${side.slice(1)} in ${joinWords(markets)} (${joinWords(sports)})`];
  if (isNum(form.price_min) && isNum(form.price_max)) {
    // the engine prices a bet at the board AVERAGE across the books (not the best single quote)
    parts.push(`only when the average price across the books is between ${fmtPrice(form.price_min)} and ${fmtPrice(form.price_max)}`);
  }
  if (isNum(form.min_books)) parts.push(`at least ${form.min_books} ${form.min_books === 1 ? "book" : "books"} must be posting a price`);
  if (isNum(form.max_bets_per_day)) parts.push(`at most ${form.max_bets_per_day} ${form.max_bets_per_day === 1 ? "bet" : "bets"} a day`);
  if (isNum(form.lock_minutes)) parts.push(`it bets ${form.lock_minutes} minutes before the start`);
  parts.push("it never takes a price of -200 or worse");
  return parts.join("; ") + ".";
}
