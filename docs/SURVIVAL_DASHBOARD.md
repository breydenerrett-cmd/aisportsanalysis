# LineHound survival dashboard

Generated 2026-10-03 15:44Z by `scripts/survival_dashboard.py`. Edit `config/business.json` and log outreach with `scripts/outreach_batch.py`, not this file.

| | |
|---|---|
| Days until 2026-10-31 | **28** |
| Current monthly burn (known + estimated infrastructure) | $78.00 |
| Current monthly burn incl. Claude at the planning assumption | $278.00 (unknown: Claude subscription that operates the business, BALLDONTLIE) |
| Identified monthly savings (not yet realised) | $29.00: The Odds API (100K tier): $29.00 (downgrade to the $30 20K tier from November; NOT confirmed, owner decision) |
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
| RETURNING USERS | 0 (not measured yet) | Activated testers who came back on another day; needs `tester_activity` in config. |
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
  - postseason (graded, not counted): n=2: 0-2, -2.00u (too few for a rate)
- **MLB previous** (Our first card rule; 2026-09-10..2026-09-22): n=230: 151-79, +7.98u, ROI +3.5%
  - game: n=113: 73-40, +7.61u, ROI +6.7%
  - prop: n=117: 78-39, +0.38u, ROI +0.3%
- **NFL current** (Our NFL value rule; 2026-09-27..2026-09-27): n=1: 1-0, +0.93u (too few for a rate)
  - game: n=1: 1-0, +0.93u (too few for a rate)
- **NFL previous** (Our first NFL rule; 2026-09-17..2026-09-21): n=10: 7-3, -0.26u (too few for a rate)
  - game: n=10: 7-3, -0.26u (too few for a rate)
- **MMA current** (Our UFC card; 2026-09-22..2026-09-26): n=6: 5-1, +2.50u (too few for a rate)
  - game: n=6: 5-1, +2.50u (too few for a rate)

Closing-line value: see `docs/VALUE_SCAN.md` (the standing measurement; no CLV figure is computed or copied here). No rule here has evidence of an edge.

- V2 MAIN picks 16-17, -5.05u; 19 of the 33 are one day (2026-09-22, cap breach, -5.14u).
- Everything shown to readers under V2 (picks plus fills): 41-27, +3.46u.
- Closing-line value is negative in every segment measured (V1 games -1.21 pts, n=51; props about -3.5).
- Our number scored worse than the market's in 12 of 16 populations and never significantly better.

## Production health and capture cost

- Production health: Run `python scripts/prod_watch.py`. 2026-10-02 05:48Z: production on d66f4816 (deployed 05:46Z), health ok, billing off, CI green. Known noise: 'odds older than 3 h' overnight when no game is coming, and the 2026-10-01 daily-loop failure until the 10:10Z run.
- Capture cost: 10.9 credits an hour after the cadence change against 23.6 before (2026-10-01, one evening, not a representative game day). Metric: credits per useful fresh observation; re-measure after Sunday. docs/audit/2026-10-01/PRODUCTION_RECOVERY.md.

## Top 3 blockers

1. Nobody has been contacted: 40 leads are queued, 0 messages sent. Everything in front of sending is done (domain, tracking, tester access, production current). What remains is the owner's two-minute funnel check with the admin token, then sending batch 1 by hand.
2. Stripe is not live: the account is verified (2026-10-02). Next: rehearse a purchase on staging in test mode (docs/GO_LIVE_2026-09-28.md section 5), then the Stripe secrets on production. Owner.
3. Discord feed not wired: needs the webhook secret and one env line on the default branch. Owner + me.

## Next actions

- **Owner:** 1) Funnel check: open the internal-test link, submit funnel-test@linehound.app, confirm the internal-test row on the admin page (docs/audit/2026-10-02/LAUNCH_CHAIN.md). 2) Send batch 1 (docs/sales/batch_01.md), forums first. 3) Rehearse a purchase on staging with Stripe's test card (GO_LIVE section 5).
- **Customer:** Batch 1 is ready to send by hand (links on linehound.app, tagged per lead). Log each send with scripts/outreach_batch.py; grant tester access from the admin page to anyone who qualifies (docs/offers/EARLY_TESTER_OFFER.md).
- **Product:** Early tester access is live (first 20, 7 days, no card). Next: an expired tester must be able to buy when billing opens (the signup form answers 'invited' today); the record panel shows dashes for a few minutes after each deploy.
- **Model:** No market shows repeatable value (docs/PERFORMANCE_MATRIX.md: 110 measured populations, 0 candidates; moneyline closing-line value negative on 26 of 26 rows). The props question cannot be answered before 2026-10-31: the best-placed family, batter total bases, reaches a minimum sample about five weeks into the 2027 season (docs/PROP_EXPERIMENT_INVENTORY.md, docs/PREREG_PROP_FAMILIES_DRAFT.md, a DRAFT with seven owner decisions). Until then: sell the public record and the price comparison, not an edge. AI critic: adds one catch over a plain rule on 8 cases and is not ready to show customers (docs/AI_CRITIC_BENCHMARK.md).

## What survival requires

- Infrastructure only ($78.00): 5 x Individual, monthly at $19.99
- Infrastructure only ($78.00): 1 x Community feed, per server at $149.00
- Everything incl. Claude ($278.00): 15 x Individual, monthly at $19.99
- Everything incl. Claude ($278.00): 2 x Community feed, per server at $149.00

## Costs and the kill list

| Item | Monthly | Verdict | Note |
|---|---|---|---|
| The Odds API (100K tier) | $59.00 | KEEP | Prices every card. Burn before the NFL/MMA re-buy fix: about 550 credits a day, 80% of it NFL and MMA boards re-bought every slot. After the fix: 6.7 credits an hour measured over 3.6 hours, but capture slots were starved for most of that window, so the saving is NOT confirmed. The 25-minute game-day refresh fired for the first time at 23:20Z. Re-measure after Sunday's games; if it holds, the $30 20K tier fits and saves $29 from November. Owner decision. |
| Fly.io production (2 shared CPUs, 1 GB, 1 GB volume) | $15.00 (est.) | KEEP | Estimate. Exact figure: Fly dashboard, billing. |
| Fly.io staging (stops when idle since 2026-10-01) | $3.00 (est.) | REDUCE | Estimate. Was always-on (about $15 estimated); now billed only while someone is using it, plus storage. Exact figure: Fly dashboard, billing. Still serves the paid product free (APP_PUBLIC_DEMO=1): turn the demo off once production is selling. |
| Domain linehound.app | $1.00 (est.) | KEEP | Amortised estimate. |
| Claude subscription that operates the business | UNKNOWN | REDUCE | UNKNOWN. Brey to supply the monthly figure; planned against $200. |
| BALLDONTLIE | UNKNOWN | CANCEL | UNKNOWN. The 48-hour trial ended 2026-09-17; nothing harvested is used by any model. Check the account's billing page that it did not convert to $299.99. |
| API-Tennis | $0.00 | CANCEL | Trial expired 2026-09-18, not renewed. |
| GitHub Actions | $0.00 | KEEP | Free only because the repo is public (about 90k runner minutes a month). Do not make the repo private. |
| Stripe | $0.00 | KEEP | Per charge: about $1.02 on $19.99. |

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
- Billing, deferred (review 2026-10-01): a failed renewal keeps access until the new period ends, and a redelivered or out-of-order Stripe event can restore access after a cancellation. Signatures are enforced, so only Stripe can trigger it. Fix before the first renewal date, about 37 days after the first sale.
- Public record, deferred: while a day is only partly graded the headline counts its graded picks but the day list withholds the whole day, so the two cannot be reconciled until it resolves.
- Sign-in, deferred: a link carrying a token signs the reader into that token's account; a crafted link could sign someone into an account that is not theirs.
- Lost access token: no email sender exists, so recovery is by support only (admin re-issue route being added 2026-10-01).

## Other blockers

- Claude monthly cost unknown, so break-even is an estimate. Owner.
- Thin content: MLB has had no counted pick since 2026-09-26 (fills only, 2 to 4 postseason games a day); NFL has published 11 picks on 4 dates, 1 since 2026-09-21; UFC is ungraded. After the World Series (about Nov 1) only NFL remains. Gates are not being loosened to fill the card; what is sold is the nightly card with labelled fills, the price view and the public record.

## Today's execution

- Outreach batch 1: 20 paste-ready messages (docs/sales/batch_01.md)
- Production recovery: stuck deploy cancelled, reviewed release deployed, 60-minute soak passed
- Admin page shows signups by outreach source; link previews for the landing page and the record link
- Capture slowdown found and fixed: engine slate 21 minutes -> 65 seconds on a runner
- Staging billing confirmed in test mode (from /health, no key shown); rehearsal purchase steps in GO_LIVE section 5
- UFC: seven published picks graded from two independent sources each
- Source tracking for outreach links; one outreach queue (40 leads) feeding this dashboard
- Performance matrix, prop-experiment inventory and draft, AI critic benchmark run 1
- Landing page: product-first first screen; production watch script; UFC auto-grading built (inactive)

