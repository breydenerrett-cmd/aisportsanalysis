# DEMO HANDOFF — hosted demo, 2026-09-07

Written by the local Parent at the end of the 3–4 hour ship sprint
(directive 2026-09-07 ~00:20Z). Running detail is in
`docs/DEMO_SHIP_CHECKLIST.md`; this page is what Brey needs in hand.

## LIVE URL

https://linehound-staging.fly.dev/app

Opens straight into the product (no invite token: the staging config sets
`APP_PUBLIC_DEMO=1`; remove that one line in `deploy/fly.staging.toml` to
put the token wall back).

## WHAT WORKS

_(filled in at the end of the sprint — see the ledger in
`docs/DEMO_SHIP_CHECKLIST.md` for the verified state as of each push)_

## TOP 3 THINGS TO CLICK

1. TODAY → the slate date, the board summary and TOP OPPORTUNITIES.
2. A game card → GAME view: starters, NO PLAY / price panel, MODEL vs MARKET.
3. CHECK → type a price for a side (try ATH +189 and PHI −175 on 2026-09-07)
   and read the PRICE VERDICT block.

## WHAT IS LIVE vs DEMO/REPLAY

- LIVE: the MLB schedule (fetched per request), the odds board
  (`data/processed/odds_multibook.jsonl`, baked into the image on every
  deploy; GitHub's forward-capture cron now fires every 15 minutes and
  redeploys staging on the first slot of each hour), the engine's frozen
  decisions for the slate date, the paper-account ledgers.
- NOT LIVE: the odds board is as fresh as the last deploy (at most ~1 hour
  behind during game hours); every board carries its capture time and the
  stale label past 30 minutes.
- NO REPLAY MODE was built: the 2026-09-07 slate exists, so nothing is
  staged. Nothing on screen is invented.

## KNOWN LIMITATIONS

_(filled in at the end)_

## NEXT 3 IMPROVEMENTS

_(filled in at the end)_
