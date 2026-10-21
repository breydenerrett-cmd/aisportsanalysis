/**
 * THE KENNEL ROOM's data: the requests, and nothing else. Each loader returns the INPUT room-adapter.js `build()` reads; none of them
 * decides a state. Every request is soft: a failure leaves that part of the input empty (the adapter then claims less, never more).
 *
 *   loadHouse()          the LINEHOUND house pack and the Claude Hound:
 *                          GET /hounds                       the hounds (kind "house"), their records and open-ticket counts
 *                          GET /hounds/stream?page_size=100  the newest tickets of every hound: the open ones and the recently graded ones
 *                          GET /sports/now                   today's board (signed-in members only; the route needs an account)
 *                          GET /hounds/graveyard             the headstones, for the corner stone (read once every ten minutes)
 *   loadKennel(data)     a signed-in member's kennel:
 *                          GET /hounds/kennels/mine          (or the payload My Kennel already holds)
 *                          GET /hounds/{id}/bets?status=open     one per hound that says it has open tickets
 *                          GET /hounds/{id}/bets?status=graded   one per hound that has settled bets
 *                          GET /sports/now                   today's board
 *
 * THE BOARD. /sports/now lists the games live and the games starting in the next 24 hours, by sport. The room means "today's board": a live game,
 * or one that starts later on today's slate date (US Eastern, the calendar the boards are keyed by). Tomorrow's games are not counted, so a
 * hound that has finished its day naps instead of scouting tomorrow's slate all night.
 */

import { apiGet, getToken } from "./api.js";
import { isWarming } from "./hounds-core.js";
import { slateDate } from "./room-adapter.js";

export const POLL_MS = 45000;
export const STREAM_URL = "/hounds/stream?page=1&page_size=100";
const GRAVEYARD_TTL_MS = 10 * 60 * 1000;

const graveyard = { at: 0, count: 0 };

async function soft(path) {
  try { return await apiGet(path); } catch (err) { return null; }
}

/** { counts: { MLB: 4 }, total } for the games live now or still to start on today's slate, or null when the board is not readable. */
export async function loadBoard(nowMs) {
  if (!getToken()) return null;                                  // /sports/now needs an account: a visitor's room does not guess a board
  const data = await soft("/sports/now");
  if (!data || !Array.isArray(data.families)) return null;
  const today = slateDate(nowMs);
  const counts = {};
  let total = 0;
  for (const fam of data.families) {
    if (!fam || !fam.code) continue;
    const code = String(fam.code).toUpperCase();
    const live = Array.isArray(fam.live) ? fam.live.length : 0;
    const later = (Array.isArray(fam.upcoming_24h) ? fam.upcoming_24h : []).filter((g) => {
      const t = Date.parse(g && g.start_utc);
      return Number.isFinite(t) && t > nowMs && slateDate(t) === today;
    }).length;
    counts[code] = live + later;
    total += live + later;
  }
  return { counts, total };
}

async function headstoneCount(nowMs) {
  if (nowMs - graveyard.at < GRAVEYARD_TTL_MS) return graveyard.count;
  const data = await soft("/hounds/graveyard");
  if (data && Array.isArray(data.headstones)) { graveyard.count = data.headstones.length; graveyard.at = nowMs; }
  return graveyard.count;
}

/** The house room. Resolves { warming: true } while the server is still working the numbers out, { error: true } when nothing answered. */
export async function loadHouse(nowMs = Date.now()) {
  const [board, stone, stream, data] = await Promise.all([
    loadBoard(nowMs), headstoneCount(nowMs), soft(STREAM_URL), soft("/hounds")]);
  if (!data || typeof data !== "object") return { error: true };
  if (isWarming(data)) return { warming: true };
  const hounds = (Array.isArray(data.hounds) ? data.hounds : []).filter((x) => x && x.kind === "house");
  const ids = new Set(hounds.map((x) => x.id));
  const bets = (stream && Array.isArray(stream.items) ? stream.items : []).filter((b) => b && ids.has(b.hound_id) && b.segment !== "replay");
  return { scope: "house", hounds, bets, board, headstones: stone, season: data.season || null };
}

/** A member's kennel room from the kennel payload (`known`, when My Kennel already has it) or a fresh GET /hounds/kennels/mine. */
export async function loadKennel(known, nowMs = Date.now()) {
  let data = known || null;
  if (!data) {
    try { data = await apiGet("/hounds/kennels/mine"); } catch (err) { data = null; }
  }
  if (!data || !Array.isArray(data.dogs)) return { error: true };
  const hounds = data.dogs.filter((d) => d && !d.retired);
  const openBets = {}, gradedBets = {};
  await Promise.all(hounds.map(async (d) => {
    const id = encodeURIComponent(d.id);
    const wantOpen = Number.isFinite(d.open_bets) && d.open_bets > 0;
    const wantGraded = d.record && ((d.record.wins || 0) + (d.record.losses || 0)) > 0;
    const [o, g] = await Promise.all([
      wantOpen ? soft(`/hounds/${id}/bets?page=1&page_size=8&segment=forward&status=open`) : null,
      wantGraded ? soft(`/hounds/${id}/bets?page=1&page_size=6&segment=forward&status=graded`) : null,
    ]);
    if (o && Array.isArray(o.items)) openBets[d.id] = o.items;
    if (g && Array.isArray(g.items)) gradedBets[d.id] = g.items;
  }));
  const board = await loadBoard(nowMs);
  return { scope: "kennel", hounds, openBets, gradedBets, board, headstones: Array.isArray(data.graveyard) ? data.graveyard : 0, season: data.season || null };
}
