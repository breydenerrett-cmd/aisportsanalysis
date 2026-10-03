# Signed-in Today page: the nightly card rendered wrongly (2026-10-03)

Scope: display only. Fixed in `web/js/card.js`. Nothing published to the ledger,
no selection, no ordering, no fingerprinted file and no server code changed.

## What a tester saw

Local server, signed in with a tester token, `#/today`, night of 2026-10-03.
`GET /card` served the frozen V2 row (`DAILY_CARD_BEST_BETS_V2`, newest published
row, `row_hash` ceae8d39...): `n_picks 8`, `picks []`, `prop_picks` 8, `fills` 2,
`all_bets` 10, every entry a different player.

1. "TONIGHT'S CARD 0 picks" directly above "TODAY'S BETS 10 bets".
2. Ten cards that all read "#N . Ty France . best of 4 books": the first pick,
   ten times.
3. The bet line (`data-hook="card-prop-bet"`) was empty on every card.
4. The breakdown read "Needs 61%% to break even at -155".
5. The two fills (Brayan Rocchio, Will Smith) were drawn as ordinary picks,
   with nothing marking them as fills.

## Since when (confirmed by rendering the ledger, not guessed)

Every published V2 row in `evidence/cards_v2.jsonl` was rendered through the old
`card.js` exactly as `GET /card/{date}` serves it (newest published row per date).
The ledger has never stored a `bet` string on any V2 entry, so this was wrong on
every V2 date, not only on days with several props:

| Date | Entries (picks + fills) | What the old page did |
|---|---|---|
| 2026-09-22 | 24 (21 + 3) | 24 cards, 1 distinct player; "0 picks"; empty bet lines; "%%" |
| 2026-09-23 | 10 (6 + 4) | 10 cards, 2 distinct (first game pick, first prop); "1 picks" |
| 2026-09-24 | 10 (6 + 4) | 8 cards, 1 distinct; the 2 moneyline fills silently dropped; "0 picks" |
| 2026-09-25 | 10 (5 + 5) | 10 cards, 2 distinct; "2 picks" |
| 2026-09-26 | 10 (0 + 10) | no card drawn: NO CARD TODAY (or yesterday's card, itself wrong) |
| 2026-09-27 | 6 (0 + 6) | same |
| 2026-09-29 | 1 (0 + 1) | same |
| 2026-09-30 | 5 (0 + 5) | same |
| 2026-10-01 | 3 (2 + 1) | 3 cards, 1 distinct player; "0 picks" |
| 2026-10-03 | 10 (8 + 2) | 10 cards, 1 distinct player; "0 picks" |

10 of 10 dates with a published V2 row (there is no row for 09-28 or 10-02).
By published version: 80 of 83 rendered wrongly; the other 3 are empty early
versions with nothing to draw. Every card that was drawn had an empty bet line.

The "%%" is older and wider than V2: `pct0(pick.breakeven)` plus a literal "%" has
been in `card.js` since 2026-09-16 (commit d248dbe3), and V1 prop picks carry
`breakeven`, so V1 prop cards printed it too. The resolver (`p.bet === item.bet`)
dates from 2026-09-14 (commit 9df1261b) and was correct for V1 references.

## Cause

1. **Repeated first pick.** `resolveAllBetsItem` was written for V1's
   `all_bets`, whose items are references `{kind, index, bet}`. It looked a pick
   up with `list.find(p => p.bet === item.bet)`. A V2 `all_bets` entry is the full
   candidate with `bet: null` and no `index`, so `null === null` matched the first
   element every time. On a night with no pick in the array to match (fills only)
   nothing matched, every entry was dropped, and the page fell back to NO CARD
   TODAY or the previous night.
2. **Empty bet line.** The V2 ledger stores no `bet`, `why` or `book`. The page
   rendered `pick.bet || ""`. The server cannot supply the sentence at serve time
   either: `best_bets_card.bet_sentence` reads `pick["bet_sentence"]`, which is not
   a frozen field, and the candidate's raw sentence names the market key
   ("batter_hits") and leaves out over or under.
3. **Headline.** `meta` was `picks.length` (game picks only), so a card made of
   props said 0.
4. **"%%".** `pct0()` returns "61%"; the template appended another "%". The other
   path (`breakevenPct`, from the price) returned a bare number, so the two paths
   disagreed about who owns the sign.

## Fix (`web/js/card.js`)

- Entries are matched by identity. A V2 entry (it carries `entry_class`, or its
  own price and no `index`) is its own pick. A V1 reference resolves through
  `index`, corroborated by its sentence, as before. A missing sentence is never
  scanned for: two nulls are not a match.
- The bet sentence for a V2 entry is composed from its own stored fields with
  `entrytext.betText` (the one shared wording function the record page and the
  landing sample already use) plus the price, and "Take " in front only when the
  entry's own `take` is true, the same rule as `best_bets_card.bet_sentence`.
  Examples from 2026-10-03: first entry (a fill) "Brayan Rocchio over 0.5 total
  bases at -135"; second entry "Take Ty France over 0.5 hits at -155".
  A sentence the server does send is used as sent.
- Fills carry the label "Fill, not a pick" (same words as the record page), a
  line under the bet saying it did not pass every check and is graded apart from
  the picks, and `data-entry-class="fill"`. Picks carry neither.
- The headline for a V2 card counts the entries it draws by their own
  `entry_class`: "8 picks . 2 fills" (no fill clause when there is none). On all 83
  published versions this equals the payload's `n_picks` and `n_fills`. A V1 card
  keeps "N of M games".
- `breakevenPct` now returns a string with its sign, like `pct0`, and the line is
  `Needs ${needs} to break even at ...`. One fix covers the game, prop and total
  card builders, which share that breakdown.
- A V2 card's "View breakdown" panel id now includes its position. `game_pk`
  alone is shared by every prop on one game, so panels shared an id and
  `aria-controls` pointed at the wrong one. V1 ids are unchanged.

## NFL and UFC pages: checked, not the same defect

Their payloads carry `picks` only (no `all_bets`), so the resolver is never
reached, and their picks carry no `breakeven`, so the break-even line was built
from the price and printed one sign before this change. Both are pinned by tests
that render two NFL picks and a UFC pick and assert distinct sentences and no
"%%". No change needed for them.

## Tests

`tests/test_web_card_v2_render.py` runs the real `card.js` under node against a
fake DOM and a stubbed `apiGet`, fed with the real ledger rows copied verbatim to
`tests/fixtures/card_v2_row_2026-10-03.json` and `card_v2_row_2026-09-25.json`
(never the live ledger), plus a V1-shaped regression payload. One route test
(skipped without FastAPI) serves both fixture rows through
`api.card.get_card_for_date(rule="v2")` and checks the response is the stored row
untouched: `row_hash`, `prev_hash` and every stored field equal.

## Not changed, and worth a decision

- `src/report/card_v2.py`, `src/analysis/best_bets_card.py`,
  `src/appstate/card_ledger.py`, `src/analysis/ufc_card.py`: untouched
  (fingerprinted). Ledger content, selection and order are as published.
- The section sub-line still says "ranked by how likely it is". V2 does not order
  that way, and on 2026-10-03 the first card is a fill (it had already locked;
  it is first in the stored order). Positions are the order as served. Not changed
  because it is a claim about V2's ordering that needs the owner's wording.
- V2 entries carry no `why`, so the cards show no reason line and no "Our number"
  in the breakdown, and the registered "our own number has not been shown to beat
  the market's" line is not on the card face. `best_bets_card.why_sentences`
  could be called at serve time to supply them. Left alone: not part of this
  defect and it would add server-side decoration.
- The empty-card state (`emptyCard`, MLB) still links "CHECK A BET OF YOUR OWN" to
  Bet Check, which conflicts with the 2026-09-22 ruling to never advertise it.
  Pre-existing, outside this change, reported only.
