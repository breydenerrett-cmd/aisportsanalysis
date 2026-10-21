# ESPN-fed leagues: schema and operation

Code: `src/datasvc/espn/`. Data: `data/datasvc/espn/<league>/` (git-tracked, copied into the image by
`deploy/Dockerfile`, admitted in `.dockerignore`). Raw pages: `data/datasvc/raw/` (git-ignored; every fetched URL
is cached, so a re-run never refetches a settled page). Leagues: nba, wnba, nhl, ncaaf, ncaab, ncaaw, epl, laliga,
bundesliga, seriea, ligue1, mls, ucl (`leagues.py`). Scheduled set (`python -m src.cli datasvc all refresh`): nba, nhl,
ncaaf, ncaab, epl, then (added in round 2) wnba, ncaaw, laliga, bundesliga, seriea, ligue1, mls, ucl. The six added
soccer leagues keep team totals only (`players=False`): their squad lines are ~9 MB a league-season each, ~45 MB a
season for the repository and the web image, and flipping the flag in `leagues.py` turns them on. Estimated growth of
the tracked files for the eight added leagues, per full season: ~19 MB (NCAAW ~12 MB of it; WNBA ~2 MB with players;
five soccer leagues plus MLS and the Champions League ~1 MB each).

## Append-only, point-in-time

Every row has `observed_utc` (when we fetched it). Rows are never changed or removed. A fact that changes (game
goes final, injury status moves) is appended as a new version; an identical re-fetch writes nothing (files are
byte-identical). The file key is (dataset key, `observed_utc`). Reads: newest version, or
`as_of=<instant>` = newest version observed at or before it. A game first fetched after `as_of` does not exist for
that read. Backfilled rows have `observed_utc` = backfill time (RECONSTRUCTED); forward rows are OBSERVED.
Injury rows that leave the report get a `status: "Cleared"` row, so absence is recorded; an empty feed never clears
anyone.

## Files (season-partitioned ones are `<name>_<season>.jsonl`)

| Dataset | Key | Notes |
|---|---|---|
| `teams` | team_id | abbreviation, name, location, display_name, short_name, colors, logo, is_active |
| `players` | team_id, player_id | weekly roster snapshot (pro leagues): name, position, jersey, height_in, weight_lb, age, birth_date, status |
| `games_<season>` | game_id | date_utc, state (pre/in/post), status, completed, home_/away_ id, abbr, name, score, winner, venue, attendance, neutral_site, season, season_type, period, `scoreboard_date` (ESPN's US-evening day), `espn_odds` when ESPN lists a line. Scores absent until the game starts |
| `team_games_<season>` | game_id, team_id | `stats`: {ESPN key: display string} (e.g. `"fieldGoalsMade-fieldGoalsAttempted": "38-83"`), home_away, opponent_id, points, points_against |
| `player_games_<season>` | game_id, player_id | `stats`: {group: {key: display string}} (group `all` for basketball/soccer, `forwards`/`defenses`/`goalies` hockey, `passing`/`rushing`... football), starter, did_not_play. Off for college leagues (about 100 MB per season) |
| `standings_<season>` | season, group, team_id | `stats`: {name: display string}; group = conference/division path |
| `injuries` | team_id, player_id | status, injury_type/location/detail/side, return_date, comment, reported_utc |
| `MANIFEST.json` | | record counts, newest, sha256, `refreshed_utc` (the refresh gate reads it) |

Values are ESPN's display strings, unconverted (ratios, minutes and counts share fields); only ids, scores and
attendance are integers. Missing = absent, never 0. `season` is ESPN's season year (NBA/NHL/NCAAB: the year it
ends; EPL 2025-26 = 2025; NCAAF: the fall year).

## Commands

```
python -m src.cli datasvc all refresh --min-age-minutes 180 --max-requests 400     # what capture_slot.sh runs
python -m src.cli datasvc nhl backfill --from 2025-10-01 --to 2026-04-20
python -m src.cli datasvc nba schedule --date 2026-01-15 [--team ORL] [--as-of 2026-01-15T23:00:00Z]
python -m src.cli datasvc nba box --game-id 401810433
python -m src.cli datasvc nba history --team ORL | --player-id 4277961
python -m src.cli datasvc epl standings | injuries | teams | players --team ARS | status | check
```

`refresh`: teams (weekly), scoreboards today-2..today+2, box scores for games that went final (and once more a day
after, for stat corrections), standings, injuries, rosters (weekly), manifest. `--min-age-minutes` makes it a no-op
(no network) when the manifest says it ran recently. Also `python -m src.datasvc.cli espn ...`; `src.cli datasvc
ufc|nfl ...` forwards to those layers. Exit codes: 0 ok, 1 parity check failed, 2 blocked source / bad argument.

## Season averages and splits (round 2)

`team_averages`, `team_splits`, `player_averages` and `player_splits` (`src/datasvc/espn/aggregate.py`) aggregate
the stored box scores; nothing new is fetched. For a team: record, points for and against, margin, every box-score
stat averaged (`stats`) and what its opponents did against it (`allowed`). For a player: games, starts, and per
group (`all`, `forwards`/`defenses`/`goalies`, ...) the same stat summaries. Each stat is read by shape: a number
(`avg`, `total`), a ratio such as `38-83` (`made_avg`, `att_avg`, volume-weighted `pct`), or a clock (`avg` as
mm:ss). A key present in some games only is averaged over those (`games` says how many).

Splits: `all`, `home`, `away`, `wins`, `losses`, `last3`/`last5`/`last10`/`lastN`, and for players `starter`, `bench`.
`season_type` defaults to `regular` (drops ESPN preseason, type 1; soccer keeps everything); `all` or ESPN type
numbers override it. Soccer rows count only appearances (the roster lists the whole squad).

POINT IN TIME. With `as_of=T` a game is used only if it was final by T:

| basis | meaning | box score used |
|---|---|---|
| `observed` | a version of the game saying "final" was observed at or before T (forward capture) | newest version observed at or before T |
| `reconstructed` | first seen final after T (a backfill: `observed_utc` is the backfill time) but it kicked off at least the per-sport allowance before T (NBA/NHL 3.5 h, football 4.5 h, soccer 2.75 h, baseball 5 h) | earliest stored version |

Anything that kicked off later, or might still have been playing at T, is excluded; `strict=true` keeps `observed`
games only. `meta.game_basis` counts both bases and the exclusions, so a caller sees how much of a past average
is reconstructed. Team names resolve against the newest `teams` rows even under `as_of` (an id is not an outcome).

```
python -m src.cli datasvc nhl averages --team BUF --split home            # one team, one split
python -m src.cli datasvc nhl splits --team BUF --as-of 2026-10-10T00:00:00Z
python -m src.cli datasvc nba averages --players --team ORL --min-games 3
python -m src.cli datasvc epl averages --player-id 134190 --last 5
```

## Play-by-play (round 2)

`python -m src.cli datasvc nhl refresh --pbp` stores plays for completed games (NBA, WNBA, NHL, NCAAF; opt-in);
`pbp-fill [--limit N] [--season S] [--source espn|nhle]` backfills stored games, resumably;
`pbp --game-id ID [--source nhle] [--period P] [--scoring-only] [--as-of T]` reads one. Sources: `espn` = the
`plays` list of the box-score page (college football: `drives[*].plays`, plus one `k:"drive"` line per drive),
fetched with the box score, no extra request; `nhle` = api-web.nhle.com `gamecenter/<id>/play-by-play`, matched to
the ESPN game by the two clubs' full names and the UTC kickoff date (one schedule-week request, then one request
per game), stored under the ESPN `game_id` with `nhle_game_id` and the roster in the header.

Files: `<league>/pbp_<season>.jsonl.gz` (one gzip member per game and source, appended, never rewritten) and
`pbp_<season>.index.jsonl` (game_id, source, observed_utc, byte offset and length, event count, sha256). An
identical re-fetch writes nothing; changed plays (ESPN patches them for about a day) append a new member, and
`as_of` reads the version known then. `check` re-reads every member against its index line.

Event keys: `n` sequence, `id` play id, `per` period, `clk` clock, `type`/`tid`, `txt`, `team`, `as`/`hs` score
after the play, `ts` wall clock, `sc` scoring play (+`pts`), `shoot`, `att`, `pen`, `to`, `x`/`y` (ESPN's
out-of-range sentinel coordinates are dropped), `ply` athlete ids with `plt` roles, `str` strength; football adds
`drive`, `off`, `down`, `dist`, `yte`, `edown`/`edist`/`eyte`, `yds`, `stype`; `nhle` events keep the feed's
`details` as `d` (coordinates, shot type, shooter, goalie in net, running shots).

SIZE (measured on real games 2026-10-20, 6 per league): gzip per game NBA 14.7 KB (502 plays), NHL 10.3 KB ESPN and
9.9 KB `nhle` (316 plays), NCAAF 10.2 KB (178 plays), WNBA ~12 KB. Per full season (regular + post): NBA ~19 MB,
NHL ~14 MB ESPN + ~14 MB `nhle`, NCAAF ~9 MB, WNBA ~3 MB: **~43 MB for NBA + NHL + NCAAF from ESPN, ~57 MB with the
NHL feed**. That is why play-by-play is a local, rebuildable cache: `data/datasvc/espn/*/pbp_*` is git-ignored and
excluded from the web image (`.gitignore`, `.dockerignore`), `refresh` skips it unless `--pbp` is passed, and the
manifest does not list it. To track it, delete the `.gitignore` line.

## Read API

`DataClient().league("nba")` returns a view with `teams, players, schedule, game, team_history, player_history,
standings, injuries, team_averages, team_splits, player_averages, player_splits, play_by_play` (all take `as_of`);
`.capabilities()` says what a league cannot answer and why. `DataClient().mlb_box()` is the same view over the MLB
statsapi box-score layer (docs/datasvc/MLB_STATSAPI.md). Answers are
`{"available": True, sport, kind, data, meta}` or `{"available": False, "missing": [...]}`; `meta` has the source,
attribution, `built_utc`, `as_of`, and the newest `observed_utc` read.

## Politeness

One request at a time, 0.35 s apart, real User-Agent, backoff on 429/5xx honouring Retry-After, a per-run request
cap, an on-disk cache. Terms: ESPN's site JSON is undocumented and public; there is no stated rate limit or licence,
so this is internal analysis, with attribution kept in the manifest. A browser check or CAPTCHA raises
`SourceBlocked` and the run stops; nothing tries to pass it. `cdn.nba.com` returned 403 and `stats.nba.com` did not
connect from the dev machine: both are marked blocked in COVERAGE_MATRIX.md and are not used.
The NHL's api-web feed (play-by-play) and the football-data and statsapi layers go through the same fetcher (one request at a time, 0.35 s apart; the
football-data fetch is slower and gated, see SOCCER_HISTORY.md). Sites that answered 403 to a plain client (`ncaa-api.henrygd.me`, TheSportsDB's shared key) were left alone.
