// Node harness for the Hounds pages (tests/test_hounds_web_*.py). Copied next to web/js/*.js in a temp dir
// and run with SCENARIO (JSON) in the environment; prints one line "@@<json>".
//
// It builds a small fake DOM FROM THE REAL HTML FILE (so the page's own data-hook skeleton is what the
// script finds), fakes fetch from scenario.routes ({path: [status, body]}), fakes interval timers so a
// test can fire them by hand, and then runs scenario.actions (click / set / check / fire_timers /
// visibility / wait) before reporting what is on the page.
//
// Dog-page scenario keys (2026-10-18): `share` (navigator.share exists; `shareFails` names the error it throws),
// `storageThrows` ("methods": getItem/setItem throw; "accessor": touching window.localStorage throws), `tz`
// (the process time zone, set by the runner), and a fake canvas / Image / URL.createObjectURL so the card
// download runs. The report carries `shares`, `downloads` and `canvases` (every fillText string, the size).
import fs from "node:fs";

// The scenario comes in a file (SCENARIO_FILE): Linux refuses an environment variable over
// 128 KB (E2BIG, "Argument list too long"), and a fixture race is bigger than that.
import { readFileSync as __readScenario } from "node:fs";
const scenario = JSON.parse(process.env.SCENARIO_FILE
  ? __readScenario(process.env.SCENARIO_FILE, "utf8")
  : process.env.SCENARIO);

// ---- fake DOM -------------------------------------------------------------------------------------
const downloads = [];
const canvases = [];
const shares = [];
const VOID = new Set(["meta", "link", "br", "img", "input", "hr", "area", "base", "col", "source", "wbr"]);
const ENT = { "&middot;": "·", "&rarr;": "→", "&larr;": "←", "&amp;": "&", "&lt;": "<", "&gt;": ">",
  "&quot;": '"', "&#39;": "'", "&mdash;": "—", "&ndash;": "–", "&nbsp;": " " };
const decode = (s) => s.replace(/&[#\w]+;/g, (m) => ENT[m] ?? m);

class TextNode {
  constructor(t) { this.nodeType = 3; this.textContent = String(t); this.parentNode = null; }
}

class Elem {
  constructor(tag, ns) {
    this.nodeType = 1; this.tagName = String(tag).toUpperCase(); this.localName = String(tag).toLowerCase();
    this.namespaceURI = ns || "http://www.w3.org/1999/xhtml";
    this.attrs = {}; this.childNodes = []; this.parentNode = null; this.style = {}; this.listeners = {};
    this._value = undefined; this.checked = false; this.tabIndex = 0;
  }
  get children() { return this.childNodes.filter((c) => c.nodeType === 1); }
  get firstChild() { return this.childNodes[0] || null; }
  appendChild(c) { if (c.parentNode) c.parentNode.removeChild(c); c.parentNode = this; this.childNodes.push(c); return c; }
  removeChild(c) { const i = this.childNodes.indexOf(c); if (i >= 0) this.childNodes.splice(i, 1); c.parentNode = null; return c; }
  setAttribute(k, v) { this.attrs[k] = String(v); if (k === "value" && this._value === undefined) this._seedValue = String(v); }
  getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; }
  removeAttribute(k) { delete this.attrs[k]; }
  hasAttribute(k) { return k in this.attrs; }
  set hidden(v) { if (v) this.attrs.hidden = ""; else delete this.attrs.hidden; }
  get hidden() { return "hidden" in this.attrs; }
  get disabled() { return "disabled" in this.attrs; }
  set disabled(v) { if (v) this.attrs.disabled = ""; else delete this.attrs.disabled; }
  get className() { return this.attrs.class || ""; }
  get id() { return this.attrs.id || ""; }
  set textContent(v) { const t = new TextNode(v); t.parentNode = this; this.childNodes = v === "" ? [] : [t]; }
  get textContent() { return this.childNodes.map((c) => c.textContent).join(""); }
  get value() {
    if (this._value !== undefined) return this._value;
    if (this.localName === "select") { const o = this._all([]).find((n) => n.localName === "option"); return o ? (o.attrs.value ?? o.textContent) : ""; }
    return this._seedValue !== undefined ? this._seedValue : "";
  }
  set value(v) { this._value = String(v); }
  select() {}
  focus() {}
  blur() {}
  getBoundingClientRect() { return { left: 0, top: 0, width: scenario.width || 640, height: 300 }; }
  addEventListener(t, f) { (this.listeners[t] ||= []).push(f); }
  removeEventListener(t, f) { this.listeners[t] = (this.listeners[t] || []).filter((x) => x !== f); }
  dispatchEvent(evt) {
    evt.target = evt.target || this;
    for (let n = this; n; n = n.parentNode) {
      for (const f of n.listeners?.[evt.type] || []) f.call(n, evt);
      if (evt.cancelBubble) break;
    }
    return !evt.defaultPrevented;
  }
  // the nearest ancestor-or-self matching one of the comma-separated compound selectors (tag, #id, .class, [attr])
  closest(sel) {
    const steps = String(sel).split(",").map((part) => parseSelector(part)[0]);
    for (let n = this; n && n.nodeType === 1; n = n.parentNode) if (steps.some((s) => n.matches(s))) return n;
    return null;
  }
  click() { this.dispatchEvent({ type: "click", target: this }); if (this.localName === "a" && "download" in this.attrs) downloads.push({ href: this.attrs.href, download: this.attrs.download }); }
  getContext() {
    if (this.localName !== "canvas") return undefined;
    const rec = { w: 0, h: 0, texts: [], images: 0, rects: 0, fonts: [] };
    canvases.push(rec);
    this._rec = rec;
    const ctx = {
      set font(v) { rec.fonts.push(v); }, set fillStyle(v) {}, set textBaseline(v) {},
      fillRect: () => { rec.rects += 1; }, drawImage: () => { rec.images += 1; },
      fillText: (t) => { rec.texts.push(String(t)); }, measureText: (t) => ({ width: String(t).length * 14 }),
    };
    return ctx;
  }
  toBlob(cb) { if (this._rec) { this._rec.w = this.width; this._rec.h = this.height; } cb({ size: 1234, type: "image/png" }); }
  _all(out) { for (const c of this.children) { out.push(c); c._all(out); } return out; }
  matches(step) {
    if (step.tag && this.localName !== step.tag) return false;
    if (step.id && this.attrs.id !== step.id) return false;
    const cls = (this.attrs.class || "").split(/\s+/);
    if (!step.classes.every((c) => cls.includes(c))) return false;
    return step.attrs.every(([k, op, v]) => (k in this.attrs) && (op === null || this.attrs[k] === v));
  }
  querySelectorAll(sel) {
    const steps = parseSelector(sel);
    return this._all([]).filter((n) => matchesChain(n, steps, this));
  }
  querySelector(sel) { return this.querySelectorAll(sel)[0] || null; }
}

function parseSelector(sel) {
  return sel.trim().split(/\s+(?![^\[]*\])/).map((part) => {
    const step = { tag: "", id: "", classes: [], attrs: [] };
    const re = /^([a-zA-Z][\w-]*)|#([\w-]+)|\.([\w-]+)|\[([\w-]+)(?:=(?:'([^']*)'|"([^"]*)"|([^\]]*)))?\]/;
    let rest = part;
    while (rest) {
      const m = re.exec(rest);
      if (!m) throw new Error("bad selector " + sel);
      if (m[1]) step.tag = m[1].toLowerCase();
      else if (m[2]) step.id = m[2];
      else if (m[3]) step.classes.push(m[3]);
      else if (m[4]) { const v = m[5] ?? m[6] ?? m[7]; step.attrs.push([m[4], v === undefined ? null : "=", v]); }
      rest = rest.slice(m[0].length);
    }
    return step;
  });
}
function matchesChain(node, steps, root) {
  if (!node.matches(steps[steps.length - 1])) return false;
  let i = steps.length - 2;
  for (let p = node.parentNode; i >= 0 && p && p !== root.parentNode; p = p.parentNode) {
    if (p.nodeType === 1 && p.matches(steps[i])) i--;
  }
  return i < 0;
}

function parseHtml(html, into) {
  html = html.replace(/<!--[\s\S]*?-->/g, "");
  const body = html.slice(html.indexOf("<body"));
  const bodyOpen = body.indexOf(">") + 1;
  const src = body.slice(bodyOpen).replace(/<script[\s\S]*?<\/script>/g, "");
  const re = /<\/?([a-zA-Z][\w-]*)((?:\s+[\w:-]+(?:\s*=\s*(?:"[^"]*"|'[^']*'|[^\s>]+))?)*)\s*\/?>|([^<]+)/g;
  const stack = [into];
  let m;
  while ((m = re.exec(src))) {
    if (m[3] !== undefined) { const t = decode(m[3]); if (t.trim() || stack.length > 1) stack[stack.length - 1].appendChild(new TextNode(t)); continue; }
    const closing = m[0].startsWith("</");
    const tag = m[1].toLowerCase();
    if (closing) { if (tag !== "body") { while (stack.length > 1) { const top = stack.pop(); if (top.localName === tag) break; } } continue; }
    const el = new Elem(tag);
    const ar = /([\w:-]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+)))?/g;
    let a;
    while ((a = ar.exec(m[2] || ""))) el.setAttribute(a[1], decode(a[2] ?? a[3] ?? a[4] ?? ""));
    stack[stack.length - 1].appendChild(el);
    if (!VOID.has(tag) && !m[0].endsWith("/>")) stack.push(el);
  }
}

const body = new Elem("body");
parseHtml(fs.readFileSync(scenario.html, "utf8"), body);

const docListeners = {};
globalThis.document = {
  createElement: (t) => new Elem(t),
  createElementNS: (ns, t) => new Elem(t, ns),
  createTextNode: (t) => new TextNode(t),
  body, readyState: "complete", visibilityState: scenario.visibility || "visible", referrer: "",
  title: "",
  addEventListener: (t, f) => { (docListeners[t] ||= []).push(f); },
  removeEventListener: (t, f) => { docListeners[t] = (docListeners[t] || []).filter((x) => x !== f); },
  dispatchEvent: (e) => { for (const f of docListeners[e.type] || []) f(e); return true; },
  querySelector: (s) => body.querySelector(s),
  querySelectorAll: (s) => body.querySelectorAll(s),
  execCommand: () => false,
};

const store = new Map(Object.entries(scenario.stored || {}));
const storage = {
  getItem: (k) => (store.has(k) ? store.get(k) : null),
  setItem: (k, v) => { store.set(k, String(v)); },
  removeItem: (k) => { store.delete(k); },
};
const throwing = scenario.storageThrows === "methods" ? () => { throw new Error("storage blocked"); } : null;
if (throwing) { storage.getItem = throwing; storage.setItem = throwing; storage.removeItem = throwing; }
const navigations = [];
const replaced = [];           // every URL the page wrote with history.replaceState (the season choice, ?season=)
const winListeners = {};
const loc = { search: scenario.search || "", host: "linehound.test", protocol: "https:", origin: "https://linehound.test",
  pathname: "/web/x.html", hash: "" };
Object.defineProperty(loc, "href", { get: () => "", set: (v) => navigations.push(String(v)) });
globalThis.window = {
  localStorage: storage, sessionStorage: storage, location: loc, history: { replaceState(state, title, url) { replaced.push(String(url)); } },
  addEventListener: (t, f) => { (winListeners[t] ||= []).push(f); }, removeEventListener() {},
  dispatchEvent() { return true; }, scrollTo() {}, crypto: globalThis.crypto,
};
globalThis.location = loc;
if (scenario.storageThrows === "accessor") {
  for (const target of [globalThis.window, globalThis]) {
    for (const key of ["localStorage", "sessionStorage"]) {
      Object.defineProperty(target, key, { configurable: true, get() { throw new Error("storage denied"); } });
    }
  }
} else {
  globalThis.localStorage = storage;
  globalThis.sessionStorage = storage;
}

const clipboard = [];
Object.defineProperty(globalThis, "navigator", { configurable: true, value: {
  share: scenario.share ? async (d) => {
    if (scenario.shareFails) throw Object.assign(new Error("share failed"), { name: scenario.shareFails });
    shares.push(d);
  } : undefined,
  clipboard: scenario.noClipboard ? undefined : { writeText: async (t) => {
    if (scenario.clipboardFails) throw new Error("denied");
    clipboard.push(t);
  } } } });
globalThis.Image = class { set src(v) { this._src = v; setTimeout(() => this.onload && this.onload(), 0); } get src() { return this._src; } };
URL.createObjectURL = () => "blob:fake";
URL.revokeObjectURL = () => {};
globalThis.URLSearchParams = URLSearchParams;

// ---- fake interval timers (setTimeout stays real: api.js clears its own) --------------------------
const intervals = new Map();
let nextTimer = 1;
globalThis.setInterval = (fn, ms) => { const id = nextTimer++; intervals.set(id, { fn, ms }); return id; };
globalThis.clearInterval = (id) => { intervals.delete(id); };

// ---- fake fetch -----------------------------------------------------------------------------------
const gets = [];
const posts = [];
globalThis.fetch = async (url, init = {}) => {
  url = String(url);
  const path = url.split("?")[0];
  if (init.method === "POST") posts.push({ url, body: init.body ? JSON.parse(init.body) : null, headers: init.headers });
  else gets.push(url);
  if ((scenario.down || []).some((p) => path === p || (p.endsWith("*") && path.startsWith(p.slice(0, -1))))) {
    throw new TypeError("fetch failed");
  }
  const counts = (globalThis.__counts ||= {});
  counts[path] = (counts[path] || 0) + 1;
  const after = (scenario.failAfter || {})[path];
  if (after !== undefined && counts[path] > after) return { ok: false, status: 503, text: async () => "{}" };
  const key = init.method === "POST" ? "POST " + path : path;
  // a route may be keyed by the FULL url (path and query) to answer one page of a paged list; else by path
  let hit = (scenario.routes || {})[(init.method === "POST" ? "POST " : "") + url] || (scenario.routes || {})[key];
  // switchAfter: {path: [n, [status, payload]]}: from the (n+1)th call on, answer with the other payload
  // (the server's first answer is "warming up", its later ones are the real thing)
  const sw = (scenario.switchAfter || {})[path];
  if (sw && counts[path] > sw[0]) hit = sw[1];
  if (!hit) return { ok: false, status: 404, text: async () => JSON.stringify({ detail: "Not Found" }) };
  const [status, payload] = hit;
  return { ok: status >= 200 && status < 300, status, text: async () => JSON.stringify(payload) };
};

// ---- helpers --------------------------------------------------------------------------------------
const text = (n) => (n.nodeType === 3 ? n.textContent : n.childNodes.map(text).join(" "));
const flat = (s) => s.replace(/\s+/g, " ").trim();
const settle = (ms = 60) => new Promise((r) => setTimeout(r, ms));
const find = (sel, index = 0) => {
  const list = body.querySelectorAll(sel);
  if (!list[index]) throw new Error(`no element for ${sel}[${index}]`);
  return list[index];
};
function evaluate(q) {
  const list = body.querySelectorAll(q.sel);
  switch (q.mode) {
    case "count": return list.length;
    case "texts": return list.map((n) => flat(text(n)));
    case "attrs": return list.map((n) => n.attrs[q.attr] ?? null);
    case "attr": return list[0] ? (list[0].attrs[q.attr] ?? null) : null;
    case "exists": return list.length > 0;
    case "hidden": return list[0] ? list[0].hidden : null;
    case "disabled": return list[0] ? list[0].disabled : null;
    case "value": return list[0] ? list[0].value : null;
    default: return list[0] ? flat(text(list[0])) : null;
  }
}
const captures = {};
const capture = (label, qs) => { captures[label] = Object.fromEntries((qs || []).map((q) => [q.name, evaluate(q)])); };

const out = { crashed: false };
try {
  const mod = await import(scenario.module);
  await settle(scenario.settleMs || 80);
  if (scenario.captureInitial) capture("initial", scenario.captureInitial);
  for (const [i, a] of (scenario.actions || []).entries()) {
    const label = a.label || String(i);
    if (a.do === "click") {
      const el = find(a.sel, a.index || 0);
      el.dispatchEvent({ type: "click", target: el });
    } else if (a.do === "set") {
      const el = find(a.sel, a.index || 0);
      el.value = a.value;
      el.dispatchEvent({ type: "input", target: el });
    } else if (a.do === "check") {
      const el = find(a.sel, a.index || 0);
      el.checked = a.checked !== false;
      el.dispatchEvent({ type: "change", target: el });
    } else if (a.do === "fire_timers") {
      for (const { fn } of [...intervals.values()]) fn();
    } else if (a.do === "visibility") {
      document.visibilityState = a.state;
      document.dispatchEvent({ type: "visibilitychange" });
    } else if (a.do === "key") {
      const el = find(a.sel, a.index || 0);
      el.dispatchEvent({ type: "keydown", key: a.key, target: el, preventDefault() {} });
    } else if (a.do === "pointer") {
      const el = find(a.sel, a.index || 0);
      el.dispatchEvent({ type: a.type || "pointermove", clientX: a.x, clientY: 0, target: el });
    }
    await settle(a.wait ?? 40);
    if (a.capture) capture(label, a.capture);
  }
  out.text = flat(text(body));
  out.hooks = body._all([]).map((n) => n.attrs["data-hook"]).filter(Boolean);
  out.title = document.title;
  out.final = Object.fromEntries((scenario.queries || []).map((q) => [q.name, evaluate(q)]));
  out.mod = Object.keys(mod);
} catch (err) {
  out.crashed = String((err && err.stack) || err);
}
out.captures = captures;
out.gets = gets;
out.posts = posts;
out.navigations = navigations;
out.replaced = replaced;
out.shares = shares;
out.downloads = downloads;
out.canvases = canvases;
out.storedAfter = Object.fromEntries(store);
out.clipboard = clipboard;
out.intervals = [...intervals.values()].map((v) => v.ms);
console.log("@@" + JSON.stringify(out));
process.exit(0);
