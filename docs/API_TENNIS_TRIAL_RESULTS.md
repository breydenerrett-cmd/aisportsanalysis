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
**Vendor limit, found 2026-09-16 (api-tennis.com homepage, plan table):** Business
is $80/month and **200,000 requests/day**. (Starter $40 / 8,000; Premium $60 /
80,000; Ultra $120 / 2,000,000. Daily allowances only -- no monthly or
per-minute cap is stated.) So check 10 finally has a number to be scored
against. At the rate the short window ran (209 calls in about 3 minutes, ~70
per minute) a 24-hour day at that rate is roughly 100,000 calls, about half
the Business allowance -- inside the limit, but "room to spare" is thin, and
the real figure is whatever the full-day run at production polling rates
records.

**MATERIAL FINDING FOR THE DECISION -- we may be measuring the wrong
transport.** The same plan table lists **Web Sockets** as a Business-tier
feature. Every latency number in check 9 was measured by POLLING, and a 37.8s
median is exactly what polling a slow REST endpoint looks like. If the
websocket feed pushes state changes, the freshness check could look completely
different on the transport we would actually pay for, and check 9's threshold
says "measured at the polling rate we would pay for" -- which presumes polling
is the transport. Do not record a skip on check 9 alone until the websocket
feed has been tried or ruled out; a fail measured on a transport we would not
use is not evidence about the product we would buy.

**Note:** The vendor's Business-plan daily call limit was not published at trial signup, so this reports the measured full-day call count for comparison against whatever limit the plan states; it is not assumed to pass. INSUFFICIENT SAMPLE: this is a partial day only, not a full day at production polling rates. 9 of 11 polls in this file failed to reach the vendor at all (see each record's 'detail' field), so calls_accumulated undercounts even a partial day. Re-run the sampler across a full day once it is reaching the vendor successfully to get a real count.

