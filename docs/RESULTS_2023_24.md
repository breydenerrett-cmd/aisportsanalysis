# Discovery results, 2023–24

**Pre-registered family:** `evidence/hypothesis_family.json`, 21 hypotheses,
frozen before any of this was run. FDR q = 0.10, effect floor 1 point of
probability.

**Discovery seasons only.** 2025 is reserved for tuning and 2026 through 08-27
for a single confirmation that has not been touched.

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
