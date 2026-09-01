/**
 * GAMES view -- GET /games/{date} (slate list), GET
 * /game/{date}/{away}/{home} (one game's quick + advanced views), both
 * from api/games.py. `sections`/`gaps` on the advanced view are, like
 * /today's `dossier`, not yet a stable per-field contract, so they render
 * through dom.renderUnknown.
 */

import { apiGet } from "./api.js";
import { el, clear, renderUnknown, renderError } from "./dom.js";
import { renderStaleness } from "./meta.js";

function todayIso() {
  return new Date().toISOString().slice(0, 10);
}

function renderDataQuality(dq) {
  const dl = el("dl", { class: "data-quality", "data-hook": "data-quality" });
  if (!dq) {
    dl.appendChild(el("dt", { text: "Data quality" }));
    dl.appendChild(el("dd", {}, [renderUnknown(null)]));
    return dl;
  }
  for (const key of ["has_market", "has_lineups", "has_starters", "has_price_board"]) {
    dl.appendChild(el("dt", { text: key }));
    dl.appendChild(el("dd", {}, [renderUnknown(dq[key])]));
  }
  dl.appendChild(el("dt", { text: "gaps" }));
  dl.appendChild(el("dd", { "data-hook": "data-quality-gaps" }, [renderUnknown(dq.gaps)]));
  return dl;
}

export async function renderGamesList(container, date) {
  clear(container);
  const useDate = date || todayIso();
  const section = el("section", { class: "games-view", "data-view": "games" });
  section.appendChild(el("h1", { text: "Games" }));

  const form = el("form", { class: "games-date-form", "data-hook": "games-date-form" });
  const label = el("label", { for: "games-date-input", text: "Date" });
  const input = el("input", { type: "date", id: "games-date-input", value: useDate,
    name: "date", "data-hook": "games-date-input" });
  form.appendChild(label);
  form.appendChild(input);
  form.appendChild(el("button", { type: "submit", text: "Load slate" }));
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    window.location.hash = `#/games/${input.value}`;
  });
  section.appendChild(form);
  container.appendChild(section);

  let payload;
  try {
    payload = await apiGet(`/games/${encodeURIComponent(useDate)}`);
  } catch (err) {
    renderError(container, err);
    return;
  }

  section.appendChild(el("p", { class: "games-view__date", "data-hook": "games-date",
    text: `Date: ${payload.date}` }));
  section.appendChild(el("p", { class: "games-view__checked", "data-hook": "checked-games",
    text: `Checked games: ${payload.checked_games}` }));

  const notesList = el("ul", { class: "games-view__notes", "data-hook": "games-notes" });
  for (const note of payload.notes || []) notesList.appendChild(el("li", { text: note }));
  section.appendChild(notesList);

  const rows = payload.games || [];
  const table = el("table", { class: "games-board", "data-hook": "games-board" });
  const caption = el("caption", { text: `Slate for ${payload.date}` });
  table.appendChild(caption);
  const thead = el("thead");
  const headRow = el("tr");
  for (const label of ["Matchup", "First pitch", "Venue", "Verdict",
    "Market-implied consensus", "Board", "Data quality"]) {
    headRow.appendChild(el("th", { scope: "col", text: label }));
  }
  thead.appendChild(headRow);
  table.appendChild(thead);

  const tbody = el("tbody");
  if (rows.length === 0) {
    const emptyRow = el("tr");
    emptyRow.appendChild(el("td", { colspan: "7", text: "No games on this slate." }));
    tbody.appendChild(emptyRow);
  }
  for (const row of rows) {
    const tr = el("tr", { class: "games-board__row", "data-hook": "games-row",
      "data-game-id": row.game_id });
    const matchupCell = el("td", { class: "games-board__matchup" });
    const link = el("a", {
      href: `#/game/${encodeURIComponent(payload.date)}/${encodeURIComponent(row.away_team)}/${encodeURIComponent(row.home_team)}`,
      "data-hook": "game-link",
      text: `${row.away_team} @ ${row.home_team}`,
    });
    matchupCell.appendChild(link);
    tr.appendChild(matchupCell);
    tr.appendChild(el("td", {}, [row.first_pitch_utc || renderUnknown(null)]));
    tr.appendChild(el("td", {}, [row.venue || renderUnknown(null)]));
    tr.appendChild(el("td", { "data-hook": "verdict", text: row.verdict }));
    tr.appendChild(el("td", {}, [renderUnknown(row.market_implied_consensus)]));
    tr.appendChild(el("td", {}, [renderStaleness(row.board_summary)]));
    tr.appendChild(el("td", {}, [renderDataQuality(row.data_quality)]));
    tbody.appendChild(tr);
  }
  table.appendChild(tbody);
  section.appendChild(table);
}

function renderQuick(quick) {
  const section = el("section", { class: "game-quick", "data-hook": "game-quick" });
  section.appendChild(el("h2", { text: "Quick view" }));
  section.appendChild(el("h3", { text: `${quick.away_team} @ ${quick.home_team}` }));
  const dl = el("dl", { class: "game-quick__fields" });
  for (const [label, value] of [
    ["Verdict", quick.verdict], ["Side", quick.side], ["Market", quick.market],
    ["Summary", quick.summary], ["Headline", quick.headline],
  ]) {
    dl.appendChild(el("dt", { text: label }));
    dl.appendChild(el("dd", {}, [value || renderUnknown(null)]));
  }
  section.appendChild(dl);

  const findings = el("section", { class: "game-quick__findings", "data-hook": "top-findings" });
  findings.appendChild(el("h3", { text: "Top findings" }));
  findings.appendChild(renderUnknown(quick.top_findings));
  section.appendChild(findings);

  const price = el("section", { class: "game-quick__price", "data-hook": "price" });
  price.appendChild(el("h3", { text: "Price" }));
  price.appendChild(renderUnknown(quick.price));
  section.appendChild(price);

  return section;
}

function renderAdvanced(advanced) {
  const details = el("details", { class: "game-advanced", "data-hook": "game-advanced" });
  details.appendChild(el("summary", { text: "Show advanced analysis" }));
  const dl = el("dl", { class: "game-advanced__fields" });
  dl.appendChild(el("dt", { text: "Information time" }));
  dl.appendChild(el("dd", { "data-hook": "information-time" }, [advanced.information_time || renderUnknown(null)]));
  dl.appendChild(el("dt", { text: "Verdict" }));
  dl.appendChild(el("dd", {}, [advanced.verdict || renderUnknown(null)]));
  details.appendChild(dl);

  const sections = el("section", { class: "game-advanced__sections", "data-hook": "advanced-sections" });
  sections.appendChild(el("h3", { text: "Sections" }));
  sections.appendChild(renderUnknown(advanced.sections));
  details.appendChild(sections);

  const gaps = el("section", { class: "game-advanced__gaps", "data-hook": "advanced-gaps" });
  gaps.appendChild(el("h3", { text: "Gaps" }));
  gaps.appendChild(renderUnknown(advanced.gaps));
  details.appendChild(gaps);

  const findings = el("section", { class: "game-advanced__findings", "data-hook": "advanced-findings" });
  findings.appendChild(el("h3", { text: "Findings" }));
  findings.appendChild(renderUnknown(advanced.findings));
  details.appendChild(findings);

  details.appendChild(renderStaleness(advanced.staleness));
  return details;
}

export async function renderGameDetail(container, date, away, home) {
  clear(container);
  const section = el("section", { class: "game-detail", "data-view": "game" });
  section.appendChild(el("h1", { text: `${away} @ ${home}` }));
  section.appendChild(el("a", { href: `#/games/${encodeURIComponent(date)}`,
    class: "game-detail__back", text: "Back to slate" }));
  container.appendChild(section);

  let payload;
  try {
    payload = await apiGet(
      `/game/${encodeURIComponent(date)}/${encodeURIComponent(away)}/${encodeURIComponent(home)}`);
  } catch (err) {
    renderError(container, err);
    return;
  }

  section.appendChild(renderQuick(payload.quick));
  section.appendChild(renderAdvanced(payload.advanced));

  const betCheckLink = el("a", {
    href: `#/betcheck?date=${encodeURIComponent(date)}&away=${encodeURIComponent(away)}&home=${encodeURIComponent(home)}`,
    class: "game-detail__bet-check-link", "data-hook": "go-to-bet-check",
    text: "Check a bet on this game",
  });
  section.appendChild(betCheckLink);
}
