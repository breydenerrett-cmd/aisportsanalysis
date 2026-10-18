# Coin-Flip Collie

A border collie with a coin. This is the control.

**Control.** This hound is random on purpose. It is the baseline the other hounds must beat; nobody claims it works.

- **Style:** seeded coin flip (control) (random)
- **Universe:** MLB and NFL; markets: moneyline; price band -199 to +400 on the board-average price (never -200 or worse); at most one bet per game and three per day; it may pass any game or any day.
- **Decides by:** random

## Rule (exactly as coded)

Control, moneyline, MLB and NFL. Seed = sha256 of 'coin_flip_collie|' plus the odds event id. Home if the seed's first byte is even, away if odd. Every game qualifies.

Shared mechanics (lock 60 minutes before the start, the board, prices, the daily cap, grading) are in
`docs/PREREG_HOUSE_PACK_V1.md`. Code: `src/hounds/pack/coin_flip_collie.py`.

## Source

A seeded coin flip, the baseline every other hound has to beat.

## Our adaptation

Seed is sha256 of the hound id and the odds event id, committed in the pre-registration so every flip can be recomputed.

## Honest expectation

A control. It should lose about the vig. Any hound that can't beat the Collie over a real sample has nothing. Judged like every hound: did it beat the closing price over enough forward bets.
Paper only; no hound is a recommendation.

## Drama hooks

- Heads, home. Tails, away. Collie, undefeated in honesty.
- If you can't beat the coin, you're the coin.
