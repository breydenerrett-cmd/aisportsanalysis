/**
 * TONIGHT, the pure half (web/js/tonight.js draws it). Approved plan: docs/HOUND_LOOP_PLAN.md, phase 4, "Guided flow".
 *
 * Nothing here fetches and nothing here invents a number: every function takes payloads the server already sent
 * (GET /hounds/kennels/mine, GET /hounds/{id}/bets, GET /sports/now, GET /sports/season, GET /hounds) and says what is in them.
 *
 *   keepTickets        a list of tickets with refusals and any ticket at -200 or worse taken out (the public cap, applied a second time here)
 *   tonightEnd         the end of "tonight" in the viewer's zone: 5 AM the next morning, so a late West Coast game is still tonight
 *   checkingGames      the games coming up in the sports the member's hounds bet, soonest first, with which hounds cover each
 *   suggestSport       the in-season sport with the most stored games that none of the hounds bet yet (the "add NBA" prompt)
 *   recapRows          the most recent day (within three days) on which the member's hounds had settled tickets, per hound
 *   recapSentence      "Underdog Gus went 2-1 last night"
 *   nextStep           the ONE primary prompt at the top of the page, and a secondary one
 *
 * Times are the viewer's: the day is judged on the viewer's own calendar (Date's local getters), never on UTC.
 */

import { onlyTickets, ticketState, ticketPrice, betsOf } from "./hounds-board.js";
import { formatStamp } from "./local-time.js";

export const CAP = -200;
export const SMALL_SAMPLE = 20;
export const TONIGHT_ROWS = 8;
export const RECAP_DAYS = 3;

const WEEKDAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];

const ms = (iso) => {
  const t = Date.parse(String(iso || ""));
  return Number.isFinite(t) ? t : null;
};

/** The viewer's calendar day as a whole number, so two moments compare by days. */
export function localDay(t) {
  const d = new Date(t);
  return Math.round(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()) / 86400000);
}

/** The tickets a page may show: real plays only, nothing at -200 or worse (the server drops them; this drops them again). */
export function keepTickets(items) {
  return onlyTickets(items).filter((t) => {
    if (t.beyond_cap === true) return false;
    const p = ticketPrice(t);
    return p === null || p > CAP;
  });
}

/** 5 AM local on the morning after `now`'s evening (or today's 5 AM when it is not yet 5), as epoch ms. */
export function tonightEnd(now = Date.now()) {
  const d = new Date(now);
  const end = new Date(d.getFullYear(), d.getMonth(), d.getDate() + (d.getHours() < 5 ? 0 : 1), 5, 0, 0, 0);
  return end.getTime();
}

const active = (dogs) => (Array.isArray(dogs) ? dogs : []).filter((d) => d && d.id && !d.retired && d.status !== "retired");
const sportsOf = (d) => (Array.isArray(d && d.sports) ? d.sports.map((x) => String(x).toLowerCase()) : []);
/** A hound with no sport list is not known NOT to bet a sport, so it stays on (the live board's rule). */
const covers = (d, code) => { const s = sportsOf(d); return !s.length || s.includes(String(code).toLowerCase()); };

/** The member's sports, as the labels the server uses (upper-case codes), from the hounds' own lists. */
export function memberSports(dogs) {
  const out = [];
  for (const d of active(dogs)) for (const s of sportsOf(d)) if (!out.includes(s.toUpperCase())) out.push(s.toUpperCase());
  return out;
}

/**
 * The games to be checked tonight. `families` is GET /sports/now's list. Returns
 * { games: [{id, name, family, label, start, dogs: [name]}], later: {family: nextIso}, sports: [code], live: n }:
 * `games` start before `tonightEnd`, `later` is the next start of a sport with none tonight (for "Tomorrow 1:05 PM PT").
 */
export function checkingGames(families, dogs, now = Date.now()) {
  const mine = active(dogs);
  const end = tonightEnd(now);
  const games = [];
  const later = {};
  const sports = [];
  let live = 0;
  for (const f of Array.isArray(families) ? families : []) {
    const code = String(f && f.code || "");
    const who = mine.filter((d) => covers(d, code));
    if (!code || !who.length) continue;
    sports.push(code);
    live += Array.isArray(f.live) ? f.live.length : 0;
    let tonight = 0;
    for (const ev of Array.isArray(f.upcoming_24h) ? f.upcoming_24h : []) {
      const start = ms(ev.start_utc);
      if (start === null || start < now) continue;
      if (start > end) { if (!later[code] || start < ms(later[code])) later[code] = ev.start_utc; continue; }
      tonight++;
      games.push({ id: String(ev.event_id || `${code}-${games.length}`), name: `${ev.away || "TBD"} at ${ev.home || "TBD"}`, family: code,
        label: String(f.label || code), start, startIso: ev.start_utc, dogs: who.map((d) => d.name) });
    }
    if (!tonight && f.next_start_utc && !later[code]) later[code] = f.next_start_utc;
  }
  games.sort((a, b) => a.start - b.start || a.id.localeCompare(b.id));
  return { games, later, sports, live };
}

/** The sport to offer: in season, with stored games, that none of the active hounds bet. {code, label, chip, games} or null. */
export function suggestSport(season, dogs) {
  const have = new Set(memberSports(dogs));
  const list = season && Array.isArray(season.sports) ? season.sports : [];
  const open = list.filter((s) => s && s.code && s.in_season && Number(s.games_7d) > 0 && !have.has(String(s.code).toUpperCase()));
  open.sort((a, b) => Number(b.games_7d) - Number(a.games_7d));
  const top = open[0];
  return top ? { code: String(top.code), label: String(top.label || top.code), chip: String(top.chip || ""), games: Number(top.games_7d) } : null;
}

const when = (t) => ms(t.start_utc) ?? ms(t.graded_utc);

/**
 * The last day the member's hounds settled something, and what each did. `graded` is {hound id: [ticket]} (settled tickets, newest
 * first). The day is the day the game STARTED, on the viewer's calendar, no more than RECAP_DAYS back. Returns
 * { gap, word, rows: [{dog, wins, losses, pushes, settled, lost: [ticket]}] } or null when nothing settled in the window.
 */
export function recapRows(dogs, graded, now = Date.now()) {
  const today = localDay(now);
  const per = [];
  for (const dog of active(dogs)) {
    const list = ((graded && graded[dog.id]) || []).filter((t) => ["won", "lost", "push"].includes(ticketState(t)));
    for (const t of list) {
      const at = when(t);
      if (at === null || at > now) continue;
      const gap = today - localDay(at);
      if (gap < 0 || gap > RECAP_DAYS) continue;
      per.push({ dog, t, gap });
    }
  }
  if (!per.length) return null;
  const gap = Math.min(...per.map((p) => p.gap));
  const rows = [];
  for (const dog of active(dogs)) {
    const mine = per.filter((p) => p.dog.id === dog.id && p.gap === gap).map((p) => p.t);
    if (!mine.length) continue;
    const count = (s) => mine.filter((t) => ticketState(t) === s).length;
    rows.push({ dog, wins: count("won"), losses: count("lost"), pushes: count("push"), settled: mine.length, lost: mine.filter((t) => ticketState(t) === "lost") });
  }
  const dayOf = new Date(now - gap * 86400000);
  const word = gap === 1 ? "last night" : gap === 0 ? "earlier today" : `on ${WEEKDAYS[dayOf.getDay()]}`;
  rows.sort((a, b) => b.settled - a.settled || a.dog.name.localeCompare(b.dog.name));
  return { gap, word, rows };
}

/** "Underdog Gus went 2-1 last night" ("2-1-1" with a push). A sample of one is said as one bet. */
export function recapSentence(row, word) {
  const rec = `${row.wins}-${row.losses}${row.pushes ? `-${row.pushes}` : ""}`;
  return `${row.dog.name} went ${rec} ${word}`;
}

export const kennelTab = (id, tab) => `kennel.html?dog=${encodeURIComponent(id)}&tab=${tab}`;
export const recordHref = (id) => `record.html?id=${encodeURIComponent(id)}`;
export const copyHref = (id) => `build-a-hound.html?from=${encodeURIComponent(id)}`;

/**
 * The one primary prompt and its quieter partner. Every href is a page that exists: the quiz, the kennel studio's tabs (?dog=&tab=),
 * the record page, the leaderboard.
 * ctx: { dogs, openCount, recap }
 */
export function nextStep(ctx) {
  const dogs = active(ctx && ctx.dogs);
  if (!dogs.length) {
    return { key: "create", text: "Make a hound and its record starts at zero.", primary: { text: "Make your first hound", href: "quiz.html" },
      secondary: { text: "See the Hounds first", href: "hounds.html" } };
  }
  const recap = ctx && ctx.recap;
  const lossRow = recap ? recap.rows.find((r) => r.losses > 0 && r.losses >= r.wins) || recap.rows.find((r) => r.losses > 0) : null;
  if (lossRow) {
    return { key: "lost", text: `${lossRow.dog.name} lost ${lossRow.losses === 1 ? "a ticket" : `${lossRow.losses} tickets`} ${recap.word}. Find out why before it bets again.`,
      primary: { text: "Ask why", href: kennelTab(lossRow.dog.id, "ask") }, secondary: { text: "Retune", href: kennelTab(lossRow.dog.id, "rules") } };
  }
  const first = dogs[0];
  if (!(ctx && ctx.openCount > 0)) {
    return { key: "idle", text: `Nothing is open. Test ${first.name}'s rule on the last 30 days, or find a hound to copy.`,
      primary: { text: "Backtest 30 days", href: kennelTab(first.id, "backtest") }, secondary: { text: "Find a hound to copy", href: "hounds.html" } };
  }
  return { key: "open", text: "Your hounds have tickets open. Check a record while they play.",
    primary: { text: `See ${first.name}'s record`, href: recordHref(first.id) }, secondary: { text: "Backtest a tweak", href: kennelTab(first.id, "backtest") } };
}

/** "Today 7:05 PM PT" in the viewer's zone, or "" when the stamp does not read. */
export function lockWords(iso, now = new Date(Date.now())) {
  return formatStamp("t", iso, now);
}

/** A hound's record as "12-8 · 20 settled", with the small-sample call-out under SMALL_SAMPLE settled bets. */
export function recordLine(dog) {
  const rec = (dog && dog.record) || {};
  const n = betsOf(dog);
  if (!n) return "No settled bets yet";
  const text = `${rec.wins ?? 0}-${rec.losses ?? 0}${rec.pushes ? `-${rec.pushes}` : ""} · ${n} settled`;
  return n < SMALL_SAMPLE ? `${text} · small sample` : text;
}
