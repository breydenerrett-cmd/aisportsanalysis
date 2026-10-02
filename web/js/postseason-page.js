/**
 * Entry point for web/postseason.html, the standalone (shareable, no router)
 * copy of the postseason view. The view itself is postseason.js, shared with
 * the app shell's #/postseason route; this file only mounts it and the shared
 * disclaimer footer.
 */

import { renderPostseason } from "./postseason.js";
import { renderDisclaimerFooter } from "./meta.js";
import { trackPublicPageView } from "./pageview.js";

document.addEventListener("DOMContentLoaded", () => {
  // An outreach link may open this page directly (postseason.html?utm_source=
  // <lead>&...): store the first touch and count the visit, once per load,
  // exactly as the app shell does for its public routes (pageview.js).
  trackPublicPageView("postseason");
  const main = document.querySelector("[data-hook='app-outlet']");
  const footer = document.querySelector("[data-hook='disclaimer-host']");
  // The standalone page has no router, so the footer's "#/support" style
  // links must point at the app shell (see meta.js `linkPrefix`).
  if (footer) renderDisclaimerFooter(footer, { linkPrefix: "index.html" });
  if (main) renderPostseason(main, { standalone: true });
});
