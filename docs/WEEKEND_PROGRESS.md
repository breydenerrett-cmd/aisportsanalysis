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
