# Example accounts

What a bankroll would be today if it had bet every pick we published since
2026-09-22. Shown on the public record page (`#/record-card`, section "If you
had followed every pick"), per sport and for all sports, for a few accounts.
It is arithmetic over the public record. It is not a real account and not a
forecast.

Code: `src/appstate/example_accounts.py` (pure), `GET /card/accounts` in
`api/card.py`, `web/js/exampleaccounts.js` (mounted by `web/js/cardrecord.js`),
settings in `config/example_accounts.json`.

## Definitions

- **Start**: the morning of 2026-09-22 (`start_date` in the config). A pick
  dated earlier is in no account.
- **Which picks**: every pick the public card published and the ledger has
  settled. Fills are never bet. A withdrawn entry is not a pick. A pick with
  no result yet moves no balance.
- **Price and units**: the price each pick was graded at. Units for a 1-unit
  stake are the ledger's own `profit_units`. A push or void returns the stake
  (0).
- **Staking**: `flat` puts the same dollars on every pick. `percent_of_balance`
  puts that percentage of the balance at the START of the day on every pick of
  the day (a day's picks are concurrent). A day's result is stake times the
  day's units. Dollars are carried at full precision (Decimal) and rounded to
  cents only where the page prints them (half a cent rounds up).
- **Accounts** (the tracked config): `flat100` $10,000 and $100 a pick,
  `flat250` $10,000 and $250 a pick, `pct1` $10,000 and 1% of the balance,
  `starter` $1,000 and $10 a pick. A bad config is "unavailable", not a crash.
- **Per sport**: MLB, NFL, UFC are three separate accounts that each bet only
  that sport. **All sports** is one account that bets every pick of the three.
- **Rows**: one per date with settled picks (date, picks, W-L with pushes and
  voids when not zero, the day's dollars, the balance after, a postseason
  flag). A day whose picks are only partly settled is a row with the picks
  that finished and a "partial" flag. Published picks with no result at all are
  listed as pending (a count per sport, never a name) and move no balance.
  Per series: start, final, units, lowest end-of-day balance and its date.
- **Percentage return** is printed only from 30 graded picks (wins plus
  losses). Below that the page says how few have been graded, in the sentence
  style the record page already uses ("Only 6 UFC picks have been graded...").

## How the population is tied to the record

The account never decides which picks count. It reads the rows the record
routes read and checks them against the record the site publishes, exactly:
pick count, wins, losses, pushes, voids and units to 4 decimals, per sport.
Any difference makes `/card/accounts` return `{"available": false, ...}` and
the page shows one sentence instead of balances. The check runs at serve time
(`example_accounts.reconcile`, shown in the payload's `reconciled` block with
the record numbers on the other side) and in `tests/test_example_accounts_*`.

**MLB.** The published record is the counted record (rule v2, regular season:
16-17, 5 voids, -5.0463u) with a postseason cohort kept apart ("graded, not
counted": 0-2, -2.0u). An account that followed the card would have bet the
postseason picks, so the MLB account is the counted record PLUS the postseason
picks (40 picks, 16-19, 5 voids, -7.0463u), and each half is checked against
its own published figure. A third check ties the pooled total to
`record_v2()["combined"]`.

**Why a naive pass is 20-20 and the record is 16-17.** A pass over
`/card/history` entries with `entry_class == "pick"` gives 20 wins, 20 losses,
6 voids, -4.1187u. Two rules separate that from the record, proven entry by
entry in `tests/test_example_accounts_reconcile.py`:

1. A **withdrawn** entry (4 wins, 1 loss, 1 void, +2.9276u) was taken off the
   card before its game. `record_v2` counts it apart as `withdrawn`, and it is
   not a pick the card published. Without it: 16-19, 5 voids, -7.0463u.
2. The **postseason** is left out of the counted record (registration 11.1).
   The two losses of 2026-10-01 are player props frozen with `game_type: "R"`;
   the record knows them as postseason because their card's date is inside the
   season's postseason calendar (`effective_record._ledger_postseason_pks`,
   applied to the history by `api.card._mark_postseason`). Without them:
   16-17, 5 voids, -5.0463u, the published record.

Fills never enter either count. One row per date is the newest settlement pass
(`history_v2` reads `latest_settled_rows_v2`), so a re-settled date is not
counted twice. `graded_without_lock_run` and price class do not change which
entries count; the pooled check above would show it if one did.

**NFL and UFC.** Every settled pick of the rule the record counts (NFL_CARD_V2,
UFC_CARD_V1), all market kinds pooled, each day's listed picks checked against
that day's own totals (the record sums those totals, not the lists). The
retired NFL_CARD_V1 stopped publishing on 2026-09-20, before the start, so none
of it is in any account.

**Reads.** The route builds from the same public memo entries the record page
fills (`/card/record` for each sport and `/card/history?limit=60`), so it
reads no ledger of its own. Only while a day is partly settled (the public
history withholds that day, the record still counts its finished picks) is one
sport's settled rows read again, and only results and units are used. The
answer is memoised per ledger state plus the config file. A history longer
than 200 days is refused rather than cut.

## What the numbers are today

As of 2026-10-01, the last settled date, on the ledgers in this branch:

| account | MLB | NFL | UFC | All sports |
|---|---|---|---|---|
| `flat100` $10,000, $100 a pick | $9,295.37 | $10,092.59 | $10,250.27 | $9,638.23 |
| `flat250` $10,000, $250 a pick | $8,238.43 | $10,231.48 | $10,625.68 | $9,095.58 |
| `pct1` $10,000, 1% of balance | $9,304.89 | $10,092.59 | $10,251.71 | $9,635.65 |
| `starter` $1,000, $10 a pick | $929.54 | $1,009.26 | $1,025.03 | $963.82 |

Reconciliation, account against published record:

| sport | account (picks, W-L, voids, units) | published record |
|---|---|---|
| MLB | 40, 16-19, 5, -7.0463 | counted 38, 16-17, 5, -5.0463 plus postseason 2, 0-2, 0, -2.0 |
| NFL | 1, 1-0, 0, +0.9259 | 1, 1-0, 0, +0.9259 |
| UFC | 7, 5-1, 1, +2.5027 | 7, 5-1, 1, +2.5027 |
| All sports | 48, 22-20, 6, -3.6177 | sum of the three above |

Percentage returns are printed for MLB (35 graded) and All sports (42 graded)
and not for NFL (1) or UFC (6). Pending now: 8 MLB picks and 3 UFC picks, in no
balance.

## What is not claimed

- It is not a real account. Prices move, sportsbooks limit bets, and nobody
  bets every pick. The page says so, and that past results do not predict
  future results and that this is analysis, not advice.
- It says nothing about the future and makes no claim of an edge. A loss is
  printed with a minus sign and "Down" in the headline, at the same size as a
  gain.
- It does not say the accounts could have been run. A flat or percentage stake
  is sized from the balance at the start of a day and is not capped, so on a
  night with many picks the stakes can add up to more than a small account
  holds; a percentage account that reaches zero stakes nothing from then on.
- **The first night is half of the MLB account.** 2026-09-22 is V2's own
  first night: 21 of the 40 MLB picks (8-11, 2 voids, -5.144u, which is -$514.40
  at $100 a pick); every later night with picks has between 2 and 6.
  V1 was still the card of record in front of readers that day
  (`CUTOVER_DATE` is 2026-09-23), but V2's published record counts 09-22 from
  its own ledger and the account must equal that record, so 09-22 is in. To
  start from the first night V2 was the public card, set `start_date` to
  `2026-09-23` in the config: the reconciliation still checks the whole record,
  and `from_start` in the payload shows what the account then holds.
- NFL and UFC are one and six graded picks. No percentage is printed for
  them.
