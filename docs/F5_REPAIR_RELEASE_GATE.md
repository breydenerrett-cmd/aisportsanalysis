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
| 7 | **NO DUPLICATE COMPLIANT SNAPSHOTS** (redefined 2026-09-04, see below) | per-game compliance test + proof no compliant observation is re-queried and no target timestamp is bought twice |

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

## Check 7, redefined (owner, 2026-09-04)

The original wording -- "rebuys none of the 4,013 held observations" -- is no
longer methodologically correct, and holding to it would have blocked the
repair for the wrong reason.

Measured under the frozen rule: **only 2 of 4,315 existing observations are
compliant** with T-2h +/-5m and >=5 books. That is structural, not a defect.
The existing snapshots were taken at fixed WALL-CLOCK instants
(`SNAPSHOT_INSTANTS = ("16:50:00Z", "22:50:00Z")`), so their lead times
scatter across hours with each game's start time. A fixed TARGET-TIME rule
can almost never reuse fixed-wall-clock data. (An earlier figure of "987
already compliant" was measured against the looser T-6h..T-30m window that
the owner's amendment replaced; it should have been re-derived the moment
the rule changed.)

Re-querying a game at a new, PRE-REGISTERED target time is intentional
normalization, not duplicate waste. The real waste to prevent is buying the
same target timestamp twice.

**The rule now is:**

- re-query IS allowed when the existing observation is not compliant with
  T-2h +/-5m;
- SKIP the game when a compliant T-2h primary observation already exists;
- NEVER purchase the same target timestamp twice;
- retain every old observation immutably in `F5_RAW_HISTORY`;
- write normalized qualifying observations separately to
  `F5_TMINUS2_PRIMARY`.

## The paid repair rule (frozen; do not slide it)

- target **T-2:00** from the scheduled `start_time_utc`;
- provider grid tolerance **+/-5 minutes**;
- **pregame only**;
- preserve the requested timestamp, the returned timestamp, and per-book
  update timestamps;
- retain the **>=5-book** requirement;
- when unavailable or non-compliant, emit **`PRIMARY_SNAPSHOT_UNAVAILABLE`**;
- **never slide to a more convenient time.**

**Do not force every game into the primary universe.** A small acquisition
sanity tranche may run first to verify the frozen rule behaves as expected --
without inspecting outcomes or profitability at any point during
acquisition.

Authorization: up to **~43,130 credits** for the 4,313 games needing a
compliant primary snapshot, superseding the earlier ~30,260 estimate because
the frozen methodology changed the definition of compliance. Budget after:
~73,196 - ~43,130 = ~30,066, still covering 33+ days of the 900/day forward
envelope.

## Check 5, as the owner requires it

Clean-checkout tests that need absent gitignored historical stores must
**SKIP with an explicit reason**. They must not fail, and they must not
fabricate fixtures to make themselves green. A production/full-data checkout
must still exercise them normally.

## After acquisition, before any search

FREEZE the eligible research universe. Then pre-register, and lock, all of:
the F5 hypothesis families; the complete strategy denominator; the
discovery/replication split across the historical seasons; the
multiple-testing procedure; the failure criteria.

**No winner search, threshold tuning, or profitability ranking before those
are locked.**
