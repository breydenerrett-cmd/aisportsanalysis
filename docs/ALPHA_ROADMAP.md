# Road to a proven-edge alpha

## Context

The project has a working mismatch scanner, 4 seasons of game data, and a paid
odds subscription (~99,900 credits). It has **no evidence that anything works** —
every threshold is an unvalidated guess.

Two goals, run as parallel tracks:

- **Demo track (hard requirement):** a polished, usable MLB analysis dashboard
  Jacob can open without explanation.
- **Proof track:** demonstrate an edge on data the system was not built from.

Jacob's framing is the product bar: decompose both sides into units and roles,
find where one side's strength meets the other's specific hole, and surface facts
a knowledgeable bettor isn't already thinking about — including telling him which
of his own reasons are noise.

**Decisions:** provisional 2026 backtest *plus* forward proof; interactive
dashboard; reserve unspent credits; full autonomy including the ~51K spend.

**Realism note.** The demo plus the priority detectors is achievable in one run.
The full research track is not, and I will not claim otherwise. Work is committed
and pushed continuously because this container can be reclaimed at any time.

---

## What "proven edge" means (pre-registered, falsifiable)

All five must hold:

1. **Beats the closing line** — positive CLV vs the de-vigged close.
2. **On data it was not built from.**
3. **Survives FDR correction** across the pre-registered hypothesis family.
4. **Clears an effect-size gate**, not just significance.
5. **≥300 forward selections — a minimum, not automatic proof.** Reported
   alongside ROI, calibration, win rate, drawdown, and **game/date-clustered
   bootstrap confidence intervals** (selections on the same slate are correlated;
   treating them as independent overstates certainty).

Anything short is "not proven." A failed hypothesis is a valid result.

---

## The spine: data-split discipline

| Window | Role | Looks allowed |
|---|---|---|
| 2023–2024 | **Discovery** | Unlimited; expendable |
| 2025 | **Tuning** | Budgeted, then frozen (a 2025 sub-split is already burned — `docs/TEST_SPLIT_STATUS.md`) |
| 2026-01-01 … **2026-08-27** | **Provisional confirmation** | **ONE evaluation, ever** |
| **2026-08-28 onward** | **Forward proof** | Continuous; never folded back into tuning |

Today is 2026-08-28, so the cutoff matters immediately: today's games are forward
proof, not backtest. Enforced by extending `src/model/seal.py` to cover detector
evaluations and to make a boundary violation loud.

### Point-in-time contract (season splits are not enough)

Hard rule: `feature_information_time <= recommendation_time`.

Every input carries provenance and a timestamp — odds, lineup status, probable
pitcher, bullpen workload, transactions, weather, team stats, Statcast features,
market movement. Automated leakage checks in the test suite, extending the
existing pattern that injects future results and asserts byte-identical output.

---

## Hypothesis family and correction

Testing 30+ angles guarantees false positives. Worse, the true family is
**detector × market × threshold variant**, which explodes far past 47.

- Pre-register the *complete* family, counting variants, before any evaluation.
- Benjamini-Hochberg FDR across the family.
- Effect-size gate in addition to FDR.
- **Publish every result, including losers.** Reporting only winners is how a
  30-test search becomes a lie.

---

## Detector catalogue

Each produces: `claim / value / baseline / sample / surprise / confidence /
market relevance`. No baseline, no ship.

### Tonight's priority group (end-to-end first)
1. **Implied bullpen assessment** — the full-game minus F5 price gap *is* the
   market's bullpen opinion. Disagreeing with it is directly tradeable and
   nobody computes it.
2. **Bullpen availability/workload** — who threw yesterday and the prior two
   days, innings last 7, leverage arms likely unavailable.
3. **Current lineup vs opposing starter** (Jacob's explicit ask) — pitcher vs
   each hitter actually starting, aggregated, with PA counts shown.
4. **Lineup quality concentration** — top vs bottom of order; matters most in F5
   where only the top is guaranteed to bat.
5. **Third-time-through-order penalty** — F5-specific.
6. **Pitch mix vs lineup whiff profile.**
7. **Platoon advantage** — starter's LHB/RHB splits × tonight's actual lineup.
8. **Cross-book disagreement** — one book stale against consensus.
9. **Starter velocity / pitch-mix trend** (once Statcast lands).

### Pitcher database (starters *and* relievers)
IP, ERA, WHIP, **FIP** (not xFIP — no batted-ball data until Statcast lands;
mislabelling it is forbidden), K%, BB%, K-BB%, home/away splits, vs-LHB/vs-RHB
splits, recent form, workload, rest, career history. Normalised into comparable
features, not dumped.

### Matchup history
Pitcher vs opponent team (career and current season); pitcher vs each hitter in
tonight's lineup; PA/AB, AVG/OBP/SLG/OPS or wOBA, K/BB; aggregated lineup-vs-
pitcher; handedness interaction. **Sample-gated in both directions** — "3-for-6"
gets shown *with* the debunk, and BvP is tested for whether it adds value at all.

### Remaining catalogue (tracked as planned / implemented / blocked / retired / validated)
- **Pitching:** first-inning splits; GB/FB × park × wind; days rest vs own norm;
  workload above career high; catcher-pairing framing; pitcher home/road;
  called-strike rate vs umpire zone.
- **Hitting:** team whiff by pitch type; velocity-band performance; wOBA vs
  breaking balls; BABIP vs xBA divergence (luck regression); day/night splits;
  platoon-advantaged PA share; lineup changes vs usual.
- **Bullpen:** handedness vs likely late-inning batters; rest-adjusted quality.
- **Situational:** travel distance / time zones / direction; road-trip length;
  day-after-night; getaway day; series position; rest differential; doubleheaders.
- **Environment:** park factor by handedness; temperature; altitude/humidity;
  roof state. **Blocked:** wind vector — `orientation_deg` is `None` for all 30
  parks by design (`docs/PARK_ORIENTATION.md`).
- **Umpire:** zone size / called-strike rate. Run-environment tendency needs
  source verification.

### Market structure — three corrections
- **Reverse line movement: BLOCKED.** Genuine RLM requires public bet
  percentages, which no source we have provides. Inferring it from price movement
  alone invents public sentiment. Earlier notes listed it as buildable; that was
  incoherent and is retracted.
- **Steam: renamed.** Three snapshots a day cannot detect synchronised book
  movement. What we can measure is *coarse directional movement between
  snapshots*, and it will be called that.
- **Information-timing edge: forward only.** The lineup-release inefficiency
  hypothesis needs dense timestamps around lineup posting. Historical snapshots
  cannot test it. Forward collection gets designed around that window.

---

## Track A — Demo (ships first)

**A1.** Ugly end-to-end dashboard: today's slate → static HTML → opens from
`file://`, no server, zero runtime deps. Real data immediately.

**A2.** Per-game drill-downs: starter profile; current lineup vs starter with
sample sizes; bullpen quality/workload/availability; team offense splits;
environment; market (books, movement, F5 vs full-game relationship).

**A3.** "Why this game is interesting" — ranked evidence in plain language with
supporting facts and sample sizes. Not `Team score = 74`, but *"Atlanta's
projected lineup carries six left-handed plate appearances against a starter
allowing materially higher wOBA to LHB."* **Negative evidence too**, including
the product-critical "NO PLAY — good matchup, but the price already reflects it."

**A4.** Evidence-status labels on every claim: `LIVE DATA / HISTORICAL CANDIDATE /
TUNING EVIDENCE / PROVISIONAL / FORWARD TESTING / PROVEN / UNPROVEN / BLOCKED —
INSUFFICIENT SAMPLE`. Stale and missing data shown, never hidden.

**A5.** Polish pass, launch instructions, tests green on the shipped path.

---

## Track B — Proof (continues after A is safe)

**B0.** Detector framework + seal extension + pre-registration file + FDR
machinery. Scanner's existing signals rewritten onto the framework.

**B1.** Data acquisition, **staged** — exact-cost dry run → tiny sample →
validate games/books/markets/timestamps/prices → verify credit accounting →
medium pilot → full backfill. Resumable and checkpointed by date/market/snapshot;
a crash must never restart from zero. Remaining credits monitored against budget
before each request.
- 3 seasons h2h+totals, 3 snapshots/day ≈ 36,000
- F5 for talent-bar candidates, 3 seasons ≈ 14,900
- Statcast with an explicit derived-column allowlist driven by actual detectors,
  not "119 columns"
- Lineups, umpires, transactions; 2024 ingest + 2023–24 pitcher logs

**B2.** Build the priority detectors, then expand through the catalogue.

**B3.** Discovery on 2023–24.

**B4.** Tune on 2025, apply FDR, then **freeze the whole decision policy** — not
just detectors. Eligible markets; ML/RL/total/F5 handling; which book's price
counts as available; consensus and de-vig methodology; recommendation timestamp;
minimum edge and confidence; stale-line tolerance; no-play conditions; missing
data; postponements; pitcher scratches; lineup changes; correlated signals on one
game; price floors and ceilings. Preserves existing philosophy: avoid overpriced
favourites, prefer actionable prices, strong underdogs can be valuable, −200 or
worse needs overwhelming support, and a likely winner is not a good bet.

**B5.** One-shot provisional confirmation on 2026 through 08-27. Seal
incremented. Provisional label permanent. Reported honestly either way.

**B6.** Forward proof — continuous from 2026-08-28.

---

## Autonomous-run prompt

```
ultracode

Work autonomously through docs/ALPHA_ROADMAP.md. Track A (demo) ships first and
is the hard requirement; Track B continues with all remaining capacity. When a
task finishes, pick the next yourself. If something is blocked, document why and
move to the highest-value unblocked work — do not stop to ask.

Authority: full autonomy including odds-API credits, up to the ~51K staged
backfill budget. Reserve the remainder.

Hard rules:
- No real-money betting; no bet-placement capability
- Never fabricate a value — blank is correct, guessed is corruption
- Never leak future information; point-in-time contract is enforced
- Never tune against the confirmation set, and never re-run the sealed 2026
  evaluation because the answer disappointed
- Never cherry-pick winning detectors; publish the whole family
- Never label anything proven without the required evidence

Maintain docs/OVERNIGHT_RUN.md throughout: completed, in-progress, blockers,
credits consumed, datasets acquired, tests passing/failing, commits, demo status,
next work. Commit and push at every green checkpoint.

Keep chat to a few lines. Detail goes in docs/.
```

---

## Verification

- `python3 -m unittest discover -s tests -q` green at every commit
- `python -m src.cli scan --date <today>` byte-identical before and after the
  framework refactor
- Backfill dry-run prints exact cost; `x-requests-remaining` checked before each
  request; resumable across a kill -9
- Leakage tests: inject future results, assert output unchanged
- Seal shows exactly one 2026-through-08-27 evaluation, ever
- Dashboard opens from `file://` with no server and no network
- Morning handoff: what works, where the demo is, how to launch, credits
  spent/remaining, which detectors work, what is *not* proven, next 5 tasks
