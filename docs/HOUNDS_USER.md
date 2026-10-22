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

## Matchup and team-strength conditions (2026-10-19)

A member asked for "head-to-head, home advantage, offense against defense" and the menu had none of it. Five
conditions read the stores already in the repo, point in time (nothing dated on or after the slate day, nothing
still being played at the lock), and say "does not apply" rather than guess when the games they name are not on file.

| Condition | What it checks | Data |
|---|---|---|
| `head_to_head` | the team's record in the last N (1 to 10) meetings with this opponent, all meetings on file or this season only | NFL: `data/datasvc/nfl/games.jsonl`, 2021 on. MLB: `data/historical/mlb_results.csv` 2023 to 2025 plus games since 2026-08-28; January to August 2026 is the sealed research stretch and is never read, so a recent meeting from it is not seen (the menu says so) |
| `venue_record` | this season's win rate at home, on the road, or on today's kind of ground, at least 5 games on that ground | same stores, this season only |
| `scoring_rate` | runs (MLB) or points (NFL) scored or allowed per game over the last N games (0 = whole season so far) | final scores in the same stores |
| `league_rank` | top or bottom N (1 to 15) of the league for scoring or defence, same window | computed over every club with enough games on file; ties share a rank; fewer than 8 clubs is no rank |
| `matchup_edge` | the team's offense (or defense) ranks at least G places better than the other team's defense (or offense) | the same ranks |

All five are in `user_rules.CONDITIONS`, so the web builder, the English parser, the Zapier translator's menu and
the output check, the renderer and the engine pick them up from the one table. Each carries a `note` in
`GET /hounds/builder/menu` that says what data is behind it.

The English parser reads them ("won 3 of the last 5 meetings", "head-to-head", "home advantage", "a top 10
defense", "scores at least 4.5 runs per game", "its offense ranks better than the opponent's defense", and
"last five games" as recent form). A phrase that names the idea with no number is read with a stated default
(5 meetings, a majority of wins, a 60% win rate, the last 10 games, 1 place better) and the default is listed
under `assumed`. Words it cannot read come back with `suggestions`: a wording it does read, or the plain fact
that the rules have no such stat (starting pitchers, bullpens, lineups, injuries).

## Removing and editing a dog

"Remove from my kennel" is `POST /hounds/{id}/retire` with no reason. It is a retirement, never a delete: the
ledger is append-only, so the dog's tickets and record stay, its address still opens ("Retired by the owner"),
and it stops betting, leaves My kennel (every earlier version of it too, `user_store.removed_roots`) and the
leaderboard, and frees a running slot. A version retired by an edit is not a removal (its reason starts
`superseded by`). A classic (version 1) dog opens in the builder as the equivalent rule set (`upgrade_v1`) and
saves as the next version through the same diff and version routes; the old row and every bet on it are untouched.

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

Verdict: `user_settle.verdict_for` is the engine's own early stand-in and is **not public**. The label a
visitor sees is `src/hounds/verdict.py`'s (150 measurable bets, a date-clustered bootstrap), through
`src/hounds/user_view.py`.

## API (`api/hounds_create.py`)

| Route | Who |
|---|---|
| `GET /hounds/menu` | public |
| `POST /hounds` `{spec, copied_from?, coach_opt_in?}` | signed-in paid/tester; 10/hour |
| `GET /hounds/mine` | signed in |
| `POST /hounds/{id}/retire` `{reason?}` | owner (no reason needed: the kennel's "Remove from my kennel"), or admin token (reason required) |
| `GET /hounds/{id}/spec` | public: a spec to POST back as your own (fresh suggested name); the copy carries `copied_from` |
| `GET /hounds/{id}/scorecard[?format=text]` | public |
| `GET /hounds/{id}/coach/diary` | public |
| `POST /hounds/{id}/coach/opt-in`, `/coach/undo` | owner |
| `POST /hounds/{id}/coach/round` | admin token |
| `POST /hounds/{id}/coach` | signed round (no bearer) |

Mount order: `api/app.py` mounts this router first so `/hounds/menu` and `/hounds/mine` are never read
as `/hounds/{id}` by the house router.

## Where the engine runs (decided 2026-10-18; reversible)

The running hounds are in the app database (`data/app/app.db`, on the production volume). The capture slot
runs in GitHub Actions and has no copy of it, so the engine does **not** run there. It runs **inside the API
process on the machine that owns the database**: `src/hounds/user_runner.py`, started from `api/app.py`.

* **Off unless `HOUNDS_ENGINE=on`** (anything else, or nothing, starts no thread). `HOUNDS_ENGINE_INTERVAL_SECONDS`
  overrides the 900 s cadence (floor 30 s).
* One daemon thread. Every 15 minutes: read the running hounds from the app database (none: stop, the odds
  store is not opened), run the engine for today's Eastern slate (plus tomorrow's after 20:00 Eastern),
  settle the last 14 days, and, if a row was written, start one background rebuild of the public stats.
* **One at a time.** The pass holds the process-wide build gate (`src/appstate/freshness.py`), the same one
  every page cache and the hounds' stats build take. It waits for the first cache warm-up pass. `GET /health`
  reports it under `hounds_engine` (passes, last report, last error).
* **Memory.** The odds store is streamed a row at a time (`user_engine.iter_rows`), only the slate's games are
  kept and only the fields the engine reads. Measured with tracemalloc against the real local store, a
  15-game regular-season slate peaks near 29 MB; the budget is 150 MB and `tests/test_hounds_integration.py`
  pins it.
* **The ledger is written beside the app database** (`data/app/hounds_user_v1.jsonl` locally; on the Fly volume
  in production), not to `evidence/`, which is baked into the image. `HOUNDS_USER_LEDGER` overrides the path.
  `src.hounds.user_engine.ledger_path()` is the one place the engine, the settler and the public stats all read it
  from. It is still a hash chain: `python -m src.hounds.user_engine verify`.
* `scripts/hounds_run.sh` still runs the same three steps by hand (against whatever `HOUNDS_USER_LEDGER`
  or `--ledger` says) and is **not** wired into `scripts/capture_slot.sh`.

How to turn it on for staging (an owner step; nothing in the deploy config changes): see
docs/HOUNDS_INTEGRATION.md, "Owner steps".

## What is public about a user hound

Everything public (record, CLV, verdict, `verified`, series, status) comes from `src/hounds/stats.py` and the
pre-registered referee `src/hounds/verdict.py`, reading this ledger. The CLV and verdict columns that
`user_settle` computes for itself stay in the ledger code and reach no public payload. The ledger rows carry
the contract's field names beside the engine's own (`price_average` = the board average, `price_best` = the best
quote recorded at lock, `book`, `book_count`, `start_utc`, `segment`, `who_decided`, `reason`; a graded row also
`units` = units at the best price). `units_average_price` (the headline) is the same bets settled at the average.

## The Houndmaster (coach)

The door a future coach (a capped model call, **not built**) must use to PROPOSE a change to a user's
hound. **Since 2026-10-18 a proposal creates a challenger, never a change** (champion / challenger,
`docs/HOUNDS_LEARNING.md`, `docs/PREREG_LEARNING_LOOP.md`): the proposed spec runs in shadow beside the
champion on the same games at the same prices, and only the referee, by a pre-set test on the paired
closing-line value, can promote it (as a new version, below). It cannot do anything the guards do not allow.

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
  `reason` (<= 200), `quip` (<= 90), and, when the spec differs from the champion's, `hypothesis` (20 to 400
  chars: why this should beat the champion) and `evidence` (1 to 10 references to scorecard fields or lesson
  ids); nothing else (a `promote` or `retire` field is refused as a bad body).
* **Guards**: kill switch on; hound running and opted in; **one round per lineage per 7 days** (applied or
  held); **at least 50 graded bets on the current version** (refused with the count otherwise); the new
  spec passes the menu (-200 cap always on) and may only keep or narrow sports, markets and price band,
  keep or lower max bets per day, keep or raise min books; name and tagline cannot change, and neither can
  `lock_minutes` (the pair must lock at the same instant); reason, quip and hypothesis pass the language
  filter and are plain text. The loop adds: at most 3 live challengers per hound and 30 in the scope; no
  near-copy of the champion, of a live challenger, or of a challenger that lost in the last 90 days.
* **A proposal creates a challenger** (decision `challenger` in the diary). A **promotion** (made by the
  referee, never by the model) creates a new version (`version_of` = old id) with a **fresh record**; the old
  version stays visible with its own. The diary row for a promotion is `applied`, `decided_by: referee`.
  An identical spec is recorded as "held".
* **The loop can switch the door off by itself**: an auto-pause (a failing promotion hit rate, or 60 days
  trailing the random controls) writes a pause flag beside the app database; `coach_enabled()` is the config
  AND no pause. Only the owner's `python -m src.hounds.learning resume --scope user` lifts it.
* **Undo** (`POST /hounds/{id}/coach/undo`, owner): retires a promoted (or legacy coached) version and
  resumes the previous spec as another new version. It does not reopen the 7-day allowance, and it is
  counted in the loop's scorecard.
* **Diary** (`coach_diary` table; `GET .../coach/diary`): one row per round (when, hound, verdict then,
  decision challenger/applied/held/rejected/undone, old/new spec, reason, quip, who decided, the challenger
  id), plus per-hound and global metrics: challengers, rewrites (promotions), holds, refusals, undos, and
  promoted-vs-replaced CLV, which is null until each side has 50 bets with a CLV.

Why the limits: a reference auto-coach rewrote rules 29 times in 11 days, was never undone, and its
review called it statistical malpractice. Rate, evidence, fresh records and undo are the answer.

## Unleash finds plays, and "Also bet games in play" (2026-10-22)

**What was wrong (2026-10-21, hound DRAKEO).** Unleash said "Checked 60 games - Nothing to lock yet" and showed no tickets.
Three faults: (1) a hound with any bet on record was only *shown*, never evaluated; (2) a hound created after a game's lock
skipped that game for good, so games starting within the lock window were passed over; (3) the day view listed only rows of
the slate date and gave no reason per game. Replaying DRAKEO's rule over the stored boards for 2026-10-22 04:40Z reproduces
"Checked 60 games" and shows why nothing fit: 54 had no board fresh enough yet (far-off games are captured every few hours;
the runner checks them at their lock), 1 fewer books than needed, 3 price outside the band, 1 rule not met, 1 placed.

**Now.** Every Unleash evaluates today's not-yet-started games (idempotent bet id, daily limit, one side per game, -200 cap
unchanged). The response carries `open_tickets` (every ticket still waiting for a result, any recent day), `why` (one bucket
per game: `src/hounds/interact/unleash_why.py`, the furthest test the game got through) and `next_check` (the next game the
runner will check, and when).

**Also bet games in play** (`bet_in_play` on a version-2 spec; default off; absent from the spec and the rule hash when off).
When on, Unleash and the runner evaluate a game that has started, inside its sport's live window, on the newest in-play
capture of the multibook store (the store the Live page reads) observed at or before the evaluation instant. A later capture
is never read. A live capture older than `LIVE_MAX_AGE_MINUTES` (5; the runner passes every 15 minutes, so most live bets
come from Unleash taps or a fresh capture) is skipped as `live_price_too_old`; no capture at all is `no_live_board`. Bets
carry `live: true` and `live_price_observed_utc`; tickets read "Live bet - price at HH:MM". Props are never bet live. The
Gematria style refuses the setting. In-play prices move fast: bet at your own risk, paper only.

**What a ticket's `lock_utc` means (checker round, 2026-10-22).** It is the instant of the board the bet read. The runner and a
hound that existed at the lock: the lock. A hound born after a game's lock that is unleashed before the game starts is priced on
the newest board at or before the tap, never the lock-time board and never a later one: its row is stamped with that tap
instant, carries `placed_after_lock: true`, and its "Why this bet" says so. An in-play bet is stamped with its evaluation
instant. Without this the public "verified" check compared the price taken with a board from before the bet's own board.
An in-play bet is graded like any other, but it has **no closing-line value** (`close_price`/`clv_pts` stay null): its price
was taken after the pre-game close. The live label is in UTC, "Live bet - price at HH:MM UTC", like the recorded time beside it.
The leaderboard's Bets figure counts open tickets beside the settled ones ("5 (5 open)"). There is no results lookup behind
"already ended": a game is bet live only inside its sport's live window and on a capture under 5 minutes old.
