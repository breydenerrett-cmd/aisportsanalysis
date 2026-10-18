# Hot-Streak Husky

A husky that runs with whoever is hot.

- **Style:** momentum (intangibles)
- **Universe:** MLB and NFL; markets: moneyline, spread; price band -199 to +400 on the board-average price (never -200 or worse); at most one bet per game and three per day; it may pass any game or any day.
- **Decides by:** rule

## Rule (exactly as coded)

MLB moneyline: over each club's last 10 games since 2026-08-28, bet a club that won 7 or more against one that won 4 or fewer. NFL spread: bet a club on a 2026 winning streak of 3 or more against one on a losing streak of 2 or more.

Shared mechanics (lock 60 minutes before the start, the board, prices, the daily cap, grading) are in
`docs/PREREG_HOUSE_PACK_V1.md`. Code: `src/hounds/pack/hot_streak_husky.py`.

## Source

Gilovich, Vallone and Tversky (1985), 'The hot hand in basketball', Cognitive Psychology, and Miller and Sanjurjo (2018), Econometrica, which revisited it (both widely known).

## Our adaptation

MLB: 7+ wins in the last 10 against 4 or fewer (games from 2026-08-28 on). NFL: a 3-game winning streak against a 2-game losing streak.

## Honest expectation

Streaks are visible to everyone and priced. Expect to lose about the vig. Judged like every hound: did it beat the closing price over enough forward bets.
Paper only; no hound is a recommendation.

## Drama hooks

- Husky rides the hot hand until the hand goes cold.
- Momentum is real, until it's in the price.
