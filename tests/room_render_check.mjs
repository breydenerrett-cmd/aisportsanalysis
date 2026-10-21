// Drives a headless Chrome over the DevTools protocol (node 22+ has WebSocket built in) and renders the Kennel Room at a phone and a desktop width.
// Used by tests/test_kennel_room.py (the render check: no "undefined" / "NaN" / "null" / "[object" in what a person can read or in any attribute,
// no sideways scroll, the card opens).
//   node room_render_check.mjs <chromePath> <baseUrl> <path> [<path> ...]    prints one JSON array on the last line
import { spawn } from "node:child_process";
import os from "node:os";
import path from "node:path";

const [chromePath, base, ...paths] = process.argv.slice(2);
const port = 9600 + Math.floor(Math.random() * 300);
const profile = path.join(os.tmpdir(), `lh-room-check-${process.pid}-${port}`);
const chrome = spawn(chromePath, ["--headless=new", `--remote-debugging-port=${port}`, `--user-data-dir=${profile}`, "--no-first-run", "--disable-gpu", "--hide-scrollbars", "about:blank"], { stdio: "ignore" });
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
const errors = [];
ws.onmessage = (m) => {
  const d = JSON.parse(m.data);
  if (d.id && pending.has(d.id)) { pending.get(d.id)(d); pending.delete(d.id); }
  else if (d.method === "Runtime.exceptionThrown") errors.push(String(d.params.exceptionDetails.exception?.description || d.params.exceptionDetails.text).slice(0, 200));
};
const send = (method, params = {}) => new Promise((res) => { const i = ++id; pending.set(i, res); ws.send(JSON.stringify({ id: i, method, params })); });
const ev = async (expression) => (await send("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true })).result.result?.value;

await send("Page.enable");
await send("Runtime.enable");
const KEY = "aisportsanalysis.invite_token";
// signed in; "?pref=open" stands for a member who has opened the fold before (a phone otherwise starts with it folded)
await send("Page.addScriptToEvaluateOnNewDocument", { source: `try{localStorage.setItem(${JSON.stringify(KEY)},"tok");if(/pref=open/.test(location.search))localStorage.setItem("linehound.kennel-room.open","1")}catch(e){}` });

const out = [];
for (const width of [390, 1440]) {
  await send("Emulation.setDeviceMetricsOverride", { width, height: 844, deviceScaleFactor: 1, mobile: width < 700 });
  for (const p of paths) {
    await send("Page.navigate", { url: base + p });
    await sleep(2600);
    // slow machines (the whole suite running in parallel): wait until the room has drawn, or the fold is closed on purpose, up to 20 s
    for (let i = 0; i < 40; i++) {
      const ready = await ev(`!!document.querySelector("[data-hook='room-hound']") || (() => { const f = document.querySelector("[data-hook='kennel-room-fold']"); return !!f && !f.open; })()`);
      if (ready) break;
      await sleep(500);
    }
    await sleep(800);
    const r = await ev(`(async () => {
      const BAD = /undefined|NaN|\\bnull\\b|\\[object|Infinity/;
      const visible = document.body.innerText;
      const svgText = [...document.querySelectorAll(".rm svg text")].map((t) => t.textContent).join(" | ");
      const attrBad = [];
      for (const el of document.querySelectorAll(".rm *, .rm-overlay *")) {
        for (const a of el.attributes) if (BAD.test(a.value)) { attrBad.push(el.tagName + "[" + a.name + "=" + a.value.slice(0, 40) + "]"); if (attrBad.length > 4) break; }
      }
      const hounds = [...document.querySelectorAll("[data-hook='room-hound']")];
      const frame = document.querySelector("[data-hook='room-frame']");
      const stage = document.querySelector("[data-hook='room-stage']");
      const states = {};
      for (const h of hounds) states[h.getAttribute("data-state")] = (states[h.getAttribute("data-state")] || 0) + 1;
      // every hound stands inside the stage
      const sr = stage ? stage.getBoundingClientRect() : null;
      const outside = hounds.filter((h) => { const r = h.getBoundingClientRect(); return sr && (r.left < sr.left - 40 || r.right > sr.right + 40 || r.bottom > sr.bottom + 10); }).length;
      const fold = document.querySelector("[data-hook='kennel-room-fold']");
      const foldOpen = fold ? fold.open : null;
      const first = document.querySelector("[data-hook='room-hound-btn']");
      if (first) first.click();
      await new Promise((r) => setTimeout(r, 400));
      const sheet = document.querySelector("[data-hook='room-sheet']");
      const sheetText = sheet && !sheet.hidden ? sheet.innerText : "";
      const sheetRect = sheet && !sheet.hidden ? sheet.getBoundingClientRect() : null;
      // the labels over the hounds (a pick bubble, the settled units): one line, never touching each other, never cut by the edge of the frame
      const rect = (e) => e.getBoundingClientRect();
      const labels = [...document.querySelectorAll("[data-hook='room-bubble'], [data-hook='room-burst']")].filter((e) => !e.hidden && e.textContent && rect(e).width && getComputedStyle(e).visibility !== "hidden");
      const touch = (a, b) => a.left < b.right - 1 && b.left < a.right - 1 && a.top < b.bottom - 1 && b.top < a.bottom - 1;
      let labelPairs = 0;
      for (let i = 0; i < labels.length; i++) for (let j = i + 1; j < labels.length; j++) if (touch(rect(labels[i]), rect(labels[j]))) labelPairs += 1;
      const fr = frame ? rect(frame) : null;
      const labelCut = fr ? labels.filter((e) => { const r = rect(e); return (r.left < fr.left - 1 && r.right > fr.left + 1) || (r.right > fr.right + 1 && r.left < fr.right - 1); }).length : 0;
      const labelLines = [...document.querySelectorAll(".rm-bubble")].filter((e) => !e.hidden && rect(e).width).filter((e) => rect(e).height > parseFloat(getComputedStyle(e).lineHeight) + 12).length;
      const tvRect = document.querySelector("[data-hook='room-tv']");
      const labelOnTv = tvRect ? labels.filter((e) => touch(rect(e), rect(tvRect))).length : 0;
      const dims = { iw: window.innerWidth, sw: document.documentElement.scrollWidth, labels: labels.length, labelPairs, labelCut, labelLines, labelOnTv };
      return { ...dims, foldOpen, hounds: hounds.length, states, outside, frameScrolls: frame ? frame.scrollWidth > frame.clientWidth + 1 : null, stageW: sr ? Math.round(sr.width) : null,
        visibleBad: (visible.match(BAD) || [])[0] || null, svgBad: (svgText.match(BAD) || [])[0] || null, attrBad, svgText: svgText.slice(0, 300),
        sheetText: sheetText.slice(0, 400), sheetBad: (sheetText.match(BAD) || [])[0] || null,
        sheetInView: sheetRect ? sheetRect.right <= window.innerWidth + 1 && sheetRect.bottom <= window.innerHeight + 1 && sheetRect.left >= -1 : null,
        title: document.title };
    })()`);
    out.push(Object.assign({ path: p, width, errors: errors.splice(0) }, r));
  }
}
console.log(JSON.stringify(out));
ws.close();
chrome.kill();
process.exit(0);
