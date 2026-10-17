/**
 * NUMBERS FOR A READER, IN THE DISPLAY LAYER ONLY.
 *
 * A brief is written once, frozen, and kept exactly as it was. Its words are
 * never changed here. What a reader meets in them is raw precision: "a 2.4712
 * ERA and 3.5027 FIP", "98.33 innings", "the wind is 12.1 mph from 306 degrees",
 * "the books' 0.5511". This module turns each of those into the figure a person
 * would say aloud, and keeps the EXACT text of the number on the element's
 * `title`, so hovering a figure shows what was published. Nothing is stored,
 * nothing is sent back, and a number this module does not recognise is left
 * as it was.
 *
 *   ERA, FIP, run differential and any other long decimal  ->  two decimals
 *   wOBA and its relatives                                  ->  two decimals
 *   a probability (the books' number, a rate, "fair")       ->  a whole percent
 *   innings (98.33)                                         ->  98 1/3 (one third, written as a
 *                                                              fraction: "98.3" would read as 98 2/3
 *                                                              in baseball notation)
 *   wind "from 306 degrees"                                 ->  "from the northwest"
 *
 * Rules that keep it honest:
 *   - Only a decimal with three or more digits is rounded (a price, a line, a
 *     "7.5 total", "11.9 mph" and "98.1 innings" are already as short as they go);
 *     a two-decimal number becomes a percent only beside plain probability words
 *     ("de-vigged numbers put SD +1.5 near 0.63").
 *   - A number already followed by "%" is left alone.
 *   - A probability is recognised by the words around it (probability, fair, the
 *     books, de-vigged, chance, rate); a number in (0, 1) with no such words is
 *     rounded to two decimals, never turned into a percent on a guess.
 *   - Rounding can only lose digits, never invent them: the title carries the
 *     original token character for character.
 */

import { el } from "./dom.js";

const COMPASS = ["north", "northeast", "east", "southeast", "south", "southwest", "west", "northwest"];

/** 306 -> "northwest" (the direction the wind blows FROM, as the text states it). */
export function compassWord(degrees) {
  const n = ((Number(degrees) % 360) + 360) % 360;
  return COMPASS[Math.round(n / 45) % 8];
}

const STAT_CONTEXT = /(woba|xwoba|obp|slg|ops|avg|era|fip|xfip|whip)/i;
const PROB_CONTEXT = /(probab|de-?vig|fair|books?\b|market|chance|implied|break-?even|my number|our number|win pct|win rate|percent|rate\b|pct|k-bb|strikeout)/i;

// A two-decimal number is only turned into a percent on the plainest probability words.
const STRICT_PROB_CONTEXT = /(probab|de-?vig|fair|implied|break-?even|chance|books')/i;

function statNear(before, after) {
  return STAT_CONTEXT.test(before.slice(-14)) || STAT_CONTEXT.test(after.slice(0, 14));
}

function thirds(frac) {
  if (frac < 0.12) return "";
  if (frac > 0.25 && frac < 0.42) return "⅓";
  if (frac > 0.58 && frac < 0.75) return "⅔";
  return null;
}

/**
 * Split `text` into display pieces: `{text}` for words left as written and
 * `{text, title}` for a number shown shorter than it was published.
 */
export function formatProse(text) {
  const source = String(text === null || text === undefined ? "" : text);
  const pieces = [];
  let cursor = 0;
  const push = (plain) => { if (plain) pieces.push({ text: plain }); };
  // Order matters: the wind phrase and innings first, then bare long decimals.
  const pattern = /(from\s+(\d{1,3}(?:\.\d+)?)\s+degrees)|(\d+\.\d{2,})(\s+innings?\b)|(?<![\d.])(\d+\.\d{2,})(?![\d])(%?)/g;
  let m;
  while ((m = pattern.exec(source)) !== null) {
    push(source.slice(cursor, m.index));
    const whole = m[0];
    cursor = m.index + whole.length;
    if (m[1]) {
      pieces.push({ text: `from the ${compassWord(m[2])}`, title: m[1] });
    } else if (m[3]) {
      const value = Number(m[3]);
      const whole_innings = Math.floor(value);
      const frac = value - whole_innings;
      const word = thirds(frac);
      const shown = word === null ? value.toFixed(1) : `${whole_innings}${word}`;
      pieces.push({ text: `${shown}${m[4]}`, title: whole });
    } else {
      const token = m[5];
      if (m[6]) { push(whole); continue; } // already a percent: as written
      const value = Number(token);
      const before = source.slice(Math.max(0, m.index - 100), m.index);
      const after = source.slice(cursor, cursor + 24);
      const twoDecimals = token.length - token.indexOf(".") - 1 === 2;
      // A short window for the long decimals; the plain probability words may sit a clause back.
      const near = before.slice(twoDecimals ? -100 : -48) + " " + after.slice(0, 20);
      let shown;
      if (value > 0 && value < 1 && !statNear(before, after)
          && (twoDecimals ? STRICT_PROB_CONTEXT : PROB_CONTEXT).test(near)) {
        shown = `${Math.round(value * 100)}%`;
      } else if (twoDecimals) {
        push(whole); // already two decimals and not a probability: as written
        continue;
      } else {
        shown = value.toFixed(2);
      }
      pieces.push({ text: shown, title: token });
    }
  }
  push(source.slice(cursor));
  return pieces;
}

/** The text a reader sees, as one string (what the tests assert on). */
export function proseText(text) {
  return formatProse(text).map((p) => p.text).join("");
}

/** DOM children for an element: plain strings and `<span title="exact">figure</span>`. */
export function proseNodes(text) {
  return formatProse(text).map((p) => (p.title
    ? el("span", { class: "an-num", title: p.title, text: p.text })
    : p.text));
}
