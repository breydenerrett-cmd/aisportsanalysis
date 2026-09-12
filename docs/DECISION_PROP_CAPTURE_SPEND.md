# Decision: spend more odds-API credits on batter props?

**Bad news first.**

1. Every batter-prop quote we hold (17,149 rows) was taken **before** the
   lineup posted — median 16.4 hours out, none inside the 2-hour capture
   window — while lineups post a median 3 hours out. We hold the
   *pre*-lineup side for almost every game and the *post*-lineup side for
   none. Why: the code takes one quote per game per day; before 2026-09-11
   it landed ~16 hours out, a fix that day moved it inside 2 hours, on
   purpose. Either way we only ever get one side per game — that's why a
   second pass matters, not "we have nothing." The post-lineup side hasn't
   landed yet as of the newest capture on file (2026-09-11).
2. Stolen bases isn't captured, isn't confirmed as even offered by the
   provider, and the pricing model refuses it regardless. Box scores carry
   the raw stat, so this is fixable later, just not now.

**The real cost, measured.** Batter-prop capture is priced at **5
credits/event** (measured 2026-09-03) — what the spend-guard actually
charges against. Worst case is 6 (one credit/market). All 116 fetches ever
made average 3.7, but that includes 10 that billed zero; the most common
result is 5, and an earlier pass is if anything more likely to hit thin
books, not less. Table below prices at the conservative 6.

| | per event (measured/worst-case) | floor only (2/night) | full slate (~15/night)* | rest of season (16 nights) |
|---|---|---|---|---|
| (A) add a ~6-hr-early pass | 5 / 6 credits | 10–12/night | 75–90/night | 160–192 (floor) / 1,200–1,440 (full slate) |
| (B) add stolen-base capture | ~1 credit, unmeasured — needs a probe first | ~2/night | ~15/night | ~32 (floor) / ~240 (full slate) |

*Not a new order of magnitude: the coded cap is 6 games/night, but the
store shows the existing pass already fetching the full slate most nights
(9–16 events/night) — a pre-lineup pass at that scale isn't new behavior.

For scale: the daily envelope is 900 credits; the last three nights used
576 / 251 / 426 of it; 22,699 remain this cycle, ~18 days left (a reset
date the provider doesn't actually report — an estimate, not a fact).
Either option is noise against that.

**Option A (yours to size):**
- *Do nothing.* Still lets us compare tonight's batters posted higher than
  usual against tonight's at their normal spot, across games, at zero
  spend — weaker than same-game before/after, but real, already running.
- *Floor only (2/night).* ~160–192 credits for the season.
- *Full slate (~15/night).* ~1,200–1,440 credits for the season — about
  1.6 days' worth of the 900-a-day envelope, spread over 16 nights. Bigger
  sample, sooner. No sample-size target exists yet for this read; only the
  free version above has one.

**Option B (yours to size):**
- *Do nothing.*
- *Capture only.* First, a cheap probe confirming the provider even quotes
  this — it could come back zero. If offered, capture is unrecoverable data
  that sits unused until priced (cost in the table).
- *Capture and model.* Off the table — no pricing method exists yet, and
  building one needs a pre-registered check first, same standard as above.

**My recommendation:** the early pass at full-slate scale (~90
credits/night worst case), and probe-then-capture stolen bases. Both round
to nothing against 22,699 credits left, buy unrecoverable data, and touch
neither the model nor your card.

**The decision I need from you:**
1. Early capture pass — off / floor only / full slate?
2. Stolen bases — off / probe-and-capture-if-available? (Modeling it isn't
   a real option yet.)
