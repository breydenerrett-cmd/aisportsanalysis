# Customer Personas

Built 2026-08-31 from `CUSTOMER_PAIN.md` (App Store review corpus, ~1,700
reviews across 9 products) and the three segment docs. **Evidence base is
thin by the source docs' own admission**: Reddit — the channel that normally
carries "here's my workflow" posts — was unreachable all session; the entire
"10-tab problem" section of `CUSTOMER_PAIN.md` rests on **4 independent
quotes**. Every field below is tagged:

- **[EVIDENCE]** — traces directly to a dated quote or a verified matrix/price
  cell.
- **[INFERENCE]** — a reasonable construction from evidence but not itself
  observed; flagged so it is never mistaken for research.
- **UNKNOWN** — no evidence found either way; not guessed.

Willingness-to-pay anchors to the verified bands in `PRICING.md`, never
invented.

---

## 1. Casual serious bettor

*Bets regularly, cares about winning, not a spreadsheet person.*

- **Pain [EVIDENCE]**: picks that feel "no better than a coin flip" — the
  single most standardized complaint phrase in the corpus, independently used
  across Rithmm, Outlier, BetQL, and PlayerProps.ai reviews.
- **Current workflow [INFERENCE]**: some mix of ESPN/free stats plus one paid
  picks app; the Action Network reviewer who wrote "the avg better could be
  more profitable using the espn app" implies this exact comparison shopping
  between paid and free.
- **Tools used [EVIDENCE]**: Action Network, Rithmm Core, BetQL Premium/Pro —
  the entry-level tiers of the mid-market products.
- **Time spent [INFERENCE]**: UNKNOWN precisely; the "8 websites, 1-2 hours"
  Rithmm quote describes a *pre-consolidation* workflow this persona is
  trying to escape, not a measured average.
- **Most valuable feature [EVIDENCE]**: consolidation — "it would take me 1-2
  hours and now it takes 2 seconds" (Rithmm review) is the clearest
  articulated value in the whole corpus for this persona type.
- **Willingness to pay [EVIDENCE, anchored]**: $20–35/mo band — matches
  Rithmm Core ($29.99), BetQL Pro/VIP ($24.99–29.99), Outlier Premium+
  ($29.99), the thickest band in the market.
- **Likely tier**: our proposed ONE SPORT $29.99/mo.
- **Acquisition channel [INFERENCE]**: App Store search/browse and word of
  mouth; no direct evidence of paid-acquisition channels for this segment was
  found.
- **Churn reason [EVIDENCE]**: "picks not beating chance," repeated across
  Rithmm, Outlier, BetQL, Action Network, PlayerProps.ai reviews — the
  #2-ranked cancellation driver in `CUSTOMER_PAIN.md`'s cross-product
  synthesis, just behind billing/cancellation friction.

---

## 2. Daily bettor

*High-frequency, volume-driven, treats betting as a routine.*

- **Pain [INFERENCE]**: needs a fast daily read across many games; no direct
  quote in the corpus separates "daily" from "casual serious" bettors by
  stated frequency — this segmentation is constructed from the products'
  own daily-cadence framing (BetQL's daily articles, Action Network's daily
  picks tab), not from a bettor describing their own frequency.
- **Current workflow [INFERENCE]**: opens a picks app most days of the season;
  UNKNOWN whether this is a distinct behavioral cluster from persona 1 in the
  actual customer base, given the evidence gap.
- **Tools used [EVIDENCE]**: BetQL (daily expert articles, "Most Popular
  Right Now" crowd-activity signal), Action Network (Pick & Game Alerts on
  the free tier).
- **Time spent [INFERENCE]**: likely under 15 minutes/day given the products'
  own "quick daily check" framing (BetQL's "one-stop shop," Action Network's
  "More edges. Less noise.") — not measured.
- **Most valuable feature [EVIDENCE]**: alerts and daily digest content —
  Action Network's free tier already includes Pick & Game Alerts, which is
  the feature this persona would most directly use.
- **Willingness to pay [EVIDENCE, anchored]**: $20–35/mo, same band as
  persona 1; Action Network PRO Monthly ($24.99) or its $14.99/week pass are
  the closest observed price points for a frequency-driven user who may not
  want a long commitment.
- **Likely tier**: our proposed ONE SPORT $29.99/mo, or a week-pass
  equivalent if we build one (per `PRICING.md`, week passes are a minority
  pattern — only 3 of 17 products offer one, so this is not an obligation).
- **Acquisition channel**: UNKNOWN — no evidence distinguishes this
  persona's acquisition path from persona 1's.
- **Churn reason [EVIDENCE]**: sync/reliability breakage and disruptive
  redesigns — Action Network's BetSync complaints and Props.Cash's October
  2025 relayout wave are the clearest evidence of a routine-dependent user
  churning over friction rather than accuracy.

---

## 3. Prop-heavy bettor

*Player props specifically, not game lines.*

- **Pain [EVIDENCE]**: no sample-size warning anywhere in the two prop tools
  inspected at the code level — Props.Cash's production JS has zero hits for
  "sample size," "disclaimer," or "denominator"; LineMate ships a filter
  category literally titled "100% Hit Rates" gated by a 3-game minimum. This
  persona is the one most directly exposed to the "100% Hit Rate on n=3"
  problem.
- **Current workflow [EVIDENCE]**: slices hit-rate tables by rolling windows
  (L3/L5/L10/L20, custom range) — this is the actual UI both Props.Cash and
  LineMate expose, so it is a direct description of the workflow, not an
  inference.
- **Tools used [EVIDENCE]**: Props.Cash ($19.99/mo), LineMate ($14.99/mo web,
  conflicting App Store SKUs $9.99–14.99), PropsBot.ai ($49.99/mo) for the
  more analysis-heavy end of this persona.
- **Time spent [INFERENCE]**: UNKNOWN; no quote measures session length for
  prop research specifically.
- **Most valuable feature [EVIDENCE]**: rolling-window filtering (BvP/DvP,
  home/away, custom range) — the entire product surface of both Props.Cash
  and LineMate is built around this, and a 5★ Props.Cash reviewer's feature
  request (more advanced NBA efficiency stats: PPP, pace-adjusted per-100
  metrics) shows active engagement with exactly this kind of slicing.
- **Willingness to pay [EVIDENCE, anchored]**: $10–35/mo — Props.Cash and
  LineMate sit at the low end ($10–20), PropsBot.ai at $49.99 for the
  AI-scored version; this persona spans a wider band than most.
- **Likely tier**: our proposed ONE SPORT $29.99/mo, positioned specifically
  against the sample-size-transparency gap (`PRICING.md`'s evidenced
  whitespace argument).
- **Acquisition channel [INFERENCE]**: content creators and prop-betting
  social content plausibly drive this segment (Props.Cash's own customer
  type is explicitly listed as including "content creators" in
  `COMPETITOR_MATRIX.csv`), but no direct acquisition-channel quote exists.
- **Churn reason [EVIDENCE]**: redesign-driven — Props.Cash's Oct 2025 UI
  change produced "25+ nearly-identical 1★ reviews" and an explicit
  cancellation wave, the single clearest churn-by-friction example in the
  entire corpus for this persona type.

---

## 4. Data nerd

*Wants the model builder, the backtest, the raw numbers — not a "trust me" pick.*

- **Pain [EVIDENCE]**: wants to verify a model before trusting it live — the
  Rithmm 5★ review explicitly frames this as differentiation: "this app goes
  the extra mile and backtests the models you create... In an industry where
  so much information comes in 'half-truths,' Rithmm stands well above the
  pack."
- **Current workflow [INFERENCE]**: builds or configures custom models where
  the tool allows it (Rithmm's model-builder is the only confirmed instance
  of this in the segment); otherwise likely maintains their own spreadsheet,
  consistent with PropsBot.ai's own positioning language ("replace manual
  spreadsheet analysis") though that phrase describes PropsBot's target
  customer, not a quote from an actual user.
- **Tools used [EVIDENCE]**: Rithmm (model-builder, all tiers), PropsBot.ai
  (self-serve sortable/date-rangeable track-record dashboard) for the users
  who want to audit a claim themselves rather than take it on faith.
- **Time spent**: UNKNOWN.
- **Most valuable feature [EVIDENCE]**: verifiable backtesting and a
  self-serve audit trail — this is the exact feature this project's own
  evidence base (falsification battery, published nulls) already
  out-executes every competitor on, per `SCORECARD.md`.
- **Willingness to pay [EVIDENCE, anchored]**: $35–100/mo — Rithmm Pro/
  Premium ($49.99/$99.99) and PropsBot.ai ($49.99) are this persona's
  observed ceiling; this is the segment most likely to pay for depth over
  breadth.
- **Likely tier**: our proposed ALL SPORTS $49.99–59.99/mo, or a future
  professional tier if one ships — this persona is the natural audience for
  making the research methodology itself (published nulls, falsification
  battery) a visible, navigable feature rather than only a `docs/` asset.
- **Acquisition channel**: UNKNOWN.
- **Churn reason [INFERENCE]**: likely churns on discovering a backtest
  claim is self-graded rather than independently audited — no direct quote
  says this, but it follows from this persona's stated value (verifiability)
  combined with the corpus-wide finding that no competitor has third-party
  audit (`CHECKPOINT.md`).

---

## 5. Sharp-leaning bettor

*Chases price, thinks in EV/CLV terms, spreads action across books.*

- **Pain [EVIDENCE]**: gets limited or banned by sportsbooks once volume or
  win rate looks sharp — third-party commentary on OddsJam users being
  "limited almost instantly," one user reportedly banned across several
  books within 3 days; RebelBetting is the only vendor that proactively
  coaches around this.
- **Current workflow [EVIDENCE]**: compares prices across many books before
  betting — Betstamp's own praise quote: "Being able to compare odds across
  multiple sportsbooks in real time is a huge plus — it helps me maximize my
  profits with every bet."
- **Tools used [EVIDENCE]**: OddsJam, Unabated, RebelBetting, Betstamp,
  Outlier's higher tiers — the entire Sharp/Odds segment in
  `COMPETITOR_MATRIX.csv`.
- **Time spent**: UNKNOWN.
- **Most valuable feature [EVIDENCE]**: a sharp-book-referenced consensus
  price (Unabated's "Unabated Line," Betstamp's "True Line") and real-time
  line-movement/steam alerts.
- **Willingness to pay [EVIDENCE, anchored]**: $60–500+/mo — this is the
  only persona whose evidenced price ceiling reaches the professional band
  (RebelBetting Pro $209/mo, OddsJam Platinum ~$499.99/mo, Unabated
  Concierge ~$799/mo).
- **Likely tier**: does not map cleanly to either of our two proposed
  consumer tiers; closest fit is a future professional tier, and
  `PRICING.md` itself flags that we have no direct evidence for what such a
  tier would need beyond the general market pattern.
- **Acquisition channel [INFERENCE]**: plausibly Discord/forum communities
  given Unabated's and RebelBetting's heavy education/community framing, but
  Reddit — where this community most visibly organizes — was unreachable, so
  this is inference, not evidence.
- **Churn reason [EVIDENCE]**: "edges are just stale lines that do not get
  updated... despite inevitable variance this is NOT A GOOD APP" (OddsJam
  review, 1,000+ bets placed) — realized losses at volume despite an EV
  framing is this persona's specific and well-evidenced churn driver, distinct
  from the "coin flip" framing used by picks-product churners.

---

## 6. Content creator

*Builds an audience around picks/analysis; needs shareable, credible material.*

- **Pain [INFERENCE]**: needs defensible, citable numbers rather than vibes,
  to protect their own credibility with an audience — inferred from
  Props.Cash's own customer-type field explicitly naming "content creators"
  as a segment, and from the market-wide finding that handicapper-marketplace
  products (Juice Reel) exist specifically to solve "verified, not
  self-reported" track records for people selling picks to others.
- **Current workflow [INFERENCE]**: pulls hit-rate/trend data from a tool
  like Props.Cash to build content; no direct quote from a self-identified
  creator describing this process was found.
- **Tools used [EVIDENCE]**: Props.Cash (explicitly named target: "content
  creators"), Juice Reel (marketplace for handicappers selling verified
  track records).
- **Time spent**: UNKNOWN.
- **Most valuable feature [INFERENCE]**: verified, synced (not
  self-reported) track-record data — Juice Reel's entire pitch ("100%
  Verified betting data") is built for exactly this persona's credibility
  problem, though no creator quote confirms this is what they value most.
- **Willingness to pay [EVIDENCE, anchored]**: variable — Props.Cash's
  $19.99/mo (or its $99.99 season passes) is the closest direct price point;
  Juice Reel's seller-subscription model ($0.96–$14.99/week, set by the
  seller) shows this persona can also be a *revenue source* via a
  marketplace, not just a subscriber, which is a structurally different
  relationship from every other persona here.
- **Likely tier**: our proposed ONE SPORT or ALL SPORTS tier, marketed on
  data credibility (sample-size transparency) rather than picks.
- **Acquisition channel [INFERENCE]**: social media (the audience-building
  motive implies this) — not evidenced directly.
- **Churn reason**: UNKNOWN — no creator-specific churn quote exists in the
  corpus.

---

## 7. New bettor wanting guidance

*Early in their betting life, wants to be taught, not just handed picks.*

- **Pain [EVIDENCE]**: distrust of black-box picks, explicitly contrasted
  with wanting to learn — PlayerProps.ai's most enthusiastic reviewers
  repeatedly frame the product as teaching, not predicting: "It's not a
  'pick machine'. It helps YOU make the choices and I love that"; "Thank you
  for teaching me how to properly bet and not gamble."
- **Current workflow [INFERENCE]**: relies on a single app's education
  content plus a community (Discord) rather than doing independent research
  — inferred from the repeated Discord/education praise pattern, not from a
  self-described beginner's own workflow narrative.
- **Tools used [EVIDENCE]**: PlayerProps.ai specifically — its own review
  characterization names this persona directly: "beginner-to-intermediate
  bettors who want to be taught 'how to think.'"
- **Time spent**: UNKNOWN.
- **Most valuable feature [EVIDENCE]**: community + education, not raw pick
  volume — this is the single most repeated praise theme for PlayerProps.ai
  specifically (15+ independent 5★ reviews reference the Discord/founder/
  education, not the tool's picks).
- **Willingness to pay [EVIDENCE, anchored]**: $35–60/mo — PlayerProps.ai's
  $59/mo (or its $20/7-day week pass as a lower-commitment entry point) is
  the direct anchor; note one review suggests the product is "best suited to
  disciplined bettors with $1,000+ bankroll," which may put a genuine
  beginner below this persona's own price ceiling — flagged tension, not
  resolved by the evidence.
- **Likely tier**: our proposed ALL SPORTS tier if positioned as a teaching
  copilot; a lower-cost or free on-ramp is not directly evidenced as
  necessary but is consistent with PlayerProps.ai's week-pass strategy.
- **Acquisition channel [EVIDENCE]**: Discord — PlayerProps.ai's 19,000+
  member Discord is explicitly cited as central to this persona's
  relationship with the product, more than the picks themselves.
- **Churn reason [EVIDENCE]**: personal-conduct/founder-trust breakdown is a
  real, if single-sourced, risk unique to this community-centric model — one
  1★ reviewer alleges founder misconduct, and a separate reviewer explicitly
  warns "don't believe the 5 star reviews" as incentivized; both are
  single-source and unverified, but they identify a churn mode ("the
  community/founder trust breaks") that does not appear for any other
  persona in this corpus.

---

## 8. Professional (future)

*B2B or high-volume operator-grade buyer — syndicates, media/affiliates, trading teams.*

- **Pain [INFERENCE]**: needs infrastructure-grade reliability (uptime SLA,
  sub-second refresh, wide book/feed coverage) rather than a consumer picks
  product — inferred entirely from what Betstamp PRO markets to this buyer
  (99.99% uptime SLA, 400ms median refresh, 200+ book/feed coverage), since
  no professional-buyer quote exists in the corpus (Betstamp's PRO homepage
  deliberately substitutes technical/authority metrics for testimonials).
- **Current workflow**: UNKNOWN — this is a B2B buyer class with zero
  first-party quotes anywhere in `CUSTOMER_PAIN.md`, which is entirely an
  App Store/consumer-review corpus.
- **Tools used [EVIDENCE]**: Betstamp PRO is the only confirmed product in
  the corpus built for this buyer; OddsJam's and Unabated's top tiers
  ($399.99–$799/mo) are priced adjacent but are still self-serve consumer
  products, not confirmed B2B/enterprise sales motions.
- **Time spent**: UNKNOWN / not applicable in the same sense as a consumer.
- **Most valuable feature [EVIDENCE]**: API access, SLA-backed uptime, and
  breadth of book/feed coverage (including PPH and prediction-market feeds
  like Polymarket/Kalshi) — these are the specific, named features of
  Betstamp PRO's pitch to this buyer class.
- **Willingness to pay [EVIDENCE, anchored]**: $249–$799+/mo — Betstamp PRO
  base $249/mo (fully loaded ≈$477/mo), OddsJam Positive EV $499.99/mo,
  Unabated Concierge ~$799/mo. This is the only persona whose price anchor
  sits entirely outside the consumer bands.
- **Likely tier**: a future professional tier, explicitly not yet scoped —
  `PRICING.md` states directly: "this pricing analysis does not have direct
  evidence for what 'professional' would need to include beyond the general
  market pattern above."
- **Acquisition channel [INFERENCE]**: direct sales/"contact sales" — the
  only confirmed pattern (Betstamp's invite-only "Props"/"Live" tiers
  require sales contact), not evidenced beyond that structural fact.
- **Churn reason**: UNKNOWN — no B2B churn evidence exists in this corpus at
  all; this entire persona is the least evidenced of the eight and should be
  treated as directional only until a dedicated B2B research pass is run.

---

## Cross-persona notes

- **Evidence concentration is uneven.** Personas 1, 3, and 5 rest on the
  richest evidence (dozens of independent, dated App Store quotes each).
  Personas 6 and 8 rest almost entirely on inference from product design
  choices, not customer quotes — label them accordingly whenever they are
  used in planning, and do not let a confident-sounding paragraph above
  launder that gap.
- **The single biggest shared risk across every persona**: none of them has
  been observed choosing *our* product, because it does not yet exist as
  something a customer can find (`PRODUCT_ARCHITECTURE_AUDIT.md`). Every
  persona above describes real behavior toward *competitors*; mapping it
  onto our roadmap is a hypothesis, not a validated fit.
- **Reddit remains the single highest-value re-run** per `CUSTOMER_PAIN.md`'s
  own recommendation — it would most directly firm up personas 2 (daily
  bettor), 5 (sharp-leaning), and 6 (content creator), the three most
  inference-heavy entries here.
