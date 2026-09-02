# Track 1 visual acceptance — matrix and procedure

2026-09-01. Visual acceptance is a HARD GATE separate from engineering
tests (Brey directive). A screen is complete only when its row below is
VISUAL PASS, graded by the orchestrator from a side-by-side of the real
implementation screenshot against the frozen artboard, then re-verified
on the REAL deployed staging product in a browser.

## Artboard references (source of truth)

All in `design/linehound-v1/LINEHOUND Gameday.dc.html` (rendered in
Chromium; full-canvas reference capture:
scratchpad/qa/canvas_gameday_full.png, 1600x14847):

| Screen | Artboard (top-to-bottom position in the canvas render) |
|---|---|
| Gameday desktop | 1st artboard: team-seam hero (PIRATES/BREWERS), price bug ("BEST OF 11 BOOKS", -110 vs struck -118, 1.5 PTS BETTER, move+time), OPEN/COMPARE CTAs, motion-spec panels beneath |
| Gameday 390 mobile | mobile card artboard after the hero sections |
| Bet Check desktop | seam input panel + ten-block skeleton artboard |
| Bet Check mobile | following mobile artboard |
| Game Quick View | team-color header artboard |
| Game Advanced View | appended-sections artboard |
| Game mobile | final mobile artboard |
| App chrome | visible in every artboard: 48px top strip (monogram, LINEHOUND + section label, status chips, ET clock), 76px labeled rail TODAY/GAMES/CHECK/ODDS/BETS |

Binding written rules: type ramp (hero price clamp(94px,11.4vw,166px),
ls -.025em, lh .76); reserved hot red (better price / primary conversion
only, one money pill per region); six-word label ceiling; per-screen
empty/error/loading states; never a row of zeros; motion specs embedded
per artboard with prefers-reduced-motion full disable.

## Grading matrix (one row per screen x viewport; all 11 dimensions)

Dimensions: composition · hierarchy · component anatomy · typography ·
team/color · spacing · density · states · motion · responsive ·
customer-ready controls/copy.

| Screen | Viewport | Impl shot | Ref shot | Dims failing | VERDICT |
|---|---|---|---|---|---|
| App chrome | 1440 | (all impl shots) | canvas artboards | none | **VISUAL PASS** |
| Gameday | 1440 | gameday_desktop_impl | gameday_desktop_ref | none | **VISUAL PASS** |
| Gameday | 390 | gameday_mobile_impl | gameday_mobile_ref | none | **VISUAL PASS** |
| Bet Check | 1440 | betcheck_desktop_impl | betcheck_desktop_ref | none | **VISUAL PASS** |
| Bet Check | 390 | betcheck_mobile_impl | betcheck_mobile_ref | none | **VISUAL PASS** |
| Game Quick | 1440 | game_quick_desktop_impl | game_quick_desktop_ref | none | **VISUAL PASS** |
| Game Advanced | 1440 | game_advanced_desktop_impl | game_advanced_desktop_ref | none | **VISUAL PASS** |
| Game | 390 | game_mobile_impl | game_mobile_ref | none | **VISUAL PASS** |

Graded 2026-09-01 by the orchestrator from side-by-side pairs under
scratchpad/rebuild/ (real 15-game slate, authenticated). Watch items,
none blocking: (1) the game-view price panel keeps the canvas's money
treatment even when no side beats consensus -- canvas-consistent;
flagged to the Design session for an explicit ruling; (2) the Games
slate list has NO artboard and reuses the Gameday tile grid -- an
extension, honest but ungraded as reproduction; (3) fonts self-hosted
(web/css/fonts.css, 525 KB) after CDN flakiness -- size flagged. The
DEMO DATA / SAMPLE SLATE chips are correctly ABSENT (live data). Free
Bet Check wired for anonymous visitors ("N OF 3 FREE CHECKS LEFT",
402 signup wall).

Out of scope (Track 2, BLOCKED until the dedicated Design session
returns approved artboards): Odds, My Bets, Signup, Auth/sign-in visual
design. The interim #/signin is functional-only and is never graded
PASS. Landing: accepted; only navigation/integration fixes allowed.

> **SUPERSEDED (2026-09-02)** — see design/linehound-v2/LINEHOUND_V2_IMPLEMENTATION_HANDOFF.md §5

## Real-staging verification checklist (after visual PASS + deploy)

In a real browser against https://linehound-staging.fly.dev, latest
build confirmed via a served-asset marker (not /health, not /meta
version which reads "dev"):

1. / redirects to the Landing; /app reaches the app shell (once the
   root-redirect lands with the backend worker's commit).
2. Landing renders (control — must be unchanged).
3. App shell: no INVITE TOKEN chrome; rail + top strip per artboards;
   wordmark returns to Landing.
4. #/today signed-out: designed-language sign-in prompt (no raw API
   strings on the primary surface); #/signin holds token entry.
5. Authenticated (Brey or Launch Ops token): Gameday hero + price bug
   from REAL board data; slate; What Changed; Game Quick -> Advanced
   appends; Bet Check end-to-end with the ten-block skeleton.
6. 390px (device emulation): Gameday + Bet Check mobile artboard match;
   tab bar; no horizontal scroll anywhere.
7. Motion present at default settings; fully disabled under
   prefers-reduced-motion.
8. Zero console errors on every screen; every rate shows its sample
   size; missing data shows NOT YET AVAILABLE; disclaimer reachable.
9. Screenshots of each staging screen archived beside the matrix.

Verdicts and evidence get recorded IN THIS FILE as rows fill in; the
frontend lane is not "complete" until every in-scope row is VISUAL PASS
*on staging*.

## Staging verification record (2026-09-01, post-deploy)

Done from the orchestration container: every web/ asset served by
staging byte-diffed IDENTICAL to the VISUAL-PASS build; / -> 307 ->
/web/landing.html live; anonymous POST /betcheck/free returns the real
check on live staging (counterargument present, recommendation null,
token minted, 2 of 3 remaining after one QA spend); /today unauth ->
honest 401. NOT possible from this container: rendering staging in a
browser -- the egress proxy resets Chromium's CONNECT tunnels to
fly.dev (relay log confirms; curl unaffected). Since the served bytes
equal the graded build, rendering is byte-equivalent to the reviewed
screenshots; the final human eyes-on-staging pass in a real Chrome
remains OPEN and is the last box before the lane is called complete.
