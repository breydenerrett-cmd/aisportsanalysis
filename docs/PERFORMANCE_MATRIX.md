# Performance matrix

Generated: 2026-10-02T03:18:50Z

Settled entries from 2026-09-10 to 2026-09-30 (all settled dates). Regenerate with `python scripts/performance_matrix.py`. Read-only on every ledger; the script changes no rule, gate, threshold or published record. Only dates from 2026-09-10 onward are read; the sealed window 2026-01-01..2026-08-27 is never opened.

## How to read this

**Verdict rule (fixed, stated once, applied identically to every row, baselines included).** `TOO FEW` when n staked < 30. `CANDIDATE` only when n staked >= 100 AND mean closing-line value > 0 AND the lower end of its 95% interval (mean - 1.96 se) > 0 AND z vs the market > 2. Everything else is `NO EVIDENCE`. A row whose closing-line value cannot be measured can never reach `CANDIDATE`. A `CANDIDATE` would be a hypothesis for a pre-registered forward test (`docs/PREREG_CARD_V2.md`), never a reason to change a rule.

**Multiplicity.** This matrix has 110 measured rows and 22 MISSING rows, each a different population. With about 110 looks, one or two will look good by chance alone, and a z above 2 in a row is what chance produces. The rows also overlap: V1 public, V2 public and the V2 shadows often hold the same games, and the paper systems bet the same games on the same sides (the FORWARD_TEST systems are near-duplicate genomes), so the rows are not independent looks and the count overstates how many separate tests were run. No row here is a reason to change a rule. Changing a rule needs a pre-registered test on forward data.

**Rows with |z| above 2: 3.** R067 (totals paper, market_derived_consensus_totals_over, n=252, z +2.07, BASELINE: MARKET REFERENCE); R069 (totals paper, market_derived_consensus_totals_under, n=278, z -2.05, BASELINE: MARKET REFERENCE); R071 (totals paper, trivial_under_total, n=278, z -2.05, BASELINE: CONTROL). Chance alone puts roughly one row in twenty past 2 in either direction; a row that does is not a result unless it is also CANDIDATE under the rule above, and a baseline row that does is a property of the sample.

**Verdicts this run (measured rows):** TOO FEW: 76, NO EVIDENCE: 34, CANDIDATE: 0. **MISSING rows:** 22.

**Baselines are not models.** Rows labelled `BASELINE: CONTROL` take a fixed side with no information (always home, always under); rows labelled `BASELINE: MARKET REFERENCE` republish the board's own de-vigged consensus (their probability IS the price). They exist to say what no-information and the-market-itself earn. A control or market-reference row that looks good is variance or a property of the sample (for example, over and under totals mirror each other), never a result for a model.

**Units** are flat 1u per entry at the frozen price. Pushes, voids, unresolved and withdrawn entries are never staked (W-L-P-V counts wins, losses, pushes, voids; N staked = W + L). ROI = units / n staked. Rows are never pooled across rule, market, entry class, season scope, model or visibility; fills never enter a pick row; postseason entries are their own rows (the project's calendar rule). z = (wins - market-expected wins) / sqrt(sum p(1-p)) with the de-vigged market probability frozen on each entry. Where `(k/n)` appears only k of n staked entries carry it. `MISSING` names why a cell is empty, from a fixed vocabulary: `NEVER_PUBLISHED` = no entry for this market exists in any ledger of this visibility; `PUBLISHED_UNGRADED` = entries exist but none graded WIN or LOSS (void, push, unresolved or withdrawn only); `PUBLISHED_NOT_STAKED` = shown as analysis flags with no stake, price rule or grade; `NO_CLOSING_LINE_CAPTURED` = graded entries exist but no closing line was captured for them; `NO_PROBABILITY_FROZEN` = graded entries exist but no per-entry probability is frozen on them.

### Rows are not all measured the same way

- **Closing-line value (CLV)** is the de-vigged close minus the break-even of the frozen price, in probability points. It subtracts a de-vigged close from a price that still carries the book's margin, so it is biased negative by roughly half the hold before any line has moved. Card, shadow and UFC rows use `card_clv.measure_pick` (refuses props always, refuses a stale or thin close and a decision-board close). Paper rows use `clv.measure_decision` at the price taken (best on the board at the decision) with a close older than 90 minutes refused, which is `card_clv`'s rule. Props, F5 and in-play have no closing board and are refused. Tags `[card]`, `[paper]` show which.
- **Market probability behind z** differs by source: cards freeze the de-vigged probability at the quoted price's board; paper rows use the decision's `consensus_fair` (mean de-vigged probability across books at the decision); MLB value shadow rows use the other books' de-vigged consensus (power or proportional, as each decision froze it). Two z values from different sources are not the same test.
- **Calibration** exists only where a per-entry probability of the row's own is frozen on the entry: V1 and V2 card rows, and paper MARKET_REFERENCE rows (whose probability is the market's own). Paper CONTROLs freeze a placeholder 0.5 (not a model number, so not used) and paper FORWARD_TEST systems freeze none; NFL and UFC picks freeze none. Rows with none print `NO_PROBABILITY_FROZEN` and no number. Gap = mean predicted - observed win rate; se = sqrt(sum p(1-p))/n under the row's own probabilities. Brier compares ours with the market's on the same entries (positive = ours worse).
- **Windows differ.** Settled dates by ledger: V1 public 09-10..09-22, V1 shadow 09-23..09-30, V2 public 09-22..09-30, V2 shadow A 09-22..09-30, NFL 09-17..09-27, UFC 09-22..09-26, paper 09-10..09-30. A ROI gap between two rows can be a different set of days.
- **Price basis differs.** Card prices are the frozen quote at publication; UFC prices are the average across books; paper prices are the best price on the board at the decision. Paper `spreads` and `totals` pool every line a system bet (-1.5, +1.5, 7.5, 8.5 ...); card run lines are single -1.5/+1.5 picks.

## Coverage grid (family by visibility)

| Family | public | shadow | paper |
|---|---|---|---|
| MLB moneyline | 5 row(s), largest n=104; NO EVIDENCE 1, TOO FEW 4 | 10 row(s), largest n=38; NO EVIDENCE 1, TOO FEW 9 | 43 row(s), largest n=198; NO EVIDENCE 24, TOO FEW 19 |
| MLB run line | 1 row(s), largest n=1; TOO FEW 1 | 1 row(s), largest n=5; TOO FEW 1 | 3 row(s), largest n=29; TOO FEW 3 |
| MLB totals | MISSING NEVER_PUBLISHED | MISSING NEVER_PUBLISHED | 6 row(s), largest n=278; NO EVIDENCE 3, TOO FEW 3 |
| MLB first-five (F5) | MISSING PUBLISHED_NOT_STAKED | MISSING NEVER_PUBLISHED | 8 row(s), largest n=6; TOO FEW 8 |
| MLB pitcher props | MISSING NEVER_PUBLISHED | MISSING NEVER_PUBLISHED | MISSING NEVER_PUBLISHED |
| MLB hitter props: hits | 4 row(s), largest n=71; NO EVIDENCE 1, TOO FEW 3 | 10 row(s), largest n=63; NO EVIDENCE 1, TOO FEW 9 | MISSING NEVER_PUBLISHED |
| MLB hitter props: total bases | 4 row(s), largest n=46; NO EVIDENCE 1, TOO FEW 3 | 9 row(s), largest n=64; NO EVIDENCE 1, TOO FEW 8 | MISSING NEVER_PUBLISHED |
| MLB hitter props: runs scored | MISSING PUBLISHED_UNGRADED | MISSING PUBLISHED_UNGRADED | MISSING NEVER_PUBLISHED |
| NFL sides | 2 row(s), largest n=10; TOO FEW 2 | MISSING NEVER_PUBLISHED | MISSING PUBLISHED_UNGRADED |
| NFL totals | MISSING NEVER_PUBLISHED | MISSING NEVER_PUBLISHED | MISSING PUBLISHED_UNGRADED |
| NFL player props | MISSING NEVER_PUBLISHED | MISSING NEVER_PUBLISHED | MISSING NEVER_PUBLISHED |
| UFC sides | 1 row(s), largest n=6; TOO FEW 1 | MISSING NEVER_PUBLISHED | MISSING NEVER_PUBLISHED |

## The matrix

### MLB moneyline

| Row | Market | Rule / class / scope | Model (probability source) | Vis | N staked | W-L-P-V | Units | ROI | Mean CLV (pts) [95% CI] n | z vs market | Calibration | Brier ours - market | Span | Verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| R001 | moneyline | V1 public / pick | V1 model (model_probability) | public | 104 | 69-35-0-0 | +9.71 | +9.3% | -1.21 [-1.56, -0.86] n=51 of 104 [card] | +1.47 | own p: pred 0.553, obs 0.663, gap -0.110 (se 0.049), n=104 | +0.0073 +/- 0.0052 (n=104) | 09-10..09-22 (13d) | NO EVIDENCE |
| R002 | moneyline | V1 public / fill | V1 model (model_probability) | public | 8 | 3-5-0-0 | -2.77 | -34.6% | -0.96 [-1.94, +0.03] n=8 of 8 [card] | -0.95 | own p: pred 0.478, obs 0.375, gap +0.103 (se 0.176), n=8 | -0.0111 +/- 0.0253 (n=8) | 09-12..09-21 (6d) | TOO FEW (n=8) |
| R003 | moneyline | V2 public / pick | our_probability_used (0.038 markdown) | public | 3 | 2-1-0-0 | +0.69 | +23.2% | -2.40 [-7.25, +2.45] n=2 of 3 [card] | +0.43 | own p: pred 0.570, obs 0.667, gap -0.096 (se 0.286), n=3 | -0.0111 +/- 0.0171 (n=3) | 09-23..09-25 (2d) | TOO FEW (n=3) |
| R004 | moneyline | V2 public / fill / postseason | our_probability_used (0.038 markdown) | public | 3 | 3-0-0-0 | +2.19 | +72.9% | -0.75, n=1 of 3, no interval [card] | +1.52 | own p: pred 0.518, obs 1.000, gap -0.482 (se 0.288), n=3 | +0.0443 +/- 0.0136 (n=3) | 09-29..09-30 (2d) | TOO FEW (n=3) |
| R005 | moneyline | V2 public / fill | our_probability_used (0.038 markdown) | public | 13 | 9-4-0-1 | +3.03 | +23.3% | -0.83 [-1.81, +0.16] n=10 of 13 [card] | +1.00 | own p: pred 0.515, obs 0.692, gap -0.177 (se 0.138), n=13 | +0.0115 +/- 0.0136 (n=13) | 09-23..09-27 (5d) | TOO FEW (n=13) |
| R006 | moneyline | V1 shadow / pick / postseason | V1 model (model_probability) | shadow | 5 | 5-0-0-0 | +3.72 | +74.3% | -1.82, n=1 of 5, no interval [card] | +1.96 | own p: pred 0.543, obs 1.000, gap -0.457 (se 0.222), n=5 | +0.0198 +/- 0.0143 (n=5) | 09-29..09-30 (2d) | TOO FEW (n=5) |
| R007 | moneyline | V1 shadow / pick | V1 model (model_probability) | shadow | 38 | 24-14-0-0 | +0.56 | +1.5% | -1.21 [-1.52, -0.90] n=31 of 38 [card] | +0.26 | own p: pred 0.568, obs 0.632, gap -0.064 (se 0.080), n=38 | +0.0059 +/- 0.0094 (n=38) | 09-23..09-27 (5d) | NO EVIDENCE |
| R008 | moneyline | V1 shadow / fill / postseason | V1 model (model_probability) | shadow | 3 | 1-2-0-0 | -1.17 | -39.1% | none measured (CLOSE_STALE x3) [card] | -0.75 | own p: pred 0.487, obs 0.333, gap +0.154 (se 0.289), n=3 | -0.0331 +/- 0.0419 (n=3) | 09-29..09-30 (2d) | TOO FEW (n=3) |
| R009 | moneyline | V1 shadow / fill | V1 model (model_probability) | shadow | 3 | 2-1-0-0 | +0.48 | +15.9% | -0.70 [-0.72, -0.68] n=2 of 3 [card] | +0.42 | own p: pred 0.467, obs 0.667, gap -0.200 (se 0.288), n=3 | +0.0495 +/- 0.0519 (n=3) | 09-23..09-25 (2d) | TOO FEW (n=3) |
| R010 | moneyline | V2 shadow A / pick / postseason | our_probability_used (0.038 markdown) | shadow | 3 | 2-1-0-0 | +0.62 | +20.7% | -1.12, n=1 of 3, no interval [card] | +0.39 | own p: pred 0.465, obs 0.667, gap -0.202 (se 0.288), n=3 | +0.0104 +/- 0.0651 (n=3) | 09-30 | TOO FEW (n=3) |
| R011 | moneyline | V2 shadow A / pick | our_probability_used (0.038 markdown) | shadow | 16 | 11-5-0-1 | +4.14 | +25.9% | -0.44 [-1.06, +0.18] n=14 of 16 [card] | +1.19 | own p: pred 0.507, obs 0.688, gap -0.181 (se 0.125), n=16 | +0.0124 +/- 0.0127 (n=16) | 09-22..09-26 (4d) | TOO FEW (n=16) |
| R012 | moneyline | V2 shadow C / pick | our_probability_used (0.038 markdown) | shadow | 2 | 1-1-0-0 | -0.15 | -7.6% | -4.88, n=1 of 2, no interval [card] | -0.14 | own p: pred 0.578, obs 0.500, gap +0.078 (se 0.349), n=2 | -0.0058 +/- 0.0281 (n=2) | 09-25 | TOO FEW (n=2) |
| R013 | moneyline | V2 shadow C / fill / postseason | our_probability_used (0.038 markdown) | shadow | 3 | 3-0-0-0 | +2.19 | +72.9% | -0.75, n=1 of 3, no interval [card] | +1.52 | own p: pred 0.518, obs 1.000, gap -0.482 (se 0.288), n=3 | +0.0443 +/- 0.0136 (n=3) | 09-29..09-30 (2d) | TOO FEW (n=3) |
| R014 | moneyline | V2 shadow C / fill | our_probability_used (0.038 markdown) | shadow | 15 | 11-4-0-1 | +4.64 | +30.9% | -0.39 [-1.48, +0.69] n=11 of 15 [card] | +1.45 | own p: pred 0.518, obs 0.733, gap -0.215 (se 0.129), n=15 | +0.0180 +/- 0.0092 (n=15) | 09-23..09-27 (5d) | TOO FEW (n=15) |
| R015 | moneyline | V2 shadow E / fill | our_probability_used (0.038 markdown) | shadow | 2 | 1-1-0-0 | -0.38 | -18.8% | -0.02 [-0.02, -0.01] n=2 of 2 [card] | -0.29 | own p: pred 0.570, obs 0.500, gap +0.070 (se 0.350), n=2 | +0.0063 +/- 0.0285 (n=2) | 09-24..09-25 (2d) | TOO FEW (n=2) |
| R016 | moneyline | paper TOP_RANKED_PLAY_PER_SYSTEM_PER_GAME_V1 / pick | 11da2d044a08ac38 | paper | 33 | 20-13-0-0 | +2.86 | +8.7% | -0.97 [-1.28, -0.66] n=24 of 33 [paper] | +0.91 | NO_PROBABILITY_FROZEN | - | 09-10..09-26 (9d) | NO EVIDENCE |
| R017 | moneyline | paper TOP_RANKED_PLAY_PER_SYSTEM_PER_GAME_V1 / pick | 2bff17328ce70639 | paper | 4 | 2-2-0-0 | -0.39 | -9.6% | -1.58 [-2.02, -1.14] n=4 of 4 [paper] | -0.07 | NO_PROBABILITY_FROZEN | - | 09-10..09-24 (4d) | TOO FEW (n=4) |
| R018 | moneyline | paper TOP_RANKED_PLAY_PER_SYSTEM_PER_GAME_V1 / pick | 375833d79e4bfef1 | paper | 32 | 21-11-0-0 | +3.98 | +12.4% | -0.76 [-1.16, -0.36] n=22 of 32 [paper] | +0.91 | NO_PROBABILITY_FROZEN | - | 09-11..09-26 (8d) | NO EVIDENCE |
| R019 | moneyline | paper TOP_RANKED_PLAY_PER_SYSTEM_PER_GAME_V1 / pick / postseason | 44faa9639a3a54e8 | paper | 1 | 1-0-0-0 | +0.88 | +88.5% | none measured (CLOSING_BOARD_IS_DECISION_BOARD x1) [paper] | +0.96 | NO_PROBABILITY_FROZEN | - | 09-30 | TOO FEW (n=1) |
| R020 | moneyline | paper TOP_RANKED_PLAY_PER_SYSTEM_PER_GAME_V1 / pick | 44faa9639a3a54e8 | paper | 58 | 30-28-0-0 | -4.89 | -8.4% | -1.01 [-1.27, -0.75] n=46 of 58 [paper] | -0.46 | NO_PROBABILITY_FROZEN | - | 09-10..09-26 (10d) | NO EVIDENCE |
| R021 | moneyline | paper TOP_RANKED_PLAY_PER_SYSTEM_PER_GAME_V1 / pick | 4703ed67882a9d2b | paper | 35 | 16-19-0-0 | -5.07 | -14.5% | -0.90 [-1.34, -0.46] n=26 of 35 [paper] | -0.50 | NO_PROBABILITY_FROZEN | - | 09-10..09-26 (9d) | NO EVIDENCE |
| R022 | moneyline | paper TOP_RANKED_PLAY_PER_SYSTEM_PER_GAME_V1 / pick | 4a7700d36b3855ab | paper | 29 | 11-18-0-0 | -8.37 | -28.9% | -0.96 [-1.46, -0.46] n=23 of 29 [paper] | -1.18 | NO_PROBABILITY_FROZEN | - | 09-10..09-26 (9d) | TOO FEW (n=29) |
| R023 | moneyline | paper TOP_RANKED_PLAY_PER_SYSTEM_PER_GAME_V1 / pick / postseason | 55b224b73474abec | paper | 1 | 1-0-0-0 | +0.88 | +88.5% | none measured (CLOSING_BOARD_IS_DECISION_BOARD x1) [paper] | +0.96 | NO_PROBABILITY_FROZEN | - | 09-30 | TOO FEW (n=1) |
| R024 | moneyline | paper TOP_RANKED_PLAY_PER_SYSTEM_PER_GAME_V1 / pick | 55b224b73474abec | paper | 30 | 15-15-0-0 | -3.54 | -11.8% | -1.15 [-1.42, -0.89] n=25 of 30 [paper] | -0.55 | NO_PROBABILITY_FROZEN | - | 09-10..09-26 (10d) | NO EVIDENCE |
| R025 | moneyline | paper TOP_RANKED_PLAY_PER_SYSTEM_PER_GAME_V1 / pick | 5f6d68dec562b5b3 | paper | 46 | 28-18-0-0 | +1.51 | +3.3% | -0.86 [-1.09, -0.63] n=36 of 46 [paper] | +0.70 | NO_PROBABILITY_FROZEN | - | 09-11..09-26 (8d) | NO EVIDENCE |
| R026 | moneyline | paper TOP_RANKED_PLAY_PER_SYSTEM_PER_GAME_V1 / pick | 606be696ff199952 | paper | 14 | 5-9-0-0 | -5.17 | -36.9% | -0.99 [-1.50, -0.48] n=12 of 14 [paper] | -1.46 | NO_PROBABILITY_FROZEN | - | 09-10..09-25 (8d) | TOO FEW (n=14) |
| R027 | moneyline | paper TOP_RANKED_PLAY_PER_SYSTEM_PER_GAME_V1 / pick / postseason | 6093c1cf8a6d6c08 | paper | 1 | 1-0-0-0 | +0.88 | +88.5% | none measured (CLOSING_BOARD_IS_DECISION_BOARD x1) [paper] | +0.96 | NO_PROBABILITY_FROZEN | - | 09-30 | TOO FEW (n=1) |
| R028 | moneyline | paper TOP_RANKED_PLAY_PER_SYSTEM_PER_GAME_V1 / pick | 6093c1cf8a6d6c08 | paper | 57 | 33-24-0-0 | +5.87 | +10.3% | -0.83 [-1.06, -0.61] n=42 of 57 [paper] | +1.12 | NO_PROBABILITY_FROZEN | - | 09-10..09-26 (10d) | NO EVIDENCE |
| R029 | moneyline | paper TOP_RANKED_PLAY_PER_SYSTEM_PER_GAME_V1 / pick | 6672fa80e22d2863 | paper | 53 | 31-22-0-0 | +2.36 | +4.5% | -0.81 [-1.09, -0.53] n=39 of 53 [paper] | +0.63 | NO_PROBABILITY_FROZEN | - | 09-10..09-26 (10d) | NO EVIDENCE |
| R030 | moneyline | paper TOP_RANKED_PLAY_PER_SYSTEM_PER_GAME_V1 / pick / postseason | 66fd4a5e38e890fd | paper | 1 | 1-0-0-0 | +0.88 | +88.5% | none measured (CLOSING_BOARD_IS_DECISION_BOARD x1) [paper] | +0.96 | NO_PROBABILITY_FROZEN | - | 09-30 | TOO FEW (n=1) |
| R031 | moneyline | paper TOP_RANKED_PLAY_PER_SYSTEM_PER_GAME_V1 / pick | 66fd4a5e38e890fd | paper | 41 | 23-18-0-0 | -0.56 | -1.4% | -0.99 [-1.24, -0.74] n=34 of 41 [paper] | +0.20 | NO_PROBABILITY_FROZEN | - | 09-10..09-26 (10d) | NO EVIDENCE |
| R032 | moneyline | paper TOP_RANKED_PLAY_PER_SYSTEM_PER_GAME_V1 / pick | 6e9a91ab8b7c0b55 | paper | 50 | 27-23-0-0 | -1.63 | -3.3% | -0.90 [-1.25, -0.54] n=39 of 50 [paper] | +0.01 | NO_PROBABILITY_FROZEN | - | 09-10..09-26 (9d) | NO EVIDENCE |
| R033 | moneyline | paper TOP_RANKED_PLAY_PER_SYSTEM_PER_GAME_V1 / pick / postseason | 7f7b7086400aea0b | paper | 1 | 1-0-0-0 | +0.88 | +88.5% | none measured (CLOSING_BOARD_IS_DECISION_BOARD x1) [paper] | +0.96 | NO_PROBABILITY_FROZEN | - | 09-30 | TOO FEW (n=1) |
| R034 | moneyline | paper TOP_RANKED_PLAY_PER_SYSTEM_PER_GAME_V1 / pick | 7f7b7086400aea0b | paper | 62 | 37-25-0-0 | +1.04 | +1.7% | -0.91 [-1.12, -0.69] n=47 of 62 [paper] | +0.61 | NO_PROBABILITY_FROZEN | - | 09-10..09-26 (10d) | NO EVIDENCE |
| R035 | moneyline | paper TOP_RANKED_PLAY_PER_SYSTEM_PER_GAME_V1 / pick | 8974e1cb85d58bcb | paper | 41 | 24-17-0-0 | -0.84 | -2.1% | -0.94 [-1.17, -0.70] n=31 of 41 [paper] | +0.33 | NO_PROBABILITY_FROZEN | - | 09-11..09-26 (8d) | NO EVIDENCE |
| R036 | moneyline | paper TOP_RANKED_PLAY_PER_SYSTEM_PER_GAME_V1 / pick | 8b2bb45d42021846 | paper | 51 | 30-21-0-0 | +6.37 | +12.5% | -0.79 [-1.04, -0.54] n=36 of 51 [paper] | +1.34 | NO_PROBABILITY_FROZEN | - | 09-10..09-26 (10d) | NO EVIDENCE |
| R037 | moneyline | paper TOP_RANKED_PLAY_PER_SYSTEM_PER_GAME_V1 / pick | 8f24d63763454ce2 | paper | 53 | 30-23-0-0 | +4.68 | +8.8% | -0.82 [-1.06, -0.58] n=37 of 53 [paper] | +0.92 | NO_PROBABILITY_FROZEN | - | 09-10..09-26 (10d) | NO EVIDENCE |
| R038 | moneyline | paper TOP_RANKED_PLAY_PER_SYSTEM_PER_GAME_V1 / pick | 999a7baa84ce385c | paper | 44 | 23-21-0-0 | -4.22 | -9.6% | -0.98 [-1.29, -0.67] n=35 of 44 [paper] | -0.47 | NO_PROBABILITY_FROZEN | - | 09-10..09-26 (10d) | NO EVIDENCE |
| R039 | moneyline | paper TOP_RANKED_PLAY_PER_SYSTEM_PER_GAME_V1 / pick / postseason | a3fd07c4387af7f0 | paper | 1 | 1-0-0-0 | +0.88 | +88.5% | none measured (CLOSING_BOARD_IS_DECISION_BOARD x1) [paper] | +0.96 | NO_PROBABILITY_FROZEN | - | 09-30 | TOO FEW (n=1) |
| R040 | moneyline | paper TOP_RANKED_PLAY_PER_SYSTEM_PER_GAME_V1 / pick | a3fd07c4387af7f0 | paper | 48 | 27-21-0-0 | -0.43 | -0.9% | -0.99 [-1.25, -0.72] n=38 of 48 [paper] | +0.19 | NO_PROBABILITY_FROZEN | - | 09-10..09-26 (10d) | NO EVIDENCE |
| R041 | moneyline | paper TOP_RANKED_PLAY_PER_SYSTEM_PER_GAME_V1 / pick | aee91192d90b3be2 | paper | 1 | 1-0-0-0 | +0.37 | +37.0% | -1.99, n=1 of 1, no interval [paper] | +0.64 | NO_PROBABILITY_FROZEN | - | 09-26 | TOO FEW (n=1) |
| R042 | moneyline | paper TOP_RANKED_PLAY_PER_SYSTEM_PER_GAME_V1 / pick | b6c0d42d22ff73a4 | paper | 8 | 6-2-0-0 | +2.90 | +36.2% | -0.39 [-1.09, +0.31] n=5 of 8 [paper] | +1.09 | NO_PROBABILITY_FROZEN | - | 09-11..09-24 (6d) | TOO FEW (n=8) |
| R043 | moneyline | paper TOP_RANKED_PLAY_PER_SYSTEM_PER_GAME_V1 / pick | d8990c3e820ca117 | paper | 1 | 1-0-0-0 | +0.94 | +94.3% | -1.48, n=1 of 1, no interval [paper] | +1.00 | NO_PROBABILITY_FROZEN | - | 09-23 | TOO FEW (n=1) |
| R044 | moneyline | paper TOP_RANKED_PLAY_PER_SYSTEM_PER_GAME_V1 / pick | e5b0edc481775057 | paper | 1 | 0-1-0-0 | -1.00 | -100.0% | -2.18, n=1 of 1, no interval [paper] | -1.30 | NO_PROBABILITY_FROZEN | - | 09-10 | TOO FEW (n=1) |
| R045 | moneyline | paper TOP_RANKED_PLAY_PER_SYSTEM_PER_GAME_V1 / pick / postseason | e5ff00d4b3899ccc | paper | 1 | 1-0-0-0 | +0.88 | +88.5% | none measured (CLOSING_BOARD_IS_DECISION_BOARD x1) [paper] | +0.96 | NO_PROBABILITY_FROZEN | - | 09-30 | TOO FEW (n=1) |
| R046 | moneyline | paper TOP_RANKED_PLAY_PER_SYSTEM_PER_GAME_V1 / pick | e5ff00d4b3899ccc | paper | 81 | 44-37-0-0 | +1.46 | +1.8% | -0.84 [-1.07, -0.62] n=61 of 81 [paper] | +0.51 | NO_PROBABILITY_FROZEN | - | 09-10..09-26 (10d) | NO EVIDENCE |
| R047 | moneyline | paper TOP_RANKED_PLAY_PER_SYSTEM_PER_GAME_V1 / pick | e64c85130b4664cc | paper | 57 | 34-23-0-0 | +4.48 | +7.9% | -0.84 [-1.14, -0.55] n=44 of 57 [paper] | +0.94 | NO_PROBABILITY_FROZEN | - | 09-10..09-26 (9d) | NO EVIDENCE |
| R048 | moneyline | paper TOP_RANKED_PLAY_PER_SYSTEM_PER_GAME_V1 / pick | e7f41ed66082c279 | paper | 80 | 47-33-0-0 | +9.44 | +11.8% | -0.80 [-1.01, -0.59] n=62 of 80 [paper] | +1.41 | NO_PROBABILITY_FROZEN | - | 09-10..09-26 (10d) | NO EVIDENCE |
| R049 | moneyline | paper TOP_RANKED_PLAY_PER_SYSTEM_PER_GAME_V1 / pick | ec712e93b6b9d771 | paper | 42 | 19-23-0-0 | -7.19 | -17.1% | -0.98 [-1.29, -0.67] n=32 of 42 [paper] | -0.72 | NO_PROBABILITY_FROZEN | - | 09-10..09-26 (9d) | NO EVIDENCE |
| R050 | moneyline | paper TOP_RANKED_PLAY_PER_SYSTEM_PER_GAME_V1 / pick | f301c228a7092d20 | paper | 44 | 24-20-0-0 | -3.84 | -8.7% | -0.97 [-1.20, -0.74] n=34 of 44 [paper] | -0.21 | NO_PROBABILITY_FROZEN | - | 09-10..09-26 (9d) | NO EVIDENCE |
| R051 | moneyline | paper TOP_RANKED_PLAY_PER_SYSTEM_PER_GAME_V1 / pick / postseason | f7685be895a987f9 | paper | 1 | 1-0-0-0 | +0.88 | +88.5% | none measured (CLOSING_BOARD_IS_DECISION_BOARD x1) [paper] | +0.96 | NO_PROBABILITY_FROZEN | - | 09-30 | TOO FEW (n=1) |
| R052 | moneyline | paper TOP_RANKED_PLAY_PER_SYSTEM_PER_GAME_V1 / pick | f7685be895a987f9 | paper | 20 | 10-10-0-0 | -2.99 | -15.0% | -1.23 [-1.48, -0.98] n=19 of 20 [paper] | -0.52 | NO_PROBABILITY_FROZEN | - | 09-10..09-26 (10d) | TOO FEW (n=20) |
| R053 | moneyline | paper TOP_RANKED_PLAY_PER_SYSTEM_PER_GAME_V1 / pick / postseason | market_derived_consensus_h2h_away [BASELINE: MARKET REFERENCE] | paper | 8 | 3-5-0-0 | -1.67 | -20.9% | -1.35, n=1 of 8, no interval [paper] | -0.40 | market's own p: pred 0.445, obs 0.375, gap +0.070 (se 0.175), n=8 | identical to market by construction | 09-29..09-30 (2d) | TOO FEW (n=8) [BASELINE: MARKET REFERENCE] |
| R054 | moneyline | paper TOP_RANKED_PLAY_PER_SYSTEM_PER_GAME_V1 / pick | market_derived_consensus_h2h_away [BASELINE: MARKET REFERENCE] | paper | 198 | 90-108-0-0 | -17.65 | -8.9% | -1.23 [-1.67, -0.80] n=125 of 198 [paper] | -0.70 | market's own p: pred 0.479, obs 0.455, gap +0.024 (se 0.035), n=198 | identical to market by construction | 09-10..09-26 (15d) | NO EVIDENCE [BASELINE: MARKET REFERENCE] |
| R055 | moneyline | paper TOP_RANKED_PLAY_PER_SYSTEM_PER_GAME_V1 / pick / postseason | market_derived_consensus_h2h_home [BASELINE: MARKET REFERENCE] | paper | 8 | 5-3-0-0 | +0.63 | +7.9% | -0.75, n=1 of 8, no interval [paper] | +0.40 | market's own p: pred 0.555, obs 0.625, gap -0.070 (se 0.175), n=8 | identical to market by construction | 09-29..09-30 (2d) | TOO FEW (n=8) [BASELINE: MARKET REFERENCE] |
| R056 | moneyline | paper TOP_RANKED_PLAY_PER_SYSTEM_PER_GAME_V1 / pick | market_derived_consensus_h2h_home [BASELINE: MARKET REFERENCE] | paper | 198 | 108-90-0-0 | +1.31 | +0.7% | -0.99 [-1.43, -0.54] n=125 of 198 [paper] | +0.70 | market's own p: pred 0.521, obs 0.545, gap -0.024 (se 0.035), n=198 | identical to market by construction | 09-10..09-26 (15d) | NO EVIDENCE [BASELINE: MARKET REFERENCE] |
| R057 | moneyline | paper TOP_RANKED_PLAY_PER_SYSTEM_PER_GAME_V1 / pick / postseason | trivial_always_home [BASELINE: CONTROL] | paper | 8 | 5-3-0-0 | +0.63 | +7.9% | -0.75, n=1 of 8, no interval [paper] | +0.40 | NO_PROBABILITY_FROZEN | - | 09-29..09-30 (2d) | TOO FEW (n=8) [BASELINE: CONTROL] |
| R058 | moneyline | paper TOP_RANKED_PLAY_PER_SYSTEM_PER_GAME_V1 / pick | trivial_always_home [BASELINE: CONTROL] | paper | 198 | 108-90-0-0 | +1.31 | +0.7% | -0.99 [-1.43, -0.54] n=125 of 198 [paper] | +0.70 | NO_PROBABILITY_FROZEN | - | 09-10..09-26 (15d) | NO EVIDENCE [BASELINE: CONTROL] |

### MLB run line

| Row | Market | Rule / class / scope | Model (probability source) | Vis | N staked | W-L-P-V | Units | ROI | Mean CLV (pts) [95% CI] n | z vs market | Calibration | Brier ours - market | Span | Verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| R059 | run line | V1 public / pick | V1 model (model_probability) | public | 1 | 1-0-0-0 | +0.67 | +67.1% | none measured (CLOSING_BOARD_THIN x1) [card] | +0.85 | own p: pred 0.545, obs 1.000, gap -0.455 (se 0.498), n=1 | +0.0300 (n=1) | 09-10 | TOO FEW (n=1) |
| R060 | run line | MLB_VALUE_SHADOW_V1 C_RUN_LINE / pick | none frozen (other-books consensus is the market p) | shadow | 5 | 3-2-0-0 | +0.53 | +10.6% | none measured (CLOSING_BOARD_THIN x5) [card] | +0.15 | NO_PROBABILITY_FROZEN | - | 09-25..09-26 (2d) | TOO FEW (n=5) |
| R061 | run line | paper TOP_RANKED_PLAY_PER_SYSTEM_PER_GAME_V1 / pick | market_derived_consensus_spreads_away [BASELINE: MARKET REFERENCE] | paper | 29 | 17-12-0-0 | -3.43 | -11.8% | -2.98 [-3.59, -2.36] n=11 of 29 [paper] | +0.87 | market's own p: pred 0.506, obs 0.586, gap -0.081 (se 0.093), n=29 | identical to market by construction | 09-10..09-26 (14d) | TOO FEW (n=29) [BASELINE: MARKET REFERENCE] |
| R062 | run line | paper TOP_RANKED_PLAY_PER_SYSTEM_PER_GAME_V1 / pick | market_derived_consensus_spreads_home [BASELINE: MARKET REFERENCE] | paper | 29 | 12-17-0-0 | +3.18 | +11.0% | +0.43 [-0.22, +1.08] n=11 of 29 [paper] | -0.84 | market's own p: pred 0.492, obs 0.414, gap +0.078 (se 0.093), n=29 | identical to market by construction | 09-10..09-26 (14d) | TOO FEW (n=29) [BASELINE: MARKET REFERENCE] |
| R063 | run line | paper TOP_RANKED_PLAY_PER_SYSTEM_PER_GAME_V1 / pick | trivial_always_home_spread [BASELINE: CONTROL] | paper | 29 | 12-17-0-0 | +3.18 | +11.0% | +0.43 [-0.22, +1.08] n=11 of 29 [paper] | -0.84 | NO_PROBABILITY_FROZEN | - | 09-10..09-26 (14d) | TOO FEW (n=29) [BASELINE: CONTROL] |

### MLB totals

| Row | Market | Rule / class / scope | Model (probability source) | Vis | N staked | W-L-P-V | Units | ROI | Mean CLV (pts) [95% CI] n | z vs market | Calibration | Brier ours - market | Span | Verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| M064 | totals | none | - | public | 0 | - | - | - | - | - | - | - | - | **MISSING** NEVER_PUBLISHED |
| M065 | totals | none | - | shadow | 0 | - | - | - | - | - | - | - | - | **MISSING** NEVER_PUBLISHED |
| R066 | totals | paper TOP_RANKED_PLAY_PER_SYSTEM_PER_GAME_V1 / pick / postseason | market_derived_consensus_totals_over [BASELINE: MARKET REFERENCE] | paper | 7 | 6-1-1-0 | +4.66 | +66.5% | none measured (CLOSE_STALE x2, CLOSING_BOARD_IS_DECISION_BOARD x3, CLOSING_BOARD_THIN x2) [paper] | +1.90 | market's own p: pred 0.498, obs 0.857, gap -0.360 (se 0.189), n=7 | identical to market by construction | 09-29..09-30 (2d) | TOO FEW (n=7) [BASELINE: MARKET REFERENCE] |
| R067 | totals | paper TOP_RANKED_PLAY_PER_SYSTEM_PER_GAME_V1 / pick | market_derived_consensus_totals_over [BASELINE: MARKET REFERENCE] | paper | 252 | 143-109-2-0 | +24.53 | +9.7% | -1.65 [-2.14, -1.17] n=82 of 252 [paper] | +2.07 | market's own p: pred 0.502, obs 0.567, gap -0.065 (se 0.031), n=252 | identical to market by construction | 09-10..09-26 (15d) | NO EVIDENCE [BASELINE: MARKET REFERENCE] |
| R068 | totals | paper TOP_RANKED_PLAY_PER_SYSTEM_PER_GAME_V1 / pick / postseason | market_derived_consensus_totals_under [BASELINE: MARKET REFERENCE] | paper | 7 | 1-6-1-0 | -5.15 | -73.6% | none measured (CLOSE_STALE x2, CLOSING_BOARD_IS_DECISION_BOARD x4, CLOSING_BOARD_THIN x1) [paper] | -1.87 | market's own p: pred 0.495, obs 0.143, gap +0.352 (se 0.189), n=7 | identical to market by construction | 09-29..09-30 (2d) | TOO FEW (n=7) [BASELINE: MARKET REFERENCE] |
| R069 | totals | paper TOP_RANKED_PLAY_PER_SYSTEM_PER_GAME_V1 / pick | market_derived_consensus_totals_under [BASELINE: MARKET REFERENCE] | paper | 278 | 123-155-7-0 | -41.50 | -14.9% | -1.45 [-1.89, -1.01] n=86 of 278 [paper] | -2.05 | market's own p: pred 0.504, obs 0.442, gap +0.062 (se 0.030), n=278 | identical to market by construction | 09-10..09-26 (15d) | NO EVIDENCE [BASELINE: MARKET REFERENCE] |
| R070 | totals | paper TOP_RANKED_PLAY_PER_SYSTEM_PER_GAME_V1 / pick / postseason | trivial_under_total [BASELINE: CONTROL] | paper | 7 | 1-6-1-0 | -5.15 | -73.6% | none measured (CLOSE_STALE x2, CLOSING_BOARD_IS_DECISION_BOARD x4, CLOSING_BOARD_THIN x1) [paper] | -1.87 | NO_PROBABILITY_FROZEN | - | 09-29..09-30 (2d) | TOO FEW (n=7) [BASELINE: CONTROL] |
| R071 | totals | paper TOP_RANKED_PLAY_PER_SYSTEM_PER_GAME_V1 / pick | trivial_under_total [BASELINE: CONTROL] | paper | 278 | 123-155-7-0 | -41.50 | -14.9% | -1.45 [-1.89, -1.01] n=86 of 278 [paper] | -2.05 | NO_PROBABILITY_FROZEN | - | 09-10..09-26 (15d) | NO EVIDENCE [BASELINE: CONTROL] |

- **M064** (totals, public) `NEVER_PUBLISHED`: no MLB public entry of this market in any ledger read; public ledgers hold only: hits prop, moneyline, run line, runs-scored prop, total-bases prop; published card rows with a total pick: 0 of 581; totals_paused true on 459.
- **M065** (totals, shadow) `NEVER_PUBLISHED`: no MLB shadow entry of this market in any ledger read; shadow ledgers hold only: hits prop, in-play moneyline, moneyline, run line, runs-scored prop, total-bases prop; published card rows with a total pick: 0 of 830; totals_paused true on 598; MLB value shadow arm D_GAME_TOTAL has 149 scan rows and no decision.

### MLB first-five (F5)

| Row | Market | Rule / class / scope | Model (probability source) | Vis | N staked | W-L-P-V | Units | ROI | Mean CLV (pts) [95% CI] n | z vs market | Calibration | Brier ours - market | Span | Verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| M072 | F5 moneyline | none | - | public | 0 | - | - | - | - | - | - | - | - | **MISSING** PUBLISHED_NOT_STAKED |
| M073 | F5 moneyline | none | - | shadow | 0 | - | - | - | - | - | - | - | - | **MISSING** NEVER_PUBLISHED |
| R074 | F5 moneyline | paper TOP_RANKED_PLAY_PER_SYSTEM_PER_GAME_V1 / pick | 192eda5ca8760fce | paper | 2 | 1-1-2-0 | +0.12 | +6.0% | none measured (MARKET_NOT_CAPTURED x2) [paper] | +0.24 | NO_PROBABILITY_FROZEN | - | 09-11 | TOO FEW (n=2) |
| R075 | F5 moneyline | paper TOP_RANKED_PLAY_PER_SYSTEM_PER_GAME_V1 / pick | 1f5b79a0578568b7 | paper | 1 | 1-0-1-0 | +0.61 | +60.6% | none measured (MARKET_NOT_CAPTURED x1) [paper] | +0.80 | NO_PROBABILITY_FROZEN | - | 09-11 | TOO FEW (n=1) |
| R076 | F5 moneyline | paper TOP_RANKED_PLAY_PER_SYSTEM_PER_GAME_V1 / pick | 487b77c84551b046 | paper | 4 | 3-1-2-0 | +2.30 | +57.4% | none measured (MARKET_NOT_CAPTURED x4) [paper] | +0.95 | NO_PROBABILITY_FROZEN | - | 09-11 | TOO FEW (n=4) |
| R077 | F5 moneyline | paper TOP_RANKED_PLAY_PER_SYSTEM_PER_GAME_V1 / pick | ab993b80cf517276 | paper | 1 | 1-0-2-0 | +0.61 | +60.6% | none measured (MARKET_NOT_CAPTURED x1) [paper] | +0.80 | NO_PROBABILITY_FROZEN | - | 09-11 | TOO FEW (n=1) |
| R078 | F5 moneyline | paper TOP_RANKED_PLAY_PER_SYSTEM_PER_GAME_V1 / pick | b0f7d329342ebce1 | paper | 1 | 1-0-2-0 | +0.61 | +60.6% | none measured (MARKET_NOT_CAPTURED x1) [paper] | +0.80 | NO_PROBABILITY_FROZEN | - | 09-11 | TOO FEW (n=1) |
| R079 | F5 moneyline | paper TOP_RANKED_PLAY_PER_SYSTEM_PER_GAME_V1 / pick | e8c58d079df7ecdd | paper | 1 | 1-0-0-0 | +0.51 | +51.3% | none measured (MARKET_NOT_CAPTURED x1) [paper] | +0.73 | NO_PROBABILITY_FROZEN | - | 09-11 | TOO FEW (n=1) |
| R080 | F5 moneyline | paper TOP_RANKED_PLAY_PER_SYSTEM_PER_GAME_V1 / pick | market_derived_consensus_h2h_1st_5_innings_away [BASELINE: MARKET REFERENCE] | paper | 6 | 3-3-3-0 | +0.58 | +9.7% | none measured (MARKET_NOT_CAPTURED x6) [paper] | +0.26 | market's own p: pred 0.448, obs 0.500, gap -0.052 (se 0.199), n=6 | identical to market by construction | 09-11 | TOO FEW (n=6) [BASELINE: MARKET REFERENCE] |
| R081 | F5 moneyline | paper TOP_RANKED_PLAY_PER_SYSTEM_PER_GAME_V1 / pick | market_derived_consensus_h2h_1st_5_innings_home [BASELINE: MARKET REFERENCE] | paper | 6 | 3-3-3-0 | -1.02 | -17.0% | none measured (MARKET_NOT_CAPTURED x6) [paper] | -0.26 | market's own p: pred 0.552, obs 0.500, gap +0.052 (se 0.199), n=6 | identical to market by construction | 09-11 | TOO FEW (n=6) [BASELINE: MARKET REFERENCE] |

- **M072** (F5 moneyline, public) `PUBLISHED_NOT_STAKED`: 17 F5 'flagged' recommendations on the Analyzer forward ledger (evidence/forward_ledger.jsonl, 2026-08-29..2026-09-26; 10 dated on or after 2026-09-10) carry a side and snapshot prices but no stake, no price rule and no grade.
- **M073** (F5 moneyline, shadow) `NEVER_PUBLISHED`: no MLB shadow entry of this market in any ledger read; shadow ledgers hold only: hits prop, in-play moneyline, moneyline, run line, runs-scored prop, total-bases prop.

### MLB pitcher props

| Row | Market | Rule / class / scope | Model (probability source) | Vis | N staked | W-L-P-V | Units | ROI | Mean CLV (pts) [95% CI] n | z vs market | Calibration | Brier ours - market | Span | Verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| M082 | pitcher props | none | - | public | 0 | - | - | - | - | - | - | - | - | **MISSING** NEVER_PUBLISHED |
| M083 | pitcher props | none | - | shadow | 0 | - | - | - | - | - | - | - | - | **MISSING** NEVER_PUBLISHED |
| M084 | pitcher props | none | - | paper | 0 | - | - | - | - | - | - | - | - | **MISSING** NEVER_PUBLISHED |

- **M082** (pitcher props, public) `NEVER_PUBLISHED`: no MLB public entry of this market in any ledger read; public ledgers hold only: hits prop, moneyline, run line, runs-scored prop, total-bases prop.
- **M083** (pitcher props, shadow) `NEVER_PUBLISHED`: no MLB shadow entry of this market in any ledger read; shadow ledgers hold only: hits prop, in-play moneyline, moneyline, run line, runs-scored prop, total-bases prop.
- **M084** (pitcher props, paper) `NEVER_PUBLISHED`: no MLB paper entry of this market in any ledger read; paper ledgers hold only: F5 moneyline, moneyline, run line, totals.

### MLB hitter props: hits

| Row | Market | Rule / class / scope | Model (probability source) | Vis | N staked | W-L-P-V | Units | ROI | Mean CLV (pts) [95% CI] n | z vs market | Calibration | Brier ours - market | Span | Verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| R085 | hits prop | V1 public / pick | V1 model (probability) | public | 71 | 45-26-0-0 | -5.84 | -8.2% | none measured (PROP_NOT_MEASURED x71) [card] | -0.38 | own p: pred 0.728, obs 0.634, gap +0.094 (se 0.053), n=71 | +0.0132 +/- 0.0091 (n=71) | 09-14..09-22 (8d) | NO EVIDENCE |
| R086 | hits prop | V2 public / pick | our_probability_used (0.038 markdown) | public | 15 | 7-8-0-1 | -2.85 | -19.0% | none measured (PROP_NOT_MEASURED x15) [card] | -0.68 | own p: pred 0.598, obs 0.467, gap +0.131 (se 0.127), n=15 | +0.0112 +/- 0.0121 (n=15) | 09-22..09-25 (4d) | TOO FEW (n=15) |
| R087 | hits prop | V2 public / fill / postseason | our_probability_used (0.038 markdown) | public | 2 | 0-2-0-0 | -2.00 | -100.0% | none measured (PROP_NOT_MEASURED x2) [card] | -1.48 | own p: pred 0.557, obs 0.000, gap +0.557 (se 0.351), n=2 | +0.0363 +/- 0.0028 (n=2) | 09-30 | TOO FEW (n=2) |
| R088 | hits prop | V2 public / fill | our_probability_used (0.038 markdown) | public | 1 | 1-0-0-1 | +0.70 | +70.4% | none measured (PROP_NOT_MEASURED x1) [card] | +0.89 | own p: pred 0.613, obs 1.000, gap -0.387 (se 0.487), n=1 | -0.0462 (n=1) | 09-25 | TOO FEW (n=1) |
| R089 | hits prop | V1 shadow / pick / postseason | V1 model (probability) | shadow | 3 | 2-1-0-0 | -0.02 | -0.7% | none measured (PROP_NOT_MEASURED x3) [card] | +0.13 | own p: pred 0.675, obs 0.667, gap +0.008 (se 0.270), n=3 | +0.0001 +/- 0.0290 (n=3) | 09-30 | TOO FEW (n=3) |
| R090 | hits prop | V1 shadow / pick | V1 model (probability) | shadow | 63 | 40-23-0-1 | -4.03 | -6.4% | none measured (PROP_NOT_MEASURED x63) [card] | -0.15 | own p: pred 0.710, obs 0.635, gap +0.075 (se 0.057), n=63 | +0.0075 +/- 0.0086 (n=63) | 09-23..09-27 (5d) | NO EVIDENCE |
| R091 | hits prop | V2 shadow A / pick | our_probability_used (0.038 markdown) | shadow | 13 | 9-4-0-3 | +2.87 | +22.1% | none measured (PROP_NOT_MEASURED x13) [card] | +1.13 | own p: pred 0.583, obs 0.692, gap -0.109 (se 0.136), n=13 | -0.0137 +/- 0.0150 (n=13) | 09-22..09-27 (4d) | TOO FEW (n=13) |
| R092 | hits prop | V2 shadow A / fill | our_probability_used (0.038 markdown) | shadow | 1 | 0-1-0-0 | -1.00 | -100.0% | none measured (PROP_NOT_MEASURED x1) [card] | -0.93 | own p: pred 0.561, obs 0.000, gap +0.561 (se 0.496), n=1 | +0.0984 (n=1) | 09-22 | TOO FEW (n=1) |
| R093 | hits prop | V2 shadow C / pick | our_probability_used (0.038 markdown) | shadow | 12 | 6-6-0-0 | -1.50 | -12.5% | none measured (PROP_NOT_MEASURED x12) [card] | -0.36 | own p: pred 0.593, obs 0.500, gap +0.093 (se 0.142), n=12 | +0.0047 +/- 0.0130 (n=12) | 09-22..09-25 (4d) | TOO FEW (n=12) |
| R094 | hits prop | V2 shadow C / fill / postseason | our_probability_used (0.038 markdown) | shadow | 2 | 0-2-0-0 | -2.00 | -100.0% | none measured (PROP_NOT_MEASURED x2) [card] | -1.48 | own p: pred 0.557, obs 0.000, gap +0.557 (se 0.351), n=2 | +0.0363 +/- 0.0028 (n=2) | 09-30 | TOO FEW (n=2) |
| R095 | hits prop | V2 shadow C / fill | our_probability_used (0.038 markdown) | shadow | 2 | 2-0-0-2 | +1.37 | +68.5% | none measured (PROP_NOT_MEASURED x2) [card] | +1.24 | own p: pred 0.603, obs 1.000, gap -0.397 (se 0.346), n=2 | -0.0308 +/- 0.0154 (n=2) | 09-25 | TOO FEW (n=2) |
| R096 | hits prop | V2 shadow E / pick | our_probability_used (0.038 markdown) | shadow | 5 | 2-3-0-0 | -1.75 | -35.0% | none measured (PROP_NOT_MEASURED x5) [card] | -0.85 | own p: pred 0.639, obs 0.400, gap +0.239 (se 0.215), n=5 | +0.0327 +/- 0.0265 (n=5) | 09-23..09-26 (4d) | TOO FEW (n=5) |
| R097 | hits prop | V2 shadow E / fill | our_probability_used (0.038 markdown) | shadow | 8 | 6-2-0-3 | +3.17 | +39.7% | none measured (PROP_NOT_MEASURED x8) [card] | +1.37 | own p: pred 0.547, obs 0.750, gap -0.203 (se 0.176), n=8 | -0.0085 +/- 0.0197 (n=8) | 09-22..09-27 (5d) | TOO FEW (n=8) |
| R098 | hits prop | MLB_VALUE_SHADOW_V1 B_HITS / pick | none frozen (other-books consensus is the market p) | shadow | 17 | 8-9-0-0 | -0.95 | -5.6% | none measured (PROP_NOT_MEASURED x17) [card] | -0.33 | NO_PROBABILITY_FROZEN | - | 09-22..09-26 (5d) | TOO FEW (n=17) |
| M099 | hits prop | none | - | paper | 0 | - | - | - | - | - | - | - | - | **MISSING** NEVER_PUBLISHED |

- **M099** (hits prop, paper) `NEVER_PUBLISHED`: no MLB paper entry of this market in any ledger read; paper ledgers hold only: F5 moneyline, moneyline, run line, totals.

### MLB hitter props: total bases

| Row | Market | Rule / class / scope | Model (probability source) | Vis | N staked | W-L-P-V | Units | ROI | Mean CLV (pts) [95% CI] n | z vs market | Calibration | Brier ours - market | Span | Verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| R100 | total-bases prop | V1 public / pick | V1 model (probability) | public | 46 | 33-13-0-1 | +6.21 | +13.5% | none measured (PROP_NOT_MEASURED x46) [card] | +1.67 | own p: pred 0.653, obs 0.717, gap -0.065 (se 0.070), n=46 | -0.0069 +/- 0.0083 (n=46) | 09-14..09-22 (9d) | NO EVIDENCE |
| R101 | total-bases prop | V2 public / pick | our_probability_used (0.038 markdown) | public | 15 | 7-8-0-1 | -2.89 | -19.3% | none measured (PROP_NOT_MEASURED x15) [card] | -0.61 | own p: pred 0.595, obs 0.467, gap +0.128 (se 0.127), n=15 | +0.0135 +/- 0.0135 (n=15) | 09-22..09-25 (4d) | TOO FEW (n=15) |
| R102 | total-bases prop | V2 public / fill / postseason | our_probability_used (0.038 markdown) | public | 1 | 1-0-0-0 | +0.65 | +64.5% | none measured (PROP_NOT_MEASURED x1) [card] | +0.86 | own p: pred 0.611, obs 1.000, gap -0.389 (se 0.487), n=1 | -0.0310 (n=1) | 09-30 | TOO FEW (n=1) |
| R103 | total-bases prop | V2 public / fill | our_probability_used (0.038 markdown) | public | 15 | 11-4-0-0 | +3.94 | +26.3% | none measured (PROP_NOT_MEASURED x15) [card] | +1.40 | own p: pred 0.594, obs 0.733, gap -0.140 (se 0.127), n=15 | -0.0166 +/- 0.0097 (n=15) | 09-22..09-27 (6d) | TOO FEW (n=15) |
| R104 | total-bases prop | V1 shadow / pick | V1 model (probability) | shadow | 26 | 15-11-0-1 | -2.78 | -10.7% | none measured (PROP_NOT_MEASURED x26) [card] | -0.28 | own p: pred 0.666, obs 0.577, gap +0.090 (se 0.092), n=26 | +0.0064 +/- 0.0128 (n=26) | 09-23..09-27 (5d) | TOO FEW (n=26) |
| R105 | total-bases prop | V2 shadow A / pick / postseason | our_probability_used (0.038 markdown) | shadow | 7 | 5-2-0-0 | +1.72 | +24.6% | none measured (PROP_NOT_MEASURED x7) [card] | +0.93 | own p: pred 0.568, obs 0.714, gap -0.147 (se 0.187), n=7 | +0.0129 +/- 0.0175 (n=7) | 09-30 | TOO FEW (n=7) |
| R106 | total-bases prop | V2 shadow A / pick | our_probability_used (0.038 markdown) | shadow | 64 | 40-24-0-4 | +5.53 | +8.6% | none measured (PROP_NOT_MEASURED x64) [card] | +1.30 | own p: pred 0.603, obs 0.625, gap -0.022 (se 0.061), n=64 | -0.0022 +/- 0.0089 (n=64) | 09-22..09-27 (6d) | NO EVIDENCE |
| R107 | total-bases prop | V2 shadow C / pick | our_probability_used (0.038 markdown) | shadow | 12 | 6-6-0-0 | -1.53 | -12.7% | none measured (PROP_NOT_MEASURED x12) [card] | -0.28 | own p: pred 0.590, obs 0.500, gap +0.090 (se 0.142), n=12 | +0.0087 +/- 0.0151 (n=12) | 09-22..09-25 (3d) | TOO FEW (n=12) |
| R108 | total-bases prop | V2 shadow C / fill / postseason | our_probability_used (0.038 markdown) | shadow | 1 | 1-0-0-0 | +0.83 | +82.6% | none measured (PROP_NOT_MEASURED x1) [card] | +0.97 | own p: pred 0.550, obs 1.000, gap -0.450 (se 0.498), n=1 | -0.0321 (n=1) | 09-30 | TOO FEW (n=1) |
| R109 | total-bases prop | V2 shadow C / fill | our_probability_used (0.038 markdown) | shadow | 16 | 12-4-0-0 | +4.76 | +29.7% | none measured (PROP_NOT_MEASURED x16) [card] | +1.60 | own p: pred 0.588, obs 0.750, gap -0.162 (se 0.123), n=16 | -0.0192 +/- 0.0082 (n=16) | 09-22..09-27 (6d) | TOO FEW (n=16) |
| R110 | total-bases prop | V2 shadow E / pick | our_probability_used (0.038 markdown) | shadow | 12 | 7-5-0-0 | -0.62 | -5.2% | none measured (PROP_NOT_MEASURED x12) [card] | +0.00 | own p: pred 0.649, obs 0.583, gap +0.066 (se 0.138), n=12 | -0.0026 +/- 0.0190 (n=12) | 09-22..09-26 (5d) | TOO FEW (n=12) |
| R111 | total-bases prop | V2 shadow E / fill | our_probability_used (0.038 markdown) | shadow | 7 | 6-1-0-1 | +2.75 | +39.3% | none measured (PROP_NOT_MEASURED x7) [card] | +1.46 | own p: pred 0.601, obs 0.857, gap -0.256 (se 0.185), n=7 | -0.0037 +/- 0.0100 (n=7) | 09-22..09-26 (5d) | TOO FEW (n=7) |
| R112 | total-bases prop | MLB_VALUE_SHADOW_V1 A_TOTAL_BASES / pick | none frozen (other-books consensus is the market p) | shadow | 1 | 1-0-0-0 | +1.40 | +140.0% | none measured (PROP_NOT_MEASURED x1) [card] | +1.15 | NO_PROBABILITY_FROZEN | - | 09-26 | TOO FEW (n=1) |
| M113 | total-bases prop | none | - | paper | 0 | - | - | - | - | - | - | - | - | **MISSING** NEVER_PUBLISHED |

- **M113** (total-bases prop, paper) `NEVER_PUBLISHED`: no MLB paper entry of this market in any ledger read; paper ledgers hold only: F5 moneyline, moneyline, run line, totals.

### MLB hitter props: runs scored

| Row | Market | Rule / class / scope | Model (probability source) | Vis | N staked | W-L-P-V | Units | ROI | Mean CLV (pts) [95% CI] n | z vs market | Calibration | Brier ours - market | Span | Verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| M114 | runs-scored prop | none | - | public | 0 | - | - | - | - | - | - | - | - | **MISSING** PUBLISHED_UNGRADED |
| M115 | runs-scored prop | none | - | shadow | 0 | - | - | - | - | - | - | - | - | **MISSING** PUBLISHED_UNGRADED |
| M116 | runs-scored prop | none | - | paper | 0 | - | - | - | - | - | - | - | - | **MISSING** NEVER_PUBLISHED |

- **M114** (runs-scored prop, public) `PUBLISHED_UNGRADED`: 4 entries recorded, none staked (VOID x4); reasons: no settlement rule for market 'batter_runs_scored' x4; rules: V2 public.
- **M115** (runs-scored prop, shadow) `PUBLISHED_UNGRADED`: 18 entries recorded, none staked (VOID x18); reasons: no settlement rule for market 'batter_runs_scored' x18; rules: V2 shadow A, V2 shadow C, V2 shadow E.
- **M116** (runs-scored prop, paper) `NEVER_PUBLISHED`: no MLB paper entry of this market in any ledger read; paper ledgers hold only: F5 moneyline, moneyline, run line, totals.

### NFL sides

| Row | Market | Rule / class / scope | Model (probability source) | Vis | N staked | W-L-P-V | Units | ROI | Mean CLV (pts) [95% CI] n | z vs market | Calibration | Brier ours - market | Span | Verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| R117 | moneyline | NFL V1 / pick | none frozen (market p only) | public | 10 | 7-3-0-0 | -0.26 | -2.6% | -2.32 [-3.79, -0.85] n=3 of 10 [card] | -0.16 | NO_PROBABILITY_FROZEN | - | 09-17..09-21 (3d) | TOO FEW (n=10) |
| R118 | moneyline | NFL V2 / pick | none frozen (market p only) | public | 1 | 1-0-0-0 | +0.93 | +92.6% | none measured (CLOSE_STALE x1) [card] | +0.85 | NO_PROBABILITY_FROZEN | - | 09-27 | TOO FEW (n=1) |
| M119 | moneyline | none | - | shadow | 0 | - | - | - | - | - | - | - | - | **MISSING** NEVER_PUBLISHED |
| M120 | moneyline | none | - | paper | 0 | - | - | - | - | - | - | - | - | **MISSING** PUBLISHED_UNGRADED |

- **M119** (moneyline, shadow) `NEVER_PUBLISHED`: no NFL shadow entry of this market in any ledger read; shadow ledgers hold only: nothing.
- **M120** (moneyline, paper) `PUBLISHED_UNGRADED`: 45 entries recorded, none staked (VOID x45); reasons: not an MLB event -- a non-MLB game wagered by the pre-2026-09-21 engin x45; rules: paper TOP_RANKED_PLAY_PER_SYSTEM_PER_GAME_V1.

### NFL totals

| Row | Market | Rule / class / scope | Model (probability source) | Vis | N staked | W-L-P-V | Units | ROI | Mean CLV (pts) [95% CI] n | z vs market | Calibration | Brier ours - market | Span | Verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| M121 | totals | none | - | public | 0 | - | - | - | - | - | - | - | - | **MISSING** NEVER_PUBLISHED |
| M122 | totals | none | - | shadow | 0 | - | - | - | - | - | - | - | - | **MISSING** NEVER_PUBLISHED |
| M123 | totals | none | - | paper | 0 | - | - | - | - | - | - | - | - | **MISSING** PUBLISHED_UNGRADED |

- **M121** (totals, public) `NEVER_PUBLISHED`: no NFL public entry of this market in any ledger read; public ledgers hold only: moneyline; published card rows with a total pick: 0 of 13; totals_paused true on 0.
- **M122** (totals, shadow) `NEVER_PUBLISHED`: no NFL shadow entry of this market in any ledger read; shadow ledgers hold only: nothing.
- **M123** (totals, paper) `PUBLISHED_UNGRADED`: 45 entries recorded, none staked (VOID x45); reasons: not an MLB event -- a non-MLB game wagered by the pre-2026-09-21 engin x45; rules: paper TOP_RANKED_PLAY_PER_SYSTEM_PER_GAME_V1.

### NFL player props

| Row | Market | Rule / class / scope | Model (probability source) | Vis | N staked | W-L-P-V | Units | ROI | Mean CLV (pts) [95% CI] n | z vs market | Calibration | Brier ours - market | Span | Verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| M124 | player props | none | - | public | 0 | - | - | - | - | - | - | - | - | **MISSING** NEVER_PUBLISHED |
| M125 | player props | none | - | shadow | 0 | - | - | - | - | - | - | - | - | **MISSING** NEVER_PUBLISHED |
| M126 | player props | none | - | paper | 0 | - | - | - | - | - | - | - | - | **MISSING** NEVER_PUBLISHED |

- **M124** (player props, public) `NEVER_PUBLISHED`: no NFL public entry of this market in any ledger read; public ledgers hold only: moneyline; published NFL card rows with a prop pick: 0 of 13.
- **M125** (player props, shadow) `NEVER_PUBLISHED`: no NFL shadow entry of this market in any ledger read; shadow ledgers hold only: nothing; published NFL card rows with a prop pick: 0 of 13.
- **M126** (player props, paper) `NEVER_PUBLISHED`: no NFL paper entry of this market in any ledger read; paper ledgers hold only: moneyline, totals; published NFL card rows with a prop pick: 0 of 13.

### UFC sides

| Row | Market | Rule / class / scope | Model (probability source) | Vis | N staked | W-L-P-V | Units | ROI | Mean CLV (pts) [95% CI] n | z vs market | Calibration | Brier ours - market | Span | Verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| R127 | moneyline | UFC V1 / pick | none frozen (market p only; price = average of books) | public | 6 | 5-1-0-1 | +2.50 | +41.7% | -1.05 [-4.48, +2.37] n=4 of 6 [card (consensus price)] | +1.29 | NO_PROBABILITY_FROZEN | - | 09-22..09-26 (2d) | TOO FEW (n=6) |
| M128 | moneyline | none | - | shadow | 0 | - | - | - | - | - | - | - | - | **MISSING** NEVER_PUBLISHED |
| M129 | moneyline | none | - | paper | 0 | - | - | - | - | - | - | - | - | **MISSING** NEVER_PUBLISHED |

- **M128** (moneyline, shadow) `NEVER_PUBLISHED`: no MMA shadow entry of this market in any ledger read; shadow ledgers hold only: nothing.
- **M129** (moneyline, paper) `NEVER_PUBLISHED`: no MMA paper entry of this market in any ledger read; paper ledgers hold only: nothing.

### MLB in-play moneyline (not a required family)

| Row | Market | Rule / class / scope | Model (probability source) | Vis | N staked | W-L-P-V | Units | ROI | Mean CLV (pts) [95% CI] n | z vs market | Calibration | Brier ours - market | Span | Verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| R130 | in-play moneyline | live mlb_favorite_trails_after_3 / candidate | none frozen | shadow | 6 | 3-3-0-0 | -0.01 | -0.2% | none measured (IN_PLAY_NO_CLOSING_LINE x6) [none] | - | NO_PROBABILITY_FROZEN | - | 09-22..09-25 (4d) | TOO FEW (n=6) |
| R131 | in-play moneyline | live mlb_starter_pulled_early / candidate / postseason | none frozen | shadow | 1 | 0-1-0-0 | -1.00 | -100.0% | none measured (IN_PLAY_NO_CLOSING_LINE x1) [none] | - | NO_PROBABILITY_FROZEN | - | 09-30 | TOO FEW (n=1) |
| R132 | in-play moneyline | live mlb_starter_pulled_early / candidate | none frozen | shadow | 61 | 19-42-0-0 | -10.48 | -17.2% | none measured (IN_PLAY_NO_CLOSING_LINE x61) [none] | - | NO_PROBABILITY_FROZEN | - | 09-22..09-27 (6d) | NO EVIDENCE |

## Paper engine inventory

Stores read: decisions `evidence/decisions_v2.jsonl` (hot file plus archive segments through `src/pipeline/store_archive.py`; 33560 lines, 26630 dated 2026-09-10 or later, 6874 dated before it and skipped unparsed, 0 dated inside the sealed window and skipped unparsed), wagers `evidence/paper_wagers_v2.jsonl` (4650 lines, 3501 in window), and the settlement store `data/paper_accounts/<system_id>.jsonl` written by `src.engine.settle_slate.run_settle` (one hash-chained ledger per system, 56 files).

**The wagers are settled.** 2977 settled account rows dated 2026-09-10 or later; 2977 joined to a wager and a decision (both joins unique); 2807 kept as live pre-commencement entries. Excluded by name: CONTROL run line replay x1; CONTROL totals replay x2; FORWARD_TEST F5 moneyline replay x29; FORWARD_TEST moneyline replay x100; MARKET_REFERENCE F5 moneyline replay x32; MARKET_REFERENCE run line replay x2; MARKET_REFERENCE totals replay x4. Account rows dated before the window and not read: 1149 (2023-04: 38, 2026-08: 36, 2026-09: 1075).

Some of those pre-window account rows carry a 2023 date (control systems); they sit inside the 2026 paper stores and are not read. They are an anomaly in the store, listed here so nobody finds them by accident.

Only decisions stamped `live_pre_commencement` count. A `replay` decision was recorded after its own game's first pitch, so it is hindsight and is excluded (doctrine section 6).

**Wagers with no settlement row** (the settle step refuses a whole date while any wagered game lacks a result, `run_settle` in `src/engine/settle_slate.py`): 2026-09-17: 68 of 68 wagers (the whole date); 2026-09-22: 323 of 323 wagers (the whole date); 2026-09-27: 108 of 108 wagers (the whole date); 2026-10-01: 25 of 25 wagers (the whole date). These are not in any row above, so the paper record omits those days entirely.

**Non-MLB wagers voided by design:** nfl x90 (the pre-2026-09-21 engine built MLB boards from every sport; such wagers settle VOID and are never staked).

**Decision, wager and settlement counts by class and market** (window; a decision is a candidate, a wager is the top-ranked play per system per game, a settled row is a wager with an account entry):

| System class | Market | Decisions | play | refused | Wagers | Settled rows | Kept as entries |
|---|---|---|---|---|---|---|---|
| CONTROL | moneyline | 1607 | 1607 | 0 | 264 | 221 | 221 |
| CONTROL | run line | 2581 | 296 | 2285 | 37 | 30 | 29 |
| CONTROL | totals | 3454 | 2580 | 874 | 366 | 310 | 308 |
| FORWARD_TEST | F5 moneyline | 74 | 74 | 0 | 74 | 51 | 22 |
| FORWARD_TEST | moneyline | 3560 | 3560 | 0 | 1392 | 1224 | 1124 |
| MARKET_REFERENCE | F5 moneyline | 70 | 70 | 0 | 70 | 50 | 18 |
| MARKET_REFERENCE | moneyline | 3214 | 3214 | 0 | 528 | 442 | 442 |
| MARKET_REFERENCE | run line | 5162 | 592 | 4570 | 74 | 60 | 58 |
| MARKET_REFERENCE | totals | 6908 | 5160 | 1748 | 696 | 589 | 585 |

**FORWARD_TEST systems:** 40 distinct systems with decisions in window; `p_model` is frozen on 0 of their decisions (provenance `none`), so no FORWARD_TEST row has a calibration. CONTROL decisions freeze a placeholder 0.5; MARKET_REFERENCE decisions freeze the board consensus as `p_model` (provenance `market_derived`).

**Not measurable for paper:** CLV on F5 (the multibook store has no F5 closing-board shape; `clv.MARKET_SHAPES` knows h2h, spreads, totals); calibration for every FORWARD_TEST and CONTROL row; any prop (the paper engine registers h2h, spreads, totals and F5 only).

## Entries counted and never staked

Withdrawn entries and entries with no WIN or LOSS (void, push, unresolved), by visibility, rule, market and class. Counted, never staked; the results shown for withdrawn entries are what they would have been and no unit is attributed to them.

| Vis | Sport | Market | Rule | Class | Entries | Void | Push | Unresolved | Withdrawn (result) |
|---|---|---|---|---|---|---|---|---|---|
| paper | mlb | F5 moneyline | FORWARD_TEST | pick | 12 | 0 | 12 | 0 | - |
| paper | mlb | F5 moneyline | MARKET_REFERENCE | pick | 6 | 0 | 6 | 0 | - |
| paper | mlb | totals | CONTROL | pick | 8 | 0 | 8 | 0 | - |
| paper | mlb | totals | MARKET_REFERENCE | pick | 11 | 0 | 11 | 0 | - |
| paper | nfl | moneyline | CONTROL | pick | 15 | 15 | 0 | 0 | - |
| paper | nfl | moneyline | MARKET_REFERENCE | pick | 30 | 30 | 0 | 0 | - |
| paper | nfl | totals | CONTROL | pick | 15 | 15 | 0 | 0 | - |
| paper | nfl | totals | MARKET_REFERENCE | pick | 30 | 30 | 0 | 0 | - |
| public | mlb | hits prop | V2 public | fill | 1 | 1 | 0 | 0 | - |
| public | mlb | hits prop | V2 public | pick | 1 | 1 | 0 | 0 | - |
| public | mlb | hits prop | V2 public | withdrawn | 2 | 0 | 0 | 0 | WIN x2 |
| public | mlb | moneyline | V2 public | fill | 1 | 1 | 0 | 0 | - |
| public | mlb | runs-scored prop | V2 public | fill | 1 | 1 | 0 | 0 | - |
| public | mlb | runs-scored prop | V2 public | pick | 3 | 3 | 0 | 0 | - |
| public | mlb | total-bases prop | V1 public | pick | 1 | 1 | 0 | 0 | - |
| public | mlb | total-bases prop | V2 public | pick | 1 | 1 | 0 | 0 | - |
| public | mlb | total-bases prop | V2 public | withdrawn | 3 | 0 | 0 | 0 | LOSS x1, VOID x1, WIN x1 |
| public | mma | moneyline | UFC V1 | pick | 1 | 1 | 0 | 0 | - |
| shadow | mlb | hits prop | V1 shadow | pick | 1 | 1 | 0 | 0 | - |
| shadow | mlb | hits prop | V2 shadow A | pick | 3 | 3 | 0 | 0 | - |
| shadow | mlb | hits prop | V2 shadow C | fill | 2 | 2 | 0 | 0 | - |
| shadow | mlb | hits prop | V2 shadow C | withdrawn | 2 | 0 | 0 | 0 | WIN x2 |
| shadow | mlb | hits prop | V2 shadow E | fill | 3 | 3 | 0 | 0 | - |
| shadow | mlb | moneyline | V2 shadow A | pick | 1 | 1 | 0 | 0 | - |
| shadow | mlb | moneyline | V2 shadow A | withdrawn | 4 | 0 | 0 | 0 | LOSS x1, WIN x3 |
| shadow | mlb | moneyline | V2 shadow C | fill | 1 | 1 | 0 | 0 | - |
| shadow | mlb | moneyline | V2 shadow C | withdrawn | 1 | 0 | 0 | 0 | WIN x1 |
| shadow | mlb | runs-scored prop | V2 shadow A | pick | 6 | 6 | 0 | 0 | - |
| shadow | mlb | runs-scored prop | V2 shadow C | fill | 2 | 2 | 0 | 0 | - |
| shadow | mlb | runs-scored prop | V2 shadow C | pick | 3 | 3 | 0 | 0 | - |
| shadow | mlb | runs-scored prop | V2 shadow E | fill | 1 | 1 | 0 | 0 | - |
| shadow | mlb | runs-scored prop | V2 shadow E | pick | 6 | 6 | 0 | 0 | - |
| shadow | mlb | total-bases prop | V1 shadow | pick | 1 | 1 | 0 | 0 | - |
| shadow | mlb | total-bases prop | V2 shadow A | pick | 4 | 4 | 0 | 0 | - |
| shadow | mlb | total-bases prop | V2 shadow C | withdrawn | 1 | 0 | 0 | 0 | LOSS x1 |
| shadow | mlb | total-bases prop | V2 shadow E | fill | 1 | 1 | 0 | 0 | - |
| shadow | mlb | total-bases prop | V2 shadow E | withdrawn | 2 | 0 | 0 | 0 | VOID x2 |

## Ledgers read and integrity

| Ledger | Status | Rows | Settled dates | First | Last | Corrections folded |
|---|---|---|---|---|---|---|
| V1 public | read | 518 | 13 | 2026-09-10 | 2026-09-22 | 0 |
| V1 shadow | read | 605 | 7 | 2026-09-23 | 2026-09-30 | 0 |
| V2 public | read | 84 | 8 | 2026-09-22 | 2026-09-30 | 0 |
| V2 shadow A | read | 117 | 8 | 2026-09-22 | 2026-09-30 | 0 |
| V2 shadow C | read | 80 | 8 | 2026-09-22 | 2026-09-30 | 0 |
| V2 shadow E | read | 59 | 8 | 2026-09-22 | 2026-09-30 | 0 |
| NFL | read | 17 | 4 | 2026-09-17 | 2026-09-27 | 0 |
| UFC | read | 51 | 2 | 2026-09-22 | 2026-09-26 | 0 |
| MLB value shadow A_TOTAL_BASES | read | 1 decisions | 1 settled | - | - | 0 |
| MLB value shadow B_HITS | read | 17 decisions | 17 settled | - | - | 0 |
| MLB value shadow C_RUN_LINE | read | 5 decisions | 5 settled | - | - | 0 |

Integrity check: 0 of 3430 staked entries (all visibilities) have flat-stake units recomputed from price and result differing from the ledger's own profit_units by more than rounding.

## What this says about where to build

**1. Which families have enough data to say anything (n >= 30), and what they say.** Counted from rows with n staked >= 30. A row is one rule, class, scope and model; the ranges below run across those rows and are never pooled.

- **MLB moneyline**: 26 row(s) (paper 24, public 1, shadow 1; 3 of them baseline, not a model). ROI -17.1 to +12.5%; z vs market -0.72 to +1.47; CLV measured (n >= 2) on 26 of them, mean -1.23 to -0.76 pts, negative on 26 of 26; verdicts NO EVIDENCE 26.
- **MLB totals**: 3 row(s) (paper 3; 3 of them baseline, not a model). ROI -14.9 to +9.7%; z vs market -2.05 to +2.07; CLV measured (n >= 2) on 3 of them, mean -1.65 to -1.45 pts, negative on 3 of 3; verdicts NO EVIDENCE 3.
- **MLB hitter props: hits**: 2 row(s) (public 1, shadow 1). ROI -8.2 to -6.4%; z vs market -0.38 to -0.15; CLV measured (n >= 2) on 0 of them, mean n/a pts, negative on 0 of 0; verdicts NO EVIDENCE 2.
- **MLB hitter props: total bases**: 2 row(s) (public 1, shadow 1). ROI +8.6 to +13.5%; z vs market +1.30 to +1.67; CLV measured (n >= 2) on 0 of them, mean n/a pts, negative on 0 of 0; verdicts NO EVIDENCE 2.
- **MLB in-play moneyline (not a required family)**: 1 row(s) (shadow 1). ROI -17.2%; z vs market n/a; CLV measured (n >= 2) on 0 of them, mean n/a pts, negative on 0 of 0; verdicts NO EVIDENCE 1.
- Across every row with CLV measured on at least 2 entries (46 rows, any n staked): mean CLV is positive on 2 and has a 95% interval entirely above zero on 0. CLV is biased negative by about half the hold, so a negative mean alone is not a finding either.
- 0 row(s) are CANDIDATE. Families with no row at n >= 30: MLB run line, MLB first-five (F5), MLB pitcher props, MLB hitter props: runs scored, NFL sides, NFL totals, NFL player props, UFC sides.

**2. Families the product sells today but cannot measure, and the one missing field or capture that would make each measurable.** A family counts as sold when it has a public row, or a public MISSING cell whose reason is PUBLISHED_UNGRADED or PUBLISHED_NOT_STAKED.

- **MLB moneyline**: measurable, partly. CLV refused on 59 staked entries (CLOSE_STALE x55, CLOSING_BOARD_THIN x1, NO_EVENT x3). Missing capture: a closing board within 90 minutes of first pitch for every game.
- **MLB run line** (1 staked across 1 public row(s), n < 30 each): CLV measured on 0. The sample is the blocker; no field is missing.
- **MLB hitter props: hits** (89 staked across 4 public row(s)): no closing price, because `card_clv` refuses every prop. Missing capture: a closing prop board per player and line, from at least 6 books, within 90 minutes of first pitch.
- **MLB hitter props: total bases** (77 staked across 4 public row(s)): no closing price, because `card_clv` refuses every prop. Missing capture: a closing prop board per player and line, from at least 6 books, within 90 minutes of first pitch.
- **NFL sides** (11 staked): no model probability and no observed time are frozen on the pick, so neither calibration nor closing-line value can be tested (the closing-line check cannot rule out a decision board that is the closing board). Missing field: `observed_utc` on the pick for CLV; `model_probability` for calibration.
- **UFC sides** (n=6 staked, TOO FEW): the sample is the blocker, not a field. CLV measured on 4; `observed_utc` is not frozen on the pick. Missing field: `observed_utc` (so a decision board that is the close can be ruled out); n >= 30 settled bouts.
- **MLB first-five (F5)**: shown as flags only (17 F5 'flagged' recommendations on the Analyzer forward ledger (evidence/forward_ledger.jsonl, 2026-08-29..2026-09-26; 10 dated on or after 2026-09-10) carry a side and snapshot prices but no stake, no price rule and no grade). Missing: a frozen side, price and stake rule on the flag, so it can be graded; F5 has no closing-board shape for CLV.
- **MLB hitter props: runs scored**: published but never graded (4 entries recorded, none staked (VOID x4); reasons: no settlement rule for market 'batter_runs_scored' x4; rules: V2 public). Missing: a grade. The settlement rule was added after these entries were written and the VOID rows stand (see `docs/audit/2026-10-01/LOSS_DIAGNOSIS.md`); CLV would also be refused (prop).

**3. The owner's hypothesis: props may be a better modelling opportunity than moneylines.** Descriptive, not a finding. Probability quality relative to price is the paired Brier difference against the market's own frozen probability (ours minus market; positive = ours worse), from card and shadow rows with n >= 30.

- Moneyline rows (n >= 30): V1 public moneyline n=104 +0.0073 (se 0.0052); V1 shadow moneyline n=38 +0.0059 (se 0.0094).
- Prop rows (n >= 30): V1 public hits prop n=71 +0.0132 (se 0.0091); V1 shadow hits prop n=63 +0.0075 (se 0.0086); V1 public total-bases prop n=46 -0.0069 (se 0.0083); V2 shadow A total-bases prop n=64 -0.0022 (se 0.0089).
- Of 6 such rows, 2 have ours better than the market (negative difference) and 0 have that difference more than 1.96 se below zero.
- Closing price: moneyline CLV is measured on part of the sample; prop CLV is never measured (no closing prop board), so for props nothing says whether the price taken beat the close.
- Paper: FORWARD_TEST and CONTROL rows freeze no model probability and no paper row covers a prop, so paper cannot speak to props or to probability quality; MARKET_REFERENCE rows are the market itself.
- What the data can say: the Brier differences above, per row, with their standard errors. What it cannot say: whether props are the better opportunity. Hit rate and ROI at the price taken are not probability quality relative to price; the rows carry n = 38 to 104 over a few weeks of games and share days and games with each other.

