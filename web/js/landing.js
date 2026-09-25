/**
 * Boot script for web/landing.html -- the public, standalone marketing
 * page (not part of the SPA's hash router in main.js; this page is served
 * on its own and links INTO the app via index.html#/signup).
 *
 * Three jobs, all read-only from the visitor's perspective:
 *   1. Mount the shared disclaimer footer (meta.js's renderDisclaimerFooter
 *      -- reused verbatim rather than re-implemented, so this page and the
 *      app shell can never drift on what /meta's disclaimer text says).
 *   2. Render the pricing section from the one shared price source
 *      (pricing.js's BETA_TIER -- see that module's docstring).
 *   3. Fire the anonymous `landing_view` funnel beacon (api/funnel.py).
 *
 * No customer-facing string is composed here beyond what CONTENT_LANDING.md
 * and BETA_TIER already state; this file wires DOM plumbing, not copy.
 */

import { trackFunnelEvent } from "./api.js";
import { el, clear } from "./dom.js";
import { renderDisclaimerFooter, meta as fetchMeta } from "./meta.js";
import { BETA_TIER } from "./pricing.js";
import { renderWordmark } from "./brand.js";
import { armEntrances, armParallax, armCharts } from "./motion.js";
import { mountLiveHero } from "./landing-live.js";

function renderPricing(host) {
  clear(host);
  const tier = el("dl", {
    class: "pricing-tier", "data-hook": "pricing-tier",
    "data-price": String(BETA_TIER.price_cents),
  });
  tier.appendChild(el("dt", { text: "Plan" }));
  tier.appendChild(el("dd", { "data-hook": "pricing-tier-name", text: BETA_TIER.name }));
  tier.appendChild(el("dt", { text: "Price" }));
  tier.appendChild(el("dd", { "data-hook": "pricing-tier-price", text: BETA_TIER.price_display }));
  tier.appendChild(el("dt", { text: "Note" }));
  tier.appendChild(el("dd", { "data-hook": "pricing-tier-note", text: BETA_TIER.billing_note }));
  host.appendChild(tier);
}

/**
 * PUBLIC DEMO ENTRY POINT (2026-09-07). GET /meta's `public_demo` flag
 * (api.js's isPublicDemo docstring) tells this page whether the deployed
 * server is serving the whole read-only product plus Bet Check with no
 * token. When it is, a visitor who lands here has the working product one
 * click away -- so this reveals a second, non-signup entry into it
 * ("OPEN THE LIVE DEMO" -> index.html#/today) beside the existing primary
 * CTA. Fetched once, fire-and-forget, exactly like trackFunnelEvent below:
 * a slow or failed /meta must never block or alter the page a visitor
 * already sees. When public_demo is false, or /meta cannot be reached at
 * all, the entry stays hidden and nothing else about the page changes --
 * every existing CTA, the pricing/FAQ copy and the sample-slate block are
 * untouched either way.
 */
async function revealPublicDemoEntry() {
  const host = document.querySelector("[data-hook='public-demo-entry']");
  if (!host) return;
  try {
    const meta = await fetchMeta();
    if (meta && meta.public_demo === true) host.hidden = false;
  } catch (err) {
    // /meta unreachable -- leave the entry hidden (see docstring above).
  }
}

/**
 * Replace every [data-hook="research-count"] with the registry's own figure.
 *
 * This page said "25 distinct ideas" in two places while web/js/today.js
 * said 27, web/js/betcheck.js said "twenty-seven", and
 * data/research/alpha_registry.jsonl said 40. Four numbers for one claim --
 * so a prospect read one figure on the page that sold them a subscription
 * and a different one the first time they opened the app, on a product
 * whose entire pitch is that it counts honestly.
 *
 * Same fire-and-forget rule as everything else here: the markup carries a
 * correct fallback, so a slow or failed /meta leaves a true sentence on the
 * page rather than a gap or a spinner.
 */
/**
 * WHERE A VISITOR CAME FROM, and WHICH BUTTON THEY PRESSED.
 *
 * There was no attribution of any kind: no UTM capture, no referrer, no
 * CTA-click event. The funnel recorded that somebody arrived and that
 * somebody later reached the signup form, and nothing in between -- so
 * across five calls to action, four of them with identical copy pointing
 * at the same destination, "which one works" was unanswerable. That is the
 * single question this page exists to answer, and every copy decision
 * downstream depends on it. docs/CONVERSION_INSTRUMENTATION_AUDIT.md had
 * already specified this and it was never built.
 *
 * WHAT IS DELIBERATELY NOT COLLECTED. No cookie, no fingerprint, no
 * cross-site identifier, no full referring URL -- only the referrer's HOST,
 * because "came from reddit" is the entire question and the specific thread
 * someone was reading is none of our business. UTM values are truncated and
 * capped in number so a crafted link cannot stuff the table. Everything
 * here is already in the URL the visitor arrived on or the header their
 * browser volunteered; nothing is derived, joined, or stored beyond the
 * single event row.
 */
const UTM_KEYS = ["utm_source", "utm_medium", "utm_campaign", "utm_content",
                  "utm_term"];
const UTM_MAX_LENGTH = 64;

function arrivalProperties() {
  const props = {};
  try {
    const params = new URLSearchParams(window.location.search);
    for (const key of UTM_KEYS) {
      const value = (params.get(key) || "").trim();
      if (value) props[key] = value.slice(0, UTM_MAX_LENGTH);
    }
    // HOST only, never the full referring URL. And never our own host --
    // an internal navigation is not a referral and would otherwise be the
    // most common "source" in the table.
    if (document.referrer) {
      const host = new URL(document.referrer).host;
      if (host && host !== window.location.host) props.referrer_host = host;
    }
  } catch (err) {
    // A malformed referrer or URL must never stop the page rendering.
  }
  return Object.keys(props).length ? props : undefined;
}

/**
 * One delegated listener for every CTA on the page, so a new button is
 * instrumented by carrying a `data-hook` starting with "cta" and nothing
 * else. Fire-and-forget, and deliberately NOT preventing the navigation:
 * an analytics call must never be able to swallow a click.
 */
function trackCtaClicks() {
  document.addEventListener("click", (event) => {
    const target = event.target.closest
      ? event.target.closest("[data-hook^='cta']")
      : null;
    if (!target) return;
    const hook = target.getAttribute("data-hook");
    if (!hook) return;
    const props = Object.assign({ cta: hook }, arrivalProperties() || {});
    trackFunnelEvent("cta_click", props);
  }, true);
}

async function fillResearchCounts() {
  const nodes = document.querySelectorAll("[data-hook='research-count']");
  if (!nodes.length) return;
  try {
    const meta = await fetchMeta();
    // The READ count: the sentence says "tested", and a hypothesis
    // registered ahead of its data has not been. `read` arrived 2026-09-12;
    // an older /meta without it still carries the total.
    const research = (meta && meta.research) || {};
    const n = typeof research.read === "number" ? research.read : research.hypotheses;
    if (typeof n !== "number") return;
    nodes.forEach((node) => { node.textContent = String(n); });
  } catch (err) {
    // Leave the markup's own figure in place.
  }
}

/**
 * Replace [data-hook="card-record"] with the ledger's running record.
 *
 * The sentence used to be typed: "2 wins, 1 loss ... 7 wins, 2 losses ...
 * 9 wins, 3 losses" (2026-09-12). Right that morning, wrong the morning
 * after the next settlement -- the research-count drift again, on the
 * page whose pitch is that it counts honestly. The markup's fallback names
 * no figure, so a slow or failed /meta leaves a sentence that stays true.
 */
export function recordSentence(rec) {
  if (!rec || typeof rec.wins !== "number" || typeof rec.losses !== "number"
      || typeof rec.days !== "number" || rec.days < 1) return null;
  const plural = (count, one, many) => `${count} ${count === 1 ? one : many}`;
  const parts = [plural(rec.wins, "win", "wins"), plural(rec.losses, "loss", "losses")];
  if (rec.pushes) parts.push(plural(rec.pushes, "push", "pushes"));
  if (rec.voids) parts.push(plural(rec.voids, "void", "voids"));
  const nights = rec.days === 1 ? "one night" : `${rec.days} nights`;
  return `Across ${nights} graded so far: ${parts.join(", ")}. Every one of them is on the record page.`;
}

/**
 * The hero's proof panel (2026-09-22 redesign), filled from the same
 * GET /meta card_record the record sentence reads. Figures come ONLY from
 * the ledger: on a failed fetch or a null field the markup's dashes stay.
 *
 * `profit_units` and `previous_rule` are optional. When the public card
 * changes rule, the new rule's record starts fresh, and the earlier rule's
 * figures show on their own labelled line, never added into the new one.
 */
export function proofFigures(rec) {
  if (!rec || typeof rec.wins !== "number" || typeof rec.losses !== "number") return null;
  const units = typeof rec.profit_units === "number" ? rec.profit_units : null;
  return {
    wl: `${rec.wins}–${rec.losses}`,
    units: units === null ? null : `${units >= 0 ? "+" : "−"}${Math.abs(units).toFixed(2)}`,
    unitsSign: units === null ? 0 : Math.sign(units),
    days: typeof rec.days === "number" ? String(rec.days) : null,
  };
}

async function fillProofPanel() {
  const panel = document.querySelector("[data-hook='hero-proof']");
  if (!panel) return;
  try {
    const meta = await fetchMeta();
    const current = meta && meta.card_record;
    const prevRec = current && current.previous_rule;
    // Until the current card rule has graded a night, the tiles show the
    // previous rule's record, under its own label. The new rule is still
    // named and counts separately from zero. Never merged.
    const currentUngraded = !current || !(current.days > 0);
    const showPrev = currentUngraded && proofFigures(prevRec);
    const rec = showPrev ? prevRec : current;
    const figs = proofFigures(rec);
    if (!figs) return;
    if (showPrev) {
      const title = panel.querySelector("[data-hook='proof-title']");
      if (title) title.textContent = (prevRec.label || "Our first card rule");
      const sub = panel.querySelector("[data-hook='proof-sub']");
      if (sub) {
        sub.textContent = "Our new value card has started. Its record counts separately, from zero.";
        sub.hidden = false;
      }
    }
    const set = (hook, text) => {
      const node = panel.querySelector(`[data-hook='${hook}']`);
      if (node && text) node.textContent = text;
      return node;
    };
    set("proof-wl", figs.wl);
    const unitsNode = set("proof-units", figs.units);
    if (unitsNode && figs.units) unitsNode.classList.add(figs.unitsSign >= 0 ? "is-up" : "is-down");
    set("proof-days", figs.days);
    const prev = showPrev ? null : current && current.previous_rule;
    const prevFigs = proofFigures(prev);
    if (prevFigs) {
      const sub = panel.querySelector("[data-hook='proof-sub']");
      if (sub) {
        const label = (prev && prev.label) || "Our first card rule";
        sub.textContent = `${label}: ${prevFigs.wl}${prevFigs.units ? `, ${prevFigs.units}u` : ""}`
          + `${prevFigs.days ? ` over ${prevFigs.days} nights` : ""}. Counted separately.`;
        sub.hidden = false;
      }
    }
  } catch (err) {
    // Leave the dashes in place -- never a guessed figure.
  }
}

async function fillCardRecord() {
  const nodes = document.querySelectorAll("[data-hook='card-record']");
  if (!nodes.length) return;
  try {
    const meta = await fetchMeta();
    const sentence = recordSentence(meta && meta.card_record);
    if (!sentence) return;
    nodes.forEach((node) => { node.textContent = sentence; });
  } catch (err) {
    // Leave the markup's own sentence in place.
  }
}

/**
 * THE PER-SPORT RECORD TILES (task B1/B2, 2026-09-24).
 *
 * The owner opened staging and saw one MLB-only proof panel under a hero
 * strapline that names MLB, NFL and UFC. These three tiles are the fix:
 * one per sport, each filled from GET /meta's `effective_record` (built
 * by src/report/effective_record.py, read-only over the same ledgers
 * /card/record already serves) with that sport's CURRENT rule and, right
 * beside it, the rule immediately before it -- never pooled, never
 * re-ordered by which one's return looks better (owner instruction).
 *
 * THE SAME HONEST-ABSENCE RULE AS `fillProofPanel` ABOVE. A cohort whose
 * `grading_state` is not "graded" (nothing published yet, or published
 * but not one settled night -- UFC's actual state today) never gets a
 * won-lost/units/nights figure: those three stat cells stay the markup's
 * own dashes, exactly like `recordLine` in web/js/card.js already leaves
 * them for a small sample. What DOES change is the state sentence, which
 * becomes the server's own `reason` string, rendered verbatim -- never a
 * sentence composed here about our own confidence.
 */
const SPORT_TILES = [
  { sport: "mlb", prefix: "sport-tile-mlb" },
  { sport: "nfl", prefix: "sport-tile-nfl" },
  { sport: "mma", prefix: "sport-tile-ufc" },
];

const MARKET_NAME = { game: "game", prop: "player prop", total: "run/point total" };

function tileSet(root, hook, text) {
  const node = root.querySelector(`[data-hook='${hook}']`);
  if (node && text) node.textContent = text;
  return node;
}

function cohortWL(cohort) {
  if (!cohort || typeof cohort.wins !== "number" || typeof cohort.losses !== "number") return null;
  return `${cohort.wins}–${cohort.losses}${cohort.pushes ? `-${cohort.pushes}` : ""}`;
}

function cohortUnitsText(cohort) {
  if (!cohort || typeof cohort.profit_units !== "number") return null;
  const sign = cohort.profit_units >= 0 ? "+" : "−";
  return `${sign}${Math.abs(cohort.profit_units).toFixed(2)}`;
}

/** "By market: game 3-2, player prop 5-1." -- only the markets this
 * cohort actually staked a pick in, in a fixed order, so a rule that has
 * never carried totals never shows an empty "run/point total 0-0". */
export function marketBreakdownSentence(breakdown) {
  if (!breakdown) return null;
  const parts = [];
  for (const kind of ["game", "prop", "total"]) {
    const fig = breakdown[kind];
    if (fig && fig.n_staked) parts.push(`${MARKET_NAME[kind] || kind} ${fig.wins}-${fig.losses}`);
  }
  return parts.length ? `By market: ${parts.join(", ")}.` : null;
}

/** "Our first card rule (retired): 73-40, +7.61u over 13 nights. Counted
 * separately." -- the exact sentence shape `fillProofPanel`'s own
 * previous-rule line already uses for MLB, reused here for every sport
 * that carries one, so the same rule reads the same way everywhere it
 * appears on this page. */
export function previousRuleSentence(previous) {
  if (!previous || !previous.available) return null;
  const wl = cohortWL(previous);
  if (!wl) return null;
  const units = cohortUnitsText(previous);
  const days = typeof previous.days === "number" ? previous.days : null;
  const label = previous.label || "The previous rule";
  return `${label} (retired): ${wl}${units ? `, ${units}u` : ""}`
    + `${days ? ` over ${days} night${days === 1 ? "" : "s"}` : ""}. Counted separately.`;
}

function fillSportTile(root, prefix, snapshot) {
  const current = snapshot && snapshot.current;
  const previous = snapshot && snapshot.previous;

  if (current && current.label) tileSet(root, `${prefix}-current-label`, current.label);

  const graded = current && current.available && current.grading_state === "graded";
  if (graded) {
    tileSet(root, `${prefix}-current-wl`, cohortWL(current));
    const unitsNode = tileSet(root, `${prefix}-current-units`, cohortUnitsText(current));
    if (unitsNode && typeof current.profit_units === "number") {
      unitsNode.classList.add(current.profit_units >= 0 ? "is-up" : "is-down");
    }
    tileSet(root, `${prefix}-current-days`, String(current.days));
    const dateSpan = current.date_span;
    const stateNode = root.querySelector(`[data-hook='${prefix}-current-state']`);
    if (stateNode) {
      stateNode.textContent = dateSpan && dateSpan.first && dateSpan.last
        ? `Graded nightly, ${dateSpan.first} through ${dateSpan.last}.`
        : "Graded nightly.";
    }
    const marketsNode = root.querySelector(`[data-hook='${prefix}-markets']`);
    const sentence = marketBreakdownSentence(current.market_breakdown);
    if (marketsNode && sentence) { marketsNode.textContent = sentence; marketsNode.hidden = false; }
  } else if (current && current.reason) {
    // UNGRADED, PUBLISHED, OR UNAVAILABLE -- the server's own reason,
    // verbatim, in place of the static marketing sentence. Never a
    // fabricated 0-0: the stat cells above are left exactly as the
    // markup's own dashes.
    const stateNode = root.querySelector(`[data-hook='${prefix}-current-state']`);
    if (stateNode) stateNode.textContent = current.reason;
  }

  const prevSentence = previousRuleSentence(previous);
  if (prevSentence) {
    const prevNode = root.querySelector(`[data-hook='${prefix}-previous']`);
    if (prevNode) { prevNode.textContent = prevSentence; prevNode.hidden = false; }
  }
}

async function fillSportTiles() {
  const host = document.querySelector("[data-hook='sport-record-tiles']");
  if (!host) return;
  try {
    const meta = await fetchMeta();
    const sports = meta && meta.effective_record && meta.effective_record.sports;
    if (!sports) return;
    for (const { sport, prefix } of SPORT_TILES) {
      const tile = host.querySelector(`[data-hook='${prefix}']`);
      if (tile && sports[sport]) fillSportTile(tile, prefix, sports[sport]);
    }
  } catch (err) {
    // Leave every tile's static fallback copy in place -- never a guess.
  }
}

function boot() {
  const disclaimerHost = document.querySelector("[data-hook='disclaimer-host']");
  const pricingHost = document.querySelector("[data-hook='pricing-host']");
  if (disclaimerHost) renderDisclaimerFooter(disclaimerHost);
  if (pricingHost) renderPricing(pricingHost);
  revealPublicDemoEntry();
  fillResearchCounts();
  fillCardRecord();
  fillProofPanel();
  fillSportTiles();
  // Tonight's real slate replaces the hardcoded Aug 28 sample matchup, or
  // degrades to an honest labelled-sample state on failure -- see
  // landing-live.js's module docstring. Fire-and-forget, same rule as
  // revealPublicDemoEntry: a slow/failed fetch never blocks the page.
  mountLiveHero(document);
  // Wordmarks are markup-authored today (see brand.js's docstring on why
  // <title> and the static text stay literal), but every mark carries the
  // hook so a future rename only has to touch BRAND_NAME plus these two
  // literal strings, not hunt through the design-system CSS.
  document.querySelectorAll("[data-hook='brand-mark']").forEach((host) => renderWordmark(host));
  // With WHERE THEY CAME FROM attached. `properties` has been supported
  // end to end by api/funnel.py since it existed and had no caller, so
  // every landing view until now was an unattributed tally.
  trackFunnelEvent("landing_view", arrivalProperties());
  trackCtaClicks();
  // Design-system motion (handoff section 08) -- content renders complete
  // and static if this never runs; see motion.js's fail-safe-reveal note.
  armEntrances(document);
  armParallax(document);
  armCharts(document);
}

document.addEventListener("DOMContentLoaded", boot);
