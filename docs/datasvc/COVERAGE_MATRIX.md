# Coverage matrix: BALLDONTLIE ALL-ACCESS vs. the in-house data service (2026-10-20)

BALLDONTLIE (BDL) is being cancelled ($299.99/mo, 600 req/min). Its ALL-ACCESS plan lists 40+ leagues
(basketball: NBA, WNBA, NCAAB, NCAAW, EuroLeague and 13 more; NFL, MLB, NHL, NCAAF, MMA, PGA; soccer: EPL, La Liga,
Serie A, Bundesliga, Ligue 1, Champions League, MLS, World Cup; ATP, WTA, F1, four esports). Per the public docs
(docs.balldontlie.io, read 2026-10-20) the feature set is: teams, players, games, per-game player stats, season
and team-season averages, advanced stats (V1/V2), live and by-date box scores, lineups, play-by-play, injuries,
standings, leaders, DFS slates, odds (+ historical opening odds), player props (+ opening), contracts. Only NBA is
documented in detail on the public page; the other sports mirror it, which is how `scripts/balldontlie_harvest.py`
called them (games, stats, season_stats, standings, player_injuries, odds, odds_opening, box_scores).

Legend: **C** covered already (stored or served by `src/datasvc`, or our own forward capture) | **F** free source
exists, not built yet | **K** free key needed (owner step) | **N** not free (or not obtainable without passing a bot
check) | `-` does not apply. Columns: T teams, P players, G games/schedule, B box scores, S season stats,
A advanced stats, ST standings, I injuries, PB play-by-play, O odds, PP player props, L live scores.

| Sport | T | P | G | B | S | A | ST | I | PB | O | PP | L |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| NBA | C | C | C | C | F | N | C | C | F | C | N | F |
| WNBA | C | C | C | C | F | N | C | C | F | C | N | F |
| NFL | C | C | C | C | C | F | F | C | F | C | N | F |
| MLB | C | F | C | F | F | F | C | F | F | C | C | F |
| NHL | C | C | C | C | F | F | C | C | F | C | N | F |
| NCAAF | C | F | C | C | F | N | C | C | F | C | N | F |
| NCAAB | C | F | C | C | F | N | C | N | F | C | N | F |
| EPL / major soccer | C | C | C | C | F | N | C | F | F | C | N | F |
| MMA | - | C | C | C | C | N | - | N | N | C | N | F |
| Tennis | - | F | C | N | F | N | - | N | N | C | N | F |

Rows are what this round (and the earlier UFC/NFL/MLB layers) delivered; `C` for NBA/NHL/NCAAF/NCAAB/EPL means
`python -m src.cli datasvc <league> ...` ingests it and `DataClient.league(code)` serves it, with `observed_utc`
on every row (docs/datasvc/ESPN_SCHEMA.md). WNBA, NCAAW, La Liga, Bundesliga, Serie A, Ligue 1, MLS and the
Champions League run on the same code (one registry line each, `src/datasvc/espn/leagues.py`); they are not in the
scheduled refresh yet.

## Best free source per cell

| Feature | Source and status | Terms / limits |
|---|---|---|
| Teams, schedule, scores, live (all ESPN sports) | `site.api.espn.com/apis/site/v2/sports/<sport>/<league>/{teams,scoreboard}` - **verified live 2026-10-20** for NBA, WNBA, NHL, NCAAF, NCAAB, EPL | undocumented public JSON, no key, no stated limit; we send 1 request per 0.35 s with a real UA and cache every page |
| Box scores (team and player) | ESPN `.../summary?event=<id>` - verified for NBA, NHL, NCAAF, EPL (soccer players come from `rosters`) | same |
| Standings | `site.api.espn.com/apis/v2/sports/<path>/standings` - verified | same |
| Injuries | ESPN `.../injuries` - verified for NBA, NHL, WNBA, NFL, MLB (large), NCAAF (3 teams only); empty for NCAAB and EPL. Soccer alternative: `fantasy.premierleague.com/api/bootstrap-static` (verified reachable; EPL only, unofficial) | injuries are a snapshot: history exists only from our first fetch, which is why the store is append-only |
| Rosters / players | ESPN `.../teams/<id>/roster` - verified NBA, NHL, EPL (flat and grouped shapes) | weekly refresh |
| Play-by-play | ESPN summary `plays` (NBA, NHL, NCAAB), `drives` (NCAAF), `keyEvents`/`commentary` (soccer); NHL official `api-web.nhle.com/v1/gamecenter/<id>/play-by-play` (verified); nflverse `play_by_play_<yr>.csv.gz` (GitHub release) | not stored yet (large); next round |
| NHL official (schedule, standings, boxscore, play-by-play, stats REST) | `api-web.nhle.com`, `api.nhle.com/stats/rest` - verified | unofficial, no key |
| NBA official | `cdn.nba.com/static/json/...` returned **403** from this IP; `stats.nba.com` did not connect. **Blocked: not used, no workaround attempted** (stats.nba.com is known to block cloud IPs) | ESPN replaces both |
| MLB | `statsapi.mlb.com/api/v1` - verified reachable (schedule, teams); game feed, stats and Statcast CSV (baseballsavant) are the free route for B/S/A/PB | unofficial; MLB 2026-01-01..08-27 outcomes stay sealed |
| NFL | nflverse GitHub releases (schedules verified) - already ingested by `src/datasvc/nfl` (games, team and player stats, injuries; CC BY 4.0). EPA/win-prob come from the play-by-play file | GitHub release CDN |
| College football (richer) | CollegeFootballData `api.collegefootballdata.com` returned **401 without a key**: **K**, free key, owner step (below). Gives advanced team metrics (PPA, SP+) that ESPN lacks | free tier, monthly call cap |
| Soccer results + historical odds | `football-data.co.uk/mmz4281/<yy><yy>/E0.csv` (verified; results, shots, cards, opening and closing odds for 10+ books) and `openfootball` on GitHub (verified; fixtures/results text) | free for personal/research use; credit the source |
| Odds, props (live) | **C**: The Odds API forward capture (paid, already in `capture_slot.sh`: MLB, NFL, UFC, allsports). Kalshi public market data (`api.elections.kalshi.com/trade-api/v2`, verified, no auth for reads) gives prediction-market prices for some games and a few props: thin, not a props replacement | Kalshi: public reads, be polite |
| Historical opening odds / props (BDL "opening") | **N** for NBA/NHL/NFL/MLB props: no free archive. Soccer: football-data.co.uk. Everything else is only what we capture forward | cannot be backfilled |
| Advanced stats (BDL V1/V2) | **N** for NBA (tracking-based; the free route is stats.nba.com, blocked). Four-factor style stats can be derived from stored box scores; NHL partial via `api.nhle.com/stats/rest`; MLB via Statcast CSV; NFL via nflverse EPA | derivation is a build item, not a source |
| MMA | ESPN core JSON + UFC.com (already `src/datasvc/ufc`); `ufcstats.com` sits behind a browser check and is never used | - |
| Tennis | ESPN scoreboard (already `src/providers/espn_tennis_results.py`); Jeff Sackmann's `tennis_atp`/`tennis_wta` GitHub repos for history (**CC BY-NC-SA: non-commercial, a problem for a paid product**; the 2025 file path returned 404 today) | check licence before use |
| Leads checked | `lacausecrypto/mcp-sports-hub` and `georgedouzas/sports-betting` source lists were not reachable from this worker; their keyless candidates (ESPN, NHL, MLB StatsAPI, football-data.co.uk, openfootball) are all in this table. Review them next round | - |
| BDL-only | contracts, DFS slates, lineups feed, leaders, esports, F1, PGA, EuroLeague and the other 12 basketball leagues: ESPN covers some (leaders, EuroLeague is not in ESPN); contracts and DFS are **N** | not needed by the dogs |

## Score

Cells: 10 sports x 12 features = 120, minus 4 not-applicable = 116.

| | cells | share |
|---|---|---|
| **C** covered already | 57 | 49% |
| **F** free source exists, not built | 37 | 32% |
| **K** free key needed | 0 | 0% (CFBD would lift NCAAF A from N to K) |
| **N** not free | 22 | 19% |

So we match **49%** of BDL's feature cells now and **81%** are reachable free (C + F + K). The not-free gaps:
advanced stats for NBA/WNBA/NCAA/soccer/MMA/tennis, player props (all sports except our own MLB capture),
historical opening odds, NCAAB and EPL injury feeds (the FPL feed is the partial EPL answer), tennis box scores,
MMA/tennis play-by-play, contracts and DFS.

## Honest caveats

* ESPN's JSON is undocumented and unofficial; it could change or block. Parsers are pure and fixture-tested so a
  shape change fails loudly in tests, and the fetcher stops on a browser check rather than working around it.
* Backfilled rows get `observed_utc` = the backfill time, not the game time. Forward-captured rows are true
  point-in-time. Reads say which (`meta.basis`).
* ESPN publishes no historical injury reports; our history starts when the store does.
