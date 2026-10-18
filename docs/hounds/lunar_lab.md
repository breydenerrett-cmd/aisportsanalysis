# Lunar Lab

A lab that howls at the full moon and goes quiet at the new one. Entertainment only.

**Entertainment only.** This hound is a joke with a ledger. Nobody claims it works; it is in the race as a control.

- **Style:** moon phase (entertainment) (esoteric)
- **Universe:** MLB and NFL; markets: total; price band -199 to +400 on the board-average price (never -200 or worse); at most one bet per game and three per day; it may pass any game or any day.
- **Decides by:** rule

## Rule (exactly as coded)

For fun, game total, MLB and NFL. Moon age at the start = days since the 2000-01-06 18:14 UTC new moon, modulo 29.530588853. Within 1.5 days of full moon bet the Over; within 1.5 days of new moon bet the Under; otherwise pass.

Shared mechanics (lock 60 minutes before the start, the board, prices, the daily cap, grading) are in
`docs/PREREG_HOUSE_PACK_V1.md`. Code: `src/hounds/pack/lunar_lab.py`.

## Source

Full-moon folklore. The phase is astronomy (mean synodic month from a reference new moon); the betting rule is entertainment.

## Our adaptation

Computed offline from the start time; full moon window means Over, new moon window means Under.

## Honest expectation

Entertainment and a control. Nobody claims this works. It should lose about the vig. Judged like every hound: did it beat the closing price over enough forward bets.
Paper only; no hound is a recommendation.

## Drama hooks

- Full moon, full send on the Over.
- Lunar Lab: as scientific as it sounds, which is not very.
