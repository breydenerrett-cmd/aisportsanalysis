# What the first seven published days say about price

Written 2026-09-17, after the owner opened the record page, saw two losing
days after five winning ones, and asked what had broken.

Nothing had. This is the measurement that answers him, and it is the first
piece of evidence this project has produced from its own published money
rather than from a backtest.

## The question

Staging showed game picks at 37-24-0 — a 60.7% strike rate — and **negative**
units, with the last two days at −2.44u and −3.15u after five positive ones.
A 60.7% win rate losing money is the thing that needs explaining.

## The measurement

Read from `evidence/cards_v1.jsonl`, every graded game pick in this checkout
(6 settled days, through 2026-09-15; staging had 7 and the shape is the same).
Break-even is computed from each pick's own price: `1 / decimal_odds`.

| Day | W-L | Units | Hit | Needed to break even | Longest price against |
|---|---|---|---|---|---|
| 09-10 | 2-1 | +0.54 | 66.7% | 58.5% | −165 |
| 09-11 | 7-2 | +2.10 | 77.8% | 63.4% | −205 |
| 09-12 | 6-3 | +0.80 | 66.7% | 61.2% | −212 |
| 09-13 | 5-3 | +0.26 | 62.5% | 59.1% | −183 |
| 09-14 | 6-3 | +1.13 | 66.7% | 58.1% | −207 |
| 09-15 | 5-5 | −2.44 | 50.0% | **64.7%** | −230 |

**48 of 48 graded picks were favourites. Not one underdog, on any day.**

## The finding

Split the same 48 picks at V2's worst allowed price of −160:

| Group | n | Hit rate | Units |
|---|---|---|---|
| Priced −160 or better | 24 | 62.5% | **+2.07u** |
| Priced worse than −160 | 24 | **66.7%** | **+0.31u** |

The picks that won MORE OFTEN returned almost nothing. That is not a paradox
and it is not variance: at −200 the break-even is 66.7%, so winning 66.7% of
them is worth exactly zero before vig. Seven picks were at −200 or worse; the
worst was −230.

## What it does and does not license

It does NOT license a claim that the −160-or-better group has an edge. 24
picks is nothing, both groups are inside the noise of each other, and the
whole sample is seven days of one sport. Nobody may cite +2.07u as a result.

What it DOES establish, and what is worth writing down:

1. The live card takes only favourites, and half its picks sit beyond the
   price the owner ruled out on 2026-09-15.
2. The two losing days are not a regression, a bug, or a data problem. They
   are the same strategy at ordinary luck. The five winning days before them
   ran warm on a bet type with almost no margin.
3. A hit rate quoted without its price is meaningless. 60.7% is a good number
   at +100 and a losing number at −160. Any surface that shows a win rate
   without the price it was earned at is inviting exactly the misreading that
   prompted this document.

## Consequence

`DAILY_CARD_MARKET_SIDE_MODEL_AGREEMENT_V1` ranks by market confidence and
applies no price test whatsoever — it cannot do anything except pick
favourites, because the market's favourite is its ranking key.

`DAILY_CARD_BEST_BETS_V2` (`src/analysis/best_bets_card.py`, committed
31cdf378, ledger 5a95931f) bands −160..+250 and requires our number to clear
break-even plus an edge that widens with the price. It is built and tested.
**It is not registered**, and registration is blocked on owner questions 12 to
14 in `docs/PREREG_CARD_V2.md`.

So the rule that would have refused half of these picks exists and is not
running. That gap is the point of Stage 18's F3, and this document is the
evidence for why F3 matters rather than a tidy-up.

No threshold anywhere was changed in response to these results, and none may
be. Seven days of live picks is a reason to finish a registration, never a
reason to move a bar.
