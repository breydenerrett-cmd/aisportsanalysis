# Reality audit, 2026-09-28

One source of truth for what Linehound is today, written before any new
feature work. Every factual claim cites a file:line, a commit, a workflow run
id, a ledger figure or a saved command output. `[verified]` means re-run or
re-read by the orchestrator in this session; `[recon]` means extracted by a
read-only reconnaissance pass and not independently re-run; `[inference]`
means a conclusion, not an observation. Local HEAD is `b152510d` plus the
commits made today; origin's tip at the time of writing is `b5d81872`
(2026-09-28T19:10Z). The runners and staging build from origin, not from
local. Evidence outputs are in `docs/audit/2026-09-28/`.

## A. What works end to end today

- Paid odds capture into `data/processed/odds_multibook.jsonl` with byte-
  preserving cold rotation: all three production rotations reproduced
  logically byte-identical (`docs/audit/2026-09-28/odds_multibook_rotation_verification.txt`,
  "ALL PRESERVED"; hot 46,970,071 bytes at `2ff8f48d`, 8 segments) `[verified]`.
- The public V2 card publishes, locks and settles nightly through the hash-
  chained ledger `evidence/cards_v2.jsonl`: 66 published rows and 6 settled
  dates (2026-09-22..27) on origin `b5d81872` `[verified]`; all five card
  chains verify `[recon]`; the decisions chain verifies over 33,252 rows
  `[verified]`.
- Settlement grading is behaviour-stable across the delayed-settlement change:
  6,075 of 6,424 real graded entries identical old vs new, 349 VOID to
  UNRESOLVED, W/L/P/units identical on every date, re-entry settles exactly
  once (`docs/audit/2026-09-28/settlement_regression_v1_v2.txt`) `[verified]`.
- The record page reconciles exactly: V1 final 73-40 games + 78-39 props =
  151-79, +7.9821u (`api/meta.py`, `src/report/effective_record.py`, local run)
  `[verified]`.
- Capture cadence keeps running: 163 forward-capture successes since 09-25
  (`gh run list`) `[verified]`; the chain self-dispatches and a Windows task on
  this PC (`scripts/capture_tick.ps1`, log `data/logs/capture_tick.log`, last
  line 18:56Z today) dispatches the daily loop and afternoon slate `[verified]`.
- The test suite runs: 8,270 tests at the pre-lane baseline `9de735a8` with
  20 real failures, all Windows-environmental
  (`docs/audit/2026-09-28/full_suite_baseline_9de735a8_failures.txt`) `[verified]`.

## B. What only appears to work

1. Capture is green while pricing nothing. Balance 4,941 credits at 19:08Z
   against `CREDIT_FLOOR = 5000` (`src/capture/budget.py:93`); the credit log
   has no upward jump since it began on 09-02 at 99,692 `[verified]`. Every
   slot since about 18:52Z on 09-27 skipped MLB, NFL and UFC pricing and
   finished green because forward-capture has no ESCALATE step
   (`scripts/capture_slot.sh:771-784`) `[recon]`. The afternoon slate refuses
   as stale (3 h limit, `src/engine/preflight.py:87`, run 36441570367)
   `[recon]`. Only the daily-loop snapshot still prices; it has no floor check
   (`src/cli.py:2013-2033`) `[recon]`.
2. Pushes are green until they are not. `evidence/decisions_v2.jsonl` is
   104,665,523 bytes on origin against GitHub's 104,857,600 limit (192,077
   bytes of headroom) `[verified]`. On 09-27 four capture slots whose lineup-
   gated slate pass appended decisions were rejected (runs 36328447003,
   36331611286, 36336047607, 36338843803): 219 + 285 + 314 + 333 = 1,151
   decisions and 384 paper wagers died with the runners (219 and 333
   spot-checked in the raw logs) `[verified]`, together with every raw odds
   file after 14:55Z and the afternoon's V2 republishes `[recon]`. The 22
   afternoon-slate failures since then lost nothing: their "decisions
   recorded" line counts rows already in the ledger
   (`scripts/afternoon_slate.sh:134-157`) `[recon]`.
3. "Graded in public" for UFC. 49 UFC picks published, 0 ever graded; results
   are manual, git-ignored (`.gitignore:13`) and uncached, and the daily loop
   has no UFC settle step `[verified]`. `web/landing.html:36,84,520` sells it
   as graded `[recon]`.
4. The deployed record strip says "Nothing graded yet" for MLB since the
   09-23 cutover: origin's `/card/record` V2 branch returns no flat keys and
   the strip reads them (`web/js/recordstrip.js:121-126`) `[recon]`; the fix is
   local commit `76cd527f` `[verified]`.
5. `/health` is `ok` on stale data: it never degrades on staleness and checks
   capture stores, not the ledgers the pages read
   (`src/appstate/apphealth.py:54-68,378`) `[recon]`. Capture health reports
   HEALTHY_IDLE from commit timestamps while nothing is priced
   (`src/capture/health.py:250-275`) `[recon]`.
6. Production. `deploy-prod` has never run `[verified]`; no
   `FLY_PROD_API_TOKEN` (run 36462148974) and `deploy/CLOUDFLARE.md:53`
   "linehound-prod DOES NOT EXIST YET" while linehound.app CNAMEs to it
   `[recon]`. Staging's last green deploy was `954ac8c6` on 2026-09-23T19:09Z;
   59 failures since; uvicorn is OOM-killed at about 878 MB on a 1,024 MB
   machine when /games loads (log 2026-09-27T14:17Z; run 36448137668)
   `[verified]`. `[inference]` the per-request materialisation of all 33k
   decision rows (`api/games.py:201-213`, `settle_slate.load_decisions`) is
   the OOM.
7. The daily loop "runs" but has failed 10 times in a row (`engine settle
   failed for 2026-09-27`: game_pk 823490 BAL@NYY missing from the results
   store; settlement gap; run 36460989591) `[recon]`; on game days `engine
   slate` takes 17-19 minutes of a 30-minute job with buffered output (runs
   36327436408, 36311686522) `[recon]`.
8. NFL live windows finish green while every tick raises `TypeError:
   can_spend() got an unexpected keyword argument 'env'`
   (`src/pipeline/livefeed_nfl.py:100`, `src/capture/budget.py:744-745`)
   `[recon]`.
9. Frozen cards always report `stale: False` (`api/card.py:290-296`)
   `[verified]`.

## C. Untested, stale, duplicated, contradictory, disconnected

- 16 reviewed local commits (`330820d4`..`b152510d`) are not on origin:
  delayed settlement, re-entrant settle, postseason results ingest, record UI,
  postseason demo, run-line shadow arm, critic, fingerprint bookkeeping
  `[verified]`. Local is 816 capture commits behind origin `[verified]`.
- Two schedulers: default-branch crons plus the PC watchdog, so the daily
  loop runs twice a day (cron observed 13:55-17:50Z, watchdog 10:10Z)
  `[recon]`. The working-branch copies of the workflow files differ from the
  default-branch copies that actually run (afternoon-slate crons) `[recon]`.
- CI never exercises the HTTP routes: about 40 API test modules skip without
  fastapi (`tests/test_api_card.py:44`) `[recon]`; `tests.yml` does not run on
  bot pushes, so the last CI run was 09-25 `[recon]`; `scripts/test_parallel.py`
  shards on timings from 09-06 covering 131 of 428 modules `[recon]`.
- Registration integrity: every production V2 row carries
  `code_fingerprint a6957bc3` (LF) while section 16 registered `8a641de0`
  (CRLF) `[verified]`; the frozen-params sha256 in section 16 does not match
  the committed file `[recon]`; all 336 V1 shadow rows carry no fingerprint,
  so the registered V1 comparison has no pin `[verified]`; section 16 never
  recorded any of this `[recon]`.
- V2 publishes outside its registration: `batter_runs_scored` is excluded by
  `PREREG_CARD_V2.md:380` yet 4 graded entries exist, all VOID "no settlement
  rule" `[verified]`; PLUS_MONEY cannot fire on game moneylines (ERRATUM E1)
  `[recon]`; run lines are not enumerated (E2) `[recon]`.
- V2's public record includes 09-22, the day before `CUTOVER_DATE`
  (`src/report/card.py:610`), when a row listed 24 entries against the ceiling
  of 10 `[verified]`; 09-26 and 09-27 cards were fills only `[recon]`.
- Postseason: PREREG 11.1 says postseason picks are "published, graded and
  shown on the record, but not counted" (`docs/PREREG_CARD_V2.md:1087-1089`)
  but no V2 reader filters `game_type`, and prop candidates are frozen
  `"game_type": "R"` (`src/report/card_v2.py:275`) `[verified]`. On origin the
  results ingest stores regular season only and a missing score grades VOID
  `[recon]`; the fixes are local. Wild Card starts 2026-09-29.
- Paper arms A2-A4 were never wired (no ledgers, no section 16 start row)
  and the 2026 counted window has closed `[recon]`.
- The alpha registry (92 rows: 47 registered, 37 read, 10 pending, 0
  survivors; last write 2026-09-15) omits the F5 family, totals, card V2, NFL
  V2, UFC and the value shadow `[recon]`. The F5 result cannot be re-derived
  from disk (`first_five_results.jsonl` absent) `[recon]`; 12 F5 genomes are
  still active in the engine and F5 close capture still spends `[recon]`.
- Unwired or callerless: `scripts/pitcher_log_freshness_audit.py`,
  `scripts/capture_health.sh`, `scripts/forward_capture.sh`,
  `card_ledger.publish_variants` `[recon]`.
- Stale documents: README ("Probability model: does not exist", "350
  tests"), ROADMAP, DEBRIEF_LATEST, GO_LIVE_TOMORROW, LAUNCH_KIT (quotes the
  retired rule's games-only 68-35 and promotes Bet Check against the owner
  ruling), STATE_OF_PLAY, NEVER_RAN_REGISTER, RESEARCH_CATALOGUE,
  MODEL_ROUTING_POLICY (says Fable orchestrates while CLAUDE.md says Opus)
  `[recon]`.
- Copy that is wrong or stale: "Between 2023 and 2024 we pre-registered"
  (registrations are dated 2026-08-28..09-16); `today.js` calls the read count
  "pre-registered"; `gotcha.js` says 40; "Tonight's card is already up" on
  off-days; "Prices are bought from three hours before first pitch" while
  below the floor `[recon]`; `MODEL_BASIS` says "No parameter in it was
  fitted to results" while `DISPERSION` and the calibration layer were fitted
  (`src/analysis/strength.py:158-166,213-219`) `[verified]`.

## D. Every policy producing public analysis, and its evidence

| Surface | Rule / model | What it is | Evidence today |
|---|---|---|---|
| `/card` MLB (default) | `DAILY_CARD_BEST_BETS_V2` (`src/analysis/best_bets_card.py:129`), `ACTIVE_CARD_RULE="v2"` since 2026-09-23 (`src/report/card.py:600,610`) | `run_expectancy_poisson_v1` (`src/analysis/strength.py:213`) with frozen dispersion 2.3615 and a moneyline calibration fitted on 2025 (n=2027); props from the live `batter_pa_outcome_v1` board | Origin `b5d81872`: MAIN 18-18, 5 VOID, -4.57u; PLUS_MONEY 1-0 plus 1 VOID, +1.20u; fills 21-8, 3 VOID, +7.68u (recomputed) `[verified]`. No pre-registered read has occurred; the counted sample is undefined (fingerprint gap above). The registration claims no edge (`PREREG_CARD_V2.md:91`). |
| `/card?rule=v1` | `DAILY_CARD_MARKET_SIDE_MODEL_AGREEMENT_V1`, retired from the public card after 09-22, shadow since | The same strength model with module dispersion 2.3352 and `card_calibration.json` (fitted on the 2026 season through 09-14, inside the sealed window `[recon]`) | 151-79, +7.98u over 13 nights (games 73-40, props 78-39) `[verified]`. A selective quote (68-35, games only) circulates in `docs/launch/LAUNCH_KIT.md` `[recon]`. |
| `/card?sport=nfl` | `NFL_CARD_V2` (`src/analysis/nfl_value.py:66`) | Leave-one-book-out de-vig, EV at least 0.02 under three de-vig methods, no price at or below -200, max 5 | NFL V1 7-3, -0.26u; V2 1-0, +0.93u `[recon]`; no evaluation plan in `PREREG_NFL_CARD_V2.md` `[recon]`. |
| `/card?sport=mma` | `UFC_CARD_V1` (`src/analysis/ufc_card.py:59`) | Mean de-vig over at least 3 books, favourites better than -200 or dogs +100..+150 | 49 published, 0 graded, no results store `[verified]`. |
| `/game`, `/daily`, `/record`, `/performance` | Engine genomes (`src/engine/adapters/evolab_system.py:492-497`), classes CONTROL / MARKET_REFERENCE / FORWARD_TEST (`src/report/engine_bridge.py:74`) | No genome carries its own model probability; `p_model` is none, placeholder or market-derived on every live row (`src/report/daily_record.py` docstring) `[recon]` | Paper accounts and `evidence/decisions_v2.jsonl` (33k rows, dominated by MARKET_REFERENCE and CONTROL: 262 + 131 on 09-27) `[verified]`. |
| `/opportunities`, `/odds` | Price verdicts STRONG VALUE / VALUE / LEAN (`src/analysis/opportunities.py:60`) | Best price against the de-vigged consensus: execution quality, not a forecast | Honest by construction; goes stale with capture. |
| `/props` | `batter_pa_outcome_v1` (`src/analysis/playerprops.py`) | Ranked by our probability, floor 0.50, min 2 books | Prop calibration buckets overconfident (`docs/PROP_CALIBRATION_2026-09-14.md`) `[recon]`; `batter_runs_scored` cannot settle `[verified]`. |
| `/performance/live` | `live_ledger` rules (`src/appstate/live_ledger.py`) | Interim W/L per LIVE_V0 rule | Rules still pending in the registry `[recon]`. |

Shadow-only, never public (each guarded in code): `CARD_STORE_V2_SHADOW_A/C/E`
and `cards_v1_shadow.jsonl` (no API reader; `effective_record.py:45-56`),
VAR arms (`publish_variants` has no caller), `mlb_value_shadow_v1`
(`customer_surface: False`, isolation tests), the enumeration shadow
(`tests/test_card_v2_candidate_enumeration.py` import allow-list), the critic
(`scripts/ai_analyst.py`, evidence only), the postseason demo `[recon]`.

Research truth: 37 hypotheses read, 0 survivors; the registered F5 family
produced zero survivors (`docs/F5_RESEARCH_RESULTS.md`); no live policy has
evidence of beating a de-vigged market baseline on any metric; no CLV figure
exists anywhere `[recon]`. That is a correct research outcome, and it is the
largest gap between what the product's copy implies and what the evidence
proves.

## E. Data sources

| Source and store | Stamps | Freshness (origin) | Cost | Leakage risk |
|---|---|---|---|---|
| The Odds API: `odds_multibook.jsonl` (+ archive), `odds_snapshots`, `f5_close`, `batter_props`, `prop_prices`, `derivative_markets` (paused since 09-21), raw `data/raw/oddsapi/*.gz` | `observed_utc`, `book_last_update`, `commence_time` | Last forward-capture MLB rows 09-27 14:54Z; daily-loop snapshots 09-28 `[recon]`; 4,941 credits `[verified]` | $59/mo, 100k credits, floor 5,000, envelope 900/day (`budget.py:63,86,93`) | Closing price is the last observation before first pitch (`snapshots.py:837`); frozen card prices can be hours old with `stale: False` `[verified]`. |
| MLB Stats API: `mlb_results.csv` (+manifest), boxscores, `pitcher_logs`, `bullpen_log`, `standings`, `transactions`, lineup/probables watch | `date`, `observed_utc` or `fetched_utc`; results carry `game_type` but no fetch stamp | Git copies: results to 09-10 (R only), pitcher logs 09-07, bullpen 09-06, standings and transactions 09-08; runners see newer cache copies `[recon; results and standings verified earlier]` | free | Cache-restored stores overwrite git on runners (`daily-loop.yml:78-117`); different runners read different results stores `[recon]`. Postseason rows exist only locally. |
| Savant arsenals, statSplits, vsPlayer | `as_of` (2026-09-08) | frozen at 09-08 | free | Applied to any 2026 date without an as-of guard (`enrichment.py:189-248`, `pointintime.py:108-131`) `[recon]`. |
| Open-Meteo weather | `observed_utc`, `provider_run_time` | to 09-25 locally | free | clean (`pointintime.py`) `[recon]`. |
| BALLDONTLIE (tennis), API-Tennis | | HTTP 401; capture paused (`tennis_capture.py:62-80`) | trial | dead feed `[recon]`. |
| nflverse CSVs | per request | live | free | none noted. |
| Sealed window 2026-01-01..08-27 (`scripts/fit_card_v2_frozen_params.py:43-57`) | | | | V1 dispersion and calibration were fitted inside it `[recon]`; V2 fitted on 2025 only `[recon]`. |

Point-in-time defects: past-date pages use the request time as information
time (`src/detect/dossier.py:37-39`, `src/analysis/briefing.py:347-350`)
`[recon]`; under `--now` the quote-leakage guard holds but model inputs read
from box-score history drift between runs (observed when the 143000Z artifact
was regenerated) `[verified]`; the leakage gate last ran 2026-09-03 `[recon]`.

## F. Operational failures and silent-failure risks

Active: (1) ledger push rejections, evidence lost (B2); (2) credits below
the floor, capture dry and green (B1); (3) staging OOM, production absent
(B6); (4) daily loop red, 823490 settlement blocker, near-timeout slates (B7);
(5) postseason ungradeable on origin (C).

Latent, cited: forward-capture prints ESCALATE lines after the commit and
never fails (`capture_slot.sh:771-784`); `afternoon-slate.yml:165-173` fails
on any ESCALATE so red is normal there and timeouts show as "cancelled"
`[recon]`; `escalations.py` only reads column-0 lines and treats the 89%
STRONG-tier drift and the readiness battery as KNOWN, so they fail nothing
(`docs/ESCALATIONS.md:44-45`) `[recon]`; `git add <list> 2>/dev/null || true`
in `daily_loop.sh:606` and `afternoon_slate.sh:187` would stage nothing if one
path were missing `[recon]`; 32 `except JSONDecodeError: continue` sites,
including settlement and grading `[recon]`; `lib_shrink_guard.sh:162-171`
warns at 95 MiB but never blocks `[recon]`; the schedules depend on this PC
being awake `[verified]`; `live_window.py:1178` ignores a failed push `[recon]`.

## G. Usefulness to a serious bettor

What exists: a public, hash-chained W/L record; a nightly card; a de-vigged
price comparison (`/opportunities`, `/odds`); prop and NFL value screens. What
does not: a validated probability (the registration itself calls the model's
number unvalidated, `PREREG_CARD_V2.md:166-183` `[recon]`); any measure of
closing-line value; any statement of what changed, why, what contradicts it,
whether it is priced in, or how stale the inputs are; fresh prices below the
floor; a working deployment (staging OOM, production absent); UFC grading.
`[inference]` today the honest product is the public grading ledger plus the
market-consensus tools; the picks are an experiment being graded in public,
not a product with evidence of edge, and the copy should say exactly that.

## H. Kill / keep / repair / build

| Item | Verdict | Why |
|---|---|---|
| Decisions ledger as one 100 MB git file | REPAIR (slice 1) | rejected pushes destroy forward evidence |
| Delayed settlement, postseason ingest, record UI (local commits) | KEEP, activate (slice 2) | reviewed; needed before the first postseason settlement |
| Postseason counted in the public record | REPAIR (slice 2) | contradicts PREREG 11.1 |
| Daily-loop snapshot that bypasses the floor; green-while-dry capture | REPAIR | policy says stop at the floor; monitoring must say so |
| UFC "graded in public" copy; LAUNCH_KIT record quote; Bet Check promotion; `MODEL_BASIS` sentence; "2023-2024 pre-registered" | REPAIR (copy) | false today |
| `batter_runs_scored` on the V2 prop board | KILL | outside the registration and unsettleable |
| 12 F5 genomes and F5 close capture | KILL | the family produced zero survivors; spends credits |
| Paper arms A2-A4 | PARK | never wired; window closed; revisit in the 2027 prereg |
| Tennis capture, BALLDONTLIE | PARK | dead feed, trial expired |
| Section 16 fingerprint, params and shadow-pin record | REPAIR (erratum) | the counted sample must be defined |
| Market-consensus tools (`/opportunities`, `/odds`) | KEEP | honest by construction |
| Per-request materialisation of the decisions ledger in the API | REPAIR | inference: the staging OOM |
| Registry coverage (NFL V2, UFC, value shadow, F5, totals, card V2) | BUILD | one ledger for every registered policy |
| Market-baseline evaluation of every public policy | BUILD (research prereg #1) | "better" needs a named metric against a named baseline |

## I. Five highest-leverage next actions

Ranked by expected evidence value, cost, risk and reversibility.

1. Ledger hot/cold persistence, active on origin before 09-29 about 09:00Z.
   Evidence value: stops losing every appended decision; cost: the
   implementation exists and its 96 tests pass, validator pending; risk: low
   with the byte-identity proof; reversible by one revert.
2. Push the reviewed release (delayed settlement, re-entrant settle,
   postseason ingest, record UI) plus the postseason not-counted rule before
   the first Wild Card settlement on 09-30 about 10:10Z. Value: correct
   grading and an honest record in October; cost: merge plus a full suite
   compared by test identity; risk: medium (activation); reversible per
   commit.
3. Capture and credit truth: a forward-capture ESCALATE gate, a floor-aware
   daily-loop snapshot, health that reads the floor. Value: monitoring that
   cannot lie; cost: small; risk: low. The floor itself is an owner decision.
4. Deployment: stream or index `decisions_for_date` instead of materialising
   the ledger, then a green staging deploy; production remains an owner
   decision. Value: a product anyone can open; cost: medium; risk: low.
5. Registration integrity and copy: a section 16 erratum for the fingerprint,
   params sha256 and V1 shadow pin; remove `batter_runs_scored`; register NFL
   V2, UFC V1 and the value shadow; retire the F5 genomes; fix the false copy.
   Value: a defined counted sample and truthful claims; cost: small; risk: low.

Then research prereg #1: de-vigged market consensus, base-rate and Elo
baselines against every public policy on log loss, Brier and its
decomposition, calibration, coverage, price advantage at recommendation time,
CLV where a valid close exists, and ROI with game/date-clustered bootstrap
intervals. Zero survivors is an acceptable outcome.

Decision waiting on the owner: the credit floor. The balance is 4,941 against
5,000 and the reset has not appeared in the log; the Wild Card round is priced
only if the floor is lowered through the reset or the quota resets first.

## Addendum, later on 2026-09-28

- The staging OOM is measured, not inferred any more: the startup warm-up
  pass peaks at 1,479 MB because whole stores are materialised and filtered
  afterwards (tennis board +1,295 MB to keep 2,475 rows; NFL card +753 MB;
  `/today` unwindowed +523 MB; the engine join +351 MB). Streaming with the
  same filters brings the pass to ~540 MB with byte-identical payloads on
  twelve route/date pairs (`docs/audit/2026-09-28/api_memory_profile.md`)
  `[verified]`.
- `src/report/daily_record.py` `day_record()` returns differently ordered
  content across two fresh processes on unmodified code and data (hash-seed
  dependent iteration; identical within one process) `[recon]`. A
  reproducibility defect on a public surface; not fixed in this cycle.
- `.github/workflows/deploy-staging.yml:206-212` waits up to six minutes for
  a warm-up pass and then continues without failing, so a process that
  never completes warm-up reaches the page checks anyway `[recon]`. Default-
  branch YAML; owner action.
