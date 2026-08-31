# Reproducibility audit — Research Family V4 (exploratory interactions)

Audited 2026-08-31 by an independent verification pass. Nothing in
`data/research/` was written; the only new file in the tree is this document.

**Verdict: REPRODUCED.** All six specs, every published field, bit-for-bit.

## What was re-run

- Family: `data/research/family_v4_exploratory.json` (6 specs, registered
  2026-08-31T02:16:27Z, fdr_q 0.10), loaded from disk and handed back to
  `funnel.run(..., family_path=<that same file>)`, so the run's own
  byte-for-byte pre-registration check had to pass before any level executed.
- Inputs: the real stores, not injected seams — `matrix.read(2023)` /
  `matrix.read(2024)`, `backfill.price_pair`, `history.read_results`.
- Seasons: `(2023, 2024)` only — `DISCOVERY_SEASONS`, structurally enforced by
  `funnel.run`. Observed selection dates span 2023-04-04 .. 2024-09-30. No
  2025 and no sealed 2026 data was read.
- `scoreboard_path=None` so the audit could not append to the frozen
  scoreboard.
- Wall clock of the re-run: **8.66 s** (whole driver 8.8 s).
- Battery: RULES_VERSION **2.0.0**, `rules_fingerprint()` = **ac74c7a7f715f9ec**
  — identical to the fingerprint recorded in the frozen family's `note`.

## Published vs re-run

Every field of every result row was compared (`status`, `level_reached`,
`n_2023`, `effect_2023`, `p_2023`, `n_2024`, `effect_2024`, `n_pooled`,
`effect_pooled`, `p_pooled`, `q_pass`, `battery_fatal`, `notes`, `expected_n`,
`p_fdr`, `fdr_family_size`, `registered`, `fdr_threshold`), plus row order.
**Total field mismatches: 0.** Published values below; re-run values were
identical in every cell, so a single column is shown rather than a doubled one.

| spec | status | lvl | n_2023 | effect_2023 | p_2023 | n_2024 | effect_2024 | n_pooled | effect_pooled | p_pooled | expected_n | p_fdr | BH thr | q_pass | match |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| pitch_lean_vulnerability | killed_by_battery | 3 | 553 | +0.00909 | 0.671665 | 537 | +0.01209 | 1090 | +0.01057 | 0.453575 | 909 | 0.453575 | 0.016667 | false | exact |
| stacked_top_platoon | screen_dead | 1 | 856 | −0.00982 | 0.499681 | – | – | – | – | – | 1086 | 1.0 | 0.033333 | false | exact |
| platoon_pressure | screen_dead | 1 | 243 | −0.00753 | 0.818606 | – | – | – | – | – | 569 | 1.0 | 0.05 | false | exact |
| stacked_top_vs_pitch | screen_dead | 1 | 602 | −0.00847 | 0.650834 | – | – | – | – | – | 917 | 1.0 | 0.066667 | false | exact |
| handed_lineup_vs_pitch | no_replication | 2 | 487 | +0.00150 | 0.938850 | 607 | −0.03547 | – | – | – | 911 | 1.0 | 0.083333 | false | exact |
| stacked_top_weak_starter | no_replication | 2 | 266 | +0.00794 | 0.786360 | 447 | −0.00444 | – | – | – | 584 | 1.0 | 0.1 | false | exact |

`registered` = true and `fdr_family_size` = 6 on all six rows, published and
re-run: the denominator is the full family, early deaths entering at p = 1.0.

### The one battery-judged spec

`pitch_lean_vulnerability` reached level 3 on 1,090 selections (2,256 rows in
the wider half-threshold graded sample that arms the dose check). Re-run
verdict: `survives = False`, `ran = True`, fatal =
`["team_concentration", "book_concentration", "extreme_removal"]` — the same
three, in the same order, as published, under fingerprint ac74c7a7f715f9ec.

### Prose numbers in docs/RESEARCH_V4_EXPLORATORY.md

The narrative table's percentage-point figures all match the re-run to the
digit: +0.91pp / n=553 and pooled +1.06pp over 1,090 at p = 0.45;
−0.98pp / 856; −0.75pp / 243; −0.85pp / 602; +0.15pp then −3.55pp;
+0.79pp then −0.44pp. Zero survivors, nothing advancing to the forward ledger.

## Drift checked, and why it did not matter

The V4 results were committed at 4f5c7a1; HEAD has moved since (the V5 stuff
family). Two changed inputs were examined rather than assumed benign:

- `src/research/funnel.py` — one hunk, appending `starter_velocity_gap` and
  `starter_groundball_share` to `NUMERIC_FEATURES`. Additive; no V4 spec names
  either, and no measurement, gate or correction code was touched.
- `data/research/matchup_matrix_{2023,2024}.jsonl` — fully rewritten by the
  V5 re-ingest, which is why the diff looks total. Compared field-by-field
  against the versions at 4f5c7a1: same 2,430 / 2,429 game_pks, and **0
  differences** across the V4-relevant columns (`away_/home_` ×
  `lineup_platoon_share`, `starter_platoon_gap`, `lineup_vs_primary_pitch`,
  `primary_pitch_share`, `top_minus_bottom`, plus teams and dates). The
  rewrite only added the two new starter columns.

So the exact reproduction is not luck of an unchanged tree: the inputs V4
reads are provably identical and the code path is unchanged.

## Integrity of the frozen evidence

md5 of every file in `data/research/` taken before the re-run and re-verified
after: all eight unchanged (both family files, both results files, both matrix
files, the shadow battery report, the scoreboard).

`git status` after the audit shows only this new document, plus two
pre-existing working-tree edits from concurrent unrelated work on
`src/cli.py` and `src/pipeline/snapshots.py` (closing-price staleness flag),
which this audit neither made nor touched.

Full suite after the audit: `python3 -m unittest discover -s tests -q` —
1,507 tests, OK.
