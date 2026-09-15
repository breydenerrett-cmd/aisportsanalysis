**Refutation: tennis data recommendation, checked against the vendor findings**

**Problems, most severe first**

**1. "All three planned tennis rules can be priced off match winner."**
- **Why:** No URL backs this, and no finding says it. The plan contradicts itself: check 7 gates the upgrade on a second-set-winner market and check 8 on a suspension flag. Neither check would matter if match winner were enough. The Odds API findings count set-winner markets and a suspended flag as part of R3, and The Odds API has neither (tennis-odds.html). If any rule needs either one, the recommended $40 stack cannot run it.
- **Fix:** List the three rules. For each, name the market, the trigger, the serving flag and the suspension state it needs, and cite the rule spec. If all three really use only match winner, drop checks 7 and 8 as gates. If not, delete the sentence.

**2. "move up to Business at $80 only if checks 7-9 pass."**
- **Why, part 1:** Look at the other branch. If checks 7-9 fail, the owner stays on Starter plus The Odds API. That stack has no suspension flag and no set-winner market. Its in-play prices update every 40s and would be polled once a minute. So checks 7-9 never decide whether the live rules can run at all.
- **Why, part 2:** get_live_odds is Business-only, so checks 7-9 can only run on the free Business trial. That means the answer is known before any payment. "Pay Starter, then upgrade" would be two charges ($40 + $80), and API-Tennis terms say nothing about proration.
- **Fix:** Pick the tier before day 14 of the Business trial and pay one month of one tier. If checks 7-9 fail, mark the rules that need set-winner or suspension as unsupported and don't build them. Pay for Starter only if the remaining rules pass on match-winner evidence.

**3. Pass rules that would pass a feed unable to support the live rules**
- **Check 6, "Pass: match winner in 90%+ of them, from 2+ books."** A feed with no set markets and no suspension flag passes this. Fix: require the market each rule actually uses.
- **Check 7, "Pass if the market opens within 2 minutes of set 1 ending in 80%+ of matches."** A market counts as "open" even if it is suspended or its last update is from before the set ended. No sample size is given. Fix: pass when the first line with suspended=No and upd later than the set-1 end appears within 120s, in at least 80% of at least 20 matches.
- **Check 8, "Pass if the flag switches on and off in 8 of 10 matches."** A flag that flips at random passes. Fix: at 20 or more known moments (point in play, break, set end, medical timeout), the flag must match the book's own in-play state at least 90% of the time. It must also be off whenever a price is posted.
- **Check 9, "Pass: at least 20s faster than The Odds API."** This is relative to a feed that updates every 40s and is polled every 60s, so an API-Tennis price 60s after the trigger could still pass. "First new price" also doesn't require the market to be unsuspended. Fix: use absolute limits. From trigger to first unsuspended price with upd after the trigger: median 10s or less, worst case 30s or less, over 20 or more triggers.
- **Check 4, "Pass: event_status tells them apart from 'Finished'."**
  - It passes by default if no retirement or walkover happens during the 14 days.
  - It doesn't require retired, walkover and cancelled to differ from each other, and each grades differently.
  - Fix: require at least 3 retirements and 1 walkover (backfill with known past cases through get_fixtures), each with its own status value. Zero observed means fail, not pass.
- **Check 2, "check 20 points across 10 live matches ... under 2% of points missing."** With 20 points, one miss is already 5%, so 2% can't be measured. Two points per match doesn't test a point log. Fix: compare the full pointbypoint log for 10 or more completed sets against the official score, and require the server to be right on every game.
- **Check 3 runs on the Business trial.** If it is measured over WebSockets, it tests a delivery path the plan doesn't buy (Starter REST polled at 15s or slower). Fix: measure on the tier and poll rate you will pay for.
- **Check 5, "request get_fixtures for 2022-03-15 and 2022-06-27."** 2022-03-15 is one of the documentation's own example dates, so it is the date most likely to work. Two days say nothing about depth for a 2021-2025 backtest. Fix: pull the full ATP and WTA singles draw for one Slam in each backtest year. Require winner, score and status on at least 98% of matches.
- **Check 11, "Pass: under 6,000."** Polling livescore every 15s all day already uses 5,760 requests. History pulls, pre-match odds and H2H share the same 8,000/day. Fix: count the full production call mix plus backfill on a busy day.
- **Missing checks and gates:** nothing tests how fast results are graded (R1) or whether results get corrected after the match. There is also no stated consequence if checks 3, 6, 10 or 11 fail.

**4. "My estimate for polling only after a trigger (1 region, h2h, one call a minute for 20 minutes) is about 20 credits per trigger."**
- **Why:**
  - The credit cost of a live odds call is not in any finding. Only the historical cost (10 credits) is.
  - Every ATP and WTA tournament has its own sport key. Triggers in different tournaments at the same time can't share a call, and adding spreads and totals triples the cost.
  - There is no triggers-per-day figure, so no monthly total. The current MLB/NFL plan tier and its spare credits are not stated anywhere.
  - The Odds API covers only 45 tournament keys, with no Challengers. A trigger in a match outside those keys can't be priced at all.
  - Polling once a minute against a 40s update cycle can return a price over 100s old.
- **Fix:** Monthly credits = sport-key-minutes with an open trigger × markets × regions × live cost. Take the live cost from the-odds-api.com/liveapi/guides/v4/ and confirm it with the usage headers during the trial. State the current plan tier and its spare credits, and limit the rules to matches inside the 45 keys.

**5. "about 8,080 in total." / "Snapshots closer to each match start cost more." / "You don't need to buy anything extra."**
- **Why:**
  - One snapshot per match day per key is one timestamp. Late matches are hours away from starting, and early ones are already in play.
  - Pricing each match near its start needs several snapshots a day. Each snapshot still costs 10 credits; you just need more of them. Hourly snapshots over a 12-hour day make it 120 credits per key-day instead of 10, which is about 97,000 credits for the same 2021-25 window.
  - 2026 is left out, even though it is the only year with 500-level coverage (about 4,080 credits even at one snapshot a day).
  - Games markets would multiply the total by 3.
  - Depending on the unstated current tier, this could force a recurring plan upgrade.
- **Fix:** Re-estimate at the snapshot rate the backtest actually needs, per market, with 2026 included, and compare against spare credits. If it goes over, buy one month of the higher tier, pull everything, and downgrade before renewal.

**6. The backtest cannot test the in-play rules, and the plan doesn't say so ("Backtesting (R4, R5). You don't need to buy anything extra.")**
- **Why:**
  - Historical Odds API snapshots are 5-10 minutes apart (historical-odds-data/), so they can't give the price in the 2 minutes after a trigger.
  - No finding says API-Tennis history includes timestamped pointbypoint or event_serve, so past triggers can't be rebuilt.
  - The Odds API has no historical suspension state or set-winner market.
  - Only pre-match stand-ins can be backtested.
- **Fix:** Say plainly that the in-play rules will be forward-tested only, by paper trading during and after the trial. Add check 5b: historical get_fixtures returns timestamped point-by-point data.

**7. The backtest stores data with no licence ("Historical results have to come from API-Tennis get_fixtures.")**
- **Why:**
  - API-Tennis terms say nothing about storing data (R7 not stated), and the backtest keeps years of it. The recommendation itself says to treat that silence as no answer.
  - If the licence is refused, the stored grading data has to go, and there is no replacement source: The Odds API goes back 3 days, and BALLDONTLIE's history depth (R4) is not stated.
  - The standard is inconsistent. BettingIsCool is skipped because its terms "don't address paid products or storage," which is the same gap accepted for API-Tennis.
- **Fix:** Don't bulk-store API-Tennis history until the licence answer covers storage. At minimum, tag every row by source so it can be deleted. Use one rule for both vendors, or reject BettingIsCool on price instead (EUR 99, about $107) or because it only has one book.

**8. The fallback is not a real fallback ("If check 2, 4 or 5 fails, or the licence is refused, switch to BALLDONTLIE ALL-STAR ATP+WTA at $19.98 plus The Odds API.")**
- **Why, failure cases:**
  - If check 5 fails, BALLDONTLIE's history depth is also not stated, so there is no evidence it fixes the problem.
  - If check 2 fails, BALLDONTLIE has no point log at all.
  - BALLDONTLIE has no live odds or suspension flag either.
- **Why, cost:** Switching after a paid API-Tennis month means paying two vendors. BALLDONTLIE fees are non-refundable, and ATP and WTA are separate subscriptions.
- **Why, likely same backend:** AllSportsAPI (in the options table) probably runs on the same feed as API-Tennis.
  - **What the findings show:**
    - identical surface fields: hard_won/hard_lost, clay_won/clay_lost, grass_won/grass_lost;
    - the same missing indoor field;
    - the same endpoint list;
    - the same "Home/Away" market name and a live-odds "suspended" flag;
    - overlapping books (bet365, bwin, 1xbet, Betsson).
  - **What that suggests (unconfirmed):** a shared upstream feed.
  - **Why the "different product" verdict is weak:** it rests only on host names, parameter naming and pricing, which differ between storefronts anyway. A failure on API-Tennis will probably repeat on AllSportsAPI.
- **Fix:**
  - Run BALLDONTLIE's 48h trial inside the API-Tennis trial window and apply checks 4 and 5 to it before paying for either.
  - For each failed check, name a fallback that actually has the missing capability, or mark that rule unsupported.
  - Label AllSportsAPI "likely same feed as API-Tennis; not an independent alternative" until live JSON has been compared field by field.

**9. Ways the owner could pay for more than one month**
- **Trial auto-charge:** it is unknown whether the Business trial needs a card. If it does, day 14 could auto-charge $80. Fix: downgrade or cancel on day 12.
- **Licence wait:** "Until the licence gets a written yes, use the data for internal research only" has no end date. The reply could take weeks and run into a second month's renewal. Fix: cancel on the first day of the paid month (terms: "will not charge you for the following billing cycle") and resubscribe only after a written yes.
- **Also:** the two-step Starter-then-Business path (item 2), paying API-Tennis then switching to BALLDONTLIE (item 8), and a possible Odds API tier upgrade (item 5).

**10. "R1/R2: Starter includes Fixtures and Livescore."**
- **Why:** R1 is treated as covered because of feature names in the pricing table. The findings rate R1 as only partly met:
  - only '', 'Finished' and 'Set 1' statuses were seen;
  - Challenger and Davis Cup coverage is not stated;
  - how quickly results are graded is not stated.
- **Fix:** Call R1 "partly met." Add a check for how quickly final results post, over 50 or more matches, and a Challenger coverage check if any rule uses Challengers.

**11. "BALLDONTLIE's free tier gives rankings for any past date"**
- **Why:** atp.yml only says "Get rankings for specific date (YYYY-MM-DD)." The earliest date is not stated. No check links BALLDONTLIE player IDs to API-Tennis or Odds API names.
- **Fix:** Say "rankings for a given date; depth unverified." Add rankings-date and player-ID linking to check 10.

**12. Options table**
- **"AllSportsAPI Ultimate | 111 (renews at 149)":** the findings only infer renewal from the struck-through price; renewal terms aren't stated. Fix: "$111 (25% off $149; renewal terms not stated)." The row also leaves out two things in AllSportsAPI's favour: its terms explicitly allow storage, and point-by-point is on every tier. And add the likely-same-feed note from item 8.
- **The Odds API row, "Missing: live match state, player data":** it leaves out:
  - no suspension flag;
  - no set-winner market;
  - results only 3 days back;
  - status is only a completed true/false flag;
  - scores for just 10 of 45 keys;
  - no Challengers.

  "0 extra" also depends on spare credits nobody has stated. Fix: add all of these.
- **API-Tennis Business row, "suspended flag":** the only evidence is one doc example on a "Set 1 to Break Serve" market. No in-play set-winner market appears in the docs. Fix: add "set-winner market not shown" to Missing.

**13. Section 5 (ChatGPT claims)**
- **"Contradicted: ATP GOAT as the research feed."** This claim isn't among the ChatGPT claims in the findings, and the GOAT claims that were checked came back confirmed. "No WTA" is trivially true of an ATP product (a WTA GOAT exists). Fix: quote the actual ChatGPT sentence, or move this to your own assessment.
- **"Unverifiable: whether any trial needs a card."** This is too broad:
  - Goalserve's terms say billing info "may be required" and then auto-charge.
  - SportDevs' cached page says no card is needed.

  Fix: limit the claim to API-Tennis, BALLDONTLIE and AllSportsAPI.
- **Wrong citations:**
  - API-Tennis point-by-point and server fields come from api-tennis.com/documentation, not api-tennis.com/.
  - BALLDONTLIE GOAT features come from atp.yml.
  - Singles-only comes from atp.balldontlie.io, not #pricing.
- **The Odds API R7 quote drops a condition:** "provided our data is not the primary product being sold or redistributed." Fix: include it.

**What is sound**
- **Prices:** every price matches the findings and has a URL:
  - API-Tennis $40/$60/$80, with 8K/80K/200K requests a day, and in-play odds plus WebSockets only from Business up;
  - BALLDONTLIE $9.99/$39.99 per sport;
  - AllSportsAPI $59/$82/$111 at 25% off;
  - Goalserve $150/month or $1,200/year;
  - The Odds API $30/$59/$119.
- **API-Tennis licence:** treating its silent terms as "no answer, not a yes," and limiting use to internal research until a written yes.
- **The Odds API limits:** stated correctly (no set-winner market, no suspended flag, 40s in-play updates, scores 3 days back, derived values allowed).
- **Historical-odds depth:** Slams from 2020-21, Masters from 2024-25, most 500s from 2026, and "a multi-year backtest is mostly Slams" all match tennis-odds.html.
- **Arithmetic:**
  - The credit maths is right under its own assumptions: 1,120×3 + 1,840 + 2,880 = 8,080, at 10 credits per region per market.
  - Polling every 10s gives 8,640 requests, over the 8,000 limit, and a 15s floor keeps livescore alone under it.
- **Betfair:** the quote is accurate, and the self-serve tiers don't license use in a subscriber product.
- **BALLDONTLIE:** GOAT is correctly rejected as the research feed (moneyline only, about one season of opening odds, no surface splits), and its licence is correctly noted as allowing betting products.
- **Tier choice:** Business is correctly named as the cheapest API-Tennis tier with in-play odds, and Premium and Ultra are correctly not recommended.
- **Checks:** the "zero wrong links" rule in check 10 and the get_odds history probe in check 5 are the right instincts, and running checks on the free trial before paying is correct.
- **Other correct calls:**
  - Tennis-API.com is correctly treated as a separate company from API-Tennis.
  - $79.98 is correctly labelled as arithmetic rather than a published price.
  - API-Tennis month-to-month cancellation is real per its terms.