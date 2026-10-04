# Result: does adjusting the pitcher-specific strikeout forecast for the opposing lineup's strikeout tendency improve it?

**Rule id** `K_OPPONENT_V1` · **Registry id**
`K_OPPONENT:opponent_k_factor_vs_pitcher_specific:pitcher_strikeouts` ·
**Registration** `docs/PREREG_K_OPPONENT.md`, commit
`614fc311aba98681165d2d71957f7cafcb2a4c8c` (2026-10-04T11:59:45-07:00), after the
harness commit `1cf52b6f5203d9cc0a6cfaeed5ac0af850a373f6` (11:59:00-07:00). The runs
were generated at 2026-10-04T18:59:52Z (2023) and 18:59:54Z (2024), after both.
**Freeze check:** the sha256 of the registration file (LF-normalised, from the
committed blob) recomputed to
`0ec6209d648baa1028194b0138fd65b2972f1b453752b0b4858949f792b0bf15` before any result
was read and matches the registry row's note. The registration stands.

**This is a comparison of forecast quality against what happened. It has no price in
it, makes no claim about betting return, authorizes nothing, and changes no live
number, board, card or threshold.**

## Verdict, by the registered rule, in its own words

> **SUPPORTED** only if, on **both** the 4.5 and the 5.5 line, the 95% interval of
> mean `d` on **2024** lies entirely above zero **and** the **2023 point estimate**
> of mean `d` on that line is positive.

`d = loss(baseline) - loss(candidate)` in nats; positive means the opponent-adjusted
candidate predicted better. The BASELINE is the registered K_BASELINE candidate
(pitcher-specific Poisson). 95% date-clustered bootstrap, 2,000 resamples, seed
20261004.

| line | 2023 mean d [95%] | 2024 mean d [95%] |
|---|---|---|
| **4.5** (decisive) | **+0.00754** [+0.00438, +0.01098] | **+0.01300** [+0.00938, +0.01642] |
| **5.5** (decisive) | **+0.00837** [+0.00503, +0.01183] | **+0.01227** [+0.00863, +0.01614] |
| 3.5 | +0.00735 [+0.00417, +0.01062] | +0.01039 [+0.00710, +0.01361] |
| 6.5 | +0.00836 [+0.00536, +0.01154] | +0.01139 [+0.00754, +0.01526] |

On both decisive lines the 2024 interval is entirely above zero and the 2023 estimate
is positive. **The verdict is SUPPORTED** (`python scripts/k_opponent_compare.py
--verdict` returns the same). Registry result: `candidate`, not `survivor`; no
falsification battery has been run. The result is not a loss and not a null, which the
registration said was the likely outcome (section 8); see "A surprise, and what was
checked" below.

What that means, narrowly: multiplying a starter's shrunk per-batter strikeout rate by
a shrunk opposing-team strikeout factor lowers the log loss of the 4.5 and 5.5 Over
probabilities, by about 0.008 to 0.013 nats per start, against the same forecast with
no opponent information, on 2023 and 2024 starts. It says nothing about price, about
2025 or 2026, about the day's actual lineup, or about any live board. It meets the 95%
bar, **not** the registry-wide `0.05 / N` family-wise bar.

## Coverage (comparable observations)

The comparable base is the set of starts K_BASELINE scored (4,122 in 2023, 4,488 in
2024), less starts whose opposing team cannot be identified from stored data. Both arms
are in one row, so a dropped start leaves both. The baseline probabilities of the
scored starts are the K_BASELINE candidate probabilities; **the K_BASELINE rows
rebuilt here (4,122 and 4,488) reproduce the stored K_BASELINE `row_digest` of each
season exactly**
(`baseline_reconciliation.equal` is true for both artifacts).

| | 2023 | 2024 |
|---|---|---|
| starts scored by K_BASELINE | 4,122 | 4,488 |
| **starts scored here** | **4,111** | **4,482** |
| excluded: game recorded under two dates (`game_excluded_multi_date`) | 11 | 6 |
| excluded: no game match, ambiguous, other game check, K/BF disagree, no reference rate | 0 | 0 |
| regular-season games used in the opponent history | 2,424 of 2,430 seen | 4,848 of 4,857 seen (2023 and 2024 read) |
| games excluded wholesale (all `multi_date`) | 6 | 9 (cumulative over 2023 and 2024) |
| factor bounded low / high | 39 / 61 | 75 / 134 |
| share of scored starts bounded (low + high) | 2.4% | 4.7% |
| factor exactly 1 (no opponent history) | 0 | 2 |

The 2024 run reads 2023 as the prior-season pool, so its game and start-extraction
counts in the artifact cover both seasons (9,715 start rows, 9,693 with an opposing
team; the 22 without are the 18 starts in the nine two-date games and the 4 starts, all
dated 2024-03-20 or 2024-03-21, that match no game; none of those 4 was scored by
K_BASELINE). All-Star games are removed because they are not in `mlb_results.csv` as
regular-season games. Every excluded start is a start in the nine games the bullpen log
records under two dates, which the registration excluded wholesale.

## Descriptive tables (nothing here can change, rescue or veto the verdict)

Log loss in nats, Brier, mean predicted Over probability, and the sample's detectable
size. `se` is the bootstrap half-width over 1.96; **minimum detectable effect** is
2.8 times it, as registered.

**2023** (n = 4,111)

| line | base rate | mean p base | mean p cand | log loss base | log loss cand | Brier base | Brier cand | se of d | min detectable |
|---|---|---|---|---|---|---|---|---|---|
| 3.5 | 0.6869 | 0.7115 | 0.7091 | 0.57160 | 0.56425 | 0.19409 | 0.19120 | 0.00164 | 0.00460 |
| 4.5 | 0.5381 | 0.5456 | 0.5438 | 0.63805 | 0.63051 | 0.22372 | 0.22024 | 0.00168 | 0.00472 |
| 5.5 | 0.3792 | 0.3849 | 0.3842 | 0.61397 | 0.60560 | 0.21308 | 0.20954 | 0.00173 | 0.00486 |
| 6.5 | 0.2540 | 0.2507 | 0.2512 | 0.51925 | 0.51089 | 0.17212 | 0.16932 | 0.00157 | 0.00441 |

**2024** (n = 4,482)

| line | base rate | mean p base | mean p cand | log loss base | log loss cand | Brier base | Brier cand | se of d | min detectable |
|---|---|---|---|---|---|---|---|---|---|
| 3.5 | 0.6943 | 0.7095 | 0.7061 | 0.58045 | 0.57006 | 0.19785 | 0.19334 | 0.00166 | 0.00465 |
| 4.5 | 0.5388 | 0.5405 | 0.5383 | 0.65514 | 0.64214 | 0.23193 | 0.22575 | 0.00180 | 0.00503 |
| 5.5 | 0.3909 | 0.3772 | 0.3768 | 0.62626 | 0.61398 | 0.21840 | 0.21327 | 0.00192 | 0.00537 |
| 6.5 | 0.2528 | 0.2421 | 0.2432 | 0.53408 | 0.52268 | 0.17694 | 0.17318 | 0.00197 | 0.00551 |

Both arms are on the same starts. The candidate improves the Brier score on every line
in both seasons too.

**Expected strikeouts (MAE; `d_mae` = baseline error minus candidate error, positive
favours the candidate).**

| | mean K | mean E baseline | mean E candidate | MAE baseline | MAE candidate | `d_mae` [95%] |
|---|---|---|---|---|---|---|
| 2023 | 4.922 | 5.009 | 5.006 | 1.8753 | 1.8508 | +0.0245 [+0.0151, +0.0342] |
| 2024 | 4.915 | 4.960 | 4.958 | 1.8741 | 1.8356 | +0.0385 [+0.0279, +0.0485] |

The factor does not change the mean forecast (the average factor is 0.9998 and
0.9997): it redistributes strikeouts across opponents, it does not shift the level.
Both arms over-forecast the mean (about 0.09 in 2023, 0.05 in 2024), which is the
K_BASELINE candidate's behaviour and is common to both.

**The factor.** 2023: min 0.850, quartiles 0.955 / 1.002 / 1.042, max 1.150. 2024:
min 0.850, quartiles 0.947 / 0.999 / 1.053, max 1.150. The registered bound binds on
2.4% and 4.7% of scored starts, mostly the high side. (The registration expected it
"to bind rarely if ever"; on 2024 it binds about one start in twenty. That is
reported, it is not a defect, and no bound was moved.)

**Subset of starts whose opponent has at least 1,000 plate appearances of history**
(2023 n = 3,852, 2024 n = 3,870; descriptive): mean d at 4.5 and 5.5 is +0.00786
[+0.00436, +0.01151] and +0.00849 [+0.00470, +0.01213] in 2023, and +0.01393
[+0.01009, +0.01769] and +0.01265 [+0.00833, +0.01693] in 2024: the same size as the
full sample, so the result does not come from the early-season starts where the factor
leans on the prior.

## A surprise, and what was checked

The registration (section 8) predicted, before any result, that an effect of realistic
size would be undetectable at about 4,000 starts and that a null was the likely
outcome. The gain observed is larger than that planning arithmetic allowed, with
intervals well clear of zero. A result better than expected is a bug report until
shown otherwise, so four **post-registration instrument checks** were run
(`scripts/k_opponent_checks.py`, fixed seeds, run once, descriptive, not part of the
registration and unable to change the verdict):

1. **Independent recount.** For 300 sampled scored starts per season, the opposing
   team, its batting strikeouts, plate appearances and prior-game count were
   recomputed from the raw bullpen rows by separate code: **0 mismatches in 300 in
   each season.** The harness's point-in-time record is what it says it is.
2. **Placebo.** With the opposing team shuffled among the starts of each date (the
   same factor distribution, the wrong team), mean d turns **negative**: 2023
   -0.00583 [-0.00847, -0.00304] at 4.5 and -0.00491 [-0.00805, -0.00184] at 5.5;
   2024 -0.00803 [-0.01183, -0.00435] and -0.00771 [-0.01149, -0.00387]. The signal depends on
   the right team, which rules out a bias in the factor's distribution alone. It does
   not rule out a leak through the true team's record (scrambling would remove that
   too); the point-in-time tests and check 1 are the evidence against a leak.
3. **Scale.** The slope of the strikeout residual (K minus the baseline's expected K)
   on the applied shift (baseline expected K times factor minus one) is **1.13 in
   2023 and 1.22 in 2024**: the factor is about the right size, if anything slightly
   too timid. A leak would give a slope far above one.
4. **Home and away.** The gain holds whether the opposing team is the home team (4.5:
   +0.00908 in 2023, +0.01301 in 2024) or the away team (+0.00600, +0.01300), so it is
   not only a home-park signature.

The most likely reading of "larger than the planning arithmetic": the registration's
planning figure assumed the factor moves the mean by a few percent, while its
interquartile range is about plus or minus 4 to 5 percent with a tail to the bound, and
team strikeout tendency is a real, stable property (slope near 1). That is an
explanation consistent with these checks, not a proof; nothing here shows the effect
would survive 2025 or a forward test.

## Limits that travel with this result (written in the registration, restated)

- **A team rate, not the day's lineup.** No handedness, no rest, no injuries, no
  platoon, no bench. The candidate is the opposing team's record, not the nine batters
  who played.
- **Relievers' strikeouts are in the rate**, and so is anything a team's own record
  carries about its park. The home/away split (check 4) does not isolate park or
  umpire effects.
- **Hindsight on the starter.** As in K_BASELINE the unit is a start that happened. A
  live board would need the starter and the opposing team in advance, which this study
  does not test.
- **No price anywhere.** There are no historical strikeout prices before 2026 and
  2026 inputs before 2026-08-28 are sealed. A better log loss against the outcome is
  not a better bet: the book prices the same facts. The pitcher-specific baseline was already
  "the lowest bar" (K_BASELINE result), and the opposing team's strikeout tendency is
  public information, so it may well already be in a posted line; this study cannot
  say, because it has no line to compare with.
- **95% bar, one candidate, one constant, one run per season.** Not the `0.05 / N`
  bar. `SUPPORTED` at most supports **asking** for the separate promotion process and
  its falsification battery; it promotes nothing.
- **Sealed-window disclosure.** `sealed_untouched` is false on the registration row:
  an inspection command printed three rows of one 2026-03-26 game (sealed window) and
  the opening of one `matchup_history.jsonl` record before the harness existed (PREREG
  section 0). Neither was a design input. The harness itself discards every
  out-of-season raw line before parsing it, and the run and the checks printed no row.

## Registry

Verdict `candidate` appended to
`K_OPPONENT:opponent_k_factor_vs_pitcher_specific:pitcher_strikeouts`.
`total_searched()` after the verdict: 50 registered hypotheses, 1 sweep (8,811 internal
candidates), 2 audits; 43 read, 10 not read. The product's own research count (the
read hypotheses) goes from 39 to 40; `_LAST_KNOWN_HYPOTHESES` in
`src/analysis/__init__.py` and the fallback figure on `web/landing.html` were updated
to 40 together, and the tests that pin them pass. K_BASELINE and K_OPPONENT are two
separate registrations; neither rescues the other.

## Reproduce

`python scripts/k_opponent_compare.py --season 2023`, then `--season 2024`, then
`--verdict`; artifacts `data/research/k_opponent/k_opponent_{2023,2024}.json` (each
holds the counts, the reconciliation against the K_BASELINE digest, the summary and
the code blob ids). `python scripts/k_opponent_checks.py` reproduces the instrument
checks. The script refuses to overwrite an artifact.
