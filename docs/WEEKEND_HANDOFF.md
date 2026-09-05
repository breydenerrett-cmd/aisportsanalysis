# Weekend handoff (interim draft — updated at each milestone; final on Monday)

Last updated: 2026-09-05 ~10:1xZ. Full ledger: `docs/WEEKEND_PROGRESS.md`; queue: `docs/WEEKEND_QUEUE.md`.

## Starting checkpoint (Fri 2026-09-04 21:2xZ)
F5 universe frozen at `ed0373f` (4,315 / 4,298 OK / 17 unavailable / 3,682 gradeable / 1,597+2,085 / MDE 1.62pp / hash `c675086…33cd1c`); prereg DRAFT unreviewed; `register_family` not called; capture recovered after the band-accounting outage; L25 repo side pushed but cutover blocked on secrets.

## Final state (so far)
- **Two families registered, evaluated, published — both zero survivors.**
  - `F5_MONEYLINE_CALIBRATION_2026H1` (m=3): H1 SCREEN_FAIL (2023 −0.58pp; 2024 −0.88pp p=0.41); H2-bottom/top POPULATION_SHIFT_FAIL (pre-registered before any outcome read; bottom showed a 2023 +4.06pp → 2024 −3.98pp sign flip). `docs/F5_RESEARCH_RESULTS.md`.
  - `TOTALS_FULLGAME_2026H1` (m=1): M1 POPULATION_SHIFT_FAIL (2023 −1.14pp below the 3.0pp floor; 2024 +0.72pp p=0.62; line-bucket χ²=281.7, book-count χ²=367.7); M2 pre-determined POPULATION_SHIFT_FAIL. `docs/TOTALS_RESEARCH_RESULTS.md`.
- No threshold, bucket, floor, or convention was changed after any outcome was read. Every gate was mechanised in code and pinned by mutation-tested regressions before the freeze.
- Capture: healthy throughout; canonical helper `scripts/capture_health.sh` (state from artifacts + lock, never balance). One window lost earlier Friday (15:16Z), logged as unrecoverable, none since.
- Factory: canonical wager store, overlap/Jaccard, lifecycle state machine. The 8,811-strategy sweep collapses to 6,050 unique wagers and 1,062 families; on persisted evidence all 1,062 classify RETIRED. That is the concrete answer to "why not 100,000 systems": the population must be de-duplicated and evidence-gated before it is scaled.
- Reasoning loop audited: no outcome coupling; win-with-refuted-mechanism → REASONING_WRONG now pinned.

## Important commits (chronological)
f2d008c weekend control files · 073ef4d F5 methodology review · 515ed93 F5 final spec · 309cc38 capture-health helper · db6eef8 F5 eval path · bb6eaee F5 adversarial FAIL · 0646c0e fixes · 8371058 re-review PASS · 5dc74e8 R1/R2 · (freeze) F5 family record · (results) F5 run · 06b5a44 F5 results doc · 9b28c62 totals methodology · 89ecfc3/8ed7244/6fc4e4e totals review→rev2→approved · b5d5f19 factory design+slice1 · 1bec5ae audit at 6h · (W16/W20/W21/W22/W23 lanes) · 01efa5f totals universe frozen · 35e0beb totals adversarial FAIL · (fix) · 0346858 re-review PASS · (freeze) totals family · (results) totals run · 5d2d99d totals results doc · 11dea8b factory slice 2 · (W25) lifecycle.
`git log --oneline ed0373f..HEAD` lists all ~70.

## Tests
Full parallel suite last reported 4,548 tests, 0 failures (lane); fast tier ~4,200 green on main at each landing.

## Credits (odds API)
Monthly remaining 25,495 (floor 5,000). Weekend spend: live-capture band only (Fri 273/900; Sat 3/900 so far). **Zero** historical/probe spend this weekend. Reset is monthly: ~20k will expire unused unless the B3 comparator (below) is authorised.

## Data acquired
None purchased. Derived: totals universe manifest (regular season 1,296/1,288, hashes `2f4f7fcf…`/`b2e6dbf9…`), F5 price-payload hash, sweep decision masks (regenerable, untracked).

## Unresolved methodology questions
1. Population-shift gate design: line-bucket occupancy measures league scoring drift, not comparability — see `docs/TOTALS_METHODOLOGY.md` "Lesson". Must be decided per hypothesis type BEFORE the next freeze; feature-side shift tests must be run and recorded in the spec before freezing.
2. Whether any F5/totals calibration question is worth a third family at all given two clean nulls at ~1.6–2.7pp resolution.

## Blocked on Brey
- **W2 capture externalization cutover**: add `ODDS_API_KEY` as a GitHub Actions secret and make `.github/workflows/forward-capture.yml` reachable from the default branch; then fire once, confirm one external commit, disable the in-session capture Routine. Safe default: in-session capture keeps running (it has, all weekend).
- **W4 T−2h full-game ML comparator** (~4–5k credits, historical_backfill band) so B3 bullpen-gap becomes testable. Reviewer found 0/3,682 owned snapshots within tolerance. Safe default: do not buy.

## Exact next recommended action
Approve or decline W2 and W4 (two yes/no calls). Research-wise: no new family until the shift-gate rule is settled; the next highest-value non-spend work is scaling the forward population using the lifecycle framework on de-duplicated families, not more historical calibration tests.
