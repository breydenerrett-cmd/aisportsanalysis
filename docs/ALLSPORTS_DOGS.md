# Dogs that bet any sport (2026-10-19)

Owner direction: member dogs may bet ANY sport The Odds API prices (tennis, cricket, soccer, NBA, NHL, college,
Euroleague ...), live ones included. Paper only. This is the backend; the builder UI only has to read the
menus below.

## Where things live

| Piece | File |
| --- | --- |
| Sport-key prefix -> family, markets, window margins, switches and caps | `config/sports_catalog.json`, read by `src/sports/catalog.py` |
| Capture (free discovery and event listing, pre-game phases, in-play snapshots) | `src/pipeline/allsports_capture.py`, `python3 -m src.cli allsports capture [--plan]`, step "allsports capture" in `scripts/capture_slot.sh` |
| Results and the grader | `src/pipeline/allsports_scores.py`, `python3 -m src.cli allsports scores [--plan]` |
| Settlement | the non-MLB/NFL branch of `src/hounds/user_settle.py` |
| Dog menu, ANY, sport-restricted conditions | `src/hounds/user_spec.py`, `src/hounds/user_rules.py` (`any_sport`) |
| `/sports/now`, `/sports/catalog`, "live elsewhere" | `src/sports/allsports_view.py`, `api/sports.py`, `src/hounds/interact/fire.py` |
| Credit band and cap | `src/capture/budget.py` (`ALLSPORTS`, `can_spend_allsports`) |

Stores (append-only, un-ignored in `.gitignore`): `data/processed/allsports_capture_done.jsonl` (phases bought,
calls, quiet-key rechecks), `allsports_sports.jsonl` (which keys were being priced when),
`allsports_scores.jsonl` (results). Prices go into the SAME `odds_multibook.jsonl`.

## API contract for the UI

* `GET /sports/now` -> `{generated_utc, families:[{code, label, live:[event], upcoming_24h:[event], next_start_utc}]}`;
  `event` = `{event_id (unique), league, league_title, home, away, start_utc, in_play, best_price_home,
  best_price_away, best_price_draw?, n_books, observed_utc, score?}`; `score` = `{home, away, detail: "Live"|"Final",
  completed, as_of}`, present only when the scores store has a fresh reading. `GET /sports/catalog` is public.
* `POST /hounds/{id}/fire` with no body is unchanged. With `{"event_id": "..."}` it answers for that game alone
  (`src/hounds/interact/fire_event.py`): `{event_id, picked, pick, picks, code, reason, live, recorded, game,
  sport, misses}`. A game that has started and has in-play snapshots is read on its NEWEST in-play price
  (`live: true`, preview only, nothing written, refused with `live_price_too_old` past 90 minutes). Codes beyond the
  engine's own: `unknown_event`, `not_eligible`, `too_far_ahead`, `no_live_price`, `live_price_too_old`, `game_over`.
* A fire result with no picks carries `next_game` ("Next game: Thu 5:15 PM — Yankees at Red Sox", Eastern) and
  `live_elsewhere` ("Live now in other sports: 14 games (tennis, cricket)"), both plain strings or null.
* `builder_menu()` / `menu()` `sports[]` ends with `{value: "ANY", label: "Any sport", any: true}`; every market
  and condition lists its supported families in `sports`. Stat conditions stay `["MLB", "NFL"]` (weather, travel and
  player conditions `["MLB"]`).

## Row shape

Exactly the MLB/NFL multibook shape (`snapshots.multibook_rows`): h2h rows have no `market` key, spreads and
totals do. Added: `sport` = the lower-case family code (`nba`, `soccer`), `league` = the Odds API sport key,
`league_title`, `in_play: true` on any row observed at or after the start, and `draw_price` on a three-way h2h
row. `user_engine.load_rows/iter_rows` and `snapshots.window_for_date` read them unchanged; each family has its
own `since_margin_days` in the catalog (a pre-game phase leads by about 1.1 days). Bet rows carry `league` and
`league_title` so settlement knows the feed.

## Credits

Free: `/sports`, `/sports/{key}/events`, the quota read. Paid: `/odds` = markets x regions per key call (one
call buys every event of the key); `/scores` = 1, or 2 with `daysFrom` (always 3 here).

* Every call is logged through `creditlog` in the `allsports_capture` band, with the vendor's own
  `x-requests-last` (a direct-sum band, like `live_odds`: never a balance delta).
* Daily cap `capture.daily_cap_credits` = 1,500 (config), sub-caps `inplay_daily_cap_credits` = 450 and
  `scores_daily_cap_credits` = 300 inside it, `max_calls_per_run` = 60. The absolute 5,000 floor applies first and
  fails closed. A refusal stops spending; a missed window is gone and is not filled.
* Phases: t24h, t6h, t2h, t30m before the start; one call per key per due moment serves every event of the key.
  In-play: h2h only, one call per key per 30 minutes while an event is inside its live window.
* Kill switches: `ALLSPORTS_CAPTURE=0` in the environment, or `capture.enabled=false` in the config.
* A key whose calls return events but no bookmaker rows twice in a row is "dark" on that region; the next rung of
  the family's `region_ladder` is tried; dark on every rung = left alone for 24 hours.

## Grading

moneyline: higher score wins. A level score is a DRAW: in a three-way family (`draw_possible`: soccer, cricket,
rugby, AFL, boxing) a draw LOSES a team moneyline; elsewhere it is a PUSH. spread: the picked side's own line.
total: both scores against the line. VOID: a cancelled game, or no completed score 72 hours after the start,
named in the graded row's reason. All outcomes (home, away, draw) are stored in `allsports_scores.jsonl`.

## What is NOT on the dog menu, and why

`settles` in the catalog says how a family is graded; `dog_menu` says whether builders may pick it. TENNIS, MMA,
BOXING and OTHER are off the menu: The Odds API `/scores` does not list tennis (docs/LIVE_BETTING_SYSTEM.md), MMA
results are entered by hand, and nothing grades boxing or the catch-all, so a dog bet there could only void after 72
hours. Their prices ARE captured and shown by `/sports/now`. Turn a family on with `dog_menu: true` once a result
source exists. `scores_verified` is false for every family except MLB and NFL until someone spends the one credit to
confirm `/scores` returns results for it.

## Owner rulings kept

No pick at -200 or worse, ever: `user_spec.beyond_cap` is checked by the engine for every family (a heavy tennis
or soccer favourite is skipped, `skipped.price_cap`), validation refuses a band that reaches it, and the underdog
side of a heavy favourite (+700) is fair game. Generic rules (favourite, underdog, home, away, over, under, line
movement, price band, books, day, coin flip, names) work for every family; conditions that read MLB/NFL tables
(rest, streaks, head-to-head, scoring ranks, team pickers, weather, travel, players, props) stay MLB/NFL only and
are validation errors for any other sport.

## Known limits

* An NHL shootout may be counted in the vendor's final score, which can move a total.
* Cricket scores are read as runs (`152/6` -> 152); a score in another form (two innings) is unreadable and the bet
  voids at 72 hours rather than guessing.
* The scores poll is driven by the capture done store, because the CI runner cannot see the hounds ledger.
