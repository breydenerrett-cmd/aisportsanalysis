# Alpha registry — migration reconciliation report

Migration script: `scripts/alpha_registry_migrate.py`. Ledger:
`data/research/alpha_registry.jsonl`. Design: `docs/ALPHA_REGISTRY_DESIGN.md`.
Every number cited below is transcribed by hand from the source document
named next to it; where a number could not be transcribed honestly, this
report says so instead of inventing one. `git check-ignore -v
data/research/alpha_registry.jsonl` returns nothing (exit 1) — the file is
not git-ignored, so no `.gitignore` negation block was needed.

## Row counts produced

```
42 hypothesis/sweep/audit rows = 40 hypothesis rows + 1 sweep row + 1 audit row
  V1: 21   V2: 5   V4: 6   V5: 3   V3: 5   = 40
  EVOLAB_PHASE2B: 1 sweep (candidates_evaluated = 8811)
  ELO_BENCHMARK: 1 audit
38 verdict rows
  V1: 21   V2: 5   V4: 6   V5: 3   V3: 1   EVOLAB_PHASE2B: 1   ELO_BENCHMARK: 1
```

This matches the acceptance target's arithmetic (21+5+6+3+5=40, +1 sweep,
+1 audit) with one substitution the task anticipated: the task's target
formula uses V3=4 (the design note's stale count); the actual admitted-class
count on disk today is 5 (four at the 2026-08-31 freeze plus the
2026-09-02 umpire-class amendment), so this migration seeds 5 V3 rows, not
4, and the total is 40 rather than 39. This is not a bug in the migration;
it is the design note (dated the same day as the amendment) not yet
reflecting a change made later that same day. See "V3: the design note is
stale" below.

Migration idempotence verified: running `python3 scripts/alpha_registry_migrate.py
migrate` a second time against the same file appends 0 rows (`tests/test_alpha_registry.py
TestMigration.test_migration_is_idempotent`, and manually: first run
"appended: 42 hypotheses/sweeps/audits, 38 verdicts", second run
"appended: 0 ... skipped: 42 ... skipped: 38").

## Disagreements with the design note (`docs/ALPHA_REGISTRY_DESIGN.md`)

### V3: the design note is stale against its own same-day amendment

The design note's Decision 2 migration-seed list and its "Acceptance for the
implementation packet" both say V3 contributes **4 rows**, "two are below
floor → status registered, no verdict" (implying two of four were read).
Reading the actual source documents instead:

- `docs/RESEARCH_V3_TIMING.md`'s freeze record names **4** admitted classes
  (`lineup_posted`, `starter_scratch`, `hitter_scratch`, `il_roster_move`).
- `docs/RESEARCH_V3_UMPIRE_CLASS.md`, dated the same day as the design note
  (2026-09-02), adds a **5th** admitted class (`umpire_crew_revealed`) "on
  the same terms as the four admitted at freeze" and states explicitly:
  "The family's BH-FDR denominator becomes 5 admitted classes, effective
  this amendment date... forward."
- The **ADDENDUM** inside `docs/RESEARCH_V3_TIMING.md` itself (also dated
  2026-09-02) reports the actual floor status of all four original classes:
  only **`transaction_first_seen` (56/30 measurable) has been read.**
  `lineup_posted` is at 29/30 (one event short), `hitter_scratch` at 3/30,
  `starter_scratch` at 0/30 — **three below floor, not two.**

This migration follows the source documents rather than the design note:
**5 hypothesis rows for V3** (the fifth carrying
`registered_via_amendment: "docs/RESEARCH_V3_UMPIRE_CLASS.md"`), and **1
verdict row** (`V3:transaction_first_seen`), not two. The task instructed
recording this rather than silently forcing the design note's number, so it
is recorded here rather than resolved.

### The sweep's `alpha_declared` is a different unit than every hypothesis row's

Every hypothesis row's `alpha_declared` is a BH-FDR q (0.10, uniformly,
across V1/V2/V3/V4/V5). The Phase 2B sweep's `alpha_declared` is **95.0**
— `threshold_pct` from `data/research/evolab/sweep-0014914df78666b9-REAL.json`,
a placebo-ceiling percentile, not a q-value. The design note's phrase
"alpha_declared (family q or sweep threshold)" anticipates exactly this, so
it is not a violation of Decision 2, but it is flagged here because a naive
reader comparing `alpha_declared` values across rows would otherwise compare
two different units (a false-discovery rate vs. a percentile ceiling)
without warning.

## Doc counts this migration disagrees with (or declines to reproduce)

`docs/RESEARCH_CATALOGUE.md`'s own "Counting the families" section already
documents the 13/25/27/35 inconsistency (V2 double-counted in the "13" and
"27" roll-ups; 25 = detector/spec level; 35 = registered-hypothesis level).
This migration adopts the catalogue's own **35** (21+5+6+3) as the
registered-hypothesis-level canonical count for V1/V2/V4/V5, per the design
note's Decision 1, and adds V3's 5 admitted classes on top (40 total) plus
the Phase 2B sweep and Elo audit as separate, non-hypothesis kinds. It does
not reproduce "13", "25", or "27" as a hypothesis count anywhere in the
ledger. One count in the catalogue needed a closer look during migration:

- **V1's published verdict table (`docs/RESULTS_STAGE2.md`) reports at the
  11-DETECTOR level, not the 21 registered detector×market-hypothesis
  level** that `evidence/hypothesis_family.json` actually froze. For a
  detector registered against two or three markets (e.g. `bullpen_exposure`
  at `h2h` and `h2h_1st_5_innings`; `pitch_mix_mismatch` at three markets),
  the published `n`/effect/CI/p appear to be POOLED across that detector's
  market variants — the doc gives one row per detector, never a market
  breakdown. This migration attaches the **same detector-level number** to
  every one of that detector's registered market-variant hypothesis rows
  (e.g. `V1:bullpen_exposure:h2h` and `V1:bullpen_exposure:h2h_1st_5_innings`
  both carry n=1508/effect=+1.65/p=0.18), rather than fabricating a
  market-specific split that does not exist in the source. **This means
  `alpha_registry.jsonl` currently has 21 V1 verdict rows built from only
  11 distinct published statistics** — a real granularity mismatch between
  the registration file and the published result, not something this
  migration could resolve without inventing numbers, so it is recorded here
  instead.

## Every null field, and why

### Hypothesis/sweep/audit rows

| field | rows | why |
|---|---|---|
| `direction` | all 21 V1 rows, V2:M4, V2:M5, EVOLAB:phase2b (24 total) | V1: `evidence/hypothesis_family.json` has no direction field for any of its 21 entries; not reverse-engineered from later results docs (would leak post-hoc knowledge into a field that is supposed to be pre-registered). V2 M4/M5: both are explicitly two-sided/methodological in `docs/RESEARCH_V2.md` — M4 "look for systematic bias (over- OR under-weight)", M5 a calibration comparison — neither pre-commits a sign. The sweep: direction is a per-genome concept inside Evolab (`src/evolab/registry.py`), not a sweep-level one. |
| `market` | all 5 V3 rows | Neither `docs/RESEARCH_V3_TIMING.md` nor `docs/RESEARCH_V3_UMPIRE_CLASS.md` names a specific betting market (h2h/totals) for the price-reaction measurement; both speak generically of "books", "quotes", "de-vigged implied probability". Guessing h2h by analogy to how other modules hardcode a market key (`src/research/pricepath.py`) would not be a value verbatim from a V3 document, so it is left null rather than guessed. |
| `code_hash` | V2's 5 rows, all 5 V3 rows, the Elo audit (11 total) | No code commit, module fingerprint, or hash is recorded anywhere in `docs/RESEARCH_V2.md`, `docs/RESULTS_V2.md`, either V3 document, or `docs/BENCHMARK_ELO.md`. (V1 has one in `evidence/stage2_2026-08-28/code_commit.txt`; V4/V5 have the shared battery-2.0.0 fingerprint `ac74c7a7f715f9ec`; the Phase 2B sweep has one in its own provenance table.) |
| `spec_id` | EVOLAB:phase2b, AUDIT:elo_benchmark | Neither is a family of multiple specs; `spec_id` is a secondary grouping key for detector/spec-level counting within a family (D1), which does not apply to a single sweep or a single audit. |
| `alpha_declared` | AUDIT:elo_benchmark | An audit is not a hypothesis test against a declared false-discovery rate; `docs/BENCHMARK_ELO.md` declares no q or threshold, only a frozen scoring procedure. |

### Verdict rows

| field | rows | why |
|---|---|---|
| `battery_version` | all 21 V1 rows, all 5 V2 rows, V3:transaction_first_seen, AUDIT:elo_benchmark (28 total) | None of `docs/RESULTS_STAGE2.md`, `docs/RESEARCH_V2.md`/`docs/RESULTS_V2.md`, or `docs/BENCHMARK_ELO.md` cites a `RULES_VERSION`/battery fingerprint (the shared falsification battery, `src/research/battery.py`, postdates V1 and V2). V3's read used a bespoke bootstrap procedure (`src/research/timingtest.py`) that the family's own document explicitly distinguishes from the shared battery ("V3 itself makes no [selection-shaped] claim" that would invoke it). |
| `ci` | V1's 4 side-less/below-floor rows (`implied_bullpen_disagreement`×2, `lineup_vs_starter`×2, `park_and_weather`×2, `thin_matchup_history`×1 — 7 rows, listed fully below), V2:M1, V2:M2, V2:M5, all 6 V4 rows, all 3 V5 rows, EVOLAB:phase2b, AUDIT:elo_benchmark | No CI is reported in the source doc for any of these: V1's side-less/below-floor detectors never produced a statistic to bound; V2's M1 autocorrelation coefficient and M5's log-loss/Brier table are reported with a p or a metric but no CI; V4/V5's `results_v*_run.json` files carry `n`/`effect`/`p` fields but no CI field at any stage; the Phase 2B sweep's fitness value (0.004882…) is reported with a percentile rank, not a CI; the Elo benchmark reports a p but no CI on the log-loss differential. |
| `effect` | V1's 4 side-less/below-floor detector groups (7 rows), V2:M2, V2:M5 | Same as above — no statistic was ever computed (side-less by design, below the 30-selection floor, or the "strict test" was never scored for M2; M5's log-loss/Brier table does not reduce to a single "effect" number). |
| `p` | same 7 V1 rows, V2:M2, V2:M5, V4:handed_lineup_vs_pitch, V4:stacked_top_weak_starter, V5's all 3 rows | V1/V2 as above. V4/V5's `no_replication` rows: the funnel's decision at the replication stage is made on effect **magnitude and sign** against the pre-registered floor (`"replication effect ... is under half the effect floor ... a sign flip counts"`), not on a freshly computed p-value — `results_v4_run.json`/`results_v5_run.json` give a `p_2023` (screen-stage) for some of these but no decisive p at the stage the row actually died at, and this migration copies the DECISIVE stage's numbers only (see "which stage's number was copied" below), so `p` is null rather than mixing a screen-stage p with a replication-stage effect. |

**The 7 V1 rows referenced above by "side-less/below-floor":**
`V1:implied_bullpen_disagreement:h2h`, `V1:implied_bullpen_disagreement:h2h_1st_5_innings`,
`V1:lineup_vs_starter:h2h`, `V1:lineup_vs_starter:h2h_1st_5_innings`,
`V1:park_and_weather:totals`, `V1:park_and_weather:totals_1st_5_innings`,
`V1:thin_matchup_history:h2h`.

## Judgment calls made explicit (not disagreements, but not verbatim either)

- **Which stage's number was copied for V4/V5.** Each spec's funnel run has
  up to three stages (2023 screen, 2024 replication, pooled/battery); this
  migration copies the number from the stage the row's own `status`/
  `level_reached` field says it actually reached and died at (screen_dead →
  `p_2023`/`effect_2023`; no_replication → `effect_2024` only, `p` left
  null per above; killed_by_battery → `p_pooled`/`effect_pooled`), never a
  number from a stage the row never reached.
- **M4's corrected numbers, not the original.** `docs/RESULTS_V2.md` carries
  both an original CI (`[-4.56pp, +7.12pp]`) and a 2026-08-31 correction
  (`[-4.31pp, +6.80pp]`) with the correction note stating it "is the
  authority for all of them." `V2:M4`'s verdict row uses the corrected
  interval, per that doc's own instruction, while the original text stays
  untouched in `docs/RESULTS_V2.md` itself (nothing in this migration edits
  any past document).
- **Phase 2B's verdict `p` is the pooled placebo-exceedance p (0.871), not
  SPA's p (0.002997).** `docs/EVOLAB_PHASE2B_RESULTS.md` records a genuine
  disagreement between the two instruments and explicitly adjudicates it:
  "the placebo ceiling embodies the correct null and SPA does not. The
  verdict stands unchanged." SPA's number is preserved, not discarded, in
  `within_sweep.spa_p` exactly where Decision 2's schema puts it.
- **V3's verdict `effect` is `S_hat(0) = 1.0`, not the ~165/225-minute
  median-latency figures.** The family's frozen primary hypothesis is
  `median(diff) > 0`, tested as `S(0) > 0.5`; the minute-denominated latency
  numbers are explicitly kept as descriptive secondary measurements by the
  family's own rules ("never promoted to findings without their own future
  pre-registration"). The registry's `effect` field records the primary
  test statistic; the magnitude figures remain in `docs/RESEARCH_V3_TIMING.md`
  for interpretation.
- **V2's semantic-hash atoms are this migration's own paraphrase**, not a
  transcription of a machine-readable spec — no such file exists for V2,
  unlike V1 (`evidence/hypothesis_family.json`), V4/V5 (their registration
  JSON files), or V3 (whose classes are named identically in prose and
  code). A future attempt to re-register an identical M-test will only
  collide with these hashes if it happens to reproduce this migration's own
  wording, which is unlikely — flagged as a known limitation of V2's
  entries specifically, documented in `src/research/alpha_registry.py`'s
  module docstring alongside every other family's grid source.
- **Elo audit `market = "h2h"` is inferred, not verbatim** — `docs/BENCHMARK_ELO.md`
  never writes the word "market"; the inference rests on an Elo
  win-probability model being a moneyline forecast by construction (no
  F5/totals variant exists in that document), a narrower and more confident
  basis than the V3 case above, which is why V3 was left null and this was
  not. Recorded as an inference rather than silently presented as verbatim.
- **`registered_utc`/`read_utc` inferred from context rather than an
  explicit sentence**, in three places: V1's read date (`2026-08-28`) comes
  from the evidence directory name `evidence/stage2_2026-08-28/`, not a
  sentence in `docs/RESULTS_STAGE2.md`; V4/V5's read timestamps reuse their
  registration timestamps because no separate "run"/"read" timestamp exists
  in `results_v4_run.json`/`results_v5_run.json` (the catalogue's stated
  run times match the registration instant to the minute); the Elo audit's
  `registered_utc` (`2026-08-31`) is inferred by co-location with its stated
  run date, since "frozen before any score is computed" carries no
  separately dated sentence of its own.

## What this migration did not touch

No past verdict was changed. No `docs/RESEARCH_V*.md`, no registration file
under `data/research/`/`evidence/`, and no `docs/ALPHA_REGISTRY_DESIGN.md`
were edited by this migration — only read. `docs/RESEARCH_CATALOGUE.md`
gained one pointer paragraph under "Counting the families"; nothing in that
section's existing text was rewritten.

## Post-migration note (2026-09-02, orchestrator)

The V3 verdict row for `transaction_first_seen` records the FIRST read
(ADDENDUM 1 in docs/RESEARCH_V3_TIMING.md). That read failed an
adversarial methodology review the same day
(docs/REVIEW_V3_FIRST_READ_2026-09-02.md): tested class broader than the
registered class, primary statistic swapped for a boundary-pinned S(0),
degenerate interval and p-value. The registry is append-only, so the row
stays; a superseding verdict row is appended when the corrected read
(ADDENDUM 2) passes a second review. Until then `total_searched` counts
the V3 class as read, which is the conservative direction for spend.

**Update, 2026-09-02 (L22):** the second review passed
(docs/REVIEW_V3_FIRST_READ_2026-09-02.md, "Second review — PASS") and the
superseding row has been appended: `data/research/alpha_registry.jsonl`
now carries a second verdict for `V3:transaction_first_seen`,
`result: "withdrawn"`, `read_utc: "2026-09-02"`, retracting the migrated
first-read "candidate" verdict above without editing or deleting it (the
original row is unchanged). Per ADDENDUM 2, the frozen `il_roster_move`
class restricted to game-relevant transactions
(`src/research/timingtest.game_relevant`) holds 19 of its required 30
events -- below floor, no result read. `total_searched()` now counts this
id's latest verdict (`"withdrawn"`) as NOT read, so the V3 class returns to
"still accumulating" for spend-accounting purposes; see
`src/research/alpha_registry.py`'s module docstring ("WITHDRAWING A
VERDICT") for the `"withdrawn"`/`"below_floor"` result values this
required adding.
