# Result: does feeding the opposing starter improve the batter total-bases model?

**Rule id** `TB_STARTER_AWARE_V1` · **Registry id**
`TB_STARTER:starter_aware_total_bases:batter_total_bases` · **Registration**
`docs/PREREG_TB_STARTER_AWARE.md`, commit `c56aa322e01e1636fe203c537b8b5f438d110a01`
(2026-10-04T00:54:36Z), after the harness commit
`e782360abd824553b75e6e30bb341ae454b06df0` (2026-10-04T00:51:59Z). The runs below were
generated at 2026-10-04T00:55:46Z (2023) and 2026-10-04T00:56:07Z (2024), after both.
**Freeze check:** the sha256 of the registration file (LF-normalised) recomputed to
`058b9833dc9333433eae0b564519bdbbcc4c0706f254d29d04fe7790b7bfae7d` before any result was
read, and matches the registry row's note. The registration stands.

## Verdict, by the registered rule, in its own words

> **SUPPORTED** only if the 95% date-clustered bootstrap interval of mean
> d = loss(without) - loss(with) on 2024 lies entirely above zero AND the 2023 point
> estimate is positive.

The primary event (probability of 2 or more total bases) on 2024 has interval
**[+0.000079, +0.000714] nats**, entirely above zero, and the 2023 point estimate is
**+0.000489**, positive. **The primary verdict is SUPPORTED.**

That is a narrow, small, paper result and the rest of this document is about how
little it licenses: the effect is about 0.0004 nats per batter-game (0.06% of the
log loss), it sits at the smallest size this sample could resolve, the 2024 interval
clears zero by 0.00008, the secondary event is **not** confirmed, it meets only the 95%
bar and not the registry-wide family-wise bar, and the starter's identity carries a
disclosed hindsight that favours the starter-aware arm. Registry result:
`candidate`, not `survivor`; no falsification battery has been run.

## Sample sizes

| | 2023 | 2024 |
|---|---|---|
| box-score rows read | 73,878 | 73,773 |
| batter rows | 50,793 | 50,686 |
| excluded: below the 40-PA floor (`PropError`) | 7,599 | 7,642 |
| excluded: no league history (season's first date) | 302 | 277 |
| excluded: not a regular-season game / unmatched `game_pk` | 39 | 0 |
| excluded: box date differs from the result row's date | 0 | 30 |
| excluded: duplicate batter-game, side/team mismatch, no outcome | 0 | 0 |
| **scored batter-games (both arms)** | **42,853** | **42,737** |
| starter known | 42,009 | 41,725 |
| starter unknown (identical in both arms) | 844 | 1,012 |
| of which: no prior logged appearance that season | 834 | 991 |
| of which: no probable id | 10 | 21 |
| slot known from the posted lineup | 37,706 | 37,671 |
| distinct dates (bootstrap clusters) | 173 | 174 |

Every excluded row left both arms. The exclusion counts are in
`data/research/tb_starter/tb_starter_{2023,2024}.json` under `counts`.

## Primary: probability of 2 or more total bases

Positive `d` means the starter-aware arm predicted better. Interval: 95%, 2,000
date-clustered resamples, seed 20261003.

| | log loss without | log loss with | mean d (without minus with) | 95% interval |
|---|---|---|---|---|
| 2023 (first look), n = 42,853 | 0.628996 | 0.628507 | **+0.000489** | [+0.000188, +0.000797] |
| 2024 (confirming), n = 42,737 | 0.619487 | 0.619085 | **+0.000402** | [+0.000079, +0.000714] |

Brier, without to with: 2023 0.219145 to 0.218924; 2024 0.214760 to 0.214580.

## Secondary: probability of 1 or more total bases

Computed and published; it cannot change the verdict and cannot rescue a primary.

| | log loss without | log loss with | mean d | 95% interval |
|---|---|---|---|---|
| 2023, n = 42,853 | 0.671075 | 0.670738 | +0.000337 | [+0.000005, +0.000693] |
| 2024, n = 42,737 | 0.670450 | 0.670148 | +0.000302 | [-0.000110, +0.000722] |

Under the same rule the secondary would be **NOT SUPPORTED**: the 2024 interval
includes zero. The direction agrees with the primary; the confirmation does not.

## Starter-known subset and posted-lineup subset (descriptive)

The starter-unknown rows contribute exactly 0 to `d`, so the known subset is the
undiluted effect.

| subset, primary event | 2023 mean d [95%] | 2024 mean d [95%] |
|---|---|---|
| starter known (42,009 / 41,725) | +0.000499 [+0.000192, +0.000811] | +0.000412 [+0.000081, +0.000732] |
| posted lineup, slot known (37,706 / 37,671) | +0.000711 [+0.000381, +0.001051] | +0.000601 [+0.000256, +0.000937] |

Starter-known, secondary: 2023 +0.000344 [+0.000005, +0.000705]; 2024 +0.000309
[-0.000113, +0.000740]. The posted-lineup subset is larger than the full population's
effect in both seasons, so the result is not an artefact of bench rows.

## What size of effect the sample could see

Observed standard error of mean `d` (bootstrap half-width over 1.96) and the minimum
detectable effect at about 80% power, two-sided 5% (2.8 times the standard error):

| | 2023 SE | 2023 MDE | 2024 SE | 2024 MDE |
|---|---|---|---|---|
| primary, all rows | 0.000155 | 0.000435 | 0.000162 | 0.000454 |
| primary, starter known | 0.000158 | 0.000442 | 0.000166 | 0.000465 |
| secondary, all rows | 0.000175 | 0.000491 | 0.000212 | 0.000595 |

**The observed primary effects (0.000489 and 0.000402) are at or just below the
minimum detectable effect.** The instrument can see an effect of this size only about
as often as not. That has two consequences, both stated plainly: a true effect much
smaller than 0.0004 nats would have read as a null, and a result that clears zero
while sitting at the detection limit is the kind whose size is most likely to be
overstated by selection. The 2024 interval's lower end, +0.000079, is the honest
statement of how little is excluded.

For scale, using only the reported standard errors and treating the estimates as
normal (arithmetic, not a registered statistic): the 2024 primary is about 2.5 standard
errors from zero, two-sided p about 0.013; the 2023 primary about 3.2, p about 0.002.
The registry-wide family-wise bar the repo holds other registrations to,
`0.05 / 48` which is about 0.001, would **not** be met by 2024. The registration set
the 95% interval and said it would not meet that bar (section 7); this restates it.

## Descriptive tables (no decision rides on them)

**Starter factor distribution** (starter-known rows; the bounds are 0.80 and 1.25):

| | n | min | p05 | p25 | median | p75 | p95 | max | at lower / upper bound |
|---|---|---|---|---|---|---|---|---|---|
| 2023 | 42,009 | 0.800 | 0.908 | 0.967 | 1.002 | 1.043 | 1.108 | 1.250 | 0.03% / 0.13% |
| 2024 | 41,725 | 0.800 | 0.908 | 0.964 | 1.001 | 1.043 | 1.116 | 1.212 | 0.09% / 0.00% |

The factor is a modest multiplier: the middle half of starters sit within about 4% of
league, and the bounds almost never bind.

**Probability movement.** Primary event: the WITH arm moves a batter-game's probability
by more than one point in **39.3%** (2023) and **39.4%** (2024) of batter-games, mean
absolute move 0.0098 and 0.0099. Secondary: 46.4% and 48.1%. The mean probability is
nearly unchanged (primary 0.3311 to 0.3322 in 2023; 0.3171 to 0.3180 in 2024).

**Mean paired difference by starter-factor tercile** (starter-known rows, equal-count
terciles; mean `d`, with the actual rate of the event in that tercile):

| primary event | n | factor range | mean d | actual rate | mean p without | mean p with |
|---|---|---|---|---|---|---|
| 2023 low factor | 14,003 | 0.800-0.980 | +0.000294 | 0.3259 | 0.3308 | 0.3184 |
| 2023 middle | 14,003 | 0.980-1.026 | -0.000053 | 0.3331 | 0.3313 | 0.3317 |
| 2023 high | 14,003 | 1.026-1.250 | +0.001256 | 0.3515 | 0.3314 | 0.3466 |
| 2024 low factor | 13,908 | 0.800-0.977 | +0.000097 | 0.3098 | 0.3169 | 0.3040 |
| 2024 middle | 13,908 | 0.977-1.027 | +0.000099 | 0.3276 | 0.3172 | 0.3175 |
| 2024 high | 13,909 | 1.027-1.212 | +0.001041 | 0.3397 | 0.3174 | 0.3326 |

| secondary event | n | mean d | actual rate | mean p without | mean p with |
|---|---|---|---|---|---|
| 2023 low | 14,003 | +0.001877 | 0.5565 | 0.5911 | 0.5761 |
| 2023 middle | 14,003 | -0.000076 | 0.5704 | 0.5921 | 0.5926 |
| 2023 high | 14,003 | -0.000768 | 0.5853 | 0.5921 | 0.6097 |
| 2024 low | 13,908 | +0.001887 | 0.5490 | 0.5816 | 0.5658 |
| 2024 middle | 13,908 | +0.000038 | 0.5724 | 0.5822 | 0.5825 |
| 2024 high | 13,909 | -0.000997 | 0.5754 | 0.5823 | 0.6003 |

Reading it, as observation and not as a tested claim: **the starter factor does sort
outcomes.** The actual rate of 2 or more total bases rises from low to high tercile
in both seasons (0.326, 0.333, 0.352; then 0.310, 0.328, 0.340), and the WITH arm's
mean probability follows that gradient where the WITHOUT arm is flat. Almost all of the
primary gain comes from the high-factor tercile. On the secondary event the model
already **over**-predicts 1 or more total bases by about two points overall (0.592
against 0.571 in 2023, and by more in the low-factor tercile), so raising the
probability against hit-prone starters pushes it further from the truth and the gain
comes only from the low-factor tercile; that is a level miscalibration of the existing
model on that line, not a starter effect, and it is why the secondary does not confirm.

How much of the primary gain is only a level shift rather than the gradient? The WITH
arm's mean probability is higher by 0.0011 (2023) and 0.0008 (2024) while the model
under-predicts the event by 0.0065 and 0.0086. A pure level shift of that size is worth
about `shift * gap / (p * (1 - p))`, roughly 0.00003 nats, 6-8% of the observed gain.
This is back-of-envelope arithmetic added after the run, not a registered analysis; it
says the gain is mostly the gradient.

**Reliability** (ten equal-width bins, both arms, both events, both seasons) is in the
artifacts under `summary.reliability`. The two arms track each other closely. The
existing model's known defect shows in both: in the primary event the 0.1-0.2 bin
predicts 0.178 and 0.171 and sees 0.105 and 0.093 (n 554 and 972, WITHOUT arm; the WITH
arm is similar), and the 0.3-0.4 bin is about 1.0-1.5 points low. This comparison
neither fixes nor worsens that.

## What the sample could and could not see

**Could see:** a starter-aware effect of at least about 0.00045 nats per batter-game on
the primary event, at about 80% power, in each season; a gradient across starter-factor
terciles; a difference between the arms in the direction registered.

**Could not see, and did not test:**

- **Anything about price.** Whether a starter-aware probability would have found value
  against a 2026 posted line is **NOT RUN**: it needs sealed-window pitcher-log rows as
  inputs, open owner decision D1 in `docs/PREREG_PROP_FAMILIES_DRAFT.md`. A better
  probability is not a better bet; the market may price the starter too.
- **A hindsight-free starter.** `*_probable_id` is the first-pitch starter, not the
  announcement (`docs/AUDIT_PROBABLE_PITCHER_PIT.md`: 99.90% and 99.92% equal to who
  threw the first pitch; 2-8% of games may carry a scratch a live system could not have
  known, an unmeasured estimate). Only who he is has hindsight; the statistics fed are
  strictly pre-game. This favours the WITH arm, so a live effect would be no larger.
- **The retroactive lineup slot** (identical in both arms) and the **2025-fit slot
  table** (identical in both arms; it cannot favour either).
- **Any improvement to the model's other known defects:** no park factor, no platoon
  split, i.i.d. plate appearances, a fixed starter share. It says this adjustment, as
  written, helps by a small amount; it does not say it is the right adjustment.
- **2025, 2026 or another sample.** Two seasons, one pipeline, one seed, one run each.
- **Sensitivity to the regression and bound constants.** Nothing was tuned, and nothing
  was swept; no claim is made about 300, 0.62 or 0.80-1.25 being right.

## Deviations, decisions and fixes, all disclosed

1. **A script defect found on the first invocation, before any row was priced.**
   `scripts/tb_starter_compare.py` verified the box-score archive by hashing the `.gz`
   file; `SHA256SUMS` records the hash of the **decompressed** content, so the check
   refused a correct archive. Fixed to hash the decompressed bytes, with a new test
   (44 tests now; the registration said 43). The script's git blob moved from
   `5306b1cfad910e108aa412cbb5de5a841557e779` (registered) to
   `f2fd59f2ed33f76698b5a18a061b74e4773e72d9`. No statistic, population, rule or parameter changed; `src/research/tb_starter.py` is
   byte-identical to the registered blob `3180a6cab6312c2adad8ca85ef0a43c2466af651`. The
   crash preceded any pricing, so this is the case the registration's section 14
   allows (a defect that corrupted nothing and showed no result).
2. **Artifact `code_blob_sha1` values differ from the committed blob ids.** The
   artifact hashes working-copy bytes, which on this Windows checkout carry CRLF line
   endings for files edited by a text-mode script; `git hash-object` (which normalises)
   gives the committed ids quoted in this document. Content is the same.
3. **Box-score source.** The registration named the tracked, checksummed archive
   (`data/archive/historical/boxscores/*.jsonl.gz`); the untracked
   `data/processed/boxscores_*.jsonl` copies are absent from the checkout. The archive's
   decompressed sha256 matched `SHA256SUMS` for both seasons (recorded in the artifacts).
   The 2025 archive was never opened.
4. **Two exclusions the design did not predict, counted not hidden:** 39 batter rows in
   2023 belong to a game that is not regular season or not in the results file, and 30
   batter rows in 2024 sit on a date that differs from the result row's date (they are
   excluded, both arms).
5. **Verification beyond the tests.** A 400-row random sample per season was
   recomputed by a separate brute-force path (league and batter history by a linear scan
   with `date <` in the raw rows, starter totals by a linear scan of the raw pitcher
   log, then `price_prop` for both arms and both lines): **0 mismatches in 800 rows**, and
   the opposing-starter side mapping agreed with the pitcher log's `is_home` flag on all
   799 checkable rows. Re-running 2023 reproduced an identical row digest and summary.
   The checker was a scratch script and is not committed.

## What this means for the product

The prop numbers shown today ignore the opposing starter. On 2023 and 2024 the unused
adjustment the code already carries improves the model's probability that a batter
reaches 2 or more total bases, the product's main total-bases line, by a small
amount: about 0.0004 nats per batter-game, which moves the probability by more than a
point on roughly four batter-games in ten and is concentrated where the starter is
hit-prone. By the registered rule that is **SUPPORTED**.

Does this support asking for the separate promotion process? **It supports asking, and
nothing more, and the ask should carry the caveats with it.** The effect is tiny and at
the detection limit, so its size is likely overstated; it meets the 95% bar but not the
family-wise bar; the line-above-one-total-base secondary did not confirm; and the
starter identity used here has hindsight a live board lacks. The question that matters
for money has not been asked: a probability that is closer to the outcomes is not value
unless it is closer than the **market's** number, and the repo's own earlier
head-to-head found calibration overall is not calibration where the model disagrees with
the price. That test needs the 2026 priced lines, which means owner decision D1, and a
forward test on announced probables (`rosterwatch` records them with timestamps). This
result authorizes no change to any card, fingerprint or published number.

## Registry

`TB_STARTER:starter_aware_total_bases:batter_total_bases` receives verdict `candidate`
(effect +0.000402, 2024 interval [+0.000079, +0.000714]); no falsification battery has
been run, so it is not a `survivor`. `total_searched()` after the verdict: 48
registered hypotheses, 1 sweep (8,811 internal candidates), 2 audits; 41 read, 10 not
read; on `market = "batter_total_bases"`: 1 hypothesis (this one, 2 events).
