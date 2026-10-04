# Pre-registration: does a pitcher-specific strikeout distribution beat a league-rate baseline?

**Rule id:** `K_BASELINE_V1`
**Registry id:** `K_BASELINE:pitcher_specific_vs_league_k_distribution:pitcher_strikeouts`
**Family:** `K_BASELINE` (one candidate, four lines; the verdict rides on two of them, see section 8)
**REGISTERED_UTC:** the committer time of the commit that adds this file (read it
with `git log --format=%cI -- docs/PREREG_K_BASELINE.md`). It is not written inside
the file because a file cannot contain the time of the commit that adds it. The
registry row is appended in the same commit; its `note` carries the sha256 of this
file with line endings normalised to LF. **Freeze check:** recompute that sha256 and
compare it to the note before reading any result. A mismatch voids the
registration and everything computed from it.

**Status: PAPER COMPARISON OF FORECAST QUALITY. It changes no live number, shows
nothing to a customer and licenses no promotion.** Nothing here involves a price.

---

## 0. What exists before this registration, stated so a reader can check it

- **The harness** was committed first, alone, in two commits:
  `d8402e20c19d6ee9b47191c75b48542a9c05d314` (2026-10-04T08:24:52-07:00) and
  `bba4f2b870b6d05e0366159d05ade9a41d1735f7` (2026-10-04T08:26:02-07:00, which only
  adds a descriptive shape control, section 9, and changes no decision input).
  Final blobs: `src/research/k_baseline.py` `ed5a5e6357a057bc5a6d2e12d4941408218fec10`,
  `scripts/k_baseline_compare.py` `b89163b574d957b56d33f75276183b9f9cadfa61`,
  `tests/test_k_baseline_compare.py` `3b92350273decc6dbcd3ed0b9d67c0c8184b1417`.
- **It was built and tested on synthetic rows only.** Every row in the 53 tests is
  built in the test file. The script has not been run on `pitcher_logs.jsonl`: no
  strikeout probability has been computed on a real start, no log loss, no interval.
- **What was looked at while designing it, disclosed in full.** Structure and
  coverage counts only, for 2023-24 rows of `data/historical/pitcher_logs.jsonl`:
  the field names (one field set across all rows), the in-window row count per season
  (8,888 in 2023; 7,837 in 2024), the `games_started` value counts per season (only
  0 and 1 occur: 4,858 and 4,857 rows with `games_started = 1`; 4,030 and 2,980
  with 0), the types of `strikeouts` and `batters_faced` (always integer, never
  missing), the two duplicated (person, date) pairs, and the first and last
  in-window dates against `mlb_results.csv`'s regular-season dates (no postseason
  date is present in the log). **No aggregate of `strikeouts` or `batters_faced` was
  computed.**
- **Two disclosed slips, neither used.** (a) While checking the file's shape the
  first six lines of the file were printed: six 2023 starts of one pitcher
  (person 425794, 2023-05-06 to 2023-06-05) with their strikeout and batters-faced
  values. (b) The last four lines of the file were printed too, and the file is not
  date-ordered: they are four relief outings of one pitcher (person 837227) dated
  2026-08-12, 2026-08-20 and 2026-09-01, plus one earlier row. **Two of those rows
  (2026-08-12 and 2026-08-20) fall inside the sealed 2026-01-01..2026-08-27
  window.** That was an error of the inspection command (`tail -c` on a mixed-year
  file), not a design input: both were relief rows, which this study never uses, and
  nothing in this document was set by them. It is recorded here and in the report
  back so the seal is not described as intact when it was touched. No sealed row was
  otherwise read, and the harness drops every row outside 2023-01-01..2024-12-31 on
  read.
- Rows dated 2025 or 2026 are never kept, counted, aggregated or printed by the
  harness, and the harness refuses any 2025 or 2026 date with `SealedDataError`.

## 1. Evidence rules this registration obeys

- 2023 and 2024 regular seasons only. **2025 is tuning-only. 2026-01-01..2026-08-27
  is sealed.** A run for 2023 reads no 2024 row into any prediction; a run for 2024
  reads 2023 only as the prior-season pool of section 4.
- Pre-registration before inference. Two models, fixed below. No tuning of any
  constant, no second specification after a result.
- Every loser is published. A null or a loss is a valid, publishable result.
- Line shopping, price and return are out of scope (section 11). **No claim about
  betting return is made or implied.**

## 2. Hypothesis, fixed

> Predicting a starter's strikeout count from his own earlier same-season starts
> (strikeouts per batter faced and batters faced, each shrunk toward the league)
> **lowers the paired log loss** of the probability of Over at 4.5 and at 5.5
> strikeouts, against giving every start the league distribution built from earlier
> starts.

Direction is fixed in advance: lower loss with the pitcher-specific candidate. A
result in the other direction is reported as `WORSE` and is a finding.

## 3. The two models, exactly

**Population of starts.** A **start** is a `pitcher_logs.jsonl` row with
`games_started == 1`. Every other in-window row is a relief outing and is used
nowhere (not as a target, not as history, not in the league pool). Starts are
**not** dropped for being short: a one-inning opener with `games_started == 1` is a
start, scored in both models; the artifact counts starts of 12 batters faced or
fewer so a reader can see how many there are, and reports a descriptive subset
without them. A (person, date) with more than one start row is ambiguous and all its
rows are dropped from target and history alike. A start with a missing, negative or
impossible (`strikeouts > batters_faced`) figure is excluded and feeds no history.
Each of these is counted by cause.

**League pool** (shared by both models, so they share every league input). For a
start on date D of season S it is the set of starts of season S dated strictly
before D **once at least `MIN_LEAGUE_STARTS = 500` such starts exist**. Before that,
it is the whole of season S-1's starts **if S-1 is inside 2023-2024 and has at least
500 starts**; this is the "prior season before enough exist" rule, and the switch
is by date, all starts of one date using the same pool. For 2023 there is no
in-window prior season, so 2023 starts before the 500th earlier league start are
excluded from both models (`excluded_no_league_pool`). For 2024 the prior-season
pool is all of 2023. This asymmetry is a consequence of the evidence window, not a
choice, and 2023 loses its first weeks while 2024 does not.

**Baseline.** Every start gets the league distribution: the empirical share of
pool starts with strictly more than `L` strikeouts is `P(Over L)`, for
`L` in 3.5, 4.5, 5.5, 6.5. Expected strikeouts is the pool's mean strikeouts per
start. Nothing depends on the pitcher. No smoothing; the clip of section 5 applies.

**Candidate.** With the pitcher's own earlier **same-season starts** (strictly before
D; no cross-season carry; relief outings excluded): `n` starts, `K` strikeouts,
`BF` batters faced, and the pool's strikeouts per batter faced `r0` and mean batters
faced per start `b0`:

- rate = `(K + 70 * r0) / (BF + 70)` (fixed prior weight **70 batters faced**),
- expected batters faced = `(BF + 3 * b0) / (n + 3)` (fixed prior weight **3 starts**),
- mean = rate x expected batters faced; strikeouts ~ **Poisson(mean)**;
  `P(Over L) = 1 - P(K <= floor(L))`. Expected strikeouts is the mean.

**Why Poisson, not binomial.** Batters faced varies a good deal from start to start
and a mixture of binomials over a varying number of trials is overdispersed relative
to one binomial; Poisson (variance equal to the mean) is wider than binomial
(n, p) at a strikeout rate near 0.22 and so is the closer of the two to the true
spread. It also avoids rounding the expected batters faced to an integer, which
would distort the mean the MAE is scored on. This is a reason of principle, stated
before any outcome was read; neither distribution was fitted.

**The two models differ only as specified.** They share the same pool, the same
starts, the same exclusions and the same row. A start with no usable pool or no
earlier own start (`MIN_PRIOR_STARTS = 1`) is excluded from **both** because both
predictions live in one row. An excluded start still counts as a start that
happened: it feeds the league pool and, for his next start, the pitcher's history.

The constants 70, 3, 500 and 1 are fixed here. They are conventions (a
strikeout-rate stabilisation scale of roughly 70 batters faced, three starts,
about two weeks of league starts, one prior start), not fitted values, and none was
tuned or checked against an outcome.

## 4. The unit and the walk

One row per start. Starts are walked in date order; a date's starts join the league
pool and the pitchers' histories only **after every start of that date has been
predicted**, so a doubleheader or any same-day start never feeds another. Every date
that enters is passed through `assert_allowed_date`. The four lines are reported
separately and are **not independent observations**: they are four views of one
strikeout count per start.

## 5. Metric and sign convention, fixed

Per-line log loss in nats with probabilities clipped to `[1e-6, 1 - 1e-6]`
(identical for both models). **`d = loss(BASELINE) - loss(CANDIDATE)` per start.
Positive `d` means the pitcher-specific candidate predicted better.** The statistic
is the mean of `d`. Expected-strikeout error: `d_mae = |K - E_baseline| - |K -
E_candidate|`, same sign, mean of it; it is reported with its interval and decides
nothing.

## 6. Interval, fixed

A date-clustered bootstrap of the mean of `d`: dates resampled with replacement (all
of a date's starts move together), **2,000 resamples, seed `20261004`**, dates sorted
ascending, 95% percentile interval from the `int(0.025 N)` and `int(0.975 N)` order
statistics. Same algorithm as `src.model.discovery.clustered_bootstrap`; a test pins
the two to the same numbers.

## 7. Decision rule, fixed

2023 is the first look. 2024 is the confirming season. **Lines 4.5 and 5.5 decide.**

- **SUPPORTED** only if, on **both** the 4.5 and the 5.5 line, the 95% interval of
  mean `d` on **2024** lies entirely above zero **and** the **2023 point estimate**
  of mean `d` on that line is positive.
- **WORSE** if on **both** lines the 2024 interval lies entirely below zero.
- **NOT SUPPORTED** otherwise: one line clears and the other does not, an interval
  touches zero, a 2023 estimate is zero or negative, any interval cannot be computed.
  The result document says in which direction the numbers fell.

Implemented as `src.research.k_baseline.decide`, applied literally; there is no
threshold to move and no effect-size floor. The 3.5 and 6.5 lines, the MAE, and
every table in section 9 are published and **cannot change, rescue or veto the
verdict**.

**Multiplicity.** One candidate, four lines (`candidates_evaluated = 4` on the
registry row). The verdict is an intersection rule over two pre-designated tests,
both of which must pass, so no BH or Bonferroni adjustment is applied to it. The
intervals are 95% intervals, **not** the registry-wide `0.05 / N` family-wise bar, and
a `SUPPORTED` here would not meet that stricter bar; the result document says so.

## 8. What size of effect the sample can detect

Stated now as a formula and a planning illustration (not data); the measured value is
reported with the result.

- **Reported with the result:** the observed bootstrap standard error of mean `d`
  (half-width / 1.96) per line and season, and the **minimum detectable effect at
  roughly 80% power, two-sided 5%: about 2.8 times that standard error**.
- **Planning arithmetic.** If the candidate moved a probability by a systematic
  `delta` in the right direction on an event of probability `p`, the expected gain per
  start is about `delta^2 / (2 p (1 - p))` and the per-start standard deviation of `d`
  about `delta / sqrt(p (1 - p))`. For the 4.5 and 5.5 lines `p` is likely near 0.5, so
  the gain is about `2 delta^2` and the standard error about `2 delta / sqrt(n)`;
  setting the gain equal to 2.8 standard errors gives `delta` of about `2.8 / sqrt(n)`.
  With roughly 4,000-4,500 scored starts per season (an estimate from the 4,858 and
  4,857 start rows less the exclusions above, **not a computed count**) that is a
  systematic shift of **about four percentage points in the Over probability, a gain
  near 0.004 nats per start**. Smaller true gains, or shifts under about three
  points, would read as a null whether or not they exist. Starters differ in
  strikeout talent by far more than that, so a real pitcher-specific signal is
  expected to be visible; a null here would say that **this simple candidate** adds
  less than about that much over the league baseline, not that pitcher skill does
  not matter.

## 9. Descriptive only, no decision rides on them

Published for both seasons whatever they show:

- All four lines: base rate, mean predicted probability, log loss, Brier score and a
  ten-bin reliability table for both models; the paired `d` interval, standard error
  and minimum detectable effect.
- **Expected-strikeout MAE**, both models, and the paired `d_mae` interval.
- **Shape control.** Poisson at the league mean with no pitcher information (equal to
  the candidate with an empty history). The baseline is empirical and the candidate is
  Poisson, so a gap between them mixes pitcher information with distribution shape.
  `d_shape = loss(BASELINE) - loss(CONTROL)` is the effect of the shape alone;
  `d_info = loss(CONTROL) - loss(CANDIDATE)` is the effect of the pitcher's history
  with the shape held fixed; they sum to `d`. Reported with intervals per line and
  season. It cannot change the verdict.
- The subset of starts by pitchers with at least 5 earlier starts, and the subset
  excluding starts of 12 batters faced or fewer.
- Starts excluded by cause, scored by pool source (same season or prior season),
  short starts scored.

## 10. Disclosed limits, written before any result

1. **No price, no opponent, no lineup.** The comparison is of two distributions of one
   count. It ignores who the starter faces, the lineup, the park, the umpire, the
   weather, rest, pitch count and velocity, and any injury or role information.
2. **No betting-return claim is possible.** There are no historical strikeout prices
   before 2026 and 2026 inputs before 2026-08-28 are sealed. A better log loss against
   the outcome is not a better bet: the book prices the same facts.
3. **Starter identity needs no probable-pitcher field here**: the unit is a start that
   happened, taken from the pitcher log itself. The hindsight limit of the total-bases
   study does not apply, but a live board would have to know the starter in advance,
   which this study does not test.
4. **Batters faced is treated as a property of the pitcher.** In reality it depends on
   the game, the leash and the bullpen; the Poisson with a point-estimate mean ignores
   that variance except through the Poisson spread.
5. **Shape and information are confounded in the registered contrast** (section 9
   separates them descriptively); a candidate that loses to the baseline might lose on
   shape alone.
6. **Early season.** Pitchers with no earlier start that season are excluded, and in
   2023 so are the first weeks (no prior-season pool). The population is therefore
   not "every start" and under-represents April.
7. **The pitcher log holds only pitchers who were listed as a probable at some point.**
   A start by anyone missing from the log is absent; the log has 4,858 and 4,857
   starts against roughly 4,860 and 4,858 regular-season team games, so the loss looks
   tiny but is unmeasured here.
8. **One seed, one run per season.** The script refuses to overwrite an artifact.

## 11. Out of scope, with the reason

Price and return on 2026 posted strikeout lines are **NOT RUN**: feeding a 2026
starter needs pitcher-log rows dated inside the sealed 2026-01-01..2026-08-27 window
as model inputs, which is the open owner decision D1 in
`docs/PREREG_PROP_FAMILIES_DRAFT.md`. Nothing here reads a 2026 row.

## 12. What a result can and cannot say

- `SUPPORTED`: on 2023-24 data this candidate lowered the log loss of the 4.5 and 5.5
  Over probabilities against the league baseline in both seasons by the registered
  rule. It says nothing about price, opponent, 2025-26 or a live board; it meets only
  the 95% bar; it authorizes nothing and at most supports **asking** for the separate
  promotion process, which has its own falsification battery.
- `NOT SUPPORTED`: no demonstrated improvement within the power of section 8.
- `WORSE`: the candidate as written degrades the probability; it is not a candidate as
  written.

## 13. Budget, and the registry

One candidate, four lines. The row is registered through
`src.research.alpha_registry.register()` before any run (`kind: hypothesis`,
`family: K_BASELINE`, `market: pitcher_strikeouts`, `sport: mlb`,
`data_window: {discovery: "2023", replication: "2024", sealed_untouched: false}`,
`candidates_evaluated: 4`, `alpha_declared: 0.05`). `sealed_untouched` is **false**
because of the disclosed slip in section 0: two sealed relief rows were printed. A
verdict is appended through `record_verdict()` after the 2024 read.

**Searched before this registration** (`total_searched()` on this checkout, read
immediately before the row was written): 48 registered hypotheses, 1 sweep (8,811
internal candidates), 2 audits; 41 read, 10 not read. On `market =
"pitcher_strikeouts"`: **0 hypotheses, 0 sweeps, 0 audits**. On `data_window =
"2023"`: 11 hypotheses, 0 sweeps, 1 audit. The count after registration is 49
hypotheses; it is updated again in the result document.

## 14. Procedure

1. Run 2023, then 2024 (`python scripts/k_baseline_compare.py --season 2023`, then
   `2024`). Artifacts: `data/research/k_baseline/k_baseline_{2023,2024}.json`.
2. Apply the rule (`python scripts/k_baseline_compare.py --verdict`), write
   `docs/research/K_BASELINE_RESULT.md` and append the verdict.
3. A defect found after this commit that changes a number is fixed in a separately
   disclosed commit, never silently, and a run already completed is not repeated
   unless the defect corrupted it (a crash or a wrong join), never because of what it
   showed. No parameter, population or rule in this document may be edited after this
   commit; a different specification is a new registration.
