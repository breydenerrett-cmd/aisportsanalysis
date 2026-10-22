// Screenshots tests/evolve_sheet.html (the version-tier sheet) with a headless Chrome, once the page says it has drawn.
//   node evolve_sheet_shot.mjs <chromePath> <url> <out.png> [height=860] [width=390]
// The page has to be served (e.g. `python -m http.server` from the repo root, then http://127.0.0.1:PORT/tests/evolve_sheet.html?style=elite&breed=doberman).
import { spawn } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

const [chromePath, url, out, height = "860", width = "390"] = process.argv.slice(2);
const port = 9700 + Math.floor(Math.random() * 20000);
const profile = path.join(os.tmpdir(), `lh-sheet-${process.pid}-${port}`);
const chrome = spawn(chromePath, ["--headless=new", `--remote-debugging-port=${port}`, `--user-data-dir=${profile}`, "--no-first-run", "--disable-gpu", "--hide-scrollbars", "about:blank"], { stdio: "ignore" });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let wsUrl = null;
for (let i = 0; i < 80 && !wsUrl; i++) {
  try { wsUrl = (await (await fetch(`http://127.0.0.1:${port}/json/new?about:blank`, { method: "PUT" })).json()).webSocketDebuggerUrl; } catch (e) { await sleep(250); }
}
const ws = new WebSocket(wsUrl);
await new Promise((r) => (ws.onopen = r));
let id = 0;
const pending = new Map();
ws.onmessage = (m) => { const d = JSON.parse(m.data); if (d.id && pending.has(d.id)) { pending.get(d.id)(d); pending.delete(d.id); } };
const send = (method, params = {}) => new Promise((res) => { const i = ++id; pending.set(i, res); ws.send(JSON.stringify({ id: i, method, params })); });
await send("Page.enable");
await send("Emulation.setDeviceMetricsOverride", { width: Number(width), height: Number(height), deviceScaleFactor: 2, mobile: false });
await send("Page.navigate", { url });
for (let i = 0; i < 60; i++) {
  const r = await send("Runtime.evaluate", { expression: "document.title", returnByValue: true });
  if (r.result.result.value === "ready") break;
  await sleep(250);
}
await sleep(300);
const shot = await send("Page.captureScreenshot", { format: "png" });
fs.mkdirSync(path.dirname(out), { recursive: true });
fs.writeFileSync(out, Buffer.from(shot.result.data, "base64"));
ws.close();
chrome.kill();
process.exit(0);
