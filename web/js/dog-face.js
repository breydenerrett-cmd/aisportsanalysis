/**
 * THE FACE: nose, mouth, eyes and brows for every breed and every expression, drawn from the breed's landmarks (`geo`).
 *
 * The hounds are meant to look like sports-mascot hounds, not pets: the eyes are narrow almonds under a heavy angled brow plate
 * (the inner corner always lower than the outer), the nose is big and defined, the mouth is a hard line with a fang tip showing.
 * An expression is a different set of parts, not a different drawing of the whole dog: every pose's eyes, brows, mouth and prop
 * is drawn ONCE with a `dk-p dk-p--<kind> dk-p--<pose>` class and css/lh.css shows the set that matches `data-pose`, so a card goes
 * from idle to grin to howl by flipping an attribute. The poses, by the names the rest of the product already uses (and the
 * expression each one draws):
 *
 *   idle       a level stare with a fang tip showing          (the dog at rest: breathing, an eye glint)
 *   happy      a grin: smug squint, mouth open, tongue        (a win)
 *   sad        a snarl: heavy brow, nose crease, teeth bared  (a loss, a refusal)
 *   thinking   focus: eyes cut sideways and up, one brow up   (out thinking, being checked)
 *   celebrate  a howl: eyes shut, head back, mouth wide open  (a new dog, a manual pick, a saved look)
 *
 * Every colour is a constant or a mix of two; nothing from a look reaches a string. Pure element building, so the node tests run it.
 */

import { INK, n, path, ell, grp, mix, f } from "./dog-art.js";

export const EXPRESSIONS = ["idle", "snarl", "grin", "focus", "howl"];
/** The expression each canonical pose draws. */
export const EXPRESSION_OF = { idle: "idle", sad: "snarl", happy: "grin", thinking: "focus", celebrate: "howl" };

const TEETH = "#F7F3E8";
const GUM = "#8E2B3A";
const TONGUE = "#E5667A";
const MOUTH = "#241014";

// ---- nose ---------------------------------------------------------------------------------------------------------

export function noseShapes(g, K, c) {
  const { ny, nrx, nry } = g;
  const d = `M${f(60 - nrx)} ${f(ny - nry * 0.5)} Q60 ${f(ny - nry * 1.55)} ${f(60 + nrx)} ${f(ny - nry * 0.5)} Q${f(60 + nrx * 1.02)} ${f(ny + nry * 0.9)} 60 ${f(ny + nry * 1.35)} Q${f(60 - nrx * 1.02)} ${f(ny + nry * 0.9)} ${f(60 - nrx)} ${f(ny - nry * 0.5)} Z`;
  const leather = mix(INK, c.shade, 0.1);
  const out = [
    path(d, { fill: leather, stroke: K.oc, "stroke-width": f(K.ow * 0.55), "stroke-linejoin": "round" }),
    path(`M${f(60 - nrx * 0.62)} ${f(ny + nry * 0.1)} Q${f(60 - nrx * 0.72)} ${f(ny + nry * 0.65)} ${f(60 - nrx * 0.28)} ${f(ny + nry * 0.55)} M${f(60 + nrx * 0.62)} ${f(ny + nry * 0.1)} Q${f(60 + nrx * 0.72)} ${f(ny + nry * 0.65)} ${f(60 + nrx * 0.28)} ${f(ny + nry * 0.55)}`,
      { fill: "none", stroke: "#000000", "stroke-width": f(Math.max(1.1, nry * 0.3)), "stroke-linecap": "round", opacity: ".75" }),
    ell(60 - nrx * 0.34, ny - nry * 0.7, nrx * 0.42, nry * 0.3, "#FFFFFF", { opacity: ".34" }),
  ];
  return out;
}

// ---- mouths -------------------------------------------------------------------------------------------------------

/** A tooth: a small downward (or, with `up`, upward) triangle from a base line. */
function tooth(x, y, w, h, up = false) {
  const t = up ? -h : h;
  return path(`M${f(x - w / 2)} ${f(y)} L${f(x)} ${f(y + t)} L${f(x + w / 2)} ${f(y)} Z`, { fill: TEETH, stroke: "#C9C2AE", "stroke-width": 0.35, "stroke-linejoin": "round" });
}

export function mouthShapes(g, K) {
  const { my, mw, ny, nry } = g;
  const line = (d, w = 1.9) => path(d, { fill: "none", stroke: INK, "stroke-width": w, "stroke-linecap": "round", "stroke-linejoin": "round" });
  const phil = line(`M60 ${f(ny + nry * 1.3)} V${f(my - 3.5)}`, 1.5);
  const lip = (lift) => line(`M${f(60 - mw)} ${f(my - lift)} Q${f(60 - mw * 0.5)} ${f(my + 3.6)} 60 ${f(my - 3)} Q${f(60 + mw * 0.5)} ${f(my + 3.6)} ${f(60 + mw)} ${f(my - lift)}`);
  const fangR = tooth(60 + mw * 0.58, my + 0.4, 3.4, 4.6);
  const small = K.small;
  const idle = [phil, lip(0.8), small ? null : fangR];

  const wide = (k, depth, lift) => {
    const L = 60 - mw * k, R = 60 + mw * k;
    return path(`M${f(L)} ${f(my - lift)} Q60 ${f(my + depth)} ${f(R)} ${f(my - lift)} Q60 ${f(my - 3.2 - lift * 0.4)} ${f(L)} ${f(my - lift)} Z`, { fill: MOUTH, stroke: INK, "stroke-width": 1.5, "stroke-linejoin": "round" });
  };
  // the snarl: the upper lip hitched up over a row of teeth
  const snarlTeeth = [
    tooth(60 - mw * 0.7, my - 3.5, 4.4, 7.2), tooth(60 + mw * 0.7, my - 3.5, 4.4, 7.2),
    ...(small ? [] : [tooth(60 - mw * 0.3, my - 3.8, 2.8, 3.8), tooth(60, my - 3.9, 2.8, 3.6), tooth(60 + mw * 0.3, my - 3.8, 2.8, 3.8)]),
  ];
  const snarl = [
    phil,
    wide(1.12, 9.5, 1.6),
    path(`M${f(60 - mw * 1.12)} ${f(my - 1.6)} Q60 ${f(my - 7)} ${f(60 + mw * 1.12)} ${f(my - 1.6)}`, { fill: "none", stroke: GUM, "stroke-width": 1.3, "stroke-linecap": "round" }),
    ...snarlTeeth,
    ...(small ? [] : [tooth(60 - mw * 0.55, my + 5.5, 3, 3.8, true), tooth(60 + mw * 0.55, my + 5.5, 3, 3.8, true)]),
    line(`M${f(60 - mw * 1.12)} ${f(my - 1.6)} Q${f(60 - mw * 1.25)} ${f(my - 4.4)} ${f(60 - mw * 1.34)} ${f(my - 5)} M${f(60 + mw * 1.12)} ${f(my - 1.6)} Q${f(60 + mw * 1.25)} ${f(my - 4.4)} ${f(60 + mw * 1.34)} ${f(my - 5)}`, 1.6),
    // the nose crease
    K.fine(line(`M${f(60 - 5)} ${f(ny - nry * 1.9)} L${f(60 - 1.5)} ${f(ny - nry * 1.4)} M${f(60 + 5)} ${f(ny - nry * 1.9)} L${f(60 + 1.5)} ${f(ny - nry * 1.4)} M${f(60 - 3.5)} ${f(ny - nry * 2.7)} L${f(60 - 0.6)} ${f(ny - nry * 2.2)} M${f(60 + 3.5)} ${f(ny - nry * 2.7)} L${f(60 + 0.6)} ${f(ny - nry * 2.2)}`, 1.2)),
  ];
  // the grin: corners up, teeth on top, tongue out
  const grin = [
    phil,
    path(`M${f(60 - mw * 1.18)} ${f(my - 3.2)} Q60 ${f(my + 12)} ${f(60 + mw * 1.18)} ${f(my - 3.2)} Q60 ${f(my - 1)} ${f(60 - mw * 1.18)} ${f(my - 3.2)} Z`, { fill: MOUTH, stroke: INK, "stroke-width": 1.5, "stroke-linejoin": "round" }),
    tooth(60 - mw * 0.75, my - 2.4, 4, 6), tooth(60 + mw * 0.75, my - 2.4, 4, 6),
    ...(small ? [] : [tooth(60 - mw * 0.28, my - 2, 2.6, 3), tooth(60 + mw * 0.28, my - 2, 2.6, 3)]),
    path(`M${f(60 - mw * 0.5)} ${f(my + 4)} Q60 ${f(my + 3)} ${f(60 + mw * 0.5)} ${f(my + 4)} Q${f(60 + mw * 0.45)} ${f(my + 10.5)} 60 ${f(my + 10.8)} Q${f(60 - mw * 0.45)} ${f(my + 10.5)} ${f(60 - mw * 0.5)} ${f(my + 4)} Z`, { fill: TONGUE, stroke: "#B8404F", "stroke-width": 0.7 }),
    line(`M60 ${f(my + 4.2)} V${f(my + 9)}`, 0.9),
    line(`M${f(60 - mw * 1.18)} ${f(my - 3.2)} Q${f(60 - mw * 1.3)} ${f(my - 5.4)} ${f(60 - mw * 1.4)} ${f(my - 5.2)} M${f(60 + mw * 1.18)} ${f(my - 3.2)} Q${f(60 + mw * 1.3)} ${f(my - 5.4)} ${f(60 + mw * 1.4)} ${f(my - 5.2)}`, 1.6),
  ];
  // focus: a flat, one-sided smirk, one fang
  const focus = [
    phil,
    line(`M${f(60 - mw * 0.92)} ${f(my + 0.6)} Q${f(60 - mw * 0.3)} ${f(my + 3)} 60 ${f(my - 1.6)} Q${f(60 + mw * 0.55)} ${f(my + 3.2)} ${f(60 + mw)} ${f(my - 2.6)}`),
    small ? null : tooth(60 + mw * 0.58, my + 0.8, 3.4, 4.2),
  ];
  // the howl: mouth thrown wide open, fangs top and bottom, tongue curled
  const howl = [
    phil,
    path(`M${f(60 - mw * 1.0)} ${f(my - 4)} Q${f(60 - mw * 1.15)} ${f(my + 14)} 60 ${f(my + 17)} Q${f(60 + mw * 1.15)} ${f(my + 14)} ${f(60 + mw * 1.0)} ${f(my - 4)} Q60 ${f(my - 7)} ${f(60 - mw * 1.0)} ${f(my - 4)} Z`, { fill: MOUTH, stroke: INK, "stroke-width": 1.6, "stroke-linejoin": "round" }),
    tooth(60 - mw * 0.66, my - 4.6, 4.2, 7.4), tooth(60 + mw * 0.66, my - 4.6, 4.2, 7.4),
    ...(small ? [] : [tooth(60 - mw * 0.26, my - 5, 2.6, 3.2), tooth(60 + mw * 0.26, my - 5, 2.6, 3.2),
      tooth(60 - mw * 0.5, my + 13.6, 3.2, 5, true), tooth(60 + mw * 0.5, my + 13.6, 3.2, 5, true)]),
    path(`M${f(60 - mw * 0.55)} ${f(my + 11)} Q60 ${f(my + 5)} ${f(60 + mw * 0.55)} ${f(my + 11)} Q60 ${f(my + 17)} ${f(60 - mw * 0.55)} ${f(my + 11)} Z`, { fill: TONGUE }),
    line(`M60 ${f(my + 7.4)} V${f(my + 13)}`, 0.9),
  ];
  return { idle, happy: grin, sad: snarl, thinking: focus, celebrate: howl };
}

// ---- eyes and brows -----------------------------------------------------------------------------------------------

/** An almond from its outer corner O and inner corner I (the inner is lower: that is the menace). */
function almond(cx, cy, hw, hh, tilt, side, topK = 1.7, botK = 1.2) {
  const ox = cx + side * hw, oy = cy - tilt, ix = cx - side * hw, iy = cy + tilt;
  return `M${f(ox)} ${f(oy)} Q${f(cx)} ${f(cy - hh * topK)} ${f(ix)} ${f(iy)} Q${f(cx)} ${f(cy + hh * botK)} ${f(ox)} ${f(oy)} Z`;
}

/** The pose table: how far the lids come down at the inner and outer corner (in eye heights), where the iris looks, how steep the brow is. */
const EYE_POSE = {
  idle: { lidIn: -0.1, lidOut: -0.95, dx: 0, dy: 0.25, slope: 3.2, thick: 4.6, lift: 0 },
  sad: { lidIn: 0.4, lidOut: -0.5, dx: 0, dy: 0.6, slope: 5.6, thick: 5.8, lift: 1.4 },
  happy: { lidIn: -0.3, lidOut: -0.75, dx: 0, dy: 0.2, slope: 2.4, thick: 4.2, lift: -1.6 },
  thinking: { lidIn: -0.2, lidOut: -0.8, dx: 1.7, dy: -1.1, slope: 2.2, thick: 4.2, lift: -0.6 },
};

export function eyeShapes(g, K, c, eyeColor) {
  // a small badge draws its eyes bigger and brighter so they still read at 32px
  const { ey, edx, tilt } = g;
  const ew = g.ew * (K.small ? 1.22 : 1), eh = g.eh * (K.small ? 1.4 : 1);
  const plateFill = mix(c.shade, INK, 0.3);
  const plate = (cx, sd, lidIn, lidOut, thick, raised) => {
    const xo = cx + sd * (ew + 2.4), xi = cx - sd * (ew + 1.2);
    const tOut = thick * 0.4 + (raised ? 0.8 : 0), tIn = thick + (raised ? 1.2 : 0);
    return path(`M${f(xo)} ${f(lidOut - tOut)} L${f(xi)} ${f(lidIn - tIn)} L${f(xi)} ${f(lidIn)} L${f(xo)} ${f(lidOut)} Z`,
      { fill: plateFill, stroke: K.oc, "stroke-width": f(K.ow * 0.4), "stroke-linejoin": "round" });
  };
  const sockets = K.small ? null : grp("dk-sockets", [-1, 1].map((sd) => ell(60 + sd * edx, ey + 0.4, ew + 3, eh + 3.2, INK, { opacity: ".14" })));
  const pose = (name) => {
    const P = EYE_POSE[name];
    const kids = [];
    [-1, 1].forEach((sd) => {
      const cx = 60 + sd * edx;
      const raised = name === "thinking" && sd === 1;           // focus: the far brow goes up
      const look = P.dx * (name === "thinking" ? 1 : 0);
      const lidIn = ey + eh * (raised ? P.lidIn - 0.6 : P.lidIn), lidOut = ey + eh * (raised ? P.lidOut - 0.2 : P.lidOut);
      const t = tilt * (raised ? 0.35 : 1);
      const e = [
        path(almond(cx, ey, ew, eh, t, sd), { fill: "#E7DEC6" }),
        path(almond(cx + look, ey + P.dy, ew * 0.66, eh * 0.98, t * 0.6, sd, 1.55, 1.15), { fill: eyeColor }),
        ell(cx + look + sd * -0.2, ey + P.dy + 0.2, ew * 0.2, eh * 0.78, "#07080B"),
        K.small ? null : ell(cx + look - sd * 1.3 - 0.6, ey + P.dy - eh * 0.46, 0.95, 0.95, "#FFFFFF", { class: "dk-glint" }),
        K.small ? ell(cx + look - 0.8, ey + P.dy - 0.6, 0.9, 0.9, "#FFFFFF") : null,
      ];
      kids.push(grp("dk-eye", e));
      // the lid and brow plate: a dark wedge, thick at the nose and thin at the temple, inner corner low
      kids.push(plate(cx, sd, lidIn, lidOut, P.thick, raised));
    });
    return grp(`dk-p dk-p--eyes dk-p--${name === "idle" ? "open" : name}`, kids);
  };
  // grin: a smug squint, the lower lid pushed up under a relaxed brow
  const grinEyes = (() => {
    const kids = [];
    [-1, 1].forEach((sd) => {
      const cx = 60 + sd * edx;
      kids.push(grp("dk-eye", [
        path(almond(cx, ey, ew, eh * 0.9, tilt * 0.8, sd), { fill: "#E7DEC6" }),
        path(almond(cx, ey + 0.1, ew * 0.66, eh * 0.9, tilt * 0.5, sd, 1.4, 1.1), { fill: eyeColor }),
        ell(cx, ey + 0.2, ew * 0.2, eh * 0.7, "#07080B"),
        K.small ? null : ell(cx - sd * 1.3 - 0.6, ey - eh * 0.42, 0.9, 0.9, "#FFFFFF", { class: "dk-glint" }),
      ]));
      kids.push(plate(cx, sd, ey - eh * 0.3, ey - eh * 0.8, EYE_POSE.happy.thick, false));
      kids.push(path(`M${f(cx - ew - 1.6)} ${f(ey + eh * 0.5)} Q${f(cx)} ${f(ey - eh * 0.55)} ${f(cx + ew + 1.6)} ${f(ey + eh * 0.5)} L${f(cx + ew + 1.6)} ${f(ey + eh * 3)} L${f(cx - ew - 1.6)} ${f(ey + eh * 3)} Z`, { fill: c.base }));
      kids.push(path(`M${f(cx - ew - 1.2)} ${f(ey + eh * 0.5)} Q${f(cx)} ${f(ey - eh * 0.55)} ${f(cx + ew + 1.2)} ${f(ey + eh * 0.5)}`, { fill: "none", stroke: K.oc, "stroke-width": f(K.ow * 0.4), "stroke-linecap": "round" }));
    });
    return grp("dk-p dk-p--eyes dk-p--happy", kids);
  })();
  // howl: the eyes shut tight under a brow pulled up
  const howlEyes = (() => {
    const kids = [];
    [-1, 1].forEach((sd) => {
      const cx = 60 + sd * edx;
      kids.push(path(`M${f(cx + sd * ew)} ${f(ey - tilt - 0.4)} Q${f(cx)} ${f(ey + eh * 1.6)} ${f(cx - sd * ew)} ${f(ey + tilt + 0.4)}`, { fill: "none", stroke: INK, "stroke-width": 2.6, "stroke-linecap": "round" }));
      kids.push(plate(cx, sd, ey - eh * 1.5, ey - eh * 2.2, 3.4, true));
    });
    return grp("dk-p dk-p--eyes dk-p--celebrate", kids);
  })();
  return { sockets, groups: [pose("idle"), grinEyes, pose("sad"), pose("thinking"), howlEyes] };
}
