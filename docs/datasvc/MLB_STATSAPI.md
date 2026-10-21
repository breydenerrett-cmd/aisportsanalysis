# MLB statsapi box scores and player game logs (forward only)

Code: `src/datasvc/mlb/{seal,statsapi,box_service,box_cli}.py`. Store: `data/datasvc/mlb/` (**git-ignored, not in the web
image**). Reads: `DataClient().mlb_box()` and `python -m src.cli datasvc mlbbox ...`.

## Scope and the sealed window

* **Forward from 2026-10-20 only** (`seal.FORWARD_FROM`): no backfill. The refresh takes `days_back=1, days_ahead=1` around
  today and skips any day before the floor (reported as `skipped_before_floor`).
* **MLB outcomes dated 2026-01-01..2026-08-27 are never read.** Enforced at every door, each with a test
  (`tests/test_datasvc_mlb_statsapi.py`): the URL guard (only an open day's schedule, the box score of a game that schedule
  listed, and the static teams list are allowed; a sealed day, an overlapping date range, any season-2026 stats request and
  the season-wide `gameLog` endpoint are refused before any request), the parser (a payload carrying a sealed game raises),
  the store (write refuses, reads drop), the read API (a sealed date or `as_of` is refused by name) and `check`.
* The player game log is built from the box scores (a player's log = his lines across the games stored). The season-wide
  `people/<id>/stats?stats=gameLog` endpoint would return sealed games, so it is never called.
* **Season-to-date fields are not stored.** A box score carries `seasonStats`, rate strings (`avg`, `era`, `whip`), a team's
  win-loss record and decision notes such as "(W, 2-0)": all cumulative over games that include sealed ones. Only
  integer counting stats of the game itself are kept, and innings pitched is stored as `outs` (6.1 IP = 19), because
  "6.1" averages wrongly as a decimal.

## Requests and terms

Per day: 1 schedule request per day in the window (3 by default) + 1 box-score request per finished game (15-30 in season),
0.35 s apart through the polite fetcher; `teams` once a month. MLBAM's notice (in every response, `gdx.mlb.com/components/
copyright.txt`) permits only individual, non-commercial, non-bulk use and requires written authorization otherwise. The
project already depends on statsapi for schedules; this layer is internal analysis and should be settled with the owner
before it backs a paid surface.

## Rows (versioned, `observed_utc` on every row)

* `games_<season>`: game_id (gamePk), `date` (the local official date), `date_utc`, state (`pre`/`in`/`post`), completed,
  scores, per-inning runs (`home_line`, `away_line`: first-five-innings totals are one slice away), hits, errors, venue,
  game type (`season_type` 3 = postseason), winning/losing/save pitcher ids.
* `team_games_<season>`: `stats` flat, `bat.hits`, `pit.earnedRuns`, `pit.outs`, `fld.errors`, ...
* `player_games_<season>`: `stats` {`batting`|`pitching`|`fielding`: {count: int}}, `starter` (batting order x00, or a pitcher who
  started), position, batting order. A player with no plate appearance and no pitch has no row.
* `teams`: abbreviation, names (30 clubs).

The ESPN-layer reads work unchanged on it: `schedule`, `game`, `team_history`, `player_history`, `team_averages`,
`team_splits`, `player_averages`, `player_splits` (point-in-time `as_of` rules in ESPN_SCHEMA.md; baseball allowance 5 h).
Standings, injuries, rosters and play-by-play are not stored here.

## Size

~40 KB a game (a player line is ~1 KB: 36 lines a game), so ~100 MB a season, which is why the store is a local cache. First
real runs, 2026-10-20: `teams` 30 rows; today's schedule 0 games (an off day); with the floor lowered by one day in a scratch
store, 2026-10-19 gave 1 game, 2 team lines and 36 player lines in 4 requests.

```
python -m src.cli datasvc mlbbox refresh --min-age-minutes 180 --max-requests 120   # in scripts/capture_slot.sh, but only where data/datasvc/mlb/MANIFEST.json exists (see below)
python -m src.cli datasvc mlbbox schedule --date 2026-10-20
python -m src.cli datasvc mlbbox averages --team TB --split home
python -m src.cli datasvc mlbbox check
```

## Scheduling (2026-10-20)

`scripts/capture_slot.sh` runs this refresh (240 s cap, `|| true`) and `datasvc all pbp-fill --limit 40 --max-requests 120`
after the ESPN refresh, **only where the local cache already exists** (`data/datasvc/mlb/MANIFEST.json`, or a
`pbp_*.index.jsonl` file), or when `DATASVC_LOCAL_CACHE=1`; `DATASVC_LOCAL_CACHE=0` stops them. Reason: this store and the
play-by-play cache are git-ignored on purpose and no workflow caches them, and a GitHub-hosted slot starts from a fresh
checkout, so run there they would refetch the same games every 15 minutes and discard them (and the box-score notice above
allows only non-bulk use). To make them run in CI the owner must choose: track the files (a licensing decision,
docs/datasvc/LICENSING.md) or add an Actions cache for `data/datasvc/mlb` and `data/datasvc/espn/*/pbp_*` (a workflow edit).
Start the cache once on a machine that keeps its checkout with the refresh command above.
