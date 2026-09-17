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
**Measured:** `{"matches_sampled": 8214, "matches_with_set_betting_quoted": 4917, "rate": 0.599}`

## Check 8: Suspension flag -- FAIL

**Question:** At >=20 known moments (break point, set end, medical timeout), does the suspension flag match the book's own in-play state?
**Threshold:** Matches at least 90% of the time; never shows a price while suspended.
**Measured:** `{"moments_checked": 638, "correct": 534, "priced_while_suspended": 104, "rate": 0.837}`

## Check 9: Freshness -- FAIL

**Question:** At >=20 triggers, how long from the trigger to the first unsuspended price updated after it?
**Threshold:** Median <=10 seconds, worst <=30 seconds, at the polling rate we'd pay for.
**Measured:** `{"triggers_observed": 5102, "median_latency_seconds": 54.029231548309326, "worst_latency_seconds": 89.67190265655518}`

## Check 10: Volume -- NOT ENOUGH DATA

**Question:** How many calls does a busy day take at production rates (live scores, live odds, fixtures, player data)?
**Threshold:** Under the plan's daily call limit, with room to spare.
**Measured:** `{"calls_accumulated": 25037, "polls_run": 367, "polls_errored": 10, "daily_limit_known": null}`
**Vendor limit, from api-tennis.com's own plan table (2026-09-16):** Business is $80/month for **200,000 requests/day**. The full-day run used **25,037 calls across 367 polls**, about 12.5% of the allowance -- so this check PASSES with genuine room to spare. (An earlier revision of this section said the limit was unpublished and the sample partial; both were true when written and are now superseded. A rescore regenerates this section, so a finding recorded here by hand can be overwritten -- that is how this note was lost once already.) 10 of 377 polls in this file failed to reach the vendor at all (see each record's 'detail' field), so calls_accumulated undercounts even a partial day. Re-run the sampler across a full day once it is reaching the vendor successfully to get a real count.

---

## DECISION: SKIP. Dated 2026-09-17. Nothing is paid to API-Tennis.

Four of the five measured checks fail, on samples large enough that none of it
is noise: 8,214 matches sampled for check 7, 5,102 triggers for check 9, across
a full day at production polling rates.

| Check | Threshold | Full-day measurement | Verdict |
|---|---|---|---|
| 6 Point log | every game's server correct | 2 of 188 points missing a server, 0 sets missing games | FAIL, narrowly |
| 7 Second-set market | priced in >=80% of matches | **59.9%** (4,917 of 8,214) | FAIL |
| 8 Suspension flag | >=90% correct, NEVER priced while suspended | 83.7%, and **104 moments priced while suspended** | FAIL |
| 9 Freshness | median <=10s, worst <=30s | **median 54.0s, worst 89.7s** | FAIL |
| 10 Volume | under the daily limit with room to spare | 25,037 calls against the Business plan's 200,000/day | PASS |

**Why this is a skip and not a close call.** The only check that passes is the
one that does not matter: we would have ample call quota to poll a feed that is
too slow and too incomplete to bet into. Check 9 is the disqualifier. A median
of 54 seconds means that by the time we see a price, the point, the game and
often the set have moved on. The entire premise of the owner's in-play idea --
Alcaraz drops the first set, take him in the second before the market catches
up -- requires seeing the price move BEFORE the book does. At 54 seconds we are
not sniping the market; we are the last to know.

Check 8 is independently disqualifying and worse in kind. The feed showed a
price while the market was suspended 104 times. A stale price is a bad bet; a
price that does not exist is a phantom bet that would be recorded as real in a
paper ledger and quietly poison the evidence.

**The websocket question was raised and is closed.** The Business plan
advertises Web Sockets, and every latency number above was measured by polling,
so failing the product on the wrong transport was a real risk. It is not what
happened: the vendor documents ONE socket, `wss://wss.api-tennis.com/live`,
whose schema carries scores and point-by-point only, and an empirical probe --
15 messages, 24 distinct matches, 46KB-191KB each -- found zero occurrences of
any odds, price or suspension field. There is no faster transport carrying
prices at any tier, so the polling number is the measurement of the only feed
that has odds in it.

**What this costs us, stated plainly.** The owner's exact bet -- a second-set
moneyline after a favourite drops the first -- has no reachable licensed source
now. The Odds API carries tennis match-winner only: no set winner, no next-set
market. So `docs/SNIPE_SYSTEM.md`'s tennis rule narrows to MATCH WINNER, and
that substitution is recorded on the face of the rule rather than in a
footnote, because a match-winner bet is a different and worse bet than the one
that was asked for, and nobody should later mistake one for the other.

**What would change this.** A vendor whose in-play prices arrive inside ten
seconds and who never quotes a suspended market. That is the bar, it is written
down here, and this decision gets revisited if such a feed is found -- not
because this one gets cheaper.

The trial key expires 2026-09-18 and is not being renewed.
