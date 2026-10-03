# Decision: serve run line and totals

For Brey. One switch, zero credits. Written 2026-10-03.

## Recommendation

**Turn it on.** Staging first, production after one look. It costs no Odds API
credits: the capture already requests and stores both markets, and the site
simply never served them.

The switch, one line in the `[env]` block of `deploy/fly.staging.toml`, then
`deploy/fly.production.toml`:

```
RUNLINE_TOTALS = "on"
```

Default is off. Unset, empty, or any value other than `1/true/yes/on` is off,
and with it off every payload and page is byte-identical to before. Remove the
line to turn it off again. (Not edited here: it is deploy config and the call
is yours.)

## What we found

The task assumed spreads and totals were not being requested. They are.

- **What each path requests.** `src/providers/odds.py` `DEFAULT_MARKETS =
  ("h2h", "spreads", "totals")`. Every featured MLB and NFL call
  (`snapshots.capture`, reached from `dense.run`, `dense.close_capture` and
  `nfl_capture`) goes through `fetch_normalized()` with no `markets=` argument,
  so it asks for all three. `ODDS_API_MARKETS` is not set in any workflow,
  script or deploy file (only in `.env.example`, as `h2h,spreads,totals`).
  Tennis, MMA and the in-play capture (`live_odds`) ask for `h2h` only.
  Per-event calls (F5, pitcher/batter props, team totals, alternates) are
  separate and unchanged.
- **What it costs today.** A featured call is `markets x regions` = 3 x 1 = **3
  credits** (`src/capture/budget.py` "featured: flat 3 credits"; `dense.py`
  guards it with `can_spend("featured", 3)`). Measured on the credit log:
  `nfl_capture.run` shows a 3-credit step on 651 of its 720 logged calls
  (`data/processed/credit_log.jsonl`).
- **It is stored.** Raw bodies in `data/raw/oddsapi/` carry all three markets.
  `data/processed/odds_multibook.jsonl` (96,717 rows at 2026-10-03 17:05Z, hot
  file only) holds MLB 2,567 h2h / 2,515 spreads / 2,578 totals and NFL 22,199 /
  27,267 / 27,410, since 2026-09-03 (MLB hot file from 2026-09-30; older rows are
  in the archive segments). `odds_snapshots.jsonl` has them too.
- **Why they never showed.** `prices.boards_by_matchup` filters to moneyline rows
  on purpose (`snapshots.moneyline_rows`, the 2026-09-07 fix) and
  `oddspayload.MARKETS = ("h2h",)`.

## Cost, current and added

Counted from the raw capture files, 2026-09-03 to 2026-10-03 (31 days):

| | featured calls | credits at 3/call | of which spreads+totals (2 of 3) |
|---|---|---|---|
| MLB | 682 (mean 22/day, max 52/day) | 2,046 | 1,364 (about 44/day) |
| NFL | 622 (mean 20/day, max 92/day) | 1,866 | 1,244 |

- **Added cost of turning the switch on: 0 credits.** It reads the store that is
  already written. Cost is CPU: the date-windowed read of the hot store took 0.4
  s here, once per 120-second cache window, streamed (no whole-store load).
- **Hypothetical, for the record.** Had the capture been h2h-only (1 credit a
  call), adding both markets would cost +2 credits a call: +44/day at the MLB
  mean, +104/day at the MLB max, about +1,400/month MLB and +1,250/month NFL
  at this cadence, against a ~100,000/month allotment (`docs/RESOURCE_POLICY.md`).
  That money is already being spent and already buying stored rows.
- **Risk to watch.** If anyone sets `ODDS_API_MARKETS=h2h` to save credits, the
  stored rows stop and the switch shows "no run line / total recorded" per game.
  It fails visible, not wrong.

## What it buys

- Run line and total prices on the game page, the Odds tab, and
  `GET /odds/{date}` / `GET /odds/{date}/{away}/{home}`: main line, best price per
  side with every book quoting it, the de-vigged fair price when 6 or more books
  quote that line, book count, and other lines noted separately.
- The owner's MLB focus (props and run lines) gets a price surface; the card's
  run-line picks (`daily_card` run line rows) get a market to be read against.
- Honest by construction: best price is only compared across books on the SAME
  line (a book hanging 7.5 never sets the best price on 8.5), boards are
  pre-game only, and a started game's block is labelled LAST PRE-GAME PRICE with
  its capture time.
- NFL: the stored NFL spreads/totals are not served by this change. The odds
  routes are MLB (`mlb.fetch_games`); NFL value surfaces are separate and
  untouched. Not needed to decide this.

## What it does not change

No pick, gate, record, fingerprinted card file, or credit path. No new Odds API
call anywhere.

## Verify after flipping it

`GET /odds/{date}/{away}/{home}` returns `markets` with `h2h`, `spreads`,
`totals`; the game page shows a PRICES block under the moneyline. If a game says
"no run line / total observations recorded", check that game's rows in
`odds_multibook.jsonl` (`market` of `spreads`/`totals`) before suspecting the code.
