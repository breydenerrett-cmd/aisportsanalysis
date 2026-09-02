/**
 * MY BETS view -- GET/POST/DELETE /my-bets (api/mybets.py). Every request
 * is scoped to the bearer token's user server-side; this client never
 * needs to know or send a user id.
 */

import { apiGet, apiPost, apiDelete } from "./api.js";
import { el, clear, renderUnknown, renderError, formatAmerican, formatEasternTime } from "./dom.js";

/** One honest line for the closing-price fields (api/mybets.py's
 * `_serialize`): "closed -118 (as of 7:40 PM ET) · you took -110" when a
 * close was captured, or the plain fact that it was not -- never an
 * estimate, and never the word CLV or edge (docs/API_CONTRACTS.md's
 * vocabulary rules). This is deliberately plain text in the existing
 * undesigned list, not a restyle -- V2 redesigns this screen. */
function formatClosingLine(bet) {
  if (bet.closing_price === null || bet.closing_price === undefined) {
    return "closing price not captured";
  }
  const closed = formatAmerican(bet.closing_price);
  const when = formatEasternTime(bet.closing_observed_utc);
  const took = formatAmerican(bet.price);
  let line = `closed ${closed}`;
  if (when) line += ` (as of ${when})`;
  if (took !== null) line += ` · you took ${took}`;
  return line;
}

function renderSaveForm(container, onSaved) {
  const form = el("form", { class: "my-bets-form panel chamfer", "data-hook": "my-bets-form" });

  const gameLabel = el("label", { for: "mb-game", text: "Game" });
  const gameInput = el("input", { type: "text", id: "mb-game", name: "game", required: "required" });

  const sideLabel = el("label", { for: "mb-side", text: "Side" });
  const sideInput = el("input", { type: "text", id: "mb-side", name: "side", required: "required" });

  const priceLabel = el("label", { for: "mb-price", text: "Price" });
  const priceInput = el("input", { type: "number", id: "mb-price", name: "price", step: "1" });

  for (const [labelEl, inputEl] of [[gameLabel, gameInput], [sideLabel, sideInput], [priceLabel, priceInput]]) {
    const row = el("p", { class: "my-bets-form__row field-row" });
    row.appendChild(labelEl);
    row.appendChild(inputEl);
    form.appendChild(row);
  }
  form.appendChild(el("button", { type: "submit", class: "btn btn--cyan", text: "Save bet" }));

  const statusRegion = el("p", { class: "my-bets-form__status", role: "status",
    "data-hook": "my-bets-form-status" });

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    clear(statusRegion);
    try {
      const body = { game: gameInput.value, side: sideInput.value };
      if (priceInput.value !== "") body.price = Number(priceInput.value);
      await apiPost("/my-bets", body);
      form.reset();
      await onSaved();
    } catch (err) {
      renderError(statusRegion, err);
    }
  });

  container.appendChild(form);
  container.appendChild(statusRegion);
}

function renderBetsTable(container, bets, onDeleted) {
  clear(container);
  const scroll = el("div", { class: "board-scroll panel chamfer" });
  const table = el("table", { class: "my-bets-board board-table", "data-hook": "my-bets-board" });
  table.appendChild(el("caption", { text: "Saved bets" }));
  const thead = el("thead");
  const headRow = el("tr");
  for (const label of ["Game", "Side", "Price", "Saved", "Settlement", "Closing price", ""]) {
    headRow.appendChild(el("th", { scope: "col", text: label }));
  }
  thead.appendChild(headRow);
  table.appendChild(thead);

  const tbody = el("tbody");
  if (!bets || bets.length === 0) {
    const tr = el("tr");
    tr.appendChild(el("td", { colspan: "7" },
      [el("div", { class: "state-empty", "data-hook": "my-bets-empty" }, [
        el("p", { class: "state-empty__title", text: "No saved bets yet." }),
        el("p", { class: "state-empty__body", text: "Save a bet from Bet Check to track it here." }),
      ])]));
    tbody.appendChild(tr);
  }
  for (const bet of bets || []) {
    const tr = el("tr", { class: "my-bets-board__row", "data-hook": "my-bets-row",
      "data-bet-id": String(bet.id) });
    tr.appendChild(el("td", { text: bet.game }));
    tr.appendChild(el("td", { text: bet.side }));
    tr.appendChild(el("td", {}, [renderUnknown(bet.price)]));
    tr.appendChild(el("td", {}, [el("time", { text: bet.saved_at })]));
    const settlementCell = el("td");
    settlementCell.appendChild(renderUnknown({
      status: bet.settlement_status, reason: bet.settlement_reason, at: bet.settled_at,
    }));
    tr.appendChild(settlementCell);
    tr.appendChild(el("td", { "data-hook": "closing-price", text: formatClosingLine(bet) }));
    const deleteCell = el("td");
    const deleteButton = el("button", { type: "button", "data-hook": "delete-bet",
      "data-bet-id": String(bet.id), text: "Delete" });
    deleteButton.addEventListener("click", async () => {
      try {
        await apiDelete(`/my-bets/${bet.id}`);
        await onDeleted();
      } catch (err) {
        renderError(container, err);
      }
    });
    deleteCell.appendChild(deleteButton);
    tr.appendChild(deleteCell);
    tbody.appendChild(tr);
  }
  table.appendChild(tbody);
  scroll.appendChild(table);
  container.appendChild(scroll);
}

export async function renderMyBets(container) {
  clear(container);
  const section = el("section", { class: "my-bets-view view", "data-view": "mybets" });
  section.appendChild(el("h1", { class: "view__title", text: "My Bets" }));

  const formHost = el("div", { class: "my-bets-form-host" });
  const boardHost = el("div", { class: "my-bets-board-host", "data-hook": "my-bets-board-host" });
  section.appendChild(formHost);
  section.appendChild(boardHost);
  container.appendChild(section);

  async function reload() {
    clear(boardHost);
    boardHost.appendChild(el("div", { class: "state-loading panel chamfer", "data-hook": "view-loading" },
      [el("p", { class: "state-loading__figure", text: "Loading your bets…" })]));
    let payload;
    try {
      payload = await apiGet("/my-bets");
    } catch (err) {
      renderError(boardHost, err);
      return;
    }
    renderBetsTable(boardHost, payload.bets, reload);
  }

  renderSaveForm(formHost, reload);
  await reload();
}
