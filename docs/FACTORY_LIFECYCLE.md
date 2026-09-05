# Factory strategy lifecycle

Implements `docs/FACTORY_SCALE_DESIGN.md` section 4 (retirement / mutation /
replacement) and section 5 (scheduled retest) as an explicit state machine.
Code: `src/evolab/lifecycle.py`. Tests: `tests/test_evolab_lifecycle.py`.
Dry-run classification of the 1,062 families from
`docs/FACTORY_OVERLAP_REPORT.md`: `scripts/factory_lifecycle_dryrun.py` /
`docs/FACTORY_LIFECYCLE_DRYRUN.md`.

**The unit of population accounting is the FAMILY** (§2's Jaccard>=0.8
connected component), not the individual strategy. A family, once admitted,
carries one lifecycle state; a strategy inside a family that fails on its own
is a `mutate` proposal against the family's coverage (§4), never a separate
lifecycle entry.

## Why bankroll never appears in a gate

Every function in `lifecycle.py` is pure and takes an explicit
`PromotionGate`/`RetestResult`/evidence dataclass — there is no field on any
of them for ROI, price movement, or bankroll. `promote()` cannot be made to
succeed by ROI alone because there is nothing in its input type ROI could
occupy; the refusal is structural (a `TypeError`/`LifecycleError` on
construction), not a runtime check that a future edit could weaken.

## States

| state | meaning |
|---|---|
| `CANDIDATE` | Admitted (§ Admission below); pre-registration exists but the family has not yet cleared the falsification battery under fresh evidence. |
| `FORWARD_TESTING` | Battery-cleared and replicated; now accumulating a live forward ledger. No promotion is possible from here without the forward-n floor. |
| `RETIRED` | Failed its most recent scheduled retest AND the family's unique-wager coverage is not lost (another still-passing family member covers it) — §4 `retire` row, verbatim condition. |
| `REPLACED` | A `RETIRED` family's *last* passing member is gone (a real coverage gap) and a pre-registered replacement (mutation or fresh genome) closed it under its own fresh CSCV/SPA run — §4 `replace` row. |
| `PROMOTED_GATED` | Reserved terminal state for a family that has cleared the full G-ladder (`src/factory/gates.py`). **Never reachable through this module alone** — see Promotion below. |

## Transitions and their exact evidence condition

### Admission: `admit()` → `CANDIDATE`

Inputs: `family_id`, `decision_set` (the family's union of `wager_id`s, per
`overlap.py`), a `PreRegistration` record (mechanism prose, registered
before any battery run — mirrors `src/research/funnel.register_family`), and
the set of currently `RETIRED` families' decision sets.

Refuses (`LifecycleError`, no state created) when:

- `PreRegistration` is missing or its `mechanism` is empty (a hypothesis with
  no stated reason for misprice is a dredge, not a candidate — same bar as
  `funnel.validate_spec`), OR
- `jaccard(decision_set, retired_family.decision_set) >= overlap.FAMILY_THRESHOLD`
  for **any** currently `RETIRED` family. This is the correlation-with-
  existing-family rule the task requires: a near-duplicate of something
  already killed cannot re-enter as if it were new evidence. The same
  `FAMILY_THRESHOLD = 0.8` constant from `overlap.py` is imported, not
  redefined, so the bar for "this is the same family" cannot silently drift
  between the overlap report and the admission gate.

### `CANDIDATE` → `FORWARD_TESTING`: `begin_forward_testing()`

Requires, as one `BatteryEvidence` record:

- `pre_registered=True` (the admission-time `PreRegistration` still applies —
  passed through, not re-derived),
- `replication_passed=True` (screen + replicate, `funnel.py`'s two-season
  discipline — a family whose effect does not survive the second season is
  not forward-tested),
- `battery_passed=True` (the placebo/ceiling/CSCV/SPA battery — `ceiling.py`
  `kill_criterion`, `spa.py` `cross_check` must have run and not disagreed).

All three, or the transition refuses with the specific missing flag(s) named.

### `FORWARD_TESTING` → `PROMOTED_GATED`: `promote()`

Structurally requires a `PromotionGate` record where every one of these
named boolean fields is `True`, AND `forward_ledger_n >= min_forward_n`:

`pre_registered`, `replication_passed`, `battery_passed`, `cscv_passed`,
`spa_passed`, `ceiling_cleared`.

`promote()` computes `gate.all_evidence_true` by conjunction over exactly
those named fields (no wildcard, no "if most pass") and refuses — returning
every failing field name, never a bare `False` — if any is missing, if
`forward_ledger_n` is below the floor, or if the entry is not currently in
`FORWARD_TESTING`. There is no path through this function that inspects ROI,
price, or bankroll at all — see "Why bankroll never appears in a gate".
`min_forward_n` defaults to `sweep.DEFAULT_MIN_SELECTIONS` (30) — the same
floor the sweep machinery already uses to call a sample "not under-powered",
reused rather than re-derived.

### `FORWARD_TESTING`/`CANDIDATE` → `RETIRED`: `retire()`

Both of these must hold (§4's `retire` row, verbatim):

1. `retest_result.passed is False` — the family's most recent **scheduled**
   retest (§ Scheduled retest below) failed CSCV/SPA, not merely a bad
   recent block with a still-passing verdict (noisy is not the same as
   falsified — the caller passes the actual gate verdict, this function does
   not compute one).
2. `family_still_has_passing_member=True` — retiring this family loses no
   unique wager coverage because another currently-passing family already
   covers the same decision set. Without this, `retire()` refuses (a
   family with no still-passing coverage is a `replace` case, not a plain
   retirement — see next).

### `RETIRED` → `REPLACED`: `replace()`

Requires `RETIRED` as the current state, `lost_last_passing_member=True` (a
genuine coverage gap — the flag is separate from `retire()`'s
`family_still_has_passing_member` so the two can never be conflated), and a
`ReplacementEvidence` record carrying a **fresh, pre-registered** battery
result (`pre_registered=True` recorded *before* the replacement's own
CSCV/SPA run per `funnel.py`'s direction-before-results discipline,
`battery_passed=True`) plus a reference to the retirement record it closes.
Refuses without all three.

## Scheduled retest cadence

`retest_due(games_since_last_retest, block_width=sweep.DEFAULT_N_BLOCKS)`
mirrors §5: a retest is due once enough new game-days have accumulated to
form one full new block of the existing block structure — wall-clock time
never enters the calculation. A retest itself is an ordinary `run_sweep`
call outside this module (unchanged, per design); `lifecycle.py` only
decides whether one is due and how its `RetestResult` feeds `retire()`
above. A retest is never a separate promotion path — its only two possible
effects are "stay as is" (passed) or feed `retire()` (failed); it can never
directly promote.

A **failed retest never overwrites** the prior verdict: each retest appends
its own audit-trail row referencing the prior one by `evidence_ref`, so the
sequence of verdicts for a family remains fully reconstructable.

## Audit-trail record format

Every transition appends one JSON line (append-only, never rewritten) via
`lifecycle.append_audit(path, record)`:

```json
{"family_id": "...", "from_state": "CANDIDATE", "to_state": "FORWARD_TESTING",
 "trigger": "begin_forward_testing", "evidence_ref": "<sha256 of the evidence dict>",
 "timestamp": "2026-09-05T00:00:00+00:00"}
```

`evidence_ref` is a `sha256` over the exact evidence dataclass converted to a
canonical (`sort_keys`) dict — the same discipline as `factory/gates.py`'s
`inputs_hash` — so a later dispute over "what evidence justified this
transition" is answerable without re-deriving anything. The log is the only
I/O this module performs; every state-machine function itself is pure (no
clock, no disk, no network) and takes `now` as an explicit optional
parameter for the timestamp, defaulting to `datetime.now(timezone.utc)`.

## Dry-run classification of the 1,062 existing families

`scripts/factory_lifecycle_dryrun.py` classifies each of the 1,062 families
from the one persisted sweep artifact
(`data/research/evolab/sweep-0014914df78666b9-REAL.json`) using **only**
fields already written to that artifact — no new evaluation, no outcome
read, no re-run of `sweep_world`/`cscv`/`spa`. The artifact's own verdict on
this population is a population-level failure, read directly off three
already-persisted fields:

- `ceiling.generators_cleared` is `[]` — no generator's placebo threshold was
  cleared by the real maximum (the single best strategy in the whole
  8,811-strategy population, hence an upper bound on every family's best
  member).
- `spa_cross_check.status` is `"DISAGREE"` — the module's own words: "Find
  the bug before quoting either number." Treating a disagreement as a pass
  would be quoting a number the artifact itself says not to trust; the
  conservative, honest reading is failure.
- `cscv.pbo` is 0.61 (`> 0.5`) — probability of backtest overfitting worse
  than a coin flip.

Since none of these are per-family and there is no per-family fresh
CSCV/SPA retest on record for any of the 1,062 families, no family has
persisted evidence that would let `admit()`/`begin_forward_testing()`
succeed for it (no `battery_passed=True` exists for anyone). The dry-run
therefore does not call `admit()` at all — every family is `RETIRED`
directly from the population-level battery verdict already on record,
because that verdict is evidence the whole search's real-world result
never beat its own placebo ceiling. `CANDIDATE` count is reported as 0 with
this fact stated plainly, not left implicit. See
`docs/FACTORY_LIFECYCLE_DRYRUN.md` for the generated counts and the exact
fields read.

This is a **read of one already-existing verdict**, not a new judgement:
the sweep artifact was always a population-level failure (this is why
`docs/FACTORY_OVERLAP_REPORT.md` itself is framed as counts-only, no
promotion claim). The dry-run makes that failure's lifecycle consequence
explicit and auditable rather than leaving it as a fact only readable by
opening the raw JSON.
