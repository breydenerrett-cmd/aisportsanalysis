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
  const section = el("section", { class: "odds-view view", "data-view": "odds" });
  section.appendChild(el("h1", { class: "view__title", text: "Odds" }));

  const form = el("form", { class: "odds-date-form field-form panel chamfer", "data-hook": "odds-date-form" });
  const row0 = el("p", { class: "field-row" });
  row0.appendChild(el("label", { for: "odds-date-input", text: "Date" }));
  const input = el("input", { type: "date", id: "odds-date-input", value: useDate,
    name: "date", "data-hook": "odds-date-input" });
  row0.appendChild(input);
  form.appendChild(row0);
  form.appendChild(el("button", { type: "submit", class: "btn btn--cyan", text: "Load board" }));
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    window.location.hash = `#/odds/${input.value}`;
  });
  section.appendChild(form);
  container.appendChild(section);

  const loading = el("div", { class: "state-loading panel chamfer", "data-hook": "view-loading" },
    [el("p", { class: "state-loading__figure", text: "Loading board…" })]);
  section.appendChild(loading);

  let payload;
  try {
    payload = await apiGet(`/odds/${encodeURIComponent(useDate)}`);
  } catch (err) {
    renderError(loading, err);
    return;
  }
  clear(loading);
  loading.remove();

  const meta = el("div", { class: "view__eyebrow-row" });
  meta.appendChild(el("p", { class: "eyebrow", "data-hook": "odds-date",
    text: `Date: ${payload.date}` }));
  meta.appendChild(el("time", { class: "eyebrow eyebrow--muted", "data-hook": "odds-generated-at",
    text: payload.generated_at }));
  section.appendChild(meta);

  if (payload.freshness) {
    section.appendChild(el("p", { class: "freshness-banner", "data-hook": "odds-freshness" },
      [renderUnknown(payload.freshness)]));
  }

  const summary = el("section", { class: "odds-summary panel chamfer", "data-hook": "odds-summary" });
  summary.appendChild(el("h2", { text: "Slate summary" }));
  summary.appendChild(renderUnknown(payload.summary));
  section.appendChild(summary);

  const scroll = el("div", { class: "board-scroll panel chamfer" });
  const table = el("table", { class: "odds-board board-table", "data-hook": "odds-board" });
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
    tr.appendChild(el("td", { colspan: "2" },
      [el("div", { class: "state-empty", "data-hook": "odds-empty" }, [
        el("p", { class: "state-empty__title", text: "No board to show yet." }),
        el("p", { class: "state-empty__body", text: "No games on this slate." }),
      ])]));
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
  scroll.appendChild(table);
  section.appendChild(scroll);
}

export async function renderOddsGame(container, date, away, home) {
  clear(container);
  const section = el("section", { class: "odds-game view", "data-view": "odds-game" });
  section.appendChild(el("h1", { class: "view__title", text: `${away} @ ${home} -- odds` }));
  section.appendChild(el("a", { href: `#/odds/${encodeURIComponent(date)}`,
    class: "odds-game__back", text: "Back to odds board" }));
  container.appendChild(section);

  const loading = el("div", { class: "state-loading panel chamfer", "data-hook": "view-loading" },
    [el("p", { class: "state-loading__figure", text: "Loading odds…" })]);
  section.appendChild(loading);

  let payload;
  try {
    payload = await apiGet(
      `/odds/${encodeURIComponent(date)}/${encodeURIComponent(away)}/${encodeURIComponent(home)}`);
  } catch (err) {
    renderError(loading, err);
    return;
  }
  clear(loading);
  loading.remove();

  if (payload.note) {
    section.appendChild(el("p", { class: "odds-game__note", "data-hook": "doubleheader-note",
      text: payload.note }));
  }

  const body = el("section", { class: "odds-game__body", "data-hook": "odds-game-body" });
  body.appendChild(renderUnknown(payload));
  section.appendChild(body);
}
