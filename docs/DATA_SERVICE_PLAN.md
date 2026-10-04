# Sports data service: build plan

Owner direction, 2026-10-03: build our own all-sports data API as a product,
not only for LineHound. Cheaper than BALLDONTLIE, better to look at, and run
without anyone logging in. LineHound is its first customer.

This file is the standing brief. Every worker and every scheduled run on this
project reads it first and updates the status table at the bottom.

## Product

One API key, every sport, stats and odds in one consistent shape.

- **Who buys it:** hobby developers, betting-model builders, fantasy tools,
  Discord bot authors, content sites. The same people who buy BALLDONTLIE or
  The Odds API today.
- **Why they would switch:** price, one schema across sports, derived
  features nobody else serves (as-of-date player and fighter features with no
  leakage, matchup fact sheets, consensus and best price per market), a
  status page that shows how fresh every dataset is, and a dashboard that is
  pleasant to use.
- **What we do not claim:** official league partnership, or odds history
  older than our own captures and harvests.

## Shape

- Paths: `/data/v1/{sport}/{resource}`. Sports: `ufc`, `mlb`, `nfl`, `nba`,
  `nhl`, `tennis`, later `ncaaf`, `ncaab`, `soccer`.
- Common resources per sport: `teams` (or `fighters`/`players`), `players`,
  `games` (or `events`/`fights`), `stats` (box and play level where the
  source has it), `standings`, `injuries` where public, `odds` (ours only),
  `features?as_of=` (derived, no leakage), `matchup`.
- Every record: stable id, `source`, `fetched_utc`, `as_of`.
- Cursor pagination, one error shape, `/data/v1/status` with newest date and
  age per dataset.
- Keys and tiers are designed in from the start and switched on last: free
  tier (rate limited, current season), paid tiers (history, odds, features,
  higher limits). Billing reuses LineHound's Stripe code.

## Sources, in build order

| Order | Sport | Source | Notes |
|---|---|---|---|
| 1 | UFC | ESPN public JSON (core API) plus UFC.com athlete pages | Verified 2026-10-03, see below. ufcstats.com is behind a browser check and is not used. |
| 2 | MLB | MLB Stats API (already used by LineHound) | Mostly exists; needs the service shape and daily refresh. |
| 3 | NFL | nflverse open data releases | Verified 2026-10-03, see `docs/datasvc/NFL_SCHEMA.md`: the schedule (`games.csv`, 1999 to 2026, with rest, roof, weather, coaches, starting quarterbacks and the market), weekly team and player statistics (1999 to 2026) and injury reports (2009 to 2026). Plain CSV, CC BY 4.0, attribution kept. Play by play and depth charts (53 MB a season) are not used. |
| 4 | NHL | NHL public web API | Games, box, play by play, standings. |
| 5 | NBA | NBA public stats endpoints | Rate limited and header sensitive; cache hard. |
| 6 | Tennis | Existing BALLDONTLIE harvest plus public results | Harvest already holds ATP/WTA history. |
| 7 | Odds, all sports | Our own Odds API captures and the BALLDONTLIE harvest | Forward only from when we captured. |

## Source probes (2026-10-03, plain client, one request at a time)

| Source | Result |
|---|---|
| ufcstats.com | Serves a JavaScript proof-of-work page instead of data. A script can only pass it by running the check, which we do not do. Not usable. |
| ESPN core and site JSON, MMA | Open, no challenge. 34 seasons listed; event and bout data checked back to UFC 200 (2016). Per bout: both fighters with records, weight class, status, winner. Per fighter: height, reach, age, date of birth, stance, weight class, nickname, overall record, and a full fight history (34 fights for one fighter checked). Per fight: 43 statistics including knockdowns, significant strikes by target and by position (distance, clinch, ground), takedowns attempted and landed. Odds: DraftKings per bout with open, close and current for the over/under on rounds and spread, also present on completed fights. |
| UFC.com athlete page | Plain HTML, no challenge. Shows striking accuracy, takedown figures, reach, significant strikes and wins by knockout. |

Measured by the ingestion workers (2026-10-03): result names for KO/TKO, submission, unanimous, split and majority decisions, DQ, draw and no contest all seen live; per-fight statistics exist back to 2005 (UFC 52); control time is recorded from about 2018 on (zero before); odds with opening and closing lines from up to 12 sportsbooks per fight start between June and September 2019, including method-of-victory prices; a live in-fight provider is flagged so it is never read as a closing line. UFC.com answers a missing fighter with HTTP 200 (a search page or another fighter), so a profile is accepted only when the name and record match.

Originally not yet verified: whether the moneyline open and close are stored for completed fights, whether control time is in the per-fight statistics, round-by-round splits (the linescores list came back empty), and the exact request volume a full backfill needs. ESPN's endpoints are unofficial and can change without notice, so every parser keeps saved fixtures and the freshness alarm below.

ESPN serves the other leagues through the same structure (the same host and path pattern with a different sport and league). That is not yet probed for MLB, NFL, NHL or NBA; if it holds, one adapter pattern covers most of the table below, with the league feeds adding depth.

A source can change or block us without notice. Each sport therefore keeps a
raw page or response cache, a parser test suite on saved fixtures, and a
freshness alarm, so a break is seen the same day and fixed in one place.

## Source matrix (2026-10-04)

Three separate kinds of data, because they are separate decisions: **sporting
statistics** (what happened), **sportsbook prices** (what books offered) and
**internally derived features** (what we compute). "Permitted use" is what the
provider's own published words say, quoted or marked uncertain; an open URL is
not a licence, and nothing here is legal advice. Measured numbers come from
`docs/audit/2026-10-04/COLLECTION.md`. Nothing in this table says a
subscription can be cancelled: that follows from a plan actually being
downgraded and the product still working, not from a row.

### A. Sporting statistics

| Capability | Provider | Fields | Permitted use (as published) | Auth | Cost or quota | Observed coverage | Freshness need | Replaces a paid dependency? |
|---|---|---|---|---|---|---|---|---|
| MLB schedule, finals, probables, boxscores (relief usage), pitcher game logs, splits, standings, handedness, transactions | MLB Stats API, `statsapi.mlb.com` (free, unofficial for third parties) | Per game: teams, scores, status, probables; per boxscore: every pitcher's line; per pitcher: season game log by game type; standings by date; people | **Restrictive.** Every response carries "Use of any content on this page acknowledges agreement to the terms posted here" (`gdx.mlb.com/components/copyright.txt`), and that text says only "individual, non-commercial, non-bulk use of the Materials is permitted" and any other use is prohibited without MLB Advanced Media's written authorization. LineHound is a paid product and fetches in bulk (632 requests for a cold refresh), so its present use is **not clearly covered**. Owner decision, not an engineering one | None | No published quota found. Observed 2026-10-04: about 1,300 requests over eight refreshes, the long ones at roughly 3 a second, 0 HTTP errors, no throttling | Complete for what the product reads: results 2023-03-30 to now, pitcher logs and bullpen log for 2026, standings to the end of the regular season (the API returns an empty table for a postseason date) | Results and bullpen: daily; pitcher logs and splits: before first pitch on a start day | **No.** It is the free dependency; it replaces nothing paid. It is the one with a terms question |
| MLB pitch-arsenal leaderboards | Baseball Savant CSV (`baseballsavant.mlb.com/leaderboard/pitch-arsenal-stats`) | Per pitcher and batter, per pitch type: usage, whiff, wOBA, hard-hit | **Uncertain.** MLB property; no licence read here | None | 2 requests per refresh | 2026 season, both sides | Daily | No |
| Weather | Open-Meteo | Forecast by ballpark | **Uncertain.** As I recall, free for non-commercial use with a paid plan for commercial; verify before relying on it | None | Free tier | Forecast rows captured since 2026-09-02 | Hours | No |
| UFC schedule, bouts, fighters, per-fight statistics, bout odds | ESPN public core JSON, UFC.com athlete pages | See the probe table above | **Uncertain.** Unofficial endpoints, no licence read; UFC.com site terms not read | None | 156 events, 1,689 bouts committed; a refresh is a handful of requests (PoliteFetcher caps and caches by URL) | 2016 to now checked | Daily | **Partly, for UFC only:** ESPN carries a bookmaker's open and close per bout, which is what the paid `mma_h2h` capture buys. Its licence is unverified and it is one book |
| NFL schedule, team and player weekly statistics, injuries | nflverse data releases | See `docs/datasvc/NFL_SCHEMA.md` | **CC BY 4.0, attribution kept** (as already recorded in the build-order table; upstream sources behind it not examined) | None | 4 requests for a daily update | 1999 to 2026 | Daily in season | Possibly for NFL statistics (BALLDONTLIE ALL-ACCESS holds some of the same); not proven, not tested |
| Tennis, NFL and other harvested history | BALLDONTLIE ALL-ACCESS (paid, bought 2026-09-15) | Harvested to `data/historical/balldontlie/` | Under that subscription's terms (not re-read here) | Key in `.env` | Paid plan | ATP/WTA history, NFL | Varies | This **is** a paid dependency. NFL statistics are also in nflverse (free); tennis has no free equivalent verified here |

### B. Sportsbook prices

| Capability | Provider | Fields | Permitted use | Auth | Cost or quota | Observed coverage | Freshness need | Replaces a paid dependency? |
|---|---|---|---|---|---|---|---|---|
| Multi-book h2h, spreads, totals; pitcher and batter props; team totals, alternates, F5 trio | The Odds API (paid) | Price, line, book, timestamps per selection | Under that plan's terms (not re-read here); resale or redistribution of the prices is a question to settle before the data service sells them | Key in `.env` | Paid plan; floor 5,000 credits, about 132 a day approved | Forward only, from when each family was first captured | Minutes before first pitch | **No.** There is no free equivalent verified here. ESPN's per-bout bookmaker feed (UFC only) is the one partial candidate and is unverified. Prices cannot be rebuilt after the fact, so a missed window is gone |

### C. Internally derived features

| Capability | Provider | Fields | Permitted use | Auth | Cost | Coverage | Freshness need | Replaces a paid dependency? |
|---|---|---|---|---|---|---|---|---|
| Form, rest, travel, workload, matchup and ratings features; the card's probabilities | Our own code over A and B (`src/features`, `src/pipeline`, `src/datasvc/*/features.py`) | Computed, point in time | Ours. It inherits the terms of the inputs: a feature built from restricted statistics is not freer than they are | None | Compute and maintenance only | Wherever the inputs exist | Daily | Not a dependency. It cannot replace A or B; it only moves what A and B must be fresh for |

What still costs money whatever this table says: sportsbook prices (The Odds
API), the BALLDONTLIE subscription, hosting (Fly), and the maintenance time.

## Running by itself

- A daily refresh job per sport (`python -m src.cli datasvc <sport> update`)
  run from the existing scheduled workflows or at deploy, never by hand.
- A nightly autonomous agent that takes the next unfinished row in the
  status table, builds it on a branch with tests, and writes a short log.
  Its work is reviewed before it is merged.
- `/data/v1/status` and `scripts/prod_watch.py` flag any dataset older than
  its allowed age.

## The site

A separate landing page and dashboard (docs, live examples, a key, usage,
freshness), designed after the API has two sports solid. Not before: a
beautiful dashboard over one sport sells nothing.

## What decides whether this makes money

Customers, not code. The first sale target is one paying developer. Until
then every hour here must also improve LineHound, which is why the build
order follows LineHound's needs.

## Status

| Piece | State | Branch or commit | Updated |
|---|---|---|---|
| Plan | written | this file | 2026-10-03 |
| UFC data layer | built and merged: schedule and results, fighters, UFC.com profiles, fight statistics, odds, leakage-free features, matchup sheet, paid `/data/v1` API. Backfill 2024 to 2026 done (156 events, 1,689 bouts, 3,182 statistics rows, 4,033 odds rows, 1,075 fighters), committed and shipped in the image; it feeds the UFC fight-night page and the UFC AI analyst. UFC.com career profiles for 863 of 1,075 fighters (862 matched on name and record, 1 on an exact name where the page shows no record; 0 errors); the other 212 have no verifiable UFC.com page | `src/datasvc/ufc/`, `python -m src.datasvc.cli ufc ...`, `fa13daad` | 2026-10-03 |
| MLB in service shape | not started | | |
| NFL data layer | built: schedule and results, team and player weekly statistics, injury reports, leakage-free features (form, rest and bye, travel and time zones, quarterback and coach, injury counts by position, head to head, player usage over the last 3 and 5 games), matchup fact sheet, paid `/data/v1/nfl` API, CLI. Backfill 2021 to 2026 done and committed (1,696 games, 3,392 team rows, 13,809 player rows from 2024, 17,972 injury rows; 22.0 MB). Shipped in the image and refreshed by the daily loop (`nfl update`: the schedule and the current season's weekly files; rehearsed from an empty cache in 3.2 s, 4 requests, 0 errors) | `src/datasvc/nfl/`, `python -m src.datasvc.cli nfl ...`, `docs/datasvc/NFL_FEATURES.md` | 2026-10-03 |
| NHL | not started | | |
| NBA | not started | | |
| Tennis | harvest exists, not served | | |
| Odds store served | not started | | |
| Keys and tiers | not started | | |
| Daily refresh wired | UFC: the daily loop runs `ufc update` (last 10 days of results, next 21 days of cards); NFL: `nfl update` (schedule and the current season). Both commit their files and the image ships them | `scripts/daily_loop.sh` | 2026-10-03 |
| Nightly agent | not started | | |
| Landing and dashboard | not started | | |
