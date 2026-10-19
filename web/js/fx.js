/**
 * Small, tasteful motion for the model pages (vanilla; no library). Loaded as its own script so a page works the same
 * without it. EVERYTHING here is skipped for `prefers-reduced-motion: reduce`, and nothing changes what a number says:
 * a count-up ends on the exact text it started with.
 *
 *   count-up     an element marked `data-count` counts up to the number already in its text when it scrolls into view
 *   celebrate    window event "linehound:celebrate" (a dog was created, a manual pick was recorded) bursts a few
 *                small pieces of confetti from the element in `detail.el` (or the middle of the screen)
 *
 * Rows fading and sliding in, hover lift, skeletons, the live pulse and the avatar's idle motion are CSS (css/lh.css).
 */

export const CELEBRATE_EVENT = "linehound:celebrate";
const COLORS = ["#2FD07A", "#7BF0B2", "#E0B24A", "#8FB8FF", "#FF8A96", "#EEF1F5"];

export function reducedMotion() {
  try {
    return !!(window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches);
  } catch (err) {
    return false;
  }
}

/** The number in `text`: {prefix, value, decimals, suffix}, or null when there is none. */
export function parseCount(text) {
  const m = /^([^0-9+\-]*)([+\-]?)(\d[\d,]*)(\.(\d+))?(.*)$/.exec(String(text || "").trim());
  if (!m) return null;
  const decimals = m[5] ? m[5].length : 0;
  const value = Number(`${m[3].replace(/,/g, "")}${decimals ? `.${m[5]}` : ""}`) * (m[2] === "-" ? -1 : 1);
  if (!Number.isFinite(value)) return null;
  return { prefix: m[1] + (m[2] === "+" ? "+" : ""), value, decimals, suffix: m[6], neg: m[2] === "-" };
}

function format(parts, v) {
  const body = Math.abs(v).toFixed(parts.decimals);
  return `${parts.prefix}${v < 0 || (parts.neg && v === 0) ? "-" : ""}${body}${parts.suffix}`;
}

export function countUp(el, ms = 700) {
  if (!el || el.getAttribute("data-counted") === "1") return;
  el.setAttribute("data-counted", "1");
  const original = el.textContent;
  const parts = parseCount(original);
  if (!parts || parts.value === 0 || reducedMotion() || typeof requestAnimationFrame !== "function") return;
  const start = performance.now();
  const step = (now) => {
    const t = Math.min(1, (now - start) / ms);
    const eased = 1 - Math.pow(1 - t, 3);
    el.textContent = t >= 1 ? original : format(parts, parts.value * eased);
    if (t < 1) requestAnimationFrame(step);
  };
  el.textContent = format(parts, 0);
  requestAnimationFrame(step);
}

export function burst(anchor, { pieces = 26 } = {}) {
  if (reducedMotion() || typeof document === "undefined" || !document.body || typeof document.body.animate !== "function") return 0;
  let x = window.innerWidth / 2, y = window.innerHeight / 3;
  if (anchor && anchor.getBoundingClientRect) {
    const r = anchor.getBoundingClientRect();
    x = r.left + r.width / 2;
    y = r.top + r.height / 2;
  }
  const layer = document.createElement("div");
  layer.setAttribute("class", "lh-confetti");
  layer.setAttribute("aria-hidden", "true");
  document.body.appendChild(layer);
  let done = 0;
  for (let i = 0; i < pieces; i++) {
    const bit = document.createElement("i");
    bit.setAttribute("style", `left:${x}px;top:${y}px;background:${COLORS[i % COLORS.length]};width:${5 + (i % 3) * 2}px;height:${8 + (i % 4) * 2}px`);
    layer.appendChild(bit);
    const angle = (Math.PI * 2 * i) / pieces + (i % 5) * 0.2;
    const dist = 70 + (i * 37) % 110;
    const anim = bit.animate([
      { transform: "translate(0,0) rotate(0deg)", opacity: 1 },
      { transform: `translate(${Math.cos(angle) * dist}px, ${Math.sin(angle) * dist - 30}px) rotate(${(i % 2 ? 1 : -1) * 240}deg)`, opacity: 1, offset: 0.55 },
      { transform: `translate(${Math.cos(angle) * dist * 1.1}px, ${Math.sin(angle) * dist + 110}px) rotate(${(i % 2 ? 1 : -1) * 420}deg)`, opacity: 0 },
    ], { duration: 1100 + (i % 6) * 70, easing: "cubic-bezier(.2,.7,.3,1)", fill: "forwards" });
    anim.onfinish = () => { done += 1; if (done >= pieces && layer.parentNode) layer.parentNode.removeChild(layer); };
  }
  return pieces;
}

function watchCounts() {
  const seen = typeof IntersectionObserver === "function"
    ? new IntersectionObserver((entries) => {
      for (const e of entries) if (e.isIntersecting) { countUp(e.target); seen.unobserve(e.target); }
    }, { threshold: 0.2 }) : null;
  const scan = (root) => {
    for (const el of root.querySelectorAll ? root.querySelectorAll("[data-count], .hd-kpi__big") : []) {
      if (el.getAttribute("data-counted") === "1" || el.getAttribute("data-watch") === "1") continue;
      el.setAttribute("data-watch", "1");
      if (seen) seen.observe(el); else countUp(el);
    }
  };
  scan(document);
  if (typeof MutationObserver === "function") {
    new MutationObserver((records) => {
      for (const r of records) for (const n of r.addedNodes) if (n.nodeType === 1) scan(n);
    }).observe(document.body, { childList: true, subtree: true });
  }
}

/**
 * Rows and cards rise in ONCE, when they first arrive. Each new row or card gets `data-rise` (css/lh.css animates it);
 * a node already on the page never gets it again, and a change a person caused (a click, a key: sorting, opening a
 * drawer, switching a tab) is not animated, so the entrance never replays.
 */
const RISE = "tr.hd-tr, .hd-ticket, .hd-stream__item, .dk-ticket, .kn-card, .kn-kcard, .hd-grave__item, .lbrow, .lbticket, .lbrace__item, .lb-podium__card";

function watchRise() {
  let lastTouch = 0;
  const touch = () => { lastTouch = Date.now(); };
  for (const type of ["pointerdown", "keydown", "click"]) document.addEventListener(type, touch, true);
  const rise = (root) => {
    const list = [];
    if (root.matches && root.matches(RISE)) list.push(root);
    if (root.querySelectorAll) list.push(...root.querySelectorAll(RISE));
    list.forEach((el, i) => {
      if (el.hasAttribute("data-rise")) return;
      el.setAttribute("data-rise", "1");
      if (el.style && el.style.setProperty) el.style.setProperty("--r", String(Math.min(i, 12)));
    });
  };
  rise(document.body);
  if (typeof MutationObserver === "function") {
    new MutationObserver((records) => {
      if (Date.now() - lastTouch < 900) return;
      for (const r of records) for (const n of r.addedNodes) if (n.nodeType === 1) rise(n);
    }).observe(document.body, { childList: true, subtree: true });
  }
}

export function startFx() {
  if (typeof document === "undefined" || !document.body) return;
  watchRise();
  watchCounts();
  window.addEventListener(CELEBRATE_EVENT, (evt) => { burst(evt && evt.detail ? evt.detail.el : null); });
}

startFx();
