# UFC picks graded by hand, 2026-10-01

Seven picks on two published cards had never been graded. Results were read
from news and reference pages (never UFC.com, per
`src/pipeline/ufc_results.py`), each bout confirmed in two independent
places, entered with `python -m src.cli ufc result` and settled with
`python -m src.cli card settle --sport mma --date ...`. The ledger gained two
`card_settled` rows; nothing published was changed.

| Date | Pick (locked price) | Result of the bout | Grade | Units |
|---|---|---|---|---|
| 2026-09-22 | Piero Guaylupo (-116) | beat Callum Connor, unanimous decision | WIN | +0.86 |
| 2026-09-22 | Damian Piwowarczyk (-135) | beat Emilio Quissua, TKO round 1 | WIN | +0.74 |
| 2026-09-26 | Rodolfo Vieira (-171) | beat Robert Bryczek, unanimous decision | WIN | +0.59 |
| 2026-09-26 | Rodolfo Bellato (-178) | lost to Christian Edwards, TKO round 3 | LOSS | -1.00 |
| 2026-09-26 | Raul Rosas Jr (-162) | beat Raoni Barcelos, KO round 5 | WIN | +0.62 |
| 2026-09-26 | Mickey Gall (-145) | bout did not happen: Gall was removed two days before and Sedriques Dumas fought Luis Hernandez | VOID | 0.00 |
| 2026-09-26 | Ailin Perez (-143) | beat Norma Dumont, unanimous decision | WIN | +0.70 |

Record: 5-1, +2.50 units over 2 events, 1 void. Six picks is far too few to
mean anything; every one was a favourite.

Sources read on 2026-10-01:

- 2026-09-22 (Contender Series, season 10, week 7): Cageside Press results
  article; Wikipedia, "Dana White's Contender Series season 10".
- 2026-09-26 (UFC Fight Night: Rosas Jr. vs. Barcelos): Wikipedia event
  page; Sherdog event page.

Worth knowing: the Gall pick was published and locked on the day of the
event, two days after Gall had been replaced. The odds feed still listed the
old pairing. A void is the correct grade, but the card showed a bout that
was never going to happen.

`data/historical/ufc_results.jsonl` is now tracked (it was git-ignored, so
the only copy of who entered what was on one PC). Each row names who entered
it and when. A wrong entry is corrected with a new row, never an edit.

Also fixed: the UFC tile on the landing page said "Graded nightly". It now
says "Graded by hand after each event".
