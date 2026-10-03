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
| 1 | UFC | ufcstats.com pages | In progress. Fights, fighters, round stats. |
| 2 | MLB | MLB Stats API (already used by LineHound) | Mostly exists; needs the service shape and daily refresh. |
| 3 | NFL | nflverse open data releases | Play by play, rosters, schedules back to 1999. |
| 4 | NHL | NHL public web API | Games, box, play by play, standings. |
| 5 | NBA | NBA public stats endpoints | Rate limited and header sensitive; cache hard. |
| 6 | Tennis | Existing BALLDONTLIE harvest plus public results | Harvest already holds ATP/WTA history. |
| 7 | Odds, all sports | Our own Odds API captures and the BALLDONTLIE harvest | Forward only from when we captured. |

A source can change or block us without notice. Each sport therefore keeps a
raw page or response cache, a parser test suite on saved fixtures, and a
freshness alarm, so a break is seen the same day and fixed in one place.

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
| UFC data layer | building | worker in progress | 2026-10-03 |
| MLB in service shape | not started | | |
| NFL | not started | | |
| NHL | not started | | |
| NBA | not started | | |
| Tennis | harvest exists, not served | | |
| Odds store served | not started | | |
| Keys and tiers | not started | | |
| Daily refresh wired | not started | | |
| Nightly agent | not started | | |
| Landing and dashboard | not started | | |
