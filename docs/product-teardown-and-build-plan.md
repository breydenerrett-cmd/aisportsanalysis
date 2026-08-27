# The Brief Engine — Product Teardown & Build Plan

*Imported from a Cowork session (Aug 27, 2026) that produced a sample MLB game
brief (Dodgers–Braves) and then audited its own work. This doc is that audit:
what held up, what would break under a paying customer, and the product
underneath it.*

## The one thing to take from this

**What was built was a well-written argument, not a model.** Every number in
the sample brief was real, but the conclusions came from reasoning over
public stats, not from a projection engine producing a fair price to compare
against the market. That distinction is the entire business. A brief without
a model behind it is a blog post — and the blog-post market is saturated,
unregulated, and full of people lying about their records. A model without a
brief is OddsJam, and they have a nine-figure head start on data.

**The product is the join.** Model-derived edges, explained in language a
normal bettor can act on, with the record kept honestly and publicly. Nobody
is doing both halves well.

## What's Working (keep these)

- **The assembly is the value.** The sample card pulled odds, weather,
  injuries, bullpen availability, pitcher splits, park factors, and
  competing model outputs into one screen. A bettor doing that by hand opens
  eleven tabs and takes forty minutes. Compression of scattered inputs into
  one decision surface is a real, repeatable product — and it scales
  cleanly to fifteen games a day.
- **Priced gates, not just picks.** "Only at 6.5." "+100 or better only."
  "At 7.5 it's a pass." Almost no pick service does this, because a gate can
  be checked against them later. It converts a recommendation into a
  conditional rule, which is how disciplined bettors actually think, and it
  protects the customer from betting a pick into a bad number.
- **The falsifiability section.** "What Would Make This Wrong" is the
  single most trust-building block and the cheapest to produce. It signals
  modeled uncertainty rather than sold confidence — a positioning moat in a
  category defined by touts hiding their losses.
- **The structural thesis.** A single reason ("elite front six innings,
  ugly back three") that both recommended bets flow from. Six disconnected
  picks read as a slot machine; one thesis expressed two ways reads as
  analysis.
- **Staked, ranked output.** Ordering by conviction with unit sizes attached
  gives the user a bankroll decision, not a list.

## What's Broken (ranked by severity)

### Blockers

1. **There is no model.** The sample said "I like the under," never "my
   simulation projects 7.9 total runs against a market of 6.5, a 4.1% edge."
   Without that: no edge to sell, no way to size a bet correctly, no way to
   know if a call was right for the right reason, no way to run this on
   fifteen games without a human writing each one.
   - **Fix:** a plate-appearance-level Monte Carlo simulator. Project each
     lineup slot against the opposing starter and projected bullpen,
     simulate 25,000 games, read fair prices for moneyline, run line,
     total, first-five, team totals, and NRFI straight off the
     distribution. Well-trodden design — the hard part is the inputs, not
     the math.

2. **The data foundation is scraped and stale.** Half the sources returned
   the prior day's game; ESPN blocked outright. Recoverable by hand for one
   card, fatal for a product — wrong prices shipped to paying customers, and
   scraped sites block you the moment there's volume.
   - **Fix:** license odds. The Odds API (~$30–$249/mo, mainly soft books,
     no Pinnacle). SportsGameOdds ($99–$499, includes Pinnacle, closing
     odds, WebSocket push — closing odds matter for CLV). OpticOdds
     (enterprise, sales-contact). Stats: free from MLB StatsAPI + Baseball
     Savant. Weather: free from the National Weather Service API.

3. **No closing-line tracking.** Nothing in the sample can be scored. CLV
   (closing line value) is the only honest measure of whether a betting
   product works — win-rate over a few hundred bets is mostly noise. A tool
   that can't prove CLV is indistinguishable from a tout.
   - **Fix:** log every recommendation with timestamp and exact price at
     issue. Auto-grade against the closing number. Publish the rolling CLV
     curve on the marketing site, unfiltered, including bad stretches. Costs
     one database table; is the entire trust story.

### Major

4. **Vocabulary assumed, not taught.** "Lean," "value," "play," "u," "F5,"
   "devig," "run line," "−130" — every unexplained term is a churn event.
   - **Fix:** glossary layer. Dotted underline on every term, hover/tap for
     a one-sentence plain definition, plus a persistent "Explain like I'm
     new" toggle that rewrites the whole brief in plain English. Nearly
     free with an LLM already in the stack, and a legitimate marketing hook.

5. **Correlated bets sized as if independent.** The F5-under and full-game
   over were called "two halves of one thesis" — true, and it means the risk
   is correlated but was sized as if it weren't. If the aces get shelled
   early, both lose together.
   - **Fix:** size from the simulation. With 25,000 simulated games,
     compute the joint outcome distribution directly and apply fractional
     Kelly to the portfolio rather than to each leg. Show total slate
     exposure and flag correlated recommendations.

6. **No line shopping, only line advice.** "Shop for 6.5, not 7" — without
   showing where. The most immediately monetizable feature in the document,
   left as homework.
   - **Fix:** a book-by-book price grid on every recommendation, best price
     highlighted, deep-linked to the bet slip where affiliate programs
     allow it.

7. **Wrong timing, no refresh.** Published sixteen hours before first pitch,
   then noted the lineups weren't out yet. A brief that expires before it's
   actionable is a demo, not a product.
   - **Fix:** two-pass delivery. An early "watch list" pass when lines open,
     then an automatic re-run at lineup lock (~3 hours out) that
     re-simulates with confirmed lineups, re-prices every gate, and pushes a
     diff of what changed.

8. **Single game, human-assembled.** The sample card took ~20 tool calls and
   ongoing human judgment. No version of this business hand-writes fifteen
   of those a day.
   - **Fix:** the narrative layer must generate *from* structured model
     output, not free research. The LLM's job is translation — turn the
     edge table, context object, and risk flags into prose. Grounded
     generation costs a few cents per brief, and every sentence traces back
     to a field, which lets you catch hallucinations mechanically.

### Polish

9. **Career-splits noise presented as signal.** Small-sample career stats
   (e.g. a pitcher's ERA over 2-5 career starts vs. one team) get flagged as
   noise in prose but still visually promoted to evidence by being in a stat
   box.
   - **Fix:** enforce a minimum-sample threshold in the data layer. Anything
     under it is suppressed or rendered greyed out with sample size
     attached. Let the system refuse to display noise rather than relying
     on prose to disclaim it.

10. **Team records didn't reconcile.** Different sources disagreed on
    win-loss record depending on whether they'd ingested the latest result.
    - **Fix:** single source of truth and a visible "data as of" timestamp
      on every figure.

## The Competitive Reality

A crowded, well-funded category. The incumbents own the data; they don't own
the explanation.

| Player | What they sell | Rough price | Their gap |
|---|---|---|---|
| OddsJam | Arb + EV screens across 100–150 books, alerts | ~$99 / $249 / $499/mo | Firehose of numbers, zero explanation, overwhelming to anyone but a grinder |
| ArbBets | Prediction-market scanning (Polymarket, Kalshi, Novig) | $59 / $149 / $299/mo | Same — screens, not analysis |
| Unabated / sharp tools | Devigged fair prices, market-maker anchoring | Mid-hundreds/yr | Assumes you already know what devigging is |
| Action Network et al. | Content, splits, "expert picks" | ~$8–$15/mo | Media business; picks are engagement bait, not modeled edge |
| Tout services | Picks, sold on a claimed record | $50–$500/mo | Largely unverifiable, reputationally toxic |
| **This product** | Modeled edge, explained plainly, publicly graded | $29–$99/mo | No data moat, no record, no distribution yet — all fixable, record takes a season |

**The wedge:** a large middle between the bettor who can read a devig table
and the bettor who buys picks off Twitter. Bets 3–8x/week, $500–$5,000 in
play, smart, finds OddsJam unusable. Nobody serves them well, because
serving them requires writing — the thing a numbers shop is culturally worst
at and an LLM-native product is best at.

## What to Actually Build — Five Layers

1. **Data.** Licensed multi-book odds with push updates and closing lines.
   Official stats, Statcast, projected/confirmed lineups, bullpen usage from
   the last three days, park factors, weather.
   *Tools: SportsGameOdds or The Odds API · MLB StatsAPI · Baseball Savant ·
   api.weather.gov*

2. **Model.** Monte Carlo game simulator, 25k runs/game. Full distribution
   output: win probability, run-total distribution, first-five, team
   totals, inning-level events. Rest-of-season pitcher/hitter projections as
   inputs, with a bullpen fatigue decay term.
   *Tools: Python, numpy, nightly batch + intraday re-run at lineup lock*

3. **Edge.** Devig every market (multiplicative/power devig, not additive)
   for a no-vig consensus, compare model fair price to best available
   price, rank by expected value, size with fractional Kelly (capped ~0.25)
   across the correlated portfolio, apply minimum-sample and staleness
   filters.

4. **Narrative.** Turn the edge table + context object into the brief —
   thesis, ranked card with priced gates, falsifiability section, glossary.
   Strictly grounded: every claim maps to a field, nothing invented.
   *Tools: LLM, structured input only · ~$0.05–$0.30/brief*

5. **Ledger.** Log every recommendation at issue price, auto-grade against
   closing line and result, publish the rolling CLV curve. Let users track
   their own bets against it. This is the retention layer and the marketing
   site at once.
   *Tools: Postgres · public, unfiltered, including losing months*

**Build order:** layers 1, 2, and 5 first, with no product surface at all.
Run silently for four to six weeks and check whether the model beats the
closing line. If it doesn't, there is no picks business — and that's
knowable for a few hundred dollars instead of after building a subscription
app.

## Packaging & Price (proposed)

| Tier | Price | Includes |
|---|---|---|
| Free | $0 | One game brief/day, posted after lineup lock, no edge numbers shown, public CLV ledger |
| **Core** | **$29/mo** | Every game, full slate; both delivery passes + change alerts; line-shopping grid; glossary + plain-English mode |
| Pro | $79/mo | Raw model numbers and fair prices; edge screen across all markets; personal bet tracking vs. CLV; Kelly sizing on your bankroll |
| Day Pass | $9/day | Full slate, 24 hours, for big-event traffic; credits toward a subscription |

- Per-game micropayments convert badly in betting — friction hits at the
  moment of decision. A day pass on a marquee slate works better and doubles
  as the paid-acquisition landing offer. Save true per-use pricing for a
  later API tier.
- Free tier: give away the whole brief on one game, not a crippled version
  of all of them. The writing is what sells this.

## Legal Ground to Cover (not legal advice)

- **"Picks" and "tools" are different businesses.** Selling picks makes you
  a tout service. No federal tout regulator exists — Nevada's 2018 attempt
  had the tout language stripped before passage — but that absence cuts
  both ways: the category has a deserved fraud reputation, and platforms,
  processors, and ad networks treat it accordingly. Framing as analytics
  with a published, auditable record is materially safer.
- **FTC exposure is real even where gaming regulators aren't.** Claimed win
  rates, "guaranteed" language, cherry-picked records — all deceptive
  advertising regardless of state gaming law. Publish the full record or
  none.
- **Affiliate revenue is state-by-state.** Deep-linking to sportsbooks with
  a referral cut is the category's most common real revenue line, and
  requires per-state compliance and licensing. Budget it as a legal
  project.
- **Scraping is not a foundation.** Violates terms, breaks under load.
  License the data — also what makes CLV numbers defensible.
- **Table stakes:** 21+ age gating, geo-restriction, responsible-gambling
  messaging and self-exclusion links on every surface, "not financial
  advice" positioning. Mobile app stores have gambling-adjacent review
  rules that have killed similar products at submission.
- Spend a few hundred dollars on a gaming attorney before taking a dollar —
  cheapest risk reduction available.

## Ninety-Day Plan

**Weeks 1–3 — Prove the model, ship nothing.** Wire the data layer, build
the simulator, run it daily against the full MLB slate. No UI, no site, no
customers. Log fair prices and grade against closing lines.
*Gate: does the model beat the close? If no, stop and rebuild the model, not
the product.*

**Weeks 4–6 — Automate the brief.** Wire the narrative layer to model
output. Regenerate the sample Dodgers–Braves card entirely from structured
data with no human research and compare to the hand-made one. Build the
glossary layer now — cheap now, expensive to retrofit.
*Ship: a daily email to twenty beta bettors, free.*

**Weeks 7–9 — Web surface + the ledger.** Slate view, brief pages,
line-shopping grid, public CLV curve. Two-pass delivery with lineup-lock
re-runs and change alerts. Auth and billing.
*Ship: Core tier live at $29. Target twenty-five paying users, not two
hundred.*

**Weeks 10–12 — Pro tier + second sport.** Expose model numbers, edge
screen, personal bet tracking, Kelly sizing. Start the NFL build
immediately — MLB ends in October and a one-sport product loses revenue for
half the year.
*Ship: Pro at $79. Decide on affiliate compliance work here, not earlier.*

## What to Watch (and when to quit)

| Metric | Target | Note |
|---|---|---|
| CLV | > +1.5% | Beat the closing line on recommended bets. Below zero over 500+ bets = no edge, no honest product. |
| Day-30 retention | > 55% | Betting tools churn brutally. Under 40% at M1 means the briefs aren't being read. |
| Brief open rate | > 45% | Leading indicator — stop opening, cancel within three weeks. |
| Cost per brief | < $0.30 | Generation is cheap; odds data is the real floor — budget $100–$500/mo before the first customer. |

**Kill criterion:** if after six weeks the model can't beat the closing
line, the picks business is dead — don't build it. But the
research-assembly product still works: sell the tool that gathers,
explains, and tracks, and let the user supply the opinion. That version has
no edge requirement, no tout exposure, and a much easier trust story.
Decide which business this is before week seven, not after.

---
*Sources referenced in the original session: ArbBets on OddsJam pricing,
OddsPapi odds-API comparison, Sports Handle on tout regulation, The Odds
API FAQ, OpticOdds pricing. Competitive pricing and API figures were pulled
in August 2026 and move often — reconfirm before building a budget on them.*
