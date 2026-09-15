/**
 * The coming-soon page (DESIGN_SYSTEM.md section 4, "Coming-soon page";
 * CHR-4). Used on `#/nfl`, `#/nfl/today`, `#/nfl/record`, `#/tennis` and
 * `#/tennis/board` -- main.js sends every one of those five routes to this
 * one function instead of `renderCard`/`renderCardRecord`/
 * `renderTennisBoard`, and stops importing `tennis.js` for the purpose of
 * routing (tennis.js itself stays on disk, unmodified and unrouted, per
 * DESIGN_SYSTEM.md section 6's "NFL and Tennis" -- `tests/test_web_tennis_
 * board.py` reads it directly and keeps passing untouched).
 *
 * NEVER SHOWN: a pick, a figure, a price, a percentage, a count or a
 * subscribe action (shell-09, nfl-today-2, tennis-board-2). NO API CALLS
 * OF ANY KIND -- this module imports nothing from api.js. The page is
 * static copy plus two links to the live MLB product.
 *
 * COPY, VERIFIED TRUE TODAY:
 *   - NFL/Tennis text is DESIGN_SYSTEM.md section 4's own corrected
 *     wording verbatim (the first draft's "with a page for every matchup"
 *     promised an unbuilt feature and was dropped there; not reintroduced
 *     here).
 *   - NBA/NHL are written in the same shape. docs/ROADMAP.md Stage 16
 *     (R16-26) is the only place season timing for either sport is stated
 *     at all -- and it states an approximate MONTH, not a date, a price or
 *     a percentage, and both are still-OPEN queue items, not work already
 *     under way. So the NBA/NHL "what is being tested now" section says
 *     plainly that nothing is being tested yet (unlike NFL, whose forward
 *     capture is already live per Stage 16's own NFL rows), and gives no
 *     number of any kind -- no date, no count, no price, no percentage --
 *     only the same qualitative "later this year" Stage 16 itself uses in
 *     its own framing.
 */

import { el, clear } from "./dom.js";
import { pageHeader, chip } from "./layout.js";

const COPY = {
  nfl: {
    label: "NFL",
    title: "NFL is coming soon.",
    purpose: "NFL picks are not published yet.",
    coming: "Daily picks published before each game and graded in public, win or lose.",
    testing: "Picks for this season are being tested privately on this week's games. "
      + "None are on the record, and none are shown here.",
  },
  tennis: {
    label: "TENNIS",
    title: "Tennis is coming soon.",
    purpose: "Tennis picks are not published yet.",
    coming: "A match board for ATP and WTA events.",
    testing: "Match prices are being collected privately.",
  },
  nba: {
    label: "NBA",
    title: "NBA is coming soon.",
    purpose: "NBA picks are not published yet.",
    coming: "Daily picks published before each game and graded in public, win or lose.",
    testing: "Nothing is being tested yet. NBA capture and testing are planned for later this year.",
  },
  nhl: {
    label: "NHL",
    title: "NHL is coming soon.",
    purpose: "NHL picks are not published yet.",
    coming: "Daily picks published before each game and graded in public, win or lose.",
    testing: "Nothing is being tested yet. NHL capture and testing are planned for later this year.",
  },
};

function copyFor(sport) {
  const key = String(sport || "").toLowerCase();
  if (Object.prototype.hasOwnProperty.call(COPY, key)) return COPY[key];
  // A future sport this module has not been told the copy for yet -- an
  // honest generic fallback rather than crashing or guessing at wording.
  const label = key ? key.toUpperCase() : "THIS SPORT";
  return {
    label,
    title: `${label} is coming soon.`,
    purpose: `${label} picks are not published yet.`,
    coming: "Daily picks published before each game and graded in public, win or lose.",
    testing: "Nothing is being tested yet.",
  };
}

function section(heading, itemText) {
  const wrap = el("div", { class: "comingsoon__section" });
  wrap.appendChild(el("h2", { class: "comingsoon__heading", text: heading }));
  const list = el("div", { class: "comingsoon__list" });
  list.appendChild(el("p", { class: "comingsoon__item", text: itemText }));
  wrap.appendChild(list);
  return wrap;
}

/**
 * Renders the coming-soon page for `sport` (e.g. "nfl", "tennis", "nba",
 * "nhl") into `container`. Clears and fully owns `container` -- there is
 * no loading state, because there is nothing to fetch.
 */
export function renderComingSoon(container, sport) {
  if (!container) return;
  clear(container);
  const copy = copyFor(sport);

  // pageHeader() is called WITHOUT `eyebrow`: the design calls for the
  // sport name next to a RED "COMING SOON" tag (the same red the top-right
  // strip items use, D4), not plain --text-3 eyebrow prose, so the eyebrow
  // row is built by hand here and inserted as the header's first child --
  // reusing the existing `.pagehead__eyebrow` type rules, just with a chip
  // riding along inside them.
  const header = pageHeader({ title: copy.title, purpose: copy.purpose });
  const eyebrowRow = el("p", { class: "pagehead__eyebrow comingsoon__eyebrow" });
  eyebrowRow.appendChild(el("span", { text: copy.label }));
  const tag = chip("COMING SOON", "coming-soon");
  tag.style.marginLeft = "10px";
  eyebrowRow.appendChild(tag);
  header.node.insertBefore(eyebrowRow, header.node.firstChild);
  // No status line (DESIGN_SYSTEM.md section 4: "no status line").

  const page = el("div", { class: "comingsoon", "data-hook": "comingsoon-page" });
  page.appendChild(section("What is coming", copy.coming));
  page.appendChild(section("What is being tested now", copy.testing));

  const actions = el("div", { class: "comingsoon__actions" });
  actions.appendChild(el("a", {
    href: "#/today", class: "btn btn--primary",
    "data-hook": "comingsoon-primary", text: "See today's MLB picks",
  }));
  actions.appendChild(el("a", {
    href: "#/record-card", class: "btn btn--ghost",
    "data-hook": "comingsoon-secondary", text: "View MLB results",
  }));
  page.appendChild(actions);

  header.body.appendChild(page);

  // CHR-4: the outlet has no default side padding and `.pagehead` itself
  // has zero inline padding (components.css), so appending the header
  // straight into `container` left the eyebrow, h1, panels and buttons
  // flush against the phone's left border and against the rail on
  // desktop. `.gutter` (app.css) is the same 40px desktop / 16px phone
  // wrap `today.js`/`games.js`/`card.js` already use for their own page
  // content -- wrapping both header nodes in one here gives this page
  // the gutter section 7 requires without changing the shared header
  // primitive every other page will also mount.
  const wrap = el("div", { class: "gutter" });
  wrap.appendChild(header.node);
  wrap.appendChild(header.body);
  container.appendChild(wrap);
}
