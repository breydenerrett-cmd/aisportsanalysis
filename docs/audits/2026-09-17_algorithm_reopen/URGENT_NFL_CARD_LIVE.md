# URGENT: the NFL card is live, publishing -225, with no provenance

Found 2026-09-17 during the algorithm-reopen audit. Operational, not research.

## What happened

The NFL card path was fixed this morning (commit 9a45be1a) after being found
incapable of ever producing a card. It worked. It then published, at
`8120b076` and `b22a9cc1` ("Afternoon slate 2026-09-17", forward-capture-bot):

```
"bet": "Take Buffalo Bills to win at -225", "book": "betmgm",
"confidence": null, "basis": null, "calibrated": null,
"calibration": null, "disclaimer": null, "model_id": null,
"games_on_slate": null, "n_picks": 1
```

## Two separate problems

**1. The price.** -225 is beyond the limit the owner stated on 2026-09-15
("if the price is -200 or higher, it's typically not going to be a good
bet"). V1 has no price test, so this is V1 behaving exactly as designed and
exactly as the owner objects to. `docs/PRICE_BAND_EVIDENCE_2026-09-17.md`
measures what that costs on MLB: at -225 the break-even is about 69%.

**2. The nulls, which may matter more.** The row carries no `basis`, no
`disclaimer`, no `calibrated` flag, no `model_id`, no `confidence`. The MLB
V1 rows carry these. A published pick with a null disclaimer and null basis
is a claim with no provenance attached — the opposite of what this project's
evidence discipline is for. It also means the NFL publish path is not
populating fields the ledger schema expects, which no test caught because
until this morning the path had never run.

## Why it was not caught

The fix was verified by `--dry-run`, which prints the card and writes
nothing. Nobody inspected a WRITTEN row, because until today no written row
had ever existed for this sport. The tests added this morning cover the CLI
path and the empty-reason split; they do not assert that a published NFL row
carries the same provenance fields as an MLB one.

## Recommended, not yet done

1. Add a test asserting a published NFL row carries `basis`, `disclaimer`,
   `calibrated` and `model_id` — the same assertion the MLB path would pass.
   It should fail against today's code.
2. Decide whether NFL should publish at all before V2 registers. The argument
   for pausing: it is internal/coming-soon, nobody is relying on it, and
   every day it runs it writes rows the owner's own rule would refuse. The
   argument against pausing: W-6's whole purpose is forward testing, and a
   paused sport tests nothing.
3. This is the owner's call, not mine, because it trades evidence collection
   against publishing bets he has said are bad.

## What it says about the audit

The audit's central theme is systems that look like they work. This is the
inverse and just as instructive: a system that was correctly diagnosed as
broken, correctly fixed, verified by the method available — and the first
real output still went out wrong, because the verification could not reach
the thing that only exists after the fix works.
