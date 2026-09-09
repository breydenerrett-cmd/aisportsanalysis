# Autonomous plan — night of 2026-09-08

Written after the verifier pass on the picks-foundation workflow. Governed by
`docs/PRODUCT_DOCTRINE.md` (LOCKED). Where this plan and the doctrine
disagree, the doctrine wins.

## The one sentence

Tonight's work exists to make tomorrow's picks *early enough to be worth
something* and *honest enough to publish* — everything below is downstream of
those two.

---

## What we learned today that sets the order

| Finding | Consequence |
|---|---|
| FORWARD_TEST median lead time is **9.9 minutes** before first pitch; 72% inside 30 min | Picks are commercially useless AND structurally unmeasurable |
| `lineup_store.build` is called from **one place**, `scripts/daily_loop.sh` | Root cause of the above. The engine only ever reads the store |
| Clean CLV: FORWARD_TEST 7/11 positive, p=0.55, 4 games | **No signal.** Sample is tiny *because of* the lead time |
| MARKET_REFERENCE CLV: 50.0% positive, mean +0.00 bps | The instrument is calibrated. Nothing wrong with the measurement |
| 112 replay + 265 stale-close rows pooled into the published CLV | `clv.py` cannot be committed as-is |
| Verifiers found named, reproducible fake tests in 3 suites | Test debt is real and each item has a precise acceptance criterion |
| `engine slip` clustered blind to genome structure (15 families vs 11) | Fixed today. Guard added so it cannot recur |

**The through-line:** the lead-time defect causes the tiny CLV sample, which
causes the unmeasurable record. One fix unblocks the chain.

---

## P0 — Lineup cadence (the only change that moves the product tonight)

**Problem.** Genomes refuse until a lineup posts (`require_lineup=True`). The
lineup store refreshes once per daily loop. So a genome sees a lineup only when
a daily loop happens to catch it, and then fires on the next slate pass —
landing a median 9.9 minutes before first pitch.

**Change.** Refresh the posted-lineup store on a cadence that tracks when
lineups actually post, so a genome can decide as soon as its inputs exist
rather than hours later.

**Acceptance.** Measured over a following slate: FORWARD_TEST median lead time
materially exceeds 30 minutes, and the share of forward-test decisions frozen
inside 30 minutes of first pitch falls well below tonight's 72%. Report the
before/after distribution; do not declare success from the code alone.

**Risk and guardrails.** This changes *when* decisions get made, which is the
E-1 blast radius. Staking is already idempotent per position, so extra passes
are safe, but: do not touch `bet_id_for`, do not change decision identity, and
do not remove the live-mode commence-time skip. Read `scripts/afternoon_slate.sh`
before touching anything about decision identity — two frozen sets for one date
is intended.

**Point-in-time.** A lineup is a fact once posted; refreshing it more often is
not a leak. `matchup_history` is different — it reads a LEAKY career-totals
endpoint and must stay TODAY-only. Do not "helpfully" extend it.

---

## P1 — Test-quality debt (highest-confidence work, fully parallel)

The verifiers handed us named mutations that survive the suites. Each is an
acceptance criterion: write the test that kills that mutation, prove it fails
with the mutation present, restore.

**families** — live-ledger tests are tautologies (`n_families <= n_systems` is
a theorem about the constructor, green with clustering fully disabled);
`STRUCTURAL_IDENTITY_THRESHOLD` unpinned anywhere in (0.5, 1.0]; nothing pins
`_FULLY_TESTED_BASES`; `is_forward_play`'s provenance half untested (deleting
it admits 1,103 rows instead of 909); `_merge_partitions` transitivity within
one group of 3+ untested.

**news** — `_date` can return today on an unparseable value with the suite
green; the category-filter test is unmeasurable because `MAX_PER_TEAM=4` caps
the result; every component of the `for_team` dedup key can be deleted
undetected; `TestIngest` fixtures default `player_id` to `transaction_id`, so
deduping on the wrong field survives all 7.

**clv** — `_stderr_naive` has no test at all (body → `return 1.0` passes);
`_median` unpinned; `CLOSING_LEAD_STALE_SECONDS` unpinned; rollups can be
zero-filled with all 53 green.

---

## P2 — CLV hardening (blocks committing `src/report/clv.py`)

1. Carry `record_provenance` onto the measurement row. A caller currently
   cannot filter it, which is why the contamination reached a headline.
2. Segment or exclude `replay` and unstamped rows. Doctrine §6: no replays in
   a published record. Some replay rows were written 33 hours after the game.
3. Surface `closing_lead_stale` in every rollup. 265 rows call a board up to
   6.5 hours before first pitch "the close"; the per-row flag is honest and
   `summarise()` throws it away.
4. Rewire `by_cohort` to read `evidence/slips_v1.jsonl`. It currently reads
   `DecisionRecord.cohorts`, which was deliberately removed — it is dead code
   that can never activate.
5. Pin the judgement thresholds with tests (see P1).

---

## P3 — Two real source bugs in `src/pipeline/news.py`

Both reach the customer path and both fail **silently**, because
`api/games.py` wraps `attach()` in a bare `except`:

- `sentence()` raises `AttributeError` when `category` is present but `None`
  (`row.get('category', 'roster move')` uses a missing-key default).
- `read()` raises `TypeError` when two rows share a date and one
  `transaction_id` is a str and one an int. Latent today (all 586 are int) but
  it would blank the news section for the whole slate with no stated reason.

A silent gap is worse than a loud one here — the page would say "roster news
not fetched" while the store is full.

---

## P4 — Deferred, deliberately

- **As-of family clustering.** Family structure is time-varying (23 families
  as-of 09-04, 19 as-of 09-08) and the one behavioural merge did not exist
  before 09-07. Re-scoring a *frozen* decision with *today's* clustering is
  re-ranking history — amendment 8. Today this is contained because each slip
  freezes its own `agreement` block including `families_by_id`, so a published
  slip is reproducible from its own artifact. Needs a real design pass, not a
  quick patch.
- **The false docstring claim** in `families.py`: it says 818 rows "predate the
  field", but 447 of them were written 09-07/09-08 beside stamped rows. Wrong
  as written; changes no number today.
- **Picks lead Today (API + web).** The customer payoff, but worth far more
  after P0 lands. Sequenced after, not tonight.
- **`scripts/factory_masks_from_sweep.py`** — `placebo.real_world` receives
  zero games. Isolated; also fix the report generator's willingness to
  overwrite a recorded result with "not computable" when a regenerable cache
  is merely cold.

---

## Rules for every lane

- **No fabrication.** A stated absence with a reason beats a guess. Zero is a
  real value and never stands in for "unknown".
- **Every test must fail when its behaviour is broken.** Introduce the bug,
  watch it go red, restore, watch it go green. Say so in the report.
- **Never `git add -A`.** Stage explicit paths — parallel lanes are writing.
- **Do not commit another lane's files.**
- **Never print or echo secret values.**
- Match the surrounding code voice: docstrings explain *why* and what was
  rejected; every threshold is a named constant with its justification beside
  it.
