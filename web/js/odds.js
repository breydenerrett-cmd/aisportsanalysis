/**
 * ODDS view -- GET /odds/{date} (the whole slate's board) and GET
 * /odds/{date}/{away}/{home} (one game's), both from api/odds.py.
 *
 * The per-market board shape (src/analysis/oddspayload.py) is not pinned
 * field-by-field in docs/API_CONTRACTS.md the way /today, /games and
 * /betcheck are, so it renders through dom.renderUnknown rather than
 * assuming a shape this client has no contract test backing it against.
 */

import { apiGet } from "./api.js";
import { el, clear, renderUnknown, renderError } from "./dom.js";

function todayIso() {
  return new Date().toISOString().slice(0, 10);
}

export async function renderOdds(container, date) {
  clear(container);
  const useDate = date || todayIso();
  const section = el("section", { class: "odds-view", "data-view": "odds" });
  section.appendChild(el("h1", { text: "Odds" }));

  const form = el("form", { class: "odds-date-form", "data-hook": "odds-date-form" });
  const label = el("label", { for: "odds-date-input", text: "Date" });
  const input = el("input", { type: "date", id: "odds-date-input", value: useDate,
    name: "date", "data-hook": "odds-date-input" });
  form.appendChild(label);
  form.appendChild(input);
  form.appendChild(el("button", { type: "submit", text: "Load board" }));
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    window.location.hash = `#/odds/${input.value}`;
  });
  section.appendChild(form);
  container.appendChild(section);

  let payload;
  try {
    payload = await apiGet(`/odds/${encodeURIComponent(useDate)}`);
  } catch (err) {
    renderError(container, err);
    return;
  }

  section.appendChild(el("p", { class: "odds-view__date", "data-hook": "odds-date",
    text: `Date: ${payload.date}` }));
  section.appendChild(el("time", { class: "odds-view__generated", "data-hook": "odds-generated-at",
    text: payload.generated_at }));

  const summary = el("section", { class: "odds-summary", "data-hook": "odds-summary" });
  summary.appendChild(el("h2", { text: "Slate summary" }));
  summary.appendChild(renderUnknown(payload.summary));
  section.appendChild(summary);

  const table = el("table", { class: "odds-board", "data-hook": "odds-board" });
  table.appendChild(el("caption", { text: `Market board for ${payload.date}` }));
  const thead = el("thead");
  const headRow = el("tr");
  for (const label of ["Matchup", "Markets"]) headRow.appendChild(el("th", { scope: "col", text: label }));
  thead.appendChild(headRow);
  table.appendChild(thead);

  const tbody = el("tbody");
  const rows = payload.games || [];
  if (rows.length === 0) {
    const tr = el("tr");
    tr.appendChild(el("td", { colspan: "2", text: "No games on this slate." }));
    tbody.appendChild(tr);
  }
  for (const row of rows) {
    const tr = el("tr", { class: "odds-board__row", "data-hook": "odds-row",
      "data-game-id": row.game_id });
    const matchupCell = el("td");
    matchupCell.appendChild(el("a", {
      href: `#/odds/${encodeURIComponent(payload.date)}/${encodeURIComponent(row.away_team)}/${encodeURIComponent(row.home_team)}`,
      "data-hook": "odds-game-link",
      text: `${row.away_team} @ ${row.home_team}`,
    }));
    tr.appendChild(matchupCell);
    tr.appendChild(el("td", {}, [renderUnknown(row.markets)]));
    tbody.appendChild(tr);
  }
  table.appendChild(tbody);
  section.appendChild(table);
}

export async function renderOddsGame(container, date, away, home) {
  clear(container);
  const section = el("section", { class: "odds-game", "data-view": "odds-game" });
  section.appendChild(el("h1", { text: `${away} @ ${home} -- odds` }));
  section.appendChild(el("a", { href: `#/odds/${encodeURIComponent(date)}`,
    class: "odds-game__back", text: "Back to odds board" }));
  container.appendChild(section);

  let payload;
  try {
    payload = await apiGet(
      `/odds/${encodeURIComponent(date)}/${encodeURIComponent(away)}/${encodeURIComponent(home)}`);
  } catch (err) {
    renderError(container, err);
    return;
  }

  if (payload.note) {
    section.appendChild(el("p", { class: "odds-game__note", "data-hook": "doubleheader-note",
      text: payload.note }));
  }

  const body = el("section", { class: "odds-game__body", "data-hook": "odds-game-body" });
  body.appendChild(renderUnknown(payload));
  section.appendChild(body);
}
