# Phase 2A — a regularised model against the closing line

**§1–§8 frozen before any score was computed.** One question, stated in
advance with its expected answer:

> Do our baseball features carry incremental predictive information beyond
> the market's own de-vigged closing price?

**Expected answer: no.** This document follows `docs/BENCHMARK_ELO.md`
exactly — register the spec and the expectation first, score once, publish
whichever way it falls.

## 0. Status of this result

**Not evidence. A diagnostic.** Train 2023, evaluate 2024; both seasons sit
inside the explicitly exploratory, non-evidential sandbox settled by Brey's
Decision 1 (`docs/EVOLUTION_LAB_ASSESSMENT.md` §7). 2023–24 has already
shaped feature development, four research families and 25 pre-registered
specs, so a 2024 number here is not an independent holdout and is never
reported as one. The forward stream remains the first independent arbiter.
2025 is tuning-only and is not read. Sealed 2026-01-01→08-27 is not read.

`docs/EVOLUTION_LAB_ASSESSMENT.md` §5 named this test and put it ahead of
the Evolution Lab: *"We have never fit a proper regularised model on the
full point-in-time matrix and measured it against the close. That test is
cheaper than the entire Evolution Lab."* This is that test.

## 1. Target, baseline and the residual framing

- **Target** `y` — home win (1/0), from `data/historical/mlb_results.csv`.
- **Baseline** `p_mkt` — the de-vigged closing consensus home probability:
  `selections._fair(pair["close"]...)["home_fair"]`, i.e. each quoting
  book's two-way moneyline de-vigged proportionally, then averaged across
  books. The identical construction the Elo benchmark was scored against.
- **Model** — penalised logistic regression **on the residual relative to
  the market**:

```
        eta_i = logit(p_mkt_i)  +  b0  +  x_i · beta
        p_i   = 1 / (1 + exp(-eta_i))
```

  `logit(p_mkt)` enters as a **fixed offset with coefficient pinned at 1**.
  It is not a feature, it is never fitted, and it is never penalised. The
  model therefore cannot earn anything by rediscovering the market; the only
  way `x·beta` reduces log-loss is by carrying information the closing price
  does not already contain. That construction is the entire point of the
  exercise.

Three nested models are reported, so that "the market is slightly
miscalibrated" can never be mistaken for "our features predict":

| id | form | what it isolates |
|---|---|---|
| **M0** | `eta = logit(p_mkt)` | the market itself — the baseline |
| **M1** | `eta = logit(p_mkt) + b0` | constant recalibration only, no features |
| **M2** | `eta = logit(p_mkt) + b0 + x·beta` | **the primary model** |

`b0` is unpenalised in M1 and M2.

## 2. Features (frozen)

Source: `data/research/matchup_matrix_{2023,2024}.jsonl` — the point-in-time
matrix built by `src/research/matrix.py`. Every value in a row is computed
from an accumulation cut off at the **first day of the game's own month**,
so a matrix feature can only ever be under-informed, never over-informed
(`matrix._cutoff_for`). No price, no outcome and no closing information
enters a feature; the only market number in the model is the offset.

Nine base quantities, each stored per side. `matrix.py` crosses sides once,
deliberately: an `away_`-prefixed value describes the **away lineup's**
matchup, i.e. it is computed against the **home** starter. So a
lineup-shaped quantity is read on its own side, and a starter-shaped
quantity is read on the *opposite* prefix. The nine, with the side the
home-oriented contrast takes:

| base quantity | shape | home value | away value |
|---|---|---|---|
| `lineup_platoon_share` | lineup | `home_` | `away_` |
| `lineup_vs_primary_pitch` | lineup | `home_` | `away_` |
| `top_minus_bottom` | lineup | `home_` | `away_` |
| `history_woba` (`lineup_vs_starter_history.woba`) | lineup | `home_` | `away_` |
| `history_pa` (`log1p` of `lineup_vs_starter_history.pa`) | lineup | `home_` | `away_` |
| `starter_platoon_gap` | starter | `away_` | `home_` |
| `starter_velocity_gap` | starter | `away_` | `home_` |
| `starter_groundball_share` | starter | `away_` | `home_` |
| `primary_pitch_share` | starter | `away_` | `home_` |

From each base quantity `q`, two columns:

- **`d_q` = home-side value − away-side value** — the home-oriented
  contrast. Positive means the quantity favours (or is larger for) the home
  side of the matchup.
- **`m_q` = (home-side value + away-side value) / 2** — the game-level
  level, which carries environment effects a contrast cancels.

**18 columns total.** `primary_pitch` (a categorical pitch code) is
excluded: one-hot encoding it would add a dozen sparse columns whose
mechanism is game-environment at best. Nothing else in the matrix row —
teams, date, start time, `cutoff`, `gaps` — enters the design.

## 3. Missing values (frozen)

Coverage is thin for several quantities and is **materially different
between the two seasons**, because the pitch store begins in 2023 and every
accumulation is thin early. Measured before freezing this section:

| base quantity | 2023 per-side coverage | 2024 per-side coverage |
|---|---|---|
| `lineup_platoon_share` | 100% | ~100% |
| `top_minus_bottom` | 99% | 100% |
| `lineup_vs_primary_pitch` | 81% | 96% |
| `primary_pitch_share` | 82% | 96% |
| `starter_groundball_share` | 70% | 92% |
| `starter_velocity_gap` | 67% | 86% |
| `starter_platoon_gap` | 49% | 84% |
| `history_woba` (pa > 0) | 25% | 71% |

`history_pa` is always defined (0 PA is a fact, not a gap; `log1p(0) = 0`).

Rule: **side-level mean imputation with training-season constants.** For
each base quantity, one pooled mean over both sides across the 2023 training
rows; a missing side takes that constant; then `d_q` and `m_q` are formed.
Pooled across sides, not per side, so no home/away asymmetry is imported by
the imputation itself.

**No missingness indicators.** Missingness rates differ so sharply between
2023 and 2024 that an indicator would carry a season-specific meaning and
teach the model a 2023 artifact. Omitting them is the conservative choice
and is stated here rather than discovered later.

This train/eval coverage shift is a real limitation and is disclosed as
one: coefficients are learned on a season where several inputs are imputed
half the time, and applied to a season where they usually exist. It biases
toward a **null** — it cannot manufacture a win.

## 4. Scaling and the penalty (frozen)

Columns are z-scored with **means and standard deviations computed on the
2023 training rows only**, applied unchanged to 2024. A column with zero
training variance is dropped. Imputation constants, standardisation
constants and the penalty are all chosen inside 2023 and never revisited;
2024 sees a frozen function.

Objective, on the standardised design, with the offset fixed:

```
    J(b0, beta) = SUM_i NLL_i  +  (lambda / 2) * ||beta||^2        (L2)
    J(b0, beta) = SUM_i NLL_i  +  lambda * ||beta||_1              (L1)
```

`b0` is never penalised.

**Penalty grid** (identical for both norms, 12 values):

```
    lambda in {0.1, 0.3, 1, 3, 10, 30, 100, 300, 1000, 3000, 10000, 30000}
```

At the top of the grid `beta` is driven to essentially zero and M2 collapses
onto M1 — deliberate, so "shrink it all away" is inside the search space.

**Penalty selection: 5-fold cross-validation inside 2023 only.** Folds are
**grouped by date** — every game on a date lands in the same fold, because
games on one slate share weather, news and market conditions and splitting a
slate across folds leaks. Distinct 2023 dates are sorted and assigned
`fold = index mod 5`. `lambda` is chosen by minimum mean out-of-fold
log-loss, then the model is refit on all of 2023 at that `lambda`. Inside
cross-validation the imputation and standardisation constants are recomputed
from each fold's own training rows, so no fold's held-out games touch the
constants used to score them. **2024 is never used to choose anything.**

**Optimisation** (no numpy, no scipy — pure Python, deterministic):
L2 by Newton/IRLS with a ridge-augmented Hessian solved by Gaussian
elimination with partial pivoting; L1 by proximal gradient (ISTA) with
backtracking and soft-thresholding. Both start from zero, both have fixed
iteration caps and tolerances, both are exercised against closed-form and
planted-coefficient tests.

## 5. The evaluation split and universe (frozen)

- **Train: 2023.** **Evaluate: 2024.** No 2024 row touches fitting,
  imputation, standardisation or penalty selection.
- A game is eligible when it (a) has a matrix row — which requires a posted
  lineup — (b) is a regular-season game with a recorded outcome, (c)
  resolves to exactly one odds event by `selections._resolve_pair` (start
  time within the module's gap, so a neighbouring game's market can never
  price it), (d) has a **distinct** close snapshot, and (e) has a close
  consensus quoted by **at least 6 books**.
- (d) and (e) are the Elo benchmark's own filters, kept so the evaluation
  universe is the *same* 2,234 games `docs/BENCHMARK_ELO.md` scored. That
  makes the two results directly comparable rather than merely adjacent.
- **Pre-registered sensitivity:** the same evaluation with filter (d)
  dropped (close consensus required, distinctness not). It only enlarges the
  sample. Reported alongside; the primary number is the one with (d).

Expected eligible counts, measured before freezing: **2,161 training games
(2023)** and **2,234 evaluation games (2024)**.

## 6. Metric (frozen)

Per evaluated game, log-loss `-log(p)` with `p` clamped to
`[1e-6, 1-1e-6]` — the same clamp `elobench._log_loss` uses — for M0, M1 and
M2, plus Brier alongside.

The statistic is the **per-game log-loss differential, model minus market**,
averaged. **Positive means the model is worse than the market**, matching
the Elo benchmark's sign convention exactly.

Uncertainty: `discovery.clustered_two_sided_p` on that differential,
**clustered by date** — the same machinery every family in this project
uses, for the same reason.

Reported: M2 − M0 (**primary**), M1 − M0, and M2 − M1.

## 7. Pre-registered expectation

**The model does not beat the market.** Concretely, stated before any score
was computed:

1. The primary M2 − M0 differential lands at or above zero — the model no
   better than the close — plausibly within ±0.005 log-loss per game.
2. Its date-clustered two-sided p does not show a significant improvement.
3. Cross-validation inside 2023 selects a penalty toward the **strong** end
   of the grid, shrinking most coefficients to near zero.
4. M1 − M0 is very close to zero: the de-vigged consensus is close to
   calibrated on the home side and there is no constant to harvest.

Grounds: 25 pre-registered specs across four families with zero survivors; a
public-style Elo losing to the close by 0.008 log-loss per game at
p = 0.0003; monthly cutoffs that make every feature up to a month stale; and
the fact that these inputs (lineups, starters, arsenals) are precisely what
the market prices most attentively.

If the expectation holds it is the strongest statement this project can make
about its own feature set, and it is far cheaper than the Evolution Lab.

## 8. What happens if the model wins (frozen, before knowing)

An implausible win is a bug until proven otherwise. **No celebration, no
downstream work, no promotion** until every item below is answered in
writing:

1. **Leakage by cutoff.** Does any row read an accumulation whose cutoff is
   on or after the game's own date? Assert `cutoff < date` on every scored
   row.
2. **Outcome encoding.** Does any feature move with the result of its own
   game? Re-derive each column's provenance and confirm it comes only from
   pitches strictly before the cutoff.
3. **Closing information in the features.** Confirm no column is derived
   from any price, and that the offset is the only market number present.
4. **Split contamination.** Confirm imputation constants, standardisation
   constants and the chosen penalty are functions of 2023 rows only.
5. **Join integrity.** Confirm each scored game's odds event is its own
   (`_resolve_pair` gap check) and that no game is scored twice.
6. **Magnitude sanity.** An improvement materially larger than the 0.008 the
   close takes off a public-grade Elo is, on its face, not credible.
7. Only then: re-register a follow-up and let forward data arbitrate.

---

## 9. Result

Run 2026-08-31, once, after §1–§8 were frozen. Code `src/evolab/baseline.py`;
artifact `data/research/evolab/phase2a_baseline.json`; 44 seconds wall-clock.

Trained on **2,161** eligible 2023 games (182 dates), evaluated on **2,234**
eligible 2024 games (183 dates) — the pre-registered counts, and the same
2,234 games `docs/BENCHMARK_ELO.md` scored. Excluded, with reasons: 2023 —
16 no price pair, 5 thin consensus, 248 no distinct close; 2024 — 14, 5,
176. No column was dropped for zero training variance; all 18 were fitted.

### 9.1 What cross-validation chose

| penalty | chosen lambda | out-of-fold log-loss at the choice | coefficients |
|---|---|---|---|
| L2 | **10000** | 0.674176 | 18 non-zero, largest 0.0046 |
| L1 | **100** | 0.674187 | **all 18 exactly zero** |

Both landed near the strong end of the grid, and the L1 fit landed *past*
it: at lambda = 100 soft-thresholding zeroes every coefficient, and every
larger lambda on the grid gives the identical out-of-fold loss (0.674187 at
100, 300, 1000, 3000, 10000, 30000 — the fit has already collapsed onto M1
and cannot collapse further). The L2 path tells the same story from the
other side: out-of-fold loss falls monotonically as the penalty rises,
0.679218 at lambda = 0.1 down to 0.674176 at 10000, i.e. **every reduction
in feature weight improved held-out fit inside the training season.**

The surviving L2 coefficients, on standardised columns, are numerically
negligible — largest `m_top_minus_bottom` at +0.00460, then
`m_starter_velocity_gap` at −0.00451; the sum of all eighteen absolute
values is 0.0278. A one-standard-deviation move in the largest feature
shifts the home log-odds by less than half a hundredth, against a market
log-odds that routinely spans ±1.

Fitted intercepts: M1 `b0` = **−0.038951**, L2 `b0` = −0.038932, L1 `b0` =
−0.038951 (identical to M1's, as it must be when every coefficient is zero).

### 9.2 Out-of-sample, 2024 (2,234 games)

| forecaster | log-loss | Brier |
|---|---|---|
| **M0 — de-vigged close consensus** | **0.67275** | **0.23999** |
| M1 — close + recalibration intercept | 0.67270 | 0.23996 |
| M2 (L1) — close + intercept + L1 features | 0.67270 | 0.23996 |
| M2 (L2) — close + intercept + L2 features | 0.67279 | 0.24001 |

M0's 0.67275 and 0.23999 **reproduce `docs/BENCHMARK_ELO.md`'s published
close numbers to the last digit**, on the same 2,234 games, through a
completely separate join written for this module. That is an independent
arithmetic check on the eligibility filter, the pairing, the de-vig and the
loss function all at once, and it passed.

Per-game log-loss differentials — **positive means the model is worse than
the market**, the Elo benchmark's sign convention — with date-clustered
two-sided p:

| comparison | mean diff / game | clustered p |
|---|---|---|
| **M2 (L2) − M0 — primary** | **+0.0000412** | **0.914** |
| M2 (L1) − M0 | −0.0000506 | 0.896 |
| M1 − M0 | −0.0000506 | 0.896 |
| M2 (L2) − M1 | +0.0000918 | 0.247 |
| M2 (L1) − M1 | −1.9e-18 | (not meaningful) |

The last row is floating-point residue, not a measurement: the L1 model *is*
M1, every coefficient being exactly zero, so the two forecasts are the same
forecast and the printed p (0.159) describes rounding. It is listed only so
that nothing in the table is silently omitted.

Pre-registered sensitivity, distinctness filter dropped — 2,409 training and
2,410 evaluation games:

| comparison | mean diff / game | clustered p |
|---|---|---|
| M2 (L2) − M0 | −0.0001883 | 0.617 |
| M2 (L1) − M0 | −0.0002038 | 0.589 |
| M1 − M0 | −0.0002038 | 0.589 |
| M2 (L2) − M1 | +0.0000155 | 0.508 |

Here L2 chose lambda = 30000 (the top of the grid) and L1 again zeroed
everything. The larger sample moves nothing: the whole M2 − M0 difference is
the intercept's, and M2 − M1 is +1.6e-05 at p = 0.508.

### 9.3 Reading

**The pre-registered expectation holds, and holds at every point.**

- §7.1 — the primary differential is +0.0000412 log-loss per game, the
  model **worse**, and inside the predicted ±0.005 band by two orders of
  magnitude.
- §7.2 — p = 0.914. Not a near miss; a measurement of zero.
- §7.3 — cross-validation chose the strong end of a grid spanning six
  orders of magnitude. L1 chose to use **no feature at all**.
- §7.4 — M1 − M0 is −0.00005 log-loss per game at p = 0.896: the de-vigged
  closing consensus needs no constant correction worth having. There is no
  calibration bias to harvest either.

The honest one-line summary is not "the model failed to beat the market". It
is: **offered eighteen point-in-time features, a free intercept and an
honest cross-validation, the procedure declined to use any of them.** The
L1 result is the cleanest statement of that — a sparse model that selects
the empty set. For scale, the market takes 0.00801 log-loss per game off a
public-style Elo (p = 0.0003); the largest movement anything in this model
produced against the market is 0.0002, and it is not distinguishable from
zero.

### 9.4 The §8 checklist, run because it is unconditional

Every item was answered, not because the result invited scrutiny but
because a check performed only after a win is a check whose answer was
already known. All are machine-computed in `baseline.leakage_checks` and
stored in the artifact.

1. **Leakage by cutoff — one item did not pass as literally written, and
   the reason is worth recording.** §8.1 says "assert `cutoff < date` on
   every scored row". Measured: 2,173 of 2,234 evaluation rows and 2,086 of
   2,161 training rows have `cutoff < date`; the remaining 61 and 75 have
   `cutoff == date`, and **zero rows in either season have a cutoff after
   the game date**. Every equal-cutoff row is a game played on the **1st of
   a month** — `matrix._cutoff_for` anchors a game to the first day of its
   own month, so a game on the 1st gets its own date as its cutoff. That is
   not a leak: `rebuilt` accumulates strictly on `game_date < cutoff`
   (`statcast_pitches.iter_rows(before=)`, `rebuilt._gate`), so a cutoff
   equal to the game date still excludes every pitch from the game's own day
   and every day after it. The pre-registered assertion was drawn one day
   too tight; the check now reports before/equal/after separately rather
   than conflating them, and `after` — the count that would be a genuine
   leak — is 0/2,234 and 0/2,161.
2. **Outcome encoding.** No column is derived from a result. Each traces to
   `matrix.py` accumulations over pitches strictly before the cutoff, plus
   schedule facts; the crossing from `away_`/`home_` prefixes to
   home-versus-away contrasts is a table (`BASE_QUANTITIES`) with a test per
   shape.
3. **Closing information in the features.** Verified mechanically, not
   asserted: the design is rebuilt with every row's market price replaced by
   0.5 and compared column by column. **0 columns move**, in both seasons.
   The offset is the only market number the model can see.
4. **Split contamination.** Imputation constants, standardisation constants
   and the penalty are functions of training rows only, and a test proves
   it by scrambling every held-out feature and asserting the fitted
   coefficients, intercept and chosen penalty are byte-identical. Inside
   cross-validation the constants are recomputed per fold.
5. **Join integrity.** Every game resolves to its own odds event through
   `selections._resolve_pair`'s start-time gate; duplicate `game_pk` count
   is 0; train/eval overlap is 0.
6. **Magnitude sanity.** Not applicable — there is no improvement to find
   implausible.
7. Nothing to re-register.

**No feature looked suspicious.** The one candidate for suspicion was
`d_history_woba` / `d_history_pa` (the lineup's history against tonight's
starter), which rises from 25% to 71% coverage between the seasons; its
fitted weight is −0.00056 and +0.00035, and the L1 fit drops both. Nothing
else came close to mattering.

### 9.5 What this does and does not say

**It says:** within this feature set, this functional form and this sample,
there is no incremental predictive information beyond the closing price.
Linear-in-the-features, monthly-cutoff, lineup-and-starter state adds
nothing the market has not already priced. That is a direct joint answer to
a question 25 pre-registered specs approached one hypothesis at a time and
never asked properly.

**It does not say** the features are useless for every purpose, that a
non-linear model would also find nothing (though a heavily constrained one
on 2,161 games has little room to), or that no MLB feature set can beat the
close. It also does not rule out that a *fresher* cutoff would do better:
these features are up to a month stale by construction, which is the single
most obvious limitation and the most obvious follow-up.

**And it is not evidence.** 2023–24 is the exploratory sandbox; only forward
data arbitrates. This is a diagnostic, as §0 states.

For the Evolution Lab this is a load-bearing prior. Phase 2 proposes to
search a strategy space built from these same features. A correctly
specified regularised model, given all eighteen at once with honest
cross-validation, extracted exactly zero — and its cross-validation, when
allowed to weight them freely, preferred to weight them at nothing. A
combinatorial search over thresholds on those inputs is searching inside a
span that has now been measured and found empty. That does not make the
lab's placebo calibration unnecessary — a search can still manufacture
apparent winners from a barren space, which is precisely what the ceiling
exists to quantify — but it does mean `docs/EVOLAB_DESIGN.md` §15's kill
criteria should now be read as the expected outcome rather than the
cautious one.
