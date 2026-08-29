# Research Family V2 — market structure

**Status:** pre-registration draft. Nothing evaluated yet.
**Opened:** 2026-08-29, after V1 concluded null (docs/RESULTS_STAGE2.md).

---

## Why V1 failed, and why that was predictable

V1 asked one question eleven different ways: *do we read baseball better than
the market does?* Platoon splits, pitch mix, bullpen workload, travel, matchup
history — all of it is public, all of it is in every model the books buy, and
all of it is priced before we wake up.

The literature said this would happen. Sung & Johnson tested **1,547 simple
wagering strategies** on MLB moneylines, 1999–2016. **38 (2.46%) were profitable
at the 5% level, 7 (0.45%) at the 1% level** — at or below what pure chance
produces. Their conclusion is the MLB moneyline market is extremely efficient.

Our zero-of-eight is not a bug and not bad luck. It is the expected result of
that experiment. Running V2 as *more baseball knowledge* would be running the
same failed experiment with new variable names.

## The reframe

V1: **"Do we know baseball better than the market?"** — answered, no.

V2: **"Does the market misprice itself?"**

That is a different question with a different literature behind it, and the
findings there are *replicated and published*, not folk wisdom. Every V2
hypothesis below is about price behaviour, not player performance. Every one is
testable on data already on disk.

---

## Data available (no new credits)

| | |
|---|---|
| Historical odds | 2023/2024/2025, 2,491 events in 2023 alone, median 5 snapshots per event (max 23) |
| Books | 10+ per snapshot — draftkings, fanduel, betmgm, bovada, betus, lowvig, betonlineag, williamhill_us, barstool, wynnbet |
| Markets | h2h and totals, both fully populated |
| First five | 661 games, 2023–2025 |
| Results | full settlement for all of it |

Multi-book × multi-snapshot × multi-market is exactly the shape these hypotheses
need. **Estimated credit cost of the whole V2 discovery pass: 0.**

---

## Pre-registered hypotheses

Counted as a family before any evaluation, same as V1. FDR at q=0.10, plus the
1-percentage-point effect floor, plus date-clustered bootstrap CIs. Losers get
published.

### M1 — Line overreaction (negative autocorrelation)

**Claim.** Consecutive price changes on the same event are negatively
correlated: the market moves too far on new information and gives some back.
Fading the most recent move beats holding it.

**Evidence base.** Management Science (2024), 3,681 MLB games across four
books, opening to close: price changes are significantly negatively
autocorrelated, sufficient to reject weak-form efficiency. Replicated across
NFL, NBA and NHL — this is a general property of sportsbook pricing, not an
MLB quirk.

**Test.** For each event, build the per-book price path. Regress change *t* on
change *t−1*. Then trade it: when the last observed move exceeds a threshold,
take the other side at the current price and settle against the outcome.

**Why it might survive where V1 didn't.** It requires no opinion about
baseball. It exploits the book's own reaction function.

**Honest caveat, recorded before testing.** Published significance is not
published profitability after vig. Our snapshots are ~5 per event, far coarser
than their tick data — coarse sampling may wash the effect out entirely. This
is the most likely hypothesis to die on granularity rather than on truth.

### M2 — Weekend day-game staleness

**Claim.** For weekend day games, the price 90 minutes before first pitch
forecasts the result *better* than the price at first pitch. Late movement on
those slates is noise, so the earlier price is the sharper one.

**Evidence base.** Same Management Science paper: forecasts do not improve
monotonically toward game time, and weekend day-game start-time forecasts are
significantly worse than forecasts 90 minutes earlier.

**Test.** Split our snapshot grid by day-of-week × start-hour. Compare
calibration and log-loss of the T−90 price against the latest pre-pitch price,
within each cell. If the effect is real, the T−90 price wins on weekend
daytime cells and loses everywhere else.

**Why this one matters even if unprofitable.** It tells us *which snapshot is
our benchmark*. Right now we assume later is sharper. If that's wrong on some
slates, every CLV number we compute on those slates is measured against the
wrong yardstick.

### M3 — Cross-book dispersion

**Claim.** When books disagree unusually widely, the outlier is wrong and the
consensus is right — and the outlier's price is the one you can bet.

**Test.** Per event-snapshot, compute de-vigged consensus and each book's
deviation. Select where |deviation| exceeds a threshold, take the outlier's
price, settle against consensus-implied and against outcome.

**Note.** V1's `stale_book` detector tested a version of this and came back
+0.03pp, p=0.97 — flat dead. V2's version differs in that it conditions on
dispersion across the *whole book set* rather than one book against consensus,
and evaluates on totals as well as moneyline. **Given the V1 result, prior
probability here is low and I am recording that now** so a positive finding
gets extra scrutiny rather than a victory lap.

### M4 — Bullpen gap mispricing (F5 vs full game)

**Claim.** The full-game price minus the F5 price *is* the market's stated
opinion on the bullpens. Where that implied bullpen edge diverges from realised
bullpen performance, the market is wrong about relief pitching specifically.

**Why it's structural, not knowledge-based.** We are not claiming to evaluate
bullpens better than the market. We are checking whether two prices the *same
book* publishes are mutually consistent. Internal inconsistency is a pricing
error regardless of who understands baseball better.

**Test.** On the 661 F5 games: derive implied innings-6-9 win probability,
compare against realised innings-6-9 outcomes, look for systematic bias
(e.g. the market consistently over- or under-weights bullpen swing).

**Constraint.** 661 games is a small sample and it is the binding limit on this
hypothesis. It may simply be underpowered — that is a legitimate outcome and
gets reported as "underpowered", not as "no effect".

### M5 — De-vig methodology divergence

**Claim.** Proportional de-vig, Shin de-vig and power de-vig disagree most on
lopsided prices. That disagreement is a direct measurement of favourite-longshot
bias, and where the methods diverge most is where the true probability is
furthest from the naive one.

**Test.** Compute all three on every historical price. Where they diverge past a
threshold, check which is best calibrated against outcomes. Then test whether
betting the side the better-calibrated method favours is profitable.

**Payoff even if unprofitable.** We currently de-vig proportionally everywhere.
If Shin is better calibrated on lopsided prices, every edge number the system
produces on favourites and longshots is biased, and fixing that improves the
whole product regardless of whether M5 itself is tradeable.

---

## What is NOT in V2, and why

**Jacob's unit-vs-weakness decomposition.** Not abandoned — deferred to V3, and
reframed. As a standalone signal it is a knowledge edge and the literature says
knowledge edges are gone. It has a real future as a *conditional* filter: not
"this matchup is good" but "this matchup is good **and** the market had no way
to price it yet" — for example inside the lineup-release window, before books
have adjusted. That is a market-timing hypothesis wearing a baseball costume,
which is the right shape. It needs dense timestamps around lineup posting that
we can only collect forward.

**Reverse line movement.** Still blocked. Needs public bet percentages. No
source we have provides them, and inferring public sentiment from price alone
invents the data.

**Anything requiring new credit spend.** V2 discovery is free. If something
survives, *then* we spend credits on true closing lines to confirm it — same
discipline as V1.

---

## Execution order

1. **M5** first — cheapest, and it improves the system's pricing whether or not
   it's tradeable.
2. **M2** second — it defines the benchmark everything else is measured against.
   Getting this wrong contaminates M1 and M3.
3. **M1** — the headline hypothesis, and the one with the strongest external
   evidence.
4. **M3** — low prior, tested anyway because it's pre-registered.
5. **M4** — last, because it's sample-limited and may not resolve.

Same rules as V1 throughout: 2023–24 discovery only, 2025 untouched, sealed
2026 untouched, family registered before evaluation, losers published, no
promotion on subgroups.

## Expected outcome, stated in advance

Most of these will fail. M5 and M2 are likely to produce *methodological*
improvements rather than edges. M1 is the real shot and it may well die on
snapshot granularity.

If all five fail, the honest conclusion is that this market is efficient at the
resolution we can observe it, and the product's value is decision support and
discipline — telling Jacob which of his reasons are noise and when not to bet —
rather than a beat-the-market engine. That is a real product. It is not the one
we set out to build, and it will be reported plainly if that is where the
evidence lands.

## Sources

- Sung & Johnson, *Do profitable wagering strategies indicate an inefficient market? … MLB moneyline markets*, Applied Economics 57(34) — 1,547 strategies, 2.46% profitable at 5%, 0.45% at 1%
- *Inefficient Forecasts at the Sportsbook: An Analysis of Real-Time Betting Line Movement*, Management Science 70(12), 2024 — 3,681 MLB games, negative autocorrelation, weekend day-game anomaly
- *Autocorrelation and Weekend Effects: Inefficiencies in Moneyline Movement for Three Major Sports* — NFL/NBA/NHL replication
