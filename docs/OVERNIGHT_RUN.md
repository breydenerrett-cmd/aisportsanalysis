# Overnight run log

**Started 2026-08-28.** Chat stays short; this is the detail.

## Status

| | |
|---|---|
| **Demo** | **working** — `artifacts/demo_latest.html` |
| Tests | 884 passing |
| Detectors | 11 registered, 1 blocked with a stated reason |
| Credits | ~36,000 spent of 100,000 |
| Odds backfill | 3 seasons h2h+totals, nearly complete |
| First-five backfill | running, 732 candidate games |

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
| Historical odds | 3 seasons, 3 snapshots/day |
| Historical first-five | 732 candidate games |
| Scanner candidates | 732 of 7,287 games (10.0%) |

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
