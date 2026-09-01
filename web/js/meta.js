/**
 * The app-shell disclaimer footer, sourced from GET /meta (no auth --
 * api/meta.py). Mounted once by main.js and left in the DOM across every
 * view swap, so the disclaimer is always rendered regardless of which
 * view is active -- never something an individual view module can forget
 * to include.
 */

import { apiGet } from "./api.js";
import { el, clear, renderUnknown, humanizeKey } from "./dom.js";

export async function renderDisclaimerFooter(container) {
  clear(container);
  const region = el("section", {
    class: "app-disclaimer", "aria-label": "disclaimer", "data-hook": "disclaimer",
  });
  try {
    const meta = await apiGet("/meta");
    // meta.disclaimer is documented as an object ({id, temporary,
    // requires_final_legal_review, text} -- api/meta.py) rather than a
    // bare string; a legal disclaimer must never render as
    // "[object Object]" (the el() text-node path would do exactly that
    // if handed the object itself).
    const disclaimerText = meta.disclaimer && typeof meta.disclaimer === "object"
      ? meta.disclaimer.text
      : meta.disclaimer;
    region.appendChild(el("p", {
      class: "app-disclaimer__product", "data-hook": "product-one-liner",
      text: meta.product,
    }));
    region.appendChild(el("p", {
      class: "app-disclaimer__text", "data-hook": "disclaimer-text",
      text: disclaimerText,
    }));
    region.appendChild(el("p", {
      class: "app-disclaimer__version", "data-hook": "app-version",
      text: `Build ${meta.version}`,
    }));
  } catch (err) {
    region.appendChild(el("p", {
      class: "app-disclaimer__text", "data-hook": "disclaimer-unavailable",
      text: "Disclaimer unavailable: " + (err && err.message ? err.message : "request failed"),
    }));
  }
  container.appendChild(region);
}

/** A game/board staleness readout shared by every view that carries a
 * `{observed_utc, age_seconds, has_market|has_board}`-shaped object --
 * renders the fields verbatim rather than composing a "fresh"/"stale"
 * label the API did not supply (no client-side threshold judgment). */
export function renderStaleness(staleness) {
  const section = el("dl", { class: "staleness", "data-hook": "staleness" });
  if (!staleness || typeof staleness !== "object") {
    section.appendChild(el("dt", { text: "Board status" }));
    section.appendChild(el("dd", {}, [renderUnknown(null)]));
    return section;
  }
  for (const key of Object.keys(staleness)) {
    section.appendChild(el("dt", { class: `staleness__key staleness__key--${key}`,
      "data-raw-key": key, text: humanizeKey(key) }));
    section.appendChild(el("dd", { class: "staleness__value" }, [renderUnknown(staleness[key])]));
  }
  return section;
}
