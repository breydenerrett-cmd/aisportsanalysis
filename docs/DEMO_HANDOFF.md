# DEMO HANDOFF — hosted demo, 2026-09-07

Written by the local Parent at the end of the 3–4 hour ship sprint
(directive 2026-09-07 ~00:20Z). Running detail is in
`docs/DEMO_SHIP_CHECKLIST.md`; this page is what Brey needs in hand.

## LIVE URL

https://linehound-staging.fly.dev/app

Opens straight into the product (no invite token: the staging config sets
`APP_PUBLIC_DEMO=1`; remove that one line in `deploy/fly.staging.toml` to
put the token wall back).

## WHAT THE SITE IS NOW

A record of what the analyzer decided before each game and what happened
after — not just a board of prices. Three questions, answered on the screen:
what does it like, why, and how has it actually done.

- **TODAY** opens with the record strip (today, last 7 days, last 30 days of
  paper results), then the honest slate verdict, then TOP OPPORTUNITIES,
  then a card for **every matchup**: teams, first pitch, venue, probable
  starters, the moneyline with book count and capture age, the LIVE PRICE
  READ (the price-versus-consensus verdict the product actually stands
  behind), and PAPER POSITIONS FROZEN BEFORE FIRST PITCH. Once a game is
  final the card carries the score and the game's own W-L-P.
- **RESULTS** opens with the same strip, then the DAILY RECAP gallery — one
  card per slate, newest first, with the day's record, units, best and worst
  settled position and its strongest pregame pick — then the full paper
  standings by system class, the reasoning split and the cumulative-units
  chart.
- **#/day/<date>** is the audit trail: the whole frozen slate for that day,
  every position with the price and book count as recorded, and what it
  settled to. Nothing there is restated after the fact.

## WHAT WORKS (verified in the browser on staging, desktop and 375px)

- TODAY: the slate date badge (TONIGHT'S SLATE / NEXT SLATE), the honest
  hero, WHAT WE CHECKED TONIGHT, then TOP OPPORTUNITIES: qualifying cards
  (word chip, value points, market-implied vs price-implied probability
  meter, NO INDEPENDENT MODEL YET, evidence tier, reasons, risks, capture
  age) or the exact text NO QUALIFYING BEST BETS RIGHT NOW, always followed
  by the ranked table of every priced side and the unpriced games with
  reasons. Then the Featured Bet and the slate rail.
- GAMES / GAME: schedule, records with sample n, both probables, the NO
  PLAY / price panel, the GAME STORY block (starters with ERA/FIP/WHIP/K-9
  and recent form, bullpen usage with per-reliever availability, lineups
  with handedness, travel, conditions at first pitch), the MODEL vs MARKET
  panel (both sides' verdicts and meters, the market-derived reference
  with engine provenance), and ENGINE DECISIONS with counts, staked plays
  and the systems' stand-down reasons said in words rather than as the
  expression that decided them.
- LANDING (`/`): the hero shows tonight's real featured matchup, game
  count and best price, fetched live; on a feed failure it falls back to
  a sample that is labelled as one and never captioned "Tonight".
- CHECK (Bet Check): the ten-block check plus the PRICE VERDICT block
  (STRONG VALUE … INSUFFICIENT DATA, fair price, your price, the meter,
  evidence tier, books, capture age, reasons, risks). Prefilled from a
  card's CHECK THIS PRICE link. Uses the open route in demo mode (no
  three-check cap).
- ODDS: the moneyline board, best price, de-vigged consensus, book count,
  capture time and stale flag (unchanged, now actually priced again after
  the board regression fix).
- RESULTS (PAPER / RESEARCH PERFORMANCE): disclaimer, settled-through and
  pending counts, summary tiles (forward-test systems and all systems),
  per-class tables with one-line explanations, recent picks with
  W/L/P/PENDING, BET WON vs REASONING CORRECT, cumulative-units sparkline.
  Numbers reconcile exactly with the paper-account ledgers and the latest
  scorecards (adversarially verified).
- Freshness: every board shows its capture time and age; the shell strip
  says LIVE within 15 minutes and LAST UPDATED after; verdicts drop to the
  LOW tier past 2 hours and INSUFFICIENT DATA when there is no consensus.
- The verdict rule and every honesty invariant are documented in
  `docs/DEMO_SHIP_CHECKLIST.md` and pinned by tests (265 Bet Check /
  contract / language tests, 36 opportunities/bridge tests, 33 performance
  tests, 130 web tests, all green in CI on every push tonight).

## TOP 3 THINGS TO CLICK

1. **TODAY** — the record strip at the top, then scroll to the matchup grid.
   Open any card's "PAPER POSITIONS FROZEN BEFORE FIRST PITCH".
2. **RESULTS** — the DAILY RECAP gallery, then "OPEN THE FULL RECORD" on
   Saturday Sep 5. That page is the audit trail: every position with the
   price and book count as frozen, and what it settled to.
3. **CHECK** — type a game, a side and a price, and read the PRICE VERDICT
   block. Try the Athletics at +189 and Philadelphia at −175 on 2026-09-07
   for a LEAN and an OVERPRICED.

## WHAT IS LIVE vs DEMO/REPLAY

- LIVE: the MLB schedule (fetched per request), the odds board
  (`data/processed/odds_multibook.jsonl`, baked into the image on every
  deploy), the engine's frozen decisions for the slate date, the
  paper-account ledgers, and since 2026-09-07 the per-game feature stores
  (records, starter form, bullpen, lineups, travel, weather) restored from
  the daily-loop cache at build time. The clock is the local Scheduled
  Task `linehound-capture-tick` on Brey's PC, not GitHub's cron: measured
  2026-09-07, the cron fired 6 of ~97 scheduled runs. The task dispatches
  a capture when the board is 40+ minutes stale, and forward-capture
  redeploys staging on the first slot of each hour.
- NOT LIVE: the odds board is as fresh as the last deploy (at most ~1 hour
  behind during game hours); every board carries its capture time and the
  stale label past 30 minutes.
- NO REPLAY MODE was built: the 2026-09-07 slate exists, so nothing is
  staged. Nothing on screen is invented.

## KNOWN LIMITATIONS

- The board is only as fresh as the last deploy, and the clock is a local
  Scheduled Task rather than GitHub's cron (which fired ~6% of the time on
  2026-09-07). The task runs every 15 minutes while the PC is awake; if
  the machine sleeps, captures stop until it wakes. Every price shows its
  capture time; past 30 minutes the UI says LAST UPDATED instead of LIVE.
  Details and the unregister command: `docs/LOCAL_SCHEDULER.md`.
- Every captured market is now ranked on Today under EVERY OTHER MARKET
  ON THE BOARD -- first-five totals and moneylines, team totals, alternate
  lines and pitcher strikeout props -- on the same price-versus-consensus
  measure as the moneyline, with the same six-book floor. Most of those
  contracts are too thinly quoted to price on a given night (a THIN BOARD
  block says how many, per market, and why); the Odds board and Bet Check
  themselves are still moneyline-only. The engine's run-line and totals
  positions show on the matchup cards and in the daily record.
- **The game screen tells the matchup story now** (F-2, shipped
  2026-09-07). Records with sample n, both starters' season and recent
  form, bullpen usage and per-reliever availability over 7 days, posted
  lineups with handedness, travel load and the forecast at first pitch,
  as a GAME STORY block on every game. Still honestly absent and named
  as gaps on the page: pitcher platoon splits and batter-vs-pitcher
  history (each ~200 live MLB calls per slate -- they need a store, not
  a fetch), pitch arsenals (the 40 MB Statcast store stays out of the
  image), and roster news. Tonight's lineups can lag on staging until
  the next daily loop refreshes the cache; the page says so per game.
- On 2026-09-07 four games had no usable board at capture time (AZ@KC,
  MIN@DET, WSH@SD not quoted; LAA@BOS only 5 books, below the 6-book
  consensus floor). They are listed as UNPRICED with the reason, never
  scored.
- No independent model probability exists. Every "model" reading is the
  market-derived reference; every verdict is price versus the de-vigged
  consensus (line-shopping value). A vigged board normally shows FAIR PRICE
  and PASS; STRONG VALUE / VALUE will be rare and that is correct.
- **The forward-test systems decided on a live slate for the first time
  tonight (2026-09-07 23:13Z).** The diagnosis held: all sixteen require a
  posted lineup, and the 10:00Z freeze runs hours before lineups post
  (`docs/FINDING_F1_DIAGNOSIS.md`). The fix is the registered
  `afternoon-slate` workflow, a second pass at 21:10Z. Its first live run
  recorded `FORWARD_TEST: 6` alongside 45 reasoned stand-downs (NO_LINEUP
  16, NO_SIGNAL 19, BELOW_ENTRY 2, MARKET_UNAVAILABLE 8) -- the same
  systems playing where they had a signal and saying no where they did
  not. Each play is recorded with `p_model=None` and
  `value_basis=price_standing_only`: it played on price standing and the
  ledger says so. Caveat: the 21:10Z cron did not fire; the run was a
  manual dispatch, and the local task now covers that slot. Those six show
  on their matchup pages under ENGINE DECISIONS and in the frozen
  positions; they settle at the next daily loop. The systems' earlier
  history still shows on RESULTS (64 settled bets, +19.18 units) because
  it is frozen and settled.
- The BET WON vs REASONING CORRECT split is all UNTESTED: control and
  market-reference systems make no checkable mechanism claim, and the
  forward-test systems' mechanism checks are recent. 70 legacy reviews
  cannot be joined (pre-2026-09-03 key format).
- Paper settlement runs in the daily loop. 2026-09-06 is settled (47-40-3,
  +1.50u); 2026-09-07's positions, including tonight's six FORWARD_TEST
  plays, show PENDING until the next loop. The loop's own push does not
  trigger a staging deploy, so RESULTS can lag a settlement by up to an
  hour until forward-capture's hourly redeploy carries it.
- Saved bets (BETS) still require an invite token; it is hidden in demo mode.
- Demo mode makes the read-only game surface public on the staging URL.
  One env line reverses it.

## WHAT HAPPENS WHILE YOU SLEEP

Three GitHub workflows do the work, and a Scheduled Task on this PC is the
clock. Nothing here depends on a Claude session being alive.

- **forward-capture** (`*/15` cron, plus the task): pulls the board,
  commits it, and on the first slot of each hour redeploys staging so the
  site's prices move. The odds pass only buys prices when a game starts
  within three hours (`WINDOW_MINUTES`), so overnight it correctly
  captures nothing and a morning visit may show a board ten hours old,
  correctly labelled, until about three hours before the first game.
- **daily-loop** (10:00Z cron, plus the task): settles the previous day,
  freezes the new slate, writes the end-of-day review. It completed twice
  on 2026-09-07 -- once by hand at 13:27Z, once by cron at 15:20Z -- and
  the second wrote nothing ("settled 0 new (15 already settled)"), which
  proved the loop is idempotent per date. Its push does not trigger a
  deploy; forward-capture's hourly redeploy carries the settlement.
- **afternoon-slate** (21:10Z cron, plus the task): the second slate pass
  so the thesis-carrying systems can decide once lineups have posted.
  Spends no odds credits, never settles, never runs the end-of-day pass.

**The clock.** `linehound-capture-tick` runs `scripts/capture_tick.ps1`
every 15 minutes: capture if nothing is in flight and the board is 40+
minutes stale; daily-loop once per UTC date after 10:00Z; afternoon-slate
once per UTC date after 21:10Z, counting only runs created at or after
21:10Z. Every decision, including "do nothing", is logged to
`data/logs/capture_tick.log`. Measured 2026-09-07: GitHub's own cron fired
6 of ~97 scheduled runs; the task made every other dispatch. It never
stacks a run and never double-dispatches a date.

**What it cannot do:** run while the PC is asleep. If the machine sleeps
overnight, captures stop until it wakes -- the site keeps serving the last
board, correctly labelled. Watch it with
`Get-Content data\logs\capture_tick.log -Tail 20 -Wait`; remove it with
`Unregister-ScheduledTask -TaskName linehound-capture-tick -Confirm:$false`.
Details in `docs/LOCAL_SCHEDULER.md`.

## F-1 IS REGISTERED (2026-09-07)

`afternoon-slate.yml` is now a live workflow on both the working branch and
the default branch, on cron at 21:10Z. It runs `engine slate` only. Proven
on one manual dispatch (run 34086614213):

- it printed the per-class counts —
  `MARKET_REFERENCE: 64, CONTROL: 32`, plus `note: still no FORWARD_TEST
  decisions for this date`;
- it did **not** settle games, did **not** run the end-of-day pass, did
  **not** touch the dense pipeline;
- the odds credit balance was identical before and after (24,789), so it
  spends nothing;
- it committed one line, to `docs/OVERNIGHT_RUN.md`.

**What that run does not prove.** It was dispatched at ~05:00Z, hours
outside any capture window, so preflight refused the board as 3.3h stale
and the genomes never got to decide. That refusal is the guard working, not
a bug. The real test is the first 21:10Z cron run against a live evening
slate: captures buy within three hours of first pitch, so an evening game
has a fresh board at 21:10Z while a 1:05pm ET game does not. Read the next
run's log for a non-zero `FORWARD_TEST` count. If it is still zero, the
per-game refusal reason is printed directly above it.

## NEXT 3 IMPROVEMENTS

1. ~~**Confirm F-1 on a live cron run.**~~ **PROVEN 2026-09-07 23:13Z --
   with one caveat.** Run 34169306905 recorded `FORWARD_TEST: 6`: the
   first thesis-carrying systems to decide on a live slate, alongside 45
   reasoned stand-downs (NO_LINEUP 16, NO_SIGNAL 19, BELOW_ENTRY 2,
   MARKET_UNAVAILABLE 8). Each play is recorded with `p_model=None` and
   `value_basis=price_standing_only` -- it played on price standing and
   the record says so. The caveat: the 21:10Z cron did not fire; this was
   a manual dispatch. `scripts/capture_tick.ps1` now covers the afternoon
   slate (after 21:10Z, once per date, counting only runs created at or
   after 21:10Z), so from tomorrow the local task fires it.
   **What to read tomorrow:** the 21:10Z+ run's per-class line. A non-zero
   FORWARD_TEST from the task, unattended, closes this item for good.
2. ~~**Fix F-2**~~ **SHIPPED 2026-09-07 (commit 4a8c6b1).** The matchup
   page now carries team records with sample n, starter form (ERA, FIP,
   WHIP, K/9, IP per start, days rest, recent vs season), bullpen workload
   over a 7-day window with per-reliever availability, posted lineups with
   handedness and platoon fields, travel load, and the forecast at first
   pitch. `api/games._enrichment_inputs` loads the same stores the CLI
   briefing always did; the deploy workflow restores them from the
   daily-loop cache; the image carries the five small ones (~3 MB). What
   is still honestly absent on a request path: batter-vs-pitcher history
   and pitcher platoon splits (each is ~200 live MLB calls per slate and
   needs a store, not a fetch) and pitch arsenals (the 40 MB Statcast store
   stays out of the image until a route reads it). The page names each of
   those as a gap with its reason.
   **Next in this lane:** build the splits and batter-vs-pitcher stores in
   the daily loop so they can ride the same cache -- that turns two more
   gaps into sections with zero request-path network.
3. ~~A scheduler that is not GitHub's cron~~ **SHIPPED 2026-09-07.** A
   Windows Scheduled Task, `linehound-capture-tick`, runs
   `scripts/capture_tick.ps1` every 15 minutes on Brey's PC: it dispatches
   `forward-capture` only when nothing is in flight and the newest run is
   40+ minutes old, and `daily-loop` once per UTC date after 10:00Z. Every
   decision is logged to `data/logs/capture_tick.log`. Measured the same
   day: GitHub's own cron fired 6 times against a `*/15` schedule that
   should have produced ~96 -- about 6% -- so the task is what actually
   keeps the board fresh. See `docs/LOCAL_SCHEDULER.md`.
   **Known architecture gap, recorded deliberately:** it only runs while
   the PC is awake. If the machine sleeps overnight, captures stop until it
   wakes. The honest next step if that bites is an external scheduler
   (a cloud cron hitting `workflow_dispatch`), not a bigger local one.

## NEXT 5 IMPROVEMENTS (written 2026-09-07 23:30Z, after F-1, F-2 and the scheduler shipped)

Ranked by user value × trust × visible impact ÷ cost.

1. **Put tonight's system plays on Today.** For the first time there are
   FORWARD_TEST decisions on a live slate (six, run 34169306905). They
   surface on each matchup's frozen-positions section and in the game's
   ENGINE DECISIONS, but Today's hero still leads with the detector
   verdict. A "SYSTEM PLAYS TONIGHT" strip -- genome, side, price, grade,
   `price_standing_only` stated plainly -- is the single most visible
   thing the product can now show that it could not show yesterday.
2. **Settle and grade those six tomorrow, visibly.** The daily loop will
   settle them; Results should show them green/red with the genome id
   and units, as the first thesis-carrying settled record. Check the
   10:00Z loop's log and the recap card for 2026-09-07.
3. **Confirm F-1 unattended.** Tomorrow's 21:10Z+ afternoon-slate run
   should come from the local task, not a hand. A non-zero FORWARD_TEST
   count in that run's log closes F-1 for good.
4. **Two more matchup sections from stores, not fetches.** Pitcher
   platoon splits and batter-vs-pitcher history are each ~200 live MLB
   calls per slate today. Build them in the daily loop so they ride the
   same cache; the page already renders whatever arrives and names what
   does not.
5. **The clock still needs the PC awake.** The local task fires ~100% of
   the time the machine is on; GitHub's cron fired ~6% today. If an
   overnight gap ever costs a capture, the fix is an external scheduler
   hitting `workflow_dispatch`, not a bigger local one. Recorded in
   `docs/LOCAL_SCHEDULER.md` as the known architecture gap.
