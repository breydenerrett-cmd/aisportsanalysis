# Relief Retriever

A Labrador who counts every pitch the bullpen threw this week.

- **Style:** bullpen fatigue (stats)
- **Universe:** MLB; markets: moneyline; price band -199 to +400 on the board-average price (never -200 or worse); at most one bet per game and three per day; it may pass any game or any day.
- **Decides by:** rule

## Rule (exactly as coded)

MLB moneyline. Add up each club's relief pitches (bullpen log, non-starters) over the three calendar days before the game. If one bullpen threw 120 or more pitches more than the other, bet the club with the fresher bullpen. All three days must be in the bullpen log.

Shared mechanics (lock 60 minutes before the start, the board, prices, the daily cap, grading) are in
`docs/PREREG_HOUSE_PACK_V1.md`. Code: `src/hounds/pack/relief_retriever.py`.

## Source

Bullpen fatigue as a handicapping input is a widely used public method (recent relief workload as a proxy for tired arms); source not verified. The repo's own bullpen research (`src/research/m4_bullpen_gap.py`) looked at the market's bullpen view, not fatigue.

## Our adaptation

Workload = relief pitches over the three calendar days before the game from the bullpen log; one fixed 120-pitch bar; bets the fresher club's moneyline.

## Honest expectation

A folk method, unproven here and probably priced. Expect to lose about the vig. Judged like every hound: did it beat the closing price over enough forward bets.
Paper only; no hound is a recommendation.

## Drama hooks

- Somebody's bullpen is running on fumes, and Retriever can smell it.
- Count the pitches, fetch the bet.
