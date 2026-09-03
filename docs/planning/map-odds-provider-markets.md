# Subsystem map: odds-provider-markets

Read-only map, written 2026-09-03. Every claim below cites file:line or a
command run against the live repo/data. Branch:
`claude/sports-betting-analysis-review-g1o0co`.

## 0. What "the board" actually is vs. what we touch

The Odds API (the-odds-api.com v4) organizes MLB markets into three billing
families, and this repo currently reaches only two of them, thinly:

| Family | Endpoint | Billing | This repo |
|---|---|---|---|
| Featured (h2h, spreads, totals) | `GET /sports/{sport}/odds` | markets × regions, ONCE for the whole slate | **EXISTS**, full use |
| Per-event (F5 variants, props, alternates, team totals) | `GET /sports/{sport}/events/{id}/odds` | markets × regions PER EVENT | **PARTIAL** — only F5 h2h/spreads/totals and one prop key (`pitcher_strikeouts`) are even nameable in code |
| Alternates / team totals as a *featured-endpoint* addon (spec-dependent on provider tier) | untested here | unknown | **CLAIMED-BUT-ABSENT** — mentioned once in a doc as a manual/offline probe, never wired into `odds.py` |

`src/providers/odds.py:52,72,86,95` — the full list of markets this codebase
can even ask for:

```
DEFAULT_MARKETS   = ("h2h", "spreads", "totals")                                   # odds.py:52
EVENT_MARKETS     = ("h2h_1st_5_innings", "spreads_1st_5_innings",
                      "totals_1st_5_innings")                                       # odds.py:72
PROP_MARKETS      = ("pitcher_strikeouts",)                                         # odds.py:86
SUPPORTED_MARKETS = DEFAULT_MARKETS + EVENT_MARKETS + PROP_MARKETS                  # odds.py:95
```

`_validate_markets` (odds.py:767-794) rejects anything outside
`SUPPORTED_MARKETS` with a hard `OddsProviderError`. This is not a
soft limitation — it is an explicit allow-list, and it is the single
chokepoint that decides what the rest of the system can ever request.
`tests/test_providers_odds.py` pins the rejection of `player_props` as a
literal string (cited in `docs/PROBE_PROP_LISTING.md:57`), confirming this
is deliberate, not an oversight.

## 1. Full market inventory vs. what's captured — EXISTS / PARTIAL / MISSING / CLAIMED-BUT-ABSENT

Owner vision asks for the whole board: moneyline, run line, alt run lines,
totals, alt totals, team totals, margin; F5 ML/RL/total/team total, first
inning; pitcher props (Ks, outs, IP, hits, ER, walks, alternates); batter
props (hits, TB, HR, RBI, runs, walks, Ks, SB, H+R+RBI); derivatives
(race-to-X, first-to-score, inning markets); parlays (two-leg, cross-game,
SGP, F5 combos, correlated structures).

| Market | Status | Evidence |
|---|---|---|
| Moneyline (h2h) | **EXISTS** | `odds.py:52` in `DEFAULT_MARKETS`; captured every run via `snapshots.capture` (`snapshots.py:93-149`); 19,487 rows in `data/processed/odds_multibook.jsonl`, 7,324 rows in `odds_snapshots.jsonl` (measured via `wc -l`, 2026-09-03) |
| Run line (spreads) | **EXISTS** | same call, `odds.py:52`; parsed by `_parse_outcomes` "spreads" branch, `odds.py:699-710` |
| Totals (O/U) | **EXISTS** | same call, `odds.py:52`; `_parse_outcomes` "totals" branch, `odds.py:712-722` |
| Alt run lines | **CLAIMED-BUT-ABSENT** | Not in `SUPPORTED_MARKETS` (`odds.py:95`); the only evidence they were ever fetched is a one-time, out-of-band 24-credit manual probe recorded in prose (`docs/COLLECTION_POLICY.md:17-18`, "Alternate spreads/totals: 7 books, 130–160 outcome rows per event at 1 credit — the best information-per-credit on the board"). No market key, no parser, no store, no scheduled call in `odds.py`, `dense.py`, or `snapshots.py`. The policy doc itself calls this "priced and documented... to be switched on when a registered hypothesis needs them" (`COLLECTION_POLICY.md:43-45`) — i.e. explicitly not live. |
| Alt totals | **CLAIMED-BUT-ABSENT** | Same evidence and same absence as alt run lines. |
| Team totals | **MISSING** | No mention anywhere in `odds.py`, `dense.py`, `COLLECTION_POLICY.md`, or `PROBE_PROP_LISTING.md`. Not even priced by the manual probe. |
| Margin (run differential market) | **MISSING** | Not referenced in any file grepped (`odds`, `dense`, `snapshots`, `f5_store`, `prop_listing`, `prop_prices`, `COLLECTION_POLICY.md`). |
| F5 moneyline | **EXISTS** | `EVENT_MARKETS[0]` = `h2h_1st_5_innings` (`odds.py:72`); fetched every dense capture moment for approaching games via `dense._f5_close_pass` (`dense.py:458-558`); stored in `data/processed/f5_close.jsonl`, 317 rows measured |
| F5 run line / total | **PARTIAL** | The market keys exist in `EVENT_MARKETS` (`odds.py:72`) and `normalize_event` parses them (`odds.py:618,634` iterate `DEFAULT_MARKETS + EVENT_MARKETS`), so the provider CAN fetch and normalize them. But `dense._f5_close_pass` only ever requests `F5_CLOSE_MARKET = "h2h_1st_5_innings"` (`dense.py:89,521`) — F5 spreads/totals are never actually scheduled or stored anywhere in the pipeline. The 3-books-thin measurement in `COLLECTION_POLICY.md:16` ("F5 spreads/totals: 3 books — thin but priced the same") was the same one-off manual probe, not a running capture. |
| Team totals F5 | **MISSING** | Not named anywhere. |
| First inning markets | **MISSING** | No `1st_1_innings` or `1st_3_innings` key anywhere in the repo. |
| Pitcher props: strikeouts | **PARTIAL** | Listed in `PROP_MARKETS` (`odds.py:86`); a *listing-only* feasibility audit runs (`prop_listing.py`, no prices/points, 446 rows measured); a bounded *price* capture also runs, gated `PROP_PRICES=1` (`prop_prices.py`, 29 rows measured — clearly not running continuously or not long since switch-on). Both are capped at 18 credits/day, 3 games/day, 6 slots — nowhere near the whole board. |
| Pitcher props: outs, IP, hits allowed, ER, walks | **MISSING** | `PROP_MARKETS` is a one-element tuple by explicit design (`odds.py:79-86`: "WHY THE LIST IS ONE KEY LONG... Keys are added when a registered need names them, not in anticipation."). No other pitcher prop key is nameable in code. |
| Pitcher prop alternates | **MISSING** | Not nameable; same allow-list gate. |
| Batter props: hits, TB, HR, RBI, runs, walks, Ks, SB, H+R+RBI | **MISSING** | Zero batter *market* keys anywhere in `odds.py`/`dense.py`/`prop_listing.py`/`prop_prices.py`. (Note: `batter_*` hits in a repo grep are all player-performance analysis code — `src/research/matrix.py`, `src/pipeline/rebuilt.py`, `src/analysis/matchup.py` — computing historical batter-vs-pitcher stats from Statcast, entirely unrelated to odds/props. Zero overlap with the odds provider.) |
| Derivatives: race-to-X, first-to-score, inning markets | **MISSING** | Not referenced anywhere. |
| Parlays: two-leg, cross-game, SGP, F5 combos, correlated structures | **MISSING** | No parlay/SGP code found anywhere in `src/`. |
| Consensus / disagreement / best-price / staleness (market-depth analysis, not raw markets) | **EXISTS**, downstream of what IS captured | `src/analysis/oddspayload.py:156-268` (`_consensus_section`, `_books_disagree_on_favorite`, `build_market_h2h`, `build_game_odds`); operates only on h2h today since that's the only multi-book series stored (`snapshots.multibook_rows`, `snapshots.py:168-192`, h2h-only by construction: `quotes = (event.get("all_books") or {}).get("h2h") or []`, `snapshots.py:177`) |
| Every book, not just one, per market | **PARTIAL** | `normalize_event`'s `all_books` section (`odds.py:609-629`) captures every book for h2h AND spreads AND totals AND the F5 trio — the normalizer itself is market-agnostic. But `snapshots.multibook_rows` (the thing that actually persists it) hardcodes `all_books.h2h` only (`snapshots.py:177`) — spreads/totals all-book data is fetched and normalized in memory every capture and then discarded, never written anywhere. This is a one-line change away from being EXISTS for spreads/totals too, and currently is the single largest "money left on the table at zero marginal API cost" gap found in this map. |

## 2. Credits: what's spent, what's left, what the floor is

### Confirmed live state (measured, not from the stale policy doc)

`data/processed/credit_log.jsonl` — 14 rows (append-only, one per quota
read since the log module shipped in commit `c7050c6`).

```
2026-09-02T23:16:40Z  dense.run           remaining=99655  used_last=0
2026-09-03T00:01:51Z  dense.close_capture remaining=99639  used_last=0
2026-09-03T00:01:52Z  prop_listing.run    remaining=99636  used_last=0
2026-09-03T00:03:17Z  prop_prices.run     remaining=99635  used_last=0
2026-09-03T00:15:46Z  dense.run           remaining=99634  used_last=0
```

**This is a material finding, not a footnote.** `docs/COLLECTION_POLICY.md:3-4`
states the balance as "53,083 credits (2026-08-31)" and prices its entire
floor/envelope discussion off that number and a "500-credit free tier" and
"20K"/"100K" language throughout `odds.py` and `docs/ODDS_PURCHASE_BRIEF.md`.
The credit log — the system's own instrument, per-request, unfiltered — shows
**~99,634 remaining as of 2026-09-03T00:15Z, on a key that appears to be on
the 100K-credit tier** (100,000 monthly allotment is the only listed tier
that explains a balance in the high 90-thousands two days after the policy
doc's 53,083 reading; `PRICING_TIERS` in `odds.py:237-243` lists 100K/$59 and
5M/$119 as the two tiers above 20K). Two explanations are consistent with the
evidence and this map cannot distinguish them from the repo alone: (a) the
account was upgraded to 100K between 2026-08-31 and 2026-09-03, resetting or
adding balance, or (b) a monthly reset occurred and the account is already on
100K. Either way, **every "132/day envelope" and "5,000 floor" figure in
`COLLECTION_POLICY.md` was written against a ~53K balance that no longer
describes the account**, and the floor/envelope math should be re-derived
against the current tier before being trusted for planning. This is flagged
as CAPTURE NOW / VERIFY NOW: nobody appears to have looked at `credit_log.jsonl`
against the policy doc since the amendment on 2026-09-02.

### What's spent today (from code, corroborated by the log's `used_last` fields being 0 in this idle window)

- Baseline (`snapshots.capture`, 3 featured markets, 1 region): 3 credits/call.
  `dense.estimate_daily_credits` (`dense.py:136-147`) computes ~132 credits/day
  at 4 captures/hour × ~11 hours of baseball — this is the number
  `docs/ODDS_PURCHASE_BRIEF.md` and `COLLECTION_POLICY.md:5-6` both cite.
- F5 close pass: piggybacked on dense capture moments, ~1 credit/game/night
  typical, ceiling `F5_CLOSE_MAX_EVENTS = 8` events/run (`dense.py:108`),
  theoretical worst case 32/night (`dense.py:103-107`).
- Prop listing audit: 18 credits/day cap (`prop_listing.py:91`), 400-credit
  lifetime hard cap (`prop_listing.py:95`), 446 rows on disk.
- Prop prices (research collection, `PROP_PRICES=1`): same 18/day shape
  (`prop_prices.py:81`), no lifetime cap coded (only the shared floor/reserve
  checks) — 29 rows on disk, consistent with having just switched on
  (commit `c7050c6`, per the 2026-09-02 amendment in `COLLECTION_POLICY.md:158-196`).
- Rosterwatch / weather: 0 credits, free feeds.

Sum: policy's own stated approved envelope is **~132 credits/day**
(`COLLECTION_POLICY.md:4-7`), with softer layers (F5 15-40/day, prop
listing+prices 18+18=36/day capped) meant to fit inside headroom under that
number, not add to it — "total daily spend stays inside the already-approved
132" (`COLLECTION_POLICY.md:6-7`).

### The floor

`CREDIT_FLOOR = 5000` is hardcoded identically in `dense.py:62`,
`prop_listing.py:98`, and re-exported into `prop_prices.py:77`. It is an
absolute, never-worked-around floor checked via the free `/sports` endpoint
before any paid call (`dense.py:298-306`, `prop_listing.py:155-168`,
`prop_prices.py:113-126`). `PROBE_RESERVE = 5200` (`prop_listing.py:104`) is
the softer-layer yield point, 200 credits above the floor.

**These constants were sized for a ~53K-credit world and have not been
revisited for a ~99.6K balance.** They still function (the floor still
protects against going to zero), but if the account is genuinely on a
100K/month recurring tier, the floor at 5% of one month's allotment and the
132/day envelope (which would use the whole month in ~757 days, i.e. is far
under-provisioned relative to what's now available) both deserve a conscious
re-decision, not silent inheritance from the 53K-era numbers.

## 3. Cadence — what fires when

- **Baseline**: `snapshots.capture()` — one call to `fetch_odds` (3 markets,
  1 region), whole slate, run every capture moment. Persists to
  `odds_snapshots.jsonl` (legacy, 1 book/market) and `odds_multibook.jsonl`
  (every book, h2h only) from the SAME response — zero marginal credit cost
  for the multibook write (`snapshots.py:100-104,139-143`).
- **Dense window**: opens 180 minutes before any game's first pitch
  (`WINDOW_MINUTES = 180`, `dense.py:50`), 4 captures at 15-minute spacing
  per scheduled run (`INTERVAL_MINUTES=15`, `CAPTURES_PER_RUN=4`,
  `dense.py:53,57`), re-checking the window before every capture so a run
  stops itself once games go live rather than burning the rest of its budget
  on in-play prices (`dense.py:282-287`).
- **F5 close pass**: rides every dense capture moment (not just the last),
  pricing games that will start before the NEXT capture moment
  (`dense.py:67-87` explains why "one instant per hour" used to leave gaps —
  measured on the real 2026-09-01 card, riding only the close pass reached 3
  of 15 games; no single trigger phase does better than 6 of 15).
- **Close-capture pass**: one extra spend if a game is inside its final 25
  minutes when the 4×15 loop finishes (`CLOSE_WINDOW_MINUTES=25`,
  `dense.py:124,361-396`).
- **Prop listing / prop prices**: 6 slots anchored to first pitch (T-12h
  through T-30m, `prop_listing.py:75-82`), 3 games/day sampled deterministically
  (earliest/median/latest first pitch, `prop_listing.py:359-372`), resumable —
  a slot already recorded is never re-fetched (`prop_listing.py:42-44`).
- **Missed-window reporting**: `dense._missed_windows` /
  `_missed_f5_closes` (`dense.py:688-721`, `561-635`) report, never repair,
  any game that reached first pitch with no capture in its final 30 (h2h) or
  25 (F5) minutes — the honest-gap contract this whole system is built on.

## 4. The multibook store — what it actually contains (as documented, verified)

`docs/COLLECTION_POLICY.md:123-156` documents (and this map confirms by
`wc -l`/grep against the live 19,487-row store) that `odds_multibook.jsonl`
is a capture-moment log, not a pre-game-only store: 592/5,803 rows as of
2026-09-01 carried `observed_utc` after their own `commence_time` (in-play
prices, up to 2h50m late, some at |price|>1000). The reading rule lives in
`snapshots.is_pregame`/`pregame_rows` (`snapshots.py:361-397`), which every
board-building caller (`analysis/prices.boards_by_matchup`/`for_game`) must
and does go through. This is a correct, deliberate design (append-only
evidence, filter at read) — cited here because it means **raw row counts in
this store overstate genuinely pre-game observations by a measurable
amount**, which matters when sizing any credit-cost-per-observation
calculation from the store itself rather than from the call-level math above.

## 5. Books

Books actually observed in the live multibook store (measured via a python
scan of `data/processed/odds_multibook.jsonl`, 2026-09-03): `betmgm`,
`betonlineag`, `betrivers`, `betus`, `bovada`, `draftkings`, `fanatics`,
`fanduel`, `lowvig`, `mybookieag`, `williamhill_us` — **11 books**, for the
h2h market specifically (the only market persisted at all-books resolution
today). `COLLECTION_POLICY.md:14-16` separately measured, via the one-off
manual probe, 5 books forward / 12 books historically for F5 h2h, and 7
books for F5 spreads/totals and for pitcher_strikeouts
(`docs/PROBE_PROP_LISTING.md:344-350`, which found **7** books listing
`pitcher_strikeouts`, materially more than the "3-4" the earlier 24-credit
probe recorded — the policy doc's own number for prop coverage is already
stale by the project's later, better measurement, and nothing has gone back
to correct `COLLECTION_POLICY.md:19-20`).

## 6. `docs/MARKET_DEPTH*.md` — does not exist

`ls docs/ | grep -i market_depth` returned nothing. No such document exists
in this repo as of 2026-09-03. `PROBE_PROP_LISTING.md` and
`COLLECTION_POLICY.md` are the two documents that actually carry
market-depth-adjacent content (book counts, listing coverage), and both are
cited throughout this map. Any prior reference to a "market depth" document
elsewhere in project planning should be treated as CLAIMED-BUT-ABSENT until
one is written.

## 7. Credit budget table: what it would cost to capture the ENTIRE MLB board

Assumptions, stated because none of this is measured for markets the code
cannot yet request: 15-game slate (a normal full MLB day), 1 region (`us`),
hourly baseline for 11 hours of live baseball, dense window adds captures
only in the ~3-hour pre-first-pitch band per cluster of games (using the
current dense shape as the multiplier). Featured-endpoint markets bill
FLAT per call regardless of slate size; per-event markets bill PER EVENT —
this is the entire reason the cost curves below diverge so sharply, and it
is already explained in `odds.py:54-72`. Costs for markets not in
`SUPPORTED_MARKETS` (alt spreads/totals, team totals, pitcher props beyond
Ks, all batter props) are **not verified by this codebase** — the only
measurement is the one-off manual 24-credit probe for alt spreads/totals and
F5 spreads/totals (`COLLECTION_POLICY.md:12-22`), and this repo's own
`PROBE_PROP_LISTING.md:52-76` explicitly states "the repo contains no
measured cost for a player-prop fetch" beyond `pitcher_strikeouts`.
Every "assumed" row below inherits the SAME per-market-per-event billing
shape the API confirms for `h2h_1st_5_innings`/`spreads_1st_5_innings`/
`totals_1st_5_innings`/`pitcher_strikeouts` (1 credit/market/region/event) —
this is the API's stated billing model for its per-event endpoint, not
specific to any one market key, so extrapolating the same rate to unmeasured
per-event markets is a reasonable assumption, not a fabricated number, but it
is still unmeasured and should be verified with a 1-credit test call before
being budgeted for real (`PROBE_PROP_LISTING.md:77-98` did exactly this for
`pitcher_strikeouts` and it is the template to repeat for every new key).

Per-call costs (whole 15-game slate, one snapshot instant):

| Tier | Markets added | Endpoint | Cost/call (15 events) | Status |
|---|---|---|---|---|
| 0 — current baseline | h2h, spreads, totals | featured | 3 credits (flat) | EXISTS |
| 1 — F5 full triple, whole slate (not just approaching games) | h2h_1st_5, spreads_1st_5, totals_1st_5 | per-event | 3 × 15 = 45 credits | PARTIAL (only h2h piggybacked today) |
| 2 — alternates | alternate_spreads, alternate_totals | per-event (assumed) | 2 × 15 = 30 credits | CLAIMED-BUT-ABSENT |
| 3 — team totals | team_totals | per-event (assumed) | 1 × 15 = 15 credits | MISSING |
| 4 — pitcher props (5 types: Ks, outs, hits allowed, ER, walks) | 5 keys | per-event (assumed; only Ks is measured) | 5 × 15 = 75 credits | 1/5 PARTIAL, 4/5 MISSING |
| 5 — batter props (8 types: hits, TB, HR, RBI, runs, walks, Ks, SB) | 8 keys | per-event (assumed) | 8 × 15 = 120 credits | MISSING |
| 6 — first-inning markets (h2h/spread/total × 1st inning) | 3 keys | per-event (assumed) | 3 × 15 = 45 credits | MISSING |

**Full-board single snapshot, all tiers combined: ~3 + 45 + 30 + 15 + 75 + 120
+ 45 = 333 credits per instant** (unverified tiers dominate this number).

### Daily cost to run the FULL board on two cadences

- **Hourly, 11 hours of baseball** (whole slate every hour, not just
  approaching games): 333 × 11 = **3,663 credits/day**.
- **Dense (every 15 min) for the 3-hour pre-first-pitch window only**, on top
  of hourly baseline for the rest of the day — approximating with the
  existing dense shape (4 captures/hour × the per-event tiers, since a dense
  moment only needs to price games actually approaching, not the whole
  slate at every instant): assume ~15 games cluster into ~3 effective dense
  hours across a slate (matches the measured "12 of 15 games start
  22:38-22:45" pattern in `dense.py:76-79`), so dense-window spend for tiers
  1-6 ≈ (45+30+15+75+120+45) × 4 captures/hour × 3 hours ≈ **3,960 credits**
  for the dense window alone, PLUS the hourly-baseline 3,663/day above minus
  double-counting the 3 dense hours already inside it (hourly tier-0 baseline
  for those 3 hours is 3×3=9 credits, negligible against the per-event
  tiers) ⇒ **full board, hourly-elsewhere + dense-near-first-pitch ≈
  3,663 + 3,960 − (already counted hourly-only tiers during the dense window)
  ≈ 7,000-7,600 credits/day**, dominated almost entirely by the per-event
  prop tiers (4, 5) because those bill per event and per market
  simultaneously — this is exactly the "cost shape is completely different"
  warning `odds.py:58-71` gives for F5, generalized to every per-event
  market.

### Monthly cost at that cadence

7,000-7,600/day × 30 ≈ **210,000-228,000 credits/month**, which exceeds
even the 100K tier the account appears to be on now and would require the
5M tier ($119/month, `odds.py:241`) for comfortable headroom — the 5M tier's
5,000,000 credits/month is ~22x this full-board estimate, so 5M is the
right tier to hold in reserve for "capture everything" mode, not a plan
that needs frequent top-ups.

### Where the real savings are, if the full board isn't worth 5M/month

1. **Fetch per-event markets only for games actually approaching** (the
   existing dense-piggyback pattern, `dense.py:67-87`), never for the whole
   slate on an hourly cadence. This alone is most of the difference between
   the ~7,000/day full-hourly estimate and something in the low hundreds.
2. **Persist the all-books spreads/totals/F5 data that's already being
   fetched and normalized for free** (Section 1's last row) before spending
   a single new credit on alternates or props — this is credits already
   spent, discarded today.
3. **Verify, don't assume, every new per-event market's cost** with the
   same 1-credit gate `PROBE_PROP_LISTING.md` used for `pitcher_strikeouts`
   (§1 of that doc) before writing it into a budget anyone will actually
   spend against.

## 8. Data that becomes unrecoverable if not captured now

- **Line movement and closing prices for every market not yet captured**
  (alt run lines, alt totals, team totals, F5 spreads/totals in practice,
  every prop beyond Ks listing/partial pricing, first-inning markets, every
  batter prop). `snapshots.py:1-26`'s own thesis — "there is no free source
  of what was this price four hours before first pitch... either you were
  recording at the time or that information is gone permanently" — applies
  identically to every market this map found MISSING or CLAIMED-BUT-ABSENT.
  Every day the live 2026 season plays without these captures running is a
  day of forward evidence for those markets that cannot be bought back at
  any price, per the owner's own "capture now, research later" principle
  (`COLLECTION_POLICY.md:160-162`, citing `docs/MASTER_PLAN.md` Sec.1 claim 3).
- **The all-books spreads/totals/F5 boards** — normalized in memory on every
  single capture today (`odds.py:609-629` iterates `DEFAULT_MARKETS +
  EVENT_MARKETS` for `all_books`) and then thrown away because
  `snapshots.multibook_rows` only persists `all_books.h2h`
  (`snapshots.py:177`). This is the single highest-leverage, literally
  zero-marginal-credit capture gap in the whole subsystem: the API call is
  already being made and paid for.
- **Prop repricing evidence for Falsifier 1** (`PROBE_PROP_LISTING.md:36`,
  `242`) — whether a book's `last_update` for `pitcher_strikeouts` moves
  after the lineup posts. The design itself flags S6 (T-30m, the slot that
  answers this) as narrower than the hourly capture cadence and roughly half
  of it goes unobserved by construction (`PROBE_PROP_LISTING.md:370-379`).
  That's a live, ongoing evidence loss on the ONE prop market currently
  measured at all.
- **Book counts for props/alternates as currently measured are already
  stale inside this project's own history**: the 24-credit probe's "3-4
  books" for pitcher_strikeouts (`COLLECTION_POLICY.md:19-20`) was
  superseded by the listing audit's measured 7 books
  (`PROBE_PROP_LISTING.md:348-350`) five days later, and nothing updated the
  policy doc. Coverage facts drift and nobody owns re-measuring them.
- **The credit-balance/tier mismatch in Section 2** is itself capture-now
  information: if the account tier changed (53K → ~99.6K balance in 3 days),
  the reason (upgrade vs. reset) is knowable today from the-odds-api.com
  account dashboard or billing history and will not be reconstructable from
  this repo's evidence alone once more billing cycles pass.

## 9. BOOST vs REPLACE, per component

- **`src/providers/odds.py` — BOOST.** The transport, error handling,
  historical-vs-live billing distinction, and per-event vs featured
  endpoint split are all correct and well-tested (794 lines, extensive
  docstrings explaining real production incidents — e.g. the dropped-connection
  fix that saved a 30,000-credit run, `odds.py:390-397`). The only change
  needed is EXTENDING `SUPPORTED_MARKETS`/`EVENT_MARKETS`/`PROP_MARKETS` as
  each new market is registered and verified — the architecture already
  supports this cleanly (`_validate_markets`'s `allow_event_markets` flag
  exists precisely for this). No reason to replace any of it.
- **`src/pipeline/dense.py` — BOOST.** The capture-moment/lookahead/budget/
  seen-set machinery for F5 is exactly the pattern needed to extend to any
  new per-event market (alternates, props, first-inning) without a full
  rewrite — `_f5_moment`/`_f5_close_pass` are already fairly generic over
  "one market, one event-list, one budget." Generalizing them to take a
  market list rather than hardcoding `F5_CLOSE_MARKET` is a natural
  extension, not a redesign.
- **`src/pipeline/snapshots.py` — BOOST, with one concrete fix identified.**
  `multibook_rows` should persist `all_books` for spreads/totals/F5 the same
  way it does for h2h (Section 8, bullet 2) — small, in-place change, zero
  new API cost, meaningfully expands what's recoverable. Everything else
  (append-only design, `is_pregame` filtering, `game_key` canonicalization)
  is solid and should not be touched.
- **`src/pipeline/prop_listing.py` / `prop_prices.py` — BOOST, cautiously.**
  The self-auditing marker-row pattern, shared-slot-grid reuse, and
  escalate-don't-silently-fail design are all worth keeping and reusing for
  every new prop market. But both are explicitly scoped to ONE market key
  each and were approved narrowly (feasibility vs. research collection
  distinction, `COLLECTION_POLICY.md:49-101`). Extending to new prop/batter
  markets means writing new, similarly narrow approvals per market — not
  widening these two modules' scope by editing `MARKET`/`PROP_MARKETS` without
  a fresh registration, which the project's own governance explicitly
  forbids ("Keys are added when a registered need names them, not in
  anticipation," `odds.py:84-85`).
- **`src/pipeline/creditlog.py` — BOOST.** Correct, minimal, fails safe. The
  one gap: nothing currently reconciles this log against
  `docs/COLLECTION_POLICY.md`'s stated balance/tier assumptions (Section 2)
  — a small script or CLI command comparing `creditlog.latest()` against the
  policy doc's stated floor/envelope would close that drift automatically
  instead of relying on someone noticing it, as this map just did.
- **Alternates / team totals / batter props / derivatives / parlays as a
  whole — this is new build, not boost-or-replace of anything existing.**
  There is nothing to replace because nothing exists. The right shape to
  build it in is a generalization of the F5/prop pattern already proven
  twice (dense.py's F5 pass, prop_listing.py/prop_prices.py's prop pass),
  not a third bespoke module per market family.

## 10. Key numbers (for quick reference)

- Balance now: **~99,634 credits remaining** (measured 2026-09-03T00:15:46Z,
  `data/processed/credit_log.jsonl` last row).
- Policy doc's balance: 53,083 (2026-08-31) — **stale by ~46,551 credits.**
- Absolute floor: 5,000 (`dense.py:62`, `prop_listing.py:98`).
- Probe reserve: 5,200 (`prop_listing.py:104`).
- Approved daily envelope: ~132 credits/day, all layers combined
  (`COLLECTION_POLICY.md:4-7`).
- Featured-endpoint call cost: 3 credits (h2h+spreads+totals, flat,
  any slate size).
- F5 close pass: ~1 credit/game/night typical, 8-event ceiling per run,
  32/night theoretical worst case.
- Prop listing: 18 credits/day cap, 400 lifetime cap, 446 rows on disk.
- Prop prices: 18 credits/day cap (shared shape), no lifetime cap coded,
  29 rows on disk.
- Books observed, h2h (persisted, all-books): 11 —
  betmgm, betonlineag, betrivers, betus, bovada, draftkings, fanatics,
  fanduel, lowvig, mybookieag, williamhill_us.
- Books observed, pitcher_strikeouts (measured once): 7 —
  fanduel, fanatics, bovada, betonlineag, betmgm, draftkings, betrivers.
- Full-board estimate (all markets in the owner's vision, hourly + dense):
  **~7,000-7,600 credits/day, ~210,000-228,000/month** — needs the 5M
  ($119/month) tier for headroom; unverified for every market beyond h2h/
  spreads/totals/F5-h2h/pitcher_strikeouts, and should be gated behind
  1-credit verification calls per new market key before committing real
  budget (see §7).
