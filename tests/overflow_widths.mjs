// Drives a headless Chrome over the DevTools protocol at several widths (375, 390, 1440) and reports, for every page given, whether it scrolls
// sideways; for the quiz it also walks all four steps and the reveal. Used by tests/test_no_horizontal_overflow.py (owner ruling 2026-10-21).
//   node overflow_widths.mjs <chromePath> <baseUrl> <widths comma list> <path> [<path> ...]   prints one JSON array on the last line
// A path may end in "#signed" (a member token is stored first) or "#quiz" (the four steps and the reveal are driven and measured too).
import { spawn } from "node:child_process";
import os from "node:os";
import path from "node:path";

const [chromePath, base, widthList, ...paths] = process.argv.slice(2);
const widths = widthList.split(",").map(Number);
const port = 9400 + Math.floor(Math.random() * 190);
const profile = path.join(os.tmpdir(), `lh-widths-${process.pid}-${port}`);
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
  if (sw > iw + 1) for (const el of document.querySelectorAll("body *")) { const r = el.getBoundingClientRect(); if (r.width && r.right > iw + 1 && getComputedStyle(el).position !== "fixed") { wide.push(el.tagName + "." + String(el.className).slice(0, 40)); if (wide.length > 5) break; } }
  return { iw, sw, wide, h: document.documentElement.scrollHeight }; })()`;

// the four steps and the reveal, driven the way a person drives them
const STEPS = `(async()=>{ const w = (ms) => new Promise((r) => setTimeout(r, ms)); const out = []; const q = (h) => document.querySelector("[data-hook='" + h + "']");
  const m = () => ${MEASURE};
  await w(900); out.push(Object.assign({ step: "sports" }, m()));
  document.querySelector("[data-hook='quiz-card'][data-group='sports'][data-id='MLB']").click(); await w(200); q("quiz-next").click(); await w(900);
  out.push(Object.assign({ step: "personality" }, m()));
  document.querySelector("[data-hook='quiz-card'][data-group='personality'][data-id='gematria']").click(); await w(200); q("quiz-next").click(); await w(900);
  out.push(Object.assign({ step: "risk" }, m()));
  q("quiz-next").click(); await w(900);
  out.push(Object.assign({ step: "finish" }, m()));
  q("quiz-next").click(); await w(3500);
  out.push(Object.assign({ step: "reveal" }, m()));
  return out; })()`;

const out = [];
for (const width of widths) {
  const height = width < 700 ? 844 : 900;
  await send("Page.enable");
  await send("Emulation.setDeviceMetricsOverride", { width, height, deviceScaleFactor: 1, mobile: width < 700 });
  for (const raw of paths) {
    const signed = raw.includes("#signed"), quiz = raw.includes("#quiz");
    const p = raw.replace("#signed", "").replace("#quiz", "");
    await send("Page.navigate", { url: base + "/web/landing.html?stay=1" });
    await sleep(600);
    await ev(`try { ${signed ? `localStorage.setItem(${JSON.stringify(KEY)}, "tok")` : `localStorage.removeItem(${JSON.stringify(KEY)}); localStorage.removeItem("linehound.quiz.draft.v1")`} } catch (e) {}`);
    await send("Page.navigate", { url: base + p });
    await sleep(2200);
    if (quiz) for (const s of await ev(STEPS)) out.push(Object.assign({ path: p, width, signed }, s));
    else out.push(Object.assign({ path: p, width, signed, step: "" }, await ev(MEASURE)));
  }
}
console.log(JSON.stringify(out));
ws.close();
chrome.kill();
process.exit(0);
