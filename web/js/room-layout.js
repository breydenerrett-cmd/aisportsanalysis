/**
 * THE KENNEL ROOM, label layout (pure: no DOM, no fetch, no clock; also runs under node, tests/test_kennel_room.py).
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
 * chars: the adapter's characters; slots: Map id -> { xy: [x, y] } (view units). Returns Map id -> 0 | 1 for every hound that carries a label.
 * Labelled hounds of one zone and one row go left to right; a label hugs its hound (tier 0) unless it would touch the last label at that height, and then it
 * takes the other height (tier 1: raised, or, at the front desk row, tucked below the desk's lip: room-scene.js picks the direction).
 */
export function assignTiers(chars, slots) {
  const rows = new Map();
  for (const c of chars) {
    if (!(c.bubble && c.state === "pending") && !c.burst) continue;
    const slot = slots.get(c.id);
    if (!slot) continue;
    const key = `${c.zone}|${slot.xy[1]}`;
    if (!rows.has(key)) rows.set(key, []);
    rows.get(key).push({ id: c.id, x: slot.xy[0], w: guessWidth(c) });
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
  const out = items.map(() => ({ shift: 0, hidden: false }));
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
    const w = idx.map((i) => items[i].w);
    const nat = idx.map((i) => items[i].c - items[i].w / 2);
    const left = nat.map((x, k) => Math.max(lo, Math.min(x, hi - w[k])));             // whole inside the slice
    for (let k = 1; k < left.length; k++) left[k] = Math.max(left[k], left[k - 1] + w[k - 1] + gap);     // push right off a neighbour
    for (let k = left.length - 1; k >= 0; k--) {                                       // then back from the right-hand side
      const room = k === left.length - 1 ? hi - w[k] : left[k + 1] - gap - w[k];
      left[k] = Math.max(lo, Math.min(left[k], room));
    }
    idx.forEach((i, k) => { out[i].shift = left[k] - nat[k]; });
  }
  return out;
}
