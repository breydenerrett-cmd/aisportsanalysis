/**
 * The unit label that sits beside bankroll figures (My Kennel, the hound page, the leaderboard): "1u = $25", plain text.
 * The bankroll is locked (owner, 2026-11-05): $2,500 for every hound, $25 a unit, so there is nothing to pick.
 * Members still choose a hound's stake and bets per day on its Rules tab.
 */

import { h } from "./hounds-core.js";
import { getSizing, unitWords } from "./unitsize.js";

export const PANEL_LINE = "Every hound starts with the same $2,500 paper bankroll. 1 unit = $25.";

/** The label: not a button, nothing opens. */
export function unitChip() {
  return h("span", { class: "us-chipwrap" }, [
    h("span", { class: "us-label-static", "data-hook": "unit-chip-label", text: unitWords(getSizing()) }),
  ]);
}
