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
4. **Each book's latest quote.** For game lines, only the rows of the
   board's (game and market's) **newest capture instant**: each book listed
   there is quoted at that row. The store writes every book the feed
   returns at every capture, so a book missing from the newest capture was
   not quoting that market then (pulled on a listed-pitcher change or
   weather, or dropped by the feed). Its older row is not quoted: never
   judged, never in anyone's consensus. For props, each book's newest
   **observation** of that game and market: every row captured at that
   instant. A player the book no longer lists at its newest observation is
   not quoted by that book. *(Game-line part corrected before the first
   decision; see "Corrections".)*
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
    The record classes every scanned date by the furthest any run that day
    got, as one of (lowest to highest):
    - "no board": no upcoming board on the date;
    - "never run inside the lock window": boards, all more than 4 hours out;
    - "board too old to judge": in the window, newest quote over an hour old;
    - "too few books to judge any line": judged, but no line had N other
      books, so nothing was compared;
    - "looked and declined": lines were compared and none cleared the bar;
    - "value found but game unmapped or ambiguous": candidates cleared the
      bar, but every one was on a game with no game_pk or an ambiguous one,
      so nothing could be decided;
    - "decided": at least one decision on the date.

    The record also prints each arm's keys skipped as unmapped, as
    ambiguous, and capped: per date the most any run that day counted
    (a later run re-counts the same key), summed over dates. *(Class list
    corrected before the first decision; see "Corrections".)*

## Per-arm constants

Common to every arm: price floor **−200** (strictly better required);
**MIN_EV 0.02** under proportional, Shin and power, lowest reported;
freshness **1800 s** per book and **3600 s** per board; lock window
**4.0 h**; **15** per arm per date; **VOID after 7 days** with no final;
flat **1 unit**; regulation **9 innings** listed in the linescore (fewer:
VOID "game shortened"). Props only (A, B): the name-join fallback's
shortest first-name prefix is **3 letters** (C and D carry `null`).

| Arm | Store, market | Other books (N) | Grades on | Label | `constants_sha256` |
|---|---|---|---|---|---|
| A | batter_props, `batter_total_bases` | **5** | box `total_bases` | — | `508219c4a2fcb4515651b0572a7f71cdf03604e6eb9d6f2798ca29f6b7ec3d15` |
| B | batter_props, `batter_hits` | **2** | box `h` | THIN_CONSENSUS | `7a2fa3f8bfa965ca29ddf61bf4f41bc790014dfe3690e98a07e7a8cfae21c01c` |
| C | odds_multibook, `spreads` | **5** | final score, run-line arithmetic | — | `426cb4e8e4d521a4a5bab7c4c0849e0a7f01751a3f2221112c61e7e11f13e63b` |
| D | odds_multibook, `totals` | **5** | final score, total runs | — | `bfe53c9be5018ec80cf0f4f10b3faf00d0059b4e3acb7f74e9b0fab263a327dc` |

`constants_sha256` is the sha256 of the arm's canonical constants JSON
(`Arm.constants()`: every number above plus rule id, market, store, grader
and label). Every decision row carries it. A test pins each value to this
table. *(The hashes changed before the first decision, when
`regulation_innings` and `name_prefix_min_letters` were added; see
"Corrections". The registration commit's hashes were never written on any
decision.)*

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

**Shortened games: VOID on every arm.** *(Corrected before the first
decision; see "Corrections".)* The box ingest treats "Completed Early"
(a game called after 5 innings) as final and writes only the innings
played. A game whose linescore lists **fewer than 9 innings** is **VOID
"game shortened"** on all four arms, and the settled row records the
innings count.
- **Run line and totals (C, D).** US books give these action only after
  9 innings, or 8.5 with the home side ahead (house rules as commonly
  published; not checked against a live rulebook). The store writes an unplayed
  bottom half as 0 runs, so a game the home side won without batting in the
  9th lists 9 innings and grades: the 8.5 case. 8 innings listed is not
  8.5 (the top of the 9th was never played), even with the home side ahead,
  so it voids.
- **No "already decided" exception.** Some books pay an Over that had
  already cleared the line when the game was called. This test does not:
  every shortened game voids, whatever its score, so no side is favoured by
  the choice.
- **Props (A, B) void too.** Book rules on player props in a shortened game
  vary. A shortened game cuts plate appearances, which pushes results
  toward Unders: the same one-directional bias as totals. Voiding removes
  it at the cost of a few decisions a season.
- **What the count cannot see.** A game called during the top of the 9th
  lists 9 innings and grades. The stored linescore cannot tell it apart,
  because an unplayed half is written as 0 runs. It is rare, and recorded
  here as a limit, not handled.
- **How often.** The local box-score stores hold 3 (2023), 4 (2024, plus 2 with
  0 innings, which are "no final") and 5 (2025) finals with 1 to 8
  innings, and none of 281 so far in 2026: about 0.2% of games.
- **Order.** For C and D the results-file cross-check (below) runs first, so
  two disagreeing sources still show as a MISMATCH.

**Props (A, B).**
- **Name join.** The decision's player is matched to that game's batter
  rows by normalised name:
  - accents stripped (NFKD), lower case;
  - `(2002)`-style parentheses dropped;
  - `.` and `'` dropped, hyphens and commas read as spaces;
  - trailing Jr/Sr/II/III/IV tokens dropped.
- **Fallback, only when that finds no row.** *(Corrected before the first
  decision; see "Corrections".)* In the same game, a batter whose
  normalised name has the **same surname tokens** and a **different first
  name, one a prefix of the other, at least 3 letters long**. For example,
  the props feed's "Leonardo Bernal" is the box score's "Leo Bernal". It
  never joins a different first name ("Colson" vs "Braden Montgomery"), an
  initial, or a one-word name.
- **The match must be unique** (batter rows are first de-duplicated by
  player_id). This applies to the fallback too.
- **Recorded.** The settled row carries `name_join` (`exact`,
  `first_name_prefix`, or null when nothing joined) and the box row's
  player id and name.
- **The grade.** Stat vs line: total bases for A, hits for B. Above the line
  wins the Over, below wins the Under, exactly on it is a PUSH. A .5 line
  never pushes.
- **Voids.**
  - No batter row by either join, or 0 plate appearances: **VOID "did not
    bat"**. Books void players who do not play.
  - Two different players match: **VOID "ambiguous name"**.

**Run line (C).**
- **Final score:** the sum of the linescore's innings (a game of 9 or more
  innings; shorter games void, above).
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
  This covers a missed box ingest, and a postponed game not yet made up.
- **A postponed game made up on another date is VOID "postponed to another
  date"**, on every arm. MLB keeps a postponed game's gamePk and moves its
  official date, so its makeup's final would otherwise grade the original
  decision against a different game. When `mlb_results.csv` gives the game
  an official date other than the decision's date, it voids. A suspended
  game keeps its official date and still grades. A game missing from the
  results file is graded as before. *(Corrected before the first decision;
  see "Corrections", 7.)*
- Two different linescores stored for one game: **unsettled** (MISMATCH),
  and VOID "box-score linescores disagree" after 7 days.
- Any other input the graders cannot use (a stat missing from the box row,
  an unusable price) is VOID with its reason. It is never a guessed loss.
- A settled decision is never graded again.

**Profit, flat 1 unit.** A win pays decimal − 1. A loss is −1. A push or
void is 0.

**Settle output is counts only:** graded, voids, unsettled and mismatches
per arm.

**One arm fails alone.** *(Corrected before the first decision; see
"Corrections".)* publish, settle, record and verify handle each arm on its
own. An arm whose file cannot be read (a line JSON cannot parse, such as a
leftover conflict marker or a truncated append) prints `<ARM>: ERROR ...`
and the command exits 1. Every other arm still publishes, settles and
records. The daily loop writes the settle's exit status into the run note.

## Record

- **Per arm, never pooled.** Each arm's record comes from its own files:
  - `record` prints W-L-P, voids, pending, units, ROI and mean claimed EV;
  - ROI is units ÷ units staked on W+L+P;
  - it also prints the count of dates by kind, and the keys skipped as
    unmapped, as ambiguous, and capped (rule 14).
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
  - excluding a non-updating book removes it from the consensus, which can
    move the fair price either way, and so can add or remove candidates.
    For example, a board where the full consensus refuses a price can make
    it a candidate once one slow book drops out
    (`tests/test_mlb_value_shadow.py`, `KnownLimitsAreTrue`). Its effect on
    the record is not measured. *(Corrected before the first decision: the
    registered draft claimed the exclusion could only remove books and
    never add value, which was false.)*
- **Withdrawn game-line quotes.** Rule 4 drops a book missing from a game
  line's newest capture. In the stored history (2026-09-03 to 09-21), 19
  such absent-book quotes would otherwise have passed the 30-minute test,
  and none became a candidate. Most came back at a later capture, and on
  two instants bovada was missing from every board, which looks like the
  feed dropping it rather than a market being pulled. Either way its price
  was not confirmed live at the decision, which is what a decision records.
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
  it drops that line. The opposite failure, one player under two names,
  is what the first-name-prefix fallback covers. Replayed on the stored
  2026 props and box scores:
  - 346 of 2,946 mapped prop player-games have no exact join, 209 of them
    in games with a final;
  - the fallback joins exactly one name, "Leonardo Bernal" to "Leo Bernal",
    in 8 games, and nothing else;
  - the rest look like players who did not play (rest days), and stay VOID
    "did not bat".

  Any other nickname the fallback cannot see (e.g. a first name that is not
  a prefix, such as "Mike" for "Michael") still voids. That shrinks the
  sample; it does not bias W-L, because the void depends on the name, not
  the result.

## Corrections before the first decision

Recorded 2026-09-21 (UTC), on branch `claude/mlb-value-shadow`, before this
file had reached the production branch and before any MLB_VALUE_SHADOW_V1
decision, scan or settled row existed. No outcome of any kind had been read
or graded. Each came from a review of the implementation, and each is a
change to a rule written above, not only to code, so each is listed here
rather than hidden in a commit message. Only correction 2 changes which
prices can become decisions; the others change grading, reporting or
operations.

1. **Shortened games void** (Grading, "Shortened games"). As first written,
   a game called after 5 innings was graded on its partial score. A
   shortened game has fewer runs and fewer plate appearances, so Unders and
   run-line leaders would have collected wins no book pays. Now VOID "game
   shortened" on every arm when the linescore lists fewer than 9 innings.
   `regulation_innings: 9` joins the constants, so every arm's
   `constants_sha256` changed.
2. **Withdrawn game-line quotes are not quoted** (rule 4). As first written,
   a book's last game-line row counted until its stamp fell 30 minutes
   behind the board, even after the book had left the market. A fixture
   reproduced a decision on a price the book no longer offered. Now only
   the board's newest capture instant is quoted. The rule inherited from
   NFL_CARD_V2 is unchanged there: `nfl_value.py` and `lobo_value.py`'s
   NFL-parity path are not edited; the filter runs in the MLB adapter.
3. **Known-limits sentence corrected** (Known limits, "Update-stamp
   dedup"). A statement of fact, not a rule. It changes no constant.
4. **Name-join fallback** (Grading, "Props"). As first written, "Leonardo
   Bernal" in the props feed never joined "Leo Bernal" in the box score,
   so a batter who played would have been VOID "did not bat". Now a
   same-surname, first-name-prefix fallback applies when the exact join
   finds no row. `name_prefix_min_letters: 3` joins the props arms'
   constants.
5. **Record classes** (rule 14). As first written, a day where value was
   found but the game join failed, or where no line had enough books to
   compare, was reported as "looked and declined". Two classes were added
   and the skip totals are printed. Reporting only: no decision or grade
   changes.
6. **One arm fails alone** (Grading, "One arm fails alone"). As first
   written, one unreadable line in any arm's file stopped every arm's
   publish, settle and record, and the daily loop's run note did not show
   it. Now each arm runs on its own, the failing arm prints an ERROR line
   and exits 1, and the run note carries the settle's exit status.
   Operational only: no decision or grade changes.
7. **Postponed games void** (Grading, "Pending and void"). Found by the
   final independent review before merge. As first written, finals were
   looked up by game_pk alone, so a decision on a game rained out and made
   up within 7 days was graded on the makeup: a fixture graded it WIN where
   this file said VOID. Now it is VOID "postponed to another date" when the
   results file's official date differs from the decision's date.
8. **THIN_CONSENSUS on every row and printed line** (Per-arm constants, arm
   B). As first written, the label was on decision rows and the record
   only: scan and settled rows, and the publish and settle log lines,
   omitted it. They carry it now. Reporting only.

After this section, the "Changing it" rules below apply in full: any
further change to a number, market, key or grading rule is a new rule id.

## Changing it

- **Any change to a number, market, key or grading rule above** is a new
  rule id with its own registration and its own record. It is never an edit
  to this file.
- **An arm may be retired.** Its record stays published. It is never
  re-tuned.
- **Implementation defects** found before the first decision exists are
  fixed in code to match this document, and recorded in the commit message.
