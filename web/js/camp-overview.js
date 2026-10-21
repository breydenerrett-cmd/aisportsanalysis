/**
 * THE TRAINING CAMP, AT A GLANCE (critic round 2, 2026-10-19). The camp was ten identical cards of copy. Now the page opens on
 * a strip of four figures (coach tips graded, helped / hurt, the next breeding cycle, your dogs in training) and every section
 * below is collapsed to its headline and ONE number; the section opens on a click, a link to its anchor, or a drill.
 *
 * Nothing here computes a result. It reads the same public endpoints the sections read (GET /hounds/coach/report,
 * /hounds/learning, /hounds/breeding, and /hounds/camp/mine for a signed-in member) and shows the figure the server already
 * sent. A figure the server did not send is a dash, never a zero; a comparison without enough bets says "too few bets", the same
 * rule the section itself follows. Counts are counts of tips and tickets (paper), not a claim that the coach or any dog is good.
 */

import { apiGet } from "./api.js";
import { isNum, signed } from "./hounds-core.js";
import { signedIn } from "./dog-common.js";

export const DASH = "—";

const q = (hook) => document.querySelector(`[data-hook='${hook}']`);
const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;

/** "in 2d 4h", "in 5h", "in 40m", "due now" until an ISO time; a dash when there is none. */
export function untilText(iso, nowMs = Date.now()) {
  const at = Date.parse(iso || "");
  if (!Number.isFinite(at)) return DASH;
  const mins = Math.round((at - nowMs) / 60000);
  if (mins <= 0) return "due now";
  const d = Math.floor(mins / 1440), hrs = Math.floor((mins % 1440) / 60);
  if (d > 0) return `in ${d}d ${hrs}h`;
  if (hrs > 0) return `in ${hrs}h`;
  return `in ${mins}m`;
}

/**
 * The figures. Each input may be null (the request failed or was not made): the matching figures are then a dash.
 * `signed` is whether a member is signed in; `mine` is GET /hounds/camp/mine.
 */
export function campFigures({ coach, learning, breeding, mine, signedInNow = false, nowMs = Date.now() } = {}) {
  const sum = coach && coach.computed !== false && coach.summary ? coach.summary : null;
  const system = (learning && learning.system) || {};
  const act = system.activity || null;
  const win30 = system.vs_random && system.vs_random.windows ? system.vs_random.windows["30"] : null;
  const hit = system.promotion_hit_rate || null;
  const lessons = learning && learning.lessons ? learning.lessons : null;
  const next = breeding && breeding.enabled !== false && !breeding.paused ? untilText(breeding.next_cycle_utc, nowMs)
    : breeding && (breeding.paused || breeding.enabled === false) ? "paused" : DASH;
  const dogCount = mine && Array.isArray(mine.dogs) ? mine.dogs.length : null;
  const dogs = !signedInNow ? "Sign in" : dogCount === null ? DASH : String(dogCount);
  const tips = sum && isNum(sum.graded_forward) ? String(sum.graded_forward) : DASH;
  const helpedHurt = sum && isNum(sum.helped) && isNum(sum.hurt) ? `${sum.helped} / ${sum.hurt}` : DASH;
  return {
    strip: { tips, helpedHurt, nextCycle: next, dogs },
    nums: {
      dogs: !signedInNow ? "Sign in" : dogCount === null ? DASH : plural(dogCount, "hound", "hounds"),
      coach: sum && isNum(sum.graded_forward) ? `${sum.graded_forward} graded` : "not graded yet",
      drills: "7, 14 or 30 days",
      cuts: learning && isNum(learning.live_challengers) ? `${learning.live_challengers} trying out` : DASH,
      coin: win30 && win30.enough && isNum(win30.difference) ? `${signed(win30.difference, 2)} pts` : win30 ? "too few bets" : DASH,
      hold: hit && isNum(hit.matured) && hit.matured > 0 ? `${hit.hits} of ${hit.matured}` : hit ? "none yet" : DASH,
      activity: system.paused ? "paused" : act && isNum(act.promotions) && isNum(act.retirements) ? `${act.promotions} promoted, ${act.retirements} cut` : DASH,
      rules: "in brief",
      lessons: lessons && isNum(lessons.count) ? plural(lessons.count, "lesson", "lessons") : DASH,
      breeding: next,
    },
  };
}

/** The sections, in page order: the data-hook of the section and the hook of its number. */
export const SECTIONS = [
  ["camp-dogs-section", "dogs"], ["coach-section", "coach"], ["camp-drills-section", "drills"], ["camp-events-section", "cuts"],
  ["learning-chance-section", "coin"], ["learning-hold-section", "hold"], ["learning-activity-section", "activity"],
  ["learning-rules-section", "rules"], ["learning-lessons-section", "lessons"], ["learning-breeding-section", "breeding"],
];

export function paintFigures(fig, root = document) {
  const set = (hook, text) => { const el = root.querySelector(`[data-hook='${hook}']`); if (el) el.textContent = text; };
  set("camp-stat-tips", fig.strip.tips);
  set("camp-stat-helped", fig.strip.helpedHurt);
  set("camp-stat-next", fig.strip.nextCycle);
  set("camp-stat-dogs", fig.strip.dogs);
  for (const [, key] of SECTIONS) set(`camp-num-${key}`, fig.nums[key]);
}

/** Open the collapsed section a hash (or a drill) points at. Returns whether one was opened. */
export function openSectionFor(hash, root = document) {
  const id = String(hash || "").replace(/^#/, "");
  if (!id) return false;
  const target = root.getElementById ? root.getElementById(id) : null;
  const acc = target && target.querySelector ? target.querySelector("details.cp-sec") : null;
  if (!acc) return false;
  acc.open = true;
  return true;
}

async function settle(promise) {
  try { return await promise; } catch (err) { return null; }
}

export async function boot() {
  openSectionFor(location.hash);
  window.addEventListener("hashchange", () => { openSectionFor(location.hash); });
  const [coach, learning, breeding, mine] = await Promise.all([
    settle(apiGet("/hounds/coach/report")), settle(apiGet("/hounds/learning")), settle(apiGet("/hounds/breeding")),
    signedIn() ? settle(apiGet("/hounds/camp/mine")) : Promise.resolve(null)]);
  paintFigures(campFigures({ coach, learning, breeding, mine, signedInNow: signedIn() }));
}

if (typeof document !== "undefined" && typeof window !== "undefined") {
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();
}
