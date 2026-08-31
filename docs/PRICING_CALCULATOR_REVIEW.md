# Pricing-page calculator — quantitative review

**Reviewing:** the breakeven/ROI calculator proposed in
`docs/PRODUCT_DESIGN_HANDOFF.md` (Pricing-page rules #3; "REAL — an
ROI/breakeven calculator" opportunity section), whose illustrative copy is:

> *"At $50 a bet and 20 bets a month, a 1.5-point better price is worth about
> $X/month. This plan costs $29."*

**Verdict: the sentence as drafted is NOT honest and must not ship. An honest
calculator exists, but it is a different calculator.** Specification below.

---

## 1. Why the drafted sentence fails

"A 1.5-point better price is worth about $X/month" smuggles in three claims:

1. **A win probability.** A price difference pays out only when the bet wins.
   Any single dollars-per-month figure is `bets × stake × Δdecimal × p_win`
   for some `p_win` the sentence never states. We have no validated win
   probability (model UNCALIBRATED per the handoff itself), so any `p_win` we
   pick is fabricated.
2. **A wrong baseline.** The engine's "improvement" (`src/analysis/prices.py`)
   is **best quoted price vs the de-vigged consensus**. The de-vigged
   consensus is not a price anyone quotes — you cannot bet it — so
   "improvement over consensus" is not money you could have captured by
   shopping. Worse, that number is **negative on a normally-priced board**
   (the module's own `NO_IMPROVEMENT_NOTE`: the best price still carries vig;
   the consensus has had it removed; the gap is roughly minus the hold). A
   calculator seeded from it would either show negative value or require us
   to cherry-pick the exceptional positive instants — persuasive arithmetic.
3. **Takeability.** `docs/EVOLAB_PHASE0_FEASIBILITY.md`: "takeable at size"
   is not measurable from any data we hold or could buy; only "on the board
   at that instant" is defensible. And in 62.7% (2023) / 78.6% (2024) of
   instants the best price is tied across books, so *which book* had it is
   an artifact of iteration order — the price is real, the book usually not.

Also: "1.5 points" is ambiguous (implied-probability points vs American
cents). The engine reports probability points; pricing copy will be read as
cents. Any spec must fix the unit.

## 2. What survives — the four questions worked through

### (a) Unconditional statements

For the **same bet, same stake, two quoted prices** (decimal `d_best ≥ d_other`):

- If the bet **loses**, both tickets lose the stake. Difference: $0. Exact.
- If the bet **wins**, the better ticket pays `stake × (d_best − d_other)`
  more. Pure arithmetic.

So the one unconditional claim is **dominance**: taking the better quoted
price never costs anything and pays strictly more whenever the bet wins.
This is honest *only if both branches are stated* — quoting the win branch
alone is selective — and *only if both prices are quoted prices* (not the
de-vigged consensus). It is a comparison of executions of a bet the user was
making anyway; it says nothing about whether the bet is worth making.

### (b) Probability-free framings — two exist

1. **The two-branch payout statement** above, aggregated:
   `bets/month × stake × (d_best − d_baseline)` labelled explicitly as
   "extra payout **on the bets that win**; on losing bets the difference is
   $0". No probability enters; the conditioning is visible, not hidden.
2. **Breakeven-probability shift.** Breakeven win rate at decimal `d` is
   `1/d`. "At −110 you need 52.4% to break even; at −105 you need 51.2%."
   Pure price arithmetic, no assumed win rate, and it *is* the honest
   meaning of "this price is cheaper". This is the natural companion line.

A "vig you pay" dollarization does **not** survive: converting hold into
dollars per bet is an expectation and re-imports a probability. Vig may be
stated as a percentage of price only, never as dollars.

### (c) Consensus-weighted illustration

Multiplying the win branch by the market-implied consensus probability is
arithmetically coherent and could be defended **as an illustration only**,
with all of: (i) the label "market-implied consensus, not a prediction and
not our estimate of the true probability"; (ii) never the words "expected
profit", "EV", "edge", or "worth $X" — the handoff's own NEVER-SAYS rules
already ban these; (iii) the number shown alongside, not instead of, the
two-branch statement. **Recommendation: do not use it.** It buys one blended
number at the cost of a probability-shaped figure on the page that skimming
readers will read as expected profit, which is exactly the category
dishonesty (Unabated's "true EV") the handoff stakes our position against.
The two-branch framing loses nothing that matters.

### (d) Takeability and ties

Any output must (i) never name the book holding the best price (tie rate
63–79%); (ii) carry the qualifier "prices as quoted at the instant we
observed them; availability at your stake is up to the book". This is one
sentence of small print, but it is non-negotiable — without it the
calculator claims an execution guarantee we cannot verify.

### The baseline choice

The honest baseline is **another quoted price on the same board** — e.g. the
median quoted price, standing in for "the one book you'd otherwise use".
Best-vs-median is realizable shopping value: both prices were simultaneously
on the board (the one execution-realism claim Phase 0 confirms). The
de-vigged consensus is barred as a calculator input.

**UNKNOWN:** the typical best-vs-median gap in our stores has not been
measured. It must be computed from the multibook capture store before any
default example is published; no default gap may be invented. Until measured,
the calculator ships with user-entered odds only and no pre-filled "typical"
example.

## 3. Approved specification — "What line shopping is worth" calculator

Rename: not "ROI calculator", not "breakeven calculator" in the
pays-for-itself sense. It computes payout differences and breakeven
probabilities. Nothing else.

### Inputs (all user-entered)

| Input | Type | Constraints |
|---|---|---|
| `stake` | dollars per bet | > 0 |
| `bets` | bets per month | integer ≥ 1 |
| `odds_a` | American odds, "the price you'd have taken" | valid American (≤ −100 or ≥ +100) |
| `odds_b` | American odds, "the better price on the board" | valid American; decimal(b) must be ≥ decimal(a), else swap with a visible note |

No pre-filled odds pair until the best-vs-median gap is measured from the
store (see UNKNOWN above); placeholder text may show the input format only.

### Computation (exact)

```
d(american) = 1 + american/100          if american >= 100
            = 1 + 100/abs(american)     if american <= -100
delta_per_win   = stake × (d(odds_b) − d(odds_a))     # round to cents
delta_per_month = bets × delta_per_win                 # round to cents
breakeven_a_pct = 100 / d(odds_a)                      # 1 decimal place
breakeven_b_pct = 100 / d(odds_b)                      # 1 decimal place
```

### Output copy (exact wording; substitute bracketed values only)

> **If a bet at [odds_b] wins, it pays [$delta_per_win] more than the same
> bet at [odds_a].** If it loses, both lose the same [stake]. Over [bets]
> winning bets, that's [$delta_per_month] — paid only on the bets that win.
>
> The better price also lowers your bar: at [odds_a] you break even winning
> [breakeven_a_pct]% of the time; at [odds_b], [breakeven_b_pct]%.
>
> *No prediction involved — this is the arithmetic of two prices on the same
> bet. Prices are as quoted at the moment we observed them; whether a book
> accepts your stake is up to the book. Finding the better number is what
> [product] does.*

### Hard wording constraints (implementer has no discretion)

1. NEVER: "worth $X/month", "expected", "EV", "edge", "profit", "ROI",
   "pays for itself", "guaranteed", "+X% value", or any single unconditional
   dollars-per-month figure.
2. The losing branch ("if it loses, both lose the same") must appear in the
   same visual block as the winning branch, same font size.
3. The takeability sentence and "no prediction involved" sentence may not be
   collapsed into a tooltip or footnote link; they render inline.
4. Never name a book. Never show the de-vigged consensus in this component.
5. Units: American odds in and out; "points" never appears.
6. The plan price ($29) may appear near the calculator but must not be
   arithmetically compared to `delta_per_month` in copy (no "covers the
   subscription N times over") — that comparison is the smuggled-probability
   claim re-entering through layout.

### Why this is still persuasive

It is the commitment device the handoff wanted: it demonstrates that the
product's value is checkable arithmetic, states both branches, and the
breakeven line quantifies "cheaper" without any probability. It is the only
calculator in the category that a hostile reader cannot fault.

## 4. Follow-up required before launch (not part of this component)

Measure from the multibook store: distribution of best-vs-median quoted
price gap (in American cents and in decimal), per instant, above the 6-book
floor. That measured number — with its sample size — is the only legitimate
source for any "typical gap" example ever added to the page.
