# Dartboard Dalmatian

A dalmatian throwing darts at the whole board. A control.

**Control.** This hound is random on purpose. It is the baseline the other hounds must beat; nobody claims it works.

- **Style:** seeded random market and side (control) (random)
- **Universe:** MLB and NFL; markets: moneyline, spread, total; price band -199 to +400 on the board-average price (never -200 or worse); at most one bet per game and three per day; it may pass any game or any day.
- **Decides by:** random

## Rule (exactly as coded)

Control, MLB and NFL. Seed = sha256 of 'dartboard_dalmatian|' plus the odds event id. Market = moneyline, spread or total by the first byte mod 3; side = home/Over if the second byte is even, away/Under if odd. Pass if that market is not on the board.

Shared mechanics (lock 60 minutes before the start, the board, prices, the daily cap, grading) are in
`docs/PREREG_HOUSE_PACK_V1.md`. Code: `src/hounds/pack/dartboard_dalmatian.py`.

## Source

A seeded random market and side, the 'monkey with darts' baseline.

## Our adaptation

Seed is sha256 of the hound id and event id; market and side come from the first two bytes; passes if the market is not on the board.

## Honest expectation

A control. It should lose about the vig. Judged like every hound: did it beat the closing price over enough forward bets.
Paper only; no hound is a recommendation.

## Drama hooks

- Dalmatian closed its eyes and threw.
- Spots on the dog, darts on the board.
