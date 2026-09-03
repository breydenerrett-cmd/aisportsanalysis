# SGP / parlay-relevant capture (docs-only, owner decision 4)

Written 2026-09-03. Fetched 2026-09-03 from
https://the-odds-api.com/sports-odds-data/betting-markets.html and
https://the-odds-api.com/#pricing.

## 1. What the vendor exposes that is parlay-relevant

No dedicated SGP/parlay endpoint or market key exists on The Odds API.
Confirmed by direct fetch of the vendor's markets page (2026-09-03): it
lists no `sgp`/`parlay` key and no parlay pricing product. This matches
`src/board/ids.py`'s `same_game_parlay` status of `BLOCKED`.

What *is* available, per-book, that lets us build correlated leg sets
ourselves: alternate lines (`alternate_spreads*`, `alternate_totals*` incl.
first-five/period variants), team totals (`totals_1st_1/3/5/7_innings` and
their alternates), first-five markets (`h2h_1st_5_innings`,
`spreads_1st_5_innings`, `totals_1st_5_innings` — already `PROBE` in
`MARKET_CATALOGUE`), and player props (batter/pitcher, plus `_alternate`
variants) — all confirmed live market keys on the vendor page. Every one of
these is priced independently per book; there is no joint/correlated price
for any combination.

**Credit cost**: per `src/providers/odds.py:203-225`, the featured `/odds`
endpoint bills **1 credit per market x per region**, once for the whole
slate (not per event). Per-event endpoints (F5, props) bill markets x
regions **per event**. The vendor pricing page itself does not publish this
per-request formula; the number above is the value already measured and
coded in this repo (`estimate_credits`), not a new vendor claim.

## 2. What cannot be captured from this vendor

Book-specific SGP correlation pricing (the discount/markup a book applies
to a specific same-game leg combination) is not exposed by The Odds API at
all — confirmed by the fetch in §1, not merely absent from this repo's
integration. No free or cheap alternative source is known to this project;
none has been probed or documented anywhere in the repo. **Stated plainly:
there is no known source, free or paid, for actual book SGP prices.** This
is a permanent capture gap, not a probe-later item.

## 3. Scientific framing: testing parlay value honestly

We cannot observe book SGP prices, so we cannot directly test "is the
book's SGP price good." What we *can* test is a weaker, still useful,
question: **is the assumption of leg independence (used to price a
hypothetical same-game combo from individual leg prices) wrong, and by how
much, in the direction that would make combo bets worse than naive pricing
implies?**

Required data, all obtainable from existing/near-existing capture:
- Independent leg prices for each candidate market, per book, at a fixed
  point before first pitch (already captured for `h2h`/`totals`; `PROBE`
  for F5 and team totals; `DECLARED`/not-yet-live for props).
- Settled outcomes for every leg (existing settlement adapters per
  `ARCHITECTURE_BETTING_ENGINE.md` §2/§6, extended per market as each
  market moves off `PROBE`/`DECLARED`).
- The **realised joint outcome** for each same-game leg pair/set (derived
  from the settled outcomes above — no separate capture needed once both
  legs are settled).

From these: compute the empirical joint frequency of each correlated leg
pair (e.g., "home team wins" AND "game total under X") across many games,
compare it to the product of the marginals implied by leg prices
(devigged), and the gap is the measured correlation the book would be
pricing into an SGP. This never touches an actual SGP price — it only says
whether "treat legs as independent" is a good or bad approximation for a
given pair, which is the honest, falsifiable version of "is this parlay
family worth building toward."

**Sample sizes**: correlation estimates on binary/near-binary outcomes need
enough joint events per candidate pair to bound the estimate meaningfully.
A rule-of-thumb minimum for detecting a moderate correlation (say a joint
frequency 5-10 percentage points off the independence-implied value) at
reasonable confidence is on the order of several hundred games per pair —
a single MLB season (~2,430 games) provides that for game-level pairs
(team result x game total, team result x team total) but is thin for
narrower pairs (e.g., specific batter prop x game total), which will need
multiple seasons or coarser groupings before any claim is trustworthy. No
specific n has been computed against this project's actual variance; this
is a planning-order-of-magnitude statement, not a computed power analysis.

**Multiplicity**: `MARKET_CATALOGUE`'s `correlation_group` column already
enumerates the plausible pair/group universe (`game_outcome`,
`game_total`, `first_five_outcome`, `first_five_total`, `first_inning`,
`pitcher_line`, `batter_line`). Testing every pair across every group
against every other group multiplies comparisons fast; per
`docs/planning/synthesis-judge.md`'s CLUSTER_SPEC convention, correlation
claims should be tested only within a pre-registered, named cluster (e.g.
"same-game team-result x total" as one hypothesis), with a fixed number of
clusters declared before looking at the data, and a multiple-comparison
correction (Bonferroni or an FDR method) applied across that declared set —
not across every pair the catalogue could technically produce.

## 4. Capture proposal

Fits inside the existing `capture_families.json` structure and current
credit envelope (~132 credits/day per `VENDOR_HISTORICAL_DATA_PACKET.md`
§7). Markets and cadence:

- **Team totals** (`totals_1st_1/3/5/7_innings` — already `PROBE` in
  `MARKET_CATALOGUE`, family `team_totals` already stubbed unmeasured in
  `capture_families.json`): capture on the existing featured-endpoint
  cadence alongside `h2h`/`totals`/`spreads`. Additive cost is 1
  credit/region per snapshot on the slate-level endpoint (same billing
  shape as `featured`), i.e. roughly the same order as the existing
  `featured` family's per-snapshot cost, scaled by however many additional
  markets are turned on.
- **Alternate lines** (`alternates` family, already `measured: true` at 1
  credit/event — reuse as-is; no market-list change needed since alternates
  are already captured).
- **First-five markets** (`f5_trio`, already `PROBE`/unmeasured in both
  files — no change proposed here beyond what those files already stage).
- **Player props** (`pitcher_props`/`batter_props`, unchanged — out of
  scope for this doc beyond noting they are already correlation-group
  members via `pitcher_line`/`batter_line`).

**Estimated credits/day**: unmeasured for team totals specifically —
marked `PROBE_REQUIRED` below rather than guessed, per this repo's
existing convention (`can_spend` refuses unmeasured families). Order-of-
magnitude: if team totals adds 1 market to the existing 3-market featured
call, that is roughly a 33% increase over the `featured` family's current
per-snapshot cost, before any real probe.

**Config edit made** (`config/capture_families.json`): the existing
`parlay_sgp` family entry's `source` field is updated to record the
2026-09-03 vendor-page confirmation that no SGP/parlay endpoint exists (see
diff below) — no cost figure is invented, `measured` stays `false` and
`credits_per_event` stays `null`/PROBE_REQUIRED, consistent with the
"never hand-edit to a guessed number" rule already stated in that file's
`_note`.

**MARKET_CATALOGUE correlation groups relevant to this proposal** (listed
here for the owner/implementer; `src/board/ids.py` itself is not edited):
`game_outcome` (h2h, spreads, alternate spreads), `game_total` (totals,
alternate totals, team totals), `first_five_outcome`, `first_five_total`,
`first_inning`, `pitcher_line`, `batter_line`. Team totals joining
`game_total` (already the case in the current catalogue) means the
independence-vs-correlation test in §3 for "team total under X" against
"game total under Y" is already representable without any catalogue change.

## 5. Open owner decisions

None required beyond decision 4 itself (already made: capture SGP/parlay-
relevant markets now where available and economical). Before any team-
totals capture goes live, a `PROBE_REQUIRED` credit measurement (per the
existing `budget --probe` mechanism) is needed — that is an implementation
step, not a decision this doc is blocked on.
