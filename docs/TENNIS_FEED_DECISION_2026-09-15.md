# Tennis data: what to buy (revised 2026-09-15)

**Supersedes** the Goalserve recommendation in
[TENNIS_RESULTS_FEED_OPTIONS.md](TENNIS_RESULTS_FEED_OPTIONS.md) and section 1 of
[STRATEGY_LAB_PLAN.md](STRATEGY_LAB_PLAN.md). Built from a check of every
feed named in the ChatGPT review plus a search for others under $100 a month.
Every vendor page was read on 2026-09-15; prices and features link to the page
they came from. The statistical and factual challenge that corrected the first
draft is summarised at the end.

## The answer

**Don't buy Goalserve.** Its pages show no historical odds product at any
price, say nothing about how far back results go, and say nothing about using
the data in a paid betting-analysis product. They even quote two different
6-month prices ([prices](https://www.goalserve.com/en/sport-data-feeds/tennis-api/prices),
[odds products](https://www.goalserve.com/en/sport-data-feeds/odds-api/prices),
[terms](https://www.goalserve.com/en/terms-and-conditions)).

**Buy this instead, in this order, trying each free first:**

| Step | What | Cost | Why | Click |
|---|---|---|---|---|
| 1 | **BALLDONTLIE ALL-STAR, ATP and WTA** (two subscriptions) | **$19.98 a month** ($9.99 per tour) | The only vendor whose terms plainly allow use in "lawful betting or wagering products", including storing and archiving the data. Match results with a status that tells retired, walkover and defaulted apart; live score with who is serving; rankings on any past date. 48-hour free trial. | [ATP API](https://atp.balldontlie.io/) · [WTA API](https://wta.balldontlie.io/) · [pricing](https://www.balldontlie.io/#pricing) · [terms](https://www.balldontlie.io/terms.html) · [ATP spec](https://www.balldontlie.io/openapi/atp.yml) |
| 2 | **API-Tennis Business**, only if the trial checks below pass | **$80 a month** | The live tennis rules need three things BALLDONTLIE does not have: a point-by-point log, in-play odds, and a flag for when a book suspends a market. API-Tennis Business has all three. Its terms say nothing either way about paid products, so it stays internal research until they confirm in writing. 14-day free trial. | [pricing](https://api-tennis.com/) · [docs](https://api-tennis.com/documentation) · [terms](https://api-tennis.com/terms-of-use) · [register](https://api-tennis.com/register) · [contact](https://api-tennis.com/contact) |
| — | **The Odds API**, already paid | $0 extra (credits) | Pre-match tennis odds for today's picks, in-play match-winner prices, and historical odds for backtests. Its terms allow displaying values derived from its data, provided the data itself is not the product sold. | [tennis coverage](https://the-odds-api.com/sports/tennis-odds.html) · [historical](https://the-odds-api.com/historical-odds-data/) · [terms](https://the-odds-api.com/terms-and-conditions.html) |

**Month-one cost: $19.98, or $99.98 if API-Tennis passes.** That's against the
$190 in the earlier plan.

## What each piece is for

- **Grading tennis picks (results and retirements):** BALLDONTLIE. Its match
  status list includes finished, retired, walkover, defaulted, suspended and
  canceled, so the retirement rule can be applied exactly
  ([ATP spec](https://www.balldontlie.io/openapi/atp.yml)). It covers Grand
  Slams, 1000s, 500s and 250s; Challengers and Davis Cup are not listed.
- **Pre-match tennis picks:** The Odds API prices we already capture, plus
  BALLDONTLIE for player context.
- **Surface records ("who is good on clay"):** BALLDONTLIE has no surface
  splits; API-Tennis's player data has hard, clay and grass won-lost counts but
  no indoor ([docs](https://api-tennis.com/documentation)). Without API-Tennis
  we build surface records ourselves from the results we store, which is also
  the only way to know a record as it stood on the match date.
- **Live tennis rules** (favourite loses the first set, break of serve against
  the favourite, favourite down a break in the deciding set): need API-Tennis
  Business. The Odds API's in-play tennis prices refresh every 40 seconds, have
  no set-winner market and no suspension flag
  ([tennis coverage](https://the-odds-api.com/sports/tennis-odds.html)), so
  they cannot price a rule that fires at a break of serve honestly.
- **Backtests:** pre-match only. The Odds API's historical tennis odds start in
  2020 to 2021 for the Grand Slams, 2024 to 2025 for most 1000s, and 2026 for
  most 500s ([tennis coverage](https://the-odds-api.com/sports/tennis-odds.html)),
  so a multi-year backtest is mostly Slams. There is no historical in-play data
  anywhere in this stack, so **the live rules are forward-tested only.**

## Credits for the backtest (estimate)

Historical snapshots cost 10 credits per region per market
([historical](https://the-odds-api.com/historical-odds-data/)), and every
tournament has its own key. One pre-match snapshot per tournament per match
day for 2021 to 2025 is about 8,000 credits; adding 2026 is about 4,000 more.
Pricing each match close to its own start needs several snapshots a day, which
multiplies that (hourly would be roughly 100,000). Plan: two snapshots a day,
Slams and 1000s only, about 16,000 credits, run just after the monthly credit
reset, because this cycle has about 21,800 left.

## The free-trial checklist (run before paying anything)

**BALLDONTLIE, 48-hour trial, ATP and WTA:**
1. **Results:** pull the full singles results for one Grand Slam in each of
   2022, 2023, 2024 and 2025. Pass: winner, score and status on at least 98% of
   matches.
2. **Retirements:** find at least 3 retirements and 1 walkover among them.
   Pass: each carries its own status value. Zero found is a fail, not a pass.
3. **Live:** on 10 live matches, compare server and game score to the official
   live score every few minutes. Pass: server correct every time.
4. **Matching:** link one day of matches to The Odds API's events by player and
   date. Pass: at least 95% linked, zero wrong links.

**API-Tennis, 14-day trial on the Business tier** (in-play odds only exist on
Business, so the trial shows the answer before any payment):
5. **Licence first:** email the three questions below through the
   [contact page](https://api-tennis.com/contact) on day 1. No written yes means
   internal research only, whatever the other checks say.
6. **Point log:** for at least 10 completed sets, compare the point-by-point
   log with the official score. Pass: every game's server correct, no missing
   games.
7. **Second-set market:** for at least 20 matches, time from the end of set 1
   to the first second-set price that is not suspended and was updated after
   the set ended. Pass: within 120 seconds in at least 80% of matches.
8. **Suspension flag:** at 20 or more known moments (break point, set end,
   medical timeout), check the flag against the book's own in-play state.
   Pass: matches at least 90% of the time, and never shows a price while
   suspended.
9. **Freshness:** at 20 or more triggers, time from the trigger to the first
   unsuspended price updated after it. Pass: median 10 seconds or less, worst
   30 seconds or less, measured at the polling rate we would pay for.
10. **Volume:** count every call on a busy day at production rates (live scores,
    live odds, fixtures, player data). Pass: under the plan's daily limit with
    room to spare.

**Decide by day 12 of the API-Tennis trial.** If checks 6 to 10 pass and the
licence answer is yes, pay one month of Business. If any fails, the live tennis
rules that need it are marked unsupported and not built, and nothing is paid to
API-Tennis. Cancel on the first day of any paid month so it cannot renew
without a decision (its terms: "All our plans are on a monthly basis").

**The three licence questions** (send to both vendors' support if in doubt):
1. May we use the data inside a paid consumer sports-betting analysis
   subscription?
2. May we store timestamped snapshots of the data to backtest our own models?
3. May we show subscribers numbers we derive from the data (not the raw
   feed)?

## Not recommended, and why

- **AllSportsAPI** ([tennis](https://allsportsapi.com/tennis-api)): $59, $82 and
  $111 are 25%-off prices, and its field names, endpoints, markets and books
  match API-Tennis closely enough that it is probably the same feed. It is not
  an independent fallback.
- **Tennis-API / SportsAPI365** ([pricing](https://tennis-api.com/api-pricing/)):
  a separate company; WebSocket access from $99; historical results are claimed
  only in marketing copy.
- **BALLDONTLIE GOAT** ($39.99 per tour): adds match statistics and opening
  odds, but the odds are match winner only and cover "the most recently
  completed season", with no surface records. Not worth it this month.
- **Betfair historical data** (GBP 49): licensed for "personal, internal use
  only".

## ChatGPT's claims, checked

Confirmed: API-Tennis's $40, $60 and $80 tiers, in-play odds and WebSockets
on Business, the point-by-point and serving fields, the 14-day trial;
BALLDONTLIE's $9.99 and $39.99 per-sport tiers, GOAT's stats, head-to-head and
odds, DraftKings and FanDuel as odds sources (Caesars too), singles only;
AllSportsAPI's discounted $59, $82 and $111; Tennis-API.com's $99 WebSocket
tier and that it is a separate company; Goalserve's $150 a month or $1,200 a
year; The Odds API's $30, $59 and $119 plans, match-winner tennis coverage and
40-second in-play updates. Partly: $79.98 for both GOAT plans is arithmetic,
not a published price. Not supported: BALLDONTLIE GOAT as the research feed,
for the reasons above.

## What the challenge corrected

The first draft said "pay API-Tennis Starter, upgrade later" and "all three
live rules can be priced off the match-winner market". The review found no
source for the second claim, and pointed out that Starter has no in-play odds,
so the trial must be run on Business and the tier chosen before paying once.
It also found trial pass rules that a useless feed could pass, a backtest
credit estimate that ignored snapshot timing, that the backtest cannot test the
live rules at all, and that the old fallback shared API-Tennis's gaps. All of
that is corrected above.
