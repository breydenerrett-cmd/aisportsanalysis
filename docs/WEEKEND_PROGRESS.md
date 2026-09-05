# Weekend progress log (append-only)

## 2026-09-04 21:2xZ — weekend mode started
- Task: W0 freeze verification DONE (independent recount + hash reproduced; 12/12 tests). Model: parent (bash/python).
- Capture health: 21:15Z run in flight; 111 artifacts today; live band 233/900; balance 25,555.
- W3 Opus review RUNNING (amended with A/B/C question). W2 BLOCKED_HUMAN (secrets).
- Next: W13 routine, W1 health helper.

## 2026-09-04 21:5xZ — W3 methodology review DONE
- Commit 073ef4d. Opus verdict: READY TO REGISTER AS AMENDED; family scope A (H1/H2 only), 13 binding amendments; comparator purchase (B) recommended separately → W4 BLOCKED_HUMAN.
- Note: reviewer's --amend rewrote an already-pushed commit locally; rebuilt onto pushed history via commit-tree, no worktree touch, pushed.
- Capture health: 21:15Z run in flight (artifact 21:19Z); no ESCALATE.
- Dispatched: W6 eval path (Sonnet, worktree), W5 final spec (Sonnet, worktree), W1 health helper (Sonnet, worktree, running).
- Next: adversarial prereg review once W5+W6 land, then register_family, then W7 discovery.

## 2026-09-04 22:0xZ — W1 health helper DONE, W5 final spec DONE
- W1: 309cc38 (16 tests; full parallel suite 4,269 green in the lane). Live: CAPTURE_HEALTH HEALTHY_IDLE age=12m artifacts_today=112 live 233/900 historical_today=73,576 (band separation visible).
- W5: 515ed93 final registrable spec appended; 3 items open for adversarial review (family_id string, hash serialization format, n>=300 on middle tercile).
- W6 eval path still RUNNING. Adversarial prereg review dispatched after W6 lands.

## 2026-09-04 22:2xZ — W6 evaluation path DONE
- db6eef8 cherry-picked; 37 lane tests pass here; tie audit reproduced (0 three-way books, gate min 5 intact); price-payload hash f2ff7b74… reproduced from manifest; dry_run 3,682 rows, 1,597/2,085, terciles fit on 2023 only, 2024 buckets 768/668/649. No outcome read.
- Dispatched: adversarial preregistration review (Opus) over final spec + eval code. register_family only on a pass.
- Capture: HEALTHY_IDLE.

## 2026-09-04 22:5xZ — adversarial prereg review: FAIL (bb6eaee)
- Blocking: B1 H1 inferred on pooled universe / no 2023 screen leg; B2 FDR m=3 in code vs m=2 in record; B3 no gate mechanised. Must-fix: M1 family.register cannot freeze this record shape; M2 A5 chi-square already fatal on feature-side counts (p=0.00203) → H2 replication is a pre-determined POPULATION_SHIFT_FAIL, to be pre-registered as such (threshold NOT changed).
- Clean: PIT/leakage, hashes, window guard (mutation-tested). Open items decided (family_id kept; hash serialization normative in code; n>=300 all terciles).
- Dispatched Sonnet fix lane. Registration still not called. Capture: healthy (22:05Z commit landed).

## 2026-09-04 23:0xZ — F5 family registered, discovery run complete: ZERO survivors
- Re-review PASS (8371058) with R1/R2 must-fix → fixed 5dc74e8 (season_split recorded skipped on single-season leg; spec hash bounded). Fast suite 4,008 green.
- Family frozen: F5_MONEYLINE_CALIBRATION_2026H1, m=3, spec sha f637dd17…, both universe hashes verified (commit after 5dc74e8).
- Results 72c0c76: H1 2023 −0.58pp (SCREEN_FAIL; 2024 −0.88pp p=0.41). H2-bottom 2023 +4.06pp → 2024 −3.98pp p=0.021 (sign flip; POPULATION_SHIFT_FAIL, χ²=12.40 p=0.002 pre-registered). H2-top 2023 −1.66pp → 2024 +1.78pp p=0.33 (POPULATION_SHIFT_FAIL). No threshold touched. Per-book H1: 13 of 15 books negative, 2 positive (superbook, wynnbet), none significant — earlier line in this log overstated it.
- W8 results doc dispatched (Sonnet). W9 totals audit now READY. Capture healthy through the run.

## 2026-09-04 23:3xZ — W9 totals methodology landed (9b28c62)
- Coverage audit re-run here reproduces docs/TOTALS_COVERAGE.md byte-identical (deterministic, counts only). 5/7 matrix features classed MONEYLINE_FEATURE_PRETENDING; weather/umpire NOT_PIT_AVAILABLE; standalone path recommended over widening funnel.
- Dispatched: Opus methodology review of TOTALS_METHODOLOGY.md (targeted packet); W10 factory-scale prep design lane (Sonnet). Capture healthy.

## 2026-09-05 00:0xZ — totals methodology review: NOT APPROVED (89ecfc3)
- Worst: V7 §2.3 over/under split is a settlement read framed as market structure → must be registered as a partially-read member. De-vig at modal line selects on book attribute → per-line fair prob with >=3-book floor. Integer vs half-point lines are different estimands. Closing line PIT-computable with staleness bound + snapshot commence_time. Validation items 7-13 added (mirror F5 B3/M1/R2).
- Dispatched Sonnet amendment lane (docs only); re-review follows. Capture healthy.

## 2026-09-05 00:4xZ — totals methodology APPROVED TO DRAFT HYPOTHESES (6fc4e4e)
- Revision 2 faithful; 5 open items decided (population-shift on bucket occupancy; family of two; bullpen recombination deferred; staleness bound from gap distribution then frozen; B6 counts-only population audit required before registration).
- Queue extended W15-W17. W15 dispatched (Sonnet). W10 factory prep still running. Capture healthy.

## 2026-09-05 01:0xZ — W10 factory scale design + slice 1 landed (b5d5f19)
- Canonical wager id (game_pk, market, side, line), append-only WagerStore, overlap/Jaccard/effective-N module; 4,387 tests green in lane. Overlap report honestly reports that sweep output does not yet persist per-strategy decision sets → W18 queued and dispatched.
- W15 totals population audit running. Capture healthy.

## 2026-09-05 01:3xZ — W15 totals population audit landed
- Joint denominator (>=3-book per-line floor AND half-point modal line, at closing): 2023 1,321 / 2024 1,320 / 2025 1,280 (tuning-only). Half-point restriction halves the population (2,402 → 1,321). Closing gap p50 ~85 min, p90 ~325-350 min, proposed staleness bound 6h (quantile rule, frozen before any split re-measure).
- Anomaly: 384/566/874 "rescheduled" games per season — implausible; W19 dispatched to characterise commence_time jitter before the closing definition is frozen. W16 eval path dispatched in parallel (closing definition parameterised). W18 running.

## 2026-09-05 02:0xZ — W19 reschedule audit landed
- Deltas are sub-15-min, both-signed, clustered at 5/10/15/60 min → provider jitter, not reschedules. No PIT schedule store exists to cross-check (reported unjoinable). Anchor stays the self-referential per-snapshot commence_time (leak-proof). W16 default anchor constant confirmed. W16, W18 still running.

## 2026-09-05 02:4xZ — W18 factory slice 2 landed (11dea8b, reclaimed)
- Lane stalled waiting on a test monitor; I ran the fast suite in its worktree (4,051 green) and committed path-specifically. Headline: 8,811 sweep strategies → 6,050 unique wagers (dedup ratio 0.0006 of decisions), 1,062 Jaccard>=0.8 families. Direct answer to "why not 100,000 systems": most of the existing population is duplicates of ~1,000 distinct behaviours.
- W16 totals eval path still running. Capture healthy.

## 2026-09-05 03:2xZ — W16 totals eval path landed; audit reconciled at 6h
- W16: totals_rows/totals_eval mirror f5_eval; 48 tests; full suite 4,441 green in lane. Real dry_run: joint 1,295/1,284 vs audit 1,321/1,320 — cause: audit hardcoded 12h while B5 froze 6h. Audit re-run at 6h (1bec5ae): 1,316/1,313. Manifest: 1,295+1,284 joint + 50 not-joined-to-settlement = 2,629 = audit 1,316+1,313. Reconciled exactly.
- The 50 unjoined events must be characterised before freezing (F5 precedent: AZ/ARI join bug hid two seasons). W20 dispatched. W17 prereg draft dispatched in parallel (denominator placeholders). Manifest NOT frozen.

## 2026-09-05 04:0xZ — W17 totals prereg DRAFT landed
- Two members: M1 full-population OVER calibration (disclosed partially read), M2 combined-starter-groundball-share terciles. Gaps surfaced, not hidden: M1 proposed floor below its own 2.71pp MDE; M2 real n unknown (no feature∩price join yet); M2 has no evaluation code. W21 dispatched for the M2 join (counts only). Opus review of the draft waits on W20 (unjoined events) and W21. Capture healthy.

## 2026-09-05 04:3xZ — W21 M2 coverage landed
- Real M2 n (feature both sides ∩ price-gradeable): 2023 792/1,295 (61%), 2024 1,090/1,284 (85%) — 24pp coverage shift; 2024 tercile occupancy under 2023 edges fails uniformity (χ²=18.34, p=0.0001) on FEATURE-SIDE counts alone; per-tercile MDE 5-6pp. As drafted M2 is a pre-determined POPULATION_SHIFT_FAIL (F5-H2 precedent). Passed to the Opus review to decide (reframe vs drop) once W20 lands. Capture: 23:16Z run in flight.

## 2026-09-05 05:0xZ — W20 unjoined audit landed; Opus review of totals prereg dispatched
- 50 unjoined: 30 postponed, 14 postseason (mlb_results.csv regular-season only → denominator-definition question for the reviewer), 5 doubleheader nightcaps past pricepath's 3h bound (fixed locally in totals_rows, regression test), 1 All-Star. Joint 2,579→2,584. Manifest still NOT frozen pending review (postseason inclusion, M2 fate).

## 2026-09-05 05:4xZ — totals prereg methodology review landed
- Regular season only (1,296/1,288); M1 floor 3.0pp with the 0-3pp band explicitly "cannot tell"; M2 demoted to a pre-determined POPULATION_SHIFT_FAIL evaluated exploratory and excluded from m; confirmatory family = M1 alone, m=1, no multiplicity credit claimable; new admissibility rule |Δ join rate| <= 10pp for any partition member; even a SURVIVOR cannot promote without an independent forward leg. Nine code items bound. W22 (code) and W23 (final spec) dispatched. Capture healthy.

## 2026-09-05 06:5xZ — W22 code + W23 spec landed; totals universe manifest frozen
- W22: nine bound items implemented; lane suites 4,134 fast / 4,482 full green; here test_totals_rows OK. Universe manifest written (regular season, 1,296/1,288, ledger reconciles: 14 postseason, 1 All-Star, 30 postponed, 169 no-closing, 2,175 not-joint). Real dry_run passes both hash guards. Family NOT frozen. Adversarial review dispatched (Opus). Capture healthy.

## 2026-09-05 07:3xZ — W11 reasoning-loop audit landed
- No outcome coupling found across five attack vectors; gap was test coverage only. Pinned: a WIN with a refuted mechanism grades REASONING_WRONG at settlement and classifier layers. docs/REASONING_LOOP_AUDIT.md. Totals adversarial review still running. Capture healthy.

## 2026-09-05 08:1xZ — totals adversarial review: FAIL (35e0beb)
- Blocking: B-A1 prereg_spec_sha256 unbounded (moves on append; starts in DRAFT text); B-A2 book-count bucket occupancy specified but not built. Must-fix: M-A1 freeze record omits numeric gates / floor not cross-checked at run; M-A2 three conflicting CANNOT_TELL precedence orders (implemented one absorbs a fatal battery flag); M-A3 run_full_evaluation happy path untested. Clean: pooled-rows, manifest, anchor, dry_run, freezes. Fix lane dispatched (Sonnet). Capture healthy.

## 2026-09-05 08:5xZ — totals family registered and evaluated: ZERO survivors
- Adversarial re-review PASS (0346858; N-B1 pinned in tests). Confirmatory family frozen (m=1, spec sha 056e7352…, both universe hashes). Evaluation run committed.
- M1: 2023 screen −1.14pp (Under-favouring, below 3.0pp floor); 2024 +0.72pp p=0.617 CI [−2.04, +3.50] (sign flip, CANNOT_TELL band); pre-registered population-shift gate fatal on BOTH bucketings (line χ²=281.7; book-count χ²=367.7) → POPULATION_SHIFT_FAIL; battery extreme_removal fatal; integer stratum report-only 0.514/0.490. M2 POPULATION_SHIFT_FAIL as pre-determined.
- Gate-design lesson for the NEXT family (not a rescue): line-bucket occupancy shift measures league scoring drift between seasons, not sample comparability. Results doc lane dispatched. No thresholds touched.

## 2026-09-05 10:0xZ — W25 factory lifecycle landed; W26 lesson landed
- Lifecycle state machine (admit refuses near-duplicates of RETIRED families; promote structurally gated). Dry run on persisted evidence: all 1,062 families RETIRED — the historical ML genome population has no surviving evidence, consistent with the earlier noise-ceiling adjudication. Queue now drained except BLOCKED_HUMAN items (W2 secrets, W4 comparator) and the Monday handoff. Capture healthy.

## 2026-09-05 03:3xZ — capture-health false OVERDUE (overnight, no games in window)
- Helper reported OVERDUE age=93m while the runner executed and committed at 03:16Z with "stopped early: no game inside the window". Artifact age is the wrong liveness signal outside game windows; a heartbeat-based fix lane (Sonnet) dispatched. Capture itself is healthy; no ESCALATE; no research stopped because the evidence shows the runner alive.

## 2026-09-05 04:0xZ — capture-health heartbeat fix landed
- Helper now uses the latest "Forward capture" commit as a heartbeat; live: HEALTHY_IDLE decided_by=heartbeat. 5 regression tests.

## 2026-09-05 10:4xZ — daily loop ESCALATE ×3: root cause found, slate re-run
- Slate refused 09-04 and 09-05: src/cli.py runs preflight.check on L1 BEFORE run_slate refreshes L1; and the mtime shortcut had disabled live projection since 09-03 18Z (all 58k live observations were unprojected). Repaired L1 by the production l1.run path (idempotent); today slate exit=0, decisions recorded. 09-04 stays a gap (no decisions → settle/eod refuse, correctly). Fix lane dispatched (refresh-before-preflight + durable projection marker + regression tests). Capture healthy; container restarted once at ~10:12Z (my L1 probe was killed), no data lost.
