/**
 * The kennel's voice, as small pure helpers (no DOM, no fetch). The Hounds pages call these to turn the
 * numbers the server already sent into the things a bettor reads: a badge, a streak, who is hot and who is
 * on tilt, who is closest to being put down, what the Houndmaster says today, what a bet looks like in a
 * chat feed.
 *
 * NOTHING HERE MEASURES ANYTHING. Every figure is one the server sent (record, form, verdict); this file
 * only orders it and words it. The badge is the old verdict label in a bettor's clothes, keyed on the
 * label and nothing else, and src/hounds/voice.py holds the same table so a test keeps the two in step.
 * The voice guide is docs/VOICE.md.
 */

import {
  hashName, isNum, fmtPrice, fmtUnits, categoryOf, verdictLabel, verdictTone, NOT_REPORTED,
} from "./hounds-core.js";

// ---- badges -----------------------------------------------------------------------------------------

/** Verdict label (the referee's words, unchanged) -> the badge it wears. */
export const BADGES = {
  "BEATING THE CLOSE": { key: "sharp", word: "SHARP", emoji: "🔥",
    explain: "Its prices keep beating where the market closes. Good shopping, not a promise of wins." },
  "NO DIFFERENT FROM THE MARKET": { key: "coin_flip", word: "COIN FLIP", emoji: "🪙",
    explain: "Its prices look just like the closing line: no better, no worse. A coin flip, so far." },
  "PAYING THE VIG": { key: "feeding_the_book", word: "FEEDING THE BOOK", emoji: "💸",
    explain: "Its prices keep landing worse than the close. Every bet costs it a little extra." },
  "TOO EARLY": { key: "rookie", word: "ROOKIE", emoji: "🐣",
    explain: "Too few bets to judge. Wins and losses this early are mostly luck." },
};
export const UNRATED_BADGE = { key: "unrated", word: "UNRATED", emoji: "🐾",
  explain: "This one was never graded against the closing line." };

/** The badge for a verdict label string. */
export function badgeForLabel(label) {
  const found = BADGES[String(label || "").trim().toUpperCase()] || UNRATED_BADGE;
  return Object.assign({ text: `${found.word} ${found.emoji}` }, found);
}

/** The badge a hound wears, with the tone the page already colours verdicts by. */
export function badgeFor(hound) {
  const label = verdictLabel(hound);
  return Object.assign(badgeForLabel(label), { tone: verdictTone(label), label });
}

// ---- units, order, streaks -------------------------------------------------------------------------

/** A hound's paper units: the average price (the headline) when it has one, else the recorded price. Null with no bets. */
export function unitsOf(hound) {
  const rec = hound && hound.record;
  if (!rec || !isNum(rec.bets) || rec.bets <= 0) return null;
  if (isNum(rec.units_average_price)) return rec.units_average_price;
  return isNum(rec.units_recorded_price) ? rec.units_recorded_price : null;
}

/** Leaderboard order: most paper units first; a dog with no bets yet goes last; ties by more bets, then name. */
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

/** The streak as flames: W3 -> "🔥🔥🔥 W3"; L3 -> "🥶 L3"; null when there is none. */
export function streakView(form) {
  const st = form && form.streak;
  if (!st || !isNum(st.length) || st.length < 1) return null;
  if (st.kind === "W") {
    const flames = st.length >= 2 ? "🔥".repeat(Math.min(st.length, 5)) + " " : "";
    return { kind: "W", length: st.length, tone: "hot", text: `${flames}W${st.length}`,
      label: `${st.length} ${st.length === 1 ? "win" : "wins"} in a row` };
  }
  const ice = st.length >= 2 ? "🥶 " : "";
  return { kind: "L", length: st.length, tone: "cold", text: `${ice}L${st.length}`,
    label: `${st.length} ${st.length === 1 ? "loss" : "losses"} in a row` };
}

/** "+1.8u this week (3-1)" from form.last7, or "" when the dog has not played this week. */
export function weekText(form) {
  const w = form && form.last7;
  if (!w || !isNum(w.bets) || w.bets <= 0) return "";
  return `${fmtUnits(w.units)} this week (${w.wins}-${w.losses})`;
}

/**
 * Hot dog / Ice cold / On tilt, from the last seven days. A dog needs at least three bets that week to be
 * named, hot needs units above zero, cold needs them below, tilt needs a losing run of two or more. Each
 * slot is a different dog, or null when nobody earned it (the page then says nobody did).
 */
export const FORM_MIN_BETS = 3;

export function formStrip(hounds) {
  const live = (hounds || []).filter((x) => x && x.status !== "retired" && x.form && x.form.last7
    && isNum(x.form.last7.bets) && x.form.last7.bets >= FORM_MIN_BETS && isNum(x.form.last7.units));
  const byName = (a, b) => String(a.name || "").localeCompare(String(b.name || ""));
  const hot = live.filter((x) => x.form.last7.units > 0)
    .sort((a, b) => b.form.last7.units - a.form.last7.units || byName(a, b))[0] || null;
  const cold = live.filter((x) => x.form.last7.units < 0 && x !== hot)
    .sort((a, b) => a.form.last7.units - b.form.last7.units || byName(a, b))[0] || null;
  const runLen = (x) => (x.form.streak && x.form.streak.kind === "L" ? x.form.streak.length : 0);
  const tiltable = (hounds || []).filter((x) => x && x.status !== "retired" && x.form && runLen(x) >= 2 && x !== hot);
  const tilt = tiltable.slice().sort((a, b) => runLen(b) - runLen(a)
    || ((a.form.last7 && a.form.last7.units) || 0) - ((b.form.last7 && b.form.last7.units) || 0) || byName(a, b))[0] || null;
  return { hot, cold, tilt };
}

// ---- the retirement rule ---------------------------------------------------------------------------

/** A dog down more than this many units is put down (src/hounds/verdict.py RETIRE_UNITS_BELOW). */
export const RETIRE_UNITS = -25;

/**
 * The dogs nearest the doghouse: still in the race, bets on the board, sorted by how few units stand between
 * them and the -25 line. `cushion` is units + 25. Static: nobody votes on this, the rule decides.
 */
export function closestToRetirement(hounds, n = 3) {
  const out = [];
  for (const hound of hounds || []) {
    if (!hound || hound.status === "retired" || hound.status === "not_started") continue;
    const units = unitsOf(hound);
    if (units === null) continue;
    const cushion = units - RETIRE_UNITS;
    // danger = how much of the walk from zero to the -25 line the dog has already done (0 at or above zero)
    out.push({ hound, units, cushion, danger: Math.max(0, Math.min(1, units / RETIRE_UNITS)) });
  }
  out.sort((a, b) => a.cushion - b.cushion || String(a.hound.name || "").localeCompare(String(b.hound.name || "")));
  return out.slice(0, n);
}

/** "27.4 units to the line", "3.1 units from the doghouse" etc., plainly. */
export function cushionText(entry) {
  const c = entry.cushion;
  if (c <= 0) return "past the line";
  return `${c.toFixed(1)} units from the doghouse`;
}

// ---- who says what ---------------------------------------------------------------------------------

export const FALLBACK_HOUNDMASTER = {
  name: "The Houndmaster",
  catchphrase: "I don't make the rules. I just enforce them.",
  roasts: [
    "That was ugly, and I watched the whole thing.",
    "Down a unit. Sit. Think about what you did.",
    "No excuses. The scoreboard doesn't take excuses.",
    "Tough night. Mostly your fault.",
    "I've seen better picks from a cat on a keyboard.",
  ],
  brags: [
    "Okay. That was good. Don't make a thing of it.",
    "Up on the night. Treat's in the bowl. Behave.",
    "One good night. Don't get cocky. They all get cocky.",
    "Fair is fair: nice work.",
    "That cashed. Do it again tomorrow, if you can.",
  ],
  put_down_lines: ["Down more than 25 units. I don't make the rules."],
};

/** The persona a hound carries (bio, catchphrase, vibe, roasts, brags), or null. */
export function personaOf(hound) {
  const p = hound && hound.persona;
  return p && typeof p === "object" ? p : null;
}

/** Same dog, same day, same line: a stable pick (FNV-1a of "key|day", the same as src/hounds/voice.py). */
export function pickLine(lines, key, day) {
  if (!Array.isArray(lines) || lines.length === 0) return null;
  return lines[hashName(`${key}|${day}`) % lines.length];
}

/**
 * The Houndmaster's line for a dog after its last settled day: a roast after a losing day, a brag after a
 * winning one, null after a flat day or none. The dog's own lines first, the boss's generic ones for a dog
 * with none (a builder's dog). `day` is the settled day the result is from, so the line holds all day.
 */
export function houndmasterLine(hound, houndmaster) {
  const last = hound && hound.form && hound.form.last_day;
  if (!last || (last.result !== "win" && last.result !== "loss")) return null;
  const kind = last.result === "win" ? "brag" : "roast";
  const field = kind === "brag" ? "brags" : "roasts";
  const persona = personaOf(hound);
  const boss = houndmaster && typeof houndmaster === "object" ? houndmaster : FALLBACK_HOUNDMASTER;
  const lines = (persona && persona[field] && persona[field].length ? persona[field] : null)
    || (boss[field] && boss[field].length ? boss[field] : FALLBACK_HOUNDMASTER[field]);
  const line = pickLine(lines, String(hound.id), String(last.date || ""));
  return line ? { kind, line, day: last.date, by: boss.name || FALLBACK_HOUNDMASTER.name } : null;
}

// ---- the graveyard ---------------------------------------------------------------------------------

/** The cause of death in a bettor's words. Unknown causes are quoted as the server wrote them. */
export function causeText(cause) {
  const text = String(cause || "").trim();
  if (!text) return "no reason was given";
  if (/down more than 25 units/i.test(text)) return "Went more than 25 units under.";
  if (/paying the vig/i.test(text)) return "300 bets paying the vig.";
  if (/retired by the owner/i.test(text)) return "Retired by the owner.";
  return text.charAt(0).toUpperCase() + text.slice(1);
}

/** The line on the tombstone: the dog's own epitaph, else a house one. */
export function epitaphFor(hound) {
  const p = personaOf(hound);
  return (p && p.epitaph) || "Gone, but still on the record.";
}

/**
 * A lesson the code wrote (src/hounds/learning/lessons.py one_line), said in camp's words: a rookie "made the
 * team" or was "cut" instead of being promoted or retired, the champion is the starter, and the statistics are
 * plain numbers. Same facts, same figures; only the vocabulary changes. Unknown wording passes through.
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

/** A sentence the server wrote about the learning loop, in camp's words (the loop is camp, a challenger a rookie). */
export function campWords(text) {
  return String(text || "")
    .replace(/\bchallengers\b/g, "rookies").replace(/\bchallenger\b/g, "rookie")
    .replace(/\bThe loop\b/g, "Camp").replace(/\bthe loop\b/g, "camp");
}

export const STATUS_WORDS = {
  running: "Running", benched: "Napping", retired: "Put down 💀", not_started: "Not started",
};

// ---- the decision stream, as chat ------------------------------------------------------------------

/** The headline price of a stream item: the average price when it has one, else the best price. */
export function chatPrice(item) {
  const it = item || {};
  return isNum(it.price_average) ? it.price_average : isNum(it.price) ? it.price : null;
}

/**
 * One chat bubble's words: { lead, rest, game, outcome } where lead is the dog's name, rest is
 * "just tailed the steam on NYY -1.5 at -110", game is the matchup, outcome is "cashed +0.9u" /
 * "lost -1.00u" once graded. A refusal reads "sat this one out". `persona` is the dog's, if known.
 */
export function chatLine(item, hound) {
  const it = item || {};
  const name = it.hound_name || it.name || (hound && hound.name) || "A dog";
  const where = it.game ? String(it.game) : "";
  if (it.refused) {
    const why = it.reason ? String(it.reason).replace(/^Refused: /, "").trim() : "";
    return { lead: name, rest: `sat this one out.${why ? ` ${why.charAt(0).toUpperCase()}${why.slice(1)}` : ""}`,
      game: where, outcome: null, kind: "pass" };
  }
  const persona = personaOf(hound);
  const verb = (persona && persona.verb) || "took";
  const price = chatPrice(it);
  const pick = it.selection || NOT_REPORTED;
  let outcome = null;
  const res = String(it.result || "").toLowerCase();
  if (res === "win" || res === "won") outcome = { tone: "win", text: `cashed${isNum(it.units) ? ` ${fmtUnits(it.units)}` : ""}` };
  else if (res === "loss" || res === "lost") outcome = { tone: "loss", text: `lost${isNum(it.units) ? ` ${fmtUnits(it.units)}` : ""}` };
  else if (res === "push") outcome = { tone: "push", text: "pushed" };
  return { lead: name, rest: `just ${verb} ${pick}${price === null ? "" : ` at ${fmtPrice(price)}`}`,
    game: where, outcome, kind: "bet" };
}

/** Category of a hound, re-exported so a page can import its voice helpers from one place. */
export { categoryOf };
