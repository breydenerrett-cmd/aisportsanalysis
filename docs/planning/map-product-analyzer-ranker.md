# Subsystem map: product-analyzer-ranker

Read-only map, 2026-09-03, against branch `claude/sports-betting-analysis-review-g1o0co`.
Scope: `src/analysis/**`, `src/report/**`, `src/model/selections.py`, `api/**`,
`web/js/**` (V2 screens), `docs/PLAN_TWO_TOOLS.md`, `docs/API_CONTRACTS.md`,
`design/linehound-v2/RECONCILED_CONTRACT_CURRENT_HEAD.md`, plus the minimum
adjacent code needed to check claims (`src/detect/**`, `src/pipeline/mismatch.py`,
`src/providers/odds.py`, `src/pipeline/snapshots.py`).

All claims below are file:line evidence, not inference from docstrings. Where a
docstring claims something the code does not do, it is flagged CLAIMED-BUT-ABSENT.

---

## 1. What the analyzer computes per game today

**Detectors — EXISTS, but eleven, not a "search the whole board."**
`src/detect/detectors.py` defines exactly 11 `Detector` subclasses
(`ImpliedBullpenDisagreement`, `BullpenWorkload`, `StaleBook`, `StarterMismatch`,
`PlatoonMismatch`, `ThinMatchupHistory`, `LineupVsStarter`, `TravelLoad`,
`ParkAndWeather`, `BullpenExposure`, `PitchMixMismatch` — lines 86, 223, 280,
368, 420, 514, 561, 623, 702, 767, 842), registered in `register_defaults()`
(detectors.py:928-934). `src/detect/base.py` defines the `Finding` shape,
`EVIDENCE_ORDER` ladder (base.py:59), and `run_all`/`rank` (base.py:206,216).
This matches the vision's "11 detectors" inventory in `docs/PLAN_TWO_TOOLS.md`
line 15, but it is a fixed, hand-written set of pattern-checks, not the
vision's per-game deep reconstruction of starters/bullpen/offense/environment/
market followed by a search over every market on the board.

**Verdict pipeline — PARTIAL, and market-scope is the key limitation.**
`src/pipeline/mismatch.py` computes `verdict` in {`no_play`, `candidate`,
`flagged`, `market_unavailable`} (mismatch.py:131-139). `scan_game`
(mismatch.py:398-475) fires only on two signals (`starter_signal`,
`roster_signal`), requires both to agree (`MIN_AGREEING_SIGNALS`,
line 454), and routes the candidate to exactly one of two markets:
`MARKET_F5 = "first_five"` or `MARKET_FULL = "full_game"`
(mismatch.py:157-158, `route_market` ~line 380). `apply_market_screen`
(mismatch.py:482-524) prices ONLY that one routed market (moneyline)
against `away_price`/`home_price` — there is no run line, no totals, no
props, no alternates, no parlay path anywhere in this module. This is the
single largest gap against the owner vision's "search the entire board...
ask which market best expresses the informational advantage": the current
engine decides the market by a hand-coded rule (starter-only → F5,
roster-wide → full game) before ever looking at price, and never considers
any other market shape.

**Synthesis / narrative — EXISTS.** `src/analysis/synthesis.py` scores
candidate claims on five 0..1 terms (`_score`, synthesis.py:286-318) and
resolves conflicts per fact key (`_resolve`, line 320). `OBSERVED = "observed"`
(line 161) is the off-ladder "not a hypothesis" vocabulary called out in the
owner's evidence-ladder rule.

**Contracts / evidence & sample-size discipline — EXISTS and is well-enforced.**
`src/analysis/contracts.py` defines frozen dataclasses for six customer page
shapes (`TodayContract`, `GameQuickContract`, `GameAdvancedContract`,
`BetCheckContract`, `OddsBoardContract`, `WhatChangedContract` — grep of
`^class`/`^@dataclass`, lines 320-574). `Claim` (line 219) is documented to
refuse construction if quantitative without both a sample size and an
evidence label (contracts.py:9-11) — this directly matches the owner's
"sample size on every claim" requirement.

**Dossier sections actually reaching the API — PARTIAL, matches an existing
independent audit.** `design/linehound-v2/RECONCILED_CONTRACT_CURRENT_HEAD.md`
lines 38-42 (dated 2026-09-01/02, same HEAD) states the live API path
(`api/games.py:163`) yields 5 sections (`park, price_improvement,
multibook_board, teams, what_changed`) and 11 gaps (`arsenals, bullpen,
lineups, market, matchup_depth, matchup_history, news, splits, starters,
travel, weather`). Starter stats (FIP/ERA/WHIP/K%/BB%/arsenal/velocity —
`src/pipeline/pitchers.py`), bullpen workload, weather, and splits all exist
as pipeline code (dimension **B** in that doc's shorthand) but do not reach
the customer-facing payload. This is a PARTIAL against the owner's
"reconstruct everything legitimately knowable before the wager": the pipeline
computes much of it, the product surface does not carry it yet.

---

## 2. Engine 1 (price improvement) and Engine 2 (None)

**Engine 1 — EXISTS, two-way moneyline only.** `src/analysis/prices.py`
`snapshot()` (lines 79-140+) computes, per side, best American price, the
proportionally de-vigged consensus (`MIN_BOOKS = 6`, line 31), the
improvement in probability points and return %, and dispersion. Every dict
returned carries the mandatory `LABEL` (line 30-31) stating this is
line-shopping value, not EV or a prediction — matching the owner's own
constraint "price improvement is never EV/edge." `NO_IMPROVEMENT_NOTE`
(lines 38-45) explains that a positive number is the exception because the
compared price still carries vig. **Gap: this module only ever receives
`away_price`/`home_price`** — i.e. h2h/moneyline. No run line, totals, or
prop price improvement exists anywhere in this module or its callers
(`src/report/ranker.py`, `src/analysis/betcheck.py`).

**Engine 2 — MISSING by design, and deliberately gated.**
`src/report/ranker.py` line 33: `ENGINE2 = None`. The module docstring
(lines 1-22) states this stays `None` until 27 pre-registered hypotheses
across 4 families (`src/analysis/__init__.py:24-25`,
`HYPOTHESES_TESTED = 27`, `HYPOTHESIS_FAMILIES = 4`) produce a survivor, and
`tests/test_ranker.py` structurally pins that the page contains no bet
recommendation, pick, unit size, or "edge" language while Engine 2 is None
(ranker.py:19-22). This matches the owner's own standing constraint: "the
Ranker publishes nothing while Engine 2 is None until the unlock gates +
owner sign-off." `docs/PLAN_TWO_TOOLS.md` lines 262-268 spells out the four
unlock conditions (pre-registration + significance, falsification battery,
300+ forward selections, Brey sign-off) — none met yet per the same doc's
"Status close-out" section (lines ~395-405: V4/V5 both ran, zero survivors).

---

## 3. Bet Check

`src/analysis/betcheck.py` — `parse()` (structured comment ~line 200-237)
and `check()`/`build_contract()` (docstring lines 23-58). **Only moneyline
is supported.** `SUPPORTED_MARKETS = {"moneyline": "h2h"}` (betcheck.py:85-86);
`UNSUPPORTED_MARKETS` explicitly lists and refuses `runline`, `over/under`,
`total`, `player prop`/`props`/`prop` etc. (lines 93-113), returning a named
refusal rather than guessing (line 220-223: "the {market} market is not
supported yet"). This is a direct, current-code contradiction of the owner
vision's "search the whole board" for every matchup — today literally one
market (two-way moneyline) can even be asked about. `docs/API_CONTRACTS.md`
lines 209-243 documents `POST /betcheck` and `/betcheck/free` on this same
moneyline-only contract.

---

## 4. Bet Rating / Picks / LOCK product surface

**MISSING entirely.** No `rating`, `Rating`, `LOCK`, or `Pick` surface exists
in `src/report/dashboard.py`, `web/js/today.js`, `web/js/games.js`,
`api/today.py`, or `api/games.py` (grep across all five returned only an
unrelated code comment in today.js:82). `docs/API_CONTRACTS.md` line 466
states explicitly: "No `recommendation` value other than `null` (Ranker
Engine 2 is gated)." The six frozen contract shapes in `contracts.py` do not
include a picks/ranking/lock contract — by design, since Engine 2 is None.
Building a Bet Rating surface would need, at minimum: (a) Engine 2 to exist
(currently None), (b) a market-scope beyond moneyline (currently absent),
(c) a new contract dataclass analogous to the existing six, and (d) new API
route(s) and web/js view(s) — none of which exist as even a shell today
(the Ranker shell in `src/report/ranker.py` is a static HTML page, not an
API-backed product surface; there is no `api/ranker.py` or `api/picks.py`).

---

## 5. Where the vision's per-market candidate search would plug in

- `src/pipeline/mismatch.py::route_market` (~line 380) is the single
  chokepoint that currently hard-codes "starter signal → F5, roster signal →
  full game." A real per-market search would need this replaced (not
  extended) with something that scores every open market for the matchup.
- `src/providers/odds.py` — **the raw fetch already supports more than the
  rest of the stack uses.** `DEFAULT_MARKETS = ("h2h", "spreads", "totals")`
  (line 52) and `EVENT_MARKETS = ("h2h_1st_5_innings", "spreads_1st_5_innings",
  "totals_1st_5_innings")` (line 72) — moneyline, run line, and totals, full
  game and first five, are already fetchable from the provider today. Props,
  alternates, team totals, derivatives (race-to-X, first-to-score), and
  parlays/SGP are not present in this provider at all — those would need new
  API market keys and new credit budget, which is a real, non-trivial cost
  (the module's own comment at odds.py:5-6 notes fetching only h2h once
  silently missed markets the whole system needed).
- `src/pipeline/snapshots.py` lines 529-530: "spreads and totals — both
  captured into `odds_snapshots.jsonl` alongside h2h by the exact same
  `capture()` call, same shape, same timing — already [wired]." So **spreads
  and totals ARE being captured into the raw snapshot history right now**,
  even though nothing downstream (multibook store, price engine, mismatch
  screen, Bet Check, dashboard) reads them yet.
- `src/analysis/oddspayload.py` line 58: `MARKETS = ("h2h",)  # the only
  market the multi-book store captures today`, with the module docstring
  (lines 19-23) explicitly designing for a future market as "an additional
  key, not a reshape of every payload" — i.e. the seam to add spreads/totals
  to the customer-facing multibook board is deliberately left open and
  should be cheap to use, since the raw data already exists in
  `odds_snapshots.jsonl`.
- `src/model/selections.py` (backtest/grading engine) also only knows
  two-way moneyline prices (`_fair(bookmakers, home_name, away_name)`,
  line 85, and `HISTORICAL_SECTIONS`/`REBUILT_SECTIONS`, lines 45-53) — the
  backtest replay described in the owner vision ("replay history with the
  exact same decision engine... at what price, at which book") currently
  can only replay moneyline decisions, not run line/totals/props.

---

## Classification summary

### EXISTS
- 11 hand-written detectors with an evidence ladder and Finding.side
  partition (`src/detect/detectors.py`, `src/detect/base.py`).
- Verdict state machine no_play/candidate/flagged/market_unavailable
  (`src/pipeline/mismatch.py:131-139`, wired through gamepayload/dashboard).
- Engine 1 price-improvement library, two-way moneyline, mandatorily labeled
  as line-shopping value, not EV (`src/analysis/prices.py`).
- Engine 2 gate, structurally test-enforced None (`src/report/ranker.py:33`,
  `tests/test_ranker.py`).
- Six frozen customer contract shapes with sample+evidence enforcement
  (`src/analysis/contracts.py`).
- Forward ledger / grading infra referenced by `docs/PLAN_TWO_TOOLS.md`
  (B2), corroborated by `RECONCILED_CONTRACT_CURRENT_HEAD.md`'s n=129
  forward-ledger measurement.
- Raw odds fetch already covers h2h + spreads + totals, full game and F5
  (`src/providers/odds.py:52,72`), and raw capture of spreads/totals into
  `odds_snapshots.jsonl` (`src/pipeline/snapshots.py:529-530`) — data that
  is NOT yet surfaced anywhere downstream.
- Team/starter historical records section reaching the API
  (`src/detect/dossier.py:86`, per RECONCILED_CONTRACT doc §2).

### PARTIAL
- Per-game "everything knowable" reconstruction: starters (handedness/
  probable name only; ERA/WHIP/FIP/K%/arsenal computed in
  `src/pipeline/pitchers.py` but not on the API path), bullpen (pipeline
  exists, gap on API path), lineups (present once posted, gap before), park
  (present, no weather) — see RECONCILED_CONTRACT_CURRENT_HEAD.md §2 table.
- Market coverage: h2h + spreads + totals + F5 variants are fetched and
  (for h2h) fully wired; spreads/totals are captured but unused; nothing
  else (props, alternates, team totals, derivatives, parlays) is fetched at
  all.
- Evolab (`src/evolab/**`, 7,250 lines: baseline, cscv, spa, placebo, decide,
  genome, sweep, replay) is a real backtest/strategy-evaluation
  infrastructure that maps toward the owner's "strategy factory" vision, but
  it is not wired into the Analyzer/Ranker product surfaces in this
  subsystem's scope — it is a separate research-layer system today.

### MISSING
- Per-market "search the whole board" analysis for a matchup (run line, alt
  lines, totals, alt totals, team totals, margin, F5 combos, pitcher props,
  batter props, derivatives, parlays/SGP) — only h2h full-game and h2h F5
  are ever screened or priced.
- Bet Rating / Picks / LOCK customer surface — no contract, no API route, no
  web/js view; `docs/API_CONTRACTS.md:466` states no `recommendation` field
  other than null exists.
- Environment inputs beyond park identity: temp, wind, humidity, precip,
  altitude effect, umpire, travel-as-price-input — weather explicitly must
  never render live per RECONCILED_CONTRACT doc §"Must NOT appear as live."
- Player-level props, TTO-aware pitcher usage modeling, and workload/
  velocity trend detectors beyond the fixed 11.
- "Many competing analysis systems... thousands... GENERATE→TEST→SCORE→
  ATTACK→RETIRE→MUTATE→RETEST→FORWARD TEST→PROMOTE" pipeline wired to the
  product surfaces (evolab exists in isolation per above; no promotion path
  into `src/detect` or `ranker.py` was found).
- Public betting percentages / market disagreement-vs-sentiment — explicitly
  called BLOCKED in `docs/PLAN_TWO_TOOLS.md` line 133 ("no source we can
  access provides them").
- Prediction-market integration.

### CLAIMED-BUT-ABSENT
- None found where a docstring asserts a capability the code contradicts —
  this codebase is unusually disciplined about labeling gaps explicitly
  (`UNSUPPORTED_MARKETS` refusals, `MARKETS = ("h2h",)  # only market...`,
  the RECONCILED_CONTRACT doc's own STILL TRUE/SUPERSEDED/NEVER TRUE
  ledger). The one process risk is docstring optimism about future ease:
  `oddspayload.py`'s "a future market is an additional key, not a reshape"
  (lines 22-23, 228-229) is a design intent, not yet exercised — adding
  spreads to the customer board is unbuilt, just plausibly cheap.

---

## BOOST vs REPLACE per component

- **Detectors (`src/detect/detectors.py`) — BOOST.** The Finding/evidence-
  ladder shape is sound and matches the owner's sample-size/evidence
  discipline; add detectors and don't touch the base contract.
- **Verdict routing (`src/pipeline/mismatch.py::route_market` /
  `scan_game`) — REPLACE.** The two-market, two-signal, hard-coded routing
  rule is structurally the opposite of "search the whole board and ask
  which market best expresses the edge." A per-market scorer that evaluates
  every open market for a matchup and lets the market with the strongest
  signal-to-price fit win cannot be grafted onto this function; it needs a
  new decision function, keeping `apply_market_screen`'s point-in-time price
  discipline as a pattern to reuse per market.
- **Price engine (`src/analysis/prices.py`) — BOOST, carefully.** The
  math (de-vig, best price, dispersion, mandatory label) generalizes
  directly to any two-way market (spreads, totals, F5) with the same
  function signature swapped from away/home to over/under or +1.5/-1.5;
  this is the cheapest, most valuable next expansion given spreads/totals
  are already captured in `odds_snapshots.jsonl`.
- **Bet Check (`src/analysis/betcheck.py`) — BOOST.** The parse/refuse
  discipline is good design; extending `SUPPORTED_MARKETS` for run line and
  totals is additive once the price engine handles those markets, without
  touching the free-text refusal architecture.
- **Contracts (`src/analysis/contracts.py`) — BOOST.** Add new frozen
  dataclasses (e.g., a per-market `MarketCandidate` and eventually a gated
  `PicksContract`) alongside the existing six; the sample+evidence
  enforcement pattern should be reused, not redesigned.
- **Ranker (`src/report/ranker.py`) — BOOST the shell, nothing more until
  Engine 2 exists.** The test-enforced gate is exactly the right
  architecture for "publish nothing until proven"; do not weaken it to add
  a Bet Rating surface before an edge is unlocked per `docs/PLAN_TWO_TOOLS.md`.
- **Selections/backtest (`src/model/selections.py`) — REPLACE the market
  scope, keep the point-in-time discipline.** The three numbered rules
  (clean detectors only, clean-sections-only dossier, 6-hour-minimum
  recommendation price) are exactly the guardrails the owner vision demands
  and should not be touched; but `_fair()`'s two-way-only price extraction
  needs a generalized per-market version before any non-moneyline backtest
  is possible.
- **Odds provider (`src/providers/odds.py`) — BOOST.** Already fetches
  h2h/spreads/totals and F5 variants; extending to props/alternates is
  additive market-key work, gated on credit budget (this file already
  tracks credit cost per market — see `estimate_credits`, line 199).
- **Web/js V2 screens — BOOST.** `today.js`/`games.js`/`betcheck.js`/
  `featuredbet.js` are pure `renderX(host, data)` views over server payload;
  new market sections or a future Picks screen are additive slots, not a
  rewrite, per the existing "never fetches anything itself" pattern noted in
  `featuredbet.js`'s docstring (lines 22-24).

---

## Data that becomes unrecoverable if not captured now (2026 live season)

- **Point-in-time news/roster/lineup events** — `docs/PLAN_TWO_TOOLS.md`'s
  A1 news layer requires every item timestamped because "a news item without
  a time cannot be used in a backtest" (PLAN_TWO_TOOLS.md ~line 155-165).
  If not captured as it happens in-season, it cannot be reconstructed later.
- **Dense multi-book price snapshots** (already running per
  `src/pipeline/dense.py`, 15-min cadence) — the sole source for both Engine 1
  and any future per-market screen; a missed capture window for a game is
  permanently missing, not backfillable (`snapshots.py` explicitly notes
  "a missed window stays missing either way," line ~600).
- **Spreads/totals raw captures already landing in `odds_snapshots.jsonl`**
  (`snapshots.py:529-530`) but not yet promoted into the multibook store or
  any analysis surface — this is capture-ahead-of-use working as intended,
  but if the raw capture pipeline is ever paused or narrowed back to h2h-only
  before the multibook/price-engine expansion happens, the run-line/totals
  history for the 2026 live season is gone for good.
- **Confirmed lineups and scratches at post time** — needed for the vision's
  platoon/handedness matchup depth; `rosterwatch` threads posted lineups
  today (RECONCILED_CONTRACT §2 "Lineups" row) but only for games captured
  while the tool is running; a gap in the daily loop loses that game's
  lineup-timing data permanently.
- **Forward ledger entries** (`evidence/forward_ledger.jsonl`, n=129 per the
  RECONCILED_CONTRACT doc) — the only path to unlock condition 3 ("holds on
  forward data... over 300+ selections," PLAN_TWO_TOOLS.md line ~266); every
  day the daily loop does not run is a day that cannot be replayed into that
  count later.

---

## Key numbers (all evidence-backed above)

- 11 detectors (`src/detect/detectors.py`, 11 `class .*Detector` matches).
- 2 markets ever screened for a candidate: `first_five`, `full_game`
  (`src/pipeline/mismatch.py:157-158`).
- 1 market with any price-improvement/Bet Check support: moneyline (h2h)
  (`src/analysis/prices.py`, `src/analysis/betcheck.py:85-86`).
- 3 raw-fetchable markets already in the odds provider: h2h, spreads, totals,
  doubled for F5 (`src/providers/odds.py:52,72`).
- 6 frozen customer contract shapes (`src/analysis/contracts.py`).
- 27 pre-registered hypotheses tested, 0 survivors, across 4 families
  (`src/analysis/__init__.py:24-25`).
- `MIN_BOOKS = 6` consensus floor (`src/analysis/prices.py:31`).
- Live slate 2026-09-01: 15 games, 15 `no_play`, 0 findings (100%)
  (RECONCILED_CONTRACT_CURRENT_HEAD.md §1).
- Forward ledger n=129: 93.0% no_play, 2.3% flagged, 4.7% market_unavailable
  (RECONCILED_CONTRACT_CURRENT_HEAD.md §1).
- `ENGINE2 = None` (`src/report/ranker.py:33`).
- 0 lines of code implementing run line, totals, props, alternates,
  derivatives, or parlay analysis anywhere in `src/analysis/**`,
  `src/pipeline/mismatch.py`, or `src/model/selections.py`.
