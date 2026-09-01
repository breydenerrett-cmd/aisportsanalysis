/**
 * The angled slate tile -- handoff section 04's "angled tile
 * specification" and section 05's slate-tile anatomy, shared by the
 * Gameday rail and the Games grid so the two can never drift.
 *
 * 298x214 desktop / 226x172 mobile, chamfer R=18-20, diagonal team
 * blocking, carbon + scanline overlays, top sheen, bottom scrim, bracket
 * ticks top-left and bottom-right, one status flag top-right, the
 * matchup at 40px italic 800, both prices in mono separated by a 1px
 * rule, first pitch in cyan mono plus the venue in Barlow 600.
 *
 * PRICES: rendered only when the board actually quoted them. A game with
 * no priced board gets a sentence, never a zero and never an em-dash
 * grid (handoff section 10: "if there is no number, there is a
 * sentence").
 */

import { el, formatAmerican, formatEasternClock } from "./dom.js";
import { teamColors, seamGradient } from "./teamcolors.js";

/**
 * @param {object} game  {date, away_team, home_team, first_pitch_utc, venue}
 * @param {object} opts  {awayPrice, homePrice, flag: {text, kind}, feature}
 *   `kind` is one of "money" | "live" | "neutral" -- and money is
 *   RESERVED: pass it only where a better price genuinely exists.
 */
export function slateTile(game, opts = {}) {
  const away = game.away_team;
  const home = game.home_team;
  const awayC = teamColors(away);
  const homeC = teamColors(home);

  const href = `#/game/${encodeURIComponent(game.date)}/${encodeURIComponent(away)}/${encodeURIComponent(home)}`;
  const tile = el("a", {
    href,
    class: `tile chamfer${opts.feature ? " tile--feature" : ""}`,
    "data-hook": "slate-tile",
    "data-game-id": game.game_id || "",
    "data-tile": "",
    "data-delay": String(opts.delay || 0),
    "aria-label": `${away} at ${home}`,
  });
  tile.setAttribute("style",
    `--team-a:${seamGradient(away, 150)};--team-b:${seamGradient(home, 210)}`);

  tile.appendChild(el("span", { class: "tile__half tile__half--a" }));
  tile.appendChild(el("span", { class: "tile__half tile__half--b" }));
  tile.appendChild(el("span", { class: "tex-carbon" }));
  tile.appendChild(el("span", { class: "tex-scanline" }));
  tile.appendChild(el("span", { class: "tile__spec" }));
  tile.appendChild(el("span", { class: "tile__sheen" }));
  tile.appendChild(el("span", { class: "tile__scrim" }));
  tile.appendChild(el("span", { class: "tile__ring" }));
  tile.appendChild(el("span", { class: "tile__corner tile__corner--tl" }));
  tile.appendChild(el("span", { class: "tile__corner tile__corner--br" }));

  if (opts.flag && opts.flag.text) {
    const kind = opts.flag.kind === "money" ? "badge--money"
      : opts.flag.kind === "live" ? "badge--live" : "badge--neutral";
    tile.appendChild(el("span", {
      class: `tile__flag badge chamfer chamfer--chip ${kind}`,
      "data-hook": "tile-flag", text: opts.flag.text,
    }));
  }

  const teams = el("span", { class: "tile__teams" });
  teams.appendChild(el("span", { class: "tile__abbr", text: away,
    style: `color:${awayC.known ? awayC.accent : "#F2F4F8"}` }));
  teams.appendChild(el("span", { class: "tile__at", text: "AT" }));
  teams.appendChild(el("span", { class: "tile__abbr", text: home,
    style: `color:${homeC.known ? homeC.accent : "#F2F4F8"}` }));
  tile.appendChild(teams);

  const awayText = formatAmerican(opts.awayPrice);
  const homeText = formatAmerican(opts.homePrice);
  if (awayText !== null && homeText !== null) {
    const prices = el("span", { class: "tile__prices", "data-hook": "tile-prices" });
    prices.appendChild(el("span", { class: "tile__price", text: awayText }));
    prices.appendChild(el("span", { class: "tile__price-rule" }));
    prices.appendChild(el("span", { class: "tile__price tile__price--muted", text: homeText }));
    tile.appendChild(prices);
  } else {
    tile.appendChild(el("span", { class: "tile__noprice", "data-hook": "tile-no-price",
      text: "No price on the board yet." }));
  }

  const foot = el("span", { class: "tile__foot" });
  const clock = formatEasternClock(game.first_pitch_utc);
  if (clock) foot.appendChild(el("span", { class: "tile__time", text: clock }));
  if (game.venue) foot.appendChild(el("span", { class: "tile__venue", text: game.venue }));
  tile.appendChild(foot);

  return tile;
}
