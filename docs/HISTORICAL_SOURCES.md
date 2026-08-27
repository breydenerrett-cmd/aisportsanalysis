# Historical data sources — audit and recommendation

Answers the Phase 3 decision gate: can this project run a real backtest, and
what does it cost?

**Short answer: yes, for a one-time $59.** Not a subscription — one month of a
paid plan, pull the history, cancel. Daily operation afterwards fits the free
tier.

---

## The three things a backtest needs

| Input | Source | Cost | Status |
|---|---|---|---|
| Final results | MLB Stats API | Free | **Solved and verified** |
| Point-in-time features | MLB Stats API | Free | Needs reconstruction work |
| Closing odds | The Odds API historical | Paid | **Decision gate** |

---

## 1. Final results — solved

The MLB Stats API serves completed games on the same endpoint as today's
schedule, going back decades. No key, no rate limit encountered in practice.

Measured live against `2025-07-01 .. 2025-07-07`:

```
96 final games in 3.4 seconds  (27.9 games/sec)
```

Extrapolated: a full 186-day season is roughly **2 minutes**. Three seasons is
about **6 minutes**.

This is the single most important finding in the audit. Earlier work on this
project was polling for one day's 13 games to settle, which would take a full
season to build a usable sample. The same data is already available in bulk.

Implemented in `src/providers/mlb.py::backfill_results`. Run it with:

```
python -m src.cli backfill 2024-04-01 2024-09-30 --verbose
```

## 2. Point-in-time features — free, but real work

Stats are free, but "what was this pitcher's ERA on 12 June" is not the same
question as "what was his ERA that season." Pulling season-final stats and
attaching them to a June game leaks the future into the past.

A model trained on leaked data backtests beautifully and loses money live. This
is the most common way a betting model fails, and it fails silently.

Two approaches, in order of preference:

1. **Date-bounded queries.** Some MLB Stats API stat endpoints accept a date
   range. Where they do, this is exact and cheap.
2. **Replay from game logs.** Where they do not, pull each player's game log and
   accumulate forward, computing the stat as of the morning of each game date.
   More work, but exact.

Never acceptable: pulling current season stats and attaching them to past
games. If a stat cannot be reconstructed point-in-time, it does not go in the
historical table at all.

**Status: not yet built.** This is the largest remaining piece of Phase 3.

## 3. Closing odds — the decision gate

There is no free source of historical sportsbook odds with reliable coverage.
This is the one place the project has to either spend money or accept a
materially weaker validation path.

### The Odds API historical endpoints

Verified against the provider's own documentation and pricing:

- Coverage begins **2020-06-06**. Nothing before that exists at any price.
- Snapshots at 10-minute intervals; 5-minute from September 2022.
- Historical endpoints cost **10 credits per region per market**, versus 1 for
  live. A 10x multiplier.
- Historical endpoints require a **paid plan**. The free tier cannot reach them.

### Pricing

| Plan | Monthly | Credits |
|---|---:|---:|
| Starter (free) | $0 | 500 |
| 20K | $30 | 20,000 |
| 100K | $59 | 100,000 |
| 5M | $119 | 5,000,000 |
| 15M | $249 | 15,000,000 |

### What a backfill actually costs

One snapshot call returns every game live at that timestamp, so cost scales
with **snapshots, not games**. MLB first pitches span roughly 1pm–10pm ET, so
10 snapshots/day catches every game near its own close.

Computed by `src/providers/odds.py::estimate_backfill_credits`:

| Scope | Credits | Cheapest plan | One-time cost |
|---|---:|---|---:|
| Moneyline, 1 season | 18,600 | 20K | **$30** |
| Moneyline, 3 seasons | 55,800 | 100K | **$59** |
| All 3 markets, 1 season | 55,800 | 100K | **$59** |
| All 3 markets, 3 seasons | 167,400 | 5M | **$119** |

### Recommendation

**Buy one month of the 100K plan ($59), pull three seasons of moneyline closing
lines, then cancel.**

Reasoning:

- Three seasons of moneyline is roughly 7,000 graded games — enough to fit and
  validate a calibrated probability model, which is the actual blocker.
- Moneyline first because it is the only market the model currently targets.
  Run lines and totals need their own models anyway (Phase 5).
- It is a one-time cost, not a recurring one. The history does not change.
- $119 for all three markets across three seasons is also defensible if you
  want to build all four charter outputs at once. Both are cheap relative to
  the alternative, which is spending a season discovering the model does not
  work.

### If you decide not to spend anything

The project is not dead, but validation changes shape:

- **No historical backtest.** You cannot bet into prices that no longer exist.
- **Forward CLV tracking becomes the only evidence.** Capture closing lines
  live from today onward (free tier, see below) and measure whether picks beat
  the close.
- **Timeline stretches from a weekend to a full season**, because you can only
  accumulate at the rate games are played.

This is a legitimate path. It is just slower, and it delays finding out whether
the model works at all.

---

## Live operation — fits the free tier

Line movement cannot be backfilled from free sources, so snapshot capture must
start now and run continuously. The constraint is that naive polling is
expensive.

Computed by `src/providers/odds.py::recommend_live_schedule`:

| Snapshots/day | Credits/month | Fits free tier |
|---:|---:|---|
| 2 | 180 | Yes (320 headroom) |
| 4 | 360 | **Yes (140 headroom)** |
| 8 | 720 | No |
| 96 (every 15 min) | 8,640 | No — by 17x |

**Use 4 snapshots per day across all three markets.** Space them to catch
opening, two intermediate points, and as close to first pitch as scheduling
allows. That fits inside the free tier with room to spare.

A 15-minute polling schedule — the obvious naive choice — exhausts the free
tier in under two days. Check `python -m src.cli credits` before scheduling
anything.

---

## Sources

- [The Odds API v4 guide — historical endpoints](https://the-odds-api.com/liveapi/guides/v4/#get-historical-odds)
- [The Odds API pricing](https://the-odds-api.com/#get-access)
- [MLB Stats API](https://statsapi.mlb.com/api/v1/) — verified live during this audit
