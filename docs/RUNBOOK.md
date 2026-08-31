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

- Full test suite: `python3 -m unittest discover -s tests -q`
- One matchup: `python3 -m src.cli analyze --away NYY --home BOS`
- Rebuild today's briefing: `python3 -m src.cli brief`
- Ledger settle: `python3 -m src.cli ledger`
- Manual capture (after downtime): `bash scripts/forward_capture.sh`

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
