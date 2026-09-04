# Resource policy — credits and storage

**Owner directive, 2026-09-04.** This supersedes the austerity posture that
governed `docs/COLLECTION_POLICY.md` and every "save credits" instinct in the
codebase. It is the canonical statement; where another doc conflicts, this
one wins.

---

## The rule

Optimize for **how quickly we can create trustworthy evidence.** Not for how
few credits and gigabytes we use.

Credits reset monthly. Storage can be purchased. The scarce resources are:

- clean methodology
- point-in-time correctness
- statistical power
- useful market coverage
- engineering time
- trustworthy validation

Spend credits and storage intelligently to improve those. Be **disciplined,
not cheap.**

---

## 1. Credits are renewable

~100,000 credits per month, reset on the cycle. **Unused credits at reset
have zero value.** Hoarding them is a loss, not a saving.

### The measured starting position (2026-09-04)

| quantity | value |
|---|---|
| monthly allotment | 100,000 |
| live-capture daily envelope | 900/day = 27,000/month |
| capture share of allotment | 27% |
| **expiring unused each month** | **73,000** |
| actual spend, cycle to date | ~660 |

The 900/day envelope (`src/capture/budget.py: DAILY_ENVELOPE`) already sits
inside the prescribed 25-35% live-capture reserve and needs no change. What
did not exist before this policy is any mechanism to deploy the other ~73%.
That is the gap this document opens.

### Allocation (flexible, reallocate on information value)

| band | share | purpose |
|---|---|---|
| live/forward capture reserve | 25-35% | continuous capture, never starved |
| historical backfill + new-market research | 40-50% | the growth budget |
| targeted probes / experiments | 10-20% | coverage and schema discovery |
| contingency | ~10% | |

### Priorities

1. Preserve enough for continuous live/forward capture. Forward data is
   irreplaceable; a missed window cannot be bought back at any price.
2. Aggressively backfill useful historical data.
3. Prioritize the unexplored markets: **F5, game totals, alternate
   spreads/totals, pitcher props, batter props, timing/line-movement/
   microstructure.**
4. Probe first where provider coverage or schema is uncertain; once a probe
   proves useful, **scale the pull instead of re-probing.**
5. Never spend thousands duplicating data we already hold densely.

### Accounting required for every meaningful pull

Track the full chain, not just the cost:

```
credits spent -> games/markets/rows unlocked
              -> new hypotheses/strategy families made testable
              -> backtests/forward tests enabled
```

Good: `12,000 credits -> several seasons of F5/prop pricing -> tens of
thousands of gradeable decisions -> multiple new strategy families.`

Bad: `12,000 credits -> redundant snapshots of markets we already cover
densely.`

### Before any large historical purchase, spec it

Years covered; books covered; F5 markets available; pitcher prop types;
batter prop types; line/price timestamps; opening/closing availability;
player/game identifiers; settlement compatibility; expected number of
historical decisions unlocked; expected research value per credit.

If it checks out, buy it. The ~12,000-credit historical F5/props purchase is
**within budget** subject to this spec.

### End of cycle

Near the end of each monthly cycle, if a meaningful balance remains,
deliberately identify the highest-value backfills rather than letting credits
expire. Underspending is a reportable failure, not a virtue.

---

## 2. Storage is not a hard constraint

More storage can be bought (SSDs, hard drives, flash drives); a flash drive
is available now; spare iCloud capacity exists.

**Do not reject a useful architecture or research plan merely because it
needs tens or hundreds of GB.** Estimate honestly and proceed when the
research value justifies it. If a requirement turns out materially larger
than expected, report exact credits, exact storage, what it unlocks, what
bottleneck it removes, and the expected payoff -- then make a
recommendation, rather than defaulting to austerity.

### Tiers

**Active working data -> local SSD.** Active git repos, databases,
append-only ledgers, live capture, frequently mutated research datasets.

**External storage -> backups and cold archives.** Immutable historical
datasets, git bundles, large raw-data snapshots, FiveM backup material.

**iCloud -> secondary/archive copies ONLY.** Never active git repos, never
live databases, never frequently-mutating ledgers or datasets. Evidence
exists that iCloud dehydration damaged an old git working copy. If iCloud is
used, verify files are fully downloaded and intact before treating the copy
as a backup.

**The flash drive currently available** is for Claude transcript/recovery
backups, workspace audit/manifest backups, git bundles, irreplaceable FiveM
backup material, and immutable historical research snapshots. A cheap USB
flash drive is never the primary live write-heavy database when an SSD is
appropriate.

### Scaling implication

A storage estimate such as ~36 GB/season must **never** be a reason to
artificially limit the strategy population. Fix the storage architecture
instead:

- normalize repeated wager data;
- store canonical wager/decision records once;
- attach strategies through lightweight references;
- compress/archive immutable historical data;
- separate hot from cold storage.

If useful historical F5/prop data eventually consumes 50-200+ GB, that is
acceptable when it materially accelerates validation.

---

## What this does NOT relax

Spending more does not lower any evidence standard. Pre-registration before
evaluation, published losers, 2025 tuning-only, the sealed 2026 set, no
promotion without the full gate, no rescue by threshold change
(`docs/RESEARCH_CATALOGUE.md` T8), and point-in-time correctness are all
unchanged. Credits buy **more data**, never a weaker gate. A bigger budget
spent on a contaminated dataset produces expensive nonsense.
