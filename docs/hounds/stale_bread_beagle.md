# Stale-Bread Beagle

A beagle with a nose for a book that forgot to move its line.

- **Style:** book disagreement (market)
- **Universe:** MLB and NFL; markets: moneyline, spread, total; price band -199 to +400 on the board-average price (never -200 or worse); at most one bet per game and three per day; it may pass any game or any day.
- **Decides by:** rule

## Rule (exactly as coded)

MLB and NFL, moneyline, main spread and main total, sides with 5+ books on the line. Edge = the side's de-vigged consensus minus the raw implied probability of its best price. Bet the single largest edge if it is 2.5 points or more. Graded at the board average like every hound.

Shared mechanics (lock 60 minutes before the start, the board, prices, the daily cap, grading) are in
`docs/PREREG_HOUSE_PACK_V1.md`. Code: `src/hounds/pack/stale_bread_beagle.py`.

## Source

Book disagreement and stale quotes, the subject of the repo's own staleness study (`src/research/m2_staleness.py`). Line shopping is price improvement, not a prediction.

## Our adaptation

Any market, 5+ books on the line, the best price at least 2.5 points better than the de-vigged consensus. Graded at the board average like every hound, with the best-price result shown beside it.

## Honest expectation

At the average price this is a random side with extra steps; expect to lose about the vig. The best-price column shows what the shopping alone was worth. Judged like every hound: did it beat the closing price over enough forward bets.
Paper only; no hound is a recommendation.

## Drama hooks

- One book fell asleep. Beagle noticed.
- Stale bread, fresh bet.
