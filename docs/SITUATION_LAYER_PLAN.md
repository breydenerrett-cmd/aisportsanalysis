# The situation layer: the bigger picture, in every sport

Owner direction, 2026-10-03: "transcend all of that same theory and ideas and
similar patterns to other sports globally ... more EQ and emotional
intelligence in macro analysis rather than just matchup." Prompted by a call
with Jacob about MLB playoff picks (`data/private/calls/`, not published):
momentum over rest, breakthrough energy, hot bats now, weak division winners,
head-to-head, who is actually available, and teams that keep folding in October.

## What it is

A per-game record of the situation around a matchup, built from data we hold,
read by the AI analyst next to the matchup statistics. Every factor is a fact
with its source and sample, or it is listed as missing. Nothing is guessed, and
no factor is trusted until it has been measured.

## Factor families (one schema, defined per sport)

| Family | MLB | NFL | NBA / NHL | UFC | Soccer |
|---|---|---|---|---|---|
| Rest and rhythm | days since last game; bye vs played in; previous series length; travel | bye week; short week; travel; time zones | back-to-back; games in last N days; road trip length | days since last fight; short notice (when knowable) | fixture congestion; midweek travel |
| Form and momentum | last 5/10 results and run margin; streak; runs per game now vs season | last results and margins; streak | same | win streak; recent finishes | form run |
| Stakes | elimination game; series state; milestone (first series win in N years) | elimination; seeding; clinched (rest starters) | tanking; seeding | title fight; ranking at stake | relegation; qualification; cup |
| Pressure history | team's and core's postseason record against regular-season strength; manager record | QB and coach playoff record | same | record in main events and title fights | big-game record |
| Head-to-head and style | this season's series; last meetings | divisional rematch; last meeting | season series | previous meeting; shared opponents | derby history |
| Availability | starters used in the previous round; injuries when a feed exists | QB and key injuries | load management; injuries | weight class change; missed weight (when knowable) | rotation; injuries |
| Market psychology | public favourite; line move since open | public teams; primetime | same | hype; line move | big clubs |
| Venue | home/away; park; weather; roof | home/away; dome; weather | home/away; altitude | location; altitude | home/away; travel |

## How it is used

1. Computed per game into the data service as a `situation` record with evidence
   paths, the same way the UFC matchup sheet is built (`src/datasvc/`).
2. Added to the AI analyst's packet (MLB `src/analyst/packet.py`, UFC
   `src/analyst/ufc_packet.py`) with a prompt section on weighing it: small
   playoff samples make situation matter more, but every claim still cites the
   packet, and the market may already price the narrative.
3. Shown on the game and fight pages in plain words, as part of the written read.

## How it is proven

- Two AI analysts run side by side on the same games: A reads matchup statistics
  only, B reads the same plus the situation layer. Both are frozen before the game
  and graded separately (separate ledgers). After enough graded calls per family
  the record says whether the situation layer helps, by family and market.
- Each factor family is also tested on past seasons before it carries weight.
  First: rest versus rhythm in the MLB Division Series (bye team against the team
  that just won its Wild Card series), every series since 2023 in the store, and
  earlier seasons from MLB's free feed into a display-only store (never a training
  population).
- A factor that does not hold up is reported as a loser and dropped from the
  prompt; one that holds up is kept and named.

## Order

1. MLB postseason and UFC (data on hand).
2. NFL (nflverse), then NBA and NHL (public feeds), then soccer, as each sport's
   data layer lands (`docs/DATA_SERVICE_PLAN.md`).

## Status

| Piece | State | Updated |
|---|---|---|
| Plan | written | 2026-10-03 |
| MLB and UFC situation records | building | 2026-10-03 |
| Side-by-side analysts (A without, B with) | building | 2026-10-03 |
| Rest vs rhythm test, MLB Division Series | building | 2026-10-03 |
