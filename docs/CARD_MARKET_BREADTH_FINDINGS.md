# The card publishes the one market that has no edge in it

Measured 2026-09-11, prompted by the owner looking at the live TODAY tab:
all five picks were moneyline favourites between -155 and -190, and four of
the five showed a model probability *below* the market's.

Everything below is measured against the repo's own code and stores. The
probes are read-only and are named at the bottom so they can be re-run.

---

## 1. What the card actually selects

`src/analysis/daily_card.py`

- Side is always the market's favourite — `_consensus_side` (:299-310)
  returns whichever side the de-vigged consensus makes more likely.
- The only model test in the file is `agrees = model_p > 0.5` (:355). That
  is a question about **who wins**. It is not a question about price.
- Ranking is by `confidence` (`_rank_key`, :509), and `confidence` is the
  **de-vigged market probability** (:386-388). So picks are ordered by how
  sure the *book* is.
- `STRONG` / `LEAN` are bands on that same market number — 0.62 and 0.55
  (:107-108). "STRONG" means the market is confident, not that we are.
- `select()` has no threshold at all (:523-543). It takes the top 5 and
  backfills to a floor of 3 from the disagreement pile.

`value_points` — the actual edge-vs-price quantity — is computed upstream
(`src/analysis/priceverdict.py:95`) and lands on every moneyline row.
`grep value_points src/analysis/daily_card.py` returns nothing. The card
throws it away.

None of this is accidental. The module argues for it at :37-66: the model
beats a home-field baseline by 0.0012 nats over 1,896 games, so ranking by
its *disagreements* would surface its own largest errors. That reasoning is
sound. What it argues for, though, is publishing **less**, not publishing
favourites — and the same docstring says so: *"Backing market favourites
wins a majority of individual bets and still loses money at the vig."*

## 2. The system already ranks every market on price, and the card ignores it

`src/analysis/opportunities.py:361-366` already does the thing:

```python
derivative = _derivative_rows(date, now, entries, derivative_candidates)
derivative_priced = [r for r in derivative if r["price_verdict"] is not None]
ranked = sorted(rows + derivative_priced, key=_sort_key)
qualifying = [r for r in ranked if r["price_verdict"]["word"] in QUALIFYING_WORDS][:top_n]
```

Moneylines and derivatives compete on one measure. Then `api/card.py:107`
passes only `opportunities.get("rows")` — moneyline-only by construction —
and `src/report/card.py:348` drops non-`h2h` a second time.

**Running the repo's own builder on real slates:**

| date | qualifying bets | of which moneyline |
|---|---|---|
| 2026-09-09 | 5 | **0** |
| 2026-09-10 | 1 | **0** |

On 2026-09-09 the price ranker found five bets worth calling. Not one was a
moneyline. The card published five moneyline favourites that day.

## 3. The "thin boards" claim that justifies moneyline-only is stale

`src/analysis/derivative_prices.py` said: *"Measured on 2026-09-07: 0 of 6
first-five totals and 0 of 12 first-five spreads cleared it."*

Re-measured through the same `candidates_for_date` → `build_opportunities`
path, counting contracts that reach a real verdict (not thin):

| game_date | priced contracts |
|---|---|
| 2026-09-07 | 214 |
| 2026-09-08 | 394 |
| 2026-09-09 | **424** |
| 2026-09-10 | 154 |

2026-09-09 breakdown: alternate totals 216, alternate spreads 64, **team
totals 46**, **pitcher strikeouts 30**, first-five h2h 26, first-five totals
26, first-five spreads 16.

The board went from 7 books deep to 9 and nobody re-measured. The docstring
has been corrected in place.

## 4. These are PRICE edges, not model edges — and they are small

`value_points` is defined as how much cheaper the best book is than the
de-vigged consensus. It is a line-shopping measure. The `opportunities`
module renamed itself away from "TOP OPPORTUNITIES / BEST BETS" on
2026-09-10 for exactly this reason.

The qualifying edges on 2026-09-09 ran **0.65 to 1.0 points**, all worded
`LEAN`, none `STRONG VALUE`. Real, but thin, and you have to bet at the
named book to get them.

This matters for the owner's ask. "The specific bet that makes the most
sense based on historical data" is a *model* claim. What the system can
honestly produce across derivative markets today is a *price* claim. Those
are different products and should not be worded the same way.

## 5. Run lines stay blocked, and that call is correct

`daily_card.py:115-142`: real run variance measured at 2.31x the Poisson
mean, so every run-line probability the card produced was roughly nine
points low. The correction passed every substantive check and **failed its
parameter-stability check at 0.3151 against a 0.30 limit**, and was not
applied.

That is the right call and should not be revisited by moving the threshold.
Note the scope, though: the block applies to *model-derived* run-line
probability. `derivative_prices.py` computes no probability of its own — it
is price-vs-consensus only — so alternate spreads ranked on price do not
depend on the broken run distribution.

## 6. Derivative capture has been dead since 2026-09-10

Last rows in both stores:

```
derivative_markets.jsonl   game_date=2026-09-10  last_obs=2026-09-10T23:22:13Z
prop_prices.jsonl          game_date=2026-09-10  last_obs=2026-09-10T19:40:55Z
```

`build_opportunities` for 2026-09-11 returns `derivative rows=0`.

No workflow under `.github/workflows/` mentions derivatives or props at all.
Forward capture and the daily loop were moved to Actions (P0-1, P0-2);
derivative and prop capture never were, so they only run when a session runs
them. **Wiring derivatives into the card changes nothing until this is
fixed**, and fixing it means scheduled odds-API spend — an owner decision.

---

## What changed in this pass

Only wording and documentation. No selection rule, no ranking, no pick count.

1. `daily_card.py` `_why` — the sentence read *"the market makes Mariners a
   60% bet to win and our own numbers agree at 54%"*. `agrees` is a fact
   about the winner; the sentence rendered it as agreement between two
   directly-comparable probabilities, while the model sat six points below
   the market. It now names the direction, with a new
   `AGREEMENT_BAND_POINTS = 2.0` for "same place". Verified on a forced live
   build of 2026-09-11: four picks now read *"lower than the market, so we
   agree on the winner but the price is against you. This is a read on the
   game, not value at this price"*; the Braves, the only pick with real
   edge, reads *"a little higher than the market, so the price is in your
   favour."* Published cards are frozen in the ledger and are not rewritten.
2. `derivative_prices.py` — stale thinness measurement corrected.
3. `web/js/card.js` — a comment quoting the old wording.

## What needs an owner decision

1. **Does the card publish when nothing has edge?** `daily_card.py:3-14`
   records the directive that it must always publish. §2 shows the nights
   when the honest answer across all markets is "no moneyline is worth
   calling, here are two cheap totals instead."
2. **Scheduled derivative/prop capture** (§6) — recurring API spend.
3. **Price edge vs model edge** (§4) — if derivative markets reach the card,
   they must be worded as price improvement, not as a read on the game.

## Re-running the probes

Written to the session scratchpad, read-only:
`probe_deriv2.py` (supply per game_date vs the six-book floor),
`probe_opps.py` (the repo's own `build_opportunities` on real slates),
`probe_capture.py` (capture recency), `probe_copy.py` (renders the card's
sentences; pass `prefer_frozen=False` or you will be served the frozen row).
