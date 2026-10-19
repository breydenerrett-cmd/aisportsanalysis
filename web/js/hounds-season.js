/**
 * Seasons on the web pages: which window of bets the leaderboard, the model page and the landing board show.
 *
 * The server owns the numbers (GET /hounds?season=, src/hounds/seasons.py, config/seasons.json); this file only
 * picks WHICH season to ask for and words it. Nothing here measures anything.
 *
 *   - The choice is remembered in two places: the page URL (`?season=s2`, so a link shows what the sender saw)
 *     and localStorage (so a return visit keeps it). The URL wins. Every storage and history call is wrapped:
 *     a private window or blocked storage just means the choice is not remembered, never an error.
 *   - Season 2 (the newest) is the default everywhere. "all" is all-time. An id the server does not list falls
 *     back to the default.
 *   - A model needs MIN_RANKED_BETS settled bets in the selected view to be ranked there; the server sends the
 *     same number as `season.min_ranked_bets` and that value wins.
 */

import { isNum, shortDate, dayNumber } from "./hounds-core.js";

export const SEASON_PARAM = "season";
export const SEASON_STORAGE_KEY = "linehound.hounds.season";
export const DEFAULT_SEASON = "s2";
export const ALL_SEASON = "all";
export const MIN_RANKED_BETS = 10;        // mirrors src/hounds/seasons.py MIN_RANKED_BETS

/** Used until a payload names the seasons (and by a page that never gets one). */
export const FALLBACK_SEASONS = [
  { id: "s2", label: "Season 2", start: "2026-10-18", end: null },
  { id: "s1", label: "Season 1", start: "2026-08-31", end: "2026-10-17" },
  { id: ALL_SEASON, label: "All-time", start: null, end: null },
];

/** The switcher's choices, newest first, all-time last: [{ id, label, text, start, end }]. `meta` is a payload's `season` block. */
export function seasonOptions(meta) {
  const list = meta && Array.isArray(meta.available) && meta.available.length ? meta.available : FALLBACK_SEASONS;
  const seasons = list.filter((x) => x && x.id && x.id !== ALL_SEASON)
    .slice().sort((a, b) => String(b.start || "").localeCompare(String(a.start || "")));
  const out = seasons.map((x) => ({ ...x, text: x.end ? String(x.label || x.id) : `${x.label || x.id} (since ${shortDate(x.start) || "the start"})` }));
  out.push({ id: ALL_SEASON, label: "All-time", start: null, end: null, text: "All-time" });
  return out;
}

export function defaultSeason(meta) {
  const d = meta && typeof meta.default === "string" ? meta.default : DEFAULT_SEASON;
  return seasonOptions(meta).some((x) => x.id === d) ? d : seasonOptions(meta)[0].id;
}

/** `value` if it is one of the choices, else null. */
export function validSeason(value, meta) {
  const v = String(value === null || value === undefined ? "" : value).trim().toLowerCase();
  return v && seasonOptions(meta).some((x) => x.id === v) ? v : null;
}

export function readStoredSeason() {
  try {
    const store = typeof window !== "undefined" ? window.localStorage : null;
    return store ? store.getItem(SEASON_STORAGE_KEY) : null;
  } catch (err) {
    return null;
  }
}

/** The season to open on: the URL's `?season=`, else the remembered one, else the default. */
export function chooseSeason(meta) {
  let fromUrl = null;
  try {
    fromUrl = new URLSearchParams((typeof window !== "undefined" && window.location && window.location.search) || "").get(SEASON_PARAM);
  } catch (err) {
    fromUrl = null;
  }
  return validSeason(fromUrl, meta) || validSeason(readStoredSeason(), meta) || defaultSeason(meta);
}

/** Remember the choice: localStorage and the URL (`?season=`, the rest of the query kept). Returns the URL it wrote, or "". */
export function saveSeason(id) {
  try {
    if (typeof window !== "undefined" && window.localStorage) window.localStorage.setItem(SEASON_STORAGE_KEY, String(id));
  } catch (err) {
    /* private window or blocked storage: the choice is simply not remembered */
  }
  try {
    if (typeof window === "undefined" || !window.history || typeof window.history.replaceState !== "function") return "";
    const loc = window.location || {};
    const params = new URLSearchParams(loc.search || "");
    params.set(SEASON_PARAM, String(id));
    const url = `${loc.pathname || ""}?${params.toString()}${loc.hash || ""}`;
    window.history.replaceState(null, "", url);
    return url;
  } catch (err) {
    return "";
  }
}

/** "?season=s1" style query for an API path (the path carries its own `?` if it needs one). */
export function seasonParam(id) {
  return `${SEASON_PARAM}=${encodeURIComponent(String(id))}`;
}

/** The settled bets a model needs to be ranked in the view the payload describes. */
export function minRanked(meta) {
  return meta && isNum(meta.min_ranked_bets) && meta.min_ranked_bets > 0 ? meta.min_ranked_bets : MIN_RANKED_BETS;
}

/** The line above the table: what this view is and that a young model is not on a level footing. */
export function seasonLine(meta, id) {
  const opt = seasonOptions(meta).find((x) => x.id === id) || seasonOptions(meta)[0];
  if (opt.id === ALL_SEASON) {
    const firsts = seasonOptions(meta).filter((x) => x.start).map((x) => x.start).sort();
    return `All-time: every forward bet${firsts.length ? ` since ${shortDate(firsts[0])}` : ""}. Models that started later have fewer bets, so compare with care.`;
  }
  if (!opt.end) return `${opt.label} started ${shortDate(opt.start)}. Every model starts at zero.`;
  return `${opt.label} ran ${shortDate(opt.start)} to ${shortDate(opt.end)}. Models are measured on that window only.`;
}

/** Today's date in Pacific time as YYYY-MM-DD (the date the slates use); falls back to UTC if Intl is missing. */
export function pacificToday(now) {
  const at = now instanceof Date ? now : new Date();
  try {
    return new Intl.DateTimeFormat("en-CA", { timeZone: "America/Los_Angeles", year: "numeric", month: "2-digit", day: "2-digit" }).format(at);
  } catch (err) {
    return at.toISOString().slice(0, 10);
  }
}

/** "Season 2 is 2 days old" from a payload's season block and today's date; "" for all-time or a season not started. */
export function seasonAgeText(meta, today) {
  if (!meta || meta.all_time || !meta.start) return "";
  const days = dayNumber(today || pacificToday()) - dayNumber(meta.start) + 1;
  if (!isNum(days) || days < 1) return "";
  return `${meta.label || "This season"} is ${days} ${days === 1 ? "day" : "days"} old`;
}
