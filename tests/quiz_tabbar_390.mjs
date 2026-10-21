// Drives a headless Chrome over the DevTools protocol at 390x844 (a phone) on the quiz's Q3 "Pick its personality." page 2 with the
// Gematria card picked, and reports whether the fixed phone tab bar covers the "Show me others" pill or the Back / Skip / Next row.
// Used by tests/test_quiz_tabbar_clear.py.   node quiz_tabbar_390.mjs <chromePath> <url>     prints one JSON object on the last line
import { spawn } from "node:child_process";
import os from "node:os";
import path from "node:path";

const [chromePath, url] = process.argv.slice(2);
const port = 9900 + Math.floor(Math.random() * 90);
const profile = path.join(os.tmpdir(), `lh-quizbar-${process.pid}-${port}`);
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
await send("Page.enable");
await send("Emulation.setDeviceMetricsOverride", { width: 390, height: 844, deviceScaleFactor: 1, mobile: true });
await send("Page.navigate", { url });
await sleep(2500);
const out = await ev(`(async () => {
  const w = (ms) => new Promise((r) => setTimeout(r, ms));
  const q = (h) => document.querySelector("[data-hook='" + h + "']");
  q("quiz-skip").click(); await w(700); q("quiz-skip").click(); await w(1500);
  q("quiz-personality-more").click(); await w(900);
  document.querySelector("[data-hook='quiz-card'][data-group='personality'][data-id='gematria']").click(); await w(900);
  const els = { more: q("quiz-personality-more"), back: q("quiz-back"), skip: q("quiz-skip"), next: q("quiz-next") };
  const bar = document.querySelector(".lh-tabbar");
  const barH = bar && getComputedStyle(bar).display !== "none" ? bar.getBoundingClientRect().height : 0;
  const probe = () => { const row = {}; for (const [k, e] of Object.entries(els)) {
    const b = e.getBoundingClientRect(); const cx = (b.left + b.right) / 2, cy = (b.top + b.bottom) / 2;
    const top = cy >= 0 && cy <= innerHeight ? document.elementFromPoint(cx, cy) : null;
    row[k] = !!top && (top === e || e.contains(top)); } return row; };
  const max = document.documentElement.scrollHeight - innerHeight;
  let clearAt = null;
  for (let y = 0; y <= max; y += 20) { scrollTo(0, y); await w(30); const r = probe(); if (Object.values(r).every(Boolean)) { clearAt = y; break; } }
  scrollTo(0, max); await w(200);
  return { iw: innerWidth, bar: Math.round(barH), pad: parseFloat(getComputedStyle(document.body).paddingBottom), max, clearAt, atEnd: probe(),
           sw: document.documentElement.scrollWidth };
})()`);
console.log(JSON.stringify(out));
ws.close();
chrome.kill();
process.exit(0);
