# Incident 2026-09-09 — the site published picks for games already over

**Found by:** Jacob, a reader Brey asked to watch the site. Not by us.

**Symptom:** 23 published picks, 21 for games already in progress or final.
One carried a STRONG evidence badge next to a game sitting at 8-0. Jacob read
it as the system having called a great bet, and said he was "shocked that pick
had such good analysis behind it."

**What he actually saw, precisely:** the Mets -2.5 at +286 was never a pick.
It was a price-gap flag (`value_points` 22.45) from `api/opportunities.py` on a
thin book — a spread, which no genome can even express (`genome.MARKETS` is
`h2h` and `h2h_1st_5_innings`). The 8-0 score does not validate it and would
not have validated it even if the system had made the call. Two separate
defects arriving at once: a surface that presents execution quality as value,
and a slip that kept presenting frozen pregame decisions as live calls all
evening.

---

## Why we missed it

The day was not under-verified. It had mutation tests on the tier function,
the join key, the system-class filter, the dedup and the cadence gate, and
four separate reads of the live DOM.

Every one of those checks asked:

> Does this code do what I intended?

A slip full of finished games passes all of them. Nobody asked:

> Is what is on the page true right now?

A pick card was screenshotted and its typography verified while the game it
recommended was over.

Three contributing failures, in descending order of how much each should have
caught it:

1. **An alarm was explained away.** A commit message that same day read
   "GREEN is deliberately rare by construction -- the ledger's ceiling is 3
   families." Then 11 families appeared, and the first instinct was to reason
   about how a grown genome population *might* justify it. It escalated only
   because 11 was too absurd to rationalise. At 5 it would have shipped.
2. **The reader's reaction was itself the bug report.** In a product with zero
   confirmed edges, someone being *impressed* means something is overclaiming.
3. **A warning was answered with more building.** Brey said that morning that
   Jacob would be reviewing the day's picks. The response was to ship more
   features rather than open the page.

## What changed

| Change | What it does |
|---|---|
| `src/engine/slip.py` `MISS_GAME_STARTED` | refuses any candidate whose first pitch has passed; fails open if the schedule fetch fails |
| `scripts/publication_audit.py` | asks whether the published claims are true right now, re-deriving each independently rather than importing the code that produced it |
| `tests/test_publication_audit.py` | replays the real 23-pick slip at the clock time Jacob read it and requires an ESCALATE |
| `scripts/capture_slot.sh` | runs the audit **outside** the lineup-cadence gate — a slip goes false by the clock, which happens between passes |
| `.claude/skills/publication-truth` | fires before claiming anything works, before a reviewer looks, and whenever a result beats expectations |

## What the new method found within minutes of existing

Running the audit against live state rather than against the code surfaced a
second defect nothing upstream forbade: **the two published picks were
opposite sides of CIN@LAD**, LAD at -272 (rank 1) and CIN at +242 (rank 2),
both tagged TOP_3. Each cleared every per-candidate floor honestly. Together
they guarantee the reader loses the hold, and they are evidence the systems
*disagree* — the opposite of what a ranked slip asserts. Every existing filter
judged one selection in isolation; this is a property of the set.

Fixed with `MISS_CONTRADICTS_HIGHER_PICK`, applied after the sort so the
ranking basis decides which side survives, and before ranks are stamped so the
refused side does not consume a rank number. Two different markets on one game
still publish — correlated is not contradictory — and the audit warns about
the correlation instead.

## Open, deliberately left red

- **A published pick claims 6 independent families; the documented ceiling is
  3.** The population has grown from 12 registered genomes to 52 systems in 29
  families, so 6 may be legitimate. "May be" is exactly the reasoning that let
  the first bug ship. The audit stays red until the clustering is verified and
  `DOCUMENTED_FAMILY_CEILING` is raised with the reason written into source.
- **`api/opportunities.py` still presents price standing as value.** This is
  the component that actually produced Jacob's impression. Roadmap Stage 12
  item 4, unfixed.
