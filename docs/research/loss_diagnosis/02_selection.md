# Loss diagnosis 02: what is guiding selection, and is the rule the problem?

Agent 2 of 3. Written 2026-10-16. Every number below comes from
`scripts/diagnosis/selection.py`; outputs are in `data/research/loss_diagnosis/`.
Everything is **retrospective**. Any rule change evaluated here is **HINDSIGHT**,
labelled so, and licenses only a forward test.

## TL;DR

- **What the rule optimises.** Out of every candidate that passes the gates, it
  takes the one where our number is furthest above the market's. The score is a
  Kelly fraction on our number minus 3.8 points, at the best price. Across 853
  candidates that could have been published, its correlation with
  model-minus-market (`mm`) is **0.98**. The gates hold `mm` between about 5
  and 10 points, so the rule pushes picks up against the 10-point disagreement
  cap: **83 of 110 picks sit at 8 to 10 points.**
- **Winner's curse: confirmed.** Our gap carries no positive information. The
  shrinkage factor that maps our gap onto results (blend weight on our number) is
  **k = -0.20 (95% date-clustered CI -0.45 to +0.06)** on 6,818 prop contracts
  (2026-09-08..10-15), **-0.33 (-0.72 to +0.07)** on 2,595 replayed card
  candidates, and **-0.01 (-0.32 to +0.29)** on 4,066 moneyline sides in 2024
  (model rebuilt point in time with the frozen 2025 numbers). Our log-loss is
  worse than the market's in both (props +0.0103 nats, 2024 moneylines
  +0.0078), and the best blend weight on our number is 0.0 in both. The 8-10
  and >10 point buckets hit about **4 points below the market**.
- **Picks vs fills is luck plus that 4 points.** Fills are not cheaper. Fills
  average -127, picks -78, and the vig at market odds is -3.9% per fill against
  -4.5% per pick. At market odds the fills should have lost 2.6u and they won
  7.9u, so they ran +10.5u above expectation. The picks ran -4.3u below
  expectation. Permutation p is 0.15 unstratified and 0.30 stratified by date.
  In a regression on `mm` and price, the pick/fill dummy is -0.12 (CI -0.34 to
  +0.10).
- **The vig.** Expected result at the market's own number: **-7.55u on 178
  bets (-4.2% per bet)**. Realised: **-1.42u**. The card ran 6.1u *luckier*
  than the market expects, and it still lost money. With no information in our
  number, the expected loss is set by bets per day times vig, whatever the
  ranking.
- **Smallest pre-registerable changes** (section 7): (1) fix the blend weight on
  our number at the measured k (about 0). That ends "value" picks, because no
  candidate can clear break-even. (2) Cap volume at 3 a day as a loss limiter,
  not an edge. (3) Lower G8 to 0.08, which drops the 8-10 point band where the
  pool hits 4 points below the market. (4) Grade at the average of the books'
  prices, as the owner ruled (props: -9.65u at the average against -6.25u at the
  best price).

## 0. The record being diagnosed, reproduced

`history_v2(path="evidence/cards_v2.jsonl")`, every graded WIN/LOSS entry,
2026-09-22..2026-10-15 (21 settled days).

| set | n | W-L | hit | market p | units | expected units at market |
|---|---:|---:|---:|---:|---:|---:|
| all graded entries (the brief's 97-81) | 178 | 97-81 | 0.545 | 0.530 | **-1.42** | -7.55 |
| excluding the 17 withdrawn-then-graded picks (= `record_v2`) | 161 | 86-75 | 0.534 | 0.534 | -6.43 | -6.85 |
| picks, shown | 93 | 43-50 | 0.462 | 0.525 | -14.27 | -4.22 |
| picks, withdrawn but graded | 17 | 11-6 | 0.647 | 0.496 | +5.01 | -0.70 |
| fills | 68 | 43-25 | 0.632 | 0.547 | +7.85 | -2.63 |

**Observation.** The brief's 97-81 / -1.4u counts the 17 picks that were
withdrawn and then still graded. `record_v2`, the public reader, leaves them
out. On that basis the card is 86-75, -6.43u, and the picks are 43-50,
-14.27u. Both are reported below. Unless a table says otherwise it uses all
178.

Reproduce: `python3 scripts/diagnosis/selection.py ledger` (writes `selection_ledger.json`).

## 1. The pipeline, end to end, on three real dates

### What the code does, in order

1. **Candidates.** For props, `props.board_for_date(limit=200)` runs
   `propboard.build`, which takes the newest quote per book, the mean de-vigged
   probability over books quoting both sides, and the **best** price across
   books. `most_likely` then keeps the side where our number is above 0.50,
   sorts by our number, and keeps the top 200. For moneylines,
   `daily_card.build_pick_candidates` builds **only the market-favoured side**
   (`_consensus_side`), even though the registration says "both sides". So every
   game candidate is a favourite and the plus-money moneyline class cannot
   fire. `card_v2_enum_shadow.py` documents the same thing.
2. **Gates** (`best_bets_card.failed_gates`): G1 started, G2 books (6 for a
   game, 2 for a prop), G3 quote older than 3,600 s, G4 band (-160..-100 or
   +100..+250), G5 market band, G6 our floor, G7 value test
   (`our - 0.038 >= breakeven + 0.010 * d/1.625`), G8 `|our - market| <= 0.10`,
   G9 calibrated, G10 season games >= 15, G13 `market <= breakeven` (a price
   better than fair is refused).
3. **Score** on the survivors: `p - (1-p)/(d-1)` with `p = our - 0.038`.
   **Ranking key = score**, then smaller disagreement, more books, earlier
   first pitch, then the sentence.
4. G11 dedup (one entry per game or player), G14 (at most 3 plus-money
   picks), G12 (10 entries per day, picks and fills together).
5. **Fills to a floor of 3** come from close calls, meaning candidates that
   fail only G3 and/or G7, ordered by fewest failures, then smallest shortfall
   against the value bar, then score.
6. The ledger (`publish_v2`) locks each entry 4 hours before first pitch, as
   last published. A fresh read that fails a gate withdraws the entry, but it
   is still graded.

The full prop path was **replayed from local stores at every one of the 175
actual publish instants**, through the registered functions unchanged. The
replay reproduces **100% of the ledger's prop close-call identities, 78% to
the exact price and number** (2,579 of 3,327). For first-shown entries it is
127 of 169 exact, and all 127 of those land in the same pick/fill class. The
inexact rows differ by a quote or by a lineup slot whose posting time the
watch log brackets only roughly. (`selection_pool.json` -> `validation_vs_ledger`.)

### Date traces (`python3 scripts/diagnosis/selection.py trace`)

**Losing day, 2026-10-05: 3-8, -5.48u.** There were 7 publish runs. The
replayed prop pool was 89 candidates, 43 on the evening runs. Gate failures
summed over all runs: G7 430, G5 282, G3 265, G4 256, G6 256, G10 42, G8 70.
Runs 1-2 (04:09Z, 04:23Z) passed 3 props, all at `mm` 9.3-9.7. At 05:15Z
every candidate failed G3, so the whole board was stale, yet the ledger
recorded `stale_board: None` (see 6.3). At 17:13Z G3 was still failing and
one G3-only fill was added. At 19:22Z and 22:13Z new picks passed and the
card grew to 7 picks and 3 fills. Every pick was a 0.5 Over on hits or total
bases at `mm` 7.7-9.7, with 4 books each.

| class | who / market | price | mkt | ours | mm | score | result |
|---|---|---:|---:|---:|---:|---:|---|
| pick | Wells hits o0.5 | +110 | .457 | .551 | 9.3 | .069 | W |
| pick (withdrawn) | Montgomery TB o0.5 | +114 | .443 | .540 | 9.7 | .065 | L |
| pick | Lombard TB o0.5 | -135 | .543 | .637 | 9.4 | .057 | L |
| pick | Meidroth TB o0.5 | -130 | .532 | .620 | 8.8 | .039 | W |
| pick | Aranda TB o0.5 | -154 | .570 | .660 | 9.0 | .039 | W |
| pick | S. Jones hits o0.5 | -135 | .545 | .627 | 8.2 | .033 | L |
| pick | Peters TB o0.5 | -119 | .517 | .594 | 7.7 | .028 | L |
| pick | Bailey TB o0.5 | -119 | .510 | .593 | 8.4 | .026 | L |
| fill G3 | McMahon hits o0.5 | +115 | .443 | .529 | 8.6 | .048 | L |
| fill G3 | Antonacci hits o0.5 | -160 | .600 | .667 | 6.8 | .036 | L |
| fill G3 | Hicks hits o0.5 | -134 | .552 | .624 | 7.2 | .030 | L |

The three fills were "picks with a stale quote", with the same 7-9 point
gaps. Nothing on this card leaned on the market. Every entry was our number
8 to 10 points above it.

**Winning day, 2026-10-14: 6-0, +5.56u.** There were 5 runs and about 48
replayed prop candidates per run. The first two runs passed 4 and published
3. At 05:15Z and 21:24Z everything was G3 stale, and one G3-only fill was
added. At 22:12Z 3 passed. Three of the six graded entries were picks that
were later withdrawn and still graded as wins (Vaughn, Bauers, Turang, +2.87u
together). All six were hits 0.5 props at `mm` 7.0-9.2. **The same rule, the
same gap band, the same market: the only difference from 10-05 is the outcome.**

**3-0 day, 2026-10-08: +2.47u.** The overnight run (04:09Z) had 3 candidates,
all outside the price band, so the card was empty. The 22:09Z run had 47
candidates. One passed every gate (Doyle hits o0.5 -116, `mm` 9.4, score
.067) and became the pick. The floor of 3 then added two G7 fills (Murakami
and Bazzana TB o0.5, `mm` 6.8 and 6.7, score -0.007 and -0.010). At their
own marked-down number those two were negative-EV bets (used .540 against
need .555, and .561 against .576). All three won.

### What the rule actually optimises (one paragraph)

The rule maximises model-minus-market disagreement, net of vig, inside a
window. The score is a Kelly fraction on our number minus 3.8 points at the
best price. Over every fill-eligible replayed candidate it is
`score = -0.105 + 2.41*mm - 2.40*vig_gap + 0.007*d` (n=853), with corr(score,
mm) = 0.98. `mm` varies 3.7 points (SD) against 0.7 points for the vig gap, so
the ranking is the disagreement ranking. The gates fix that disagreement
between about 5 points (G7: the markdown plus the required edge plus the vig
gap) and 10 points (G8), and the score then fills from the top of that
window. That is the slice the registration itself flagged as the measured
worst (`PREREG_CARD_V2.md` 0.2: 10+ points above the market hit 40.6% against
62.1% claimed). `propboard.py`'s own docstring records the same thing: ranking
props by edge returned -13.4% against -9.1% for not selecting at all. Fills
reverse the logic. They are the close calls closest to clearing the value
bar. In practice that means G7 failures with a smaller `mm` (mean 4.4 points
against 8.5 for picks) and G3-stale near-picks. They exist only because
"always show 3" puts them on the card.

## 2. Selection on noise (winner's curse)

The shrinkage regression is `realised(0/1) - market_p = k * (our_p - market_p)`.
`k` is the weight our number deserves in `p = market + k*(ours - market)`:
1 means our gap is fully real, 0 means it carries nothing, and below 0 means
it points the wrong way. The slope with an intercept is also shown. The CI is
a percentile 95% interval from 2,000 date-clustered bootstrap resamples (seed
20261016).

### 2a. Hit rate by model-minus-market, four populations

Published entries (n=178):

| mm (pts) | n | W-L | hit | market | hit - market | units |
|---|---:|---:|---:|---:|---:|---:|
| <0 | 15 | 10-5 | .667 | .566 | +.101 | +2.67 |
| 0-2 | 4 | 4-0 | 1.000 | .560 | +.440 | +3.07 |
| 2-4 | 7 | 3-4 | .429 | .544 | -.116 | -1.68 |
| 4-6 | 7 | 4-3 | .571 | .538 | +.033 | +0.59 |
| 6-8 | 46 | 30-16 | .652 | .525 | +.128 | +9.02 |
| **8-10** | **99** | **46-53** | **.465** | .525 | **-.060** | **-15.09** |

Replayed card candidate pool, props, one row per contract, graded (n=2,595,
`selection_pool.json` -> `run_pool`):

| mm | n | hit | market | hit - market | ROI |
|---|---:|---:|---:|---:|---:|
| <0 | 917 | .693 | .635 | +.057 | +2.9% |
| 0-2 | 326 | .601 | .600 | +.001 | -5.1% |
| 2-4 | 359 | .582 | .587 | -.004 | -5.5% |
| 4-6 | 309 | .553 | .574 | -.020 | -8.7% |
| 6-8 | 255 | .631 | .561 | +.070 | +6.5% |
| 8-10 | 189 | .508 | .545 | **-.037** | -12.5% |
| >10 | 240 | .479 | .518 | **-.039** | -12.5% |

Pregame-close prop board, the side our number favours, every assessable
contract from 2026-09-08 to 10-15 (n=6,818, 34 days). This is the largest and
cleanest test:

| mm | n | hit (95% CI) | market | hit - market | ROI |
|---|---:|---:|---:|---:|---:|
| <0 | 2,440 | .650 (.631-.669) | .630 | +.020 | -2.6% |
| 0-2 | 994 | .581 (.550-.611) | .596 | -.015 | -7.9% |
| 2-4 | 992 | .594 (.563-.624) | .584 | +.010 | -3.9% |
| 4-6 | 796 | .580 (.546-.614) | .571 | +.009 | -3.7% |
| 6-8 | 616 | .565 (.526-.604) | .560 | +.005 | -4.5% |
| **8-10** | 450 | .511 (.465-.557) | .551 | **-.040** | -12.7% |
| **>10** | 530 | .481 (.439-.524) | .521 | **-.040** | -12.9% |

2024 moneylines, both sides of every game, the model rebuilt (2c below)
(n=4,066):

| mm | n | hit | market | hit - market | ROI |
|---|---:|---:|---:|---:|---:|
| <0 | 2,033 | .563 | .559 | +.005 | -0.9% |
| 0-2 | 533 | .460 | .490 | -.030 | -6.9% |
| 2-4 | 452 | .476 | .460 | +.016 | +2.4% |
| 4-6 | 369 | .472 | .436 | +.036 | +5.7% |
| 6-8 | 285 | .372 | .408 | -.036 | -9.6% |
| 8-10 | 201 | .398 | .395 | +.003 | -0.4% |
| >10 | 193 | .352 | .372 | -.019 | -6.2% |

**Reading.** In no population does the hit rate rise with the gap. Over 0-8
points it tracks the market's own number. Where the rule's picks
concentrate, 8-10 points and the >10 tail just past the cap, it falls about
4 points below the market in both prop populations. The ranking is therefore
selecting model error.

### 2b. The shrinkage factor

| population | n | days | k (origin) | k 95% CI | slope (with intercept) | slope CI |
|---|---:|---:|---:|---:|---:|---:|
| published entries | 178 | 21 | -0.12 | -0.98..+0.96 | -1.38 | -2.75..+0.08 |
| published picks | 110 | 18 | -0.48 | -1.43..+0.76 | -11.1 | -21.1..-2.7 |
| replayed card pool (props) | 2,595 | 20 | **-0.33** | -0.72..+0.07 | -0.50 | -0.91..-0.10 |
| replayed pool, mm 0-10 only | 1,438 | 20 | +0.07 | -0.44..+0.59 | +0.11 | -1.30..+1.28 |
| **close board, model-favoured (props)** | **6,818** | **34** | **-0.20** | **-0.45..+0.06** | -0.24 | -0.51..+0.04 |
| close board, card window (09-22+) | 4,061 | 20 | -0.20 | -0.55..+0.10 | -0.28 | -0.65..+0.05 |
| close board, before card (09-08..09-21) | 2,757 | 14 | -0.19 | -0.61..+0.25 | -0.17 | -0.64..+0.30 |
| close board, hits | 2,276 | 34 | -0.20 | -0.50..+0.13 | | |
| close board, total bases | 2,448 | 34 | -0.18 | -0.45..+0.10 | | |
| close board, runs scored | 2,094 | 29 | -0.23 | -0.57..+0.10 | | |
| **2024 moneylines, both sides** | **4,066** | **165** | **-0.01** | **-0.32..+0.29** | -0.01 | -0.32..+0.29 |
| 2024 moneylines, favourite side | 2,033 | 165 | -0.01 | -0.32..+0.29 | +0.02 | -0.35..+0.39 |

Log-loss, close board (props): market 0.66359, ours 0.67385 (+0.0103 nats
worse), best blend weight on ours over a 0.0-1.0 grid = **0.0**. On 2024
moneylines (home side): market 0.67252, ours 0.68031 (+0.0078), best weight 0.0.

**The shrinkage number: k is about -0.2 for props (CI excludes anything above
+0.06) and about 0 for moneylines (CI excludes anything above +0.29).** The
G7 value test needs the *raw* gap to exceed about 5 points. After shrinkage
by any k inside these intervals, no candidate in any population clears
break-even.

One positive sliver, recorded so it is not buried: **closing-line movement.**
Between the decision-time read and the close, the market moved toward our
side by **0.020 points per point of `mm`** (CI 0.007 to 0.035, n=2,653
contracts). A 10-point gap therefore buys about 0.2 points of line movement,
against about 2.4 points of vig paid on the published set. It is real
information, and it is two orders of magnitude too small to bet.

### 2c. How the 2024 numbers were built

`section_y2024`: `features.build_training_table` over 2023-2024 results
only, with every other season dropped on its date column before any field is
kept, games strictly before each date, and 2024-04-15 onward. Pitcher logs
and the bullpen log are filtered to 2023-2024 the same way, and relief rates
are taken strictly before each date. `strength.model_line` uses the **frozen
2025** dispersion (2.3615) and the frozen Platt calibration (a=0.0712,
b=0.6852), with league runs per game from that date's slate, as the live path
does. The market is the mean proportional de-vig over the books on the newest
archive poll strictly before first pitch (`snapshot_at`, per
`src/board/l1_historical.py`), and the price is the best book. There are
2,194 modelled games, 2,033 of them matched to pregame odds (439 archive
events unmatched: spring, pre-04-15 and postseason). G3 cannot be evaluated
on a 3-polls-a-day archive and is dropped. This is **not** agent 1's method,
which was not available to this agent.

What V2 would have done in 2024 had it enumerated both moneyline sides, as
registered: 379 underdog sides would have passed every gate (6 or more books,
before the per-day G11, G12 and G14 caps). They went **143-236, -30.6u
(-8.1%)**, with the market saying 40.3% and actual 37.7%. Only 44 favourite
sides passed (25-19, +2.2u). The same Platt `b = 0.685` that pulls every
favourite down toward 0.5 pushes every underdog up, and that manufactures
plus-money "value". The live path's failure to enumerate underdogs (section 1)
is the only reason this class is absent from the 2026 record.

## 3. Picks vs fills

| | picks (110) | fills (68) |
|---|---:|---:|
| mean price | -78 | -127 |
| mean decimal | 1.851 | 1.762 |
| plus-money share | 21.8% | 2.9% |
| game (moneyline) share | 4.5% | 35.3% |
| mean market p | .520 | .547 |
| mean our p | .605 | .592 |
| mean mm | **8.5 pts** | **4.4 pts** |
| mean vig gap (breakeven - market) | 2.46 pts | 2.21 pts |
| mean books | 4.17 | 5.68 |
| hit / market expectation | .491 / .520 | .632 / .547 |
| units | -9.26 | +7.85 |
| expected units at market | -4.92 | -2.63 |
| **luck (units - expected)** | **-4.34** | **+10.48** |

**Price.** No. Fills are *shorter*, not cheaper. The vig per bet is about the
same (-4.5% against -3.9% at market). Within every MAIN price band, fills
beat picks:

| band | picks n, hit-mkt, u | fills n, hit-mkt, u |
|---|---|---|
| -160..-140 | 27, -.087, -5.31 | 28, -.001, -1.04 |
| -139..-120 | 41, -.070, -6.89 | 25, +.177, +6.79 |
| -119..-100 | 18, -.068, -2.92 | 13, +.101, +2.06 |
| +100..+150 | 24, +.134, +5.86 | 2, +.043, +0.03 |

**Market type.** Partly. Moneylines are 35% of fills and went 16-8, +4.20u
(the 5 moneyline picks went 3-2). Among props alone, picks are 51-54
(-9.89u) and fills 27-17 (+3.65u). Date-stratified permutation, props only:
p = 0.25 on units, p = 0.18 on hit minus market.

**Gap size.** This is the structural part. Picks sit at 8-10 points (83 of
110). That band went 36-47, -16.32u, 8.8 points below the market. Picks at
6-8 points went 17-8, +7.15u. Fills spread across `mm` with no gradient.
The pool says the 8-10 band costs about 4 points (2a). The remaining 4-5
points of the picks' shortfall is within noise.

**Books.** No. The 2-book stratum was the *best* (16-5, +7.96u; picks 6-2,
fills 10-3). The 3-4 book stratum, where most picks live (87 of 110), went
41-46 for picks.

**Luck.** This is most of it. In units, fills ran +10.48u above market
expectation and picks -4.34u. Under the market's own number the z-score is
+1.41 for fills (43 wins against 37.2 expected) and -0.62 for picks (54
against 57.2). Permutation tests on the pick/fill label (10,000 shuffles):

| test | observed diff | p (two-sided) |
|---|---:|---:|
| units per bet, unstratified | -0.200 | 0.153 |
| units per bet, stratified by date | -0.200 | 0.298 |
| hit minus market, stratified by date | -0.114 | 0.246 |

Regression of realised minus market on `[is_pick, mm, decimal odds]` with a
date-bootstrap CI: is_pick -0.12 (-0.34 to +0.10), mm -0.78 (-3.12 to
+1.65), decimal +0.47 (-0.15 to +1.13). **Nothing is distinguishable from
zero.**

**Verdict.** The fill advantage is luck, sitting on top of one structural
fact. Picks are taken from the high-disagreement band, which the larger pool
shows hits about 4 points under the market. Fills come from closer to the
market, which hits at the market rate. Neither class has an edge: both pay
about 4% vig. Hindsight caution: "publish only fills" (+7.85u, n=68) is the
same noise read backwards.

## 4. Volume and the vig

| | value |
|---|---:|
| settled days | 21 |
| bets per day | 8.48 mean (distribution: 1,3,3,4,5,6,6,8,8,8,9,9,10,10,10,11,11,11,11,12,22) |
| mean price | -96.7 |
| mean break-even | .554 |
| mean market p | .530 |
| vig gap (break-even - market) | **2.36 pts per bet** |
| expected units at market | **-7.55 (-4.24% per bet)** |
| realised hit | .545 (needs .554 to break even) |
| realised units | -1.42 |

**Volume caps, HINDSIGHT** (each day's entries in published rank order:
picks by score, then fills in close-call order, all 178 graded):

| cap/day | n | W-L | hit | units | expected at market |
|---:|---:|---:|---:|---:|---:|
| 1 | 21 | 12-9 | .571 | +2.23 | -0.81 |
| 2 | 41 | 23-18 | .561 | +2.32 | -1.73 |
| 3 | 61 | 33-28 | .541 | +1.24 | -2.64 |
| 5 | 96 | 54-42 | .563 | +4.02 | -4.10 |
| none | 178 | 97-81 | .545 | -1.42 | -7.55 |

In chronological order (first shown first) the same caps give +0.31u, +8.50u,
+10.29u and +9.24u. The two orderings disagree by up to 9u on the same bets,
so the cap's "result" is noise. **What a cap does do is mechanical: it cuts
the expected vig.** At 3 a day the expected loss is -2.6u where uncapped it is
-7.6u.

**Alternative rules, HINDSIGHT** (same 178 bets, filtered):

| rule | n | W-L | units | expected at market |
|---|---:|---:|---:|---:|
| as published | 178 | 97-81 | -1.42 | -7.55 |
| publish only plus money | 26 | 15-11 | **+5.89** | -1.07 |
| drop plus money | 152 | 82-70 | -7.31 | -6.49 |
| props no worse than -115 (games kept) | 69 | 40-29 | **+8.16** | -2.13 |
| props no worse than -115, props only | 40 | 21-19 | +3.33 | -1.57 |
| moneylines only | 29 | 19-10 | +4.83 | -0.55 |
| props only | 149 | 78-71 | -6.25 | -7.00 |
| drop total bases | 100 | 56-44 | +4.78 | -3.38 |
| mm <= 6 pts | 33 | 21-12 | +4.65 | -0.75 |
| mm > 6 pts | 145 | 76-69 | -6.07 | -6.81 |
| break-even <= .56 | 89 | 49-40 | +5.73 | -3.53 |

Every positive row here has an expected value at market below zero. Each is
an n of 26 to 100 cut from the data that produced it.
**"Publish only plus money" has a 2024 counter-measurement:** the
plus-money moneyline class V2 would have published went -8.1% over 379 bets
(2c).

**Thin edges the system knowingly bet.** The rule's own marked-down number
(`our_probability_used`) was **below the price's own break-even** on **31**
graded bets, so by its own number they lose money. All 31 were fills (29 G7,
2 G3+G7). They went 20-11, +4.39u. The gate that let them through is the
**floor of 3**, because a fill may fail G7 (registration section 3, "A fill").
At `our_probability_used < 0.56`: 70 bets (36 picks, 34 fills), 41-29,
+9.33u. The whole card's expected value at its own marked-down number was
only +2.8u (+1.6% per bet). At the raw number it was +15.1u. At the market's
number it was -7.55u.

**Grading price** (`python3 scripts/diagnosis/selection.py pricing`). Every
entry is graded at `price`, the **best** quote across books. The owner's
ruling, as given in this brief, is to grade at average odds. Re-graded at the
mean of the books' own quotes at the same observation, the 149 props come to
**-9.65u** against **-6.25u** at best (picks -12.41 against -9.89, fills
+2.76 against +3.65). Mean decimal: 1.788 against 1.826. *Observation, not a
fix: this agent edits no grading code.*

## 5. Moneylines

The 29 moneyline entries: **all market favourites, all priced -100 to -160,
24 home (82.8%)**, 19-10, +4.83u. 5 were picks (3-2) and 24 were fills (23
G7, 1 G3+G7).

| | n | W-L | hit | market | units |
|---|---:|---:|---:|---:|---:|
| home | 24 | 16-8 | .667 | .554 | +4.62 |
| away | 5 | 3-2 | .600 | .556 | +0.21 |
| -160..-140 | 10 | 5-5 | .500 | .583 | -1.53 |
| -139..-120 | 11 | 8-3 | .727 | .554 | +3.07 |
| -119..-100 | 8 | 6-2 | .750 | .520 | +3.29 |

Mean `mm` on the 29 is **+0.28 points**. Our number and the market's are
almost the same.

**Where `our_probability` comes from.** It is the real run model
(`strength.model_line`) passed through the frozen 2025 Platt fit,
`p_home = sigmoid(0.0712 + 0.6852*logit(raw))`. It is not market-derived and
not a placeholder. That fit adds a constant **+1.78 points to the home side**
at raw 0.50, and shrinks every raw number toward 0.5 (raw .60 becomes .586,
raw .40 becomes .449).

**Is there model content?** It is barely measurable. Over all 69
market-favoured moneyline sides the card evaluated (one per game per date,
graded from linescores): corr(ours, market) = **0.19**. Fitting
`ours = 0.451 + 0.149*market + 2.0 pts*home` leaves 2.8 points of residual
SD. So our number is roughly a constant 0.53, plus a 2-point home lean, plus
noise that does not track the market. The rule then does this:

- **G7 almost never passes**, because a shrunk number cannot sit 5 points
  above a favourite's market price. 67 of the 69 were close calls; 2 were
  pick-eligible on the representative run.
- **G6 (`our > 0.50`) quietly filters out away favourites**, because the home
  lean drags the away side's number toward 0.50. On the 2024 rebuild, among
  favourites priced -100 to -160 (with 6 or more books), G6 fails **45% of
  away favourites (n=588) against 17% of home favourites (n=869)**, and 53%
  against 81% survive as pick-or-fill-eligible. The ledger cannot show this
  directly, because hard-gate failures are never stored. So the moneylines
  that survive to be fills are mostly **home favourites the market already
  prices at -100 to -160**.

In 2024 the same model's moneyline gap has k = -0.01 (CI -0.32 to +0.29),
with log-loss 0.0078 worse than the market. **The moneyline entries are,
functionally, the market's favourite in the -100..-160 band with a home lean.
Their 19-10 is the market's 55% plus luck.** At market odds they were worth
-0.55u, and they made +4.83u.

The `p_model_provenance` field in `evidence/decisions_v2.jsonl` belongs to a
**separate pipeline**: the Stage-16 paper engine,
`TOP_RANKED_PLAY_PER_SYSTEM_PER_GAME_V1`. The public card never reads that
file. On the 29 card moneyline games the engine's h2h decisions were 117
`none` (signal systems with no probability), 32 `market_derived` (the
market's own number, by construction) and 16 `placeholder`.

## 6. Close calls, ceiling, refusals, stale boards

`python3 scripts/diagnosis/selection.py closecalls`. Each never-published close
call is graded at its last instance before the lock window.

| source | n | W-L | hit | market | units | expected at market |
|---|---:|---:|---:|---:|---:|---:|
| close calls never shown | 721 | 415-306 | .576 | .552 | -4.84 | -35.84 |
| ceiling-refused (G12) | 40 | 21-19 | .525 | .541 | -3.45 | -2.06 |
| of which passed every gate (refused only by the cap) | 32 | 16-16 | .500 | .540 | -4.22 | -1.66 |
| plus-money sub-cap drops (G14) | 0 | | | | | |

- **The 10-entry cap removed bets worth -3.45u.** The 32 full-gate picks it
  refused went 16-16, so G12 *saved* 4.2u, in hindsight.
- **Close calls not shown** hit 2.4 points above the market on 721 bets. That
  is in line with the pool (2a): no edge, about -0.7% ROI against -5%
  expected.
- **`refused_thin` / `refused_stale`** exist only in `decisions_v2.jsonl`,
  the paper engine. None of them is an h2h decision (all h2h engine decisions
  are `play`; the refusals are totals/spreads). **They removed nothing from
  the public card**, which does not read that file. The engine's own graded
  h2h paper plays: `market_derived` 48-48 (-3.61u), `none` 118-136 (-21.04u),
  `placeholder` 28-20 (+3.00u).

**Did stale or single-book quotes produce the worst bets?** No.

| stratum (published) | n | W-L | units |
|---|---:|---:|---:|
| props with 2 books (the G2 minimum) | 21 | 16-5 | +7.96 |
| props with 4 books | 88 | 41-47 | -12.35 |
| quote age at first show <= 30 min | 146 | 79-67 | -0.80 |
| quote age at first show > 180 min | 23 | 14-9 | +1.58 |
| G3-stale fills | 20 | 11-9 | -0.75 |

The worst ten bets by expected value at market are all total-bases props at
-119 to -160 with 2 to 7 books. Seven of them had quotes under a minute old
when first shown, and only one was over 20 minutes (614). That is a price fact, not a staleness fact.

### 6.3 A recording defect found on the way

`best_bets_card.select()` hard-codes `"stale_board": None` (line 616), and
nothing downstream sets it. So **all 175 published rows carry
`stale_board: None`**, even on runs like 2026-10-05 05:15Z and 2026-10-14
05:15Z where the replay shows every candidate failing G3. A reader counting
stale boards from the ledger gets zero, but that zero means "never computed"
rather than "none happened". This is reported, not fixed (the file is
fingerprinted).

## 7. Conclusions

### What guides selection today, in plain words

The card bets where our number is most above the bookmakers' number, up to a
10-point limit, at the best price any book offers, provided that price is not
better than fair. "Most above" is the whole ranking (corr 0.98). When fewer
than three bets qualify, it tops up with the bets that came closest to
qualifying. Our number does not beat the market's on any cut measured here,
so the ranking is effectively choosing where our model is most wrong.

### The selection rules that lose money, and the evidence

1. **Ranking by disagreement (the score), with picks pushed to the 8-10 point
   band.** Pool evidence: the 8-10 and >10 point bands hit 4.0 points under
   the market (close board: n=450 and n=530; replayed pool: n=189 and n=240).
   Published: the 8-10 band went 46-53, -15.09u. Our gap's blend weight is -0.20
   (CI -0.45 to +0.06) for props and -0.01 (CI -0.32 to +0.29) for moneylines.
2. **A value test with no value behind it, combined with G13 and best-price
   pricing, which guarantees the vig.** G13 lets through only bets where the
   market's number is at or below break-even. Every published bet therefore
   pays vig against the market (2.36 points, -4.2% per bet, -7.55u expected).
   An uninformative model cannot recover that. Volume (8.5 bets a day, up to
   22) multiplies it.
3. **Fills that fail the value test by the rule's own number.** 31 bets were
   negative-EV at the system's own marked-down probability. They won this
   time (+4.39u), but the fill rule publishes bets the rule itself prices as
   losers, in exchange for always showing three.
4. **Latent, measured in 2024: Platt shrinkage plus underdog enumeration.** If
   both moneyline sides are enumerated as registered, the frozen calibration
   makes underdogs look like value: -8.1% over 379 bets in 2024. Do not promote
   `moneyline_both_sides_v1` on the strength of "plus money is winning".

### Smallest pre-registerable rule changes

Every "retrospective effect" below is **HINDSIGHT** on the same 178 bets and
licenses nothing beyond a forward test. Each change is a **new rule id**
(registration 16: "Anything else is a new rule id") and runs as a paper arm
under 17.6's one-board, many-screens machinery. Power, stated plainly: at
p near .55, telling a 3-point hit-rate excess over the market's own number
apart from zero at 80% power (two-sided 5%) needs about 2,200 bets per arm,
which is about 260 days at today's volume. Comparing two arms against each
other needs about 4,300. The
first-line forward metric therefore has to be **closing-line movement**
(n is in the thousands per month, and the noise is far lower) together with
**log-loss against the market**, with hit rate and units as secondary.

| # | change | what it does | retrospective (HINDSIGHT) | required forward test |
|---|---|---|---|---|
| R1 | **Shrink our number before G7:** `p = market + k*(ours - market)` with `k` fixed in advance at 0.0. The measured CIs put k at or below +0.06 (props) and +0.29 (moneylines) | Ends "value" picks honestly. With k=0 nothing clears break-even (G13 already forces market <= break-even), so the card stops claiming value until a model earns k > 0 | 0 picks. The 110 picks (-9.26u) and every fill failing G7 disappear. The card shows "likely" bets labelled as carrying no edge, or nothing | Forward k re-estimate on the next 30 days of the close board (pre-register: the k CI must exclude 0 from above before any k > 0 is allowed) |
| R2 | **Volume cap 3 per day**, ranked by market probability or by least disagreement, not by score | A loss limiter, not an edge: expected vig falls from -7.55u to about -2.6u | rank order: 33-28, +1.24u; chronological: +10.29u. The ordering disagreement shows it is noise | Paper arm; primary metric is expected-vs-realised against market, and the cap is judged on loss per day, not hit rate |
| R3 | **G8 disagreement cap 0.10 -> 0.08** | Removes the band the pool shows is worst | Published: drops 99 entries that went 46-53, -15.09u. Pool: 8-10 hits -4.0 points (n=450). Registration 4.4 warns that the main band nearly closes, so expect very few picks | Paper arm over 60 days; pre-register the pool's 8-10 band as the falsifier (if 8-10 hits at or above the market, R3 is retired) |
| R4 | **Grade at the mean of books' prices** (the owner's average-odds ruling) | Truth in the record, not selection | Props -9.65u against -6.25u (-3.4u) | None: a reporting change; apply to the ledger reader and say so on the page |
| R5 | **Drop the floor-of-3 fills that fail G7 at the system's own break-even** (`used < breakeven`) | Stops publishing bets the rule prices as losers | Removes 31 bets that went 20-11, +4.39u (it would have *cost* units this time) | Owner decision. "Always show 3" is a ruling; this is the price of it, stated |

What **not** to pre-register from this data: "plus money only" (+5.89u,
n=26), "props no worse than -115" (+8.16u, n=69), "drop total bases"
(+4.78u, n=100), "fills only" (+7.85u, n=68). Each one is the observed noise
re-read as a rule, and each has expected value at market below zero. The
2024 plus-money result points the other way.

### What this agent could not do

- The **moneyline candidate pool for 2026 could not be fully replayed**.
  Rebuilding a past slate's game entries needs the MLB schedule endpoint
  (network). Moneylines use the ledger's own candidates (69 games) plus the
  2024 rebuild.
- **Lineup-slot timing** in the replay comes from `data/watch/lineups_watch.jsonl`
  poll times. It accounts for most of the 22% of close calls reproduced by
  identity but not to the exact number.
- The 2024 rebuild is **not agent 1's method**. Its market number comes from
  a 3-polls-a-day archive, and G3 is not evaluated there.
- Nothing here re-tests 2025 (tuning-only) or touches the sealed window.
  `_open()` drops 2026-01-01..2026-08-27 and all of 2025 on the date column
  before any outcome field is read. `_season_ok()` restricts the 2024 rebuild
  to 2023-2024 rows of the shared results, pitcher and bullpen stores.

## Reproduce

```
python3 scripts/diagnosis/selection.py replay      # rebuilds data/research/loss_diagnosis/prop_replay_pool.jsonl.gz (~2 min)
python3 scripts/diagnosis/selection.py all         # every section -> data/research/loss_diagnosis/selection_<section>.json
python3 scripts/diagnosis/selection.py ledger|pool|moneyline|closecalls|trace|pricing|y2024
```

The bootstrap and permutation seed is 20261016. The outputs are
deterministic given the stores at commit time.
