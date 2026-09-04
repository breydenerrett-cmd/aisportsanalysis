# Weekend queue — source of truth

Statuses: READY RUNNING VERIFYING DONE BLOCKED_HUMAN BLOCKED_EXTERNAL
FAILED_RETRYABLE FAILED_TERMINAL DEFERRED. One task RUNNING per lane.

| ID | Pri | Task | Depends | Runtime | Status | Evidence required | Files | SHA | Blocker |
|---|---|---|---|---|---|---|---|---|---|
| W0 | P0 | Verify F5 freeze independently from persisted data | – | bash/python (parent) | DONE | recount + hash match + test | docs/F5_UNIVERSE_FROZEN.md, tests/test_f5_universe.py | ed0373f (verified 21:20Z) | – |
| W1 | P0 | Canonical capture-health helper: RUNNING/HEALTHY_IDLE/OVERDUE/FAILED/UNKNOWN from artifacts+heartbeat+lock, no self-matching pgrep; CLI + regression tests | – | Sonnet | DONE | tests green; CLI output on live state | src/capture/health.py, tests/test_capture_health.py, scripts/capture_health.sh | 309cc38 | – |
| W2 | P0 | Capture externalization cutover (GitHub Actions) | repo side done 04d1e4f | owner | BLOCKED_HUMAN | one external commit lands | .github/workflows/forward-capture.yml, docs/CAPTURE_EXTERNALIZATION.md | 04d1e4f | needs ODDS_API_KEY Actions secret + default-branch reachability |
| W3 | P0 | Opus methodology review: A/B/C family-scope decision + hard calls 1-6 | W0 | Opus (review only) | DONE | dated review section + VERDICT line | docs/PREREG_F5_FAMILIES.md | 073ef4d (VERDICT: READY AS AMENDED; scope A) | – |
| W4 | P1 | Full-game ML T-2h comparator purchase (~4-5k credits) so B3 becomes testable; reviewer measured 0/3,682 owned snapshots within tolerance (median 81 min off) | W3 | owner | BLOCKED_HUMAN | – | docs/PREREG_F5_FAMILIES.md §Family-scope | – | Q: authorize ~4-5k historical_backfill credits for a T-2h full-game ML comparator (same frozen rule as F5)? Safe default: do not buy; H1/H2 proceed without it. |
| W5 | P0 | Finalize prereg per review; adversarial prereg review; then register_family | W3 | Sonnet + Opus adversarial | DONE — adversarial PASS (8371058), R1/R2 fixed (5dc74e8), family frozen | review pass + register_family record | docs/PREREG_F5_FAMILIES.md, data/research/f5/ | – | – |
| W6 | P0 | Build + PIT-validate F5 calibration evaluation path (standalone per review; items 1-6, A1 tie audit, A3 price hash) | W3 | Sonnet | DONE | tests incl. leakage fixture | src/research/f5_eval.py, tests/test_f5_eval.py, scripts/f5_tie_audit.py, docs/F5_TIE_AUDIT.md | db6eef8 | – |
| W7 | P0 | Preregistered discovery (2023) → replication (2024) → FDR → battery, all outcomes recorded | W5, W6 | bash/python | DONE — 0 survivors (H1 SCREEN_FAIL; H2-bottom/top POPULATION_SHIFT_FAIL) | results JSON + every hypothesis recorded | data/research/f5/, docs/F5_RESEARCH_RESULTS.md | – | – |
| W8 | P0 | docs/F5_RESEARCH_RESULTS.md post-mortem (nulls first-class) | W7 | Sonnet | RUNNING | doc complete per directive list | docs/F5_RESEARCH_RESULTS.md | – | – |
| W9 | P1 | Totals feature-legitimacy audit: legit run-environment vs ML-pretending; methodology before search | W7 | Sonnet (+Opus review) | READY | audit table + methodology doc | docs/TOTALS_METHODOLOGY.md | – | – |
| W10 | P1 | Factory scale prep: canonical wager store, strategy→wager refs, unique-wager counts, correlation clustering, retire/mutate/replace framework | – | Sonnet | DEFERRED | design + tests | src/evolab/, docs/ | – | – |
| W11 | P1 | Reasoning loop improvements (mechanism grading independent of W/L) | – | Sonnet | DEFERRED | tests | src/review/, src/engine/ | – | – |
| W12 | P1 | Daily-loop unattended validation review (refusal of bankroll-only promotion) | daily trigger | bash | READY (daily) | ESCALATE-free run + ledger check | scripts/daily_loop.sh | – | – |
| W13 | P0 | Weekend routine: hourly wake running the cycle procedure | – | trigger | READY | trigger updated | – | – | – |
| W14 | P1 | docs/WEEKEND_HANDOFF.md before Monday | all | parent | DEFERRED | doc | docs/WEEKEND_HANDOFF.md | – | – |
