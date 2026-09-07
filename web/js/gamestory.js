/**
 * GAME STORY -- the six F-2 sections (starters, bullpen, lineups, travel,
 * weather, park) games.js only listed by key name until now. This module
 * owns ALL of that rendering so the stream already working in games.js
 * never has to merge around it; games.js touches exactly two lines (see
 * its own comment at the renderGameStory import/call site).
 *
 * ARCHITECTURE
 * -------------------------------------------------------------------
 * `renderGameStory(advanced, quick)` reads `advanced.sections` directly
 * (never trusting a shape it has not verified against the live payload --
 * captured 2026-09-07 against GET /game/2026-09-07/CIN/LAD) and returns
 * one <section class="gs-story"> node holding a sub-panel per section
 * that is actually present, or `null` when none of the five are. `teams`
 * is deliberately NOT one of the five: games.js's own gqvTeams() and the
 * identity panel's record/RS-RA cells already render it, and repeating
 * it here would be the exact duplication the brief asks this file to
 * avoid.
 *
 * HONESTY RULES THIS FILE FOLLOWS (see the task brief this module was
 * built against)
 * -------------------------------------------------------------------
 * - A present section renders only the fields it actually carries; a
 *   null/undefined field renders "--" (dom.js's renderAbsent) or is
 *   omitted, never invented.
 * - Every rate the payload gives a sample for (starts, games, window
 *   days) shows that sample alongside it. `*_sp_thin`/long_trip/
 *   dense_stretch render as visible amber chips (the shared
 *   .pv-chip--warn tone every other "know this, not a pick" state in
 *   this client already uses -- screens.css's PRICE VERDICT WORDCHIP
 *   section), never silently folded into the number.
 * - No win probability, no prediction, no "edge" framing anywhere in
 *   this file -- the `diff_sp_*` matchup numbers are printed as a plain
 *   signed difference, deliberately labelled DIFFERENCE rather than any
 *   edge/advantage word.
 * - An entirely-missing section renders NOTHING here -- the Advanced
 *   view's own consolidated gap ledger (gavGapsConsolidated in games.js)
 *   is the one place that explains absences; this file does not add a
 *   second one.
 */

import { el, humanizeKey, renderAbsent } from "./dom.js";

/** Mirrors games.js's own `readSection` -- kept as a local copy rather
 * than an import so this module has no dependency on games.js at all
 * (the two files only meet at the one call site games.js owns). */
function readSection(advanced, name) {
  const sections = advanced && typeof advanced.sections === "object" ? advanced.sections : {};
  const value = sections ? sections[name] : undefined;
  return value === undefined ? null : value;
}

function fmtNum(value, digits = 2) {
  if (typeof value !== "number" || !Number.isFinite(value)) return null;
  return value.toFixed(digits);
}

/** One labelled figure, with its sample size printed underneath when the
 * payload gives one -- same shape as games.js's own gqvStatCell, kept as
 * a local copy per this module's no-dependency-on-games.js rule above. */
function statCell(label, valueText, sampleText) {
  const cell = el("div", { class: "gs-stat chamfer" });
  cell.appendChild(el("div", { class: "gs-stat__label", text: label }));
  cell.appendChild(el("div", { class: "gs-stat__value" },
    [valueText != null ? document.createTextNode(valueText) : renderAbsent()]));
  if (sampleText) cell.appendChild(el("div", { class: "gs-stat__n", text: sampleText }));
  return cell;
}

/** A label/value inline pair for the one-off facts (days rest, miles,
 * window) that do not belong in the stat grid. */
function factRow(label, valueText) {
  const row = el("div", { class: "gs-fact" });
  row.appendChild(el("span", { class: "gs-fact__label", text: label }));
  row.appendChild(el("span", { class: "gs-fact__value" },
    [valueText != null ? document.createTextNode(valueText) : renderAbsent()]));
  return row;
}

/** The shared amber "know this, not a pick" chip (screens.css's
 * .pv-chip--warn, already used for THIN SAMPLE/stale-board/pending states
 * elsewhere in this client) -- reused verbatim rather than a new tone. */
function warnChip(text) {
  return el("span", { class: "pv-chip pv-chip--warn", text });
}

function panelHead(text) {
  return el("div", { class: "gs-panel__eyebrow", text });
}

/* =====================================================================
 * STARTERS
 * ===================================================================*/

const STARTER_STATS = [
  { key: "era", label: "ERA", digits: 2 },
  { key: "fip", label: "FIP", digits: 2 },
  { key: "whip", label: "WHIP", digits: 3 },
  { key: "k9", label: "K/9", digits: 1 },
  { key: "ip_per_start", label: "IP / START", digits: 2 },
];

function starterColumn(section, side, teamAbbr, probable) {
  const col = el("div", { class: "gs-col" });
  col.appendChild(el("div", { class: "gs-col__head", text: (probable || teamAbbr || "").toUpperCase() }));
  const known = section[`${side}_sp_known`];
  if (!known) {
    col.appendChild(el("p", { class: "gs-col__absent", text: "Starter not confirmed for this side." }));
    return col;
  }
  const thin = section[`${side}_sp_thin`] === true;
  if (thin) col.appendChild(warnChip("THIN SAMPLE"));

  const starts = section[`${side}_sp_starts`];
  const sample = typeof starts === "number" ? `n = ${starts} starts` : null;
  const grid = el("div", { class: "gs-stats" });
  grid.appendChild(statCell("STARTS", typeof starts === "number" ? String(starts) : null, null));
  for (const { key, label, digits } of STARTER_STATS) {
    grid.appendChild(statCell(label, fmtNum(section[`${side}_sp_${key}`], digits), sample));
  }
  col.appendChild(grid);

  const rest = section[`${side}_sp_days_rest`];
  col.appendChild(factRow("DAYS REST", typeof rest === "number" ? `${rest} day${rest === 1 ? "" : "s"}` : null));

  const recentEra = section[`${side}_sp_recent_era`];
  const recentStarts = section[`${side}_sp_recent_starts`];
  const seasonEra = section[`${side}_sp_era`];
  if (typeof recentEra === "number") {
    const n = typeof recentStarts === "number" ? `${recentStarts} start${recentStarts === 1 ? "" : "s"}` : "recent starts";
    const seasonText = typeof seasonEra === "number" ? ` — season ${seasonEra.toFixed(2)} ERA` : "";
    col.appendChild(el("p", { class: "gs-note",
      text: `Recent form: ${recentEra.toFixed(2)} ERA over the last ${n}${seasonText}.` }));
  }
  return col;
}

/** `diff_sp_*` printed as a plain signed difference (home minus away, the
 * API's own convention -- verified against the sample payload: e.g.
 * `diff_sp_era: 2.5` with away 2.7867 / home 5.2867). Deliberately
 * labelled DIFFERENCE, never an "edge"/advantage word, and only rendered
 * when `both_sp_known` is true. */
function starterDiffRow(section) {
  if (section.both_sp_known !== true) return null;
  const chips = el("div", { class: "gs-diffrow__chips" });
  let any = false;
  for (const { key, label, digits } of STARTER_STATS) {
    const v = section[`diff_sp_${key}`];
    if (typeof v !== "number") continue;
    any = true;
    const sign = v > 0 ? "+" : "";
    chips.appendChild(el("span", { class: "gs-diffchip", text: `${label} ${sign}${v.toFixed(digits)}` }));
  }
  if (!any) return null;
  const row = el("div", { class: "gs-diffrow" });
  row.appendChild(el("div", { class: "gs-diffrow__label", text: "DIFFERENCE · HOME MINUS AWAY" }));
  row.appendChild(chips);
  return row;
}

function renderStarters(advanced, quick) {
  const section = readSection(advanced, "starters");
  if (!section) return null;
  const game = advanced && typeof advanced.game === "object" ? advanced.game : null;
  const panel = el("section", { class: "gs-panel panel chamfer", "data-hook": "gs-starters" });
  panel.appendChild(panelHead("STARTERS"));
  const cols = el("div", { class: "gs-cols" });
  cols.appendChild(starterColumn(section, "away", quick.away_team, game && game.away_probable));
  cols.appendChild(starterColumn(section, "home", quick.home_team, game && game.home_probable));
  panel.appendChild(cols);
  const diff = starterDiffRow(section);
  if (diff) panel.appendChild(diff);
  return panel;
}

/* =====================================================================
 * BULLPEN
 * ===================================================================*/

/** A single reliever row, shape-agnostic on purpose: the local bullpen
 * log is mid-rebuild as of this file's writing (relievers: [] on every
 * game here), so the real row shape has not been observed yet. Prints
 * whatever the row actually carries -- a name-ish field first, then every
 * other scalar field humanized -- rather than guessing at field names
 * that might not match what staging's populated log actually sends. */
function relieverRow(row) {
  const wrap = el("div", { class: "gs-reliever" });
  const name = row.name || row.player_name || row.pitcher || row.reliever || "Reliever";
  wrap.appendChild(el("span", { class: "gs-reliever__name", text: String(name) }));

  // The row shape has now been observed on a populated log (2026-09-07):
  // person_id, name, appearances, innings, pitches, pitches_known,
  // availability, availability_reason. Render those deliberately -- the
  // generic loop this replaced printed "Availability available ·
  // Availability Reason rested yesterday" on every row and leaked the raw
  // enum `likely_unavailable` onto the page. Anything the row carries
  // beyond these keys still falls through to the generic treatment, so a
  // field added later is shown rather than silently dropped -- but with
  // underscores turned to spaces, so no enum value ever reaches a reader
  // verbatim.
  const known = new Set(["name", "player_name", "pitcher", "reliever", "person_id", "team",
    "appearances", "innings", "pitches", "pitches_known", "availability", "availability_reason"]);
  const bits = [];
  if (typeof row.appearances === "number") {
    bits.push(`${row.appearances} app${row.appearances === 1 ? "" : "s"}`);
  }
  if (typeof row.innings === "number") bits.push(`${fmtNum(row.innings, 2)} IP`);
  if (typeof row.pitches === "number" && row.pitches_known !== false) {
    bits.push(`${row.pitches} pitches`);
  }
  for (const [key, value] of Object.entries(row)) {
    if (known.has(key) || value === null || value === undefined) continue;
    if (typeof value === "number") {
      bits.push(`${humanizeKey(key)} ${Number.isInteger(value) ? value : value.toFixed(2)}`);
    } else if (typeof value === "string") {
      bits.push(`${humanizeKey(key)} ${value.replace(/_/g, " ")}`);
    }
  }
  if (bits.length) wrap.appendChild(el("span", { class: "gs-reliever__meta", text: bits.join(" · ") }));

  if (typeof row.availability === "string" && row.availability) {
    const word = row.availability.replace(/_/g, " ");
    const fine = row.availability === "available";
    wrap.appendChild(el("span", {
      class: `gs-reliever__avail${fine ? "" : " gs-reliever__avail--warn"}`,
      text: word.toUpperCase() }));
  }
  if (typeof row.availability_reason === "string" && row.availability_reason) {
    wrap.appendChild(el("span", { class: "gs-reliever__why", text: row.availability_reason }));
  }
  return wrap;
}

function bullpenColumn(teamAbbr, data) {
  const col = el("div", { class: "gs-col" });
  col.appendChild(el("div", { class: "gs-col__head", text: (teamAbbr || "").toUpperCase() }));
  if (!data) {
    col.appendChild(el("p", { class: "gs-col__absent", text: "No bullpen data for this team." }));
    return col;
  }
  const windowDays = data.window_days;
  const count = data.reliever_count;
  if (!count) {
    // A real "no relief appearances in the window" state -- rendered
    // honestly as a sentence, never hidden and never a fabricated row.
    col.appendChild(el("p", { class: "gs-note",
      text: `No relief appearances recorded in the last ${typeof windowDays === "number" ? windowDays : 7} `
          + `day${windowDays === 1 ? "" : "s"}${data.as_of ? ` (as of ${data.as_of})` : ""}.` }));
    return col;
  }
  col.appendChild(factRow("RELIEVERS USED", String(count)));
  col.appendChild(factRow("BULLPEN INNINGS", fmtNum(data.total_innings, 1)));
  col.appendChild(factRow("WINDOW", typeof windowDays === "number"
    ? `${windowDays} day${windowDays === 1 ? "" : "s"}${data.as_of ? ` · as of ${data.as_of}` : ""}` : null));
  const relievers = Array.isArray(data.relievers) ? data.relievers : [];
  if (relievers.length) {
    const list = el("div", { class: "gs-reliever-list" });
    for (const r of relievers) {
      if (r && typeof r === "object") list.appendChild(relieverRow(r));
    }
    col.appendChild(list);
  }
  return col;
}

function renderBullpen(advanced, quick) {
  const section = readSection(advanced, "bullpen");
  if (!section) return null;
  const panel = el("section", { class: "gs-panel panel chamfer", "data-hook": "gs-bullpen" });
  panel.appendChild(panelHead("BULLPEN"));
  const cols = el("div", { class: "gs-cols" });
  cols.appendChild(bullpenColumn(quick.away_team, section[quick.away_team]));
  cols.appendChild(bullpenColumn(quick.home_team, section[quick.home_team]));
  panel.appendChild(cols);
  return panel;
}

/* =====================================================================
 * LINEUPS
 * ===================================================================*/

function battingOrder(sideData) {
  const wrap = el("div", { class: "gs-lineup" });
  const batters = Array.isArray(sideData.batters) ? sideData.batters : [];
  for (const b of batters) {
    const row = el("div", { class: "gs-lineup__row" });
    row.appendChild(el("span", { class: "gs-lineup__order", text: typeof b.order === "number" ? String(b.order) : "—" }));
    row.appendChild(el("span", { class: "gs-lineup__name", text: b.name || "—" }));
    row.appendChild(el("span", { class: "gs-lineup__pos", text: b.position || "" }));
    wrap.appendChild(row);
  }
  return wrap;
}

function handednessLine(h) {
  if (!h || typeof h !== "object") return null;
  const parts = [];
  if (typeof h.L === "number" && h.L > 0) parts.push(`${h.L} L`);
  if (typeof h.R === "number" && h.R > 0) parts.push(`${h.R} R`);
  if (typeof h.S === "number" && h.S > 0) parts.push(`${h.S} S`);
  if (typeof h.unknown === "number" && h.unknown > 0) parts.push(`${h.unknown} unknown`);
  if (!parts.length) return null;
  const known = typeof h.known === "number" ? ` (n = ${h.known} known)` : "";
  return parts.join(" · ") + known;
}

function lineupColumn(teamAbbr, sideData) {
  const col = el("div", { class: "gs-col" });
  col.appendChild(el("div", { class: "gs-col__head", text: (teamAbbr || "").toUpperCase() }));
  col.appendChild(battingOrder(sideData));
  const hLine = handednessLine(sideData.handedness);
  if (hLine) col.appendChild(el("p", { class: "gs-note", text: `Handedness: ${hLine}.` }));
  const platoon = sideData.platoon_advantage;
  if (platoon && typeof platoon === "object") {
    if (typeof platoon.share === "number") {
      col.appendChild(factRow("PLATOON ADVANTAGE", `${(platoon.share * 100).toFixed(0)}%`));
    } else if (platoon.reason) {
      const row = factRow("PLATOON ADVANTAGE", null);
      row.appendChild(el("span", { class: "gs-fact__reason", text: ` — ${platoon.reason}` }));
      col.appendChild(row);
    }
  }
  return col;
}

function renderLineups(advanced, quick) {
  const section = readSection(advanced, "lineups");
  if (!section || !section.away || !section.home) return null;
  const panel = el("section", { class: "gs-panel panel chamfer", "data-hook": "gs-lineups" });
  panel.appendChild(panelHead("LINEUPS"));
  const cols = el("div", { class: "gs-cols" });
  cols.appendChild(lineupColumn(quick.away_team, section.away));
  cols.appendChild(lineupColumn(quick.home_team, section.home));
  panel.appendChild(cols);
  return panel;
}

/* =====================================================================
 * TRAVEL & REST
 * ===================================================================*/

function travelColumn(teamAbbr, data) {
  const col = el("div", { class: "gs-col" });
  col.appendChild(el("div", { class: "gs-col__head", text: (teamAbbr || "").toUpperCase() }));
  if (!data) {
    col.appendChild(el("p", { class: "gs-col__absent", text: "No travel data for this team." }));
    return col;
  }
  const miles = data.miles;
  // A home team's real 0-miles state ("home stand") is a fact, not an
  // absence -- shown plainly rather than left to look like a missing row.
  col.appendChild(factRow("MILES TRAVELED",
    typeof miles === "number" ? (miles === 0 ? "0 MI · HOME STAND" : `${miles.toFixed(0)} MI`) : null));
  if (typeof data.zones === "number") {
    const dirWord = data.zones > 0 ? (data.eastward ? " EASTWARD" : " WESTWARD") : "";
    col.appendChild(factRow("TIME ZONES CROSSED", `${data.zones.toFixed(1)}${dirWord}`));
  }
  col.appendChild(factRow("DAYS SINCE LAST GAME",
    typeof data.days_since_last_game === "number" ? String(data.days_since_last_game) : null));
  col.appendChild(factRow("GAMES · LAST 7 DAYS",
    typeof data.games_last_7 === "number" ? String(data.games_last_7) : null));
  if (data.last_venue) col.appendChild(factRow("LAST VENUE", String(data.last_venue)));
  const chips = el("div", { class: "gs-chips" });
  if (data.long_trip === true) chips.appendChild(warnChip("LONG TRIP"));
  if (data.dense_stretch === true) chips.appendChild(warnChip("DENSE STRETCH"));
  if (chips.childNodes.length) col.appendChild(chips);
  if (data.reason) col.appendChild(el("p", { class: "gs-note", text: String(data.reason) }));
  return col;
}

function renderTravel(advanced, quick) {
  const section = readSection(advanced, "travel");
  if (!section) return null;
  const panel = el("section", { class: "gs-panel panel chamfer", "data-hook": "gs-travel" });
  panel.appendChild(panelHead("TRAVEL & REST"));
  const cols = el("div", { class: "gs-cols" });
  cols.appendChild(travelColumn(quick.away_team, section[quick.away_team]));
  cols.appendChild(travelColumn(quick.home_team, section[quick.home_team]));
  panel.appendChild(cols);
  return panel;
}

/* =====================================================================
 * CONDITIONS -- weather + park. Rendered only when `weather` is present;
 * `park` is folded in as supplementary rows on the same panel rather than
 * a seventh panel of its own, since roof/altitude alone do not carry a
 * game story without the weather reading beside them.
 * ===================================================================*/

const COMPASS = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
  "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"];

function compassWord(deg) {
  if (typeof deg !== "number" || !Number.isFinite(deg)) return null;
  const normalized = ((deg % 360) + 360) % 360;
  return COMPASS[Math.round(normalized / 22.5) % 16];
}

function renderConditions(advanced) {
  const weather = readSection(advanced, "weather");
  if (!weather) return null;
  const park = readSection(advanced, "park");
  const panel = el("section", { class: "gs-panel panel chamfer", "data-hook": "gs-conditions" });
  panel.appendChild(panelHead("CONDITIONS"));

  const grid = el("div", { class: "gs-stats" });
  grid.appendChild(statCell("TEMP", typeof weather.temp_f === "number" ? `${weather.temp_f.toFixed(0)}°F` : null, null));
  const windWord = compassWord(weather.wind_from_deg);
  const windText = typeof weather.wind_mph === "number"
    ? `${weather.wind_mph.toFixed(0)} MPH${windWord ? ` ${windWord}` : ""}`
      + `${typeof weather.wind_from_deg === "number" ? ` (${Math.round(weather.wind_from_deg)}°)` : ""}`
    : null;
  grid.appendChild(statCell("WIND", windText, null));
  grid.appendChild(statCell("PRECIP CHANCE",
    typeof weather.precip_probability_pct === "number" ? `${weather.precip_probability_pct}%` : null, null));
  grid.appendChild(statCell("HUMIDITY",
    typeof weather.humidity_pct === "number" ? `${weather.humidity_pct}%` : null, null));
  if (park) {
    grid.appendChild(statCell("ROOF", park.roof ? String(park.roof).toUpperCase() : null, null));
    grid.appendChild(statCell("ALTITUDE", typeof park.altitude_m === "number" ? `${park.altitude_m} M` : null, null));
  }
  panel.appendChild(grid);

  const hrs = weather.hours_from_first_pitch;
  if (typeof hrs === "number" && Number.isFinite(hrs)) {
    const absHrs = Math.abs(hrs);
    const when = hrs >= 0 ? "before first pitch" : "after first pitch";
    const amount = absHrs < 1 ? `${Math.round(absHrs * 60)} min` : `${absHrs.toFixed(1)} hr`;
    panel.appendChild(el("p", { class: "gs-note", text: `Forecast captured ${amount} ${when}.` }));
  }
  return panel;
}

/* =====================================================================
 * ENTRY POINT
 * ===================================================================*/

/** Builds the GAME STORY block from this game's `advanced.sections`, or
 * returns `null` when none of the five sections it covers are present
 * (an entirely dark night for this game's story -- the Advanced view's
 * own gap ledger already explains why, so this file adds nothing). */
export function renderGameStory(advanced, quick) {
  const panels = [
    renderStarters(advanced, quick),
    renderBullpen(advanced, quick),
    renderLineups(advanced, quick),
    renderTravel(advanced, quick),
    renderConditions(advanced),
  ].filter(Boolean);
  if (!panels.length) return null;

  const wrap = el("section", { class: "gs-story", "data-hook": "game-story", "data-rise": "" });
  wrap.appendChild(el("h2", { class: "gs-story__head", text: "GAME STORY" }));
  const grid = el("div", { class: "gs-grid" });
  for (const panel of panels) grid.appendChild(panel);
  wrap.appendChild(grid);
  return wrap;
}
