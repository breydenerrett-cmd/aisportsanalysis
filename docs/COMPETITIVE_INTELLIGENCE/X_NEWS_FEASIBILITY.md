# News-Speed Feasibility: Can We Beat Books to Public News?

Checked 2026-08-31. Prices/limits change — re-verify before committing spend.

## Costed comparison

| Source | Access tier | Price (checked 2026-08-31) | Latency | Coverage | Commercial terms | Verdict |
|---|---|---|---|---|---|---|
| X API v2 | Pay-per-use (default, no subscription now) | $0.005/post read, $0.015/post write ($0.20 if link), $0.010/user read; **capped 3M post reads/mo** on pay-per-use, Enterprise required above that | Near-real-time if polling/filtered-stream endpoints used, but filtered-stream/pricing detail page did not confirm stream inclusion at pay-per-use tier — UNKNOWN, needs Enterprise sales confirmation | Full public post firehose/search if entitled | Standard X dev terms apply (display/attribution, no full-corpus redistribution) — not independently re-verified here | Workable at low volume (single beat-reporter watchlist, filtered polling) for likely tens of dollars/month; NOT viable for broad multi-account real-time streaming, which historically sits behind Enterprise (~$42k+/mo per third-party reporting, not confirmed on an official page) |
| X API legacy Basic/Pro | Grandfathered only, closed to new signups | Basic $200/mo, Pro $5,000/mo (per third-party reporting, not on an official current page — UNKNOWN reliability) | N/A — unavailable to us as a new customer | N/A | N/A | Not available to a new project |
| MLB StatsAPI | Public, no key | Free for individual, non-commercial, non-bulk use | Near-real-time (already used in this repo) | MLB rosters, transactions, injuries as published by MLB | Copyright notice (gdx.mlb.com/components/copyright.txt): commercial or bulk use requires prior written authorization from MLB Advanced Media | Already in use; fine for internal research, but a commercial product needs to seek MLBAM authorization — flag before scaling |
| Bluesky Firehose / Jetstream | Public AT Protocol firehose | $0 — no paid tier, rate-limited by points (5,000 pts/hr, post=3pts) | Real-time (firehose push) | Whoever posts on Bluesky — beat-reporter coverage is much thinner than X | Free use; Bluesky's own docs say funded/commercial projects relying on it are expected to run their own Relay or pay an infra provider for an SLA — no fee to Bluesky itself, but reliability isn't free | Cheapest real-time option, but coverage gap (fewer beat reporters) limits its value as an X substitute |
| RotoWire (RSI) syndication | Licensed feed, sales-negotiated | UNKNOWN — no price on public pages, requires contacting RotoWire's sales/syndication team | Reported real-time injury/lineup/depth-chart feed | NFL/NBA/MLB/NHL injuries, confirmed lineups, depth charts, player news | Commercial licensing is the explicit business model (syndicated to media companies) — terms negotiated per client | Credible commercial alternative to raw X polling for injury/lineup news specifically; price unknown until we ask, but worth a quote |
| News wires (AP, official league RSS/press feeds) | Public RSS / press-release feeds | Free | Minutes, not seconds — wires publish after initial breaking, not synchronous with beat-reporter tweets | Official transactions/press releases only | Generally fine for factual redisplay with attribution; verify per-feed ToS before redistribution | Good backbone for confirmed facts, too slow to be the "first" signal |
| Weather APIs (e.g., NWS, OpenWeatherMap) | Public/free tier | NWS free; OpenWeatherMap has free tier + paid | Minutes | Game-day conditions | Generally permissive; check specific ToS | Fine, low-priority relative to injury/lineup news |

## The honest latency question

Books run dedicated trading desks and automated feeds watching the same public sources we would watch (beat reporters, official team accounts, wires). Public reporting and industry commentary consistently describes regulated books pulling markets or props within seconds to low minutes of a significant break — that is the standard they operate to, and it is faster than a small independent team can realistically match on ingestion-to-market-close latency alone, especially without a direct relationship or paid low-latency feed.

**What a small product can realistically achieve:** being organised, not first. A pipeline that ingests public sources (X polling on a narrow beat-reporter watchlist, MLB StatsAPI, league wires, maybe a licensed injury feed) and immediately surfaces "here's what changed, here's whether the line has already moved" in one place has real value even running seconds-to-low-minutes behind the books, because most users are not watching a trading desk's feed themselves — they're watching nothing, or watching scattered sources manually. The product's edge is aggregation and clarity, not speed superiority over the market.

**What it cannot realistically achieve:** consistently beating a regulated book's own market move. Treat "beat the books" as effectively unavailable at this budget and team size; do not build a strategy around it.

## Legal/ToS flags (not legal advice)

- MLB StatsAPI: commercial/bulk use requires MLBAM's prior written authorization — currently used here for research; get that authorization before shipping anything commercial that leans on it.
- X API: standard platform terms on display/attribution and no bulk redistribution of the raw corpus apply; not independently re-verified in this pass — get current ToS text before building.
- RotoWire/RSI: licensing is the whole model, so terms will be spelled out in a contract — no redistribution assumptions until that contract exists.
- Bluesky: free, but "commercial project relying on the firehose without paying for reliable infra" is explicitly flagged by Bluesky's own docs as not really free at scale.

## Recommendation

A news-speed product built primarily on the X API is not viable at "small independent product" budget beyond a narrow, low-volume watchlist (a short list of beat reporters, polled, well under the 3M-read pay-per-use cap) — broad real-time coverage historically requires Enterprise-tier pricing that has not been confirmed on an official current page but is reported in the tens of thousands of dollars per month. The affordable version of the idea is not "beat the books" but "organise and surface" — combine the free/cheap backbone (MLB StatsAPI, official wires, Bluesky) with a narrow paid X watchlist and, if budget allows, a quoted RotoWire syndication feed for injuries/lineups, and present users with a clear "what changed / has the market moved" view rather than promising them a speed edge the product cannot deliver.
