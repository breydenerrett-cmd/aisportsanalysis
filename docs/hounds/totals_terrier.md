# Totals Terrier

A wire-haired terrier who digs for runs and barks at the total.

- **Style:** model total vs market total (stats)
- **Universe:** MLB; markets: total; price band -199 to +400 on the board-average price (never -200 or worse); at most one bet per game and three per day; it may pass any game or any day.
- **Decides by:** model

## Rule (exactly as coded)

MLB game total, main line, half-point lines only. Same house run model and inputs as Professor Paws. Shrink its Over probability 50% toward the de-vigged consensus. Bet the Over if the shrunk probability beats the consensus Over by 3.0 points or more, the Under if it trails by 3.0 points or more.

Shared mechanics (lock 60 minutes before the start, the board, prices, the daily cap, grading) are in
`docs/PREREG_HOUSE_PACK_V1.md`. Code: `src/hounds/pack/totals_terrier.py`.

## Source

The same two-Poisson run model (`src/analysis/strength.py`), read for totals instead of sides. Source for the method: standard Poisson scoring models; source not verified beyond the repo.

## Our adaptation

Half-point main lines only (no pushes to model), the same unsealed team rates as Professor Paws, the same 50% shrink, and a wider 3-point bar because totals carry more model error.

## Honest expectation

Totals markets are efficient; a team-rates-only model is crude. Expect to lose about the vig. Judged like every hound: did it beat the closing price over enough forward bets.
Paper only; no hound is a recommendation.

## Drama hooks

- The Terrier smelled runs. The bats did not.
- Over, under, or just digging?
