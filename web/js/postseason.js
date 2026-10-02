/**
 * MLB POSTSEASON (#/postseason, web/postseason.html, GET /postseason).
 *
 * THE FREE PAGE. Series chances, the next game of every live series with its
 * starters, and the chance each club still has to win the pennant and the
 * World Series. Public: it needs no sign-in and sends no token anywhere
 * that matters (GET /postseason is open), so it renders for a visitor who
 * has never seen the app.
 *
 * WHAT IT SAYS, AND WHAT IT REFUSES TO SAY
 * -------------------------------------------------------------------
 * Every number comes straight off the API response; this module computes
 * nothing except a bar width and a rounded percentage from a number it was
 * given. The first caveats the API sends (any note that the data is old, then
 * "model estimates, can be wrong, no track record yet") are rendered
 * verbatim, near the top, not in a footer. Nothing on the page claims an
 * edge.
 *
 * STARTERS COUNT ONLY WHEN THEY ARE CONFIRMED AND CURRENT. The API classifies
 * every starter slot (`starter_input_class`) and sends one plain-word line per
 * game (`starter_text`). A slot shows a pitcher's name only when the schedule
 * named him, otherwise "TBD": a projected pitcher is never shown there. When a
 * game's starters are not confirmed-and-current they are not in the estimate,
 * and the page says so under it, with the inputs that ARE used
 * (`inputs_used_text`). A projected-starters what-if (`scenarios`) is drawn
 * under the estimate, quieter, and labelled "scenario, not the estimate". The
 * page-level `input_summary.text` sits beside the caveats at the top.
 *
 * WHEN THE BRACKET CANNOT BE SET the API answers `available: false` with a
 * plain `reason`, and this page shows that reason instead of a bracket. It
 * does not fill the gap with anything, and it never renders the API's
 * internal `detail`.
 *
 * COLOUR. Cyan is analytical (chance bars, announced starters), amber is
 * "waiting on an input" (projected starters), red is the one call to action.
 * Club colour is identity only.
 */

import { apiGet } from "./api.js";
import { el, clear, formatSlateDate, formatLocalClock, formatLocalDate } from "./dom.js";
import { teamColors } from "./teamcolors.js";
import { NOT_ON, loadCheckoutState } from "./checkout.js";

export const POSTSEASON_PATH = "/postseason";

/**
 * The one call to action, worded from what the server can actually sell
 * (checkout.js, GET /meta billing). The static trial sentence that used to
 * sit here promised a trial on a deploy with checkout switched off.
 */
export function postseasonCtaText(state) {
  if (!state || !state.on) return "Tonight's graded card: request early access";
  return state.trialDays > 0
    ? `Tonight's graded card: start your ${state.trialDays}-day free trial`
    : "Tonight's graded card: subscribe";
}

const ROUND_ORDER = ["WC", "DS", "LCS", "WS"];
const ROUND_TITLE = {
  WC: "Wild Card Series",
  DS: "Division Series",
  LCS: "League Championship Series",
  WS: "World Series",
};
const ROUND_BEST_OF = { WC: "best of 3", DS: "best of 5", LCS: "best of 7", WS: "best of 7" };

/** A starter input class -> the tone it is drawn in, and the words used when
 * the API did not send its own `starter_text` (a cached payload from before
 * the classes existed falls back through the machine label to a class). */
const STARTER_CLASS = {
  CONFIRMED_CURRENT: { text: "Starters confirmed, current numbers used", tone: "announced" },
  PROJECTED_CURRENT: {
    text: "Starter not announced: estimate uses team results and ballpark only",
    tone: "projected",
  },
  STALE_REFERENCE_ONLY: {
    text: "Announced, but pitcher numbers on file are out of date: not used",
    tone: "projected",
  },
  UNAVAILABLE: {
    text: "Starter not announced: estimate uses team results and ballpark only",
    tone: "unknown",
  },
};
const CLASS_BY_LABEL = {
  "MODEL-USED": "CONFIRMED_CURRENT",
  "SCENARIO INPUT": "PROJECTED_CURRENT",
  UNAVAILABLE: "UNAVAILABLE",
};

const STATUS_WORD = {
  live: "LIVE",
  upcoming: "UPCOMING",
  complete: "FINAL",
  waiting: "WAITING",
};

/* ---------------------------------------------------------------------
 * Formatting -- rounding a given number, never deriving one.
 * ------------------------------------------------------------------- */

/** 0.842 -> "84%". Under half a percent reads "<1%", over 99.5 reads ">99%",
 * so a chance is never shown as an impossibility or a certainty it is not.
 * An exact 0 or 1 (a series that is over) is shown as it is. */
export function percent(p) {
  if (typeof p !== "number" || !Number.isFinite(p)) return null;
  if (p === 0) return "0%";
  if (p === 1) return "100%";
  if (p < 0.005) return "<1%";
  if (p > 0.995) return ">99%";
  return `${Math.round(p * 100)}%`;
}

function dayLabel(iso) {
  return iso ? formatSlateDate(iso) : null;
}

/** [date, clock] for one game, both in the VIEWER's own zone so they always
 * agree: a 00:00Z game is "THU OCT 1 · 5:00 PM PDT" for a viewer in Los
 * Angeles and "FRI OCT 2 · 9:00 AM GMT+9" in Tokyo. The schedule's own date
 * is a ballpark calendar date and can differ from the viewer's, so it is only
 * used when there is no start time to pair with a clock. */
export function gameWhen(game) {
  const clock = formatLocalClock(game.start_utc);
  const day = game.start_utc ? formatLocalDate(game.start_utc) : null;
  if (clock && day) return [day, clock];
  return game.date ? [dayLabel(game.date)] : [];
}

function teamLabel(team) {
  return team.name ? `${team.name}` : team.team;
}

/* ---------------------------------------------------------------------
 * Pieces
 * ------------------------------------------------------------------- */

function chanceBar(p, tone) {
  const track = el("div", { class: `ps-bar ps-bar--${tone || "chance"}`, "aria-hidden": "true" });
  const fill = el("span", { class: "ps-bar__fill" });
  const width = typeof p === "number" && Number.isFinite(p) ? Math.max(0, Math.min(1, p)) : 0;
  fill.style.width = `${(width * 100).toFixed(1)}%`;
  track.appendChild(fill);
  return track;
}

function starterClass(game) {
  return game.starter_input_class || CLASS_BY_LABEL[game.starter_label] || "UNAVAILABLE";
}

function starterTag(game) {
  const cls = starterClass(game);
  const tag = STARTER_CLASS[cls] || STARTER_CLASS.UNAVAILABLE;
  return el("span", {
    class: `ps-tag ps-tag--${tag.tone}`, "data-hook": "ps-starter-tag",
    "data-input-class": cls,
    text: game.starter_text || tag.text,
  });
}

/** The starter slot of one side: the name only when the schedule named him,
 * "TBD" otherwise, whatever the projection thinks. A named pitcher whose
 * numbers are not used says so beside his name. */
function starterName(view) {
  if (!view) return "TBD";
  if (typeof view.display === "string") {
    return view.note ? `${view.display} (${view.note})` : view.display;
  }
  // A payload from before the slot carried `display`: never show a projected
  // pitcher, and never a pitcher the schedule did not name.
  if (view.id === null || view.id === undefined || view.source !== "actual") return "TBD";
  return view.name || `pitcher ${view.id}`;
}

function teamRow(team, series, homeField) {
  const colors = teamColors(team.team);
  const row = el("div", { class: "ps-team", "data-hook": "ps-team", "data-team": team.team });
  row.style.setProperty("--team", colors.known ? colors.accent : "var(--text-mute)");
  const who = el("div", { class: "ps-team__who" });
  who.appendChild(el("span", { class: "ps-team__abbr", text: team.team }));
  const sub = [];
  if (team.name) sub.push(teamLabel(team));
  if (team.seed) sub.push(`No. ${team.seed} seed`);
  who.appendChild(el("span", { class: "ps-team__sub", text: sub.join(" · ") }));
  if (homeField === team.team && series.status !== "complete") {
    who.appendChild(el("span", { class: "ps-team__home", text: "HOME FIELD" }));
  }
  row.appendChild(who);

  const score = el("span", {
    class: "ps-team__wins", "data-hook": "ps-wins",
    "aria-label": `${team.wins} ${team.wins === 1 ? "win" : "wins"}`, text: String(team.wins),
  });
  row.appendChild(score);

  const chance = el("span", {
    class: "ps-team__chance", "data-hook": "ps-chance",
    text: percent(team.chance) || "—",
  });
  row.appendChild(chance);
  if (typeof team.chance === "number") row.appendChild(chanceBar(team.chance));
  return row;
}

function likelier(game) {
  return game.home_chance >= game.away_chance
    ? { team: game.home, p: game.home_chance } : { team: game.away, p: game.away_chance };
}

function nextGameBlock(game, series) {
  if (!game) return null;
  const block = el("div", { class: "ps-next", "data-hook": "ps-next-game" });
  const when = gameWhen(game);
  const lead = game.started ? "UNDER WAY" : "NEXT";
  block.appendChild(el("p", {
    class: "ps-next__head",
    text: `${lead} · GAME ${game.number}${when.length ? " · " + when.join(" · ") : " · date not set yet"}`,
  }));
  block.appendChild(el("p", {
    class: "ps-next__teams",
    text: `${game.away} at ${game.home}${game.venue ? " · " + game.venue : ""}`,
  }));
  const pitchers = el("p", { class: "ps-next__pitchers", "data-hook": "ps-pitchers" });
  pitchers.appendChild(document.createTextNode(
    `${game.away}: ${starterName(game.starters.away)}  ·  ${game.home}: ${starterName(game.starters.home)}`));
  block.appendChild(pitchers);
  block.appendChild(starterTag(game));
  if (game.starter_note && !game.starter_input_class) {
    block.appendChild(el("p", { class: "ps-next__note", text: game.starter_note }));
  }
  if (game.started) {
    block.appendChild(el("p", {
      class: "ps-next__note", "data-hook": "ps-started",
      text: "This game has started. Its result is not in these numbers.",
    }));
  }
  const leader = likelier(game);
  block.appendChild(el("p", {
    class: "ps-next__chance", "data-hook": "ps-game-chance",
    text: `${leader.team} ${percent(leader.p)} to win this game`,
  }));
  if (game.inputs_used_text) {
    block.appendChild(el("p", {
      class: "ps-next__inputs", "data-hook": "ps-inputs-used", text: game.inputs_used_text,
    }));
  }
  for (const scn of game.scenarios || []) block.appendChild(scenarioBlock(scn, game));
  return block;
}

/** A labelled what-if, drawn quieter than the estimate and never mistaken for
 * it. It only ever appears under a game whose starters are projected, and it
 * feeds no series or bracket number. */
function scenarioBlock(scn, game) {
  const wrap = el("div", { class: "ps-next__scenario", "data-hook": "ps-scenario" });
  wrap.appendChild(el("p", {
    class: "ps-next__scenario-tag", text: "Scenario, not the estimate",
  }));
  wrap.appendChild(el("p", { class: "ps-next__scenario-label", text: scn.label }));
  const lead = likelier({
    home: game.home, away: game.away,
    home_chance: scn.home_chance, away_chance: scn.away_chance,
  });
  wrap.appendChild(el("p", {
    class: "ps-next__scenario-chance",
    text: `${lead.team} ${percent(lead.p)} to win this game`,
  }));
  return wrap;
}

function gameList(series) {
  const games = series.games || [];
  if (!games.length) return null;
  const details = el("details", { class: "ps-games", "data-hook": "ps-games" });
  details.appendChild(el("summary", { text: "Every game in the series" }));
  const list = el("ol", { class: "ps-games__list" });
  for (const game of games) {
    const item = el("li", { class: `ps-game ps-game--${game.status}`, "data-hook": "ps-game" });
    if (game.status === "final") {
      item.appendChild(el("span", { class: "ps-game__n", text: `G${game.number}` }));
      item.appendChild(el("span", {
        class: "ps-game__body",
        text: `${game.away} ${game.away_score}, ${game.home} ${game.home_score}`,
      }));
      item.appendChild(el("span", { class: "ps-game__meta", text: `${game.winner} won` }));
    } else {
      const leader = likelier(game);
      item.appendChild(el("span", { class: "ps-game__n", text: `G${game.number}` }));
      item.appendChild(el("span", {
        class: "ps-game__body",
        text: `${game.away} at ${game.home} · ${leader.team} ${percent(leader.p)}`,
      }));
      const meta = el("span", { class: "ps-game__meta" });
      meta.appendChild(document.createTextNode(game.if_needed ? "if needed · " : ""));
      meta.appendChild(starterTag(game));
      item.appendChild(meta);
    }
    list.appendChild(item);
  }
  details.appendChild(list);
  return details;
}

function saidBefore(series) {
  if (series.status !== "complete") return null;
  const wrap = el("div", { class: "ps-said", "data-hook": "ps-said-before" });
  const before = series.said_before;
  if (!before) {
    wrap.appendChild(el("p", {
      class: "ps-said__none",
      text: series.said_before_note || "No forecast was recorded before game 1.",
    }));
    return wrap;
  }
  const parts = Object.entries(before.chance).map(([team, p]) => `${team} ${percent(p)}`);
  wrap.appendChild(el("p", {
    class: "ps-said__head",
    text: `WHAT WE SAID BEFORE GAME 1 · ${dayLabel(before.date) || before.date}`,
  }));
  wrap.appendChild(el("p", { class: "ps-said__line", text: parts.join("  ·  ") }));
  wrap.appendChild(el("p", {
    class: `ps-said__result ps-said__result--${before.rated_higher_advanced ? "right" : "wrong"}`,
    text: before.rated_higher_advanced
      ? `The team we rated higher, ${before.rated_higher}, advanced.`
      : `The team we rated higher, ${before.rated_higher}, did not advance.`,
  }));
  return wrap;
}

function seriesCard(series, byId) {
  const card = el("article", {
    class: `ps-series panel chamfer ps-series--${series.status}`,
    "data-hook": "ps-series", "data-series": series.id, "data-status": series.status,
  });
  const head = el("div", { class: "ps-series__head" });
  const league = series.league ? `${series.league} · ` : "";
  head.appendChild(el("span", { class: "ps-series__slot", text: `${league}${series.slot_label}` }));
  head.appendChild(el("span", {
    class: `ps-series__status ps-series__status--${series.status}`,
    text: STATUS_WORD[series.status] || String(series.status).toUpperCase(),
  }));
  card.appendChild(head);

  if (series.status === "waiting") {
    for (const team of series.teams) {
      const row = el("div", { class: "ps-team ps-team--bye", "data-hook": "ps-team", "data-team": team.team });
      const who = el("div", { class: "ps-team__who" });
      who.appendChild(el("span", { class: "ps-team__abbr", text: team.team }));
      who.appendChild(el("span", {
        class: "ps-team__sub",
        text: [team.name, team.seed ? `No. ${team.seed} seed` : null].filter(Boolean).join(" · "),
      }));
      row.appendChild(who);
      card.appendChild(row);
    }
    const feeders = (series.waiting_on || []).map((id) => {
      const feeder = byId[id];
      return feeder ? `${feeder.league ? feeder.league + " " : ""}${feeder.round_label} (${feeder.slot_label})` : id;
    });
    card.appendChild(el("p", {
      class: "ps-series__waiting", "data-hook": "ps-waiting",
      text: feeders.length ? `Waiting on: ${feeders.join("; ")}` : "Waiting on earlier series.",
    }));
    return card;
  }

  for (const team of series.teams) card.appendChild(teamRow(team, series, series.home_field));
  card.appendChild(el("p", {
    class: "ps-series__score", "data-hook": "ps-score",
    text: series.score_text || "",
  }));
  const next = nextGameBlock(series.next_game, series);
  if (next) card.appendChild(next);
  const said = saidBefore(series);
  if (said) card.appendChild(said);
  const games = gameList(series);
  if (games) card.appendChild(games);
  return card;
}

function roundSection(key, series, payload, byId) {
  const label = ROUND_TITLE[key];
  const section = el("section", {
    class: "ps-round", "data-hook": "ps-round", "data-round": key,
  });
  const head = el("div", { class: "sechead" });
  head.appendChild(el("span", { class: "sechead__label", text: label.toUpperCase() }));
  head.appendChild(el("span", { class: "sechead__hair" }));
  const cal = (payload.calendar || {})[label];
  const when = cal ? `${dayLabel(cal.start)} – ${dayLabel(cal.end)}` : "";
  head.appendChild(el("span", {
    class: "sechead__meta", text: [ROUND_BEST_OF[key], when].filter(Boolean).join(" · "),
  }));
  section.appendChild(head);
  const grid = el("div", { class: "ps-round__grid" });
  for (const s of series) grid.appendChild(seriesCard(s, byId));
  section.appendChild(grid);
  return section;
}

function oddsTable(payload) {
  const section = el("section", { class: "ps-odds", "data-hook": "ps-odds" });
  const head = el("div", { class: "sechead" });
  head.appendChild(el("span", { class: "sechead__label", text: "CHANCE TO WIN IT ALL" }));
  head.appendChild(el("span", { class: "sechead__hair" }));
  head.appendChild(el("span", { class: "sechead__meta", text: "most likely first" }));
  section.appendChild(head);

  const table = el("table", { class: "ps-table" });
  const thead = el("thead");
  const hr = el("tr");
  for (const label of ["Club", "Pennant", "World Series"]) {
    hr.appendChild(el("th", { scope: "col", text: label }));
  }
  thead.appendChild(hr);
  table.appendChild(thead);
  const tbody = el("tbody");
  for (const t of payload.teams || []) {
    const row = el("tr", {
      class: `ps-table__row ps-table__row--${t.status}`, "data-hook": "ps-odds-row",
      "data-team": t.team, "data-status": t.status,
    });
    const colors = teamColors(t.team);
    const who = el("th", { scope: "row", class: "ps-table__team" });
    who.style.setProperty("--team", colors.known ? colors.accent : "var(--text-mute)");
    who.appendChild(el("span", { class: "ps-table__abbr", text: t.team }));
    const detail = t.status === "alive"
      ? [t.name, `${t.league} No. ${t.seed}`]
      : [t.name, t.status_text];
    who.appendChild(el("span", { class: "ps-table__sub", text: detail.filter(Boolean).join(" · ") }));
    row.appendChild(who);
    row.appendChild(el("td", { class: "ps-table__num", text: percent(t.wins_pennant) || "—" }));
    const cell = el("td", { class: "ps-table__num ps-table__num--main" });
    cell.appendChild(el("span", { text: percent(t.wins_world_series) || "—" }));
    if (t.status !== "eliminated") cell.appendChild(chanceBar(t.wins_world_series));
    row.appendChild(cell);
    tbody.appendChild(row);
  }
  table.appendChild(tbody);
  section.appendChild(table);
  return section;
}

function trackRecord(payload) {
  const grading = payload.grading || {};
  const box = el("section", { class: "ps-record panel chamfer", "data-hook": "ps-record" });
  box.appendChild(el("p", { class: "ps-record__head", text: "HOW WE GRADE THIS" }));
  // The sentence comes from the API, written from what the forecast ledger
  // actually holds. This page promises nothing the ledger does not show.
  if (payload.grading_note) {
    box.appendChild(el("p", { class: "ps-record__body", text: payload.grading_note }));
  }
  if (grading.recorded_and_finished > 0) {
    box.appendChild(el("p", {
      class: "ps-record__tally", "data-hook": "ps-record-tally",
      text: `The team we rated higher advanced in ${grading.rated_higher_advanced} of `
        + `${grading.recorded_and_finished} series recorded before game 1. `
        + "That is too few series to say anything about accuracy.",
    }));
  }
  return box;
}

function ctaBlock(standalone, checkout) {
  const wrap = el("section", { class: "ps-cta", "data-hook": "ps-cta" });
  wrap.appendChild(el("a", {
    class: "btn btn--primary btn--lg chamfer chamfer--btn",
    href: standalone ? "index.html#/signup" : "#/signup",
    "data-hook": "postseason-cta", text: postseasonCtaText(checkout),
  }));
  wrap.appendChild(el("p", {
    class: "ps-cta__note",
    text: "The daily card is posted before first pitch and graded win or lose, every night. "
      + "No edge is claimed.",
  }));
  return wrap;
}

function methodBlock(payload) {
  const wrap = el("section", { class: "ps-method", "data-hook": "ps-method" });
  wrap.appendChild(el("p", { class: "ps-method__head", text: "HOW THESE ARE MADE" }));
  if (payload.method) wrap.appendChild(el("p", { class: "ps-method__body", text: payload.method }));
  const extra = (payload.caveats || []).slice(payload.lead_caveat_count || 1);
  if (extra.length) {
    const list = el("ul", { class: "ps-method__list" });
    for (const line of extra) list.appendChild(el("li", { text: line }));
    wrap.appendChild(list);
  }
  return wrap;
}

function header(payload) {
  const head = el("header", { class: "ps-head" });
  head.appendChild(el("p", {
    class: "ps-head__eyebrow", text: `MLB postseason${payload.season ? " · " + payload.season : ""}`,
  }));
  head.appendChild(el("h1", { class: "ps-head__title", text: "Who wins October, series by series" }));
  head.appendChild(el("p", {
    class: "ps-head__lede",
    text: "The chance each club has to win its series and the World Series, "
      + "estimated from team run rates and ballparks, with starting pitchers and "
      + "bullpens added when their numbers are current. Free to read.",
  }));
  const line = [];
  if (payload.as_of) line.push(`Scores through ${dayLabel(payload.as_of)}`);
  if (payload.live_round_label) line.push(`Now: ${payload.live_round_label}`);
  if (payload.champion) line.push(`Champion: ${payload.champion}`);
  if (line.length) {
    head.appendChild(el("p", { class: "ps-head__asof", "data-hook": "ps-as-of", text: line.join(" · ") }));
  }
  // The caveats the page leads with: a note that the data is old (when it
  // is), then "model estimates, can be wrong".
  const lead = (payload.caveats || []).slice(0, payload.lead_caveat_count || 1);
  for (const caveat of lead) {
    head.appendChild(el("p", { class: "ps-caveat", "data-hook": "ps-caveat", text: caveat }));
  }
  // And what the estimates are made from right now (which inputs are in).
  const inputs = payload.input_summary && payload.input_summary.text;
  if (inputs) {
    head.appendChild(el("p", {
      class: "ps-caveat ps-caveat--inputs", "data-hook": "ps-input-summary", text: inputs,
    }));
  }
  return head;
}

function unavailable(payload) {
  const box = el("section", { class: "ps-unavailable panel chamfer", "data-hook": "ps-unavailable" });
  box.appendChild(el("p", {
    class: "ps-unavailable__head", text: "Postseason odds are not available right now",
  }));
  box.appendChild(el("p", {
    class: "ps-unavailable__body", "data-hook": "ps-unavailable-reason",
    text: payload.reason || "Check back in a few minutes.",
  }));
  return box;
}

/** The request itself failed. One plain sentence, no status codes and no
 * technical panel: nothing a visitor can act on beyond trying again. */
function loadError(host) {
  const section = el("section", {
    class: "gate view-error chamfer state-error", role: "alert", "data-hook": "view-error",
  });
  section.appendChild(el("p", {
    class: "gate__title", text: "We could not load this page. Try again in a minute.",
  }));
  host.appendChild(section);
}

/* ---------------------------------------------------------------------
 * Entry point
 * ------------------------------------------------------------------- */

export function renderPostseasonPayload(host, payload, { standalone = false, checkout = NOT_ON } = {}) {
  clear(host);
  host.appendChild(header(payload));

  if (!payload.available) {
    host.appendChild(unavailable(payload));
    host.appendChild(ctaBlock(standalone, checkout));
    return;
  }

  const series = payload.series || [];
  const byId = {};
  for (const s of series) byId[s.id] = s;

  const bracket = el("div", { class: "ps-bracket", "data-hook": "ps-bracket" });
  for (const key of ROUND_ORDER) {
    const inRound = series.filter((s) => s.round === key);
    if (inRound.length) bracket.appendChild(roundSection(key, inRound, payload, byId));
  }
  host.appendChild(bracket);
  host.appendChild(oddsTable(payload));
  host.appendChild(trackRecord(payload));
  host.appendChild(ctaBlock(standalone, checkout));
  host.appendChild(methodBlock(payload));
}

export async function renderPostseason(container, { standalone = false } = {}) {
  clear(container);
  const screen = el("section", { class: "ps", "data-hook": "postseason-screen" });
  container.appendChild(screen);
  const host = el("div", { "data-hook": "postseason-host" });
  screen.appendChild(host);
  host.appendChild(el("p", {
    class: "ps__loading", "data-hook": "ps-loading", text: "Reading the bracket...",
  }));

  let payload;
  try {
    payload = await apiGet(POSTSEASON_PATH);
  } catch (_err) {
    clear(host);
    loadError(host);
    return;
  }
  // Never rejects: an unreadable /meta reads as "checkout not on".
  const checkout = await loadCheckoutState();
  renderPostseasonPayload(host, payload || {}, { standalone, checkout });
}
