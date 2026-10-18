# PREREG: the Hound verdict ("good or lucky") and the retirement rule

Registered 2026-10-17, BEFORE `src/hounds/verdict.py` exists and before any
hound's closing-line value, units, win rate or verified-share has been computed
or looked at. What had been looked at when this was written: the list of
system ids in the paper ledgers and how many paper wagers each holds (counts
only, no outcome, no price, no closing line). Nothing below was tuned to a
number.

PAPER ONLY. A hound is a rule that makes simulated flat one-unit bets. No
money is ever staked, and nothing here is betting advice.

## 0. Why a referee exists

A hound that is up 12 units after 80 bets has told you almost nothing: a
coin-flipping bettor is up 12 units that often. Units take hundreds of bets to
separate a skill from a hot streak, and a bettor can run out of runway first.
The closing price answers sooner. If the price a hound took keeps being better
than where the whole market later settled, that is evidence about the choice,
not the luck of the result. So the referee reads the closing line, never the
win/loss units, and it refuses to speak until it has enough bets to say
anything.

## 1. What is measured (the only input to the verdict)

For each graded bet of a hound the referee takes the existing closing-line
measurement `src.report.clv.measure_decision` (read-only, unchanged): the
de-vigged multi-book consensus probability for the exact selection (same line)
from the last capture strictly before first pitch, minus the break-even
probability of the price the hound took. In percentage points:

    clv_pts = 100 * (closing_consensus_probability - implied_probability(price_taken))

Positive means the market later said the hound's side was more likely than the
price it took requires.

A bet is **measurable** only if ALL of these hold (the doctrine cut of
`src.report.clv.is_publishable`, with one stated difference below):

1. `clv_bps` exists (a named absence such as a thin or missing closing board
   makes the bet unmeasurable; it is never counted as zero);
2. its decision record is stamped `live_pre_commencement` (not a replay, not
   written after first pitch, not unstamped);
3. the closing capture is within 90 minutes of first pitch
   (`CLOSING_LEAD_STALE_SECONDS`, not "stale").

The one difference from `is_publishable`: it also drops controls and market
references. Hounds are shown to the public AS baselines, labelled as such, so
that third condition is not applied here. Conditions 2 and 3 are, and they are
the ones that retracted a headline once.

**Measurement bias, stated up front.** The price taken carries the book's
margin and the close has had it removed, so `clv_pts` starts below zero by
roughly half the hold before any line has moved. That is why one of the
labels below is named PAYING THE VIG. It is a property of the instrument,
identical for every hound, and it is not corrected for.

`n` below always means the count of measurable graded bets. Pushes and voids
are not measurable bets.

## 1a. Segments: forward only (added before the first commit, same registration)

Every graded hound bet carries a `segment`:

* `forward` -- the hound's rule was written, and the bet recorded, before the
  game started (a live pre-commencement record). The house systems read from
  the engine ledgers are all forward.
* `replay` -- a rule written on or after 2026-10-18 applied to boards that had
  already been captured earlier. The rule never saw the outcomes, but its
  author had seen the world those boards came from, so a replay record is a
  rehearsal, not a forward test.

The verdict (`n`, the mean, the interval, the label), the units line's
threshold, the retirement rule (section 5) and `verified` use **forward bets
only**. Replay bets are summarised in their own block on every hound (record
and units, labelled replay) and are never added to any forward figure,
sparkline or leaderboard order. A hound with no forward bets is TOO EARLY with
n = 0, whatever its replay shows.

## 2. The statistic and its interval

* Statistic: the mean of `clv_pts` over measurable bets.
* Interval: 95 % percentile interval from a **date-clustered bootstrap**.
  Bets on one slate share weather, schedule and market conditions, so whole
  decision dates (UTC date of `decision_utc`) are resampled, not bets. 2,000
  resamples, seed 20260828, dates sorted ascending before resampling,
  percentiles taken at indices `int(0.025 * k)` and `min(k-1, int(0.975 * k))`
  of the sorted draws. This is exactly `src.model.discovery.clustered_bootstrap`
  (`BOOTSTRAP_RESAMPLES`, `BOOTSTRAP_SEED`); `src/hounds/stats.py` reproduces it
  from per-date sums for speed and a test pins the two to the same answer.
* Fewer than two distinct dates: no interval; the label is TOO EARLY.

## 3. The labels (closed set, applied top to bottom, first match wins)

| Label | Rule | Sentence template (numbers filled by code) |
|---|---|---|
| `TOO EARLY` | `n < 150`, or no interval | "Only {n} of its bets have a measurable closing price. At least 150 are needed before this means anything." |
| `BEATING THE CLOSE` | `n >= 150` and CI low > 0 | "The price it took beat the closing market by {mean} points on average (95% interval {low} to {high}) over {n} bets." |
| `PAYING THE VIG` | `n >= 150` and CI high < 0 | "The price it took was worse than the closing market by {abs mean} points on average (95% interval {low} to {high}) over {n} bets." |
| `NO DIFFERENT FROM THE MARKET` | `n >= 150` and CI spans 0 | "Over {n} bets its price was {mean} points from the closing market on average (95% interval {low} to {high}); that cannot be told apart from zero." |
| `NOT MEASURED` | the hound's bets carry no closing-line pipeline (the paused public card, whose graded entries are not decision records) | "The referee does not re-measure this hound; see its retirement note." |

150 is chosen because the standard error of a mean of clustered percentage-point
differences with a per-bet spread near 5 points falls below about 0.4 points
only in the low hundreds of bets, and because anything below is shown as TOO
EARLY rather than as a weak version of a verdict. It is a floor, not a promise
that 150 bets suffice.

The label is **never** a function of units, win rate, record or streak. No
field of the units line can move it.

## 4. The units line (separate, always shown, never an input)

Every hound page prints a line that is labelled as being about luck and not
about quality:

* fewer than **1,000** graded bets: "Win/loss units over fewer than 1,000 bets
  say nothing about skill. At one unit a bet, ordinary luck alone moves a
  1,000-bet total by about 32 units either way." (1 unit bet-level standard
  deviation x sqrt(1000) = 31.6.)
* 1,000 or more: "Win/loss units are shown for the record. They never change
  the label above."

`units_recorded_price` is flat one unit settled at the price the hound took
(the price in the paper ledger). `units_average_price` is the same bets settled
at the average (mean decimal) price of the books quoting that exact selection
on the last captured board at or before the decision, shown only where at least
3 books quoted it; it is the figure a bettor shopping nothing would have
seen. A hound reports `units_average_price` only when that board exists for at
least 90 % of its graded non-void bets, else null. Neither figure feeds the
label. The retirement rule below is the ONLY place units are read, and only to
stop a hound from running forever, not to praise one.

## 5. Status and the retirement rule (house hounds, mechanical)

Evaluated by code on every refresh from the append-only ledgers, never by
hand, never discretionary:

* **RETIRED** when either condition has ever held, on any settled day:
  1. cumulative `units_average_price` (recorded price where no average price
     exists for the hound at all) is **more than 25 units below zero**; or
  2. at or after the first day measurable `n >= 300` and the verdict that day
     is `PAYING THE VIG`.
  The retirement date is the FIRST settled day on which a condition held,
  found by walking the hound's days in order. Because the ledgers are
  append-only and the walk reads only data up to each day, later bets can
  never un-retire a hound. The cause string is "retired: down more than 25
  units" or "retired: closing price verdict PAYING THE VIG at 300+ bets", with
  the date. A hound retired by its owner says "retired by the owner" (user
  hounds, `src.hounds.contract`).
* **BENCHED** (not retired) when its newest bet is more than **7 days** older
  than the as-of day. As-of is the newest decision date in the decision ledger,
  not the wall clock, so the answer is a function of the data.
* **RUNNING** otherwise.

The 25-unit figure is about 8 standard deviations of nothing and about 5
standard deviations of a 1,000-bet total near 32: a hound that reaches it is
already well outside luck on a flat-stake rule with ordinary prices, and the
cut stops publishing a loser, it does not hide it. Retired hounds stay public
in the graveyard with their full record.

## 6. Verified

A graded bet is **verified** when the captured odds at its decision time contain
the price it recorded: the last multi-book capture at or before `decision_utc`,
for that game and market and line, holds a quote from the recorded book with the
recorded price on the recorded side. A hound is `verified: true` when at least
95 % of its graded bets that can be checked (market captured) were verified and
at least 90 % of its graded bets can be checked. Otherwise false, with the
shares reported. Verification is a statement about the record's honesty and
never affects a label.

## 7. What this does not claim

No label is a statement that a hound will win, that a price is wrong, or that
anyone should bet. BEATING THE CLOSE is a statement about past prices; it has
never been observed on this ledger as of this registration (not looked at). The
referee reads only the forward record from 2026-08-28 onward; the sealed
2026-01-01..2026-08-27 window is never read.

Paper only. Not advice.

## 8. Changes (and the one erratum)

This file is frozen at its commit. A change to a threshold, a label rule or the
measurable-bet definition is a new dated section with the reason, and the code
constants in `src/hounds/verdict.py` must cite this file; nothing is tuned to
make a hound's label change.

### 2026-10-17 erratum (wording only, no threshold changed)

Section 5's sentence beginning "The 25-unit figure is about 8 standard
deviations of nothing" is garbled. What it meant: 25 units is the stated
number and nothing is derived from it; for scale, the luck-only spread of a
1,000-bet flat-stake total is about 32 units (section 4). The rule is the 25
units written in section 5, and nothing else.

Section 5's walk reads the hound's forward bets by the day they were graded;
the CLV condition counts a bet from the day its result was graded, using the
bet's decision date as the bootstrap cluster. Hounds with no average-price
board use recorded-price units for the 25-unit rule (stated in section 5).
