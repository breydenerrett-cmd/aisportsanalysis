# Weekend autonomous plan — 2026-09-04 → Monday

Owner (Brey) is away. The parent session orchestrates; workers execute.
Source of truth for work: `docs/WEEKEND_QUEUE.md`. Progress ledger:
`docs/WEEKEND_PROGRESS.md` (append-only). Monday: `docs/WEEKEND_HANDOFF.md`.

## Starting checkpoint (verified 2026-09-04 21:2xZ)

- F5 universe frozen at `ed0373f`; independently recomputed from persisted
  data this session: 4,315 eligible, 4,298 OK, 17 unavailable, 3,682
  gradeable, 1,597 / 2,085 season split, MDE 1.62pp, hash
  `c675086…33cd1c` reproduced, 0 eligible 2025/2026. `tests/test_f5_universe.py`
  guards drift (12 tests).
- `register_family` NOT called. Draft prereg pending Opus review (running).
- Capture healthy: >100 odds artifacts today post-fix; live band 233/900
  spent; monthly balance 25,555 (floor 5,000).
- L25 repo side pushed (`04d1e4f`); cutover blocked on owner secrets.

## Cycle procedure (every hourly wake)

1. Read the queue. 2. `git status`, `git worktree list`, live workers.
3. **Capture health first** via the canonical helper (`W1`); if not
   RUNNING/HEALTHY_IDLE, all optional research stops. 4. Reclaim dead
   workers. 5. Take the highest-priority READY task with deps satisfied
   (one at a time). 6. Execute → verify independently → path-specific
   staging → commit → push. 7. Update queue + progress. 8. Continue if
   capacity remains, else exit cleanly. Never dispatch a duplicate of a
   task already RUNNING.

## Priority order

P0 capture protection → P0 capture externalization → P0 freeze
verification (done) → P0 methodology review → prereg finalization →
preregistered discovery/replication → F5 results doc → P1 totals
methodology → P1 factory scale prep → P1 reasoning loop → P1 daily loop.

## Model routing

Fable orchestrates. Haiku: reads/inspection. Sonnet: implementation.
Opus: methodology/adversarial review only, with an evidence packet.
Deterministic scripts before model tokens.

## Hard limits (BLOCKED_HUMAN, never autonomous)

New paid spend beyond approved envelopes; unsealing 2026; real-money
anything; changing frozen methodology after outcomes; deleting data;
destructive git; secrets; destructive deploys.
