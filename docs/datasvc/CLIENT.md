# The data service's door: `DataClient`, `/data/v1`, and MLB

Written 2026-10-04. This is the internal reference for the part of the data service LineHound's own code
uses. It is a backend, not a product page: no keys, tiers or portal. The plan is
[`../DATA_SERVICE_PLAN.md`](../DATA_SERVICE_PLAN.md); the per-sport contracts are `UFC_SCHEMA.md`,
`UFC_FEATURES.md`, `NFL_SCHEMA.md`, `NFL_FEATURES.md`.

## One set of functions, two doors

The domain logic of every route lives in `src/datasvc/client.py` (stdlib, no FastAPI) and is called by

* `api/datasvc.py`, which adds sign-in (`require_paid_access`, always), parameter parsing, pagination and the
  one error shape; and
* `DataClient`, the same functions with no HTTP in between.

`holder` and `nfl_holder` are the process's one UFC and one NFL store: the data API, the UFC fight-night page
and the client share them, so a process holds each store once. MLB is wrapped, not rebuilt:
`src/datasvc/mlb/service.py` calls the analyst's own loader and packet builder
(`src/analyst/source.py`, `packet.py`), so an MLB packet served here is byte for byte the one the analyst
builds, read-only and never published.

## Who uses it

| Consumer | How |
|---|---|
| The UFC fight-night page (`api/ufc_fights.py`) | reads the shared UFC store holder |
| The MLB analyst's supervised-session pilot (`src/analyst/pilot.py`) | `pilot.prepare(date, "NYY@TB", client=DataClient())` takes its packet from the data service; the packet hash is identical to the loader path (`tests/test_datasvc_mlb_pilot.py`) |
| `/data/v1/...` | the HTTP routes below |

## What a call returns

Every capability returns one of two shapes, and nothing in between.

```
{"available": true,  "sport", "kind", "data": <the sport's own shape>, "page": {...} (lists), "meta": {...}}
{"available": false, "missing": [{"item", "reason"}, ...]}
```

A capability with no usable data (a file absent or unreadable, an id the store has never seen, a name that
fits two people, a schedule provider that cannot be reached) is the second shape, with the reason. Never a
zero where there is no number, never a made-up name, never a fresh timestamp on old data. A bad parameter is
the caller's mistake and raises `DataError` (status 422), as the route would answer 422.

Capabilities, per sport (`client.capabilities(sport)` says the same, with the reason where one is missing):

| Capability | UFC | NFL | MLB |
|---|---|---|---|
| `schedule` | events, upcoming cards with current odds | games | the schedule for a date, results for final games |
| `game` | an event or a bout | a game with both teams' rows | one game of a date |
| `participants` | fighters | teams, players | clubs and probable starters of a date |
| `history` | a fighter's bouts | a player's rows | a pitcher's appearances |
| `features` | as of a moment | team and player, as of a moment | not served alone (inside the packet) |
| `availability` | none: the UFC store has no such dataset | injury reports | none: lineups and roster news ride inside the packet |
| `quotes` | a bout's odds, as ESPN reports them | the schedule file's market: ONE value per game | the packet's markets, each with its capture time |
| `matchup` | the fact sheet for two fighters | the fact sheet for one game | the analyst's frozen evidence packet |

## `meta`

Every packet's `meta` carries

* `ids`: the stable ids and `provider_ids` (ESPN athlete and competition ids and the UFC.com slug; nflverse,
  ESPN, PFR and GSIS ids; MLB Stats API `game_pk`, team and person ids and The Odds API event ids);
* `units`;
* `sources` or `datasets`: each source's identity, `basis` (below), our `version` of the file and its kind;
* `built_utc` (when this answer was assembled), `observed_utc` (when WE read or last wrote the source) and
  `source_updated_utc` (the source's own update time where it supplies one, else null with the reason);
* `coverage` (each dataset's newest record, its age and whether that is past the dataset's own limit; for MLB
  what each store covers through, from `src/pipeline/store_freshness.py`);
* `missing`: every absent, stale or thin input, each with its reason;
* `data_version`: a hash of the version of every file the packet was built from. A file the store's
  `MANIFEST.json` describes is identified by its sha256, so the version is the same on every machine holding the
  same bytes; a file with no usable manifest entry (and every MLB file: they are too large to hash per read) is
  identified by size and modification time, which is stable on one machine only, and `version_kind` says which.

A packet is built from one snapshot: the files are stat()ed again after the build, and a build that straddles a
change is repeated. Files that keep changing are `unavailable`, never a packet that mixes two versions. Reads of
an unchanged snapshot cost a stat per file: no upstream request (the MLB schedule is held for 120 seconds) and no
store re-read (`tests/test_datasvc_client.py`, `tests/test_datasvc_mlb_service.py` count both over fifty reads).
A cached packet keeps its own `built_utc`.

## Observed at the time, or reconstructed later

A value's history is only as good as how we got it. `observed_at_the_time` is our own forward capture, stamped
with when we saw it; `reconstructed_later` was fetched or derived after the fact, so an old row says what the
source says now; `single_value_per_record` is a value the source overwrites, so there is no point-in-time
observation at all. This is about what a value means, not whether it may be used: the leakage-free features
filter on dates on top of it.

<!-- basis:begin -->
| Sport | Dataset | Source | Basis | What that means |
|---|---|---|---|---|
| ufc | `events` | ESPN public JSON (core API) | `reconstructed_later` | cards and their status as ESPN lists them when we fetched; a past card is read after it happened, a future card is a schedule that can change |
| ufc | `bouts` | ESPN public JSON (core API) | `reconstructed_later` | bouts, results and finish times are read after the fight; the booked card order of a future bout can change |
| ufc | `fighters` | ESPN public JSON (core API) | `single_value_per_record` | one record per fighter as of its fetched_utc (record, reach, age, stance): not an as-of-bout value, never used by the leakage-free features |
| ufc | `fight_stats` | ESPN public JSON (core API) | `reconstructed_later` | per-fight statistics are fetched after the bout; control time is recorded from about 2018 on (zero before) |
| ufc | `odds` | ESPN public JSON (core API), DraftKings and other providers ESPN carries | `reconstructed_later` | open, close and current as the provider reports them when we fetched; for a finished bout the close was read after the fight (is_closing marks it), so these are NOT our own point-in-time captures and never as-of-safe |
| ufc | `ufccom_profiles` | UFC.com athlete pages | `single_value_per_record` | career figures as the page showed them when fetched; they include every fight up to the fetch and feed nothing where leakage matters |
| nfl | `games` | nflverse schedules/games.csv (CC BY 4.0) | `single_value_per_record` | the schedule file's market (spread, total, moneylines) is ONE value per game that nflverse overwrites as the market moves: the closing numbers for a final game, the latest at fetched_utc otherwise; never an as-of-date price. The quarterback listed for a game not yet played is a projection, replaced by the actual starter once final |
| nfl | `team_games` | nflverse stats_team (CC BY 4.0) | `reconstructed_later` | weekly team statistics read after the games were played |
| nfl | `player_games` | nflverse stats_player (CC BY 4.0) | `reconstructed_later` | weekly player statistics read after the games were played; a player who played but had no stat line has no row |
| nfl | `injuries` | nflverse injuries (CC BY 4.0) | `observed_at_the_time` | report rows with the time we first fetched each changed row (fetched_utc); the source's own report timestamp exists only for 2009 to 2024, so for later seasons and for backfilled rows fetched_utc is when WE saw the row, not when it was issued |
| mlb | `schedule` | MLB Stats API schedule (statsapi.mlb.com) | `reconstructed_later` | read live at observed_utc. For a game already played the probable pitcher is the starter the schedule lists now (retroactive), not necessarily the one announced before the game |
| mlb | `mlb_results` | MLB Stats API schedule, ingested after each date | `reconstructed_later` | final scores and the starters' ids are written after the games finish; the starter ids are retroactive |
| mlb | `pitcher_logs` | MLB Stats API game logs | `reconstructed_later` | appearances accumulated after they happened; as-of use filters by appearance date |
| mlb | `bullpen_log` | MLB Stats API box scores | `reconstructed_later` | relief workload derived after the games |
| mlb | `lineups` | MLB Stats API posted lineups, captured by our own jobs | `observed_at_the_time` | batting orders as captured when posted |
| mlb | `standings` | MLB Stats API standings, one snapshot per day | `observed_at_the_time` | daily snapshots; a date with no snapshot says so and is never filled from another |
| mlb | `matchup_history` | MLB Stats API vsPlayer career totals | `single_value_per_record` | career totals with no as-of parameter; captured forward only, never built after the fact |
| mlb | `odds_multibook` | The Odds API, our own capture | `observed_at_the_time` | every quote carries the time we captured it (observed_utc) and the book's own last_update; the packet drops quotes captured after it was built or at or after first pitch |
| mlb | `derivative_markets` | The Odds API, our own capture | `observed_at_the_time` | team totals, same capture rule as the multi-book store |
| mlb | `batter_props` | The Odds API, our own capture | `observed_at_the_time` | player props, same capture rule as the multi-book store |
| mlb | `pitcher_props` | The Odds API, our own capture | `observed_at_the_time` | pitcher props, same capture rule as the multi-book store |
| mlb | `weather_forecast` | forecast captured by our own job | `observed_at_the_time` | the forecast for the game hour as captured at observed_utc |
<!-- basis:end -->

## Routes

Generated from the router (`python -m api.datasvc`); a test compares this table to it. Every route needs a valid
token and answers errors as `{"error": {"code", "message", "details"?}}`. The MLB routes answer `503
data_unavailable` when the schedule provider cannot be reached, `404 not_found` for a game that is not on the
schedule and `409 ambiguous_game` for a doubleheader (a packet is one game's; the URL cannot say which half).

<!-- routes:begin -->
| Method | Path | Parameters | Returns |
|---|---|---|---|
| GET | `/data/v1/mlb/games` | `date`, `limit`, `cursor` | MLB games for a date, results for final games |
| GET | `/data/v1/mlb/games/{date}/{away}/{home}/packet` | `date`, `away`, `home` | The analyst's frozen evidence packet for one game (read-only, never published) |
| GET | `/data/v1/nfl/games` | `season`, `week`, `team`, `game_type`, `status`, `order`, `limit`, `cursor` | NFL games, newest first; filter by season, week, team, type and status |
| GET | `/data/v1/nfl/games/{game_id}` | `game_id` | One NFL game with both teams' rows |
| GET | `/data/v1/nfl/injuries` | `game_id`, `team`, `season`, `week`, `player_id`, `position_group`, `report_status`, `order`, `limit`, `cursor` | Injury report rows (designated or limited players), newest first |
| GET | `/data/v1/nfl/matchup` | `game_id`, `a`, `b`, `season`, `week`, `as_of` | The fact sheet for one game (a game id, or two teams) |
| GET | `/data/v1/nfl/player-games` | `player`, `team`, `game_id`, `season`, `week`, `position_group`, `order`, `limit`, `cursor` | Offensive usage and production per player per game, newest first |
| GET | `/data/v1/nfl/players/{player}/features` | `player`, `as_of` | A player's recent usage and production over his last 3 and 5 games, as of a moment |
| GET | `/data/v1/nfl/team-games` | `team`, `season`, `week`, `game_type`, `status`, `order`, `limit`, `cursor` | One row per team per game, newest first |
| GET | `/data/v1/nfl/teams/{team}/features` | `team`, `as_of`, `season` | A team's leakage-free form as of a moment |
| GET | `/data/v1/status` | none | Each dataset's record count, newest date and age |
| GET | `/data/v1/ufc/bouts/{bout_id}` | `bout_id` | One bout with its fighters, result, statistics rows and odds |
| GET | `/data/v1/ufc/events` | `year`, `status`, `order`, `limit`, `cursor` | Events, newest first; filter by year and status |
| GET | `/data/v1/ufc/events/{event_id}` | `event_id` | One event with its bouts |
| GET | `/data/v1/ufc/fighters` | `search`, `limit`, `cursor` | Search fighters by name, or list them |
| GET | `/data/v1/ufc/fighters/{fighter_id}` | `fighter_id` | One fighter (and the UFC.com profile when there is one) |
| GET | `/data/v1/ufc/fighters/{fighter_id}/features` | `fighter_id`, `as_of` | A fighter's leakage-free features as of a moment |
| GET | `/data/v1/ufc/fighters/{fighter_id}/fights` | `fighter_id`, `limit`, `cursor` | A fighter's bouts, newest first, upcoming ones included |
| GET | `/data/v1/ufc/matchup` | `a`, `b`, `as_of` | The fact sheet for two fighters (ids or names) |
| GET | `/data/v1/ufc/upcoming` | `days`, `limit`, `cursor` | Scheduled events with their bouts and current odds, soonest first |
<!-- routes:end -->

`/data/v1/status` carries a `datasets` block per sport (`nfl`, `mlb` beside the UFC one): record count, newest date
and age for UFC and NFL; for MLB each store's `through`, `lag_days` and `stale` from the existing freshness
module, with the basis of its history.

## Three examples

They are executed from this file by `tests/test_datasvc_client_docs.py` against synthetic stores, so they cannot
drift. In each, `client` is `DataClient()`.

A UFC packet, and what to do when there is none:

<!-- example: ufc_matchup -->
```python
packet = client.matchup("ufc", a="Alex Archer", b="Ben Brawler")
if packet["available"]:
    version = packet["meta"]["data_version"]
    odds_basis = packet["meta"]["datasets"]["odds"]["basis"]       # reconstructed_later: not our own capture
    open_questions = [m["item"] for m in packet["meta"]["missing"]]
else:
    reasons = packet["missing"]                                     # why there is no packet; never a guess
```

An NFL closing line is one value per game, not a point-in-time price:

<!-- example: nfl_closing_line -->
```python
quote = client.quotes("nfl", game_id="2025_01_BUF_KC")
if quote["available"]:
    spread = quote["data"]["market"]["spread"]["nflverse_spread_line"]   # positive when the home team is favoured
    one_value = quote["data"]["basis"] == "single_value_per_record"
```

The MLB packet is the analyst's, with the stores' coverage beside it:

<!-- example: mlb_packet -->
```python
answer = client.matchup("mlb", date="2026-10-03", away="NYY", home="TB")
if answer["available"]:
    packet = answer["data"]                            # exactly what the analyst builds
    markets = list(packet["markets"])                  # moneyline, run_line, total, ...
    coverage = answer["meta"]["coverage"]["results"]   # {"through": ..., "stale": ...}
    version = answer["meta"]["data_version"]
else:
    why = answer["missing"][0]["reason"]
```
