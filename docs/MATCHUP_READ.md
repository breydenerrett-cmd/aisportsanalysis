# The written read of one game

Built 2026-10-03. The owner's verdict on the game page was that the matchup
analysis was "barely analytical, just a couple of numbers", and that was
right: tables and no reasoning. `src/analysis/matchup_read.py` now writes a
plain-English read of each game, deterministically, from the data already on
the page, and the page shows it at the top as "The read".

It is a description. It is not a prediction, not advice, not a pick and not a
claim that any price is wrong. It changes no pick, gate or record, and it does
not touch the fingerprinted card files.

## Where it lives

| Piece | File |
| --- | --- |
| The read (pure, stdlib) | `src/analysis/matchup_read.py` |
| How old each of our stores is, league run rate, park factor | `src/pipeline/read_context.py` |
| Served on the game route as `read` (and `read_inputs`) | `api/games.py` (`get_game`) |
| Rendered at the top of the game page | `web/js/matchupread.js`, called from `web/js/games.js` |
| Styles (`.mr-` rules) | `web/css/gamestory.css` |
| Tests | `tests/test_matchup_read.py`, `tests/test_matchup_read_web.py`, `tests/test_read_context.py` |
| Golden fixtures (the four real payloads) | `tests/fixtures/matchup_read_2026-10-03_*.json` |
| Fixture and doc regeneration | `scripts/regen_matchup_read_fixtures.py` |

`GET /game/{date}/{away}/{home}` now carries two more keys. `read_inputs` says
how old each store behind the page is, with the league run rate and the park
factor; `read` is the read. A failure while building either costs the read,
never the page (`read` is then null and the page renders as before).

## The shape of a read

```
headline              one sentence naming the biggest factor in this game
notices               game already started; postseason game (rates are regular season)
factors[]             ranked, each: factor, title, favours, size, short, sentence,
                      evidence[], confidence, caveat, down_weighted, rank
run_environment       expected runs per club and for the game, a range, the arithmetic,
                      labelled an estimate with no track record
market_view           what the price implies, where the read agrees or disagrees, why a
                      disagreement is more likely our error than a bargain
what_would_change_it  two or three facts that would flip the read
missing[]             every absent, stale, thin or failed input, named plainly
```

One deliberate difference from the brief: the list is called `factors`, not
`edges`. The product's own language tripwire (`tests/test_customer_language.py`)
forbids the word as a customer noun, and a field name that spells it would
trip the same rule. The meaning is the same.

Every `evidence` entry is `{path, label, value}`. `path` is a dotted field path
into the payload, `value` is read from that path (never typed), and
`tests/test_matchup_read.py` resolves every path against the payload and checks
the value matches. A number the read worked out itself (a pooled wOBA, say)
carries `derived: true`, its path points at the section it was worked out from,
and the page says "worked out from the lines on this page".

## Ranking, size and confidence

Each factor has a size (slight, moderate, large) and a confidence (low,
medium, high). The rank score is size (1, 2, 3) times confidence (0.3, 0.6,
1.0), so a large gap on thin data ranks below a moderate gap on solid data.
Ties keep the order of the list below. `favours` is a club abbreviation or
"even"; a factor can be shown with "even" when what it says is that something
does not separate the clubs.

The headline is the top factor's own one-sentence summary, with two honest
additions. When the top factor is low confidence it adds "the data behind it is
thin". When a starter has no line and nothing else in the read reaches
moderate on medium data, the headline says the starting pitching cannot be
read, because a missing starter is the largest hole a read can have.

## The factors, their thresholds, and why

Every threshold is a design choice made before looking at results, never tuned,
and none is a betting claim. Where the project already had a bar, the read uses
the same one.

| Factor | What it compares | Thresholds | Confidence |
| --- | --- | --- | --- |
| `starting_pitching` | Starters' FIP, WHIP and strikeouts minus walks | FIP gap 0.25 slight, 0.50 moderate, 1.00 large (runs per nine). 1.00 is the talent scan's own bar (`OBVIOUS_FIP_GAP`); over a six inning start 1.00 is two thirds of a run and 0.25 about a sixth. If WHIP and K-BB both point the other way the size drops one step | innings behind the smaller line: under 60 low, under 120 medium, else high; a thin flag forces low; stale pitcher logs cap at medium |
| `pitcher_regression` | Each starter's ERA against his FIP | A gap of 0.50 or more with at least 50 innings. Net of the two starters 0.50 slight, 1.00 moderate. ERA below FIP means results ran ahead of the strikeouts, walks and homers behind them | medium at 100 or more innings, else low; stale logs cap at medium |
| `pitcher_form` | Last three starts against the season, ERA | A gap of 1.50 runs, or outings 0.75 innings shorter than the season average. Direction comes from both starters' gaps. Always slight | always low: three starts is about eighteen innings. Says so, and says when the logs end |
| `hr_park` | Home runs per nine of the two starters, against the park | Gap 0.40 slight, 0.80 moderate. A park factor of 1.05 or more, or an altitude of 1000 metres or more, raises the size one step each; a factor of 0.95 or less lowers it one. A park factor resting on thin games is shown but not used to move the size | low under 100 innings, else medium |
| `arsenal_results` | wOBA allowed, pooled over each starter's pitch types by plate appearances | Gap 0.015 slight, 0.030 moderate, 0.050 large. Each starter needs 60 plate appearances to be compared | low under 200 plate appearances, else medium. The pitch file's date is not on the page, so never high. This is the only pitcher comparison when a starter has no game log |
| `pitch_mix` | Each lineup's wOBA against the opposing starter's pitch types, weighted by his usage, against that lineup's own wOBA over every pitch type | Difference in the two lineups' gaps 0.015, 0.030, 0.050. A lineup within 0.015 of its own line against these pitches is "close" | low under 150 plate appearances or under 70% of his pitches covered, else medium |
| `platoon` | Share of each posted lineup with the platoon advantage against the opposing starter's hand | Gap in share 0.20 slight, 0.30 moderate, 0.40 large (one hitter of nine is 0.111). Adds the starter's own platoon split, with its batters-faced counts, when we have it | medium with both lineups and 8 or more known bat sides, else low |
| `lineup_depth` | Slots one to four against slots five to nine, pooled by plate appearances; each lineup's pooled total compared | Gap 0.010 slight, 0.020 moderate, 0.035 large. Uses the matchup depth section when the pitch store built it, otherwise works it out from the per-pitch lines | low with under 60 plate appearances in either half or with one lineup, else medium |
| `batter_vs_pitcher` | Career head-to-head totals, with at-bats | Leans only with 40 or more at-bats per side and a gap of 0.040 in average; always slight. States the largest single hitter's at-bats | always low and down-weighted: nine hitters with a handful of at-bats each |
| `season_strength` | Season runs scored minus allowed per game | Gap 0.25 slight, 0.50 moderate, 1.00 large. 1.00 is the talent scan's own bar (`OBVIOUS_RUN_DIFF_GAP`) | games played of the smaller sample: 100 or more high, 40 or more medium, else low; a thin flag forces low; results more than seven days old cap at medium. Notes that a postseason game uses regular season rates |
| `recent_form` | Last-ten run margin against each club's own season margin | Lean at a difference of 0.75; always slight | always low: ten games swings by more than a run a game on luck alone |
| `rest_travel` | Travel flags (a dense stretch, 2 or more time zones east, 1500 or more miles) and rest days | Flag count differs by one slight, by two or more moderate | always low: whether travel costs runs is untested here. Not used when there are no games in the window to travel from, or when the results are stale |
| `bullpen` | Seven day relief workload: a likely unavailable arm counts two, a questionable one counts one | Point gap 2 slight, 4 moderate | medium, and only when the bullpen log ends within three days of the game |
| `park_weather` | Park factor, altitude, roof, temperature, wind, rain chance | Warm air at 85 F or more, cold at 55 F or less, altitude 1000 metres or more, park factor 1.05 or more or 0.95 or less each push one point (altitude two). Never picks a side; it is about the setting for both clubs | medium; low when the forecast hour is more than 3 hours from first pitch |

Wind direction is never used. `orientation_deg` is `None` for every park in
`src/data/parks.py`, deliberately (a wrong bearing flips the sign of a real
effect), so a 15 mph wind cannot be read as blowing in or out, and the read says
that. A fixed roof sets the weather aside; a retractable roof with no stated
state does too, because whether it is closed decides whether the weather matters.

## Stale and thin inputs are named and down-weighted

`read_inputs` carries the newest record date of our results, pitcher logs and
bullpen log. Without it, a team's "rest days" (the gap since the newest game in
our results) reads ten days of rest for every club when our results simply stop
ten days before first pitch.

| Store | Stale when it ends more than | What changes |
| --- | --- | --- |
| Results | 2 days before the game | Rest days are not used; last-five, last-ten and travel are labelled as the newest we hold; season factors cap at medium when it is over 7 days |
| Pitcher logs | 7 days | Starter factors cap at medium; the last-three-starts factor says the three are not the latest; a "14 days rest" figure (the field is capped at 14) is not trusted |
| Bullpen log | 3 days | The workload factor is not used and the gap says when the log ends |
| Platoon split | 7 days | Named stale in `missing` |

If `read_inputs` is absent altogether, the read says it cannot tell how old
anything is and treats nothing as current.

A starter with no game log is checked against the pitch file: if it shows
hundreds of pitches from him, the read says the gap is in our log and he is not
a newcomer; if it shows nothing, it says nothing can be said about him.

## The run environment

It calls `src.analysis.strength.run_means`, the unfitted run arithmetic the
rest of the product already uses, instead of carrying a second formula:

1. League scoring, measured from our own results (runs per team per game).
2. Each club's offence: its season rate, pulled toward the league rate by 25
   games of weight.
3. The opposing run prevention: the starter's share of the game (innings per
   start over nine) at his FIP times 1.08, pulled toward the league rate by 50
   innings, plus the rest of the game at the club's whole-season runs allowed,
   which stands in for the bullpen and includes the rotation. With no starter
   line the club's rate stands for the whole game.
4. Expected runs = offence x run prevention / league rate, plus the 0.20 run
   home field credit for the home club, times the park factor.

The range is one standard error of the season rates behind each number, built
from the project's published run dispersion (2.3352, `strength.DISPERSION`). It
is the uncertainty in the inputs, not the spread of possible scores: one
standard deviation of one club's score in a single game is about three runs, and
the read prints that next to the range. Weather and lineups are not in the
arithmetic, and the read says so. It is labelled an estimate with no track
record.

## The market view

It states the books' de-vigged consensus for each club (from
`price_improvement`) with the book count and the age of the board, then compares
it with the read's own lean. The lean is the net of the club-favouring factors,
each weighted size times confidence, and it must reach 1.2 (two slight factors
on medium data, or one moderate) before the read names a side.

- No lean: the read says it neither agrees nor disagrees and that the price is
  the better informed number.
- Agrees: the read says that is expected because starters and run rates are
  already in the price, and that it says nothing about whether the price is right.
- Disagrees: with three or more inputs missing or stale, or low confidence in
  the top factors, the read says the likelier explanation is that our read is
  missing something the books priced in (a confirmed lineup, a starter we have
  no log for, a fresh injury), not that the price is wrong. With full inputs it
  says a disagreement with a board of this many books is a question to check,
  not a finding.

Every market view ends with the research note: in our own pre-registered tests
of features like these against the market, none held up as a betting advantage.
The read never says a price is a bargain and never states a chance of winning.

## What it cannot support from the payload

- Wind direction relative to the park (no orientation on file for any park).
- A league baseline for home runs per nine, ERA or FIP, so a starter on his own
  can be described but not called good or bad against the field. The read
  compares the two starters with each other and, for run arithmetic, with the
  league run rate measured from our results.
- Roster news in the factors (the news section is read only as a gap).
- League standings and playoff position (the section is absent on the days
  checked and is named as missing).
- Whether a game's pitch file, or its platoon split, is current: the pitch file
  carries no date on the page.
- Park effects on home runs specifically; the park factor is a run factor.
- Anything about a player beyond the names and numbers on the page.

## Tests and regeneration

`python3 -m unittest tests.test_matchup_read tests.test_matchup_read_web tests.test_read_context`

The golden test rebuilds each real read from its stored payload and compares
the two. If wording or logic changes on purpose, run
`python3 scripts/regen_matchup_read_fixtures.py`, review the fixture diff, and
accept it. That script also rewrites the reads below, and a test checks that
this document still holds every sentence of every fixture.

## The four reads for 2026-10-03, verbatim

These are the reads the app produced for the four games on 2026-10-03, from the
payloads frozen in `tests/fixtures/`. The local stores behind them were stale
on that day (results to 2026-09-23, pitcher logs to 2026-09-07, bullpen log to
2026-09-06) and the reads say so.

<!-- READS:START -->

### CWS at CLE

**Headline.** Parker Messick has a pitching line on file (3.29 FIP over 167 innings) and Hagen Smith does not, so the starting pitching matchup cannot be read and nothing else on this page is large enough to replace it.

**Notice.** This game is already under way or finished (In Progress). The read describes the game before first pitch and does not use the live score.

**Notice.** This is a division series. Team rates on this page are regular season rates.

_A written description of this game built only from the data on this page. It is not a prediction, not advice, and not a claim that any price is wrong._

**What stands out, largest first**

1. **ERA against FIP** (favours CWS, slight, medium confidence). Parker Messick's ERA of 2.53 sits 0.76 below his FIP of 3.29 over 167 innings, so his results have run ahead of the strikeouts, walks and homers behind them. That gap is a sign part of the ERA is sequencing luck, and results of that kind tend to drift back toward the FIP.
   - Caveat: A pointer toward which results are more likely to cool, not a forecast of any one game. Our pitcher logs end 2026-09-07, 26 days before this game.
   - Evidence (3): Parker Messick ERA = 2.533; Parker Messick FIP = 3.293; Parker Messick innings = 167.0
2. **Lineup handedness** (no side, slight, medium confidence). 6 of 9 White Sox hitters have the platoon advantage against Parker Messick, who throws left-handed; 6 of 9 Guardians hitters have the platoon advantage against Hagen Smith, who throws left-handed. The two lineups present a similar platoon picture.
   - Caveat: A count of bat sides against the starter's throwing hand. A switch hitter always counts as having the advantage. A lineup can still change before first pitch.
   - Evidence (6): White Sox hitters with the advantage = 6; White Sox hitters with a known bat side = 9; Parker Messick throws = L; Guardians hitters with the advantage = 6; Guardians hitters with a known bat side = 9; Hagen Smith throws = L
3. **Lineup depth** (favours CWS, slight, medium confidence). The White Sox lineup has run 0.355 wOBA from slots one to four (1232 plate appearances) and 0.310 from slots five to nine (618), top-heavy. The Guardians lineup has run 0.331 wOBA from slots one to four (1633 plate appearances) and 0.313 from slots five to nine (1079), fairly even from top to bottom. Pooled across all nine, that favours the White Sox.
   - Caveat: Built from each hitter's results on plate appearances that ended on a pitch of each type, pooled by plate appearances. Hitters with no measured line are left out, so a lineup can look better or worse than it is.
   - Evidence (4): White Sox slots 1 to 4 wOBA = 0.355 (worked out); White Sox slots 5 to 9 wOBA = 0.31 (worked out); Guardians slots 1 to 4 wOBA = 0.331 (worked out); Guardians slots 5 to 9 wOBA = 0.313 (worked out)
4. **Pitch mix against the lineup** (no side, slight, medium confidence). The White Sox lineup has run 0.335 wOBA against the pitch types Parker Messick throws, weighted by how often he throws them, 0.005 worse than its 0.340 across every pitch type it has a line against (1531 plate appearances; his main pitch is the 4-seam fastball at 40.9%). That lineup is close to its usual line against these pitches, and the other lineup cannot be read.
   - Caveat: Plate appearances that ended on each pitch type, pooled across the hitters named. Individual hitters carry small samples, and the pitch file's date is not stated.
   - Evidence (2): White Sox lineup wOBA against Parker Messick's mix = 0.335 (worked out); Parker Messick top pitch usage = 40.9
5. **Season run margin** (favours CWS, slight, medium confidence). The White Sox have outscored opponents by 0.33 runs a game (4.78 scored, 4.45 allowed) and the Guardians by 0.03 (4.09 scored, 4.07 allowed). The 0.31 run gap favours the White Sox.
   - Caveat: This is a division series game and these are regular season rates; the smaller sample is 155 games. Our results end 2026-09-23, 10 days before this game.
   - Evidence (6): White Sox run margin per game = 0.333; Guardians run margin per game = 0.026; White Sox games played = 156; Guardians games played = 155; White Sox win share = 0.519; Guardians win share = 0.523
6. **Park and weather** (no side, slight, medium confidence). At Progressive Field, the park factor of 1.028 is close to neutral; the forecast around first pitch is 64 F, a mild reading, light wind of 6 mph and a 0% chance of rain. Taken together the setting is not tilted either way, for both clubs equally.
   - Caveat: Park orientation is not on file for any ballpark, so wind direction cannot be read as blowing in or out.
   - Evidence (7): roof type = open; park run factor = 1.028; home games behind the park factor = 81; forecast temperature (F) = 64.2; forecast wind (mph) = 6.0; chance of rain (%) = 0; hours between the forecast hour and first pitch = 0.0
7. **Starting pitching** (no side, slight, low confidence). Only Parker Messick (3.29 FIP, 1.04 WHIP, 19.3% strikeouts minus walks, 167 innings) has a line on file. Hagen Smith has none, so the two starters cannot be compared and this factor carries no direction.
   - Caveat: One starter has no line, so there is nothing to weigh him against. Hagen Smith has no game log in our records and no pitch data either, so nothing can be said about him from this page.
   - Evidence (2): Parker Messick FIP = 3.293; Parker Messick innings = 167.0
8. **Hitters against this pitcher** (no side, slight, low confidence). White Sox hitters are 18 for 73 (0.247) with 4 home runs against Parker Messick, spread over 9 hitters, the most at-bats for any one being 15. These are career head-to-head totals; at this many at-bats they are background, not a measured tendency. The other lineup's history is not on file, so there is no comparison.
   - Caveat: Small samples by nature: nine hitters each with a handful of at-bats. Career totals with no date cutoff, so they are as old as the hitters' careers.
   - Evidence (3): White Sox at-bats against Parker Messick = 73; White Sox hits against Parker Messick = 18; White Sox average against Parker Messick = 0.247
9. **Recent run scoring and prevention** (favours CLE, slight, low confidence). The White Sox outscored opponents by 0.80 a game over their last 10, against 0.33 on the season; the Guardians outscored opponents by 1.50 a game over their last 10, against 0.03 on the season. The Guardians are running further above their season line.
   - Caveat: Ten games swings by more than a run a game on luck alone, so this factor is capped at slight. Our results end 2026-09-23, 10 days before this game, so these ten games are the newest in our records, not the newest played.
   - Evidence (6): White Sox run margin, last ten = 0.8; White Sox games in the window = 10; White Sox run margin, last five = 1.6; Guardians run margin, last ten = 1.5; Guardians games in the window = 10; Guardians run margin, last five = 1.8

**Expected runs, an estimate**

An estimate built from season averages. It has no track record and is not a prediction of the score.

- CWS: 4.2, range 3.7 to 4.8
- CLE: 4.4, range 4.1 to 4.8
- Game total: 8.7, range 8.0 to 9.3

The arithmetic:

- League scoring: 4.47 runs per team per game over 2331 games in our results.
- White Sox offence: 4.78 runs per game over 156 games, pulled toward the league rate to 4.74.
- Guardians run prevention: 0.66 of the game is Parker Messick at 3.77 runs per nine (his FIP of 3.29 times 1.08, pulled toward the league rate), and 0.34 is the bullpen at 4.12, the club's whole season rate standing in for it. That blends to 3.89.
- White Sox expected runs: 4.74 x 3.89 / 4.47 = 4.12, times the park factor of 1.028, giving 4.23.
- Guardians offence: 4.09 runs per game over 155 games, pulled toward the league rate to 4.14.
- White Sox run prevention: no starter line on file for Hagen Smith, so the club's season runs allowed of 4.45 stands for the whole game.
- Guardians expected runs: 4.14 x 4.45 / 4.47 = 4.12 plus the 0.20 run home field credit, times the park factor of 1.028, giving 4.44.
- Range: one standard error of the season rates behind each number (the White Sox 3.7 to 4.8, the Guardians 4.1 to 4.8, total 8.0 to 9.3). That is the uncertainty in the inputs, not the spread of possible scores.
- A single game is far wider than that range: one standard deviation of one club's score in a single game is about 3.2 runs.
- Weather is not in this arithmetic; no weather effect has been fitted or tested here.
- Lineups are not in this arithmetic; both clubs are priced as their season selves.
- The bullpen share uses each club's whole season runs allowed, which includes its starters.
- Our pitcher logs end 2026-09-07, 26 days before this game, so starter lines miss his newest outings.
- Our results end 2026-09-23, 10 days before this game; the season rates stop there.

**What the price says**

- Across 11 books the market makes the Guardians a 57.3% favourite (a fair price of -134) and the White Sox 42.7%, with each book's margin removed.
- The board was captured 60 minutes before this page was built, which is older than we like.
- This read leans toward the White Sox, the side the market has as the underdog, so it disagrees with the price.
- With 13 inputs missing or stale, the likelier explanation is that our read is missing something the books have priced in, a confirmed lineup, a starter we have no log for, a fresh injury, not that the price is wrong.
- In our own pre-registered tests of features like these against the market, none held up as a betting advantage. Treat everything above as a description of the game.

**What would change it**

- A change of starting pitcher. Both probables, Hagen Smith and Parker Messick, drive the pitching factors; a replacement or an opener voids them. Hagen Smith has no line on file, so news about him would move this read the most.
- A late scratch from the top of either lineup. The depth and platoon counts above come from the posted nine; a replacement changes both. Top of the order, White Sox: Chase Meidroth, Randal Grichuk and Miguel Vargas; Guardians: Steven Kwan, José Ramírez and Chase DeLauter.
- A change in the forecast before first pitch. The scoring setting uses 64 F, 6 mph wind and a 0% chance of rain; rain could also delay or shorten the game.

**What we could not use (13)**

- [stale] Team results. our results end 2026-09-23, 10 days before this game, so last-five, last-ten, rest and travel are older than they look
- [stale] Pitcher logs. our pitcher logs end 2026-09-07, 26 days before this game, so starters' season lines and last-three-start figures miss anything newer, and a rest figure of 14 or more days is not reliable
- [absent] Hagen Smith (starter line). Hagen Smith has no game log in our records and no pitch data either, so nothing can be said about him from this page
- [absent] Hagen Smith (pitch arsenal). our pitch file has no rows for Hagen Smith
- [absent] Guardians lineup against Hagen Smith (pitch mix). Hagen Smith's pitch mix or the Guardians lineup's per-pitch lines are not on file
- [absent] Guardians hitters against Hagen Smith. no head-to-head history for the Guardians lineup against Hagen Smith is on file
- [stale] Bullpen workload. our bullpen log ends 2026-09-06, 27 days before this game, so the seven day workload window holds 0 relief outings for the White Sox and 0 for the Guardians; it is not used
- [absent] White Sox travel. no games in the window to travel from; our results end 2026-09-23, 10 days before this game
- [absent] Guardians travel. no games in the window to travel from; our results end 2026-09-23, 10 days before this game
- [stale] Days of rest. the rest days on the page (10 and 10) are the gap since the newest game in our results, and our results end 2026-09-23, 10 days before this game, so they are not a measured break
- [absent] League standings. no standings snapshot stored for 2026-10-03
- [absent] Matchup depth. no pitch-level data is available for this season, so matchup depth cannot be computed
- [absent] Pitcher platoon splits. pitcher platoon splits not fetched

### ATL at LAD

**Headline.** Tarik Skubal has a pitching line on file (2.59 FIP over 132 innings) and Dylan Dodd does not, so the starting pitching matchup cannot be read and nothing else on this page is large enough to replace it.

**Notice.** This is a division series. Team rates on this page are regular season rates.

_A written description of this game built only from the data on this page. It is not a prediction, not advice, and not a claim that any price is wrong._

**What stands out, largest first**

1. **Season run margin** (favours LAD, slight, medium confidence). The Braves have outscored opponents by 0.83 runs a game (4.66 scored, 3.83 allowed) and the Dodgers by 1.16 (4.93 scored, 3.78 allowed). The 0.32 run gap favours the Dodgers.
   - Caveat: This is a division series game and these are regular season rates; the smaller sample is 155 games. Our results end 2026-09-23, 10 days before this game.
   - Evidence (6): Braves run margin per game = 0.832; Dodgers run margin per game = 1.155; Braves games played = 155; Dodgers games played = 155; Braves win share = 0.6; Dodgers win share = 0.607
2. **Park and weather** (no side, slight, medium confidence). At Dodger Stadium, the park factor of 0.989 is close to neutral; the forecast around first pitch is 102 F, warm air that carries the ball, light wind of 5 mph and a 0% chance of rain. Taken together the setting is tilted toward runs, for both clubs equally.
   - Caveat: Park orientation is not on file for any ballpark, so wind direction cannot be read as blowing in or out. A forecast of 102 F is extreme enough to be worth checking against a live forecast.
   - Evidence (7): roof type = open; park run factor = 0.989; home games behind the park factor = 77; forecast temperature (F) = 102.4; forecast wind (mph) = 4.7; chance of rain (%) = 0; hours between the forecast hour and first pitch = 0.0
3. **Starting pitching** (no side, slight, low confidence). Only Tarik Skubal (2.59 FIP, 0.98 WHIP, 26.3% strikeouts minus walks, 132 innings) has a line on file. Dylan Dodd has none, so the two starters cannot be compared and this factor carries no direction.
   - Caveat: One starter has no line, so there is nothing to weigh him against. Dylan Dodd has no game log in our records, yet our pitch file shows 680 pitches and 168 plate appearances from him this season, so the gap is in our log, not a sign he is new.
   - Evidence (2): Tarik Skubal FIP = 2.585; Tarik Skubal innings = 132.33
4. **Results by pitch** (favours ATL, slight, low confidence). Dylan Dodd has held hitters to a 0.257 wOBA over 168 plate appearances, 28.1% whiffs, leaning on the sinker (60.5% of his pitches). Tarik Skubal has held hitters to a 0.284 wOBA over 492 plate appearances, 30.3% whiffs, leaning on the 4-seam fastball (36.5% of his pitches). By results on each pitch, Dylan Dodd has been harder to hit by 0.027 wOBA, which favours the Braves.
   - Caveat: Plate appearances that ended on each pitch type, season to date, as of a pitch-file date this page does not state. Not adjusted for opponent or park.
   - Evidence (12): Dylan Dodd Sinker wOBA allowed = 0.276; Dylan Dodd Sinker plate appearances = 97.0; Dylan Dodd Cutter wOBA allowed = 0.232; Dylan Dodd Cutter plate appearances = 71.0; Tarik Skubal 4-Seam Fastball wOBA allowed = 0.302; Tarik Skubal 4-Seam Fastball plate appearances = 178.0; Tarik Skubal Changeup wOBA allowed = 0.229; Tarik Skubal Changeup plate appearances = 156.0; Tarik Skubal Sinker wOBA allowed = 0.345; Tarik Skubal Sinker plate appearances = 91.0; Tarik Skubal Slider wOBA allowed = 0.282; Tarik Skubal Slider plate appearances = 67.0
5. **Recent run scoring and prevention** (favours LAD, slight, low confidence). The Braves outscored opponents by 0.60 a game over their last 10, against 0.83 on the season; the Dodgers outscored opponents by 2.40 a game over their last 10, against 1.16 on the season. The Dodgers are running further above their season line.
   - Caveat: Ten games swings by more than a run a game on luck alone, so this factor is capped at slight. Our results end 2026-09-23, 10 days before this game, so these ten games are the newest in our records, not the newest played.
   - Evidence (6): Braves run margin, last ten = 0.6; Braves games in the window = 10; Braves run margin, last five = 1.2; Dodgers run margin, last ten = 2.4; Dodgers games in the window = 10; Dodgers run margin, last five = 3.4

**Expected runs, an estimate**

An estimate built from season averages. It has no track record and is not a prediction of the score.

- ATL: 3.5, range 3.0 to 4.1
- LAD: 4.4, range 4.0 to 4.8
- Game total: 8.0, range 7.3 to 8.6

The arithmetic:

- League scoring: 4.47 runs per team per game over 2331 games in our results.
- Braves offence: 4.66 runs per game over 155 games, pulled toward the league rate to 4.63.
- Dodgers run prevention: 0.67 of the game is Tarik Skubal at 3.25 runs per nine (his FIP of 2.59 times 1.08, pulled toward the league rate), and 0.33 is the bullpen at 3.88, the club's whole season rate standing in for it. That blends to 3.46.
- Braves expected runs: 4.63 x 3.46 / 4.47 = 3.58, times the park factor of 0.989, giving 3.54.
- Dodgers offence: 4.93 runs per game over 155 games, pulled toward the league rate to 4.87.
- Braves run prevention: no starter line on file for Dylan Dodd, so the club's season runs allowed of 3.92 stands for the whole game.
- Dodgers expected runs: 4.87 x 3.92 / 4.47 = 4.26 plus the 0.20 run home field credit, times the park factor of 0.989, giving 4.42.
- Range: one standard error of the season rates behind each number (the Braves 3.0 to 4.1, the Dodgers 4.0 to 4.8, total 7.3 to 8.6). That is the uncertainty in the inputs, not the spread of possible scores.
- A single game is far wider than that range: one standard deviation of one club's score in a single game is about 3.0 runs.
- Weather is not in this arithmetic; no weather effect has been fitted or tested here.
- Lineups are not in this arithmetic; both clubs are priced as their season selves.
- The bullpen share uses each club's whole season runs allowed, which includes its starters.
- Our pitcher logs end 2026-09-07, 26 days before this game, so starter lines miss his newest outings.
- Our results end 2026-09-23, 10 days before this game; the season rates stop there.

**What the price says**

- Across 11 books the market makes the Dodgers a 65.9% favourite (a fair price of -193) and the Braves 34.1%, with each book's margin removed.
- The board was captured 60 minutes before this page was built, which is older than we like.
- This read does not lean clearly toward either club, so it does not agree or disagree with the price. On these inputs the price is the better informed number.
- In our own pre-registered tests of features like these against the market, none held up as a betting advantage. Treat everything above as a description of the game.

**What would change it**

- A change of starting pitcher. Both probables, Dylan Dodd and Tarik Skubal, drive the pitching factors; a replacement or an opener voids them. Dylan Dodd has no line on file, so news about him would move this read the most.
- The lineups, once posted. Platoon, depth and pitch-mix factors cannot be read until they are. Tarik Skubal has been weaker against left-handed bats (121 and 400 batters faced on each side), so the make-up of the opposing lineup matters.
- A change in the forecast before first pitch. The scoring setting uses 102 F, 5 mph wind and a 0% chance of rain; rain could also delay or shorten the game.

**What we could not use (13)**

- [stale] Team results. our results end 2026-09-23, 10 days before this game, so last-five, last-ten, rest and travel are older than they look
- [stale] Pitcher logs. our pitcher logs end 2026-09-07, 26 days before this game, so starters' season lines and last-three-start figures miss anything newer, and a rest figure of 14 or more days is not reliable
- [absent] Dylan Dodd (starter line). Dylan Dodd has no game log in our records, yet our pitch file shows 680 pitches and 168 plate appearances from him this season, so the gap is in our log, not a sign he is new
- [absent] Lineups. lineup not posted yet, or not fetched
- [absent] Batter against pitcher history. batter-vs-pitcher history not fetched
- [stale] Bullpen workload. our bullpen log ends 2026-09-06, 27 days before this game, so the seven day workload window holds 0 relief outings for the Braves and 0 for the Dodgers; it is not used
- [absent] Braves travel. no games in the window to travel from; our results end 2026-09-23, 10 days before this game
- [absent] Dodgers travel. no games in the window to travel from; our results end 2026-09-23, 10 days before this game
- [stale] Days of rest. the rest days on the page (10 and 10) are the gap since the newest game in our results, and our results end 2026-09-23, 10 days before this game, so they are not a measured break
- [absent] League standings. no standings snapshot stored for 2026-10-03
- [absent] Matchup depth. no posted lineup for this game, so there is no unit to decompose
- [absent] Dylan Dodd platoon split. no platoon split is on file for Dylan Dodd
- [stale] Tarik Skubal platoon split. the split was last updated 2026-09-08, 25 days before this game

### NYY at TB

**Headline.** Drew Rasmussen (2.99 FIP) is the better starter than Gerrit Cole (3.86 FIP), which favours the Rays.

**Notice.** This is a division series. Team rates on this page are regular season rates.

_A written description of this game built only from the data on this page. It is not a prediction, not advice, and not a claim that any price is wrong._

**What stands out, largest first**

1. **Starting pitching** (favours TB, moderate, medium confidence). Gerrit Cole (3.86 FIP, 1.09 WHIP, 20.1% strikeouts minus walks, 111 innings) against Drew Rasmussen (2.99 FIP, 0.91 WHIP, 21.6% strikeouts minus walks, 153 innings). Drew Rasmussen is better by 0.87 runs per nine on FIP, which favours the Rays. WHIP and strikeouts minus walks point the same way.
   - Caveat: Season lines only; park and opponent are not adjusted. Our pitcher logs end 2026-09-07, 26 days before this game, so recent starts are missing.
   - Evidence (8): Gerrit Cole FIP = 3.86; Gerrit Cole WHIP = 1.09; Gerrit Cole strikeouts minus walks = 0.201; Gerrit Cole innings = 111.0; Drew Rasmussen FIP = 2.991; Drew Rasmussen WHIP = 0.906; Drew Rasmussen strikeouts minus walks = 0.216; Drew Rasmussen innings = 153.33
2. **Results by pitch** (favours TB, moderate, medium confidence). Gerrit Cole has held hitters to a 0.291 wOBA over 428 plate appearances, 23.0% whiffs, leaning on the 4-seam fastball (49.3% of his pitches). Drew Rasmussen has held hitters to a 0.251 wOBA over 567 plate appearances, 24.7% whiffs, leaning on the cutter (28.9% of his pitches). By results on each pitch, Drew Rasmussen has been harder to hit by 0.040 wOBA, which favours the Rays.
   - Caveat: Plate appearances that ended on each pitch type, season to date, as of a pitch-file date this page does not state. Not adjusted for opponent or park.
   - Evidence (16): Gerrit Cole 4-Seam Fastball wOBA allowed = 0.274; Gerrit Cole 4-Seam Fastball plate appearances = 225.0; Gerrit Cole Slider wOBA allowed = 0.282; Gerrit Cole Slider plate appearances = 87.0; Gerrit Cole Curveball wOBA allowed = 0.435; Gerrit Cole Curveball plate appearances = 55.0; Gerrit Cole Changeup wOBA allowed = 0.236; Gerrit Cole Changeup plate appearances = 61.0; Drew Rasmussen Cutter wOBA allowed = 0.271; Drew Rasmussen Cutter plate appearances = 185.0; Drew Rasmussen 4-Seam Fastball wOBA allowed = 0.293; Drew Rasmussen 4-Seam Fastball plate appearances = 159.0; Drew Rasmussen Sinker wOBA allowed = 0.237; Drew Rasmussen Sinker plate appearances = 142.0; Drew Rasmussen Changeup wOBA allowed = 0.144; Drew Rasmussen Changeup plate appearances = 81.0
3. **Home runs against the park** (favours TB, slight, medium confidence). Gerrit Cole has allowed 1.38 home runs per nine and Drew Rasmussen 0.82 (111 and 153 innings), a gap that favours the Rays; the park factor of 1.002 is close to neutral.
   - Caveat: Home run rates settle slowly; with a few hundred batters behind each, a gap this size can move a lot.
   - Evidence (6): park run factor = 1.002; home games behind the park factor = 81; Gerrit Cole home runs per nine = 1.378; Gerrit Cole innings = 111.0; Drew Rasmussen home runs per nine = 0.822; Drew Rasmussen innings = 153.33
4. **Season run margin** (favours NYY, slight, medium confidence). The Yankees have outscored opponents by 0.82 runs a game (4.56 scored, 3.74 allowed) and the Rays by 0.44 (4.49 scored, 4.06 allowed). The 0.38 run gap favours the Yankees.
   - Caveat: This is a division series game and these are regular season rates; the smaller sample is 155 games. Our results end 2026-09-23, 10 days before this game.
   - Evidence (6): Yankees run margin per game = 0.819; Rays run margin per game = 0.436; Yankees games played = 155; Rays games played = 156; Yankees win share = 0.568; Rays win share = 0.603
5. **Park and weather** (no side, slight, medium confidence). At Tropicana Field, the park factor of 1.002 is close to neutral; the roof is fixed, so the weather outside does not apply. Taken together the setting is not tilted either way, for both clubs equally.
   - Caveat: Park orientation is not on file for any ballpark, so wind direction cannot be read as blowing in or out.
   - Evidence (3): roof type = fixed; park run factor = 1.002; home games behind the park factor = 81
6. **Last three starts** (favours TB, slight, low confidence). Gerrit Cole has a 4.91 ERA over his last three on file (3 starts, about 18 innings) against 3.41 on the season, worse by 1.50. Three starts is a small sample.
   - Caveat: Three starts is roughly eighteen innings, which is noise-level. These are the three newest on file and our pitcher logs end 2026-09-07, 26 days before this game, so they are not the latest three he has thrown.
   - Evidence (5): Gerrit Cole last three ERA = 4.909; Gerrit Cole season ERA = 3.405; Gerrit Cole recent starts = 3; Gerrit Cole innings per start, last three = 6.111; Gerrit Cole innings per start, season = 5.842
7. **Recent run scoring and prevention** (no side, slight, low confidence). The Yankees outscored opponents by 1.80 a game over their last 10, against 0.82 on the season; the Rays outscored opponents by 2.00 a game over their last 10, against 0.44 on the season. Neither club is far from its season line.
   - Caveat: Ten games swings by more than a run a game on luck alone, so this factor is capped at slight. Our results end 2026-09-23, 10 days before this game, so these ten games are the newest in our records, not the newest played.
   - Evidence (6): Yankees run margin, last ten = 1.8; Yankees games in the window = 10; Yankees run margin, last five = -0.4; Rays run margin, last ten = 2.0; Rays games in the window = 10; Rays run margin, last five = 0.2

**Expected runs, an estimate**

An estimate built from season averages. It has no track record and is not a prediction of the score.

- NYY: 3.8, range 3.3 to 4.3
- TB: 4.3, range 3.7 to 5.0
- Game total: 8.2, range 7.3 to 9.0

The arithmetic:

- League scoring: 4.47 runs per team per game over 2331 games in our results.
- Yankees offence: 4.56 runs per game over 155 games, pulled toward the league rate to 4.55.
- Rays run prevention: 0.63 of the game is Drew Rasmussen at 3.54 runs per nine (his FIP of 2.99 times 1.08, pulled toward the league rate), and 0.37 is the bullpen at 4.12, the club's whole season rate standing in for it. That blends to 3.75.
- Yankees expected runs: 4.55 x 3.75 / 4.47 = 3.81, times the park factor of 1.002, giving 3.82.
- Rays offence: 4.49 runs per game over 156 games, pulled toward the league rate to 4.49.
- Yankees run prevention: 0.65 of the game is Gerrit Cole at 4.26 runs per nine (his FIP of 3.86 times 1.08, pulled toward the league rate), and 0.35 is the bullpen at 3.84, the club's whole season rate standing in for it. That blends to 4.12.
- Rays expected runs: 4.49 x 4.12 / 4.47 = 4.13 plus the 0.20 run home field credit, times the park factor of 1.002, giving 4.34.
- Range: one standard error of the season rates behind each number (the Yankees 3.3 to 4.3, the Rays 3.7 to 5.0, total 7.3 to 9.0). That is the uncertainty in the inputs, not the spread of possible scores.
- A single game is far wider than that range: one standard deviation of one club's score in a single game is about 3.1 runs.
- Weather is not in this arithmetic; no weather effect has been fitted or tested here.
- Lineups are not in this arithmetic; both clubs are priced as their season selves.
- The bullpen share uses each club's whole season runs allowed, which includes its starters.
- Our pitcher logs end 2026-09-07, 26 days before this game, so starter lines miss his newest outings.
- Our results end 2026-09-23, 10 days before this game; the season rates stop there.

**What the price says**

- Across 11 books the market makes the Rays a 54.9% favourite (a fair price of -122) and the Yankees 45.1%, with each book's margin removed.
- The board was captured 60 minutes before this page was built, which is older than we like.
- This read leans toward the Rays too, so it agrees with the market on direction. That is expected: starters and run rates are already in the price. It says nothing about whether the price is right.
- In our own pre-registered tests of features like these against the market, none held up as a betting advantage. Treat everything above as a description of the game.

**What would change it**

- A change of starting pitcher. Both probables, Gerrit Cole and Drew Rasmussen, drive the pitching factors; a replacement or an opener voids them.
- The lineups, once posted. Platoon, depth and pitch-mix factors cannot be read until they are.

**What we could not use (11)**

- [stale] Team results. our results end 2026-09-23, 10 days before this game, so last-five, last-ten, rest and travel are older than they look
- [stale] Pitcher logs. our pitcher logs end 2026-09-07, 26 days before this game, so starters' season lines and last-three-start figures miss anything newer, and a rest figure of 14 or more days is not reliable
- [absent] Lineups. lineup not posted yet, or not fetched
- [absent] Batter against pitcher history. batter-vs-pitcher history not fetched
- [stale] Bullpen workload. our bullpen log ends 2026-09-06, 27 days before this game, so the seven day workload window holds 0 relief outings for the Yankees and 0 for the Rays; it is not used
- [absent] Yankees travel. no games in the window to travel from; our results end 2026-09-23, 10 days before this game
- [absent] Rays travel. no games in the window to travel from; our results end 2026-09-23, 10 days before this game
- [stale] Days of rest. the rest days on the page (10 and 10) are the gap since the newest game in our results, and our results end 2026-09-23, 10 days before this game, so they are not a measured break
- [absent] League standings. no standings snapshot stored for 2026-10-03
- [absent] Matchup depth. no posted lineup for this game, so there is no unit to decompose
- [absent] Pitcher platoon splits. pitcher platoon splits not fetched

### SD at MIL

**Headline.** Jacob Misiorowski (2.31 FIP) is the better starter than Robbie Ray (4.88 FIP), which favours the Brewers.

**Notice.** This is a division series. Team rates on this page are regular season rates.

_A written description of this game built only from the data on this page. It is not a prediction, not advice, and not a claim that any price is wrong._

**What stands out, largest first**

1. **Starting pitching** (favours MIL, large, medium confidence). Robbie Ray (4.88 FIP, 1.34 WHIP, 7.8% strikeouts minus walks, 151 innings) against Jacob Misiorowski (2.31 FIP, 0.79 WHIP, 31.8% strikeouts minus walks, 155 innings). Jacob Misiorowski is better by 2.57 runs per nine on FIP, which favours the Brewers. WHIP and strikeouts minus walks point the same way.
   - Caveat: Season lines only; park and opponent are not adjusted. Our pitcher logs end 2026-09-07, 26 days before this game, so recent starts are missing.
   - Evidence (8): Robbie Ray FIP = 4.877; Robbie Ray WHIP = 1.341; Robbie Ray strikeouts minus walks = 0.078; Robbie Ray innings = 151.33; Jacob Misiorowski FIP = 2.311; Jacob Misiorowski WHIP = 0.793; Jacob Misiorowski strikeouts minus walks = 0.318; Jacob Misiorowski innings = 155.0
2. **Results by pitch** (favours MIL, large, medium confidence). Robbie Ray has held hitters to a 0.321 wOBA over 638 plate appearances, 25.3% whiffs, leaning on the 4-seam fastball (32.7% of his pitches). Jacob Misiorowski has held hitters to a 0.229 wOBA over 584 plate appearances, 37.6% whiffs, leaning on the 4-seam fastball (63.0% of his pitches). By results on each pitch, Jacob Misiorowski has been harder to hit by 0.093 wOBA, which favours the Brewers.
   - Caveat: Plate appearances that ended on each pitch type, season to date, as of a pitch-file date this page does not state. Not adjusted for opponent or park.
   - Evidence (18): Robbie Ray 4-Seam Fastball wOBA allowed = 0.371; Robbie Ray 4-Seam Fastball plate appearances = 225.0; Robbie Ray Slider wOBA allowed = 0.329; Robbie Ray Slider plate appearances = 125.0; Robbie Ray Changeup wOBA allowed = 0.243; Robbie Ray Changeup plate appearances = 141.0; Robbie Ray Sinker wOBA allowed = 0.401; Robbie Ray Sinker plate appearances = 86.0; Robbie Ray Curveball wOBA allowed = 0.19; Robbie Ray Curveball plate appearances = 61.0; Jacob Misiorowski 4-Seam Fastball wOBA allowed = 0.254; Jacob Misiorowski 4-Seam Fastball plate appearances = 338.0; Jacob Misiorowski Cutter wOBA allowed = 0.198; Jacob Misiorowski Cutter plate appearances = 87.0; Jacob Misiorowski Slider wOBA allowed = 0.235; Jacob Misiorowski Slider plate appearances = 84.0; Jacob Misiorowski Curveball wOBA allowed = 0.143; Jacob Misiorowski Curveball plate appearances = 75.0
3. **Season run margin** (favours MIL, large, medium confidence). The Padres have outscored opponents by 0.19 runs a game (4.37 scored, 4.19 allowed) and the Brewers by 1.28 (5.12 scored, 3.84 allowed). The 1.10 run gap favours the Brewers.
   - Caveat: This is a division series game and these are regular season rates; the smaller sample is 155 games. Our results end 2026-09-23, 10 days before this game.
   - Evidence (6): Padres run margin per game = 0.187; Brewers run margin per game = 1.284; Padres games played = 155; Brewers games played = 155; Padres win share = 0.548; Brewers win share = 0.619
4. **ERA against FIP** (favours MIL, moderate, medium confidence). Robbie Ray's ERA of 3.39 sits 1.49 below his FIP of 4.88 over 151 innings, so his results have run ahead of the strikeouts, walks and homers behind them. That gap is a sign part of the ERA is sequencing luck, and results of that kind tend to drift back toward the FIP.
   - Caveat: A pointer toward which results are more likely to cool, not a forecast of any one game. Our pitcher logs end 2026-09-07, 26 days before this game.
   - Evidence (3): Robbie Ray ERA = 3.39; Robbie Ray FIP = 4.877; Robbie Ray innings = 151.33
5. **Park and weather** (no side, slight, medium confidence). At American Family Field, the park factor of 1.001 is close to neutral; the roof can close and its state for this game is not on file, so the weather is not used. Taken together the setting is not tilted either way, for both clubs equally.
   - Caveat: Park orientation is not on file for any ballpark, so wind direction cannot be read as blowing in or out.
   - Evidence (3): roof type = retractable; park run factor = 1.001; home games behind the park factor = 75
6. **Last three starts** (no side, slight, low confidence). Robbie Ray has a 5.27 ERA over his last three on file (3 starts, about 14 innings) against 3.39 on the season, worse by 1.88, with shorter outings (4.6 innings a start against 5.4), which hands more innings to the bullpen. Jacob Misiorowski has a 3.94 ERA over his last three on file (3 starts, about 16 innings) against 1.97 on the season, worse by 1.96. Three starts is a small sample.
   - Caveat: Three starts is roughly eighteen innings, which is noise-level. These are the three newest on file and our pitcher logs end 2026-09-07, 26 days before this game, so they are not the latest three he has thrown.
   - Evidence (10): Robbie Ray last three ERA = 5.268; Robbie Ray season ERA = 3.39; Robbie Ray recent starts = 3; Robbie Ray innings per start, last three = 4.556; Robbie Ray innings per start, season = 5.37; Jacob Misiorowski last three ERA = 3.938; Jacob Misiorowski season ERA = 1.974; Jacob Misiorowski recent starts = 3; Jacob Misiorowski innings per start, last three = 5.333; Jacob Misiorowski innings per start, season = 5.962
7. **Recent run scoring and prevention** (favours SD, slight, low confidence). The Padres outscored opponents by 1.80 a game over their last 10, against 0.19 on the season; the Brewers outscored opponents by 1.10 a game over their last 10, against 1.28 on the season. The Padres are running further above their season line.
   - Caveat: Ten games swings by more than a run a game on luck alone, so this factor is capped at slight. Our results end 2026-09-23, 10 days before this game, so these ten games are the newest in our records, not the newest played.
   - Evidence (6): Padres run margin, last ten = 1.8; Padres games in the window = 10; Padres run margin, last five = 1.6; Brewers run margin, last ten = 1.1; Brewers games in the window = 10; Brewers run margin, last five = 1.2

**Expected runs, an estimate**

An estimate built from season averages. It has no track record and is not a prediction of the score.

- SD: 3.2, range 2.8 to 3.7
- MIL: 5.5, range 4.9 to 6.2
- Game total: 8.8, range 8.0 to 9.6

The arithmetic:

- League scoring: 4.47 runs per team per game over 2331 games in our results.
- Padres offence: 4.37 runs per game over 155 games, pulled toward the league rate to 4.39.
- Brewers run prevention: 0.66 of the game is Jacob Misiorowski at 2.98 runs per nine (his FIP of 2.31 times 1.08, pulled toward the league rate), and 0.34 is the bullpen at 3.93, the club's whole season rate standing in for it. That blends to 3.30.
- Padres expected runs: 4.39 x 3.30 / 4.47 = 3.24, times the park factor of 1.001, giving 3.24.
- Brewers offence: 5.12 runs per game over 155 games, pulled toward the league rate to 5.03.
- Padres run prevention: 0.60 of the game is Robbie Ray at 5.07 runs per nine (his FIP of 4.88 times 1.08, pulled toward the league rate), and 0.40 is the bullpen at 4.23, the club's whole season rate standing in for it. That blends to 4.73.
- Brewers expected runs: 5.03 x 4.73 / 4.47 = 5.32 plus the 0.20 run home field credit, times the park factor of 1.001, giving 5.53.
- Range: one standard error of the season rates behind each number (the Padres 2.8 to 3.7, the Brewers 4.9 to 6.2, total 8.0 to 9.6). That is the uncertainty in the inputs, not the spread of possible scores.
- A single game is far wider than that range: one standard deviation of one club's score in a single game is about 3.2 runs.
- Weather is not in this arithmetic; no weather effect has been fitted or tested here.
- Lineups are not in this arithmetic; both clubs are priced as their season selves.
- The bullpen share uses each club's whole season runs allowed, which includes its starters.
- Our pitcher logs end 2026-09-07, 26 days before this game, so starter lines miss his newest outings.
- Our results end 2026-09-23, 10 days before this game; the season rates stop there.

**What the price says**

- Across 11 books the market makes the Brewers a 65.2% favourite (a fair price of -188) and the Padres 34.8%, with each book's margin removed.
- The board was captured 60 minutes before this page was built, which is older than we like.
- This read leans toward the Brewers too, so it agrees with the market on direction. That is expected: starters and run rates are already in the price. It says nothing about whether the price is right.
- In our own pre-registered tests of features like these against the market, none held up as a betting advantage. Treat everything above as a description of the game.

**What would change it**

- A change of starting pitcher. Both probables, Robbie Ray and Jacob Misiorowski, drive the pitching factors; a replacement or an opener voids them.
- The lineups, once posted. Platoon, depth and pitch-mix factors cannot be read until they are. Jacob Misiorowski has been weaker against right-handed bats (330 and 262 batters faced on each side), so the make-up of the opposing lineup matters.
- Whether the roof is open or closed. The page does not give the roof state, and it decides whether the weather matters.

**What we could not use (13)**

- [stale] Team results. our results end 2026-09-23, 10 days before this game, so last-five, last-ten, rest and travel are older than they look
- [stale] Pitcher logs. our pitcher logs end 2026-09-07, 26 days before this game, so starters' season lines and last-three-start figures miss anything newer, and a rest figure of 14 or more days is not reliable
- [absent] Lineups. lineup not posted yet, or not fetched
- [absent] Batter against pitcher history. batter-vs-pitcher history not fetched
- [stale] Bullpen workload. our bullpen log ends 2026-09-06, 27 days before this game, so the seven day workload window holds 0 relief outings for the Padres and 0 for the Brewers; it is not used
- [absent] Padres travel. no games in the window to travel from; our results end 2026-09-23, 10 days before this game
- [absent] Brewers travel. no games in the window to travel from; our results end 2026-09-23, 10 days before this game
- [stale] Days of rest. the rest days on the page (10 and 10) are the gap since the newest game in our results, and our results end 2026-09-23, 10 days before this game, so they are not a measured break
- [absent] Roof state. American Family Field has a retractable roof and the page does not say whether it is closed
- [absent] League standings. no standings snapshot stored for 2026-10-03
- [absent] Matchup depth. no posted lineup for this game, so there is no unit to decompose
- [absent] Robbie Ray platoon split. no platoon split is on file for Robbie Ray
- [stale] Jacob Misiorowski platoon split. the split was last updated 2026-09-08, 25 days before this game

<!-- READS:END -->
