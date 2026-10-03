# NFL data layer: the contract

Every module in `src/datasvc/nfl/` reads and writes the shapes below. They are fixed in the
same sense as `UFC_SCHEMA.md`: a module that needs a new field adds it, never renames or
repurposes one. Written 2026-10-03 from real nflverse release files fetched that day through
`src.datasvc.http.PoliteFetcher` (the measurements below are of those downloads, not recalled).
The features, the matchup sheet and the API built on these files are described in
[`NFL_FEATURES.md`](NFL_FEATURES.md).

## Sources

All files are GitHub release assets of `nflverse/nflverse-data`, plain CSV, no login, no
browser check. **License: CC BY 4.0. Attribution is kept:** every record's `source` names the
nflverse file it came from, `MANIFEST.json` carries the attribution line, and the API's
`/status` repeats it. The existing `src/providers/nfl.py` reads three of the same files for the
NFL card; this layer does not change it.

Base: `https://github.com/nflverse/nflverse-data/releases/download`

| File | Path under the base | Seasons that answer | Measured 2026-10-03 |
|---|---|---|---|
| Schedule and results | `schedules/games.csv` | 1999 to 2026 in one file | 2,182,448 bytes, 7,548 games, 46 columns |
| Team stats by week | `stats_team/stats_team_week_{season}.csv` | 1999 and 2021 to 2026 answered 200 (the years between were not fetched) | 2025: 229,660 bytes, 570 rows, 138 columns; 2026 so far: 98 rows; 1999: 517 rows |
| Player stats by week | `stats_player/stats_player_week_{season}.csv` | 1999 and 2021 to 2026 answered 200 (the years between were not fetched) | 2025: 8,656,387 bytes, 19,422 rows, 150 columns; 2026 so far: 3,407 rows; 1999: 16,839 rows |
| Injury reports | `injuries/injuries_{season}.csv` | 2009 and 2021 to 2026 answered 200; 2008 answers 404 | 2025: 696,006 bytes, 6,068 rows, 16 columns; 2026 so far: 1,047 rows; 2009: 4,821 rows |

Seasons 2021 to 2026 were each fetched and parsed (all four files answered 200 every time).
Every request in the build went through one `PoliteFetcher` (cache, spacing, cap, browser-check
stop). Nothing in this layer opens another connection.

**Evaluated and not used**

| Candidate | What was measured | Why not |
|---|---|---|
| `depth_charts/depth_charts_2025.csv` | 52,917,870 bytes, 554,215 rows, 12 columns (`dt`, `team`, `gsis_id`, `pos_abb`, `pos_slot`, `pos_rank`, ...): ESPN daily snapshots | 50 MB a season for something the schedule file already answers: `games.csv` carries each game's starting quarterback (projected for games not yet played) |
| `rosters/roster_2025.csv` | 1,010,039 bytes, 3,137 rows, 36 columns (one row per player per season: status, birth date, college, draft) | Player attributes, not point in time. Nothing requested needs them |
| `roster_weekly/roster_weekly_2025.csv` | answers 404 at this path | n/a |
| play by play (`pbp/`) | not fetched (tens of MB a season) | The weekly team and player files already carry the yards, plays, turnovers and EPA the features use |
| snap counts | not fetched | Would make "played but had no stat" visible; see section 9 of `NFL_FEATURES.md` |

**Columns used.** Everything below is read by name, never by position, and a column that is
absent is a missing value, not an error. The measured differences between seasons:
`injuries_2009` to `injuries_2024` carry `date_modified` (the report's timestamp) and no
`season_type`; `injuries_2025` and `injuries_2026` carry `season_type` and **no timestamp at
all**. The stats files have identical columns for every season 1999 to 2026, and both carry
`game_id` (the same id the schedule uses), so a stats row joins to its game without guessing.

## Fetching rules

- One `PoliteFetcher`. Historical files are cached forever; the live ones (the schedule and
  the current season's three files) are re-fetched when the cached copy is older than
  `LIVE_MAX_AGE_S` (1 hour), so running `update` twice in a row costs no request.
- A 404 for a season file is recorded in the run summary (`missing_files`), never an error: a
  new season's stats do not exist before its first game.
- A browser check (`SourceBlocked`) or the request cap stops the whole run at once and keeps
  everything already saved. Nothing here works around either.
- A bad response never erases anything. nflverse replaces its release assets in place, so a file can 404 for a
  moment, arrive empty or arrive partial. The schedule is used only if it has `game_id` and `gameday` columns, and a
  stored unplayed game is marked `removed` only when the whole file read cleanly (no unreadable row) and the game is
  absent from it. A team statistics row that is missing from the file never replaces one the store already holds
  (`team_rows_kept_with_their_stored_statistics` in the run summary counts them). Each of these has a test.
- CSV is read with `csv.reader` over `io.StringIO(text, newline="")`. `str.splitlines()` (what
  `src/providers/nfl.py` does) cuts a row in two wherever a quoted field holds a line break, and
  the injuries files do: 45 of the 2021 rows have a practice status of `"\n    "`.

## Time

- **Kickoff.** The schedule gives `gameday` (the Eastern calendar date) and `gametime` (Eastern,
  24-hour). `kickoff_utc` is computed from those with US Eastern daylight rules written out in
  `src/datasvc/nfl/timeutil.py` (second Sunday of March to first Sunday of November from 2007,
  first Sunday of April to last Sunday of October for 1987 to 2006). It does **not** use a time
  zone database: this machine, and any container without `tzdata`, has none, and
  `src/providers/nfl.start_utc` then silently falls back to a fixed UTC-4 that is wrong for every
  game from November to February. A test compares the written rules with `zoneinfo` wherever it
  is available.
- Instants are ISO strings in UTC with seconds and a `Z` (`2026-09-10T00:20:00Z`).
- **The leakage rule.** A game counts as of an instant `as_of` only if `kickoff_utc + 6 hours <=
  as_of` and it has a result. The source gives no finish time; 6 hours (`FINISH_ALLOWANCE`) is a
  safe upper bound on a game with overtime and a weather delay, so an `as_of` in the middle of
  a game never sees its score. A bare date is the start of that day, 00:00 UTC (the UFC rule).
  Because the rule is on the kickoff instant in UTC, a Sunday night game (kickoff 00:20 UTC
  Monday) belongs to Monday: an `as_of` of Monday's bare date does not count it. That is the
  conservative direction.

## Files (`data/datasvc/nfl/`, tracked) and the raw cache (`data/datasvc/raw/`, not tracked)

Names, keys and the date field for "newest" are in `src/datasvc/nfl/store.py` (`FILES`, `KEYS`,
`DATE_FIELDS`). Save through `NflStore.upsert(name, records)`. Every record carries `source`
(`nflverse:` plus the file name, for example `nflverse:stats_player_week_2025`) and
`fetched_utc`. **`fetched_utc` is when this exact content was first fetched:** an update that
finds a row unchanged leaves the stored row, and its `fetched_utc`, alone, so a daily run
rewrites only the rows that changed and a file that did not change keeps its bytes and its
modification time. Ids are strings, numbers are numbers, an absent value is `null`.

### games.jsonl (key `game_id`): one row per game, played or scheduled

| Field | Type | From |
|---|---|---|
| game_id | str | `game_id` (`2025_01_DAL_PHI`: season, week, away, home) |
| season, week | int | `season`, `week` (regular season 1 to 18; wild card 19, divisional 20, conference 21, Super Bowl 22) |
| game_type | str | `game_type`: REG, WC, DIV, CON, SB |
| gameday | str | `gameday`, the Eastern calendar date |
| weekday | str | `weekday` |
| kickoff_et | str or null | `gametime`, "HH:MM" Eastern, null when blank |
| kickoff_utc | str or null | computed (Time, above) |
| status | str | `final` (both scores, and the record was fetched at least 150 minutes after kickoff), `in_progress` (scores present sooner than that), `scheduled`, `no_result` (kickoff more than 12 hours before the fetch and still no score), `removed` (stored earlier, gone from the source, never final) |
| home_team, away_team | str | nflverse codes (`LA` is the Rams, `LV` the Raiders; `src/sports/nfl_teams.abbrev` resolves other spellings) |
| home_score, away_score | int or null | |
| overtime | bool or null | `overtime` (blank before the game: null) |
| neutral_site | bool | `location == "Neutral"` |
| stadium_id, stadium | str or null | the source's id and the name it had that season (the id is stable across renamings) |
| venue_check | str | `ok`, `nominal_home_stadium_on_neutral_site` or `stadium_id_name_conflict` (below) |
| roof | str or null | outdoors, dome, closed, open (the last two are a retractable roof's state), null when blank |
| surface | str or null | lower case, trimmed (the source has both `grass` and `grass ` with a trailing space) |
| temp_f, wind_mph | int or null | observed conditions, recorded for outdoor and open-roof games only |
| div_game | bool or null | `div_game` |
| home_rest_days, away_rest_days | int or null | the source's days since the team's previous game (7 in week 1 by convention) |
| home_coach, away_coach, referee | str or null | |
| home_qb_id, home_qb_name, away_qb_id, away_qb_name | str or null | the starting quarterback. **For a game not yet played this is the source's projected starter**, not a fact: it is filled for the current week and the next (measured 2026-10-03: all 16 week-4 games and 15 week-5 games had one, week 6 had none) and replaced by the actual starter once the game is final |
| spread_line | float or null | `spread_line`, **positive when the home team is favoured** (checked on 1,503 games since 2021 that carry a spread and both moneylines: the sign agrees with which side has the shorter moneyline in 1,496 and disagrees in 7) |
| total_line | float or null | |
| home_moneyline, away_moneyline | int or null | American prices |
| home_spread_odds, away_spread_odds, over_odds, under_odds | int or null | American prices |
| espn_id, pfr_id, gsis_id | str or null | cross ids |
| source, fetched_utc | str | |

The market columns are the source's single value per game. nflverse overwrites them as the
market moves until kickoff, so for a game that is final they are the closing numbers, and for
a game still to be played they are the latest numbers at `fetched_utc`. **They are never an
as-of-date value** and the matchup sheet labels them `as_of_safe: false`.

**`venue_check`.** The schedule's venue is wrong for 8 of the 1,696 games since 2021 (measured
2026-10-03), in two ways, and each is flagged by a rule that reads only the file:

- For seven neutral-site games of the 2025 season the source names the nominal home team's own
  stadium (`2025_04_MIN_PIT` is listed at `PIT00` Acrisure Stadium, `2025_01_KC_LAC` at `LAX01`
  SoFi Stadium, `2025_07_LA_JAX` at `JAX00`, and so on): a neutral game cannot be played at a team's
  own stadium that the schedule also calls neutral, and these are the season's international games.
  A game is flagged `nominal_home_stadium_on_neutral_site` when `neutral_site` is true and its
  `stadium_id` is the stadium that `home_team` used for its home games that season. Every other
  neutral game of 2021 to 2026 (33 of the 40) names a stadium that is not the nominal home team's
  own (London, Munich, Frankfurt, Mexico City, Melbourne, Rio de Janeiro, Madrid, Paris, Sao Paulo,
  or a US host city) and is not flagged.
- One 2026 home game, `2026_05_PHI_JAX`, has the id `JAX00` (Jacksonville) and the stadium name
  "Tottenham Hotspur Stadium" (London). It is flagged `stadium_id_name_conflict`: the id has two
  names that season and this row carries the rarer one.

The travel features treat a flagged venue as unknown (missing, with the reason) rather than compute
a distance to the wrong city. No venue is corrected from memory, and the home-stadium table
(`venues.home_stadium_ids`) ignores flagged games.

### team_games.jsonl (key `game_id`, `team`): one row per team per game

Two rows per game, built from `games` and the team stats file. Rows exist for scheduled games
too (every statistic null, `has_stats` false).

| Field | Type | From |
|---|---|---|
| game_id, team, opponent | str | |
| season, week, game_type | | as in games |
| kickoff_utc | str or null | |
| status | str | the game's status |
| site | str | `home`, `away` or `neutral` |
| points_for, points_against, margin | int or null | from the scores; margin = for minus against, only when the game is final |
| result | str or null | `W`, `L`, `T`, only when the game is final |
| overtime | bool or null | |
| rest_days_source | int or null | the source's rest days for this team |
| coach | str or null | |
| qb_id, qb_name | str or null | starting quarterback (projected until final) |
| has_stats | bool | the team's row of the stats file was found |
| pass_attempts, completions, passing_yards, passing_tds | number or null | `attempts`, `completions`, `passing_yards`, `passing_tds` |
| interceptions | number or null | `passing_interceptions`, thrown |
| sacks_taken, sack_yards_lost | number or null | `sacks_suffered`; `sack_yards_lost` is stored **positive** (the source writes it negative: measured on 2,542 rows with a sack, 0 positive) |
| carries, rushing_yards, rushing_tds | number or null | |
| fumbles_lost | number or null | `fumbles_lost_total`: all of the team's lost fumbles, special teams included (it exceeds the sum of the sack, rushing and receiving columns on 208 of 2,946 rows) |
| penalties, penalty_yards | number or null | |
| passing_first_downs, rushing_first_downs | number or null | |
| passing_epa, rushing_epa | float or null | rounded to 3 decimals |
| sacks_made, def_interceptions | number or null | `def_sacks`, `def_interceptions` |
| plays | number or null | `pass_attempts + sacks_taken + carries` |
| net_yards | number or null | `passing_yards - sack_yards_lost + rushing_yards` |
| yards_per_play | float or null | `net_yards / plays`, 4 decimals |
| giveaways | number or null | `interceptions + fumbles_lost` |
| takeaways | number or null | the **opponent's** giveaways in this game (null when the opponent's row is missing) |
| turnover_margin | number or null | `takeaways - giveaways` |
| source, fetched_utc | str | |

`takeaways` is the opponent's giveaways rather than the team's own `def_interceptions +
fumble_recovery_opp` so that the two teams' margins in a game always sum to zero. The two
definitions disagree on 11 of 2,946 team games (0.4%).

### player_games.jsonl (key `game_id`, `player_id`): offensive usage and production

One row per player per game from the weekly player file. **Kept rows:** every row whose
position group is quarterback, running back (fullbacks included), wide receiver or tight end,
and any other row with a pass attempt, a carry or a target. Defensive, line and kicking rows
are not stored (measured for 2025: 6,432 of 19,422 rows kept). Rows with no `player_id` (22 a
season) cannot be keyed and are counted in the run summary, not stored.

**Seasons.** This is the largest file (about 620 bytes a row), so the committed copy holds the
seasons **2024, 2025 and 2026 to date** (13,809 rows, 8.5 MB); the same rows for 2021 to 2023
(about 18,700 more, 11.6 MB) were left out to keep the committed data modest, and
`MANIFEST.json` says so (`coverage.player_games_since: 2024`, kept by every later update). The
features need the current season and the one before it. `nfl backfill --player-since 2021` brings
the earlier seasons back from the raw cache or the source.

| Field | Type | From |
|---|---|---|
| game_id, player_id | str | `game_id`; `player_id` (the GSIS id, `00-0023459`, the same id the injuries file and the schedule's quarterback columns use) |
| season, week, game_type, kickoff_utc | | from the game |
| team, opponent | str | `team`, `opponent_team` |
| name | str | `player_display_name` |
| position | str | `position` |
| position_group | str | QB, RB, WR, TE, OL, DL, LB, DB, ST, OTHER (the table in `store.POSITION_GROUPS`, the same one the injuries use) |
| pass_attempts, completions, passing_yards, passing_tds | number | `attempts`, `completions`, `passing_yards`, `passing_tds` |
| interceptions | number | `passing_interceptions`, thrown |
| sacks_taken | number | `sacks_suffered` |
| carries, rushing_yards, rushing_tds | number | |
| targets, receptions, receiving_yards, receiving_tds | number | |
| target_share, air_yards_share | float or null | the source's shares of the team's targets and air yards, rounded to 4 decimals |
| source, fetched_utc | str | |

**What a row is.** The source writes a row for a player who recorded any statistic in the game
(offence, defence or special teams). An offensive player who played and recorded nothing has no
row, so a row means "has a stat line", not "was on the field". The features say so wherever they
count games (section 5 of `NFL_FEATURES.md`).

### injuries.jsonl (key `game_id`, `player_id`): the weekly injury report

One row per player on a team's report for the week, joined to that team's game of the week
(`season`, `week`, `team` to `game_id`). Of the 30,198 rows of 2021 to 2026, 30,181 joined; the
17 that did not are the 2022 week 17 rows of the two teams whose game was cancelled (it is not in
the schedule file) and are counted, not stored. **Kept rows:** a row with a game-status
designation (`report_status`) or a practice status other than full participation. A row that only
says "full participation" with no designation is not stored (measured: 39% of 2021's rows, 43% of
2025's, 12,204 of the 30,198): it says nothing about availability. The run summary counts what was
dropped, so source rows = stored + dropped + duplicates is checkable (17,972 stored + 12,204 full
participation only + 3 with no status + 17 with no game + 2 duplicates = 30,198).

| Field | Type | From |
|---|---|---|
| game_id, player_id | str | joined; `gsis_id` |
| season, week, game_type | | |
| team | str | |
| name | str | `full_name` |
| position, position_group | str or null | `position` (whitespace trimmed; null when blank), grouped as above |
| report_status | str or null | `out`, `doubtful`, `questionable`, `note`, or the lower-cased source text of any other value; null when the player has no designation |
| report_injury, report_injury_2 | str or null | `report_primary_injury`, `report_secondary_injury` |
| practice_status | str or null | `full`, `limited`, `dnp`, `note`, or the lower-cased source text; null when blank |
| practice_injury, practice_injury_2 | str or null | |
| date_modified | str or null | the report's timestamp (`2021-09-10T19:35:39Z`) where the file has one (seasons up to 2024), else null |
| source, fetched_utc | str | |

Duplicate rows for one player in one week (2 pairs in 2024) are resolved to the row with the
latest `date_modified`, ties to the later line.

**When is an injury row known?** Where `date_modified` exists, at that instant. Where it does
not (2025 and 2026) the file is one final report per team and week, and the features treat it as
published 24 hours before that team's kickoff (`INJURY_REPORT_LEAD`): the NFL issues the final
game-status designations one to two days before a game (for a Thursday game, on the Wednesday,
about 28 hours before). **That 24 hours is an assumption, not a measurement.** An `as_of`
earlier than that gets no injury figure, with the reason. 3 of 5,587 rows in 2021 and 1 of 6,215
in 2024 are stamped on a later day than their game (a Thursday game's report updated the next
morning); those are excluded from any as-of earlier than their stamp.

## What is on disk (the committed backfill, 2026-10-03)

Produced by `python -m src.datasvc.cli nfl backfill --since 2021 --player-since 2024`; a second run and an
`update` straight after changed no byte of any file.

| File | Records | Bytes | Covers |
|---|---|---|---|
| `games.jsonl` | 1,696 | 1,786,169 | every game of 2021 to 2026: 1,473 final, 223 scheduled |
| `team_games.jsonl` | 3,392 | 3,349,368 | two rows per game |
| `player_games.jsonl` | 13,809 | 8,531,446 | 2024, 2025 and 2026 to date |
| `injuries.jsonl` | 17,972 | 8,363,160 | 2021 to 2026 (the rows that carry information) |
| `MANIFEST.json` | | about 2.3 KB | per-file records, newest, bytes and sha256, the attribution, the coverage, the last run |

22,030,143 bytes of data in all. The raw files they were cut from (about 100 MB for the six seasons) are in
`data/datasvc/raw/`, which is git-ignored and never shipped. `nfl status --check` runs nine parity checks over these
files (all pass).

## Position groups

`store.POSITION_GROUPS` maps the source's positions: QB; RB (RB, FB, HB); WR; TE; OL (OT, T, G,
OG, C, OL); DL (DE, DT, NT, DL); LB (LB, OLB, ILB, MLB); DB (CB, S, SS, FS, SAF, DB); ST (K, P,
LS, PK); anything else OTHER.

## Measured source quirks, handled

| Quirk | Handling |
|---|---|
| `games.csv` has `surface` values `grass ` (trailing space) and `grass` | trimmed and lower-cased |
| `overtime`, `temp`, `wind`, scores are blank for a game not played | null, never zero |
| `games.csv` names the nominal home stadium for seven of 2025's neutral games, and one 2026 home game has a stadium id and name that disagree | `venue_check`, above |
| Projected quarterbacks on unplayed games | stored, flagged by `status`; features label them `projected` |
| A game cancelled and dropped from the source (the 2022 Bills at Bengals game is absent from the file: 284 games, 568 team rows) | an earlier stored copy becomes `removed`; it is never deleted |
| `injuries` file without `date_modified` from 2025 | the 24-hour rule above |
| `injuries` `practice_status` of `"\n    "` and positions of `"\n    "` (2024: 12) | trimmed; blank becomes null |
| `sack_yards_lost` negative | stored positive |
| 22 player rows a season with no id, name or position | counted, not stored |

## Who owns what

| Module | Exposes |
|---|---|
| `src/datasvc/nfl/timeutil.py` | `eastern_to_utc`, `utc_offset_hours`, `season_of` |
| `src/datasvc/nfl/venues.py` | the stadium table with its citation, `haversine_miles`, `venue` |
| `src/datasvc/nfl/sources.py` | URLs, `parse_games`, `parse_team_stats`, `build_team_games`, `parse_player_stats`, `parse_injuries`, `fetch_*` |
| `src/datasvc/nfl/store.py` | `NflStore`, `FILES`, `KEYS`, `DATE_FIELDS`, `POSITION_GROUPS`, `compact` |
| `src/datasvc/nfl/pipeline.py` | `backfill`, `update`, `status`, `check` |
| `src/datasvc/nfl/features.py` | `team_features_as_of`, `player_features_as_of`, `game_features`, `completed_games` (the gate) |
| `src/datasvc/nfl/matchup.py` | `matchup`, `find_game`, `market_block` |
| `src/datasvc/nfl/cli.py`, `src/datasvc/cli.py`, `api/datasvc.py` | the `nfl` subcommands (registered by `src/datasvc/cli.py`); `/data/v1/nfl/...` |

## Rules for every module

- No leakage: a feature computed as of an instant uses only games that finished before it
  (`features.completed_games` is the one place a game is admitted).
- Missing data is null and listed, never guessed or filled with an average.
- Parsers are pure functions over CSV text; tests run them on saved excerpts of the real files
  and on synthetic ones, with no network.
- stdlib only in `src/`. Route tests are `skipUnless(HAS_FASTAPI)`.
- Forward-captured data is append-only in spirit: an update upserts changed rows and never
  deletes one.
- Never touch the LineHound card rules, ledgers or the fingerprinted files, `src/situation/`,
  `src/analyst/`, `src/providers/nfl.py`, or anything under `.github/`.
