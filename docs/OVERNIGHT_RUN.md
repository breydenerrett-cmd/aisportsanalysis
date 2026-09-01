# Overnight run log

**Started 2026-08-28.** Chat stays short; this is the detail.

## 2026-08-29 update

Stage 1 (point-in-time rebuild) and Stage 2 (full 2023-24 discovery rerun)
are both DONE — see `docs/RESULTS_STAGE2.md`. Zero of 8 detectors cleared
FDR + effect-size gates on clean data. V1 concluded null. Stage 4 (2025
tuning) is gated open but empty: no candidate exists to tune.

Forward ledger (Stage 7, continuous): 32 games across 2026-08-28/29, 15
settled, 17 pending. Verdicts: 29 no_play, 2 flagged (first candidates
flagged since forward tracking began), 1 market_unavailable. No graded
outcomes yet — settled games haven't been scored against predictions
because the prediction log requires the game to be final; grading run
2026-08-29 shows 7 pending, 0 graded. First decided mismatch flag: 0-1
(insufficient sample, as expected this early).

Statcast ingest confirmed DONE (2026 season: 39 windows, 593,336 rows,
0 failed). No further Stage 1 rewiring needed — already complete.

**Research Family V2 opened and closed the same day.** Reframed away from
baseball knowledge (V1's dead end) toward market structure: five pre-registered
hypotheses about whether the market misprices itself, all testable on data
already on disk. Zero credits spent. See docs/RESEARCH_V2.md for the
pre-registration and docs/RESULTS_V2.md for the full tables.

Result: zero survivors. M5 null, M2 inconclusive, M1 null, M3 debunked after
looking significant, M4 underpowered. Two families, thirteen hypotheses, none
standing.

New this run: `src/research/` (price-path harness plus one module per
hypothesis), `src/research/f5_store.py` (free MLB StatsAPI linescore ingest --
181 dates, 2,512 games, 0 odds credits), 27 tests. 1,038 green.

Open question for user: whether to fund a denser forward snapshot grid. M1 and
M2 both died on sampling resolution rather than on evidence, and a 15-minute
grid across the live window costs 132 credits a day (~4,400 for the rest of the
season, 8% of the 53,155 remaining). It is a recurring cadence, so it waits for
approval.

## Status

| | |
|---|---|
| **Demo** | **working** — `artifacts/demo_latest.html` |
| Tests | 918 passing |
| Detectors | 11 registered, family of 21 hypotheses frozen |
| Credits | 46,700 spent, **53,332 remaining** |
| Odds backfill | **complete** — 1,800 snapshots, 0 failures |
| First-five backfill | **complete** — 661 of 732 candidates (90%) |

## How to open the demo

    python -m src.cli brief --date 2026-08-28 --f5

Writes `artifacts/briefing.html`; double-click it. Or open the tracked snapshot
`artifacts/demo_latest.html`. No server, no network, no dependencies.

Flags: `--no-odds`, `--no-weather`, `--no-matchups` (skips the ~270 batter-vs-
pitcher calls), `--f5` (buys first-five prices, ~2 credits a game).

## What works end to end

**The page** — every game, findings ranked in plain language, a "worth looking
at" summary across the whole slate, full drill-downs, an evidence label on every
claim, missing data rendered as missing.

**The detectors**, with live examples from this run:

| Detector | Live output |
|---|---|
| Implied bullpen | *The market gives BOS 4.4 points of win probability from innings 6–9* — the full-game minus first-five gap is the market's own bullpen opinion |
| Platoon mismatch | *TOR's starter allows .817 OPS to lefties against .571 to righties, and KC is starting 7 of 9 left-handed hitters* |
| Pitch mix | *SF's starter throws his sinker 34% of the time, and AZ's lineup is at .400 wOBA against that pitch* |
| Thin matchup (debunk) | *Mookie Betts is 7-for-18 lifetime against tonight's starter. That is 18 at-bats and it means nothing* |
| Bullpen workload | *Justin Topa threw 34 pitches yesterday* |
| Stale book | *betrivers has PIT 1.4 points cheaper than the 11-book consensus* |
| Travel | *SEA flew 2,066 miles east across 2.9 time zones* |
| Run environment | *94F in Anaheim against a typical 74F* |
| Bullpen exposure | *DET's starter averages 4.17 innings, so 4.8 go to the pen* |
| Starter mismatch | *2.62 FIP against a league 4.20* |
| Lineup vs starter | fires only above 60 combined career at-bats |

## Data on disk

| Set | Size |
|---|---|
| Game results | 9,291 games, 2023–2026 |
| Pitcher game logs | 40,289 appearances, all four seasons |
| Bullpen appearances | 1,004 from boxscores |
| Pitch arsenals | 1,071 pitchers, 956 hitters |
| Handedness, splits | cached per player |
| Historical odds | **complete** — 1,800 snapshots, 7,439 games matched to a near-closing price |
| Historical first-five | 661 games (2023: 265, 2024: 189, 2025: 207) |
| Scanner candidates | 732 of 7,287 games (10.0%) |

## Backfill validation

Closing-price matching across all three seasons, measured after the run:

| Season | Snapshots | Games matched | Median gap to first pitch | Within 3h | Books/game |
|---|---|---|---|---|---|
| 2023 | 600 | 2,475 | 84 min | 74.5% | 18 |
| 2024 | 600 | 2,472 | 85 min | 74.0% | 12 |
| 2025 | 600 | 2,492 | 84 min | 75.1% | 11 |

Three snapshots a day turns out to be enough for a usable closing proxy: the
median game's price was captured 84 minutes before first pitch, and three
quarters are inside three hours. The gap is stored per game, so an analysis can
drop the stale quarter rather than averaging it in unknowingly.

Book counts fall over time (19 in 2023, 11 in 2025) because the market
consolidated, not because coverage degraded.

## Bugs found and fixed this run

1. **Innings per start of 13.56** — total innings divided by start count, so a
   swingman's relief innings were attributed to his starts. Physically
   impossible, silently produced, and it fed a detector claiming the bullpen
   would barely be used.
2. **A home stand scored as surprising** — surprise is absolute distance from a
   baseline, so zero miles against a 1,200-mile threshold came out at 1.7 and
   reached the top-six summary.
3. **Totals rendered as dashes** — the market table only knew away/home columns,
   so a priced market displayed as missing data.
4. **Cold-air physics on a 94F night** — the explanation only runs one way.
5. **Afternoon games unmatched** — a single 22:50 UTC lookup cannot see a 1pm
   Eastern start, which was already over.
6. **First-five history starts mid-May 2023** — caught by a three-game pilot
   before the 15,000-credit run began. Costs zero credits to discover.

## Blockers, each with its reason

- **Wind direction** — `orientation_deg` is `None` for all 30 parks by design; a
  wrong bearing inverts the effect rather than muting it. Reported, never
  interpreted.
- **Reverse line movement** — needs public bet percentages, which no source we
  have provides. Marked blocked rather than faked from price movement.
- **Steam** — three snapshots a day cannot support the claim.
- **Historical splits and arsenals** — season-to-date, so safe live and a leak
  historically. `assert_point_in_time` raises; game-log reconstruction needed.
- **Lineup handedness before lineups post** — most of a day has no lineups, and
  that is a normal state rather than a failure.

## First research result

Q5, blocked since the project began, is answered. On 454 candidate games from 2023–24
with stored first-five prices:

| | Games | Share |
|---|---|---|
| Passes the market screen | 220 | 48.5% |
| Screened out as already priced | 88 | 19.4% |
| **No first-five price offered at all** | **136** | **30.0%** |

The screen rejects about 29% of the candidates it can judge, so it is doing real
work rather than rubber-stamping.

The larger finding is the row nobody went looking for: **more than a third of
flagged games have no first-five market on the board**. The scanner routes to a
market that, for those games, does not exist. That caps the realistic fire rate
well below the 10% talent-bar rate, makes the full-game line the fallback for
those games — needing its own screen rather than one designed for a conditional
price — and means forward logging must record *market unavailable* as distinct
from *no play*.

No outcomes were read: this counts availability and screen rates only.

## Unfinished research, ranked by expected value

1. **Grade the implied-bullpen disagreement against first-five closes.** The
   most original idea here and now the data exists to test it.
2. **Rebuild splits and arsenals point-in-time from game logs.** Unblocks every
   historical evaluation of the platoon and pitch-mix detectors, which are
   currently live-only.
3. **Discovery pass on 2023–24** across all eleven detectors, with the
   hypothesis family pre-registered first.
4. **FDR machinery and effect-size gates**, before any result is read.
5. **Freeze the decision policy** — eligible markets, which book's price counts,
   stale-line tolerance, no-play conditions. A detector is not a strategy.
6. **Third-time-through-order from pitch-level data** — the one priority
   detector still approximated rather than measured.
7. **Umpire assignments** — source not yet verified.
8. **Clustered bootstrap confidence intervals** — selections on one slate are
   correlated, and treating them as independent overstates certainty.

## Not done, and why

- No backtest has been run. Discovery has not started, so nothing has been
  measured against outcomes and no result exists to report.
- The 2026 confirmation set has not been touched, and must be evaluated once.
- No detector has been validated. Every threshold on the page is a written-down
  guess, which is what the evidence labels say.

## 2026-08-31 update — validation gate opened, V4 run, zero survivors

The 7-check machinery gate closed its one failure: the battery originally
PASSED the real M3 false positive. Two fatal rules were amended as general
skeptical rules (no M3-specific logic), validated against a six-case
synthetic generality matrix, an old-vs-new shadow comparison over all 15
reproducible prior candidates (only M3's verdict changed), and an
independent skeptical adjudication that re-reproduced everything and
returned gate_open=true with two recorded, non-blocking concerns. Battery
rules frozen at RULES_VERSION 2.0.0 with a content fingerprint in every
verdict. Full story: docs/VALIDATION_GATE.md.

The funnel gained interaction features (a*b products per side). V4 — six
coverage-ranked unit-vs-weakness interactions, thresholds set from feature
distributions only — was registered frozen and run as one batch:
**zero survivors** (3 wrong-direction screens, 2 replication sign flips,
1 battery kill at p=0.45). Third empty family; 24 pre-registered hypotheses
total against the h2h moneyline. docs/RESEARCH_V4_EXPLORATORY.md has every
loser.

Forward lane: daily loop ran clean for 2026-08-31 (12 ledger entries, all
no_play); hourly dense grid had a long gap while the session was held in
plan mode — roughly 17:15 through 01:15 UTC's firings executed late or
found no game in window (one run: 0 captures, stopped early). Missed
capture windows are gone and noted, not backfilled.

## 2026-08-31, later — public-projection benchmark scouting (lane B)

Question: can any FREE public MLB projection be honestly benchmarked
against the closing line for 2023–24? Answer: **no external source
qualifies.** FanGraphs game odds are shown live and never archived;
Baseball Reference/Savant win probabilities are retroactive situational
models, not pre-game forecasts; FiveThirtyEight's Elo was frozen mid-June
2023 (no 2024) and its canonical CSV is dead, with the only mirror stale at
2018; free odds archives stop at 2021; tout sites' "past predictions" are
self-attested. Every route fails the replayability test the news layer's
docstring states.

The one honest path: RECONSTRUCT a public-style projection point-in-time
from data already in the repo — a pitcher-free Elo (results-only, zero
lookahead) scored by log-loss/Brier against the de-vigged closes already
held for 2023–24. Queued as its own small pre-registered benchmark;
expected result, stated in advance, is that it does NOT beat the close.

## 2026-08-31, continuous-autonomy session — audits, probe, builds

**Timestamp audit (V3 gate):** every event class is grade C/D today; four
classes (lineup_posted, starter_scratch, hitter_scratch, il_roster_move)
reach grade B forward once a polling store records our own fetch times.
Historical replay is unsupportable (transaction dates are day-only, stored
lineups are date-only, historical odds sample 3x/day so brackets are 6-15
hours). Excluded from V3: reliever_status (no announcement source), roof
(no feed). CRITICAL capture defect found: the forward snapshot store keeps
ONE book per event (96% fanduel) because normalize() collapses the payload
-- first-mover/consensus/stale measurements are impossible on it. V3's
clock starts when the multi-book store and rosterwatch both run.

**Grid/ledger audit:** ledger append-only verified through git history, all
45 settlements join, zero orphans. Defects: closing=null in every
settlement (cli never threads it -> no CLV from the ledger); 08-30 rec rows
carry no prices (briefing ran with no snapshot on file); 32 of 58 window
games had zero observations in their last 3 pre-pitch hours (the plan-mode
outage plus cadence).

**Market probe (24 credits; balance 53,083):** F5 h2h 5 books forward at
1cr/event; HISTORICAL archive has 12 books on a 5-minute grid at 10x;
alternates 7 books with full ladders at 1cr (best info/credit); K props
thin. Policy written: docs/COLLECTION_POLICY.md.

**V3 frozen** (docs/RESEARCH_V3_TIMING.md): four admitted classes,
denominator 4, forward-only, measurement core + lead/lag aggregation built
and tested. **Elo benchmark published** (docs/BENCHMARK_ELO.md): the close
beats a clean public-style Elo by 0.8 log-loss points/game, p=0.0003.
**Analyzer matchup depth shipped** (23 tests).

**In flight:** the two capture builds (multi-book store; rosterwatch
polling store) hit the session usage limit (resets 05:10 UTC) and are
scheduled to resume right after.

## 2026-08-31 ~06:00 UTC — V3 capture infrastructure LIVE

The capture builds landed (after one usage-limit delay): every dense
capture now persists all books' h2h to data/processed/odds_multibook.jsonl
(same payload, zero extra credits); dense gained a T-25 close pass with a
bounded F5 first-five fetch (≤6 events, 1 credit each) and missed-window
reporting; settlements carry their closing observation or an explicit
reason; rosterwatch polls probables/lineups/transactions into
data/watch/ with our own fetch times — hourly via the renamed "Forward
capture: watch + dense grid" trigger, every 15 minutes during dense runs.
First live poll: 12 probables, 1 transaction. V3's event clock starts
today; class floors are 30 events each. Suite: 1,319 tests green.

## 2026-08-31 ~07:00 UTC — Analyzer complete through A4, resilience, V3 runner

Shipped this stretch: any-matchup mode ('analyze --away X --home Y', real
games resolved point-in-time, hypotheticals rendered with named gaps);
starter_velocity_gap matrix feature (injection-tested; batted-ball share
correctly NOT built — the store carries no bb_type, so a re-ingest with
the column is running in the background, ~180 windows, free); ledger
resilience (write-time dedup with the priced-repair exception, first-
priced recommendation rule, unsettled-past-date alerting); the V3 timing
report ('timing' command — counts below the 30-event class floor, pre-
registered tables only at it; first event already accumulating); and the
narrative pass over all eleven detector claims (samples inside every
sentence, mechanism clauses, warnings kept load-bearing).

The two-tools plan's Analyzer items A1–A4 and Ranker items B1–B3 are all
shipped; the Ranker page remains gated by test. Suite: 1,377.

## 2026-08-31 ~07:30 UTC — pitch store re-ingested with batted-ball type

All 180 windows re-fetched from Savant (free) with bb_type in the kept
columns: 2,737,968 rows, exactly matching the old store, zero failed
windows (one mid-transfer hangup killed the first attempt at window
seven; the retry net now catches IncompleteRead and the resume cost one
window). bb_type present on 17.4% of pitches -- the balls-in-play rate,
so coverage is effectively complete. Old store preserved locally as
statcast_pre_bbtype. This unlocks the batted-ball/contact profile
features for the V5 pre-registration and the Analyzer.

## 2026-08-31 ~08:00 UTC — V5 run and published: zero survivors

Idea to published result in under an hour on the trusted machine: the two
new features went through coverage measurement, a three-hypothesis
pre-registration (docs/RESEARCH_V5_STUFF.md), registration, one batch, and
full publication. All three died at 2024 replication, two by sign flip --
the same screen-then-flip shape V4 showed. Running total: four families,
27 pre-registered hypotheses, zero survivors. The live research lanes are
now the ones the market cannot trivially price: V3 information timing
(accumulating) and softer markets (F5 closes accumulating via the dense
close pass). Another season-level feature family needs a mechanism the
market plausibly CANNOT price, not merely one it might not.

2026-08-31 14:15Z — health monitor shipped (`python3 -m src.cli health`; 20
tests). Its first real finding investigated: lineups_watch.jsonl has zero
lineup rows — verified NOT a bug. The hydrate=lineups fetch returns full
lineups for yesterday's completed slate (14/14 games); today's store simply
started at 05:42Z and lineups had not posted yet at 14:11Z. Expected to
bracket normally from ~14:35Z on. Multibook store starting 08-31 and absent
f5_close.jsonl are the same story: stores younger than a day.

2026-08-31 red-team round (commit 72c43be): six REPRODUCED collection bugs
fixed with regression tests; the two worst were losing closing lines nightly
(dense blind to the West Coast slate after 00:00 UTC; game_key merging a
night game with the next matinee, letting Saturday's close settle Sunday).
Three written up, not fixed: (7) a corrupt ledger line halts recording until
a human intervenes (writer hardened; loud halt kept deliberately), (8)
closing_observation ignores book_last_update so a suspended book can supply
"the close" (changing it changes closing semantics — needs a decision),
(9) grade-B poll markers don't record which date they polled (near-zero
after the rosterwatch date fix; proper fix = stamp polled date on markers).

2026-08-31 product red-team (commit 1986495): nine rendering honesty defects
fixed with tests (suite 1475 -> 1507). Worst: the Ranker banner claimed every
row "beats the consensus" above an all-negative board; hypothetical matchups
rendered as real games in the saved artifact. Written up, not fixed (queued):
bullpen_workload's "sample" is a period not a denominator (src/detect);
thin-starter warning overreaches onto adequately-sampled velocity; one market
read from two stores (detector vs multibook) shows two book counts; the
synthesis suppressed-items audit trail is computed but never rendered
(product call, not defect); "<20 IP" parses as a 20-IP sample.

2026-08-31 day summary: master-directive day complete. Architecture (scripts
own collection, Opus workers execute, four-horizon roadmap, RESUME/RUNBOOK),
research catalogue (73 ideas), synthesis layer, slate health monitor,
collection red-team (6 reproduced bugs), product red-team (9 + 4 follow-up
honesty fixes), closing staleness + marker dates, pre-event relevance tiers,
V4 reproducibility audit (exact). Suite 1,396 -> 1,587 green. Remaining open
write-ups: one-market-two-stores unification (queue 7); corrupt-ledger-line
halt semantics (deliberate, documented).

2026-08-31 decisions: public-projection benchmark queue item removed -- the
dead end (no honestly replayable free source) and the Elo reconstruction
already answer it (docs/BENCHMARK_ELO.md). Ledger corrupt-line halt KEPT
deliberately: a tolerant dedup scan risks double-recording after a crash,
worse for evidence than a loud halt that names its line.

2026-08-31 resume audit (post usage-limit). Three concurrent forward-evidence
failures found, none of which raised an error anywhere:
1. data/processed/* gitignored -- five days of h2h snapshots and every
   multi-book board existed only on one ephemeral container's disk. Fixed
   56b8ccf; forward captures are now tracked as evidence.
2. f5_close.jsonl never existed despite the close pass running for days.
3. V3: 33 admissible events, 0 measurable (transactions carry no team;
   lineup events map to no game).
Also: results store has 251 unfetched dates inside its span; health monitor
printed "8 of 7 games have a posted lineup" (two different denominators).
Four workers dispatched under workflow wf_be70a6ab-e3e, each verified
adversarially. Lesson recorded in ROADMAP: check stores for ROWS, not for
the absence of errors.

Brey also proposed an Evolution Lab (historical replay + evolving strategy
population). Assessed before implementation in docs/EVOLUTION_LAB_ASSESSMENT.md
-- reframed around placebo-calibrated enumeration rather than naive genetic
search, with two decisions referred to Brey (the 2024 holdout question; the
prop-listing policy gap).

2026-08-31 evening results:
- PHASE 2A (39d6003): our feature set carries NO linear incremental
  information beyond the close. Pre-registered, market log-odds as offset,
  train 2023 / eval 2024. L2 is +0.0000412 log-loss/game WORSE than the
  close (clustered p=0.914); L1 selects the empty model, all 18 coefficients
  exactly zero. Close reproduces BENCHMARK_ELO 0.67275 to the digit via an
  independent join. This is the strongest statement the project has made
  about its own features, and it cost one worker-day rather than the lab.
- PROBABLE-PITCHER LEAK (0039f15): stored historical probable disagrees with
  the actual first-pitch starter on only 0.10%/0.08% of sides -- 12-41x too
  clean versus the estimated scratch rate. The store absorbed scratches, so
  starter-conditioned historical features knew who really pitched. Exposure
  2.3-7.6% of the replay universe. Sign favours the features and all families
  produced zero survivors, so the nulls STRENGTHEN. Forward path unaffected.
- PROP AUDIT LIVE (6873e19): cost gate passed at exactly 1 credit/fetch,
  4 credits spent, SEVEN books list pitcher strikeouts (design assumed 3-4).
- EVOLAB CORE (39d6003): 11,088 genomes sweep in 51ms via integer bitsets.
  The build found two holes in my design: a negative `weight` was a sign-flip
  hole defeating the frozen registry, and a genome validated under one
  registry could silently bet the other side under another. Both refused now.
- V2 REPRODUCIBILITY (adc04c6): all five hypotheses exact; M3 still killed at
  fingerprint ac74c7a7f715f9ec.
- Competitive-intelligence lane opened (Brey): four Sonnet research workers
  on AI-prediction, sharp/odds, props/tracking, and customer pain.

2026-08-31 21:00Z V3 state after the mappability repair. The report now
distinguishes the two unmappable causes instead of lumping them:
- lineup_posted 18/30 admitted, unmappable ONLY because the games have not
  been played yet (later than the last settled results date). This is the
  healthy case and resolves on settlement. The lane is in better shape than
  the pre-repair reading suggested.
- transaction_first_seen 20/30 admitted, unmappable because those rows
  predate club capture. Permanently unmappable, kept as history rather than
  deleted or backfilled; rows written from now on carry the club.
Also landed: bootstrap determinism fix (one published CI superseded, recorded
as errata with the original left standing), P4 reclassified out of the placebo
ceiling as a dispersion diagnostic, evolab statistics validated both ways.
F5 close pass shipped with coverage 3-of-15 to 15-of-15; two reproduced
defects in its miss-detector and credit cap are being fixed now.

## 2026-09-01 00:00-01:30Z — paid-beta backend waves (build loop live)
Design moved to a separate Claude Design session (directions-v1 archived).
Waves 1-3 landed and pushed, each unit tested before commit: Bet Check /
Games / What Changed / Odds APIs; auth (invite tokens, hashed at rest) +
My Bets; deploy (Dockerfile, /health, redacting request log, smoke);
red-team round (fixed INVERTED price direction in Bet Check bottom line,
invite race, overflow 500s; then gated the whole game surface behind
auth); caching/freshness (stale-served-with-flag); contract tests +
analytics (hashed users only); Clerk seam + Stripe test-mode provider +
billing persistence; My Bets settlement in the daily loop; scripts/ci.sh
green end to end. Brey decisions recorded (Clerk/Stripe/staging/temp
disclaimer). Wave 4 in flight: provider timeout/retry + load smoke;
structural reference client. Suite 2,655. V3: 0 measurable events, floor
30 - accumulating. Hourly captures on schedule (00:02Z committed;
00:16Z run still polling close windows).

## 2026-09-01 ~02:30Z — forward-store audit verdict + app-db cleanup
Write-blocker + sha256 audit: all seven forward stores took ZERO test
writes and hold no fixture artifacts (earlier report wrong about which
store). Real leak: 1,593 test analytics rows in the gitignored app db
via record_event_safe's silent default path. Containment now structural
(tests/__init__.py redirect + write blocker + end-of-suite fingerprint,
commit 8b08c59). Cleanup executed: rows under sha256("1") — a synthetic
hash no DB-assigned user id can produce, zero real users exist —
quarantined to data/app/quarantine_2026-09-01_test_analytics.json
(kept, gitignored dir) then deleted in one transaction. Queued
observation (hypothesis, unchased): odds_multibook holds post-first-
pitch rows (in-play prices) with CLOSING_GRACE_SECONDS=0 — needs its
own task before anything treats that store as closes-only.
