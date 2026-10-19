/**
 * The Training camp's working sections (web/learning.html): "Your dogs in training", "Drills" and "Promotions and
 * cuts". The scorecard, the coach report card and the lessons are web/js/hounds-learning.js's; this file is the part
 * of camp where a person improves a dog.
 *
 *   YOUR DOGS IN TRAINING  GET /hounds/camp/mine (signed in): each of your dogs with its season record, its last five
 *                          tickets, the feedback it has had, suggestions waiting, your manual picks (kept apart), and
 *                          one-click Fire now, Ask and Drill.
 *   DRILLS                 POST /hounds/drill {dog_id, days: 7|14|30}: the dog's current rule replayed over the last
 *                          7, 14 or 30 days of stored boards. LABELLED "Hindsight drill: not counted", read only, with
 *                          W-L, units, the best and worst picks, and every pick. A month can take a minute.
 *   PROMOTIONS AND CUTS    the learning loop's lessons that ended in a promotion (made the team) or a retirement (cut).
 *
 * Nothing here computes a number: it draws what the server sent and says "small sample" where the server did.
 */

import { h, clearNode, fmtPrice, isNum, signed, monogram, fmtWhen } from "./hounds-core.js";
import { friendlyLesson } from "./hounds-voice.js";
import { dogFace } from "./dog-avatar.js";
import { get, post, errorText, signedIn, signInPrompt, builderHref, changeText, SLOW_MS, statusLine } from "./dog-common.js";
import { renderFireResult } from "./dog-fire.js";
import { mountAsk } from "./dog-ask.js";

const q = (hook) => document.querySelector(`[data-hook='${hook}']`);
const DAYS = [7, 14, 30];

const units = (u) => (isNum(u) ? `${u > 0 ? "+" : ""}${u.toFixed(2)}u` : "n/a");
const record = (r) => `${r.wins || 0}-${r.losses || 0}${r.pushes ? `-${r.pushes}` : ""}`;

// ---- your dogs in training ---------------------------------------------------------------------------------

function avatar(d) {
  return dogFace(d, { size: 52 });
}

function ticketsTable(items) {
  if (!items.length) return h("p", { class: "hd-muted", text: "No tickets yet. The engine records one when its rule fires on a game at its placing time." });
  return h("div", { class: "dk-tablewrap" }, [h("table", { class: "dk-mini", "data-hook": "camp-tickets" }, [
    h("thead", {}, [h("tr", {}, ["Date", "Pick", "Price", "Result"].map((t, i) => h("th", { class: i >= 2 ? "hd-num" : "", text: t })))]),
    h("tbody", {}, items.map((t) => h("tr", {}, [
      h("td", { text: String(t.date || "").slice(0, 10) }), h("td", { text: t.selection || "" }),
      h("td", { class: "hd-num", text: fmtPrice(isNum(t.price_average) ? t.price_average : t.price) }),
      h("td", { class: "hd-num", text: t.result ? `${String(t.result).toUpperCase()}${isNum(t.units) ? ` ${signed(t.units, 2)}u` : ""}` : "Open" })])))])]);
}

function dogCard(d, { onDrill }) {
  const rec = d.record || {};
  const bets = isNum(rec.bets) ? rec.bets : 0;
  const li = h("li", { class: "dk-camp-dog", "data-hook": "camp-dog", "data-dog": d.id, "data-status": d.status });
  li.appendChild(h("div", { class: "dk-camp-dog__head" }, [
    avatar(d),
    h("div", {}, [h("a", { class: "dk-camp-dog__name", href: d.page_href, text: d.name }),
      h("p", { class: "hd-fine", text: `${d.status === "running" ? "Running" : d.status === "benched" ? "Idle" : "Retired"}, version ${d.version_no}${d.tagline ? ` · ${d.tagline}` : ""}` })]),
    d.verdict && d.verdict.label ? h("span", { class: "dk-chip", text: d.verdict.label }) : null,
  ]));
  const avg = isNum(rec.units_average_price) ? rec.units_average_price : rec.units_recorded_price;
  li.appendChild(h("dl", { class: "dk-camp-dog__facts" }, [
    h("div", {}, [h("dt", { text: "Season record" }), h("dd", { text: bets ? `${record(rec)} over ${bets} ${bets === 1 ? "bet" : "bets"}${bets < 100 ? ", small sample" : ""}` : "no graded bets yet" })]),
    h("div", {}, [h("dt", { text: "Units (average price)" }), h("dd", { text: bets ? units(avg) : "n/a" })]),
    h("div", {}, [h("dt", { text: "Open tickets" }), h("dd", { text: String(d.open_bets || 0) })]),
    h("div", {}, [h("dt", { text: "Feedback" }), h("dd", { text: `${d.feedback.good} good, ${d.feedback.bad} bad${d.feedback.notes ? `, ${d.feedback.notes} notes` : ""}` })]),
    h("div", {}, [h("dt", { text: "Suggestions waiting" }), h("dd", { text: String(d.feedback.suggestions || 0) })]),
    h("div", {}, [h("dt", { text: "Manual picks (apart)" }), h("dd", { text: d.manual && d.manual.tickets ? `${d.manual.wins}-${d.manual.losses} of ${d.manual.graded} graded, ${d.manual.open} open` : "none" })]),
  ]));
  li.appendChild(h("div", {}, [h("h3", { class: "hd-h3", text: "Last five tickets" }), ticketsTable(d.last_tickets || [])]));
  if (d.suggestions && d.suggestions.length) {
    li.appendChild(h("div", { "data-hook": "camp-suggestions" }, [h("h3", { class: "hd-h3", text: "Suggestions waiting" }),
      h("ul", { class: "dk-misses" }, d.suggestions.map((s) => h("li", { class: "dk-miss" }, [
        h("p", {}, [h("strong", { text: changeText(s.change) }), s.note ? ` — ${s.note}` : ""]),
        h("a", { class: "btn btn--ghost", href: builderHref(d.id, s.change), text: "Open in the builder" })])))]));
  }
  const inline = h("div", { class: "dk-inline", "data-hook": "camp-inline", hidden: "" });
  let open = "";
  const toggle = (which, make) => {
    if (open === which) { open = ""; inline.setAttribute("hidden", ""); clearNode(inline); return; }
    open = which;
    clearNode(inline);
    inline.removeAttribute("hidden");
    make(inline);
  };
  const fireBtn = h("button", { type: "button", class: "btn btn--primary", "data-hook": "camp-dog-fire", text: "Fire now" });
  fireBtn.addEventListener("click", () => toggle("fire", async (box) => {
    const status = statusLine("camp-fire-status");
    status.textContent = "Reading the latest boards...";
    box.appendChild(status);
    const out = h("div", { class: "dk-result" });
    box.appendChild(out);
    try {
      const data = await post(`/hounds/${encodeURIComponent(d.id)}/fire`, {}, 90000);
      status.textContent = "";
      renderFireResult(out, data, { id: d.id, canRecord: d.status === "running" && data.viewer_is_owner });
    } catch (err) {
      status.textContent = errorText(err, "The boards could not be read just now.");
    }
  }));
  const askBtn = h("button", { type: "button", class: "btn btn--ghost", "data-hook": "camp-dog-ask", text: "Ask" });
  askBtn.addEventListener("click", () => toggle("ask", (box) => {
    const chat = mountAsk(box, { id: d.id, name: d.name, compact: true });
    for (const text of ["What did you bet today?", "How are you doing?"]) {
      const b = h("button", { type: "button", class: "dk-chipbtn", "data-hook": "ask-chip", text });
      b.addEventListener("click", () => chat.ask(text));
      box.querySelector("[data-hook='ask-suggestions']").appendChild(b);
    }
  }));
  const drillBtn = h("button", { type: "button", class: "btn btn--ghost", "data-hook": "camp-dog-drill", text: "Drill this dog" });
  drillBtn.addEventListener("click", () => onDrill(d.id));
  li.appendChild(h("div", { class: "dk-camp-dog__tools" }, [fireBtn, askBtn, drillBtn,
    h("a", { class: "btn btn--ghost", href: d.page_href, text: "Open its page" }),
    d.status !== "retired" ? h("a", { class: "btn btn--ghost", href: d.builder_href, text: "Change it in the builder" }) : null]));
  li.appendChild(inline);
  return li;
}

async function bootDogs(onDrill) {
  const box = q("camp-dogs");
  if (!box) return [];
  clearNode(box);
  if (!signedIn()) {
    box.appendChild(signInPrompt("Sign in to see the dogs you built, fire them, ask them and drill them."));
    box.appendChild(h("p", { class: "hd-fine" }, ["No dog yet? ", h("a", { href: "build-a-hound.html", text: "Build one" }), "."]));
    return [];
  }
  let data;
  try {
    data = await get("/hounds/camp/mine");
  } catch (err) {
    box.appendChild(err && err.status === 401 ? signInPrompt("Your sign-in has expired.") : h("p", { class: "hd-muted", "data-hook": "camp-dogs-error", text: errorText(err, "Your dogs could not be loaded just now.") }));
    return [];
  }
  const dogs = Array.isArray(data.dogs) ? data.dogs : [];
  if (!dogs.length) {
    box.appendChild(h("p", { class: "hd-muted", "data-hook": "camp-dogs-empty" }, ["You have not built a dog yet. ", h("a", { href: "build-a-hound.html", text: "Build one" }),
      ", and it will show up here with its record, its tickets and what people think of it."]));
    return [];
  }
  box.appendChild(h("ul", { class: "dk-camp-dogs", "data-hook": "camp-dog-list" }, dogs.map((d) => dogCard(d, { onDrill }))));
  return dogs;
}

// ---- drills ------------------------------------------------------------------------------------------------

function pickRow(p) {
  return h("tr", {}, [h("td", { text: String(p.date || "").slice(0, 10) }), h("td", { text: p.selection || "" }), h("td", { text: p.game || "" }),
    h("td", { class: "hd-num", text: fmtPrice(p.price_average) }),
    h("td", { text: p.result || "Pending" }), h("td", { class: "hd-num", text: p.result ? units(p.units_average_price) : "" })]);
}

export function renderDrill(box, data) {
  clearNode(box);
  const rec = data.record || {};
  box.appendChild(h("div", { class: "dk-hindsight", "data-hook": "drill-label", role: "status" }, [
    h("span", { class: "dk-chip dk-chip--hind", text: data.label || "Hindsight drill: not counted" }),
    h("span", { class: "hd-fine", text: data.disclosure || "" })]));
  box.appendChild(h("dl", { class: "dk-camp-dog__facts", "data-hook": "drill-facts" }, [
    h("div", {}, [h("dt", { text: "Dog" }), h("dd", { text: (data.dog && data.dog.name) || "" })]),
    h("div", {}, [h("dt", { text: "Window" }), h("dd", { text: data.window ? `${data.window.first} to ${data.window.last} (${data.days} days)` : "" })]),
    h("div", {}, [h("dt", { text: "Bets" }), h("dd", { "data-hook": "drill-bets", text: `${rec.bets || 0} (${rec.graded || 0} graded${rec.pending ? `, ${rec.pending} pending` : ""})` })]),
    h("div", {}, [h("dt", { text: "Record" }), h("dd", { "data-hook": "drill-record", text: (rec.graded || 0) ? record(rec) : "no graded bets" })]),
    h("div", {}, [h("dt", { text: "Units, average price" }), h("dd", { "data-hook": "drill-units", text: (rec.graded || 0) ? units(data.units_average_price) : "n/a" })]),
    h("div", {}, [h("dt", { text: "Units, best price" }), h("dd", { text: (rec.graded || 0) ? units(data.units_best_price) : "n/a" })]),
  ]));
  box.appendChild(h("p", { class: "hd-fine", "data-hook": "drill-sample", text: data.sample_note || "" }));
  if (data.rule_text) box.appendChild(h("p", { class: "hd-fine", "data-hook": "drill-rule", text: `Rule replayed: ${data.rule_text.replace(/\s*Paper only\. These are simulated picks.*$/s, "")}` }));
  for (const [title, list, hook] of [["Best picks", data.best, "drill-best"], ["Worst picks", data.worst, "drill-worst"]]) {
    if (!list || !list.length) continue;
    box.appendChild(h("div", { class: "dk-block" }, [h("h3", { class: "hd-h3", text: title }),
      h("ul", { class: "dk-misses", "data-hook": hook }, list.map((p) => h("li", { class: "dk-miss" }, [
        h("strong", { text: p.selection }), ` ${String(p.date).slice(0, 10)} at ${fmtPrice(p.price_average)}: ${units(p.units_average_price)}`])))]));
  }
  if (data.picks && data.picks.length) {
    box.appendChild(h("div", { class: "dk-block" }, [
      h("h3", { class: "hd-h3", text: `Every pick, newest first${data.picks_total > data.picks.length ? ` (${data.picks.length} of ${data.picks_total})` : ""}` }),
      h("div", { class: "dk-tablewrap" }, [h("table", { class: "dk-mini", "data-hook": "drill-picks" }, [
        h("thead", {}, [h("tr", {}, ["Date", "Pick", "Game", "Price", "Result", "Units"].map((t, i) => h("th", { class: i === 3 || i === 5 ? "hd-num" : "", text: t })))]),
        h("tbody", {}, data.picks.map(pickRow))])])]));
  } else {
    box.appendChild(h("p", { class: "hd-muted", "data-hook": "drill-empty", text: "The rule made no pick in this window." }));
  }
}

async function bootDrills(dogs) {
  const box = q("camp-drill");
  if (!box) return () => {};
  clearNode(box);
  let house = [];
  try {
    const lb = await get("/hounds");
    house = (lb.hounds || []).filter((x) => x.kind === "house" && x.status !== "retired");
  } catch (err) { house = []; }
  const select = h("select", { class: "dk-select", id: "dk-drill-dog", "data-hook": "drill-dog", "aria-label": "Which dog to drill" });
  const mine = h("optgroup", { label: "Your dogs" }, dogs.filter((d) => d.status !== "retired").map((d) => h("option", { value: d.id, text: d.name })));
  const pack = h("optgroup", { label: "House models" }, house.map((x) => h("option", { value: x.id, text: x.name })));
  if (dogs.length) select.appendChild(mine);
  if (house.length) select.appendChild(pack);
  let days = 14;
  const segs = h("div", { class: "hd-segs", role: "group", "aria-label": "How many days to replay" });
  const paintSegs = () => { for (const b of segs.querySelectorAll("button")) b.setAttribute("aria-pressed", b.getAttribute("data-days") === String(days) ? "true" : "false"); };
  for (const n of DAYS) {
    const b = h("button", { type: "button", class: "hd-seg", "data-days": String(n), "data-hook": "drill-days", "aria-pressed": "false", text: `${n} days` });
    b.addEventListener("click", () => { days = n; paintSegs(); });
    segs.appendChild(b);
  }
  paintSegs();
  const run = h("button", { type: "button", class: "btn btn--primary", "data-hook": "drill-run", text: "Run drill" });
  const status = statusLine("drill-status");
  const out = h("div", { class: "dk-result", "data-hook": "drill-result", "aria-live": "polite" });
  run.addEventListener("click", async () => {
    if (!select.value) { status.textContent = "Pick a dog first."; return; }
    if (!signedIn()) { clearNode(status); status.appendChild(signInPrompt("Sign in to run a drill.")); return; }
    run.setAttribute("disabled", "");
    clearNode(out);
    status.textContent = `Replaying ${days} days of boards. ${days === 30 ? "A month can take up to a minute." : "This takes a few seconds."}`;
    try {
      const data = await post("/hounds/drill", { dog_id: select.value, days }, SLOW_MS);
      status.textContent = "";
      renderDrill(out, data);
    } catch (err) {
      status.textContent = errorText(err, "The drill could not run just now. Try again in a minute.");
    } finally {
      run.removeAttribute("disabled");
    }
  });
  box.appendChild(h("div", { class: "dk-drill-controls" }, [
    h("label", { for: "dk-drill-dog", text: "Dog" }), select, segs, h("div", { class: "dk-actions" }, [run, status])]));
  box.appendChild(out);
  const params = new URLSearchParams(window.location.search || "");
  const want = params.get("drill");
  if (want && [...select.querySelectorAll("option")].some((o) => o.getAttribute("value") === want)) select.value = want;
  if (DAYS.includes(Number(params.get("days")))) { days = Number(params.get("days")); paintSegs(); }
  return (id) => {
    if ([...select.querySelectorAll("option")].some((o) => o.getAttribute("value") === id)) select.value = id;
    const section = q("camp-drills-section");
    const collapsed = section && section.querySelector("details.cp-sec");
    if (collapsed) collapsed.open = true;   // the camp sections are collapsed: a drill opens its own
    if (section && section.scrollIntoView) section.scrollIntoView({ behavior: "smooth", block: "start" });
    run.focus();
  };
}

// ---- promotions and cuts -----------------------------------------------------------------------------------

export function eventItem(l) {
  const promoted = l.outcome === "promoted";
  return h("li", { class: "dk-event", "data-outcome": l.outcome, "data-hook": "camp-event" }, [
    h("p", {}, [h("span", { class: `dk-chip ${promoted ? "dk-chip--good" : "dk-chip--bad"}`, text: promoted ? "Made the team" : "Cut" }),
      l.utc ? h("span", { class: "hd-fine", text: ` ${fmtWhen(l.utc)}` }) : null]),
    h("p", { text: friendlyLesson(l.lesson) })]);
}

async function bootEvents() {
  const box = q("camp-events");
  if (!box) return;
  clearNode(box);
  let lessons = null;
  let live = null;
  try { lessons = await get("/hounds/learning/lessons?page=1&page_size=100"); } catch (err) { lessons = null; }
  try { live = (await get("/hounds/learning")).live_challengers; } catch (err) { live = null; }
  if (!lessons) {
    box.appendChild(h("p", { class: "hd-muted", "data-hook": "camp-events-error", text: "The tryout results are not available just now." }));
    return;
  }
  const items = (lessons.items || []).filter((l) => l.outcome === "promoted" || l.outcome === "retired");
  const undecided = (lessons.items || []).filter((l) => l.outcome === "undecided").length;
  if (isNum(live)) box.appendChild(h("p", { class: "hd-fine", "data-hook": "camp-live", text: `${live} ${live === 1 ? "rookie is" : "rookies are"} trying out right now.` }));
  if (!items.length) {
    box.appendChild(h("p", { class: "hd-muted", "data-hook": "camp-events-empty",
      text: `No rookie has made the team or been cut yet${undecided ? `; ${undecided} ${undecided === 1 ? "tryout ended" : "tryouts ended"} undecided` : ""}. Promotions and cuts show up here the day they happen.` }));
    return;
  }
  box.appendChild(h("ul", { class: "dk-events", "data-hook": "camp-event-list" }, items.slice(0, 20).map(eventItem)));
}

export async function boot() {
  let goDrill = () => {};
  const dogsPromise = bootDogs((id) => goDrill(id));
  const dogs = await dogsPromise;
  goDrill = (await bootDrills(dogs)) || (() => {});
  await bootEvents();
}

if (typeof document !== "undefined" && typeof window !== "undefined") {
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();
}
