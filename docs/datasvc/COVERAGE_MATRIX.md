# Coverage matrix: BALLDONTLIE ALL-ACCESS vs. the in-house data service (2026-10-20, updated after round 2)

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
| NBA | C | C | C | C | C | N | C | C | C | C | N | F |
| WNBA | C | C | C | C | C | N | C | C | C | C | N | F |
| NFL | C | C | C | C | C | F | F | C | F | C | N | F |
| MLB | C | F | C | C | C | F | C | F | F | C | C | F |
| NHL | C | C | C | C | C | F | C | C | C | C | N | F |
| NCAAF | C | F | C | C | C | N | C | C | C | C | N | F |
| NCAAB | C | F | C | C | C | N | C | N | F | C | N | F |
| EPL / major soccer | C | C | C | C | C | N | C | F | F | C | N | F |
| MMA | - | C | C | C | C | N | - | N | N | C | N | F |
| Tennis | - | F | C | N | F | N | - | N | N | C | N | F |

Rows are what rounds 1 and 2 (and the earlier UFC/NFL/MLB layers) delivered; `C` for NBA/NHL/NCAAF/NCAAB/EPL means
`python -m src.cli datasvc <league> ...` ingests it and `DataClient.league(code)` serves it, with `observed_utc`
on every row (docs/datasvc/ESPN_SCHEMA.md). WNBA, NCAAW, La Liga, Bundesliga, Serie A, Ligue 1, MLS and the
Champions League run on the same code (one registry line each, `src/datasvc/espn/leagues.py`) and joined the scheduled
refresh in round 2 (team totals only for the six soccer leagues; see ESPN_SCHEMA.md for the size reasoning).

**Round 2 moved 12 cells from F to C.** S = season averages and splits, aggregated point-in-time from the stored box
scores (NBA, WNBA, NHL, NCAAF, NCAAB team lines, MLB, soccer); PB = play-by-play (NBA, WNBA, NHL, NCAAF); B = MLB box
scores. Caveats on those cells: MLB B and S are **forward only** (they start 2026-10-20; the 2026-01-01..08-27 outcomes
are sealed and the layer refuses them); play-by-play and the MLB store are local rebuildable caches (git- and
image-ignored; play-by-play is opt-in); NCAAF, NCAAB and the new soccer leagues have team-level S only (no player lines
stored); NCAAB play-by-play stays F (the flag is off for ~6,000 games a season). The soccer O cell stays C on our own
forward capture: the historical open/close archive (football-data.co.uk) is built, tested and joined to ESPN ids, but
its terms bar commercial and automated use, so its fetch is gated (docs/datasvc/SOCCER_HISTORY.md).

## Best free source per cell

| Feature | Source and status | Terms / limits |
|---|---|---|
| Teams, schedule, scores, live (all ESPN sports) | `site.api.espn.com/apis/site/v2/sports/<sport>/<league>/{teams,scoreboard}` - **verified live 2026-10-20** for NBA, WNBA, NHL, NCAAF, NCAAB, EPL | undocumented public JSON, no key, no stated limit; we send 1 request per 0.35 s with a real UA and cache every page |
| Box scores (team and player) | ESPN `.../summary?event=<id>` - verified for NBA, NHL, NCAAF, EPL (soccer players come from `rosters`) | same |
| Standings | `site.api.espn.com/apis/v2/sports/<path>/standings` - verified | same |
| Injuries | ESPN `.../injuries` - verified for NBA, NHL, WNBA, NFL, MLB (large), NCAAF (3 teams only); empty for NCAAB and EPL. Soccer alternative: `fantasy.premierleague.com/api/bootstrap-static` (verified reachable; EPL only, unofficial) | injuries are a snapshot: history exists only from our first fetch, which is why the store is append-only |
| Rosters / players | ESPN `.../teams/<id>/roster` - verified NBA, NHL, EPL (flat and grouped shapes) | weekly refresh |
| Play-by-play | ESPN summary `plays` (NBA, WNBA, NHL; NCAAB flag off), `drives` (NCAAF), `keyEvents`/`commentary` (soccer, not built); NHL official `api-web.nhle.com/v1/gamecenter/<id>/play-by-play`; nflverse `play_by_play_<yr>.csv.gz` (GitHub release, not built) | **built in round 2** for NBA, WNBA, NHL (both feeds) and NCAAF: gzip member store, ~43 MB a season (~57 MB with the NHL feed); verified on real games 2026-10-20 |
| NHL official (schedule, standings, boxscore, play-by-play, stats REST) | `api-web.nhle.com`, `api.nhle.com/stats/rest` - verified | unofficial, no key |
| NBA official | `cdn.nba.com/static/json/...` returned **403** from this IP; `stats.nba.com` did not connect. **Blocked: not used, no workaround attempted** (stats.nba.com is known to block cloud IPs) | ESPN replaces both |
| MLB | `statsapi.mlb.com/api/v1`: schedule + one box score per finished game, built in round 2 (`src/datasvc/mlb`, forward only from 2026-10-20); the Statcast CSV (baseballsavant) remains the free route for A and PB | unofficial; **MLBAM's notice allows only individual, non-commercial, non-bulk use**; MLB 2026-01-01..08-27 outcomes stay sealed |
| NFL | nflverse GitHub releases (schedules verified) - already ingested by `src/datasvc/nfl` (games, team and player stats, injuries; CC BY 4.0). EPA/win-prob come from the play-by-play file | GitHub release CDN |
| College football (richer) | CollegeFootballData `api.collegefootballdata.com` returned **401 without a key**: **K**, free key, owner step (below). Gives advanced team metrics (PPA, SP+) that ESPN lacks | free tier, monthly call cap |
| Soccer results + historical odds | `football-data.co.uk/mmz4281/<yy><yy>/E0.csv` (verified; results, shots, cards, open and closing odds for 10+ books) and `openfootball` on GitHub (verified; fixtures/results text) | **football-data.co.uk limits its data to private individuals and bars commercial, bot/scraper and AI/data-training use** (data.php, 2026-10-20). Parser, store and ESPN join built (EPL 2025/26: 380 of 380 matched); the fetch is gated behind the site's permission |
| Odds, props (live) | **C**: The Odds API forward capture (paid, already in `capture_slot.sh`: MLB, NFL, UFC, allsports). Kalshi public market data (`api.elections.kalshi.com/trade-api/v2`, verified, no auth for reads) gives prediction-market prices for some games and a few props: thin, not a props replacement | Kalshi: public reads, be polite |
| Historical opening odds / props (BDL "opening") | **N** for NBA/NHL/NFL/MLB props: no free archive. Soccer: football-data.co.uk. Everything else is only what we capture forward | cannot be backfilled |
| Advanced stats (BDL V1/V2) | **N** for NBA (tracking-based; the free route is stats.nba.com, blocked). Four-factor style stats can be derived from stored box scores; NHL partial via `api.nhle.com/stats/rest`; MLB via Statcast CSV; NFL via nflverse EPA | derivation is a build item, not a source |
| MMA | ESPN core JSON + UFC.com (already `src/datasvc/ufc`); `ufcstats.com` sits behind a browser check and is never used | - |
| Tennis | ESPN scoreboard (already `src/providers/espn_tennis_results.py`); Jeff Sackmann's `tennis_atp`/`tennis_wta` GitHub repos for history (**CC BY-NC-SA: non-commercial, a problem for a paid product**; the 2025 file path returned 404 today) | check licence before use |
| Leads checked | `lacausecrypto/mcp-sports-hub` (42 providers, 19 keyless) and `georgedouzas/sports-betting` (stats: football-data, EuroLeague, NBA via nba_api; odds: football-data, The Odds API) were read in round 2: see "Sources found in the two repos" below | - |
| BDL-only | contracts, DFS slates, lineups feed, leaders, esports, F1, PGA, EuroLeague and the other 12 basketball leagues: ESPN covers some (leaders, EuroLeague is not in ESPN); contracts and DFS are **N** | not needed by the dogs |

## Score

Cells: 10 sports x 12 features = 120, minus 4 not-applicable = 116. Counted from the table above by script.

| | cells | share | round 1 |
|---|---|---|---|
| **C** covered | 69 | **59%** | 57 (49%) |
| **F** free source exists, not built | 25 | 22% | 37 (32%) |
| **K** free key needed | 0 | 0% (CFBD would lift NCAAF A from N to K) | 0 |
| **N** not free | 22 | 19% | 22 (19%) |

So we match **59%** of BDL's feature cells now (up from 49%) and **81%** are reachable free (C + F + K, unchanged). What
is left in **F** (25): live scores for every sport (ESPN scoreboards are stored every 3 hours, not live), NFL
play-by-play and standings/advanced (nflverse), MLB players, advanced, play-by-play and injuries (Statcast, rosters),
NHL advanced (stats REST), NCAAF/NCAAB players, NCAAB play-by-play, soccer injuries (FPL feed) and play-by-play, tennis
players and season stats.

The not-free gaps (**N**, 22, unchanged): advanced stats for NBA/WNBA/NCAA/soccer/MMA/tennis (tracking data; `stats.nba.com`
is blocked from our IP), player props (all sports except our own MLB capture), historical opening odds and props (cannot
be backfilled; soccer has football-data.co.uk, whose terms block our use without permission), NCAAB and EPL injury feeds
(the FPL feed is the partial EPL answer), tennis box scores, MMA/tennis play-by-play, contracts and DFS. Also not free in
practice: the MLB statsapi layer, if MLBAM's non-commercial notice is enforced against a paid product.

## Sources found in the two repos (round 2 review, 2026-10-20)

`mcp-sports-hub` wraps 42 providers; `sports-betting` builds datasets from football-data (stats and odds), EuroLeague and
NBA (nba_api) stats, and The Odds API odds. Reachability was checked with one polite request each.

| Source | Gives us | Status here | Terms to check before use |
|---|---|---|---|
| EuroLeague/EuroCup official feeds (`api-live.euroleague.net/v2/competitions/E/seasons/E2025/games`, `live.euroleague.net/api`) | the one BDL league ESPN lacks: schedule, scores, per-game header, box and play-by-play | **200, 1 MB season JSON, keyless**; not built | no licence stated; official feed, treat like ESPN |
| OpenLigaDB (`api.openligadb.de`) | German football results, tables, scorers since 2007 | **200, keyless**; ESPN already covers the Bundesliga, so low value | community open data; confirm licence |
| Jolpica F1 (`api.jolpi.ca/ergast`) | F1 results, standings, laps, pit stops since 1950 (BDL lists F1) | **200, keyless**; not built | Ergast lineage, CC BY-NC-SA: non-commercial |
| Sleeper (`api.sleeper.app/v1`) | NFL player directory and ids, state, trending | **200, keyless**; a useful NFL id crosswalk | free, ~1000 req/min |
| NCAA API (`ncaa-api.henrygd.me`) | college scoreboards, box scores, rankings, team stats for all NCAA sports | **403 from this IP**: not used, not worked around | community proxy of ncaa.com |
| TheSportsDB (shared test key 3) | events and scores for 40+ sports | **403** with the shared key: not used | key and licence for commercial use |
| College Football Data (`api.collegefootballdata.com`) | NCAAF advanced metrics (PPA, SP+) | needs a free key (`CFBD_API_KEY`, 1000 req/month): **K**, owner step | free tier |
| football-data.org (not .co.uk) | soccer fixtures, results, standings, scorers for 12 leagues | free key, 10 req/min: **K** | free tier is non-commercial |
| API-Football (api-sports) | soccer injuries, lineups, predictions, odds | free key, 100 req/day: **K**; would fill the soccer injury gap | free-plan terms |
| MySportsFeeds | NFL/NBA/MLB/NHL stats, play-by-play, injuries, DFS | free key, non-commercial only: **K** | non-commercial |
| nba_api / `stats.nba.com` (sports-betting's NBA source) | NBA advanced and tracking stats | **blocked from our IP**; not used | - |
| OpenF1, Squiggle (AFL), MotoGP, Formula E, NASCAR CDN, OpenDota, Lichess, Chess.com | other sports BDL lists (esports, F1, motorsport) | keyless, not probed; outside the dogs' scope | each |

Nothing in either repo is a free historical player-props or opening-odds archive; both lean on football-data.co.uk and
The Odds API, which we already know.

## Honest caveats

* ESPN's JSON is undocumented and unofficial; it could change or block. Parsers are pure and fixture-tested so a
  shape change fails loudly in tests, and the fetcher stops on a browser check rather than working around it.
* Backfilled rows get `observed_utc` = the backfill time, not the game time. Forward-captured rows are true
  point-in-time. Reads say which (`meta.basis`).
* ESPN publishes no historical injury reports; our history starts when the store does.
* A past `as_of` season average on backfilled games is `reconstructed` (the game had certainly finished by then, by a
  per-sport allowance), not `observed`; `meta.game_basis` says how much of each, and `strict` drops the reconstructed part.
* The matrix counts a cell C when the code, tests and a real verification exist, not when years of history are already on
  disk: MLB starts on 2026-10-20, play-by-play is filled on demand (`pbp-fill`), the soccer odds archive needs the site's permission.
* Three sources carry non-commercial terms we have not been given a waiver for: football-data.co.uk (fetch gated), MLBAM
  statsapi (layer built, internal use) and, from the repo review, Jolpica/Ergast (not built).
* Player props (PP) for NBA, NFL, NHL and NCAAF: capture is built and fixture-tested (`src/pipeline/allsports_props.py`,
  docs/ALLSPORTS_DOGS.md) but has **not been run against the live API**, so the PP cells above stay N until a first paid
  run verifies the market keys. Licence status of every source: docs/datasvc/LICENSING.md.
