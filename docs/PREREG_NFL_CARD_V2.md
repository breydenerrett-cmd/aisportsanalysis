# Pre-registration: NFL_CARD_V2 (value lines)

**Rule id:** `NFL_CARD_V2`
**REGISTERED_UTC:** the commit that adds this file is the registration instant.
**Code:** `src/analysis/nfl_value.py` (constants fixed there), wired in `src/report/nfl_card.py`.
**Replaces on the NFL card:** `NFL_CARD_V1` (the market favourite in every game).
**Tests:** `tests/test_nfl_value.py`.

No V2 pick existed, and no V2 result had been seen, when this was written.

## Why

On 2026-09-20 NFL_CARD_V1 published San Francisco -950, Tampa Bay -420,
Baltimore -380, Philadelphia -320, Los Angeles -295 and Kansas City -278. Its
rule is "take whichever side the market makes more likely", which is a list of
favourites by construction. The owner's rulings that day:

- a moneyline at -200 or worse is never a bet;
- the value in the NFL is on the point spread and the game total, not on
  picking winners;
- the goal is odds that are worth more than they cost.

## The rule

1. **Markets:** point spread, game total, moneyline.
2. **Price floor:** no selection priced at -200 or worse is a candidate, in any
   market. -199 passes and -200 does not.
3. **Fresh quotes only:** each book's latest quote per game and market counts,
   and only if that book updated within **30 minutes** of the newest update any
   book posted for the same game and market. **And the board itself must be
   fresh:** the newest quote for that game and market must be no more than
   **60 minutes** older than the run. Otherwise that game and market are not
   judged at all. A quote's time is the book's own update time, or the capture
   time when the book gives none.
4. **Fair price, leave-one-book-out:** a price at book B is judged against the
   de-vigged average of every *other* book quoting the **same number** (same
   spread, same total). B is never part of its own consensus. At least
   **5 other books** must quote that exact number, or the line is not judged.
   A book's quote is de-vigged **three ways: proportional, Shin and power**
   (`src/core/odds.py` `devig_two_way`). A quote that any of the three cannot
   de-vig is left out: it is not judged, and it is not in anyone's consensus.
5. **Value:** EV = fair probability × decimal price − 1, at B's price,
   computed once per de-vig method. A candidate needs **EV ≥ 2.0% under all
   three**. The fair probability and EV the card publishes, and the ones its
   "why" sentence quotes, are the **lowest of the three**.
6. **Card:** one pick per game (its highest-EV candidate), ranked by EV, at most
   **5 per date**. The label is STRONG when EV ≥ 4.0% and at least 8 other books
   quote the line, and LEAN otherwise. Labels never change the ranking.
   - **Held across publishes.** The card is re-published every capture slot.
     Once a game's pick is locked (4 hours before kickoff), that pick is the
     bet of record for the game. Later publishes never add a second pick on
     the same game, whatever its best line has moved to.
   - **The 5 is per date, not per publish.** A later publish only fills the
     room the date's locked picks leave, and is ranked after them.
7. **Empty days are real:** when nothing clears, the card publishes nothing and
   says which kind of nothing it is:
   - "no board";
   - "every game on this date has already started";
   - "board too old to judge" (rule 3's 60-minute gate,
     `nfl_value.has_fresh_board`);
   - "looked and declined".
8. **Never two rules on one date.** V2 does not publish onto a date whose card
   was already published under another rule (NFL_CARD_V1). It sits that date
   out. Both publish paths (the CLI the capture slot runs, and
   `publish_for_date`) refuse, and `card_ledger.publish` refuses underneath.
9. **No model, so no calibration claim.** V2's fair price is the market's own
   consensus. Its cards carry `has_model: false` and `calibrated: null`, so the
   page never shows model-calibration copy for this rule.

## Corrections made before registration (2026-09-21)

A review of the uncommitted draft found two holes. Both were fixed before this
file was committed. No V2 pick had been published, and no V2 result had been
seen. Each change makes the rule stricter; none was chosen to produce picks.

- **Rule 5, all three de-vig methods (was: proportional only).**
  Proportional de-vig leaves too much probability on the long shot.
  `src/core/odds.py` says so, and says an edge that survives only one method is
  fragile. The repo already applies that rule in `disagreement_is_robust`
  (`src/pipeline/predict.py`) and in the F5 and totals evals'
  `devig_sign_survives_check`. The -200 price floor removes the favourite side
  of every lopsided game, so the long dog was the only side left to judge
  there. That is exactly where proportional over-counts.

  Replay over the local store (100 NFL capture instants, 2026-09-15 19:09Z to
  2026-09-21 03:51Z, each judged on the rows known by then):

  | Draft | Distinct candidates | Mix |
  |---|---|---|
  | Proportional only | 17 | 16 plus-money moneylines, 1 total |
  | All three methods | 1 | the total below; every moneyline dropped out |

  Example, at the 2026-09-21 02:58Z capture: NYJ +275 at betmgm came out at
  3.9% under proportional, 0.0% under Shin and −2.1% under power.
- **Rule 3, board age (was: book-versus-book only).** The 30-minute test only
  compares books with each other, so a board that every book stopped updating
  on together still passed. On 2026-09-20 NFL capture stopped at 04:01Z. The
  card still ran at 14:37Z, 17:01Z, 20:15Z and 20:29Z.
  - **Draft without the gate:** at 20:29Z it found IND@KC Over 46.5 +110
    (bovada) on the 16-hour-old board. Kickoff was 3.85 hours away, inside the
    4-hour lock, so the pick would have locked. By the next capture
    (2026-09-21 00:09Z) no book was offering 46.5 +110.
  - **With the gate:** all four runs find nothing.

  While NFL capture runs, its snapshots land about 9 to 20 minutes apart (94
  of the 99 gaps in the store). The other 5 gaps are about 20 to 27.5 hours
  each: the daytime captures lost by the capture-commit bug fixed on
  2026-09-21 (section "Known limits"). So a board whose newest quote is more
  than an hour old means capture stopped, not that the market is quiet.
- **Rule 6, one bet per game across publishes, and 5 per date (was: one per
  game and 5 within a single publish).** The card is re-published every
  capture slot. Picks lock 4 hours before kickoff, so a later publish whose
  best line on a game had moved added a second, locked bet on that game.
  Reproduced on a scratch ledger: DET −6.5 +105, then NYJ +7 +104, both
  locked, graded PUSH and WIN. With held games no longer using slots, a Sunday
  built across kickoff windows then reached 10 locked picks. Both are closed
  as described in rule 6.

## Grading and record

- Flat 1 unit per pick, graded from the final score. Spreads use the run-line
  arithmetic (a push is a push). Totals are over/under against combined
  points. Moneylines are win/loss.
- V2's record is **its own**: `card_ledger.record(rule="NFL_CARD_V2")`.
  NFL_CARD_V1's rows stay in the same ledger file under their own rule id and
  are never pooled with V2's.
- V2 never publishes onto a date that already carries a V1 card, because the
  lock-and-carry-forward would merge V1's locked picks into V2's row.

## What it claims, and what it does not

It claims a **price** fact: the pick pays more than the rest of the market
thinks the bet is worth. The fair price comes from the market itself, so this
is not a prediction model and not a claim that the bet wins. Whether prices
like these return money over time is exactly what the forward record is for.
There is no positive-return claim and no guarantee.

## Known limits, recorded before any result

- **Same-number only.** A book hanging +3.5 while everyone else is at +3 is
  the classic NFL value, but it is not judged here: comparing different numbers
  needs a margin-distribution model (key numbers 3 and 7). That is the next NFL
  build (historical final scores via BALLDONTLIE `/nfl/v1/games`). It will be
  registered as its own rule, not as an edit to this one.
- **Expect sparse cards, often empty ones.** NFL main lines are among the most
  efficient prices there are.
  - **Registration-day board.** The rule, as registered here, was run at
    2026-09-21 04:11:04Z on the local capture store. The newest capture was
    03:51:04Z, 20 minutes old. It found **0 candidates** across 17 upcoming
    games. Those games have 51 game-and-market boards, and 45 were inside the
    one-hour gate. The other 6 are KC@MIA and HOU@IND (2026-09-27), which the
    books stopped quoting at 00:23Z. Run at the 03:51Z capture instant itself,
    it also found 0.
  - **Whole-store replay.** Across all 100 capture instants, the rule finds
    exactly one candidate: IND@KC Over 46.5 +110 at bovada. It appeared at
    2026-09-20 04:01:57Z with EV 3.10% (power), 3.14% (Shin) and 3.22%
    (proportional), against 8 other books.
- **The board-age gate follows the capture schedule.** In the store up to
  2026-09-21 03:51Z, NFL snapshots exist only between about 00:00Z and 04:00Z
  each day. The cause was not the market. From 2026-09-15 the capture slot's
  own commit staged nothing: one missing path made git refuse the whole
  `git add`. Daytime captures were therefore thrown away with the runner.
  Only the evening ones survived, because the afternoon slate job committed
  them. That was fixed and deployed at 2026-09-21 ~04:03Z (`a8cce55c`), and
  the first capture on the new code (04:14Z) committed its odds. On a stale
  board the rule correctly judges nothing; it is never a reason to loosen the
  gate. With daytime capture persisting, Sunday's day games can now be judged
  inside their own lock window.
- **No team totals and no NFL player props yet.** The capture's featured call
  is moneyline, spread and total only. BALLDONTLIE `/nfl/v1/odds/player_props`
  plus `/nfl/v1/stats` would supply both, subject to the key's plan tier.

## Changing it

Any change to a number above is a new rule id with its own registration and
its own record. It is never an edit to this file.
