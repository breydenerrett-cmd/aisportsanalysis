# Pre-registration: does adjusting the pitcher-specific strikeout forecast for the opposing lineup's strikeout tendency improve it?

**Rule id:** `K_OPPONENT_V1`
**Registry id:** `K_OPPONENT:opponent_k_factor_vs_pitcher_specific:pitcher_strikeouts`
**Family:** `K_OPPONENT` (one candidate, four lines; the verdict rides on two of them, see section 7)
**REGISTERED_UTC:** the committer time of the commit that adds this file (read it
with `git log --format=%cI -- docs/PREREG_K_OPPONENT.md`). It is not written inside
the file because a file cannot contain the time of the commit that adds it. The
registry row is appended in the same commit; its `note` carries the sha256 of this
file with line endings normalised to LF. **Freeze check:** recompute that sha256 and
compare it to the note before reading any result. A mismatch voids the
registration and everything computed from it.

**Status: PAPER COMPARISON OF FORECAST QUALITY. It changes no live number, shows
nothing to a customer and licenses no promotion.** Nothing here involves a price.
This is the next step after `docs/PREREG_K_BASELINE.md` (whose result,
`docs/research/K_BASELINE_RESULT.md`, found the pitcher-specific distribution beat a
league-rate baseline in 2023 and 2024) and uses that registered candidate, unchanged,
as its BASELINE.

---

## 0. What exists before this registration, stated so a reader can check it

- **The harness** was committed first, alone, before this document:
  `src/research/k_opponent.py`, `scripts/k_opponent_compare.py`,
  `tests/test_k_opponent.py`. Commit and blob ids are in section 15 (filled in by the
  registration commit, because a document cannot name the commit that precedes it
  until that commit exists).
- **It was built and tested on synthetic rows only.** No opponent factor has been
  computed on a real start; no log loss, interval or paired difference has been
  computed on real data. The script has not been run.
- **What was looked at while designing it, disclosed in full. Structure and coverage
  counts only**, for 2023-24 rows of `data/historical/bullpen_log.jsonl`,
  `pitcher_logs.jsonl` and `mlb_results.csv`:
  - field names; the in-window row count of `bullpen_log.jsonl` (41,443 including six
    `{date, empty: true}` marker rows with no pitcher data, so 41,437 pitching
    rows); 4,859 distinct `game_pk`, each with exactly two team codes;
  - `mlb_results.csv` holds 4,857 regular-season (`game_type == "R"`) games in the
    window and every one of them is in the bullpen log; the two games in the bullpen
    log that are not in `mlb_results.csv` carry the team codes `AL` and `NL` (the
    All-Star games, 2023-07-11 and 2024-07-16); the bullpen log's date equals the
    results date for every shared game;
  - **nine games appear under two different dates** in the bullpen log (the same box
    score duplicated, 94 duplicated `(game_pk, person_id)` pairs, 4 starting pitchers
    in those games); these are excluded wholesale (section 3);
  - all 9,715 in-window start rows of `pitcher_logs.jsonl`: 9,711 match exactly one
    `started` row of the bullpen log on `(person_id, date)` and all 9,711 agree with
    it on strikeouts and batters faced; 4 do not match any row (all dated 2024-03-20
    or 2024-03-21); in the 4,850 other regular games each team has exactly one
    starter;
  - `strikeouts` and `batters_faced` are integers on every pitching row.
  **No aggregate of `strikeouts` or `batters_faced` was computed, no team or league
  strikeout rate was computed, and nothing was compared with an outcome.**
- **Disclosed slips, none used as a design input.** (a) A `head -c` of
  `bullpen_log.jsonl` (a file that mixes 2023-24 with later rows) printed three
  rows of one **2026-03-26** game (one starter and two relievers of one team: name,
  strikeouts, batters faced); 2026-03-26 is **inside the sealed 2026-01-01..2026-08-27
  window**. (b) A `head -c` of `matchup_history.jsonl` (all of whose rows are outside
  2023-24) printed the opening of one record, a batter list for one away team, with no
  date visible; it may be a sealed-window row. (c) `head -c` of `lineups.jsonl` and
  `standings.jsonl` printed one record each dated 2026-09-08/09, after the seal
  window. Nothing in this document was set by any of them: constants were chosen
  from the structure of the task (section 3) and baseball convention, not from any
  row. They are recorded here so the seal is not described as intact.
  **`sealed_untouched` is therefore false on the registry row.**
- Rows dated 2025 or 2026 are never kept, counted, aggregated or printed by the
  harness: the streaming reader tests the raw line's `date` text and discards an
  out-of-window line **before parsing it**, and the harness refuses any 2025 or 2026
  date with `SealedDataError` (a test pins both).

## 1. Evidence rules this registration obeys

- 2023 and 2024 regular seasons only. **2025 is tuning-only. 2026-01-01..2026-08-27
  is sealed.** A run for 2023 reads no 2024 row into any prediction; a run for 2024
  reads 2023 only as the prior-season pool (the K_BASELINE rule, section 3).
- Pre-registration before inference. One candidate, one shrinkage constant, one
  bound, fixed below. No tuning, no second specification after a result.
- Every loser is published. A null or a loss is a valid, publishable result.
- Line shopping, price and return are out of scope. **No claim about betting return
  is made or implied.**

## 2. Hypothesis, fixed

> Multiplying a starter's shrunk per-batter strikeout rate by **(the opposing team's
> strikeout rate per plate appearance in its earlier same-season games, shrunk toward
> the league rate, divided by the league rate)** **lowers the paired log loss** of
> the probability of Over at 4.5 and at 5.5 strikeouts, against the same forecast
> without the factor (the registered K_BASELINE candidate).

Direction is fixed in advance: lower loss with the opponent-adjusted candidate. A
result in the other direction is reported as `WORSE` and is a finding.

## 3. The two arms, exactly

**Start population and its two arms.** The population is the K_BASELINE population
(`src.research.k_baseline.extract_starts` over `pitcher_logs.jsonl`, unchanged) and
the BASELINE is `src.research.k_baseline.build_comparison_rows` **called on every
such start, unchanged**: its candidate arm (pitcher-specific Poisson, prior weights
70 batters faced and 3 starts, league pool and early-season rule of
K_BASELINE section 3, `MIN_LEAGUE_STARTS = 500`, `MIN_PRIOR_STARTS = 1`) is this
study's BASELINE, probability for probability. Its rows are scored for one season at
a time exactly as before. A test pins that this study's baseline probabilities equal
the K_BASELINE candidate probabilities on the same starts.

**The one change.** For a scored start on date D by pitcher P against opposing team
T, over the games of T dated **strictly before D in the same season** (this is the
opposing team's *batting* record: in each of its games the strikeouts and batters
faced recorded by the other team's pitchers, all pitchers of that game, starters and
relievers):

- `K_T` = strikeouts, `PA_T` = batters faced (plate appearances) by T's batters,
  summed over those games;
- `r_ref` = the league strikeout rate per plate appearance over the same kind of
  evidence: if the K_BASELINE pool for this date is `same_season`, all regular-season
  games of that season dated strictly before D (all pitchers, both teams); if it is
  `prior_season`, **all** regular-season games of the prior season (2023 for a 2024
  start). In 2023 the pool source is always `same_season` (a 2023 start before the
  500th league start is excluded in both arms, as in K_BASELINE);
- `rate_T = (K_T + 1000 * r_ref) / (PA_T + 1000)`: the opposing team's rate shrunk
  toward the league with a fixed prior weight of **`OPP_PRIOR_PA = 1000` plate
  appearances**;
- `factor = rate_T / r_ref`, **bounded to `[0.85, 1.15]`** (`FACTOR_MIN`,
  `FACTOR_MAX`); outside that range it is set to the bound and counted.

The CANDIDATE is the BASELINE with its per-batter strikeout rate multiplied by that
factor: `mean = baseline_rate * factor * baseline_expected_batters_faced`;
strikeouts ~ **Poisson(mean)**, `P(Over L) = 1 - P(K <= floor(L))`. Expected batters
faced is not changed. With no earlier game for T the factor is exactly 1 (so the two
arms coincide); the arms differ **only** by the factor, a test pins this row by row.

**Why 1000 plate appearances.** A convention fixed from the structure of the problem,
not from any row: a team's strikeout rate is the average of nine batters, so its
true-talent spread is far narrower than a single batter's, while the binomial noise
of its observed rate over N plate appearances is `sqrt(0.225 * 0.775 / N)`. A
weight near 1,000 plate appearances (about 26 team-games at roughly 38 plate
appearances each) is the scale at which that noise and a spread of roughly one
percentage point of true team strikeout rate are of the same size, so the shrunk
rate trusts a team's record roughly half after about 26 games. It was written down
before any comparison was computed and is not a fitted value.

**Why the bound `[0.85, 1.15]`.** A guard rail against a degenerate early-season
estimate or a data fault, not a feature: a team strikeout rate fifteen percent from
the league rate is more than twice any plausible true-talent gap. It is expected to
bind rarely if ever; the result reports how often it binds.

**Rows that cannot be compared.** A start is dropped from **both** arms when it
cannot be given an opposing team from stored data, by cause, each counted:

1. `no_game_match`: the start's `(person_id, date)` matches no `started` row of the
   bullpen log in a regular-season game;
2. `ambiguous_game`: it matches more than one game;
3. `game_excluded_multi_date`: its game is one of the games recorded under two dates
   (excluded wholesale, from the opponent history too, because the date on which the
   complete box score became known is unknowable here);
4. `k_bf_disagree`: the start's strikeouts or batters faced differ from the matching
   bullpen-log row (none expected: 9,711 of 9,711 agreed);
5. `game_excluded_other`: its game failed one of the game checks below (not exactly
   two team codes, a date different from the results date, a duplicated pitcher row,
   or an invalid figure).

A scored start whose opposing team is identified but for which no reference rate
exists is also dropped from both arms and counted (`no_reference_rate`; none expected).

A game enters the opponent history only if it is in `mlb_results.csv` with
`game_type == "R"` (this removes the two All-Star games), has exactly two team codes
and one date, and every pitching row has integer non-negative strikeouts and batters
faced with strikeouts not above batters faced (else the game is excluded and counted).
An excluded start still counts as a start that happened for the K_BASELINE pool and
pitcher history, because the baseline is run on every start, unchanged.

**Coverage, reported with the result.** Starts scored by K_BASELINE (the comparable
base, its 2023 and 2024 counts), starts excluded here by each cause above, starts
scored here, games used and excluded from the opponent history, the share of scored
starts whose factor is exactly 1, and the share bounded.

## 4. The unit and the walk

One row per start. Starts are walked in date order; **a date's games and starts
join the opponent history and the league record only after every start of that date
has been predicted**, so neither a doubleheader's first game nor any same-day box
score feeds a same-day start. The four lines are reported separately and are **not
independent observations**: they are four views of one strikeout count per start.
Every date that enters passes `assert_allowed_date`.

## 5. Metric and sign convention, fixed

Per-line log loss in nats with probabilities clipped to `[1e-6, 1 - 1e-6]`
(identical to K_BASELINE, same code). **`d = loss(BASELINE) - loss(CANDIDATE)` per
start. Positive `d` means the opponent-adjusted candidate predicted better.** The
statistic is the mean of `d` over the **same starts** (a paired comparison: both arms
are in one row). Expected-strikeout error: `d_mae = |K - E_baseline| - |K -
E_candidate|`, same sign; reported with its interval and decides nothing. Brier
scores are descriptive.

## 6. Interval, fixed

A date-clustered bootstrap of the mean of `d`: dates resampled with replacement (all
of a date's starts move together), **2,000 resamples, seed `20261004`**, dates sorted
ascending, 95% percentile interval from the `int(0.025 N)` and `int(0.975 N)` order
statistics. The same function as K_BASELINE (`clustered_mean_interval`); a test pins
it to `src.model.discovery.clustered_bootstrap`.

## 7. Decision rule, fixed

2023 is the first look. 2024 is the confirming season. **Lines 4.5 and 5.5 decide.**

- **SUPPORTED** only if, on **both** the 4.5 and the 5.5 line, the 95% interval of
  mean `d` on **2024** lies entirely above zero **and** the **2023 point estimate**
  of mean `d` on that line is positive.
- **WORSE** if on **both** lines the 2024 interval lies entirely below zero.
- **NOT SUPPORTED** otherwise: one line clears and the other does not, an interval
  touches zero, a 2023 estimate is zero or negative, any interval cannot be computed.
  The result document says in which direction the numbers fell.

Applied by `src.research.k_baseline.decide` unchanged (re-exported here), literally;
there is no threshold to move and no effect-size floor. The 3.5 and 6.5 lines, the
MAE, and every descriptive table **cannot change, rescue or veto the verdict**.

**Multiplicity.** One candidate, four lines (`candidates_evaluated = 4` on the
registry row). The verdict is an intersection rule over two pre-designated tests, so
no BH or Bonferroni adjustment is applied to it. The intervals are 95% intervals,
**not** the registry-wide `0.05 / N` family-wise bar, and a `SUPPORTED` here would not
meet that stricter bar; the result document says so. This is the second strikeout
registration (`K_BASELINE` was the first); the two are counted separately in the
registry and neither rescues the other.

## 8. What size of effect the sample can detect

Stated now as a formula and a planning illustration (not data); the measured value
is reported with the result.

- **Reported with the result:** the observed bootstrap standard error of mean `d`
  per line and season and the **minimum detectable effect at roughly 80% power,
  two-sided 5%: about 2.8 times that standard error**.
- **Planning arithmetic.** The factor moves the mean by a few percent (a shrunk
  opposing team rate is plausibly within a few percent of the league rate), a
  movement of the Over probability of the order of one to two percentage points
  near the 4.5 and 5.5 lines. For a systematic shift `delta` in the right direction on
  an event of probability near 0.5, the expected gain per start is about
  `2 * delta^2` and the standard error of the mean about `2 * delta / sqrt(n)`, so
  the gain over its standard error is about `delta * sqrt(n)`; with roughly 4,000
  scored starts a shift of one percentage point gives a ratio near 0.6 and two points
  near 1.3, both **well short of the 2.8 needed**. **This study is therefore expected,
  before any result, to be underpowered against an effect of the realistic size, and
  a null (`NOT SUPPORTED`) is the likely outcome whether or not an opponent effect
  exists.** A null would say that this specific candidate adds less than the
  minimum detectable effect, not that the opposing lineup does not matter.

## 9. Descriptive only, no decision rides on them

Published for both seasons whatever they show:

- All four lines: base rate, mean predicted probability for both arms, log loss and
  Brier score for both arms; the paired `d` interval, standard error and minimum
  detectable effect.
- Expected-strikeout MAE for both arms and the paired `d_mae` interval.
- The distribution of the factor (minimum, quartiles, maximum, mean), the share
  exactly 1, the share bounded at each end, and the mean `d` on the subset of starts
  whose opponent has at least 1,000 plate appearances of history.
- The 2023 and 2024 K_BASELINE baseline log losses on this study's comparable starts
  against the K_BASELINE artifacts, as a reconciliation (they must agree on the
  starts both scored).

## 10. Disclosed limits, written before any result

1. **No price, no lineup card.** The factor is a TEAM rate over the team's earlier
   games, not the actual nine batters who started: no handedness, no rest, no
   platoon, no injury, no bench. The registered hypothesis is about the opposing
   team's strikeout tendency, not that day's lineup.
2. **Relievers' strikeouts count in the opposing team's rate** (the rate is of the
   whole game's pitching, starters and relievers), as the stored data has no
   batter-level strikeouts for 2023-24. It is a team batting strikeout rate in the
   ordinary sense, but its plate appearances are faced partly by relievers.
3. **No park, umpire or weather.** A home team's rate includes its home park; the
   factor is not park-adjusted.
4. **No betting-return claim is possible.** There are no historical strikeout
   prices before 2026 and 2026 inputs before 2026-08-28 are sealed.
5. **Underpowered by construction** (section 8).
6. **One candidate, one constant, one run per season.** The script refuses to
   overwrite an artifact.
7. **The comparable base is a subset** of the K_BASELINE scored starts (starts
   without an identified opposing team are dropped from both arms); the exclusion
   counts are reported.
8. **Hindsight on the starter.** As in K_BASELINE the unit is a start that happened,
   not a probable pitcher; a live board would need the opposing team and the starter
   in advance, which this study does not test.

## 11. Out of scope, with the reason

Price and return on 2026 posted strikeout lines are **NOT RUN**: they need
sealed-window inputs. Nothing here reads a 2026 row. No live model, board, card or
threshold is touched.

## 12. What a result can and cannot say

- `SUPPORTED`: on 2023-24 data the opposing-team factor lowered the log loss of the
  4.5 and 5.5 Over probabilities against the K_BASELINE candidate in both seasons by
  the registered rule. It says nothing about price, 2025-26 or a live board, meets
  only the 95% bar, authorizes nothing, and at most supports **asking** for the
  separate promotion process, which has its own falsification battery.
- `NOT SUPPORTED`: no demonstrated improvement within the power of section 8.
- `WORSE`: the candidate as written degrades the probability.

## 13. Budget, and the registry

One candidate, four lines. The row is registered through
`src.research.alpha_registry.register()` before any run (`kind: hypothesis`,
`family: K_OPPONENT`, `market: pitcher_strikeouts`, `sport: mlb`,
`data_window: {discovery: "2023", replication: "2024", sealed_untouched: false}`,
`candidates_evaluated: 4`, `alpha_declared: 0.05`). A verdict is appended through
`record_verdict()` after the 2024 read. Registering raises the registered
count by one and leaves the *read* count (the figure the product states) unchanged
until a verdict is recorded.

## 14. Procedure

1. Run 2023, then 2024 (`python scripts/k_opponent_compare.py --season 2023`, then
   `2024`). Artifacts: `data/research/k_opponent/k_opponent_{2023,2024}.json`.
2. Apply the rule (`python scripts/k_opponent_compare.py --verdict`), write
   `docs/research/K_OPPONENT_RESULT.md`, append the verdict.
3. A defect found after this commit that changes a number is fixed in a separately
   disclosed commit, never silently, and a run already completed is not repeated
   unless the defect corrupted it (a crash or a wrong join), never because of what it
   showed. No parameter, population or rule in this document may be edited after this
   commit; a different specification is a new registration.

## 15. Harness provenance (filled in by the registration commit)

The harness was committed alone, before this document, in commit
`1cf52b6f5203d9cc0a6cfaeed5ac0af850a373f6` (2026-10-04T11:59:00-07:00). Final blobs:

- `src/research/k_opponent.py` `d8e85423c4fdaaaac2e62f9bcb84bfa9f1fdc086`
- `scripts/k_opponent_compare.py` `9966b170e3abda7dfc1c04a2b9adaf9753fc9ba9`
- `tests/test_k_opponent.py` `b7db6846b56423a1eff2820b1295461aa9e5d9c5`
- `src/research/k_baseline.py` `ed5a5e6357a057bc5a6d2e12d4941408218fec10` (the
  registered K_BASELINE harness, unchanged and imported, not copied)

`tests/test_k_opponent.py` has 53 tests, all on synthetic rows built in the test
file. They pin, among others: the hard date guard (a 2025 or 2026 date raises
`SealedDataError` in the builders and the history; sealed and out-of-season raw
lines are discarded **before parsing**, proven with deliberately unparsable sealed
lines that would raise if decoded), point-in-time construction (changing or deleting
any game on or after a start's date changes nothing before it; a same-day game never
feeds a same-day start; a mutation of "strictly before" to "on or before" was run
and made three tests fail), that the baseline probabilities equal the K_BASELINE
candidate probabilities, that the arms differ only by the factor (with the factor
switched off they coincide), one row per start with both arms in it, and the
exclusion-by-cause accounting.
