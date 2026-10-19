/**
 * Showable: share a dog, and download its card.
 *
 *   SHARE THIS DOG: navigator.share when the browser has it (phones), else copy the link and say so in a
 *   toast. The link is /d/<id> (api/hounds_share.py), the server page whose Open Graph tags make the link
 *   unfurl as the dog; it then sends a person on to the dog page. A cancelled share sheet is not an error
 *   and shows nothing.
 *
 *   DOWNLOAD CARD: a 1200x630 PNG drawn on a canvas in the browser, nothing uploaded: the model's initials
 *   badge (an inline SVG drawn from its own markup), name, catchphrase, season W-L, paper units,
 *   streak, status, and "Paper bets only · 21+ · linehound.app". The words come from the numbers the page
 *   already has (`cardLines`, pure); the drawing is `drawCard`, which takes any 2D context so a test can
 *   hand it a recorder. The hard lines are ON the card: it leaves the site.
 */

import { h, monogramSvg, categoryOf, isNum } from "./hounds-core.js";
import { unitsOf, wlText, personaOf } from "./hounds-voice.js";
import { statusOf, streakText } from "./hounds-board.js";

export const CARD_W = 1200;
export const CARD_H = 630;
export const CARD_FOOTER = "Paper bets only · 21+ · linehound.app";
export const SITE_ORIGIN = "https://linehound.app";
const TOAST_MS = 3200;

// ---- the link ------------------------------------------------------------------------------------------

export function siteOrigin() {
  try {
    const loc = typeof window !== "undefined" ? window.location : null;
    if (loc && loc.origin && loc.origin !== "null") return loc.origin;
    if (loc && loc.protocol && loc.host) return `${loc.protocol}//${loc.host}`;
  } catch (err) { /* fall through */ }
  return SITE_ORIGIN;
}

/** The link to share: the server's /d/<id> page, never the bare dog page (that one cannot unfurl). */
export function shareUrl(id) {
  return `${siteOrigin()}/d/${encodeURIComponent(String(id))}`;
}

export function shareTitle(hound) {
  return `${hound.name || "A model"} | LineHound`;
}

function unitsWord(hound) {
  const u = unitsOf(hound);
  if (u === null) return "no bets yet";
  const r = Math.round(u * 100) / 100;
  return `${r > 0 ? "+" : r < 0 ? "-" : ""}${Math.abs(r).toFixed(2)}u paper`;
}

export function shareMessage(hound) {
  return `${hound.name || "A model"}: ${wlText(hound.record)} · ${unitsWord(hound)}. Paper bets only, not advice, 21+.`;
}

// ---- copy and toast -------------------------------------------------------------------------------------

/** Copy text; resolves true/false. Uses the async clipboard, then the old textarea route. */
export async function copyText(text) {
  try {
    if (typeof navigator !== "undefined" && navigator.clipboard && navigator.clipboard.writeText) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch (err) { /* fall through */ }
  try {
    const area = h("textarea", { "aria-hidden": "true", readonly: "", style: "position:fixed;opacity:0;top:0;left:0" });
    area.value = text;
    document.body.appendChild(area);
    if (area.select) area.select();
    const ok = document.execCommand ? document.execCommand("copy") : false;
    document.body.removeChild(area);
    return !!ok;
  } catch (err) {
    return false;
  }
}

let toastTimer = null;

/** A small message that fades on its own; one at a time, announced to screen readers. */
export function toast(text) {
  let node = document.querySelector("[data-hook='toast']");
  if (!node) {
    node = h("div", { class: "hd-toast", role: "status", "aria-live": "polite", "data-hook": "toast" });
    document.body.appendChild(node);
  }
  node.textContent = text;
  node.removeAttribute("hidden");
  if (toastTimer) clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { node.setAttribute("hidden", ""); toastTimer = null; }, TOAST_MS);
  if (toastTimer && toastTimer.unref) toastTimer.unref();
  return node;
}

/** Share this dog. Returns "shared" | "copied" | "cancelled" | "failed". */
export async function shareDog(hound, id) {
  const url = shareUrl(id || hound.id);
  const data = { title: shareTitle(hound), text: shareMessage(hound), url };
  if (typeof navigator !== "undefined" && typeof navigator.share === "function") {
    try {
      await navigator.share(data);
      return "shared";
    } catch (err) {
      if (err && err.name === "AbortError") return "cancelled";
      // any other failure: fall through to copying the link
    }
  }
  if (await copyText(url)) {
    toast("Link copied. Paste it anywhere.");
    return "copied";
  }
  toast(`Couldn't copy. The link is ${url}`);
  return "failed";
}

// ---- the card -------------------------------------------------------------------------------------------

/** Everything the card says, as plain strings (pure; the drawing only places them). */
export function cardLines(hound) {
  const persona = personaOf(hound);
  const rec = hound.record || {};
  const bets = isNum(rec.bets) ? rec.bets : 0;
  const streak = streakText(hound);
  const status = statusOf(hound);
  return {
    name: hound.name || "A model",
    catchphrase: persona && persona.catchphrase ? `“${persona.catchphrase}”` : (hound.tagline || ""),
    record: bets > 0 ? `${wlText(rec)}` : "0-0",
    recordNote: bets > 0 ? `season record, ${bets} ${bets === 1 ? "bet" : "bets"}` : "no bets yet",
    units: unitsWord(hound),
    streak: streak || "no streak",
    badge: status.text,
    footer: CARD_FOOTER,
  };
}

/** Serialize a (fake or real) SVG element to markup, for drawing the avatar on a canvas. */
export function svgToString(node) {
  const esc = (t) => String(t).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/"/g, "&quot;");
  const walk = (n) => {
    if (n.nodeType === 3) return esc(n.textContent).replace(/&quot;/g, '"');
    const attrs = Object.entries(n.attrs || {}).map(([k, v]) => ` ${k}="${esc(v)}"`).join("");
    const kids = (n.childNodes || []).map(walk).join("");
    return `<${n.localName}${attrs}${kids ? `>${kids}</${n.localName}>` : "/>"}`;
  };
  let out = walk(node);
  if (!/xmlns=/.test(out)) out = out.replace("<svg", '<svg xmlns="http://www.w3.org/2000/svg"');
  return out;
}

/** The initials badge as an SVG string at `size` px. */
export function avatarMarkup(hound, size = 360) {
  const dead = hound.status === "retired";
  const svg = monogramSvg(hound.name, { size, category: categoryOf(hound), muted: dead });
  // a real browser serializes its own SVG (with the namespace); the walker above is for a fake DOM
  return typeof XMLSerializer === "function" ? new XMLSerializer().serializeToString(svg) : svgToString(svg);
}

function wrap(ctx, text, maxWidth) {
  const words = String(text).split(/\s+/).filter(Boolean);
  const lines = [];
  let line = "";
  for (const word of words) {
    const next = line ? `${line} ${word}` : word;
    if (line && ctx.measureText(next).width > maxWidth) { lines.push(line); line = word; } else line = next;
  }
  if (line) lines.push(line);
  return lines;
}

/** Paint the card on `ctx` (a CanvasRenderingContext2D, or anything with the same calls). `avatar` is an
 *  image the context can draw, or null (the card is still complete without it). */
export function drawCard(ctx, hound, avatar) {
  const t = cardLines(hound);
  ctx.fillStyle = "#0A0B0E";
  ctx.fillRect(0, 0, CARD_W, CARD_H);
  ctx.fillStyle = "#2FD07A";
  ctx.fillRect(0, 0, 14, CARD_H);
  ctx.fillStyle = "#111317";
  ctx.fillRect(60, 60, CARD_W - 120, CARD_H - 150);
  if (avatar) ctx.drawImage(avatar, 100, 120, 340, 340);
  const x = 490;
  ctx.textBaseline = "alphabetic";
  ctx.fillStyle = "#8FE9FA";
  ctx.font = "700 26px sans-serif";
  ctx.fillText("LINEHOUND", x, 112);
  ctx.fillStyle = "#F6F7FA";
  ctx.font = "800 72px sans-serif";
  ctx.fillText(t.name, x, 196, CARD_W - x - 90);
  ctx.fillStyle = "#D6DBE4";
  ctx.font = "italic 400 32px sans-serif";
  let y = 248;
  for (const line of wrap(ctx, t.catchphrase, CARD_W - x - 90).slice(0, 2)) { ctx.fillText(line, x, y); y += 40; }
  ctx.fillStyle = "#F6F7FA";
  ctx.font = "800 84px sans-serif";
  ctx.fillText(t.record, x, 372);
  ctx.fillStyle = "#A3A9B5";
  ctx.font = "400 26px sans-serif";
  ctx.fillText(t.recordNote, x, 408);
  ctx.fillStyle = "#F6F7FA";
  ctx.font = "700 40px sans-serif";
  ctx.fillText(t.units, x, 470);
  ctx.fillText(t.streak, x + 420, 470);
  ctx.fillStyle = "#D6DBE4";
  ctx.font = "800 36px sans-serif";
  ctx.fillText(t.badge, x, 530);
  ctx.fillStyle = "#A3A9B5";
  ctx.font = "600 26px sans-serif";
  ctx.fillText(t.footer, 60, CARD_H - 30);
  return t;
}

function loadImage(src) {
  return new Promise((resolve) => {
    try {
      const img = new Image();
      img.onload = () => resolve(img);
      img.onerror = () => resolve(null);
      img.src = src;
    } catch (err) {
      resolve(null);
    }
  });
}

/** Draw the card to a new canvas and hand back a PNG blob (or null). */
export async function makeCardBlob(hound) {
  const canvas = document.createElement("canvas");
  canvas.width = CARD_W;
  canvas.height = CARD_H;
  const ctx = canvas.getContext("2d");
  if (!ctx) return null;
  let avatar = null;
  try {
    avatar = await loadImage(`data:image/svg+xml;charset=utf-8,${encodeURIComponent(avatarMarkup(hound))}`);
  } catch (err) { avatar = null; }
  drawCard(ctx, hound, avatar);
  return new Promise((resolve) => {
    try { canvas.toBlob((blob) => resolve(blob || null), "image/png"); } catch (err) { resolve(null); }
  });
}

/** Download the card as <id>-linehound.png. Returns true when a file was offered. */
export async function downloadCard(hound, id) {
  const blob = await makeCardBlob(hound);
  if (!blob) { toast("Couldn't make the card on this browser."); return false; }
  const url = URL.createObjectURL(blob);
  const a = h("a", { href: url, download: `${String(id || hound.id).replace(/[^A-Za-z0-9_.-]/g, "_")}-linehound.png`,
    "data-hook": "card-download-link" });
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  setTimeout(() => { try { URL.revokeObjectURL(url); } catch (err) { /* nothing to free */ } }, 4000);
  toast("Card saved.");
  return true;
}
