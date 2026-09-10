# The STRONG tier stopped meaning anything the day the engine started working

Found 2026-09-10 by `scripts/publication_audit.py`, which escalated on a
published pick claiming four independent families against a documented
ceiling of three.

**Nothing here is a bug in the clustering.** The clustering is correct. What
broke is a customer-facing label whose threshold was calibrated against a
population that no longer exists.

---

## What the audit said

> ESCALATE: a published pick claims 4 independent families agree; the
> documented ceiling is 3. Either the clustering is collapsing too little
> (near-duplicate genomes counted as independent, which manufactures exactly
> the confidence doctrine amendment 9 forbids), or the ceiling is genuinely
> higher now — verify which, then raise `DOCUMENTED_FAMILY_CEILING` with the
> reason.

Two branches, and the check refused to guess between them. Both were checked.

## Branch 1: is the clustering under-collapsing? No.

A structure-blind clustering — the failure mode where near-duplicate genomes
are counted as independent and agreement is manufactured — has one
unmistakable signature: **every system becomes its own family and nothing
merges.** Measured across today's slips:

| slip | families | backing systems | collapsed |
|---|---|---|---|
| 14:57Z | 15 | 22 | 7 |
| 16:13Z | 16 | 22 | 6 |
| 16:13Z | 14 | 17 | 3 |
| 18:14Z | 4 | 4 | 0 |

Twenty-two systems collapsing into sixteen families is a clustering doing its
job. The 4-of-4 pick collapses nothing because four genuinely distinct
systems agreed — and with **29 distinct forward-test systems playing today**,
four of them landing on one wager needs no special explanation.

Branch 1 is refuted.

## Branch 2: is the ceiling genuinely higher? Yes, and obviously so.

`src/engine/slip.py` justifies `EVIDENCE_STRONG` at 3+ families like this:

> The strongest agreement ever measured on this project's live ledger,
> across its whole history, is 3 families (**2026-09-08 measurement**).

That sentence was true when written. On 2026-09-08 the engine produced
essentially **no forward-test plays at all** — the ledger's ceiling of three
was the ceiling of a population of almost nothing.

By 2026-09-10 the engine ran **166 forward-test decisions from 29 systems**.
More systems playing means more families can agree. The ceiling moved for
the most ordinary reason there is, and `DOCUMENTED_FAMILY_CEILING` has been
raised from 3 to 16 with that verification recorded in source.

---

## The actual problem, which is worse than the alarm

**Every pick the engine published on 2026-09-10 was STRONG. Fourteen of
fourteen**, at family counts of 4, 6, 13, 14, 15 and 16 against a threshold
of 3.

`EVIDENCE_STRONG` is described to the reader as the rarest grade a pick can
carry. It now fires on everything. A label that fires on everything
distinguishes nothing, and the tier ladder beneath it — BUILDING, THIN,
MINIMAL — has become unreachable.

This is precisely what `slip.py`'s own comment warned about:

> A scheme that made most nights green would be recalibrating the label to
> flatter the picks instead of describing them, which is the exact
> manufactured-confidence failure this module exists to refuse.

It did not happen by recalibrating. It happened by **not** recalibrating
while the population underneath changed by two orders of magnitude.

## Why the alarm that exists for this stayed silent

`STRONG_SHARE_ALARM` fires when 40%+ of a slip's picks are STRONG — exactly
this condition — and it never fired, because `STRONG_SHARE_MIN_PICKS` was
**5** and no slip today carried five picks. They carried one, two or three.

A rare-tier alarm that needs five picks cannot see a day of one- and
two-pick slips, which is the shape a selective engine produces by design.
The floor is now 3.

---

## What was NOT done

**No new threshold was chosen.** The obvious move is to raise
`EVIDENCE_STRONG` to somewhere around 12 so today's picks stop all being
green. That is forbidden by the same sentence in `slip.py` that this
document has already quoted twice:

> a threshold picked to produce a target number of picks is the purest form
> of the thing this project's whole research discipline exists to resist

Picking 12 because it makes today look selective is that, exactly. The tier
ladder needs recalibrating against the population it now describes, by a
rule stated before the answer is known — the same discipline as
`docs/PREREG_RUN_DISPERSION.md` — and that is a separate piece of work.

`STRONG_TIER_RECALIBRATION_OWED` in `scripts/publication_audit.py` reports
this on **every run**, unconditionally, not only on nights when a pick
happens to clear the bar. A check that goes quiet on an empty slate is a
check that gets forgotten.

## The ceiling itself was the wrong shape of check

Raising `DOCUMENTED_FAMILY_CEILING` from 3 to 16 is correct by the
constant's own definition — "the largest anyone has verified" — and it makes
the check **unable to fire on the data that raised it**. Every threshold set
to the largest observed value has that property. It is a ratchet, not a
detector.

So a second check was added, and it is the one that does the work:

```
22 systems -> 16 families    collapsing, healthy
 4 systems ->  4 families    collapsed nothing, and legitimate
22 systems -> 22 families    collapsed nothing at 22, which cannot be right
```

A structure-blind clustering has a signature that **does not depend on
population size**: every system becomes its own family and nothing merges.
Zero collapse is unremarkable on four systems and implausible on twenty-two.
`COLLAPSE_CHECK_MIN_SYSTEMS = 8` is about the arithmetic of the clustering,
not about how good tonight's picks look, so it does not go stale as the
population grows — which is exactly what went wrong with the tier threshold.

One consequence recorded honestly: the incident-replay test used to assert
the per-pick ceiling message and can no longer, because the ceiling now sits
above the incident's counts. That test asserts the share alarm instead, and
the collapse check has its own tests on both sides — a 22-of-22 pick
escalates, a 4-of-4 pick does not.

## What this does and does not affect

- **THE CARD is unaffected.** It does not use these tiers. Its own labels
  (STRONG / LEAN / SLIGHT / SPLIT) come from `src/analysis/daily_card.py` and
  are bands on the market's own consensus probability, not on family counts.
- **The engine slip IS affected**, and it renders below the card on
  `#/today`. Until the ladder is recalibrated, a STRONG on a slip pick means
  "at least three families agreed", which today was every pick.

## The thing worth remembering

The engine published its first real forward-test picks today — 0 to 166
decisions in one step. That is the good news, and it arrived carrying a
silent measurement failure, because a constant that described the old
population kept describing it.

**A threshold calibrated against a population is a claim with an expiry
date.** Nothing in this repo currently records which constants have that
property. That is worth fixing before the next one goes stale.
