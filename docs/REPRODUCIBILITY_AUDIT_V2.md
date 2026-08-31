# Reproducibility audit — Research Family V2 (market structure)

Audited 2026-08-31 by an independent verification pass, following the
V4 audit's method (`docs/REPRODUCIBILITY_AUDIT_V4.md`). Nothing in
`data/historical/` or `data/research/` was written; the only new file in the
tree is this document.

**Verdict: REPRODUCED.** Every published number in `docs/RESULTS_V2.md`
matches the re-run, across all five hypotheses. M3 is still killed by the
current frozen battery (RULES_VERSION 2.0.0, fingerprint
`ac74c7a7f715f9ec` — matches exactly), via `book_concentration` and
`dose_response` under the registered bands, as `docs/VALIDATION_GATE.md`
records.

## Why V2 is a different shape of audit than V4

V4 pre-registers through `funnel.run(..., family_path=...)` and writes its
own frozen JSON evidence file. V2 predates that machinery — it was run
directly against `src/research/{pricepath,m1..m5}.py` and its numbers live
only in prose/tables in `docs/RESULTS_V2.md`, backed by
`tests/test_research_v2.py` (unit tests on synthetic fixtures, not the
headline sample). There is no `family_v2.json` to reload. So this audit's
"frozen evidence package" is the code as committed at V2's completion
(`036d053`, unchanged since — see Drift below) plus the real historical
stores it reads: `data/historical/odds_history/{mlb_2023,mlb_2024}.jsonl`
and `data/historical/mlb_results.csv`, for M4 also
`data/historical/odds_first_five/*.jsonl` and
`data/historical/first_five_results.jsonl`. All of it lives under
`data/historical/`, which is **not git-tracked** (`.gitignore` line 13) —
so `git status` cannot attest to its integrity the way it can for
`data/research/`. Verified instead by md5 before/after (see Integrity below).

## What was re-run

- A driver script under `/tmp` calling `pricepath.build`,
  `m1_overreaction`, `m2_staleness`, `m3_dispersion`, `m4_bullpen_gap`,
  `m5_devig`, `f5_store` exactly as committed, plus `battery.run` for the
  M3 machinery check (mirroring `tests/test_validation_m3.py`'s driver).
- Seasons: `pricepath.build(2023)` and `pricepath.build(2024)` only, matching
  V2's registered discovery window. No 2025, no sealed 2026 data read by
  anything in this audit.
- Wall clock: **21.7 s** for the full driver (join + all five hypotheses +
  the M3 battery check).

## Published vs re-run

### Data substrate

| | Published | Re-run |
|---|---|---|
| Events joined 2023 | 2,413 / 2,475 | 2,413 / 2,475 — exact |
| Events joined 2024 | 2,412 / 2,472 | 2,412 / 2,472 — exact |
| Quotes | 191,968 | 191,968 — exact |
| Median books/event | 18 | 18 — exact, **but only reproduces on 2023 alone** (pooled 2023+2024 is 14; see note) |
| Median snapshots/event; ≥3 | 4–5; 1,977/2,413 | 4; 1,977/2,413 — exact, also 2023-only |
| Home win rate | 51.97% | 51.97% on 2023 alone (1,254/2,413); pooled 2023+2024 is 52.02% |

**Note, not a mismatch:** the substrate table in `docs/RESULTS_V2.md` reads
as if it describes both discovery seasons together, but three of its rows
(books/event, snapshot density, home win rate) reproduce exactly only when
computed on **2023 alone** — confirmed by direct computation above. The
join counts and quote total are correctly pooled. This is a documentation
clarity gap (the table doesn't flag the season split), not a computational
error: every number is exactly reproducible once you know which slice it
describes. Flagged as non-blocking below.

### M5 — de-vig methodology

| Method | Published log loss | Re-run | Published Brier | Re-run |
|---|---|---|---|---|
| proportional | 0.674168 | 0.674168 | 0.240707 | 0.240707 |
| additive | 0.674160 | 0.674160 | 0.240708 | 0.240708 |
| power | 0.674177 | 0.674177 | 0.240719 | 0.240719 |
| shin | 0.674160 | 0.674160 | 0.240708 | 0.240708 |

n = 4,486 both. Median disagreement 0.37pp / p95 1.1pp, both exact. Best
method still flips (additive on log loss, proportional on Brier) — exact.

### M2 — weekend day-game staleness

| Cell | n | Published early advantage | Re-run |
|---|---|---|---|
| weekday-day | 238 | −0.0025 | −0.002523 |
| weekday-night | 1,542 | −0.0005 | −0.000486 |
| weekend-day | 503 | −0.0002 | −0.000241 |
| weekend-night | 285 | −0.0011 | −0.001115 |

n = 2,568 overall — exact. Strict test: **197** games qualify, of which
**3** are weekend afternoons — both exact, and the strict test remains
unrunnable for the same reason published (n=3).

### M1 — line overreaction

| | Published | Re-run |
|---|---|---|
| Pairs / events | 62,183 / 4,087 | 62,183 / 4,087 — exact |
| Lag-1 autocorrelation | +0.013 (p=0.13) | +0.0130 (p=0.1350) |
| Mean absolute change | 1.05pp | 1.0523pp |
| Fade 1pp | n=19,250, ROI −3.5%, p=0.13 | n=19,250, ROI −3.55%, p=0.1295 |
| Fade 2pp | n=7,720, ROI −4.1%, p=0.25 | n=7,720, ROI −4.14%, p=0.2534 |
| Follow 1pp | ROI −3.3%, p=0.12 | ROI −3.30%, p=0.1152 |
| Follow 2pp | ROI −2.8%, p=0.41 | ROI −2.78%, p=0.4066 |

Every field exact to the published rounding.

### M3 — cross-book dispersion (the false positive)

| Test | Published n / effect / p | Re-run |
|---|---|---|
| Baseline (2pp) | 249 / +8.49pp / 0.0063 | 249 / +8.49pp / 0.0063 |
| Deduped one/event | 223 / +9.38pp / 0.0029 | 223 / +9.38pp / 0.0029 |
| 2023 only | 144 / +6.14pp / 0.13 | 144 / +6.14pp / 0.1252 |
| 2024 only | 105 / +11.72pp / 0.016 | 105 / +11.72pp / 0.0155 |
| FanDuel only | 74 / +15.49pp / 0.0016 | 74 / +15.49pp / 0.0016 |
| BetRivers only | 29 / +12.27pp / 0.15 | 29 / +12.27pp / 0.1517 |
| BetMGM only | 27 / −9.44pp / 0.34 | 27 / −9.44pp / 0.3449 |
| Circa only | 22 / +1.20pp / 0.91 | 22 / +1.20pp / 0.9123 |
| Excluding FanDuel | 175 / +5.53pp / 0.16 | 175 / +5.53pp / 0.1590 |

Hit rate 60.6%, consensus implied 52.2%, CI [+2.34pp, +14.28pp], ROI +18.1%
— all exact.

Dose-response bands:

| Band | Published | Re-run |
|---|---|---|
| 0.015–0.020 | 940 / −1.56pp / 0.35 | 940 / −1.56pp / 0.3513 |
| 0.020–0.025 | 209 / +8.55pp / 0.012 | 209 / +8.55pp / 0.0123 |
| 0.025–0.030 | 33 / +5.40pp / 0.55 | 33 / +5.40pp / 0.5531 |
| 0.030+ | 7, below floor (withheld) | 7, +21.44pp (correctly withheld as unjudgeable, n<30) |

**M3 under the current frozen battery** (the objective's specific ask): the
candidate was rebuilt from raw price paths exactly as
`tests/test_validation_m3.py` does — 249 selections, effect 8.4920pp,
matching the documented candidate to 4 decimal places — then run through
`battery.run`:

- Registered bands (`[0.01, 0.02, 0.03, 0.10]`): `ran=True`,
  `survives=False`, `fatal=['book_concentration', 'dose_response']`.
- Funnel's own bands (`funnel._dose_edges`): `ran=True`, `survives=False`,
  `fatal=['book_concentration']`.
- `rules.version = 2.0.0`, `rules.fingerprint = ac74c7a7f715f9ec` on both —
  **exact match** to the fingerprint named in the objective and to
  `docs/VALIDATION_GATE.md`'s shadow-comparison table.

M3 is still dead, by the same two rules `VALIDATION_GATE.md` names.

### M4 — F5 vs full-game bullpen gap

The published write-up needed a `paths_by_event` mapping (full-game
consensus probability per event) that no committed driver or test builds —
it is genuinely ad hoc, so reconstructing it correctly was the one place
this audit had to make a methodological judgment call rather than replay a
pinned procedure. The right construction, confirmed by exact reproduction,
is the full-game de-vigged consensus at the same 360-minute
(`RECOMMENDATION_LEAD_MINUTES`) lead used everywhere else in the family
(M3, M5) — **not** the full-game quote matched to the F5 record's own
snapshot timestamp, which was tried first and undercounted/misbucketed (see
Investigation note below).

| | Published | Re-run |
|---|---|---|
| Ingest | 181 dates, 2,512 games, 0 failures, 33 void | 181 dates, 2,512 games, 33 incomplete — exact |
| Sample | 308 games, 270 decided, 38 ties | 308 / 270 / 38 — exact |
| F5 calibration | actual 54.4%, implied 53.2%, effect +1.25pp, p=0.67, CI [−4.56,+7.12]pp | actual 54.4%, implied 53.2%, effect +1.25pp, p=0.6651, CI [−4.56pp,+7.12pp] |
| Mean gap | +0.001 | +0.0011 |

Gap buckets:

| Bucket | Published n / mean gap / effect / p | Re-run |
|---|---|---|
| −1.000…−0.020 | 49 / −0.042 / +8.56pp / 0.20 | 49 / −0.0421 / +8.56pp / 0.2007 |
| −0.020…−0.005 | 52 / −0.012 / +2.11pp / 0.76 | 52 / −0.0119 / +2.11pp / 0.7625 |
| −0.005…+0.005 | 36 / +0.000 / −5.05pp / 0.50 | 36 / +0.0002 / −5.05pp / 0.5020 |
| +0.005…+0.020 | 66 / +0.011 / −0.87pp / 0.88 | 66 / +0.0114 / −0.87pp / 0.8796 |
| +0.020…+1.000 | 49 / +0.045 / +2.36pp / 0.73 | 49 / +0.0449 / +2.36pp / 0.7258 |

Exact on every field once the correct lead convention is used.

**Investigation note (this is exactly the kind of discrepancy the method
says to chase down, not paper over):** the first attempt matched full-game
odds to the F5 record's exact snapshot timestamp (both markets are fetched
in the same historical-odds batch, so an exact timestamp match exists for
most events). That produced n=247, mean gap +0.0036, and a visibly
different bucket split (34/54/50/60/49 vs published 49/52/36/66/49) — a
real mismatch, investigated rather than dismissed. Switching to the
360-minute lead convention (the same one M3 and M5 use, and the one
`backfill.py` itself documents as "the price the system actually uses")
reproduced every field exactly. Conclusion: the original M4 write-up
computed the full-game side of the gap at the standard recommendation lead,
not at the F5 snapshot's own timestamp. Diagnosed as a reconstruction
detail on this audit's side, not a divergence in the frozen result.

## Drift checked

`git diff 036d053 HEAD` (V2's completion commit, still the tip of the
history that touched this code) on every module V2's numbers depend on —
`pricepath.py`, all five `m*.py`, `f5_store.py`, `src/model/discovery.py`,
`src/core/odds.py`, `src/pipeline/backfill.py`, `src/data/parks.py`,
`src/pipeline/slate.py` — is **empty**. None of it has changed since the
numbers were published. `battery.py` and `funnel.py` are pure additions
(they didn't exist at `036d053`); they are the current machinery being
applied fresh to the frozen M3 candidate, which is the point of this check,
not drift.

## Integrity of the frozen evidence

md5 of every file under `data/historical/{odds_history,odds_first_five,
first_five_results.jsonl}` and every file under `data/research/`, taken
before and after the full re-run: **identical**. (`data/historical/` is
gitignored, so this md5 check — not `git status` — is what actually
attests to it; see note above.)

**One file did not stay byte-identical: `data/historical/mlb_results.csv`
(and its manifest).** Row count grew from 9,337 to 9,338 between checksum
snapshots, entirely inside 2026: a concurrent worker's forward-collection
pipeline (`src/pipeline/{dense,health}.py`, both showing as modified in
`git status` from other active work this session) is live-appending
today's settled games to this shared results ledger while this audit ran.
This is not the odds/price data V2's numbers are computed from, and it is
not the sealed 2026-01-01..2026-08-27 window read — it is 2026-08-3x
results being written by an unrelated in-progress pipeline. Verified this
did not touch the rows V2 reads: re-running `pricepath.build_report(2023)`
/ `(2024)` after the file grew reproduces the identical join counts
(2,413/2,475 and 2,412/2,472) and the identical 2023 home-win numerator
(1,254/2,413) as the first run. The 2023/2024 rows are unchanged; only new
2026 rows were appended after them. Recorded here rather than silently
re-running the checksum to get a clean diff, per the standing rule against
smoothing over a mismatch.

`git status` after the audit shows only this new document plus pre-existing
concurrent work from other active workers, none of it touching anything
this audit read: `src/pipeline/{dense,health,rosterwatch,history}.py`,
`src/providers/odds.py`, `src/research/timingreport.py`, `src/cli.py`,
`src/evolab/` and `data/processed/{odds_multibook,odds_snapshots,
prop_listing}.jsonl`, `data/watch/*_watch.jsonl`, `scripts/forward_capture.sh`,
`docs/{COLLECTION_POLICY,PROBE_PROP_LISTING,EVOLAB_PHASE2A_BASELINE}.md`,
and their tests. None of it is in `src/research/{pricepath,m1..m5,battery,
funnel}.py`, `data/historical/`, or `docs/{RESULTS_V2,RESEARCH_V2,
VALIDATION_GATE}.md`.

## Full suite

`python3 -m unittest discover -s tests -q`: **1,767 tests, 1 failure.**
The objective's baseline of 1,637 predates the concurrent work visible in
`git status` above (new `test_evolab_baseline.py`, `test_prop_listing.py`,
and edits to five other test files) — consistent with "other workers are
active," not a regression from this audit. The one failure,
`test_forward_evidence_tracked.ForwardEvidenceIsTrackedTests.test_existing_forward_stores_are_actually_tracked`,
fails because `data/processed/prop_listing.jsonl` exists on disk but isn't
git-tracked yet — a concurrent worker's in-progress forward-evidence file,
unrelated to V2's odds/price-path machinery. Confirmed pre-existing and
out of this audit's scope: running only the V2-relevant and
validation-gate modules in isolation —
`test_research_v2`, `test_validation_m3`, `test_battery_generality`,
`test_validation_planted`, `test_validation_pit`, `test_validation_equivalence`,
`test_validation_immutability` — gives **68/68 green**.

## Concerns

**Non-blocking:**

1. The data-substrate table in `docs/RESULTS_V2.md` mixes a 2023-only slice
   (books/event, snapshot density, home win rate) with pooled 2023+2024
   figures (join counts, quote total) without saying so. Every number
   still reproduces exactly once you know which slice — this is a
   documentation clarity issue, not a computation error, but it cost real
   audit time to resolve and a future reader would hit the same confusion.
2. M4's `paths_by_event` construction was never pinned in code or a test —
   it lives only in whatever ad hoc driver produced the published numbers,
   which is not in the repository. This audit reconstructed it correctly
   (confirmed by exact reproduction), but the fact that a wrong-but-
   plausible reconstruction (snapshot-matched rather than lead-matched)
   silently produces a different, still-plausible-looking table is worth
   noting: M4 is the one V2 result that cannot be re-verified from the
   repo alone without knowing this convention.

**Blocking: none.** No fabricated values, no leakage past 2024, no sealed
2026 access (none of the code paths exercised here can reach it — V2's
modules only ever call `pricepath.build(2023)` / `build(2024)`), no credit
spend, no terminology drift (M3's "deviation" is never called CLV or edge
in the modules; `late_move`/`price_improvement` language does not appear
here — that's the V4/timing-report family's concern, untouched by this
audit).

## Answering the objective directly

| Hypothesis | Verdict |
|---|---|
| M1 overreaction | **REPRODUCED** — every number exact |
| M2 staleness | **REPRODUCED** — every number exact, including the strict test's n=197/3 |
| M3 dispersion | **REPRODUCED**, and **still killed** by the current battery via `book_concentration` + `dose_response` (registered bands) / `book_concentration` (funnel bands), fingerprint `ac74c7a7f715f9ec` — matches the objective's stated current fingerprint exactly |
| M4 bullpen gap | **REPRODUCED** — exact once the 360-minute lead convention is used for the full-game side (see Investigation note) |
| M5 de-vig | **REPRODUCED** — every number exact |

Wall-clock of the re-run: 21.7 s (driver only; full suite 24.3 s separately).

**Confidence: high.** Five hypotheses, ~200 published numeric fields
compared, zero unexplained mismatches — every apparent discrepancy
(the 2023-only substrate stats, the M4 lead convention) resolved to an
exact match once diagnosed, and the diagnosis is recorded above rather than
silently patched. The one thing this audit could not do is verify the
original M4 driver script byte-for-byte, because it was never committed —
flagged as a non-blocking concern rather than papered over.
