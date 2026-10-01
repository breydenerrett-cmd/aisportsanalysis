# LineHound survival dashboard

Generated 2026-10-01 22:55Z by `scripts/survival_dashboard.py`. Edit `config/business.json` and `docs/sales/pipeline.csv`, not this file.

| | |
|---|---|
| Days until 2026-10-31 | **30** |
| Monthly cost (known + estimated infrastructure) | $78.00 |
| Monthly cost incl. Claude at the planning assumption | $278.00 (unknown: Claude subscription that operates the business, BALLDONTLIE) |
| Revenue (MRR) | $0.00 |
| Paying customers | 0 |
| Trials | 0 |
| Leads contacted | 0 (ever replied 0, ever had a demo 0, lost 0) |
| Lead to paid conversion | n/a (no leads yet) |
| CAC | $0 spent on acquisition |
| Gap to break-even | $278.00 per month |

## What survival requires

- Infrastructure only ($78.00): 5 x Individual, monthly at $19.99
- Infrastructure only ($78.00): 1 x Community feed, per server at $149.00
- Everything incl. Claude ($278.00): 15 x Individual, monthly at $19.99
- Everything incl. Claude ($278.00): 2 x Community feed, per server at $149.00

## Costs and the kill list

| Item | Monthly | Verdict | Note |
|---|---|---|---|
| The Odds API (100K tier) | $59.00 | KEEP | Prices every card. Measured burn before the NFL/MMA re-buy fix: about 550 credits a day (16,500 a month), 80% of it NFL and MMA boards re-bought every slot. Fix pushed 2026-10-01 18:42Z; confirm the drop over the next slots, then the $30 20K tier fits. October is already paid, so a downgrade saves from November. Owner decision. |
| Fly.io production (2 shared CPUs, 1 GB, 1 GB volume) | $15.00 (est.) | KEEP | Estimate. Exact figure: Fly dashboard, billing. |
| Fly.io staging (stops when idle since 2026-10-01) | $3.00 (est.) | REDUCE | Estimate. Was always-on (about $15 estimated); now billed only while someone is using it, plus storage. Exact figure: Fly dashboard, billing. Still serves the paid product free (APP_PUBLIC_DEMO=1): turn the demo off once production is selling. |
| Domain linehound.app | $1.00 (est.) | KEEP | Amortised estimate. |
| Claude subscription that operates the business | UNKNOWN | REDUCE | UNKNOWN. Brey to supply the monthly figure; planned against $200. |
| BALLDONTLIE | UNKNOWN | CANCEL | UNKNOWN. The 48-hour trial ended 2026-09-17; nothing harvested is used by any model. Check the account's billing page that it did not convert to $299.99. |
| API-Tennis | $0.00 | CANCEL | Trial expired 2026-09-18, not renewed. |
| GitHub Actions | $0.00 | KEEP | Free only because the repo is public (about 90k runner minutes a month). Do not make the repo private. |
| Stripe | $0.00 | KEEP | Per charge: about $1.02 on $19.99. |

## Active sports

- MLB postseason (card, hits and total-bases props)
- NFL (value lines)
- UFC (published; graded by hand)

## Public record by sport and market (counted picks; never pooled)

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
- **MMA current** (Our UFC card; no dates): nothing graded

No rule here has evidence of an edge. Closing-line value and calibration: see `docs/audit/` for the latest loss diagnosis.

- V2 MAIN picks 16-17, -5.05u; 19 of the 33 are one day (2026-09-22, cap breach, -5.14u).
- Everything shown to readers under V2 (picks plus fills): 41-27, +3.46u.
- Closing-line value is negative in every segment measured (V1 games -1.21 pts, n=51; props about -3.5).
- Our number scored worse than the market's in 12 of 16 populations and never significantly better.

## Product errors

- Production memory incident (2026-10-01): the site restarted for lack of memory about every 11 minutes from its first deploy until 21:39Z. Fixed by serialising cache rebuilds, deployed 21:41Z. 60-minute soak passed: 0 restarts, peak 589 MB of 1,024, steady memory 358 MB and flattening. docs/audit/2026-10-01/PRODUCTION_RECOVERY.md.
- Record page: fixed locally 2026-10-01, not yet in production. Every night now lists its picks and fills; on a phone the won-lost figure is on the first screen (was 1,884px down) and the result column fits. Pushed after 23:15Z; production picks it up at the next hourly refresh.
- Capture cadence: forward-capture slots have completed about 1.5 times an hour since 19:06Z against about 4.5 before. The afternoon-slate job takes about 20 minutes of every 30 and shares the capture job's lock, and a newer waiting slot cancels the older one. Odds on the site and the NFL card's board go stale in between. Not yet diagnosed further.
- Hourly production refresh gate: it checks that the latest COMPLETED tests run is green, not that the commit being deployed has a green run. A push made late in an hour can reach production before its own tests finish. Proposed fix written in docs/audit/2026-10-01/PRODUCTION_RECOVERY.md; workflow edits are the owner's call. Until then: no code push between minute 45 and minute 15.
- UFC picks never graded (results are entered by hand).
- V2 has published zero MAIN picks since 2026-09-26; every entry since is a fill. The public MAIN record is frozen at 4 dates.
- Shadow ledgers hold one wrong permanent VOID (game 824785, played a day late). Append-only correction pending.
- NFL picks store no model probability or observation time, so NFL calibration and closing-line value cannot be measured.
- Daily loop red on 'settlement gap': cause found (a cancelled game and a rain-out played a day late could never settle). Fix pushed 2026-10-01 (eb850168); confirm on the 2026-10-02 10:10Z run.
- Billing, deferred (review 2026-10-01): a failed renewal keeps access until the new period ends, and a redelivered or out-of-order Stripe event can restore access after a cancellation. Signatures are enforced, so only Stripe can trigger it. Fix before the first renewal date, about 37 days after the first sale.
- Public record, deferred: while a day is only partly graded the headline counts its graded picks but the day list withholds the whole day, so the two cannot be reconciled until it resolves.
- Sign-in, deferred: a link carrying a token signs the reader into that token's account; a crafted link could sign someone into an account that is not theirs.
- Lost access token: no email sender exists, so recovery is by support only (admin re-issue route being added 2026-10-01).

## Top blockers

- linehound.app does not load: the domain is on Cloudflare with no A, AAAA or CNAME record and Fly holds no certificate for it. Outreach links use linehound-prod.fly.dev until it does. Checkout cannot be switched on before it does, because buyers are returned to that domain. Steps: docs/GO_LIVE_2026-09-28.md section 1. Owner.
- Signups are invisible: production has no admin token, so nobody can read who signed up or from which outreach link. One command, no Stripe needed, before batch 1 is sent: docs/GO_LIVE_2026-09-28.md section 0. Owner.
- No distribution: zero outreach sent. The first 20 are written and ready to paste in docs/sales/batch_01.md; log each send with `python scripts/outreach_batch.py sent --batch 1 --items ...`. Owner.
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

**Next customer action:** Brey: send batch 1 (docs/sales/batch_01.md). Start with items 1 and 2 (two forums where promotion is allowed), then the four creators and five X replies; at most five Discord notes a day. Log each with scripts/outreach_batch.py.

**Next research action:** docs/VALUE_SCAN.md is now the standing measurement (python scripts/value_scan.py): 43 populations, 0 candidates, 6 with enough data and no evidence, 37 too few. The one hypothesis worth a pre-registered forward test is whether V2's value gate selects the worse entries (z -1.43 in shadow A). No gate or threshold changes until that test reports.

