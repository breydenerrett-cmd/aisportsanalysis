# The mismatch scanner — a different objective from the model

**Written 27 Aug 2026**, after the strategy the project is actually being built for was
described in detail for the first time.

## The project had been optimising the wrong thing

Everything built before this — de-vigging, calibration, the logistic model, the
disagreement ranking, closing-line-value grading — serves one objective: estimate a
probability, remove the bookmaker's margin, bet the difference. That is
expected-value betting.

The stated approach is not that:

> trying to find bets that have good value or EV isn't necessarily a part of the strat

> we're just trying to find clear advantages that other people aren't finding

And the decisive example:

> there's a game today with Yamamoto versus Chris Sale and that's just a great pitching
> matchup against both teams and you just don't know what's gonna happen and it's −115
> ml ... but like if the pitching matchup was super different and we had a superstar on
> one team and not on the other

That example rules out the EV frame twice.

A −115 ace duel is the single best case for an EV model. Near a coin-flip price, a
small probability difference produces the largest apparent edge, so that is exactly
the game an EV ranker puts at the top of its list. It is rejected anyway — and the
reason given is not the price. It is **"you just don't know what's gonna happen."**

That is a statement about *variance*, not about *value*. The scanner therefore scores
a different quantity:

| | EV model | Mismatch scanner |
|---|---|---|
| Question | Is this priced wrong? | Is the gap visible without a model? |
| Best case | Close price, small model disagreement | Large talent gap, price not blown out |
| Ace duel at −115 | **Top of the list** | **Suppressed outright** |
| Typical day | Ranks all 15 games | Says no play |

These are close to opposites. A gap obvious enough to see is usually well priced, and
the EV frame discards it for exactly that reason.

## What the scanner does

Two independent talent signals, both point-in-time and both built by the same leak-free
code the model uses:

- **Starters** — FIP gap ≥ 1.00, or K-BB% gap ≥ 10 points.
- **Roster** — run differential per game gap ≥ 1.00.

Plus three suppressions, in order:

1. **The Yamamoto/Sale rule.** If *both* starters have FIP under 3.50, the game is
   suppressed before the gap is even measured. Two good starters make an unpredictable
   game whatever the distance between them.
2. **Agreement.** Both signals must point at the same team. One signal alone is an
   observation, not something anyone would call obvious at a glance; contradicting
   signals are a disagreement between two measurements, not an edge.
3. **The market screen.** If the de-vigged price on the flagged side is already ≥ 0.65,
   the market has made the mismatch its headline and there is nothing left that other
   people are missing. *No model probability enters this test* — it is a screen on the
   market alone, which is what keeps it from quietly becoming an EV calculation.

## Where a flagged game gets expressed

> there is value on like the over under runs in the first five innings

F5 is not an arbitrary preference, and the mechanism decides the routing:

A starter throws about five to six innings. Over nine innings his contribution is
diluted by two to four innings of bullpen — and bullpens are far more alike across
clubs than starters are. A starter gap is therefore **largest in innings one through
five and shrinks after that**. Betting a starter mismatch on the full-game line runs it
through a layer of noise that has nothing to do with the reason for the bet.

So: starter-driven mismatch → first five. Roster-driven mismatch → full game.

## How often it fires

Measured across **1,561 games, 1 June – 28 Sept 2025**, with thresholds fixed before the
run and unchanged after it:

| | Games | Share |
|---|---|---|
| Clear both talent signals, agreeing side | 159 | **10.2%** (≈1.4/day) |
| Single signal only | 690 | 44.2% |
| Signals contradict | 60 | 3.8% |
| Suppressed — thin sample or unknown starter | 183 | 11.7% |
| Suppressed — starters too close, or both strong | rest | — |

Games that cleared the talent bar look right: 2025 COL @ MIA, DET @ CWS, ATH @ TOR,
BAL @ SEA. Bad club with a weak starter against a good club with a good one.

**None of the 1,561 reached a flagged verdict**, because the market screen could not
run — the historical store holds no closing odds. That is the finding, not a bug.

### What this measurement is and is not

- No game **outcomes** were read. This counts how often signals fire, not whether the
  games won. Nothing about the burned 2025 test split changes.
- Thresholds were written down *before* this run and not touched after it. They are
  asserted in `tests/test_pipeline_mismatch.py::TestThresholdsArePreRegistered` so that
  a later quiet tweak toward whatever would have won fails a test rather than passing
  as a diff nobody reads.

## What this changes about the pending decisions

The **$59 for three seasons of historical odds** was previously a nice-to-have for
validating the model. It is now the binding constraint on the scanner too: without
historical prices, the market screen — one of the three suppressions, and the one that
encodes "advantages other people aren't finding" — cannot be measured at all. 10.2% is
an upper bound on the fire rate, and the true rate is unknown.

Second: the pipeline requests `h2h`, `spreads`, `totals`. It has **never requested
first-five markets**, which is the market the scanner routes most of its flags to. That
gap needs closing before any flagged game can actually be priced.

## What the scanner does not claim

An obvious mismatch is not a profitable bet. Bad teams with bad starters lose more
often *and are priced to lose more often*; that is what the market screen is for, and
the screen is the part that has never been tested. The output is a shortlist and a
reason for a human to look at.

Every threshold is a pre-registered guess. Not one has been validated against a result.
