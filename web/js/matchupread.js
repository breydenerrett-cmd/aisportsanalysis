/**
 * THE READ -- the written read of one game, at the top of the game page.
 *
 * `renderMatchupRead(read)` takes the `read` object the game route serves
 * (src/analysis/matchup_read.py) and returns one <section> node, or null when
 * the route sent none. It renders words the server wrote; it composes no claim
 * of its own, ranks nothing and computes nothing. Every number on screen is a
 * number in `read`, and each sentence's evidence sits under a native
 * <details> toggle (no script needed to open it, which also keeps the page
 * working from file://).
 *
 * LAYOUT RULE: no tables. The page has to hold at 390px without a sideways
 * scroll, so everything here is blocks that wrap, and the stylesheet gives
 * every text node overflow-wrap:anywhere (css/gamestory.css, `.mr-` rules).
 *
 * HONESTY RULES, THE SAME ONES THE SERVER WRITES BY
 * -------------------------------------------------------------------
 * - A thin-data factor says so: the confidence chip is printed on every
 *   factor and the caveat sentence is printed under it, never behind the
 *   toggle.
 * - What we could not use is listed, in words, below the read.
 * - Nothing here says a price is wrong, names a pick, or states a chance of
 *   winning. The server's market paragraph carries that boundary.
 */

import { el } from "./dom.js";
import { teamName } from "./labels.js";

/** How many factors print before the rest fold into one toggle. */
export const FACTORS_SHOWN = 5;

function evidenceValue(value) {
  if (typeof value === "number") {
    return String(Math.round(value * 1000) / 1000);
  }
  return String(value);
}

function chip(text, tone) {
  return el("span", { class: `mr-chip mr-chip--${tone}`, text });
}

function favourLabel(favours) {
  if (!favours || favours === "even") return "NO SIDE";
  return `FAVOURS ${String(teamName(favours) || favours).toUpperCase()}`;
}

function evidenceList(items) {
  const list = el("ul", { class: "mr-evidence__list" });
  for (const item of items || []) {
    const row = el("li", { class: "mr-evidence__row" });
    row.appendChild(el("span", { class: "mr-evidence__label", text: item.label }));
    const suffix = item.derived ? " (worked out from the lines on this page)" : "";
    row.appendChild(el("span", { class: "mr-evidence__value",
      text: evidenceValue(item.value) + suffix }));
    list.appendChild(row);
  }
  return list;
}

function evidenceToggle(items, hook) {
  if (!items || !items.length) return null;
  const details = el("details", { class: "mr-evidence", "data-hook": hook });
  details.appendChild(el("summary", { class: "mr-evidence__summary",
    text: `EVIDENCE (${items.length})` }));
  details.appendChild(evidenceList(items));
  return details;
}

function factorNode(factor) {
  const node = el("article", { class: "mr-factor", "data-hook": "read-factor",
    "data-factor": factor.factor });
  const head = el("div", { class: "mr-factor__head" });
  head.appendChild(el("h4", { class: "mr-factor__title", text: factor.title }));
  const chips = el("div", { class: "mr-chips" });
  chips.appendChild(chip(favourLabel(factor.favours),
    !factor.favours || factor.favours === "even" ? "plain" : "side"));
  chips.appendChild(chip(String(factor.size).toUpperCase(), "plain"));
  chips.appendChild(chip(`${String(factor.confidence).toUpperCase()} CONFIDENCE`,
    factor.confidence === "low" ? "warn" : "plain"));
  head.appendChild(chips);
  node.appendChild(head);
  node.appendChild(el("p", { class: "mr-factor__sentence", text: factor.sentence }));
  if (factor.caveat) {
    node.appendChild(el("p", { class: "mr-factor__caveat", text: factor.caveat }));
  }
  const toggle = evidenceToggle(factor.evidence, "read-evidence");
  if (toggle) node.appendChild(toggle);
  return node;
}

function subhead(text) {
  return el("h3", { class: "mr-subhead", text });
}

function paragraphs(lines, cls) {
  const wrap = el("div", { class: cls });
  for (const line of lines || []) wrap.appendChild(el("p", { text: line }));
  return wrap;
}

function range(low, high) {
  if (typeof low !== "number" || typeof high !== "number") return "";
  return `, range ${low.toFixed(1)} to ${high.toFixed(1)}`;
}

function runEnvironment(env) {
  const block = el("div", { class: "mr-block", "data-hook": "read-runs" });
  block.appendChild(subhead("EXPECTED RUNS, AN ESTIMATE"));
  if (!env) return block;
  block.appendChild(el("p", { class: "mr-small", text: env.label }));
  if (!env.available) {
    block.appendChild(el("p", { text: env.reason || "No estimate could be built from this page." }));
    return block;
  }
  const lines = [];
  for (const side of ["away", "home"]) {
    const row = env[side];
    if (!row) continue;
    lines.push(`${teamName(row.team) || row.team}: ${row.expected_runs.toFixed(1)}${range(row.low, row.high)}`);
  }
  if (env.game) {
    lines.push(`Game total: ${env.game.expected_total.toFixed(1)}${range(env.game.low, env.game.high)}`);
  }
  block.appendChild(paragraphs(lines, "mr-runs"));
  const details = el("details", { class: "mr-evidence", "data-hook": "read-arithmetic" });
  details.appendChild(el("summary", { class: "mr-evidence__summary", text: "SHOW THE ARITHMETIC" }));
  details.appendChild(paragraphs(env.arithmetic, "mr-arith"));
  details.appendChild(paragraphs(env.caveats, "mr-arith mr-arith--caveats"));
  const toggle = evidenceToggle(env.evidence, "read-runs-evidence");
  if (toggle) details.appendChild(toggle);
  block.appendChild(details);
  return block;
}

function marketView(view) {
  const block = el("div", { class: "mr-block", "data-hook": "read-market" });
  block.appendChild(subhead("WHAT THE PRICE SAYS"));
  if (!view) return block;
  block.appendChild(paragraphs(view.sentences, "mr-market"));
  const toggle = evidenceToggle(view.evidence, "read-market-evidence");
  if (toggle) block.appendChild(toggle);
  return block;
}

function changeList(items) {
  const block = el("div", { class: "mr-block", "data-hook": "read-change" });
  block.appendChild(subhead("WHAT WOULD CHANGE IT"));
  const list = el("ul", { class: "mr-list" });
  for (const item of items || []) {
    const row = el("li", { class: "mr-list__item" });
    row.appendChild(el("strong", { class: "mr-list__lead", text: item.fact }));
    row.appendChild(el("span", { class: "mr-list__body", text: " " + item.because }));
    list.appendChild(row);
  }
  block.appendChild(list);
  return block;
}

function missingList(items) {
  const block = el("div", { class: "mr-block", "data-hook": "read-missing" });
  block.appendChild(subhead(`WHAT WE COULD NOT USE (${(items || []).length})`));
  const list = el("ul", { class: "mr-list" });
  for (const item of items || []) {
    const row = el("li", { class: "mr-list__item" });
    row.appendChild(chip(String(item.status).toUpperCase(),
      item.status === "stale" || item.status === "thin" ? "warn" : "plain"));
    row.appendChild(el("strong", { class: "mr-list__lead", text: " " + item.input + ". " }));
    row.appendChild(el("span", { class: "mr-list__body", text: item.detail }));
    list.appendChild(row);
  }
  block.appendChild(list);
  return block;
}

/**
 * THE SITUATION -- where each club stands going into the game (src/situation/mlb.py). Plain
 * sentences the server wrote, each with its sample in the words; the evidence toggle lists the
 * values behind them and the foldout lists what the data could not say. Null when the read
 * carries no situation block (a page with no record shows no block, never an empty one).
 */
export function situationView(situation) {
  if (!situation || typeof situation !== "object") return null;
  const lines = Array.isArray(situation.lines) ? situation.lines : [];
  const missing = Array.isArray(situation.missing) ? situation.missing : [];
  if (!lines.length && !missing.length) return null;
  const block = el("div", { class: "mr-block", "data-hook": "read-situation" });
  block.appendChild(subhead("SITUATION"));
  if (situation.label) block.appendChild(el("p", { class: "mr-small", text: situation.label }));
  for (const line of lines) {
    block.appendChild(el("p", { class: "mr-situation__line", "data-hook": "read-situation-line",
      text: line.sentence }));
  }
  const toggle = evidenceToggle(lines.map((l) => l.evidence).filter(Boolean), "read-situation-evidence");
  if (toggle) block.appendChild(toggle);
  if (missing.length) {
    const details = el("details", { class: "mr-evidence", "data-hook": "read-situation-missing" });
    details.appendChild(el("summary", { class: "mr-evidence__summary",
      text: `WHAT THE SITUATION COULD NOT SAY (${missing.length})` }));
    const list = el("ul", { class: "mr-list" });
    for (const item of missing) {
      const row = el("li", { class: "mr-list__item" });
      row.appendChild(chip(String(item.status).toUpperCase(), item.status === "stale" ? "warn" : "plain"));
      row.appendChild(el("strong", { class: "mr-list__lead", text: " " + item.input + ". " }));
      row.appendChild(el("span", { class: "mr-list__body", text: item.detail }));
      list.appendChild(row);
    }
    details.appendChild(list);
    block.appendChild(details);
  }
  return block;
}

/** The whole read, or null when there is none to show. */
export function renderMatchupRead(read) {
  if (!read || typeof read !== "object" || !read.headline) return null;
  const host = el("section", { class: "mr-read panel chamfer", "data-hook": "matchup-read" });
  host.appendChild(el("div", { class: "mr-eyebrow", text: "THE READ" }));
  host.appendChild(el("p", { class: "mr-headline", "data-hook": "read-headline", text: read.headline }));
  for (const note of read.notices || []) {
    host.appendChild(el("p", { class: "mr-notice", "data-hook": "read-notice", text: note }));
  }
  host.appendChild(el("p", { class: "mr-small", text: read.label }));

  const factors = read.factors || [];
  if (factors.length) {
    host.appendChild(subhead("WHAT STANDS OUT, LARGEST FIRST"));
    const list = el("div", { class: "mr-factors" });
    for (const f of factors.slice(0, FACTORS_SHOWN)) list.appendChild(factorNode(f));
    host.appendChild(list);
    if (factors.length > FACTORS_SHOWN) {
      const more = el("details", { class: "mr-evidence", "data-hook": "read-more-factors" });
      more.appendChild(el("summary", { class: "mr-evidence__summary",
        text: `SMALLER FACTORS (${factors.length - FACTORS_SHOWN})` }));
      const rest = el("div", { class: "mr-factors" });
      for (const f of factors.slice(FACTORS_SHOWN)) rest.appendChild(factorNode(f));
      more.appendChild(rest);
      host.appendChild(more);
    }
  } else {
    host.appendChild(el("p", { class: "mr-factor__sentence",
      text: "No factor could be built from the data on this page." }));
  }
  const situation = situationView(read.situation);
  if (situation) host.appendChild(situation);
  host.appendChild(runEnvironment(read.run_environment));
  host.appendChild(marketView(read.market_view));
  host.appendChild(changeList(read.what_would_change_it));
  host.appendChild(missingList(read.missing));
  return host;
}
