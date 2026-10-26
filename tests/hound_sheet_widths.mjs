// Drives a headless Chrome over the DevTools protocol at several widths and, for every "<dogId>:<tab>" given, opens My Kennel's hound sheet on that
// tab (web/kennel.html?dog=..&tab=..) signed in, then reports whether anything scrolls sideways and whether the header is whole. With a shots
// directory it also writes a PNG per width and tab. Used by tests/test_hound_sheet_widths.py (owner, 2026-10-26: the hound detail view).
//   node hound_sheet_widths.mjs <chromePath> <baseUrl> <widths comma list> <shotsDir or -> <shotPrefix> <dogId:tab> [<dogId:tab> ...]
import { spawn } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

const [chromePath, base, widthList, shotsDir, prefix, ...jobs] = process.argv.slice(2);
const widths = widthList.split(",").map(Number);
const port = 9600 + Math.floor(Math.random() * 190);
const profile = path.join(os.tmpdir(), `lh-sheet-${process.pid}-${port}`);
const chrome = spawn(chromePath, ["--headless=new", `--remote-debugging-port=${port}`, `--user-data-dir=${profile}`, "--no-first-run",
  "--disable-gpu", "--hide-scrollbars", "about:blank"], { stdio: "ignore" });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function target() {
  for (let i = 0; i < 80; i++) {
    try { return (await (await fetch(`http://127.0.0.1:${port}/json/new?about:blank`, { method: "PUT" })).json()).webSocketDebuggerUrl; } catch (e) { await sleep(250); }
  }
  throw new Error("chrome did not start");
}
const ws = new WebSocket(await target());
await new Promise((r) => (ws.onopen = r));
let id = 0;
const pending = new Map();
ws.onmessage = (m) => { const d = JSON.parse(m.data); if (d.id && pending.has(d.id)) { pending.get(d.id)(d); pending.delete(d.id); } };
const send = (method, params = {}) => new Promise((res) => { const i = ++id; pending.set(i, res); ws.send(JSON.stringify({ id: i, method, params })); });
const ev = async (expression) => (await send("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true })).result.result.value;
const KEY = "aisportsanalysis.invite_token";

const MEASURE = `(()=>{ const iw = window.innerWidth, sw = document.documentElement.scrollWidth; const wide = [];
  const studio = document.querySelector("[data-hook='studio']");
  const inside = studio ? Array.from(studio.querySelectorAll("*")) : [];
  const clipped = (el) => { for (let n = el.parentElement; n && n !== studio; n = n.parentElement) { if (n.classList.contains("kn-studio__body")) continue; const o = getComputedStyle(n).overflowX; if (o !== "visible") return true; } return false; };
  for (const el of inside) { if (el instanceof SVGElement || clipped(el)) continue; const r = el.getBoundingClientRect(); if (r.width && r.right > iw + 1 && getComputedStyle(el).position !== "fixed") { wide.push(el.tagName + "." + String(el.className).slice(0, 40)); if (wide.length > 5) break; } }
  const title = document.querySelector("[data-hook='studio-title']");
  const sub = document.querySelector("[data-hook='studio-sub']");
  const cut = (el) => !!el && (el.scrollWidth > el.clientWidth + 1 || getComputedStyle(el).textOverflow === "ellipsis");
  const tabs = document.querySelector("[data-hook='studio-tabs']");
  const active = tabs ? tabs.querySelector("[aria-selected='true']") : null;
  let activeVisible = null;
  if (tabs && active) { const a = active.getBoundingClientRect(), t = tabs.getBoundingClientRect(); activeVisible = a.left >= t.left - 1 && a.right <= t.right + 1; }
  const body = studio ? studio.querySelector(".kn-studio__body") : null;
  return { iw, sw, wide, h: document.documentElement.scrollHeight, studioOpen: !!studio && !studio.hidden,
    studioSw: studio ? studio.scrollWidth : 0, studioCw: studio ? studio.clientWidth : 0, bodySw: body ? body.scrollWidth : 0, bodyCw: body ? body.clientWidth : 0,
    title: title ? title.textContent : "", titleCut: cut(title), subCut: cut(sub), tabsSw: tabs ? tabs.scrollWidth : 0, tabsCw: tabs ? tabs.clientWidth : 0, activeVisible,
    tabsPos: tabs ? getComputedStyle(tabs).position : "", moreHidden: !!document.querySelector("[data-hook='studio-more']") && document.querySelector("[data-hook='studio-more']").hidden }; })()`;

const out = [];
if (shotsDir && shotsDir !== "-") fs.mkdirSync(shotsDir, { recursive: true });
for (const width of widths) {
  const height = width < 700 ? 844 : 900;
  await send("Page.enable");
  await send("Emulation.setDeviceMetricsOverride", { width, height, deviceScaleFactor: 1, mobile: width < 700 });
  for (const job of jobs) {
    const [dog, tab] = job.split(":");
    await send("Page.navigate", { url: base + "/web/landing.html?stay=1" });
    await sleep(500);
    await ev(`try { localStorage.setItem(${JSON.stringify(KEY)}, "tok"); localStorage.setItem("linehound.unit_size", JSON.stringify({ mode: "fixed", unit_usd: 25, pct: null, start_usd: 2500 })); } catch (e) {}`);
    await send("Page.navigate", { url: `${base}/web/kennel.html?dog=${dog}&tab=${tab === "rules-edit" ? "rules" : tab}` });
    await sleep(tab === "backtest" || tab === "fire" ? 3200 : 2400);
    if (tab === "rules-edit") await ev(`(document.querySelector("[data-hook='studio-edit-rules']") || {click(){}}).click()`);
    out.push(Object.assign({ path: job, width }, await ev(MEASURE)));
    if (shotsDir && shotsDir !== "-") {
      const shot = await send("Page.captureScreenshot", { format: "png" });
      fs.writeFileSync(path.join(shotsDir, `${prefix}_${dog}_${tab}_${width}.png`), Buffer.from(shot.result.data, "base64"));
    }
  }
}
console.log(JSON.stringify(out));
ws.close();
chrome.kill();
process.exit(0);
