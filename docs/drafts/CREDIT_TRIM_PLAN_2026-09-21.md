# Credit trim plan, 2026-09-21

**Status: proposal only. No code changed by this document.** Read-only
analysis of `data/processed/credit_log.jsonl` plus the existing config in
`src/capture/budget.py`, `config/capture_families.json` and
`scripts/capture_slot.sh`. Every number below is computed from the log as
it stood at the last row read, `2026-09-21T18:20:11Z`.

## 1. Where the balance actually is

- **Last logged balance: 9,283 credits**, at 2026-09-21T18:20:11Z
  (`credit_log.jsonl`, last row).
- **Floor: 5,000 credits** (`CREDIT_FLOOR`, `src/capture/budget.py:93`) —
  `can_spend()` refuses any request that would take the balance to or below
  this.
- **Usable runway above the floor today: 9,283 − 5,000 = 4,283 credits.**
- **Reset:** the owner's context states ~10-01 is assumed. `budget.py`'s
  own `quota_reset_utc()` independently assumes the same thing (first of
  next UTC month) and labels it explicitly as an *assumption*, not a
  verified billing date (`RESET_CYCLE_DAYS` docstring). From 09-21 to
  10-01 is **10 calendar days**.
- **Target burn rate to survive to reset without hitting the floor:
  4,283 ÷ 10 ≈ 428 credits/day.**

## 2. Spend per caller/family per day, 09-19 to 09-21

Computed from consecutive `credits_remaining` deltas in `credit_log.jsonl`
(the log's `credits_used_last` field is populated only for `live_odds` and
probe rows; every other family's real cost is the balance drop between
consecutive rows, attributed to the row that observed it — same method
`spent_today()` in `src/capture/budget.py` uses).

| Family | 09-19 | 09-20 | 09-21 (partial, through 18:20Z) |
|---|---:|---:|---:|
| `dense.run` (MLB "featured", 3 markets/event) | 1,218 | 1,168 | 155 |
| `nfl_capture.run` | 153 | 111 | **216** |
| `derivative_markets.run` | 96 | 48 | 15 |
| `prop_listing.run` | 70 | 67 | 99 |
| `dense.close_capture` | 18 | 21 | — |
| `batter_props.run` | 16 | 9 | — |
| `prop_prices.run` | 4 | 2 | 6 |
| `tennis_capture.run` | — | — | **25** (new) |
| `budget.probe_family:tennis_h2h` | — | — | 15 (one-time probe) |
| **Day total** | **1,575** | **1,426** | **531 so far** |

**Current daily rate: roughly 1,400-1,600 credits/day** on a full day
(09-19, 09-20). 09-21 is already at 531 by 18:20Z and still has the
evening slate ahead of it, so it is on pace to land in the same range or
higher — `nfl_capture.run` alone has already spent more today (216) than
on either of the prior two full days, because the capture-commit bug fix
deployed at ~04:03Z today (`docs/PREREG_NFL_CARD_V2.md`, "Known limits")
let daytime NFL captures start committing again, and `tennis_capture.run`
is a brand-new cost that did not exist before today.

**`dense.run` is the dominant cost — about 75-82% of daily spend on 09-19
and 09-20.** It is the MLB "featured" family (3 credits/event, measured,
`config/capture_families.json`), called on the forward-capture chain's
~13-minute cadence.

## 3. The arithmetic: today's rate does not fit the runway

- Runway: **4,283 credits over 10 days ≈ 428/day.**
- Current rate: **~1,400-1,600/day** (and rising, per §2).
- At the current rate, the floor is reached in **4,283 ÷ 1,500 ≈ 2.9
  days** — around **2026-09-24**, roughly a week before the 10-01 reset,
  not accounting for UFC or any NFL/tennis growth.
- **The gap to close: cut daily spend by roughly 70%**, from ~1,500/day to
  ~428/day or less, while still leaving room for UFC (~20-30 credits/week
  per `docs/plans/2026-09-21_ALL_SPORTS_UFC_AND_PAID_PLAN.md` §5.2) and
  ongoing NFL capture.

## 4. What the owner's thesis changes about what's needed

2026-09-21 thesis: "we're just going to pick the average odds... the value
does not matter if the confidence is not high." That means LINEHOUND no
longer needs to catch a single book's mispriced line before it corrects —
the entire reason `dense.run` chases a ~13-minute cadence
(`scripts/capture_slot.sh:59-62`, `CHAIN_MIN_SPACING_MINUTES=13`,
comment: "a dispatch takes tens of seconds to become a running job... every
gap must stay under 15 minutes"). What the thesis actually requires is
**enough captures for a fresh, stable multi-book average close to lock**,
not near-continuous re-pricing through the whole pre-game window. That is
a materially cheaper requirement, and it is the lever with by far the
biggest leverage on the numbers above, because `dense.run` is 75-82% of
spend and its cost scales directly with how often it's called.

## 5. Proposed changes, named by file and constant

None of these are applied by this document. Each names the exact
config/code location a human (or a follow-up change) would edit.

### 5.1 Slow the forward-capture chain (`scripts/capture_slot.sh:62-63`)

```
CHAIN_MIN_SPACING_MINUTES=13   # game-day cadence
CHAIN_QUIET_SPACING_MINUTES=60 # quiet-hours cadence
```

**Proposed: raise both.** `CHAIN_MIN_SPACING_MINUTES` 13 → **40**;
`CHAIN_QUIET_SPACING_MINUTES` 60 → **120**. This one change scales down
every family that rides the same chain slot — `dense.run`,
`dense.close_capture`, `prop_listing.run`, `prop_prices.run`,
`batter_props.run`, `derivative_markets.run`, and `nfl_capture.run`, which
all fire once per slot. Going from a 13-minute floor to a 40-minute floor
cuts the number of slots on a game day from roughly one every 13 minutes
to one every 40 — **about a 3x reduction in call volume**, and, because
`dense.run`'s cost is roughly linear in call count (3 credits × markets
per event, not per elapsed time), roughly a 3x reduction in its spend too:
**~1,200/day → ~400/day** on 09-19/09-20's own dense.run figures.
`CHAIN_GATE_MAX_MINUTES=30` (line 66) should move with it — it exists so a
waiting rival doesn't sit stuck longer than one cadence interval; leaving
it at 30 while the cadence is 40 would make the gate expire mid-slot, so
this should track `CHAIN_MIN_SPACING_MINUTES` (e.g. set to the same value
or slightly above).

**Caveat, stated plainly:** the code comment on line 59-60 warns that 13
(not 15) exists so "every gap must stay under 15 minutes" for an
hour-boundary dense-window widening rule elsewhere in the script to not
miss a hour. Widening the cadence to 40 minutes needs that hour-boundary
logic checked, not just the two constants — flagged here as a real
follow-up, not assumed safe.

### 5.2 Suspend the lowest-value-per-credit families
(`config/capture_families.json`)

The repo already has a **measured drop order** for exactly this situation
(`src/capture/budget.py` `DROP_ORDER`, `docs/PREREG_MLB_VALUE_SHADOW_V1.md`
is unaffected — it reads no odds-API credit at all, confirmed by its own
"no odds-API credit is spent" rule). Per that existing order (lowest rank
= drop first), consistent with the owner's average-odds thesis, which no
longer needs the highest-breadth, most price-shopping-oriented families:

- **`alternates`** (rank 4, "least unique... the same book relists the
  same ladder tomorrow") — the alternate-line ladder exists to shop for a
  better number across many lines; the average-odds thesis has no use for
  it. Zero cost on 09-19/09-20/09-21 in the sampled window (already near
  idle), but worth confirming it is off, not just quiet.
- **`pitcher_props`**, **`f5_trio`**, **`batter_props_extra`** (ranks 5-7)
  — all zero-to-low spend in the 09-19..09-21 window already, but should
  be explicitly suspended (not just quiet by coincidence) for the
  remainder of this cycle, since they sit below the non-droppable
  `batter_props_floor` in value and the owner's stated focus (total bases,
  hits, run lines) does not need them.
- **`batter_props_floor` stays on** — it is deliberately non-droppable
  (`NON_DROPPABLE_FAMILY`, `src/capture/budget.py`), 2 games/night,
  designed to survive exactly this kind of squeeze. Do not touch it.

None of these four moved meaningful credits in the sampled window, so this
step's savings are mostly precautionary (stopping any of them from waking
up mid-squeeze), not the main lever — §5.1 and §5.3 are.

### 5.3 Pause `tennis_capture.run` until the results feed actually works

`docs/plans/2026-09-21_ALL_SPORTS_UFC_AND_PAID_PLAN.md` §3.3: BALLDONTLIE
is returning a 401 on ATP/WTA results, and the account's real plan tier is
unverified. Capturing tennis odds (25 credits so far today, brand new as
of 09-21, cadence not yet steady-state) with **no path to grade a single
pick** is pure spend with zero evidence value while that's true. **Proposed:
stop `tennis_capture.run` calls (whatever gates that call in the forward
chain) until the BALLDONTLIE auth/tier question is resolved**, then resume.
This is a pause, not a cut to a smaller cadence, because an ungradable
capture is worth exactly the same near-zero amount at any cadence.

### 5.4 Explicit reserve for UFC and NFL

- **UFC:** `docs/plans/2026-09-21_ALL_SPORTS_UFC_AND_PAID_PLAN.md` §5.2
  estimates ~20-30 credits for a full fight week (The Odds API bills
  per-pull, not per-fight, for `mma_mixed_martial_arts`). That is small
  enough to absorb inside the trimmed daily budget without a separate
  carve-out — call it **~5 credits/day amortized**.
- **NFL:** keep `nfl_capture.run` on the same chain as §5.1 (it already
  rides the same slot cadence), so it shrinks with the same 13→40 minute
  change. Its 09-21 spike (216, already above either prior full day) is
  the capture-commit bug fix working as intended (daytime captures no
  longer silently discarded) — that is a real, wanted increase in
  coverage, not a bug to reverse, so the room for it should come from
  §5.1's cadence cut and §5.3's tennis pause, not from cutting NFL itself.

## 6. Projected daily spend under the combined change

Using 09-19/09-20 as the baseline (before today's NFL and tennis changes,
which are new cost, not yet steady-state):

| Family | Baseline/day | After §5.1 (~1/3 the calls) |
|---|---:|---:|
| `dense.run` | ~1,190 | ~400 |
| `nfl_capture.run` | ~130 | ~45 (plus real growth from the bug fix — unmeasured yet) |
| `derivative_markets.run` | ~70 | ~25 |
| `prop_listing.run` | ~70 | ~25 |
| `dense.close_capture` | ~20 | ~20 (end-of-window pass, not chain-cadence-scaled) |
| `batter_props.run` | ~13 | ~5 |
| `prop_prices.run` | ~3 | ~3 |
| `tennis_capture.run` | 0 (paused, §5.3) | 0 |
| UFC reserve | — | ~5 |
| **Total** | **~1,496** | **~528** |

**~528/day is still above the ~428/day target**, so §5.1's cadence change
alone is not quite enough — it gets within about 100 credits/day, and the
remaining gap should be closed by watching the first 2-3 days at the new
cadence against the real `nfl_capture.run` growth (unmeasured, because
daytime NFL capture only started working again today) before deciding
whether the spacing needs to go past 40 minutes, or `nfl_capture.run`
needs its own, slower schedule separate from the MLB-driven chain. **This
plan gets most of the way there and names where the remaining slack has to
come from; it does not claim the arithmetic closes to the exact dollar.**

## 7. What this plan does not do

- It does not change `DAILY_ENVELOPE` (`src/capture/budget.py:86`, derived
  as 100,000 × 0.27 ÷ 30 ≈ 900/day) — that constant governs a different
  thing (the approved share of the *monthly* allotment for live capture,
  per `docs/RESOURCE_POLICY.md`) and is not the binding constraint here;
  the binding constraint is the **10-day runway to the assumed reset**,
  which is tighter than the monthly envelope by construction this close to
  a reset.
- It does not touch `CREDIT_FLOOR` (5,000) — that is a safety floor, not a
  lever to spend into.
- It does not change any code, config file, or workflow file. Every
  constant named above (`CHAIN_MIN_SPACING_MINUTES`,
  `CHAIN_QUIET_SPACING_MINUTES`, `CHAIN_GATE_MAX_MINUTES`, the four
  suspended families in `config/capture_families.json`, the
  `tennis_capture.run` pause) is a proposal for the owner or a follow-up
  change to apply, not something this document applied.
