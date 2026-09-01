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
import { renderDisclaimerFooter } from "./meta.js";
import { BETA_TIER } from "./pricing.js";
import { renderWordmark } from "./brand.js";
import { armEntrances, armParallax, armCharts } from "./motion.js";

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

function boot() {
  const disclaimerHost = document.querySelector("[data-hook='disclaimer-host']");
  const pricingHost = document.querySelector("[data-hook='pricing-host']");
  if (disclaimerHost) renderDisclaimerFooter(disclaimerHost);
  if (pricingHost) renderPricing(pricingHost);
  // Wordmarks are markup-authored today (see brand.js's docstring on why
  // <title> and the static text stay literal), but every mark carries the
  // hook so a future rename only has to touch BRAND_NAME plus these two
  // literal strings, not hunt through the design-system CSS.
  document.querySelectorAll("[data-hook='brand-mark']").forEach((host) => renderWordmark(host));
  trackFunnelEvent("landing_view");
  // Design-system motion (handoff section 08) -- content renders complete
  // and static if this never runs; see motion.js's fail-safe-reveal note.
  armEntrances(document);
  armParallax(document);
  armCharts(document);
}

document.addEventListener("DOMContentLoaded", boot);
