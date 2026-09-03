# RUNBOOK — operator guide (for Brey or any human)

## What runs on its own

| cadence | what | how |
|---|---|---|
| hourly | roster/lineup/transaction watch + dense odds grid + F5 close pass | trigger runs `bash scripts/forward_capture.sh` |
| daily 10:00 UTC | snapshot, ingest, briefing, **engine slate → engine settle → eod**, ledger settle/grade | trigger runs `bash scripts/daily_loop.sh` |
| 4-hourly | autonomous build loop (roadmap queue) | model session, works docs/ROADMAP.md |

Both scripts commit and push data changes themselves and print `ESCALATE:`
lines for the only conditions needing attention (credit floor, missed
capture window, settlement gap, crash).

### The unattended engine loop (S8, added to `scripts/daily_loop.sh`)

Three steps, always in this order, on the existing 10:00 UTC cadence (well
before the earliest MLB first pitch, ~16:00Z, so `engine slate` sees the
bulk of the day's slate still pre-game):

1. **`engine slate --date TODAY`** — analyzes today's slate through the
   registered systems and places FLAT_1U paper wagers (S5). Skips any game
   already commenced (the existing first-pitch guard in the board/snapshot
   builder) rather than deciding on an in-play board.
2. **`engine settle --date YESTERDAY`** — settles yesterday's paper wagers
   from real results and appends Scorecards (S6a). Runs on yesterday, not
   today, so a game has had a full day to post a final result.
3. **`eod --date YESTERDAY`** — writes the end-of-day self-review to
   `docs/eod/YESTERDAY.md` and the review chain (S7). Runs last, after
   settlement, so it never reads a partially-settled day.

Each step's exit status is captured explicitly and turned into its own
`ESCALATE:` line on failure; a bad step never aborts the other two or the
loop's own commit (same guard style as every other step in this script —
`set -uo pipefail`, no `-e`). Each step's output goes to the loop's own log
(stdout) and a one-line summary is appended to `docs/OVERNIGHT_RUN.md` (the
run note) so the outcome survives past the session transcript that ran it.
`data/paper_accounts/` (one ledger per registered system) and `docs/eod/`
(one report per date) are staged for commit alongside the other data-plane
paths.

**Pre-slate freshness guard (`src/engine/preflight.py`), what step 1
refuses on.** `engine slate` refuses — no board built, nothing staked —
before doing anything else, whenever either of these fails, both checked
every run and both reported together if both fail:

- *Price capture staleness* (`PRICE_CAPTURE_STALE_HOURS = 3`): the newest
  L1 price observation captured for the date being sliced is more than 3
  hours old, or there is none at all. Capture runs hourly
  (`scripts/forward_capture.sh`); 3 hours tolerates two missed cycles
  before treating the board as too old to price a slate off of.
- *Matchup feature coverage* (`MATCHUP_COVERAGE_MAX_LAG_DAYS = 3`): the
  Statcast pitch store's actual ingested coverage (read from its manifest,
  not its declared target) ends more than 3 days before today, or the
  store has no coverage recorded at all.

**Named gap this guard exposes rather than papering over:** the Statcast
pitch store that feeds six of the seven matchup features
(`src/providers/statcast_pitches.py`, `src/pipeline/rebuilt.py`,
`src/research/matrix.py`) is a **manual backfill with no forward-ingest
cadence**. Its coverage currently ends **2026-08-27** — already past the
3-day threshold above — so live matchup features keep aging every day this
gap stays open, and `engine slate` will keep honestly refusing on it until
either the threshold is deliberately widened or a forward pitch-ingest
cadence is built to keep the store's coverage current. That forward-ingest
cadence is itself the follow-up work — **not built here** — that this
guard is standing in for: it stops the engine from quietly betting on
stale matchup inputs in the meantime, at the cost of refusing to slate at
all until the real gap closes.

## Daily health check (30 seconds)

1. `git log --oneline -10` — hourly "Forward capture" commits present?
2. `python3 -m src.cli credits` — credits above 5,000 floor? (~132/day burn)
3. `python3 -m src.cli timing` — V3 event accumulation by class (floors 30).
   Read the MEASURABLE count, not just the admitted count: on 2026-08-31
   there were 33 admitted events and zero of them could be measured.
4. **Count the rows.** The check that matters most, and the one that was
   missing when three collection failures ran concurrently for days:

       wc -l data/processed/*.jsonl data/watch/*.jsonl

   Every store that should be growing must have grown since yesterday. A
   store that is absent entirely is the loudest possible signal — on
   2026-08-31 `f5_close.jsonl` had never been written at all while the
   roadmap believed the lane was accumulating. **Silence is not success:
   no error message is printed when a store is simply never created.**
5. Open `artifacts/` latest briefing — renders from file://, looks sane.
6. `python3 -m src.cli health` — slate coverage, book counts, staleness,
   settlement gaps and anomalies for today.

## Common operations

- Full test suite (parallel, before declaring done): `python3 scripts/test_parallel.py`
  — shards tests/test_*.py across `os.cpu_count()` worker processes and runs
  the forward-store fingerprint check once at the end; measured 2,960 tests
  in ~29s wall on 4 CPUs here, vs ~89s for the equivalent raw
  `python3 -m unittest discover -s tests -q` in the same worktree (that raw
  command still works and stays correct — it's just the 4x-slower way to get
  the same answer, so use the parallel runner instead of typing it).
- Fast tier during development: `bash scripts/test_fast.sh` — the same
  runner minus the ~13 modules in `tests/slow_modules.txt` (parameter
  sweeps and the in-process HTTP app tests, all individually >=4s); finishes
  in single-digit seconds here, budgeted at <=4 minutes on a slower machine.
  Never the last check before declaring done — that's always the full
  parallel run above.
- Re-measure module timings (only needed after a real shift in test scope;
  the parallel runner degrades gracefully to round-robin without this file):
  `python3 scripts/time_tests.py` — writes scripts/module_timings.json.
- One matchup: `python3 -m src.cli analyze --away NYY --home BOS`
- Rebuild today's briefing: `python3 -m src.cli brief`
- Ledger settle: `python3 -m src.cli ledger`
- Manual capture (after downtime): `bash scripts/forward_capture.sh`
- Per-game box lines (props settlement substrate): `python3 -m src.cli
  boxscores --date YYYY-MM-DD` for one date, or `python3 -m src.cli
  boxscores --backfill 2023-03-30..2023-11-01` for a resumable historical
  range. Free, keyless MLB Stats API (`src.providers.mlb.fetch_boxscore` /
  `fetch_linescore`); idempotent by game_pk, so a rerun over the same range
  costs one extra `fetch_results` call per date and no wasted box fetches.
  Writes `data/processed/boxscores_<yyyy>.jsonl` (one pitcher row, one
  batter row per player who recorded a stat, one linescore row per game) --
  tracked forward evidence, same as the odds/weather/credit-log stores.
  `src.board.settle_props.settle` grades one box row against one prop
  selection (win/loss/push/void) but is not wired into the CLI or the daily
  loop yet. The daily loop's step 9 fetches yesterday's box lines
  automatically and never fails the loop on a miss (box lines don't expire,
  so a missed day is retried for free the next run).

## Forward-ledger row kinds

`evidence/forward_ledger.jsonl` is append-only; every row has a `kind`:

- `recommendation` — what the system knew before first pitch (`ledger.record_slate`).
- `settlement` — the final result and closing price, written once
  (`ledger.settle`). A null `closing` on an old row is permanent — the
  original line is never rewritten — but see the next kind.
- `closing_backfill` — added 2026-09 (L14) to repair h2h settlements whose
  `closing` was wrongly null because of the club-abbreviation/full-name
  join bug fixed in commit 65f499a (`src.pipeline.snapshots.game_key`),
  and extended 2026-09 (L18) to also record spreads and totals closes,
  which `ledger.settle` has never had a writer for at all. Never edits
  the settlement it corrects; it is a separate row carrying `ref` (the
  settlement's `game_pk`), `market` (`h2h`/`spreads`/`totals` — absent on
  every row written before L18, which readers must treat as `h2h`),
  `closing_price` (both the line/point and the price per side, whatever
  the store captured for that market), `closing_observed_utc`,
  `closing_source`, `derived_utc`, `clv`, and `reason`. An h2h settlement
  that already had a non-null closing is never touched; spreads and
  totals have no such original field to protect, so every not-yet-backfilled
  settled game is a candidate for them. Produced by
  `python3 -m src.cli closing-backfill --market {h2h,spreads,totals,all}`
  (default `h2h`, preserving pre-L18 behaviour; `--dry-run` to preview;
  see `closing-audit` for a read-only count of what is derivable).
  Readers should call `grading.effective_closing`/`grading.read_backfills`
  (both now take a `market=` argument, defaulting to `h2h`) rather than
  reading a settlement's `closing` field directly, so the preference rule
  (prefer the backfill only when the original is null) lives in one
  place. CLV is graded only for h2h — a spreads/totals backfill row always
  carries `clv_graded: False` with a `clv_reason` naming the missing
  fair-price model, because comparing prices across markets where the
  line itself can move needs a model this project does not have, and
  nothing here fabricates one. first_five still has no backfill mechanism
  at all — see the coverage paragraph below for what IS measured for it.

**Per-market closing coverage (L17, backfill-aware for h2h/spreads/totals
since L18).** `python3 -m src.cli closing-audit` reports, for every
settled game and each of four markets (h2h, spreads, totals, first_five),
whether a closing observation can be identified — read-only, and it
never writes to the ledger itself. h2h/spreads/totals are all captured
together in `odds_snapshots.jsonl` by the same bulk capture call, so
their coverage tracks together; first_five is captured separately and
far more sparsely into `f5_close.jsonl` (a single per-event snapshot near
first pitch, not a running series), so its coverage is a different,
usually much lower, number. The table's four columns read left to right:
`settled` (every settled game, regardless of what was actually
recommended for it — the question is what the CAPTURED STORES cover, not
what was bet), `recorded` (already evidence on the ledger — h2h via the
original `closing` field or a `closing_backfill` row; spreads and totals
via a `closing_backfill` row only, since they have no original field;
first_five never, with no backfill path for it), `derivable` (a close the
store could supply right now but that is not recorded anywhere — zero for
h2h/spreads/totals once `closing-backfill --market all` has run to
completion; always a dry-run number for first_five), and `not derivable`,
broken down by reason: `not_captured` (this market's store holds no
observation of the game at all — most of first_five's gap, since the
store started running weeks after most settled games) versus `no
snapshot observed before first pitch` (an observation exists but arrived
too late to count as a close, same PIT rule `closing_observation` has
always used). `recorded + derivable + not derivable` sums to `settled`
for every market row.

## Failure playbook

- **"skipped: credit floor"** — spending stopped by design. Decide whether
  to raise budget; nothing resumes spend without you.
- **Missed capture windows** — gone forever; logged in
  docs/OVERNIGHT_RUN.md. Never backfilled — accept the gap.
- **A store stopped growing (or never started)** — treat as an outage, not
  a quiet day. Run the capture manually and read its full output rather
  than its exit code; a pass that captures nothing still exits 0. Check
  whether the store's path is tracked by git
  (`python3 -m unittest tests.test_forward_evidence_tracked`) — an untracked
  forward store is one container recycle from being lost, which is exactly
  how five days of prices nearly disappeared on 2026-08-31.
- **Settlement gap alert** — `python3 -m src.cli ledger` after results
  exist; if it persists, a game's result mapping failed — investigate,
  don't hand-edit the ledger.
- **Savant/API outages** — ingest and capture retry with backoff; a failed
  window is recorded and refetched next run where possible.

## What requires your explicit approval (hard gates)

Sealed 2026-01-01→08-27 evaluation (one shot, ever) · Ranker Engine 2
activation · any real-money capability (never) · large historical data
purchases · spend beyond the dense grid + small probes.

## Keys and data

- `ODDS_API_KEY` lives only in `.env` (gitignored). New machine: recreate it.
- All forward stores are append-only JSONL under `data/`; treat as evidence.
