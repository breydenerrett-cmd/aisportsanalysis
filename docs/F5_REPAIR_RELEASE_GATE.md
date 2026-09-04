# Release gate for the paid T-2h F5 repair

**Owner directive, 2026-09-04.** The ~30,260-credit T-2h timing-normalization
repair is APPROVED but HELD. It does not begin until all seven checks below
pass and are demonstrated with evidence, not asserted.

Why the hold exists: the fast tier went from 3,831 green at `0c48a0e` to 22
failures + 13 errors at `4405b19` -- a forward-capture commit touching ONLY
data files (`credit_log.jsonl`, `weather_forecast.jsonl`, `data/watch/*`)
and no code at all. The capture tests read the real
`data/processed/credit_log.jsonl` through `src/capture/budget.py`'s
`spent_today()`; the owner-approved 36,451-credit purchase registered as
today's spend against a 900/day envelope, so the capture code correctly
declined to fetch and every assertion expecting fetches failed. Three
separate lanes had already reported "pre-existing failures" that could not
be reproduced -- each was telling the truth about a different data state.

**A suite that cannot distinguish "the code is broken" from "capture
appended a row" cannot certify a 30,000-credit dataset.** That is the whole
reason for this gate.

## The seven checks

| # | check | how it is demonstrated |
|---|---|---|
| 1 | Capture tests use fixture/temp credit logs, never the live production ledger | show the injection seam in the tests; grep/AST proof no unit-tier module reads the live store |
| 2 | Two runs of the suite on unchanged code agree, even if live capture appends between them | run, append a real capture row (or wait for a capture commit), run again, diff the results |
| 3 | The live capture process still reads the REAL ledger normally | `spent_today()`/`remaining_today()` against the production store, plus evidence of a real fetch |
| 4 | Test isolation cannot accidentally redirect PRODUCTION capture to fixture data | a test that fails if the production path resolves to anything but the real store |
| 5 | Fast and full tiers green from a CLEAN checkout | fresh clone/worktree, both tiers, no local state |
| 6 | The AZ/ARI and doubleheader join repairs stay covered by regression tests | the named tests, run and green |
| 7 | The repair manifest contains ONLY genuinely non-compliant T-2h games and rebuys none of the 4,013 held observations | manifest count + explicit proof of zero overlap with holdings |

Check 6 guards a fix that mattered: 288 of 302 unmatched games were a single
abbreviation split (`mlb_results.csv` spells the Diamondbacks `AZ`; the odds
feed resolves to `ARI`), and 6 more were doubleheaders colliding on a
`date:away@home` manifest key with no `game_pk`. Both silently removed real
games from the universe. A regression that reintroduced either would not
announce itself.

## After the repair, report actual

credits spent; eligible games; T-2h snapshots obtained; >=5-book pass rate;
unavailable snapshots (`PRIMARY_SNAPSHOT_UNAVAILABLE`); residual unmatched
games; gradeable decisions; MDE; lead-time distribution; book-depth
distribution.

Report what the frozen rule actually produces. **Do not force the result
toward the expected ~3,400 decisions or ~2.28pp MDE.**

## Sequence, unchanged

acquisition/normalization -> freeze the eligible universe -> pre-register the
F5 hypothesis families -> freeze the denominator -> only then discovery.

**No strategy evaluation until the dataset is frozen and the pre-registered
F5 universe is locked.** No winner search, no ranking, no threshold tuning,
no examining which systems would have profited.
