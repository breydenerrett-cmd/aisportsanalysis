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

import { apiGet, trackFunnelEvent } from "./api.js";
import { el, clear } from "./dom.js";
import {
  FILL_TAG, POSTSEASON_TAG_SAMPLE, dayEntries, entryRow, isHeavyFavourite, tallyText,
} from "./entrytext.js";
import { renderDisclaimerFooter, meta as fetchMeta } from "./meta.js";
import { BETA_TIER } from "./pricing.js";
import {
  loadCheckoutState, NOT_ON, ctaLabel, heroNote, pricingNote, trialPhrase, monthlyPrice,
} from "./checkout.js";
import { renderWordmark } from "./brand.js";
import { armEntrances, armParallax, armCharts } from "./motion.js";
import { mountLiveHero } from "./landing-live.js";
import { captureFirstTouch } from "./attribution.js";

function renderPricing(host, state) {
  clear(host);
  if (!state.on) {
    // Checkout is not open: the planned price and nothing more -- no plan
    // story, no trial, no "cancel anytime" (checkout.js).
    const planned = el("p", {
      class: "pricing-tier", "data-hook": "pricing-tier",
      "data-price": String(BETA_TIER.price_cents),
    });
    planned.appendChild(el("span", { "data-hook": "pricing-tier-note", text: pricingNote(state) }));
    host.appendChild(planned);
    return;
  }
  const tier = el("dl", {
    class: "pricing-tier", "data-hook": "pricing-tier",
    "data-price": String(BETA_TIER.price_cents),
  });
  tier.appendChild(el("dt", { text: "Plan" }));
  tier.appendChild(el("dd", { "data-hook": "pricing-tier-name", text: BETA_TIER.name }));
  const price = monthlyPrice(state.priceCents);
  if (price) {
    tier.appendChild(el("dt", { text: "Price" }));
    tier.appendChild(el("dd", { "data-hook": "pricing-tier-price", text: price }));
  }
  tier.appendChild(el("dt", { text: "Note" }));
  tier.appendChild(el("dd", { "data-hook": "pricing-tier-note", text: pricingNote(state) }));
  host.appendChild(tier);
}

/**
 * EVERY PAYING-RELATED WORD ON THIS PAGE, FROM /meta (2026-10-01).
 *
 * The markup carries the CAUTIOUS wording -- checkout.js's CAUTIOUS_CTA, the planned price, no trial badge, no "cancel anytime" line -- so a
 * crawler, a slow connection and a deploy with checkout off all read the true
 * thing. This upgrades it to the trial wording only when GET /meta says
 * checkout is "on", using that response's own trial length and price
 * (checkout.js is the one decision shared with the signup, sign-in and record
 * pages). The buttons keep their href: the signup page saves the email.
 */
export function applyCheckoutCopy(state) {
  document.querySelectorAll("[data-checkout-cta]").forEach((node) => {
    node.textContent = ctaLabel(state);
  });
  const note = document.querySelector("[data-hook='hero-cta-note']");
  if (note) note.textContent = heroNote(state);
  const badge = document.querySelector("[data-hook='pricing-trial-badge']");
  if (badge) {
    const phrase = trialPhrase(state);
    badge.textContent = phrase || "";
    badge.hidden = !phrase;
  }
  const cancelLine = document.querySelector("[data-hook='pricing-cancel-line']");
  if (cancelLine) cancelLine.hidden = !state.on;
  const pricingHost = document.querySelector("[data-hook='pricing-host']");
  if (pricingHost) renderPricing(pricingHost, state);
}

async function fillCheckoutCopy() {
  applyCheckoutCopy(await loadCheckoutState());
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
 * THE PER-SPORT RECORD TILES (task B1/B2, 2026-09-24; unified with the
 * hero panel 2026-09-25 per owner review).
 *
 * The owner opened staging and saw one MLB-only proof panel under a hero
 * strapline that names MLB, NFL and UFC. These three tiles are the fix:
 * one per sport, each filled from GET /meta's `effective_record` (built
 * by src/report/effective_record.py, read-only over the same ledgers
 * /card/record already serves) with that sport's CURRENT rule and, right
 * beside it, the rule immediately before it -- never pooled, never
 * re-ordered by which one's return looks better (owner instruction).
 *
 * OWNER REVIEW, 2026-09-25 -- TWO BUGS IN THE FIRST VERSION OF THIS
 * SECTION, BOTH FIXED HERE TOGETHER:
 *
 * 1. PROMINENCE WAS NOT IDENTICAL. The current rule got three large
 *    `.hero__stat` cells; the previous rule got one small grey sentence
 *    (`previousRuleSentence`, rendered into a `<p class="hero__proof-sub">`
 *    with no stat cells of its own) -- in the hero panel and every sport
 *    tile alike. `fillRuleBlock` below is now the ONE renderer for BOTH
 *    roles: current and previous each get the identical
 *    `.hero__proof-grid` of three `.hero__stat` cells, at the identical
 *    size, the only difference being which `data-hook` prefix
 *    ("...-current-..." vs "...-previous-...") and role label ("Current
 *    rule" vs "Previous rule (retired)") it is called with. The two
 *    blocks are always both present in the markup, in the SAME FIXED
 *    ORDER (current first, then previous -- see web/landing.html), which
 *    never depends on which one is currently profitable.
 *
 * 2. ASYMMETRIC COLOUR. is-up/is-down was only ever applied to the
 *    CURRENT cohort's units cell; the previous cohort's units rendered in
 *    plain white regardless of sign. `fillRuleBlock` applies the exact
 *    same `cohort.profit_units >= 0 ? "is-up" : "is-down"` rule to
 *    whichever cohort it is called with -- current and previous both, no
 *    special-casing either.
 *
 * THE HERO PANEL NOW READS `meta.effective_record.sports.mlb` AND CALLS
 * THIS SAME `fillRuleBlock` (see `fillProofPanel` below), not a
 * separately-derived `meta.card_record`. This is what makes "the hero's
 * previous-rule figure equals the MLB tile's previous-rule figure" true
 * by construction rather than by two independently-written formulas
 * happening to agree -- the root cause of the 73-40/151-79 mismatch this
 * review found (see api/meta.py's `_card_record` for the matching API-
 * level fix, which keeps GET /meta's `card_record.previous_rule` field
 * itself correct for any other reader).
 *
 * THE SAME HONEST-ABSENCE RULE AS ALWAYS, FOR A COHORT THAT EXISTS. A
 * cohort whose `grading_state` is not "graded" (nothing published yet,
 * or published but not one settled night -- NFL's real current state
 * today) never gets a won-lost/units/nights figure: those three stat
 * cells stay the markup's own dashes, exactly like `recordLine` in
 * web/js/card.js already leaves them for a small sample. What DOES
 * change is the state sentence, which becomes the server's own `reason`
 * string, rendered verbatim -- never a sentence composed here about our
 * own confidence.
 *
 * A DIFFERENT RULE FOR A PREDECESSOR THAT DOES NOT EXIST AT ALL (owner
 * review, 2026-09-25, second pass). UFC has never had a previous rule --
 * `effective_record.mma_snapshot`'s `previous` is `None`, not an
 * unavailable/ungraded cohort. Rendering a dash-filled "PREVIOUS RULE
 * (RETIRED)" block for that case would imply a rule that never existed,
 * so `fillRuleSet` (below) omits the previous block ENTIRELY -- `hidden
 * = true` on the block itself -- whenever `snapshot.previous` is
 * null/undefined, and never calls `fillRuleBlock` for it at all. This is
 * the one place role (current vs previous) is allowed to change WHETHER
 * a block renders; `fillRuleBlock` itself still never branches on role
 * once a block reaches it.
 */
const RULE_BLOCKS = [
  { role: "current", label: "Current method" },
  { role: "previous", label: "Earlier method (retired)" },
];

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

/**
 * Fills ONE rule-block -- `${prefix}-wl` / `${prefix}-units` /
 * `${prefix}-days` stat cells, `${prefix}-label` and `${prefix}-state` --
 * from ONE cohort. Called identically for "current" and "previous" (see
 * `fillRuleSet` below): there is no branch anywhere in this function on
 * WHICH role it is filling, only on whether the cohort it was GIVEN is
 * graded -- the one asymmetry this page is allowed to have, and it is a
 * data fact (a rule that hasn't graded a night has no W-L to show),
 * never a role-based styling decision.
 */
function fillRuleBlock(root, prefix, cohort, roleLabel) {
  const labelNode = root.querySelector(`[data-hook='${prefix}-label']`);
  if (labelNode) labelNode.textContent = roleLabel;

  const stateNode = root.querySelector(`[data-hook='${prefix}-state']`);
  const graded = cohort && cohort.available && cohort.grading_state === "graded";

  if (graded) {
    tileSet(root, `${prefix}-wl`, cohortWL(cohort));
    const unitsNode = tileSet(root, `${prefix}-units`, cohortUnitsText(cohort));
    if (unitsNode && typeof cohort.profit_units === "number") {
      unitsNode.classList.add(cohort.profit_units >= 0 ? "is-up" : "is-down");
    }
    tileSet(root, `${prefix}-days`, String(cohort.days));
    if (stateNode) {
      const dateSpan = cohort.date_span;
      const span = dateSpan && dateSpan.first && dateSpan.last
        ? `${dateSpan.first} through ${dateSpan.last}` : null;
      const named = cohort.label ? `${cohort.label}. ` : "";
      // UFC has no results feed: a person enters each result after the
      // event (src/pipeline/ufc_results.py), so "nightly" was untrue on
      // that one tile the first time it had a graded record to show.
      const cadence = /(^|-)ufc-/.test(prefix) ? "Graded by hand after each event" : "Graded nightly";
      stateNode.textContent = `${named}${cadence}${span ? `, ${span}` : ""}.`;
    }
    const marketsNode = root.querySelector(`[data-hook='${prefix}-markets']`);
    const sentence = marketBreakdownSentence(cohort.market_breakdown);
    if (marketsNode) {
      if (sentence) { marketsNode.textContent = sentence; marketsNode.hidden = false; }
      else { marketsNode.hidden = true; }
    }
  } else if (cohort && cohort.reason) {
    // UNGRADED, PUBLISHED, OR UNAVAILABLE -- a predecessor EXISTS (this
    // is a real cohort object, just not a graded one -- e.g. a rule that
    // was retired before it ever settled a night) -- the server's own
    // reason, verbatim, in place of the static marketing sentence. Never
    // a fabricated 0-0: the stat cells above are left exactly as the
    // markup's own dashes. This block stays VISIBLE -- see fillRuleSet,
    // which is the only place that decides whether a block renders at
    // all; a cohort reaching this function at all means it should.
    if (stateNode) stateNode.textContent = cohort.reason;
  }

  // POSTSEASON, GRADED BUT NOT COUNTED (owner ruling, registration 11.1;
  // docs/PREREG_CARD_V2.md lines 1087-1089 and 3203-3205). Every stat cell
  // above (`${prefix}-wl`/`-units`/`-days`) is the COUNTED figure --
  // effective_record.py's own `counted_scope` -- so a postseason pick
  // never moves them. This is the one line that shows it happened at
  // all: independent of `graded` above (a cohort can, in principle, have
  // postseason activity for a night that itself reads ungraded/
  // unavailable), driven only by whether `cohort.postseason` itself has
  // anything in it. Uses the SAME `cohortWL`/`cohortUnitsText` helpers
  // every other figure on this page uses, so a postseason W-L/units
  // string is formatted identically to a counted one.
  const postseasonNode = root.querySelector(`[data-hook='${prefix}-postseason']`);
  if (postseasonNode) {
    const postseason = cohort && cohort.postseason;
    const active = postseason && ((postseason.n_staked > 0) || (postseason.days > 0));
    if (active) {
      const wl = cohortWL(postseason);
      const units = cohortUnitsText(postseason);
      const nights = postseason.days || 0;
      // Nights with a card but no staked pick (fills only) used to print
      // "0–0, +0.00u over 2 nights", which reads as a result. It is the
      // absence of one, so it says that.
      const nightWord = `night${nights === 1 ? "" : "s"}`;
      postseasonNode.textContent = postseason.n_staked > 0
        ? `Postseason: ${wl}, ${units}u over ${nights} ${nightWord}. Graded, not counted.`
        : `Postseason: no picks on ${nights} ${nightWord} so far. Graded, not counted.`;
      postseasonNode.hidden = false;
    } else {
      postseasonNode.hidden = true;
    }
  }
}

/**
 * Fills BOTH rule-blocks (current, then previous -- RULE_BLOCKS' own
 * fixed order) for one snapshot (`{current, previous}`, MLB/NFL/UFC's own
 * shape from `effective_record`) under one root -- the hero panel and
 * every sport tile all call this same function, so "the hero and the
 * tile show the same number for the same rule" is true by construction --
 * sharing the renderer, not two call sites staying in sync by hand.
 *
 * OWNER REVIEW, 2026-09-25 (second pass) -- THE PREVIOUS BLOCK IS OMITTED
 * ENTIRELY WHEN NO PREDECESSOR EXISTS, NEVER RENDERED DASH-FILLED.
 * UFC's `previous` is `null` -- not an unavailable/ungraded cohort object,
 * an actual `None` -- because `src.report.effective_record.mma_snapshot`
 * returns `"previous": None` BY DESIGN: UFC_CARD_V1 is the only rule this
 * sport has ever published under, so there is no predecessor to describe
 * at all. Rendering a full "PREVIOUS RULE (RETIRED)" block of dashes for
 * that case implies a rule that never existed -- a fabrication by
 * omission, the same category of mistake this whole surface exists to
 * refuse. `snapshot.previous === null/undefined` is the ONLY signal this
 * function uses to decide that -- it is a structural fact from the
 * server (this sport's snapshot never carries a predecessor), never a
 * data quality judgement made here.
 *
 * THIS IS DISTINCT FROM a predecessor that EXISTS but has not graded a
 * night (MLB and NFL's `previous` are never `null` -- `_v1_style_cohort`
 * always returns a real cohort dict, even one with `available: false` or
 * `grading_state !== "graded"`). That case still renders the block, with
 * dashes and the cohort's own `reason`, exactly as `fillRuleBlock`
 * already handled it before this review -- see that function's own
 * `cohort.reason` branch just above. Only `cohort === null/undefined`
 * -- never `available: false`, never an ungraded `grading_state` -- hides
 * the block.
 */
function fillRuleSet(root, prefix, snapshot) {
  const bySlot = { current: snapshot && snapshot.current, previous: snapshot && snapshot.previous };
  for (const { role, label } of RULE_BLOCKS) {
    const blockNode = root.querySelector(`[data-hook='${prefix}-${role}-block']`);
    if (role === "previous" && !bySlot.previous) {
      if (blockNode) blockNode.hidden = true;
      continue;
    }
    if (blockNode) blockNode.hidden = false;
    fillRuleBlock(root, `${prefix}-${role}`, bySlot[role], label);
  }
}

async function fillProofPanel() {
  const panel = document.querySelector("[data-hook='hero-proof']");
  if (!panel) return;
  try {
    const meta = await fetchMeta();
    const mlb = meta && meta.effective_record && meta.effective_record.sports
      && meta.effective_record.sports.mlb;
    if (!mlb) return;
    fillRuleSet(panel, "hero", mlb);
  } catch (err) {
    // Leave the dashes in place -- never a guessed figure.
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
      if (tile && sports[sport]) fillRuleSet(tile, prefix, sports[sport]);
    }
  } catch (err) {
    // Leave every tile's static fallback copy in place -- never a guess.
  }
}

/**
 * Replace the closing CTA's headline with the truth about whether
 * tonight's MLB card has actually posted -- GET /card's own `frozen`
 * flag (src/report/card.py: True only once the afternoon pass has
 * published a row; False while the page would still be building live).
 * "Tonight's card is already up" was a static claim that read as false
 * for roughly the first half of every day, before that pass runs. The
 * markup's own fallback already states the always-true "before first
 * pitch" promise instead, so a slow or failed fetch never overclaims --
 * same honest-absence rule as fillResearchCounts/fillCardRecord above.
 */
async function fillClosingCta() {
  const node = document.querySelector("[data-hook='closing-cta-title']");
  if (!node) return;
  try {
    const card = await apiGet("/card");
    if (!card || card.frozen !== true) return;
    clear(node);
    node.appendChild(document.createTextNode("Tonight's card is already up."));
    node.appendChild(el("br"));
    node.appendChild(document.createTextNode("See what it says."));
  } catch (err) {
    // Leave the markup's conservative fallback in place.
  }
}

/* =====================================================================
 * WHAT IS PROVEN AND WHAT IS NOT; THE FREE SAMPLE (2026-10-01)
 *
 * Two blocks a stranger needs before the pricing card. Both follow the same
 * rule as every other record surface on this page: the markup carries
 * sentences with NO figure in them, and a number appears only when GET /meta
 * (or the public GET /card/history) has actually answered. A slow or failed
 * fetch leaves true words, or -- for the sample -- no block at all.
 * ===================================================================== */

/** The record line of "what is proven": the current MLB rule's own cohort,
 * the same object the hero panel reads (effective_record.sports.mlb.current).
 * Says "negative" only when the units are negative, and never implies the
 * picks make money when they are not. Null for a cohort that has not graded
 * a night, so the markup's figure-free sentence stays. */
export function provenRecordSentence(cohort) {
  if (!cohort || !cohort.available || cohort.grading_state !== "graded") return null;
  const wl = cohortWL(cohort);
  const units = cohortUnitsText(cohort);
  if (!wl || !units || typeof cohort.days !== "number" || cohort.days < 1) return null;
  const nights = `${cohort.days} night${cohort.days === 1 ? "" : "s"}`;
  const figures = `${wl}, ${units} units over ${nights} graded`;
  // The sign picks words through ternaries only -- never a branch that
  // builds different markup (tests/test_landing_profit_sign_rendering.py).
  const negative = cohort.profit_units < 0;
  const lead = negative ? "The record so far is negative for the current method"
    : "The record so far for the current method";
  const tail = negative ? "."
    : ". That is a result so far, not evidence that the picks make money.";
  return `${lead}: ${figures}${tail}`;
}

/** The research line of "what is proven", from /meta.research -- the same
 * registry counts fillResearchCounts reads. */
export function researchSentence(research) {
  if (!research || typeof research.read !== "number" || research.read < 1
      || typeof research.surviving !== "number") return null;
  if (research.surviving === 0) {
    return `No research idea has survived testing: ${research.read} tested, none survived.`;
  }
  return `${research.surviving} of ${research.read} research ideas tested have survived our checks.`;
}

async function fillProvenBlock() {
  const recordNode = document.querySelector("[data-hook='proven-record-text']");
  const researchNode = document.querySelector("[data-hook='proven-research-text']");
  if (!recordNode && !researchNode) return;
  try {
    const meta = await fetchMeta();
    const sports = meta && meta.effective_record && meta.effective_record.sports;
    const mlb = sports && sports.mlb;
    const recordText = provenRecordSentence(mlb && mlb.current);
    if (recordNode && recordText) recordNode.textContent = recordText;
    const researchText = researchSentence(meta && meta.research);
    if (researchNode && researchText) researchNode.textContent = researchText;
  } catch (err) {
    // Leave the markup's own figure-free sentences in place.
  }
}

/**
 * THE FREE SAMPLE: the most recent fully graded card, from the public
 * GET /card/history?limit=1 (api/card.py `_public_history` -- settled days
 * only, newest first).
 *
 * TWO PAYLOAD SHAPES, ONE RENDERER. The live MLB rule (V2) sends each day as
 * `graded`: every entry the card showed, picks AND fills, each carrying
 * `entry_class` ("pick" or "fill"), its price, result and profit. The older
 * rule sends `picks`/`prop_picks`/`total_picks` with a server-written `bet`
 * sentence and a `book`. The V2 entries carry neither a `bet` sentence nor a
 * book name today, so the bet line is composed from the entry's own fields
 * (team, player, side, line, market); a `bet` or `book` that arrives later is
 * used as sent.
 *
 * The pure text half (bet words, price line, result line, fill and postseason
 * tags, the -200 test) lives in web/js/entrytext.js, shared with the record
 * page's day-by-day rows, so the two pages cannot word an entry differently.
 *
 * HONESTY RULES, each one mirrored from web/js/cardrecord.js or the owner:
 *   - A fill is labelled a fill, listed under its own heading, summed apart
 *     from the picks and never called a pick (cardrecord's calendar note).
 *   - A withdrawn entry is not shown and not counted (record_v2 counts it
 *     apart); the sample says how many there were.
 *   - An entry priced at -200 or shorter is never shown on a public card
 *     (owner ruling, 2026-09-22; landing-live.js `priceQualifies`). The record
 *     page is the ledger and lists every entry as stored, so only this
 *     sample filters, and it says how many it left out.
 *   - A void is a void: no units, the server's reason beside it.
 *   - Fail closed. A day with no entry, an entry with no readable bet, price
 *     or result, or any failed fetch hides the whole block -- no empty frame,
 *     no placeholder figure.
 */
const LAST_CARD_TITLE = "Last night's card, as published, with what happened";
const LAST_CARD_TITLE_OLDER = "The most recent graded card, as published, with what happened";

function lastCardDateLabel(dateIso) {
  if (!dateIso || !/^\d{4}-\d{2}-\d{2}$/.test(dateIso)) return null;
  const d = new Date(`${dateIso}T12:00:00Z`);
  if (Number.isNaN(d.getTime())) return null;
  return new Intl.DateTimeFormat("en-US", {
    timeZone: "UTC", weekday: "long", month: "short", day: "numeric", year: "numeric",
  }).format(d);
}

/** Yesterday's calendar date in US Eastern, as YYYY-MM-DD -- the slate dates
 * the ledger uses are Eastern. */
function yesterdayEastern(now) {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "America/New_York", year: "numeric", month: "2-digit", day: "2-digit",
  }).formatToParts(now);
  const get = (type) => Number((parts.find((p) => p.type === type) || {}).value);
  const prior = new Date(Date.UTC(get("year"), get("month") - 1, get("day") - 1));
  return prior.toISOString().slice(0, 10);
}

/** The pure half: a /card/history payload -> what the block will say, or
 * null (render nothing). `now` is injectable for the "last night" test. */
export function lastCardModel(payload, now = new Date()) {
  const days = payload && Array.isArray(payload.days) ? payload.days : [];
  const dated = days.filter((d) => d && typeof d === "object" && /^\d{4}-\d{2}-\d{2}$/.test(d.date || ""));
  if (!dated.length) return null;
  const day = dated.reduce((best, d) => (d.date > best.date ? d : best));

  let withdrawn = 0;
  let heavy = 0;
  const picks = [];
  const fills = [];
  for (const entry of dayEntries(day)) {
    if (!entry || typeof entry !== "object") return null;
    if (entry.withdrawn) { withdrawn += 1; continue; }
    if (isHeavyFavourite(entry)) { heavy += 1; continue; }
    const row = entryRow(entry);
    if (!row) return null;
    (row.fill ? fills : picks).push(row);
  }
  if (!picks.length && !fills.length) return null;

  const dateLabel = lastCardDateLabel(day.date);
  if (!dateLabel) return null;
  const notes = [];
  if (withdrawn) {
    notes.push(`${withdrawn} ${withdrawn === 1 ? "entry was" : "entries were"} withdrawn before the game `
      + "and is not shown or counted.");
  }
  if (heavy) {
    notes.push(`${heavy} ${heavy === 1 ? "entry" : "entries"} priced at -200 or shorter ${heavy === 1 ? "is" : "are"} not shown here.`);
  }
  return {
    date: day.date,
    title: day.date === yesterdayEastern(now) ? LAST_CARD_TITLE : LAST_CARD_TITLE_OLDER,
    dateLine: `Card for ${dateLabel}. Published before the game, graded the next morning.`,
    picks,
    fills,
    noPicks: !picks.length,
    notes,
  };
}

function lastCardGroup(kind, head, summary, rows, explainer) {
  const group = el("div", {
    class: "lc-group panel chamfer", "data-hook": `last-card-${kind}`,
  });
  group.appendChild(el("h3", { class: "lc-group__head", text: head }));
  group.appendChild(el("p", { class: "lc-group__sum", "data-hook": `last-card-${kind}-sum`, text: summary }));
  if (explainer) {
    group.appendChild(el("p", { class: "lc-note", "data-hook": `last-card-${kind}-note`, text: explainer }));
  }
  const list = el("ul", { class: "lc-list" });
  for (const row of rows) {
    const item = el("li", {
      class: "lc-row", "data-hook": "last-card-row",
      "data-kind": kind === "fills" ? "fill" : "pick", "data-result": row.outcome,
    });
    item.appendChild(el("span", { class: "lc-row__bet", text: row.bet }));
    if (row.fill) {
      item.appendChild(el("span", { class: "lc-row__tag", "data-hook": "last-card-fill-tag", text: FILL_TAG }));
    }
    if (row.postseason) {
      item.appendChild(el("span", { class: "lc-row__tag", text: POSTSEASON_TAG_SAMPLE }));
    }
    item.appendChild(el("span", { class: "lc-row__meta", text: row.meta }));
    item.appendChild(el("span", {
      class: `lc-row__result lc-row__result--${String(row.outcome).toLowerCase()}`,
      "data-hook": "last-card-result", text: row.result,
    }));
    list.appendChild(item);
  }
  group.appendChild(list);
  return group;
}

/** The DOM half. Returns true when the block was filled and shown; on any
 * payload it cannot show honestly it empties and hides the section. */
export function renderLastCard(section, payload, now = new Date()) {
  const body = section.querySelector("[data-hook='last-card-body']");
  if (body) clear(body);
  let model = null;
  try { model = lastCardModel(payload, now); } catch (err) { model = null; }
  if (!model || !body) {
    section.hidden = true;
    return false;
  }
  const title = section.querySelector("[data-hook='last-card-title']");
  if (title) title.textContent = model.title;
  const dateNode = section.querySelector("[data-hook='last-card-date']");
  if (dateNode) dateNode.textContent = model.dateLine;

  if (model.noPicks) {
    body.appendChild(el("p", {
      class: "lc-note", "data-hook": "last-card-no-picks",
      text: "No pick passed every check that night, so the card listed fills only.",
    }));
  } else {
    body.appendChild(lastCardGroup("picks", "Picks", tallyText(model.picks, true), model.picks, null));
  }
  if (model.fills.length) {
    body.appendChild(lastCardGroup("fills", "Fills, not picks", tallyText(model.fills, false), model.fills,
      "Fills are listed to round out the card. They did not pass every check, so they are not "
      + "picks and are not counted in the record."));
  }
  for (const note of model.notes) {
    body.appendChild(el("p", { class: "lc-note", "data-hook": "last-card-footnote", text: note }));
  }
  body.appendChild(el("a", {
    class: "wyg-link", href: "index.html#/record-card", "data-hook": "last-card-link",
    text: "See the whole record",
  }));
  section.hidden = false;
  return true;
}

/**
 * THE HERO'S SECOND BUTTON POINTS AT THE SAMPLE ONLY WHILE THERE IS ONE
 * (2026-10-02). The markup says "See last night's card, graded" and jumps to
 * #free-sample, but that section is hidden until a settled day has rendered. A
 * button that promises a card and scrolls nowhere is worse than no button, so
 * when the sample is not shown the button becomes the plain record link. The
 * hook (`cta-record-secondary`) never changes: clicks are counted by hook.
 */
export const SAMPLE_BUTTON = "See last night's card, graded";
export const RECORD_BUTTON = "See every pick, graded";

export function pointSampleButton(sampleShown) {
  const button = document.querySelector("[data-hook='cta-record-secondary']");
  if (!button) return;
  button.textContent = sampleShown ? SAMPLE_BUTTON : RECORD_BUTTON;
  button.setAttribute("href", sampleShown ? "#free-sample" : "index.html#/record-card");
}

export async function fillLastCard() {
  const section = document.querySelector("[data-hook='last-card']");
  if (!section) return;
  try {
    const payload = await apiGet("/card/history?limit=1");
    renderLastCard(section, payload);
  } catch (err) {
    // Nothing to show, so nothing is shown: the section stays hidden.
    section.hidden = true;
  }
  pointSampleButton(!section.hidden);
}

function boot() {
  const disclaimerHost = document.querySelector("[data-hook='disclaimer-host']");
  const pricingHost = document.querySelector("[data-hook='pricing-host']");
  // One <footer> on this page: the host sits inside it, so meta.js mounts the
  // shared disclaimer as a group there, not as a second footer.
  if (disclaimerHost) renderDisclaimerFooter(disclaimerHost);
  if (pricingHost) renderPricing(pricingHost, NOT_ON);
  fillCheckoutCopy();
  revealPublicDemoEntry();
  fillResearchCounts();
  fillCardRecord();
  fillProofPanel();
  fillSportTiles();
  fillClosingCta();
  fillProvenBlock();
  fillLastCard();
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
  // FIRST TOUCH, KEPT. The UTM tags and referrer host used to live and die on
  // this page's own beacons; stored here (localStorage, first touch wins) they
  // travel with the visitor into the signup request, the account row, the
  // Stripe Checkout metadata and the paid event. See attribution.js.
  captureFirstTouch();
  trackFunnelEvent("landing_view", arrivalProperties());
  trackCtaClicks();
  // Design-system motion (handoff section 08) -- content renders complete
  // and static if this never runs; see motion.js's fail-safe-reveal note.
  armEntrances(document);
  armParallax(document);
  armCharts(document);
}

document.addEventListener("DOMContentLoaded", boot);
