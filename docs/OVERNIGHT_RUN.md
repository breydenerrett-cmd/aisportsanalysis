# Overnight run log

**Started 2026-08-28.** Updated continuously. Chat stays short; this is the detail.

## Status

| | |
|---|---|
| Demo | not yet built |
| Tests | 709 passing |
| Credits spent this run | 41 of 100,000 (probes only) |
| Credits remaining | ~99,959 |

## Completed

- 2023 + 2024 results ingested — store now holds 9,291 games across 4 seasons
  (2023: 2,430 · 2024: 2,429 · 2025: 2,428 · 2026: 2,004)
- Historical odds access verified on the paid plan; 10 credits per slate snapshot,
  20 credits per game for first-five, 1 credit for a historical events list
- `src/pipeline/backfill.py` — resumable, budget-enforced, manifest-checkpointed
- Roadmap approved and committed

## In progress

- Detector framework

## Blockers

- Wind vector detector: `orientation_deg` is `None` for all 30 parks by design
- Reverse line movement: no public bet-percentage source exists for us
- Steam: 3 snapshots/day cannot support the claim; renamed to coarse movement

## Next

1. Detector framework
2. First end-to-end dashboard, then snapshot to `artifacts/`
3. Lineup + reliever + splits data layer
4. Priority detectors
5. Staged backfill
