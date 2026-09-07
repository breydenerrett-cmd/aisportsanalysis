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
- GAMES / GAME: schedule, probable starters, the NO PLAY / price panel,
  and the new MODEL vs MARKET panel (both sides' verdicts and meters, the
  market-derived reference with engine provenance, ENGINE DECISIONS with
  counts, staked plays and fatal counterarguments as warnings).
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
  screens yet. The engine does freeze run-line and totals positions, and
  those DO show on the matchup cards and in the daily record.
- **The game screen cannot tell the matchup story yet** (finding F-2). It
  shows the park, the board and the price read, but team records, bullpen,
  splits, handedness and lineups all come back as gaps, because the API
  never assembles those inputs and the container ships without the
  historical feature stores they need. Starter names are fine — they ride on
  the schedule. Fixing it means publishing the rebuilt stores the way the
  Statcast pitch store is already published, then threading them through;
  that is a repo-size decision for you, written up in the checklist.
- On 2026-09-07 four games had no usable board at capture time (AZ@KC,
  MIN@DET, WSH@SD not quoted; LAA@BOS only 5 books, below the 6-book
  consensus floor). They are listed as UNPRICED with the reason, never
  scored.
- No independent model probability exists. Every "model" reading is the
  market-derived reference; every verdict is price versus the de-vigged
  consensus (line-shopping value). A vigged board normally shows FAIR PRICE
  and PASS; STRONG VALUE / VALUE will be rare and that is correct.
- **The forward-test systems have not frozen a decision since 2026-09-03,
  and now we know why.** All sixteen require a posted lineup before they will
  play. The daily slate freezes at 10:00Z, deliberately hours before first
  pitch — but on 09-05 every one of the fifteen games posted its lineup
  between 17:16Z and 22:39Z, seven to twelve hours later. So they refuse
  "no lineup" on every game, every day, and until tonight they did it
  silently. Proven by experiment, written up in
  `docs/FINDING_F1_DIAGNOSIS.md`. Consequence: every engine decision on the
  current slate is a null baseline or a market reference, neither of which is
  a pick to follow, so the honest answer to "what does the system like today"
  is "nothing with a thesis" — and the product says exactly that rather than
  dressing a baseline up as a recommendation. Their real history still shows
  on RESULTS (64 settled bets, +19.18 units) because it is frozen and settled.
  **This one needs your call** — see the three options in
  `docs/DEMO_SHIP_CHECKLIST.md` under "DECISION FOR BREY". The silent half is
  already fixed: the next slate run logs why each system stood down.
- The BET WON vs REASONING CORRECT split is all UNTESTED: control and
  market-reference systems make no checkable mechanism claim, and the
  forward-test systems' mechanism checks are recent. 70 legacy reviews
  cannot be joined (pre-2026-09-03 key format).
- Paper settlement runs at 10:00Z; 2026-09-06 and 2026-09-07 wagers show
  PENDING until then. The daily-loop cron is also best-effort.
- Saved bets (BETS) still require an invite token; it is hidden in demo mode.
- Demo mode makes the read-only game surface public on the staging URL.
  One env line reverses it.

## WHAT HAPPENS WHILE YOU SLEEP

Two scheduled GitHub jobs keep the site alive with no session running:

- **forward-capture** every 15 minutes: pulls the board, commits it, and on
  the first slot of each hour redeploys staging so the site's prices move.
  Two things to know before you read a stale board as a failure:
  - The odds pass only buys prices when a game starts within three hours
    (`WINDOW_MINUTES` in the dense capture). Overnight, with the next first
    pitch at 1:05pm ET, it correctly captures nothing — the 02:46Z run
    logged "0 capture(s), 0 observations". Prices start moving again about
    three hours before the first game, so a morning visit may show a board
    ten hours old, correctly labelled, and then watch it refresh.
  - GitHub's cron is best-effort and skipped most slots tonight (it fired
    once at 01:00Z; the rest were manual dispatches). If nothing has run for
    hours once games are close, one click on Actions → forward-capture →
    Run workflow fixes it.
- **daily-loop** at 10:00Z: settles the previous day, freezes the new slate,
  and writes the end-of-day review. This has never yet completed on a
  schedule (the one dispatched run failed by design, mid-evening, because
  games were still in progress). If it runs, RESULTS gains 2026-09-06 and
  2026-09-07 settled and the slate rolls to 2026-09-08. If it does not,
  those days stay PENDING and the site still works, just frozen at
  "settled through 2026-09-05".

Neither job needs anything from you unless both stay red. A watchdog in the
overnight session will dispatch the daily loop at 10:27Z if — and only if —
the cron produced no run for that date; it never dispatches over an existing
run, because a second one would write a duplicate set of frozen decisions.
That watchdog lives only as long as the session, so treat it as a bonus, not
a guarantee.

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
