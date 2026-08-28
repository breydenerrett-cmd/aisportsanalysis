# Overnight run log

**Started 2026-08-28.** Updated continuously. Chat stays short; this is the detail.

## Status

| | |
|---|---|
| **Demo** | **working** — `artifacts/demo_latest.html`, opens from `file://` |
| Tests | 860 passing |
| Detectors registered | 9 |
| Credits spent | ~8,100 of 100,000 |
| Backfill | running, 3 seasons h2h+totals |

## How to open the demo

    python -m src.cli brief --date 2026-08-28 --f5

Writes `artifacts/briefing.html`. Double-click it, or open the tracked snapshot
`artifacts/demo_latest.html`. No server, no network, no dependencies.

## What works end to end

- **Briefing dashboard** — every game, ranked findings in plain language, full
  drill-downs, evidence label on every claim, missing data shown as missing.
- **Detector framework** — `claim / value / baseline / sample / surprise /
  confidence / market relevance`. A signal without a baseline raises.
- **Implied bullpen assessment** — full-game minus first-five fair probability
  is the market's own bullpen opinion. Tonight it gives BOS 4.4 points from
  innings 6–9 at Yankee Stadium.
- **Bullpen availability** — 1,004 appearances from boxscores; availability
  inferred from usage with the reason attached to every rating.
- **Platoon mismatch** — on 2026-08-27: *"TOR's starter allows 0.817 OPS to
  lefties against 0.571 to righties, and KC is starting 7 of 9 left-handed
  hitters against him tonight."*
- **Matchup history, both directions** — the aggregate when it clears 60 career
  at-bats, and the debunk when it does not: *"Mookie Betts is 7-for-18 lifetime
  against tonight's starter. That is 18 at-bats — it will be quoted somewhere
  today and it means nothing."*
- **Stale book** — 11 books captured per game instead of 1; an outlier price is
  arithmetic, not prediction.
- **Travel load** — SEA flew 2,066 miles east across 2.9 zones into Toronto.
- **Run environment** — 94F in Anaheim tonight against a typical 74F.
- **Starter mismatch**, ported onto the framework from the scanner.

## Data on disk

| Set | Size |
|---|---|
| Game results | 9,291 games, 2023–2026 |
| Pitcher game logs | 2025 + 2026 complete; 2023–24 building |
| Bullpen appearances | 1,004 across 116 games |
| Handedness + splits | cached per player |
| Historical odds | backfilling |

## Blockers

- **Wind direction** — `orientation_deg` is `None` for all 30 parks by design.
  Reported, never interpreted.
- **Reverse line movement** — no public bet-percentage source exists for us.
  Marked blocked rather than faked from price movement.
- **Steam** — 3 snapshots/day cannot support the claim; only coarse directional
  movement is honest at that density.
- **Historical splits** — season-to-date splits are safe live and a leak
  historically. `assert_point_in_time` raises; game-log reconstruction needed.

## Next

1. Finish the odds backfill; validate closing-price matching across a full season
2. First-five backfill for historical scanner candidates
3. Third-time-through-order and pitch-mix detectors
4. Discovery pass on 2023–24
5. FDR machinery and the frozen decision policy
