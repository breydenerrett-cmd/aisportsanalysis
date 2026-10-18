# Steamy Setter

An Irish setter that points wherever the money is moving.

- **Style:** line movement, with it (market)
- **Universe:** MLB and NFL; markets: moneyline; price band -199 to +400 on the board-average price (never -200 or worse); at most one bet per game and three per day; it may pass any game or any day.
- **Decides by:** rule

## Rule (exactly as coded)

Moneyline, MLB and NFL. Compare the de-vigged consensus at the open (earliest capture with 3+ books, within 24 hours for MLB or 7 days for NFL, at least an hour before lock) with the consensus at lock. Bet the side the consensus moved toward if it moved 3.0 points or more.

Shared mechanics (lock 60 minutes before the start, the board, prices, the daily cap, grading) are in
`docs/PREREG_HOUSE_PACK_V1.md`. Code: `src/hounds/pack/steamy_setter.py`.

## Source

'Steam' chasing is sportsbook folklore; the academic background on betting-market price formation includes Levitt (2004), 'Why are gambling markets organised so differently from financial markets?', Economic Journal (widely known).

## Our adaptation

Moves are measured on the de-vigged multi-book consensus from the open (first 3-book capture) to lock; one fixed 3-point bar; bets at lock, after the move.

## Honest expectation

By lock the move is in the price. Expect to lose about the vig. Judged like every hound: did it beat the closing price over enough forward bets.
Paper only; no hound is a recommendation.

## Drama hooks

- Setter smelled steam. So did everyone else.
- Late to the party, but always at the party.
