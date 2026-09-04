# Reasoning-loop audit: does outcome ever leak into the mechanism grade?

Red-team pass over `src/engine/mechanism_predicates.py`,
`src/review/mechanism_eval.py`, `src/review/postmortem.py`,
`src/pipeline/gameflow.py`, `src/engine/explain.py`,
`src/board/readable.py` against the five attack vectors in the mission.
Method: read every function on the settlement path for an outcome/pnl
parameter, then prove or disprove each finding by constructing a WIN with a
refuted mechanism and a LOSS with a confirmed one and running them through
the real code.

## Findings

| # | Attack vector | Verdict | Status |
|---|---|---|---|
| 1 | Verdict/predicate grade depends on won/loss/pnl instead of frozen predicate vs. facts | No defect found | REPRODUCED (negative result) |
| 2 | A WIN suppresses a post-mortem | No defect found | REPRODUCED (negative result) |
| 3 | A predicate is unfalsifiable as frozen | No defect found | REPRODUCED (negative result) |
| 4 | Sample sizes not shown with thesis claims in readable output | No defect found | REPRODUCED (negative result) |
| 5 | A settlement-time predicate uses price/result instead of in-game facts | No defect found | REPRODUCED (negative result) |
| 6 | Missing pinning test: WIN + refuted mechanism | Real test gap | FIXED |

Detail:

**1. Outcome leaking into the grade.** `mechanism_eval.evaluate` /
`_verdict` / `_measure` take only `(predicates, flow)` — no function in
that module accepts `settled`/`outcome`/`won`/`result`/`pnl`, pinned by
`tests/test_mechanism_checks.py::TestTheCheckNeverSeesTheBet` via
signature inspection. `compute_thesis_outcome` (`src/ledger/records.py`)
does read `settled`, but only *after* the refuted/confirmed split: `any
refuted -> REFUTED` fires before the win/loss branch is ever reached, so
outcome only decides CONFIRMED-vs-VARIANCE among mechanisms that already
held — it never turns a refuted mechanism into anything else. Verified by
constructing a WIN whose mechanism check comes back refuted
(`away_lineup_game(2)`, 2-of-18 reached-base against a 0.3245 league
floor) and running it through the real settlement path
(`build_review_for`): `thesis_outcome` is `REFUTED`, not `CONFIRMED`.
`postmortem.classify` checks `thesis_outcome == "REFUTED"` before ever
looking at `checks`, independent of `review.settled`.

**2. WIN suppressing a post-mortem.** `build_postmortems` defaults
`outcomes=("loss", "win")` and `summarize` reports `win_verdicts` beside
`loss_verdicts`; `render_postmortem` renders a `(WON -- control)` tag
rather than skipping. No code path filters wins out of `classify()`.

**3. Unfalsifiable predicate.** All six `PREDICATES` compare a measured
rate/share to a held-out league baseline or to zero (`top_minus_bottom`),
each gated by a `min_sample` floor below which the verdict is
`UNDETERMINED` rather than a forced PASS — `_verdict` never coerces a
thin sample. The `gt_zero` comparison additionally treats an exact tie as
`UNDETERMINED`, not a pass, closing the one edge that could otherwise
never fail. None of the six measures reads price, line, or the pick's own
side beyond which team the predicate is *about* (a decision-time fact,
not the outcome).

**4. Sample sizes at every thesis claim.** `mechanism_eval.evaluate`
formats `observed` as `"<value> over <N> observation(s) of <subject>"`
for every row, and `mechanism_predicates.predicates_for` freezes
`away_sample`/`home_sample` from the decision-time feature onto the row.
`postmortem.render_postmortem` prints `observed` verbatim for every
check, so a reader sees the sample size next to every claim without
needing to open the code.

**5. Settlement-time predicate leaking price/result.** `mechanism_eval`
never imports `src.providers.odds`, never reads `price_american`, `line`,
or `settled`; it reads only `gameflow.load_game(...)["plays"]`
(pitcher/batter ids, event types, half-inning) — in-game facts available
the instant the final out is recorded, before settlement even looks at
the bet's own result. The narrative "pivot" in `postmortem.py` does use
`line` (for the run-margin proxy metric), but that is cosmetic
storytelling about *when the game turned*, not part of any mechanism
predicate's PASS/FAIL rule, and is documented as a labelled PROXY.

**6. Test gap (real, fixed).** The suite already pinned "loss + refuted
-> REASONING_WRONG" and "loss + confirmed -> VARIANCE", and pinned that
identical inputs give identical verdicts across win/loss when *no*
mechanism check exists. It never pinned the sharper case the mission
specifically calls out: a bet that **won** while its mechanism was
**refuted**. That is exactly the case a careless implementation would get
wrong (grading REASONING_WRONG only ever seemed to apply to losses in
practice, since a refuted mechanism usually loses). Added:

- `tests/test_mechanism_checks.py::TestSettlementWiring::test_a_win_with_a_refuted_mechanism_is_still_reasoning_wrong`
  — full settlement wiring (`build_review_for`), asserts `verdict=refuted`
  and `thesis_outcome=REFUTED` on a `SettledBet(outcome="win")`.
- `tests/test_review_postmortem.py::TestVerdictRuleReachesAllThreeClasses::test_a_win_with_a_refuted_mechanism_is_reasoning_wrong_not_confirmed`
  — classifier level, asserts `VERDICT_REASONING_WRONG` on `make_review("win", mechanism_checks=REFUTED_CHECK)`.

Both pass against current code (no fix needed there) and would fail if
`compute_thesis_outcome` ever moved the `settled == "win"` branch ahead of
the `any(refuted)` check, or if `classify()` ever special-cased `settled`.

## No fixes required

No REAL bug was found in the reasoning/mechanism loop itself. The design
already separates prediction (`mechanism_predicates`, decision path,
price-blind) from measurement (`mechanism_eval`, settlement path,
outcome-blind) from classification (`postmortem.classify`, reads only
`thesis_outcome`/`counterargument_realized`/`late_information`, never
`settled` directly). The one gap was in test coverage, not code, and is
closed above.
