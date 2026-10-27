/**
 * TONIGHT, the signed-in home (web/tonight.html). Approved plan: docs/HOUND_LOOP_PLAN.md, phase 4, "Guided flow".
 *
 *   NEXT STEP     one primary prompt (Make a hound / Ask why / Backtest 30 days / See a record) and a quieter one: tonight-model.js nextStep.
 *   YOUR TICKETS  the member's open tickets (GET /hounds/{id}/bets?status=open), soonest lock first, times in the viewer's zone.
 *   LAST NIGHT    "Underdog Gus went 2-1 last night" from settled tickets (GET /hounds/{id}/bets?status=graded); a loss carries Ask why / Retune.
 *   CHECKING      the games coming up in the sports the hounds bet (GET /sports/now) and when each locks; "No games tonight in MLB. Add NBA".
 *   TOP HOUNDS    the leaderboard's top hounds' open tickets, each with Open hound and Copy it (the builder's ?from= copy). There is no betting
 *                 flow on this page and none is invented: paper only.
 *
 * Every section loads on its own and fails on its own, in words, with a way to try again. Every empty state names a next step. Nothing
 * here is a price at -200 or worse, a profit claim or a probability: a ticket is shown as the server sent it. Every string goes in
 * through textContent (the `h` helper).
 */

import { apiGet, TOKEN_CHANGED_EVENT } from "./api.js";
import { h, clearNode, houndHref, fmtPrice } from "./hounds-core.js";
import { signedIn, SIGNIN_HREF } from "./dog-common.js";
import { dogFace } from "./dog-avatar.js";
import { pickOf, marketLabel, ticketPrice, ticketState } from "./hounds-board.js";
import { boardModels } from "./landing-board.js";
import { minRanked } from "./hounds-season.js";
import {
  keepTickets, checkingGames, suggestSport, recapRows, recapSentence, nextStep, lockWords, recordLine, kennelTab, recordHref, copyHref,
  memberSports, TONIGHT_ROWS,
} from "./tonight-model.js";

const q = (hook) => document.querySelector(`[data-hook='${hook}']`);
const OPEN_URL = (id) => `/hounds/${encodeURIComponent(id)}/bets?page=1&page_size=8&segment=forward&status=open`;
const GRADED_URL = (id) => `/hounds/${encodeURIComponent(id)}/bets?page=1&page_size=20&segment=forward&status=graded&sort=newest`;
const MAX_HOUNDS_READ = 8;
const TOP_READ = 4;

const state = { dogs: [], open: null, graded: null, nextCtx: null };

const link = (cls, href, text, hook) => h("a", { class: cls, href, "data-hook": hook, text });

/** A section that could not load: what failed, in words, and a button that tries that section again. */
function failed(host, what, retry) {
  clearNode(host).appendChild(h("div", { class: "hd-state hd-state--down", role: "status", "data-hook": "section-state" }, [
    h("p", { text: `Could not load ${what} just now.` }),
    h("button", { type: "button", class: "lh-btn lh-btn--soft", "data-hook": "section-retry", text: "Try again", on: { click: retry } })]));
}

function empty(host, hook, text, actions) {
  clearNode(host).appendChild(h("div", { class: "tn-empty", "data-hook": hook }, [
    h("p", { class: "tn-empty__text", text }),
    h("div", { class: "tn-empty__row" }, actions)]));
}

const settledOf = (d) => (Number.isFinite(d && d.settled) ? d.settled : ((d && d.record && d.record.bets) || 0));

// ---- the ticket row -------------------------------------------------------------------------------------

function ticketRow(dog, t, { actions = null, sub = "" } = {}) {
  const price = ticketPrice(t);
  const when = lockWords(t.start_utc);
  const started = Date.parse(String(t.start_utc || "")) < Date.now();
  return h("li", { class: "tn-tix", "data-hook": "tonight-ticket", "data-ahead": started ? "false" : "true" }, [
    h("span", { class: "tn-tix__dog", "aria-hidden": "true" }, [dogFace(dog, { size: 36 })]),
    h("span", { class: "tn-tix__main" }, [
      h("span", { class: "tn-tix__pick" }, [h("strong", { text: pickOf(t) }), ` ${marketLabel(t.market)}${price === null ? "" : ` ${fmtPrice(price)}`}`]),
      h("span", { class: "tn-tix__game", text: [t.game, dog.name].filter(Boolean).join(" · ") }),
      sub ? h("span", { class: "tn-tix__sub hd-fine", "data-hook": "tonight-ticket-sub", text: sub }) : null]),
    h("span", { class: "tn-tix__lock", text: when ? `${started ? "Started" : "Locks"} ${when}` : "" }),
    actions ? h("span", { class: "tn-tix__actions" }, actions) : null]);
}

// ---- next step ------------------------------------------------------------------------------------------

function paintNext() {
  const host = q("tonight-next");
  if (!host || !state.nextCtx) return;
  const step = nextStep(state.nextCtx);
  clearNode(host).hidden = false;
  host.setAttribute("data-step", step.key);
  host.appendChild(h("p", { class: "tn-next__text", "data-hook": "next-text", text: step.text }));
  host.appendChild(h("div", { class: "tn-next__row" }, [
    link("lh-btn lh-btn--solid lh-btn--lg", step.primary.href, step.primary.text, "next-primary"),
    link("lh-btn lh-btn--soft", step.secondary.href, step.secondary.text, "next-secondary")]));
}

// ---- your hounds tonight --------------------------------------------------------------------------------

async function loadMine() {
  const host = q("tonight-mine");
  const dogs = state.dogs;
  const asked = dogs.filter((d) => Number.isFinite(d.open_bets) && d.open_bets > 0).slice(0, MAX_HOUNDS_READ);
  const lists = await Promise.all(asked.map(async (d) => {
    try { const out = await apiGet(OPEN_URL(d.id)); return [d.id, Array.isArray(out && out.items) ? keepTickets(out.items) : null]; } catch (err) { return [d.id, null]; }
  }));
  const read = lists.filter(([, items]) => items);
  if (asked.length && !read.length) { failed(host, "your tickets", loadMine); return; }
  const rows = [];
  for (const [id, items] of read) {
    const dog = dogs.find((d) => d.id === id);
    for (const t of items) rows.push({ dog, t, start: Date.parse(String(t.start_utc || "")) });
  }
  const now = Date.now();
  rows.sort((a, b) => (((a.start >= now) === (b.start >= now)) ? (a.start || 0) - (b.start || 0) : a.start >= now ? -1 : 1));
  state.open = rows.length;
  state.nextCtx = Object.assign(state.nextCtx || { dogs }, { dogs, openCount: rows.length });
  if (!rows.length) {
    const first = dogs[0];
    empty(host, "tonight-mine-empty", "Nothing open. Your hounds bet when a game fits their rule.", [
      link("lh-btn lh-btn--soft", kennelTab(first.id, "backtest"), `Backtest ${first.name}`, "mine-backtest"),
      link("lh-btn lh-btn--soft", kennelTab(first.id, "rules"), "Edit its rules", "mine-rules")]);
  } else {
    const shown = rows.slice(0, TONIGHT_ROWS);
    clearNode(host).appendChild(h("ol", { class: "tn-list", "data-hook": "tonight-list" }, shown.map((r) => ticketRow(r.dog, r.t))));
    if (rows.length > shown.length) host.appendChild(h("p", { class: "hd-fine", text: `${rows.length - shown.length} more open in My Kennel.` }));
    host.appendChild(h("p", { class: "tn-more" }, [link("tn-textlink", "kennel.html", "Open My Kennel", "mine-kennel")]));
  }
  paintNext();
}

// ---- last night -----------------------------------------------------------------------------------------

async function loadRecap() {
  const host = q("tonight-recap");
  const dogs = state.dogs.filter((d) => settledOf(d) > 0).slice(0, MAX_HOUNDS_READ);
  if (!dogs.length) {
    state.graded = {};
    empty(host, "tonight-recap-empty", "Nothing settled yet. A hound's first graded ticket shows up here.", [
      link("lh-btn lh-btn--soft", "hounds.html", "Find a hound to copy", "recap-find")]);
    return;
  }
  const lists = await Promise.all(dogs.map(async (d) => {
    try { const out = await apiGet(GRADED_URL(d.id)); return [d.id, Array.isArray(out && out.items) ? keepTickets(out.items) : null]; } catch (err) { return [d.id, null]; }
  }));
  if (!lists.some(([, items]) => items)) { failed(host, "last night's results", loadRecap); return; }
  const graded = {};
  for (const [id, items] of lists) if (items) graded[id] = items;
  state.graded = graded;
  const recap = recapRows(state.dogs, graded);
  state.nextCtx = Object.assign(state.nextCtx || { dogs: state.dogs }, { recap });
  if (!recap) {
    const first = state.dogs[0];
    empty(host, "tonight-recap-empty", "Nothing settled in the last few days.", [
      link("lh-btn lh-btn--soft", recordHref(first.id), `See ${first.name}'s record`, "recap-record")]);
  } else {
    clearNode(host).appendChild(h("ul", { class: "tn-recap", "data-hook": "tonight-recap-list" }, recap.rows.map((row) => {
      const lines = [h("span", { class: "tn-recap__line", "data-hook": "recap-line", text: recapSentence(row, recap.word) })];
      const acts = [link("tn-textlink", recordHref(row.dog.id), "Record", "recap-record")];
      if (row.losses > 0) {
        acts.unshift(link("lh-btn lh-btn--soft", kennelTab(row.dog.id, "rules"), "Retune", "recap-retune"));
        acts.unshift(link("lh-btn lh-btn--soft", kennelTab(row.dog.id, "ask"), "Ask why", "recap-ask"));
      }
      return h("li", { class: "tn-recap__row", "data-hook": "recap-row", "data-losses": String(row.losses) }, [
        h("span", { class: "tn-tix__dog", "aria-hidden": "true" }, [dogFace(row.dog, { size: 36 })]),
        h("span", { class: "tn-recap__main" }, lines.concat(row.settled < 3 ? [h("span", { class: "hd-fine", text: `${row.settled} settled ${row.settled === 1 ? "bet" : "bets"}, too few to read anything into.` })] : [])),
        h("span", { class: "tn-recap__acts" }, acts)]);
    })));
  }
  paintNext();
}

// ---- games your hounds are checking ---------------------------------------------------------------------

async function loadChecking() {
  const host = q("tonight-checking");
  let now, season;
  try {
    [now, season] = await Promise.all([apiGet("/sports/now"), apiGet("/sports/season").catch(() => null)]);
  } catch (err) { failed(host, "tonight's games", loadChecking); return; }
  const info = checkingGames(now && now.families, state.dogs);
  if (!info.games.length) {
    const mine = memberSports(state.dogs);
    const names = mine.length ? mine.join(", ") : "your sports";
    const add = suggestSport(season, state.dogs);
    const first = state.dogs[0];
    const laterCode = info.sports.find((c) => info.later[c]);
    const laterText = laterCode ? ` The next ${laterCode} game is ${lockWords(info.later[laterCode])}.` : "";
    const actions = [];
    if (add) actions.push(link("lh-btn lh-btn--solid", kennelTab(first.id, "rules"), `Add ${add.label}`, "checking-add"));
    actions.push(link("lh-btn lh-btn--soft", "live.html", "See what is on in Live", "checking-live"));
    empty(host, "tonight-checking-empty", `No games tonight in ${names}.${laterText}${add ? ` ${add.chip}.` : ""}`, actions);
    return;
  }
  clearNode(host).appendChild(h("ol", { class: "tn-list", "data-hook": "checking-list" }, info.games.slice(0, 8).map((g) =>
    h("li", { class: "tn-game", "data-hook": "checking-game" }, [
      h("span", { class: "tn-game__main" }, [h("strong", { text: g.name }), h("span", { class: "tn-tix__game", text: `${g.label} · ${g.dogs.join(", ")}` })]),
      h("span", { class: "tn-tix__lock", text: `Locks ${lockWords(g.startIso)}` })]))));
  const more = info.games.length - 8;
  host.appendChild(h("p", { class: "hd-fine", text: `${more > 0 ? `${more} more tonight. ` : ""}Your hounds bet only when a game fits their rule; a game here is one they will look at.${info.live ? ` ${info.live} in play now.` : ""}` }));
  host.appendChild(h("p", { class: "tn-more" }, [link("tn-textlink", "live.html", "See every game in Live", "checking-live")]));
}

// ---- top hounds tonight ---------------------------------------------------------------------------------

async function loadTop() {
  const host = q("tonight-top");
  let board;
  try { board = await apiGet("/hounds"); } catch (err) { failed(host, "the top hounds", loadTop); return; }
  if (board && board.warming_up) { failed(host, "the top hounds", loadTop); return; }
  const mine = new Set(state.dogs.map((d) => d.id));
  const picks = boardModels(board && board.hounds, board && board.season).filter((d) => !mine.has(d.id)).slice(0, TOP_READ);
  const lists = await Promise.all(picks.map(async (d) => {
    try { const out = await apiGet(OPEN_URL(d.id)); return [d, Array.isArray(out && out.items) ? keepTickets(out.items) : null]; } catch (err) { return [d, null]; }
  }));
  const rows = [];
  for (const [dog, items] of lists) for (const t of items || []) if (ticketState(t) === "pending") rows.push({ dog, t });
  rows.sort((a, b) => (Date.parse(String(a.t.start_utc || "")) || 0) - (Date.parse(String(b.t.start_utc || "")) || 0));
  if (!picks.length || !rows.length) {
    empty(host, "tonight-top-empty", picks.length ? "The top hounds have no open tickets right now." : "No hound has enough settled bets to rank yet.", [
      link("lh-btn lh-btn--soft", "hounds.html", "Browse the Hounds", "top-browse")]);
    return;
  }
  clearNode(host).appendChild(h("ol", { class: "tn-list", "data-hook": "top-list" }, rows.slice(0, 6).map((r) => ticketRow(r.dog, r.t, {
    sub: recordLine(r.dog),
    // only a member's hound has a spec the server hands out (GET /hounds/{id}/spec); a house hound is opened, not copied
    actions: r.dog.kind === "user"
      ? [link("lh-btn lh-btn--soft", houndHref(r.dog.id), "Open hound", "top-open"), link("lh-btn lh-btn--solid", copyHref(r.dog.id), "Copy it", "top-copy")]
      : [link("lh-btn lh-btn--soft", houndHref(r.dog.id), "Open hound", "top-open")] }))));
  host.appendChild(h("p", { class: "hd-fine", text: "Copy makes a hound of your own with the same rule. A paper record this short says little about what comes next." }));
}

// ---- boot -----------------------------------------------------------------------------------------------

function gate() {
  const box = q("tonight-gate");
  clearNode(box).hidden = false;
  q("tonight-body").hidden = true;
  box.appendChild(h("div", { class: "kn-empty", "data-hook": "tonight-signin" }, [
    h("h2", { text: "Sign in to see tonight" }),
    h("p", { class: "hd-lede", text: "Your hounds' tickets, the games they are checking and last night's results show up here." }),
    h("div", { class: "kn-empty__row" }, [
      link("lh-btn lh-btn--solid", SIGNIN_HREF, "Sign in", "tonight-signin-link"),
      link("lh-btn lh-btn--soft", "hounds.html", "See the Hounds", "tonight-browse")])]));
}

function today() {
  try { return new Date().toLocaleDateString([], { weekday: "long", month: "short", day: "numeric" }); } catch (err) { return ""; }
}

async function boot() {
  if (!signedIn()) { gate(); return; }
  q("tonight-gate").hidden = true;
  q("tonight-body").hidden = false;
  const eyebrow = q("tonight-eyebrow");
  if (eyebrow) eyebrow.textContent = today();
  let data;
  try { data = await apiGet("/hounds/kennels/mine"); } catch (err) {
    if (err && (err.status === 401 || err.status === 403)) { gate(); return; }
    q("tonight-body").hidden = true;
    q("tonight-gate").hidden = false;
    failed(clearNode(q("tonight-gate")), "your hounds", boot);
    return;
  }
  state.dogs = (data && Array.isArray(data.dogs) ? data.dogs : []).filter((d) => d && d.id && !d.retired);
  state.nextCtx = { dogs: state.dogs, openCount: 0, recap: null };
  if (!state.dogs.length) {
    for (const hook of ["tonight-mine-section", "tonight-recap-section", "tonight-checking-section"]) q(hook).hidden = true;
    paintNext();
    await loadTop();
    return;
  }
  paintNext();
  await Promise.all([loadMine(), loadRecap(), loadChecking(), loadTop()]);
  paintNext();
}

window.addEventListener(TOKEN_CHANGED_EVENT, () => { boot(); });
export const booted = boot();
