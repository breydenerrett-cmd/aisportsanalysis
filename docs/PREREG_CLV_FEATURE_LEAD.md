# Pre-registration — does `lineup_vs_primary_pitch` carry closing-line value?

**Written 2026-09-10, BEFORE any game on or after 2026-09-10 was measured
against it.** The finding that motivates it is EXPLORATORY and was produced
by looking at data that already existed. That data is therefore spent: it can
motivate this hypothesis and it can never test it. Everything below defines a
test on games this project had not yet played when the document was written.

---

> ## CORRECTION, 2026-09-10 — read this before anything below
>
> **The "+15.00 bps effect" reported in the first version of this document
> was not an effect size. The real excess is about +3 bps.**
>
> The statistic was `mean(all with) − mean(all without)`, pooled across
> games. That weights each game's mean by `k_g` in one arm and `n_g − k_g`
> in the other, so it has a **non-zero expectation under random labels**.
> Here **18 of 30 games are single-arm** (13 all-with, 5 all-without): the
> within-game shuffle is a no-op in them, and their contribution is frozen
> identically in every trial.
>
> Measured on the real pool, the permutation null for that statistic is
> **centred at +11.89 bps (sd 1.13), not at zero.** Observed +14.85. Excess
> over its own null: **+2.96 bps.**
>
> The p-value was never wrong — it is a valid test of "labels are
> exchangeable within game," and it survives a placebo split (p = 0.94) and
> leave-one-game-out in 29 of 30 cases. What was wrong was quoting the
> observed statistic **as if measured from zero**.
>
> Two further problems found in the same review, both real:
>
> * **The arms are not exchangeable for reasons that are not information.**
>   Within-game, decisions carrying the feature freeze a median of **45
>   minutes earlier** (20:40Z vs 21:25Z) and sit at different price
>   standing. The response variable is how far the market moved between
>   freeze and close, so an arm that freezes earlier gets a mechanically
>   larger move. The permutation attributes all of that to the feature.
> * **The cleanest available contrast says zero.** Where both arms took the
>   *identical* bet (same event, market, side, line — 12 such selections),
>   the difference is **−0.67 bps, median 0.00, positive in 0 of 12**.
>
> **The statistic has been changed** (before any forward data accrued —
> the window is still PENDING at 0 of 60 games) to the mean of **within-game
> contrasts**, which is centred at zero by construction because each game's
> own mean cancels. It costs sample: only games holding both arms can
> contribute, which is the honest position, since a game where every
> decision carries the feature contains no information about it.
>
> Also corrected below: the pool is **3 dates, not 10**, and **100% h2h
> moneyline**, neither of which the first version said.

## What was observed (exploratory — not evidence)

Measured over the publishable CLV pool. **Three dates only — 2026-09-07,
-08 and -09** (the first version said 2026-08-31 … 2026-09-09, which is the
range of the raw ledger, not of the rows that survive the publishable
filter), with 382 of 452 rows on a single day, and **100% h2h moneyline**.
Decisions
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
| **Statistic** | mean of **within-game contrasts** — per game holding both arms, mean(with) − mean(without), then averaged over games. Centred at zero under the null by construction. See the correction at the top: the pooled version this replaced had a null centred at +11.89 bps. |
| **Reported effect** | the **excess over the permuted null mean**, never the raw statistic |
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

**RETRACTED, 2026-09-10.** The first version of this section said *"16 of 22
measured systems have negative closing-line value, several at |t| > 3. The
engine as a whole currently takes sides the market moves away from."* That
is not supported, for three separate reasons:

* **It names the wrong quantity.** Those figures are `consensus_move_bps`,
  not `clv_bps`. This module exists to keep them apart: `clv_bps` is
  *structurally* negative by roughly half the hold before any line moves,
  and 27 of 28 systems are negative on it by construction. Calling
  `consensus_move_bps` "closing-line value" is the exact conflation the
  measurement was built to prevent.
* **It is one observation restated 28 times.** All 28 systems draw from the
  same **31 games and 39 distinct selections**. The pooled mean is −4.05 bps
  over 506 decisions, but the game-level mean of means is **−3.01 over 31
  games with a game-clustered 95% CI of [−16.2, +10.2] — which includes
  zero.**
* **The |t| > 3 figures used `_stderr_naive`,** which `src/report/clv.py`
  itself labels a LOWER BOUND on the true uncertainty. One system showed
  t = −8.03 on two decisions in one game.

**The honest statement:** *across 31 games the publishable pool's vig-neutral
consensus move averages about −3 bps, with a game-clustered 95% CI of roughly
[−16, +10]. It cannot be distinguished from zero. The per-system split is 18
negative and 10 positive, but those are 28 overlapping views of the same 31
games, not 28 independent tests.*

**Also retracted:** *"correlation(confirm rate, mean CLV) = +0.35 over 21
genomes."* It reproduces at +0.341 under a ≥10-checks-and-≥10-rows filter and
flips to **−0.047 at n = 28** under a slightly looser one. A sign change from
a threshold change is what an n≈21 noise correlation does. It was also
offered as evidence that confirm rate is a *forward* selector, which it
cannot be: confirm rate and mean move are computed over **the same games**,
so the relationship is contemporaneous. The forward version has no history at
all yet — only reviews written from 2026-09-10 onward carry resolved checks.

What survives, and is still worth acting on: the systems backing the flagship
STRONG pick of 2026-09-09 skew toward the negative end of a distribution
centred near zero. That is a reason to look at whether family agreement
clusters correlated systems, which is a design question about the ranker —
not evidence that the engine is systematically anti-predictive.
