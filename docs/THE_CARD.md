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

**One constant is fitted, and it took three pre-registrations.** Everything
else is published (`HOME_FIELD_RUNS = 0.20`, `FIP_TO_RA_SCALE = 1.08`) or
measured from the point-in-time store at call time (the league run rate).

### `DISPERSION = 2.3352` — runs are not Poisson

Per-team run variance is **2.33× the mean**, not 1.0×. Poisson badly
understates how spread out real games are, and it costs most on the exact
quantity a run line pays: 72.7% of real games are decided by two or more
runs and independent Poissons say 61.0%.

Adopted 2026-09-10 after being **refused once**. Full history in
[`PREREG_RUN_DISPERSION.md`](PREREG_RUN_DISPERSION.md); the short version is
that the first pre-registration's stability check failed, the threshold was
not moved, and the question was then settled on the 2025 season — 2,212
games ingested afterwards, untouched by any prior measurement:

| | dispersion | se |
|---|---|---|
| 2025, estimated from scratch | 2.3265 | 0.0682 |
| 2026, the value applied | 2.3352 | — |
| apart | **0.128 standard errors** | |

Applying the 2026 value unchanged to 2025: run-line calibration error
**0.08088 → 0.00950**, moneyline log-loss **−0.0065 nats**. That last number
is roughly seven times the model's entire gain over a home-field base rate —
correcting the *shape* of the run distribution did more for picking winners
than every other input in the model combined.

### Where the model is still wrong, stated up front

- The two clubs' scores are modelled as independent. Measured and defensible
  — residual correlation −0.0203 over 1,896 games, z = −0.88 — but it is an
  assumption, not a finding of zero.
- A single dispersion constant is one number where the true shape has more
  than one. The books' own boards still disagree with our run line by a
  uniform ≈2.4 points after the correction, and that residual is most likely
  this.
- `bullpen_rate` is the team's whole-season allowance, which includes the
  starters, so rotation quality is double-counted a little.
- Lineups are ignored. A club resting four regulars is priced as its season
  self.
- Park and weather are ignored. Coors Field is priced like Petco.

---

## Calibration

**This section describes the model as it was BEFORE the dispersion
correction, and the correction changed the picture — see the note at the
end.** The table below is kept because it is the reason the calibration
layer exists at all.

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

### The correction changed this, and the question it raised is now answered

With the run distribution fixed, the model is far better calibrated
natively. The fitted shrink relaxed from **b = 0.489 to b = 0.708** — it
needs much less correcting than it did.

That raised a real worry: over the full 2026 season the raw model's
walk-forward log-loss (**0.68831**) came out *better* than the calibrated one
(**0.69137**), which would mean the layer was now over-shrinking a model that
had earned its confidence.

**Tested, and the worry was wrong.** `scripts/test_calibration_still_helps.py`
fits Platt once on 2025 and applies it to 2026, so the fit never sees a game
it is scored on:

| | log-loss on 2026 |
|---|---|
| raw | 0.688326 |
| calibrated | **0.687946** |

Calibration **helps** by +0.00038 nats, and helps in both halves of the
season. Under the criterion fixed before the test ran — keep if it gains
0.0005, drop if it loses 0.0005, otherwise leave alone — the verdict is
**leave it in place**.

**What the 0.69137 actually was:** the walk-forward *procedure* warming up.
In April it fits on a handful of games and is mostly noise, and that drags
the season figure down. It is an artefact of how the backtest simulates
calibration, not a property of the live card — which fits on ~1,900
completed games by September, not on a handful.

The prediction that this was the explanation was written into the test's
docstring before it ran.

---

## What the evidence says so far

**Model vs. a coin that knows the home-field base rate** — walk-forward,
1,896 games, 2026-04-15 to 2026-09-06, with the real relief rate:

| | log-loss | Brier | accuracy |
|---|---|---|---|
| model (calibrated) | 0.69137 | 0.24905 | 53.5% |
| model (raw) | 0.69256 | 0.24950 | 54.4% |
| always the base rate | 0.69226 | 0.24955 | 52.1% |

Gain over the base rate: **+0.00089 nats**. Real, and very small.

### The bullpen change, and the number that disagrees with itself

The relief innings used to be priced with the team's whole-season
runs-allowed rate, which includes its own starters — so the rotation was
counted twice. `src.pipeline.bullpen.relief_rate` replaced it with a real
relief-only figure on 2026-09-10.

**The two measurements of that change do not agree, and both are here.**

| test | window | result |
|---|---|---|
| `scripts/test_bullpen_rate.py` — window fixed BEFORE running | 2026-07-16 onward, 710 games | **+0.00216 nats**, improving in both halves |
| `scripts/backtest_card.py` — full season, walk-forward | 2026-04-15 onward, 1,896 games | **−0.00034 nats** |

The mechanism is not mysterious. `relief_rate` regresses toward the league
over a 120-inning prior, and in April a club has barely any relief innings
before its own game — so the early-season figure is mostly the league
average with extra noise on top. The July-onward window starts with half a
season of bullpen behind every club.

**The pre-specified test is the one that counts**, because its window was
fixed before it was run and the full-season figure was computed afterwards.
A post-hoc measurement does not overturn a pre-specified one; that is the
entire reason for specifying first. It is reported here anyway, at the same
size, because a reader deciding whether to believe this model is entitled
to the number that argues against it.

**What was deliberately not done:** the 120-inning prior was not enlarged,
and the relief rate was not switched off for thin samples. Both would be
tuning a constant against a result already seen, and either might well be
right — which is exactly why they need a window fixed in advance.

Raw accuracy went the other way too, 53.7% to **54.4%**, while calibrated
log-loss fell slightly. Mixed, and stated as mixed.

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

### The park factor — built, measured, and NOT wired in

`src.pipeline.parkfactors` derives a real run factor per venue,
point-in-time, from the home club's own home-versus-road split — not from
"runs at this venue over the league average", which is part park and part
the home club's own offence and would double-count what the model already
knows. Regressed toward neutral over 150 imaginary games, because a raw
single-season park factor on ~70 games is mostly noise.

The factors are sensible: **0.94 to 1.16, mean 1.00** across the evaluation
window.

`scripts/test_park_factor.py` on the same 710-game window as the bullpen
test: moneyline gain **+0.000337 nats** against a 0.0005 threshold, improving
in both halves, with run-line calibration marginally better (0.08707 →
0.08694). **DO NOT ADOPT**, and the threshold did not move.

**The test's own docstring predicted this before it was run**, and the
prediction is the useful part: a park multiplies both clubs' run means
equally, so it changes how MANY runs are scored far more than it changes WHO
wins. A near-zero moneyline result was named in advance as the likely
outcome and as meaning the factor belongs in the totals and run-line
surfaces — which the card does not publish.

So the code exists, is tested and is correct, and nothing passes
`park_factor` to `run_means`. It is off. When totals are published, this is
the first thing to switch on and it already has its measurement.

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
