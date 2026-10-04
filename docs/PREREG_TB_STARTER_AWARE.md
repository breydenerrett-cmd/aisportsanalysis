# Pre-registration: does feeding the opposing starter improve the batter total-bases model?

**Rule id:** `TB_STARTER_AWARE_V1`
**Registry id:** `TB_STARTER:starter_aware_total_bases:batter_total_bases`
**Family:** `TB_STARTER` (one candidate, two events; family size for any correction is 2)
**REGISTERED_UTC:** the committer time of the commit that adds this file (read it
with `git log --format=%cI -- docs/PREREG_TB_STARTER_AWARE.md`). It is not written
inside the file because a file cannot contain the time of the commit that adds it.
The registry row is appended in the same commit; its `registered_utc` is the
moment it was written, minutes before that commit, and its `note` carries the
sha256 of this file with line endings normalised to LF (Windows checkouts may
rewrite them to CRLF). **Freeze check:** recompute that sha256 and compare it to
that note before reading any result. A mismatch voids the
registration and everything computed from it.

**Status: PAPER COMPARISON. It changes no live number and licenses no promotion.**
Nothing here is on a customer surface. A `SUPPORTED` verdict would mean only
"this is worth asking the separate promotion process about" (section 12).

---

## 0. What exists before this registration, stated so a reader can check it

- **The harness** was committed first, alone, at commit
  `e782360abd824553b75e6e30bb341ae454b06df0` (2026-10-04T00:51:59Z):
  `src/research/tb_starter.py` (git blob `3180a6cab6312c2adad8ca85ef0a43c2466af651`),
  `scripts/tb_starter_compare.py` (`5306b1cfad910e108aa412cbb5de5a841557e779`),
  `tests/test_tb_starter_compare.py` (`932f990e11d1a428efab39ad8c2940d4081fb5b9`).
  The model it calls, `src/analysis/playerprops.py`, is untouched (blob
  `6478e41071b50b80e7a91ca74f2f930e297b4a2d`).
- **It was built and tested on synthetic rows only.** The 43 tests construct every
  row in the test file. The script has not been run against the 2023 or 2024
  stores: no probability has been priced on a real batter-game, no log loss has
  been computed, no interval exists.
- **What was looked at while designing it, disclosed in full.** Row structure and
  counts only: the box-score archive's row types and field names for 2023 (73,878
  rows; 50,793 batter rows; 1,991 batter rows with `pa = 0`; no duplicated
  `(game_pk, player_id)`), the first few 2023 rows of the archive (three pitcher rows
  and one batter line were printed while checking field names), the lineup file's
  shape and counts for 2023-24 (4,868 in-window rows, nine games with two lineup rows,
  every lineup has nine distinct slots), `mlb_results.csv`'s `game_type` counts, its
  doubleheader flags and the number of missing probable ids for 2023-24, and the
  pitcher-log field set, row count (16,725 in-window rows, 514 pitchers) and the
  two duplicated pitcher-date pairs. **No aggregate of `h`, `total_bases`, `hr`,
  `doubles` or any other outcome-bearing field was computed.** Nothing in this
  document was set by a result.
- Rows dated 2025 or 2026 in `pitcher_logs.jsonl`, `lineups.jsonl` and
  `mlb_results.csv` were dropped on read and never counted, aggregated or printed.
  The 2025 box-score archive was never opened. The harness refuses any 2025 or
  2026 date with `SealedDataError`, and builds a box-score path only after the
  season has passed that guard.

## 1. Evidence rules this registration obeys

- 2023 and 2024 regular seasons only (`src/research/matrix.ALLOWED_SEASONS`).
  **2025 is tuning-only. 2026-01-01..2026-08-27 is sealed.**
- Pre-registration before inference. One candidate, as coded; no tuning of
  `STARTER_SHARE` (0.62), `BF_REGRESSION` (300), the bounds (0.80, 1.25), the
  clip, the bootstrap or anything else; no second specification after a result.
- Every loser is published. A null or a loss is a valid, publishable result.
- Zero survivors is a valid result. Nothing here is manufactured toward a yes.
- Line shopping, price and return are out of scope (section 11).

## 2. Hypothesis, fixed

> Feeding the listed opposing starter's same-season hits allowed and batters
> faced, strictly before the game, **lowers the paired log loss** of the model's
> probability that a batter records **2 or more total bases** (primary) and
> **1 or more** (secondary), against the same model with no starter fed.

Direction is fixed in advance: lower loss with the starter. A result in the other
direction is reported as `WORSE` and is a finding, not a failed test.

## 3. The two arms, exactly

Both arms call `src.analysis.playerprops.price_prop(market="batter_total_bases", ...)`
unmodified, with the same `batter_lines`, `league`, `batting_slot` and `slot_table`.

| arm | extra arguments |
|---|---|
| WITHOUT | none (what the product computes today) |
| WITH | `pitcher_hits_allowed=H`, `pitcher_batters_faced=BF` |

- **Lines:** `line=1.5` for the primary event (P of 2 or more total bases) and
  `line=0.5` for the secondary (P of 1 or more).
- **`H`, `BF`:** the opposing starter's summed `hits` and `batters_faced` over
  his rows in `data/historical/pitcher_logs.jsonl` dated **strictly before the game
  date and in the same calendar year**. All his appearances count, starts and
  relief alike. A missing `hits` or `batters_faced` row is skipped, never zero
  filled. If he has no usable row (or the sum of `BF` is zero) the starter is
  **unknown** and the WITH arm is called with no starter arguments, which is the
  identical call to WITHOUT.
- **Inside the model, unchanged:** `pitcher_hit_factor`, regressed with
  `BF_REGRESSION = 300` toward the league hit rate, bounded to 0.80-1.25, blended
  as `STARTER_SHARE * factor + (1 - STARTER_SHARE)`, applied to the four per-PA hit
  buckets. Nothing is passed or changed.
- **Expected plate appearances, identical in both arms:** the batter's posted slot
  from `data/historical/lineups.jsonl` through the **frozen slot table**
  (`data/processed/card_v2_frozen_params.json`, `slot_plate_appearances`, **fit on
  2025**) when the slot is known; otherwise `price_prop`'s own fallback to the
  batter's season average. **That table was fit on 2025 and is used here because
  it is the card's frozen constant; it applies to both arms equally and so cannot
  favour either.** It is not a 2023-24 quantity and no 2023-24 outcome touched it.
- `rho` is not passed: the total-bases market is not rho-corrected inside
  `probability_over`, so it is moot for this event.
- **League rates:** `playerprops.league_rates` over every regular-season batter
  box row of the season dated strictly before the game date (rows with `pa = 0`
  contribute zero plate appearances and are included).
- **No cross-season carry.** A 2024 batter's prior lines are 2024 lines; his 2023
  games are not used, and the 2023 and 2024 runs share no state. Early-season rows
  are therefore often below the 40-PA floor and are excluded (section 4).

## 4. Population and exclusions, fixed

**Unit:** one row per batter per game, from the box-score archive's `type == "batter"`
rows (`data/archive/historical/boxscores/boxscores_{2023,2024}.jsonl.gz`, whose
sha256 is checked against `data/archive/historical/SHA256SUMS` before use; the
`data/processed/boxscores_*.jsonl` copies are untracked and absent from a checkout,
so the tracked, checksummed archive is the source). Games are regular season
(`game_type == "R"` in `mlb_results.csv`, matched on `game_pk`, same date).

This is the repo's own backtest convention
(`scripts/backtest_player_props.py`): a batter is in the population if he has a box
row, so it includes bench batters with `pa = 0`. That is a selection on appearing in
the game; it is identical in both arms and cannot bias the paired difference in
expectation, but it is a population a live board would not price. The
posted-lineup subset (`slot` known) is reported as a descriptive row (section 9).

**The starter** is the opposing club's `*_probable_id`: `home_probable_id` for an
away batter, `away_probable_id` for a home batter. The side comes from the box row
and must agree with the result row's team id (otherwise the row is excluded).

**Exclusions, each counted by cause in the artifact and published** (a row is
excluded from BOTH arms, never one):

| artifact key | cause |
|---|---|
| `excluded_wrong_season_date` | box row dated outside the run's season or outside 2023-01-01..2024-12-31 |
| `excluded_not_regular_season_or_unmatched_game` | `game_pk` absent from results, or `game_type != "R"` |
| `excluded_result_date_mismatch` | box date differs from the result row's date |
| `excluded_duplicate_batter_game` | a second row for the same `(game_pk, player_id)` |
| `excluded_side_team_mismatch` | box `side`/`team_id` disagree with the result row |
| `excluded_no_outcome` | `total_bases` missing |
| `excluded_no_league_history` | the season's first date (no prior plate appearance) |
| `excluded_no_rate` | `price_prop` raises `PropError`: below the 40-PA floor (cause named) |

**Stays in both arms, flagged:** a batter-game with no usable starter (no
probable id, or no logged appearance that season before the date). The arms are
identical there. The artifact reports `starter_known` / `starter_unknown` counts
and the cause, and every summary is also given for the **starter-known subset**.

**A starter-unknown row contributes exactly 0 to the paired difference.** The
primary population therefore dilutes any effect by the starter-known share; the
starter-known subset is the undiluted size of the effect. The decision rule below
is on the full population, as asked.

## 5. Metric and sign convention, fixed

Per-event log loss in nats with probabilities clipped to `[1e-6, 1 - 1e-6]`
(identical for both arms; the convention of `scripts/prereg_market_vs_model.py`).

**`d = loss(WITHOUT) - loss(WITH)` per batter-game.** **Positive `d` means the
starter-aware arm predicted better.** The statistic is the mean of `d`.

## 6. Interval, fixed

A date-clustered bootstrap of the mean of `d`: dates resampled with replacement
(all of a date's rows move together), **2,000 resamples, seed `20261003`**,
dates sorted ascending, 95% percentile interval from the `int(0.025 N)` and
`int(0.975 N)` order statistics. Same algorithm as
`src.model.discovery.clustered_bootstrap`; a test pins the two to the same numbers.

## 7. Decision rule, fixed

2023 is the first look. 2024 is the confirming season. **Primary event only
decides.**

- **SUPPORTED** only if the 95% interval of mean `d` on **2024** lies entirely above
  zero **and** the **2023 point estimate** of mean `d` is positive.
- **WORSE** if the 2024 interval lies entirely below zero.
- **NOT SUPPORTED** otherwise, including: the 2024 interval includes or touches zero;
  the 2024 interval is above zero but the 2023 estimate is zero or negative; any
  interval cannot be computed.

The rule is implemented as `src.research.tb_starter.decide` and applied literally.
There is no threshold to move, no effect-size floor, and no second look.

**The secondary event** (1 or more total bases) has the same rule computed and
published, labelled SECONDARY. **It cannot change the verdict** and cannot rescue
a primary that is `NOT SUPPORTED` or `WORSE`; a secondary `SUPPORTED` beside a
primary `NOT SUPPORTED` is reported as exactly that and licenses nothing.

**Multiplicity.** One candidate, two events (`candidates_evaluated = 2` on the
registry row; `total_searched()` counts the row as one hypothesis while the true
family size is 2, read this note and not the count). The verdict rides on the
primary alone, a single pre-designated test, so no BH or Bonferroni adjustment is
applied to it and the secondary is subordinate. **Stated plainly:** the interval
here is the 95% interval the task asked for, **not** the registry-wide
`0.05 / N` family-wise bar that `docs/PREREG_SLOT_PROP.md` holds itself to. A
`SUPPORTED` here would therefore not meet that stricter bar, and the result
document will say so.

## 8. What size of effect the sample can detect

Stated now as a formula and a planning illustration; the measured value is
reported with the result.

- **Reported with the result:** the observed standard error of mean `d`
  (bootstrap half-width / 1.96), and the **minimum detectable effect at roughly 80%
  power, two-sided 5%: about 2.8 times that standard error**, for the full
  population and for the starter-known subset, for each season.
- **Planning arithmetic, assumptions labelled (not data).** If the starter moved a
  probability by a systematic `delta` on an event of probability `p`, the expected
  gain per row from adding it correctly is about `delta^2 / (2 p (1 - p))`, and the
  per-row standard deviation of `d` is about `delta / sqrt(p (1 - p))`. For an
  illustrative `p = 0.25` and `delta = 0.01` that is a gain near 0.0003 nats against a
  per-row SD near 0.023; over tens of thousands of rows per season the standard
  error is about 0.0001. So **a systematic one-point probability shift is about the
  smallest effect this instrument can see; a true gain below roughly 0.0003 nats
  per row, or a shift much under a point, would read as a null whether or not it
  exists.** A null here is "no effect larger than about that", not "no effect".
  Because starter-unknown rows contribute zero, the full-population mean is the
  starter-known effect scaled by the known share.

## 9. Descriptive only, no decision rides on them

Reported for both arms, both seasons, both events, and published whatever they show:

- Brier score and a ten-bin reliability table (`src.core.calibration.reliability_curve`).
- The distribution of the starter factor (min, quantiles, max, share at each bound).
- The share of batter-games whose probability moves by more than one point
  (`|p_with - p_without| > 0.01`), and the mean absolute move.
- The mean paired difference by **starter-factor tercile** (equal-count terciles of
  starter-known rows by the factor, ties broken by date, game, player).
- The starter-known subset's paired difference and interval.
- The posted-lineup subset's (`slot` known) paired difference and interval, to show
  the result is not an artefact of bench rows.
- Exclusion counts, starter-unknown counts by cause, slot-known counts.

## 10. Disclosed limits, written before any result

1. **Starter identity carries hindsight.** `*_probable_id` is the starter at first
   pitch, not the pre-game announcement
   (`docs/AUDIT_PROBABLE_PITCHER_PIT.md`: 99.90% / 99.92% equal to who threw the
   first pitch, 2023 / 2024; the stored value cannot be repaired and no announcement
   history exists). Only WHO the starter is has hindsight: the statistics fed are
   strictly pre-game. The audit estimated 2-8% of games carry a scratch the live
   system could not have known; that estimate is unmeasured. The comparison
   therefore slightly **favours** the WITH arm relative to a live board, never the
   other way, and a `SUPPORTED` would be an upper bound on a live effect.
2. **The lineup slot is retroactive** (`lineups.jsonl`, `observed_utc` is a
   2026 backfill timestamp). It is identical in both arms.
3. **The model's known simplifications stand:** no park factor, no platoon split,
   i.i.d. plate appearances, a fixed `STARTER_SHARE` that ignores the starter's
   actual workload. A null does not say a better-specified starter model would
   fail; it says the one written does not help.
4. **Doubleheaders are handled conservatively:** "strictly before" is by date, so
   the first game of a doubleheader never feeds the second, for batter, league and
   starter alike.
5. **Early season:** starters with no prior appearance that season are unknown, and
   the factor is shrunk toward 1 by the 300-batter regression, so the effect is
   concentrated in the middle and late season.
6. **Pitcher logs hold only pitchers who were listed as a probable at some point;**
   a starter missing from the log is unknown, counted, and identical in both arms.
7. **One seed, one run per season.** The script refuses to overwrite an artifact.

## 11. Out of scope, with the reason: price and return on the 2026 priced lines

Whether a starter-aware probability would have found value against a 2026
posted line is **NOT RUN**. Feeding a 2026 starter needs that starter's pitcher-log
rows dated inside the sealed 2026-01-01..2026-08-27 window as model inputs, which is
open owner decision **D1** in `docs/PREREG_PROP_FAMILIES_DRAFT.md` (adopt the
disclosed dependence of `docs/PREREG_CARD_V2.md` section 1.2, or restrict inputs to
2025 plus 2026-08-28 onward). Until the owner decides it, nothing here reads a 2026
row. This is a comparison of target prediction (log loss against what happened),
not of price: a better probability is not a better bet, because the book may price
the same fact.

## 12. What a result can and cannot say

- `SUPPORTED`: on 2023-24 data, feeding the listed starter lowered the model's log
  loss on the primary event in both seasons by the registered rule. It does not say
  the effect survives hindsight-free starters (limit 1), the 2025-26 seasons, or
  the market; it meets only the 95% bar (section 7); and it authorizes nothing. At
  most it supports **asking** for the separate promotion process, which has its own
  falsification battery.
- `NOT SUPPORTED`: no demonstrated improvement within the power of section 8. The
  unused adjustment stays unused.
- `WORSE`: the unused adjustment, as written, degrades the probability; the
  result document says so and the adjustment is not a candidate as written.

## 13. Budget, and the registry

One candidate (the unused starter adjustment, as coded), two events. The row is
registered through `src.research.alpha_registry.register()` before any run
(`kind: hypothesis`, `family: TB_STARTER`, `market: batter_total_bases`,
`data_window: {discovery: "2023", replication: "2024", sealed_untouched: true}`,
`candidates_evaluated: 2`, `alpha_declared: 0.05`) and a verdict is appended through
`record_verdict()` after the 2024 read.

**Searched before this registration** (`total_searched()` on this checkout, read
immediately before the row was written): 47 registered hypotheses, 1 sweep (8,811
internal candidates), 2 audits; 40 read, 10 not read. On
`market = "batter_total_bases"`: **0 hypotheses, 0 sweeps, 0 audits** (no prior
registered search on this market). On `data_window = "2023"`: 10 hypotheses, 0
sweeps, 1 audit. The count after registration is 48 hypotheses; it is updated again
in the result document.

## 14. Procedure

1. Time a 1,000-row slice (`--time-slice 1000`, which prints no metric and writes
   nothing). If the full run would exceed an hour, run the pricing in a process pool
   with the identical function; never subsample.
2. Run 2023, then 2024 (`python scripts/tb_starter_compare.py --season 2023`, then
   `2024`). Artifacts: `data/research/tb_starter/tb_starter_{2023,2024}.json`.
3. Write `docs/research/TB_STARTER_AWARE_RESULT.md` and append the verdict.
4. A defect found after this commit that changes a number is fixed in a separately
   disclosed commit, never silently, and a run already completed is not repeated
   unless the defect corrupted it (a crash or a wrong join), never because of what
   it showed. No parameter, population or rule in this document may be edited after
   this commit; a different specification is a new registration.
