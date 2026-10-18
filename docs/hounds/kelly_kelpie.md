# Kelly the Kelpie

A working kelpie that herds its bankroll by the Kelly fraction.

- **Style:** fractional Kelly staking (math)
- **Universe:** MLB and NFL; markets: moneyline; price band -199 to +400 on the board-average price (never -200 or worse); at most one bet per game and three per day; it may pass any game or any day.
- **Decides by:** rule

## Rule (exactly as coded)

Same selections as Bargain Bloodhound. Stake = a quarter of the full Kelly fraction (consensus fair probability at the best price) of a 100-unit bankroll, capped at 3 units, rounded to 0.01; pass if under 0.05 units. Results scale by the stake.

Shared mechanics (lock 60 minutes before the start, the board, prices, the daily cap, grading) are in
`docs/PREREG_HOUSE_PACK_V1.md`. Code: `src/hounds/pack/kelly_kelpie.py`.

## Source

Kelly (1956), 'A New Interpretation of Information Rate', Bell System Technical Journal; Thorp's popularisation of fractional Kelly (widely known).

## Our adaptation

Same picks as Bargain Bloodhound; quarter Kelly of a 100-unit bankroll using the consensus fair probability at the best price, capped at 3 units. Results scale by the stake.

## Honest expectation

Kelly sizing cannot create an edge that is not there. Expect Bargain's result, scaled. Judged like every hound: did it beat the closing price over enough forward bets.
Paper only; no hound is a recommendation.

## Drama hooks

- Kelpie bets big when it's sure. It's never that sure.
- Fractional Kelly, whole dog.
