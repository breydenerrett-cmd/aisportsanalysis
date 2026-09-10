# Pre-registration — anchoring the evidence ladder to a null, not to a count

**Written 2026-09-10, before the null was computed and before any threshold
was chosen.** The rule below decides the numbers. I do not.

---

## The problem this replaces

`src/engine/slip.py` grades a pick STRONG when three or more independent
families back it. The 3 was set on 2026-09-08 because three was the largest
agreement the live ledger had ever produced — when essentially nothing
forward-test played.

By 2026-09-10 the engine ran 166 decisions from 29 systems, the verified
ceiling was 16, and **78% of every pick ever published is STRONG**
(`scripts/calibration_drift_audit.py`). The rarest grade in the product
distinguishes nothing and BUILDING, THIN and MINIMAL are unreachable.
Details: `docs/INCIDENT_2026-09-10_STRONG_TIER.md`.

**The obvious fix is forbidden.** Raising the threshold to whatever makes
today's slate look selective is, in this module's own words, "a threshold
picked to produce a target number of picks… the purest form of the thing
this project's whole research discipline exists to resist." Any absolute
count chosen that way goes stale again the next time the population moves.

## The rule

> **An absolute count is the wrong shape of threshold entirely.** What the
> ladder is trying to say is *how much independent support this pick has
> relative to what support means in this population*. That is a question
> about a distribution, and it has a standard answer: compare against a null
> in which agreement is arbitrary.

**H1.** Family agreement on a real wager exceeds what the same systems,
playing the same number of wagers, would produce by chance — and the tier
thresholds are the percentiles of that null.

### The null

For each slate date, holding fixed:

- which systems played at all that date, and **how many wagers each played**
- which wagers were available, and **how many backers each attracted**

…reassign backers to wagers at random, recompute family counts through the
real clustering, and record the distribution. This preserves both marginals,
so the null asks precisely "given this much agreement in aggregate, how
concentrated would it be by chance?"

### The thresholds, fixed here

| tier | rule |
|---|---|
| STRONG | family count ≥ the **95th percentile** of the null |
| BUILDING | ≥ the **75th percentile** |
| THIN | above the null's **median** |
| MINIMAL | anything else that cleared the publication floors |

95 and 75 are conventional and are chosen **now**, before the null is
computed, precisely so they cannot be chosen afterwards. Whatever counts
those percentiles land on become the thresholds, including if they land on
values that make most of today's picks STRONG anyway — that outcome would
mean the agreement is real, and it would be reported as such.

### Sample and stability

- **10,000 permutations**, seeded, over every date with at least 5 played
  wagers and 5 playing systems.
- The thresholds must be **stable across a split of the dates**: computed on
  the first half and the second half separately, no percentile may differ by
  more than 1 family. If it does, the ladder is not yet estimable and the
  current threshold stays with the debt still recorded.

### What would make this fail

Any of these, and no threshold changes:

- The real family counts are **not** above the null — meaning agreement in
  this population is what chance produces and the ladder is measuring
  nothing.
- The split-half check disagrees by more than one family.
- Fewer than 20 usable dates.

## What this cannot claim

A pick clearing a high percentile of the null has **more independent support
than chance would give it**. It is not more likely to win. Nothing in this
document touches whether any system has an edge, and `docs/THE_CARD.md`'s
statement that none does is unaffected.

## Status

**RUN 2026-09-10. REFUSED: not enough data.** `EVIDENCE_STRONG_MIN_FAMILIES`
stays at 3 and the debt stays recorded.

> REFUSED: 5 usable dates, the pre-registration requires 20. The ladder is
> not estimable yet and the current threshold stays.

The engine only began producing forward-test plays at volume on 2026-09-06.
Five dates clear the "at least 5 wagers and 5 systems" bar; the rule needs
twenty.

**This is the pre-registration working, not failing.** The minimum sample
was written down before the null was computed, precisely so that a ladder
could not be estimated off a handful of days and then defended because it
existed. Had the script simply produced numbers from five dates, they would
have looked exactly as authoritative as numbers from fifty.

### What happens next, without anyone remembering to do it

`scripts/test_tier_ladder.py` runs nightly from `scripts/daily_loop.sh` and
reports its distance to the twenty-date bar. It does **not** escalate while
it is short — a pending pre-registration is a normal state, not a fault —
and it flips to escalating the moment it becomes answerable, so the ladder
gets recalibrated because the data arrived rather than because someone
remembered.

Roughly fifteen more slate days at the current rate.

### The one caveat on the eventual answer

The run above reported no family-map warning, which means the clustering map
was not reachable from this script and every count fell back to distinct
systems. That fallback is **exactly the number the family discount exists to
replace**, so when the twenty dates arrive the first thing to check is that
`systems_with_no_known_family` is zero. The script prints it prominently and
calls the ladder provisional if it is not.
