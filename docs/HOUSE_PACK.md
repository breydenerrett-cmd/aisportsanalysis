# LineHound Hounds: the house pack (v1)

21 paper-only betting strategies with characters, racing in public. Each one is a fixed,
pre-registered rule (`docs/PREREG_HOUSE_PACK_V1.md`, frozen at commit `20cd68eb8` before any replay
ran). Each hound's playbook is `docs/hounds/<id>.md`; the registry the read API uses is
`config/house_pack.json`. **Nothing here claims an edge or a profit.** The esoteric hounds
(Numerology Newfie, Lunar Lab) are entertainment; the random hounds (Coin-Flip Collie, Dartboard
Dalmatian) are controls. Every hound may pass any game or any whole day; a quiet day is a valid
state, not a failure.

## Read this before the table

**The replay below covers five weeks and says almost nothing.** 0 to 96 bets per hound is far too
few to tell skill from luck: on 60 coin-flip bets at even money the 95% range of outcomes is about
plus or minus 15 units. **The race that counts is forward and starts at registration** (the prereg
commit). The verdict, written separately by worker H1 (`docs/PREREG_HOUND_VERDICT.md`), judges every
hound the same way: did it beat the closing price over enough forward bets.

**CLV here is structurally about minus 2 points.** Every bet is graded at the board-average price
at lock (the owner's grading ruling), which carries the books' margin; `clv_pts` compares that price's
break-even with the closing de-vigged consensus. A hound with no skill therefore lands near minus half
the hold, and that is what all 20 hounds that bet did. On top of that, the lock is 60 minutes before
the start and captures are sparse: for 271 of 889 graded bets (30%) there was no capture between lock
and start, so the close IS the lock board, and the mean absolute move from lock to close was 0.24
probability points. Over this window no hound could have beaten the close by much more than the vig
even with perfect foresight of the last hour. That is a property of the measurement, not a finding
about any hound.

**Units are dominated by luck.** Jet-Lag Jack's +9.7 and Professor Paws' -20.6 are both well
inside what random sides at these prices produce over 20 to 70 bets.

## Replay table (segment "replay", 2026-09-08..2026-10-17)

MLB games 2026-09-08..2026-10-17 and NFL weeks 2-6 (games through 2026-10-15) with captured odds.
913 bets on 244 games (754 MLB, 159 NFL; 720 moneyline, 117 totals, 76 spreads) over 37 dates; 903
graded, 10 pending. Units are per one-unit stake (Kelly the Kelpie stakes by its own rule), graded
at the board average; "Units @ best" grades the same bets at the best book's price. CLV interval:
cluster-robust over dates, t with (days - 1) degrees of freedom.

| Hound | Category | Bets | W-L-P (void) | Units @ avg | Units @ best | CLV mean (pts) | 95% CI (date-clustered) | Days |
|---|---|---|---|---|---|---|---|---|
| Professor Paws | stats | 69 | 21-47-0 (1) | -20.63 | -19.47 | -1.80 | -1.93 to -1.68 | 28 |
| Totals Terrier | stats | 64 | 28-33-0 (1), 2 pending | -8.08 | -6.98 | -2.44 | -2.58 to -2.30 | 27 |
| Relief Retriever | stats | 21 | 12-8-0 (1) | +3.96 | +4.52 | -1.71 | -2.01 to -1.41 | 13 |
| Gridiron Greyhound | stats | 14 | 6-8-0 (0) | -2.61 | -2.30 | -2.32 | -2.56 to -2.08 | 8 |
| Elimination Basset | history | 8 | 3-5-0 (0) | -2.65 | -2.54 | -1.86 | -2.04 to -1.67 | 6 |
| Jet-Lag Jack | history | 19 | 15-3-1 (0) | +9.73 | +10.24 | -2.07 | -2.37 to -1.77 | 10 |
| Steamy Setter | market | 37 | 20-16-0 (1) | +1.10 | +1.86 | -1.88 | -2.08 to -1.69 | 21 |
| Contrary Corgi | market | 37 | 18-18-0 (1) | +4.64 | +5.57 | -1.87 | -2.09 to -1.64 | 22 |
| Stale-Bread Beagle | market | 0 | 0-0-0 (0) | +0.00 | +0.00 | n/a | n/a | 0 |
| Bargain Bloodhound | math | 9 | 4-5-0 (0) | -0.62 | -0.13 | -1.70 | -2.39 to -1.01 | 7 |
| Kelly the Kelpie | math | 9 | 4-5-0 (0) | +0.03 | +0.27 | -1.70 | -2.39 to -1.01 | 7 |
| Hot-Streak Husky | intangibles | 38 | 19-19-0 (0) | -3.98 | -3.33 | -2.09 | -2.24 to -1.94 | 20 |
| Grudge Bulldog | intangibles | 41 | 20-21-0 (0) | -1.88 | -0.96 | -1.94 | -2.09 to -1.79 | 21 |
| Numerology Newfie | esoteric | 89 | 43-44-0 (0), 2 pending | +0.67 | +2.73 | -1.86 | -1.99 to -1.72 | 33 |
| Lunar Lab | esoteric | 23 | 11-10-2 (0) | +0.09 | +0.51 | -2.23 | -2.43 to -2.03 | 9 |
| Coin-Flip Collie | random | 96 | 43-51-0 (0), 2 pending | -2.77 | -0.45 | -1.89 | -2.03 to -1.74 | 35 |
| Dartboard Dalmatian | random | 94 | 46-45-1 (0), 2 pending | +0.31 | +2.47 | -2.14 | -2.27 to -2.02 | 35 |
| Pack Leader | mixed | 22 | 13-9-0 (0) | +4.74 | +5.32 | -1.74 | -1.95 to -1.53 | 15 |
| Scrappy Schnauzer | mixed | 71 | 20-49-1 (1) | -21.29 | -20.08 | -1.65 | -1.79 to -1.52 | 31 |
| Chalk Chihuahua | simple | 93 | 48-43-0 (0), 2 pending | -8.71 | -7.15 | -2.09 | -2.23 to -1.94 | 35 |
| Home Dog Hank | simple | 59 | 24-35-0 (0) | -3.88 | -2.46 | -1.66 | -1.77 to -1.55 | 25 |

Every interval is entirely below zero: no hound beat the closing price in the replay, controls
included. That is the expected result of grading at the average price, and it is published as is.

## Notes on the replay

* **Zero bets is a result.** Stale-Bread Beagle never fired: the largest best-price edge over the
  de-vigged consensus on any lock board in the window (5+ books) was 2.05 points; its bar is 2.5.
  Its rule is not changed.
* **Professor Paws and Scrappy Schnauzer lean on away underdogs** (75% and 84% of their picks were
  away sides). The team-rates-only model is heavily regressed in this window (rates start at the seal
  floor, 2026-08-28) and carries only a 0.2-run home credit, so it sits closer to 50/50 than the
  market and likes the visiting dog. They won 21 of 68 and 20 of 69 graded bets against about 28 the
  consensus expected; they share many picks, so these are not two independent misses. Read as variance
  plus a structural lean, not as evidence about the model.
* **Pending makeup, live example.** TB@CLE on 2026-10-16 (game_pk 849817) was postponed to
  2026-10-18 under the same game_pk. Its five bets are pending; when the makeup's result arrives with
  a start more than 36 hours after the original, they grade VOID. The 2026-10-18 makeup is a new odds
  event and gets its own bets in the forward race. Five 2026-10-17 bets (849816) await that day's results.
* **One cancelled game.** BAL@NYY 2026-09-27 (823490) was cancelled (results manifest: cancelled 1);
  its bets graded VOID after four days, as the prereg says.
* **Results gap filled.** The results store never fetched 2026-09-07..09-09. For those 41 games the
  box-score store's pitcher lines were summed per side (accepted only with 24+ outs per side). On the
  377 games where both stores exist they agree 377 of 377.
* **Shared daily cap.** The three-a-day cap spans both sports in lock order, so on a day with MLB
  afternoon games a hound can be full before Thursday Night Football locks. The 2026-09-17 DET@BUF game
  drew no bets: the every-game hounds were already full, and no rule-based hound qualified (week 1
  gave each club one game, below Gridiron Greyhound's two).

## Running it

```
python -m src.hounds.pack_run --date 2026-10-18                     # forward, run during the day
python -m src.hounds.pack_run --from 2026-09-08 --to 2026-10-17 --replay
python -m src.hounds.pack_settle                                    # grade what can be graded
python -m src.hounds.pack_settle --report [--segment forward]       # this table
python -m src.hounds.pack_run --verify                              # hash-chain check
```

A forward run writes rows only for games whose lock (start minus 60 minutes) has passed and whose
start has not, so it has to run more than once a day to catch every lock. Ledger:
`evidence/hounds_house_v1.jsonl` (append-only, hash-chained; bet rows `hound_bet`, graded rows
`hound_graded`; a corrected grade is a new row naming the row it corrects).
