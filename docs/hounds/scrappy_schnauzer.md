# Scrappy Schnauzer

A schnauzer that only bites the big dogs: underdogs from +100 to +250.

- **Style:** underdogs with a reason (mixed)
- **Universe:** MLB and NFL; markets: moneyline; price band +100 to +250 on the board-average price (never -200 or worse); at most one bet per game and three per day; it may pass any game or any day.
- **Decides by:** rule

## Rule (exactly as coded)

Moneyline underdogs priced +100 to +250 on the board average, MLB and NFL. Bet the underdog when at least one of Professor Paws, Gridiron Greyhound, Steamy Setter or Hot-Streak Husky picks that club in this game.

Shared mechanics (lock 60 minutes before the start, the board, prices, the daily cap, grading) are in
`docs/PREREG_HOUSE_PACK_V1.md`. Code: `src/hounds/pack/scrappy_schnauzer.py`.

## Source

The owner's stated preference for +100 to +250 underdogs. The favourite-longshot bias literature (for example Thaler and Ziemba (1988), Journal of Economic Perspectives, widely known) suggests longshots are slightly overbet.

## Our adaptation

An underdog is only taken when one of four hounds (model, rating, steam, momentum) backs it.

## Honest expectation

Favourite-longshot bias says underdogs lose a little more than the vig. Lumpy results either way. Judged like every hound: did it beat the closing price over enough forward bets.
Paper only; no hound is a recommendation.

## Drama hooks

- Schnauzer loves an underdog. Underdogs love to lose.
- Small dog, big price, bigger bark.
