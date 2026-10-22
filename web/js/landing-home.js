/**
 * The two live parts of web/landing.html, the kennel-first landing page:
 *
 *   THE STRIP    "Betting right now": the hounds the leaderboard ranks first, as small cards (a dog, a name, the record and the bet
 *                count, the return). It reads the PUBLIC GET /hounds, the same payload the leaderboard page and the old landing
 *                board read, and picks the same hounds (landing-board.js boardModels: the ranked top five, topped up from the
 *                qualifying round). Nothing is typed into the markup: with no answer the strip says so and names no figure, a
 *                server still working the numbers out says that and tries once more, and a hound short of the ranking bar is
 *                greyed with its bet count beside it, so a hot start on a handful of bets never reads as more than it is.
 *   THE OFFER    one line, "Founding member: $14.99/mo for life · N of 50 left", from GET /billing/offer. It shows only while the
 *                server says a founding seat can really be had (pricing.js foundingFromOffer): sold out, not configured or any
 *                failure means no line at all, never a guess and never a countdown.
 *
 * Fire-and-forget like every fill on the landing page: a slow or failed request leaves the page as it is. Written against
 * attributes only (no classList, no dataset, no innerHTML) so the node test harness's small DOM can run it.
 */

import { apiGet, getToken } from "./api.js";
import { withEvents } from "./unitsize.js";
import { h, clearNode, houndHref, isWarming, NOT_REPORTED } from "./hounds-core.js";
import { dogFace, dogBadge, poseOfHound } from "./dog-avatar.js";
import { MY_KENNEL_HREF } from "./home-route.js";
import { boardModels } from "./landing-board.js";
import { minRanked } from "./hounds-season.js";
import { recordText, betsOf, returnPctOf, fmtPct, isSmallSample, smallSampleTitle } from "./hounds-board.js";
import { loadFoundingOffer, foundingOfferLine } from "./pricing.js";

export const STRIP_WARMING_RETRY_MS = 6000;
/** OWNER RULING 2026-10-21: the landing page shows ONE small proof, the top three. */
export const STRIP_SIZE = 3;
/** The three step pictures: real hound art (the same coats, breeds and tiles as the quiz's personalities), cosmetic only. */
export const HOW_ART = [
  { look: { coat: "grey", bg: "maroon" }, breed: "husky", mood: "idle" },
  { look: { coat: "brown", bg: "navy" }, breed: "bulldog", mood: "happy" },
  { look: { coat: "golden", bg: "sand" }, breed: "retriever", mood: "celebrate" },
];

const q = (hook) => document.querySelector(`[data-hook='${hook}']`);
let retried = false;

function tone(n) {
  return n === null || n === undefined ? "flat" : n > 0 ? "up" : n < 0 ? "down" : "flat";
}

/** One hound on the strip: its dog, its name, the record with the bet count, and the return. A link to its page. */
export function houndCard(hound) {
  const ret = returnPctOf(hound);
  const small = isSmallSample(hound);
  const bets = betsOf(hound);
  return h("li", { class: small ? "kh-hound kh-hound--small" : "kh-hound", "data-hook": "kh-hound", "data-hound": hound.id }, [
    h("a", { class: "kh-hound__link", href: houndHref(hound.id) }, [
      h("span", { class: "kh-hound__face", "aria-hidden": "true" }, [dogFace(hound, { size: 44, pose: poseOfHound(hound) })]),
      h("span", { class: "kh-hound__name", "data-hook": "kh-name", text: hound.name || NOT_REPORTED }),
      h("span", { class: "kh-hound__rec", "data-hook": "kh-record", text: `${recordText(hound)} · ${bets} ${bets === 1 ? "bet" : "bets"}` }),
      h("span", Object.assign({ class: `kh-hound__ret kh-hound__ret--${tone(ret)}`, "data-hook": "kh-return" },
        small ? { title: smallSampleTitle(hound) } : {}), [fmtPct(ret), h("small", { text: " return" })])])]);
}

function say(row, text, hook) {
  clearNode(row);
  row.appendChild(h("li", { class: "kh-strip__empty", "data-hook": hook, text }));
}

/** Fill the strip from GET /hounds. */
export async function fillStrip() {
  const row = q("kh-strip-row");
  if (!row) return;
  let data = null;
  try { data = await apiGet(withEvents("/hounds")); } catch (err) { data = null; }
  if (!data || typeof data !== "object") { say(row, "The leaderboard is not answering right now.", "kh-strip-down"); return; }
  if (isWarming(data)) {
    say(row, "The leaderboard is warming up. Numbers in a few seconds.", "kh-strip-warming");
    if (!retried && typeof setTimeout === "function") { retried = true; setTimeout(() => { fillStrip(); }, STRIP_WARMING_RETRY_MS); }
    return;
  }
  const meta = data.season && typeof data.season === "object" ? data.season : null;
  const models = boardModels(data.hounds, meta).slice(0, STRIP_SIZE);
  if (!models.length) {
    say(row, `No hound has ${minRanked(meta)} settled bets yet. The strip fills as the slate settles.`, "kh-strip-empty-board");
    return;
  }
  clearNode(row);
  for (const hound of models) row.appendChild(houndCard(hound));
}

/** Show the founding line while a founding seat can really be had. */
export async function fillOffer() {
  const box = q("kh-offer"), line = q("kh-offer-line");
  if (!box || !line) return;
  let founding = null;
  try { founding = await loadFoundingOffer(); } catch (err) { founding = null; }
  const text = foundingOfferLine(founding);
  if (!text) return;
  line.textContent = text;
  box.removeAttribute("hidden");
}

/** Draw the real hound art into the three steps. Art that fails to draw leaves the step as plain text. */
export function fillHow() {
  const slots = Array.from(document.querySelectorAll("[data-hook='how-art']"));
  slots.forEach((slot, i) => {
    const art = HOW_ART[i % HOW_ART.length];
    try { slot.appendChild(dogBadge(art.look, { size: 88, mood: art.mood, breed: art.breed })); } catch (err) { /* text only */ }
  });
}

/** A signed-in visitor who stayed on the page (?stay=1): the first choice opens the kennel instead of asking to sign in. */
export function fillSignedIn() {
  if (!getToken()) return;
  const link = q("cta-kennel-signin");
  if (!link) return;
  link.setAttribute("href", MY_KENNEL_HREF);
  const ask = link.querySelector ? link.querySelector(".kh-choice__ask") : null;
  if (ask) ask.textContent = "Welcome back";
  const go = q("kh-signin-label");
  if (go) { clearNode(go); go.appendChild(document.createTextNode("Open My Kennel ")); go.appendChild(h("span", { "aria-hidden": "true", text: "→" })); }
}

/** Everything the landing page fills, fire-and-forget. */
export function mountHome() {
  fillHow();
  fillSignedIn();
  fillStrip();
  fillOffer();
}
