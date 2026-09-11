# Pre-registration: when a depleted lineup posts, does the price move against that team?

**Written 2026-09-11, before the measurement was run.** The criterion below is
fixed. It is not moved afterwards to rescue a result.

---

## Why this event and not another

`docs/EVENT_DIRECTION_RESULT.md` ran three pre-registered direction tests and
none could answer, for three different reasons. Two of them were about
**timing**: weather news arrives before any book has priced the game, and IL
placements are filed against games already played.

`lineup_posted` has neither problem. It arrives a median **2.9 hours before
first pitch** — inside the window where a market exists, is liquid, and is
about to be bet — and it is the largest event class we hold: **255 distinct
posted lineups**, 165 of them with three or more prior lineups for the same
club, accruing at roughly 16 signable per day.

It was reported there as *unsigned*, because nobody had built a way to say
which direction a posted lineup should push a price. This document builds it.

## The trap this design exists to avoid

**Most lineup churn is not news.** A posted lineup differs from that club's
previous one by a mean of **2.22 batters out of 9**; only 24 of 255 are
identical. Almost all of that is rest days and platoon splits — routine,
scheduled, and *already priced*.

A signer that scores "different from last night" as news would spend most of
its sample measuring the weekly bench rotation, and would look directionally
sensible while doing it. The baseline must approximate **what the market
expected**, not **what happened last night**.

## What "expected" means here, fixed before measuring

For a club's game on date D, using only lineups that club posted **strictly
before D**:

- Each player's **appearance rate** = (lineups he started) / (lineups posted).
- The **expected lineup** is the nine players with the highest rate.
- Ties are broken by **most recent appearance first, then lowest player_id** —
  a deterministic rule stated here so it cannot be chosen later to suit an
  answer.
- **Surprise** = the sum of the appearance rates of expected-nine players who
  are **not** in tonight's lineup.

Weighting by rate is the whole point: a man who starts nine nights in ten and
is absent is news; a man who starts five in ten and is absent is Tuesday.
Surprise is zero when the expected nine all play, and grows with both the
number of missing regulars and how reliable they were.

Measured on the real data before writing this: surprise runs **0.00 to 3.62,
median 1.38** across 197 scorable lineups, with 61 distinct values. There is
something to sign.

**Minimum history: 3 prior lineups.** Below that an appearance rate is noise.

## The sign, fixed before measuring

**One a-priori assumption, stated plainly because everything rests on it:
teams play their best available players, so a regular who is missing is on
average better than whoever replaced him.** A depleted lineup is a weaker
lineup.

The board tracks the **home** team's de-vigged win probability. So:

| event | predicted move in the home number |
|---|---|
| **home** lineup posts with surprise > 0 | **down** |
| **away** lineup posts with surprise > 0 | **up** |

Getting that mapping backwards would invert the entire result while printing
a plausible number, so it is one expression in the code with its own test.

**Events with surprise exactly zero are excluded** — they carry no
directional claim — and their count is reported.

## Why this route, and what was rejected

A richer signer would score lineup *quality*, not just availability. Three
things were checked before choosing:

- **`src/analysis/strength.py` cannot do it.** Its own docstring, line 81:
  *"Lineups are ignored entirely. A club resting four regulars is priced as
  its season self."* No function in it takes a player, a lineup, or a batting
  order.
- **The wOBA route is dead for this population.** `src/research/matrix.py`'s
  per-batter numbers come from `rebuilt.accumulate`, which reads
  `data/historical/statcast/` — **that directory does not exist**. The only
  cached matchup matrices on disk cover **2023 and 2024**; the events under
  test are all 2026-08 and 2026-09. Zero overlap.
- **Composing `playerprops.batter_rates` nine-wide is possible but
  self-selecting.** It refuses a batter under 40 plate appearances, and
  **only 153 of 287 posted lineups (53%) have all nine batters clearing that
  floor.** The batters who refuse are the call-ups and platoon players — that
  is, precisely the ones whose appearance is the news. Requiring all nine
  would systematically drop the lineups most worth measuring.

So the primary uses **availability, not quality**: it needs no batter model,
no plate-appearance floor, and no data beyond the lineups themselves, and it
does not select against the newsy lineups.

## What is measured

**Population.** Every `lineup_posted` event where the club has at least 3
prior posted lineups, surprise > 0, and the game's moneyline board carries a
consensus quote on both sides of the event inside the window.

Consensus, window, de-vigging, the `MIN_BOOKS = 3` floor and the
in-play exclusion are all unchanged from `scripts/probe_event_direction.py`
and are not restated as new choices.

**Anchor:** `observed_utc` — when *we* saw it, which is what we could have
acted on.

**Move:** net change in the consensus home probability from the last quote at
or before the anchor to the last quote within `HORIZON_MINUTES = 120`. Net,
not peak.

**Statistic:** hit rate — of events that moved at all, the fraction that moved
in the predicted direction. Exact ties leave the denominator and are counted.

**Uncertainty:** clustered bootstrap over **games**, 2,000 resamples, seed
`20260911`. Both lineups of one game read the same board and are not
independent.

## The decision rule, fixed before running

One primary hypothesis, so **α = 0.05** and intervals are reported at 95%.

- **CONFIRMED** — interval lower bound **> 0.50** and `n >= 25`.
- **REFUTED** — interval upper bound **< 0.50**. The market moves the other
  way, which would mean the sign was declared backwards, and is a finding.
- **UNDETERMINED** — interval spans 0.50, or `n < 25`.

No rescue clauses. The window is not swept, the minimum history is not tuned,
the surprise threshold is not raised until something clears, and no subset is
promoted on the strength of its point estimate.

## The sensitivity control, and what a null is worth without it

The last round's lesson was that **a null from an untested instrument is
worth nothing**. Its positive control failed on sample starvation, and every
null beside it became uninterpretable.

This test's control is a **dose-response check**: split the scorable events at
the median surprise and compare how far the price moves (absolute, ignoring
direction) after a big surprise versus a small one.

- If big surprises move the price **more** than small ones, the instrument can
  see lineup news, and a null on direction means the direction is genuinely
  not predictable.
- If the two are **indistinguishable**, this instrument cannot detect lineup
  news at all, **no null below it is evidence of absence**, and the probe must
  say so rather than print a number.

This is a magnitude check, not a direction claim, so it is not part of the
decision rule and carries no correction. It decides only whether the primary
result may be interpreted.

## Secondary, descriptive — declared now so they cannot appear later

None of these can promote anything.

1. **Before-window.** The same statistic over the 120 minutes *before* the
   anchor. A before-rate as high as the after-rate means the market had
   already moved and we are late.
2. **Surprise tercile breakdown** of the hit rate. Reported for all three; no
   tercile is promoted.
3. **Novel starters** — players in tonight's lineup never seen in any prior
   lineup for that club (call-ups, new acquisitions). Reported as a count
   only; 46 of 197 lineups have exactly one.
4. **Quality composition**, if it is ever built: `batter_rates` nine-wide with
   a declared league-average fallback for sub-floor batters, so it does not
   drop the newsy lineups. It is **not** run here, and if run later it needs
   its own pre-registration and its own sign.

## What this cannot say, in advance

- **It is not a backtest.** Moving in a predicted direction is not profit. Vig,
  limits, and whether a bet could have been placed at that instant are
  untouched.
- **Surprise conflates injury with rest.** A regular missing because he was
  hurt this morning is different from one rested on a scheduled day, and
  appearance rate cannot tell them apart. The weighting reduces this; it does
  not remove it.
- **`observed_utc` is our poll time.** Our watchers run every fifteen minutes,
  so a real window could be that much larger — or the news could have been
  public for fourteen of those minutes.
- **One partial season of one sport.** Whatever this finds is a hypothesis
  about MLB 2026, not a law.
