# Segment: AI / Prediction Platforms

Scope: products whose core pitch is AI-generated picks, projections, or predictions (as opposed to pure odds-comparison or DFS tools). Covers **PlayerProps.ai**, **Rithmm**, **BetQL**, **PropsBot.ai**, **PropJuice.ai**.

Research date: **2026-08-31** (all "date verified" fields below are this date unless noted). Researcher: automated research pass, docs-only, no accounts created, no paywalls bypassed.

---

## 0. Methodology, confidence key, and a hard limitation to disclose

**Confidence tags used throughout:**
- `[DIRECT]` — I fetched/rendered the primary company page myself today and am quoting/paraphrasing what it showed.
- `[APP-STORE-DIRECT]` — I fetched the Apple App Store or Google Play listing myself today (primary source for IAP pricing, but iOS/Android pricing can differ from a company's own web pricing).
- `[3P-REVIEW, publish date]` — a third-party review site's content, not the vendor's own page. Flagged because several of these (notably PropsBot.ai and its own blog) are **competitor-authored content** reviewing rivals (Rithmm, PlayerProps.ai) — read their framing with that bias in mind, though the specific quoted mechanics (ledger structure, methodology text) were themselves quoting the vendor's own site.
- `[SEARCH-SUMMARY]` — a search engine's synthesized answer citing multiple pages, not a page I read directly. Lowest confidence; used only where direct fetch failed and no better source existed.
- `UNVERIFIED` / `UNKNOWN` — used explicitly per the task's rules rather than a plausible guess.

**Environment limitation (important, affects every product below):** The task allowed driving headless Chromium for pages WebFetch renders poorly. I set this up (Node's Playwright, `/opt/pw-browsers` Chromium) and it launches fine, but **every navigation attempt through this session's outbound proxy fails with `net::ERR_CONNECTION_RESET`**, including a control test against `https://example.com`. The proxy's own status endpoint (`/__agentproxy/status`) confirms this is systemic, not a per-site block: `recentRelayFailures` shows the same `ws_closed_mid_exchange` (tunnel closed after ~6s) pattern against `example.com`, `redirector.gvt1.com` (Chromium's own update-check host), `old.reddit.com`, and the actual targets (`playerprops.ai`, `oddsjam.com`, `props.cash`). This is a proxy/relay-level timeout on the WebSocket-tunneled raw TCP that browser automation needs, not something fixable from inside this session (I did not disable TLS verification or unset `HTTPS_PROXY`, per policy). **Net effect: no screenshots were captured for this segment.** `docs/COMPETITIVE_INTELLIGENCE/screenshots/` exists but is empty for this file. Brand/visual-style notes below are therefore based on WebFetch's rendered text description (which for at least one product — PlayerProps.ai — only ever returned a client-side-rendering "loading" shell, not the hydrated page) plus what third-party reviews say about the visuals. **Treat every color/visual claim below as lower-confidence than the pricing and feature claims**, and a later pass should retry screenshots once the proxy issue is fixed.

A second, related limitation: **PlayerProps.ai (playerprops.ai) is a client-side-rendered SPA.** Every WebFetch attempt against its marketing site and `/pricing` page returned only the loading shell — literally the text "V4.0 AI LOADING" / "Initializing predictions" — because WebFetch does not execute JavaScript. I could not get the headless browser working (see above) to force a render. **I was not able to independently confirm PlayerProps.ai's own pricing page today.** Everything reported for PlayerProps.ai's pricing/features/claims below is `[APP-STORE-DIRECT]` (partial), `[3P-REVIEW]`, or `[SEARCH-SUMMARY]` — flagged per line. This is exactly the "say UNKNOWN rather than guess" case the brief anticipated.

---

## 1. PlayerProps.ai

| Field | Value |
|---|---|
| URL | https://playerprops.ai |
| Date verified | 2026-08-31 (own site could not be rendered past loading screen — see limitation above) |
| Customer type | B2C, self-serve, individual bettor |
| Sports covered | NBA, NFL, MLB, NHL, WNBA, CFB (college football), CBB (men's college basketball), WCBB (women's college basketball). Advertised as "coming soon": PGA, major soccer leagues, tennis, League of Legends, Dota 2, CS2. `[3P-REVIEW, propsbot.ai, 2026-07-19]` |
| Markets covered | Player props (over/under), moneyline, spread, total, NRFI, first-five (F5) predictors. `[3P-REVIEW]` |

### Pricing — CORRECTION TO PRIOR LEAD

The preliminary lead of **~$59/mo / $499/yr is directionally close but not exact**, and it omits a product that materially changes the "free tier" answer:

| Plan | Price | Source confidence |
|---|---|---|
| Monthly (direct/web) | **$59/mo** | `[3P-REVIEW, propsbot.ai, 2026-07-19]` |
| Monthly (Apple IAP) | **$59.99/mo** | `[3P-REVIEW]`; not independently re-confirmed via App Store fetch today (rate-limited, HTTP 429) |
| Annual (Apple IAP) | **$499.99/yr** | `[3P-REVIEW]`; matches the preliminary lead's $499/yr almost exactly (off by $0.99) |
| 6-month | **$295** ("buy 5 months, get 1 free") | `[SEARCH-SUMMARY]` |
| **Week Pass** | **$20 for 7 days**, creditable toward a monthly subscription if upgraded | `[3P-REVIEW, propsbot.ai]` — **this is a real "week pass" tier the original lead didn't mention** |
| Free trial | **No unrestricted free trial.** Only the paid $20 week pass plus "limited free tool access." | `[3P-REVIEW]` — **corrects an implicit assumption; do not assume a standard free-trial pattern here** |

Free tier: limited free tools only (exact scope UNKNOWN — not itemized in any source I could read). Sport-specific plans: UNKNOWN/likely absent — reviewed pricing describes one tier covering "every tool and every sport," not a per-sport split (contrast with BetQL below). Pro tier: UNKNOWN — no separate "Pro" tier name found; the product appears to be single-tier (monthly/annual/week-pass) rather than multi-tier like Rithmm/BetQL.

Mobile app: yes, iOS + Android (`ai.playerprops.app` on Google Play; `id6502717388` on App Store). Web app: yes (the SPA itself).

### Feature checklist (from third-party review + own-site text fragments seen)

Present: AI predictions/projections (player props with over/under views), "BetScore" proprietary 1–100 ranking for both sides of a market, opponent splits/usage filters/home-away splits, line movement tracking, odds comparison across books, game markets (moneyline/spread/total/NRFI/F5), team trends, public betting splits, educational "How To Win" system + beginner mode, Discord community, mobile + web apps.

Absent / not found in any source: AI chat/conversational assistant (no evidence of one — contrast Rithmm's "Scout"), explicit model-builder / custom-model tools, bankroll management tool, arbitrage or +EV calculator by name, API access, sportsbook direct integration/bet placement, backtesting tool exposed to users, weather data, injuries/lineups as a named distinct feature (UNKNOWN — plausible but not confirmed), historical-data export.

All of the above is `[3P-REVIEW]` confidence — **none of it was independently confirmed against the live site today** due to the SPA rendering limitation.

### Messaging & positioning

- Hero headline: **UNKNOWN** — could not render the live homepage; the review site's own headline ("PlayerProps.ai Review 2026: Award-Winning Prop Tool Worth $60/Month?") is the reviewer's framing, not PlayerProps.ai's own copy.
- Primary promise (as characterized by review): AI-powered research/education to help "everyday bettors make smarter, more confident decisions" — framed as *research assistant*, not *guaranteed winner*.
- Target persona (per review): beginner-to-intermediate bettors who want to be taught "how to think," with an aside that it's best suited to "serious, disciplined bettors with $1,000+ bankroll." `[3P-REVIEW]`
- Primary CTA: UNKNOWN (site unrenderable).
- Social proof: **250,000+ user community** (per company press release, see awards below), **19,000+ Discord members** `[3P-REVIEW]`. CEO named in press: Trevis Waters.
- Accuracy/ROI claim: PlayerProps.ai **does not publish a quantified accuracy or ROI number** on the page the reviewer read. Exact quote from the review: *"PlayerProps.ai does not guarantee profits, and past performance does not predict future results."* The only number-adjacent statement found is the reviewer's own break-even math, not a company claim: *"break-even (betting $100/week) = $60/mo cost = need +15% ROI improvement."* That +15% is the **reviewer's** calculation, not PlayerProps.ai's claim — do not attribute it to the vendor.

### Claims interrogation — the "Most Accurate" and "Business of the Year" awards

Two award claims recur across press coverage (BusinessWire press release, Rutland Herald syndication, casinobeats.com interview):

1. **"Most Accurate NFL Prop Prediction App" — BetSmart 2025 Accuracy Contest.** I could not find, via search, an independent methodology page for "BetSmart" describing sample size, time period, or scoring rules for this contest. **Who runs BetSmart, what games/props were scored, over what window, and against what benchmark is UNKNOWN** — treat this as an unverified third-party contest claim until its methodology can be located and read directly.
2. **"2025 Sports Betting Business of the Year" — Fantasy Sports & Gaming Association (FSGA).** This one is more verifiable as an *award existing* (FSGA is a real, named industry trade association, and the company's press release names FanDuel and DraftKings as the only past winners, which is a checkable, specific claim). However, an industry-association "Business of the Year" award is a **business/growth recognition, not an accuracy or predictive-performance credential** — it says nothing about whether the AI predictions are good. The press release also states the company passed **$1M ARR** and **250,000+ users**, both self-reported/company-sourced figures with no independent audit found.

**Bottom line on PlayerProps.ai's evidence for its "AI accuracy" pitch: no public, line-by-line, pre-game-timestamped ledger was found by the third-party reviewer either** (exact quote: *"We did not find a public line-by-line historical ledger on the open web"* that non-subscribers could audit) — and that reviewer explicitly warns *"community scale and testimonials are adoption signals, not an accuracy test."* This is a meaningful gap: two industry awards, zero disclosed track record.

### Brand

Primary/accent colors: **UNVERIFIED.** The original lead's "dark purple-pink neon identity" could not be confirmed or refuted today — the live site only rendered a loading screen (white logo on presumably dark background, but color values not extractable from that fragment), and no third-party review described the current color palette in enough detail to confirm or deny "purple-pink neon." One relevant, dateable fact: the product's own App Store copy describes a **"V3.0" redesign** ("complete redesign from the ground up... modern, lightning-fast interface with clearer charts, **fresher colors**, and more intuitive screens") and the loading screen seen today says **"V4.0"** — meaning the app has gone through at least one more visual refresh since. **If the "dark purple-pink neon" read came from pre-V3.0/V4.0 screenshots, it is likely stale.** Recommend re-checking with a working screenshot pipeline before using this in any competitive one-pager.

Visual category (per one review's characterization, not my own observation): **"AI-tech + sports-media hybrid with education focus,"** explicitly contrasted against "flashy casino aesthetics." Take this as one reviewer's read, not a confirmed brand audit.

Logo style: UNKNOWN (only saw a small white wordmark in a loading state).

---

## 2. Rithmm

| Field | Value |
|---|---|
| URL | https://rithmm.com |
| Date verified | 2026-08-31 `[DIRECT]` |
| Customer type | B2C, self-serve, individual bettor — explicitly positioned as "everyday sports bettors," anti-jargon |
| Sports covered | NFL, NBA, MLB, WNBA, Golf, College Football, College Basketball `[DIRECT]`; a World Cup 2026 beta also advertised per one review `[3P-REVIEW]` |
| Markets covered | Player props (with win probabilities), spread, totals, moneyline `[DIRECT]` |

### Pricing — CORRECTION TO PRIOR LEAD

The preliminary monthly figures were **exactly right**; the annual figures were **missing from the lead entirely** and had to be sourced third-party (Rithmm's own site does not display annual pricing on its main pricing view):

| Plan | Monthly | Annual | Confidence |
|---|---|---|---|
| Core | **$29.99/mo** | **$239.99/yr** (≈$19.99/mo effective — advertised as "4 months free") | Monthly `[DIRECT]`; annual `[3P-REVIEW, propsbot.ai, 2026-07-19]` |
| Pro | **$49.99/mo** | annual price not found in any source — UNKNOWN | Monthly `[DIRECT]` |
| Premium | **$99.99/mo** | **$999.99/yr** (≈$83.33/mo effective — advertised as "2 months free") | Monthly `[DIRECT]`; annual `[3P-REVIEW]` |

Free trial: **7 days, all tiers**, "no expertise required," no credit-card-required language was not explicitly confirmed either way. Free tier (no-cost ongoing access): none found — this is trial-then-paid. Week pass: not offered. Sport-specific vs all-sport plans: **all three tiers appear to cover all sports** (tiers differ by *feature depth* — Scout AI usage, model-copying, advanced factor tools — not by sport count). This is a structural difference from BetQL, which tiers by sport count.

Mobile app: not explicitly confirmed on the page fetched (UNKNOWN — likely exists given "mobile-first approach" language, but I did not verify an app-store listing). Web app: yes.

### Feature checklist

Present `[DIRECT]`: AI predictions on every game, player-prop analysis with win probabilities, spread/totals/moneyline analysis, line shopping across major sportsbooks, an AI chat-style analyst named **"Scout"** (Pro/Premium only — "Ask Scout what's good tonight," reasoning explanations, bet verification), **custom model building** (user-created or AI-generated — a genuine model-builder, not just picks), performance tracking/filtering, "Smart Signals" pattern highlighting, parlay builder, bet-slip export tools.

Absent / not found: dedicated bankroll-management module (UNKNOWN — not mentioned), arbitrage/+EV calculator by name, public bet-percentage / sharp-money indicator (UNKNOWN), news/injuries/weather modules (UNKNOWN — not mentioned in the fetched content), community feature beyond a Discord link, backtesting exposed as a named feature (adjacent: "performance tracking" exists, but not confirmed as a forward-looking backtest tool), API access.

### Messaging & positioning

- Hero headline (exact quote): **"Never sweat another pick alone."** `[DIRECT]`
- Subheadline (exact quote): **"AI sports predictions, player prop analysis, and sportsbook line comparisons built for everyday sports bettors."** `[DIRECT]`
- Primary CTA (exact quote): **"Try Rithmm Free →"** with supporting text "7 DAYS FREE · No expertise required" `[DIRECT]`
- Target persona: explicitly *not* the quant/data-scientist bettor — copy leans on "no spreadsheets," "no code," accessibility-first language, while simultaneously offering a genuine model-builder for the users who do want to go deep. `[DIRECT]`
- Social proof: user testimonials only, no user-count or press-logo claims seen. Exact testimonial quotes: *"Rithmm helps me fine tune my process"* and language about the product *"eliminates the emotional side of betting."* `[DIRECT]`
- Accuracy/ROI claim: **Rithmm's own site makes none.** Exact language found: *"Recommended bets with an edge"* and copy about *"whether your models agree, where the edge is"* — "edge" here is **not defined** on-page (not tied to a percentage, an EV formula, or a time-boxed backtest). There is an explicit disclaimer: **"No guarantees of outcomes are made."** `[DIRECT]`

### Claims interrogation — the "72% NBA accuracy" figure

**This number does NOT come from Rithmm.** It originates from a third-party aggregator/comparison article (TheAISurf.com, dated March 2026) that ranked several AI prediction tools and credited Rithmm with "the highest observed accuracy at 72% on NBA spread picks based on independent testing." I could not locate TheAISurf's own methodology for that "independent testing" — no disclosed sample size, date range, or scoring rules were found in the search results, and I did not fetch that article directly to check for one. **This is a third-party claim about Rithmm, not a Rithmm marketing claim, and it should not be repeated as "Rithmm says 72%."** A separate reviewer (PropsBot.ai, itself a competitor) explicitly notes that **no public, line-by-line prediction ledger exists on the open web for Rithmm that a non-subscriber could independently filter**, and cautions that user reviews are weak evidence of accuracy. Net: Rithmm's own site is unusually disciplined about *not* making a quantified accuracy claim; the 72% number bettors may encounter searching for Rithmm is an outside party's unaudited number, not the vendor's.

### Brand

Colors: primarily dark background with white/light logo/wordmark per the rendered page; a specific accent hex was not extractable from WebFetch's text-only rendering (screenshots unavailable — see limitation). Typography feel: modern, minimalist sans-serif implied by "clean" copy but not independently confirmed. Logo style: white wordmark, no further detail available. Visual category: reads as **AI-tech**, reinforced by the "Scout AI analyst" framing and explicit avoidance of jargon/spreadsheet language — does not read casino-like based on copy tone (no odds-boost/neon-jackpot language anywhere in the fetched copy).

---

## 3. BetQL

| Field | Value |
|---|---|
| URL | https://betql.co |
| Date verified | 2026-08-31 `[DIRECT]` for homepage; pricing page itself would not render text content via WebFetch (numbers are baked into pricing-comparison images) |
| Customer type | B2C, self-serve; also runs an explicit affiliate program |
| Sports covered | NCAAF, NFL, MLB, MLS, EPL, Bundesliga, LaLiga, Serie A, UEFA Champions League, World Cup, NHL, NBA, NCAAB, ATP, WTA, Golf `[DIRECT]` — the broadest sport list of the five products reviewed |
| Markets covered | Spread, moneyline, totals, 1st/2nd-half spreads, player props, first-five-innings (MLB) `[DIRECT]` |

### Pricing — the messiest data point in this report; three conflicting sources found

I could not render BetQL's own `/pricing` pages (JS-driven; WebFetch saw only nav links). BetQL's **own support-center article** (`support.betql.co`, a primary source) confirms the *structure* but embeds actual dollar figures in images that couldn't be extracted: it names **"Premium"** and **"Sharp"** as plan tiers, sold in **weekly, three-month, and annual** durations, with "Premium... more limited" and "Sharp... full access to the entire product" `[DIRECT-partial]`. That structure — tiers named by sport-count, priced weekly/monthly/annual — is corroborated by a source I *did* fetch directly and fully:

**`[APP-STORE-DIRECT]` — Apple App Store listing (`id1334825645`), fetched 2026-08-31, in-app purchases as literally listed on the page:**

| Tier | Sports included | Monthly | Annual |
|---|---|---|---|
| Premium | 1 sport | $19.99 | $59.99 |
| Pro | 2 sports | $24.99 | $99.99 |
| VIP | 3 sports | $29.99 | $149.99 |
| Sharp | All sports | $49.99 | $299.99 |
| All Sports Day Pass | All sports, 24 hours | $4.99 flat | — |

This is a genuine **sport-specific vs. all-sport plan structure** — unique among the five products reviewed, and a meaningfully different pricing model (pay more only if you want more sports) than PlayerProps.ai/Rithmm's single all-sport tiers.

**Two other sources partially conflict and should not be treated as authoritative:**
- A search-engine-summarized answer (not independently fetched) gave the same tier *names* but different numbers (Premium $14.99, Pro $19.99, VIP $24.99, day pass $2.99, plus separate "weekly" rates like $2.99–$6.99/week). This looks like it may be blending web pricing, promotional pricing, or an older price point with the Apple IAP numbers above — **I flag it as lower-confidence and did not use it in the table**, since the App Store fetch is a primary, directly-observed source as of today.
- A third-party review (SportBotAI, dated 2026-01-06) described an entirely different tier scheme — **"Basic" $19.99/mo, "Standard" $29.99/mo, "Premium" $49.99/mo** — that does not match BetQL's own tier names ("Premium/Pro/VIP/Sharp") at all. This is either a stale/incorrect review or describes a different, older BetQL pricing scheme from before a restructure. **Do not use the Basic/Standard/Premium naming — it conflicts with BetQL's own current support documentation.**

**Recommendation for the synthesis pass:** treat the App Store table above (Premium/Pro/VIP/Sharp, $19.99–$49.99/mo) as the best-available number today, sourced 2026-08-31, but flag it for re-verification once BetQL's own `/pricing` page can be rendered (iOS IAP pricing can run higher than web/direct pricing for exactly this kind of product).

Free tier: yes — "Get Started for Free" is the primary homepage CTA; scope of the free tier is UNKNOWN (not itemized in rendered content). Free trial: a third-party review claims "a limited free trial" exists in addition to the always-free tier — UNVERIFIED, possibly conflating the free tier itself with a trial.

Mobile app: yes (App Store confirmed). Web app: yes.

### Feature checklist

Present `[DIRECT]`: computer-model picks ("Bets based on Hottest Trends," 1-to-5-star rating system), "Most Popular Right Now" (crowd-activity signal), full odds display (spread/moneyline/totals/halves), **public betting-percentage data**, **"Sharp Picks"** (professional-bettor activity signal — the clearest "sharp book reference" style feature of the five products), **line-movement tracker updating every 5 minutes**, expert daily articles, promotional/odds-boost offers, player props, first-five-innings MLB markets.

Absent / not found: AI chat assistant, model-builder/custom-model tools, bankroll-management tool, arbitrage/+EV calculator by name, parlay-builder tool (UNKNOWN — not seen, though "same-game parlay" content exists editorially per search results for a sibling CBS-style product, not confirmed for BetQL itself), API access, backtesting tool for users.

### Messaging & positioning

- Hero headline (exact quote): **"Your one-stop shop for sports betting picks, analysis, and sports offers."** `[DIRECT]`
- Primary CTA (exact quote): **"Get Started for Free"** (secondary: "Learn More") `[DIRECT]`
- Target audience: explicit dual-segment language for "casual and serious bettors," with content segmented by experience level. `[DIRECT]`
- Accuracy/edge claim (exact quote): **"Each game or match is simulated 10,000 times based on all available data providing BetQL subscribers with a fact based prediction and clear probability projections."** `[DIRECT]`

### Claims interrogation — "10,000 simulations"

This is a **Monte-Carlo-style methodology claim, which is more methodologically specific than any other product in this segment** (compare: Rithmm's undefined "edge," PropJuice's undefined "ensemble of 30+ models," PlayerProps.ai's undisclosed methodology). However, what's still **not disclosed**: what inputs feed the simulation, how the model is validated/backtested, what its actual historical hit rate or ROI has been, whether that 10,000-simulation figure is fixed across all sports/markets or varies, and whether any independent party has audited the simulation's outputs against results. A third-party review (SportBotAI) explicitly notes **no ROI or win-rate guarantee is made anywhere**, quoting BetQL/the review as: *"No betting platform can guarantee winning bets, as sports outcomes are inherently uncertain."* So: specific-sounding methodology language, but **zero disclosed track record** — the same evidentiary gap as the AI-native competitors, just dressed in more technical-sounding language ("10,000 simulations" vs. "AI-powered").

### Brand

Colors/typography: UNKNOWN — WebFetch's rendering did not surface CSS/color data and screenshots were unavailable (see limitation). Visual category, based on copy/content structure alone: reads as **sports-media-like** (star ratings, "hottest trends," "most popular right now," daily expert articles) blended with **finance-like data-terminal elements** (line-movement tracker, public-betting-percent data, sharp-money signal) — this is the least "AI-tech" feeling of the three original named competitors based on copy tone; it emphasizes data/trends framing over "AI" framing, despite the 10,000-simulation claim.

---

## 4. PropsBot.ai (discovered — additional AI prediction competitor #1)

| Field | Value |
|---|---|
| URL | https://propsbot.ai |
| Date verified | 2026-08-31 `[DIRECT]` |
| Customer type | B2C, self-serve, positions itself as "serious bettors seeking automated research to replace manual spreadsheet analysis" |
| Sports covered | NFL, NBA, MLB, NHL, WNBA, NCAAF, PGA Golf, UFC, eSports, Bare Knuckle (BKFC), Soccer (EPL/La Liga/Bundesliga/Serie A/Ligue 1/MLS), Tennis, KBO — **the widest sport list found in this segment, including niche combat/esports coverage no competitor here offers** `[DIRECT]` |
| Markets covered | Player props (with a proprietary "0–100 Confidence Score" and "Edge Score"), moneyline, spread, totals `[DIRECT]` |

### Pricing

| Plan | Price | Effective monthly |
|---|---|---|
| Monthly | **$49.99/mo** | $49.99 |
| 6-month | **$254.99** | ≈$42/mo |
| Annual | **$419.99/yr** | ≈$35/mo ("save $180") |

Free trial: **7 days, "cancel anytime."** `[DIRECT]` Free tier: appears to be trial-only, not an ongoing free tier (site framing is "Start Free — 7 days"). Week pass: not offered. Sport-specific plans: none found — single all-sport tier structure like Rithmm/PlayerProps.ai.

Mobile/web app: web app confirmed; mobile app UNKNOWN (not confirmed either way in fetched content).

### Feature checklist

Present `[DIRECT]`: AI player-prop predictions with a 0–100 confidence score, "Edge Score," player-prop dashboard, daily top-5 picks, advanced filtering, **line shopping across 25+ sportsbooks**, private strategy Discord, tutorials/walkthroughs, and — notably — **a public, self-described track record/ledger** (see claims section below).

Absent / not found: AI chat assistant, model-builder, bankroll tool, arbitrage calculator by name, API access, weather/lineups/injuries as named modules (UNKNOWN).

### Messaging & positioning

- Hero headline (exact quote, seasonal/dynamic): **"NFL research starts now. Your matchup tools are ready."** `[DIRECT]`
- Subheadline (exact quote): **"The regular-season board is still building. Use current picks and player-prop pages for available markets."** `[DIRECT]` — notably honest/hedged in-season copy, not an evergreen claim.
- Primary CTA (exact quote): **"Start Free — 7 days, cancel anytime."** `[DIRECT]`
- Accuracy/ROI claim (exact figures found): **"27.8% ROI"**, **"218,826 Props graded"**, **"+95 units tracked profit"**, **"101,881 verified MLB outcomes"**, **"4.8★ Average rating."** `[DIRECT]`

### Claims interrogation — the most transparent methodology found in this segment, with real caveats

Of all five products, **PropsBot.ai discloses the most about its own grading methodology**, per its own `/track-record/` page `[DIRECT]`:
- Picks are logged **before games begin**, with **a timestamp and a posted line captured at publication**, and the **closing line is also captured** — meaning it explicitly supports comparing its picks against both the line-at-publication and the closing line, not just the final outcome. Exact quote: *"every pick was published before its game started, with a timestamp and a posted line."*
- "Graded" is explicitly defined: *"A pick that was published with a timestamp and a posted line before the game started. Pre-game only. We don't grade live in-game picks against the same ledger."*
- There is a user-facing dashboard (`dashboard.propsbot.ai`) that can be **sorted and date-ranged by the visitor** — "Sort the table by date, sport, signal, edge, or result" / "Pull a date range to verify a specific stretch" — this is a genuine self-serve audit tool, not just a marketing stat.

**What is still NOT disclosed / still a gap:**
- **No independent third-party audit** — explicitly self-reported: *"the result is graded against the actual outcome, and the rolling totals update automatically"* by their own system, with no named external auditor.
- **The exact date range for the headline 27.8% ROI / 218,826-props figure is not stated on the page** — it's an all-time or rolling cumulative number of unstated duration, updated "weekly" per their own text. A reader cannot tell if this is a hot streak, a cherry-picked stretch, or a genuine multi-season average without opening the dashboard and doing the date-range work themselves.
- "Edge" (used as a sort/filter dimension) is not defined on the page fetched — UNKNOWN whether it means EV, book-line delta, or a proprietary score.

**Net assessment: best-in-segment transparency infrastructure (timestamped, closing-line-referenced, self-serve-auditable ledger), but still self-graded with no independent audit, and the headline number's time window is unstated.** This is the most defensible "AI accuracy" claim of the five products, but "most defensible" is not the same as "audited" — worth naming precisely in any competitive narrative.

### Brand

Colors/typography: described secondhand as "modern dashboard interface, blue/tech color scheme, mobile-responsive app design" by the fetch tool's summarization of the rendered page — not independently screenshot-confirmed (see limitation), so treat the specific "blue" as provisional. Visual category: reads as **AI-tech / SaaS-dashboard-like** based on copy and structure (confidence scores, sortable dashboard, "Edge Score") rather than casino- or sports-media-like.

---

## 5. PropJuice.ai (discovered — additional AI prediction competitor #2)

| Field | Value |
|---|---|
| URL | https://propjuice.ai |
| Date verified | 2026-08-31 `[DIRECT]` |
| Customer type | B2C, self-serve |
| Sports covered | NBA, NFL, MLB (per homepage); MLB matchup models specifically flagged as newly live for the 2026 season `[DIRECT]` — narrowest sport coverage of the five products |
| Markets covered | NBA: spreads, totals, player props. NFL: spreads, moneyline, totals, player props. MLB: moneyline, spread, total, batter props, pitcher props. `[DIRECT]` |

### Pricing

**UNKNOWN / UNVERIFIED.** The homepage references a pricing URL, a free trial, and a refund policy, but does not state tier names or dollar amounts in the content WebFetch could read, and I did not locate a working `/pricing` render. **Do not report a PropJuice price without going back to verify — none was found.** Free tier: a "free probability calculator tool" is offered standalone. `[DIRECT]`

Mobile app: **yes, iOS app confirmed**, described as including alerts and bet tracking. `[DIRECT]` Web app: yes.

### Feature checklist

Present `[DIRECT]`: predictions from a stated **"ensemble of 30+ models,"** player props across multiple stat categories, spreads/totals/moneyline, a letter-grade pick system (**"A through B recommended"**), a free probability calculator, live results tracking broken out by grade, iOS app with alerts and bet tracking.

Absent / not found: AI chat, model-builder/custom models, line shopping across books (UNKNOWN — not confirmed), bankroll tool, arbitrage calculator, API, parlay builder, injuries/weather/lineups modules (UNKNOWN).

### Messaging & positioning

- Hero headline (exact quote): **"AI-powered sports betting analytics platform that uses an ensemble of 30+ models."** `[DIRECT]`
- Positioning detail: the page references a **"DOD forecasting heritage"** — i.e., invokes a defense/military-forecasting pedigree as a credibility signal. This is a distinctive claim not seen elsewhere in the segment and **could not be verified** (no named individual, program, or contract was surfaced) — flag as an unverified credibility claim, not a confirmed fact.
- Accuracy claims (exact figures quoted on-page): **"NBA spreads 75%, NBA player props up to 80%, NFL spreads and moneyline 70%, NFL totals 65%."** `[DIRECT]` — these are the **highest headline accuracy percentages found anywhere in this segment**, notably higher than the 72% NBA figure that a third party (not PropJuice itself) credited to Rithmm.

### Claims interrogation — highest numbers, thinnest disclosed sample

PropJuice states picks are **"timestamped before game time"** and results are **"scored against closing lines from major sportsbooks"** rather than raw final-score outcomes — a real methodological detail (comparable to PropsBot's closing-line capture). However:
- **No sample size or time period is disclosed for the headline percentages** (75% / 80% / 70% / 65%). The page's own MLB section undercuts confidence in the other sports' numbers by admitting, for MLB specifically: *"Early season — tracking live"* and *"hit-rate populates as the sample matures."* That caveat is not repeated for the NBA/NFL numbers, but nothing on the page indicates those numbers have a larger or more mature sample either.
- The site's own methodology language admits this is early-stage: **"These results represent our initial development phase."** This is an unusually candid admission sitting directly alongside the segment's highest accuracy percentages — a real tension worth naming explicitly: **the biggest numbers in the segment come with the most explicit self-disclosed "still early" caveat.**
- Explicitly self-graded, no independent audit: **"We grade and post our own results"** / **"We publish outcomes; we don't place bets."**
- "Recommended bet win rate" is scoped to **grade A–B picks only** — i.e., the headline percentages likely describe a filtered subset of all predictions (their best-graded picks), not all predictions issued. The page doesn't state what share of total picks fall into A–B, so the denominator for these percentages is unclear.

**Net assessment: PropJuice makes the boldest quantified accuracy claims in the segment, while simultaneously disclosing (more candidly than most competitors) that the underlying sample is early-stage and self-graded, and without clarifying what fraction of picks the headline rate actually covers.** This is a genuinely useful finding for a "here's what to watch for" competitive narrative — the biggest number and the thinnest support sit in the same paragraph.

### Brand

Colors/typography/logo: **UNKNOWN** — not described by the fetch tool's summarization and not screenshot-confirmed. Visual category: UNKNOWN.

---

## 6. Cross-product comparison (matrix-ready)

### 6.1 Pricing snapshot

| Product | Monthly | Annual | Week/Day pass | Free trial | Free tier | Sport-specific plans? |
|---|---|---|---|---|---|---|
| PlayerProps.ai | $59 (site) / $59.99 (Apple) `[3P-REVIEW]` | $499.99 `[3P-REVIEW]` | **$20/7-day week pass** `[3P-REVIEW]` | None unrestricted | Limited free tools only | No (one all-sport tier) |
| Rithmm | $29.99 / $49.99 / $99.99 (Core/Pro/Premium) `[DIRECT]` | $239.99 (Core) / UNKNOWN (Pro) / $999.99 (Premium) `[3P-REVIEW]` | None | 7 days, all tiers `[DIRECT]` | None (trial-then-paid) | No (tiers = feature depth, all sports) |
| BetQL | $19.99 / $24.99 / $29.99 / $49.99 (Premium/Pro/VIP/Sharp) `[APP-STORE-DIRECT]` — **conflicting sources exist, see §3** | $59.99 / $99.99 / $149.99 / $299.99 `[APP-STORE-DIRECT]` | **$4.99 all-sports day pass** `[APP-STORE-DIRECT]` | Unclear — "limited free trial" claimed `[3P-REVIEW]`, unverified | **Yes — "Get Started for Free" is the primary CTA** `[DIRECT]` | **Yes — tiers scale by number of sports (1/2/3/all)** |
| PropsBot.ai | $49.99 `[DIRECT]` | $419.99 `[DIRECT]` | None | 7 days `[DIRECT]` | Trial-only | No |
| PropJuice.ai | UNKNOWN | UNKNOWN | UNKNOWN | Referenced but terms UNKNOWN | Free probability calculator only | UNKNOWN |

### 6.2 Feature presence matrix

`Y` = confirmed present, `N` = not found (may still exist — see per-product notes), `U` = unknown/unclear, all at `[DIRECT]`/`[3P-REVIEW]` confidence as detailed above (not independently verified behind any paywall).

| Feature | PlayerProps.ai | Rithmm | BetQL | PropsBot.ai | PropJuice.ai |
|---|---|---|---|---|---|
| AI chat / conversational assistant | N | **Y ("Scout")** | N | N | N |
| AI predictions / picks | Y | Y | Y | Y | Y |
| AI explanations / reasoning shown | U | Y (Scout reasoning) | N | U | U |
| Player props | Y | Y | Y | Y | Y |
| Spread | Y | Y | Y | Y | Y |
| Total | Y | Y | Y | Y | Y |
| F5 (first five innings) | Y | U | Y | U | U |
| NRFI | Y | U | U | U | U |
| Live odds | Y | Y | Y | U | U |
| Line movement | Y | U | **Y (5-min refresh)** | U | U |
| Best line / line shopping | U | Y | U | **Y (25+ books)** | U |
| +EV / arbitrage tool (named) | N | N | N | N | N |
| Sharp book / sharp money reference | U | U | **Y ("Sharp Picks")** | U | U |
| Public bet % | U | U | **Y** | U | U |
| Bet tracking | U | Y (play tracking) | U | U | Y (app feature) |
| Bankroll tool | N | N | N | N | N |
| Custom models / model builder | N | **Y** | N | N | N |
| Parlay tools | U | Y | U | U | U |
| News | U | U | Y (daily articles) | U | U |
| Injuries / weather / lineups | U | U | U | U | U |
| Historical data / public ledger | N (none found) | N (none found) | U | **Y (sortable, date-rangeable)** | Y (results page, self-graded) |
| Alerts | U | U | U | U | Y (iOS app) |
| Community (Discord etc.) | Y | Y (link only) | N | Y (private Discord) | U |
| Backtesting (user-facing) | N | U | N | U | U |
| API | N | N | N | N | N |
| Sportsbook integration (bet placement) | N | N | N | N | N |
| Mobile app | Y | U | Y | U | Y |
| Web app | Y | Y | Y | Y | Y |

### 6.3 Headline accuracy/ROI claims, side by side

| Product | Claim as stated | Who's making the claim | Methodology disclosed? | Pre-game timestamped? | Independently audited? |
|---|---|---|---|---|---|
| PlayerProps.ai | "Most Accurate NFL Prop Prediction App" (BetSmart 2025); "Sports Betting Business of the Year" (FSGA 2025) | Third-party contest/award bodies, publicized by PlayerProps.ai | BetSmart methodology: **not found**. FSGA: business award, not an accuracy metric | Unknown | No (no public ledger found by third-party reviewer) |
| Rithmm | None on Rithmm's own site ("edge" undefined). "72% NBA accuracy" is a **third party's** number, not Rithmm's claim | TheAISurf.com (comparison site), not Rithmm | Not found | Unknown | No (reviewer found no public ledger) |
| BetQL | "Each game... simulated 10,000 times... fact based prediction and clear probability projections" | BetQL itself | Simulation count stated; inputs/validation not disclosed | Unknown | No |
| PropsBot.ai | "27.8% ROI," "218,826 Props graded," "+95 units," "101,881 verified MLB outcomes" | PropsBot.ai itself | **Most disclosed**: timestamp + posted line + closing line captured at publication; user-sortable/date-rangeable dashboard | **Yes, explicitly** | No (self-graded, no named external auditor) |
| PropJuice.ai | "NBA spreads 75%, NBA player props up to 80%, NFL spreads/ML 70%, NFL totals 65%" | PropJuice.ai itself | Scored vs. closing line, stated; sample size/date range **not disclosed**; site itself calls results "initial development phase" | Yes, claimed ("timestamped before game time") | No (self-graded: "We grade and post our own results") |

---

## 7. Findings summary

**Corrections to the preliminary rumor:**
- PlayerProps.ai: $59/mo and $499/yr were **close to correct** ($59.99/mo, $499.99/yr per Apple IAP, per third-party review) — but the rumor **missed the $20/7-day week pass** and the fact that there's **no unrestricted free trial**, only that paid week pass. Brand identity ("dark purple-pink neon") is **UNVERIFIED today** — could not render the live site, and the product has been through at least two redesigns (V3.0, now V4.0) since whatever screenshot the original lead was based on, so it may simply be out of date.
- Rithmm: $29.99/$49.99/$99.99 monthly tiers were **exactly correct**. The rumor said nothing about annual pricing, which turned out to require a third-party source to find at all ($239.99/yr Core, $999.99/yr Premium; Pro's annual price is UNKNOWN).
- BetQL: no prior pricing lead was given; found conflicting numbers across three sources, resolved to the App Store's own listing (Premium $19.99 → Sharp $49.99/mo, tiered by sport count 1/2/3/all) as the highest-confidence figure available today, but flagged for re-verification once the site itself renders.

**Surprising/noteworthy findings for a synthesis pass:**
1. **Only Rithmm has a real AI-chat feature ("Scout")** among these five — "AI chat" as a category is mostly unbuilt in this segment despite "AI" branding everywhere.
2. **Only BetQL ties tiers to sport count** (1/2/3/all sports); the four AI-native products all sell one all-sport tier. This is a genuinely different pricing architecture worth a deliberate decision either way for us.
3. **None of the five products expose an arbitrage/+EV calculator, bankroll tool, or API** — this whole segment leaves that functionality to a different competitor category (line-shopping/odds tools), suggesting either whitespace or a signal that AI-prediction users don't demand it.
4. **Transparency is genuinely uneven and gradable**, exactly as hypothesized: PropsBot.ai has real timestamped/closing-line-referenced/self-serve-auditable infrastructure (best-in-segment, still self-graded/unaudited); PropJuice.ai makes the highest numbers in the segment while its own copy admits "initial development phase" and doesn't disclose sample size; Rithmm and PlayerProps.ai make essentially no quantified claims on their own sites at all (Rithmm explicitly disclaims guarantees; PlayerProps.ai's "accuracy" credentials are outsourced entirely to two industry-award bodies with no visible methodology); BetQL's "10,000 simulations" sounds rigorous but discloses nothing about validation. **No product in this segment has a third-party-audited track record.** That is the single clearest opening for a differentiation claim, but note it as an opening, not yet a fact about our own product.
5. Two award/credibility claims (PlayerProps.ai's "BetSmart 2025 Accuracy Contest," PropJuice's "DOD forecasting heritage") could not be traced to a checkable methodology or named source at all — these read as the weakest evidentiary claims in the whole segment and would be easy, low-risk contrast points if we can independently confirm we don't make unverifiable claims like these.

**Unresolved / needs a follow-up pass:**
- PlayerProps.ai's own site render (blocked by SPA + proxy issue) — pricing, hero copy, full feature list, and brand colors all need direct re-verification.
- BetQL's own `/pricing` numbers, to resolve the three-way conflict noted in §3.
- PropJuice.ai pricing (entirely unfound).
- All screenshot/brand-color capture for all five products — blocked today by the proxy relay issue described in §0, not by anything site-specific. Retry once that's fixed.
- Rithmm Pro-tier annual price.
- BetSmart contest methodology and PropJuice's "DOD forecasting heritage" claim — worth one more targeted search pass if these claims matter to the synthesis.

---

*This file is additive — later synthesis passes should lift rows from §6 directly into a master matrix rather than re-deriving them.*
