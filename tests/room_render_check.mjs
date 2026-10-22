// Drives a headless Chrome over the DevTools protocol (node 22+ has WebSocket built in) and renders the Kennel Room at a phone and a desktop width.
// Used by tests/test_kennel_room.py (the render check: no "undefined" / "NaN" / "null" / "[object" in what a person can read or in any attribute,
// no sideways scroll, the card opens).
//   node room_render_check.mjs [--widths=390,1440] [--reduced] [--daytime] <chromePath> <baseUrl> <path> [<path> ...]    prints one JSON array on the last line
// Every row also carries `geom`: the room's GEOMETRY as laid out (tests/test_kennel_room.py RoomCrowding): sprites, name tags, labels, "+K more" tokens
// and signs as rects, which of them overlap, which cross their zone's boundary, whether the zone bands overlap. --reduced emulates
// prefers-reduced-motion (no animation, so the rects are the resting ones); --daytime pretends the viewer's clock is mid-afternoon (the idle hounds scout).
import { spawn } from "node:child_process";
import os from "node:os";
import path from "node:path";

const argv = process.argv.slice(2);
const flags = argv.filter((a) => a.startsWith("--"));
const [chromePath, base, ...paths] = argv.filter((a) => !a.startsWith("--"));
const widthsArg = (flags.find((f) => f.startsWith("--widths=")) || "--widths=390,1440").split("=")[1].split(",").map(Number);
const reduced = flags.includes("--reduced"), daytime = flags.includes("--daytime");
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

if (reduced) await send("Emulation.setEmulatedMedia", { features: [{ name: "prefers-reduced-motion", value: "reduce" }] });
if (daytime) {
  // a time zone where it is mid-afternoon right now, so "not the viewer's night" holds whatever hour the machine is at
  const zones = ["America/New_York", "Asia/Tokyo", "Europe/London", "Pacific/Auckland", "America/Los_Angeles", "Asia/Kolkata", "Australia/Sydney", "Pacific/Honolulu", "America/Sao_Paulo", "Asia/Dubai"];
  const hourIn = (z) => Number(new Intl.DateTimeFormat("en-US", { timeZone: z, hour: "numeric", hourCycle: "h23" }).format(new Date()));
  const zone = zones.find((z) => hourIn(z) >= 10 && hourIn(z) <= 17) || "America/New_York";
  await send("Emulation.setTimezoneOverride", { timezoneId: zone });
}

const out = [];
for (const width of widthsArg) {
  await send("Emulation.setDeviceMetricsOverride", { width, height: 844, deviceScaleFactor: 1, mobile: width < 700 });
  for (const p of paths) {
    const nav = await send("Page.navigate", { url: base + p });
    if (nav.result && nav.result.errorText) console.error("navigate " + base + p + ": " + nav.result.errorText);
    await sleep(2600);
    // slow machines (the whole suite running in parallel): wait until the room has drawn, or the fold is closed on purpose, up to 50 s
    for (let i = 0; i < 100; i++) {
      const ready = await ev(`!!document.querySelector("[data-hook='room-hound']") || !!document.querySelector("[data-hook='room'][data-empty='true']") || (() => { const f = document.querySelector("[data-hook='kennel-room-fold']"); return !!f && !f.open; })()`);
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
      const geom = (() => {
        const box = (e) => { const r = e.getBoundingClientRect(); return { l: r.left, t: r.top, r: r.right, b: r.bottom, w: r.width, h: r.height }; };
        const shown = (e) => { const r = e.getBoundingClientRect(); const cs = getComputedStyle(e); return r.width > 0 && r.height > 0 && !e.hidden && cs.visibility !== "hidden" && cs.display !== "none"; };
        const cross = (a, b) => a.l < b.r && b.l < a.r && a.t < b.b && b.t < a.b;                        // two rects share some area (touching edges do not count: 0 px allowed)
        const inside = (a, z) => a.l >= z.l - 0.5 && a.r <= z.r + 0.5 && a.t >= z.t - 0.5 && a.b <= z.b + 0.5;
        const items = [];                                    // { kind, owner, zone, name, box }
        for (const hd of document.querySelectorAll("[data-hook='room-hound']")) {
          const id = hd.getAttribute("data-id"), zone = hd.getAttribute("data-zone");
          const add = (kind, el) => { if (el && shown(el)) items.push({ kind, owner: id, zone, name: id + ":" + kind + (el.getAttribute("style") ? "{" + el.getAttribute("style") + "}" : ""), box: box(el) }); };
          add("sprite", hd.querySelector(".rm-dog svg"));
          add("name", hd.querySelector("[data-hook='room-name']"));
          add("bubble", hd.querySelector("[data-hook='room-bubble']"));
          add("burst", hd.querySelector("[data-hook='room-burst']"));
        }
        for (const t of document.querySelectorAll("[data-hook='room-more']")) if (shown(t)) items.push({ kind: "more", owner: "more-" + t.getAttribute("data-zone"), zone: t.getAttribute("data-zone"), name: "more:" + t.getAttribute("data-zone"), box: box(t) });
        for (const t of document.querySelectorAll(".rm svg text.rm-label")) items.push({ kind: "sign", owner: "sign-" + t.getAttribute("data-sign"), zone: t.getAttribute("data-sign") === "bed" ? "bed" : "gym", name: "sign:" + t.textContent, box: box(t) });
        const zones = {};
        for (const z of document.querySelectorAll(".rm svg rect.rm-zone")) zones[z.getAttribute("data-zone")] = box(z);
        const overlaps = [];
        for (let i = 0; i < items.length; i++) for (let j = i + 1; j < items.length; j++) {
          const a = items[i], b = items[j];
          if (a.owner === b.owner && (a.kind === "sprite" || b.kind === "sprite")) continue;           // a hound's own tag is tucked under its own sprite on purpose
          if (cross(a.box, b.box)) overlaps.push(a.name + " x " + b.name + " " + JSON.stringify([a.box.l, a.box.t, a.box.r, a.box.b].map(Math.round)) + " " + JSON.stringify([b.box.l, b.box.t, b.box.r, b.box.b].map(Math.round)));
        }
        const outside = items.filter((it) => it.kind !== "sign" && !(zones[it.zone] && inside(it.box, zones[it.zone]))).map((it) => it.name + " in " + it.zone + " " + JSON.stringify([it.box.l, it.box.t, it.box.r, it.box.b].map(Math.round)) + " zone " + JSON.stringify(zones[it.zone] ? [zones[it.zone].l, zones[it.zone].t, zones[it.zone].r, zones[it.zone].b].map(Math.round) : null));
        const signsOut = items.filter((it) => it.kind === "sign" && !(zones[it.zone] && inside(it.box, zones[it.zone]))).map((it) => it.name);
        const zoneNames = Object.keys(zones), zoneOverlaps = [];
        for (let i = 0; i < zoneNames.length; i++) for (let j = i + 1; j < zoneNames.length; j++) if (cross(zones[zoneNames[i]], zones[zoneNames[j]])) zoneOverlaps.push(zoneNames[i] + " x " + zoneNames[j]);
        const kinds = {};
        for (const it of items) kinds[it.kind] = (kinds[it.kind] || 0) + 1;
        const more = [...document.querySelectorAll("[data-hook='room-more']")].map((t) => t.getAttribute("data-zone") + ":" + t.textContent);
        const tags = [...document.querySelectorAll("[data-hook='room-name']")].filter(shown).map((t) => ({ full: t.textContent, title: t.getAttribute("title"), cut: t.scrollWidth > t.clientWidth + 1 }));
        return { kinds, overlaps: overlaps.slice(0, 8), overlapCount: overlaps.length, outside: outside.slice(0, 8), outsideCount: outside.length, signsOut, zoneOverlaps, zones: zoneNames,
          more, rosterCount: document.querySelectorAll("[data-hook='room-roster-btn']").length, tagsCut: tags.filter((t) => t.cut).length, tagsCutNoTitle: tags.filter((t) => t.cut && t.title !== t.full).length,
          stageH: stage ? Math.round(stage.getBoundingClientRect().height) : null };
      })();
      const msg = ((document.querySelector("[data-hook='room-message']") || {}).innerText || "") + " | " + ((document.querySelector("[data-hook='room-status']") || {}).innerText || "") + " | " + location.href + " | " + document.readyState + " | " + document.body.innerText.slice(0, 80);
      const dims = { geom, msg: msg.slice(0, 120), iw: window.innerWidth, sw: document.documentElement.scrollWidth, labels: labels.length, labelPairs, labelCut, labelLines, labelOnTv };
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
