# Is our batter-prop probability trustworthy? (2026-09-14, rev. 2)

Produced by `scripts/probe_prop_calibration.py`. Tests:
`tests/test_probe_prop_calibration.py` (31/31 passing, pure functions only,
synthetic rows). Track: calibration.

**Revision note (2026-09-14, same day):** an Opus checker found two real bugs
in rev. 1 of this probe (leakage in the posted-lineup slot, and a same-name
join collision) plus four writing problems in rev. 1 of this doc. Both bugs
are fixed below, the probe was rerun end to end, and every number in this
revision is from that rerun -- **none of the numbers below match rev. 1**,
because the fixes changed which contracts price off a posted lineup versus a
season average, and (in principle) which box row a same-named player grades
against. See "What changed and why" at the end of Method.

## TL;DR

**Switch today's card to a "both-gate": require OUR probability > 0.5 AND
the market's de-vigged probability > 0.5 before a contract is even a
candidate, keep the existing "clears its own price" filter, and rank
survivors by OUR probability (not by the gap).** This is a change from the
"rank by ours alone" rule rev. 1 of this doc recommended. The reason is the
evidence itself, not caution for its own sake: on every cut in this
measurement -- overall Brier, all three markets separately, and (most
directly) the exact slice of contracts where our number and the market's
disagree by 10+ points -- the market's own probability tracked what actually
happened at least as well as ours, and on the disagreement slice
noticeably better. Requiring the market to also clear 50% is not ranking by
the gap (doctrine's actual prohibition); it is refusing to trust our number
alone on a market where the evidence says it should not be trusted alone.

**The under skew is real, but modest -- about a 1-point lean beyond what the
market already shows, not the 5+ point gap suspected going in.** Overs in
this settled sample actually won 53.2% of the time (n=600, paired with 600
Unders by construction). Our own mean predicted probability for Over was
48.4%; the market's was 49.3%. Both numbers lean toward Under relative to
what happened; ours leans about 1 point further than the market's does. That
is a real, directionally consistent bias worth fixing eventually
(`playerprops.py`'s own "No park factor" gap is a plausible cause) but it is
not the dominant story in today's numbers -- the big-gap overconfidence
below is larger and better-evidenced.

**The specific question that matters for today -- contracts where OUR number
beat the market's by 10+ points:** n=32, actual hit rate **40.6%**. We had
called that group **62.1%** on average (21.5 points overconfident); the
market had called it **50.2%** (9.6 points overconfident). A binomial check
against each side's own prediction: if our 62.1% were the true rate, seeing
13 or fewer wins in 32 happens only **1.1%** of the time (reject ours as
calibrated on this slice); if the market's 50.2% were the true rate, 13-or-
fewer happens **18.1%** of the time (not rejected). **A large gap between our
number and the market's is not a reason for extra confidence in our number
-- on this settled sample, it has been the opposite.** Caveat: 25 of the 32
rows (78%) come from one date (09-12), so this is one slate's worth of
evidence wearing a bigger-sounding n; treat the direction as trustworthy and
the exact magnitude as provisional.

**Overall, the market's de-vigged number is slightly better calibrated than
ours, consistently but not overwhelmingly.** Brier: ours 0.24687, market's
0.24057 (market lower/better) on all 1,200 settled contracts; market wins on
Brier in all three individual markets too. The reliability tables are more
mixed than "market wins everywhere": the market is close to exactly
calibrated in its best-populated bucket (60-70%: predicted 63.6%, actual
65.0%) but MORE overconfident than we are in its other populated bucket
(50-60%: market +6.8 points overconfident vs. our +3.8); we are overconfident
in every populated bucket, worst at 70-80% (+18.3 points, n=27). Weighted
across buckets the market's calibration error is smaller (~0.041 average
absolute gap vs. our ~0.051), which is the same direction as the Brier
result, just not a clean sweep. A date-clustered bootstrap on the Brier gap:
point estimate +0.0063 (positive = ours worse), 90% CI [+0.0045, +0.0066].
**Read that CI as directionally supportive, not as proof**: it comes from
only 5 date clusters, one of which (09-12) supplies 69% of the pooled rows,
so its coverage is not the same guarantee a bootstrap with dozens of
independent clusters would give. The per-date signs agree on 4 of 5 dates
(ours worse on 09-09, 09-10, 09-11, 09-12; ours slightly better on 09-08,
the smallest date at n=14) -- that consistency, not the CI's exact bounds, is
the actual reason to believe the direction.

**Coors still cannot be tested at all -- zero settled Coors contracts exist
in this store.** Absence of Coors evidence is not evidence the Coors read is
fine; the exclusion below stays.

**Declared rule for today's card** (2026-09-14 rev. 2), a constant choice,
not a threshold fitted after looking at today's board:

```
PROP_CARD_RULE_2026_09_14 = (
    "A contract is a candidate pick only if BOTH: our probability > 0.5 "
    "AND the market's de-vigged probability > 0.5 (the 'both-gate' -- this "
    "checks each side's OWN probability against 0.5, never the size of the "
    "gap between them, so it does not rank or select by edge). Candidates "
    "must still clear their own break-even price (existing gate, "
    "unchanged). Rank survivors by OUR probability, most likely first. "
    "Exclude any batter_hits/batter_total_bases/batter_runs_scored "
    "contract whose game's home_team is 'Colorado Rockies' from automatic "
    "card picks until this probe (or its successor) has measured at least "
    "20 settled Coors contracts (MIN_SPLIT_N) -- there is still no settled "
    "Coors data to justify trusting or distrusting that number either way."
)
```

Concretely: today's board can still show Coors props and props that fail
the both-gate under `most_likely`/`long_shots` (the board is diagnostic and
already labelled as such); if `select_props` is ever pointed at these three
markets for the live card, both the both-gate and the Coors exclusion belong
next to it.

## Two bugs an Opus checker found in rev. 1, fixed here

### 1. Leakage: the posted-lineup slot was not checked against first pitch

Rev. 1's `_slots_for_date` read `lineup_store.read()` for a date and used
whatever batting order was stored, with no check on WHEN that lineup was
observed relative to that game's own first pitch. The live board only ever
reads TODAY's lineup store, where "stored" and "posted before first pitch"
are the same fact in practice -- nothing enforces it, but nothing has ever
violated it either. Replaying PAST dates breaks that assumption:
`lineup_store.build` is commonly run well after a slate finishes (catching
up the historical backfill), so a stored row's `observed_utc` is routinely
AFTER the game it describes. The checker measured 64 of 65 stored lineup
rows failing this on the current store -- e.g. every 2026-09-09 game's
lineup carries `observed_utc` `2026-09-10T10:11Z`, fetched the next morning,
which is the batting order that ACTUALLY took the field, not the one posted
pregame. Rev. 1's own leakage claims ("cannot be leakier than the real
board... identical point in time"; "No game... ever informs its own
prediction") were **false** for this reason.

**Fix:** `_slots_for_date` now takes a `game_pk_commence` index (built from
`src.board.gamekey.load_map()`, the only store in this project that records
a UTC start time keyed by MLB `game_pk`) and drops any lineup entry whose
`observed_utc` is missing, unresolvable to a commence_time, or not strictly
before it. `propboard.build`/`playerprops.price_prop`'s existing
season-average fallback applies to every dropped entry, exactly as it would
for a game with no lineup posted at all. Effect on this rerun:
`expected_pa_source=batting_slot` dropped from 1,138 of 1,200 settled
records (rev. 1) to **8 of 1,200** (rev. 2) -- the season_average split
below is now the whole story; `batting_slot` is too thin (n=8) to report on
its own. Rev. 1's "season_average beats the market" lead (its own caveat
that this was a thin, unrepeated result) is now moot -- the population it
was measured on barely exists anymore under the corrected filter.

### 2. Join collision: the box-score join had no team check

Rev. 1's `_box_row_for` joined a prop contract to a boxscore row by player
NAME and DATE alone (the prop feed carries no player id) and returned the
first match, with no check that the row's team was actually in that game.
The checker found the box store holds two different players named Max Muncy
(`person_id` 691777 and 571970), both with rows on 2026-09-09, 09-11, and
09-12 -- inside the settled window -- so a same-named collision could have
silently graded a contract against the wrong player's stats. The checker's
own cross-check found 0 mismatches in the 1,200 rev.-1 records (today's
headline numbers were not actually affected), but that was luck, not a
guarantee.

**Fix:** `_box_row_for` now takes the event's `home_team`/`away_team` (read
off the prop row) and, when more than one candidate row matches on name and
date, keeps only the one whose `team_name` is one of those two teams;
neither matching returns `None` (void), never a guess. Effect on this
rerun: **0 mismatches** -- the settled win/loss/void counts by date are
identical before and after adding the guard (12 void, 588 win, 600 loss
retained... see "The numbers" for the exact breakdown), confirming the
checker's finding that today's headline numbers were not affected, while
the guard now holds going forward instead of depending on file order.

## Other caveats that limit how hard to lean on the numbers above

1. **Thin, lopsided sample.** Only 5 calendar dates ever produced a settled
   contract (2026-09-08 .. 09-12), and one date, 09-12, supplies 830 of the
   1,200 records (69%). The bootstrap is date-clustered specifically
   because of this, but 5 clusters is still 5 clusters -- read the CI as
   directionally consistent, not as strong evidence on its own (see TL;DR).
2. **Boxscore history starts 2026-08-30**, four days before the earliest
   prop date this probe could price at all. `playerprops.MIN_PA_FOR_A_RATE`
   (40) refused nearly every batter on 09-03 through 09-07 outright (2,185
   refusals total, the single largest refusal bucket) -- this is a POWER
   problem (too little history to form a rate), not a leakage problem: no
   game or later date informs its own prediction anywhere in this pipeline
   once the lineup-timing fix above is applied (see Method).
3. **"Both sides" does not double the statistical power.** For any
   contract, `Under`'s probability is `1 - Over`'s and its outcome is the
   mirror image, so the squared error each side contributes to Brier/
   log-loss is IDENTICAL. Pooling both sides gives numerically the same
   Brier/log-loss as either side alone -- verified: the `by_side` split
   below prints bit-identical Brier/log-loss for `Over` and `Under`. The
   reliability table's per-bucket rows and the by-side base rates (used for
   the under-skew read in the TL;DR) are the real payoff of including both
   sides; the headline Brier/log-loss numbers are not "twice the data."
4. **`batter_runs_scored` still has no live settlement path.**
   `src.board.settle_props`'s registry keys this market `"batter_runs"`,
   not propboard's `"batter_runs_scored"` (documented at `daily_card.py`
   around `PROP_MARKETS`, 2026-09-12 incident). This probe works around it
   by calling `settle()` directly with the stat (`"r"`), bypassing the
   mismatched registry key entirely -- it does not fix the mismatch, and a
   live pick in this market would still grade VOID forever until that
   registry key is corrected. Out of scope for this track; flagged for the
   integrator.
5. **This is not the live-board's exact code path**, it is a
   reconstruction of it (`src.report.props.board_for_date`'s own
   construction: `playerprops.league_rates` over history strictly before
   the date, each batter's own prior game log, that date's posted lineup
   when the historical store has one AND it passes the pre-first-pitch
   check above). It can be a worse APPROXIMATION of the live board if the
   historical lineup store (`data/historical/lineups.jsonl`, 70
   game-entries total) is missing games the live board's own
   `lineup_store` had at the time, or if a historical lineup was in fact
   observed before first pitch but not recorded with an `observed_utc` that
   proves it (dropped conservatively rather than trusted). Where a slot is
   unavailable, `price_prop` falls back to season average and the contract
   says so (`expected_pa_source`); see the split below.
6. **The 10+ point gap finding is a distinct measurement, not a
   reproduction of `propboard.py`'s -13.4%/-9.1% number.** `propboard.py`'s
   own module docstring (around line 41) and `clears_its_price`'s docstring
   (around line 427) already document that ranking-by-edge result and
   credit it to `scripts/probe_prop_value.py`. This probe's big-gap number
   above is a different measurement, on a different, hand-picked
   population (10+ point disagreements across exactly the three markets in
   this brief, on settled real outcomes) -- it shows the same qualitative
   pattern (trusting our edge over the market has not paid off here
   either), and is corroborating, not a reproduction of that number.

## The numbers

Store sizes: 56,186 prop-quote rows, 4,133 boxscore batter rows (type
`batter` only), covering game dates 2026-08-30 through 2026-09-12 for
boxscores and 2026-09-03 through 2026-09-14 for props.

Settled contracts (win/loss only): **n = 1,200** (600 win, 600 loss by
construction -- paired Over/Under; see caveat 3). 0 pushes. 1,472 voided,
of which 1,460 belong to 2026-09-13/09-14 (no boxscore posted yet --
expected, not a join defect). The remaining 12 voids fall inside the
settled window itself (09-09: 4, 09-11: 2, 09-12: 6) -- batters who did not
appear that day. Outcome counts by date:

| date | win | loss | void |
|---|---|---|---|
| 2026-09-08 | 7 | 7 | 0 |
| 2026-09-09 | 39 | 39 | 4 |
| 2026-09-10 | 35 | 35 | 0 |
| 2026-09-11 | 104 | 104 | 2 |
| 2026-09-12 | 415 | 415 | 6 |
| 2026-09-13 | 0 | 0 | 840 |
| 2026-09-14 | 0 | 0 | 620 |

Refused before pricing at all: 2,185 below the 40-PA floor, 1,589 fewer
than two books quoting both sides, 498 no prior box score.

### Overall: ours vs. market

| | n | Brier | log-loss | base rate | mean prediction |
|---|---|---|---|---|---|
| ours | 1200 | 0.24687 | 0.68733 | 0.500 | 0.500 |
| market | 1200 | 0.24057 | 0.67383 | 0.500 | 0.500 |

Base rate and mean prediction are exactly 0.500 for both by construction
(caveat 3) -- not itself informative; Brier/log-loss are the numbers that
matter here, and both say the market is slightly better calibrated on this
sample.

### Reliability, our probability (bucketed on whichever side we favour)

| bucket | n | predicted | actual | gap |
|---|---|---|---|---|
| 50%-60% | 212 | 0.5712 | 0.5330 | +0.038 |
| 60%-70% | 361 | 0.6328 | 0.5845 | +0.048 |
| 70%-80% | 27 | 0.7383 | 0.5556 | +0.183 |
| 80%+ | 0 | -- | -- | -- |

### Reliability, market probability

| bucket | n | predicted | actual | gap |
|---|---|---|---|---|
| 50%-60% | 305 | 0.5663 | 0.4984 | +0.068 |
| 60%-70% | 294 | 0.6358 | 0.6497 | -0.014 |
| 70%-80% | 1 | 0.7247 | 0.000 | +0.725 (n=1, ignore) |
| 80%+ | 0 | -- | -- | -- |

We are overconfident in every populated bucket. The market is MORE
overconfident than us in its 50-60% bucket but close to exact in its
60-70% bucket (its best-populated one). Weighted average absolute
calibration gap across populated buckets (excluding the n=1 noise row):
ours ~0.051, market's ~0.041.

### By market (n, ours Brier vs. market Brier)

| market | n | ours Brier | market Brier |
|---|---|---|---|
| batter_hits | 454 | 0.23115 | 0.22528 |
| batter_total_bases | 494 | 0.25580 | 0.25018 |
| batter_runs_scored | 252 | 0.25769 | 0.24927 |

The market wins on Brier in all three -- small margins (0.006-0.008), same
direction every time.

### By side (Over / Under)

| side | n | actual (base rate) | our mean prediction | market mean prediction |
|---|---|---|---|---|
| Over | 600 | 0.5317 | 0.4838 | 0.4932 |
| Under | 600 | 0.4683 | 0.5162 | 0.5068 |

Both models under-price Over relative to what happened; ours by about 4.8
points, the market's by about 3.9 points -- a real but modest under-skew,
and ours leans about 1 point further into it than the market's does (TL;DR).

### By expected_pa_source

| source | n | ours Brier | market Brier |
|---|---|---|---|
| batting_slot | 8 | below the 20-row floor (MIN_SPLIT_N) | -- |
| season_average | 1192 | 0.24757 | 0.24091 |

`batting_slot` collapsed from 1,138 (rev. 1, leaky) to 8 (rev. 2, fixed) --
see "Two bugs" above. It is too thin to report a score on its own now;
essentially every settled contract in this store prices off season average.

### Coors Field vs. elsewhere

Zero settled Coors contracts (see TL;DR). The `coors_vs_elsewhere` split
has a single populated group, `elsewhere`, identical to the overall table.

### Ours >= market + 10 points (n=32)

| | value |
|---|---|
| n | 32 |
| actual hit rate | 0.4062 |
| mean our prediction | 0.6210 |
| mean market prediction | 0.5024 |
| gap (ours - actual) | +0.2147 |
| gap (market - actual) | +0.0961 |
| Coors rows in this subset | 0 |
| rows by date | 09-08: 1, 09-10: 2, 09-11: 4, 09-12: 25 |
| P(X<=13 wins of 32 \| p=0.621, our mean) | 0.011 |
| P(X<=13 wins of 32 \| p=0.502, market mean) | 0.181 |

### Date-clustered bootstrap, ours-Brier minus market-Brier

Seed 20260914 (fixed, declared before reading the result), 2000 resamples,
clustered by date so a slate's contracts are never split across the
resample boundary.

- point estimate: **+0.0063** (positive = ours worse)
- 90% CI: **[+0.0045, +0.0066]**
- 5 distinct dates clustered; one (09-12) supplies 69% of the pooled rows
  (caveat 1) -- read the CI as directional, not as strong evidence on its
  own
- per-date diff (ours Brier - market Brier): 09-08 -0.0097 (n=14), 09-09
  +0.0051 (n=78), 09-10 +0.0070 (n=70), 09-11 +0.0066 (n=208), 09-12
  +0.0066 (n=830) -- 4 of 5 dates agree on sign; the one disagreement
  (09-08) is also the smallest date

## Method

**Point-in-time reconstruction, not a recorded probability.**
`data/processed/batter_props.jsonl` stores a raw quote (book, price,
`observed_utc`) and carries no model probability -- there is nothing to
read off the row, so this probe REBUILDS the probability for each
historical slate date using `src.analysis.propboard.build`, the identical
function `src.report.props.board_for_date` calls for a live board, fed:

- `playerprops.league_rates()` over every batter-game STRICTLY BEFORE the
  slate date (`<`, never `<=`),
- each batter's own prior box-score rows, same strict inequality,
- that date's posted lineup slot from `data/historical/lineups.jsonl`
  ONLY when that lineup's own `observed_utc` predates that game's own
  `commence_time` (from `src.board.gamekey.load_map()`) -- see "Two bugs"
  fix #1 above; otherwise `price_prop` falls back to the batter's season
  average (`expected_pa_source` says which).

**Last pre-first-pitch quote.** Every prop row for the target markets is
filtered to `observed_utc < commence_time` before being handed to
`propboard.build` (which itself keeps only each contract's newest
surviving quote per book). Measured on the current store: 0 of 32,618
target-market rows are dropped by this filter -- nothing in this project's
capture has ever recorded an in-game quote -- but the filter stays in
place rather than being trusted to remain unnecessary.

**Markets.** `batter_hits`, `batter_total_bases`, `batter_runs_scored` --
named by the brief. `batter_home_runs` is excluded because no book quotes
the under (`playerprops.NOT_DEVIGGABLE`), so there is no market probability
to compare against at all. `batter_rbis` and `batter_hits_runs_rbis` are
excluded because `playerprops.NOT_PUBLISHABLE` already measured them worse
than a base rate; re-measuring them here would not tell a reader anything
that module does not already say louder.

**Settlement.** `src.board.settle_props.settle()` is called directly with
an explicit stat (`h` / `total_bases` / `r`) rather than through its
market-name registry, because that registry keys runs-scored as
`"batter_runs"` while every other consumer of this market (propboard, the
prop board's transport layer) calls it `"batter_runs_scored"` --
documented at `src/analysis/daily_card.py` around `PROP_MARKETS`
(2026-09-12 incident). Grading by stat name sidesteps the mismatch instead
of rediscovering it; it does not fix it (see caveat 4).

**Join key.** Player full name plus exact slate date
(`src.report.props._by_name`'s join key -- the prop feed carries no player
id, so this is the only identifier the two stores share), NARROWED to the
box row whose own `team_name` is one of the event's `home_team`/
`away_team` whenever the store holds more than one same-name/same-date
candidate (see "Two bugs" fix #2 above). A quote with no matching box row
for that date/team settles `void` (batter did not appear, box store
missing that game, or a same-name collision with no team match) and is
excluded from every score in this report, not scored as a loss.

**Scoring.** Brier score (mean squared error of probability vs. 0/1
outcome) and log-loss (clamped away from the 0/1 boundary at 1e-9, same as
`backtest_player_props.py`'s own `_log_loss`), computed once on our
probability and once on the market's de-vigged probability for the exact
same set of settled contracts.

**Bootstrap.** Resamples calendar DATES with replacement (not individual
contracts) `len(dates)` times per iteration, 2000 iterations, seed
20260914 fixed in the script before this run -- date-clustered because
contracts on the same slate share one league-rate snapshot and often one
park/weather and are not independent draws.

**Binomial check on the big-gap slice.** Exact binomial CDF, computed
against each side's own mean predicted probability on that 32-row subset
(not the 0.5 null) -- the question asked is "if that side's own number
were the true rate, how likely is 13-or-fewer wins", not "is this
different from a coin flip".

## What changed and why (rev. 1 -> rev. 2)

Both fixes described in "Two bugs" above were applied to
`scripts/probe_prop_calibration.py`, the full test suite was extended (31
tests, up from 25 -- the 6 new tests cover the leakage guard and the join
guard, each constructed to fail against the pre-fix code) and the probe was
rerun end to end against the current stores. Every number in this revision
comes from that rerun. The join fix (bug #2) did not change any settled
outcome on this run (0 mismatches, confirmed by the identical win/loss/void
counts by date before and after adding the guard) -- it closes a real gap
without changing today's answer. The lineup-timing fix (bug #1) changed
which fallback (`batting_slot` vs `season_average`) 1,130 of 1,200 settled
records use, which is why several numbers above (the reliability tables,
the by-market Brier scores, the big-gap slice's n and composition) differ
from rev. 1 -- this is the fix taking effect, not new noise.
