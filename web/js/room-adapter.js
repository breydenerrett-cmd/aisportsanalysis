/**
 * THE KENNEL ROOM: real hound state -> a character state (pure, no DOM, no fetch, no clock of its own).
 *
 * Adapted from the Edge Desk's Floor adapter (a pattern, not a copy: the domain there was trading bots, here it is paper sports-betting
 * hounds). docs/design/KENNEL_ROOM.md is the state table; tests/test_kennel_room.py runs fixtures through this file under node.
 *
 * INPUT (assembled by room-data.js from the endpoints the product already has; every key is optional):
 *   scope        "house" (the LINEHOUND house pack + the Claude Hound, from GET /hounds) or "kennel" (a member's kennel, GET /hounds/kennels/mine)
 *   hounds       the hound rows: { id, name, kind, status, sports, record, open_bets, settled, new, look, persona, trained_times,
 *                coached_from, retired, bankroll, tagline, rule_text }
 *   openBets     { hound id: [bet] }   the open tickets (GET /hounds/{id}/bets?status=open, or the open rows of GET /hounds/stream)
 *   gradedBets   { hound id: [bet] }   recently graded tickets (GET /hounds/{id}/bets?status=graded, or the stream's graded rows)
 *   bets         a flat list of bets (hound_id on each) instead of the two maps above; split here by status
 *   board        null (not read) or { counts: { MLB: 4, NBA: 0 }, total: 4 }: the games LIVE or still to start on today's board, by sport code
 *   headstones   a count, or the list of headstones (the Graveyard)
 *   season       { min_ranked_bets }
 * OPTIONS: { now (ms), localHour (0-23, the viewer's), today ("YYYY-MM-DD" in US Eastern, the slate's own calendar), recentHours, minRanked }
 *
 * OUTPUT: { characters: [...], headstones, counts, leaderId, whiteboard, ticker, board, now }. Each character carries the state, a plain label,
 * the zone it stands in, the dog's pose, an optional bubble (the open pick) or burst (the settled units), its badges and the numbers its card shows.
 *
 * HONESTY RULES (the animation reads real state only):
 *   - a state is only claimed from a fact in the input: no open ticket is never "at its desk"; an unread board is never "scouting";
 *   - "just won" and "just lost" come from graded tickets inside the recent window, dated by `graded_utc` when the row has one and otherwise by the
 *     game's start plus a typical length (the row says `estimated`);
 *   - a ticket priced -200 or worse is never put in a bubble (the product recommends none);
 *   - units are the scoreboard, never "profit"; a crown goes to the units leader only with enough settled bets and units above zero.
 */

export const RECENT_HOURS = 4;          // a graded ticket this recent = a celebration or the rain cloud
export const GAME_HOURS = 3;            // a graded row with no stamp is dated this long after its first pitch
export const NIGHT_START = 23;          // the viewer's local hour at which the kennel goes to sleep ...
export const NIGHT_END = 6;             // ... and wakes up
export const MIN_RANKED = 10;           // mirrors web/js/hounds-season.js MIN_RANKED_BETS
export const PRICE_FLOOR = -200;        // -200 or worse is never shown as a pick
export const ANY_SPORT = ["DOG_MENU", "ALL", "ANY", "*"];

export const STATE_LABEL = {
  pending: "At its desk", won: "Just won", lost: "Just lost", scouting: "Scanning the board",
  nap: "Napping", asleep: "Asleep", training: "At the gym",
};
/** The zone each state stands in (the scene owns the coordinates). */
export const ZONE_OF = { pending: "desk", won: "desk", lost: "bowl", scouting: "floor", nap: "bed", asleep: "bed", training: "gym" };
/** The pose each state asks of the dog rig (dog-rig.js POSES). */
export const POSE_OF = { pending: "thinking", won: "celebrate", lost: "sad", scouting: "thinking", nap: "idle", asleep: "idle", training: "happy" };

const num = (v) => typeof v === "number" && Number.isFinite(v);
const int = (v) => (num(v) ? Math.max(0, Math.round(v)) : 0);
const text = (v) => (typeof v === "string" ? v.replace(/\s+/g, " ").trim() : "");
const ms = (iso) => { const t = Date.parse(String(iso || "")); return Number.isFinite(t) ? t : null; };

// ---- small formatters ------------------------------------------------------------------------------------

/** "+130" / "-115", or "" for anything that is not an American price. */
export function fmtPrice(p) {
  if (!num(p) || Math.abs(p) < 100) return "";
  return `${p > 0 ? "+" : "-"}${Math.abs(Math.round(p))}`;
}

/** "+1.3u", "-1u", "+0.83u": up to two decimals, no trailing zeros. */
export function fmtUnits(u) {
  if (!num(u)) return "";
  const body = Math.abs(u).toFixed(2).replace(/\.?0+$/, "");
  if (body === "0" || body === "") return "0u";
  return `${u > 0 ? "+" : "-"}${body}u`;
}

/** "1u", "0.5u", "2u": a stake with no sign. */
export function fmtStake(u) {
  if (!num(u) || u <= 0) return "1u";
  return `${Number(u.toFixed(2))}u`;
}

/** "2h 5m", "35m", "now". */
export function inText(deltaMs) {
  if (!num(deltaMs) || deltaMs <= 0) return "now";
  const mins = Math.max(1, Math.round(deltaMs / 60000));
  const hrs = Math.floor(mins / 60);
  return hrs ? `${hrs}h ${mins % 60}m` : `${mins}m`;
}

/** The US Eastern calendar date of an instant: the date the slate boards are keyed by. */
export function slateDate(nowMs) {
  try {
    const parts = {};
    for (const p of new Intl.DateTimeFormat("en-US", { timeZone: "America/New_York", year: "numeric", month: "2-digit", day: "2-digit" }).formatToParts(new Date(nowMs))) parts[p.type] = p.value;
    return `${parts.year}-${parts.month}-${parts.day}`;
  } catch (err) {
    return new Date(nowMs).toISOString().slice(0, 10);
  }
}

// ---- tickets ---------------------------------------------------------------------------------------------

const RESULT = { win: "win", won: "win", loss: "loss", lost: "loss", lose: "loss", push: "push", void: "void", voided: "void" };
export function resultOf(bet) {
  const r = bet && typeof bet.result === "string" ? bet.result.trim().toLowerCase() : "";
  return RESULT[r] || "";
}

/** A forward ticket that is still open (not graded, not a refusal, not a rehearsal). */
export function isOpen(bet) {
  if (!bet || typeof bet !== "object" || bet.refused === true || bet.segment === "replay") return false;
  if (resultOf(bet)) return false;
  const st = text(bet.status).toUpperCase();
  return st === "" || st === "OPEN" || st === "PENDING";
}

export function isGraded(bet) {
  if (!bet || typeof bet !== "object" || bet.refused === true || bet.segment === "replay") return false;
  return !!resultOf(bet);
}

/** When a graded ticket settled: { ms, estimated } or null. Never invents a time. */
export function settledAt(bet) {
  const own = ms(bet && bet.graded_utc);
  if (own !== null) return { ms: own, estimated: false };
  const start = ms(bet && bet.start_utc);
  if (start !== null) return { ms: start + GAME_HOURS * 3600000, estimated: true };
  return null;
}

/** "Yankees ML", "Over 8.5", "Red Sox -1.5": the pick in a bettor's short form. */
export function shortPick(bet) {
  const sel = text(bet && bet.selection);
  if (!sel) return "";
  const market = text(bet && bet.market).toLowerCase();
  const won = /^(.*?)\s+to\s+win$/i.exec(sel);
  if (won) return `${won[1]} ML`;
  if (/^(over|under)\b/i.test(sel)) return sel;
  if ((market === "h2h" || market === "moneyline" || market === "ml") && !/\d/.test(sel)) return `${sel} ML`;
  if ((market === "spread" || market === "spreads") && num(bet.line) && !/[+-]?\d+(\.\d+)?\s*$/.test(sel)) return `${sel} ${bet.line > 0 ? "+" : ""}${bet.line}`;
  return sel;
}

/** The bubble for the soonest-starting open ticket, plus "+N more" when there are others. */
export function bubbleFor(open, count, nowMs, stakeUnits) {
  const list = open.slice().sort((a, b) => (ms(a.start_utc) ?? Infinity) - (ms(b.start_utc) ?? Infinity));
  const first = list[0];
  if (!first) return count > 0 ? { text: `${count} open ${count === 1 ? "ticket" : "tickets"}`, tone: "pending", suppressed: false, extra: 0 } : null;
  const price = num(first.price) ? first.price : first.price_average;
  const extra = Math.max(0, count - 1);
  if ((num(price) && price <= PRICE_FLOOR) || first.beyond_cap === true) {
    return { text: extra ? `Open ticket · +${extra} more` : "Open ticket", tone: "pending", suppressed: true, extra };
  }
  const stake = num(first.stake) ? first.stake : num(first.stake_units) ? first.stake_units : stakeUnits;
  const pick = shortPick(first) || "Open ticket";
  const parts = [`${pick}${fmtPrice(price) ? ` ${fmtPrice(price)}` : ""}`, fmtStake(stake)];
  if (extra) parts.push(`+${extra} more`);
  return { text: parts.join(" · "), tone: "pending", suppressed: false, extra };
}

// ---- the board -------------------------------------------------------------------------------------------

/** How many games are on the board for a hound's sports: a number, or null when the board was not read. */
export function boardGamesFor(sports, board) {
  if (!board || typeof board !== "object" || !board.counts || typeof board.counts !== "object") return null;
  const counts = {};
  for (const [k, v] of Object.entries(board.counts)) counts[String(k).toUpperCase()] = int(v);
  const total = num(board.total) ? int(board.total) : Object.values(counts).reduce((a, b) => a + b, 0);
  const list = Array.isArray(sports) ? sports.map((s) => String(s).toUpperCase()) : [];
  if (!list.length || list.some((s) => ANY_SPORT.includes(s))) return total;
  return list.reduce((sum, s) => sum + (counts[s] || 0), 0);
}

// ---- one hound -------------------------------------------------------------------------------------------

function recordOf(hound) {
  const r = (hound && hound.record) || {};
  const wins = int(r.wins), losses = int(r.losses), pushes = int(r.pushes);
  const units = num(r.units_average_price) ? r.units_average_price : (hound && hound.bankroll && num(hound.bankroll.units_total) ? hound.bankroll.units_total : null);
  return { wins, losses, pushes, settled: wins + losses + pushes, bets: int(r.bets) || wins + losses + pushes, units };
}

function isTraining(hound, rec, openCount) {
  if (text(hound.status).toLowerCase() === "training" || hound.training === true) return true;
  // the product has no running "training" status: a training makes the next version at once and its record starts now. A hound whose newest version
  // came from a training and that has not bet yet is the one still at the gym.
  return int(hound.trained_times) > 0 && !!hound.coached_from && rec.settled === 0 && openCount === 0;
}

function stateFor(hound, ctx) {
  const rec = recordOf(hound);
  const open = (ctx.open[hound.id] || []).filter(isOpen);
  const openCount = Math.max(open.length, int(hound.open_bets));
  const graded = (ctx.graded[hound.id] || []).filter(isGraded);
  const status = text(hound.status).toLowerCase();
  const stake = hound.bankroll && num(hound.bankroll.stake_units) ? hound.bankroll.stake_units : 1;

  // the settled tickets inside the recent window, newest first
  const recent = graded.map((b) => ({ b, at: settledAt(b) })).filter((x) => x.at && x.at.ms <= ctx.now + 60000 && ctx.now - x.at.ms <= ctx.recentMs)
    .filter((x) => x.b && (resultOf(x.b) === "win" || resultOf(x.b) === "loss") && num(x.b.units))
    .sort((a, b) => b.at.ms - a.at.ms);
  const net = recent.reduce((s, x) => s + x.b.units, 0);
  const rw = recent.filter((x) => resultOf(x.b) === "win").length, rl = recent.filter((x) => resultOf(x.b) === "loss").length;
  const lastSettle = recent.length ? { net: Math.round(net * 100) / 100, wins: rw, losses: rl, ageMin: Math.max(0, Math.round((ctx.now - recent[0].at.ms) / 60000)), estimated: recent.some((x) => x.at.estimated) } : null;
  const base = { openCount, lastSettle, bubble: null, burst: null, detail: "", reason: "" };

  if (isTraining(hound, rec, openCount)) {
    return Object.assign(base, { state: "training", label: "At the gym", detail: "Fresh from training. Its new record starts now.", reason: "newest version came from training and has no bet yet" });
  }

  if (openCount > 0) {
    const bubble = bubbleFor(open, openCount, ctx.now, stake);
    const starts = open.map((b) => ms(b.start_utc)).filter((t) => t !== null);
    const live = starts.some((t) => t <= ctx.now);
    const next = starts.filter((t) => t > ctx.now).sort((a, b) => a - b)[0];
    const detail = `${openCount} open ${openCount === 1 ? "ticket" : "tickets"}${live ? " · a game is live" : next ? ` · first starts in ${inText(next - ctx.now)}` : ""}`;
    return Object.assign(base, { state: "pending", label: live ? "Game live" : "At its desk", bubble, live, detail, nextStartMs: next || null, reason: "has open tickets" });
  }

  if (recent.length && Math.abs(net) > 0.004) {
    const won = net > 0;
    const tally = `${rw}-${rl}`;
    return Object.assign(base, {
      state: won ? "won" : "lost", label: won ? "Just won" : "Just lost", burst: fmtUnits(net),
      bubble: { text: `${fmtUnits(net)} (${tally})`, tone: won ? "win" : "loss", suppressed: false, extra: 0 },
      detail: `${tally} on tickets that settled in the last ${ctx.recentHours} hours`, reason: "graded tickets inside the recent window",
    });
  }

  // nothing open and nothing just settled: scouting, a nap, or sleep
  const night = ctx.night;
  const running = status === "running" || status === "";
  const games = boardGamesFor(hound.sports, ctx.board);
  if (running && games !== null && games > 0) {
    if (night) return Object.assign(base, { state: "asleep", label: "Asleep", detail: "Overnight. Back on the board in the morning.", reason: "viewer's local night" });
    return Object.assign(base, { state: "scouting", label: "Scanning the board", detail: `${games} ${games === 1 ? "game" : "games"} left on today's board in its sports. No pick yet.`, games, reason: "games on the board, no pick" });
  }
  if (night) return Object.assign(base, { state: "asleep", label: "Asleep", detail: "Overnight. Back on the board in the morning.", reason: "viewer's local night" });
  if (status === "benched") return Object.assign(base, { state: "nap", label: "Idle", detail: "No ticket in 7+ days.", reason: "benched" });
  if (status === "not_started") return Object.assign(base, { state: "nap", label: "Not started", detail: "It has not placed a ticket yet.", reason: "not started" });
  if (!running) return Object.assign(base, { state: "nap", label: "Resting", detail: "Not betting right now.", reason: `status ${status}` });
  if (games === null) return Object.assign(base, { state: "nap", label: "No open pick", detail: "Nothing open right now.", reason: "no open ticket; the board was not read" });
  const betToday = [...(ctx.graded[hound.id] || []), ...open].some((b) => b && b.date === ctx.today);
  return Object.assign(base, { state: "nap", label: betToday ? "Done for today" : "No games left", detail: betToday ? "Its tickets for today are graded." : "No games left on today's board in its sports.", reason: betToday ? "bet today, none left" : "no games on the board" });
}

// ---- the whole room --------------------------------------------------------------------------------------

function headstoneCount(h) {
  if (Array.isArray(h)) return h.length;
  return int(h);
}

function groupBets(input) {
  const open = {}, graded = {};
  for (const [id, list] of Object.entries(input.openBets || {})) open[id] = Array.isArray(list) ? list : [];
  for (const [id, list] of Object.entries(input.gradedBets || {})) graded[id] = Array.isArray(list) ? list : [];
  for (const b of Array.isArray(input.bets) ? input.bets : []) {
    if (!b || !b.hound_id) continue;
    if (isOpen(b)) (open[b.hound_id] ||= []).push(b);
    else if (isGraded(b)) (graded[b.hound_id] ||= []).push(b);
  }
  return { open, graded };
}

export function build(input, opts) {
  input = input && typeof input === "object" ? input : {};
  opts = opts || {};
  const now = num(opts.now) ? opts.now : Date.now();
  const localHour = num(opts.localHour) ? opts.localHour : new Date(now).getHours();
  const night = localHour >= NIGHT_START || localHour < NIGHT_END;
  const recentHours = num(opts.recentHours) && opts.recentHours > 0 ? opts.recentHours : RECENT_HOURS;
  const minRanked = num(opts.minRanked) ? opts.minRanked : (input.season && num(input.season.min_ranked_bets) && input.season.min_ranked_bets > 0 ? input.season.min_ranked_bets : MIN_RANKED);
  const today = typeof opts.today === "string" && opts.today ? opts.today : slateDate(now);
  const { open, graded } = groupBets(input);
  const scope = input.scope === "kennel" ? "kennel" : "house";
  const board = input.board && typeof input.board === "object" && input.board.counts ? input.board : null;
  const ctx = { now, night, today, open, graded, board, recentMs: recentHours * 3600000, recentHours };

  let buried = 0;
  const seen = new Set();
  const characters = [];
  for (const hound of Array.isArray(input.hounds) ? input.hounds : []) {
    if (!hound || typeof hound !== "object" || !hound.id || seen.has(hound.id)) continue;
    seen.add(hound.id);
    const status = text(hound.status).toLowerCase();
    if (status === "buried") { buried += 1; continue; }                           // buried: not in the room (a headstone in the corner)
    if (hound.retired === true || status === "retired" || (hound.retired && typeof hound.retired === "object")) continue;   // a retired model has left the room
    const st = stateFor(hound, ctx);
    const rec = recordOf(hound);
    characters.push({
      id: String(hound.id), name: text(hound.name) || String(hound.id), kind: text(hound.kind) || (scope === "kennel" ? "user" : "house"),
      mine: scope === "kennel", href: `hound.html?id=${encodeURIComponent(String(hound.id))}`,
      state: st.state, label: st.label, zone: ZONE_OF[st.state], pose: POSE_OF[st.state],
      bubble: st.bubble, burst: st.burst, detail: st.detail, reason: st.reason, live: !!st.live, games: st.games ?? null,
      openCount: st.openCount, lastSettle: st.lastSettle, nextStartMs: st.nextStartMs || null,
      sports: Array.isArray(hound.sports) ? hound.sports.map((s) => String(s)) : [],
      record: { wins: rec.wins, losses: rec.losses, pushes: rec.pushes, bets: rec.bets, settled: rec.settled, units: rec.units },
      crown: false, trained: int(hound.trained_times),
      tagline: text(hound.tagline), rule: text(hound.rule_text), hound,
    });
  }

  // the season leader wears the crown: the most units among hounds with enough settled bets, and above zero (no crown for a leader who is down)
  const ranked = characters.filter((c) => c.record.settled >= minRanked && num(c.record.units) && c.record.units > 0)
    .sort((a, b) => b.record.units - a.record.units || b.record.settled - a.record.settled);
  const leader = ranked.length ? ranked[0] : null;
  if (leader) leader.crown = true;

  const counts = {};
  for (const c of characters) counts[c.state] = (counts[c.state] || 0) + 1;
  const whiteboard = ranked.slice(0, 3).map((c) => ({ id: c.id, name: c.name, units: c.record.units, bets: c.record.settled }));
  const gamesTotal = board ? (num(board.total) ? int(board.total) : Object.values(board.counts).reduce((a, b) => a + int(b), 0)) : null;
  return {
    scope, now, night, today, minRanked, characters, counts, leaderId: leader ? leader.id : null, whiteboard,
    headstones: Math.max(headstoneCount(input.headstones), buried),
    board: { known: !!board, total: gamesTotal },
    ticker: { open: characters.reduce((n, c) => n + c.openCount, 0), live: characters.filter((c) => c.live).length, games: gamesTotal, hounds: characters.length },
  };
}
