/**
 * web/hounds.html: the live kennel.
 *
 * WHAT IT SHOWS, TOP TO BOTTOM
 *   - a big LIVE KENNEL header and the paper-only line (static markup);
 *   - the form strip: Hot dog / Ice cold / On tilt, from each dog's last seven days (hounds-voice.js
 *     formStrip; a dog needs 3 bets that week to be named);
 *   - the leaderboard, SORTED BY PAPER UNITS (average price, forward bets): rank, W-L with the bet count
 *     beside it, units, streak flames, this week, and the badge (SHARP / COIN FLIP / FEEDING THE BOOK /
 *     ROOKIE) which is the old verdict label in a bettor's clothes. Tap the badge for one plain line on
 *     what it means. The old "check against the close" is the badge, not the order: a dog can lead the board
 *     and still wear FEEDING THE BOOK, and the page says so right beside it. The receipts (record, price vs
 *     the close, replay) sit in a collapsed block per row;
 *   - "Which dog gets put down next?": the three nearest the 25-units-under line. Static: the rule decides;
 *   - a chart called "Bankroll race (paper units)": cumulative paper units at the AVERAGE price, FORWARD bets
 *     only (that is all GET /hounds/series sends; replay results are never drawn or mixed in);
 *   - the decision stream as a chat feed, each bubble saying who decided: the rule, the code or the model;
 *   - the graveyard as tombstones with epitaphs and the cause;
 *   - the "Build your dog" call to action.
 *
 * EVERY SECTION LOADS ON ITS OWN. A failed or missing endpoint puts an honest sentence in that section
 * (describeError) and leaves the others alone. A server that is still working out the numbers for the
 * first time answers `warming_up: true`; the section says so and asks again (retryWhileWarming). Nothing
 * is invented to fill a gap. The page never claims an edge, never calls units profit, and the "paper bets
 * only, not advice" line is static markup in the HTML so it is there with scripts off.
 */

import { apiGet } from "./api.js";
import {
  h, s, clearNode, filterHounds, splitBaselines, presentCategories, categoryOf, categoryLabel,
  houndColor, verdictGlyph, avatarSvg, vibeOf, fmtRecord, fmtUnits, fmtWhen, signed, isNum,
  houndHref, whoLabel, normalizeSeries, pointsFor, hasForwardData, toChartPoints, sparkValues, segmentView,
  describeError, noticeLine, createPoller, FUN_CATEGORIES, FUN_TAG, REPLAY_NOTE, NO_FORWARD_TEXT, NOT_REPORTED,
  unitsPairText, BEST_PRICE_WORDS, isWarming, retryWhileWarming, stopWarmingRetry, WARMING_FALLBACK_TEXT,
} from "./hounds-core.js";
import {
  badgeFor, sortByUnits, unitsOf, wlText, streakView, weekText, formStrip, closestToRetirement, cushionText,
  causeText, epitaphFor, personaOf, chatLine, STATUS_WORDS, RETIRE_UNITS, houndmasterLine,
} from "./hounds-voice.js";
import { renderLineChart, renderSparkline } from "./hounds-chart.js";
import { followedIds, pinFollowed } from "./hounds-follow.js";

export const STREAM_POLL_MS = 60000;
export const CHART_LABEL = "Paper units, one a bet. Tap a name to hide a dog.";
export const FORWARD_TITLE = "Live bets only: placed after each dog's rule was written. No backfilling.";
export const NO_FORWARD_CHART_TEXT =
  "No live bets yet. Each dog's old-board rehearsal is on its row below; it is never drawn here.";
const DASHES = [undefined, "7 4", "2 3", "10 3 2 3", "14 4", "1 4"];

/** The filter list with "mine" (the dogs this browser follows, ./hounds-follow.js) on top of core's house/user. */
function scoped(filter, category = "all") {
  if (filter === "mine") {
    const mine = followedIds();
    return filterHounds(state.hounds.filter((x) => mine.has(String(x.id))), "all", category);
  }
  return filterHounds(state.hounds, filter, category);
}

const state = {
  hounds: [],
  filter: "all",          // all | house | user | mine
  category: "all",
  hidden: new Set(),      // hound ids off the chart
  hiddenInitialised: false,
  series: null,           // { id: [points] } once loaded
  seriesError: null,
  payload: null,
  houndmaster: null,
};

const q = (hook) => document.querySelector(`[data-hook='${hook}']`);

function stateBox(kind, text, retry) {
  const box = h("div", { class: `hd-state hd-state--${kind}`, role: kind === "down" ? "alert" : "status",
    "data-hook": "section-state", "data-kind": kind }, [h("p", { text })]);
  if (retry) box.appendChild(h("button", { type: "button", class: "btn btn--ghost hd-retry", text: "Try again",
    on: { click: retry } }));
  return box;
}

/**
 * A restart answers from the last saved copy (`stale: true`, `as_of` = when it was built) while the server
 * works the new numbers out. The page says so in one small line and asks again on the server's cadence
 * until a real answer replaces it. The numbers shown are the earlier ones, never edited.
 */
export function isStale(payload) {
  return !!(payload && typeof payload === "object" && payload.stale === true);
}

export function staleText(payload) {
  const when = fmtWhen(payload && payload.as_of) || (payload && payload.as_of) || "";
  return when ? `Updated ${when}, from the last saved copy while the latest numbers are worked out.`
    : "From the last saved copy while the latest numbers are worked out.";
}

function staleNote(payload) {
  return h("p", { class: "hd-fine", "data-hook": "stale-note", text: staleText(payload) });
}

function warmingBox(payload) {
  return h("div", { class: "hd-state hd-state--warming", role: "status", "data-hook": "section-state",
    "data-kind": "warming" }, [h("p", { text: (payload && payload.message) || WARMING_FALLBACK_TEXT })]);
}

/** The avatar of a hound, wearing its vibe. */
function dogAvatar(hound, size, extra) {
  return avatarSvg(hound.name, Object.assign({ size, category: categoryOf(hound), vibe: vibeOf(hound) }, extra || {}));
}

function knownHound(id) {
  return state.hounds.find((x) => String(x.id) === String(id)) || null;
}

// ---- the form strip: hot dog, ice cold, on tilt --------------------------------------------------------

function formCard(slot, title, hound, detail, empty) {
  const card = h("article", { class: `hd-formcard hd-formcard--${slot}`, "data-slot": slot, "data-hook": `form-${slot}` }, [
    h("h3", { class: "hd-formcard__title", text: title })]);
  if (!hound) {
    card.appendChild(h("p", { class: "hd-formcard__empty", text: empty }));
    return card;
  }
  card.appendChild(h("div", { class: "hd-formcard__dog" }, [
    dogAvatar(hound, 52),
    h("div", {}, [
      h("a", { class: "hd-formcard__name", href: houndHref(hound.id), text: hound.name || NOT_REPORTED }),
      h("p", { class: "hd-formcard__detail", text: detail }),
    ]),
  ]));
  return card;
}

function renderFormStrip() {
  const grid = q("hounds-form-grid");
  if (!grid) return;
  clearNode(grid);
  if (state.hounds.length === 0) {
    grid.appendChild(h("p", { class: "hd-muted", text: "Nobody's in the ring yet." }));
    return;
  }
  const { hot, cold, tilt } = formStrip(state.hounds);
  grid.appendChild(formCard("hot", "Hot dog 🔥", hot, hot ? weekText(hot.form) : "",
    "Nobody's above water this week."));
  grid.appendChild(formCard("cold", "Ice cold 🥶", cold, cold ? weekText(cold.form) : "",
    "Nobody's freezing. Yet."));
  const run = tilt ? streakView(tilt.form) : null;
  grid.appendChild(formCard("tilt", "On tilt 😵", tilt, run ? `${run.length} losses in a row` : "",
    "Nobody's on tilt. Enjoy it."));
  renderMasterBanner([tilt, cold, hot]);
}

/** The Houndmaster has an opinion about whoever is in the strip: a roast for the dogs losing, a brag for the hot one. */
function renderMasterBanner(candidates) {
  const box = q("houndmaster-banner");
  if (!box) return;
  clearNode(box);
  for (const hound of candidates) {
    const said = hound ? houndmasterLine(hound, state.houndmaster) : null;
    if (!said) continue;
    box.hidden = false;
    box.removeAttribute("hidden");
    box.appendChild(avatarSvg("The Houndmaster", { size: 44, vibe: "grumpy", category: "mixed" }));
    box.appendChild(h("p", { class: "hd-master__line", "data-hook": "houndmaster-line", "data-kind": said.kind }, [
      h("strong", { text: `${said.by} to ${hound.name}: ` }), `“${said.line}”`]));
    return;
  }
  box.hidden = true;
  box.setAttribute("hidden", "");
}

// ---- chart ----------------------------------------------------------------------------------------

function chartWidth(panel) {
  const box = panel && panel.getBoundingClientRect ? panel.getBoundingClientRect() : null;
  const w = box && box.width ? box.width : 640;
  return Math.max(300, Math.min(760, Math.round(w)));
}

function lineSample(color, dash) {
  return s("svg", { class: "hd-legend__line", viewBox: "0 0 22 6", width: 22, height: 6, "aria-hidden": "true",
    focusable: "false" }, [s("line", { x1: 1, x2: 21, y1: 3, y2: 3, stroke: color, "stroke-width": 2.25,
    "stroke-dasharray": dash || undefined, "stroke-linecap": "round" })]);
}

/** The series field a hound is drawn with: the average price, unless the server says it has none for this hound. */
function seriesKey(hound) {
  return hound && hound.spark_basis === "recorded_price" ? "cum_units_recorded_price" : "cum_units_average_price";
}

function renderChartPanel() {
  const panel = q("hounds-chart-panel");
  if (!panel) return;
  clearNode(panel);
  const titleNode = q("hounds-chart-title");
  if (titleNode) titleNode.textContent = state.series ? FORWARD_TITLE : "";
  if (state.seriesError) {
    const e = describeError(state.seriesError, "the bankroll chart");
    panel.appendChild(stateBox(e.kind, e.text));
    return;
  }
  if (state.series === null) {
    panel.appendChild(h("p", { class: "hd-muted", "data-hook": "chart-loading", text: "Loading the chart..." }));
    return;
  }
  const shown = sortByUnits(scoped(state.filter, state.category));
  // baselines stay selectable but start off the chart; they are listed under the board, not hidden
  const shownAll = shown.concat(sortByUnits(splitBaselines(scoped(state.filter)).baselines)
    .filter((x) => !shown.includes(x)));
  const legend = h("ul", { class: "hd-legend", "data-hook": "chart-legend", "aria-label": "Dogs on the chart" });
  const lines = [];
  const perCategory = {};
  let usedBestPrice = false;
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
    }, [dogAvatar(hound, 22), lineSample(color, dash),
      h("span", { class: "hd-legend__name", text: hound.name })])]));
    if (!off) {
      const key = seriesKey(hound);
      const points = toChartPoints(pointsFor(state.series, hound.id, "forward"), key);
      if (key !== "cum_units_average_price" && points.length) usedBestPrice = true;
      lines.push({ id: String(hound.id), name: hound.name, color, dash, points });
    }
  });
  const anyPoints = lines.some((l) => l.points.length > 0);
  const chart = renderLineChart({
    series: lines, width: chartWidth(panel), height: chartWidth(panel) < 480 ? 230 : 280, unit: "units",
    label: "Cumulative paper units at the average price, live bets only, one line per dog",
    zeroLabel: "0 units",
    dashes: lines.map((l) => l.dash),
    emptyText: state.hounds.length === 0 ? "No dogs yet, so there is nothing to draw."
      : shown.length === 0 ? "No dogs in this filter."
      : !anyPoints && !hasForwardData(state.series) ? NO_FORWARD_CHART_TEXT
        : "No settled bets to draw yet.",
  });
  panel.appendChild(chart);
  panel.appendChild(legend);
  if (usedBestPrice) {
    panel.appendChild(h("p", { class: "hd-fine", "data-hook": "chart-basis-note",
      text: "A dog whose boards could not all be averaged is drawn at its best recorded price instead." }));
  }
}

function toggle(id) {
  if (state.hidden.has(id)) state.hidden.delete(id); else state.hidden.add(id);
  renderChartPanel();
}

// ---- leaderboard ----------------------------------------------------------------------------------

function statusLine(hound) {
  const word = STATUS_WORDS[hound.status] || "Status not reported";
  return h("span", { class: `hd-status hd-status--${hound.status || "unknown"}`, text: word });
}

/** Forward facts. The average price is the headline units figure, the best price the small print. */
function resultFacts(view) {
  const rec = (view && view.record) || null;
  if (!rec || !(rec.bets > 0)) {
    return { record: NO_FORWARD_TEXT, clv: null, units: null };
  }
  return { record: fmtRecord(rec), clv: friendlyClose(view.clv), units: unitsPairText(rec) };
}

/** How far a dog's prices sat from the close, in plain words. Null means "not measured yet", never zero. */
export function friendlyClose(clv) {
  if (!clv || !isNum(clv.mean_pts)) return null;
  const n = isNum(clv.n) ? `${clv.n} ${clv.n === 1 ? "bet" : "bets"}` : "an unreported number of bets";
  const side = clv.mean_pts > 0 ? "better than" : clv.mean_pts < 0 ? "worse than" : "level with";
  return { main: `${signed(clv.mean_pts, 1)} pts`, detail: `${side} the closing line on average, over ${n}` };
}

/** The replay block is a record and a best-price figure only: no CLV, no average price, never a forward number. */
function replayFacts(hound) {
  const block = hound && hound.replay;
  if (!block || typeof block !== "object") return null;
  if (!(block.bets > 0)) return { record: "no rehearsal reported", units: null };
  return { record: fmtRecord(block), units: `${fmtUnits(block.units_recorded_price)} ${BEST_PRICE_WORDS}` };
}

function verifiedBadge(hound) {
  if (hound.verified === true) {
    return h("span", { class: "hd-verified", "data-hook": "verified" }, [
      h("span", { "aria-hidden": "true", text: "✓ " }), "verified"]);
  }
  // "not verified" is a finding about checked bets; a hound with nothing checkable yet has no finding.
  if (hound.verified === false && hound.verified_share !== null && hound.verified_share !== undefined) {
    return h("span", { class: "hd-unverified", text: "not verified" });
  }
  return null;
}

/** The badge as a button: tap it and the one-line meaning opens under it. */
function badgeButton(hound) {
  const badge = badgeFor(hound);
  const explain = h("p", { class: "hd-badge-explain", "data-hook": "badge-explain", hidden: true }, badge.explain);
  const btn = h("button", { type: "button", class: `hd-chip hd-chip--${badge.tone} hd-badgebtn`,
    "data-hook": "badge", "data-badge": badge.key, "aria-expanded": "false",
    "aria-label": `${badge.word}. Tap to see what it means.`,
    on: { click: () => {
      const open = btn.getAttribute("aria-expanded") === "true";
      btn.setAttribute("aria-expanded", open ? "false" : "true");
      explain.hidden = open;
    } } }, [h("span", { "aria-hidden": "true", text: verdictGlyph(badge.tone) + " " }), badge.text]);
  return h("div", { class: "hd-row__badgebox" }, [btn, explain]);
}

function row(hound, rank) {
  const tone = badgeFor(hound).tone;
  const cat = categoryOf(hound);
  const forward = resultFacts(segmentView(hound, "forward"));
  const replay = replayFacts(hound);
  const verified = verifiedBadge(hound);
  const seriesPts = state.series ? pointsFor(state.series, hound.id, "forward") : null;
  const fun = FUN_CATEGORIES.includes(cat);
  const persona = personaOf(hound);
  const units = unitsOf(hound);
  const rec = hound.record;
  const streak = streakView(hound.form);
  const week = weekText(hound.form);
  const unitsTone = units === null ? "none" : units > 0 ? "up" : units < 0 ? "down" : "flat";
  const dead = hound.status === "retired";
  return h("li", { class: "hd-row", "data-hound": hound.id, "data-kind": hound.kind || "", "data-category": cat,
    "data-verdict": tone, "data-status": hound.status || "" }, [
    h("div", { class: "hd-row__rank", "data-hook": "rank", text: dead ? "💀" : `#${rank}` }),
    h("div", { class: "hd-row__who" }, [
      dogAvatar(hound, 52, { gray: dead, dead }),
      h("div", { class: "hd-row__id" }, [
        h("span", { class: "hd-row__namebar" }, [
          h("a", { class: "hd-row__name", href: houndHref(hound.id), text: hound.name || NOT_REPORTED }),
          followedIds().has(String(hound.id)) ? h("span", { class: "hd-row__star", "data-hook": "row-star",
            role: "img", "aria-label": "You follow this dog", text: "⭐" }) : null,
          fun ? h("span", { class: "hd-tag", "data-hook": "fun-tag", text: FUN_TAG }) : null,
        ]),
        persona && persona.catchphrase
          ? h("p", { class: "hd-row__catch", "data-hook": "catchphrase", text: `“${persona.catchphrase}”` })
          : (hound.tagline ? h("p", { class: "hd-row__tagline", text: hound.tagline }) : null),
        h("span", { class: "hd-badges" }, [
          cat ? h("span", { class: "hd-chip-cat", "data-category": cat, text: categoryLabel(cat) }) : null,
          h("span", { class: "hd-badge", text: hound.kind === "user"
            ? (hound.owner_display ? `Built by ${hound.owner_display}` : "Builder's dog") : "House dog" }),
        ]),
      ]),
    ]),
    h("div", { class: "hd-row__score", "data-hook": "score" }, [
      h("span", { class: `hd-units hd-units--${unitsTone}`, "data-hook": "row-units",
        text: units === null ? "no bets yet" : fmtUnits(units) }),
      h("span", { class: "hd-wl", "data-hook": "row-wl" },
        rec && rec.bets > 0 ? [h("strong", { text: wlText(rec) }), ` · ${rec.bets} ${rec.bets === 1 ? "bet" : "bets"}`] : "0-0"),
      streak ? h("span", { class: `hd-streak hd-streak--${streak.tone}`, "data-hook": "streak",
        role: "img", "aria-label": streak.label, text: streak.text }) : null,
      week ? h("span", { class: "hd-week", "data-hook": "week", text: week }) : null,
    ]),
    badgeButton(hound),
    h("div", { class: "hd-row__line" }, [
      renderSparkline({ values: sparkValues(hound, seriesPts), color: houndColor(hound),
        label: `${hound.name}: paper units, last 30 points` }),
    ]),
    h("details", { class: "hd-row__more", "data-hook": "receipts" }, [
      h("summary", { text: "The receipts" }),
      h("dl", { class: "hd-row__facts", "data-hook": "forward-facts" }, [
        h("div", {}, [h("dt", { text: "Live record" }), h("dd", { text: forward.record })]),
        h("div", {}, [h("dt", { text: "Price vs the close" }), h("dd", {},
          forward.clv ? [forward.clv.main, h("span", { class: "hd-fine", text: ` (${forward.clv.detail})` })]
            : [h("span", { class: "hd-fine", text: "not measured yet" })])]),
        h("div", {}, [h("dt", { text: "Status" }), h("dd", {}, [statusLine(hound), verified ? " " : null, verified])]),
        h("div", {}, [h("dt", { text: "Units, two ways" }), h("dd", { "data-hook": "units-pair",
          text: forward.units || "none yet" })]),
      ]),
      replay ? h("p", { class: "hd-row__replay", "data-hook": "replay-line" }, [
        h("strong", { text: REPLAY_NOTE }), ": ",
        replay.record,
        replay.units ? `; ${replay.units}` : ""]) : null,
    ]),
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
  const count = (f) => scoped(f).length;
  filterButtons(bar, [["all", `All (${count("all")})`], ["mine", `My dogs ⭐ (${count("mine")})`],
    ["house", `House (${count("house")})`], ["user", `Builders' (${count("user")})`]],
    state.filter, (k) => { state.filter = k; renderAll(); }, "data-filter");
  const cats = q("hounds-categories");
  if (!cats) return;
  clearNode(cats);
  const present = presentCategories(scoped(state.filter));
  if (state.category !== "all" && !present.includes(state.category)) state.category = "all";
  const base = scoped(state.filter);
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

/** Board order: dogs still in the race by paper units, then the put-down dogs by theirs. */
export function boardOrder(hounds) {
  const live = sortByUnits((hounds || []).filter((x) => x.status !== "retired"));
  const dead = sortByUnits((hounds || []).filter((x) => x.status === "retired"));
  return live.concat(dead);
}

function renderBoard() {
  const list = q("hounds-list");
  const baseBox = q("hounds-baselines-list");
  if (!list) return;
  clearNode(list);
  const filtered = scoped(state.filter, state.category);
  const ordered = boardOrder(splitBaselines(filtered).race);
  const rankOf = new Map(ordered.map((x, i) => [x, i + 1]));
  const race = pinFollowed(ordered);          // followed dogs first, in their own order; ranks stay true
  if (race.length === 0) {
    list.appendChild(h("li", { class: "hd-empty", "data-hook": "board-empty" }, [
      h("p", { text: state.hounds.length === 0
        ? "Nobody's in the ring yet. When the first dog puts down a paper bet it shows up here."
        : state.filter === "mine" ? "You aren't following any dogs yet. Open a dog and tap ⭐ Follow."
        : "No dogs match this filter." }),
      h("a", { class: "btn btn--primary", href: "build-a-hound.html", text: "Build your dog" }),
    ]));
  }
  race.forEach((hound) => list.appendChild(row(hound, rankOf.get(hound))));
  // baselines: below the board, collapsed, always listed (the house/builder filter applies; the category filter does not)
  const group = q("hounds-baselines");
  if (group && baseBox) {
    clearNode(baseBox);
    const baselines = boardOrder(splitBaselines(scoped(state.filter)).baselines);
    group.hidden = baselines.length === 0;
    if (baselines.length === 0) group.setAttribute("hidden", ""); else group.removeAttribute("hidden");
    const sum = q("hounds-baselines-summary");
    if (sum) sum.textContent = `Baselines (${baselines.length}): the dumb dogs everybody else has to beat`;
    baselines.forEach((hound, i) => baseBox.appendChild(row(hound, i + 1)));
  }
}

// ---- which dog gets put down next? -----------------------------------------------------------------

function renderPoll() {
  const box = q("hounds-poll-list");
  if (!box) return;
  clearNode(box);
  const close = closestToRetirement(state.hounds, 3);
  if (close.length === 0) {
    box.appendChild(h("p", { class: "hd-muted", "data-hook": "poll-empty",
      text: state.hounds.length === 0 ? "Nobody's in the ring yet." : "Nobody has bets on the board yet, so nobody's in danger." }));
    return;
  }
  const ul = h("ol", { class: "hd-poll__list", "data-hook": "poll-options" });
  for (const entry of close) {
    const hound = entry.hound;
    const pct = Math.round(entry.danger * 100);
    ul.appendChild(h("li", { class: "hd-poll__opt", "data-hound": hound.id, "data-hook": "poll-option" }, [
      dogAvatar(hound, 44),
      h("div", { class: "hd-poll__body" }, [
        h("a", { class: "hd-poll__name", href: houndHref(hound.id), text: hound.name || NOT_REPORTED }),
        h("div", { class: "hd-poll__bar", role: "img", "aria-label": `${pct} percent of the way to the doghouse` }, [
          h("span", { class: "hd-poll__fill", style: `width:${Math.max(3, pct)}%` })]),
        h("p", { class: "hd-poll__text" }, `${fmtUnits(entry.units)} so far · ${cushionText(entry)}`),
      ]),
    ]));
  }
  box.appendChild(ul);
  box.appendChild(h("p", { class: "hd-fine", "data-hook": "poll-note",
    text: `No ballot yet. The rule decides: ${Math.abs(RETIRE_UNITS)} units under zero, or a long run of feeding the book, and the dog is put down.` }));
}

function renderMeta() {
  const basis = q("hounds-basis");
  if (basis) {
    const p = state.payload || {};
    const notice = noticeLine(p);
    basis.textContent = [
      p.basis ? p.basis : "",
      isStale(p) ? staleText(p) : (p.as_of ? `As of ${fmtWhen(p.as_of) || p.as_of}.` : ""),
      notice,
    ].filter(Boolean).join(" ");
  }
}

function renderAll() {
  renderFilter();
  renderFormStrip();
  renderChartPanel();
  renderBoard();
  renderPoll();
  renderMeta();
}

// ---- stream, as chat -------------------------------------------------------------------------------

function streamItem(item) {
  const who = String(item.who_decided || "").toLowerCase();
  const name = item.hound_name || item.name || "";
  const when = fmtWhen(item.decided_utc || item.date);
  const known = knownHound(item.hound_id);
  const line = chatLine(item, known);
  const bubble = h("div", { class: "hd-chat__bubble" }, [
    h("p", { class: "hd-chat__text", "data-hook": "chat-text" }, [
      item.hound_id !== undefined ? h("a", { class: "hd-chat__name", href: houndHref(item.hound_id), text: line.lead })
        : h("strong", { class: "hd-chat__name", text: line.lead }),
      ` ${line.rest}`,
      line.outcome ? h("span", { class: `hd-chat__out hd-chat__out--${line.outcome.tone}`, "data-hook": "chat-outcome",
        text: ` ${line.outcome.tone === "win" ? "✅" : line.outcome.tone === "loss" ? "❌" : "➖"} ${line.outcome.text}` }) : null,
    ]),
    h("p", { class: "hd-chat__meta" }, [
      line.game ? h("span", { text: line.game }) : null,
      when ? h("span", { class: "hd-stream__when", text: ` · ${when}` }) : null,
      h("span", { class: `hd-who hd-who--${who || "unknown"}`, "data-hook": "stream-who" }, `Decided by: ${whoLabel(who)}`),
    ]),
  ]);
  return h("li", { class: "hd-chat__item", "data-who": who || "unknown", "data-refused": item.refused ? "true" : "false" }, [
    name ? avatarSvg(name, { size: 36, category: known ? categoryOf(known) : "", vibe: known ? vibeOf(known) : "" }) : null,
    bubble,
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
    if (isWarming(data)) {
      box.appendChild(warmingBox(data));
      retryWhileWarming("stream", loadStream, data);
      return;
    }
    if (isStale(data)) retryWhileWarming("stream", loadStream, data); else stopWarmingRetry("stream");
    const items = Array.isArray(data && data.items) ? data.items : [];
    if (isStale(data)) box.appendChild(staleNote(data));
    if (items.length === 0) {
      box.appendChild(h("p", { class: "hd-muted", "data-hook": "stream-empty",
        text: "Quiet in the kennel. When a dog makes a move it shows up here, with who made the call: the rule, the code or the model." }));
    } else {
      const ul = h("ul", { class: "hd-chat__list", "data-hook": "stream-list" });
      for (const item of items.slice(0, 40)) ul.appendChild(streamItem(item || {}));
      box.appendChild(ul);
    }
  } catch (err) {
    const e = describeError(err, "the live feed");
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

// ---- graveyard: tombstones ------------------------------------------------------------------------

/** Contract: a retired hound is a HoundSummary with `retired: {date, cause}`. */
function graveRow(hound) {
  const fwd = segmentView(hound, "forward");
  const retired = hound.retired || {};
  const rec = fwd && fwd.record;
  const finalUnits = unitsOf(hound);
  const final = [rec && rec.bets > 0 ? `${wlText(rec)} in ${rec.bets} bets` : "",
    finalUnits !== null ? fmtUnits(finalUnits) : ""].filter(Boolean).join(", ");
  return h("li", { class: "hd-stone", "data-hound": hound.id }, [
    h("div", { class: "hd-stone__slab" }, [
      avatarSvg(hound.name, { size: 56, gray: true, dead: true, category: categoryOf(hound), vibe: vibeOf(hound) }),
      h("p", { class: "hd-stone__rip", text: "R.I.P." }),
      h("a", { class: "hd-stone__name hd-row__name", href: houndHref(hound.id), text: hound.name || NOT_REPORTED }),
      h("p", { class: "hd-stone__epitaph", "data-hook": "epitaph", text: `“${epitaphFor(hound)}”` }),
    ]),
    h("div", { class: "hd-stone__facts" }, [
      h("p", { class: "hd-grave__cause", "data-hook": "grave-cause" }, [h("strong", { text: "Cause of death: " }),
        causeText(retired.cause),
        retired.date ? h("span", { class: "hd-fine", text: ` (${fmtWhen(retired.date)})` }) : null]),
      h("p", { class: "hd-fine", text: [final ? `Final: ${final}` : "",
        hound.last_bet_utc ? `last bet ${fmtWhen(hound.last_bet_utc)}` : ""].filter(Boolean).join(" · ") }),
    ]),
  ]);
}

export async function loadGraveyard() {
  const box = q("hounds-graveyard");
  if (!box) return;
  try {
    const data = await apiGet("/hounds/graveyard");
    clearNode(box);
    if (isWarming(data)) {
      box.appendChild(warmingBox(data));
      retryWhileWarming("graveyard", loadGraveyard, data);
      return;
    }
    if (isStale(data)) retryWhileWarming("graveyard", loadGraveyard, data); else stopWarmingRetry("graveyard");
    const list = Array.isArray(data && data.hounds) ? data.hounds : [];
    if (isStale(data)) box.appendChild(staleNote(data));
    if (list.length === 0) {
      box.appendChild(h("p", { class: "hd-muted", "data-hook": "grave-empty",
        text: "No tombstones yet. Nobody has been put down. Give it time." }));
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
  // (a retry while the numbers are a saved copy keeps the rows it has, rather than blanking them every 5 s)
  if (list && state.hounds.length === 0) {
    clearNode(list); list.appendChild(h("li", { class: "hd-muted", text: "Loading the kennel..." }));
  }
  try {
    const data = await apiGet("/hounds");
    if (isWarming(data)) {
      state.hounds = [];
      state.payload = null;
      if (list) { clearNode(list); list.appendChild(h("li", {}, [warmingBox(data)])); }
      renderFilter();
      renderFormStrip();
      renderPoll();
      const panel = q("hounds-chart-panel");
      if (panel) { clearNode(panel); panel.appendChild(h("p", { class: "hd-muted", "data-hook": "chart-needs-board",
        text: "The chart appears as soon as the race has been worked out." })); }
      retryWhileWarming("board", loadBoard, data);
      return false;
    }
    if (isStale(data)) retryWhileWarming("board", loadBoard, data); else stopWarmingRetry("board");
    state.payload = data || {};
    state.hounds = Array.isArray(data && data.hounds) ? data.hounds : [];
    state.houndmaster = data && data.houndmaster && typeof data.houndmaster === "object" ? data.houndmaster : null;
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
    renderFormStrip();
    renderPoll();
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
      const raw = await apiGet(`/hounds/series?ids=${ids.join(",")}`);
      state.series = isWarming(raw) ? {} : normalizeSeries(raw);
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
