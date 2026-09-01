# RECONCILED CAPABILITY CONTRACT — CURRENT HEAD

2026-09-02, by the parent engineering session. Reconciles
`CAPABILITY_LEDGER.md` (audited at `3dca767`) against **current HEAD
`f0bc637`** (which includes the canvas-first frontend rebuild `2947aa8`,
the entitlement/free-check work `4914756`, and the staging verification
`6348590`). Every priority finding is classified STILL TRUE / SUPERSEDED
/ NEVER TRUE with evidence measured live at this HEAD on 2026-09-01/02.

Dimension shorthand where useful: **A** available directly on the
customer API · **B** exists internally, not exposed · **C** safe
deterministic presentation derivation · **D** not available, must not
show as live · **E** demo/sample only, labeled.

---

## PRIORITY ANSWERS

### 1. NO-PLAY / ZERO-FINDINGS — STILL TRUE, and it is the PRIMARY UX STATE

Measured on current code and data:

- **Live slate 2026-09-01, built fresh through `briefing.build_slate` on
  this HEAD: 15 games checked, 15 `verdict: "no_play"`, 0 games with any
  finding.** (100% no_play, 100% findings=[].)
- **Forward ledger, every recommendation entry since forward tracking
  began (`evidence/forward_ledger.jsonl`, n=129): `no_play` 120
  (93.0%), `flagged` 3 (2.3%), `market_unavailable` 6 (4.7%).**

Verdict: **treat no_play + zero findings as the PRIMARY designed state,
not an empty state.** This is the honesty engine working (27
pre-registered hypotheses, zero survivors), not a data outage. Price
context (always real) carries the visual weight; `flagged` is the rare
exception state (~2%), `market_unavailable` the honest-absence state
(~5%).

### 2. DOSSIER / MATCHUP DATA — one gap SUPERSEDED, the rest STILL TRUE

Live-measured at this HEAD, the API path (`api/games.py:163` →
`_build_entries(date)` with **no enrichment kwargs** — unchanged) yields
**5 sections and 11 gaps** per game, not the ledger's 4/12:

- Sections: `park, price_improvement, multibook_board, teams,
  what_changed`.
- Gaps: `arsenals, bullpen, lineups, market, matchup_depth,
  matchup_history, news, splits, starters, travel, weather`.

Per item:

| Item | Verdict | Evidence at current HEAD |
|---|---|---|
| Team records | **SUPERSEDED — A.** The `teams` section IS on the customer path: `src/detect/dossier.py:86` adds it from the historical results store whenever the store is present, and the store ships in the image (`deploy/Dockerfile:58`). Live sample: `away_games_played 138, away_wins 73, away_losses 65, away_win_pct .529`, runs-scored/allowed per game, last-5/last-10 splits — every rate with its n. The ledger's separate "no `leagueRecord` in mlb.py" is STILL TRUE of the provider but moot: records are computed from our own store, not fetched. |
| Probable starters | **A** — `advanced.game.away_probable` / `home_probable` (+ `_id`s) verified live ("Randy Vásquez"). Absent when unannounced — design the absent state. |
| Starter stats (FIP/ERA/WHIP…) | **STILL TRUE — B.** `starters` remains a gap on the API path; `src/pipeline/pitchers.py` is CLI-only. |
| Starter handedness | **STILL TRUE — B** standalone; reaches the payload only inside matchup depth when a lineup is posted. |
| Lineups | **STILL TRUE as a pre-posting gap — A when posted.** `lineups` gap on the morning slate; rosterwatch threads posted lineups → matchup depth. Design both states. |
| Bullpen | **STILL TRUE — gap on API path** (`bullpen` in the live gap list). Pipeline exists (B). |
| Weather | **STILL TRUE — D.** `weather_by_pk` is an injectable seam nothing supplies on the customer path. Never render live weather. |
| Venue | **A** — `game.venue` full string, verified live ("Great American Ball Park"). Roof/altitude in park section. |
| Team display names | **STILL TRUE — no map anywhere; C to add.** Wire carries abbreviations (`"SD"`). A static 30-club abbrev→club-name map is a safe deterministic derivation. |
| Team colors | **SUPERSEDED — C, shipped.** `web/js/teamcolors.js` (commit `2947aa8`): static 30-club map, identity-only rule, NEUTRAL fallback for unknown abbrevs. |

### 3. TEAM / BOOK PRESENTATION

- Team display names: **do not exist** (verified: no `TEAM_NAMES`/
  `displayName` map in `web/js/`). **Safe static presentation map (C)**
  — MLB's 30 clubs are a fixed public list. Engineering ships it beside
  `teamcolors.js` when V2 commits to full names.
- Team colors: **exist** — `web/js/teamcolors.js` (C, shipped).
- Sportsbook display labels: **do not exist**; books are raw provider
  keys (`fanduel`, `williamhill_us`, `betonlineag`). **Safe static map
  (C)** for the ~11 US books the provider emits, with a raw-key
  fallback for unknown keys. No logos (trademark/licensing = a Brey
  decision, not a design default).

### 4. BET CHECK FRESHNESS — timestamp EXISTS; "UPDATED X SEC AGO" stays prohibited

SUPERSEDED in one narrow way: the ledger said "no age field at all."
There is **no `age_seconds`/`stale` field**, but the payload DOES carry
capture instants:

- `best_available_price.observed_utc` — required, constructor-enforced
  (`src/analysis/contracts.py:153,158`).
- The multibook board's `observed_utc` (`contracts.py:555,561`;
  threaded `src/analysis/betcheck.py:505-532`).
- The Game Quick view additionally carries
  `price.staleness.{observed_utc, age_seconds, has_board}` (verified
  live: `age_seconds 4883`).

**Design contract:** "PRICES CAPTURED 10:31 PM ET" / "AS OF <time>"
derived client-side from `observed_utc` is honest (C). A seconds-level
"UPDATED 32 SEC AGO" counter is **still prohibited**: capture cadence is
15–60 min and the live board measured ~81 minutes old today. If an age
is shown at all, show it in minutes/hours with no implied liveness.

### 5. BILLING / SIGNUP

- `DEFAULT_BILLING_PROVIDER = "null"` — **STILL TRUE**
  (`src/appstate/billing.py:851`). Provider selection reads the
  `BILLING_PROVIDER` env var only; Stripe keys alone do NOT activate
  Stripe.
- **Staging is NOT the default deployment:** Launch Ops configured
  Stripe TEST there; live staging signup returns a real
  `checkout:{checkout_url}` (verified during staging QA), and the
  activation-token handoff (`GET /signup/complete`, one-time) works
  end-to-end.
- Unconfigured deployment → honest `{status:"waitlisted"}` (all four
  signup outcomes HTTP 200 — STILL TRUE, `api/signup.py:166-190`).
  Design both branches.
- The ledger's "402 subscription_expired unreachable" and "null-provider
  cancel never persisted" are **SUPERSEDED** by the entitlement work
  (commit `4914756` and Lane B): scheduled cancel persists
  `cancel_at_period_end` + `current_period_end`
  (`api/billing.py:164,270`), entitlement is a local read
  (`customers.has_paid_access`, `api/auth.py:122`), the 402
  `{"error":"subscription_expired"}` state is reachable for
  subscription holders after period end, and **`POST
  /billing/reactivate` exists** (`api/billing.py:218`). "Cancelled?" is
  still answered by `cancel_at_period_end`, never `status` — STILL
  TRUE and load-bearing for the UI.
- Free checks: `/betcheck/free` **wired and live-verified on staging**
  (design already confirmed; parent re-verified with a real anonymous
  check). Response carries `free_check: {token, remaining, limit: 3}`
  (`api/betcheck.py:253-260`); exhaustion is 402
  `{error:"free_checks_exhausted", remaining: 0, limit: 3}`.

### 6. ODDS BOARD — the three variants STILL TRUE; distribution has shifted richer

- **Variant A (full board, consensus)** / **B (thin board, consensus
  null + `consensus_unavailable_reason` present)** / **C (no board,
  `board_available:false`, reason, and the `consensus_unavailable_reason`
  KEY ABSENT — use `hasOwnProperty`)** — all **STILL TRUE**
  (`src/analysis/oddspayload.py:184-215`).
- Consensus floor `MIN_BOOKS = 6` — STILL TRUE
  (`src/analysis/prices.py:31,100-102`).
- Book-count distribution, re-measured on the current multibook store
  (690 game-instants): **median 11, min 5, max 11, 0.3% below floor** —
  richer than the audit's median-8/6.5% (the store has densified since).
  Design rule stands: **show the real N, never a fixed "11"**, and keep
  the below-floor collapse state as a first-class (if now rare) variant.
- Best price: per-side best with **`best.{side}.books` an array of all
  ties — render all** — STILL TRUE.
- De-vig: proportional only on every customer path
  (`prices.py:95` calls `devig_two_way` with no method) — STILL TRUE.
  Label it MARKET-IMPLIED CONSENSUS, de-vigged; never "true" anything.
- Freshness: `staleness.{observed_utc, age_seconds}` raw, **no server
  stale verdict** — STILL TRUE. A client threshold must be drawn
  client-side (1800 s per `src/appstate/freshness.py:69`) and labeled
  as the client's own.
- Movement timestamps: **STILL TRUE — B.** Snapshot history exists in
  stores; `grep movement api/` → nothing. **No customer series
  endpoint.** The movement chart stays NOT YET AVAILABLE unless V2
  commits and engineering builds the endpoint.
- Outbound sportsbook URLs: **STILL TRUE — none exist** (no URL field on
  any price object), and **D by policy**: Brey's ruling is in-app
  COMPARE only for beta. No OPEN AT BOOK.

---

## SECONDARY RECONCILIATION

| Finding (ledger) | Verdict | Evidence at current HEAD |
|---|---|---|
| "Nothing in the shipped client is designed" (`renderUnknown` everywhere) | **SUPERSEDED** by `2947aa8` — Gameday d/m, Bet Check d/m, Game Quick/Advanced/mobile, and the shell are canvas-first designed implementations, graded VISUAL PASS on all 8 rows (`docs/VISUAL_ACCEPTANCE_TRACK1.md`) and byte-verified on staging. Odds, My Bets, Signup, Auth remain undesigned (Track 2, blocked on artboards). |
| Ten-block skeleton, "five rendered" | **SUPERSEDED** — all ten blocks render in order (`web/js/betcheck.js:14-23`, blocks 01–10 incl. STRONGEST/WEAKEST/WHAT CHANGED/HISTORICAL SUPPORT/EVIDENCE STATUS as peers). |
| `#/signin` does not exist | **SUPERSEDED** (design already confirmed) — interim screen at `web/js/signin.js`, routed `web/js/main.js:21,63`. Functional-only; never graded PASS; Track 2 designs it. |
| `/betcheck/free` unwired | **SUPERSEDED** (design already confirmed) — `web/js/betcheck.js` posts to it signed-out; live-verified on staging. |
| What Changed ~96% `lineup_posted`, identical MEDIUM tiers, player IDs not names, `market_reaction` null | **STILL TRUE.** Starter-change text still says "player {id} to player {id}" (`src/pipeline/briefing.py:289-290`). No reaction arrows (movement is B). Design for a feed of near-identical lineup-posted items. |
| WATCH OUT as a distinct feed | **NEVER TRUE** — no `watch_out` field has ever existed. The role is served by `counterargument_lines` (never empty, constructor-enforced, `contracts.py:516-518`) + the gap ledger. Merge/rename in V2; never fabricate a concern. |
| THE CASE (`thesis_support`) | **STILL TRUE** — can be and usually is `[]`. Empty-first design. |
| Bottom Line | **STILL TRUE — mechanical, not editorial.** Composed from finding counts + price clause + permanent disclaimer (`src/analysis/betcheck.py:586-633`). `recommendation` permanently null with a raising `__post_init__` (`contracts.py:495-501`). The canvas's editorial bottom line cannot be produced; render the server string verbatim. |
| My Bets narrow (8 fields, free text, delete-only, no save-from-Bet-Check, no ROI/record) | **STILL TRUE** in every particular. Grading needs `AWAY@HOME` + side conventions the form does not enforce. Unsettled rows have no reason text. |
| Free-check states | **A** — `remaining`/`limit` in every free 200; 402 exhaustion wall; token in body only. |
| Auth states | One 401 for missing/invalid/expired (deliberate) — STILL TRUE. 402 expired links `#/billing` → reactivate (SUPERSEDED, now real). Raw-API-text 401 rendering was replaced by designed customer copy in the rebuild. |
| Onboarding endpoint unclient-ed | **STILL TRUE** — `GET /onboarding` has zero client callers. |
| §4 HARD PROHIBITIONS (win probability, EV/edge, picks, confidence meters, ROI/record, public-%/steam/arrows, bare rates, personalized diffs, BELOW MARKET badge, MODERATE/STRONG support, "UPDATED 32 SEC AGO", "7 PTS BETTER" hero, book links, fixed "11 BOOKS", team-name evidence grouping) | **ALL STILL TRUE.** Every anchor re-checked or unchanged. These bind V2 exactly as written. |
| §5 copy contradictions (refund promise, "one click" cancel, "confirmation emailed instantly") | **FIXED in this commit** — `web/js/pricing.js` billing_note and `web/landing.html` pricing card + cancel FAQ now claim only what the code does (scheduled cancel, period-end access, on-screen activation code). Refund policy remains undecided and unpromised. |
| DEMO/SAMPLE chips | **E, rule inverted:** staging and production run LIVE captured data. Chips appear ONLY if data actually is sample — never as default chrome. |

---

## V2 DESIGN CONTRACT — CURRENT HEAD

Design may treat the following, and only the following, as real:

**Identity & schedule (A):** game_id · away/home abbreviations · date ·
first_pitch_utc · venue · probable starter names+ids (absent state
required) · doubleheader note.

**Presentation derivations (C, static, safe):** club display names ·
club colors (shipped) · sportsbook display labels · "as of <time>"
formatting from any `observed_utc`.

**Records & context (A):** teams section — W-L, win pct, runs
scored/allowed per game, last-5/last-10, home/away splits, every rate
with its sample · park section (roof/altitude; NO wind, NO live
weather).

**Market (A):** multibook board (one capture instant, one row per book,
real N; median 11, min observed 5) · best price per side with all tying
books · MARKET-IMPLIED CONSENSUS (proportional de-vig; null below the
6-book floor with a reason when a board exists, key absent when none) ·
price improvement points/return with mandatory label (negative is the
normal case — design the pill-absent default and the ~60-word note) ·
`staleness.{observed_utc, age_seconds}` raw (client draws and owns any
threshold).

**Analysis (A):** verdict (`no_play` dominant — PRIMARY state; flagged
~2%; market_unavailable ~5%) · findings usually `[]` ·
`counterargument_lines` never empty · thesis_support may be empty ·
ten-block Bet Check skeleton with blocks 05/06/08/09 usually NOT YET
AVAILABLE · mechanical bottom_line verbatim · evidence_status
"Observation" only · What Changed feed (mostly lineup postings, IDs not
names, no reaction data) · the 11-key gap ledger with per-gap reason
strings (render the reason).

**Commerce & account (A):** signup → checkout redirect OR waitlist
(both HTTP 200; both states designed) · one-time activation token
handoff (urgency designed, second retrieval refused, recovery via
POST /support) · $19.99/mo Founding Access · 3 lifetime free checks
with remaining/limit and a 402 exhaustion wall · bearer-token sign-in
(one undifferentiated 401) · 402 subscription_expired with reactivate ·
`cancel_at_period_end` (not `status`) answers "cancelled?" ·
`current_period_end` for "access until" copy · My Bets exactly as
scoped (save/list/delete, settlement states, no aggregates).

**Must NOT appear as live (D/E):** weather · line-movement chart or
arrows (B until an endpoint exists) · outbound sportsbook links (policy)
· starter stat lines (B) · bullpen workload (gap; honest-absence copy) ·
xwOBA/xFIP · win probabilities, EV, picks, confidence, ROI/records ·
sub-minute freshness claims · demo/sample chips on live data · refund
promises.

**B items needing an engineering request BEFORE an artboard commits:**
line-movement series endpoint · starter stats section on the API path ·
bullpen section on the API path · standalone handedness field · any
transactional email.

The real system defines this contract; nothing here was added to
preserve an artboard.
