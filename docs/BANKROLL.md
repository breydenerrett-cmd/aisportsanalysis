# The bankroll view

**Owner ruling, 2026-10-19.** "Bettors cannot be up 2 units and ROI can't be 71%; that doesn't make sense. All
simulated accounts should start with a $1,000 bankroll. Show the ROI % they're up over the week, 30 days and 24
hours. Units up should be total units up. Strategies differ: some units are 5% of bankroll, heavy bettors 20%. ROI
and units should correlate and help people understand what's really going on. Advertise that they all have the
same starting balance."

This is a **presentation of the bets that were already placed and graded**. No new bet, no new grade, no new
price, no recorded result or rule changed. Code: `src/hounds/bankroll.py`. Constants: `config/bankroll.json`.
Tests: `tests/test_hounds_bankroll.py`. Paper only; nobody staked anything.

## Why the old board contradicted itself

It put two different denominators on one row: **units** (a sum of profits, 1 unit per bet) and **ROI** (units
divided by the number of bets, a per-bet yield). A model up 0.9 units over 1 bet shows "ROI 94%": true, and
meaningless next to "up 0.9 units". The new board states one thing, the account balance, and everything else is a
view of that balance.

## The definitions

| Term | Definition |
|---|---|
| Starting bankroll | **$1,000**, the same for every model, every season view. `starting_bankroll` |
| Unit | **1% of the STARTING bankroll = $10.** `unit_pct`. Fixed: it does **not** grow or shrink with the balance (no compounding), so dollar profits are plain sums and a 7-day figure plus the earlier figure equals the season figure to the cent. |
| Stake, house / baseline / desk dogs | exactly **1 unit ($10)** per bet. |
| Stake, member dogs | the **units the owner chose** (0.5, 1, 1.5, 2, 2.5 or 3), read from the dog's own bet row. A missing or out-of-range stake is 1 unit. This supersedes the earlier "every bet counts as one unit" ruling **for the bankroll view only**; `record.units_*` is still flat, and `bankroll.units_flat` is the flat figure on the same price basis, for comparison. |
| Bet profit | the profit the page already uses: at the board-average price when 90% of the priced bets have one (`basis: average_price`), else at the recorded price. Dollars = units x stake x $10. A void or push is $0. |
| `current` | `1000 + pnl_usd`. |
| `pnl_usd` | the sum of the dollars above over the settled bets in the view. |
| `return_pct` | `pnl_usd / 1000 x 100`. Return on the **starting** bankroll. The headline % everywhere. |
| `units_total` | stake-weighted units won or lost: `pnl_usd / 10`. **`return_pct = units_total x unit_pct`** (unit_pct = 1.0), so units and % always move together. |
| `yield_pct` | profit per dollar **bet**: `pnl_usd / (stake in $ of bets that were won or lost) x 100`. This is the old "ROI". It stays on the model page, labelled "profit per $ bet", and is never put beside the units on a board. A push or void gets its stake back, so it is not money at risk. |
| `small_sample` | true when fewer than **20** settled bets (win, loss or push) are in the view. The UI greys it. |
| `peak`, `max_drawdown_usd`, `max_drawdown_pct` | the highest balance reached, and the worst peak-to-trough fall, bets taken in settle order, starting from $1,000. `pct` is of the peak the fall started from. |
| `windows.h24 / d7 / d30` | `pnl_usd`, `return_pct`, `units`, `bets` (graded in the window), `settled` (win, loss, push) for bets **settled** in `(now - 24h, now]`, `(now - 7d, now]`, `(now - 30d, now]`. A bet settled exactly 24 hours ago is **out**; a settle stamp after `now` counts as just now. |
| `windows.season` | the whole view (a season, or all-time). Equal to the top-level figures. |

### Windows are by settle time, inside the view

* **Settle time** is `graded_utc` (pack and member graded rows, the card's per-day `settled_utc`). The engine
  account ledgers carry only the slate day, so for those the settle time is **estimated** as 00:00 UTC of the
  slate date + `fallback_settle_hours_after_slate_start` (**30 h**, i.e. 06:00 UTC the next morning, after the
  last west-coast game). `settle_estimated` counts how many bets used the estimate; the UI does not hide it.
* A **season view** (`?season=s2`) holds only that season's bets, so its 7d and 30d figures never reach into an
  earlier season; they can never exceed what the season itself shows. The all-time view windows over everything.
* The windows are **recomputed against the clock every time a payload is built** (`bankroll.refreshed`). The
  cached book can be hours old; "24h" always means the 24 hours before the request. (The saved copy served
  during a restart carries the windows as of its build, and says so with `stale: true`.)

### Season views are separate accounts

Each season is its own account from $1,000: the Season 2 board shows how a model has done since Oct 18 with a
fresh $1,000, and the all-time view is the whole run from one $1,000. Nothing is carried over or compounded.

## Worked example

A house dog wins 1 bet at +110 (average price), loses 2: `+1.10 - 1 - 1 = -0.90 units` = **-$9.00**, balance
**$991.00**, return **-0.90%**, units **-0.90**, yield **-30.0%** per $ bet ($30 at risk).

A member dog stakes 3 units on the +110 win, 0.5 and 2 units on the two losses: `+3.30 - 0.50 - 2.00 = +0.80
units` = **+$8.00**, balance **$1,008.00**, return **+0.80%**. The same three bets counted flat are -0.90 units
(`units_flat`). The dollars and the % are the member's real (paper) result; the flat number is the comparison.

## Where it appears

| Place | What |
|---|---|
| `GET /hounds`, `/hounds/graveyard`, `/hounds/{id}` | every summary gains `bankroll` (additive; every old field is unchanged). The envelope gains `bankroll_rules` (start, unit, label). |
| `GET /hounds/series` | every series point gains `bankroll_usd` (the balance after that slate day; the first point is the opening $1,000). |
| Leaderboard | Model, Type, Record, Bankroll, Return, 7d, 24h, Units, Bets, Avg price, CLV, Last 10, Status. Header line: "Every model starts with the same $1,000 paper bankroll. 1 unit = $10." Default sort: bankroll. Small samples are greyed with a tooltip. |
| Model page | Bankroll, Return (24h / 7d / 30d / season tabs), Units, Record, Max drawdown, Yield ("profit per $ bet"); a bankroll line chart in dollars. |
| Landing board | the top five by bankroll, with return %. |
| Builder | "1 unit = $10 of your $1,000; this dog bets N units" beside the stake picker. |

## What this does not change

The record, the CLV, the verdict badge, the retirement rules, the rankings by CLV and every recorded ledger row.
The seasons are still windows over slate dates. The 150-bet rookie rule and the "no money is staked" disclaimers
stand: the dollars are simulated.
