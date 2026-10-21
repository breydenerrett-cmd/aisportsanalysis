/**
 * THE ACCESSORY LAYERS: the body (shoulders, hoodie, jersey with its number), the neck pieces (default collar, chain, spiked collar,
 * bandana) and the head pieces (cap, headband, visor, sunglasses, the Professor's round glasses).
 *
 * Every piece is placed from the breed's ANCHORS (dog-breeds.js `anchorsOf`: the crown, the brow line, the eye line, the chin, the
 * neck, the chest, the hood), never from fixed numbers, so each one lines up on a Greyhound's blade and a Mastiff's block alike.
 * The art style decides the finish: metal (gold and silver gradients) on Elite, a heavier chain and a darker hoodie on Street, flat
 * colour and a thick outline on Mascot. Every colour is a constant or a mix; the jersey number is the only text and it is a
 * whitelisted integer from the look.
 */

import { INK, n, path, ell, grp, mix, f } from "./dog-art.js";
import { collarFor } from "./dog-tiers.js";

const ACCENT = "#2FD07A";
const GOLD = "#E0B24A";
const GOLD_DARK = "#8A6A1F";

const metalGold = (st) => (st.metal ? "url(#lh-gold)" : GOLD);
const metalSilver = (st) => (st.metal ? "url(#lh-silver)" : "#C9D0DA");

// ---- the body ---------------------------------------------------------------------------------------------------

/** The shoulders and chest. `top` is where the neck meets them. */
function torsoD(bulk, top) {
  const X = (x) => f(60 + (x - 60) * bulk);
  return `M${X(-8)} 126 C${X(-6)} ${f(top + 16)} ${X(14)} ${f(top + 4)} ${X(40)} ${f(top)} Q60 ${f(top + 7)} ${X(80)} ${f(top)} C${X(106)} ${f(top + 4)} ${X(126)} ${f(top + 16)} ${X(128)} 126 Z`;
}

/** The torso's top: the chin or the shoulder line, whichever is lower. */
export const torsoTop = (a) => Math.max(94, a.chin.y + 1);

/**
 * The body layer. Returns { body: nodes behind the head (neck, shoulders, hood, hoodie, jersey), number: the jersey number node or null }.
 * The default (no body piece) is bare shoulders with the coat's chest light.
 */
export function bodyShapes(look, coat, a, K, st, geo) {
  const top = torsoTop(a), bulk = geo.bulk || 1, nk = a.neck.half;
  const neckD = `M${f(60 - nk)} ${f(a.chin.y - 18)} L${f(60 + nk)} ${f(a.chin.y - 18)} L${f(60 + nk + 12)} ${f(top + 10)} L${f(60 - nk - 12)} ${f(top + 10)} Z`;
  const neck = K.solid(neckD, mix(coat.base, coat.shade, 0.35), {});
  const D = torsoD(bulk, top);
  if (look.body === "hoodie") {
    const hood = grp("dk-hood", K.solid(`M${f(60 - a.hood.half)} ${f(a.hood.y + 16)} C${f(60 - a.hood.half - 2)} ${f(a.hood.y - 22)} ${f(60 + a.hood.half + 2)} ${f(a.hood.y - 22)} ${f(60 + a.hood.half)} ${f(a.hood.y + 16)} C${f(60 + a.hood.half - 8)} ${f(a.hood.y + 30)} ${f(60 - a.hood.half + 8)} ${f(a.hood.y + 30)} ${f(60 - a.hood.half)} ${f(a.hood.y + 16)} Z`, st.hoodLight, { rim: true }));
    const body = [
      hood,
      ...K.solid(D, st.hood, { rim: true }),
      path(`M${f(60 - nk - 4)} ${f(top + 2)} Q60 ${f(top + 14)} ${f(60 + nk + 4)} ${f(top + 2)} Q60 ${f(top + 7)} ${f(60 - nk - 4)} ${f(top + 2)} Z`, { fill: mix(st.hood, INK, 0.45) }),
      path(`M${f(52)} ${f(top + 6)} L${f(51)} ${f(top + 19)} M${f(68)} ${f(top + 6)} L${f(69)} ${f(top + 19)}`, { fill: "none", stroke: "#E9ECF1", "stroke-width": 1.8, "stroke-linecap": "round" }),
      K.fine(path(`M${f(60 - 24 * bulk)} 124 Q60 ${f(Math.min(112, top + 12))} ${f(60 + 24 * bulk)} 124`, { fill: "none", stroke: mix(st.hood, "#FFFFFF", 0.14), "stroke-width": 1.4 })),
    ];
    if (st.metal) body.push(path(`M60 ${f(top + 8)} V124`, { stroke: "url(#lh-silver)", "stroke-width": 1.6, fill: "none" }));
    if (st.spray) body.push(path(`M${f(60 - 20 * bulk)} ${f(top + 22)} Q60 ${f(top + 16)} ${f(60 + 20 * bulk)} ${f(top + 23)}`, { fill: "none", stroke: "#FF4FA3", "stroke-width": 2.4, "stroke-linecap": "round", opacity: ".85" }));
    return { body: [...neck, ...body], number: null };
  }
  if (look.body === "jersey") {
    const body = [
      ...neck,
      ...K.solid(D, st.jersey, { rim: true }),
      path(`M${f(60 - 13 * bulk)} ${f(top + 1)} L60 ${f(top + 10)} L${f(60 + 13 * bulk)} ${f(top + 1)} L${f(60 + 13 * bulk)} ${f(top + 4)} L60 ${f(top + 13.5)} L${f(60 - 13 * bulk)} ${f(top + 4)} Z`, { fill: ACCENT, stroke: K.oc, "stroke-width": f(K.ow * 0.4), "stroke-linejoin": "round" }),
      path(`M${f(60 - 44 * bulk)} ${f(top + 10)} Q${f(60 - 30 * bulk)} ${f(top + 3)} ${f(60 - 20 * bulk)} ${f(top + 3)} M${f(60 + 44 * bulk)} ${f(top + 10)} Q${f(60 + 30 * bulk)} ${f(top + 3)} ${f(60 + 20 * bulk)} ${f(top + 3)}`, { fill: "none", stroke: ACCENT, "stroke-width": 2.4, "stroke-linecap": "round" }),
    ];
    let number = null;
    if (look.number !== null && look.number !== undefined) {
      number = n("text", {
        x: 60, y: f(Math.min(118, top + 20.5)), "text-anchor": "middle", "font-size": 14, "font-weight": 800, "font-family": "Instrument Sans, Arial, Helvetica, sans-serif",
        fill: "#0E1116", "data-number": String(look.number),
      }, String(look.number));
    }
    return { body, number };
  }
  const body = [
    ...neck,
    ...K.solid(D, coat.base, { rim: true }),
    path(`M${f(60 - 22 * bulk)} ${f(top + 5)} C${f(60 - 14 * bulk)} ${f(top + 20)} ${f(60 + 14 * bulk)} ${f(top + 20)} ${f(60 + 22 * bulk)} ${f(top + 5)} C${f(60 + 12 * bulk)} ${f(top + 12)} ${f(60 - 12 * bulk)} ${f(top + 12)} ${f(60 - 22 * bulk)} ${f(top + 5)} Z`, { fill: coat.light, opacity: ".5" }),
  ];
  return { body, number: null };
}

// ---- neck pieces ------------------------------------------------------------------------------------------------

/** A band hugging the neck below the chin, as a stroke: an outline stroke under a colour stroke. */
function band(a, K, color, w) {
  const nk = a.neck.half, y = a.chin.y;
  const d = `M${f(60 - nk + 1)} ${f(y - 14)} Q60 ${f(y + 24)} ${f(60 + nk - 1)} ${f(y - 14)}`;
  return [
    path(d, { fill: "none", stroke: K.oc, "stroke-width": f(w + K.ow * 0.9), "stroke-linecap": "round" }),
    path(d, { fill: "none", stroke: color, "stroke-width": w, "stroke-linecap": "round" }),
  ];
}

/** Points along the band's centre line (its quadratic curve) with the outward normal, for spikes. */
function along(a, count) {
  const nk = a.neck.half, y = a.chin.y;
  const P0 = [60 - nk + 1, y - 14], C = [60, y + 24], P2 = [60 + nk - 1, y - 14];
  const out = [];
  for (let i = 0; i < count; i++) {
    const t = 0.18 + (0.64 * i) / (count - 1);
    const x = (1 - t) * (1 - t) * P0[0] + 2 * (1 - t) * t * C[0] + t * t * P2[0];
    const yy = (1 - t) * (1 - t) * P0[1] + 2 * (1 - t) * t * C[1] + t * t * P2[1];
    const dx = 2 * (1 - t) * (C[0] - P0[0]) + 2 * t * (P2[0] - C[0]);
    const dy = 2 * (1 - t) * (C[1] - P0[1]) + 2 * t * (P2[1] - C[1]);
    const len = Math.hypot(dx, dy) || 1;
    out.push({ x, y: yy, tx: dx / len, ty: dy / len, nx: -dy / len, ny: dx / len });
  }
  return out;
}

/** The pieces on the neck. Returns { behind: nodes drawn before the head, front: nodes drawn after it (the chain) }. */
export function neckPieces(look, a, K, st, coat, version) {
  const behind = [], front = [];
  const y = a.chin.y;
  if (look.neck === "collar") {
    behind.push(grp("dk-acc dk-acc--collar", [
      ...band(a, K, "#16181D", 5.4),
      path(along(a, 7).map((p) => `M${f(p.x - p.tx * 2.2)} ${f(p.y - p.ty * 2.2)} L${f(p.x + p.nx * 5.4)} ${f(p.y + p.ny * 5.4)} L${f(p.x + p.tx * 2.2)} ${f(p.y + p.ty * 2.2)} Z`).join(" "),
        { fill: metalSilver(st), stroke: K.oc, "stroke-width": f(Math.max(0.5, K.ow * 0.3)), "stroke-linejoin": "round" }),
      K.small ? null : ell(60, y + 5.5, 3.4, 3.4, "none", { stroke: metalSilver(st), "stroke-width": 1.4 }),
    ]));
  } else if (look.neck === "bandana") {
    const nk = a.neck.half + 6, tipY = Math.min(118, y + 23);
    const col = st.id === "elite" ? "#1E2D57" : st.id === "street" ? "#F2C94C" : "#E4572E";
    behind.push(grp("dk-acc dk-acc--bandana", [
      ...K.solid(`M${f(60 - nk)} ${f(y - 6)} Q60 ${f(y + 4)} ${f(60 + nk)} ${f(y - 6)} L${f(60 + 5)} ${f(tipY - 2)} Q60 ${f(tipY + 2)} ${f(60 - 5)} ${f(tipY - 2)} Z`, col, { rim: true }),
      K.fine(path(`M${f(60 - nk * 0.55)} ${f(y + 1)} l0 0.1 M${f(60)} ${f(y + 6)} l0 0.1 M${f(60 + nk * 0.55)} ${f(y + 1)} l0 0.1 M${f(60 - 8)} ${f(y + 11)} l0 0.1 M${f(60 + 8)} ${f(y + 11)} l0 0.1 M60 ${f(y + 16)} l0 0.1`,
        { fill: "none", stroke: "#FFFFFF", "stroke-width": 2.6, "stroke-linecap": "round", opacity: ".6" })),
      path(`M${f(60 - nk)} ${f(y - 6)} L${f(60 - nk - 7)} ${f(y - 1)} L${f(60 - nk - 2)} ${f(y + 5)} Z M${f(60 + nk)} ${f(y - 6)} L${f(60 + nk + 7)} ${f(y - 1)} L${f(60 + nk + 2)} ${f(y + 5)} Z`, { fill: col, stroke: K.oc, "stroke-width": f(K.ow * 0.5), "stroke-linejoin": "round" }),
    ]));
  } else if (look.body !== "hoodie" && look.body !== "jersey") {
    // the default collar: the brand-green band and a gold tag
    // a trained hound's collar wears its version's metal (dog-tiers.js); a v1 hound keeps the brand-green band and the gold tag
    const tier = collarFor(version, st);
    behind.push(grp("dk-collar", tier
      ? [...band(a, K, tier.band, 4.6), ell(60, y + 11.5, 4.3, 4.3, tier.tag, { stroke: tier.tagLine, "stroke-width": 1 })]
      : [...band(a, K, ACCENT, 4.2), ell(60, y + 11.5, 3.5, 3.5, metalGold(st), { stroke: GOLD_DARK, "stroke-width": 0.9 })]));
  }
  if (look.neck === "chain") {
    const nk = a.neck.half + 1, depth = Math.max(8, Math.min(16, 109 - y));
    const d = `M${f(60 - nk)} ${f(y - 12)} Q60 ${f(y + 2 * depth + 12)} ${f(60 + nk)} ${f(y - 12)}`;
    const py = y + depth + 2;
    front.push(grp("dk-acc dk-acc--chain", [
      path(d, { fill: "none", stroke: K.oc, "stroke-width": f(st.chainW + K.ow * 0.8), "stroke-linecap": "round" }),
      path(d, { fill: "none", stroke: metalGold(st), "stroke-width": st.chainW, "stroke-dasharray": `${f(st.chainW * 1.25)} ${f(st.chainW * 0.55)}`, "stroke-linecap": "round" }),
      K.fine(path(d, { fill: "none", stroke: "#FFF3C2", "stroke-width": f(st.chainW * 0.28), "stroke-dasharray": `${f(st.chainW * 0.5)} ${f(st.chainW * 1.3)}`, "stroke-linecap": "round", opacity: ".8" })),
      path(`M60 ${f(py - 6.4)} L${f(60 + 6)} ${f(py - 1.4)} L${f(60 + 6)} ${f(py + 3.6)} L60 ${f(py + 7)} L${f(60 - 6)} ${f(py + 3.6)} L${f(60 - 6)} ${f(py - 1.4)} Z`, { fill: metalGold(st), stroke: K.oc, "stroke-width": f(K.ow * 0.5), "stroke-linejoin": "round" }),
      K.fine(path(`M${f(60 - 2.4)} ${f(py - 0.6)} h4.8 M60 ${f(py - 3)} v6`, { fill: "none", stroke: GOLD_DARK, "stroke-width": 1.3, "stroke-linecap": "round" })),
    ]));
  }
  return { behind, front };
}

// ---- head pieces ------------------------------------------------------------------------------------------------

const CAP = { mascot: "#2B5FD9", street: "#2A2E37", elite: "#1B2D52" };

/** Cap, headband or visor, placed on the crown and brow anchors. Returns a node or null. */
export function headPiece(look, a, K, st) {
  // the pieces sit a little above the brow line so the eyes under them stay visible (a cap pulled over the eyes would hide the menace)
  const by = a.brow.y - 6, L = a.brow.left, R = a.brow.right, ty = a.crown.y - 12;
  if (look.head === "cap") {
    const base = CAP[st.id] || CAP.mascot;
    const trim = st.metal ? "#E0B24A" : ACCENT;
    const crownD = `M${f(L - 1)} ${f(by + 1)} C${f(L - 2)} ${f(ty + 8)} ${f(60 - 22)} ${f(ty)} 60 ${f(ty)} C${f(60 + 22)} ${f(ty)} ${f(R + 2)} ${f(ty + 8)} ${f(R + 1)} ${f(by + 1)} Q60 ${f(by + 6)} ${f(L - 1)} ${f(by + 1)} Z`;
    return grp("dk-acc dk-acc--cap", [
      ...K.solid(crownD, base, { rim: true, key: true }),
      K.fine(path(`M60 ${f(ty + 1)} Q${f(60 - 5)} ${f((ty + by) / 2)} ${f(60 - 4)} ${f(by + 4)} M60 ${f(ty + 1)} Q${f(60 + 5)} ${f((ty + by) / 2)} ${f(60 + 4)} ${f(by + 4)}`, { fill: "none", stroke: mix(base, "#FFFFFF", 0.22), "stroke-width": 1, opacity: ".7" })),
      K.fine(ell(60, by + 8, (R - L) * 0.4, 2.6, INK, { opacity: ".28" })),
      ...K.solid(`M${f(L - 1)} ${f(by + 1)} Q60 ${f(by + 13)} ${f(R + 1)} ${f(by + 1)} Q60 ${f(by + 3.4)} ${f(L - 1)} ${f(by + 1)} Z`, mix(base, "#FFFFFF", 0.14), { sh: false }),
      path(`M${f(L + 3)} ${f(by - 1)} Q60 ${f(by + 6)} ${f(R - 3)} ${f(by - 1)}`, { fill: "none", stroke: trim, "stroke-width": 2.2, "stroke-linecap": "round" }),
      path(`M60 ${f(by - 15)} l5 5 l-5 5 l-5 -5 Z`, { fill: trim, stroke: K.oc, "stroke-width": f(K.ow * 0.35), "stroke-linejoin": "round" }),
      n("circle", { cx: 60, cy: f(ty + 0.6), r: 2.2, fill: trim }),
    ]);
  }
  if (look.head === "headband") {
    const col = st.id === "street" ? "#FF4FA3" : ACCENT;
    return grp("dk-acc dk-acc--headband", [
      ...K.solid(`M${f(L)} ${f(by - 4)} Q60 ${f(by + 3)} ${f(R)} ${f(by - 4)} L${f(R + 0.5)} ${f(by + 2.6)} Q60 ${f(by + 9.6)} ${f(L - 0.5)} ${f(by + 2.6)} Z`, col, { rim: true }),
      path(`M${f(R - 5)} ${f(by + 1)} L${f(R + 9)} ${f(by - 3)} L${f(R + 6)} ${f(by + 4)} L${f(R + 11)} ${f(by + 8)} L${f(R - 2)} ${f(by + 5)} Z`, { fill: mix(col, INK, 0.2), stroke: K.oc, "stroke-width": f(K.ow * 0.4), "stroke-linejoin": "round" }),
    ]);
  }
  if (look.head === "visor") {
    const strap = st.metal ? "url(#lh-silver)" : "#E9ECF1";
    return grp("dk-acc dk-acc--visor", [
      path(`M${f(L)} ${f(by - 4)} Q60 ${f(by + 3)} ${f(R)} ${f(by - 4)}`, { fill: "none", stroke: K.oc, "stroke-width": f(4 + K.ow * 0.8), "stroke-linecap": "round" }),
      path(`M${f(L)} ${f(by - 4)} Q60 ${f(by + 3)} ${f(R)} ${f(by - 4)}`, { fill: "none", stroke: strap, "stroke-width": 4, "stroke-linecap": "round" }),
      ...K.solid(`M${f(L + 5)} ${f(by - 1)} Q60 ${f(by + 15)} ${f(R - 5)} ${f(by - 1)} Q60 ${f(by + 4)} ${f(L + 5)} ${f(by - 1)} Z`, st.metal ? "#CDE4F5" : "#6FC3F0", { rim: true, sh: true }),
      K.fine(path(`M${f(L + 12)} ${f(by + 3)} Q60 ${f(by + 11)} ${f(R - 12)} ${f(by + 3)}`, { fill: "none", stroke: "#FFFFFF", "stroke-width": 1, opacity: ".7" })),
    ]);
  }
  return null;
}

/** Sunglasses, drawn across the eye line: two angular lenses slanted like the brow, a bridge and the arms. */
export function sunglasses(a, K, st) {
  const { y, left, right, ew, eh } = a.eyes;
  const lens = (cx, side) => {
    const ox = cx + side * (ew + 4.4), ix = cx - side * (ew + 2.2);
    return `M${f(ox)} ${f(y - eh * 2.1)} L${f(ix)} ${f(y - eh * 1.2)} Q${f(ix - side * 0.6)} ${f(y + eh * 2.4)} ${f(cx - side * (ew - 1.5))} ${f(y + eh * 2.7)} Q${f(cx + side * (ew + 0.5))} ${f(y + eh * 3.1)} ${f(ox)} ${f(y + eh * 1.3)} Z`;
  };
  const frame = st.metal ? "url(#lh-gold)" : K.oc;
  return grp("dk-acc dk-acc--sunglasses", [
    path(`M${f(left - ew - 4.4)} ${f(y - eh * 0.6)} L${f(left - ew - 12)} ${f(y - eh * 1.8)} M${f(right + ew + 4.4)} ${f(y - eh * 0.6)} L${f(right + ew + 12)} ${f(y - eh * 1.8)}`, { fill: "none", stroke: K.oc, "stroke-width": 2.2, "stroke-linecap": "round" }),
    path(`M${f(left + ew + 2)} ${f(y - eh * 1.2)} Q60 ${f(y - eh * 2)} ${f(right - ew - 2)} ${f(y - eh * 1.2)}`, { fill: "none", stroke: K.oc, "stroke-width": 2.4, "stroke-linecap": "round" }),
    path(lens(left, -1), { fill: "#0B0C10", stroke: frame, "stroke-width": f(Math.max(1.1, K.ow * 0.55)), "stroke-linejoin": "round" }),
    path(lens(right, 1), { fill: "#0B0C10", stroke: frame, "stroke-width": f(Math.max(1.1, K.ow * 0.55)), "stroke-linejoin": "round" }),
    K.small ? null : path(`M${f(left - ew * 0.2)} ${f(y - eh * 0.4)} l${f(ew * 0.9)} ${f(-eh * 0.5)} M${f(right - ew * 0.2)} ${f(y - eh * 0.4)} l${f(ew * 0.9)} ${f(-eh * 0.5)}`, { fill: "none", stroke: "#8FD0FF", "stroke-width": 1.5, "stroke-linecap": "round", opacity: ".8" }),
  ]);
}

/** The Professor's round glasses (a trait of one dog, not a look choice). */
export function roundGlasses(a, K) {
  const { y, left, right, ew, eh } = a.eyes, r = Math.max(ew, eh * 1.6) + 3.4, gold = GOLD;
  const rim = (x) => n("circle", { cx: f(x), cy: f(y), r: f(r), fill: "#FFFFFF", "fill-opacity": 0.12, stroke: gold, "stroke-width": 1.9 });
  return grp("dk-acc dk-acc--glasses", [
    rim(left), rim(right),
    path(`M${f(left + r)} ${f(y - 1)} Q60 ${f(y - 4.5)} ${f(right - r)} ${f(y - 1)}`, { fill: "none", stroke: gold, "stroke-width": 1.9, "stroke-linecap": "round" }),
    path(`M${f(left - r)} ${f(y)} L${f(left - r - 5)} ${f(y - 2)} M${f(right + r)} ${f(y)} L${f(right + r + 5)} ${f(y - 2)}`, { fill: "none", stroke: gold, "stroke-width": 1.6, "stroke-linecap": "round" }),
  ]);
}
