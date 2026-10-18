# Contrary Corgi

A corgi who digs in its short legs and goes the other way.

- **Style:** line movement, against it (market)
- **Universe:** MLB and NFL; markets: moneyline; price band -199 to +400 on the board-average price (never -200 or worse); at most one bet per game and three per day; it may pass any game or any day.
- **Decides by:** rule

## Rule (exactly as coded)

Moneyline, MLB and NFL. Same trigger as Steamy Setter (the consensus moved 3.0 points or more from the open to lock). Bet the other side.

Shared mechanics (lock 60 minutes before the start, the board, prices, the daily cap, grading) are in
`docs/PREREG_HOUSE_PACK_V1.md`. Code: `src/hounds/pack/contrary_corgi.py`.

## Source

'Fade the public' contrarian folklore; Levitt (2004), Economic Journal, discusses books shading prices against public biases (widely known).

## Our adaptation

Exactly Steamy Setter's trigger, opposite side, so the two form a matched pair.

## Honest expectation

The mirror of the Setter. Between them they should lose about two vigs. Judged like every hound: did it beat the closing price over enough forward bets.
Paper only; no hound is a recommendation.

## Drama hooks

- Corgi saw the crowd and turned around.
- When the steam rises, Corgi sits down.
