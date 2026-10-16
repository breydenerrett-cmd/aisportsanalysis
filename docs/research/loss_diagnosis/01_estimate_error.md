# Loss diagnosis 01: why the prop probabilities are off, and which way

Research agent 1 of 3, 2026-10-16. Research only: no model file, store, card, threshold or
fingerprint was changed. Every number below is printed by
`python3 scripts/diagnosis/estimate_error.py --part all` into
`data/research/loss_diagnosis/estimate_error_tables_all.md`; table ids in brackets (P2, Q5,
X10 ...) are that file's headings. Evidence rules: no outcome dated 2026-01-01..2026-08-27 was
read (loaders drop sealed rows on their date first; the 2026 box store is asserted to have
none); 2025 is used only where labelled TUNING-ONLY; 2023/2024 and 2026-08-28 onward are open.

## The answer in one paragraph

Our published prop probabilities were **too high by 8.5 points** on average (149 graded
props: mean `our_probability` 0.608, hit rate 0.523) while the de-vigged market on the same
bets was off by **+0.2 points** (P1). Almost exactly the whole error is the gap the card
selects on: our number sat **+8.2 points above the market** on the bets we published, and
**none of that gap was realized** (hit rate minus market = -0.2 points, X7). On the full,
unselected forward pool (6,818 priced contracts), the model is close to calibrated overall
(+0.9 points) but **worse than the market** by +0.0103 nats per contract [+0.0061, +0.0147]
(Q2), and the best blend of model and market puts **no weight on the model's disagreement**:
lambda = -0.20 [-0.43, +0.05] (X5). The direction is up, on Overs, and it comes from three
places: (1) selecting the model's largest disagreements with a market that knows more,
about 4 of the 8 points; (2) total bases over 0.5 priced without the within-game correlation
correction that the identical hits-over-0.5 event gets, +3.0 points on every such contract,
in every season measured; (3) no opposing-pitcher term and no postseason adjustment, which
leaves the October pool 6 to 11 points too high.

## How this was measured

**Command (reproduces every number in this document):**

```
python3 scripts/diagnosis/estimate_error.py --part all
```

Runtime about 5 minutes. Helpers: `scripts/diagnosis/_ee_common.py`. Outputs (small):
`data/research/loss_diagnosis/estimate_error_tables_all.md` and six cached statsapi.mlb.com
team-hitting totals (`statsapi_team_hitting_{2023,2024,2025}_{R,P}.json`).

| what | file | how used |
|---|---|---|
| published graded props | `evidence/cards_v2.jsonl` via `card_ledger.history_v2(path=..., limit=None)` | 149 props graded WIN/LOSS over 20 dates; 8 VOID and 3 UNRESOLVED excluded (P0) |
| decision rows | `evidence/decisions_v2.jsonl` | census only (P-1): 5,689 game-market rows, no prop rows, no independent model number (market_derived / placeholder / none), so unusable here |
| prop quotes | `data/processed/batter_props.jsonl` | 173,088 rows (2026-09, 2026-10); kept only quotes observed strictly before `commence_time` |
| 2026 outcomes and batter history | `data/processed/boxscores_2026.jsonl` | 2026-08-30..2026-10-15, no sealed row |
| 2023-2025 outcomes and history | `data/archive/historical/boxscores/boxscores_{2023,2024,2025}.jsonl.gz` | regular season only; no archive holds October |
| lineups | `data/historical/lineups.jsonl` | 2023, 2024, 2026-forward (no 2025 rows) |
| game type, probable starters | `data/historical/mlb_results.csv` | sealed rows dropped on `date` first |
| 2024 starter history | `data/historical/pitcher_logs.jsonl` | sealed rows dropped on `date` first |
| handedness | `data/historical/handedness.json` | starter throws, batter bats |
| event to game | `data/processed/event_game_map.jsonl` | `gamekey.load_map` |
| frozen V2 values | `data/processed/card_v2_frozen_params.json` | 2025 slot table and rho as counterfactuals only |
| prior postseason level | statsapi.mlb.com `teams/stats?group=hitting&gameType=R` and `P`, 2023-2025 | six read-only GETs, cached; 2026 never fetched (its season totals contain the sealed window) |

**Same code path as the card.** For each forward date the pool is built by
`propboard.build(...)` with the arguments `src.report.props.board_for_date` passes (box rows
strictly before the slate date, league rates from those rows, slot from the stored lineup by
name) and therefore `playerprops.price_prop` with V1's live constants (V1 slot table,
`RHO = 0.05065`, no starter, `PA_REGRESSION = 200`). The one difference is the quote
snapshot: the newest quote observed strictly before first pitch rather than the publish-time
quote.

**Instrument check (Q0b).** All 149 published props are found in the rebuilt pool; 134
reproduce `our_probability` to rounding (within 0.0006); median absolute difference 0.0000,
maximum 0.0170. The script also re-prices every pool contract through `price_prop` directly
and counts disagreements with `propboard.build`: none.

**Counterfactuals** use arguments `price_prop` already accepts (`slot_table`, `rho`,
`expected_pa`, starter hits/batters faced), `playerprops.probability_over` with a multiplier on
the hit-type rates, or `playerprops.PA_REGRESSION` set inside the script's own process for one
call and restored. Bias = mean probability minus realized rate, in percentage points ("pts").
Intervals: 95% date-clustered bootstrap, 2,000 resamples, seed 20261016 (300 for lambda, 500
for slopes). Log loss in nats.

**Disclosed hindsights in the forward rebuild** (both also in
`docs/research/TB_STARTER_AWARE_RESULT.md`): the slot is the stored posted lineup, which a
live card may not yet have had; the opposing starter is the results file's probable id (the
first-pitch starter).

## 1. Published bets (149 graded props)

**Scores on the same bets (P1, P2).**

| arm | n | Brier | log loss | mean p minus hit rate |
|---|---|---|---|---|
| our_probability | 149 | 0.2605 | 0.7152 | +8.5 |
| our_probability_used (minus 0.038) | 149 | 0.2555 | 0.7044 | +4.7 |
| market, de-vigged | 149 | 0.2512 | 0.6956 | +0.2 |
| breakeven of the price taken | 149 | 0.2536 | 0.7004 | +2.8 |

Paired, ours minus market: log loss +0.0195 [-0.0120, +0.0470]; Brier +0.0092 [-0.0060,
+0.0226]. Our bias +8.5 [-1.0, +16.9]; the market's +0.2 [-9.2, +8.6]. With 149 bets on 20
dates the intervals are wide; the pool below is where the precision is.

**Reliability (P3).** The higher our number, the worse it did:

| our p bin | n | mean our p | hit rate | bias |
|---|---|---|---|---|
| 0.50-0.55 | 18 | 0.522 | 0.556 | -3.3 |
| 0.55-0.60 | 35 | 0.581 | 0.571 | +1.0 |
| 0.60-0.65 | 72 | 0.625 | 0.514 | +11.1 |
| 0.65-0.70 | 24 | 0.662 | 0.458 | +20.3 |

**Bias by group (P4; our bias, then the market's on the same bets).**

| cut | group (n) | our bias | market bias |
|---|---|---|---|
| market | hits (69) | +5.7 | -2.3 |
| | total bases (78) | +9.6 | +1.2 |
| | runs (2) | +59.0 | +50.0 |
| side | **Over (122)** | **+9.9** [+0.4, +17.8] (P5) | +1.7 |
| | Under (27) | +2.0 [-15.1, +15.6] | -6.3 |
| market x side | hits Over 0.5 (62) | +10.0 | +2.1 |
| | TB Over 0.5 (59) | +9.0 | +0.6 |
| | TB Under 1.5 (19) | +11.5 | +3.1 |
| | hits Under 0.5 (7) | -33.0 | -41.1 |
| price | +100 or longer (26) | -4.3 | -12.7 |
| | -120 to -100 (36) | +9.4 | +1.5 |
| | -140 to -121 (46) | +12.3 | +3.9 |
| | -160 to -141 (41) | +11.5 | +3.2 |
| season_games | 15-19 (39) | -3.6 | -11.9 |
| | 20-24 (51) | +4.3 | -4.0 |
| | 25+ (59) | +20.1 | +11.9 |
| expected_pa_source / lineup_posted | batting_slot, posted (103) | +11.8 | +3.4 |
| | season_average, not posted (46) | +1.1 | -7.0 |
| stored slot | 1-3 (41) | +7.5 | -0.8 |
| | 4-6 (55) | +6.9 | -1.4 |
| | 7-9 (52) | +9.9 | +1.7 |
| home/away | away (79) / home (70) | +8.5 / +8.5 | +0.3 / +0.1 |
| starter throws | L (54) | -7.8 | -15.9 |
| | R (95) | +17.7 | +9.4 |
| starter hit factor (2025+fwd, TUNING-ONLY input) | stingy (49) | +18.8 | +10.7 |
| | middle (46) | +13.4 | +4.9 |
| | hittable (54) | -5.1 | -13.3 |
| entry_class | pick (105) | +12.0 | +3.4 |
| | fill (44) | +0.1 | -7.4 |
| game type | regular (50) | +5.1 | -3.2 |
| | postseason (99) | +10.2 | +1.9 |
| actual PA | <=3 (50) | +14.4 | +6.4 |
| | 4 (69) | +9.7 | +1.3 |
| | 5+ (30) | -4.4 | -12.5 |

**Is the model systematically too high on Overs?** On the published bets, yes: +9.9 points
on 122 Overs (interval clears zero), and our number was 8.2 points above the market on them
(P5). The 27 Unders were also 8.4 points above the market but happened to win at 59%. On the
unselected pool (section 2) the answer is narrower: Overs are too high on total bases over
0.5 and in the postseason, not in general.

Most of the cuts above are within noise at this sample (every subgroup row is 20-100 bets and
the market's own bias swings by 10-40 points across the same rows). Read them for direction,
not size. Two agree with better-powered evidence below: postseason worse than regular season
(as in the pool, X4b), and stingy starters worse than hittable ones (the direction the
starter term in section 3c corrects).

## 2. The full forward candidate pool (selection removed)

Every priced hits, total-bases and runs contract on 34 dates from 2026-09-08 to 2026-10-15
with at least two two-way books, a batter with 40+ prior PA and a box row in that game:
**6,818 contracts** (Q0; 150 more had no box row, i.e. did not play; 21 joined to another
game_pk; refusals by the 40-PA floor and the two-book rule are counted in Q0).

**Model vs market, all contracts, Over side (Q1, Q2).**

| arm | n | Brier | log loss | bias |
|---|---|---|---|---|
| model as the card prices it | 6,818 | 0.2404 | 0.6738 | +0.9 |
| market, last pre-game, de-vigged | 6,818 | 0.2355 | 0.6636 | +0.0 |

Paired, model minus market: **log loss +0.0103 [+0.0061, +0.0147]**, Brier +0.0048 [+0.0029,
+0.0069], 34 date clusters. The model is reliably worse than the market on the unselected
pool.

**By market (Q3).**

| market | n | hit rate | model mean p | model bias [95%] | market bias [95%] | LL model minus market [95%] |
|---|---|---|---|---|---|---|
| hits over 0.5 | 2,072 | 0.599 | 0.604 | +0.5 [-1.9, +3.3] | -0.8 [-3.0, +1.9] | +0.0072 [+0.0033, +0.0112] |
| hits over 1.5 | 204 | 0.358 | 0.259 | -9.9 [-15.7, -2.9] | -1.5 [-7.1, +5.1] | +0.0213 [-0.0036, +0.0440] |
| runs over 0.5 | 2,094 | 0.388 | 0.392 | +0.4 [-2.7, +3.8] | +0.2 [-2.8, +3.4] | +0.0101 [+0.0054, +0.0157] |
| **TB over 0.5** | 1,196 | 0.538 | 0.616 | **+7.8 [+5.2, +11.0]** | +1.4 [-1.2, +4.5] | +0.0147 [+0.0069, +0.0237] |
| TB over 1.5 | 1,247 | 0.413 | 0.391 | -2.2 [-5.4, +1.9] | -0.1 [-3.2, +3.8] | +0.0101 [+0.0026, +0.0172] |

Reliability per market is Q3r. TB over 0.5 is too high in every probability bin (+6.0 to
+11.5 in the populated bins).

**Regular season vs postseason (X4b).**

| games | market | n | hit rate | model bias | market bias | model + starter factor |
|---|---|---|---|---|---|---|
| regular | hits 0.5 | 1,674 | 0.614 | -0.9 | -1.7 | -1.1 |
| regular | TB 0.5 | 905 | 0.550 | +6.7 | +0.7 | +6.3 |
| regular | TB 1.5 | 1,092 | 0.427 | -3.7 | -1.3 | -3.5 |
| regular | runs 0.5 | 1,727 | 0.409 | -1.6 | -1.2 | -1.7 |
| post | hits 0.5 | 398 | 0.535 | +6.3 | +2.9 | +4.9 |
| post | TB 0.5 | 291 | 0.502 | +11.0 | +3.3 | +9.3 |
| post | TB 1.5 | 155 | 0.316 | +8.4 | +8.5 | +7.5 |
| post | runs 0.5 | 367 | 0.289 | +10.1 | +6.6 | +9.0 |

In the regular season the model is calibrated or slightly low on everything except TB over
0.5. In the postseason it is 6-11 points high on everything; the market is also high (3-9),
by less.

**Other pool cuts (Q4, hits / TB 0.5 / TB 1.5).** Home and away identical (within 0.6).
Starter hand: no consistent effect. Slots 7-9 carry the largest misses (+4.1 / +8.2 / -12.0
on hits / TB 0.5 / TB 1.5, n 530 / 480 / 59). Platoon: opposite-hand matchups +3.8 / +11.9 /
-2.1 against same-hand -4.3 / +2.7 / -2.0 on hits / TB 0.5 / TB 1.5 (n 465 to 1,019 per
cell), i.e. the model, which has no platoon term, is too high on the matchups the batter
should like and too low on the ones he should not; that is the opposite of the textbook
platoon edge and is not explained here (flag, not finding). Contracts on batters not in the
stored lineup (36-40 per market, priced off season PA) are 16-30 points high: they mostly did not start (actual PA 2.15 against 3.89 assumed,
D2).

**The selection effect, measured where it can be (Q5).** Both sides of every contract, by
how far the model sits above the market on that side:

| model minus market | n | model p | hit rate | model bias | market p | market bias |
|---|---|---|---|---|---|---|
| more than +10 | 621 | 0.616 | 0.459 | **+15.7** | 0.489 | +3.1 |
| +6 to +10 | 1,419 | 0.580 | 0.482 | **+9.7** | 0.502 | +2.0 |
| +3 to +6 | 1,987 | 0.543 | 0.505 | +3.8 | 0.499 | -0.6 |
| 0 to +3 | 2,791 | 0.512 | 0.481 | +3.1 | 0.497 | +1.6 |
| -3 to 0 | 2,791 | 0.488 | 0.519 | -3.1 | 0.503 | -1.6 |
| -6 to -3 | 1,987 | 0.457 | 0.495 | -3.8 | 0.501 | +0.6 |
| below -6 | 2,040 | 0.409 | 0.525 | -11.6 | 0.502 | -2.3 |

The hit rate follows the market and ignores the model: where we were 10+ points more
confident than the market we hit 45.9%, below the market's 48.9%. The same holds for Overs and
Unders separately (Q5O, Q5U). Emulating the card's gates on the pool at the last pre-game
price (Q6): the 1,716 card-eligible sides carry +4.2 [+1.3, +7.7] model bias and lose 6.2% per
bet flat; the 219 that also pass the value test carry **+13.6 [+7.0, +21.2]** and lose 14.0%
per bet. The value test is a selector of model error.

**Shrink toward the market (X5).** Fitting q = market + lambda x (model - market) by log loss
on the 6,818 contracts: **lambda = -0.20 [-0.43, +0.05]**. Per market: hits 0.5 -0.29, runs
-0.23, TB 0.5 -0.08, TB 1.5 -0.48, hits 1.5 -0.01. The model's disagreement with the market
is worth nothing and probably slightly less than nothing.

## 3. Decomposition

**3a. Expected plate appearances.**

The live V1 slot table is right on average (within 0.15 PA of the 2026 actual in every slot,
0.005 PA over the slot-priced pool); the 2025 frozen table is not (D1).

| slot | V1 table (live) | 2025 frozen | 2024 actual | 2026 forward actual | 2026 share <=3 PA | 2026 share <=2 PA |
|---|---|---|---|---|---|---|
| 1 | 4.467 | 4.155 | 4.476 | 4.413 | 0.078 | 0.017 |
| 2 | 4.444 | 4.045 | 4.375 | 4.301 | 0.088 | 0.030 |
| 3 | 4.326 | 3.947 | 4.278 | 4.249 | 0.081 | 0.016 |
| 4 | 4.234 | 3.842 | 4.184 | 4.169 | 0.089 | 0.016 |
| 5 | 4.105 | 3.662 | 4.053 | 4.008 | 0.155 | 0.042 |
| 6 | 3.919 | 3.513 | 3.924 | 3.901 | 0.207 | 0.053 |
| 7 | 3.753 | 3.325 | 3.774 | 3.700 | 0.321 | 0.077 |
| 8 | 3.623 | 3.161 | 3.613 | 3.484 | 0.433 | 0.130 |
| 9 | 3.461 | 2.872 | 3.451 | 3.391 | 0.501 | 0.144 |

On the 6,672 slot-priced pool contracts, assumed 4.111 PA against 4.116 actual (D2); 6.6% got
more than one PA fewer than assumed and 3.5% two or fewer. In 2024, 4.052 against 4.005.
**The PA level is not a source of bias for posted-lineup starters in the regular season.**
Two places it is:

* **Postseason** (X4): 4.029 assumed against 3.773 actual. A low-offence game turns the lineup
  over fewer times.
* **The published bets** (X3): batting_slot bets assumed 3.993 PA and got 3.709 (+0.284); 35%
  had three or fewer and 10.7% two or fewer. Season-average bets: 3.861 against 3.913. Two
  thirds of the published bets were postseason.

Treating PA as a distribution instead of a point (a prior season's slot distribution) moves
probabilities by 0.0 to -0.6 points in 2024 and 2026 and does not change calibration (D4):
the concavity effect is small. Knowing the actual PA (an ORACLE, not available pre-game)
would cut log loss by 0.026-0.038 nats, more than any other input here, which says the PA
realization is the largest single source of per-bet noise, not of bias.

**Side finding, not a cause of these losses:** the 2025 frozen table sits 0.3-0.6 PA below
both measured seasons in every slot. D1b shows why: the 2025 fit counted 5,389 to 6,311 rows
per slot against 4,054 team-games (1.33 to 1.56 rows per slot per team-game), so substitutes
who inherited a slot were averaged with the starters. If that table were ever wired into the
live board it would lower every number about 3.5 points (D4, "slot table: 2025 frozen").

**3b. The per-PA rate and the short sample.**

The live board's batter history is the forward box store only (it starts 2026-08-30), so the
card priced batters on **15 to 43 prior games** (P0), and 1,989 of the 2,072 hits-0.5 pool
contracts had under 120 prior PA (Q0). With `PA_REGRESSION = 200`, a batter with n PA gets
weight n / (n + 200) on his own rate: 23% at 60 PA, 38% at 120. The question is whether even
that is too much.

Slope of a batter's actual excess hits on his predicted excess (1 = shrinkage exactly right,
below 1 = his own short-sample deviation is over-trusted), D3:

| sample | prior PA under 120 | prior PA 120+ |
|---|---|---|
| 2026 forward pool | 0.43 [-0.31, +1.13], n 1,986 | (n 83) |
| 2024, short-history regime | 0.30 [-0.35, +1.02], n 2,560 | (n 52) |
| 2024, full-history regime | (n 850) | 0.76 [+0.52, +1.00], n 9,720 |
| TUNING-ONLY 2025, short | -0.15 [-0.45, +0.16], n 1,879 | (n 39) |
| TUNING-ONLY 2025, full | (n 268) | 0.88 [+0.67, +1.08], n 7,846 |

With under 120 PA the batter's deviation from league carries little or no predictive
information in any season (point estimates -0.15 to 0.43); with a full season it carries most
of it (0.76-0.88). So yes, **small samples are over-trusted**, but this does not bias the
average: bias by tercile of predicted rate is within 1.6 points in the 2026 pool, 2024-full and
2025-full; the short regimes show -3.3 / 0.0 / +2.8 (2024) and -3.1 / +2.3 / -1.9 (2025),
weak hitters doing better and strong hitters worse than predicted, which is what over-trust
looks like (D3b). Harder shrinkage (400 or 800) barely moves
log loss (D4: within +/-0.002 nats). What over-trust does do is manufacture disagreements with
the market out of noise, and the card selects disagreements. The market prices from full and
multi-season histories; our 20-game rate cannot know more than that. Adding 2025 lines to the
batter history (TUNING-ONLY input) lowers the published side probability by 1.04 points on
average (D5).

**3c. The opponent: no starter term, no postseason term.**

The card calls `price_prop` without `pitcher_hits_allowed`, so the blended starter factor is
always 1.0. Measured effect of adding it:

* On the 2026 pool (D4), from forward-window starter history: 0.0 to -0.4 points on average,
  log loss +0.0009 to +0.0022 better; from 2025 + forward history (TUNING-ONLY input): +0.1
  to -0.7 points, +0.0025 / +0.0059 / +0.0026 nats on hits / TB 0.5 / TB 1.5, the first two
  intervals clear of zero.
* On 2024 full history (D4): +0.0009 to +0.0010 nats, matching
  `TB_STARTER_AWARE_RESULT.md`'s +0.0004 on TB 1.5 in size class.
* On the published bets (D5): -0.94 points (forward history) to **-1.61 points** (2025 +
  forward). The published Overs were concentrated against stingier starters (P4).

The bigger opponent miss is the **postseason**. On postseason hits-0.5 contracts the league
rate the model used was 0.2177 hits per PA and the realized rate **0.1802** (X4); across all
forward box rows, 0.1860 postseason against 0.2190 regular season, a ratio of **0.849** (X0b,
hindsight). Prior seasons (X0, statsapi totals) put the postseason ratio at 0.969 (2023),
0.923 (2024) and 0.930 (2025, TUNING-ONLY), mean **0.941**. Applying that point-in-time
multiplier lowers the published side probability by 1.36 points (D5); applying the realized
2026 ratio instead (ORACLE, hindsight upper bound) lowers it by 3.59 points. 2026's
October offence was low beyond anything the market priced either (market bias +2.9 to +8.5 in
the postseason rows of X4b).

**3d. Total bases over 0.5 is the hits-over-0.5 event priced without the correction.**

`probability_over` routes `batter_total_bases` through `total_bases_distribution`, which is
deliberately not rho-corrected ("calibrated to within about one point" at 1.5). But TB >= 1
is exactly "at least one hit", the event the rho correction was fitted for. On the 1,163
player-games where both contracts were quoted (X1): hits path 0.587, TB path 0.617, market
0.557 and 0.552, hit rate 0.545. **The TB path is +2.95 points above our own hits path on the
identical event.** Routing TB 0.5 through the hits path lowers the TB 0.5 bias from +7.8 to
+4.8 and improves log loss by +0.0075 [+0.0043, +0.0115] (D4). The defect is stable across
seasons (section 4) and the 59 published TB Over 0.5 bets were each 2.98 points too high from
it alone (D5). TB 0.5 lines are posted for weaker hitters lower in the order (X2: 40% in slots
7-9 against 26% for hits 0.5), which is also where the model disagrees most with the market
(+6.4 points mean against +1.2 for hits 0.5), so the card harvested this defect.

**3e. Putting the pieces together on the published bets (D5, X10).** Mean shift of our
side probability, points:

| component | shift on the published side probability |
|---|---|
| TB over 0.5 via the rho-corrected hits path (59 bets) | -2.98 per affected bet; -1.18 averaged over all 149 |
| opposing starter factor (2025 + forward H/BF; TUNING-ONLY input) | -1.61 |
| postseason multiplier 0.941 from 2023-2025 | -1.36 |
| **composite of the three** | **-4.11** |
| ORACLE: realized 2026 postseason ratio 0.849 instead of 0.941 (hindsight) | -3.59 |
| harder shrinkage (PA_REGRESSION 800) | -0.46 |
| 2025 lines added to batter history (TUNING-ONLY input) | -1.04 |
| PA as a distribution | -0.40 |
| rho 0.05885 instead of 0.05065 | -0.17 |
| market at publish to market at the last pre-game quote | +0.19 |

Accounting for the 8.5-point published overestimate: market error on these bets +0.2 (noise
around a calibrated market); structural terms the composite removes about 4.1; the remainder
**about 4.1 points is unexplained disagreement that the selection rule picked**, consistent with
lambda near zero (X10: composite minus market is still +4.1 on the published bets; on the pool
the composite's own lambda is 0.02 and it is still worse than the market by +0.0049 nats
[+0.0017, +0.0079], X9). Fixing the structural terms makes the model less wrong; it does not
make its disagreements informative.

## 4. Out of sample: 2024, and 2025 (TUNING-ONLY)

Same code, same V1 constants, listed starters (2025 has no stored lineups: regulars with 3.5+
prior PA per game, a point-in-time proxy), regular season only (no archive holds October), no
prices (no market comparison is possible). Two regimes: full season-to-date history scored
from Aug 15, and a short history that starts on Aug 28 (the live 2026 store's shape), scored
from Sep 15 with the card's 15-game gate.

| season, regime | hits 0.5 bias [95%] | TB 0.5 bias [95%] | TB 1.5 bias [95%] | n per market |
|---|---|---|---|---|
| 2024 full | -0.3 [-1.3, +0.7] | **+2.7 [+1.7, +3.7]** | +2.3 [+1.1, +3.5] | 10,581 |
| 2024 short | -0.2 [-1.8, +1.2] | **+2.9 [+1.3, +4.3]** | +1.9 [+0.1, +3.6] | 2,612 |
| TUNING-ONLY 2025 full | +0.9 [-0.2, +1.9] | **+3.9 [+2.9, +5.0]** | +1.6 [+0.2, +2.8] | 8,206 |
| TUNING-ONLY 2025 short | -0.4 [-2.7, +2.0] | **+2.7 [+0.4, +5.2]** | +1.5 [-1.1, +3.9] | 1,935 |
| 2026 forward pool, regular season (X4b) | -0.9 | +6.7 | -3.7 | 1,674 / 905 / 1,092 |

(H1; reliability in H2, slots in H3, PA in D1/D2, counterfactuals in D4 for each.)

What is stable: **hits over 0.5 is calibrated** (within a point everywhere); **TB over 0.5 is
2.7 to 3.9 points high in every season and regime**, the size of the missing rho correction
(rho 0 moves hits by +3.1 in every season, D4); TB over 1.5 runs 1.5-2.3 high in 2024/2025.
The short-history regime does not by itself create bias (2024 and 2025 short are within a
point of full). The V1 slot table matches 2024's measured PA within 0.05 on average (D2: 4.052
against 4.005).

What is 2026-specific and therefore not shown to be stable: the postseason excess (cannot be
tested on any archive), the larger TB 0.5 excess in 2026 (+6.7 regular season against +2.7 to
+3.9 before; the 2026 TB 0.5 population is the book's choice of weaker hitters), and the
selection effect (no priced props exist for 2023-2025).

## 5. Conclusions

**The three largest, best-supported sources of estimate error.**

1. **Selecting the model's disagreements with the market: about +4 points on the published
   bets, and the reason the error is so much larger on the card than on the pool.** Evidence:
   pool bias +0.9 against published +8.5; published gap to market +8.2 with -0.2 realized
   (X7); bias rises monotonically with the gap to +15.7 at more than 10 points (Q5); the
   value-test subset carries +13.6 [+7.0, +21.2] (Q6); lambda -0.20 [-0.43, +0.05] (X5);
   after removing the structural terms the residual published gap is still +4.1 (X10). Its
   engine is the 16-29-game batter sample: under 120 PA the batter's own deviation has a
   slope of -0.15 to 0.43 on what happens (D3), while the market prices from far more.
2. **TB over 0.5 priced without the within-game correlation correction: +2.95 points on the
   identical event (X1), +2.7 to +3.9 points of bias in 2024 and 2025 and +7.8 on the 2026
   pool.** About 1.2 points averaged over the published bets, 2.98 on each of the 59 TB Over
   0.5 bets. Best supported of the three: it is a code path, it reproduces in four seasons and
   regimes, and its fix is a measured log-loss gain (+0.0075 [+0.0043, +0.0115], D4).
3. **No opponent and no postseason adjustment: postseason pool bias +6.3 to +11.0 points
   against -3.7 to +6.7 in the regular season (X4b).** Point-in-time fixes recover about 3 of
   it on the published bets (starter -1.61, prior-season postseason ratio -1.36, D5); the
   2026 postseason's realized hit rate (0.180 per PA against 0.218 used) was lower than prior
   seasons predict, and the market missed it too.

**What the data does NOT support.**

* That the expected-PA level is wrong for posted starters: V1's slot table is within 0.15 PA
  of the 2026 actual in every slot, 0.005 PA on average over the pool, and matches 2024 (D1,
  D2). PA is the largest source of
  per-bet noise (ORACLE gain about 0.03 nats), not of bias, outside the postseason.
* That the per-PA shrinkage constant is the fix: 100 / 400 / 800 move log loss by under
  0.003 nats (D4).
* A general Over bias: in the regular-season pool, hits, TB 1.5 and runs Overs are calibrated
  or low (X4b); the Over excess is TB 0.5 and the postseason.
* Any home/away or starter-handedness effect (Q4, H3b). The platoon cut points the wrong way
  and is a flag for later, not a finding.
* Using `evidence/decisions_v2.jsonl` to score the prop model: it has no prop rows and no real
  model number (P-1).
* That the structural fixes would make the card profitable. The composite is still worse than
  the market (+0.0049 nats, X9) with lambda 0.02.

**What a corrected estimate would have said about the published bets (S1, X10).
RETROSPECTIVE, fitted after the outcomes, not a promise.** Expected units on the same 149 bets
at the prices taken (realized -6.25 units, hit rate 0.523 against mean breakeven 0.552):

| estimate | mean p | expected units | bets with expected value above zero |
|---|---|---|---|
| raw our_probability (what was shown) | 0.608 | +15.44 | 148 |
| our_probability_used (minus 0.038) | 0.570 | +5.10 | 142 |
| structural composite (X10) | 0.567 | +4.25 | n/a |
| market only (lambda 0) | 0.526 | -7.00 | 0 |
| shrunk to market, lambda -0.20 fitted on the forward pool | 0.509 | -11.49 | 0 |

At the market's own number, not one of the 149 bets had positive expected value (the G13
no-line-shopping gate requires the price to be no better than the market's fair number, so
this is by construction); the 0.038 markdown removed 3.8 of the 8.5 points of overstatement;
and the realized -6.25 units is close to the -7.00 the market's own probabilities imply at
these prices. The losses are what the market expected; our number is what was wrong.

## Limits

* Published sample: 149 bets on 20 dates. Subgroup tables in section 1 are directional only.
* Forward pool: 6,818 contracts on 34 dates, 16 of them postseason. Postseason findings rest
  on 398 / 291 / 155 / 367 contracts per market and one October.
* The pool uses the last pre-game quote; the card bet earlier quotes. On the published bets
  the market moved +0.19 points toward us between publish and the last pre-game quote (D5),
  so this choice does not flatter the market. Closing-line value is reported elsewhere
  (`docs/SURVIVAL_DASHBOARD.md`, about -3.5 on props) on a different definition.
* Two hindsights (posted lineup, first-pitch starter) favour the model, not the market.
* 2023-2025 have no prices and no October; selection and postseason cannot be tested out of
  sample from local stores. 2025 has no lineups.
* The starter factor and the postseason multiplier are the model's own bounded constructions
  (`pitcher_hit_factor`, a flat 0.941); no other opponent model was tried.
* The platoon cut (Q4) and the hits-over-1.5 under-prediction (-9.9 on 204 contracts) were
  noticed, not investigated.
* Nothing here is a pre-registered test; no hypothesis was promoted and none should be on this
  evidence. Any fix proposed from it needs its own registration and a forward test.

## Reproduce

```
python3 scripts/diagnosis/estimate_error.py --part all          # everything, about 5 minutes
python3 scripts/diagnosis/estimate_error.py --part published    # section 1 only
python3 scripts/diagnosis/estimate_error.py --part pool         # sections 1-3 and 5
python3 scripts/diagnosis/estimate_error.py --part hist --season 2024
```
