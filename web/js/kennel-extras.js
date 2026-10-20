/**
 * What fills a quiet kennel page (critic round 2, 2026-10-19: "Kennels index + public kennel ~60% empty"). Three small pieces, all
 * built from data the page already reads or one public GET, none of them a number the server did not send:
 *
 *   featuredDog(dogs)    the one dog to put in front of a visitor: the highest paper bankroll among dogs with a settled bet; with none
 *                        settled, the dog with the most open tickets, else the first. `featuredCard` draws it big, says WHY it is featured
 *                        in words ("Highest paper bankroll", "Most open tickets", "No bets settled yet") and says "small sample" under 20 settled bets.
 *   activityStrip(items) the latest tickets from member dogs, from GET /hounds/stream filtered to the dog ids on the page.
 *   quietKennel(...)     the empty state: a dog that is thinking and one sentence, instead of a blank page.
 *
 * "Featured" is a reading aid, not an endorsement: nothing here says a dog is good, and a paper record this young is labelled as small.
 */

import { apiGet } from "./api.js";
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
  return h("section", { class: "kn-feat", "data-hook": "kennels-featured", "aria-label": "Featured dog" }, [
    h("span", { class: "kn-feat__dog", "aria-hidden": "true" }, [dogFace(dog, { size: 132, pose: poseOfHound(dog) })]),
    h("div", { class: "kn-feat__body" }, [
      h("p", { class: "kn-feat__kicker", text: `Featured dog · ${why}` }),
      h("h2", { class: "kn-feat__name" }, [h("a", { href: houndHref(dog.id), "data-hook": "featured-name", text: dog.name })]),
      h("p", { class: "kn-feat__sub hd-muted", text: [breed, kennelLabel, dog.tagline].filter(Boolean).join(" · ") }),
      h("dl", { class: "kn-feat__stats" }, [
        stat("Bankroll", bank === null ? "$1,000" : fmtUsd(bank)),
        stat("Return", bets > 0 && ret !== null ? fmtPct(ret) : "0.0%"),
        stat("Record", bets > 0 ? recordText(dog) : "no graded bets"),
        stat("Open", String(open))]),
      h("p", { class: "kn-feat__note hd-fine", "data-hook": "featured-note",
        text: bets === 0 ? "Nothing has settled yet, so there is no record to read." : bets < SMALL_SAMPLE ? `${bets} settled ${bets === 1 ? "bet" : "bets"}: a small sample, not a verdict.` : `${bets} settled bets.` }),
      h("div", { class: "kn-feat__actions" }, [
        h("a", { class: "lh-btn lh-btn--solid", href: houndHref(dog.id), "data-hook": "featured-open", text: "Open this dog" }),
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

