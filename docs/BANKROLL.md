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
| Stake, member dogs | the **units the owner chose** (0.5, 1, 1.5, 2, 2.5, 3, 4 or 5), read from the dog's own bet row. A missing or out-of-range stake is 1 unit. This supersedes the earlier "every bet counts as one unit" ruling **for the bankroll view only**; `record.units_*` is still flat, and `bankroll.units_flat` is the flat figure on the same price basis, for comparison. |
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

## Your unit size: paper dollars at your sizing (owner ask, 2026-10-21)

**Paper dollars at your unit size; units are the record.** Everything above is the *reference account* (a $1,000
start, a $10 unit) and it is what is stored, graded and ranked. A viewer chooses how the dollars on the pages are
sized, and nothing else moves: every bet, grade, rank, leaderboard order and "+2.4u" figure is unit-based and identical
for everyone. The dollar figures are a **lens** (`src/hounds/unit_size.py`, ported to `web/js/unitsize.js`; the two are
tested to agree to the cent).

Where the choice lives: a signed-in member's is on the account (`GET` / `PUT /me/unit-size`, validated server-side,
table `member_unit_size`, never in a public payload); a visitor's is in the browser (`localStorage`, wrapped so a
blocked or throwing store means the default). Default for everyone: **a fixed $25 unit**. The Account page holds the
settings; a small "1u = $25 ▾" chip sits beside the bankroll figures (My Kennel, the hound page, the leaderboard).
The payload carries `bankroll.events`, the units-only bet list (`[slate date, settle epoch, profit units, stake units,
result letter]`), so the browser can price the same bets at any sizing without another request.

| Mode | Unit | Starting bankroll | Dollars | Return % |
|---|---|---|---|---|
| **Fixed dollars** | any whole dollar $1 to $1,000 (chips $10 / $25 / $50 / $100) | **100 units**: $1,000 at $10, $2,500 at $25, $5,000 at $50, $10,000 at $100 | `units x unit` to the cent | `units / 100`, **identical at every unit size**; so are all ranks |
| **% of bankroll** | 0.5% to 5% of the balance **when the bet is placed** (steps of 0.5, default 1%) | the viewer's own, $100 to $100,000 (default $2,500) | compounds, see below | the compounded figure, labelled **"at your sizing"** |

`config/bankroll.json` still says one unit = 1% of the start (`unit_pct` = 1), which is why a fixed start of 100 units
makes the percent independent of the unit size.

### % of bankroll: how the compounding works

Bets are taken slate day by slate day. **Every bet of one slate day is sized off the same balance**: the balance after
every earlier slate day has settled, before any bet of this day settles. So concurrent open bets never size off each
other. A bet that stakes `s` units risks `s x pct%` of that balance and its profit is `profit_units x pct% x balance`.
Day end balance = balance + the day's profits. The peak and drawdown walk the balance in settle order; the 24h / 7d /
30d windows sum each bet's own dollars by settle time, exactly as the fixed view does. P&L is therefore **not** `units
x a constant` in this mode.

**Worked example.** 2% of a $5,000 start. Five bets on three slate days (`flat` is the one-unit profit):

| Day | Balance before | 1u = | Bet | Stake | Flat | Units | Dollars |
|---|---|---|---|---|---|---|---|
| Oct 1 | $5,000.00 | $100.00 | a (win) | 1u | +0.9 | +0.9u | **+$90.00** |
| Oct 1 | $5,000.00 | $100.00 | b (loss) | 2u | -1.0 | -2.0u | **-$200.00** |
| Oct 2 | $4,890.00 | $97.80 | c (win) | 1u | +1.5 | +1.5u | **+$146.70** |
| Oct 3 | $5,036.70 | $100.734 | d (win) | 3u | +0.5 | +1.5u | **+$151.10** |
| Oct 3 | $5,036.70 | $100.734 | e (push) | 1u | 0 | 0u | $0.00 |

P&L **+$187.80**, balance **$5,187.80**, return **+3.76%** at that sizing (the same bets are +2.9u / +2.9% in the
record). Wagered on decided bets $700.00, yield 26.83% per $ bet. Worst fall: $200.00 (b), 3.93% off the $5,090 peak.
Both bets of Oct 1 used $100.00 per unit, and so did both of Oct 3 ($100.734): the 1.5u won on Oct 2 paid $146.70 and
the 1.5u won on Oct 3 paid $151.10. Held by `tests/test_unit_size.py` (`PercentCompounds`) and cross-checked against
the browser port.

Not changed by any of this: the leaderboard order (it sorts on the reference account, which is unit-based), the
units, the record, the CLV and every stored row. Server-composed copy with no viewer (the Discord feed, emails, the
share card) speaks in the reference account.

## One price basis per model, and it is marked

A model's dollars and units are settled at the **board-average price** when at least 90% of its priced bets have
one (`bankroll.basis: "average_price"`). Below that the model is settled at **the price it took**
(`"recorded_price"`, the best quote) and the pages mark it "best price" with a tooltip: never a quiet mix. A
**loss is -1 unit at any price** and needs no board; coverage counts only real stored average prices (audit
2026-10-19: a loss with no stored board used to count 0, and `unitsOf` quietly fell back to the recorded price
while the column said "average price").

## The -200 rule

Owner ruling: no pick at -200 or worse is featured on any public card. Season 1 engine dogs have such bets, so they
stay in the record and in the money, and are **never featured**: not as a model's best bet or worst beat
(`form`), not in a streak item of the kennel feed, not in the digest's hottest / coldest / coin-flip lines (a dog
whose figures include one is not named; `old_rule_bets` on the summary, `old_rule` on a 7-day row). Every ticket
list carries a small "-200 or worse (old rule)" tag from the server's `beyond_cap` flag (the price taken OR the
average at `user_spec.beyond_cap`, the one definition).

## Slate day and "ungraded"

A ticket with no start time counts its slate day as ending at **midnight Eastern** (the game's official date), not
midnight UTC, before the 36-hour rule calls it ungraded (`contract._slate_end`).

## What this does not change

The record, the CLV, the verdict badge, the retirement rules, the rankings by CLV and every recorded ledger row.
The seasons are still windows over slate dates. The 150-bet rookie rule and the "no money is staked" disclaimers
stand: the dollars are simulated.
