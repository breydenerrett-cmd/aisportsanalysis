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

---

# RESULT — run 2026-09-10

```
  --- OVER ---
    flagged (edge >= 3 pts)  n=113   won 45.1%   ROI -13.4%
      95%  [-31.5, +4.8]     97.5% [-34.1, +7.4]  <-- decides
    control (every over)     n=1107  won 48.9%   ROI  -9.1%  [-14.8, -3.3]
    -> NO FINDING (excludes zero: no; beats own control: no)

  --- UNDER ---
    flagged (edge >= 3 pts)  n=163   won 50.9%   ROI  -0.2%
      95%  [-16.0, +15.6]    97.5% [-18.3, +17.8]  <-- decides
    control (every under)    n=1107  won 51.1%   ROI  -2.2%  [-8.1, +3.7]
    -> NO FINDING (excludes zero: no; beats own control: yes)
```

## Both sides: NO FINDING

The pre-registered conclusion applies and is not re-litigated:
**model-versus-price disagreement does not select profitable player props on
this data in either direction, and the prop card does not ship as a
disagreement scanner.**

The under arm's point estimate is −0.2% against a −2.2% control. It is not
read. Its 97.5% interval is 36 points wide and contains zero comfortably, and
a point estimate inside an interval that wide is a number the data did not
produce.

What is worth saying is the *direction*: the over arm lost badly and the
under arm did not, which is exactly what
`docs/PREREG_MARKET_VS_MODEL.md` predicted from the structural bias — our
model sits below the market's number more often than above it, so a scan that
read only overs was drawing every pick from its own upward tail. The
prediction was made before this was run and it came out the right way. That
is a point in favour of the *diagnosis*, not evidence for the *bet*.

## The bias check that had to be run first

An under arm looking good is exactly what a model biased low would produce,
and that would be an instrument fault rather than a finding. Checked before
reading anything into it:

```
  actual over rate    0.4887
  mean model P(over)  0.4990
  mean market P(over) 0.5066
```

**The model is not biased low — if anything it is a shade high**, and the
deciles track the outcome monotonically from 0.31 predicted / 0.35 actual up
to 0.66 / 0.67. The under arm is not an artifact of a sagging model.

## An observation this run produced that nobody registered

The two controls are 6.9 points apart: taking every **over** at the best
available price returned **−9.1%** and taking every **under** returned
**−2.2%**. Both controls select on nothing at all. Consistent with it, the
market's mean P(over) of 0.5066 sits 1.8 points above the actual 0.4887 —
**the board as priced leans over, and the overs did not arrive.**

That is the well-documented retail over-lean in player props, and it is an
observation about the market rather than anything our model did.

**It is explicitly NOT a finding and must not be treated as one.** It is the
third thing looked at in this week of prices, it was not registered in
advance, and the under control's own interval [−8.1, +3.7] contains zero.
Reporting it here, in the losers' column, is how it gets to be examined later
without being smuggled in as a result now. If it is to be tested it needs its
own registration, a fourth-look correction, and a forward period — and a
−2.2% return is still a losing bet even if it is real.

## What changed as a result

- The scan reads both sides permanently. That was a bug fix and it stands on
  its own merits regardless of what the arms returned.
- `_propboard.resolve()` now **refuses a whole-number line** rather than
  guessing. Every line in the capture today is a half, so no push is possible
  — but on a line of 1.0 a batter with one hit pushes, and scoring that as an
  under win would have quietly inflated the very arm this run was measuring.
- **The lineup split is now on a real sample.** Pooling both sides moved the
  season-average-only arm from n=7 to n=49: with tonight's slot **−1.4%**
  (n=227), season average only **−25.3%** (n=49). The intervals still
  overlap and this is still not significant, but it is no longer a number
  that meant nothing.
