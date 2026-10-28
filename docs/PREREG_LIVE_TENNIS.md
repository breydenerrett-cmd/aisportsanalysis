# Pre-registration: does a serve-hold Markov model beat the live tennis match-winner board at set starts?

**Rule id:** `LIVE_TENNIS_V1` (model id `MARKOV_V1`)
**Registry id:** `LIVE_TENNIS:setstart_markov_gap_clv:match_winner`
**Family:** `LIVE_TENNIS` (one hypothesis; one decisive test, section 8)
**Frozen:** 2026-10-28.
**REGISTERED_UTC:** the committer time of the commit that adds this file (read it
with `git log --format=%cI -- docs/PREREG_LIVE_TENNIS.md`). The registry row is
appended in the same commit; its `note` carries the sha256 of this file with line
endings normalised to LF. **Freeze check:** recompute that sha256 and compare it to
the note before reading any result. A mismatch voids the registration.

**Status: PAPER TEST. No real money, ever, from this test.** There is no
bet-placement code anywhere in it, it shows nothing to a customer, it feeds no card
and it licenses no promotion. A result here is a research finding about one
question; it is never a pick, an edge claim or a reason to stake anything.

**Where this came from.** Owner, 2026-10-28: there is "so much money to be made"
in live tennis betting. The prior written down before any data (section 2) is that
the owner is probably wrong, because books price live tennis point by point with
exactly the model tested here and the edge that does exist in that market is
latency (courtsiding), which this project does not have. The owner chose to run a
paper test to find out. This document is that test, fixed in advance.

---

## 0. What exists before this registration, stated so a reader can check it

- **No harness exists yet.** `src/research/live_tennis/`, its CLI entry
  (`python -m src.cli research live-tennis capture|grade|report`) and
  `tests/test_live_tennis_*.py` are written AFTER this commit. No model price, no
  closing-line value, no gap and no outcome has been computed by this study on any
  row. Nothing has been run. (Section 13 lists the files and the check that keeps
  the code's constants equal to the table in section 12.)
- **Prior evidence read before writing, in full:**
  - `docs/API_TENNIS_TRIAL_RESULTS.md` (2026-09-17, SKIP): the only vendor found
    with a live set-level market and a suspension flag failed four of five checks.
    Median 54.0 s and worst 89.7 s from a trigger to the first unsuspended updated
    price, and 104 of 638 checked moments showed a price while the market was
    suspended. Nothing is paid to API-Tennis and this study does not use it.
  - `docs/TENNIS_FEED_DECISION_2026-09-15.md`: The Odds API carries tennis
    **match winner only**. There is no set-winner market and no suspension flag, and
    its in-play prices refresh about every 40 seconds (vendor page as recorded
    there). So the owner's exact bet, a set or next-set winner, has no reachable
    price source, and this test's only bettable contract is the **match winner**.
  - `docs/SNIPE_SYSTEM.md` and `docs/LIVE_BETTING_SYSTEM.md` (design; the live
    pipeline there has never produced evidence).
  - `docs/API_TENNIS_TRIAL_RESULTS.md` and `src/providers/espn_tennis_results.py`
    for the free ESPN tennis scoreboard (statuses, per-set `linescores`).
- **What was looked at while designing it, structure and counts only:**
  - `data/processed/odds_multibook.jsonl`, tennis rows only, `observed_utc`
    2026-10-25T03:12Z to 2026-10-28T15:41Z (the all-sports capture's pre-game and
    30-minute in-play snapshots): 13,820 tennis rows, 1,146 flagged `in_play`,
    across 4 tournament keys, 184 distinct in-play (capture, event) boards, and 14 and
    21 distinct in-play matches on the two full UTC days (1 and 11 on the two partial
    ones), a floor because the cadence is 30 minutes.
    Boards held 5 / 6 / 6 / 6 / 8 books (p10 / p25 / p50 / p75 / p90). Median-book
    two-way overround per board (sum of raw implied probabilities) p10 / p25 / p50 /
    p75 / p90 = 1.0477 / 1.0512 / 1.0559 / 1.0587 / 1.0608. Sum of the board-average raw
    implied probabilities, median 1.0561. Sum of the BEST raw implied probability on
    each side, p10 / p25 / p50 / p75 / p90 = 0.9226 / 0.9753 / 1.0000 / 1.0194 /
    1.0261: **about a quarter of boards offered a combination of best prices summing
    to 0.975 or less, which cannot be a real market, so some quote on the board was
    stale.** Range across books of the de-vigged home probability on one board,
    p10 / p25 / p50 / p75 / p90 = 2.1 / 3.1 / 4.9 / 7.5 / 12.8 points. Age of a
    book's `last_update` at observation, over the 1,146 in-play rows, p10 / p25 /
    p50 / p75 / p90 / p99 = 3 / 13 / 31 / 74 / 321 / 831 seconds. These numbers
    exist to size the design (sections 5, 6, 9). No de-vigged price was compared to
    any model, nothing was graded, and no outcome column was read.
  - The live ESPN ATP and WTA scoreboard for 2026-10-28: statuses seen
    `STATUS_FINAL / SCHEDULED / IN_PROGRESS / WALKOVER / RETIRED`; an in-progress
    match carries per-set games in `linescores` (the in-progress set included) and a
    `possession` flag on one competitor. 86 ATP and 211 WTA singles matches on the
    day's draws (whole draws, every round), of which 2 and 3 were in progress when
    read. Not every ESPN-listed event is priced by The Odds API (WTA 125 and
    similar events are not), so the usable population is the intersection.
  - `data/processed/credit_log.jsonl`: end-of-day balances 2026-10-13..10-28 fell
    from 97,133 to 85,489 of a 100,000 monthly allotment.
  **No row dated 2026-01-01..2026-08-27 was read; no 2025 row was read; no outcome
  of any match was read.** `sealed_untouched` is true.

## 1. Evidence rules this registration obeys

- Forward capture only. The first captured set start is the first observation.
  Nothing backfilled, nothing replayed, no historical in-play data exists in this
  stack to replay.
- Pre-registration before inference: one rule, fixed constants (section 12), one
  decisive test (section 8). The code refuses to run if its constants differ from
  the fingerprint written into the ledger's first row (section 13), so a threshold
  cannot be edited after the fact without leaving a visible break.
- Every loser is published: every decision point, bet or not, every exclusion and
  every unpriced attempt is a ledger row and is counted in the report.
- Line-shopping value is PRICE IMPROVEMENT, never EV or edge. The decisive
  closing-line value is measured at the board AVERAGE price, never the best price
  (section 7). The best-price version is reported, labelled as price improvement.
- No effect statistic is shown before the floors in section 8 are met. Below them
  the report prints counts, coverage and credits only. There is no peeking.
- No threshold, rule or population here may be edited after this commit. A
  different specification is a new registration.

## 2. Hypothesis, fixed, and the honest prior

> At the start of a set after the first (the previous set just completed, the new
> set at 0-0), the **match-winner** side on which a standard serve-hold Markov
> model, seeded only from the pre-match market and the set score, prices the match
> at least 3.0 probability points better than the best fresh live price, **beats
> the live board's own later price**: a bet at the board-average price at that
> decision point has positive closing-line value against the de-vigged live
> consensus ten to twenty-five minutes later (M2 > 0, interval above zero, with the
> consensus also drifting toward the bet, M1 > 0).

**Prior, written before any data.** The expected result is that M2 at the average
price is negative, by roughly the half-overround a bettor pays: from the stored
boards, the average-price overround is about 1.056, so about **2.8 points per side**
(section 0). A PASS would need the live consensus to move toward the model's side
by more than that within the window. The books' own live prices are made by this
class of model with better inputs (player-specific serve statistics, point-level
data), so we expect no gap that survives. The remaining candidate for a real edge
in live tennis is **latency**: seeing the score before the book reprices. That is
not testable here, because our feed is late by construction (The Odds API refreshes
about every 40 s and we poll scores about every 60 s), so this test **cannot
detect, and says nothing about, courtsiding**. A FAIL does not mean live tennis
cannot be beaten; it means this model, at these decision points, with these feeds,
cannot beat this board.

## 3. Population and unit

- **Matches.** Singles matches on The Odds API sport keys beginning `tennis_` that
  are active, that The Odds API prices (a match-winner board exists for the event)
  and that the free ESPN ATP or WTA scoreboard lists. The ESPN match and the Odds
  API event are paired by the repo's existing matcher
  (`src/pipeline/allsports_free_results.match_tennis`: both player names, a
  start-time window, exactly one fit). Unpaired or ambiguously paired events are
  excluded and counted (`UNMATCHED`). Doubles are never included.
- **Tour and format.** The tour is read from the key (`tennis_atp_*` ATP,
  `tennis_wta_*` WTA). Sets to win are 3 for an ATP key naming a Grand Slam
  (`wimbledon`, `french_open`, `us_open`, `aus_open`) and 2 for everything else. A
  match whose live set count contradicts that format is excluded
  (`FORMAT_CONTRADICTION`).
- **Unit, the decision point.** One decision point (DP) is one (match, set number
  N) with **N >= 2** at which the previous set has just completed and the new set
  is at 0-0 (section 6). Set 1 is not a decision point: at 0-0 in set 1 the model's
  price IS the pre-match market by construction, so there is nothing to compare.
  The **current-set winner** is also priced by the model at every decision point and
  written to the ledger, but it has no book price and is never bet or used in
  closing-line value; it is checked only against the set's own result (section 7,
  descriptive).
- **Unit of inference.** One paper bet. A DP produces **at most one bet**, or none.
  Bets from one match share a result process, so the interval is clustered by match
  (section 8).

## 4. The model, `MARKOV_V1`, fixed

A standard model, with no player-specific inputs beyond the pre-match market and
nothing fitted on any data in this study.

1. **Points.** The server wins each service point with probability `p`, the same
   for every point and independent of all others. Player A is the **home** team as
   The Odds API names it, player B the away team. A's service-point probability is
   `p_A = s + d`, B's is `p_B = s - d`, where `s` is a fixed tour constant and `d`
   a skill gap solved below.
2. **Game.** `G(p) = p^4 (1 + 4q + 10 q^2) + 20 p^3 q^3 * p^2 / (p^2 + q^2)`, with
   `q = 1 - p`. (`G(0.5) = 0.5`, `G(0.6) = 0.7357`, `G(0.7) = 0.9008`.)
3. **Set.** Games alternate server; the first server of a set serves games 1, 3,
   5, ... A set is won at 6 games with a lead of 2, at 7-5, or by winning a
   tiebreak at 6-6. The tiebreak is to 7, win by 2; its first server serves one
   point, then service alternates every two points. The tiebreak counts as one game
   for the serving order. The set DP returns, for each first server, the
   probabilities of (winner, total games odd or even), because the next set's first
   server is the same player if the set had an even number of games and the other
   player if odd.
4. **Match.** Dynamic programme over (sets won by A, sets won by B, first server of
   the current set), best of 3 or 5 per section 3.
5. **Unknown server.** Neither the feed nor the market says who serves first, so
   every model price **averages the two possible first servers 50/50**. The ESPN
   `possession` flag is recorded in the ledger and is never used by the rule.
6. **Seeding from the market.** `p0` is the de-vigged (proportional,
   `src.core.odds.devig_two_way`) consensus (mean over books) probability that the
   home player wins the match from the latest **admissible pre-match board** (section
   5). `d` is the unique value in `[-0.15, +0.15]` at which the model's pre-match
   match-win probability for the home player (set 1 start, first server averaged)
   equals `p0`, found by bisection; a `p0` outside what that range can produce
   excludes the DP (`MODEL_OUT_OF_RANGE`). The constants `s` are in section 12.
7. **Prices.** At a DP the model's match-win probability for each side is the
   match DP started from the sets already won with the new set at 0-0, and its
   current-set-winner probability is the set DP from 0-0, both with the first server
   averaged. Nothing observed in the match other than the sets-won score is used.
8. **Simplifications, disclosed.** Final sets are modelled with a 7-point tiebreak at
   6-6, so advantage final sets, 10-point final-set tiebreaks and the Slam variants
   are not modelled. A single serve level `s` per tour ignores surface. Games already
   played in earlier sets, and who held, carry no information in this model.

## 5. Data plan, and what the price board means

**Sources, all already in the stack, nothing new bought.**

- **Live score state:** the free, keyless ESPN ATP and WTA scoreboard JSON
  (`src/providers/espn_tennis_results.py`, `parse_scoreboard`). Polled about every 60
  seconds while a paired match is in progress or scheduled to start within 90
  minutes, every 300 seconds otherwise.
- **Prices:** The Odds API `sports/<tennis key>/odds`, region `us`, market `h2h`
  only. One call returns the whole key (every live and upcoming match in that
  tournament) and bills **1 credit**. Event listings (`sports/<key>/events`) and the
  sports list are free.
- **Settlement:** the same ESPN scoreboard, through the repo's existing
  `espn_tennis_results.settlement` rule (a retirement after at least one completed
  set goes to the player who advanced; before a set completes, a walkover and a
  cancellation are void).

**A quote is FRESH** only if the book's own `last_update` is **at or after `t_c`**,
the moment OUR poll first saw the previous set completed. That is strictly after the
set ended, so a fresh quote cannot be a price from before the set's result. A
quote with an earlier `last_update` is stale: it is dropped from the board and
counted. This rule is stricter than needed on purpose. The stored boards show the
failure it prevents: a stale quote that predates a set result sits on the side that
just WON the set, so betting it and then measuring against any later price produces a
positive closing-line value that no real bettor could have captured (a phantom bet).
A board needs **at least 3 fresh books** with both sides priced.

**Admissible pre-match board.** A snapshot of the key taken while the paired ESPN
match was `pre` (not started) at the poll immediately BEFORE and the poll immediately
AFTER the paid call. `p0` is taken from the latest such snapshot, with at least 3
books priced on both sides. None means the DP is excluded (`NO_PREMATCH_PRICE`).

**Score bracket.** Every decision snapshot is bracketed by two free score polls, one
before the paid call and one after. The DP is valid only if both polls show the same
sets-won score and the new set at 0-0 (`SCORE_MOVED` otherwise). This is what makes
"the price and the score describe the same instant" an observed fact instead of an
assumption.

## 6. Decision points and the selection rule, fixed

**Arming.** A match is **armed** at the first poll showing: status in progress,
`c` completed sets with `1 <= c`, the match not decided (neither player has the sets
needed), and the current set at 0-0 or not yet listed. `N = c + 1`. The poll time is
`t_c`. One DP per (event, N), ever.

**Attempts.** A decision snapshot is taken at the first tick after arming, and once
more at least 45 seconds later if the first board was thin. At most **2 attempts**,
and none later than **240 seconds after `t_c`**. An attempt costs 1 credit and is
shared by every armed DP of the same tournament key.

**Evaluation of an attempt, in this order; the first failure is the recorded
reason.** Checks 1 and 2 need no new price, so a DP that fails them **costs no
credit**; check 3 is made before the paid call and checks 4 to 6 after it.

1. `NO_PREMATCH_PRICE` (section 5) or `MODEL_OUT_OF_RANGE` (section 4.6), or at
   arming `UNMATCHED` / `FORMAT_CONTRADICTION` (section 3).
2. the same match was already decided for this (event, N): never a second DP.
3. credit guard refuses: `CREDIT_REFUSED` (section 9).
4. `SCORE_MOVED` (section 5, the bracket).
5. fewer than 3 fresh books: `THIN_BOARD` (retried if an attempt remains).
6. the **best fresh raw implied probability on each side sums below 0.99**:
   `INCONSISTENT_BOARD`. A board offering more than a 1% arbitrage across books has
   a stale quote on it by construction.

**The bet.** For each side, the **gap** is `100 * (p_model(side) - implied(best fresh
price on that side))` in probability points, where `implied` is the raw
(vig-included) implied probability of the best, highest-decimal-odds, fresh price.
The side with the larger gap is the candidate. If its gap is **at least 3.0 points**
the DP produces a **BET** on that side, otherwise `NO_BET` (`BELOW_THRESHOLD`). Ties
go to the home side. One paper bet, flat 1 unit, never anything else.

**Why 3.0 and not another number.** The board-average price carries about 2.8 points
of overround per side (section 0). A model gap of at least that size against the BEST
price is the smallest claim that, if true, would pay the vig a bettor takes at the
average price. It is fixed here from that arithmetic and from nothing the outcome
could have told us, and it is not tuned: a different X is a different registration.
Because it is a threshold and not a target, **too few bets is a valid result**
(section 8), and the threshold is never lowered to find more.

## 7. The measurements, fixed

**Consensus.** At a board, every fresh book with both sides priced is de-vigged
two-way with `src.core.odds.devig_two_way` (proportional) and the favoured side's
fair probability is averaged over books: `fair`.

**Entry (at the DP).** `fair_d` is the consensus of the decision board. `avg_entry`
is the mean raw (vig-included) implied probability of the bet side over the fresh
books: the break-even of the board AVERAGE price. `best_entry` is the best fresh
price's implied probability.

**Reference.** The first stored snapshot of the key at or after **600 seconds** and
no later than **1,500 seconds** after the decision snapshot, with at least 3 books
whose `last_update` is at or after the decision snapshot's response time (so the
reference cannot be the same stale quote), taken while ESPN still shows the match in
progress. Any paid snapshot taken for any purpose counts; a dedicated call is made
only if none is due by 900 seconds. `fair_r` is its consensus. A bet with no valid
reference is `NO_REFERENCE`, with its cause counted (match ended, suspended, market
removed, window passed, credit refused). Nothing is excluded for any reason that
depends on who won.

- **M1 (drift), probability points:** `100 * (fair_r - fair_d)` on the bet side.
- **M2 (closing-line value, DECISIVE), probability points:** `100 * (fair_r -
  avg_entry)`. Positive means a bet at the board-average price beat the later
  consensus.
- **Descriptive only, cannot change the verdict:** M2 at `best_entry`, labelled
  "includes price improvement from line shopping" (never edge); M2 and M1 for the
  side the rule did NOT pick (the selection effect is the difference); the model's
  and the consensus's Brier scores against the match result and the model's
  current-set price against the set's own result (the only place an outcome is read);
  flat 1-unit profit at the average price and at the best price, settled by the
  ESPN rule above (void and retirement handling as in section 5); the model-minus-
  consensus gap by sets-won score, by tour and by favourite or underdog; the share of
  DPs excluded by each reason; the distribution of the age of every fresh quote; the
  same M2 recomputed with freshness relaxed to `last_update >= the last poll that
  still showed the set in progress` (labelled "permissive", exists only to show how
  much of any apparent result is stale-quote contamination).

## 8. The decisive test and the verdict rule, fixed

**Statistic.** The mean of M2 over bets that have a reference. **Interval:** match-
clustered bootstrap (`src.model.discovery.clustered_bootstrap` with the match as the
cluster key), **2,000 resamples, seed 20261028**, 95% percentile interval.

**Floors, all required before any verdict:** at least **300 bets with a valid
reference**, from at least **150 distinct matches**, and a reference coverage of at
least **70%** of all bets. Below any of them no effect statistic is printed.

- **PASS** (registry `candidate`, never `survivor`): the floors are met, M2's 95%
  interval lies entirely above zero, **and** M1's point estimate is above zero. PASS
  means one thing: a second, independent forward window may be registered with a
  falsification battery. It is not a promotion, a pick or a claim of profit.
- **FAIL** (registry `null`): the floors are met and the PASS rule is not. The
  report says in which direction the numbers fell.
- **INCONCLUSIVE** (registry `below_floor`): the floors are not met by the stop date,
  **2027-01-31**, or the code's constants no longer match the ledger's first-row
  fingerprint. The report then states the counts as the finding. Too few bets, too
  few fresh boards or too little credit are results, not defects to repair.

**One decisive test.** The family is one hypothesis and one pooled statistic; the 95%
interval is not the registry-wide `0.05 / N` bar and a PASS here would not meet that
bar. Everything in section 7 marked descriptive cannot rescue, veto or re-run the
verdict. **There is no threshold to move, and no effect-size floor.**

## 9. Credits and cost

**Budget rule.** Data spend stays at the plan already paid, the $59 / 100,000-credit
Odds API plan, which is also used by the pre-game and all-sports captures. This test
adds **no subscription and no vendor**: ESPN is free; API-Tennis is rejected (cited
in section 0); BALLDONTLIE is not used. Unused credits expire at the monthly reset, so
the cost is the share of one existing allotment, capped below.

**Hard caps in code (section 12):** 200 credits per UTC day for this test in total,
of which at most 60 may go to pre-match boards; 4,000 per UTC month (4% of the
allotment); and a refusal whenever the balance would fall to the repository's
5,000-credit floor (`src/capture/budget.CREDIT_FLOOR`) or when the balance is
unreadable (fail closed). Every call is logged to the live credit log under the
existing direct-sum band `live_odds` with caller `live_tennis.capture`, from the
call's own `x-requests-last`, so it is billed to the live band and not the pre-game
envelope. The owner's 300-credit daily live-odds cap, shared by every sport, is also
checked before each call.

**Estimate, stated before any measurement and replaced by the measured figure in the
report.** Planning inputs from section 0: 3 to 4 active priced tournament keys, about
40 priced matches a day (observed floor 14 to 21), about 1.4 decision points per match
(set 2 always, a deciding set in roughly two matches in five), so about **55 decision
points a day**.

| Purpose | Rule | Worst case | Planning figure |
|---|---|---|---|
| Pre-match boards | one call per key per 45 minutes while a match of that key is `pre` and due within 90 minutes | 48 | 20 |
| Decision snapshots | at most 2 per DP, shared across DPs of the same key and tick | 110 | 70 |
| References | at most 1 per bet, shared, and any decision snapshot serves | 55 | 30 |
| **Total** | | **213** | **~120 a day** |

**This is already the reduced design, chosen because the full one does not fit.**
Polling every live key continuously, even once a minute, would cost about 60 credits
an hour per key, roughly 2,000 credits on a day with three keys over twelve hours,
ten times the cap and half a month's allotment in two days. So this test buys prices
only at a set start, its reference ten minutes on, and a pre-match board; it covers
ATP and WTA keys only, one region, one market; and it never watches a match
continuously. Anything smaller (for example one tour) would cut the sample the floors
need without cutting the cost per bet, so it is not used.

So a typical active day is about **120 credits**, at most 200 by construction (the
worst case above is cut off by the cap, never exceeded), and the month is at most
4,000. The all-sports capture already spends up to 450 credits a day on 30-minute in-
play tennis snapshots; this test is additional to that and is the reason for its own
cap. **If the cap binds, decision points are logged `CREDIT_REFUSED` and counted**;
the cap is not raised. If the credits cannot support the sample, the registered
result is INCONCLUSIVE and the report shows how many DPs per day were refused.

## 10. Size the sample can detect

The minimum detectable effect at about 80% power, two-sided 5%, is about **2.8 times
the bootstrap standard error** of the mean. Stated now, measured value reported with
the result. The ten-minute consensus drift on a two-way tennis board is a few
points, so a clustered standard error of a few tenths of a point at 300 bets is
expected, and the vig, not the sample, sets the bar: **M2 > 0 requires M1 above about
2.8 points**. The expectation in section 2 stands: **M2 at the average price will be
negative.**

## 11. What is NOT claimed

- No profit, no edge, no value, no pick. M2 is closing-line value at the average
  price, a necessary condition for a timing or modelling rule, not proof of profit.
  Units are descriptive and secondary.
- A FAIL says this model at these decision points on these feeds does not beat this
  board. It does not say live tennis is unbeatable, and it says nothing about
  latency, because the feeds here are late by construction.
- A PASS at most licenses registering a forward replication with the falsification
  battery and the full promotion gate. Nothing here is a live rule.
- The current-set winner is priced by the model and never bet: no book price exists.

## 12. Frozen constants

The block below is the machine-readable freeze. `tests/test_live_tennis_frozen.py`
parses it and requires `src/research/live_tennis/config.py` to hold exactly these
values; the code also hashes them into the ledger's first row.

<!-- FROZEN_CONSTANTS_BEGIN -->
RULE_ID = LIVE_TENNIS_V1
MODEL_ID = MARKOV_V1
SERVE_LEVEL_ATP = 0.64
SERVE_LEVEL_WTA = 0.56
SKILL_GAP_BOUND = 0.15
MIN_DECISION_SET = 2
MIN_FRESH_BOOKS = 3
BEST_IMPLIED_SUM_FLOOR = 0.99
GAP_THRESHOLD_PP = 3.0
DP_WINDOW_SECONDS = 240
MAX_DECISION_ATTEMPTS = 2
ATTEMPT_SPACING_SECONDS = 45
REF_MIN_DELAY_SECONDS = 600
REF_MAX_DELAY_SECONDS = 1500
REF_DEDICATED_AFTER_SECONDS = 900
PREMATCH_LEAD_MINUTES = 90
PREMATCH_REFRESH_MINUTES = 45
POLL_INTERVAL_SECONDS = 60
IDLE_POLL_INTERVAL_SECONDS = 300
DAILY_CREDIT_CAP = 200
PREMATCH_DAILY_SUBCAP = 60
MONTHLY_CREDIT_CAP = 4000
BET_FLOOR = 300
MATCH_FLOOR = 150
REFERENCE_COVERAGE_FLOOR = 0.70
STOP_DATE = 2027-01-31
BOOTSTRAP_RESAMPLES = 2000
BOOTSTRAP_SEED = 20261028
<!-- FROZEN_CONSTANTS_END -->

Why each is what it is, in one line apiece. `SERVE_LEVEL_*` are approximate
long-run tour averages of the share of service points won (about 64% on the men's
tour, about 56% on the women's), chosen from published tour statistics before any
data in this study was read and never re-fitted; the verdict does not require them to
be exact, and a sensitivity of plus or minus 0.03 is reported as descriptive only.
`SKILL_GAP_BOUND` is wide enough to price any match-win probability a real board
shows. `MIN_FRESH_BOOKS` and `BEST_IMPLIED_SUM_FLOOR` come from the board structure in
section 0. `GAP_THRESHOLD_PP` is section 6. The windows, attempts and spacing keep a
decision inside the one stretch in which a set start can be seen at 0-0 (a set break
and the first game). `REF_*` put the reference mid-set, where a set cannot have ended
(a set takes well over ten minutes), so the reference exists for every bet regardless
of result. The caps are section 9. The floors and the stop date are section 8. The
stop date, 2027-01-31, is long enough to cover the rest of the autumn season and, after
the winter break in the calendar, the opening weeks of the next, so the sample is
hard-court heavy and that is a disclosed limit.

## 13. Procedure and stopping rule

1. Commit this file alone with the registry row (this commit).
2. Write the harness and its tests (synthetic rows and scripted fake feeds only),
   commit. Files: `src/research/live_tennis/` (`config.py`, `markov.py`, `state.py`,
   `board.py`, `decision.py`, `ledger.py`, `guard.py`, `runner.py`, `grade.py`,
   `report.py`, `cli.py`) and `tests/test_live_tennis_*.py`.
3. **Off by default.** Capture spends nothing and makes no request unless the
   environment switch `LIVE_TENNIS_TEST` is set to `on`; the owner flips it. The
   first tick writes a genesis ledger row holding the first-capture time, the stop
   date, the constants fingerprint and the sha256 of this file. From then on a
   constants mismatch makes capture refuse to run and the report INCONCLUSIVE.
4. `report` before the floors prints counts, coverage and credits only. After the
   stop date or the floors, one run writes the verdict; the registry verdict is
   appended once (`record_verdict`, `result` in `candidate / null / below_floor`).
5. **One pass, no tuning.** A defect found after data exists that changes a number is
   fixed in a separately disclosed commit and the affected rows are re-derived only if
   the defect corrupted them (a crash or a wrong join), never because of what they
   showed. No constant, rule or population here is edited; a different specification
   is a new registration.

## 14. Disclosed limits, written before any result

1. **Our prices are late.** The Odds API refreshes about every 40 s and we poll about
   every 60 s, so a fresh quote is typically 30 to 100 seconds behind the book. A
   positive result could not be a latency edge; a negative one cannot refute one.
2. **No suspension flag.** The Odds API has none. A price can be on the board while
   the book has suspended the market. Freshness (a post-set update), at least three
   books and the consistency filter reduce, and cannot remove, phantom prices.
3. **Retirements, walkovers, suspensions and rain delays.** These void or remove the
   reference or the settlement. They are counted by cause and are never dropped on
   anything that depends on who won.
4. **Survivorship.** Only matches that are priced in play, paired to ESPN and
   alive at a set boundary have decision points. Selection on those is by feed
   coverage, not outcome, and each exclusion is counted.
5. **Unknown first server**, ignored final-set rules, one serve level per tour and no
   surface or player-specific serve data (section 4.8). A systematic model
   misspecification would show up as a gap on the same side again and again; that is
   a model error to be reported, not an opportunity.
6. **Correlation.** Several bets in one match and several matches in one tournament
   share information; the cluster is the match, which understates tournament-level
   dependence.
7. **Regime.** The window is the tail of the autumn hard-court season and the opening
   of the next. It says nothing about clay or grass.
8. **Time.** All timestamps are UTC from the capturing machine's clock plus the
   books' own `last_update`; a clock error would shift freshness. The capture also
   writes a heartbeat file, one row per tick, so downtime is counted and never reads
   as a quiet day.
9. **A different bettor.** Real stakes would move prices and books limit winners; the
   paper ledger takes the board as given.

## 15. The registry

Registered through `src.research.alpha_registry.register()` in this commit
(`kind: hypothesis`, `family: LIVE_TENNIS`, `market: h2h`, `sport: tennis`,
`data_window: {discovery: "forward capture from the first armed set start", replication:
null, sealed_untouched: true}`, `alpha_declared: 0.05`, `code_hash: null` because no
harness exists yet). Registering raises the registered count by one and leaves the read
count unchanged until a verdict other than `below_floor` is recorded.
