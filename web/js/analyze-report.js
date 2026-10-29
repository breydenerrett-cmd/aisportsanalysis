/**
 * THE ANALYZE REPORT (owner ask 2026-10-29): what a member hound is picking, why its record looks the way it does, and what could be
 * done about it. Fed by GET /hounds/{id}/report (api/hounds_report.py, src/hounds/analyze_report.py); this file draws what the server
 * answered and works out nothing but where a needle points.
 *
 *   HEADLINE + "HOT HAND OR HOT DICE?"  a half-dial gauge (SVG, role="meter") whose needle sweeps in 700 ms under prefers-reduced-motion:
 *                                       no-preference and is simply drawn at its place otherwise, the referee's verdict in words, and
 *                                       small chips: wins against the wins the prices expected, how often luck alone gives a record that
 *                                       good, and how many bets beat the closing line.
 *   WHAT IS DRIVING IT                  the best and worst slices of the hound's own bets, each with how many bets stand behind it.
 *   WHAT IT IS PICKING                  every ticket, open first. Grades show as the meters of web/js/pick-meters.js when that file exists
 *                                       (loaded at run time, so this file never depends on it) and as "C 60 · V 71" chips when it does
 *                                       not; a ticket with no grades shows neither. A hindsight line is always labelled hindsight.
 *   KEEP IT UP / EXPAND                 the case for changing nothing, and loosening ideas. An idea's button dispatches a CustomEvent
 *                                       "linehound:analyze-expand" with { dogId, id } (and { href } for a spin-off); the training review
 *                                       that applies an idea is wired by the page, never here. Nothing in this file changes a hound.
 *   COACH'S READ                        a short paragraph the server wrote from the numbers above, labelled so.
 *   TEASER                              anyone may read the first three parts. The rest is ONE panel that says what is inside the full
 *                                       report: no blurred fake data, no number that is not there.
 *
 * Every word is the server's and goes in as text (textContent), so a hostile hound name or review never becomes an element. Phone first:
 * 16 px gutters and nothing wider than the screen at 400 px. CSS: css/analyze-report.css, inserted by this module with one <link>.
 */

import { h, s, clearNode, isNum } from "./hounds-core.js";
import { apiGet as defaultGet } from "./api.js";
import { UPGRADE_HREF, UPGRADE_LABEL } from "./upgrade.js";

export const CSS_HREF = "css/analyze-report.css";
export const EXPAND_EVENT = "linehound:analyze-expand";
export const HOST_HOOK = "studio-analyze";
export const COACH_LABEL = "Coach’s read — from the numbers above";
export const METERS_MODULE = "./pick-meters.js";
export const SWEEP_MS = 700;

/** What the full report holds, in the words the teaser's panel uses. The server's `locked` list says which of these are missing. */
export const LOCKED_WORDS = {
  drivers: "What is driving the record: its best and worst slices of bets, with how many bets stand behind each",
  keep_it_up: "The case for changing nothing, from the numbers",
  expand: "Ways to find more of the kind of bet that has been working, counted against today’s board",
  coach_read: "The coach’s read, in plain words",
};

const clean = (v) => (typeof v === "string" ? v.replace(/\s+/g, " ").trim() : "");
const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;
export const unitsText = (u) => (isNum(u) ? `${u >= 0 ? "+" : "-"}${Math.abs(u).toFixed(1)}u` : "");
export const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));

// ---- the stylesheet -------------------------------------------------------------------------------------------------------

/** Insert the one <link> for this module's CSS, once. A page that cannot take it still reads fine: the markup is plain. */
export function ensureStyles() {
  try {
    if (typeof document === "undefined" || !document.head) return false;
    if (document.querySelector && document.querySelector("link[data-analyze-report]")) return false;
    const link = document.createElement("link");
    link.setAttribute("rel", "stylesheet");
    link.setAttribute("href", CSS_HREF);
    link.setAttribute("data-analyze-report", "1");
    document.head.appendChild(link);
    return true;
  } catch (err) {
    return false;
  }
}

// ---- the gauge ------------------------------------------------------------------------------------------------------------

/** The needle's rotation in degrees for a 0 to 100 meter: -90 is all the way left (hot dice), +90 all the way right (hot hand). */
export const needleAngle = (value) => Math.round((clamp(Number(value) || 0, 0, 100) / 100) * 180 - 90);

/** A point on the dial's arc: `t` runs 0 (left) to 180 (right) degrees around the centre (100, 100). */
function arcPoint(t, r) {
  const rad = (t * Math.PI) / 180;
  return [Math.round((100 - r * Math.cos(rad)) * 100) / 100, Math.round((100 - r * Math.sin(rad)) * 100) / 100];
}

/** The path of one coloured stretch of the dial, from meter value `a` to meter value `b`. */
export function arcPath(a, b, r = 80) {
  const [x0, y0] = arcPoint((a / 100) * 180, r);
  const [x1, y1] = arcPoint((b / 100) * 180, r);
  return `M ${x0} ${y0} A ${r} ${r} 0 0 1 ${x1} ${y1}`;
}

/** The three stretches of the dial: the part luck can explain, the part nobody can call yet, and the part the referee has cleared. */
export const ZONES = [["dice", 0, 25], ["mid", 25, 50], ["hand", 50, 100]];

export function gauge(hot) {
  const value = clamp(Math.round(Number(hot.meter) || 0), 0, 100);
  const label = clean(hot.meter_label) || "Too close to call";
  const text = `${value} out of 100: ${label}`;
  const svg = s("svg", { class: "ar-dial", viewBox: "0 0 200 118", "aria-hidden": "true", focusable: "false" }, [
    ...ZONES.map(([name, a, b]) => s("path", { class: `ar-dial__zone ar-dial__zone--${name}`, d: arcPath(a, b), fill: "none", "stroke-width": "14" })),
    s("line", { class: "ar-dial__tick", x1: "100", y1: "13", x2: "100", y2: "29" }),
    s("g", { class: "ar-needle", style: `--ar-angle:${needleAngle(value)}deg`, "data-angle": String(needleAngle(value)) }, [
      s("line", { class: "ar-needle__stem", x1: "100", y1: "100", x2: "100", y2: "36" }),
      s("circle", { class: "ar-needle__hub", cx: "100", cy: "100", r: "6" })]),
  ]);
  return h("div", { class: "ar-gauge", role: "meter", "aria-label": "Hot hand or hot dice?", "aria-valuemin": "0", "aria-valuemax": "100",
    "aria-valuenow": String(value), "aria-valuetext": text, "data-hook": "analyze-gauge", "data-value": String(value) }, [
    svg,
    h("div", { class: "ar-gauge__ends", "aria-hidden": "true" }, [h("span", { text: clean(hot.meter_left) || "Hot dice" }), h("span", { text: clean(hot.meter_right) || "Hot hand" })]),
    h("p", { class: "ar-gauge__read" }, [h("b", { class: "ar-gauge__n", "data-count": "", text: String(value) }), h("span", { class: "ar-gauge__of", text: " / 100" })]),
    h("p", { class: "ar-gauge__label", "data-hook": "analyze-gauge-label", text: label }),
  ]);
}

// ---- the first screen -----------------------------------------------------------------------------------------------------

function chip(label, value, hook, count = false) {
  return h("li", { class: "ar-chip", "data-hook": hook }, [
    h("span", { class: "ar-chip__k", text: label }),
    h("b", Object.assign({ class: "ar-chip__v", text: String(value) }, count ? { "data-count": "" } : {})),
  ]);
}

/** Wins against the wins the prices expected, how often luck alone gives a record that good, and the closing line. */
export function chips(hot) {
  const luck = hot.luck_check || {};
  const clv = hot.clv || {};
  const out = [chip("Wins", hot.actual_w, "analyze-chip-wins", true), chip("Prices expected", isNum(hot.expected_w) ? hot.expected_w.toFixed(1) : "n/a", "analyze-chip-expected", true)];
  if (luck.one_in) out.push(chip(luck.tail === "at_most" ? "A record this poor, by luck" : "A record this good, by luck", `1 in ${luck.one_in}`, "analyze-chip-luck"));
  out.push(chip("Beat the closing line", clv.measured ? `${clv.beat} of ${clv.measured}` : "none measured", "analyze-chip-clv"));
  return out;
}

function topBlock(report) {
  const hot = report.hot_hand || {};
  const ref = hot.referee || {};
  return h("section", { class: "ar-card ar-top", "data-hook": "analyze-top" }, [
    h("p", { class: "ar-eyebrow", text: "Analyze" }),
    h("h2", { class: "ar-headline", "data-hook": "analyze-headline", text: clean(report.headline) }),
    h("div", { class: "ar-hot" }, [
      gauge(hot),
      h("div", { class: "ar-hot__side" }, [
        h("p", { class: "ar-verdict", "data-hook": "analyze-verdict", "data-verdict": clean(hot.verdict), text: clean(hot.verdict_label) }),
        h("p", { class: "ar-hot__text", "data-hook": "analyze-hot-text", text: clean(hot.text) }),
        hot.run_text ? h("p", { class: "ar-run", "data-hook": "analyze-run", text: clean(hot.run_text) }) : null,
      ]),
    ]),
    h("ul", { class: "ar-chips", "data-hook": "analyze-chips" }, chips(hot)),
    ref.needs ? h("p", { class: "ar-fine", "data-hook": "analyze-referee", text: `The referee calls a record real or lucky from ${ref.needs} bets with a measurable closing price. ${clean(report.not_forecast)}` }) : null,
  ]);
}

// ---- drivers --------------------------------------------------------------------------------------------------------------

function driverItem(d) {
  return h("li", { class: "ar-driver", "data-hook": "analyze-driver", "data-level": clean(d.level) }, [
    h("div", { class: "ar-driver__main" }, [
      h("span", { class: "ar-driver__name", text: clean(d.name) }),
      h("span", { class: "ar-driver__rec", text: `${clean(d.record)}, ${unitsText(d.units)}` }),
    ]),
    h("span", { class: "ar-badge", "data-hook": "analyze-sample", text: `${plural(d.n, "bet", "bets")} · ${clean(d.level_text)}` }),
  ]);
}

function driverList(title, items, hook, empty) {
  return h("div", { class: "ar-drivers__col", "data-hook": hook }, [
    h("h4", { class: "ar-drivers__h", text: title }),
    items.length ? h("ul", { class: "ar-drivers__list" }, items.map(driverItem)) : h("p", { class: "ar-muted", "data-hook": `${hook}-none`, text: empty }),
  ]);
}

export function driversBlock(drivers) {
  return h("section", { class: "ar-card", "data-hook": "analyze-drivers" }, [
    h("h3", { class: "ar-h", text: "What is driving it" }),
    h("div", { class: "ar-drivers" }, [
      driverList("Working", drivers.winning || [], "analyze-winning", "No slice of bets stands out yet."),
      driverList("Not working", drivers.losing || [], "analyze-losing", "No slice of bets is clearly losing."),
    ]),
    h("p", { class: "ar-fine", "data-hook": "analyze-drivers-note", text: clean(drivers.note) }),
  ]);
}

// ---- picks ----------------------------------------------------------------------------------------------------------------

let metersPromise = null;

/** The sibling meters module, or null when it does not exist (a missing file is not an error, it is the text chips). */
export function loadMeters() {
  if (!metersPromise) {
    metersPromise = (async () => {
      try {
        const mod = await import(METERS_MODULE);
        return mod && typeof mod.renderPickMeters === "function" ? mod : null;
      } catch (err) {
        return null;
      }
    })();
  }
  return metersPromise;
}

export function resetMeters() {
  metersPromise = null;
}

const scoreOf = (g) => (g && isNum(g.score) ? Math.round(g.score) : null);

/** "C 60 · V 71" from the grades, or "" when there are none to show. */
export function gradeText(grades) {
  if (!grades || typeof grades !== "object") return "";
  const parts = [["C", scoreOf(grades.confidence)], ["V", scoreOf(grades.value)]].filter(([, n]) => n !== null).map(([k, n]) => `${k} ${n}`);
  return parts.join(" · ");
}

function gradeNode(grades, meters) {
  if (!grades) return null;
  if (meters) {
    try {
      const node = meters.renderPickMeters(grades, { compact: true });
      if (node) return h("div", { class: "ar-pick__meters", "data-hook": "analyze-meters" }, [node]);
    } catch (err) { /* fall through to the text chips */ }
  }
  const text = gradeText(grades);
  return text ? h("span", { class: "ar-grade", "data-hook": "analyze-grade", text }) : null;
}

const RESULT_WORD = { win: "Won", loss: "Lost", push: "Push", open: "Open" };

function priceText(p) {
  const n = p.price_average !== null && p.price_average !== undefined ? p.price_average : p.price;
  return isNum(n) ? (n > 0 ? `+${n}` : String(n)) : "";
}

export function pickRow(p, meters) {
  const clv = p.clv && isNum(p.clv.pts) ? p.clv : null;
  const sel = clean(p.selection);
  const extra = p.line && !sel.includes(String(p.line)) ? clean(String(p.line)) : "";     // a spread's selection already says its line
  const line = [sel, extra, priceText(p)].filter(Boolean).join(" ");
  return h("li", { class: "ar-pick", "data-hook": "analyze-pick", "data-result": clean(p.result) }, [
    h("div", { class: "ar-pick__top" }, [
      h("span", { class: "ar-pick__result", "data-result": clean(p.result), text: RESULT_WORD[p.result] || clean(p.result) }),
      h("span", { class: "ar-pick__sel", text: line }),
      isNum(p.units) ? h("span", { class: "ar-pick__units", text: unitsText(p.units) }) : null,
    ]),
    h("div", { class: "ar-pick__sub" }, [
      h("span", { class: "ar-pick__game", text: [clean(p.game), clean(p.date)].filter(Boolean).join(" · ") }),
      clv ? h("span", { class: "ar-clv", "data-beat": clv.beat ? "1" : "0", "data-hook": "analyze-clv", text: `${clv.pts > 0 ? "+" : ""}${clv.pts.toFixed(2)} vs close` }) : null,
      gradeNode(p.grades, meters),
    ]),
    p.reason ? h("p", { class: "ar-pick__reason", text: clean(p.reason) }) : null,
    p.hindsight ? h("p", { class: "ar-hind", "data-hook": "analyze-hindsight" }, [
      h("b", { class: "ar-hind__k", text: `${clean(p.hindsight.label) || "Hindsight review"}: ` }), clean(p.hindsight.text),
      p.hindsight.luck ? ` (${clean(p.hindsight.luck)})` : ""]) : null,
  ]);
}

export const PICKS_SHOWN = 12;           // a phone shows this many tickets, then a button for the rest

export function picksBlock(report, meters) {
  const picks = report.picks || [];
  const more = isNum(report.picks_more) ? report.picks_more : 0;
  const rows = picks.map((p, i) => {
    const row = pickRow(p, meters);
    if (i >= PICKS_SHOWN) row.setAttribute("hidden", "");
    return row;
  });
  const list = rows.length ? h("ol", { class: "ar-picks", "data-hook": "analyze-picks-list" }, rows) : null;
  let toggle = null;
  if (rows.length > PICKS_SHOWN) {
    toggle = h("button", { type: "button", class: "btn btn--ghost ar-picks__more", "data-hook": "analyze-picks-more", "aria-expanded": "false",
      text: `Show all ${rows.length} tickets` });
    toggle.addEventListener("click", () => {
      for (const row of rows) row.removeAttribute("hidden");
      if (toggle.parentNode) toggle.parentNode.removeChild(toggle);
    });
  }
  return h("section", { class: "ar-card", "data-hook": "analyze-picks" }, [
    h("h3", { class: "ar-h", text: "What it is picking" }),
    list || h("p", { class: "ar-muted", "data-hook": "analyze-picks-none", text: "No tickets yet. The first one shows up here the moment the hound makes it." }),
    toggle,
    more ? h("p", { class: "ar-fine", text: `${plural(more, "older ticket", "older tickets")} not shown.` }) : null,
    report.hindsight_note ? h("p", { class: "ar-fine", "data-hook": "analyze-hindsight-note", text: clean(report.hindsight_note) }) : null,
  ]);
}

// ---- keep it up, expand, coach --------------------------------------------------------------------------------------------

export function keepBlock(keep) {
  return h("section", { class: "ar-card", "data-hook": "analyze-keep" }, [
    h("h3", { class: "ar-h", text: clean(keep.headline) || "The case for changing nothing" }),
    h("p", { class: "ar-keep__text", text: clean(keep.text) }),
    (keep.points || []).length ? h("ul", { class: "ar-points" }, keep.points.map((t) => h("li", { text: clean(t) }))) : null,
  ]);
}

export function sendExpand(node, dogId, item) {
  const detail = { dogId, id: item.id };
  if (item.href) detail.href = item.href;
  const evt = new CustomEvent(EXPAND_EVENT, { detail, bubbles: true, composed: true });
  return node.dispatchEvent(evt);
}

export function expandItem(item, dogId) {
  const spin = item.id === "spin_off";
  const button = h("button", { type: "button", class: "btn btn--ghost ar-expand__go", "data-hook": "analyze-expand-go", "data-id": clean(item.id),
    text: spin ? "Start a copy" : "Review this change" });
  button.addEventListener("click", () => sendExpand(button, dogId, item));
  return h("li", { class: "ar-expand", "data-hook": "analyze-expand", "data-id": clean(item.id) }, [
    h("p", { class: "ar-expand__text", text: clean(item.text) }),
    item.because ? h("p", { class: "ar-expand__because", text: clean(item.because) }) : null,
    item.today_text ? h("p", { class: "ar-expand__today", "data-hook": "analyze-today", text: clean(item.today_text) }) : null,
    h("p", { class: "ar-fine", text: clean(item.how) }),
    button,
  ]);
}

export function expandBlock(expand, dogId) {
  const items = expand.items || [];
  return h("section", { class: "ar-card", "data-hook": "analyze-expand-block" }, [
    h("h3", { class: "ar-h", text: "Find more of the same" }),
    expand.intro ? h("p", { class: "ar-muted", text: clean(expand.intro) }) : null,
    items.length ? h("ul", { class: "ar-expands" }, items.map((i) => expandItem(i, dogId))) : h("p", { class: "ar-muted", "data-hook": "analyze-expand-none", text: "Nothing in the record backs a wider rule yet." }),
    expand.note ? h("p", { class: "ar-fine", text: clean(expand.note) }) : null,
  ]);
}

export function coachBlock(coach) {
  return h("section", { class: "ar-card ar-coach", "data-hook": "analyze-coach", "data-source": clean(coach.source) }, [
    h("p", { class: "ar-coach__label", "data-hook": "analyze-coach-label", text: COACH_LABEL }),
    h("p", { class: "ar-coach__text", "data-hook": "analyze-coach-text", text: clean(coach.text) }),
  ]);
}

// ---- the teaser -----------------------------------------------------------------------------------------------------------

/** ONE panel for everything the teaser leaves out: what is inside, the server's upgrade line, and (for the owner only) the way to the plan. */
export function lockedPanel(report) {
  const locked = Array.isArray(report.locked) ? report.locked : [];
  const upgrade = report.upgrade || {};
  const owner = !!(report.viewer && report.viewer.is_owner);
  return h("section", { class: "ar-card ar-locked", "data-hook": "analyze-locked" }, [
    h("h3", { class: "ar-h", text: "Inside the full report" }),
    h("ul", { class: "ar-points", "data-hook": "analyze-locked-list" }, locked.filter((k) => LOCKED_WORDS[k]).map((k) => h("li", { "data-key": k, text: LOCKED_WORDS[k] }))),
    upgrade.line ? h("p", { class: "ar-muted", "data-hook": "analyze-upgrade-line", text: clean(upgrade.line) }) : null,
    owner ? h("a", { class: "btn btn--primary", href: UPGRADE_HREF, "data-hook": "analyze-upgrade", text: UPGRADE_LABEL }) : null,
  ]);
}

// ---- states ---------------------------------------------------------------------------------------------------------------

export function loadingBlock() {
  return h("div", { class: "ar-loading", role: "status", "aria-busy": "true", "data-hook": "analyze-loading" }, [
    h("p", { class: "ar-muted", text: "Reading the record..." }),
    h("div", { class: "ar-skel" }), h("div", { class: "ar-skel ar-skel--short" }),
  ]);
}

export function errorLine(err) {
  const detail = err && err.detail;
  if (detail && typeof detail === "object" && typeof detail.message === "string" && detail.message) return detail.message;
  if (err && err.status === 503) return "The record is still being worked out. Try again in a few seconds.";
  if (err && err.status === 404) return "That hound could not be found.";
  if (err && (err.status === null || err.status === undefined)) return "Could not reach the server. Try again in a minute.";
  return "The report could not be built just now. Try again in a minute.";
}

function errorBlock(err, retry) {
  const button = h("button", { type: "button", class: "btn btn--ghost", "data-hook": "analyze-retry", text: "Try again" });
  button.addEventListener("click", retry);
  return h("div", { class: "ar-error", role: "alert", "data-hook": "analyze-error" }, [h("p", { text: errorLine(err) }), button]);
}

// ---- the report -----------------------------------------------------------------------------------------------------------

export function renderReport(report, { dogId, meters = null } = {}) {
  const full = report.tier === "full";
  const root = h("section", { class: "ar", "data-hook": "analyze-report", "data-tier": full ? "full" : "teaser", "data-dog": dogId || "" });
  root.appendChild(topBlock(report));
  if (full && report.drivers) root.appendChild(driversBlock(report.drivers));
  root.appendChild(picksBlock(report, meters));
  if (full && report.keep_it_up) root.appendChild(keepBlock(report.keep_it_up));
  if (full && report.expand) root.appendChild(expandBlock(report.expand, dogId));
  if (full && report.coach_read) root.appendChild(coachBlock(report.coach_read));
  if (!full) root.appendChild(lockedPanel(report));
  return root;
}

/**
 * Draw the report for `dogId` into `container`. Resolves { ok: true, tier } once drawn, { ok: false } when the request failed (the
 * container then holds the error and a retry). `apiGet` is injectable (the page's own, a test's).
 */
export async function mountAnalyze(container, { dogId, apiGet = defaultGet } = {}) {
  if (!container) return { ok: false };
  ensureStyles();
  const path = `/hounds/${encodeURIComponent(dogId)}/report`;
  const run = async () => {
    clearNode(container);
    container.appendChild(loadingBlock());
    let report;
    try {
      report = await apiGet(path);
    } catch (err) {
      clearNode(container);
      container.appendChild(errorBlock(err, run));
      return { ok: false };
    }
    const meters = await loadMeters();
    clearNode(container);
    container.appendChild(renderReport(report || {}, { dogId, meters }));
    return { ok: true, tier: report && report.tier };
  };
  return run();
}

/** Mount into the studio Overview tab's container, when the page has one. Returns the mount's promise, or null when there is no place. */
export function mountAnalyzeIfPresent(root, dogId, opts = {}) {
  try {
    const scope = root || (typeof document !== "undefined" ? document : null);
    const host = scope && scope.querySelector ? scope.querySelector(`[data-hook="${HOST_HOOK}"]`) : null;
    return host && dogId ? mountAnalyze(host, Object.assign({ dogId }, opts)) : null;
  } catch (err) {
    return null;
  }
}
