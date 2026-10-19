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

## The fan lane

Fans can send a tip from any tunable dog's page (`POST /hounds/{id}/tips`, `src/hounds/fan_tips.py`; a tip is
a row in the app database and never changes a dog). The report card grades those tips **exactly like the coach's
suggestions** and publishes them in their own block, never mixed into the coach's numbers.

1. `python -m src.hounds.coach_intake --source tips` (the capture slot runs `--source api,tips --grade`, same
   120 s cap, same `|| true`) reads the site's public export, `GET <PUBLIC_BASE_URL or https://linehound.app>/hounds/tips/export?since=<iso>`,
   with `urllib`. `since` is a minute before the newest tip already recorded; tip ids dedupe the overlap.
   A site that has not shipped the export yet answers 404: intake prints one line and still does the other
   source and the grading.
2. Intake trusts nothing in the export. Each tip is validated again by `tunables.validate` against the dog's
   **current** champion (bounds, step grid, one or two knobs changed). An invalid tip is counted and **not written**.
   The nickname is cut down to letters, numbers and spaces (20 characters) and run through the site's text
   rules; anything left unusable is no nickname.
3. A valid tip becomes a `fan_tip` row (mode `fan`, the tip id, the nickname, the time the fan sent it, the
   time we recorded it). **A fan tip is never offered to `propose_pack`**: no challenger, ever, and nothing in the
   referee's ledger. Forward grading starts at the recorded time, as for the coach.
4. Limits at intake, counted by the UTC day the fan *sent* the tip, first come first served: at most
   `FAN_PER_UTC_DAY` (20) rows a day, and one row per (dog, values) a day. A repeat is a `fan_tip_count` row (the chain
   is append-only) that adds one to the first row's `count`; repeats take no slot of the 20.
5. Grading is `coach_grade` unchanged: a fan row carries a **synthetic key** in the `issue` field
   (`FAN_KEY_BASE` = 1,000,000,000 + a running number, far above any GitHub issue number), so hindsight and forward
   rows and the shadow ids (`coach-<key>-champion` / `-suggested`) need no second code path. Only the newest
   `FAN_FOLLOWED_MAX` (120) fan tips are followed live, so the slot's time budget holds; an older tip keeps its
   last grade.

`GET /hounds/coach/report` gains `fans`: `summary` (tips, how many fans sent them, HELPED / HURT / NO DIFFERENCE /
TOO EARLY, live and hindsight units), the latest 20 `items` (each with both grades), `helped_events`, and
`versus`: *"Coach vs the fans: the coach helped 2 of 5 graded tips, the fans helped 1 of 3 (live grades only)."* Hindsight
gets its own labelled line and never enters that one. The Training camp page shows it as "Fans vs the coach", and
`GET /hounds/{id}/tips` gives each graded tip a `grade`, which the dog page's tip list prints.

The kennel feed posts `🐶 Fan tip paid off: <nickname or 'a fan'>'s tweak to <Dog> is beating the dog (+x.xu, n bets)`
once, when a tip's live grade first turns HELPED (guid `kennel:fan_tip:<tip id>`, dated by that grade, numbers
frozen at that grade). A fan row does not move the coach card's own "last change" date.

## Hard lines

Paper only. Not advice. 21+. No claim of an edge or of profit: a HELPED tip is a paper result on a small number
of games. No bet-placement capability exists anywhere in this lane, and `ranker Engine 2` stays gated.
