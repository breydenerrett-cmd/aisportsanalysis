# Coach report card (practice lane)

Owner, 2026-10-18: *"we need self improving even if the suggestions aren't changed that day we can grade the
suggestions from coach and see if the coach is actually coaching."*

The pre-registered champion/challenger loop (`docs/PREREG_LEARNING_LOOP.md`) needs 50 graded forward bets on a
hound before a coach proposal can even become a challenger, then 100+ paired games before the referee looks.
That is weeks of nothing visible. The report card is a **separate practice lane** that runs beside it: every
valid coach suggestion is recorded and **graded by code** (no model) against the hound as it stands, in two
ways, and the grades are published. It never feeds the referee, never changes a hound, and never places or
sizes a bet. Paper only, not advice.

## The flow

1. The weekly coach Zap (`docs/ZAPS.md`) files a GitHub issue titled `Coach proposal: <hound>` with a
   ```` ```json ```` block `{"hound","params","hypothesis","evidence"}`.
2. `python -m src.hounds.coach_intake --source api --grade` runs in the capture slot on GitHub Actions. It
   reads the **public** issues API (no token needed; `GITHUB_TOKEN` is used only for rate limits if present),
   keeps issues authored by `breydenerrett-cmd`, skips pull requests, and never re-records an issue number.
3. Each issue is judged by the same validators a hand-typed proposal meets (`tunables.validate`: bounds, step
   grid, 1 or 2 knobs; hypothesis and evidence text rules).
   * invalid: a `coach_refused` row with the reason. Bad coaching counts against the coach.
   * valid: a `coach_suggestion` row. If the hound is **challenger-eligible** (50 graded forward bets, cooldown
     passed, caps clear) and `propose_pack` accepts it, a real shadow challenger is also recorded
     (`proposed_by: zapier-coach`) and the row says `mode: challenger`; otherwise `mode: practice`.
   * rate limit on practice rows: at most 1 per hound per 3 days and 3 per UTC day. Extra issues get
     `coach_refused` with `too_soon_practice`.
4. Grading (code only):
   * **Hindsight**: the hound with the champion's values and with the suggested values, replayed over the
     stored boards of the 30 days before the suggestion and settled by the normal settler. Labelled hindsight
     everywhere because the coach could see that period. It is instant and it is **not evidence**.
   * **Forward** (the honest one): from the suggestion's recorded time on, both value sets run in shadow on new
     boards (same engine, same games, same prices, the rule's lock) and settle as games finish. One row per
     suggestion, updated when the numbers move.

Ledgers (both under `evidence/`, which the capture slot stages wholesale and the production image copies):

* `evidence/hounds_coach_v1.jsonl`: hash-chained (`src/ledger/chain.HashChainLedger`). Kinds
  `coach_suggestion`, `coach_refused`, `coach_graded_hindsight`, `coach_graded_forward`.
* `evidence/hounds_coach_shadow_v1.jsonl`: hash-chained pack-ledger rows of the shadow runs. Two ids per
  suggestion, `coach-<issue>-champion` and `coach-<issue>-suggested`. Not a public source for the race.

## Why both sides run in shadow

The real champion's bets live in the house ledger. Comparing a shadow suggestion with them would mean any game
the shadow runner missed (a skipped slot) looks like "the suggestion passed", which flatters or punishes it by
accident. Running the champion's values in shadow too puts both sides in the same world: a missed game is
missed by both, so it is no slot at all.

## The forward decision rule (written before the code)

A **slot** is one game on which at least one of the two shadow runs bet, and where every bet that was made has
settled (a win, a loss or a push; pending, void and unresolved bets wait). A side that passed on a slot
counts 0 units there.

* `d` for a slot = units the suggested values won on it minus units the champion's values won on it, at the
  board-average price, stake 1.
* `n` = the number of settled slots ("paired settled bets").

The label:

| Condition | Label |
|---|---|
| `n` is under 20, or the slots cover fewer than 3 different slate dates | **TOO EARLY** |
| otherwise, the 90% interval for the mean of `d` is entirely above 0 | **HELPED** |
| otherwise, the 90% interval is entirely below 0 | **HURT** |
| otherwise | **NO DIFFERENCE** |

The interval is a **date-clustered percentile bootstrap**: resample the slate dates with replacement (as many
dates as there are distinct dates), take every slot of each drawn date, compute the mean of `d`; do that
2,000 times with a fixed seed (the issue number, so a re-run gives the same answer) and take the 5th and 95th
percentiles. Slots on one date are resampled together because games on one night share weather, the same
slate and the same news, so they are not independent.

Reported beside the label and never used for it: bets on each side, units on each side, the sum of `d`, and the
closing-line difference on games both sides bet (`clv_diff`, mean of suggested minus champion where both bets
have a measurable close).

Where the knobs only tighten a threshold the suggested values bet a subset of the champion's games, and the
slots where only the champion bet carry the whole signal; that is why a slot, not "games both bet", is the
unit. Hindsight reports the both-bet subset too, labelled as such.

This rule is not a promotion rule. A HELPED label is a note on a suggestion, not a reason to change a hound;
the referee alone promotes, on its own pre-registered numbers.

## The summary

`GET /hounds/coach/report` (and the "Is the coach any good?" panel on `web/learning.html`) shows: tips made,
tips refused, tips with a verdict, how many HELPED / HURT / NO DIFFERENCE / TOO EARLY, the total forward units
difference, the total hindsight units difference (labelled hindsight), and the last 20 tips, each in one plain
line: *"Coach told Steamy Setter to change X from 3.0 points or more to 4.0 points or more. Hindsight: +2.1u
better. Live: too early (3 bets)."*

## Hard lines

Paper only. Not advice. 21+. No claim of an edge or of profit: a HELPED tip is a paper result on a small number
of games. No bet-placement capability exists anywhere in this lane, and `ranker Engine 2` stays gated.
