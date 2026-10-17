# Pre-registration: does a posted lineup move the market afterwards, and does a bet at the first capture after it beat the close?

**Rule id:** `INFO_TIMING_V1`
**Registry id:** `INFO_TIMING:lineup_post_first_capture_clv:hitter_props`
**Family:** `INFO_TIMING` (one hypothesis; five markets reported; the verdict rides
on one pooled hitter-prop test, section 7)
**REGISTERED_UTC:** the committer time of the commit that adds this file (read it
with `git log --format=%cI -- docs/PREREG_INFO_TIMING.md`). The registry row is
appended in the same commit; its `note` carries the sha256 of this file with line
endings normalised to LF. **Freeze check:** recompute that sha256 and compare it to
the note before reading any result. A mismatch voids the registration.

**Status: PAPER MEASUREMENT OF PRICE MOVEMENT AND CLOSING-LINE VALUE. No bet, no
outcome, no return.** It changes no live number, shows nothing to a customer and
licenses no promotion. Nothing here reads who won a game or whether a prop went
over.

---

## 0. What exists before this registration, stated so a reader can check it

- **No harness exists yet.** `src/research/info_timing.py`,
  `scripts/info_timing_measure.py` and `tests/test_info_timing.py` are written
  AFTER this commit. No consensus price, price movement or CLV has been computed
  by this study on any row. Nothing has been run.
- **Prior results that motivated this, read in full before writing:**
  `docs/research/loss_diagnosis/00_SYNTHESIS.md` and `03_prices.md`. They report,
  on the card's own entries, that the prop consensus moved toward our selections
  after the quote by +0.53 points [+0.12, +0.89] (n=56) and that the
  taken-minus-refused gap was +0.74 [+0.32, +1.07]; that prop captures run at about
  04:00Z plus one to three gate captures, the last usually near 22:00Z, a median 110
  minutes before first pitch; and that moneyline closes are a median 13 minutes out.
  This study is a different population (every contract touched by a lineup posting,
  not our picks) and a different timing anchor (the posting, not our quote), so it
  is not a replication of those numbers and cannot be rescued by them.
  `docs/EVENT_DIRECTION_RESULT.md` (an earlier UNDETERMINED event-direction probe)
  and `src/pipeline/rosterwatch.py` (how lineup postings are bracketed) were read
  for method.
- **What was looked at while designing it, structure and counts only:**
  - `data/watch/lineups_watch.jsonl`: 4,434 rows; 3,852 poll markers
    `{fetched_utc, game_date, poll}`, 24 undated markers, 558 lineup change rows
    `{away_lineup, home_lineup, fetched_utc, game_pk}` (lists of person ids);
    fetched_utc from 2026-08-31T05:42Z to 2026-10-16T23:07Z. No sealed row.
  - `data/processed/batter_props.jsonl`: 173,762 rows, fields `away_team, book,
    book_last_update, commence_time, event_id, game_date, home_team, line, market,
    observed_utc, player, price, selection, side`; markets and row counts
    (total bases 46,201, hits 35,341, plus four other markets); game_date
    2026-09-03..2026-10-16 (40 dates).
  - `data/processed/odds_multibook.jsonl` and
    `data/processed/archive/odds_multibook/*.jsonl.gz`: field names for h2h (no
    `market` key), `spreads` (`away_line, home_line`) and `totals` (`total,
    over_price, under_price`); row counts 390,413 / 319,475 / 327,819.
  - `data/processed/prop_listing.jsonl`, `prop_prices.jsonl`,
    `event_game_map.jsonl`: field names and row counts only; the event map has
    2,814 resolved unambiguous rows, 108 ambiguous, 17 unresolved; its last row
    shows an odds `commence_time` two hours earlier than the MLB
    `schedule_commence_time` (the reason section 3 takes first pitch from MLB
    sources).
  - `data/raw/oddsapi/2026/09/08/`: 231 envelopes `{captured_utc, kind, payload}`,
    214 `event` (props) and 17 `featured` (game lines).
  - `data/historical/lineups.jsonl`: row shape `{date, game_pk, away, home,
    observed_utc}` with `{name, order, person_id, position}` per batter; per-month
    row counts. `data/historical/handedness.json`: id to `{bats, name, throws}`.
  - `data/processed/boxscores_2026.jsonl`: field names and row `type` counts for
    dates on or after 2026-08-28 only.
  - `data/historical/mlb_results.csv`: header; 266 games dated 2026-09-08..10-15
    (234 `R`, 16 `D`, 9 `F`, 7 `L`), all with `start_time_utc`.
  **No price was converted, compared or aggregated; no capture cadence or capture
  lag was computed; no outcome column was read for any row.**
- **Disclosed:** the `mlb_results.csv` count above was taken with `csv.DictReader`,
  which decoded every row, including rows dated inside the sealed window, in memory
  before the window filter discarded them. Nothing from a sealed row was printed,
  counted or used. **`sealed_untouched` is therefore recorded as false**, as the
  house rule requires when sealed bytes were decoded at all. The harness reads
  `mlb_results.csv` by testing each raw line's date text before parsing it.

## 1. Evidence rules this registration obeys

- Forward captures only, game dates **2026-09-08..2026-10-15**. No 2025 row. No row
  dated 2026-01-01..2026-08-27 is read; the harness raises `SealedDataError` on any
  such date and drops out-of-window raw lines before parsing them.
- Pre-registration before inference. One rule, one pass, fixed constants below.
- Every loser is published. A null, or "the capture cadence cannot see this", is a
  valid result and will be written up as such.
- Line-shopping value is PRICE IMPROVEMENT, never EV or edge. The decisive CLV is
  measured at the board AVERAGE price, never the best price (section 5).

## 2. Hypothesis, fixed

> After a team's batting order first becomes observable (a `lineup_posted` event
> bracketed by our own polls), the de-vigged consensus on the contracts that posting
> favours (section 4) keeps moving toward the favoured side between the first
> capture after the posting and the last capture before first pitch (M1 > 0), and
> **betting the favoured side at the board-average price of that first capture
> beats the pre-pitch closing consensus** (M2 > 0, interval above zero), on hitter
> props.

## 3. Data, exactly

- **Information events.** `src.pipeline.rosterwatch.events(data/watch)` class
  `lineup_posted`, admissible only (`inadmissible` false: an earlier poll of the
  same slate saw the side without a lineup). Unit time **`t_info` = the interval
  END** (the poll that first saw the lineup): the earliest moment WE could know it.
  The interval START is recorded (bracket width reported). The posted lineup is the
  `{side}_lineup` list on the change row with `fetched_utc == t_info`; it must hold
  **exactly 9 distinct person ids** or the event is excluded (`PARTIAL_LINEUP`).
- **Game identity and first pitch.** `game_pk` from the watch row. Game date, teams
  and `start_time_utc` from `data/historical/mlb_results.csv` (raw line date tested
  before parsing; only `game_pk, date, start_time_utc, game_type, away_team,
  home_team, double_header` are kept; **score columns are never read into any
  structure**). **First pitch = the earlier of `start_time_utc` and the event map's
  `schedule_commence_time`** (both MLB schedule sources). The odds API
  `commence_time` is not used as a cutoff (it disagreed with the MLB schedule by two
  hours on an inspected row) but disagreements are counted. Games with
  `double_header` other than `N`, or on any ambiguous event-map row, are excluded
  (`AMBIGUOUS_EVENT`); games with no first pitch are excluded (`NO_FIRST_PITCH`);
  events with `t_info >= first pitch` are excluded (`POSTED_AFTER_FIRST_PITCH`).
- **Event to odds.** `data/processed/event_game_map.jsonl`, resolved and not
  ambiguous, `event_id -> game_pk`; a game_pk named on any ambiguous row (or as an
  ambiguous candidate) is refused, as in `scripts/diagnosis/prices.py`. A game_pk
  mapped from more than one event id is refused. Odds rows whose `away_team` /
  `home_team` differ from the map row's are refused (`SIDE_MISMATCH`).
- **Hitter-prop prices.** `data/processed/batter_props.jsonl`, markets
  `batter_hits` and `batter_total_bases`, every line. One capture = one
  `(event_id, observed_utc)` instant; the board at that instant = every book's
  Over and Under price on `(player, market, line)`.
- **Game-line prices.** `data/processed/odds_multibook.jsonl` plus every
  `data/processed/archive/odds_multibook/*.jsonl.gz` segment: h2h (moneyline),
  `spreads` (run line) and `totals`. One capture = one `(event_id, observed_utc)`
  instant per market.
- **Raw captures** `data/raw/oddsapi/2026/09..10/*/*.jsonl.gz` are the provenance of
  the processed stores; the harness reports, descriptively, how many processed
  capture instants have a raw envelope of the matching kind within 5 minutes. They
  are not a second price source.
- **Names.** Prop rows name players; lineups carry ids. id -> name from
  `data/historical/handedness.json`, then any `data/historical/lineups.jsonl` row
  (names are biographical and static). Normalisation: Unicode NFKD with accents
  removed, lowercase, `.`, `'` and `-` replaced by spaces, trailing `jr`, `sr`,
  `ii`, `iii`, `iv` dropped, whitespace collapsed. A normalised name that maps to
  two ids among the game's eighteen posted batters is refused (`AMBIGUOUS_NAME`).
- **Lineup history (game-line rule only).** `data/historical/lineups.jsonl` rows
  dated **on or after 2026-08-28 and strictly before the game's date**, teams of each
  history game from `mlb_results.csv`.

**Point-in-time, byte-serious.** Every price used has `observed_utc` strictly
before first pitch; the entry capture is strictly after `t_info`; the close is
strictly after the entry; history is strictly before the game date. Rows at or
after first pitch are dropped at read time.

## 4. Unit of observation and the favoured side, fixed before any price is read

**One unit = one contract-side at one information event.** A contract is
`(event_id, market, player or none, line)`; the side is the one the rule below
favours.

**Hitter props (decisive):**

- **R1, confirmed batter -> Over.** For each `lineup_posted` event of side S, each of
  the nine posted batters: every `batter_hits` and `batter_total_bases` line on which
  he is quoted. Favoured side **Over**. Event time `t_info` of side S.
- **R2, batter left out -> Under.** At the moment BOTH sides of a game have an
  admissible posting (`t_info` = the later of the two), every player with a hits or
  total-bases quote on that event at any capture at or before that moment whose
  normalised name maps to a known MLB person id (section 3) that is in **neither**
  posted lineup. Favoured side **Under**. A quoted name that maps to no known id is
  excluded (`NAME_UNMATCHED`), never guessed into R2.

**Game lines (reported, cannot change the verdict):**

- **R3, regulars rested -> opponent / Under.** Team T's regulars for a game on date
  D are the players with **at least 7 starts in T's last 10 games** in the lineup
  history (section 3); T needs 10 history games or the event has no game-line units
  (`NO_HISTORY`). `k_absent` = regulars not in the posted nine. If `k_absent >= 1`:
  favoured sides are the **opponent's moneyline**, the **opponent's run line**
  (the opponent side at `|line| = 1.5`) and the **Under** of the total. If
  `k_absent = 0` the event yields no game-line unit (`NO_DIRECTION`, counted).
  The total contract is the line quoted by the most books at the entry capture
  (ties: the lower total), and the close must quote the same line.
- **Starter confirmations: no rule, not tested.** A confirmed or changed probable
  pitcher carries no direction without a pitcher-quality model; `probables_watch`
  is not read.

## 5. The measurements, fixed

**Consensus.** At one capture, for one contract: every book with both sides quoted;
props additionally require raw implied probabilities summing to at least 0.98 (the
`propboard` rule). De-vig each book two-way (`src.core.odds.devig_two_way`) and
average the favoured side's fair probability. Valid only with **at least 2 books
for props** and **at least 6 books for game lines** (the `propboard.MIN_BOOKS` and
`prices.MIN_BOOKS` rules used in `scripts/diagnosis/prices.py`).

**Entry capture** = the first capture with `observed_utc > t_info` and `<` first
pitch at which the contract is valid. **Close** = the last valid capture `<` first
pitch. A unit needs both, with the close **strictly after** the entry; else it is
excluded (`NO_ENTRY_CAPTURE` / `NO_LATER_CAPTURE`) and counted.

- **M1 (drift), probability points:** `100 * (fair_close - fair_entry)` on the
  favoured side. Positive = the market kept moving toward the favoured side.
- **M2 (CLV), probability points:** `100 * (fair_close - avg_entry)`, where
  `avg_entry` is the mean raw (vig-included) implied probability of the favoured
  side over the valid books at the entry capture: the break-even of the board
  AVERAGE price. Positive = a bet at the average price beat the close.
- **Descriptive only:** the same CLV at the entry's BEST price, labelled "includes
  price improvement from line shopping" (never edge); the pre-information move
  `100 * (fair_entry - fair_pre)` where `fair_pre` is the last valid capture at or
  before the bracket START (before the lineup could have been seen).

**Statistic and interval.** Mean over units, **date-clustered bootstrap**
(`src.model.discovery.clustered_bootstrap`, clusters = game date, all units of a
date move together), **2,000 resamples, seed 20261016**, 95% percentile interval.

**Reported by market** (hits, total bases, moneyline, run line, total) and pooled
hitter props (hits + total bases), with n units, n events and n dates; by rule (R1,
R2); and the capture-lag distribution.

**Capture lag and coverage (reported whatever M1/M2 show).** For each admissible
`lineup_posted` event: minutes from `t_info` to the first hitter-prop capture of its
event and to the first game-line capture of its event (each strictly before first
pitch): median, quartiles, and **how many postings have a capture within 30, 60
and 120 minutes**, and how many have none before first pitch. Also: minutes from
`t_info` to first pitch, the bracket width, and the median gap between consecutive
capture instants per event in the six hours before first pitch, for props and for
game lines.

## 6. Size the sample can detect

Stated now; the measured values are reported with the result. The minimum
detectable effect at about 80% power, two-sided 5%, is **about 2.8 times the
bootstrap standard error** of the mean. The vig sets the bar for M2: at the board
average price a bettor pays about half the book's overround, typically two to four
probability points on a prop, so **M2 > 0 requires a post-posting drift larger than
half the overround**. The motivating drift (+0.5 to +0.7 points) is a fraction of
that. **This study therefore expects, before any result, that M2 at the average
price will be negative**; a positive M1 with a negative M2 would say the market
digests lineups after our first capture but not by enough to pay the vig.

## 7. Decision rule, fixed

Applied to the **pooled hitter-prop units** (R1 + R2, hits + total bases) only:

- **NOT MEASURABLE** (registry `below_floor`) if fewer than **30** units have both
  an entry and a close, or they span fewer than **5** dates, or the M2 interval
  cannot be computed. The result then states the coverage numbers as the finding.
- **SUPPORTED** (registry `candidate`, never `survivor`) only if **M2's 95% interval
  lies entirely above zero AND M1's point estimate is above zero**.
- **NOT SUPPORTED** (registry `null`) otherwise. The result says in which direction
  the numbers fell.

There is no threshold to move and no effect-size floor. Game lines, R1/R2 splits,
best-price CLV and the pre-information move **cannot change, rescue or veto the
verdict**. **Multiplicity:** one decisive test; the 95% interval is not the
registry-wide `0.05 / N` bar and a SUPPORTED here would not meet that bar.

## 8. What is NOT claimed

- No outcome is read; there is no hit rate, no return, no units, no bet.
- M2 is closing-line value at the average price, not expected value. A positive CLV
  is a necessary condition for a timing rule, not proof of profit.
- A NOT SUPPORTED says the rules here, at this capture cadence, do not beat the
  close; it does not say lineups carry no information.
- Nothing here is a live rule. A SUPPORTED would at most license registering a
  forward V3 timing rule with its own falsification battery.

## 9. Disclosed limits, written before any result

1. **Capture cadence.** Prop captures are sparse (section 0); many postings may
   have no prop capture after them before first pitch. That is a finding, reported
   with numbers, not a defect to fix.
2. **The prop "close" is not a true close** (last prop capture often ~2 hours before
   first pitch).
3. **R1's direction is weak by construction:** most books void a prop when the
   batter does not play, so confirmation mainly removes a void risk; the batting
   slot is information the rule does not use.
4. **R2 depends on books still quoting a benched batter**, which they usually pull,
   so R2 is expected to be thin.
5. **Line moves on totals** drop a unit whose line changes (`LINE_ABSENT_AT_CLOSE`),
   which biases game-line M1 toward zero; counted.
6. **Postseason** games (`D`, `F`, `L`) are in the window; reported split by game
   type, descriptively.
7. **Name matching** can fail; failures are counted, never guessed.

## 10. Stopping rule and procedure

1. Write the harness and tests (synthetic rows only), commit.
2. Recompute the freeze sha256, then run once:
   `python scripts/info_timing_measure.py` -> `data/research/info_timing/info_timing_result.json`
   (the script refuses to overwrite it).
3. Write `docs/research/INFO_TIMING_RESULT.md` as it falls; append the verdict with
   `record_verdict()`.
4. **One pass, no tuning.** A defect found after the run that changes a number is
   fixed in a separately disclosed commit and the run repeated only if the defect
   corrupted it (a crash or a wrong join), never because of what it showed. No
   constant, rule or population here may be edited after this commit; a different
   specification is a new registration.

## 11. The registry

Registered through `src.research.alpha_registry.register()` in this commit
(`kind: hypothesis`, `family: INFO_TIMING`, `market: hitter_props`, `sport: mlb`,
`data_window: {discovery: "2026-09-08..2026-10-15 forward captures", replication:
null, sealed_untouched: false}`, `candidates_evaluated: 5`, `alpha_declared:
0.05`, `code_hash: null` because no harness exists yet). Registering raises the
registered count by one and leaves the read count unchanged until a verdict other
than `below_floor` is recorded.
