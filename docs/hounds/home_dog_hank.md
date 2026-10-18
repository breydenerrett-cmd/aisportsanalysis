# Home Dog Hank

A hound that never leaves home and loves an underdog.

- **Style:** home underdogs (simple)
- **Universe:** MLB and NFL; markets: moneyline; price band +100 to +400 on the board-average price (never -200 or worse); at most one bet per game and three per day; it may pass any game or any day.
- **Decides by:** rule

## Rule (exactly as coded)

Moneyline, MLB and NFL. Bet the home club when its board-average price is +100 to +400.

Shared mechanics (lock 60 minutes before the start, the board, prices, the daily cap, grading) are in
`docs/PREREG_HOUSE_PACK_V1.md`. Code: `src/hounds/pack/home_dog_hank.py`.

## Source

The home-underdog angle; this repo pre-registered it (`docs/PREREG_SR1_HOME_UNDERDOG.md`) and it came back null.

## Our adaptation

Home club when its board-average price is +100 to +400; first three games by lock each day.

## Honest expectation

Null in this repo's own study. A baseline; it should lose about the vig. Judged like every hound: did it beat the closing price over enough forward bets.
Paper only; no hound is a recommendation.

## Drama hooks

- Hank stays home and barks at the favourite.
- Home sweet underdog.
