# Numerology Newfie

A Newfoundland who reads the stars in the alphabet. Entertainment only.

**Entertainment only.** This hound is a joke with a ledger. Nobody claims it works; it is in the race as a control.

- **Style:** gematria (entertainment) (esoteric)
- **Universe:** MLB and NFL; markets: moneyline; price band -199 to +400 on the board-average price (never -200 or worse); at most one bet per game and three per day; it may pass any game or any day.
- **Decides by:** rule

## Rule (exactly as coded)

For fun, moneyline, MLB and NFL. Team number = digital root of the English ordinal gematria (A=1..Z=26) of the odds feed's full team name. Date number = digital root of the digits of the game's date. Bet the club whose number is closer to the date number; equal distance passes.

Shared mechanics (lock 60 minutes before the start, the board, prices, the daily cap, grading) are in
`docs/PREREG_HOUSE_PACK_V1.md`. Code: `src/hounds/pack/numerology_newfie.py`.

## Source

English ordinal gematria (A=1..Z=26) and digital roots, a numerology parlour game. Entertainment, not a method.

## Our adaptation

Fully deterministic and documented so anyone can check a pick with a pencil.

## Honest expectation

Entertainment and a control. Nobody claims this works. It should lose about the vig. Judged like every hound: did it beat the closing price over enough forward bets.
Paper only; no hound is a recommendation.

## Drama hooks

- The numbers have spoken. The numbers are made up.
- Newfie did the math. It was the wrong math.
