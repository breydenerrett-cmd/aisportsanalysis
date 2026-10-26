# Jarvis pre-game briefing

Owner-only, paper-only daily briefing for Brey and Jacob (docs/TODO_UNTIL_SUNDAY.md item 4). Built only on stored LINEHOUND data: no web research, no paid API, no model call.

## Use

- CLI: `python -m src.cli jarvis brief --date YYYY-MM-DD [--as-of ISO] [--no-file] [--json]`. Prints in Pacific time, writes JSON to `data/app/jarvis/<date>__<as-of>.json` plus `<date>__latest.json` (beside the app database, so the Fly volume in production; `JARVIS_DIR` overrides), and files every pick with the Apprentice store. `--no-file` is the dry run.
- API (admin token, `api.auth._require_admin`): `GET /admin/jarvis/brief?date=` returns the latest saved briefing; `POST /admin/jarvis/brief {date, as_of?}` builds, saves and files one. `as_of` may not be in the future.
- JSON text fields carry `[[w:<ISO>]]` tokens; `web/js/local-time.js` shows them in the reader's zone. The CLI resolves them to Pacific.
- No page section: web/admin.html is a routed, fixture-tested dashboard and a new route touches its loader and tests. Follow-up, not done here.

## Rules (owner rulings), and where each is enforced

| Rule | Where |
|---|---|
| Never -200 or worse, best OR average price, max price clamped to -199 | `board.price_allowed`, `board.max_price`; tests `NoMinusTwoHundred` |
| One side per game; parlay legs from different games | `one_side.keep_first`, `brief.choose_parlays`; tests `OneSidePerGame` |
| Frozen as-of: later rows, lineups, forecasts ignored; started games left out | every reader takes `as_of`; tests `FrozenKnowledge` (with a control run) |
| EXPERIMENTAL on every uncalibrated number | `brief.CALIBRATED_SOURCES` is empty; tests `ExperimentalLabel` |
| Filed with source "jarvis" and the real publish time, once per (date, bets) | `brief.file_picks`; tests `FilingWithTheApprentice` |
| Paper only, no profit claims, 21+ / 1-800-GAMBLER, never "Bet Check" | `brief.DISCLAIMER`, render guard; tests `PaperOnlyWording` |

## How a pick is made

1. Boards: the newest capture per book at or before `as_of` (current) and each book's first capture (open). Game markets from `odds_multibook`, props from `batter_props` / `prop_prices` (MLB) or `allsports_props`.
2. Probability: a stored model output when one exists (today only the postseason forecast `POSTSEASON_PAGE_V1` for the moneyline), else the leave-one-out no-vig consensus of the other books (at least 3 others). A consensus "edge" is a price gap, not information.
3. Gates: at least +1% expected value at the best price, at least 4 books, best and average price above -200, quote not stale (2 h), a consensus edge above 15% is treated as a bad quote, a prop for a player not in a posted lineup is out.
4. Rank: confidence tier (about the price information, never a chance of winning), then expected value. Singles: one side per game, at most 2 per market, top 5. Parlays: best two pairs from different games, no shared leg. Fewer than three clearing says so; nothing is padded.
5. Vanished edges: what cleared on the open board and no longer does, with the open and current price.

## First real run (2026-10-26 slate, as of Sun Oct 25 10:53 PM PT), trimmed

```
Jarvis 2026-10-26 (MLB) as of Sun Oct 25 10:53 PM PT: 3 single(s), 0 parlay(s). Top: Milwaukee Brewers moneyline +104 (EXPERIMENTAL, low confidence).

 #1 Milwaukee Brewers moneyline [EXPERIMENTAL] confidence LOW
   best +104 at betonlineag, average +101 across 11 books, captured Sun Oct 25 10:08 PM PT; max acceptable price -128
   probability 56.8% vs break-even 49.0%, expected value +15.9% if the estimate is right (source: model)
   Why: POSTSEASON_PAGE_V1 (stored, not recalibrated) puts this at 56.8%; the 11 books' no-vig market says 47.8%.
        Probables: Robert Gasser (away) vs Freddy Peralta (home). Lineup: not posted yet (no data). Umpire: no data.
        Weather (stored forecast): 72.6 F, wind 12.4 mph from 26 deg, 1% rain, roof fixed. Injuries: no data.
   How it could lose: loses about 43.2% of the time even if the estimate is right; the model and the market are
        9.0 points apart and the market has tracked results at least as well as our models.
   Avoid: anything worse than -128; the other side of this game.
 #2 David Hamilton over 0.5 (batter hits + runs + rbis) -130 at betmgm, 4 books, EV +2.1% (consensus), LOW
 #3 Ryan Vilade over 0.5 (batter hits + runs + rbis) -130 at betmgm, 4 books, EV +1.7% (consensus), LOW

PARLAYS: none. The slate has one game with a priced pick; legs from one game are correlated and could hold both sides.
VANISHED EDGES: none.
LEFT OUT: ev_below_floor 45, price_at_the_ban 54, thin_market 128
```

Inputs present: 231 game quotes (11 books, captures 10-25 14:08 UTC to 10-26 05:08 UTC), 270 prop quotes, probables, weather forecast, transactions, event-to-game map, postseason forecast. Missing at that time: lineups (not posted), home-plate umpire (not assigned), injuries (no MLB injury feed is stored), no regular-season model output (card V2 and MLB value picks are paused), and no pitcher-strikeout quotes for this game.

Honest reading: the moneyline pick exists only because a stored, uncalibrated series model sits 9 points above the market, which is why it is LOW confidence. The two props are price gaps of about 2% across four books with no lineup yet. Treat all three as experiments.
