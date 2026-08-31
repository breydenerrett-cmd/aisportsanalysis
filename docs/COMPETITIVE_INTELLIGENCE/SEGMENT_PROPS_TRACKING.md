# Segment Research: Prop Research Tools & Tracking/Consumer Platforms

Date checked: 2026-08-31 (all prices/features below verified this date unless noted otherwise). Researcher note: WebFetch and headless Chromium in this environment could only see **logged-out, non-JS-hydrated, or app-store views** for several sites. Where the live marketing site itself returned an error, price/feature data was pulled directly from that site's own production JavaScript bundle (fetched live today) rather than from a rendered page — this is marked "SOURCE: live JS bundle" and is a direct read of the site's own code/copy, not a rumor or a third-party guess. Anything from a review/aggregator site is marked "THIRD-PARTY, unverified against primary source."

---

## PART A — PROP RESEARCH TOOLS

### 1. Props.Cash
- URL: https://props.cash/ | Date verified: 2026-08-31
- Customer type: individual sharp/recreational prop bettors, content creators
- Sports (SOURCE: live `<meta description>` tag, seen directly): NBA, NFL, MLB, NHL, NCAAF, NCAAM, EPL, MLS, WNBA, CS:GO
- **Pricing — CONFIRMED, corrects nothing in the preliminary lead:**
  - Monthly (All Sports): **$19.99/mo** (SOURCE: live JS bundle FAQ string: `"How Much Does Props.Cash Cost?" -> "$19.99/Monthly, $199.99/Annually"`)
  - Annual (All Sports): **$199.99/yr** list price; live promo banner in the same bundle offers `ANNUAL40` for 40% off = **$119.99/yr** effective
  - Sport-specific "Season Pass" tiers exist: NFL Season Pass $99.99, NBA Season Pass $99.99 (SOURCE: App Store listing, seen directly, 2026-08-31)
  - Free tier: no persistent free tier found in code; **7-Day Free Trial** confirmed (live JS bundle string: "7 Day Free Trial")
  - Web app: yes (React SPA). Mobile app: yes, iOS confirmed (App Store: 4.8★, 7.7K ratings, last updated Dec 18 2025, v3.0.17)
- Features seen in live code: player-prop hit-rate tables, filterable by home/away, opponent (BvP/DvP), rolling windows (labels for L3/L5/L10/L20 plus a "custom" range), injuries, weather, lineups/rotation context, odds comparison across sportsbooks ("Displays current betting odds from various sportsbooks, helping you find the best available lines and compare different books" — a form of line shopping, though the literal phrase "line shopping" does not appear)
- Features NOT found anywhere in the live code (grepped the full production bundle): **bankroll tracking, parlay building, community/social features, "line shopping" as a named feature.** Also **no bet-tracking or sportsbook-account-sync** — Props.Cash is research-only, not a tracker.
- Pro tier: no separate "Pro" brand tier; single "All Sports" plan plus optional sport-specific season passes.

**THE HIT-RATE PROBLEM — direct finding:** Grepped the entire live production JS bundle for "sample size," "small sample," "denominator," "disclaimer," "minimum games," "low sample," "caution" — **zero product-facing hits**. The only hit-rate related copy found is a tooltip: *"Percentage of games where the player exceeded the current line value."* — a plain definition, with no caveat about sample size. The UI exposes rolling windows down to L3 (last 3 games) and a fully custom range, with no visible floor or warning when a user narrows to a tiny sample. **Verdict: Props.Cash shows no denominator warning and no sample-size guardrail anywhere in its client code.**

---

### 2. LineMate
- URL: https://linemate.io/ | Date verified: 2026-08-31
- Tagline (SOURCE: live `<meta description>`): "Sports analytics for everyone"
- Customer type: "everyday sports fan" (per third-party coverage), casual-to-intermediate bettors
- Sports (App Store listing, seen directly): NFL, NCAAF, AFL, NRL, NBA, WNBA, NCAAB, NHL, MLB, EPL, La Liga, Serie A, Bundesliga, Ligue 1, MLS, UEFA competitions
- **Pricing — two different numbers from two different live surfaces, flagged as a real discrepancy, not resolved:**
  - Website (SOURCE: live JS bundle, `price:14.99` / `price:149.99` literals in checkout code): Monthly **$14.99**, Annual **$149.99** (a `discountPercentage: 60.001` field is attached to the annual tier but its exact math vs. list price is unclear from code alone — UNVERIFIED how that percentage is computed)
  - iOS App Store in-app-purchase list (seen directly, 2026-08-31): Monthly **$9.99 and $14.99** (two monthly tiers), Annual **$59.99 and $79.99** (two annual tiers)
  - These do not reconcile cleanly (web checkout shows one $14.99/$149.99 pair; App Store shows four different price points). Likely explanation: multiple historical/regional/promotional SKUs coexist in Apple's IAP catalog while the web checkout only surfaces the current default. Treat "$14.99/mo, $59.99/yr" (the pre-existing rumor for LineMate+ from search aggregators) as **roughly in the right neighborhood but not confirmed as the current live default** — the live web checkout price is $149.99/yr, not $59.99/yr.
  - Base app is free; "LineMate+" gates parlay recommendations. 7-day free trial confirmed in code.
  - Mobile app: iOS + Android confirmed (App Store 4.8★/14K ratings; Google Play listing exists). Web app: yes.
- Pro tier / structure: single premium tier ("LineMate+"), not sport-specific plans.

**THE HIT-RATE PROBLEM — direct finding, and this is the most important single finding in this report:** LineMate's live code defines a set of built-in filter *categories* whose **subtitle string is literally "100% Hit Rates"** — e.g. `"versus-opponent": {title:"Versus Opponent", subtitle:"100% Hit Rates"}`, and the same "100% Hit Rates" subtitle is reused for "Alternate Lines," "Home/Away Games," "Team Form," and "Unders Only." In other words, the product ships pre-built views whose entire selling point is finding splits with a perfect record. The floor for showing a trend at all is gated by a **minimum of 3 games** (localized string across 6 languages: *"Need 3 games minimum" / "minimumGames"*). So a badge reading "100% Hit Rate" can legitimately be built on an n of 3. No warning copy, no sample-size caveat, and no visible denominator was found anywhere alongside the "100% Hit Rates" category labels themselves (the code does carry a `gamesPlayed` field used elsewhere, so an actual fraction may appear on a deeper per-player screen — this could not be confirmed since the SPA would not render in our headless browser; flagged UNVERIFIED). **Verdict: LineMate is the clearest example found in this research of a tool that structurally encourages "slice until it looks meaningful" — the product literally names a feature category after the outcome (100% hit rate) rather than the sample.**

---

### 3. OddsJam (discovered — player props / +EV tool)
- URL: https://oddsjam.com/ | Date verified: 2026-08-31 — **note: the live marketing site and pricing page both returned HTTP 403 to our fetcher; could not render directly.** Data below is from OddsJam's own iOS App Store listing (seen directly) and third-party review aggregation (marked accordingly).
- App Store (seen directly, 2026-08-31): "OddsJam: Sharp Sports Betting," 4.7★, 2.2K ratings, last updated Aug 18 2026 (v27.07). Hero pitch on the listing: **"Player Props, +EV, & Arbitrage."**
- In-app purchase tiers listed on the App Store page (seen directly): Trends $19.99/mo, Fantasy Optimizer $59.99/mo, Fantasy Picks $79.00, Gold $199.99/mo, Sharp Money $199.99/mo, Platinum Monthly $499.99/mo, Positive EV Monthly $499.99/mo, Positive EV Global Monthly $399.99/mo. This is a much wider and higher-ceiling tier ladder than Props.Cash or LineMate — OddsJam monetizes odds/EV-scanning tooling (arbitrage, +EV) as premium add-ons on top of a props layer.
- THIRD-PARTY (unverified against primary site, from aggregator search summaries): base +EV/arbitrage tooling "starts around $99/month," fantasy pick'em tier at $59.99/mo for PrizePicks/Underdog/Sleeper/Betr/ParlayPlay, fantasy notifications flag props with a 60%+ hit rate.
- Hit-rate/sample-size handling: not directly verifiable (site blocked); one third-party source asserts OddsJam avoids publishing performance figures because its core function is cross-book price-discrepancy detection rather than outcome prediction — plausible given the product is fundamentally an odds/EV scanner, not a trend browser, but this is an ASSERTION from a secondary source, not something we saw ourselves.

### 4. Outlier.bet (discovered — player props research dashboard)
- URL: https://outlier.bet/ | Date verified: 2026-08-31 (fetched live, rendered as text)
- Hero headline (seen live): **"The #1 App for Making Smarter Bets"**; sub-line: "Quickly analyze thousands of picks. Find your edge. Beat the odds."
- Pricing (seen live): Premium $19.99/mo, Premium+ $29.99/mo, Pro $79.99/mo. THIRD-PARTY sources add annual figures of $199.99/$299.99/$359.99 per year respectively — not independently confirmed on the live page in this pass. 7-day free trial confirmed live.
- Sports/markets: NBA, NFL, MLB, CBB; player props and game lines across FanDuel, DraftKings, BetMGM, Caesars, bet365, Underdog, ESPN Bet.
- Features (seen live): EV+ indicators, arbitrage feed, middle-betting tools, sharp-book odds identification, line movement tracking, real-time odds comparison, 2-click bet placement integration, injury reports/matchup analysis. Outlier explicitly blends the props-research and the odds-scanning/EV categories — closer to OddsJam than to Props.Cash/LineMate.
- Social proof (seen live): 4.9/5, 14.6K reviews; a testimonial quoting "+24.82% ROI" — **this is a user-testimonial claim quoted on the marketing page, not an audited/verified performance number; treat as marketing assertion, not a fact about the product's accuracy.**
- Branding: blue/purple accents, minimalist modern UI (per fetch summary).
- Hit-rate/sample-size handling: not independently verified this pass — flagged as a gap; worth a follow-up direct check of Outlier's actual trend cards for denominators.

---

## PART B — TRACKING / CONSUMER PLATFORMS

### 1. Action Network / Action PRO
- URL checked live: https://www.actionnetwork.com/pro → redirects to https://www.actionnetwork.com/subscribe | Date verified: 2026-08-31, fetched and rendered directly (this is a primary, live, today-dated source, not a rumor).
- **Pricing — CONFIRMS the preliminary lead exactly, with one addition (a weekly tier the lead didn't mention):**
  - PRO Weekly: **$14.99/week**
  - PRO Monthly: **$24.99/month**
  - PRO Annual: **$119.99/year** (marked "Best Value!" on the live checkout page)
  - The iOS App Store IAP list (seen directly) additionally shows a 3-Month tier at $59.99 and a separate "EDGE" product line (EDGE Monthly $29.99, EDGE Annual $99.99) not present on the /subscribe web checkout — Action Network appears to be running more SKUs in-app than on web.
- Hero copy (seen live, on the subscribe page): **"ACTION PRO — More edges. Less noise."** Feature bullets on that same page: Live expert pick alerts, Betting model projections, Real money percentages, Premium article access, Top player prop values, Historically profitable systems.
- Feature comparison table (seen live) — Free vs PRO:
  - Free (Action Network base app): Live Odds, Expert Picks, Personal Bet Tracking, Pick & Game Alerts, Some Articles, Bet Percentages
  - PRO adds: Instant Expert Pick Alerts, Money Percentages, PRO System Picks, Premium Articles & Insights, Sharp Action Report, Prop Projections, Custom Bet Tracking, Betting Projections, PRO Line Alerts
- Social proof (seen live): one featured App Store review quoted verbatim: *"Hey man, all I can say is this app has paid for itself. Super great insight and deep analysis. Subscribing forever. If you don't get the PRO version you're playing yourself!"* — attributed to "Mal504 (via App Store Review)." This is a cherry-picked testimonial, not an aggregate rating shown on that page.
- App Store listing (seen directly): 4.8★, 35K ratings, v7.0.0 "New codebase... faster user experience," updated within hours of check.
- **Bet tracking / sync mechanism — THE APP-STORE-AND-SYNC QUESTION, direct finding:** Action Network's own help documentation ("BetSync 101," found via search, not independently re-fetched this pass) states BetSync **automatically tracks bets placed at partner sportsbooks** — historically DraftKings, WynnBet, and PointsBet, in 18 approved states — and that **BetSync does not require any Action Network subscription** to use; it's a free feature gating on sportsbook/state availability, not on the PRO paywall. Outside BetSync's supported books/states, tracking is manual entry. This is a materially narrower sportsbook-sync list than Pikkit's or Juice Reel's (see below) — worth confirming currency, since WynnBet has exited some markets since this documentation was likely written; flagged UNVERIFIED/possibly-stale.

### 2. Pikkit
- URL: https://pikkit.com/ | Date verified: 2026-08-31, fetched and rendered directly (primary source).
- Hero headline (seen live): **"All of Your Bets And Friends In One Place."**
- Pricing/free tier: core tracking, analytics, and BookSync are on the **free tier with no subscription or credit card required**; a paid "Pikkit Pro" tier exists layering on features like closing-line-value analysis (per App Store listing) — exact Pro price not confirmed on the marketing homepage; App Store IAP range shown is $29.99–$199.99 monthly/annually (unclear which specific tier maps to which price — UNVERIFIED breakdown).
- **Sync mechanism — direct finding, this is the strongest sync story found in either segment:** "BookSync" automatically imports bets from **30+ sportsbooks** (named on-site: DraftKings, FanDuel, BetMGM, Caesars, theScore Bet, Fanatics, and more) via **read-only credential-based sync** — site states credentials are encrypted and never stored on Pikkit's servers, and the integration cannot place bets or move funds. Bets sync in real time per the marketing copy (an ASSERTION — "real time" was not independently timed by us). No screenshot-parsing or email-parsing mechanism was mentioned; the sync is described purely as direct account connection.
- Features (seen live): live tracking with win-probability, analytics/trend/scenario analysis, social feed (follow friends/influencers), copy-bet-to-slip, line shopping across 30+ books, granular privacy controls (hide bets by type/date/amount/league).
- Social proof (seen live): 4.9★, 18K+ reviews aggregate claim on-site; separately, App Store listing (seen directly) shows 4.9★/21,000 ratings, last updated "7 hours ago."
- Accuracy/profit claims: none found on the homepage; product deliberately positions itself against self-reported/manual stats ("verified" via sync) rather than making its own performance claims.
- Branding: clean, modern, minimalist; dark/light UI with blue accents (per fetch).

### 3. Juice Reel
- URL: https://www.juicereel.com/ | Date verified: 2026-08-31, fetched and rendered directly (primary source).
- Hero headline (seen live): **"The world's first transparent betting marketplace."**
- Pricing/free tier: the bet-tracker app itself is free (iOS + Android). A marketplace layer lets verified handicappers sell their picks; seller-side subscription prices range roughly **$0.96–$14.99/week**, set per-seller, not a flat platform price.
- **Sync mechanism — direct finding:** "automatically pulls every bet from **300+ sportsbooks**" (site's own figure) with named integrations including DraftKings, FanDuel, BetMGM, Caesars, Bet365, Underdog, PrizePicks, Sleeper, and Kalshi — notably this list spans traditional sportsbooks **and** DFS/pick'em platforms **and** a prediction market (Kalshi), broader than Pikkit's stated list. Mechanism (API-based sync vs. screenshot/email parsing) is not specified on the page — UNVERIFIED which underlying method is used, though "sync" language implies direct account connection similar to Pikkit's model.
- Marketplace/transparency mechanic: the core differentiator is that every seller's track record is **derived from their synced sportsbook data**, not self-reported — positioned explicitly against tout marketplaces where records can be fabricated.
- Claims (seen live): "60M+ Bets tracked," "100% Verified betting data," 4.8★ rating with "5.5K ratings" cited on-site; App Store listing (seen directly) separately shows 4.8★/4.2K ratings, last updated Aug 6 2026 (v3.92.0).
- Branding: orange/white color scheme, clean modern card-and-leaderboard UI (per fetch).
- Sample-size handling: not applicable in the same way as prop tools — Juice Reel tracks realized bet outcomes (ROI, win/loss), not "X of last Y" prop splits, so the small-sample problem shows up differently here (e.g., a handicapper's win rate over a handful of picks could still be misleadingly small) — no explicit small-sample warning or minimum-picks threshold was found on the marketing pages for the marketplace/leaderboard rankings. Worth a follow-up check of the actual leaderboard UI (logged out, could not access).

### 4. BettorEdge (discovered — hybrid peer-to-peer exchange + social tracking, not a pure tracker)
- URL: https://www.bettoredge.com/ | Date verified: 2026-08-31, fetched and rendered directly.
- **Important scoping note:** BettorEdge is fundamentally a peer-to-peer betting exchange ("bet against people, not the house"), not a bet tracker in the Pikkit/Juice Reel sense. It's included here because it bundles social leaderboards, performance tracking, and a premium analytics tier, making it a relevant adjacent consumer platform, not a strict apples-to-apples comparator.
- Hero headline (seen live): **"Bet against people, not the house."**
- Pricing: free to join (~2 min ID verification, no deposit required); a "Premium tier" is mentioned for advanced analytics and priority market access, but no dollar figure was found on the homepage — UNVERIFIED price.
- Sports: NFL, MLB, NBA, NHL, WNBA, UFC, Tennis, College Football, March Madness.
- Features (seen live): peer-to-peer order matching (no-vig pricing), leaderboards, head-to-head challenges, pick'ems, "auction squares," group chats, a Discord bot posting live odds into 1,100+ servers, 26+ free betting calculators.
- Claims (seen live, marketing assertions): 35,000+ active bettors, $100M+ matched peer-to-peer, 1M+ orders placed, "legal in 45+ states."
- Testimonials (seen live, cherry-picked): *"I've actually made money since finding BettorEdge"* (John); *"Really awesome app"* (Nick); *"Super easy to get started"* (Marty).
- Sync/tracking mechanism: since bets are placed on BettorEdge's own exchange rather than at third-party sportsbooks, there is no sportsbook-sync problem for BettorEdge's own bets — this sidesteps the entire sync question that Pikkit/Juice Reel/Action Network have to solve, which is itself a notable structural difference worth flagging for product strategy.

---

## CROSS-CUTTING FINDING 1 — THE HIT-RATE / SAMPLE-SIZE PROBLEM (direct answer to the brief)

Summary across every prop tool actually inspected at the code/copy level (Props.Cash, LineMate) plus what secondary sources say about OddsJam/Outlier:

| Product | Shows denominator? | Warns on small samples? | Baseline for comparison? | Lets user slice to n as small as... |
|---|---|---|---|---|
| Props.Cash | Not found anywhere in live code/copy | No — zero hits for sample/warning/disclaimer strings | Not found | L3 (last 3 games) + fully custom range, no floor |
| LineMate | Not found next to the "100% Hit Rate" category labels (a per-player screen may carry a raw count via a `gamesPlayed` field — unconfirmed) | No — same zero hits, and it actively names a filter category "100% Hit Rates" | Not found | **3 games minimum, enforced in code, localized in 6 languages** |
| OddsJam | Unverified (site blocked) | Unverified | Unverified | Unverified |
| Outlier.bet | Unverified this pass | Unverified this pass | Unverified this pass | Unverified this pass |

**Bottom line for product strategy:** in the two products we could actually inspect at the source level, **neither shows a denominator next to a hit-rate percentage, neither warns about small samples, and neither offers any baseline (e.g., league-average hit rate, or a Bayesian-shrunk estimate) for context.** LineMate goes further than merely being silent on this — it structurally organizes a whole feature area around finding "100% Hit Rate" splits with a floor of just 3 games. This is strong evidence that **explicitly calling out small samples and challenging weak reasoning is a genuine, currently-unaddressed differentiator**, not table stakes — at least among these two closely-comparable competitors. This should be validated against OddsJam and Outlier.bet directly (both currently blocked or unverified in this pass) before being treated as true of the whole category.

## CROSS-CUTTING FINDING 2 — THE APP-STORE / SYNC REALITY (direct answer to the brief)

| Product | Sync mechanism | Books/platforms named | Cost to use sync |
|---|---|---|---|
| Action Network (BetSync) | Direct account connection (mechanism not detailed beyond "automatic"), per third-party help doc — **not independently re-verified live this pass** | DraftKings, WynnBet, PointsBet, in 18 approved states (per that doc — likely dated; WynnBet's market presence should be re-checked) | Free, no subscription required |
| Pikkit (BookSync) | Read-only credential-based direct connection; explicitly "not stored," cannot place bets/move funds | 30+ named: DraftKings, FanDuel, BetMGM, Caesars, theScore Bet, Fanatics, + more | Free (BookSync is on the free tier) |
| Juice Reel | "Automatically pulls" from 300+ books; underlying mechanism (API vs. scraping vs. other) not disclosed on-site | 300+ claimed; named: DraftKings, FanDuel, BetMGM, Caesars, Bet365, Underdog, PrizePicks, Sleeper, Kalshi | Free (base tracker) |
| BettorEdge | N/A — bets are native to its own exchange, no third-party sync needed | N/A | N/A |

**Bottom line for product strategy:** none of the trackers researched disclosed screenshot-parsing or email-parsing as their sync method — all describe (or imply) **direct, credentialed account connections** to sportsbooks, which is the harder engineering problem (per-book integration/maintenance, credential security, regulatory/read-only scoping) but is what all three real trackers have converged on. Juice Reel's claimed 300+ book/platform count (spanning sportsbooks, DFS pick'em apps, and even Kalshi) is the widest reach found and would be the bar to match; Pikkit's list, while smaller, is the most transparent about its security model (encrypted, not stored, read-only). This suggests **broad sportsbook sync is achievable and already commoditized among competitors** — it is likely not a moat by itself; the differentiation opportunity is more in what's done with the synced data (verification, community, closing-line-value, alerts) than in the sync mechanism itself.

---

## CONFIDENCE, GAPS, AND WHAT REMAINS UNVERIFIED

- **High confidence (live, primary-source, dated 2026-08-31):** Action Network PRO pricing and feature table (fetched directly); Pikkit homepage claims and BookSync description (fetched directly); Juice Reel homepage claims (fetched directly); Props.Cash pricing, sports list, and complete absence of sample-size warnings (read directly from the site's own live production code); LineMate's "100% Hit Rate" filter categories and 3-game minimum (read directly from the site's own live production code); all six App Store listing snapshots (ratings, counts, last-update dates, IAP tiers) fetched directly on 2026-08-31.
- **Medium confidence / third-party-sourced, not independently re-verified against the live primary site this pass:** Outlier.bet's annual pricing figures; OddsJam's base +EV tier price and hit-rate-alert threshold; Action Network BetSync's exact supported-book list (documentation, not the live product surface); BettorEdge's Premium tier price (not found on-site at all).
- **Explicitly blocked and unresolved:** oddsjam.com and oddsjam.com/pricing returned HTTP 403 to our fetcher both directly and via headless Chromium (which also hit connection resets — consistent with active bot-protection on gambling-adjacent domains). props.cash, linemate.io, and actionnetwork.com/pro also could not be rendered by headless Chromium in this environment (consistent connection resets across repeated attempts, most likely TLS-fingerprint-based bot detection) — for those three, this report instead used the sites' own live JS bundles/redirected checkout pages fetched via plain HTTPS, which is a direct, dated, primary-source read, just not a rendered screenshot.
- No screenshots were captured — the rendering blockers above meant no browser session got far enough to produce one. `docs/COMPETITIVE_INTELLIGENCE/screenshots/` was created but is currently empty.
- Not yet done: a second pass specifically re-testing Outlier.bet and OddsJam's own trend/props screens (not just marketing pages) for sample-size/denominator handling, since that's the single most decision-relevant open question left in this report.
