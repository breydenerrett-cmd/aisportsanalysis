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
import { el, clear, renderUnknown, humanizeKey, formatEasternClock, formatAge, localZoneAbbr } from "./dom.js";
import { BRAND_NAME } from "./brand.js";

/** The always-visible one-liner above the fold. Deliberately short and
 * deliberately NOT a paraphrase of the legal text -- it says what the
 * product is and points at the full wording, which sits one click away
 * and unedited. */
// REWRITTEN 2026-09-10 because the old line had become false.
//
// It read: "We show what supports a bet, what argues against it, and where
// the price is better — never what to bet." That described the product
// before THE CARD, which names three to five bets a day in plain words. A
// page that opens with "Take Yankees -1.5 at -149" and carries a footer
// promising it never says what to bet is not being careful, it is
// contradicting itself, and a reader who notices trusts neither half.
//
// REWRITTEN AGAIN, 2026-09-15 (DESIGN_SYSTEM.md section 3 / shell-07):
// "frozen before first pitch" overclaimed a fixed price the moment a
// later publish replaces a provisional pick (see section 5's record
// wording). The record is what a pick read AT ITS LOCK, not what it read
// the instant it was first published. This line now matches that policy
// exactly, and drops the specific "three to five" count and "frozen"
// verb, neither of which the record wording repeats.
//
// EXTENDED 2026-09-20 (owner: NFL and tennis go live beside MLB). With
// three sports on the page, one of them with a single graded pick and one
// with no graded picks at all, the footer now says outright that every
// pick is part of a test and that any bet is the reader's own decision.
const SUMMARY =
  "Beta. Every pick here is part of an ongoing test — published before each game and graded as it stood at its lock, win or lose. This is analysis, not advice. Nothing here is a guarantee; bet at your own risk.";

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

/**
 * /meta, fetched at most ONCE per page load and shared by every caller.
 *
 * EXPORTED 2026-09-10 BECAUSE THE SHARING WAS NOT HAPPENING. This cache has
 * existed for a while and four call sites went around it -- the disclaimer
 * footer directly below, main.js's version stamp, and landing.js twice --
 * each calling `apiGet("/meta")` on its own. A single load of #/today fired
 * FIVE requests for one unchanging payload, against a container that serves
 * them one at a time on a single shared CPU.
 *
 * A private cache that callers can bypass is not a cache, it is a
 * suggestion. This one is now the only way in.
 */
export function meta() {
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
    // The READ count: every sentence built here says "measured" or
    // "pre-registered ... surviving", and a hypothesis registered ahead of
    // its data (V7, 2026-09-12) is neither measured nor a survivor. An
    // older /meta without `read` still carries the total.
    const read = typeof counts.read === "number" ? counts.read : counts.hypotheses;
    if (typeof read !== "number" || typeof counts.surviving !== "number") return;
    node.textContent = build(read, counts.surviving);
  });
  return node;
}

/**
 * `container` is the footer's mount point; `linkPrefix` (DESIGN_SYSTEM.md
 * section 3, matching `sport.js`'s `renderSportLevel`) defaults to `""`
 * so every app-route href here (`#/record-card`, `#/performance`,
 * `#/props`, `#/betcheck`, `#/support`) resolves normally when mounted by
 * `main.js` inside the app shell. `landing.js` calls this with
 * `linkPrefix: "index.html"` so the SAME hrefs resolve from
 * `landing.html`, which has no route behind a bare `#/...` fragment of
 * its own -- confirmed dead-end otherwise (section 3).
 */
export async function renderDisclaimerFooter(container, { linkPrefix = "" } = {}) {
  clear(container);
  const region = el("footer", {
    class: "sitefoot", "aria-label": "disclaimer", "data-hook": "disclaimer",
  });
  const route = (hash) => `${linkPrefix}${hash}`;

  const row = el("div", { class: "sitefoot__row" });
  row.appendChild(el("span", { class: "sitefoot__mark", text: BRAND_NAME }));
  row.appendChild(el("span", { class: "sitefoot__hair", "aria-hidden": "true" }));
  // Row 1's legal line (DESIGN_SYSTEM.md section 3): "21+ · Play
  // responsibly · 1-800-GAMBLER" -- the source string stays uppercase
  // "PLAY RESPONSIBLY" (tests/test_shared_footer.py pins it case-
  // sensitively; CSS may transform the case it renders, the DOM text does
  // not need to). The viewer's own zone abbreviation used to be prefixed
  // onto this same line -- moved to its own row 4 below so the zone is
  // stated once, not twice (section 3: do not duplicate the old
  // zone-prefix phrase from elsewhere in the footer).
  row.appendChild(el("span", { class: "sitefoot__legal", text: "21+ · PLAY RESPONSIBLY" }));
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
  // but it would be here even if it were not. Not a `#/...` route, so it
  // is never prefixed by `linkPrefix`.
  // No extra hairline here: .sitefoot__row already sets `gap`, and a second
  // `flex: 1` spacer competed with the first for the same slack and
  // collapsed BOTH to zero width -- which quietly undid the row's original
  // mark-left / legal-right composition.
  row.appendChild(el("a", { class: "sitefoot__help", href: "tel:1-800-426-2537",
    "data-hook": "responsible-gambling-help", text: "1-800-GAMBLER" }));
  // Row 1's link list, in DESIGN_SYSTEM.md section 3's stated order --
  // Results, Research, Player props, Bet Check, Support. The footer is
  // mounted once by main.js (and by landing.js) and survives every view
  // swap, so it is the one place none of these links can be forgotten;
  // see the per-link history below for why each one is here at all.
  //
  // THE RECORD -> Results (#/record-card): the receipts for the product's
  // whole pitch ("picks with receipts"), not a utility route, but it
  // belongs here rather than the primary nav (see cardrecord.js's own
  // docstring on why).
  row.appendChild(el("a", { class: "sitefoot__support", href: route("#/record-card"),
    "data-hook": "footer-record", text: "Results" }));
  // RESEARCH (#/performance), after an ORPHANING. When RESULTS was
  // repointed from #/performance to #/record-card (main.js, 2026-09-10)
  // the comment justifying it claimed #/performance "stays reachable and
  // unchanged". It did not -- the route still dispatched, but nothing in
  // the app linked to it any more. A route only reachable by typing its
  // URL is an orphan, and the paper standings are where this product
  // publishes its losers, which is the whole claim the landing page makes.
  row.appendChild(el("a", { class: "sitefoot__support", href: route("#/performance"),
    "data-hook": "footer-performance", text: "Research" }));
  // PLAYER PROPS (#/props): THE CARD can only show moneylines and run
  // lines, so without this the product has no route at all to the
  // seventeen thousand player-prop prices it already collects.
  row.appendChild(el("a", { class: "sitefoot__support", href: route("#/props"),
    "data-hook": "footer-props", text: "Player props" }));
  // BET CHECK (#/betcheck), NEW (DESIGN_SYSTEM.md section 3 / D7): CHECK
  // leaves the primary navigation and the fixed "Check a bet" band goes
  // with it, but Bet Check's own route and function stay, reachable from
  // matchup pages and here -- the one place in the shared chrome it is
  // still one click away.
  row.appendChild(el("a", { class: "sitefoot__support", href: route("#/betcheck"),
    "data-hook": "footer-betcheck", text: "Bet Check" }));
  // SUPPORT (#/support): before this it had ZERO inbound links anywhere
  // in web/ -- a working support form reachable only by typing the URL.
  // A paying customer with a problem could not find the one place built
  // to hear about it, which is how a fixable complaint becomes a silent
  // cancellation.
  row.appendChild(el("a", { class: "sitefoot__support", href: route("#/support"),
    "data-hook": "footer-support", text: "Support" }));
  region.appendChild(row);

  region.appendChild(el("p", { class: "sitefoot__summary", "data-hook": "disclaimer-summary",
    text: SUMMARY }));

  try {
    // The shared promise, not a fifth request for the same payload.
    const payload = await meta();
    if (!payload) throw new Error("meta unavailable");
    // meta.disclaimer is documented as an object ({id, temporary,
    // requires_final_legal_review, text} -- api/meta.py) rather than a
    // bare string; a legal disclaimer must never render as
    // "[object Object]" (the el() text-node path would do exactly that
    // if handed the object itself).
    const disclaimerText =
      payload.disclaimer && typeof payload.disclaimer === "object"
        ? payload.disclaimer.text
        : payload.disclaimer;

    const disclosure = el("details", { class: "sitefoot__disclosure" });
    disclosure.appendChild(el("summary", { text: "Full beta disclaimer" }));
    const body = el("div", { class: "sitefoot__full chamfer" });
    body.appendChild(el("p", { class: "sitefoot__product", "data-hook": "product-one-liner",
      text: payload.product }));
    body.appendChild(el("p", { "data-hook": "disclaimer-text", text: disclaimerText }));
    body.appendChild(el("p", { class: "sitefoot__version", "data-hook": "app-version",
      text: `BUILD ${payload.version}` }));
    disclosure.appendChild(body);
    region.appendChild(disclosure);
  } catch (err) {
    region.appendChild(el("p", { class: "sitefoot__summary", "data-hook": "disclaimer-unavailable",
      text: "Disclaimer unavailable: " + (err && err.message ? err.message : "request failed") }));
  }

  // Row 4 (DESIGN_SYSTEM.md section 3): the one place the viewer's own
  // zone is stated in the footer now (row 1's legal line used to carry
  // the same zone prefix too -- removed above so this is not said twice).
  // Client-side only, so it renders whether or not /meta answered; omitted
  // entirely (not a guessed zone) on the rare browser where Intl cannot
  // resolve one at all.
  const zoneAbbr = localZoneAbbr();
  if (zoneAbbr) {
    region.appendChild(el("p", { class: "sitefoot__summary", "data-hook": "disclaimer-timezone",
      text: `Times shown in ${zoneAbbr}, your time zone.` }));
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
    // `formatAge` already ends in AGO ("13 HR AGO"). Appending another one
    // printed "11:52am ET · 13 HR AGO ago" on the slate page, in the
    // freshness row, where a reader is being asked to trust the timestamp.
    // Local-time rewrite, 2026-09-14: `clock` now already carries the
    // viewer's own zone abbreviation ("11:52 AM PDT"), so no more literal
    // " ET" appended here.
    if (clock && age) text = `${clock} · ${age}`;
    else if (clock) text = clock;
    else if (age) text = age;
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
