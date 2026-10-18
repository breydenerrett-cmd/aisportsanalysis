# Jet-Lag Jack

A Jack Russell who never takes the red-eye and bets against those who do.

- **Style:** rest and travel (history)
- **Universe:** MLB and NFL; markets: moneyline, spread; price band -199 to +400 on the board-average price (never -200 or worse); at most one bet per game and three per day; it may pass any game or any day.
- **Decides by:** rule

## Rule (exactly as coded)

MLB moneyline: bet a club that did not play yesterday when its opponent played yesterday in a different ballpark from today's (the opponent travelled overnight); yesterday must be covered by the results stores. NFL spread: bet the club with 3 or more extra days of rest since its previous 2026 game.

Shared mechanics (lock 60 minutes before the start, the board, prices, the daily cap, grading) are in
`docs/PREREG_HOUSE_PACK_V1.md`. Code: `src/hounds/pack/jetlag_jack.py`.

## Source

Song, Severini and Allada (2017), 'How jet lag impairs Major League Baseball performance', PNAS, a widely known study; NFL rest-differential studies are common public handicapping material (source not verified).

## Our adaptation

MLB: a crude travel flag (the opponent played yesterday in a different ballpark, our club had the day off), no time-zone direction. NFL: 3+ extra days of rest. Both from schedules and results known before the game.

## Honest expectation

A documented effect in research, small and very likely priced. Expect to lose about the vig. Judged like every hound: did it beat the closing price over enough forward bets.
Paper only; no hound is a recommendation.

## Drama hooks

- Jack slept in. The other dugout slept on a plane.
- Rested legs, tired eyes, and a bet in between.
