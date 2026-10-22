/**
 * THE KENNEL ROOM, layout (pure: no DOM, no fetch, no clock; also runs under node, tests/test_kennel_room.py).
 *
 * WHERE EACH HOUND STANDS (planRoom). The room is a stack of zone bands, top to bottom: the floor (scouting), the water bowl (just lost), the desks (an
 * open pick, just won), the gym (fresh from training) and the beds (naps, sleep). Every band is the full width of the room and is cut into as many
 * seats across as the stage's width allows (columnsFor); a zone that has more hounds than seats wraps into more rows, up to a few rows, and past that
 * it shows its first N hounds (orderCharacters: the season leader first, then the most recent activity) and a "+K more" seat that opens the list
 * filtered to that zone. The room's height follows the rows, so no two seats, labels or signs can share a place. Only the first N are DRAWN; the list
 * under the room holds every hound, from the same state.
 *
 * A hound carries one label above it: the pick bubble ("Yankees ML +135 · 1u · +1 more") while it has a ticket open, or the settled units
 * ("+1.3u", "-1u") for a moment after a result. Hounds stand about one seat apart and the room can be wider than the screen, so three things keep the
 * labels readable (the hound's state is never touched, only where its label sits):
 *   bubbleParts   the bubble is one line; the pick truncates with an ellipsis, the "+N more" tail never does
 *   assignTiers   labelled neighbours in one row take turns on two heights, so two labels at the same height are two seats apart
 *   placeLabels   on a phone the frame shows a slice of the room: a label of a hound in view slides sideways until it is whole inside the slice
 *                 (and clear of the label beside it); the label of a hound out of view that would be cut by the frame's border is not drawn
 */

export const LABEL_GAP = 6;       // px kept between two labels at one height

/** The bubble's text in two parts: the pick (which may truncate) and the " · +N more" tail (which never does). Together they are the adapter's string. */
export function bubbleParts(bubble) {
  if (!bubble || !bubble.text) return ["", ""];
  const extra = Number(bubble.extra) || 0;
  const tail = extra > 0 ? ` · +${extra} more` : "";
  return tail && bubble.text.endsWith(tail) ? [bubble.text.slice(0, -tail.length), tail] : [bubble.text, ""];
}

/** A label's rough width in view units (1000 across), enough to tell whether two labels in a row would touch: a bubble caps at 200, a float is a few characters. */
function guessWidth(c) {
  const bubble = c.bubble && c.state === "pending";
  const len = bubble ? c.bubble.text.length : String(c.burst || "").length;
  return bubble ? Math.min(200, len * 6.4 + 18) : len * 9 + 12;
}

/**
 * chars: the adapter's characters; slots: Map id -> { xy: [x, y] } (view units); opts.widths: Map id -> the label's measured width in view units (the
 * scene's; a guess stands in without it). Returns Map id -> 0 | 1 for every hound that carries a label.
 * Labelled hounds of one zone and one row go left to right; a label hugs its hound (tier 0) unless it would touch the last label at that height, and then it
 * takes the other height (tier 1: raised, or, at the front desk row, tucked below the desk's lip: room-scene.js picks the direction).
 */
export function assignTiers(chars, slots, opts = {}) {
  const rows = new Map();
  for (const c of chars) {
    if (!(c.bubble && c.state === "pending") && !c.burst) continue;
    const slot = slots.get(c.id);
    if (!slot) continue;
    const key = `${c.zone}|${slot.xy[1]}`;
    if (!rows.has(key)) rows.set(key, []);
    const real = opts.widths && opts.widths.get(c.id);             // the label's measured width (view units) when the scene has one, else a guess
    rows.get(key).push({ id: c.id, x: slot.xy[0], w: real > 0 ? real : guessWidth(c) });
  }
  const tier = new Map();
  const GAP = 8;
  for (const list of rows.values()) {
    list.sort((a, b) => a.x - b.x);
    const right = [-Infinity, -Infinity];
    for (const e of list) {
      const left = e.x - e.w / 2;
      const t = left >= right[0] + GAP ? 0 : left >= right[1] + GAP ? 1 : (right[0] <= right[1] ? 0 : 1);
      tier.set(e.id, t);
      right[t] = e.x + e.w / 2;
    }
  }
  return tier;
}

/**
 * items: [{ group, c (the label's natural centre, px), w (its width, px), owner (its hound's centre, px) }]; [lo, hi] is the visible slice (px, the same
 * scale). Returns one { shift, hidden } per item: shift (px) to add to the label's position, hidden when it would be cut and its hound is out of view.
 */
export function placeLabels(items, lo, hi, gap = LABEL_GAP) {
  const out = items.map(() => ({ shift: 0, hidden: false, fit: null }));
  const groups = new Map();
  items.forEach((it, i) => {
    const left = it.c - it.w / 2, right = it.c + it.w / 2;
    if (!(it.owner >= lo && it.owner <= hi)) {                    // its hound is out of view: a label cut by the frame's border belongs to nobody on screen
      if (right > lo && left < hi) out[i].hidden = true;
      return;
    }
    if (!groups.has(it.group)) groups.set(it.group, []);
    groups.get(it.group).push(i);
  });
  for (const idx of groups.values()) {
    idx.sort((a, b) => items[a].c - items[b].c);
    // labels that cannot all stand side by side inside the slice share it: the longest are cut to a width (an ellipsis on the pick), the short ones keep theirs
    const w = fitWidths(idx.map((i) => items[i].w), hi - lo, gap);
    idx.forEach((i, k) => { if (w[k] < items[i].w - 0.01) out[i].fit = Math.floor(w[k]); });
    const nat = idx.map((i, k) => items[i].c - w[k] / 2);
    const left = nat.map((x, k) => Math.max(lo, Math.min(x, hi - w[k])));             // whole inside the slice
    for (let k = 1; k < left.length; k++) left[k] = Math.max(left[k], left[k - 1] + w[k - 1] + gap);     // push right off a neighbour
    for (let k = left.length - 1; k >= 0; k--) {                                       // then back from the right-hand side
      const room = k === left.length - 1 ? hi - w[k] : left[k + 1] - gap - w[k];
      left[k] = Math.max(lo, Math.min(left[k], room));
    }
    idx.forEach((i, k) => { out[i].shift = left[k] + w[k] / 2 - items[i].c; });          // the label's centre moves from the hound's by this much
  }
  return out;
}

/** Widths for labels that must share `room` px with `gap` between them: the ones that already fit keep their width, the longest are cut to an equal share of what is left. */
function fitWidths(w, room, gap) {
  const avail = room - gap * (w.length - 1);
  if (w.reduce((a, b) => a + b, 0) <= avail) return w.slice();
  const order = w.map((x, k) => k).sort((a, b) => w[a] - w[b]);
  const out = w.slice();
  let left = avail, count = w.length;
  for (let n = 0; n < order.length; n++) {
    const share = left / count;
    if (w[order[n]] <= share) { left -= w[order[n]]; count -= 1; continue; }
    for (const j of order.slice(n)) out[j] = Math.max(20, share);
    break;
  }
  return out;
}

// ---- where each hound stands -----------------------------------------------------------------------------

export const VIEW_W = 1000;           // the room's width in view units; its height grows with the rows (MIN_H and up)
export const MIN_H = 600;
export const ZONE_ORDER = ["floor", "bowl", "desk", "gym", "bed"];
/** The most rows a zone wraps into before it shows "+K more". */
export const ZONE_ROWS = { floor: 3, bowl: 1, desk: 2, gym: 1, bed: 3 };
export const ZONE_NAME = { floor: "On the floor", bowl: "At the water bowl", desk: "At the desks", gym: "At the gym", bed: "In the beds" };
export const COL_PX = 108;            // the narrowest a seat may be on screen, in px: a name tag (a seat less 18 px) always has room for a few letters and an ellipsis
const SIDE = 55;                      // view units kept clear at each side of the seats
const GEO = {
  top: 252,                                                    // the first band starts at the baseboard
  pad: 12,                                                     // under the last row of a band (the desks, beds and bowls reach a little further down: the next band's first row starts well clear)
  above: { floor: 110, bowl: 118, desk: 166, gym: 132, bed: 132 },   // from a band's top to its first row's feet: a hound (92) + its crown, a sign, or a bubble's two heights
  step: { floor: 112, bowl: 118, desk: 172, gym: 112, bed: 112 },    // from one row's feet to the next
};

/** The widest a label may be, in view units: two seats less a gap (so two labels at one height two seats apart never touch), and no wider than the room at the end seats. */
export function labelMax(pitch) {
  return Math.round(Math.min(2 * pitch - 14, 2 * SIDE + pitch - 2) * 10) / 10;
}

/** How many seats fit across the stage (`widthPx`: its width on screen; unknown -> the desktop's). Never fewer than 4, never more than 10. */
export function columnsFor(widthPx) {
  const w = Number(widthPx) > 0 ? Number(widthPx) : 1000;
  return Math.max(4, Math.min(10, Math.floor((w * (VIEW_W - 2 * SIDE) / VIEW_W) / COL_PX)));
}

/**
 * The stable order hounds are shown in when a zone is full: the season leader first, then the most recent activity (a settled result, newest first;
 * then a game that is live, then the soonest first pitch among open tickets), then the most open tickets, the most settled bets, and at last the name
 * and the id, so the same input always gives the same order.
 */
export function orderCharacters(chars) {
  const rank = (c) => [
    c.crown ? 0 : 1,
    c.lastSettle ? 0 : 1, c.lastSettle ? c.lastSettle.ageMin : 0,
    c.live ? 0 : 1, c.nextStartMs || 0,
    -(c.openCount || 0), -((c.record && c.record.settled) || 0),
  ];
  return chars.slice().sort((a, b) => {
    const ra = rank(a), rb = rank(b);
    for (let i = 0; i < ra.length; i++) if (ra[i] !== rb[i]) return ra[i] - rb[i];
    const na = String(a.name || ""), nb = String(b.name || "");
    return na < nb ? -1 : na > nb ? 1 : String(a.id) < String(b.id) ? -1 : String(a.id) > String(b.id) ? 1 : 0;
  });
}

/**
 * chars: the adapter's characters; opts: { width (px), previous (Map id -> { zone, i }: the seats the hounds already have) }.
 * Returns { cols, pitch, H, zones, seats, hidden }:
 *   zones   zone -> { rows, cap, top, bottom, feet (first row's feet), step, n (hounds in the zone), shown, used (Set of seat numbers), more: null | { k, i, xy } }
 *           only for a zone that is drawn: the desks and the beds always (an honest empty room shows empty desks and beds), the others when a hound is in them
 *   seats   Map id -> { zone, i, xy: [x, y] } for the hounds that are drawn (feet position, view units)
 *   hidden  Map zone -> [ids] of the hounds the zone had no seat for (they are in the list, and behind its "+K more")
 * A hound keeps its seat while it stays in its zone and the seat still exists; a new one takes the first free seat.
 */
export function planRoom(chars, opts = {}) {
  const cols = columnsFor(opts.width);
  const pitch = (VIEW_W - 2 * SIDE) / cols;
  const previous = opts.previous || new Map();
  const byZone = new Map(ZONE_ORDER.map((z) => [z, []]));
  for (const c of orderCharacters(chars)) if (byZone.has(c.zone)) byZone.get(c.zone).push(c);
  const zones = {}, seats = new Map(), hidden = new Map();
  let y = GEO.top;
  for (const zone of ZONE_ORDER) {
    const list = byZone.get(zone);
    const cap = ZONE_ROWS[zone] * cols;
    const over = list.length > cap;
    const show = over ? cap - 1 : list.length;                   // the last seat of a full zone is the "+K more" token
    const shown = list.slice(0, show);
    const taken = new Set(), at = new Map();
    for (const c of shown) {                                    // keep the seat a hound already has in this zone
      const p = previous.get(c.id);
      if (p && p.zone === zone && Number.isInteger(p.i) && p.i >= 0 && p.i < (over ? cap - 1 : cap) && !taken.has(p.i)) { taken.add(p.i); at.set(c.id, p.i); }
    }
    for (const c of shown) {
      if (at.has(c.id)) continue;
      let i = 0; while (taken.has(i)) i += 1;
      taken.add(i); at.set(c.id, i);
    }
    const last = over ? cap - 1 : (taken.size ? Math.max(...taken) : -1);
    const always = zone === "desk" || zone === "bed";
    const rows = last >= 0 ? Math.floor(last / cols) + 1 : always ? 1 : 0;
    if (!rows) continue;
    const top = y, step = GEO.step[zone];
    const feet = top + (zone === "desk" && !list.length ? GEO.above.floor : GEO.above[zone]);      // empty desks need no room above them for a bubble
    const xy = (i) => [Math.round((SIDE + pitch * ((i % cols) + 0.5)) * 100) / 100, feet + Math.floor(i / cols) * step];
    for (const c of shown) seats.set(c.id, { zone, i: at.get(c.id), xy: xy(at.get(c.id)) });
    if (over) hidden.set(zone, list.slice(show).map((c) => c.id));
    const bottom = feet + (rows - 1) * step + GEO.pad;
    zones[zone] = { rows, cap, top, bottom, feet, step, n: list.length, shown: shown.length, used: taken,
      more: over ? { k: list.length - show, i: cap - 1, xy: xy(cap - 1) } : null };
    y = bottom;
  }
  return { cols, pitch, H: Math.max(MIN_H, Math.ceil(y + 26)), zones, seats, hidden };      // 26 under the last band: the beds' rims and a napping hound's shadow are drawn inside the room
}
