# UFC results: ESPN grades the card (2026-10-03)

TL;DR. `python -m src.cli ufc autograde --date YYYY-MM-DD` now reads ESPN's
public MMA results through our own data layer (`src/datasvc/ufc/`) and records
what ESPN has marked final. No key, no cost. Typing results in by hand still
works and always wins: an automatic result never overwrites one a person
entered, it is compared with it and a disagreement is reported. BALLDONTLIE
stays selectable (`--source balldontlie`) but is not needed.

Code: `src/providers/espn_mma_results.py` (the source),
`src/pipeline/ufc_autograde.py` (the driver and the comparison),
`src/pipeline/ufc_results.py` (the one writer, unchanged),
tests `tests/test_espn_mma_results.py` and `tests/test_ufc_autograde.py`.

## Commands

```
python -m src.cli ufc autograde --date 2026-10-03            # record what ESPN has marked final
python -m src.cli card settle --sport mma --date 2026-10-03  # then grade the picks from the rows
python -m src.cli ufc autograde --date 2026-10-03 --dry-run  # print what it would record and why
python -m src.cli ufc autograde --date 2026-10-03 --verify   # audit: compare ESPN with every result on
                                                             # file, settled picks included; writes nothing
python -m src.cli ufc autograde --date D --offline [--cache-dir DIR]   # replay from the saved raw cache
python -m src.cli ufc result --date D --fight "A vs B" --winner A --entered-by you   # by hand, as before
```

Every run is safe to repeat. A pick whose bout ESPN has not called final is
left alone and listed as UNRESOLVED with the reason; run it again later. A
bout is graded the moment ESPN marks it final, so a card can be graded in
pieces as it goes on. `--verify` exits non-zero if ESPN contradicts anything
on file.

### Tonight: 2026-10-03, UFC 332 (ESPN event 600061182)

Run `python -m src.cli ufc autograde --date 2026-10-03`, then `card settle`.
It reads the three published picks from the ledger and finds each on ESPN's
card by name (checked on ESPN's saved scoreboard, 14 bouts, exactly one bout
per pick):

| Pick (ledger) | ESPN bout | Segment |
|---|---|---|
| Marvin Vettori vs Ismail Naurdiev | 401912275 | early prelims |
| Johnny Walker vs Michael Parkin | 401912274 (ESPN: "Mick Parkin", see below) | early prelims |
| Imanol Rodriguez vs Alden Coria | 401912276 | prelims |

All three are prelims, so they can be graded before the main event ends. The
test `TonightsCard` runs this exact command against the saved card with the
three bouts synthetically flipped to final and gets three recorded rows and a
2-1 settlement; with the bouts still scheduled it correctly records nothing.
If any line says UNRESOLVED when you run it, the reason is printed; enter that
result by hand with `ufc result` as before. It costs one scoreboard request
plus 1 + 14 for the event, about six seconds.

## How a pick is matched to a bout

1. ESPN's scoreboard for the card date lists the day's events with every
   bout's two fighters, name and ESPN athlete id (the event document the data
   layer crawls has ids only). If a pick has neither fighter on it, the day
   before is read too: the card date is the UTC date a bout starts on, so a
   main-card bout after midnight UTC belongs to the next date while ESPN lists
   the event under the evening it began.
2. `names.match` runs on both of the pick's fighters. Each must resolve to
   exactly one ESPN athlete. Accents, punctuation, case, spacing and a "Jr."
   are folded; when two athletes fit equally well `names.match` refuses to
   choose and so do we.
3. A bout must exist whose two fighters are exactly those two athletes. If
   not, and a published fighter fought someone else in a final bout, the
   published pairing did not happen and the pick is VOID (the same rule the
   hand path uses). If it cannot be told apart from a spelling variant of the
   missing opponent, it is left for a person.
4. Anything else is left ungraded, with the reason: not on ESPN's card, name
   ambiguous, bout not final, final with no winner and no draw or no-contest
   marker, scoreboard and event document disagreeing.

Only the events that hold a published fighter are crawled, through the data
layer's `schedule.crawl_event` (the event, then one status document per bout).

## What is checked, and what is not

Checked:

- ESPN's own status document for the exact bout says final (or canceled).
- A winner is flagged on exactly one competitor; a draw or no contest carries
  no winner. A winner flagged on a bout ESPN calls a draw is left for a person.
- The scoreboard and the event document agree on who is in the bout and, when
  both flag a winner, on who won. If not the bout is HELD (ESPN is mid-edit).
- A result already on file (typed or automatic) is compared with ESPN's: the
  same grade is "agrees", a different grade is "DISAGREES (nothing changed)".
  The row on file stands; a correction is a new row entered by a person.
- Rows record where they came from: `entered_by` is `auto:espn`; `provider`
  `espn`, `provider_event_id`, `provider_fight_id` (the ESPN bout id),
  `fetched_utc` (when ESPN was read), `raw_status` (status, method, round,
  time) and `basis` (how the names were matched).

Not checked, and not claimed:

- ESPN is one source. Nothing here proves a result is right beyond what ESPN
  says. A result ESPN corrects after calling it final is not noticed by a
  normal run; run `--verify` later to compare again.
- ESPN has no explicit "this pairing was cancelled" for a replaced fighter.
  The old bout simply is not on the card any more, so the void is inferred
  from a published fighter appearing in a different final bout. On
  2026-09-26 ESPN lists no Mickey Gall anywhere; Sedriques Dumas is in bout
  401924683 against Luis Hernandez.
- ESPN labels both KO and TKO `kotko`; the audit's wording ("KO round 5",
  "TKO round 3") cannot be checked, only the round.
- Bout start times are per card segment on ESPN, so they are never used to
  match. The "has the bout started" guard still uses the ledger's time.
- The data layer's `dropped_from_event` marker (a bout we knew that left the
  card) is ours, not ESPN's. It is never read as a cancellation; the bout is
  held for a person.
- Terms of use: these are the unofficial public JSON endpoints the data layer
  already reads (docs/datasvc/UFC_SCHEMA.md). ESPN's terms for automated
  reading were not reviewed in this change. UFC.com is still never read.

## Names the odds feed spells differently

Published picks carry the odds feed's names; ESPN uses ring names. Tonight's
card has "Michael Parkin" in the ledger and "Mick Parkin" on ESPN, and ESPN's
own athlete record says first name "Mick" (`tests/fixtures/espn_mma/
w5_athlete_5060505.json`), so not even the data layer's aliases tie them. A
strict matcher leaves that pick ungraded and a fuzzy one would be guessing.

The middle path is `CONFIRMED_ALIASES` in `src/providers/espn_mma_results.py`:
a spelling a person has confirmed is one ESPN athlete, keyed to that
athlete's ESPN id and applied only when that athlete is on the card being
read, and the pair rule still applies (a bout between the two resolved
fighters must exist). Every entry carries its evidence. There is one entry:
"Michael Parkin" is ESPN athlete 5060505, confirmed as the same bout (ESPN's
scoreboard and Wikipedia's UFC 332 card both list Johnny Walker against Mick
Parkin; Walker has no other bout and no other Parkin is on the card). It
rests on bout identity, not on a biography: Wikipedia states no legal first
name. Delete the entry if you disagree and that pick will wait for a person.
A new mismatch is never bridged on its own: the pick is UNRESOLVED and the
reason names the ESPN candidate and how to fix it (a hand result or an alias).

## Validation on real history

Run live on 2026-10-03 through the real CLI (`ufc autograde --date D
--verify`, read-only, against the real ledger and the real hand-entered
results). Sixteen requests for the two dates (2 for 09-22, whose statuses
were already cached; 14 for 09-26), 24 of the 30 allowed counting the first
captures. Then replayed offline against an empty results store, so each line
below is ESPN's own answer with no hand row to agree with.

| Date | Pick (home vs away) | Hand-entered | ESPN | ESPN bout | Match |
|---|---|---|---|---|---|
| 09-22 | Piero Guaylupo vs Callum Connor | win Guaylupo (unanimous decision) | Guaylupo, decision unanimous, R3 5:00 | 401921411 | yes |
| 09-22 | Emilio Quissua vs Damian Piwowarczyk | win Piwowarczyk (TKO round 1) | Piwowarczyk, kotko, R1 4:55 (Punches) | 401921412 | yes |
| 09-26 | Robert Bryczek vs Rodolfo Vieira | win Vieira (unanimous decision) | Vieira, decision unanimous, R3 5:00 | 401911631 | yes |
| 09-26 | Christian Edwards vs Rodolfo Bellato | win Edwards (TKO round 3) | Edwards, kotko, R3 1:47 (Punch) | 401914467 | yes |
| 09-26 | Raoni Barcelos vs Raul Rosas Jr | win Rosas Jr (KO round 5) | Rosas Jr., kotko, R5 1:38 | 401911630 | yes |
| 09-26 | Sedriques Dumas vs Mickey Gall | cancelled (VOID) | Gall not on the card; Dumas fought Luis Hernandez (submission, R1 0:57) so the pairing did not happen: cancelled | 401924683 | yes |
| 09-26 | Ailin Perez vs Norma Dumont | win Perez (unanimous decision) | Perez, decision unanimous, R3 5:00 | 401914471 | yes |

Seven of seven agree; none disagrees. Fed through settlement the ESPN rows
give 5 wins, 1 loss, 1 void, +2.5027 units over the two events, with the same
per-pick grades and units as the hand-entered rows
(`ReplayOfTheSevenHandGradedPicks`). The Contender Series card (09-22) is on
ESPN's UFC scoreboard as event 600060738, so no separate source is needed for
it. The responses the tests rely on are saved as `tests/fixtures/espn_mma/w5_*`
(the 09-22 card and Mick Parkin's athlete record); the 09-26 and 10-03 cards
use the earlier `tests/fixtures/espn_mma` captures.

## Where each source stands

| Source | Names the winner | Cancelled / no contest / draw | Cost | Status |
|---|---|---|---|---|
| ESPN MMA (our data layer) | Yes, plus method, round and time | Draw and no contest have their own result codes; canceled is a status; a replaced fighter is inferred | Free, no key | Built and validated 2026-10-03. The default. |
| The Odds API (already paid) | No | No | n/a | Its sports table has no scores for MMA. Not usable. |
| BALLDONTLIE MMA, fights endpoint | Yes | `canceled` documented; draw / no contest encoding is not | "ALL-STAR" tier, about $9.99 a month for this one sport | Provider written from the documentation; never run against the live service. Selectable, not needed. |
| TheSportsDB | Not confirmed | Not confirmed | Free key or $9 a month | Could not confirm it carries UFC results. |
| Wikipedia | In prose and tables | In prose | Free | Allowed by licence; parsing is fragile. Kept as a manual source. |
| Sherdog, Tapology | Yes | Yes | Free to read | Terms not confirmed for automated reading. Manual only. |
| UFC.com | | | | Never: its terms ban automated and manual collection. |

## Decision for Brey

1. Nothing to buy. The BALLDONTLIE MMA tier would have cost about $10 a month
   to do what ESPN now does for free. Skip it, and cancel anything still
   billing on that account.
2. Hand grading stays as the override and for anything the command leaves
   UNRESOLVED, not as the routine. Nothing runs the command on a schedule yet:
   it is a command to run after a card, then `card settle`. The landing page
   still says results are graded by hand, which stays true until it is run.
3. Confirm or delete the one alias (`Michael Parkin` / `Mick Parkin`) above.
