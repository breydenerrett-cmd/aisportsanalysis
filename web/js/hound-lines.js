/**
 * THE HOUND'S VOICE (owner ruling 2026-10-21: the hound page is for engagement and fun, sly and chill, not analytical).
 *
 * Canned templates, no model call: a hound talks in one of ten voices (underdog hunter, chalk eater, chaos agent, stats nerd,
 * steam chaser, mystic, gematria, degen, grinder, or a plain hound). The server names the voice (src/hounds/interact/right_now.py
 * `voice_key`, read off the hound's persona or its own rule); this file only words it. PURE: no DOM, no fetch, no clock. The same
 * hound on the same game always says the same line (a stable hash picks the variant), so a reload never changes its mind.
 *
 * WHAT A LINE MAY NOT DO. It never says a pick is safe, certain, "locked", a "lock", a guarantee or an edge, never talks about
 * profit or value, never tells a person to stake anything, and never uses the word for a canine. It may be cheeky. Every number
 * in a line is one the caller passed in: a template has slots for the selection, the price and the time, and nothing else.
 * tests/test_hound_page_fun.py scans every template for the banned words.
 */

export const VOICES = ["underdog", "chalk", "chaos", "nerd", "steam", "mystic", "gematria", "degen", "grinder", "generic"];

/** A stable 32-bit hash of a string (FNV-1a over UTF-16 units, as src/hounds/voice.py fnv1a does). */
export function fnv(text) {
  let h = 0x811c9dc5;
  const s = String(text);
  for (let i = 0; i < s.length; i += 1) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 0x01000193) >>> 0;
  }
  return h >>> 0;
}

/** One entry of `list`, chosen by `seed`; the same seed always gives the same entry. */
export function choose(list, seed) {
  return list.length ? list[fnv(seed) % list.length] : "";
}

const fill = (template, slots) => template.replace(/\{(\w+)\}/g, (_m, key) => (slots[key] === undefined || slots[key] === null ? "" : String(slots[key])));

/** The voice key to use: an unknown or missing one is the plain hound. */
export function voiceOf(key) {
  return VOICES.includes(key) ? key : "generic";
}

// ---- "What I'd play right now" -------------------------------------------------------------------------------------

export const PICK_LINES = {
  underdog: ["Long price, loud upset energy. {sel} at {price} is my kind of trouble.",
    "Everyone else is looking the other way. {sel} at {price}, and I like the view.",
    "I don't do comfortable. {sel} at {price} is the one tugging my sleeve."],
  chalk: ["Boring on purpose. {sel} at {price}: I like my games to behave.",
    "No drama, no gimmicks. {sel} at {price} and a quiet night.",
    "Call it a short-price kind of mood. {sel} at {price}."],
  chaos: ["Vibes only. {sel} at {price}, and I'm not explaining it.",
    "No reason. A great reason. {sel} at {price}.",
    "The dartboard pointed at {sel}. {price}. Sure, why not."],
  nerd: ["Ran it twice, got the same answer. {sel} at {price} fits my rule cleanest.",
    "Small sample of one, perfect fit. {sel} at {price}.",
    "My spreadsheet is blushing. {sel} at {price}."],
  steam: ["The market's leaning, so I'm leaning. {sel} at {price}.",
    "Somebody knows something. {sel} at {price}, and I'm following the crowd.",
    "The number moved, I noticed. {sel} at {price}."],
  mystic: ["The signs are loud tonight. {sel} at {price}.",
    "The moon has an opinion. {sel} at {price}.",
    "The letters lined up, I just listened. {sel} at {price}."],
  gematria: ["The letters add up. {sel} at {price}.",
    "Every name is a number if you squint. {sel} at {price}.",
    "The sums point one way: {sel} at {price}."],
  degen: ["Itching for this one. {sel} at {price}, let's ride.",
    "Tell me you don't feel it. {sel} at {price}.",
    "Pulse is up. {sel} at {price}, and no regrets yet."],
  grinder: ["Quiet work. {sel} at {price}, no fireworks.",
    "Same routine, same rule. {sel} at {price}.",
    "Nothing flashy, just a game that fits. {sel} at {price}."],
  generic: ["This one fits my rule best right now. {sel} at {price}.",
    "Of everything on the board, {sel} at {price} is the one I'd look at.",
    "If I had to pick one, it's {sel} at {price}."],
};

/** The pick line: the hound's voice, the selection and the price. `seed` should be stable (hound id, event id). */
export function pickLine(voice, { selection = "", priceText = "" } = {}, seed = "") {
  const v = voiceOf(voice);
  return fill(choose(PICK_LINES[v], `${v}|pick|${seed}`), { sel: selection, price: priceText });
}

export const NOTHING_LINES = {
  underdog: ["No long shots speaking to me yet.", "Nothing with enough price and attitude right now."],
  chalk: ["Nothing safe-looking enough to bother with.", "Not a short price in sight that fits."],
  chaos: ["The dartboard is silent. Suspicious.", "Even chaos needs a game to land on."],
  nerd: ["Nothing clears my rule yet. I'm not bending it.", "No game fits. The sample of one stays at zero."],
  steam: ["The market hasn't moved my way yet.", "No steam on anything I like."],
  mystic: ["The signs are quiet.", "The moon is not saying much."],
  gematria: ["No sums are lining up.", "The letters are not adding up to anything yet."],
  degen: ["Nothing's got me twitchy. Yet.", "I'd love to bark about something, but there's nothing."],
  grinder: ["Nothing fits. That's part of the job.", "No game meets the rule. I wait."],
  generic: ["Nothing fits my rule right now.", "Nothing on the board matches. I wait."],
};

/** The empty state: the hound says so in its voice, then the next game it will look at. `next` = { game, whenText }. */
export function nothingLine(voice, next, seed = "") {
  const v = voiceOf(voice);
  const first = choose(NOTHING_LINES[v], `${v}|nothing|${seed}`);
  if (next && next.game) return `${first} Next game on my radar: ${next.game}${next.whenText ? `, ${next.whenText}` : ""}.`;
  return `${first} I'll look again when a new game hits the board.`;
}

// ---- the hero's mood line ------------------------------------------------------------------------------------------

export const MOOD_LINES = {
  hot: {
    underdog: "Three straight and I'm acting casual about it.", chalk: "Winning quietly, which is the best way.",
    chaos: "Absolutely no idea why this is working.", nerd: "Statistically noteworthy. Also fun.",
    steam: "The market keeps agreeing with me.", mystic: "The signs said so.", gematria: "The sums keep coming out right.",
    degen: "Don't touch anything. I'm on one.", grinder: "Heads down, still going.", generic: "On a roll. Keeping it chill.",
  },
  cold: {
    underdog: "Long shots miss. That's the deal. Next.", chalk: "Even the safe ones bite sometimes.",
    chaos: "Chaos was always going to cut both ways.", nerd: "Variance. I'm told it exists.",
    steam: "The market and I are not speaking right now.", mystic: "The signs got blurry.", gematria: "The sums went sideways.",
    degen: "Rough patch. I've had worse. Probably.", grinder: "Bad stretch. Same routine tomorrow.", generic: "Rough patch. Still here.",
  },
  open: {
    underdog: "Tickets out there. I'm rooting for the upset.", chalk: "Tickets out there. Nothing to see, hopefully.",
    chaos: "Tickets out there. Anything could happen.", nerd: "Tickets out there. Watching the data come in.",
    steam: "Tickets out there. Watching the number.", mystic: "Tickets out there. Watching the sky.",
    gematria: "Tickets out there. Counting letters.", degen: "Tickets out there. Can't look. Looking.",
    grinder: "Tickets out there. Waiting on the finals.", generic: "Tickets out there. Waiting on the results.",
  },
  idle: {
    underdog: "Sniffing around for a price worth barking at.", chalk: "Checking the board for something sensible.",
    chaos: "Spinning the dartboard.", nerd: "Reading the board. Again.", steam: "Watching the numbers twitch.",
    mystic: "Reading the signs.", gematria: "Adding up the names.", degen: "Pacing. Need a game.",
    grinder: "On the clock, waiting for a fit.", generic: "Sniffing around the board.",
  },
  fresh: {
    underdog: "New here. Hungry for an upset.", chalk: "New here. Keeping it tidy.", chaos: "New here. Zero plan.",
    nerd: "New here. Collecting data.", steam: "New here. Learning the market.", mystic: "New here. The signs will show.",
    gematria: "New here. Learning the letters.", degen: "New here. Let's go.", grinder: "New here. Putting in the hours.",
    generic: "New here. Waiting for a first game.",
  },
  gone: {
    underdog: "Off the clock. The record stays.", chalk: "Off the clock. The record stays.", chaos: "Off the clock. The record stays.",
    nerd: "Off the clock. The record stays.", steam: "Off the clock. The record stays.", mystic: "Off the clock. The record stays.",
    gematria: "Off the clock. The record stays.", degen: "Off the clock. The record stays.", grinder: "Off the clock. The record stays.",
    generic: "Off the clock. The record stays.",
  },
};

/**
 * The hero's "right now" line. `facts` = { retired, streakKind ("W"|"L"|""), streakLen, open, graded }.
 * Priority: retired, a streak of 3+, open tickets, a hound with no graded bets, else idle.
 */
export function moodLine(voice, facts = {}) {
  const v = voiceOf(voice);
  if (facts.retired) return MOOD_LINES.gone[v];
  if (facts.streakKind === "W" && facts.streakLen >= 3) return MOOD_LINES.hot[v];
  if (facts.streakKind === "L" && facts.streakLen >= 3) return MOOD_LINES.cold[v];
  if (facts.open > 0) return `${facts.open === 1 ? "1 ticket" : `${facts.open} tickets`} out there. ${MOOD_LINES.open[v].replace(/^Tickets out there\.\s*/, "")}`;
  if (!(facts.graded > 0)) return MOOD_LINES.fresh[v];
  return MOOD_LINES.idle[v];
}

// ---- the feed ------------------------------------------------------------------------------------------------------

export const FEED_FLOURISH = {
  won: { underdog: "Long price, loud result.", chalk: "Boring wins are my favorite.", chaos: "Told you. (I didn't.)", nerd: "Fits the model. Smug.",
    steam: "The market was right.", mystic: "The signs delivered.", gematria: "The sums held.", degen: "Told you I felt it.", grinder: "Another day at the office.", generic: "Nice." },
  lost: { underdog: "That's what a long price does.", chalk: "Even chalk bites.", chaos: "Chaos giveth, chaos taketh.", nerd: "Noted. Variance.",
    steam: "The market blinked.", mystic: "The signs got cloudy.", gematria: "The sums lied.", degen: "Next one, I swear.", grinder: "Back to work.", generic: "On to the next." },
};

/** One sentence for a settled ticket. `t` = { result: "won"|"lost"|"push", selection, priceText, moneyText }. */
export function settledLine(voice, t, seed = "") {
  const v = voiceOf(voice);
  const sel = t.selection || "that one";
  const price = t.priceText ? ` at ${t.priceText}` : "";
  const money = t.moneyText ? ` (${t.moneyText} on paper)` : "";
  if (t.result === "won") {
    const lead = choose([`${sel}${price} came in${money}.`, `${sel}${price} got there${money}.`, `Hit on ${sel}${price}${money}.`], `${v}|won|${seed}`);
    return `${lead} ${FEED_FLOURISH.won[v]}`;
  }
  if (t.result === "lost") {
    const lead = choose([`${sel}${price} missed${money}.`, `${sel}${price} didn't get there${money}.`, `Swing and a miss on ${sel}${price}${money}.`], `${v}|lost|${seed}`);
    return `${lead} ${FEED_FLOURISH.lost[v]}`;
  }
  if (t.result === "push") return `${sel}${price} pushed. Nobody wins, nobody loses, everybody shrugs.`;
  return `${sel}${price} is still out there.`;
}

/** One sentence for a ticket that has not settled. `t` = { selection, priceText, game, whenText }. */
export function openLine(voice, t, seed = "") {
  const v = voiceOf(voice);
  const sel = t.selection || "a pick";
  const price = t.priceText ? ` at ${t.priceText}` : "";
  const where = t.game ? ` in ${t.game}` : "";
  const when = t.whenText ? ` ${t.whenText}` : "";
  return choose([`Put ${sel}${price} on the card${where}.${when}`, `${sel}${price}${where} is out there.${when}`], `${v}|open|${seed}`).trim();
}

/** A streak sentence, or "" under two in a row. */
export function streakLine(voice, kind, len) {
  const v = voiceOf(voice);
  if (!(len >= 2)) return "";
  if (kind === "W") return `${len} wins in a row. ${FEED_FLOURISH.won[v]}`;
  if (kind === "L") return `${len} losses in a row. ${FEED_FLOURISH.lost[v]}`;
  return "";
}

/** Every template string in this file, for the banned-word scan in tests. */
export function allTemplates() {
  const out = [];
  const walk = (x) => { if (typeof x === "string") out.push(x); else if (Array.isArray(x)) x.forEach(walk); else if (x && typeof x === "object") Object.values(x).forEach(walk); };
  [PICK_LINES, NOTHING_LINES, MOOD_LINES, FEED_FLOURISH].forEach(walk);
  return out;
}
