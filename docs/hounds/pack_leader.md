# Pack Leader

The alpha who only moves when the pack agrees.

- **Style:** ensemble vote (mixed)
- **Universe:** MLB and NFL; markets: moneyline; price band -199 to +400 on the board-average price (never -200 or worse); at most one bet per game and three per day; it may pass any game or any day.
- **Decides by:** rule

## Rule (exactly as coded)

Moneyline, MLB and NFL. Voters: Professor Paws, Relief Retriever, Gridiron Greyhound, Elimination Basset, Jet-Lag Jack, Steamy Setter and Stale-Bread Beagle (moneyline and spread picks only), asked about this game before any daily cap. Bet a club's moneyline when it has 2 or more votes and the other club has none.

Shared mechanics (lock 60 minutes before the start, the board, prices, the daily cap, grading) are in
`docs/PREREG_HOUSE_PACK_V1.md`. Code: `src/hounds/pack/pack_leader.py`.

## Source

Simple majority-vote ensembling, a widely known public method.

## Our adaptation

Voters are seven stats, history and market hounds asked before any daily cap; two or more votes for one club and none against.

## Honest expectation

Averaging hounds with no edge gives a hound with no edge. Expect to lose about the vig. Judged like every hound: did it beat the closing price over enough forward bets.
Paper only; no hound is a recommendation.

## Drama hooks

- When the pack agrees, the Leader leads. When it doesn't, the Leader naps.
- Seven opinions, one bet.
