# How RabbitSZN builds a pick (reverse-engineered from his posts)

Status of everything below: OBSERVATION from screenshots of his public Patreon and X posts and forwarded messages (about 130 images,
2026-10-04 .. 2026-10-20). Nothing here says the method predicts anything. His posts carry no authenticated timestamp ("5 days ago"
and a post date), so every pick is "post date visible; exact post time NOT visible; not authenticated". `ledger.csv` has one row per
distinct pick, `claims.csv` has every checkable claim, `replay.py` runs our engine over the same games.

## The shape of a post

1. A title with sport and date ("CFB 10/16/26"), sometimes a line of intent: "Liking both codes", "My more confident ones here are
   OSU and Cincinnati", "In order from most confident goes Bengals, Bears, Saints, then Ravens", "Loving Dodgers' code", "Of the two
   games, Braves' code is my most confident, but it's pretty close", "tread carefully", "just a surface read, I'll update once I look
   into the pitcher", "sprinkle them or stay off the ML". A post is sometimes edited when a pitcher or an injury is decided (odds and
   bullets change; the later version is the one in the ledger).
2. One block per game or prop, headed by the matchup with the posted price of each side: `Seattle Seahawks (-142) vs Denver Broncos (+120)`,
   or a prop with its price: `Drake Baldwin HR +1 (+600)`.
3. A HEADLINE for the side he takes: "X wins, giving Y their Nth win/loss/game, N weeks/days from <date>". The headline is a COUNT
   (a milestone the result would produce) and usually a span. Props use the same grammar: "Gesicki can get his 8th TD, exactly 8
   weeks from Dolphins' founding date".
4. Supporting bullets, each an equality with the headline's number N (or a number linked to it):
   * a cipher value of a name = N ("Seattle = 19 FR", "Indiana University = 88 FR", "Ryan Day = 88 EO", "Washington Commanders = 305 RO");
   * a state's order of statehood = N ("Georgia 4th state", "Indiana 19th state"), usually the state of one team's city or a person's
     birthplace;
   * a prime-index or triangular link ("67 = 19th prime", "41 = 13th prime", "66 = 11th Tri #");
   * another count that equals N ("Barry Odom's 19th game with Purdue", "Dream's 19th season");
   * a span in days/weeks/months from a founding date, an anniversary, a birthday or a prior event, with the end-date convention
     sometimes stated ("including end date"). The posts mostly count to or FROM THE NEAREST ANNIVERSARY of the date (33 days after
     California's September 9; 19 days before the University of Washington's November 4; 41 weeks to Colorado's next August 1);
   * incidental numbers: jersey numbers (#51 Peralta on the mound), area codes (305 Miami), draft position, ages, a stadium's age, day
     of year ("the 4th DOY").
5. A block is one target number. A game's post stacks two to five blocks (a 19-block, a 36-block, a 33/47 block), each introduced by
   a new "X ... Nth ..." line. The "33/47 Mason coding" tag marks any 33 or 47 anywhere in the game.
6. Warning bullets (a warning sign) give the OTHER result's matches ("Broncos lose, giving home teams their 38th loss ... 163 = 38th
   prime, Colorado = 38 FR"; "Spurs win their 36th season opener, Thunder = 36 FR"), a caveat ("Leaning Broncos ... could see it
   going either way"), or the conditions under which his own headline fails ("ODU can only pick up their 33rd home loss if you include
   their loss as the designated home team in the Toastery Bowl").

## How he picks the side

There is no stated rule. What the posts show:

* The side taken is the one whose RESULT produces the headline milestone and the larger stack of matching numbers; the opposite result's
  matches are listed under a warning sign, and he says in plain words when the two are close.
* Confidence is spoken, not scored: "most confident", "liking", "loving", "just a surface read", "tread carefully", "sprinkle them or
  stay off". Within a post the order of appearance and an explicit ordering line carry rank.
* Prices range from -600 to +1300 across ML and props. He takes favourites and underdogs and does not appear to use the price. Some
  selections are at -200 or worse (Cowboys -455, Ravens -218); the Gematria Hound may never output one.
* He posts a subset of the day's games, plus props: touchdown scorers and home-run hitters, each with its own code. Props are not
  moneylines; the ledger records them and `replay.py` does not replay them.
* Every pick is built after the number is found: there is no pre-registered list of what counts, how many alternatives were searched,
  or what disqualifies a match. That is the central measurement problem: matches are cheap (see the engine's search-space counts).

## What we reproduced in the engine (`src/hounds/gematria`)

| his structure | the engine |
|---|---|
| the headline count of the taken side's world | `milestones()` per world; a count that at least 3 other numbers equal is a `headline_milestone` (weight 3.0, above a loose match at 1.0) |
| cipher = N | `milestone_eq_name` over EO, FR, RO, RFR for team, city, mascot, state, university, abbreviation, head coach, weekday |
| state order = N | `milestone_eq_state` (statehood table, tested) |
| prime index / triangular link | `prime_link`, `triangular_link` |
| spans from founding dates, to or from the nearest anniversary, inclusive or exclusive | `milestone_eq_span` with `anniv_since/until_days/weeks`, `days`, `weeks`, `years`; the convention is in the label |
| game, meeting, coach game numbers | `milestone_eq_count`; NFL coach records from our NFL store |
| jersey numbers, area codes | `milestone_eq_fact_number` when the facts hold the number (none are seeded: no source) |
| 33/47 Mason coding | `special_33_47` plus a bonus on any match at 33 or 47 |
| the opposite result's warning bullets | the other side's world is scored the same way; its matches count for that side |
| spoken confidence | confidence 1..5 from the margin, less one when the other side's score is within 85% |

Stadium names and opening dates are STORED for MLB and WNBA (sourced to Wikipedia) but the engine does not read them under rules v1; reading them is a v2 decision. Not reproducible from our stores, and so ABSENT rather than guessed: all-time franchise records ("their 33rd home loss"), birthdays,
founding dates of cities, draft positions, seasons since a player's last event outside the stored season, anything about
players. An absent fact makes no quantity.

## The claims, checked

`claims.csv`: every cipher, prime-index, triangular and statehood claim recomputed with the same engine (`tests/test_gematria_engine.py`
re-checks the CSV). Almost every cipher value he states is arithmetically right under Full Reduction (A=1..I=9, J=1..R=9, S=1..Z=8,
letters summed, the sum not reduced). Arithmetic agreement says only that the sum is right. The exceptions are listed in `claims.csv` with
status CONTRADICTED (for example "317 = 66th Tri #": 317 is the 66th PRIME, not a triangular number; the "RR" claim is not any variant we
can reproduce). Claims about records, streaks, weeks since an event and birthdays are UNVERIFIED_HISTORY: our stores do not hold them.

## Results and the honest record

`ledger.csv` carries the result of every pick with the box score or scoreboard it cites (62 rows; read through a page summariser, not
line by line, so a second source should confirm before anyone quotes the record; two rows cite the owner's own screenshot). On the
documented moneylines with a known result (39 rows, including the three losses and the Broncos win): 21 wins, 18 losses, +2.9 units
flat at the posted prices; leaving out the four selections priced -200 or worse: 19-16, +4.4 units. Documented props: 6 wins and 11 losses
(one void, DJ Moore inactive), +4.8 units because the winners were long shots. This is a SELECTED collection (the posts that were captured),
not a record: the full card, every pass, the deleted posts and the exact post times are not available. No record is claimed from it.

## What the engine does on the same games (`replay.py`; IN-SAMPLE, diagnostics only)

The engine was run point-in-time over the 36 documented moneyline/lean rows (`replay_table.csv`). Rules v1 were frozen BEFORE the
first replay and were not touched for this one: what changed between the two runs is the DATA, not the rules. The first run placed 26 of the
36 (MLB and WNBA had no team facts, so they passed as `no_facts` and were reported as not placed); the facts layer now covers MLB (30 clubs)
and WNBA (15 teams), so all 36 are placed. MLB history is the results store from 2026-08-28 only (the sealed window 2026-01-01..2026-08-27
is never read, and nothing before it is read either). Because that window starts months into the season, MLB gets NO season-to-date counts:
no win or loss totals, home/road counts, game numbers or head-to-head totals, since a total since 08-28 is not "the Nth win of the season"
and absent is better than wrong. Spans, ciphers, statehood, days since a last win or loss and streaks that end inside the window remain. WNBA has no point-in-time results store in this tree, so its two rows are
`no_history` passes, not scores.

Of the 36: 14 engine picks and 22 passes (10 uneven search size, 6 small margin, 4 thin data, 2 no history). On those 14 the engine took the SAME
SIDE as him 5 times (35.7%), which is no better than a coin: the engine reproduces his structure, not his choices. Its in-sample record on the
14 was 6-8, against his 22-14 on the 36 placed games. Neither number says anything about the future. The median absolute margin on the 34 games that
had scores was 10 points against a minimum of 3 (26 of them cleared it), so the v1 margin threshold barely filters; a noise-aware margin (scaled by the size of the
search) is still the obvious first candidate for rules v2, to be proposed, versioned and judged on forward games, not on this sample.

The MLB rows added by this extension (8 placed): 2 engine picks and 6 passes (4 small margin, 2 thin data). The engine took the other side from him
on both picks; its in-sample record on them is 2-0. Two picks is not a sample, and a first version of this replay that counted wins since
2026-08-28 as season wins (4 picks, 1-3) was withdrawn for exactly that reason.

## The forward test (`forward.csv`, `forward_claims.csv`): the only out-of-sample record

Everything above is in-sample. The first genuinely forward picks arrived on 2026-10-21 (three NBA games, forwarded by the owner as screenshots
BEFORE tip-off). `forward.csv` holds them as rows with a capture time, a source ("owner screenshot, pre-game") and the status "forward,
pre-game", beside the Gematria Hound's own pre-game output for the same games (computed by the engine from results observed before the cutoff,
no result of the game used). It is kept apart from `ledger.csv` and `replay_table.csv` on purpose.

Rules for the file: a pick row is never edited after its game. When a game is final, a NEW row is appended (`row_type` = `result`, same
`pick_id`, with `final_score`, `result` of WIN / LOSS / VOID / NO_BET, `graded_utc` and `result_source`). A hound PASS is graded NO_BET: it is not
a win. Both sides are graded into the same file, so the comparison is his record on his selections against the hound's record on its own,
over the same games. `tests/test_gematria_replay.py` holds the shape. Three games is an anecdote; the file is the start of a record, and
no claim is made from it. `forward_claims.csv` re-checks the ciphers the three posts state: all 11 arithmetic claims recompute (an "RR" is
read as Reverse Full Reduction, the only reverse reduction the engine has; that reading is an interpretation and is flagged on each row), and
the record/streak claims are UNVERIFIED_HISTORY because the NBA store holds this season only.

## What the hound does with this

The hound builds the same worlds for every game on the board, not for the games a person chose, logs the size of the search, applies one
fixed table of weights and a fixed margin, and passes when it cannot decide. Whether any of it beats the price is exactly what its
public record will say. Until then: experimental, paper, no claim.
