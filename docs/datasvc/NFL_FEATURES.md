# NFL features, the matchup fact sheet and the `/data/v1/nfl` API

Four things read the records fixed in [`NFL_SCHEMA.md`](NFL_SCHEMA.md) and serve them:

| What | Where | One line |
|---|---|---|
| Team, game and player features | `src/datasvc/nfl/features.py` | `team_features_as_of`, `game_features`, `player_features_as_of`: what a team, a game or a player had behind it as of a moment, leakage-free |
| Matchup fact sheet | `src/datasvc/nfl/matchup.py` | `matchup(store, game_id, as_of=None)`: both teams side by side with the market, the differences and what is missing |
| Command line | `src/datasvc/nfl/cli.py` | `python -m src.datasvc.cli nfl backfill\|update\|status\|matchup` |
| HTTP API | `api/datasvc.py` | `GET /data/v1/nfl/...`, signed-in, one error shape, cursor pagination (the same router as the UFC routes) |

All of it is facts only: no prediction, no pick, no edge. The numbers in the examples below were produced by
running the code on the real files fetched 2026-10-03 (the London game of week 4 of 2026, kickoff 2026-10-04 13:30
UTC, which had not been played yet) or, where a figure is worked by hand, on the synthetic league the tests use
(`tests/_nfl_world.py`).

## 1. The leakage rule

> Every figure uses only games that **finished before `as_of`**: kickoff plus 6 hours is not after `as_of`, and the
> game has a final result.

- `as_of` is an ISO date or datetime. A bare date is the **start of that day, 00:00 UTC**. A game on that date, at
  that instant, or under way at it (kicked off less than six hours earlier: the source has no finish time, six hours
  covers overtime and a weather delay) never counts, nor does any later game.
- The rule is on the kickoff **instant in UTC**, so the Thursday night game of 2025-09-04 (Eastern) is a game of
  2025-09-05 (kickoff 00:20 UTC) and a bare `as_of` of `2025-09-05` does not count it. That is the conservative
  direction.
- **One gate.** `features.completed_games(store, team, before)` is the only place a game is admitted. A game with
  no kickoff time is excluded and listed (`sample.skipped.no_kickoff_time`): it cannot be placed, so it is never
  assumed to be in the past. A game that should have finished with no result recorded (cancelled, postponed, not
  updated yet) is left out and listed with its status (`started_without_result`), and a game that started before
  `as_of` but may still have been under way is listed too (`in_progress_at_as_of`), so a reader can see a missing
  game instead of assuming it never happened. Player rows go through the same test, by their game.
- **A game's own sheet is as of its kickoff, and may not be later.** `game_features` and `matchup` default `as_of` to
  the kickoff and refuse a later one (HTTP 422): a "pre-game" sheet as of after the game would put the game's own
  result into the form figures, a quiet leak. Team and player features accept any `as_of`.
- **What the schedule fixes in advance is as-of safe** (the opponent, the stadium, the kickoff slot, divisional or not,
  the previous scheduled game and so rest, bye and travel). **What is recorded at or after the game is labelled
  `"as_of_safe": false` and nothing else reads it:** the starting quarterback and head coach listed for the game, the
  observed temperature and wind, and the market in the matchup sheet.
- **Rest and travel look at the previous SCHEDULED game, played or not** (`previous_scheduled_game`), because they
  are schedule facts known before either game. Form looks at finished games only, so for a game a few weeks ahead the
  team block says how many earlier games have no result yet (`sample.scheduled_games_without_a_finished_result_before_this_game`
  and a `form` entry in `missing`): the form is then as of the team's last finished game.

How it is tested (`tests/test_datasvc_nfl_features.py`): for every game of the league and for 75 moments between
games and inside them (one second before a kickoff, one hour in, five hours fifty-nine in, six hours in, a day
after), the features computed from the store must equal the features computed from the same store in which **every
game that had not finished by then is filled with nonsense** (a 777-3 overtime win, 9,999 yards, 999 targets,
statuses flipped, a market of -9999) while the schedule is left alone. The same is checked for every player. Three
deliberately leaky gates (one admitting games a month ahead, one that forgets the six hours, one with a negative
allowance) are each caught by that check, and a control shows the nonsense does reach the figures at a moment when
those games have finished. Separately, the six-hour edge, a bare date, a Sunday-night kickoff after midnight UTC, a game
with no result and a game with no kickoff time each have a hand-checked case.

## 2. Where the numbers come from

- Results, scores, sites, overtime, the listed starter and coach, rest as the source gives it: `games` and the
  `team_games` rows built from them.
- Plays, net yards, giveaways and takeaways: `team_games` (formulas in the schema). A figure uses a game only when
  **the fields it needs** are numbers in that game's row; a game with a score but no statistics row still counts
  toward results and is left out of the yards and turnover figures, each of which states its own sample.
- Usage and production of players: `player_games`. Injuries: `injuries`. Where a venue is: `venues.py` and the
  `stadium_id` of the game.
- A ratio is **the sum of the numerators over the sum of the denominators** (yards per play is total net yards over
  total plays, not an average of per-game ratios). Values are rounded to 4 decimals; a whole number is an int.

## 3. `team_features_as_of(store, team, as_of, *, season=None) -> dict`

`team` is a code, a nickname or an alias (`KC`, `chiefs`, `LAR` for the Rams). `season` (default: the NFL season
`as_of` falls in, March to February) picks the games of `season_to_date`. Raises `ValueError` for an unreadable
`as_of` and `UnknownTeam` (a `LookupError`) for a team the store has no game for.

```
team, name, as_of, leakage_rule, season
sample    games, first_game_utc, last_game_utc, skipped {no_kickoff_time, in_progress_at_as_of, started_without_result}
record    season {games, wins, losses, ties}, store {...}
streak    {type: W|L|T|null, length}
form      last_3, last_5, season_to_date          (each a window, below)
last_games  the last five, newest first: {game_id, kickoff_utc, season, week, game_type, opponent, site, points_for, points_against, result, margin}
rest      {days_since_last_game, last_game_id, last_game_utc, measured_to, unit}   (days to the as_of date, Eastern)
missing   [{figure, reason}]
```

A **window** is the last 3 or 5 finished games before `as_of` (any season, so one that reaches into last season says
so: `seasons`, `games_in_target_season`), or this season's games for `season_to_date`:

```
games, wins, losses, ties, points_for, points_against, points_for_per_game, points_against_per_game, margin_per_game,
first_game_utc, last_game_utc, seasons, games_in_target_season,
yards_per_play           {value, unit, games, num, den}     net yards over plays, from the games that have both
yards_per_play_allowed   {...}                              the opponents' figures in the same games
turnover_margin          {value, unit, games, total}        takeaways minus giveaways, per game
```

A window holds fewer games than it names when the team has fewer (`games` says how many); a figure with no
statistics behind it is `value: null` with a `reason` and a `missing` entry.

Worked by hand on the league: Kansas City as of week 8 had three straight wins by 31-17, 30-10 and 20-13, so
`last_3` is 81 points for, 40 against, 27 and 13.3333 a game, a margin of 13.6667; 1,170 net yards on 194 plays is
6.0309 a play (opponents 730 on 170, 4.2941), and its takeaways minus giveaways over the three games are +1, +2, +2,
1.6667 a game.

## 4. `game_features(store, game_id, as_of=None) -> dict`

Both teams' features for one game, as of its kickoff by default. Raises `UnknownGame`, or `ValueError` for an
unreadable `as_of`, one later than the kickoff, or a game with no kickoff time and no `as_of`.

```
game_id, as_of, as_of_source ("kickoff" | "argument"), leakage_rule
game        {game_id, status, home_team, away_team, stadium_id, stadium, venue_check}      (no score)
schedule    {season, week, game_type, postseason, gameday, weekday, kickoff_et, kickoff_utc, time_window, primetime, divisional, neutral_site}
conditions  {temp_f, wind_mph, roof, surface, as_of_safe: false, note}
home, away  a team block (section 3) plus: rest, travel, injuries, qb, coach
head_to_head
missing     [{side, team, figure, reason}]
```

### Rest, short week, bye

From the team's previous **scheduled** game, in calendar days between the two `gameday`s (Sunday to Thursday is 4,
the NFL's own count):

```
days_since_last_game, short_week (5 days or fewer), coming_off_bye (two or more weeks since the last game, or 13+ days),
week_gap, season_opener, last_game_id, last_game_utc, source_rest_days
```

A previous game in an earlier season makes it a **season opener**: no rest figure (the gap is months),
`season_opener: true`, and the reason is in `missing`. The two-week gap before the Super Bowl (week 21 to 22, 14
days) is a bye by the days. The source's own `home_rest`/`away_rest` agree with this figure on **every game of 2023,
2024, 2025 and 2026** (measured 2026-10-03: 2,126 of 2,126 team games with a previous game) and differ only where
the source used the nominal schedule instead of the real dates: 20 team games of 2021 (the COVID reschedules) and 2
of 2022 (week 18, after the Bills at Bengals game was cancelled and dropped from the file).

### Slot and schedule facts

`primetime` is a kickoff at or after 19:00 Eastern (`night`; `late_afternoon` is 15:00 to 19:00, `early` before).
`divisional` is the source's `div_game`. `postseason` is any game type but `REG`. These are as-of safe.

### Travel

For each team, from its home stadium (the stadium it used for most of its home games that season, read from the
schedule) and from the venue of its previous scheduled game to this game's venue, with the coordinates and clocks of
`venues.py` (`STADIUM_ID` to latitude, longitude and zone, 41 stadiums, cited there):

```
base_stadium_id, venue_stadium_id, miles_from_home_base, miles_from_last_game,
time_zones_crossed (venue UTC offset at kickoff minus the home stadium's, hours; negative is westward), direction,
kickoff_home_base_clock ("08:30": the kickoff on the team's own clock), reasons {}
```

A home team at its own stadium travels 0.0 miles and no zones. A neutral-site game is travel for both teams (the
"home" team in London flies 4,341 miles). Arizona does not change its clocks, so it is three hours behind Buffalo in
September and two after the clocks go back, no hours from Seattle in September and one ahead in December; the
offsets are computed at the kickoff instant (`timeutil.utc_offset_hours`), not assumed. A venue the schedule contradicts (`venue_check`
not `ok`), a stadium id not in the table, or a game with no kickoff time gives `null` figures with the reason in
`reasons` and in `missing`.

### Quarterback and coach

```
qb.last_game   {game_id, qb_id, qb_name, as_of_safe: true}                  the last FINISHED game's starter
qb.this_game   {qb_id, qb_name, projected, changed_since_last_game, prior_starts_in_store, prior_starts_with_team,
                as_of_safe: false, note}
coach.last_game {coach, as_of_safe: true}
coach.this_game {coach, changed_since_last_game, as_of_safe: false, note}
```

The schedule file lists a starting quarterback for the current week and the next before they are played (a
projection, replaced by the actual starter after the game), recorded when fetched and not time-stamped. So everything
that depends on **this** game's listed quarterback is inside the block labelled `as_of_safe: false`, `projected` says
which kind it is, and the leakage test strips those blocks. `prior_starts_in_store` counts games that player
started in the store before `as_of`, so a first start shows 0.

### Injuries

The team's injury report as of the last report out before `as_of`: counts by position group and in total of players
`listed`, `out`, `doubtful`, `questionable`, `dnp` (did not practise) and `limited`, the skill players (quarterbacks
always, running backs, receivers and tight ends with a designation) by name, `newest_report_utc`, `rows_not_yet_known`.

A row is known from its `date_modified` where it has one (2021 to 2024). The 2025 and 2026 files have no timestamp;
a row without one is the week's final report and is **taken as out 24 hours before kickoff, an assumption stated in
the block (`assumption`)**. An `as_of` earlier than a row is known gets `available: false` with the reason. A week
with no injury rows at all in the store is `available: false` ("no injury report rows for week W of season S"), never
zero. A team with nobody on a published week's report is a real zero (`players_listed: 0`).

### Head to head

Every meeting of the two teams in the store before `as_of`, newest first, from the target game's home team's side:
`meetings`, `home_team_wins`, `away_team_wins`, `ties`, `average_margin_for_home_team`, `last_meeting`, `items`, and
`store_window.seasons` (the store holds 2021 to 2026, so this is the meetings since 2021, not the teams' history).
For the London game it is one meeting, Washington at Indianapolis in week 8 of 2022.

## 5. `player_features_as_of(store, player_id, as_of, *, windows=(3, 5)) -> dict`

A player's recent usage and production, for props. Raises `UnknownPlayer` for an id with no row.

```
player_id, name, position, position_group, team (as of the newest game counted), as_of, leakage_rule
sample   games_in_store_before_as_of, first_game_utc, last_game_utc, skipped, note
last_3, last_5   {games, stats, shares, first_game_utc, last_game_utc, game_ids, team, team_games_in_span, missed_team_games}
recent_games     the last five, newest first, each with its whole stat line
missing
```

`stats` has, for each of `pass_attempts`, `completions`, `passing_yards`, `passing_tds`, `interceptions`, `carries`,
`rushing_yards`, `rushing_tds`, `targets`, `receptions`, `receiving_yards`, `receiving_tds`: `{total, per_game,
games}`. `shares` has the mean of `target_share` and `air_yards_share` over the games that have them.

**`games` is the games played that have a row, and is stated.** A window holds fewer than 3 or 5 when the player has
fewer, and `missed_team_games` lists the team's games inside the window's span that the player has **no row** for.
The source writes a row for a player with any statistic in the game, so an offensive player who played and recorded
nothing has no row: a row of zeros is a game played, an absent row is unknown (injured, inactive, or played without
a statistic). A player traded in mid-window is compared against his current team's games only.

Real example: CeeDee Lamb before Dallas's week 11 game of 2025 (20 games in the store from 2024): his last three
games hold 30 targets (10 a game), 19 receptions, 269 yards and a mean target share of 0.2952, and Dallas played
only those three games in the span, so `missed_team_games` is empty. A recomputation from the raw nflverse file
agreed (30 targets, 269 yards).

## 6. `matchup(store, game_id, as_of=None, *, now=None) -> dict`

```
game            {game_id, season, week, game_type, status, kickoff_utc, home_team, away_team, home_name, away_name,
                 stadium_id, stadium, neutral_site, venue_check}                      (no score, ever)
as_of, as_of_source, leakage_rule, note
schedule, conditions
home, away      the team blocks of section 4
head_to_head
market          null-safe block, section 6.1
differentials   {figure: {unit, home, away, diff, home_sample, away_sample, thin_sample}}
missing         [{side, team, figure, reason}]
```

**Differentials** are home minus away (4 decimals, `null` when either side has no value) for points for, points
against, margin, yards per play, yards per play allowed and turnover margin in each of `last_3`, `last_5` and
`season_to_date` (18 figures), the days of rest, the miles travelled, the zones crossed, and the injury counts `out`
and `listed`. `thin_sample` is true when either side's window holds fewer games than it names (3, 5 and 3) or a
side has no value, so a one-game average cannot pass for a real one.

**Missing** is each side's own `missing` list tagged with the side and team, plus the sheet's own gaps (the market,
and every difference that could not be computed). For the London game the sheet has none: both teams have three
finished games in 2026, an injury report for week 4, a rest figure and a travel figure.

### 6.1 The market block

The schedule file's one value per game: `spread_line` (nflverse's convention, **positive when the home team is
favoured**, checked against the moneylines on 1,503 games since 2021), the total, both moneylines and the spread
and total prices. It is **not an as-of price**: nflverse overwrites it as the market moves, so it is the closing
line of a game that is final and the latest line at `fetched_utc` of one that is not. The block says
`as_of_safe: false`.

Prices are American. `implied` is the price as a probability, margin included (`100/(p+100)` for a plus price,
`|p|/(|p|+100)` for a minus price); a two-way market's `margin` is the sum of the two implied probabilities minus 1
and `without_margin` divides each by that sum, so they are the market's numbers, not an estimate made here. With a
price missing the other is shown and `margin` and `without_margin` are null; a price that cannot be American (zero,
between -100 and +100, a string, a bool) is treated as absent. The spread is given both ways, so neither reading is a
guess: `nflverse_spread_line` and `home`/`away` in betting convention (the favourite's number is negative). For the
London game: Indianapolis -205, Washington +170 (`implied` 0.6721 and 0.3704, margin 0.0425, `without_margin` 0.6447
and 0.3553), spread -4.5 (Indianapolis favoured), total 46.5.

`find_game(store, team_a, team_b, *, season=None, week=None, now=None)` is how two teams become a game (either of
them home): the earliest game still to be played, else the latest, or the one of the given season and week.

## 7. The command line

```
python -m src.datasvc.cli nfl backfill --since 2021 [--player-since 2024] [--max-requests N] [--delay S]
python -m src.datasvc.cli nfl backfill --seasons 2026,2025
python -m src.datasvc.cli nfl update [--today YYYY-MM-DD]
python -m src.datasvc.cli nfl status [--check]
python -m src.datasvc.cli nfl matchup KC BUF [--season 2026 --week 5] [--as-of 2026-10-11]
python -m src.datasvc.cli nfl matchup --game-id 2026_04_IND_WAS
```

`backfill` fetches the schedule once, then for each season newest first the team statistics, the player statistics
and the injury reports; `update` does the same for the current season only. Both are idempotent (a second run
changes no file, not even a modification time) and resumable (progress is on disk and in the manifest after every
season; a request cap or a browser check stops the run cleanly and the next run continues). `status --check` prints
the counts and ages and then nine parity checks (every game has two team rows, every final game has statistics for
both teams, a game's two turnover margins cancel, every player and injury row belongs to a game and one of its teams,
the manifest describes the files on disk, ...) and exits 1 if any fails. The exit code is 2 for a source that blocked
us or an argument that names nothing.

## 8. The API: `GET /data/v1/nfl/...`

Read-only, JSON only, the same sign-in as the UFC routes (`Authorization: Bearer <token>`, 401 and 402 in the one
error shape), the same cursor pagination (`limit` default 50, capped by the caller's tier at 100; `next_cursor` is
keyset and opaque; a cursor replayed against another query is `422 invalid_cursor`) and the same error shape
(`{"error": {"code", "message", "details"?}}`). The files are loaded by their own holder, once per process, and
swapped in only when one changes on disk; a dataset a route does not touch is never read; a corrupt dataset is a
`503 data_unavailable` for the routes that need it and nothing else. Rows are shared in memory (`store.compact`):
the four files take about 31 MB resident, a matchup request about 19 MB.

| Endpoint | Returns |
|---|---|
| `/data/v1/status` | the UFC datasets as before, and a new `nfl` object: each dataset's record count, newest date and age, the manifest's `coverage`, the attribution |
| `/data/v1/nfl/games?season=&week=&team=&game_type=&status=&order=&limit=&cursor=` | stored game records, newest first (`order=asc` reverses) |
| `/data/v1/nfl/games/{game_id}` | the game and both teams' rows |
| `/data/v1/nfl/team-games?team=&season=&week=&game_type=&status=&order=&limit=&cursor=` | one row per team per game |
| `/data/v1/nfl/player-games?player=&team=&game_id=&season=&week=&position_group=&order=&limit=&cursor=` | offensive usage and production per player per game; `player` is an id or a name |
| `/data/v1/nfl/injuries?game_id=&team=&season=&week=&player_id=&position_group=&report_status=&order=&limit=&cursor=` | injury report rows |
| `/data/v1/nfl/matchup?game_id=` or `?a=&b=&season=&week=&as_of=` | the fact sheet; `a` and `b` are team codes or names |
| `/data/v1/nfl/teams/{team}/features?as_of=&season=` | `team_features_as_of` |
| `/data/v1/nfl/players/{player}/features?as_of=` | `player_features_as_of`; `player` is an id or a name |

`team` takes a code, a nickname, a full name or an alias and matches home or away; something that is no NFL team is
`422` naming the parameter, a real team with no game is an empty list. A player name goes through `names.match` and
**refuses to guess**: two equally good matches are `409 ambiguous_name` listing both. `as_of` follows the UFC rule
(`2026-10-03`, `2026-10-03T21:00Z`, a `+` offset URL-encoded as `%2B`); omitted, it is now for team and player
features and the kickoff for a matchup, and for a matchup one later than the kickoff is `422`. An unknown id is `404
not_found`, a wrong method is `405` with `Allow: GET`.

```
GET /data/v1/nfl/matchup?a=IND&b=WAS            (the next game between them)
{"data": {"game": {"game_id": "2026_04_IND_WAS", "status": "scheduled", "kickoff_utc": "2026-10-04T13:30:00Z",
                   "home_team": "WAS", "away_team": "IND", "stadium": "Tottenham Hotspur Stadium", "neutral_site": true, ...},
          "as_of": "2026-10-04T13:30:00Z", "as_of_source": "kickoff",
          "home": {"team": "WAS", "rest": {"days_since_last_game": 7, "short_week": false, "coming_off_bye": false},
                   "travel": {"miles_from_home_base": 3658.0, "time_zones_crossed": 5, "direction": "east",
                              "kickoff_home_base_clock": "09:30"},
                   "form": {"last_3": {"games": 3, "points_for_per_game": 25, "points_against_per_game": 30.6667,
                                       "margin_per_game": -5.6667, "yards_per_play": {"value": 4.7337, "games": 3, ...},
                                       "turnover_margin": {"value": 0.6667, "games": 3, "total": 2}}, ...},
                   "qb": {"last_game": {"qb_name": "Jayden Daniels", "as_of_safe": true},
                          "this_game": {"qb_name": "Marcus Mariota", "projected": true, "changed_since_last_game": true,
                                        "as_of_safe": false}},
                   "injuries": {"available": true, "totals": {"listed": 10, "out": 4, "questionable": 2, ...}}, ...},
          "away": {"team": "IND", "travel": {"miles_from_home_base": 3989.5, ...}, ...},
          "market": {"available": true, "as_of_safe": false,
                     "moneyline": {"home": 170, "away": -205, "implied": {"home": 0.3704, "away": 0.6721}, "margin": 0.0425, ...},
                     "spread": {"nflverse_spread_line": -4.5, "home": 4.5, "away": -4.5, "favourite": "away", ...}, ...},
          "differentials": {"travel.miles_from_home_base": {"home": 3658.0, "away": 3989.5, "diff": -331.5, ...}, ...},
          "head_to_head": {"meetings": 1, "last_meeting": {"game_id": "2022_08_WAS_IND", ...}, ...},
          "missing": [], "resolved": {"a": "IND", "b": "WAS", "game_id": "2026_04_IND_WAS", "matched_by": "teams"}}}
```

## 9. What the data could not support

- **Injury timestamps from 2025 on.** The injuries file lost `date_modified`; the 24-hour rule above is an assumption,
  so an as-of between a report's real publication and 24 hours before kickoff is answered "not available" rather than
  guessed. The store's own `fetched_utc` for a row is when we first saw it, which for a backfilled season is the
  backfill, not the publication.
- **The starting quarterback of a game not yet played** is the source's projection, listed for the current week and
  the next only (measured 2026-10-03: weeks 4 and 5 had starters, week 6 none), and it is not time-stamped.
- **The market as of a moment.** The schedule file holds one value per game. Closing lines are the final value; a
  line as of last Tuesday is not recoverable from it. (Our own forward captures hold those, for the markets they
  cover; this layer does not read them.)
- **Played but no statistic.** Without snap counts (not ingested) a player who played and recorded nothing has no
  row, so `games` counts games with a stat line and `missed_team_games` is the honest count of the others.
- **Defensive and kicking props.** Only quarterbacks, running backs, receivers and tight ends, and any player with a
  pass attempt, a carry or a target, are stored; defenders and kickers are in the raw file and not here.
- **Player history before 2024.** `player_games` starts with the 2024 season (the largest file; see the schema for the
  sizes). A game in 2021 to 2023 has team, schedule, injury and head-to-head features, and its players' recent
  usage is not available. Early-2024 games have partial windows, which the `games` count shows.
- **The venue of the 2025 international games.** The source names the home team's own stadium for them (seven games)
  and one 2026 game (`2026_05_PHI_JAX`) with a stadium id and name that disagree. Their travel figures are missing,
  with the reason; nothing is corrected from memory.
- **Stakes** (elimination, seeding, clinched) are not derived here; the records and streaks are in the team block for
  whatever builds them (`docs/SITUATION_LAYER_PLAN.md`).
