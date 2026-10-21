/**
 * web/js/first-grade.js: R6, "a hound's first graded ticket" (docs/marketing/GROWTH_PLAYBOOK.md section 2).
 *
 * THE MOMENT. A ticket that was PENDING becomes WON, LOST or PUSH. The first time that happens to a person's own hound is the
 * event the product is built around, so on that page the newly graded tickets flip from PENDING to their grade (400 ms, the chip)
 * and their units count up (500 ms), and the hound's FIRST grade, and only that one, gets the single celebration burst.
 *
 * WINS AND LOSSES ANIMATE IDENTICALLY. Nothing in this file reads a ticket's result: it counts graded tickets, nothing else. The burst
 * is for "your hound's first grade", whatever the grade was. Later grades flip and count up the same way, with no burst, and a loss
 * gets no sad animation either. (Confetti only on wins teaches a person to chase the animation: playbook section 3.2.)
 *
 * HOW THIS BROWSER KNOWS WHICH HOUNDS ARE ITS PERSON'S. The page that saves a hound (the quiz, the builder) calls watchFirstGrade(id),
 * which writes {graded: 0, burst: false} to localStorage. When the hound's page later loads and the graded count is higher than the
 * count last seen, the difference is the number of fresh grades. A hound this browser never watched (somebody else's, or one kept on
 * another device) gets no motion at all: the page has no way to know a grade is new, and it does not guess. Every access is guarded: a
 * blocked store means no motion, never an error.
 *
 * Counts, not ticket ids: the ticket feed carries no stable id, and the newest graded tickets are first, so "n fresh grades" is "the
 * first n rows".
 */

export const GRADE_KEY = "linehound.firstgrade.v1";

function store() {
  try { return window.localStorage || null; } catch (err) { return null; }
}

function read() {
  try {
    const ls = store();
    const raw = ls && ls.getItem(GRADE_KEY);
    const parsed = raw ? JSON.parse(raw) : null;
    return parsed && typeof parsed === "object" ? parsed : {};
  } catch (err) { return {}; }
}

function write(map) {
  try {
    const ls = store();
    if (ls) ls.setItem(GRADE_KEY, JSON.stringify(map));
  } catch (err) { /* a full or blocked store: no motion later, nothing else */ }
}

/** Start watching a hound this browser just kept. Safe to call twice: it never resets what was already seen. */
export function watchFirstGrade(id) {
  if (!id) return;
  const map = read();
  if (map[id]) return;
  map[id] = { graded: 0, burst: false };
  write(map);
}

/** Is this hound one this browser is watching? */
export function isWatched(id) {
  return !!(id && read()[id]);
}

/**
 * Settle the graded count seen on a hound's page against what was last seen.
 * Returns {fresh, burst}: `fresh` newly graded tickets (0 when none or when the hound is not watched), and `burst` true exactly once
 * per hound, the first time any grade is fresh.
 */
export function settleGrades(id, gradedTotal) {
  const none = { fresh: 0, burst: false };
  if (!id || !Number.isFinite(gradedTotal)) return none;
  const map = read();
  const rec = map[id];
  if (!rec) return none;
  const fresh = Math.max(0, gradedTotal - (Number(rec.graded) || 0));
  if (!fresh) return none;
  const burst = !rec.burst;
  map[id] = { graded: gradedTotal, burst: true };
  write(map);
  return { fresh, burst };
}
