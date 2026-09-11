# Pre-registration: is the book's own number a better predictor than ours?

**Written 2026-09-10, before the measurement was run.** The criterion below is
fixed. It is not moved afterwards to rescue a result.

---

## Why this measurement decides the direction of the whole prop effort

Two things are already established and they sit uncomfortably together.

1. **The prop model has real signal.** `scripts/backtest_player_props.py`, on
   16,741 batter games with no price in sight, measured `batter_hits` at
   **+0.0133 nats** over the base rate — 3.3x what the team model manages.
   It is calibrated.
2. **Its disagreements with the price lose money.** `scripts/probe_prop_value.py`
   flags contracts where our probability clears the best available price's
   break-even. Those flagged bets returned **-13.4%** against a control of
   every assessable over at **-9.1%**. Selecting on our own edge did *worse*
   than not selecting at all.

Both cannot be waved away. The reconciliation is the sentence this repo has
now written twice in two days:

> **Calibrated overall is not the same as calibrated conditional on
> disagreeing with the market.**

A model can be right on average across every contract and still be wrong
exactly on the contracts where it departs from the price — because departure
is *selected on the model's own error*. That is the same defect the team
model was measured committing, and adding better inputs does not obviously
cure it.

There are two live hypotheses and the current work is only worth continuing
under one of them.

- **H1 — the gap is missing inputs.** We disagree with the price because the
  price knows tonight's lineup, the platoon matchup, the park and the weather
  and we do not. Feed those in and the spurious disagreement shrinks; what
  remains is edge. Weak support exists: wiring tonight's batting slot moved
  flagged ROI from -16.6% to -13.4%, and the with-slot subset reached -9.4%,
  level with the control.
- **H2 — the gap is noise.** The de-vigged consensus is simply a better
  estimate of the outcome than anything we can build from box scores, and
  every disagreement is our variance, not their blind spot. Under H2 no input
  fixes anything, because each new input makes us better *overall* while the
  disagreements stay adversely selected.

**The two hypotheses make opposite predictions about one quantity that has
not yet been measured: which probability predicts the outcome better,
head to head, on the same contracts.**

If the market's number is the better predictor, then betting our
disagreements cannot be profitable other than by luck, and the honest product
is not "our number beats their number." If ours is better, or if they are
indistinguishable, H1 survives and adding inputs is the right work.

---

## What is measured

**Population.** Every assessable prop contract with a resolved outcome — the
same population `probe_prop_value.py` calls the *control*: publishable market,
de-viggable market, at least `MIN_BOOKS` books quoting both sides, a batter
over the plate-appearance floor, and a box score that settles it.

**The flagged subset is deliberately NOT the population.** Scoring only the
contracts where our model disagrees would condition on the model's own error
and is exactly the trap being tested for.

**Arms.** Four probabilities for the same binary event (the over hits):

| arm | probability |
|---|---|
| `base_rate` | the pooled over-rate of the whole population — the do-nothing floor |
| `market` | the mean of each book's two-way de-vigged over probability |
| `model` | `playerprops.price_prop(...)`, point-in-time, no price read |
| `blend_w` | `w * model + (1 - w) * market` over a fixed grid |

The weight grid is fixed here, before running:
`w in {0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0}`.

**Metric.** Mean log loss in nats, lower better. Brier score reported
alongside as a secondary that is less punishing of confident misses. Both are
proper scoring rules: neither can be gamed by shading probabilities toward
the middle.

**Uncertainty.** The comparison is *paired* — the same contract scored by both
arms — so the statistic is the mean per-contract difference
`loss(model) - loss(market)`, not the difference of two means.

Contracts are **clustered by (date, player)**: one batter's hits line and his
total-bases line on the same night settle on the same at-bats and are not
independent draws. The standard error is a clustered bootstrap over those
clusters, 2,000 resamples, resampling whole player-nights.

**Numerical details, fixed here before the run.** Probabilities are clipped to
`[1e-6, 1 - 1e-6]` before taking a logarithm, because a confident arm that
happened to say 0.0 on an event that occurred would otherwise return infinity
and destroy the mean. The bootstrap RNG is seeded at `20260910` so the
interval reproduces exactly.

## Secondary, descriptive analyses — also fixed before the run

These do not carry the decision. They are declared here so that they cannot be
introduced afterwards as a way of finding a slice where the answer changes.

1. **Per-market breakdown** of the same paired difference. Reported for all
   markets in the population; no market is promoted or dropped on the strength
   of it.
2. **Conditional on disagreement.** Restricted to contracts where
   `|model - market| > 0.05`, which number lands closer to the outcome. This
   is the H1/H2 question stated in its most direct form, and it is *secondary
   precisely because* the restriction conditions on the model's own departure
   — the same selection the primary analysis exists to avoid.
3. **Concentration.** How much of the flagged board comes from a handful of
   batters with thin prior samples. The current top five findings contain the
   same player three times, which is a reason to look.

---

## The decision rule, fixed before running

Let `d = mean[ loss(model) - loss(market) ]` over the population, with a 95%
clustered bootstrap interval.

- **If the interval lies entirely above zero** (model loses):
  **H2 is supported.** The market's number is the better predictor. Stop
  building a card out of model-versus-price disagreement on these markets.
  The prop model's role becomes an *input to* a market-anchored estimate, not
  a rival to it, and the product's edge must be sought somewhere the market
  is not already right — execution, stale outliers, or markets the books
  price lazily.
- **If the interval lies entirely below zero** (model wins): our number
  carries information the price lacks. H1 survives. Continue adding inputs
  and re-run this at each addition.
- **If the interval spans zero:** undetermined. Report it as undetermined.
  **Do not pick the arm with the better point estimate** and do not narrow
  the population to find a subset where one wins.

**The blend curve is descriptive only.** Its minimum is chosen on the same
data that produced it and is therefore in-sample. If the curve's minimum sits
at an interior `w`, that value may NOT be adopted from this measurement — it
becomes a candidate requiring confirmation on a held-out period, registered
separately. If the minimum sits at `w = 0`, that is not a fitted parameter and
is reported as the corner it is.

## What this measurement cannot say

- **It does not measure profit.** It measures accuracy. The link is one-way
  and worth stating precisely: if the market probability strictly dominates
  ours as a predictor, betting our disagreements cannot be profitable except
  by luck. The converse does not hold — being the better predictor does not
  by itself clear the vig.
- **The price store covers about a week.** The clustered interval will be
  wide. A wide interval that spans zero is the honest answer, not a licence to
  read the point estimate.
- **`batter_home_runs` is out of the population** by the existing `deviggable`
  gate: no book quotes the under, so no fair price exists to compare against.
  `batter_rbis` and `batter_hits_runs_rbis` are out by the `publishable`
  gate — the model measured worse than a base rate on both.

## Where it runs

`scripts/prereg_market_vs_model.py` — read-only, reads no result before the
criterion above was committed.

---

# RESULT — run 2026-09-10, 1,107 contracts across 689 player-nights

## Primary: UNDETERMINED

```
paired difference  loss(model) - loss(market)
  +0.00655 nats    95% clustered CI [-0.00137, +0.01455]
```

The interval spans zero. By the rule fixed above, **the answer is
undetermined and the point estimate is not read.** Neither H1 nor H2 is
supported. A week of prices was never going to settle this and it did not.

What can be said without violating the rule:

```
                log loss (nats)     brier
  base_rate        0.69289         0.24987
  market           0.66784         0.23760
  model            0.67439         0.24072
```

**Both arms beat the do-nothing floor.** The prop model carries real
information — about +0.019 nats over the base rate on this population, which
is consistent with the +0.0133 measured independently on 16,741 batter games.
The market carries about +0.025. That the model is genuinely informative is
established; whether it is informative *about anything the price has missed*
is what stayed undetermined.

## The blend curve is monotone, with its minimum at the corner

```
  w=0.0   0.66784   <-- lowest
  w=0.1   0.66797
  w=0.2   0.66821
  ...
  w=1.0   0.67439
```

Every unit of weight moved from the price onto our model makes the estimate
worse, with no interior minimum anywhere. This is the shape the
pre-registration named in advance as the corner case: it is not a fitted
parameter and it is reported as the corner it is.

**It is also the more interesting half of the result.** Two predictors that
carry *independent* information almost always blend better than either alone —
that is ordinary shrinkage, and a small `w` should have helped even if our
model were much the weaker of the two. It did not help at `w = 0.1`. The
natural reading is that the market's information already contains ours.

**That reading is suggestive, not established.** The whole curve spans
0.0066 nats, which is the same size as the primary point estimate whose
interval spans zero. Do not promote it.

## Secondary findings

**Conditional on disagreement** (355 contracts more than 5 points apart):
our number landed closer to the outcome **49.6%** of the time. A coin flip.
When we depart from the price, we are right exactly as often as chance — and
departure is precisely what a value card selects on.

**The card can only ever recommend overs, and that is a structural bias
nobody chose.** On those same 355 disagreements we were the *higher* number
only **39.7%** of the time — our model sits *below* the market's more often
than above it. But `probe_prop_value.py` scans the over side only. So every
pick it can ever produce is drawn from the minority tail where our model runs
hottest relative to the price. That is selection on our own upward error,
built into the shape of the scan rather than chosen. Registered separately in
`docs/PREREG_UNDER_SIDE.md`.

**Concentration:** 256 distinct batters; 8.1% of contracts are batters with
fewer than 100 prior plate appearances. The paired difference is worse on
those (+0.019 vs +0.005), consistent with thin histories producing wilder
model numbers — and the top of the flagged board is where they surface (the
same player held three of the top five findings).

**Per market:** `batter_runs_scored` is the worst arm by a factor of six
(+0.030 nats against +0.005 for hits and +0.003 for total bases) on n=99.
Descriptive. Nothing is dropped on the strength of it; if it survives to a
larger sample it becomes a candidate for the `publishable` gate.

## What this changes

Nothing is adopted. The direction of the prop work is unchanged but the bar
is now explicit: **adding an input is only progress if it moves this paired
difference**, and that measurement now exists and is re-runnable. Platoon
splits, park, weather and recent form each get re-measured here, not merely
added.
