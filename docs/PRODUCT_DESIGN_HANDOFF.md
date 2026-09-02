> **SUPERSEDED (2026-09-02)** — see design/linehound-v2/LINEHOUND_V2_IMPLEMENTATION_HANDOFF.md §5

# PRODUCT DESIGN HANDOFF

**A customer-facing product, UX and brand specification for a sports-betting
intelligence platform.**

Prepared 2026-08-31 as a standalone document. An implementing AI should be able
to build the customer product from this file plus the engineering repository
(`breydenerrett-cmd/aisportsanalysis`).

---

## How to read this document

### Capability labels — MANDATORY, applied to every feature

| Label | Meaning |
|---|---|
| **EXISTS TODAY** | The current engine and data genuinely support this. Verified in the repo. |
| **ENGINEERING REQUIRED** | Reasonable application functionality that does not exist yet. Buildable on current data. |
| **FUTURE / RESEARCH DEPENDENT** | Depends on props data, a validated Ranker, multi-sport ingestion, or research that has not concluded. |

**Never mistake product vision for existing backend capability.** Roughly 85% of
this document is ENGINEERING REQUIRED, because there is currently no application
— only a static HTML generator. That is expected and stated openly.

### Priority labels — applied to every major page/feature

Timing: **MVP** · **V1** · **LATER**
Strategic role: **HIGH WTP DRIVER** · **TABLE STAKES** · **DIFFERENTIATOR** · **MOAT CANDIDATE** · **NICE TO HAVE**

### Evidence labels

**VERIFIED** — I saw it myself in a browser or measured it in the repo, this session.
**INFERRED** — reasoned from evidence, not directly observed.
**HYPOTHESIS** — a design bet that should be tested.

Where competitor research came from a text-only research pass rather than my own
browser session, it is marked `[desk]` and the underlying file is named.

### Supporting research files

```
research/CURRENT_PRODUCT_CRITIQUE.md              my visual critique of demo_latest.html
research/BREY_DIRECTIVE_PROGRESSIVE_DISCLOSURE.md binding product direction
research/desk/PRICING.md                          competitor pricing + packaging
research/desk/APP_STORE.md                        store listings, ratings, complaints
research/desk/CUSTOMER_PAIN.md                    bettor workflow, habit, churn
research/desk/FEATURES_TRUST.md                   feature matrix + trust audit
research/desk/NAMES.md                            36 name candidates + collisions
reference-repo/                                   read-only clone (no git remote)
```

---

# Product vision

A **sports betting intelligence platform**: the layer a bettor checks *before*
placing a wager, which consolidates and interprets what they currently assemble
by hand from sportsbooks, odds sites, FanGraphs, Baseball Savant, ESPN, MLB.com,
X, beat reporters, Reddit, weather, injury feeds, lineup pages and bet trackers.

The product does not need a proven predictive edge to be worth paying for. Its
value is:

**better information · faster research · better context · skeptical analysis · market intelligence**

A demonstrated predictive edge, if it ever arrives, becomes a premium feature —
not the foundation. This ordering is deliberate and is the core structural
difference from every competitor examined.

## The one-sentence test

> *"I would be stupid to place this wager without checking this first."*

Every design decision in this document is answerable to that sentence.

## What this is not

Not an "AI LOCKS 🔥 87% WIN RATE" product. Not a pick seller. Not a tout.
Not a chatbot with a personality. Not a database dump.

---

# Customer promise

**Primary:** *Everything that matters before you bet.*

The promise is completeness and honesty, not accuracy. We do not promise the
customer will win. We promise they will not bet with half the story, and that
when the evidence is weak we will say so — including when that means telling
them there is nothing here tonight.

**The three things the product always tells you about a bet:**

1. **What supports it** — the real reasons, in plain English.
2. **What argues against it** — always shown, never suppressed.
3. **Whether you can get it cheaper somewhere else** — the only claim we can make
   that requires no prediction at all and is verifiable on the spot.

---

# Target personas

Six personas, in descending order of how much of the MVP they should drive.

### 1. The Daily Bettor — **primary MVP persona**
Researches most slates. Bets 4–7 days a week. Already has 3–5 tools open.
**Needs immediately:** tonight's slate, what changed since this morning, best
price on the bet they were already going to make.
**Why primary:** this is the persona with a daily habit, and daily habit is what
makes subscription software survive. Retention is designed around this person.

### 2. The Casual Serious Bettor — **primary conversion persona**
Bets a few times a week, usually on games they're watching anyway. Knows the
sport well; knows the math poorly.
**Needs immediately:** *"Is this bet stupid?"* in under 30 seconds, in plain
English. This person is the entire reason **Quick View** is the default and
**Bet Check** is the hero. They will churn instantly from a terminal UI.
**Why they matter:** largest addressable segment and the one competitors serve
worst — every tool examined assumes fluency the casual bettor does not have.

### 3. The Prop Bettor
Needs player-level research: usage, lineup slot, platoon, pitcher matchup.
Books price props less rigorously than sides/totals, which is why this persona
believes edges exist there `[desk: CUSTOMER_PAIN.md]`.
**Needs immediately:** confirmed lineup, role, matchup context, price shop.
**Status:** props are **FUTURE / RESEARCH DEPENDENT** — the current engine has
no prop data. Do not design the MVP around this persona.

### 4. The Data Nerd
Wants FIP, xwOBA, pitch mix, batted-ball profile, confidence intervals, and the
methodology. **Needs immediately:** the Advanced View, and the ability to make
it their default. Small segment, disproportionate word-of-mouth influence.

### 5. The Sharp-Leaning Bettor
Cares about closing line value, book disagreement, line shopping, market
movement. CLV is genuine working vocabulary for this person, not jargon
`[desk: CUSTOMER_PAIN.md]`. **Needs immediately:** the odds board, dispersion
across books, and a CLV record. Will judge the product on price accuracy and
refresh latency, and will find any error.

### 6. The Content Creator
Needs fast, quotable explanations and storylines for a segment or a thread.
**Needs immediately:** the "what matters tonight" narrative and shareable
per-game cards. Cheap to serve, high marketing leverage.

### Design consequence
Personas 1 and 2 define the MVP. Persona 4 is served by the Advanced toggle
rather than a separate product. Persona 3 is deferred entirely. Persona 5 is
served by the Odds board. Persona 6 needs only a share affordance.

---

# Competitor visual research

Nine products inspected **in a live browser this session** (VERIFIED). Twelve
covered by parallel text research `[desk]`. Every claim below is tagged.

Each Tier 1 profile records the five first-value fields, because they drive our
onboarding and free tier.

---

## PlayerProps.ai — VERIFIED (browser, 2026-08-31)

**URL:** https://playerprops.ai/ · pages inspected: home, `/pricing`,
`/odds-comparison`, `/public-betting-splits`

### What I actually saw

- **Palette:** near-black indigo ground with a magenta→violet gradient. The
  single most saturated example of the "AI casino tech" convention in the set.
- **Type:** heavy condensed display caps for headlines
  ("STOP GUESSING. START WINNING."), rounded sans for body.
- **Hero:** phone mockup showing a prop card — `Pitcher Strikeouts 3.5 Over
  -171`, a green **`+46% EDGE`** pill, and a metrics row reading
  `IMPLIED 63.10% · PROJECTION 5.10 · ACCURACY 66.7% (39)`, with split rates
  `L5 60% · L10 70% · S2H 76% · H2H 0%`.
- **Trust chips:** `102,900+ Members` · `🏆 #1 Ranked` · `⭐ 4.8 App Store` ·
  `🏆 2025 MOST ACCURATE A.I. PREDICTION APP`. No audit link anywhere.
- **Left-rail IA (pricing page):** Prop Predictor · Moneyline Predictor · Spread
  Predictor · Total Predictor · NRFI Predictor · First Basket Predictor · MLB F5
  Predictor · Team Trends · Public Betting Splits · Props Comparison · Odds
  Comparison.
- **Pricing:** Week Pass $20 · Monthly · **6-Month VIP $295** ("pay 5, get 1
  free", shown as **$1.62 per day**) · Annual "Save 30%". `MOST POPULAR` and
  `BEST VALUE` badges. "Cancel anytime · No questions asked."
- **Responsible gambling:** partnership with Birches Health, plus a "100% for
  entertainment purposes only" disclaimer. Corporate entity: Better Bets Inc.

### First-value profile

| Field | Finding |
|---|---|
| **First 30 seconds** | "AI predicts player props and tells me which ones have an edge." Unambiguous. |
| **First 2 minutes** | **Nothing.** Every product route renders empty skeletons logged out. |
| **Free value** | Effectively zero. A locked card reads *"Log in to see today's most favorited pick."* |
| **Paywall moment** | Immediate and total — a **login wall**, before any value is shown. |
| **Core aha** | Intended: seeing a big green `+46% EDGE` on a specific prop. |

### Strengths
- The clearest single-sentence value proposition in the category.
- **`Ask AI`** is described in their own pricing copy as *"Run any bet past our
  AI and get an instant, unbiased read backed by the numbers before you lock it
  in. **Our single most powerful feature.**"* — an explicit, vendor-stated
  validation that **Bet Check is the highest-value feature in this category.**
- **Community as retention.** In-app chat is called *"the feature long-time
  members prize most"* — deliberately positioned as a Discord replacement.
- The Week Pass is a smart low-commitment trial that isn't a card-trap free trial.

### Weaknesses
- **A hard login wall with zero free value.** For a product whose whole pitch is
  "see the edge," showing nothing is a severe funnel leak.
- **`ACCURACY 66.7% (39)`.** They disclose the sample — 39 — and still present it
  as a headline accuracy figure. n=39 supports essentially no conclusion. The
  disclosure is honest; the framing is not.
- **The positioning contradicts itself.** Mid-page: *"WE DON'T GIVE YOU PICKS.
  WE MAKE YOU SHARPER."* Top of page: *"2025 MOST ACCURATE A.I. PREDICTION APP"*
  and a `+46% EDGE` pill. They market education and ship prediction.
- IA is organised **by market type**, not by game or by workflow. There is no
  "today," no game page, no bet history. The user must already know which
  predictor they want.

### Useful patterns to adopt
- The Week Pass as a paid, no-trap trial.
- Explicit per-day price framing ($1.62/day) to shrink a $295 commitment.
- Naming the single strongest feature explicitly in pricing copy.

### Do not copy
- The login wall with no free value.
- Any headline accuracy percentage over a sub-100 sample.
- Superlative badges ("#1 Ranked", "Most Accurate") with nothing behind them.
- The purple/magenta gradient — it is the most crowded look in the category.

### The strategic finding
**PlayerProps.ai already claims our intended positioning in copy.** "We don't
give you picks, we make you sharper" is on their homepage today. Their pain list
— *"Trusting social media cappers who never show their record"*, *"Betting
without knowing line movement or sharp action"*, *"No way to quickly compare
projections vs posted lines"*, *"Losing streaks with no idea what went wrong"* —
is nearly verbatim our pitch.

**Consequence:** "we're not a picks bot" is **not** available as a
differentiator. It is table stakes marketing language. Our differentiation must
be *structural* — what the product actually shows — not tonal.

---

## Rithmm — VERIFIED (browser, 2026-08-31)

**URL:** https://rithmm.com/ · pages inspected: home, `/scout`

**This is the most important competitor in the set.** Read this section before
designing Bet Check.

### What I actually saw

- **Palette:** near-black with a single **burnt orange** accent (#E8622A-ish).
  Notably *not* purple. The most disciplined visual identity of any competitor
  examined — one accent, used sparingly.
- **Type:** a wide squarish grotesque for display ("Never sweat another pick
  alone."), monospace for eyebrow labels (`/ AI SPORTS PREDICTIONS FOR EVERY GAME`,
  `WHAT YOU GET`). The mono-eyebrow + big-sans-headline pairing is genuinely
  premium and worth learning from.
- **Nav:** THE EDGE · WHAT YOU GET · SCOUT · MODELS · PRICING.
- **Scout** is an AI chat product: *"Your AI betting buddy. Ask Scout about any
  game, player or bet. Get the pick. See the edge. Understand why."*

### Scout's structured answer format — verbatim

> **Anatomy of a Scout answer. Every answer has four parts.**
> **01 The pick** — "A clear position. No hedging, no word salad."
> **02 The numbers** — "Model win probability and the edge vs. the book's price."
> **03 The why** — "The factors actually driving the pick, in plain language."
> **04 The next move** — "Scout keeps digging — props, alt lines, the other side."

### Scout's five suggested questions — verbatim, and #2 is Bet Check

> **02 "What do you think about this bet?"** — *"Already have a pick? Run it past
> Scout before you lock it. Scout agrees, disagrees, or **points you to the
> better version of the same bet**."*

That is our Bet Check concept, shipped, including price improvement.

### Scout's voice guide — verbatim

> **SCOUT NEVER SAYS:** "Hammer this lock." · "Free money." · "The model
> guarantees…" · "Based on multidimensional predictive analysis…"
> **SCOUT SAYS:** "I like Philly here." · "There's an edge here." · "Here's what
> I'm seeing." · "I'd stay away."

Note the fourth "never" — they explicitly ban **jargon**, not just hype.

### They already own "No Play" as a virtue — verbatim

> **THE HONEST AI — Sometimes the best bet is no bet.** *"Touts need you to bet
> every game. Scout doesn't. When the value isn't there, Scout tells you —
> that's the difference between a pick-seller and a betting buddy."*

### They already state progressive disclosure as philosophy — verbatim

> **"Do I need to understand the models?"** — *"No. That's the point. You ask a
> question. Scout does the modeling. If you want to go deeper into win
> probability, edge or line comparison, Scout will take you there — but you never
> have to."*

> **"Does Scout guarantee winners?"** — *"No — and anyone who does is selling you
> something."*

### Strengths
- The most sophisticated positioning in the category, by a wide margin.
- An explicit, published voice guide — rare and effective.
- Honest-by-design marketing that does not feel defensive.
- Licence numbers in the footer (NJ 0094686, IN SWR000591, MI 008230, AZ EW2453)
  — real regulatory legitimacy signalling.
- 7-day free trial, "NO EXPERTISE REQUIRED."

### Weaknesses — and this is where the opening is
- **Answer part 01 is "The pick."** For all the anti-tout framing, the structure
  still leads with a position the model hands you. The honesty is *tonal*; the
  product is still a prediction engine.
- **"Edge" is defined as "Rithmm's projected win probability vs. the book's
  price."** That is a predictive claim, and its accuracy is unaudited — no
  independent track record exists `[desk: FEATURES_TRUST.md]`. They ban the
  phrase "the model guarantees" while the entire product rests on the model
  being right.
- **Chat is unauditable and ephemeral.** A conversation cannot be diffed,
  compared across nights, or held to account. You cannot ask a chat log "what
  did you tell me last Tuesday and were you right?"
- Progressive disclosure is delivered *conversationally* ("Scout will take you
  there") rather than *structurally*. The user cannot see the shape of what is
  being withheld.

### Useful patterns to adopt
- **A published voice guide with explicit NEVER SAYS.** Adopt this wholesale.
- **The four-part fixed answer skeleton.** Structure beats free-form prose for
  trust, because a fixed skeleton makes an omission visible.
- The mono-eyebrow / large-sans-headline typographic pairing.
- One restrained accent colour instead of a gradient.
- Licence numbers and responsible-gambling links in the footer.

### Do not copy
- Leading with "the pick."
- Defining "edge" as an unaudited model's probability minus the book's price and
  presenting it as a number.
- Chat as the *primary* interface for analysis.

### The strategic finding
Honesty, skepticism, "sometimes no bet", and progressive disclosure are **all
already claimed** by Rithmm in marketing copy. Our differentiation cannot be
*"we are honest."*

It has to be: **our honest claim is verifiable and theirs is not.**
Price improvement is checkable against the books in ten seconds. "The model
projects 58%" is not checkable at all. That asymmetry — and a structured,
persistent, inspectable record instead of a chat log — is the actual moat.

---

## OddsJam — VERIFIED (browser, 2026-08-31)

**URL:** https://oddsjam.com/

### What I actually saw
- **Palette:** very dark navy/near-black, **electric blue** primary, money-green
  for profit figures.
- **Headline:** "**Forget losing. Win either way.**" Sub: *"Every sportsbook
  prices games differently. Bet both sides at the right price and you'll profit
  no matter the outcome."* — pure arbitrage framing.
- **Hero visual:** a **profit calendar heatmap** attributed to
  `@The_Arbitron · Verified user · Live Arbitrage Tool · July 2026`, with a
  `NET PROFIT +$32,185` badge and per-day cells ($3k, $2.4k, $1.6k…).
- **Nav:** Tools · Pricing · Resources — a thin marketing nav over a deep tool.
- **CTA:** "Start a free trial" / "See how much you can make". "7 days free.
  Cancel anytime."

### First-value profile
| Field | Finding |
|---|---|
| **First 30 seconds** | "This finds arbitrage so I profit regardless of outcome." Very clear. |
| **First 2 minutes** | Marketing only at the top level; tools sit behind signup. |
| **Free value** | Limited — some public odds pages exist; the scanners are gated. |
| **Paywall moment** | Free trial requiring a card, then a steep price step. |
| **Core aha** | Seeing a live arb with a guaranteed return, or the profit calendar. |

### Strengths
- The clearest *mechanism* explanation in the category: it says exactly how you
  make money, and that mechanism does not require prediction.
- The profit calendar is potent social proof — concrete, dated, granular.
- Arbitrage and price improvement are honest, verifiable claims.

### Weaknesses
- "Forget losing" is close to a guarantee, and arbitrage in practice gets you
  limited or restricted by books — a risk not shown on the homepage.
- Profit screenshots from a named power user set an expectation most subscribers
  will not meet.
- **Billing complaints are the most severe in the category**, including a
  reported surprise €630 post-trial charge `[desk: APP_STORE.md]`.
- Their own educational content treats a line move (-110 → -140) as evidence of
  "sharp money" justifying a bet "even at low EV%" — **conflating a price
  observation with a predictive claim** `[desk: FEATURES_TRUST.md]`.

### Useful patterns to adopt
- Explaining the money mechanism in one plain sentence on the homepage.
- Dated, granular, personal-scale proof rather than aggregate percentages.

### Do not copy
- "Forget losing." Never imply a guaranteed outcome.
- Card-required trials with punitive post-trial charges.

---

## Unabated — VERIFIED (browser, 2026-08-31)

**URL:** https://unabated.com/

### What I actually saw
- **Palette:** dark navy-charcoal, **green** primary CTA, with a live odds
  screen used as a dimmed background texture behind the hero — the "terminal as
  hero" device.
- **Headline:** "**Every Sharp Started Somewhere**" / *"Bet with clarity using
  the tools, education and data science developed by pro bettors."*
- **Proof claim:** *"Trusted by thousands — **96% of Unabated members say they've
  become profitable sports bettors.**"*
- **Nav:** Home · Tools · Sports · Pricing · Community · Education · API.
- **CTA:** "Start for Free" (note: free entry, unlike PlayerProps).
- Below the fold: a "Featured in:" press logo wall.

### First-value profile
| Field | Finding |
|---|---|
| **First 30 seconds** | "Professional-grade tools and education for serious bettors." |
| **First 2 minutes** | Some tooling is reachable free; the depth is gated. |
| **Free value** | Genuine free tier exists — better funnel design than PlayerProps. |
| **Paywall moment** | Depth and real-time refresh gated behind tiers. |
| **Core aha** | Seeing the odds screen populated with real dispersion across books. |

### Strengths
- **"Every Sharp Started Somewhere" is the best headline in the category.** It is
  aspirational without promising an outcome, and it makes education a ladder
  rather than a remedial admission. It converts the intimidation of sharp tools
  into an invitation.
- Web-first and unapologetic about it — no app store listing found
  `[desk: APP_STORE.md]` — which is coherent for a desktop odds screen.
- Education and Community as first-class nav items, not footer links.

### Weaknesses
- **"96% of members say they've become profitable"** is a self-selected,
  self-reported survey presented in the position of a performance claim. It is
  the most misleading number I saw this session precisely *because* it is
  technically defensible — it is a real survey result doing the rhetorical work
  of an audited track record.
- Their marketing describes a synthetic consensus line as showing "true EV" /
  "true edge" — again blurring a market observation into a predictive claim
  `[desk: FEATURES_TRUST.md]`.
- Desktop-only reality excludes the phone, where most bettors actually decide.

### Useful patterns to adopt
- The headline strategy: aspiration without outcome promise.
- Using the real product screen as the hero image. It signals substance and sets
  accurate expectations — far better than an illustration.
- Education as top-level navigation.

### Do not copy
- Survey results dressed as performance evidence.
- "True EV" / "true edge" language.

---

## Action Network — VERIFIED (browser, 2026-08-31)

**URL:** https://www.actionnetwork.com/

### What I actually saw
- **The only major competitor with a LIGHT interface.** White/light-grey ground,
  green accent, heavy sports photography. Reads as media, not tooling.
- **Two full nav rows, ~21 destinations:**
  Row 1 — Sports · Odds · Picks · Tools `PRO` · Sports Betting · Prediction
  Markets · Casinos · Resources.
  Row 2 — Home · Odds · Public Betting · PRO Report · Prop Projections · PRO
  Projections · Picks · Sportsbooks · Casinos · Pro Systems · Legalization
  Tracker · How To Bet · Betting Calculators.
- **A horizontal odds rail across the top**: per-game cards showing
  `NE +162 / SEA -194`, kickoff time, and TV network (NBC/Peacock, Netflix, CBS,
  FOX). Compact, scannable, immediately useful.
- Right rail: "Best U.S. Sportsbooks" affiliate list (Fanatics, BetMGM, bet365).
- Persistent chat bubble bottom-right.

### First-value profile
| Field | Finding |
|---|---|
| **First 30 seconds** | "Sports betting news, odds and picks." Media-first identity. |
| **First 2 minutes** | A lot — free odds, public betting %, articles, scores. |
| **Free value** | **The highest in the category.** Most content is open. |
| **Paywall moment** | PRO tier for projections, PRO Report, Pro Systems. Soft and gradual. |
| **Core aha** | Free public-betting splits — "here's what everyone else is doing." |

### Strengths
- **The top odds rail is the single best UI pattern I saw this session.** Games,
  prices, start time and broadcast channel in one scannable strip. Directly
  adaptable to our TODAY screen.
- Content-led acquisition gives an enormous free surface and SEO moat.
- Largest real scale in the set (~35K app ratings) `[desk: APP_STORE.md]`.
- Light theme differentiates it instantly from every tool competitor.

### Weaknesses
- **Twenty-one nav destinations is not an information architecture, it is a
  sitemap.** No task ordering, duplicated labels across both rows ("Odds",
  "Picks", "Casinos" appear twice). A user cannot form a mental model.
- Affiliate sportsbook placement competes with the editorial product for trust.
- Casino content sits beside betting analysis, diluting the analytical brand.

### Useful patterns to adopt
- **The top odds rail.** Adopt the pattern.
- Generous free content as the acquisition engine.
- Broadcast channel shown alongside start time — small, genuinely useful, and
  nobody else does it.

### Do not copy
- The nav sprawl. Our entire IA should be ~6 items.
- Casino adjacency.

---

## Props.Cash — VERIFIED (browser, 2026-08-31)

**URL:** https://props.cash/

### What I actually saw
- **Palette:** black with a **mint/spring green** accent. Green is the dominant
  accent colour in this category alongside blue.
- **Headline:** "**FIND THE EDGE**" in very heavy condensed caps.
- **Hero:** phone mockup of a player prop screen — Shai Gilgeous-Alexander,
  `O 31.5 Points`, tab rail `3PTA · PTS · AST · REB · 3PM · P+A`, a `MATCHUP`
  dial showing a letter grade **`A-`**, `OPP vs NOP`, `DEF RANK ▲27th`,
  `AVG: 32.1`, and a bar chart of recent games.
- **Proof:** `★★★★★ 7,000+ reviews`.
- **A scrolling promotional marquee pinned to the very top of the page:**
  *"All Sports Annual 40% OFF! Enter ANNUAL40 at checkout — $119.99/year"*.
- Cookie consent bar with Decline/Accept.

### First-value profile
| Field | Finding |
|---|---|
| **First 30 seconds** | "Research player props with hit rates and matchup grades." |
| **First 2 minutes** | Marketing page; the tool requires the app or login. |
| **Free value** | Limited on web; the mobile app is the real product. |
| **Paywall moment** | Discount-driven — the marquee pushes the annual plan immediately. |
| **Core aha** | The letter-graded matchup dial — instant, legible verdict. |

### Strengths
- **The `A-` matchup grade is the most legible verdict device in the category.**
  A letter grade needs no explanation, compresses many inputs into one glyph, and
  works at a glance on a phone. This is a genuinely strong pattern.
- The stat-tab rail (PTS/AST/REB/…) is an efficient way to pivot one player
  across markets.
- `DEF RANK ▲27th` — contextualising an opponent by rank rather than raw stat is
  good plain-English translation.

### Weaknesses
- A **permanent discount marquee** trains users that the list price is fake and
  devalues the product.
- A letter grade with no visible derivation is a black box — legible but not
  inspectable. It is the *opposite* failure to our current product, which is
  inspectable but illegible.
- Hit-rate splits over short windows invite small-sample conclusions.

### Useful patterns to adopt
- **A single-glyph verdict** (grade or equivalent) as the top-level summary,
  **provided it expands to show its inputs.** This resolves our density problem
  and their opacity problem simultaneously.
- Rank-based context instead of raw stats.

### Do not copy
- Permanent discount marquees.
- An unexplained grade.

---

## Betstamp — VERIFIED (browser, 2026-08-31)

**URL:** https://betstamp.com/

### What I actually saw — note the pivot
Betstamp has **repositioned from a consumer bet tracker to a B2B data business.**
The homepage now sells infrastructure.

- **Palette:** deep navy, **sky blue** accent, orange secondary CTA.
- **Eyebrow:** `THE TRUE LINE`. **Headline:** "**THE SHARPEST PROPS PRICING IN
  THE INDUSTRY.**"
- **Body:** *"Our proprietary props pricing engine — built from 200+ sportsbooks
  and 5+ seasons of closing lines. Powering the PRO Odds Screen and sportsbook
  pricing feed. Plus our sports betting API, prediction markets API, and SGP
  pricing engine."*
- **CTAs:** "**Talk to Sales →**" and "See PRO Odds Screen". Header has "Request
  a Demo". This is enterprise sales language.
- **Hero:** a browser-chrome mock of `pro.betstamp.com` showing a dense odds
  grid — league tabs (MLB/NBA/NHL/NFL), `Player Props | Game Lines` toggle, a
  `filter edge ≥ 1.5%` control, and columns `Edge | True Line | FanDuel | Betano
  | bet365 | Betway | Novig`, with best prices highlighted in blue and stale ones
  struck through. Footer of the mock: `207 books · 2,548 markets · refresh 404ms
  · API v4 · 99.99%`.
- **Stat bar:** `8+ ODDS FEEDS · 110+ MARKETS · 17ms MEDIAN REFRESH · 4.41%
  UPTIME SLA · 0+ SEASONS BACKTESTED` — the last two are visibly wrong
  (a 4.41% uptime SLA, zero seasons backtested), almost certainly count-up
  animations captured mid-render. **A cautionary note for our own design: animated
  stat counters screenshot and cache badly, and can display absurd values.**

### Strengths
- The odds grid mock is the best **dense data presentation** in the set:
  strikethrough for stale prices, highlight for best price, an explicit edge
  filter, and latency/coverage stated as hard numbers.
- Stating `refresh 404ms` and `207 books` is *falsifiable* infrastructure proof —
  a much better class of claim than "96% of members are profitable."

### Weaknesses
- The consumer product is now secondary; consumer pricing is steep
  ($249/mo Main tier) `[desk: PRICING.md]`.
- App reviews report phantom bets and sportsbook sync failures
  `[desk: APP_STORE.md]` — a warning for any auto-sync ambition of ours.
- "True Line" is their branded term. **Avoid "Trueline"/"True Line" in our
  naming** — it collides both here and with an existing P2P betting app
  `[desk: NAMES.md]`.

### Useful patterns to adopt
- Strikethrough for stale prices; highlight for best available.
- Hard, checkable infrastructure numbers as trust signals.

### Do not copy
- Animated stat counters.
- "True Line" terminology.

---

## Pikkit — VERIFIED (browser, 2026-08-31)

**URL:** https://pikkit.com/

### What I actually saw
- **Palette:** near-black with a **periwinkle/soft blue-violet** accent —
  friendlier and less aggressive than the rest of the category.
- **Nav:** Pikkit Pro · Social · Features · Offers · QuickPickBot · Blog · Sign in.
- **Hero:** two phone mockups — a **monthly calendar heatmap** with per-day unit
  results (green/red cells: `6.47u`, `11.8u`, `19.3u`), and a weekly summary
  showing `Profit +$135.21 · ROI +49.52% · Record 25-13-0` with a stepped equity
  curve, plus tag and league breakdowns.
- **CTA:** "Start tracking for free" · `4.9` · `18K+ reviews`.

### Strengths
- **Free-first.** Tracking is free; Pro is the upsell. The best funnel shape in
  the category.
- Second-largest real scale in the set (~21K ratings) `[desk: APP_STORE.md]`.
- **Pikkit is the one product that does sample-size skepticism properly.** Their
  own material states that *a bettor with 5% ROI over 1,000 bets is much stronger
  than 20% ROI over 50 bets, since small samples are mostly luck*
  `[desk: FEATURES_TRUST.md]`. This is real, vendor-authored statistical
  honesty as product philosophy — **the single most important counterexample to
  our "nobody does sample-size skepticism" hypothesis.**
- Sportsbook-synced records are harder to fake than self-reported ones.

### Weaknesses
- Backward-looking. It tells you how you did, not what to do next.
- Sync breaks on unsupported books `[desk: APP_STORE.md]`.
- The calendar heatmap is emotionally loaded — a wall of red cells during a
  normal downswing is a churn risk.

### Useful patterns to adopt
- **Free-forever core utility with a paid intelligence layer.** This should be
  our funnel.
- Sample-size honesty as stated philosophy — and we must now do it *better*
  than Pikkit, not merely claim it first.
- The calendar heatmap for a personal record (with care).

### Do not copy
- Loss-heavy visualisations without framing.

---

## Outlier — VERIFIED (browser, 2026-08-31)

**URL:** https://outlier.bet/

### What I actually saw
- **Palette:** true black with an **iridescent pastel gradient** (mint → cream →
  peach → lavender) and soft 3D blob shapes. The most "design-forward" and least
  gambling-coded look in the set — closer to a consumer fintech app.
- **Headline:** "**The #1 App for Making Smarter Bets**" · *"Quickly analyze
  thousands of picks. Find your edge. Beat the odds."*
- **Nav:** Features · Reviews · Pricing · **Positive EV** · Calculator ·
  Education · Blog · Press. Note "Positive EV" promoted to top-level nav.
- **CTA:** "Find your next bet" / "Start betting".

### Strengths
- The most visually distinctive brand in the category and the least casino-coded.
- Pastel-on-black is genuinely differentiated and legible.
- "Reviews" and "Press" in primary nav — confident social proof placement.

### Weaknesses
- "#1 App" — a second unsubstantiated #1 claim in the same category.
- "Positive EV" as a nav label assumes fluency most bettors lack.
- Their "Trends" feature surfaces streak filters ("7 of last 10 primetime
  games") criticised by a third-party reviewer for artificially narrowing the
  sample — **the tiny-sample mechanism, without the "100%" copy**
  `[desk: FEATURES_TRUST.md]`.
- Cheapest advertised tier reportedly excludes the differentiating features,
  drawing bait-and-switch complaints `[desk: APP_STORE.md]`.

### Useful patterns to adopt
- Proving that a betting tool can look like premium consumer software.
- Education and Calculator as free, indexable top-level assets.

### Do not copy
- Jargon as a navigation label.
- Streak-based trend filters.
- Feature-starved entry tiers.

---

## Tier 2 — covered by text research `[desk]`

Not visually inspected this session; see `research/desk/` for detail.

| Product | Position | Key finding |
|---|---|---|
| **BetQL** | Consumer picks, 1–5 star game ratings | Worst trust profile found: charges after cancellation, 33.3/100 trust score, unresponsive support `[APP_STORE.md]` |
| **LineMate** | Low-cost mobile prop trends (~$9.99–14.99/mo) | Undisclosed trial terms complaints; conflicting price sources |
| **Juice Reel** | Social bet tracking | Sync crashes; social/group angle is its differentiator |
| **BetQL / Action LABS** | Premium systems | Enterprise pricing, opaque methodology |

---

# Competitive white space

Each opportunity is rated for how defensible it actually is, after visual
verification. **Two of the original hypotheses did not survive contact.**

### ✗ NOT white space — "we don't sell picks / we're honest"
**FALSIFIED.** PlayerProps.ai ships *"We don't give you picks. We make you
sharper."* Rithmm ships *"Sometimes the best bet is no bet"* and *"anyone who
guarantees winners is selling you something."* Two competitors already own this
language. **Do not build the brand on it.**

### ✗ NOT white space — "nobody warns about sample size"
**PARTIALLY FALSIFIED.** Pikkit explicitly teaches that 5% ROI over 1,000 bets
beats 20% over 50 `[desk: FEATURES_TRUST.md]`. The claim must be narrowed:
sample-size skepticism is absent from *pre-bet research* surfaces, but present in
*post-bet tracking*. Our opportunity is to move it to the point of decision.

### ✓✓✓ REAL — "Why did this line move?"
**No product in the category narrates causation.** Several show the raw
ingredients — an injury feed, a line chart, public vs sharp percentages — but
none joins event → book reaction → consensus shift into a sentence
`[desk: FEATURES_TRUST.md]`. This is the **strongest single differentiator
available**, it is genuinely hard to copy (it needs event timing plus odds
snapshots plus editorial judgment), and the repo already has the ingredients:
`src/cli watch` polls probables/lineups/transactions for event timing, and
`snapshot`/`dense`/`movement` capture spaced odds observations.
**MOAT CANDIDATE.**

### ✓✓✓ REAL — verifiable-without-prediction as the core claim
Every competitor's headline number is a model output: "+46% EDGE", "Edge = our
win probability vs the book", "true EV". **None of them can be checked by the
customer.** Price improvement can be checked in ten seconds against the books.
Building the product's central promise on the one claim that survives scrutiny
is a structural, not tonal, difference. **DIFFERENTIATOR.**

### ✓✓ REAL — the two-depth product
Rithmm promises depth-on-demand *conversationally*; nobody delivers a
**structural** Quick ⇄ Advanced toggle where the user can see the shape of what
is hidden and pull it forward. Competitors are either simple-and-opaque
(Props.Cash's `A-` grade) or dense-and-illegible (Betstamp's grid, and our own
current output). **Nobody is legible at the top and inspectable underneath.**
**DIFFERENTIATOR.**

### ✓✓ REAL — negative evidence as a first-class field
"Reason to avoid it" / "your weakest reason" is shown by nobody as a permanent,
structural field. Rithmm's Scout will say "I'd stay away" as a *verdict*, but no
product routinely presents the counterargument alongside a bet the user likes.
**DIFFERENTIATOR.**

### ✓✓ REAL — a research tool that is honest about a quiet night
Every competitor is incentivised to find you action. A product that says "we
checked 15 games and none of them clears the bar, here's what we looked at" is
differentiated *and* trust-building — but only if it is presented as a service
rather than as an empty state. See **No Play UX**.

### ✓ REAL — transparent, self-serve billing
Billing friction is the **#1 recurring complaint across the entire category**
`[desk: APP_STORE.md]`: BetQL charging post-cancellation, OddsJam's surprise
€630 charge, PlayerProps requiring an email to cancel, LineMate's undisclosed
trial terms. One-click in-app cancellation, no card for the free tier, and a
plain-language billing page is cheap to build and directly attacks the loudest
pain in the market. **TABLE STAKES that competitors have vacated.**

### ✓ REAL — per-sport packaging
Only Props.Cash sells a standalone sport SKU, and as a flat season fee rather
than a recurring tier `[desk: PRICING.md]`. The per-sport axis is nearly unused.
Genuine packaging differentiation — though see the caveat under Pricing.

### ✓ REAL — an ROI/breakeven calculator on the pricing page
Nobody does it `[desk: PRICING.md]`. For a product whose value is price
improvement, showing "at your stake size, this pays for itself at N bets/month"
is both honest and persuasive.

---
# Proposed customer information architecture

## Recommended navigation — 5 items

```
TODAY      GAMES      BET CHECK      ODDS      MY BETS
```

Secondary (account menu, not primary nav): Research · Settings · Billing · Help.

## Why this, and not the starting hypothesis

The brief's hypothesis was: `TODAY · GAMES · BET CHECK · PROPS · WHAT CHANGED ·
ODDS · RESEARCH · MY BETS` (8 items). I recommend **5**, with three changes:

| Change | Reason |
|---|---|
| **Remove PROPS** | **FUTURE / RESEARCH DEPENDENT.** No prop data exists in the engine. A nav item that leads to an empty page is worse than no nav item. Add it when props ship, as a peer of GAMES. |
| **Fold WHAT CHANGED into TODAY** | "What changed" is not a destination — it is *the reason you reopen the app*. As its own tab it gets visited once and forgotten; as a live band on TODAY it is the thing that makes TODAY worth reloading at 4pm. This is a retention decision, not a taxonomy decision. |
| **Demote RESEARCH to the account menu** | Small audience, high confusion cost. Keeping it in primary nav invites exactly the engineering-vocabulary leakage we are trying to eliminate. |

**Evidence for going narrow:** Action Network has ~21 nav destinations with
duplicated labels across two rows (VERIFIED) and no discernible task ordering.
Rithmm has 5 (THE EDGE · WHAT YOU GET · SCOUT · MODELS · PRICING) and is the
most coherent product in the set. Unabated has 7. PlayerProps has 11 rail items
organised by market type, with no "today" and no game page — a user must already
know which predictor they want before the IA helps them.

**The nav must map to the customer's actual sequence, not to our data model:**

```
What's on tonight?   → TODAY
Tell me about a game → GAMES
Is my bet any good?  → BET CHECK
Where's the price?   → ODDS
How am I doing?      → MY BETS
```

## Mobile navigation
Same five items as a bottom tab bar. Five is the maximum that fits comfortably
with labels at 375px, which independently confirms the count.

## Vocabulary rules — customer surface

The customer must **never** encounter: `V1`–`V5` · `PBO` · `CSCV` · genomes ·
registry fingerprints · falsification battery · `Phase 2A` · Alpha/Beta/Charlie/
Delta · `h2h_1st_5_innings` · raw z-scores · UTC timestamps with microseconds.

**Required translations:**

| Internal | Customer-facing |
|---|---|
| z-score / "rarity" | *(never shown as a number — converted to prose)* |
| `UNPROVEN` | **Observation** |
| exploratory research family | **Exploratory** |
| historical candidate | **Historical support** |
| forward ledger entry | **Forward testing** |
| validated / gate passed | **Validated** |
| Engine 2 is `None` / Ranker gated | **No demonstrated edge** |
| de-vig / no-vig fair probability | ~~Market's true read~~ **MARKET-IMPLIED CONSENSUS** [row corrected 2026-08-31 per Brey: removing vig does not make a market objectively true; the original phrase is hard-banned by tests/test_customer_language.py] |
| hold | **Book's margin** |
| book dispersion | **How much books disagree** |
| `h2h_1st_5_innings` | **First 5 innings — moneyline** |
| sample size N | **Sample reliability** |
| price improvement vs consensus | **Better price available** |

---

# Page map

Every page below carries capability and priority labels.

| Page | Purpose | Audience | Primary action | Timing | Role |
|---|---|---|---|---|---|
| **TODAY** | Orient in 30s; find tonight's few things that matter | All | Open a game or a finding | **MVP** | **HIGH WTP DRIVER** |
| **GAME (Quick)** | Understand one matchup in 30s | Casual, Daily | Read verdict / go to Bet Check | **MVP** | **HIGH WTP DRIVER** |
| **GAME (Advanced)** | Expose the full evidence | Data nerd, Sharp | Inspect, verify | **MVP** | **DIFFERENTIATOR** |
| **BET CHECK** | Evaluate the user's own stated bet | All — esp. Casual | Accept / reject / reprice the bet | **MVP** | **HIGH WTP DRIVER** |
| **ODDS** | Find the best available price | Sharp, Daily | Take a better number | **MVP** | **TABLE STAKES** |
| **MY BETS** | Track what was bet and what it was worth | Daily, Sharp | Log a bet; review CLV | **V1** | **MOAT CANDIDATE** |
| **WHAT CHANGED** *(band on TODAY)* | Show what moved since last visit | Daily | Re-check an affected game | **MVP** | **DIFFERENTIATOR** |
| **WHY DID THIS LINE MOVE** *(in-game)* | Narrate event → market reaction | Sharp, Daily | Understand a price | **V1** | **MOAT CANDIDATE** |
| **PROPS** | Player-level research | Prop bettor | Research a prop | **LATER** | **HIGH WTP DRIVER** |
| **RESEARCH / METHODOLOGY** | Explain how we know things | Nerd, skeptic | Build trust | **V1** | **DIFFERENTIATOR** |
| **PRICING** | Convert | Prospect | Subscribe | **MVP** | **TABLE STAKES** |
| **ONBOARDING** | Personalise + reach first value | New user | Reach aha | **MVP** | **TABLE STAKES** |
| **INTERNAL ADMIN** | Research operations | Us only | — | **V1** | — |

---

# Today / Daily Slate specification

**MVP · HIGH WTP DRIVER · ENGINEERING REQUIRED** (the underlying briefing content
is EXISTS TODAY — `src/pipeline/briefing.py`, `src/report/dashboard.py`)

**Purpose:** the customer's home screen. Answer "what should I know about tonight?"
in 30 seconds, and be worth reopening at 4pm.

**Primary action:** open a game, or act on a finding.

## Component hierarchy

```
1  DATE + SLATE SUMMARY      one plain sentence, never a row of zeros
2  WHAT CHANGED band         live, only if non-empty; the reason to reload
3  WHAT MATTERS TONIGHT      3–5 findings, ranked by ACTIONABILITY
4  GAME RAIL / GAME LIST     every game, price, first pitch, broadcast
5  BEST PRICES STRIP         biggest price improvements across the slate
```

## Rule 1 — never lead with a null count

Our current output's header reads `15 GAMES · 0 FLAGGED · 0 CANDIDATES · 0 NO
MARKET` and stamps `NO PLAY` on all 15 games (VERIFIED). Three zeros in the
largest type on the page reads as an outage, not a service.

**Replace with a sentence that states the work done:**

> *"15 games tonight. We checked all of them. Two are worth your attention, and
> one has a price worth taking."*

On a genuinely quiet night:

> *"15 games tonight. Nothing clears the bar — here's what we looked at and why
> it didn't."*

The honesty is preserved. The framing changes from absence to service.

## Rule 2 — rank by actionability, not rarity

This is the most important single fix. On the 2026-08-28 slate, ranking by
z-score produced (VERIFIED):

| Rank | z | Item |
|---|---|---|
| 1 | 3.8 | SD flew 2,078 miles, crossing 2.3 time zones |
| 2 | 2.0 | LAD starter 2.69 FIP vs 4.20 league average |
| 5 | 1.5 | **betrivers has PIT at -110 — 1.5 points cheaper than 11-book consensus** |

The only item that makes the reader money is fifth, beneath travel trivia,
because the sort key is statistical rarity. The page's own subhead admits
*"that is rarity, not importance"* — and ships it anyway.

**Required ranking tiers:**

```
TIER 1  Price improvement — a better number on a bet you'd make anyway
TIER 2  Material change   — scratch, lineup, starter change, weather flip
TIER 3  Matchup substance — starter quality, bullpen state, platoon
TIER 4  Context           — travel, rest, park
```

Rarity may inform ordering *within* a tier. It must never determine the tier.
**z-scores are never displayed to the customer.**

## Finding card anatomy

```
┌────────────────────────────────────────────────┐
│ BETTER PRICE                          PIT @ STL│   ← tier label + game
│                                                │
│ PIT is 1.5 points cheaper at BetRivers         │   ← plain-English claim
│ than the 11-book consensus.                    │
│                                                │
│ -110 at BetRivers   ·   -118 consensus         │   ← the numbers, secondary
│                                                │
│ No prediction required — the same bet at a     │   ← why it's trustworthy
│ better price.                                  │
└────────────────────────────────────────────────┘
```

## Game rail
Adopt Action Network's top odds rail (VERIFIED as the best pattern in the set):
per-game card with teams, both prices, first pitch **in the user's local time**,
and broadcast channel. Add our own layer: a small marker when a game has an
unread change or a price improvement.

## States

| State | Behaviour |
|---|---|
| **Loading** | Skeleton matching final layout. Never a spinner on the whole page. Game rail renders first — it needs only the schedule. |
| **Empty (no games)** | "No games today. Next slate: Thursday." Plus a link to yesterday's results. Offseason is a real state — design it. |
| **Empty (nothing notable)** | Never blank. Show what was checked. See No Play UX. |
| **Partial data** | Render what exists; label the gap explicitly. See Missing-data UX. |
| **Error** | Preserve the game rail if schedule loaded. Never blank the page for one failed source. |
| **Stale** | If odds are older than ~2 minutes, show the age. Never show a stale price as current. |

## Mobile
Single column. WHAT CHANGED and WHAT MATTERS above the game list. Game rail
becomes a vertical list, not a horizontal scroller — horizontal scrollers hide
content on phones.

---

# Game Analyzer specification

**MVP · HIGH WTP DRIVER**

This page has **two depths of one page** — not two pages, not two products.

---

## QUICK VIEW — the default

**ENGINEERING REQUIRED** (content EXISTS TODAY via `src/detect/dossier.py`)

**Target: understood in ~30 seconds.** Plain English. No jargon. No raw tables.
No z-scores. No badge spam.

### Reference layout

```
─────────────────────────────────────────────
PADRES @ RAYS
6:10 pm ET · Tropicana Field · MLB Network
─────────────────────────────────────────────

WHY THIS GAME MATTERS

  ✓  Tampa's starter has performed well above
     league average.
  ✓  Tampa has the stronger starting-pitching
     matchup.
  ⚠  San Diego traveled more than 2,000 miles
     east, crossing two time zones.
  ⚠  Market support is modest, not overwhelming.

─────────────────────────────────────────────
YOUR BET               Rays ML  -132
BEST AVAILABLE PRICE   -125  at DraftKings  →
─────────────────────────────────────────────

DATA SUPPORT           ●●●○  Moderate

MAIN REASON TO LIKE IT
Starting pitching.

MAIN REASON TO AVOID IT
Price / bullpen uncertainty.

HISTORICAL EVIDENCE
Interesting matchup — no demonstrated betting
edge yet.

          [ SHOW ADVANCED ANALYSIS ]
─────────────────────────────────────────────
```

### Quick View rules

1. **Maximum 5 factors.** If the engine produces 20, show 5. The rest live in
   Advanced. Truncation is the feature.
2. **Every factor is one sentence** and must survive the "why should I care?"
   test. `FIP 3.42 vs 4.20` fails. *"Tampa's starter has performed well above
   league average"* passes.
3. **✓ and ⚠ carry the visual load**, not colour alone (accessibility).
   ✓ = supports the home/favoured side. ⚠ = argues against or adds uncertainty.
4. **Both sides always appear.** If there are no ⚠ items, say
   *"No significant counterarguments found"* — never silently omit the section.
   A page that only ever shows ✓ is a tout.
5. **No numbers without meaning.** `-132` and `-125` stay because bettors read
   prices natively. `3.42`, `2.69`, `3.8` do not appear at this depth.
6. **One accent colour maximum.** No rainbow of severity states.

---

## ADVANCED VIEW — one click deeper

**Mixed capability — labelled per block below**

**Do not dumb this down.** The Data Nerd and Sharp personas are served here, and
they will judge the product by whether it holds real content.

### Blocks, in order

```
1  STARTING PITCHERS       FIP, xFIP*, ERA, WHIP, K-BB%, IP/start,
                           expected length tonight
2  LINEUPS                 confirmed vs projected, platoon splits,
                           lineup-slot decomposition*
3  BULLPEN                 availability, back-to-back usage, leverage,
                           likely late-inning arms
4  BATTED BALL / QUALITY   xwOBA*, contact profile, pitch mix*, velocity*
5  MARKET                  full de-vig table, hold, consensus, book
                           dispersion, F5 vs full game
6  CONTEXT                 park, weather with wind bearing caveat, travel,
                           rest
7  EVIDENCE + METHOD       sample sizes, confidence intervals, how each
                           claim was derived
```

`*` = **FUTURE / RESEARCH DEPENDENT** — pitch mix, velocity, xwOBA, xFIP and
lineup-slot decomposition are **not currently ingested**. The engine is Python
standard library only, with MLB Stats API + Open-Meteo as free sources
(VERIFIED via `python3 -m src.cli status`). Blocks 1 (partly), 3, 5, 6 are
**EXISTS TODAY**. **Do not design Advanced View as if Savant data is present.**

### Advanced View rules

1. **Every block collapses, and remembers its state per user.** A returning nerd
   should land in the shape they left.
2. **Every number is paired with its sample.** `FIP 3.42` alone is forbidden;
   `FIP 3.42 · 107 IP this season` is required. This is where sample-size
   honesty lives structurally.
3. **Tables are permitted here — and only here.** Horizontally scrollable in
   their own container, never causing page-level horizontal scroll.
4. **Monospace for figures only.** Prose stays in the text face.
5. **Each block links to the methodology** for that block.

---

## Moving between depths

This is a named, designed interaction, not an afterthought.

| Rule | Behaviour |
|---|---|
| **Default** | Quick View, always, for every new user. |
| **Control** | A single primary button: `SHOW ADVANCED ANALYSIS` at the end of Quick View. Not a tab, not a settings toggle — an invitation at the moment curiosity peaks. |
| **Transition** | Advanced **expands beneath** Quick View. Quick View stays on the page. The user never loses the plain-English summary they just understood; the detail is *appended*, not *swapped*. **This is the core interaction of the product.** |
| **Per-factor drilling** | Each ✓/⚠ factor is independently expandable in place, revealing just that factor's numbers and sample. A user can go deep on one thing without opening everything. |
| **Stickiness** | If a user opens Advanced 3 times, offer once: "Always show advanced analysis?" Never auto-switch without asking. |
| **Persistence** | The preference is per-user and per-device, and reversible from the page itself, not buried in settings. |
| **URL** | Advanced state is addressable (`?depth=advanced`) so a Content Creator can share the deep view. |
| **Mobile** | Identical model. Advanced expands inline. Never a separate screen — a back-button trip loses context. |

**The one-line summary for the implementing agent:**
**Quick View translates the intelligence. Advanced View exposes it. Same engine,
same page, appended not replaced.**

---

# Bet Check specification

**MVP · HIGH WTP DRIVER · ENGINEERING REQUIRED**
(underlying analysis EXISTS TODAY; the entry point, parser and layout do not)

**This is the flagship feature.** Competitive validation: PlayerProps.ai calls
its equivalent *"our single most powerful feature"*; Rithmm's Scout lists
*"What do you think about this bet?"* as question #2 (both VERIFIED).

**The customer insight:** most bettors already have a bet in mind. They do not
want a pick. They want to know **"is my reasoning actually supported?"**

## Input

A single field accepting natural language:

```
┌──────────────────────────────────────────────┐
│  Yankees ML -125                          →  │
└──────────────────────────────────────────────┘
   Try:  "Rays first five under 3.5"
         "Padres +1.5"
```

Must tolerate: `Yankees ML -125` · `NYY moneyline` · `Yanks -125` ·
`Rays F5 under 3.5` · `Padres +1.5 -110`. Parsing failures must offer a picker,
never a bare error.

## Output — fixed skeleton, always these fields, always this order

A **fixed skeleton is a trust mechanism**: when the shape never changes, an
omission becomes visible. Free-form prose can quietly drop the counterargument.

```
─────────────────────────────────────────────
YOUR BET      Yankees ML  -125
─────────────────────────────────────────────

THESIS SUPPORT                    4 factors
  ✓ Starter matchup favours NYY
  ✓ Opposing bullpen worked 3 innings last night
  ✓ Platoon edge in 5 of 9 lineup spots
  ✓ Wind blowing out to right

COUNTERARGUMENT                   2 risks
  ⚠ NYY starter averages 4.9 innings — this
    game reaches the bullpen early
  ⚠ Price has already moved from -112 to -125

─────────────────────────────────────────────
BEST AVAILABLE PRICE    -118  at FanDuel   →
MARKET CONSENSUS        -124
YOUR PRICE              -125    ⚠ below market
─────────────────────────────────────────────

STRONGEST REASON
Starter matchup.

WEAKEST REASON
"Yankees are 6-1 recently" — a seven-game record
adds almost nothing. Recent record is mostly
noise at this sample size.

WHAT CHANGED
· 2:41pm  Judge confirmed in the lineup
· 3:15pm  Price moved -112 → -125 across 9 books

HISTORICAL SUPPORT      ●●○  Moderate
EVIDENCE STATUS         Observation

─────────────────────────────────────────────
BOTTOM LINE
The pitching argument is real. The price is not —
you can get this same bet 7 points cheaper at
FanDuel, and the number has already moved against
you today. If you like it, take -118, not -125.
─────────────────────────────────────────────

        [ SHOW ADVANCED ANALYSIS ]
```

## Field definitions

| Field | Content | Capability |
|---|---|---|
| **THESIS SUPPORT** | Factors that back the bet. Count shown. | EXISTS TODAY |
| **COUNTERARGUMENT** | Factors against. **Never suppressed, never zero-by-omission.** | EXISTS TODAY |
| **BEST AVAILABLE PRICE** | Best number across books, with the book named and a link | EXISTS TODAY |
| **MARKET CONSENSUS** | De-vigged multi-book consensus | EXISTS TODAY |
| **STRONGEST / WEAKEST REASON** | One line each. Weakest is the Debunker surface. | ENGINEERING REQUIRED |
| **WHAT CHANGED** | Timestamped events since this morning | EXISTS TODAY (`cli watch`) |
| **HISTORICAL SUPPORT** | Weak / Moderate / Strong | ENGINEERING REQUIRED |
| **EVIDENCE STATUS** | Observation → Exploratory → Historical support → Forward testing → Validated | ENGINEERING REQUIRED |
| **BOTTOM LINE** | 2–3 plain sentences. **Never implies guaranteed profit.** | ENGINEERING REQUIRED |

## Bet Check rules

1. **We never say "bet this."** We say what supports it, what argues against it,
   and where the price is better. The decision stays with the user — this is
   both an honesty position and a regulatory one.
2. **The counterargument is mandatory.** If genuinely none is found, print
   *"No significant counterarguments found"* explicitly.
3. **Price improvement is always surfaced** when it exists. It is the only
   claim requiring no prediction.
4. **Never a probability we cannot defend.** With the model UNCALIBRATED
   (VERIFIED via `cli status`), Bet Check must **not** display a win-probability
   number. It reasons about evidence and price only. When a model is validated,
   probability becomes an additive field — not a redesign.

---

# Bet Debunker specification

**V1 · DIFFERENTIATOR · ENGINEERING REQUIRED**

Not a separate page. The **WEAKEST REASON** field of Bet Check, plus an optional
free-text box: *"What's your reasoning?"*

**Behaviour:** take the user's stated rationale, assess its evidential weight,
and *replace it with something better* — never merely negate it.

```
YOU SAID
"Judge is 7-for-15 against this pitcher."

WHAT THAT'S WORTH
15 at-bats is about two games. At that sample,
a .467 average and a .150 average are both
completely normal for the same hitter. This
tells you almost nothing.

WHAT'S ACTUALLY USEFUL HERE
Judge has a platoon edge against right-handed
pitching this season (312 PA), and this pitcher
throws a slider 38% of the time — a pitch Judge
has handled well over a much larger sample.
```

**Rules:** never condescending; always replaces rather than only debunks; the
correction is quantified, not asserted. The pattern *"you're not wrong to look at
this, you're looking at too little of it"* is the tone target.

**Repo note:** `demo_latest.html` already contains a `debunk` CSS class (3 uses,
VERIFIED) — the concept exists in embryo.

---

# What Changed specification

**MVP · DIFFERENTIATOR · EXISTS TODAY** (`src/cli watch` polls probables,
lineups and transactions for event timing)

**This is the retention engine.** It is the answer to "why open the app again at
4pm when I already read it at 9am?"

**Placement:** a live band on TODAY (not a separate tab), plus a per-game section.

## Format — reverse chronological, plain language, always timestamped local

```
WHAT CHANGED SINCE YOU LAST LOOKED           4 updates

4:12pm  LINEUP     Judge is OUT — not in the posted lineup.
                   NYY ML moved -145 → -128 across 9 books.       → NYY @ BOS

3:47pm  STARTER    Tampa's probable changed to Baz.                → SD @ TB

2:30pm  WEATHER    Wind at Wrigley flipped to blowing in at 12mph.
                   Total dropped 9.5 → 8.5.                        → CIN @ CHC

1:15pm  BULLPEN    Cleveland's closer threw 28 pitches yesterday
                   and is unlikely tonight.                        → KC @ CLE
```

## Rules

1. **Relevance tiers**, matching the existing engine's tiering: a scratched
   starter outranks a bench swap. Show tier 1–2 by default; "show all" reveals
   the rest.
2. **"Since you last looked" requires knowing when they last looked** —
   ENGINEERING REQUIRED (accounts). Until accounts exist, use "since this
   morning."
3. **Pair the event with the market reaction whenever both are known.** That
   pairing is the bridge to "Why did this line move" and is the single most
   valuable line on the screen.
4. **Empty is a legitimate state**: *"Nothing has changed since this morning."*
   That is genuinely useful information, not a failure.

---

# Why Did This Line Move specification

**V1 · MOAT CANDIDATE · ENGINEERING REQUIRED**
(ingredients EXIST TODAY: `cli watch` for event timing, `cli snapshot`/`dense`/
`movement` for spaced odds observations)

**No competitor in the category does this** — several show the ingredients,
none narrates causation `[desk: FEATURES_TRUST.md]`. This is the strongest
differentiator available and the hardest to copy.

## Presentation — narrative first, chart second

```
WHY DID THIS LINE MOVE?

NYY went from -112 to -145 between 1pm and 4pm.

  1:52pm   Beat reporter posts that Judge is
           getting a scheduled day off.
     ↓
  1:58pm   Two books pull the number.
     ↓
  2:10pm   Six of nine books move to -130 or
           shorter.
     ↓
  4:00pm   Consensus settles at -145.

WHAT WE THINK HAPPENED
A lineup scratch for a middle-order bat, priced
in over about twenty minutes.

CONFIDENCE   ●●○  Moderate
We observed the event and the move in this order.
We cannot prove the event caused the move.
```

## Rules

1. **Causal honesty is mandatory.** We observed sequence, not causation. The
   confidence line is not optional garnish — it is what makes the feature
   defensible.
2. **Three confidence levels:** *Strong* (single clear event, tight timing,
   broad book agreement) · *Moderate* (plausible event, reasonable timing) ·
   *Unexplained* (the line moved and we don't know why).
3. **"Unexplained" must be shown, not hidden.** A product that always has an
   explanation is confabulating. Showing "we don't know" on some moves is what
   makes the confident ones believable.
4. **Narrative above chart.** The line chart is supporting evidence, not the
   answer.

---

# Odds / Market Board specification

**MVP · TABLE STAKES · EXISTS TODAY** (multi-book capture, de-vig and consensus
are implemented; the repo's own research measured a mean best-vs-worst gap of
1.85% of implied probability, peaking at 4.14%)

**Purpose:** find the best available number. The most mechanically valuable page
in the product, because its claims need no prediction.

## Columns

```
GAME    MARKET   BEST PRICE   CONSENSUS   SPREAD OF BOOKS   MOVEMENT
```

## Rules

1. **Best price is highlighted and names the book.** Adopt Betstamp's pattern
   (VERIFIED): best price highlighted, stale prices struck through.
2. **Show price age.** Never present a stale number as live. State the refresh
   interval honestly — if we refresh every 5 minutes, say so; do not imply
   real-time.
3. **"How much books disagree"** rather than "dispersion". High disagreement is
   itself a finding worth surfacing.
4. **F5 and full game side by side.** The gap between them is the market's
   bullpen opinion — the product's best existing insight (VERIFIED in
   `demo_latest.html`) and it should be a first-class, explained element here.
5. **Never label a price difference as "EV" or "edge".** It is a better price.
   That distinction is the brand.

## Mobile
Cards, not a table. One game per card: best price, consensus, and the delta.
The full grid is desktop-only, and that is an acceptable, stated limitation.

---

# Props specification

**LATER · HIGH WTP DRIVER · FUTURE / RESEARCH DEPENDENT**

**No prop data exists in the engine today.** Do not build this in MVP; do not put
PROPS in the nav until it ships.

When it ships, the same two-depth model applies. Quick View for a prop:

```
AARON JUDGE — OVER 1.5 TOTAL BASES  (-135)

  ✓ Facing a right-hander he's handled well
  ✓ Batting second — more plate appearances
  ⚠ Best price is -125 at BetMGM, not -135
  ⚠ Only 15 at-bats against this pitcher —
    too few to mean anything

BEST AVAILABLE   -125 at BetMGM  →
DATA SUPPORT     ●●○  Moderate
```

**Design warning learned from competitors:** prop tools are where tiny-sample
marketing concentrates — PlayerProps.ai's `ACCURACY 66.7% (39)` and
`H2H 0%` (VERIFIED), Outlier's streak "Trends", Rithmm's "Power Trends"
`[desk: FEATURES_TRUST.md]`. **Our prop product must lead with sample
reliability, not hit-rate streaks.** Props.Cash's `A-` matchup grade is the
pattern to adapt — a legible verdict that expands to its inputs.

---

# Research area specification

**V1 · DIFFERENTIATOR · Mixed capability**

Account-menu, not primary nav. Two audiences: skeptics evaluating whether to
trust us, and nerds who want the method.

**Contains:** how each evidence tier is defined · what data sources we use and
their refresh cadence · what we have tested and what failed · our current
honest position on predictive edge · a plain-language methodology per feature.

**Must contain, prominently:**

> **We have not demonstrated a predictive betting edge.**
> What we do reliably: find better prices, surface what changed, and show you the
> evidence for and against a bet. If we ever demonstrate an edge, we will show
> the forward-tested record before we charge for it.

**This is a feature, not a disclaimer.** Zero of twelve competitors have an
independently audited track record `[desk: FEATURES_TRUST.md]`, and every one
of them implies performance. Saying the true thing plainly is differentiating —
but only if it sits alongside a product that already delivers value without it.

**Never expose:** V1–V5 families, PBO, CSCV, genomes, registry fingerprints,
falsification batteries, Evolution Lab internals.

---

# My Bets / saved research

**V1 · MOAT CANDIDATE · ENGINEERING REQUIRED** (no accounts or persistence exist)

**Why it is a moat:** it is the only feature that accumulates a switching cost.
Everything else is reproducible; a bet history is not.

**Contains:** logged bets · price taken vs closing price (CLV) · what we said at
the time · saved games and watchlist · a personal record.

## Two rules that differentiate us

1. **Show what we told you at the time, next to what happened.** No competitor
   does this. It is the closest thing to self-auditing available, and it is the
   strongest possible trust signal — *especially* when it makes us look wrong.
2. **Sample-size honesty on the user's own record.** Pikkit already teaches that
   5% ROI over 1,000 bets beats 20% over 50 `[desk: FEATURES_TRUST.md]`. We must
   match this at minimum: never show a win rate over a small sample without
   stating what that sample can and cannot support.

**Design warning:** Pikkit's red/green calendar heatmap is emotionally loaded
(VERIFIED). A wall of red during a normal downswing is a churn risk. Lead with
CLV — a process metric the user controls — rather than profit, which is mostly
variance in the short run.

**Manual entry for MVP.** Sportsbook auto-sync is a support burden: phantom bets
and sync failures are recurring complaints for Betstamp, Pikkit and Juice Reel
`[desk: APP_STORE.md]`.

---

# Internal Research / Admin separation

**V1 · Internal only · EXISTS TODAY** (as CLI tooling)

A **separate application at a separate URL**, behind separate auth. Not a
customer route with a role check — a different app.

**Contains:** Evolution Lab (`src/evolab/`) · V1–Vn research families ·
falsification battery · PIT audits · CSCV/PBO · data-health monitor
(`src/pipeline/health.py`) · forward ledger · timing reports · reproducibility
audits · the Ranker while Engine 2 is `None`.

## The hard rule that must survive the split

> **The customer product and the research lab must never share an evidence
> standard.** The Analyzer may show a labelled observation; the Ranker may not
> rank on one.

That asymmetry is the reason they are two things, and it comes from the repo's
own architecture audit. It must be preserved verbatim in the implementation.

---
# The customer value loop

**This is the spine of the product. If the loop breaks, the subscription churns.**

```
   OPEN APP
      ↓
   SEE TODAY ──────────── what changed since this morning
      ↓
   FIND GAME / BET
      ↓
   UNDERSTAND WHAT MATTERS  (Quick View, 30 seconds)
      ↓                      └─ optional: SHOW ADVANCED
   CHECK MY BET  (Bet Check)
      ↓
   FIND BETTER PRICE  /  IMPORTANT NEWS  /  COUNTERARGUMENT
      ↓
   SAVE / WATCH / PLACE
      ↓
   RETURN ────────────────────┐
      ↑                       │
      └── the next change ────┘
```

## What actually creates daily return behaviour

Ranked by evidential strength. **A product can be excellent and still churn if
it has no reason to be reopened.**

### 1. WHAT CHANGED — the strongest mechanic **(MVP)**
Information *decays*. A slate read at 9am is wrong by 4pm: lineups post, pitchers
get scratched, weather flips, prices move. This is the only feature whose value
is *inherently* time-bound, which is exactly what a daily habit needs.
The morning read creates the obligation to re-check. **This is why WHAT CHANGED
belongs on TODAY rather than in its own tab** — a tab is a destination you forget;
a band on the home screen is a reason to reload.

### 2. Price shopping before every bet **(MVP)**
The best-evidenced recurring bettor behaviour is multi-tab price comparison
across 5–10 books immediately before betting `[desk: CUSTOMER_PAIN.md]`. It
happens on *every* bet, not once a week. If we are faster than their tab-stack,
we enter the ritual — and rituals are what subscriptions rent.

### 3. Bet Check as a pre-commitment ritual **(MVP)**
Bettors already have a bet in mind. Attaching ourselves to the moment *before*
placing — the highest-anxiety, highest-attention moment in the workflow — is
worth more than being consulted during idle browsing.

### 4. CLV feedback after the close **(V1)**
Serious bettors check realised CLV after games close `[desk: CUSTOMER_PAIN.md]`.
This creates a *second* daily session, in the evening, and it is a process metric
the user controls — better for retention than profit, which is mostly variance.

### 5. Alerts pulling the user back **(V1)**
The only mechanic that initiates a return rather than waiting for one.
See Notification concepts.

## The churn risks to design against

| Risk | Evidence | Design response |
|---|---|---|
| **"I paid and there's nothing here"** | Our own output stamps all 15 games NO PLAY under a header of three zeros (VERIFIED) | No Play UX — never lead with a null |
| **Thin edge doesn't justify cost** | `[desk: CUSTOMER_PAIN.md]` | ROI/breakeven calculator; lead with price improvement, which is measurable |
| **Billing friction** | #1 complaint category-wide `[desk: APP_STORE.md]` | One-click in-app cancel; no card for free tier |
| **Unmet accuracy claims** | Every AI-projection app has "I lost money on this pick" reviews `[desk: APP_STORE.md]` | Make no accuracy claims at all |
| **Downswing despair** | Pikkit's red calendar (VERIFIED) | Lead with CLV, not profit |

---

# Navigation, hierarchy and density

## Information hierarchy — the universal rule

Every screen answers, in this order:

```
1  WHAT IS THIS?          identity — teams, bet, market
2  WHAT SHOULD I KNOW?    the verdict / findings, plain English
3  WHAT'S THE PRICE?      best available vs consensus
4  WHY?                   supporting and opposing factors
5  HOW DO YOU KNOW?       evidence, samples, method   ← Advanced
6  RAW DATA               tables and figures          ← Advanced
```

**Levels 5 and 6 are below the fold and behind a control on every page.** Our
current output inverts this — it opens with raw z-scores and value/normal/sample
triples before any interpretation (VERIFIED). That inversion is the single
biggest reason it reads as a debugging terminal.

## Data density rules

| Rule | Detail |
|---|---|
| **Quick View: ≤ 5 factors** | Truncation is a feature. Show the best five. |
| **Quick View: zero tables** | Our current page has 86 (VERIFIED). Quick View has none. |
| **One idea per line** | If a sentence needs a semicolon and a parenthetical, it is two findings. |
| **Numbers earn their place** | Prices always. Stats only in Advanced, always with sample. |
| **Whitespace is not waste** | A 30-second read needs room. Density is Advanced's job. |
| **Max one accent per screen** | Rithmm uses exactly one (VERIFIED) and looks the most premium in the set. |
| **No decoration without meaning** | No sparklines that don't encode something the user asked about. |

## Mobile-first requirements

**Mobile is the primary target.** Bettors research on phones, often minutes
before first pitch. Our current output has **one media query, and it only
switches colour scheme** — zero responsive breakpoints, 86 tables inside a fixed
1080px column (VERIFIED). It is unusable on a phone.

| Requirement | Spec |
|---|---|
| Design width | 375px first, then scale up |
| Nav | Bottom tab bar, 5 items, labels visible |
| Tables | **Never** at Quick depth. In Advanced, inside `overflow-x:auto` containers. Page body never scrolls horizontally. |
| Touch targets | ≥ 44px |
| Type | ≥ 16px body; never below 14px for content |
| Primary action | Reachable with a thumb — bottom third |
| Horizontal scrollers | Avoided for primary content; they hide things on phones |
| Performance | TODAY interactive in < 2s on 4G. A bettor 3 minutes from first pitch will not wait. |

## Desktop requirements

Desktop is the **Advanced and Odds surface** — where the Sharp and the Data Nerd
work, and where Unabated proves a desktop-only tool can be a real business.

- Max content width ~1200px; the odds grid may exceed it in its own scroller.
- Two-column Game page ≥ 1024px: Quick View left, Advanced right, both visible.
- Keyboard: `/` focuses Bet Check from anywhere. Real users of dense tools live
  on the keyboard.
- Dense tables are legitimate here, and only here.

---

# Evidence-label UX

**The most important correction to the current product.**

## The problem, measured

`demo_latest.html` contains **153 `UNPROVEN` badges** against 12 `CANDIDATE` and
5 `BLOCKED` (VERIFIED). A label applied to essentially everything conveys zero
information and trains the eye to skip it — the exact opposite of its intent.
The legend implies a three-way distinction; the distribution is 153/12/5.

## The rule: labels must be differential, not universal

**Most findings carry no badge at all.** Unremarkable evidence is the default and
needs no decoration. A label appears **only when it changes how the finding
should be read**, and should appear on well under 20% of items.

## The customer-facing evidence ladder

Five tiers, ascending. Plain English. Never internal vocabulary.

| Tier | Label | Means | Visual |
|---|---|---|---|
| 1 | **Observation** | We measured it. No claim it predicts anything. | no badge — this is the default |
| 2 | **Exploratory** | We are researching whether it matters. | subtle outline |
| 3 | **Historical support** | Held up in past data. Not forward-tested. | filled, neutral |
| 4 | **Forward testing** | Being tracked live, right now. | filled, accent |
| 5 | **Validated** | Survived forward testing at adequate sample. | filled, strong |

**Today, essentially everything is Tier 1**, and Tier 1 shows no badge. The
screen becomes calm and the rare Tier 3+ item becomes genuinely visible.

**Do not ship Tiers 4–5 until something legitimately reaches them.** An unused
top tier is honest; a prematurely used one is not.

## Where labels appear
Quick View: on the **DATA SUPPORT** summary only. Advanced: per finding.
Never a badge on every line at any depth.

---

# Sample-size warning UX

Sample-size skepticism at the moment of decision is a real opportunity —
**narrowed** by the finding that Pikkit already does it well in post-bet tracking
`[desk: FEATURES_TRUST.md]`. Our version must be better, not merely first.

## Three levels

```
● ○ ○   Weak       Too little data to conclude anything
● ● ○   Moderate   Suggestive, not conclusive
● ● ●   Strong     Enough data to take seriously
```

## Rules

1. **Every rate, split or streak carries its sample.** `66.7%` alone is
   forbidden; `66.7% (39 attempts)` is required.
   PlayerProps.ai displays `ACCURACY 66.7% (39)` (VERIFIED) — they disclose the
   sample and still headline the rate. **Disclosure is not enough; the framing
   must carry the caveat too.**
2. **Below threshold, the warning outranks the number.** Under ~30 observations,
   lead with the caveat:
   > *"7-for-15 — about two games' worth of at-bats. At this sample, a .467
   > average and a .150 average are both completely normal for the same hitter."*
3. **Never build a filter that selects on tiny samples.** No "hit in 9 of last
   10" screens. This is the mechanism behind Outlier's "Trends" and Rithmm's
   "Power Trends" `[desk: FEATURES_TRUST.md]` and we do not ship it, even though
   it demos well.
4. **Say what the sample can and cannot support**, rather than only flagging it
   as small.

---

# No Play UX

**Every competitor is incentivised to find you action. We are not.** But
"nothing here" must read as a service, not an outage.

## What not to do — from our own product

Header: `15 GAMES · 0 FLAGGED · 0 CANDIDATES · 0 NO MARKET`, and all 15 games
stamped `NO PLAY` (VERIFIED). Three zeros in the largest type reads as a failure.

## What to do

```
─────────────────────────────────────────────
TONIGHT
We checked all 15 games. Nothing clears the bar.

Here's what we looked at, and the closest calls:

  SD @ TB    Both starters strong (FIP 3.46 and
             3.42). Evenly matched — exactly the
             game whose outcome you cannot call.

  KC @ CLE   Starters close, teams close on run
             differential. No separation.

  PIT @ STL  ✓ BetRivers has PIT 1.5 points
             cheaper than the 11-book consensus.
             No prediction required.
─────────────────────────────────────────────
```

## Rules

1. **Never a blank page or a bare zero.** Show the work.
2. **State what was examined**, so the subscription visibly did something.
3. **"No play" is a verdict, not an absence.** Frame it with confidence: *"we
   checked, and the answer is no."*
4. **Price improvements survive a no-play night.** They require no prediction, so
   they are still actionable when nothing else is. This is precisely why price
   improvement must be Tier 1 in ranking — it is the floor of daily value.
5. **Never manufacture interest** to fill the page. Rithmm's *"Touts need you to
   bet every game"* framing (VERIFIED) is correct, and they already say it — our
   version has to be *demonstrated by the product*, not claimed in copy.

---

# Price-improvement UX

**The most important distinction in the entire product.**

| | Price improvement | Predictive EV |
|---|---|---|
| Claim | "The same bet is cheaper at another book" | "We know the true probability" |
| Requires a model | **No** | Yes |
| Verifiable by the customer | **Yes, in seconds** | No |
| Can we make it today | **Yes — EXISTS TODAY** | **No — model UNCALIBRATED** |

**Category evidence:** OddsJam's own guide treats a -110 → -140 move as "sharp
money" justifying a bet "even at low EV%"; Unabated markets a synthetic
consensus as "true EV" / "true edge" `[desk: FEATURES_TRUST.md]`. Both conflate
a market observation with a predictive claim. **This conflation is the category's
central intellectual dishonesty, and refusing it is our position.**

## Language rules — non-negotiable

**Always say:** "better price" · "cheaper" · "N points better than consensus" ·
"the same bet at a better number" · "no prediction required".

**Never say:** "+EV" · "edge" · "value" · "true line" · "beat the market" ·
"we project".

Our current output already gets this right (VERIFIED):
> *"betrivers has PIT at -110, which is 1.5 points cheaper than the 11-book
> consensus. No prediction required — it is the same bet at a better price."*

**Keep that sentence. It is the brand in one line.** Make it Tier 1 everywhere.

---

# Missing-data UX

Missing data is normal: no odds key, wind bearings unverified for 30/30 parks,
lineups not posted until ~3 hours out (all VERIFIED via `cli status`).

## Rules

1. **Name the gap; never fail silently.** *"Lineups not posted yet — typically
   about 3 hours before first pitch."*
2. **Say when it will be there.** A gap with a time is a plan; without one it is
   a bug.
3. **Never substitute a projection for a fact without labelling it.**
   "Projected lineup" and "confirmed lineup" are different, and the difference
   changes the bet.
4. **Degrade, don't collapse.** One failed source must never blank a page.
5. **Be explicit about known unknowns.** The wind case is a model of good
   practice already present in the repo: wind is collected but *not applied* until
   park bearings are verified. Say exactly that:
   > *"Wind is 12mph, but we haven't verified this park's orientation, so we're
   > not drawing a conclusion from it."*
   That sentence builds more trust than a confident wind adjustment would.

---

# News / event UX

**Speed is the product here.** A lineup scratch is worth more at 4:12pm than in
tomorrow's recap.

## Rules

1. **Event + market reaction together.** *"Judge is out. NYY moved -145 → -128
   across 9 books."* The pairing is the value; either half alone is commodity.
2. **Local time, always.** Our current output shows
   `generated 2026-08-28T09:15:47.555360+00:00 · times in UTC` (VERIFIED).
   Microsecond UTC is a machine's idea of a timestamp. Show "4:12pm ET".
3. **Attribute and link.** Source named, timestamped, linked out.
4. **Relevance tiers.** A scratched starter is not a bench swap.
5. **Never editorialise a rumour into a fact.** "Reported" and "confirmed" are
   different labels and must look different.

---

# Charts and tables

## Charts — restrained, and only where they beat a sentence

| Chart | Use | Rule |
|---|---|---|
| **Line movement** | Price over time | Y-axis in American odds, not implied %. Annotate events on the timeline. |
| **Book dispersion** | Spread across books | Dot plot, not a bar chart. Best price marked. |
| **CLV over time** | Personal record | Process metric, shown before profit. |
| **Recent form** | Last N games | **Always labelled with N.** Never a bare sparkline. |

**Forbidden:** confidence gauges/speedometers, "AI confidence" meters, any chart
implying precision we do not have, decorative sparklines encoding nothing.

**Note:** our current page has 85 `spark` elements (VERIFIED). Most should go.

## Tables

Advanced View only. Right-align numbers, tabular figures, monospace for figures
only. Sticky header row. Horizontally scrollable in their own container. Zebra
striping only above ~8 rows. **Never a table at Quick depth.**

---

# Notification concepts

**V1 · ENGINEERING REQUIRED.** The only mechanic that *initiates* a return.
Also the fastest way to get uninstalled — every notification must be one the user
would have wanted to be interrupted for.

| Notification | Trigger | Default |
|---|---|---|
| **Your bet's price moved** | Watched bet's price moves ≥ N points | **On** |
| **Better price available** | A book beats the price you logged | **On** |
| **Lineup change on a watched game** | Scratch or starter change | **On** |
| **Your game starts in 30 min** | Watched game | Off |
| **Tonight's slate is ready** | Daily digest | Off — opt-in only |

## Rules
1. **Watched things only.** Never notify about a game the user never touched.
2. **Actionable or silent.** "Something changed" without a consequence is spam.
3. **Per-type controls**, not one master switch.
4. **Hard cap** (~3/day default). Trust is spent per notification.
5. **Never a marketing push disguised as an alert.** Action Network draws
   complaints for unremovable marketing email `[desk: APP_STORE.md]`.

---

# Trust / transparency system

Zero of twelve competitors have an independently audited track record, and every
one implies performance `[desk: FEATURES_TRUST.md]`. Trust is the category's
largest structural vacancy — **but note that both PlayerProps.ai and Rithmm
already market honesty in copy (VERIFIED).** Our version must be *demonstrated
by the interface*, not asserted in marketing.

## The five commitments — visible in the product, not just the footer

1. **We never claim an edge we haven't demonstrated.**
   Until forward testing validates something, the product says *"no demonstrated
   betting edge."*
2. **Every number carries its sample.**
3. **We show what argues against your bet**, always, as a structural field.
4. **We separate "better price" from "we predict".**
   One is checkable in seconds; the other needs a model we do not have.
5. **We tell you when we don't know.**
   Unexplained line moves, unposted lineups, unverified park orientation.

## Mechanisms

| Mechanism | Detail | Timing |
|---|---|---|
| **Evidence ladder** | Five tiers, differential labelling | MVP |
| **Sample everywhere** | No rate without its N | MVP |
| **Methodology pages** | Plain-language, per feature | V1 |
| **"What we said then"** | Our past read shown beside the result in My Bets | V1 |
| **Public forward ledger** | Timestamped predictions, graded, wins *and* losses | LATER |
| **Transparent billing** | One-click in-app cancel, no dark patterns | MVP |

**The forward ledger is the eventual moat.** Nobody has one. It only becomes
credible with time, which is exactly what makes it defensible — a competitor
cannot buy two years of timestamped, graded public predictions.

## Anti-patterns — banned outright

Unaudited superlatives ("#1 Ranked", "Most Accurate") · headline accuracy over
small samples (`66.7% (39)`) · self-reported surveys as performance ("96% of
members say they've become profitable") · profit screenshots from power users ·
"Forget losing" · countdown timers · permanent discount marquees · streak
filters · any implication of guaranteed profit.

*(Every item above was observed on a live competitor page this session.)*

---

# Competitive differentiation — the honest summary

**What we cannot claim** (already taken, VERIFIED):
"we don't sell picks" · "we make you sharper" · "sometimes the best bet is no
bet" · "we're honest about uncertainty" · depth-on-demand as a promise.

**What we can actually own:**

1. **Our central claim is verifiable and theirs is not.** Price improvement can
   be checked against the books in ten seconds. "+46% EDGE" and "our model
   projects 58%" cannot be checked at all.
2. **Why the line moved.** Nobody narrates causation. Hardest to copy, and we
   have the ingredients.
3. **Structural progressive disclosure.** Legible at the top, inspectable
   underneath — versus simple-and-opaque (Props.Cash's ungrounded `A-`) or
   dense-and-illegible (Betstamp's grid, and our own current output).
4. **The counterargument as a permanent field**, not an occasional verdict.
5. **A fixed, inspectable answer skeleton** instead of an ephemeral chat log. A
   structure can be audited across nights; a conversation cannot.
6. **Honest billing** — attacking the loudest complaint in the category.

**The positioning sentence:**

> Everyone else sells you a number you cannot check.
> We show you what actually backs your bet — including the part that argues
> against it — and where to get it cheaper.

---
# Visual brand research — what the category actually looks like

Palettes recorded from live pages this session (VERIFIED):

| Product | Ground | Accent(s) | Display type |
|---|---|---|---|
| PlayerProps.ai | black-indigo | magenta → violet gradient | heavy condensed caps |
| OddsJam | near-black navy | electric blue + money green | large geometric sans |
| Outlier | true black | iridescent pastel gradient (mint/cream/peach/lavender) | rounded sans |
| Unabated | dark navy-charcoal | green | bold sans |
| Props.Cash | black | mint/spring green | very heavy condensed caps |
| Betstamp | deep navy | sky blue + orange | heavy condensed caps |
| Pikkit | near-black | periwinkle | rounded sans |
| Rithmm | near-black | **single** burnt orange | wide squarish grotesque + mono eyebrows |
| Action Network | **light** white/grey | green | news sans, photo-led |
| **Ours (current)** | sage "paper", light + dark | green + clay | **monospace only** |

## What is oversaturated

| Convention | Count | Verdict |
|---|---|---|
| **Dark ground** | 9 of 10 | Saturated — but it is also correct for evening phone use |
| **Green accent** | 4 | Saturated (money/positive semantics) |
| **Blue accent** | 3 | Saturated |
| **Gradients** | 3 | Saturated, and reads "AI product" |
| **Purple/magenta** | 2 | The most clichéd "AI casino tech" look. **Avoid entirely.** |
| **Heavy condensed caps** | 4 | Saturated — reads "sportsbook promo" |

## What is under-used

- **Light interfaces among tools.** Only Action Network is light, and it is a
  media brand, not a tool. Genuinely open space — with a real risk attached.
- **Warm accents.** Only Rithmm (orange). Amber/ochre is nearly vacant.
- **Editorial typography.** Nobody uses a serif. Nobody looks like writing.
- **Restraint.** Only Rithmm uses a single accent colour. Everyone else uses 2–4.
- **Whitespace.** The whole category is dense.

## The strategic conclusion

**Hue is exhausted; typography and density are not.** Nine of ten competitors are
dark, and dark is genuinely right for the usage moment (evening, phone, often
while watching a game). Trying to win on background colour is a losing game.

**Differentiate on how the page is set and how much it says**, not on what colour
it is. The product that looks like *careful writing* rather than *a trading
terminal* or *a sportsbook promo* is the one that will look different — because
nobody in this category looks like writing.

---

# Visual territory 1 — "The Broadsheet"

*A sports desk, not a trading desk.*

**Palette**

```
Ground        #FBFAF7  warm paper white
Surface       #FFFFFF
Ink           #16181C  near-black, warm
Muted         #5C6068
Rule          #E4E1DA  hairlines
Accent        #1B4D3E  deep forest — links, primary actions
Positive      #1B4D3E
Caution       #8A6D1F  ochre
Negative      #8C2F2A  brick, used sparingly
(dark mode: inverted to #14150F ground, cream ink, sage accent)
```

**Typography** — editorial serif for headlines and analytical prose
(Freight Text, Tiempos, Source Serif); humanist sans for labels and UI (Inter);
mono **only** for prices and figures. Generous measure (~65ch), real leading.

**UI personality** — a well-set newspaper analysis page. Calm, authoritative,
unhurried. It reads as *someone wrote this*.

**Cards** — mostly absent. Content is separated by hairline rules and whitespace,
not boxes. Cards only where something is genuinely a discrete object (a game).

**Icons** — minimal, thin-stroke, near-none. ✓ and ⚠ are typographic.

**Charts** — sparse, thin-line, no fills, direct labels, no gridlines. The FT/
Economist idiom.

**Why differentiated** — nothing in the category looks like this. It is the
strongest possible signal of "analysis, not gambling," and it makes the
long-form prose (our best existing asset) look like the point rather than
filler.

**Risk — and it is real.** Light + serif may read insufficiently sports-native
and insufficiently premium-tech to a mass-market bettor at 6pm on a phone. It
risks feeling like homework. It is also the hardest territory to execute well;
done badly it reads as a blog, not a product.

---

# Visual territory 2 — "Graphite Terminal"

*Bloomberg for people who don't work at Bloomberg.*

**Palette**

```
Ground        #0E1113  warm graphite  (NOT navy — navy is taken)
Surface       #16191C
Sunk          #0A0C0E
Ink           #E8EAED
Muted         #9BA1A8
Rule          #24282D
Accent        #5FD3E8  ice cyan — intelligence, links, focus
Opportunity   #E0A33C  restrained amber — price improvement, opportunity
Caution       #D8A657
Negative      #E06B60  used sparingly
```

Two accents only, with fixed jobs: **cyan = information, amber = opportunity.**
Amber appears almost exclusively on price improvement, which makes the most
valuable finding on the page also the most visually distinct.

**Typography** — humanist sans for prose (Inter, Söhne); a true mono for all
figures and prices (JetBrains Mono, Söhne Mono) with tabular alignment; small
mono uppercase eyebrows for section labels — **the Rithmm pairing, which was the
most premium thing I saw this session.**

**UI personality** — precise, quiet, fast. A professional instrument that has
been made legible. Confident enough not to shout.

**Cards** — low-contrast surfaces, 1px rules, generous internal padding, no
shadows, no glow. Restraint is the whole point.

**Icons** — thin-stroke, geometric, sparse.

**Charts** — thin lines on dark, single accent, direct labels, no gridlines,
no fills, no glow.

**Why differentiated** — it is dark, like most of the category, but it inverts
the two things the category gets wrong: it uses **warm graphite instead of navy**,
**one-to-two accents instead of gradients**, and — most importantly — it is
**spacious where competitors are dense**. It says "professional" without
condensed caps and without a single gradient.

**Risk** — dark + cyan is adjacent to Outlier's mint and to generic dev-tool
aesthetics. Differentiation depends almost entirely on execution discipline:
spacing, typography and restraint. A sloppy version of this looks like every
other dark SaaS.

---

# Visual territory 3 — "Night Game"

*The feeling of the ballpark at 7pm.*

**Palette**

```
Ground        #131215  warm near-black (a hint of aubergine, not blue)
Surface       #1C1A1F
Ink           #F2EFE9  warm white
Muted         #A09AA6
Accent        #F0A830  stadium-light amber — primary
Secondary     #6FA8A0  dusk teal — secondary information
Negative      #C4574A
```

**Typography** — a confident grotesque with real personality (GT America,
Founders Grotesk) for display; clean sans for body; mono for figures. Large,
tight headlines — but **sentence case, never condensed all-caps**.

**UI personality** — warm, atmospheric, sports-native, a little aggressive. Made
by people who watch the games.

**Cards** — richer surfaces, subtle warm gradients (very restrained), team colour
used as a thin accent edge on game cards only.

**Icons** — solid, rounded, slightly chunky. More character than territories 1–2.

**Charts** — warm palette, slightly heavier strokes, more willing to be
expressive.

**Photography** — selective, high-quality, atmospheric (stadium lights, dusk).
The only territory that uses imagery at all.

**Why differentiated** — warm dark is genuinely vacant; the entire category is
cold (navy/black/blue/purple). It is the most emotionally sports-native option
and the most likely to be *liked* by a mass-market bettor.

**Risk** — warmth plus amber plus atmosphere is the closest of the three to
sportsbook marketing, which is exactly the association we are trying to escape.
It needs constant discipline to stay on the analytical side of the line.

---

# Recommended visual territory

## Territory 2 — "Graphite Terminal" — with territory 1's typographic discipline

**Rationale, grounded:**

1. **Dark is correct for the usage moment**, not just conventional. The product
   is used in the evening, on a phone, often with a game on. Light-on-dark is
   the right call for that context, and Action Network — the one light
   competitor — is a media brand read in daylight, not a pre-bet tool.

2. **Hue cannot differentiate us; typography and density can.** Nine of ten
   competitors are dark. Winning on background colour is not available. What is
   available is being the only product in the category that is **spacious,
   well-set, and legible** — which is precisely the fix the current product needs
   anyway.

3. **The amber-for-opportunity rule solves a product problem with a visual
   mechanism.** Reserving one colour almost exclusively for price improvement
   makes the most valuable, most verifiable finding the most visually salient
   thing on the page — structurally fixing the ranking failure documented earlier.

4. **The mono-eyebrow + sans-prose pairing was empirically the most premium thing
   I saw** (Rithmm, VERIFIED), and it lets us keep monospace for figures — where
   it genuinely helps with column alignment — while removing it from prose, where
   it currently destroys scanability.

5. **It preserves what is already good.** The current product's restraint and
   sobriety are real assets. This territory keeps that character and fixes the
   legibility, rather than discarding a correct instinct.

**Adopt from Territory 1:** the editorial typographic discipline — real measure,
real leading, hairline rules instead of boxes, prose that looks written.

**Adopt from Territory 3:** warmth in the neutrals. Graphite, not navy. This is
what keeps it from reading as a cold dev tool.

**Explicitly reject:** gradients of any kind · purple/magenta · condensed
all-caps display type · glow effects · more than two accent colours.

## Light mode
Ship both. Light mode is not an afterthought — it is the desktop daytime
research mode, and it is where the Broadsheet character can come forward. The
current product already implements both light and dark via
`prefers-color-scheme` (VERIFIED); keep that, and add an explicit user override.

---

# Brand-name candidates

36 candidates generated across six territories; full list, rationale and
collision notes in `research/desk/NAMES.md`. **No formal trademark clearance was
performed.** DNS/whois results are signals only.

## Territory samples

**Sports intelligence:** Analyst · The Desk · Scout Room · Field Note
**Market intelligence:** Consensus Room · Bookwatch · Market Read · Nine Books
**Signal / information:** Signal Desk · Priors · Counterpoint · The Read
**Line / price:** Closing · Best Number · Points Better · The Number
**Premium abstract:** Fulcrum · Sable · Verity · Keystone · Ledger
**Bold consumer:** No Fluff · Before You Bet · Check First · Cold Read

---

# Top five names

| # | Name | Why | Main risk |
|---|---|---|---|
| 1 | **Fulcrum** | The leverage point where a bet is decided. Premium, abstract, sport-agnostic, works for MLB and soccer equally. Short, spellable, pronounceable. | Crowded generic-SaaS word — unrelated companies in field data, manufacturing, litigation support. `.com` taken. |
| 2 | **Signal Desk** | Signal-vs-noise plus a trading-desk register. Matches the skeptical, professional tone precisely. Multi-sport, and "Desk" implies people and judgment, not just an algorithm. | Several small unrelated "SignalDesk" companies exist. Two words. Domain status unclear. |
| 3 | **Consensus Room** | Strong market-intelligence framing, and "consensus" is already core product vocabulary (multi-book consensus). No betting collision found. | Not deep-checked for domain/App Store. Two words, less punchy alone. |
| 4 | **Bookwatch** | Speaks the audience's own language — "book" = sportsbook — and implies constant vigilance, which is exactly what What Changed does. One word, memorable. | Direct App Store name collision with an unrelated book-summary app. |
| 5 | **Counterpoint** | The counterargument is our signature structural feature; the name *is* the differentiator. Sport-agnostic, premium, and no betting collision surfaced. | Long-ish; "counterpoint" has music/opinion-column associations. Not deep-collision-checked. |

## Names to actively avoid

| Name | Reason |
|---|---|
| **Trueline / True Line** | Betstamp uses "THE TRUE LINE" as its eyebrow (VERIFIED this session), *and* a live P2P betting app uses the name |
| **Hammer** | Collides with The Hammer Betting Network and Hammer Wagers — and "hammer this" is exactly the tout language we ban |
| **Meridian** | MeridianBet is a real licensed sportsbook brand |
| **Cadence** | Cadence Design Systems (NASDAQ) is litigious |
| **Vantage** | Contested in finance/trading, including a spread-betting broker |
| Anything with **AI**, **GPT**, **Picks**, **Props**, **Bot** | Traps us in a category, a sport, or a technology that will date |

---

# Domain / collision notes

**Method:** DNS/whois signal checks plus web search. **Not a trademark search.**
An unregistered domain is weak evidence of availability; a registered one is
strong evidence of unavailability. Before committing to any name, commission a
proper clearance search — this section does not substitute for one.

- Most one-word `.com`s in this space are long since taken. Expect to buy, use a
  two-word `.com`, or take a modern TLD.
- **Prefer a `.com` you can own outright over a clever TLD.** `playerprops.ai`,
  `outlier.bet` and `props.cash` all took alternative TLDs, and all three suffer
  the same tax: the domain must always be said in full, and typing the `.com`
  reaches someone else.
- **The App Store is the binding constraint, not the domain.** App names must be
  globally unique on iOS. Check the App Store *before* buying anything.
- Test every finalist by **saying it aloud on a podcast** and by **spelling it
  over the phone**. If either is hard, drop it.

---

# Tagline candidates

**Recommended primary:**

> ### Everything that matters before you bet.

It states the promise (completeness), implies the moment (pre-bet), makes no
performance claim, and works across every sport. It is also the only one of the
candidates that survives regulatory scrutiny unchanged.

**Strong alternatives**

| Tagline | Note |
|---|---|
| **Know what backs your bet.** | Best short form. "Backs" is sports-native and evidentially precise. |
| **Research the bet before you make it.** | Most literal, most explanatory — good for paid acquisition. |
| **Stop betting with half the story.** | Most aggressive. Names the pain. Slight negativity risk. |
| **The case for and against.** | Uniquely ours — no competitor shows the counterargument structurally. |
| **Check before you bet.** | Shortest, most memorable, most repeatable. Ritual-forming. |

**Rejected, with reasons:** "Your sports betting intelligence layer" — "layer" is
B2B SaaS language a bettor will not use. Anything with "edge", "value", "sharp"
or "win" — all are either taken, jargon, or imply performance.

---

# Tone of voice

**We sound like a sharp analyst friend who respects you enough to tell you when
you're wrong.** Confident, plainspoken, specific, and willing to say "I don't
know."

## We say / we never say

| We say | We never say |
|---|---|
| "The same bet at a better price." | "+EV" · "value" · "edge" |
| "We checked, and nothing clears the bar." | "No plays today" (as an empty state) |
| "15 at-bats is about two games — it tells you almost nothing." | "Trends suggest…" |
| "The price has already moved against you." | "Lock" · "hammer" · "free money" |
| "We don't know why this line moved." | An invented explanation |
| "No demonstrated betting edge yet." | "Our model projects…" (while uncalibrated) |
| "Wind is 12mph, but we haven't verified this park's orientation." | A confident wind adjustment |

**Never, under any circumstances:** guarantee or imply profit · use "lock",
"guaranteed", "can't lose", "free money" · display an accuracy figure over a
small sample · use urgency or scarcity pressure · use hype emoji (🔥💰🚀).

**Adopt Rithmm's device wholesale:** publish an internal **NEVER SAYS** list and
enforce it in code review of copy. Their version (VERIFIED) bans hype *and*
jargon — *"Based on multidimensional predictive analysis…"* is on their banned
list, which is a genuinely sophisticated move. Ours must ban engineering
vocabulary the same way.

## Register by surface
Marketing — confident, direct, a little aggressive. Product — calm, plain,
precise. Errors — honest and specific, never cute. Money/billing — maximally
plain. No jokes anywhere near a price.

---
# Pricing-page UX

## Where the market actually sits (VERIFIED / `[desk: PRICING.md]`)

| Band | Monthly | Products |
|---|---|---|
| Budget | $9.99–19.99 | LineMate, Props.Cash ($19.99), Outlier entry ($19.99) |
| **Core (most crowded)** | **$29.99–49.99** | Rithmm ($29.99/$49.99), Outlier ($29.99), Juice Reel |
| Power user | $49.99–99.99 | PlayerProps.ai (~$49/mo equivalent), Rithmm Premium ($99.99) |
| Professional | $199–399 | OddsJam Gold (~$199.99) |
| Enterprise | $249–1000+ | Betstamp ($249/mo), OddsJam Platinum, Action LABS |

Directly verified this session: PlayerProps.ai **Week Pass $20**, **6-Month VIP
$295** ("pay 5, get 1 free", framed as **$1.62/day**), Annual "Save 30%".

## Assessment of the pricing hypothesis

The hypothesis was ~$29.99/mo single sport, ~$49.99–59.99/mo all sports,
~$299/$499 annual.

**The price *levels* are well validated.** $29.99 and $49.99 are exactly where
Rithmm and Outlier sit; $299–499 annual is validated by Outlier, Pikkit and
PlayerProps.ai.

**The single-sport *axis* is not.** Only Props.Cash sells a standalone sport SKU,
and as a flat season pass rather than a recurring tier `[desk: PRICING.md]`.
Nearly the entire category packages by **feature depth**, not by sport.

**Recommendation — and this is a change from the hypothesis:**

> **Do not ship a single-sport / all-sports split at launch.** At launch there is
> only MLB. Two SKUs for one sport is a decision the customer cannot act on and a
> promise ("all sports") we cannot yet keep. Ship **one price** for the product
> that exists, and introduce the multi-sport tier when a second sport actually
> ships — at which point existing subscribers should be grandfathered, which is
> also excellent retention.

The per-sport axis remains a genuine differentiation opportunity **later**, when
there is more than one sport to choose between.

## Recommended structure

```
FREE                      $0        no card, forever
WEEK PASS                 $20       one-off, no auto-renew
STANDARD                  $29/mo    or $290/yr (2 months free)
[LATER] ALL SPORTS        $49/mo    or $490/yr  — only when sport #2 ships
[LATER] PRO / RESEARCH    $99/mo    — only when there is real pro depth
```

## Pricing-page rules

1. **Annual is the default toggle.** Nobody in the category defaults to annual
   `[desk: PRICING.md]` — a free differentiator and better cash flow.
2. **Show the per-day price.** PlayerProps.ai's `$1.62 per day` (VERIFIED) makes
   a $295 commitment feel small. Adopt it — honestly, not as a trick.
3. **Ship the breakeven calculator. Nobody has one** `[desk: PRICING.md]`:
   > *"At $50 a bet and 20 bets a month, a 1.5-point better price is worth about
   > $X/month. This plan costs $29."*
   For a product whose core value is price improvement, this is both the most
   honest and the most persuasive thing on the page. **It is also a commitment
   device** — it says our value is arithmetic, not prophecy.
4. **State exactly what is in each tier**, including what is *not*. Outlier and
   BetQL both draw bait-and-switch complaints for feature-starved entry tiers
   `[desk: APP_STORE.md]`.
5. **Cancellation policy stated on the pricing page**, in plain language, with
   the one-click in-app path named. Billing friction is the category's #1
   complaint; making the cancel path a *selling point* is unoccupied ground.
6. **No countdown timers. No permanent discount marquees.** Props.Cash runs a
   perpetual "40% OFF" banner (VERIFIED); it teaches customers the price is fake.
7. **No fake anchoring.** A "MOST POPULAR" badge is acceptable if it is true.

---

# Free vs paid experience

**Free must deliver real, repeatable value.** Pikkit's free-forever tracker with
a paid intelligence layer is the best funnel shape in the category (VERIFIED),
and PlayerProps.ai's total login wall with zero free value is the worst.

| Surface | Free | Paid |
|---|---|---|
| **TODAY** | Full game list, start times, one market price | All prices, all findings, WHAT CHANGED |
| **Game — Quick View** | **Full Quick View on 1 game/day** | Every game |
| **Game — Advanced** | Locked (visible, with a real preview) | Full |
| **BET CHECK** | **3 checks/day** | Unlimited |
| **ODDS** | Consensus only | Best price + book names + dispersion |
| **WHAT CHANGED** | Headline count only ("4 updates today") | Full timeline |
| **MY BETS** | **Free forever, unlimited** | + CLV, + "what we said then" |
| **Alerts** | None | Full |

## Rules

1. **No credit card for free.** Ever.
2. **Free is not a demo — it is a product.** Bet tracking free forever is the
   habit hook; the intelligence layer is the upsell. This is Pikkit's shape and
   it works.
3. **Free must include the aha.** One full Quick View and three Bet Checks per
   day means every new user *experiences* the core value, repeatedly, before
   paying. This is the single most important funnel decision in the document,
   and it is the direct inverse of PlayerProps.ai's approach.
4. **Locked features are shown, not hidden**, with a genuine preview — a blurred
   or truncated real result, never a marketing placeholder.

---

# Onboarding

**Goal: reach the aha in under 60 seconds, before any account is required.**

```
1  LAND                No signup wall. TODAY renders immediately.
                       ↓
2  PICK A TEAM         "Which teams do you follow?"  (optional, skippable)
                       Personalises TODAY. Not required.
                       ↓
3  FIRST BET CHECK     A pre-filled example from tonight's real slate:
                       "Try it — Rays ML -132"
                       ↓
4  THE AHA             They see: 4 factors for, 2 against, and a
                       better price at another book.
                       ↓
5  SOFT ACCOUNT        "Save this? Create an account" — only after value.
                       ↓
6  FREE TIER           3 Bet Checks/day, 1 full game, free tracking.
                       ↓
7  UPGRADE             Prompted at the limit, in context, never by interruption.
```

## Rules

1. **No account before value.** Rithmm and Unabated both let you in ("Start for
   Free"); PlayerProps.ai does not, and shows empty skeletons to logged-out users
   (VERIFIED). Be the former.
2. **The aha is Bet Check finding a better price.** It is instant, concrete,
   verifiable by the user against their own sportsbook app, and requires no trust
   in us at all. That last property is what makes it the right aha for a category
   with a trust deficit.
3. **Skippable personalisation.** Never block on preferences.
4. **Onboard into tonight's real slate**, not a canned demo. Real data is the
   proof.
5. **No tutorial carousel.** Nobody reads them.

---

# Conversion funnel

```
ACQUISITION    SEO (game pages, "why did X line move", education)
               + content + App Store
                    ↓
ACTIVATION     First Bet Check completed          ← the metric that matters
                    ↓
HABIT          3 sessions in first week
               (driven by WHAT CHANGED + price shopping)
                    ↓
CONVERSION     Hits free limit on a night they care about
                    ↓
RETENTION      Daily WHAT CHANGED + CLV feedback loop
                    ↓
EXPANSION      All-sports tier when sport #2 ships
```

**North-star activation metric:** *first Bet Check completed where a better price
was found.* It is the moment the product proves itself with a claim the user can
verify independently.

**SEO note:** Action Network's content moat is the category's most durable
acquisition asset (VERIFIED — largest scale in the set). Public, indexable
per-game pages showing Quick View with a soft gate is the highest-leverage
acquisition investment available, and it doubles as free-tier value.

---

# Product roadmap implications

## MVP customer-facing scope

**Everything here is ENGINEERING REQUIRED as an application, even where the
underlying analysis EXISTS TODAY. There is currently no app to put it in.**

| # | Item | Capability of the *content* |
|---|---|---|
| 1 | **An actual web application** — routes, URLs, server, deploy | ENGINEERING REQUIRED — none of this exists |
| 2 | **TODAY** — slate, findings ranked by actionability, WHAT CHANGED band | content EXISTS TODAY |
| 3 | **GAME — Quick View** | content EXISTS TODAY |
| 4 | **GAME — Advanced View** (blocks that have data; hide the rest) | partly EXISTS TODAY |
| 5 | **BET CHECK** with the full fixed skeleton | analysis EXISTS TODAY; parser + layout REQUIRED |
| 6 | **ODDS board** — best price, consensus, dispersion | EXISTS TODAY |
| 7 | **Responsive mobile layout** | ENGINEERING REQUIRED — currently zero breakpoints |
| 8 | **Evidence ladder + sample-size UX** | ENGINEERING REQUIRED |
| 9 | **No Play UX** | ENGINEERING REQUIRED |
| 10 | **Accounts, billing, one-click cancel** | ENGINEERING REQUIRED — none exist |
| 11 | **Pricing page + breakeven calculator** | ENGINEERING REQUIRED |
| 12 | **Free tier limits** | ENGINEERING REQUIRED |

**Hard prerequisites, from the repo (VERIFIED via `cli status`):**
- `ODDS_API_KEY` is not configured. **Without live odds there is no price
  improvement, and without price improvement there is no MVP.** This is the
  single highest-priority unblock.
- The historical store is empty — `cli brief` exits with "historical store is
  empty — run `ingest` first."
- The probability model is UNCALIBRATED. **The MVP must not display a win
  probability.**

## V1 post-MVP scope

MY BETS with CLV · WHY DID THIS LINE MOVE · alerts · Bet Debunker free-text ·
Research/Methodology pages · "what we said then" · saved games/watchlist ·
public game pages for SEO.

## LATER

Props · a second sport · all-sports tier · Pro/Research tier · public forward
ledger · sportsbook auto-sync · community features.

## Things explicitly NOT to build yet

| Do not build | Why |
|---|---|
| **Any win-probability display** | The model is UNCALIBRATED. Showing a number we cannot defend destroys the entire trust position in one screen. |
| **Anything labelled "+EV" or "edge"** | We cannot substantiate it, and refusing to is the brand. |
| **Props** | No prop data exists. Do not put it in the nav. |
| **A chat interface** | Rithmm's Scout is a mature version of this and chat is unauditable. Our structured skeleton is the differentiator. Do not chase it. |
| **Sportsbook auto-sync** | Recurring sync-failure complaints across three competitors. Manual entry first. |
| **Multi-sport** | One sport done excellently beats four done shallowly. |
| **A "confidence meter" / AI score gauge** | Implies precision we do not have. |
| **Streak / hit-rate filters** | The tiny-sample mechanism we are positioned against. |
| **Community / chat** | Real retention value (PlayerProps calls it their most-prized feature) but a large moderation and compliance burden. Not MVP. |
| **The Ranker as a customer feature** | Engine 2 is `None`. It is currently an honesty artifact, not a product. |
| **A native app** | Ship a responsive web app first. Unabated proves web-first is viable. |

---

# Engineering handoff

**What a coding agent needs to know to implement this.**

## Start here — the single most important fact

**There is no application.** The repo is a Python **static-site generator with no
site**: no web framework, no server, no `package.json`/`pyproject.toml`, no
Dockerfile, no routes, no URLs. Pages open from `file://` with zero script tags,
and that is *test-enforced*. Standard library only.

**Building the customer product is a new application that consumes the existing
analysis** — not a redesign of the existing HTML, and not a deployment task.

## Architecture recommendation

```
┌─────────────────────────────────────────────────────┐
│  EXISTING (do not rewrite)                          │
│  src/pipeline/briefing.py  src/detect/dossier.py    │
│  src/analysis/*  src/report/*  src/evolab/*         │
│  Python 3.11+, standard library only                │
└──────────────────────┬──────────────────────────────┘
                       │  NEW: a JSON boundary
                       ▼
┌─────────────────────────────────────────────────────┐
│  NEW: API layer                                     │
│  Serialise dossiers/findings/odds to JSON.          │
│  Do NOT render HTML here.                           │
└──────────────────────┬──────────────────────────────┘
                       ▼
┌─────────────────────────────────────────────────────┐
│  NEW: customer web app (responsive, mobile-first)   │
│  TODAY · GAME (Quick/Advanced) · BET CHECK ·        │
│  ODDS · MY BETS                                     │
└─────────────────────────────────────────────────────┘
┌─────────────────────────────────────────────────────┐
│  NEW: internal admin app — separate URL + auth      │
│  Evolution Lab, health, ledger, audits              │
└─────────────────────────────────────────────────────┘
```

**The critical first step is a JSON boundary.** Today the analysis and its HTML
rendering are fused in `src/report/*`. Separating "what we know" from "how it
looks" is the prerequisite for everything in this document. Do that before
writing any UI.

## Non-negotiable implementation rules

1. **Quick View is the default. Advanced appends beneath it, never replaces it.**
   This is the core interaction; get it right before anything else.
2. **Never display a win probability** while the model is UNCALIBRATED.
3. **Never label a price difference "EV" or "edge".**
4. **Every rate ships with its sample size.** Enforce it at the component level —
   make the sample a *required prop* on any component rendering a rate, so it is
   impossible to ship a bare percentage.
5. **Evidence badges are differential**, appearing on well under 20% of items.
   Do not port the current 153-badge behaviour.
6. **Ranking is by actionability tier, not z-score.** z-scores are never
   rendered to customers.
7. **No tables in Quick View.** In Advanced, tables live in `overflow-x:auto`
   containers; the page body never scrolls horizontally.
8. **All times in the user's local timezone.** No UTC, no microseconds.
9. **The counterargument field is structurally required** and cannot be empty by
   omission — render "No significant counterarguments found" instead.
10. **Customer product and research lab never share an evidence standard.**

## Known data constraints — design around these, do not assume they are fixed

| Constraint | Status |
|---|---|
| `ODDS_API_KEY` | Not configured. **Blocks the MVP's core value.** Highest priority. |
| Historical store | Empty; `ingest` must run before `brief` works |
| Probability model | UNCALIBRATED — no edge claims available |
| Park orientation | 0/30 verified — wind collected but **not** applied |
| Pitch mix / velocity / xwOBA / xFIP | **Not ingested.** Do not design Advanced View as if present. |
| Props | Not ingested at all |
| Dependencies | Standard library only — a deliberate constraint; check before adding any |

## Verification checklist for the implementing agent

- [ ] Quick View for a real game is understandable in 30 seconds by someone who
      does not know what FIP is.
- [ ] Advanced View expands beneath Quick View; Quick View remains visible.
- [ ] Bet Check renders all ten skeleton fields for a real bet string.
- [ ] The counterargument section is present even when empty.
- [ ] No win probability appears anywhere.
- [ ] No "+EV", "edge" or "value" appears in customer-facing copy — grep for it.
- [ ] Grep the rendered output: fewer than 20% of findings carry an evidence badge.
- [ ] Every displayed rate has a visible sample size.
- [ ] At 375px, no horizontal page scroll on any screen.
- [ ] A no-play night renders a service, not three zeros.
- [ ] All timestamps are local, with no microseconds.
- [ ] The pricing page states the cancellation path in plain language.

---

# Document status and honest limitations

**What is VERIFIED:** nine competitors inspected live in Chrome on 2026-08-31
(PlayerProps.ai, Rithmm, OddsJam, Outlier, Unabated, Action Network, Props.Cash,
Betstamp, Pikkit), with quoted copy and recorded palettes. The current product
measured directly from `artifacts/demo_latest.html` in a read-only clone. Repo
capability confirmed via `python3 -m src.cli status` and `--help`.

**Known gaps — stated rather than papered over:**

1. **No paywalled interiors were seen.** No accounts were created and no paywall
   was bypassed. Every claim about logged-in product depth is `[desk]` or
   INFERRED. **This is the largest gap in the research** — the actual in-product
   UX of OddsJam, Rithmm and PlayerProps.ai remains unobserved.
2. **`briefing.html` was never regenerated live.** It requires an ingested
   historical store and a paid odds key. The committed `demo_latest.html`
   (2026-08-28, 15 games, odds-bearing) was analysed instead. Conclusions about
   the *current* product's structure are sound; conclusions about today's live
   content are not available.
3. **Reddit was unreachable** by the text-research agent, so customer-pain
   findings are second-hand from search aggregation `[desk: CUSTOMER_PAIN.md]`.
   **A manual pass through r/sportsbook for cancellation stories and AI-pick
   distrust would materially strengthen the persona and churn sections**, and I
   have a working browser that could do it — it was not done in this pass.
4. **Mobile emulation did not render** in the browser pane, so mobile competitor
   layouts were not visually captured. Our own product's mobile failure is
   VERIFIED by CSS inspection (one media query, zero breakpoints), not by
   screenshot.
5. **Tier 2 competitors** (BetQL, LineMate, Juice Reel) were not visually
   inspected.
6. **No trademark clearance was performed** on any name.
7. **Screenshots were not persisted to disk.** Competitor pages were captured and
   analysed live in-session; the quoted copy, palettes and layout descriptions in
   this document are the durable record of what was seen. They are accurate, but
   they are not independently re-checkable without revisiting the sites.

**Nothing in the engineering repository was modified.** The reference clone at
`reference-repo/` has had its git remote removed; all CLI execution happened in a
disposable scratchpad copy.
