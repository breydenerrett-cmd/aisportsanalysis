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
    const n = meta && meta.research && meta.research.hypotheses;
    if (typeof n !== "number") return;
    nodes.forEach((node) => { node.textContent = String(n); });
  } catch (err) {
    // Leave the markup's own figure in place.
  }
}

function boot() {
  const disclaimerHost = document.querySelector("[data-hook='disclaimer-host']");
  const pricingHost = document.querySelector("[data-hook='pricing-host']");
  if (disclaimerHost) renderDisclaimerFooter(disclaimerHost);
  if (pricingHost) renderPricing(pricingHost);
  revealPublicDemoEntry();
  fillResearchCounts();
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
