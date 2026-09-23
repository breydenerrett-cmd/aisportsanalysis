# Controlled integration report — 2026-09-23

Branch `claude/sports-betting-analysis-review-g1o0co`. Nine commits, none
merged to the default branch, nothing pushed, nothing deployed, no purchase.
Evidence tiers: **CODE** read in source, **RUN** observed executing, **DATA**
measured on stored output.

---

## 1. Commit identifiers

| Commit | Workstream |
|---|---|
| `dfa0cf8a` | Correct four wrong claims in the handoff at their source |
| `02cfaf69` | Fix a leak check that stopped being one when V2 first published |
| `e68321b6` | V2 candidate enumeration: both moneyline sides, shadow-only |
| `a139879c` | Ceiling: diagnose the breach, demonstrate admission enforcement |
| `069f9a16` | Fingerprint: reproduce the checkout dependence, preserve the record |
| `2def4f83` | Pitcher logs: separate in-season refresh from closed-season resume |
| `d3b8ebd9` | Authorise one shadow runner and record the first forward run |
| `77dd901e` | **Restore the ten-entry ceiling at admission** (`v2_admission_2026_09_23`) |
| `0e2e64ee` | Fingerprint bookkeeping: version the method, keep every recorded value |

Not committed: the conversation exports under `docs/handoff/` (7.6 MB of chat
logs — an unintended large data copy) and the pre-existing untracked
`test_*.py` scratch files at the repo root, which are not mine. The pinned
enumeration input extract is committed gzipped (279 KB, from 8.2 MB); its
uncompressed sha256 is recorded in the manifest so the reference still
resolves. Secret scan over every committed file: clean.

**Baseline-versus-patch comparison: NOT YET COMPLETE.** An isolated
two-worktree comparison of `069f9a16` against `2def4f83` is running. Until it
returns, the attribution I have is the weaker kind the ruling rejected, and I
am not presenting it as more. See §2.

---

## 2. What merged and ran

**Nothing merged to the default branch. Nothing deployed.** Scheduled
workflows run the default branch, so no change here has reached the
production runner.

### Pitcher refresh — activation still BLOCKED
Committed at `2def4f83`, not activated. The bounded checks the ruling made
conditions of activation are in flight: the isolated baseline-vs-patch run,
the deployment-environment check, the 20-hour-rule probe, the behavioural
regression through the daily caller, the snapshot-restore proof against the
real store, and the full downstream-consumer enumeration. **Activation is not
authorised by me and has not happened.** The rollback reference is
`069f9a16`, the commit immediately before the patch.

One thing already verified (RUN): the before/after sample was taken against a
scratch copy, and the real store's hash and mtime are unchanged — which is
what kept the enumeration reconstruction's inputs intact while both
workstreams ran.

### Ceiling — INTEGRATED into the real publisher path
`77dd901e`. `card_ledger._apply_ceiling_v2` now applies the cap at
admission. Tested through `publish_v2` across successive runs against a real
ledger file (`tests/test_card_ledger_ceiling_admission.py`, 9 tests, **RUN**,
OK), not only the standalone helper:

* an already-published entry keeps its slot and is never removed to make room;
* a new entry cannot buy a slot by arriving already locked — the explicit
  bypass test publishes ten, then offers an eleventh whose game has already
  started so the merge locks it on sight, and it is refused admission;
* a day already over the ceiling keeps all fourteen entries and admits none;
* a later clean slate gets the ordinary ten-entry rule;
* one test asserts the ledger rule and `src/appstate/ceiling_admission.py`
  agree, because the logic is deliberately written twice — `card_ledger.py`
  is inside `V1_FINGERPRINT_FILES` and the helper is not, and a rule that
  decides what gets published belongs where the fingerprint can see it.

Stamped `ceiling_admission_version = v2_admission_2026_09_23` on every row.
Rollback: revert `77dd901e`; the constant on each stored row identifies which
rule produced it, so rows from either side of the change stay distinguishable
without inference.

`tests/test_card_v2_ledger.test_locked_entries_are_never_refused_by_the_ceiling`
was replaced. It asserted the exemption and passed, while the behaviour it
pinned is what let real cards reach fourteen entries. Both properties are now
tested separately: being locked buys nothing; having been *published* is what
protects a bet.

### Fingerprint — versioned, nothing overwritten
`0e2e64ee`. New module in neither fingerprint list, so adding it moved no
recorded value. `card_ledger.code_fingerprint` is byte-for-byte unmodified
and v1 wraps it rather than reimplementing it. The classifier returns
`CANNOT_DETERMINE` for "did selection behaviour or model inputs change",
because file hashes cannot answer that — a checksum format change must never
imply the sporting model changed. The §16 V1 value is recorded as a known
**non**-representation discrepancy (it pins a pre-commit state, erratum E4),
with a test asserting it is never classified representation-only.

The erratum's "a real change could be offset by a line-ending change" claim
is **withdrawn** as unsupported, in the document and in the test comment.
sha256 offers no such mechanism and no case was constructed. The failure mode
is one-way: a false alarm, not a blind spot.

### Archive "corruption" — resolved, sidecar untouched
The two checksum-mismatched entries are **not corrupt**. Both are plain
`.json`, so unlike the nine `.gz` entries they are subject to `core.autocrlf`
and sit in a Windows tree as CRLF. Normalised to LF, each one's sha256 equals
**both** its git blob hash and the sidecar's recorded value exactly:

```
odds_first_five/manifest.json  LF -> 60e9497f…  == sidecar == git blob
odds_history/manifest.json     LF -> 5f7ce223…  == sidecar == git blob
```

So the recorded checksums are right and the content never changed; the
*check* was checkout-dependent. No recorded checksum was overwritten —
doing so would have destroyed the only evidence that the content is intact.
The verification now reports a representation-only difference as such and
still fails on anything else, and a mismatch on a `.gz` still fails outright
because line endings cannot explain one there.

That is the **third** false alarm from one root cause today, after the V2
fingerprint and the V1 fingerprint. Every checksum in this repo that hashes
raw working-tree bytes is checkout-dependent.

---

## 3. Public behaviour: what changed and what did not

| Behaviour | Changed? |
|---|---|
| **Ten-entry ceiling on the published V2 card** | **YES.** From `77dd901e`, a card lists at most ten entries. Nothing already published is removed; the eleventh is refused admission. |
| Which candidates V2 evaluates | **No.** The published card still builds one moneyline side per game and still cannot list a plus-money moneyline. |
| V2 gates, thresholds, scores, ranking | **No.** Untouched. |
| V2's `code_fingerprint` and counted sample | **No.** `card_ledger.py` is not in `V2_FINGERPRINT_FILES`, so V2's sample does **not** restart. |
| `v1_code_fingerprint` | **YES**, recorded in §16 under the entry 11.6 permits, with both LF-normalised and as-checked-out values. The changed function is on V2's publish path only — V1 publishes through `publish`/`_lock_and_merge` and calls neither — so no V1 selection or published row changes. |
| Pitcher log freshness in production | **No.** Committed, not merged, not activated. |
| Any historical published card | **No.** Nothing deleted, truncated or rewritten. |

---

## 4. First forward shadow result

`scripts/shadow_enumeration_run.py` — the single authorised caller. The
isolation test is now an allow-list of one rather than a ban: a *new*
importer still fails it, and a second test parses the runner with `ast` and
fails on any publish call, so the allow-list buys an import, not a publish.

**Result, 2026-09-23 board as at 02:50Z (DATA):** 16 games on the slate, 16
modelled, and **zero candidates on both paths** — because all 16 were below
the registered six-book floor (2 to 5 books quoted; books had not yet posted
next-day lines).

That is the board's state, not a verdict on either rule, and the record says
so: `board.games_without_a_priced_board` carries the per-game reason, so the
zero cannot be misread as "a full board was evaluated and everything was
refused". An earlier version of the record omitted that and is kept beside it
for comparison. **The first *complete* forward result needs a thicker board
and is not fabricated here.** Re-run the command when the morning board fills.

The runner captures what the authorisation asked for: per-quote observation
timestamps, complete model inputs with raw **and** calibrated outputs plus a
per-game check that `sigmoid(a + b·logit(raw))` matches the number the
candidate actually carries, parameter and implementation identity, both
sides' quotes and candidate identities, and every gate result and selection
outcome. G6/G7/G8 run on the real frozen model. A candidate with no model
number keeps `our_probability = None`, fails those gates, is refused, and is
marked `model_input_missing` — so "our model said no" can never be totalled
with "our model had nothing to say".

Corrected as instructed: the historical reconstruction summary now states
explicitly that at the **19:14:07Z** snapshot **all fifteen** added sides
failed G3 freshness — the board was over an hour stale at that publish.

---

## 5. Next bounded task, and the milestone after it

### Next: both-side prop enumeration
Scoped against the code (**CODE**), and smaller than expected.
`propboard.build` **already builds both sides** — `propboard.py:232` loops
`(("Over", over), ("Under", under))` and stamps `"side"` on each contract,
each with its own price and de-vigged probability. Nothing is missing at the
board.

The loss is one downstream filter. `src/report/props.py:148` passes the board
through `propboard.most_likely`, which keeps only `probability > LIKELY_FLOOR`
(0.50) — so the under side is discarded before V2's gates ever see it, and so
is any over below 50%. A `capped` limit then truncates further.

The bounded task, mirroring the moneyline fix exactly: build V2's prop
candidate pool from `built["contracts"]` rather than from
`most_likely(...)`, in the shadow module, behind the same isolation, through
the real candidate-to-selection path, with existing thresholds untouched. The
registered scope is `batter_hits` and `batter_total_bases` only.

Two facts to carry into it: `batter_home_runs` has **zero** under quotes
across eight books, which is a real market limit rather than a defect — and
it is outside §2's registered scope anyway. And this matters more than the
moneyline gap did, because **every entry on all seven 2026-09-22 publishes
was a prop.**

### Then: registered run-line enumeration
§2 registers both sides at exactly ±1.5. The implementation attaches the
favoured side's run line as display text only (`daily_card.py:571-572`,
`card_v2.py:228` stamps `"line": None`), so no run line is a candidate on
either side. Same approach, same isolation, same thresholds.

### Deeper-analysis milestone, kept separate
None of the above is a better forecasting model and none of it will be
reported as one. The first deeper-analysis milestone remains a measured
comparison of the existing baseline against a small number of genuinely
different challengers on the same target, timestamps and eligible games, with
probability accuracy, calibration, selection quality and realised return kept
apart. That is a separate registration and does not ride on any of this work.

---

## Open blockers

1. **Pitcher activation** — waits on the bounded checks now running. Not
   authorised until they pass, and the "patch only" failure column is empty.
2. **First complete forward shadow result** — waits on a board that clears
   the six-book floor.
3. **Enumeration promotion** — still shadow-only. Under §16 promotion is a
   new rule id with its own registration and count, and the model gates have
   never been evaluated on a real forward board.
