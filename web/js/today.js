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
import { el, clear, renderUnknown, renderError, verdictLabel, verdictChipClass,
  formatEasternTime } from "./dom.js";
import { renderStaleness } from "./meta.js";

function renderNotes(notes) {
  const section = el("section", { class: "today-notes panel chamfer section-block", "data-hook": "today-notes" });
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
  const section = el("section", { class: "what-changed panel chamfer section-block", "data-hook": "what-changed" });
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

/** /today's `dossier` is documented opaque (module docstring), but its
 * `game` sub-object is where the team identity and start time actually
 * live -- there is no other source for them on this endpoint. Read
 * defensively (never assume the shape holds) so a future dossier reshape
 * degrades to the NOT-YET-AVAILABLE marker on the card face rather than
 * throwing; the full raw dossier is still rendered verbatim, unread and
 * unchanged, in the collapsed disclosure below. */
function readDossierGame(entry) {
  const dossier = entry && typeof entry.dossier === "object" ? entry.dossier : null;
  const game = dossier && typeof dossier.game === "object" ? dossier.game : null;
  return game || null;
}

function renderGameEntry(entry) {
  const article = el("article", {
    class: "slate-entry panel chamfer", "data-hook": "slate-entry", "data-verdict": entry.verdict || "",
  });

  // Lead with the matchup and the verdict as a styled chip, exactly like
  // the Gameday canvas's card anatomy -- machine fields (game_pk,
  // observed_utc, has_market, the raw dossier) never lead the card face;
  // they stay reachable in the collapsed "Full dossier" disclosure below
  // (handoff section 11's content-hierarchy rule).
  const game = readDossierGame(entry);
  const header = el("div", { class: "slate-entry__header" });
  const matchup = el("h3", { class: "slate-entry__matchup" });
  matchup.appendChild(game ? document.createTextNode(`${game.away_team} @ ${game.home_team}`) : renderUnknown(null));
  header.appendChild(matchup);

  const chip = el("span", { class: `badge chamfer chamfer--chip ${verdictChipClass(entry.verdict)}`,
    "data-hook": "verdict", "data-verdict-raw": entry.verdict || "" });
  chip.appendChild(entry.verdict ? document.createTextNode(verdictLabel(entry.verdict)) : renderUnknown(null));
  header.appendChild(chip);
  article.appendChild(header);

  const startTime = game ? formatEasternTime(game.start_time_utc) : null;
  article.appendChild(el("p", { class: "slate-entry__start", "data-hook": "start-time" },
    [startTime || renderUnknown(null)]));
  if (game && game.venue) {
    article.appendChild(el("p", { class: "slate-entry__venue", text: game.venue }));
  }

  const dl = el("dl", { class: "slate-entry__fields" });
  dl.appendChild(el("dt", { text: "Side" }));
  dl.appendChild(el("dd", {}, [entry.side || renderUnknown(null)]));
  dl.appendChild(el("dt", { text: "Market" }));
  dl.appendChild(el("dd", {}, [entry.market || renderUnknown(null)]));
  dl.appendChild(el("dt", { text: "Summary" }));
  dl.appendChild(el("dd", { "data-hook": "summary" }, [entry.summary || renderUnknown(null)]));
  article.appendChild(dl);

  // Board/price freshness -- demoted beneath the human-readable fields,
  // never leading the card, but still present (never suppressed).
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
  const section = el("section", { class: "today-view view", "data-view": "today" });
  section.appendChild(el("h1", { class: "view__title", text: "Today" }));
  container.appendChild(section);

  const loading = el("div", { class: "state-loading panel chamfer", "data-hook": "view-loading" },
    [el("p", { class: "state-loading__figure", text: "Loading today's slate…" })]);
  section.appendChild(loading);

  let payload;
  try {
    payload = await apiGet("/today");
  } catch (err) {
    // Header stays -- an error clears only the loading placeholder, not
    // the page title (handoff section 10, "Header retained").
    renderError(loading, err);
    return;
  }
  clear(loading);
  loading.remove();

  const meta = el("div", { class: "view__eyebrow-row" });
  meta.appendChild(el("p", { class: "eyebrow", "data-hook": "today-date",
    text: `Date: ${payload.date}` }));
  meta.appendChild(el("time", { class: "eyebrow eyebrow--muted", "data-hook": "today-generated-at",
    text: payload.generated_at }));
  section.appendChild(meta);

  if (payload.freshness) {
    section.appendChild(el("p", { class: "freshness-banner", "data-hook": "today-freshness" },
      [renderUnknown(payload.freshness)]));
  }

  section.appendChild(renderNotes(payload.notes));

  let changed = null;
  try {
    changed = await apiGet(`/changed/${encodeURIComponent(payload.date)}`);
  } catch (err) {
    changed = null;
  }
  section.appendChild(renderWhatChanged(changed));

  const gamesSection = el("section", { class: "today-games section-block", "data-hook": "today-games" });
  gamesSection.appendChild(el("h2", { text: "Games" }));
  const games = payload.games || [];
  if (games.length === 0) {
    // NO PLAY state (handoff section 10): plain language, never a blank
    // page or a manufactured pick -- and quantify the work if the
    // /changed payload gave us a checked-games count to cite honestly.
    const empty = el("div", { class: "state-empty", "data-hook": "today-no-play" });
    empty.appendChild(el("p", { class: "state-empty__title", text: "Nothing on this slate yet." }));
    const checked = changed && typeof changed.checked_games === "number" ? changed.checked_games : null;
    empty.appendChild(el("p", { class: "state-empty__body", text: checked !== null
      ? `${checked} games checked. None have a slate entry yet.`
      : "No games on this slate." }));
    gamesSection.appendChild(empty);
  } else {
    for (const entry of games) {
      gamesSection.appendChild(renderGameEntry(entry));
    }
  }
  section.appendChild(gamesSection);
}
