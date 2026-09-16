# API-Tennis Business trial results

Generated: 2026-09-16T06:23:00Z

Checks and thresholds are from `docs/TENNIS_FEED_DECISION_2026-09-15.md`, "The free-trial checklist" (checks 6-10; check 5, the licence email, is manual and tracked separately).

Live matches observed this run: **19**

## Check 6: Point log -- FAIL

**Question:** For >=10 completed sets, does the point-by-point log match the official score (server correct every game, no missing games)?
**Threshold:** Every game's server correct, no missing games, across >=10 completed sets.
**Measured:** `{"sets_checked": 30, "points_seen": 188, "points_missing_server": 2, "sets_with_missing_games": 0, "problems_sample": []}`

## Check 7: Second-set market speed -- FAIL

**Question:** For >=20 matches, how long from end of set 1 to the first unsuspended second-set price updated after the set ended?
**Threshold:** Within 120 seconds in at least 80% of matches.
**Measured:** `{"matches_sampled": 19, "matches_with_set_betting_quoted": 8, "rate": 0.421}`
**Note:** only 19 matches with a completed set 1 sampled this run (need >=20); this check needs repeated runs across the trial window -- see docs/TENNIS_FEED_DECISION_2026-09-15.md.

## Check 8: Suspension flag -- FAIL

**Question:** At >=20 known moments (break point, set end, medical timeout), does the suspension flag match the book's own in-play state?
**Threshold:** Matches at least 90% of the time; never shows a price while suspended.
**Measured:** `{"moments_checked": 638, "correct": 534, "priced_while_suspended": 104, "rate": 0.837}`

## Check 9: Freshness -- FAIL

**Question:** At >=20 triggers, how long from the trigger to the first unsuspended price updated after it?
**Threshold:** Median <=10 seconds, worst <=30 seconds, at the polling rate we'd pay for.
**Measured:** `{"triggers_observed": 7, "poll_gap_seconds": 5.0, "median_latency_seconds": 23.578524112701416, "worst_latency_seconds": 24.511838912963867}`
**Note:** only 7 price-change triggers observed in one 5.0s poll window (need >=20); this check needs a longer-running poller across the trial, not one script pass.

## Check 10: Volume -- NOT ENOUGH DATA

**Question:** How many calls does a busy day take at production rates (live scores, live odds, fixtures, player data)?
**Threshold:** Under the plan's daily call limit, with room to spare.
**Measured:** `{"calls_this_run": 77, "daily_limit_known": null}`
**Note:** This run's own call count is a lower bound only. The real check needs counting every call across one full day at the intended production polling rate (live scores, live odds, fixtures, player data) and comparing to the Business plan's stated daily limit -- run scripts/api_tennis_trial.py on a schedule for a day and sum its calls, or check the vendor dashboard's own daily usage counter if it has one.
