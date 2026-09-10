# Pre-registration — does `lineup_vs_primary_pitch` carry closing-line value?

**Written 2026-09-10, BEFORE any game on or after 2026-09-10 was measured
against it.** The finding that motivates it is EXPLORATORY and was produced
by looking at data that already existed. That data is therefore spent: it can
motivate this hypothesis and it can never test it. Everything below defines a
test on games this project had not yet played when the document was written.

---

## What was observed (exploratory — not evidence)

Measured over the publishable CLV pool on 2026-08-31 … 2026-09-09: decisions
whose record provenance is `live_pre_commencement`, whose closing board sits
within 90 minutes of first pitch, and whose system is FORWARD_TEST.

- 438 decisions, **29 games**, 20 registered genomes.
- Response variable: `consensus_move_bps` — the de-vigged consensus at the
  close minus the de-vigged consensus the decision was frozen against.
  Positive means the market moved toward the side we took. It is
  deliberately NOT `clv_bps`, which is biased negative by roughly half the
  hold before any line moves, and NOT `price_standing_bps`, which is
  execution quality and not information.

| feature in the deciding genome | decisions with | without | effect |
|---|---|---|---|
| **`lineup_vs_primary_pitch`** | 196 | 242 | **+15.00 bps** |
| `starter_velocity_gap` | 179 | 259 | −11.16 |
| `top_minus_bottom` | 186 | 252 | +8.35 |
| `lineup_platoon_share` | 193 | 245 | −4.14 |
| `primary_pitch_share` | 219 | 219 | −3.05 |
| `starter_groundball_share` | 265 | 173 | +0.13 |

Significance by permutation, shuffling the system label **within each game**
so the null keeps the game-level move structure and destroys only the
feature→CLV link, scored against the permuted MAXIMUM absolute effect across
all six features so the cost of testing all of them is paid rather than
ignored: **p = 0.005** for `lineup_vs_primary_pitch`. No other feature
survives (next best p = 0.82).

### Why this is not yet a result

1. **29 games.** The permutation respects game clustering, but 29 clusters is
   a small number of effective observations however many decision rows sit on
   top of them.
2. **CLV is not profit.** +15 bps is 0.15%. The hold is roughly 450 bps. This
   is evidence of *information*, not of a profitable bet, and it must never
   be presented as one.
3. **It was found by looking.** A system-level cut of the same data pointed at
   `primary_pitch_share` instead, which the stronger decision-level test says
   is nothing. That disagreement is exactly what an exploratory pass looks
   like from the inside.

---

## The hypothesis, stated before the test

> **H1.** Among FORWARD_TEST decisions in the publishable CLV pool, decisions
> made by a genome carrying `lineup_vs_primary_pitch` have a higher mean
> `consensus_move_bps` than decisions made by a genome without it.

Directional: only a positive effect counts. A negative effect of any size
is a refutation, not a discovery about the other direction.

## The test, fixed now

| | |
|---|---|
| **Window** | decisions frozen on or after **2026-09-10 00:00 UTC** |
| **Pool** | `clv.is_publishable` rows with a non-null `consensus_move_bps` |
| **Statistic** | mean(with feature) − mean(without), in bps |
| **Null** | permutation, system labels shuffled within game, 10,000 trials |
| **Stopping rule** | **≥ 60 distinct games** in the window. Not a date, not a decision count |
| **Threshold** | one-sided p < 0.05 against the permuted distribution of THIS single effect |
| **Verdict** | p < 0.05 and effect > 0 → SUPPORTED. Anything else → NOT SUPPORTED |

**Amended once, 2026-09-10, before a single row accrued and before any
result existed.** The window was first written on first pitch. A CLV
measurement row carries `decision_utc` but no commence time, so a first-pitch
window would have had to resolve every row through the game-key map — one
more join to go silently wrong, on the axis that decides what is admissible.
Decision time is on the row, is unambiguous, and is *stricter*: a decision
frozen at 23:50 on 09-09 for a game played on 09-10 is excluded, where a
first-pitch window would have admitted it. Recorded here rather than edited
away, because a spec change is only honest when it is timestamped and the
direction it moved is stated.

`docs/RESEARCH_CATALOGUE.md` T8 applies in full: if the answer is
disappointing, the answer is reported. The window does not get extended, the
threshold does not move, the feature set does not get re-cut, and a second
feature does not get promoted in its place.

## What SUPPORTED would and would not license

**Would:** a pre-registered, versioned, forward-epoch-only change to the day
ranker that weights family agreement by measured per-family CLV — proposed as
`DAY_SLIP_..._V2`, stamped on new decisions, with graded history never
re-ranked (doctrine amendment 7).

**Would not:** a win-probability field, an edge percentage, a confidence
meter, variable staking, or any customer-facing claim of an edge. Those stay
gated behind the promotion gate, which this test is not.

## The larger finding this sits inside

The same measurement says something blunter and more actionable than H1:
**16 of 22 measured systems have negative closing-line value**, several at
|t| > 3. The engine as a whole currently takes sides the market moves away
from. Worse, the systems backing the flagship STRONG pick of 2026-09-09 were
disproportionately the negative ones — five of its six families sit below
zero, two of them below −20 bps.

That is not a promotion question, it is a defect: family agreement is
currently clustering the *worst* systems and presenting the result as the
strongest evidence tier. It is tracked separately from this pre-registration
because fixing a defect needs no hypothesis test.
