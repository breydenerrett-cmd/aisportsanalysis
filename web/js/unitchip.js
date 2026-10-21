/**
 * The unit-size controls: a compact "1u = $25 ▾" chip that sits beside bankroll figures (My Kennel, the hound page,
 * the leaderboard) and the full settings panel (Account, and inside the chip's popover). The rules and the dollar
 * math are web/js/unitsize.js; this file is only the pickers.
 *
 * WORDS THAT MATTER (docs/VOICE.md): "paper dollars at your unit size; units are the record." The panel says it in
 * one line, says it is paper, and never says profit. Choosing never edits a bet: the record is in units.
 *
 * A CHOICE IS APPLIED BY RELOADING THE PAGE (unitsize.chooseSizing does it when no page registered its own redraw):
 * every figure on the page is a lens on the same units, so the simple honest redraw is a fresh render.
 */

import { h } from "./hounds-core.js";
import {
  getSizing, chooseSizing, sizingProblem, syncFromAccount, unitWords, fixedSizing, percentSizing,
  FIXED_CHIPS, FIXED_MIN, FIXED_MAX, PCT_CHOICES, START_MIN, START_MAX, DEFAULT_START_USD, DEFAULT_PCT, DEFAULT_FIXED_USD,
} from "./unitsize.js";

export const PANEL_LINE = "Paper dollars at your unit size. Units are the record, and they never change.";

const usd = (n) => `$${Number(n).toLocaleString("en-US")}`;

/**
 * The full settings form. `onSaved(sizing)` runs after a valid choice is applied (the chip closes its popover).
 * Validation is the same on both sides: this form says why before it sends, and the server (PUT /me/unit-size)
 * checks again.
 */
export function unitSettings({ onSaved } = {}) {
  const start = getSizing();
  const draft = {
    mode: start.mode,
    unit: start.mode === "fixed" ? start.unit_usd : DEFAULT_FIXED_USD,
    pct: start.mode === "percent" ? start.pct : DEFAULT_PCT,
    bankroll: start.mode === "percent" ? start.start_usd : DEFAULT_START_USD,
  };
  const root = h("form", { class: "us-panel", "data-hook": "unit-settings", novalidate: "" });

  const modeFixed = h("input", { type: "radio", name: "us-mode", value: "fixed", id: "us-mode-fixed", "data-hook": "us-mode-fixed" });
  const modePct = h("input", { type: "radio", name: "us-mode", value: "percent", id: "us-mode-percent", "data-hook": "us-mode-percent" });
  if (draft.mode === "fixed") modeFixed.setAttribute("checked", ""); else modePct.setAttribute("checked", "");

  // fixed dollars: chips plus any whole dollar
  const chips = FIXED_CHIPS.map((v) => h("button", { type: "button", class: "us-chip", "data-unit": String(v),
    "data-hook": `us-chip-${v}`, "aria-pressed": "false", text: usd(v) }));
  const custom = h("input", { type: "number", class: "us-input", id: "us-unit", inputmode: "numeric", min: FIXED_MIN, max: FIXED_MAX, step: 1,
    value: draft.unit, "data-hook": "us-unit", "aria-label": `Unit size in dollars, ${usd(FIXED_MIN)} to ${usd(FIXED_MAX)}` });
  const fixedPane = h("div", { class: "us-pane", "data-hook": "us-fixed" }, [
    h("div", { class: "us-chips", role: "group", "aria-label": "Quick unit sizes" }, chips),
    h("label", { class: "us-label", for: "us-unit", text: `Or any whole-dollar unit, ${usd(FIXED_MIN)} to ${usd(FIXED_MAX)}` }), custom,
    h("p", { class: "hd-fine", text: "Your starting bankroll is always 100 units, so the account is the same at every size." }),
  ]);

  // percent of bankroll
  const pctSelect = h("select", { class: "us-input", id: "us-pct", "data-hook": "us-pct" },
    PCT_CHOICES.map((v) => h("option", { value: String(v), text: `${v}%`, selected: v === draft.pct ? "" : undefined })));
  pctSelect.value = String(draft.pct);
  const bankrollInput = h("input", { type: "number", class: "us-input", id: "us-bankroll", inputmode: "numeric", min: START_MIN, max: START_MAX, step: 1,
    value: draft.bankroll, "data-hook": "us-bankroll", "aria-label": `Starting bankroll in dollars, ${usd(START_MIN)} to ${usd(START_MAX)}` });
  const pctPane = h("div", { class: "us-pane", "data-hook": "us-percent" }, [
    h("label", { class: "us-label", for: "us-pct", text: "One unit is this share of your balance when the bet is placed" }), pctSelect,
    h("label", { class: "us-label", for: "us-bankroll", text: `Starting bankroll, ${usd(START_MIN)} to ${usd(START_MAX)}` }), bankrollInput,
    h("p", { class: "hd-fine", text: "Bets compound: a bet of 2 units risks twice that share of the balance at the time. Return % is shown at your sizing; ranks never change." }),
  ]);

  const status = h("p", { class: "hd-fine us-status", role: "status", "aria-live": "polite", "data-hook": "us-status", text: "" });
  const save = h("button", { type: "submit", class: "lh-btn lh-btn--soft us-save", "data-hook": "us-save", text: "Save" });

  let mode = draft.mode;                 // tracked here, not read back from the radios: one source for paint() and read()
  const paint = () => {
    const fixedOn = mode === "fixed";
    fixedPane.hidden = !fixedOn;
    pctPane.hidden = fixedOn;
    for (const c of chips) c.setAttribute("aria-pressed", fixedOn && Number(custom.value) === Number(c.getAttribute("data-unit")) ? "true" : "false");
  };
  for (const r of [modeFixed, modePct]) r.addEventListener("change", () => { mode = r.getAttribute("value") === "percent" ? "percent" : "fixed"; status.textContent = ""; paint(); });
  custom.addEventListener("input", paint);
  for (const c of chips) c.addEventListener("click", () => { custom.value = c.getAttribute("data-unit"); status.textContent = ""; paint(); });

  const read = () => (mode === "fixed"
    ? { mode: "fixed", unit_usd: custom.value === "" ? null : Number(custom.value), pct: null, start_usd: null }
    : { mode: "percent", unit_usd: null, pct: Number(pctSelect.value), start_usd: bankrollInput.value === "" ? null : Number(bankrollInput.value) });

  // The Save button's click does the work (and stops the form's own submit): Enter in a field clicks the default button,
  // so keyboard and pointer take the same path.
  save.addEventListener("click", async (event) => {
    if (event && event.preventDefault) event.preventDefault();
    const raw = read();
    const problem = sizingProblem(raw);
    if (problem) { status.textContent = problem; return; }
    const sizing = raw.mode === "fixed" ? fixedSizing(raw.unit_usd) : percentSizing(raw.pct, raw.start_usd);
    status.textContent = "Saving...";
    const used = await chooseSizing(sizing);
    status.textContent = used ? `Saved: ${unitWords(used)}.` : "That sizing was not accepted.";
    if (used && onSaved) onSaved(used);
  });

  root.appendChild(h("fieldset", { class: "us-modes" }, [
    h("legend", { class: "us-label", text: "Show my paper money as" }),
    h("label", { class: "us-mode", for: "us-mode-fixed" }, [modeFixed, " Fixed dollars per unit"]),
    h("label", { class: "us-mode", for: "us-mode-percent" }, [modePct, " Percent of bankroll"]),
  ]));
  root.appendChild(fixedPane);
  root.appendChild(pctPane);
  root.appendChild(h("div", { class: "us-actions" }, [save, status]));
  root.appendChild(h("p", { class: "hd-fine", "data-hook": "us-line", text: PANEL_LINE }));
  paint();
  return root;
}

/**
 * The chip: "1u = $25 ▾", a button that opens the settings panel in place. Mount it beside any bankroll figure.
 * It asks the account for the member's saved choice once (a signed-in member on a new device gets their own dollars).
 */
export function unitChip() {
  const label = h("span", { "data-hook": "unit-chip-label", text: unitWords(getSizing()) });
  const button = h("button", { type: "button", class: "us-trigger", "data-hook": "unit-chip", "aria-expanded": "false",
    "aria-haspopup": "true", title: "Paper dollars at your unit size. Units are the record." }, [label, h("span", { "aria-hidden": "true", text: " ▾" })]);
  const pop = h("div", { class: "us-pop", "data-hook": "unit-pop" });
  pop.hidden = true;
  button.addEventListener("click", () => {
    const open = pop.hidden;
    pop.hidden = !open;
    button.setAttribute("aria-expanded", open ? "true" : "false");
    if (open && !pop.firstChild) pop.appendChild(unitSettings({ onSaved: () => { pop.hidden = true; button.setAttribute("aria-expanded", "false"); } }));
  });
  syncFromAccount().then(() => { label.textContent = unitWords(getSizing()); }).catch(() => {});
  return h("span", { class: "us-chipwrap" }, [button, pop]);
}
