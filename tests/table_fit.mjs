// Loads one page in headless Chrome at each given width and reports every .hd-tablewrap: does its table fit without sideways scroll,
// and which columns are visible. Used by tests/test_web_leaderboard_fit.py.
//   node table_fit.mjs <chromePath> <baseUrl> <path> <width> [<width> ...]     prints one JSON array on the last line
import { spawn } from "node:child_process";
import os from "node:os";
import path from "node:path";

const [chromePath, base, page, ...widths] = process.argv.slice(2);
const port = 9900 + Math.floor(Math.random() * 90);
const profile = path.join(os.tmpdir(), `lh-fit-${process.pid}-${port}`);
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
const out = [];
for (const w of widths.map(Number)) {
  await send("Emulation.setDeviceMetricsOverride", { width: w, height: 900, deviceScaleFactor: 1, mobile: false });
  await send("Page.navigate", { url: base + page });
  await sleep(2600);
  out.push(Object.assign({ width: w }, await ev(`(()=>{
    const wraps = [...document.querySelectorAll(".hd-tablewrap")].map((wrap) => {
      const table = wrap.querySelector("table");
      const heads = [...wrap.querySelectorAll("thead th")].filter((th) => getComputedStyle(th).display !== "none").map((th) => (th.className.match(/hd-col-([a-z0-9]+)/) || [])[1]);
      return { client: wrap.clientWidth, scroll: wrap.scrollWidth, table: table ? Math.round(table.getBoundingClientRect().width) : 0, heads, hook: (table && table.getAttribute("data-hook")) || "" };
    });
    return { wraps, docScroll: document.documentElement.scrollWidth };
  })()`)));
}
console.log(JSON.stringify(out));
ws.close();
chrome.kill();
process.exit(0);
