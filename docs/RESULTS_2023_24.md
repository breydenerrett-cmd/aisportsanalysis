# Discovery results, 2023–24

**Pre-registered family:** `evidence/hypothesis_family.json`, 21 hypotheses,
frozen before any of this was run. FDR q = 0.10, effect floor 1 point of
probability.

**Discovery seasons only.** 2025 is reserved for tuning and 2026 through 08-27
for a single confirmation that has not been touched.

---

## The full family, including the losers

Selections are moneyline picks on games with a recommendation-time price at
least six hours before first pitch and a closing price. **Effect** is the
realised win rate minus the de-vigged consensus probability the market already
implied — a detector that merely restates the favourite scores zero by
construction. Confidence intervals are **clustered by date**, since selections
on one slate share weather, schedule position and market conditions.

All figures in percentage points.

| Detector | n | Hit | Implied | Effect | Clustered 95% CI | p | CLV | ROI | By season |
|---|---|---|---|---|---|---|---|---|---|
| bullpen_exposure | 1322 | 0.5673 | 0.5266 | **+4.08** | +1.26 to +6.54 | 0.0027 | -0.008 | +7.76 | 2023 +3.25 / 2024 +4.92 |
| stale_book | 2655 | 0.5002 | 0.5079 | **-0.77** | -2.27 to +0.68 | 0.4186 | +0.008 | -2.15 | 2023 -1.12 / 2024 -0.25 |
| starter_mismatch | 2018 | 0.5347 | 0.5295 | **+0.52** | -1.68 to +2.77 | 0.6370 | +0.116 | +0.78 | 2023 +0.93 / 2024 +0.11 |
| travel_load | 526 | 0.4981 | 0.5067 | **-0.86** | -4.59 to +3.17 | 0.6902 | -0.036 | -2.08 | 2023 +2.05 / 2024 -3.88 |
| bullpen_workload | 899 | 0.5028 | 0.4964 | **+0.64** | -2.01 to +3.40 | 0.6957 | +0.058 | -0.55 | 2024 +0.64 |

### Family correction

Benjamini-Hochberg at q = 0.10 over the five detectors that produced selections,
plus the one-point effect floor:

**One of five clears both gates: `bullpen_exposure`.** The other four are
consistent with no effect at all — every interval includes zero.

Two of the eleven registered detectors produced no side-bearing selections at
all: `implied_bullpen_disagreement` (its finding is context, not a side) and
`park_and_weather` (it bears on totals). Four more were excluded before the run
as not point-in-time safe. All of that is in `docs/OVERNIGHT_RUN.md`.

---

## The one that survived, and why I do not believe it yet

`bullpen_exposure` fires when a starter's innings-per-start is far from the
league average, and picks his team when he goes deep or the opponent when he
does not.

| | |
|---|---|
| Selections | 1,322 |
| Effect | **+4.08 points** over the implied probability |
| Clustered 95% CI | +1.26 to +6.54 |
| p (raw) | 0.0027 |
| FDR at q=0.10 | **survives** |
| Season stability | +3.25 (2023, n=670) / +4.92 (2024, n=652) |
| ROI | +7.8% |
| **CLV** | **−0.008 points, p = 0.87** |

It survives the base-rate control. Away picks beat their price by +1.79 points
across every detector in this sample, so a detector that leaned away would
inherit that for free. This one does not lean: 669 away against 653 home, both
sides pointing the same way (away +4.73, home +3.40). Re-scoring every selection
against its own side's base rate leaves **+3.41 points, p = 0.012, CI +0.62 to
+5.88**.

### The objection that matters more than the p-value

**Its closing line value is zero.** −0.008 points, p = 0.87.

If a detector held real information, the price should drift toward it between
the recommendation and the close. Here the outcome beats the price by four
points while the market does not move at all. That is either a market blind spot
that persisted across two full seasons, or a result that will not repeat.

CLV is the metric this project pre-registered as primary precisely because it
converges faster than return. It says nothing is here. The outcome statistic
says something is. **Until those agree, this is a candidate, not a finding**, and
it is labelled `historical_candidate` rather than anything stronger.

### What would settle it

2025 is the tuning season and is available; 2026 is sealed and stays sealed. But
the honest resolution is forward: the ledger began on 2026-08-28 and grades this
detector on games nobody has seen, with both CLV and outcome recorded.

---

## Result 1 — implied bullpen assessment: **no effect found**

The project's most original idea, and it does not work at this sample size.

### The hypothesis

A full-game price and a first-five price on the same team differ by exactly one
thing: innings six through nine. So `full_game_fair − first_five_fair` is not a
proxy for the market's bullpen view, it **is** that view in probability units.
The test: does a larger implied shift predict the home side actually gaining
ground after the fifth?

### The measurement

**308 games**, 2023–24, every one with a full-game and a first-five price taken
at **exactly the same instant** — separation 0.0 minutes, because both backfills
sampled the same snapshot times. That removes the failure mode that would have
sunk this: a price nine hours out compared against one fifteen minutes out
differs by the bullpens *and* by nine hours of market movement, and the second
term is far larger.

146 first-five rows were dropped for having no first-five price on the board.
None were dropped for mismatched timing.

| | High shift (n=153) | Low shift (n=155) |
|---|---|---|
| Home gains ground late | 15.7% | 12.9% |
| Home loses ground late | 11.8% | 9.7% |
| **Net** | **+3.9%** | **+3.2%** |

### The result

**Difference in net late gain: +0.70 points. p = 0.90. Clustered 95% interval
−10.5% to +11.8%, over 178 date clusters.**

Squarely zero.

### The trap inside it

The headline row looks like a hit: 15.7% against 12.9% is a 2.8-point gap in
exactly the predicted direction. It is an artifact. The high-shift group gains
late more often **and loses late more often** — it changes hands 15.0% of the
time against 10.3%. Reading only the favourable row would have produced a
"finding" that was a volatility effect wearing a direction.

So the volatility reading was tested too, both ways:

| Framing | Difference | p | Clustered CI |
|---|---|---|---|
| Signed shift → changes hands | +4.7% | 0.21 | −3.1% to +12.1% |
| Absolute shift → changes hands | −5.7% | 0.13 | −13.1% to +1.9% |

Both include zero, and they point in **opposite directions**, which is what
noise looks like.

### Honest note on my own multiple comparisons

Three framings were tested on one dataset. None reached significance, so no
correction changes the conclusion — but had one done so, it would have needed
correcting for the three, and the correct move would have been to pre-register
the framing before looking. The direction test was the pre-registered one; the
two volatility tests were prompted by the data and are reported as exploratory.

### What this does and does not rule out

- **Ruled out at this sample:** the market's implied bullpen shift, on its own,
  predicting who gains ground late. n = 308 can only detect a large effect, so a
  small real one would not have shown.
- **Not tested:** whether *disagreeing* with the market's shift is profitable.
  That needs our own bullpen availability read on the same games, which requires
  2023–24 boxscore ingestion — in progress. That was always the version that
  could be a bet; this one only ever asked whether the market is competent.
- **Not affected:** the detector still earns its place on the live page as
  context. Stating what the market thinks of two bullpens is worth a line
  whether or not it predicts anything.
