# Sources — Customer Pain Research

Append-only log. Format: `[date checked] URL — what was pulled`.

## Fetched directly (WebFetch / direct HTTP, content read in full)

- [2026-08-31] https://www.trustpilot.com/review/playerprops.ai — individual dated reviews, star ratings
- [2026-08-31] https://www.trustpilot.com/review/oddsjam.com — individual dated reviews, star ratings
- [2026-08-31] https://justuseapp.com/en/app/1334825645/betql-sports-betting/reviews — aggregated App Store review complaints for BetQL, safety score
- [2026-08-31] https://itunes.apple.com/us/rss/customerreviews/page=1/id=1334825645/sortby=mostrecent/json — BetQL App Store reviews, page 1
- [2026-08-31] https://itunes.apple.com/us/rss/customerreviews/page=2/id=1334825645/sortby=mostrecent/json — BetQL App Store reviews, page 2
- [2026-08-31] https://itunes.apple.com/us/rss/customerreviews/page=1/id=1083677479/sortby=mostrecent/json — Action Network App Store reviews, page 1
- [2026-08-31] https://itunes.apple.com/us/rss/customerreviews/page=2/id=1083677479/sortby=mostrecent/json — Action Network App Store reviews, page 2
- [2026-08-31] https://itunes.apple.com/us/rss/customerreviews/page=1/id=1586567110/sortby=mostrecent/json — Pikkit App Store reviews, page 1
- [2026-08-31] https://itunes.apple.com/us/rss/customerreviews/page=2/id=1586567110/sortby=mostrecent/json — Pikkit App Store reviews, page 2
- [2026-08-31] https://itunes.apple.com/us/rss/customerreviews/page=1/id=6443885102/sortby=mostrecent/json — Outlier App Store reviews, page 1
- [2026-08-31] https://itunes.apple.com/us/rss/customerreviews/page=2/id=6443885102/sortby=mostrecent/json — Outlier App Store reviews, page 2
- [2026-08-31] https://itunes.apple.com/us/rss/customerreviews/page=1/id=1606752641/sortby=mostrecent/json — Props.Cash App Store reviews, page 1
- [2026-08-31] https://itunes.apple.com/us/rss/customerreviews/page=2/id=1606752641/sortby=mostrecent/json — Props.Cash App Store reviews, page 2
- [2026-08-31] https://itunes.apple.com/us/rss/customerreviews/page=1/id=6448072108/sortby=mostrecent/json — OddsJam App Store reviews, page 1
- [2026-08-31] https://itunes.apple.com/us/rss/customerreviews/page=2/id=6448072108/sortby=mostrecent/json — OddsJam App Store reviews, page 2
- [2026-08-31] https://itunes.apple.com/us/rss/customerreviews/page=1/id=6502717388/sortby=mostrecent/json — PlayerProps.ai App Store reviews, page 1
- [2026-08-31] https://itunes.apple.com/us/rss/customerreviews/page=2/id=6502717388/sortby=mostrecent/json — PlayerProps.ai App Store reviews, page 2
- [2026-08-31] https://itunes.apple.com/us/rss/customerreviews/page=1/id=1641010681/sortby=mostrecent/json — Rithmm App Store reviews, page 1
- [2026-08-31] https://itunes.apple.com/us/rss/customerreviews/page=2/id=1641010681/sortby=mostrecent/json — Rithmm App Store reviews, page 2
- [2026-08-31] https://itunes.apple.com/us/rss/customerreviews/page=1/id=1525948689/sortby=mostrecent/json — Betstamp App Store reviews, page 1
- [2026-08-31] https://itunes.apple.com/us/rss/customerreviews/page=2/id=1525948689/sortby=mostrecent/json — Betstamp App Store reviews, page 2

Each RSS feed returned up to 100 individual dated, star-rated user reviews (author handle, date, title, full text). All quotes in CUSTOMER_PAIN.md sourced from these feeds are traceable to this feed URL pattern (`itunes.apple.com/us/rss/customerreviews/page=N/id=<APP_ID>/sortby=mostrecent/json`).

## Attempted, blocked or failed

- [2026-08-31] old.reddit.com and www.reddit.com (search.json, subreddit listings, plain HTML) — all requests (via WebFetch, curl through the session's egress proxy, and a Playwright/Chromium headless browser through the same proxy) returned HTTP 302 redirects to `/login/?reason=lor2`, i.e. Reddit's anti-bot/login wall triggered for this session's egress IP. No Reddit content (r/sportsbook, r/sportsbetting, r/dfsports, r/baseball) could be read directly in this session, live or via Reddit's public JSON API.
- [2026-08-31] Chromium/Playwright fetches to several other hosts (google.com, oddsjam.com, playerprops.ai, props.cash) intermittently failed with proxy-level `ws_closed_mid_exchange` errors (tunnel closed after ~6s) — this looks like a general limitation of browser-based fetches through this session's egress proxy, not a per-site block.
- [2026-08-31] html.duckduckgo.com/html search — returned a CAPTCHA challenge page, no results extracted.
- [2026-08-31] www.bing.com/search (site:reddit.com query) — returned irrelevant results (R programming language), no Reddit content surfaced.
- [2026-08-31] play.google.com/store/apps/details (Google Play reviews, PlayerProps.ai) — page content truncated before reaching the review list; no Android reviews captured this way.

## WebSearch-only (tool-synthesized answers, not independently re-fetched — cited in CUSTOMER_PAIN.md as "reported via aggregator/search summary", not as directly-read primary source)

- [2026-08-31] WebSearch: reddit.com r/sportsbook multi-tool research workflow queries (multiple phrasings) — did not surface indexable Reddit thread text; Reddit itself appears to not be well-indexed for these query shapes in this environment.
- [2026-08-31] WebSearch: "Rithmm review" — surfaced bettingnews.com/tools/rithmm-app-review/, oddsplays.com/reviews/rithmm/, propsbot.ai/rithmm-review/, sportbotai.com/blog/tools/rithmm-review (not independently re-fetched; pricing figures cross-checked against Rithmm's own App Store listing context)
- [2026-08-31] WebSearch: "PlayerProps.ai review reddit cancel" — surfaced trustpilot.com/review/playerprops.ai (independently fetched, see above), oddsplays.com/reviews/playerprops-ai/, propsbot.ai/best-ai-sports-betting-app/
- [2026-08-31] WebSearch: "OddsJam review worth it cancel subscription" — surfaced getarbitragebets.com/blog/oddsjam-review, picksandparlays.net/reviews/ai-picks/oddsjam (synthesized claims about bankroll/discipline requirements, not independently verified)
- [2026-08-31] WebSearch: "Outlier.bet review reddit" — surfaced xclsvmedia.com/is-outlier-bet-worth-it..., propfirmreviews.net/blog/outlier-bet-review/
- [2026-08-31] WebSearch: "BetQL review reddit cancel subscription complaint" — surfaced justuseapp.com/en/app/1334825645 (independently fetched, see above), justanswer.com thread, cappertek.com review
- [2026-08-31] WebSearch: AI picks skepticism / "no better than guessing" / verified track record queries — surfaced sportbotai.com/blog/best-ai-for-sports-betting-reddit and sportbotai.com/blog/best-betting-app-reddit (claims about r/algobetting sentiment attributed to these secondary summaries, not to a directly-read Reddit thread)
- [2026-08-31] WebSearch: verified-record/tout-skepticism queries — surfaced marketing copy from competing prop tools (Juice Reel, PropsBot, Stat Sniper) explicitly positioning "publicly auditable pick ledger" / "verified from synced sportsbook accounts" as a differentiator — treated as indirect market evidence that unverifiable track records are a known pain point, not as a bettor's own complaint.

## Added by SEGMENT_AI_PREDICTION.md research pass (2026-08-31)

### Fetched directly (WebFetch, content read; browser screenshots blocked — see note below)

- [2026-08-31] https://playerprops.ai — SPA loading shell only ("V4.0 AI LOADING"); JS did not render for WebFetch
- [2026-08-31] https://playerprops.ai/pricing — same SPA loading shell, no pricing content reachable
- [2026-08-31] https://rithmm.com — homepage, hero copy, pricing tiers, features
- [2026-08-31] https://rithmm.com/pricing — tier breakdown (Core/Pro/Premium monthly prices, 7-day trial)
- [2026-08-31] https://betql.co — homepage hero, feature list, sports list
- [2026-08-31] https://betql.co/pricing/monthly — nav only, no pricing content rendered
- [2026-08-31] https://betql.co/pricing — nav only, no pricing content rendered
- [2026-08-31] https://betql.co/pricing/annual — nav only, no pricing content rendered
- [2026-08-31] https://support.betql.co/hc/en-us/articles/360047974514-Pricing — confirmed "Premium"/"Sharp" tier names and weekly/3-month/annual durations; dollar figures embedded in images, not extractable as text
- [2026-08-31] https://apps.apple.com/us/app/betql-sports-betting/id1334825645 — full in-app-purchase list with exact prices (Premium/Pro/VIP/Sharp, monthly + annual)
- [2026-08-31] https://propsbot.ai/ — homepage hero, pricing, features, headline accuracy/ROI figures
- [2026-08-31] https://propsbot.ai/track-record/ — grading methodology, timestamp/closing-line disclosure, dashboard description
- [2026-08-31] https://propsbot.ai/playerprops-ai-review/ — third-party review (competitor-authored) of PlayerProps.ai: pricing, features, week-pass detail, awards skepticism, dated 2026-07-19
- [2026-08-31] https://propsbot.ai/rithmm-review/ — third-party review (competitor-authored) of Rithmm: annual pricing, features, dated 2026-07-19
- [2026-08-31] https://propjuice.ai/ — homepage hero, ensemble-model claim, accuracy percentages
- [2026-08-31] https://propjuice.ai/results — accuracy methodology page: closing-line scoring, "initial development phase" admission, self-grading disclosure
- [2026-08-31] https://picksandparlays.net/reviews/ai-picks/playerprops-ai — third-party review, brand/positioning read, dated 2026-08-26
- [2026-08-31] https://www.sportbotai.com/blog/tools/betql-review — third-party review with conflicting Basic/Standard/Premium pricing (flagged as likely stale/inconsistent with BetQL's own tier names), dated 2026-01-06

### Attempted, blocked or failed

- [2026-08-31] Headless Chromium via Node Playwright (`/opt/pw-browsers`), proxied through `$HTTPS_PROXY` — every navigation attempt failed with `net::ERR_CONNECTION_RESET`, confirmed systemic (not site-specific) via a control test against `https://example.com` which failed identically. Proxy status endpoint's `recentRelayFailures` showed matching `ws_closed_mid_exchange` (tunnel closed ~6s) entries for `example.com`, `redirector.gvt1.com`, `old.reddit.com`, `playerprops.ai`, `oddsjam.com`, `props.cash`. No screenshots captured for this pass; `docs/COMPETITIVE_INTELLIGENCE/screenshots/` remains empty. Did not disable TLS verification or unset `HTTPS_PROXY` to work around this, per policy.
- [2026-08-31] https://support.betql.co/hc/en-us/articles/360047974514-Pricing via r.jina.ai reader proxy — returned page shell noting pricing is presented as images, no dollar figures extracted
- [2026-08-31] https://web.archive.org/web/2026/https://playerprops.ai/pricing — WebFetch tool reported it is unable to fetch from web.archive.org
- [2026-08-31] https://apps.apple.com/us/app/betql-sports-betting/id1451774951 — HTTP 404 (wrong app ID; correct ID 1334825645 used instead, see above)
- [2026-08-31] https://apps.apple.com/us/app/playerprops-ai-premium-monthly/id6502717388 — HTTP 429 Too Many Requests, not re-attempted
- [2026-08-31] https://play.google.com/store/apps/details?id=ai.playerprops.app&hl=en_US — content truncated before reaching app description/pricing

### WebSearch-only (tool-synthesized, not independently re-fetched)

- [2026-08-31] WebSearch: "playerprops.ai" pricing "$59" OR "$499" — corroborated propsbot.ai review figures ($59/mo, $499.99/yr, $20 week pass)
- [2026-08-31] WebSearch: BetQL app store in-app purchases pricing — returned a numerically different tier table (Premium $14.99/Pro $19.99/VIP $24.99/Sharp $49.99) than the directly-fetched App Store page; treated as lower-confidence and not used in the report's pricing table given the conflict
- [2026-08-31] WebSearch: Rithmm annual pricing — surfaced propsbot.ai/rithmm-review/ figures ($239.99/yr Core, $999.99/yr Premium), corroborated by direct fetch of that review
- [2026-08-31] WebSearch: Rithmm "72%" NBA accuracy source — traced to theaisurf.com (March 2026 comparison article), a third party, not Rithmm's own claim; theaisurf.com article itself was not independently fetched
- [2026-08-31] WebSearch: "BetSmart" "2025 Accuracy Contest" PlayerProps.ai — surfaced businesswire.com press release and app-store copy; no BetSmart methodology page located
- [2026-08-31] WebSearch: FSGA "Sports Betting Business of the Year" 2025 — surfaced businesswire.com/rutlandherald.com press coverage and thefsga.org/industry-awards/ (award-body page itself not independently fetched)
- [2026-08-31] WebSearch: PlayerProps.ai screenshot/brand color queries — returned no usable visual-design source; brand color claims for PlayerProps.ai remain unverified for this pass

## Added by SEGMENT_SHARP_ODDS.md research pass (2026-08-31)

### Fetched directly (WebFetch, content read)

- [2026-08-31] https://unabated.com — homepage hero, testimonials, feature list
- [2026-08-31] https://unabated.com/pricing — redirected (301) to tools.unabated.com/pricing
- [2026-08-31] https://tools.unabated.com/pricing — page fetched but pricing values are client-rendered (React/Next.js), no dollar figures present in fetched content
- [2026-08-31] https://betstamp.com — homepage, six B2B customer segments, product list
- [2026-08-31] https://www.betstamp.com/pro — PRO Odds Screen pricing ($249/mo base + add-ons), features, sports/book coverage, target audience
- [2026-08-31] https://www.betstamp.com/comparison/oddsjam — Betstamp's vendor-authored comparison claims about OddsJam pricing/features (biased source, flagged as such)
- [2026-08-31] https://outlier.bet — homepage hero, three-tier pricing, social proof, testimonial quote
- [2026-08-31] https://outlier.bet/pricing — HTTP 404 (wrong URL guess)
- [2026-08-31] https://help.outlier.bet/en/articles/12556823-choosing-the-right-outlier-plan-for-your-betting-style — per-tier feature breakdown confirming DVIG/no-VIG EV badge, sharp-book comparison, arbitrage feed language
- [2026-08-31] https://oddsjam.com — HTTP 403 (Cloudflare bot challenge, `cf-mitigated: challenge`)
- [2026-08-31] https://oddsjam.com/pricing — HTTP 403 (same Cloudflare challenge)
- [2026-08-31] https://oddsjam.com/subscribe — HTTP 403 (same)
- [2026-08-31] https://oddsjam.com/checkout?plan=gold&term=month — HTTP 403 (same)
- [2026-08-31] https://oddsjam.com/positive-ev — HTTP 403 (same)
- [2026-08-31] http://web.archive.org/web/20260603165706/https://oddsjam.com/pricing — Wayback Machine snapshot (2026-06-03) of OddsJam's pricing page; nav/feature copy recovered, but pricing figures are loaded client-side via API and were absent even from this archived HTML (confirmed by inspecting the embedded `__NEXT_DATA__` JSON, which contains no plan/price data)
- [2026-08-31] https://www.oddsshopper.com — homepage hero, feature list, testimonials
- [2026-08-31] https://www.oddsshopper.com/pricing — HTTP 404 (guessed URL, pricing not located this pass)
- [2026-08-31] https://rebelbetting.com — homepage hero, pricing (Starter/Pro), profit/ROI claims, social proof

### Attempted, blocked or failed

- [2026-08-31] Headless Chromium via Node Playwright (`/opt/pw-browsers`) and via the raw `chrome` binary directly, both proxied through `$HTTPS_PROXY` — every navigation attempt failed (`ERR_CONNECTION_RESET` / `SSL error code 1, net_error -101`), reproduced against a trivial control site (`https://example.com`) and confirmed via the proxy status endpoint (`ws_closed_mid_exchange`, tunnel closed ~6s, affecting example.com, google.com, old.reddit.com, props.cash). This is a systemic incompatibility between headless Chromium's TLS client and this session's egress proxy, not a per-site block — curl to the same hosts succeeded instantly every time. No screenshots captured this pass; did not disable TLS verification or unset `HTTPS_PROXY` to work around it.
- [2026-08-31] curl (via Bash) to `http://web.archive.org/...` (plain HTTP, not https) — returned "Blocked by egress policy"; retried with `https://` and succeeded (see above). Note for future workers: use https:// for web.archive.org, not http://.

### WebSearch-only (tool-synthesized, not independently re-fetched)

- [2026-08-31] WebSearch: OddsJam Gold/Platinum pricing 2026 — surfaced rotowire.com/betting/oddsjam-review, oddsplays.com/reviews/oddsjam/, xclsvmedia.com/oddsjam-review-2026-..., getarbitragebets.com/blog/oddsjam-pricing; figures inconsistent across sources (Gold ~$199/mo, Platinum ~$499/mo most common, one source cites $999/mo as likely-stale). Not independently re-fetched — OddsJam's own site is Cloudflare-blocked.
- [2026-08-31] WebSearch: Unabated pricing tiers 2026 — surfaced xclsvmedia.com/unabated-review-2026-..., getarbitragebets.com/blog/unabated-review, betherosports.com/blog/unabated-alternative; cited Props+ $99/mo, Premium $199/mo ($167/mo annual), Concierge $799/mo ($667/mo annual). Not independently confirmed on tools.unabated.com (client-rendered pricing, see above).
- [2026-08-31] WebSearch: Gambling.com acquires OddsJam parent 2026 — surfaced businesswire.com, igamingbusiness.com, cdcgaming.com, yogonet.com, nasdaq.com press coverage confirming Gambling.com Group's acquisition of Odds Holdings Inc. (OddsJam's parent), $80M upfront + up to $80M earnout through end of 2026. Multiple independent financial-press sources corroborate; treated as high confidence despite not being independently re-fetched.
- [2026-08-31] WebSearch: Betstamp free app history/shutdown/pivot 2026 — surfaced appbrain.com, play.google.com, apps.apple.com listings showing the consumer "Betstamp: Bet Tracker & Props" app remains actively updated (100,000+ downloads, updated July 2026) alongside the separately-positioned B2B "Betstamp PRO" product.
- [2026-08-31] WebSearch: RebelBetting bookmaker limits/bans — surfaced rebelbetting.com/blog/how-to-handle-bookmaker-limitations-what-to-do-when-you-get-limited (title/existence confirmed, not opened in full), letscomparebets.com review, betmok.com blog on avoiding arbitrage bans.
- [2026-08-31] WebSearch: Unabated sharp-book/market-maker methodology — surfaced unabated.com/articles/who-sets-the-sports-betting-line-market-makers and unabated.com/post/what-is-the-unabated-line (titles/summaries only, not independently opened), valuebetfactory.com, picktheodds.app discussing Pinnacle/Circa as market-making reference books generally.
- [2026-08-31] WebSearch: Reddit/forum discussion of sportsbook limiting OddsJam/+EV users — surfaced trustpilot.com/review/oddsjam.com and several Substack posts (itsnotgambling, closingline, howgamblingworks) discussing sportsbook limiting practices and regulatory attention (Massachusetts); a specific user complaint about being "banned on every sportsbook... within 3 days" was reported via the search tool's synthesis, not independently traced to its original Reddit thread — treat as UNVERIFIED-secondary.

## Segment: Prop Research & Tracking/Consumer Platforms — checked 2026-08-31 (worker: props/tracking segment research)
- https://props.cash/ — 2026-08-31 (raw HTML shell + meta description)
- https://props.cash/static/js/main.573c667a.js — 2026-08-31 (live production JS bundle, read for pricing/feature/copy strings)
- https://apps.apple.com/us/app/props-cash-prop-pick-finder/id1606752641 — 2026-08-31
- https://linemate.io/ — 2026-08-31 (raw HTML shell + meta description)
- https://linemate.io/static/js/main.594d7c3c.js — 2026-08-31 (live production JS bundle)
- https://www.linemate.io/pricing — 2026-08-31 (redirect target, same SPA shell)
- https://apps.apple.com/us/app/linemate-find-your-next-bet/id1635246793 — 2026-08-31
- https://oddsjam.com/ — 2026-08-31 (HTTP 403, blocked)
- https://oddsjam.com/pricing — 2026-08-31 (HTTP 403, blocked)
- https://apps.apple.com/us/app/oddsjam-sharp-sports-betting/id6448072108 — 2026-08-31
- https://outlier.bet/ — 2026-08-31 (fetched and rendered)
- https://www.actionnetwork.com/pro — 2026-08-31 (redirects to /subscribe)
- https://www.actionnetwork.com/subscribe — 2026-08-31 (fetched and rendered directly, primary pricing source)
- https://apps.apple.com/us/app/action-network-sports-betting/id1083677479 — 2026-08-31
- https://pikkit.com/ — 2026-08-31 (fetched and rendered directly)
- https://apps.apple.com/us/app/pikkit-sports-bet-tracker/id1586567110 — 2026-08-31
- https://www.juicereel.com/ — 2026-08-31 (fetched and rendered directly)
- https://apps.apple.com/us/app/juice-reel-bet-tracker-tips/id1527960097 — 2026-08-31
- https://www.bettoredge.com/ — 2026-08-31 (fetched and rendered directly)
- WebSearch aggregator results (oddsplays.com, betsmart.co, picksandparlays.net, xclsvmedia.com, sportshandle.com, bettednews.com, rotogrinders.com, bvcompany.org, mybets.gg) — 2026-08-31, used only as secondary/cross-check, not as primary source; flagged inline in SEGMENT_PROPS_TRACKING.md wherever relied upon
