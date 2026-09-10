# Pre-registration — replacing Poisson runs with an overdispersed distribution

**Written 2026-09-10, before any correction was implemented and before any
out-of-sample window was scored.** The measurements that motivate it are
descriptive and are named as spent: they can motivate this correction and
they cannot test it.

Unusually for this repo, the thing being tested is **not a claim of edge**.
It is a claim that a component of our own model is the wrong shape, and that
correcting it makes our published probabilities more accurate. Nothing here
asserts that the corrected model beats the market at anything.

---

## What was found, and how

Two independent measurements, neither of which was looking for this.

### 1. The books' own boards say our distribution is too narrow

`scripts/probe_market_consistency.py`. For every instant where one book
quoted a moneyline, a total and the standard run line together, solve the
book's moneyline and total for two Poisson run means, then ask what run line
those means imply. Compare with the run line the book is actually offering.

Measured on 2026-09-09 — 3,575 usable (book, game, instant) triples across
11 books:

| | median disagreement | p25 | p75 |
|---|---|---|---|
| home LAYS the runs (−1.5) | **+3.57 pts** | +2.98 | +4.02 |
| home TAKES the runs (+1.5) | **−8.42 pts** | −8.87 | −7.95 |

Both say the same thing: real margins are more spread out than independent
Poissons allow. The interquartile ranges are about one point wide, which is
far too tight for market disagreement and is the signature of a
deterministic property of the model.

**A control was run first and it killed the original headline.** The raw
pooled distribution looked bimodal and the between-book spread looked large
(p95 13.44 points). Splitting by run-line direction showed the bimodality was
entirely the model's own two branches, and restricting the between-book
comparison to instants where every book agrees on the favourite collapsed the
spread to p95 **3.49**. There is no market-disagreement finding here. There
is a model fault.

### 2. Final scores say the same thing, more strongly

`scripts/probe_run_dispersion.py`, 2,153 finished games of 2026.

| quantity | observed | independent Poissons | ratio |
|---|---|---|---|
| per-team runs variance | 10.422 | 4.481 | **2.33** |
| run-margin variance | 21.093 | 8.961 | **2.35** |
| game-total variance | 20.593 | 8.961 | **2.30** |

And conditional on the model's own per-game means — mean squared Pearson
residual, which is 1.000 under Poisson by construction whatever the means
are, over 3,792 team-games:

| | ratio |
|---|---|
| team runs | **2.313** |
| run margin | **2.349** |

The conditional figure is the one a correction must be sized from. That it
is essentially identical to the pooled figure means the model's per-game
means explain almost none of the excess variance: this is real conditional
overdispersion, not game-to-game variation the model already represents.

What it costs at the run line, the market the card actually publishes:

| | observed | Poisson |
|---|---|---|
| games decided by 2+ runs | **72.7%** | 61.0% |
| one-run games | 27.3% | 39.0% |

**An 11.7-point error on the single quantity the run line pays on.**

The two witnesses are independent — one is the betting market with no game
results in it, the other is game results with no market in them — and they
agree on both the direction and roughly the magnitude.

---

## The hypothesis

> **H1.** Replacing the independent-Poisson run distribution in
> `src.analysis.strength` with an overdispersed one, with the dispersion
> estimated out of sample, materially improves the calibration of published
> run-line probabilities without degrading moneyline calibration.

Stated as a null that can be rejected: *the corrected model's run-line
calibration error is no smaller than the Poisson model's.*

---

## Exactly what changes

One constant and one distribution family. Nothing else in `strength.py`
moves — not the means, not the home-field credit, not the log5
construction. The correction is deliberately confined to the SHAPE of the
distribution around means that are already computed.

Per team, runs become negative binomial with the same mean and

```
variance = DISPERSION * mean          (quasi-Poisson / NB1)
```

`DISPERSION = 1.0` reproduces today's behaviour exactly, and that
equivalence is asserted by a test so the correction can always be switched
off and compared.

**Two families will be fitted, and the choice between them is pre-committed
to the out-of-sample criterion below, not to which looks better:**

- **NB1**: `variance = φ·mean`, φ constant.
- **NB2**: `variance = mean + mean²/k`, k constant.

They agree at the league-average mean by construction and differ in how the
correction scales for a heavy favourite or a Coors-style total, which is
exactly where the card's run-line picks live.

---

## The test

### Split

Fit on **2026-04-15 to 2026-07-15**. Evaluate on **2026-07-16 onward**. The
fit window is chosen by the calendar and is fixed here; it is not moved
afterwards for any reason.

The evaluation window contains data that already exists, so this is an
out-of-sample test and **not** a forward test. It is the weaker of the two
and it is labelled as such. A forward window is defined at the bottom.

### Primary metric

**Run-line calibration error on the evaluation window.** For each game, the
model's probability that the game is decided by two or more runs; binned into
deciles; the error is the sample-size-weighted mean absolute gap between
predicted and observed within bins.

Pre-committed decision rule:

- **The correction is adopted** only if its calibration error is at least
  **50% lower** than Poisson's on the evaluation window, AND
- moneyline log-loss on the same window is **not worse by more than 0.001
  nats** (the correction should barely touch the moneyline; a large change
  there means it is doing something other than what it claims), AND
- the improvement holds for **both halves** of the evaluation window split
  at its midpoint, so a single hot fortnight cannot carry it.

### Secondary metric, no outcomes involved

Re-run `scripts/probe_market_consistency.py` with the corrected
distribution. The median disagreement in both run-line directions should
move toward zero. This is reported whether or not it does, and it does not
gate adoption — it is a check that the correction is explaining the thing it
was derived from.

### What would make this a failure

Any of these, and the correction is not adopted and the negative result is
written up in this file:

- Calibration error does not fall by half.
- Moneyline log-loss degrades by more than 0.001 nats.
- The improvement appears in one half of the evaluation window and not the
  other.
- The fitted dispersion differs by more than 0.3 between the two halves of
  the FIT window, which would mean the parameter is not stable enough to
  carry forward.

---

## What this cannot claim, whatever it shows

- **Not an edge.** A better-calibrated run-line probability is a better
  description of the game. It is not evidence that our number beats the
  market's, and the card's own rule still takes the market's side and uses
  our model only for agreement.
- **Not a reason to start ranking by model disagreement.** The reason that
  is forbidden (`docs/THE_CARD.md`) is that the model gains 0.0012 nats over
  a base rate on the moneyline. This correction is about the run line's
  shape and does not touch that finding.
- **Not transferable to the total.** The same dispersion widens the total's
  distribution too, and the card does not publish totals. If totals are ever
  published, that is a separate pre-registration.

---

## Forward window

Independently of the out-of-sample test above, the corrected model's
run-line probabilities accrue against **the next 200 games settled after
adoption**, scored on the same calibration metric. That window is a genuine
forward test; the one above is not. It reports PENDING until 200 games have
settled and its result is published either way.

---

## Status

**RUN 2026-09-10. VERDICT: DO NOT ADOPT.** `DISPERSION` stays at 1.0.

---

# Result

`scripts/test_run_dispersion.py`. Fit 2026-04-15 to 2026-07-15 (1,186
games); evaluate 2026-07-16 onward (710 games).

Fitted dispersion: **2.3352**.

| arm | run-line calibration error | 1st half | 2nd half | ML log-loss | predicted 2+ | observed 2+ |
|---|---|---|---|---|---|---|
| poisson | 0.08623 | 0.06954 | 0.10293 | 0.68914 | 0.6222 | 0.7085 |
| nb1 | **0.00637** | 0.02278 | 0.01474 | 0.68580 | 0.7148 | 0.7085 |
| nb2 | **0.00560** | 0.02215 | 0.01174 | 0.68556 | 0.7140 | 0.7085 |

| check | nb1 | nb2 |
|---|---|---|
| calibration error down ≥ 50% | PASS (+92.6%) | PASS (+93.5%) |
| moneyline not degraded > 0.001 nats | PASS (−0.00334) | PASS (−0.00358) |
| holds in both halves | PASS | PASS |
| **fitted dispersion stable (drift ≤ 0.30)** | **FAIL (0.3151)** | **FAIL (0.3151)** |

Three substantive checks passed, decisively. The correction removes almost
all of the run-line calibration error and *improves* moneyline log-loss by
0.0034 nats — nearly three times the entire gain the model has over a
home-field base rate.

**The fourth check failed and the verdict is the verdict.** The threshold is
not moving. Rescue by threshold change is the single thing this project's
research discipline exists to prevent, and it does not become acceptable
because the result is flattering. It is *more* dangerous when the result is
flattering.

## Why the check failed, measured rather than argued

Dispersion by month, with standard errors:

| month | n (team-games) | dispersion | se | runs/game |
|---|---|---|---|---|
| 2026-04 | 420 | 2.151 | 0.174 | 4.62 |
| 2026-05 | 838 | 2.244 | 0.135 | 4.30 |
| 2026-06 | 788 | 2.339 | 0.176 | 4.67 |
| 2026-07 | 742 | 2.563 | 0.204 | 4.50 |
| 2026-08 | 834 | 2.231 | 0.155 | 4.35 |
| 2026-09 | 170 | 2.245 | 0.264 | 4.79 |

Overall **2.3129 ± 0.074**. No trend, no relationship with the run
environment, and every month within about one standard error of the whole.

The two fit halves: **2.179 ± 0.103** and **2.497 ± 0.157**. The difference
is 0.318 with a standard error of 0.188 — **1.7 standard errors**, which is
not evidence of instability by any conventional standard.

**The criterion was underpowered, and that is my error, not the data's.** I
set a 0.30 drift limit without first computing the estimator's precision. At
SE(difference) ≈ 0.19, a perfectly constant dispersion would fail this check
roughly one time in nine. A pre-registration is only as good as the power
calculation behind it, and this one had none.

That is a lesson about writing criteria, not a licence to ignore this one.

## What changed in the product anyway, and why it needed no adoption

The card used to choose between the moneyline and the run line by comparing
each market's model probability against that market's own consensus. One
input to that comparison is now measured wrong by about nine points in a
known direction, so the comparison was biased against the run line
throughout and any run line it did select was selected by model error.

**That comparison is deleted** (`RUNLINE_AS_ALTERNATIVE` in
`src/analysis/daily_card.py`). The card publishes the moneyline and shows
the run line beside it as an alternative with the trade stated in words —
"pays more, needs them to win by two or more". Nothing in that sentence
depends on our distribution being right, which is the point.

Removing a known-broken input is not adopting a fitted constant, and does
not require this pre-registration to have passed.

**One consequence is on the public record and stays there.** The frozen card
for 2026-09-10 has `Take Yankees -1.5 at -149` as pick #1, selected by the
comparison described above. It is not being edited. A record you can correct
after the fact is not a record.

---

# Second pre-registration — properly powered, forward data only

**Written 2026-09-10, after the above failed, and deliberately testing on
games this project had not yet played.** Everything above is spent.

> **H2.** Dispersion estimated on all 2026 games completed before the test
> window is stable enough to carry forward, and applying it improves
> run-line calibration on games played after it.

**Window.** The next **300 games** settled after 2026-09-11, whichever dates
those fall on.

**Fit.** `DISPERSION` estimated once, on every 2026 game completed before
2026-09-11, and then frozen for the whole window. `DISPERSION_FAMILY` is
pinned to `nb1` in advance; nb2's marginal advantage above (0.00560 vs
0.00637) is inside the noise and choosing on it would be selection.

**Primary metric.** The same run-line calibration error, on the forward
window only.

**Adoption criterion, powered this time.** Adopt if BOTH:

- calibration error is at least 50% below the Poisson arm's on the same
  window, and
- the fitted dispersion sits within **±2 standard errors** of the estimate
  it was frozen at, computed from the window's own residuals.

The stability check is now expressed in units of the estimator's own
precision rather than in raw dispersion points, which is what the first one
should have been.

**Status: PENDING**, 0 of 300 games. Reported either way.

---

# Third pre-registration — 2025, held out and never looked at

**Written 2026-09-10, after the 2025 season was ingested and BEFORE any
dispersion figure was computed on it.** 2,212 games. This document's first
test used 2026 only, both windows; 2025 did not exist in the store when it
ran and no measurement in this repo has touched it.

It settles today what H2's forward window would settle in a month, on seven
times the sample, and it is a stricter test than either: an entirely
different season, different rosters, a different run environment.

> **H3.** The overdispersion measured on 2026 is a property of baseball, not
> of 2026. Estimated independently on 2025 it lands close to the 2026
> figure, and applying the 2026 estimate to 2025 improves run-line
> calibration there.

**Why the first half matters more than the second.** The reason H1 was not
adopted was parameter stability, and the strongest possible evidence about
stability is a completely separate season estimated from scratch. If 2025
comes back near 2.31, the constant is a fact about the sport. If it comes
back at 1.6 or 3.0, the first test was right to refuse and this correction
should not be carried forward at a single value at all.

**Fit.** Nothing is fitted on 2025. `DISPERSION = 2.3352` — the value
estimated from the 2026 fit window in H1 — is applied unchanged. The 2025
dispersion is computed only to be compared against it.

**Primary criterion, powered this time.** Adopt if BOTH:

- the dispersion estimated independently on 2025 sits within **±3 standard
  errors** of 2.3352, using 2025's own residual standard error, and
- run-line calibration error on 2025 under `nb1` at 2.3352 is at least
  **50% below** the Poisson arm's on the same games.

Three standard errors rather than two: this is a cross-season comparison and
the run environment genuinely differs between years, so a criterion tight
enough to fail on a real league-wide scoring shift would be measuring the
wrong thing. The interval is stated in units of the estimator's own
precision, which is the correction H1's criterion needed.

**Secondary, reported and not gating.** Moneyline log-loss on 2025 must not
degrade by more than 0.001 nats.

**What would make this a failure**, and it is written up either way:

- 2025's dispersion is more than 3 standard errors from 2.3352.
- Run-line calibration does not improve by half on 2025.
- The moneyline degrades by more than 0.001 nats.

**Status: RUN 2026-09-10. VERDICT: ADOPT.** `DISPERSION = 2.3352`.

## H3 result

`scripts/test_run_dispersion_2025.py`. 2,186 usable games, 4,372 team-games,
none of which existed in the store when H1 ran.

| | dispersion | se |
|---|---|---|
| estimated on **2025**, from scratch | **2.3265** | 0.0682 |
| estimated on **2026** (the value applied) | **2.3352** | — |
| **distance** | **0.128 standard errors** | limit 3.0 |

Two independent seasons, different rosters, a different run environment, and
they agree to a tenth of a standard error.

Applying the 2026 value unchanged to 2025:

| | Poisson | nb1 @ 2.3352 |
|---|---|---|
| run-line calibration error | 0.08088 | **0.00950** (−88.2%) |
| moneyline log-loss | 0.690832 | **0.684298** (−0.0065) |

| check | result |
|---|---|
| dispersion within 3 SE of the 2026 estimate | **PASS** (0.128) |
| run-line calibration improved by half | **PASS** (+88.2%) |
| moneyline not degraded (reported, not gating) | **PASS** (improved 0.0065) |

The moneyline improvement is worth stating separately: **0.0065 nats is
about seven times the model's entire gain over a home-field base rate.** A
correction to the *shape* of the run distribution did more for the moneyline
than everything else in the model put together.

### Secondary check, no outcomes involved

`scripts/probe_market_consistency.py` on 2026-09-09, before and after:

| | Poisson | adopted |
|---|---|---|
| disagreement sd | 5.288 | **0.921** |
| home lays the runs, median | +3.57 | −2.16 |
| home takes the runs, median | −8.42 | −2.74 |

The two clusters converge and the spread falls by a factor of five. The
correction explains what it was derived from.

### What H1's refusal cost, and whether it was worth it

H1 refused this correction for six hours on a criterion that was
underpowered — a perfectly stable parameter fails it about one time in nine.
Adopting it there would have reached the same place sooner.

**The refusal was still right.** The criterion was written before the answer
was known, it failed, and the rule is that a failed pre-registered check is a
failed check. What that bought is this document: a correction adopted on a
completely separate season under a criterion fixed in advance, rather than
one adopted because the number looked good. The two paths end at the same
constant and only one of them is evidence.

### What is still true after adopting

- **This is not an edge.** A better-shaped run distribution describes the
  game more accurately. It says nothing about beating the price.
- **The card still does not rank by model disagreement.** That remains
  forbidden for the reason in `THE_CARD.md`.
- **The card still does not select the run line.** `RUNLINE_AS_ALTERNATIVE`
  stands; run lines are offered beside the pick, not chosen by a model.
  Reinstating that comparison is a separate question needing its own
  pre-registration now that one of its inputs is fixed.

### The question this opened

With the shape corrected, the RAW model's log-loss (0.68831) is now **better
than the Platt-calibrated one** (0.69137), and the fitted shrink relaxed from
b = 0.489 to b = 0.708. The calibration layer was built to fix an
overconfidence that no longer exists at the same size, and may now be
over-shrinking.

**Not acted on.** It needs its own pre-registered window, and changing two
things at once is how a result stops being attributable. Recorded here as
the next question.
