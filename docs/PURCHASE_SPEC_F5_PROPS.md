# Purchase spec — historical F5 and player-prop pricing

**Written 2026-09-04** to satisfy `docs/RESOURCE_POLICY.md` § "Before any large
historical purchase, spec it". Every line below is either a **measurement taken
today** (probe scripts and evidence files named inline) or a **count from a
store on disk**. Where something could not be measured it says so and says why;
nothing here is an estimate dressed as a fact.

**Probe spend: 435 credits** (`data/processed/credit_log.jsonl`, callers
`probe_historical_f5_props.*`, `probe_historical_boundaries.*`,
`probe_historical_leadtime.*`, `probe_prop_name_join.*`, and one live
`budget --probe pitcher_props`). Balance 99,340 → 98,905. Daily envelope 900,
spend today 460, floor 5,000 never approached. This is the 10-20% probe band in
`docs/RESOURCE_POLICY.md` being used for exactly what it is for.

**Headline.** The purchase is real, gradeable, and worth making — but the
owner's ~12,000-credit figure is off by roughly a factor of four against the
thing it was meant to buy. 12,000 credits buys about **1,093 games** of F5
moneyline history, which moves B3 from "cannot see an 8.5pp effect" to "cannot
see a 4.6pp effect". **The recommendation is a 45,000-credit buy** of the
2023–24 F5 moneyline, which is what actually cures B3, and which fits one
cycle's growth band. Details in § 9.

---

## 1. What we already hold (measured, not assumed)

### Full-game history — DENSE. Do not re-buy any of it.

`data/historical/odds_history/` (archived byte-identical at
`data/archive/historical/odds_history/`, 600 snapshot lines per season):

| season | snapshots | event-rows | distinct games | dates | books | markets |
|---|---|---|---|---|---|---|
| 2023 | 600 | 11,167 | 2,491 | 189 | 19 | h2h, totals |
| 2024 | 600 | 10,310 | 2,486 | 192 | 14 | h2h, totals |
| 2025 | 600 | 10,540 | 2,500 | 193 | 11 | h2h, totals |

Cadence is **3 snapshots/day** (2024 exactly 3 every day; 2023 and 2025 have a
handful of 1- and 23-snapshot days). Full-game h2h rows: 133,330 / 93,724 /
90,458. Requested market string was `h2h,totals` on all 1,800 snapshots — there
are no spreads and no F5 in this store.

### First-five history — THIN. This is the gap.

`data/historical/odds_first_five/`:

| season | rows | distinct games | with an `h2h_1st_5_innings` price | books | date range |
|---|---|---|---|---|---|
| 2023 | 265 | 229 | 151 | 13 | 2023-05-03 .. 2023-10-01 |
| 2024 | 189 | 170 | 113 | 14 | 2024-04-21 .. 2024-09-29 |
| 2025 | 207 | 195 | 160 | 10 | 2025-04-20 .. 2025-09-28 |
| **total** | **661** | **594** | **424** | | |

Against the 6,923 games that exist in the F5-available window (§ 4), that is
**6.1% coverage of games and 8.6% of the seasons' dates**. One snapshot per
game, near first pitch. No opening line, no second observation, so **no
line-movement question is answerable from this store at all.**

### Settlement — free, correct, and partially built.

`data/historical/first_five_results.jsonl`, written by `src/research/f5_store.py`
from MLB StatsAPI at **0 odds credits**:

- **2,494 games over 181 dates**, 2023-05-03 .. 2024-09-29. (The catalogue's
  "2,512" is the file's line count; 18 lines are duplicate `game_pk`s.)
- 2,479 complete; **354 level after five innings = 14.3% ties.** This is the
  measured push rate that every F5 moneyline sample loses off the top.
- **2025 is entirely absent** from this store. So are 2024-09-30 onward and
  every 2023 date before 05-03.

### Props — forward only, days old, zero history.

| store | rows | distinct games | dates | markets | books |
|---|---|---|---|---|---|
| `prop_prices.jsonl` | 164 | 5 | 2026-09-02..09-04 | `pitcher_strikeouts` | 7 |
| `batter_props.jsonl` | 874 | 9 | 2026-09-03..09-04 | 5 batter keys | 5 |
| `derivative_markets.jsonl` | 3,009 | 9 | 2026-09-03..09-04 | alternates, team totals, F5 trio | 9 |
| `f5_close.jsonl` | 416 | 46 | 2026-08-31..09-04 | `h2h_1st_5_innings` | 9 |

All four are days old and all four are inside the forward-proof window
(2026-08-28 onward). **We hold zero historical prop pricing of any kind.**

### The gap, stated precisely

- Full-game h2h/totals 2023–25: **complete, do not buy.**
- F5 moneyline 2023–25: **424 of ~6,900 gradeable games priced (6%).**
- F5 totals 2023–25: 12 books present but only on those same ~594 games.
- Pitcher props, any season before 2026-08-31: **nothing.**
- Batter props, any season before 2026-09-03: **nothing.**
- F5 settlement: 2023–24 partial (181 of 339 dates), 2025 missing — **but free.**

---

## 2. Measured provider facts

Probes: `scripts/probe_historical_f5_props.py`,
`scripts/probe_historical_boundaries.py`, `scripts/probe_historical_leadtime.py`,
`scripts/probe_prop_name_join.py`. Raw results in `evidence/probe_historical_*.json`
and `evidence/probe_prop_name_join.json`.

### Billing — the code's assumption is exactly right, with one free case

`src/pipeline/backfill.py:57` assumes `HISTORICAL_MULTIPLIER (10) × len(markets)`
per event. Measured against the provider's own `x-requests-last` header on 19
per-event historical calls: **billed == 10 × markets, every time, no exception.**

The one thing the assumption misses is free: **an empty payload bills 0.** The
first probe run drew events that had already started (F5 and prop markets are
pulled from the board at first pitch) and every one of those returned zero books
and billed zero credits. A `MarketsUnavailableAtDate` 422 also bills zero. So a
backfill that overshoots the coverage boundary or asks for a game in progress
pays nothing for the miss — the cost model has no waste term.

The historical `/events` lookup bills **1 credit** (measured, 10 lookups).

### Cadence — a real 5-minute grid, and it is not a "date"

`docs/RESEARCH_CATALOGUE.md` B5 grades every historical event class C/D and
records that a transaction DATE is never treated as a TIME. **That grade does
not extend to prices, and this is the measurement that says so.**

Every per-event response carries `timestamp`, `previous_timestamp` and
`next_timestamp`. Measured on ordinary in-season nights in all three seasons:

| season | requested | served | previous | next |
|---|---|---|---|---|
| 2023 | 2023-07-18T22:50:00Z | 22:45:40Z | 22:40:40Z | 22:50:40Z |
| 2024 | 2024-07-10T22:50:00Z | 22:45:37Z | 22:40:37Z | 22:50:37Z |
| 2025 | 2025-07-09T22:50:00Z | 22:45:37Z | 22:40:38Z | 22:50:37Z |

**Five-minute grid, all three seasons.** The served snapshot is the grid point
at or before the requested instant, so the requested-to-served gap is bounded by
5 minutes and is a *known* quantity, not a bracket to be guessed at.

Better: each bookmaker and each market carries its own `last_update`, and those
are genuinely finer than the grid — e.g. at the 2023-07-18T22:45:40Z snapshot
the eleven books' `last_update` values spread over 22:42:29 .. 22:44:52. So a
price is stamped to the **minute**, by the book, not by our sampling.

**The one measured hole:** 2023-07-12 (the All-Star break) served
`2023-07-12T03:40:40Z` for a 22:50Z request, with `next_timestamp`
2023-07-13T09:15:40Z — a **29-hour hole in the archive**. Off-days are not on
the grid. This costs nothing (no games), but a backfill must key off game dates,
which `backfill.py` already does.

### Coverage start — measured, not quoted

`docs/COLLECTION_POLICY.md` says F5 history "begins in mid-May 2023" as prose.
Measured, per-event, F5 moneyline:

| date | result |
|---|---|
| 2023-03-31 | `MarketsUnavailableAtDate` (HTTP 422), billed 0 |
| 2023-04-20 | `MarketsUnavailableAtDate` (HTTP 422), billed 0 |
| 2023-05-10 | **8 books, 16 outcomes, billed 10** |

`pitcher_strikeouts` on 2023-04-20: also 422. So **F5 and pitcher props both
start between 2023-04-21 and 2023-05-10.** The 20 and 21 events on the board at
those earlier instants prove the *slate* is archived — it is the derivative
markets that are absent, which is the honest version of "mid-May 2023".

The spec budgets from **2023-05-10** and treats 2023-03-30..05-09 as unbuyable.

### Lead time — an opening line exists, from about T-12h

The boundaries probe first tried to measure this by taking the soonest pre-game
event at three instants; that silently compared three *different* games each an
hour from its own first pitch and answered nothing. Re-done properly by holding
ONE event fixed (Yankees @ Rays, first pitch 2024-07-10T22:51:00Z) and moving
the instant (`scripts/probe_historical_leadtime.py`):

| lead | served | F5 h2h books | K-prop books | billed |
|---|---|---|---|---|
| T-48h | — | HTTP 404, event not in that snapshot | | 0 |
| T-24h | 2024-07-09T22:45:37Z | **0 (market not yet posted)** | 0 | **0** |
| T-12h | 2024-07-10T10:45:37Z | 9 | 5 | 20 |
| T-6h | 2024-07-10T16:45:37Z | 12 | 8 | 20 |
| T-1h | 2024-07-10T21:45:37Z | 12 | 8 | 20 |
| T-6m | 2024-07-10T22:40:37Z | 12 | 8 | 20 |

**F5 and pitcher props are posted somewhere between T-24h and T-12h and stay up
to first pitch, on a 5-minute grid throughout.** So an opening-to-close price
path IS purchasable — at 10 credits per market per snapshot, which is what makes
a multi-snapshot pull expensive (§ 4).

### Books available, per market, per season (measured)

| market | 2023 | 2024 | 2025 |
|---|---|---|---|
| `h2h_1st_5_innings` | **13** | 12 | 8 |
| `totals_1st_5_innings` | 12 | 10 | 6 |
| `pitcher_strikeouts` | **10** | 8 | 8 |
| batter (hits / TB / HR) | 11 | 9 | 9 |

2023 F5 books: barstool, betmgm, betonlineag, betrivers, betus, bovada,
draftkings, fanduel, lowvig, mybookieag, pointsbetus, unibet_us, williamhill_us.
Book count declines season over season as US books consolidated; 2025 F5 at 8
books is the thinnest.

**This corrects two documented figures.** `docs/RESEARCH_CATALOGUE.md` U3 says
pitcher-strikeout history is "3–4 books, thin"; measured, it is **10 books in
2023 and 8 in 2024–25**, with 40–78 outcome rows per event. And
`config/capture_families.json` records batter props as "zero history, no
retroactive purchase path"; measured, **batter props are retrievable historically
from at least 2023-07-18 at 9–11 books and ~1,200 outcome rows per event.**

### Payload sizes (measured, one pre-game event)

| group | markets | 2023 | 2024 | 2025 |
|---|---|---|---|---|
| F5 h2h | 1 | 26 outcomes | 24 | 16 |
| F5 pair | 2 | 50 | 44 | 28 |
| pitcher K | 1 | 78 outcomes, 2 players | 40, 2 | 42, 2 |
| batter × 3 | 3 | 1,231 outcomes, 31 players | 1,230, 21 | 938, 19 |

Pitcher props return exactly **the two starters** — no relievers, ever, in any
probe. Batter props return 19–31 named batters per game.

---

## 3. Settlement compatibility — can we actually grade this?

A market we cannot settle is worth zero credits at any price. Measured per
market family.

### F5 moneyline and F5 totals — YES, cleanly, and already proven

The F5 store rows carry **`game_pk`** (MLB's own id) alongside the Odds API
`event_id`. Measured on the existing store: of the 424 rows carrying an
`h2h_1st_5_innings` price, **424 (100%) carry a `game_pk`.** Joining those
against `first_five_results.jsonl`:

| | count |
|---|---|
| priced F5 events | 424 |
| `game_pk` present | 424 (100%) |
| joined to a settlement record | 264 |
| joined **and** complete (gradeable) | 264 (100% of joins) |
| joined, complete, **decided** (no tie) | **228** |

Every join that lands is gradeable. The 160 that do not land are the **2025**
rows, and they fail only because the settlement store stops at 2024-09-29 — not
because of any id problem. Closing that is **free** (§ 8).

This is the strongest settlement result in the spec, and it is the reason the F5
buy is the recommended one.

### Pitcher strikeouts — YES, with a name join that measures clean

`data/historical/pitcher_logs.jsonl` (42,963 rows) carries per-start
`strikeouts` keyed by MLBAM `person_id` and date. The prop payload carries the
player as a **name string** (`outcome.description`), never an id, so grading
needs a name→id join. Measured against `data/historical/handedness.json` (1,610
players, 1,608 distinct normalised names, 2 genuinely ambiguous — "carlos perez",
"max muncy"):

**Pitcher prop names resolved 2/2 (100%) in every probe, all three seasons.**
n is small because a game only has two starters; the relevant fact is that zero
pitcher names failed across seven payloads.

### Batter props — YES for regulated books, NO for one offshore book

Aggregated across books, the 2023 batter payload resolved only **21/31 (68%)**,
missing "Frederick Freeman", "Markus Betts", "Boyce Mullins", "Christopher
Taylor", "Maxwell Muncy", "Julio Martinez" and similar. That looked like a
2023-wide feed defect. It is not. Re-probed with names kept **per book**
(`scripts/probe_prop_name_join.py`, 31 credits, same event and instant):

| book | resolved | note |
|---|---|---|
| barstool, betmgm, betonlineag, draftkings, fanduel, pointsbetus, williamhill_us | **18–19 / 18–19 (100%)** | |
| bovada | 17/18 | the miss is `No Home Run` — a market outcome, not a player |
| betrivers, unibet_us | 13/14 (93%) | the miss is `Will (LAD) Smith` — a disambiguation suffix |
| **mybookieag** | **19/27 (70%)** | legal names: Frederick/Markus/Boyce/Maxwell/Christopher/Julio |

**Nine of eleven books settle at 100% once `No Home Run` is excluded as an
outcome rather than a player.** The batter-prop settlement risk is one offshore
book and a ten-name alias table, not a structural blocker. It is still real
engineering that does not exist today.

The deeper batter constraint: **there is no batter game-log store.** Hits, total
bases and home runs would have to be reconstructed per plate appearance from
`data/historical/statcast/` (183 pitch-level files, `events`, `game_pk`,
`batter` id present). That is derivable and cheap in credits (zero) but is a
build, and it is unbuilt.

### Claims the cadence cannot support

Stated plainly, per `docs/RESEARCH_CATALOGUE.md` B5:

- **Anything sub-5-minute.** V2/N13's tick-level reversal question stays closed
  historically at any price. The 5-minute grid is coarser than the tick data the
  Management Science result used, and buying more of it does not change that.
- **Anything before T-12h.** No F5 or prop line exists on the board at T-24h, so
  "the number the market opened at, days out" is not a thing that can be bought.
  The earliest purchasable observation is roughly T-12h.
- **Anything joining prices to a same-day non-price event.** Transactions are
  day-only and stored lineups are date-only (B5). A price stamped to the minute
  joined to a lineup stamped to the day is still a day-resolution claim; the
  price side getting better does not fix the other side. **V3 remains a forward
  study.**
- **Anything relying on 2023-03-30..2023-05-09.** Provider-side absent, measured.

---

## 4. Cost model (every term measured)

```
credits = (dates × 2 events-lookups × snapshots) + (games × 10 × markets × snapshots)
```

`backfill.py` asks two instants per date (16:50Z for the day slate, 22:50Z for
the night slate) at 1 credit each. Empty payloads and 422s bill 0.

**Games in the F5-available window**, counted from the full-game archive:

| season | games from 2023-05-10 / season start | dates |
|---|---|---|
| 2023 (from 05-10) | 1,937 | 147 |
| 2024 | 2,486 | 192 |
| 2025 | 2,500 | 193 |
| **total** | **6,923** | **532** |

| pull | markets × snapshots | total credits | per game |
|---|---|---|---|
| F5 h2h, close only, 3 seasons | 1 × 1 | **70,294** | 10.2 |
| F5 h2h + totals, close only | 2 × 1 | 139,524 | 20.2 |
| F5 h2h, 2 snapshots (T-6h + close) | 1 × 2 | 140,588 | 20.3 |
| F5 pair + K props + 3 batter markets | 6 × 1 | 416,444 | 60.2 |
| **F5 h2h, close only, 2023–24 only** | 1 × 1 | **44,908** | 10.2 |

**What 12,000 credits actually buys**, at the same measured rates:

| pull | games |
|---|---|
| F5 h2h close only | 1,093 |
| F5 h2h + totals | 546 |
| F5 h2h + pitcher K | 546 |
| F5 h2h at two snapshots | 493 |
| the full six-market bundle | 182 |

---

## 5. Historical decisions unlocked, and the power that buys

Decided-game yield uses the **measured 14.3% F5 tie rate**: 85.7% of complete
games produce a decided moneyline.

B3 today: n=270 decided, effect +1.25pp, 95% CI [−4.56, +7.12] (half-width
5.84pp). A binomial half-width at n=270 is 5.96pp, so B3's interval is
effectively unclustered and this arithmetic is the right arithmetic.

Minimum detectable calibration miss, 80% power, 5% two-sided:

| decided games | detects | 95% CI half-width |
|---|---|---|
| 270 (today) | **8.52pp** | 5.96pp |
| 936 (12,000 credits) | 4.58pp | 3.20pp |
| 1,206 (12,000 + today's) | 4.03pp | 2.82pp |
| 2,050 (25,000 credits) | 3.09pp | 2.16pp |
| **3,791 (45,000 credits, 2023–24)** | **2.28pp** | **1.59pp** |
| 5,933 (70,000 credits, 3 seasons) | 1.82pp | 1.27pp |

Read the other way — what a target effect costs:

| detect | decided needed | games priced | credits at 10/game |
|---|---|---|---|
| 5.0pp | 785 | 916 | 9,159 |
| 4.0pp | 1,226 | 1,431 | 14,310 |
| 3.0pp | 2,180 | 2,544 | 25,440 |
| **2.5pp** | 3,140 | 3,663 | **36,634** |
| 2.0pp | 4,906 | 5,724 | 57,241 |
| 1.0pp | 19,622 | 22,896 | 228,964 |

**This is the decisive table.** A soft-market mispricing worth trading is
plausibly 2–3pp. At 12,000 credits we can see 4.6pp — bigger than any edge we
would believe. **12,000 credits buys a second "we cannot tell".**

---

## 6. The accounting chain

Per `docs/RESOURCE_POLICY.md`, for the recommended buy (§ 9):

```
45,000 credits (2023-05-10 .. 2024-10-07, F5 h2h, one close snapshot per game)
  -> 4,423 games priced across 339 dates, 12-13 books each
  -> ~3,791 DECIDED F5 moneylines (14.3% measured tie rate)
     plus ~4,400 * 12 = ~53,000 book-level price rows for consensus/de-vig
  -> B3/M4 becomes answerable at 2.28pp instead of 8.52pp; U1 becomes
     registrable as a pre-registered family with a real 2023-screen /
     2024-replication split
  -> backtests: U1 (F5 moneyline as a bet target) point-in-time on 2023,
     replicated on 2024, FDR-gated; B3 resolved as evidence rather than as
     a sample-size shrug. Forward test continues on f5_close.jsonl, which is
     already accumulating at 1 credit/event/moment.
```

And the losing chain, stated so it cannot be proposed later:

```
70,000 credits (3 seasons) -> 2025 is TUNING-ONLY FOREVER, so the third
  season's 2,500 games can never contribute to a discovery or replication
  result. It buys a tuning set we can look at once. Not now.
```

---

## 7. Which research families become testable

| family | today | after the 45,000-credit buy |
|---|---|---|
| **U1 — first F5 research family** | BLOCKED in practice: 424 priced games, 228 decided, no 2023/2024 split with power | **UNBLOCKED.** 2023 screen on ~1,660 decided, 2024 replication on ~2,130 decided. Detects 2.3pp pooled; ~3.4pp within each season alone. This is the first F5 family that could survive its own replication gate rather than dying of n. |
| **B3 / M4 — F5 vs full-game bullpen gap** | "we cannot tell" at 8.5pp | **RESOLVABLE** at 2.28pp. The full-game side already exists (133,330 / 93,724 h2h rows), so the buy completes an otherwise-complete pair. |
| **U3 — pitcher-strikeout props** | no history at all | **NOT unblocked by this buy** — deliberately carved out (§ 9). Coverage is better than documented (10/8/8 books, both starters, from May 2023) and settlement joins 100%, so it is a *good* future buy, just not this one: 44,908 more credits for a family with no registered hypothesis. |
| **U2 — alternate spreads/totals** | probe-priced at 1–2 credits/event forward, collection off by choice | **UNCHANGED.** Historical alternates were not probed and are not in this spec. Forward capture is already the cheapest information-per-credit on the board; nothing here argues for buying its history. |
| **U5 — a totals family** | never registered as a bet target | **PARTIALLY.** F5 totals are quoted at 12/10/6 books and would cost 44,908 more (the second market doubles the pull). Full-game totals history we already hold densely — 123,224 / 90,534 / 88,513 rows — so **U5's full-game half needs no purchase at all**, only a registered hypothesis. That makes U5 the cheapest unblocked family on the board today: zero credits. |

**The honest note on U5:** it is listed in the catalogue as never evaluated, and
this spec finds that the data to evaluate its full-game half has been on disk
the whole time. That is a free lane and it should be taken before any purchase
is made, not because it competes with the F5 buy but because it costs nothing.

---

## 8. Prerequisites that cost zero credits

Both must be done **before** the pull, or the bought rows are ungradeable:

1. **Extend `first_five_results.jsonl` to every date in the buy window.** It
   holds 181 dates; the 2023-05-10..2024-10-07 window has 339. `f5_store.ingest`
   is resumable, skips dates already present, and costs **0 odds credits**
   (MLB StatsAPI). Without this, ~47% of the bought games have no settlement row
   — exactly the failure that leaves 160 of today's 2025 rows ungradeable.
2. **De-duplicate the 18 repeated `game_pk` lines** in that store, or make the
   reader last-write-wins explicitly. It is append-only forward data, so this is
   a read-side fix, never a rewrite.

Not required for the recommended buy, but required before any batter-prop buy:

3. A batter game-log store derived from `data/historical/statcast/` (hits, total
   bases, home runs per `game_pk` × `batter`), and a name-alias table covering
   mybookieag's legal-name convention. Both zero credits, both unbuilt.

---

## 9. Recommendation

**Buy 45,000 credits of 2023–24 F5 moneyline history. Do not buy props yet. Do
not buy 2025 yet.**

| | |
|---|---|
| **markets** | `h2h_1st_5_innings` only |
| **window** | 2023-05-10 .. 2024-10-07 (339 dates, 4,423 games) |
| **cadence** | one snapshot per game, at `backfill.py`'s existing 22:50Z/16:50Z instants |
| **cost** | 4,423 × 10 + 339 × 2 = **44,908 credits** |
| **yield** | ~3,791 decided F5 moneylines, 12–13 books each, ~53,000 price rows |
| **power** | B3 at **2.28pp** (from 8.52pp); U1 gets a real 2023/2024 split |
| **prereq** | free settlement backfill (§ 8), done first |
| **execution** | `src/pipeline/backfill.py run_first_five` already does this, is resumable, is manifest-keyed, and reports unmatched games rather than silently skipping. Pass `budget=` and run it in tranches. |

**Why not 12,000.** 12,000 credits is 1,093 games and 936 decided. It takes the
minimum detectable effect from 8.5pp to 4.6pp — still larger than any F5 edge
worth believing. It would produce a second underpowered B3 result and burn the
option. If the choice is 12,000 or nothing, **choose nothing**: the credits keep
their value inside the cycle, and `f5_close.jsonl` keeps accumulating forward at
1 credit/event/moment regardless.

**Why not 70,000 (all three seasons).** 2025 is tuning-only forever
(`docs/ROADMAP.md` Stage 4). Its 2,500 games cannot appear in a discovery or a
replication result. Buying it now is 25,000 credits for a set we may look at
once, later; it belongs in a subsequent cycle after 2023–24 has produced or
killed a family, not in this one.

**Why props are carved out.** They measure *better* than documented — 10 books
in 2023, both starters every time, 100% name resolution, and
`pitcher_logs.jsonl` already holds the strikeout counts that settle them. That
is a genuine correction to U3 and to `config/capture_families.json`. But
**no pitcher-prop or batter-prop hypothesis is registered**, and
`docs/RESOURCE_POLICY.md` priority 4 says probe first, then scale once a probe
proves useful — not buy history for a family nobody has named. Batter props
additionally need a settlement store that does not exist. Register a prop
hypothesis first; the buy is then ~45,000 credits for 2023–24 pitcher K at the
same measured rates, and this spec's numbers carry over unchanged.

### Budget fit

Cycle allotment 100,000, reset assumed 2026-10-01, 98,905 remaining, 26 days
left. Forward capture at 900/day needs ~23,400 of that. A 45,000 buy is **45% of
the allotment**, landing at the top of the 40–50% "historical backfill" band,
and leaves ~30,000 for contingency and the 10–20% probe band. It never
approaches the 5,000 floor. Run it in tranches with `budget=` so a mid-run stop
is a resumable pause, not a loss.

### What else 45,000 credits could buy — the trade

| alternative | at measured rates | verdict |
|---|---|---|
| forward alternates (U2), 15 games/night | 2 cr/event → **1,500 game-nights** | Cheapest information-per-credit on the board, but collection is off *by choice* pending a hypothesis, and a season only has ~2,430 game-nights — this cannot absorb 45,000 credits usefully this cycle. |
| forward batter props, floor + extra | 10 cr/event → 4,500 event-captures | ~300 nights at 15 games. More than the season has left. |
| widening the whole forward stack | 900/day is already the 27% reserve | **Forward capture is not credit-constrained.** Raising it would exceed the 25–35% band, not the budget. |
| historical pitcher K, 2023–24 | 44,908 | Same price as the F5 buy, for a family with no registered hypothesis. Second, not first. |
| doing nothing | 0 | Credits expire at reset with zero value. `docs/RESOURCE_POLICY.md` calls this a reportable failure. |

The trade is genuinely favourable: the forward lanes are constrained by the
reserve band and by the number of games left in the season, **not by credits**.
The F5 backfill is the only line item that can absorb this much budget and
convert it into gradeable decisions inside this cycle.

---

## 10. What this spec could not measure

Stated so nothing here reads as more certain than it is.

- **Match rate of a real backfill.** The 4,423 figure counts games the full-game
  archive saw. `run_first_five` matches by team pair per date and reports
  unmatched rather than skipping; the historical unmatched rate was not measured
  (measuring it means running the pull). Budget for it: if 3% go unmatched the
  buy is ~43,600 credits and ~3,680 decided instead.
- **Book-count stability across the season.** Books were counted on one night
  per season. April and September could differ.
- **Whether the 2023 coverage boundary is 2023-05-01 or 2023-05-10.** Bisected to
  a 20-day window (2023-04-20 dead, 2023-05-10 live). Narrowing it further is ~5
  more free 422s; worth doing at pull time, worth at most ~200 extra games.
- **Historical alternate spreads/totals.** Not probed. Out of scope; U2's
  forward price is already known.
- **2025 F5 settlement.** The settlement store stops at 2024-09-29, so the 160
  priced 2025 events in hand are currently ungradeable. This is free to fix and
  is § 8, but it is not fixed as of this writing.
- **Batter total-bases derivation from statcast.** The `events` field is present
  and per-plate-appearance, so the derivation is clearly possible, but no
  mapping from `events` values to bases was written or validated here.
