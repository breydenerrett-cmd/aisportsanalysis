# NHL pre-lock capture (2026-10-26)

Symptom: members' NHL hounds sat at "waiting for its check time (no fresh board yet)" and often placed nothing.

Measured on the local stores, 7 days to 2026-10-26 (44 NHL games, deterministic read of `odds_multibook.jsonl`
plus its archive; the engine rule is `evaluate()`: board age at the lock must be <= `MAX_BOARD_AGE_MINUTES` = 75):

| lock | games | fresh board at the lock | median age | worst age |
|------|-------|-------------------------|-----------|-----------|
| 60   | 44    | 82%                     | 38 min    | 335 min   |
| 120  | 44    | 73%                     | 42 min    | 275 min   |
| 180  | 44    | 64%                     | 58 min    | 335 min   |

On the 2026-10-24 and 10-25 evening slates (23:10Z to 02:10Z puck drops) the 180 lock found boards 95 to 335
minutes old.

Two causes, both in code, neither in workflow YAML:

1. Phases. `allsports_capture` buys NHL at t24h, t6h, t2h and t30m before a start. A 180-minute lock falls in the
   4-hour hole between t6h and t2h; only an unrelated call for another game of the same key happened to land there.
2. The day's cap. `capture.daily_cap_credits` (1,500, UTC day) was spent by 18:35Z on 2026-10-24 (capture 1,200 plus
   scores 300), so from 17:35Z to 00:07Z no allsports call was made in any sport, through every evening lock.

Fix (`src/pipeline/allsports_capture.py`, `src/capture/budget.py`, `src/sports/catalog.py`, `config/sports_catalog.json`):

- Families flagged `lock_capture` (NHL only) get three extra phases per game, 45 minutes before each lock choice:
  `lock180` at 225, `lock120` at 165, `lock60` at 105 minutes before the start
  (`capture.lock_phases_minutes`). The board at the lock is then at most about 45 minutes old.
- `capture.lock_reserve_credits` (90) is held back from every call that is not buying a lock board, so the cap cannot
  be gone before the evening locks. Reserve refusals skip that call without halting the run; the hard cap and the
  credit floor still stop everything, lock calls included.

Extra credits: an NHL call is 3 credits (h2h, spreads, totals, `us`). Worst case from the last week's schedule is
5 to 11 distinct lock-call times a day, so 15 to 33 credits a day (about 25 average), only on NHL game days. No
change to the daily cap; the reserve moves ordinary spending earlier-stopping by 90 credits on a capped-out day.

To cover another sport, set `"lock_capture": true` on its family in `config/sports_catalog.json`; each such sport
adds its own calls.

Not fixed here: slot cadence. Slots run every 15 to 40 minutes; a late slot can land a lock board after the lock.
The 45-minute lead absorbs a slot gap up to 45 minutes. No workflow YAML change is proposed.
