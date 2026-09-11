# A depleted lineup moves its own price — and it is still not promoted

**2026-09-11.** `scripts/probe_lineup_direction.py`, against
`docs/PREREG_LINEUP_DIRECTION.md`, committed before the probe was written.

**Headline: n=149, hit rate 0.584. It clears the alpha its own
pre-registration declared and it does NOT clear the one this programme's own
ledger implies. NOT PROMOTED.** Registered as
`V6:lineup_surprise_direction:h2h`, held for forward replication.

---

## What was measured

When a club posts a lineup missing players who normally start, does the
market move against that club over the next two hours?

The signer needs no batter-quality model. For each club, from its own prior
postings only, every player gets an **appearance rate**; the nine highest are
the **expected lineup**; **surprise** is the summed rate of expected regulars
who are absent tonight. A man who starts nine nights in ten and is out is
news. A man who starts five in ten is Tuesday. That distinction is the whole
test — 2.22 of 9 batters turn over on an average night and almost all of it
is routine rest.

| | n | hit rate | interval | verdict |
|---|---|---|---|---|
| as pre-registered, α = 0.05 | 149 | 0.584 | [0.535, 0.636] | CONFIRMED |
| **at the registry's family size (41), α = 0.0012** | 149 | 0.584 | **[0.500, 0.664]** | **UNDETERMINED** |

**The stricter reading decides.** The pre-registration declared α = 0.05 on
the grounds that this is one primary hypothesis. Those grounds were wrong,
and adversarial review caught it: this repository keeps
`data/research/alpha_registry.jsonl` precisely to count what it has already
tested against this market, and the answer was **40 hypotheses, all null**,
before this one. The parent probe already divides by its own sibling count.

**A result that clears 0.05 as though it were the first thing ever tried is
not clearing the bar this programme set for itself.** The first "yes" after
forty "no"s is exactly the result that needs the harsher bar, not the kinder
one. The interval crosses 0.500 outright at a family of 60.

The probe prints both figures and overrules itself in its own output, so this
cannot be quietly re-read as a win later.

## Why it is being kept alive rather than binned

Five independent reviewers attacked the mechanism, each on a different
failure lens, each running code against real data. **None of them broke it**,
and several checks are strong:

- **`observed_utc` is a real observation time.** Across 132 incremental
  commits, no commit of the events ledger ever contained an event stamped
  after itself — a retrospective rebuild cannot produce that. All 287 lineup
  postings were observed *before* their own first pitch; none after.
- **No look-ahead in the price series.** An instrumented re-run confirmed
  0 of 149 "final" quotes came from at or after true first pitch.
- **No home/away inversion, no baseline drift** (P(home number rose) =
  0.510), and it holds in both arms separately — home postings 0.573, away
  postings 0.595.
- **The move follows us.** The same statistic over the 120 minutes *before*
  the posting is 0.483, i.e. chance.
- **Dose-response.** Bigger surprises move the price 1.31× further, and the
  hit rate rises monotonically with surprise: 0.490 / 0.612 / 0.647 by
  tercile.
- **A structure-preserving permutation** (flipping both signs of a game
  together) reached 0.584 in 0.04% of 5,000 shuffles.
- **Stability.** Every one of the 8 days is at or above 0.500;
  leave-one-day-out worst case is 0.574; clustering by *day* instead of game
  gives a **tighter** interval, [0.552, 0.621] — which refutes the reviewers'
  one remaining speculation, that same-day correlation was inflating it.

The mechanism is clean. It is the **confidence** that is not earned yet.

## Two caveats that belong on the record

**Half the sample could never have falsified anything.** Both clubs post for
the same game and carry opposite predicted signs, so a pair whose postings
share a window is pinned near 0.500 by arithmetic whatever the market does.
Split by posting gap: could-falsify n=81 at 0.630, structurally-pinned n=68
at 0.529 — the pinned stratum behaving exactly as the mechanism predicts.
The 45-minute threshold was chosen after the run, so those are descriptive,
not estimates. What they establish is that **the pooled figure is diluted,
not inflated**, and that 149 is not the effective sample size.

An earlier cut split those pairs by *whether they scored 1 of 2*, which is
selecting on the outcome; it inflated the survivors to 0.821. **That number
was wrong** and appears nowhere else.

**Scope is narrower than the claim sounds.** Every scored observation falls
in 2026-09-03..09-10 — entirely inside MLB's post-September-1 roster
expansion, when clubs carry extra players and rest regulars more freely.
There is no pre-expansion sample to contrast against, and none can be
obtained this season. Whatever this is, it is currently a claim about
late-season expanded-roster baseball.

## What would settle it

**Forward replication, floor 150 out-of-sample postings**, on data collected
after 2026-09-11 — accruing at roughly 16 signable per day, so about ten
days. That is the same discipline already applied to
`V3:transaction_first_seen`, which sits at 19 of its required 30 events with
no result read.

No promotion before that floor. No re-reading of the discovery sample.

## The finding that came out of this and matters more for player totals

The owner asked what the next step is for player props and totals. This work
answered it by accident, and the answer is an operational defect.

A lineup posting is a **bigger** event for a player total than for a
moneyline: it tells you each batter's slot, and slot sets plate appearances
(`playerprops.SLOT_PLATE_APPEARANCES` — leadoff 4.467, nine-hole 3.461). A
batter moving from ninth to leadoff gains about **29% more chances**, which
is enormous relative to a hits or total-bases line.

We have **never once observed a prop price at that moment**:

```
                              hours before first pitch
  batter prop captures        median 17.32h    (9,672 quotes)
  lineup postings             median  2.92h    (287 events)

  prop captures landing after the median lineup post:  0 / 9,672
  games with a prop quote both before and after a posting:  0 / 77
```

Every prop capture in the store landed between **04:00 and 09:10 UTC** —
midnight to 5am Eastern — roughly fourteen hours before the lineup that
determines those players' plate appearances is published.

**This is a clock problem, not a budget problem.** The captures already
happen; they are simply at the wrong hour. Moving a slot costs no additional
credits, and until one runs after lineups post, the single most informative
moment for a player total is one we have no price for.
