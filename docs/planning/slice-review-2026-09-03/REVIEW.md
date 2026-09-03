# Vertical-slice adversarial review — HEAD 41c74c7 (read-only audit)

`python3 scripts/test_parallel.py` → **OK, 3948 tests, failures=0 errors=0 skipped=1, 493.2s, exit 0**;
forward-store fingerprint OK (10 stores unchanged). Green — so every defect below is one the suite does not
cover. In-flight lane (`preflight.py`, `slate.py`, `bridge.py`, `daily_loop.sh`) audited as-is.

## BLOCKING

**B1. `recorded_utc` is not the write time — the freeze is unfalsifiable.** `src/engine/analyze.py:406` sets
`recorded_utc=snapshot.t`, identical to `decision_utc` and `information_time` on all 69 rows, so no record
carries any evidence of *when* it was written. `src/engine/truncation.py:43-45` and the test fixtures
(`tests/test_report_eod.py:30`, `tests/test_factory_scorecard.py:60`, which set `recorded_utc` ~5 min *after*
`decision_utc`) assume the opposite semantics. Nothing asserts the production value.

**B2. The flagship "live 2026-09-03 slate frozen" was written after games started.**
`evidence/decisions_v2.jsonl` mtime `2026-09-03T20:38:12Z`, committed in 41c74c7 at 20:39:31Z; the run cannot
have begun before `18:01:25Z`, the latest L1 capture it consumed (seven of nine games carry exactly that
`decision_utc`). Two of the nine staked games were already underway at that lower bound: `f857ea67…` (commence
`16:35:00Z`, `recorded_utc` claims `16:25:13Z`) and `e956df5f…` (commence `17:10:00Z`, claims `16:55:19Z`) —
86 and 51 min in at the earliest possible write, ~4 h and ~3.5 h at the observed one. The *board* was genuinely
pre-game; the *row* was not written before the outcome was knowable, and B1 hides it.

**B3. The settled/scored evidence is entirely backfilled.** The 2026-08-31 (20 rows) and 2026-09-01 (16 rows)
decisions first appear in commit 5ff6ac4 (2026-09-03 20:26:53Z), two to three days after those games finished
(verified with `git show <sha>:evidence/decisions_v2.jsonl` per commit). Those are exactly the rows that were
settled and that fed the accounts, the scorecards and `docs/eod/2026-08-31.md`. The
settle→account→scorecard→EOD half of the loop has only ever run on post-outcome-written rows.

**B4. Calibration is contaminated across systems.** `src/factory/scorecard.py:209` (`decision_key_for`) omits
`system_id`, and `src/engine/settle_slate.py:413` hands `build_scorecard` *all* systems' reviews, so
`_decision_review_pairs` (`scorecard.py:234`) pairs one system's decision with every other system's review of
the same `(event_id, market_key, selection_id, decision_utc)`. Reproduced:
`_calibration(trivial_always_home's 36 decisions, all 51 reviews)` returns **n = 41** pairs,
`logloss=0.6910194294992784`, `brier=0.2489365853658538` — byte-identical to the published `window=2026-08-31`
scorecard, whose own `n_decisions` is 27 and whose account staked 27 units. 12 of 43 decision keys are shared
by >1 system. `logloss_vs_market` *is* `objective()`; the one scalar the factory ranks on is wrong.

**B5. Pitch-store cutoff uses the UTC day; games file under the Eastern day.** `src/engine/features.py:600`
(`cutoff_date = t_dt.date().isoformat()`) against `rebuilt._gate`/`accumulate`'s strict `game_date < cutoff`
on the bare date, while slate membership uses `official_date` (Eastern, `src/pipeline/snapshots.py:392`). For
any decision instant between 00:00Z and ~04:00Z — the previous Eastern evening — the cutoff is the *next* day
and admits every pitch of the game's own official date: games still in progress at `t`, and on a backfilled
run the subject game itself. **19 of 69 published decisions sit on this condition** (measured as
`official_date(commence) < decision_utc[:10]`), e.g. event `1174006e…`, decision `2026-09-01T00:02:08Z`,
commence `2026-09-01T00:10:00Z`, official date `2026-08-31`, cutoff `2026-09-01`. It also corrupts the grade:
on that path `pitch_grade` becomes `GRADE_A` with `known_at = day_before_cutoff` (`features.py:613-621`),
asserting knowledge of a day that had not finished at `t`. It did not materialise in this demo only because
the store then ended 2026-08-27; commit c39cf7b (`statcast --catchup`, 20:28Z today) extended coverage to
2026-09-02 (windows now include `2026-08-28..2026-08-31`), so the next evening slate leaks for real.

**B6. Four markets is unreachable.** `SCOPE_MARKETS` names h2h/spreads/totals/F5-h2h and L1 carries all four
(49,858 / 9,130 / 9,134 / 742 rows), but all 11,088 genomes `enumerate_genomes()` produces declare
`eligibility.markets == ('h2h',)` and `routing.f5_condition == 'never'`, and `TrivialAlwaysHomeSystem`
(`src/engine/glue.py:630-647`) is h2h-only. All 69 decisions are h2h. Three of the four in-scope markets have
no reachable path through the demonstrated loop; the scope filter can only ever be a no-op.

## NON-BLOCKING

**N1. Refusals are never published.** `src/engine/analyze.py:250` drops FATAL-vetoed candidates with the
comment "recorded below as verdict=no_play" — it does not; `records` is built only from survivors
(`analyze.py:277-289`), and both `StaleBook` and `ThinBoard` issue FATAL. So 69/69 rows are `verdict="play"`,
the eight refusal verdicts in `VERDICTS` are dead vocabulary, and `docs/eod/2026-08-31.md`'s "No
refused/no-play verdicts today." is structurally guaranteed, not observed. Related: `verdict` is "play"
whenever a price exists (`analyze.py:288`), with no threshold — plays at `edge_bps = -1431` are staked.

**N2. `p_model = 0.52` is hardcoded and drives everything calibrated.** `src/engine/glue.py:637`. It is the
only `p_model` in the system (evolab genomes honestly emit `None` + `value_basis`), so every `edge_bps`, every
Bet Rating (`probability_quality = 0.04000000000000004` on all 36 rows — `|0.52-0.5|*2`) and every
logloss/brier derives from it. Disclosed in `thesis`/`evidence`, but published as an edge and rated.

**N3. The chain detects edits, not rewrites.** Verified on a copy: an in-place field edit is caught
(`broken_at_line=6`); rebuilding the file through `HashChainLedger.append` with one price changed verifies
**ok=True, 70 rows**. The only external anchor is genesis's v1 sha256 — already red:
`python3 -m src.cli ledger verify` prints `v1 ledger … CHANGED` (recorded `7d005a25…` vs current
`15da9db4…`), because `bridge.ensure_genesis` pinned a whole-file hash of an append-only file (and recorded a
`.claude/worktrees/agent-a9a8ecd4…` path that no longer exists). A permanently-failing integrity check is
worse than none. All 14 chains themselves verify clean.

**N4. Drawdown/peak are run-order, not chronological.** `data/paper_accounts/trivial_always_home.jsonl` holds
the 09-02 rows *before* the 08-31 rows and `_replay_prior_settlements` (`settle_slate.py:437`) folds them in
file order, so the published `Scorecard.account.drawdown = 7.420072992700852` is the max of a shuffled equity
curve. Settling dates in another order publishes a different drawdown.

**N5. Two disagreeing bankrolls for one system and date.** `docs/eod/2026-08-31.md`: `bankroll=1000.9470
roi_units=0.0789 drawdown_max=1.1870 n_settled=12`. The `window=2026-08-31` scorecard: `bankroll=995.0169
roi_units=-0.1846 drawdown=7.4201 units=27`. Both internally consistent (EOD per-day from 1000, scorecard
cumulative) — I recomputed the EOD figures by hand from the 12 ledger rows and they match to the digit,
including the 1.18699 intermediate drawdown — but nothing labels or reconciles the gap.

**N6. `Scorecard.window` names a date, holds cumulative content, and the published delta is backwards.**
`settle_slate.py:415` passes `window=date_str` while `bets`/`decisions`/`reviews` are the whole history.
Because 09-02 settled first, the row labelled `2026-08-31` has `n_decisions=27` and `2026-09-02` has 15;
`src/report/eod.py:310` sorts by the `window` string and publishes `2026-08-31 -> 2026-09-02, n_decisions:
27 -> 15 (-12)`, `logloss 0.6910 -> 0.7126`.

**N7. Reviews are inert.** All 51 `ReviewRecords` have empty `mechanism_checks`, `market_path`,
`late_information`, `missed_information`, `lineup_delta`, `bullpen_delta`, `counterargument_realized`; all
`thesis_outcome=UNTESTED`, `system_action=none`. Honestly labelled, but the "second verdict" and CLV are
structurally uncomputable (0 of 20 closes captured).

**N8. `objective()` is never called** in `src/` outside its own module and tests (`src/evolab/baseline.py` has
an unrelated local `objective`). `promotion_verdict` is what runs; it correctly refuses bankroll-only
promotion (`src/factory/fitness.py:298-310`).

**N9. No sealed-window guard on the new entry points.** `engine slate`/`engine settle` accept any `--date`;
`src/evolab/replay.py:124` refuses 2026-01-01..2026-08-27 by name, nothing in `slate.py`/`settle_slate.py`
does. L1's earliest row is `2026-08-27T10:26:48Z` — inside the sealed window.

**N10. Doubleheader ambiguity is recorded then discarded.** `src/board/gamekey.py:289-310` sets
`ambiguous: True` alongside `resolved: True`; `game_pk_for_event` (`:349-354`) returns the
nearest-commence_time guess and no caller — slate, wager row, settle — reads or records the flag. The one real
DH (BOS@NYY 2026-08-29) resolved correctly only because the two starts are 6 h apart.

**N11. A postponement stalls a date forever.** `run_settle` (`settle_slate.py:325-338`) refuses the whole date
if any wagered `game_pk` is absent from `mlb_results.csv` — no VOID path, no override; under `daily_loop.sh`
that is a daily ESCALATE and an indefinitely unsettled date.

**N12. `scripts/daily_loop.sh`'s S8 block has never executed.** Last loop run is e35d3f3 `Daily loop
2026-09-03` at 10:08:25Z; the slate→settle→eod wiring landed in a70c9f4 at 20:06:35Z the same day, and
`docs/OVERNIGHT_RUN.md` has no `daily_loop:` step lines. Every step of the demonstration was hand-invoked. The
guards read correctly (per-step exit status, no `-e`, ESCALATE lines, flock round the commit) but are
unproven. The 10:00Z cadence also forces `decision_time_for_game` onto a pre-10:00Z capture, whereas the demo
used captures to 18:01Z — the demonstrated decision instants are not the ones the unattended loop would produce.

**N13. Live and replay share the waist but not the feature builder.** `analyze()`, `glue.build_board`,
`glue.build_snapshot` are genuinely shared (one call site each:
`src/engine/adapters/evolab_system.py:203-247`, `src/engine/slate.py:349-361`). Divergences: the S3 replay
driver passes `features=view.features`, short-circuiting `features.build_features` entirely
(`glue.py:409-412`), so `features._build_replay` is never exercised by it; it passes `lineup_posted`
explicitly and `game_pk_map={}` (so `asof_key is None`, no as_of read, every replay record forced to grade D);
and `replay_decision` defaults to `adversaries=()` while the slate uses `DEFAULT_ADVERSARIES`, so ATTACK never
runs on replay. Separately, the 08-31/09-01 "replay" here did not use that driver at all — it re-ran
`run_slate` over past L1 captures.

**N14. Minor.** `evidence/eod_reviews_v2.jsonl` has two rows for 2026-08-31 (same `report_sha256`), one
carrying a `.claude/worktrees/agent-ae7a4efb…` `report_path`. `docs/OVERNIGHT_RUN.md` self-reports an untraced
provider call at 2026-09-03T05:21:23Z that spent ~3 credits with no `credit_log` row — outside this slice and
honestly disclosed, but a live credit path bypassing `creditlog`.

## Verified sound

Stop-at-T holds where implemented: `build_board` truncates to `observed_utc <= t` (`glue.py:317`), `as_of`
skips `row_dt > t_dt` (`src/core/asof.py:403`), and `from_asof` folds only *provenance counts* into
`assumption_exposure` — `boxscores_2026.jsonl` is an as_of default (`asof.py:321-328`) but its values never
reach `snapshot.features` or any system, so a final score cannot reach a decision that way. The first-pitch
guard is real and refuses rather than clamping (`slate.py:203-227`, `glue.py:309-315`), including on an
explicit `--asof`. Settlement is honest: I re-derived all 12 `trivial_always_home` 2026-08-31 settlements from
`data/historical/mlb_results.csv` by hand — 12/12 outcomes and profits match the account ledger. Nothing in
the settle path writes the decision ledger (`append_decision`/`V2_LEDGER_PATH` writes only at
`slate.py:390`). Idempotency holds (0 repeat `(event, system, market, selection)` pairs across 69 decisions
and 69 wagers). Losers published (13 in the EOD); `p_model=None` never defaulted (33 rows carry
`value_basis=price_standing_only…`); no `rating` where `p_model` is absent (33 nulls / 36 dicts);
`price_improvement_bps` never populated and never called edge; `clv_bps_mean` labelled advisory; `ENGINE2 is
None`; no `api/`/`web/` module imports `src.ledger`; `promotion_verdict` refuses bankroll-only promotion
conjunctively; all 14 hash chains verify clean.

## Could not verify

Whether B5 has *already* changed a published feature value — mechanism proven and the 19 affected rows
identified, but they carry no grade-A pitch feature (the store lagged when they were written) and I did not
re-run `accumulate` at both cutoffs to measure the delta a fresh run would now produce. True wall-clock write
times for the 08-31/09-01 rows beyond git commit stamps (B1 removes the in-band evidence). No-capture day /
partial slate / postponed game were read from code (`preflight.check` refuses on zero or >3 h-stale capture;
`decision_time_for_game` skips per-game with a reason; `run_settle` refuses the whole date) but not exercised.

## Verdict

**FAIL — apparently met, not genuinely met.** The wiring is real: one waist, one board builder, one snapshot
builder, a real first-pitch guard, real prices, real settlements I re-derived by hand, losers published,
honest `None`s where there is no probability, and a green 3948-test suite. But the two things the owner asked
to be *proved* do not hold. The freeze is not demonstrated: `recorded_utc` is the decision instant rather than
the write instant (B1), the settled evidence was written two to three days after those games ended (B3), and
even the flagship live slate wrote rows for games already underway (B2) — so "frozen before the outcome" is an
assertion the ledger is structurally incapable of supporting, while a whole-file re-chain defeats the only
tamper check (N3) and the v1 anchor is already red. And the loop is narrower than it reads: three of four
in-scope markets are unreachable by any registered system (B6); the only probability in the system is a
hardcoded 0.52 that every calibration number and Bet Rating rests on (N2); the objective those numbers feed is
computed over other systems' reviews (B4); an unguarded UTC-vs-Eastern cutoff already covers 19 of 69
decisions and became live-dangerous with today's pitch-store catch-up (B5); refusals are discarded so the veto
section can only ever say "none" (N1); the published fitness delta is backwards (N6); and the unattended path
has never once run (N12). Fix B1–B4, then re-run the loop for real on a day where the rows demonstrably
precede first pitch, before calling this proved.
