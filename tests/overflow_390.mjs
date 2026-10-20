// Drives a headless Chrome over the DevTools protocol (node 22+ has WebSocket built in) and reports, for every URL given, whether the
// page scrolls sideways at 390 px wide. Used by tests/test_no_horizontal_overflow.py.
//   node overflow_390.mjs <chromePath> <baseUrl> <path> [<path> ...]    prints one JSON array on the last line
import { spawn } from "node:child_process";
import os from "node:os";
import path from "node:path";

const [chromePath, base, ...paths] = process.argv.slice(2);
const port = 9600 + Math.floor(Math.random() * 300);
const profile = path.join(os.tmpdir(), `lh-overflow-${process.pid}-${port}`);
const chrome = spawn(chromePath, ["--headless=new", `--remote-debugging-port=${port}`, `--user-data-dir=${profile}`, "--no-first-run",
  "--disable-gpu", "--hide-scrollbars", "about:blank"], { stdio: "ignore" });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function target() {
  for (let i = 0; i < 80; i++) {
    try {
      const r = await fetch(`http://127.0.0.1:${port}/json/new?about:blank`, { method: "PUT" });
      return (await r.json()).webSocketDebuggerUrl;
    } catch (e) { await sleep(250); }
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

await send("Page.enable");
await send("Emulation.setDeviceMetricsOverride", { width: 390, height: 844, deviceScaleFactor: 1, mobile: true });
const out = [];
for (const p of paths) {
  await send("Page.navigate", { url: base + p });
  await sleep(2200);
  await ev(`(async()=>{const H=document.documentElement.scrollHeight;for(let y=0;y<H;y+=600){window.scrollTo(0,y);await new Promise(r=>setTimeout(r,40));}window.scrollTo(0,0);})()`);
  await sleep(500);
  out.push(Object.assign({ path: p }, await ev(`(()=>{
    const iw = window.innerWidth, sw = document.documentElement.scrollWidth;
    const wide = [];
    if (sw > iw + 1) for (const el of document.querySelectorAll("body *")) { const r = el.getBoundingClientRect(); if (r.width && r.right > iw + 1 && getComputedStyle(el).position !== "fixed") { wide.push((el.tagName + "." + String(el.className).slice(0, 40))); if (wide.length > 5) break; } }
    // the phone tab bar and the room the page leaves above it (round 2, 2026-10-19): the last piece of content must end above the bar
    const bar = document.querySelector(".lh-tabbar");
    const barH = bar && getComputedStyle(bar).display !== "none" ? bar.getBoundingClientRect().height : 0;
    let lastBottom = 0;
    for (const el of document.body.querySelectorAll("*")) {
      if (bar && bar.contains(el)) continue;
      const cs = getComputedStyle(el);
      if (cs.position === "fixed" || cs.display === "none" || cs.visibility === "hidden") continue;
      const r = el.getBoundingClientRect();
      if (r.width > 0 && r.height > 0) lastBottom = Math.max(lastBottom, r.bottom + window.scrollY);
    }
    const docH = document.documentElement.scrollHeight;
    return { iw, sw, wide, h: docH, bar: Math.round(barH), pad: parseFloat(getComputedStyle(document.body).paddingBottom), clear: Math.round(docH - lastBottom) };
  })()`)));
}
console.log(JSON.stringify(out));
ws.close();
chrome.kill();
process.exit(0);
