# Game plan after the reframe

**Written 27 Aug 2026.** The strategy this project is being built for was described in
detail for the first time, and it is not the objective the codebase was optimising. The
scanner in `docs/MISMATCH_SCANNER.md` is the first piece built for the real objective.
This document does the part that was missing: says what happens to everything else, and
in what order.

## The three things that changed

1. **EV is not the selection criterion.** *"Trying to find bets that have good value or
   EV isn't necessarily a part of the strat."* The question is whether a talent gap is
   visible without a model, not whether a price is wrong.
2. **First-five is a named target market.** The pipeline had never requested it.
3. **Live betting is central**, triggered by *"statistics that just don't align with
   previous history"*. Nothing in the repository can observe a game in progress.

And one thing that did not change: **no real money, ever. Paper only, and no code
capable of placing a bet.**

## What happens to what already exists

Nothing is deleted. The distinction is between code that still serves the objective,
code that serves a supporting role it did not previously have, and code that is now a
control rather than a decision tool.

### Keeps its job unchanged

These were never about bet selection. They are data integrity and price execution, and
both survive any change of strategy.

| Module | Why it still matters |
|---|---|
| `core/odds.py` | The market screen de-vigs. Comparing against raw implied probability overstates every gap, whatever the gap is for. |
| `providers/mlb.py` | Now also the source of first-five results via `first_five()`. |
| `providers/odds.py` | Extended for per-event first-five markets. |
| `providers/weather.py` | Unused by the scanner today; the input a totals model needs first. |
| `pipeline/history.py` | The season the scanner reads. |
| `pipeline/features.py`, `pipeline/pitchers.py` | Both scanner signals are built from these. Point-in-time discipline matters more, not less. |
| `pipeline/snapshots.py` | Line movement is unbackfillable regardless of strategy. |
| `model/seal.py`, CI, `paths.py` | Research integrity. Strategy-independent. |

### Demoted from decision tool to control group

The logistic model, `pipeline/predict.py`, and `pipeline/grading.py`.

The model's own `ignorance_check` already reports that ranking games by its
disagreement with the market **is not meaningful** — its predictions vary about 0.38×
as much as the market's. Under the EV objective that was a problem to solve. Under this
one it is simply not the tool, and the honest move is to stop treating it as the
project's centrepiece.

**It is not deleted, and should not be.** It is the control the scanner has to beat. A
scanner that cannot outperform a calibrated logistic regression on team records is not
finding anything a model could not, and without the model running alongside there is
nothing to make that comparison against. Keep it fitted, keep it logging, stop
presenting it as the product.

### Needs rework before it can be used

`core/staking.py`. Kelly sizing requires a probability estimate, and the scanner
deliberately does not produce one — it produces a verdict and a reason. `size_bet()`
already refuses Kelly when `calibrated=False` and falls back to flat, which is the
correct behaviour and happens to be exactly right here. **Flat staking is the honest
default for this strategy**, and no change is needed beyond saying so out loud rather
than treating the fallback as a degraded mode.

## What the new objective needs and does not have

Ordered by how much of the strategy each one blocks.

### 1. First-five totals — the market that was actually named

*"There is value on like the over under runs in the first five innings."*

The scanner routes flags to the first five and screens the first-five **moneyline**.
Nothing anywhere estimates first-five **runs**, which is the market that was named.
This is the largest gap between what was asked for and what exists.

Measurement has since narrowed what will work. Across 953 completed games the scanner's
talent bar showed **no relationship to first-five run totals** — candidates averaged
4.99 runs against 5.07 for every other game, going over 4.5 at 50.6% against 50.5%
(`docs/RESEARCH_PLAN.md`, Q2). So a totals estimate cannot be a reroute of the existing
signals; it needs its own inputs — park, weather, lineup quality, bullpen usage — and
weather is already collected and sitting unused.

### 2. Live betting — completely unbuilt

All four triggers were selected, plus *"based on performance while watching the game or
seeing statistics that just don't align with previous history"*. That requires three
things the repository has none of: a live game-state feed, a divergence detector
comparing what is happening against what the priors said, and in-play prices.

This is the single biggest build, and it is deliberately sequenced last — a divergence
detector needs established priors to diverge *from*, and those priors are what the
pre-game work produces.

### 3. Hitters

*"We had a superstar on one team and not on the other."* A superstar is as likely to be
a hitter as a pitcher, and the repository has **no batting data at all**. Both scanner
signals are pitching and run differential. A lineup gap is invisible to it.

### 4. Line shopping

Snapshots keep one book of nine. Measured earlier: best-versus-worst averages 1.85% of
implied probability and peaks at 4.14%. This is arithmetic, not prediction — it is free
money on any bet from any strategy, and the discarded quotes are unbackfillable.

### 5. KBO and NPB

Deferred by explicit instruction ("stay on MLB"). Noted so it is not lost.

## Sequence, and why this order

**Phase 1 — Finish the market that was named.** First-five totals: a runs estimate for
innings one to five, compared against the posted line. Everything needed to *research*
this is already in hand (see `docs/RESEARCH_PLAN.md`); what is missing is the estimate
and the routing.

**Phase 2 — Capture what cannot be recaptured.** Store all nine books per snapshot, and
add first-five lines to the snapshot for flagged games. Every day this waits is a day
of prices that cannot be bought back at any price. This is ahead of Phase 3 purely
because it decays.

**Phase 3 — Give the scanner eyes for hitters.** Lineup-level offensive features, on the
same point-in-time discipline. This is what turns "a superstar on one team" from a
phrase into a signal.

**Phase 4 — Live.** Game-state polling, a divergence detector against the pre-game
priors, and in-play pricing. Sequenced last because it consumes Phases 1 and 3 as
inputs: "statistics that don't align with previous history" requires the history to
have been established first.

Running underneath all four, continuously: **flags accumulate in
`evidence/mismatch_flags.jsonl` and get graded forward.** At roughly one flag a day, the
200 decided flags needed for a verdict is most of a season. Nothing in Phases 1 to 4
shortens that clock, which is the argument for starting it now rather than after the
build is finished.

## What is blocked on you

| Decision | What it unblocks | Cost |
|---|---|---|
| **Historical odds** | The market screen cannot be measured on any past game without them. Also the only way to test a first-five totals estimate against real lines rather than a fixed 4.5. | $59, one time |
| **Rotate the API key** | Nothing, but it is in a chat log. | Free |
| **Paper-trading start date** | When the forward record formally begins. Flags are already logging; this decides which day counts as day one. | Free |
