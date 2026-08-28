# Overnight run log

**Started 2026-08-28.** Chat stays short; this is the detail.

## Status

| | |
|---|---|
| **Demo** | **working** — `artifacts/demo_latest.html` |
| Tests | 884 passing |
| Detectors | 11 registered, 1 blocked with a stated reason |
| Credits | ~47,000 spent of 100,000 |
| Odds backfill | **complete** — 1,800 snapshots, 0 failures |
| First-five backfill | 525 games stored, second pass running for 194 afternoon games |

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
| Historical first-five | 732 candidate games |
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

Q5, blocked since the project began, is answered. On 367 candidate games from
2023–24 with stored first-five prices:

| | Games | Share |
|---|---|---|
| Passes the market screen | 158 | 43.1% |
| Screened out as already priced | 63 | 17.2% |
| **No first-five price offered at all** | **136** | **37.1%** |

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
