# Tennis Results Feed Options

**Verification date: 2026-09-14.** Every price and term below was read on the vendor page linked in the same row on that date.

## Vendor Comparison Table

| Vendor | Coverage (R1) | API (R2) | Commercial licence (R3) | Price (R4) | Trial | Live (R5) | Verified URL | Notes |
|--------|----------|-----|-------------------|-----------------|-----------|------------|-----|--------|
| **Goalserve** | ATP, WTA, Davis Cup, ITF, Challenger, Grand Slams | REST JSON/XML, stable match IDs | Page allows use in "livescore, fantasy applications, betting and more" | $150/mo, or $1,200/yr | Yes, 30 days on request | Yes, every 5 seconds, point by point | [Coverage](https://www.goalserve.com/en/sport-data-feeds/tennis-api/coverage) [Prices](https://www.goalserve.com/en/sport-data-feeds/tennis-api/prices) | Only vendor with published language allowing betting apps. |
| **api-tennis.com** | ATP, WTA, ITF, Challenger | REST JSON, stable tournament/match IDs | Terms neither grant nor forbid commercial use | $40/mo (Starter, 8,000 req/day) | 14 days free | Yes, point by point over WebSocket on Business ($80/mo) and up | [Pricing](https://api-tennis.com/) [Docs](https://api-tennis.com/documentation) [Terms](https://api-tennis.com/terms-of-use) | Cheapest. Davis Cup not listed in the docs. |
| **Live Tennis API** | ATP, WTA, Challenger, ITF, singles and doubles | REST + WebSocket JSON, stable match/player IDs | Commercial use implied by paid tiers, not stated | Free tier, then $9.99–$99.99/mo | Free tier: 30 req/min, 100/day | Yes, with win probability on paid tiers | [Homepage](https://livetennisapi.com/) | MIT client libraries. Davis Cup not confirmed. |
| **SportsDataIO** | Real time; tournament list not published | REST JSON, stable identifiers | Self-serve tier is "not licensed for commercial redistribution"; production licence is quoted | Discovery Lab $99–$149/mo | Yes, demo data | Yes, from pre-match on | [Tennis API](https://sportsdata.io/tennis-api) [Trial](https://sportsdata.io/cart/free-trial/tennis) | Real price needs a sales call. |
| **Sportradar** | 4,000+ competitions: ATP, WTA, Grand Slams, ITF, Davis Cup | REST JSON | Betting use is not banned but needs "express written approval from Sportradar" at its discretion (Master Terms 2.10, 8.2.3) | Enterprise, $10,000+/mo | No | Yes, real time | [Marketplace](https://marketplace.sportradar.com/products/6501e20f236aba44b550bdae) [Master Terms](https://developer.sportradar.com/sportradar-updates/page/master-terms-and-conditions-for-non-betting-services) | Official ATP partner. Approval gate plus sales call: too slow to buy this week. |
| **The Odds API** | Grand Slams, ATP 1000/500, WTA 1000/500 | REST JSON, odds only, no scores endpoint for tennis | Not documented | Tennis is on paid tiers, price not listed | Free tier is NBA and MLB only | No | [Tennis](https://the-odds-api.com/sports/tennis-odds.html) [Docs](https://theoddsapi.com/docs/) | **Fails R1: odds, not results.** |
| **API-Sports** | Unknown | Unknown | Unknown | Unknown | Unknown | Unknown | HTTP 403 on fetch | Site would not load; nothing verified. |
| **Sportmonks** | Unclear; sources disagree on whether a tennis product exists | Unknown | Unknown | Unknown | Unknown | Unknown | [Homepage](https://www.sportmonks.com/) | Mainly football, cricket, F1. |

## Recommendation

**Primary: Goalserve, $150/mo.** It is the only vendor whose own page names all three required tours, including Davis Cup, and the only one that says in writing that the feed may be used in betting applications — which is exactly the licence question a paid analysis subscription has to answer ([coverage](https://www.goalserve.com/en/sport-data-feeds/tennis-api/coverage), [prices](https://www.goalserve.com/en/sport-data-feeds/tennis-api/prices)). The same page offers a free 30-day trial on request, so the feed can be tested before any money moves. Buy it if the answer must be certain this week.

**Fallback: api-tennis.com, $40/mo.** A quarter of the price, documented JSON with stable IDs, and a 14-day trial to test the data before paying ([pricing](https://api-tennis.com/), [docs](https://api-tennis.com/documentation)). Two gaps to close first, both by email: Davis Cup is not in the published coverage list, and the terms are silent on commercial use ([terms](https://api-tennis.com/terms-of-use)). Only take this route with written answers to both.

## Unverified

- **Results within a few hours of match end (R1 latency).** No vendor publishes a post-match latency figure. All of them advertise live scoring, which implies results land quickly, but the "few hours" bar is inferred, not sourced.
- **"Live Tennis API roughly $10 to $100 per month."** Close but restate it: the site lists $9.99–$99.99/mo plus a free tier ([livetennisapi.com](https://livetennisapi.com/)). Tour-by-tour coverage and the licence for a paid product are not stated anywhere on the page.
- **Sportradar as the "safe" enterprise pick.** Its terms permit betting use only with express written approval, at its discretion ([Master Terms](https://developer.sportradar.com/sportradar-updates/page/master-terms-and-conditions-for-non-betting-services)). Whether a small subscription business would be approved, and the real price, are both unknown.
- **SportsDataIO production pricing.** The $99–$149/mo self-serve tiers exclude commercial redistribution; the commercial rate is quote-only ([developers](https://sportsdata.io/developers/apis)).
- **API-Sports tennis.** Nothing confirmed: the site returned HTTP 403.
- **Sportmonks tennis.** No product page found; treat as non-existent until shown otherwise.
