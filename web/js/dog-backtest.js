/**
 * Backtest: a dog's CURRENT rule replayed over stored boards, in paper dollars (POST /hounds/drill, the route keeps
 * its old name; src/hounds/interact/drill.py). One module, three homes: the "Backtest" tab on a dog's page, the
 * studio's "Backtest" tab on kennel.html, and the Training camp's "Backtest" section (dog-camp.js).
 *
 * LABELLED "Backtest (hindsight, not counted in the record)" BY THE SERVER AND SAID AGAIN HERE. The boards were
 * captured before the rule was run over them and the person asking can see how those games ended, so a backtest is a
 * rehearsal, never evidence: it is written to a throwaway ledger and never reaches a record, a ranking or a verdict.
 *
 * ONE CLICK PER WINDOW: 7, 14, 30 days or Season 2 (the season's finished days so far, at most the last 30). The
 * money is the live bankroll's own arithmetic computed by the server (the $1,000 paper bankroll, 1u = $10); this
 * file only draws it. Sign-in is required (any signed-in member may backtest any dog, house or member's), and the
 * server's two refusals are said in their own numbers: another backtest running ("try again in N s") and the
 * five-an-hour allowance.
 */

import { h, clearNode, fmtPrice, isNum } from "./hounds-core.js";
import { showUpgrade } from "./upgrade.js";
import { post, errorText, errorCode, signedIn, signInPrompt, statusLine, SLOW_MS } from "./dog-common.js";

export const TITLE = "Backtest (hindsight, not counted in the record)";
/** The windows, in the order of the buttons. `season` windows send {season}; the rest send {days}. */
export const WINDOWS = [
  { key: "7", days: 7, label: "7 days" },
  { key: "14", days: 14, label: "14 days" },
  { key: "30", days: 30, label: "30 days" },
  { key: "s2", season: "s2", label: "Season 2" },
];

export const requestBody = (dogId, win) => (win.season ? { dog_id: dogId, season: win.season } : { dog_id: dogId, days: win.days });

const units = (u) => (isNum(u) ? `${u > 0 ? "+" : ""}${u.toFixed(2)}u` : "n/a");
const record = (r) => `${r.wins || 0}-${r.losses || 0}${r.pushes ? `-${r.pushes}` : ""}`;

/** "+$12.00" / "-$10.00" / "$0.00". */
export function money(n) {
  if (!isNum(n)) return "n/a";
  const abs = Math.abs(n).toFixed(2).replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  return `${n > 0 ? "+" : n < 0 ? "-" : ""}$${abs}`;
}

const pct = (n) => (isNum(n) ? `${n > 0 ? "+" : ""}${n.toFixed(2)}%` : "n/a");

/** One honest sentence for a refusal: the queue message on a busy replay, the allowance on the hourly limit. */
export function backtestError(err) {
  const detail = err && err.detail && typeof err.detail === "object" ? err.detail : {};
  const wait = Number(detail.retry_after);
  if (err && err.status === 429 || errorCode(err) === "drill_busy" || errorCode(err) === "rate_limited") {
    if (errorCode(err) === "rate_limited") {
      const mins = isNum(wait) && wait > 0 ? Math.max(1, Math.ceil(wait / 60)) : null;
      return `You have used your 5 backtests for this hour. ${mins ? `Try again in ${mins} min.` : "Try again later."}`;
    }
    return `Another backtest is running, try again in ${isNum(wait) && wait > 0 ? Math.round(wait) : 30} s.`;
  }
  if (err && err.status === 401) return "Sign in to run a backtest.";
  return errorText(err, "The backtest could not run just now. Try again in a minute.");
}

function pickRow(p) {
  return h("tr", {}, [h("td", { text: String(p.date || "").slice(0, 10) }), h("td", { text: p.selection || "" }), h("td", { text: p.game || "" }),
    h("td", { class: "hd-num", text: fmtPrice(p.price_average) }),
    h("td", { text: p.result || "Pending" }),
    h("td", { class: "hd-num", "data-hook": "backtest-pick-usd", text: p.result && isNum(p.usd) ? money(p.usd) : "" })]);
}

/** Draw one backtest result into `box`. */
export function renderBacktest(box, data) {
  clearNode(box);
  const rec = data.record || {};
  const bank = data.bankroll || {};
  const graded = rec.graded || 0;
  box.appendChild(h("div", { class: "dk-hindsight", "data-hook": "drill-label", role: "status" }, [
    h("span", { class: "dk-chip dk-chip--hind", text: data.label || TITLE }),
    h("span", { class: "hd-fine", text: data.disclosure || "" })]));
  const seasonNote = data.season && data.season.clipped
    ? ` (the last ${data.days} of ${data.season.days_in_season} days of ${data.season.label})` : data.season ? ` (${data.season.label})` : "";
  box.appendChild(h("dl", { class: "dk-camp-dog__facts", "data-hook": "backtest-facts" }, [
    h("div", {}, [h("dt", { text: "Hound" }), h("dd", { text: (data.dog && data.dog.name) || "" })]),
    h("div", {}, [h("dt", { text: "Window" }), h("dd", { "data-hook": "backtest-window-text", text: data.window ? `${data.window.first} to ${data.window.last}, ${data.days} days${seasonNote}` : "" })]),
    h("div", {}, [h("dt", { text: "Bets" }), h("dd", { "data-hook": "drill-bets", text: `${rec.bets || 0} (${graded} graded${rec.pending ? `, ${rec.pending} pending` : ""})` })]),
    h("div", {}, [h("dt", { text: "Record (W-L)" }), h("dd", { "data-hook": "drill-record", text: graded ? record(rec) : "no graded bets" })]),
    h("div", {}, [h("dt", { text: "Paper dollars" }), h("dd", { "data-hook": "backtest-usd", text: graded ? `${money(bank.pnl_usd)} on the $${isNum(bank.start) ? bank.start.toLocaleString("en-US") : "1,000"} paper bankroll` : "n/a" })]),
    h("div", {}, [h("dt", { text: "Return" }), h("dd", { "data-hook": "backtest-return", text: graded ? pct(bank.return_pct) : "n/a" })]),
    h("div", {}, [h("dt", { text: "Units" }), h("dd", { "data-hook": "drill-units", text: graded ? units(data.units_average_price) : "n/a" })]),
    h("div", {}, [h("dt", { text: "Worst dip" }), h("dd", { "data-hook": "backtest-drawdown", text: graded && isNum(bank.max_drawdown_usd) ? money(-bank.max_drawdown_usd) : "n/a" })]),
  ]));
  box.appendChild(h("p", { class: "hd-fine", "data-hook": "drill-sample", text: data.sample_note || "" }));
  if (bank.label) box.appendChild(h("p", { class: "hd-fine", "data-hook": "backtest-bankroll-note", text: `${bank.label} Units are at the board-average price.` }));
  if (data.rule_text) box.appendChild(h("p", { class: "hd-fine", "data-hook": "drill-rule", text: `Rule replayed: ${data.rule_text.replace(/\s*Paper only\. These are simulated picks.*$/s, "")}` }));
  for (const [title, list, hook] of [["Best picks", data.best, "drill-best"], ["Worst picks", data.worst, "drill-worst"]]) {
    if (!list || !list.length) continue;
    box.appendChild(h("div", { class: "dk-block" }, [h("h3", { class: "hd-h3", text: title }),
      h("ul", { class: "dk-misses", "data-hook": hook }, list.map((p) => h("li", { class: "dk-miss" }, [
        h("strong", { text: p.selection }), ` ${String(p.date).slice(0, 10)} at ${fmtPrice(p.price_average)}: ${money(p.usd)} (${units(p.units_average_price)})`])))]));
  }
  if (data.picks && data.picks.length) {
    box.appendChild(h("div", { class: "dk-block" }, [
      h("h3", { class: "hd-h3", text: `Tickets, newest first${data.picks_total > data.picks.length ? ` (${data.picks.length} of ${data.picks_total})` : ""}` }),
      h("div", { class: "dk-tablewrap" }, [h("table", { class: "dk-mini", "data-hook": "drill-picks" }, [
        h("thead", {}, [h("tr", {}, ["Date", "Pick", "Game", "Price", "Result", "Paper $"].map((t, i) => h("th", { class: i === 3 || i === 5 ? "hd-num" : "", text: t })))]),
        h("tbody", {}, data.picks.map(pickRow))])])]));
  } else {
    box.appendChild(h("p", { class: "hd-muted", "data-hook": "drill-empty", text: "The rule made no pick in this window." }));
  }
}

/**
 * Run one backtest and draw it. Shared by the tabs and the camp. `dogId` is read when called, `win` is one of
 * WINDOWS, `status` is a status line element and `out` the result box. Resolves to the data, or null on a refusal.
 */
export async function runBacktest({ dogId, win, status, out, busy }) {
  if (!dogId) { status.textContent = "Pick a dog first."; return null; }
  if (!signedIn()) { clearNode(status); status.appendChild(signInPrompt("Sign in to run a backtest.")); return null; }
  if (busy) busy(true);
  clearNode(out);
  status.textContent = `Running the backtest over ${win.season ? "Season 2" : `${win.days} days`} of boards. ${win.days === 30 || win.season ? "A month can take up to a minute." : "This takes a few seconds."}`;
  try {
    const data = await post("/hounds/drill", requestBody(dogId, win), SLOW_MS);
    status.textContent = "";
    renderBacktest(out, data);
    return data;
  } catch (err) {
    if (showUpgrade(out, err)) { status.textContent = ""; return null; }
    status.textContent = backtestError(err);
    return null;
  } finally {
    if (busy) busy(false);
  }
}

/**
 * The "Backtest" tab body: the label, a one-line how-it-works, four window buttons, a status line and the result.
 * Signed-out visitors get the sign-in prompt in place of the buttons. `section` is the panel's section element (it
 * is un-hidden here); `body` the element to fill.
 */
export function mountBacktest(section, { id, name }) {
  const body = section.querySelector("[data-hook='dog-backtest']");
  if (!body) return;
  clearNode(body);
  body.appendChild(h("p", { class: "dk-hindsight-title", "data-hook": "backtest-title" }, [h("span", { class: "dk-chip dk-chip--hind", text: TITLE })]));
  body.appendChild(h("p", { class: "hd-muted", text: `Replay ${name || "this hound"}'s current rule over boards already stored and see what it would have done on the $1,000 paper bankroll. You can see how those games ended, so this is a rehearsal and never counts toward its record.` }));
  const status = statusLine("backtest-status");
  const out = h("div", { class: "dk-result", "data-hook": "backtest-result", "aria-live": "polite" });
  if (!signedIn()) {
    body.appendChild(h("div", { "data-hook": "backtest-signin" }, [signInPrompt("Sign in to run a backtest on this hound.")]));
    section.removeAttribute("hidden");
    return;
  }
  const buttons = [];
  const segs = h("div", { class: "hd-segs", role: "group", "aria-label": "Which window to backtest" });
  for (const win of WINDOWS) {
    const b = h("button", { type: "button", class: "hd-seg", "data-window": win.key, "data-hook": "backtest-window", "aria-pressed": "false", text: win.label });
    b.addEventListener("click", async () => {
      for (const x of buttons) x.setAttribute("aria-pressed", x === b ? "true" : "false");
      await runBacktest({ dogId: id, win, status, out, busy: (on) => { for (const x of buttons) { if (on) x.setAttribute("disabled", ""); else x.removeAttribute("disabled"); } } });
    });
    buttons.push(b);
    segs.appendChild(b);
  }
  body.appendChild(segs);
  body.appendChild(status);
  body.appendChild(out);
  section.removeAttribute("hidden");
}
