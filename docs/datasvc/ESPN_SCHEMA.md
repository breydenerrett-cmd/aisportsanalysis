# ESPN-fed leagues: schema and operation

Code: `src/datasvc/espn/`. Data: `data/datasvc/espn/<league>/` (git-tracked, copied into the image by
`deploy/Dockerfile`, admitted in `.dockerignore`). Raw pages: `data/datasvc/raw/` (git-ignored; every fetched URL
is cached, so a re-run never refetches a settled page). Leagues: nba, wnba, nhl, ncaaf, ncaab, ncaaw, epl, laliga,
bundesliga, seriea, ligue1, mls, ucl (`leagues.py`). Scheduled set: nba, nhl, ncaaf, ncaab, epl.

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

## Read API

`DataClient().league("nba")` returns a view with `teams, players, schedule, game, team_history, player_history,
standings, injuries` (all take `as_of`); `.capabilities()` says what a league cannot answer and why. Answers are
`{"available": True, sport, kind, data, meta}` or `{"available": False, "missing": [...]}`; `meta` has the source,
attribution, `built_utc`, `as_of`, and the newest `observed_utc` read.

## Politeness

One request at a time, 0.35 s apart, real User-Agent, backoff on 429/5xx honouring Retry-After, a per-run request
cap, an on-disk cache. Terms: ESPN's site JSON is undocumented and public; there is no stated rate limit or licence,
so this is internal analysis, with attribution kept in the manifest. A browser check or CAPTCHA raises
`SourceBlocked` and the run stops; nothing tries to pass it. `cdn.nba.com` returned 403 and `stats.nba.com` did not
connect from the dev machine: both are marked blocked in COVERAGE_MATRIX.md and are not used.
