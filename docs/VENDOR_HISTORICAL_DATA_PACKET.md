# Vendor historical-data purchase packet (P0-H, owner decision only)

Docs-only. No purchase, no probe call, no credential use. Written 2026-09-03.

## 1. Vendor and product

**The Odds API** (the-odds-api.com), v4 REST API, already integrated in
`src/providers/odds.py` (`API_HOST = "https://api.the-odds-api.com/v4"`, key
in env var `ODDS_API_KEY`, never printed). Purchase under review is
**historical odds access on the same key/account**, not a new vendor. Fetched
2026-09-03 from https://the-odds-api.com/liveapi/guides/v4/#historical-odds
and https://the-odds-api.com/#pricing.

## 2. Endpoints and fields available historically

Per vendor docs (fetched 2026-09-03):

- `GET /v4/historical/sports/{sport}/odds?apiKey=&regions=&markets=&date=`
- `GET /v4/historical/sports/{sport}/events?apiKey=&date=`
- `GET /v4/historical/sports/{sport}/events/{eventId}/odds?apiKey=&regions=&markets=&date=`

Response shape mirrors the live endpoints (bookmaker → market → outcomes),
plus `timestamp`, `previous_timestamp`, `next_timestamp` for stepping through
the snapshot series. Fields per quote match live: price (American, per this
repo's `ODDS_FORMAT`), point (for spreads/totals/props), `last_update`.

**Snapshot granularity**: vendor states 5-minute intervals from **September
2022** onward; **10-minute** intervals before that. This repo's own constant
(`HISTORICAL_COVERAGE_START = "2020-06-06"`, `odds.py:234`) matches the
vendor's stated archive start of **June 6, 2020**.

**Markets historically**: same market keys as live (h2h, spreads, totals, F5
variants, player props, alternates) — vendor says historical responses use
"odds structures matching live endpoints" but does not enumerate a separate
historical market list. Where the vendor page is unclear: **it does not name
which specific prop markets, or which sports' props, are covered for MLB**
— only that props are "available for selected US sports and bookmakers, with
more on the way." This project's own live probe (`PROBE_PROP_LISTING.md`)
measured **7 books** on MLB `pitcher_strikeouts` live in 2026; the vendor
gives no historical book-count guarantee, so a pull could return fewer books.
**Unclear, stated as unclear rather than guessed.**

**Books**: no per-sport historical book list published; "bookmakers, sports,
and markets only appear from when they were added to the live API" — a book
that joined in 2024 has no 2023 history, unverifiable without the §5 probe.

## 3. Years/dates of coverage per market family

| Market family | Coverage start | Source |
|---|---|---|
| h2h / spreads / totals (core) | 2020-06-06 | vendor page; matches `odds.py:234` |
| Player props, alternate lines, period markets (incl. F5) | **2023-05-03T05:30:00Z** | vendor page, exact timestamp given |
| Snapshot spacing | 10-min before Sept 2022, 5-min from Sept 2022 on | vendor page |
| Odds format | Decimal only before 2022-09-18; American conversions may have rounding errors before then | vendor page |

Matches what this repo already holds (`map-historical-data-pit.md`):
`data/historical/odds_history/` = 600 records/season × 3 seasons (2023–25),
markets **`h2h` and `totals` only** — no `spreads` was ever bought (confirmed
by direct scan). `odds_first_five/` = one F5 snapshot per game (185/133/172
games with any book, 2023/24/25), h2h/totals only, no timing, no movement.
**No prop history has ever been purchased.**

## 4. Credit cost per historical call, and purchase arithmetic

Vendor-confirmed formula (fetched 2026-09-03): **cost = 10 × markets ×
regions**, per call, matching `HISTORICAL_CREDIT_MULTIPLIER = 10` already
coded at `odds.py:233`. One call returns the whole slate at that instant
(cost does not scale with games in a snapshot). Empty responses bill 0.

Assumptions: 15 games/day average slate (`map-odds-provider-markets.md` §7);
1 region (`us`); season length 186 days (`SEASON_DAYS`, `odds.py:230`), ×2
for "2023–24"; props assumed to need the **per-event** historical call (one
call/game, not one call/slate), mirroring the live per-event billing shape —
**an assumption, not vendor-confirmed for the historical endpoint**, to be
checked by the probe in §5 before any purchase.

### (a) 2023–24 pitcher-K props, one snapshot per game

- Calls: 1 market (`pitcher_strikeouts`) × 1 region, **per event**, per season.
  ≈ 15 games/day × 186 days × 2 seasons = 5,580 calls.
- Credits/call: 10 × 1 × 1 = 10.
- Total: 5,580 × 10 = **55,800 credits**.
- Tier: 100K ($59/mo) covers it with headroom; 20K ($30/mo) does not
  (55,800 > 20,000). **Cost: $59** (one month, cancel after — this repo's own
  "one-time backfill" convention, `estimate_backfill_credits` docstring).

### (b) 2023–24 full board at 5-minute grid, last 3 hours before first pitch

- Snapshots: 3 hours ÷ 5 min = 36 snapshots per game-night (slate-level call,
  not per-event, since h2h/spreads/totals are on the featured historical
  endpoint).
- "Full board" here = h2h + spreads + totals = 3 markets, 1 region, per
  slate-snapshot (not per event — the featured historical endpoint bills
  once for the whole slate, same shape as live `/odds`).
- Credits/call: 10 × 3 × 1 = 30.
- Calls: 36 snapshots/day × 186 days × 2 seasons = 13,392 calls.
- Total: 13,392 × 30 = **401,760 credits**.
- Tier required: exceeds 100K; needs **5M** ($119/mo).
- **Cost: $119** (one month).
- Caveat: this reuses one snapshot per instant for every game on the slate,
  so it is much cheaper per game-hour of coverage than the per-event prop
  math in (a)/(c) — the "cost shape is completely different" warning already
  in `odds.py:58-71` for F5, generalized.

### (c) 2024 batter props, two snapshots per game

- No batter prop market key exists anywhere in this codebase today
  (`SUPPORTED_MARKETS` has none; confirmed MISSING in
  `map-odds-provider-markets.md` §1). Assume 1 representative batter market
  (e.g. `batter_hits`) per the owner's vision list, per-event, 1 region.
- Calls: 15 games/day × 186 days × 1 season × 2 snapshots = 5,580 calls.
- Credits/call: 10 × 1 × 1 = 10.
- Total: 5,580 × 10 = **55,800 credits**.
- Tier: 100K ($59/mo). **Cost: $59** (one month).
- Full 8-market batter-prop family from the vision list (hits, TB, HR, RBI,
  runs, walks, Ks, SB) ×8: **446,400 credits → needs 5M tier ($119/mo)**.

### Combined, all three in the same month

(a) 55,800 + (b) 401,760 + (c) 55,800 = **513,360 credits**, fits the 5M
tier ($119, ~10% used) — cheaper than three separate 100K months.

## 5. Coverage caveats and pre-purchase verification

- **Missing/unclear books**: no historical per-book list for MLB props; a
  book added after a given date has no history before it. Only verifiable
  with a live probe against the historical endpoint.
- **Missing dates**: pre-2023-05-03 has zero prop/alternate/period-market
  data — exact vendor timestamp, not an estimate.
- **Pre-Sept-2022 precision**: 10-minute grid, decimal-odds-only before
  2022-09-18, with stated rounding risk on American conversions of it.
  Irrelevant to the 2023–24 purchases above; relevant only for 2020–22.
- **What we can verify before buying**: a **10-credit probe** of one
  historical date for `pitcher_strikeouts` on one event (10 × 1 market × 1
  region, per the confirmed 10x multiplier — note this is *not* the 1-credit
  figure `PROBE_PROP_LISTING.md` used, which was for the live per-event
  endpoint). Described, not run: call the historical per-event odds endpoint
  for one known 2023 game/date and one prop market, read `x-requests-last`
  for the true billed cost, and confirm book count and field shape before
  committing to (a)/(b)/(c) at scale.

## 6. What each purchase unlocks vs. does not, per `ARCHITECTURE_BETTING_ENGINE.md` §6/§8

**Unlocks:**
- (a)/(c) prop purchases: settlement-backed prop backtests become possible
  for the purchased window — §6 P2 names this ("the vendor's prop history...
  register a hypothesis or accept the permanent gap"). Combined with GUMBO
  box-score backfill (§6 P0 item 8), a purchased prop price plus an actual
  box-score outcome gives a real graded historical prop bet, which this repo
  has never had.
- (b) 5-minute grid: enables dense timing/lead-lag questions for 2023–24 at
  the same granularity the forward system runs at today.
- All three: a real, priced-market alternative to the current
  LATE_BOARD/grade-D-starter degraded-information replay (§7 amendment 2),
  for the purchased window and markets only.

**Does NOT unlock:**
- Lineup-post timestamps for 2023–24 — confirmed **forever gone**
  (`map-historical-data-pit.md` §3, §9): no archived feed with fetch
  timestamps exists, and no purchase can manufacture one retroactively.
  Grade-C/D starter-identity and lineup-conditioned features stay C/D
  regardless of how much market history is bought.
- Probable-pitcher announcement timestamps — same permanent gap
  (`AUDIT_PROBABLE_PITCHER_PIT.md`), independent of market data.
- Umpire crew history for 2023–24 — no archived feed exists.
- API-observation latency (book-changes-price → vendor-records-it lag) — not
  observable from any historical pull; would need a second concurrent feed
  never run at the time.
- Any market never polled at the time by a book not yet on the platform —
  a purchase cannot manufacture a snapshot never taken.

## 7. Recommendation, ordered by information-per-dollar

1. **(a) pitcher-K props, 2023–24, one snapshot/game — $59, 55,800 credits.**
   Cheapest, and plugs the one prop market this project already has
   forward-capture and listing-feasibility tooling for (`prop_listing.py`,
   `prop_prices.py`), sharing schema and settlement path. Highest
   information-per-dollar: turns an already-instrumented market from
   forward-only to backtestable.
2. **(b) full-board 5-minute grid, last 3h, 2023–24 — $119, 401,760 credits.**
   Larger absolute cost, but slate-level, densifying every game's closing
   window — good value per game-hour, poor value per credit for any single
   question. Worth buying only alongside (a) or (c) in one $119 month (§4
   "combined"), not alone, since a dedicated 100K month covers (a) or (c) at
   half the price.
3. **(c) batter props, 2024, two snapshots/game — $59–$119.** Lowest
   priority: no batter-prop market key exists in code (§6 of
   `map-odds-provider-markets.md`), so this data would sit unused until new
   code and a fresh narrow approval (`odds.py:84-85`'s "keys are added when a
   registered need names them") are done first.

**Honest comparison to free forward 2026 capture.** The live pipeline already
captures h2h/spreads/totals continuously (§6 P0, inside the ~132 credits/day
envelope), F5 h2h nightly, and a bounded live pitcher-K prop listing+price
stream (36 credits/day, on since 2026-09-02) — at zero incremental cost
beyond the existing plan, and none of it needs buying back later. The
purchases above buy only *retroactive* 2023–24 coverage; they add nothing the
current forward capture is not already accumulating for 2026 at zero extra
cost. The case for buying is purely about widening the backtest window into
pre-2026 seasons.
