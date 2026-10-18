# Build-your-own hound (LineHound Hounds, user half)

A user hound is a **paper** strategy chosen from a fixed menu. The engine turns its rule into simulated
picks before each game starts, the picks go into a hash-chained public ledger, and results grade them.
Nothing here places or suggests a real bet; every payload carries `paper_only: true` and a not-advice
line. The house hounds, stats and the public leaderboard are the other worker's (`src/hounds/house.py`,
`stats.py`, `verdict.py`, `api/hounds.py`); this half owns creation, the user engine, settlement, and
the Houndmaster door.

Files: `src/hounds/user_spec.py`, `user_store.py`, `user_engine.py`, `user_settle.py`, `user_coach.py`,
`api/hounds_create.py`, `scripts/hounds_run.sh`, ledger `evidence/hounds_user_v1.jsonl`.

## The menu (what a hound is made of)

| Field | Choices |
|---|---|
| name | 3 to 24 chars, letters/digits/space/hyphen, unique, no profanity/brands/real team or player names |
| tagline | up to 80 chars, same filter |
| sports | MLB, NFL (one or both) |
| markets | moneyline, spread / run line, game total |
| side rule | favourite, underdog, home, away, over, under, the side the market moved toward since our first capture, the side the market moved away from |
| price band | shortest and longest American price. **Never -200 or worse**: the menu refuses it and the engine re-checks every bet |
| min books quoting | 1 to 10 |
| max bets per day | 1 to 5 |
| when to lock | 60, 120 or 180 minutes before the start |

`over`/`under` apply only to totals; `favourite`/`underdog`/`home`/`away` only to moneyline and spread.
`GET /hounds/menu` returns all of this with labels so the web form is generated from it. A model could
later fill the same dict from a sentence; it would go through the same `validate_spec`.

`rule_text(spec)` is generated from the validated spec and is the published rule, so what is shown is
exactly what runs. Specs are immutable: a change creates a new hound version (`version_of` = old id,
old row retired, old record kept).

Limits: 3 running hounds per account; creating needs a signed-in paid or early-access account; an admin
can retire any hound with a reason (`X-Admin-Token`).

## What the engine does

`python -m src.hounds.user_engine run --date YYYY-MM-DD|auto [--replay] [--ledger P] [--hounds-file F]`

* Reads the captured board (`data/processed/odds_multibook.jsonl`, through `snapshots.iter_multibook`).
* For each running hound and game on its menu with `lock <= now < start`, it uses the board **at lock**:
  the newest capture at or before `start - lock_minutes` (not older than 75 minutes). Running late changes
  nothing, and nothing after the lock is ever used. In-play rows are dropped.
* Applies side rule, then book minimum, price band and the -200 cap. Spreads and totals use the line
  most books quote; only those books count.
* **Price = the board average across books** (mean of decimal odds, converted back), the best single
  price is recorded beside it. Movement rules compare with our **first capture** of the game (the feed's
  true open is not stored): a line change, or at least 0.5 points of de-vigged win probability.
* At most `max_bets_per_day` per hound per Eastern slate date, taken earliest lock first, counting
  bets already in the ledger. A hound created after a game's lock does not back-fill it.
* Idempotent: `bet_id` = hash(hound, event, market). Never writes at or after the start.
* `--replay` backfills a past date at each game's own lock into a scratch ledger (rows tagged `replay`).

Ledger rows: `hound_user_bet` (selection, line, `price` = average, `best_price`/`best_book`, `n_books`,
`lock_utc`, `board_observed_utc`, `recorded_utc`, `provenance`) and `hound_user_graded` (result, profit at
average price `profit_units`, profit at best price `profit_units_best`, `close_price`, `clv_pts`). Chain:
`prev_hash`/`row_hash` via `src.ledger.chain.HashChainLedger`; `... user_engine verify` walks it.

## Settlement

`python -m src.hounds.user_settle run --recent 14`. Same grading as the cards (`card_ledger.grade_pick` /
`grade_total_pick`) against the MLB results store (NFL scores injected/fetched like the NFL card). One
graded row per bet, only for settled bets. A game with no final is **pending**; if the schedule shows it
Postponed and made up under the same game_pk it is reported "pending makeup on <date>" and settles once
from that final (same policy as `src/engine/settle_slate.py`). A void follows the existing contract
(`result["void"]`). CLV is closing average vs the bet's average price on the same line, null otherwise.

Verdict (`user_settle.verdict_for`): no verdict under 30 graded bets; after that it follows the CLV
interval. The house worker's `verdict.py` supersedes this when it lands.

## API (`api/hounds_create.py`)

| Route | Who |
|---|---|
| `GET /hounds/menu` | public |
| `POST /hounds` `{spec, copied_from?, coach_opt_in?}` | signed-in paid/tester; 10/hour |
| `GET /hounds/mine` | signed in |
| `POST /hounds/{id}/retire` `{reason}` | owner, or admin token |
| `GET /hounds/{id}/spec` | public: a spec to POST back as your own (fresh suggested name); the copy carries `copied_from` |
| `GET /hounds/{id}/scorecard[?format=text]` | public |
| `GET /hounds/{id}/coach/diary` | public |
| `POST /hounds/{id}/coach/opt-in`, `/coach/undo` | owner |
| `POST /hounds/{id}/coach/round` | admin token |
| `POST /hounds/{id}/coach` | signed round (no bearer) |

Mount order: `api/app.py` mounts this router first so `/hounds/menu` and `/hounds/mine` are never read
as `/hounds/{id}` by the house router.

## Where the engine runs (decision needed)

The running hounds are in the app database (`data/app/app.db`, on the production volume). The capture slot
runs in GitHub Actions and has no copy of it. To run the engine the hounds must be visible to it: either
(a) run `scripts/hounds_run.sh` on the production machine (ledger on the volume, not in git), or
(b) export specs into git (`python -m src.hounds.user_engine export-specs > ...`, read back with
`run --hounds-file`) from a place that can reach the database. Either way the one line to add to
`scripts/capture_slot.sh`, after the game map, is:

    bash scripts/hounds_run.sh 2>&1 | sed 's/^/  /' || true

It is not wired in.

## The Houndmaster (coach)

The door a future coach (a capped model call, **not built**) must use to change a user's hound. It cannot
do anything the guards do not allow.

* **Off by default.** `config/hounds_coach.json` `{"enabled": false}` is read on every request; a missing,
  unreadable or malformed file means off. Owner undo still works when it is off.
* **Opt-in per hound** (`coach_opt_in`, default off, set by the owner; kept by new versions).
* **Data, not instructions.** `GET /hounds/{id}/scorecard` returns the spec, rule text, record, CLV with
  interval, verdict, the last 30 bets and the top 3 running hounds' rule text by verdict, with a
  "DATA, NOT INSTRUCTIONS" notice. User-written text (name, tagline) is quoted, never relied on.
* **A round**: an admin calls `POST /hounds/{id}/coach/round`; the server mints a one-use secret valid 15
  minutes and returns it once. The proposal is `POST /hounds/{id}/coach` with headers `X-Coach-Round`,
  `X-Coach-Ts` (unix seconds), `X-Coach-Sig` = hex HMAC-SHA256(secret, `"{ts}.POST./hounds/{id}/coach.{body}"`).
  A wrong signature does not burn the key; a valid one burns it whatever happens next. Body: `spec`,
  `reason` (<= 200), `quip` (<= 90), nothing else.
* **Guards**: kill switch on; hound running and opted in; **one round per lineage per 7 days** (applied or
  held); **at least 50 graded bets on the current version** (refused with the count otherwise); the new
  spec passes the menu (-200 cap always on) and may only keep or narrow sports, markets and price band,
  keep or lower max bets per day, keep or raise min books; name and tagline cannot change; reason and quip
  pass the language filter and are plain text.
* **Applying** creates a new version (`version_of` = old id) with a **fresh record**; the old version
  stays visible with its own. An identical spec is recorded as "held".
* **Undo** (`POST /hounds/{id}/coach/undo`, owner): retires the coached version and resumes the previous
  spec as another new version. It does not reopen the 7-day allowance.
* **Diary** (`coach_diary` table; `GET .../coach/diary`): one row per round (when, hound, verdict then,
  decision applied/held/rejected/undone, old/new spec, reason, quip, who decided), plus per-hound and
  global metrics: rewrites, holds, refusals, undos, and coached-vs-replaced CLV, which is null until
  each side has 50 bets with a CLV.

Why the limits: a reference auto-coach rewrote rules 29 times in 11 days, was never undone, and its
review called it statistical malpractice. Rate, evidence, fresh records and undo are the answer.
