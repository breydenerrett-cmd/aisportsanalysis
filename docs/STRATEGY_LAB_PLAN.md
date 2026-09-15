# Strategy Lab: what to buy, and the plan for NFL, tennis and MLB

Written 2026-09-15 for Brey. Every price and claim below links to the page it
came from. Where a number is an assumption it says so.

Two things first, because they shape everything else:

1. **The last time we ran a mass strategy search (the MLB Evolution Lab, 8,811
   strategies), zero survived.** The best one scored below the middle of pure
   noise. That is documented in
   [EVOLAB_PHASE2B_RESULTS.md](EVOLAB_PHASE2B_RESULTS.md) and
   [EVOLUTION_LAB_ASSESSMENT.md](EVOLUTION_LAB_ASSESSMENT.md). The machinery
   that produced that honest answer is what we reuse for NFL and tennis.
2. **Testing thousands of strategies a day is easy; proving one of them works
   is not.** More strategies tried means a higher bar for any one to count,
   or we would be selling luck. The plan below keeps the bar where the
   product's credibility needs it, and still runs the volume you asked for.

## 1. What to buy (one month, $190)

| Buy | Cost | Click | What it gives us |
|---|---|---|---|
| **Goalserve Tennis API**, one month | **$150** | [Request the free 30-day trial](https://www.goalserve.com/en/contact-us) then [pricing](https://www.goalserve.com/en/sport-data-feeds/tennis-api/prices) | Results **and odds since 2010** from 20+ books, pre-match and in-play, so tennis can be backtested; live point-by-point scores every ~5 seconds with a serving flag; in-play odds. Sources: [coverage](https://www.goalserve.com/en/sport-data-feeds/tennis-api/coverage), [description](https://www.goalserve.com/en/sport-data-feeds/tennis-api/description/14), [live sample](https://www.goalserve.com/en/sport-data-feeds/tennis-api/sample/34), [player sample](https://www.goalserve.com/en/sport-data-feeds/tennis-api/sample/72), [docs](https://documentation.goalserve.com/). |
| **api-tennis.com Starter** | **$40** | [Register](https://api-tennis.com/register) · [docs](https://api-tennis.com/documentation) · [terms](https://api-tennis.com/terms-of-use) | Player surface records (hard, clay, grass won/lost), head-to-head, rankings, live scores and in-play odds. Historical depth is not documented, so it is our day-to-day enrichment feed, not the backtest source. 14-day trial. |

Two things to type into the Goalserve contact form when you request the
trial, so we have them in writing before the month starts:

- "We build a paid betting-analysis subscription. Does the tennis feed
  licence cover use inside a consumer analysis product?" (Their public pages
  say "betting and more"; the licence sentence itself is not published.)
- "Are match and player IDs stable across seasons, and what is the request
  limit per day on the $150 tier?"

And for api-tennis.com, by email after registering: "Is Davis Cup covered
on Starter, and is commercial use inside a paid product allowed?" Their terms
say accounts are individual and that what you do with the data is your
responsibility; they do not say yes or no.

Not buying, but relevant:

- [The Odds API historical odds](https://the-odds-api.com/historical-odds-data/):
  NFL and tennis odds snapshots every 5 minutes since 2020, 10 credits per
  snapshot per market per region. This is the only way to backtest NFL
  **line movement**; see section 6 for the cost and the decision.
- [nflverse](https://github.com/nflverse/nflverse-data/releases) (free, CC BY
  4.0): schedules with closing moneylines, spreads and totals back to 2006,
  injuries, team stats. Already wired in. [nflreadr](https://nflreadr.nflverse.com/).
- [tennis-data.co.uk](http://www.tennis-data.co.uk/): results with odds since
  2000, but [commercial use is barred](https://results.tennisdata.com/en/terms-and-conditions)
  without a separate licence. Not used.

## 2. The "$1,000 agent", exactly

What we can say, and it will be true: **"Every strategy we test starts with
$1,000 of paper money. If it goes broke, we say so. We publish the losers."**
What we will never say: that any of them has an edge, until the full gate
says so (section 4).

How it works:

- **Start:** $1,000 paper. **Stake:** a fixed fraction of the starting
  bankroll on every bet. The fraction is a display setting, not a finding:
  going broke at 1% per bet and at 0.1% per bet are different stories for
  the same strategy, so the page shows the same strategy at **three stake
  fractions (0.5%, 1%, 2%)** with that sentence printed beside it.
- **Broke:** bankroll at or below $0 at any settlement. The agent stops, is
  marked BROKE, and stays in every later number at minus 100%. Dropping
  broke agents from the 60- and 90-day figures would make the survivors look
  better than the strategy is, which is the one thing this page must not do.
- **Random start points:** we take real calendar dates at random, and play the
  strategy's actual bets **forward from that date in the order they
  happened**. No shuffling, no resampling. (Last time's lab used fixed
  windows, not random starts; this is new and simpler than what people
  usually do.)
- **Windows:** return after 7, 30, 60 and 90 days from each start. **One
  headline window per sport, declared before the first run** (proposed: 30
  days for MLB and tennis, 60 days for NFL because it plays once a week).
  The other three are shown as full spreads, never as the best one.
- **What is shown:** the median return, the 10th to 90th percentile band, the
  share of starts that went broke, and **how many non-overlapping windows
  the data actually contains**. A 90-day band from two seasons of data is
  about eight real windows; the page prints that number next to every band
  and hides any window with fewer than five.
- **What it is for:** a plain picture of what betting the strategy would have
  felt like. It never decides whether a strategy is promoted. That is the
  gate's job, and this number cannot feed it.

## 3. Thousands of strategies a day: how, and what the bar does

- **Where they come from.** Not written by hand. A strategy is a combination
  of: which market (moneyline, spread, total), which signals (up to three,
  each with a threshold and a direction that is frozen in advance), how the
  signals combine, and when to enter. The lab enumerates every combination in
  a declared space. The MLB run enumerated 8,811 this way. NFL and tennis
  spaces will be larger because there are more features.
- **How they are registered.** One pre-registration per sweep, filed before
  anything is evaluated, with the whole space described and hashed so the
  same idea cannot be re-run under a new name. Every strategy in the sweep
  is published with its result, winners and losers.
- **How luck is priced.** The real test is the **placebo ceiling**: we run
  the same sweep on scrambled data many times and record the best score pure
  noise produces. A real strategy has to beat the 95th percentile of noise
  on a majority of the noise generators, then survive the overfitting check
  (which last time said our best MLB strategy was anti-predictive), then
  survive forward testing with decisions frozen before results.
- **Why the bar rises.** Under pure noise, about 1 in 100 strategies looks
  "significant" at the usual cutoff, so a 1,000-strategy sweep produces about
  10 false candidates by chance, and any false-discovery filter set at 10%
  will still let roughly 1 in 10 sweeps emit a false survivor. So: **the
  number of sweeps for the month is declared up front and a fixed error
  budget is spread across them**, and any survivor goes to forward
  replication before it is named anywhere. Searching harder does not lower
  the bar; it raises it.
- **What to expect.** The honest, pre-stated expectation for the first
  1,000-strategy sweep in each sport is **zero validated survivors**. That is
  what the MLB lab found, and it is what most published research on
  systematic betting finds. A survivor would be the surprise, and we would
  treat it as one (verify twice before believing it).

## 4. The gate that decides anything

A strategy becomes a product pick only after: pre-registration, the placebo
ceiling, the overfitting check, at least 60 forward days and 300 forward
selections with decisions frozen before results, and the language rules. That
is longer than one month. **Nothing bought or built this week can produce a
validated edge by 2026-10-15.** It can produce Phase 0 verdicts for NFL and
tennis, real forward ledgers, published sweep results, and the $1,000 pages.

## 5. Tennis: the analysis, the courts, and live versus pre-match

**What the data lets us do.** Goalserve gives results with odds since 2010,
which is roughly 7,000 tour matches a year: enough to power a real backtest.
api-tennis.com gives the day-to-day player records.

**Court surfaces and who is good where.** Surface (hard, clay, grass, indoor)
is known before the match, so it is safe to use. We build, from timestamped
history: each player's win rate and set rate by surface; serve-hold and
break rates by surface (serve statistics if the feed carries them, otherwise
inferred from game scores); head-to-head by surface; how a player's surface
form compares to their overall form (the clay specialist, the grass
specialist). **Court speed** has no field in either feed; we use tournament
as a proxy and label it an assumption.

**Features we will not use in a backtest**, because the historical record
shows today's value, not the value known at the time: ranking movement,
minutes played in prior rounds (fatigue), and anything backfilled. They are
forward-only until each field carries a first-seen timestamp.

**Retirements and walkovers.** Books differ on whether a retirement voids a
bet. The settlement rule is declared before the first bet is graded
(proposed: follow the majority of our board's books; a retirement before one
full set is a void). No tennis result is graded until the feed's match-status
field is confirmed in the first data audit.

**Pre-match strategy families** (each a sweep, each pre-registered): surface
specialist versus generalist mispricing; favourite with a poor surface record
priced like their overall record; head-to-head dominance; early-round
favourite overpricing at 250 and 500 events; ranking gap versus price on
each surface.

**Live strategy families** (Goalserve point-by-point with a serving flag and
in-play odds, so **tennis live does not spend our odds credits**): favourite
loses the first set; break of serve against the favourite; favourite down a
break in the deciding set; momentum runs (three games in a row). Two rules
protect these from fooling us: we only enter at a price observed after the
trigger plus a declared delay, because books suspend markets at exactly these
moments and a price from the next tick may never have been offered; and the
matches we watch live are chosen by a rule that cannot see the outcome (a
declared tournament tier), so the sample is not selected by convenience.

## 6. NFL: what is possible this month, and one purchase decision

**Forward testing starts this week** on the NFL card rule already built and
pre-registered (NFL_CARD_V1) plus a small set of live rules that need no game
clock (score change, lead change, favourite behind around halftime by
elapsed time). The NFL scores feed has no clock, so clock-based live rules
wait for a clocked source.

**Backtesting NFL properly needs a purchase you have not made.** nflverse
carries closing lines only. That means two things: no line-movement families
(the family that did best in MLB), and no test of whether a strategy survives
a slightly worse price, which the gate requires. And with about 5,400 games
since 2006, detecting a 3-point edge at the gate's cutoff would need roughly
18,000 bets; we cannot get there, so an NFL backtest "null" this month would
not mean anything. **Decision for you:** buy NFL historical odds from
[The Odds API](https://the-odds-api.com/historical-odds-data/)? Estimate:
5 snapshots a week, 3 markets, 1 region, 10 credits each is about 150
credits a week, about 2,700 a season, about 8,000 for three seasons, if one
historical call returns every game at that time as the live call does (an
assumption we verify with a single 30-credit call first). That is inside our
monthly credits. Until then, NFL is forward-tested and live-tested only,
and its pages say so.

## 7. MLB

Nothing in the MLB product changes. The lab runs on the MLB stores we
already have (pre-game and, from this week, live state and in-play odds),
using the same machinery that produced the MLB null. MLB gets the $1,000
pages as an addition, not a reordering of the card.

## 8. Live versus pre-match, as a strategy

- **Pre-match search is cheap:** it runs on stored prices and costs no
  credits, so it carries the volume (thousands of strategies a sweep, one or
  two sweeps a week per sport).
- **Live is rationed:** MLB and NFL in-play prices come from The Odds API
  under the 300-credit-a-day cap and are fetched only when a game's state
  changes; tennis in-play prices come from Goalserve. We measure MLB's own
  in-play draw for a week before assigning any of the cap to NFL, and tennis
  needs none of it.
- **The money question.** Live markets are where a single fact (a starter
  pulled, a break of serve) moves the price fastest, which is where an
  information edge could live; pre-match is where the market has had hours
  to settle, which is where the MLB evidence says the market is right. That
  is why the live rules are pre-registered as research candidates with a
  real forward test, and why the pre-match sweeps are expected to come back
  null. We follow the evidence, not the preference.

## 9. The week, Pacific time

| Day | What happens |
|---|---|
| Tue 9/15 | You request the Goalserve trial and register api-tennis.com. I finish the NFL card publish path, the API and web surfaces, and the live runner already in progress. |
| Wed 9/16 | Tennis results feed wired to Goalserve (results, odds, status field). Historical tennis loader with outcome isolation on. |
| Thu 9/17 | Phase 0 data audits for tennis and NFL (fields, timestamps, gaps only; no outcome distributions). NFL Thursday game: first NFL card published and locked. |
| Fri 9/18 | Tennis feature accumulators (surface, serve, H2H); the $1,000 page engine (real forward paths, broke agents carried); the sweep budget for the month declared. |
| Sat 9/19 | Tennis sweep pre-registered, enumerated and run against the placebo ceiling (CPU only). NFL: forward-only; the purchase decision in section 6 is yours. |
| Sun 9/20 | Forward paper accounts open at $1,000 for every registered system in all three sports; NFL Sunday card and live window run. |
| Mon 9/21 | First settlements. Sweep results published, losers included. $1,000 pages go up, backtest-labelled, language-checked, with the no-guarantee line. Week report. |

## 10. Credits

About 100,000 a month. Live capture envelope 900 a day; in-play cap 300 a
day shared by MLB and NFL; tennis live costs no credits (Goalserve). The
pre-match lab costs no credits. The only new credit spend on the table is the
NFL historical purchase in section 6 (about 8,000 for three seasons).

## 11. What you will and will not see by 2026-10-15

**Will see:** Phase 0 verdicts for tennis and NFL; a tennis sweep judged
against its own placebo ceiling (most likely null); forward ledgers for NFL,
tennis and MLB with decisions frozen before results; the $1,000 pages for
every registered system, busts included; the live research ledger filling
in; a clear record of what was tried and what lost.

**Will not see:** a validated edge in any sport (the gate needs more than a
month); a 90-day forward return (only backtest windows, labelled as such);
NFL line-movement strategies (needs the purchase); clock-based NFL live rules;
tennis grading before the status field is confirmed.

## 12. Decisions I need from you

1. Buy Goalserve (one month, $150, trial first) and api-tennis.com Starter
   ($40): yes or no.
2. Buy NFL historical odds for backtesting (about 8,000 credits for three
   seasons, verified with one 30-credit call first): yes or no.
3. Headline windows: 30 days for MLB and tennis, 60 days for NFL: agree or
   change.
4. Stake fractions shown on the $1,000 pages: 0.5%, 1%, 2%: agree or change.

Technical appendix: [STRATEGY_LAB_PLAN_OF_RECORD.md](STRATEGY_LAB_PLAN_OF_RECORD.md)
(file-level reuse map and module plan) and the statistical review that
shaped sections 2 to 4: [STRATEGY_LAB_REFUTATION_2026-09-15.md](STRATEGY_LAB_REFUTATION_2026-09-15.md).
