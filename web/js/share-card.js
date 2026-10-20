/**
 * The quiz-result STORY IMAGE: a 1080x1920 PNG a person can post as a story, and the Share button that offers it.
 *
 *   WHAT IT SAYS: the hound's archetype name, the hound itself (the real illustrated rig, drawn from the look the quiz
 *   composed), three trait lines, "Find your hound at linehound.app", and the hard line "21+ · Paper bets · 1-800-GAMBLER".
 *   It never carries a pick or a price: a trait that contains a price (a rule card that says "+120 or better") is left out
 *   rather than shown, and `hasPrice` is the same test the server card uses (src/hounds/share_card.py PRICE_RE).
 *
 *   WHERE IT RUNS: in the browser, on a canvas, nothing uploaded. The dog is the page's own SVG badge (dog-avatar.js
 *   `dogBadge`), serialised with a copy of the shared gradients and the static pose rules (the page's CSS is not inside a
 *   standalone SVG) and drawn onto the canvas as an image. Everything else is `drawStory`, which takes any 2D context so a
 *   test can hand it a recorder, and `storyLines`, which is pure.
 *
 *   SHARE: `navigator.share({files})` when the browser can share a PNG (phones), else a download of the same PNG. A cancelled
 *   share sheet is not an error and shows nothing.
 *
 * THE ONE-LINE IMPORT for the quiz page (web/js/hound-quiz.js; another worker owns that file, so it is not edited here):
 *
 *     import { mountShareButton } from "./share-card.js";
 *     // then, once, when the reveal is on screen (host = any element; S.result is the /hounds/quiz/compose payload):
 *     mountShareButton(q("reveal-dog").parentNode, () => S.result);
 *
 * `mountShareButton(host, getResult)` appends a "Share" button and a polite status line to `host` and returns the button;
 * calling it twice on the same host replaces the first button. `getResult()` may return null (nothing composed yet): the
 * button then says so and does nothing. It reads `result.spec.name`, `result.rule_cards`, `result.look`, `result.breed`
 * and `result.personality`; a caller with its own words can pass `{ archetype, traits, look, breed, id, name }` instead.
 */

import { h } from "./hounds-core.js";
import { dogBadge } from "./dog-avatar.js";

export const STORY_W = 1080;
export const STORY_H = 1920;
export const STORY_FOOTER = "21+ · Paper bets · 1-800-GAMBLER";
export const STORY_CTA = "Find your hound at linehound.app";
export const SHARE_LABEL = "Share";
export const MAX_TRAITS = 3;
export const FILE_NAME = "my-linehound.png";
const SVG_NS = "http://www.w3.org/2000/svg";
const DEFS_ID = "lh-dog-defs";
const ART_PX = 720;
/** Labels the composer uses when it has nothing specific to say; not a trait worth putting on an image. */
const GENERIC_LABELS = new Set(["your style", "your words", "your picks", "a rule"]);
/** The pose rules of web/css/lh.css (the static ones, no animation): a standalone SVG does not carry the page's CSS. */
const POSE_CSS = [
  ".dk-badge .dk-p{display:none}.dk-badge .dk-paws{display:none}",
  '.dk-badge[data-pose="idle"] .dk-p--mouth.dk-p--idle,.dk-badge[data-pose="happy"] .dk-p--mouth.dk-p--happy,',
  '.dk-badge[data-pose="sad"] .dk-p--mouth.dk-p--sad,.dk-badge[data-pose="thinking"] .dk-p--mouth.dk-p--thinking,',
  '.dk-badge[data-pose="celebrate"] .dk-p--mouth.dk-p--celebrate{display:inline}',
  '.dk-badge[data-pose="idle"] .dk-p--eyes.dk-p--open,.dk-badge[data-pose="happy"] .dk-p--eyes.dk-p--happy,',
  '.dk-badge[data-pose="celebrate"] .dk-p--eyes.dk-p--celebrate,.dk-badge[data-pose="sad"] .dk-p--eyes.dk-p--sad,',
  '.dk-badge[data-pose="thinking"] .dk-p--eyes.dk-p--thinking{display:inline}',
  '.dk-badge[data-pose="happy"] .dk-p--gleam,.dk-badge[data-pose="celebrate"] .dk-p--sparkles{display:inline}',
].join("");

// ---- the words (pure) ------------------------------------------------------------------------------------------

/** An American price: a sign and three or four digits not glued to a word or a number ("-110", "+1500"). */
export function hasPrice(text) {
  return /(^|[^\w$.,])[+\-−]\d{3,4}(?!\d)/.test(String(text === undefined || text === null ? "" : text));
}

function clean(text, limit) {
  const s = String(text === undefined || text === null ? "" : text).replace(/\s+/g, " ").trim();
  return s.length > limit ? `${s.slice(0, limit - 1).trimEnd()}...` : s;
}

/** Everything the story says, as plain strings (pure; the drawing only places them). */
export function storyLines(result) {
  const r = result && typeof result === "object" ? result : {};
  const cards = Array.isArray(r.rule_cards) ? r.rule_cards : [];
  const personality = cards.find((c) => c && c.source === "personality" && c.label);
  const archetype = clean(r.archetype || (personality && personality.label) || (r.spec && r.spec.name) || r.name || "Your hound", 40);
  let pool = Array.isArray(r.traits) ? r.traits.map((t) => String(t)) : cards.map((c) => (c && c.label) || "");
  if (!Array.isArray(r.traits)) pool = pool.concat(Array.isArray(r.sentences) ? r.sentences : []);
  const seen = new Set([archetype.toLowerCase()]);
  const traits = [];
  for (const raw of pool) {
    const t = clean(raw, 64);
    const key = t.toLowerCase();
    if (!t || seen.has(key) || GENERIC_LABELS.has(key) || hasPrice(t)) continue;
    seen.add(key);
    traits.push(t);
    if (traits.length >= MAX_TRAITS) break;
  }
  return { archetype, traits, cta: STORY_CTA, footer: STORY_FOOTER, wordmark: "LINEHOUND", eyebrow: "YOUR HOUND" };
}

// ---- the picture -----------------------------------------------------------------------------------------------

function wrap(ctx, text, maxWidth, maxLines) {
  const words = String(text).split(/\s+/).filter(Boolean);
  const lines = [];
  let line = "";
  for (const word of words) {
    const next = line ? `${line} ${word}` : word;
    if (line && ctx.measureText(next).width > maxWidth) { lines.push(line); line = word; } else line = next;
  }
  if (line) lines.push(line);
  return lines.slice(0, maxLines);
}

const DISPLAY = '"Barlow Condensed", "Arial Narrow", sans-serif';
const BODY = '"Instrument Sans", -apple-system, "Segoe UI", sans-serif';

/** The hard line, its three parts spaced evenly around a dot (a font's own middle dot hugs the words). */
function drawFooter(ctx, text, mid, y) {
  const parts = String(text).split("·").map((p) => p.trim());
  const gap = 40;
  const widths = parts.map((p) => ctx.measureText(p).width);
  const total = widths.reduce((a, b) => a + b, 0) + gap * (parts.length - 1);
  let x = mid - total / 2;
  ctx.textAlign = "left";
  parts.forEach((part, i) => {
    ctx.fillText(part, x, y);
    x += widths[i];
    if (i < parts.length - 1) { ctx.fillRect(x + gap / 2 - 3, y - 12, 6, 6); x += gap; }
  });
  ctx.textAlign = "center";
}

/** Paint the story on `ctx` (a CanvasRenderingContext2D, or anything with the same calls). `art` is an image the context can
 *  draw, or null: the story is complete without it. Returns the lines it placed. */
export function drawStory(ctx, lines, art) {
  const mid = STORY_W / 2;
  const grad = ctx.createLinearGradient ? ctx.createLinearGradient(0, 0, 0, STORY_H) : null;
  if (grad) { grad.addColorStop(0, "#14203A"); grad.addColorStop(0.55, "#0B0C0E"); grad.addColorStop(1, "#0B0C0E"); }
  ctx.fillStyle = grad || "#0B0C0E";
  ctx.fillRect(0, 0, STORY_W, STORY_H);
  ctx.textAlign = "center";
  ctx.textBaseline = "alphabetic";
  ctx.fillStyle = "#2FD07A";
  ctx.font = `700 54px ${DISPLAY}`;
  ctx.fillText(lines.wordmark.split("").join(" "), mid, 150);
  ctx.fillRect(mid - 40, 178, 80, 5);
  if (art) ctx.drawImage(art, (STORY_W - ART_PX) / 2, 250, ART_PX, ART_PX);
  ctx.fillStyle = "#8A919E";
  ctx.font = `600 34px ${BODY}`;
  ctx.fillText(lines.eyebrow, mid, 1060);
  ctx.fillStyle = "#F6F7FA";
  ctx.font = `700 132px ${DISPLAY}`;
  let y = 1190;
  for (const line of wrap(ctx, lines.archetype, STORY_W - 160, 2)) { ctx.fillText(line, mid, y); y += 128; }
  ctx.font = `500 48px ${BODY}`;
  ctx.fillStyle = "#D6DBE4";
  y = Math.max(y + 40, 1420);
  for (const trait of lines.traits) {
    ctx.fillStyle = "#2FD07A";
    ctx.fillRect(110, y - 30, 18, 18);
    ctx.fillStyle = "#D6DBE4";
    ctx.textAlign = "left";
    for (const part of wrap(ctx, trait, STORY_W - 260, 1)) ctx.fillText(part, 150, y);
    ctx.textAlign = "center";
    y += 82;
  }
  ctx.fillStyle = "#F6F7FA";
  ctx.font = `700 56px ${DISPLAY}`;
  ctx.fillText(lines.cta, mid, 1770);
  ctx.fillStyle = "#6F7682";
  ctx.fillRect(110, 1806, STORY_W - 220, 2);
  ctx.fillStyle = "#8A919E";
  ctx.font = `500 30px ${BODY}`;
  drawFooter(ctx, lines.footer, mid, 1864);
  return lines;
}

/** The dog's badge as a standalone SVG string: its own markup, the shared gradients inside it, the static pose rules. */
export function badgeMarkup(look, opts = {}) {
  const svg = dogBadge(look, { size: ART_PX, mood: "happy", decorative: true, breed: opts.breed, id: opts.id, name: opts.name });
  const clone = svg.cloneNode(true);
  clone.setAttribute("xmlns", SVG_NS);
  clone.setAttribute("width", String(ART_PX));
  clone.setAttribute("height", String(ART_PX));
  const shared = typeof document !== "undefined" && document.getElementById ? document.getElementById(DEFS_ID) : null;
  if (shared && !clone.querySelector("defs")) {
    const defs = shared.querySelector("defs");
    if (defs) clone.insertBefore(defs.cloneNode(true), clone.firstChild);
  }
  const style = document.createElementNS(SVG_NS, "style");
  style.textContent = POSE_CSS;
  clone.insertBefore(style, clone.firstChild);
  return new XMLSerializer().serializeToString(clone);
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

async function fontsReady() {
  try {
    if (document.fonts && document.fonts.load) {
      await Promise.all([document.fonts.load(`700 120px ${DISPLAY}`), document.fonts.load(`500 40px ${BODY}`)]);
    }
  } catch (err) { /* the fallback faces draw instead */ }
}

/** Draw the story to a new canvas and hand back a PNG blob (or null). */
export async function makeStoryBlob(result) {
  const lines = storyLines(result);
  const canvas = document.createElement("canvas");
  canvas.width = STORY_W;
  canvas.height = STORY_H;
  const ctx = canvas.getContext("2d");
  if (!ctx) return null;
  await fontsReady();
  let art = null;
  const r = result && typeof result === "object" ? result : {};
  if (r.look) {
    try {
      art = await loadImage(`data:image/svg+xml;charset=utf-8,${encodeURIComponent(badgeMarkup(r.look, { breed: r.breed, id: r.id, name: r.name || (r.spec && r.spec.name) }))}`);
    } catch (err) { art = null; }
  }
  drawStory(ctx, lines, art);
  return new Promise((resolve) => {
    try { canvas.toBlob((blob) => resolve(blob || null), "image/png"); } catch (err) { resolve(null); }
  });
}

// ---- share or download -----------------------------------------------------------------------------------------

function download(blob, doc) {
  const url = URL.createObjectURL(blob);
  const a = doc.createElement("a");
  a.setAttribute("href", url);
  a.setAttribute("download", FILE_NAME);
  a.setAttribute("data-hook", "story-download-link");
  doc.body.appendChild(a);
  a.click();
  doc.body.removeChild(a);
  setTimeout(() => { try { URL.revokeObjectURL(url); } catch (err) { /* nothing to free */ } }, 4000);
}

/** Share the story image: the share sheet with the PNG when the browser can, else a download.
 *  Returns "shared" | "downloaded" | "cancelled" | "failed". */
export async function shareStory(result, { nav = typeof navigator !== "undefined" ? navigator : null, doc = typeof document !== "undefined" ? document : null, blob = null } = {}) {
  const png = blob || await makeStoryBlob(result);
  if (!png) return "failed";
  if (nav && typeof nav.share === "function" && typeof nav.canShare === "function" && typeof File === "function") {
    try {
      const file = new File([png], FILE_NAME, { type: "image/png" });
      if (nav.canShare({ files: [file] })) {
        await nav.share({ files: [file], title: "My LINEHOUND", text: STORY_CTA });
        return "shared";
      }
    } catch (err) {
      if (err && err.name === "AbortError") return "cancelled";
      // any other failure: fall through to the download
    }
  }
  if (!doc) return "failed";
  download(png, doc);
  return "downloaded";
}

const STATUS = { shared: "", downloaded: "Saved. Post it from your photos.", cancelled: "", failed: "Couldn't make the image on this browser." };

/** Add the Share button (and its status line) to `host`. `getResult()` returns the composed quiz result, or null. */
export function mountShareButton(host, getResult) {
  const old = host.querySelector ? host.querySelector("[data-hook='story-share']") : null;
  if (old && old.parentNode) old.parentNode.removeChild(old);
  const oldStatus = host.querySelector ? host.querySelector("[data-hook='story-share-status']") : null;
  if (oldStatus && oldStatus.parentNode) oldStatus.parentNode.removeChild(oldStatus);
  const status = h("span", { class: "qz-share-status", role: "status", "aria-live": "polite", "data-hook": "story-share-status" });
  const button = h("button", { type: "button", class: "qz-btn qz-btn--ghost", "data-hook": "story-share", text: SHARE_LABEL });
  button.addEventListener("click", async () => {
    const result = typeof getResult === "function" ? getResult() : null;
    if (!result) { status.textContent = "Your hound is still loading."; return; }
    button.disabled = true;
    status.textContent = "";
    try {
      const outcome = await shareStory(result);
      status.textContent = STATUS[outcome] || "";
    } finally {
      button.disabled = false;
    }
  });
  host.appendChild(button);
  host.appendChild(status);
  return button;
}
