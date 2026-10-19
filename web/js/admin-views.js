/**
 * ADMIN VIEWS -- what each tab of web/admin.html shows, as plain functions of the data the admin
 * API sent. Two kinds live here:
 *
 *   * pure computations (kpis, dailySeries, attentionItems, peopleRows, filterPeople,
 *     storeCards, funnelBars): numbers in, numbers out, no DOM; tests/test_admin_dashboard.py
 *     drives them through the real page;
 *   * renderers (renderOverview, renderPeople, renderFunnel, renderHealth, renderSupport) that
 *     draw them with el()/svgEl().
 *
 * HONESTY RULES, same as the rest of the product: a number the server did not send is drawn as an
 * em dash, never as 0 or a guess; a small count says it is small; a health threshold this page
 * invented says it is this page's and not the server's.
 */

import { el, clear } from "./dom.js";
import {
  svgEl, chip, button, fmtInt, parseTime, dayLabel, dateLabel, momentLabel, agoLabel, untilLabel,
  spanLabel,
} from "./admin-ui.js";

const DAY_MS = 86400000;
const HOUR_MS = 3600000;

/** Visits and signups come from analytics events (src/appstate/events.py). */
const VISIT_KINDS = ["landing_view", "public_page_view"];
const SIGNUP_KINDS = ["account_created"];

export const EXPIRING_WINDOW_HOURS = 48;

// ---------------------------------------------------------------------------
// Computations
// ---------------------------------------------------------------------------

/** The UTC calendar day of an epoch-ms instant, "YYYY-MM-DD". */
function utcDay(ms) {
  return new Date(ms).toISOString().slice(0, 10);
}

/** The last `days` UTC days ending today as [{day, visits, signups}], oldest first. A day the
 * server sent nothing for is a real 0 (the server only lists days that had events). */
export function dailySeries(overview, now, days = 14) {
  const byDay = ((overview || {}).events || {}).daily_counts_by_kind || {};
  const out = [];
  for (let i = days - 1; i >= 0; i--) {
    const day = utcDay(now - i * DAY_MS);
    const counts = byDay[day] || {};
    const sum = (kinds) => kinds.reduce((total, kind) => total + (Number(counts[kind]) || 0), 0);
    out.push({ day, visits: sum(VISIT_KINDS), signups: sum(SIGNUP_KINDS) });
  }
  return out;
}

function sumLast(series, key, days) {
  return series.slice(-days).reduce((total, point) => total + point[key], 0);
}

/** testers whose access is running now. */
export function activeTesters(testers, now) {
  return ((testers || {}).testers || []).filter((t) => parseTime(t.expires_at) > now);
}

/** The KPI cards. A source that failed to load gives `value: null` (drawn as "—"). */
export function kpis(data, now) {
  const overview = data.overview;
  const users = overview ? overview.users || {} : null;
  const series = overview ? dailySeries(overview, now) : null;
  const testers = data.testers;
  const comps = data.comps;
  const revenue = data.revenue;
  const trialing = revenue && typeof revenue.trialing === "number" ? revenue.trialing : null;
  return [
    { key: "total", label: "Total users", value: users ? users.total : null,
      sub: users ? `${fmtInt((users.by_status || {}).active || 0)} active` : "" },
    { key: "waitlist", label: "Waitlist", value: users ? (users.by_status || {}).waitlisted || 0 : null,
      sub: "waiting for access", tone: users && ((users.by_status || {}).waitlisted || 0) > 0 ? "warn" : "" },
    { key: "testers", label: "Testers active",
      value: testers ? (typeof testers.limit === "number" ? `${activeTesters(testers, now).length}/${testers.limit}` : activeTesters(testers, now).length) : null,
      sub: testers ? `${fmtInt(testers.granted)} granted so far` : "" },
    { key: "free", label: "Free members", value: comps ? comps.active : null, sub: "no card, until revoked" },
    { key: "paying", label: "Paying", value: revenue ? revenue.paying : null,
      sub: revenue ? (trialing === null ? "" : `${fmtInt(trialing)} trialing`) : "payments data unavailable" },
    { key: "signups", label: "Signups, 7 days", value: series ? sumLast(series, "signups", 7) : null,
      sub: "accounts created" },
    { key: "visits", label: "Visits, 7 days", value: series ? sumLast(series, "visits", 7) : null,
      sub: "landing and public pages" },
  ];
}

/** Which tone a store check belongs to, by the age of its newest row. These thresholds are this
 * page's, not the server's: the server reports the age and the status, not a verdict. */
export const HEALTH_GREEN_HOURS = 24;
export const HEALTH_AMBER_HOURS = 72;

export function storeTone(check) {
  const status = check && check.status;
  if (status === "unreadable") return "bad";
  if (status !== "ok") return "warn";
  const age = check.newest_row_age_seconds;
  if (typeof age !== "number") return "warn";
  if (age <= HEALTH_GREEN_HOURS * 3600) return "ok";
  if (age <= HEALTH_AMBER_HOURS * 3600) return "warn";
  return "bad";
}

const STORE_WORD = {
  ok: { ok: "Fresh", warn: "Aging", bad: "Stale" },
  missing: "Missing", empty: "Empty", archived_only: "Archived only", unreadable: "Unreadable",
};

export function storeWord(check) {
  const status = check && check.status;
  if (status === "ok") return STORE_WORD.ok[storeTone(check)];
  return STORE_WORD[status] || String(status || "Unknown");
}

/** "2h 14m" for the age of a store's newest row; an em dash when there is none. */
export function ageLabel(seconds) {
  return typeof seconds === "number" && Number.isFinite(seconds) ? spanLabel(seconds * 1000) : "—";
}

const STORE_TITLE = {
  odds_multibook: "Odds, multi-book",
  odds_snapshots: "Odds snapshots",
  f5_close: "First-five closing lines",
  prop_listing: "Prop listings",
  probables_watch: "Probable pitchers",
  transactions_watch: "Transactions",
  lineups_watch: "Lineups",
};

function titleOf(name) {
  return STORE_TITLE[name] || String(name).replace(/_/g, " ");
}

/** Every health card, grouped. Each: {key, title, tone, word, big, lines[], reason}. */
export function storeCards(overview) {
  const health = (overview || {}).store_health;
  if (!health) return null;
  const groups = [];
  const appCards = [];
  const db = health.app_db || {};
  appCards.push({ key: "app_db", title: "App database", tone: db.reachable ? "ok" : "bad",
    word: db.reachable ? "Reachable" : "Unreachable", big: db.reachable ? "OK" : "DOWN",
    lines: [], reason: db.reason || null });
  const checkout = health.checkout;
  if (checkout) {
    const tone = checkout.status === "ok" ? "ok" : (checkout.status === "broken" ? "bad" : "warn");
    const word = { ok: "Ready", off: "Billing off", broken: "Broken", unknown: "Unknown" }[checkout.status]
      || String(checkout.status);
    appCards.push({ key: "checkout", title: "Checkout", tone, word, big: word,
      lines: [checkout.provider ? `Provider: ${checkout.provider}` : "",
              checkout.mode ? `Mode: ${checkout.mode}` : ""].filter(Boolean),
      reason: checkout.reason || null });
  }
  appCards.push({ key: "version", title: "Version", tone: "mute", word: "Running", big: String(overview.version || "—"),
    lines: [health.generated_at ? `Checked ${momentLabel(health.generated_at)}` : ""].filter(Boolean),
    reason: null });
  groups.push({ key: "app", title: "App", cards: appCards });

  const fromStores = (entries) => Object.entries(entries || {}).map(([name, check]) => ({
    key: name, title: titleOf(name), tone: storeTone(check), word: storeWord(check),
    big: ageLabel(check.newest_row_age_seconds),
    lines: [typeof check.rows === "number" ? `${fmtInt(check.rows)} rows` : "",
            check.newest_row_utc ? `Newest ${momentLabel(check.newest_row_utc)}` : ""].filter(Boolean),
    reason: check.reason || null,
  }));
  groups.push({ key: "odds", title: "Odds store", cards: fromStores(health.odds) });
  groups.push({ key: "forward", title: "Forward captures", cards: fromStores(health.forward_captures) });

  const fresh = health.data_freshness;
  if (fresh && !fresh.error) {
    groups.push({ key: "pages", title: "Data behind the pages", cards: Object.entries(fresh.stores || {}).map(([name, s]) => ({
      key: `fresh_${name}`, title: titleOf(name), tone: s.stale ? "bad" : (s.lag_days > 0 ? "warn" : "ok"),
      word: s.stale ? "Stale" : (s.lag_days > 0 ? "Behind" : "Current"),
      big: s.through || "—",
      lines: [typeof s.lag_days === "number" ? `${s.lag_days} day${s.lag_days === 1 ? "" : "s"} behind` : ""].filter(Boolean),
      reason: s.reason || null,
    })) });
  } else if (fresh && fresh.error) {
    groups.push({ key: "pages", title: "Data behind the pages", cards: [], error: fresh.error });
  }
  return { status: health.status, reasons: health.reasons || [], generatedAt: health.generated_at, groups };
}

/** One row per user, with the tester and free-member facts joined in by user id. */
export function peopleRows(data, now) {
  const testerById = new Map();
  for (const t of (data.testers || {}).testers || []) testerById.set(t.user_id, t);
  const compById = new Map();
  for (const c of (data.comps || {}).comps || []) compById.set(c.user_id, c);
  const rows = [];
  for (const u of (data.users || {}).users || []) {
    const t = testerById.get(u.id) || null;
    const c = compById.get(u.id) || null;
    const expiresAt = u.tester_expires_at || (t && t.expires_at) || null;
    const testerRunning = Boolean(u.tester) && parseTime(expiresAt) > now;
    const paying = u.plan === "beta" && u.status === "active" && !u.comp;
    let state;
    if (u.status === "suspended") state = { word: "Suspended", tone: "bad", group: "suspended" };
    else if (u.comp) state = { word: "Free member", tone: "info", group: "free" };
    else if (u.tester && testerRunning) state = { word: "Tester", tone: "info", group: "testers" };
    else if (u.tester) state = { word: "Tester ended", tone: "warn", group: "testers" };
    else if (paying) state = { word: "Paying", tone: "ok", group: "paying" };
    else if (u.status === "waitlisted") state = { word: "Waitlist", tone: "warn", group: "waitlist" };
    else if (u.status === "pending_payment") state = { word: "Pending payment", tone: "warn", group: "other" };
    else if (u.status === "invited") state = { word: "Invited", tone: "mute", group: "other" };
    else if (u.comp_revoked) state = { word: "Free access ended", tone: "mute", group: "other" };
    else state = { word: u.status === "active" ? "Active" : String(u.status), tone: "mute", group: "other" };
    rows.push({
      id: u.id, email: String(u.email || ""), status: u.status, plan: u.plan, createdAt: u.created_at,
      tester: Boolean(u.tester), testerRunning, testerExpiresAt: expiresAt,
      lastSeen: (t && t.last_active_at) || null,
      comp: Boolean(u.comp), compRevoked: Boolean(u.comp_revoked), paying,
      state, compReason: c && c.reason ? c.reason : null,
    });
  }
  rows.sort((a, b) => (parseTime(b.createdAt) || 0) - (parseTime(a.createdAt) || 0) || b.id - a.id);
  return rows;
}

export const PEOPLE_GROUPS = [
  { key: "all", label: "All" },
  { key: "waitlist", label: "Waitlist" },
  { key: "testers", label: "Testers" },
  { key: "free", label: "Free members" },
  { key: "paying", label: "Paying" },
  { key: "suspended", label: "Suspended" },
];

export function filterPeople(rows, query, group) {
  const needle = String(query || "").trim().toLowerCase();
  return rows.filter((row) => {
    if (group && group !== "all" && row.state.group !== group) return false;
    if (needle && !(row.email.toLowerCase().includes(needle) || String(row.id) === needle)) return false;
    return true;
  });
}

/** The menu a row offers. `disabled` ones are shown greyed with a `note` saying why. */
export function rowActions(row, { passwordReset = false } = {}) {
  const items = [];
  const suspended = row.status === "suspended";
  if (!row.comp && !suspended && !row.paying) {
    items.push({ key: "approve", label: "Approve as free member" });
  }
  if (!row.tester && !row.comp && !suspended && !row.paying) {
    items.push({ key: "grant", label: "Grant 7-day tester" });
  }
  if (row.tester && !suspended) items.push({ key: "extend", label: "Extend tester (reason)" });
  if ((row.tester || row.comp || row.status === "active") && !suspended) {
    items.push({ key: "reissue", label: "Re-issue login (reason)" });
  }
  if (passwordReset) items.push({ key: "password", label: "Reset password (reason)" });
  else items.push({ key: "password", label: "Reset password", disabled: true,
    note: "Not available yet: needs the password-login release." });
  if (row.comp) items.push({ key: "revoke", label: "Revoke free member (reason)", danger: true });
  return items;
}

/** The "Needs your attention" list, most urgent first. */
export function attentionItems(data, now) {
  const items = [];
  const rows = data.users ? peopleRows(data, now) : [];
  const waiting = rows.filter((r) => r.status === "waitlisted" && !r.comp && !r.tester);
  for (const row of waiting.slice(0, 5)) {
    items.push({ key: `approve-${row.id}`, tone: "warn", kind: "approve", row,
      title: row.email, detail: `On the waitlist, joined ${dateLabel(row.createdAt)}` });
  }
  if (waiting.length > 5) {
    items.push({ key: "approve-more", tone: "warn", kind: "go", route: "people", group: "waitlist",
      title: `${waiting.length - 5} more on the waitlist`, detail: "Open the waitlist in People", cta: "View waitlist" });
  }
  const limit = now + EXPIRING_WINDOW_HOURS * HOUR_MS;
  const expiring = rows.filter((r) => r.tester && r.testerRunning && parseTime(r.testerExpiresAt) <= limit);
  for (const row of expiring) {
    items.push({ key: `expiring-${row.id}`, tone: "warn", kind: "extend", row,
      title: row.email, detail: `Tester access ends ${untilLabel(row.testerExpiresAt, now)}` });
  }
  const cards = storeCards(data.overview);
  if (cards) {
    const flat = cards.groups.flatMap((g) => g.cards.map((c) => ({ ...c, group: g.title })));
    const bad = flat.filter((c) => c.tone === "bad");
    for (const card of bad) {
      items.push({ key: `health-${card.key}`, tone: "bad", kind: "go", route: "health", cta: "Open Health",
        title: `${card.title}: ${card.word}`, detail: card.reason || `${card.group}, newest row ${card.big} old` });
    }
    const aging = flat.filter((c) => c.tone === "warn" && c.word !== "Running");
    if (aging.length) {
      items.push({ key: "health-aging", tone: "warn", kind: "go", route: "health", cta: "Open Health",
        title: `${aging.length} data store${aging.length === 1 ? " is" : "s are"} aging, empty or behind`,
        detail: aging.slice(0, 3).map((c) => c.title).join(", ") + (aging.length > 3 ? ", ..." : "") });
    }
  }
  const open = ((data.support || {}).messages || []).filter((m) => m.status === "open");
  if (open.length) {
    items.push({ key: "support-open", tone: "warn", kind: "go", route: "support", cta: "Open Support",
      title: `${open.length} open support message${open.length === 1 ? "" : "s"}`,
      detail: `Latest: ${open[0].subject}` });
  }
  const order = { bad: 0, warn: 1 };
  return items.map((item, index) => ({ item, index }))
    .sort((a, b) => (order[a.item.tone] ?? 2) - (order[b.item.tone] ?? 2) || a.index - b.index)
    .map((pair) => pair.item);
}

const STEP_LABEL = {
  landing_view: "Landing page views",
  cta_click: "Button clicks",
  free_bet_check: "Free bet checks",
  signup_started: "Signup form reached",
  account_created: "Accounts created",
  checkout_started: "Checkouts started",
  checkout_completed: "Checkouts completed",
  invite_redeemed: "Invites redeemed",
  bet_check_run: "Bet checks run",
  bet_saved: "Bets saved",
};

export function stepLabel(kind) {
  return STEP_LABEL[kind] || String(kind).replace(/_/g, " ");
}

/** Funnel bars: width is the step's count against the biggest step. */
export function funnelBars(funnel) {
  const steps = (funnel || {}).steps || [];
  const max = Math.max(1, ...steps.map((s) => Number(s.count) || 0));
  return steps.map((s, i) => {
    const from = s.conversion_from || (i > 0 ? steps[i - 1].kind : null);
    const previous = i > 0 ? steps[i - 1].kind : null;
    return {
      kind: s.kind, label: stepLabel(s.kind), count: Number(s.count) || 0,
      width: Math.round(1000 * (Number(s.count) || 0) / max) / 10,
      pct: s.conversion_pct_from_previous,
      from: from && from !== previous ? stepLabel(from) : null,
      hasBase: s.conversion_pct_from_previous !== null && s.conversion_pct_from_previous !== undefined,
    };
  });
}

// ---------------------------------------------------------------------------
// Rendering
// ---------------------------------------------------------------------------

function panelHead(title, right) {
  const head = el("div", { class: "adm-panel__head" }, [el("h3", { class: "adm-panel__title", text: title })]);
  if (right) head.appendChild(right);
  return head;
}

function loadFailed(label, err) {
  const status = err && err.status != null ? ` (${err.status})` : "";
  return el("p", { class: "adm-note adm-note--bad", "data-hook": "admin-load-failed",
    text: `${label} could not be loaded${status}. Use Refresh to try again.` });
}

function kpiCard(k) {
  const card = el("div", { class: `adm-kpi${k.tone ? " adm-kpi--" + k.tone : ""}`, "data-hook": "admin-kpi", "data-kpi": k.key });
  card.appendChild(el("div", { class: "adm-kpi__label", text: k.label }));
  const value = k.value === null || k.value === undefined ? "—"
    : (typeof k.value === "number" ? fmtInt(k.value) : String(k.value));
  card.appendChild(el("div", { class: "adm-kpi__value", "data-hook": "admin-kpi-value", text: value }));
  card.appendChild(el("div", { class: "adm-kpi__sub", text: k.sub || "" }));
  return card;
}

/** A 14-bar chart, inline SVG, its own scale. Every bar has a <title> so a hover or a screen
 * reader gets the day and the exact count. */
export function barChart(series, key, title) {
  const W = 320, H = 96, padL = 4, padB = 18, padT = 14;
  const max = Math.max(1, ...series.map((p) => p[key]));
  const n = series.length;
  const slot = (W - padL * 2) / n;
  const bar = slot * 0.66;
  const total = series.reduce((sum, p) => sum + p[key], 0);
  const svg = svgEl("svg", { viewBox: `0 0 ${W} ${H}`, class: "adm-chart__svg", role: "img",
    "aria-label": `${title}, last ${n} days: ${total} in total`, "data-hook": "admin-chart-svg", "data-chart": key });
  svg.appendChild(svgEl("line", { x1: padL, x2: W - padL, y1: H - padB, y2: H - padB, class: "adm-chart__axis" }));
  series.forEach((p, i) => {
    const h = p[key] === 0 ? 0 : Math.max(2, (H - padB - padT) * p[key] / max);
    const x = padL + i * slot + (slot - bar) / 2;
    const rect = svgEl("rect", { x: x.toFixed(1), y: (H - padB - h).toFixed(1), width: bar.toFixed(1),
      height: h.toFixed(1), class: `adm-chart__bar adm-chart__bar--${key}`, "data-hook": "admin-chart-bar",
      "data-day": p.day, "data-value": String(p[key]) });
    rect.appendChild(svgEl("title", {}, `${dayLabel(p.day)}: ${p[key]}`));
    svg.appendChild(rect);
  });
  svg.appendChild(svgEl("text", { x: padL, y: H - 4, class: "adm-chart__tick" }, dayLabel(series[0].day)));
  svg.appendChild(svgEl("text", { x: W - padL, y: H - 4, class: "adm-chart__tick", "text-anchor": "end" },
    dayLabel(series[n - 1].day)));
  svg.appendChild(svgEl("text", { x: padL, y: 10, class: "adm-chart__tick" }, `peak ${max === 1 && total === 0 ? 0 : max}`));
  return svg;
}

function attentionRow(item, ctx) {
  const row = el("li", { class: `adm-attn adm-attn--${item.tone}`, "data-hook": "admin-attention-item",
    "data-kind": item.kind, "data-key": item.key });
  row.appendChild(el("span", { class: "adm-attn__dot", "aria-hidden": "true" }));
  const text = el("div", { class: "adm-attn__text" }, [
    el("div", { class: "adm-attn__title", text: item.title }),
    el("div", { class: "adm-attn__detail", text: item.detail }),
  ]);
  row.appendChild(text);
  const actions = el("div", { class: "adm-attn__actions" });
  if (item.kind === "approve") {
    actions.appendChild(button("Approve as free member", { variant: "ghost", hook: "admin-attention-approve",
      onClick: () => ctx.runAction("approve", item.row) }));
    actions.appendChild(button("Grant 7-day tester", { variant: "ghost", hook: "admin-attention-grant",
      onClick: () => ctx.runAction("grant", item.row) }));
  } else if (item.kind === "extend") {
    actions.appendChild(button("Extend", { variant: "ghost", hook: "admin-attention-extend",
      onClick: () => ctx.runAction("extend", item.row) }));
  } else {
    actions.appendChild(button(item.cta || "Open", { variant: "ghost", hook: "admin-attention-go",
      onClick: () => ctx.go(item.route, item.group) }));
  }
  row.appendChild(actions);
  return row;
}

export function renderOverview(host, data, ctx) {
  clear(host);
  const now = ctx.now();
  const grid = el("div", { class: "adm-kpis", "data-hook": "admin-kpis" });
  for (const k of kpis(data, now)) grid.appendChild(kpiCard(k));
  host.appendChild(grid);

  const cols = el("div", { class: "adm-cols" });

  const attn = el("section", { class: "adm-panel adm-panel--attn", "data-hook": "admin-attention" });
  attn.appendChild(panelHead("Needs your attention"));
  const items = attentionItems(data, now);
  if (items.length === 0) {
    attn.appendChild(el("p", { class: "adm-empty", "data-hook": "admin-attention-empty",
      text: "Nothing needs you right now: nobody is waiting, no tester access ends in the next 48 hours, all data is current and no support message is open." }));
  } else {
    const list = el("ul", { class: "adm-attn-list" });
    for (const item of items) list.appendChild(attentionRow(item, ctx));
    attn.appendChild(list);
  }
  cols.appendChild(attn);

  const chartPanel = el("section", { class: "adm-panel adm-panel--charts", "data-hook": "admin-charts" });
  chartPanel.appendChild(panelHead("Last 14 days"));
  if (data.overview) {
    const series = dailySeries(data.overview, now);
    const visitsTotal = series.reduce((s, p) => s + p.visits, 0);
    const signupsTotal = series.reduce((s, p) => s + p.signups, 0);
    for (const [key, label, total] of [["visits", "Visits", visitsTotal], ["signups", "Signups", signupsTotal]]) {
      const fig = el("figure", { class: "adm-chart", "data-hook": "admin-chart" });
      fig.appendChild(el("figcaption", { class: "adm-chart__cap" }, [
        el("span", { text: label }),
        el("span", { class: "adm-chart__total", text: `${fmtInt(total)} in 14 days` }),
      ]));
      fig.appendChild(barChart(series, key, label));
      chartPanel.appendChild(fig);
    }
    chartPanel.appendChild(el("p", { class: "adm-note", text:
      "Visits are landing and public page views; signups are accounts created. Small counts move a lot day to day." }));
  } else {
    chartPanel.appendChild(loadFailed("The overview", ctx.errors.overview));
  }
  cols.appendChild(chartPanel);
  host.appendChild(cols);
}

// ---- People ---------------------------------------------------------------

function td(label, content, attrs = {}) {
  const cell = el("td", { "data-label": label, ...attrs });
  if (content !== null && content !== undefined) {
    cell.appendChild(typeof content === "string" ? document.createTextNode(content) : content);
  }
  return cell;
}

function actionMenuCell(row, ctx) {
  const wrap = el("div", { class: "adm-rowmenu" });
  const items = rowActions(row, { passwordReset: ctx.passwordReset });
  const trigger = el("button", { type: "button", class: "adm-btn adm-btn--ghost adm-btn--sm", "data-hook": "admin-row-menu",
    "aria-haspopup": "menu", "aria-expanded": "false", "aria-label": `Actions for ${row.email}`, text: "Actions" });
  trigger.addEventListener("click", () => ctx.openMenu(trigger, row, items));
  wrap.appendChild(trigger);
  return wrap;
}

export function renderPeople(host, data, ctx) {
  clear(host);
  const rows = data.users ? peopleRows(data, ctx.now()) : null;
  if (!rows) {
    host.appendChild(el("section", { class: "adm-panel" }, [loadFailed("The people list", ctx.errors.users)]));
    return;
  }
  const filter = ctx.filter;
  const bar = el("div", { class: "adm-toolbar" });
  const search = el("input", { type: "search", class: "adm-input", placeholder: "Search email or id",
    "aria-label": "Search people", autocomplete: "off", "data-hook": "admin-people-search" });
  if (filter.q) search.value = filter.q;
  bar.appendChild(search);
  const groups = el("div", { class: "adm-seg", role: "group", "aria-label": "Filter people", "data-hook": "admin-people-groups" });
  for (const g of PEOPLE_GROUPS) {
    const count = g.key === "all" ? rows.length : rows.filter((r) => r.state.group === g.key).length;
    const b = el("button", { type: "button", class: "adm-seg__opt", "data-hook": "admin-people-group", "data-group": g.key,
      "aria-pressed": filter.group === g.key ? "true" : "false" });
    b.appendChild(document.createTextNode(g.label + " "));
    b.appendChild(el("span", { class: "adm-seg__count", text: String(count) }));
    b.addEventListener("click", () => { filter.group = g.key; ctx.rerenderPeople(); });
    groups.appendChild(b);
  }
  bar.appendChild(groups);
  bar.appendChild(button("Add person", { variant: "primary", hook: "admin-add-person", onClick: () => ctx.addPerson() }));
  host.appendChild(bar);

  const listHost = el("div", { "data-hook": "admin-people-list" });
  host.appendChild(listHost);

  function drawList() {
    clear(listHost);
    const shown = filterPeople(rows, filter.q, filter.group);
    const limit = filter.limit || 100;
    listHost.appendChild(el("p", { class: "adm-count", "data-hook": "admin-people-count",
      text: shown.length === rows.length ? `${fmtInt(rows.length)} people`
        : `${fmtInt(shown.length)} of ${fmtInt(rows.length)} people` }));
    if (shown.length === 0) {
      listHost.appendChild(el("p", { class: "adm-empty", "data-hook": "admin-people-empty",
        text: rows.length ? "Nobody matches that search and filter." : "No users yet." }));
      return;
    }
    const table = el("table", { class: "adm-table adm-table--people", "data-hook": "admin-people-table" });
    const head = el("tr");
    for (const col of ["Email", "Status", "Plan", "Joined", "Last seen", "Tester ends", ""]) {
      head.appendChild(el("th", { scope: "col", text: col }));
    }
    table.appendChild(el("thead", {}, [head]));
    const body = el("tbody");
    for (const row of shown.slice(0, limit)) {
      const tr = el("tr", { "data-hook": "admin-person-row", "data-user-id": String(row.id) });
      tr.appendChild(td("Email", el("span", { class: "adm-email", "data-hook": "admin-person-email", text: row.email })));
      tr.appendChild(td("Status", chip(row.state.word, row.state.tone, "admin-person-status")));
      tr.appendChild(td("Plan", row.plan === "beta" ? "Beta" : "None"));
      tr.appendChild(td("Joined", dateLabel(row.createdAt)));
      tr.appendChild(td("Last seen", row.lastSeen ? agoLabel(row.lastSeen, ctx.now()) : "—"));
      tr.appendChild(td("Tester ends", row.tester ? untilLabel(row.testerExpiresAt, ctx.now()) : "—",
        { "data-hook": "admin-person-expiry" }));
      tr.appendChild(td("", actionMenuCell(row, ctx), { class: "adm-td-actions" }));
      body.appendChild(tr);
    }
    table.appendChild(body);
    listHost.appendChild(el("div", { class: "adm-tablewrap" }, [table]));
    if (shown.length > limit) {
      listHost.appendChild(button(`Show more (${fmtInt(shown.length - limit)} not shown)`, { variant: "ghost",
        hook: "admin-people-more", onClick: () => { filter.limit = limit + 100; drawList(); } }));
    }
  }
  search.addEventListener("input", () => { filter.q = search.value; filter.limit = 100; drawList(); });
  drawList();
}

// ---- Funnel ---------------------------------------------------------------

export function renderFunnel(host, funnel, ctx) {
  clear(host);
  if (!funnel) {
    host.appendChild(el("section", { class: "adm-panel" }, [loadFailed("The funnel", ctx.errors.funnel)]));
    return;
  }
  const bars = funnelBars(funnel);
  const panel = el("section", { class: "adm-panel", "data-hook": "admin-funnel" });
  panel.appendChild(panelHead("Funnel", el("span", { class: "adm-panel__meta",
    text: `${dayLabel(funnel.start)} to ${dayLabel(funnel.end)}` })));
  const list = el("ol", { class: "adm-funnel", "data-hook": "admin-funnel-steps" });
  for (const bar of bars) {
    const li = el("li", { class: "adm-funnel__row", "data-hook": "admin-funnel-step", "data-step": bar.kind });
    li.appendChild(el("div", { class: "adm-funnel__label", text: bar.label }));
    const track = el("div", { class: "adm-funnel__track" });
    const fill = el("div", { class: "adm-funnel__fill", "data-hook": "admin-funnel-fill" });
    fill.style.width = `${bar.width}%`;
    track.appendChild(fill);
    li.appendChild(track);
    li.appendChild(el("div", { class: "adm-funnel__count", "data-hook": "admin-funnel-count", text: fmtInt(bar.count) }));
    const conv = bar.hasBase ? `${bar.pct}%${bar.from ? " of " + bar.from.toLowerCase() : ""}` : "—";
    li.appendChild(el("div", { class: "adm-funnel__conv", "data-hook": "admin-funnel-conv", text: conv }));
    list.appendChild(li);
  }
  panel.appendChild(list);
  const top = Math.max(0, ...bars.map((b) => b.count));
  panel.appendChild(el("p", { class: "adm-note", "data-hook": "admin-funnel-note", text:
    (top < 100 ? `Small sample: the biggest step has only ${top}, so a percentage here can swing a lot on one person. ` : "")
    + "Each percentage is measured from the step named beside it, or from the row above when none is named." }));
  if (funnel.internal_events_excluded > 0) {
    panel.appendChild(el("p", { class: "adm-note", text:
      `${funnel.internal_events_excluded} event(s) from our own test links are not counted above; they are listed under their source below.` }));
  }
  host.appendChild(panel);
  host.appendChild(sourceTable(funnel.by_source || {}));
  const sample = samplePanel(funnel);
  if (sample) host.appendChild(sample);
}

function sourceTable(bySource) {
  const panel = el("section", { class: "adm-panel", "data-hook": "admin-funnel-by-source" });
  panel.appendChild(panelHead("By source"));
  const sources = Object.keys(bySource);
  if (!sources.length) {
    panel.appendChild(el("p", { class: "adm-empty", text: "No attributed events in this range." }));
    return panel;
  }
  const steps = [];
  for (const s of sources) for (const k of Object.keys(bySource[s] || {})) if (!steps.includes(k)) steps.push(k);
  const table = el("table", { class: "adm-table", "data-hook": "admin-source-table" });
  const head = el("tr");
  head.appendChild(el("th", { scope: "col", text: "Source" }));
  for (const k of steps) head.appendChild(el("th", { scope: "col", class: "adm-num", text: stepLabel(k) }));
  table.appendChild(el("thead", {}, [head]));
  const body = el("tbody");
  for (const s of sources) {
    const tr = el("tr", { "data-hook": "admin-source-row", "data-source": s });
    tr.appendChild(td("Source", s));
    for (const k of steps) tr.appendChild(td(stepLabel(k), fmtInt(Number((bySource[s] || {})[k]) || 0), { class: "adm-num" }));
    body.appendChild(tr);
  }
  table.appendChild(body);
  panel.appendChild(el("div", { class: "adm-tablewrap" }, [table]));
  return panel;
}

function samplePanel(funnel) {
  const sample = funnel.page_views && funnel.page_views.sample;
  if (!sample || !sample.by_source) return null;
  const panel = el("section", { class: "adm-panel", "data-hook": "admin-sample-views" });
  panel.appendChild(panelHead("Sample page by source"));
  const table = el("table", { class: "adm-table" });
  const head = el("tr");
  for (const c of ["Source", "Sample views", "Unique visitors", "Signups started (any page)", "Accounts created (any page)"]) {
    head.appendChild(el("th", { scope: "col", class: c === "Source" ? "" : "adm-num", text: c }));
  }
  table.appendChild(el("thead", {}, [head]));
  const body = el("tbody");
  for (const [source, mine] of Object.entries(sample.by_source)) {
    const row = (funnel.by_source || {})[source] || {};
    const tr = el("tr");
    tr.appendChild(td("Source", source));
    tr.appendChild(td("Sample views", fmtInt(mine.views || 0), { class: "adm-num" }));
    tr.appendChild(td("Unique visitors", fmtInt(mine.unique_visitors || 0), { class: "adm-num" }));
    tr.appendChild(td("Signups started (any page)", fmtInt(row.signup_started || 0), { class: "adm-num" }));
    tr.appendChild(td("Accounts created (any page)", fmtInt(row.account_created || 0), { class: "adm-num" }));
    body.appendChild(tr);
  }
  table.appendChild(body);
  panel.appendChild(el("div", { class: "adm-tablewrap" }, [table]));
  return panel;
}

// ---- Health ---------------------------------------------------------------

function healthCard(card) {
  const node = el("div", { class: `adm-health adm-health--${card.tone}`, "data-hook": "admin-health-card",
    "data-store": card.key, "data-tone": card.tone });
  node.appendChild(el("div", { class: "adm-health__top" }, [
    el("div", { class: "adm-health__title", text: card.title }),
    chip(card.word, card.tone === "mute" ? "mute" : card.tone, "admin-health-word"),
  ]));
  node.appendChild(el("div", { class: "adm-health__big", "data-hook": "admin-health-big", text: card.big }));
  for (const line of card.lines) node.appendChild(el("div", { class: "adm-health__line", text: line }));
  // The server's own words, verbatim.
  if (card.reason) node.appendChild(el("div", { class: "adm-health__reason", "data-hook": "admin-health-reason", text: card.reason }));
  return node;
}

export function renderHealth(host, overview, ctx) {
  clear(host);
  const cards = storeCards(overview);
  if (!cards) {
    host.appendChild(el("section", { class: "adm-panel" }, [loadFailed("Health", ctx.errors.overview)]));
    return;
  }
  const summary = el("section", { class: `adm-panel adm-banner adm-banner--${cards.status === "ok" ? "ok" : "bad"}`,
    "data-hook": "admin-health-summary" });
  summary.appendChild(el("div", { class: "adm-banner__word", text: cards.status === "ok" ? "Healthy" : "Degraded" }));
  summary.appendChild(el("div", { class: "adm-banner__sub", text: cards.generatedAt ? `Checked ${momentLabel(cards.generatedAt)}` : "" }));
  if (cards.reasons.length) {
    const list = el("ul", { class: "adm-reasons", "data-hook": "admin-health-reasons" });
    // Verbatim -- no paraphrase, no truncation.
    for (const reason of cards.reasons) list.appendChild(el("li", { text: reason }));
    summary.appendChild(list);
  }
  host.appendChild(summary);
  for (const group of cards.groups) {
    const section = el("section", { class: "adm-group", "data-hook": "admin-health-group", "data-group": group.key });
    section.appendChild(el("h3", { class: "adm-group__title", text: group.title }));
    if (group.error) section.appendChild(el("p", { class: "adm-note adm-note--bad", text: group.error }));
    const grid = el("div", { class: "adm-health-grid" });
    for (const card of group.cards) grid.appendChild(healthCard(card));
    section.appendChild(grid);
    host.appendChild(section);
  }
  host.appendChild(el("p", { class: "adm-note", text:
    `Colours for stores: green when the newest row is under ${HEALTH_GREEN_HOURS} hours old, amber under ${HEALTH_AMBER_HOURS} hours or when there are no rows yet, red when older or unreadable. `
    + "The server reports the age; the colour thresholds are this page's." }));
}

// ---- Support --------------------------------------------------------------

const SUPPORT_STATUSES = ["open", "answered", "closed"];

export function renderSupport(host, support, ctx) {
  clear(host);
  if (!support) {
    host.appendChild(el("section", { class: "adm-panel" }, [loadFailed("Support", ctx.errors.support)]));
    return;
  }
  const messages = support.messages || [];
  const filter = ctx.supportFilter;
  const counts = { all: messages.length };
  for (const s of SUPPORT_STATUSES) counts[s] = messages.filter((m) => m.status === s).length;
  const bar = el("div", { class: "adm-toolbar" });
  const seg = el("div", { class: "adm-seg", role: "group", "aria-label": "Filter messages", "data-hook": "admin-support-filter" });
  for (const key of ["open", "answered", "closed", "all"]) {
    const b = el("button", { type: "button", class: "adm-seg__opt", "data-hook": "admin-support-filter-opt", "data-filter": key,
      "aria-pressed": filter.status === key ? "true" : "false" });
    b.appendChild(document.createTextNode(key[0].toUpperCase() + key.slice(1) + " "));
    b.appendChild(el("span", { class: "adm-seg__count", text: String(counts[key]) }));
    b.addEventListener("click", () => { filter.status = key; ctx.rerenderSupport(); });
    seg.appendChild(b);
  }
  bar.appendChild(seg);
  host.appendChild(bar);
  const shown = messages.filter((m) => filter.status === "all" || m.status === filter.status);
  if (!shown.length) {
    host.appendChild(el("p", { class: "adm-empty", "data-hook": "admin-support-empty",
      text: messages.length ? `No ${filter.status} messages.` : "No support messages." }));
    return;
  }
  const list = el("ul", { class: "adm-support", "data-hook": "admin-support-list" });
  for (const m of shown) {
    const card = el("li", { class: "adm-msg", "data-hook": "admin-support-message", "data-message-id": String(m.id),
      "data-status": m.status });
    card.appendChild(el("div", { class: "adm-msg__top" }, [
      el("div", { class: "adm-msg__subject", text: m.subject }),
      chip(m.status[0].toUpperCase() + m.status.slice(1), m.status === "open" ? "warn" : "mute", "admin-support-status"),
    ]));
    card.appendChild(el("div", { class: "adm-msg__meta", text:
      `${m.email || (m.user_id != null ? `user #${m.user_id}` : "unknown sender")} · ${momentLabel(m.created_at)}`
      + (m.answered_at ? ` · answered ${momentLabel(m.answered_at)}` : "") }));
    card.appendChild(el("p", { class: "adm-msg__body", text: m.body }));
    const actions = el("div", { class: "adm-msg__actions" });
    for (const s of SUPPORT_STATUSES) {
      if (s === m.status) continue;
      const label = s === "open" ? "Reopen" : `Mark ${s}`;
      actions.appendChild(button(label, { variant: "ghost", hook: "admin-support-set", onClick: () => ctx.setSupportStatus(m, s) }));
    }
    card.appendChild(actions);
    list.appendChild(card);
  }
  host.appendChild(list);
}
