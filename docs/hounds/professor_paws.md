# Professor Paws

A tweed-jacketed spaniel who trusts the house run model, but only halfway.

- **Style:** model vs market, shrunk halfway to the market (stats)
- **Universe:** MLB; markets: moneyline; price band -199 to +400 on the board-average price (never -200 or worse); at most one bet per game and three per day; it may pass any game or any day.
- **Decides by:** model

## Rule (exactly as coded)

MLB moneyline. Feed the house run model (strength.model_line) each club's runs scored and allowed per game since 2026-08-28 (games before today; both clubs need 5+). Shrink its home win probability 50% toward the de-vigged consensus. Bet the side whose shrunk probability beats the consensus by 2.0 points or more.

Shared mechanics (lock 60 minutes before the start, the board, prices, the daily cap, grading) are in
`docs/PREREG_HOUSE_PACK_V1.md`. Code: `src/hounds/pack/professor_paws.py`.

## Source

Two-Poisson run model with Bill James' log5 odds-ratio construction, as written up in this repo's `src/analysis/strength.py` (a standard public method). The 50% shrink toward the market follows the repo's loss diagnosis (`data/research/loss_diagnosis/estimate_error_tables_all.md`), which found the house probabilities ran about 8.5 points hot on graded bets.

## Our adaptation

Inputs are restricted to games from 2026-08-28 on (the sealed window is never read), so the team rates are heavily regressed early in the window. No starters, bullpen or park factor: none of those is point-in-time for the replay. The model's opinion is averaged 50/50 with the market before any comparison.

## Honest expectation

The house model has not beaten the market in any study in this repo. Expect it to lose about the vig. Judged like every hound: did it beat the closing price over enough forward bets.
Paper only; no hound is a recommendation.

## Drama hooks

- The Professor has a model, a theory and a leash, and the leash is doing most of the work.
- Half model, half market, all tweed.
