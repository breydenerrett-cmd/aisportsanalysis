# Why the card loses: synthesis of the three diagnoses (2026-10-16)

Reports: `01_estimate_error.md` (the model's numbers), `02_selection.md` (what the card picks),
`03_prices.md` (what the prices say). Each was written by a separate agent from the same data,
every number comes from a committed script under `scripts/diagnosis/`, and a fourth agent reran
the scripts (byte-identical outputs) and tried to refute the claims. What follows separates what
survived that check from what remains an estimate.

Record under study: 178 graded V2 entries, 2026-09-22 to 2026-10-15 (97-81, -1.42u; props 149 at
52.3% on -115 to -150 prices; moneylines 29). The site's public headline is different and
narrower: regular-season MAIN picks 16-17, -5.05u, with the postseason shown as "not counted"
(27-33, -9.22u). 97-81 is the count of every graded entry including 17 withdrawn picks that
`record_v2` reports separately.

## Facts (recomputed independently, survived refutation)

1. **Every bet was priced worse than fair.** Gate G13 requires the taken price to sit above the
   de-vigged consensus; the mean premium is +2.36 probability points per bet. At the market's own
   numbers the 178 bets were expected to lose 7.55u. They lost 1.42u. The card ran lucky, not
   unlucky.
2. **The model's disagreement with the market carries no information.** On the full pool of
   6,818 priced prop contracts (every contract, not only our picks; 34 forward dates, nothing
   from the sealed window) the model's log loss is worse than the market's by +0.0103 nats
   [+0.0064, +0.0153]. The best weight to give our disagreement when blending with the market is
   -0.20 [about -0.46, +0.07]: zero or negative. On 2024 moneylines (parameters fitted on 2025,
   no 2024 outcomes used) the weight is -0.01 [-0.32, +0.29].
3. **The card ranks by that disagreement.** The score correlates 0.98 with model-minus-market and
   the gates keep disagreements of 5 to 10 points, so the card publishes our largest errors by
   construction. On the published props our mean probability was 0.608; the hit rate was 0.523;
   the market said 0.525.
4. **A code defect:** total bases Over 0.5 uses an uncorrected convolution while hits Over 0.5
   uses the correlation-corrected path (`src/analysis/playerprops.py`, `probability_over`). On
   identical inputs the gap is +2.3 to +3.4 points, in 2024, 2025 (tuning-only) and 2026.
5. **Grading is at the best two-sided price, not the board average** (`propboard.fair_and_best`;
   `docs/PREREG_CARD_V2.md` lines 380/384). The owner's 2026-09-21 ruling (grade at average odds)
   was never implemented. At the board average the same bets are -4.11u, not -0.69u on the
   measured subset.
6. **Closing-line value is negative wherever it can be measured:** -1.69 points per bet
   [-2.09, -1.28] on 82 bets (26 of 29 moneylines, 56 of 149 props). The unmeasured props hold
   most of the loss, so the prop figure is not representative.
7. **At fair price the non-withdrawn bets come to +0.01u.** That is what a model with no
   information produces; it is not evidence of good sides.
8. **Moneylines carry no model content:** 24 of 29 are home favourites at -100 to -160; our
   number tracks the market at r = 0.19.

## Estimates (direction supported, size not pinned)

- Decomposition of the 8.5-point prop bias: about 4 points from selecting our biggest
  disagreements (small batter samples, 15 to 43 games, over-trusted), about 3 from the total-bases
  defect, about 3 from no opposing-starter and no postseason term. October hitters produced hits
  at 0.186 per PA [0.172, 0.199] against the 0.218 the model assumed (one October, 32 games).
- Picks versus fills (54-56 vs 43-25) is most likely luck (permutation p = 0.15); fills are not
  cheaper.
- The market drifts toward our prop selections after we bet by about +0.5 to +0.7 points; that
  is a quarter of the premium we pay, and it is the only hint of information in the data.
- Every "what the record would have been under rule X" figure in the three reports is hindsight
  and is labelled so. None is a forecast.

## What this means

The card is not a slightly unlucky edge. It is a mechanism that pays a 2.4-point premium to bet
the market's number plus our own noise, selected at its noisiest. Fixing the three model errors
(estimate) still leaves the model behind the market (fact 2). No reweighting of the present
inputs is expected to produce an edge; the owner was told this before and it is now measured
three ways.

## Changes worth making, in order (each pre-registered, forward only)

1. **Stop paying the premium for noise.** Remove or invert the value test: a model with weight 0
   should not pick against the market. Concretely, pause MAIN prop picks and moneyline value picks;
   publish the brief and the board (prices, consensus, what moved) instead of bets. This is a
   loss-stopping change, not an edge.
2. **Fix the total-bases path** so TB 0.5 uses the corrected probability. Fingerprinted file:
   proposal, not an edit; it needs the registration amendment procedure.
3. **Implement the grading ruling** (average odds) or formally reverse it; the public record
   currently claims a price basis that was never applied.
4. **Grade withdrawn picks visibly** or exclude them consistently; "97-81" and "16-17" must not
   both be readable from the same ledger without a label.
5. **Make `stale_board` real** (it is hard-coded None) and grade moneyline fills at a price that
   was on the board at lock (9 of 20 were not).
6. If a value product is still wanted later: the only candidate direction the data supports is
   information the market lacks at the moment we bet (fact: post-bet drift exists but is a
   quarter of the vig), which means earlier, better inputs (lineups, starters, weather at lock),
   not a better formula on the same inputs.

Commands: `python scripts/diagnosis/estimate_error.py --part all`, `python scripts/diagnosis/selection.py`,
`python scripts/diagnosis/prices.py`. Reviewer recomputations: session scratch `refute/`.
