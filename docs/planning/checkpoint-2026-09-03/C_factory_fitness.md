# C — Strategy Factory loop: fitness/gates/promotion audit

Read-only audit, HEAD, `/home/user/aisportsanalysis`. No files modified.

## Q4. The loop, stage by stage

| Stage | Status | Evidence |
|---|---|---|
| GENERATE (candidates) | WORKING, but exhaustive enumeration, **not** evolutionary | `src/evolab/genome.py:466-567 enumerate_genomes()` walks signal count → feature combo → threshold ladder → combination rule → weights → routing via `itertools.combinations`/`product`. `genome.py:104`: "Phase B mutation tunes magnitudes freely; enumeration does not." Grepped `mutat|crossover|breed|offspring` across `src/evolab/*.py`: every hit is a docstring/comment naming mutation/crossover as a *future* phase (`ceiling.py:11-12`, `genome.py:8,104`) or an unrelated word ("mutates", "reproduce" re: determinism). **No mutation or crossover operator exists anywhere in the codebase.** |
| ANALYZE SLATE | WORKING (as a batch sweep, not a per-day slate scan) | `src/evolab/sweep.py:334 sweep_world()` and `:623 run_sweep()` evaluate the enumerated genome population against a `World` (real or placebo), using `src/evolab/cscv.py:102 cscv()` and `src/evolab/spa.py:115 spa_test()` for robustness (real computation, called from `sweep.py:812,815,818`). |
| SELECT BETS | NOT BUILT (as a factory stage) | `src/evolab/decide.py:214 decide()` / `:224 decide_with_reason()` picks one side for one genome against one `WorldView` — a decision primitive, not a "select today's bets from surviving systems" step. Nothing calls it from `cli.py`. |
| PAPER WAGER | SCAFFOLD ONLY (real code, zero callers) | `src/accounts/paper.py` — `PaperAccount`, `PaperAccountBook`, `settle_and_record()` are fully implemented and unit-tested, but grep shows the only importer anywhere in the repo is `tests/test_accounts_paper.py`. Nothing in `cli.py` or `src/engine/**` creates a `PaperAccount` or calls `settle_and_record`. |
| SETTLE | WORKING (separately, for the real prediction-log pipeline) | `src/board/settle.settle` (called from `paper.py:142`) and `cmd_grade`/`cmd_ledger` in `cli.py` settle logged predictions against results — but this is the human-run prediction/CLV pipeline (`src/pipeline/grading.py`), not the evolab factory's candidates. The two settlement paths never meet. |
| SCORE (fitness) | SCAFFOLD ONLY (real code, zero callers) | `src/factory/fitness.py` — see Q8. Only `tests/test_factory_fitness.py` imports it. |
| RETIRE | NOT BUILT | No retirement/demotion function found anywhere (`grep -rniE "retire|demot" src/` → nothing beyond LOCK's "withdrawal_automatic" *criterion name*, which is a boolean field a caller must supply in `gate_g_lock`/`lock_eligible`, not code that withdraws anything). |
| MUTATE | NOT BUILT | Confirmed above — no operator exists. |
| CREATE REPLACEMENTS | NOT BUILT | No function anywhere spawns a new genome from a failed/retired one; `enumerate_genomes` produces the whole space once, deterministically, not incrementally in response to a retirement. |
| RETEST | PARTIAL | The placebo/CSCV/SPA/battery re-evaluation machinery (`placebo.py`, `cscv.py`, `spa.py`, `battery.py`) is real and callable, and is exercised by `sweep.py`/`funnel.py`, but nothing drives it as a scheduled "retest a promoted system" loop — it's invoked ad hoc (by tests, and presumably by hand) not by `cli.py daily`/`season-end`. |

`src/cli.py` has no `season-end` subcommand at all (`grep "season-end" src/cli.py` → nothing). `cmd_daily` (`src/cli.py:1560-1720`) is a fixed 9-step loop — snapshot odds, ingest results, refresh pitcher logs, refresh bullpen, brief, settle, grade, settle My Bets, boxscores — confirmed by reading the full function body. **Zero of those 9 steps touch `src/evolab/**`, `src/factory/**`, or `src/accounts/paper.py`.** `grep -n "evolab" src/cli.py` returns exactly one hit, a comment at line 2029, not a call.

### What fitness.py / gates.py / paper.py actually implement

**`src/factory/fitness.py`** (328 lines): a frozen-dataclass *data model*, not a computation.
- `Fitness` (line 189) bundles 8 components: `economic`, `robustness`, `forward_survival`, `sample_sufficiency`, `price_resilience`, `falsification`, `multiplicity`, `bankroll`. Every field is a value the **caller must supply** (e.g. `cscv_pbo`, `spa_p`, `logloss_vs_market`) — the module does no measurement itself; it only validates ranges (`_require_unit_interval`, `__post_init__` checks) and structurally forbids collapsing to one scalar (no `.score()`, no `__float__`).
- `promotion_verdict(fitness)` (line 282): pure function, inputs = one `Fitness`, output = `PromotionVerdict(promote, reasons, positive_components, negative_components)`. Logic: refuses if bankroll is the *only* positive component; otherwise requires all 7 non-bankroll components positive (conjunctive gate). Does **not** compute any of the underlying numbers, does **not** read a store, does **not** decide which system enters the funnel.
- Callers: `grep -rn "factory.fitness" src/ tests/` → only `tests/test_factory_fitness.py`. **Only tests call it.**

**`src/factory/gates.py`** (628 lines): pure functions for the G-cadence/G0-G7 ladder plus LOCK.
- `gate_cadence`, `gate_g0_record_conformance` … `gate_g7_owner_signoff` (lines 75-408): each takes explicit keyword inputs (counts, booleans) and returns a `GateResult(gate, passed, reasons, inputs_hash)`. None read a clock, a store, or global state — inputs must be assembled and passed in by a caller.
- `gate_ladder(state)` (line 450): walks `GATE_ORDER` and stops at first failure; a gate absent from `state` auto-fails.
- `lock_eligible(scorecard, evidence)` (line 556) + `LOCK_CRITERIA` (line 488, hash-pinned): evaluates a candidate against 11 named criteria, returns a tier (`LOCK`/`NEAR_MISS`/`NOT_ELIGIBLE`/`NOT_PROMOTED`), never a probability.
- Does **not** compute any of the metrics it gates on (e.g. does not compute `live_snapshot_reproduces_days` or `n_forward_selections` — those must come from elsewhere).
- Callers: `grep -rn "factory.gates\|factory\\.gates" src/ tests/` → `src/engine/truncation.py:114,117` only *mentions* gates.py in a docstring ("GateResult-compatible... mirrors the shape of... `src.factory.gates`") and does not import or call it; the only actual import is `tests/test_factory_gates.py`. **Only tests call it** (truncation.py independently reimplements a same-shaped result, it does not call gates.py).

**`src/accounts/paper.py`** (313 lines): a real, working simulated-bankroll ledger.
- `PaperAccount`: `settle_and_record()` (line 218) settles one `PaperBet` via `src.board.settle.settle` (never re-implements settlement), updates `bankroll`, `peak`, `drawdown_max`, win/loss/push/void counts, appends a row to a `HashChainLedger` (tamper-evident, `src/ledger/chain.py`). `roi_units` (line 226), `close_day()` (line 233) computes per-day snapshots. `FLAT_1U` is the only enabled stake size — `kelly_stake()` (line 62) is a named stub that always raises, by design (S13), so it can never silently fall back to flat.
- `PaperAccountBook`: many `PaperAccount`s side by side, one per system.
- Explicitly documented (module docstring, lines 1-14) as *reporting only*: never feeds `objective()`, never decides promotion.
- Callers: `grep -rn "accounts.paper" src/ tests/` → only `tests/test_accounts_paper.py`. **Only tests call it** — no `PaperAccount` is ever instantiated by `cli.py` or by any pipeline code; there is no live paper-wagering loop.

## Q8. Fitness/promotion contract — what's actually computed, and where

| Metric | Status | Where | Feeds `promotion_verdict`? |
|---|---|---|---|
| Units / stake size | EXISTS | `src/accounts/paper.py:49 FLAT_1U`, `PaperBet.stake_units` | No — bankroll ledger is disconnected from `fitness.py` |
| ROI | EXISTS | `src/accounts/paper.py:226 roi_units` (paper ledger); also `EconomicComponent.realized_return` field on `Fitness` (declared, not computed) | Only as the `bankroll`/`economic` *fields*, and bankroll is explicitly never decisive alone (`fitness.py:282-329`) |
| Hit rate + n | PARTIAL | `PaperAccount` tracks `n_wins/n_losses/n_pushes/n_voids/n_settled` (paper.py:170-174); `SampleSufficiencyComponent.n_decisions`/`n_independent_clusters` are declared fields on `Fitness`, not computed by fitness.py itself | `sample_sufficiency.sufficient` feeds the gate, but the counts come from a caller, not from real settlement data connected to this path |
| Average odds | MISSING | not found anywhere in `factory/`, `accounts/`, or `evolab/` as an aggregate | no |
| Bankroll | EXISTS | `src/accounts/paper.py` (`bankroll`, `peak`) | Yes, as `BankrollComponent`, but by rule **never sufficient alone** (`fitness.py:296-310`, tested) |
| Max drawdown | EXISTS | `src/accounts/paper.py:169,198-199 drawdown_max`; also `BankrollComponent.drawdown_max` field | Only via bankroll (non-decisive) |
| Volatility | MISSING | no stdev/variance-of-returns computation found in `factory/`, `accounts/`, `evolab/` | no |
| CLV (not `late_move`) | EXISTS, separately | `src/pipeline/grading.py:184-201 _closing_line_value()`, `src/cli.py:1518 "CLV (the primary metric)"`. `late_move` is a distinct, separately-computed field in `src/model/discovery.py:219,254,258` (movement post-hoc), never mislabeled CLV — confirmed by reading both files; no cross-reference between them | **No** — CLV lives in the prediction/grading pipeline, not wired into `Fitness` at all; `EconomicComponent` has no CLV field |
| Calibration | EXISTS elsewhere | `src/core/calibration.py`, `src/evolab/placebo.py:878 calibration_error()` | No — not referenced by `fitness.py` |
| Historical performance | PARTIAL | `src/pipeline/history.py` (results store) feeds grading/CLV, not `Fitness` | no |
| Out-of-sample performance | PARTIAL (field only) | `ForwardSurvivalComponent.out_of_sample: bool` (`fitness.py:90`) — a boolean the caller asserts, no OOS split logic inside `fitness.py` itself; real OOS/backtest split logic lives in `cscv.py`'s `chronological_blocks` | Yes as declared field, but not computed here |
| Forward performance | PARTIAL (field only) | `ForwardSurvivalComponent.forward_selections`, `ledger_days`, `point_class` — declared fields, no forward-tracking code in this module | Yes as declared field |
| Price-degradation sensitivity | PARTIAL (field only) | `PriceResilienceComponent.survives_worst_book`, `survives_shrink`, `shrink_fraction` (`fitness.py:134-147`) — booleans/float the caller supplies; grep for "shrink" computation logic in `src/` outside `fitness.py`/`gates.py` docstrings found none | Yes as declared field, not computed anywhere |
| Season/month stability | MISSING | `grep -rniE "season.stab|month.stab|market.stab" src/` → zero hits anywhere in the codebase | no |
| Dependence on top wins | PARTIAL | `src/research/battery.py:314 _extreme_removal()` (leave-one-out / extreme-value removal check) is real and used by the falsification battery | Indirectly, via `FalsificationComponent.battery_verdict` |
| Falsification survival | EXISTS | `src/research/battery.py:468 run()` — real, versioned rule battery (`rules_fingerprint()` at line 455); `FalsificationComponent.survived` (`fitness.py:163`) reads `battery_verdict == "PASS"` | Yes — a declared component, positive/negative check implemented in `_component_positive` |
| Multiple-comparison status (FDR) | EXISTS | `src/research/funnel.py:662 _apply_fdr()` calls `family.benjamini_hochberg()` (real BH-FDR, line 674), sets `p_fdr`/`fdr_threshold`/`status="failed_fdr"` | `MultiplicityComponent` on `Fitness` mirrors this shape (`effective_tests`, `multiplicity_charge`) but is a separate declared struct — no code path found connecting `funnel.py`'s FDR output into a live `Fitness` object |

**Structural finding**: `Fitness` is a well-designed *contract* — its `promotion_verdict()` correctly refuses bankroll-only promotion (see test run below) and correctly requires every non-bankroll component to independently read positive. But every non-bankroll component's *substance* (CSCV PBO, SPA p, battery verdict, FDR charge, OOS flag, shrink survival) has to be computed elsewhere and hand-assembled into the dataclass by a caller that does not yet exist in this codebase — `grep` confirms no file other than the test suite ever constructs a `Fitness` object at all (`grep -rn "Fitness(" src/` → only inside `fitness.py`'s own type definition and `tests/test_factory_fitness.py`).

### Test run confirming bankroll-only refusal

```
$ python3 -m unittest tests.test_factory_gates tests.test_factory_fitness tests.test_accounts_paper tests.test_evolab_sweep -q
----------------------------------------------------------------------
Ran 95 tests in 16.246s

OK
```

Relevant test names (from `tests/test_factory_fitness.py`, all passing):
- `test_bankroll_only_positive_is_refused`
- `test_bankroll_negative_but_everything_else_positive_still_refused`
- `test_insufficient_sample_refuses_even_with_good_bankroll_and_economics`

## Ten hardest truths

1. There is no evolutionary loop. `enumerate_genomes` is exhaustive combinatorial enumeration; grep for mutation/crossover finds only comments about a future "Phase B" that was never built.
2. RETIRE, MUTATE, and CREATE REPLACEMENTS do not exist as code anywhere in the repo — not scaffolded, not stubbed, simply absent.
3. `cli.py` has no `season-end` command and `cmd_daily`'s 9 steps never touch `src/evolab/**`, `src/factory/**`, or `src/accounts/paper.py` — the "factory" is entirely disconnected from the thing that actually runs daily.
4. `src/factory/fitness.py` and `src/factory/gates.py` are real, well-tested, pure-function code, but their only caller in the entire repository is their own test file — production code never constructs a `Fitness` or runs the gate ladder.
5. `src/accounts/paper.py` is fully implemented (ledger, drawdown, ROI, hash-chain) but nothing ever instantiates a `PaperAccount` outside its tests — there is no live paper-wagering loop.
6. `promotion_verdict` does correctly refuse bankroll-only promotion (test-verified), but that correctness is moot while nothing feeds it real `Fitness` objects.
7. Most non-bankroll `Fitness` components (`ForwardSurvivalComponent`, `PriceResilienceComponent`) are just typed booleans/floats a caller must assert — the module validates shape, not truth.
8. CLV is real and correctly kept separate from `late_move` (the standing rule holds), but CLV lives in `src/pipeline/grading.py`'s separate prediction pipeline and is never wired into `Fitness`.
9. Season/month/market stability metrics do not exist anywhere in the codebase — not partial, not stubbed, zero hits.
10. FDR (multiple-comparison control) is genuinely computed in `src/research/funnel.py` via real Benjamini-Hochberg, and CSCV/SPA robustness is genuinely computed in `sweep.py` — these are the strongest pieces of real math in the loop, but they, too, terminate in `sweep.py`/`funnel.py` outputs that no code assembles into a `Fitness` object or the gate ladder.
