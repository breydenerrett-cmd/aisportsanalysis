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
**Measured:** `{"matches_sampled": 65, "matches_with_set_betting_quoted": 38, "rate": 0.585}`

## Check 8: Suspension flag -- FAIL

**Question:** At >=20 known moments (break point, set end, medical timeout), does the suspension flag match the book's own in-play state?
**Threshold:** Matches at least 90% of the time; never shows a price while suspended.
**Measured:** `{"moments_checked": 638, "correct": 534, "priced_while_suspended": 104, "rate": 0.837}`

## Check 9: Freshness -- FAIL

**Question:** At >=20 triggers, how long from the trigger to the first unsuspended price updated after it?
**Threshold:** Median <=10 seconds, worst <=30 seconds, at the polling rate we'd pay for.
**Measured:** `{"triggers_observed": 35, "median_latency_seconds": 37.80629277229309, "worst_latency_seconds": 39.245381593704224}`

## Check 10: Volume -- NOT ENOUGH DATA

**Question:** How many calls does a busy day take at production rates (live scores, live odds, fixtures, player data)?
**Threshold:** Under the plan's daily call limit, with room to spare.
**Measured:** `{"calls_accumulated": 209, "polls_run": 2, "polls_errored": 9, "daily_limit_known": null}`
**Note:** The vendor's Business-plan daily call limit was not published at trial signup, so this reports the measured full-day call count for comparison against whatever limit the plan states; it is not assumed to pass. INSUFFICIENT SAMPLE: this is a partial day only, not a full day at production polling rates. 9 of 11 polls in this file failed to reach the vendor at all (see each record's 'detail' field), so calls_accumulated undercounts even a partial day. Re-run the sampler across a full day once it is reaching the vendor successfully to get a real count.

