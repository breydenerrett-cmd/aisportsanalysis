/**
 * The hound studio's three tabs and the names the old seven answer to (web/js/kennel.js).
 *
 * OWNER, 2026-10-29: the studio had Look, Rules, Unleash, Backtest, Ask, Record, Versions and Lessons, a fork at every turn. It is Overview,
 * Rules and Coach now, with Unleash, Train and a ... menu in the header. Every link that was ever written (the Tonight page, the room, the
 * builder's "Backtest 30 days" button, a bookmark) says ?tab=<old name>, so each old name lands on the tab that now holds its content and
 * says what else to do once it is there: open the Look editor, show the Unleash panel, open the full test under the Rules line, or bring the
 * Versions list into view. Pure: no DOM, so a test can run it as a function.
 */

export const STUDIO_TABS = ["overview", "rules", "coach"];

/** Old tab name -> the tab that holds it now. */
export const TAB_ALIASES = Object.freeze({
  record: "overview", lessons: "overview", fire: "overview", look: "overview",
  backtest: "rules",
  ask: "coach", versions: "coach",
});

const has = (obj, key) => Object.prototype.hasOwnProperty.call(obj, key);

/** True for a name the studio answers to: one of the three tabs or one of the seven it replaced. */
export function isStudioTab(tab) {
  const t = String(tab || "");
  return STUDIO_TABS.includes(t) || has(TAB_ALIASES, t);
}

/**
 * Where a tab name lands. `tab` is always one of the three; the flags say what to do after it is built. An unknown or empty name is Overview,
 * the tab a hound opens on.
 */
export function studioTarget(tab) {
  const t = String(tab || "");
  const canon = STUDIO_TABS.includes(t) ? t : has(TAB_ALIASES, t) ? TAB_ALIASES[t] : "overview";
  return { tab: canon, fire: t === "fire", look: t === "look", test: t === "backtest", versions: t === "versions" };
}
