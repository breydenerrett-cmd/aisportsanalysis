/**
 * Tennis research board: matches per tournament with de-vigged consensus.
 *
 * Displays the board for a date, grouped by tournament. Each match shows
 * players, time in the viewer's local timezone, the likelier side and its
 * de-vigged consensus probability (when 6+ books quoted), and the book count.
 * No bets, no picks. Research only.
 */

import { apiGet } from "./api.js";
import { el, clear, formatLocalClock, formatLocalDate, formatSlateDate } from "./dom.js";
import { renderLoading, renderError } from "./states.js";

/** Fetch and render the tennis board for a date. */
export async function renderTennisBoard(main) {
  clear(main);

  // Show loading state
  main.appendChild(renderLoading());

  const today = new Date().toISOString().split("T")[0];
  const dateParam = today;

  try {
    const payload = await apiGet(`/tennis/board?date=${dateParam}`, { timeoutMs: 20000 });

    clear(main);

    // Render the page structure. `gutter` (app.css: 40px desktop, 16px
    // phone) -- without it the board sat flush against the screen edge on
    // a phone, against DESIGN_SYSTEM.md section 7's 16px gutter rule
    // (seen at 375px on 2026-09-20, the first time this page was routed).
    const container = el("div", { class: "tennis-board gutter" });

    // Notice first
    const notice = el("p", {
      class: "tennis-board__notice",
      text: payload.notice || "Research only. No tennis picks until results grading is connected.",
    });
    container.appendChild(notice);

    // Date heading
    const dateHeading = el("h2", {
      class: "tennis-board__date-heading",
      text: `${formatSlateDate(payload.date) || payload.date || ""}`,
    });
    container.appendChild(dateHeading);

    // Tournaments list
    const tournaments = payload.tournaments || [];
    if (tournaments.length === 0) {
      container.appendChild(emptyBoard(payload));
    } else {
      for (const tournament of tournaments) {
        const tournamentSection = renderTournament(tournament);
        container.appendChild(tournamentSection);
      }
    }

    main.appendChild(container);
  } catch (err) {
    // renderError(container, err) renders INTO the container and returns
    // nothing. This used to call main.appendChild(renderError(err)), which
    // handed the error object in as the container, threw a TypeError
    // inside this catch, and left the page blank on every failure -- a
    // missing invite token (401), a 5xx, a timeout (2026-09-20).
    clear(main);
    renderError(main, err);
  }
}

/** The empty board, saying which kind of empty it is (2026-09-20).
 *
 * "No tennis matches are priced for this date" was a sentence about the
 * market, and it was false: tennis capture was halted from 2026-09-16 by a
 * probe deadlock, so the store held no tennis prices at all while books
 * were pricing WTA matches. The payload's `captured_any` says whether ANY
 * tennis price has been captured; each sentence below only states what we
 * have on file, never what the books are doing. */
function emptyBoard(payload) {
  if (payload.captured_any === false) {
    return el("p", {
      class: "tennis-board__empty",
      "data-hook": "tennis-board-none-captured",
      text: "No tennis prices have been captured yet, so there is nothing to show for any date. "
          + "This board fills in as prices are captured.",
    });
  }
  let text = "We have no captured prices for a tennis match on this date.";
  const last = payload.last_captured_utc;
  const when = last ? [formatLocalDate(last), formatLocalClock(last)].filter(Boolean).join(" ") : "";
  if (when) text += ` The newest tennis prices on file were captured ${when}.`;
  return el("p", { class: "tennis-board__empty", "data-hook": "tennis-board-none-for-date", text });
}

/** Render one tournament section with its matches. */
function renderTournament(tournament) {
  const section = el("section", { class: "tennis-tournament" });

  // Tournament title
  const title = el("h3", {
    class: "tennis-tournament__title",
    text: tournament.title || tournament.key || "Unknown Tournament",
  });
  section.appendChild(title);

  // Matches
  const matchList = el("div", { class: "tennis-tournament__matches" });
  const matches = tournament.matches || [];
  for (const match of matches) {
    const matchRow = renderMatch(match);
    matchList.appendChild(matchRow);
  }
  section.appendChild(matchList);

  return section;
}

/** Render one match row. */
function renderMatch(match) {
  const row = el("div", { class: "tennis-match" });

  // Player names
  const playerA = match.player_a || "Player A";
  const playerB = match.player_b || "Player B";
  const players = el("span", {
    class: "tennis-match__players",
    text: `${playerA} vs ${playerB}`,
  });
  row.appendChild(players);

  // Time in viewer's local timezone
  const timeStr = formatLocalClock(match.commence_time);
  if (timeStr) {
    const time = el("span", {
      class: "tennis-match__time",
      text: timeStr,
    });
    row.appendChild(time);
  }

  // Probability and books
  const books = match.books || 0;
  let probabilityStr = "";

  if (match.probability !== null && match.probability !== undefined && books >= 6) {
    const side = match.likelier === "a" ? playerA : playerB;
    const pct = Math.round(match.probability * 100);
    probabilityStr = `market leans ${side} (${pct}%), ${books} books`;
  } else if (books > 0) {
    probabilityStr = `not enough books yet (${books})`;
  } else {
    probabilityStr = "no quotes available";
  }

  const probability = el("span", {
    class: "tennis-match__probability",
    text: probabilityStr,
  });
  row.appendChild(probability);

  return row;
}
