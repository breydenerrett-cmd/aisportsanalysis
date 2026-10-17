/**
 * THE NFL BRIEF on the page -- one self-contained module: the fetch and the page.
 *
 * It is the MLB analyst's page code (analyst.js) for football, built on it: the section is drawn by
 * `renderAnalystSection`, so a PASS looks exactly like a TAKE and the case against, the derivations,
 * what the brief could not use and the label are the same words in the same places.
 *
 *   fetchNflAnalyst(date, away, home)   GET /analyst/nfl/{date}/{away}/{home}; a failure is null,
 *                                       never an error page.
 *   renderNflBrief(container, date, away, home)
 *                                       the page behind #/nfl/brief/{date}/{away}/{home}: who is
 *                                       playing, then the brief, or the plain reason there is none.
 *
 * WHERE THE NFL GAME VIEW LIVES. It does not: the NFL has a card (#/nfl, card.js) and a record, and
 * "NFL has no game page" is written in card.js on purpose (an MLB link on an NFL pick opened a 404).
 * This is the NFL's first per-game page, reached by its address. It is the page the public sample
 * brief points a reader at when the designated game is an NFL one (sample.js).
 *
 * WHAT THIS PAGE MUST NEVER DO (analyst.js's rules, unchanged)
 * -------------------------------------------------------------------
 * - Make a pass look smaller than a take, drop the label, or show a call the checker could not
 *   verify as though it were analysis. All of that is `renderAnalystSection`'s, called as is.
 * - Write its own label. The server sends the supervised-session label; the page prints it.
 * - Call a model, compute a price or re-derive anything. It reads what the ledger froze before
 *   kickoff.
 */

import { apiGet } from "./api.js";
import { el, clear, formatEasternClock } from "./dom.js";
import { renderAnalystSection } from "./analyst.js";

/** The fetch the page needs. A failure is an absent brief, never an error page. */
export async function fetchNflAnalyst(date, away, home) {
  try {
    return await apiGet(
      `/analyst/nfl/${encodeURIComponent(date)}/${encodeURIComponent(away)}/${encodeURIComponent(home)}`);
  } catch (err) {
    return null;
  }
}

/** The line that says which game this is and when it starts. */
export function gameHeading(date, away, home, analysis) {
  const kick = analysis && analysis.first_pitch_utc ? formatEasternClock(analysis.first_pitch_utc) : null;
  return `${away} at ${home}, ${date}${kick ? ` (kickoff ${kick})` : ""}`;
}

export async function renderNflBrief(container, date, away, home) {
  clear(container);
  const screen = el("div", { class: "screen", "data-view": "nfl-brief" });
  container.appendChild(screen);
  screen.appendChild(el("a", { class: "gqv-back", href: "#/nfl", "data-hook": "nfl-brief-back",
    text: "← BACK TO NFL GAMEDAY" }));
  const data = await fetchNflAnalyst(date, away, home);
  const analysis = data && data.analysis;
  screen.appendChild(el("h2", { class: "an-family__head", "data-hook": "nfl-brief-heading",
    text: gameHeading(date, away, home, analysis) }));
  screen.appendChild(renderAnalystSection(data || { available: false, analysis: null,
    reason: "The brief could not be loaded." }));
  return screen;
}
