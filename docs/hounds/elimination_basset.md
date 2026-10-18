# Elimination Basset

A mournful basset hound who backs the home club when the season is on the line.

- **Style:** postseason series state (history)
- **Universe:** MLB; markets: moneyline; price band -199 to +400 on the board-average price (never -200 or worse); at most one bet per game and three per day; it may pass any game or any day.
- **Decides by:** rule

## Rule (exactly as coded)

MLB postseason moneyline. From this postseason's finished games between the two clubs, find their current series. If the home club is one loss from elimination, bet the home club. Otherwise pass.

Shared mechanics (lock 60 minutes before the start, the board, prices, the daily cap, grading) are in
`docs/PREREG_HOUSE_PACK_V1.md`. Code: `src/hounds/pack/elimination_basset.py`.

## Source

Folk wisdom about home teams in elimination games; the repo's postseason work (`src/situation/series.py`, `src/situation/rest_vs_rhythm.py`) describes series state but found no edge. Source not verified.

## Our adaptation

Series state is rebuilt from finished postseason games before the day of the game; bets only the home club when it is one loss from elimination.

## Honest expectation

A handful of bets a postseason. A coin flip less the vig. Judged like every hound: did it beat the closing price over enough forward bets.
Paper only; no hound is a recommendation.

## Drama hooks

- Basset only howls when somebody's season is about to end.
- Do or die, and Basset picked do.
