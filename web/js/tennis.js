/**
 * Tennis research board: matches per tournament with de-vigged consensus.
 *
 * Displays the board for a date, grouped by tournament. Each match shows
 * players, time in the viewer's local timezone, the likelier side and its
 * de-vigged consensus probability (when 6+ books quoted), and the book count.
 * No bets, no picks. Research only.
 */

import { apiGet } from "./api.js";
import { el, clear, formatLocalClock, formatSlateDate } from "./dom.js";
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

    // Render the page structure
    const container = el("div", { class: "tennis-board" });

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
      const emptyMsg = el("p", {
        class: "tennis-board__empty",
        text: "No tennis matches are priced for this date.",
      });
      container.appendChild(emptyMsg);
    } else {
      for (const tournament of tournaments) {
        const tournamentSection = renderTournament(tournament);
        container.appendChild(tournamentSection);
      }
    }

    main.appendChild(container);
  } catch (err) {
    clear(main);
    main.appendChild(renderError(err));
  }
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
