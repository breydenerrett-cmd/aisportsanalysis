/**
 * web/kennel.html: My kennel (signed in) and a member's public kennel (?u=<handle>).
 *
 * MY KENNEL is the signed-in HOME (owner ruling 2026-10-20, kennel-first: docs/design/KENNEL_FIRST_BRIEF.md; the app shell and the landing
 * page send a member here, see home-route.js). Top to bottom: a "Tonight" strip (the open tickets of the member's hounds, soonest lock first,
 * from GET /hounds/{id}/bets?status=open); each hound as a big card with its locker-room avatar (an idle bob and blink; a happy wiggle when its
 * last pick won, a slump when it lost: all CSS, see css/lh.css), record, bankroll, return, bets and a "today" line, and exactly four buttons:
 * Unleash, Send to training, Edit and Take them out back (the burial, styled as the destructive act; see dog-rites.js); the member plan
 * card ONLY when earned (a free account at its one hound, or the studio showed the server's upgrade prompt for a paid tool); the Training camp
 * (learning.html is part of My Kennel); the latest settled results; the public page and rename links; and the Graveyard. With no hound the
 * page is one button, "Create your first hound" (the quiz). Tapping a card's art opens the STUDIO, an in-place drawer with six tabs that
 * REUSE the dog page's and the builder's own modules, never a copy of their logic (Ask, Backtest and Remove live there, not on the card):
 *
 *   Look     dog-locker.js          the locker room, previewed live on the animated avatar
 *   Rules    hounds-build.js        the English box and the rule cards (builder-skeleton.js), saved as a new version
 *   Unleash  dog-fire.js            "Unleash": what the rule would bet right now, read only
 *   Backtest dog-backtest.js        the rule over 7 / 14 / 30 days or Season 2 of stored boards, in paper dollars (hindsight)
 *   Ask      dog-ask.js             the dog's answers, worked out from its own data
 *   Record   dog-manual.js + tickets  the season record, the manual picks and the last tickets
 *
 * KENNEL NAMES. Until a member names their kennel it is "Handler 21E8"; the first visit to My kennel asks once ("Name your
 * kennel", PUT /me/kennel; "Not now" is remembered by the server) and a "Rename kennel" button stays on the page. The
 * server checks the name (2-30 characters, unique, no language the dog names refuse) and its own words are shown.
 *
 * A PUBLIC KENNEL is also the member's PROFILE: kennel name, member since, dog count, the combined paper record and
 * dollars across their dogs, their best dog and their recent tickets (all from GET /hounds/kennels/{handle}), above
 * the same cards, read only (Open and Ask are links to the dog's page), for any visitor. The data is
 * GET /hounds/kennels/mine (signed in) and GET /hounds/kennels/{handle}; a dog with no bet yet is listed and says "New".
 * The studio's deep link is ?dog=<id>&tab=<tab>. Nothing here measures anything: every number is the server's.
 *
 * THE GRAVEYARD. Every kennel page ends with a "Graveyard" section: the dogs this kennel took out back, as the frozen
 * headstones the server wrote when they were buried (dog-headstone.js). A buried dog is not in the grid, the dog count or the
 * leaderboard; a trained dog carries a "Trained xN" badge.
 *
 * A NEW MEMBER lands here with ?welcome=1 (web/js/signin.js, right after "Create free account"). While they have no
 * dog the empty state is a welcome card instead ("Build your first dog"); once they have one the flag does nothing.
 */

import { apiGet } from "./api.js";
import { TOKEN_CHANGED_EVENT } from "./api.js";
import { h, clearNode, isNum, houndHref, kennelName, describeError } from "./hounds-core.js";
import { signedIn, get, put, errorText, SIGNIN_HREF, removeDog, removedText } from "./dog-common.js";
import { dogBadge, DEFAULT_LOOK, lookFor } from "./dog-avatar.js";
import { activityStrip, quietKennel, fetchStream, tonightInfo, tonightStrip, todayLine, upgradeCard } from "./kennel-extras.js";
import { loadFoundingOffer } from "./pricing.js";
import { startTraining, startOutBack } from "./dog-rites.js";
import { headstoneCard, trainedBadge } from "./dog-headstone.js";
import { mountTabs } from "./tabs.js";
import { mountKennelRoom } from "./room-scene.js";
import { mountLocker } from "./dog-locker.js";
import { mountFire } from "./dog-fire.js";
import { mountBacktest, money } from "./dog-backtest.js";
import { bootAsk } from "./dog-ask.js";
import { mountManual } from "./dog-manual.js";
import { ticketList } from "./hounds-tickets.js";
import { bankrollNow, returnPctOf, fmtUsd, fmtPct, isSmallSample, smallSampleTitle, onlyTickets, ticketState } from "./hounds-board.js";

const q = (hook) => document.querySelector(`[data-hook='${hook}']`);

const state = {
  mode: "mine",             // "mine" | "public"
  data: null,               // the kennel payload
  open: null,               // the dog id (or "new") the studio shows
  opener: null,
  tabs: null,
  loaded: {},               // tab -> the dog id it was built for
  kit: null,
  plan: null,               // "free" | "paid" | null: from GET /hounds/mine, read once per load (null = unknown, so no upgrade card)
  founding: null,           // pricing.js loadFoundingOffer(): the real founding offer, or null
  tonight: null,            // tonightInfo(...) for the open tickets, or null until (or unless) they are read
  upgradeTapped: false,     // the studio showed the server's upgrade prompt for a paid tool
};

const STUDIO_TABS = ["look", "fire", "backtest", "ask", "record"];   // the tabs that are cleared between dogs (rules is the builder's)

const stop = (e) => { if (e && e.stopPropagation) e.stopPropagation(); };

// ---- small text helpers ------------------------------------------------------------------------------------

export function recordText(rec) {
  const r = rec || {};
  return `${r.wins || 0}-${r.losses || 0}${r.pushes ? `-${r.pushes}` : ""}`;
}

export function unitsText(rec) {
  const u = rec && rec.units_average_price;
  if (!isNum(u)) return "0.00u";
  return `${u > 0 ? "+" : ""}${u.toFixed(2)}u`;
}

/** The dog's paper account now, "$1,023" (every dog starts with the same $1,000), or "n/a" without the server's block. */
export function bankrollText(dog) {
  return fmtUsd(bankrollNow(dog));
}

/** The account's return on that start, "+2.3%", or "n/a". */
export function returnText(dog) {
  return fmtPct(returnPctOf(dog));
}

/** "$1,023 (+2.3%)" for a one-line sub-title. */
export function accountText(dog) {
  return bankrollNow(dog) === null ? "n/a" : `${bankrollText(dog)} (${returnText(dog)})`;
}

/** "happy" after a winning last pick, "slump" after a losing one, else "idle". */
export function moodOf(dog) {
  const last = dog && dog.last_pick;
  if (!last) return "idle";
  return last.result === "won" ? "happy" : last.result === "lost" ? "slump" : "idle";
}

export function statusOf(dog) {
  if (dog.retired || dog.status === "retired") return { key: "retired", text: "Retired" };
  if (dog.new) return { key: "new", text: "New" };
  if (dog.open_bets > 0) return { key: "live", text: `${dog.open_bets} open` };
  if (dog.status === "benched") return { key: "idle", text: "Idle" };
  return { key: "running", text: "Running" };
}

function lastPickText(dog) {
  const last = dog.last_pick;
  if (!last) return dog.new ? "No picks yet. It bets when a game fits its rule." : "No pick in this season yet.";
  const word = { won: "won", lost: "lost", push: "push", void: "void", pending: "pending" }[last.result] || last.result;
  return `Last pick: ${last.selection || "a pick"} (${word})`;
}

const avatarOf = (dog, size, mood) => dogBadge(dog.look || lookFor(dog.root_id || dog.id), { size, mood: mood || moodOf(dog), id: dog.root_id || dog.id, name: dog.name, vibe: dog.persona && dog.persona.vibe, version: dog.version_no });

// ---- cards ------------------------------------------------------------------------------------------------

function stat(label, value, extra = {}) {
  return h("div", { class: "kn-stat" }, [h("dt", { text: label }), h("dd", Object.assign({ text: value }, extra))]);
}

function dogCard(dog, { mine }, index) {
  const status = statusOf(dog);
  const rec = dog.record || {};
  const mood = moodOf(dog);
  const open = () => openStudio(dog.id, "look", card);
  // KENNEL-FIRST (owner ruling 2026-10-20): the card offers Unleash, Send to training, Edit and Take them out back, and nothing else. Ask, Backtest and Remove live in
  // the studio (tap the card's art); the hound's page is its name.
  const actions = mine && !dog.retired
    ? [
      h("button", { type: "button", class: "kn-act kn-act--primary", "data-hook": "dog-action-fire", text: "Unleash",
        "aria-label": `Unleash ${dog.name}`, on: { click: (e) => { stop(e); openStudio(dog.id, "fire", card, { autofire: true }); } } }),
      h("button", { type: "button", class: "kn-act", "data-hook": "dog-action-train", text: "Send to training",
        "aria-label": `Send ${dog.name} to training`, on: { click: (e) => { stop(e); sendToTraining(dog, e.currentTarget); } } }),
      h("button", { type: "button", class: "kn-act kn-act--edit", "data-hook": "dog-action-edit", text: "Edit",
        "aria-label": `Edit ${dog.name}`, on: { click: (e) => { stop(e); openStudio(dog.id, "rules", card); } } }),
      h("button", { type: "button", class: "kn-act kn-act--danger", "data-hook": "dog-action-outback", text: "Take them out back",
        "aria-label": `Take ${dog.name} out back`, on: { click: (e) => { stop(e); takeOutBack(dog, e.currentTarget); } } })]
    : mine
      ? [h("a", { class: "kn-act", href: houndHref(dog.id), "data-hook": "dog-action-open", text: "Open" }),
        h("a", { class: "kn-act", href: dog.builder_href || "build-a-hound.html", "data-hook": "dog-action-copy", text: "Build a copy" })]
      : [h("a", { class: "kn-act kn-act--primary", href: houndHref(dog.id), "data-hook": "dog-action-open", text: "Open" }),
        h("a", { class: "kn-act", href: `${houndHref(dog.id)}&tab=ask`, "data-hook": "dog-action-ask", text: "Ask" })];
  const small = isSmallSample(dog) ? { title: smallSampleTitle(dog), "data-small": "true" } : {};
  const card = h("article", { class: "kn-card", "data-hook": "kennel-dog", "data-id": dog.id, "data-status": status.key, "data-mood": mood,
    style: `--i:${Math.min(index, 12)}` }, [
    h("div", { class: "kn-card__head" }, [
      h("button", { type: "button", class: "kn-card__avatar", "data-hook": "dog-avatar", "aria-label": mine ? `Open ${dog.name}'s studio` : `${dog.name}`,
        on: { click: mine ? open : () => { window.location.href = houndHref(dog.id); } } }, [avatarOf(dog, 104, mood)]),
      h("div", { class: "kn-card__id" }, [
        h("h3", { class: "kn-card__name" }, [h("a", { href: houndHref(dog.id), "data-hook": "dog-name", text: dog.name })]),
        dog.tagline ? h("p", { class: "kn-card__tag", text: dog.tagline }) : null,
        h("div", { class: "kn-card__badges" }, [
          h("span", { class: "kn-pill", "data-status": status.key, "data-hook": "dog-status" }, [
            status.key === "live" ? h("i", { class: "lh-live", "aria-hidden": "true" }) : null, status.text]),
          trainedBadge(dog.trained_times)])])]),
    h("div", { class: "kn-card__main" }, [
      mine ? h("p", { class: "kn-card__today", "data-hook": "dog-today", text: todayLine(dog, state.tonight && state.tonight.byId[dog.id]) }) : null,
      h("dl", { class: "kn-stats" }, [
        stat("Record", recordText(rec), { "data-hook": "dog-record" }),
        stat("Bankroll", bankrollText(dog), Object.assign({ "data-hook": "dog-bankroll", "data-count": "1" }, small)),
        stat("Return", returnText(dog), Object.assign({ "data-hook": "dog-return" }, small)),
        stat("Bets", String(rec.bets || 0), { "data-hook": "dog-bets", "data-count": "1" })]),
      h("p", { class: "kn-card__last", "data-hook": "dog-last", text: lastPickText(dog) }),
      h("div", { class: "kn-card__actions" }, actions)]),
  ]);
  return card;
}

/** After a rite: close the studio, redraw the kennel from the server, say what happened and refresh the builder's list. */
async function afterRite(message) {
  closeStudio();
  await load({ quiet: true });
  say(message);
  try {
    const builder = await import("./hounds-build.js");
    if (builder.builderReady()) await builder.refreshMine();
  } catch (err) { /* the builder is not on this page yet: it reads the list when it loads */ }
}

/** Send to training (dog-rites.js): one confirmation, the montage, the "what changed and why" card; then the kennel redraws. */
function sendToTraining(dog, opener) {
  return startTraining(dog, { opener, onTrained: (r) => afterRite(`${dog.name} is back as version ${r.new.version_no}. Its new record starts now.`) });
}

/** Take them out back (dog-rites.js): two confirmations, the burial, the reveal; then the kennel redraws without the dog. */
function takeOutBack(dog, opener) {
  return startOutBack(dog, { opener, onBuried: () => afterRite(`${dog.name} was taken out back. Its record is frozen in the graveyard.`) });
}

/** "Remove from my kennel": ask, retire, say so, and redraw. The dog's record stays on the ledger (see dog-common.js removeDog). */
async function removeFromKennel(dog) {
  const res = await removeDog(dog);
  if (res.cancelled) return;
  if (!res.ok) { say(res.message, "error"); return; }
  closeStudio();
  await load({ quiet: true });
  say(removedText(dog.name));
  try {
    const builder = await import("./hounds-build.js");
    if (builder.builderReady()) await builder.refreshMine();
  } catch (err) { /* the builder is not on this page yet: it reads the list when it loads */ }
}

function say(text, kind) {
  const box = q("kennel-status");
  if (!box) return;
  box.textContent = text || "";
  if (kind) box.setAttribute("data-kind", kind); else box.removeAttribute("data-kind");
}

/** True when the page was opened right after a free signup (?welcome=1). */
export function isWelcome() {
  return new URLSearchParams(window.location.search).get("welcome") === "1";
}

/** The first thing a new free member sees: one welcome and the one next step, the quiz that finds their first hound. */
function welcomeCard() {
  return h("div", { class: "kn-empty kn-welcome", "data-hook": "kennel-welcome" }, [
    h("div", { class: "kn-empty__dog", "aria-hidden": "true" }, [dogBadge(DEFAULT_LOOK, { size: 112, mood: "thinking", id: "welcome" })]),
    h("h2", { text: "Welcome to your kennel" }),
    h("p", { class: "hd-lede", text: "Your account is free. Four quick questions find your first hound, and it bets on paper money." }),
    h("a", { class: "lh-btn lh-btn--solid kn-empty__cta", href: "quiz.html", "data-hook": "kennel-welcome-build", text: "Create your first hound" })]);
}

/** No hounds yet: one button. */
function emptyMine() {
  return h("div", { class: "kn-empty", "data-hook": "kennel-empty" }, [
    h("div", { class: "kn-empty__dog", "aria-hidden": "true" }, [dogBadge(DEFAULT_LOOK, { size: 112, mood: "thinking", id: "empty-kennel" })]),
    h("h2", { text: "No hounds yet" }),
    h("p", { class: "hd-lede", text: "Create one and it starts betting on paper money." }),
    h("a", { class: "lh-btn lh-btn--solid kn-empty__cta", href: "quiz.html", "data-hook": "kennel-empty-build", text: "Create your first hound" })]);
}

// ---- the page ---------------------------------------------------------------------------------------------

function setHead({ eyebrow, title, sub }) {
  q("kennel-eyebrow").textContent = eyebrow;
  q("kennel-title").textContent = title;
  q("kennel-sub").textContent = sub || "";
  document.title = `${title} — LINEHOUND`;
}

function gate(kind) {
  const box = q("kennel-gate");
  clearNode(box);
  clearNode(q("kennel-grid"));
  clearNode(q("kennel-actions"));
  box.hidden = false;
  if (kind === "signin") {
    setHead({ eyebrow: "", title: "My Kennel", sub: "" });
    box.appendChild(h("div", { class: "kn-empty", "data-hook": "kennel-signin" }, [
      h("div", { class: "kn-empty__dog", "aria-hidden": "true" }, [dogBadge(DEFAULT_LOOK, { size: 112 })]),
      h("h2", { text: "Sign in to see your hounds" }),
      h("p", { class: "hd-lede", text: "Your kennel is where you create, train and unleash them." }),
      h("div", { class: "kn-empty__row" }, [
        h("a", { class: "lh-btn lh-btn--soft", href: SIGNIN_HREF, "data-hook": "kennel-signin-link", text: "Sign in" }),
        h("a", { class: "lh-btn lh-btn--soft", href: "hounds.html", "data-hook": "kennel-browse", text: "See the leaderboard" })])]));
  } else {
    setHead({ eyebrow: "Kennel", title: "Kennel not found", sub: "" });
    box.appendChild(h("div", { class: "kn-empty", "data-hook": "kennel-missing" }, [
      h("h2", { text: "No kennel with that name" }),
      h("p", { class: "hd-lede", text: "It may have no public hounds, or the link is off." }),
      h("a", { class: "lh-btn lh-btn--soft", href: "hounds.html?tab=kennels", text: "See all kennels" })]));
  }
}

// ---- the kennel name -------------------------------------------------------------------------------------

/** The div above the grid that one feature owns (kennel.html), emptied: a re-render replaces it, never stacks a second. */
function slot(hook) {
  return clearNode(q(hook) || h("div"));
}

/** "Name your kennel": one text box, Save and (for the first-visit prompt) Not now. */
function nameForm(data, { first }) {
  const limits = data.name_limits || { min: 2, max: 30 };
  const input = h("input", { type: "text", class: "lh-input", name: "kennel_name", maxlength: String(limits.max), minlength: String(limits.min),
    autocomplete: "off", "data-hook": "kennel-name-input", "aria-label": "Kennel name", placeholder: "Bob's Hounds", value: data.kennel_name || "" });
  const status = h("p", { class: "hd-fine", role: "status", "aria-live": "polite", "data-hook": "kennel-name-status" });
  const save = h("button", { type: "submit", class: "lh-btn lh-btn--solid", "data-hook": "kennel-name-save", text: "Save name" });
  const close = async (dismiss) => {
    if (dismiss) { try { await put("/me/kennel", { dismiss_prompt: true }); } catch (err) { /* it asks again next visit: harmless */ } }
    clearNode(q("kennel-name-slot"));
  };
  // COMPACT (owner add-on 2026-10-21): the hound is the product, and the old card pushed it below the fold at 375px. One heading line, the
  // input with Save / Not now beside it, and the helper text behind a small "rules" toggle. The slot now sits BELOW the hounds (kennel.html).
  const helper = `${data.kennel_name ? `Your kennel is called ${data.kennel_name}.` : `Until you name it, your kennel shows as ${data.display}.`} Everyone sees the name on your hounds, the leaderboard and your public page. ${limits.min} to ${limits.max} characters: letters, numbers, spaces, hyphens and apostrophes.`;
  const form = h("form", { class: "kn-nameform", "data-hook": "kennel-name-form", novalidate: "" }, [
    h("div", { class: "kn-nameform__head" }, [
      h("h2", { class: "hd-h3", text: first ? "Name your kennel" : "Rename your kennel" }),
      h("details", { class: "kn-nameform__rules", "data-hook": "kennel-name-rules" }, [
        h("summary", { text: "rules" }), h("p", { class: "hd-muted", text: helper })])]),
    h("div", { class: "kn-nameform__row" }, [input, save,
      first ? h("button", { type: "button", class: "lh-btn lh-btn--soft", "data-hook": "kennel-name-skip", text: "Not now", on: { click: () => close(true) } })
        : h("button", { type: "button", class: "lh-btn lh-btn--soft", "data-hook": "kennel-name-cancel", text: "Cancel", on: { click: () => close(false) } })]),
    status]);
  form.addEventListener("submit", async (evt) => {
    evt.preventDefault();
    const name = String(input.value || "").trim();
    if (!name) { status.textContent = "Type a name first."; return; }
    save.setAttribute("disabled", "");
    status.textContent = "Saving...";
    try {
      await put("/me/kennel", { kennel_name: name });
      await load({ quiet: true });
      clearNode(q("kennel-name-slot"));
    } catch (err) {
      status.textContent = errorText(err, "The name could not be saved just now. Try again in a minute.");
      save.removeAttribute("disabled");
    }
  });
  return form;
}

function openNameForm(first) {
  const box = slot("kennel-name-slot");
  box.appendChild(h("section", { class: "kn-name hd-panel", "data-hook": first ? "kennel-name-prompt" : "kennel-name-editor" }, [nameForm(state.data, { first })]));
  const input = box.querySelector("[data-hook='kennel-name-input']");
  if (input && input.focus && !first) input.focus();
}

// ---- the public profile ----------------------------------------------------------------------------------

function profileStat(label, value, hook) {
  return h("div", { class: "kn-stat" }, [h("dt", { text: label }), h("dd", Object.assign({ text: value }, hook ? { "data-hook": hook } : {}))]);
}

/** The member's profile block: the numbers the server added up, and what their dogs did lately. */
export function profileCard(data) {
  const c = data.combined || {};
  const rec = c.record || {};
  const settled = c.settled || 0;
  const best = data.best;
  const stats = h("dl", { class: "kn-stats kn-stats--wide", "data-hook": "kennel-profile-stats" }, [
    profileStat("Member since", data.member_since || "n/a", "profile-since"),
    profileStat("Hounds", String(data.dog_count || 0), "profile-dogs"),
    profileStat("Paper record", settled ? recordText(rec) : "no settled bets", "profile-record"),
    profileStat("Paper dollars", settled && isNum(c.pnl_usd) ? money(c.pnl_usd) : "n/a", "profile-usd"),
    profileStat("Return", settled && isNum(c.return_pct) ? `${c.return_pct > 0 ? "+" : ""}${c.return_pct.toFixed(2)}%` : "n/a", "profile-return"),
    profileStat("Best hound", best ? `${best.name}, ${recordText(best.record)}` : "none yet", "profile-best")]);
  const tickets = Array.isArray(data.recent_tickets) ? data.recent_tickets : [];
  const list = tickets.length
    ? h("ul", { class: "dk-misses", "data-hook": "profile-tickets" }, tickets.map((t) => h("li", { class: "dk-miss", "data-hook": "profile-ticket" }, [
      h("strong", { text: t.selection || "A pick" }), ` in ${t.game || "a game"}, ${String(t.date || "").slice(0, 10)}: ${t.result}. `,
      h("a", { href: (t.dog && t.dog.href) || "#", text: (t.dog && t.dog.name) || "its hound" })])))
    : h("p", { class: "hd-muted", "data-hook": "profile-no-tickets", text: "No tickets yet across these hounds." });
  return h("section", { class: "hd-panel kn-profile", "data-hook": "kennel-profile" }, [
    h("h2", { class: "hd-h3", text: "Profile" }), stats,
    h("p", { class: "hd-fine", text: `Combined across ${data.dog_count === 1 ? "its hound" : "its hounds"}: each hound starts with its own $1,000 paper bankroll (1 unit = $10). Paper only.` }),
    h("h3", { class: "hd-h3", text: "Recent tickets" }), list]);
}

function render() {
  const data = state.data;
  const mine = state.mode === "mine";
  const grid = clearNode(q("kennel-grid"));
  q("kennel-gate").hidden = true;
  const active = data.dogs.filter((d) => !d.retired);
  const retired = data.dogs.filter((d) => d.retired);
  const actions = clearNode(q("kennel-actions"));
  const noun = (n) => `${n} ${n === 1 ? "hound" : "hounds"}`;
  // no hound yet: the page is one button, so the paper line, the links row and an empty graveyard step aside
  const app = q("kennel-app");
  if (app) app.setAttribute("data-empty", mine && !data.dogs.length ? "true" : "false");
  if (mine) {
    setHead({ eyebrow: "", title: "My Kennel", sub: [data.kennel_name, active.length ? noun(active.length) : ""].filter(Boolean).join(" · ") });
    // one quiet way to make another: the quiz is the front door to a hound
    if (active.length) actions.appendChild(h("a", { class: "lh-btn lh-btn--soft", href: "quiz.html", "data-hook": "kennel-build", text: "Create a hound" }));
    paintMore(data);
  } else {
    const best = data.best;
    setHead({ eyebrow: "Kennel", title: kennelName(data.title || data.display),
      sub: `${noun(data.dog_count)}${best ? `. Best: ${best.name}, ${recordText(best.record)}` : ". No bets settled yet"}.` });
    if (q("kennel-more")) clearNode(q("kennel-more"));
  }
  if (!mine && data.combined) slot("kennel-profile-slot").appendChild(profileCard(data));
  else if (q("kennel-profile-slot")) clearNode(q("kennel-profile-slot"));
  if (mine && data.needs_name_prompt && !q("kennel-name-prompt")) openNameForm(true);
  else if (mine && !data.needs_name_prompt && q("kennel-name-prompt")) clearNode(q("kennel-name-slot"));
  if (!data.dogs.length && mine) {
    grid.appendChild(isWelcome() ? welcomeCard() : emptyMine());
  } else {
    active.forEach((dog, i) => grid.appendChild(dogCard(dog, { mine }, i)));
  }
  paintTonight();
  paintUpgrade();
  paintCamp();
  if (mine && !data.dogs.length && !(Array.isArray(data.graveyard) && data.graveyard.length)) clearNode(q("kennel-graveyard"));
  else paintGraveyard(data);
  const rest = clearNode(q("kennel-retired"));
  if (mine && retired.length) {
    rest.appendChild(h("details", { class: "kn-retired", "data-hook": "kennel-retired-list" }, [
      h("summary", { text: `Retired (${retired.length})` }),
      h("div", { class: "kn-grid kn-grid--quiet" }, retired.map((d, i) => dogCard(d, { mine }, i)))]));
  }
}

/** The quiet row under My Kennel: the public page and the rename button. */
function paintMore(data) {
  const host = q("kennel-more");
  if (!host) return;
  clearNode(host);
  host.appendChild(h("a", { class: "kn-link", href: `kennel.html?u=${encodeURIComponent(data.handle)}`, "data-hook": "kennel-public-link", text: "Public page" }));
  host.appendChild(h("button", { type: "button", class: "kn-link", "data-hook": "kennel-rename", text: data.kennel_name ? "Rename kennel" : "Name your kennel",
    on: { click: () => openNameForm(false) } }));
}

/** The Tonight strip (My Kennel with at least one active hound): the open tickets and the next locks. */
function paintTonight() {
  const host = q("kennel-tonight-slot");
  if (!host) return;
  clearNode(host);
  if (state.mode !== "mine" || !state.data) return;
  const active = state.data.dogs.filter((d) => !d.retired);
  if (!active.length) return;
  const openCount = active.reduce((n, d) => n + (Number.isFinite(d.open_bets) ? d.open_bets : 0), 0);
  host.appendChild(tonightStrip(state.tonight, openCount));
}

/** Each card's "today" line, once the open tickets are in (it already reads the payload's own count before that). */
function paintToday() {
  if (!state.data) return;
  for (const dog of state.data.dogs) {
    const node = document.querySelector(`[data-hook='kennel-dog'][data-id='${dog.id}'] [data-hook='dog-today']`);
    if (node) node.textContent = todayLine(dog, state.tonight && state.tonight.byId[dog.id]);
  }
}

/** The upgrade card, only when earned: a free account at its one hound, or a paid tool was tapped. */
function paintUpgrade() {
  const host = q("kennel-upgrade-slot");
  if (!host) return;
  clearNode(host);
  if (state.mode !== "mine" || !state.data) return;
  const card = upgradeCard(state.plan, state.founding, { activeCount: state.data.dogs.filter((d) => !d.retired).length, tapped: state.upgradeTapped });
  if (card) host.appendChild(card);
}

/** The Training camp, part of My Kennel: a quiet card that opens the camp page (backtests, the coach's report card, breeding). */
function paintCamp() {
  const host = q("kennel-camp-slot");
  if (!host) return;
  clearNode(host);
  if (state.mode !== "mine" || !state.data || !state.data.dogs.some((d) => !d.retired)) return;
  host.appendChild(h("section", { class: "kn-camp", "data-hook": "kennel-camp", "aria-label": "Training camp" }, [
    h("div", { class: "kn-camp__text" }, [
      h("h2", { class: "kn-camp__title", text: "Training camp" }),
      h("p", { class: "kn-camp__sub", text: "Backtest a hound, read the coach's report card and see the breeding." })]),
    h("a", { class: "lh-btn lh-btn--soft", href: "learning.html", "data-hook": "kennel-camp-link", text: "Open the camp" })]));
}

/** The Graveyard: a quiet link to the page and the headstones this kennel's rites made, newest first (they come from the server that way). */
function paintGraveyard(data) {
  const host = q("kennel-graveyard");
  if (!host) return;
  clearNode(host);
  const stones = Array.isArray(data.graveyard) ? data.graveyard : [];
  const mine = state.mode === "mine";
  host.appendChild(h("section", { class: "kn-graveyard", "data-hook": "kennel-graveyard-section", "aria-labelledby": "kn-grave-h" }, [
    h("h2", { id: "kn-grave-h", class: "kn-graveyard__title", text: "Graveyard" }),
    stones.length
      ? h("p", { class: "hd-muted", text: `${stones.length} ${stones.length === 1 ? "hound" : "hounds"} ${mine ? "you took" : "this kennel took"} out back. Each record is frozen.` })
      : h("p", { class: "hd-muted", "data-hook": "kennel-graveyard-empty", text: mine ? "Nothing buried. A hound you take out back lands here with a headstone." : "Nothing buried here." }),
    stones.length ? h("div", { class: "hs-list", "data-hook": "kennel-graveyard-list" }, stones.map((s) => headstoneCard(s, { compact: false, showKennel: false }))) : null,
    h("p", { class: "hd-fine" }, [h("a", { class: "kn-link", href: "graveyard.html", "data-hook": "kennel-graveyard-link", text: "See every headstone" })])]));
}

/** The latest results from this kennel's hounds, or a quiet state with a thinking hound when there are none yet. Never throws. */
async function fillExtras() {
  const host = q("kennel-extras");
  if (!host || !state.data) return;
  const dogs = (state.data.dogs || []).filter((d) => !d.retired);
  if (!dogs.length) { clearNode(host); return; }
  const mine = state.mode === "mine";
  const items = await fetchStream();
  // My Kennel shows what has SETTLED here (what is still open is the Tonight strip above); a public kennel shows everything it posted
  const shown = mine && items ? onlyTickets(items).filter((t) => ticketState(t) !== "pending") : items;
  const strip = activityStrip(shown, dogs, 5, mine ? "Latest results" : "Latest tickets from this kennel");
  clearNode(host);
  if (strip) { host.appendChild(strip); return; }
  if (mine) return;                  // nothing settled yet: Tonight and the cards already say what is going on
  host.appendChild(quietKennel("No tickets from this kennel yet. Its hounds bet when a game fits their rule.", { href: "hounds.html?tab=kennels", cta: "See all kennels" }));
}

/**
 * The open tickets of the member's own hounds (GET /hounds/{id}/bets?status=open), one request per hound that says it has some, and the
 * plan and founding offer for the upgrade card. All soft: a failure leaves the payload's own counts on the page and no upgrade card.
 */
async function fillTonight() {
  if (state.mode !== "mine" || !state.data) return;
  const active = state.data.dogs.filter((d) => !d.retired);
  const asked = active.filter((d) => Number.isFinite(d.open_bets) && d.open_bets > 0);
  const [lists, plan, founding] = await Promise.all([
    Promise.all(asked.map(async (d) => {
      try {
        const out = await apiGet(`/hounds/${encodeURIComponent(d.id)}/bets?page=1&page_size=8&segment=forward&status=open`);
        return [d.id, Array.isArray(out && out.items) ? out.items : null];
      } catch (err) { return [d.id, null]; }
    })),
    readPlan(),
    loadFoundingOffer(),
  ]);
  if (state.mode !== "mine" || !state.data) return;
  const byHound = {};
  let read = 0;
  for (const [id, items] of lists) { if (items) { byHound[id] = items; read++; } }
  state.tonight = read ? tonightInfo(byHound, active) : null;
  state.plan = plan;
  state.founding = founding;
  paintToday();
  paintTonight();
  paintUpgrade();
}

/** "free" or "paid" from GET /hounds/mine (the builder's own list, which says which plan the account is on), or null when unknown. */
async function readPlan() {
  try {
    const out = await apiGet("/hounds/mine");
    return out && (out.plan === "free" || out.plan === "paid") ? out.plan : null;
  } catch (err) {
    return null;
  }
}

async function load({ quiet = false } = {}) {
  const params = new URLSearchParams(window.location.search);
  const handle = params.get("u");
  state.mode = handle ? "public" : "mine";
  if (!quiet) {
    clearNode(q("kennel-grid")).appendChild(h("div", { class: "lh-skel lh-skel--cards", "aria-hidden": "true" }));
  }
  if (state.mode === "mine" && !signedIn()) { gate("signin"); return null; }
  try {
    state.data = await apiGet(state.mode === "mine" ? "/hounds/kennels/mine" : `/hounds/kennels/${encodeURIComponent(handle)}`);
  } catch (err) {
    if (state.mode === "mine" && err && (err.status === 401 || err.status === 403)) { gate("signin"); return null; }
    if (err && err.status === 404 && state.mode === "public") { gate("missing"); return null; }
    const box = clearNode(q("kennel-grid"));
    box.appendChild(h("div", { class: "hd-state hd-state--down", role: "alert", "data-hook": "section-state" }, [
      h("p", { text: describeError(err, "this kennel").text })]));
    return null;
  }
  render();
  mountKennelRoom(q("kennel-room"), state.mode === "mine" ? state.data : null, { onStudio: (id, tab) => openStudio(id, tab) });   // "Your kennel room" (room-scene.js)
  fillExtras();
  fillTonight();
  return state.data;
}

// ---- the studio -------------------------------------------------------------------------------------------

const dogById = (id) => (state.data ? state.data.dogs.find((d) => d.id === id) : null);

function studioDog() {
  return state.open && state.open !== "new" ? dogById(state.open) : null;
}

function paintStudioHead(look) {
  const dog = studioDog();
  const av = clearNode(q("studio-avatar"));
  const sub = q("studio-sub");
  const remove = q("studio-remove");
  if (remove) remove.hidden = !(dog && !dog.retired);
  if (!dog) {
    av.appendChild(dogBadge(look || DEFAULT_LOOK, { size: 64, id: "new-dog", mood: "thinking" }));
    q("studio-title").textContent = "New hound";
    sub.textContent = "Say a strategy and it becomes a hound.";
    q("studio-open").hidden = true;
    return;
  }
  av.appendChild(dogBadge(look || dog.look || lookFor(dog.root_id || dog.id), { size: 64, mood: moodOf(dog), id: dog.root_id || dog.id, name: dog.name, vibe: dog.persona && dog.persona.vibe, version: dog.version_no }));
  q("studio-title").textContent = dog.name;
  sub.textContent = `${recordText(dog.record)}, ${accountText(dog)}${dog.tagline ? ` · ${dog.tagline}` : ""}`;
  const link = q("studio-open");
  link.hidden = false;
  link.setAttribute("href", houndHref(dog.id));
}

function section(hook) {
  return h("section", { class: "dk-panel kn-section" }, [h("div", { "data-hook": hook })]);
}

async function buildTab(tab) {
  const dog = studioDog();
  const id = state.open;
  if (state.loaded[tab] === id) return;
  state.loaded[tab] = id;
  const host = q(`studio-${tab}`);
  clearNode(host);
  if (tab === "rules") return buildRules(host, dog);
  if (!dog) return;
  host.appendChild(h("div", { class: "lh-skel lh-skel--rows", "aria-hidden": "true" }));
  try {
    if (!state.kit || state.kit.dog_id !== dog.id) state.kit = await get(`/hounds/${encodeURIComponent(dog.id)}/kit`);
  } catch (err) {
    clearNode(host).appendChild(h("p", { class: "hd-muted", text: describeError(err, "this hound").text }));
    state.loaded[tab] = null;
    return;
  }
  const kit = state.kit;
  clearNode(host);
  if (tab === "look") {
    const sec = section("dog-locker");
    host.appendChild(sec);
    mountLocker(sec, { id: dog.id, name: dog.name, kit, vibe: dog.persona && dog.persona.vibe, onChange: (look) => paintStudioHead(look),
      onSaved: (look) => { dog.look = look; refreshCards(); } });
  } else if (tab === "fire") {
    const sec = section("dog-fire");
    host.appendChild(sec);
    mountFire(sec, { id: dog.id, name: dog.name, kit, onRecord: () => { state.loaded.record = null; } });
  } else if (tab === "backtest") {
    const sec = section("dog-backtest");
    host.appendChild(sec);
    mountBacktest(sec, { id: dog.id, name: dog.name });
  } else if (tab === "ask") {
    const sec = section("dog-ask");
    host.appendChild(sec);
    await bootAsk(sec, { id: dog.id, name: dog.name });
  } else if (tab === "record") {
    await buildRecord(host, dog, kit);
  }
}

async function buildRecord(host, dog, kit) {
  const rec = dog.record || {};
  host.appendChild(h("dl", { class: "kn-stats kn-stats--wide", "data-hook": "studio-record-stats" }, [
    stat("Record", recordText(rec)), stat("Bankroll", bankrollText(dog)), stat("Return", returnText(dog)),
    stat("Bets", String(rec.bets || 0)),
    stat("Open", String(dog.open_bets || 0))]));
  host.appendChild(h("p", { class: "hd-fine", text: `${state.data.season && state.data.season.label ? state.data.season.label : "This season"}, a paper account that started with $1,000 (1 unit = $10), bets settled at the average price.` }));
  const tickets = h("div", { "data-hook": "studio-tickets" });
  host.appendChild(h("h3", { class: "hd-h3", text: "Last tickets" }));
  host.appendChild(tickets);
  try {
    const out = await apiGet(`/hounds/${encodeURIComponent(dog.id)}/bets?page=1&page_size=5&segment=forward`);
    const items = Array.isArray(out && out.items) ? out.items : [];
    if (items.length) tickets.appendChild(ticketList(items, { showModel: false, hook: "studio-ticket-list" }));
    else tickets.appendChild(h("p", { class: "hd-muted", text: "No tickets recorded yet." }));
  } catch (err) {
    tickets.appendChild(h("p", { class: "hd-muted", text: describeError(err, "this hound's tickets").text }));
  }
  const manual = h("section", { class: "dk-panel kn-section", hidden: "" }, [h("h3", { class: "hd-h3", text: "Manual picks" }), h("div", { "data-hook": "dog-manual" })]);
  host.appendChild(manual);
  await mountManual(manual, { id: dog.id, kit });
}

// ONE builder per page. hounds-build.js binds its listeners once, to the first skeleton it boots on (module state).
// buildTab clears the Rules panel each time it opens, so a fresh skeleton per open was dead on arrival: the second
// Rules panel of a visit (another dog, or New dog) had no listeners at all. The same element is moved back in
// instead, listeners and all.
let rulesSkeleton = null;

async function buildRules(host, dog) {
  const { builderSkeleton } = await import("./builder-skeleton.js");
  if (!rulesSkeleton) rulesSkeleton = builderSkeleton();
  if (rulesSkeleton.parentNode !== host) host.appendChild(rulesSkeleton);
  const builder = await import("./hounds-build.js");
  await builder.booted;
  if (state.open !== (dog ? dog.id : "new")) return;
  if (!dog) { builder.openBlank(); return; }
  if (dog.retired) {
    host.appendChild(h("p", { class: "hd-muted", "data-hook": "studio-retired-note" }, [
      "A retired hound cannot be edited. ", h("a", { href: dog.builder_href || "build-a-hound.html", text: "Build a copy" }), "."]));
    return;
  }
  if (!builder.builderReady()) {
    host.appendChild(editProblem("The rule builder did not load (a bad connection, or it is busy for a moment).", dog));
    return;
  }
  const opened = await builder.openEdit(dog.id);
  if (!opened.ok) {
    host.appendChild(editProblem(opened.reason === "signed_out" ? "Your sign-in has lapsed, so this hound cannot be opened for editing. "
      : "That hound could not be found in your list just now.", dog, opened.reason === "signed_out"));
  }
}

/** Why Edit did not open, in words, with a way forward: sign in, or try again. Never a dead end. */
function editProblem(text, dog, signIn) {
  return h("p", { class: "hd-muted", "data-hook": "studio-edit-problem" }, [`${text} `,
    signIn ? h("a", { href: SIGNIN_HREF, text: "Sign in" }) : h("button", { type: "button", class: "lh-btn lh-btn--soft", "data-hook": "studio-edit-retry", text: "Try again",
      on: { click: async () => {
        try { const builder = await import("./hounds-build.js"); await builder.reboot(); } catch (err) { /* openStudio says what is still wrong */ }
        state.loaded.rules = null;
        openStudio(dog.id, "rules");
      } } })]);
}

function refreshCards() {
  if (state.data) {
    const grid = q("kennel-grid");
    const scroll = grid ? grid.scrollTop : 0;
    render();
    if (grid) grid.scrollTop = scroll;
  }
}

export function openStudio(id, tab = "look", opener = null, { autofire = false } = {}) {
  const studio = q("studio");
  if (!studio || state.mode !== "mine") return;
  state.open = id;
  state.opener = opener;
  state.kit = null;
  state.loaded = {};
  for (const k of STUDIO_TABS) clearNode(q(`studio-${k}`));
  if (id === "new" || !dogById(id)) {
    state.open = "new";
    clearNode(q("studio-rules"));
  } else if (q("studio-rules")) {
    clearNode(q("studio-rules"));
  }
  const fresh = state.open === "new";
  for (const t of document.querySelectorAll("[data-hook='studio-tabs'] [role='tab']")) {
    if (t.getAttribute("data-tab") === "rules") t.removeAttribute("hidden");
    else if (fresh) t.setAttribute("hidden", ""); else t.removeAttribute("hidden");
  }
  paintStudioHead();
  q("studio-scrim").hidden = false;
  studio.hidden = false;
  studio.setAttribute("data-open", "true");
  document.body.style.overflow = "hidden";
  if (!state.tabs) state.tabs = mountTabs(q("studio-tabs"), { onChange: (key) => { buildTab(key).then(() => { if (key === "fire" && state.autofire) { state.autofire = false; const b = q("fire-btn"); if (b) b.click(); } }); } });
  state.autofire = autofire;
  const want = fresh ? "rules" : tab;
  if (state.tabs.current === want) buildTab(want); else state.tabs.select(want);
  writeUrl(state.open === "new" ? null : state.open, want);
  const close = q("studio-close");
  if (close && close.focus) close.focus();
}

function writeUrl(dogId, tab) {
  try {
    const url = new URL(window.location.href);
    if (dogId) { url.searchParams.set("dog", dogId); url.searchParams.set("tab", tab); } else { url.searchParams.delete("dog"); url.searchParams.delete("tab"); }
    window.history.replaceState(null, "", url.pathname + (url.search || "") + url.hash);
  } catch (err) { /* a file:// page or a fake window */ }
}

export function closeStudio() {
  const studio = q("studio");
  if (!studio || studio.hidden) return;
  // a paid tool was tapped on a free account: the studio showed the server's own upgrade prompt, so the kennel offers the plan too
  if (studio.querySelector && studio.querySelector("[data-hook='upgrade-prompt']") && !state.upgradeTapped) {
    state.upgradeTapped = true;
    paintUpgrade();
  }
  studio.hidden = true;
  studio.removeAttribute("data-open");
  q("studio-scrim").hidden = true;
  document.body.style.overflow = "";
  state.open = null;
  writeUrl(null);
  if (state.opener && state.opener.focus) state.opener.focus();
}

function bindStudio() {
  q("studio-close").addEventListener("click", closeStudio);
  if (q("studio-remove")) q("studio-remove").addEventListener("click", () => { const dog = studioDog(); if (dog) removeFromKennel(dog); });
  q("studio-scrim").addEventListener("click", closeStudio);
  document.addEventListener("keydown", (evt) => { if (evt.key === "Escape") closeStudio(); });
  window.addEventListener("linehound:dog-saved", async (evt) => {
    const detail = (evt && evt.detail) || {};
    await load({ quiet: true });
    if (!state.data || !detail.id) return;
    if (detail.type === "created") {
      state.open = detail.id;
      state.loaded = {};
      for (const t of document.querySelectorAll("[data-hook='studio-tabs'] [role='tab']")) t.removeAttribute("hidden");
      for (const k of STUDIO_TABS) clearNode(q(`studio-${k}`));
      paintStudioHead();
      if (state.tabs) state.tabs.select("look");
      writeUrl(detail.id, "look");
    } else if (detail.type === "retired") {
      closeStudio();
    } else if (detail.type === "version" && dogById(detail.id)) {
      state.open = detail.id;
      state.loaded = { rules: detail.id };
      for (const k of STUDIO_TABS) clearNode(q(`studio-${k}`));
      paintStudioHead();
      writeUrl(detail.id, "rules");
    }
  });
  window.addEventListener(TOKEN_CHANGED_EVENT, () => { closeStudio(); load(); });
}

async function boot() {
  bindStudio();
  const data = await load();
  const params = new URLSearchParams(window.location.search);
  const want = params.get("dog");
  if (data && state.mode === "mine" && want && dogById(want)) openStudio(want, params.get("tab") || "look");
}

export const booted = boot();
