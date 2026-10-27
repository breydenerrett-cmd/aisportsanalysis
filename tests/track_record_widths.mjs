// Drives a headless Chrome at several widths over web/record.html (against a local stub that answers GET /hounds/{id}/record) and reports
// whether the page scrolls sideways. With a shots directory it also writes a full-page PNG per width. Used by tests/test_track_record_widths.py.
//   node track_record_widths.mjs <chromePath> <baseUrl> <widths comma list> <shotsDir or -> <shotPrefix> <path> [<path> ...]
import { spawn } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

const [chromePath, base, widthList, shotsDir, prefix, ...paths] = process.argv.slice(2);
const widths = widthList.split(",").map(Number);
const port = 9800 + Math.floor(Math.random() * 190);
const profile = path.join(os.tmpdir(), `lh-record-${process.pid}-${port}`);
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

const MEASURE = `(()=>{ const iw = window.innerWidth, sw = document.documentElement.scrollWidth; const wide = [];
  if (sw > iw + 1) for (const el of document.querySelectorAll("body *")) { const r = el.getBoundingClientRect(); if (r.width && r.right > iw + 1 && getComputedStyle(el).position !== "fixed") { wide.push(el.tagName + "." + String(el.className).slice(0, 40)); if (wide.length > 5) break; } }
  const body = document.querySelector("[data-hook='record-body']");
  const cut = [];
  for (const el of document.querySelectorAll(".rc-wrap h1, .rc-ticket__pick, .rc-cut__label, .rc-cutline, .rc-ticket__why")) { if (el.scrollWidth > el.clientWidth + 1) cut.push(el.className || el.tagName); }
  return { iw, sw, wide, cut, h: document.documentElement.scrollHeight, bodyShown: !!body && !body.hidden,
    title: (document.querySelector("[data-hook='record-title']") || {}).textContent || "",
    cards: document.querySelectorAll(".rc-cutcard").length, tickets: document.querySelectorAll("[data-hook='ticket']").length,
    months: document.querySelectorAll("[data-hook='cal-month']").length, svgs: document.querySelectorAll(".rc-curve svg").length }; })()`;

const out = [];
if (shotsDir && shotsDir !== "-") fs.mkdirSync(shotsDir, { recursive: true });
for (const width of widths) {
  const height = width < 700 ? 844 : 900;
  await send("Page.enable");
  await send("Emulation.setDeviceMetricsOverride", { width, height, deviceScaleFactor: 1, mobile: width < 700 });
  for (const p of paths) {
    await send("Page.navigate", { url: base + p });
    await sleep(2600);
    const m = await ev(MEASURE);
    out.push(Object.assign({ path: p, width }, m));
    if (shotsDir && shotsDir !== "-") {
      const shot = await send("Page.captureScreenshot", { format: "png", captureBeyondViewport: true, clip: { x: 0, y: 0, width, height: Math.min(m.h, 2600), scale: 1 } });
      const name = p.replace(/[^a-z0-9]+/gi, "_").replace(/^_|_$/g, "");
      fs.writeFileSync(path.join(shotsDir, `${prefix}_${name}_${width}.png`), Buffer.from(shot.result.data, "base64"));
    }
  }
}
console.log(JSON.stringify(out));
ws.close();
chrome.kill();
process.exit(0);
