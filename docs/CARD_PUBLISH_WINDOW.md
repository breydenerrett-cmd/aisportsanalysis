# The card publishes too late, one day in five

**Measured 2026-09-10.** Needs a one-line change on the default branch that
I am not able to make; everything else here is done.

---

## The defect

`card publish` runs from exactly one place — `scripts/afternoon_slate.sh`,
fired by `.github/workflows/afternoon-slate.yml` on `cron: "10 21 * * *"`,
which is **5:10pm Eastern**.

`run_slate`'s first-pitch guard skips games already under way. That guard is
correct — a card cannot freeze a bet after the game has started — but at
5:10pm Eastern it throws away the entire afternoon.

`daily_card.MIN_PICKS` is 3, and the standing rule is three to five bets a
day, no matter what.

## What it costs, over the last 45 slates

From `data/historical/mlb_results.csv`, counting games whose first pitch is at
or after each candidate publish time:

| publish (ET) | UTC cron | days with fewer than 3 games open | share of all games excluded |
|---|---|---|---|
| 11:40 | `40 15 * * *` | **0 (0%)** | **0%** |
| 13:40 | `40 17 * * *` | 0 (0%) | 10% |
| 15:40 | `40 19 * * *` | 1 (2%) | 24% |
| **17:10** | **`10 21 * * *`** | **8 (18%)** | **33%** |

**One day in five the automatic card physically cannot make three picks.**
Sundays are worst — 2026-08-23 and 2026-08-30 each left **one** game open out
of fifteen, and 2026-09-06 left two out of fifteen.

Today's own card is the clearest case: of its five games, three started before
5:10pm ET. The automatic run would have had two candidates.

That card exists only because it was published by hand at 10:36am ET during a
working session. **The scheduled job has never produced a full card on a
normal slate.**

## The fix

`cron: "10 21 * * *"` → `cron: "40 15 * * *"` (11:40am ET).

11:40 is chosen as the **latest time that costs nothing**: the earliest first
pitch in the sample is 12:10 ET, so it is pre-game for every game on every
slate in it, and later means a more mature board.

### What it costs, stated

Evening lineups are not posted at 11:40 — they land 17:16Z–22:39Z. **The card
does not read lineups.** That is the player-props surface, which does not
ship (`docs/DOES_THE_MODEL_BEAT_THE_MARKET.md`). So the cost is board depth
rather than correctness.

The 2026-09-10 card settles the question directly: published at 10:36am ET, it
priced a 7:05pm game across **eight books**. Fewer than the afternoon games'
eleven, and enough.

## Why it is not already done

**The schedule lives on the default branch and the code does not.**

GitHub reads `schedule` from the default branch's copy of a workflow file.
Here that is `claude/cowork-session-migration-tn3sx2`, whose
`afternoon-slate.yml` carries `cron: "10 21 * * *"` and whose job body does
`actions/checkout@v4` with `ref: claude/sports-betting-analysis-review-g1o0co`
— the working branch — for everything else.

So editing the cron on the working branch produces a file that reads correctly
and fires at the old time. The working branch's copy now carries a warning
saying exactly that, so nobody reads it as done.

Changing production scheduling is the owner's call and the attempt was
blocked, which is the right gate. **The change needed is one line, on
`claude/cowork-session-migration-tn3sx2`, in
`.github/workflows/afternoon-slate.yml`.**

## The wider trap

This is the second thing tonight that was broken by the split between the
default branch (schedules, workflow definitions) and the working branch (code):

1. `deploy-staging.yml` restores a data cache that lives on the default
   branch's scope and is invisible to the working branch, so every deploy
   ships with an empty `data/historical/` —
   `docs/INCIDENT_2026-09-10_SPINNING_SLATE.md`.
2. This.

`scripts/reachability_audit.py` walks the working tree's workflows. Until it
reads the **default branch's**, a job that is wired only on the working branch
looks reachable while cron never runs it — which is precisely how both of
these stayed invisible.
