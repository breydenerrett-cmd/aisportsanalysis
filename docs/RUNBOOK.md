# RUNBOOK — operator guide (for Brey or any human)

## What runs on its own

| cadence | what | how |
|---|---|---|
| hourly | roster/lineup/transaction watch + dense odds grid + F5 close pass | trigger runs `bash scripts/forward_capture.sh` |
| daily 10:00 UTC | snapshot, ingest, briefing, settle, grade | trigger runs `bash scripts/daily_loop.sh` |
| 4-hourly | autonomous build loop (roadmap queue) | model session, works docs/ROADMAP.md |

Both scripts commit and push data changes themselves and print `ESCALATE:`
lines for the only conditions needing attention (credit floor, missed
capture window, settlement gap, crash).

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

## Forward-ledger row kinds

`evidence/forward_ledger.jsonl` is append-only; every row has a `kind`:

- `recommendation` — what the system knew before first pitch (`ledger.record_slate`).
- `settlement` — the final result and closing price, written once
  (`ledger.settle`). A null `closing` on an old row is permanent — the
  original line is never rewritten — but see the next kind.
- `closing_backfill` — added 2026-09 to repair settlements whose `closing`
  was wrongly null because of the club-abbreviation/full-name join bug
  fixed in commit 65f499a (`src.pipeline.snapshots.game_key`). Never
  edits the settlement it corrects; it is a separate row carrying `ref`
  (the settlement's `game_pk`), `closing_price`, `closing_observed_utc`,
  `closing_source`, `derived_utc`, `clv`, and `reason`. A settlement that
  already had a non-null closing is never touched. Produced by
  `python3 -m src.cli closing-backfill` (`--dry-run` to preview; see
  `closing-audit` for a read-only count of what is derivable). Readers
  should call `grading.effective_closing`/`grading.read_backfills` rather
  than reading a settlement's `closing` field directly, so the preference
  rule (prefer the backfill only when the original is null) lives in one
  place. CLV on a backfill row is h2h-only — there is no backfill
  mechanism for spreads, totals, or first-five closes, and this project
  does not add one; see the coverage paragraph below for what IS measured
  for those markets.

**Per-market closing coverage (L17).** `python3 -m src.cli closing-audit`
reports, for every settled game and each of four markets (h2h, spreads,
totals, first_five), whether a closing observation can be identified —
read-only, backfill-aware, and it never writes to the ledger. h2h/spreads/
totals are all captured together in `odds_snapshots.jsonl` by the same
bulk capture call, so their coverage tracks together; first_five is
captured separately and far more sparsely into `f5_close.jsonl` (a
single per-event snapshot near first pitch, not a running series), so its
coverage is a different, usually much lower, number. The table's four
columns read left to right: `settled` (every settled game, regardless of
what was actually recommended for it — the question is what the CAPTURED
STORES cover, not what was bet), `recorded` (already evidence on the
ledger — today only ever nonzero for h2h, via the original `closing`
field or a `closing_backfill` row), `derivable` (a close the store could
supply right now but that is not recorded anywhere — always a dry-run
number for spreads/totals/first_five, since no backfill path exists for
them), and `not derivable`, broken down by reason: `not_captured` (this
market's store holds no observation of the game at all — most of
first_five's gap, since the store started running weeks after most
settled games) versus `no snapshot observed before first pitch` (an
observation exists but arrived too late to count as a close, same PIT
rule `closing_observation` has always used). `recorded + derivable + not
derivable` sums to `settled` for every market row.

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
