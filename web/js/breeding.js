/**
 * The breeding program's family tree: a self-contained section any Hounds page can mount.
 *
 *   import { renderBreeding } from "./breeding.js";
 *   renderBreeding(document.querySelector("[data-hook='breeding']"));
 *
 * Reads GET /hounds/breeding (src/hounds/breeding/cycle.py: family_tree):
 *   {enabled, paused, pause_reason, next_cycle_utc, cadence_days,
 *    generations: [{generation, members: [ref]}],
 *    babies: [{challenger_id, hound_id, generation, litter, born_cycle, parents: [ref], values, mutation,
 *              status, outcome_reason, record: {w, l, p, settled, clv_mean, units}}],
 *    culls: [{cycle_date, action, member}], refusals: [{cycle_date, hound_id, litter, code, message, parents}],
 *    cycles: [{cycle_date, outcome, reason, births}],
 *    eligibility: [{ref, name, role, generation, settled, need, eligible, shrunk_clv, record}], rules}
 *
 * WHAT IT SAYS (docs/PREREG_BREEDING.md). Generations are rows; each baby shows its parents and a status
 * chip; the next cycle counts down; every member's progress to the 25 settled forward bets it needs before
 * it can breed is a bar. A baby starts at 0-0 and is only a challenger: the referee alone can promote it.
 * Parents are chosen on forward closing-line value only, never on hindsight. Paper only.
 *
 * Self-contained on purpose (no DOM helpers, no page globals): the markup is built as an escaped string by
 * the pure ``breedingHtml`` so it can be tested under node, and ``renderBreeding`` only fetches, writes
 * ``container.innerHTML`` and runs the countdown. A failed fetch writes a calm line, never a broken page.
 */

export const BREEDING_URL = "/hounds/breeding";
export const BREEDING_NOTE =
  "Every 3 days the fittest members of each model's family, ranked on forward closing-line value only, " +
  "get at most 2 babies. A baby starts at 0-0 and runs in shadow; only the referee's pre-registered " +
  "paired test can promote it. The worst members with 40 or more bets and a negative score are culled. " +
  "Paper only. No real bet is ever placed. Not advice.";

const STYLE = `
.brd{--brd-bg:var(--tile-base,#0E1013);--brd-edge:var(--edge-1,rgba(255,255,255,.07));--brd-text:var(--text,#F2F4F8);
--brd-mute:var(--text-mute,#8A919E);--brd-good:#2ED47A;--brd-bad:#FF3D57;--brd-warn:#FFB020;--brd-flat:#B9C0CC;
--brd-live:var(--live,#00E0FF);color:var(--brd-text);font-family:var(--font-body,system-ui,sans-serif);
background:var(--brd-bg);border:1px solid var(--brd-edge);padding:16px;margin:16px 0}
.brd h2{font-family:var(--font-display,'Arial Narrow',sans-serif);text-transform:uppercase;letter-spacing:.04em;
font-size:22px;margin:0 0 6px}
.brd h3{font-size:14px;text-transform:uppercase;letter-spacing:.06em;color:var(--brd-mute);margin:18px 0 8px}
.brd p{margin:4px 0;line-height:1.45}
.brd .brd-note{color:var(--brd-mute);font-size:13px}
.brd .brd-top{display:flex;flex-wrap:wrap;gap:12px;align-items:baseline;justify-content:space-between}
.brd .brd-count{font-family:var(--font-mono,monospace);font-size:15px;color:var(--brd-live)}
.brd .brd-gen{display:flex;gap:10px;align-items:flex-start;border-top:1px solid var(--brd-edge);padding:10px 0;
overflow-x:auto}
.brd .brd-gen-label{flex:0 0 92px;font-family:var(--font-mono,monospace);font-size:12px;color:var(--brd-mute);
text-transform:uppercase;padding-top:4px}
.brd .brd-row{display:flex;flex-wrap:wrap;gap:8px}
.brd .brd-node{border:1px solid var(--brd-edge);padding:6px 10px;font-size:13px;background:rgba(255,255,255,.02);
min-width:0;max-width:100%}
.brd .brd-node b{display:block;font-size:13px;word-break:break-all}
.brd .brd-parents{color:var(--brd-mute);font-size:12px;word-break:break-all}
.brd .brd-chip{display:inline-block;padding:2px 8px;font-weight:800;font-size:11px;letter-spacing:.03em;border:1px solid;
margin-top:4px}
.brd .brd-chip--good{color:var(--brd-good);border-color:var(--brd-good);background:rgba(46,212,122,.1)}
.brd .brd-chip--bad{color:var(--brd-bad);border-color:var(--brd-bad);background:rgba(255,61,87,.1)}
.brd .brd-chip--early{color:var(--brd-warn);border-color:var(--brd-warn);background:rgba(255,176,32,.09)}
.brd .brd-chip--flat{color:var(--brd-flat);border-color:var(--brd-flat)}
.brd table{width:100%;border-collapse:collapse;font-size:13px}
.brd th,.brd td{text-align:left;padding:6px 8px;border-top:1px solid var(--brd-edge);vertical-align:middle}
.brd th{color:var(--brd-mute);font-weight:600;font-size:12px;text-transform:uppercase}
.brd .brd-bar{position:relative;height:8px;background:rgba(255,255,255,.07);min-width:80px}
.brd .brd-bar span{position:absolute;left:0;top:0;bottom:0;background:var(--brd-live)}
.brd .brd-bar--done span{background:var(--brd-good)}
.brd .brd-num{font-family:var(--font-mono,monospace);white-space:nowrap}
.brd ul{margin:4px 0;padding-left:18px}
.brd li{margin:2px 0;font-size:13px}
.brd .brd-scroll{overflow-x:auto}
`;

export function esc(value) {
  return String(value === undefined || value === null ? "" : value)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

function isNum(v) {
  return typeof v === "number" && Number.isFinite(v);
}

function signed(v, digits = 2) {
  if (!isNum(v)) return "not measured";
  const s = v.toFixed(digits);
  return v > 0 ? `+${s}` : s;
}

/** "2d 4h 10m" until the next cycle; "due at the next capture slot" once it has passed. */
export function countdownText(nextUtc, nowMs) {
  const target = Date.parse(nextUtc || "");
  if (!Number.isFinite(target)) return "next cycle time unknown";
  let left = Math.floor((target - nowMs) / 60000);
  if (left <= 0) return "due at the next capture slot";
  const d = Math.floor(left / 1440); left -= d * 1440;
  const h = Math.floor(left / 60); const m = left - h * 60;
  return `${d}d ${h}h ${m}m`;
}

/** The chip for a baby's status on the referee. */
export function statusChip(status, reason) {
  if (status === "live") return { label: "IN SHADOW", tone: "early" };
  if (status === "promoted") return { label: "PROMOTED", tone: "good" };
  if (status === "retired" && reason === "harm") return { label: "HURT", tone: "bad" };
  if (status === "retired" && reason === "breeding_cull") return { label: "CULLED", tone: "bad" };
  if (status === "retired") return { label: "RETIRED", tone: "flat" };
  if (status === "undecided" && reason === "expired") return { label: "TOO EARLY", tone: "early" };
  if (status === "undecided") return { label: "CLOSED", tone: "flat" };
  return { label: "UNKNOWN", tone: "flat" };
}

function chip(c) {
  return `<span class="brd-chip brd-chip--${esc(c.tone)}" data-hook="brd-chip">${esc(c.label)}</span>`;
}

function recordText(r) {
  if (!r) return "0-0";
  const base = `${r.w || 0}-${r.l || 0}${r.p ? `-${r.p}` : ""}`;
  return isNum(r.clv_mean) ? `${base}, CLV ${signed(r.clv_mean)}` : base;
}

function knobText(values) {
  return Object.keys(values || {}).sort().map((k) => `${k} ${values[k]}`).join(", ");
}

function babyNode(b) {
  const parents = (b.parents || []).join(" + ");
  return `<div class="brd-node" data-hook="brd-baby" data-id="${esc(b.challenger_id)}">` +
    `<b>${esc(b.hound_id)} &middot; ${esc(b.challenger_id)}</b>` +
    `<div class="brd-parents">parents: ${esc(parents || "none recorded")} &rarr; born ${esc(b.born_cycle || "")}</div>` +
    `<div class="brd-parents">${esc(knobText(b.values))}</div>` +
    `<div class="brd-num">${esc(recordText(b.record))}</div>${chip(statusChip(b.status, b.outcome_reason))}</div>`;
}

function founderNode(ref) {
  return `<div class="brd-node" data-hook="brd-founder"><b>${esc(ref)}</b></div>`;
}

function barRow(e) {
  const need = isNum(e.need) && e.need > 0 ? e.need : 25;
  const have = isNum(e.settled) ? e.settled : 0;
  const pct = Math.max(0, Math.min(100, Math.round((100 * have) / need)));
  return `<tr data-hook="brd-elig"><td>${esc(e.name || e.hound_id)}<div class="brd-parents">${esc(e.ref)} &middot; ` +
    `${esc(e.role)}</div></td>` +
    `<td><div class="brd-bar${e.eligible ? " brd-bar--done" : ""}" role="progressbar" aria-valuemin="0" ` +
    `aria-valuemax="${need}" aria-valuenow="${Math.min(have, need)}"><span style="width:${pct}%"></span></div></td>` +
    `<td class="brd-num">${have}/${need} bets</td>` +
    `<td class="brd-num">${e.eligible ? esc(signed(e.shrunk_clv, 3)) : "&mdash;"}</td></tr>`;
}

/** The whole section as an escaped HTML string. Pure: payload in, markup out. */
export function breedingHtml(p, nowMs = Date.now()) {
  if (!p || typeof p !== "object") {
    return `<section class="brd" data-hook="brd-root"><style>${STYLE}</style>` +
      `<p class="brd-note">The breeding program could not be read right now.</p></section>`;
  }
  const babies = Array.isArray(p.babies) ? p.babies : [];
  const gens = Array.isArray(p.generations) ? p.generations : [];
  const elig = Array.isArray(p.eligibility) ? p.eligibility : [];
  const state = p.paused ? `Paused: ${p.pause_reason || "the owner must resume it"}`
    : (p.enabled === false ? "Switched off by the owner" : "Running");
  const parts = [`<section class="brd" data-hook="brd-root" aria-label="Breeding program"><style>${STYLE}</style>`];
  parts.push(`<div class="brd-top"><h2>Breeding program</h2>` +
    `<span class="brd-count" data-hook="brd-countdown" data-next="${esc(p.next_cycle_utc || "")}">` +
    `Next cycle in ${esc(countdownText(p.next_cycle_utc, nowMs))}</span></div>`);
  parts.push(`<p data-hook="brd-state">${esc(state)} &middot; every ${esc(p.cadence_days || 3)} days &middot; ` +
    `${esc(p.live_babies || 0)} live ${p.live_babies === 1 ? "baby" : "babies"}</p>`);
  parts.push(`<p class="brd-note" data-hook="brd-note">${esc(BREEDING_NOTE)}</p>`);

  parts.push(`<h3>Family tree</h3>`);
  if (!babies.length) {
    parts.push(`<p class="brd-note" data-hook="brd-empty">No babies yet. A member needs 25 settled forward bets ` +
      `before it can be a parent; until then each cycle records "no eligible parents" and does nothing.</p>`);
  }
  for (const g of gens) {
    const n = g.generation;
    const label = n === 0 ? "Founders" : `Gen ${esc(n)}`;
    const row = n === 0 ? (g.members || []).map(founderNode)
      : babies.filter((b) => b.generation === n).map(babyNode);
    parts.push(`<div class="brd-gen" data-hook="brd-gen" data-gen="${esc(n)}"><div class="brd-gen-label">${label}</div>` +
      `<div class="brd-row">${row.join("")}</div></div>`);
  }

  parts.push(`<h3>Eligibility (forward bets only)</h3>`);
  parts.push(`<div class="brd-scroll"><table data-hook="brd-table"><thead><tr><th>Member</th><th>Progress</th>` +
    `<th>Settled</th><th>Shrunk CLV</th></tr></thead><tbody>${elig.map(barRow).join("")}</tbody></table></div>`);

  const culls = Array.isArray(p.culls) ? p.culls : [];
  parts.push(`<h3>Culled</h3>`);
  parts.push(culls.length ? `<ul data-hook="brd-culls">${culls.map((c) => {
    const m = c.member || {};
    return `<li>${esc(c.cycle_date)}: ${esc(m.ref || m.id)} (${esc(m.settled)} bets, shrunk CLV ` +
      `${esc(signed(m.shrunk_clv, 3))}) &rarr; ${esc(c.action === "retired" ? "retired" : "replacement proposed")}</li>`;
  }).join("")}</ul>` : `<p class="brd-note" data-hook="brd-culls-empty">Nobody has been culled.</p>`);

  const refusals = Array.isArray(p.refusals) ? p.refusals : [];
  if (refusals.length) {
    parts.push(`<h3>Babies the guards refused</h3><ul data-hook="brd-refusals">${refusals.map((r) =>
      `<li>${esc(r.cycle_date)}: ${esc(r.hound_id)} (${esc((r.parents || []).join(" + "))}) &mdash; ` +
      `${esc(r.code)}: ${esc(r.message)}</li>`).join("")}</ul>`);
  }
  const cycles = Array.isArray(p.cycles) ? p.cycles.slice(-6).reverse() : [];
  if (cycles.length) {
    parts.push(`<h3>Recent cycles</h3><ul data-hook="brd-cycles">${cycles.map((c) =>
      `<li>${esc(c.cycle_date)}: ${esc(c.outcome)} &mdash; ${esc(c.reason)}</li>`).join("")}</ul>`);
  }
  parts.push(`</section>`);
  return parts.join("");
}

/**
 * Fetch the family tree and render it into ``container``. Options (all optional): ``get(url)`` returns the
 * payload (default: api.js's apiGet), ``now()`` the clock in ms, ``timer`` false to skip the countdown.
 * Returns the payload (or null on failure).
 */
export async function renderBreeding(container, opts = {}) {
  if (!container) return null;
  const now = opts.now || (() => Date.now());
  let payload = null;
  try {
    const get = opts.get || (await import("./api.js")).apiGet;
    payload = await get(BREEDING_URL);
  } catch (err) {
    payload = null;
  }
  container.innerHTML = breedingHtml(payload, now());
  if (payload && opts.timer !== false && typeof setInterval === "function" && container.querySelector) {
    const id = setInterval(() => {
      const el = container.querySelector("[data-hook='brd-countdown']");
      if (!el) { clearInterval(id); return; }
      el.textContent = `Next cycle in ${countdownText(payload.next_cycle_utc, now())}`;
    }, 30000);
  }
  return payload;
}
