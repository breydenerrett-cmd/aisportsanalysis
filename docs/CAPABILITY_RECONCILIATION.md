> **SUPERSEDED (2026-09-02)** — see design/linehound-v2/RECONCILED_CONTRACT_CURRENT_HEAD.md

# Capability Reconciliation — 2026-08-31

Verifies every capability label in `docs/PRODUCT_DESIGN_HANDOFF.md` against the
CURRENT repo. The handoff was drafted from an isolated read-only clone taken
earlier; today shipped changes in both directions. Current repo state wins
every disagreement below. Evidence gathered via free commands only (`wc`,
`grep`, `python3 -m src.cli timing`, `python3 -m src.cli status`) — no odds
credits spent, no results below the 30-event floor read, 2026 sealed range
untouched.

## Part 1 — Capability-by-capability verification

| Capability | Classification | Evidence (today) |
|---|---|---|
| Live odds / multi-book coverage | **READY BACKEND CAPABILITY** | `data/processed/odds_multibook.jsonl` = 2,533 rows across 11 books today (fanatics, betrivers, lowvig, bovada, betus, mybookieag, williamhill_us, draftkings, betonlineag, fanduel, betmgm). `src/analysis/prices.py` implements the snapshot/label logic consuming this store. |
| Historical odds store | **PARTIAL INGREDIENTS** | The multi-book capture above is the live feed; no separate long-run historical-odds archive was located alongside it in `data/processed/` — movement/spaced-observation reads (`cli snapshot`/`dense`/`movement`, per the handoff) depend on accumulated captures over time, not a backfilled archive. Treat "historical odds" as accumulating-today, not populated-from-history. |
| F5 close capture | **ENGINEERING REQUIRED (code shipped today, no data yet)** | The handoff's claim of a "fixed and capturing tonight" F5 close pass is confirmed at the code level: `src/pipeline/dense.py` has `_f5_close_pass`, `F5_CLOSE_MARKET = "h2h_1st_5_innings"`, budget/drop reporting wired into `cli brief --f5`, and `tests/test_f5_close.py` passes tests against it (bounded per-event spend, honest failure reporting, dated 2026-08-31). However, **no `data/processed/f5_close.jsonl` (or any f5-named data file) exists in the repo yet** — nothing has landed on disk as of this check. Classify the pass as shipped/tested code with zero captured rows tonight so far; do not claim it as READY until a data file with rows actually exists. |
| Lineup monitoring, probable starters, transactions | **READY BACKEND CAPABILITY (watch), PARTIAL (historical)** | `src/pipeline/rosterwatch.py` implements poll/record/event logic for probables, lineups, transactions. Watch stores today: `data/watch/probables_watch.jsonl` = 56 rows, `data/watch/lineups_watch.jsonl` = 61 rows, `data/watch/transactions_watch.jsonl` = 71 rows. Deeper historical stores also exist: `data/historical/lineups.jsonl` = 4,892 rows, `data/historical/transactions.jsonl` = 26,893 rows. `cli timing` output today shows `lineup_posted: 21 events, 21 admissible, 0 measurable` and `transaction_first_seen: 29 events, 28 admissible` — all still accumulating toward the 30-event floor, so no result reads exist below that floor (correctly withheld). |
| What Changed ingredients | **READY BACKEND CAPABILITY** | `src/analysis/relevance.py` implements `build_index`, `score_event`, `score_events`, `tier_sentence`, `basis_lines`, `what_changed` — a full tiering/scoring pipeline over the watch stores above. This backs the "since this morning" feed the handoff describes; per-user "since you last looked" personalization is correctly marked ENGINEERING REQUIRED by the handoff itself (needs accounts, which do not exist — see below). |
| Bet Check domain logic | **PARTIAL INGREDIENTS, actively being built (mid-flux per orchestrator)** | `src/analysis/betcheck.py` (428 lines) has a documented `parse()`/`check()` two-stage design, explicit refusal-not-guess parsing for team/market/price, and a fixed-skeleton verdict object mirroring the handoff's Bet Check output spec (thesis support, counterargument, price context, what-changed, sample-quality warnings, bottom line). No stub markers (`TODO`/`NotImplementedError`/`pass #`) were found in the file at read time. Only h2h (moneyline) is parsed today — every other market is explicitly refused by name, not silently coerced. Because another worker may be actively extending this file, treat this as a snapshot: solid skeleton and parsing exist, market coverage is moneyline-only, and downstream fields the handoff calls ENGINEERING REQUIRED (STRONGEST/WEAKEST REASON, HISTORICAL SUPPORT, EVIDENCE STATUS, BOTTOM LINE prose) were not confirmed as implemented in this read. |
| Dashboard / business-logic extraction state | **IN FLUX (noted, not a final state)** | `src/report/dashboard.py` (1,244 lines) already imports `src.analysis` (as `analysis`), `src.analysis.prices` and `src.analysis.synthesis` directly, and a comment in the file ("The count comes from src.analysis and nowhere else") shows extraction discipline is being actively enforced. Another worker is reportedly mid-refactor on this split — do not treat this line count or import list as final; re-check before building the plan's dashboard-dependent screens. |
| Market consensus and de-vig | **READY BACKEND CAPABILITY** | `src/model/selections.py` calls `odds_math.devig_two_way(away, home)` inside `_fair()`, and documents deliberately using every book from the recommendation snapshot rather than a single consensus number (a prior version silently produced zero selections doing that). This is real de-vig math over the live multi-book feed. |
| Price improvement | **READY BACKEND CAPABILITY, labeling constraint binding** | `src/analysis/prices.py` implements the price snapshot and `LABEL` used by `betcheck.py`. Per the codebase's own doctrine (visible in `betcheck.py`'s docstring): a bet's price beating de-vigged consensus is **LINE-SHOPPING VALUE**, never "expected value" or "edge." Design must use that exact vocabulary. |
| Forward ledger and evidence | **PARTIAL INGREDIENTS** | `src/pipeline/ledger.py` exists in the pipeline; evidence labeling is centralized in `src/analysis/synthesis.py` (`EVIDENCE_LABELS`, referenced from `betcheck.py`). Full ledger contents/maturity were not read in depth here (out of scope for free-command evidence); classify as existing machinery, unverified end-to-end today. |
| V3 state | **RESEARCH DEPENDENT, still accumulating** | `python3 -m src.cli timing` today: `hitter_scratch: 1 events, 1 admissible, 0 measurable, accumulating (1 of 30 admitted)`; `lineup_posted: 21 events, 21 admissible, 0 measurable, accumulating (21 of 30)`; `transaction_first_seen: 29 events, 28 admissible, 0 measurable, accumulating (28 of 30)`. Results store settled through 2026-08-30. No event family has crossed the 30-event admission floor yet, so no result reads exist below it (correctly enforced) — counts only, as instructed. |
| Probability model calibration | **BLOCKED (load-bearing constraint)** | `python3 -m src.cli status` today: `probability: UNCALIBRATED -- no fitted model yet`; `edge claims: not available until calibration completes`. Per the mission brief, Phase 2A found no linear info beyond the close. **No screen in the design may display a model win-probability number.** Bet Check's own rule 4 (in the handoff) already states this correctly — hold the line on it. |
| Statcast pitch features, pitching metrics, bullpen metrics | **RESEARCH DEPENDENT (pitch-level) / PARTIAL (aggregate)** | `src/pipeline/rebuilt.py` backs FIP/ERA/WHIP-style aggregate metrics. `selections.py`'s `_bullpen_for` takes a plain `bullpen_by_team` dict passed in by callers (`cli.py`, `briefing.py`) — there is no `bullpen_grade.py` module backing it; that file had zero importers repo-wide and was deleted 2026-09-02. Pitch mix, velocity, xwOBA, xFIP, lineup-slot decomposition are NOT ingested — the engine is Python-standard-library-only with MLB Stats API + Open-Meteo as the only external sources, matching the handoff's own footnote. Design Advanced View blocks 1 (partly) and 3 as EXISTS TODAY only for the non-Statcast fields; everything marked `*` in the handoff's block list stays FUTURE / RESEARCH DEPENDENT. |
| Weather and park orientation | **READY BACKEND CAPABILITY** | `src/pipeline/slate.py` defines weather columns (`weather_temp_f`, `weather_wind_mph`, `weather_wind_from_deg`, `weather_humidity_pct`, `weather_source`, `wind_effect`, `wind_applicable`) and `_attach_weather()` calling `src/providers/weather.py` (Open-Meteo). `docs/PARK_ORIENTATION.md` (70 lines) documents park bearing data backing the wind-direction caveat the handoff requires. |
| Props | **PARTIAL INGREDIENTS — feasibility/listing only, no prices** | `data/processed/prop_listing.jsonl` = 40 rows today, all listing-feasibility records (event/book/market/player/slot/listed flag), e.g. `pitcher_strikeouts` for Bryce Elder at FanDuel, `listed: true`. This confirms *which props are offered*, not their prices or any prop-level analysis. Matches the handoff's own "LATER / FUTURE / RESEARCH DEPENDENT" label for the Props page — do not let the fact that a listing feed now exists upgrade that label; it answers a different question than "what price/edge does this prop have." |
| User/application infrastructure, auth, billing, deployment | **ENGINEERING REQUIRED — none exist** | Confirmed by `docs/PRODUCT_ARCHITECTURE_AUDIT.md` and `docs/SAAS_APPLICATION_ARCHITECTURE.md` (1,251 lines) — the latter is the plan, not an implementation. No auth/billing/deployment code path was found in the modules reviewed. A plan exists; no infrastructure exists. |

## Part 2 — §17 contract-readiness table (per-screen field audit)

Legend: REAL TODAY (working code + data backs it now) / PARTIAL (some of the
field exists, some does not — treat the whole field as not-yet-designable at
full fidelity) / ENGINEERING REQUIRED (no code path yet, or explicitly named
so by the handoff) / RESEARCH DEPENDENT (blocked on data/model that does not
exist).

### TODAY (main landing page — Quick View + What Changed band)
| Field | Status | Why |
|---|---|---|
| Game list / schedule | REAL TODAY | Backed by pipeline slate/dossier build. |
| Quick View 5-factor summary (✓/⚠) | PARTIAL | `src/detect/dossier.py`-driven findings exist; the handoff itself labels Quick View "ENGINEERING REQUIRED (content EXISTS TODAY)" — the UI layer and truncation-to-5 logic are not yet built. |
| WHAT CHANGED live band | REAL TODAY | `src/analysis/relevance.py` scoring + watch stores (Part 1) are live and accumulating today. "Since you last looked" personalization is ENGINEERING REQUIRED (needs accounts, which don't exist). |
| Best available price / market snapshot | REAL TODAY | Multi-book feed + `prices.py` snapshot, 2,533 rows today. |
| Data support meter (●●●○) | ENGINEERING REQUIRED | No evidence of a confidence-meter mapping in the modules read; would need a defined scale on top of existing evidence labels. |

### GAME QUICK (Quick View detail page)
| Field | Status | Why |
|---|---|---|
| ✓/⚠ factor sentences | PARTIAL | Findings exist (`detect.base.Finding`); plain-English sentence generation/truncation not confirmed built. |
| Your bet / best available price line | REAL TODAY | `prices.py` + multi-book store. |
| Historical evidence line | RESEARCH DEPENDENT | Must not overstate — 27 pre-registered hypotheses have not survived measurement per `betcheck.py`'s own docstring; any "historical evidence" copy must say so, never imply a demonstrated edge. |
| Show Advanced control/transition | ENGINEERING REQUIRED | UI/interaction layer, not backend. |

### GAME ADVANCED
| Field | Status | Why |
|---|---|---|
| Starting pitcher FIP/ERA/WHIP/K-BB%/IP | REAL TODAY | `rebuilt.py`, `selections.py` dossier building consumes pitcher logs. |
| xFIP, pitch mix, velocity, xwOBA, lineup-slot decomposition | RESEARCH DEPENDENT | Confirmed not ingested — standard-library + MLB Stats API + Open-Meteo only. |
| Lineups (confirmed vs projected, platoon splits) | PARTIAL | Confirmed/projected lineup data exists via rosterwatch; platoon-split computation not confirmed in modules read. |
| Bullpen availability/leverage | REAL TODAY | `src/pipeline/bullpen.py` (`read_log`, `team_workload`, `build_log`, 295 lines) computes per-team workload from boxscores; `cli.py` passes the result into `selections.py`'s `_bullpen_for`, which takes a plain dict — there is no `bullpen_grade.py` (deleted 2026-09-02, zero importers repo-wide). |
| Market: full de-vig table, hold, consensus, dispersion, F5 vs full game | PARTIAL | De-vig/consensus/multi-book real today; F5-vs-full-game comparison is blocked until F5 close data actually lands (currently zero rows — see Part 1). |
| Context: park, weather+wind bearing, travel, rest | REAL TODAY | Weather provider + `PARK_ORIENTATION.md` confirmed; travel/rest fields present in pipeline (`travel.py`). |
| Evidence + method (sample sizes, CIs, derivation) | PARTIAL | Evidence labels exist (`synthesis.py`); confidence-interval presentation not confirmed built. |

### BET CHECK
| Field | Status | Why |
|---|---|---|
| Parse free-text bet (moneyline) | REAL TODAY | `betcheck.py` `parse()`, h2h only, explicit refusal for other markets. |
| Parse spread/total/props | ENGINEERING REQUIRED | Explicitly refused by name in code today, not silently handled. |
| THESIS SUPPORT / COUNTERARGUMENT | PARTIAL | Verdict-object design exists per docstring; full field population depends on the in-flight build — flag as PARTIAL until confirmed end-to-end. |
| BEST AVAILABLE PRICE / MARKET CONSENSUS | REAL TODAY | Backed by `prices.py` + `selections.py` de-vig, both confirmed live. |
| YOUR PRICE vs market flag | REAL TODAY | Same price machinery. |
| STRONGEST/WEAKEST REASON | ENGINEERING REQUIRED | Handoff itself marks this ENGINEERING REQUIRED; not confirmed present in `betcheck.py` at this read. |
| WHAT CHANGED (per-bet) | REAL TODAY | `relevance.py` scoring is callable per game/dossier. |
| HISTORICAL SUPPORT meter | ENGINEERING REQUIRED | Handoff marks ENGINEERING REQUIRED; no meter-mapping code found. |
| EVIDENCE STATUS ladder | ENGINEERING REQUIRED | Handoff marks ENGINEERING REQUIRED; underlying evidence labels exist but the 5-stage ladder UI/logic does not. |
| BOTTOM LINE prose | ENGINEERING REQUIRED | Handoff marks ENGINEERING REQUIRED; needs template/generation logic not confirmed present. |
| Win probability | **BLOCKED — must never appear** | Model UNCALIBRATED per `cli status`; hold this line absolutely in design. |

### ODDS (Market Board)
| Field | Status | Why |
|---|---|---|
| Best price + book name | REAL TODAY | Multi-book feed, 11 books, 2,533 rows today. |
| Consensus (de-vigged) | REAL TODAY | `selections.py` de-vig. |
| Spread of books / disagreement | REAL TODAY | Same multi-book store supports per-book comparison. |
| Price age / staleness indicator | PARTIAL | Timestamps exist in the raw feed; a designed staleness threshold/label was not confirmed as implemented. |
| F5 vs full game side by side | ENGINEERING REQUIRED (today), pending data | F5 close pass code shipped and tested today but zero rows captured so far — see Part 1. Do not design this as populated until a data file with rows exists. |
| Movement column | PARTIAL | Depends on spaced observations accumulating over time in the multi-book store; not a backfilled history. |

### WHAT CHANGED (standalone feed)
| Field | Status | Why |
|---|---|---|
| Reverse-chronological timestamped events | REAL TODAY | `relevance.py` + watch stores, accumulating today (56/61/71 rows across the three watch stores). |
| Event + market-reaction pairing | PARTIAL | Both ingredients exist (events from watch stores, price moves from multi-book store) but the pairing logic ("why did this line move" causal narrative) is explicitly V1/ENGINEERING REQUIRED per the handoff, not built today. |
| Relevance tiering (tier 1–2 default, show all) | REAL TODAY | `relevance.py` has `tier_rank`, `_shift`, `_best` — tiering logic is implemented. |
| "Since you last looked" | ENGINEERING REQUIRED | Needs accounts, which do not exist. Use "since this morning" per the handoff's own fallback. |
| Empty state | REAL TODAY | Trivial to support given the above is real; no blocking dependency. |

## Notes on staleness direction (both ways)

- **Handoff too pessimistic today, repo has since caught up:** dashboard/business-logic
  extraction is further along than a static snapshot would show (imports from
  `src.analysis` are already in place in `dashboard.py`), and de-vig/multi-book
  consensus is fully real, not aspirational.
- **Handoff too optimistic, repo has NOT caught up:** the F5 close capture pass
  is code-complete and tested today, but **zero rows exist in any f5-close data
  file** as of this check — "fixed and capturing tonight" is a code-level fact,
  not yet a data-level fact. Treat F5-vs-full-game board content as blocked
  until confirmed populated.
- **Mid-flux, deliberately unresolved:** Bet Check domain logic and the
  dashboard extraction are both being actively worked by other agents today.
  This document reflects a single read-time snapshot of each; re-verify before
  finalizing any Bet Check or dashboard-dependent artboard.
