# Pre-registration: after news, does the price move the way we could have called?

**Written 2026-09-11, before the measurement was run.** The criteria below are
fixed. They are not moved afterwards to rescue a result.

---

## Why this is the measurement that matters

`docs/INFORMATION_EDGE_FIRST_LOOK.md` established a distinction this repo had
been collapsing. Every measurement in
`docs/DOES_THE_MODEL_BEAT_THE_MARKET.md` asks whether **our number** beats
**their number** — a question about modelling, answered *no* five times. The
owner named a different one: knowing a *fact* before the price does.

The first attempt to measure it failed, and it failed instructively. It asked
how far a price travels after news, against a control anchored at quiet
moments. The control could not be built: in the three hours before first
pitch — when lineups post and scratches land — **a comparable moment with no
news barely exists.** The events are not incidental to the busy period; they
*are* the busy period.

**Direction sidesteps that entirely.** If, after a player is placed on the
injured list, his team's win probability falls more often than chance, that
is a real asymmetry whether or not boards are generally busy at that hour.
There is no quiet-hour control to build, because the null is not "no
movement" — it is **50/50 on which way**.

And direction is the only form of this that is bettable. Knowing a price will
move is worth nothing. Knowing which way is the whole game.

---

## The defect this design exists to avoid

Five nulls are on the record in this repo and **not one of them can
distinguish "there is no effect" from "the instrument cannot see."** That is
a real hole. A measurement that can only ever return *no* is not evidence of
absence; it is an untested instrument.

So one hypothesis here is a **positive control**: an effect that is known to
be real, that is public to every book, and that we therefore expect to find.
Warm air is less dense and the ball carries; rising forecast temperature
raises run expectation. This is the best-documented environmental effect in
baseball and it is **not a claim of edge** — everyone can read the same
forecast.

Its job is to license the interpretation of the others:

- **Control confirms, tests null** → the instrument works and the null is
  real. Worth believing.
- **Control fails** → the instrument is blind. Every null in this document is
  uninformative, and nothing may be concluded from them.

Without this, a null on the injury tests would be exactly as worthless as the
five that came before.

---

## Hypotheses, each with its sign fixed here

Signs are declared before any data is touched. A hypothesis whose sign is
chosen after seeing the movement is not a test.

### Primary family (three; these carry the decision)

| # | Event | Market | Predicted direction | Rationale |
|---|---|---|---|---|
| **C** | `weather_forecast_updated`, temp rises | consensus posted total | **total rises** | *Positive control.* Warm air is thinner, the ball carries. Public to every book. |
| **H1** | `transaction_relevant`, `il_placement` | that team's de-vigged win probability | **falls** | The team just lost a player it was counting on. |
| **H2** | `transaction_relevant`, `il_activation` | that team's de-vigged win probability | **rises** | The team just got a player back. |

For a temperature *fall*, C's prediction reverses; the hypothesis is about
the signed relationship, and every temperature change with a recorded
`from` is used, in the direction its own delta implies.

**Why only these three.** `recalled` (71) and `optioned` (40) are the larger
buckets and are deliberately **not** primary: a recall usually accompanies
someone else going the other way, so the net effect on team strength is
genuinely ambiguous and its sign cannot be declared honestly in advance.
Declaring a sign one does not believe, in order to gain sample size, is how
a pre-registration becomes theatre.

### Secondary, descriptive (declared now so they cannot be introduced later)

Reported with intervals; **none of them can promote anything**, and none is
counted in the multiplicity correction because none carries a decision.

1. `recalled`, `optioned`, `designated`, `rehab` — reported as two-sided with
   **no predicted sign**, purely to see whether anything is there.
2. Precipitation probability rising → total falls (rain-shortened games are
   shorter games). Plausible but not established; n is small.
3. `lineup_changed` (14 events, 13 real substitutions) — far too few to test.
   Reported as a listing, not a statistic.
4. Wind speed is recorded **without direction**, so its effect on a total is
   unsignable. Excluded, and noted here so its absence is not mistaken for an
   oversight.

---

## What is measured

**Population.** Every information event whose game is on a board we were
capturing, with a usable consensus quote on **both** sides of the event
timestamp inside the window.

**The anchor** is `observed_utc` — the instant *we* saw it, not the instant it
happened. That is the honest anchor for an edge claim: it is what we could
have acted on.

**The move.** `consensus(last quote in window after anchor) − consensus(last
quote at or before anchor)`.

**Net, not peak.** The first probe used peak travel. Peak is the right
statistic for "did anything happen" and the wrong one for direction, because
picking the extreme of a noisy path is a free parameter that flatters the
result. Net movement over a fixed window has no such freedom.

**Window:** `HORIZON_MINUTES = 120`, unchanged from the first probe.

**Consensus** for a moneyline is the mean two-way de-vigged home probability
across books, requiring `MIN_BOOKS = 3` two-way books at an instant. For a
total it is the mean posted total across books at that instant, same floor.
In-play quotes are excluded (`snapshots.is_pregame`).

**Side resolution.** A transaction names a team code; the results store gives
each game its home and away code. The team's own win probability is the home
probability when it is home, and its complement when it is away. **An event
whose team cannot be resolved to a side is dropped, not guessed** — and the
count of drops is reported.

**The statistic** is the **hit rate**: of events that moved at all, the
fraction that moved in the predicted direction.

**Ties.** A net move of exactly zero is not evidence in either direction. Such
events are excluded from the denominator **and their count is reported**.
Silently dropping them would let a market that mostly does not move at all
masquerade as one that moves correctly.

**Uncertainty.** Events on the same game share one board and are not
independent. The interval is a **clustered bootstrap over games** — whole
games resampled, 2,000 resamples, RNG seeded `20260911` so it reproduces.

---

## The decision rule, fixed before running

Three primary hypotheses, so the family-wise correction is **Bonferroni:
α = 0.05 / 3 = 0.0167**, i.e. intervals are reported at **98.33%**, not 95%.
This is stated here so it cannot be quietly relaxed to 95% afterwards.

For each primary hypothesis, with hit rate `p` and its clustered interval:

- **CONFIRMED** — interval lower bound **> 0.50** and `n >= 25`.
- **REFUTED** — interval upper bound **< 0.50**. The market reliably moves the
  *other* way, which is a finding, not a failure, and would mean the sign was
  declared backwards.
- **UNDETERMINED** — interval spans 0.50, or `n < 25`.

**`n >= 25` is a floor, not a target.** A hit rate of 1.00 on four events is
not a finding and will be reported as UNDETERMINED however tempting it looks.

**No rescue clauses.** If a hypothesis lands UNDETERMINED it is reported
UNDETERMINED. The population is not narrowed, the window is not re-tuned, the
horizon is not swept, and no subset is promoted on the strength of its point
estimate.

---

## The second question, and it decides whether any of this is an edge

A confirmed direction is **necessary but nowhere near sufficient**. If the
market had already moved before our timestamp, we are reading news the price
has finished absorbing, and knowing the direction is worth nothing.

So the same signed statistic is computed over the window **before** the
anchor — `[anchor − 120min, anchor]` — and reported beside the after window:

- **Before ≈ chance, after > chance** → the move follows our observation.
  A window exists. This is the only pattern that supports an edge.
- **Before > chance already** → the price moved first. We are late, and the
  event kind is a record of what the market already knew. **This is the
  expected result for the public positive control**, and finding it there
  would be reassuring evidence the before/after split works.
- **Both at chance** → nothing to see.

This is descriptive and carries no decision, because the before-window
statistic has a confound of its own: an IL placement is often preceded by
hours of reporting that never reaches our ledger. A high before-rate is
therefore evidence we are late, but a low one is not proof we are early.

## What this cannot say, in advance

- **Nothing here is a backtest.** Moving in a predicted direction is not a
  profit. Vig, limits, the price actually available at that instant, and
  whether a bet could have been placed at all are untouched.
- **`observed_utc` is our poll time, not the world's.** Our watchers run every
  fifteen minutes, so a real edge could be up to that much larger than
  measured — or the event could have been public for fourteen of those
  minutes. This blurs both directions and is not corrected for.
- **One partial season of one sport.** Whatever this finds is a hypothesis
  about MLB 2026, not a law.
