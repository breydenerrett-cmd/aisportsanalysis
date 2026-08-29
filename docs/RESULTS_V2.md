# Research Family V2 — results

**Discovery window:** 2023–2024 only. 2025 untouched. Sealed 2026 untouched.
**Pre-registration:** docs/RESEARCH_V2.md, written before any evaluation.
**Credits spent:** 0. Every hypothesis ran on data already on disk.
**Run date:** 2026-08-29.

---

## Summary

| | Hypothesis | Verdict |
|---|---|---|
| **M5** | De-vig methodology divergence | **NULL** — the choice does not matter |
| **M2** | Weekend day-game staleness | **INCONCLUSIVE** — our snapshots are too sparse to run the test |
| **M1** | Line overreaction | **NULL** — does not replicate; no directional signal either way |
| **M3** | Cross-book dispersion | **DEBUNK** — looked significant, failed falsification |
| **M4** | F5 vs full-game bullpen gap | pending free linescore ingest |

**Nothing survives so far.** One hypothesis produced a headline number
(+8.5 percentage points, p=0.006) and was killed by the falsification battery
it was pre-committed to. That is the process working, not the process failing.

---

## The data substrate

`src/research/pricepath.py` reconstructs, for every event, each book's ordered
sequence of pre-game quotes joined to the realised result.

| | |
|---|---|
| Events joined | 2,413 of 2,475 (2023), 2,412 of 2,472 (2024) — 97.5% |
| Quotes | 191,968 across both seasons |
| Books | median 18 per event |
| Snapshots | median 4–5 per event; 1,977 of 2,413 have ≥3 |
| Home win rate | 51.97% — correct for MLB, and the first sanity check |

Prices are stored American and un-de-vigged, because *which* de-vig to apply is
itself hypothesis M5 and baking one in would answer the question before asking
it.

---

## M5 — de-vig methodology: NULL

Four methods (proportional, additive, power, Shin) scored by log loss and Brier
against outcomes, on identical games at identical snapshots, n=4,486.

| Method | Log loss | Brier |
|---|---|---|
| proportional | 0.674168 | 0.240707 |
| additive | 0.674160 | 0.240708 |
| power | 0.674177 | 0.240719 |
| shin | 0.674160 | 0.240708 |

They agree to the fifth decimal place. The "best" method flips between additive
(log loss) and proportional (Brier) — the ordering is noise. Median
disagreement between methods is 0.37 percentage points, 95th percentile 1.1pp.

**Two things worth keeping:**

1. **Proportional de-vig stands.** The system's existing primitive is fine and
   every later result inherits it without an asterisk.
2. **Shin is mathematically identical to additive on two-way markets** — exact
   to thirteen decimal places, on every price tested. Not a bug; it is a known
   identity for two outcomes. Shin only earns its keep on three-way markets,
   which matters when the project expands to soccer and nothing sooner. Locked
   in as a test so a future change to either solver has to be deliberate.

---

## M2 — is the latest price the sharpest? INCONCLUSIVE

The published claim is that on weekend day games, the price 90 minutes out
forecasts better than the price at first pitch.

**Loose test** (latest quote ≥90 min out vs latest pre-pitch quote, n=2,568):
the late price wins in all four cells.

| Cell | n | Early advantage |
|---|---|---|
| weekday-day | 238 | −0.0025 |
| weekday-night | 1,542 | −0.0005 |
| weekend-day | 503 | −0.0002 |
| weekend-night | 285 | −0.0011 |

**But that is not the paper's test.** In the weekend-day cell our "early" quote
has a median gap of 954 minutes — sixteen hours, not ninety minutes. We
measured whether a yesterday price beats an hour-out price. It does not, which
surprises nobody.

**Strict test** (early quote 90–240 min out, late quote <60 min out): only 197
games in two seasons qualify, and **three** of them are weekend afternoons. The
test cannot be run.

**What this is worth:**

- The closing-line benchmark is safe as the system currently uses it. Later is
  better everywhere we can measure.
- Forward collection should sample densely inside the last three hours. Right
  now we cannot answer a question the literature says is answerable, purely
  because of when we take snapshots. That is a fixable gap and it costs
  nothing but scheduling.

---

## M1 — line overreaction: NULL

The headline hypothesis, and the one with the strongest external evidence:
consecutive price changes are supposed to be negatively autocorrelated, so
fading the last move should pay.

Measured **within each book's own price path** — never on a consensus series,
because a consensus moves when books enter or leave the sample, manufacturing
mean-reverting changes that no book ever made.

**62,183 consecutive change pairs across 4,087 events.**

| | |
|---|---|
| Lag-1 autocorrelation | **+0.013** (clustered p = 0.13) |
| Mean absolute change | 1.05 percentage points |

The sign is **positive**, not negative. Weak momentum, not reversal, and not
significant.

**Trading it, both directions:**

| Strategy | Threshold | n | ROI | Clustered p |
|---|---|---|---|---|
| Fade the move | 1pp | 19,250 | **−3.5%** | 0.13 |
| Fade the move | 2pp | 7,720 | **−4.1%** | 0.25 |
| Follow the move *(post-hoc)* | 1pp | 19,250 | **−3.3%** | 0.12 |
| Follow the move *(post-hoc)* | 2pp | 7,720 | **−2.8%** | 0.41 |

The follow-the-move rows are a **post-hoc diagnostic, not a pre-registered
hypothesis**, and are reported only because they make the conclusion sharper:
both directions lose about three percent, which is the vig. There is no
information in the direction of a move at our sampling resolution. It is not
that fading is a bad idea — it is that the move predicts nothing either way and
you pay the spread to find out.

**Honest limit.** The paper had tick-level data; we have four or five snapshots
per game. If the overreaction happens and resolves inside one of our intervals,
we cannot see it. This is "not visible at this resolution", not "not real".
Confirming it would need a much denser snapshot grid, which forward collection
could build for free over a season.

---

## M3 — cross-book dispersion: DEBUNK

**This is the one that looked real.** Recording the full sequence, because how a
candidate dies is more instructive than the fact that it did.

Per event, at one snapshot ≥6 hours out, each book's **leave-one-out** deviation
from consensus. Where a book sits far off the pack, bet against it at its own
price.

**Headline result at a 2pp deviation threshold:**

| | |
|---|---|
| n | 249 selections, 223 events, 162 dates |
| Hit rate | 60.6% |
| Consensus implied | 52.2% |
| **Effect** | **+8.49pp** |
| Clustered p | **0.0063** |
| 95% CI | [+2.34pp, +14.28pp] |
| ROI | **+18.1%** |

An 18% ROI should trigger suspicion, not celebration. Real edges in a liquid
market are one to three percent. The pre-registration recorded a **low prior**
for M3 before the run, because V1's `stale_book` detector tested a near-relative
and came back +0.03pp at p=0.97.

### The falsification battery

| Test | n | Effect | p |
|---|---|---|---|
| Baseline | 249 | +8.49pp | 0.0063 |
| Deduped to one selection per event | 223 | +9.38pp | 0.0029 |
| 2023 only | 144 | +6.14pp | 0.13 |
| 2024 only | 105 | +11.72pp | 0.016 |
| FanDuel only | 74 | +15.49pp | 0.0016 |
| BetRivers only | 29 | +12.27pp | 0.15 |
| BetMGM only | 27 | **−9.44pp** | 0.34 |
| Circa only | 22 | +1.20pp | 0.91 |
| **Excluding FanDuel** | 175 | **+5.53pp** | **0.16** |

**Dose-response — the test it fails worst:**

| Deviation band | n | Effect | p |
|---|---|---|---|
| 0.015–0.020 | 940 | **−1.56pp** | 0.35 |
| 0.020–0.025 | 209 | +8.55pp | 0.012 |
| 0.025–0.030 | 33 | +5.40pp | 0.55 |
| 0.030+ | 7 | below floor | — |

### Why it is dead

1. **No mechanism.** If bigger disagreement meant bigger error, the effect
   would grow with the deviation. Instead the band immediately below the
   threshold is *negative*, the effect spikes in one narrow slice, and then
   fades. That is the shape of noise, not of a cause.
2. **It is one book.** Remove FanDuel and the effect drops to +5.53pp at
   p=0.16 — gone. FanDuel alone is +15.49pp while BetMGM is −9.44pp. Books
   scatter across the sign, which a market-wide effect would not do.
3. **It does not replicate across seasons.** +6.14pp (p=0.13) in 2023 against
   +11.72pp in 2024 — nearly double, with the earlier season not significant.
4. **One bad price makes six selections.** With eighteen books, an extreme
   quote is part of the leave-one-out consensus every *other* book is measured
   against, so it drags them past the threshold in the opposite direction. A
   single stale line can therefore produce a handful of correlated selections
   on one game. Pinned as a test; any revival of this hypothesis has to cap
   selections per event.
5. **It is a 0.4% tail.** 249 selections out of 59,297 observations, at one of
   three thresholds, in one of five hypotheses. This is exactly where a false
   positive lives.

Promoting this on the baseline number alone would have been the single easiest
mistake available today. The pre-registered battery is the only reason it did
not happen.

---

## M4 — F5 vs full-game bullpen gap: pending

The pre-registered test needs to know who led after five innings. The results
CSV records only final scores, so a free MLB StatsAPI linescore ingest is
running (`src/research/f5_store.py`, no odds credits).

**Expect this one to be underpowered regardless.** Only 318 games across
2023–24 have F5 prices with books attached. That is the binding constraint, and
if the answer comes back "underpowered" it will be reported as underpowered
rather than as no effect.

---

## Where this leaves the project

Two families, thirteen hypotheses, zero survivors.

That is a real finding, and it agrees with the best external evidence we have:
of 1,547 simple MLB moneyline strategies tested in the literature, 0.45% were
profitable at the 1% level — the rate chance alone produces. This market is
efficient at the resolution we can observe it.

**What is genuinely worth building next, in order:**

1. **A denser forward snapshot grid.** M1 and M2 both died on sampling
   resolution rather than on evidence. Snapshots every fifteen minutes inside
   the last three hours would make both testable, and forward collection is
   free.
2. **The lineup-release window.** The one place a knowledge edge could still
   live is the gap between a lineup posting and books adjusting to it. That is
   a market-timing hypothesis, and it needs the dense grid from (1) before it
   can be asked at all.
3. **Honest decision support.** No-play verdicts, debunking a bettor's own
   reasoning, sample sizes on every claim. The system already does this and it
   is the part with demonstrated value.

**What is not worth building:** more detectors of the V1 kind. The evidence on
that question is now internal as well as external.
