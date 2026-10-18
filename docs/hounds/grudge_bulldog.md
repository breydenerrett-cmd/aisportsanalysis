# Grudge Bulldog

A bulldog that never forgets who beat it.

- **Style:** revenge and bounce-back (intangibles)
- **Universe:** MLB and NFL; markets: moneyline, spread; price band -199 to +400 on the board-average price (never -200 or worse); at most one bet per game and three per day; it may pass any game or any day.
- **Decides by:** rule

## Rule (exactly as coded)

NFL spread: bet a club that lost the two clubs' most recent meeting (a final since 2021, within 450 days before kickoff) by 7 or more points. MLB moneyline: bet a club that lost to the same opponent yesterday by 5 or more runs.

Shared mechanics (lock 60 minutes before the start, the board, prices, the daily cap, grading) are in
`docs/PREREG_HOUSE_PACK_V1.md`. Code: `src/hounds/pack/grudge_bulldog.py`.

## Source

'Revenge game' and bounce-back narratives are broadcast and handicapping folklore; source not verified.

## Our adaptation

NFL: the club that lost the last meeting (within 450 days) by 7+ points. MLB: the club blown out by 5+ runs by the same opponent yesterday.

## Honest expectation

Folklore. Expect to lose about the vig. Judged like every hound: did it beat the closing price over enough forward bets.
Paper only; no hound is a recommendation.

## Drama hooks

- Bulldog remembers. The scoreboard doesn't care.
- Revenge is a dish best served against the spread.
