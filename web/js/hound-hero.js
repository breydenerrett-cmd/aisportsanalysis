/**
 * The hero's live look at the hound's capital (owner request 2026-10-21): the paper bankroll at the viewer's sizing, a small
 * sparkline of the balance after each slate day, and the change over the last 24 hours. PURE helpers plus one DOM builder; every
 * number is one the server sent (the series and the bankroll block), read in the viewer's dollars by web/js/unitsize.js. With fewer
 * than two points there is nothing to draw and the line says so rather than drawing a shape.
 */

import { h, s, isNum } from "./hounds-core.js";

export const SPARK_W = 120;
export const SPARK_H = 36;

/** "x,y x,y ..." for a polyline of `values` scaled into a w x h box (a flat series sits mid-height). Empty under two values. */
export function sparkPoints(values, w = SPARK_W, hgt = SPARK_H, pad = 3) {
  const v = (values || []).filter(isNum);
  if (v.length < 2) return "";
  const lo = Math.min(...v);
  const hi = Math.max(...v);
  const span = hi - lo;
  const step = (w - pad * 2) / (v.length - 1);
  return v.map((n, i) => {
    const y = span === 0 ? hgt / 2 : pad + (1 - (n - lo) / span) * (hgt - pad * 2);
    return `${(pad + i * step).toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");
}

/** The sparkline as an inline SVG (no script, no library). `tone` is "up" | "down" | "flat" and only picks the colour class. */
export function sparkline(values, tone = "flat") {
  const pts = sparkPoints(values);
  const svg = s("svg", { class: `hh-spark hh-spark--${tone}`, viewBox: `0 0 ${SPARK_W} ${SPARK_H}`, width: String(SPARK_W), height: String(SPARK_H),
    role: "img", "aria-label": pts ? "The balance after each day it has bet" : "No graded days to draw yet", "data-hook": "hound-spark", preserveAspectRatio: "none" });
  if (pts) svg.appendChild(s("polyline", { points: pts, fill: "none", stroke: "currentColor", "stroke-width": "2", "stroke-linejoin": "round", "stroke-linecap": "round", "vector-effect": "non-scaling-stroke" }));
  else svg.appendChild(s("line", { x1: "3", y1: String(SPARK_H / 2), x2: String(SPARK_W - 3), y2: String(SPARK_H / 2), stroke: "currentColor", "stroke-width": "2", "stroke-dasharray": "3 4", "stroke-linecap": "round", opacity: ".45" }));
  return svg;
}

/**
 * The change line. `change` = { pnl, bets } for the last 24 hours in the viewer's terms (pnl in dollars, or null), `money` formats a
 * signed dollar figure. Returns { text, tone }. A window with no settled bet says so; it is not "+$0".
 */
export function changeLine(change, money) {
  if (!change || !isNum(change.bets) || change.bets <= 0 || !isNum(change.pnl)) return { text: "Nothing settled in the last 24 hours", tone: "flat" };
  const tone = change.pnl > 0 ? "up" : change.pnl < 0 ? "down" : "flat";
  return { text: `${money(change.pnl)} in the last 24 hours`, tone };
}

/** The block under the hero's facts: sparkline plus the change line. */
export function capitalBlock(values, change, money) {
  const line = changeLine(change, money);
  return h("div", { class: `hh-capital hh-capital--${line.tone}`, "data-hook": "hound-capital", "data-tone": line.tone }, [
    sparkline(values, line.tone),
    h("span", { class: "hh-capital__change", "data-hook": "hound-change", text: line.text }),
  ]);
}
