# Tennis in-play calibration, v2 (early rounds, 15-minute snapshots)

This page looks at one question about past tennis matches: when the pre-match favourite fell behind in the betting during the match, how often did they still win, compared with what the market price at that moment said? It describes history. It is not a betting system.

## CORRECTION (2026-10-29): the band tables below are biased; use this one

The tables below put each favourite in the band of the LONGEST price they reached. A favourite who loses always ends at a very long price, so the shorter bands hold only winners by construction (the 100% rows). Corrected: count every favourite the first time they touch each band, before the match is decided. Combined v1+v2:

| Band | n | Wins | Win rate | Implied | ROI per 1u | 95% range |
|---|---|---|---|---|---|---|
| -150..-101 | 25 | 14 | 56% | 55% | +3% | 37-73% |
| +100..+149 | 17 | 6 | 35% | 45% | -23% | 17-59% |
| +150..+249 | 13 | 7 | 54% | 36% | +52% | 29-77% |
| +250 or longer | 15 | 3 | 20% | 22% | -7% | 7-45% |

Every range includes the market's own price: no evidence of an edge either way, on 70 band touches. The fix still has to be folded into the module's build step.

## How to read the numbers (please read first)

- The prices come from 15-minute snapshots, and each snapshot is at least 5 minutes old when we see it. These are not prices you could actually have bet. In a live tennis match the price can move a lot in five minutes.
- Each price is the middle (median) price across sportsbooks, not the best price available. A real bettor could do better or worse than that.
- Winners are worked out from the odds themselves: a player counts as the winner if the last snapshot where someone was priced -1500 or shorter shows them as the heavy favourite. If no snapshot got that far, the match is marked unsettled and left out. We never guess a winner. This leaves out matches that dropped off the feed early.
- Implied probability here includes the sportsbook's built-in margin, so it runs slightly high and the calibration gap runs slightly low. A margin-free version is in the data file as mean_fair_prob.

## What was collected

- 145 snapshots across 11 tournament-days; 224 matches seen.
- Match outcomes: no_inplay 122, no_prematch_snapshot 1, settled 77, unsettled 24.
- 77 matches were settled; 27 produced a favourite price in one of the four bands below.

**The sample is small (27 banded matches). Treat every number below as a rough look, not a finding. The ranges are wide for a reason.**

## Results by price band

A favourite is put in the band of the longest price they reached during the match. The numbers then use the FIRST time they hit that band. Win rate has a 95% Wilson range. Gap = win rate minus the average implied probability at that first moment. ROI is a flat 1-unit bet at that first-hit median price (not obtainable in practice). The last column counts first hits where the other player was already at -1500 or shorter, meaning the match was effectively over.

| Band | Matches | Wins | Win rate (95% range) | Avg implied | Gap | ROI per 1u | Already decided |
|---|---|---|---|---|---|---|---|
| -150..-101 | 6 | 6 | 100.0% (61.0% to 100.0%) | 55.7% | +44.3 pts | +79.8% | 0 |
| +100..+149 | 2 | 2 | 100.0% (34.2% to 100.0%) | 47.2% | +52.8 pts | +112.0% | 0 |
| +150..+249 | 5 | 5 | 100.0% (56.6% to 100.0%) | 35.3% | +64.7 pts | +184.2% | 0 |
| +250 or longer | 14 | 2 | 14.3% (4.0% to 39.9%) | 21.7% | -7.4 pts | -32.1% | 0 |

## What this does and does not show

In -150..-101, +150..+249 the 95% range for the win rate does not include the average implied probability. That is one exploratory result among four bands looked at, with matches clustered inside a few tournament-days and stale median prices. It is a reason to write a pre-registered test, not a reason to bet.

No edge is claimed. A real test needs a pre-registered plan, live prices you could actually bet, and a much larger sample.

## Combined with v1

v1 (hourly, late rounds) gave 60 events; v2 gave 224; after removing duplicate event ids there are 284. Outcomes: no_inplay 153, no_prematch_snapshot 1, settled 90, unsettled 40.

```
band               n  wins  win rate  implied         gap
-150..-101         8     8    100.0%    55.0%   +45.0 pts
+100..+149         2     2    100.0%    47.2%   +52.8 pts
+150..+249         5     5    100.0%    35.3%   +64.7 pts
+250 or longer    16     3     18.8%    20.7%    -2.0 pts
```

The two plans differ in cadence and round mix, so treat the pooled rows as a rough look, not a finding.

