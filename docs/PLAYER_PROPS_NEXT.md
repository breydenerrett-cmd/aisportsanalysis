# Player props: likely first, price second

**2026-09-11.** Written against the owner's directive, in his words:

> "none of that price matters until we know it's a MORE THAN LIKELY BET, once
> we have the almost guaranteed bets, then we find the best sports picks of
> those with the best value, not the other way around."

And, on line shopping:

> "how do we move completely away from price checking multiple books cuz that
> shit does not matter and never has and never will."

This document is the plan that follows from taking both literally.

---

## Why he is right, in this repo's own numbers

Ranking a board by price gap surfaces whatever the books **disagree** about.
That is adverse selection, not opportunity: the outlier price is usually the
shop that is slowest or most wrong about something *it* knows and we don't.

`docs/PROP_MARKET_ECONOMICS.md` measured prop margins at **6.79 points**
against **3.65** for moneylines — props are where the house charges most,
which is also why the disagreements look biggest there.

And `scripts/probe_prop_value.py` measured what acting on our own edge
returns: contracts where our probability cleared the best available price
returned **-13.4%**, against **-9.1%** for every assessable over. **Selecting
on our own edge did worse than not selecting at all.**

## The uncomfortable half of his rule

"Know it's more than likely" has to come from *somewhere*. Five measurements
in `docs/DOES_THE_MODEL_BEAT_THE_MARKET.md` say it cannot currently come from
our model:

> Calibrated overall is not the same as calibrated conditional on disagreeing
> with the market.

The prop model **is** calibrated — `batter_hits` at +0.0133 nats over the base
rate, 3.3× what the team model manages. It is calibrated *and* its
disagreements lose money, because departure is selected on the model's own
error.

So "more than likely" cannot mean "our number says so." It has to mean **we
know a fact the price has not absorbed yet.** That is a different claim, it
needs different work, and a null on the first says nothing about it
(`docs/INFORMATION_EDGE_FIRST_LOOK.md`).

## The fact we already have, and were throwing away

**A posted lineup sets each batter's slot, and slot sets plate appearances.**

`playerprops.SLOT_PLATE_APPEARANCES`, measured: leadoff **4.467**, nine-hole
**3.461**. A hitter moving from ninth to leadoff gains about **29% more
chances** — against a 1.5-hit line, that is not a rounding error, it is the
whole edge.

Lineups post a median **2.9 hours before first pitch**, and
`docs/LINEUP_DIRECTION_RESULT.md` shows the *moneyline* moves against a
depleted club after they post (n=149, hit rate 0.584 — real but not yet
promoted; it fails this programme's own family-wise bar and is held for
forward replication).

Until 2026-09-11 we had **never once observed a prop price at that moment**:

```
  batter prop captures   median 17.32h before first pitch   (9,672 quotes)
  lineup postings        median  2.92h                      (287 events)

  prop captures landing after the median lineup post:   0 / 9,672
  games with a prop quote on both sides of a posting:   0 / 77
```

Every capture landed 04:00–09:10 UTC — midnight to 5am Eastern. Not a cron
time: each game is captured once per slate date, so the first run after the
date rolled over took the whole plan. **Fixed** (`CAPTURE_LEAD_MINUTES`),
at no additional credit cost — same games, same caps, different hour.

## The next test, and what it needs

**Hypothesis, sign fixed in advance:** a batter who starts **higher** in the
order than his recent norm gains plate appearances, so his over should
shorten; a batter dropped down should lengthen.

It reuses the machinery that already works:

- the **expected lineup** from appearance rates (`probe_lineup_direction`),
  extended to an **expected slot** — the same point-in-time construction,
  needing no batter-quality model and no price;
- `expected_pa_for_slot` for the magnitude, which is measured, not modelled;
- the same net-move-over-a-window statistic, the same clustered bootstrap,
  the same before-window check for whether we are early or late.

**It is not runnable yet, and saying so is the point.** It needs prop quotes
on both sides of a lineup posting, and the first of those will be collected
tonight. Nothing can be pre-registered honestly against a sample of zero.

**Stopping rule before it is read:** 150 contracts with a quote on both sides
of a posting. At roughly 6 games × ~20 batter contracts per capture, that is
days, not months — but it is measured when it arrives, not estimated here.

## What stops

- **No price-gap ranking is ever presented as a pick list.** `TOP PLAY` was a
  client-invented label over rows the API calls `qualifying` and ranks by
  *execution quality*; it is already removed from `#/today` and
  `tests/test_web_matchups.py` now fails if it comes back.
- **Line shopping stays as execution, never as selection.** Which book to use
  once a bet is chosen is a real question worth one line of UI. It is not a
  reason to bet, and it never answers "is this likely."
- **`#/betcheck` is the last surface still written in the price-comparison
  register** and is the remaining cleanup.

## Honest status

No edge is claimed for player props. One is now *testable* that was not
testable last week, because the thing we needed to observe was happening at
an hour we were asleep.

---

## Status, 2026-09-12 (early morning UTC)

- **Home runs are on the board.** `propboard.likelihood_only` admits a
  market the model is measured good on but no book quotes the under of;
  `/props` carries `long_shots` (the ten likeliest home runs) and the page
  shows them under "Home runs — none of these is likely", OURS and PRICE
  NEEDS only, the market number absent and said so. Ranked by probability,
  never by gap.
- **The T-2h capture gate produces its first rows tonight** (the evening
  of 09-12 UTC). Until then every quote on disk is a pre-lineup quote from
  the 04:00Z runs. Verify after ~22:00Z: a quote observed within two hours
  of a first pitch, and a `batting_slot` on a board row.
- **V7 is pre-registered** before any of that data exists:
  `docs/PREREG_SLOT_PROP.md`, reader `scripts/probe_slot_prop.py` (PENDING
  until 150 UP / 150 FLAT / 100+100 control rows). Market-only: a batter
  against his own prior nights. Needs no extra credits.
- **The timing version** ("does the price move after the lineup posts")
  needs a quote from before the posting, which the gate never takes. A
  ~T-6h baseline capture is about one credit per game per night. That is
  the owner's spend decision and is not made here.
- **Still refused, still measured:** RBIs and hits+runs+RBIs (bunched
  counts; `probe_bunched_counts.py` reports it cannot run until the box
  store is deep enough). Stolen bases: not collected; cost it first.
