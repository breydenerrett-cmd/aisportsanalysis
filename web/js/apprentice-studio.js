/**
 * The Apprentice hound's Lessons tab (api/hounds_apprentice.py, src/hounds/apprentice).
 *
 * The owner logs the bets they really placed, by hand or from a sportsbook screenshot, and the hound learns from the
 * settled ones. Lessons are kept exactly as logged: no edit, no delete, and a state change is a new line in the history.
 * Every string from the server or the model goes into the page through h() (textContent), never as markup.
 *
 * Nothing here places a bet and nothing here claims results: numbers are the owner's own, with their sample size.
 */

import { h, clearNode, fmtPrice, isNum } from "./hounds-core.js";
import { get, post, errorText } from "./dog-common.js";

const SPORTS = ["MLB", "NFL", "NCAAF", "NBA", "WNBA", "NCAAB", "NHL", "SOCCER", "TENNIS", "MMA", "CRICKET", "RUGBY", "AFL"];
const MARKETS = [["moneyline", "Moneyline"], ["spread", "Spread"], ["total", "Total"], ["player_rushing_yards", "Rushing yards"],
  ["player_receiving_yards", "Receiving yards"], ["player_passing_yards", "Passing yards"], ["player_receptions", "Receptions"],
  ["player_anytime_td", "Anytime touchdown"], ["batter_hits", "Hits"], ["batter_total_bases", "Total bases"],
  ["batter_home_runs", "Home runs"], ["pitcher_strikeouts", "Strikeouts"], ["player_points", "Points"],
  ["player_rebounds", "Rebounds"], ["player_assists", "Assists"], ["other", "Other"]];
const SIDES = [["", "Side"], ["home", "Home"], ["away", "Away"], ["over", "Over"], ["under", "Under"]];
const STATE_WORDS = { pending: "Pending", live: "Live", settled: "Settled", void: "Void", cashed_out: "Cashed out" };
const RESULT_WORDS = { won: "Won", lost: "Lost", push: "Push" };
const MAX_IMAGE_BYTES = 4 * 1024 * 1024;
const OWNERS = [["unknown", "Whose bet: not said"], ["Brey", "Brey"], ["Jacob", "Jacob"]];
const GRADE_WORDS = { A: "A: recommended first, matched exactly", B: "B: no exact earlier match", C: "C: another bettor", D: "D: bettor not said" };

const usd = (v) => (isNum(v) ? `${v < 0 ? "-" : ""}$${Math.abs(v).toFixed(2)}` : "none yet");
const pct = (v) => (isNum(v) ? `${(v * 100).toFixed(1)}%` : "none yet");
const signed = (v) => (isNum(v) ? `${v > 0 ? "+" : ""}${v.toFixed(2)}` : "none yet");

function field(label, control) {
  return h("label", { class: "hd-fine" }, [`${label} `, control]);
}

function select(options, value = "") {
  const el = h("select", {}, options.map(([v, text]) => h("option", { value: v, text })));
  el.value = value;
  return el;
}

function numberInput(placeholder) {
  return h("input", { type: "text", inputmode: "decimal", placeholder, size: "8", autocomplete: "off" });
}

/** The local clock as an ISO instant with the device's own offset, so a typed time means what the owner meant. */
export function localToIso(text) {
  if (!text) return null;
  const d = new Date(text);
  return Number.isNaN(d.getTime()) ? null : d.toISOString();
}

export function resultLine(l) {
  if (l.disputed) return "Disputed: not counted until you resolve it";
  if (l.state === "settled") return `${RESULT_WORDS[l.result] || l.result}, ${usd(l.profit)}`;
  if (l.state === "cashed_out") return `Cashed out for ${usd(l.cash_out_amount)}, ${usd(l.profit)}`;
  if (l.state === "void") return "Void, stake returned";
  return STATE_WORDS[l.state] || l.state;
}

function legText(leg) {
  const bits = [leg.player ? `${leg.player} ` : "", leg.selection || "", leg.line !== null && leg.line !== undefined ? ` (${leg.line})` : "",
    ` at ${fmtPrice(leg.price)}`, leg.game ? `, ${leg.game}` : ""];
  return bits.join("");
}

export async function mountApprentice(host, { hound }) {
  const base = `/hounds/${encodeURIComponent(hound.id)}/apprentice`;
  const status = h("p", { class: "hd-fine", role: "status", "aria-live": "polite", "data-hook": "lessons-status" });
  const root = h("div", { "data-hook": "lessons-root" });
  host.appendChild(root);
  let board = [];

  const say = (text) => { status.textContent = text || ""; };

  async function refresh() {
    let data;
    try { data = await get(base); } catch (err) { clearNode(root).appendChild(h("p", { class: "hd-muted", text: errorText(err) })); return; }
    clearNode(root);
    root.appendChild(h("p", { class: "hd-fine", text: data.note }));
    root.appendChild(status);
    root.appendChild(analyticsBlock(data.analytics));
    if (data.can_add) {
      root.appendChild(addForm());
      root.appendChild(importBlock());
    } else {
      root.appendChild(h("p", { class: "hd-muted", text: "This hound is retired. Its lessons stay, but it takes no new ones." }));
    }
    root.appendChild(proposalBlock());
    root.appendChild(lessonList(data.lessons));
  }

  // ---- numbers ---------------------------------------------------------------------------------

  function cutTable(title, rows) {
    if (!rows || !rows.length) return null;
    return h("details", { "data-hook": "lessons-cut" }, [h("summary", { text: title }),
      h("ul", { class: "dk-tickets" }, rows.map((r) => h("li", { class: "dk-ticket" }, [
        h("strong", { text: String(r.key) }),
        ` ${r.n} bets, ${r.wins}-${r.losses}, profit ${usd(r.profit)}, return on stake ${pct(r.roi)}, win rate ${pct(r.win_rate)}`])))]);
  }

  function analyticsBlock(a) {
    const o = a.overall;
    const box = h("section", { class: "dk-panel", "data-hook": "lessons-analytics" }, [
      h("h3", { class: "hd-h3", text: "Your numbers" }),
      h("dl", { class: "kn-stats kn-stats--wide" }, [
        stat("Profit", usd(o.profit)), stat("Return on stake", pct(o.roi)), stat("Win rate", pct(o.win_rate)),
        stat("Counted", `${o.counted} of ${a.lessons}`), stat("Open", String(a.open)), stat("Disputed", String(a.disputed))]),
      h("p", { class: "hd-fine", "data-hook": "lessons-clv", text: a.clv.legs
        ? `Closing-line value on ${a.clv.legs} legs with a closing price: ${signed(a.clv.mean_pts)} points on average, ${pct(a.clv.positive)} of them positive.`
        : "Closing-line value needs a graded leg with a captured closing price. None yet." })]);
    for (const [title, key] of [["By market", "market"], ["By sport", "sport"], ["By price band", "band"], ["Favourite or plus money", "role"]]) {
      const t = cutTable(title, a.cuts[key]);
      if (t) box.appendChild(t);
    }
    const v = a.views;
    const pick = v.b_executed;
    box.appendChild(h("div", { "data-hook": "lessons-views" }, [
      h("p", { class: "hd-fine", "data-hook": "lessons-linehound", text: `Recommendations followed (grade A only): ${pick.counted} counted, ${pick.wins}-${pick.losses}${pick.pushes ? `-${pick.pushes}` : ""}, profit ${usd(pick.profit)}, return on stake ${pct(pick.roi)}. Returned ${usd(pick.returned)} on ${usd(pick.staked)} staked.` }),
      h("p", { class: "hd-fine", text: `${v.a_recommendations.published} recommendations published, ${v.a_recommendations.placed} placed, ${v.a_recommendations.unplaced} not placed. ${v.c_other_bettors.n} tickets from other bettors are left out of every number here.` })]));
    const ex = a.exposure;
    if (ex.games.length || ex.players.length) {
      box.appendChild(h("details", { "data-hook": "lessons-exposure" }, [h("summary", { text: "Bets riding on the same game or player" }),
        h("ul", {}, [...ex.games, ...ex.players].map((g) => h("li", { text: `${g.label}: ${g.lessons.length} bets, ${usd(g.staked)} staked, ${usd(g.open_staked)} still open` })))]));
    }
    return box;
  }

  function stat(label, value) {
    return h("div", {}, [h("dt", { text: label }), h("dd", { text: value })]);
  }

  // ---- by hand ---------------------------------------------------------------------------------

  function legRow(index) {
    const game = select([["", "Game from the board"]].concat(board.map((g) => [g.event_id, `${g.away_team} @ ${g.home_team}`])));
    const typed = h("input", { type: "text", placeholder: "or type the game", maxlength: "120", autocomplete: "off" });
    const sport = select([["", "Sport"]].concat(SPORTS.map((s) => [s, s])));
    const market = select([["", "Market"]].concat(MARKETS));
    const selection = h("input", { type: "text", placeholder: "Selection", maxlength: "120", autocomplete: "off" });
    const side = select(SIDES);
    const line = numberInput("Line");
    const price = numberInput("Price you got");
    const player = h("input", { type: "text", placeholder: "Player (props)", maxlength: "60", autocomplete: "off" });
    const row = h("fieldset", { class: "hd-fine", "data-hook": "lessons-leg" }, [h("legend", { text: `Leg ${index + 1}` }),
      field("Game", game), typed, field("Sport", sport), field("Market", market), field("Selection", selection), field("Side", side),
      field("Line", line), field("Price", price), field("Player", player)]);
    row.read = () => {
      const g = board.find((b) => b.event_id === game.value);
      return { event_id: g ? g.event_id : undefined, sport: g ? g.sport : sport.value, game: g ? `${g.away_team} @ ${g.home_team}` : typed.value,
        market: market.value, selection: selection.value, side: side.value || null, line: line.value || null, price: price.value, player: player.value || null };
    };
    return row;
  }

  function addForm() {
    const legs = h("div", { "data-hook": "lessons-legs" });
    const rows = [];
    const addLeg = () => { const r = legRow(rows.length); rows.push(r); legs.appendChild(r); };
    addLeg();
    const stake = numberInput("Stake, in dollars");
    const book = h("input", { type: "text", value: "DraftKings", maxlength: "40" });
    const placed = h("input", { type: "datetime-local" });
    const owner = select(OWNERS);
    const rec = h("input", { type: "text", placeholder: "Recommendation ID (if any)", maxlength: "64", autocomplete: "off" });
    const ticket = h("input", { type: "text", placeholder: "Bet ID (if any)", maxlength: "64", autocomplete: "off" });
    const total = numberInput("Combined price (parlay)");
    const submit = h("button", { type: "button", class: "lh-btn lh-btn--soft", "data-hook": "lessons-add", text: "Log this bet",
      on: { click: async () => {
        say("Saving...");
        try {
          await post(`${base}/lessons`, { legs: rows.map((r) => r.read()), stake: stake.value, book: book.value,
            placed_at: localToIso(placed.value), owner: owner.value, recommendation_id: rec.value || null, ticket_id: ticket.value || null, total_price: rows.length > 1 ? total.value || null : null });
          await refresh();
          say("Logged. It stays exactly as you entered it.");
        } catch (err) { say(fieldsText(err)); }
      } } });
    return h("section", { class: "dk-panel", "data-hook": "lessons-form" }, [h("h3", { class: "hd-h3", text: "Log a bet you placed" }),
      legs, h("button", { type: "button", class: "lh-btn lh-btn--soft", text: "Add a leg (parlay)", on: { click: addLeg } }),
      field("Stake", stake), field("Book", book), field("Placed", placed), field("Whose bet", owner), field("Recommendation", rec), field("Bet ID", ticket), field("Combined price", total), submit]);
  }

  function fieldsText(err) {
    const f = err && err.detail && err.detail.fields;
    if (f && typeof f === "object") {
      const list = Array.isArray(f) ? f.map((x) => `${x.field}: ${x.reason}`) : Object.entries(f).map(([k, v]) => `${k}: ${v}`);
      return `${errorText(err)} ${list.join("; ")}`;
    }
    return errorText(err);
  }

  // ---- screenshot import -----------------------------------------------------------------------

  function importBlock() {
    const out = h("div", { "data-hook": "lessons-draft" });
    const input = h("input", { type: "file", accept: "image/png,image/jpeg,image/webp", "data-hook": "lessons-file", "aria-label": "Bet slip screenshot" });
    input.addEventListener("change", async () => {
      const file = input.files && input.files[0];
      if (!file) return;
      if (file.size > MAX_IMAGE_BYTES) { say("That screenshot is over 4 MB. Crop it or enter the bet by hand."); return; }
      say("Reading the slip...");
      clearNode(out);
      try {
        const b64 = await toBase64(file);
        const res = await post(`${base}/import`, { image_b64: b64, utc_offset_minutes: -new Date().getTimezoneOffset() }, 60000);
        if (!res.ok) { say(res.message || "Import unavailable, enter manually."); return; }
        say("");
        out.appendChild(draftCard(res));
      } catch (err) { say(fieldsText(err)); }
    });
    return h("section", { class: "dk-panel", "data-hook": "lessons-import" }, [h("h3", { class: "hd-h3", text: "Import a bet slip screenshot" }),
      h("p", { class: "hd-fine", text: "Upload a screenshot. We read it, show you what we read, and file nothing until you confirm." }), input, out]);
  }

  function toBase64(file) {
    return new Promise((resolve, reject) => {
      const r = new FileReader();
      r.onload = () => resolve(String(r.result).split(",")[1] || "");
      r.onerror = () => reject(new Error("read"));
      r.readAsDataURL(file);
    });
  }

  function draftCard(res) {
    if (res.duplicate && !res.lesson) return h("p", { class: "hd-muted", text: "That screenshot is already filed against one of your lessons." });
    const lesson = res.lesson;
    const ambiguous = res.ambiguous || [];
    const acks = new Set();
    const card = h("div", { "data-hook": "lessons-draft-card" });
    if (res.duplicate) {
      card.appendChild(h("p", { "data-hook": "lessons-duplicate", text: `This bet is already in your lessons (same ${res.duplicate.by}). Confirming adds this screenshot and records the ticket's new status as a state change; the original stays as it was.` }));
    }
    const edits = {};
    const bind = (name, value, label) => {
      const flagged = ambiguous.find((a) => a.field === name);
      const input = h("input", { type: "text", value: value === null || value === undefined ? "" : String(value), size: "14", "aria-invalid": flagged ? "true" : "false" });
      input.addEventListener("input", () => { edits[name] = input.value; });
      const kids = [field(label, input)];
      if (flagged) {
        const box = h("input", { type: "checkbox" });
        box.addEventListener("change", () => { if (box.checked) acks.add(name); else acks.delete(name); });
        kids.push(h("span", { class: "hd-fine", "data-hook": "lessons-ambiguous", text: ` Check this: ${flagged.reason}. ` }), h("label", { class: "hd-fine" }, [box, " It is right as read"]));
      }
      return h("div", {}, kids);
    };
    card.appendChild(bind("stake", lesson.stake, "Stake"));
    card.appendChild(bind("total_price", lesson.total_price, "Combined price"));
    card.appendChild(bind("payout", lesson.payout, "To pay"));
    card.appendChild(bind("placed_at", lesson.placed_at, "Placed (UTC)"));
    card.appendChild(bind("ticket_id", lesson.ticket_id, "Bet ID"));
    card.appendChild(bind("book", lesson.book, "Book"));
    const owner = select(OWNERS);
    owner.addEventListener("change", () => { edits.owner = owner.value; });
    card.appendChild(field("Whose bet", owner));
    const rec = h("input", { type: "text", placeholder: "Recommendation ID (if any)", maxlength: "64", autocomplete: "off" });
    rec.addEventListener("input", () => { edits.recommendation_id = rec.value; });
    card.appendChild(field("Recommendation", rec));
    (lesson.legs || []).forEach((leg, i) => {
      card.appendChild(h("p", { class: "hd-fine", text: `Leg ${i + 1}: ${legText(leg)}` }));
      for (const key of ["sport", "market", "selection", "price", "line", "player", "game"]) {
        if (ambiguous.some((a) => a.field === `legs[${i}].${key}`)) card.appendChild(bind(`legs[${i}].${key}`, leg[key], `Leg ${i + 1} ${key}`));
      }
    });
    for (const a of ambiguous.filter((x) => x.field === "legs")) card.appendChild(h("p", { class: "hd-fine", "data-hook": "lessons-ambiguous", text: `Check this: ${a.reason}.` }));
    card.appendChild(h("button", { type: "button", class: "lh-btn lh-btn--soft", "data-hook": "lessons-confirm", text: "Confirm and file", on: { click: async () => {
      const merged = JSON.parse(JSON.stringify(lesson));
      for (const [name, value] of Object.entries(edits)) {
        const m = /^legs\[(\d+)\]\.(\w+)$/.exec(name);
        if (m) merged.legs[Number(m[1])][m[2]] = value; else merged[name] = value;
      }
      if (ambiguous.some((a) => a.field === "legs")) acks.add("legs");
      try {
        await post(`${base}/import/confirm`, { image_hash: res.image.hash, lesson: merged, acknowledged: Array.from(acks),
          lesson_id: res.duplicate ? res.duplicate.lesson_id : null });
        await refresh();
        say("Filed.");
      } catch (err) { say(fieldsText(err)); }
    } } }));
    return card;
  }

  // ---- the lessons -----------------------------------------------------------------------------

  function stateButtons(l) {
    const send = async (state, data) => {
      try { await post(`${base}/lessons/${encodeURIComponent(l.id)}/state`, { state, ...data }); await refresh(); } catch (err) { say(fieldsText(err)); }
    };
    const resolution = l.disputed;
    const buttons = [["Won", () => send("settled", { result: "won", resolution })], ["Lost", () => send("settled", { result: "lost", resolution })],
      ["Push", () => send("settled", { result: "push", resolution })]];
    if (!resolution) {
      buttons.push(["Void", () => send("void", {})]);
      const amount = numberInput("Cash-out $");
      buttons.push(["Cashed out", () => send("cashed_out", { cash_out_amount: Number(amount.value) })]);
      return h("p", { class: "hd-fine", "data-hook": "lessons-state" }, [...buttons.map(([t, fn]) => h("button", { type: "button", class: "lh-btn lh-btn--soft", text: t, on: { click: fn } })), amount]);
    }
    return h("p", { class: "hd-fine", "data-hook": "lessons-state" }, [`${"Resolve it as: "}`, ...buttons.map(([t, fn]) => h("button", { type: "button", class: "lh-btn lh-btn--soft", text: t, on: { click: fn } }))]);
  }

  function lessonList(items) {
    if (!items.length) return h("p", { class: "hd-muted", "data-hook": "lessons-empty", text: "No lessons yet. Log a bet you placed, or import a slip." });
    return h("ul", { class: "dk-tickets", "data-hook": "lessons-list" }, items.map((l) => h("li", { class: "dk-ticket", "data-state": l.state }, [
      h("p", {}, [h("strong", { text: `${l.bet_type === "parlay" ? `${l.legs.length}-leg parlay` : "Single"} at ${fmtPrice(l.total_price)}` }), `, ${usd(l.stake)} on ${l.book}`]),
      ...l.legs.map((leg) => h("p", { class: "hd-fine", text: legText(leg) })),
      h("p", { class: "hd-fine", "data-hook": "lessons-grade", text: `${l.owner}. Evidence ${GRADE_WORDS[l.evidence_grade] || l.evidence_grade}${l.evidence_reason ? ` (${l.evidence_reason})` : ""}` }),
      h("p", { class: "hd-fine", "data-hook": "lessons-result", text: resultLine(l) }),
      ...(l.flags || []).map((f) => h("p", { class: "hd-fine", "data-hook": "lessons-flag", text: f })),
      h("details", {}, [h("summary", { text: "History" }), h("ul", {}, l.history.map((e) => h("li", { class: "hd-fine", text: `${e.at}: ${STATE_WORDS[e.state] || e.state}${e.data && e.data.result ? ` (${e.data.result})` : ""}, from ${e.source}` })))]),
      (l.state === "pending" || l.state === "live" || l.disputed) ? stateButtons(l) : null])));
  }

  // ---- what it suggests ------------------------------------------------------------------------

  function proposalBlock() {
    const box = h("section", { class: "dk-panel", "data-hook": "lessons-proposal" }, [h("h3", { class: "hd-h3", text: "What your bets suggest" })]);
    const body = h("div", {});
    box.appendChild(body);
    box.appendChild(h("button", { type: "button", class: "lh-btn lh-btn--soft", "data-hook": "lessons-propose", text: "Look at my patterns", on: { click: async () => {
      clearNode(body);
      try {
        const card = await get(`${base}/proposal`);
        body.appendChild(h("p", { class: "hd-fine", text: `From ${card.summary.settled} settled bets, as of ${card.as_of}.` }));
        if (card.nothing) { body.appendChild(h("p", { class: "hd-muted", text: card.message })); return; }
        body.appendChild(h("ul", {}, card.changes.map((c) => h("li", { text: `${c.text}: ${c.why}` }))));
        body.appendChild(h("p", { class: "hd-fine", text: card.honesty }));
        body.appendChild(h("button", { type: "button", class: "lh-btn lh-btn--soft", "data-hook": "lessons-apply", text: "Apply as a new version (paper bets only)", on: { click: async () => {
          try { await post(`${base}/apply`, { basis: card.basis, as_of: card.as_of, confirm: true }); say("Applied. Your hound has a new version."); window.dispatchEvent(new CustomEvent("linehound:dog-saved", { detail: { type: "version", id: hound.id } })); }
          catch (err) { say(fieldsText(err)); }
        } } }));
      } catch (err) { say(fieldsText(err)); }
    } } }));
    return box;
  }

  try { board = (await get(`${base}/board`)).games || []; } catch (err) { board = []; }
  await refresh();
  return { refresh };
}
