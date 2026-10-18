# Gridiron Greyhound

A lean racing greyhound that only reads the scoreboard.

- **Style:** simple rating vs spread (stats)
- **Universe:** NFL; markets: spread; price band -199 to +400 on the board-average price (never -200 or worse); at most one bet per game and three per day; it may pass any game or any day.
- **Decides by:** rule

## Rule (exactly as coded)

NFL spread, main line. Expected home margin = half of (home point differential per game minus away point differential per game, 2026 finals before kickoff, 2+ games each) plus 1.5 for home field. Add the home spread line. Bet the home side if that is +3.0 or more, the away side if -3.0 or less.

Shared mechanics (lock 60 minutes before the start, the board, prices, the daily cap, grading) are in
`docs/PREREG_HOUSE_PACK_V1.md`. Code: `src/hounds/pack/gridiron_greyhound.py`.

## Source

Point-differential ratings, the idea behind Pro-Football-Reference's Simple Rating System and Pythagorean expectation; widely known public methods, source not verified here.

## Our adaptation

A deliberately crude rating: half the difference in 2026 point differential per game, plus 1.5 points of home field, against the main spread; 3-point bar; at least two games each.

## Honest expectation

NFL spreads are among the sharpest markets; early-season point differential is noise. Expect to lose about the vig. Judged like every hound: did it beat the closing price over enough forward bets.
Paper only; no hound is a recommendation.

## Drama hooks

- Greyhound read the scoreboard. The spread read it first.
- Two games of data and a whole lot of confidence.
