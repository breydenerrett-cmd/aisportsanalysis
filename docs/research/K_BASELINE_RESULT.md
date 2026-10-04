# Result: does a pitcher-specific strikeout distribution beat a league-rate baseline?

**Rule id** `K_BASELINE_V1` · **Registry id**
`K_BASELINE:pitcher_specific_vs_league_k_distribution:pitcher_strikeouts` ·
**Registration** `docs/PREREG_K_BASELINE.md`, commit
`af528708b8ab8f5daa79aab92dc89450ebb9e868` (2026-10-04T08:27:36-07:00), after the
harness commits `d8402e20c19d6ee9b47191c75b48542a9c05d314` and
`bba4f2b870b6d05e0366159d05ade9a41d1735f7`. The runs were generated at
2026-10-04T15:27:43Z (2023) and 15:27:52Z (2024), after all three.
**Freeze check:** the sha256 of the registration file (LF-normalised) recomputed to
`020ee9052a32451049f752fc8fbc6fa88d72f5ccb92b6f0f25e458d46661b0cc` before any result was
read and matches the registry row's note. The registration stands.

**This is a comparison of forecast quality against what happened. It has no price in it
and makes no claim about betting return. It authorizes nothing.**

## Verdict, by the registered rule, in its own words

> **SUPPORTED** only if, on **both** the 4.5 and the 5.5 line, the 95% interval of mean
> `d` on **2024** lies entirely above zero **and** the **2023 point estimate** of mean
> `d` on that line is positive.

`d = loss(baseline) - loss(candidate)` in nats; positive means the pitcher-specific
candidate predicted better. 95% date-clustered bootstrap, 2,000 resamples, seed 20261004.

| line | 2023 mean d [95%] | 2024 mean d [95%] |
|---|---|---|
| **4.5** (decisive) | **+0.05246** [+0.04329, +0.06160] | **+0.03517** [+0.02773, +0.04257] |
| **5.5** (decisive) | **+0.05008** [+0.04023, +0.05927] | **+0.04305** [+0.03439, +0.05104] |
| 3.5 | +0.05024 [+0.04175, +0.05861] | +0.03530 [+0.02852, +0.04176] |
| 6.5 | +0.04824 [+0.03943, +0.05693] | +0.03172 [+0.02302, +0.03992] |

On both decisive lines the 2024 interval is entirely above zero and the 2023 estimate is
positive. **The verdict is SUPPORTED** (`python scripts/k_baseline_compare.py --verdict`
returns the same). Registry result: `candidate`, not `survivor`; no falsification
battery has been run.

What that means, narrowly: knowing a starter's own earlier strikeouts per batter faced
and batters faced makes the forecast of his strikeout count clearly better than knowing
only the league. That is the lowest bar a pitcher model can face (the baseline ignores
who is pitching), and clearing it says nothing about the market, which prices the same
history and a great deal more.

## Sample sizes and coverage losses

| | 2023 | 2024 |
|---|---|---|
| pitcher-log rows in 2023-24 (both seasons) | 16,725 | 16,725 |
| relief outings (`games_started = 0`), used nowhere | 7,010 (both seasons together) | |
| starts (`games_started = 1`) in the season | 4,858 | 4,857 |
| excluded: duplicate (person, date), other `games_started`, missing or impossible figure | 0 | 0 |
| excluded: no league pool yet (2023 has no prior season in the window) | 528 | 0 |
| excluded: no earlier start by that pitcher this season | 208 | 369 |
| **scored starts (both models)** | **4,122** | **4,488** |
| scored using the same-season pool / the prior-season (2023) pool | 4,122 / 0 | 4,166 / 322 |
| scored starts of 12 batters faced or fewer (openers, early exits) | 208 | 158 |
| distinct dates (bootstrap clusters) | 162 | 181 |

Every excluded start left both models, because both predictions live in one row, and
still fed the league pool and the pitcher's history. Starts of 12 or fewer batters faced
were **kept** (the registered start is `games_started = 1`): 310 of 2023's 4,858 and 217
of 2024's 4,857 starts are that short, 208 and 158 of them scored. The pitcher log holds
no postseason date and no other `games_started` value, so no start was dropped for
type. 2023 lost its first weeks (528 starts, 11% of the season) to the 500-start pool
rule; 2024 did not, and 322 of its early starts were scored from 2023's pool.

## What size of effect the sample could see

Observed standard error of mean `d` (bootstrap half-width over 1.96) and the minimum
detectable effect at about 80% power, two-sided 5% (2.8 times the standard error):

| line | 2023 SE | 2023 MDE | 2024 SE | 2024 MDE |
|---|---|---|---|---|
| 4.5 | 0.00467 | 0.01308 | 0.00379 | 0.01061 |
| 5.5 | 0.00486 | 0.01360 | 0.00425 | 0.01189 |
| 3.5 | 0.00430 | 0.01204 | 0.00338 | 0.00946 |
| 6.5 | 0.00446 | 0.01250 | 0.00431 | 0.01208 |
| expected-strikeout MAE (in strikeouts) | 0.0141 | 0.0394 | 0.0114 | 0.0320 |

**The registration's planning arithmetic was too optimistic and is corrected here.** It
guessed a minimum detectable effect near 0.004 nats per start; the measured one is about
0.011 to 0.014, roughly three times larger, because the per-start loss differences are
noisier than the back-of-envelope SD assumed. It does not matter for the verdict: the
observed effects (0.032 to 0.052) are three to five times the minimum detectable effect,
and the 2024 estimates sit about nine standard errors from zero (0.0352 / 0.0038 on the
4.5 line, 0.0431 / 0.0043 on the 5.5 line; arithmetic from the reported standard errors,
not a registered statistic). The registry-wide family-wise bar the repo holds other
registrations to, `0.05 / 49`, about 0.001 or roughly 3.3 standard errors, would also be
cleared on those numbers, but the registration set the 95% interval and said it would
not claim that bar; this restates it rather than promoting the result.

A null on this instrument would have meant "no gain larger than about 0.011 nats". It
could not have seen a gain of a few thousandths.

## Expected-strikeout error (descriptive, decides nothing)

Mean absolute error of expected strikeouts; `d_mae = |K - E_baseline| - |K - E_candidate|`,
positive means the candidate was closer.

| | mean K | mean E baseline | mean E candidate | MAE baseline | MAE candidate | mean d_mae [95%] |
|---|---|---|---|---|---|---|
| 2023, n = 4,122 | 4.918 | 4.881 | 5.009 | 2.0264 | 1.8764 | +0.1500 [+0.1217, +0.1768] |
| 2024, n = 4,488 | 4.911 | 4.859 | 4.961 | 1.9884 | 1.8757 | +0.1127 [+0.0896, +0.1344] |

The candidate is about 0.11-0.15 strikeouts closer per start. Its mean expected
strikeouts runs 0.05-0.13 above the observed mean in both seasons, and the baseline's
runs 0.04-0.05 below it. This was not diagnosed. A plausible, untested reading is that
the scored starts (pitchers with a start already this season) differ from the pool,
which includes the debuts and the first weeks.

## Descriptive tables (no decision rides on them)

**Shape control.** The baseline is an empirical distribution and the candidate is
Poisson, so the registered contrast mixes pitcher information with distribution shape.
The control is Poisson at the league mean with no pitcher information.
`d_shape = loss(baseline) - loss(control)`, `d_info = loss(control) - loss(candidate)`,
sum = `d`:

| line | 2023 d_shape | 2023 d_info | 2024 d_shape | 2024 d_info |
|---|---|---|---|---|
| 3.5 | -0.00226 [-0.00489, +0.00033] | +0.05250 | -0.00061 [-0.00212, +0.00102] | +0.03591 |
| 4.5 | +0.00026 [-0.00026, +0.00078] | +0.05220 | +0.00025 [-0.00016, +0.00068] | +0.03492 |
| 5.5 | -0.00040 [-0.00123, +0.00042] | +0.05048 | -0.00184 [-0.00316, -0.00065] | +0.04489 |
| 6.5 | -0.00269 [-0.00430, -0.00116] | +0.05093 | -0.00306 [-0.00482, -0.00127] | +0.03478 |

The Poisson shape costs up to 0.003 nats (on the 6.5 line) and is about zero on the 4.5
line; the pitcher's own history supplies 0.035-0.052. So the gain is information, not
shape, and the concern that a Poisson-vs-empirical mismatch could have manufactured or
hidden the result is answered: it did neither at this scale. The `d_info` intervals
are in the artifacts (`summary.all_scored.lines.*.information_effect_descriptive`).

**Subsets** (mean `d`, 4.5 / 5.5; both seasons):

| subset | n 2023 / 2024 | 2023 | 2024 |
|---|---|---|---|
| pitchers with 5 or more earlier starts | 3,348 / 3,384 | +0.04955 / +0.05041 | +0.03912 / +0.04675 |
| excluding starts of 12 batters faced or fewer | 3,914 / 4,330 | +0.04326 / +0.04325 | +0.03118 / +0.03943 |

Every interval in both subsets excludes zero (artifacts, `summary`). The effect is
somewhat smaller without the short starts and about the same for experienced
pitchers: the gain is not confined to thin-history pitchers or to openers.

**Calibration.** Reliability tables for both models and all four lines are in the
artifacts (`summary.reliability`). The baseline is a single probability per line (one
bin). The candidate spreads across 0.07 to 0.93 and tracks outcomes closely in the
middle (2024, 4.5 line: predicted 0.452 / observed 0.456 on n = 1,036; predicted 0.645
/ 0.626 on n = 1,009). Its tails are thin and noisier: the 0.15-0.2 bin predicted 0.151
and saw 0.034 on 29 starts in 2024. Brier scores improve on every line (4.5 line: 0.2488
to 0.2321 in 2024; 0.2488 to 0.2238 in 2023).

## What the sample could and could not see

**Could see:** a gain of about 0.011-0.014 nats per start on a line, in either season,
about 80% of the time; a difference of 0.03-0.04 strikeouts in mean absolute error.

**Could not see, and did not test:**

- **Anything about price.** There are no historical strikeout prices before 2026 and
  2026 inputs before 2026-08-28 are sealed (owner decision D1, `docs/PREREG_PROP_FAMILIES_DRAFT.md`).
  A better probability is not a better bet; the market prices the same history.
- **The opponent, the lineup, the park, the umpire, rest, pitch count, role, velocity.**
  The candidate sees only the pitcher's own earlier starts.
- **A live board.** Both models are fed starts that happened. Whether the starter is
  known in advance, and the line is posted, is not tested.
- **2025, 2026, or another sample.** Two seasons, one pipeline, one seed, one run each.
- **Sensitivity to the constants.** Nothing was tuned: prior weights 70 batters faced
  and 3 starts, 500-start pool, one prior start. No claim is made that those values are
  right.
- **Pitchers outside the log.** The log holds only pitchers who were ever listed as a
  probable; its 4,858 and 4,857 starts are close to the 4,860 and 4,858 team games, so
  the gap is small but not measured here.
- **First starts and 2023's first weeks**, excluded by design.

## Deviations, decisions and fixes, all disclosed

1. **Two harness commits instead of one.** After the first harness commit
   (`d8402e20`) a descriptive shape control was added (`bba4f2b8`) so a negative result
   could be read, before the registration and before any real row was read. It changed
   no decision input. The registration cites the final blobs, and the artifacts record
   `src/research/k_baseline.py` `ed5a5e6357a057bc5a6d2e12d4941408218fec10` and
   `scripts/k_baseline_compare.py` `b89163b574d957b56d33f75276183b9f9cadfa61`, both the
   registered blobs. No code changed after registration; no run was repeated.
2. **A sealed-window slip, disclosed in the registration (section 0) and carried on its
   registry row (`sealed_untouched: false`).** An inspection command printed the tail of
   `pitcher_logs.jsonl`, which put four of that file's last rows on screen, two of them
   (relief outings of one pitcher, 2026-08-12 and 2026-08-20) inside the sealed
   2026-01-01..2026-08-27 window, plus six 2023 starts from the file's head. Neither was
   a design input: relief rows are used nowhere in this study, and the design was set
   by the task and by conventions, not by any strikeout figure. The harness never keeps
   a row outside 2023-01-01..2024-12-31.
3. **The registration's planning arithmetic for the detectable effect was off by about
   three times** (corrected above; the rule is unaffected).
4. **Verification beyond the tests.** A separate brute-force path (league pool, the
   pitcher's own earlier starts and both models recomputed by linear scans with `date <`
   straight from the raw log, not through the harness) matched **400 random starts per
   season on all four lines and the prior-start count, with 0 mismatches**. Two
   further checks guarded against a leak, since an effect this large is a surprise worth
   suspecting: shuffling the candidate's probabilities across starts within a date
   reverses the gain to -0.051 (2023) and -0.035 (2024), the same size with the opposite
   sign, so the gain is carried by pitcher-specific information and not by a level or
   date artifact; and the candidate's expected strikeouts correlates 0.39 (2023) and 0.34
   (2024) with the actual count: a moderate figure, not the near-1 that a leak of the
   target would give. The checker was a
   scratch script and is not committed.
5. **Poisson, not binomial,** was chosen before any outcome and stated with its reason in
   the registration; the shape control shows it cost at most 0.003 nats.
6. **A transient test run.** A `scripts/test_fast.sh` run was started by mistake while
   iterating and stopped before it finished; no full suite was run.

## What it would take before any strikeout number is shown to customers

This result authorizes nothing; showing a strikeout probability is a separate promotion
decision, and this study clears only its first and easiest condition (the model knows
more than the league does). Before any customer sees a strikeout number the work would
have to include: a **market benchmark** (the model must beat the de-vigged closing
probability of a posted line on the same starts, not a league baseline, which needs the
priced strikeout lines, which exist only from 2026, so anything before 2026-08-28 also
needs an owner decision on D1); a **hindsight-free forward test** on announced
probables with timestamps, on a pre-registered sample large enough for the minimum
detectable effect measured here (about 0.011 nats per start on one line); the
**missing inputs** the market certainly uses (the opposing lineup's strikeout rate, the
park, rest and pitch-count limits, role and bullpen usage) and a distribution that models
batters-faced variance instead of a Poisson at a point estimate; **calibration at the
tails**, where the candidate over-predicted in the thin low bins; the full
**falsification battery** and the registry-wide `0.05 / N` family bar, then the repo's
promotion gate and the owner's rulings on what may appear on a public card (no -200 or
worse prices, nothing advertised that the product cannot stand behind).

## Registry

`K_BASELINE:pitcher_specific_vs_league_k_distribution:pitcher_strikeouts` receives
verdict `candidate` (2024 4.5-line effect +0.03517, interval [+0.02773, +0.04257]; the
5.5 line and the other two are in the verdict note). `total_searched()` after the
verdict: 49 registered hypotheses, 1 sweep (8,811 internal candidates), 2 audits; 42
read, 10 not read; on `market = "pitcher_strikeouts"`: 1 hypothesis (this one, four lines).
