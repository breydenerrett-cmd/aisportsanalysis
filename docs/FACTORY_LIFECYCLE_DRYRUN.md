# Factory lifecycle dry-run

Generated 2026-09-05 00:40 UTC. Classifies the families already computed in `docs/FACTORY_OVERLAP_REPORT.md` into CANDIDATE-ELIGIBLE/RETIRED using only fields already persisted in the sweep artifact -- no evaluation, no outcome read. See `docs/FACTORY_LIFECYCLE.md` for the exact rule.

## `data/research/evolab/sweep-0014914df78666b9-REAL.json`

Population battery verdict: **FAIL**.

Reasons (already-persisted fields read):
- ceiling.generators_cleared is empty -- the population's real maximum cleared no placebo generator's threshold
- spa_cross_check.status is DISAGREE -- the artifact's own verdict says neither number should be quoted as a pass
- cscv.pbo is 0.6111 > 0.5 -- probability of backtest overfitting worse than a coin flip

- families found: **1,062**
- RETIRED: **1,062**
- CANDIDATE-ELIGIBLE (data does not rule them out -- NOT the same as admitted; admission needs a PreRegistration this script has no authority to write): **0**

This is a read of one already-existing population-level verdict applied uniformly to every family drawn from it -- there is no per-family fresh CSCV/SPA retest on record for any of them yet. See docs/FACTORY_LIFECYCLE.md for why this is the honest, conservative reading rather than a new judgement.
