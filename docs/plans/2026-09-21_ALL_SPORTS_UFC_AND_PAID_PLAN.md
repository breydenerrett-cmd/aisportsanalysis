# LINEHOUND — All-Sports Expansion + UFC Launch Plan

**Date:** 2026-09-21 (Monday). Next Saturday: 2026-09-26.
**Prepared by:** writer synthesis of five research memos (UFC/MMA, multi-sport roadmap, repo/pricing infrastructure, payments/legal/hosting, and proof-standard/statistics).
**Reading this doc:** a few terms get used constantly below. They're each defined once, here, so you don't have to chase them:

- **Unit / ROI** — every LINEHOUND pick is graded as if someone staked exactly 1 "unit" on it at the price we published. Win = you gain (decimal odds − 1) units; lose = you lose 1 unit; push/void = 0. ROI = total units won or lost ÷ number of units staked. This is a bookkeeping convention, not a claim that anyone actually bet that amount — it's how the record is graded consistently across every sport.
- **The Card** — LINEHOUND's flagship daily MLB picks product (moneyline "which team wins").
- **LOBO ("leave-one-book-out")** — our core method for finding a mispriced bet: compare what one sportsbook is offering against the consensus of several other books, after removing each book's built-in profit margin ("de-vig"), and only flag it if the gap is big enough (an "edge," expressed as expected value / EV) and the price isn't already a heavy, unfavorable favorite.
- **De-vig** — every sportsbook price has a built-in margin favoring the house ("the vig" or "juice"). De-vigging is the math that strips that margin out to estimate the *true* probability the market thinks each side has of winning.
- **CLV (closing line value)** — did we get a better price than the price right before the game started (the "closing line")? This is a faster, more sensitive way to tell if a strategy is real than waiting for enough wins and losses to pile up.
- **Credits** — The Odds API (our paid odds-data vendor) charges "credits" per data pull. We have a fixed monthly allotment; running low forces captures to stop.
- **Shadow / experimental** — a rule that is running and being graded internally, but never shown to a paying customer or the public. This is how every new sport or bet type is supposed to start.
- **Pre-registration** — writing down the exact rule and its numeric settings, in git, *before* any result exists — so nobody can quietly pick "the rule that happened to win" after the fact. Every rule discussed below either already is, or must be, pre-registered before it counts as real evidence.
- **Bootstrap confidence interval** — a way of asking "if I reran history many times, how much would this win-rate/ROI number bounce around by chance alone?" A wide interval that includes zero means "we don't yet know if this is a real edge or luck."

---

## 1. TL;DR

- **The goal Brey stated:** add every sport we reasonably can, build a standout UFC tool for Saturday fight nights, prove a winning strategy sport-by-sport and bet-type-by-bet-type, sell single-sport or all-sports access, and price each sport by how much money its own record is actually making.
- **The honest state of the evidence today:** nothing in the product — including MLB, the 11-day-old, longest-running test — has yet proven a betting edge by the product's own statistical bar. THE CARD is 66-34, +8.21 units, +8.2% ROI over 100 picks/11 days, but a proper (block-bootstrap) 95% confidence interval on that number is **[-5.0%, +20.8%]**, and the one-sided lower bound is **-2.8%** — i.e., not yet distinguishable from *break-even*. (The 66-34 win rate itself is nowhere near a coin-flip — the open question is whether the *ROI* is real, not whether the team wins the game.) This is not a knock on the product; it's what "still early" honestly looks like, and it's already the repo's own stated conclusion in `docs/DOES_THE_MODEL_BEAT_THE_MARKET.md`.
- **UFC by this Saturday (2026-09-26):** technically doable to get *capturing and shadow-testing* — the value-finding engine (LOBO) plugs into UFC's moneyline market with no new math, and there is a real fight card that day (UFC Fight Night: Rosas Jr. vs. Barcelos). What is **not** honestly doable by Saturday is a priced, publicly graded UFC pick with a track record — because there is no confirmed, legal, free source of UFC fight results to grade picks against (UFC.com's own terms explicitly ban automated data collection, including doing it "manually"), and grading a card by hand against a news/broadcast source is the realistic stopgap. **Recommendation: launch UFC Saturday as a free, clearly-labeled public research page — "being tested, bet at your own risk," picks published and graded, but not sold** — treated as a stated, one-time exception to the normal Stage-0-shadow-first ladder (§4.5), because a public page is exactly what the owner asked for by Saturday. Say plainly that a sparse value rule may publish 0-2 picks on a 12-14 fight card, and that's the rule working as designed, not a bug. Only start charging for it once it clears the same evidence bar every other sport has to clear.
- **Sport order (cheapest, best-timed, highest-value first):** (0) ~~stop the live outage~~ **done 17:41Z** (see blocker 1 below); (1) fix the credit budget shortfall itself — a real constraint, but separate from the outage, and it blocks every *new* sport below; (2) NCAAF, already in-season, cheapest build, ship as a free shadow test; (3) UFC, ship Saturday as a free research page; (4) NHL, season starts 2026-09-29, best free official results feed of any candidate sport; (5) NBA, opens 2026-10-20, cheap build but its results feed for grading is unofficial and unverified; (6) NCAAB, tip-off 2026-11-01, scope to ~100 teams first — full college hoops coverage is both the biggest credit risk and the biggest team-identity build in this whole plan; (7) soccer, opportunistic — its 3-way (win/draw/loss) markets need a real new piece of math we don't have yet; (8) skip WNBA (5 weeks left this season) and boxing (too thin) for now; (9) skip golf until the whole value engine is rebuilt for "pick one winner out of 100+" markets, which it currently cannot do at all.
- **The pricing model the owner is asking for already has a written design** (`docs/PER_SPORT_PRICING_PLAN.md`, written 2026-09-15) — buy one sport, or all sports as a bundle, with a price that steps up only once a sport's own record clears a strict, pre-agreed bar, and steps back down just as readily on a bad quarter (existing subscribers keep their price until renewal; new subscribers get the new price). **Billing exists for one flat plan only.** A Stripe checkout for a single $19.99/month "Beta" plan is built and tested in Stripe's test mode (`src/appstate/billing.py`). It waits on the owner connecting a live Stripe account. Nothing per-sport is built: there is no way to pay for "just NFL," and no code that checks which sport a customer paid for.
- **Three biggest blockers, in order of how soon they bite:**
  1. **~~A live outage~~ — fixed at 17:41Z today, but the same wall is coming for other files.** `odds_multibook.jsonl` passed GitHub's 100 MB file limit, and about 3 hours of captures (14:39Z–17:41Z) were lost. It now archives old rows automatically (commit `f0b68c70`; the first production run archived 08-31..09-17 into a 2.3 MB file and left the live file at 36 MB). Three other stores are next: `derivative_markets.jsonl` (63 MB), `evidence/decisions_v2.jsonl` (57 MB) and `batter_props.jsonl` (40 MB). A warning now fires at 75 MB, but each needs the same archiving before adding sports multiplies the growth.
  2. **The Odds API credit budget is short for the reset window**, independent of the outage above — there isn't enough headroom above the 5,000-credit floor to reach the (unconfirmed) monthly reset at the current pace, and the floor is on track to land on or just before UFC's Saturday card, not comfortably before it.
  3. **UFC has no legal, free source to grade fight results against** — every free public option (UFC.com, UFCStats.com, Sherdog, Tapology) either explicitly bans automated scraping (and, per UFC.com's own wording, manual monitoring too) or sits in a legal gray zone. This is the one blocker that isn't a code problem — it needs either a paid data vendor or a person checking results by hand each week against a news/broadcast source, not by watching UFC.com.
- **Decisions waiting on the owner** (full list with recommendations in §11): decide how to close the credit shortfall given the floor now lands on or near UFC Saturday; decide UFC's per-fight lock timing and what happens when a fighter is swapped late; pick a payment processor path (Stripe test charge + Whop as a parallel fallback is the research finding); confirm nobody — including MLB — gets priced above the $19.99 floor until the evidence bar is actually cleared; sign off on the handful of Fly.io/Stripe account steps only the account owner can do to bring the real (production) site online; authorize starting the billing/entitlements build.
- **Bottom line:** the picks have looked good so far, and the infrastructure to prove that honestly (per-sport ledgers, a public record API, a well-designed pricing plan, a rigorous internal research process) is mostly already built — it just isn't finished, connected, or public yet. The work ahead is less "invent a new strategy" and more "finish wiring what's already designed, per sport, and don't let the marketing get ahead of the evidence."

---

## 2. The goal, restated as measurable targets

"Prove we have a winning strategy" is not a feeling — the product's own rules (from `docs/PER_SPORT_PRICING_PLAN.md`, `docs/COMMERCIAL_READINESS.md`, and `docs/ARCHITECTURE_BETTING_ENGINE.md`) already define exactly what "proven" means, and it's a high bar on purpose. For every sport and every bet type (e.g., "MLB moneyline," "MLB total bases prop," "UFC moneyline"), proof means clearing **all** of the following, together, not just one:

1. **A rule that was written down and frozen before any result existed** ("pre-registered") — so the rule can't be quietly cherry-picked after the fact to fit whatever happened to work.
2. **A real sample size.** The product's existing bar is 500 graded picks over 6 months. Section 4 below shows why, mathematically, that's often not even enough for a modest (3-5%) real-world edge — smaller samples can only detect big, unrealistic edges.
3. **A statistically real result, not just a lucky-looking one.** Specifically: a 95% confidence interval on the ROI that stays above zero — using a bootstrap method that respects the fact that picks made on the same day aren't independent of each other (§4.3 explains why this matters).
4. **That result repeated, not just achieved once.** The existing rule requires it to hold in **two consecutive quarterly reviews** — a result that vanishes the next quarter was noise, not an edge.
5. **Corroboration from a second, faster signal (CLV)** once that machinery is wired up (it already exists in the code, see §4.4) — CLV needs far fewer bets to say something meaningful, so it's a useful early tell on whether a borderline record is heading toward real or fake.
6. **A correction for how many things you're checking at once.** If you track 20 different (sport, bet-type) cells simultaneously, some of them will look "statistically significant" by pure chance even if none of them have a real edge — this is the single most important, least intuitive point in this whole document, and §4.3 works the actual math.

**Under this bar, as of today, no sport and no bet type in LINEHOUND has proven a winning strategy.** That is a fact about the evidence, not a judgment about the picks — MLB's positive-looking record could easily be real, it just isn't old enough yet to say so with confidence. Every public and pricing claim from here forward needs to say exactly that, honestly, per sport — never "proven," always "here's the current record, here's the sample size, here's the interval, here's how confident we can be so far."

**A note on "all different teams":** the owner's ask also named proving this per-team, not just per-sport. That's honestly out of scope at every stage of this plan — a single MLB team gets roughly 3-6 picks over an 11-day stretch like this one; even at the whole season's pace, no team will individually clear the §4.2 sample-size bar (hundreds to thousands of picks) within a single season, or several. Team-level results can be shown as a transparency feature (here's every pick on the Yankees, win or lose) once the cross-sport record page (§4.1, item 3) exists, but they should never be marketed or priced as "we've proven an edge on this team" — flagging this now so it isn't silently dropped rather than answered.

---

## 3. Where we are, per sport (real numbers, what they do and don't prove)

### 3.1 MLB — the longest-running test

**Source:** live recomputation directly from `evidence/cards_v1.jsonl` (the raw pick ledger), cross-checked against `docs/reports/2026-09-21_WHERE_WE_ARE.md`. [tier-1, internal ledger — this is our own data, not a claim from a vendor]

| Market | Picks (n) | Record | Units | ROI | Days |
|---|---|---|---|---|---|
| Game picks (moneyline) | 100 | 66-34 | +8.21 | +8.2% | 11 |
| — STRONG confidence tier | 34 | 29-5 | +9.48 | +27.9% | — |
| — LEAN confidence tier | 40 | 22-18 | -3.03 | -7.6% | — |
| — SLIGHT confidence tier | 19 | 12-7 | +3.53 | +18.6% | — |
| — SPLIT confidence tier | 7 | 3-4 | -1.77 | -25.3% | — |
| Props (total bases, hits) | 94 | 64-30 | +2.75 | +2.9% | ~7 |
| — Total bases (Over) | 18 | 13-5 | +2.68 | +14.9% | — |
| — Total bases (Under) | 22 | 16-6 | +3.05 | +13.9% | — |
| — Hits (Over) | 14 | 10-4 | +1.69 | +12.1% | — |
| — **Hits (Under)** | 40 | 25-15 | **-4.66** | **-11.7%** | — |

**What this does and doesn't prove, stated plainly:**

- The **+8.2% game-pick ROI is not statistically distinguishable from break-even yet** (the raw 66-34 win rate is nowhere near a coin flip — it's the ROI, not the win rate, that's still inside the noise band). A proper 95% confidence interval, computed by resampling whole days at a time (not individual picks — picks on the same day aren't independent of each other), comes out to **[-5.0%, +20.8%]**. The one-sided 95% lower bound is **-2.8%**. In plain terms: this record is consistent with both "we have a real, sizeable edge" and "we have no edge and got a bit lucky over 11 days," and roughly 11% of resampled versions of this same 11-day history came back break-even or worse (89% came back positive). **Separately**, and on a different question: the repo's broader EvoLab search tested 8,811 systematically-generated line-movement strategies against 2023-24 moneylines and found zero survived a rigorous overfitting test (`docs/EVOLAB_PHASE2B_RESULTS.md`) — that's a null on whether *any* line-movement strategy beats the market, not a test of THE CARD's own rule. The internal evidence that speaks directly to THE CARD's rule is `docs/DOES_THE_MODEL_BEAT_THE_MARKET.md`'s own backtest of it, which came back **-9.7% ROI** (n=72, 95% CI [-29.1%, +9.8%]) — a caution sitting right next to today's positive live number, not an independent confirmation of it.
- **Every one of these 100 game picks has been a favourite (0 underdogs), and 16 of them were bought at -200 or worse — the same is true for 44 of the 94 props.** That's a direct conflict with the owner's own standing rule ("no moneyline at -200 or worse, ever"). The live V1 card predates that ruling and the owner separately said not to alter V1's rule midstream (09-17), so this isn't a "just fix it" item — it's a decision only the owner can make about how the rule applies retroactively to a card that's already running (see §7.3, §11).
- The **confidence tiers are not a validated ranking yet either** — note that LEAN (the second-highest confidence label) is currently the *worst* performer (-7.6% ROI), which is either bad luck in a small sample or a sign the confidence labels aren't capturing what they're meant to. Too early to say which; flagging it because a customer looking at "STRONG: +27.9%!" without this context would be misled.
- The **Hits Under prop line is a warning, not proof of a structural problem**: at a *median* price of -246 (the mean is actually -240.9), it needs roughly 70.6-70.9% to break even; 25-15 (62.5%) over 40 picks is about 1.1 standard deviations below that break-even rate (one-sided p ≈ 0.16) — a real caution sign, but well within the range a 40-pick sample can produce by chance alone even if the line is fine. Any pause or redesign of this specific line would also run into the same 09-17 "don't alter V1 midstream" instruction above, so treat "pause Hits Under" as an owner decision to weigh against that instruction, not a unilateral engineering call.
- **How many picks would it take to actually know?** The rule-of-thumb sample sizes in §4.2 (revised there) detect a true edge only about half the time at that count — at a conventional 80% power the same table roughly doubles. At THE CARD's current pace (~9 picks/day), the easiest 50%-power threshold on today's own 8.2% number is roughly **40 days out**, not "2 months"; the day-block variance actually observed so far suggests something closer to **2-3 more weeks** could already be informative even before that, with the caveat that it's a range, not a promised date. MLB's regular season ends **2026-09-27**, six days from today, which caps how much more evidence accrues this year before the sample simply stops growing until spring.

**Bottom line for MLB:** real, promising, worth continuing exactly as-is — and not yet provably profitable, and not yet compliant with the owner's own -200 rule. It should keep the "our longest-running test" language (the only sport allowed to say that, per owner ruling) but not "proven edge" language. It's public today (staging, demo mode) but not sold anywhere (see §4.5) — so "stay priced at the floor" doesn't yet apply; the open question for the owner is what happens *when* MLB is priced, given the -200 conflict above.

### 3.2 NFL

**Source:** `docs/reports/2026-09-21_WHERE_WE_ARE.md`, `evidence/cards_nfl_v1.jsonl`, `docs/PREREG_NFL_CARD_V2.md`. [tier-1, internal]

- The **old rule (V1, betting favorites)** is retired, finishing 6-3, -0.59 units overall (1-0 on 09-17, then 5-3 on the 09-20 Sunday slate). The 09-20 slate alone shows the point clearly: five favourites won, paying back a combined +1.97 units (KC -278, SF -950, SEA -195, DEN -148, PHI -320), but that didn't cover three losses at heavy favourite prices (-295, -420, -380) that each cost a full unit (-3.00u), netting -1.03u on a day it won 62.5% of its bets. This is the exact same "-950 problem" as MLB's Hits Under line: win rate and profitability are different things, and this is a clean real-world example of why.
- The **new rule (NFL_CARD_V2)** — comparing a book's price against a "leave-one-book-out" consensus of the others, only when at least three different math methods for removing the vig all agree there's a real edge, and never touching a moneyline of -200 or worse — is registered but **has not published a single graded pick yet**. A replay of the rule over the local store (100 NFL capture instants across 7 games, 09-15 to 09-21) found 1 candidate that survived all three de-vig methods, versus 17 candidates (16 plus-money moneylines, 1 total) that a looser, rejected proportional-only version would have fired on — this is a sparse, honestly cautious rule by design, not a bug.
- **What this proves:** nothing yet, on purpose — it hasn't run long enough to prove or disprove anything, and that's exactly the point of registering it before it runs.

### 3.3 Tennis

**Source:** `docs/reports/2026-09-21_WHERE_WE_ARE.md`. [tier-1, internal]

- Prices have been captured since 2026-09-21. **Zero graded picks exist**, because the results feed we pay for (BALLDONTLIE) is returning an authentication error ("401") on ATP/WTA tennis results. **What we're actually entitled to is UNVERIFIED**: the code comment on our own client (`src/providers/balldontlie.py`) says the owner "bought ALL-ACCESS on a 48-hour trial (2026-09-15)," and the account is behaving as if throttled to roughly the vendor's Free-tier rate limit (~5 req/min) rather than the ALL-ACCESS 600/min — so the 401 may be a trial that lapsed or a tier mismatch, not necessarily a vendor bug on coverage we're actually paying $299.99/mo for. **Before raising this with BALLDONTLIE support, confirm what plan the account is actually on** (see §5.2, §7.3, §10 for the same open question on cost).
- **This same "what tier are we actually on" question is the single biggest open question for UFC too** (see §5.2) — don't assume any new sport's BALLDONTLIE coverage works, or that we're being billed $299.99/mo for it, just because a marketing page says a tier includes it.
- **What this proves:** nothing — there is no record to evaluate yet.

---

## 4. The proof standard: a public per-sport / per-bet-type scoreboard, and how it should set price (up **and** down)

### 4.1 What already exists to build this on

The good news: the hard, tedious part — actually computing a real, per-sport, per-strategy win/loss/ROI record from tamper-evident data — is **already built and live**, just not assembled into one public page yet.

- `src/appstate/card_ledger.py` already computes wins, losses, pushes, voids, units, and ROI **broken out by sport and by which specific rule made the pick** (so a retired rule and a live rule on the same sport never get blended together), and it already includes a tamper-evidence check (a "hash chain," which proves the historical record hasn't been quietly edited after the fact).
- `api/card.py`'s `GET /card/record` and `GET /card/history` compute that data correctly today, but they are **not public in production** — `api/app.py` mounts the card router behind the same paid-access gate as everything else, and it only opens up with no login on staging when a "demo mode" flag is set. Making these routes genuinely public (no auth, in production) is still unbuilt work, and it's already scoped in `docs/PER_SPORT_PRICING_PLAN.md` ("`/card/record` and `/card/history` move to a public router with no auth").
- What's **missing** is (a) that public-router change, and (b) a single page that lays every sport and bet type side-by-side — today you'd have to know to ask for each one separately. Both are small, mechanical additions on top of what already exists.

### 4.2 How many picks before a number means something (the math, plain-language)

Sports odds already tell you the "breakeven" chance a bet needs to win — a -110 price needs to win 52.4% of the time just to break even, a +150 underdog needs 40%, and so on. The math of "how many bets until I can trust a win rate above breakeven is real, not luck" depends on that breakeven number. **These are 50%-power numbers** — at this sample size, a true edge of the stated size is only caught about half the time; a conventional 80%-power bar (the standard for "we'd actually expect to detect this if it's real") needs roughly 2.04x more:

| Typical price | 3% edge (50% / 80% power) | 5% edge (50% / 80%) | 8% edge (50% / 80%) |
|---|---|---|---|
| -110 (spreads/totals) | ~3,880 / ~7,900 | ~1,400 / ~2,850 | ~550 / ~1,120 |
| +150 (underdog) | ~6,400 / ~13,050 | ~2,300 / ~4,700 | ~900 / ~1,840 |
| -130 (moderate favorite) | ~3,280 / ~6,690 | ~1,180 / ~2,410 | ~460 / ~940 |
| -246 (like MLB's Hits Under) | ~1,740 / ~3,550 | ~625 / ~1,280 | ~245 / ~500 |

*Read this as "n where a true edge of this size would be caught," not "n that proves an edge" — a sample this size that comes back positive is still just a data point, not proof; §4.3's multiple-comparisons correction pushes these numbers up further once several sports are being compared at once.*

**Two things worth internalizing:** heavier favorites need *fewer* bets to prove the same percentage edge (because their outcomes carry less surprise, statistically) — but that's a statistics fact, not a reason to prefer them; the "-950 problem" above shows heavy favorites are economically harder to profit from even when they're right most of the time. And the product's existing "500 picks in 6 months" pricing-step-up rule is well-powered (80%) to detect only a fairly large 8%-ish edge at typical prices — a real, more typical 3-5% edge would need years of data at that rule's own threshold. This is worth knowing before promising a step-up "once we hit 500 picks" — 500 may prove a big edge exists, but it will not prove a small one is fake, it'll just stay inconclusive.

### 4.3 The multiple-comparisons trap — the single most important idea in this section

Here's the trap in the owner's own framing: *"any record that's making more money than the others, we can charge more for it."* If we're going to look across, say, 20 different (sport, bet-type) combinations and pick whichever one looks best to charge more for, **some of them will look great purely by chance, even if none of them have a real edge** — this isn't a hypothetical, it's guaranteed by the math of checking many things at once, and it's exactly what our own internal research process (called "EvoLab") already found the hard way: **zero of 8,811 systematically tested strategies survived** a rigorous test built specifically to catch this trap.

The fix is well-understood and cheap to apply: when deciding whether a sport/bet-type's good-looking record is "real enough" to raise its price, the bar needs to get *stricter* the more things are being compared simultaneously (a standard method called a Bonferroni correction). Worked example: with about 20 sport/bet-type cells being tracked (a realistic number once UFC and a couple more sports are live), the sample size needed to trust a result honestly roughly **doubles** (about 2.4×) compared to judging that one cell in isolation.

**Recommendation:** build this correction into the pricing step-up script (`scripts/price_review.py`, already planned in the existing pricing doc) from day one — it's a small, one-time addition, and it directly protects against the exact failure mode ("we found the sport that looks good by luck and charged more for it") that would undermine the whole pitch to customers.

### 4.4 CLV — a faster signal that's built in several places, but not for the live card and not shown to anyone

There's a second, faster way to tell whether a strategy is real: instead of waiting for enough wins and losses to pile up, check whether we consistently got a *better price* than the final ("closing") price right before the game started. This needs meaningfully *fewer* bets to say something meaningful than win/loss record does — a named industry practitioner (Joseph Buchdahl, via a third-party site that republishes Pinnacle-sourced content — tier-2, not independently confirmed on pinnacle.com directly) puts it as "perhaps as few as 50 bets" for CLV versus "several thousand" for raw profit and loss on an even-money bet, on the assumption of a fairly large, consistent ~5% CLV edge — a smaller or noisier true edge would need more.

**The finding here:** LINEHOUND has built CLV-measuring code in three places (`src/report/clv.py`, `src/report/card_clv.py`, and `src/pipeline/snapshots.closing_line_value`), but none of it covers the live V1 card that's actually publishing picks today — `card_clv.py` explicitly measures the not-yet-live `DAILY_CARD_BEST_BETS_V2` card's picks, and the figures it produces (`clv_bps_mean` in `evidence/scorecards_v2.jsonl`, and the CLV lines `cli grade` prints to the console) are operator-facing internal numbers, not anything a customer or the owner sees on a page. **Recommendation: adapt this code to cover the live V1 card and surface it on the new scoreboard** — this is real, non-trivial work (a different ledger shape than what `card_clv.py` was built for), not a config flip. It's worth doing regardless: it's a local computation with no data-vendor cost, and could give an earlier read than the win/loss record alone. Two caveats to set expectations honestly: MLB's regular season ends in 6 days (09-27), and the raw closing-line captures needed to compute it were themselves lost for stretches (09-15 to 09-21, and again since today's 14:39Z outage — see §9.2), so the backfilled history to compute it from is incomplete. **Also flag for the owner:** the architecture doc is explicit that "CLV is a monthly review dimension, never a daily score" and the scoring code enforces CLV as advisory-only, never gating `promotion_verdict` — wiring CLV into the pricing step-up logic (as this section originally proposed) would change that rule, not just implement it, and needs sign-off, not a silent addition.

### 4.5 The promotion ladder — and how price should move down, not just up

Putting §2-4.4 together, every sport and bet type should move through the same four stages, and a sport can move *backward* down this ladder on a bad quarter, not just forward:

| Stage | What it means | What it takes to leave |
|---|---|---|
| **0. Shadow** | Running and graded, visible to nobody but the team | At least 10 graded picks |
| **1. Public research page (free)** | Visible, clearly labeled "research/testing, not a paid pick," graded publicly including the losers | Enough of a track record to even evaluate a pricing decision — no fixed number, can run indefinitely (tennis has been here since 09-14, though prices have only been captured since 09-21, so it's more "just started" than "stuck") |
| **2. Priced at the floor ($19.99/mo)** | Sold, but priced flat, not performance-based — same public record, same "past results don't predict future results" disclaimer next to the price | 500+ eligible picks in 6 months, the one-sided 95% block-bootstrap lower bound (§4.3) stays positive, in **two consecutive quarters** |
| **3. Priced above the floor ("step-up")** | Price rises **by the worked formula in `docs/PER_SPORT_PRICING_PLAN.md`**: step-up = 10% x (lower-bound units/pick x 100 picks/month x $10), rounded down, capped at 2x the floor — e.g. a +0.03 lower-bound units/pick sport prices at $19.99 + $3.00 = $22.99 | Same statistical bar as Stage 2, sustained; picks must be graded at the **market consensus price** (not the "best of ~11 books" price the live card shows today), and a **public hash of each frozen card posted before the first game** so "published before the game" is independently checkable |

*(This maps onto `docs/PER_SPORT_PRICING_PLAN.md`'s own two-part design: Stage 2 is that doc's "Part A: floor," Stage 3 is "Part B: step-up." That doc also already answers what happens to an existing subscriber when a sport steps back down: price drops apply at the subscriber's next renewal, no mid-cycle refund, and a subscriber keeps their old price only while their subscription stays continuously active — pull this into the checkout/entitlements copy directly rather than re-deriving it.)*

**Under this ladder, today: no sport is even at Stage 2.** MLB is public on staging (demo mode only, not production) and unsold — that's Stage 1, not Stage 2, regardless of record quality, because nothing is being charged for yet anywhere. Once billing exists, MLB's own interval (§3.1) is below zero even before applying the stricter multi-sport correction, so there's no honest basis for pricing it above the floor — and its current record also breaks the owner's -200 rule (§3.1), which the owner needs to resolve before MLB is priced at all, not just before it's stepped up. NFL and tennis are at Stage 0/1. UFC starts at Stage 0 with zero existing infrastructure, except that §5.1 recommends a Stage-1 launch this Saturday as an explicit, stated exception (see §5).

---

## 5. UFC — the tailored analysis tool for Saturday fight nights

### 5.1 What's realistic for 2026-09-26 vs. later — the honest answer up front

| Piece | Ready by Sat 09-26? | Why |
|---|---|---|
| Odds capture (new UFC data adapter + a real, measured credit cost) | **Yes, plausible** | Small, mechanical build following the same pattern already proven twice (NFL, tennis) |
| A pre-registered UFC value rule, running as a **shadow** test | **Yes, plausible** | The value-finding math (LOBO) needs zero new code for a two-way moneyline market — only a small UFC-specific data adapter |
| **Public, paid, graded UFC picks** | **No — not responsibly** | No legal, free, bulk source of UFC fight results exists to grade against (§5.4); the product's own rules require real evidence before charging for anything |
| A fighter-rating model (an "Elo"-style ranking, like chess ratings) | **No** | Blocked on the same missing-legal-data-source problem, and the one relevant academic study found this kind of model needs real extra design work for MMA specifically (fighters fight too rarely per year for a simple version to work well) |
| Method-of-victory / round-total betting markets | **No** | Method-of-victory isn't listed anywhere in our vendor's product pages. Round-totals coverage is genuinely unconfirmed, not absent — one vendor page says "limited coverage of total rounds odds are also available from some bookmakers," a second doesn't mention it. Out of scope for launch either way; worth a live check before ruling it out long-term. |

**Recommendation for Saturday: launch a free, clearly-labeled UFC research page, published and graded** — not shadow-only. This is a deliberate, stated exception to the normal Stage-0-first ladder (§4.5): a shadow test nobody sees doesn't meet what the owner actually asked for by Saturday, and UFC's build is small enough to make a public page realistic this week. Capture odds, run the value rule, publish what it picked, and grade it manually against a news/broadcast result (not by monitoring UFC.com — see §5.2/§5.5) once fight night is over. **Set expectations now: a sparse, honestly cautious value rule may publish 0-2 picks on a 12-14 fight card** (the NFL version of this same rule found 1 candidate across 100 capture instants) — an empty or near-empty first Saturday is the rule working as designed, not a failed launch. Do not sell it and do not claim it has a track record until it has one.

### 5.2 The data situation

**Odds (moneyline betting lines):** Our existing paid odds vendor (The Odds API) covers UFC/MMA under the sport key `mma_mixed_martial_arts`. [tier-1, vendor's own product page] Today's coverage is **moneyline (who wins the fight) only, confirmed** — a second page from the same vendor mentions "limited coverage of total rounds odds... from some bookmakers"; this isn't a contradiction so much as one page being less detailed, but treat totals as unconfirmed until checked live rather than assuming either page is complete. **Method-of-victory isn't mentioned on either vendor page** — treat it as not offered.

Cost is unusually cheap for UFC specifically: this vendor charges per *data pull*, not per fight, so one pull covering an entire 12-14-fight card costs about 1-2 credits, regardless of card size. A realistic capture schedule across a full fight week (stepping up around Friday weigh-ins and again before Saturday's card) is roughly **20-30 credits for the entire week** — this is one of the cheapest sports we could ever add, credit-wise, *if* the moneyline-only situation holds.

**Results (who actually won, for grading):** This is the real bottleneck, not the odds. Every free, public source of UFC fight results and fighter data has a real legal problem:

- **UFC.com's own Terms of Use explicitly ban automated data collection**, in unambiguous language (fetched and quoted directly): *"You may not use any 'deep-link', 'page-scrape', 'robot', 'spider' or other automatic device... to access, acquire, copy or monitor any portion of the Site."* [tier-1, fetched directly]
- **UFCStats.com** (the site most third-party MMA models actually use) is very likely part of the same corporate family and probably carries the same restriction — this wasn't independently confirmed (its own terms couldn't be fetched directly in this research pass), so treat it as off-limits until proven otherwise, not the other way around.
- **Sherdog and Tapology** both have similar bans and, per third-party reports, active anti-scraping defenses that would get an automated collector blocked.
- **ESPN's unofficial data** is a usable manual spot-check, not something to build a scheduled, automated pipeline on.

**There is no clean free option. The realistic paths are:** (a) **BALLDONTLIE** — they do have a dedicated MMA API with fight results and fighter rankings on their **"ALL-STAR" tier ($9.99/mo)** and odds/fight-stats on their top **"GOAT" tier ($39.99/mo)**. **What we're actually paying for is UNVERIFIED**: the "ALL-ACCESS" plan is documented in our own code as a **48-hour trial** started 2026-09-15, and the account is currently rate-limited as if it's on something closer to the Free tier — so "we pay $299.99/mo for ALL-ACCESS" may not be a fact yet, not just a plan whose MMA coverage is untested. **The cheap, low-risk path: buy MMA ALL-STAR directly for $9.99/mo** — it's a fraction of ALL-ACCESS's price and gets fight results and rankings regardless of how the ALL-ACCESS question resolves. (b) **A paid, licensed MMA data vendor** we haven't evaluated yet (a couple were found in passing — SportsDataIO, OddsMatrix — not priced or vetted). (c) **Manual entry** — a UFC card is once a week, 12-14 fights, small enough that a person typing in the official result by hand (from a news or broadcast source, not UFC.com — see §5.5) is a genuinely reasonable stopgap, unlike MLB's daily multi-game volume, which would be too much to do by hand.

**Recommendation: confirm what BALLDONTLIE plan the account is actually on this week (free to check — it doesn't spend Odds API credits), buy the $9.99/mo MMA ALL-STAR tier directly rather than assuming ALL-ACCESS covers it, and plan on manual grading as the fallback for the first few Saturdays regardless** — even a working BALLDONTLIE feed would benefit from a manual cross-check early on.

### 5.3 A note on the market-efficiency research — resolved this pass

Two research memos read the same academic paper (Miller & Nichols, 2026, *Journal of Economics and Finance*, on MMA betting market efficiency) and described its central finding differently; one said no bias, one said a significant bias was found. **This is now resolved** — the abstract, re-fetched directly this pass [tier-1, ideas.repec.org], says plainly: *"We find no evidence of a favorite-longshot bias that has frequently been found in other sports."* The market is characterized as largely efficient, with two weaker, non-replicated signals (the market may under-price youth/travel effects, and betting favorites in women's fights showed some promise, though the paper's own out-of-sample test found few statistically significant results from these). **Do not repeat the "significant favorite-longshot bias" claim publicly — the paper found the opposite.**

What this means for approach: MMA betting markets are broadly efficient, similar to the conclusion already reached internally about MLB and NFL — which is a reasonable argument for a value-line rule (find the one mispriced book) over a from-scratch prediction model claiming a big edge out of the gate. But **that argument stands on its own logic, not on a track record** — no value-line rule (LOBO-based) has produced a single graded pick anywhere in this product yet: NFL_CARD_V2 (the closest thing to a running value-line rule) hasn't published a pick, and the MLB value shadow tests started today with zero decisions. MLB's actual positive record (§3.1) comes from a different rule entirely (`DAILY_CARD_MARKET_SIDE_MODEL_AGREEMENT_V1`, market-favourite-plus-model-agreement, not a value-line rule) — and when the value-line approach itself was backtested for MLB, it came back **-9.7% ROI** (`docs/DOES_THE_MODEL_BEAT_THE_MARKET.md`). Treat UFC's Arm A as untested in this product, resting on the market-efficiency literature and the design's own internal logic, not on any existing win.

### 5.4 The proposed build: UFC_CARD_V1 (value rule) + a separate, slower fighter-rating shadow arm

**Arm A — value rule (the one that could plausibly run by Saturday).** This reuses our existing, already-generalized value-finding code (`src/analysis/lobo_value.py`) completely unchanged — it was specifically built to be sport-agnostic, and a two-way UFC moneyline board is the exact same shape as an NFL moneyline board. The only new code needed is a small adapter that turns UFC odds data into the same format the existing engine already expects. Settings that carry over unchanged from NFL/MLB: no bet at -200 or worse (owner ruling), same 2% minimum edge threshold, same freshness rules. **The one setting that must be measured, not assumed: how many different sportsbooks need to agree before we trust the signal.** NFL uses 5; UFC likely has fewer US books actively quoting fights, so this needs a real check rather than a guess — if only 3-4 books quote a given fight, using NFL's threshold would make the rule fire on almost nothing.

**Arm B — a fighter-rating model (a ranking/strength system, like a chess-style rating), shadow-only, much later.** This is explicitly **out of scope for launch.** The one relevant academic source found that a simple version of this kind of model tends to underperform for MMA specifically, because top fighters only fight 2-4 times a year (versus dozens of games/matches a year in most other sports this technique is normally used for) — a workable version needs real design work (accounting for opponent quality, how a fight ended, and time off between fights), and it's blocked anyway on the missing legal-data-source problem in §5.2. Treat this as its own multi-week project with its own pre-registration, not a fight-week rush job.

**Fight-week operational details that need an owner decision (flagged, not yet decided):**

- **Lock timing.** MLB and NFL lock each pick a fixed number of hours before that specific game starts, because every game has its own independent start time. A UFC card is one long session (5-7 hours from first prelim to main event) — locking the whole card at the first fight's start time would lock main-event picks unrealistically early; locking each fight independently a couple hours before its own estimated start time is the better fit, with a simple fallback (a fixed offset from the announced card start) if per-fight timing isn't built yet. **Recommendation: build the per-fight version; it's a modest addition, not a rewrite.**
- **Fighter swaps.** Unlike a rained-out baseball game, a UFC fight can have a *different combatant* step in on short notice while a pick is already locked. This needs a new rule that voids (or requires resubmitting) any locked pick on that bout — there's no existing equivalent to copy from MLB/NFL, so this needs to be built and decided before launch, not discovered after a bad grading dispute.
- **Draws, no-contests, cancelled bouts** — these already have a home in the existing grading vocabulary (the same "VOID" outcome already used for postponed MLB/NFL games), so no new concept is needed there, just wiring the trigger.

### 5.5 What NOT to do

- Do **not** sell a UFC pick, or claim a UFC record, until a results source is confirmed and running (§5.2). The free Saturday page in §5.1 is the one exception, graded by hand from a news or broadcast result.
- Do **not** describe UFC as having "an edge" or use MLB's "longest-running test" language — per the owner's own ruling, only MLB gets that phrase.
- Do **not** build the method-of-victory/round-total markets or the fighter-rating model for launch — neither is available on confirmed data, and rushing either would repeat the exact "claimed more than the evidence supports" mistake already flagged and walked back for MLB in the 2026-09-21 status report.
- Do **not** assume BALLDONTLIE's UFC coverage works, or that we're on ALL-ACCESS at all — confirm the actual plan first (same lesson as the open tennis problem).
- Do **not** use UFC.com as the source for manual grading, even by having a person check it by eye. Its Terms of Use ban not just automated scraping but "any similar or equivalent manual process" used "to access, acquire, copy or monitor any portion of the Site" — manual grading needs a news/broadcast result or a licensed feed instead (§5.2, §11).

---

## 6. Every other sport — ranked roadmap, with dates and reasons

**Why this order:** build cost (how much genuinely new code a sport needs, not just configuration), how soon its season starts, how good its free results-grading feed is, and what (if anything) is known about that sport's betting-market efficiency. The single biggest technical fact driving this ranking: our value-finding engine, sport registry, and pick-ledger code were all built to be reusable across sports from day one — but only for sports whose main bets are **two-way** (moneyline/spread/total, like NFL). Sports whose main bet is **three-way** (soccer's win/draw/loss) or an **outright field bet** (golf's "who wins the whole tournament") need real new math we don't have yet.

| Rank | Sport | Starts | Build cost | Results feed | Why here |
|---|---|---|---|---|---|
| — | **(Fix the credit budget)** | now | — | — | Blocks every sport below; see §9.2 |
| 1 | **NCAAF (college football)** | already in season | Cheapest — near-verbatim reuse of the NFL code | Free, community-run (CollegeFootballData.com), not independently vetted this pass | Available today; but academic research on college-football markets is more nuanced than "easier than the NFL" — ship as an unpublished shadow test first, both for that reason and because it runs weekly (not daily), which shrinks how fast evidence accumulates |
| 2 | **UFC/MMA** | next card is Sat 09-26 | Small — value rule reuses existing code | **Not solved** — the real blocker (§5.2) | Best market-efficiency case found in this research (though see the flagged discrepancy in §5.3); technically clean; grading is the open problem |
| 3 | **NHL** | 2026-09-29 | Small — new sport spec + a results-feed connector | The best free, official option found for any candidate sport (a keyless official NHL API) | Nearest season start of anything un-started; cheapest daily-slate sport to add |
| 4 | **NBA** | 2026-10-20 | Small — near-identical shape to NHL's build | **Unverified** — no confirmed free, reliable, official source; the commonly-used one is unofficial and undocumented | Cheap technically, but don't promise a grading feed as solid as NHL's until this is checked |
| 5 | **NCAAB (college basketball)** | 2026-11-01 | **Large** — 350+ teams to identify and match correctly, versus ~30 for MLB | Unverified | Real signal potential (more games, likely softer lines on smaller programs) but also the single biggest credit-cost risk in this whole plan if built without limits — start with roughly the top 100 programs, not full Division I |
| 6 | **Soccer (EPL / Champions League / MLS)** | already running | **Large, structural** — needs a brand-new three-way pricing calculation our code doesn't have at all today | Unverified | High audience appeal, but this is a real subproject, not a config change — treat as opportunistic, not scheduled |
| skip (for now) | **WNBA** | playoffs end by 10-31 | small | unverified | Season is ending in ~5 weeks; not worth building a pipeline for a league about to go quiet until May 2027 — revisit ahead of next season |
| skip (for now) | **Boxing** | irregular | small | none found | Too few events, too thin on bookmakers, to be more than an occasional one-off feature |
| skip (until the engine is rebuilt) | **Golf** | mid-season lull now | **New architecture required** | n/a | Golf's main bet is "pick the tournament winner out of 100+ players" — this doesn't fit our two-way value engine at all; not a near-term item |

**One general finding worth keeping in mind for every sport above (but not UFC — §5.3 resolved that MMA shows no such bias):** the pattern that shows up in soccer and horse racing research is the "favorite-longshot bias" — bettors tend to overpay for big underdogs relative to their real chances, which means favorites are relatively the better value on average. **The owner's -200-floor rule is a profitability rule (born from the 09-20 NFL favourites slate losing 1.03 units — §3.2), not a bias-hunting rule** — and read against the favourite-longshot bias, it actually points the wrong way: banning heavy favourites pushes NFL_CARD_V2's remaining candidates toward the longshot side, which the bias says is the *worse*-value side. That's precisely why the rule also requires all three de-vig methods to agree before firing (§3.2) — it's the guard against exactly that steering effect, not a second application of the same insight.

---

## 7. The product: per-sport subscriptions + all-sports bundle

### 7.1 The design already exists — it just isn't built

The exact thing being asked for — "let people buy one sport, or all sports, and price each sport by how well its own record is doing" — **is not a new idea for this product.** It's already fully designed in `docs/PER_SPORT_PRICING_PLAN.md` (written 2026-09-15), which explicitly says at the top: "Nothing is built." That design specifies:

- **A floor price per sport** (suggested $19.99/month), the same for every sport at launch, including UFC.
- **A step-up rule** that raises a sport's price only after it clears the evidence bar from §4 (500+ graded picks over 6 months, positive interval two quarters running), capped at 2× the floor. The actual formula (worked example in §4.5): **step-up = 10% x (lower-bound units/pick x 100 picks/month x $10)**, rounded down to whole dollars — so a modest +0.03 lower-bound units/pick sport prices at $22.99, not an arbitrary jump.
- **A bundle**, sold only once at least two sports are individually on sale, priced at the most expensive single sport plus roughly 50% — never cheaper than buying the priciest sport alone.
- **What happens to an existing subscriber when a sport's price moves**, up or down: a price drop takes effect at the subscriber's next renewal (no mid-cycle refund); an existing subscriber keeps their price only while their subscription stays continuously active (shown at checkout and in cancellation emails). This is already decided in the pricing doc — it needs to be built into the entitlements/billing code (item 12, §9.1), not re-decided later after a demotion actually happens.
- **The exact code pieces needed:** a new plans/entitlements system, a per-route access check (so an NFL-only subscriber can't be served MLB picks for free), and per-sport Stripe pricing.

### 7.2 What a buyer actually sees

- A menu of sports, each showing: current price, its status label ("being tested, bet at your own risk" — every sport, every time, per the owner's standing rule), and a public record summary (win/loss, units, ROI, sample size, date range, and the statistical interval from §4 — never a bare headline number).
- A bundle card once 2+ sports have individually cleared the floor-pricing stage.
- Coming-soon sports (anything still in Stage 0/1 from §4.5) shown as free/research-only, not for sale — this already matches how NBA and NHL are pre-listed in the product's sport menu today, and UFC should launch the same way.
- **Important constraint from the legal research:** the record display shows only wins-losses-pushes, units at a flat stake, sample size, dates, and a range that visibly includes values below zero. **The pricing plan is explicit that ROI itself is never shown** on record displays, alongside dollar-profit projections, "expected profit," and "verified returns." **This is a live conflict, not a future rule:** the current record page (`web/js/cardrecord.js`) already displays a prominent "ROI PER UNIT STAKED" tile — flag this for the owner as something that needs to come down (or the written rule needs to change) before this becomes a customer-facing pricing page, not something to quietly loosen the rule to match what's already shipped.

### 7.3 Pricing numbers and unit economics

Researched competitor pricing (2026-09-21) clusters mainstream "pro picks" products around **$29.99/month** on monthly billing — Dimers and Rithmm's entry tier both confirmed at exactly that number [tier-1, fetched directly]. **On annual billing these run much cheaper, not $20-25/month:** Dimers' annual plan is $169.99 for the first year, about **$14.17/month** [tier-1]; BettingPros advertises "as low as $9.99/month" [tier-1]; Rithmm offers a "Yearly — save more" annual option but its specific annual price wasn't confirmed in this pass (its monthly tiers of $29.99/$49.99/$99.99 are confirmed) — UNVERIFIED, flagged rather than assumed. So LINEHOUND's $19.99 floor undercuts the *monthly* competitor price, but sits *above* what several competitors charge annual subscribers — a fair "we're new" position against monthly pricing, less clearly so against annual. Interestingly, the couple of existing UFC-specific tout products found in this research are priced far below that — **$10-50 per year**, not per month — which is either a sign nobody's willing to pay much for UFC picks yet, or a sign nobody has built a serious one at mainstream pricing (this research can't tell which; it's genuinely ambiguous, flagged as such rather than spun either way).

**Fixed monthly costs today** (these don't change with subscriber count — they're paid regardless of how many customers we have):

| Item | Cost | Note |
|---|---|---|
| The Odds API | $59/mo, 100K-credit tier (confirmed directly against the vendor's own pricing page — no disagreement) | Already subscribed |
| BALLDONTLIE ALL-ACCESS | **UNVERIFIED — do not book as a fixed $299.99/mo cost.** The client code documents this as a 48-hour trial (started 2026-09-15) and the account is currently rate-limited as if on a much lower tier. If it turns out we're not actually paying $299.99/mo (or don't need to), the cheapest path that still covers UFC results is the $9.99/mo MMA ALL-STAR tier (§5.2). | Confirm the actual plan and price before modeling this cost either way |
| Fly.io hosting | roughly $25-45/mo at current (beta) scale | |
| Auth (Clerk) | $0 (free tier) | |
| Domain/DNS | negligible (~$1/mo amortized) | |
| **Total, with BALLDONTLIE at $299.99/mo** | **~$385-405/mo** | Only if that plan and price are confirmed |
| **Total, without it (or on the $9.99 MMA tier)** | **~$85-115/mo** | The more conservative planning number until the BALLDONTLIE question is resolved |

**Marginal cost per subscriber** is essentially zero on the data side (the feeds are already paid for a flat monthly rate no matter how many people subscribe) — the only real per-subscriber cost is payment processing, stated in §8.1 as **roughly 3-7% of the charge depending on processor** (Whop, the recommended fallback processor, runs toward the higher end of that range, roughly 6-7%).

**Rough breakeven, shown at both ends of that 3-7% fee range** (not one implied midpoint, since the fallback processor sits at the expensive end): at $19.99/month, a subscriber nets **$19.39 at 3% fees, $18.59 at 7% fees**. Covering fixed costs takes:
- **With BALLDONTLIE at $299.99/mo (~$385-405/mo):** roughly **20-22 single-sport subscribers**, or about 14-15 bundle subscribers at $29.99.
- **Without it (~$85-115/mo, until that cost is confirmed):** roughly **5-6 single-sport subscribers**.

**This is a low bar either way — the current constraint on this business is getting subscribers and being able to charge for the product credibly, not the cost of running it** (see §7.4 — nothing in this plan yet says how those subscribers get found).

**Recommendation:** keep the $19.99 floor; do not price any sport (including MLB) above it until it clears the evidence bar in §4 — the research consistently found nothing to justify a higher starting price, and pricing above evidence would undercut the exact "we grade ourselves honestly, losers included" pitch that's LINEHOUND's real differentiator.

### 7.4 Go-to-market — the piece this plan doesn't cover yet

Everything above assumes subscribers show up. Nothing in this plan says how the first ones actually get found — that's a real gap given the owner's own framing ("a profitable system," "allow people to buy it"), not a detail to leave implicit. At minimum, before turning on billing (item 12): **owner to name a first-10-customer channel** — the obvious candidate given the stated niche edge is Brey's existing gaming/FiveM/LetsBeCops community, where there's already trust and an audience, versus cold acquisition into a crowded "pro picks" market. Whether that's a direct offer, a referral/affiliate mechanic, or something else is an open owner decision (§11), but the plan shouldn't reach "the product exists and is priced" and stop there.

---

## 8. Payments, hosting, legal/compliance

### 8.1 Payment processor — the real finding

**Stripe's own published policy** (fetched directly, quoted verbatim) bans: *"Sports forecasting or odds-making with a monetary or material prize."* Read closely, this clause is qualified by "with a monetary or material prize" — it's clearly aimed at contests where the *customer* wins a payout for correct picks (a pick'em contest), not a flat monthly subscription fee for information, which is what LINEHOUND actually is. **On the letter of the policy, a flat-fee picks subscription with no bet-placement and no prize payout is arguably outside what's banned.** But real-world reports (lower-confidence, marketing/support-forum sourcing) suggest Stripe's automated risk review sometimes flags "sports betting"-flavored subscription businesses for manual review or account freezes regardless of the precise wording — and a frozen account holding live subscriber money mid-launch would be a much worse outcome than finding this out now. **Recommendation: before charging real customers, either submit the actual site copy to Stripe for a pre-launch review or run a small live test charge, rather than assuming approval.**

**Two other general-purpose processors explicitly ban this category with no helpful carve-out** — Paddle's own Gambling category (Category 9) separately lists "betting-related products" and "sports forecasting/odds making where monetary or material prizes are involved" [tier-1, paddle.com], which is the clause that actually reaches this product (its "trading signals and strategies" clause is a different category, aimed at investment/financial advice, not sports picks). Lemon Squeezy bans "gambling" with no qualifier at all. **Neither is recommended** — the conclusion holds, just on the correct clause.

**Whop is the one processor whose policy explicitly names and allows this exact category**: *"[Whop] excludes information, analysis, picks, or other advisory services related to gambling or sports betting"* from its gambling ban. It's also where a meaningful share of existing pick-sellers already operate. Trade-off: Whop is a marketplace, not a pure white-label payment processor — the product would be listed inside Whop's own storefront, not purely on linehound.app, and fees run higher (roughly 6-7% all-in, based on lower-confidence third-party sourcing — the number should be re-verified directly on Whop's own current pricing page before being used to model costs).

**Recommendation:** pursue Stripe as primary (as already planned), but treat approval as a real go/no-go test to run *before* paid launch, not an assumption — and set up a Whop presence in parallel now, at low cost, as a documented fallback if Stripe underwriting is a problem.

### 8.2 FTC / advertising rules

The core rule: any performance claim ("we're up 8.2%!") needs to be backed by real evidence *before* it's said, not after, and the level of proof required scales with how confident the claim sounds. The good news: the underlying discipline this needs (timestamped, tamper-evident, sample-sized picks, losers included) is already built into the product. **The gap is procedural, not evidentiary:** whoever writes pricing or checkout-page copy needs a standing rule that no win-rate/ROI/units number ever appears without its sample size, date range, and a "self-graded, not third-party audited" note in the same sentence — and that this applies to the *pricing and checkout* pages specifically, not just the internal record page, since that's the page where competitors' worst overclaiming tends to live.

### 8.3 State-level licensing and age gating

No confirmed state law was found requiring a license to sell sports picks online (as distinct from operating a sportsbook) — the one concrete example found (Louisiana) only regulates physical "tout sheets" sold on racetrack premises, which doesn't obviously reach an online, non-racing product. This is consistent with the product's existing legal research and remains **an open question for a lawyer to close, not a cleared one.** A 21+ age gate and responsible-gambling messaging are good practice and low-cost to add, but nothing found makes them a confirmed legal requirement for a pure information product (as opposed to an actual sportsbook) — treat them as a credibility choice, not a compliance mandate. **Do not hard-code a specific responsible-gambling helpline number without a same-week check** — the standard national number is reportedly mid-transition to a new number, and the existing legal research already flagged this as unresolved. **Scheduled as item 20 in §9.1 and decision 17 in §11** — flagged in prose here previously but not actually on the build list or the decisions list, which is fixed below.

### 8.4 Hosting — what's live vs. blocked

- **Staging is live and public today, but it's giving the whole product away for free** — a "demo mode" setting removes the paywall entirely on the staging URL. This is intentional for testing, but it means nobody should ever point the real domain (linehound.app) at it.
- **The real production site does not exist yet.** The configuration for it is fully written and ready — what's missing is four steps that only the account owner can do (create the Fly.io app, create its storage volume, set an admin secret, and provide a deploy credential), plus an automated deploy workflow for it (not yet written) and final legal copy sign-off. This is a small amount of engineering work blocked entirely on the owner's calendar, not a hard technical problem.
- **The domain is bought and ready** (linehound.app, via Cloudflare, purchased 2026-09-17) but not yet pointed anywhere, because there's no production site yet to point it at.
- **How data actually gets from capture to the live site today is worth understanding:** automated jobs pull odds/results roughly every 13 minutes and save them directly as files committed to the code repository — there is no separate live database. This means the file-size problem in §9.2 isn't just a storage annoyance; if a commit can't go through, the whole site quietly stops updating.

### 8.5 What needs a lawyer (not resolved here, flagged explicitly)

- Whether "we're an information service, not a gambling operator" holds up in every state we'd actually market in.
- Whether any state's picks-seller/handicapper rule (beyond Louisiana's narrow, racetrack-specific one) reaches an online product like this.
- A real conversation with Stripe (or someone experienced with Stripe underwriting) about how their risk team reads this business in practice, not just the policy text.
- Final sign-off on Terms of Service and Privacy Policy before anyone can actually pay.
- Confirming the current, correct responsible-gambling helpline number before it goes on any page.

---

## 9. Engineering plan

### 9.1 Ordered build list

**S = small (config/plumbing, days), M = medium (a real feature, roughly a week), L = large (a real subsystem, multiple weeks), XL = a new domain of the size the original MLB build was.** **Executor:** who actually does the item — "Builder" means whoever's doing the engineering work day to day (contractor or agentic build pipeline, per Brey's usual setup), "Owner" means only Brey can do it (an account, a legal sign-off, a business decision).

| # | Item | Size | Executor | Depends on |
|---|---|---|---|---|
| 0 | ~~Fix the live capture outage~~ — **done** (`f0b68c70`, 17:41Z). Remaining: archive `derivative_markets`, `decisions_v2`, `batter_props` the same way (§9.2) | S | Builder | none |
| 1 | Close the credit shortfall for the reset window (§9.2) — cut spend, lower the floor, or buy a bigger tier; raising the daily-cap knob alone does not add credits | S | Owner decision, then Builder | Owner decision |
| 2 | ~~Fix the oversized data file~~ — folded into item 0 above; this was already broken, not a 7-day-out risk | — | — | — |
| 3 | Cross-sport public record page (§4.1), including the `/card/record` and `/card/history` public-router change (currently gated behind paid access) | S | Builder | none |
| 4 | Adapt CLV measurement to the live V1 card and wire it into the daily pipeline + scoreboard (§4.4) | M | Builder | none — code exists for a different card, needs real adaptation |
| 5 | Multiple-comparisons correction in the pricing step-up script (§4.3) | S | Builder | Item 3 |
| 6 | NCAAF shadow test | S | Builder | Item 1 |
| 7 | UFC odds adapter + a real, measured credit cost for it | S | Builder | Item 1 |
| 8 | UFC value-rule shadow test (Arm A), published as Stage-1 public research page per §5.1's exception | S-M | Builder | Item 7 |
| 9 | UFC results source — confirm the actual BALLDONTLIE plan; buy MMA ALL-STAR ($9.99/mo) directly if ALL-ACCESS doesn't cover it; stand up manual grading (news/broadcast source, not UFC.com) as fallback regardless | S | Builder + Owner (the $9.99/mo purchase) | none — free to test, no credits spent |
| 10 | UFC fight-week rules: per-fight lock timing, fighter-swap void handling | M | Builder | Owner decisions (§11) |
| 11 | NHL: sport spec + results-feed connector | M | Builder | Item 1 |
| 12 | The full per-sport billing system: plans, entitlements, per-route access checks, per-sport Stripe pricing, the price-move-down/grandfathering rule from §7.1 (this is the entire `PER_SPORT_PRICING_PLAN.md` §4 build) | L | Builder, with a careful review pass before merging (touches billing and access control) | **Owner authorization — see decision 15, §11**; this was previously undecided in name only |
| 13 | Per-sport pricing-review script (computes the step-up price from the real ledger data, using the §4.5/§7.1 formula) | S | Builder | Item 12 |
| 14 | Frontend: per-sport and bundle pricing cards | M | Builder | Item 12 |
| 15 | Production site go-live (the four owner-only account steps + a deploy workflow) | M (workflow) + S (account steps) | **Owner** (account steps) + Builder (workflow) | Owner-only steps; legal sign-off |
| 16 | NBA: sport spec + results-feed connector (results-feed reliability unresolved — confirm before relying on it for grading) | M | Builder | Item 1 |
| 17 | NCAAB, scoped to ~100 teams | L | Builder | Item 1; deliberate scoping decision |
| 18 | Soccer: new three-way pricing math + sport build | L (real subproject) | Builder | none scheduled — opportunistic |
| 19 | UFC fighter-rating model (shadow) | L | Builder | A confirmed, legal results/fighter-data source (currently blocked, §5.2) |
| 20 | 21+ age gate + responsible-gambling messaging, site-wide | S | Builder | Owner sign-off on the helpline-number check (§8.3, §11) |

### 9.2 The infrastructure risks that block everything else

1. **The 100 MB file wall. It caused a live outage today, now fixed, and it will return for other files.** `odds_multibook.jsonl` passed GitHub's 100 MB per-file limit. Every forward-capture push from 14:39Z to 17:41Z was rejected (red runs, `ESCALATE: push failed after retries`), so about 3 hours of odds captures for every sport were lost. The fix (`f0b68c70`) moves old rows automatically into compressed, git-tracked archive files that every reader still sees. The first production run at 17:41Z archived 08-31..09-17 into a 2.3 MB file and left the live file at 36 MB. **Still open:** `derivative_markets.jsonl` (63 MB), `evidence/decisions_v2.jsonl` (57 MB) and `batter_props.jsonl` (40 MB) need the same archiving. A size warning now fires at 75 MB and escalates at 95 MB. Every sport added (NFL alone is about 5 MB a day of odds rows) brings this closer.
2. **The credit budget is short for the reset window, a separate and smaller problem.** We currently have roughly 4,400-4,700 credits of real headroom above the hard floor we won't go below. At the current 900/day approved envelope, if it fully binds from here, the floor lands **around 2026-09-26 — UFC's own Saturday card** — five days before the assumed 10-01 reset. **Raising the daily-cap knob does not fix this and can make it worse:** the knob only raises how much *can* be spent per day; it adds no credits and doesn't move the 5,000 floor. Raising utilization from 27% to the approved 35% ceiling would raise the daily allowance to roughly 1,167/day, which — if actually spent at that rate — would pull the floor date *earlier* (roughly 09-25), not later, landing it *before* UFC Saturday instead of on it. The real levers are: (a) cut spend below 900/day for the rest of the window (the 09-15 to 09-21 elevated spend came from a since-fixed checkpoint bug, not steady demand — see below, so this may already be improving); (b) get the owner to accept a lower floor for this window; or (c) buy the bigger $119/mo, 5M-credit tier (confirmed price, §10) — the daily-cap knob by itself is not one of the fixes.
3. **Most of this cycle's spend was one event, not steady demand — worth knowing before assuming three sports "use the entire 900/day."** Of the ~90,000 credits spent since the 09-02 reset, **73,850 went to a single-day historical backfill on 09-04** (99,365 → 25,515 in one day, confirmed in `credit_log.jsonl`). Live, steady-state MLB-only spend from 09-05 to 09-14 ran roughly 250-1,400/day. The elevated spend from 09-15 to 09-20 (mostly 1,400-1,650/day, with one clear outlier day near 4,100) is attributed in `docs/reports/2026-09-21_WHERE_WE_ARE.md` to a lost-checkpoint capture bug, fixed at 04:14Z today — not to what MLB+NFL+tennis actually need in steady state. Tennis capture only started today. **Whether the three current sports genuinely need the full 900/day, once the bug-fix holds, is not yet measured** — treat this as a 10-day problem that should ease at the reset and as the fix holds, not a permanent structural shortfall, without over-committing to a bigger paid tier before that's known.

### 9.3 Schedule

**Today:**
- ~~Fix the live capture outage (item 0)~~ done 17:41Z. Next: add the other three large stores to archiving before they reach 75 MB.

**Next 7 days (by 2026-09-28):**
- Close the credit shortfall (item 1) — cut spend / accept a lower floor / buy the bigger tier, chosen with the owner (§11); confirm this doesn't push the floor earlier than UFC Saturday.
- Confirm the actual BALLDONTLIE plan and buy MMA ALL-STAR directly if needed (item 9) — free to test, no credits spent; the $9.99/mo purchase needs the owner.
- Build the UFC odds adapter and get a real, measured credit cost for it (item 7).
- Launch the UFC value-rule shadow test as a public Stage-1 research page in time for Saturday 09-26 (item 8), graded manually against a news/broadcast source — not UFC.com. Set expectations that it may publish 0-2 picks.
- Decide UFC's fight-week operational rules (lock timing, fighter-swap handling) — owner decision needed first (§11).
- Adapt CLV to the live card and wire it into the pipeline (item 4) and stand up the cross-sport record page, including the public-router change (item 3).

**Next 30 days (by ~2026-10-21):**
- NCAAF shadow test live.
- NHL build complete in time for its 09-29 season opener.
- Start the full per-sport billing build (item 12) — this is the largest piece of engineering work in this plan and should start early given its size.
- Production site go-live, contingent on the owner completing the account-setup steps (item 15).
- Run the Stripe underwriting test / test charge (§8.1), in parallel with standing up a Whop presence.
- NBA build underway, targeting its 10-20 season opener, with its results-feed reliability question resolved before launch.

**Next 90 days (by ~2026-12-20):**
- Per-sport billing live: customers can buy one sport or a bundle.
- Multiple-comparisons correction live in the pricing step-up script before any sport is allowed to step above the floor.
- NCAAB live, scoped to roughly the top 100 programs, ahead of its 11-01 tip-off.
- UFC evaluated for whether it can move from "free research page" to "priced at the floor," based honestly on whatever record has accumulated by then — not before.
- Revisit MLB's own pricing status once its interval has had more time to narrow (mindful that its regular season ends 09-27, so its *rate* of new evidence slows until spring).

---

## 10. Costs — subscriptions and credits, with the arithmetic

**Already-committed monthly subscriptions:**

| Item | Monthly cost | Status |
|---|---|---|
| The Odds API | $59/mo, 100,000-credit tier (confirmed directly against the vendor's own pricing page — matches the repo's docs, no disagreement) | Active |
| BALLDONTLIE ALL-ACCESS | **UNVERIFIED, do not book as $299.99/mo** — our own client code documents this as a 48-hour trial started 2026-09-15, and the account is currently rate-limited well below the ALL-ACCESS tier's stated ceiling | Confirm the real plan; tennis results 401 either way |
| Fly.io hosting | ~$25-45/mo | Active (staging) |
| **Total, if BALLDONTLIE is confirmed at $299.99/mo** | **~$385-405/mo** | |
| **Total, if not (conservative planning number)** | **~$85-115/mo** (up to $105 alone; up to $115 if the $9.99/mo MMA ALL-STAR tier is added for UFC results) | |

**Credit math, worked out:**

- Current balance: roughly 9,400-9,600 credits (9,436 at 14:26Z today, before the outage in §9.2 item 1 stopped further capture).
- Hard floor (never go below): 5,000.
- Usable headroom: roughly **4,400-4,700 credits.**
- Current approved daily envelope: 900 credits/day.
- Days until the (assumed, unconfirmed) monthly reset: roughly 10.
- At the full 900/day rate for 10 days, that's **9,000 credits needed** against ~4,400-4,700 available — a real shortfall for the reset window, independent of any new sport. If the 900/day cap fully binds from today, the floor is projected around **09-26 — UFC's own Saturday card, not comfortably before it.**
- **Raising the daily-cap knob is not a fix, and can make the UFC-day problem worse.** Utilization is currently 27% of the monthly allotment (the 900/day figure); the internal policy ceiling is 35% (roughly 1,167/day). That knob only changes how much is *allowed* to be spent per day — it adds no credits and doesn't move the 5,000 floor. If actually spent at 1,167/day, the floor arrives sooner (roughly 09-25), a day *before* UFC Saturday instead of on it. Real fixes: cut spend, accept a lower floor for this window (owner decision), or buy the bigger tier below.
- **Paid tier upgrade:** confirmed directly against the vendor — $119/mo for 5,000,000 credits (versus $59/mo for 100,000 today), roughly 2x the price for 50x the credits. Billing renews "on the same day of the month that the subscription started," so the reset date is inferred from the credit log (~10-01/10-02), not read off an account page in this pass.
- **Most of this cycle's spend was a one-day historical backfill (73,850 credits on 09-04), not steady three-sport demand** (§9.2 item 3) — whether MLB+NFL+tennis genuinely need the full 900/day once the checkpoint bug stays fixed is not yet measured, so treat the shortfall as likely to ease, not assume it's permanent before spending on a bigger tier.
- **UFC's own credit cost, once the above is fixed, is trivial** — roughly 20-30 credits for an entire fight week, because The Odds API charges per data-pull, not per fight, and a UFC card is captured far less often than MLB's daily 15-game slate.
- **NHL/NBA, by contrast, are real new draws** — rough (unmeasured — flagged as such, following the product's own rule of never spending against a guessed number) estimates put each at roughly 150-450 credits/day in-season, which would roughly double or triple the current 900/day envelope on its own. **This is exactly why the credit shortfall has to be closed before NHL or NBA capture turns on**, not as an afterthought.

---

## 11. Decisions for the owner

Each numbered with a recommended default — these are the things that need Brey's sign-off before the plan above can move.

1. **~~Approve the emergency fix to the live capture outage~~ — done, no decision needed.** The fix was pushed at about 17:45Z (commit `f0b68c70`). Old rows move automatically into compressed archive files that every reader still sees, and a new warning fires when any file nears 100 MB. Captures from about 14:39Z to the first run on the fix are lost. See the status report for confirmation from production.
2. **Credit shortfall for the reset window: pick a lever.** Raising the daily-cap knob alone doesn't add credits and can pull the floor date earlier than UFC Saturday. Choose among: cut spend below 900/day until the reset, accept the floor landing on/near 09-26 and let the site go read-only-on-odds if it hits, or buy the $119/mo 5M-credit tier. *Recommendation: hold off on the paid upgrade for a few days — most of this cycle's spend was a one-time 09-04 backfill and a since-fixed checkpoint bug, so the shortfall may ease on its own; revisit if 09-22/09-23 spend is still elevated.*
3. **MLB's V1 card breaks the owner's own -200 rule** (every game pick is a favourite, 16 of 100 at -200 or worse; 44 of 94 props too) **and the owner separately said not to alter V1 midstream (09-17).** These conflict. Decide: grandfather V1 as a legacy exception to the -200 rule, or accept altering it despite the earlier instruction. *Recommendation: grandfather explicitly and say so in writing — don't leave this as an unstated exception, since it will come up again with new sports.*
4. **UFC fight-week lock timing:** lock each fight independently a set number of hours before its own estimated start, or lock the whole card at once? *Recommendation: per-fight, with a simple fixed-offset fallback if per-fight timing estimation isn't ready by Saturday.*
5. **UFC fighter-swap handling:** what happens to a locked pick when a fighter is replaced on short notice? *Recommendation: automatically void it — do not carry a locked pick over to a fight that's no longer the same matchup.*
6. **UFC results grading for launch:** confirm the real BALLDONTLIE plan (buy MMA ALL-STAR at $9.99/mo directly if needed); manual grading against a news/broadcast source (never UFC.com — its terms ban manual monitoring too) as the near-term fallback regardless. *Recommendation: approve both the $9.99/mo purchase and the manual-grading stopgap now so Saturday isn't blocked on a vendor test landing in time.*
7. **Payment processor path:** Stripe as primary, with a pre-launch underwriting test/test charge, and a Whop presence stood up in parallel as a fallback. *Recommendation: approve both, in parallel, now — avoid Paddle (its actual disqualifying clause is "betting-related products," not the trading-signals one) and Lemon Squeezy entirely.*
8. **Pricing discipline: no sport — including MLB — gets priced above the $19.99 floor until it clears the full evidence bar in §4**, even though MLB's headline number looks good today; and nothing gets *priced at all* (even the floor) until it's actually sold somewhere, which nothing is yet. *Recommendation: hold this line; it's the product's actual differentiator (self-graded honesty, losers included) and pricing ahead of the evidence would undercut it.*
9. **Public messaging discipline:** every sport carries "being tested, bet at your own risk"; only MLB may say "our longest-running test"; no sport, including UFC, gets "proven edge" language; and the live record page's ROI tile needs a decision (drop it to match the written no-ROI rule, or change the written rule to match it — see §7.2). *Recommendation: enforce the no-ROI rule as written and fix the page to match, rather than the reverse.*
10. **Adopt the multiple-comparisons correction (§4.3) in the pricing step-up logic before any sport is allowed to step above the floor.** *Recommendation: yes — build this in from the start rather than retrofitting it after a sport has already been priced up.*
11. **Adapt CLV measurement to the live V1 card and surface it on the new scoreboard** (it currently measures a different, not-yet-live card and isn't shown to anyone). Separately: **should CLV ever gate the pricing step-up**, or stay advisory-only as the architecture doc currently mandates ("never a daily score," never gates `promotion_verdict`)? *Recommendation: build the V1-card adaptation now; keep CLV advisory-only unless the owner explicitly wants to change that architecture rule.*
12. **Schedule the four owner-only production go-live steps** (Fly.io app creation, storage volume, admin secret, deploy credential) plus final legal copy sign-off. *Recommendation: put this on the calendar inside the 30-day window — it's the one blocker in this whole plan that no amount of engineering time can substitute for.*
13. **NCAAF: ship as a free shadow test rather than skip it entirely**, since it's already in season and cheap to build, but keep it unpublished given the weekly-cadence sample problem. *Recommendation: yes, ship shadow, don't sell it yet.*
14. **NCAAB scope: cap initial coverage to roughly the top 100 programs**, not full Division I, to control both the credit cost and the team-matching build. *Recommendation: approve the cap; revisit expanding it only after NCAAB's own record and credit draw are measured.*
15. **Authorize starting the per-sport billing/entitlements build (§9.1 item 12)** — the largest and highest-risk item in this plan (it touches billing and access control) has been described as needing "owner go-ahead" without ever appearing as its own numbered decision until now. *Recommendation: approve starting it inside the 30-day window, on the condition that it ships the price-move-down/grandfathering rule from §7.1, not just the step-up path.*
16. **Add a mid-cycle kill switch for a priced sport's live results turning sharply negative**, rather than waiting for the next quarterly review (§4.5 currently only reviews quarterly, even though CLV — once wired up per decision 11 — could flag a problem faster). *Recommendation: yes — e.g., if the block-bootstrap interval turns and stays negative for N consecutive days, auto-suspend new sales pending review; N itself is an open call, propose N=14 as a starting point.*
17. **Approve the age-gate + responsible-gambling messaging item (§9.1 item 20)** as a scheduled build item, not just a prose mention. *Recommendation: yes, ship it alongside whichever sport goes to production first — low cost, credibility upside.*
18. **Name a first-10-customer acquisition channel before billing turns on** (§7.4) — most likely Brey's existing gaming/FiveM community, but that's a call only the owner can make. *Recommendation: decide this in parallel with the billing build (item 12/15), not after it ships — a finished, priced product with no channel to reach first buyers wastes the billing work.*

---

## Appendix: sources, with tiers

**Tier 1 = official/vendor primary source or peer-reviewed academic paper. Tier 2 = named practitioner or a credible secondary/community source. Tier 3 = marketing, aggregator, or SEO content — used only for context, never as evidence of an edge.**

**Internal (this repo, read directly — treated as tier-1, it's our own first-party data):**
`src/appstate/card_ledger.py`, `api/card.py`, `api/app.py`, `src/analysis/lobo_value.py`, `src/analysis/nfl_value.py`, `src/report/clv.py`, `src/report/card_clv.py`, `src/pipeline/snapshots.py`, `src/factory/scorecard.py`, `src/sports/spec.py`, `src/sports/__init__.py`, `src/providers/odds.py`, `src/providers/balldontlie.py`, `src/board/gamekey.py`, `src/capture/budget.py`, `config/capture_families.json`, `web/js/sport.js`, `web/js/card.js`, `web/js/cardrecord.js`, `api/auth.py`, `src/appstate/billing.py`, `src/appstate/customers.py`, `deploy/secrets.md`, `evidence/cards_v1.jsonl`, `evidence/cards_nfl_v1.jsonl`, `evidence/mlb_value_shadow_v1/*`, `data/processed/credit_log.jsonl`, `data/processed/odds_multibook.jsonl`, `docs/PER_SPORT_PRICING_PLAN.md`, `docs/COMMERCIAL_READINESS.md`, `docs/LAUNCH_DECISIONS.md`, `docs/LEGAL_COMPLIANCE_RESEARCH.md`, `docs/MULTI_SPORT_2026-09-14.md`, `docs/MULTISPORT_AUDIT.md`, `docs/PREREG_NFL_CARD_V2.md`, `docs/PREREG_MLB_VALUE_SHADOW_V1.md`, `docs/DOES_THE_MODEL_BEAT_THE_MARKET.md`, `docs/ARCHITECTURE_BETTING_ENGINE.md`, `docs/EVOLAB_PHASE2B_RESULTS.md`, `docs/reports/2026-09-21_WHERE_WE_ARE.md`, GitHub Actions run logs for the `forward-capture` workflow (runs 35611904025, 35613385266, 35614832630, 35616287198, 35617778799, 2026-09-21).

**Tier 1 (external, official/vendor primary or peer-reviewed):**
- The Odds API — MMA/UFC product page (the-odds-api.com/sports/mma-ufc-odds.html) and MMA odds-data page (sports-odds-data/mma-odds.html), v4 API docs (quota/cost).
- BALLDONTLIE MMA API docs (mma.balldontlie.io) and main pricing page (balldontlie.io).
- UFC.com Terms of Use (ufc.com/terms) — fetched and quoted directly.
- Sherdog Terms of Use, Tapology Terms of Use.
- Miller, K.M. & Nichols, M.W. (2026), "Efficient market insights and favorite-longshot bias in mixed martial arts betting markets," *Journal of Economics and Finance* (via IDEAS/RePEc abstract mirror, re-fetched directly this pass) — resolves a discrepancy between two of our own research memos in favor of "no bias found"; see §5.3.
- Stripe Prohibited/Restricted Businesses page and Pricing page (stripe.com).
- Paddle prohibited-products help page; Lemon Squeezy prohibited-products docs.
- FTC Policy Statement on Advertising Substantiation; 16 CFR Part 255 (Endorsement Guides); 16 CFR Part 437 (Business Opportunity Rule).
- Louisiana Administrative Code tit. 46, §XLI-1701 (racetrack tout-sheet licensing).
- Action Network, Dimers, BettingPros, Rithmm, Unabated pricing pages (competitive pricing table, §7.3).
- Fly.io pricing docs.

**Tier 2 (named practitioner / credible secondary):**
- Joseph Buchdahl on closing-line-value sample sizes, via a third-party site republishing Pinnacle-sourced content — not independently confirmed on pinnacle.com directly in this pass.
- Wikipedia's "2026 in UFC" event schedule (community-maintained, sourced to UFC's own announcements — used for the fight-date table in §5, cross-check against UFC.com directly before locking any capture calendar).
- NHL/NBA/NCAAF season-calendar reporting (NHL.com, NBA press materials, Wikipedia's NCAA football season page).
- CollegeFootballData.com (free community results API for NCAAF grading).
- Dodo Payments' Whop fee breakdown; Whop's own trust-and-safety policy text (accessed via search synthesis — recommend a direct re-fetch before relying on it for underwriting).

**Tier 3 (marketing/aggregator — context only, never used as evidence of an edge):**
- Crawlbase blog on UFC-stats scraping practices; OddsPapi's Odds-API pricing breakdown; sportsapis.dev on ESPN's unofficial API; various high-risk-merchant-account fee-comparison sites (PaymentCloud, Durango, Merchant Maverick); small UFC-specific Substack/marketplace pricing examples (Money MMA, We Want Picks).

**Explicitly UNVERIFIED in this pass (do not treat as fact until checked):**
- **Whether we are actually on, or billed for, BALLDONTLIE "ALL-ACCESS" at $299.99/mo at all** — our own client code documents this as a 48-hour trial started 2026-09-15, and the account is currently rate-limited well below that tier's stated ceiling. This is a bigger open question than just "does it return UFC data" (which is also unverified) — it's whether the $299.99/mo fixed-cost line item is real.
- Whether The Odds API offers a working UFC totals (round-total) market today, beyond moneyline — one vendor page mentions "limited coverage... from some bookmakers," a second doesn't mention it; genuinely unconfirmed rather than contradictory, and out of scope for launch either way.
- Whether a free, sufficiently reliable NBA results feed exists at the same quality level as MLB's or NHL's official feeds.
- Rithmm's actual annual-billing price (the page offers a "Yearly — save more" toggle; the discounted number itself wasn't confirmed in this pass, unlike Dimers' and BettingPros' annual/low prices, which were).
- Exact current fees on Whop's own pricing page (not independently re-fetched in this pass; §7.3 uses the high end of the stated 3-7% range for it, which should be confirmed against Whop's actual current number).

**Resolved this pass (previously listed as unverified or disputed):**
- The Odds API's price: confirmed directly — $59/mo for 100,000 credits, $119/mo for 5,000,000 credits, billing renews on the subscription's own monthly anniversary. Matches the repo's docs; there was never an actual disagreement to reconcile.
- The Miller & Nichols (2026) MMA finding: confirmed directly from the abstract — no favorite-longshot bias found in MMA. The "significant bias" characterization in one internal memo was wrong; see §5.3.
- UFC.com's Terms of Use: confirmed to ban "any similar or equivalent manual process" alongside automated scraping — manual grading cannot use UFC.com as its source; see §5.5.
- Paddle's disqualifying clause for this business: confirmed as "betting-related products" / "sports forecasting... where monetary or material prizes are involved" (Gambling category), not the separate trading-signals/investment-advice clause; see §8.1.
