# Validation criteria — pre-registered

**Written before any model exists, any backtest has run, or any pick has been
graded.** Committed deliberately at this point so the sequence is provable from
git history.

## Why this document exists first

If you decide what counts as success after seeing results, you will set the bar
wherever the results landed. That is not a judgement about discipline — it is
what everyone does, which is why the fix is procedural rather than personal.

These thresholds are fixed. If a future session is asked to loosen them after
results are in, the correct response is to point at this file and decline.

## Status at time of writing

| Thing | State |
|---|---|
| Probability model | Does not exist. Scoring is uncalibrated. |
| Historical data | Results backfill works; odds backfill unpurchased. |
| Graded picks | Zero. |
| Backtest | Never run. |
| Claims made | None. |

---

## The primary criterion: closing line value

**CLV is the pass/fail metric. ROI is secondary.**

Reasoning: ROI needs on the order of a thousand bets before it separates a real
edge from variance. CLV — whether you consistently bet at better prices than the
market closed at — converges roughly ten times faster, and it is the standard
professional bettors judge themselves by.

If picks beat the closing line, real inefficiency is being found, even during a
losing stretch. If they do not, there is no edge, even during a winning one.

### Thresholds

| Metric | Pass | Inconclusive | Fail |
|---|---|---|---|
| Share of picks beating the close | ≥ 55% | 50–55% | < 50% |
| Mean CLV | ≥ +1.5% | 0 to +1.5% | ≤ 0% |
| Minimum sample | 300 graded picks | < 300 | — |

**Below 300 picks, no verdict is drawn regardless of what the numbers say.**

## Secondary: return on investment

Reported with a confidence interval, never as a point estimate.

At realistic sample sizes the interval will likely still span zero. That is
expected and is not itself a failure — it is why CLV leads. ROI acts as a
sanity check: a strongly positive CLV alongside a deeply negative ROI means
something is wrong with execution or grading, and both need investigating
before any verdict.

| Metric | Pass | Fail |
|---|---|---|
| ROI point estimate | > 0% | < −5% over 300+ picks |
| ROI confidence interval | Lower bound > −3% | Entirely below zero |

## Secondary: calibration holding up live

A model that was calibrated in backtest and drifts live has not generalized.

| Metric | Pass | Fail |
|---|---|---|
| Expected calibration error, live | ≤ 0.03 | > 0.06 |
| Live vs backtest ECE | Within 0.02 | Drift > 0.04 |
| Log loss vs de-vigged market | Model lower | Model higher |

**The market comparison is not negotiable.** If the model's log loss is worse
than simply using the de-vigged market price, it has learned nothing the market
has not, and no CLV figure rescues that.

## Sample-size gates

| Picks graded | What may be claimed |
|---|---|
| 0–99 | Nothing. Reports must state this explicitly. |
| 100–299 | CLV direction may be described as a trend. No verdict. |
| 300–999 | A CLV verdict may be drawn. ROI remains indicative only. |
| 1000+ | Both CLV and ROI may be treated as evidence. |

## Failure criteria — stop conditions

Written as concretely as the pass conditions, because these are the harder ones
to honor.

Stop and reassess if **any** of these hold at 300+ graded picks:

1. Picks beating the close is below 50%. The model is systematically getting
   worse prices than the market settles at.
2. Model log loss is worse than the de-vigged market's.
3. Live ECE exceeds 0.06 — probabilities do not mean what they say.
4. ROI is below −5% with the whole confidence interval under zero.
5. Fewer than 60% of picks were made on games with complete data. A model
   mostly guessing from partial inputs is not being tested.

**A stop is a successful outcome of this process, not a failure of it.** It
means real money was never risked on something that does not work, and the
diagnosis says which layer broke.

## What is explicitly not a criterion

- A winning streak of any length.
- A single profitable week, month, or season.
- Backtest performance on its own — in-sample results prove nothing.
- Any result on fewer than 300 graded picks.
- Anything measured after a mid-sample model change. Changing the model
  restarts the sample.

## Amendment rule

This document may be amended only:

- **Before** the sample begins accumulating, or
- To make a criterion **stricter**, at any time.

Loosening a criterion after results exist voids the sample. If that happens, the
count restarts at zero.
