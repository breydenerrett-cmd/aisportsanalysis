# Honest Competitor Scorecard

Scored 2026-08-31. Subject is **our current shipped product** — the static
generator described in `docs/PRODUCT_ARCHITECTURE_AUDIT.md` and `DEBRIEF.md`
section B (`artifacts/briefing.html`, `artifacts/analyze_*.html`, opened from
disk, no accounts, no URL, no server) — **not** the future SaaS. Each
dimension is scored against the single strongest competitor found for that
dimension, per the evidence in `COMPETITOR_MATRIX.csv` and the three segment
docs. 0–5 scale. One evidence sentence per cell. `UNKNOWN` where the
competitor-side evidence is itself unverified (screenshots were blocked all
session; several sites were access-blocked — see each segment doc's
confidence notes).

**Brey's instruction, followed literally: do not rig it.** Four dimensions
below score us a flat 0 with no hedging. This is not a marketing document.

Scale used throughout:
- 0 = does not exist / not offered
- 1 = token or severely limited
- 2 = present but shallow
- 3 = competitive, average for the category
- 4 = strong, above-average
- 5 = best-in-class / category-defining

---

## The scores

| Dimension | Us | Evidence (us) | Best competitor | Their score | Evidence (them) |
|---|---|---|---|---|---|
| **Data depth** | 3 | Point-in-time stats, injuries, weather, lineups, historical box scores feed the detectors (`DEBRIEF.md` §B); standard-library only, no paid data vendor. | PropsBot.ai / Betstamp | 4 | PropsBot.ai spans 13 sports incl. niche esports/combat; Betstamp claims 5+ seasons backtested data across 200+ books — broader breadth than our single-sport pipeline. |
| **Matchup depth** | 5 | Lineup-vs-actual-starter decomposition, starter "stuff" (velocity gap vs league, GB share), debunks weak samples in plain language ("7-for-18 lifetime... means nothing") — nothing found in any competitor does the contradicting half of this. | Rithmm / Outlier | 3 | Rithmm's "Scout" answers matchup questions on request; Outlier shows weather/injuries/matchups but reviewers say it "makes things seem like a good bet" with no debunk framing. |
| **AI analysis** | 2 | Detectors and synthesis are rule-based/statistical, not an LLM; there is no chat interface; explanations are pre-written, not generative. | Rithmm | 4 | "Scout" is the only confirmed real AI-chat/reasoning feature in the segment ("I just ask scout" — praised repeatedly in reviews); still not independently audited. |
| **Explainability** | 5 | Every claim states its own sample size in the sentence; evidence labels (`TESTED_NULL` etc.) are structurally enforced, ranking refuted claims below open questions — no competitor was found doing this. | PropsBot.ai | 2 | Discloses timestamp/posted-line/closing-line per pick (best in segment) but does not label individual claims by evidentiary strength the way ours does. |
| **Transparency (as shipped)** | 1 | The evidence machinery (25+ hypotheses, published nulls, falsification battery) lives in `docs/`, not in the product a customer would ever open — CHECKPOINT.md's own words: "our transparency is unshipped." | PropsBot.ai | 4 | Self-serve, sortable, date-rangeable public track-record dashboard — self-graded, no external auditor, but genuinely customer-facing, which ours is not yet. |
| **Trust (as perceived by a customer)** | 0 | There is no product a customer can find, sign up for, or read a review of; perceived trust requires a perceiver, and there is currently no audience. | Betstamp / PropsBot.ai | 3 | Neither is externally audited either (no competitor found has third-party audit), but both have live customers, App Store ratings, and a visible track record to be trusted or distrusted. |
| **News speed** | 2 | "What changed" roster-event timeline exists and is built from pre-cutoff data only (`DEBRIEF.md` §B), but it is descriptive/relevance-tiered, not a live real-time feed, and X/news integration was only feasibility-probed (`X_NEWS_FEASIBILITY.md`), not shipped. | Action Network | 3 | Free tier includes live pick/game alerts and a sharp-action report refreshed on their own schedule; not verified as faster than seconds-level book reaction. |
| **Market intelligence** | 2 | De-vigged consensus and dispersion (Engine 1) are built and tested; no public-bet%, no sharp-money signal, no cross-book EV/arb scanner. | BetQL / Betstamp | 4 | BetQL ships public bet% and a named "Sharp Picks" signal; Betstamp's "True Line" is a market-maker-referenced benchmark refreshed sub-second across 200+ books. |
| **Odds coverage** | 2 | Price-improvement figures exist against de-vigged consensus for the sports/markets in scope; single-sport, and book count is not documented as competitive with the segment leaders. | Betstamp | 5 | 200–207+ sportsbook/operator feeds including PPH/offshore/prediction markets, 400ms median refresh — the widest and fastest coverage found in the entire corpus. |
| **Props** | 1 | Only a capped feasibility probe exists (`PRODUCT_ARCHITECTURE_AUDIT.md` roadmap notes); no shipped player-prop product surface. | PropsBot.ai | 4 | Props across 13 sports with a 0–100 confidence score and Edge Score, plus a self-serve track-record dashboard scoped to props specifically. |
| **Line shopping** | 2 | Price-improvement is computed and explicitly never called EV or edge in code/docs/copy (a real, evidenced differentiator per `PRICING.md`), but there is no live multi-book comparison UI a customer can browse. | Pikkit / PropsBot.ai | 4 | Pikkit shops 30+ books live and free; PropsBot.ai shops 25+ books; both are interactive, browsable, and free-tier or near-free-tier accessible. |
| **Historical tools** | 3 | Point-in-time reconstruction and a season archive index (`artifacts/archive.html`) exist and are test-enforced for correctness. | Betstamp | 4 | 5+ seasons of backtested/historical data marketed as a named product feature with an uptime SLA behind it; broader scope, still not customer-browsable the way ours is. |
| **Backtesting** | 5 | A falsification battery, placebo noise ceilings, and published nulls across V1–V6 (`DEBRIEF.md` §E) — no competitor found does anything comparable; this is the single deepest methodological asset in the corpus on either side. | Rithmm | 2 | One reviewer praises being able to "backtest the models you create" via Scout — real, but self-serve and unaudited, nowhere near the falsification rigor described in §E. |
| **Strategy research** | 5 | 25+ pre-registered hypotheses across six research families, effect-size and significance gates, a documented process for killing ideas including the project's own best-looking candidate. Nothing in the corpus resembles this; it is not a competitor category at all. | — | 0 | No competitor publishes anything like a research program; "10,000 simulations" (BetQL) and "ensemble of 30+ models" (PropJuice.ai) are black-box claims with no disclosed validation. |
| **Tracking** | 0 | No bet-tracking, no sportsbook sync, no account to track anything against. | Pikkit | 5 | Free, credential-based sync across 30+ books, real-time, encrypted, read-only — the clearest best-in-class feature found in the entire matrix. |
| **Alerts** | 0 | No accounts, so no alerting mechanism of any kind exists. | Betstamp | 4 | Steam alerts on True Line moves >2.5%, sub-second refresh; Action Network and Outlier also ship real-time alerts free or near-free. |
| **Trust — the earned claim, honesty machinery itself** | 5 | 25+ hypotheses, every loser published, a falsification battery, published nulls, honest "no demonstrated betting edge" headline when nothing clears the bar — CHECKPOINT.md: "not one [competitor] has a third-party-audited record... That is an empty position, and it happens to be the only one this project has actually earned." | — | 1 | Every competitor audited (17 products) promises more (edge, sharpness, accuracy); the most transparent (PropsBot.ai) is still self-graded; none makes publishing its own losses a headline promise. |
| **Mobile** | 0 | Pages open from `file://`; there is no mobile app, no responsive web app, no installable surface at all. | PlayerProps.ai / Rithmm / most segment | 4 | Native iOS/Android apps are the category default — 12+ of 17 audited products confirmed a mobile app. |
| **Visual polish** | 1 | Generated static HTML, no design system audit performed, no screenshots exist of our own product for comparison; functional but not evaluated against a design bar. | Pikkit / Rithmm | 4 | Described (per fetch-tool text, not screenshot-verified for competitors either — see caveat) as clean, modern, minimalist; Pikkit specifically: "clean, modern, minimalist; dark/light UI with blue accents." |
| **Pricing** | UNKNOWN | We have a proposed price ($29.99 one-sport / $49.99–59.99 all-sport per `PRICING.md`) but no live billing, no product to buy — there is nothing to score as "pricing" for a real customer today. | — | UNKNOWN | Every competitor has live, chargeable pricing; comparing "our proposal" to "their live price" would score a plan against a product, which is not a fair comparison — hence UNKNOWN rather than a number. |
| **Community** | 0 | No Discord, no forum, no social feed, no user base to have a community. | Unabated / PropsBot.ai / PlayerProps.ai | 4 | PlayerProps.ai's Discord (19,000+ members) is the single most emotionally loaded praise cluster in the entire customer-pain corpus — members explicitly credit community/education over the picks themselves. |
| **Unique IP** | 5 | Point-in-time reconstruction pipeline, falsification battery, placebo noise ceilings, an evidence-label taxonomy enforced structurally, and the Ranker's Engine-2-gated architecture (an honesty mechanism, not a feature) — no analog found anywhere in the corpus. | — | 1 | BetQL's sport-count pricing architecture and Outlier's named "DVIG/no-VIG" math are the closest things to distinctive IP found among competitors, and both are packaging/labeling choices, not methodology. |

---

## Reading the table straight

**Where we win outright (score ≥4, beating a real competitor or standing
alone):** matchup depth, explainability, backtesting, strategy research, the
honesty machinery itself, unique IP. These are not close calls — no
competitor in the 17-product corpus does the contradicting-evidence half of
matchup analysis, discloses sample size inline, publishes a falsification
battery, or runs anything resembling a pre-registered research program. This
is genuinely built, tested, and differentiated.

**Where we are simply not on the field (score 0):** trust-as-perceived,
tracking, alerts, community, mobile. Not "behind" — absent. There is no
account system, so there is nothing to sync, alert on, or build community
around; there is no mobile surface at all; and "trust" requires a customer
who has encountered the product, which cannot happen today because there is
no way to encounter it (`PRODUCT_ARCHITECTURE_AUDIT.md`: "THERE IS NO
CANONICAL DEPLOYABLE APPLICATION").

**Where we are present but shallow (score 1–2):** AI analysis (rule-based,
not generative/chat), transparency-as-shipped (the honesty lives in `docs/`,
not the product), news speed, market intelligence, odds coverage, props, line
shopping, visual polish. Each of these has a real asset behind it (price
improvement, the "what changed" timeline, the props feasibility probe) that
is either too narrow or not customer-facing yet.

**Pricing is UNKNOWN by design**, not by omission: there is no live price to
score, only a proposal (`PRICING.md`), and scoring a plan against a shipped
price would misrepresent both sides.

## The one sentence this scorecard should leave you with

We have the best evidence engine in the corpus and no product; every
competitor scored above has a real product and, per `CHECKPOINT.md`, not one
of them has anything resembling our evidence discipline. The gap is not
analytical — it is that mobile, tracking, alerts, community, and trust are
scored zero for the same underlying reason: nobody outside this container has
ever seen the product.
