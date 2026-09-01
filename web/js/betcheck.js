/**
 * BET CHECK view -- POST /betcheck (api/betcheck.py).
 *
 * FIXED SKELETON, MANDATED ORDER (docs/PRODUCT_DESIGN_HANDOFF.md, "A fixed
 * skeleton is a trust mechanism": an omission becomes visible only if the
 * shape never changes) -- always these five regions, always in this
 * order, regardless of what the response contains:
 *
 *   1. YOUR BET          (data-hook="bet-check-your-bet")
 *   2. SUPPORT            (data-hook="bet-check-support")
 *   3. COUNTERARGUMENT    (data-hook="bet-check-counterargument")
 *   4. PRICES             (data-hook="bet-check-prices")
 *   5. BOTTOM LINE        (data-hook="bet-check-bottom-line")
 *
 * tests/test_web_structure.py asserts these five data-hook values appear
 * in this exact order in this file's source -- do not reorder the
 * `section.appendChild` calls in `renderResult` below without updating
 * that test.
 *
 * SUPPORT AND COUNTERARGUMENT GET IDENTICAL MARKUP (<section><h2><ul>) --
 * "counterargument equal standing" (docs/PRODUCT_DESIGN_HANDOFF.md) means
 * structural parity, not that one gets a richer template than the other.
 * `counterargument_lines` is documented "never empty" (renders "No
 * significant counterarguments found" itself) -- so it is rendered
 * verbatim with no client-side fallback text composed for it.
 */

import { apiGet, apiPost } from "./api.js";
import { el, clear, renderUnknown, renderError } from "./dom.js";

function todayIso() {
  return new Date().toISOString().slice(0, 10);
}

function renderForm(container, prefill, onSubmit) {
  const form = el("form", { class: "bet-check-form field-form panel chamfer", "data-hook": "bet-check-form" });

  const dateLabel = el("label", { for: "bc-date", text: "Date" });
  const dateInput = el("input", { type: "date", id: "bc-date", name: "date",
    value: prefill.date || todayIso(), required: "required" });

  const awayLabel = el("label", { for: "bc-away", text: "Away club" });
  const awayInput = el("input", { type: "text", id: "bc-away", name: "away",
    value: prefill.away || "", required: "required" });

  const homeLabel = el("label", { for: "bc-home", text: "Home club" });
  const homeInput = el("input", { type: "text", id: "bc-home", name: "home",
    value: prefill.home || "", required: "required" });

  const sideLabel = el("label", { for: "bc-side", text: "Side" });
  const sideSelect = el("select", { id: "bc-side", name: "side", required: "required" });
  sideSelect.appendChild(el("option", { value: "away", text: "Away" }));
  sideSelect.appendChild(el("option", { value: "home", text: "Home" }));

  const priceLabel = el("label", { for: "bc-price", text: "American price" });
  const priceInput = el("input", { type: "number", id: "bc-price", name: "american_price",
    step: "1", required: "required" });

  for (const [labelEl, inputEl] of [
    [dateLabel, dateInput], [awayLabel, awayInput], [homeLabel, homeInput],
    [sideLabel, sideSelect], [priceLabel, priceInput],
  ]) {
    const row = el("p", { class: "bet-check-form__row field-row" });
    row.appendChild(labelEl);
    row.appendChild(inputEl);
    form.appendChild(row);
  }
  form.appendChild(el("button", { type: "submit", class: "btn btn--cyan", text: "Check this bet" }));

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    onSubmit({
      date: dateInput.value,
      away: awayInput.value,
      home: homeInput.value,
      side: sideSelect.value,
      american_price: Number(priceInput.value),
    });
  });

  container.appendChild(form);
}

function renderYourBet(result, submitted) {
  const section = el("section", { class: "bet-check-your-bet panel chamfer", "data-hook": "bet-check-your-bet" });
  section.appendChild(el("h2", { text: "Your bet" }));
  const dl = el("dl", { class: "bet-check-your-bet__fields" });
  dl.appendChild(el("dt", { text: "As typed" }));
  dl.appendChild(el("dd", { "data-hook": "query-raw" }, [result.query ? result.query.raw : submitted.raw]));
  dl.appendChild(el("dt", { text: "Parsed" }));
  dl.appendChild(el("dd", { "data-hook": "query-parsed" },
    [renderUnknown(result.query ? result.query.parsed : null)]));
  dl.appendChild(el("dt", { text: "Game" }));
  dl.appendChild(el("dd", { "data-hook": "bet-check-game" }, [renderUnknown(result.game)]));
  section.appendChild(dl);
  return section;
}

function renderClaimList(claims) {
  const list = el("ul", { class: "claim-list" });
  for (const claim of claims) {
    const item = el("li", { class: "claim-list__item" });
    item.appendChild(renderUnknown(claim));
    list.appendChild(item);
  }
  return list;
}

function renderSupport(result) {
  const section = el("section", { class: "bet-check-support panel chamfer", "data-hook": "bet-check-support" });
  section.appendChild(el("h2", { text: "Support" }));
  const support = result.thesis_support || [];
  section.appendChild(support.length ? renderClaimList(support) : renderUnknown(null));
  return section;
}

function renderCounterargument(result) {
  const section = el("section", {
    class: "bet-check-counterargument panel chamfer", "data-hook": "bet-check-counterargument",
  });
  section.appendChild(el("h2", { text: "Counterargument" }));
  // counterargument_lines is contractually never empty -- rendered as-is,
  // never replaced with client-composed filler.
  const lines = result.counterargument_lines || [];
  const list = el("ul", { class: "counterargument-lines", "data-hook": "counterargument-lines" });
  for (const line of lines) list.appendChild(el("li", { text: line }));
  section.appendChild(list);
  return section;
}

function renderPrices(result) {
  const section = el("section", { class: "bet-check-prices panel chamfer", "data-hook": "bet-check-prices" });
  section.appendChild(el("h2", { text: "Prices" }));
  const dl = el("dl", { class: "bet-check-prices__fields" });
  dl.appendChild(el("dt", { text: "Best available price" }));
  dl.appendChild(el("dd", { "data-hook": "best-available-price" }, [renderUnknown(result.best_available_price)]));
  dl.appendChild(el("dt", { text: "Market consensus" }));
  dl.appendChild(el("dd", { "data-hook": "market-consensus" }, [renderUnknown(result.market_consensus)]));
  dl.appendChild(el("dt", { text: "Price improvement" }));
  dl.appendChild(el("dd", { "data-hook": "price-improvement" }, [renderUnknown(result.price_improvement)]));
  dl.appendChild(el("dt", { text: "Your price beats consensus" }));
  dl.appendChild(el("dd", { "data-hook": "your-price-beats-consensus" },
    [renderUnknown(result.your_price_beats_consensus)]));
  section.appendChild(dl);
  return section;
}

function renderBottomLine(result) {
  const section = el("section", { class: "bet-check-bottom-line panel chamfer", "data-hook": "bet-check-bottom-line" });
  section.appendChild(el("h2", { text: "Bottom line" }));

  const dl = el("dl", { class: "bet-check-bottom-line__fields" });
  for (const [label, key, hook] of [
    ["Strongest reason", "strongest_reason", "strongest-reason"],
    ["Weakest reason", "weakest_reason", "weakest-reason"],
    ["Historical support", "historical_support", "historical-support"],
    ["Evidence status", "evidence_status", "evidence-status"],
  ]) {
    dl.appendChild(el("dt", { text: label }));
    dl.appendChild(el("dd", { "data-hook": hook }, [result[key] || renderUnknown(null)]));
  }
  section.appendChild(dl);

  const whatChanged = el("section", { class: "bet-check-what-changed", "data-hook": "bet-check-what-changed" });
  whatChanged.appendChild(el("h3", { text: "What changed" }));
  whatChanged.appendChild(renderUnknown(result.what_changed));
  section.appendChild(whatChanged);

  // recommendation is contractually always null (Ranker Engine 2 gate) --
  // rendered verbatim, never interpreted into a pick.
  const recommendation = el("p", { class: "bet-check-recommendation", "data-hook": "recommendation" });
  recommendation.appendChild(renderUnknown(result.recommendation));
  section.appendChild(recommendation);

  const bottomLine = el("p", { class: "bet-check-bottom-line__text", "data-hook": "bottom-line-text" });
  bottomLine.appendChild(result.bottom_line ? document.createTextNode(result.bottom_line) : renderUnknown(null));
  section.appendChild(bottomLine);

  return section;
}

function renderResult(container, result, submitted) {
  const section = el("section", { class: "bet-check-result", "data-view": "bet-check-result" });
  if (result.note) {
    section.appendChild(el("p", { class: "bet-check-result__note", "data-hook": "doubleheader-note",
      text: result.note }));
  }
  // Fixed order -- see module docstring. Do not reorder.
  section.appendChild(renderYourBet(result, submitted));
  section.appendChild(renderSupport(result));
  section.appendChild(renderCounterargument(result));
  section.appendChild(renderPrices(result));
  section.appendChild(renderBottomLine(result));
  container.appendChild(section);
}

export async function renderBetCheck(container, prefill = {}) {
  clear(container);
  const section = el("section", { class: "bet-check-view view", "data-view": "betcheck" });
  section.appendChild(el("h1", { class: "view__title", text: "Bet Check" }));
  container.appendChild(section);

  const formHost = el("div", { class: "bet-check-form-host" });
  section.appendChild(formHost);
  const resultHost = el("div", { class: "bet-check-result-host", "data-hook": "bet-check-result-host" });
  // Empty state: the ten-block skeleton is not drawn until a bet exists
  // (handoff section 10) -- a plain sentence, not a blank pane.
  resultHost.appendChild(el("div", { class: "state-empty", "data-hook": "bet-check-empty" }, [
    el("p", { class: "state-empty__title", text: "Paste a bet to begin." }),
    el("p", { class: "state-empty__body",
      text: "Fill in the game, side and price above and check it." }),
  ]));
  section.appendChild(resultHost);

  renderForm(formHost, prefill, async (submitted) => {
    clear(resultHost);
    resultHost.appendChild(el("div", { class: "state-loading panel chamfer", "data-hook": "view-loading" },
      [el("p", { class: "state-loading__figure", text: "Checking this bet…" })]));
    let result;
    try {
      result = await apiPost("/betcheck", {
        date: submitted.date, away: submitted.away, home: submitted.home,
        side: submitted.side, american_price: submitted.american_price,
      });
    } catch (err) {
      renderError(resultHost, err);
      return;
    }
    const submittedRaw = `${submitted.away} @ ${submitted.home}, ${submitted.side} ${submitted.american_price}`;
    renderResult(resultHost, result, { raw: submittedRaw });
  });
}
