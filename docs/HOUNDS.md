# LineHound Hounds

A public, paper-only race of betting strategies. Paper only, not advice: no
hound stakes money, and nothing here tells anyone what to bet.

## What a hound is

A **hound** is a named rule that makes simulated flat one-unit bets. The rule is
written down before the game, the bet is recorded before first pitch, and the
result is graded afterwards from official scores. Every hound has a name, a
one-line tagline, a plain-English `rule_text` that you can copy, a `category`
(`stats`, `history`, `market`, `math`, `esoteric`, `random`, `mixed`,
`baseline`) and a short `style` label.

Three kinds:

* `house` -- built by us.
* `user` -- built by a visitor (see `src/hounds/user_*.py`, `api/hounds_create.py`).
* `baseline` -- an instrument, not a contender: "always home", "always under",
  the market-follower. They are listed, graded and refereed like everyone, but
  never lead the board. A good hound has to clear them.

## The house pack

Two sources, both editable without code:

1. `config/house_hounds.json` -- hounds backed by systems the engine **already
   paper-trades every day** (45 systems, a real forward record from
   2026-09-02, graded in `data/paper_accounts/<system>.jsonl`):

   | Hound | Kind | System | Rule in one line |
   |---|---|---|---|
   | Beagle | baseline | `trivial_always_home` | the home team on the moneyline, every game |
   | Basset | baseline | `trivial_under_total` | the under, every game |
   | Collie | baseline | `market_derived_consensus_totals_over` | the over, every game, carrying the market's own number as its opinion |
   | Pointer | house | `e5ff00d4b3899ccc` | three pre-registered pitching signals |
   | Setter | house | `e7f41ed66082c279` | three pre-registered lineup-vs-pitch signals |
   | Whippet | house | `7f7b7086400aea0b` | lineup-vs-pitch plus two pitcher signals |
   | Terrier | house | `6093c1cf8a6d6c08` | pitch share, ground balls, top-heavy lineups |
   | Spaniel | house | `e64c85130b4664cc` | platoon, lineup-vs-pitch, pitch share |
   | The Old Dog | house (retired) | the paused public card | see below |

   The five signal hounds are evolab genomes. Their `rule_text` is **generated
   from the genome** by `src/hounds/house.py:genome_rule_text`, and
   `tests/test_hounds_house.py` regenerates it and compares, so the copy cannot
   drift from what decides. The baselines' sides are checked against the
   engine's own classes in the same file.

2. `config/house_pack.json` -- the strategy pack (stats/model, history,
   market, math, esoteric, seeded-random control, ensembles ...), defined and
   bet by `src/hounds/pack/*` into `evidence/hounds_house_v1.jsonl`. Read here,
   never written.

**The Old Dog** is LineHound's paused public MLB value card, read through the
card ledger's own read function (`card_ledger.history_v2`). Retired by the
owner's decision of 2026-10-16: "paused 2026-10-16: paid a premium over the
market's fair number" (`docs/decisions/MLB_VALUE_PICKS_PAUSED.md`). Its picks
and fills are counted as published. The referee does not re-measure it
(`NOT MEASURED`): card entries are not engine decisions with a stored closing
board.

## The referee: "good or lucky"

Pre-registered in `docs/PREREG_HOUND_VERDICT.md` (committed before the code and
before any hound's closing-line numbers were looked at). Short version:

* The label reads only **closing-line value** on the hound's **forward**
  bets: the price it took against where the de-vigged multi-book market closed
  (`src.report.clv`, unchanged), mean with a 95% date-clustered bootstrap
  interval.
* `TOO EARLY` until 150 bets have a measurable closing price. Then
  `BEATING THE CLOSE` (interval entirely above 0), `PAYING THE VIG` (entirely
  below 0) or `NO DIFFERENT FROM THE MARKET`.
* The price taken carries the book's margin and the close does not, so the
  measure starts below zero for everyone. That is what the label name says.
* **Units never move the label.** Win/loss units are a separate line, and under
  1,000 bets it says they say nothing.
* **Replay is separate.** A rule written on 2026-10-18 and applied to boards
  captured earlier is a rehearsal. Replay bets are summarised in their own block,
  tagged `segment: "replay"`, and never counted in the verdict, the record, the
  series, status, or `verified`.
* **Retirement is mechanical** (house hounds): down more than 25 units at the
  average price, or `PAYING THE VIG` at 300+ measurable bets. The date is the
  first settled day the condition held, found by walking the days in order;
  later bets cannot un-retire a hound. **Benched** = no bet in 7 days of the
  data's own as-of day. Retired hounds live on `/hounds/graveyard` with their
  full record and the cause.
* `verified`: at least 90% of a hound's priced bets can be checked against the
  captured odds, and at least 95% of those checkable bets found their recorded
  price (same book, same side, same line) on the last capture at or before the
  decision.

`units_average_price` re-settles the same bets at the board's mean decimal
price at decision time (at least 3 books quoting the selection); it is null
unless that board exists for 90% of priced bets.

## Routes (public, read-only, no auth)

| Route | Returns |
|---|---|
| `GET /hounds` | leaderboard: running and benched hounds, each with `spark` |
| `GET /hounds/{id}` | one hound: summary, `series`, first page of bets |
| `GET /hounds/{id}/bets?page=&page_size=&segment=&status=` | bets, newest first. `status=open\|ungraded\|graded` splits them. Every row carries `status`: `OPEN`, `GRADED`, or `UNGRADED` (no grade and more than 36 hours past the start; the slate date, counted as the end of that day, stands in when the start is unknown). A month-old bet is never open; the summary's `open_bets` and `ungraded_bets` count them apart |
| `GET /hounds/stream?page=` | newest decisions across all hounds, refusals marked |
| `GET /hounds/graveyard` | retired hounds with their cause |
| `GET /hounds/series?ids=a,b,c` | cumulative-units series for line charts |
| `GET /hounds/learning` | the learning loop's system scorecard (promotion hit rate, champions vs the random controls on the same games, activity, the false-discovery budget, the pause) |
| `GET /hounds/learning/lessons?hound=&category=&page=` | every ended challenger's lesson, newest first |
| `GET /hounds/{id}/lineage` | a hound's versions (each with its own record), live challengers, tried-and-failed list and lessons |
| `GET /hounds/{id}/rulebook` | the rule, the plain "bets when" line and, for a tunable pack hound, its dials with current values and when the referee last changed them (`src/hounds/dials.py`) |
| `GET /hounds/{id}/tips` | the newest 20 fan tips for a tunable hound and the count |
| `POST /hounds/{id}/tips` | send a fan tip `{values: {knob: value}, nickname?}`; same validation as the AI coach (bounds, step grid, at most 2 knobs); 3 a day per caller, 60 a day for the site, counted in the app database |
| `GET /hounds/tips/export?since=` | every tip, oldest first, with the champion's values at the time (no addresses or hashes), for the grading job |
| `GET /d/{id}` | not JSON: a tiny page of Open Graph tags (name, W-L, paper units, catchphrase) that sends a person on to the dog page; what the Share button links to |

Every bet row also carries `start_utc` (first pitch) and `recorded_utc` (when the row was written, never the
lock deadline). The dog page's "on the record before the game" line is `recorded_utc < start_utc` and says less
when either is missing.

**A fan tip never changes a dog.** It is a row in a table (`src/hounds/fan_tips.py`); only the referee
changes a dog. Tips are graded later like the AI coach's proposals.

**Seasons** (owner decision 2026-10-19; `config/seasons.json`, `src/hounds/seasons.py`). The leaderboard mixed
models that began on Aug 31, on Sep 9 and on Oct 18, so a 1-0 model could top it. A season is a date window over
the forward bets (slate dates, both ends inclusive; Season 1 is Aug 31 to Oct 17, Season 2 starts Oct 18). It is a
VIEW: no bet leaves the all-time view and no ledger is touched.

- `GET /hounds`, `/hounds/{id}` and `/hounds/series` take `?season=s2|s1|all` (default `s2`; anything else is a 422).
  `/hounds/{id}/bets` takes the same filter but, with no `season`, lists every bet. Each payload carries a `season`
  block (id, label, dates, `min_ranked_bets`, the available seasons).
- A summary's record, units, CLV, typical price, last ten, streak, spark, series and open-ticket count are the SAME
  `stats.summarize` run over only the bets in the window (`stats.summarize_window`); replay bets are in no forward
  figure. The referee's verdict (label, sentence, `verdict.n`), the status, retirement, `verified` and the first and
  last ticket stamps stay all-time, and the pages say so.
- `settled` (wins + losses + pushes in the view) and `ranked` (`settled >= 10`) ride on every summary. A model that
  is not ranked sits in the page's collapsed "Warming up (N)" group with its record so far; sorting never lifts it.
- The saved copy (`hounds_public_cache.json`, version 2) holds `views[season]` with a leaderboard and a series per
  season and all-time; a cold start answers the season asked for. Moving a date in `seasons.json` rebuilds the book.
- The digest names hottest and coldest only among ranked models when any are ranked.

Shapes are in `src/hounds/contract.py` (dataclasses + `to_json`). Every payload
has `paper_only: true`, `not_advice`, `as_of` (the newest decision day in the
data, never the wall clock) and, for list routes, a `basis` paragraph.

`series` is one point per day the hound had graded bets, starting at 0 the day
before its first bet: `{date, cum_units_average_price, cum_units_recorded_price,
bets_settled, cum_clv_mean_pts}` (`cum_clv_mean_pts` is null below 20 measurable
bets; `cum_units_average_price` is null when the average price is unavailable).

## How it is computed, and what it costs

`src/hounds/stats.py:get_book()` builds everything once and caches it on the
size and mtime of every input (decisions + archive, wagers, the 56 account
ledgers, the odds store + archive, both configs, the pack/user ledgers, the card
ledger). A request costs a few `stat` calls. The cold build streams the odds
store once (~1,000,000 rows, ~5 s) keeping only the few boards it needs
(`src/hounds/boards.py`); python-side peak is under ~100 MB. Call
`stats.warm()` at process start so the first visitor does not pay for it.

Nothing writes to any ledger. The sealed 2026-01-01..2026-08-27 outcomes are
never read (`ledgers.FIRST_OPEN_DAY`).

## Ledger row shape for pack and user hounds

`src/hounds/ledgers.py:pack_ledger_rows` reads hash-chained JSONL rows:

* a **definition** row: `{"kind": "hound", "hound_id", "name", "tagline",
  "category", "style", "rule_text", "sports", "markets", "owner_display"?,
  "retired_by_owner"?}` (a pack hound may instead be defined in
  `config/house_pack.json`);
* a **bet** row: `hound_id, date, game_id | event_id, sport, market
  (h2h|spreads|totals or moneyline/run_line/total), selection (or side
  home|away|over|under), line, price_average, price_best (the price taken),
  book, book_count, lock_utc, start_utc, reason, who_decided
  (code|model|rule), segment (forward|replay), bet_id?`;
* a **graded** row: the same `bet_id` (or the same hound + event + market +
  selection + line + segment) with `result` (win|loss|push|void) and `units`.
  One row may carry both.

CLV, verification and the average price come from the odds store by `event_id`
(the same ids the odds store uses), so a pack bet that wants a closing-line
verdict must carry the store's `event_id` and a `lock_utc` before `start_utc`.

## How the hounds learn

A hound is never edited. A coach may propose a **challenger**; it runs in shadow beside the champion on the
same games at the same prices; and only the referee, by a pre-set sequential test on the paired
closing-line value controlled for false discoveries across all challengers, can promote it, as the next
**version**. The old version keeps its own record (`<id>@v<n>` in the graveyard). The loop also computes
whether it is improving anything and pauses itself when it cannot show it. The rules, with every number, are
`docs/PREREG_LEARNING_LOOP.md` (committed before the code); the operator's guide is `docs/HOUNDS_LEARNING.md`;
the pages are `web/learning.html` and the "Versions and challengers" section of `web/hound.html`.

## How to add a hound

* **From an engine system:** add an entry to `config/house_hounds.json` with
  `system_id` (the id in `data/paper_accounts/`), `name`, `tagline`, `kind`,
  `category`, `style`, `rule_text`. If it is an evolab genome, generate the text
  with `house.genome_rule_text` and let the test pin it. The rule text must
  describe what the code actually does.
* **From the pack:** define it in `config/house_pack.json` and write its bets to
  `evidence/hounds_house_v1.jsonl`.
* **A user hound:** the engine (`src/hounds/user_runner.py`, in the API process) writes
  `hounds_user_v1.jsonl` beside the app database; `api/hounds_create.py` writes only the hound's definition,
  to the app database. docs/HOUNDS_INTEGRATION.md has the whole picture.

No hound may claim an edge. The copy tests reject guarantee/profit language.
