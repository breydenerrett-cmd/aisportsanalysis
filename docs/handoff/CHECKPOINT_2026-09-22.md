# Completion checkpoint — 2026-09-22

Five workstreams, reported separately. Nothing here has been committed,
pushed or deployed. No purchase was made. The live publisher's behaviour is
unchanged in every case, and each section says so explicitly.

Environment for every claim below: branch
`claude/sports-betting-analysis-review-g1o0co`, HEAD `b525c54e`, 0 ahead /
22 behind origin (the 22 are routine capture-bot commits). `git diff` against
origin is empty for every source file cited.

Evidence tiers are labelled: **CODE** = read in the source; **RUN** =
observed executing; **DATA** = measured on stored output.

## Full test suite

`python scripts/test_parallel.py` — **8,216 tests, 39 failures, 2 errors, 35
skipped**, 344s wall over 12 workers. `forward-store fingerprint check: OK
(10 stores unchanged)`.

**Attribution, stated carefully.** I did not establish a clean pre-session
baseline count, so I am not claiming "all 39 were already failing". What I
can establish:

* **No failure names any file added or changed in this session.** Grepping
  the whole run output for `card_v2_enum_shadow`, `ceiling_admission`,
  `replay_candidate_enumeration`, `ceiling_reconciliation` and
  `fingerprint_diagnostic` returns zero hits.
* **By construction they cannot.** Every new module is imported only by its
  own test and its own script; nothing in the existing `src/` import graph
  changed. The only edits to pre-existing files are two test files, and both
  pass (`test_card_v2_report`, `test_card_v1_v2_cutover`: 14/14).
* **Every module touched in this session passes in isolation**: 697
  card/ledger/API tests, the 26 enumeration tests, the 7 ceiling tests, and
  the worker's 70 pitcher tests.

The 39 break down as: 22 in `tests.test_deploy_scripts`
(`test_scripts_are_executable` ×11, `test_every_listed_script_parses` ×11 —
shell scripts on NTFS, no executable bit and CRLF line endings); an
`fcntl` import error (POSIX-only module); a `/tmp` vs `C:/tmp` path
assertion; `test_peak_rss_mb_is_positive` returning 0.0; and a cluster in
db-backup, seed-restore, capture-window and NFL-chain modules that a second
worker independently observed in the same categories before this session's
card changes existed. **These are environment-dependent, not verdicts on the
code.** On Linux CI most of them do not apply.

One of the 39 is worth its own line, because it is a real data finding rather
than an environment artifact:
`tests.test_historical_archive.test_each_archived_entry_decompresses_to_its_sidecar_sha256`
reports two archived entries whose sidecar checksum does not match their
decompressed content — `odds_first_five/manifest.json` and
`odds_history/manifest.json`. That archive is not in git, so this is local
disk state, and nothing in this session writes to `data/historical`. It is
unattributed and should be checked on the machine that produced the archive
before it is trusted.

---

## 1. Candidate enumeration — SHADOW ONLY

**Status: implemented, tested, evidence produced. Not integrated into any
published path. Not deployed.**

### What changed
| File | Kind |
|---|---|
| `src/analysis/card_v2_enum_shadow.py` | new module, in neither fingerprint list |
| `tests/test_card_v2_candidate_enumeration.py` | new, 26 tests |
| `tests/test_card_v2_report.py` | one vacuous test replaced |
| `scripts/replay_candidate_enumeration.py` | new, tracked reconstruction harness |
| `docs/CARD_V2_IMPLEMENTATION_ERRATUM_2026-09-22.md` | new record |

No registered file was edited. `docs/PREREG_CARD_V2.md` is untouched: §16
permits only a closed list of entries and ends "Anything else is a new rule
id", so the findings went into the erratum instead, and promotion of the
corrected enumeration would require a new rule id rather than an amendment.

### The defect (CODE + DATA)
`daily_card._consensus_side` returns `max(p_away, p_home)`, so a game
moneyline candidate always carries `market_probability >= 0.50`. G5's
PLUS_MONEY branch requires `< 0.50`. Disjoint — the registered PLUS_MONEY
class cannot fire on a game moneyline at any price. DATA: 332 stored
moneyline entries, every price negative, minimum market probability 0.5003;
7 PLUS_MONEY candidates ever, all props, all refused on G7, none published.

### Tests (RUN)
`python -m unittest tests.test_card_v2_candidate_enumeration` → **26 tests,
OK, 1 expected failure.**

The expected failure is the defect itself, asserted against the live builder
(`test_registration_section_2_requires_both_sides_of_every_game`). It is
marked expected so the suite stays green while the departure stays recorded,
and so that correcting the live path in place turns it into an *unexpected
success* that forces whoever did it to confront the fingerprint restart 11.2
requires.

Assertions covering the owner's list: both priced sides reach evaluation ·
reversed home/away · market underdog distinguished in fields from a positive
price on a favoured side · missing quote reported with a reason · stale quote
enumerated and refused by G3 (not conflated with "never posted") · G11 dedup
after ranking · G12 ceiling · G14 plus-money sub-cap · no side enumerated
twice · the registered candidate dict passed through field-for-field.

### Shadow isolation — proved three ways, not asserted (RUN)
1. **Content.** Both fingerprinted file lists hash to their unchanged values
   over LF-normalised bytes.
2. **Import graph.** A test walks `src/`, `api/` and `scripts/` and fails if
   anything there mentions the module. Nothing does.
3. **Behaviour.** The same card is built through the registered entry point
   in two subprocesses — one that never imports the shadow module, one that
   imports it first — and the payloads are compared byte for byte. Equal.
   This is what covers shared dependencies, config and data rather than only
   the two source files. A fourth test parses the module with `ast` and
   fails on any write, open, subprocess or network call.

**Read this as "shadow enumeration repaired". Public V2 is NOT repaired.**
The published card still enumerates one side per game and still cannot list
a plus-money moneyline.

### Reconstruction evidence (RUN + DATA)
`python scripts/replay_candidate_enumeration.py --date 2026-09-22
--out evidence/enumeration_reconstruction_2026-09-22.json
--pin-inputs evidence/enumeration_inputs_pinned_2026-09-22.jsonl`

Each of the seven 2026-09-22 publish snapshots reconstructed **separately**,
from quotes observed at or before its own `published_utc`. Inputs pinned to
an immutable 8.2 MB extract (23,742 quote rows), sha256
`7bdd93a056b570d2153d98c29c8c8bcbea3e7c1081d88864f769ab57fe0e8fe9`, so the
result survives store rotation and any concurrent repair.

Determinism, stated precisely: an immediate rerun was byte-identical. A
later rerun, after a concurrent worker had changed other files, differed by
**eight lines, all of them in the manifest** — the dirty-tracked-file list
and the `--pin-inputs` field. Every line of the `snapshots` block, every
count and every gate breakdown was identical. The findings are
reproducible; the manifest deliberately records the tree state it ran
against, which is the point of having one.

| Published (UTC) | listed | sides before | sides after | added | added clearing every board gate | primary refusals among the added |
|---|---:|---:|---:|---:|---:|---|
| 14:43:31 | 3 | 16 | 32 | 16 | 15 | G5 ×1 |
| 15:41:59 | 5 | 16 | 32 | 16 | 14 | G5 ×1, G13 ×1 |
| **19:14:07** | 5 | 15 | 30 | 15 | **0** | **G3_STALE ×15 — every added side** |
| 20:12:45 | 6 | 15 | 30 | 15 | 13 | G5 ×1, G3 ×1 |
| 21:00:25 | 12 | 15 | 30 | 15 | 11 | G5 ×1, G3 ×1, G13 ×2 |
| 21:31:49 | 13 | 15 | 30 | 15 | 11 | G5 ×1, G3 ×1, G13 ×2 |
| 22:02:40 | 14 | 15 | 30 | 15 | 12 | G5 ×1, G3 ×1, G13 ×1 |

"Board gates" means the six the board alone can decide: G1, G2, G3, G4, G5,
G13. The model gates are not among them — see below.

**The 19:14:07Z snapshot is called out on its own row because every one of
its fifteen added sides failed G3 freshness.** The board was more than an
hour stale at that publish. That is a finding about that run's data, not
about enumeration, and a summary that averaged it away would overstate what
the correction reaches: six of seven snapshots is not seven.

**It is labelled a controlled reconstruction, not a replay**, and the script
says why in its own docstring: no point-in-time snapshot of the dossier /
feature state exists, so our own number cannot be rebuilt as the publisher
held it. G6, G7 and G8 are therefore reported as `model_input_unavailable`
and **never** as passes. No count of "would have been picks" is produced and
no profitability claim is made. The manifest lists the three inputs that are
not reconstructible and why. The prior locked state *is* recoverable — each
snapshot's own `all_bets` carries `locked`/`locked_at` — and is covered by
the card store's hash.

### Affects the current publisher?
**No.**

### Remaining blockers / open
* **Run line — OPEN.** §2 registers both sides at ±1.5; the implementation
  attaches the favoured side's run line as display text only.
* **Props — OPEN.** §2 registers both sides of every contract;
  `props.py:148` keeps only `propboard.most_likely`'s side. This matters
  more than it looks: **every entry on all seven 09-22 publishes was a
  prop.** No game moneyline has ever been published under V2.
* Promotion needs a new rule id, a registration, its own fingerprint and its
  own count. Not requested here, and no activation date is proposed.

---

## 2. Pitcher refresh — REPAIRED LOCALLY, NOT DEPLOYED

**Status: implemented, tested, integrated at both call sites. Not committed,
not pushed, not deployed.**

Delivered by a worker; I have reviewed the report and the traced call chain,
not re-derived every measurement. Items marked *(worker-reported)* are its
evidence, not mine.

### The defect (CODE + RUN)
`.github/workflows/daily-loop.yml` → `scripts/daily_loop.sh` →
`src.cli cmd_daily` step 3 → `pitchers.build_log_store(ids, today[:4])` with
`resume` defaulting True. `_has_season` returns True on *any* cached row for
the season, so a pitcher with one 2026 appearance is never refetched. This is
the **current-season** path, every day — not a historical backfill. Confirmed
at runtime against the untouched local store: 9 of 10 tracked probable
starters were skipped without the fetch seam ever being called. The
empty-season marker has the same problem (CODE; no live instance exists, so
it is covered by a synthetic-fixture test).

### What changed
`src/pipeline/pitchers.py` (+202/−21, new `refresh=True` mode separating
closed-season resume from in-season refresh, 20-hour staleness, whole-season
replacement so no duplicates, failure leaves cache and coverage state
untouched, `max_refetch_per_run` budget), `src/pipeline/store_archive.py`
(+102, `snapshot_full()` reusing the existing gzip + sha256-verify machinery),
`src/cli.py` and `scripts/daily_bootstrap.sh` (call sites).

### Tests (RUN, worker-reported)
`tests/test_pipeline_pitchers_refresh.py` (7) and
`tests/test_pitcher_log_freshness_audit.py` (7). All five required scenarios
covered. Pre-fix, against `pitchers.py` reverted to HEAD in a scratch copy,
all 7 refresh tests failed with `TypeError: build_log_store() got an
unexpected keyword argument 'refresh'` — the correct pre-fix failure, since
the capability did not exist. Post-fix all pass; 56 pre-existing pitcher
tests unaffected.

### Before/after (DATA, worker-reported)
Ten real pitchers, fetched against a **scratch copy** — the real store's hash
and mtime are unchanged, which is what keeps the enumeration reconstruction's
inputs intact. Appearances rose 36→39, 93→95, 88→91, 0→16 and so on; newest
stored appearance moved from 2026-09-04/05 to 2026-09-15..22.

Model input, as-of 2026-09-11, through `pitchers.matchup_pitcher_features` →
`dossier.build()` "starters" → `briefing.build_slate` (a real, scheduled
consumer): `away_sp_appearances` 27→28, `away_sp_era` 3.9558→3.7969, with
nothing dated on or after the cutoff leaking in. **Data-coverage comparison
only — no accuracy or profitability claim, and no historical prediction was
overwritten.** Separately: `cmd_predict`'s deployed `model.json` carries zero
`sp_*` features, so that consumer is not gated on this store today.

### Freshness check
`scripts/pitcher_log_freshness_audit.py`, matching
`scripts/calibration_drift_audit.py`'s `ESCALATE:` + exit-code convention.
Per-player for the slate, not the store maximum. Distinguishes job executed ·
fetch succeeded · source coverage · restored-copy coverage · model-input
freshness. On 2026-09-10 it escalates (one pitcher with no 2026 rows at all,
exit 1); on the well-covered 2026-08-15 it reports 30/30 fresh, exit 0 — so
it separates a real gap from healthy coverage rather than alarming on "zero
fetched".

### Affects the current publisher?
**Not yet.** Nothing reaches the Actions runner until committed and merged.
Deploying it changes what the daily job fetches and what the dossier holds.

### Remaining blocker
Owner decision to commit/merge. The `snapshot_full()` pre-write snapshot must
be confirmed working on the deployed store before the first live run
overwrites it.

---

## 3. Cap enforcement — DIAGNOSED AND DEMONSTRATED, NOT APPLIED

**Status: defect confirmed, correct behaviour implemented in an unwired
module and demonstrated on the real sequence. Publisher unchanged.**

### The defect (DATA + CODE)
The registered cap is 10 listed bets, picks and fills together (owner,
2026-09-16 00:45Z), and §16 records the cost he accepted: "an eleventh entry
that passed every gate is refused a slot rather than a published fill being
withdrawn."

`best_bets_card.select` honours it per run. `card_ledger._apply_ceiling_v2`
does not: `room = max(0, ceiling - len(locked_shown))` exempts locked
entries, entries lock at their own first pitch and are carried forward, so
the card grows past the cap through the day. `web/js/card.js` renders
`all_bets` in server order and caps nothing.

The `n_picks = 11` in the handoff is **not** a counting-unit artifact. It is
eleven distinct picks on a card that listed fourteen entries against a cap of
ten. Three of the seven publishes breached it: 12, 13, 14.

### What changed
`src/appstate/ceiling_admission.py` (new, unwired — applies the cap at
admission so a carried entry keeps its slot and a fresh eleventh is refused
one, which removes nothing already published), `scripts/ceiling_reconciliation.py`
(new, read-only), `tests/test_ceiling_admission.py` (new, 7 tests, **OK**).

Kept deliberately separate from enumeration: different module, different
script, different test file, so neither defect's evidence reads as the
other's.

### Demonstration (RUN)
`python scripts/ceiling_reconciliation.py --date 2026-09-22` — exit 1, three
escalations, and the cap holds at ten on every run with 3, 4 and 5 entries
refused a slot and **no published entry removed**.

### Affects the current publisher?
**No.** Applying it would.

### Remaining blocker
Owner decision: admit under the cap, or amend the registered cap — which
under §16 is a new rule id. No historical entry has been deleted or
truncated.

---

## 4. Fingerprint diagnostics — REPRODUCED AND BOUNDED, NOT FIXED

**Status: cause identified, minimal reproduction retained and runnable,
recorded hashes preserved unchanged.**

### Two findings (RUN)
`python scripts/fingerprint_diagnostic.py` (new, read-only, exit 1):

1. **`code_fingerprint` depends on the checkout.** It hashes raw bytes, and
   line endings are bytes. §16's V2 value reproduces exactly under all-CRLF;
   this checkout holds three of the seven files as LF with byte-identical
   committed content (`git diff` from `859176ba` is empty) and computes
   `0a5d8ad7…`. So the same code stamps different fingerprints depending on
   whether it published from Windows or Linux CI, and 11.2's "a change
   restarts the counted sample" guard can fire on a checkout difference.
2. **§16's recorded `v1_code_fingerprint` is not the value at the commit it
   names.** It reproduces only with `src/report/card.py` and
   `src/appstate/card_ledger.py` taken from `859176ba~1` — the two
   `V1_FINGERPRINT_FILES` members that commit itself modified. It pins a
   pre-commit state, so the V1 comparison's baseline is not the registered
   one.

### What was NOT done
No recorded hash was reset or recomputed into agreement. `code_fingerprint`
itself was not changed — fixing it edits a fingerprinted file and restarts
the sample, which is the owner's decision. The enumeration regression tests
were not blocked on it: they pin content over LF-normalised bytes instead.

### Affects the current publisher?
**No.** But note that every V2 row published so far carries a fingerprint
whose value depends on where it ran.

### Remaining blocker
Owner decision on whether to normalise (and accept the restart) or to record
the platform dependency and leave it.

---

## 5. Handoff corrections — DONE

Four claims in my own handoff were wrong and are corrected at source in
`docs/handoff/STATE_OF_PLAY_2026-09-22.md` (original text preserved and
marked, plus a new §4.1 with evidence and timestamps), and in two audit notes.

1. **Price bias direction was inverted.** Including the best book in its own
   consensus *understates* improvement (12–44%, up to ~97%), it does not
   inflate it. The reference is **LOBO-relative**, not "true". 14 affected
   callers listed; `src/analysis/lobo_value.py` already does correct
   leave-one-book-out and is unaffected. Derivation and fixtures retained.
2. **BALLDONTLIE payloads are not lost.** 959 release assets on
   `balldontlie-harvest-2026-09` vs 461 manifest entries (429 complete, 198
   with rows) — two different units, both stated. Entitlement **not
   verified**: the key exists, but the sanctioned cheap probe is currently
   unusable because the default branch's workflow copy lacks the `mode`
   input, so dispatching would trigger a full harvest. Do not claim a
   re-harvest needs new spending.
3. **Statcast is current**, through 2026-09-21, via the seed branch plus
   daily catch-up. The "ends 2024-09-30" figure described a git-ignored
   partial local copy. One source-to-forecast path verified end to end; it
   feeds the engine's paper strategies, not the published card probability.
4. **Pitcher logs**: the repo dates were right but irrelevant — the deployed
   job reads larger cache copies. The real defect is workstream 2.

Root cause of all four, stated once in the document: **a local working-tree
read was treated as the system's live state.**

---

## What is ready for controlled live-change approval

| Item | Ready to propose | Why |
|---|---|---|
| Pitcher refresh (workstream 2) | **Yes** — commit/merge decision | Repairs a live job that has fetched nothing for five days. Reversible, snapshot-protected, tested, no rule or registration touched. |
| Ceiling admission (workstream 3) | **Yes, as a decision** | The published card is exceeding a cap the owner personally set. Fix is written and demonstrated; applying it is his call. |
| Cutover leak-check repair | **Yes** | Test-only. `tests/test_card_v1_v2_cutover.py` asserted the real V2 store did not *exist*, which stopped being a leak check the day V2 first published; it now compares the store's bytes across the publish, which is what it was written to detect. |
| Fingerprint normalisation (workstream 4) | **Decision only** | Any fix restarts the counted sample. |
| **Candidate enumeration (workstream 1)** | **No — shadow only** | Promotion is a new rule id under §16, needs registration and its own count, and the model gates were never evaluated in the reconstruction. |
| Run line / prop enumeration | **No** | Not started. Still departing from §2. |
