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

/**
 * THE RESEARCH COUNTS, FROM THE REGISTRY, ONCE.
 *
 * "27 hypotheses pre-registered ... zero surviving" was a hardcoded string
 * in web/js/today.js. web/js/betcheck.js carried a second, independently
 * worded copy saying "Twenty-seven". web/landing.html said 25 in two
 * places. data/research/alpha_registry.jsonl says 40. So a prospect read
 * one number on the page that sold them the subscription and a different
 * one the first time they opened the app -- on a product whose whole pitch
 * is that it counts honestly.
 *
 * The old constant's defence was that this is a CLOSED historical record,
 * not a live count, so pinning it was safe. That is exactly why it drifted:
 * a number nobody expects to change is a number nobody re-checks. The
 * registry is the closed record; reading it costs one request that every
 * page already makes.
 *
 * One in-flight promise, shared -- not one fetch per caller.
 */
let _metaPromise = null;

function meta() {
  if (!_metaPromise) {
    _metaPromise = apiGet("/meta").catch(() => null);
  }
  return _metaPromise;
}

/**
 * Fills `node` with a sentence about the research record once /meta answers.
 *
 * `build(hypotheses, surviving)` returns the sentence -- each call site
 * writes its own wording, since Today's panel and Bet Check's evidence
 * block are different registers. `fallback` is rendered when the registry
 * could not be read: a sentence with no figures in it, never a guessed
 * number, matching the honest-absence rule everywhere else in this client.
 *
 * Asynchronous on purpose. Both call sites build their DOM synchronously
 * inside a larger render, so the alternative is either blocking the whole
 * screen on /meta or going back to a hardcoded string.
 */
export function fillResearchCount(node, build, fallback) {
  node.textContent = fallback;
  meta().then((payload) => {
    const counts = (payload && payload.research) || {};
    if (typeof counts.hypotheses !== "number"
        || typeof counts.surviving !== "number") return;
    node.textContent = build(counts.hypotheses, counts.surviving);
  });
  return node;
}

export async function renderDisclaimerFooter(container) {
  clear(container);
  const region = el("footer", {
    class: "sitefoot", "aria-label": "disclaimer", "data-hook": "disclaimer",
  });

  const row = el("div", { class: "sitefoot__row" });
  row.appendChild(el("span", { class: "sitefoot__mark", text: BRAND_NAME }));
  row.appendChild(el("span", { class: "sitefoot__hair", "aria-hidden": "true" }));
  row.appendChild(el("span", { class: "sitefoot__legal", text: "ALL TIMES ET · 21+ · PLAY RESPONSIBLY" }));
  // A REACHABLE HELPLINE, not just the words "play responsibly".
  //
  // 1-800-GAMBLER existed only in design/linehound-v1 and -v2 mockups; it
  // never shipped into web/. So the product told people to play responsibly
  // and gave them nowhere to go -- the one piece of copy on this page whose
  // whole value is being actionable at the moment somebody needs it.
  //
  // A tel: link, because on the device most people read this on it is one
  // tap. Both app stores require a helpline in the listing for anything
  // betting-adjacent, so this is also on the path to being installable --
  // but it would be here even if it were not.
  // No extra hairline here: .sitefoot__row already sets `gap`, and a second
  // `flex: 1` spacer competed with the first for the same slack and
  // collapsed BOTH to zero width -- which quietly undid the row's original
  // mark-left / legal-right composition.
  row.appendChild(el("a", { class: "sitefoot__help", href: "tel:1-800-426-2537",
    "data-hook": "responsible-gambling-help", text: "1-800-GAMBLER" }));
  // #/support had ZERO inbound links anywhere in web/ -- a working support
  // form reachable only by typing the URL. A paying customer with a problem
  // could not find the one place built to hear about it, which is how a
  // fixable complaint becomes a silent cancellation. The footer is mounted
  // once by main.js and survives every view swap, so it is the one place a
  // link cannot be forgotten.
  row.appendChild(el("a", { class: "sitefoot__support", href: "#/support",
    "data-hook": "footer-support", text: "SUPPORT" }));
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
