/**
 * web/kennel.html: My kennel (signed in) and a member's public kennel (?u=<handle>).
 *
 * MY KENNEL is the hub. Each dog is a card with its locker-room avatar (an idle bob and blink; a happy wiggle when its
 * last pick won, a slump when it lost: all CSS, see css/lh.css), its season record and units, its last pick and a
 * status. One tap each: Fire now, Ask, Edit, Open. "Build a dog" is the last card. Clicking a dog opens the STUDIO, an
 * in-place drawer with five tabs that REUSE the dog page's and the builder's own modules, never a copy of their logic:
 *
 *   Look     dog-locker.js          the locker room, previewed live on the animated avatar
 *   Rules    hounds-build.js        the English box and the rule cards (builder-skeleton.js), saved as a new version
 *   Fire now dog-fire.js            what the rule would bet right now, read only
 *   Ask      dog-ask.js             the dog's answers, worked out from its own data
 *   Record   dog-manual.js + tickets  the season record, the manual picks and the last tickets
 *
 * A PUBLIC KENNEL is the same cards, read only (Open and Ask are links to the dog's page), for any visitor. The data is
 * GET /hounds/kennels/mine (signed in) and GET /hounds/kennels/{handle}; a dog with no bet yet is listed and says "New".
 * The studio's deep link is ?dog=<id>&tab=<tab>. Nothing here measures anything: every number is the server's.
 */

import { apiGet } from "./api.js";
import { TOKEN_CHANGED_EVENT } from "./api.js";
import { h, clearNode, isNum, houndHref, kennelName, describeError } from "./hounds-core.js";
import { signedIn, get, SIGNIN_HREF } from "./dog-common.js";
import { dogBadge, DEFAULT_LOOK } from "./dog-avatar.js";
import { mountTabs } from "./tabs.js";
import { mountLocker } from "./dog-locker.js";
import { mountFire } from "./dog-fire.js";
import { bootAsk } from "./dog-ask.js";
import { mountManual } from "./dog-manual.js";
import { ticketList } from "./hounds-tickets.js";

const q = (hook) => document.querySelector(`[data-hook='${hook}']`);

const state = {
  mode: "mine",             // "mine" | "public"
  data: null,               // the kennel payload
  open: null,               // the dog id (or "new") the studio shows
  opener: null,
  tabs: null,
  loaded: {},               // tab -> the dog id it was built for
  kit: null,
};

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

const avatarOf = (dog, size, mood) => dogBadge(dog.look || DEFAULT_LOOK, { size, mood: mood || moodOf(dog) });

// ---- cards ------------------------------------------------------------------------------------------------

function stat(label, value, extra = {}) {
  return h("div", { class: "kn-stat" }, [h("dt", { text: label }), h("dd", Object.assign({ text: value }, extra))]);
}

function dogCard(dog, { mine }, index) {
  const status = statusOf(dog);
  const rec = dog.record || {};
  const mood = moodOf(dog);
  const open = () => openStudio(dog.id, "look", card);
  const actions = mine && !dog.retired
    ? [
      h("button", { type: "button", class: "kn-act kn-act--primary", "data-hook": "dog-action-fire", text: "Fire now",
        on: { click: (e) => { stop(e); openStudio(dog.id, "fire", card, { autofire: true }); } } }),
      h("button", { type: "button", class: "kn-act", "data-hook": "dog-action-ask", text: "Ask",
        on: { click: (e) => { stop(e); openStudio(dog.id, "ask", card); } } }),
      h("button", { type: "button", class: "kn-act", "data-hook": "dog-action-edit", text: "Edit",
        on: { click: (e) => { stop(e); openStudio(dog.id, "rules", card); } } }),
      h("a", { class: "kn-act", href: houndHref(dog.id), "data-hook": "dog-action-open", text: "Open",
        on: { click: (e) => stop(e) } })]
    : mine
      ? [h("a", { class: "kn-act", href: houndHref(dog.id), "data-hook": "dog-action-open", text: "Open" }),
        h("a", { class: "kn-act", href: dog.builder_href || "build-a-hound.html", "data-hook": "dog-action-copy", text: "Build a copy" })]
      : [h("a", { class: "kn-act kn-act--primary", href: houndHref(dog.id), "data-hook": "dog-action-open", text: "Open" }),
        h("a", { class: "kn-act", href: `${houndHref(dog.id)}&tab=ask`, "data-hook": "dog-action-ask", text: "Ask" })];
  const card = h("article", { class: "kn-card", "data-hook": "kennel-dog", "data-id": dog.id, "data-status": status.key, "data-mood": mood,
    style: `--i:${Math.min(index, 12)}` }, [
    h("button", { type: "button", class: "kn-card__avatar", "data-hook": "dog-avatar", "aria-label": mine ? `Open ${dog.name}'s studio` : `${dog.name}`,
      on: { click: mine ? open : () => { window.location.href = houndHref(dog.id); } } }, [avatarOf(dog, 76, mood)]),
    h("div", { class: "kn-card__main" }, [
      h("div", { class: "kn-card__top" }, [
        h("h3", { class: "kn-card__name" }, [h("a", { href: houndHref(dog.id), "data-hook": "dog-name", text: dog.name })]),
        h("span", { class: "kn-pill", "data-status": status.key, "data-hook": "dog-status" }, [
          status.key === "live" ? h("i", { class: "lh-live", "aria-hidden": "true" }) : null, status.text])]),
      dog.tagline ? h("p", { class: "kn-card__tag", text: dog.tagline }) : null,
      h("dl", { class: "kn-stats" }, [
        stat("Record", recordText(rec), { "data-hook": "dog-record" }),
        stat("Units", unitsText(rec), { "data-hook": "dog-units", "data-count": "1" }),
        stat("Bets", String(rec.bets || 0), { "data-hook": "dog-bets", "data-count": "1" })]),
      h("p", { class: "kn-card__last", "data-hook": "dog-last", text: lastPickText(dog) }),
      h("div", { class: "kn-card__actions" }, actions)]),
  ]);
  return card;
}

function buildCard(index) {
  return h("button", { type: "button", class: "kn-card kn-card--build", "data-hook": "kennel-build-card", style: `--i:${Math.min(index, 12)}`,
    on: { click: (e) => openStudio("new", "rules", e.currentTarget) } }, [
    h("span", { class: "kn-build__plus", "aria-hidden": "true", text: "+" }),
    h("span", { class: "kn-build__title", text: "Build a dog" }),
    h("span", { class: "kn-build__sub", text: "Say a strategy in plain English." })]);
}

function emptyMine() {
  return h("div", { class: "kn-empty", "data-hook": "kennel-empty" }, [
    h("div", { class: "kn-empty__dog", "aria-hidden": "true" }, [dogBadge(DEFAULT_LOOK, { size: 96 })]),
    h("h2", { text: "No dogs yet" }),
    h("p", { class: "hd-lede", text: "Build your first dog. It turns a strategy into rules and races them on paper money." }),
    h("button", { type: "button", class: "lh-btn lh-btn--solid kn-empty__cta", "data-hook": "kennel-empty-build", text: "Build your first dog",
      on: { click: (e) => openStudio("new", "rules", e.currentTarget) } })]);
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
    setHead({ eyebrow: "Kennel", title: "My kennel", sub: "" });
    box.appendChild(h("div", { class: "kn-empty", "data-hook": "kennel-signin" }, [
      h("div", { class: "kn-empty__dog", "aria-hidden": "true" }, [dogBadge(DEFAULT_LOOK, { size: 96 })]),
      h("h2", { text: "Sign in to see your dogs" }),
      h("p", { class: "hd-lede", text: "Your kennel is where you build, dress and fire your dogs." }),
      h("div", { class: "kn-empty__row" }, [
        h("a", { class: "lh-btn lh-btn--solid", href: SIGNIN_HREF, "data-hook": "kennel-signin-link", text: "Sign in" }),
        h("a", { class: "lh-btn lh-btn--soft", href: "kennels.html", "data-hook": "kennel-browse", text: "Browse kennels" })])]));
  } else {
    setHead({ eyebrow: "Kennel", title: "Kennel not found", sub: "" });
    box.appendChild(h("div", { class: "kn-empty", "data-hook": "kennel-missing" }, [
      h("h2", { text: "No kennel with that name" }),
      h("p", { class: "hd-lede", text: "It may have no public dogs, or the link is off." }),
      h("a", { class: "lh-btn lh-btn--solid", href: "kennels.html", text: "Browse kennels" })]));
  }
}

function render() {
  const data = state.data;
  const mine = state.mode === "mine";
  const grid = clearNode(q("kennel-grid"));
  q("kennel-gate").hidden = true;
  const active = data.dogs.filter((d) => !d.retired);
  const retired = data.dogs.filter((d) => d.retired);
  const actions = clearNode(q("kennel-actions"));
  if (mine) {
    setHead({ eyebrow: "Your dogs", title: "My kennel",
      sub: active.length ? `${active.length} ${active.length === 1 ? "dog" : "dogs"}. Tap one to dress it, edit it or fire it.` : "" });
    actions.appendChild(h("a", { class: "lh-btn lh-btn--soft", href: `kennel.html?u=${encodeURIComponent(data.handle)}`, "data-hook": "kennel-public-link", text: "Public page" }));
    actions.appendChild(h("button", { type: "button", class: "lh-btn lh-btn--solid", "data-hook": "kennel-build", text: "Build a dog",
      on: { click: (e) => openStudio("new", "rules", e.currentTarget) } }));
  } else {
    const best = data.best;
    setHead({ eyebrow: "Kennel", title: kennelName(data.display),
      sub: `${data.dog_count} ${data.dog_count === 1 ? "dog" : "dogs"}${best ? `. Best: ${best.name}, ${recordText(best.record)}` : ". No bets settled yet"}.` });
  }
  if (!data.dogs.length && mine) {
    grid.appendChild(emptyMine());
  } else {
    active.forEach((dog, i) => grid.appendChild(dogCard(dog, { mine }, i)));
    if (mine) grid.appendChild(buildCard(active.length));
  }
  const rest = clearNode(q("kennel-retired"));
  if (mine && retired.length) {
    rest.appendChild(h("details", { class: "kn-retired", "data-hook": "kennel-retired-list" }, [
      h("summary", { text: `Retired (${retired.length})` }),
      h("div", { class: "kn-grid kn-grid--quiet" }, retired.map((d, i) => dogCard(d, { mine }, i)))]));
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
  if (!dog) {
    av.appendChild(dogBadge(look || DEFAULT_LOOK, { size: 56 }));
    q("studio-title").textContent = "New dog";
    sub.textContent = "Say a strategy and it becomes a dog.";
    q("studio-open").hidden = true;
    return;
  }
  av.appendChild(dogBadge(look || dog.look || DEFAULT_LOOK, { size: 56, mood: moodOf(dog) }));
  q("studio-title").textContent = dog.name;
  sub.textContent = `${recordText(dog.record)}, ${unitsText(dog.record)}${dog.tagline ? ` · ${dog.tagline}` : ""}`;
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
    clearNode(host).appendChild(h("p", { class: "hd-muted", text: describeError(err, "this dog").text }));
    state.loaded[tab] = null;
    return;
  }
  const kit = state.kit;
  clearNode(host);
  if (tab === "look") {
    const sec = section("dog-locker");
    host.appendChild(sec);
    mountLocker(sec, { id: dog.id, name: dog.name, kit, onChange: (look) => paintStudioHead(look),
      onSaved: (look) => { dog.look = look; refreshCards(); } });
  } else if (tab === "fire") {
    const sec = section("dog-fire");
    host.appendChild(sec);
    mountFire(sec, { id: dog.id, name: dog.name, kit, onRecord: () => { state.loaded.record = null; } });
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
    stat("Record", recordText(rec)), stat("Units", unitsText(rec)), stat("Bets", String(rec.bets || 0)),
    stat("Open", String(dog.open_bets || 0))]));
  host.appendChild(h("p", { class: "hd-fine", text: `${state.data.season && state.data.season.label ? state.data.season.label : "This season"}, one unit a bet at the average price.${(rec.bets || 0) < 30 ? " A small sample: it says little about what comes next." : ""}` }));
  const tickets = h("div", { "data-hook": "studio-tickets" });
  host.appendChild(h("h3", { class: "hd-h3", text: "Last tickets" }));
  host.appendChild(tickets);
  try {
    const out = await apiGet(`/hounds/${encodeURIComponent(dog.id)}/bets?page=1&page_size=5&segment=forward`);
    const items = Array.isArray(out && out.items) ? out.items : [];
    if (items.length) tickets.appendChild(ticketList(items, { showModel: false, hook: "studio-ticket-list" }));
    else tickets.appendChild(h("p", { class: "hd-muted", text: "No tickets recorded yet." }));
  } catch (err) {
    tickets.appendChild(h("p", { class: "hd-muted", text: describeError(err, "this dog's tickets").text }));
  }
  const manual = h("section", { class: "dk-panel kn-section", hidden: "" }, [h("h3", { class: "hd-h3", text: "Manual picks" }), h("div", { "data-hook": "dog-manual" })]);
  host.appendChild(manual);
  await mountManual(manual, { id: dog.id, kit });
}

async function buildRules(host, dog) {
  const { builderSkeleton } = await import("./builder-skeleton.js");
  if (!host.querySelector("[data-hook='build-app']")) host.appendChild(builderSkeleton());
  const builder = await import("./hounds-build.js");
  await builder.booted;
  if (state.open !== (dog ? dog.id : "new")) return;
  if (!dog) { builder.openBlank(); return; }
  if (dog.retired) {
    host.appendChild(h("p", { class: "hd-muted", "data-hook": "studio-retired-note" }, [
      "A retired dog cannot be edited. ", h("a", { href: dog.builder_href || "build-a-hound.html", text: "Build a copy" }), "."]));
    return;
  }
  if (!builder.openEdit(dog.id)) {
    host.appendChild(h("p", { class: "hd-muted", text: "Sign in again to edit this dog." }));
  }
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
  for (const k of ["look", "fire", "ask", "record"]) clearNode(q(`studio-${k}`));
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
      for (const k of ["look", "fire", "ask", "record"]) clearNode(q(`studio-${k}`));
      paintStudioHead();
      if (state.tabs) state.tabs.select("look");
      writeUrl(detail.id, "look");
    } else if (detail.type === "version" && dogById(detail.id)) {
      state.open = detail.id;
      state.loaded = { rules: detail.id };
      for (const k of ["look", "fire", "ask", "record"]) clearNode(q(`studio-${k}`));
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
