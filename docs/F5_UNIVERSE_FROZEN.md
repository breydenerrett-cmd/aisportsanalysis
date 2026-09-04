# F5 eligible universe — frozen

**Frozen 2026-09-04.** This is the denominator. It does not move to fit a
result — that is the entire point (`docs/RESEARCH_CATALOGUE.md` T8 "no
rescue by threshold change", T4 "a whole results set invalidated by a
silent join defect"). Manifest: `data/research/f5/universe_frozen.json`.
Recomputation code: `src/research/f5_universe.py`. Regression:
`tests/test_f5_universe.py` — fails the suite if the eligible set, its
counts, or its exclusion ledger ever drift from what is frozen here.

**Content hash (sha256 over the sorted eligible `game_pk` set):**

```
c67508603b14af2c494e13fadeb2a2f039f52df996ab6e12ff6164585e33cd1c
```

This hash covers identity of the set only (which games), not any
downstream classification of them. If it changes, the universe changed —
full stop, investigate before touching anything else.

## Recomputed counts (independent recomputation from source files, not
copied from any prior report)

Every number below was recomputed directly from
`data/historical/odds_first_five/f5_tminus2_primary.jsonl`,
`data/historical/first_five_results.jsonl`, and the raw
`snapshot_rule: "tminus2_v1"` rows in
`data/historical/odds_first_five/mlb_*.jsonl`, via `src/research/f5_universe.py`.
**All of them agree exactly with the measured figures in the mission brief
and `docs/F5_NORMALIZATION_REPORT.md`. No discrepancy was found.**

| quantity | value |
|---|---|
| eligible universe (all statuses) | **4,315** |
| — status `OK` | **4,298** |
| — status `PRIMARY_SNAPSHOT_UNAVAILABLE` | **17** |
| eligible by season | 2023: 1,886 / 2024: 2,429 |
| OK rows with ≥5 unique books | **100%** (min 5, median 12, all ≥5) |
| settlement join rate (eligible set) | **100.0%** (4,315 / 4,315) |
| OK rows, ties (`winner is None`, complete) | 614 |
| OK rows, void/incomplete settlement | 2 |
| **gradeable (OK ∧ decided)** | **3,682** |
| — 2023 | **1,597** |
| — 2024 | **2,085** |
| MDE (two-sided 95%, p≈0.5, n=3,682) | **1.62pp** |

`614 ties + 2 void + 3,682 decided = 4,298` = every OK row accounted for.

## Exclusion ledger

Walking every `snapshot_rule: "tminus2_v1"` row ever written to
`F5_RAW_HISTORY` (4,323 attempts total — the T-2h acquisition's own scope,
regardless of eligibility), and classifying each through
`src.research.f5_eligibility.eligibility()`:

| rule | count | disposition |
|---|---|---|
| `tuning_only_2025` | 6 | acquired in the sanity tranche while the paid acquisition was live; real, paid, valid observations of games dated in 2025 — retained immutably in `F5_RAW_HISTORY`, permanently excluded from every research universe per the owner's standing 2025-tuning-only-forever rule |
| `outside_approved_window` | 2 | pre-window 2023 tranche games (2023-03-30, 2023-05-06) — before the approved 2023-05-10 start |
| `sealed_2026` | 0 | none acquired — the acquisition's own game list never reached 2026 |
| `date_missing` | 0 | none |
| **total excluded** | **8** | |
| eligible | 4,315 | 4,323 − 8 |

`4,315 (eligible) + 8 (excluded) = 4,323 (raw attempts)` — fully accounted,
asserted by `f5_universe.build_universe()`'s own
`raw_attempts_accounted` check and covered by
`test_raw_attempts_fully_accounted_by_eligible_plus_excluded`.

## What "eligible" does and does not mean

The **eligible universe** (4,315) is every game the T-2h acquisition rule
was run against, whose date falls inside the approved window and outside
the 2025-tuning/2026-sealed years — whether or not a compliant price was
obtained. This is deliberate: `PRIMARY_SNAPSHOT_UNAVAILABLE` rows stay in
the denominator so the universe cannot later be narrowed to only the games
that happened to price (`PREREG_F5_SNAPSHOT_RULE.md` §5).

The **gradeable set** (3,682) is the strict subset actually usable by any
F5-moneyline hypothesis: `status == "OK"` (a compliant T-2h price exists)
**and** `decided` (the first five did not end level — no side to grade a
tie against). This is the number any pre-registered F5 family's sample-size
and MDE arithmetic must be computed against.

Nothing in this document evaluates any hypothesis, computes a win rate, or
looks at price direction. `decided`/`tie` are settlement facts (who won the
first five, if anyone) needed only to define gradeability.

## How to re-verify

```
python3 -m src.research.f5_universe   # recomputes and rewrites the manifest
bash scripts/test_fast.sh             # tests/test_f5_universe.py included
```

If a future acquisition or repair changes the eligible set on purpose,
re-run the module deliberately, diff the new hash against this document,
and update both together — never let the test start passing again by
silently regenerating the manifest to match new data without recording why.

## Amendment — 2026-09-04: price-payload hash (A3)

`PREREG_F5_FAMILIES.md` flaw A3: the content hash above covers identity of
the eligible set only (which `game_pk`s), not any book price. A re-fetch,
repair, or normalisation pass could rewrite every price in
`f5_tminus2_primary.jsonl` without moving that hash by a bit — which means
this family could be pre-registered against a denominator whose PRICES it
cannot prove did not move.

`src.research.f5_universe.price_payload_hash(rows)` closes that gap: a
sha256 over, per `game_pk`, `snapshot_at` and each book's `key` plus both
`away_price`/`home_price`, canonically ordered (books sorted by `key`,
`last_update` excluded so a harmless re-fetch that only refreshes provider
timestamps does not look like a moved price). It is computed over every row
of the primary view (both `OK` and `PRIMARY_SNAPSHOT_UNAVAILABLE`) and
recorded in the manifest as `price_payload_hash`.

**Price-payload hash (sha256):**

```
f2ff7b748b1b76f1702cfe2b29750f684e554ffe2c773887a04f132bf2275ec7
```

`src/research/f5_eval.py` re-verifies both this hash and the identity hash
above at run time, before any statistic is computed, and aborts (raises)
rather than proceeding on a moved universe. The original text of this
document, above this amendment, is unchanged.
