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
