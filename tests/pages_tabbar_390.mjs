// Measures the phone chrome of a page at 390 x 844 in a headless Chrome (tests/test_pages_tabbar_390.py):
// the fixed tab bar's top, the page's bottom padding, where the last content ends, and how many lines a long hound
// name takes in the landing card. Usage: node pages_tabbar_390.mjs <chromePath> <url>   prints one JSON object on the last line.
import { spawn } from "node:child_process";
import os from "node:os";
import path from "node:path";

const [chromePath, url] = process.argv.slice(2);
const port = 9400 + Math.floor(Math.random() * 500);
const profile = path.join(os.tmpdir(), `lh-pages-${process.pid}-${port}`);
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
await sleep(3000);
const out = await ev(`(() => {
  const bar = document.querySelector('.lh-tabbar');
  let maxBottom = 0;
  for (const el of document.querySelectorAll('body *')) {
    if (bar && (el === bar || bar.contains(el))) continue;
    // a closed <details> keeps its body laid out (a tall box nobody can see or tap): only the summary of a closed one counts
    const closed = el.parentElement && el.parentElement.closest('details:not([open])');
    if (closed && el.tagName !== 'SUMMARY') continue;
    const st = getComputedStyle(el);
    if (st.position === 'fixed' || st.display === 'none' || st.visibility === 'hidden') continue;
    const r = el.getBoundingClientRect();
    if (r.height === 0) continue;
    maxBottom = Math.max(maxBottom, r.bottom + scrollY);
  }
  // a long hound name in the landing card's name slot: two lines allowed, then cut
  const probe = document.createElement('span');
  probe.className = 'kh-hound__name';
  probe.style.cssText = 'width:120px;';
  probe.textContent = 'Gematria Hound Experimental Numerology Rules';
  document.body.appendChild(probe);
  const lineH = parseFloat(getComputedStyle(probe).lineHeight) || 1;
  const nameLines = Math.round(probe.getBoundingClientRect().height / lineH);
  probe.remove();
  return { barTop: bar ? bar.getBoundingClientRect().top : null, barH: bar ? bar.getBoundingClientRect().height : 0,
    padBottom: parseFloat(getComputedStyle(document.body).paddingBottom), maxBottom: Math.round(maxBottom),
    scrollH: document.documentElement.scrollHeight, nameLines };
})()`);
console.log(JSON.stringify(out));
chrome.kill();
process.exit(0);
