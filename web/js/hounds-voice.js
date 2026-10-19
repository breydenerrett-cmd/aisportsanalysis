/**
 * Small pure helpers the model pages share (no DOM, no fetch): a model's units, the board order, the W-L text,
 * the persona a model carries, a retirement reason in plain words, and the learning page's wording.
 *
 * NOTHING HERE MEASURES ANYTHING. Every figure is one the server sent (record, form, verdict); this file only
 * orders it and words it. The status words ("Beating the close", "Paying the vig") are in hounds-board.js and are
 * keyed on the referee's label and nothing else.
 *
 * PROFESSIONAL PASS, 2026-10-19 (docs/VOICE.md). This file used to hold the toy voice: emoji badges, flames,
 * the Houndmaster's roasts and brags, the "who gets put down next" poll, the chat-feed lines. The pages no
 * longer render any of it, so it is gone from here. The persona fields stay in config/house_pack.json and
 * friends (voice data, not shown), and src/hounds/voice.py still carries them for the digest.
 */

import { isNum } from "./hounds-core.js";

// ---- units, order, W-L -----------------------------------------------------------------------------

/** A hound's units: the average price (the headline) when it has one, else the recorded price. Null with no bets. */
export function unitsOf(hound) {
  const rec = hound && hound.record;
  if (!rec || !isNum(rec.bets) || rec.bets <= 0) return null;
  if (isNum(rec.units_average_price)) return rec.units_average_price;
  return isNum(rec.units_recorded_price) ? rec.units_recorded_price : null;
}

/** Board order: most units first; a model with no graded bet goes last; ties by more bets, then name. */
export function sortByUnits(hounds) {
  const betsOf = (x) => (x && x.record && isNum(x.record.bets) ? x.record.bets : 0);
  return (hounds || []).slice().sort((a, b) => {
    const ua = unitsOf(a), ub = unitsOf(b);
    if (ua === null && ub !== null) return 1;
    if (ub === null && ua !== null) return -1;
    return (ub ?? 0) - (ua ?? 0) || betsOf(b) - betsOf(a) || String(a.name || "").localeCompare(String(b.name || ""));
  });
}

/** "63-46" (or "63-46-2" with pushes), the part a bettor reads first. */
export function wlText(rec) {
  const r = rec || {};
  if (!isNum(r.bets) || r.bets <= 0) return "0-0";
  return `${r.wins ?? 0}-${r.losses ?? 0}${r.pushes ? `-${r.pushes}` : ""}`;
}

// ---- persona ---------------------------------------------------------------------------------------

/** The persona a hound carries, or null. Only its catchphrase is ever shown (one small italic line). */
export function personaOf(hound) {
  const p = hound && hound.persona;
  return p && typeof p === "object" ? p : null;
}

// ---- retirement ------------------------------------------------------------------------------------

/** The reason a model was retired, in plain words. An unknown reason is quoted as the server wrote it. */
export function causeText(cause) {
  const text = String(cause || "").trim();
  if (!text) return "No reason was given.";
  if (/down more than 25 units/i.test(text)) return "Went more than 25 units under.";
  if (/paying the vig/i.test(text)) return "300 bets paying the vig.";
  if (/retired by the owner/i.test(text)) return "Retired by the owner.";
  return text.charAt(0).toUpperCase() + text.slice(1);
}

// ---- the learning page's wording -------------------------------------------------------------------

/**
 * A lesson the code wrote (src/hounds/learning/lessons.py one_line), said in the learning page's words: a
 * challenger "made the team" or was "cut" instead of being promoted or retired, the champion is the starter, and
 * the statistics are plain numbers. Same facts, same figures; only the vocabulary changes.
 */
export function friendlyLesson(text) {
  return String(text || "")
    .replace(/was promoted to champion/g, "made the team")
    .replace(/was retired:/g, "was cut:")
    .replace(/was closed undecided:/g, "ended undecided:")
    .replace(/it did worse than the champion/g, "it did worse than the starter")
    .replace(/it never beat the champion by the bar/g, "it never beat the starter by the bar")
    .replace(/it cleared its own bar but not the system-wide false-discovery control/g,
      "it cleared its own bar but not camp's fluke check")
    .replace(/the champion changed during its test/g, "the starter changed during its tryout")
    .replace(/(\d+) paired slots, mean CLV difference ([+-][\d.]+) pts/g,
      "$1 paired games, its prices beat the starter's by $2 pts on average")
    .replace(/\(bounds ([+-][\d.]+) to ([+-][\d.]+)\)/g, "(somewhere between $1 and $2)")
    .replace(/; adjusted p ([\d.]+)/g, "; fluke-check number $1 (lower is better)");
}

/** A sentence the server wrote about the learning loop, in the learning page's words. */
export function campWords(text) {
  return String(text || "")
    .replace(/\bchallengers\b/g, "rookies").replace(/\bchallenger\b/g, "rookie")
    .replace(/\bThe loop\b/g, "Camp").replace(/\bthe loop\b/g, "camp");
}
