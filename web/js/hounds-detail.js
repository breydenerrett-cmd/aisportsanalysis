/**
 * web/hound.html?id=<hound id>: one dog.
 *
 * Reads GET /hounds/{id} (a HoundSummary plus `series` and the first page of `bets`, an object
 * {items, page, page_size, total, pages}), GET /hounds/{id}/bets?page=&segment= for the other pages, and
 * GET /hounds/series?ids=<id> when the detail payload does not carry the series. The shapes are
 * src/hounds/contract.py's. Each part loads on its own and says honestly what happened when its endpoint
 * is missing.
 *
 * TOP OF THE PAGE IS THE DOG: a portrait (inline SVG wearing its vibe), name, catchphrase, bio; the
 * scoreboard (record, units, streak, this week, best bet, worst beat); what the Houndmaster said after the
 * dog's last settled day (picked by date, so it holds all day); the badge (SHARP / COIN FLIP / FEEDING THE
 * BOOK / ROOKIE) with one plain line on what it means; the rules with copy buttons ("Copy this dog's rules",
 * "Tail it", "Fade it": paper-only fun, a pasteable take, not a tip).
 * THE DETAILS ARE COLLAPSED: the verdict sentence and numbers, versions and rookies, the desk, the charts
 * (live bets only: the average price, the headline, and the best price), and every bet, paged by the server,
 * saying who decided each; a retired dog's cause of death sits at the top.
 */

import { apiGet } from "./api.js";
import {
  h, clearNode, avatarSvg, vibeOf, categoryOf, categoryLabel, houndColor, verdictLabel,
  fmtRecord, fmtClv, fmtUnits, fmtPrice, fmtWhen, shortDate, signed, isNum, whoLabel,
  normalizeSeries, pointsFor, hasForwardData, toChartPoints, segmentView, describeError, noticeLine,
  FUN_CATEGORIES, FUN_TAG, REPLAY_NOTE, NO_FORWARD_TEXT, NOT_REPORTED, dayKey, unitsPairText,
  AVERAGE_PRICE_WORDS, BEST_PRICE_WORDS, isWarming, retryWhileWarming, stopWarmingRetry, WARMING_FALLBACK_TEXT,
  VERDICT_MEANING,
} from "./hounds-core.js";
import {
  badgeFor, unitsOf, wlText, streakView, weekText, personaOf, houndmasterLine, STATUS_WORDS, causeText,
} from "./hounds-voice.js";
import { renderLineChart } from "./hounds-chart.js";
import { bootDesk } from "./hounds-desk.js";
import { bootLineage } from "./hounds-lineage.js";

export const PAGE_SIZE = 20;
const AVG_COLOR = "#00E0FF";
const BEST_COLOR = "#FFB020";

export const VIBE_LABELS = {
  degen: "Degen 🎉", nerd: "Nerd 🤓", grinder: "Grinder ⛏️", psychic: "Psychic 🔮", chaos: "Chaos 🎲", grumpy: "Boss 📣",
};

const SECTIONS = ["hound-scoreboard-section", "hound-master-section", "hound-verdict-section", "hound-rule-section",
  "hound-details"];

const state = { id: "", hound: null, houndmaster: null, bets: null, betsError: null, betSegment: "", series: null,
  seriesError: null };

const q = (hook) => document.querySelector(`[data-hook='${hook}']`);

function stateBox(kind, text, retry) {
  const box = h("div", { class: `hd-state hd-state--${kind}`, role: kind === "down" ? "alert" : "status",
    "data-hook": "section-state", "data-kind": kind }, [h("p", { text })]);
  if (retry) box.appendChild(h("button", { type: "button", class: "btn btn--ghost hd-retry", text: "Try again",
    on: { click: retry } }));
  return box;
}

// ---- copy -----------------------------------------------------------------------------------------

/** Copy text; resolves true/false. Uses the async clipboard, then the old textarea route. */
export async function copyText(text) {
  try {
    if (typeof navigator !== "undefined" && navigator.clipboard && navigator.clipboard.writeText) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch (err) { /* fall through */ }
  try {
    const area = h("textarea", { "aria-hidden": "true", readonly: "", style: "position:fixed;opacity:0;top:0;left:0" });
    area.value = text;
    document.body.appendChild(area);
    if (area.select) area.select();
    const ok = document.execCommand ? document.execCommand("copy") : false;
    document.body.removeChild(area);
    return !!ok;
  } catch (err) {
    return false;
  }
}

/** The pasteable take behind "Tail it" / "Fade it": fun for a group chat, paper only, never a tip. */
export function shareText(hound, mode) {
  const name = hound.name || "this dog";
  const rule = hound.rule_text || "";
  const tail = mode !== "fade";
  const lead = tail ? `Tailing ${name} 🐕 (paper bets only, not advice):` : `Fading ${name} 🙃 (paper bets only, not advice):`;
  const body = tail ? rule : `The opposite of: ${rule}`;
  return `${lead}\n${body}\nlinehound.app`;
}

// ---- header: the portrait ---------------------------------------------------------------------------

function renderHeader(hound) {
  const box = q("hound-header");
  clearNode(box);
  const cat = categoryOf(hound);
  const vibe = vibeOf(hound);
  const persona = personaOf(hound);
  const dead = hound.status === "retired";
  document.title = `${hound.name || "Dog"} — LINEHOUND`;
  const verified = hound.verified === true
    ? h("span", { class: "hd-verified" }, [h("span", { "aria-hidden": "true", text: "✓ " }), "verified"])
    : hound.verified === false && isNum(hound.verified_share) ? h("span", { class: "hd-unverified", text: "not verified" }) : null;
  box.appendChild(h("div", { class: "hd-portrait", "data-hook": "portrait", "data-vibe": vibe }, [
    avatarSvg(hound.name, { size: 136, category: cat, vibe, gray: dead, dead }),
    h("span", { class: "hd-portrait__tag", "data-hook": "vibe", text: VIBE_LABELS[vibe] || "" }),
  ]));
  box.appendChild(h("div", { class: "hd-hound-head__text" }, [
    h("h1", { "data-hook": "hound-name", text: hound.name || NOT_REPORTED }),
    persona && persona.catchphrase ? h("p", { class: "hd-catch", "data-hook": "catchphrase", text: `“${persona.catchphrase}”` }) : null,
    persona && persona.bio ? h("p", { class: "hd-bio", "data-hook": "bio", text: persona.bio })
      : hound.tagline ? h("p", { class: "hd-bio", "data-hook": "bio", text: hound.tagline }) : null,
    h("p", { class: "hd-badges" }, [
      cat ? h("span", { class: "hd-chip-cat", "data-category": cat, text: categoryLabel(cat) }) : null,
      FUN_CATEGORIES.includes(cat) ? h("span", { class: "hd-tag", text: FUN_TAG }) : null,
      h("span", { class: "hd-badge", text: hound.kind === "user"
        ? (hound.owner_display ? `Built by ${hound.owner_display}` : "Builder's dog") : "House dog" }),
      h("span", { class: `hd-status hd-status--${hound.status || "unknown"}`, "data-hook": "hound-status",
        text: STATUS_WORDS[hound.status] || "Status not reported" }),
      verified,
    ]),
  ]));
  // Contract: a retired hound carries `retired: {date, cause}`.
  const retired = hound.retired && typeof hound.retired === "object" ? hound.retired : null;
  const causeBox = q("hound-cause");
  clearNode(causeBox);
  if (hound.status === "retired") {
    causeBox.hidden = false;
    causeBox.removeAttribute("hidden");
    causeBox.appendChild(h("p", {}, [h("strong", { text: "Put down 💀. Cause of death: " }),
      (retired && retired.cause) ? causeText(retired.cause) : "the kennel didn't say",
      retired && retired.date ? h("span", { class: "hd-fine", text: ` (${fmtWhen(retired.date)})` }) : null]));
  } else if (hound.status === "benched" && hound.last_bet_utc) {
    causeBox.hidden = false;
    causeBox.removeAttribute("hidden");
    causeBox.appendChild(h("p", {}, [h("strong", { text: "Napping. Why: " }),
      `its last bet was ${fmtWhen(hound.last_bet_utc)}, and a dog with no bet for more than 7 days goes on the bench.`]));
  }
}

// ---- the scoreboard -------------------------------------------------------------------------------------

function tile(slot, label, big, small, tone) {
  return h("div", { class: `hd-tile hd-tile--${tone || "plain"}`, "data-slot": slot }, [
    h("span", { class: "hd-tile__label", text: label }),
    h("span", { class: "hd-tile__big", text: big }),
    small ? (typeof small === "string" ? h("span", { class: "hd-tile__small", text: small }) : small) : null,
  ]);
}

function betTile(slot, label, bet, kind) {
  if (!bet) return tile(slot, label, "none yet", kind === "best" ? "No winner on the board yet." : "No loser on the board yet.");
  const price = isNum(bet.price) ? ` at ${fmtPrice(bet.price)}` : "";
  const fair = isNum(bet.market_fair) ? ` The market had it ${Math.round(bet.market_fair * 100)}% to win.` : "";
  return tile(slot, label, `${bet.selection || NOT_REPORTED}${price}`,
    `${bet.game ? `${bet.game}. ` : ""}${fmtUnits(bet.units)}, ${shortDate(bet.date) || NOT_REPORTED}.${kind === "worst" ? fair : ""}`,
    kind === "best" ? "up" : "down");
}

export function renderScoreboard(hound) {
  const box = q("hound-scoreboard");
  clearNode(box);
  const rec = hound.record;
  const bets = rec && isNum(rec.bets) ? rec.bets : 0;
  if (bets <= 0) {
    box.appendChild(h("p", { class: "hd-muted", "data-hook": "scoreboard-empty",
      text: `${NO_FORWARD_TEXT}. This dog hasn't put a unit down yet.` }));
    return;
  }
  const units = unitsOf(hound);
  const streak = streakView(hound.form);
  const form = hound.form || {};
  const week = weekText(form);
  box.appendChild(h("div", { class: "hd-tiles", "data-hook": "scoreboard-tiles" }, [
    tile("record", "Record", wlText(rec), `${bets} ${bets === 1 ? "bet" : "bets"}${bets < 100 ? ", a small sample" : ""}`),
    tile("units", "Paper units", units === null ? NOT_REPORTED : fmtUnits(units),
      `average price; best price ${fmtUnits(rec.units_recorded_price)}`, units > 0 ? "up" : units < 0 ? "down" : "plain"),
    tile("streak", "Streak", streak ? streak.text : "none", streak ? streak.label : "no settled bets", streak ? streak.tone : "plain"),
    tile("week", "This week", week ? week.replace(" this week", "") : "quiet", week ? "last 7 days" : "no bets in the last 7 days"),
    betTile("best", "Best bet 🏆", form.best_bet, "best"),
    betTile("worst", "Worst beat 💔", form.worst_beat, "worst"),
  ]));
}

// ---- the Houndmaster ------------------------------------------------------------------------------------

export function renderMaster(hound) {
  const box = q("hound-master");
  clearNode(box);
  const said = houndmasterLine(hound, state.houndmaster);
  const last = hound.form && hound.form.last_day;
  const portrait = avatarSvg("The Houndmaster", { size: 56, vibe: "grumpy", category: "mixed" });
  if (!said) {
    box.appendChild(h("div", { class: "hd-master" }, [portrait,
      h("p", { class: "hd-master__line", "data-hook": "houndmaster-line", "data-kind": "quiet",
        text: "Nothing settled yet. The Houndmaster is watching." })]));
    return;
  }
  box.appendChild(h("div", { class: `hd-master hd-master--${said.kind}` }, [portrait,
    h("div", {}, [
      h("p", { class: "hd-master__line", "data-hook": "houndmaster-line", "data-kind": said.kind }, [
        h("strong", { text: `${said.kind === "brag" ? "Bragging" : "Roasting"}: ` }), `“${said.line}”`]),
      last ? h("p", { class: "hd-fine", "data-hook": "houndmaster-why",
        text: `After ${shortDate(last.date)}: ${last.wins}-${last.losses}, ${fmtUnits(last.units)}.` }) : null,
    ])]));
}

// ---- the badge, the numbers, the rules --------------------------------------------------------------------

function resultLines(hound) {
  const box = q("hound-results");
  clearNode(box);
  const fwd = segmentView(hound, "forward");
  const fRec = fwd && fwd.record;
  const fClv = fmtClv(fwd && fwd.clv);
  box.appendChild(h("dl", { class: "hd-row__facts hd-facts--big", "data-hook": "forward-facts" }, [
    h("div", {}, [h("dt", { text: "Live record" }), h("dd", { text: fRec && fRec.bets > 0 ? fmtRecord(fRec) : NO_FORWARD_TEXT })]),
    h("div", {}, [h("dt", { text: "Price vs the close" }), h("dd", {}, [
      fRec && fRec.bets > 0 ? fClv.main : "not measured yet",
      fRec && fRec.bets > 0 && fClv.detail ? h("span", { class: "hd-fine", text: ` (${fClv.detail})` }) : null])]),
    h("div", {}, [h("dt", { text: "First / last bet" }), h("dd", { text:
      `${fmtWhen(hound.first_bet_utc) || "none yet"} / ${fmtWhen(hound.last_bet_utc) || "none yet"}` })]),
  ]));
  if (fRec && fRec.bets > 0) {
    box.appendChild(h("p", { class: "hd-row__units", "data-hook": "units-pair",
      text: `Units two ways: ${unitsPairText(fRec)}.` }));
  }
  if (hound.verdict && hound.verdict.sentence) {
    box.appendChild(h("p", { class: "hd-verdict__sentence", "data-hook": "verdict-sentence", text: hound.verdict.sentence }));
  }
  if (hound.verdict && hound.verdict.units_note) {
    box.appendChild(h("p", { class: "hd-fine", "data-hook": "units-note", text: hound.verdict.units_note }));
  }
  const rep = hound.replay && typeof hound.replay === "object" ? hound.replay : null;
  if (rep) {
    box.appendChild(h("p", { class: "hd-row__replay", "data-hook": "replay-line" }, [
      h("strong", { text: REPLAY_NOTE }), ": ", rep.bets > 0 ? fmtRecord(rep) : "no rehearsal reported",
      rep.bets > 0 ? `; ${fmtUnits(rep.units_recorded_price)} ${BEST_PRICE_WORDS}` : ""]));
    if (rep.note) box.appendChild(h("p", { class: "hd-fine", "data-hook": "replay-note", text: rep.note }));
  }
}

function renderVerdict(hound) {
  const box = q("hound-verdict");
  clearNode(box);
  const badge = badgeFor(hound);
  box.appendChild(h("div", { class: "hd-badgeline" }, [
    h("span", { class: `hd-chip hd-chip--${badge.tone} hd-chip--lg`, "data-hook": "badge", "data-badge": badge.key,
      text: badge.text }),
    h("p", { class: "hd-badgeline__explain", "data-hook": "badge-explain", text: badge.explain }),
  ]));
  box.appendChild(h("p", { class: "hd-verdict__meaning", "data-hook": "verdict-meaning",
    text: VERDICT_MEANING[badge.label] || "No badge for this one yet. Treat the result as unproven." }));
  const rec = hound.record || (segmentView(hound, "forward") || {}).record;
  if (rec && isNum(rec.bets)) {
    box.appendChild(h("p", { class: "hd-fine", text: `Based on ${rec.bets} live ${rec.bets === 1 ? "bet" : "bets"}.${rec.bets < 100 ? " That's a small sample." : ""}` }));
  }
}

function ruleBlock(text) {
  return h("pre", { class: "hd-rule", "data-hook": "rule-text", tabindex: "0",
    text: text || "The kennel didn't send this dog's rules." });
}

function renderRule(hound, specHref) {
  const box = q("hound-rule");
  clearNode(box);
  const text = hound.rule_text || "";
  box.appendChild(ruleBlock(text));
  const status = h("span", { class: "hd-fine", role: "status", "data-hook": "copy-status" });
  const copier = (what, payload) => async () => {
    status.textContent = (await copyText(payload)) ? `Copied: ${what}.` : "Couldn't copy. Select the text and copy it by hand.";
  };
  const btn = h("button", { type: "button", class: "btn btn--primary", "data-hook": "copy-rule", text: "Copy this dog's rules",
    "aria-label": "Copy this dog's rules to the clipboard", on: { click: copier("the rules", text) } });
  const tail = h("button", { type: "button", class: "btn btn--ghost", "data-hook": "copy-tail", text: "Tail it 🐕",
    "aria-label": "Copy a take that tails this dog, paper only", on: { click: copier("a tail", shareText(hound, "tail")) } });
  const fade = h("button", { type: "button", class: "btn btn--ghost", "data-hook": "copy-fade", text: "Fade it 🙃",
    "aria-label": "Copy a take that fades this dog, paper only", on: { click: copier("a fade", shareText(hound, "fade")) } });
  if (!text) { btn.setAttribute("disabled", ""); tail.setAttribute("disabled", ""); fade.setAttribute("disabled", ""); }
  box.appendChild(h("div", { class: "hd-rule__actions" }, [btn, tail, fade,
    h("a", { class: "btn btn--ghost", href: specHref, "data-hook": "build-from", text: "Build one like this" }), status]));
  box.appendChild(h("p", { class: "hd-fine", "data-hook": "tail-fade-note",
    text: "Tail and Fade copy a take for the group chat. It's paper-only fun, not a tip." }));
}

// ---- charts ---------------------------------------------------------------------------------------

function chartWidth(panel) {
  const box = panel && panel.getBoundingClientRect ? panel.getBoundingClientRect() : null;
  const w = box && box.width ? box.width : 640;
  return Math.max(300, Math.min(760, Math.round(w)));
}

export function renderCharts() {
  const units = q("hound-units-chart");
  const clv = q("hound-clv-chart");
  clearNode(units); clearNode(clv);
  if (state.seriesError) {
    const e = describeError(state.seriesError, "the charts");
    units.appendChild(stateBox(e.kind, e.text));
    return;
  }
  if (state.series === null) {
    units.appendChild(h("p", { class: "hd-muted", text: "Loading the charts..." }));
    return;
  }
  const title = q("hound-chart-title");
  const pts = pointsFor(state.series, state.id, "forward");
  const hasPoints = pts.length > 0 || hasForwardData(state.series);
  title.textContent = hasPoints
    ? "Live bets only: placed after the rule was written."
    : "No live bets yet. This dog's old-board rehearsal, if it has one, is in the numbers and is never drawn here.";
  const width = chartWidth(units);
  units.appendChild(renderLineChart({
    hook: "units-chart",
    series: [
      { id: "avg", name: "Average price", color: AVG_COLOR, points: toChartPoints(pts, "cum_units_average_price") },
      { id: "best", name: "Best price", color: BEST_COLOR, points: toChartPoints(pts, "cum_units_recorded_price") },
    ],
    dashes: [undefined, "7 4"], width, height: width < 480 ? 240 : 300, unit: "units",
    label: "Cumulative paper units, live bets, at the average price and at the best price",
    zeroLabel: "0 units",
    emptyText: hasPoints ? "No settled bets to draw yet."
      : "No live bets yet. A rehearsal result is not drawn here.",
  }));
  units.appendChild(h("ul", { class: "hd-legend hd-legend--static" }, [
    h("li", {}, [h("span", { class: "hd-tip__swatch", style: `background:${AVG_COLOR}` }),
      ` Average price: the mean price across the books when the bet was placed (the headline)`]),
    h("li", {}, [h("span", { class: "hd-tip__swatch", style: `background:${BEST_COLOR}` }),
      ` Best price: the single best quote recorded when the bet was placed (small print)`]),
  ]));
  clv.appendChild(h("h3", { class: "hd-h3", text: "Beating the closing line? (running average)" }));
  const clvPts = toChartPoints(pts, "cum_clv_mean_pts");
  clv.appendChild(renderLineChart({
    hook: "clv-chart",
    series: [{ id: "clv", name: "Running average vs the close", color: houndColor(state.hound || {}), points: clvPts }],
    width, height: 190, unit: "pts",
    label: "Running average of price versus the closing price, in points, live bets",
    zeroLabel: "0 = same as the close",
    emptyText: "Nothing measured against the close yet.",
  }));
  clv.appendChild(h("p", { class: "hd-fine", text: "Above zero means the prices taken beat the closing line, on average so far. A handful of bets can swing it either way; the badge looks at the whole run." }));
}

// ---- bets -----------------------------------------------------------------------------------------

export function resultCell(result) {
  const r = String(result || "pending").toLowerCase();
  const map = { win: ["W", "Win", "win"], won: ["W", "Win", "win"], w: ["W", "Win", "win"],
    loss: ["L", "Loss", "loss"], lost: ["L", "Loss", "loss"], l: ["L", "Loss", "loss"],
    push: ["P", "Push", "push"], p: ["P", "Push", "push"], void: ["V", "Void", "void"], v: ["V", "Void", "void"],
    pending: ["...", "Pending", "pending"], open: ["...", "Pending", "pending"] };
  const [glyph, word, tone] = map[r] || ["?", r ? r : "Not reported", "unknown"];
  return h("span", { class: `hd-result hd-result--${tone}`, "data-result": tone }, [
    h("span", { "aria-hidden": "true", text: glyph + " " }), word]);
}

/** A page of bets as the server sends it: {items, page, page_size, total, pages}. */
function betsPageOf(data) {
  if (Array.isArray(data)) return { items: data, page: 1, page_size: data.length || PAGE_SIZE, total: data.length, pages: 1 };
  const items = Array.isArray(data && data.items) ? data.items : [];
  const total = isNum(data && data.total) ? data.total : items.length;
  const size = isNum(data && data.page_size) && data.page_size > 0 ? data.page_size : PAGE_SIZE;
  return { items, page: isNum(data && data.page) ? data.page : 1, page_size: size, total,
    pages: isNum(data && data.pages) ? data.pages : Math.max(1, Math.ceil(total / size)) };
}

function renderSegmentBar() {
  const bar = q("bets-segment");
  if (!bar) return;
  clearNode(bar);
  for (const [key, text] of [["", "All bets"], ["forward", "Live"], ["replay", "Rehearsal"]]) {
    bar.appendChild(h("button", { type: "button", class: "hd-seg", "data-segment": key || "all",
      "aria-pressed": state.betSegment === key ? "true" : "false",
      on: { click: () => { state.betSegment = key; loadBets(1); } } }, text));
  }
}

function renderBets() {
  const box = q("hound-bets");
  clearNode(box);
  renderSegmentBar();
  if (state.betsError) {
    const e = describeError(state.betsError, "the bets list");
    box.appendChild(stateBox(e.kind, e.text, () => { loadBets(state.bets ? state.bets.page : 1); }));
    return;
  }
  if (state.bets === null) { box.appendChild(h("p", { class: "hd-muted", text: "Loading the bets..." })); return; }
  const page = state.bets;
  if (page.total === 0) {
    box.appendChild(h("p", { class: "hd-muted", "data-hook": "bets-empty",
      text: state.betSegment ? `No ${state.betSegment === "forward" ? "live" : "rehearsal"} bets for this dog.` : "No bets yet. This dog hasn't put a paper unit down." }));
    return;
  }
  const head = ["Date", "Game", "Market", "Selection", "Average price", "Best price (book)", "Market fair value", "Result",
    "Units at best price", "Vs the close", "Decided by", "Why"];
  const rows = page.items.map((b) => h("tr", { "data-who": String(b.who_decided || ""), "data-segment": String(b.segment || "") }, [
    h("td", { text: shortDate(b.date) || NOT_REPORTED }),
    h("td", { text: b.game || NOT_REPORTED }),
    h("td", { text: b.market || NOT_REPORTED }),
    h("td", { text: b.selection || NOT_REPORTED }),
    h("td", { text: fmtPrice(b.price_average) }),
    h("td", { text: `${fmtPrice(b.price)}${b.book ? ` (${b.book})` : ""}` }),
    h("td", { text: isNum(b.consensus_fair) ? (b.consensus_fair > 1 || b.consensus_fair < -1 ? fmtPrice(b.consensus_fair) : `${(b.consensus_fair * 100).toFixed(1)}%`) : NOT_REPORTED }),
    h("td", {}, [resultCell(b.result), b.segment ? h("span", { class: "hd-fine", text: ` ${b.segment === "forward" ? "live" : "rehearsal"}` }) : null]),
    h("td", { text: isNum(b.units) ? fmtUnits(b.units) : NOT_REPORTED }),
    h("td", { text: isNum(b.clv_pts) ? `${signed(b.clv_pts, 1)} pts` : "not measured" }),
    h("td", {}, [h("span", { class: `hd-who hd-who--${String(b.who_decided || "unknown").toLowerCase()}`, text: whoLabel(b.who_decided) })]),
    h("td", { class: "hd-td-reason", text: b.reason || "" }),
  ]));
  box.appendChild(h("div", { class: "hd-tablewrap", tabindex: "0", role: "region", "aria-label": "Bets table, scrolls sideways on a phone" }, [
    h("table", { class: "hd-table", "data-hook": "bets-table" }, [
      h("caption", { class: "hd-sr-only", text: "This dog's paper bets, newest first as sent by the kennel" }),
      h("thead", {}, [h("tr", {}, head.map((t) => h("th", { scope: "col", text: t })))]),
      h("tbody", {}, rows)])]));
  box.appendChild(h("div", { class: "hd-pager", "data-hook": "bets-pager" }, [
    h("button", { type: "button", class: "btn btn--ghost", "data-hook": "bets-prev", text: "Newer",
      disabled: page.page <= 1 ? "" : undefined, on: { click: () => { loadBets(page.page - 1); } } }),
    h("span", { class: "hd-fine", "data-hook": "bets-page", role: "status",
      text: `Page ${page.page} of ${page.pages} (${page.total} bets)` }),
    h("button", { type: "button", class: "btn btn--ghost", "data-hook": "bets-next", text: "Older",
      disabled: page.page >= page.pages ? "" : undefined, on: { click: () => { loadBets(page.page + 1); } } }),
  ]));
}

/** One page of bets from the server (the server pages: a hound can have hundreds). */
async function loadBets(pageNo = 1) {
  state.betsError = null;
  renderBets();
  const size = state.bets ? state.bets.page_size : PAGE_SIZE;
  const seg = state.betSegment ? `&segment=${state.betSegment}` : "";
  try {
    const data = await apiGet(`/hounds/${encodeURIComponent(state.id)}/bets?page=${pageNo}&page_size=${size}${seg}`);
    state.bets = betsPageOf(data);
  } catch (err) {
    state.betsError = err;
  }
  renderBets();
}

// ---- boot -----------------------------------------------------------------------------------------

function setSections(hidden) {
  for (const hook of SECTIONS) {
    const sec = q(hook);
    if (!sec) continue;
    if (hidden) sec.setAttribute("hidden", ""); else sec.removeAttribute("hidden");
  }
}

export async function boot() {
  const params = new URLSearchParams(window.location.search || "");
  state.id = params.get("id") || "";
  const hero = q("hound-header");
  if (!state.id) {
    hero.appendChild(stateBox("missing", "No dog was chosen. Pick one from the kennel."));
    setSections(true);
    return;
  }
  let hound;
  try {
    hound = await apiGet(`/hounds/${encodeURIComponent(state.id)}`);
    if (!hound || typeof hound !== "object") throw Object.assign(new Error("empty"), { status: 404 });
  } catch (err) {
    clearNode(hero);
    const e = describeError(err, "this dog");
    hero.appendChild(stateBox(err && err.status === 404 ? "missing" : e.kind,
      err && err.status === 404 ? "There's no dog with this id. It may have been removed, or the link is wrong." : e.text,
      err && err.status === 404 ? null : () => { boot(); }));
    setSections(true);
    return;
  }
  if (isWarming(hound)) {
    // the server is still working out the numbers for the first time: say so, ask again, show nothing made up
    clearNode(hero);
    hero.appendChild(stateBox("warming", hound.message || WARMING_FALLBACK_TEXT));
    setSections(true);
    retryWhileWarming("hound", () => {
      stopWarmingRetry("hound");
      setSections(false);
      clearNode(hero);
      boot();
    }, hound);
    return;
  }
  state.hound = hound;
  state.houndmaster = hound.houndmaster && typeof hound.houndmaster === "object" ? hound.houndmaster : null;
  renderHeader(hound);
  renderScoreboard(hound);
  renderMaster(hound);
  resultLines(hound);
  renderVerdict(hound);
  renderRule(hound, `build-a-hound.html?from=${encodeURIComponent(state.id)}`);
  const notice = noticeLine(hound);
  // The page already says paper-only, not advice and 21+; the server line is shown only if it adds something.
  if (notice && !/paper only, not advice/i.test(notice)) q("hound-notice").textContent = notice;

  // the AI desk's hounds also show how they argued their newest game (every other hound never sees this)
  bootDesk(hound);

  // versions and rookies (the learning loop): loads on its own and never takes this page down
  bootLineage(hound);

  // bets: the first page rides with the detail payload; the rest are the server's pages
  if (hound.bets && typeof hound.bets === "object") { state.bets = betsPageOf(hound.bets); renderBets(); } else { loadBets(1); }

  renderCharts();
  if (Array.isArray(hound.series)) {
    state.series = normalizeSeries({ series: { [state.id]: hound.series } });
    state.seriesError = null;
  } else {
    try {
      state.series = normalizeSeries(await apiGet(`/hounds/series?ids=${encodeURIComponent(state.id)}`));
      state.seriesError = null;
    } catch (err) {
      state.series = null;
      state.seriesError = err;
    }
  }
  renderCharts();
}

export const __state = state;
export { dayKey, AVERAGE_PRICE_WORDS, verdictLabel };

if (typeof document !== "undefined" && typeof window !== "undefined") {
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();
}
