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
 *   - THE TABLE. One row per RANKED model (10 settled bets in the view): rank, model, type, record (W-L-P), units, ROI, bets,
 *     typical price, CLV (the share of bets that beat the close, and the average points), the last ten results
 *     as dots, and a plain-words status. Every column sorts. Units and ROI are one unit a bet at the average
 *     price. A model's drawer (click its row) lists its last ten tickets and links to its page. Every other model
 *     is one collapsed group, "Warming up (N)", at the bottom: its record so far, how many of the 10 settled bets it
 *     has, and its open tickets, never units or ROI; they are never 28 rows of 0-0;
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
  stopWarmingRetry, WARMING_FALLBACK_TEXT,
} from "./hounds-core.js";
import { wlText, unitsOf, causeText } from "./hounds-voice.js";
import {
  COLUMNS, NA, betsOf, roiOf, fmtRoi, fmtUnitsPlain, avgPriceOf, clvOf, last10Of, openBetsOf, recordText, streakText,
  statusOf, typeText, sportLabel, sportsOf, marketsText, presentSports, filterBySport, sortHounds, splitRanked,
  settledOf, onlyTickets, freshness,
} from "./hounds-board.js";
import {
  ALL_SEASON, seasonOptions, chooseSeason, saveSeason, seasonParam, seasonLine, minRanked,
} from "./hounds-season.js";
import { ticketList } from "./hounds-tickets.js";
import { followedIds } from "./hounds-follow.js";

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
  sortKey: "units",
  sortDir: "desc",
  expanded: new Set(),     // model ids whose drawer is open
  drawers: {},             // id -> { status: "loading" | "ok" | "error", items, error }
  warmOpen: false,
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

/** The models the filters let through (retired ones live in their own table). */
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
  if (line) line.textContent = seasonLine(state.seasonMeta, state.season);
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
  segButtons(bar, [["all", `All models (${count("all")})`], ["mine", `My models (${count("mine")})`],
    ["house", `House (${count("house")})`], ["user", `Builders' (${count("user")})`]],
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
      `${col.label}${sortArrow(col.key)}`)])),
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

function modelCell(hound, rank, open) {
  const mine = followedIds().has(String(hound.id));
  const sports = sportsOf(hound).map(sportLabel).join(", ");
  const where = [sports, marketsText(hound)].filter(Boolean).join(" · ");
  return h("td", { class: "hd-col-model" }, [h("div", { class: "hd-modelcell" }, [
    h("button", { type: "button", class: "hd-expand", "data-hook": "expand", "aria-expanded": open ? "true" : "false",
      "aria-label": `${open ? "Hide" : "Show"} ${hound.name || "this model"}'s latest tickets`,
      on: { click: () => toggleDrawer(hound.id) } }, [h("span", { class: "hd-chev", "aria-hidden": "true" })]),
    monogram(hound.name, { size: 32, category: categoryOf(hound) }),
    h("span", { class: "hd-modelid" }, [
      h("a", { class: "hd-modelname", href: houndHref(hound.id), text: hound.name || NOT_REPORTED }),
      mine ? h("span", { class: "hd-tag hd-tag--follow", "data-hook": "row-follow", text: "Following" }) : null,
      h("small", { class: "hd-aux", text: where || NA }),
    ]),
  ])]);
}

function tableRow(hound, rank) {
  const units = unitsOf(hound);
  const roi = roiOf(hound);
  const bets = betsOf(hound);
  const price = avgPriceOf(hound);
  const open = state.expanded.has(String(hound.id));
  const tone = (n) => (n === null ? "none" : n > 0 ? "up" : n < 0 ? "down" : "flat");
  const streak = streakText(hound);
  const tr = h("tr", { class: "hd-tr", "data-hound": hound.id, "data-kind": hound.kind || "", "data-category": categoryOf(hound),
    "data-open": open ? "true" : "false" }, [
    h("td", { class: "hd-col-rank hd-num", text: String(rank) }),
    modelCell(hound, rank, open),
    h("td", { class: "hd-col-type" }, [h("span", { class: "hd-typechip", "data-category": categoryOf(hound), text: typeText(hound) })]),
    h("td", { class: "hd-col-record hd-num", "data-hook": "row-record" }, [
      h("strong", { text: recordText(hound) }),
      streak ? h("small", { class: "hd-aux", text: streak }) : null]),
    h("td", { class: `hd-col-units hd-num hd-tone--${tone(units)}`, "data-hook": "row-units", text: fmtUnitsPlain(units) }),
    h("td", { class: `hd-col-roi hd-num hd-tone--${tone(roi)}`, "data-hook": "row-roi", text: fmtRoi(roi) }),
    h("td", { class: "hd-col-bets hd-num", "data-hook": "row-bets", text: String(bets) }),
    h("td", { class: "hd-col-price hd-num", "data-hook": "row-price", text: price === null ? NA : fmtPrice(price) }),
    h("td", { class: "hd-col-clv" }, [clvCell(hound)]),
    h("td", { class: "hd-col-last10" }, [dots(hound)]),
    h("td", { class: "hd-col-status" }, [statusCell(hound)]),
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
    const e = describeError(info.error, "this model's tickets");
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

/** What a warming model shows instead of units and ROI: its record so far, how far it is from a rank, its open tickets. */
export function warmingNote(hound, min) {
  const settled = settledOf(hound);
  const open = openBetsOf(hound);
  const parts = [];
  if (settled > 0) parts.push(`${recordText(hound)} so far`);
  parts.push(`${settled} of ${min} settled bets`);
  if (open > 0) parts.push(`${open} open ${open === 1 ? "ticket" : "tickets"}`);
  else if (settled === 0) parts.push(hound.status === "not_started" ? "not started" : hound.status === "benched" ? "idle, no ticket in 7+ days" : "no ticket yet");
  return parts.join(" · ");
}

function warmingBody(warming) {
  const min = minRanked(state.seasonMeta);
  const openTotal = warming.reduce((n, x) => n + openBetsOf(x), 0);
  const label = `Warming up (${warming.length})`;
  const summary = `ranked at ${min} settled bets · ${openTotal} open ${openTotal === 1 ? "ticket" : "tickets"}`;
  const tbody = h("tbody", { class: "hd-warm", "data-hook": "warming-group", "data-open": state.warmOpen ? "true" : "false" }, [
    h("tr", { class: "hd-warm__head" }, [h("td", { colspan: COLUMNS.length + 1 }, [
      h("button", { type: "button", class: "hd-warm__toggle", "data-hook": "warming-toggle",
        "aria-expanded": state.warmOpen ? "true" : "false",
        on: { click: () => { state.warmOpen = !state.warmOpen; renderTable(); } } }, [
        h("span", { class: "hd-chev", "aria-hidden": "true" }),
        h("strong", { text: label }),
        h("span", { class: "hd-aux", text: ` ${summary}` }),
      ])])]),
  ]);
  if (state.warmOpen) {
    for (const hound of warming) {
      const sports = sportsOf(hound).map(sportLabel).join(", ");
      tbody.appendChild(h("tr", { class: "hd-tr hd-tr--warm", "data-hound": hound.id }, [
        h("td", { class: "hd-col-rank hd-num", text: "-" }),
        h("td", { class: "hd-col-model" }, [h("div", { class: "hd-modelcell" }, [
          monogram(hound.name, { size: 28, category: categoryOf(hound) }),
          h("span", { class: "hd-modelid" }, [
            h("a", { class: "hd-modelname", href: houndHref(hound.id), text: hound.name || NOT_REPORTED }),
            h("small", { class: "hd-aux", text: [sports, marketsText(hound)].filter(Boolean).join(" · ") || NA })])])]),
        h("td", { class: "hd-col-type" }, [h("span", { class: "hd-typechip", "data-category": categoryOf(hound), text: typeText(hound) })]),
        h("td", { colspan: 7, class: "hd-warm__note", "data-hook": "warming-note", text: warmingNote(hound, min) }),
        h("td", { class: "hd-col-status" }, [statusCell(hound)]),
      ]));
    }
  }
  return tbody;
}

function renderTable() {
  const host = q("hounds-table");
  if (!host) return;
  clearNode(host);
  const all = scoped();
  // Ranked models only are sorted and numbered; the rest wait in "Warming up" whatever column is sorted.
  const { active, warming } = splitRanked(all, minRanked(state.seasonMeta));
  const rows = sortHounds(active, state.sortKey, state.sortDir);
  const count = q("hounds-count");
  if (count) count.textContent = `${all.length} ${all.length === 1 ? "model" : "models"}, ${active.length} ranked`;
  if (all.length === 0) {
    host.appendChild(h("div", { class: "hd-empty", "data-hook": "board-empty" }, [
      h("p", { text: state.hounds.length === 0 ? "No models are running yet. The first graded bet puts a model on this table."
        : state.scope === "mine" ? "You are not following any models yet. Open a model and press Follow."
        : "No models match these filters." }),
      h("a", { class: "btn btn--primary", href: "build-a-hound.html", text: "Build a model" })]));
    return;
  }
  const thead = h("thead", {}, [headRow()]);
  const tbody = h("tbody", { "data-hook": "hounds-list" });
  rows.forEach((hound, i) => {
    tbody.appendChild(tableRow(hound, i + 1));
    if (state.expanded.has(String(hound.id))) tbody.appendChild(drawerRow(hound));
  });
  const table = h("table", { class: "hd-table hd-table--board", "data-hook": "leaderboard-table" }, [
    h("caption", { class: "hd-sr-only", text: "Model leaderboard. One unit a bet, at the average price. Click a column to sort." }),
    thead,
    rows.length ? tbody : h("tbody", {}, [h("tr", {}, [h("td", { colspan: COLUMNS.length + 1, class: "hd-muted",
      "data-hook": "no-graded", text: `No model has ${minRanked(state.seasonMeta)} settled bets in this view yet, so none is ranked.${
        warming.length ? ` ${warming.length} ${warming.length === 1 ? "model is" : "models are"} warming up below.` : ""}` })])]),
  ]);
  if (warming.length) table.appendChild(warmingBody(warming));
  host.appendChild(h("div", { class: "hd-tablewrap", tabindex: "0", role: "region",
    "aria-label": "Model leaderboard. Scrolls sideways on a phone." }, [table]));
}

// ---- data freshness --------------------------------------------------------------------------------

function renderMeta() {
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
      text: "No tickets recorded yet. When a model places a paper bet it appears here, before the game." }));
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

// ---- retired models --------------------------------------------------------------------------------

function renderRetired() {
  const box = q("hounds-graveyard");
  if (!box) return;
  clearNode(box);
  const list = state.retired;
  if (list === null) return;
  if (list.length === 0) {
    box.appendChild(h("p", { class: "hd-muted", "data-hook": "grave-empty", text: "No model has been retired." }));
    return;
  }
  const rows = list.map((hound) => {
    const rec = hound.record || {};
    const retired = hound.retired || {};
    const units = unitsOf(hound);
    return h("tr", { "data-hound": hound.id }, [
      h("td", { class: "hd-col-model" }, [h("div", { class: "hd-modelcell" }, [
        monogram(hound.name, { size: 28, category: categoryOf(hound), muted: true }),
        h("a", { class: "hd-modelname", href: houndHref(hound.id), text: hound.name || NOT_REPORTED })])]),
      h("td", { class: "hd-num", text: rec.bets > 0 ? `${wlText(rec)} (${rec.bets} bets)` : "no graded bets" }),
      h("td", { class: `hd-num hd-tone--${units === null ? "none" : units > 0 ? "up" : units < 0 ? "down" : "flat"}`,
        text: units === null ? NA : fmtUnitsPlain(units) }),
      h("td", { "data-hook": "grave-cause", text: causeText(retired.cause) }),
      h("td", { class: "hd-num", text: retired.date ? (shortDate(retired.date) || fmtWhen(retired.date)) : NA }),
    ]);
  });
  box.appendChild(h("div", { class: "hd-tablewrap", tabindex: "0", role: "region", "aria-label": "Retired models" }, [
    h("table", { class: "hd-table", "data-hook": "grave-list" }, [
      h("caption", { class: "hd-sr-only", text: "Retired models and their final records" }),
      h("thead", {}, [h("tr", {}, ["Model", "Final record", "Units", "Reason", "Date"].map((t) => h("th", { scope: "col", text: t })))]),
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
    const e = describeError(err, "the retired models");
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

function main() {
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
