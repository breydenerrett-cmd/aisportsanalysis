# API memory profile (why staging is OOM-killed), 2026-09-28

Measured locally (Windows, Python 3.14; working set sampled every 20 ms) by
replaying the deploy's own health-check sequence
(`.github/workflows/deploy-staging.yml:190-271`) against one uvicorn process
started the way the image starts it (`APP_PUBLIC_DEMO=1`, warm-up on). Fly's
staging VM is 1,024 MB; production is configured at 512 MB.

## Finding

The kill happens in the STARTUP WARM-UP PASS (`api/warmup.py`, 8 items x 2
dates), before the page checks: peak 1,479 MB working set / 1,465 MB private.
The page checks then hit a dead process (`/today -> 000`). The engine
decisions join is real but is the second contributor, not the trigger.

| warm-up item | added over its start | cause |
|---|---|---|
| tennis_board | +1,295 MB | `src/report/tennis_board.py:68` reads the whole odds store (809,468 rows, 259 MB JSON) to keep 2,475 tennis rows |
| nfl_card | +753 MB | `src/report/nfl_card.py:286` reads the whole store |
| today | +523 MB | `api/today.py:152-154` passes no `date`, so `briefing.py:98` -> `prices.py:352` reads every MLB row |
| mlb_card | +444 MB | `card.py:845-847` loads the whole batter-props store (fingerprinted path; left alone) |
| props | +357 MB | `props.py:130` -> `batter_props.read_processed()` (fingerprinted path; left alone) |

Per-route (warm-up off): worst checked route `/today` +570 MB; `/daily`
+760 MB (not checked by the deploy). Engine join
`engine_bridge.decisions_for_date('2026-09-27')`: +351 MB to return 393
rows (1.2% of the ledger). `derivative_markets.jsonl` +308 MB and
`batter_props.jsonl` +362 MB are loaded whole and filtered afterwards.
Stale-while-revalidate caches hold only 0.8 MB of values; the problem is an
overlapping background rebuild (`freshness.py:294-330`) plus a request's own
build: 1,029 MB peak 135 s after the pass. `_RELIEF_LOG` (`card.py:99-117`)
keeps 75 MB permanently. Floor after the sequence: 315 MB.

## Fixes simulated in memory (nothing changed in the repo at the time)

| change | before | after |
|---|---|---|
| tennis board: stream with a keep predicate | +1,324 MB | +6 MB |
| NFL card: stream by commence date (newest per key on Sundays) | +771 MB | +67 MB off-day, +431 MB Sunday |
| `/today`: pass `date` like `/games` does | +574 MB | +239 MB |
| engine join: event ids first, then stream the ledger | +351 MB | +1 MB |
| derivative store: filter by game_date while reading | +328 MB | 0 |
| warm-up peak, all fixes | 1,479 MB | 397 MB |
| page checks with stale caches, all fixes | 1,029 MB | 626 MB |

Production at 512 MB still needs background rebuilds limited to one in
flight; the fingerprinted batter-props path stays as is until the
off-season fingerprint change.

## Repeat

Server: `env -u API_TENNIS_KEY -u GEMINI_API_KEY -u FAL_KEY APP_PUBLIC_DEMO=1
WARM_INTERVAL_SECONDS=0 python -m uvicorn api.app:app --port 8012`; sample
`K32GetProcessMemoryInfo` every 20 ms; request the health-check list in
order; repeat 135 s later. Component probe: a fresh process that evaluates
one expression (e.g. `HashChainLedger('evidence/decisions_v2.jsonl').read()`
= 33,252 rows, +311 MB) under the same sampler.
