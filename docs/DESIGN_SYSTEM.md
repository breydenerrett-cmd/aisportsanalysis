# LINEHOUND design system

The reference every page is built to. Sources: `docs/SITE_REDESIGN_2026-09-15.md`
(owner decisions D1-D9), `Desktop/LineHound_Review_2026-09-14/05_AMENDMENT_2026-09-14.md`
(sections 1-9, cited below as R1-R9 for its numbered rules), Direction A
(`Desktop/LineHound_Review_2026-09-14/concepts/A_franchise_desk/`). Finding
ids are from the 2026-09-15 nine-group page audit
(`scratchpad/audit_results/01-09`). This is the corrected version of the
2026-09-15 draft, after two independent adversarial reviews
(`scratchpad/audit_results/11`, `/12`) and direct verification of every
challenge point against `tests/` and `src/`. See "Corrections applied" at
the end for what changed and why.

## 1. Principles

- **A desk, not a scoreboard.** A labelled menu with a clear selected state
  sits beside one ranked list that gets louder toward the top. Rank 1 stands
  out by size and a white edge, never by colour.
- **The pick first, the numbers one tap away.** A card says what the pick is
  and when it was published. The market / our number / break-even
  comparison lives in "View breakdown" (amendment section 1, cited as R3).
- **Every status is a recorded field, said in words.** Nothing is invented.
  Colour never carries meaning alone. A condition that should stop someone
  acting stays on the card (R2, amendment section 1).
- **Say only what is true today.** One experimental notice, record wording
  that matches the lock policy, coming-soon sports that show no picks, and
  Live kept out of public view (R4/R7, amendment section 7; D4, D5).
- **One system.** The same shell, header, section heads, cards, tables,
  states and voice on every page, at 1440, 390 and 360 wide (D8).
- **No idle motion (R_MOTION).** Nothing on the page moves unless the
  visitor did something or new data arrived. This is its own rule, not a
  restatement of "no entrance motion" — see section 8.

## 2. Tokens (`web/css/tokens.css`)

Reuse existing values. Add these role aliases at the end of the file. New
rules use role names, never `--v-*` or `--money*` directly.

| Role | Token | Value | Use |
|---|---|---|---|
| Ground | `--ground` (exists) | #0B0C0E | page |
| Strip | add `--panel-3: var(--tile-base)` | #0E1013 | chrome: strip, rail, tab bar, banner |
| Panel | add `--panel` | #111317 | cards |
| Nested | add `--panel-2` | #15171B | breakdown boxes |
| Hairline | add `--edge-soft: var(--edge-1)` | white .07 | row dividers |
| Border | add `--edge` | rgba(255,255,255,.10) | panel borders |
| Strong edge | add `--edge-hi` | rgba(255,255,255,.28) | secondary buttons, neutral chips, rank-1 edge |
| Red | add `--primary: var(--money)`, `--primary-soft: rgba(255,61,87,.13)` | #FF3D57 | brand mark, selected item, one primary action, COMING SOON |
| Cyan | add `--fresh: var(--live)`, `--fresh-text: var(--live-badge)` | #00E0FF / #8FE9FA | confirmed inputs, times, links, focus ring |
| Amber | add `--caution: var(--v-warn)`, `--caution-text: var(--v-warn-label)`, `--caution-soft: rgba(255,176,32,.10)` | #FFB020 / #FFCF6B | waiting on an input: lineup, starter, an older quote |
| Win | add `--win: var(--v-win-label)` | #7BE8AC | the word "Win" only |
| Text | `--text-hi`; `--text-2` body; `--text-3` secondary; `--text-mute` at 15px and up | | |

Red is never a better price, a loss, staleness, an error or decoration.
Cyan is never a button fill. Loss/push/void are neutral, not red — a
customer's own bad night is not a warning colour.

**Retire:**
- `--money-2` gradients.
- `--money-lit` and `--money-soft` used as text colours.
- `--text-dim`, `--text-ghost` and `--v-t7` used as text (under 4.5:1).
- `.btn--cyan` as a fill (kept as an alias of secondary until every caller
  migrates — see section 3's "shared class names" note).
- Textures, sheens and glows.
- Every idle-motion duration and keyframe: `--dur-gseam`, `--dur-gsheen`,
  `--dur-gbreathe`, `--dur-gping`, `--dur-gcaret`, `--dur-gtype`, and the
  seven `infinite` animations confirmed in the current CSS (gseam, gsheen,
  three gbreathe uses, a skeleton pulse, a spinner) plus the `gseam`/
  `gsheen`/`gbreathe` uses in `base.css` and `landing.css`. See section 8.

**Type.**
- Font families stay the same.
- Add `--fs-meta: 13px` (desktop labels only), `--fs-small: 15px`,
  `--fs-body: 17px`, `--fs-lead: 19px`, `--fs-h3: 22px`, `--fs-h2: 26px`,
  `--fs-h1: 34px` and `--fs-hero: clamp(40px, 6vw, 72px)`.
- Line height is 1.5 for body text and 1.1 for display text.
- Display type is upright. Italic survives only in the wordmark.
- Figures use tabular numerals.

**Spacing.**
- Use `--sp-3`, `--sp-5`, `--sp-7`, `--sp-9`, `--sp-12`, `--sp-13` and
  `--sp-15` (8 to 56px).
- Change `--gutter-mobile` from 14px to 16px, `--rail-width` from 76px to
  228px, and `--tabbar-height` from 74px to 60px.
- Add `--strip-height-phone: 56px` and `--sportrow-height: 44px`.

**Radii and elevation.** Everything is flat and square, with 1px borders.
The chamfer stays on three things only: the brand mark, the rank-1 card
corner (`--r-panel`) and the primary button (`--r-btn`). No shadows except
the focus ring. Depth comes from surface steps: ground, panel-3, panel,
panel-2.

## 3. The shell

**Ownership note.** `web/js/shell.js`, `web/js/main.js`, `web/js/sport.js`,
`web/js/meta.js`, `web/index.html`, `web/css/nav.css` and `web/css/app.css`
are owned by the **chrome** group. `web/css/tokens.css`, `web/css/base.css`,
`web/css/components.css`, `web/js/layout.js`, `web/js/states.js`,
`web/js/dom.js`, `web/js/motion.js` are owned by **foundation**, which
chrome depends on.

**Top strip, desktop (900px and up).** 64px tall, `--panel-3`, with a 1px
`--edge` line below. Left to right:
1. Hound mark and LINEHOUND, linking to `landing.html`.
2. A 1px rule.
3. Live sports as tabs: "MLB", display 700 17px, with a 3px red underline
   when selected.
4. A spacer.
5. The coming-soon items.
6. A 1px rule.
7. The clock: mono 13px, in the viewer's time zone. **Hidden between 900
   and 1199px** (see section 9, width budget) and shown again at 1200px+.

There is no sport switcher dropdown, no Live link, no section-label text and
no status readout in the strip (shell-01, shell-02, live-1). The status line
moves into the page header (section 4).

**COMING SOON items.**
- "NFL · COMING SOON" links to `#/nfl`; "TENNIS · COMING SOON" links to
  `#/tennis`.
- Display 700, 15px, uppercase, letter-spacing .06em, colour `--primary`
  (5.4:1 on the strip).
- Text only, 20px apart, min-height 44px. A label never wraps inside
  itself.
- Hover and focus show an underline. On the item's own page it gets a 3px
  red underline and `aria-current="page"`.
- The tag on the news banner (below) uses a neutral border, not red — D4
  reserves red for these two top-right labels specifically, not every
  "coming soon" mention sitewide (see "corrections applied", L2).

**Phone (under 900px).**
- **Row 1**, 56px: hound mark and LINEHOUND at 18px. No clock (shell-04).
- **Row 2**, the sport row, 44px, 16px gutters: "MLB" tab on the left, both
  red items on the right, wrapping allowed if a fallback font is briefly
  wider (measured: at 360px, both red labels total 275px against a 328px
  content width once the MLB tab is hidden below 400px — see section 9).
- **Under 400px the MLB tab hides**, not under 375px as the first draft
  said — measured slack at 375-399px is 4px, not enough headroom for any
  real font metric or tab padding.
- Neither row is sticky. One host element renders the sport-level content;
  CSS repositions it between the desktop strip and the phone row (a single
  `renderSportLevel` mount, not two — see the corrected build note below).

**News banner** (`web/js/news.js`, new; shell-08, landing-01).
- **Placement:** under the top strip on desktop, under the sport row on
  phone, and under `.site-nav` on landing.
- **Layout:** two rows, not one. **Row 1** carries the controls (tag,
  "1 of 4", previous/next, dismiss "×"), each a 44px target. **Row 2**
  carries the item text at full width, wrapping freely. Splitting text
  from controls this way is required, not stylistic: the longest item
  ("COMING SOON · NFL: picks for this season are being tested on this
  week's games before they go on the record.") measures 636px at 15px —
  wider than the "one line on desktop" claim in the first draft could
  support below roughly 1275px, and wider than "two lines on phone" could
  support at 360px once a tag sits inline with it. Wrapping text on its
  own row, with no length ceiling, fixes both without a special case.
- **Box:** full width, `--panel-3`, with a 1px `--edge-soft` line below.
- **Tags:** COMING SOON is red text with a 1px red border. NEW is
  `--fresh-text` with a 1px cyan border.
- **Text:** 15px `--text-2`.

Items, verbatim, in this order:

1. COMING SOON · NFL: picks for this season are being tested on this week's
   games before they go on the record. (links to `#/nfl`)
2. COMING SOON · Tennis: a match board for ATP and WTA events. (links to
   `#/tennis`)
3. NEW · Player props now sit on the daily card with the game picks.
   (links to `#/today`)
4. NEW · Game times show in your own time zone.

Behaviour:
- Items never rotate on their own (R_MOTION).
- Dismiss stores `lh.news.dismissed = "2026-09-15"` in localStorage, inside
  try/catch. If storage fails, the dismissal lasts for the current page
  view only (a caught exception, never an uncaught one — this is the one
  place in the redesign that touches browser storage, and it must degrade
  silently).
- A new item list gets a new version string, so the banner shows again.
- The item text becomes `aria-live="polite"` only after the visitor
  presses previous or next.
- With reduced motion, items swap instantly. Otherwise they change with a
  150ms opacity fade — a state change the visitor triggered, not idle
  motion.
- On `landing.html`, every link in the banner is prefixed
  (`index.html#/nfl`, not `#/nfl`) — see the `linkPrefix` correction below.

**Sport level and sub menu** (`sport.js`, `main.js`; shell-03, gd-02,
nfl-today-3). One registry holds every sport as `{key, label, status: "live"
| "coming_soon", home, submenu, plan: null}`. NBA and NHL are added as
entries when they are announced (D6), and then appear as red items
automatically. A sport that goes live becomes a tab with its own sub menu.

- `renderSportLevel(host, activeSport, {placement, linkPrefix})` renders
  live sports as tabs and coming-soon sports as the two red links.
  **`linkPrefix` defaults to `""`** so app routes are unaffected;
  `landing.js` calls it with `linkPrefix: "index.html"` so its links resolve
  from `landing.html` (the first draft omitted this parameter entirely,
  which would have made every coming-soon link on the landing page point at
  a non-existent `landing.html#/nfl` fragment with no page behind it —
  confirmed dead-end in the first draft, not shipped).
- **`renderSportLevel` runs on every route change, not once in `boot()`.**
  `aria-current` and the selected MLB tab change per route, and mounting
  once at boot would freeze the selected state at whatever the first route
  was. It is called from the same place `mountNav`/`setSectionLabel`
  already are, inside `_renderRouteInner`.
- Route aliases (`#/gameday`, `#/matchups`, `#/results`, `#/mlb/...`)
  resolve **inside the router** (`parseSport`/`_renderRouteInner`), not via
  `location.replace` and not via a second, separate "strip a leading mlb"
  step — one alias table, checked once, per route.

**Desktop rail.** 228px wide, `--panel-3`, full height. Heading "MLB"
(display 700 13px, `--text-3`). Items are at least 64px tall, with the
index in mono 14px, the label in display 700 19px and the sub-line at 13px:

- 01 GAMEDAY · Today's picks → `#/today`
- 02 MATCHUPS · Every game, in depth → `#/games`
- 03 PROPS · Priced player props → `#/props`
- 04 RESULTS · Every pick, graded → `#/record-card`
- 05 BETS · Your saved bets → `#/mybets` (shown only when the visitor is
  signed in **and** `public_demo` is false — D7 restricts BETS to signed-in
  users; the first draft only hid it in the public demo, which left a
  signed-out, non-demo visitor seeing BETS and landing on a 401 gate. The
  item is hidden until both conditions are confirmed, matching how the
  existing code already treats "not known yet" as "hide it", never as "show
  it and let it 401".)

The selected item gets a 4px red left border, a `--primary-soft` wash, a
red index and `aria-current="page"`.

Selection is decided from the route with the sport prefix removed
(shell-06's actual defect: `mountNav`'s `activeHash` is built from the
**pre-sport-parse** hash `"#/" + segments.join("/")`, e.g. `"#/nfl/today"`,
while `NAV_ITEMS`' hashes are un-prefixed `"#/today"`, so
`navItem`'s `activeHash.indexOf(item.hash) === 0` check can never match on
a sport-prefixed route — this is why no rail item highlights on the NFL
empty-card page today. Fix: compare against the sport-stripped `route`
value, the same one already used for `setSectionLabel`):
- `games`, `game` and `odds` select MATCHUPS.
- `record-card` selects RESULTS.
- `betcheck`, `performance`, `day`, account routes and coming-soon routes
  select nothing.

`NAV_ITEMS` keep the existing entry shape
`{ hash: "#/props", label: "PROPS", ... }` (verified against the current
array in `main.js`: each entry is already `{hash, label, glyph}`; the
redesign drops `glyph`, adds `sub`, and nothing else about the shape
changes). This exact shape, with `hash` immediately followed by `label`,
is required by `tests/test_whose_record_is_it.py`'s regex match on the
RESULTS entry — write it as `{ hash: "#/record-card", label: "RESULTS",
sub: "Every pick, graded" }`, in that field order, and it stays green.

**Phone tab bar.**
- Fixed to the bottom, `--tabbar-height` plus the safe area.
- Equal-width tabs, label only: display 700 15px, no glyphs (shell-05: the
  old rail's `.glyph--line` was reused for both PROPS and RESULTS with
  nothing to tell them apart but the text underneath — dropping icons
  entirely removes the ambiguity instead of hunting for a fourth shape).
  Each tab is at least 56px tall.
- The selected tab gets a 4px red top border and the wash.
- Page content is padded by the bar height plus 16px.
- Hidden on `#/live` (live-4).
- At 360px with five tabs visible (signed-in, non-demo), each cell is 72px;
  "MATCHUPS" at 15px condensed needs roughly 60-66px unpadded. Acceptance
  covers this explicitly in section 9 — the first draft had no check for
  it.

**Per-sport plan, later (D6).** The rail reserves `data-hook="sport-plan"`
under its items; on phone the Gameday header reserves the same slot. While
`plan` is null the slot renders nothing: no box, no price, no per-sport
wording. Once billing supplies a plan, it shows "MLB · $X/mo" and a
secondary "Subscribe to MLB" button.

**Status line.**
- It lives in the page header, not the strip.
- `setShellStatus(text, options)` **keeps its exact signature** (both
  `games.js`'s `setShellStatusFromStaleness` and `live.js`'s direct calls
  depend on it unchanged), but its target changes: `pageHeader()` (section
  4) returns `{node, setStatus, body}`, and `setShellStatus` writes into
  the **currently mounted header's** `setStatus`, caching the last value so
  a header mounted after the call (or a late call that lands after a route
  change) does not silently disappear or bleed into the wrong page. This
  fixes a real ordering bug the first draft did not address: several
  screens call `renderError(container, err)` where `container` is the
  *whole* content area including the header
  (`performance.js:638`, `cardrecord.js:596`, `dayrecap.js:553`,
  `live.js:265`, `signup.js:192`, confirmed by reading each call site) —
  `renderError` clears its container, which would wipe a header the spec
  says must "always stay on screen" unless the header and the state body
  are separate DOM nodes. `pageHeader()`'s returned `body` node is what
  every render function now clears and re-renders into; the header node
  itself is never touched by a loading/error/empty state.
- No breathing dot (R_MOTION).
- **Stale threshold: not a flat 90 minutes.** The first draft's "90
  minutes, because prices are captured hourly" does not match the real
  capture cadence (`.github/workflows/forward-capture.yml` runs slots
  roughly 13 minutes apart during game hours and 60 minutes in quiet
  hours; `scripts/capture_slot.sh` takes one odds capture per slot). A
  flat 90-minute threshold would let a 75-minute outage during game hours
  read as fresh. Use the game-hours cadence: flag stale after
  approximately two missed slots (about 30 minutes) when any game's first
  pitch is within a few hours, and after 90 minutes otherwise (quiet
  hours). Stale text uses `--caution-text` and gives the age in words
  ("68 min ago"), never a flat "STALE" badge on every row regardless of
  real age (this also fixes odds-2/oddsgame-2 — see section 6).

**Footer** (`meta.js`).
- **Row 1:** LINEHOUND; "21+ · Play responsibly · 1-800-GAMBLER" (source
  text stays uppercase **"PLAY RESPONSIBLY"** — `tests/test_shared_footer.py`
  pins that exact case-sensitive string; the source string does not need to
  visually shout, CSS may `text-transform` it, but the DOM text itself must
  stay uppercase or the test needs a matching, deliberate update, which is
  not part of this build); links to Results, Research, Player props, Bet
  Check and Support. Add `footer-betcheck` and keep the existing hooks.
- **Row 2:** the summary sentence (section 5).
- **Row 3:** "Full beta disclaimer", unchanged.
- **Row 4:** "Times shown in PDT, your time zone." (do not duplicate "ALL
  TIMES PDT" from elsewhere in the footer — the first draft's row 4 note
  repeated existing copy; keep one instance).
- **Phone:** links at 15px in a two-column grid of 44px targets.
- `renderDisclaimerFooter(container, {linkPrefix})` also takes the same
  `linkPrefix` parameter as `renderSportLevel`, for the same reason — the
  footer's Bet Check link, rendered from `landing.js`, needs to resolve to
  `index.html#/betcheck`, not a bare `#/betcheck` fragment on
  `landing.html` that goes nowhere.

**Shared class names, named explicitly** (a gap in the first draft: it said
"rebuild `.btn`... retire `.btn--cyan`" without naming the new classes, and
nine JS files plus `landing.html` currently use `.btn--ghost`, four use
`.btn--cyan`). `components.css` (foundation) defines, and every later group
uses by name:
- `.btn--primary` — solid `--primary` fill, white display 700 19px, 48px,
  chamfered.
- `.btn--ghost` — kept as the name for the secondary style (1px
  `--edge-hi`, 17px, 44px) so the nine existing call sites do not all need
  a rename in the same pass.
- `.btn--text` — new, `--fresh-text`, underlined, 44px target.
- `.btn--cyan` stays defined, pointed at the same rules as `.btn--ghost`,
  until every caller (`games.js`, `mybets.js`, `today.js`, `landing.html`)
  migrates in its own group's pass. No gradients, no hover lift, anywhere.
- `.glyph` and its variants (`.glyph--circle`, `.glyph--line`,
  `.glyph--ticket`) are deleted from `nav.css` **only** — verified that
  `betcheck.js`'s one mention of the word "glyph" is prose inside a code
  comment ("empty glyph on every check"), not a class reference, so this
  deletion does not touch Bet Check. (The first adversarial review flagged
  this as a cross-group break; checked directly and it is not one — see
  "corrections applied", rejected point.)
- Chip, `.dtable` (including its phone stacked mode and `.dtable--scroll`
  sticky-first-column variant), `.rankrow`, `.field`/`.form`, `.notice
  --experimental`, `.pagehead`, `.disclosure`, `.news`, `.comingsoon`,
  `.sportlevel` and neutral `.state-*`/gate classes are all defined once in
  `components.css` before any page group starts, so no two groups invent
  their own version.

## 4. Page anatomy

**Page header** (`web/js/layout.js`, foundation), in this order:
1. **Eyebrow:** sport · section. Display 700, 13px desktop / 15px phone,
   `--text-3`.
2. **Title (h1):** display 800, 34px / 28px, `--text-hi`.
3. **Purpose:** one sentence, 17px / 16px, `--text-2`, at most 70ch.
4. **Status line:** mono 14px / 15px, `--text-3` with values in
   `--text-hi`, `role="status"`. Every fact is named, e.g. "Published 9:40
   AM PDT · prices checked 11:05 AM PDT".

`pageHeader({eyebrow, title, purpose, status})` returns `{node, setStatus,
body}`. `node` mounts once per route; `body` is what every loading/empty/
error/content render clears and repaints (see section 3's status-line
note — this is the fix for the header-gets-wiped bug). One h1 per page.

**Section head** (`.sechead`). A label (display 700 16px, `--text-2`), a
hairline, and meta (mono 13px). On phone the meta moves under the label at
15px. It is never hidden, because it carries counts.

**Experimental notice.**
- One block above the picks: "Experimental selections. Performance is
  still being evaluated."
- `--panel-3`, 1px `--edge`, a 4px `--edge-hi` left edge, 15px text.
- Shown on Gameday and wherever a pick appears directly (matchup detail,
  landing sample card).
- Never a badge on each card.
- It stays in place in empty and error states (nfl-today-4).

**Compact pick card** (amendment section 1, R3). Every card is `--panel`
with a 1px `--edge` border and 12px 16px padding.

```
#1 · Canyon at Harbor · 4:10 PM PDT          rank, matchup, first_pitch_utc
Harbor to win · full game moneyline          selection, market, line
-150 at DraftKings · published 9:40 AM PDT   price, book, published_utc / frozen_at
Harbor's starter has held right-handed lineups to a low on-base rate all season.
[Lineup not posted]  [Provisional until 12:10 PM PDT]      only when true
View breakdown
```

- **Type:** line 1 mono 15px; line 2 display 800, 26px desktop / 24px
  phone; line 3 15px with the price in mono.
- **Reason:** `why[0]`, the payload's first reasoning string, rendered
  **whole, never split on sentence punctuation client-side.** The first
  draft said "the first sentence the payload carries", but `pick.why` is
  an array whose first element today reads as a stat line ("Rays score 4.5
  runs a game and give up 4.2. ATH score 4.4 and give up 5.7."), not a
  single narrative sentence, and a client-side sentence-splitter would
  also break on abbreviated names like "J. Ortega". Show `why[0]` as
  delivered.
- **Conditions, in words, from recorded fields:**
  - "Lineup not posted" and "Starter unconfirmed" are amber. They come
    from `knowledge.core.*`, and for props from `expected_pa_source`.
  - **"Provisional until [first_pitch_utc minus lock lead hours]" shows
    only while `now < that time`. "Locked" shows only while the payload's
    own `locked` field is `true`.** These are not the same guard. `locked`
    is stamped only during a publish run (`card_ledger._lock_and_merge`),
    so between the cutoff and the next publish the stored value can still
    read `false` even though the cutoff has passed. Showing "Locked" the
    moment the clock crosses the cutoff — inferring it client-side — would
    invent a status the record does not yet confirm, which R2 forbids. In
    that gap, show a third, neutral state: **"Lock pending · graded as
    published."** Lock lead hours are read from the payload, not
    hardcoded as "4h" in the client, since `lock_lead_for(sport)` varies by
    sport in the source even though only MLB ships picks today.
  - There is no "price has moved" status and no main-risk line, because no
    field records either.
- **Rank 1:** a 4px `--edge-hi` left edge, a chamfered corner, and a 30px
  selection line.
- **Phone, rank 4 and below:** the same fields and the same condition
  chips as a full card, never fewer — amendment section 1 says a condition
  is never hidden to make a card cleaner. What changes at rank 4+ is
  density only: rank and selection share one line, price/book/published
  share a second, and condition chips sit on a third, all at the same
  15px floor as a full card, with no "View breakdown" control (rank 4+
  rows still link to "Open this matchup" for the full breakdown instead of
  expanding in place).
- **"View breakdown":** a text button with `aria-expanded` and
  `aria-controls` that expands in place. Inside:
  - Three labelled boxes: "Market says NN%" (market-derived), "Our number
    NN%" (our statistical game model, or our prop estimate) and "Needs
    NN% to break even at -150".
  - The payload's comparison sentence.
  - The argument and counterargument.
  - The alternate bet.
  - The grade letter and its legend.
  - An "Open this matchup" link.
- **Removed from the card:** STRONG / LEAN / SPLIT chips, grade chips, and
  "CHECK THIS PRICE YOURSELF" (gd-03, gd-04).
- **`compactPickCard(pick, opts)` is exported once**, from `card.js`
  (owned by gameday-card), and is the **only** implementation. The first
  draft had `landing-live.js` build its own copy of the same card
  independently — two hand-maintained implementations of the identical
  anatomy would drift the first time either page changed. `landing.js`
  imports `compactPickCard` from `card.js` and adds `web/css/card.css`'s
  link to `landing.html` (landing does not currently load it at all).

**Tables and ranked rows** (`.dtable`).
- Header cells 13px display. Body cells 15px. Figures in mono,
  right-aligned. `--edge-soft` dividers.
- **On phone, tables with more than three columns** stack each row into
  label: value pairs under a row title (REC-5, mybets-7).
- **Wide book tables** scroll inside their container, with a sticky first
  column and the caption "Swipe for more books".
- **Ranked rows:** at least 56px tall; rank 20px; selection 17-19px; meta
  15px.

**Buttons.**
- **Primary:** `--primary` fill, white display 700 19px (large text,
  3.5:1), 48px tall, chamfered. Never two in one viewport (Direction A's
  rule is "one primary action per screen" — the compact-card's own
  primary "View breakdown" toggle and a page-level primary button do not
  count as two, since only one page-level primary CTA is ever rendered;
  landing's hero primary is "See today's picks" and "Get founding access"
  in the pricing section is styled **secondary**, not a second primary in
  the same viewport — the first draft left this as a primary, which
  Direction A's own rule forbids).
- **Secondary:** 1px `--edge-hi` border, 17px, 44px tall.
- **Text:** `--fresh-text`, underlined, 44px target.
- No gradients and no hover lift.

**Chips.** The word comes first. 13px desktop / 15px phone, square
corners.
- **Confirmed** (cyan dot): "Lineup posted".
- **Waiting** (amber ring): "Lineup not posted", "Starter unconfirmed",
  "No price yet".
- **Neutral** (dashed): "Provisional until ...", "Locked", "Lock pending".
- **Settled:** "Win" uses `--win`; "Loss", "Push" and "Void" are neutral —
  not red. A customer's own loss is not a warning to flash at them.

**States** (`states.js`, foundation). The page header always stays on
screen; every state below renders into `pageHeader()`'s `body` node, never
the header's container (see section 3).
- **Loading:** eyebrow "LOADING"; headline "Loading [thing]..."; one line
  saying what is being fetched; skeleton rows at the real layout size.
  After 15s add "Still loading. The server is slow right now." After 30s
  switch to the error state (PERF-1, gd-07). Use `withLoadingTimeout`
  (`states.js`, foundation-owned — the first draft did not say which
  module owns it, and it must live in one place since `today.js`,
  `matchups.js`, `performance.js` and others all need it identically).
- **Network failure vs. server error, kept distinct.** When the request
  itself never reached the server (no response, `status` is `null`), the
  error body reads **"We could not reach the board."**, distinct from a
  server response that returned an error — `tests/test_request_timeout.py`
  pins this exact sentence plus "it is not the same as" and "Technical
  detail" in `dom.js`, and the first draft's generic "[Thing] didn't load."
  / "The request failed." copy would have silently dropped this
  distinction (a real network outage read identically to a server 500).
  Both cases share the same neutral panel and "Try again" / "Technical
  detail" structure; only the headline sentence differs by cause.
- **Empty:** an eyebrow naming the state (e.g. "NO PICKS TODAY"). The
  headline is the payload's reason, verbatim. One secondary action.
- **Not available yet:** an amber marker, the missing input named, and the
  reason verbatim.
- **Signed out:** eyebrow "SIGN IN REQUIRED", headline "Sign in to see
  this.", primary button "Sign in". (Never names the specific route or
  says "tonight's board" — the gate is shared across every signed-in
  route, including ones with nothing to do with tonight.)

**Coming-soon page** (`web/js/comingsoon.js`, new, chrome-owned). Used on
`#/nfl`, `#/nfl/today`, `#/nfl/record`, `#/tennis` and `#/tennis/board`.
- **Header:** eyebrow "NFL" with a red COMING SOON tag; title "NFL is
  coming soon."; purpose "NFL picks are not published yet."; no status
  line.
- **What is coming** (planned, no date set — see the corrected copy
  below):
  - NFL: "Daily picks published before each game and graded in public,
    win or lose." (The first draft's longer "with a page for every
    matchup" promised a feature that does not exist yet; dropped.)
  - Tennis: a match board for ATP and WTA events.
- **What is being tested now:**
  - NFL: "Picks for this season are being tested privately on this week's
    games. None are on the record, and none are shown here."
  - Tennis: "Match prices are being collected privately." (The first
    draft's "there are no tennis picks" sentence is dropped as redundant
    with the coming-soon framing, and to avoid drifting from whatever the
    live tennis capture actually shows at build time — verify against a
    fresh `#/tennis/board` capture before wording this claim more
    specifically.)
- **Actions:** primary "See today's MLB picks", secondary "View MLB
  results".
- **Never shown:** picks, figures, prices or a subscribe action (shell-09,
  nfl-today-2, tennis-board-2). No API calls of any kind — the page is
  static copy plus two links.

## 5. Voice and expectations

Rules for every string:
- Plain English.
- Every number names its source.
- Absence is said as absence.
- No promised outcome, no edge, and no model number called a chance of
  winning.
- "Tonight" only when the slate date is the viewer's date.
- A count only when it is read from a field.

**Every customer-facing string in `web/` must pass
`tests/test_web_structure.py`'s `NoBannedCustomerVocabulary` (and
`LandingVocabularyScan` for `landing.html`) and, for the server strings in
section "Server-side strings" below, `tests/test_customer_language.py`.**
Both import the same two lists from `test_customer_language.py`:

- `HARD_BANNED` — banned outright, negated or not: "+EV", "true line",
  "true probability", "true odds", "market's true read", "free money",
  "lock of the day", "a lock", "expected value play".
- `NEGATION_ONLY` — allowed **only** inside a negation: "edge(s)",
  "guaranteed", "win-probability", "sure thing", "can't lose". A use counts
  as negated only if one of these words appears in the **90 characters
  immediately before** the match: `no, not, none, never, nothing, without,
  zero, cannot, can't, refuses, isn't, aren't, until, instead of, rather
  than, guard` (case-insensitive; verified verbatim from `NEGATORS` in
  `tests/test_customer_language.py`). **"too few" is not in that list.**

This is why the amendment's own suggested preliminary-line wording fails
the scan as written (see "Corrections applied", H5) and why this document
uses "not enough" instead everywhere that sentence appears.

Numbers carry their context:
- Percentages say whose they are: "Market says", "Our number", "Needs ...
  to break even".
- Odds carry the book and the capture time.
- Ages read "68 min ago".
- Record figures carry cohort, period, sample size (n) and the preliminary
  line.

**Record wording (today's policy, amendment section 4/7).**
- **Short:** "Picks are published before each game and graded as they
  stood at their lock, win or lose."
- **Full:** "Each pick is published before its game. Until it locks it is
  provisional, and a later publish can replace it; then it locks at its
  published price. Only the locked version is graded, win or lose.
  Replaced versions stay in the ledger history, ungraded."
- **Record line, e.g.:** "Card picks, graded at their lock, rule v1 ·
  [first]-[last date] · 29 picks · 20-9-0 · +3.69 units at the published
  prices. Preliminary: not enough picks yet to show an edge or its
  absence."
- **Chain, from `chain_ok`:** "Recorded in a hash-chained ledger, each
  entry linked by a hash to the one before it, so changing a past entry
  breaks every link after it. The chain check passes." / "The chain check
  does not pass. Treat every figure on this page as unconfirmed until it
  does."

**Use / avoid.**

| Use | Avoid |
|---|---|
| "published before each game" | "frozen" |
| "hash-chained ledger" | "tamper-proof", "cannot be edited" |
| "Market says" | "fair price" |
| "our statistical game model" | "AI picks" |
| "Experimental selections" | STRONG, LEAN, "value", "edge" |
| "Coming soon" | "research only" |
| "not enough picks yet to show an edge or its absence" | "too few picks to show an edge or its absence" (fails the banned-word scan — see above) |

**Expectation-setting claims found, and their replacements.**

| Where (finding) | Now | Replace with |
|---|---|---|
| Footer, every page (shell-07) | "Three to five bets a day, frozen before first pitch and graded after" | "Beta. Picks are published before each game and graded as they stood at their lock, win or lose. Nothing here is a guarantee." |
| Landing title (landing-05) | "tonight's picks, frozen before first pitch" | "LINEHOUND — Daily MLB picks and matchup analysis" |
| Landing record card (landing-05) | "frozen before first pitch and written to a tamper-proof chain" | "published before each game and recorded in a hash-chained ledger" |
| Landing hero (landing-03, -06) | "Needs 56% to break even · we make it 57%"; "Try 3 Bet Checks free" | The adopted headline, a sample card (via `compactPickCard`), "See today's picks". No "Tonight" before the card loads. |
| Landing data note (landing-04) | "The Pirates/Brewers example above is a fixed demo" | "The pick above is read from today's published card. If it cannot load, a labelled sample shows instead." |
| Landing research line and FAQ answer on predicting winners (amendment section 8) | "Between 2023 and 2024"; "a 64% side" | No years or counts unless read from `/meta`'s `research-count` field; "Market says" wording only |
| Landing FAQ (landing-07) | "other sports are not currently supported" | "MLB today. NFL and tennis are coming soon. NFL picks are being tested privately and are not on the record." |
| Signup bullet (signup-frozen-overclaim) | "Every pick frozen before first pitch, so there's no changing the call" | "Every pick is published before its game. It can still change until it locks, then it's graded as it stood at that lock." |
| Record strip (gd-05) | "every pick frozen before first pitch" | "each pick graded as it stood at its lock" |
| Card record line (gd-05) | "tamper-proof chain" | "hash chain" |
| Older card (card.js) | "frozen before those games started" | "published before those games started" |
| Record intro (REC-4) | "chained so none of it can be quietly edited afterward" | The full record wording above |
| Ledger panel (nfl-record-1) | "nothing below has been changed after the fact" | "The chain check passes." |
| Day page (DAY-2) | "FROZEN PREGAME RECORD" | "PREGAME RECORD" |
| Gameday grid (gd-06) | "PAPER POSITIONS FROZEN BEFORE FIRST PITCH", CONTROL / FORWARD-TEST chips | Removed from Gameday. Research pages only, as "RESEARCH POSITIONS, RECORDED BEFORE FIRST PITCH". |
| Matchup context (gd-10) | "MIL 68.3%" | "Market says MIL 68.3%" |
| Games legend (served by the API, `src/analysis/grade.py` `legend()`) | "A+ means the price is on your side by our own number. That number has been **measured unreliable** when it disagrees with the market..." | "A+ means our number is above what the price needs. That number has not been checked against enough results yet, so read the plus as a note, not a reason." (Not "unreliable" — the amendment's own restated conclusion (section 2) is that at n=29 the tests "cannot distinguish the approaches yet", which is an absence of evidence, not a finding of unreliability. "Unreliable" overstates what was actually shown.) |
| Card props subhead (amendment section 3) | "Ranked by how likely we make them" | "Ranked by how strongly the market favours each, never by the price." |
| Props list (props-3) | Pre-lineup rows on top, with no note | "Rows marked Lineup not posted use a season-average number of plate appearances and can change when lineups post." |
| NFL today (shell-09) | "No NFL games on this date." with a Bet Check button | The coming-soon page |
| Live (live-5) | "Ready." | "Internal testing. No alerts are sent." |
| Server: `CARD_BASIS` (`src/analysis/daily_card.py`) | "...or the pick is **labelled SPLIT**. ... Ranked by how confident the market is." | "...or the pick does not qualify. ... Ranked by how strongly the market favours each pick." (SPLIT is removed from the card entirely — see section 6, gd-04 — so the server text describing it must stop referencing it too.) |
| Server: `CARD_DISCLAIMER` (`src/analysis/daily_card.py`) | "...still **loses money at the vig**. Every pick here is published before first pitch, **frozen**, and graded win or lose." | "...No pick here has shown a positive estimated return under our market benchmark. Every pick here is published before first pitch and graded win or lose." (Matches the amendment's own restated conclusion in section 2 — "no positive estimated return under our market benchmark" — instead of the stronger, unsupported "still loses money at the vig".) |
| Server: `daily_record.LABEL` (`src/report/daily_record.py`) | "FROZEN PREGAME RECORD" | "PREGAME RECORD" |
| Server: `daily_record.BASIS` (`src/report/daily_record.py`) | "...the row the engine **froze** before first pitch..." | "...the row the engine recorded before first pitch..." |

## 6. Page by page

Items are in priority order within each page. Matchups and Results (record,
day, research) keep their layouts and calculations (amendment section 7,
"R6" below) — the exceptions actually required are listed explicitly per
page and are copy or state-guard fixes, never a calculation or layout
change. Findings that repeat the shell problems on individual pages
(betcheck-1 to -3, props-1, odds-1, REC-1, REC-2, PERF-2 and similar) are
closed by the chrome group's shell work, not repeated per page.

**Landing.**
1. News banner and red items under `.site-nav` (landing-01, -02, -08),
   both using `linkPrefix: "index.html"`.
   - Links: Gameday · Matchups · Props · Results · Pricing · FAQ (the first
     draft's nav omitted Props; D7's menu is GAMEDAY · MATCHUPS · PROPS ·
     RESULTS and landing should not silently drop one quarter of it).
   - "Sign in" is a secondary button.
   - On phone: a sport row, with Pricing · FAQ as text links under the
     hero actions.
2. Hero (landing-06):
   - Eyebrow "YOUR MLB GAME PLAN".
   - h1 "Daily MLB picks. Matchup analysis that goes deeper."
   - Subheading "See today's selections, the reasoning behind them, and
     the published record."
   - Primary "See today's picks" (the only primary in this viewport);
     secondary "View results".
3. One sample card via `compactPickCard` (imported from `card.js`), with
   the experimental notice (landing-03).
   - The markup stays neutral until `/card` responds — no "Tonight", no
     team names, until the fetch resolves either way.
   - "Sample pick · Demo data" shows only if that request fails (renamed
     from "Sample slate · demo data" — `tests/test_web_polish.py` pins the
     old string and `data-hook="sample-slate-badge"`; both need a matching
     test update, listed in the landing group's `tests_to_update`).
4. No Bet Check buttons anywhere in the header or hero (the footer's Bet
   Check link is the one place it stays, per D7). One trust block "How the
   record works" using the full record wording from section 5. The line
   "Live game analysis is planned. It is not available yet."
5. Copy fixes from the table in section 5 (landing-04, -05, -07).
6. 15px text floor on phone (landing-09).
7. `Get founding access` in the pricing section is a **secondary** button
   (see section 4's one-primary-per-viewport rule).

**Gameday `#/today`.**
1. Header:
   - Eyebrow "MLB · GAMEDAY".
   - Title "Today's picks".
   - Purpose "Ranked by how strongly the betting market favours each
     pick."
   - Status line with published time and prices-checked time.
2. The experimental notice, then compact cards in payload order (gd-04).
3. Remove the fixed and inline Bet Check band entirely, the "CHECK A BET
   OF YOUR OWN" hero button, and the per-card "CHECK THIS PRICE YOURSELF"
   button (gd-03). Keep "OPEN THE FULL BOARD" as a secondary link.
4. Show the record once, below the picks, using the existing
   `renderCardRecordStrip` call (relocated, not renamed —
   `tests/test_whose_record_is_it.py` requires `today.js` to call
   `renderCardRecordStrip` and forbids it from calling the unrelated
   `renderRecordStrip`, the forward-test systems' strip; the fix for gd-09
   is to stop rendering the *second*, differently-formatted "THE RECORD SO
   FAR" block from `card.js`'s own `recordLine`, not to remove or rename
   the card's own strip), with cohort, period, sample size (n) and the
   preliminary line (gd-09).
5. **A new, small "Next matchup" card replaces the old hero entirely — it
   does not reuse `heroNoPlay`/`heroFlagged`/`heroMarketUnavailable`.**
   Read directly from source, those three builders carry a price-
   comparison panel outside any breakdown (a direct R3 violation), a
   "STILL WORTH YOUR TIME" / "SAVED BETS" combination D7 hides in the
   public demo, an editorializing sentence ("ONE GAME CLEARED IT... one
   finding survived pre-registration"), a designer's own aside meant for
   internal review ("Amber, not red. Absence of a board is not a risk to
   a bet.") printed as if it were customer copy, and a texture/`data-rise`
   entrance effect R_MOTION forbids — none of it fits a 300px column, and
   reusing it was the first draft's mistake. Build `nextMatchupCard`
   instead: matchup, local first pitch time, both starters with a
   confirmed/probable word chip sourced from `knowledge.core.starters`, a
   lineup-state chip, "Our picks in this game: N" linking up to the cards
   above, and "Open this matchup". A 300px right column on desktop, after
   the picks on phone. The three old hero builders are removed from
   Gameday's render path (`tests/test_today_one_answer.py` and
   `tests/test_web_v2_gameday.py` pin their classes and need updating to
   match — listed in gameday-page's `tests_to_update`).
6. Matchup grid shows matchup, time, starters, "Market says" and a link
   (gd-06, gd-07, gd-10).
   - No paper positions, no CONTROL/MARKET_REFERENCE/FORWARD_TEST chips.
   - Its own empty sentence ("No games on this slate.") — never a bare
     "—" (gd-07's second defect: the grid's fetch can resolve to neither
     game cards nor its own coded empty text under real conditions; fix
     the render path, not just the copy).
7. When the slate date differs from the viewer's date it reads "Tue Sep 15
   slate · slates turn over at midnight Eastern" (gd-11).
8. 15px text floor on the cards (gd-08).
9. Investigate the `today_desktop.png` stuck-on-skeleton capture (gd-07's
   first defect) directly — `api.js` already aborts every request at 20
   seconds, so a stuck skeleton beyond that is not a hung fetch; it is more
   likely a throw after a successful fetch, or a race between an in-flight
   render and the capture. Wrap `renderToday` in try/catch that falls
   through to the shared error state, and make any loading timeout
   discard a stale render (a render token) rather than paint over a
   newer one.

**Matchups list `#/games`.**
- Header "MLB · MATCHUPS", "Every game on the slate", with board age as
  the status.
- Legend and labels at 15px on phone (games-sub-15px-text).
- **Tile layout, order and grade flags are unchanged (R6).** A treatment-
  only pass — flat panel, upright type, role tokens, no sheen sweep, no
  animation — replaces the loud per-team gradient tiles with the same
  content in the same order, closing games-grid-visual-system-mismatch
  without touching what the tiles say or how they're sorted. Acceptance:
  tile count and DOM order match a saved snapshot of the pre-change
  `/games/{date}` order (a full-page capture of the pre-change state was
  not available for this comparison — `games_mobile.png` shows only the
  loading skeleton — so save the live DOM order once, at build time,
  rather than comparing against a screenshot that does not show it).

**Matchup detail `#/game/...`.**
- Header "MLB · MATCHUP", title "{Away} at {Home}", status "Prices
  captured ...".
- The experimental notice above "Tonight's pick", in **both** branches
  whenever a pick is shown (game-detail-no-experimental-notice).
- "Check a bet on this game" stays, as a secondary button.
- Game Story text at 15px on phone (game-detail-sub-15px-gamestory-text).
- Tap-to-see definitions for FIP and WHIP only — ERA, K/9 and IP are
  common enough to skip (game-detail-jargon-stat-labels).
- Re-capture the desktop view after confirming it is not the same
  stuck-loading pattern as gd-07 (game-detail-desktop-stuck-loading). The
  broader visual pass to Direction A's board look is deferred, same as the
  Matchups list (game-detail-visual-system-mismatch) — R6 protects this
  page's layout and calculations for this build.

**Player props `#/props`.**
- Header "MLB · PROPS", title "Player props", purpose "Every priced player
  prop on the slate.", status with the price capture time — **not** built
  from `formatEasternTime`/`formatEasternClock` if the resulting string
  ever contains the word "clock" or "block" anywhere, including in a
  comment in the same file: `tests/test_web_props.py` reads the whole raw
  text of `props.js` (`self.text = _read(PROPS_JS)`) and asserts the
  lowercased text contains **no occurrence of the substring "lock"
  anywhere** (`test_no_row_is_labelled_a_pick`, guarding against "top play"
  / "best bet" / "lock" / "our pick" / "recommended" reading as a
  recommendation). "clock" and "block" both contain "lock" as a substring
  and will trip this check even inside a code comment. Use a helper or
  variable name that avoids the letters "lock" entirely in `props.js`
  (e.g. call the formatter result `capturedTime`, and do not write the
  word "clock" in any comment in that file).
- Counts and the lineup note move to the top (props-2, props-3).
- A market filter (All · Hits · Total bases · Home runs) and a "Show 25
  more" button. The server's order is never re-sorted (`.sort(` must not
  appear in `props.js` — an existing, still-binding test).
- 15px text floor (props-4).
- Keep the literal "lineup not posted yet" string somewhere in rendered
  text — an existing pinned test.

**Odds board and one game `#/odds...`.**
- Header "MLB · ODDS", "Prices across the books", status "Captured 9:08 PM
  PDT · 68 min ago" (odds-3, oddsgame-3, oddsgame-5).
- **A relative "Older quote" chip, not a fixed-clock STALE flag:** amber,
  shown only for a book whose `observed_utc` is at least 3600 seconds
  older than the newest `observed_utc` **for that same game** — never
  flagging every row on the newest capture, which is what the current
  fixed `STALE_AFTER_SECONDS` threshold does against an hourly-ish batch
  capture (odds-2, oddsgame-2: confirmed on every book of every game in
  the audited captures).
- BEST panels become neutral (never a red fill for "the better price" —
  red is reserved for the top-right coming-soon labels and the one
  primary action per screen).
- Games collapse to summary rows, with a jump list at the top (odds-4).
- Real headings: one h2 for the board, one h3 per game (odds-5).

**The record `#/record-card`.**
- Header "MLB · RESULTS", "Every card pick, graded", status "Last graded
  [date]".
- Cohort and preliminary line beside the headline figures (REC-3).
- Intro and ledger wording from section 5 (REC-4, nfl-record-1). Stop
  rendering the server-supplied `record.disclaimer` field verbatim once
  `copy-truth-sweep` has corrected `CARD_DISCLAIMER` upstream — this page
  depends on that group landing first.
- Day tables stack on phone (REC-5).
- "Loss" is neutral, not red (its colour today comes from `card2lede*`/
  `crp-*` rules in `card.css`, which the gameday-card group owns; results
  depends on gameday-card for this).

**One day `#/day/...`.**
- Header "RESEARCH · ONE DAY".
- Badge and loading copy fixed (DAY-2): "PREGAME RECORD", loading text
  "Loading this day's record…". The purpose sentence itself is server-
  supplied (`payload.basis`, from `daily_record.BASIS`) — fixed by
  `copy-truth-sweep`, which this page depends on.
- Units show "—" until something settles, the same guard `cardrecord.js`'s
  `headline()` already applies, extended to `dayrecap.js`'s
  `dayRollupSummary()` (DAY-3) — a real "0-0-0 · 0.00u" for a day with 186
  pending recommendations reads identically to a day that broke even, and
  that is worse than showing nothing.
- Each row names its system in words, through `humanizeKey(system_id)`
  (DAY-1) — this exact call shape is separately pinned by
  `tests/test_web_register_sweep.py`.
- Grouping/pagination of the 1,286-row list is deferred (R6) — this build
  only makes each row distinguishable, not shorter.
- Check the tab bar position on a live, scrolled page rather than trusting
  the full-page capture tool, which is known to mis-place `position:fixed`
  elements mid-document in a few other captures this audit flagged the
  same way (DAY-5).

**Research `#/performance`.**
- Header "RESEARCH", "Research systems, kept apart from the card".
- Replace the single awaited `Promise.all` with `Promise.allSettled`
  inside `withLoadingTimeout`, rendering every section whose data loaded
  and a named not-available panel for any that did not — the current
  all-or-nothing await is why `performance_desktop.png` and
  `performance_mobile.png` show nothing but a stuck shimmer today
  (PERF-1).

**Bet Check `#/betcheck`.**
- Header "MLB · BET CHECK", "Check a moneyline: the case for it, the case
  against it, and the prices." (betcheck-6).
- The date defaults to the current **slate** date, imported as
  `currentEasternDateIso` from `today.js` (gameday-page owns that export),
  not a fresh `new Date().toISOString().slice(0,10)` UTC-day computation —
  the latter is why the field silently defaults to tomorrow's date after
  roughly 5 PM Pacific (betcheck-4, confirmed: at 10:14 PM PDT the UTC
  calendar day is already the next day). Label the field "Slate date" with
  "Slates turn over at midnight Eastern."
- 15px text floor (betcheck-7).

**My Bets `#/mybets`.**
- Header "MLB · BETS", "Bets you saved, and how they settled." (mybets-5).
- Shared `.field`/`.form` and `.dtable` stacked table (mybets-1, mybets-7).
- Capture this page while signed in before calling it done — every
  capture in the original audit was signed out and showed only the shared
  gate, never the real form or table.

**Sign in, Sign up, Sign up complete, Billing, Support.**
- Shared header over one panel (signin-header-pattern, billing-header-
  pattern).
- Signup:
  - New benefit bullet, from section 5's table.
  - Headline "Daily MLB picks, published before each game." (signup-
    frozen-overclaim, signup-headline-drift).
- Sign up complete: the no-token branch adds a secondary "Go to sign up"
  and a text link "Contact support" (signup-complete-dead-end) — today it
  is the one error state in the app with no next action at all.
- Support is rebuilt from shared `.panel`/`.field`/`.btn` parts — today it
  is the single screen in the whole app with **zero** CSS backing
  (support-unstyled, support-mobile-text-and-targets: confirmed no
  stylesheet anywhere targets any of `support.js`'s class names).
- Capture the signed-in success states before calling Billing or Sign up
  complete done (billing-states-uncaptured, signup-complete-states-
  uncaptured) — both were only ever captured signed out.
- Re-check the tab bar over the signup form on a real, scrolled device
  rather than trusting the full-page capture tool (signup-mobile-tabbar-
  overlap) — `app.css` already reserves bottom padding sized to clear the
  tab bar, so this may already be a capture artifact, not a live bug.

**NFL and Tennis.**
- The coming-soon page on all five routes (nfl-today-1 to -5, nfl-record-1
  to -5, tennis-board-1 to -5).
- The MLB menu stays visible, with nothing in it selected.
- The NFL card and tennis board code (`web/js/tennis.js`,
  `card.js`'s NFL branches, `cardrecord.js`'s NFL branch) stay on disk,
  unmodified and unrouted — `tests/test_web_tennis_board.py` reads only
  `tennis.js` directly and keeps passing untouched.

**Live `#/live` (internal).**
- Linked from nowhere in any public chrome.
- Header "INTERNAL · LIVE", status "Internal testing. No alerts are
  sent." — replaces `setShellStatus('Ready.')`, which today reads as a
  live, operating feature (live-5).
- One empty-state sentence, not two stacked idioms saying the same thing
  (live-2 to live-5): when no games are live, render the shared empty
  state once and do not also print the poller's own idle sentence
  underneath it.

## 7. Phone rules (under 900px; checked at 390x844 and 360x780)

- No text under 15px. Inputs are 16px.
- Interactive targets are 44x44px or larger.
- A 16px side gutter everywhere, including forms and states.
- One column. Tables with more than three columns stack.
- **Hidden on phone:** the clock, the rail, context columns (their content
  follows the main column), and the MLB tab under 400px.
- **Never hidden:** section meta, sample sizes, conditions, the
  experimental notice.
- Only the tab bar is fixed. Content ends above it.
- No horizontal page scroll at 320px.

## 8. Accessibility and motion

- **Contrast:** text 4.5:1; large text, borders and the focus ring 3:1.
- **Focus:** `:focus-visible` draws a 3px `--fresh` outline with a 2px
  offset.
- **Landmarks:** a "Skip to content" link first, then `header`,
  `nav aria-label="Sports"`, `nav aria-label="MLB sections"`, `main` and
  `footer`. One h1 per page; sections use h2.
- **Current page:** `aria-current="page"` on the selected sport and sub
  menu item.
- **Disclosures:** use `aria-expanded` or native `details`.
- **Status:** every status, win and loss is a word.
- **Tables:** a caption and `th scope`. Stacked rows keep their labels.
- **Idle motion — an explicit removal list, not a general instruction
  (R_MOTION).** The first draft banned "breathing dots, seams, sheens,
  carets, auto-rotation, hover lifts or entrance animations" as a
  principle but assigned no task to actually delete the CSS, and one was
  needed: seven `infinite` keyframe animations exist today in
  `screens.css` alone (a seam sweep, a sheen sweep, three separate
  `gbreathe` uses, a skeleton pulse and a spinner), plus further
  `gbreathe`/`gseam`/`gsheen` uses in `base.css` and `landing.css`. Every
  one is deleted or replaced with a static final state; `motion.js` keeps
  every export (`armParallax`, `armCharts`, `beat` and the rest, since
  `landing.js` still calls them) but arms nothing — elements render
  directly in their final visible state. `prefers-reduced-motion: reduce`
  removes every remaining transition regardless.
- **State-change motion only:** 150ms or less, colour or opacity — the
  news banner's item swap and a disclosure's open/close are the only
  motion anywhere in the app, and both are visitor-triggered, not idle.
- **Zoom:** content survives 200% zoom.

---

## Server-side strings that must change (so no group leaves them)

These live in Python, not `web/`, and are served into the client verbatim
— fixing only the client copy leaves the server's own words on screen
wherever a page renders a server-supplied field instead of hardcoding its
own text. All four are owned by the **copy-truth-sweep** group; every
group listed as a "consumer" below either depends on copy-truth-sweep or
stops rendering the raw server field in favour of client-owned copy (noted
per row).

| File | Constant / function | Current text (verified in source) | Replacement | Consumers |
|---|---|---|---|---|
| `src/analysis/daily_card.py` | `CARD_BASIS` (line 149) | "The side is whichever the multi-book market makes more likely. Our own run model has to agree, or the pick is labelled SPLIT. The bet is the moneyline unless the run line prices the same opinion better. Ranked by how confident the market is." | "The side is whichever the multi-book market makes more likely. Our own run model has to agree, or the pick does not qualify. The bet is the moneyline unless the run line prices the same opinion better. Ranked by how strongly the market favours each pick." | `api/card.py` (`/card`, `/card/record` for MLB), rendered by `card.js`'s `standingNote` (as `payload.basis`) and `cardrecord.js` |
| `src/analysis/daily_card.py` | `CARD_DISCLAIMER` (line 155) | "These are reads, not guarantees, and they are not claims of positive expected value. Backing the more likely side wins most individual bets and still loses money at the vig. Every pick here is published before first pitch, frozen, and graded win or lose." | "These are reads, not guarantees, and they are not claims of positive expected value. No pick here has shown a positive estimated return under our market benchmark. Every pick here is published before first pitch and graded win or lose." | same as above |
| `src/analysis/grade.py` | `legend()`, third line (line 208) | "A+ means the price is on your side by our own number. That number has been measured unreliable when it disagrees with the market, so treat the plus as a note, not a reason." | "A+ means our number is above what the price needs. That number has not been checked against enough results yet, so read the plus as a note, not a reason." | Served as `knowledge_legend` on every `/card` response; rendered by `card.js` (`data-hook="card-grade-legend"`) and `games.js`'s grade legend |
| `src/report/daily_record.py` | `LABEL` (line 89) | "FROZEN PREGAME RECORD" | "PREGAME RECORD" | `/daily/{date}`, rendered as the badge on `dayrecap.js`'s day page |
| `src/report/daily_record.py` | `BASIS` (line 91) | "Every recommendation below is the row the engine froze before first pitch; prices and confidence are as of that instant, never restated." | "Every recommendation below is the row the engine recorded before first pitch; prices and confidence are as of that instant, never restated." | same as above, rendered as the day page's purpose line |

All four edits are string-only — no change to `CARD_RULE`, selection
logic, field names, or any other constant in these files. Each is a
top-level Python string literal inside `src/analysis/` or `src/report/`,
so `tests/test_customer_language.py`'s AST scan covers it directly (it
already would have caught "labelled SPLIT" and "frozen" as violations if
either word were separately banned outright — they are not currently
hard-banned strings, which is exactly why this table exists as a manual
sweep rather than something the existing language tripwire already
catches).

`card.js` also independently replaces its own hardcoded "The record's
tamper-proof chain does not currently verify" string (line 675) with
"The record's hash chain does not currently verify, so treat the numbers
above as unconfirmed until it does." — this one is a client-owned literal,
not server-sourced, and does not depend on copy-truth-sweep.

---

## Corrections applied

Every point raised by the two independent adversarial reviews
(`scratchpad/audit_results/11`, `/12`) was checked against `tests/`,
`src/`, and `web/` directly before being adopted or rejected. "Adopted"
means the correction above reflects it; "Rejected" states why, with the
verification performed.

**Adopted — test breaks / banned-word failures (would go red by construction):**
- The amendment's suggested preliminary line ("too few picks...") fails
  `NoBannedCustomerVocabulary`'s `NEGATION_ONLY` check on "edge" — verified
  the exact `NEGATORS` list in `tests/test_customer_language.py` and
  confirmed "too few" is not one of them. Fixed to "not enough picks yet".
- `tests/test_funnel_attribution.py` asserts `"#/betcheck"` appears
  literally in `landing.html` — verified at line 170. Since the redesign
  removes every Bet Check CTA from the header/hero and only the footer
  (rendered by JS) keeps the link, this test needs updating; assigned to
  landing's owned tests.
- `tests/test_whose_record_is_it.py` requires `today.js` to keep calling
  `renderCardRecordStrip` and forbids `renderRecordStrip` — verified the
  test file directly. The fix is to keep the existing card-record-strip
  call and remove only the *duplicate* record block, not to rename or
  remove the strip itself.
- `tests/test_request_timeout.py` pins "We could not reach the board.",
  "it is not the same as" and "Technical detail" in `dom.js` — verified at
  lines 141-149. The network-vs-server-error distinction in section 4's
  error state preserves these.
- `tests/test_web_hero_market_gap.py` pins exact line numbers 720 and 740
  in `today.js` via a coverage-style check — verified at lines 217-218.
  Any edit that shifts lines above them (removing the Bet Check button,
  adding an import) breaks this by construction; the fix removes the
  line-number assertion in favour of the file's own existing content
  check, listed in gameday-page's `tests_to_update`.
- `tests/test_installable.py` pins `safe-area-inset-bottom` inside
  `.tabbar {}` in `nav.css`, with the padding shorthand required to
  precede `padding-bottom`, plus the same string in `app.css` — verified
  at lines 123-142. Assigned to chrome's owned tests.
- `tests/test_web_props.py` bans the raw substring "lock" anywhere in
  `props.js`'s full text (comments included) — verified at lines 104-114.
  "clock" and "block" both trip it. Documented as an explicit naming
  constraint in the Player props section above.

**Adopted — hidden dependencies:**
- `renderSportLevel` needs a `linkPrefix` parameter for `landing.js` to
  build working links, and must run per-route (not once in `boot()`) for
  `aria-current` to track the active route — both confirmed by reading
  `main.js`'s current `_renderRouteInner` structure directly; the first
  draft's "mount... once" would have frozen the selected state.
- `pageHeader()` must return a separate `body` node from the header, since
  `renderError` and friends clear their entire container — verified five
  call sites (`performance.js:638`, `cardrecord.js:596`, `dayrecap.js:553`,
  `live.js:265`, `signup.js:192`) that pass the whole content area, which
  would otherwise wipe the "always on screen" header the spec itself
  requires.
- `dayrecap.js` imports `CLASS_MEANING` from `matchups.js` directly
  (verified in `dayrecap.js`'s own import list) — added `gameday-page`
  (which owns `matchups.js`) to the `results` group's dependencies.
- `compactPickCard` is built once in `card.js` and imported by
  `landing.js`, rather than reimplemented — avoids the two-copies drift
  the first draft's separate landing/gameday card builders would have
  produced.
- The `locked` field is only stamped during a publish run
  (`card_ledger._lock_and_merge`) — verified in `card_ledger.py`. A flat
  "Provisional until X → Locked" toggle keyed only on the clock would
  invent a status between the cutoff and the next publish; added the
  neutral "Lock pending" state as a third, honestly-labelled gap.
- `pick.why` is an array whose first element is a plain stat sentence, not
  guaranteed to be a single grammatical sentence — verified against the
  audit's own captured card text. Render `why[0]` whole, not client-split.

**Adopted — size and CSS ownership:**
- Split `shell-and-shared` into **foundation** (tokens/base/components/
  layout/states/dom/motion/shell — buildable in one sitting) and
  **chrome** (index.html/main.js/sport.js/meta.js/news.js/comingsoon.js/
  nav.css/app.css) — the first draft's single group touched 17 source
  files including a 3,627-line CSS pass across 8 tests, too large for one
  session as the task instructions require. Verified `screens.css`'s real
  line count and section structure directly.
- Split `gameday` into **gameday-card** (`card.js`, `recordstrip.js`,
  `card.css`) and **gameday-page** (`today.js`, `matchups.js`,
  `screens.css`) for the same reason — verified `today.js` (1,186 lines)
  and `card.js` (1,043 lines) directly.
- **Rejected the proposal to physically split `screens.css` into eight
  per-page files by section banner.** Verified the file directly: its own
  comments document *cross-section* media-query parsing dependencies
  (e.g. the note at line ~2136 that GAME QUICK V2/GAME ADVANCED V2/
  GAMEDAY V2/ODDS V2 all depend on a preceding block being present, or
  they parse inside the wrong media query). A mechanical split risks
  silently breaking that cascade. Instead, `screens.css` is owned entirely
  by **gameday-page** and `card.css` entirely by **gameday-card**; groups
  that need a specific section fixed (`tools` needs the Bet Check
  sections, `matchups` needs Game View, `props-odds` needs Odds V2,
  `results` needs `card.css`'s `crp-*` rules) depend on the owning group
  instead of editing the file themselves. This achieves the same
  coordination goal the split proposed, without the refactor risk.

**Adopted — copy-truth-sweep scope, expanded:**
- `CARD_BASIS` and `CARD_DISCLAIMER` in `src/analysis/daily_card.py`
  (lines 149-160) still say "labelled SPLIT" and "still loses money at the
  vig... frozen" — verified directly in source, and verified they are
  served into `/card` and `/card/record` by `api/card.py`, and rendered
  verbatim by `card.js`'s `standingNote` and `cardrecord.js`. Neither file
  was in the original draft's `copy-truth-sweep` scope, which only touched
  `grade.py` and `daily_record.py`. Added both constants to the table
  above.

**Adopted — uncovered rules given an explicit owner:**
- **Idle motion (R_MOTION)** — the first draft stated the ban as a
  principle with no task deleting any CSS. Verified seven `infinite`
  animations directly in `screens.css` plus further uses in `base.css`
  and `landing.css`, and gave foundation (base.css, components.css) and
  gameday-page/gameday-card (screens.css, card.css, landing.css within
  their respective owned files) explicit removal tasks.
- **R3** (the market/our-number/break-even comparison stays inside "View
  breakdown", never on the visible card) — the first draft's reused hero
  builders (`heroNoPlay` etc.) render a price-comparison panel directly on
  the card face, outside any breakdown, which is a direct R3 violation
  hiding inside a task described as "re-render the existing hero
  builders". Replaced with a new, minimal `nextMatchupCard` (section 6).

**Adopted — smaller fixes, each verified against source or a test file:**
- Real capture cadence (13/60 minutes, not "hourly") for the stale
  threshold — verified `.github/workflows/forward-capture.yml` and
  `scripts/capture_slot.sh` directly.
- `.tabbar` five-tab width at 360px — measured against the condensed font
  metrics; added an explicit acceptance check where none existed.
- The MLB tab hides under 400px, not 375px — measured slack at 375-399px
  is 4px, not enough for real font/padding variance.
- The news banner's text and controls split onto two rows — measured the
  longest item at 636px, wider than "one line" or "two lines with an
  inline tag" can support at the stated widths.
- `renderError`/`clear` container-wiping behaviour and the resulting need
  for `pageHeader()`'s split `body` node (covered above under hidden
  dependencies).
- BETS visibility gated on signed-in-and-not-public-demo, not public-demo
  alone (D7 specifically restricts BETS to signed-in users).
- `"Get founding access"` demoted to secondary on landing, since Direction
  A's "one primary action per screen" rule is violated by a hero primary
  plus a second primary in the pricing section.
- Landing's nav gains Props (D7's menu has four items; the first draft's
  landing nav only listed three).
- `test_shared_footer.py`'s case-sensitive "PLAY RESPONSIBLY" pin — kept
  the uppercase source string rather than changing the test.
- Coming-soon copy: dropped "with a page for every matchup" (promises an
  unbuilt feature) and "there are no tennis picks" (redundant, and worth
  re-verifying against a fresh capture rather than hardening a specific
  claim about the tennis board's current empty-state text).

**Rejected, with reason:**
- **"Shell's `.glyph` rules deletion breaks betcheck.js, which uses
  `.glyph`."** Checked directly: `betcheck.js`'s only occurrence of the
  word "glyph" (line 536) is inside a code comment ("empty glyph on every
  check"), not a class reference. `.glyph` is used as an actual CSS class
  only in `nav.css` and `main.js`'s `navItem()`, both owned by chrome.
  Deleting `.glyph` from `nav.css` does not affect Bet Check. No task
  changed.
- **"Physically split `screens.css` into per-section files."** Rejected
  for the cross-section dependency risk described above under "Adopted —
  size and CSS ownership"; single ownership with explicit cross-group
  dependencies achieves the same coordination without the refactor risk.
- **The 47-file "reads web/" count versus the literal `grep -l "web/"
  tests/*.py` command in the task brief (39 files).** Ran the exact
  command specified: it returns 39. A broader pattern
  (`web/|WEB_DIR|"web"|'web'`) returns 47, catching eight real test files
  that reference web/ paths through a `WEB_DIR`/`JS_DIR` constant rather
  than the literal substring `"web/"` (including `test_whose_record_is_it.py`
  and `test_record_cohort_consistency.py`, both of which genuinely read
  `web/js/*.js` files and needed ownership). Used the union of both
  (47 files) for `tests_owned` assignment in the build plan, since the
  narrower literal command undercounts real structural dependencies on
  `web/` — not a rejection of the substance, just a correction to which
  grep pattern actually finds every file that matters.
- **Four files matched by the broader pattern turned out to be false
  positives on inspection** (`test_api_funnel.py`, `test_checkout_delivery.py`,
  `test_market_from_the_board.py`, `test_ranker.py`): each mentions the
  string "web/" only inside a docstring or comment, and none opens or
  parses any file under `web/`. Excluded from `tests_owned` assignment;
  noted here so the count is explained rather than silently short.
