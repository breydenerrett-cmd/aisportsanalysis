# Benchmark: a public-style projection against the closing line

**Frozen before any score is computed.** One question, stated in advance
with its expected answer: does a free, public-style projection beat the
market's closing consensus at forecasting MLB games? **Expected answer:
no.** The benchmark exists to measure the gap, not to hunt for a win; if
the answer surprises, the surprise is the finding and gets its own
follow-up registration before anything is built on it.

## Why reconstruct instead of download

Scouting (docs/OVERNIGHT_RUN.md, 2026-08-31) found no free external source
that is honestly replayable for 2023–24: FanGraphs never archives its game
odds, FiveThirtyEight's Elo died mid-2023 with its data files gone,
retro-computed win probabilities (Savant, B-R) are not pre-game forecasts,
and self-hosted "past picks" pages are self-attested. So the projection is
rebuilt point-in-time from the repo's own results store — which makes it
*better* evidence than a download: zero unverifiable inputs.

## The model (frozen, deliberately public-grade)

Standard Elo, constants from FiveThirtyEight's published MLB methodology —
chosen a priori, never tuned on our data:

- base rating 1500, logistic scale 400
- K = 4 per game
- home advantage = 24 rating points
- preseason: ratings regress 1/3 of the way back to 1500
- results only — no starting-pitcher adjustment, no margin-of-victory
  multiplier. Pitcher-free on purpose: the retroactive "probable starter"
  is really the actual starter, a small but real lookahead this benchmark
  refuses to carry.

Forecast for a game: P(home) = 1 / (1 + 10^(−(R_home + 24 − R_away)/400)),
computed strictly BEFORE that game's result updates any rating. Games are
processed in (date, start time, game_pk) order.

## The data split (frozen)

- **2023 = burn-in.** The results store begins 2023-03-30, so 2023 exists
  only to warm the ratings. No 2023 game is scored.
- **2024 = the scored season.** Every 2024 regular-season game with a
  distinct close snapshot and at least 6 books quoting is scored; the rest
  are reported as unscored with the reason. 2025 and sealed 2026 are not
  touched.

## Scoring (frozen)

Per scored game: the Elo forecast and the de-vigged close consensus
(`selections._fair`, proportional, mean over quoting books) each get a
log-loss and a Brier score against the actual outcome. The benchmark
statistic is the per-game log-loss differential (Elo minus close; positive
means Elo is worse), averaged, with a DATE-clustered two-sided p from the
same machinery every family uses. Brier is reported alongside. No bets, no
selections, no ROI — this is forecast accuracy only, and the close is the
benchmark precisely because beating it is what every failed family could
not do.

## Result

Run 2026-08-31 on 2,234 scored 2024 regular-season games (14 had no price
pair, 181 lacked a distinct close snapshot, 0 had a thin consensus):

| forecaster | log-loss | Brier |
|---|---|---|
| close consensus | **0.67275** | **0.23999** |
| public-style Elo | 0.68076 | 0.24391 |

Per-game log-loss differential +0.00801 (Elo worse), date-clustered
two-sided p = 0.0003. **The closing line beats the free public-style
projection, decisively — the pre-stated expectation, now measured.**

Reading: this quantifies route 4 ("stand on other people's work") for the
free tier: a clean, honestly reconstructed public-grade model gives up
about 0.8 log-loss points per game to the close. Any input that cannot
demonstrably do better than this baseline adds nothing the market lacks —
a useful yardstick for every future data-acquisition decision. It also
re-confirms, from a third angle, that the close is the benchmark to beat
and that beating it needs information the public tier does not carry.
