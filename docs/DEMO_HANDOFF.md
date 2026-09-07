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

- The board is only as fresh as the last deploy. GitHub's `*/15` cron is
  best-effort (it fired at 01:00Z, skipped 01:15Z and 01:30Z); a watchdog in
  the local session dispatches a capture when the newest run is over 45
  minutes old. Every price shows its capture time; past 30 minutes the UI
  says LAST UPDATED instead of LIVE.
- Moneyline only on the odds board and in Bet Check. Spreads, totals and
  first-five prices are captured into the store but not exposed on these
  screens yet.
- On 2026-09-07 four games had no usable board at capture time (AZ@KC,
  MIN@DET, WSH@SD not quoted; LAA@BOS only 5 books, below the 6-book
  consensus floor). They are listed as UNPRICED with the reason, never
  scored.
- No independent model probability exists. Every "model" reading is the
  market-derived reference; every verdict is price versus the de-vigged
  consensus (line-shopping value). A vigged board normally shows FAIR PRICE
  and PASS; STRONG VALUE / VALUE will be rare and that is correct.
- Engine decisions on the slate come from CONTROL and MARKET REFERENCE
  systems (null baselines and calibration references); no forward-test
  system staked a 2026-09-07 game. Performance therefore has real
  forward-test history (64 settled bets) but no forward-test picks tonight.
- The BET WON vs REASONING CORRECT split is all UNTESTED: control and
  market-reference systems make no checkable mechanism claim, and the
  forward-test systems' mechanism checks are recent. 70 legacy reviews
  cannot be joined (pre-2026-09-03 key format).
- Paper settlement runs at 10:00Z; 2026-09-06 and 2026-09-07 wagers show
  PENDING until then. The daily-loop cron is also best-effort.
- Saved bets (BETS) still require an invite token; it is hidden in demo mode.
- Demo mode makes the read-only game surface public on the staging URL.
  One env line reverses it.

## NEXT 3 IMPROVEMENTS

1. A scheduler that is not GitHub's cron: a small external pinger (or the
   cloud routine) that dispatches `forward-capture` every 15 minutes and
   `daily-loop` at 10:00Z, so freshness never depends on a session.
2. Expose spreads, totals and first-five on the odds board and Bet Check
   (the store already has them; `oddspayload.MARKETS` and a builder each).
3. Ship the forward-test systems' decisions onto the slate as tagged
   FORWARD TEST · UNPROVEN interest, and settle 09-06/09-07 so Performance
   shows this week's picks resolved.
