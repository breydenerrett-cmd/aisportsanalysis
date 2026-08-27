# aisportsanalysis

MLB betting analysis. Free-data alpha.

Nothing here claims an edge. The system collects data, removes bookmaker margin
correctly, and reports honestly what it does and does not know. Whether the
model beats the market is an open question that the plan below is designed to
answer — including the possibility that the answer is no.

## Status

| Component | State |
|---|---|
| De-vig / odds maths | Built, 38 tests |
| Calibration metrics | Built, 36 tests |
| Stake sizing | Built, flat by default |
| Ballpark data | Coordinates yes, orientations **unverified** |
| MLB results + backfill | Built and verified live |
| Historical store | Idempotent, resumable, manifest-tracked |
| Odds snapshots / CLV | Built, capturing |
| Weather | Built and verified live |
| Odds provider | Built, key-gated, all 3 markets |
| Slate pipeline | Built and verified live |
| **Probability model** | **Does not exist — scoring is uncalibrated** |
| **Backtest** | **Never run** |
| **Graded picks** | **Zero** |

350 tests, no network access in the suite (enforced in CI), zero runtime
dependencies beyond the Python standard library.

## Quick start

```bash
python -m src.cli status                          # what is configured
python -m src.cli slate 2025-07-09                # build a slate
python -m src.cli results 2025-07-09              # what is actually final
python -m src.cli ingest 2025-03-20 2025-11-05    # build the historical store
python -m src.cli history                         # coverage + integrity of that store
python -m src.cli snapshot                        # capture odds now (run on a schedule)
python -m src.cli movement                        # line movement captured so far
python -m src.cli credits                         # odds API cost before you schedule
python -m src.cli calibration-demo                # see the metrics work
```

Everything except odds works with no configuration at all. For odds:

```bash
cp .env.example .env       # then add a key from the-odds-api.com
```

With no key, price columns stay blank and the run says so. Nothing is
fabricated to fill a gap.

## Design rules

These are enforced in code and tests, not just documented.

**Never fabricate a value.** A blank field is correct; a guessed one is
corruption that surfaces months later as a model that backtests well and loses
live. `weather_wind_dir` does not exist as a column because park orientations
are unverified — an invented bearing would invert a real effect.

**Always de-vig before computing edge.** A −150/+130 moneyline implies 103.5%
total probability. Comparing a model probability against raw implied
probability overstates edge, worst on favorites — exactly where a betting
system is most likely to talk itself into a bad wager. See `src/core/odds.py`.

**Uncalibrated means uncalibrated.** Every probability carries a flag. Kelly
sizing refuses to run while that flag is set and falls back to flat staking,
because Kelly sizes up precisely on the bets an overconfident model is most
wrong about.

**Backfill, don't wait.** The MLB API serves decades of completed games.
Measured: 96 final games in 3.4 seconds, so a full season is about 2 minutes.
Waiting for tonight's games to settle takes a season to build the same sample.

**Fail safe and say why.** Missing key, missing weather, unmatched odds — each
leaves a blank, records a warning, and continues. A run reports its own
coverage rather than asserting completeness.

## Layout

```
src/core/       odds maths, calibration metrics, stake sizing
src/data/       ballpark reference data and wind geometry
src/providers/  MLB Stats API, Open-Meteo, The Odds API
src/pipeline/   slate assembly
src/cli.py      command line entry point
docs/           source audit, validation criteria, orientation method
```

## Documents worth reading before changing anything

- [`docs/VALIDATION_CRITERIA.md`](docs/VALIDATION_CRITERIA.md) — pass/fail
  thresholds, pre-registered before any results exist. Committed first
  deliberately.
- [`docs/HISTORICAL_SOURCES.md`](docs/HISTORICAL_SOURCES.md) — what a backtest
  costs. Short version: **$59 one-time** for three seasons of moneyline closing
  lines. Daily operation fits the free tier.
- [`docs/PARK_ORIENTATION.md`](docs/PARK_ORIENTATION.md) — how to make wind a
  live model input, roughly an hour of work.

## What is next

The blocker is not more inputs. It is that the model emits a weighted score
rather than a calibrated probability, and a score cannot be compared to a price.

1. Reconstruct point-in-time features so historical rows carry only what was
   knowable before first pitch.
2. Decide on the $59 historical odds backfill.
3. Fit and validate a probability model against the de-vigged market.
4. Only then does "edge" mean anything.

## Not betting advice

No component places wagers or is capable of doing so. Nothing here should be
read as a recommendation to bet money.
