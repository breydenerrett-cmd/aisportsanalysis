/**
 * The dog look: the whitelisted choices a dog wears, and nothing else.
 *
 * THE LOOK IS A SET OF CHOICES, NEVER MARKUP. `look` is the JSON the server validated (src/hounds/interact/look.py): coat,
 * eyes, bg, head, face, neck, body, number. This file holds those key tables and the colours they stand for. A key it does
 * not know falls back to the default, so nothing a server sends can inject a colour string or a node.
 * tests/test_hounds_interact_web.py holds the key lists here to the server's.
 *
 * It is split out of dog-avatar.js so the drawing code (dog-rig.js) and the old `dogBadge` entry point can both read the
 * tables without importing each other. dog-avatar.js re-exports everything here, so existing imports keep working.
 *
 * `lookFor(seed)` is the DEFAULT look of a dog that has never been dressed (every house dog): a stable pick of coat, eyes
 * and background from the same tables, chosen by hashing its id, so the leaderboard is a pack of different dogs rather
 * than one dog twelve times. It is presentation only; nothing is stored and nothing is sent.
 */

export const COATS = {
  tan: { base: "#C9A06B", shade: "#9F7746", light: "#E2C79B" },
  black: { base: "#2B2F36", shade: "#14171B", light: "#4A515C" },
  white: { base: "#E9ECF1", shade: "#C3C9D3", light: "#FFFFFF" },
  grey: { base: "#8C95A4", shade: "#646C7A", light: "#B5BCC8" },
  brown: { base: "#7A5638", shade: "#573A24", light: "#9A7455" },
  golden: { base: "#E0B24A", shade: "#BC8B2A", light: "#F1D58F" },
  red: { base: "#B4533C", shade: "#8A3A29", light: "#D07C63" },
  merle: { base: "#7E93B2", shade: "#596C8A", light: "#A9B8CE" },
};
export const EYES = { brown: "#5A3A1E", amber: "#C98A1B", blue: "#4A8FD8", green: "#4BA36B", hazel: "#8A6B2F" };
export const BACKGROUNDS = {
  navy: ["#1B3157", "#0C1730"], slate: ["#38465A", "#1B2330"], charcoal: ["#3A3F48", "#181B20"],
  forest: ["#1F5A40", "#0E2A1E"], maroon: ["#63293A", "#2F121B"], teal: ["#18646C", "#0A2F34"],
  violet: ["#51397F", "#241A3E"], sand: ["#8A7450", "#493C27"],
};
export const HEAD = ["none", "cap", "headband", "visor"];
export const FACE = ["none", "sunglasses"];
export const NECK = ["none", "chain"];
export const BODY = ["none", "hoodie", "jersey"];
export const DEFAULT_LOOK = { coat: "tan", eyes: "brown", bg: "navy", head: "none", face: "none", neck: "none", body: "none", number: null };

/** A look with every key checked against the tables above; anything unknown becomes the default. */
export function cleanLook(look) {
  const src = look && typeof look === "object" ? look : {};
  const pick = (value, allowed, fallback) => (typeof value === "string" && allowed.includes(value) ? value : fallback);
  const number = Number.isInteger(src.number) && src.number >= 0 && src.number <= 99 ? src.number : null;
  const body = pick(src.body, BODY, "none");
  return {
    coat: pick(src.coat, Object.keys(COATS), DEFAULT_LOOK.coat), eyes: pick(src.eyes, Object.keys(EYES), DEFAULT_LOOK.eyes),
    bg: pick(src.bg, Object.keys(BACKGROUNDS), DEFAULT_LOOK.bg), head: pick(src.head, HEAD, "none"),
    face: pick(src.face, FACE, "none"), neck: pick(src.neck, NECK, "none"), body, number: body === "jersey" ? number : null,
  };
}

/** A small stable hash of a string (FNV-1a), for picking a default look and breed from an id. */
export function hashStr(text) {
  let x = 2166136261;
  const str = String(text === undefined || text === null ? "" : text);
  for (let i = 0; i < str.length; i++) { x ^= str.charCodeAt(i); x = Math.imul(x, 16777619); }
  return x >>> 0;
}

/** The default look of a dog nobody has dressed: coat, eyes and background chosen by the hash of its id. No accessories. */
export function lookFor(seed) {
  const x = hashStr(seed);
  const coats = Object.keys(COATS), eyes = Object.keys(EYES), bgs = Object.keys(BACKGROUNDS);
  return cleanLook({ coat: coats[x % coats.length], eyes: eyes[(x >>> 5) % eyes.length], bg: bgs[(x >>> 9) % bgs.length] });
}

/** A random complete look, for the studio's Randomize button. Presentation only: the owner still has to save it. */
export function randomLook(rand = Math.random) {
  const one = (list) => list[Math.min(list.length - 1, Math.floor(rand() * list.length))];
  const body = one(BODY);
  return cleanLook({
    coat: one(Object.keys(COATS)), eyes: one(Object.keys(EYES)), bg: one(Object.keys(BACKGROUNDS)),
    head: one(HEAD), face: rand() < 0.3 ? "sunglasses" : "none", neck: rand() < 0.3 ? "chain" : "none",
    body, number: body === "jersey" ? Math.floor(rand() * 100) : null,
  });
}
