# Prop experiment inventory

**Written 2026-10-01. A measurement of INPUTS, not an evaluation.** Nothing here
fits, tunes or scores a model on outcomes; no win rate and no ROI is computed
for any new slice (the allowed descriptive rows are in
`docs/PERFORMANCE_MATRIX.md`, cited below). No rule, gate or threshold changes.
Numbers come from the repo's own stores; each carries the store path and how it
was counted. Every table in the GENERATED block is regenerated, byte for byte,
by

    python3 scripts/prop_inventory.py --raw-scan \
        --statcast-manifest <main checkout>/data/historical/statcast/manifest.json \
        --update-doc docs/PROP_EXPERIMENT_INVENTORY.md

(read-only; standard library plus the repo's own pure helpers; tests in
`tests/test_prop_inventory.py`). The Statcast manifest is the one input not in a
worktree checkout (it is untracked and lives only in the main checkout); the run
above reads that one metadata file from there.

Data as of worktree commit `a942daee`. The prop stores, the credit log, the
event map and the box store in this worktree have the same line counts as the
main checkout at the time of writing (prop_prices 6,046; prop_listing 3,944;
batter_props 146,655; credit_log 8,667; boxscores_2026 12,516), so this is not a
stale copy of those stores. Newer runner data commits on the remote were not
fetched.

## The question, and the trap

The owner's hypothesis: props may be a better modelling opportunity than
moneylines. The trap: "a more predictable outcome" is not "a better betting
market", because the book may price it better too. What matters is probability
quality relative to price. So every row below asks the same four things: is the
price captured, how wide is the margin the bettor pays, can the outcome be
graded without a human, and how soon can a paired comparison against the
de-vigged market reach a sample that can say anything.

Where we stand (from `docs/PERFORMANCE_MATRIX.md`, section 3 and the MISSING
rows, not recomputed): no market is a CANDIDATE; moneyline closing-line value is
negative on 26 of 26 rows; the paired Brier difference against the market for
props is within noise both ways (n 46 to 104); prop closing-line value has never
been measured; pitcher props and NFL props have never been published.

## Bottom line

1. **Only three of the ten families are captured at all**: pitcher strikeouts,
   batter hits, batter total bases. Pitcher outs, hits allowed, earned runs and
   all four NFL families have zero rows in every prop store and zero raw
   responses in the 4,573-file raw archive. For them every price, book, margin
   and sample cell is UNKNOWN, and the only truthful sample size is zero.
2. **The margin is not the story.** Median two-sided margin is 6.5% (pitcher
   strikeouts), 6.8% (batter hits) and 7.0% (batter total bases); moneylines ran
   3.65% in `docs/PROP_MARKET_ECONOMICS.md` (written 2026-09-10 from a different
   slice: not re-measured here). A prop bettor pays roughly twice the margin, and
   today a prop line has a median of 3 to 6 two-sided books against 11 for a
   moneyline in that document. That bar is what a
   candidate's probability has to clear, and it is why price improvement
   (shopping) is reported separately and never as edge.
3. **Settlement is automatic for the six MLB families and does not exist for
   NFL.** MLB: `src/pipeline/boxscores.py` plus `src/board/settle_props.py`.
   NFL: no module in `src/` reads a player's passing, receiving or rushing yards.
4. **No inferential read can finish in 2026.** The postseason has at most 53
   games by format (best-of-3, 5, 7, 7), 10 of which are dated 2026-09-29 to
   2026-10-01 in the event map, and 2 to 4 a day until about 2026-11-01. The
   regular season ended 2026-09-27. Batter total bases is the only captured
   family with enough contracts per game (about 16) to say anything about the
   postseason alone, and even that is an underpowered, separately labelled read.
   The earliest confirmatory sample for any family is the 2027 regular season
   (opening day: not in the repo, UNKNOWN).
5. **Ranking by information gained per credit and per week**: (1) batter total
   bases, (2) pitcher strikeouts. Reasons and the families not worth testing now
   are at the end.

## What was not opened, and why

- `data/historical/mlb_results.csv`: **never opened**. It is the results store
  and holds sealed-window outcomes.
- `evidence/` (every ledger and the shadow stores): not opened. This inventory
  needs no decision, only inputs; the performance matrix already reads them.
- `data/archive/historical/*` (2023 to 2025 box scores, first-five odds, odds
  history): not opened. 2025 is tuning-only, nothing here tunes.
- `data/live/mlb/*.jsonl`, `odds_multibook.jsonl`, `odds_snapshots.jsonl`,
  `derivative_markets.jsonl`: not opened (not prop stores).
- `data/historical/pitcher_logs_2025.jsonl`, `bullpen_log_2025.jsonl`: exist only in
  the main checkout (names listed, not opened).
- Opened, with the sealed window gated on the raw line before parsing (a line
  dated 2026-01-01 to 2026-08-27 is counted and dropped unparsed; Table 6 has the
  counts): `pitcher_logs.jsonl` (7,745 sealed lines skipped), `bullpen_log.jsonl`
  (17,115 skipped), `event_game_map.jsonl` (6 skipped), plus the stores with 0
  sealed lines (prop stores, `boxscores_2026.jsonl`, both credit logs, lineups).
  Only dates were read from the two historical stores; no stat value.
- A caveat on my own process: before the script existed I ran one exploratory
  count over `boxscores_2026.jsonl` that parsed every line and grouped by month
  and row type. The script's gate later showed that file holds 0 sealed-window
  lines (it starts 2026-08-30), so no sealed outcome was read, but the
  exploration did not use the gate. Everything in this document comes from the
  gated script.

## The inventory, one row per family

The numeric columns are in the generated tables below (Tables 1 to 3). This table
carries the qualitative columns. "Settleable" counts eligible contracts whose
player has a row of the right type in the box store; presence only, the stat was
not read.

| Family | Captured today (store, key) | Forecast target and data completeness | Baseline and candidate | Closing-line value: what capture is needed | Settlement |
|---|---|---|---|---|---|
| MLB pitcher strikeouts | YES. `data/processed/prop_prices.jsonl`, `pitcher_strikeouts`, written by `src/pipeline/prop_prices.py` at three slots per game (T-3h, T-90m, T-30m), 1 credit per snapshot. 19 dates since 2026-09-10; no capture 2026-09-20, 09-28, 09-29 | Target: the starter's strikeouts. Features: pitcher game logs (2023: 8,888 lines; 2024: 7,837; 2026 unsealed 553, last date **2026-09-07**; the 2025 file is main-checkout-only); posted lineups from 2026-09-10; handedness (1,642 players); pitcher arsenal as of 2026-09-08 (a season-to-date leaderboard, not point in time); Statcast pitches to **2024-09-30 only** (main checkout only). Absent: any point-in-time 2026 per-pitch feature; opposing batters' strikeout rates exist point in time only from the box store (2026-08-30 onward) and the 2025 archive (not opened), because every 2026 row before 2026-08-28 sits in the sealed window | Baseline: de-vigged per-book proportional consensus (`src/analysis/prices.snapshot`, six-book floor). Candidate: **none exists in the repo.** `src/analysis/playerprops.py` is hitters only; `derivative_prices.py` ranks strikeout prices but computes no probability. Would need building | **Already captured**: the T-30m board exists for 83.9% of captured games (median lead 28.7 min), and 55.2% of lines have six or more two-sided books (176 of the 304 eligible lines on a board 90 minutes or less before first pitch). Missing: nothing for the board; the gap is slate coverage (62.2% of games, from credit-floor starvation) | YES. `src/board/settle_props.py` rule `pitcher_strikeouts` -> `k`; box rows from `src/pipeline/boxscores.py`. Gap: box rows carry no starter flag, so a scratched starter who relieved would grade as a start; the registration must define the starter test before any grade |
| MLB pitcher outs | NO. 0 rows in any store, 0 raw responses; the provider documents `pitcher_outs` | Target: outs recorded (box `outs`). Same pitcher features as above | Baseline: UNKNOWN (no quotes). Candidate: none; would need building | Capture does not exist. Cost in Table 3 (1 credit per game per snapshot per region) | YES. rule `pitcher_outs` -> `outs`. Same starter-flag gap |
| MLB hits allowed | NO (same) | Target: hits allowed (`h`). Same features | none | same | YES. rule `pitcher_hits_allowed` -> `h` |
| MLB earned runs | NO (same) | Target: earned runs (`er`). Same features | none | same | YES. rule `pitcher_earned_runs` -> `er` |
| MLB batter hits | YES. `data/processed/batter_props.jsonl`, `batter_hits`, six-market call (5 to 6 credits per game; 314 marker rows, 1,521 credits since 2026-09-10) at a baseline pass (5 to 7 h out, pre-lineup) and a gate pass (at most 2 h out). 20 dates; no capture 09-28, 09-29 | Target: a hit (Over 0.5 is essentially all quoted lines). Features: posted lineup slot, batter box lines (box store from 2026-08-30; 2025 archive not opened), handedness, opposing starter hits allowed. Frozen parameters fit on 2025 only: `data/processed/card_v2_frozen_params.json` (`RHO` 0.05885 on 42,667 predictions; slot plate-appearance table). Point-in-time season rates still read 2026 stores that include sealed-window games: the dependence `docs/PREREG_CARD_V2.md` section 1.2 discloses | Baseline: de-vigged consensus. Candidate: **exists**, `src/analysis/playerprops.price_prop` (shadow arm `B_HITS` in `src/analysis/mlb_value_shadow.py`; matrix: paired Brier +0.0132 and +0.0075, both within noise) | The gate board has a median lead of 101 min and only 35.3% of games are within 90 min, so a closing board needs a re-timed or extra pass. Six or more two-sided books: **0% of lines** (median 3 two-sided; Betrivers is the only one-sided book and quotes Overs only: 2,430 of 11,145 book quotes). The six-book floor cannot be met in region `us` as captured | YES. rule `batter_hits` -> `h`. Name join; 181 eligible lines have a mapped game and a box date but no row (DNP or name mismatch, not separable here); graded VOID, never guessed |
| MLB batter total bases | YES (same store, `batter_total_bases`). 20 dates, same gaps | Target: Over 1.5 bases (the common line). Same features and frozen parameters as hits | Baseline: de-vigged consensus. Candidate: **exists**, `playerprops.price_prop` (shadow arm `A_TOTAL_BASES`; matrix: paired Brier -0.0069 (se 0.0083, n=46) and -0.0022 (se 0.0089, n=64), both within noise) | Same timing gap (35.1% of games within 90 min). Six or more two-sided books: 19.9% of lines (332 of 1,348 eligible lines on a board 90 minutes or less before first pitch). Capture needed: one TB (optionally plus hits) snapshot per game 30 to 90 minutes before first pitch | YES. rule `batter_total_bases` -> `total_bases`. 144 eligible lines unsettled for the same reasons |
| NFL QB passing yards | NO. 0 rows, 0 raw responses; the provider documents `player_pass_yds`. NFL capture is the featured h2h/spreads/totals call only (`src/pipeline/nfl_capture.py`) | Target: passing yards. Features: none on disk. BALLDONTLIE manifest lists NFL endpoints `games` (12), `odds` (176), `odds_opening` (176); no `stats`, `season_stats` or `player_props` was ever harvested; only 2 `.cursor` files exist in `data/historical/balldontlie/nfl/`, no data files. `/nfl/v1/stats` and `/nfl/v1/odds/player_props` are named in `scripts/balldontlie_harvest.py` and `docs/PREREG_NFL_CARD_V2.md` but no manifest entry shows either was run; plan-tier access UNKNOWN (no probe, no network) | Baseline: UNKNOWN. Candidate: none | Capture does not exist; cost in Table 3 | **NO.** No module fetches NFL player box scores |
| NFL receptions | NO (same; `player_receptions`) | same | same | same | NO |
| NFL receiving yards | NO (same; `player_reception_yds`) | same | same | same | NO |
| NFL rushing yards | NO (same; `player_rush_yds`) | same | same | same | NO |

Expected new decisions per week, from the measured lines per game (Table 2,
two-sided books >= 2, at 14 and 28 games a week; this assumes every game is
captured, which was true for only 62% to 75% of games): pitcher strikeouts 28 to
57; batter hits 211 to 422; batter total bases 227 to 454. The postseason cannot
supply more than about 43 more games in all, so over the rest of 2026 that is
at most about 85 strikeout lines and about 700 total-bases lines, before any
candidate abstention. Not captured families: UNKNOWN. A structural upper bound
for pitcher markets is two lines per game (one per probable starter), about 28 to
56 a week; for NFL a QB market is at most two lines per game, about 32 a week at
16 games. Those are bounds, not measurements.

Credit context (Table 3): the account spent a median of 696 credits on days
with spend of 100 or more since 2026-09-10 (630 to 756 on 2026-09-21 to
09-27), against the 250 to 550 a day in the brief; 497 on 2026-10-01, the first
day after the monthly reset. Capture stopped on 2026-09-28 to 09-30 (spend 14 to
28 a day) because the balance sat at about 4,900, under the 5,000 credit floor,
until the allowance reset on 2026-10-01. Those three days are the missing
capture dates in Table 1. A 2,963-credit single step on 2026-09-16 is logged to
`budget.probe_family:tennis_h2h` (a step in the log, which may include other
spend between rows).

## Generated tables

<!-- GENERATED:prop_inventory BEGIN -->
### Table 1. Price availability, books and margin (since 2026-09-10)

Captured families (final board of each game; see Definitions).

| Family | Store | Capture dates (no capture on) | Slate coverage: games with a priced line / games on the slate | Eligible lines per slate (median, range) | Lines per game, mean (>=1 / >=2 / >=6 two-sided books) | Books quoting a line (median) | Two-sided books (median) | Lines with >=6 two-sided | One-sided book quotes | Margin % (median, IQR) | Hold % (median) | Lines moved off the final board |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| MLB pitcher strikeouts | `prop_prices` | 19 dates, 2026-09-10..2026-10-01 (2026-09-20, 2026-09-28, 2026-09-29) | 155 / 249 (62.2%) | 20 (2-39) | 2.4 / 2.0 / 1.3 | 6.0 | 6.0 | 55.2% | 0.0% (0 of 1803; none) | 6.51 (6.10-6.99) | 6.11 | 12 of 378 |
| MLB batter hits | `batter_props` | 20 dates, 2026-09-10..2026-10-01 (2026-09-28, 2026-09-29) | 186 / 249 (74.7%) | 183 (19-312) | 18.6 / 15.1 / 0.0 | 4.0 | 3.0 | 0.0% | 21.8% (2430 of 11145; betrivers 2430) | 6.76 (6.48-6.99) | 6.33 | 163 of 3724 |
| MLB batter total bases | `batter_props` | 20 dates, 2026-09-10..2026-10-01 (2026-09-28, 2026-09-29) | 187 / 249 (75.1%) | 178 (20-335) | 18.3 / 16.2 / 3.6 | 4.0 | 4.0 | 19.9% | 15.7% (2377 of 15131; betrivers 2377) | 7.00 (6.58-7.47) | 6.54 | 194 of 4829 |

Player-games with a priced line (one contract per player-game, the unit a paired comparison would use): MLB pitcher strikeouts: 1.9 per game with >=2 two-sided books (286 player-games), 1.3 per game with >=6 (202); MLB batter hits: 15.1 per game with >=2 two-sided books (2819 player-games), 0.0 per game with >=6 (0); MLB batter total bases: 15.7 per game with >=2 two-sided books (2956 player-games), 3.6 per game with >=6 (682)

Not captured (UNKNOWN for every price, book, margin and sample column):

| Family | Market key | In any prop store | Provider documents the key |
|---|---|---|---|
| MLB pitcher outs | `pitcher_outs` | NO (0 rows in `prop_prices`, `batter_props`; 0 raw responses in the archive) | yes |
| MLB hits allowed | `pitcher_hits_allowed` | NO (0 rows in `prop_prices`, `batter_props`; 0 raw responses in the archive) | yes |
| MLB earned runs | `pitcher_earned_runs` | NO (0 rows in `prop_prices`, `batter_props`; 0 raw responses in the archive) | yes |
| NFL QB passing yards | `player_pass_yds` | NO (0 rows in `prop_prices`, `batter_props`; 0 raw responses in the archive) | yes |
| NFL receptions | `player_receptions` | NO (0 rows in `prop_prices`, `batter_props`; 0 raw responses in the archive) | yes |
| NFL receiving yards | `player_reception_yds` | NO (0 rows in `prop_prices`, `batter_props`; 0 raw responses in the archive) | yes |
| NFL rushing yards | `player_rush_yds` | NO (0 rows in `prop_prices`, `batter_props`; 0 raw responses in the archive) | yes |

### Table 2. Closing-board feasibility, settleable sample, expected volume (since 2026-09-10)

| Family | Median lead of each game's newest board (min before first pitch) | Games whose newest board is within 90 min | Eligible lines on a <=90 min board (of which >=6 two-sided books) | Settleable lines (eligible, box row present) | ... with >=2 two-sided | ... with >=6 | Settleable games | Settleable dates | Postseason games captured (lines / game, >=2 books) | Expected lines / week at 14 and 28 games (>=2 books) |
|---|---|---|---|---|---|---|---|---|---|---|
| MLB pitcher strikeouts | 28.7 | 83.9% | 304 (176) | 342 | 295 | 193 | 147 | 18 | 2 (2.0) | 28 / 57 |
| MLB batter hits | 101.2 | 35.3% | 1317 (0) | 3143 | 2678 | 0 | 175 | 19 | 3 (12.0) | 211 / 422 |
| MLB batter total bases | 101.2 | 35.1% | 1348 (332) | 3138 | 2817 | 666 | 177 | 19 | 3 (15.3) | 227 / 454 |

Settleable-line accounting (eligible lines on the final board that are NOT settleable, and why): MLB pitcher strikeouts: 366 eligible, 15 no mapped game, 2 on a date with no box rows yet, 7 with a mapped game and date but no box row; MLB batter hits: 3470 eligible, 108 no mapped game, 38 on a date with no box rows yet, 181 with a mapped game and date but no box row; MLB batter total bases: 3434 eligible, 125 no mapped game, 27 on a date with no box rows yet, 144 with a mapped game and date but no box row

Box-score dates ingested in the forward store: 2026-09-10, 2026-09-11, 2026-09-12, 2026-09-13, 2026-09-14, 2026-09-15, 2026-09-16, 2026-09-17, 2026-09-18, 2026-09-19, 2026-09-20, 2026-09-21, 2026-09-22, 2026-09-23, 2026-09-24, 2026-09-25, 2026-09-26, 2026-09-27, 2026-09-29, 2026-09-30

### Table 3. Odds API credits

Daily account spend from `data/processed/credit_log.jsonl` (sum of drops in `credits_remaining` between consecutive rows, attributed to the UTC day of the later row; rises are treated as a monthly reset and not counted): 23 days since 2026-09-10, median 666, median of days with spend >= 100 696, min 6, max 4120. Days under 100: 2026-09-28, 2026-09-29, 2026-09-30, 2026-10-02.

| UTC day | log rows | credits spent | last credits_remaining |
|---|---|---|---|
| 2026-09-10 | 179 | 251 | 23219 |
| 2026-09-11 | 173 | 432 | 22787 |
| 2026-09-12 | 144 | 479 | 22308 |
| 2026-09-13 | 38 | 358 | 21950 |
| 2026-09-14 | 238 | 480 | 21470 |
| 2026-09-15 | 205 | 1411 | 20059 |
| 2026-09-16 | 216 | 4120 | 15939 |
| 2026-09-17 | 343 | 1474 | 14465 |
| 2026-09-18 | 215 | 1650 | 12815 |
| 2026-09-19 | 315 | 1575 | 11240 |
| 2026-09-20 | 341 | 1426 | 9814 |
| 2026-09-21 | 632 | 756 | 9058 |
| 2026-09-22 | 492 | 696 | 8362 |
| 2026-09-23 | 452 | 714 | 7648 |
| 2026-09-24 | 467 | 701 | 6947 |
| 2026-09-25 | 431 | 682 | 6265 |
| 2026-09-26 | 449 | 666 | 5599 |
| 2026-09-27 | 345 | 630 | 4969 |
| 2026-09-28 | 420 | 28 | 4941 |
| 2026-09-29 | 464 | 14 | 4927 |
| 2026-09-30 | 456 | 28 | 4899 |
| 2026-10-01 | 574 | 497 | 99503 |
| 2026-10-02 | 26 | 6 | 99497 |

Single steps of 1,000 credits or more: 2026-09-16T10:19:01.853372Z 2963 (budget.probe_family:tennis_h2h); 2026-09-16T14:48:37.895859Z 1124 (dense.run); 2026-09-17T14:12:46.304100Z 1153 (dense.run); 2026-09-18T19:14:43.554583Z 1493 (dense.run); 2026-09-19T15:36:54.826621Z 1204 (dense.run); 2026-09-20T14:35:08.915133Z 1160 (dense.run)

In-play capture (`data/live/credit_log_live.jsonl`, 1 credit per logged call): 8 days, 215 credits in all; per day: 2026-09-21 2, 2026-09-22 26, 2026-09-23 30, 2026-09-24 35, 2026-09-25 43, 2026-09-26 36, 2026-09-27 40, 2026-10-01 3

Pitcher strikeouts (`prop_prices.jsonl` markers): 347 billed fetches since 2026-09-10, credits per fetch distribution {"0": 8, "1": 339}, 339 credits, median 15 credits per capture day.
Batter props, 6 markets per call (`batter_props_raw.jsonl` markers): 314 billed fetches since 2026-09-10, credits per fetch distribution {"0": 25, "1": 18, "3": 13, "4": 10, "5": 64, "6": 184}, 1521 credits, median 61 credits per capture day.

**Cost model (documented rule: credits = unique markets returned x regions, 1 each; empty responses free).** Per game, per snapshot, one region unless stated. Weekly figures use 14 and 28 games a week (the 2 to 4 games a day of the postseason); NFL uses 16.

| Closing-board capture | Markets | Credits / game / snapshot / region | Per week at 14 games | at 28 games | at 28 games, 2 regions | % of 100,000 monthly allowance (28 games, 1 region, x4.3 weeks) |
|---|---|---|---|---|---|---|
| MLB pitcher strikeouts | 1 | 1 | 14 | 28 | 56 | 0.12% |
| MLB pitcher outs | 1 | 1 | 14 | 28 | 56 | 0.12% |
| MLB hits allowed | 1 | 1 | 14 | 28 | 56 | 0.12% |
| MLB earned runs | 1 | 1 | 14 | 28 | 56 | 0.12% |
| MLB all four pitcher markets | 4 | 4 | 56 | 112 | 224 | 0.48% |
| MLB batter hits | 1 | 1 | 14 | 28 | 56 | 0.12% |
| MLB batter total bases | 1 | 1 | 14 | 28 | 56 | 0.12% |
| MLB batter hits + total bases | 2 | 2 | 28 | 56 | 112 | 0.24% |
| MLB six batter markets (today's gate call) | 6 | 6 | 84 | 168 | 336 | 0.72% |
| NFL QB passing yards (16 games) | 1 | 1 | 16 | n/a | 32 | 0.07% |
| NFL four families (pass yds, receptions, receiving yds, rush yds) (16 games) | 4 | 4 | 64 | n/a | 128 | 0.28% |

### Table 4. Feature and settlement stores (measured spans; no stat value read)

| Store | Path | First unsealed date | Last date | Unsealed lines by year | Lines on or after 2026-09-10 | Sealed-window lines skipped unparsed |
|---|---|---|---|---|---|---|
| pitcher game logs | `data/historical/pitcher_logs.jsonl` | 2023-03-30 | 2026-09-07 | 2023: 8888, 2024: 7837, 2026: 553 | 0 | 7745 |
| bullpen log | `data/historical/bullpen_log.jsonl` | 2023-03-30 | 2026-09-06 | 2023: 20723, 2024: 20720, 2026: 1250 | 0 | 17115 |
| posted lineups | `data/historical/lineups.jsonl` | 2023-03-30 | 2026-10-02 | 2023: 2440, 2024: 2434, 2026: 446 | 431 | 0 |
| box scores 2026 (settlement) | `data/processed/boxscores_2026.jsonl` | 2026-08-30 | 2026-09-30 | 2026: 12516 | 7698 | 0 |

- handedness: 1642 players with bats/throws, static file.
- pitcher arsenal (season to date): present True, as_of 2026-09-08T20:38:01.094438+00:00 (leaderboard snapshot, NOT point in time).
- batter arsenal (season to date): present True, as_of 2026-09-08T20:38:01.094438+00:00 (leaderboard snapshot, NOT point in time).
- Statcast pitch store (`C:\Users\KC\Desktop\aisportsanalysis\data\historical\statcast\manifest.json`): 94 windows, first window 2023-03-30..2023-04-02, last window ends 2024-09-30.
- NFL player data: BALLDONTLIE manifest present True; NFL endpoints in it: {"games": 12, "odds": 176, "odds_opening": 176}; files on disk in `data/historical/balldontlie/nfl/`: nfl_games_2016.jsonl.gz.cursor, nfl_games_2018.jsonl.gz.cursor.

### Table 5. Market keys ever returned (raw archive, `data/raw/oddsapi/`)

4573 raw capture files opened (0 dated inside the sealed window skipped unopened).

| sport / market key | market occurrences in raw responses |
|---|---|
| americanfootball_nfl/h2h | 131625 |
| americanfootball_nfl/spreads | 154461 |
| americanfootball_nfl/totals | 155470 |
| baseball_mlb/alternate_spreads | 2303 |
| baseball_mlb/alternate_totals | 2053 |
| baseball_mlb/batter_hits | 1058 |
| baseball_mlb/batter_hits_runs_rbis | 1029 |
| baseball_mlb/batter_home_runs | 455 |
| baseball_mlb/batter_rbis | 742 |
| baseball_mlb/batter_runs_scored | 300 |
| baseball_mlb/batter_total_bases | 1703 |
| baseball_mlb/h2h | 95084 |
| baseball_mlb/h2h_1st_5_innings | 7781 |
| baseball_mlb/pitcher_strikeouts | 4760 |
| baseball_mlb/spreads | 89646 |
| baseball_mlb/spreads_1st_5_innings | 1840 |
| baseball_mlb/team_totals | 1874 |
| baseball_mlb/totals | 95607 |
| baseball_mlb/totals_1st_5_innings | 4769 |
| mma_mixed_martial_arts/h2h | 56903 |
| tennis_wta_singapore_open/h2h | 2475 |

### Table 6. Sealed-window accounting

Lines dated 2026-01-01..2026-08-27 met while reading each store (all skipped, none parsed):

| Store | Lines read | Sealed-window lines skipped | Lines before 2026-09-10 (not parsed) | Lines parsed |
|---|---|---|---|---|
| prop_prices | 6046 | 0 | 1736 | 4310 |
| batter_props | 146655 | 0 | 14306 | 132349 |
| event_game_map | 2913 | 6 | 2657 | 250 |
| boxscores_2026 | 12516 | 0 | 4818 | 7698 |
| credit_log | 8667 | 0 | 1052 | 7615 |
| credit_log_live | 215 | 0 | 0 | 215 |

<!-- GENERATED:prop_inventory END -->

## Ranking: information gained per credit and per week

The question each family answers is the same: does a frozen candidate's
probability carry information the de-vigged market probability does not, at the
price a bettor would actually face.

**1. MLB batter total bases (first).**
- Soonest: about 16 contracts per game with two or more two-sided books, so
  roughly 230 to 450 a week at postseason pace and about 15 games a day in the
  2027 regular season. It is the only family where a game-clustered paired
  comparison can approach a useful standard error inside one season.
- A candidate exists (`src/analysis/playerprops.py`, frozen 2025 parameters), so
  the first read does not wait on a build.
- Already captured post-lineup and already settleable: 3,138 eligible lines
  have a box row now (descriptive, nothing scored).
- Cheapest marginal credit: the primary metric (paired Brier at the decision
  board) needs **no new capture**. Closing-line value needs one extra snapshot of
  `batter_total_bases` alone, 1 credit per game (2 with hits): 14 to 28 credits a
  week at 14 to 28 games, 105 to 210 a week at a 2027 full slate. The current
  gate call spends 5 to 6 credits per game on six markets; four of them are used
  by nothing here.
- Weaknesses, stated: margin 7.0% (the widest of the captured families); only
  19.9% of lines have six or more two-sided books, so the six-book closing
  standard covers about one line in five and region `us` alone may never reach it
  (whether region `us2` adds books is untested: UNKNOWN, a 2-credit probe would
  answer it); the candidate's point-in-time season rates read 2026 stores that
  include sealed-window games, a disclosed dependence, not a clean forward fit;
  the lines within a game are correlated, so the effective sample is smaller than
  the contract count.

**2. MLB pitcher strikeouts (second).**
- Best price infrastructure of the three: the closing-quality board already
  exists (T-30m, 83.9% of captured games within 90 minutes, 55.2% of lines with
  six or more two-sided books, no one-sided quotes at all) and costs 1 credit per
  snapshot, already inside the daily envelope. Margin 6.5%, the lowest captured.
- Weaknesses: no candidate model exists, so a build comes first; two lines per
  game means only 28 to 57 lines a week in the postseason and about 130 a week
  at a 2027 full slate at the present 62% coverage; the starter test for
  settlement is undefined; feature data for a point-in-time strikeout model is
  thin (no 2026 Statcast, arsenal leaderboard not point in time, pitcher logs last
  dated 2026-09-07 and refreshable at zero credits from the MLB Stats API).
- Why still second: it is the cleanest test of "is the book's price good where
  books are deep", and every credit is already being spent.

**Not worth testing now.**
- **Pitcher outs, hits allowed, earned runs**: no capture, so no price, margin or
  book depth is known; at most 2 lines per game and at most about 43 postseason
  games, so the whole postseason could give at most about 85 lines per family. A
  capture-only probe is the right move if anyone wants the UNKNOWNs measured: 3
  markets x 1 credit x about 3 games a day is about 9 credits a day.
- **All four NFL families**: cannot settle (no player box-score module), no
  feature data, hold UNKNOWN, and a QB-only market is at most about 32 lines a
  week. A capture-only probe is cheap (Table 3: 4 credits per game, 64 a week at
  16 games) and would measure availability, books and margin, but it would not
  create a testable sample this season.
- **Batter hits as a primary**: zero lines meet the six-book standard, 21.8% of
  book quotes are one-sided, and it adds nothing total bases does not. Kept as a
  descriptive secondary.
- **A postseason-only confirmatory read of any family**: too few games by format.
  Reported as its own descriptive, underpowered row if collected, never pooled
  with the regular season (the project's calendar rule).
