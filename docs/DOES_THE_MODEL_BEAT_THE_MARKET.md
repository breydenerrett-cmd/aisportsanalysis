# Does our model beat the market? Every measurement, one page.

Last run 2026-09-10. This is the register the project did not have: one place
holding every measurement that bears on the single question a paying customer
is really asking. Each row links to the script that produces it, so every
number here is re-runnable rather than remembered.

**Short answer: no measurement has shown that it does, and five independent
ones point the same way.** Nothing here is a reason to stop — the samples are
small and the intervals are wide. It is a reason to stop *assuming* it does,
and to be careful about what the product claims.

---

## The five measurements

### 1. The team model's own predictive power
`scripts/backtest_card.py`

**+0.004 nats** over the base rate. That is almost exactly nothing: knowing
our model's number instead of "the home team wins 52.3% of the time" improves
the forecast by less than half a percent of a nat.

### 2. The prop model's own predictive power
`scripts/backtest_player_props.py` — 16,741 batter games, no price in sight

**+0.0133 nats** on `batter_hits`, 3.3x the team model. **The prop model is
genuinely informative** and this is the strongest positive result the project
has. It is a statement about the model, not about beating a price.

### 3. Head to head against the price, on props
`scripts/prereg_market_vs_model.py` — pre-registered, 1,107 contracts

```
              log loss (nats)
  base rate       0.69289      the do-nothing floor
  market          0.66784
  model           0.67439
  paired difference +0.00655   95% clustered CI [-0.00137, +0.01455]
```

**UNDETERMINED** by the rule fixed before the run — the interval spans zero.
Both arms beat the floor; which of the two is better did not resolve.

The blend curve is the more telling half: **monotone increasing in `w` with
its minimum at `w = 0`**. Independent predictors normally blend better than
either alone; every unit of weight moved onto our model made the estimate
worse, with no interior optimum. Suggestive, not established — the whole
curve spans less than the primary interval.

Conditional on disagreeing with the price by more than five points, our
number landed closer **49.6%** of the time. A coin flip.

### 4. Betting the disagreements, both directions
`scripts/probe_prop_value.py` — pre-registered, Bonferroni-corrected

```
  OVER   flagged n=113  ROI -13.4%  97.5% [-34.1, +7.4]   control -9.1%
  UNDER  flagged n=163  ROI  -0.2%  97.5% [-18.3, +17.8]  control -2.2%
```

**NO FINDING on both sides.** The pre-registered conclusion applies: model-
versus-price disagreement does not select profitable player props in either
direction, and the prop card does not ship as a disagreement scanner.

### 5. The card's own selection rule
`scripts/backtest_card_rule.py` — 97 settled games, the only window with prices

```
  market: every consensus favourite       n=97  win 53.6%  ROI -7.8%  [-25.1, +9.5]
  card: favourite, model agrees           n=72  win 54.2%  ROI -9.7%  [-29.1, +9.8]
  contrarian: favourite, model disagrees  n=25  win 52.0%  ROI -2.4%  [-40.0, +35.1]
```

**Every interval is 20 to 75 points wide. Nothing here is a finding and the
point estimates are not read.** What can be said is that the card's model
filter has not been shown to add anything over simply taking the market
favourite, and the window is far too short to show it either way.

---

## What consistently points the other way

These are the positives, stated as plainly as the negatives.

- **The prop model is genuinely informative** (+0.0133 nats, item 2). That is
  measured on 16,741 games, the largest sample in the project.
- **Tonight's lineup matters.** The batting slot beats a batter's own season
  average on plate appearances by 13% (0.608 MAE against 0.699), and pooling
  both sides of the value scan put the ROI split on a real sample for the
  first time: **−1.4% with the slot (n=227) against −25.3% without (n=49)**.
  Not significant. The clearest signal in the area, and it is exactly what
  the owner predicted.
- **Shopping the price is real and needs no forecast.** +1.13 points per prop
  bet, about 17% of the book's margin, with clean dose-response from 2 books
  to 5. See `docs/PROP_MARKET_ECONOMICS.md` — including why that number's
  tight interval proves nothing on its own.

## What we now know about the market itself

`docs/PROP_MARKET_ECONOMICS.md`

| | player props | game moneylines |
|---|---|---|
| margin the average book charges | 6.79 points | 3.65 points |
| median books quoting both sides | 2 | 11 |

**Props cost 1.9x the game market and are quoted by a fifth as many books.**
The edge required to beat a prop is nearly twice the edge required to beat a
moneyline, and no edge of even the smaller size has been demonstrated.

## What this means for what LINEHOUND may claim

1. **It may not claim to beat the market.** Not "edge", not "value", not
   "+EV", not an implied track record. Nothing measured supports it. The
   language tripwires in `tests/test_customer_language.py` exist for this and
   should be extended, not relaxed.
2. **It may claim what is true and rare:** a frozen, published, hash-chained
   daily pick that is graded afterwards **including the losers**. No
   competitor does that. It is the honest wedge and it does not depend on any
   of the above resolving.
3. **It may claim to find the best available price**, with the number
   attached and the caveat that recovering 17% of a 6.8-point margin is not a
   winning strategy by itself.
4. **THE CARD has no track record.** The ledger holds zero settled days as of
   2026-09-10 — it was built the same day. Every statement about its
   performance is forward-looking and must be written that way.

## Inputs attempted, and what happened

### Platoon splits — ATTEMPTED, NO FEATURE
`scripts/probe_platoon_split.py`

The handedness cache turned out to hold **one of 286 starting pitchers**:
`lineups.fetch_handedness` has always captured `throws`, but its only caller
passes tonight's lineup plus two probables, so the cache never looked
backwards. `scripts/backfill_handedness.py` fixed that from the free MLB
Stats API — 1,281 people, 738 of 739 pitchers now carry a throwing hand.

With the data in hand the measurement still refuses to produce a feature, and
**the switch-hitter control is what caught it.** Pooled rates say left-handed
*and* right-handed batters both hit left-handed pitching better, which cannot
be true.

The cause is composition, not noise. Teams platoon left-handed hitters
heavily, so the lefties who face a left-hander are the subset good enough not
to be benched against one — pooling compares two different populations.
Comparing each batter with **himself** removes that exactly and moves both
groups the right way (lefties −0.51 → −0.22, righties −0.51 → −1.04) without
finishing the job. Relief attribution is the remaining confound and it bites
lefties hardest, since left-handed relievers exist to face left-handed
batters.

**Blocked on a data gap with a free fix**: the plate-appearance store that
resolves relief attribution covered 183 of 1,099 games. Backfilled
2026-09-10.

Also worth recording while here: **player-level data exists for 2026 only.**
There is no sealed holdout for any prop-model constant, so `RHO`, the slot
table and anything that follows are tuned in-sample and their gains are
optimistic. Pre-registration guards against moving a threshold; it does not
make an estimate out-of-sample.

## What would change the answer

The bar is now explicit and the instrument exists. **Adding an input is only
progress if it moves the paired difference in item 3**, which is re-runnable
on demand. Remaining candidates:

1. **Park factors** — built (`src/pipeline/parkfactors.py`), measured, and
   deliberately switched off. Re-measure against item 3 rather than adopting.
2. **Weather** — `data/processed/weather_forecast.jsonl` exists.
3. **Recent form** — a batter's last N games against his season rate.
4. **Platoon, second attempt** — once the plate-appearance store covers the
   season, the within-batter comparison becomes possible without the relief
   confound.

And the one structural candidate that is not an input at all: **prove the
method on the game market first**, where the margin is half and the books are
five times as many. An edge that cannot be shown at 3.65 points has no chance
at 6.79.
