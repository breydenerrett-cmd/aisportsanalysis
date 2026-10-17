/**
 * Entry point for web/why-we-paused.html. The page's words are static markup; this only does what
 * web/js/sample.js does around its content: stores the link's utm tags as the first touch and sends one
 * public_page_view beacon labelled "why-paused" (pageview.js; fire-and-forget, never throws into the
 * page), and mounts the shared disclaimer footer. It claims nothing and fetches no data.
 */

import { trackPublicPageView } from "./pageview.js";
import { renderDisclaimerFooter } from "./meta.js";

/** The `page` label of this page's public_page_view (api/funnel.py PAGE_LABEL_RE). */
export const WHY_PAUSED_PAGE = "why-paused";

function main() {
  try { trackPublicPageView(WHY_PAUSED_PAGE); } catch (err) { /* never break the page */ }
  const footer = document.querySelector("[data-hook='disclaimer-host']");
  if (footer) renderDisclaimerFooter(footer, { linkPrefix: "index.html" });
}

if (typeof document !== "undefined" && typeof window !== "undefined") {
  document.addEventListener("DOMContentLoaded", main);
}
