# LineHound survival dashboard

Generated 2026-10-02 02:56Z by `scripts/survival_dashboard.py`. Edit `config/business.json` and log outreach with `scripts/outreach_batch.py`, not this file.

| | |
|---|---|
| Days until 2026-10-31 | **29** |
| Current monthly burn (known + estimated infrastructure) | $78.00 |
| Current monthly burn incl. Claude at the planning assumption | $278.00 (unknown: Claude subscription that operates the business, BALLDONTLIE) |
| Identified monthly savings (not yet realised) | $29.00: The Odds API (100K tier): $29.00 (downgrade to the $30 20K tier from November; NOT confirmed, owner decision) |
| Revenue (payments logged in the queue) | none logged (no `paid` lead in the queue) |
| MRR (config, manual: manual until /admin/revenue is read from production) | $0.00 |
| Unique leads | 40 |
| Messages sent | 0 |
| Replies | 0 |
| Signups | 0 |
| Active users | 0 |
| People who said they would pay | 0 |
| Paid customers | 0 |
| Conversion rate (paid / leads sent) | n/a (no lead has been sent a message yet) |
| CAC | $0 spent on acquisition |
| Gap to break-even | $278.00 per month |

## Milestones (first timestamp of each, UTC)

- First message sent: not yet
- First real reply (not auto): not yet
- First interested reply: not yet
- First signup: not yet
- First active user: not yet
- First would-pay: not yet
- First payment: not yet

## Current sports

- MLB postseason (card, hits and total-bases props)
- NFL (value lines)
- UFC (published; graded by hand)

## Performance by market (counted picks; never pooled) and CLV

- **MLB current** (Our value card; 2026-09-22..2026-09-27): 16-17, -5.05u, ROI -15.3% (n=33)
  - game: 2-1, +0.69u, ROI +23.2% (n=3)
  - prop: 14-16, -5.74u, ROI -19.1% (n=30)
  - fills (shown apart, never counted): 21-8, +7.68u, ROI +26.5% (n=29)
- **MLB previous** (Our first card rule; 2026-09-10..2026-09-22): 151-79, +7.98u, ROI +3.5% (n=230)
  - game: 73-40, +7.61u, ROI +6.7% (n=113)
  - prop: 78-39, +0.38u, ROI +0.3% (n=117)
- **NFL current** (Our NFL value rule; 2026-09-27..2026-09-27): 1-0, +0.93u, ROI +92.6% (n=1)
  - game: 1-0, +0.93u, ROI +92.6% (n=1)
- **NFL previous** (Our first NFL rule; 2026-09-17..2026-09-21): 7-3, -0.26u, ROI -2.6% (n=10)
  - game: 7-3, -0.26u, ROI -2.6% (n=10)
- **MMA current** (Our UFC card; 2026-09-22..2026-09-26): 5-1, +2.50u, ROI +41.7% (n=6)
  - game: 5-1, +2.50u, ROI +41.7% (n=6)

Closing-line value: see `docs/VALUE_SCAN.md` (the standing measurement; no CLV figure is computed or copied here). No rule here has evidence of an edge.

- V2 MAIN picks 16-17, -5.05u; 19 of the 33 are one day (2026-09-22, cap breach, -5.14u).
- Everything shown to readers under V2 (picks plus fills): 41-27, +3.46u.
- Closing-line value is negative in every segment measured (V1 games -1.21 pts, n=51; props about -3.5).
- Our number scored worse than the market's in 12 of 16 populations and never significantly better.

## Production health and capture cost

- Production health: see docs/audit
- Capture cost: see docs/audit

## Top 3 blockers

1. linehound.app does not load: the domain is on Cloudflare with no A, AAAA or CNAME record and Fly holds no certificate for it. Outreach links use linehound-prod.fly.dev until it does. Checkout cannot be switched on before it does, because buyers are returned to that domain. Steps: docs/GO_LIVE_2026-09-28.md section 1. Owner.
2. Signups are invisible: production has no admin token, so nobody can read who signed up or from which outreach link. One command, no Stripe needed, before batch 1 is sent: docs/GO_LIVE_2026-09-28.md section 0. Owner.
3. No distribution: zero outreach sent. The first 20 are written and ready to paste in docs/sales/batch_01.md; log each send with `python scripts/outreach_batch.py sent --batch 1 --items ...`. Owner.

## Next actions

- **Owner:** not set
- **Customer:** Brey: first set the admin token (GO_LIVE section 0) so signups are visible, then send batch 1 (docs/sales/batch_01.md). Start with items 1 and 2 (two forums where promotion is allowed), then the four creators and five X replies; at most five Discord notes a day. Log each with scripts/outreach_batch.py. Batch 2 (docs/sales/batch_02.md, 20 more, nobody repeated from batch 1) is ready for when batch 1 is out.
- **Product:** not set
- **Model:** docs/VALUE_SCAN.md is now the standing measurement (python scripts/value_scan.py): 43 populations, 0 candidates, 6 with enough data and no evidence, 37 too few. The one hypothesis worth a pre-registered forward test is whether V2's value gate selects the worse entries (z -1.43 in shadow A). No gate or threshold changes until that test reports.

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

- Stripe is not live: account verification pending (date of birth, phone), then the five Fly secrets. Owner.
- Discord feed not wired: needs the webhook secret and one env line on the default branch. Owner + me.
- Claude monthly cost unknown, so break-even is an estimate. Owner.
- Thin content: MLB has had no counted pick since 2026-09-26 (fills only, 2 to 4 postseason games a day); NFL has published 11 picks on 4 dates, 1 since 2026-09-21; UFC is ungraded. After the World Series (about Nov 1) only NFL remains. Gates are not being loosened to fill the card; what is sold is the nightly card with labelled fills, the price view and the public record.

## Today's execution

- Public record, access delivery, cancel link, attribution (buying-path worker)
- Free public postseason odds page (lead magnet)
- Loss diagnosis: done, filed in docs/audit/2026-10-01/
- Independent attack on the buying path: 1 blocker and 9 other findings; blocker fixed, rest fixed or listed above
- Independent check of the postseason page: bracket and sums correct; 10 defects being fixed before it ships
- Outreach batch 1: 20 paste-ready messages (docs/sales/batch_01.md)
- Production recovery: stuck deploy cancelled, reviewed release deployed, 60-minute soak passed
- Admin page shows signups by outreach source; link previews for the landing page and the record link
- Capture slowdown found and fixed: engine slate 21 minutes -> 65 seconds on a runner
- Staging billing confirmed in test mode (from /health, no key shown); rehearsal purchase steps in GO_LIVE section 5
- UFC: seven published picks graded from two independent sources each

