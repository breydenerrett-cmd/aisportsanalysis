# LineHound survival dashboard

Generated 2026-10-04 18:29Z by `scripts/survival_dashboard.py`. Edit `config/business.json` and log outreach with `scripts/outreach_batch.py`, not this file.

| | |
|---|---|
| Days until 2026-10-31 | **27** |
| Current monthly burn (known + estimated infrastructure) | $78.00 |
| Current monthly burn incl. Claude at the planning assumption | $278.00 (unknown: Claude subscription that operates the business, BALLDONTLIE) |
| Identified monthly savings (not yet realised) | $29.00: The Odds API (100K tier): $29.00 (downgrade to the $30 20K tier; NOT confirmed, owner decision) |
| MRR (config, manual: manual until /admin/revenue is read from production) | $0.00 |
| Testers granted | 0 of 20 (config, owner-updated) |
| CAC | $0 spent on acquisition |
| Gap to break-even | $278.00 per month |

## Customer discovery

Read from `docs/sales/outreach_queue.csv`, people only. A forum thread is a public post, not a human, and a queued person nobody has contacted is not a lead.

| Measure | Value | What it counts |
|---|---|---|
| UNIQUE LEADS | 0 | People (not channel posts) who were sent a message, replied or signed up. Queued people nobody has contacted are not counted. |
| MESSAGES SENT | 0 | Rows of any kind with a send logged, so a thread posted counts here. |
| REPLIES | 0 | People with a reply logged. |
| POSITIVE REPLIES | 0 | People whose reply type is POSITIVE_INTEREST, SIGNED_UP, ACTIVE_TESTER or WOULD_PAY. |
| SIGNUPS | 0 | People with a signup logged. |
| ACTIVE TESTERS | 0 | People whose tester access was granted less than 7 days ago. |
| ACTIVATED USERS | 0 (from the outreach log) | People with an `activated` entry in the outreach log. |
| RETURNING USERS | 0 (not measured yet) | Activated testers who used it again 12 hours or more after their first use; needs `tester_activity` in config. |
| WOULD PAY | 0 (0 said no) | People who said yes to paying; the number who said no is beside it. |
| PAID USERS | 0 | People with a payment logged. |
| REVENUE | none logged (no `paid` lead in the queue) | Revenue figures from `paid` events for those people; nothing is estimated. |

- queued, not yet contacted: 37 (people in the queue with no message, reply or signup; not leads)
- channel posts made: 0 (forum threads posted; a thread is not a human, so it is not a lead)

| Rate | Value | Definition |
|---|---|---|
| Reply rate | 0 of 0 (no rate yet) | People sent a message who replied, of people sent a message. |
| Signup rate | 0 of 0 (no rate yet) | Signups of unique leads. |
| Activation rate | 0 of 0 (no rate yet) | Activated of signups, both from the outreach log so they are the same people. |
| Would-pay rate | 0 of 0 (no rate yet) | Yes of everyone who answered yes or no. |
| Paid conversion | 0 of 0 (no rate yet) | Paid users of unique leads. |

## Milestones (first timestamp of each, UTC)

- First message sent: not yet
- First reply: not yet
- First positive reply (the time of that lead's first reply): not yet
- First signup: not yet
- First tester access: not yet
- First active tester: not yet
- First feedback: not yet
- First would-pay (yes): not yet
- First payment: not yet

## Current sports

- MLB postseason (card, hits and total-bases props)
- NFL (value lines)
- UFC (published; graded by hand)

## Performance by market (counted picks; never pooled) and CLV

- **MLB current** (Our value card; 2026-09-22..2026-09-27): n=33: 16-17, -5.05u, ROI -15.3%
  - game: n=3: 2-1, +0.69u (too few for a rate)
  - prop: n=30: 14-16, -5.74u, ROI -19.1%
  - fills (shown apart, never counted): n=29: 21-8, +7.68u (too few for a rate)
  - postseason (graded, not counted): n=10: 5-5, -0.48u (too few for a rate)
- **MLB previous** (Our first card rule; 2026-09-10..2026-09-22): n=230: 151-79, +7.98u, ROI +3.5%
  - game: n=113: 73-40, +7.61u, ROI +6.7%
  - prop: n=117: 78-39, +0.38u, ROI +0.3%
- **NFL current** (Our NFL value rule; 2026-09-27..2026-09-27): n=1: 1-0, +0.93u (too few for a rate)
  - game: n=1: 1-0, +0.93u (too few for a rate)
- **NFL previous** (Our first NFL rule; 2026-09-17..2026-09-21): n=10: 7-3, -0.26u (too few for a rate)
  - game: n=10: 7-3, -0.26u (too few for a rate)
- **MMA current** (Our UFC card; 2026-09-22..2026-10-03): n=9: 8-1, +4.80u (too few for a rate)
  - game: n=9: 8-1, +4.80u (too few for a rate)

Closing-line value: see `docs/VALUE_SCAN.md` (the standing measurement; no CLV figure is computed or copied here). No rule here has evidence of an edge.

- V2 MAIN picks 16-17, -5.05u; 19 of the 33 are one day (2026-09-22, cap breach, -5.14u).
- Everything shown to readers under V2 (picks plus fills): 41-27, +3.46u.
- Closing-line value is negative in every segment measured (V1 games -1.21 pts, n=51; props about -3.5).
- Our number scored worse than the market's in 12 of 16 populations and never significantly better.

## Production health and capture cost

- Production health: Run `python scripts/prod_watch.py`. 2026-10-03: production served 09:02Z data until 16:08Z behind one stalled deploy (docs/audit/2026-10-03/PROD_DEPLOY_HANG.md); the watch now flags a deploy unfinished for 20 minutes. Known noise: the daily loop fails on days with no MLB games (2026-10-02).
- Capture cost: 10.9 credits an hour after the cadence change against 23.6 before (2026-10-01, one evening, not a representative game day). Metric: credits per useful fresh observation; re-measure after Sunday. docs/audit/2026-10-01/PRODUCTION_RECOVERY.md.

## Top 3 blockers

1. Nobody has been contacted: 40 leads are queued, 0 messages sent. Everything in front of sending is done (domain, tracking, tester access, production current). What remains is the owner's two-minute funnel check with the admin token, then sending batch 1 by hand.
2. Stripe is not live: the account is verified (2026-10-02). Next: rehearse a purchase on staging in test mode (docs/GO_LIVE_2026-09-28.md section 5), then the Stripe secrets on production. Owner.
3. Discord feed not wired: needs the webhook secret and one env line on the default branch. Owner + me.

## Next actions

- **Owner:** 0) Verify the BALLDONTLIE billing status (UNKNOWN: an unauthorized key does not prove billing stopped); what to do about it is your decision. 1) Send the five invitations (docs/sales/SEND_ORDER.md, top section); each carries the live sample link https://linehound.app/web/sample.html; report each send. 2) Open the Padres at Brewers game page on production with a tester account and confirm the brief shows. 3) Stripe test-mode rehearsal on staging, about 15 minutes (docs/billing/PURCHASE_REHEARSAL.md): first subscribe the staging webhook to invoice.paid and invoice.payment_failed. 4) Send Stripe the support question (docs/billing/STRIPE_SUPPORT_QUESTION.md). 5) Decide: MLB's data terms allow individual, non-commercial, non-bulk use only (docs/audit/2026-10-04/COLLECTION.md); repeat free trials and legacy rows (PURCHASE_REHEARSAL.md, Owner decisions); resuming team-total capture, about 96 credits a day (docs/decisions/derivatives-capture.patch). 6) Three cost numbers: Claude plan, Fly bill, domain. 7) Recommended: the Anthropic API key with a $10 limit, so briefs need no live session. Resume a brief any time: say "run the brief" (docs/BRIEF_RUNBOOK.md).
- **Customer:** Batch 1 goes out in five small groups, best fit first; group 1 is written and waiting. Log sends and replies with scripts/outreach_batch.py (exact words stay in a private local file). Grant tester spots only to people who bet these sports, will use it and will give feedback (docs/sales/DISCOVERY_GUIDE.md). After five real conversations: stop and synthesise before changing the product.
- **Product:** Delivery is session-assisted, not unattended. A brief for each playoff game before first pitch (docs/BRIEF_RUNBOOK.md); grade yesterday's. Briefs from now on use prompt v4 (no "packet" in reader text, one-sided missing lineups listed, the props line states the real reason); the two briefs already published keep their wording. Research, no live change: the opposing starter helps total bases slightly (docs/research/TB_STARTER_AWARE_RESULT.md); a pitcher-specific strikeout model beats a league baseline (docs/research/K_BASELINE_RESULT.md); both need a market comparison before any promotion.
- **Model:** No market shows repeatable value (docs/PERFORMANCE_MATRIX.md: 110 measured populations, 0 candidates; moneyline closing-line value negative on 26 of 26 rows). The props question cannot be answered before 2026-10-31: the best-placed family, batter total bases, reaches a minimum sample about five weeks into the 2027 season (docs/PROP_EXPERIMENT_INVENTORY.md, docs/PREREG_PROP_FAMILIES_DRAFT.md, a DRAFT with seven owner decisions). Until then: sell the public record and the price comparison, not an edge. AI critic: adds one catch over a plain rule on 8 cases and is not ready to show customers (docs/AI_CRITIC_BENCHMARK.md).

## What survival requires

- Infrastructure only ($78.00): 5 x Individual, monthly at $19.99
- Infrastructure only ($78.00): 1 x Community feed, per server at $149.00
- Everything incl. Claude ($278.00): 15 x Individual, monthly at $19.99
- Everything incl. Claude ($278.00): 2 x Community feed, per server at $149.00

## Costs and the kill list

| Item | Monthly | Basis | Kind | Evidence | Verdict | Note |
|---|---|---|---|---|---|---|
| The Odds API (100K tier) | $59.00 | estimated | fixed subscription | Plan price $59; the 100,000 quota reset is in data/processed/credit_log.jsonl on 2026-10-01. Invoice not seen. | KEEP | Prices every card. September used 95,101 of 100,000 credits. Since the re-buy fix, October is running at about 270 a day (814 in the first three days, postseason slate, no NFL Sunday yet), which would be about 8,400 a month and fit the $30 20K tier. Re-measure after two NFL Sundays before deciding. What the smaller tier loses: headroom for backfills and new-market probes. Owner decision. |
| Fly.io production (2 shared CPUs, 1 GB, 1 GB volume) | $15.00 (est.) | estimated | usage, roughly fixed | Machine size from deploy/fly.production.toml times list price. Invoice not seen. | KEEP | Estimate. Exact figure: Fly dashboard, billing. |
| Fly.io staging (stops when idle since 2026-10-01) | $3.00 (est.) | estimated | usage | Stops when idle; list-price estimate. Invoice not seen. | REDUCE | Estimate. Was always-on (about $15 estimated); now billed only while someone is using it, plus storage. Exact figure: Fly dashboard, billing. Still serves the paid product free (APP_PUBLIC_DEMO=1): turn the demo off once production is selling. |
| Domain linehound.app | $1.00 (est.) | estimated | fixed, prepaid yearly | Amortised guess. Registrar receipt not seen. | KEEP | Amortised estimate. |
| Claude subscription that operates the business | UNKNOWN | unknown | fixed subscription, shared | Owner to supply. Session-assisted briefs run on this subscription and add no API charge. | REDUCE | UNKNOWN. Brey to supply the monthly figure; planned against $200. |
| BALLDONTLIE | UNKNOWN | unknown | unknown | None. No invoice, receipt or billing page seen. Owner to verify. | VERIFY | Billing and cancellation status UNKNOWN until verified on the billing page. The key answering unauthorized since 2026-09-17 does not prove billing stopped, and nothing here establishes the exact charge that could be avoided or refunded. Nothing on the site depends on it. PROPOSED saving only (not confirmed): the plan's list price, about $289 to $299.99 a month, if it is in fact charging. Cancelling is the owner's decision. |
| API-Tennis | $0.00 | actual | none | Trial expired 2026-09-18, not renewed. | CANCEL | Trial expired 2026-09-18, not renewed. |
| GitHub Actions | $0.00 | actual | none | Public repository; no charge. | KEEP | Free only because the repo is public (about 90k runner minutes a month). Do not make the repo private. |
| Stripe | $0.00 | actual | per charge | Published fees; nothing is charged while billing is off. | KEEP | Per charge: about $1.02 on $19.99. |

Contribution per paying subscriber: $18.97 a month ($19.99 less Stripe's fees). No other cost rises with each subscriber: the analysis is written once per game, not once per customer.
- api per game usd: 0.08 to 0.11 at list price (docs/AI_ANALYST.md); not incurred until the key is set
- session assisted per brief: first published brief, 2026-10-04 Padres at Brewers (3 markets, no props): about $0.04 at list price (8,921 input and about 1,900 output tokens), 60 seconds of model time, about 12 minutes of operator time; billed to the shared subscription, no API charge.

## Product errors

- Production memory incident (2026-10-01): the site restarted for lack of memory about every 11 minutes from its first deploy until 21:39Z. Fixed by serialising cache rebuilds, deployed 21:41Z. 60-minute soak passed: 0 restarts, peak 589 MB of 1,024, steady memory 358 MB and flattening. docs/audit/2026-10-01/PRODUCTION_RECOVERY.md.
- Record page: fixed and on staging (5a85b867): every night lists its picks and fills; on a phone the won-lost figure is on the first screen and the result column fits. Production picks it up at the next hourly refresh.
- Capture cadence: fixed 2026-10-01 23:15Z. Slots had dropped to about one an hour because one step re-read the day's raw files once per observation (21 minutes per run, growing all day). Now 65 seconds on a runner, output byte-identical. docs/audit/2026-10-01/CAPTURE_STARVATION.md. Watch that slots keep completing and production's hourly refresh resumes.
- Hourly production refresh gate: it checks that the latest COMPLETED tests run is green, not that the commit being deployed has a green run. A push made late in an hour can reach production before its own tests finish. Proposed fix written in docs/audit/2026-10-01/PRODUCTION_RECOVERY.md; workflow edits are the owner's call. Until then: no code push between minute 45 and minute 15.
- UFC: the seven published picks were graded by hand on 2026-10-01 (5-1, +2.50u, 1 void; docs/audit/2026-10-01/UFC_GRADING.md). Each new event still needs its results typed in afterwards; nothing does that automatically. One pick was published on a bout whose fighter had been replaced two days earlier (graded VOID).
- V2 has published zero MAIN picks since 2026-09-26; every entry since is a fill. The public MAIN record is frozen at 4 dates.
- Shadow ledgers hold one wrong permanent VOID (game 824785, played a day late). Append-only correction pending.
- NFL picks store no model probability or observation time, so NFL calibration and closing-line value cannot be measured.
- Daily loop red on 'settlement gap': cause found (a cancelled game and a rain-out played a day late could never settle). Fix pushed 2026-10-01 (eb850168); confirm on the 2026-10-02 10:10Z run.
- Billing, deferred (review 2026-10-01): a failed renewal keeps access until the new period ends, and a redelivered or out-of-order Stripe event can restore access after a cancellation. Signatures are enforced, so only Stripe can trigger it. Fix before the first renewal date, about 37 days after the first sale. UPDATE: Billing (2026-10-04): past_due, unpaid and incomplete events no longer move the access end forward, and invoice.payment_failed is acknowledged and logged (tests/test_billing_failed_payment.py and its review file). NOT verified against Stripe's real event order: if a renewal announces the new period while still active before the charge, a declined renewal can still keep one extra period, and access would have to move onto invoice.paid. Staging step 13 is NOT RUN; treat the flaw as open.
- Public record, deferred: while a day is only partly graded the headline counts its graded picks but the day list withholds the whole day, so the two cannot be reconciled until it resolves.
- Sign-in, deferred: a link carrying a token signs the reader into that token's account; a crafted link could sign someone into an account that is not theirs.
- Lost access token: no email sender exists, so recovery is by support only (admin re-issue route being added 2026-10-01).

## Other blockers

- Claude monthly cost unknown, so break-even is an estimate. Owner.
- Thin content: MLB has had no counted pick since 2026-09-26 (fills only, 2 to 4 postseason games a day); NFL has published 11 picks on 4 dates, 1 since 2026-09-21; UFC is ungraded. After the World Series (about Nov 1) only NFL remains. Gates are not being loosened to fill the card; what is sold is the nightly card with labelled fills, the price view and the public record.

## Today's execution

- First brief published and live for customers: Padres at Brewers. Version 1 (15:19Z) passed on all three markets; version 2 (16:54Z, both lineups posted) takes Brewers moneyline at -128 and passes on the run line and total (https://linehound.app/web/sample.html). Session-assisted, not unattended.
- Internal data API: MLB joins UFC and NFL behind one client; the brief's prepare command reads through it; fifty repeated reads make no upstream request
- Collection: measured against MLB's feed, a current store refreshes in 5 requests (was 19) and a cold one in 618 (was 632). The daily loop now saves the refreshed stats, so builds should stop refetching the whole gap; the per-day saving (about 36,000 to about 600 requests) is modelled, not yet observed on a runner
- Billing: access follows verified payment whatever the event order (two adversarial reviews, defects fixed). Still open: the real Stripe test-mode rehearsal (NOT RUN) and two owner decisions (repeat free trials, legacy rows)
- Checker: declared calculations are recomputed and kept with their source; undeclared numbers are still rejected
- Research: starter-aware total bases (small), pitcher strikeout baseline (clear against a weak baseline); no live change
- Five invitations ready, linking to the live sample; none sent
- Outreach batch 1: 20 paste-ready messages (docs/sales/batch_01.md)
- Production recovery: stuck deploy cancelled, reviewed release deployed, 60-minute soak passed
- Admin page shows signups by outreach source; link previews for the landing page and the record link
- Capture slowdown found and fixed: engine slate 21 minutes -> 65 seconds on a runner
- Staging billing confirmed in test mode (from /health, no key shown); rehearsal purchase steps in GO_LIVE section 5
- UFC: seven published picks graded from two independent sources each

