# Segment: Sharp / Market / Odds-Tool Competitors

Date checked: 2026-08-31 (unless noted otherwise on a specific fact)
Researcher: automated research pass, logged-out views only

## Method note / access limitations

- WebFetch was used for direct site content where accessible.
- OddsJam's entire domain (oddsjam.com) returned Cloudflare bot-challenge responses (`cf-mitigated: challenge`, HTTP 403) to every automated fetch attempt (homepage, /pricing, /subscribe, /checkout, /positive-ev, /faq), both via WebFetch and via curl. This is Cloudflare's own bot protection, not a proxy/policy block — confirmed by inspecting response headers (`server: cloudflare`, `cf-ray`, CSP referencing `challenges.cloudflare.com`).
- Headless Chromium (both via Playwright and the raw chrome binary) could not complete a TLS handshake through this session's egress proxy at all — every attempt failed with `ERR_CONNECTION_RESET` / `SSL error code 1, net_error -101`, even against trivial control sites (example.com, google.com). This reproduced consistently and is an environment/proxy incompatibility with headless Chromium's TLS client, not a per-site block (confirmed: curl to the same hosts succeeded instantly). Practical effect: **no screenshots were captured for this report**, and any page whose content only exists behind a Cloudflare JS challenge (OddsJam) could not be rendered.
- Where OddsJam figures could not be verified live, I used: (a) a June 3, 2026 Wayback Machine snapshot of oddsjam.com/pricing (its pricing numbers are loaded client-side via API and were NOT present even in that archived HTML — only nav/feature copy came through), and (b) multiple independent third-party review sites, flagged UNVERIFIED-secondary below. Brand/visual description for OddsJam is UNKNOWN (no render possible).
- All other findings below marked "SEEN" came from a direct fetch of the live page today (2026-08-31).

---

## 1. OddsJam

- URL: https://oddsjam.com | Date checked: 2026-08-31 (blocked); pricing cross-checked against reviews dated 2026
- **Access: BLOCKED for automated/logged-out fetch (Cloudflare challenge). Nothing below is a direct SEEN observation of oddsjam.com itself except the nav/feature list recovered from a Wayback Machine snapshot (2026-06-03) and page `<title>`s surfaced in search results.**
- Corporate note (SEEN, verified via multiple financial press sources): OddsJam's parent, Odds Holdings Inc., was acquired by **Gambling.com Group** (Nasdaq: GAMB) — deal announced Dec 2024, closed ~Jan 2025, $80M upfront + up to $80M earnout through end of 2026. OddsJam is therefore not an independent startup; it's owned by a public affiliate/media company. This is a **surprising finding** worth flagging.
- Customer type: recreational-to-semi-pro bettors (per Betstamp's competitor page, see below) up through serious +EV/arb bettors.
- Sports/markets (from archived nav): NFL, NBA, College Football, MLB, College Basketball, NHL, Soccer, Golf; player props; futures.
- Tools (from archived nav, confirmed feature names): Arbitrage Betting Tool, Positive EV Betting Tool, Middles Betting Tool, Low Hold Betting Tool, Promo Conversion Tool, Parlay Builder, plus a full calculator suite (Arbitrage, EV, Bonus Bet Conversion, Half Point, Hold, Kelly, No-Vig Fair Odds, Odds Converter, Parlay, Point Spread, Poisson, Round Robin, Vig).
- Also has a public "Betting Education" hub explaining Arbitrage, +EV, moneyline, spread, juice, **Closing Line Value**, odds boosts, bonuses — i.e., CLV is a named/taught concept in their content, though CLV as a *tool* (tracked automatically) is UNCONFIRMED.
- Pricing (UNVERIFIED — secondary sources only, site itself inaccessible; figures are inconsistent across sources and should be re-verified before use):
  - Multiple 2026 reviews (XCLSV, RotoWire, oddsplays, ArbBets/getarbitragebets) converge on: **Gold ≈ $199/month** (one source phrased it as "$6.60/day billed monthly"), **Platinum ≈ $499/month, or ~$400/month billed annually**. One outdated source cited $999/month for Platinum — likely stale.
  - Betstamp's own comparison page (see below, vendor-competitor claim) states OddsJam is "Open Access — Uncapped, all plans accessible without restrictions" and positions OddsJam as "aimed at new bettors looking to arbitrage bet," i.e., a sharper competitor calling OddsJam the more casual/entry-level tool. Treat as biased but directionally useful.
  - Free tier / trial: UNCONFIRMED for current state (nav shows "Try for free" CTA on at least one archived page).
- Mobile app: confirmed to exist — App Store listing "OddsJam: Sharp Sports Betting" found via search (title itself uses the word "Sharp").
- EV/arb terminology: uses "Positive EV," "Arbitrage," "Middles," "Low Hold" as first-class named tools — i.e., calls the same arithmetic **EV** and **arbitrage**, not "price improvement." No disclaimer language about vig-adjusted EV being negative in expectation was found (could not access FAQ/EV explainer directly to check for a vig caveat — UNKNOWN).
- Limits/restrictions discourse: a search on Reddit-adjacent sources surfaced direct user complaints: "users get limited almost instantly when betting real money on any sportsbook... one user reported being banned on every sportsbook from a couple hundred dollar bets just 3 days in." This is third-party commentary, not OddsJam's own messaging — UNVERIFIED-secondary but consistent with well-known industry behavior (see cross-cutting section below).
- Brand/visual identity: UNKNOWN — could not render the page in this session.

## 2. Unabated

- URL: https://unabated.com (marketing) / https://tools.unabated.com (product) | Date checked: 2026-08-31, SEEN (homepage) — pricing page fetched but pricing values are loaded client-side and did not appear in fetched content; pricing below is UNVERIFIED-secondary.
- Hero headline (quoted, SEEN): **"Every Sharp Started Somewhere"**
- Subheadline (quoted, SEEN): "Bet with clarity using the tools, education and data science developed by pro bettors"
- Primary CTA (SEEN): "Start for Free"
- Social proof (quoted, SEEN): **"96% of Unabated members say they've become profitable sports bettors"** — a strong, unqualified profitability claim worth flagging; testimonials also cite specific dollar bankroll growth and a "$12k from limited availability" claim (implying the user was already being restricted by books and still profited).
- Sharp-book reference (SEEN via unabated.com articles): Unabated explicitly names its methodology — the **"Unabated Line"** is described as a vig-free consensus line built from a sport-specific blend of the sharpest market-making books (their own "Who Sets The Betting Line? The Market Makers" article discusses Pinnacle/Circa-type market makers as the reference class). This is the closest analog to our own de-vigged consensus approach and should be read closely for positioning risk — but note they market their comparison as pro-bettor education/tooling, not as a guaranteed-profit claim on any single number.
- Feature list (SEEN, homepage): Unabated Line (vig-free benchmark), real-time odds/props from 30+ sportsbooks, betting calculators (half-point, partial-game derivatives, hedge), futures simulators (NFL/CFB), player prop projections (WNBA + multi-sport), live/in-play market-inefficiency detection, education (videos/articles/courses), member Discord.
- Pricing (UNVERIFIED-secondary, multiple 2026 review sites): a free/"essentials" tier plus paid add-ons — **Props+ ≈ $99/mo**, **Premium ≈ $199/mo ($167/mo annual)**, **Concierge (top tier) ≈ $799/mo ($667/mo annual)**; sport-specific add-ons (e.g., WNBA Projections ≈ $129/mo, Tennisform ≈ $55/mo or per-season) sold separately. No advertised free trial per these sources; monthly plans reportedly carry a 14-day money-back guarantee. These numbers could not be confirmed against the live pricing page's client-rendered content — re-verify before quoting internally.
- Target persona (SEEN): recreational bettors seeking sustainable profitability, "side-hustle" volume bettors, aspiring pros.
- Mobile app: UNKNOWN/not confirmed in this pass.
- Brand/visual identity: UNKNOWN — no screenshot possible this session; site copy reads sports-media/pro-bettor-community in tone (heavy emphasis on education, Discord, "pro bettors" authorship) rather than fintech-clean.

## 3. Betstamp

- URL: https://www.betstamp.com (B2B/PRO site) and https://betstamp.com/pro | Date checked: 2026-08-31, SEEN
- **Major repositioning note (surprising finding):** Betstamp's main site headline now reads **"Betstamp — The pricing and data layer for modern sports markets"** (per page title) — it has repositioned from its original identity as a free consumer bet-tracking app into a B2B pricing/data infrastructure company. The consumer mobile app **"Betstamp: Bet Tracker & Props"** still exists and is actively updated (Google Play/App Store listings show 100,000+ downloads, last updated mid-2026, ~1.4K downloads in the last month) — so Betstamp now runs a free/freemium consumer tracker *and* a separate high-priced B2B "PRO Odds Screen" product. Treat these as two different products under one brand.
- Hero headline (quoted, SEEN, PRO site): **"The True Line: The Sharpest Props Pricing in the Industry."**
- Pricing for **Betstamp PRO** (SEEN directly, confirmed twice on the live page): **Main plan $249/month**, with optional add-ons **PPH feeds +$99/month** and **Alts +$129/month** (so a fully-loaded plan runs **≈$477/month**); "Props" and "Live" plans are invite-only / "Contact Sales, limited seats, requires approval." Annual billing advertised as "save up to 40%" but no exact annual dollar figure shown. **This confirms the preliminary lead that Betstamp's professional product reaches hundreds per month — verified live, 2026-08-31.**
- Feature list (SEEN): proprietary "True Line" pricing across 2,548+ markets, sub-second (400ms median) refresh, 200-207+ sportsbook/operator coverage (regulated books + offshore + PPH + prediction markets Polymarket/Kalshi), 99.99% uptime SLA, 5+ seasons of backtested/historical data, steam alerts (True Line move >2.5%), same-game-parlay leg-by-leg fair value, integrated one-click bet tracking, arbitrage detection via negative-hold sorting, full custom filtering.
- Target audience (SEEN): explicitly six B2B/pro segments — professional bettors/syndicates, sportsbook operators/trading teams, market makers/exchanges/prediction markets, DFS/sweepstakes operators, media/affiliates, pro sports team analytics departments. Explicitly **not** positioned at recreational bettors on the PRO product.
- Competitor framing (SEEN, betstamp.com/comparison/oddsjam — vendor-authored, treat as biased): claims OddsJam uses an "inefficient" weighted-aggregate line vs. Betstamp's "hyper-efficient market-based True Line," claims OddsJam has "limited edge metrics" and "no PPH feeds," and explicitly labels OddsJam as "aimed at new bettors looking to arbitrage bet" vs. Betstamp's professional positioning. Comparison pages also exist vs. Unabated and OddsLogic (both fetched titles only, not opened this pass).
- Social proof: none on the PRO homepage — Betstamp deliberately substitutes technical/authority metrics (uptime, refresh speed, book count) for testimonials, consistent with a B2B/enterprise pitch.
- Sports coverage (SEEN): NFL, NBA, MLB, NHL, NCAA football/basketball, soccer (EPL, UCL, La Liga, Serie A, Bundesliga, Ligue 1, MLS, World Cup), UFC, WNBA, CFL, ATP, WTA.
- Brand/visual identity: UNKNOWN (no screenshot); copy tone reads finance/data-infrastructure ("SLA," "data layer," "API," enterprise segments) rather than casual sports-media.

## 4. Outlier

- URL: https://outlier.bet | Date checked: 2026-08-31, SEEN (homepage, pricing page returned 404 at the guessed URL; pricing recovered from homepage + Outlier's own Help Center article, both SEEN)
- Hero headline (quoted, SEEN): **"The #1 App for Making Smarter Bets"**
- Subheadline (quoted, SEEN): "Quickly analyze thousands of picks. Find your edge. Beat the odds."
- Primary CTA (SEEN): "Find your next bet" → app.outlier.bet
- **Pricing — the preliminary lead is CONFIRMED as accurate, verified live today (2026-08-31):**
  - **Premium: $19.99/month**
  - **Premium+: $29.99/month**
  - **Pro: $79.99/month**
  - All three include a 7-day free trial. No free (non-trial) tier. (Annual equivalents per third-party review — UNVERIFIED-secondary — cited as ~$199.99/yr, ~$299.99/yr, ~$359.99/yr respectively; not confirmed on-site this pass.)
- Feature differentiation by tier (SEEN, from Outlier's own Help Center article "Choosing the Right Outlier Plan"):
  - Premium: trending insights/recommended bets, thousands of props/games, data visuals, basic odds tracking/live movement charts, injury reports, real-time alerts.
  - Premium+ adds: a "Positive EV badge" that flags plays using Outlier's own **"DVIG/no-VIG calculations"** (i.e., they explicitly name their de-vigged-consensus math — directly analogous to our price-improvement engine's arithmetic, but they surface it as an EV badge rather than "price improvement"), plus a live odds-movement tracker per sportsbook.
  - Pro adds: full +EV feed with custom filters, **"sharp-book odds comparison,"** middling tools, and an **arbitrage feed that "calculates exact stakes across sportsbooks for a guaranteed profit."** Note the phrase "guaranteed profit" is used for arbitrage specifically (mathematically defensible for true arb, unlike +EV) — but it sits right next to the +EV badge in the same tier ladder, which risks blurring the two concepts for a reader.
- Sportsbook integrations (SEEN): FanDuel, DraftKings, BetMGM, Caesars, bet365, and others; direct bet-placement/integration implied ("Integrated betting with...") though whether this is true one-click bet placement or deep-linking was not confirmed — UNKNOWN.
- Social proof (SEEN): 4.9/5 across 14.6k+ reviews; a testimonial quoted verbatim: **"Up +24.82% ROI for May."**
- Mobile app: confirmed (App Store listings: "Outlier: Smart Sports Betting").
- CLV tooling: not mentioned in what we saw — UNKNOWN/absent.
- Brand/visual identity: UNKNOWN (no screenshot); copy tone reads consumer-app/mobile-first, closer to a sports-media betting app than a finance terminal.

## 5. OddsShopper

- URL: https://www.oddsshopper.com | Date checked: 2026-08-31, SEEN (homepage); /pricing guessed URL 404'd, pricing therefore UNKNOWN
- Hero headline (quoted, SEEN): **"All Paths To Profit Begin Here"**
- Subheadline (quoted, SEEN): "Numbers in your hands. Legends at your back. One home."
- CTAs (quoted, SEEN): "Engineer your edge with OddsShopper," "Ride With Sharps on Tails," "Start Free Trial"
- Feature list (SEEN): "Portfolio EV" (diversified +EV strategy), Arbitrage ("guaranteed profit opportunities" — quoted), Odds Screen, in-game/live EV and arbitrage, a "Liquidity Tool" for following sharp bettors on prediction exchanges, and "Tails" — curated picks from "vetted insiders" (a follow-the-expert product layered on top of the odds tooling, notable since most of this segment avoids tout-style framing).
- Profit claim (quoted, SEEN): "stress-test millions of strategies across billions of odds to surface profitable edges"; testimonials claim being "profitable every month."
- Pricing: UNKNOWN — not shown on homepage, only a free-trial CTA; the guessed /pricing URL 404'd and was not tracked down further this pass.
- Target audience (SEEN): both new and experienced bettors, explicit tout/insider-following angle in addition to self-serve tools — a hybrid of odds-tool and pick-selling business models, worth noting as a distinct positioning from the other five.
- Brand/visual identity: UNKNOWN (no screenshot); copy voice is the most tout/marketing-forward of the six ("Legends," "Ride With Sharps").

## 6. RebelBetting

- URL: https://www.rebelbetting.com | Date checked: 2026-08-31, SEEN (homepage)
- Hero headline (quoted, SEEN): **"Turn Sports Betting Into an Investment"**
- Subheadline (quoted, SEEN): "RebelBetting helps you find profitable bets with a mathematical edge, letting you outsmart the bookmakers at their own game."
- Pricing (SEEN): 14-day free trial (capped at 50 bets/day); **Starter $99/month or $69/month annual**; **Pro $209/month or $139/month annual**.
- Feature list (SEEN): value betting (mispriced-odds identification, i.e., +EV under a different name), sure betting/arbitrage ("risk-free profit locking" — quoted), auto-settling bet tracker, 100+ supported bookmakers, real-time alerts, custom filters.
- Profit/ROI claims (quoted verbatim, SEEN) — the most aggressive of the six: **"Total Member Profit: €23M,"** **"30% Avg ROI / Month,"** **"€1,760 Avg Profit / Month,"** **"Average users double their starting bankroll within 3 months."** These are unusually strong, specific numeric claims relative to the rest of the segment and are a useful contrast point for our own "price improvement, not a promised return" framing.
- Social proof: 325,000+ users; named testimonials with individual ROI figures; states a Pinnacle partnership "since 2009."
- **Limits/restrictions — directly investigated, and RebelBetting itself openly addresses this** (SEEN via site content, not opened in full but title/summary confirms existence): they publish their own blog post titled **"How to Handle Bookmaker Limitations: What to Do When You Get Limited,"** i.e., unlike the other five, RebelBetting proactively tells users limiting is expected and coaches them on managing it (spreading action across 100+ supported books, disguising bet patterns) rather than treating it as an edge case. This is the clearest example in the segment of a vendor acknowledging up front that the displayed edge is not durably executable at one book.
- Brand/visual identity: UNKNOWN (no screenshot); copy tone is the most explicitly "investment/finance" of the six ("Turn Sports Betting Into an Investment," ROI/profit language throughout).

## Also noted, not fully profiled (time-boxed out of scope for full capture)

- **Pikkit** (pikkit.com) — SEEN homepage: primarily a free social bet-tracking app ("All of Your Bets And Friends In One Place," 4.9★/18k+ reviews) with a "Line Shop" comparing 30+ books and a CLV feature in-nav; monetizes via referrals and an unpriced "Pikkit Pro." Adjacent to this segment (tracking-first, not screen-first) — worth a dedicated pass if Brey wants bet-tracker positioning covered separately.
- **BetQL**, **AVO (Arbs vs Odds)**, **SmartStake**, **ProfitDuel**, **OddsPedia** — surfaced repeatedly in review-site "best of" lists as OddsJam/Outlier alternatives but not opened directly this pass; flagging as candidates for a follow-up sweep if broader segment coverage is wanted.

---

## Cross-cutting: how this segment talks about limits, executability, and account restriction

- **None of the six primary sites' own marketing copy (as fetched) discloses, on the page that makes the EV/edge/arbitrage claim, that a displayed positive-EV price is frequently not fully bettable at size, or that the average +EV bet is priced against a vig-inclusive market and is negative-EV before the tool's own no-vig adjustment.** Where this content exists, it lives in secondary education/blog content (OddsJam's "What is Closing Line Value" / "What is Positive EV" articles; RebelBetting's arbitrage-risk and bookmaker-limitation blog posts) rather than on the pricing/hero pages that carry the profit claims.
- **RebelBetting is the one outlier (no pun intended) that puts "you will likely get limited" front and center as its own content**, coaching users to spread bets and disguise patterns — an implicit admission that the tool's edge does not survive concentrated, visible use at a single book.
- **Independent/third-party evidence (Reddit-adjacent commentary surfaced via search, UNVERIFIED-secondary) corroborates that OddsJam users report being limited or banned within days of using its tools for real-money +EV betting at material stake sizes** — consistent with well-documented industry practice (books limiting or reducing odds for bettors who look sharp) and with regulatory attention reportedly beginning in Massachusetts.
- **Vendor-vs-vendor claims should be read skeptically**: Betstamp's own comparison page characterizes OddsJam as "uncapped... aimed at new bettors" (implying casual/less sophisticated), which is marketing self-interest, not independent fact — but it is a useful signal that price-improvement/EV tools in this space explicitly compete on "how sharp is the reference line," which is directly the terrain our price-improvement engine sits on.
- **Terminology used across the segment for the same underlying arithmetic (de-vigged consensus vs. best line) varies a lot**: "Positive EV" / "+EV" (OddsJam, Outlier, OddsShopper), "value betting" (RebelBetting), "edge" (Betstamp: "automatic edge detection," Unabated: general "edge" language), and only Outlier explicitly names its underlying math ("DVIG/no-VIG calculations"). **Nobody in this set uses "price improvement" as their primary term** — that appears to be open, differentiated language for us, while also meaning our audience has been extensively pre-trained by this whole segment to read "EV/edge" as the default vocabulary for this exact comparison.

## Sources appended to SOURCES.md

All URLs opened today were appended with today's date; see docs/COMPETITIVE_INTELLIGENCE/SOURCES.md.

## Confidence summary

- HIGH confidence / directly verified today: Betstamp PRO pricing and features, Outlier pricing and tier features, Unabated homepage copy/testimonials, RebelBetting pricing and claims, OddsShopper homepage copy.
- LOW confidence / secondary-sourced only, needs re-verification: OddsJam pricing (site inaccessible), Unabated exact tier pricing (client-rendered, not directly observed), any Reddit/forum claims about specific users being banned.
- UNKNOWN / not established this pass: brand color/typography/logo for all six (no screenshots possible this session), OddsJam's on-site EV/vig disclaimer language, OddsShopper pricing, whether Outlier's "integrated betting" is true one-click placement or a deep link.
