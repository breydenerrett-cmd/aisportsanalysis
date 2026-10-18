# Bargain Bloodhound

A bloodhound who never pays retail.

- **Style:** best price vs de-vigged consensus (math)
- **Universe:** MLB and NFL; markets: moneyline; price band -199 to +400 on the board-average price (never -200 or worse); at most one bet per game and three per day; it may pass any game or any day.
- **Decides by:** rule

## Rule (exactly as coded)

Moneyline, MLB and NFL. Bet the side whose best price has a break-even probability at least 0.5 points below the de-vigged consensus (the larger margin if both sides qualify).

Shared mechanics (lock 60 minutes before the start, the board, prices, the daily cap, grading) are in
`docs/PREREG_HOUSE_PACK_V1.md`. Code: `src/hounds/pack/bargain_bloodhound.py`.

## Source

Value betting against a de-vigged consensus, a widely known public method; de-vigging as in this repo's `src/core/odds.py`.

## Our adaptation

Moneyline only; the best price must beat the consensus fair probability by half a point; graded at the board average per the owner's ruling.

## Honest expectation

Price improvement at the best book is real; it is not a prediction. At the average price, expect to lose about the vig. Judged like every hound: did it beat the closing price over enough forward bets.
Paper only; no hound is a recommendation.

## Drama hooks

- Bloodhound found a bargain. The bargain found the average price.
- Never pays retail, still pays the vig.
