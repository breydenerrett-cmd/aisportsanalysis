# The loss post-mortem

Answers, for every settled bet: what happened, where the game turned, and
which of three things caused the result. Built 2026-09-04.

Modules: `src/pipeline/gameflow.py` (the data), `src/review/postmortem.py`
(the analysis), `src/providers/mlb.py` (`fetch_play_by_play`,
`fetch_win_probability`, `parse_play_by_play`).

CLI:

```
python3 -m src.cli gameflow --date 2026-09-02          # ingest (free)
python3 -m src.cli gameflow --date 2026-09-02 --games 824470,824312
python3 -m src.cli gameflow --backfill 2026-08-01..2026-09-03
python3 -m src.cli postmortem [--date D] [--out FILE] [--losses-only]
```

## Part A: the data

`data/processed/gameflow_<yyyy>.jsonl`, append-only, resumable by `game_pk`.
One `type="play"` row per completed plate appearance (inning, half, pre-play
outs and base state, batter, pitcher, event, description, running score,
MLB's win probability and WPA, leverage index) and one `type="game"` row per
game, written last, carrying `wp_available`, the final score, the probables
and the pitchers who actually started.

Source: `statsapi.mlb.com/api/v1/game/{pk}/playByPlay` and
`/winProbability`. Free, keyless, **zero odds credits** at any volume.

### This data never reaches the decision path

Every row describes something that happened during the game it belongs to, so
a decision that could read it would be reading the outcome. Four guards:

1. The filename is `gameflow_*`, not `boxscores_*`, so
   `settle_slate.BOXSCORES_GLOB` cannot sweep it up.
2. `src.core.asof._default_stores()` does not register it, so `as_of()`
   cannot surface it at any T.
3. `tests/test_gameflow_pit.py` proves 1 and 2 by injection — a full game's
   flow is planted in a redirected data root and the snapshot must stay
   byte-identical — plus a positive control proving the same payload DOES
   move a snapshot when written into a store `as_of` does read.
4. The same test walks the import graph of the decision-path modules and
   fails if any of them imports `src.pipeline.gameflow`, and asserts the
   ingest writes no credit-log row and hits only the MLB host.

## Part B: the post-mortem

### 1. What happened

Final score, plate-appearance count, lead changes, and when the game stopped
being in doubt: the last play after which the eventual winner's own win
probability never fell below 50% again (or, without a WP series, the last
play after which its lead never returned to level or behind). The basis is
printed with the claim.

### 2. The pivot

The single play with the largest swing **against our selection**, plus the
half-inning with the largest aggregate swing (a five-run inning arrives as
five separate plate appearances, none individually the largest).

Two metrics, and the choice is never silent:

| metric | used when | reads like |
| --- | --- | --- |
| `win_probability` | the bet settles on the full-game winner (`h2h`) **and** MLB served a WP series | `win probability 76% -> 0%` |
| `run_margin_proxy` | any other settlement rule, or no WP served | `run margin (PROXY) +1 -> -1` |

The proxy is defined in `_margin_series` and is a pure function of the score:
runs ahead for `h2h`; the same frozen after the 5th for `h2h_1st_5`; distance
to the line for `totals`. It is **not** a probability, is never rendered as a
percentage, and every post-mortem using it carries "PROXY" in its
limitations. Nothing anywhere models, interpolates or borrows a win
probability.

Ties break to the **later** play: two plays that moved the game equally far
against us are not equally decisive, because the later one had less game left
to undo it.

### 3. The verdict — the fixed rule

Ordered; first match wins; every branch names the stored fact it fired on.
Implemented in `postmortem.classify`, tested in
`tests/test_review_postmortem.py`.

**R1 — INFORMATION_MISSING.** Something knowable-but-unknown to us decided
it. Fires on either:

- the `ReviewRecord` carries `late_information` or `missed_information` (a
  real `InformationEvent` landed after the decision was frozen — this is the
  `degraded_information` / assumption-exposure signal already on every
  record), or
- **late scratch**: the decision's `assumption_exposure` shows it was
  assuming a probable pitcher, and the pitcher who actually took the ball
  (read off the first play of the half-inning) is not that probable.

Checked first on purpose: if the board we decided on was wrong, neither of
the other verdicts is a claim we are entitled to make.

**R2 — REASONING_WRONG.** The thing the pick was built on is what failed.
Requires the decision to have made a claim a game could contradict, and the
game to have contradicted it:

- `thesis_outcome == "REFUTED"` (a recorded mechanism check came back
  refuted), or
- `counterargument_realized` is non-empty (a counterargument the decision
  itself wrote down actually happened).

Note what is **not** in R2: losing. Losing is not evidence the reasoning was
wrong, and treating it as such is the back door this whole module is built to
keep shut.

**R3 — VARIANCE.** Everything else: the reasoning held, or made no claim, and
the game turned on something the pick never predicted. Qualified:

- `mechanism_confirmed` — checks existed and all held. Real variance.
- `no_falsifiable_mechanism` — no checkable claim was made at all, so the
  result carries **zero** information about the thesis. This is a statement
  about the thesis, not a defence of it, and the report says so in the
  limitations of every affected post-mortem.

**What separates VARIANCE from REASONING_WRONG** is a single question: *did
the decision name something a game could contradict, and did the game
contradict it?* Not "did we lose".

### 4. What it suggests researching

Only a signature appearing in ≥ `MIN_PATTERN_N` (3) losses, covering ≥
`MIN_PATTERN_SHARE` (25%) of them, at ≥ `MIN_PATTERN_LIFT` (2×) its rate in
the won control. Below that floor the report says "one game is an anecdote"
and suggests nothing. The lift term is the important one: a property present
in half our losses and half our wins describes the games we bet, not the bets
we lost.

Every output is a question to prespecify and test on unseen data.
`_REFUSED_SUGGESTION_TERMS` drops any sentence that drifts into being a
parameter change.

## The two honesty constraints

**A post-mortem is a description, never evidence for a strategy change.**
`docs/RESEARCH_CATALOGUE.md` T8 ("no rescue by threshold change") applies with
full force: this artifact is written after the outcome is known, on the games
we happened to lose, with the outcome in hand. It is the most overfittable
thing this system can produce.

**The win control is not optional.** `build_postmortems` runs the identical
classifier over won bets by default, and the rendered table puts the two
columns side by side. A process pointed only at losses manufactures exactly
one story — our reasoning was fine, we were unlucky. When one verdict class
holds every loss *and* every win, `render_section` prints a WARNING saying the
classifier separated nothing.

## Known state, 2026-09-04

Run over all 114 joinable settled decisions (52 losses, 62 wins) across
2023-04-18, 2026-08-31, 2026-09-02 and 2026-09-03:

- every one landed in `VARIANCE (no_falsifiable_mechanism)`;
- because **no system in the ledger records a mechanism check**
  (`settle_slate.build_review_for` writes `mechanism_checks=()` and says so),
  so no loss could ever have been classed REASONING_WRONG;
- and no `InformationEvent` exists for these games, so none could have been
  classed INFORMATION_MISSING either.

That is a real finding and the report prints it as a warning rather than as
reassurance. The gap it exposes is in what the systems write down at decision
time, not in any parameter. Until a thesis records a mechanism check, this
classifier cannot tell "the reasoning held" from "the reasoning was never
testable".

### Update (2026-09-04): the checks now exist

`settle_slate.build_review_for` no longer writes `mechanism_checks=()`. It
EVALUATES the post-game predicates a decision froze at decision time
(`src.engine.mechanism_predicates`, pre-registered in
docs/PREREG_MECHANISM_CHECKS.md) against the game's own play-by-play, via
`src.review.mechanism_eval`. A third VARIANCE qualifier,
`mechanism_undetermined`, distinguishes "the claim was made and the game
could not decide it" from both "it held" and "there was no claim".

The numbers above **do not change**, and that is correct rather than a
failure: every DecisionRecord in the ledger is frozen inside a hash chain and
carries no predicate, so those 114 decisions genuinely made no claim a game
could refute. Separation begins with the first slate decided after the change.
Applying the re-derived predicate to the 31 of those decisions whose frozen
thesis names its fired signal -- a BACKFILL, explicitly not a
pre-commitment -- moves the same corpus to 5 REASONING_WRONG / 3
`mechanism_confirmed` / 28 `no_falsifiable_mechanism` among losses against 14
/ 6 / 32 among the won control, which is what the classifier separating looks
like. That REASONING_WRONG is commoner among WINS there is the point: a
mechanism check is scored on the mechanism, never on the bet.

Independently of any pick, the check machinery was measured on all 284 real
games in the play-by-play store, all six predicates, both sides -- 3,408
evaluations: 1,601 confirmed, 1,588 refuted, 219 undetermined. The layer
decides most games and says so honestly when it cannot. The near-even
confirmed/refuted split is a property of a baseline derived near the league
median (docs/PREREG_MECHANISM_CHECKS.md says so in advance) and is not a
finding about any mechanism.

44 further settled reviews could not be examined: they carry pre-B4 4-field
`decision_key`s (no `system_id`, see `factory.scorecard.decision_key_for`)
that match several systems' wagers at the same instant. They are skipped with
the ambiguity recorded, never resolved by guessing.
