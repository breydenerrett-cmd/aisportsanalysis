/**
 * The app-shell footer, sourced from GET /meta (no auth -- api/meta.py).
 * Mounted once by main.js and left in the DOM across every view swap, so
 * the disclaimer is always rendered regardless of which view is active --
 * never something an individual view module can forget to include.
 *
 * FOOTER TREATMENT (canvas: wordmark, hairline, legal meta on one row)
 * -------------------------------------------------------------------
 * The artboards' footer is one compact row. The beta disclaimer is long,
 * and it is NOT optional -- so the row carries a one-line summary that is
 * always visible, and the FULL disclaimer text stays reachable, verbatim
 * and unabridged, inside an expandable disclosure directly beneath it.
 * Summarised in the fold, never deleted, never truncated in the source.
 */

import { apiGet } from "./api.js";
import { el, clear, renderUnknown, humanizeKey } from "./dom.js";
import { BRAND_NAME } from "./brand.js";

/** The always-visible one-liner above the fold. Deliberately short and
 * deliberately NOT a paraphrase of the legal text -- it says what the
 * product is and points at the full wording, which sits one click away
 * and unedited. */
const SUMMARY =
  "Beta. We show what supports a bet, what argues against it, and where the "
  + "price is better -- never what to bet. Read the full disclaimer below.";

export async function renderDisclaimerFooter(container) {
  clear(container);
  const region = el("footer", {
    class: "sitefoot", "aria-label": "disclaimer", "data-hook": "disclaimer",
  });

  const row = el("div", { class: "sitefoot__row" });
  row.appendChild(el("span", { class: "sitefoot__mark", text: BRAND_NAME }));
  row.appendChild(el("span", { class: "sitefoot__hair", "aria-hidden": "true" }));
  row.appendChild(el("span", { class: "sitefoot__legal", text: "ALL TIMES ET · 21+ · PLAY RESPONSIBLY" }));
  region.appendChild(row);

  region.appendChild(el("p", { class: "sitefoot__summary", "data-hook": "disclaimer-summary",
    text: SUMMARY }));

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

    const disclosure = el("details", { class: "sitefoot__disclosure" });
    disclosure.appendChild(el("summary", { text: "Full beta disclaimer" }));
    const body = el("div", { class: "sitefoot__full chamfer" });
    body.appendChild(el("p", { class: "sitefoot__product", "data-hook": "product-one-liner",
      text: meta.product }));
    body.appendChild(el("p", { "data-hook": "disclaimer-text", text: disclaimerText }));
    body.appendChild(el("p", { class: "sitefoot__version", "data-hook": "app-version",
      text: `BUILD ${meta.version}` }));
    disclosure.appendChild(body);
    region.appendChild(disclosure);
  } catch (err) {
    region.appendChild(el("p", { class: "sitefoot__summary", "data-hook": "disclaimer-unavailable",
      text: "Disclaimer unavailable: " + (err && err.message ? err.message : "request failed") }));
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
