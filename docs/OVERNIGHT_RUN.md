# Overnight run log

**Started 2026-08-28.** Chat stays short; this is the detail.

## 2026-09-01 update — staging outage (Launch Ops owns) + F5 store audit

~13:35 UTC the staging app stopped answering (TLS reset at the Fly edge;
proxy/egress verified fine — fly.io and github.com reachable through the
same path). This cloud session's Fly token did not survive the container
recycle, so per Brey's direction LAUNCH OPS OWNS the restoration,
root-cause, and self-recovery verification; this session does not touch
Fly and does not redeploy. Data plane unaffected throughout — hourly
captures green all day.

ROOT CAUSE (Brey, ~18:30 UTC): Fly BILLING — no card on the account, so
Fly suspended the app; that is why the edge accepted TCP but reset TLS.
Card now added; Launch Ops is restoring linehound-staging. Note for the
record: the Fly dashboard also shows an obsolete `aisportsanalysis`
deployment path tracking the old Cowork branch — Launch Ops is ignoring
it; nothing in this repo references it, and it should not be used.

F5 close store structural audit (rows-not-errors rule): 94 rows, 11 games
over 2 days, one close capture per game, 8-9 books/game, zero duplicate
(book, observed) rows, every observation pregame, market
h2h_1st_5_innings only. The 8-game daily budget cap is binding as
designed on 15-game slates. No defect; the ~2-week accumulation toward
the lane F review is safe. Structure only — no prices or movement were
analysed (that stays behind the pre-registration gate).

## 2026-09-01 update — season-end credit gate on the daily snapshot

Closed the one non-zero off-season cost `docs/SEASON_END_PLAN.md` §2 found:
the daily loop's `do_snapshot` (and the standalone `snapshot` command) billed
the whole-sport odds call every day regardless of whether MLB had any games,
so a slate-less off-season day cost ~3 credits for nothing. Both now gate on
`dense.any_game_scheduled()` — the same FREE yesterday/today/tomorrow schedule
check the hourly `dense` loop already uses. A confirmed-empty slate skips the
paid capture; a schedule OUTAGE (`None`) still captures, because missed
movement on a live day is unrecoverable and an outage is not proof the season
is over. Regression tests in `tests/test_dense.py` (`AnyGameScheduledTests`)
and new `tests/test_cli_snapshot_gate.py`. Full suite green. No behavior
change in-season (there is always a game today); the effect is entirely at the
season boundary and through the winter. Staging unaffected. Launch Ops (Stripe)
and the design session untouched.

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

## 2026-09-01 ~02:30Z — forward-store audit verdict + app-db cleanup
Write-blocker + sha256 audit: all seven forward stores took ZERO test
writes and hold no fixture artifacts (the earlier report was wrong about
which store). Real leak: test analytics rows in the gitignored app db
via record_event_safe's silent default path. Containment now structural
(tests/__init__.py APP_DB_PATH redirect + write blocker + end-of-suite
fingerprint, commit 8b08c59). Cleanup: 1,583 rows under sha256("1")
quarantined to data/app/quarantine_2026-09-01_test_analytics.json then
deleted in one transaction. 15 rows under sha256("2") — equally
synthetic (no users table exists; zero real users) — REMAIN: the
permission classifier blocked further deletes, so they are left in
place, identifiable by that exact hash, for Brey to remove or filter.
Queued observation (hypothesis, unchased): odds_multibook holds
post-first-pitch rows (in-play prices) with CLOSING_GRACE_SECONDS=0 —
needs its own task before anything treats that store as closes-only.

## 2026-09-01 03:48Z — STAGING IS LIVE
https://linehound-staging.fly.dev deployed via the GitHub Actions
workflow (Brey added FLY_API_TOKEN; manual dispatch). /health ok with
all stores present; full remote smoke PASS end to end (auth gating,
invite mint, authed slate 200, clean 404). Volume app_data (iad),
APP_ADMIN_TOKEN set. Session-container CLI deploys remain blocked
(depot TLS via proxy; classic builder unauthorized for app tokens) —
Actions is the deploy path. Next: Stripe test keys -> webhook at
https://linehound-staging.fly.dev/billing/webhook -> dry-run purchase.

## 2026-09-02 00:57Z build-loop tick
- V2 capability reconciliation delivered and pushed (design/linehound-v2/
  RECONCILED_CONTRACT_CURRENT_HEAD.md, d333a67); false commerce copy
  (refund/one-click/instant-email) removed from pricing.js + landing.
- V3 still gated: 28 measurable transaction events / 16 lineup vs the
  30 floor. F5 review time-gated ~09-14. Queue items 4-5 await Brey.
- Lane C started: adversarial functional QA worker attacking the rebuilt
  frontend locally (routes, auth, free-check, contracts, honesty sweep).

- 2026-09-02 21:04Z–22:00Z: the session container restarted four times (21:04, ~21:25, ~21:43, ~21:55), each time killing the running hourly capture mid-dense. Captured rows on disk were committed by hand after each restart (commits 85782ef, bd5d65d and this one); the 21:15 trigger's message was dropped by the first restart and the run was started by hand. Some 15-minute dense slots in the 21:xx window were missed; nothing was reconstructed. Cause not identified (memory was 0.6 GB of 16 GB in use).
- 2026-09-02 22:18Z–22:49Z: a capture launched detached (setsid nohup) as a survival test also died before its commit step; restarts continue roughly every 15–30 minutes. Rows on disk were committed by hand again. From here the hourly trigger runs capture as usual and any rows an interrupted run leaves on disk are committed at the next check; the missed dense slots are real gaps.

- 2026-09-03 02:30Z–04:15Z: Phase 0 started under the owner's approval with
  amendments (docs/ARCHITECTURE_BETTING_ENGINE.md §9.1). Sixteen lanes
  integrated on the branch in one pass (39 commits, ~26K lines): L0 raw-first
  odds capture + all-books persistence; GUMBO boxscores + prop settlement
  rules; budget guards, drop order and cadence SLO; timing instrumentation
  (the "51 ms" claim struck); universal market record + catalogue + L1
  projection (56,680 observations backfilled, store ~36 MB, gitignored until
  partitioned); as_of stop-at-T reader with the degraded-information replay
  label; hash-chained ledger v2 (v1 untouched, hash recorded); paper accounts,
  gates G-cadence..G7 and the pinned LOCK criteria; the engine waist
  (price-blind PROPOSE → PROJECT → ATTACK → RATE → RANK) with an equivalence
  run against evolab.decide on 7,742 genomes × 200 decision points, 0
  divergences; conformance + truncation differential library and a first
  adversary roster; free information-events layer (305 events from existing
  stores); SGP/parlay assessment (vendor has no SGP endpoint; team totals
  proposed next); vendor prop-history packet (no purchase). Batter-prop capture
  switched on behind the budget guards. The first two probes hit an
  already-started game (1 book, 1 outcome) and were retro-marked degenerate;
  the probe now requires a 45-minute lead. Full suite green at every merge
  (last: 3,710 OK before W6/W11). Capture ran throughout; no restart this
  window.
  04:09Z pre-game re-probe (first pitch 16:35Z): both batter families
  measured 5 credits/event, 4 books, 5 of 6 requested markets, 79 outcomes;
  PROBE_REQUIRED cleared for both. Credits 99,597 remaining.
- 2026-09-03 05:21:23Z: one real featured-odds provider call (10 events, 11
  books) wrote a raw L0 file but left no credit_log row, so the budget view
  under-counts today's spend by about 3 credits. Origin not traced (the
  checkpoint readers were told zero credits; the likeliest path is a
  fetch_normalized caller that bypasses creditlog). Follow-up: the raw writer
  should record the calling module, and every provider call should pass
  through creditlog. Raw file committed as real data.

- 2026-09-03 19:15Z and 20:15Z: both hourly forward-capture slots were MISSED.
  The session was integrating the vertical-slice lanes and did not run the
  script when the triggers fired; the windows are gone and are not
  reconstructible. Captures resumed at 22:44Z (late, in-window for the late
  games). Staging stayed healthy throughout. The slice work is exactly the
  kind of thing the owner warned must not consume capture: the daily loop now
  runs slate/settle/EOD unattended, but capture itself is still a Claude
  Routine, and this is the second time in-session work has cost live windows.
- 2026-09-04T10:09Z daily_loop: engine slate --date 2026-09-04 exit=2
- 2026-09-04T10:09Z daily_loop: engine settle --date 2026-09-03 exit=0
- 2026-09-04T10:09Z daily_loop: eod --date 2026-09-03 exit=0

- **2026-09-04 15:16Z and 16:15Z forward-capture windows MISSED.** The
  owner-approved T-2h normalization run (4,315 games, ~91 minutes, 16 resume
  attempts against a throttling provider) held the interactive session, so
  neither trigger fired. The 16:15Z window was recovered at 16:22Z; the
  15:16Z window is gone and is not reconstructible. Earlier windows that day
  (11:23Z, 12:29Z, 13:23Z, 14:23Z) committed with no odds rows -- those are
  legitimate quiet-hour no-ops, not misses: the newest odds file before the
  gap is 10:08Z because no game was inside the capture window. This is the
  third time in-session work has cost live capture, and the standing note
  applies: capture is still a Claude Routine, and externalizing it (task
  L25) remains the fix.
- **2026-09-04: forward capture SILENTLY BLOCKED ~10:08Z-17:2xZ (~7 hours).**
  Not quiet-hour no-ops, as an earlier note in this file guessed. The
  owner-approved ~47,000-credit historical F5 normalization landed in
  `data/processed/credit_log.jsonl` as today's spend, and
  `src/capture/budget.py`'s `spent_today()` sums every delta for the UTC day
  regardless of band, so `can_spend()` tripped its 900/day LIVE-CAPTURE
  envelope on every fetch: `dense.run: skipped: daily envelope (spent=73658,
  requested=3, envelope=900)`. The credit floor was never the issue --
  balance ~25,700 against a 5,000 floor.
  Two defects, both real: (1) `docs/RESOURCE_POLICY.md` defines the capture
  reserve and the historical/backfill band as SEPARATE, and the envelope
  check did not honour that separation, so a growth-band purchase starved
  the one stream that cannot be bought back; (2) the skip path crashed with
  `KeyError: 'floor'` at `src/cli.py:1976` because the envelope-skip result
  carries no `floor` key, so the block surfaced as a traceback rather than a
  clean `ESCALATE:` line -- which is why no trigger ever alerted and the
  outage ran for hours unnoticed.
  Compounding error on my side: I checked `remaining_today()` (the monthly
  balance, healthy) and reported capture as fine. The envelope half is what
  gates fetching, and I did not read it.
- 2026-09-05T10:07Z daily_loop: engine slate --date 2026-09-05 exit=2
- 2026-09-05T10:07Z daily_loop: engine settle --date 2026-09-04 exit=2
- 2026-09-05T10:07Z daily_loop: eod --date 2026-09-04 exit=2
- 2026-09-05T10:4xZ manual: engine slate --date 2026-09-05 exit=0 after L1 repair (cli preflight ran before run_slate's L1 refresh; L1 had no live rows since 2026-09-03 18Z — 52,380 multibook + 6,354 snapshot + 302 f5_close observations projected by a manual l1.run). 2026-09-04 has no decisions (slate refused that day) — settle/eod for 09-04 correctly refuse; that day's slate is a recorded gap, not reconstructed.
- 2026-09-06T10:11Z daily_loop: engine slate --date 2026-09-06 exit=2
- 2026-09-06T10:12Z daily_loop: engine settle --date 2026-09-05 exit=2
- 2026-09-06T10:12Z daily_loop: eod --date 2026-09-05 exit=0
- 2026-09-07T00:04Z daily_loop: statcast --catchup exit=0
- 2026-09-07T00:04Z daily_loop: gamekey --date 2026-09-06 --end 2026-09-07 exit=0
- 2026-09-07T00:04Z daily_loop: engine slate --date 2026-09-07 exit=0
- 2026-09-07T00:04Z daily_loop: engine settle --date 2026-09-06 exit=2
- 2026-09-07T00:04Z daily_loop: eod --date 2026-09-06 exit=0
- 2026-09-07 01:0xZ — CUTOVER: first genuine `schedule` run of forward-capture succeeded (run 34071611931, 01:00:46Z → bot commit 0bc53ca "slot 01:02Z"); earlier 00:36Z slot was a dispatch by the local Parent (run 34070311873 → 2b2337b). The cloud fallback capture launched at 00:15Z (heartbeat then 67 min stale, no cron run yet) ran its 4-capture grid to 01:02Z, so the 01:00 window was captured twice (≈20 credits duplicated; balance 24,847 after). Its commit conflicted on the append-only stores and was resolved by union-merge (upstream first, local-only rows appended; 119 snapshot rows kept) as 4fc98fc. The cloud hourly capture routine is now FALLBACK-ONLY: it fires only when no bot commit / successful run exists in the last 45 min.
- 2026-09-07 03:3xZ — FALLBACK capture launched from the cloud session: external heartbeat 50 min stale (last bot commit c569bb3 at 02:46Z, a dispatch; no cron slot has fired since 01:00Z). No games inside the 180-min window at this hour, so expected paid spend ≈0; watch stores refreshed.
- 2026-09-07T05:23Z afternoon_slate: engine slate --date 2026-09-07 exit=2
- 2026-09-07T13:28Z daily_loop: statcast --catchup exit=0
- 2026-09-07T13:28Z daily_loop: gamekey --date 2026-09-06 --end 2026-09-07 exit=0
- 2026-09-07T13:29Z daily_loop: engine slate --date 2026-09-07 exit=0
- 2026-09-07T13:29Z daily_loop: engine settle --date 2026-09-06 exit=0
- 2026-09-07T13:29Z daily_loop: eod --date 2026-09-06 exit=0
- 2026-09-07T15:21Z daily_loop: statcast --catchup exit=0
- 2026-09-07T15:21Z daily_loop: gamekey --date 2026-09-06 --end 2026-09-07 exit=0
- 2026-09-07T15:22Z daily_loop: engine slate --date 2026-09-07 exit=0
- 2026-09-07T15:22Z daily_loop: engine settle --date 2026-09-06 exit=0
- 2026-09-07T15:22Z daily_loop: eod --date 2026-09-06 exit=0
- 2026-09-07T23:16Z afternoon_slate: engine slate --date 2026-09-07 exit=0
- 2026-09-07T23:30Z afternoon_slate: engine slate --date 2026-09-07 exit=0
- 2026-09-08T10:11Z daily_loop: statcast --catchup exit=0
- 2026-09-08T10:11Z daily_loop: gamekey --date 2026-09-07 --end 2026-09-08 exit=0
- 2026-09-08T10:11Z daily_loop: engine slate --date 2026-09-08 exit=0
- 2026-09-08T10:12Z daily_loop: engine settle --date 2026-09-07 exit=0
- 2026-09-08T10:12Z daily_loop: eod --date 2026-09-07 exit=0
- 2026-09-08T13:57Z daily_loop: statcast --catchup exit=0
- 2026-09-08T13:57Z daily_loop: gamekey --date 2026-09-07 --end 2026-09-08 exit=0
- 2026-09-08T13:58Z daily_loop: engine slate --date 2026-09-08 exit=0
- 2026-09-08T13:58Z daily_loop: engine settle --date 2026-09-07 exit=0
- 2026-09-08T13:58Z daily_loop: eod --date 2026-09-07 exit=0
- 2026-09-08T20:24Z afternoon_slate: engine slate --date 2026-09-08 exit=0
- 2026-09-08T20:57Z afternoon_slate: engine slate --date 2026-09-08 exit=0
- 2026-09-08T21:27Z afternoon_slate: engine slate --date 2026-09-08 exit=0
- 2026-09-08T21:57Z afternoon_slate: engine slate --date 2026-09-08 exit=0
- 2026-09-08T22:29Z afternoon_slate: engine slate --date 2026-09-08 exit=0
- 2026-09-08T22:57Z afternoon_slate: engine slate --date 2026-09-08 exit=0
- 2026-09-08T23:23Z afternoon_slate: engine slate --date 2026-09-08 exit=0
- 2026-09-08T23:59Z afternoon_slate: engine slate --date 2026-09-08 exit=0
- 2026-09-09T00:27Z afternoon_slate: engine slate --date 2026-09-09 exit=0
- 2026-09-09T00:56Z afternoon_slate: engine slate --date 2026-09-09 exit=0
- 2026-09-09T01:26Z afternoon_slate: engine slate --date 2026-09-09 exit=0
- 2026-09-09T01:57Z afternoon_slate: engine slate --date 2026-09-09 exit=0
- 2026-09-09T02:27Z afternoon_slate: engine slate --date 2026-09-09 exit=0
- 2026-09-09T02:57Z afternoon_slate: engine slate --date 2026-09-09 exit=0
- 2026-09-09T10:11Z daily_loop: statcast --catchup exit=0
- 2026-09-09T10:11Z daily_loop: gamekey --date 2026-09-08 --end 2026-09-09 exit=0
- 2026-09-09T10:13Z daily_loop: engine slate --date 2026-09-09 exit=0
- 2026-09-09T10:13Z daily_loop: engine settle --date 2026-09-08 exit=0
- 2026-09-09T10:13Z daily_loop: eod --date 2026-09-08 exit=0
- 2026-09-09T14:00Z daily_loop: statcast --catchup exit=0
- 2026-09-09T14:00Z daily_loop: gamekey --date 2026-09-08 --end 2026-09-09 exit=0
- 2026-09-09T14:02Z daily_loop: engine slate --date 2026-09-09 exit=0
- 2026-09-09T14:02Z daily_loop: engine settle --date 2026-09-08 exit=0
- 2026-09-09T14:02Z daily_loop: eod --date 2026-09-08 exit=0
- 2026-09-09T15:12Z afternoon_slate: engine slate --date 2026-09-09 exit=0
- 2026-09-09T15:44Z afternoon_slate: engine slate --date 2026-09-09 exit=0
- 2026-09-09T16:13Z afternoon_slate: engine slate --date 2026-09-09 exit=0
- 2026-09-09T16:44Z afternoon_slate: engine slate --date 2026-09-09 exit=0
- 2026-09-09T17:12Z afternoon_slate: engine slate --date 2026-09-09 exit=0
- 2026-09-09T17:43Z afternoon_slate: engine slate --date 2026-09-09 exit=0
- 2026-09-09T18:16Z afternoon_slate: engine slate --date 2026-09-09 exit=0
- 2026-09-09T18:42Z afternoon_slate: engine slate --date 2026-09-09 exit=0
- 2026-09-09T19:12Z afternoon_slate: engine slate --date 2026-09-09 exit=0
- 2026-09-09T19:43Z afternoon_slate: engine slate --date 2026-09-09 exit=0
- 2026-09-09T19:43Z afternoon_slate: engine slip --date 2026-09-09
- 2026-09-09T20:13Z afternoon_slate: engine slate --date 2026-09-09 exit=0
- 2026-09-09T20:13Z afternoon_slate: engine slip --date 2026-09-09
- 2026-09-09T20:48Z afternoon_slate: engine slate --date 2026-09-09 exit=0
- 2026-09-09T20:48Z afternoon_slate: engine slip --date 2026-09-09
- 2026-09-09T21:12Z afternoon_slate: engine slate --date 2026-09-09 exit=0
- 2026-09-09T21:12Z afternoon_slate: engine slip --date 2026-09-09
- 2026-09-09T21:43Z afternoon_slate: engine slate --date 2026-09-09 exit=0
- 2026-09-09T21:43Z afternoon_slate: engine slip --date 2026-09-09
- 2026-09-09T22:16Z afternoon_slate: engine slate --date 2026-09-09 exit=0
- 2026-09-09T22:16Z afternoon_slate: engine slip --date 2026-09-09
- 2026-09-09T22:43Z afternoon_slate: engine slate --date 2026-09-09 exit=0
- 2026-09-09T22:43Z afternoon_slate: engine slip --date 2026-09-09
- 2026-09-09T23:17Z afternoon_slate: engine slate --date 2026-09-09 exit=0
- 2026-09-09T23:17Z afternoon_slate: engine slip --date 2026-09-09
- 2026-09-10T00:01Z afternoon_slate: engine slate --date 2026-09-09 exit=0
- 2026-09-10T00:01Z afternoon_slate: engine slip --date 2026-09-09
- 2026-09-10T00:27Z afternoon_slate: engine slate --date 2026-09-10 exit=0
- 2026-09-10T00:27Z afternoon_slate: engine slip --date 2026-09-10
- 2026-09-10T00:56Z afternoon_slate: engine slate --date 2026-09-10 exit=0
- 2026-09-10T00:56Z afternoon_slate: engine slip --date 2026-09-10
- 2026-09-10T01:26Z afternoon_slate: engine slate --date 2026-09-10 exit=0
- 2026-09-10T01:26Z afternoon_slate: engine slip --date 2026-09-10
- 2026-09-10T01:57Z afternoon_slate: engine slate --date 2026-09-10 exit=0
- 2026-09-10T01:57Z afternoon_slate: engine slip --date 2026-09-10
- 2026-09-10T02:26Z afternoon_slate: engine slate --date 2026-09-10 exit=0
- 2026-09-10T02:26Z afternoon_slate: engine slip --date 2026-09-10
- 2026-09-10T02:57Z afternoon_slate: engine slate --date 2026-09-10 exit=0
- 2026-09-10T02:57Z afternoon_slate: engine slip --date 2026-09-10
- 2026-09-10T10:11Z daily_loop: standings catchup end=2026-09-10
- 2026-09-10T10:11Z daily_loop: lineups+matchup_history date=2026-09-10
- 2026-09-10T10:11Z daily_loop: pitcher splits date=2026-09-10
- 2026-09-10T10:11Z daily_loop: pitch arsenals season=2026
- 2026-09-10T10:11Z daily_loop: statcast --catchup exit=0
- 2026-09-10T10:11Z daily_loop: gamekey --date 2026-09-09 --end 2026-09-10 exit=0
- 2026-09-10T10:11Z daily_loop: gameflow --date 2026-09-09 exit=0
- 2026-09-10T10:12Z daily_loop: engine slate --date 2026-09-10 exit=0
- 2026-09-10T10:12Z daily_loop: engine slip --date 2026-09-10
- 2026-09-10T10:13Z daily_loop: engine settle --date 2026-09-09 exit=0
- 2026-09-10T10:13Z daily_loop: eod --date 2026-09-09 exit=0
- 2026-09-10T10:13Z daily_loop: postmortem --date 2026-09-09 exit=0
- 2026-09-10T10:13Z daily_loop: train exit=0
- 2026-09-10T10:13Z daily_loop: closing-audit exit=0
- 2026-09-10T10:13Z daily_loop: research-readiness exit=0
- 2026-09-10T10:13Z daily_loop: prereg-clv exit=0
- 2026-09-10T13:55Z daily_loop: standings catchup end=2026-09-10
- 2026-09-10T13:55Z daily_loop: lineups+matchup_history date=2026-09-10
- 2026-09-10T13:55Z daily_loop: pitcher splits date=2026-09-10
- 2026-09-10T13:55Z daily_loop: pitch arsenals season=2026
- 2026-09-10T13:55Z daily_loop: statcast --catchup exit=0
- 2026-09-10T13:55Z daily_loop: gamekey --date 2026-09-09 --end 2026-09-10 exit=0
- 2026-09-10T13:55Z daily_loop: gameflow --date 2026-09-09 exit=0
- 2026-09-10T13:56Z daily_loop: engine slate --date 2026-09-10 exit=0
- 2026-09-10T13:56Z daily_loop: engine slip --date 2026-09-10
- 2026-09-10T13:56Z daily_loop: engine settle --date 2026-09-09 exit=0
- 2026-09-10T13:56Z daily_loop: eod --date 2026-09-09 exit=0
- 2026-09-10T13:56Z daily_loop: postmortem --date 2026-09-09 exit=0
- 2026-09-10T13:56Z daily_loop: train exit=0
- 2026-09-10T13:56Z daily_loop: closing-audit exit=0
- 2026-09-10T13:56Z daily_loop: research-readiness exit=0
- 2026-09-10T13:56Z daily_loop: prereg-clv exit=0
- 2026-09-10T15:11Z afternoon_slate: engine slate --date 2026-09-10 exit=0
- 2026-09-10T15:12Z afternoon_slate: card publish --date 2026-09-10 exit=0
- 2026-09-10T15:12Z afternoon_slate: engine slip --date 2026-09-10
- 2026-09-10T15:44Z afternoon_slate: engine slate --date 2026-09-10 exit=0
- 2026-09-10T15:45Z afternoon_slate: card publish --date 2026-09-10 exit=0
- 2026-09-10T15:45Z afternoon_slate: engine slip --date 2026-09-10
- 2026-09-10T16:13Z afternoon_slate: engine slate --date 2026-09-10 exit=0
- 2026-09-10T16:13Z afternoon_slate: card publish --date 2026-09-10 exit=0
- 2026-09-10T16:13Z afternoon_slate: engine slip --date 2026-09-10
- 2026-09-10T16:44Z afternoon_slate: engine slate --date 2026-09-10 exit=0
- 2026-09-10T16:45Z afternoon_slate: card publish --date 2026-09-10 exit=0
- 2026-09-10T16:45Z afternoon_slate: engine slip --date 2026-09-10
- 2026-09-10T17:11Z afternoon_slate: engine slate --date 2026-09-10 exit=0
- 2026-09-10T17:12Z afternoon_slate: card publish --date 2026-09-10 exit=0
- 2026-09-10T17:12Z afternoon_slate: engine slip --date 2026-09-10
- 2026-09-10T17:42Z afternoon_slate: engine slate --date 2026-09-10 exit=0
- 2026-09-10T17:42Z afternoon_slate: card publish --date 2026-09-10 exit=0
- 2026-09-10T17:42Z afternoon_slate: engine slip --date 2026-09-10
- 2026-09-10T18:13Z afternoon_slate: engine slate --date 2026-09-10 exit=0
- 2026-09-10T18:14Z afternoon_slate: card publish --date 2026-09-10 exit=0
- 2026-09-10T18:14Z afternoon_slate: engine slip --date 2026-09-10
- 2026-09-10T18:42Z afternoon_slate: engine slate --date 2026-09-10 exit=0
- 2026-09-10T18:42Z afternoon_slate: card publish --date 2026-09-10 exit=0
- 2026-09-10T18:42Z afternoon_slate: engine slip --date 2026-09-10
- 2026-09-10T19:11Z afternoon_slate: engine slate --date 2026-09-10 exit=0
- 2026-09-10T19:12Z afternoon_slate: card publish --date 2026-09-10 exit=0
- 2026-09-10T19:12Z afternoon_slate: engine slip --date 2026-09-10
- 2026-09-10T19:42Z afternoon_slate: engine slate --date 2026-09-10 exit=0
- 2026-09-10T19:43Z afternoon_slate: card publish --date 2026-09-10 exit=0
- 2026-09-10T19:43Z afternoon_slate: engine slip --date 2026-09-10
- 2026-09-10T20:12Z afternoon_slate: engine slate --date 2026-09-10 exit=0
- 2026-09-10T20:13Z afternoon_slate: card publish --date 2026-09-10 exit=0
- 2026-09-10T20:13Z afternoon_slate: engine slip --date 2026-09-10
- 2026-09-10T20:42Z afternoon_slate: engine slate --date 2026-09-10 exit=0
- 2026-09-10T20:43Z afternoon_slate: card publish --date 2026-09-10 exit=0
- 2026-09-10T20:43Z afternoon_slate: engine slip --date 2026-09-10
- 2026-09-10T21:13Z afternoon_slate: engine slate --date 2026-09-10 exit=0
- 2026-09-10T21:14Z afternoon_slate: card publish --date 2026-09-10 exit=0
- 2026-09-10T21:14Z afternoon_slate: engine slip --date 2026-09-10
- 2026-09-10T21:42Z afternoon_slate: engine slate --date 2026-09-10 exit=0
- 2026-09-10T21:42Z afternoon_slate: card publish --date 2026-09-10 exit=0
- 2026-09-10T21:42Z afternoon_slate: engine slip --date 2026-09-10
- 2026-09-10T22:14Z afternoon_slate: engine slate --date 2026-09-10 exit=0
- 2026-09-10T22:14Z afternoon_slate: card publish --date 2026-09-10 exit=0
- 2026-09-10T22:14Z afternoon_slate: engine slip --date 2026-09-10
- 2026-09-10T22:42Z afternoon_slate: engine slate --date 2026-09-10 exit=0
- 2026-09-10T22:43Z afternoon_slate: card publish --date 2026-09-10 exit=0
- 2026-09-10T22:43Z afternoon_slate: engine slip --date 2026-09-10
- 2026-09-10T23:09Z afternoon_slate: engine slate --date 2026-09-10 exit=0
- 2026-09-10T23:10Z afternoon_slate: card publish --date 2026-09-10 exit=0
- 2026-09-10T23:10Z afternoon_slate: engine slip --date 2026-09-10
- 2026-09-10T23:42Z afternoon_slate: engine slate --date 2026-09-10 exit=0
- 2026-09-10T23:43Z afternoon_slate: card publish --date 2026-09-10 exit=0
- 2026-09-10T23:43Z afternoon_slate: engine slip --date 2026-09-10
- 2026-09-11T00:11Z afternoon_slate: engine slate --date 2026-09-11 exit=2
- 2026-09-11T00:11Z afternoon_slate: card publish --date 2026-09-11 exit=0
- 2026-09-11T00:11Z afternoon_slate: engine slip --date 2026-09-11
- 2026-09-11T00:40Z afternoon_slate: engine slate --date 2026-09-11 exit=2
- 2026-09-11T00:40Z afternoon_slate: card publish --date 2026-09-11 exit=0
- 2026-09-11T00:40Z afternoon_slate: engine slip --date 2026-09-11
- 2026-09-11T01:10Z afternoon_slate: engine slate --date 2026-09-11 exit=2
- 2026-09-11T01:10Z afternoon_slate: card publish --date 2026-09-11 exit=0
- 2026-09-11T01:10Z afternoon_slate: engine slip --date 2026-09-11
- 2026-09-11T01:40Z afternoon_slate: engine slate --date 2026-09-11 exit=2
- 2026-09-11T01:40Z afternoon_slate: card publish --date 2026-09-11 exit=0
- 2026-09-11T01:40Z afternoon_slate: engine slip --date 2026-09-11
- 2026-09-11T02:11Z afternoon_slate: engine slate --date 2026-09-11 exit=2
- 2026-09-11T02:11Z afternoon_slate: card publish --date 2026-09-11 exit=0
- 2026-09-11T02:11Z afternoon_slate: engine slip --date 2026-09-11
- 2026-09-11T02:40Z afternoon_slate: engine slate --date 2026-09-11 exit=2
- 2026-09-11T02:40Z afternoon_slate: card publish --date 2026-09-11 exit=0
- 2026-09-11T02:40Z afternoon_slate: engine slip --date 2026-09-11
- 2026-09-11T10:11Z daily_loop: standings catchup end=2026-09-11
- 2026-09-11T10:11Z daily_loop: lineups+matchup_history date=2026-09-11
- 2026-09-11T10:11Z daily_loop: pitcher splits date=2026-09-11
- 2026-09-11T10:11Z daily_loop: pitch arsenals season=2026
- 2026-09-11T10:11Z daily_loop: statcast --catchup exit=0
- 2026-09-11T10:11Z daily_loop: gamekey --date 2026-09-10 --end 2026-09-11 exit=0
- 2026-09-11T10:11Z daily_loop: gameflow --date 2026-09-10 exit=0
- 2026-09-11T10:13Z daily_loop: engine slate --date 2026-09-11 exit=0
- 2026-09-11T10:14Z daily_loop: engine slip --date 2026-09-11
- 2026-09-11T10:14Z daily_loop: engine settle --date 2026-09-10 exit=0
- 2026-09-11T10:14Z daily_loop: card settle --date 2026-09-10 exit=0
- 2026-09-11T10:14Z daily_loop: fit_card_calibration exit=0
- 2026-09-11T10:14Z daily_loop: eod --date 2026-09-10 exit=0
- 2026-09-11T10:14Z daily_loop: postmortem --date 2026-09-10 exit=0
- 2026-09-11T10:14Z daily_loop: train exit=0
- 2026-09-11T10:14Z daily_loop: closing-audit exit=0
- 2026-09-11T10:14Z daily_loop: calibration_drift_audit exit=1
- 2026-09-11T10:14Z daily_loop: test_tier_ladder exit=0
- 2026-09-11T10:14Z daily_loop: research-readiness exit=0
- 2026-09-11T10:14Z daily_loop: prereg-clv exit=0
- 2026-09-11T13:55Z daily_loop: standings catchup end=2026-09-11
- 2026-09-11T13:55Z daily_loop: lineups+matchup_history date=2026-09-11
- 2026-09-11T13:55Z daily_loop: pitcher splits date=2026-09-11
- 2026-09-11T13:55Z daily_loop: pitch arsenals season=2026
- 2026-09-11T13:55Z daily_loop: statcast --catchup exit=0
- 2026-09-11T13:55Z daily_loop: gamekey --date 2026-09-10 --end 2026-09-11 exit=0
- 2026-09-11T13:55Z daily_loop: gameflow --date 2026-09-10 exit=0
- 2026-09-11T13:57Z daily_loop: engine slate --date 2026-09-11 exit=0
- 2026-09-11T13:57Z daily_loop: engine slip --date 2026-09-11
- 2026-09-11T13:57Z daily_loop: engine settle --date 2026-09-10 exit=0
- 2026-09-11T13:57Z daily_loop: card settle --date 2026-09-10 exit=0
- 2026-09-11T13:57Z daily_loop: fit_card_calibration exit=0
- 2026-09-11T13:57Z daily_loop: eod --date 2026-09-10 exit=0
- 2026-09-11T13:57Z daily_loop: postmortem --date 2026-09-10 exit=0
- 2026-09-11T13:57Z daily_loop: train exit=0
- 2026-09-11T13:57Z daily_loop: closing-audit exit=0
- 2026-09-11T13:58Z daily_loop: calibration_drift_audit exit=1
- 2026-09-11T13:58Z daily_loop: test_tier_ladder exit=0
- 2026-09-11T13:58Z daily_loop: research-readiness exit=0
- 2026-09-11T13:58Z daily_loop: prereg-clv exit=0
- 2026-09-11T15:11Z afternoon_slate: engine slate --date 2026-09-11 exit=0
- 2026-09-11T15:11Z afternoon_slate: card publish --date 2026-09-11 exit=0
- 2026-09-11T15:11Z afternoon_slate: engine slip --date 2026-09-11
- 2026-09-11T15:41Z afternoon_slate: engine slate --date 2026-09-11 exit=0
- 2026-09-11T15:41Z afternoon_slate: card publish --date 2026-09-11 exit=0
- 2026-09-11T15:41Z afternoon_slate: engine slip --date 2026-09-11
- 2026-09-11T16:13Z afternoon_slate: engine slate --date 2026-09-11 exit=0
- 2026-09-11T16:13Z afternoon_slate: card publish --date 2026-09-11 exit=0
- 2026-09-11T16:13Z afternoon_slate: engine slip --date 2026-09-11
- 2026-09-11T16:44Z afternoon_slate: engine slate --date 2026-09-11 exit=0
- 2026-09-11T16:44Z afternoon_slate: card publish --date 2026-09-11 exit=0
- 2026-09-11T16:44Z afternoon_slate: engine slip --date 2026-09-11
- 2026-09-11T17:11Z afternoon_slate: engine slate --date 2026-09-11 exit=0
- 2026-09-11T17:11Z afternoon_slate: card publish --date 2026-09-11 exit=0
- 2026-09-11T17:11Z afternoon_slate: engine slip --date 2026-09-11
- 2026-09-11T17:43Z afternoon_slate: engine slate --date 2026-09-11 exit=0
- 2026-09-11T17:43Z afternoon_slate: card publish --date 2026-09-11 exit=0
- 2026-09-11T17:43Z afternoon_slate: engine slip --date 2026-09-11
- 2026-09-11T18:15Z afternoon_slate: engine slate --date 2026-09-11 exit=0
- 2026-09-11T18:15Z afternoon_slate: card publish --date 2026-09-11 exit=0
- 2026-09-11T18:15Z afternoon_slate: engine slip --date 2026-09-11
- 2026-09-11T18:41Z afternoon_slate: engine slate --date 2026-09-11 exit=0
- 2026-09-11T18:42Z afternoon_slate: card publish --date 2026-09-11 exit=0
- 2026-09-11T18:42Z afternoon_slate: engine slip --date 2026-09-11
- 2026-09-11T18:44Z afternoon_slate: engine slate --date 2026-09-11 exit=0
- 2026-09-11T18:45Z afternoon_slate: card publish --date 2026-09-11 exit=0
- 2026-09-11T18:45Z afternoon_slate: engine slip --date 2026-09-11
- 2026-09-11T19:29Z afternoon_slate: engine slate --date 2026-09-11 exit=0
- 2026-09-11T19:29Z afternoon_slate: card publish --date 2026-09-11 exit=0
- 2026-09-11T19:29Z afternoon_slate: engine slip --date 2026-09-11
- 2026-09-11T19:56Z afternoon_slate: engine slate --date 2026-09-11 exit=0
- 2026-09-11T19:57Z afternoon_slate: card publish --date 2026-09-11 exit=0
- 2026-09-11T19:57Z afternoon_slate: engine slip --date 2026-09-11
- 2026-09-11T20:27Z afternoon_slate: engine slate --date 2026-09-11 exit=0
- 2026-09-11T20:27Z afternoon_slate: card publish --date 2026-09-11 exit=0
- 2026-09-11T20:27Z afternoon_slate: engine slip --date 2026-09-11
- 2026-09-11T21:01Z afternoon_slate: engine slate --date 2026-09-11 exit=0
- 2026-09-11T21:01Z afternoon_slate: card publish --date 2026-09-11 exit=0
- 2026-09-11T21:01Z afternoon_slate: engine slip --date 2026-09-11
- 2026-09-11T21:14Z afternoon_slate: engine slate --date 2026-09-11 exit=0
- 2026-09-11T21:15Z afternoon_slate: card publish --date 2026-09-11 exit=0
- 2026-09-11T21:15Z afternoon_slate: engine slip --date 2026-09-11
- 2026-09-11T21:57Z afternoon_slate: engine slate --date 2026-09-11 exit=0
- 2026-09-11T21:57Z afternoon_slate: card publish --date 2026-09-11 exit=0
- 2026-09-11T21:57Z afternoon_slate: engine slip --date 2026-09-11
- 2026-09-11T22:27Z afternoon_slate: engine slate --date 2026-09-11 exit=0
- 2026-09-11T22:27Z afternoon_slate: card publish --date 2026-09-11 exit=0
- 2026-09-11T22:27Z afternoon_slate: engine slip --date 2026-09-11
- 2026-09-11T23:03Z afternoon_slate: engine slate --date 2026-09-11 exit=0
- 2026-09-11T23:04Z afternoon_slate: card publish --date 2026-09-11 exit=0
- 2026-09-11T23:04Z afternoon_slate: engine slip --date 2026-09-11
- 2026-09-11T23:28Z afternoon_slate: engine slate --date 2026-09-11 exit=0
- 2026-09-11T23:28Z afternoon_slate: card publish --date 2026-09-11 exit=0
- 2026-09-11T23:28Z afternoon_slate: engine slip --date 2026-09-11
- 2026-09-11T23:34Z afternoon_slate: engine slate --date 2026-09-11 exit=0
- 2026-09-11T23:34Z afternoon_slate: card publish --date 2026-09-11 exit=0
- 2026-09-11T23:34Z afternoon_slate: engine slip --date 2026-09-11
- 2026-09-12T00:14Z afternoon_slate: engine slate --date 2026-09-12 exit=0
- 2026-09-12T00:14Z afternoon_slate: card publish --date 2026-09-12 exit=0
- 2026-09-12T00:14Z afternoon_slate: engine slip --date 2026-09-12
- 2026-09-12T00:41Z afternoon_slate: engine slate --date 2026-09-12 exit=0
- 2026-09-12T00:41Z afternoon_slate: card publish --date 2026-09-12 exit=0
- 2026-09-12T00:41Z afternoon_slate: engine slip --date 2026-09-12
- 2026-09-12T01:12Z afternoon_slate: engine slate --date 2026-09-12 exit=0
- 2026-09-12T01:12Z afternoon_slate: card publish --date 2026-09-12 exit=0
- 2026-09-12T01:12Z afternoon_slate: engine slip --date 2026-09-12
- 2026-09-12T01:35Z afternoon_slate: engine slate --date 2026-09-12 exit=0
- 2026-09-12T01:35Z afternoon_slate: card publish --date 2026-09-12 exit=0
- 2026-09-12T01:35Z afternoon_slate: engine slip --date 2026-09-12
- 2026-09-12T02:15Z afternoon_slate: engine slate --date 2026-09-12 exit=0
- 2026-09-12T02:15Z afternoon_slate: card publish --date 2026-09-12 exit=0
- 2026-09-12T02:15Z afternoon_slate: engine slip --date 2026-09-12
- 2026-09-12T02:42Z afternoon_slate: engine slate --date 2026-09-12 exit=0
- 2026-09-12T02:42Z afternoon_slate: card publish --date 2026-09-12 exit=0
- 2026-09-12T02:42Z afternoon_slate: engine slip --date 2026-09-12
- 2026-09-12T10:11Z daily_loop: standings catchup end=2026-09-12
- 2026-09-12T10:11Z daily_loop: lineups+matchup_history date=2026-09-12
- 2026-09-12T10:11Z daily_loop: pitcher splits date=2026-09-12
- 2026-09-12T10:12Z daily_loop: pitch arsenals season=2026
- 2026-09-12T10:12Z daily_loop: statcast --catchup exit=0
- 2026-09-12T10:12Z daily_loop: gamekey --date 2026-09-11 --end 2026-09-12 exit=0
- 2026-09-12T10:12Z daily_loop: gameflow --date 2026-09-11 exit=0
- 2026-09-12T10:16Z daily_loop: engine slate --date 2026-09-12 exit=0
- 2026-09-12T10:16Z daily_loop: engine slip --date 2026-09-12
- 2026-09-12T10:16Z daily_loop: engine settle --date 2026-09-11 exit=0
- 2026-09-12T10:16Z daily_loop: card settle --date 2026-09-11 exit=0
- 2026-09-12T10:16Z daily_loop: fit_card_calibration exit=0
- 2026-09-12T10:16Z daily_loop: eod --date 2026-09-11 exit=0
- 2026-09-12T10:16Z daily_loop: postmortem --date 2026-09-11 exit=0
- 2026-09-12T10:16Z daily_loop: train exit=0
- 2026-09-12T10:16Z daily_loop: closing-audit exit=0
- 2026-09-12T10:16Z daily_loop: calibration_drift_audit exit=1
- 2026-09-12T10:16Z daily_loop: test_tier_ladder exit=0
- 2026-09-12T10:16Z daily_loop: research-readiness exit=0
- 2026-09-12T10:16Z daily_loop: prereg-clv exit=0
- 2026-09-12T13:12Z daily_loop: standings catchup end=2026-09-12
- 2026-09-12T13:12Z daily_loop: lineups+matchup_history date=2026-09-12
- 2026-09-12T13:12Z daily_loop: pitcher splits date=2026-09-12
- 2026-09-12T13:12Z daily_loop: pitch arsenals season=2026
- 2026-09-12T13:12Z daily_loop: statcast --catchup exit=0
- 2026-09-12T13:12Z daily_loop: gamekey --date 2026-09-11 --end 2026-09-12 exit=0
- 2026-09-12T13:12Z daily_loop: gameflow --date 2026-09-11 exit=0
- 2026-09-12T13:16Z daily_loop: engine slate --date 2026-09-12 exit=0
- 2026-09-12T13:16Z daily_loop: engine slip --date 2026-09-12
- 2026-09-12T13:16Z daily_loop: engine settle --date 2026-09-11 exit=0
- 2026-09-12T13:16Z daily_loop: card settle --date 2026-09-11 exit=0
- 2026-09-12T13:16Z daily_loop: fit_card_calibration exit=0
- 2026-09-12T13:16Z daily_loop: eod --date 2026-09-11 exit=0
- 2026-09-12T13:16Z daily_loop: postmortem --date 2026-09-11 exit=0
- 2026-09-12T13:16Z daily_loop: train exit=0
- 2026-09-12T13:16Z daily_loop: closing-audit exit=0
- 2026-09-12T13:16Z daily_loop: calibration_drift_audit exit=1
- 2026-09-12T13:16Z daily_loop: test_tier_ladder exit=0
- 2026-09-12T13:16Z daily_loop: research-readiness exit=0
- 2026-09-12T13:16Z daily_loop: prereg-clv exit=0
- 2026-09-12T15:12Z afternoon_slate: engine slate --date 2026-09-12 exit=0
- 2026-09-12T15:12Z afternoon_slate: card publish --date 2026-09-12 exit=0
- 2026-09-12T15:12Z afternoon_slate: engine slip --date 2026-09-12
- 2026-09-12T15:46Z afternoon_slate: engine slate --date 2026-09-12 exit=0
- 2026-09-12T15:47Z afternoon_slate: card publish --date 2026-09-12 exit=0
- 2026-09-12T15:47Z afternoon_slate: engine slip --date 2026-09-12
- 2026-09-12T16:12Z afternoon_slate: engine slate --date 2026-09-12 exit=0
- 2026-09-12T16:12Z afternoon_slate: card publish --date 2026-09-12 exit=0
- 2026-09-12T16:12Z afternoon_slate: engine slip --date 2026-09-12
- 2026-09-12T16:43Z afternoon_slate: engine slate --date 2026-09-12 exit=0
- 2026-09-12T16:43Z afternoon_slate: card publish --date 2026-09-12 exit=0
- 2026-09-12T16:43Z afternoon_slate: engine slip --date 2026-09-12
- 2026-09-12T17:49Z afternoon_slate: engine slate --date 2026-09-12 exit=0
- 2026-09-12T17:49Z afternoon_slate: card publish --date 2026-09-12 exit=0
- 2026-09-12T17:49Z afternoon_slate: engine slip --date 2026-09-12
- 2026-09-12T20:55Z afternoon_slate: engine slate --date 2026-09-12 exit=0
- 2026-09-12T20:55Z afternoon_slate: card publish --date 2026-09-12 exit=0
- 2026-09-12T20:55Z afternoon_slate: engine slip --date 2026-09-12
- 2026-09-12T23:18Z afternoon_slate: engine slate --date 2026-09-12 exit=0
- 2026-09-12T23:18Z afternoon_slate: card publish --date 2026-09-12 exit=0
- 2026-09-12T23:18Z afternoon_slate: engine slip --date 2026-09-12
- 2026-09-13T01:26Z afternoon_slate: engine slate --date 2026-09-13 exit=0
- 2026-09-13T01:26Z afternoon_slate: card publish --date 2026-09-13 exit=0
- 2026-09-13T01:26Z afternoon_slate: engine slip --date 2026-09-13
- 2026-09-13T13:57Z daily_loop: standings catchup end=2026-09-13
- 2026-09-13T13:57Z daily_loop: lineups+matchup_history date=2026-09-13
- 2026-09-13T13:57Z daily_loop: pitcher splits date=2026-09-13
- 2026-09-13T13:57Z daily_loop: pitch arsenals season=2026
- 2026-09-13T13:57Z daily_loop: statcast --catchup exit=0
- 2026-09-13T13:57Z daily_loop: gamekey --date 2026-09-12 --end 2026-09-13 exit=0
- 2026-09-13T13:58Z daily_loop: gameflow --date 2026-09-12 exit=0
- 2026-09-13T14:01Z daily_loop: engine slate --date 2026-09-13 exit=0
- 2026-09-13T14:01Z daily_loop: engine slip --date 2026-09-13
- 2026-09-13T14:01Z daily_loop: engine settle --date 2026-09-12 exit=0
- 2026-09-13T14:01Z daily_loop: card settle --date 2026-09-12 exit=0
- 2026-09-13T14:01Z daily_loop: fit_card_calibration exit=0
- 2026-09-13T14:01Z daily_loop: eod --date 2026-09-12 exit=0
- 2026-09-13T14:01Z daily_loop: postmortem --date 2026-09-12 exit=0
- 2026-09-13T14:01Z daily_loop: train exit=0
- 2026-09-13T14:01Z daily_loop: closing-audit exit=0
- 2026-09-13T14:01Z daily_loop: calibration_drift_audit exit=1
- 2026-09-13T14:01Z daily_loop: test_tier_ladder exit=0
- 2026-09-13T14:01Z daily_loop: research-readiness exit=0
- 2026-09-13T14:01Z daily_loop: prereg-clv exit=0
- 2026-09-13T18:20Z afternoon_slate: engine slate --date 2026-09-13 exit=0
- 2026-09-13T18:20Z afternoon_slate: card publish --date 2026-09-13 exit=0
- 2026-09-13T18:20Z afternoon_slate: engine slip --date 2026-09-13
- 2026-09-13T21:06Z afternoon_slate: engine slate --date 2026-09-13 exit=0
- 2026-09-13T21:06Z afternoon_slate: card publish --date 2026-09-13 exit=0
- 2026-09-13T21:06Z afternoon_slate: engine slip --date 2026-09-13
- 2026-09-13T23:27Z afternoon_slate: engine slate --date 2026-09-13 exit=0
- 2026-09-13T23:27Z afternoon_slate: card publish --date 2026-09-13 exit=0
- 2026-09-13T23:27Z afternoon_slate: engine slip --date 2026-09-13
- 2026-09-14T01:38Z afternoon_slate: engine slate --date 2026-09-14 exit=2
- 2026-09-14T01:38Z afternoon_slate: card publish --date 2026-09-14 exit=0
- 2026-09-14T01:38Z afternoon_slate: engine slip --date 2026-09-14
- 2026-09-14T15:12Z afternoon_slate: engine slate --date 2026-09-14 exit=2
- 2026-09-14T15:12Z afternoon_slate: card publish --date 2026-09-14 exit=0
- 2026-09-14T15:12Z afternoon_slate: engine slip --date 2026-09-14
- 2026-09-14T16:01Z daily_loop: standings catchup end=2026-09-14
- 2026-09-14T16:01Z daily_loop: lineups+matchup_history date=2026-09-14
- 2026-09-14T16:02Z daily_loop: pitcher splits date=2026-09-14
- 2026-09-14T16:02Z daily_loop: pitch arsenals season=2026
- 2026-09-14T16:02Z daily_loop: statcast --catchup exit=0
- 2026-09-14T16:02Z daily_loop: gamekey --date 2026-09-13 --end 2026-09-14 exit=0
- 2026-09-14T16:02Z daily_loop: gameflow --date 2026-09-13 exit=0
- 2026-09-14T16:04Z daily_loop: engine slate --date 2026-09-14 exit=0
- 2026-09-14T16:04Z daily_loop: engine slip --date 2026-09-14
- 2026-09-14T16:04Z daily_loop: engine settle --date 2026-09-13 exit=0
- 2026-09-14T16:04Z daily_loop: card settle --date 2026-09-13 exit=0
- 2026-09-14T16:05Z daily_loop: fit_card_calibration exit=0
- 2026-09-14T16:05Z daily_loop: eod --date 2026-09-13 exit=0
- 2026-09-14T16:05Z daily_loop: postmortem --date 2026-09-13 exit=0
- 2026-09-14T16:05Z daily_loop: train exit=0
- 2026-09-14T16:05Z daily_loop: closing-audit exit=0
- 2026-09-14T16:05Z daily_loop: calibration_drift_audit exit=1
- 2026-09-14T16:05Z daily_loop: test_tier_ladder exit=0
- 2026-09-14T16:05Z daily_loop: research-readiness exit=0
- 2026-09-14T16:05Z daily_loop: prereg-clv exit=0
- 2026-09-14T16:13Z afternoon_slate: engine slate --date 2026-09-14 exit=0
- 2026-09-14T16:13Z afternoon_slate: card publish --date 2026-09-14 exit=0
- 2026-09-14T16:13Z afternoon_slate: engine slip --date 2026-09-14
- 2026-09-14T16:43Z afternoon_slate: engine slate --date 2026-09-14 exit=0
- 2026-09-14T16:43Z afternoon_slate: card publish --date 2026-09-14 exit=0
- 2026-09-14T16:43Z afternoon_slate: engine slip --date 2026-09-14
- 2026-09-14T17:12Z afternoon_slate: engine slate --date 2026-09-14 exit=0
- 2026-09-14T17:12Z afternoon_slate: card publish --date 2026-09-14 exit=0
- 2026-09-14T17:12Z afternoon_slate: engine slip --date 2026-09-14
- 2026-09-14T17:41Z afternoon_slate: engine slate --date 2026-09-14 exit=0
- 2026-09-14T17:42Z afternoon_slate: card publish --date 2026-09-14 exit=0
- 2026-09-14T17:42Z afternoon_slate: engine slip --date 2026-09-14
- 2026-09-14T18:14Z afternoon_slate: engine slate --date 2026-09-14 exit=0
- 2026-09-14T18:14Z afternoon_slate: card publish --date 2026-09-14 exit=0
- 2026-09-14T18:14Z afternoon_slate: engine slip --date 2026-09-14
- 2026-09-14T18:42Z afternoon_slate: engine slate --date 2026-09-14 exit=0
- 2026-09-14T18:42Z afternoon_slate: card publish --date 2026-09-14 exit=0
- 2026-09-14T18:42Z afternoon_slate: engine slip --date 2026-09-14
- 2026-09-14T19:12Z afternoon_slate: engine slate --date 2026-09-14 exit=0
- 2026-09-14T19:13Z afternoon_slate: card publish --date 2026-09-14 exit=0
- 2026-09-14T19:13Z afternoon_slate: engine slip --date 2026-09-14
- 2026-09-14T19:16Z afternoon_slate: engine slate --date 2026-09-14 exit=2
- 2026-09-14T19:16Z afternoon_slate: card publish --date 2026-09-14 exit=0
- 2026-09-14T19:16Z afternoon_slate: engine slip --date 2026-09-14
- 2026-09-14T19:29Z afternoon_slate: engine slate --date 2026-09-14 exit=2
- 2026-09-14T19:29Z afternoon_slate: card publish --date 2026-09-14 exit=0
- 2026-09-14T19:29Z afternoon_slate: engine slip --date 2026-09-14
- 2026-09-14T19:42Z afternoon_slate: engine slate --date 2026-09-14 exit=0
- 2026-09-14T19:42Z afternoon_slate: card publish --date 2026-09-14 exit=0
- 2026-09-14T19:42Z afternoon_slate: engine slip --date 2026-09-14
- 2026-09-14T19:44Z afternoon_slate: engine slate --date 2026-09-14 exit=2
- 2026-09-14T19:44Z afternoon_slate: card publish --date 2026-09-14 exit=0
- 2026-09-14T19:44Z afternoon_slate: engine slip --date 2026-09-14
- 2026-09-14T19:56Z afternoon_slate: engine slate --date 2026-09-14 exit=2
- 2026-09-14T19:56Z afternoon_slate: card publish --date 2026-09-14 exit=0
- 2026-09-14T19:56Z afternoon_slate: engine slip --date 2026-09-14
- 2026-09-14T19:59Z afternoon_slate: engine slate --date 2026-09-14 exit=0
- 2026-09-14T20:00Z afternoon_slate: card publish --date 2026-09-14 exit=0
- 2026-09-14T20:00Z afternoon_slate: engine slip --date 2026-09-14
- 2026-09-14T20:09Z afternoon_slate: engine slate --date 2026-09-14 exit=2
- 2026-09-14T20:09Z afternoon_slate: card publish --date 2026-09-14 exit=0
- 2026-09-14T20:09Z afternoon_slate: engine slip --date 2026-09-14
- 2026-09-14T20:22Z afternoon_slate: engine slate --date 2026-09-14 exit=2
- 2026-09-14T20:22Z afternoon_slate: card publish --date 2026-09-14 exit=0
- 2026-09-14T20:22Z afternoon_slate: engine slip --date 2026-09-14
- 2026-09-14T20:34Z afternoon_slate: engine slate --date 2026-09-14 exit=2
- 2026-09-14T20:34Z afternoon_slate: card publish --date 2026-09-14 exit=0
- 2026-09-14T20:34Z afternoon_slate: engine slip --date 2026-09-14
- 2026-09-14T20:48Z afternoon_slate: engine slate --date 2026-09-14 exit=2
- 2026-09-14T20:48Z afternoon_slate: card publish --date 2026-09-14 exit=0
- 2026-09-14T20:48Z afternoon_slate: engine slip --date 2026-09-14
- 2026-09-14T21:01Z afternoon_slate: engine slate --date 2026-09-14 exit=2
- 2026-09-14T21:02Z afternoon_slate: card publish --date 2026-09-14 exit=0
- 2026-09-14T21:02Z afternoon_slate: engine slip --date 2026-09-14
- 2026-09-14T21:14Z afternoon_slate: engine slate --date 2026-09-14 exit=2
- 2026-09-14T21:14Z afternoon_slate: card publish --date 2026-09-14 exit=0
- 2026-09-14T21:14Z afternoon_slate: engine slip --date 2026-09-14
- 2026-09-14T21:27Z afternoon_slate: engine slate --date 2026-09-14 exit=2
- 2026-09-14T21:27Z afternoon_slate: card publish --date 2026-09-14 exit=0
- 2026-09-14T21:27Z afternoon_slate: engine slip --date 2026-09-14
- 2026-09-14T21:40Z afternoon_slate: engine slate --date 2026-09-14 exit=2
- 2026-09-14T21:40Z afternoon_slate: card publish --date 2026-09-14 exit=0
- 2026-09-14T21:40Z afternoon_slate: engine slip --date 2026-09-14
- 2026-09-14T21:53Z afternoon_slate: engine slate --date 2026-09-14 exit=2
- 2026-09-14T21:53Z afternoon_slate: card publish --date 2026-09-14 exit=0
- 2026-09-14T21:53Z afternoon_slate: engine slip --date 2026-09-14
- 2026-09-14T22:03Z afternoon_slate: engine slate --date 2026-09-14 exit=0
- 2026-09-14T22:03Z afternoon_slate: card publish --date 2026-09-14 exit=0
- 2026-09-14T22:03Z afternoon_slate: engine slip --date 2026-09-14
- 2026-09-14T22:34Z afternoon_slate: engine slate --date 2026-09-14 exit=2
- 2026-09-14T22:34Z afternoon_slate: card publish --date 2026-09-14 exit=0
- 2026-09-14T22:34Z afternoon_slate: engine slip --date 2026-09-14
- 2026-09-14T22:46Z afternoon_slate: engine slate --date 2026-09-14 exit=2
- 2026-09-14T22:46Z afternoon_slate: card publish --date 2026-09-14 exit=0
- 2026-09-14T22:46Z afternoon_slate: engine slip --date 2026-09-14
- 2026-09-14T23:00Z afternoon_slate: engine slate --date 2026-09-14 exit=2
- 2026-09-14T23:01Z afternoon_slate: card publish --date 2026-09-14 exit=0
- 2026-09-14T23:01Z afternoon_slate: engine slip --date 2026-09-14
- 2026-09-14T23:13Z afternoon_slate: engine slate --date 2026-09-14 exit=2
- 2026-09-14T23:13Z afternoon_slate: card publish --date 2026-09-14 exit=0
- 2026-09-14T23:13Z afternoon_slate: engine slip --date 2026-09-14
- 2026-09-14T23:25Z afternoon_slate: engine slate --date 2026-09-14 exit=2
- 2026-09-14T23:25Z afternoon_slate: card publish --date 2026-09-14 exit=0
- 2026-09-14T23:25Z afternoon_slate: engine slip --date 2026-09-14
- 2026-09-14T23:39Z afternoon_slate: engine slate --date 2026-09-14 exit=2
- 2026-09-14T23:39Z afternoon_slate: card publish --date 2026-09-14 exit=0
- 2026-09-14T23:39Z afternoon_slate: engine slip --date 2026-09-14
- 2026-09-14T23:52Z afternoon_slate: engine slate --date 2026-09-14 exit=2
- 2026-09-14T23:52Z afternoon_slate: card publish --date 2026-09-14 exit=0
- 2026-09-14T23:52Z afternoon_slate: engine slip --date 2026-09-14
- 2026-09-15T00:04Z afternoon_slate: engine slate --date 2026-09-14 exit=0
- 2026-09-15T00:05Z afternoon_slate: card publish --date 2026-09-14 exit=0
- 2026-09-15T00:05Z afternoon_slate: engine slip --date 2026-09-14
- 2026-09-15T00:06Z afternoon_slate: engine slate --date 2026-09-15 exit=2
- 2026-09-15T00:06Z afternoon_slate: card publish --date 2026-09-15 exit=0
- 2026-09-15T00:06Z afternoon_slate: engine slip --date 2026-09-15
- 2026-09-15T00:45Z afternoon_slate: engine slate --date 2026-09-15 exit=0
- 2026-09-15T00:45Z afternoon_slate: card publish --date 2026-09-15 exit=0
- 2026-09-15T00:45Z afternoon_slate: engine slip --date 2026-09-15
- 2026-09-15T01:14Z afternoon_slate: engine slate --date 2026-09-15 exit=0
- 2026-09-15T01:14Z afternoon_slate: card publish --date 2026-09-15 exit=0
- 2026-09-15T01:14Z afternoon_slate: engine slip --date 2026-09-15
- 2026-09-15T01:43Z afternoon_slate: engine slate --date 2026-09-15 exit=0
- 2026-09-15T01:43Z afternoon_slate: card publish --date 2026-09-15 exit=0
- 2026-09-15T01:43Z afternoon_slate: engine slip --date 2026-09-15
- 2026-09-15T01:56Z afternoon_slate: engine slate --date 2026-09-15 exit=0
- 2026-09-15T01:56Z afternoon_slate: card publish --date 2026-09-15 exit=0
- 2026-09-15T01:56Z afternoon_slate: engine slip --date 2026-09-15
- 2026-09-15T02:29Z afternoon_slate: engine slate --date 2026-09-15 exit=0
- 2026-09-15T02:29Z afternoon_slate: card publish --date 2026-09-15 exit=0
- 2026-09-15T02:29Z afternoon_slate: engine slip --date 2026-09-15
- 2026-09-15T02:58Z afternoon_slate: engine slate --date 2026-09-15 exit=0
- 2026-09-15T02:58Z afternoon_slate: card publish --date 2026-09-15 exit=0
- 2026-09-15T02:58Z afternoon_slate: engine slip --date 2026-09-15
- 2026-09-15T10:11Z daily_loop: standings catchup end=2026-09-15
- 2026-09-15T10:11Z daily_loop: lineups+matchup_history date=2026-09-15
- 2026-09-15T10:11Z daily_loop: pitcher splits date=2026-09-15
- 2026-09-15T10:11Z daily_loop: pitch arsenals season=2026
- 2026-09-15T10:11Z daily_loop: statcast --catchup exit=0
- 2026-09-15T10:11Z daily_loop: gamekey --date 2026-09-14 --end 2026-09-15 exit=0
- 2026-09-15T10:11Z daily_loop: gameflow --date 2026-09-14 exit=0
- 2026-09-15T10:15Z daily_loop: engine slate --date 2026-09-15 exit=0
- 2026-09-15T10:15Z daily_loop: engine slip --date 2026-09-15
- 2026-09-15T10:15Z daily_loop: engine settle --date 2026-09-14 exit=0
- 2026-09-15T10:15Z daily_loop: card settle --date 2026-09-14 exit=0
- 2026-09-15T10:15Z daily_loop: nfl card settle --date 2026-09-14 exit=0
- 2026-09-15T10:15Z daily_loop: tennis discover
- 2026-09-15T10:15Z daily_loop: budget --probe scores
- 2026-09-15T10:15Z daily_loop: budget --probe tennis_h2h
- 2026-09-15T10:15Z daily_loop: live settle --date 2026-09-14
- 2026-09-15T10:15Z daily_loop: fit_card_calibration exit=0
- 2026-09-15T10:15Z daily_loop: eod --date 2026-09-14 exit=0
- 2026-09-15T10:15Z daily_loop: postmortem --date 2026-09-14 exit=0
- 2026-09-15T10:15Z daily_loop: train exit=0
- 2026-09-15T10:15Z daily_loop: closing-audit exit=0
- 2026-09-15T10:15Z daily_loop: calibration_drift_audit exit=1
- 2026-09-15T10:15Z daily_loop: test_tier_ladder exit=0
- 2026-09-15T10:15Z daily_loop: research-readiness exit=0
- 2026-09-15T10:15Z daily_loop: prereg-clv exit=0
- 2026-09-15T14:31Z daily_loop: standings catchup end=2026-09-15
- 2026-09-15T14:31Z daily_loop: lineups+matchup_history date=2026-09-15
- 2026-09-15T14:31Z daily_loop: pitcher splits date=2026-09-15
- 2026-09-15T14:31Z daily_loop: pitch arsenals season=2026
- 2026-09-15T14:31Z daily_loop: statcast --catchup exit=0
- 2026-09-15T14:31Z daily_loop: gamekey --date 2026-09-14 --end 2026-09-15 exit=0
- 2026-09-15T14:31Z daily_loop: gameflow --date 2026-09-14 exit=0
- 2026-09-15T14:36Z daily_loop: engine slate --date 2026-09-15 exit=0
- 2026-09-15T14:36Z daily_loop: engine slip --date 2026-09-15
- 2026-09-15T14:36Z daily_loop: engine settle --date 2026-09-14 exit=0
- 2026-09-15T14:36Z daily_loop: card settle --date 2026-09-14 exit=0
- 2026-09-15T14:36Z daily_loop: nfl card settle --date 2026-09-14 exit=0
- 2026-09-15T14:36Z daily_loop: tennis discover
- 2026-09-15T14:36Z daily_loop: budget --probe tennis_h2h
- 2026-09-15T14:36Z daily_loop: live settle --date 2026-09-14
- 2026-09-15T14:36Z daily_loop: fit_card_calibration exit=0
- 2026-09-15T14:36Z daily_loop: eod --date 2026-09-14 exit=0
- 2026-09-15T14:36Z daily_loop: postmortem --date 2026-09-14 exit=0
- 2026-09-15T14:36Z daily_loop: train exit=0
- 2026-09-15T14:36Z daily_loop: closing-audit exit=0
- 2026-09-15T14:36Z daily_loop: calibration_drift_audit exit=1
- 2026-09-15T14:36Z daily_loop: test_tier_ladder exit=0
- 2026-09-15T14:36Z daily_loop: research-readiness exit=0
- 2026-09-15T14:36Z daily_loop: prereg-clv exit=0
- 2026-09-15T15:13Z afternoon_slate: engine slate --date 2026-09-15 exit=0
- 2026-09-15T15:13Z afternoon_slate: card publish --date 2026-09-15 exit=0
- 2026-09-15T15:13Z afternoon_slate: engine slip --date 2026-09-15
- 2026-09-15T15:43Z afternoon_slate: engine slate --date 2026-09-15 exit=0
- 2026-09-15T15:43Z afternoon_slate: card publish --date 2026-09-15 exit=0
- 2026-09-15T15:44Z afternoon_slate: engine slip --date 2026-09-15
- 2026-09-15T16:12Z afternoon_slate: engine slate --date 2026-09-15 exit=0
- 2026-09-15T16:12Z afternoon_slate: card publish --date 2026-09-15 exit=0
- 2026-09-15T16:12Z afternoon_slate: engine slip --date 2026-09-15
- 2026-09-15T16:42Z afternoon_slate: engine slate --date 2026-09-15 exit=0
- 2026-09-15T16:42Z afternoon_slate: card publish --date 2026-09-15 exit=0
- 2026-09-15T16:42Z afternoon_slate: engine slip --date 2026-09-15
- 2026-09-15T17:13Z afternoon_slate: engine slate --date 2026-09-15 exit=0
- 2026-09-15T17:14Z afternoon_slate: card publish --date 2026-09-15 exit=0
- 2026-09-15T17:14Z afternoon_slate: engine slip --date 2026-09-15
- 2026-09-15T17:43Z afternoon_slate: engine slate --date 2026-09-15 exit=2
- 2026-09-15T17:43Z afternoon_slate: card publish --date 2026-09-15 exit=0
- 2026-09-15T17:43Z afternoon_slate: engine slip --date 2026-09-15

## 2026-09-15 17:41Z — hourly cloud routine, first live fire (R16-07 smoke test / R16-08)

Claimed R16-08 (the only OPEN, unblocked, today-dated queue item; everything
else eligible was already RUNNING/DONE/BLOCKED_HUMAN). Checked GitHub Actions
via the MCP tools (no `gh` CLI in this container) for new escalations since
the last run: the two most recent `daily-loop` runs (10:10Z, 14:30Z) both
failed, but their job logs show only the two escalations already acknowledged
in `docs/ESCALATIONS.md` (strong-tier drift, research-readiness battery
wiring) — the 14:30Z run predates the default-branch sync of the acknowledged-
escalations ledger fix (R16-06), so it still ran the old unconditional
ESCALATE check; nothing NEW. The `balldontlie-harvest` failure (run 1) is the
already-documented expected stop at the missing `BALLDONTLIE_API_KEY` secret.
No new `ESCALATE:` lines, so nothing outranked the queue.

R16-08 turned out to be a no-op in this environment: a fresh cloud clone never
carried the described stray root `test_*.py` files, `wt-default` worktree, or
held stash — those live only on an earlier local/interactive session's
persistent disk, which this ephemeral container does not share. `git status
--porcelain` was already empty, `git worktree list` showed only the current
worktree, `git stash list` was empty. Recorded this honestly rather than
claiming a cleanup that didn't happen; this class of stray cannot recur
through the hourly routine going forward since every run starts from the
same clean clone.

Verified: full suite green (`python -m unittest discover -s tests -t .`,
7186 tests, 447 skipped, 0 failures); `python scripts/publication_audit.py`
clean. No `web/` changes this run, so the customer-language/web-structure
tests weren't separately required (they're also covered by the full
discover run).

Commits: 417cc92e (claim R16-08), 60ef4fc9 (R16-08 DONE, R16-07 DONE).
Pushed cleanly; one concurrent push from another automation (a card/slip
publish) fast-forwarded in between with no conflict.

Blockers: none new. Standing blockers unchanged — `BALLDONTLIE_API_KEY`
secret (R16-02), per-sport pricing decisions (R16-28), API-Tennis trial
call (R16-22) all still BLOCKED_HUMAN as before.

## 2026-09-15 ~18:45Z — hourly cloud routine: NEW escalation diagnosed and fixed (dense capture window)

Start-of-run check found a NEW `ESCALATE:` line not in `docs/ESCALATIONS.md`
and not previously logged anywhere: `afternoon-slate` run 35002735013
(17:40:29Z dispatch) failed at 17:43:07Z with `ERROR: engine slate --date
2026-09-15 refused by the pre-slate freshness guard (LIVE mode)` —
`price capture for 2026-09-15 is 3.2h stale relative to wall-clock now,
past the 3h threshold`. Per the routine's own rule this outranks the
queue, so this run diagnosed and fixed it instead of claiming R16-09.

Also noted in passing (not part of this fix, recorded for whoever claims
R16-02 next): the BALLDONTLIE_API_KEY secret has clearly been added since
the last run — `balldontlie-harvest` runs 2, 3 and 4 all dispatched and
succeeded (commits "balldontlie harvest: 2026-09-15T1{7,8}:{16,33}Z"),
`data/historical/balldontlie/MANIFEST.json` has real rows for tennis and
NFL. R16-02's own acceptance (a runner log showing tennis result rows) is
someone else's to close since R16-33 already owns that surface and is
RUNNING; left the roadmap untouched here to avoid colliding with that
session's edits.

**Diagnosis.** `engine slate` refuses when the newest captured price
(`data/processed/l1_observations.jsonl`, reprojected each run from
whatever raw odds snapshots are on disk) is older than 3 hours
(`src/engine/preflight.py`, `PRICE_CAPTURE_STALE_HOURS`). The raw source
of that projection, `data/raw/oddsapi/YYYY/MM/DD/*.jsonl.gz`, is git-
committed by `scripts/capture_slot.sh`'s "dense" odds capture step, which
only fires against every game on the slate (a wide, once-an-hour-budgeted
call) when the current UTC minute is under 15 or the slot was a hand
dispatch (`CAPTURE_NOW=1`) — otherwise it only prices games inside a
180-minute window, and skips entirely if none qualify. Checked the
actually-committed files: the newest dense capture for 2026-09-15 was
14:31Z (from the daily loop's own catchup run), nothing since, despite
`forward-capture` firing every ~13 minutes without a single reported
failure all afternoon (verified via the GitHub Actions job logs, run
35006066960 at 18:26Z: `dense (one slot): window: 180 minutes … stopped
early: no game inside the window`). The design already had a fix for a
late slate (2026-09-14, same file's comments) — widen to a full-day
window once an hour — but it depends on SOME chained slot happening to
land on a wall-clock minute under 15, and the chain's own gate can yield
an entire slot to a waiting rival (afternoon-slate was being hand-
dispatched roughly every 30 minutes today for R16-34/35's testing,
sharing the same `forward-capture` concurrency group); with today's
first pitch not until 22:40Z, every slot between 14:31Z and past 18:40Z
apparently landed on an unlucky minute, so the widen never fired and the
board went 4+ hours stale while every workflow run still reported green.

**Fix**, `scripts/capture_slot.sh` (commit 90f93ff1): left the existing
minute-under-15 widen untouched, and added a fallback that checks how
long it has actually been since the newest committed
`data/raw/oddsapi/` capture (durable across every ephemeral runner,
unlike the gitignored L1 projection) and widens to the full-day window
anyway once that exceeds 55 minutes — so a missed lucky window now costs
at most one extra slot, never hours. Three new tests in
`tests/test_capture_no_set_time.py` run the real extracted snippet
(never re-typed) against a stubbed `date` and a fabricated `data/raw/
oddsapi/` tree: a recent capture stays at the narrow window, a capture
stale past 55 minutes widens, and no prior capture on disk widens
immediately. The pre-existing test asserting the exact minute<15
condition text still passes unchanged.

**Verified**: `tests/test_capture_no_set_time.py` (55 tests, all green,
including the 3 new ones and the pre-existing regex assertion on the
unmodified line); full suite (`python -m unittest discover -s tests -t
.`, 7215 tests, 447 skipped, 0 failures); `python
scripts/publication_audit.py` clean. No `web/` files touched, so the
customer-language/web-structure tests weren't separately required.

**Not done this run, and why**: did not add a row to
`docs/ESCALATIONS.md` — that ledger only gates `daily-loop.yml`'s check
step (`scripts/escalations.py --check`); `afternoon-slate.yml`'s
ESCALATE check is a bare `grep` with no ledger lookup, so a ledger row
here would document but not functionally change anything. Flagging here
instead: if `afternoon-slate.yml` should also read the ledger, that is a
small follow-up someone can pick up, not folded into this fix to keep
the diff to the actual root cause.

Commit: 90f93ff1 (rebased cleanly onto d73676db, a concurrent forward-
capture data commit, no conflict). Pushed to
`claude/sports-betting-analysis-review-g1o0co`.

Blockers: none new. Did not claim a numbered roadmap item this run — the
new escalation outranked the queue per the routine's own rule. Standing
blockers unchanged: per-sport pricing decisions (R16-28) and the
API-Tennis trial call (R16-22) still BLOCKED_HUMAN; `BALLDONTLIE_API_KEY`
(R16-02) appears resolved (see above) but left for whoever is already
working that surface to close out with the roadmap evidence it wants.
- 2026-09-15T19:10Z afternoon_slate: engine slate --date 2026-09-15 exit=2
- 2026-09-15T19:10Z afternoon_slate: card publish --date 2026-09-15 exit=0
- 2026-09-15T19:10Z afternoon_slate: engine slip --date 2026-09-15
- 2026-09-15T19:17Z afternoon_slate: engine slate --date 2026-09-15 exit=0
- 2026-09-15T19:17Z afternoon_slate: card publish --date 2026-09-15 exit=0
- 2026-09-15T19:17Z afternoon_slate: engine slip --date 2026-09-15
- 2026-09-15T19:22Z afternoon_slate: engine slate --date 2026-09-15 exit=2
- 2026-09-15T19:22Z afternoon_slate: card publish --date 2026-09-15 exit=0
- 2026-09-15T19:22Z afternoon_slate: engine slip --date 2026-09-15
- 2026-09-15T19:35Z afternoon_slate: engine slate --date 2026-09-15 exit=2
- 2026-09-15T19:35Z afternoon_slate: card publish --date 2026-09-15 exit=0
- 2026-09-15T19:35Z afternoon_slate: engine slip --date 2026-09-15
- 2026-09-15T19:50Z afternoon_slate: engine slate --date 2026-09-15 exit=2
- 2026-09-15T19:50Z afternoon_slate: card publish --date 2026-09-15 exit=0
- 2026-09-15T19:50Z afternoon_slate: engine slip --date 2026-09-15

## 2026-09-15 19:57Z — hourly cloud routine: today's queue fully claimed; diagnosed a second, distinct intraday-slate refusal (not the staleness bug, and not customer-facing)

Start-of-run check: no NEW top-level `ESCALATE:` line outranked the queue
(daily-loop hasn't run since 14:30Z, still only the two acknowledged
patterns; the 90f93ff1 price-staleness fix verified holding — afternoon-slate
run 35011990916 at 19:10Z succeeded outright). Every Stage 16 row dated
Tue 9/15 was already DONE, RUNNING or BLOCKED_HUMAN: R16-33 (balldontlie
harvest) had a push as recent as 19:36Z from an active session; R16-34
(Card V2) and R16-35 (live betting design) carry a 17:05Z "local session"
evidence stamp, which is stale by the routine's 2-hour reclaim rule but is
a different kind of actor than a dead hourly-cloud claim (a local/interactive
session doing "understand, design panel, adversarial review" work can
legitimately run for hours), and both are owner-sensitive, customer-facing
pricing-logic work — reclaiming and duplicating that risked real collision
for no confirmed benefit, so left both alone. No Wed 9/16+ item is eligible
yet ("today or earlier" per the routine). Ran the full suite (7229 tests
green) and `scripts/publication_audit.py` (clean) as a baseline health
check since nothing else was safely claimable.

While doing that health check, the repeated `afternoon_slate: engine slate
... exit=2` lines auto-appended above (19:10, 19:22, 19:35, 19:50Z — all
from `forward-capture.yml`'s chained lineup-cadence call to
`afternoon_slate.sh`, not the standalone `afternoon-slate.yml`) turned out
NOT to be the already-fixed price-staleness bug recurring. Pulled the
actual job logs (run 35012776181, job 104532996667, 19:31-19:35Z): the
dense capture window correctly widened to 1440 minutes (the 90f93ff1 fix
is working — `AGE_MIN=317` on a manual replay of its exact bash against
today's real data confirms it), but `engine slate` then refused with a
different reason entirely: `ERROR: [LIVE] the matchup feature store
(Statcast pitch backfill) has no coverage recorded at all`.

**Root cause.** `forward-capture.yml` self-chains via `workflow_dispatch`
against `CHAIN_BRANCH=claude/sports-betting-analysis-review-g1o0co`
(`scripts/capture_slot.sh`'s `chain_dispatch`). Every such chained run's
"Restore the daily loop's git-ignored inputs" cache-restore step misses
100% of the time: `Cache not found for input keys:
forward-capture-never-saved-<run_id>, daily-loop-data-` — confirmed on
run 35012776181 at 19:31Z, seconds after `afternoon-slate.yml` run
35011990916 (19:10Z, which restored that exact cache successfully and
ran `engine slate` clean) had saved it. The difference: `afternoon-slate.yml`
and `daily-loop.yml` both run associated with the repository's default
branch (`claude/cowork-session-migration-tn3sx2`, confirmed via
`head_branch` on their own runs even when `workflow_dispatch`-triggered),
while every `forward-capture.yml` chain link after the first is dispatched
against the working branch specifically — a different, and per
`forward-capture.yml`'s own comment "an orphan sharing no history with the
working line," unrelated ref for GitHub's Actions-cache purposes. Unlike
`daily-loop.yml` and `afternoon-slate.yml`, `forward-capture.yml` has no
`scripts/daily_bootstrap.sh` fallback step at all, so on the cache miss
there is nothing to rebuild Statcast coverage from, and
`src/engine/preflight.py` correctly refuses rather than staking on an
empty backfill. The refusal is swallowed by forward-capture.yml's own
`|| echo "...did not complete cleanly..."` and by forward-capture.yml
having no ESCALATE-check step of any kind (confirmed: `grep -n "ESCALATE"
.github/workflows/forward-capture.yml` returns nothing) — so this has
never shown red in the Actions UI and nobody would have seen it without
reading a chained run's raw job log.

**Impact, stated plainly.** The two real, customer-facing passes
(`daily-loop.yml` 10:00Z, `afternoon-slate.yml` 15:40 UTC) are unaffected —
confirmed by reading their own runs' logs directly, both green, both with
real Statcast coverage. Those are what freeze and publish the actual card.
The only casualty is the newer *intraday* re-decisioning enrichment
`forward-capture.yml`'s chain was supposed to add on top of those two
(2026-09-14/15 work, "restores the pre-09-05 behaviour" of deciding again
as soon as a lineup posts) — it has most likely never once succeeded since
being wired in, silently. No incorrect data was published; nothing here
touches the card, the ledger, or any customer-facing surface.

**Why this run does not push a fix.** Two tempting fixes are both traps,
checked and rejected here so nobody repeats the check: (1) pointing
`CHAIN_BRANCH` at the default branch to match daily-loop/afternoon-slate's
cache scope — diffed the two branches' copies of this workflow
(`git diff origin/claude/cowork-session-migration-tn3sx2:.github/workflows/forward-capture.yml
origin/claude/sports-betting-analysis-review-g1o0co:.github/workflows/forward-capture.yml`)
and the default branch's copy predates the entire self-chaining/pace-job
design (still has `workflow_dispatch: {}` with no inputs and a
workflow-level concurrency group) — dispatching there would run that
stale copy and silently kill the whole 13-minute cadence, a far worse
outcome than the bug it would fix, and this routine is explicitly
forbidden from editing the default branch to fix the staleness. (2) just
bolting on a bare `bash scripts/daily_bootstrap.sh` step — its Statcast
piece alone is cheap (a shallow git fetch of the `data-seed/statcast`
orphan branch), but the full script is measured at ~9-10 minutes on a
cold miss, this job's cache misses on every single chained run today, and
the chain fires roughly every 13 minutes — a naive add would tax most of
~100 runs/day by 9-10 minutes each and very likely back up or break the
cadence entirely. The real fix needs its own same-branch-scoped cache
(so only the first run after a scope reset pays the bootstrap cost) and
should be load-tested against the live cadence before trusting it, which
is more than this run's remaining budget should spend on a live 24/7
workflow. Recorded as **R16-36** (OPEN, Wed 9/16) in `docs/ROADMAP.md`
with the full diagnosis and both rejected approaches, so the next run
with a proper budget can build and load-test it rather than re-deriving
any of this.

Verified this run: full suite (`python -m unittest discover -s tests -t .`,
7229 tests, 447 skipped, 0 failures); `python scripts/publication_audit.py`
clean. No code changed, so no targeted tests to add — this run's output is
documentation (roadmap queue row + this section) plus the diagnosis itself.

Commits this run: roadmap R16-36 addition and this section (see next
commit hash after push). No data/app, no data/raw, no force-push.

Blockers: none new requiring Brey. R16-36 is a pure engineering follow-up,
not an owner decision, so it is OPEN rather than BLOCKED_HUMAN. Standing
blockers unchanged: per-sport pricing decisions (R16-28), the API-Tennis
trial call (R16-22), and R16-02's roadmap-evidence close-out (owned by
whoever is already on the balldontlie surface) all as before.
- 2026-09-15T20:02Z afternoon_slate: engine slate --date 2026-09-15 exit=2
- 2026-09-15T20:02Z afternoon_slate: card publish --date 2026-09-15 exit=0
- 2026-09-15T20:02Z afternoon_slate: engine slip --date 2026-09-15
- 2026-09-15T20:17Z afternoon_slate: engine slate --date 2026-09-15 exit=2
- 2026-09-15T20:17Z afternoon_slate: card publish --date 2026-09-15 exit=0
- 2026-09-15T20:17Z afternoon_slate: engine slip --date 2026-09-15
- 2026-09-15T20:30Z afternoon_slate: engine slate --date 2026-09-15 exit=2
- 2026-09-15T20:31Z afternoon_slate: card publish --date 2026-09-15 exit=0
- 2026-09-15T20:31Z afternoon_slate: engine slip --date 2026-09-15

## 2026-09-15 21:12Z — hourly cloud routine: claimed R16-02 (tennis results CLI), found and fixed a live credit-leak crash along the way

Start-of-run check: no NEW `ESCALATE:` line outranked the queue. `daily-loop`
had not run since its 14:30Z failure, which predates 502368c1 (the
escalations-ledger fix, landed 16:40Z) and was already explained in the
19:57Z section; `gh` Actions checks (`forward-capture` runs 340-349, all
`success`; `balldontlie-harvest` run 5 still `in_progress` since 19:35Z, so
the standing "keep one harvest run active" instruction needed nothing).

**Claimed R16-02** (the only Tue-9/15 item that was OPEN, unblocked and not
already owned by another session): the owner set `BALLDONTLIE_API_KEY`
earlier today, but this item's other half -- a runner-verified
`tennis results --date` command -- was never done.

**Built.** `src/providers/tennis_results.py` already had a complete, tested
`results_for()`/`BallDontLieFeed` (built ahead of R16-10's future grading
work) that nothing called. Added `python -m src.cli tennis results --date`
(37abe21f, 9a366ed4), a thin read-only wrapper: prints the provider, any
unavailability reason, and each result row; 5 new parsing/routing tests.
Wired one call of it into `scripts/daily_loop.sh` right after tennis
discover, for yesterday's date, tolerant of failure and never escalating
(9a366ed4; 23 `test_daily_loop_wiring.py` tests including a new one
asserting the step is read-only and correctly ordered) -- so every 10:00Z
run now gives an ongoing answer to "is the tennis results feed reachable."
Also added a standalone `tennis-results-check.yml` (727aff25) for an
on-demand check without replaying the rest of the daily loop -- **left
undispatchable this run**: GitHub only exposes a `workflow_dispatch` target
once the file exists on the default branch (confirmed: `POST .../actions/
workflows/tennis-results-check.yml/dispatches` returned 404), and this
routine's own instructions forbid editing that branch. It needs the same
one-line registration commit `balldontlie-harvest.yml` got from an
authorized session (`b62763fb`, R16-33) before anyone can dispatch it.

**Verified on a real runner.** Rather than leave the wiring unverified until
tomorrow's 10:00Z run, dispatched `daily-loop.yml` directly (run
`35022286676`, 20:55-21:05Z UTC) -- safe to do ad hoc: `daily_loop.sh` spends
zero odds credits of its own (confirmed by reading the script; `engine
slate` only reprojects already-captured L1 data) and is explicitly designed
to be re-run safely any time (`card_ledger.publish` locks each pick against
its own first pitch). Read the job's full log: the run went green end to
end, both standing acknowledged escalations (STRONG-tier drift, research-
readiness NOT_RUN) still fired as `KNOWN` not `NEW` (the escalations ledger
is holding), and the new step printed exactly what it should --
`== tennis results (yesterday, 2026-09-14) ==` followed by
`ERROR: balldontlie API returned HTTP 429`. That is the same account-wide
~5 requests/minute throttle R16-33 already tracked (not a defect here: the
command reached the real vendor and reported the failure cleanly, no
crash), so the literal "runner log shows result rows" half of R16-02's
acceptance stays open on the owner's still-pending key/rate-limit question,
not on anything left to build here.

**Found and fixed a live bug in that same log.** Further down the same run,
`== probe unmeasured capture families ==` crashed on `tennis_h2h`:
`AttributeError: 'list' object has no attribute 'get'`, in
`src/capture/budget.py`'s `_payload_shape`. Root cause: the `tennis_h2h`
probe fetches via `provider.fetch_odds()`, which hits
`/sports/{sport}/odds` and returns every event for that sport as a LIST;
`_payload_shape` assumed the single-event dict shape
`fetch_event_odds_with_usage()` returns for every other family. The crash
happened *after* `creditlog.log()` had already recorded a real spent
credit and *before* `_record_measurement()` could ever set `measured: true`
in `config/capture_families.json` -- so `tennis_h2h` would stay permanently
unmeasured, and every future daily loop would repeat the exact crash and
spend another real credit, silently (no `ESCALATE:` line, just an unlabelled
traceback nobody reads). `tests/test_budget_probe_families.py`'s fake
provider had been hiding this: its `fetch_odds()` default returned a
single-event dict instead of the real list shape. Fixed `_payload_shape`
with a new `is_multi_event` branch (aggregates books/markets/outcomes
across every event in the list instead of assuming one), fixed the test
double to the real shape, added two regression tests (multi-event
aggregation; empty-list/no-upcoming-tennis degenerate case). Commit
f790ceef.

**Verified**: full suite (`python -m unittest discover -s tests -t .`, 7237
tests, 447 skipped, 0 failures) after each of the three commits; `python
scripts/publication_audit.py` clean throughout. No `web/` files touched.
`daily-loop.yml`'s own commit from the dispatched run (`Daily loop
2026-09-15`) rebased in cleanly alongside another session's `Redesign group
1` commit -- no conflicts.

Commits this run: 37abe21f (roadmap claim), 9a366ed4 (CLI command +
daily_loop wiring), 727aff25 (standalone check workflow), f790ceef (budget
probe fix), and this roadmap/log update. No `data/app`, no `data/raw`
committed directly, no force-push.

Blockers: R16-02 stays RUNNING, not DONE -- everything buildable here is
built and tested, but full acceptance needs the owner's R16-33 key/rate-
limit answer, same as before. `tennis-results-check.yml` needs default-
branch registration from an authorized session before it is dispatchable.
Standing blockers unchanged: per-sport pricing decisions (R16-28), the
API-Tennis trial call (R16-22).
- 2026-09-15T20:45Z afternoon_slate: engine slate --date 2026-09-15 exit=2
- 2026-09-15T20:45Z afternoon_slate: card publish --date 2026-09-15 exit=0
- 2026-09-15T20:45Z afternoon_slate: engine slip --date 2026-09-15
- 2026-09-15T20:54Z afternoon_slate: engine slate --date 2026-09-15 exit=0
- 2026-09-15T20:54Z afternoon_slate: card publish --date 2026-09-15 exit=0
- 2026-09-15T20:54Z afternoon_slate: engine slip --date 2026-09-15
- 2026-09-15T20:56Z daily_loop: standings catchup end=2026-09-15
- 2026-09-15T20:56Z daily_loop: lineups+matchup_history date=2026-09-15
- 2026-09-15T20:56Z daily_loop: pitcher splits date=2026-09-15
- 2026-09-15T20:56Z daily_loop: pitch arsenals season=2026
- 2026-09-15T20:57Z daily_loop: statcast --catchup exit=0
- 2026-09-15T20:57Z daily_loop: gamekey --date 2026-09-14 --end 2026-09-15 exit=0
- 2026-09-15T20:57Z daily_loop: gameflow --date 2026-09-14 exit=0
- 2026-09-15T21:03Z daily_loop: engine slate --date 2026-09-15 exit=0
- 2026-09-15T21:03Z daily_loop: engine slip --date 2026-09-15
- 2026-09-15T21:03Z daily_loop: engine settle --date 2026-09-14 exit=0
- 2026-09-15T21:03Z daily_loop: card settle --date 2026-09-14 exit=0
- 2026-09-15T21:03Z daily_loop: nfl card settle --date 2026-09-14 exit=0
- 2026-09-15T21:03Z daily_loop: tennis discover
- 2026-09-15T21:03Z daily_loop: tennis results --date 2026-09-14
- 2026-09-15T21:03Z daily_loop: budget --probe tennis_h2h
- 2026-09-15T21:03Z daily_loop: live settle --date 2026-09-14
- 2026-09-15T21:04Z daily_loop: fit_card_calibration exit=0
- 2026-09-15T21:04Z daily_loop: eod --date 2026-09-14 exit=0
- 2026-09-15T21:04Z daily_loop: postmortem --date 2026-09-14 exit=0
- 2026-09-15T21:04Z daily_loop: train exit=0
- 2026-09-15T21:04Z daily_loop: closing-audit exit=0
- 2026-09-15T21:04Z daily_loop: calibration_drift_audit exit=1
- 2026-09-15T21:04Z daily_loop: test_tier_ladder exit=0
- 2026-09-15T21:04Z daily_loop: research-readiness exit=0
- 2026-09-15T21:04Z daily_loop: prereg-clv exit=0
- 2026-09-15T21:22Z afternoon_slate: engine slate --date 2026-09-15 exit=0
- 2026-09-15T21:22Z afternoon_slate: card publish --date 2026-09-15 exit=0
- 2026-09-15T21:22Z afternoon_slate: engine slip --date 2026-09-15

## 2026-09-15 ~21:50Z — hourly cloud routine: no NEW escalation, no unclaimed Tue-9/15 item; diagnosed why R16-06's readiness line hasn't flipped (it's a one-day wait, not a bug)

Start-of-run check: pulled the working branch clean at `d4cc4f43`.
`gh`-less GitHub check via the Actions MCP tools: `daily-loop` has had no
new scheduled run since the 14:30Z failure already explained in the
19:57Z section; `forward-capture` runs 346-355 all `success` or
`in_progress` (normal chaining); `balldontlie-harvest` run 5
(35014512871) still `in_progress` since 19:35Z, well inside its
330-minute budget, so the standing "keep one harvest run active"
instruction needed nothing; `afternoon-slate` runs all green except the
already-explained pre-fix 17:40Z failure. Read the most recent
`daily-loop` job log directly (run 35022286676, 20:55-21:05Z) end to end:
both acknowledged patterns fired as `KNOWN`, no `NEW` `ESCALATE:` line —
nothing here outranks the queue.

**Queue check.** Every Stage 16 row dated Tue 9/15 is DONE, RUNNING (owned
by this or another session with evidence inside the 2-hour reclaim
window), or BLOCKED_HUMAN; nothing is OPEN and dated today or earlier
(R16-36 is real but dated Wed 9/16, not yet eligible). R16-34 and R16-35
still carry their 20:36Z local-session stamp (under 2 hours old) —
left alone, same reasoning as the 19:57Z run. R16-03's "verify tonight's
MLB window" isn't actionable yet; tonight's window hasn't happened.

**R16-06's evidence was stale** (its commits, 45aa0dad/cba4ce88, are from
~09:50-10:00 Pacific, well past the 2-hour mark) with a clear, checkable
remaining acceptance line, so this run dug into it rather than doing
nothing. Read the same 20:55-21:05Z `daily-loop` job log for the
`research readiness` step: it still prints `ESCALATE: 14 forward-test
system(s) now have 30+ graded selections` (matched `KNOWN` against the
ledger, so the job still went green — this is not a new problem). Traced
why: `src/engine/settle_slate.py`'s `run_settle` only calls
`append_scorecard` when the run "actually settled something new" — a
deliberate idempotency guard, not an oversight (its own docstring says
so). Today's dispatch settled `--date 2026-09-14` again and every one of
the ~30 systems logged `settled 0 new (N already settled)`, because
2026-09-14 was already fully closed out **before** the battery wiring
(45aa0dad) landed at 16:50Z today. Confirmed directly against the data:
`evidence/scorecards_v2.jsonl`'s last commit is still `2f5e1d71` ("Daily
loop 2026-09-15", 10:15:48Z — before the wiring), and the newest `window`
on file for all five top-ranked ready systems is still 2026-09-14 with
`battery_verdict: NOT_RUN`. Since `daily_loop.sh` always settles
*yesterday's* date, the first window that gets settled for the first time
after the wiring is 2026-09-15 — which only becomes "yesterday" on the
next calendar day's run, ~2026-09-16 10:00Z. **No code change needed or
possible today.** Recorded this diagnosis in R16-06's Evidence
(`docs/ROADMAP.md`, commit `74c66bad`) so no future run re-derives it or
mistakes this for something to fix; the next run on or after 2026-09-16
should just re-check the `research-readiness` step and, if it reads
`INFO`, mark the ledger row fixed and the item DONE.

Verified this run: full suite (`python -m unittest discover -s tests -t .`,
7268 tests, 447 skipped, 0 failures); `python scripts/publication_audit.py`
clean. No `web/` files touched, so no extra web test files needed.

Commits this run: `74c66bad` (roadmap R16-06 evidence) and this section
(next commit hash after push). No `data/app`, no `data/raw`, no
force-push.

Blockers: none new. Standing blockers unchanged: R16-33's key/rate-limit
question (owner), per-sport pricing decisions (R16-28), the API-Tennis
trial call (R16-22), R16-02's roadmap-evidence close-out (same rate-limit
question), R16-06 waiting on 2026-09-16's daily settle as diagnosed above.
- 2026-09-15T21:52Z afternoon_slate: engine slate --date 2026-09-15 exit=0
- 2026-09-15T21:52Z afternoon_slate: card publish --date 2026-09-15 exit=0
- 2026-09-15T21:52Z afternoon_slate: engine slip --date 2026-09-15
- 2026-09-15T22:20Z afternoon_slate: engine slate --date 2026-09-15 exit=0
- 2026-09-15T22:20Z afternoon_slate: card publish --date 2026-09-15 exit=0
- 2026-09-15T22:20Z afternoon_slate: engine slip --date 2026-09-15
