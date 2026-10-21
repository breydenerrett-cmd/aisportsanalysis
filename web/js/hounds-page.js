/**
 * web/hounds.html: the model leaderboard.
 *
 * WHAT IT SHOWS, TOP TO BOTTOM
 *   - the title, one disclosure bar (paper results, not advice, 21+: static markup, so it is there with
 *     scripts off) and a "Build a model" link;
 *   - the SEASON switcher (Season 2 since Oct 18 | Season 1 | All-time) and one line saying what the window is.
 *     Season 2 is the default; the choice is kept in the URL (?season=) and localStorage. Every figure in the
 *     table is worked out by the server over that window only (GET /hounds?season=); the status column is the
 *     referee's verdict and stays all-time. A model is RANKED with 10 settled bets in the view; below that it
 *     waits in the collapsed "Warming up" group with its record so far, whatever column is sorted;
 *   - filters: whose models (All / My models / House / Builders'), sport, type;
 *   - THE TABLE. One row per RANKED model (10 settled bets in the view): rank, model, type, record (W-L-P), BANKROLL
 *     (the paper account now, from the same $1,000 every model starts with), RETURN (that account's % for the view),
 *     7d and 24h (the same %, from bets settled in those windows), total units (1 unit = $10), bets, typical
 *     price, CLV (the share of bets that beat the close, and the average points), the last ten results as dots,
 *     and a plain-words status. Every column sorts, the balance first. A model with under 20 settled bets is
 *     greyed with a tooltip. A model's drawer (click its row) lists its last ten tickets and links to its page.
 *     Every other model is one collapsed group, "Warming up (N)", at the bottom: its record so far, how many of
 *     the 10 settled bets it has, and its open tickets, never dollars or a return; they are never 28 rows of 0-0
 *     (docs/BANKROLL.md for the definitions);
 *   - LATEST TICKETS: the newest bets any model recorded, as ticket rows (model, game, pick, market, price,
 *     books, when it went on the record against the start, PENDING / WON / LOST / PUSH), paged by the server.
 *     Every number in the table adds up from tickets like these;
 *   - RETIRED MODELS: a small table (name, final record, units, why, when).
 *
 * "Data as of ..." sits above the table, from the API's as_of. Older than six hours, or a saved copy served
 * while the numbers are rebuilt, and a small amber "Updating" note says so. The numbers shown stay the
 * earlier ones, never edited.
 *
 * EVERY SECTION LOADS ON ITS OWN. A failed or missing endpoint puts an honest sentence in that section
 * (describeError) and leaves the others alone. A server still working out the numbers for the first time
 * answers `warming_up: true`; the section says so and asks again. Nothing is invented to fill a gap, and the
 * page never claims an edge or calls units profit.
 */

import { apiGet } from "./api.js";
import {
  h, clearNode, filterHounds, presentCategories, categoryOf, categoryLabel, monogram, fmtPrice,
  fmtWhen, shortDate, isNum, houndHref, describeError, createPoller, NOT_REPORTED, isWarming, retryWhileWarming,
  stopWarmingRetry, WARMING_FALLBACK_TEXT, kennelHref, kennelName,
} from "./hounds-core.js";
import { wlText, unitsOf, causeText } from "./hounds-voice.js";
import {
  COLUMNS, DEFAULT_SORT, NA, betsOf, fmtUnitsPlain, avgPriceOf, clvOf, last10Of, openBetsOf, recordText, streakText,
  bankrollNow, returnPctOf, windowPct, totalUnitsOf, isSmallSample, smallSampleTitle, fmtUsd, fmtPct, bankrollRules,
  basisTagText, RECORDED_TITLE,
  statusOf, typeText, sportLabel, sportsOf, marketsText, presentSports, filterBySport, sortHounds, splitRanked,
  settledOf, onlyTickets, freshness, inQualifyingRound, qualifyingRows, progressText, isMemberDog, isNewDog, sortByBankroll,
} from "./hounds-board.js";
import {
  ALL_SEASON, seasonOptions, chooseSeason, saveSeason, seasonParam, seasonLine, minRanked,
} from "./hounds-season.js";
import { ticketList } from "./hounds-tickets.js";
import { followedIds } from "./hounds-follow.js";
import { dogFace, poseOfHound } from "./dog-avatar.js";
import { kennelLabel } from "./kennel-label.js";

export const STREAM_POLL_MS = 60000;
export const TICKET_PAGE_SIZE = 15;
export const DRAWER_TICKETS = 10;

const state = {
  hounds: [],
  payload: null,
  season: "",              // the season shown: "s2" | "s1" | "all" (URL, then localStorage, then the default)
  seasonMeta: null,        // the payload's `season` block (labels, dates, min_ranked_bets)
  scope: "all",            // all | mine | house | user
  sport: "all",
  category: "all",
  sortKey: DEFAULT_SORT,   // the account balance (the bankroll ruling, docs/BANKROLL.md)
  sortDir: "desc",
  expanded: new Set(),     // hound ids whose drawer is open
  drawers: {},             // id -> { status: "loading" | "ok" | "error", items, error }
  warmOpen: false,
  view: "compact",         // compact (rank, hound, record, bankroll, return) | full (every column), behind the "All stats" button
  stream: { page: 1, pages: 1, total: 0, items: [], payload: null, error: null, loaded: false },
  retired: null,           // null until loaded, then [HoundSummary]
};

const q = (hook) => document.querySelector(`[data-hook='${hook}']`);

function stateBox(kind, text, retry) {
  const box = h("div", { class: `hd-state hd-state--${kind}`, role: kind === "down" ? "alert" : "status",
    "data-hook": "section-state", "data-kind": kind }, [h("p", { text })]);
  if (retry) box.appendChild(h("button", { type: "button", class: "btn btn--ghost hd-retry", text: "Try again",
    on: { click: retry } }));
  return box;
}

/**
 * A restart answers from the last saved copy (`stale: true`, `as_of` = when it was built) while the server
 * works the new numbers out. The page says so in one small line and asks again on the server's cadence
 * until a real answer replaces it.
 */
export function isStale(payload) {
  return !!(payload && typeof payload === "object" && payload.stale === true);
}

function warmingBox(payload) {
  return h("div", { class: "hd-state hd-state--warming", role: "status", "data-hook": "section-state",
    "data-kind": "warming" }, [h("p", { text: (payload && payload.message) || WARMING_FALLBACK_TEXT })]);
}

// ---- filters ---------------------------------------------------------------------------------------

/** The hounds the filters let through (retired ones live in their own table). */
export function visibleHounds(hounds, { scope, sport, category }, followed) {
  let list = (hounds || []).filter((x) => x && x.status !== "retired");
  if (scope === "mine") {
    const mine = followed || followedIds();
    list = list.filter((x) => mine.has(String(x.id)));
  } else if (scope === "house" || scope === "user") {
    list = filterHounds(list, scope);
  }
  list = filterBySport(list, sport);
  if (category && category !== "all") list = list.filter((x) => categoryOf(x) === category);
  return list;
}

function scoped() {
  return visibleHounds(state.hounds, state);
}

function segButtons(bar, entries, current, onPick, dataKey) {
  clearNode(bar);
  for (const [key, text] of entries) {
    bar.appendChild(h("button", { type: "button", class: "hd-seg", "aria-pressed": current === key ? "true" : "false",
      [dataKey]: key, on: { click: () => onPick(key) } }, text));
  }
}

/** The season switcher and the line under it. Picking a season is remembered (URL and localStorage) and reloads the board. */
function renderSeasonBar() {
  const bar = q("hounds-season");
  if (bar) {
    segButtons(bar, seasonOptions(state.seasonMeta).map((o) => [o.id, o.text]), state.season,
      (k) => { pickSeason(k); }, "data-season");
  }
  const line = q("season-line");
  if (line) line.textContent = houndWords(seasonLine(state.seasonMeta, state.season));
}

/** The season line is the shared module's sentence; this page says hound where it says model. */
function houndWords(text) {
  return String(text || "").replace(/\bModels\b/g, "Hounds").replace(/\bmodels\b/g, "hounds").replace(/\bmodel\b/g, "hound");
}

function pickSeason(id) {
  if (id === state.season) return;
  state.season = id;
  saveSeason(id);
  state.expanded = new Set();     // a drawer's tickets belong to the season they were opened in
  state.drawers = {};
  renderSeasonBar();
  loadBoard();
}

function renderFilters() {
  const bar = q("hounds-filter");
  if (!bar) return;
  const live = state.hounds.filter((x) => x.status !== "retired");
  const mine = followedIds();
  const count = (scope) => visibleHounds(live, { scope, sport: "all", category: "all" }, mine).length;
  segButtons(bar, [["all", `All hounds (${count("all")})`], ["mine", `Following (${count("mine")})`],
    ["house", `LINEHOUND kennel (${count("house")})`], ["user", `Members' kennels (${count("user")})`]],
    state.scope, (k) => { state.scope = k; renderAll(); }, "data-filter");

  const sportBar = q("hounds-sports");
  if (sportBar) {
    const base = visibleHounds(live, { scope: state.scope, sport: "all", category: "all" }, mine);
    const sports = presentSports(base);
    if (state.sport !== "all" && !sports.includes(state.sport)) state.sport = "all";
    segButtons(sportBar, [["all", "All sports"]].concat(sports.map((sp) =>
      [sp, `${sportLabel(sp)} (${filterBySport(base, sp).length})`])), state.sport,
    (k) => { state.sport = k; renderAll(); }, "data-sport");
  }

  const typeBar = q("hounds-categories");
  if (typeBar) {
    const base = visibleHounds(live, { scope: state.scope, sport: state.sport, category: "all" }, mine);
    const present = presentCategories(base).concat(base.some((x) => categoryOf(x) === "baseline") ? ["baseline"] : []);
    if (state.category !== "all" && !present.includes(state.category)) state.category = "all";
    segButtons(typeBar, [["all", "All types"]].concat(present.map((c) =>
      [c, `${categoryLabel(c)} (${base.filter((x) => categoryOf(x) === c).length})`])), state.category,
    (k) => { state.category = k; renderAll(); }, "data-category");
  }
}

// ---- the table -------------------------------------------------------------------------------------

function sortArrow(key) {
  if (state.sortKey !== key) return "";
  return state.sortDir === "asc" ? " ▲" : " ▼";
}

function setSort(key) {
  if (state.sortKey === key) {
    state.sortDir = state.sortDir === "asc" ? "desc" : "asc";
  } else {
    state.sortKey = key;
    state.sortDir = (COLUMNS.find((c) => c.key === key) || {}).first || "desc";
  }
  renderTable();
}

function headRow() {
  return h("tr", {}, [
    h("th", { scope: "col", class: "hd-col-rank", text: "#" }),
    ...COLUMNS.map((col) => h("th", { scope: "col", class: `hd-col-${col.key}${col.numeric ? " hd-th--num" : ""}`,
      "aria-sort": state.sortKey === col.key ? (state.sortDir === "asc" ? "ascending" : "descending") : "none",
      title: col.hint || undefined }, [
      h("button", { type: "button", class: "hd-sort", "data-sort": col.key,
        "aria-label": `Sort by ${col.label}`, on: { click: () => setSort(col.key) } },
      `${col.key === "model" ? "Hound" : col.label}${sortArrow(col.key)}`)])),
  ]);
}

function dots(hound) {
  const list = last10Of(hound);
  if (list.length === 0) return h("span", { class: "hd-na", text: NA });
  const word = { W: "win", L: "loss", P: "push" };
  return h("span", { class: "hd-dots", role: "img", "data-hook": "last10",
    "aria-label": `Last ${list.length}, oldest first: ${list.map((x) => word[x]).join(", ")}` },
  list.map((x) => h("span", { class: `hd-dot hd-dot--${x}`, "aria-hidden": "true", title: word[x] })));
}

function clvCell(hound) {
  const clv = clvOf(hound);
  if (!clv) return h("span", { class: "hd-na", "data-hook": "clv", text: NA });
  const parts = [];
  if (clv.beatPct !== null) parts.push(h("strong", { class: "hd-num", text: `${Math.round(clv.beatPct)}%` }), " beat");
  const sub = [clv.mean !== null ? `${clv.mean > 0 ? "+" : clv.mean < 0 ? "-" : ""}${Math.abs(clv.mean).toFixed(1)} pts` : "",
    clv.n ? `n=${clv.n}` : ""].filter(Boolean).join(" · ");
  return h("span", { class: "hd-clv", "data-hook": "clv" }, [
    ...parts, sub ? h("small", { class: "hd-aux", text: sub }) : null]);
}

function statusCell(hound) {
  const st = statusOf(hound);
  return h("span", { class: "hd-statuswrap" }, [
    h("span", { class: `hd-st hd-st--${st.tone}`, "data-hook": "status", "data-status": st.key,
      title: `${st.title} This is the referee's all-time verdict, not limited to the season shown.`, text: st.text }),
    hound.status === "benched" ? h("small", { class: "hd-aux", text: "Idle 7+ days" }) : null,
  ]);
}

function progressPill(hound) {
  const min = minRanked(state.seasonMeta);
  const st = statusOf(hound);
  return h("span", { class: "hd-statuswrap" }, [
    h("span", { class: "hd-pill", "data-hook": "progress", "data-settled": String(settledOf(hound)),
      title: `Needs ${min} settled bets to be ranked. Referee status, all-time: ${st.text}.`, text: progressText(hound, min) })]);
}

function modelCell(hound, rank, open) {
  const mine = followedIds().has(String(hound.id));
  const sports = sportsOf(hound).map(sportLabel).join(", ");
  const where = [sports, marketsText(hound)].filter(Boolean).join(" · ");
  const kennel = kennelLabel(hound);
  return h("td", { class: "hd-col-model" }, [h("div", { class: "hd-modelcell" }, [
    h("button", { type: "button", class: "hd-expand", "data-hook": "expand", "aria-expanded": open ? "true" : "false",
      "aria-label": `${open ? "Hide" : "Show"} ${hound.name || "this hound"}'s latest tickets`,
      on: { click: () => toggleDrawer(hound.id) } }, [h("span", { class: "hd-chev", "aria-hidden": "true" })]),
    h("span", { class: "hd-dogface", "data-hook": "row-dog" }, [dogFace(hound, { size: 44, pose: poseOfHound(hound) })]),
    h("span", { class: "hd-modelid" }, [
      h("a", { class: "hd-modelname", href: houndHref(hound.id), text: hound.name || NOT_REPORTED }),
      mine ? h("span", { class: "hd-tag hd-tag--follow", "data-hook": "row-follow", text: "Following" }) : null,
      // whose kennel it lives in: a member's own, or the one house kennel (owner ruling 2026-10-20)
      h("small", { class: "hd-aux" }, [
        kennel.href ? h("a", { class: `hd-kennellink${kennel.house ? " hd-kennellink--house" : ""}`, href: kennel.href, "data-hook": "row-kennel",
          "data-house": kennel.house ? "1" : "0", text: kennel.text })
          : h("span", { "data-hook": "row-kennel", text: kennel.text }),
        where ? ` · ${where}` : null]),
    ]),
  ])]);
}

/**
 * One table row. `qual` (the qualifying round) numbers nothing, greys the money columns until the ranking bar
 * tooltip and puts a progress pill ("3/10 bets") in the Status column in place of the referee's chip. A ranked
 * model with under 20 settled bets is greyed the same way. A window with no settled bet reads "n/a", not "0.0%".
 */
function moneyCell(hound, cls, hook, text, ret, small, tagged = false) {
  const tone = ret === null ? "none" : ret > 0 ? "up" : ret < 0 ? "down" : "flat";
  // A hound settled at its recorded price (its average-price board is incomplete) says so right under the figure.
  const tag = tagged && basisTagText(hound)
    ? h("small", { class: "hd-basis", "data-hook": "basis-tag", title: RECORDED_TITLE, text: basisTagText(hound) }) : null;
  return small
    ? h("td", { class: `${cls} hd-num hd-roi--small`, "data-hook": hook, "data-small": "true", title: smallSampleTitle(hound) }, [text, tag])
    : h("td", { class: `${cls} hd-num hd-tone--${tone}`, "data-hook": hook }, [text, tag]);
}

function tableRow(hound, rank, qual) {
  const units = totalUnitsOf(hound);
  const small = qual || isSmallSample(hound);
  const ret = returnPctOf(hound);
  const d7 = windowPct(hound, "d7");
  const h24 = windowPct(hound, "h24");
  const bets = betsOf(hound);
  const price = avgPriceOf(hound);
  const open = state.expanded.has(String(hound.id));
  const tone = (n) => (n === null ? "none" : n > 0 ? "up" : n < 0 ? "down" : "flat");
  const streak = streakText(hound);
  const tr = h("tr", { class: qual ? "hd-tr hd-tr--qual" : "hd-tr", "data-hound": hound.id, "data-kind": hound.kind || "", "data-category": categoryOf(hound),
    "data-open": open ? "true" : "false" }, [
    h("td", { class: "hd-col-rank hd-num", text: qual ? "-" : String(rank) }),
    modelCell(hound, rank, open),
    h("td", { class: "hd-col-type" }, [h("span", { class: "hd-typechip", "data-category": categoryOf(hound), text: typeText(hound) })]),
    h("td", { class: "hd-col-record hd-num", "data-hook": "row-record" }, [
      h("strong", { text: recordText(hound) }),
      // the sample beside the record, always (it is the compact view's only count); the streak belongs to "All stats"
      h("small", { class: "hd-aux lb-bets", "data-hook": "row-bets-inline", text: `${bets} ${bets === 1 ? "bet" : "bets"}` }),
      streak ? h("small", { class: "hd-aux lb-streak", text: streak }) : null]),
    moneyCell(hound, "hd-col-bankroll", "row-bankroll", fmtUsd(bankrollNow(hound)), ret, small, true),
    moneyCell(hound, "hd-col-return", "row-return", fmtPct(ret), ret, small),
    moneyCell(hound, "hd-col-d7", "row-d7", fmtPct(d7), d7, small),
    moneyCell(hound, "hd-col-h24", "row-h24", fmtPct(h24), h24, small),
    moneyCell(hound, "hd-col-units", "row-units", fmtUnitsPlain(units), units, small),
    h("td", { class: "hd-col-bets hd-num", "data-hook": "row-bets", text: String(bets) }),
    h("td", { class: "hd-col-price hd-num", "data-hook": "row-price", text: price === null ? NA : fmtPrice(price) }),
    h("td", { class: "hd-col-clv" }, [clvCell(hound)]),
    h("td", { class: "hd-col-last10" }, [dots(hound)]),
    h("td", { class: "hd-col-status" }, [qual ? progressPill(hound) : statusCell(hound)]),
  ]);
  tr.addEventListener("click", (ev) => {
    const target = ev.target;
    if (target && target.closest && target.closest("a, button")) return;
    toggleDrawer(hound.id);
  });
  return tr;
}

function drawerRow(hound) {
  const id = String(hound.id);
  const info = state.drawers[id];
  const box = h("div", { class: "hd-drawer__body", "data-hook": "drawer" });
  if (!info || info.status === "loading") {
    box.appendChild(h("p", { class: "hd-muted", text: "Loading the last tickets..." }));
  } else if (info.status === "error") {
    const e = describeError(info.error, "this hound's tickets");
    box.appendChild(stateBox(e.kind, e.text, () => { loadDrawer(id, true); }));
  } else if (info.items.length === 0) {
    box.appendChild(h("p", { class: "hd-muted", "data-hook": "drawer-empty", text: "No tickets recorded yet." }));
  } else {
    box.appendChild(h("p", { class: "hd-drawer__title", text: `Last ${info.items.length} ${info.items.length === 1 ? "ticket" : "tickets"}` }));
    box.appendChild(ticketList(info.items, { showModel: false, hook: "drawer-tickets" }));
  }
  box.appendChild(h("a", { class: "hd-drawer__more", href: houndHref(hound.id), "data-hook": "drawer-link",
    text: `Full page: rule, every ticket, bankroll chart` }));
  return h("tr", { class: "hd-drawer", "data-hound": id }, [h("td", { colspan: COLUMNS.length + 1 }, [box])]);
}

function toggleDrawer(id) {
  const key = String(id);
  if (state.expanded.has(key)) {
    state.expanded.delete(key);
  } else {
    state.expanded.add(key);
    loadDrawer(key, false);
  }
  renderTable();
}

async function loadDrawer(id, force) {
  const have = state.drawers[id];
  if (have && have.status === "ok" && !force) return;
  state.drawers[id] = { status: "loading", items: [] };
  renderTable();
  try {
    const within = state.season && state.season !== ALL_SEASON ? `&${seasonParam(state.season)}` : "";
    const data = await apiGet(`/hounds/${encodeURIComponent(id)}/bets?page=1&page_size=${DRAWER_TICKETS}&segment=forward${within}`);
    const items = Array.isArray(data && data.items) ? data.items : (Array.isArray(data) ? data : []);
    state.drawers[id] = { status: "ok", items: items.slice(0, DRAWER_TICKETS) };
  } catch (err) {
    state.drawers[id] = { status: "error", items: [], error: err };
  }
  renderTable();
}

/** What a warming hound shows instead of units and ROI: its record so far, how far it is from a rank, its open tickets. */
export function warmingNote(hound, min) {
  const settled = settledOf(hound);
  const open = openBetsOf(hound);
  if (isNewDog(hound)) return "New: no bets yet";
  const parts = [];
  if (settled > 0) parts.push(`${recordText(hound)} so far`);
  parts.push(`${settled} of ${min} settled bets`);
  if (open > 0) parts.push(`${open} open ${open === 1 ? "ticket" : "tickets"}`);
  else if (settled === 0) parts.push(hound.status === "not_started" ? "not started" : hound.status === "benched" ? "idle, no ticket in 7+ days" : "no ticket yet");
  return parts.join(" · ");
}

function warmingBody(warming) {
  const min = minRanked(state.seasonMeta);
  // the Builders' tab always lists every member dog, so its group is never collapsed
  const open = state.warmOpen || state.scope === "user";
  const openTotal = warming.reduce((n, x) => n + openBetsOf(x), 0);
  const label = `Warming up (${warming.length})`;
  const summary = `ranked at ${min} settled bets · ${openTotal} open ${openTotal === 1 ? "ticket" : "tickets"}`;
  const tbody = h("tbody", { class: "hd-warm", "data-hook": "warming-group", "data-open": open ? "true" : "false" }, [
    h("tr", { class: "hd-warm__head" }, [h("td", { colspan: COLUMNS.length + 1 }, [
      h("button", { type: "button", class: "hd-warm__toggle", "data-hook": "warming-toggle",
        "aria-expanded": open ? "true" : "false",
        on: { click: () => { state.warmOpen = !state.warmOpen; renderTable(); } } }, [
        h("span", { class: "hd-chev", "aria-hidden": "true" }),
        h("strong", { text: label }),
        h("span", { class: "hd-aux", text: ` ${summary}` }),
      ])])]),
  ]);
  if (open) {
    for (const hound of warming) {
      const sports = sportsOf(hound).map(sportLabel).join(", ");
      tbody.appendChild(h("tr", { class: "hd-tr hd-tr--warm", "data-hound": hound.id }, [
        h("td", { class: "hd-col-rank hd-num", text: "-" }),
        h("td", { class: "hd-col-model" }, [h("div", { class: "hd-modelcell" }, [
          h("span", { class: "hd-dogface", "data-hook": "row-dog" }, [dogFace(hound, { size: 32 })]),
          h("span", { class: "hd-modelid" }, [
            h("a", { class: "hd-modelname", href: houndHref(hound.id), text: hound.name || NOT_REPORTED }),
            h("small", { class: "hd-aux", text: [sports, marketsText(hound)].filter(Boolean).join(" · ") || NA })])])]),
        h("td", { class: "hd-col-type" }, [h("span", { class: "hd-typechip", "data-category": categoryOf(hound), text: typeText(hound) })]),
        h("td", { colspan: 10, class: "hd-warm__note", "data-hook": "warming-note", text: warmingNote(hound, min) }),
        h("td", { class: "hd-col-status" }, [statusCell(hound)]),
      ]));
    }
  }
  return tbody;
}

/**
 * The qualifying round: every model short of the ranking bar that has a settled bet or an open ticket, as the same
 * table columns (most units, then the better record), each with its progress pill. A model with nothing yet is
 * counted in one line below. Not sortable: it is a progress list, and the ranked table below keeps the sorting.
 */
function qualifyingSection(warming) {
  const min = minRanked(state.seasonMeta);
  const label = (state.seasonMeta && state.seasonMeta.label) || "This season";
  const shown = qualifyingRows(warming);
  const rest = warming.length - shown.length;
  const tbody = h("tbody", { "data-hook": "qualifying-list" });
  for (const hound of shown) {
    tbody.appendChild(tableRow(hound, 0, true));
    if (state.expanded.has(String(hound.id))) tbody.appendChild(drawerRow(hound));
  }
  const table = h("table", { class: "hd-table hd-table--board", "data-hook": "qualifying-table" }, [
    h("caption", { class: "hd-sr-only", text: "Qualifying round: hounds short of the ranking bar, with their progress." }),
    h("thead", {}, [h("tr", {}, [h("th", { scope: "col", class: "hd-col-rank", text: "#" }),
      ...COLUMNS.map((col) => h("th", { scope: "col", class: `hd-col-${col.key}${col.numeric ? " hd-th--num" : ""}`,
        title: col.hint || undefined, text: col.key === "model" ? "Hound" : col.label }))])]),
    tbody]);
  return h("div", { class: "hd-qual", "data-hook": "qualifying" }, [
    h("h3", { class: "hd-qual__title", "data-hook": "qualifying-title",
      text: `${label} qualifying: a hound needs ${min} settled bets to be ranked` }),
    shown.length ? h("div", { class: "hd-tablewrap", tabindex: "0", role: "region", "aria-label": "Qualifying round. Scrolls sideways on a phone." }, [table]) : null,
    rest > 0 ? h("p", { class: "hd-fine", "data-hook": "qualifying-rest",
      text: `${rest} more ${rest === 1 ? "hound has" : "hounds have"} no settled bet yet.` }) : null,
  ]);
}

/**
 * THE LEADERS: up to three models as big dog cards above the table (design system v2). Ranked models first, by bankroll; while fewer
 * than three are ranked, the best of the qualifying round fill in and the heading says so, with each one's progress to the bar.
 * Everything on a card is a figure the table below prints: the account, its return, the record and the bet count.
 */
function podium(active, warming, min) {
  const ranked = sortByBankroll(active).slice(0, 3);
  const filler = ranked.length < 3 ? qualifyingRows(warming).slice(0, 3 - ranked.length) : [];
  const picks = ranked.concat(filler);
  if (!picks.length) return null;
  const title = !filler.length ? "Leading now" : ranked.length ? "Leading, with the best of the qualifying round" : "Leading the qualifying round";
  const sub = filler.length ? `A hound is ranked at ${min} settled bets. These are the closest.` : "Ranked by paper bankroll.";
  return h("section", { class: "lb-podium", "data-hook": "podium", "aria-label": title }, [
    h("div", { class: "lb-podium__head" }, [h("h3", { class: "lb-podium__title", text: title }), h("p", { class: "hd-fine", text: sub })]),
    h("ol", { class: "lb-podium__row" }, picks.map((hound, i) => {
      const isRanked = i < ranked.length;
      const ret = returnPctOf(hound);
      const small = !isRanked || isSmallSample(hound);
      return h("li", { class: `lb-podium__card${i === 0 ? " lb-podium__card--lead" : ""}`, "data-hound": hound.id, style: `--r:${i}` }, [
        h("a", { class: "lb-podium__face", href: houndHref(hound.id), "aria-label": `${hound.name || "Hound"}'s page` }, [
          dogFace(hound, { size: i === 0 ? 108 : 88, pose: poseOfHound(hound) })]),
        h("span", { class: "lb-podium__rank", text: isRanked ? `#${i + 1}` : progressText(hound, min) }),
        h("a", { class: "lb-podium__name", href: houndHref(hound.id), text: hound.name || NOT_REPORTED }),
        h("strong", { class: "lb-podium__bank", "data-count": "1", text: fmtUsd(bankrollNow(hound)) }),
        h("span", { class: `lb-podium__ret lb-podium__ret--${ret === null ? "flat" : ret > 0 ? "up" : ret < 0 ? "down" : "flat"}`,
          title: small ? smallSampleTitle(hound) : "", text: fmtPct(ret) }),
        h("span", { class: "lb-podium__rec", text: `${recordText(hound)} · ${betsOf(hound)} ${betsOf(hound) === 1 ? "bet" : "bets"}` }),
      ]);
    })),
  ]);
}

function renderTable() {
  const host = q("hounds-table");
  if (!host) return;
  clearNode(host);
  const all = scoped();
  // Ranked hounds only are sorted and numbered; the rest wait in "Warming up" whatever column is sorted.
  const { active, warming } = splitRanked(all, minRanked(state.seasonMeta));
  const rows = sortHounds(active, state.sortKey, state.sortDir);
  const count = q("hounds-count");
  if (count) count.textContent = `${all.length} ${all.length === 1 ? "hound" : "hounds"}, ${active.length} ranked`;
  if (all.length === 0) {
    host.appendChild(h("div", { class: "hd-empty", "data-hook": "board-empty" }, [
      h("p", { text: state.hounds.length === 0 ? "No hounds are running yet. The first graded bet puts a hound on this board."
        : state.scope === "mine" ? "You are not following any hounds yet. Open a hound and press Follow."
        : "No hounds match these filters." }),
      h("a", { class: "btn btn--primary", href: "quiz.html", text: "Create your own hound" })]));
    return;
  }
  // Fewer than 3 ranked: the QUALIFYING ROUND leads (expanded, with progress), the ranked table follows. From 3
  // ranked on, the ranked table leads and the models still short of the bar wait in the collapsed "Warming up" group.
  const qualifying = inQualifyingRound(active.length) && warming.length > 0;
  const lead = podium(active, warming, minRanked(state.seasonMeta));
  if (lead) host.appendChild(lead);
  if (qualifying) host.appendChild(qualifyingSection(warming));
  // ROUND 2 (critic, 2026-10-19): with nobody ranked yet the qualifying round IS the leaderboard. An empty "Ranked (0)" table under
  // it said nothing twice, so it is not drawn; one line says why nobody is numbered and the table appears the moment one model is.
  if (qualifying && rows.length === 0) {
    host.appendChild(h("p", { class: "hd-fine hd-qual__none", "data-hook": "no-graded",
      text: `No hound has ${minRanked(state.seasonMeta)} settled bets in this view yet, so none is ranked. The qualifying round above shows who is closest.` }));
    return;
  }
  const thead = h("thead", {}, [headRow()]);
  const tbody = h("tbody", { "data-hook": "hounds-list" });
  rows.forEach((hound, i) => {
    tbody.appendChild(tableRow(hound, i + 1));
    if (state.expanded.has(String(hound.id))) tbody.appendChild(drawerRow(hound));
  });
  const table = h("table", { class: "hd-table hd-table--board", "data-hook": "leaderboard-table" }, [
    h("caption", { class: "hd-sr-only", text: "Leaderboard. Every hound is a paper account that starts with the same $1,000. Click a column to sort." }),
    thead,
    rows.length ? tbody : h("tbody", {}, [h("tr", {}, [h("td", { colspan: COLUMNS.length + 1, class: "hd-muted",
      "data-hook": "no-graded", text: `No hound has ${minRanked(state.seasonMeta)} settled bets in this view yet, so none is ranked.${
        qualifying ? " The qualifying round above shows who is closest."
          : warming.length ? ` ${warming.length} ${warming.length === 1 ? "hound is" : "hounds are"} warming up below.` : ""}` })])]),
  ]);
  if (warming.length && !qualifying) table.appendChild(warmingBody(warming));
  if (qualifying) host.appendChild(h("h3", { class: "hd-qual__ranked", "data-hook": "ranked-title", text: `Ranked (${active.length})` }));
  host.appendChild(h("div", { class: "hd-tablewrap", tabindex: "0", role: "region",
    "aria-label": "Leaderboard. All stats scroll sideways on a phone." }, [table]));
}

// ---- data freshness --------------------------------------------------------------------------------

/** The one short line next to the money: every hound starts from the same paper bankroll (from the server's `bankroll_rules`), and it is paper. */
function renderBankrollLine() {
  const line = q("bankroll-line");
  if (line && state.payload) line.textContent = `Every hound starts with the same ${fmtUsd(bankrollRules(state.payload).start)} paper bankroll. Paper money, not advice.`;
}

/** The compact list (rank, hound, record, bankroll, return) or every column. The choice lives on the panel so CSS draws it. */
function renderViewToggle() {
  const panel = q("hounds-race");
  const btn = q("view-toggle");
  if (panel) panel.setAttribute("data-view", state.view);
  if (btn) {
    btn.setAttribute("aria-pressed", state.view === "full" ? "true" : "false");
    btn.textContent = state.view === "full" ? "Fewer stats" : "All stats";
  }
}

function bindViewToggle() {
  const btn = q("view-toggle");
  if (btn && !btn.getAttribute("data-bound")) {
    btn.setAttribute("data-bound", "1");
    btn.addEventListener("click", () => { state.view = state.view === "full" ? "compact" : "full"; renderViewToggle(); });
  }
  renderViewToggle();
}

function renderMeta() {
  renderBankrollLine();
  const box = q("hounds-asof");
  if (!box) return;
  clearNode(box);
  const fresh = freshness(state.payload);
  if (fresh.label) box.appendChild(h("span", { class: "hd-asof", "data-hook": "data-as-of", text: `Data as of ${fresh.label}` }));
  if (fresh.stale) {
    box.appendChild(h("span", { class: "hd-updating", "data-hook": "updating-note", role: "status",
      text: "Updating: showing the last numbers while new ones load." }));
  }
}

function renderAll() {
  bindViewToggle();
  renderSeasonBar();
  renderFilters();
  renderTable();
  renderMeta();
}

// ---- latest tickets --------------------------------------------------------------------------------

function renderStream() {
  const box = q("hounds-stream");
  if (!box) return;
  clearNode(box);
  const s = state.stream;
  if (s.error && !s.loaded) {
    const e = describeError(s.error, "the ticket feed");
    box.appendChild(stateBox(e.kind, e.text, () => { loadStream(s.page); }));
    return;
  }
  if (!s.loaded) {
    box.appendChild(h("p", { class: "hd-muted", text: "Loading the latest tickets..." }));
    return;
  }
  if (isWarming(s.payload)) {
    box.appendChild(warmingBox(s.payload));
    return;
  }
  const tickets = onlyTickets(s.items);
  if (tickets.length === 0) {
    box.appendChild(h("p", { class: "hd-muted", "data-hook": "stream-empty",
      text: "No tickets recorded yet. When a hound places a paper bet it appears here, before the game." }));
    return;
  }
  box.appendChild(ticketList(tickets, { showModel: true, hook: "stream-list" }));
  box.appendChild(h("div", { class: "hd-pager", "data-hook": "stream-pager" }, [
    h("button", { type: "button", class: "btn btn--ghost", "data-hook": "stream-prev", text: "Newer",
      disabled: s.page <= 1 ? "" : undefined, on: { click: () => { loadStream(s.page - 1); } } }),
    h("span", { class: "hd-fine", "data-hook": "stream-page", role: "status",
      text: `Page ${s.page} of ${s.pages}${isNum(s.total) ? ` (${s.total.toLocaleString("en-US")} tickets)` : ""}` }),
    h("button", { type: "button", class: "btn btn--ghost", "data-hook": "stream-next", text: "Older",
      disabled: s.page >= s.pages ? "" : undefined, on: { click: () => { loadStream(s.page + 1); } } }),
  ]));
  if (s.error) {
    box.appendChild(h("p", { class: "hd-fine", "data-hook": "stream-stale",
      text: "Could not refresh just now; this is the previous list." }));
  }
}

let streamInflight = false;

export async function loadStream(page = state.stream.page) {
  if (streamInflight) return;
  streamInflight = true;
  const s = state.stream;
  try {
    const data = await apiGet(`/hounds/stream?page=${Math.max(1, page)}&page_size=${TICKET_PAGE_SIZE}`);
    s.payload = data;
    s.error = null;
    s.loaded = true;
    if (isWarming(data)) {
      s.items = [];
      retryWhileWarming("stream", () => { loadStream(s.page); }, data);
    } else {
      if (isStale(data)) retryWhileWarming("stream", () => { loadStream(s.page); }, data); else stopWarmingRetry("stream");
      s.items = Array.isArray(data && data.items) ? data.items : [];
      s.page = isNum(data && data.page) ? data.page : page;
      s.pages = isNum(data && data.pages) && data.pages > 0 ? data.pages : 1;
      s.total = isNum(data && data.total) ? data.total : s.items.length;
    }
  } catch (err) {
    s.error = err;
  } finally {
    streamInflight = false;
  }
  renderStream();
}

// ---- retired hounds --------------------------------------------------------------------------------

function renderRetired() {
  const box = q("hounds-graveyard");
  if (!box) return;
  clearNode(box);
  const list = state.retired;
  if (list === null) return;
  if (list.length === 0) {
    box.appendChild(h("p", { class: "hd-muted", "data-hook": "grave-empty", text: "No hound has been retired." }));
    return;
  }
  const rows = list.map((hound) => {
    const rec = hound.record || {};
    const retired = hound.retired || {};
    const now = bankrollNow(hound);
    const ret = returnPctOf(hound);
    return h("tr", { "data-hound": hound.id }, [
      h("td", { class: "hd-col-model" }, [h("div", { class: "hd-modelcell" }, [
        h("span", { class: "hd-dogface hd-dogface--retired", "data-hook": "row-dog" }, [dogFace(hound, { size: 32, pose: "sad" })]),
        h("a", { class: "hd-modelname", href: houndHref(hound.id), text: hound.name || NOT_REPORTED })])]),
      h("td", { class: "hd-num", text: rec.bets > 0 ? `${wlText(rec)} (${rec.bets} bets)` : "no graded bets" }),
      h("td", { class: `hd-num hd-tone--${ret === null ? "none" : ret > 0 ? "up" : ret < 0 ? "down" : "flat"}`,
        "data-hook": "grave-bankroll", text: now === null ? NA : `${fmtUsd(now)} (${fmtPct(ret)})` }),
      h("td", { "data-hook": "grave-cause", text: causeText(retired.cause) }),
      h("td", { class: "hd-num", text: retired.date ? (shortDate(retired.date) || fmtWhen(retired.date)) : NA }),
    ]);
  });
  box.appendChild(h("div", { class: "hd-tablewrap", tabindex: "0", role: "region", "aria-label": "Retired hounds" }, [
    h("table", { class: "hd-table", "data-hook": "grave-list" }, [
      h("caption", { class: "hd-sr-only", text: "Retired hounds and their final records" }),
      h("thead", {}, [h("tr", {}, ["Hound", "Final record", "Final bankroll", "Reason", "Date"].map((t) => h("th", { scope: "col", text: t })))]),
      h("tbody", {}, rows)])]));
}

export async function loadGraveyard() {
  const box = q("hounds-graveyard");
  if (!box) return;
  try {
    const data = await apiGet("/hounds/graveyard");
    if (isWarming(data)) {
      clearNode(box);
      box.appendChild(warmingBox(data));
      retryWhileWarming("graveyard", loadGraveyard, data);
      return;
    }
    if (isStale(data)) retryWhileWarming("graveyard", loadGraveyard, data); else stopWarmingRetry("graveyard");
    state.retired = Array.isArray(data && data.hounds) ? data.hounds : [];
  } catch (err) {
    clearNode(box);
    const e = describeError(err, "the retired hounds");
    box.appendChild(stateBox(e.kind, e.text, () => { loadGraveyard(); }));
    return;
  }
  renderRetired();
}

// ---- boot ------------------------------------------------------------------------------------------

export async function loadBoard() {
  const host = q("hounds-table");
  if (host && state.hounds.length === 0) {
    clearNode(host);
    host.appendChild(h("p", { class: "hd-muted", text: "Loading the leaderboard..." }));
  }
  if (!state.season) state.season = chooseSeason(state.seasonMeta);
  const asked = state.season;
  renderSeasonBar();
  try {
    const data = await apiGet(`/hounds?${seasonParam(asked)}`);
    if (asked !== state.season) return false;        // the reader picked another season while this one loaded
    if (data && typeof data === "object" && data.season && typeof data.season === "object") state.seasonMeta = data.season;
    if (isWarming(data)) {
      state.hounds = [];
      state.payload = null;
      if (host) { clearNode(host); host.appendChild(warmingBox(data)); }
      renderSeasonBar();
      renderFilters();
      retryWhileWarming("board", loadBoard, data);
      return false;
    }
    if (isStale(data)) retryWhileWarming("board", loadBoard, data); else stopWarmingRetry("board");
    state.payload = data || {};
    state.hounds = Array.isArray(data && data.hounds) ? data.hounds : [];
  } catch (err) {
    if (asked !== state.season) return false;
    state.hounds = [];
    state.payload = null;
    if (host) {
      clearNode(host);
      const e = describeError(err, "the leaderboard");
      host.appendChild(stateBox(e.kind, e.text, () => { boot(); }));
    }
    renderFilters();
    return false;
  }
  renderAll();
  return true;
}

export async function boot() {
  await Promise.all([loadBoard(), loadStream(1), loadGraveyard()]);
}

/** `?tab=kennels` (the old Kennels view of this page) goes to the Kennels page; `?scope=house|user|mine` opens a filter. */
function readAddress() {
  try {
    const params = new URLSearchParams(window.location.search || "");
    if (params.get("tab") === "kennels" && window.location && typeof window.location.replace === "function") {
      window.location.replace("kennels.html");
      return false;
    }
    const scope = params.get("scope");
    if (["all", "mine", "house", "user"].includes(scope)) state.scope = scope;
  } catch (err) { /* a fake window: the board opens on everything */ }
  return true;
}

function main() {
  if (!readAddress()) return;
  boot();
  const poller = createPoller({ run: () => { if (state.stream.page === 1) loadStream(1); }, intervalMs: STREAM_POLL_MS });
  poller.start();
  globalThis.__houndsPoller = poller;
}

export const __state = state;

if (typeof document !== "undefined" && typeof window !== "undefined") {
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", main);
  else main();
}
