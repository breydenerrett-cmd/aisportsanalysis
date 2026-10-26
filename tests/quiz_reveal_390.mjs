// Drives a headless Chrome at 390x844 (a phone) through the quiz to the reveal, OPENS the "Add anything in your own words" details (the textarea sits
// inside a closed <details>, so a closed-state measurement cannot see it) and reports the rects of the heading line and the textarea.
// Used by tests/test_quiz_reveal_textarea.py.   node quiz_reveal_390.mjs <chromePath> <baseUrl>     prints one JSON object on the last line
import { spawn } from "node:child_process";
import os from "node:os";
import path from "node:path";

const [chromePath, base] = process.argv.slice(2);
const port = 9700 + Math.floor(Math.random() * 90);
const profile = path.join(os.tmpdir(), `lh-quizrev-${process.pid}-${port}`);
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
await send("Page.navigate", { url: base + "/web/landing.html?stay=1" });
await sleep(600);
await ev(`try { localStorage.removeItem("linehound.quiz.draft.v1"); } catch (e) {}`);
await send("Page.navigate", { url: base + "/web/quiz.html?restart=1#quiz" });
await sleep(2200);
const out = await ev(`(async () => { try {
  const w = (ms) => new Promise((r) => setTimeout(r, ms));
  const q = (h) => document.querySelector("[data-hook='" + h + "']");
  if (q("quiz-take") && !q("quiz-entry").hidden) { q("quiz-take").click(); await w(900); }
  document.querySelector("[data-hook='quiz-card'][data-group='sports'][data-id='MLB']").click(); await w(200); q("quiz-next").click(); await w(900);
  document.querySelector("[data-hook='quiz-card'][data-group='personality'][data-id='gematria']").click(); await w(200); q("quiz-next").click(); await w(900);
  q("quiz-next").click(); await w(900);
  q("quiz-next").click(); await w(3500);
  const det = q("reveal-own"), ta = q("reveal-english-input"), sum = det.querySelector("summary");
  const rect = (e) => { const b = e.getBoundingClientRect(); return { top: Math.round(b.top * 10) / 10, bottom: Math.round(b.bottom * 10) / 10, left: b.left, right: b.right, h: b.height }; };
  const closed = { open: det.open, ta: rect(ta), sum: rect(sum) };
  det.open = true; ta.scrollIntoView({ block: "center" }); await w(300);   // every rect below is read at ONE scroll position
  const heads = [...det.querySelectorAll("summary, h1, h2, h3, h4, legend, label:not(.qz-sr)")].map((e) => ({ tag: e.tagName, cls: String(e.className), text: (e.textContent || "").slice(0, 40), r: rect(e) }));
  const hit = (() => { const b = ta.getBoundingClientRect(); const bad = []; for (const [fx, fy] of [[.1, 2], [.5, 2], [.9, 2], [.5, 12], [.5, b.height / 2]]) { const t = document.elementFromPoint(b.left + b.width * fx, b.top + fy); if (t !== ta) bad.push((t ? t.tagName + "." + String(t.className) : null) + "@" + fx + "," + Math.round(fy)); } return bad; })();
  const taR = rect(ta), sumR = rect(sum);
  return { iw: innerWidth, closed, open: det.open, ta: taR, sum: sumR, heads, topEdgeHit: hit, det: rect(det), sw: document.documentElement.scrollWidth };
  } catch (e) { return { error: String(e && e.message || e) }; }
})()`);
if (process.env.QR_SHOT) { await ev(`document.querySelector("[data-hook='reveal-own']").scrollIntoView({block:"center"})`); await sleep(300);
  const shot = await send("Page.captureScreenshot", { format: "png" }); (await import("node:fs")).writeFileSync(process.env.QR_SHOT, Buffer.from(shot.result.data, "base64")); }
console.log(JSON.stringify(out));
ws.close();
chrome.kill();
process.exit(0);
