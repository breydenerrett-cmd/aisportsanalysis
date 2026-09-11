# What player props actually cost, measured

Written 2026-09-10 from `scripts/probe_line_shopping.py`. Descriptive. No
model is called anywhere in it — every number here is arithmetic on prices
that were all available at the same moment, plus the outcomes that settled
them.

This exists because two pre-registered runs had just come back with no
finding (`docs/PREREG_MARKET_VS_MODEL.md`, `docs/PREREG_UNDER_SIDE.md`) and
the obvious next question is not "what else can the model try" but **what
does this market cost to be in at all.**

---

## The headline: props cost roughly twice what game bets cost

| | player props | game moneylines |
|---|---|---|
| margin the average book charges | **6.79 points** | **3.65 points** |
| tightest book on each contract | 6.49 points | — |
| median books quoting both sides | **2** | **11** |
| settled sample | 1,155 contracts | 155 events |

**Player props cost 1.9× the game market and are quoted by a fifth as many
books.** More expensive to enter, and much harder to shop once you are in.

That does not make props the wrong market. Brey's argument for them stands on
its own — a hitter's chance of a hit is a far more tractable thing to
estimate than which of two teams wins. But it sets the size of the problem:
**the edge required to beat a prop is nearly twice the edge required to beat
a moneyline**, and two pre-registered runs have now failed to find an edge of
even the smaller size.

## What shopping the price is worth

Backing *both sides* of every contract, one unit each, changing only which
price is taken. Backing both sides is a guaranteed small loss — that is the
point. It holds the bet completely fixed, so the only thing separating the
arms is execution:

```
  best  price   ROI -5.59%
  mean  price   ROI -6.72%
  worst price   ROI -7.87%
```

Paired on the same contract so book count and market popularity cancel:
**+1.13 points per bet**, 95% clustered CI [+1.06, +1.20].

**That interval excluding zero proves nothing, and saying otherwise was an
error this document is correcting.** A losing bet returns −1 at every price
and a winning one returns more at the higher price, so the paired difference
cannot be negative. `max >= mean` is arithmetic. The interval measures how
*big* the arithmetic is, not whether it is real money.

What it does say: **1.13 points against a 6.79-point margin — shopping
recovers about 17% of what the book charges.** You still pay 5.6.

Dose-response, which is what real dispersion looks like:

```
  2 books   n=706   +0.92 points
  3 books   n=264   +1.15
  4 books   n=139   +1.73
  5 books   n=42    +2.18
```

## The question the arithmetic cannot ask, and it is not settled

A book sitting well above the others has often moved on news the rest have
not priced — a late scratch, a weather change. If that is what dispersion
mostly is, taking the best price means trading against whoever is fastest and
the 1.13 points is an illusion the outcomes take back.

Contract-sides sorted by how far the best price sits above the mean;
the statistic is realised win rate minus the books' own de-vigged consensus:

```
   dispersion      n    fair  actual     gap
        0.22%    577   0.533   0.541   +0.81
        0.70%    577   0.506   0.496   -1.05
        1.29%    577   0.504   0.515   +1.07
        2.64%    579   0.457   0.449   -0.83
```

**This column is not flat and it is not falling — it is noise.** It bounces
±1 point with no trend, and ±1 point is *the same size as the entire shopping
gain*. So this data cannot distinguish "shopping is worth 1.13 points" from
"shopping is worth nothing because the outlier is informed." Four strata on
one week of prices settles neither, and no conclusion is drawn from it. It is
a shape to watch as the store grows.

## An alarm worth recording

The game-moneyline reference was wrong the first time it was computed. An
unfiltered pass over the same store reported a median best-versus-mean price
gap of **39%** and a maximum of **301%** — one event carried two books at
+2800 while six others said +250, *at the same instant*, 9:32pm Eastern.

That is not dispersion between books. It is an **in-play** price for a team
already losing, and the store carries those.

- Every production consumer filters correctly: `src/report/card.py` and
  `src/analysis/prices.py` pass `is_pregame`/`pregame_rows`, `clv.py` uses
  raw rows only to recover a corrected first-pitch time and filters before
  reading any price, and `engine_bridge.py` reads no prices at all. **No live
  surface is affected.**
- The prop store was checked for the same contamination: **0 of 15,020 quotes
  were observed after first pitch.** Every number in this document and in
  today's two pre-registered runs is pre-game.
- The throwaway query was the thing that was wrong. That is the sixth time in
  two days the instrument was the suspect rather than the thing measured, and
  it looked like an enormous finding for about a minute.

## What this means for the product

1. **Do not push customers into props as a value play on the strength of
   anything measured so far.** It is the most expensive market on the board
   and we have not demonstrated an edge in it. Doing so would be selling the
   worst version of the product.
2. **Shopping the price is real, honest, needs no forecast, and is not
   enough on its own.** 17% of a 6.79-point margin still leaves the bettor
   paying 5.6 points. It is a genuine service — it is not a winning strategy,
   and it must never be presented as one.
3. **If props are pursued, the game market is the cheaper place to prove the
   method.** Half the margin and five times the books. An edge that cannot be
   shown at 3.65 points has no chance at 6.79.
4. **The one input that keeps mattering is the lineup.** Tonight's batting
   slot beats a batter's own season average on plate appearances by 13%, and
   pooling both sides of the scan put the split on a real sample for the
   first time: −1.4% with the slot (n=227) against −25.3% without (n=49).
   Still not significant. Still the clearest signal in the area.
