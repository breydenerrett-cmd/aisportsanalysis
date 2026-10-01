# Loss diagnosis, 2026-10-01

Read-only audit by a separate worker of every ledger on origin's working branch at `64c39a9`. Scripts and their outputs are in `perf/` beside this file (run each with `python <script>`; they expect `data/` and `repo/` exports made with `git show` / `git archive`, which are not committed). Nothing here was tuned on the sealed 2026-01-01..08-27 window.

## What this changes (orchestrator's reading)

- **Product claim.** No rule has shown positive expected value, and our number is not better than the market's. The sellable thing is the public, pre-game, graded record and the price comparison, never 'winning picks'.
- **The MAIN-pick loss is one day.** 19 of 33 staked picks are 2026-09-22 (the cap breach): -5.14u. The other three dates net +0.09u.
- **The V2 value gate (G7) is the research question.** Entries that pass it did worse than entries that fail it (z -1.43 in shadow A; picks vs fills z -1.91). That is a hypothesis for a pre-registered test on forward data, not a reason to change the gate now: no threshold moves on this evidence.
- **Nothing left in line shopping.** The frozen price was already the best on the board every time it could be checked.

## Open items raised by the audit

- Already on record, not new: V1's moneyline calibration was fitted on games inside the sealed window (1,753 of the 1,901 rows it selects) and refit nightly until the owner froze it on 2026-09-15. `docs/PREREG_CARD_V2.md` sections 1.1 and 1.2 say so and conclude the sealed rule was already broken by V1; V2 reads no number from that file. Consequence for reading this audit: V1's record is not clean forward evidence.
- Game 824785 (TOR@BAL, postponed 09-22, played 09-23) is a permanent VOID in two shadow ledgers under the old rule. Correction is append-only and shadows only; not yet made.
- Game 823490 (BAL@NYY, 09-27): no result in the stores; one public fill is VOID on it.
- `batter_runs_scored` had no settlement rule (22 VOIDs). Rule added in `4ebaaed2`; the old VOID rows stand.
- NFL picks freeze no `model_probability` and no `observed_utc`, so NFL calibration and CLV cannot be measured.
- UFC: 7 picks published, none settled.

---

## Quantitative audit of every ledger on origin/claude/sports-betting-analysis-review-g1o0co @ 64c39a9 (2026-10-01 18:13Z)

**Bottom line:**
- **No rule has shown positive expected value.**
- **The public V2 card is not losing overall.** Picks plus fills shown to readers went 41-27, +3.46u (+5.1%), or +5.14u counting withdrawn entries.
- **What lost is the "MAIN pick" class only:** 16-17, −5.05u on 33 staked.
  - 19 of those 33 come from 2026-09-22, the day the 10-entry cap was breached. That day alone is −5.14u; the other three days net +0.09u.
  - V2 has published zero picks since 09-26. Every entry since then is a fill, so the MAIN record is frozen at 4 dates.

I edited nothing in the repo and ran nothing in it. Data came from origin via `git show` / `git archive` into the scratch folder (paths at the end). No tuning used the sealed 2026-01-01..08-27 window.

### Goal 1 — Record table (newest settled row per date; no correction rows exist; no date was settled more than once)

Abbreviations:
- **Rules:** V1-GAME = DAILY_CARD_MARKET_SIDE_MODEL_AGREEMENT_V1; V1-PROP = DAILY_CARD_PROP_LIKELY_AND_CLEARS_PRICE_V1; V2-shA/C/E = the V2 shadows.
- **Entry class:** SPLIT = V1's demoted "fill" entries.
- **Columns:** mBE = mean break-even probability implied by the price (vig included). mMkt = de-vigged market probability frozen on the entry. mOur = our probability (V2: after the 0.038 markdown; MVS: the fair price from other books). WR = W/(W+L).
- **Units/ROI:** flat 1u stakes; ROI = units/(W+L); pushes and voids are not staked.

```
RULE        SP  MKT       VIS  ENTRY   BAND       DATES        N   W   L  P  V  U   UNITS   ROI%   mPx  mBE   mMkt  mOur  WR
V1-GAME     mlb ML        PUB  pick    <=-160     09-10..09-22 46  35  11 0  0  0   +7.00  +15.2  -192 .659  .642  .576  .761
V1-GAME     mlb ML        PUB  pick    -159..-100 09-10..09-22 58  34  24 0  0  0   +2.71   +4.7  -129 .565  .554  .535  .586
V1-GAME     mlb ML        PUB  pick    ALL        09-10..09-22 104 69  35 0  0  0   +9.71   +9.3  -151 .607  .593  .553  .663
V1-GAME     mlb ML        PUB  SPLIT   ALL        09-12..09-21 8   3   5  0  0  0   -2.77  -34.6  -123 .553  .542  .478  .375
V1-GAME     mlb run_line  PUB  pick    ALL        09-10       1   1   0  0  0  0   +0.67  +67.1  -149 .598  .579  .545 1.000
V1-PROP     mlb hits      PUB  pick    <=-160     09-14..09-22 70  44  26 0  0  0   -6.54   -9.3  -225 .694  .657  .729  .629
V1-PROP     mlb hits      PUB  pick    ALL        09-14..09-22 71  45  26 0  0  0   -5.84   -8.2  -223 .692  .655  .728  .634
V1-PROP     mlb TB        PUB  pick    <=-160     09-14..09-22 35  25   9 0  1  0   +4.86  +14.3  -179 .642  .607  .663  .735
V1-PROP     mlb TB        PUB  pick    -159..-100 09-14..09-21 12   8   4 0  0  0   +1.35  +11.3  -147 .596  .566  .624  .667
V1-PROP     mlb TB        PUB  pick    ALL        09-14..09-22 47  33  13 0  1  0   +6.21  +13.5  -170 .630  .597  .653  .717
V1-GAME     mlb ML        SHAD pick    <=-160     09-23..09-29 23  14   9 0  0  0   -1.94   -8.4  -193 .660  .646  .579  .609
V1-GAME     mlb ML        SHAD pick    -159..-100 09-23..09-30 20  15   5 0  0  0   +6.22  +31.1  -132 .571  .560  .549  .750
V1-GAME     mlb ML        SHAD pick    ALL        09-23..09-30 43  29  14 0  0  0   +4.27   +9.9  -159 .619  .606  .565  .674
V1-GAME     mlb ML        SHAD SPLIT   ALL        09-23..09-30 6   3   3  0  0  0   -0.70  -11.6  -126 .560  .548  .477  .500
V1-PROP     mlb hits      SHAD pick    ALL(<=-160)09-23..09-30 67  42  24 0  1  0   -4.05   -6.1  -209 .679  .643  .708  .636
V1-PROP     mlb TB        SHAD pick    ALL        09-23..09-27 27  15  11 0  1  0   -2.78  -10.7  -178 .641  .604  .666  .577
V2          mlb hits      PUB  pick    MAIN       09-22..09-25 15   7   8 0  0  0   -2.85  -19.0  -136 .576  .554  .598  .467
V2          mlb hits      PUB  pick    +100..+250 09-25        1   0   0  0  1  0    0.00     -     -    -     -     -     -
V2          mlb TB        PUB  pick    MAIN       09-22..09-25 16   7   8 0  1  0   -2.89  -19.3  -135 .575  .545  .595  .467
V2          mlb runs_scr  PUB  pick    MAIN       09-22..09-24 3   0   0  0  3  0    0.00     -     -    -     -     -     -
V2          mlb ML        PUB  pick    MAIN       09-23..09-25 3   2   1  0  0  0   +0.70  +23.2  -122 .549  .543  .570  .667
V2          mlb hits      PUB  fill    MAIN       09-25..09-30 4   1   2  0  1  0   -1.30  -43.2  -130 .565  .535  .576  .333
V2          mlb TB        PUB  fill    MAIN       09-22..09-30 16  12   4 0  0  0   +4.58  +28.7  -142 .587  .555  .595  .750
V2          mlb runs_scr  PUB  fill    MAIN       09-26        1   0   0  0  1  0    0.00     -     -    -     -     -     -
V2          mlb ML        PUB  fill    MAIN       09-23..09-30 17  12   4 0  1  0   +5.22  +32.6  -131 .567  .556  .516  .750
V2          mlb hits      PUB  withdrn ALL        09-23..09-27 2   2   0  0  0  0   +2.02 +101.0   101 .502  .479  .515 1.000
V2          mlb TB        PUB  withdrn ALL        09-23..09-24 3   1   1  0  1  0   -0.34  -17.1  -143 .589  .557  .611  .500
V2-shA      mlb TB        SHAD pick    ALL        09-22..09-30 75  45  26 0  4  0   +7.25  +10.2  -134 .575  .544  .600  .634
V2-shA      mlb hits      SHAD pick    ALL        09-22..09-27 16   9   4 0  3  0   +2.87  +22.1  -124 .559  .537  .583  .692
V2-shA      mlb runs_scr  SHAD pick    ALL        09-22        6   0   0  0  6  0    0.00     -     -    -     -     -     -
V2-shA      mlb ML        SHAD pick    ALL        09-22..09-30 20  13   6 0  1  0   +4.76  +25.0  -123 .552  .542  .500  .684
V2-shA      mlb ML        SHAD withdrn ALL        09-29..09-30 4   3   1  0  0  0   +1.38  +34.4  -125 .556  .546  .497  .750
V2-shA      mlb hits      SHAD fill    ALL        09-22        1   0   1  0  0  0   -1.00 -100.0   105 .488  .465  .561  .000
V2-shC      mlb hits/TB/ML SHAD pick   ALL        09-22..09-25 26* 13  13 0  3  0   -3.18  -12.2  -133  (hits 6-6 -1.50; TB 6-6 -1.53; ML 1-1 -0.15; runs 3 VOID)
V2-shC      mlb hits/TB/ML SHAD fill   ALL        09-22..09-30 39* 29  10 0  5  0  +11.78  +30.2  -132  (TB 13-4 +5.59; ML 14-4 +6.83; hits 2-2 -0.63; runs 2 VOID)
V2-shC      mlb hits/TB/ML SHAD withdrn ALL       09-23..09-27 4   3   1  0  0  0   +1.87          (hits 2-0 +2.02; ML 1-0 +0.85; TB 0-1 -1.00)
V2-shE      mlb hits/TB   SHAD pick    ALL(-160)  09-22..09-26 17*  9   8 0  6  0   -2.38  -14.0  -160  (all 6 runs_scored VOID)
V2-shE      mlb hits/TB/ML SHAD fill   ALL        09-22..09-27 17* 13   4 0  5  0   +5.55  +32.6  -132  (hits +100..+250: 3-2 +1.30)
V2-shE      mlb TB        SHAD withdrn ALL        09-23..09-27 2   0   0  0  2  0    0.00
NFL_CARD_V1 nfl ML        PUB  pick    <=-160     09-17..09-21 9   6   3  0  0  0   -0.93  -10.4  -309 .761  .739   -    .667
NFL_CARD_V1 nfl ML        PUB  pick    ALL        09-17..09-21 10  7   3  0  0  0   -0.26   -2.6  -279 .745  .723   -    .700
NFL_CARD_V2 nfl ML        PUB  pick    ALL        09-27        1   1   0  0  0  0   +0.93  +92.6  -108 .519  .583   -   1.000
UFC_CARD_V1 mma -         PUB  -       -          09-22,09-26  published only (2+5 picks), ZERO settled rows
MVS-B_HITS  mlb hits      SHAD decis.  ALL        09-22..09-26 17  8   9  0  0  0   -0.95   -5.6   104 .496   -    .510  .471
MVS-C_RL    mlb run_line  SHAD decis.  ALL        09-25..09-26 5   3   2  0  0  0   +0.53  +10.6  -122 .554   -    .567  .600
MVS-A_TB    mlb TB        SHAD decis.  ALL        09-26        1   1   0  0  0  0   +1.40 +140.0   140 .417   -    .429 1.000
LIVE starter_pulled_early ML-inplay SHAD cand ALL 09-22..09-30 62  19  43 0  0  0  -11.48  -18.5   191 .381   (53 at +100..+250: 14-39 -16.24)
LIVE favorite_trails_after_3 ML-inplay SHAD cand ALL 09-22..09-25 6 3 3 0  0  0   -0.01   -0.2   127 .452
(* N includes VOIDs; all live candidates have customer_eligible=False; MVS D_GAME_TOTAL has scans only, no decisions)
```

**Paper accounts** (newest row per bet_id; every system kept separate; band rows are in `out_record_table.txt`):

```
CONTROL           trivial_always_home          h2h     372 st 204-168 P0 V15  +4.27u  +1.1%  mPx -110
                  trivial_always_home_spread   spreads  47 st  15-32         -6.69u -14.2%  mPx +175
                  trivial_under_total          totals  423 st 188-235 P16 V15 -61.91u -14.6%
MARKET_REFERENCE  mdc_totals_over              totals  380 st 219-161 P8 V15 +44.09u +11.6%
                  mdc_totals_under             totals  405 st 177-228 P15 V15 -65.05u -16.1%
                  mdc_h2h_home / _away         h2h     332 st each: +6.68u (+2.0%) / -27.05u (-8.1%)
                  mdc_spreads_away / _home     spreads  47 st each: +1.43u / -6.69u
                  mdc_h2h_1st_5_away / _home   F5 ML    36 st each (P11): +1.13u / -2.50u
FORWARD_TEST      45 systems (all h2h or F5 h2h); 28/45 have positive units; of the 23 with >=30 staked, 13 are positive.
                  Best: e7f41ed66082c279 96 st 56-40 +12.31u +12.8% (units/sqrt(n) about 1.3). Worst: 55b224b73474abec 40 st -6.93u -17.3%.
```

Two data anomalies in this section:
- 38 control rows are dated 2023-04-18 (19 in trivial_always_home, 19 in trivial_under_total).
- The over/under mirror (+44u vs −65u) reflects a high-scoring stretch from 09-05 to 09-30, not a rule edge.

### Goal 2 — Why is V2 losing? (verdicts, with n)

**(a) Calibration — supported as a contributor.**
- **V2 MAIN picks (n=33):**
  - Our raw number averaged 0.632 (0.594 after markdown). The realised win rate was 0.485; the market said 0.549.
  - Brier score: ours 0.2624 (raw 0.2721) vs market 0.2522. The difference is +0.0102 ± 0.0083, about 1.2 SE. Log loss: 0.7184 / 0.7391 vs 0.6975.
- **Other populations:**
  - **V1 hits props (n=71):** we said 0.728, they won 0.634, the market said 0.655. When we said 0.75 or higher, they won 0.500 (n=22, −6.46u).
  - **V1 games (n=105):** we said 0.553, they won 0.667, the market said 0.593. Brier ours 0.2306 vs market 0.2231.
- **Overall:** our number scored worse than or equal to the market in 12 of 16 populations, and was never significantly better.
- **Does disagreeing with the market predict anything?** I regressed (win − market) on (our raw − market). The slope is never positive and significant:

  | Population | n | Slope | SE |
  |---|---|---|---|
  | V2 MAIN | 33 | −10.2 | 8.3 |
  | V2 shadow A | 103 | −0.61 | 0.86 |
  | V1 hits | 71 | −2.15 | 1.91 |
  | V1 TB | 46 | −3.61 | 3.20 |
  | V1 games | 105 | +0.50 | 1.07 |

- **NFL:** model_probability is null on all 11 picks, so our calibration cannot be tested. The market said 0.723 vs realised 0.700 (V1, n=10).

**(b) Price / vig — real, but small relative to the loss.**
- **V2 MAIN (n=33):**
  - Mean hold paid is +2.45 points (min +0.20). Gate G13 forbids any price better than the de-vigged consensus, so hold is always at least zero.
  - At the fair (no-vig) price the picks would have made −3.92u instead of −5.05u. Vig accounts for 1.13u of the loss.
  - Expected units if the market is right: −1.40u (−4.3% per bet).
- **Shopping is already maxed:** the frozen price was the best book on the board at the freeze instant for 104/104 V1 games and 2/2 V2 MAIN game picks (none worse). There is nothing left to gain from better line shopping.
- **Expected units per bet if the market is right:** V1 games −2.2%, V1 props −5.3%, V2 fills −3.8%.

**(c) CLV — contradicts any edge; there is no closing price for the V2 MAIN props.**
I used card_clv.measure_pick read-only. It defines CLV as p_close (de-vigged) minus the break-even of the frozen price. "Drift" is p_close minus the frozen market probability, i.e. the line move with vig removed.

| Segment | n measured | Mean CLV (pts) | Beat close | Drift (pts) | Notes |
|---|---|---|---|---|---|
| V1 games | 51 of 105 | −1.21 (se 0.18) | 14% | +0.11 | 52 CLOSE_STALE, 2 thin board |
| V1 shadow games | 32 | −1.23 | 3% | — | |
| V2 MAIN games | 2 of 3 | −1.86 | — | — | too few |
| V2 fills, games | 11 | −0.82 | 18% | +0.46 | |
| Shadow A, games | 16 | −0.44 | 31% | +0.58 | |
| Shadow C fills, games | 12 | −0.42 | — | +0.83 | |
| NFL (team-name join) | 3 of 11 | −0.88, −2.69, −3.39 | — | — | 8 stale; NFL freezes no observed_utc |

- **V2 MAIN props (34):** no close exists. For 33 of them, the decision board *is* the last pre-game prop capture in the store.
- **Prop close, relaxed method** (not the project metric: card_clv refuses props; median 3–6 books):

  | Segment | n | CLV (pts) | Beat | Drift (pts) |
  |---|---|---|---|---|
  | V1 hits | 14 | −3.63 | 0% | −0.05 |
  | V1 TB | 15 | −3.50 | 0% | −0.19 |
  | V2 fills props | 11 | −1.71 | — | +1.29 |
  | Shadow A props | 28 | −2.06 | — | +0.89 |

- No segment has positive mean CLV. Drift is about zero for V1, which means V1's CLV is roughly just the hold it paid.

**(d) Staleness — cannot decide.**
- V2 MAIN: price age at first pitch has a median of 96 minutes; quote age at lock has a median of 14 minutes. Fresh half −8.7% ROI (n=17) vs stale half −22.3% (n=16).
- Other populations point the opposite way:
  - V1 games: fresh +5.1% (n=54) vs stale +15.0% (n=51).
  - V2 fills: +6.6% vs +43.1%.
  - V1 shadow hits: −20.4% vs +10.0%.
- CLV per hour of price age is about zero (−0.03, −0.007, −0.095).
- Fills that failed the stale-price gate (G3) went 8-1, +4.86u.

**(e) Selection — the strongest structural explanation (moderate support).**
- **What changed:**
  - V1 bet the market favourite when our model agreed, ranked by market confidence, with no price cap. Props were "likely and clears price".
  - V2 adds:
    - a price band of −160 to +250;
    - a 0.038 markdown on our number;
    - a required edge of 0.010 × d/d(−160), where d = decimal odds;
    - floors of 0.50;
    - a disagreement cap of 0.10;
    - G13 (no price better than consensus);
    - a 10-entry cap counting fills;
    - fills that may fail only G3/G7.
- **Population shift:**
  - V1 public (230 staked): 100% favourites, 0% plus-money, 51% props, mean −170, 65% priced at −160 or shorter.
  - V2 picks (33): 100% favourites, 0% plus-money staked, 91% props, mean −134, 0% at −160 or shorter.
- **V1's record:**
  - 151-79 at mean −170 needed a 0.636 win rate; it won 0.657, giving +7.98u (+3.5%).
  - If the market's de-vigged numbers were right, V1 would have made −8.74u. The difference (+16.7u) is outcomes beating the market's own probabilities.
  - It is concentrated in heavy-favourite games: −160 or shorter went 35-11 vs 29.5 expected wins (z +1.68), +7.00u vs −1.14u expected.
  - Games at −159..−100 (picks + SPLIT) were +0.61u (z +0.24). Props won exactly at break-even (z −0.03).
  - So yes: V1's "good" record is mostly heavy favourites outrunning their market-implied rate.
- **V2's value test picks the wrong entries.**
  - Inside shadow A (n=103), entries that pass V2's value test (G7) went 32-23, +3.2%. Entries that fail it went 35-13, +27.3%. On win − market the difference is −0.133 (se 0.093, z −1.43).
  - V2 public picks vs fills on win − market: −0.064 vs +0.160 (z −1.91).
  - In other words, the gate that admits the largest our-vs-market gaps selects the worse outcomes.

**(f) Variance — fully sufficient on its own.**
- V2 MAIN: 33 staked, 16-17, −5.05u, −15.3% ROI.
- Bootstrap over dates: 95% interval [−24.6%, +4.2%]. This is degenerate because there are only 4 dates. Bootstrap over picks: [−46.2%, +15.7%].
- Probability of doing this badly or worse:
  - if true ROI were 0: 0.165;
  - if true ROI were −4.5%: 0.247.
- The result is −1.02 SD from zero-EV.

**(g) Settlement / data bugs — no grading errors. One V2 market cannot be graded, but it is not the cause of the loss.**
- **Re-grading:** 227/227 MLB game entries re-graded against mlb_results.csv / linescores: 0 mismatches. 427 props re-graded against boxscores_2026: 0 mismatches. I spot-checked 10 games against the CSV: all OK, teams match, none graded against the wrong game.
- **Unresolved:** zero in every ledger. 10-01 is not yet settled.
- **batter_runs_scored:** all 22 entries across ledgers are VOID with "no settlement rule for market 'batter_runs_scored'". V2 publishes a market it cannot grade.
  - The 4 public ones would have graded W, W, L for the picks (+0.48u) and W for the fill (+0.65u).
- **Wrong permanent VOID (shadows only):** game 824785 TOR@BAL was postponed from 09-22 and played 09-23 (BAL won 4-2). It was graded VOID ("no final score stored") under the old rule. Shadow A's BAL −117 pick would have WON, and shadow E's Dylan Beavers Over 0.5 hits fill would have WON (h=1).
- **V2 public 09-27 fill (BAL@NYY 823490):** VOID; no result exists in origin's stores, so I can't tell what it should be.
- **Other VOIDs:** "no box score found for player" (did not play) — 1 V1 public, 4 V2 public.

**(h) Props vs games.**
- V1 props went 78-39 (66.7%) at mean −199, which needs 66.8% to break even, so units are +0.38. The average win pays only 0.505u.
- Hits: 45-26 at −223 (break-even 69.2%), −5.84u; 55 of 71 were Under 1.5. Total bases: 33-13 at −170 (break-even 63.0%), +6.21u.
- Prop hold is 3.4–3.7 points, typically on 2–4 books.
- Calibration:
  - **Hits:** we said 0.728, realised 0.634, market 0.655. Brier 0.2461 vs 0.2329.
  - **TB:** we said 0.653, realised 0.717, market 0.597. Brier 0.2062 vs 0.2131, our only win.
  - **The TB win did not persist:** in the V1 shadow, TB went 15-11, −2.78u (Brier 0.2457 vs 0.2394).

### Goal 3

**(i) Has any rule demonstrated positive expected value? No.**
- Every CLV measurement is negative: V1 games −1.21 pts (n=51), V2 game fills −0.82 (n=11), shadow A games −0.44 (n=16), relaxed prop close −1.7 to −4.5.
- Expected units if the market is right are negative for every card population.
- The positive totals do not show an edge:
  - V1 +7.98u: z +1.42 vs the market's own probabilities.
  - Shadow A +14.87u: z +2.20, with games CLV −0.44.
  - Shadow C fills +11.78u: z +2.44.
  - Market-reference totals-over +44u: its mirror is −65u.
- These come from about 20 overlapping populations over 8–13 dates. The best of 45 forward-test systems is z about 1.3.

**(ii) Which market shows the best calibration and CLV? The market's own number, everywhere.**
- Our number beat the market's Brier only on V1 public total bases (0.2062 vs 0.2131, n=46), and that reversed in the shadow (n=26).
- The least-bad CLV is the MLB moneyline in the V2 shadows and fills: shadow A −0.44 pts with 31% beating the close (n=16), shadow C fills −0.42 (n=12). Compare V1 moneyline −1.21 and props about −3.5. None is positive.

**(iii) Single most likely reason the public card is losing — medium confidence.**
- Only the MAIN-pick class is losing (−5.05u). The cause is a negative-expectation structure plus ordinary variance concentrated on 09-22.
- The structure has two parts:
  - G13 guarantees positive hold: about −4.3% per bet, roughly −1.40u.
  - The value test admits the largest our-vs-market gaps, which on this ledger predict worse outcomes: z −1.43 in shadow A, z −1.91 for picks vs fills. On MAIN picks our raw 0.632 vs realised 0.485 vs market 0.549.
- The remaining −3.64u is a 2.1-win shortfall vs the market (z −0.74).
- It is not a settlement bug: re-grading found 0 errors, and the runs-scored VOIDs would have added only +0.48u.

### Side observation (resolved above: already recorded in PREREG_CARD_V2 1.1 and 1.2)
`data/processed/card_calibration.json` (V1's calibration) says season 2026, fitted through 2026-09-14, n=1911 games. On its face that spans the sealed 2026-01-01..08-27 window. The daily_card.py docstring also cites a backtest on 1,896 games of 2026.
