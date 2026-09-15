# Live betting system: MLB, NFL and tennis

**Written:** 2026-09-15, from 17:06Z. **Revised:** 2026-09-15 about 21:30Z,
after an adversarial review by three independent reviewers (the Review record
at the end lists every high and medium finding and what was done with it).
**Roadmap item:** R16-35 (Stage 16).
**Status:** design. Nothing in this document is registered. The three live
rules already registered live in `docs/PREREG_MULTI_SPORT_2026-09-14.md`
(entries 2 to 4); every new family proposed here needs its own
pre-registration document, committed before its first observation.

**Evidence rules that apply to every line below:** pre-registration before any
evaluation; every loser published; no promotion without the full gate; no
rescue by threshold change; point-in-time data only; customer text never claims
an edge or a guarantee. The data split, in the
words of `docs/DEBRIEF.md`: "2026-01-01 → 2026-08-27 SEALED, one evaluation
ever, only after a policy freeze plus Brey's explicit go · 2026-08-28 onward is
forward proof, never folded back into tuning." 2025 is tuning-only.

**Numbers in this document** were computed in this session unless a source file
is named. Every computed number names its store and filter. Numbers marked
EXPLORATORY come from forward data that has already been looked at; they size
the work and can never count as evidence for or against any rule. No outcome
(who won a game) was read for any count in this document.

---

## 1. What the owner asked for, and the short answer

Owner, 2026-09-15 10:00am PT, in the same message as the Card V2 request:

> "Also, we need to find out how to make a live bet system and incorporate it
> into our MLB, as well as the NFL and tennis."

and, about what a good bet is:

> "If it's a high-confidence bet and the value is great, that's what we're
> looking for."

**The answer.** A live bet system here is a machine that watches games while
they are played, notices when a situation written down in advance happens (a
favourite falls behind early, a starter is pulled, a favourite drops the first
set), records the in-game price that was actually on offer at that moment, and
grades it when the game ends. Today it can honestly claim nothing about winning:
the live pipeline has never run once, no live rule has a single observation,
and this pass found that the shipped code could not record a candidate even if
it did run (section 2.3). It cannot claim an edge, value or a pick, and no live
reading may reach the card. What makes live worth building is not evidence that
it works; it is that live markets are where a fact moves a price within
seconds, which is where an information edge could exist, and the five
pre-game "does our model beat the market" measurements, none of which found
that it does (`docs/DOES_THE_MODEL_BEAT_THE_MARKET.md`), say nothing about that
question. The
earliest any live rule could be shown to a customer as a pick is after its
pre-registered floor read passes and a fresh confirmation run clears the
repo's full promotion gate, G0 to G7 (`docs/ARCHITECTURE_BETTING_ENGINE.md`
section 5; quoted in 4.1), which includes a placebo-world ceiling (G5), at
least 300 forward selections with a settled close over at least 60 ledger days
(G6) and the owner's explicit, dated sign-off (G7). An in-play bet has no
settled close, so G6 cannot be met for a live family until a stand-in is
registered (4.1). On the trigger rates measured below (EXPLORATORY), the
most frequent registered rule reaches its floor of 150 around the end of May
2027 on its point estimate and needs about another season for 300
confirmation selections (in May 2028: early May if every day of the season
carries 15 games, late May if a season holds only its 2,430), so **2028 at the
earliest for the registered rules** (per-rule dates in 4.1).
Only the proposed M2, if registered and on its point estimate, could finish
both in 2027 (about August).

A second honest point for the owner: the registered live rules mostly buy a
favourite after it has fallen behind, which means a price near even money or
better and a likelihood below the pre-game favourite's. They are price-shaped
research, not the "high-confidence" bets the pre-game card is being rebuilt to
show. Section 4 proposes families shaped to the owner's band, and says where a
live situation cannot be both likely and cheap.

---

## 2. What exists now (v0), what has run, and the gaps

### 2.1 Components on disk

| Piece | File | What it does |
|---|---|---|
| MLB state poller | `src/pipeline/livefeed_mlb.py` | Free MLB Stats API linescore, one row per observation into `data/live/mlb/<date>.jsonl`, one Final row per game. |
| NFL state poller | `src/pipeline/livefeed_nfl.py` | The Odds API `/scores` (1 credit per call, measured in `config/capture_families.json` at 2026-09-15T10:15:19Z), gated by `in_window()` (Thu 19 to 23:59, Sun 12 to 23:59, Mon 19 to 23:59 ET) and `budget.can_spend("scores", 1)`; credits logged under `live_capture`. |
| In-play odds capture | `src/pipeline/live_odds.py` | `should_capture()` fires on any change (MLB: score, inning, half, pitcher; NFL: score); `capture_inplay()` fetches featured `/odds` h2h (1 market x region `us` = 1 credit for the whole slate), writes `data/live/odds_inplay.jsonl`, gated by `budget.can_spend_live_odds()`. |
| Rules | `src/analysis/live_rules.py` | `mlb_favorite_trails_after_3`, `mlb_starter_pulled_early`, `nfl_favorite_trails_halftime`; price = median across books (lower middle on even counts). |
| Runner | `src/pipeline/live_window.py` | `pregame_context()`, `tick()`, `run()` (MLB 60 s, NFL 300 s, stop at 330 minutes or nothing live), `should_dispatch()`, `settle()`, commit and push every 5 minutes. |
| Ledger | `src/appstate/live_ledger.py` | Hash-chained, append-only `evidence/live_candidates_v1.jsonl`; dedupe on (rule_id, sport, game_id); isolated from `card_ledger`. |
| Budget | `src/capture/budget.py` | `LIVE_ODDS_DAILY_CAP = 300`, `LIVE_ODDS` switch (default off), `CREDIT_FLOOR = 5000`. |
| Dispatch | `scripts/capture_slot.sh` (live-window block) | Each forward-capture slot runs `--should-dispatch` for mlb and nfl and calls `gh workflow run live-window.yml` on `DISPATCH`. |
| Workflow | `.github/workflows/live-window.yml` | `workflow_dispatch` only, `timeout-minutes: 350`, concurrency per sport. |
| Page and API | `api/live.py`, `web/js/live.js`, `src/pipeline/live_remote.py` | `#/live?sport=mlb|nfl`, out of the public chrome and reachable only by typed URL since redesign group 1 (commit 846218b0, deployed to staging; R16-05), fixed notice "Live analysis is in internal testing. No alerts are sent.", chip "research, not a pick". |
| Tennis | none | No poller, no rule, no page tab. |

### 2.2 What has actually run (as of 2026-09-15 about 17:06Z)

From the inventory pass, re-checked where noted:

- `live-window.yml` runs ever: **0** (`gh api .../workflows/358415890/runs`, `total_count: 0`).
- `data/live/mlb/`: exists, **0 files**. `data/live/nfl/`: absent.
  `data/live/odds_inplay.jsonl`: absent. `evidence/live_candidates_v1.jsonl`:
  absent. `git log --all` shows no commit ever touching either path.
- `data/processed/credit_log.jsonl`: 1,940 rows, **0** with
  `"budget_band": "live_odds"`.
- Repository variable `LIVE_ODDS=1` set 2026-09-15T16:30:36Z.
- Six forward-capture slots between 16:04Z and 17:09Z printed `HOLD` for both
  sports (MLB: nothing live or within 30 minutes; NFL: outside the broadcast
  window on a Tuesday).
- Observations toward the three registered floors of 150: **0, 0, 0**.

Re-checked at about 21:25Z for this revision:

- `live-window.yml` runs ever: still **0** (`gh run list --workflow
  live-window.yml` returns an empty list). The slot at 20:09:54Z (run
  35017941084) printed `HOLD no live games and nothing starts within 30
  minutes` for MLB and `HOLD outside NFL broadcast window` for NFL at
  20:27:09Z.
- Local `data/processed/credit_log.jsonl`: 1,989 rows, still **0** with
  `"budget_band": "live_odds"`; newest row 2026-09-15T21:03:53Z, balance
  20,473.
- **BALLDONTLIE is not a working feed.** The `BALLDONTLIE_API_KEY` secret was
  set at 2026-09-15T17:28:10Z (`gh secret list`). The key reaches paid
  endpoints (ATP matches returned rows), but it is served at about 5 requests
  a minute, the vendor's free-tier rate, not the 600 a minute its pricing page
  lists for ALL-ACCESS (vendor pricing page, read 2026-09-15). Every harvest
  job in runs 35001607006 and 35002183724 took exactly 5 pages and then HTTP
  429. On origin, `data/historical/balldontlie/MANIFEST.json` marks every ATP
  2010 to 2026 and WTA 2016 to 2026 matches file `complete: false` at 500 rows
  with `http_status: 429`, and `atp_odds_opening` and `wta_odds_opening`
  returned HTTP 400 with 0 rows. The harvester was fixed twice (79e28ccb,
  fac6ef45); run 35014512871 on the fixed code was still running at 21:25Z.
  The owner has been asked to confirm the ALL-ACCESS trial is on the same
  account as the key. The trial ends about 2026-09-17 05:30Z (R16-33), and no
  paid continuation is recorded. Every use of BALLDONTLIE below is therefore
  conditional, and each sport has a fallback that does not depend on it.

One store that does exist and was not in the inventory: the pre-game capture
chain already keeps in-play prices as a side effect. In
`data/processed/odds_multibook.jsonl` (173,511 rows), **25,407 rows** have
`observed_utc` at or after `commence_time`, across 177 events with commence
dates 2026-08-31 to 2026-09-15, almost all from eight books (betmgm 3,221,
fanduel 3,153, fanatics 3,116, draftkings 3,087, williamhill_us 3,051, bovada
3,013, betrivers 2,988, mybookieag 2,836). They were observed 10.2 / 67.4 /
144.8 minutes after the scheduled start (10th / 50th / 90th percentile), and
the quote age at capture (`observed_utc` minus `book_last_update`) is 7.9 /
40.1 / 139.1 / 768.4 seconds (10th / 50th / 90th / 99th percentile). Scheduled
start is not first pitch, so the earliest of these rows may still be pre-game.
These rows are taken on the chain's 13 to 15 minute clock, not at trigger
moments, so they cannot test any registered rule; section 4.1 proposes
quarantining them from any outcome join.

### 2.3 Defects found in this pass

Each was checked by running code on real or synthetic inputs (scripts in the
session scratchpad, `card_v2/live_*.py`) or, where marked, by reading.

| # | Defect | Evidence | Effect |
|---|---|---|---|
| D1 | `pregame_context()` for MLB reads `game["teams"]...` and `probablePitcher`, but `mlb.fetch_games()` returns `mlb.parse_game()` records, which have `home_team` (an abbreviation such as `CIN`), `home_probable_id` and no `teams` or `status` key. | Real run for 2026-09-14 (10 games, schedule from the Stats API): `home_team` None for 10 of 10, `starter_ids` empty for 10 of 10, favourite None for 10 of 10. `tests/test_live_window.py` passes because its fixture invents a shape with both `game_pk` and `teams`. | Neither MLB rule can fire. |
| D2 | The favourite probability reads `consensus.get("home_prob", 0.5)` from `prices.snapshot()`, which returns `sides`, `dispersion`, `label`, `any_positive`, `note` and no `home_prob`. `snapshot()` is also handed every row of the day, although its docstring requires one capture instant, and nothing filters out rows observed after first pitch. | Real `prices.snapshot()` output keys printed. The store holds 25,407 in-play rows (2.2). | With D1 fixed, every favourite probability would read 0.5 and the favourite would always be "away": `mlb_favorite_trails_after_3` (needs 0.55) and `nfl_favorite_trails_halftime` (needs 0.60) never fire, and `mlb_starter_pulled_early` watches the wrong team. It is also a point-in-time leak waiting to happen. |
| D3 | MLB live states are keyed by integer `game_pk` (`livefeed_mlb.latest_states`), the pre-game context by string; `tick()` skips any game not in the context. | By reading `live_window.tick()`. | No MLB game is ever evaluated. |
| D4 | NFL pre-game context is keyed by the nflverse `game_id`; NFL states by The Odds API `event_id`; the context's `event_id` is looked up with `gamekey.game_id_for_event(None, ...)`, which returns None; settlement keys NFL finals by `event_id` while candidates carry `game_id`. | By reading. | No NFL game is ever evaluated or settled. |
| D5 | The NFL halftime proxy (first observation 80 to 100 minutes after kickoff) is only evaluated on ticks where `should_capture()` saw a score change. | By reading `tick()`. | Most halftimes are never evaluated, even with D4 fixed. |
| D6 | `capture_inplay()` logs its credit row with `credits_remaining` None (no quota is passed from `tick()`). `spent_today()` skips None rows, so the spend is billed to whichever band logs the next real balance, and `remaining_today()` returns None whenever that None row is the newest. | Synthetic temp store: 40 in-play captures between two capture rows gave `live_odds` spent **0**, `live_capture` spent **43**, and `can_spend_live_odds` still allowed. With a None row newest: `remaining_today` None, and both `can_spend("scores", 1)` (the NFL poller) and `can_spend_live_odds(1)` refused "quota unreadable". | The 300 cap never binds; in-play spend lands on the 900 pre-game envelope; after one capture the runner refuses further captures and the NFL poller stops until another band logs a balance. |
| D7 | The live window commits `data/processed/credit_log.jsonl` while the capture chain, on another runner, appends to the same file every 13 to 15 minutes; both push with `pull --rebase`. | Expected from git's three-way merge (both sides add lines at the same end of file). Not rehearsed: the scratch git rehearsal was denied by the tool policy. | Once the chain pushes a credit row after the window's checkout, every window commit that touches the credit log fails to rebase, all three retries fail the same way, and the window's rows are lost when the job ends. Treat as likely until observed. |
| D8 | `should_dispatch()` reads `status.abstractGameState`, which `parse_game()` lacks, and treats any start time in the past as "starts within 30 minutes"; `run()` does the same when nothing is live. | Synthetic: a game final hours earlier returned `(True, "MLB game starts within 30 minutes")`. | Windows keep dispatching and running to 330 minutes after the slate ends. Free Stats API calls only, but the log reason is false. |
| D9 | `capture_inplay()` drops each book's `last_update`, although `odds.fetch_normalized()` provides it. | By reading (`src/providers/odds.py` normalises `last_update` per book). | No stored price can be shown to post-date the trigger; stale and suspended prices cannot be excluded. |
| D10 | A rule returns None when no median price exists, so a trigger that could not be priced leaves no record. Ledger rows carry no pre-registration reference, code commit, per-book quotes or pre-game proof. | By reading `live_rules.py` and `live_ledger.record_candidate()`. | Silent selection by price availability; rows cannot be audited against their registration. |
| D11 | `live_ledger.settle()` writes a permanent VOID when no final score is supplied, and `live_window.settle()` takes finals only from the poller's own rows. | By reading. | A window that stopped early, or a push that failed (D7), voids real candidates forever. |
| D12 | `mlb_starter_pulled_early` compares against the listed probable pitcher; the registered text says the favourite's starting pitcher. | EXPLORATORY count on forward `gameflow_2026.jsonl`: for the pre-game favourite, probable and actual starter differed in 0 of 121 games. | Rare in practice, but an opener or late scratch would fire the rule at the first pitch. |

What is not a defect: the ledger's isolation from the card, the separate
credit band and floor, the hash chain, the page's fixed internal-testing
notice, and the budget refusal when `LIVE_ODDS` is off. One gap on that page
is: `web/js/live.js` `renderCandidateRow` (`:142-165`) shows an in-play price
and a clock time with nothing saying the price may already be gone, and rows
reach the page on a 5-minute push cadence (3.1, Stage 1). R16-L16 fixes the
wording.

A gap in the shipped reporting: the daily loop already prints interim live
results. `scripts/daily_loop.sh:321-322` runs `live_window --settle` and echoes
its output into the Actions log, and `live_ledger.settle` returns wins,
losses, pushes, voids and units by rule. That contradicts Stage 0's "nobody
computes an interim result" (3.1); R16-L7 removes it.

### 2.4 Gaps that are design, not bugs

- The registration has a direction and a win condition but no test statistic,
  no definition of which in-play price counts, no rule for triggers that could
  not be priced, and no stop date if a floor is never reached.
- The shipped capture design (any change) spends most of the shared cap on MLB
  alone (section 5.2). The cap is counted per UTC calendar date
  (`budget._row_date` is `utc[:10]`), which resets at 8pm ET in the middle of
  the evening slate, so it runs out in the late afternoon or early evening ET
  and drops the start of that evening's games by time of day.
- No feed for tennis in-play prices; no verified clocked NFL feed
  (BALLDONTLIE's spec defines an `NFLPlay` record with `period`,
  `clock_display` and `wallclock`, but the path and its live behaviour are
  unverified, 3.3).
- No confirmed zero-credit feed for any sport. BALLDONTLIE is served at about
  5 requests a minute on a trial that ends about 2026-09-17 05:30Z (2.2), so
  the NFL state feed defaults to The Odds API `/scores` and tennis state has no
  feed that is both confirmed and affordable (3.3, 3.4).
- No customer surface design beyond "internal testing", and no delivery path
  fast enough for a live pick (3.1, Stage 1).
- Handoffs between live windows leave uncovered minutes that nothing records
  (3.2, Windows).

**Consequence for tonight.** R16-03 asks to verify tonight's MLB window. If a
window dispatches on 2026-09-15 before the fixes in section 6, expect zero
candidates (D1 to D3), at most about one in-play capture per real credit row
(D6), a `live_odds` band that reads 0 whatever was spent (D6), and a likely
failed push (D7). Treat tonight as a plumbing rehearsal, and do not read R16-03's
"live_odds band at most 300" acceptance as a pass while D6 stands. The spend at
risk is small (D6 itself throttles captures), so `LIVE_ODDS=1` can stay.

---

## 3. Architecture

### 3.1 Shared design (all sports)

**The flow, per game:** state feed, trigger check on every poll, capture on
trigger, freshness check, ledger row, settlement from an authoritative final,
page.

**Rule-gated capture replaces any-change capture.** A paid in-play price is
fetched only when a registered rule's trigger condition is true for some game
on this poll, plus at most two retries for freshness and one follow-up capture
five minutes after the trigger (descriptive price-reaction data, never a gate).
One featured `/odds` call returns every live game in the sport, so a capture
for one game prices the rest at no extra cost.

**Trigger time.** T0 is the `observed_utc` of the first state row on which the
trigger condition is true.

**The vendor's refresh.** The Odds API refreshes in-play featured markets
(moneyline, spreads, totals) every **40 seconds** and pre-match every 60
(`https://the-odds-api.com/sports-odds-data/update-intervals.html`, read
2026-09-15). Its v4 guide, as read here, does not define whether a bookmaker's
`last_update` means "last retrieved from the book" or "price last changed",
and has no suspension flag. `src/providers/odds.py:862,879` stores
`market.get("last_update") or book.get("last_update")`. Until that meaning is
measured (R16-L9, repeated captures of an unchanged price), the 139-second and
768-second quote-age tails in 2.2 may not measure staleness at all.

**Fresh price (proposed definition of "in-play quote price").** A capture is
taken at T0, T0 + 45 s and T0 + 90 s (spanning two vendor refreshes), stopping
at the first that prices. A book's quote is fresh when its `last_update` is at
or after T0 and its age at capture is 60 seconds or less. The logged price is
the median of fresh books' prices (lower middle on an even count, as the
registered code already does), and needs at least 3 fresh books. The median is
the typical price across books, not the best; this keeps faith with the
owner's 2026-09-11 ruling against cross-book shopping
(`probability-before-price`). If still not priced within the sport's capture
deadline, write the trigger row with an UNPRICED status. The chain's
side-effect rows (2.2) show why this matters: 10% of stored in-play quotes had
`last_update` more than 139 seconds before capture.

**Which "fresh" is registered.** "`last_update` at or after T0" means one
thing if the field is a retrieval time (every book retrieved after T0 passes)
and another if it is a change time (only books that repriced after our lagged
T0 pass, which drops the fastest books, those that moved before T0: a
selection bias). So that nobody chooses a reading after rows or outcomes
exist, the LIVE_V0 addendum (R16-L1) commits a fixed mapping before the first
window that can record a candidate (R16-L8):

- **How the field is classified.** R16-L9 compares pairs of captures of the
  same book and event at least 60 seconds apart (so at least one 40-second
  vendor refresh lies between them, for example T0 and the T0 + 5 minute
  follow-up) in which the price did not
  change. If `last_update` advanced in at least 90% of at least 10 such
  pairs, it is a retrieval time; if it stayed fixed in at least 90%, a change
  time; otherwise undetermined. The rule is mechanical: no one picks the
  answer.
- **Retrieval time, or undetermined:** a book's quote is fresh when its
  `last_update` is at or after T0 and its age at capture is 60 seconds or
  less (the definition above).
- **Change time:** a book's quote is fresh when its `last_update` is at or
  after P, the time of the event that completed the trigger condition, with
  no age limit (under a change time the age measures how long a price has
  held, not staleness). P is, for MLB, the Stats API play-by-play time of that
  play (`about.endTime` of the play that ended the inning or changed the
  score, or the substitution event's time for a pitching change; R16-L1
  confirms these fields on a real payload before committing); for NFL, the
  `last_update` of the first The Odds API `/scores` row that showed the score
  the trigger fired on. P is read for that event only, never a later play or a
  final.
- **Which rows.** The runner stores every capture it takes for a trigger
  with its per-book quotes (R16-L5, R16-L6) and stops retrying at the first
  capture that prices under the retrieval-time rule. A book fresh under that
  rule is also fresh under the change-time rule, because T0 is after P. The
  classification is made once, from R16-L9's three nights; if it is
  undetermined then, the retrieval-time rule applies to LIVE_V0 for good, and
  the field is not re-measured to change it. Every trigger row from the first
  window on is then classified under the mapped rule from those stored
  quotes, using the earliest stored capture that prices under it. Rows
  written before the classification carry the retrieval-time status and get
  an appended classification row with the final status and logged price; the
  ledger is append-only, so nothing is rewritten. Rows from R16-L9's own
  nights count like any other.

Every read reports the share of books excluded for a `last_update` before T0
and, under the change-time rule, before P.

**Suspension.** Neither The Odds API nor BALLDONTLIE's odds schema (per its
OpenAPI spec, read through a fetch summary on 2026-09-15, not a raw file)
carries a suspension flag. A book absent from the response for the event, or
whose quote is not fresh under the registered rule above, is treated as
suspended or stale for that trigger. API-Tennis Business has a flag; its accuracy is trial check 8 in
`docs/TENNIS_FEED_DECISION_2026-09-15.md`.

**One trigger per rule per game.** The first time a rule's condition is true in
a game is that game's only trigger for the rule, priced or not. A game whose
first trigger was UNPRICED does not get a second chance later, so availability
of a price cannot choose the sample.

**Ledger row (fields added to `live_candidates_v1` before its first row; if any
row exists when this is built, a `v2` store is opened instead):**

| Group | Fields |
|---|---|
| Identity | `schema_version`, `family`, `rule_id`, `rule_version`, `prereg_doc`, `prereg_commit`, `code_commit` (the runner's `GITHUB_SHA`) |
| Game | `sport`, canonical `game_id` (MLB `game_pk` as a string; NFL Odds API `event_id` plus nflverse `game_id`; tennis provider match id plus odds event id) |
| Pre-game proof | `favourite`, `favourite_prob` (de-vigged mean), `pregame_books`, `pregame_newest_observed_utc`, `commence_time`; the row is refused unless every pre-game quote was observed before `commence_time` |
| Trigger | `t0_utc`, the state row id, the state fields that satisfied the rule |
| Quote | `capture_observed_utc`, per book `{book, price, last_update}`, `fresh_books`, `logged_price`, `latency_s` (capture minus T0), `max_quote_age_s`, `retries` |
| Status | `PRICED`, `UNPRICED_NO_FRESH_QUOTE`, `UNPRICED_NO_MARKET`, `UNPRICED_CREDIT_REFUSED`, `UNPRICED_FEED_ERROR` |
| Band | `in_band` and `band_version` (descriptive for LIVE_V0; part of the trigger for proposed families) |
| Surface | `customer_eligible: false`, fixed until a family passes the full gate |

Field names avoid the customer-language test's banned parts (`edge`, `roi`,
`win_prob` and the rest in `tests/test_customer_language.py`).

**Grading.** From an authoritative final, never from the live poller alone:
MLB from `mlb.fetch_results(date)` (the Stats API final bucket), NFL from The
Odds API `/scores` completed flag (BALLDONTLIE only once R16-L13 confirms its
rate and plan) cross-checked against the nflverse schedule the next day,
tennis from BALLDONTLIE's status list with the retirement rule recorded before
any grading (R16-10). Grading needs a few calls a day, which the measured 5
requests a minute allows; what is unconfirmed is whether the plan in force
after the trial still serves ATP and WTA matches. If it does not, tennis
grading needs API-Tennis results (R16-22) and no tennis rule is graded until
one of the two is confirmed. A candidate with no
final yet stays unsettled and is retried daily; VOID is written only after 7
days, or for a game postponed or suspended and not resumed, with the reason.
Profit is flat 1 unit at `logged_price`. An NFL tie is a PUSH.

**Customer surface, in two stages.**

- Stage 0, now until a family passes the full gate: internal page by typed URL
  only, no alerts, no win-loss display. Each rule shows "N of 150 tested" and
  its trigger rows with status, time and row age. Outcomes are published once,
  at the registered read or at retirement. The ledger file stays public in the
  repo; the process rule is that nobody on the project computes an interim
  result, and no job prints one: settlement writes graded rows and prints only
  counts (graded, voids, unsettled), never wins, losses or units, in every log
  (R16-L7 removes today's per-rule win-loss output from the daily loop).
- Stage 1, only for a family that has passed: a live pick row and an opt-in
  alert. The row expires at the earlier of 90 seconds after
  `capture_observed_utc` or the sport's next state boundary (MLB: the next
  pitch after the break; NFL: the next score or the second-half kickoff;
  tennis: the next point). It shows the lowest price at which the record still
  applies ("only if you can get +110 or better"), never a best-book comparison.

**Stage 1 is not buildable on the current delivery path.** The window runs on a
GitHub Actions runner and publishes by `git push` every 5 minutes
(`src/pipeline/live_window.py` `run(commit_every_minutes=5)`, `_commit()`); the
web container never sees those pushes and reads them from
`raw.githubusercontent.com` through a 60-second in-process cache
(`src/pipeline/live_remote.py:9,31,63`). Capture to screen is therefore up to
about 360 seconds plus push and CDN time (not measured), so a row that expires
90 seconds after capture would be expired before anyone saw it. A PWA service
worker (R16-31) does not give the runner a way to reach the server. Stage 1
needs a runner-to-server write (for example a signed POST to the web app, or a
push service) and a measured latency. Stage 1 row expiry and alerts are not
buildable on the current architecture, and stay unbuilt until R16-L20
(section 6) passes: p95 capture-to-render at or under 20 seconds over 20
captures.

**Kill switches and caps.** Two rows are marked not built: listed as they are
today, they would do nothing in an incident.

| Switch | Where | Effect |
|---|---|---|
| `LIVE_WINDOW_DISPATCH=0` (**not usable yet**) | env for `scripts/capture_slot.sh` | No window is dispatched. Today the script defaults it to 1 (`scripts/capture_slot.sh:556`) and the "Capture one slot" step of `.github/workflows/forward-capture.yml` passes only `ODDS_API_KEY`, `BALLDONTLIE_API_KEY`, `CAPTURE_NOW` and `CHAIN_BY_WORKFLOW_STEP`, so turning it off takes a code commit. R16-L3 wires `LIVE_WINDOW_DISPATCH: ${{ vars.LIVE_WINDOW_DISPATCH }}` into that step. |
| `LIVE_ODDS` not 1 | repository variable (`live-window.yml` passes `vars.LIVE_ODDS`) | No in-play credit is spent. |
| `LIVE_SPORTS` (proposed) | repository variable, e.g. `mlb,nfl` | Per-sport off switch. |
| Per-sport daily caps (proposed) | `budget.py` | Inside the 300: MLB 150, NFL 100, 50 unassigned. Per window: 100. Counted per ET slate day (the MLB official date; the ET kickoff date for NFL), not per UTC date as the shipped 300 is (`budget._row_date` is `utc[:10]`); R16-L3. |
| Rule status (**not built**) | `data/research/alpha_registry.jsonl` | Intended: a rule not in `registered` or forward-testing status triggers no capture. No live code reads the registry today (`src/pipeline/live_*.py` and `src/analysis/live_rules.py` never mention it). R16-L5 adds the check to `live_rules.evaluate_all`. |
| `LIVE_REMOTE_BASE=off` | web container env | The page stops reading the repo. |
| `CREDIT_FLOOR` 5,000 | `budget.py` | No paid call below the floor. |
| `gh workflow disable live-window.yml` | owner or admin | Stops the workflow outright. |

### 3.2 MLB

| Part | Design |
|---|---|
| State feed | MLB Stats API linescore, free and keyless (`livefeed_mlb.py`). Poll every 20 seconds while any game is live (proposed; now 60). `livefeed_mlb.poll` makes one schedule call plus one linescore call per live game, in sequence, each with a 20-second timeout, so 15 live games at a 20-second poll is 16 calls every 20 seconds, 0.8 a second. The schedule call already hydrates the linescore (`mlb.fetch_schedule`, `hydrate = "probablePitcher,team,linescore"`), so R16-L5 checks whether that linescore carries every field the rules read (including the current pitcher); if it does, the per-game calls go (about 0.05 a second), and if not they run in parallel. The Stats API publishes no rate limit, so stay at or under 1 a second and back off on errors. No BALLDONTLIE dependence. |
| In-play price | The Odds API featured `/odds`, `baseball_mlb`, h2h, region `us`: 1 credit per call for the whole slate; totals added (+1) only on a totals-family trigger or an M2 descriptive capture (R16-L5). This is the MLB price source; nothing below depends on BALLDONTLIE. Possible later zero-credit source: BALLDONTLIE `/mlb/v1/odds` (moneyline, run line, total, `updated_at`; no live flag or suspension flag in the spec summary; freshness unmeasured). Its key is set but served at about 5 requests a minute on a trial ending about 2026-09-17 05:30Z (2.2), so it is not measured or used unless a paid plan and a measured rate are confirmed first (R16-L9, R16-L13). |
| Trigger cadence | Every poll, every live game, every registered MLB rule. |
| Latency budget | Stats API lag behind the field: unmeasured (R16-L9 measures it against play timestamps). Detection to first capture: 10 seconds or less (a target, unmeasured; the sequential per-game calls above make it longer today). The Odds API refreshes in-play featured markets every 40 seconds (3.1), so a capture within 10 seconds of T0 will often find few books updated after T0; the retries at T0 + 45 s and T0 + 90 s are set from that refresh. Capture deadline: 120 seconds after T0, because an inning break is about two minutes under the 2023 pace rules (not measured here) and a later price belongs to a different state. For a pitching change, the deadline is the first pitch by the new pitcher. |
| Stale and suspended | Section 3.1 rule. |
| Windows | Dispatch from the schedule's first start minus 15 minutes; stop when every game on the date is final. Replayed live spans on forward dates run 369 to 767 minutes, so a day needs 2 or 3 windows of at most 330 minutes. The lock file plus the per-sport concurrency group prevent overlap, but today they also leave blind gaps at every handoff (below). |
| Ledger and grading | Section 3.1; finals from `mlb.fetch_results`. |
| Surface | Stage 0 only. |
| Caps | 150 credits a day proposed, counted per MLB official date; section 5. |

**Window handoffs.** Today a window is started only by a forward-capture slot
(every 13 minutes), whose dispatch check runs 4 to 15 minutes into the slot on
the checkout taken at job start: `scripts/capture_slot.sh:562` runs the check,
and the script's first `git fetch` and `git pull` are at lines 630 and 633
(run 34992480262: created 16:02:54Z, check 16:17:55Z; run 35017941084:
created 20:09:54Z, check 20:27:09Z). The running window rewrites
`data/live/<sport>/window.lock` to now plus 30 minutes on every tick
(`live_window.run`) and pushes it every 5 minutes, and `should_dispatch()`
returns HOLD while that expiry is in the future. A slot whose checkout predates
the ending window's last push sees an unexpired lock and holds, so each
handoff leaves roughly 15 to 30 minutes or more with no state rows. A trigger
in that gap leaves no row at all, not even UNPRICED, so time of day would
choose the sample. Design (R16-L5): the running window dispatches its
successor (`gh workflow run live-window.yml`) about 10 minutes before its
330-minute stop whenever a game is live or starts within 30 minutes; the
concurrency group (`cancel-in-progress: false`) queues the successor until the
first job ends; the lock expiry drops to two poll intervals; the dispatch check
in the slot reads the lock from origin, not from its own checkout. Every live
minute that no window covers is written as a `WINDOW_GAP` row (start, end,
reason) by the next window from the last state row before the gap, so gaps are
counted, never silent.

### 3.3 NFL

**State feed choice.**

| Option | Cost | What it carries | Verdict |
|---|---|---|---|
| The Odds API `/scores` | 1 credit per call (measured in `config/capture_families.json`; the vendor's v4 guide gives cost 1 without `daysFrom`, 2 with it). At 300 s: about 45 calls on a Thursday or Monday night, about 126 on a Sunday (1pm to about 11:30pm ET), about 216 a week, about 930 a month, all in the `live_capture` band. At 60 s, five times that. | Scores, completed flag, `last_update`. No clock, no quarter. NFL is covered (vendor sports list, "Scores & Results" column). | **Primary (default)** until R16-L13 passes on a confirmed BALLDONTLIE plan. Does not depend on BALLDONTLIE. |
| BALLDONTLIE `/nfl/v1/games` | No credits on a plan that serves it. The key is set (2026-09-15T17:28:10Z) but served at about 5 requests a minute, and the ALL-ACCESS trial ends about 2026-09-17 05:30Z with no paid continuation recorded (2.2). The vendor pricing page lists 600 requests a minute for ALL-ACCESS at $299.99 a month and 5 for the free tier. Polling every 15 to 30 seconds needs 2 to 4 requests a minute, which fits inside 5 only when nothing else (such as the harvest) uses the key at the same time; whether the plan in force after the trial serves this endpoint is unverified. | Per the spec summary: `status`, `status_state` (scheduled, in_progress, final and others), running scores, quarter-by-quarter scores; no clock field on the game record. Whether `status` says halftime is unverified. | Candidate only. Becomes primary only if R16-L13 shows, on the day, a measured rate at or above the polling need plus any concurrent use, a confirmed plan that serves the endpoint, and score updates at least as fresh as `/scores`. |
| BALLDONTLIE `/nfl/v1/plays` | As the row above. | The spec defines an `NFLPlay` record ("Play-by-play data for NFL games") with `period`, `clock_display`, `wallclock`, `home_score`, `away_score`, `scoring_play`. This pass's fetches of the spec were truncated and could not confirm the path itself; one reviewer read it as present. Unverified live. | Candidate clocked feed, same conditions as the row above; R16-L13 checks whether the newest play's `wallclock` is within 60 seconds of real time during a game. |
| Free unofficial scoreboard JSON from a broadcaster | Free | Usually clock, quarter, possession | Not recommended. No terms allow use in a paid product, nothing in the repo uses one, and at most it could be an internal timing reference with the owner's agreement. |
| nflverse | Free | Play-by-play after games, nightly | Not live. Useful for trigger-rate counts on 2025 (R16-L14). |

**Clock-based rules** wait for a clocked feed, and per the registered text of
LIVE_V0 entry 4, a real halftime marker replaces the elapsed-time proxy only by
a new registration.

| Part | Design |
|---|---|
| In-play price | The Odds API `americanfootball_nfl` h2h, 1 credit per capture, at triggers only. This is the NFL price source. BALLDONTLIE `/nfl/v1/odds` (moneyline, spread, total, `updated_at`) is a zero-credit candidate only under the same rate and plan conditions as its state feed, measured before use. |
| Trigger cadence | Every poll. Time-based triggers (the halftime proxy) are evaluated on every poll, not only on score changes (fixes D5). |
| Latency budget | Halftime proxy: capture within 300 seconds of T0 and inside the 80 to 100 minute window. Score-based triggers (proposed N1): within 60 seconds of T0, because an NFL price reacts to a score within seconds and the next kickoff follows within about two minutes. |
| Windows | From the schedule, each kickoff minus 15 minutes to final, replacing the fixed Thu/Sun/Mon windows so Friday, Saturday and international games are not dropped. `in_window()` is a scheduling choice, not part of any registered rule. This month: Thursday 2026-09-17 (DET at BUF, 5:15pm PT), Sunday 2026-09-20 (about 10am to 9pm PT), Monday 2026-09-21. |
| Stale, ledger, grading, surface | Section 3.1. |
| Caps | 100 in-play credits a day proposed; state polling separately in `live_capture` while The Odds API is the state feed, which is the default. |

### 3.4 Tennis

Conditional on trial checks in `docs/TENNIS_FEED_DECISION_2026-09-15.md` that
have not been run. That document is a buy plan ("Buy this instead, in this
order, trying each free first") with ten checks and no result recorded for any
of them; this design follows it and passes nothing on its behalf.

| Part | Design |
|---|---|
| State feed | BALLDONTLIE ATP and WTA `/matches` (`is_live`, game scores, `server`). Not confirmed: the key is served at about 5 requests a minute, the trial ends about 2026-09-17 05:30Z with no paid plan recorded, and the harvest of 2025 and 2026 matches stopped at 500 rows with HTTP 429 (2.2). Trial check 3 (server correct on 10 live matches) has not run; R16-L21 runs it before the trial ends or records it as not run, and R16-L17 stays blocked until it passes on a confirmed plan. Fallback that does not depend on BALLDONTLIE: API-Tennis Business as both state and price feed (its point-by-point log is trial check 6), only if the owner starts R16-22 (default skip). The Odds API `/scores` does not cover tennis (vendor sports list: no tennis entry is marked for "Scores & Results"). With neither, live tennis is not built. Singles only; Grand Slams, 1000s, 500s, 250s; no Challengers. |
| In-play price | **API-Tennis Business** ($80 a month after a 14-day trial): point-by-point log, in-play odds, suspension flag. The decision doc rules out The Odds API's in-play tennis prices for live rules ("refresh every 40 seconds, have no set-winner market and no suspension flag") and BALLDONTLIE's tennis odds (GOAT tier, match winner, most recent season). |
| Conditions to build | Owner starts the trial (R16-22, default skip); checks 6 to 10 pass (point log, second-set price within 120 seconds in at least 80% of matches, suspension flag at least 90% accurate and never priced while suspended, freshness median 10 s or less and worst 30 s or less, volume under the plan limit); a written yes to the three licence questions, without which live tennis stays internal research whatever the checks say; decision by trial day 12. If any fails, live tennis rules are marked unsupported and not built (R16-27). |
| Trigger cadence and latency | Every point update. Entry at the first unsuspended price updated at least 30 seconds after the trigger (the strategy lab's "declared delay"), deadline 120 seconds. Matches watched are chosen by a declared tournament tier, never by convenience. |
| Stale, ledger, grading, surface | Section 3.1; retirement and walkover grading recorded in a pre-registration before any tennis grade. |
| Caps | 0 Odds API credits. API-Tennis daily call volume is trial check 10. |

---

## 4. Rule families

### 4.1 The value test every live family uses (proposed)

This is the missing test statistic for LIVE_V0 (section 2.4). It must be
committed as an addendum before the first LIVE_V0 observation (R16-L1); the
adversarial reviewer decides whether it is an addendum or a new version
(`LIVE_V0.1`). It changes no trigger, floor or alpha. It does fix one
direction that the registered words leave open. Entry 3
(`mlb_starter_pulled_early`) says "the market under-reacts; the opponent's
moneyline is priced above its fair probability given the pitcher change"
(`docs/PREREG_MULTI_SPORT_2026-09-14.md`). Read as "the opponent's implied
probability is above its fair probability", the opponent bet should lose,
which contradicts "under-reacts". The addendum states the tested direction in
plain terms, "the opponent wins more often than its in-play price implies"
(the upper tail below), records that this resolves ambiguous wording, and the
adversarial reviewer rules on whether that needs `LIVE_V0.1`.

- **Primary (the gate).** Flat 1-unit profit at `logged_price`, vig included.
  Under the null each priced candidate wins independently with the probability
  its own price implies (1 / decimal price), so expected profit is zero. The
  p-value is the one-sided upper tail of total profit under that null, computed
  exactly by convolution (or from at least 100,000 simulated seasons), read
  once at the floor, at the family's alpha (LIVE_V0: 0.05/3).
- **Size of effect this can see.** Computed for n = 150, one-sided alpha
  0.05/3, power 80%: the win rate must beat break-even by about 12 points
  (40% to 51.9%, 45% to 57.0%, 50% to 62.0%), which is a return of +24% to
  +30% at those prices. At n = 300 the gap is about 8.5 points; at 600, about
  6. A null at a floor of 150 therefore rules out only a very large mispricing,
  and must be reported in those words.
- **Descriptive, never a gate:** the de-vigged in-play consensus at T0 against
  the result; the price five minutes after T0 against the logged price (a live
  analogue of closing-line value); results inside and outside the owner band;
  the UNPRICED share.
- **UNPRICED rows** count toward nothing, are published with the family, and a
  family whose UNPRICED share exceeds 30% at the read is reported as
  "unmeasurable at this feed" beside its result.
- **Quarantine.** The 25,407 side-effect in-play rows in
  `data/processed/odds_multibook.jsonl` (2.2) and any later ones are never
  joined to game outcomes for any live hypothesis. Feed-quality use without
  outcomes (quote age, books present, price at a state) is allowed.
- **After a pass.** A floor read that passes is SUPPORTED at floor, not
  promoted. Promotion needs a fresh confirmation registration on new games and
  the repo's full gate, G0 to G7 (`docs/ARCHITECTURE_BETTING_ENGINE.md`
  section 5: G0 record conformance, G1 grade audit, G2 budget, G3 settlement
  before collection, G4 store fidelity and truncation differential), whose
  last three read:
  "**G5 Ceiling** | A pre-registered cell clears its ceiling with placebo
  worlds run through the full argmax, world count from power analysis,
  effective tests reported."
  "**G6 Forward** | ≥300 forward selections with book, price, rating,
  counterarguments and settled close; ≥60 ledger days; class A/B;
  out-of-sample only; within sealed epochs."
  "**G7 Owner sign-off** | Explicit, dated, after G6."
  `docs/STRATEGY_LAB_PLAN_OF_RECORD.md` adds the battery and BH-FDR to "the
  full gate". Then the language rules.
- **The settled close for an in-play bet.** An in-play bet has no settled
  close, so G6 cannot currently be met for any live family. Proposed stand-in,
  to be registered before any live family claims G6: the de-vigged in-play
  consensus five minutes after T0 (the follow-up capture in 3.1), with the
  same fresh-price rule. Until that is registered, a live family can reach
  SUPPORTED at floor and no further.
- **Earliest dates, per rule** (point estimates, EXPLORATORY rates from 4.4 to
  4.5, about 15 games a day from a late-March opening day, net of the
  candidates expected in the rest of 2026): `mlb_favorite_trails_after_3`
  reaches 150 around the end of May 2027 and 300 confirmation selections in
  May 2028; `mlb_starter_pulled_early` reaches 150 around the end of August
  2027 and 300 confirmation selections between late July 2029 and April 2030.
  The confirmation ranges come from two readings of "about 15 games a day":
  15 on every day from opening day to the end of the regular season (early May
  2028, late July 2029), or a season capped at its 2,430 games (late May
  2028, April 2030); both include postseasons of about 43 games
  (`scratchpad/card_v2_revise/live_dates.py`);
  `nfl_favorite_trails_halftime` needs four to five seasons for 150. Only the
  proposed M2, counted from its registration, could finish both inside 2027
  (about August).

### 4.2 The owner band, for live

The pre-game owner band is "no lower than -150 or -160". The owner's ordering
rule, 2026-09-11, in his words (quoted in `docs/PLAYER_PROPS_NEXT.md`):

> "none of that price matters until we know it's a MORE THAN LIKELY BET, once
> we have the almost guaranteed bets, then we find the best sports picks of
> those with the best value, not the other way around."

"More than likely" means above 0.50. For live, proposed:

- **Price no worse than -150.**
- **In-play de-vigged market probability above 0.50** (the default, because it
  follows from the directive; about -105 to -110 or shorter after vig). This
  matches the pre-game gate in the Card V2 draft, "market number `> 0.50`"
  (`docs/PREREG_CARD_V2.md`, not yet registered).
- **0.40 is a departure, not the default.** A 0.40 floor (roughly +140 after
  vig) would admit bets the market itself makes more likely to lose, which is
  where trailing-favourite families cluster. It is used only if the owner
  answers yes to question 1 in section 8 (default no), with the share of
  triggers each floor removes in front of him. That share is unknown until
  R16-L9 has captured prices at V0, M1 and M2 trigger states; R16-L9 reports
  it for both floors.
- **M2 (a main-line total).** Both sides of a main total are priced near 0.50
  by construction, so an Under at the main line is close to a coin flip
  whatever the floor. The draft applied no likelihood floor to M2. M2 is
  registered only if the owner answers yes to question 2 in section 8
  (default no), before R16-L10.

The band cannot be added to LIVE_V0: it would change which candidates are
recorded, which is a new rule. For LIVE_V0 it is stored as a descriptive flag.
For proposed families it is part of the trigger.

MLB's own win probability cannot stand in for the in-play price when checking
band fit: in forward `gameflow_2026.jsonl` it gave exactly 0.500 for every tied
state and identical values for identical states, so it ignores team strength.
Band fit has to be measured from captured prices (R16-L9).

### 4.3 Where the MLB counts come from

EXPLORATORY trigger counts, no outcomes read. Store: `gameflow_2026.jsonl`
play rows dated 2026-08-28 onward (183 games, 2026-08-28 to 2026-09-09), plays
up to the trigger inning only. Pre-game favourite: per book, the newest
`odds_multibook.jsonl` row observed before `commence_time`, proportional
de-vig, at least 6 books, mean home probability; games mapped through
`event_game_map.jsonl` (resolved, not ambiguous). 121 of the 183 games had
such a consensus (9 dates, 2026-08-31 to 2026-09-09); 68 had a favourite at
0.55 or more, 36 at 0.60 or more. Season figures multiply the per-game rate by
2,430 regular-season games and assume every game is covered; ranges are 95%
Wilson intervals on the rate.

### 4.4 Registered: LIVE_V0 (`docs/PREREG_MULTI_SPORT_2026-09-14.md`, entries 2 to 4)

**LIVE_V0:mlb_favorite_trails_after_3:h2h**

| | |
|---|---|
| Trigger | Pre-game consensus favourite at 0.55 or more; the third inning has ended (`inning 3` and `inning_state End`, or top of the 4th with 0 outs); favourite trails by exactly 1 or 2 runs. |
| Side and market | Favourite, full-game moneyline, in play. |
| Price band | None registered; `in_band` stored. |
| Value test | 4.1, alpha 0.05/3, one read at 150. |
| Expected observations | 15 of 121 games (12.4%, interval 7.7% to 19.5%): about 301 a season (186 to 473). 150 needs about 1,210 games (771 to 1,958). Remaining 2026 (about 12 days at about 15 games, plus a postseason of at most about 43 games): roughly 22 to 28. Net of those, the floor is reached around the end of May 2027 on the point estimate (early May to mid-July 2027 on the interval), at about 15 games a day from a late-March opening day. |
| Pre-registration | Registered 2026-09-14. Addendum text needed: section 4.1 test, section 3.1 fresh-price and UNPRICED definitions, one trigger per game, stop date. |
| Retires when | The floor read gives p at or above 0.0167: TESTED_NULL, published with the effect-size sentence from 4.1. Or the floor is not reached by the end of the 2028 MLB postseason (proposed stop date): UNDERPOWERED, published without a read. |

**LIVE_V0:mlb_starter_pulled_early:h2h**

| | |
|---|---|
| Trigger | The favourite's starting pitcher (the first pitcher seen on the favourite's defence, fixing D12) leaves before completing four innings while the favourite leads or is tied. |
| Side and market | Opponent, full-game moneyline, in play. |
| Price band | None registered; `in_band` stored. |
| Value test | 4.1, alpha 0.05/3, one read at 150; upper tail, "the opponent wins more often than its in-play price implies" (the registered wording is ambiguous, see 4.1). |
| Expected observations | 7 of 121 games (5.8%, 2.8% to 11.5%): about 141 a season (69 to 278). 150 needs about 2,593 games (1,309 to 5,300). Net of about 10 to 13 candidates in the rest of 2026, the floor is reached around the end of August 2027 on the point estimate (early June 2027 on the upper bound; not within two full seasons on the lower bound). |
| Pre-registration | As above. |
| Retires when | As above. The proposed 2028 stop date binds only if the rate is near its lower bound. |

**LIVE_V0:nfl_favorite_trails_halftime:h2h**

| | |
|---|---|
| Trigger | Pre-game consensus favourite at 0.60 or more; first observation 80 to 100 minutes after kickoff, game not completed; favourite trails by 1 to 7. |
| Side and market | Favourite, full-game moneyline, in play. |
| Price band | None registered; `in_band` stored. |
| Value test | 4.1, alpha 0.05/3, one read at 150. |
| Expected observations | Not computed: no NFL in-game data on disk. Labelled estimate: a 0.60 favourite in roughly half of games and trailing by 1 to 7 at half in roughly a quarter of those gives about 0.125 a game (0.5 x 0.25), about 34 a season of 272 games, so 150 is four to five seasons away. R16-L14 replaces this with a count from 2025 play-by-play. |
| Pre-registration | As above. |
| Retires when | As above, with the stop date at the end of the 2028-29 postseason (proposed). If R16-L14 shows the floor cannot be reached by then, that is recorded and the rule keeps collecting cheaply; it is not re-registered with a lower floor. |

### 4.5 Proposed MLB families (LIVE_V1_MLB, not registered)

Registered together, with family-wise alpha 0.05/2 (M1 alone at 0.05 if
section 8 question 2 leaves M2 out), only after R16-L9 shows
band fit and freshness are workable and R16-L22 has recounted the triggers on
2025. A game can yield a candidate in both a V0 and a V1 family; the V1
document must state how that overlap is reported.

**How these were shaped, and what that costs.** M1's and M2's thresholds
(0.60, level at the end of the 4th to 6th; four runs through two innings) were
chosen after looking at trigger frequencies on forward games from 2026-08-28
to 2026-09-09 (4.3; no outcome was read). The data split says 2026-08-28 onward
is "forward proof, never folded back into tuning". Choosing a trigger by its
forward frequency uses that data for design, so: (1) no M1 or M2 evaluation
may use any game from 2026-08-28 up to the registration commit, which is why
the draft texts say "from the registration commit onward"; (2) before R16-L10,
R16-L22 recounts both triggers on the 2025 tuning season (free Stats API
play-by-play through `mlb.fetch_play_by_play`; pre-game favourites from
`data/archive/historical/odds_history/mlb_2025.jsonl.gz`, 600 h2h and totals
snapshots; how many 2025 games it prices before first pitch is counted in
R16-L22), and the 2025 counts,
not the forward ones, size the registration. The forward counts below stay
EXPLORATORY and size the work only.

**M1 `mlb_strong_favourite_level_mid_game`**

| | |
|---|---|
| Trigger | Pre-game favourite at 0.60 or more; score level at the end of the 4th, 5th or 6th inning (first occurrence only). |
| Side and market | Favourite, full-game moneyline, in play. |
| Price band | Logged price no worse than -150 and in-play de-vigged probability above 0.50 (0.40 only if the owner approves that departure, 4.2); a trigger outside the band is recorded with status `OUTSIDE_BAND` and is not a candidate. |
| Direction | The market prices a level game between unequal teams closer to even than the pre-game gap supports. |
| Value test | 4.1. |
| Expected observations | Tied at the end of the 4th: 5 of 121 games; 5th: 4; 6th: 3. The union is between 5 and 12 of 121 (not de-duplicated): roughly 100 to 240 a season before the band cut. Floor of 150 in one to two seasons. |
| Pre-registration text (draft) | "LIVE_V1_MLB:M1. When the pre-game consensus favourite (0.60 or more) is level at the end of the 4th, 5th or 6th inning, first occurrence per game, its in-play moneyline at the fresh median price, if no worse than -150 and above 0.50 de-vigged, wins more often than that price implies. Floor 150 priced candidates. Alpha 0.05/2. One read at floor. Stop at the end of the 2028 postseason. Forward data only, from the registration commit onward." |
| Retires when | Null at floor, or stop date without floor, or UNPRICED plus OUTSIDE_BAND above 50% of triggers after 60 triggers (the band makes it unmeasurable; published, not re-banded). |

**M2 `mlb_early_runs_total_under`**

| | |
|---|---|
| Trigger | Four or more combined runs through two complete innings. |
| Side and market | Under, full-game total, in play, at the main line. |
| Price band | Logged price no worse than -150. No likelihood floor: a main-line total sits near 0.50 on both sides, so M2 is not "more than likely", and it is registered only if the owner answers yes to question 2 in section 8 (default no) before R16-L10 (4.2). |
| Direction | In-play totals over-adjust to early scoring. |
| Value test | 4.1. |
| Expected observations | 24 of 121 games (19.8%, 13.7% to 27.8%), counted on the consensus games; about 482 a season (333 to 676). 150 in about 756 games (539 to 1,094): within half a season. |
| Pre-registration text (draft) | "LIVE_V1_MLB:M2. When four or more runs have scored in total through two complete innings, the in-play full-game Under at the main total, at the fresh median price no worse than -150, wins more often than that price implies. Push on landing exactly on a whole-number total. Floor 150. Alpha 0.05/2. One read at floor. Stop at the end of the 2028 postseason." |
| Retires when | As M1. |

Considered and not proposed: the favourite down one at the end of the 5th or
6th (8 of 121 games each) and down one to three after the 5th (18 of 121).
They were set aside because they buy a trailing favourite, as LIVE_V0 entry 2
already does. Their band fit is unmeasured: the Stats API win probability that
the draft leaned on ignores team strength (4.2), so it cannot say how these
states are priced. If R16-L9's captured prices show such states inside the
band, they can be proposed in a later registration, counted on 2025.

### 4.6 Proposed NFL family (LIVE_V1_NFL, not registered)

**N1 `nfl_favourite_concedes_first_touchdown`**

| | |
|---|---|
| Trigger | Pre-game favourite at 0.65 or more; the first scoring change of the game leaves the favourite behind by 6 to 8. Needs no clock. |
| Side and market | Favourite, full-game moneyline, in play. |
| Price band | No worse than -150, de-vigged above 0.50 (0.40 only on the owner's approval, 4.2). |
| Direction | The market over-reacts to an early underdog touchdown. |
| Value test | 4.1, alpha 0.05 (a family of one). |
| Expected observations | Labelled estimate only: roughly 0.1 a game, about 30 a season; 150 is about five seasons. |
| Pre-registration | Only if R16-L14's 2025 count shows the floor is reachable by the end of the 2029-30 season; otherwise recorded as "not registered: underpowered". |
| Retires when | Null at floor or the stop date. |

The NFL is where single-game live rules are weakest statistically: 272
regular-season games cannot fill a floor of 150 for any narrow situation in
under several seasons. Engineering effort on NFL live should stay small until
a count says otherwise.

### 4.7 Proposed tennis families (LIVE_T1, not registered; only if section 3.4's conditions pass)

From `docs/STRATEGY_LAB_PLAN.md` section 5, with triggers made exact.

**T1 `tennis_favourite_loses_first_set`**

| | |
|---|---|
| Trigger | Pre-match de-vigged favourite at 0.70 or more (The Odds API pre-match consensus, newest pre-start quotes); loses the first set; declared tournament tiers only. |
| Side and market | Favourite, match winner, in play; entry at the first unsuspended API-Tennis price updated at least 30 seconds after the set ends. |
| Price band | No worse than -150, de-vigged above 0.50 (0.40 only on the owner's approval, 4.2). |
| Value test | 4.1. |
| Expected observations | Labelled estimate: a few hundred a season across ATP and WTA tour-level singles. Not computable from what is on disk. The trigger needs 2025 first-set scores and a 2025 pre-match price: the BALLDONTLIE 2025 ATP and WTA matches files stopped at 500 rows each with HTTP 429, and its opening-odds endpoints returned HTTP 400 with 0 rows (2.2), so the harvest has no pre-match prices at all. A count needs The Odds API historical tennis odds for 2025 (10 credits per region per market per snapshot; coverage mostly Slams and 1000s, per the tennis decision doc) plus complete 2025 set scores from a confirmed source (tuning-only season, triggers only, no match results read). Until both exist, recorded as "not computable". |
| Retires when | Null at floor, stop date, feed decision reversed, or licence refused. |

**T2 `tennis_favourite_broken_early_in_deciding_set`**

| | |
|---|---|
| Trigger | Pre-match favourite at 0.60 or more is broken within the first three games of the deciding set. |
| Side and market | Favourite, match winner, in play, same entry rule. |
| Price band | Same (above 0.50 by default); expect a large OUTSIDE_BAND share, which is why it is second. |
| Value test | 4.1; family-wise alpha 0.05/2 with T1. |
| Expected observations | Unknown until counted. |
| Retires when | As T1. |

Not proposed: "momentum runs" (three games in a row) until it has an exact
definition that does not overlap T2.

---

## 5. Credits and costs

### 5.1 Where the balance stands

- Newest known balance in the local checkout: **20,473** at
  2026-09-15T21:03:53Z (`credit_log.jsonl`, re-read for this revision; the
  local copy may lag origin). Floor 5,000, so 15,473 spendable. Monthly allotment assumed about 100,000,
  reset assumed near the 1st (owner decision 8, still open).
- Pre-game capture (`live_capture` band) spent 251 to 576 credits a day from
  2026-09-05 to 2026-09-14, 3,987 in total, a mean of 398.7 (`budget.spent_today`
  by band). On 2026-09-15 to 21:03:53Z: 517 `live_capture` and 480 `probe`;
  band attribution between two rows follows the later row, so that split is
  approximate.
- About 15 days to an assumed 1 October reset: pre-game at about 400 a day uses
  about 6,000, leaving about 9,500 above the floor for NFL and tennis pre-game
  capture (new this week, not yet measured) and live.
- `LIVE_ODDS_DAILY_CAP` is 300 a day across all sports. It is not enforced
  until D6 is fixed.

### 5.2 MLB

Replay of the shipped any-change design (EXPLORATORY; forward
`gameflow_2026.jsonl` play timestamps for 2026-08-28 to 2026-09-09, 13 dates;
a 60-second tick costs 1 credit when any game changed score, inning, half or
pitcher; assumes the free feed shows a change within the same minute):
**195 to 336 credits a day, median 256**, counted per MLB official date. That
is not how the shipped cap counts. `budget.spent_today()` counts per UTC
calendar date (`_row_date` is `utc[:10]`), which resets at 8pm ET in the middle
of the evening slate, so one UTC day carries the previous night's late innings
plus that day's day games. Re-run with the same event model bucketed by UTC
date (EXPLORATORY; 14 UTC dates, the first and last partial): the 300 cap
would have run out on **5 of 14 UTC dates**, with the 300th credit at 16:21,
17:04, 17:11, 17:37 and 19:03 ET, dropping the start of that evening's games
by time of day. Per official date the same replay runs out on 2 of 13 dates.
MLB alone would use most of the shared cap and would leave nothing for NFL on
Thursdays, Sundays and Mondays. The proposed per-sport caps are counted per ET
slate day (3.1, R16-L3), so this boundary problem does not carry over to them.

Rule-gated design (proposed): LIVE_V0 MLB triggers averaged about 2.4 a day
on the counted games (15 plus 7 over 9 dates). At most 4 credits a trigger (one
capture, two retries, one follow-up) is **10 credits a day or less**. Adding M1
(0.6 to 1.3 triggers a day) and M2 (2.7 a day, at 2 credits a capture because it
adds totals) brings it to **about 40 a day or less**; the descriptive,
never-graded captures at M1 and M2 states before their registration (R16-L5)
cost the same. Proposed MLB cap 150 a
day. Rest of the 2026 regular season (about 12 game days) at 40: about 480; the
postseason plays 1 to 4 games a day, so well under that per day.

### 5.3 NFL

- State via The Odds API `/scores` at 300 s (the default state feed): about
  216 credits a week, about 930 a month, `live_capture` band. Via BALLDONTLIE:
  0 credits, but only on a confirmed plan at a measured rate (3.3); budget the
  930 until then.
- In-play at triggers: at most 4 credits a trigger; roughly 1 to 3 triggers a
  week for LIVE_V0 on the labelled estimate; **12 credits a week or less**.
- The side-by-side feed test on Thursday 2026-09-17 (kickoff 00:15Z on
  2026-09-18, after the trial ends) costs about 45 credits of `/scores`;
  Sunday 2026-09-20 about 126. BALLDONTLIE polling beside it runs only if the
  key is served that day (R16-L13); otherwise the credits buy `/scores` data
  and the comparison is recorded as not run.
- Proposed NFL cap 100 a day.

### 5.4 Tennis

- The Odds API: 0 credits for live (API-Tennis supplies in-play prices).
- API-Tennis Business: $0 during the 14-day trial, then $80 a month if the
  decision passes; cancel on the first day of any paid month without a
  decision (per the decision doc).
- BALLDONTLIE ATP and WTA: no confirmed plan. The ALL-ACCESS trial ends about
  2026-09-17 05:30Z; the vendor pricing page (read 2026-09-15) lists
  ALL-ACCESS at $299.99 a month and 600 requests a minute, ALL-STAR at 60 a
  minute, free at 5. The tennis decision doc's plan is ALL-STAR ATP plus WTA,
  $19.98 a month. Which plan, if any, continues is the owner's call.

### 5.5 Month view (rule-gated design, all three sports)

| | Per day | Per month |
|---|---|---|
| MLB in-play (live_odds) | 40 or less during the season | about 480 for the rest of September; postseason days less |
| NFL in-play (live_odds) | 0 to 10 on game days | about 50 |
| NFL state, The Odds API (default) | 45 to 126 on game days | about 930 (`live_capture`) |
| Tennis | 0 credits | $80 if API-Tennis passes; plus a BALLDONTLIE tennis plan if one is confirmed |
| Existing subscriptions | The Odds API plan (tier not recorded in the repo) | no new cost |
| BALLDONTLIE | trial ends about 2026-09-17 05:30Z; key served at about 5 requests a minute | unconfirmed; ALL-ACCESS lists $299.99 a month, ALL-STAR ATP plus WTA $19.98 |

---

## 6. Build order

Each item fits one working session. Acceptance checks are literal commands or
observations. Every code item follows Stage 16's run loop: named tests shown
failing on the pre-fix code first, then `python -m unittest discover -s tests -t .`,
commit by path, push. Fixtures for anything reading the schedule are built by
calling `mlb.parse_game()` on a raw schedule record, never hand-shaped. A
separate checker (not the builder) verifies each item's acceptance.

### MLB first (regular season ends about 2026-09-27; postseason from about 2026-09-29)

| Id | When | Item | Acceptance |
|---|---|---|---|
| R16-L1 | Tue 9/15, before any live fix is deployed | `docs/PREREG_LIVE_V0_ADDENDUM_2026-09-15.md`: section 4.1 test statistic and effect-size sentence; entry 3's tested direction in plain terms, recorded as resolving ambiguous wording; section 3.1 fresh-price, UNPRICED and one-trigger-per-game definitions, with the fixed mapping of 3.1 "Which fresh is registered": the mechanical classification of `last_update` (retrieval time, change time or undetermined, from R16-L9's pairs of unchanged prices), the fresh rule each classification selects, and the classification of every trigger row from the first window on from its stored per-book quotes, committed before the first window that can record a candidate; stop dates; quarantine of side-effect in-play rows; the statement that G6 cannot be met until an in-play stand-in for the settled close is registered. Adversarial review before commit, including a ruling on whether entry 3's direction needs `LIVE_V0.1`. | `git log --all --oneline -- evidence/live_candidates_v1.jsonl` prints nothing at the commit; `git log --format=%cI -1 -- docs/PREREG_LIVE_V0_ADDENDUM_2026-09-15.md` is earlier than `recorded_utc` in `head -1 evidence/live_candidates_v1.jsonl` once that file exists; the reviewer's verdict is quoted in the doc. |
| R16-L2 | Wed 9/16 | MLB pre-game context and keys (D1, D2, D3, D8, D12): consensus from each book's newest quote observed before `commence_time`, keyed by `event_id` through the gamekey map; favourite probability from `sides.home.consensus_probability`; string `game_pk` keys everywhere; starter as first pitcher seen on the favourite's defence; dispatch and stop treat a game as live when its `start_time_utc` is in the past and `mlb.game_state()` is neither `final` nor `cancelled` (`game_state` has no live value: it returns only `final`, `cancelled` or `pending`), and only future starts count as "within 30 minutes". Adds `scripts/live_pregame_check.py`. | `python -m unittest tests.test_live_window tests.test_livefeed_mlb tests.test_live_rules` green, with the new tests failing on the parent commit; `python scripts/live_pregame_check.py --sport mlb --date 2026-09-14` prints a favourite for every game with 6 or more pre-start books and 0 quotes observed at or after start; after the last final of a date, `python -m src.pipeline.live_window --should-dispatch --sport mlb` prints `HOLD` (seen in a forward-capture run log). |
| R16-L3 | Wed 9/16 | In-play credit accounting and caps (D6): `capture_inplay` logs the provider quota read from that call's own response headers (`x-requests-remaining`, and `x-requests-last`, "the usage cost of the last API call" per the vendor's v4 guide) with band `live_odds`; the `live_odds` spend and its caps are the sum of those per-call costs, not remaining-balance deltas, because two runners write credit rows at once and `spent_today()` bills each delta to the band of the later row in the local store (the chain's rows today are balance checkpoints: 164 of 165 carry `credits_used_last` 0). The pre-game envelope subtracts the per-call `live_odds` costs that fall inside its deltas once both logs are merged (R16-L4). Estimate from `odds.estimate_credits(markets, regions)`; per-sport caps (MLB 150, NFL 100, window 100) counted per ET slate day (MLB official date; ET kickoff date for NFL), written as a `slate_date` field on each row; `LIVE_SPORTS` switch; `LIVE_WINDOW_DISPATCH: ${{ vars.LIVE_WINDOW_DISPATCH }}` added to the "Capture one slot" step of `forward-capture.yml`. | `python -m unittest tests.test_budget_live_band tests.test_live_odds tests.test_creditlog tests.test_live_window_workflow` green, including: 40 synthetic captures give a `live_odds` spend of 40 and no change to `live_capture`; a two-writer test that interleaves chain and window spends, gives each budget view only its own recent rows, and asserts per-band totals equal the true per-call costs; a test whose captures cross 00:00Z counts them on one ET slate day; a test that `forward-capture.yml`'s capture step passes `vars.LIVE_WINDOW_DISPATCH`; after an in-play row, `can_spend("scores", 1)` is allowed; `python -m src.cli budget` shows the live_odds block with per-sport spend and names the day boundary. |
| R16-L4 | Wed 9/16 | Push path without credit-log conflicts (D7): the live window writes its credit rows to `data/live/credit_log_live.jsonl`; `budget` reads both logs merged in time order; the window stages only `data/live` and `evidence/live_candidates_v1.jsonl`. A union merge driver is rejected because it can reorder rows and break `spent_today`'s delta arithmetic. | A test with two temporary clones appending to their own stores and pushing within one minute ends with both commits on the remote and no rebase failure; on the first real window, `gh run view <run-id> --log` contains no `rebase failed` line and `git log origin/claude/sports-betting-analysis-review-g1o0co --oneline -- data/live` lists window commits. |
| R16-L5 | Thu 9/17 | Rule-gated capture, freshness and window handoffs (D5, D9): capture only on a registered trigger this poll, retries at T0 + 45 s and T0 + 90 s, 1 follow-up at T0 plus 5 minutes; a registry-status check in `live_rules.evaluate_all` (a rule not `registered` or forward-testing captures nothing); persist each book's `last_update`; fresh median with 3 books; MLB poll 20 s, reading the linescore from the hydrated schedule if it carries every field the rules read; time-based triggers on every poll. Descriptive, never-graded captures at M1 and M2 candidate states (h2h at level-game states, totals at four or more runs through two innings), billed to `live_odds`, written to a separate `data/live/odds_descriptive.jsonl` with `graded: never`, and quarantined from outcomes like the side-effect rows (4.1). Window handoff per 3.2: successor dispatched about 10 minutes before the 330-minute stop, lock expiry two poll intervals, dispatch check reads the lock from origin, `WINDOW_GAP` rows for uncovered live minutes. | A replay test feeding a recorded state sequence produces exactly the expected trigger rows and no more than 4 captures per trigger; a test that a rule marked retired in a temporary registry triggers no capture; a test that a window at minute 320 with a game live dispatches its successor; a test that a gap between two windows' state rows writes one `WINDOW_GAP` row with its start and end; `python -m unittest tests.test_live_odds tests.test_live_window tests.test_live_rules` green. |
| R16-L6 | Thu 9/17 | Ledger rows (D10): section 3.1 fields, UNPRICED statuses, one trigger per rule per game, refusal when any pre-game quote is at or after start. | `python -m unittest tests.test_live_ledger` green; `python -c "from src.appstate import live_ledger; print(live_ledger.verify())"` reports a valid chain on a test store; a test shows an unpriced trigger writes a row and blocks a later trigger in the same game. |
| R16-L7 | Fri 9/18 | Settlement from authoritative finals (D11): MLB from `mlb.fetch_results`; no VOID before 7 days; reason on every VOID; daily loop calls settle for yesterday and for any unsettled date in the last 7; settlement writes graded rows to the ledger and prints only counts (graded, voids, unsettled), never wins, losses or units, so the per-rule win-loss output leaves `scripts/daily_loop.sh:321-322` and every other log. | `python -m unittest tests.test_live_ledger tests.test_live_window` green, including a candidate with no final that stays unsettled and a test that the settle output contains no `wins`, `losses` or `units` key; `python -m src.pipeline.live_window --settle --date 2026-09-17` prints only `graded N voids N unsettled N` or "No unsettled candidates for this date"; `python -c "from src.appstate import live_ledger; print(live_ledger.verify())"` reports a valid chain afterwards. |
| R16-L8 | First night after L2 to L7 merge (target Fri 9/18) | First real MLB window, verified by a separate checker; supersedes R16-03's acceptance. | From `gh run list --workflow live-window.yml --json databaseId,startedAt,updatedAt,conclusion`: the first window started at or before first pitch minus 15 minutes, the last window ended at or after the last final, and every run concluded `success`; the checker lists each gap between one run's last state row and the next run's first, and every such gap has a `WINDOW_GAP` row whose minutes match, with a total of 5 minutes or less a handoff between first pitch and last final; `data/live/mlb/2026-09-18.jsonl` has rows on origin; every row in `data/live/odds_inplay.jsonl` carries `last_update`; `python -m src.cli budget` shows MLB live_odds spend of 150 or less for ET slate day 2026-09-18; the checker's independent recount of triggers from the day's state file equals the ledger's trigger rows; `live_ledger.verify()` valid. |
| R16-L9 | Fri 9/18 to Mon 9/21 (3 nights) | `docs/LIVE_FEED_QUALITY_MLB.md`: quote age and fresh books at triggers; the classification of `last_update` by the R16-L1 mapping (at least 10 pairs of unchanged prices at least 60 seconds apart; retrieval time, change time or undetermined, made once) and the share of books excluded for a `last_update` before T0, and before P under the change-time rule; T0-to-capture latency; UNPRICED share; Stats API lag against play timestamps; in-play price at trigger states, band fit reported only for families whose prices were captured (V0 h2h from triggers; M1 h2h and M2 totals from R16-L5's descriptive captures, never joined to outcomes), with the share of triggers removed by the 0.50 floor and by a 0.40 floor. BALLDONTLIE MLB odds `updated_at` against The Odds API only if R16-L13 has confirmed a paid plan and a measured rate; otherwise recorded as not measured. | The doc's script asserts at start that it reads no final score or result field, and prints the `last_update` classification computed with R16-L1's thresholds, with its pair count; each measure is reported with its n over at least 3 nights, and a measure with n under 10 is reported as unmeasured, never estimated; a named decision on whether M1 and M2 go to registration, which may be "not yet". |
| R16-L22 | Fri 9/18 to Mon 9/21 | Recount M1 and M2 triggers on the 2025 tuning season (4.5): Stats API play-by-play through `mlb.fetch_play_by_play` (free) for 2025 regular-season games in `data/historical/mlb_results.csv` (2,428 rows dated 2025), pre-game favourites from the newest pre-start quotes in `data/archive/historical/odds_history/mlb_2025.jsonl.gz`; triggers only, no final score or result read. Section in `docs/LIVE_FEED_QUALITY_MLB.md`. | The script refuses any season other than 2025 and asserts at start that it reads no final score or result field; it prints games with a pre-game favourite, trigger counts with 95% Wilson intervals for M1 and M2, and expected per-season counts; the numbers are quoted in R16-L10. |
| R16-L10 | Tue 9/22, after R16-L9 and R16-L22 | `docs/PREREG_LIVE_V1_MLB.md` (M1, M2) with adversarial review; registry rows; sized from R16-L22's 2025 counts; the owner's dated answers to section 8 questions 1 (0.40 floor, default no) and 2 (M2 registered, default no), recorded in the doc, with M1 at a floor above 0.50 unless question 1 is yes and M2 left out unless question 2 is yes; excludes every game from 2026-08-28 to the registration commit and says why (4.5). | Registry rows in `data/research/alpha_registry.jsonl` and the doc commit are earlier than the first M1 or M2 row in the ledger (`git log --format=%cI -1 -- docs/PREREG_LIVE_V1_MLB.md`). |
| R16-L11 | Wed 9/23 | Wire M1, and M2 only if R16-L10 registered it (totals in-play capture on the M2 trigger only). | Replay tests for both triggers and the OUTSIDE_BAND status green; a postseason or late-September window logs M1 or M2 trigger rows with `prereg_commit` equal to the L10 commit. |

### NFL next

| Id | When | Item | Acceptance |
|---|---|---|---|
| R16-L12 | Wed 9/16 to Thu 9/17 before 5:15pm PT | NFL keys and halftime proxy (D4, D5): pre-game context and states keyed by The Odds API `event_id` with the nflverse `game_id` alongside; halftime proxy on every poll; schedule-driven windows. | A replay test with an NFL scores sequence and no score change between minutes 80 and 100 fires the proxy once; `python -m unittest tests.test_livefeed_nfl tests.test_live_window` green; the forward-capture log on 2026-09-17 after 23:45Z shows `DISPATCH` for nfl (`gh run view <run-id> --log` around `live-window dispatch check (nfl)`); Thursday's window completes, and `python -c "import json,sys; s,e=sys.argv[1:3]; print(sum(1 for l in open('data/live/credit_log_live.jsonl') if l.strip() and (r:=json.loads(l))['caller']=='livefeed_nfl.poll' and s<=r['utc']<e))" <startedAt> <updatedAt>`, with the window run's timestamps from `gh run view <run-id> --json startedAt,updatedAt`, prints 60 or less (each `livefeed_nfl.poll` row is one `/scores` call at 1 credit, `config/capture_families.json`). |
| R16-L13 | Thu 9/17 and Sun 9/20, conditional | NFL state feed side by side, run only if, on the day: the owner has confirmed which BALLDONTLIE plan the key is on after the trial (which ends about 2026-09-17 05:30Z, before Thursday's 00:15Z kickoff), and a rate probe before kickoff measures at least the polling need (2 requests a minute at 30 s, 4 at 15 s) plus anything else using the key. Then BALLDONTLIE `/nfl/v1/games` every 30 s beside The Odds API `/scores`, and, if the path is served, `/nfl/v1/plays`; `docs/LIVE_FEED_DECISION_NFL.md` with the probe result, detection lag per scoring change, whether `status` marks halftime, and whether the newest play's `wallclock` is within 60 seconds of real time. Until this passes, The Odds API `/scores` is the NFL state feed. | Either the doc records the condition that failed ("not run: plan unconfirmed" or "not run: measured N requests a minute") with The Odds API named as primary, or: at least 20 scoring changes timed on both feeds, the measured rate, a named primary feed, and the `wallclock` check result; in both cases `git grep -n "BALLDONTLIE_API_KEY"` shows only environment reads, never a value. |
| R16-L14 | Fri 9/18 | NFL trigger-rate count on 2025 play-by-play (tuning-only season; triggers only, no final scores read): expected per season for LIVE_V0 entry 4 and for N1. | Script plus a section in `docs/LIVE_FEED_DECISION_NFL.md`; the script refuses any season other than 2025; a recorded yes or no on registering N1. |
| R16-L15 | Mon 9/21 | Only if L14 says yes: `docs/PREREG_LIVE_V1_NFL.md` (N1) with adversarial review, then wiring. | Registry row and doc commit earlier than the first N1 ledger row; replay test for the first-scoring-change trigger green. |

### Shared surface

| Id | When | Item | Acceptance |
|---|---|---|---|
| R16-L16 | Tue 9/22 | Internal live page v1 (Stage 0): per rule "N of 150 tested", trigger rows with status, time and row age ("seen N minutes ago"), the sentence "in-game prices change within seconds and this one may already be gone" on every priced row, no win-loss before the read, section 7 wording. | `python -m unittest tests.test_web_live_page tests.test_api_live tests.test_customer_language tests.test_web_structure` green, with a new test in `tests.test_web_live_page` that `renderCandidateRow` renders "may already be gone" and a "minutes ago" age on every candidate row; staging `#/live?sport=mlb` screenshot at 390 px wide shows the counts, the "research, not a pick" chip, the "may already be gone" sentence and row age on each row, and no profit figure. |
| R16-L20 | Not scheduled; required before any Stage 1 work, and only once a family has passed the full gate | Stage 1 delivery path (3.1): a runner-to-server write (for example a signed POST from the window runner to the web app, or a push service) replacing git push plus the `raw.githubusercontent.com` read for live rows. | Over 20 captures, capture-to-render latency is measured from `capture_observed_utc` to the time the row first renders on staging, and p95 is at or under 20 seconds; until this passes, no Stage 1 row expiry or alert is built. |

### Tennis last, only if the feed decision passes

| Id | When | Item | Acceptance |
|---|---|---|---|
| R16-L21 | Before 2026-09-17 05:30Z (trial end) | BALLDONTLIE tennis trial check 3 from `docs/TENNIS_FEED_DECISION_2026-09-15.md`: on 10 live singles matches, compare `server` and game score to the official live score every few minutes, at a pace the key's measured rate allows alongside the harvest. | Results recorded in `docs/TENNIS_FEED_DECISION_2026-09-15.md` under check 3 with the match ids, times and pass or fail; or, if not run before the trial ends, recorded there as "not run" and R16-L17 marked BLOCKED in the roadmap. |
| R16-L17 | BLOCKED until R16-L21 passes and a BALLDONTLIE tennis plan is confirmed after the trial | `src/pipeline/livefeed_tennis.py`: BALLDONTLIE ATP and WTA live state into `data/live/tennis/<date>.jsonl`, internal, zero credits. | Runner log shows rows for at least 10 live matches with `server`; `python -m unittest tests.test_livefeed_tennis` green; `grep -c tennis data/processed/credit_log.jsonl` unchanged by the poller. |
| R16-L18 | Only if the owner starts R16-22 | API-Tennis Business trial checks 5 to 10 into `docs/API_TENNIS_TRIAL_RESULTS.md`; decision by trial day 12. | Each check has its measured number and pass or fail; the licence answer is quoted or recorded as "no written yes"; the decision is recorded in R16-22. |
| R16-L19 | Only if L18 passes and the licence is a written yes (this is R16-27) | `docs/PREREG_LIVE_T1.md` (T1, T2) with adversarial review; then the API-Tennis adapter and wiring. | Registry rows and doc commit earlier than the first tennis ledger row; replay tests for both triggers with the 30-second entry delay green. |

---

## 7. Risks, and the honest wording

### 7.1 Risks

- **Statistical.** Floors take one to five seasons (4.4 to 4.6). A floor of 150
  detects only a mispricing of about 12 win-rate points. Several families on the
  same games are not independent; family-wise alpha controls the count of
  tests, not the dependence, and each registration must say how overlap is
  reported.
- **Selection by availability.** Unpriced triggers, a cap counted per UTC date
  that runs out in the late afternoon or early evening ET (5.2), and blind
  gaps between windows (3.2) all choose the sample by time of day. Rule-gated
  capture, UNPRICED rows, one trigger per game, ET slate-day caps and
  `WINDOW_GAP` rows are the counter.
- **Freshness selection.** If `last_update` is a change time, "`last_update`
  at or after T0" drops the books that repriced fastest, before our lagged T0
  (3.1). R16-L1 commits a mechanical classification and the fresh rule for
  each outcome before any window can record a candidate, R16-L9 applies it
  once, and every read reports the excluded share, so no one chooses the
  reading after seeing rows.
- **Stale and suspended prices.** 10% of the chain's stored in-play quotes were
  over 139 seconds old and 1% over 768 seconds. A price that predates the
  trigger is not a price anyone could take after the event.
- **Feed lag and adverse selection.** Books see the field faster than a free
  feed. The fresh-price rule keeps only prices updated after we saw the
  trigger; it cannot prove the price reflected the event, only that it came
  after it.
- **Point in time.** The pre-game favourite must use only quotes observed before
  start; the same store holds tens of thousands of in-play rows (D2).
- **Contamination.** Joining the side-effect in-play rows, or any live store,
  to outcomes before a registration spends that data. The quarantine in 4.1
  exists for this.
- **Operational.** The pipeline has never run; D1 to D11 were found by reading
  and small checks, not by a live night. Jobs are capped at 350 minutes, days
  need several windows, and the push path is untested under real concurrency.
- **Vendor.** BALLDONTLIE is served at about 5 requests a minute on a trial
  that ends about 2026-09-17 05:30Z, with no paid plan confirmed (2.2). Nothing
  in the MLB design depends on it; NFL defaults to The Odds API `/scores`;
  tennis live has no confirmed state feed without it or API-Tennis.
- **Credits.** The cap is not enforced until R16-L3; the reset date is assumed.
  Balance deltas bill spend to the wrong band when two runners spend at once,
  which is why R16-L3 bills in-play spend per call.
- **Licences.** BALLDONTLIE's terms allow betting products and storage (per the
  tennis decision doc). The Odds API allows displaying derived values.
  API-Tennis is unconfirmed. Free broadcaster feeds carry no permission.
- **Expectation.** A rule that buys a trailing favourite is not a
  high-confidence bet, and a live pick that expires in 90 seconds needs alerts
  and a delivery path the product does not have (rows reach the page up to
  about 6 minutes after capture today, 3.1). A pass is years away for most
  rules; the likely first result for any of them is a null, which is
  published.
- **Hard rule.** No bet-placement code, ever. The system records prices; it
  never places or links to a bet slip.

### 7.2 Customer wording

**Stage 0 (now, internal page only).**

- Page notice (unchanged): "Live analysis is in internal testing. No alerts are
  sent."
- Under it: "These are tests of ideas about in-game prices, written down before
  the first game. None has been shown to win."
- Row chip (unchanged): "research, not a pick".
- Row: "Phillies to win, in play, +125 seen at 8:14:05 pm ET (seen 3 minutes
  ago); in-game prices change within seconds and this one may already be gone.
  Idea: a favourite behind by one or two after three innings." Nothing records
  the price at the next pitch, so the row never says the price was gone, only
  that it may be.
- Unpriced row: "The situation happened at 8:14 pm ET, but no current price was
  available within two minutes. Counted as untested."
- Rule line: "38 of 150 tested. We read the result once, at 150, and publish it
  whether it won or lost."

**Stage 1 (only for a family that has passed the full gate).**

- "Live: Phillies to win, if you can still get +110 or better. Seen at 8:14:05 pm
  ET; this row is removed at the next pitch, and the price may be gone
  sooner."
- "Why this is here: this in-game situation has been tested on 312 games since
  2026-09-18 under a rule written before the first one. Record at the prices
  seen: W-L, units. That is a record, not a promise. Live prices move in
  seconds; if yours is worse, skip it."

**Never, at any stage:** "value", "edge", "lock", "+EV", "sharp", "steam",
"guaranteed", "can't lose", a best-book comparison, a countdown that urges a
bet, or a live reading on the card or its record. Stage 1 text must also pass
`tests/test_customer_language.py`.

---

## 8. Owner decisions this needs

Each question is one yes or no, with the default every draft in this document
uses until Brey answers. Brey answers each himself, or explicitly accepts its
default; nobody else may accept a default for him. Both are put to him after
R16-L9 has reported the share of triggers each floor removes and before
R16-L10, and each answer is recorded with its date in the pre-registration
that relies on it (for MLB, `docs/PREREG_LIVE_V1_MLB.md`). After that
registration's commit a different answer needs a new registration.

1. **May a live family use a 0.40 in-play likelihood floor instead of above
   0.50? Default: no.**
   Departs from "none of that price matters until we know it's a MORE THAN
   LIKELY BET" (2026-09-11): a 0.40 floor admits bets the market itself makes
   more likely to lose. Under no, M1, N1, T1 and T2 need an in-play de-vigged
   probability above 0.50 (4.2).
2. **May M2, an in-play main-line Under priced near 0.50 by construction, be
   registered although it is not more likely than not? Default: no.**
   Departs from the same directive. Under no, R16-L10 registers M1 alone at
   alpha 0.05, R16-L11 wires M1 only, and R16-L5's descriptive totals captures
   at M2 states stop once the answer is recorded. M2 is the only proposed
   family that could finish both its floor and its confirmation inside 2027
   (4.1).

---

## Review record

Three independent adversarial reviewers (evidence and statistics; owner
intent, customer truth and buildability; live system reality) reviewed the
draft on 2026-09-15. Each finding below was re-checked against the repo, `gh`
and the vendor pages before it was applied. Some were already partly present
in the draft when this revision started (marked "completed"). No finding was
rejected. Where the applied fix differs from the reviewer's wording, the
reason is given.

**High**

| # | Finding | Decision | Where and why |
|---|---|---|---|
| H1 | BALLDONTLIE treated as a working 600-a-minute ALL-ACCESS feed blocked only on the secret | Applied | 2.2, 2.4, 3.2, 3.3, 3.4, 3.1 grading, 5.3 to 5.5, 7.1, R16-L9, R16-L13, R16-L17, R16-L21. Verified: secret set 17:28:10Z (`gh secret list`); manifest on origin shows 429s at 500 rows and HTTP 400 on opening odds; trial ends about 2026-09-17 05:30Z (R16-33). The Odds API `/scores` is the NFL default; MLB never depended on it; tennis falls back to API-Tennis or is not built. |
| H2 | Stage 1 expiry and alerts cannot work over git push plus a 60-second raw read | Applied (completed) | 3.1 already named the delivery path; this revision states Stage 1 is not buildable on the current architecture and adds R16-L20 with the literal p95 20-second acceptance. Verified `live_remote.py:9,31,63` and `run(commit_every_minutes=5)`. |
| H3 | R16-L9 cannot measure M1/M2 band fit because capture is h2h-only and V0-triggered | Applied | R16-L5 adds descriptive, never-graded h2h and totals captures at M1 and M2 states, quarantined from outcomes; R16-L9 reports band fit only for captured families, with n, and n under 10 as unmeasured. Verified `live_odds.DEFAULT_MARKETS = ("h2h",)`. |

**Medium**

| # | Finding | Decision | Where and why |
|---|---|---|---|
| M1 | Freshness rule ignores the 40-second in-play refresh and the meaning of `last_update` | Applied (completed) | 3.1 already carried the refresh, the T0 + 45 s and T0 + 90 s retries and the reading question; this revision cites the refresh in 3.2, makes R16-L9 measure the field's meaning and the excluded share, and puts the reading in R16-L1. This pass's read of the v4 guide found no definition of `last_update`, not the "retrieved" definition the reviewer quoted, so the doc keeps "undefined, measure it". |
| M2 | Blind gaps between windows, unmeasured | Applied, acceptance bound changed | 3.2 "Window handoffs", R16-L5, R16-L8. Verified the lock logic in `live_window.run` and `should_dispatch`, the slot's check before its first pull, and both runs' timings. The reviewer's "gap minutes equal 0" is replaced by `WINDOW_GAP` rows for every uncovered minute and at most 5 minutes a handoff, because a successor queued behind the concurrency group cannot start with zero delay. |
| M3 | The 300 cap was replayed per official date; the shipped cap counts per UTC date | Applied | 5.2, 2.4, 3.1 caps, R16-L3, R16-L8, 7.1. Re-ran the reviewer's script: 5 of 14 UTC dates reach 300, at 16:21 to 19:03 ET; the draft's script still gives median 256 and 2 of 13 per official date. Proposed caps are per ET slate day. |
| M4 | Credit accounting bills spend to the wrong band with two writers; tests use one store | Applied, refined | R16-L3 bills `live_odds` by each call's `x-requests-last` and adds a two-writer test. Refinement: the chain's own rows are balance checkpoints (164 of 165 today log `credits_used_last` 0), so per-call billing covers the window's calls and the pre-game envelope subtracts them from its deltas. |
| M5 | The daily loop already prints interim win-loss; R16-L7 required printed graded rows | Applied (completed) | 2.3 and 3.1 already stated it; the line reference is corrected to `scripts/daily_loop.sh:321-322`, and R16-L7's acceptance now checks counts only, no `wins`, `losses` or `units`, and a chain verify. |
| M6 | Full gate shrunk to 300 selections and 60 days; G6 "settled close" undefined in-play; dates wrong | Applied (completed) | Section 1 already named G0 to G7; 4.1 now quotes G5 to G7, proposes the T0 + 5 minute consensus as the registered stand-in (G6 unmet until then), and gives dates per rule, recomputed net of 2026 candidates. |
| M7 | A 0.40 likelihood floor misstates "more than likely" | Applied | 4.2 quotes the directive from `docs/PLAYER_PROPS_NEXT.md`, sets above 0.50 as the default and 0.40 as a departure needing the owner's written approval, with R16-L9 reporting the share each removes; M1, N1, T1, T2 and R16-L10 follow. M2 (a main-line total, near 0.50 by construction) is flagged as an owner decision. |
| M8 | Stage 0 wording asserts "the price was gone"; no staleness text; R16-L16 does not check it | Applied | 7.2 wording and row age; R16-L16 adds a literal test in `tests.test_web_live_page` and the 390 px screenshot check. Verified `renderCandidateRow` has no staleness text. The Stage 1 line is reworded the same way. |
| M9 | Two kill switches are not usable as listed | Applied | 3.1 table marks `LIVE_WINDOW_DISPATCH` not usable (`capture_slot.sh:556` default 1; not passed by `forward-capture.yml`) and rule status not built (no live code reads the registry); R16-L3 and R16-L5 build both with tests. |
| M10 | M1/M2 were shaped on forward 2026 data; rejection sentence rests on Stats API win probability | Applied | 4.5 states the thresholds were chosen after viewing forward frequencies, excludes 2026-08-28 to the registration commit and says why, adds R16-L22 (2025 recount from free play-by-play and `mlb_2025.jsonl.gz` pre-game odds) before R16-L10, and drops the rejection sentence. |
| M11 | Tennis depends on unrun, unscheduled feed checks and a count source that does not exist | Applied | 3.4 is conditional on the unrun checks; R16-L21 runs BALLDONTLIE check 3 before the trial ends or records "not run" and blocks R16-L17; T1's count is "not computable" until 2025 pre-match prices (The Odds API historical) and complete set scores exist. |

**Low** (applied): L1 `/nfl/v1/plays` added to 3.3 and R16-L13 as a candidate,
with the path itself marked unconfirmed because this pass's spec fetches were
truncated; L2 NFL estimate corrected to 0.125 and about 34 a season, the
starter rule's stop-date sentence reconciled, floor dates recomputed net of
2026 candidates, poll rate corrected to 0.8 a second with the hydrated-schedule
option; L3 R16-L2, R16-L8 and R16-L12 acceptances made literal (`game_state`
has no live value); L4 entry 3's tested direction stated in 4.1, 4.4 and
R16-L1 for the reviewer's ruling.

### Verification pass

An independent verifier then checked every high and medium finding above
against this text and the repo and found them resolved, except for three new
problems and one low item, all re-checked and applied here. None was rejected.

| Severity | Finding | Decision | Where and why |
|---|---|---|---|
| medium | The evidence-rules header let customer text claim an edge or a guarantee once the full gate passed, against the standing rule, 7.2 and `NEGATION_ONLY` in `tests/test_customer_language.py` | Applied | Header now reads "customer text never claims an edge or a guarantee". Verified the `NEGATION_ONLY` entries for `edge` and `guaranteed`. The registration's 11.8 was corrected the same way |
| medium | The reading of "fresh" was to be fixed from R16-L9's measurement after LIVE_V0 rows, and public graded rows, already existed, with no stated mapping | Applied | 3.1 "Which fresh is registered" now fixes, in R16-L1 before the first window that can record a candidate: a mechanical classification of `last_update` (at least 10 pairs of unchanged prices at least 60 seconds apart, 90% thresholds, made once); the fresh rule for each outcome (retrieval time or undetermined: at or after T0 and at most 60 seconds old; change time: at or after the triggering event's time P, no age limit); and classification of every trigger row from its stored per-book quotes, with appended classification rows. R16-L1, R16-L9, 7.1 and the suspension paragraph follow. Verified that `mlb.fetch_play_by_play` returns the raw play-by-play payload and that the repo's parser already reads `about.startTime` from it (`src/providers/mlb.py:1006-1008,1137`); `about.endTime` was not checked against a live response in this pass, so R16-L1 confirms the field before committing |
| medium | The 0.40 floor and M2 were owner decisions without yes/no questions or defaults, and R16-L10 relied on "recorded answers" to unstated questions | Applied | New section 8 with two questions, each with default no, answered by Brey himself and dated in the relying registration; 4.2, M2, 4.5, R16-L10 and R16-L11 point to them |
| low | Section 1's "late May 2028" works out nearer early May on the doc's own inputs | Applied, as a range | Recomputed (`scratchpad/card_v2_revise/live_dates.py`): 15 games on every day of the season gives early May 2028; a season capped at its 2,430 games gives late May. The doc used both inputs, so 1 and 4.1 now give May 2028 with both readings. The same arithmetic moved `mlb_starter_pulled_early`'s confirmation from "not before late 2029" to between late July 2029 and April 2030. M2's "about August 2027" holds on both readings |
