/**
 * Entry point for web/postseason.html, the standalone (shareable, no router)
 * copy of the postseason view. The view itself is postseason.js, shared with
 * the app shell's #/postseason route; this file only mounts it and the shared
 * disclaimer footer.
 */

import { renderPostseason } from "./postseason.js";
import { renderDisclaimerFooter } from "./meta.js";

document.addEventListener("DOMContentLoaded", () => {
  const main = document.querySelector("[data-hook='app-outlet']");
  const footer = document.querySelector("[data-hook='disclaimer-host']");
  // The standalone page has no router, so the footer's "#/support" style
  // links must point at the app shell (see meta.js `linkPrefix`).
  if (footer) renderDisclaimerFooter(footer, { linkPrefix: "index.html" });
  if (main) renderPostseason(main, { standalone: true });
});
