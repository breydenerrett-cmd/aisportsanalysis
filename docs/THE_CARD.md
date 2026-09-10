# THE CARD

Three to five bets a day, in plain English, frozen before first pitch and
graded in public. Shipped 2026-09-10.

This document is the honest account of what it is, what it is built on, and
what the evidence currently says it is worth. If those three ever disagree
with the front page, the front page is wrong.

---

## Why it exists

Every customer-facing surface in this product before today answered "where
is this bet cheapest". None answered "what should I bet". The owner's
instruction, in substance: the slate board looks like a lot of random
numbers, nobody knows what "de-vig" means, and if the game is
Nationals–Padres there needs to be a bet that says take the Padres. And the
site may never again tell a paying reader that nothing cleared the bar.

Both halves of that are now enforced mechanically:

- `src/analysis/daily_card.py` has `MIN_PICKS = 3`, and the floor is met by
  lowering the **label**, never by inventing a claim.
- `tests/test_no_nothing_clears_the_bar.py` bans the sentence and the jargon
  across every customer-facing file, comment-stripped so it cannot pass by
  matching its own documentation.

---

## The rule, pre-registered

Fixed in code before the slate is read, so it cannot be chosen with the
candidate list in view.

1. Every game that has not started and carries a moneyline on at least
   `prices.MIN_BOOKS` books is a candidate.
2. The **side** is whichever the multi-book market makes more likely. That is
   the market's opinion, not ours, and the copy says so.
3. Our own run model must **agree** that side is more likely. Where it
   disagrees the pick is demoted and labelled `SPLIT`, never promoted.
4. The **market** is the moneyline unless the run line prices the same
   opinion better against the model's own distribution. One bet per game.
5. Rank by the moneyline consensus, tie-break on price standing. Publish at
   most 5.
6. If fewer than 3 survive step 3, fill from the demoted pile in the same
   order, each carrying `SPLIT`.

### Why a disagreement demotes rather than promotes

This is the counter-intuitive line, and it is the one that keeps the
2026-09-09 incident from happening again in a new costume.

The obvious product is "our model says 62%, the market says 54%, bet it".
That requires the model to be **better** than the market. Ours is not.

Measured walk-forward over 1,896 games of the 2026 season
(`scripts/backtest_card.py`), the model beats a coin that knows only the
home-field base rate by **0.0012 nats**. A market beats that baseline by an
order of magnitude more. A model that weak, ranked by its *disagreements*
with the market, selects its own largest errors — with maximum confidence,
because the size of the disagreement is the size of the error.

So the model is used for the one thing a weak-but-honest model is good for:
agreement. When two independent reads point the same way the pick is
ordinary; when they split, the reader is told they split.

---

## The model

`src/analysis/strength.py`. Two Poisson run means per game, from which the
moneyline, the run line and the total all fall out of one joint
distribution — so the card can never publish a moneyline and a run line that
contradict each other.

```
runs_allowed = starter_share * starter_rate + (1 - share) * team_rate
expected_runs = offence * defence / league_average          (log5, on runs)
margin        = home_runs - away_runs + HOME_FIELD_RUNS
```

**Nothing in it is fitted.** Every constant is either published
(`HOME_FIELD_RUNS = 0.20`, `FIP_TO_RA_SCALE = 1.08`) or measured from the
point-in-time store at call time (the league run rate). A model with no free
parameters cannot be overfitted, so its out-of-sample behaviour is its only
behaviour.

`MARGIN_INFLATION` is deliberately **1.0 — off**. It is a real correction
(runs are overdispersed relative to Poisson) and switching it on without an
out-of-sample measurement would be a fitted parameter wearing a constant's
clothes. `tests/test_strength_model.py` asserts it stays off.

### Where the model is wrong, stated up front

- Runs are overdispersed relative to Poisson, so tail probabilities are
  understated and blowout run lines shade toward the middle.
- `bullpen_rate` is the team's whole-season allowance, which includes the
  starters, so rotation quality is double-counted a little.
- Lineups are ignored. A club resting four regulars is priced as its season
  self.
- Park and weather are ignored. Coors Field is priced like Petco.

---

## Calibration

The raw model orders games correctly and states its confidence wrongly.
Measured over the same 1,896 games:

| it said | home team actually won |
|---|---|
| 36% | 45% |
| 55% | 53% |
| 64% | 57% |
| 73% | 60% |

Monotone, so the **ordering** carries information; compressed, so the
**numbers** were fiction.

`src/analysis/calibrate.py` fits Platt scaling walk-forward — to calibrate a
game on date D it uses only games that finished strictly before D. The fit
over the full season lands at **b ≈ 0.51**: the model is roughly twice as
confident as its accuracy earns.

`scripts/fit_card_calibration.py` refits nightly from
`scripts/daily_loop.sh`. Without `data/processed/card_calibration.json` the
card would serve raw, overconfident numbers under the same words — so the
file is tracked in git, the card payload carries `calibrated: false` when it
is missing, and `scripts/publication_audit.py` escalates on both.

---

## What the evidence says so far

**Model vs. a coin that knows the home-field base rate** — walk-forward,
1,896 games, 2026-04-15 to 2026-09-06:

| | log-loss | Brier | accuracy |
|---|---|---|---|
| model (calibrated) | 0.69103 | 0.24888 | 53.7% |
| model (raw) | 0.69183 | 0.24914 | 53.7% |
| always the base rate | 0.69226 | 0.24955 | 52.1% |

Gain over the base rate: **+0.00123 nats**. Real, and very small.

**The selection rule vs. controls** — `scripts/backtest_card_rule.py`, over
the eleven days where real multi-book prices exist (2026-08-31 to
2026-09-10):

| arm | n | win rate | ROI | 95% interval |
|---|---|---|---|---|
| every consensus favourite | 97 | 53.6% | −7.8% | [−25.1%, +9.5%] |
| card: favourite, model agrees | 72 | 54.2% | −9.7% | [−29.1%, +9.8%] |
| contrarian: favourite, model disagrees | 25 | 52.0% | −2.4% | [−40.0%, +35.1%] |

**Read the intervals, not the point estimates.** Ninety-seven bets settles
nothing about profitability: every arm's interval spans thirty-plus points
of ROI, which is wider than any effect anyone is arguing about. The
difference between the arms is not a finding, in either direction. The card
does not currently have evidence that its model filter helps, and it does
not have evidence that it hurts.

**Nothing on this page may be quoted as a claim that the card wins.** The
thing that will eventually answer that question is
`evidence/cards_v1.jsonl`, which started accumulating on 2026-09-10.

---

## The receipts

`src/appstate/card_ledger.py`, a hash-chained append-only ledger.

- **Frozen on publication.** `publish` is idempotent per date. A retry after
  the lines move cannot rewrite what a reader was shown.
- **Graded, never re-scored.** `settle` appends a *separate* row. The
  published row is never touched, so the file reads as what was claimed and
  then what happened, in that order.
- **The page serves the frozen row.** `src/report/card.py`'s `frozen_card`.
  Without this the endpoint would rebuild from live prices and drift away
  from the ledger, and the record would be receipts for a card nobody saw.
- **Voids are counted and reported.** A game with no final score grades
  `VOID`, never `LOSS`. A postponed slate counted as losses is the one way a
  public record goes quietly wrong in the direction nobody thinks to check.

Return is flat one-unit stakes at the published price. It is not a claim
that anyone bet that amount.

---

## Cadence

| when | what | escalates |
|---|---|---|
| `afternoon_slate.sh` (21:10Z) | `card publish` — freeze the day | yes |
| `daily_loop.sh` (10:00Z) | `card settle` — grade yesterday | yes |
| `daily_loop.sh` | `card record` — print the running record | no |
| `daily_loop.sh` | `fit_card_calibration.py` — refit | yes |
| `capture_slot.sh` (*/15) | `publication_audit.py` — check the claims | yes |

`scripts/publication_audit.py` checks the card for: the floor of three,
games that have already started, missing prices or books, an uncalibrated
publish, a stale calibration file, and the ledger's hash chain.

---

## What would change the story

In rough order of how much each would move the product:

1. **A real bullpen rate.** The single largest known error in the model, and
   the data (`data/historical/bullpen_log.jsonl`) is already captured.
2. **Lineups.** Posted lineups are already stored and already join to games;
   the model ignores them entirely.
3. **Park and weather.** Both are in the dossier and neither reaches the run
   means.
4. **Totals.** The joint distribution prices them today and the card does not
   publish them, because their pairing has not been verified end to end the
   way the run line's was.
5. **Enough settled days to say anything.** A hundred graded picks is where
   the record starts being able to reject "this is a coin flip at the vig",
   and that is roughly a month.

None of those is a promise. Each is a thing that is measurably missing.
