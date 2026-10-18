# Pre-registration: the LineHound Hounds house pack, v1

**Status: FROZEN at the commit that adds this file, before any replay was run.**
Every threshold below was chosen from the brief and from public conventions, not
from any replay output: no hound has been run over a single game when this file is
committed. A rule that turns out to be buggy is fixed in code, the fix is recorded
in the Changelog at the bottom with its reason, and the original rule's replay rows
stay in the ledger. No rule is changed because of what the replay says.

This is a paper-only, public race of betting strategies with characters. Nothing
here claims an edge or a profit. The esoteric and random hounds are controls and
entertainment, labelled as such. The public verdict (written by worker H1 in
`docs/PREREG_HOUND_VERDICT.md`) judges every hound the same way: did it beat the
closing price over enough forward bets. **The forward race starts at registration
(this commit).** The replay over 2026-09-08..2026-10-17 is shown for colour only:
five weeks of bets says almost nothing about any rule.

## 1. Evidence boundaries

* **Sealed window.** 2026-01-01..2026-08-27 outcomes are sealed and never read.
  Every MLB results reader in the pack drops a row dated inside that window before
  any score in it is looked at (`base.SEAL_FIRST`/`SEAL_LAST`), so every 2026
  "form" or "rate" input starts at **2026-08-28** (the seal floor). Standings
  snapshots are not used at all (a 2026 win-loss record aggregates sealed games).
  NFL 2026 games all postdate the seal; NFL 2021-2025 seasons are readable history.
* **Starters are not used.** The results store's `*_probable` columns were filled
  after the games and agree with the actual starter 99.9% of the time
  (`docs/AUDIT_PROBABLE_PITCHER_PIT.md`): a point-in-time leak for any replay.
  No point-in-time probable-pitcher snapshot exists for 2026-09-08..09-20, so the
  starter-matchup hound the brief suggested is **not buildable** (section 6).
* **Point in time.** A hound sees only a context built for one game at that game's
  lock instant: odds quotes observed at or before lock (and before the start);
  MLB games dated strictly before the game's date whose start was at least 5 hours
  before lock; bullpen rows dated strictly before the game's date; NFL games marked
  final whose kickoff was at least 6 hours before lock. Nothing else.
* **The -200 rule.** No selection whose board-average price is -200 or worse is
  ever written (owner's standing rule). The runner refuses it whatever a hound says.

## 2. Shared mechanics (identical for every hound)

* **Universe.** MLB and NFL games that appear in the multi-book odds store
  (`data/processed/odds_multibook.jsonl`, read through
  `src.pipeline.snapshots.iter_multibook`, archive-aware). Markets: moneyline (h2h),
  spread (MLB run line / NFL point spread) and total.
* **Start and lock.** `start_utc` = the odds feed's `commence_time` on the newest
  capture of the event at or before lock (first approximation: the newest capture
  of the event at or before `commence_time - 60 min`). `lock_utc = start_utc - 60
  minutes`. A hound decides at lock; a bet is never written at or after the start.
* **The board at lock.** For each book, its newest quote for the market observed at
  or before lock and strictly before the start, and no older than 6 hours (MLB) or
  48 hours (NFL) at lock. A market is on the board only if at least 3 books quote
  it. For spread and total markets the **main line** is the line quoted by the most
  books; ties go to the line whose consensus fair probability is nearest 0.5, then
  to the smaller absolute line. Only books quoting the main line count for it.
* **Prices.** `consensus_fair` for a side = the mean over books of that book's
  proportional de-vig probability (`src.core.odds.devig_two_way`). `price_average`
  = mean of the books' decimal prices for the side, converted back to American and
  rounded to the nearest integer (the owner's grading ruling: grade at the board
  average). `price_best` = the highest decimal price; `book` = the book offering it
  (ties: alphabetical). `book_count` = books quoting the side on that line.
* **The open board.** The earliest capture instant of the event, within 24 hours
  (MLB) or 7 days (NFL) before the start, at which at least 3 books quote the
  moneyline, if that instant is at least 60 minutes before lock. Movement = lock
  consensus fair minus open consensus fair, for a side.
* **Price band.** Every hound: `-199 <= price_average <= +400` unless its own rule
  is narrower.
* **At most one bet per game per hound, at most 3 bets per hound per day.** The day
  is the US-Eastern calendar date of the start. Games are offered to a hound in
  lock-time order (ties: event_id); a qualifying game is taken while the hound has
  fewer than 3 bets that day. A hound cannot look ahead to a later game's board.
* **No forced bets.** Every hound may pass any game and any whole day. A day with
  no qualifying game is a valid state, shown as such. No rule exists whose purpose
  is activity: a hound with nothing to say says nothing.
* **Stake.** One unit per bet, except Kelly the Kelpie (section 4, rule 11).

## 3. Ledger, settlement and the numbers shown

* **Ledger.** `evidence/hounds_house_v1.jsonl`, append-only and hash-chained
  (`src.ledger.chain.HashChainLedger`: `prev_hash`/`row_hash`). Bet rows
  `kind:"hound_bet"` with the shared row shape (hound_id, date, sport, event_id,
  game_pk or nfl game id, away, home, start_utc, lock_utc, market, selection, side,
  line, price_average, price_best, book, book_count, consensus_fair, reason,
  who_decided, segment, stake). Idempotent per (hound_id, event_id, market): a
  second run appends nothing. Segment `replay` for rows written after the fact
  from captures; `forward` for rows written live between lock and start.
* **Settlement** (`src.hounds.pack_settle`), graded rows `kind:"hound_graded"`.
  MLB: the results store (`data/historical/mlb_results.csv`); for a game whose
  date the results store never fetched (2026-09-07..09-09), the box-score store
  (`data/processed/boxscores_2026.jsonl`) summed per side, accepted only when each
  side's pitchers recorded at least 24 outs. NFL: `data/datasvc/nfl/games.jsonl`
  rows with status `final`. Results: WIN, LOSS, PUSH (landed on the line), VOID,
  UNRESOLVED (a result row exists but carries no usable score).
* **Postponed games: "pending makeup".** A bet whose game has no result stays
  pending (no graded row) for 4 days after its start. A result whose start is more
  than 36 hours after the bet's start (the game was played as a makeup) grades the
  bet VOID; no result 4 days after the start grades it VOID. A makeup game is a new
  odds event, so it gets its own bets.
* **Units.** `units_average_price`: win = stake x (decimal(price_average) - 1),
  loss = -stake, push/void = 0. `units_best_price` the same at `price_best`.
* **Closing price and CLV.** The close is the board built exactly like the lock
  board but at the instant just before the start (each book's newest quote strictly
  before the start, same staleness window, same line as the bet). `close_price` =
  the close board's average price for the selection; `clv_pts` = 100 x (close
  consensus fair probability of the selection - break-even probability of
  `price_average`). Positive means the bet's average price beat the closing fair
  price. Because `price_average` carries the books' margin, a hound with no skill
  should average about minus half the hold (roughly -2 points). No close on the
  bet's line = `clv_pts` null.
* **Shown per hound.** Bets, record (W-L-P, voids), units at average price, CLV
  mean with a date-clustered 95% interval (cluster-robust standard error over
  days, t critical value with days - 1 degrees of freedom). No hound is promoted,
  recommended or described as working on the replay.

## 4. The pack (21 hounds)

Notation: `fair(x)` = consensus fair probability of side x at lock; `avg(x)` =
price_average; "MLB window" = MLB games dated 2026-08-28 or later and strictly
before the game's date (the seal floor); "ML" = moneyline.

### Stats

1. **Professor Paws** (`professor_paws`), "the house model, on a leash". MLB, ML.
   Inputs: each club's runs scored and allowed per game and games played over the
   MLB window; league runs per game over the same window. Calls
   `src.analysis.strength.model_line` read-only with those features only (no
   starters, bullpen or park: none is point-in-time) to get the model's home win
   probability `p_model`. Shrinks 50% toward the market: `p = 0.5 p_model + 0.5
   fair(home)` (the loss diagnosis found the house probabilities overconfident).
   Bets the side whose `p - fair >= 0.020`. Both clubs need at least 5 window games.
   Score = the gap. Expectation: the house model has not beaten the market in any
   study here; should lose about the vig.
2. **Totals Terrier** (`totals_terrier`), "smells runs". MLB, total. Same features
   and model as Professor Paws, at the main total line; only half-point lines.
   `p = 0.5 p_model(over) + 0.5 fair(over)`; bets Over if `p - fair(over) >=
   0.030`, Under if `fair(over) - p >= 0.030`. Expectation: lose about the vig.
3. **Relief Retriever** (`relief_retriever`), "counts the bullpen's pitches". MLB,
   ML. Inputs: relief pitches (bullpen-log rows with `started` false) per club over
   the three calendar dates before the game's date. If one club's relievers threw
   at least 120 more pitches than the other's, bet the fresher club. Needs each of
   the three dates present in the bullpen log (a row or an `empty` marker). Score =
   the pitch gap. Expectation: a public folk method; unproven; lose about the vig.
4. **Gridiron Greyhound** (`gridiron_greyhound`), "point differential with a
   whistle". NFL, spread. Inputs: each club's 2026 point differential per game over
   finals before lock (at least 2 games each). Expected home margin = 0.5 x (home
   PD/game - away PD/game) + 1.5. Home cover margin = expected margin + home spread
   line. Bets home if >= +3.0, away if <= -3.0. Score = |cover margin|.
   Expectation: a simple rating; spreads are efficient; lose about the vig.

### History

5. **Elimination Basset** (`elimination_basset`), "home when it's do or die". MLB
   postseason. Finds the two clubs' current-season postseason series from MLB
   window games (the latest round they met in that is not complete). If the home
   club is one loss from elimination (the visitor has `needed - 1` wins), bet the
   home club ML. Otherwise pass. Expectation: tiny sample; coin flip less the vig.
6. **Jet-Lag Jack** (`jetlag_jack`), "rested legs beat red-eyes". MLB ML and NFL
   spread. MLB: bet club A when A did not play on the day before the game's date
   and B did play that day in a different ballpark from today's (B travelled
   overnight). Needs that day covered by the results or box-score store, or
   confirmed as a no-game day by the results manifest. NFL: rest = days since the
   club's previous 2026 game; bet A's spread if rest(A) - rest(B) >= 3 (week 1
   passes). Score = rest gap (MLB: 1). Expectation: documented jet-lag effect in
   MLB research; tiny and priced; lose about the vig.

### Market

7. **Steamy Setter** (`steamy_setter`), "follows the steam". MLB+NFL, ML. Bets the
   side whose consensus fair probability rose by at least 0.030 from the open board
   to the lock board. Score = the move. Expectation: moves are already in the
   price at lock; lose about the vig.
8. **Contrary Corgi** (`contrary_corgi`), "fades the steam". Same trigger as Steamy
   Setter, bets the other side. Expectation: lose about the vig.
9. **Stale-Bread Beagle** (`stale_bread_beagle`), "sniffs out a stale book".
   MLB+NFL, ML, main spread, main total. For every side of every market with at
   least 5 books on the line: edge = fair(side) - raw implied probability of the
   best price. Bets the single largest edge if >= 0.025. Score = the edge. Graded
   at the board average like everyone else (the best book is recorded and graded
   separately as `units_best_price`). Expectation: line-shopping value is price
   improvement, not a prediction; at the average price, lose about the vig.

### Math

10. **Bargain Bloodhound** (`bargain_bloodhound`), "only buys below fair". MLB+NFL,
    ML. Bets the side whose best price's break-even probability is at least 0.005
    below fair (the best price beats the de-vigged consensus); if both sides
    qualify, the larger margin. Score = the margin. Expectation: price improvement
    at the best book; graded at average, lose about the vig.
11. **Kelly the Kelpie** (`kelly_kelpie`), "bets the Kelly fraction". Same
    selections as Bargain Bloodhound. Stake = min(3.0, 100 x 0.25 x
    `kelly_fraction(fair, price_best)`) units, rounded to 0.01; passes if below
    0.05. Units scale by the stake. Expectation: same as Bargain, scaled.

### Intangibles

12. **Hot-Streak Husky** (`hot_streak_husky`), "rides the hot hand". MLB: over each
    club's last 10 MLB-window games, bet A's ML when A won >= 7 and B won <= 4 (both
    need 10 games). NFL: bet A's spread when A is on a 2026 winning streak >= 3 and B
    on a losing streak >= 2. Score = A's wins (MLB) or streak (NFL). Expectation:
    the hot hand is mostly priced; lose about the vig.
13. **Grudge Bulldog** (`grudge_bulldog`), "never forgets". NFL: bet A's spread when
    A lost the clubs' most recent meeting (any final since 2021, within 450 days
    before kickoff) by >= 7 points. MLB: bet A's ML when the same two clubs met on
    the day before and B won that game by >= 5 runs. Score = that margin.
    Expectation: folklore; lose about the vig.

### Esoteric (for fun; labelled entertainment)

14. **Numerology Newfie** (`numerology_newfie`), "reads the numbers, not the
    games". MLB+NFL, ML. Team number = English ordinal gematria (A=1..Z=26, letters
    only) of the odds feed's full team name, reduced to its digital root (1-9). Date
    number = digital root of the digit sum of the game's date (YYYY-MM-DD). Bets the
    club whose number is closer to the date number; equal distance passes. Score 0.
    Worked examples: "New York Yankees" = 191 -> 2; "Boston Red Sox" = 170 -> 8;
    "Kansas City Chiefs" = 172 -> 1; "Athletics" = 97 -> 7; 2026-09-08 -> 27 -> 9.
15. **Lunar Lab** (`lunar_lab`), "howls at the moon". MLB+NFL, total. Moon age at
    the start = days since the reference new moon 2000-01-06 18:14 UTC, modulo the
    mean synodic month 29.530588853 days (computed, no network). Full-moon window
    (|age - 14.765| <= 1.5): bet the Over; new-moon window (age <= 1.5 or age >=
    28.03): bet the Under; else pass. Worked examples: the 2024-04-08 18:21 UTC new
    moon (the eclipse) computes to age 29.359; the 2024-04-23 23:49 UTC full moon to
    15.056 (the mean-month approximation is within about a day).

### Random (controls)

16. **Coin-Flip Collie** (`coin_flip_collie`), "the control". MLB+NFL, ML. Seed =
    sha256 of "coin_flip_collie|" + event_id; home if the first byte is even, else
    away. Every game qualifies. Expectation: a control; should lose about the vig.
17. **Dartboard Dalmatian** (`dartboard_dalmatian`), "throws a dart at the board".
    Seed = sha256 of "dartboard_dalmatian|" + event_id; market = [moneyline,
    spread, total][byte0 mod 3]; side = home/over if byte1 is even, else away/under.
    Passes if that market is not on the board. Expectation: a control.

### Mixed

18. **Pack Leader** (`pack_leader`), "goes with the pack". MLB+NFL, ML. Voters:
    Professor Paws, Relief Retriever, Gridiron Greyhound, Elimination Basset,
    Jet-Lag Jack, Steamy Setter and Stale-Bread Beagle (its moneyline and spread
    picks only), each asked about this game at this lock before any daily cap. A
    pick on a club's ML or spread is a vote for that club. Bets the club's ML when
    it has >= 2 votes and the other club has none. Score = votes.
19. **Scrappy Schnauzer** (`scrappy_schnauzer`), "the underdog hunter". MLB+NFL,
    ML, only +100 <= avg <= +250 (the owner's stated preference). Bets the underdog
    when at least one of Professor Paws, Gridiron Greyhound, Steamy Setter or
    Hot-Streak Husky picks that club for this game. Score = number of backers.
    Expectation: favourite-longshot bias says dogs lose a little more than the vig.

### Simple

20. **Chalk Chihuahua** (`chalk_chihuahua`), "always the favourite". MLB+NFL, ML.
    Bets the favourite (higher fair) when -199 <= avg <= -101. Score = fair.
21. **Home Dog Hank** (`home_dog_hank`), "the home underdog". MLB+NFL, ML. Bets the
    home club when +100 <= avg(home) <= +400. Score = fair(home).

## 5. Seeds are committed

The random hounds' seeds are the hound id and the odds event id, nothing else, so
anyone can recompute every coin flip from this file. Tests pin worked examples.

## 6. Not buildable, and why

* **Starter-matchup totals hound** (opponent-adjusted strikeout and run prevention):
  no point-in-time probable-pitcher record exists for the replay window; the
  results store's probable is the actual starter (a leak). Revisit for the forward
  race only when probables are captured with an observed time.
* **Game model with starters and bullpen** (the full card model): its season
  inputs aggregate sealed 2026 games. Professor Paws uses the same arithmetic on
  unsealed inputs only.
* **Player props, weather, injuries, NFL QB changes**: no hound uses them in v1.
* **Primetime / short rest**: folded out; the NFL schedule rows carry no
  point-in-time primetime flag and the sample over five weeks is a handful of games.

## 7. Replay and forward

Replay: `python -m src.hounds.pack_run --from 2026-09-08 --to 2026-10-17 --replay`
then `python -m src.hounds.pack_settle`. Forward: `python -m src.hounds.pack_run
--date D` run during the day writes rows only for games whose lock has passed and
whose start has not. The replay table lives in `docs/HOUSE_PACK.md`.

## Changelog

* v1 frozen (this commit). No changes yet.
