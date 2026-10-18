# Chalk Chihuahua

A chihuahua that always picks the bigger dog (inside the -200 rule).

- **Style:** favourites (simple)
- **Universe:** MLB and NFL; markets: moneyline; price band -199 to -101 on the board-average price (never -200 or worse); at most one bet per game and three per day; it may pass any game or any day.
- **Decides by:** rule

## Rule (exactly as coded)

Moneyline, MLB and NFL. Bet the favourite (the side with the higher de-vigged consensus) when its board-average price is between -199 and -101.

Shared mechanics (lock 60 minutes before the start, the board, prices, the daily cap, grading) are in
`docs/PREREG_HOUSE_PACK_V1.md`. Code: `src/hounds/pack/chalk_chihuahua.py`.

## Source

Backing favourites, the simplest baseline.

## Our adaptation

Favourites priced -199 to -101 only (owner's rule: never -200 or worse); first three games by lock each day.

## Honest expectation

A baseline. It should lose about the vig. Judged like every hound: did it beat the closing price over enough forward bets.
Paper only; no hound is a recommendation.

## Drama hooks

- Chihuahua always backs the biggest dog in the room.
- Chalk is boring. Chihuahua is not.
