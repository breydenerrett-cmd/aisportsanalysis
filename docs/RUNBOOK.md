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
4. Open `artifacts/` latest briefing — renders from file://, looks sane.

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
