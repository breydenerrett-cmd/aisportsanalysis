# Card V3 patches

Five patches against the MLB card, produced from the loss diagnosis
(`docs/research/loss_diagnosis/`, 2026-10-16). **None is applied to the committed tree.**
Each edits a file the V2 registration fingerprints (`src.appstate.card_ledger.
V2_FINGERPRINT_FILES`, PREREG_CARD_V2 11.2) or a file V1's shadow fingerprint covers
(`V1_FINGERPRINT_FILES`, section 10). **A fingerprint change restarts the counted sample**
("Changing the model restarts the sample", PREREG_CARD_V2 11.2), so these are for the V3
successor registration (`docs/PREREG_CARD_V3.md`, a DRAFT), applied once, together, in
the registration commit. They are not for V2 mid-sample.

## How to use

```
git apply --check docs/decisions/card_v3/<name>.patch     # each applies to HEAD alone
git apply docs/decisions/card_v3/tb_correction.patch       # and all five apply in this order:
git apply docs/decisions/card_v3/grade_average_odds.patch  #   tb, avg, stale, mlfill, withdrawn
git apply docs/decisions/card_v3/stale_board_real.patch
git apply docs/decisions/card_v3/ml_fill_lock_price.patch
git apply docs/decisions/card_v3/withdrawn_label.patch
CARD_V3_PATCHES_APPLIED=all python3 -m unittest tests.test_card_v3_patches
```

`tests/test_card_v3_patches.py` holds each patch's tests. On today's committed code the
tests that describe a missing behaviour are marked `expectedFailure` (the suite stays
green: `OK (expected failures=28)`), and they FAIL if the decorator is removed, which is
the proof they test the defect. With a patch applied and `CARD_V3_PATCHES_APPLIED=<name>`
(`tb`, `avg`, `stale`, `mlfill`, `withdrawn`, comma separated, or `all`) they run as
ordinary tests; delete the `@pending(...)` lines in the same commit that applies the
patch. Tests without `@pending` are guards that pass before and after.

The patch files are kept LF by `.gitattributes`
(`docs/decisions/card_v3/*.patch text eol=lf`): `git apply` rejects a CRLF patch against
an LF tree.

**What breaks when you apply them, by design.** `tests/test_card_v2_candidate_enumeration.py`
pins the content fingerprint of both file sets and fails the moment any fingerprinted file
changes (`RegisteredFilesAreUntouched`). With all five applied, on this checkout:
`V2_CONTENT_FINGERPRINT` becomes `b73126650b1bef7f120dc6bf33f60672c5d1ef4f1e0af62cfc5558a745d73fff` and `V1_CONTENT_FINGERPRINT` becomes `3fe755d6ed33e3911b1efae63eb4d66cebcc76484f58e565e60f77e17d69a614`
(LF-normalised, the test's own `_content_fingerprint`). Update both pins and write the new
`code_fingerprint` into PREREG_CARD_V3 in the same commit. Nothing else in the 13,885-test
suite changes with the patches applied (the other failures on a Windows checkout are
pre-existing and listed under "Tests").

## Measurements

Every measurement is a script, `scripts/diagnosis/card_v3_measure.py {tb,avg,ml,stale}`,
reusing the diagnosis' own loaders (`estimate_error.py`, `prices.py`) so a number here and
the number in the diagnosis come from the same code. Outputs sit beside this file
(`measured_*.json`). The sealed window (2026-01-01 to 2026-08-27) is never read; 2025 is
not used. **Every "what the record would have been" figure is hindsight on the same
published bets and licenses nothing beyond a forward test.**

### 1. `tb_correction.patch` (edits `src/analysis/playerprops.py`)

**Purpose.** Total bases over 0.5 is the event "at least one hit", which hits over 0.5
prices through the correlation-corrected beta-binomial (`_at_least`, rho). Total bases
over 0.5 went through the uncorrected convolution instead, so one event was priced two
ways on the same plate appearances (diagnosis 01 section 3d: +2.95 points on 1,163
identical player-games). The patch routes `need == 1` through `_at_least(hit rate)`.
Total bases over 1.5 and above are untouched (the diagnosis found them 1.5 to 2.3 points
high in 2024/2025; that is not this defect and is not fixed here).

**Measured effect** (`measured_tb_correction.json`, 1m06s):

| sample | n | TB 0.5 bias before | after | log loss gain [95%] |
|---|---|---|---|---|
| 2024, full-history regime (open, out of sample) | 10,581 | +2.74 pts [+1.72, +3.74] | -0.32 [-1.34, +0.68] | +0.0015 [+0.0002, +0.0028] |
| 2024, short-history regime (the live store's shape) | 2,612 | +2.94 [+1.31, +4.29] | -0.17 [-1.80, +1.18] | +0.0018 [-0.0004, +0.0036] |
| 2026 forward, published TB over 0.5 bets | 59 (39 picks, 20 fills) | our side probability 61.6% | 58.6% (mean shift -2.97 pts per bet; -1.17 averaged over all 149 published props) | n/a (no price-matched outcomes beyond the 59) |

On the 2026 bets, re-running the V2 gates on the corrected number: **all 59 fail G7 (the
value test), so all 39 TB over 0.5 picks would have been fills, none would have been a
pick** (those 39 went 16-23, -10.65u, HINDSIGHT). The 59 together went 31-28, -4.25u. This
is a re-test of the same entries, not a replay: the candidates that would have filled the
vacated slots are not modelled. The corrected number equals the hits path to machine
precision on every one of the 59 (`equals_hits_path_max_abs_diff: 0.0`).

**Registration consequence.** `playerprops.py` is in both fingerprint sets. Applying it
mid-V2 restarts V2's count and V1's `v1_code_fingerprint` drifts (PREREG_CARD_V2 11.6
discloses it).

**Test.** `python3 -m unittest tests.test_card_v3_patches.TotalBasesOverHalfIsTheHitsEvent`.

### 2. `grade_average_odds.patch` (edits `propboard.py`, `props.py`, `prices.py`, `opportunities.py`, `card_v2.py`, `card_ledger.py`)

**Purpose.** The owner's 2026-09-21 ruling is to grade at average odds. V2 grades every
entry at `price`, the best quote any book showed (`propboard.fair_and_best`;
PREREG_CARD_V2 lines 380 and 384). The patch records the board's mean **decimal** price
(`average_decimal`, over the same books the best price came from) on every candidate,
freezes it on the entry (`V2_FROZEN_FIELDS`), and `settle_v2` grades at it:
`profit_units` is the average-odds figure every reader already sums, `profit_units_at_best`
keeps the old one, `price` keeps the best price, and `graded_price_basis` says which
price was used. An entry with no recorded average (every one of today's 178; a board too
thin to average) is graded at its best price and labelled `best_price_no_average_recorded`:
no average is ever guessed. Moneylines get the average from `prices.snapshot` through the
`opportunities` row; `daily_card.build_pick_candidates` is not touched.

**Measured effect** (`measured_grade_average_odds.json`, rebuilt from the capture stores,
170 of 178 boards rebuildable):

| set | n | units at best price (as graded) | at board average | note |
|---|---|---|---|---|
| all 178 graded entries | 178 | -1.42 | -4.77 | the 8 with no rebuilt board stay at best |
| rebuilt subset | 170 | -0.69 | -4.04 | the diagnosis' other definition (mean implied probability) gives -4.11 |
| props | 149 (144 rebuilt) | -6.25 | -9.02 (-7.60 vs -4.82 on the rebuilt 144) | |
| moneylines | 29 (26 rebuilt) | +4.83 | +4.25 | |
| picks / fills | 110 / 68 | -9.26 / +7.85 | -11.28 / +6.51 | |
| shown / withdrawn | 161 / 17 | -6.43 / +5.01 | -9.16 / +4.39 | |

Mean decimal price 1.818 at best against 1.785 at the average on the rebuilt entries. The
diagnosis' "-9.65u at the average" for the 149 props used every book quoting the side, not
only the two-way books `fair_and_best` counts; this patch's definition uses the latter so
the best price is the maximum of the set it averages (-9.02).

**Registration consequence.** `propboard.py` and `props.py` are in the V2 fingerprint;
`card_v2.py` too; `card_ledger.py` is in V1's. New frozen field on every row from the
registration commit. Rows frozen before it have no average and grade at best with the
label above, so a V3 record that mixes the two must report the basis per row.

**Tests.** `python3 -m unittest tests.test_card_v3_patches.PropBoardAverage
tests.test_card_v3_patches.SettlementGradesAtAverageOdds
tests.test_card_v3_patches.TheAverageReachesTheCandidate`.

### 3. `stale_board_real.patch` (edits `src/analysis/best_bets_card.py`)

**Purpose.** `select()` hard-coded `"stale_board": None`, so all 175 published rows
recorded "no stale board" including runs where every candidate failed G3. The patch adds
`stale_board(candidates, now, params)` and sets the key from it.

**Threshold, and where it comes from.** The registration's definition (PREREG_CARD_V2
section 6, "Stale board"): the board is stale when no quote on the newest board for the
slate is within `params.fresh_seconds` of the publish instant. That is **3,600 seconds**,
G3's `FRESH_SECONDS`, which the registration ties to the capture cadence (the dense
capture widens to the full slate once an hour). It reads the very ages G3 compares, so "the
board is stale" and "every candidate fails G3" cannot disagree (a test asserts it).
Returns `None` for a fresh board and for an empty pool (no board is `raw_pool_size == 0`, a
different state); else `{age_seconds, threshold_seconds, n_quotes, n_unparseable}`.

**Measured effect** (`measured_stale_board_real.json`; an ESTIMATE from the prop pool only,
because the replay has no game candidates): the ledger recorded the flag on **0 of 175**
rows. Replaying the prop pool at 164 publish instants, **78 (47.6%) had no prop quote within
3,600 s**, 18 of 20 dates had at least one such run, and none had every run stale; 18 of the 78
fall in the 05Z hour (the overnight baseline). The patch's exact count would be lower on any
run where a game quote was fresh.

**Consumer note.** `scripts/daily_post.py` stringifies `stale_board` into `no_input` and only
shows it when the card has no picks and no fills; with the patch that line would read the
dict. Nothing else reads the key.

**Test.** `python3 -m unittest tests.test_card_v3_patches.StaleBoardIsComputedFromTheQuoteAgesG3Used`.

### 4. `ml_fill_lock_price.patch` (edits `src/appstate/card_ledger.py`)

**Purpose.** A moneyline fill is added on whatever quote the run had (G3 is not required
of a fill) and L3 locked it "as last published". The diagnosis (03 section 4): 20 of 29
graded moneylines had a newer multi-book capture before `locked_at`; on 11 of the 20 the
graded price was no longer on any book (mean -3.0 cents; the worst, a Dodgers fill graded
-147 with -212 the best at lock). The patch, for moneyline **fills only** and only on the
run that locks them: if the run's read of the game clears every hard gate, the fill locks
on that read's market side (`price`, `book`, `books`, `observed_utc`,
`market_probability`, `average_decimal`, `breakeven`, `value_need`, `bet`), keeping
`price_when_shown`; if the read fails a hard gate (the price has left the band) the fill is
withdrawn (graded, labelled); if the run has no read of the game the fill locks as published
and `lock_price_basis` says `last_published_no_read_at_lock`. Our own probability is never
refreshed. Props are out of scope (no capture exists between a prop's quote and its lock).

**Limit, stated.** Production passes only picks and fills to `publish_v2`
(`select()["all_bets"]`), so a candidate that hard-fails never reaches the ledger and the
"read fails a hard gate" branch fires only if a caller hands failing candidates in, as the
ledger's own docstring and tests do. In production a lock-time board that left the band
shows up as "no read" and the fill is labelled unverified, not withdrawn. Closing that gap
means passing the hard-failed candidates through `card_v2_for_date`, which is V3 pipeline
work, not a patch to this file.

**Measured effect** (`measured_ml_fill_lock_price.json`): of the 24 moneyline fills, 18 have a
newer board before lock; 7 of those 18 still had the graded price on the board, 11 did not;
the lock-time best was 3.7 cents worse on average. Re-priced at the lock-time best, the 18 go
from +3.08u to +3.17u. **2 of the 18 would have been out of band at lock (shorter than -160),
both losses, -2.00u as graded** (withdrawn under the patch's contract, unverified in
production); excluding them the other 16 go from +5.08u as graded to +5.17u at the lock
board. The patch is about auditability, not units: the stale moneyline prices did not
flatter the record in total (diagnosis 03).

**Registration consequence.** Departs from V2's L3 for fills only (PREREG_CARD_V2 section 6
states a fill "is graded at that price"). `card_ledger.py` is in V1's fingerprint, not V2's.

**Test.** `python3 -m unittest tests.test_card_v3_patches.MoneylineFillsLockOnTheBoardAtLock`.

### 5. `withdrawn_label.patch` (edits `src/appstate/card_ledger.py`)

**Is a ledger change needed? Yes, but a reader-level one.** The public record API already
excludes withdrawn entries from every figure and reports a count (`effective_record`;
`api/card.py` `_card_record_uncached` aliases the counted cohort), so the headline is
unambiguous. The ambiguity is in the ledger readers: `settle_v2` sums withdrawn entries into
the settled row's `wins/losses/profit_units`, `history_v2` (and so `/card/history`) serves those
totals per day, and `record_v2` reports the withdrawn only as a bare count. One ledger therefore
reads **97-81, -1.42u** (every graded entry) or **86-75, -6.43u** (what `record_v2` counts) with
no label, and "19 withdrawn" with no result. The patch changes nothing that is written
(the chain is untouched; old rows could not be relabelled anyway):

* `record_v2()` gains `withdrawn_graded` (W-L-units; `withdrawn` stays an int);
* each `history_v2` day gains `totals_include_withdrawn: True`, `shown` and
  `withdrawn_graded`, the pooled legacy figures unchanged beside them.

**Measured effect** on the real ledger: `record_v2()["withdrawn"]` is 19 and
`withdrawn_graded` is **11-6, +5.01u** (plus 1 void and 1 unresolved); summing the day rows,
pooled 97-81 / -1.42u = shown 86-75 / -6.43u + withdrawn 11-6 / +5.01u, the diagnosis' figures.

**Test.** `python3 -m unittest tests.test_card_v3_patches.WithdrawnPicksAreReportedAndLabelled`.

## Tests

* Committed state (patches NOT applied): `tests/test_card_v3_patches.py` runs `OK (expected
  failures=28)` (38 tests: 28 pending-patch tests, 10 guards that pass either way).
  `tests/test_card_v2_*` and `tests/test_player_props.py` are green. Full suite
  (`scripts/test_parallel.py`, 2026-10-16): 13,885 tests, 17 failures and 1 error, all
  Windows-checkout or environment failures unrelated to the card (`test_deploy_scripts`
  executable bits, `test_daily_bootstrap`, `test_timing`, `test_capture_no_set_time`,
  `test_appstate_users` path separators, `test_f5_eval`, `test_card_memory_budget`,
  `test_capture_health` imports `fcntl`).
* All five patches applied, `CARD_V3_PATCHES_APPLIED=all`: `tests/test_card_v3_patches.py`
  `OK (38 tests)`; the full suite shows the same 17 failures and 1 error **plus exactly two**,
  the fingerprint pins above (19 failures, 1 error). Nothing else in the suite moves.

## Reproduce

```
python3 scripts/diagnosis/card_v3_measure.py tb      # needs tb_correction.patch applied for the "after" arm to differ
python3 scripts/diagnosis/card_v3_measure.py avg
python3 scripts/diagnosis/card_v3_measure.py ml
python3 scripts/diagnosis/card_v3_measure.py stale
```

`tb` prices the "before" arm by swapping in the pre-patch branch at run time, so it needs
the patched tree for the "after" arm; on an unpatched tree before and after are identical and
the shift reads zero.
