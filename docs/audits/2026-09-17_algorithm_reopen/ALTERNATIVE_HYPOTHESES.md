# Where an edge could plausibly be, if there is one

Written 2026-09-17. Twelve structurally different hypotheses, not twelve
weightings of the same regression.

**Framing.** The project's strongest null — a Phase 2A result finding
essentially no linear incremental information beyond the MLB closing price
(empty L1, L2 about +0.0000412 log-loss/game WORSE at p≈0.914) — is evidence
about **one target, one model family, one representation, one market, one
prediction time**. Each hypothesis below is written to be false in a
DIFFERENT way than that result was, so that running them is not re-running it.

**Prior, stated honestly.** Most of these will die. The registry has searched
a large number of hypotheses and none has survived. The value of this document
is that the deaths will be informative rather than repetitive.

**A rule applied throughout.** Every hypothesis names the moment its
information becomes available (`as_of`) and the moment the bet would be
placed. A hypothesis that cannot state both is not testable here.

---

## H1 — Closing prices are efficient; the pre-close window is not

**MECHANISM.** Lineup confirmation, scratch news and late bullpen information
arrive between roughly 4 hours and 30 minutes before first pitch. The closing
price has absorbed them. Prices two to four hours earlier may not have.
**WHY THE MARKET COULD MISS IT.** It does not miss it at close; the claim is
that the market's absorption is not instantaneous and we can act inside the
lag, not beat the end state.
**DATA.** Our 11-book snapshot series with observation timestamps; lineup
posting TIME (not just content); scratch events.
**MARKET.** Moneyline, run line, totals.
**PREDICTION TIME.** Explicitly NOT the close. Several fixed `as_of` points.
**MODEL FAMILY.** Any — the hypothesis is about time, not functional form.
**NULL.** Price movement from `as_of` to close is unpredictable from
information available at `as_of`.
**FALSIFICATION.** Predict the SIGN of open→close movement from `as_of`
features. If it is at chance across a season, H1 dies for that `as_of`.
**LEAKAGE RISK.** High and specific — the lineup store must be point-in-time
by posting time, not by game date. Our lineup rows carry `observed_utc`, which
makes this testable and also makes a careless join fatal.
**OVERFITTING RISK.** Moderate; few features, many games.
**SAMPLE.** ~2,400 games/season × several `as_of` points.
**WHAT SUCCESS MEANS.** A timing edge, not a prediction edge. It would require
execution speed and would be capacity-limited. It would NOT mean our model is
better than the market.

## H2 — Side prediction is efficient; pitcher props are not

**MECHANISM.** Side markets aggregate 18 players into one number and attract
the most attention and money. A strikeout line for one pitcher against one
lineup is a thinner market priced with coarser inputs.
**WHY MISSED.** Attention and liquidity are concentrated on sides. Prop
pricing at many books is semi-automated from season aggregates.
**DATA.** Statcast pitch-level (we hold 1.43M pitches for 2023-24), batter
contact profiles, lineup composition, catcher, park, umpire if quality allows.
**MARKET.** Pitcher strikeouts, outs, earned runs, hits allowed, walks.
**PREDICTION TIME.** After lineup confirmation.
**MODEL FAMILY.** Distributional — negative binomial or Poisson for counts,
NOT a win-probability classifier. The target is a distribution over a count,
and the bet is a threshold on it.
**NULL.** Our count distribution is no better calibrated than the price
implies, across the line's neighbourhood.
**FALSIFICATION.** Calibration of the full predicted distribution against
realised counts, plus CLV against the prop close.
**LEAKAGE RISK.** Moderate — batter-vs-pitcher history must exclude the game
being predicted.
**OVERFITTING RISK.** HIGH. Many players, many lines, many thresholds. Needs
strict multiplicity control.
**SAMPLE.** Large: every start, several lines each.
**WHAT SUCCESS MEANS.** The most directly product-relevant outcome available,
and the owner asked for exactly this on 2026-09-17.

## H3 — Team averages are efficient; arsenal × lineup mismatches are not

**MECHANISM.** A pitcher whose primary weapon is a high-spin four-seam up
faces a lineup of low-launch contact hitters differently than the season
aggregate suggests. The interaction is real and the aggregate destroys it.
**WHY MISSED.** Pricing uses team-level offence and pitcher-level rate stats.
The specific pairing is not in either.
**DATA.** Statcast pitch type/velocity/movement per pitcher; per-batter
performance by pitch class; confirmed lineup.
**MARKET.** Pitcher props first (cleanest test), then F5 totals.
**PREDICTION TIME.** After lineup confirmation.
**MODEL FAMILY.** Matchup representation — embeddings or matrix
factorisation over (pitcher arsenal) × (batter vulnerability), then aggregate
to the bet.
**NULL.** Mismatch score adds nothing beyond both sides' marginals.
**FALSIFICATION.** Residualise on both marginals FIRST, then test whether the
interaction term adds calibrated information. If it does not, H3 dies and
takes a large family with it — which makes it a cheap, high-information test.
**LEAKAGE RISK.** Moderate.
**OVERFITTING RISK.** HIGH — interaction space is enormous. Screening must be
principled, not exhaustive.
**SAMPLE.** Large at pitch level, much smaller at bet level.
**WHAT SUCCESS MEANS.** Validates the whole "matchup analysis" product claim,
which is currently a product promise with no measured backing.

## H4 — Point estimates are efficient; the tails are not

**MECHANISM.** The market's central estimate is sharp, but its implied
variance may not be. Alternate lines and totals price the distribution's
shoulders, which receive less attention than the median.
**WHY MISSED.** Most money is on the main line; alternates are often derived
from it by a fixed model rather than priced independently.
**DATA.** Alternate run lines, alternate totals, our run-distribution model.
**MARKET.** Alternate lines, team totals.
**PREDICTION TIME.** Any.
**MODEL FAMILY.** Explicitly distributional — bivariate Poisson or negative
binomial with a fitted dispersion. We already measure dispersion at 2.3352
(`strength.py`), which is a starting point and itself a testable claim.
**NULL.** Our implied distribution is no better than the book's across the
line ladder.
**FALSIFICATION.** Compare predicted vs realised exceedance at every rung of
the ladder. A mispriced tail shows as systematic bias at the extremes with a
correct median.
**LEAKAGE RISK.** Low.
**OVERFITTING RISK.** Moderate.
**WHAT SUCCESS MEANS.** Edge in a market segment with less competition, and it
would be compatible with the side market being perfectly efficient.

## H5 — Bullpen QUALITY is priced; bullpen AVAILABILITY is not

**MECHANISM.** A team whose three best relievers threw on each of the last two
days has a materially different effective bullpen tonight. Season-level
bullpen quality is priced; last-72-hours usage may not be, especially early.
**WHY MISSED.** It requires assembling appearance-level history per reliever
and reasoning about manager behaviour. It decays within days, so it never
appears in season aggregates.
**DATA.** `bullpen_log` — we hold 27,483 appearances for 2025 alone. Who
pitched, how many pitches, on which days.
**MARKET.** F5 versus full-game divergence is the cleanest expression: a tired
bullpen should not affect the first five innings.
**PREDICTION TIME.** Morning, before the market has thought about it.
**MODEL FAMILY.** Feature engineering into any calibrated model; the test is
the feature, not the family.
**NULL.** Recent usage adds nothing beyond season-level bullpen quality.
**FALSIFICATION.** The F5/full-game split is a built-in placebo. If a usage
feature "predicts" F5 outcomes as strongly as full-game, it is not measuring
bullpen fatigue and the result is spurious.
**LEAKAGE RISK.** Moderate — usage must be as-of that morning.
**OVERFITTING RISK.** Low-moderate; few, interpretable features.
**WHAT SUCCESS MEANS.** A mechanism-backed edge with a natural placebo, which
is rare and valuable.

## H6 — No variable-level edge; execution and disagreement are the edge

**MECHANISM.** Across 11 books, at any instant some are stale or wider. The
edge is not a better probability, it is finding the best available price and
acting before it moves.
**WHY MISSED.** It is not missed by the market; it is a structural property of
a fragmented market.
**DATA.** Our 11-book cross-section, already captured.
**MARKET.** All.
**MODEL FAMILY.** None — this is microstructure, not prediction.
**NULL.** Cross-book dispersion at our capture instants is not exploitable
after accounting for availability, limits and the time to act.
**FALSIFICATION.** Measure whether the best price is still obtainable N
seconds later. If dispersion vanishes on contact, H6 dies.
**LEAKAGE RISK.** Low. **EXECUTION RISK.** The whole hypothesis.
**IMPORTANT PRODUCT NOTE.** The owner has explicitly said price-shopping /
Bet Check must NOT become the product's identity. So even if H6 is TRUE it is
constrained as a product direction. It should still be measured, because if
H6 is the only real effect, we need to know that rather than attribute it to
a model.

## H7 — Static ratings fail; latent dynamic state succeeds

**MECHANISM.** Team and player strength are not constant. A model fitting a
season-long parameter averages across regimes that genuinely differ (injury,
role change, mechanical adjustment).
**WHY MISSED.** The market may also use slow-moving ratings.
**DATA.** Game logs, our existing stores.
**MARKET.** Sides and totals.
**MODEL FAMILY.** State-space / dynamic Elo / Kalman-style latent strength
with a fitted evolution variance. Distinct from everything tested so far.
**NULL.** A dynamic rating is no better calibrated than a static one.
**FALSIFICATION.** Head-to-head calibration, and — critically — the dynamic
model must beat a static baseline before it is compared to the market. Rule
13: sophisticated models beat simple baselines first.
**OVERFITTING RISK.** Moderate; evolution variance is a tempting knob.
**WHAT SUCCESS MEANS.** Would reopen team-level modelling that Phase 2A
appeared to close, because Phase 2A tested a STATIC linear form.

## H8 — The system should not predict every game; it should abstain

**MECHANISM.** A model forced to price 15 games is optimised for average
accuracy. A model allowed to say "no opinion" on 12 of them can concentrate
on the cases where its inputs are unusually informative.
**WHY MISSED.** This is not a market inefficiency; it is a product and
loss-function claim about US.
**MODEL FAMILY.** Mixture of experts; selective prediction with a learned
abstention; specialists per market.
**NULL.** Selected subsets are no better calibrated than the full population —
i.e. our confidence carries no information about our own accuracy.
**FALSIFICATION.** THIS IS THE CHEAPEST AND MOST IMPORTANT TEST IN THE
DOCUMENT. Bin every historical prediction by our own stated confidence and
check whether accuracy-versus-price improves monotonically with it. If our
confidence does not predict our own error, then ranking, selection, the card,
and the entire product premise are unsupported.
**LEAKAGE RISK.** Low. **COST.** Very low — the data exists.
**WHAT SUCCESS MEANS.** It licenses the product's core structure. Failure
would be the most consequential null the project could find, and it has
apparently never been run.

## H9 — Umpire assignment is public early and imperfectly priced

**MECHANISM.** Plate umpires differ measurably in called strike zone, which
moves strikeout and walk rates, which moves totals and pitcher props.
**WHY MISSED.** Assignment is published but not headline news; effect is small
per game but systematic per umpire.
**DATA.** UNKNOWN whether we capture umpire assignment — `data/watch/umpires_watch.jsonl`
exists, contents unverified. Statcast gives called-strike data to build zones.
**MARKET.** Totals, pitcher strikeout props.
**NULL.** Umpire identity adds nothing to a strikeout model given pitcher and
lineup.
**FALSIFICATION.** Straightforward: umpire fixed effects on called strikes,
then on totals residual.
**OVERFITTING RISK.** Moderate — many umpires, few games each per season.
**NOTE.** Cheap because the data may already be in hand.

## H10 — Weather is priced as temperature; direction and its interaction are not

**MECHANISM.** Wind SPEED is commonly priced. Wind VECTOR relative to park
orientation, interacted with the specific lineups' batted-ball profiles, is a
finer object.
**WHY MISSED.** Requires joining park geometry, wind direction and player
batted-ball distributions — three sources nobody joins casually.
**DATA.** We capture weather (`weather_forecast.jsonl`, ~4.5MB); direction
availability UNKNOWN. Park geometry not known to be stored.
**MARKET.** Totals, team totals, home-run props.
**NULL.** Direction adds nothing beyond speed and temperature.
**FALSIFICATION.** Direct: does a park-oriented wind component explain run
residuals better than raw speed?
**LEAKAGE RISK.** HIGH AND SUBTLE — forecast at `as_of` must be used, never
the realised weather. Our store is a FORECAST store, which is the right shape,
but the as-of discipline must be explicit.

## H11 — The market's own movement is the signal

**MECHANISM.** Rather than predicting the game, predict the PRICE. Sharp money
moves lines; the direction and speed of movement may carry information about
the eventual close that is exploitable earlier.
**WHY MISSED.** This is what many professionals actually do; the question is
whether our capture cadence is fine enough to see it.
**DATA.** Our multi-book time series — but note the known limitation that the
historical odds grid's finest gap is 177 minutes, which may be too coarse.
**MARKET.** All.
**MODEL FAMILY.** Time-series / microstructure.
**NULL.** Movement between our snapshots does not predict further movement.
**FALSIFICATION.** Direct, cheap, and it also MEASURES OUR DATA ADEQUACY — a
null here may mean "no effect" or "our cadence is too coarse to see it", and
the test must be designed to distinguish those two, or it is uninformative.

## H12 — There is no edge, and the honest product is transparency

**MECHANISM.** None. The market is efficient at every horizon we can reach
with the data we can afford.
**WHY IT DESERVES A SLOT.** It is the hypothesis most consistent with the
evidence to date, and a research programme that cannot name it as a live
possibility is not a research programme. The registry has searched many
hypotheses and none has survived.
**FALSIFICATION.** It is the null that every other hypothesis tests against.
It "wins" by attrition.
**WHAT IT WOULD MEAN.** The product becomes what it already half is: a
transparent, honestly-graded public ledger with genuinely good explanation,
sold on rigour rather than on returns. That is a real product. It is not the
one anyone hopes for, and the system must not be permitted to quietly avoid
concluding it if the evidence points there.

---

## What separates these from each other

Deliberately spread across the axes, so that a null in one does not imply a
null in the others:

| | Target | Market | Time | Model family |
|---|---|---|---|---|
| H1 | price movement | sides | pre-close | any |
| H2 | count distribution | pitcher props | post-lineup | distributional |
| H3 | interaction residual | props, F5 | post-lineup | matchup embedding |
| H4 | full distribution | alternates | any | distributional |
| H5 | F5 vs full split | F5 | morning | feature test |
| H6 | none | all | instant | microstructure |
| H7 | latent strength | sides | any | state-space |
| H8 | our own error | all | any | selective prediction |
| H9 | called strikes | totals, K props | day-of | fixed effects |
| H10 | run residual | totals | as-of forecast | interaction |
| H11 | the price itself | all | intraday | time series |
| H12 | — | — | — | — |

**The one to run first is H8**, and not because it is the most likely to
succeed. It is the cheapest, it needs no new data, and it tests a premise
every other part of the product already assumes: that our own confidence
predicts our own accuracy. If that is false, the card's ranking is
decoration, and we should know before building anything else on top of it.
