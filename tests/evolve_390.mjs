// Drives a headless Chrome and plays the training evolution at 390 px wide, measuring sideways overflow on the way through.
// Used by tests/test_dog_evolve.py.
//   node evolve_390.mjs <chromePath> <baseUrl> <outDir|-> [full|reduced] [width=390]     prints one JSON object on the last line
import { spawn } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

const [chromePath, base, outDir, mode = "full", widthArg = "390"] = process.argv.slice(2);
const port = 9700 + Math.floor(Math.random() * 20000);
const profile = path.join(os.tmpdir(), `lh-evolve-${process.pid}-${port}`);
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
};
const send = (method, params = {}) => new Promise((res) => { const i = ++id; pending.set(i, res); ws.send(JSON.stringify({ id: i, method, params })); });
const ev = async (expression) => (await send("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true })).result.result?.value;

await send("Page.enable");
await send("Runtime.enable");
await send("Emulation.setDeviceMetricsOverride", { width: Number(widthArg), height: 844, deviceScaleFactor: 1, mobile: true });
if (mode === "reduced") await send("Emulation.setEmulatedMedia", { features: [{ name: "prefers-reduced-motion", value: "reduce" }] });
await send("Page.addScriptToEvaluateOnNewDocument", { source: `try{localStorage.setItem("aisportsanalysis.invite_token","tok")}catch(e){}` });
await send("Page.navigate", { url: base + "/web/kennel.html" });
for (let i = 0; i < 120; i++) { if (await ev(`!!document.querySelector("[data-hook='dog-action-train']")`)) break; await sleep(300); }
await sleep(400);
await ev(`document.querySelector("[data-hook='dog-action-train']").click()`);
await sleep(300);
await ev(`document.querySelector("[data-hook='training-go']").click()`);
const measure = () => ev(`(() => {
  const sheet = document.querySelector(".rt-sheet");
  const wide = [];
  for (const el of document.querySelectorAll(".rt-layer *")) { const r = el.getBoundingClientRect(); if (r.width && r.right > innerWidth + 1 && !el.closest(".ev-rays, .ev-shock, .ev-ripple, .ev-flash, .ev-stage")) { wide.push(el.tagName + "." + String(el.className && el.className.baseVal !== undefined ? el.className.baseVal : el.className).slice(0, 30)); if (wide.length > 4) break; } }
  const stage = document.querySelector(".ev-stage");
  // the sound toggle must never sit over the sheet's title (the title's own text box, not its padded row)
  const snd = document.querySelector(".ev-sound"), ttl = document.querySelector(".rt-sheet__title");
  let overlap = false;
  if (snd && ttl) {
    const a = snd.getBoundingClientRect(), range = document.createRange();
    range.selectNodeContents(ttl);
    const b = range.getBoundingClientRect();
    overlap = a.width > 0 && b.width > 0 && a.left < b.right && a.right > b.left && a.top < b.bottom && a.bottom > b.top;
  }
  return { phase: (document.querySelector(".rt-layer") || {getAttribute(){return ""}}).getAttribute("data-phase"), flip: stage ? stage.getAttribute("data-flip") : "", overlap, sw: document.documentElement.scrollWidth, iw: innerWidth,
    sheetSw: sheet ? sheet.scrollWidth : 0, sheetCw: sheet ? sheet.clientWidth : 0, wide };
})()`);
const samples = [];
const seenAt = {};
const t0 = Date.now();
let seenCard = false;
while (Date.now() - t0 < 12000) {
  const m = await measure();
  samples.push(m);
  if (outDir !== "-" && m.phase) {
    // frames: the first sight of each beat, the charge once per silhouette, and the reveal and the card once they have settled
    if (!(m.phase in seenAt)) seenAt[m.phase] = Date.now();
    const late = Date.now() - seenAt[m.phase];
    const key = m.phase === "charge" ? `charge_${m.flip}` : m.phase;
    for (const k of [...(m.phase === "before" && late < 900 ? [] : [key]), ...(m.phase === "reveal" && late > 900 ? ["reveal_late"] : []), ...(m.phase === "card" && late > 2600 ? ["card_late"] : [])]) {
      if (fs.existsSync(path.join(outDir, k + ".png"))) continue;
      fs.mkdirSync(outDir, { recursive: true });
      const s = await send("Page.captureScreenshot", { format: "png" });
      fs.writeFileSync(path.join(outDir, k + ".png"), Buffer.from(s.result.data, "base64"));
    }
  }
  if (m.phase === "card" || m.phase === "static") { if (seenCard) break; seenCard = true; await sleep(3000); continue; }
  await sleep(250);
}
console.log(JSON.stringify({ samples, errors, phases: [...new Set(samples.map((s) => s.phase))] }));
ws.close();
chrome.kill();
process.exit(0);
