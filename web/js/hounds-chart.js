/**
 * Inline-SVG charts for the Hounds pages. No library, no network, no timers.
 *
 *   renderLineChart(opts)  a multi-line chart with a zero baseline, a hover/keyboard tooltip and a
 *                          visually hidden data table that says the same thing in words and numbers.
 *   renderSparkline(opts)  the small line on a leaderboard row.
 *
 * MOTION. The only motion is a one-time CSS draw-in (web/css/hounds.css, `.hd-line`), which a browser
 * does not run for a page nobody is looking at, and which is switched off for prefers-reduced-motion.
 * Nothing here uses requestAnimationFrame or a timer, so nothing keeps running in a hidden tab.
 *
 * The geometry (scales, ticks, the zero line, one-point and empty series) is layoutChart in
 * hounds-core.js, which is plain functions and is what the tests pin.
 */

import {
  h, s, clearNode, layoutChart, layoutSparkline, nearestDay, valuesAtDay, shortDate, signed, isNum,
} from "./hounds-core.js";

function fmtValue(v, unit) {
  return unit === "pts" ? `${signed(v, 2)} pts` : `${signed(v, 2)}u`;
}

/** The hidden table: one row per date, one column per line. Same numbers as the picture. */
export function dataTable(layout, { caption, unit }) {
  const head = h("tr", {}, [h("th", { scope: "col", text: "Date" }),
    ...layout.lines.map((l) => h("th", { scope: "col", text: `${l.name} (${unit === "pts" ? "points" : "units"})` }))]);
  const rows = layout.days.map((day) => {
    const cells = layout.lines.map((l) => {
      const hit = l.points.find((p) => p.day === day);
      return h("td", { text: hit ? fmtValue(hit.value, unit) + (isNum(hit.bets) ? `, ${hit.bets} settled` : "") : "-" });
    });
    return h("tr", {}, [h("th", { scope: "row", text: shortDate(day) }), ...cells]);
  });
  return h("table", { class: "hd-sr-only", "data-hook": "chart-data-table" }, [
    h("caption", { text: caption }), h("thead", {}, [head]), h("tbody", {}, rows)]);
}

/**
 * opts: { series:[{id,name,color,points:[{date,value,bets}]}], width, height, unit:"units"|"pts",
 *         label, zeroLabel, emptyText, dashes }
 * Returns a <figure>. An empty series set draws an honest empty frame and says so in words.
 */
export function renderLineChart(opts) {
  const unit = opts.unit || "units";
  const width = opts.width || 640;
  const height = opts.height || 280;
  const layout = layoutChart(opts.series || [], { width, height });
  const figure = h("figure", { class: "hd-chart", "data-hook": opts.hook || "chart" });
  const tip = h("div", { class: "hd-tip", hidden: true, "aria-hidden": "true", "data-hook": "chart-tooltip" });

  const svg = s("svg", { class: "hd-chart__svg", viewBox: `0 0 ${width} ${height}`, role: "img",
    "aria-label": opts.label, focusable: "false" });

  if (layout.empty) {
    svg.appendChild(s("rect", { x: 0.5, y: 0.5, width: width - 1, height: height - 1, class: "hd-chart__frame" }));
    svg.appendChild(s("text", { x: width / 2, y: height / 2, "text-anchor": "middle", class: "hd-chart__empty",
      text: opts.emptyText || "No settled bets to draw yet." }));
    figure.appendChild(svg);
    figure.appendChild(h("p", { class: "hd-chart__empty-note", "data-hook": "chart-empty",
      text: opts.emptyText || "No settled bets to draw yet." }));
    figure.setAttribute("data-empty", "true");
    return figure;
  }

  // grid + y labels
  for (const t of layout.yTicks) {
    svg.appendChild(s("line", { x1: layout.plot.x0, x2: layout.plot.x1, y1: t.y, y2: t.y, class: "hd-chart__grid" }));
    svg.appendChild(s("text", { x: layout.plot.x0 - 6, y: t.y + 4, "text-anchor": "end", class: "hd-chart__tick",
      text: t.label }));
  }
  layout.xTicks.forEach((t, i) => {
    // the first and last labels hang inward so they are never clipped by the frame
    const anchor = layout.xTicks.length > 1 && i === 0 ? "start"
      : layout.xTicks.length > 1 && i === layout.xTicks.length - 1 ? "end" : "middle";
    svg.appendChild(s("text", { x: t.x, y: layout.height - 6, "text-anchor": anchor, class: "hd-chart__tick",
      text: t.label }));
  });
  // the zero baseline, drawn over the grid and under the lines
  svg.appendChild(s("line", { x1: layout.plot.x0, x2: layout.plot.x1, y1: layout.zeroY, y2: layout.zeroY,
    class: "hd-chart__zero", "data-hook": "chart-zero" }));
  if (opts.zeroLabel) {
    svg.appendChild(s("text", { x: layout.plot.x1, y: layout.zeroY - 4, "text-anchor": "end",
      class: "hd-chart__zero-label", text: opts.zeroLabel }));
  }

  const dashes = opts.dashes || [];
  layout.lines.forEach((line, i) => {
    const g = s("g", { class: "hd-line", "data-line": line.id, style: `--hd-line:${line.color}` });
    if (line.d) {
      g.appendChild(s("path", { d: line.d, fill: "none", stroke: line.color, "stroke-width": 2.25,
        "stroke-linecap": "round", "stroke-linejoin": "round", pathLength: dashes[i] ? undefined : 1,
        "stroke-dasharray": dashes[i] || undefined,
        class: dashes[i] ? "hd-line__path" : "hd-line__path hd-line__path--solid" }));
    }
    // the last point is always marked; a one-point series is only that mark
    const end = line.points[line.points.length - 1];
    if (end) {
      svg.appendChild(g);
      g.appendChild(s("circle", { cx: end.x, cy: end.y, r: line.single ? 4 : 3, fill: line.color,
        class: "hd-line__end", "data-single": line.single ? "true" : undefined }));
    }
  });

  const cross = s("line", { x1: 0, x2: 0, y1: layout.plot.y0, y2: layout.plot.y1, class: "hd-chart__cross",
    visibility: "hidden", "data-hook": "chart-cross" });
  svg.appendChild(cross);
  const dots = s("g", { class: "hd-chart__hover-dots" });
  svg.appendChild(dots);

  figure.appendChild(svg);
  figure.appendChild(tip);
  if (opts.caption) figure.appendChild(h("figcaption", { class: "hd-chart__caption", text: opts.caption }));
  figure.appendChild(dataTable(layout, { caption: opts.label, unit }));

  let day = null;
  function show(d) {
    day = d;
    const x = layout.x(d);
    cross.setAttribute("x1", x);
    cross.setAttribute("x2", x);
    cross.setAttribute("visibility", "visible");
    const rows = valuesAtDay(layout, d);
    clearNode(dots);
    for (const r of rows) {
      const line = layout.lines.find((l) => l.id === r.id);
      const p = line.points.find((q) => q.date === r.date);
      if (p) dots.appendChild(s("circle", { cx: p.x, cy: p.y, r: 4, fill: r.color, class: "hd-chart__hover-dot" }));
    }
    clearNode(tip);
    tip.appendChild(h("p", { class: "hd-tip__date", text: shortDate(d) }));
    for (const r of rows) {
      tip.appendChild(h("p", { class: "hd-tip__row" }, [
        h("span", { class: "hd-tip__swatch", style: `background:${r.color}` }),
        h("span", { class: "hd-tip__name", text: r.name }),
        h("span", { class: "hd-tip__val", text: fmtValue(r.value, unit) }),
        h("span", { class: "hd-tip__bets", text: isNum(r.bets) ? `${r.bets} settled` : "" }),
      ]));
    }
    if (rows.length === 0) tip.appendChild(h("p", { class: "hd-tip__row", text: "No hound had a settled bet by this date." }));
    tip.hidden = false;
    tip.removeAttribute("hidden");
    // keep the tooltip inside the figure: flip to the left half's right side and vice versa
    const frac = (x - layout.plot.x0) / Math.max(1, layout.plot.x1 - layout.plot.x0);
    tip.setAttribute("data-side", frac > 0.55 ? "left" : "right");
    tip.setAttribute("style", `left:${(x / layout.width * 100).toFixed(2)}%`);
  }
  function hide() {
    day = null;
    cross.setAttribute("visibility", "hidden");
    clearNode(dots);
    tip.hidden = true;
    tip.setAttribute("hidden", "");
  }
  const pxOf = (evt) => {
    const box = svg.getBoundingClientRect ? svg.getBoundingClientRect() : { left: 0, width };
    const w = box.width || width;
    return ((evt.clientX - (box.left || 0)) / w) * width;
  };
  svg.addEventListener("pointermove", (evt) => { const d = nearestDay(layout, pxOf(evt)); if (d !== null) show(d); });
  svg.addEventListener("pointerleave", hide);
  // keyboard: the figure is focusable; left/right walk the dates, Escape clears
  figure.setAttribute("tabindex", "0");
  figure.addEventListener("keydown", (evt) => {
    const i = day === null ? -1 : layout.days.indexOf(day);
    if (evt.key === "ArrowRight") { show(layout.days[Math.min(layout.days.length - 1, i + 1)]); evt.preventDefault && evt.preventDefault(); }
    else if (evt.key === "ArrowLeft") { show(layout.days[Math.max(0, i < 0 ? layout.days.length - 1 : i - 1)]); evt.preventDefault && evt.preventDefault(); }
    else if (evt.key === "Escape") hide();
  });
  figure.addEventListener("blur", hide);
  figure.__chart = { layout, show, hide };
  return figure;
}

/** A leaderboard-row sparkline. Under two points it says so in words instead of drawing a flat line. */
export function renderSparkline({ values, color, label, width = 96, height = 28 }) {
  const lay = layoutSparkline(values, { width, height });
  if (lay.empty) {
    return h("span", { class: "hd-spark hd-spark--none", "data-hook": "spark-none", text: "no line yet" });
  }
  const svg = s("svg", { class: "hd-spark", viewBox: `0 0 ${width} ${height}`, width, height, role: "img",
    "aria-label": label || `Units over the last ${lay.n} points, from ${signed(lay.first, 2)} to ${signed(lay.last, 2)}`,
    "data-hook": "spark" });
  svg.appendChild(s("line", { x1: 0, x2: width, y1: lay.zeroY, y2: lay.zeroY, class: "hd-spark__zero" }));
  svg.appendChild(s("path", { d: lay.d, fill: "none", stroke: color, "stroke-width": 1.75, "stroke-linecap": "round",
    "stroke-linejoin": "round" }));
  svg.appendChild(s("circle", { cx: lay.end.x, cy: lay.end.y, r: 2.5, fill: color }));
  return svg;
}
