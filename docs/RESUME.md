# RESUME — cold-start handoff (keep current; updated 2026-08-31)

Any capable AI session should be able to continue the program from this file
plus docs/ROADMAP.md. Read both, then run the standing loop in ROADMAP's
AUTONOMOUS CONTROL section.

## What this project is

MLB betting-analysis research program for Brey (breydenerrett@gmail.com).
Two products: the **Analyzer** (deep honest per-matchup analysis; shipping)
and the **Ranker** (bet list; GATED — Engine 2 is None until four unlock
conditions plus Brey's sign-off; a test enforces the gate).

## State of the evidence (do not re-litigate)

- V1 (13) · V2 (5) · V4 (6) · V5 (3) = 27 pre-registered hypotheses,
  **zero survivors**. All losers published in docs/RESULTS_* and
  docs/RESEARCH_V4/V5 files. New season-level features alone are not edge.
- Elo benchmark: the close beats a tuned pitcher-free Elo by 0.008
  log-loss/game (p=0.0003) — the yardstick for any data acquisition.
- Live research lanes: **V3 information timing** (frozen prereg in
  docs/RESEARCH_V3_TIMING.md; grade-B events accumulating; class floor 30;
  check `python3 -m src.cli timing`) and **market depth** (F5 closes
  accumulating in data/processed/f5_close.jsonl).
- Falsification battery RULES_VERSION 2.0.0, frozen at the adjudicated
  validation gate (docs/VALIDATION_GATE.md).

## Standing rules (never relax; Brey's words)

No real-money betting or bet-capable code · no fabricated values (None over
guess) · no future leakage · no hidden losers · no retroactive
recommendation changes · pre-registration + FDR + battery before promotion ·
2025 = tuning only · **2026-01-01→08-27 SEALED** (Brey's explicit approval,
one evaluation, ever) · line shopping = PRICE IMPROVEMENT, never EV/edge ·
never call late_move "CLV" · credits: floor 5,000 absolute, ~132/day dense
envelope; "skipped: credit floor" = stop and tell Brey · forward data is
sacred and append-only · preserve artifacts/demo_latest.html · no model
identifiers in commits/PRs.

## Operating architecture

- **Orchestrator** decides; **Opus workers** (.claude/agents/opus-*.md)
  execute; **scripts** collect: `scripts/forward_capture.sh` (hourly trigger)
  and `scripts/daily_loop.sh` (daily trigger). React ONLY to their ESCALATE
  lines.
- Branch: `claude/sports-betting-analysis-review-g1o0co`. Commit and push
  every completed unit. API key in gitignored `.env` (ODDS_API_KEY) — a
  fresh clone lacks it.
- Tests: `python3 -m unittest discover -s tests -q` (~1,640, all green at
  every commit).
- Chat with Brey: EXTREMELY concise, few lines, detail goes in docs/.

## Where work state lives

- docs/ROADMAP.md — horizons, current task, ready queue, backlog, gates.
- docs/OVERNIGHT_RUN.md — running operational log.
- docs/VALIDATION_GATE.md, RESEARCH_*.md, RESULTS_*.md, BENCHMARK_ELO.md,
  COLLECTION_POLICY.md — the evidence record.
- data/research/*.json — frozen families and run results (immutable).
- Ledger: data/ledger/ via src/pipeline/ledger.py (append-only).

## If resuming after a usage limit or crash

1. `git status` / `git log` — commit or recover any uncommitted unit.
2. Check trigger backlog (hourly capture, daily loop) — run
   `bash scripts/forward_capture.sh` if captures were missed; record missed
   windows honestly, never backfill.
3. Re-enter the ROADMAP loop at CURRENT TASK.
