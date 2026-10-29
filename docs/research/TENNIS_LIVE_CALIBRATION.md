# Tennis in-play calibration (history, exploratory)

This page looks at one question about past tennis matches: when the pre-match favourite fell behind in the betting during the match, how often did they still win, compared with what the market price at that moment said? It describes history. It is not a betting system.

## How to read the numbers (please read first)

- The prices come from hourly snapshots, and each snapshot is at least 5 minutes old when we see it. These are not prices you could actually have bet. In a live tennis match the price can move a lot in five minutes.
- Each price is the middle (median) price across sportsbooks, not the best price available. A real bettor could do better or worse than that.
- Winners are worked out from the odds themselves: a player counts as the winner if the last snapshot where someone was priced -1500 or shorter shows them as the heavy favourite. If no snapshot got that far, the match is marked unsettled and left out. We never guess a winner. This leaves out matches that dropped off the feed early.
- Implied probability here includes the sportsbook's built-in margin, so it runs slightly high and the calibration gap runs slightly low. A margin-free version is in the data file as mean_fair_prob.

## What was collected

- 140 snapshots across 24 tournament-days; 60 matches seen.
- Match outcomes: no_inplay 31, settled 13, unsettled 16.
- 13 matches were settled; 4 produced a favourite price in one of the four bands below.

**The sample is small (4 banded matches). Treat every number below as a rough look, not a finding. The ranges are wide for a reason.**

## Results by price band

A favourite is put in the band of the longest price they reached during the match. The numbers then use the FIRST time they hit that band. Win rate has a 95% Wilson range. Gap = win rate minus the average implied probability at that first moment. ROI is a flat 1-unit bet at that first-hit median price (not obtainable in practice). The last column counts first hits where the other player was already at -1500 or shorter, meaning the match was effectively over.

| Band | Matches | Wins | Win rate (95% range) | Avg implied | Gap | ROI per 1u | Already decided |
|---|---|---|---|---|---|---|---|
| -150..-101 | 2 | 2 | 100.0% (34.2% to 100.0%) | 52.8% | +47.2 pts | +89.5% | 0 |
| +100..+149 | 0 | 0 | n/a | n/a | n/a | n/a | 0 |
| +150..+249 | 0 | 0 | n/a | n/a | n/a | n/a | 0 |
| +250 or longer | 2 | 1 | 50.0% (9.5% to 90.5%) | 13.7% | +36.3 pts | +120.0% | 1 |

## What this does and does not show

In every band the 95% range for the win rate includes the average implied probability, so this data shows no gap between what the market implied and what happened. That is not proof the prices are right; with this sample it simply cannot tell.

No edge is claimed. A real test needs a pre-registered plan, live prices you could actually bet, and a much larger sample.

