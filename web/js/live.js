/**
 * Live game states and research candidates.
 *
 * Internal testing surface (#/live?sport=mlb or #/live?sport=nfl).
 * Displays live game scores and research candidates that are evaluated but
 * never placed as selections on the card.
 *
 * BANNER NOTICE
 * Renders a fixed sentence: "Live analysis is in internal testing. No alerts
 * are sent." — the same sentence every contract delivers, rendered verbatim
 * from the API payload.
 *
 * SPORT TABS
 * Reads sport from the hash query (?sport=mlb or ?sport=nfl). Defaults to
 * "mlb". Clicking a tab rewrites the hash to switch the active sport.
 *
 * POLLER STATUS
 * Reads poller.status and renders it in plain words:
 *   - "live": "Live data is 40 seconds old."
 *   - "stale": "Live data is stale."
 *   - "idle": "No games are live right now."
 *
 * GAMES
 * Plain list: "Yankees 3, Red Sox 2, top of the 6th" etc. No links to place
 * bets. Empty state when no games.
 *
 * RESEARCH CANDIDATES
 * Each row shows: rule name (from a static map), bet text, price, time,
 * and a fixed chip "research, not a pick". Empty state when no candidates.
 *
 * CUSTOMER LANGUAGE
 * Must pass tests/test_customer_language.py and the vocabulary sweep in
 * tests/test_web_structure.py: plain words only, nothing that promises an
 * outcome or names a model's number.
 */

import { apiGet, ApiError } from "./api.js";
import { el, clear, renderError, renderLoading, formatEasternClock } from "./dom.js";
import { renderEmptySlate } from "./states.js";
import { setShellStatus } from "./shell.js";

// Rule id -> plain sentence. The ids are the three pre-registered LIVE_V0
// rules in src/analysis/live_rules.py (docs/PREREG_MULTI_SPORT_2026-09-14.md);
// an id this map does not know is shown with its underscores replaced.
const RULE_DESCRIPTIONS = {
  "mlb_favorite_trails_after_3": "Favourite behind after three innings",
  "mlb_starter_pulled_early": "Favourite's starter pulled before the fifth",
  "nfl_favorite_trails_halftime": "Favourite behind around halftime",
};

function ruleDescription(ruleId) {
  return RULE_DESCRIPTIONS[ruleId] || (ruleId ? ruleId.replace(/_/g, " ") : "Research candidate");
}

/**
 * Parse the sport from the hash query string.
 * Hash format: #/live or #/live?sport=nfl
 * Defaults to "mlb".
 */
function parseSportFromQuery() {
  const hash = window.location.hash;
  const queryIdx = hash.indexOf("?");
  if (queryIdx < 0) return "mlb";

  const query = new URLSearchParams(hash.substring(queryIdx + 1));
  const sport = query.get("sport");
  return (sport === "nfl" || sport === "mlb") ? sport : "mlb";
}

/**
 * Create sport tab buttons.
 */
function renderSportTabs(activeSport, onSportChange) {
  const container = el("div", { class: "live-sport-tabs" });

  for (const sport of ["mlb", "nfl"]) {
    const btn = el("button", {
      class: `live-sport-tab ${sport === activeSport ? "live-sport-tab--active" : ""}`,
      text: sport.toUpperCase(),
    });
    btn.addEventListener("click", () => {
      window.location.hash = `#/live?sport=${sport}`;
      if (typeof onSportChange === "function") onSportChange(sport);
    });
    container.appendChild(btn);
  }

  return container;
}

/**
 * Render the poller status line.
 */
function renderPollerStatus(poller) {
  if (!poller) return el("div", { text: "Status unknown." });

  const status = poller.status;
  const ageSeconds = poller.last_observed_utc
    ? Math.floor((new Date() - new Date(poller.last_observed_utc)) / 1000)
    : null;

  let statusText = "Status unknown.";
  if (status === "live" && ageSeconds !== null) {
    const ageStr = ageSeconds < 60 ? "seconds" : "minutes";
    statusText = `Live data is ${ageSeconds} ${ageStr} old.`;
  } else if (status === "stale") {
    statusText = "Live data is stale.";
  } else if (status === "idle") {
    statusText = "No games are live right now.";
  }

  return el("div", { class: "live-status", text: statusText });
}

/**
 * Render a single game row.
 */
function renderGameRow(game) {
  const row = el("div", { class: "live-game-row" });

  // Score + status
  const scoreText = game.score || `${game.away_team} vs ${game.home_team}`;
  const statusText = game.inning || game.quarter || game.status || "";
  const desc = statusText ? `${scoreText}, ${statusText}` : scoreText;

  row.appendChild(el("span", { class: "live-game-desc", text: desc }));

  // Updated time
  if (game.observed_utc) {
    const clock = formatEasternClock(game.observed_utc);
    if (clock) {
      row.appendChild(el("span", { class: "live-game-time", text: clock }));
    }
  }

  return row;
}

/**
 * Render a single candidate row.
 */
function renderCandidateRow(candidate) {
  const row = el("div", { class: "live-candidate-row" });

  // Rule description
  const ruleLabel = ruleDescription(candidate.rule_id);
  row.appendChild(el("div", { class: "live-candidate-rule", text: ruleLabel }));

  // Bet text + price
  const betLine = candidate.bet || "Research candidate";
  const price = candidate.price !== undefined && candidate.price !== null
    ? ` (${candidate.price > 0 ? "+" : ""}${candidate.price})`
    : "";
  row.appendChild(el("div", { class: "live-candidate-bet", text: betLine + price }));

  // Time
  if (candidate.observed_utc) {
    const clock = formatEasternClock(candidate.observed_utc);
    if (clock) {
      row.appendChild(el("span", { class: "live-candidate-time", text: clock }));
    }
  }

  // Chip: "research, not a pick"
  row.appendChild(el("span", { class: "live-candidate-chip badge badge--outline", text: "research, not a pick" }));

  return row;
}

/**
 * Main render function.
 */
export async function renderLive(main) {
  clear(main);

  const sport = parseSportFromQuery();

  // Loading state
  const loading = renderLoading();
  main.appendChild(loading);

  setShellStatus("Loading live data…");

  try {
    const payload = await apiGet(`/live?sport=${sport}`);

    clear(main);

    // Container
    const container = el("div", { class: "live-container" });

    // Sport tabs
    container.appendChild(renderSportTabs(sport, () => {
      renderLive(main);  // Re-render with new sport
    }));

    // Banner notice
    if (payload.notice) {
      container.appendChild(el("div", { class: "live-notice", text: payload.notice }));
    }

    // Poller status line
    if (payload.poller) {
      container.appendChild(renderPollerStatus(payload.poller));
    }

    // Games section
    const gamesList = payload.games || [];
    if (gamesList.length > 0) {
      const gamesSection = el("div", { class: "live-section" });
      gamesSection.appendChild(el("h3", { class: "live-section-title", text: "LIVE GAMES" }));

      for (const game of gamesList) {
        gamesSection.appendChild(renderGameRow(game));
      }

      container.appendChild(gamesSection);
    } else {
      container.appendChild(renderEmptySlate({
        eyebrow: "NO LIVE GAMES",
        headline: "No games are live right now.",
        body: "Check back during game hours.",
      }));
    }

    // Candidates section
    const candidatesList = payload.candidates || [];
    if (candidatesList.length > 0) {
      const candidatesSection = el("div", { class: "live-section" });
      candidatesSection.appendChild(el("h3", { class: "live-section-title", text: "RESEARCH CANDIDATES" }));

      for (const candidate of candidatesList) {
        candidatesSection.appendChild(renderCandidateRow(candidate));
      }

      container.appendChild(candidatesSection);
    } else if (gamesList.length > 0) {
      // Only show "no candidates" if there are games
      container.appendChild(renderEmptySlate({
        eyebrow: "NO CANDIDATES",
        headline: "No research candidates right now.",
        body: "Research opportunities appear during live play.",
      }));
    }

    main.appendChild(container);

    // Update status line
    if (payload.poller && payload.poller.status === "live") {
      setShellStatus("Live data received.");
    } else if (payload.poller && payload.poller.status === "stale") {
      setShellStatus("Live data is stale.");
    } else {
      setShellStatus("Ready.");
    }
  } catch (err) {
    // renderError(container, err) clears the container and paints the error
    // panel into it; it returns nothing. The first version called it with
    // the error alone and appended its return value, which threw
    // "container.appendChild is not a function" on every failed fetch --
    // so the one page whose job is to show an outage showed a spinner.
    const shown = err instanceof ApiError
      ? err
      : new ApiError(null, `Failed to load live data: ${err.message}`);
    renderError(main, shown);
    setShellStatus("Error loading live data.");
  }
}
