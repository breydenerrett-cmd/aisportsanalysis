/**
 * LIVE GAME STATE -- GET /live/{date} (api/live_state.py), shown as one compact
 * strip on the Today slate tile and the game page, and the rule that goes with it.
 *
 * THE RULE THIS MODULE EXISTS FOR
 * -------------------------------------------------------------------
 * Once a game is in progress, delayed, final or postponed, every PREGAME price
 * the site shows for it is the LAST PRE-GAME price, not a current one. The boards
 * behind /odds and /game are built from pre-game captures only
 * (prices.boards_by_matchup filters to pre-game rows), so the number is honest --
 * what was dishonest was a page that printed it with nothing saying the game had
 * started. `pregameLabel(game, observedUtc)` is the one place that sentence is
 * built, so no surface words it its own way.
 *
 * FAIL SOFT, TWICE
 * -------------------------------------------------------------------
 * `fetchLiveIndex` resolves to null when the endpoint is down, unreachable, or
 * says `available: false`. Every caller treats null as "no live state": the page
 * renders exactly as it did before this module existed, with no strip and no
 * label. A missing live feed is never read as "every game is pregame" in text --
 * it is simply silent -- and never throws into the page.
 *
 * ONE REQUEST PER PAGE VIEW, NOT PER CONSUMER
 * -------------------------------------------------------------------
 * Several sections of one screen want the same slate's live state. The promise
 * for a date is shared for LIVE_TTL_MS, so the browser makes one request however
 * many sections ask, and the server (src/analysis/livestate.py) makes one
 * upstream call per slate per 45 seconds however many browsers do.
 */

import { apiGet } from "./api.js";
import { el, formatEasternClock } from "./dom.js";

export const LIVE_TTL_MS = 30000;

const cache = new Map(); // date -> { at, promise }

/** Test seam: forget every cached date. */
export function _resetLiveCache() {
  cache.clear();
}

/** The payload's games keyed by game_id, or null when live state is unavailable. */
export function liveIndexOf(payload) {
  if (!payload || payload.available !== true || !Array.isArray(payload.games)) return null;
  const index = new Map();
  for (const game of payload.games) {
    if (game && game.game_id) index.set(game.game_id, game);
  }
  return index;
}

/** Map(game_id -> live game) for a date, or null. Never rejects. */
export function fetchLiveIndex(date, { fetcher = apiGet, now = () => Date.now() } = {}) {
  const key = String(date || "");
  const hit = cache.get(key);
  if (hit && now() - hit.at < LIVE_TTL_MS) return hit.promise;
  const promise = Promise.resolve()
    .then(() => fetcher(`/live/${encodeURIComponent(key)}`))
    .then(liveIndexOf)
    .catch(() => null);
  cache.set(key, { at: now(), promise });
  return promise;
}

/** The live row for a game, or null. `index` may be null (feed unavailable). */
export function liveFor(index, gameId) {
  return (index && gameId && index.get(gameId)) || null;
}

/** The live row whose MLB game_pk matches, or null. For screens whose own game
 * object has the pk but not the game_id (the matchup grid's dossier). */
export function liveByPk(index, gamePk) {
  if (!index || gamePk === null || gamePk === undefined) return null;
  for (const game of index.values()) {
    if (String(game.game_pk) === String(gamePk)) return game;
  }
  return null;
}

/** True when the game is anything but pregame -- i.e. any pregame price shown
 * for it must carry the last-pregame label. */
export function pricesAreLastPregame(game) {
  return Boolean(game && game.status && game.status !== "pregame");
}

/** "LAST PRE-GAME PRICE · 6:41 PM PDT" -- or null while the game is pregame
 * (or live state is unavailable). The time is the board's own capture instant;
 * when it is unknown the label still says what the price is, without a time. */
export function pregameLabel(game, observedUtc) {
  if (!pricesAreLastPregame(game)) return null;
  const clock = formatEasternClock(observedUtc);
  return clock ? `LAST PRE-GAME PRICE · ${clock}` : "LAST PRE-GAME PRICE";
}

/** The tile's shorter wording of the same label: "LAST PRE-GAME · 6:41 PM PDT". */
export function pregameShortLabel(game, observedUtc) {
  if (!pricesAreLastPregame(game)) return null;
  const clock = formatEasternClock(observedUtc);
  return clock ? `LAST PRE-GAME · ${clock}` : "LAST PRE-GAME";
}

function score(game) {
  if (game.away_score === null || game.away_score === undefined
      || game.home_score === null || game.home_score === undefined) return null;
  return `${game.away_team} ${game.away_score} · ${game.home_team} ${game.home_score}`;
}

/** What the strip says, as plain data (testable without a DOM):
 * { kind, label, score, detail } or null while pregame / unavailable.
 * kind is the CSS state: live | delayed | final | off. */
export function liveStripModel(game) {
  if (!game || !game.status || game.status === "pregame") return null;
  const scoreText = score(game);
  if (game.status === "in_progress") {
    const parts = [];
    if (game.inning_text) parts.push(game.inning_text.toUpperCase());
    if (typeof game.outs === "number") parts.push(`${game.outs} OUT${game.outs === 1 ? "" : "S"}`);
    if (game.pitcher) parts.push(`P ${game.pitcher}`);
    return { kind: "live", label: "LIVE", score: scoreText, detail: parts.join(" · ") || null };
  }
  if (game.status === "delayed") {
    const parts = [];
    if (game.inning_text) parts.push(game.inning_text.toUpperCase());
    return { kind: "delayed", label: "DELAYED", score: scoreText,
      detail: [game.detailed_state, ...parts].filter(Boolean).join(" · ") || null };
  }
  if (game.status === "final") {
    return { kind: "final", label: "FINAL", score: scoreText, detail: null };
  }
  if (game.status === "postponed") {
    return { kind: "off", label: "POSTPONED", score: null, detail: game.detailed_state || null };
  }
  return null;
}

/** The compact live strip element, or null while pregame / unavailable. */
export function renderLiveStrip(game, { hook = "live-strip" } = {}) {
  const model = liveStripModel(game);
  if (!model) return null;
  const strip = el("div", { class: `live-strip live-strip--${model.kind}`, "data-hook": hook,
    "data-status": game.status, role: "status" });
  strip.appendChild(el("span", { class: "live-strip__label", text: model.label }));
  if (model.score) strip.appendChild(el("span", { class: "live-strip__score", text: model.score }));
  if (model.detail) strip.appendChild(el("span", { class: "live-strip__detail", text: model.detail }));
  return strip;
}

/** The slate tile's one-line version of the same thing, or null. */
export function tileLiveText(game) {
  const model = liveStripModel(game);
  if (!model) return null;
  return [model.label, model.score, model.kind === "live" ? game.inning_text && game.inning_text.toUpperCase() : null]
    .filter(Boolean).join(" · ");
}

/** The small label element for a pregame price on a started game, or null. */
export function renderPregameLabel(game, observedUtc, { hook = "pregame-label" } = {}) {
  const text = pregameLabel(game, observedUtc);
  if (!text) return null;
  return el("p", { class: "pregame-label", "data-hook": hook, text });
}
