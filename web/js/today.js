/**
 * TODAY view -- GET /today (api/app.py; always today's server-side date,
 * see that route's docstring) plus GET /changed/{date} for the "what
 * changed" band the design handoff folds into this page rather than
 * giving it its own nav item (docs/PRODUCT_DESIGN_HANDOFF.md, "Fold WHAT
 * CHANGED into TODAY").
 *
 * `dossier` is documented as opaque ("not yet a stable per-field
 * contract" -- docs/API_CONTRACTS.md); it is rendered through
 * dom.renderUnknown rather than reaching into assumed fields.
 */

import { apiGet, ApiError } from "./api.js";
import { el, clear, renderUnknown, renderError } from "./dom.js";
import { renderStaleness } from "./meta.js";

function renderNotes(notes) {
  const section = el("section", { class: "today-notes", "data-hook": "today-notes" });
  section.appendChild(el("h2", { text: "Notes" }));
  if (!notes || notes.length === 0) {
    section.appendChild(renderUnknown(null));
    return section;
  }
  const list = el("ul", { class: "today-notes__list" });
  for (const note of notes) {
    list.appendChild(el("li", { class: "today-notes__item", text: note }));
  }
  section.appendChild(list);
  return section;
}

function renderWhatChanged(payload) {
  const section = el("section", { class: "what-changed", "data-hook": "what-changed" });
  section.appendChild(el("h2", { text: "What Changed" }));
  if (!payload) {
    section.appendChild(el("p", { class: "what-changed__unavailable" },
      ["What changed is unavailable right now."]));
    return section;
  }
  section.appendChild(el("p", { class: "what-changed__checked",
    text: `Games checked: ${payload.checked_games}` }));
  const items = payload.items || [];
  if (items.length === 0) {
    const notes = payload.notes || [];
    const list = el("ul", { class: "what-changed__notes" });
    for (const note of notes) list.appendChild(el("li", { text: note }));
    section.appendChild(list.childNodes.length ? list
      : el("p", { class: "what-changed__empty", text: "Nothing has changed." }));
    return section;
  }
  const list = el("ul", { class: "what-changed__items" });
  for (const item of items) {
    const li = el("li", { class: "what-changed__item",
      "data-tier": item.tier, "data-inadmissible": String(!!item.inadmissible) });
    li.appendChild(el("span", { class: "what-changed__game",
      text: `${item.away_team} @ ${item.home_team}` }));
    li.appendChild(el("span", { class: "what-changed__tier", text: item.tier }));
    li.appendChild(el("p", { class: "what-changed__headline",
      text: item.headline || "" }));
    li.appendChild(el("time", { class: "what-changed__seen",
      "data-hook": "what-changed-seen", text: item.seen_utc || "" }));
    list.appendChild(li);
  }
  section.appendChild(list);
  return section;
}

function renderGameEntry(entry) {
  const article = el("article", {
    class: "slate-entry", "data-hook": "slate-entry", "data-verdict": entry.verdict || "",
  });
  const verdictP = el("p", { class: "slate-entry__verdict", "data-hook": "verdict" });
  verdictP.appendChild(entry.verdict ? document.createTextNode(entry.verdict) : renderUnknown(null));
  article.appendChild(verdictP);

  const dl = el("dl", { class: "slate-entry__fields" });
  dl.appendChild(el("dt", { text: "Side" }));
  dl.appendChild(el("dd", {}, [entry.side || renderUnknown(null)]));
  dl.appendChild(el("dt", { text: "Market" }));
  dl.appendChild(el("dd", {}, [entry.market || renderUnknown(null)]));
  dl.appendChild(el("dt", { text: "Summary" }));
  dl.appendChild(el("dd", { "data-hook": "summary" }, [entry.summary || renderUnknown(null)]));
  article.appendChild(dl);

  article.appendChild(renderStaleness(entry.odds_meta));

  const findingsSection = el("section", { class: "slate-entry__findings", "data-hook": "findings" });
  findingsSection.appendChild(el("h3", { text: "Findings" }));
  findingsSection.appendChild(renderUnknown(entry.findings));
  article.appendChild(findingsSection);

  const dossierDetails = el("details", { class: "slate-entry__dossier", "data-hook": "dossier" });
  dossierDetails.appendChild(el("summary", { text: "Full dossier (unstructured)" }));
  dossierDetails.appendChild(renderUnknown(entry.dossier));
  article.appendChild(dossierDetails);

  return article;
}

export async function renderToday(container) {
  clear(container);
  const section = el("section", { class: "today-view", "data-view": "today" });
  section.appendChild(el("h1", { text: "Today" }));
  container.appendChild(section);

  let payload;
  try {
    payload = await apiGet("/today");
  } catch (err) {
    renderError(container, err);
    return;
  }

  section.appendChild(el("p", { class: "today-view__date", "data-hook": "today-date",
    text: `Date: ${payload.date}` }));
  section.appendChild(el("time", { class: "today-view__generated", "data-hook": "today-generated-at",
    text: payload.generated_at }));
  section.appendChild(renderNotes(payload.notes));

  let changed = null;
  try {
    changed = await apiGet(`/changed/${encodeURIComponent(payload.date)}`);
  } catch (err) {
    changed = null;
  }
  section.appendChild(renderWhatChanged(changed));

  const gamesSection = el("section", { class: "today-games", "data-hook": "today-games" });
  gamesSection.appendChild(el("h2", { text: "Games" }));
  const games = payload.games || [];
  if (games.length === 0) {
    gamesSection.appendChild(el("p", { class: "today-games__empty",
      text: "No games on this slate." }));
  } else {
    for (const entry of games) {
      gamesSection.appendChild(renderGameEntry(entry));
    }
  }
  section.appendChild(gamesSection);
}
