/**
 * MLB club identity colors, keyed by the club abbreviations this API
 * emits (`away_team`/`home_team` -- see the slate rows in
 * docs/API_CONTRACTS.md).
 *
 * WHY THIS FILE EXISTS
 * -------------------------------------------------------------------
 * The frozen Gameday canvas blocks its hero and its slate tiles in TEAM
 * COLOR (design/linehound-v1, section 02: "--team-pit #FDB827 ... team
 * colour is identity only -- never a status colour"). The API carries no
 * color field and never will: a club's brand palette is public identity
 * data, not analysis, so it belongs in the client as a static table.
 *
 * RULES THAT COME WITH IT
 * -------------------------------------------------------------------
 * - Team color is IDENTITY ONLY. It never encodes a verdict, a price
 *   advantage, freshness, or any other status -- those are the reserved
 *   money/live tokens in css/tokens.css.
 * - An abbreviation this table does not know renders the NEUTRAL seam
 *   below rather than a guessed color: a wrong club color is a small lie
 *   that looks like a bug, and a made-up one is worse.
 *
 * `primary` blocks the seam half; `secondary` draws the skewed rule under
 * the wordmark and the tile monogram.
 */

const NEUTRAL = { primary: "#1D222B", secondary: "#8A919E", known: false };

const TEAMS = {
  ATH: { primary: "#003831", secondary: "#EFB21E" },
  ATL: { primary: "#13274F", secondary: "#CE1141" },
  AZ:  { primary: "#A71930", secondary: "#E3D4AD" },
  BAL: { primary: "#DF4601", secondary: "#000000" },
  BOS: { primary: "#BD3039", secondary: "#0C2340" },
  CHC: { primary: "#0E3386", secondary: "#CC3433" },
  CIN: { primary: "#C6011F", secondary: "#000000" },
  CLE: { primary: "#0C2340", secondary: "#E31937" },
  COL: { primary: "#333366", secondary: "#C4CED4" },
  CWS: { primary: "#27251F", secondary: "#C4CED4" },
  DET: { primary: "#0C2340", secondary: "#FA4616" },
  HOU: { primary: "#002D62", secondary: "#EB6E1F" },
  KC:  { primary: "#004687", secondary: "#BD9B60" },
  LAA: { primary: "#BA0021", secondary: "#003263" },
  LAD: { primary: "#005A9C", secondary: "#EF3E42" },
  MIA: { primary: "#00A3E0", secondary: "#EF3340" },
  MIL: { primary: "#12284B", secondary: "#FFC52F" },
  MIN: { primary: "#002B5C", secondary: "#D31145" },
  NYM: { primary: "#002D72", secondary: "#FF5910" },
  NYY: { primary: "#0C2340", secondary: "#C4CED3" },
  PHI: { primary: "#E81828", secondary: "#002D72" },
  PIT: { primary: "#27251F", secondary: "#FDB827" },
  SD:  { primary: "#2F241D", secondary: "#FFC425" },
  SEA: { primary: "#0C2C56", secondary: "#005C5C" },
  SF:  { primary: "#27251F", secondary: "#FD5A1E" },
  STL: { primary: "#C41E3A", secondary: "#0C2340" },
  TB:  { primary: "#092C5C", secondary: "#8FBCE6" },
  TEX: { primary: "#003278", secondary: "#C0111F" },
  TOR: { primary: "#134A8E", secondary: "#1D2D5C" },
  WSH: { primary: "#AB0003", secondary: "#14225A" },
};

/* ---------------------------------------------------------------------
 * Colour maths. Two jobs, both about legibility on the near-black
 * ground, neither of them a judgment about the club.
 * ------------------------------------------------------------------- */

const GROUND = [11, 12, 14]; // --ground #0B0C0E

function toRgb(hex) {
  const h = String(hex).replace("#", "");
  return [parseInt(h.slice(0, 2), 16), parseInt(h.slice(2, 4), 16), parseInt(h.slice(4, 6), 16)];
}

function mix(rgb, toward, weight) {
  return rgb.map((c, i) => Math.round(c * weight + toward[i] * (1 - weight)));
}

function css(rgb) {
  return `rgb(${rgb[0]}, ${rgb[1]}, ${rgb[2]})`;
}

/** Relative luminance, sRGB. Used only to decide whether a colour is
 * readable as text on the near-black ground. */
function luminance(rgb) {
  const [r, g, b] = rgb.map((c) => {
    const s = c / 255;
    return s <= 0.04045 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

/** Identity colors for a club abbreviation. Unknown club -> the neutral
 * seam (never a guessed color); `known` says which happened, so a caller
 * can choose not to draw a color rule at all.
 *
 * `accent` is the club colour actually safe to set type in on this
 * ground: the brighter of the two brand colours, lifted toward white
 * only as far as legibility requires. Several clubs' brand palettes are
 * black or near-black, which is a real colour on a white jersey and an
 * invisible one here -- lifting it is a rendering decision, not a change
 * to the club's identity.
 */
export function teamColors(abbr) {
  if (!abbr) return NEUTRAL;
  const entry = TEAMS[String(abbr).toUpperCase()];
  if (!entry) return NEUTRAL;
  const candidates = [toRgb(entry.secondary), toRgb(entry.primary)];
  let accent = candidates[0];
  if (luminance(candidates[1]) > luminance(candidates[0])) accent = candidates[1];
  let guard = 0;
  while (luminance(accent) < 0.3 && guard < 12) {
    accent = mix(accent, [255, 255, 255], 0.82);
    guard += 1;
  }
  return {
    primary: entry.primary,
    secondary: entry.secondary,
    accent: css(accent),
    known: true,
  };
}

/**
 * The seam-half gradient for one club.
 *
 * The canvas blocks both halves in the same DARK band (its own tokens
 * name them --team-block-a #12284B and --team-block-b #1A4A57), so the
 * white display type on top keeps its contrast and no half ever reads as
 * a warm or bright field -- section 02's FORBIDDEN list rules out brown,
 * sepia and warm neutrals outright. A club's primary is therefore mixed
 * down into that band rather than painted at full strength: the identity
 * is legible, the ground stays the ground.
 */
export function seamGradient(abbr, angleDeg) {
  const { primary, known } = teamColors(abbr);
  if (!known) {
    return `linear-gradient(${angleDeg}deg, #1D222B 0%, #14181F 58%, #0B0C0E 100%)`;
  }
  const rgb = toRgb(primary);
  return `linear-gradient(${angleDeg}deg, ${css(mix(rgb, GROUND, .46))} 0%, `
    + `${css(mix(rgb, GROUND, .26))} 58%, ${css(mix(rgb, GROUND, .10))} 100%)`;
}

export { NEUTRAL as NEUTRAL_TEAM_COLORS };
