# Pre-registration: the value scan reads one side of the market

**Written 2026-09-10, before the measurement was run.** Criterion fixed above
the result.

---

## This is a bug report first and a hypothesis second

`scripts/probe_prop_value.py` scans the **over** side of every player-prop
contract and nothing else. There is no design decision behind that. It came
from the shape of the capture — `Over` was the row that got read — and it has
been true since the probe was written.

A value scan that can structurally only ever recommend one direction is
broken, and it is broken whether or not fixing it makes money. That is the
reason to fix it. What follows is the measurement, but the fix stands on its
own.

**Why it matters more than it looks.** `docs/PREREG_MARKET_VS_MODEL.md`
measured, on the 355 contracts where our number sits more than five points
from the market's, that our model is the **higher** number only **39.7%** of
the time. We are *below* the price more often than above it. Yet only the
over side is ever scanned for value. So every pick the probe can emit is
drawn from the 39.7% minority tail — the contracts where our model happens to
run hottest relative to the market.

That is textbook adverse selection, and it was not chosen by anyone. It is
what the scan's shape does. The flagged arm's −13.4% return against a −9.1%
control is exactly the signature you would predict from it.

## The honest accounting: this is the second look

The over side was measured and lost. Looking at the under side now is the
second slice of the same data, and pretending otherwise would be dishonest.
A second look at a fresh slice is how a null result gets converted into a
false positive.

**So the bar is corrected here, in advance.** With two sides examined, a
nominal 95% interval is not a 95% statement about the family. The requirement
fixed now:

> An arm counts as a finding only if its **97.5% interval** excludes zero
> (Bonferroni across the two sides), **and** it beats its own same-side
> control.

A third slice would require a further correction, and that correction would
be registered before it was looked at, not after.

**This measurement also cannot settle profitability.** The price store covers
about a week. The intervals will be wide. The same caveat that governs the
over arm governs this one.

## What is measured

**Population.** Identical to the over scan's — the board built by
`scripts/_propboard.py`: publishable market, de-viggable market, at least
`MIN_BOOKS` books quoting both sides, batter above the plate-appearance
floor, settled box score. Every contract in it already carries an **under**
price, because `deviggable` requires both sides to exist. No new data is
needed; the under price was always there and never read.

**Four arms**, flat one-unit stakes at the best available price on that side:

| arm | selection |
|---|---|
| `flagged_over` | our P(over) exceeds the best over price's break-even by ≥ the threshold |
| `flagged_under` | our P(under) exceeds the best under price's break-even by ≥ the threshold |
| `control_over` | every assessable contract, backed on the over |
| `control_under` | every assessable contract, backed on the under |

The threshold is the probe's existing `--min-edge`, default 3 points. It is
**not** re-tuned for the under side; a threshold chosen per side would be a
threshold chosen to produce a result.

**Each flagged arm is judged against its own side's control.** Comparing the
under arm to the over control would confound the selection with the base rate
— overs hit 48.9% of these contracts and unders therefore 51.1%, and a naive
cross-side comparison would credit that gap to our model.

## The decision rule, fixed before running

For each side, let `r` be the flagged arm's ROI and `c` its same-side
control's, with the flagged arm's 97.5% interval.

- **Finding:** the interval excludes zero *and* `r > c`. Only then does the
  side become a candidate — and a candidate still requires a forward test,
  because a week of prices cannot settle profitability no matter how the
  interval falls.
- **No finding:** anything else. Reported as no finding. The point estimate is
  not read, the threshold is not moved, and the population is not narrowed to
  look for a subset that works.

**Pre-declared and binding:** if the under arm also fails, the conclusion is
that model-versus-price disagreement does not select profitable player props
on this data *in either direction*, and the prop card does not ship as a
disagreement scanner. That is the outcome this registration is most
expecting, and writing it down now is what stops it being re-litigated later.

## Where it runs

`scripts/probe_prop_value.py`, extended to run both sides. Read-only.
