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
| Free results for tennis and MMA (ESPN) | `src/pipeline/allsports_free_results.py`, `src/providers/espn_tennis_results.py`, `src/providers/espn_mma_results.py`; runs inside `python3 -m src.cli allsports scores` |
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

## Tennis and MMA: free results from ESPN (2026-10-20)

The Odds API `/scores` lists neither sport, so each has a free source and `settles` = `free_results` in the
catalog. Both end in the same `allsports_scores.jsonl` and the same `score` row the settlement already reads
(keyed by the Odds API event id), so `user_settle` has no special case. `python3 -m src.cli allsports scores`
runs them after the credit-spending poll; they cost nothing and are rate-limited by `free_results_poll_interval_hours`
(default 1). A kill switch is the same as the capture's (`ALLSPORTS_CAPTURE=0`).

**Which events:** the family's events in `odds_multibook.jsonl` that started between 20 minutes and
`scores_days_from` + 1 days ago with no completed row. **Row:** `completed: true`, `home_score`/`away_score`
1.0 and 0.0 (a match-win marker, not sets or rounds), `outcome` home/away; or, for a void,
scores `null` and a named `void_reason`. Also `source` (`espn_tennis`, `espn_mma`), `evidence` (ESPN ids,
status, the names matched and how) and `completed_utc`.

**Point in time.** ESPN publishes a scheduled start and no finish time. `completed_utc` is the moment OUR run
first saw the match settled (`completed_utc_basis: observed`), an upper bound on the real finish. A back-fill run
stamps its own fetch time; nothing claims to have been known before it was seen.

**Tennis** (`espn_tennis_results.py`, `https://site.api.espn.com/apis/site/v2/sports/tennis/{atp,wta}/scoreboard?dates=YYYYMMDD`):
`?dates=` returns every active tournament's whole draw. Singles only. Covered: Grand Slams, Masters/1000, 500s,
250s, qualifying, the WTA 125s ESPN lists. NOT covered: Challenger and ITF (the slugs `challenger`, `itf`,
`atp-challenger`, `wta-125` answer 400). Rules, the common book rules for a match-winner bet:

| ESPN status | Bet |
| --- | --- |
| `STATUS_FINAL`, one winner flagged | the winner wins |
| `STATUS_RETIRED` (also default, disqualification), at least one COMPLETED set | the player who advanced wins |
| `STATUS_RETIRED`, no set completed | VOID |
| `STATUS_WALKOVER` | VOID |
| `STATUS_CANCELED` | VOID |
| scheduled, in progress, postponed, suspended, delayed | pending |
| final or retired with no single winner flagged, an unknown status | unresolved, never graded |

A set is completed by its games (6-0 to 6-4, 7-5, 7-6, any lead of two from six games on, a 10-x super-tiebreak),
not by ESPN's per-set winner flag, which is not set on the last set (checked against real retirements).

**MMA** (`espn_mma_results.py`, unchanged except three confirmed aliases): each Odds API bout is asked of the
existing ESPN UFC grader as a `BoutIdentity`. A decision is a win for the matched side; a draw, a no contest or
a bout ESPN calls cancelled is a VOID for the moneyline. An INFERRED replacement (a published fighter fought
someone else) is NOT written: on 2026-10-17 it mistook Katlyn Chookagian's ESPN name (Katlyn Cerminara) for a
replacement and would have voided a bout that happened, so it is held; the bet then voids at 72 hours like any
unmatched one. ESPN has UFC and Contender Series only: a bout of KSW, Oktagon, PFL, Cage Warriors and the rest
never matches and voids after 72 hours.

**Matching.** Tennis uses `names.person_score` (accents, case, punctuation, reversed order, initials, a dropped
middle name or particle; never a nickname such as Alex for Alexander) on BOTH players, an ESPN start within 48
hours of the odds start, and exactly one candidate. MMA uses the grader's `names.match` plus
`CONFIRMED_ALIASES`. **An unmatched, ambiguous or not-yet-final result writes nothing**; the bet stays pending
and `grade_bet` voids it 72 hours after the start with a reason that names the feed.

**Measured 2026-10-19/20 (real fetches).** Tennis, yesterday's scoreboards: ATP 117 singles in the active draws,
47 settled, 15 of them scheduled 2026-10-19; WTA 94 singles, 51 settled, 11 scheduled that day (its draws held 9
retirements: 7 graded, 2 void). The 8 Odds API tennis events on file (WTA Singapore, 2026-09-21/22) all matched one ESPN
match each (7 exact names, 1 reversed order: "Xinyu Wang"). MMA, the UFC Fight Night of 2026-10-17: 46 captured
bouts in the window, all 13 UFC bouts matched and graded (3 of them only through the new confirmed aliases), the
other 33 are other promotions and correctly unmatched.

## What is NOT on the dog menu, and why

`settles` in the catalog says how a family is graded; `dog_menu` says whether builders may pick it. BOXING and
OTHER are off the menu: nothing grades boxing or the catch-all, so a dog bet there could only void after 72
hours. Their prices ARE captured and shown by `/sports/now`. Turn a family on with `dog_menu: true` once a result
source exists. `scores_verified` is false for every Odds-API-scored family except MLB and NFL until someone spends
the one credit to confirm `/scores` returns results for it; it is true for TENNIS and MMA, whose free feeds were
fetched for real and matched against the odds feed's own names.

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
* The scores poll is driven by the capture done store, because the CI runner cannot see the hounds ledger. The
  free tennis and MMA results are driven by the multibook store for the same reason.
* Tennis Challenger/ITF matches and non-UFC MMA bouts have no free result source and void at 72 hours.

## Player props: NBA, NFL, NHL, NCAAF (2026-10-20)

Code `src/pipeline/allsports_props.py`, grader `src/pipeline/allsports_props_grade.py`, command
`python3 -m src.cli allsports props [--plan]`, step "allsports props" in `scripts/capture_slot.sh`.

* **What it buys.** Each game's main prop markets in ONE per-event call (`/sports/{key}/events/{id}/odds`, billed
  markets x regions per event, `us` region): NBA points, rebounds, assists, threes, PRA (5); NHL points, assists,
  shots on goal, anytime goal, saves (5); NFL pass yards and TDs, rush yards, receptions, reception yards, anytime TD
  (6); NCAAF pass, rush and reception yards, anytime TD (4). The market lists are `props_markets` on each family in
  `config/sports_catalog.json`; **the keys follow the vendor's documented list but no paid call was made to confirm
  them**: a wrong key is an HTTP 422 that bills nothing, and the summary prints an ESCALATE line naming it.
* **When.** Three windows before the start: t6h (6h to 2h out), t2h (2h to 30m), t30m (30m to the start), one snapshot
  per window, soonest game first. A window that closes with no purchase is written as `missed` and never filled. A
  game whose calls return no props twice running is left alone (college games without a prop board).
* **Credits.** Own band `allsports_props` (`budget.ALLSPORTS_PROPS`, a direct-sum band: every call logs the vendor's
  `x-requests-last`), own daily cap `capture.props_daily_cap_credits` = 1,200 in the config's capture block; it does not
  spend the 1,500 all-sports cap or the 900 pre-game envelope. The absolute 5,000-credit floor applies first and fails
  closed (an unreadable quota stops the run). Estimate: a weeknight (8 NBA + 8 NHL) about 240 credits; a Sunday (13 NFL,
  8 NBA, 6 NHL) about 440; a Saturday (30 college games with props, 10 NBA, 8 NHL) about 630; roughly 330 a day over a
  week in season, 10,000 a month. Well inside the cap, so raising the cap alone buys nothing: more spend means more
  markets (alternate lines), more windows (`props_phases_minutes`) or more leagues (WNBA, NCAAB, add a catalog entry).
* **Rows.** `data/processed/allsports_props.jsonl`, the MLB prop store's shape (`batter_props._project`): `event_id,
  game_date, commence_time, home_team, away_team, market, selection, player, side, line (string, null for anytime),
  price, book, book_last_update, observed_utc, capture_phase` plus `sport` and `league`. Every snapshot is whole (no
  de-duplication against an earlier window). Memory: `data/processed/allsports_props_done.jsonl` (phases bought or
  missed, one `call` marker per billed fetch with credits, errors, quiet-league peeks). Both are un-ignored in
  `.gitignore`, appended only, and the rows file is a registered rotatable store (`store rotate --all` in the slot), so it
  cannot reach GitHub's 100 MB limit. Read it with `allsports_props.iter_rows` (archive segments plus hot file). Neither
  file is copied into the web image (`.dockerignore`): nothing serves props. Size, unmeasured until a live run: about
  200-400 KB per NBA game snapshot, so tens of MB a week in season.
* **Kill switch.** `ALLSPORTS_PROPS=0` (also `ALLSPORTS_CAPTURE=0`, or `capture.props_enabled=false`).
* **Grading.** `grade_prop(row, box)` -> `win | loss | push | void | unresolved`, against `DataClient().league(..).game(id)`
  (NBA, NHL, NCAAF) or the nflverse player rows (NFL). A player who did not play is a void; a game not final, an
  unmatched name, a stat the box lacks or a market it cannot answer is `unresolved`, never a guess. **NCAAF cannot be
  graded from the stored data**: college leagues keep team totals only (`players=False`, about 100 MB a season to turn
  on), so those rows grade `unresolved` until player lines are enabled. Joining an Odds API event to a data-service game
  id is not built.
* **Licence note.** The Odds API terms forbid selling the data as a feed: these rows back picks and research, not a
  data product (docs/datasvc/LICENSING.md).
