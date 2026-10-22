/**
 * WHAT A TRAINED HOUND WEARS (the on-the-hound half of the version tiers, dog-tiers.js).
 *
 * A version is the same hound grown up, so the breed and the coat never change; what changes is what it wears and how it is drawn:
 *
 *   v2   a bandana in the tier's metal, knotted at the sides with two tails that stick out past the jaw
 *   v3   + a vest (two dark panels, a trimmed front hem, a chest strap with a buckle) and a bolder brow ridge (the outline is bolder too:
 *        dog-tiers.js `tierStyle`)
 *   v4   + a domed plate over each shoulder, and a soft glow round each eye
 *   v5+  + a mantle: wings behind the shoulders that rise up beside the head like a high collar, and an aura round the hound
 *
 * Everything is placed from the breed's ANCHORS (dog-breeds.js `anchorsOf`) and its body bulk, never from fixed numbers, so each piece
 * lines up on a Greyhound's blade and a Mastiff's block alike. Each tier also changes the hound's OUTLINE (the bandana's tails, the
 * plates, the mantle's wings): the training evolution (dog-evolve.js) plays the old and new hound as white silhouettes, and the
 * morph has to read there. At 44px and under (`K.small`) the fine lines are left out and the heavy pieces stay.
 *
 * Pure SVG from the toolkit's own pieces, createElementNS only. Every colour is a constant here or a tier colour handed in by
 * dog-tiers.js (a hex or a `url(#lh-...)` gradient from dog-defs.js); nothing comes from the server. The result is a pure function of
 * (version flags, breed anchors, kit): no clock, no random.
 */

import { n, path, grp, ell, f, mix } from "./dog-art.js";

const VEST = "#262D3A";
const STEEL = "#566277";

/**
 * `v` the version's flags (dog-tiers.js `versionTier`), `T` the tier's colours, `fill` the tier's metal for this art style, `a` the breed's
 * anchors, `K` the kit and `geo` the breed's landmarks (its body bulk). Returns { cape, gear, brow, eyes }:
 *   cape   behind the torso: the mantle's wings
 *   gear   over the torso and behind the head, in this order: the vest, the shoulder plates, the bandana
 *   brow   a bolder brow ridge over each eye, drawn on the head
 *   eyes   a soft glow round each eye, drawn first inside the eyes group so it sits behind the eyes themselves
 */
export function gearShapes(v, T, fill, a, K, geo) {
  const out = { cape: [], gear: [], brow: [], eyes: [] };
  const small = K.small;
  const top = Math.max(94, a.chin.y + 1), bulk = (geo && geo.bulk) || 1, nk = a.neck.half, cy = a.chin.y;
  const X = (d, s) => f(60 + s * d * bulk);          // a distance from the centre line, scaled by the breed's bulk
  const Y = (y) => f(Math.min(121, y));
  const rim = (w = 0.7) => ({ stroke: K.oc, "stroke-width": f(Math.max(0.9, K.ow * w)), "stroke-linejoin": "round" });
  const both = (fn) => [fn(-1), fn(1)];

  // the mantle's wings, behind the torso (v5): they flare out past the shoulders and rise up beside the head like a high collar
  if (v.mantle) {
    const cloth = mix(T.dark, T.flat, 0.3);
    out.cape.push(grp("dk-tier dk-tier--mantle", both((s) => grp("", [
      ...K.solid(`M${X(nk - 4, s)} ${Y(top - 4)} C${X(nk + 2, s)} ${Y(top - 22)} ${X(38, s)} ${Y(top - 34)} ${X(47, s)} ${Y(top - 33)} C${X(50, s)} ${Y(top - 20)} ${X(60, s)} ${Y(top - 10)} ${X(66, s)} ${Y(top + 2)} L${X(66, s)} 122 L${X(14, s)} 122 C${X(30, s)} ${Y(top + 20)} ${X(nk + 6, s)} ${Y(top + 12)} ${X(nk - 4, s)} ${Y(top - 4)} Z`, cloth, { rim: true }),
      path(`M${X(nk + 3, s)} ${Y(top - 8)} C${X(33, s)} ${Y(top - 24)} ${X(40, s)} ${Y(top - 29)} ${X(46, s)} ${Y(top - 28)} C${X(50, s)} ${Y(top - 18)} ${X(58, s)} ${Y(top - 8)} ${X(63, s)} ${Y(top + 1)}`, { fill: "none", stroke: T.lit, "stroke-width": small ? 3 : 2.4, "stroke-linecap": "round" }),
    ]))));
  }

  // the vest (v3): two dark panels with a trimmed front hem, and a chest strap with a buckle
  if (v.vest) {
    const panel = (s) => {
      const d = `M${X(14, s)} ${Y(top)} C${X(26, s)} ${Y(top - 2)} ${X(38, s)} ${Y(top - 3)} ${X(48, s)} ${Y(top + 1)} C${X(55, s)} ${Y(top + 6)} ${X(57, s)} ${Y(top + 14)} ${X(60, s)} 122 L${X(13, s)} 122 C${X(11, s)} ${Y(top + 16)} ${X(9, s)} ${Y(top + 9)} ${X(14, s)} ${Y(top)} Z`;
      return grp("", [
        ...K.solid(d, VEST, { rim: true }),
        path(`M${X(14, s)} ${Y(top)} C${X(9, s)} ${Y(top + 9)} ${X(11, s)} ${Y(top + 16)} ${X(13, s)} 122`, { fill: "none", stroke: fill, "stroke-width": small ? 3 : 2.2, "stroke-linecap": "round" }),
        K.fine(path(`M${X(26, s)} ${Y(top + 3)} L${X(28, s)} ${Y(top + 19)}`, { fill: "none", stroke: T.flat, "stroke-width": 1, "stroke-linecap": "round", opacity: ".55" })),
      ]);
    };
    const sy = Math.min(114, top + 13), sh = small ? 6 : 4.6;
    out.gear.push(grp("dk-tier dk-tier--vest", [
      ...both(panel),
      path(`M${X(14, -1)} ${f(sy)} H${X(14, 1)} V${f(sy + sh)} H${X(14, -1)} Z`, Object.assign({ fill }, rim(0.55))),
      path(`M${X(3.6, -1)} ${f(sy - 1.2)} H${X(3.6, 1)} V${f(sy + sh + 1.2)} H${X(3.6, -1)} Z`, Object.assign({ fill: T.lit }, rim(0.55))),
      K.fine(n("rect", { x: 58.4, y: f(sy + 0.8), width: 3.2, height: f(sh - 1.6), fill: T.dark })),
    ]));
  }

  // the shoulder plates (v4): a domed steel plate over each shoulder with a metal rim, a rivet and a groove
  if (v.pads) {
    const pad = (s) => grp("", [
      ...K.solid(`M${X(20, s)} ${Y(top + 4)} C${X(23, s)} ${Y(top - 8)} ${X(40, s)} ${Y(top - 12)} ${X(49, s)} ${Y(top - 2)} C${X(54, s)} ${Y(top + 4)} ${X(55, s)} ${Y(top + 12)} ${X(51, s)} ${Y(top + 18)} Q${X(36, s)} ${Y(top + 15)} ${X(20, s)} ${Y(top + 11)} Z`, STEEL, { rim: true, w: 0.9 }),
      path(`M${X(25, s)} ${Y(top + 4)} C${X(28, s)} ${Y(top - 4)} ${X(39, s)} ${Y(top - 8)} ${X(46, s)} ${Y(top - 1)}`, { fill: "none", stroke: fill, "stroke-width": small ? 3 : 2.2, "stroke-linecap": "round" }),
      path(`M${X(24, s)} ${Y(top + 10)} Q${X(37, s)} ${Y(top + 13)} ${X(50, s)} ${Y(top + 16)}`, { fill: "none", stroke: fill, "stroke-width": small ? 2.4 : 1.8, "stroke-linecap": "round" }),
      K.fine(n("circle", { cx: X(35, s), cy: Y(top + 5), r: 1.7, fill: T.lit, stroke: T.dark, "stroke-width": 0.7 })),
    ]);
    out.gear.push(grp("dk-tier dk-tier--pads", both(pad)));
  }

  // the bandana (v2): a triangle of cloth on the chest, knotted at the sides with two tails that stick out past the jaw
  {
    const w = nk + 9, y0 = cy - 8, tipY = Math.min(118, cy + 27);
    const tail = (s) => path(`M${f(60 + s * (w - 3))} ${f(y0 + 1)} L${f(60 + s * (w + 10))} ${f(y0 - 8)} L${f(60 + s * (w + 7))} ${f(y0 + 3)} L${f(60 + s * (w + 11))} ${f(y0 + 8)} L${f(60 + s * (w - 3))} ${f(y0 + 8)} Z`, Object.assign({ fill }, rim(0.55)));
    out.gear.push(grp("dk-tier dk-tier--bandana", [
      ...both(tail),
      ...K.solid(`M${f(60 - w)} ${f(y0)} Q60 ${f(y0 + 12)} ${f(60 + w)} ${f(y0)} L${f(60 + 6)} ${f(tipY - 2)} Q60 ${f(tipY + 3)} ${f(60 - 6)} ${f(tipY - 2)} Z`, fill, { rim: true }),
      path(`M${f(60 - w + 3)} ${f(y0 + 3)} Q60 ${f(y0 + 14)} ${f(60 + w - 3)} ${f(y0 + 3)}`, { fill: "none", stroke: T.dark, "stroke-width": small ? 1.6 : 1.2, "stroke-linecap": "round", opacity: ".7" }),
      K.fine(path(`M${f(60 - w * 0.42)} ${f(y0 + 10)} l0 0.1 M60 ${f(y0 + 15)} l0 0.1 M${f(60 + w * 0.42)} ${f(y0 + 10)} l0 0.1 M${f(60 - 6)} ${f(y0 + 21)} l0 0.1 M${f(60 + 6)} ${f(y0 + 21)} l0 0.1`, { fill: "none", stroke: T.lit, "stroke-width": 2.2, "stroke-linecap": "round", opacity: ".8" })),
    ]));
  }

  // a bolder brow ridge over each eye (v3): slanted down towards the nose
  if (v.bold && a.eyes) {
    const { y, left, right, ew } = a.eyes;
    const ridge = (cx, s) => path(`M${f(cx + s * (ew + 3.2))} ${f(y - 8.4)} Q${f(cx + s * 1)} ${f(y - 9.6)} ${f(cx - s * (ew + 0.6))} ${f(y - 6.2)}`,
      { fill: "none", stroke: mix(K.coat.shade, "#000000", 0.55), "stroke-width": small ? 3.2 : 2.5, "stroke-linecap": "round" });
    out.brow.push(grp("dk-tier dk-tier--brow", [ridge(left, -1), ridge(right, 1)]));
  }

  // a soft glow round each eye (v4)
  if (v.glow && a.eyes) {
    const { y, left, right, ew, eh } = a.eyes;
    const glow = (cx) => grp("", [
      ell(cx, y, ew + 5.2, eh + 4.6, T.lit, { opacity: small ? ".3" : ".2" }),
      ell(cx, y, ew + 2.4, eh + 2.2, T.lit, { opacity: small ? ".3" : ".24" }),
    ]);
    out.eyes.push(grp("dk-tier dk-tier--eyeglow", [glow(left), glow(right)]));
  }
  return out;
}

/** The aura of a v5 hound, drawn behind it: a bright rim and a soft wide ring, and a few embers drifting off it. */
export function auraShapes(T, K) {
  const small = K.small;
  const ember = (x, y, r) => n("circle", { cx: x, cy: y, r, fill: T.lit, opacity: ".85" });
  return grp("dk-tier dk-tier--aura", [
    ell(60, 64, 50, 53, "none", { stroke: T.flat, "stroke-width": 10, opacity: ".2" }),
    ell(60, 64, 45, 48, "none", { stroke: T.lit, "stroke-width": small ? 2.6 : 1.8, opacity: ".6" }),
    small ? null : grp("", [ember(16, 78, 1.6), ember(104, 84, 1.4), ember(22, 44, 1.2), ember(100, 36, 1.8), ember(11, 58, 1.1), ember(108, 60, 1.2)]),
  ]);
}
