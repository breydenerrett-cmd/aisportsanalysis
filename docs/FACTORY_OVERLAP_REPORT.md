# Factory overlap report

Generated 2026-09-04 22:41 UTC. Counts only -- see `docs/FACTORY_SCALE_DESIGN.md` for the method and its limits.

Found 1 sweep artifact(s).

| artifact | world | n_strategies | n_games | real_champion |
|---|---|---|---|---|
| `data/research/evolab/sweep-0014914df78666b9-REAL.json` | REAL | 8811 | 4188 | 4f1b92d3a4cf55ba |

## Decision-level overlap: not yet computable

`src/evolab/sweep.py`'s `SweepReport.to_dict()` stores per-world aggregate statistics (selection counts, mean movement/ROI) but does not persist the per-strategy decision sets (`WorldFitness.masks`) that `src/evolab/overlap.py`'s dedup and Jaccard clustering need. Unique-wagers-vs-total-decisions and family clustering (docs/FACTORY_SCALE_DESIGN.md sections 1.4 and 2) therefore cannot be computed from the artifact(s) above as they stand today. This is stated here rather than estimated, per this program's rule that absence is the honest answer over a guess.

The total strategy count and total selection volume above are real counts from the sweep artifact(s); they are NOT a substitute for the unique-wager count and must not be read as effective sample size (see design section 3).

