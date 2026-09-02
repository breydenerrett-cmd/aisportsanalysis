# LINEHOUND V2 — Implementation Plan

Companion to `IMPLEMENTATION_MANIFEST.json` (the machine-readable
per-artboard manifest — read that first for field bindings). This file is
the human-readable build order, ownership split, and acceptance protocol
for the parallel Sonnet workers implementing V2 screen-by-screen.

## Decisions already made (orchestrator, not re-litigated here)

- V2 replaces V1 **in place**, screen by screen, canvas-first. No feature
  flag — git history is the rollback.
- V2's `--v-*` tokens are **added** to `web/css/tokens.css` alongside the
  existing V1 tokens. V1 tokens are removed only when the last V1 screen
  using them is gone — see "Token bridge" below.

## Artboard count: 38, not 35

`IMPLEMENTATION_MANIFEST.json`'s `artboard_count_resolution` has the full
account. Short version: 35 numbered slots (V2-01…V2-35), but slot V2-01
(Gameday) alone expands into 4 physical canvas frames — the carousel
artboard plus three dedicated verdict-state artboards (V2-01a NO_PLAY,
V2-01b FLAGGED, V2-01c MARKET_UNAVAILABLE). 35 + 3 = 38, matching the
canvas's own footer ("38 ARTBOARDS · 10 FAMILIES · 2 VIEWPORTS",
`LINEHOUND V2 Full Product.dc.html:7896`). See
`RECONCILIATION_REQUIRED.md`'s added closing line for the one-line record.

## Build order and file ownership groups

Ownership is disjoint by **JS module + CSS section name** so 3–4 workers
can run concurrently without touching each other's files. `screens.css`
is a shared file — each worker adds ONE new, clearly-bannered section
(matching the existing `/* ===== NAME ===== */` convention already in the
file) and never edits another group's section. Same rule for
`tokens.css`: add `--v-*` custom properties, never edit a `--v1-*` (or
unprefixed V1) one.

### Wave 0 — must land before any Featured Bet placement (blocking)

**Group F — Featured Bet primitive.** Owns: a new shared component,
`web/js/featuredbet.js` (or a function exported from an existing shared
module — worker's call, but it must be ONE definition, not copy-pasted
into today.js/betcheck.js/games.js), plus
`screens.css:FEATURED BET — primitive`. Builds the Tier A segmented
"bet standing" card (price standing rank, beats-consensus, improvement,
board depth, thesis/counterargument count) exactly as specified in
V2-32's body. Ships with its three consuming artboards' placements
stubbed as TODOs for the owning screen workers to wire in Wave 1
(V2-32 Bet Check block 01, V2-33 Gameday carousel head, V2-34 Game
spotlight) — this group does NOT edit today.js/betcheck.js/games.js
itself, it only publishes the component and its call signature.

This wave also includes **Group S — Shared states.** Owns:
`web/js/dom.js` (or a new `web/js/states.js`) additions for the shared
loading/empty/unavailable/error primitives (V2-27–30), plus
`screens.css:SHARED STATES`. Every other group's screens call into this
rather than inventing their own skeleton/empty/error markup — land it
first so Wave 1 groups can use it.

### Wave 1 — parallel, disjoint files (3–4 workers)

| Group | Owns (JS) | Owns (CSS section) | Artboards | Depends on |
|---|---|---|---|---|
| **Odds** | `web/js/odds.js` | `screens.css:ODDS V2` | V2-02, V2-23 | Group S | 
| **Gameday** | `web/js/today.js` | `screens.css:GAMEDAY V2` | V2-01, 01a, 01b, 01c, 22, 33 | Group F (for V2-33 only), Group S |
| **Game** | `web/js/games.js` | `screens.css:GAME QUICK V2`, `screens.css:GAME ADVANCED V2` | V2-03, 13, 14, 15, 31, 34 | Group F (for V2-34 only), Group S |
| **Bet Check** | `web/js/betcheck.js` | `screens.css:BET CHECK V2` | V2-04, 24, 25, 26, 32 | Group F (for V2-32), Group S |

**Odds is already assigned to a worker today** — do not re-assign it.
The other three (Gameday, Game, Bet Check) are the recommended next wave;
each references the Featured Bet primitive from Wave 0 but otherwise
touches no file another Wave-1 group touches.

### Wave 2 — parallel, lower-traffic surfaces (2–3 workers)

| Group | Owns (JS) | Owns (CSS section) | Artboards |
|---|---|---|---|
| **My Bets** | `web/js/mybets.js` | `screens.css:MY BETS V2` | V2-16, 17, 18 |
| **Signup & Billing** | `web/js/signup.js`, `web/js/billing.js` | `screens.css:SIGNUP V2` | V2-05, 09, 10, 11, 12, 21 (the 402 branch touches billing.js — coordinate with Access if run concurrently) |
| **Access / Sign-in** | `web/js/signin.js` | `screens.css:ACCESS V2`, `screens.css:SIGN IN V2` | V2-06, 19, 20 (V2-21 shared with Signup & Billing above — see note) |
| **Landing** | `web/js/landing.js`, `web/js/pricing.js` | `web/css/landing.css` | V2-07, 08 |

Note on V2-21 (`ACCESS PAUSED · 402`): it touches `billing.js` (the
reactivate call) and is conceptually part of both Signup/Billing and
Access. Assign it to ONE of those two groups explicitly before Wave 2
starts — do not let both workers touch `billing.js` in the same wave.

### Do not build yet (Tier B, contract-gated)

**V2-35 (`RANKED BOARD · TIER B`)** is validation-dependent: the Ranker
publishes no recommendations while Engine 2 is `None`
(`src/report/ranker.py`), enforced structurally by `tests/test_ranker.py`.
Nothing in this wave plan assigns a worker to build `web/js/ranked.js`
against live data — there is no field to bind to, and the design's own
copy says so ("NOT YET EARNED", "blocked on validation"). If a worker is
asked to scaffold the nav entry for it, it must render disabled/hidden,
never a computed rating, probability, gap, or rank. See
`IMPLEMENTATION_MANIFEST.json`'s V2-35 entry for the full warning before
anyone touches this artboard.

## Token bridge

`web/css/tokens.css` currently holds only V1 tokens (transcribed from
`design/linehound-v1/LINEHOUND Design System Handoff.dc.html`). Each V2
group adds its own `--v-*` custom properties (color, type ramp, spacing,
motion durations from the V2 canvas's `DESIGN TOKENS` / `TYPE ROLES` /
`SPACING, GRID AND GEOMETRY` sections, lines 167–900-ish) alongside, never
replacing, the existing `--*` V1 tokens a still-live V1 screen depends on.
A V1 token is deleted only in the same commit that removes the last V2
screen still reading it — track this per-token, not per-file, since
`tokens.css` is shared for the whole migration window. `web/README.md`'s
CSS file table should get one line added noting the coexistence once the
first V2 section lands (not this task — flag it to whichever group lands
first).

## Visual-acceptance protocol (per `docs/VISUAL_ACCEPTANCE_TRACK1.md`)

Same hard gate Track 1 used, extended to V2. A screen is complete only
when its row is **VISUAL PASS**, graded by the orchestrator — engineering
tests passing is necessary but not sufficient.

1. Implementer takes a full-page screenshot of the real running screen at
   each viewport the artboard specifies (1280 desktop canvas width /
   390×844 mobile device frame — see `IMPLEMENTATION_MANIFEST.json`'s
   `viewport_legend`).
2. Orchestrator places it side-by-side against the frozen artboard
   (`LINEHOUND V2 Full Product.dc.html`, the exact `dc_html_line_start`–
   `dc_html_line_end` range from the manifest).
3. Grade across the same 11 dimensions Track 1 used: composition ·
   hierarchy · component anatomy · typography · team/color · spacing ·
   density · states · motion · responsive · customer-ready controls/copy.
4. Orchestrator records an explicit **VISUAL PASS** or **VISUAL FAIL**
   per screen × viewport row (not per artboard id — a family like Gameday
   gets one row per viewport, covering all its verdict-state variants).
   A FAIL names which dimension(s) failed, same format as
   `docs/VISUAL_ACCEPTANCE_TRACK1.md`'s grading matrix table.
5. Re-verify PASS rows on the real deployed staging product in a browser
   before calling the screen done — a local dev-server screenshot is not
   sufficient on its own, matching Track 1's practice.
6. No screen is marked complete in this plan or in any status doc without
   a recorded VISUAL PASS row. Passing `tests/test_web_structure.py` or
   any other engineering test is necessary but never sufficient.

## V1 → V2 replacement rule

- Replace **in place**: the V2 screen's composition replaces the V1
  markup in the same JS module (`today.js` keeps being Gameday's owner,
  its render function's internals change). Do not create parallel
  `todayV2.js`-style files — there is no feature flag to switch between
  them.
- A screen is only replaced once it has a recorded VISUAL PASS (see
  above). Until then, the V1 composition keeps serving traffic —
  `web/README.md` already documents this exact pattern for Odds and My
  Bets today ("keep serving their current structural views ... until
  Claude Design ships those screens").
- Once ALL V1 screens sharing a given `tokens.css` V1 token group are
  replaced, delete that V1 token group in the same commit that removes
  the last reference to it (see "Token bridge" above) — do not leave dead
  tokens indefinitely.
- `artifacts/demo_latest.html` is untouched by any of this — it is not a
  V1 or V2 screen, it is a standing demo artifact outside this migration.
