/**
 * What fills a quiet kennel page (critic round 2, 2026-10-19: "Kennels index + public kennel ~60% empty"). Three small pieces, all
 * built from data the page already reads or one public GET, none of them a number the server did not send:
 *
 *   featuredDog(dogs)    the one dog to put in front of a visitor: the highest paper bankroll among dogs with a settled bet; with none
 *                        settled, the dog with the most open tickets, else the first. `featuredCard` draws it big, says WHY it is featured
 *                        in words ("Highest paper bankroll", "Most open tickets", "No bets settled yet") and shows the ranking bar under 20 settled bets.
 *   activityStrip(items) the latest tickets from member dogs, from GET /hounds/stream filtered to the dog ids on the page.
 *   quietKennel(...)     the empty state: a dog that is thinking and one sentence, instead of a blank page.
 *
 * KENNEL-FIRST additions (owner ruling 2026-10-20), for My Kennel:
 *   lockText / tonightInfo / tonightStrip   the "Tonight" strip: the member's open tickets and the next locks, from each hound's own
 *                                           GET /hounds/{id}/bets?status=open. Times are the viewer's own clock; nothing is guessed.
 *   todayLine(hound, info)                  one plain line for a hound's card: "2 open · next lock 7:05 PM", "Waiting on its first game".
 *   upgradeCard(plan, founding, {tapped})  the quiet upgrade card, only when it is earned: a free account at its one hound, or a paid
 *                                           feature tapped. The founding line is the server's real count (GET /billing/offer).
 *
 * "Featured" is a reading aid, not an endorsement: nothing here says a dog is good, and a paper record this young is labelled as small.
 */

import { apiGet } from "./api.js";
import { foundingOfferLine, FOUNDING_FINE_PRINT, STANDARD_CENTS } from "./pricing.js";
import { UPGRADE_HREF } from "./upgrade.js";
import { h, houndHref, fmtPrice, NOT_REPORTED } from "./hounds-core.js";
import { dogBadge, dogFace, DEFAULT_LOOK, poseOfHound, breedLabel, breedFor } from "./dog-avatar.js";
import { bankrollNow, returnPctOf, fmtUsd, fmtPct, betsOf, recordText, onlyTickets, ticketState, RESULT_WORDS, ticketPrice, pickOf, marketLabel } from "./hounds-board.js";

export const SMALL_SAMPLE = 20;
export const STREAM_URL = "/hounds/stream?page=1&page_size=60";

const openOf = (d) => (Number.isFinite(d && d.open_bets) ? d.open_bets : 0);

/** The dog to feature, and the reason, from a flat list of dogs. Returns {dog, why} or null for no dogs. */
export function featuredDog(dogs) {
  const list = (Array.isArray(dogs) ? dogs : []).filter((d) => d && d.id && !d.retired);
  if (!list.length) return null;
  const settled = list.filter((d) => betsOf(d) > 0 && bankrollNow(d) !== null);
  if (settled.length) {
    const best = settled.slice().sort((a, b) => bankrollNow(b) - bankrollNow(a) || betsOf(b) - betsOf(a))[0];
    return { dog: best, why: "Highest paper bankroll" };
  }
  const busiest = list.slice().sort((a, b) => openOf(b) - openOf(a))[0];
  return openOf(busiest) > 0 ? { dog: busiest, why: "Most open tickets" } : { dog: list[0], why: "No bets settled yet" };
}

export function featuredCard(pick, kennelLabel = "") {
  const { dog, why } = pick;
  const bets = betsOf(dog);
  const bank = bankrollNow(dog);
  const ret = returnPctOf(dog);
  const open = openOf(dog);
  const breed = breedLabel(breedFor({ id: dog.id, name: dog.name, vibe: dog.persona && dog.persona.vibe }));
  const stat = (label, value) => h("div", { class: "kn-feat__stat" }, [h("dt", { text: label }), h("dd", { text: value })]);
  return h("section", { class: "kn-feat", "data-hook": "kennels-featured", "aria-label": "Featured hound" }, [
    h("span", { class: "kn-feat__dog", "aria-hidden": "true" }, [dogFace(dog, { size: 132, pose: poseOfHound(dog) })]),
    h("div", { class: "kn-feat__body" }, [
      h("p", { class: "kn-feat__kicker", text: `Featured hound · ${why}` }),
      h("h2", { class: "kn-feat__name" }, [h("a", { href: houndHref(dog.id), "data-hook": "featured-name", text: dog.name })]),
      h("p", { class: "kn-feat__sub hd-muted", text: [breed, kennelLabel, dog.tagline].filter(Boolean).join(" · ") }),
      h("dl", { class: "kn-feat__stats" }, [
        stat("Bankroll", bank === null ? "$1,000" : fmtUsd(bank)),
        stat("Return", bets > 0 && ret !== null ? fmtPct(ret) : "0.0%"),
        stat("Record", bets > 0 ? recordText(dog) : "no graded bets"),
        stat("Open", String(open))]),
      h("p", { class: "kn-feat__note hd-fine", "data-hook": "featured-note",
        text: bets === 0 ? "Nothing has settled yet, so there is no record to read." : bets < SMALL_SAMPLE ? `${bets} settled ${bets === 1 ? "bet" : "bets"}. Ranked in full at ${SMALL_SAMPLE}.` : `${bets} settled bets.` }),
      h("div", { class: "kn-feat__actions" }, [
        h("a", { class: "lh-btn lh-btn--soft", href: houndHref(dog.id), "data-hook": "featured-open", text: "Open this hound" }),
        h("a", { class: "lh-btn lh-btn--soft", href: `${houndHref(dog.id)}&tab=ask`, text: "Ask it why" })]),
    ])]);
}

/** One line of the activity strip: the dog's face, who, what it backed, and how it stands. */
function activityRow(t, dogs) {
  const state = ticketState(t);
  const price = ticketPrice(t);
  const dog = (dogs || []).find((d) => d.id === t.hound_id) || { id: t.hound_id, name: t.hound_name };
  return h("li", { class: "kn-act-row", "data-hook": "activity-ticket", "data-status": state }, [
    h("span", { class: "kn-act-row__dog", "aria-hidden": "true" }, [dogFace(dog, { size: 36 })]),
    h("span", { class: "kn-act-row__main" }, [
      h("a", { class: "kn-act-row__who", href: houndHref(t.hound_id), text: t.hound_name || NOT_REPORTED }),
      h("span", { class: "kn-act-row__pick" }, [h("strong", { text: pickOf(t) }), ` ${marketLabel(t.market)}${price === null ? "" : ` ${fmtPrice(price)}`}`]),
      t.game ? h("span", { class: "kn-act-row__game hd-fine", text: t.game }) : null]),
    h("span", { class: `kn-act-row__res lbres lbres--${state}`, text: RESULT_WORDS[state] })]);
}

/** The strip: the latest `n` tickets whose dog is one of `dogs`. Nothing matching returns null (the caller draws the quiet state). */
export function activityStrip(items, dogs, n = 5, title = "Latest tickets from member dogs") {
  const ids = new Set((dogs || []).map((d) => d.id));
  const mine = onlyTickets(items).filter((t) => ids.has(t.hound_id)).slice(0, n);
  if (!mine.length) return null;
  return h("section", { class: "kn-activity", "data-hook": "kennel-activity", "aria-label": title }, [
    h("h3", { class: "kn-activity__title", text: title }),
    h("ol", { class: "kn-activity__list" }, mine.map((t) => activityRow(t, dogs)))]);
}

/** The empty state: a dog that is thinking, and one sentence. */
export function quietKennel(text, { href = "build-a-hound.html", cta = "Build a dog" } = {}) {
  return h("div", { class: "kn-quiet", "data-hook": "kennel-quiet" }, [
    h("span", { class: "kn-quiet__dog", "aria-hidden": "true" }, [dogBadge(DEFAULT_LOOK, { size: 96, mood: "thinking", id: "quiet-kennel" })]),
    h("p", { class: "kn-quiet__text", text }),
    h("a", { class: "lh-btn lh-btn--solid", href, text: cta })]);
}

/** GET /hounds/stream, or null when it is not answering (the strip is then simply not drawn). */
export async function fetchStream() {
  try {
    const data = await apiGet(STREAM_URL);
    return data && Array.isArray(data.items) ? data.items : null;
  } catch (err) {
    return null;
  }
}



// ---- My Kennel: Tonight ------------------------------------------------------------------------------------

/** "7:05 PM EDT" from an ISO stamp, in the viewer's own zone, or "" when the stamp does not parse. */
export function lockText(iso, opts = {}) {
  const ms = Date.parse(String(iso || ""));
  if (!Number.isFinite(ms)) return "";
  try {
    return new Date(ms).toLocaleTimeString([], Object.assign({ hour: "numeric", minute: "2-digit" }, opts.zone === false ? {} : { timeZoneName: "short" }));
  } catch (err) {
    return "";
  }
}

/**
 * What the open tickets say, per hound and overall. `byHound` is {id: [ticket, ...]} (open tickets only). Returns
 * {rows, byId, next} where rows are every ticket, upcoming locks first (soonest first) then games already under way, byId maps a
 * hound to {open, next} and next is the soonest lock still ahead of `now`, or null.
 */
export function tonightInfo(byHound, dogs, now = Date.now()) {
  const rows = [];
  const byId = {};
  for (const dog of dogs || []) {
    const list = (byHound && byHound[dog.id]) || [];
    let next = null;
    for (const t of list) {
      const start = Date.parse(String(t.start_utc || ""));
      const ahead = Number.isFinite(start) && start >= now;
      if (ahead && (next === null || start < next)) next = start;
      rows.push({ dog, ticket: t, start: Number.isFinite(start) ? start : null, ahead });
    }
    byId[dog.id] = { open: list.length, next };
  }
  rows.sort((a, b) => (a.ahead === b.ahead ? (a.start || 0) - (b.start || 0) : a.ahead ? -1 : 1));
  const aheads = rows.filter((r) => r.ahead);
  return { rows, byId, next: aheads.length ? aheads[0].start : null };
}

/** One plain line for a hound's card about today. `info` is tonightInfo's byId entry (or undefined when the tickets are not in). */
export function todayLine(dog, info) {
  if (dog.retired || dog.status === "retired") return "Retired. Its record stays.";
  const open = Number.isFinite(dog.open_bets) ? dog.open_bets : 0;
  if (open > 0) {
    const when = info && info.next ? lockText(new Date(info.next).toISOString()) : "";
    return `${open} open${when ? ` · next lock ${when}` : ""}`;
  }
  if (dog.new) return "Waiting on its first game";
  return "Nothing open right now";
}

function tixRow(row) {
  const t = row.ticket;
  const price = ticketPrice(t);
  const when = lockText(t.start_utc);
  return h("li", { class: "kn-tix", "data-hook": "tonight-ticket", "data-ahead": row.ahead ? "true" : "false" }, [
    h("span", { class: "kn-tix__dog", "aria-hidden": "true" }, [dogFace(row.dog, { size: 32 })]),
    h("span", { class: "kn-tix__main" }, [
      h("span", { class: "kn-tix__pick" }, [h("strong", { text: pickOf(t) }), ` ${marketLabel(t.market)}${price === null ? "" : ` ${fmtPrice(price)}`}`]),
      h("span", { class: "kn-tix__game", text: [row.dog.name, t.game].filter(Boolean).join(" · ") })]),
    h("span", { class: "kn-tix__lock", text: when ? `${row.ahead ? "Locks" : "Started"} ${when}` : "" })]);
}

/**
 * The Tonight strip. `info` is tonightInfo's result, or null when the tickets could not be read (`openCount` is then the count the
 * kennel payload carried). One quiet line when nothing is open; the list never invents a ticket.
 */
export function tonightStrip(info, openCount = 0) {
  const rows = info ? info.rows.slice(0, 6) : [];
  if (!rows.length) {
    return h("section", { class: "kn-tonight kn-tonight--quiet", "data-hook": "kennel-tonight", "aria-label": "Tonight" }, [
      h("h2", { class: "kn-tonight__title", text: "Tonight" }),
      h("p", { class: "kn-tonight__line", "data-hook": "tonight-empty",
        text: openCount > 0 ? `${openCount} open across your hounds.` : "Nothing open. Your hounds bet when a game fits their rule." })]);
  }
  const next = info.next ? lockText(new Date(info.next).toISOString()) : "";
  return h("section", { class: "kn-tonight", "data-hook": "kennel-tonight", "aria-label": "Tonight" }, [
    h("div", { class: "kn-tonight__head" }, [
      h("h2", { class: "kn-tonight__title", text: "Tonight" }),
      next ? h("p", { class: "kn-tonight__next", "data-hook": "tonight-next", text: `Next lock ${next}` }) : null]),
    h("ol", { class: "kn-tonight__list" }, rows.map(tixRow)),
    info.rows.length > rows.length ? h("p", { class: "kn-tonight__more hd-fine", text: `${info.rows.length - rows.length} more open.` }) : null]);
}

// ---- My Kennel: the upgrade card, only when earned ---------------------------------------------------------------

/** "Member plan: $19.99/mo" or "" for a price in cents. */
function planLine() {
  return `Member plan: $${(STANDARD_CENTS / 100).toFixed(2)}/mo`;
}

/**
 * The quiet upgrade card. Earned means: a free account at its one hound (`plan === "free"` and `activeCount >= 1`), or a paid feature
 * was tapped (`tapped`, the studio showed the server's own upgrade prompt). Anything else returns null, and so does a payload that
 * is not a clear plan. `founding` is pricing.js's loadFoundingOffer() (GET /billing/offer, already checked: null unless a seat can be
 * had): the founding line shows only while the server says so, with its real count, and never otherwise.
 */
export function upgradeCard(plan, founding, { activeCount = 0, tapped = false } = {}) {
  const earned = tapped || (plan === "free" && activeCount >= 1);
  if (!earned) return null;
  return h("aside", { class: "kn-upgrade", "data-hook": "kennel-upgrade", "aria-label": "Member plan" }, [
    h("div", { class: "kn-upgrade__text" }, [
      h("h2", { class: "kn-upgrade__title", text: "Run up to five hounds" }),
      h("p", { class: "kn-upgrade__sub", text: "Members get more hounds, every sport, Live sends, Backtest and Ask." }),
      h("p", { class: "kn-upgrade__offer", "data-hook": "upgrade-offer", text: founding ? foundingOfferLine(founding) : planLine() }),
      founding ? h("p", { class: "kn-upgrade__fine hd-fine", text: FOUNDING_FINE_PRINT }) : null]),
    h("a", { class: "lh-btn lh-btn--soft kn-upgrade__cta", href: UPGRADE_HREF, "data-hook": "upgrade-link", text: "See the member plan" })]);
}
