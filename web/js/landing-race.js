/**
 * The landing page's hero visual: the top models RACING on their paper bankroll.
 *
 * Every line is a real model's account, taken from the same public GET /hounds payload the board beside it reads (no extra
 * route): `spark` is the model's cumulative result by day, `bankroll` is its account now. A model starts at the shared $1,000
 * start line and its line ends at its balance today. The dog at the end of each line is the character rig (dog-rig.js): the
 * pose it wears (happy after a streak of wins, sad after a streak of losses) is restated from the model's own `form`, never
 * invented. The intro draws the lines and runs the dogs up them once; "Replay" runs it again. With reduced motion the finished
 * picture is drawn at once and there is no replay.
 *
 * HONESTY. The picture says what it is: a handful of games. It names each model's bet count beside its balance, says how old the
 * season is, and, while every racer has fewer than 30 bets, says in a sentence that a few bets say little. A line never implies
 * a model is good: it is where a paper account is, nothing more. If the payload has no `spark` for a model, its line is the straight
 * run from the $1,000 start to its balance (and says nothing more than that).
 *
 * `raceSeries` and `layoutRace` are pure, so they are tested without a DOM; `renderRace` builds the SVG with createElementNS only.
 */

import { s, h, clearNode, isNum } from "./hounds-core.js";
import { dogFace, poseOfHound } from "./dog-avatar.js";
import { bankrollNow, returnPctOf, fmtUsd, fmtPct, betsOf } from "./hounds-board.js";
import { seasonAgeText } from "./hounds-season.js";

export const RACE_COLORS = ["#2FD07A", "#8FB8FF", "#E0B24A", "#C79BFF", "#F28ABF"];
export const START_USD = 1000;
export const THIN_SAMPLE_BETS = 30;

const reduced = () => {
  try { return !!(window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches); } catch (err) { return false; }
};

/** A model's bankroll by day, in dollars: [start, ..., now]. Null when the payload has no balance for it. */
export function raceSeries(hound) {
  const now = bankrollNow(hound);
  if (!isNum(now)) return null;
  const b = (hound && hound.bankroll) || {};
  const start = isNum(b.start) ? b.start : START_USD;
  const spark = Array.isArray(hound.spark) ? hound.spark.filter(isNum) : [];
  if (spark.length < 2) return [start, now];
  const last = spark[spark.length - 1];
  const scale = Math.abs(last) > 1e-9 ? (now - start) / last : (isNum(b.unit_usd) ? b.unit_usd : 10);
  const out = spark.map((u) => start + u * scale);
  out[out.length - 1] = now;
  return out;
}

/** The y ticks and domain for a set of series: always includes the $1,000 line, padded, ticks on a round step. */
export function yScale(all, start = START_USD) {
  const flat = all.flat().concat([start]);
  let lo = Math.min(...flat), hi = Math.max(...flat);
  const span = Math.max(hi - lo, 6);
  const step = span <= 12 ? 5 : span <= 30 ? 10 : span <= 80 ? 20 : span <= 200 ? 50 : 100;
  lo = Math.floor((lo - span * 0.12) / step) * step;
  hi = Math.ceil((hi + span * 0.12) / step) * step;
  const ticks = [];
  for (let v = lo; v <= hi + 1e-9; v += step) ticks.push(v);
  return { lo, hi, ticks };
}

/** Spread label y positions so two labels never overlap: `ys` sorted by value, `gap` pixels apart, kept in [min, max]. */
export function spreadLabels(ys, gap, min, max) {
  const order = ys.map((y, i) => ({ y, i })).sort((a, b) => a.y - b.y);
  for (let k = 1; k < order.length; k++) if (order[k].y - order[k - 1].y < gap) order[k].y = order[k - 1].y + gap;
  const over = order.length ? order[order.length - 1].y - max : 0;
  if (over > 0) for (const o of order) o.y -= over;
  for (let k = 0; k < order.length; k++) if (order[k].y < min) order[k].y = min + k * gap;
  const out = new Array(ys.length);
  for (const o of order) out[o.i] = o.y;
  return out;
}

/** The geometry of the chart for a width: plot box, scales and each racer's polyline in pixels. Pure. */
export function layoutRace(racers, width) {
  const wide = width >= 520;
  const W = Math.max(280, Math.min(width, 760));
  const H = wide ? 340 : 270;
  const m = { l: 52, r: wide ? 178 : 48, t: 22, b: 30 };
  const series = racers.map((r) => r.series);
  const sc = yScale(series);
  const n = Math.max(2, ...series.map((x) => x.length));
  const x = (i, len) => m.l + ((W - m.l - m.r) * i) / Math.max(1, len - 1);
  const y = (v) => m.t + (H - m.t - m.b) * (1 - (v - sc.lo) / (sc.hi - sc.lo));
  const lines = racers.map((r, k) => ({
    id: r.id, name: r.name, color: RACE_COLORS[k % RACE_COLORS.length], leader: k === 0,
    points: r.series.map((v, i) => ({ x: x(i, r.series.length), y: y(v), v })),
  }));
  // the dogs finish in a column at the right, spread so no two overlap; a thin link joins each to the end of its line
  const face = wide ? 34 : 28;
  const slotYs = spreadLabels(lines.map((l) => l.points[l.points.length - 1].y), face + 8, m.t + face / 2, H - m.b - face / 2);
  const slotX = W - m.r + 12;
  lines.forEach((l, i) => { l.labelY = slotYs[i]; l.slot = { x: slotX, y: slotYs[i] }; });
  return { W, H, m, wide, face, sc, n, y, x, lines, slotX, baseY: y(START_USD) };
}

const num = (v) => Math.round(v * 10) / 10;
const pathOf = (pts) => pts.map((p, i) => `${i ? "L" : "M"}${num(p.x)} ${num(p.y)}`).join(" ");

/** The polyline cut at fraction t (0..1) of its length by points, so the line "runs". Returns { d, tip }. */
export function partial(points, t) {
  if (points.length === 1) return { d: pathOf(points), tip: points[0] };
  const seg = (points.length - 1) * Math.min(1, Math.max(0, t));
  const whole = Math.floor(seg);
  const cut = points.slice(0, whole + 1);
  let tip = points[whole];
  if (whole < points.length - 1) {
    const a = points[whole], b = points[whole + 1], f = seg - whole;
    tip = { x: a.x + (b.x - a.x) * f, y: a.y + (b.y - a.y) * f, v: a.v + (b.v - a.v) * f };
    cut.push(tip);
  }
  return { d: pathOf(cut), tip };
}

const ease = (t) => 1 - Math.pow(1 - Math.min(1, Math.max(0, t)), 3);

/** The text a screen reader gets for the whole picture. */
export function raceLabel(racers) {
  return `Paper bankroll by model, each starting at $${START_USD.toLocaleString("en-US")}: ${racers.map((r) => `${r.name} ${fmtUsd(r.now)} on ${r.bets} ${r.bets === 1 ? "bet" : "bets"}`).join("; ")}.`;
}

/**
 * Draw the race into `host` (the [data-hook='lb-race'] node). `models` is the board's selection (the top models in rank order);
 * `meta` is the payload's season block; `today` is a YYYY-MM-DD for the age line (tests pass one).
 */
export function renderRace(host, models, meta, today, opts = {}) {
  if (!host) return null;
  const sub = host.querySelector("[data-hook='lb-race-sub']");
  const chart = host.querySelector("[data-hook='lb-race-chart']");
  const legend = host.querySelector("[data-hook='lb-race-legend']");
  const note = host.querySelector("[data-hook='lb-race-note']");
  const replay = host.querySelector("[data-hook='lb-race-replay']");
  const racers = (models || []).map((m) => ({ id: m.id, name: m.name || "Model", series: raceSeries(m), now: bankrollNow(m), ret: returnPctOf(m), bets: betsOf(m), hound: m }))
    .filter((r) => r.series).slice(0, 5);
  if (!chart) return null;
  clearNode(chart);
  if (legend) clearNode(legend);
  if (!racers.length) {
    host.setAttribute("data-state", "empty");
    if (sub) sub.textContent = "No model has a settled bet in this season yet. The race starts after the next slate.";
    if (note) note.textContent = "";
    if (replay) replay.setAttribute("hidden", "");
    return null;
  }
  host.setAttribute("data-state", "ready");
  const age = seasonAgeText(meta, today);
  const thin = Math.max(...racers.map((r) => r.bets)) < THIN_SAMPLE_BETS;
  if (sub) sub.textContent = `Paper bankroll, every model starts at $${START_USD.toLocaleString("en-US")}.${age ? ` ${age}.` : ""}`;
  if (note) {
    note.textContent = thin
      ? "A handful of games: a few bets say little about what comes next. Lines show where each paper account is, nothing more."
      : "Lines show where each paper account is, nothing more.";
  }
  const width = (chart.getBoundingClientRect && chart.getBoundingClientRect().width) || (host.getBoundingClientRect && host.getBoundingClientRect().width) || 640;
  const geo = layoutRace(racers, width);
  host.setAttribute("data-layout", geo.wide ? "wide" : "narrow");
  const { W, H, m } = geo;
  const face = geo.face;

  const svg = s("svg", { class: "lbrace__svg", viewBox: `0 0 ${W} ${H}`, width: "100%", role: "img", "aria-label": raceLabel(racers), focusable: "false" });
  for (const v of geo.sc.ticks) {
    const yy = num(geo.y(v));
    svg.appendChild(s("line", { x1: m.l, x2: W - m.r, y1: yy, y2: yy, class: "lbrace__grid" }));
    svg.appendChild(s("text", { x: m.l - 10, y: yy + 4, "text-anchor": "end", class: "lbrace__tick", text: fmtUsd(v) }));
  }
  const by = num(geo.baseY);
  svg.appendChild(s("line", { x1: m.l, x2: W - m.r, y1: by, y2: by, class: "lbrace__base" }));
  svg.appendChild(s("text", { x: m.l + 2, y: by + 15, class: "lbrace__start", text: "$1,000 start" }));
  svg.appendChild(s("text", { x: m.l, y: H - 8, class: "lbrace__tick", text: "Season start" }));
  svg.appendChild(s("text", { x: W - m.r, y: H - 8, "text-anchor": "end", class: "lbrace__tick", text: "Latest" }));

  const parts = geo.lines.map((line, k) => {
    const r = racers[k];
    const path = s("path", { class: `lbrace__line${line.leader ? " lbrace__line--lead" : ""}`, d: pathOf(line.points.slice(0, 1)), stroke: line.color, fill: "none", "data-id": line.id });
    const ring = s("rect", { class: "lbrace__ring", x: -2, y: -2, width: face + 4, height: face + 4, rx: Math.round(face * 0.28), fill: "none", stroke: line.color, "stroke-width": 2 });
    const dog = dogFace(r.hound, { size: face, pose: "idle" });
    dog.setAttribute("x", 0); dog.setAttribute("y", 0);
    const dogG = s("g", { class: "lbrace__dog", "data-id": line.id }, [ring, dog]);
    const last = line.points[line.points.length - 1];
    const label = geo.wide ? s("g", { class: "lbrace__label", opacity: 0 }, [
      s("text", { x: 0, y: -3, class: "lbrace__name", text: r.name.length > 20 ? `${r.name.slice(0, 19)}.` : r.name }),
      s("text", { x: 0, y: 13, class: "lbrace__val", text: `${fmtUsd(r.now)} · ${r.bets} ${r.bets === 1 ? "bet" : "bets"}` })]) : null;
    const link = s("path", { class: "lbrace__link", d: "M0 0", stroke: line.color, fill: "none", opacity: 0 });
    svg.appendChild(link);
    svg.appendChild(path);
    return { line, r, path, link, dogG, dog, label, last };
  });
  // dogs and labels sit above all lines
  for (const p of parts) svg.appendChild(p.dogG);
  for (const p of parts) if (p.label) svg.appendChild(p.label);
  chart.appendChild(svg);

  if (legend) {
    for (const p of parts) {
      legend.appendChild(h("li", { class: "lbrace__item", "data-id": p.line.id, style: `--c:${p.line.color}` }, [
        h("span", { class: "lbrace__swatch", "aria-hidden": "true" }),
        h("a", { class: "lbrace__itemname", href: `hound.html?id=${encodeURIComponent(p.line.id)}`, text: p.r.name }),
        h("span", { class: "lbrace__itemval", text: `${fmtUsd(p.r.now)} (${fmtPct(p.r.ret)})` }),
        h("span", { class: "lbrace__itembets", text: `${p.r.bets} ${p.r.bets === 1 ? "bet" : "bets"}` })]));
    }
  }

  // ---- the run ------------------------------------------------------------------------------------------------
  // t runs 0..1: the first 78% the lines draw and the dogs run up them, the rest each dog settles into its finish slot
  const place = (p, t) => {
    const a = ease(Math.min(1, t / 0.78));
    const u = ease(Math.max(0, (t - 0.78) / 0.22));
    const cut = partial(p.line.points, a);
    const end = p.line.points[p.line.points.length - 1];
    const slot = p.line.slot;
    const cx = cut.tip.x + (slot.x + face / 2 - cut.tip.x) * u;
    const cy = cut.tip.y + (slot.y - cut.tip.y) * u;
    p.path.setAttribute("d", cut.d);
    p.dogG.setAttribute("transform", `translate(${num(cx - face / 2)} ${num(cy - face / 2)})`);
    if (u > 0) {
      p.link.setAttribute("d", `M${num(end.x)} ${num(end.y)} C${num(end.x + 24)} ${num(end.y)} ${num(slot.x - 14)} ${num(slot.y)} ${num(slot.x)} ${num(slot.y)}`);
      p.link.setAttribute("opacity", num(u * 0.7));
    } else p.link.setAttribute("opacity", 0);
  };
  const finish = () => {
    parts.forEach((p) => {
      place(p, 1);
      if (p.label) {
        p.label.setAttribute("transform", `translate(${num(p.line.slot.x + face + 10)} ${num(p.line.slot.y - 1)})`);
        p.label.setAttribute("opacity", 1);
      }
      p.dog.setAttribute("data-pose", poseOfHound(p.r.hound));
      p.dog.setAttribute("data-mood", poseOfHound(p.r.hound));
    });
    host.setAttribute("data-run", "done");
  };
  const run = () => {
    if (reduced() || typeof requestAnimationFrame !== "function") { finish(); if (replay) replay.setAttribute("hidden", ""); return; }
    host.setAttribute("data-run", "running");
    if (replay) replay.setAttribute("hidden", "");
    parts.forEach((p) => { if (p.label) p.label.setAttribute("opacity", 0); p.dog.setAttribute("data-pose", "idle"); place(p, 0); });
    const t0 = (typeof performance !== "undefined" ? performance.now() : 0);
    const total = 1500;
    const step = (now) => {
      const el = now - t0;
      parts.forEach((p, k) => place(p, (el - k * 110) / (total - 300)));
      if (el < total + parts.length * 110) requestAnimationFrame(step);
      else { finish(); if (replay) replay.removeAttribute("hidden"); }
    };
    requestAnimationFrame(step);
  };
  if (replay && replay.getAttribute("data-bound") !== "1") {
    replay.setAttribute("data-bound", "1");
    replay.addEventListener("click", () => run());
  }
  host.__lbRaceRun = run;
  if (opts.animate === false) { finish(); if (replay && !reduced()) replay.removeAttribute("hidden"); } else run();
  return { racers, geo };
}
