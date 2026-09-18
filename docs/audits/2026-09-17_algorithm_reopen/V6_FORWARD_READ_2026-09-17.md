# V6 forward replication: it cleared its floor, and it did not replicate

2026-09-17. This supersedes `URGENT_V6_NOT_ACCUMULATING.md`, which was wrong
in its central claim. Both documents are kept.

## What I got wrong

I reported that `V6:lineup_surprise_direction:h2h` had "collected nothing for
six days" because `scripts/probe_lineup_direction.py` is scheduled nowhere,
and called it the most important operational finding of the audit.

The scheduling observation was correct. The conclusion drawn from it was not.

**The evidence was accumulating the whole time.** The probe does not maintain
a counter — it recomputes from `data/processed/information_events.jsonl`,
which the capture chain has been appending `lineup_posted` events to
continuously. The registry's `forward_window: {'n': 0, ...}` is a field
written once at registration and never updated, not a measurement of how much
evidence exists. Nothing was lost. Only the READ had never happened.

The lesson is the same one this audit keeps finding, pointed at myself: a
counter reading zero and evidence not existing are different facts, and I
collapsed them. Twice in one day I treated "not where I looked" as "not
there" — and this time I was the one who did it.

## What the read says

`python scripts/probe_lineup_direction.py --forward`, read-only, no API spend:

```
160 usable postings after the registration instant; floor 150
  n=158   hit 0.481   family of 47   alpha 0.00106   [0.326, 0.592]
VERDICT: UNDETERMINED
```

This is a legitimate registered read. The pre-registration set a forward floor
of 150 and there are 160 usable postings, so the sample was reached honestly
rather than peeked at early.

Set against the discovery:

| read | n | hit rate | interval |
|---|---:|---:|---|
| Discovery, 2026-09-11 | 149 | **0.584** | clears its own alpha, fails the family-wide one |
| Full pooled, today | 323 | 0.526 | [0.483, 0.569] |
| **Forward only** | **158** | **0.481** | [0.326, 0.592] |

The hit rate decayed toward 0.500 as the sample grew, then below it. The
forward interval contains chance comfortably and its point estimate is on the
wrong side of it.

## What this does and does not establish

**Does:** the discovery did not replicate out of sample, at its own
pre-registered floor, under its own pre-registered alpha. That is the test
working exactly as designed, and the answer is no.

**Does not:** kill the underlying idea. The verdict is UNDETERMINED, not
refuted. The forward interval [0.326, 0.592] is wide and does not exclude a
small real effect any more than it supports a large one. What it excludes is
0.584 — the discovery estimate sits outside the forward interval's centre and
near its upper edge.

**Also worth keeping from the full-sample run**, and it cuts against the
hypothesis rather than for it: the probe's own stratification shows the
pooled figure is diluted by a "structurally pinned" stratum (n=209, hit
0.493) where a hit is recorded whatever the market does. The stratum that
could actually falsify the claim reads n=114, hit 0.588. But that split was
chosen AFTER the first run — the probe says so itself, in its own output —
so it is descriptive, not an estimate, and must not be quoted as a rescue.

## What happens now

1. **No verdict is recorded by me.** `record_verdict()` is append-only and
   refuses a second verdict per id, and V6 already carries `result=candidate`.
   Whether this forward read closes the row is a research decision with
   permanence, and it is the owner's to take with the numbers in front of him.
2. **Schedule the probe anyway.** The read should be produced on a cadence and
   recorded, not discovered by someone happening to run it. That was the right
   half of the original finding.
3. **The hypothesis is not the same as the bet.** Even had it replicated, this
   is a PRICE MOVEMENT result. It says nothing about whether acting on it
   obtains better prices, produces positive expected value against the
   obtainable price, or survives vig and execution. Those are three further
   hypotheses and the forward protocol keeps them separate.

## Why this is a good day

The project's only live positive signal was pre-registered before the probe
was written, given a floor, held for out-of-sample replication, and then
failed that replication the first time anyone looked. Nothing was published,
nothing was promoted, and no threshold moved to rescue it.

That is the machinery working. A null arrived on schedule and was legible
when it did.
