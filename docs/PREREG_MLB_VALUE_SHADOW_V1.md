# Pre-registration: MLB_VALUE_SHADOW_V1 (value prices on MLB, shadow only)

**Rule family:** `MLB_VALUE_SHADOW_V1`, four arms, each its own rule id and record:

| Arm | Rule id | Bet type |
|---|---|---|
| A | `MLB_VALUE_SHADOW_V1_A_TOTAL_BASES` | batter total bases, over and under |
| B | `MLB_VALUE_SHADOW_V1_B_HITS` | batter hits, over and under (**thin consensus**, see below) |
| C | `MLB_VALUE_SHADOW_V1_C_RUN_LINE` | run line (the MLB `spreads` market, normally ±1.5), both sides |
| D | `MLB_VALUE_SHADOW_V1_D_GAME_TOTAL` | game total, over and under |

**REGISTERED_UTC:** the commit that adds this file is the registration instant.
It is committed on its own, before the code that implements it.
**Code:** `src/analysis/mlb_value_shadow.py` (constants, decisions, grading,
record, CLI) and `src/analysis/lobo_value.py` (the value rule with its
constants as arguments).
**Tests:** `tests/test_mlb_value_shadow.py`, `tests/test_lobo_value.py`,
`tests/test_mlb_value_shadow_wiring.py`.
**Method source:** `NFL_CARD_V2` (`docs/PREREG_NFL_CARD_V2.md`,
`src/analysis/nfl_value.py`), reused unchanged except where stated.
`nfl_value.py` is not edited. `lobo_value.py` does not import it; a parity
test proves the two give identical candidates on NFL_CARD_V2's constants.

When this file was written, no MLB_VALUE_SHADOW_V1 decision existed and no
outcome of any kind had been read or graded for it. The only look at the
stored data before registration was the explorer's structural survey:
book coverage per market, and candidate **counts** from a replay. Those
counts are quoted under "Known limits". No replayed candidate was graded.

## Why

Owner direction, 2026-09-20 (Brey):

- MLB's main focus is player props, **total bases** and **total hits**, then
  **run lines** (e.g. favourite −1.5 / underdog +1.5).
- Forward-test different strategies every day for every bet type, and show
  which work.
- Never take a price at −200 or worse.
- Find **value** (a price better than it is worth), not favourites.

This registers one strategy, the NFL_CARD_V2 leave-one-book-out value rule,
on each of those bet types. Game totals (arm D) are added because the same
rows, code path and grader already exist. Other strategies on the same bet
types are future registrations with their own ids and records.

## The rule (every arm)

1. **Sources.** Arms A and B read `data/processed/batter_props.jsonl`. Arms C
   and D read the MLB rows of `data/processed/odds_multibook.jsonl` (rows with
   no `sport` key, or `sport: "mlb"`). Nothing else is read to decide. **No
   odds-API credit is spent:** the module imports no provider module, and a
   test proves no `src.providers` module is loaded.
2. **Point in time.** A run at instant `now` uses only rows observed at or
   before `now`. Only games on the run's ET date (`official_date` of the
   first pitch) are considered.
3. **Lock window.** A game is judged only while
   `first pitch − 4 hours ≤ now < first pitch`. Nothing is decided before the
   window, or at or after first pitch.
4. **Each book's latest quote.** For game lines, each book's newest row per
   game and market. For props, each book's newest **observation** of that
   game and market: every row captured at that instant. A player the book
   no longer lists at its newest observation is not quoted by that book.
5. **Two-way only.** A prop quote is one player at one line at one book,
   with exactly one Over and one Under row. A one-sided quote (betrivers
   posts Overs only) and a duplicated row are never judged and never in
   anyone's consensus. Their update times still count toward the board's
   freshness, as in NFL_CARD_V2.
6. **Fresh quotes only.** A quote's time is the book's own update time,
   else the capture time. The board is one game and one market (for props,
   all players in that market). **Board:** its newest quote must be no more
   than **60 minutes** older than `now`, or nothing on it is judged. **Book:**
   a quote counts only if it is within **30 minutes** of that newest quote.
7. **Fair price, leave-one-book-out, same number.** A price at book B is
   judged against the mean de-vigged probability of every **other** book
   quoting the **same line**. For props that means the same player (name
   normalised as in "Grading") at the same number. For run lines it means
   the same home line, and for totals the same total. B is never in its own
   consensus. At least **N other books** must quote that exact line (N per
   arm, below), or it is not judged. A book appearing twice on one line is
   dropped from that line.
8. **De-vig three ways.** Each quote is de-vigged **proportional, Shin and
   power** (`src/core/odds.py` `devig_two_way`). A quote any method cannot
   de-vig is excluded everywhere.
9. **Value.** EV = fair probability × decimal price − 1, at B's price, once
   per method. A candidate needs **EV ≥ 2.0% under all three**. The fair
   probability and EV recorded are the **lowest** of the three.
10. **Price floor.** No selection priced at **−200 or worse** is ever a
    candidate. −199 passes and −200 does not. The floor applies to the side
    being taken; the other side of the pair is only used to de-vig.
11. **One decision per key, locked on first clear.** The key is
    (game_pk, normalised player) for A and B, and game_pk for C and D.
    Among a run's candidates for a key, the highest EV wins. Ties go to more
    other books, then book name, side and line. That candidate is written
    immediately as the decision of record. **A written key is final:** later
    runs never add a second decision on it, whatever its best line has moved
    to.
12. **Flood guard.** At most **15 decisions per arm per ET date**. When more
    new keys clear than there is room for, the highest EV are written. The
    rest are counted as `capped` in the scan row, never silently dropped.
13. **Game identity.** A game's `game_pk` comes from
    `data/processed/event_game_map.jsonl`, last write per odds event. An
    event with no game_pk is skipped as `unmapped`. An event flagged
    `ambiguous` (doubleheaders, where the nearest start was guessed) is
    skipped as `ambiguous`. Both are counted.
14. **Empty days are real.** Every run appends a scan row per arm, unless
    its counts equal that arm's previous scan row for the date. A scan row
    records boards seen, outside window, stale, judged, book-lines judged,
    candidates, keys, held, unmapped, ambiguous, capped and new decisions.
    The record classes every scanned date as one of: "no board"; "never
    run inside the lock window"; "board too old to judge"; "looked and
    declined"; "decided".

## Per-arm constants

Common to every arm: price floor **−200** (strictly better required);
**MIN_EV 0.02** under proportional, Shin and power, lowest reported;
freshness **1800 s** per book and **3600 s** per board; lock window
**4.0 h**; **15** per arm per date; **VOID after 7 days** with no final;
flat **1 unit**.

| Arm | Store, market | Other books (N) | Grades on | Label | `constants_sha256` |
|---|---|---|---|---|---|
| A | batter_props, `batter_total_bases` | **5** | box `total_bases` | — | `6345b03d780b256ee63081c747e46f52a526fce813085259cd0d0bada869179b` |
| B | batter_props, `batter_hits` | **2** | box `h` | THIN_CONSENSUS | `5f21504807985f3b3820edfcd0b63ee4ae1dca5eb861ea536d4b73633c63da3d` |
| C | odds_multibook, `spreads` | **5** | final score, run-line arithmetic | — | `4daf957eab6e8b70869822cc662aca09daa6ea20fb8961e96113e6a10c315ae3` |
| D | odds_multibook, `totals` | **5** | final score, total runs | — | `930d70f5caa1d01826a0a02623ed9c7180259b353ef9001058878f58aae6ed06` |

`constants_sha256` is the sha256 of the arm's canonical constants JSON
(`Arm.constants()`: every number above plus rule id, market, store, grader
and label). Every decision row carries it. A test pins each value to this
table.

### Why arm B uses 2 other books, decided from coverage, not volume

The explorer's book survey of `batter_props.jsonl` (2026-09-03 to 09-21)
found the following.

- **Hits two-way:** only betmgm, betonlineag and draftkings, plus fanatics
  rarely. williamhill_us, bovada and mybookieag never list hits. betrivers
  posts Overs only.
- **Books per player-line:** at most 4 at one instant, typically 2 to 3.
  None of 3,944 player-line instants had 5 books.

At NFL_CARD_V2's 5 other books, arm B therefore **cannot fire at all**: it
would be a registered null by construction, not a test. With 3 two-way
books, the most a quote can have is 2 others. So 2 is the only minimum at
which the arm can run on its usual coverage, and 3 would need fanatics,
which is rare.

- **The cost:** a 2-book consensus is noisy. One off-market book moves the
  fair price.
- **How that is handled:** the arm is labelled **THIN_CONSENSUS** on every
  row and in its record. It is registered as its own rule id, and it is
  never pooled with A.
- **What does not change:** its other constants are A's. The EV bar is not
  raised or lowered to compensate, because any other number would be a
  choice with no basis.
- **Volume was not a reason:** A's and C's minimums are **not** lowered to
  add volume.

## Grading

**Timing.** The daily loop settles, after `daily` has ingested yesterday's
box scores. Box scores for date D land at about 10:10Z on D+1.

**Final signal.** A game is final when `data/processed/boxscores_<yyyy>.jsonl`
holds its linescore row with at least one inning. The store is indexed by
**game_pk, not date**, so a suspended game that finishes on a later date
still grades.

**Props (A, B).**
- **Name join.** The decision's player is matched to that game's batter
  rows by normalised name:
  - accents stripped (NFKD), lower case;
  - `(2002)`-style parentheses dropped;
  - `.` and `'` dropped, hyphens and commas read as spaces;
  - trailing Jr/Sr/II/III/IV tokens dropped.
- **The match must be unique** (batter rows are first de-duplicated by
  player_id).
- **The grade.** Stat vs line: total bases for A, hits for B. Above the line
  wins the Over, below wins the Under, exactly on it is a PUSH. A .5 line
  never pushes.
- **Voids.**
  - No batter row, or 0 plate appearances: **VOID "did not bat"**. Books
    void players who do not play.
  - Two different players match: **VOID "ambiguous name"**.

**Run line (C).**
- **Final score:** the sum of the linescore's innings.
- **Arithmetic:** the picked side's margin plus its signed line. Positive
  wins, negative loses, zero is a PUSH (`card_ledger.grade_pick`).

**Totals (D).**
- **Arithmetic:** total runs vs the line. Exactly on it is a PUSH
  (`card_ledger.grade_total_pick`).

**Cross-check (C and D).** When `data/historical/mlb_results.csv` also holds
the game and its score differs, the decision stays **unsettled** and is
counted as a MISMATCH. After 7 days it is VOID "final score sources
disagree".

**Pending and void.**
- No final yet: **unsettled**, retried every run.
- Still no final once the decision date is 7 days old: **VOID "no final"**.
  This covers postponed games and a missed box ingest.
- Two different linescores stored for one game: **unsettled** (MISMATCH),
  and VOID "box-score linescores disagree" after 7 days.
- Any other input the graders cannot use (a stat missing from the box row,
  an unusable price) is VOID with its reason. It is never a guessed loss.
- A settled decision is never graded again.

**Profit, flat 1 unit.** A win pays decimal − 1. A loss is −1. A push or
void is 0.

**Settle output is counts only:** graded, voids, unsettled and mismatches
per arm.

## Record

- **Per arm, never pooled.** Each arm's record comes from its own files:
  - `record` prints W-L-P, voids, pending, units, ROI and mean claimed EV;
  - ROI is units ÷ units staked on W+L+P;
  - it also prints the count of dates by kind (rule 14).
- **There is no all-arms total, anywhere.**
- **Files.** Each arm has its own hash-chained files under
  `evidence/mlb_value_shadow_v1/`:
  - `<arm>_decisions.jsonl` and `<arm>_scans.jsonl`, written only by the
    capture slot;
  - `<arm>_settled.jsonl`, written only by the daily loop.
- **One writer per file.** The two jobs run concurrently. Two writers on one
  file would conflict at rebase and fork the chain.
- **Run log only.** The record is printed to the daily loop's log. It is on
  no customer surface.

## What it claims, and what it does not

- **It claims a price fact.** At the moment of decision, the book was paying
  more than the other books, de-vigged the most cautious of three ways,
  thought the bet was worth.
- **It is not a prediction, and there is no model.** The fair price is the
  market's own. There is no positive-return claim and no guarantee.
- **The forward record exists to find out** whether prices like these return
  money on MLB props and lines.
- **Shadow only.**
  - No decision is shown on the customer card, the site or any API.
  - Every decision row carries `customer_surface: false`. Tests prove that
    `api/` and `src/report/` never import the module.
  - The MLB V1 card (`DAILY_CARD_MARKET_SIDE_MODEL_AGREEMENT_V1`, which the
    owner ruled on 2026-09-17 must not be altered), `evidence/cards_v1.jsonl`,
    the engine and its decisions, paper wagers and scorecards are never read
    or written.
- **No promotion without the full gate.** A good record here licenses
  nothing by itself. Any customer-facing use needs:
  - a new registration;
  - the project's full gate, G0 to G7 (`docs/ARCHITECTURE_BETTING_ENGINE.md`);
  - the owner's decision.

## Known limits, recorded before any decision

- **Expect sparse and often empty days.** These are real, reportable
  results, not bugs. The explorer's replay counted candidates only and graded
  nothing. It covered 2026-09-03 to 09-21 and every capture instant, and
  held the first qualifying candidate per key:
  - **A (5 others):** 0 decisions in 18 days (3,118 book-lines judged across
    194 games). As a sanity check, proportional-only at EV ≥ 0 gives 14, so
    the replay is live. After de-vig, cross-book prop prices agree within 2%.
  - **B:** impossible at 5 others. At 2 others, the explorer's count was 24.
    It is quoted here because it was seen, not because it chose anything.
  - **C:** 5 decisions inside the 4-hour window, all at ±1.5, about 0.3 a
    day.
  - **D:** 1 decision inside the window.
- **The history understates forward volume.** From 2026-09-15 to 09-20, the
  daytime prop and odds captures were lost to the capture-commit bug. It was
  fixed and deployed at 2026-09-21 about 04:03Z (`a8cce55c`).
- **Props are judgeable essentially only after the gate capture.** Each game
  is captured at most twice a day:
  - baseline, 24h to 5h before first pitch;
  - gate, 2h to first pitch, after lineups for about 85% of games.

  A baseline board is usually more than an hour old by the time the lock
  window opens. So prop decisions will come from the post-lineup gate board,
  in the hour after it is captured.
- **No FanDuel on props.** The prop store has no fanduel. Arm A's consensus
  is at most 6 other books.
- **Update-stamp dedup.** The prop store writes a row only when a book's
  update stamp changes. A book whose market did not change between captures
  keeps its older stamp and can fail the 30-minute book test. Measured:
  - one book in the 36 twice-captured events was absent at the later
    instant;
  - the effect can only remove books, never add value.
- **The box ingest is not retried.** `daily` fetches yesterday only. A missed
  game's decisions VOID after 7 days rather than being re-fetched. The shadow
  never writes the shared box store.
- **Doubleheaders are skipped** (the ambiguous game map), whatever their
  prices.
- **Same number only.** A book at a different number is never compared to
  the consensus: for example 1.5 vs 0.5 on a prop, or −1.5 vs −2.5 on a run
  line. That needs a distribution model, and would be its own registration.
- **No closing-line measure.** Closing-line value would say something much
  sooner than W-L at about 0.3 decisions a day. It is not measured here. If
  wanted, it is a separate registration.
- **Name joins.** Normalisation could merge two different players into one
  name. Inside one game this voids as "ambiguous name". In the value rule,
  it drops that line.

## Changing it

- **Any change to a number, market, key or grading rule above** is a new
  rule id with its own registration and its own record. It is never an edit
  to this file.
- **An arm may be retired.** Its record stays published. It is never
  re-tuned.
- **Implementation defects** found before the first decision exists are
  fixed in code to match this document, and recorded in the commit message.
