/**
 * The news banner (DESIGN_SYSTEM.md section 3, "News banner"; CHR-3;
 * SITE_REDESIGN_2026-09-15.md decision 3). One announcement strip, mounted
 * under the top strip on desktop, under the sport row on phone, and under
 * `.site-nav` on landing -- same content everywhere, dismissible and
 * remembered per browser.
 *
 * EVERY ITEM MUST BE TRUE TODAY. Verified against the repo, not assumed:
 *   1. NFL COMING SOON -- sport.js's registry (CHR-1) marks nfl
 *      `status: "coming_soon"`; nothing on `#/nfl` publishes a pick
 *      (comingsoon.js, CHR-4).
 *   2. TENNIS COMING SOON -- same, tennis is `status: "coming_soon"`.
 *   3. Player props on the card -- src/analysis/daily_card.py's
 *      "PLAYER PROPS ON THE CARD" section (`select_props`,
 *      `_build_prop_pick`, `merge_card_and_props`) genuinely merges prop
 *      picks into the one card the game picks ship on; this is not a
 *      separate, disconnected board.
 *   4. Game times in the viewer's own time zone -- web/js/dom.js's
 *      `formatLocalClock`/`formatLocalDate` (2026-09-14, pacific_time
 *      track) resolve the viewer's IANA zone via
 *      `Intl.DateTimeFormat().resolvedOptions().timeZone`, not a hardcoded
 *      one.
 *
 * TWO ROWS, NOT ONE (see DESIGN_SYSTEM.md section 3's measurement note):
 * row 1 carries the controls (tag, "N of 4", previous/next, dismiss),
 * each a 44px target; row 2 carries the item text at full width, wrapping
 * freely. The longest item measures 636px at 15px -- wider than one line
 * can support below ~1275px and wider than two lines-with-an-inline-tag
 * can support at 360px, which is why the tag and the text never share a
 * row.
 *
 * R_MOTION: items never rotate on their own. There is no `setInterval`/
 * `setTimeout` anywhere in this file -- advancing only ever happens inside
 * a click handler. The 150ms swap fade (when the visitor presses previous
 * or next, and only then) is done with a forced-reflow CSS-transition
 * trick, never a timer, and is skipped entirely under
 * `prefers-reduced-motion: reduce`, where the swap is instant.
 *
 * `aria-live="polite"` is added to the text row only after the first
 * previous/next press -- the initial render must not announce itself.
 *
 * Dismissal: `localStorage['lh.news.dismissed']` is set to `NEWS_VERSION`
 * inside try/catch. If storage throws (private mode, quota, a locked-down
 * embed), the dismissal falls back to an in-memory flag that lasts only
 * for the current page view -- a caught exception, never an uncaught one,
 * per DESIGN_SYSTEM.md section 3. A new `NEWS_ITEMS` list ships with a new
 * `NEWS_VERSION`, so a stored dismissal of an older version never hides
 * the new one.
 */

import { el, clear } from "./dom.js";
import { chip } from "./layout.js";

const STORAGE_KEY = "lh.news.dismissed";

/** Bumped whenever NEWS_ITEMS changes, so an old dismissal never hides a
 * genuinely new item list. */
export const NEWS_VERSION = "2026-09-15";

/** Verbatim, in this order (SITE_REDESIGN_2026-09-15.md decision 3,
 * DESIGN_SYSTEM.md section 3). `href` is the bare app hash; `mountNews`
 * applies `linkPrefix` at render time so the same list works from
 * `index.html` and, prefixed, from `landing.html`. Item 4 has no link in
 * the source spec -- it names a fact about every clock on the site, not
 * one destination. */
export const NEWS_ITEMS = [
  {
    tag: "COMING SOON",
    text: "NFL: picks for this season are being tested on this week's games before they go on the record.",
    href: "#/nfl",
  },
  {
    tag: "COMING SOON",
    text: "Tennis: a match board for ATP and WTA events.",
    href: "#/tennis",
  },
  {
    tag: "NEW",
    text: "Player props now sit on the daily card with the game picks.",
    href: "#/today",
  },
  {
    tag: "NEW",
    text: "Game times show in your own time zone.",
    href: null,
  },
];

// Fallback used only when localStorage itself throws on read or write.
let inMemoryDismissedVersion = null;

function readDismissedVersion() {
  try {
    return window.localStorage.getItem(STORAGE_KEY);
  } catch (_) {
    return inMemoryDismissedVersion;
  }
}

function writeDismissedVersion(version) {
  try {
    window.localStorage.setItem(STORAGE_KEY, version);
  } catch (_) {
    inMemoryDismissedVersion = version;
  }
}

function prefersReducedMotion() {
  try {
    return Boolean(
      window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches
    );
  } catch (_) {
    return false;
  }
}

function tagKind(tag) {
  return tag === "NEW" ? "new" : "coming-soon";
}

/**
 * Mounts the banner into `host` (a data-hook="news-host" element the
 * chrome shell owns). Renders nothing at all -- not a hidden node, an
 * empty host -- once the current `NEWS_VERSION` has been dismissed on
 * this browser.
 *
 * `linkPrefix` (default `""`) is prefixed onto every item's href, exactly
 * like `renderSportLevel`'s and `renderDisclaimerFooter`'s own
 * `linkPrefix` parameter: app routes are unaffected, and `landing.js`
 * passes `"index.html"` so a link resolves from `landing.html` instead of
 * pointing at a bare, page-less `landing.html#/nfl` fragment.
 */
export function mountNews(host, { linkPrefix = "" } = {}) {
  if (!host) return;
  clear(host);

  if (readDismissedVersion() === NEWS_VERSION) return;

  let index = 0;
  let liveAfterInteraction = false;

  const region = el("div", {
    class: "news",
    "data-hook": "news-banner",
    role: "region",
    "aria-label": "News",
  });

  const row1 = el("div", { class: "news__row" });
  const tagHost = el("span", { "data-hook": "news-tag" });
  const count = el("span", { class: "news__count", "data-hook": "news-count" });
  const spacer = el("span", { class: "news__spacer" });
  const prevBtn = el("button", {
    type: "button", class: "news__nav", "data-hook": "news-prev",
    "aria-label": "Previous item", text: "‹",
  });
  const nextBtn = el("button", {
    type: "button", class: "news__nav", "data-hook": "news-next",
    "aria-label": "Next item", text: "›",
  });
  const dismissBtn = el("button", {
    type: "button", class: "news__dismiss", "data-hook": "news-dismiss",
    "aria-label": "Dismiss", text: "×",
  });
  row1.appendChild(tagHost);
  row1.appendChild(count);
  row1.appendChild(spacer);
  row1.appendChild(prevBtn);
  row1.appendChild(nextBtn);
  row1.appendChild(dismissBtn);

  const textRow = el("p", { class: "news__text", "data-hook": "news-text" });

  region.appendChild(row1);
  region.appendChild(textRow);

  function paint(fade) {
    const item = NEWS_ITEMS[index];

    clear(tagHost);
    tagHost.appendChild(chip(item.tag, tagKind(item.tag)));
    count.textContent = `${index + 1} of ${NEWS_ITEMS.length}`;

    clear(textRow);
    if (item.href) {
      textRow.appendChild(el("a", { href: `${linkPrefix}${item.href}`, text: item.text }));
    } else {
      textRow.textContent = item.text;
    }
    if (liveAfterInteraction) textRow.setAttribute("aria-live", "polite");

    if (fade && !prefersReducedMotion()) {
      textRow.style.transition = "none";
      textRow.style.opacity = "0";
      // Force a reflow so the browser registers opacity:0 as its own style
      // recalculation before the transition below is applied -- otherwise
      // the two writes coalesce into one and nothing visibly fades.
      void textRow.offsetWidth;
      textRow.style.transition = "opacity 150ms ease";
      textRow.style.opacity = "1";
    } else {
      textRow.style.transition = "";
      textRow.style.opacity = "";
    }
  }

  function go(delta) {
    index = (index + delta + NEWS_ITEMS.length) % NEWS_ITEMS.length;
    liveAfterInteraction = true;
    paint(true);
  }

  prevBtn.addEventListener("click", () => go(-1));
  nextBtn.addEventListener("click", () => go(1));
  dismissBtn.addEventListener("click", () => {
    writeDismissedVersion(NEWS_VERSION);
    clear(host);
  });

  paint(false);
  host.appendChild(region);
}
