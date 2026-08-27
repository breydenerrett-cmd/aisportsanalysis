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
3. **The market screen**, run on the market the game was routed to (see below). If the
   de-vigged price on the flagged side is already ≥ 0.65,
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

## First running live, 27 Aug 2026

With the 2026 season ingested (4,432 games) and 2026 pitcher logs built (476 pitchers,
17,635 appearances), the scanner produced its first live output on a 7-game slate:

    2 of 7 games flagged.
      HOU @ NYY: home (first five) -- K-BB% gap 10.7 points
      MIL @ NYM: away (first five) -- FIP gap 2.24, K-BB% gap 17.8 points

Five games said no play, each for a different reason, and one of them is the exact
case the strategy was described with:

    LAD @ ATL  [no_play]
      - both starters are strong (FIP 3.29 and 2.16, both under 3.50) -- a good
        pitching matchup on both sides is exactly the game whose outcome you
        cannot call

The Yamamoto/Sale rule fired on a real Dodgers game on its first day live.

Also suppressed: COL @ WSH, where the starter edge pointed one way and the roster edge
the other; KC @ TOR, one signal alone; AZ @ SF, a starter under 20 innings.

## An honest problem with the F5 routing

Both flagged games were priced. The first-five moneylines, de-vigged:

| Game | Full-game screen | F5 de-vigged |
|---|---|---|
| HOU @ NYY | home 59.0% | home **60.2%** |
| MIL @ NYM | away 64.1% | away **65.2%** |

The first-five market prices the flagged side **shorter than the full game does**, in
both cases — and MIL @ NYM at 65.2% is past the 0.65 screen the full-game price passed.

This is not a surprise on reflection, and it partly cuts against the routing argument.
The reasoning for F5 was that a starter gap is concentrated in innings one to five. But
the market knows that too: a first-five line is a starter line, and it is priced as
one. Concentrating the signal concentrates the price along with it.

What survives the objection is narrower than the original claim: F5 is the market that
*matches the reason for the bet*, so a flagged game there is not being diluted by
bullpen noise. Whether it is also *cheaper* there is an open question, and on this
single day's evidence the answer is no.

### The fix, and why it needed two stages

Screening on the wrong market let MIL @ NYM through, so the screen now runs against
the price of the market a game is routed to. That is harder than it sounds, because
the two requirements are circular:

- The screen must use the routed market's price.
- First-five prices are billed **per game**, so pricing every game to find out costs
  sixteen times what pricing the survivors costs.

You cannot afford to price everything, and you cannot screen correctly until you know
the routing. Splitting the stages resolves it:

| Stage | Cost | Produces |
|---|---|---|
| 1. Talent + routing | free | `candidate`, with its market named |
| 2. Screen on that market | per candidate | `flagged` or `no_play` |

`candidate` is an honest intermediate state, not a weaker verdict: it means *cleared
the talent bar, not yet priced*. A candidate whose price cannot be fetched **stays a
candidate** rather than being flagged — a missing screen is not a pass, and treating
it as one would flag every game whose F5 line happened to be unavailable, which is the
exact opposite of a scanner that stays quiet.

Re-run on the same slate after the fix:

    1 of 7 games flagged.
      HOU @ NYY: home (first five) -- K-BB% gap 10.7 points

MIL @ NYM is now correctly rejected on its own first-five price. Two flags became one,
and the one that disappeared was the one that should never have been there.

## What the scanner does not claim

An obvious mismatch is not a profitable bet. Bad teams with bad starters lose more
often *and are priced to lose more often*; that is what the market screen is for, and
the screen is the part that has never been tested. The output is a shortlist and a
reason for a human to look at.

Every threshold is a pre-registered guess. Not one has been validated against a result.
