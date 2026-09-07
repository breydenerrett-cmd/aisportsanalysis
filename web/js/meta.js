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
import { el, clear, renderUnknown, humanizeKey, formatEasternClock, formatAge } from "./dom.js";
import { BRAND_NAME } from "./brand.js";

/** The always-visible one-liner above the fold. Deliberately short and
 * deliberately NOT a paraphrase of the legal text -- it says what the
 * product is and points at the full wording, which sits one click away
 * and unedited. */
const SUMMARY =
  "Beta. We show what supports a bet, what argues against it, and where the "
  + "price is better — never what to bet. Read the full disclaimer below.";

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
 * `{observed_utc, age_seconds, has_market|has_board}`-shaped object.
 *
 * STILL NO CLIENT-SIDE THRESHOLD JUDGMENT. This used to enumerate the
 * object's keys and print each value verbatim, which put
 * `age_seconds 13070.244993` and `has_board true` on a customer page --
 * raw field names, a raw ISO timestamp and a float of seconds, reading as
 * debug output rather than as the freshness note it is. Every fact is
 * still here and none is softened; the values are only formatted the way
 * the rest of the product formats them (ET clock, `formatAge`), and
 * `has_board` is restated in words. What is NOT added is a verdict: no
 * "fresh", no "stale", no threshold the API did not supply. Unknown keys
 * still fall through to the old key/value treatment, so a field the API
 * adds later shows up rather than being silently dropped. */
export function renderStaleness(staleness) {
  const section = el("dl", { class: "staleness", "data-hook": "staleness" });
  if (!staleness || typeof staleness !== "object") {
    section.appendChild(el("dt", { text: "Board status" }));
    section.appendChild(el("dd", {}, [renderUnknown(null)]));
    return section;
  }

  const pair = (key, label, node) => {
    section.appendChild(el("dt", { class: `staleness__key staleness__key--${key}`,
      "data-raw-key": key, text: label }));
    section.appendChild(el("dd", { class: "staleness__value" }, [node]));
  };

  const known = new Set(["books", "observed_utc", "age_seconds", "has_board", "has_market"]);

  if (typeof staleness.books === "number") {
    pair("books", "Books", el("span", { text: `${staleness.books} compared` }));
  } else if ("books" in staleness) {
    pair("books", "Books", renderUnknown(staleness.books));
  }

  if ("observed_utc" in staleness || "age_seconds" in staleness) {
    const clock = staleness.observed_utc == null ? null : formatEasternClock(staleness.observed_utc);
    const age = typeof staleness.age_seconds === "number" ? formatAge(staleness.age_seconds) : null;
    let text = null;
    if (clock && age) text = `${clock} ET · ${age} ago`;
    else if (clock) text = `${clock} ET`;
    else if (age) text = `${age} ago`;
    pair("observed_utc", "Prices captured",
      text === null ? renderUnknown(staleness.observed_utc == null ? null : staleness.observed_utc)
                    : el("span", { text }));
  }

  for (const key of ["has_board", "has_market"]) {
    if (!(key in staleness)) continue;
    const label = key === "has_board" ? "Board" : "Priced market";
    pair(key, label, staleness[key] == null
      ? renderUnknown(null)
      : el("span", { text: staleness[key] ? "loaded" : "none on file" }));
  }

  for (const key of Object.keys(staleness)) {
    if (known.has(key)) continue;
    pair(key, humanizeKey(key), renderUnknown(staleness[key]));
  }
  return section;
}
