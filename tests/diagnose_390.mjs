// Drives a headless Chrome through the diagnosis phase of Send to training at 390 px wide, measuring sideways overflow on the way
// through, then the evolution that follows it. Used by tests/test_dog_diagnose.py.
//   node diagnose_390.mjs <chromePath> <baseUrl> <outDir|-> [full|reduced]     prints one JSON object on the last line
// The pacing of the page is sped up (dog-diagnose.js exports its TIMING object) so a run takes seconds, not half a minute; the
// layout under test is the same.
import { spawn } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

const [chromePath, base, outDir, mode = "full"] = process.argv.slice(2);
const port = 9700 + Math.floor(Math.random() * 20000);
const profile = path.join(os.tmpdir(), `lh-diagnose-${process.pid}-${port}`);
const chrome = spawn(chromePath, ["--headless=new", `--remote-debugging-port=${port}`, `--user-data-dir=${profile}`, "--no-first-run",
  "--disable-gpu", "--hide-scrollbars", "about:blank"], { stdio: "ignore" });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function target() {
  for (let i = 0; i < 80; i++) {
    try { const r = await fetch(`http://127.0.0.1:${port}/json/new?about:blank`, { method: "PUT" }); return (await r.json()).webSocketDebuggerUrl; }
    catch (e) { await sleep(250); }
  }
  throw new Error("chrome did not start");
}
const ws = new WebSocket(await target());
await new Promise((r) => (ws.onopen = r));
let id = 0;
const pending = new Map();
const errors = [];
ws.onmessage = (m) => {
  const d = JSON.parse(m.data);
  if (d.id && pending.has(d.id)) { pending.get(d.id)(d); pending.delete(d.id); }
  else if (d.method === "Runtime.exceptionThrown") errors.push(String(d.params.exceptionDetails.exception?.description || d.params.exceptionDetails.text).slice(0, 300));
  else if (process.env.DIAG_DEBUG && d.method === "Runtime.consoleAPICalled") console.error("console", d.params.type, JSON.stringify(d.params.args.map((a) => a.value || a.description)).slice(0, 300));
};
const send = (method, params = {}) => new Promise((res) => { const i = ++id; pending.set(i, res); ws.send(JSON.stringify({ id: i, method, params })); });
const ev = async (expression) => (await send("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true })).result.result?.value;

await send("Page.enable");
await send("Runtime.enable");
await send("Emulation.setDeviceMetricsOverride", { width: 390, height: 844, deviceScaleFactor: 1, mobile: true });
if (mode === "reduced") await send("Emulation.setEmulatedMedia", { features: [{ name: "prefers-reduced-motion", value: "reduce" }] });
await send("Page.addScriptToEvaluateOnNewDocument", { source: `try{localStorage.setItem("aisportsanalysis.invite_token","tok")}catch(e){}` });
await send("Page.navigate", { url: base + "/web/kennel.html" });
for (let i = 0; i < 120; i++) { if (await ev(`!!document.querySelector("[data-hook='dog-action-train']")`)) break; await sleep(300); }
await sleep(400);
if (mode !== "reduced") {
  // shorten the page's own pacing (the same module object the page imports), keeping every beat
  await ev(`import("/web/js/dog-diagnose.js").then((m) => { Object.assign(m.TIMING, { rowTarget: 2400, rowMin: 50, rowMax: 110, pending: 40, askMin: 500, reasonGap: 500, hold: 900, skipAfter: 600 }); return true; })`);
}
await ev(`document.querySelector("[data-hook='dog-action-train']").click()`);
for (let i = 0; i < 100; i++) { if (await ev(`!!document.querySelector("[data-hook='training-go']")`)) break; await sleep(100); }
await ev(`document.querySelector("[data-hook='training-go']").click()`);
const measure = () => ev(`(() => {
  const sheet = document.querySelector(".rt-sheet");
  const dx = document.querySelector(".dx");
  const wide = [];
  for (const el of document.querySelectorAll(".rt-layer *")) { const r = el.getBoundingClientRect(); if (r.width && r.right > innerWidth + 1 && !el.closest(".ev-rays, .ev-shock, .ev-ripple, .ev-flash, .ev-stage, .dx-beam")) { wide.push(el.tagName + "." + String(el.className && el.className.baseVal !== undefined ? el.className.baseVal : el.className).slice(0, 30)); if (wide.length > 4) break; } }
  const layer = document.querySelector(".rt-layer");
  const phase = dx ? dx.getAttribute("data-phase") : (layer ? layer.getAttribute("data-phase") : "");
  return { phase, lines: document.querySelectorAll(".dx-line").length, sw: document.documentElement.scrollWidth, iw: innerWidth,
    sheetSw: sheet ? sheet.scrollWidth : 0, sheetCw: sheet ? sheet.clientWidth : 0, wide };
})()`);
const samples = [];
const t0 = Date.now();
let sawEnd = false;
let continued = false;
let maxLines = 0;
while (Date.now() - t0 < 70000) {
  const m = await measure();
  samples.push(m);
  maxLines = Math.max(maxLines, m.lines || 0);
  if (outDir !== "-" && m.phase && !fs.existsSync(path.join(outDir, m.phase + ".png"))) {
    fs.mkdirSync(outDir, { recursive: true });
    const s = await send("Page.captureScreenshot", { format: "png" });
    fs.writeFileSync(path.join(outDir, m.phase + ".png"), Buffer.from(s.result.data, "base64"));
  }
  // after the diagnosis the proposal is reviewed: measure it once at this width, then stop (nothing is applied here)
  if (await ev(`!!document.querySelector("[data-hook='review-apply']")`)) { sawEnd = true; await sleep(300); samples.push(await measure()); samples[samples.length - 1].phase = "review"; break; }
  if (m.phase === "static" && !continued) { await sleep(500); continued = true; await ev(`document.querySelector("[data-hook='diagnose-continue']").click()`); continue; }
  if (m.phase === "card" || m.phase === "static") { if (m.phase === "static" && !(await ev(`!document.querySelector(".dx")`))) { if (sawEnd) break; sawEnd = true; await sleep(1500); continue; } if (m.phase === "card") { if (sawEnd) break; sawEnd = true; await sleep(1500); continue; } }
  await sleep(120);
}
if (process.env.DIAG_DEBUG) console.error(await ev(`document.querySelector('.rt-layer') ? document.querySelector('.rt-layer').outerHTML.slice(0, 1500) : 'no layer'`));
console.log(JSON.stringify({ samples, errors, phases: [...new Set(samples.map((s) => s.phase))], lines: maxLines }));
ws.close();
chrome.kill();
process.exit(0);
