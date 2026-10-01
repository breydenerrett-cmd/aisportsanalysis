# LineHound survival dashboard

Generated 2026-10-01 19:28Z by `scripts/survival_dashboard.py`. Edit `config/business.json` and `docs/sales/pipeline.csv`, not this file.

| | |
|---|---|
| Days until 2026-10-31 | **30** |
| Monthly cost (known + estimated infrastructure) | $78.00 |
| Monthly cost incl. Claude at the planning assumption | $278.00 (unknown: Claude subscription that operates the business, BALLDONTLIE) |
| Revenue (MRR) | $0.00 |
| Paying customers | 0 |
| Trials | 0 |
| Leads contacted | 0 (replied 0, demo 0, lost 0) |
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

- Production shows only what was in the repository when it was last deployed: tonight's card, odds and results do not reach linehound.app until someone runs deploy-prod again. Staging refreshes on every push; production is manual by design. A paying customer would see a stale card the next day. Needs an owner decision on an automatic production refresh.
- Stripe is not live: account verification pending (date of birth, phone), then the five Fly secrets. Owner.
- No distribution: zero outreach sent. Target list and scripts in docs/sales/.
- Discord feed not wired: needs the webhook secret and one env line on the default branch. Owner + me.
- Claude monthly cost unknown, so break-even is an estimate. Owner.
- Thin content: MLB has had no counted pick since 2026-09-26 (fills only, 2 to 4 postseason games a day); NFL has published 11 picks on 4 dates, 1 since 2026-09-21; UFC is ungraded. After the World Series (about Nov 1) only NFL remains. Gates are not being loosened to fill the card; what is sold is the nightly card with labelled fills, the price view and the public record.

## Today's execution

- Public record, access delivery, cancel link, attribution (buying-path worker)
- Free public postseason odds page (lead magnet)
- Outreach targets, channel rules and scripts
- Loss diagnosis: done, filed in docs/audit/2026-10-01/
- Independent attack on the buying path: 1 blocker and 9 other findings; blocker fixed, rest fixed or listed above
- Independent check of the postseason page: bracket and sums correct; 10 defects being fixed before it ships

**Next customer action:** Brey: finish Stripe verification, then send the first 20 messages from docs/sales/targets.csv using docs/sales/scripts.md.

**Next research action:** No rule has shown positive expected value (docs/audit/2026-10-01/LOSS_DIAGNOSIS.md). Pre-register one forward test: do entries that pass V2's value gate do worse than entries that fail it? No gate or threshold changes until that test reports.

