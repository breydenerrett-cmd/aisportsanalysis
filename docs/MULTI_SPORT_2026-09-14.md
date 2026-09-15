# Multi-sport LINEHOUND: NFL, tennis and live betting (week of 2026-09-14)

Owner request, 2026-09-14 (evening): add NFL and tennis "immediately as the
seasons are started" and build "polished versions of systems for pre bet and
live betting including baseball as well" through the week. Owner decisions
taken during planning: live in-play odds capped at **300 credits a day,
event-driven**; the owner **buys a tennis results feed** (until it is
connected, tennis is research only); **all tracks in parallel**; alerts are
**in-app only** (Twilio and Resend both prohibit gambling content).

This document is the architecture record for that work. The plan of record
lives in the session plan; this file says what was built, what is
experimental, and what the owner still has to decide.

**No edge is claimed for NFL, tennis or live betting.** Every new selection
rule is a pre-registered experimental forward test
(`docs/PREREG_MULTI_SPORT_2026-09-14.md`) with a floor in the hundreds of
settled units before its single read. MLB pre-game behaviour is unchanged.

## 1. Architecture decisions

1. **`sport` is a parameter everywhere, default `"mlb"`.** Existing callers
   and tests keep working without edits. `src/sports/` is the registry:
   `spec(key)` returns a `SportSpec` (odds API key, card ledger path, lock
   lead, featured markets, game id field, customer wording for the start,
   experimental flag, schedule and team-name adapters). Keys: `mlb`, `nfl`,
   `tennis`.
2. **Pre-game odds rows for other sports live in the existing stores** with a
   `sport` field; **MLB rows are byte-identical to before** (no field). Every
   reader defaults to MLB and treats a missing field as MLB, so NFL rows can
   never leak into an MLB board.
3. **One card ledger file per sport.** MLB keeps `evidence/cards_v1.jsonl`
   untouched; NFL uses `evidence/cards_nfl_v1.jsonl`; tennis has a path
   reserved and nothing is ever written to it this week. Records are never
   pooled across sports.
4. **Live data has its own stores and its own ledger.** Game state:
   `data/live/<sport>/<date>.jsonl` (append-only, one row per observation,
   `observed_utc` and `state_id` on every row). In-play prices:
   `data/live/odds_inplay.jsonl`, tagged `in_play` with the state observation
   that triggered them. Live research candidates:
   `evidence/live_candidates_v1.jsonl`, hash-chained, separate from the card
   ledger, never shown on the card record.
5. **Live prices are fetched only when a game's state changes** (score,
   inning, half, pitching change; NFL score), under a new budget band
   `live_odds` capped at 300 credits a day across all sports, behind the
   `LIVE_ODDS` kill switch (a repository variable; unset means off). MLB game
   state is free (statsapi). NFL game state costs 1 credit per poll on the
   scores endpoint and is polled only inside the broadcast windows.
6. **NFL identity is the nflverse `game_id`** (for example `2026_02_DET_BUF`);
   tennis identity is the odds event id plus player names; MLB stays on
   `game_pk`. Odds-event-to-game maps carry `sport` and `game_id` for
   non-MLB rows.
7. **Data licences.** nflverse (schedules, injuries, team-week stats) is
   CC BY 4.0 and is attributed in code and in the app. Sackmann tennis data
   is CC BY-NC-SA and is **not used**. No free, licensable tennis results feed
   exists; the options for the owner are in
   `docs/TENNIS_RESULTS_FEED_OPTIONS.md`.

## 2. What is built (committed 2026-09-15, 03:22Z)

| Area | Modules | Status |
|---|---|---|
| Sport registry, calendar, NFL team map | `src/sports/` | done |
| Odds provider sport keys, scores and sports endpoints | `src/providers/odds.py` | done |
| Snapshot stores tag non-MLB rows; readers default to MLB | `src/pipeline/snapshots.py`, `src/analysis/prices.py` | done |
| Game identity per sport | `src/board/gamekey.py` | done |
| Card ledger per sport, picks keyed by `game_id` | `src/appstate/card_ledger.py` | done |
| Budget band `live_odds`, kill switch, probe store injection | `src/capture/budget.py`, `config/capture_families.json` | done |
| Four pre-registered hypotheses | `data/research/alpha_registry.jsonl`, `docs/PREREG_MULTI_SPORT_2026-09-14.md` | done |
| NFL provider (nflverse CSVs), v0 strength model, knowledge grade, capture cadence | `src/providers/nfl.py`, `src/analysis/nfl_strength.py`, `src/analysis/nfl_grade.py`, `src/pipeline/nfl_capture.py` | done |
| MLB and NFL live state pollers, in-play odds triggers, live ledger, three live rules | `src/pipeline/livefeed_mlb.py`, `livefeed_nfl.py`, `live_odds.py`, `src/appstate/live_ledger.py`, `src/analysis/live_rules.py` | done |
| Tennis discovery, bounded h2h capture, results-feed adapter | `src/pipeline/tennis_discovery.py`, `tennis_capture.py`, `src/providers/tennis_results.py` | done |
| NFL card rule, slate, publish and settle, CLI | `src/analysis/nfl_card.py`, `src/pipeline/nfl_slate.py`, `src/report/nfl_card.py`, `src/cli.py` | in progress |
| API `sport` parameter, live API, tennis API, live record | `api/card.py`, `api/games.py`, `api/live.py`, `api/tennis.py`, `api/performance.py` | in progress |
| Web: sport switcher, NFL card and record, Live page, tennis board | `web/js/sport.js`, `card.js`, `cardrecord.js`, `live.js`, `tennis.js` | in progress |
| Chain scheduling, live runner workflow | `scripts/capture_slot.sh`, `scripts/daily_loop.sh`, `scripts/live_window.sh`, `.github/workflows/live-window.yml` | in progress |

## 3. Selection rules (all experimental)

- **NFL_CARD_V1.** The moneyline side the de-vigged multibook consensus
  favours (at least six books), ranked by that consensus, with the v0 model
  (nflverse EPA per play, home field 1.5 points, margin standard deviation
  13.5 as a documented constant, not a fit) confirming or marking the pick
  SPLIT. Labels read the market's number: STRONG at 0.62 and above, LEAN at
  0.55, SLIGHT below. At most five picks, **no minimum** (owner decision
  pending; the MLB "at least three" rule is MLB's). The spread is shown as
  the alternative and is not graded. Locks four hours before its own
  kickoff, exactly like an MLB pick.
- **LIVE_V0 rules** (research candidates, never picks): favourite trailing by
  one or two runs after three innings; favourite's starter pulled before
  four innings while ahead or level; NFL favourite trailing by one to seven
  points at halftime, where halftime is proxied by 80 to 100 minutes after
  kickoff because the scores feed has no clock. Each is logged once per
  game at the median in-play price across books and settled from the final
  score.

## 4. Credits

| Use | Estimate | Guard |
|---|---|---|
| MLB pre-game | unchanged, 120 to 580 a day | existing envelope (900) |
| NFL featured board | 3 credits per capture, five captures per kickoff cluster, roughly 15 a game day | `can_spend("featured", 3)` |
| NFL scores (settlement and Sunday state at five minutes) | about 130 on a Sunday, about 10 otherwise | family `scores` (measured on first probe) |
| Tennis h2h | 1 credit per active tournament per phase, at most six tournaments a day | family `tennis_h2h` (measured on first probe) |
| In-play odds, all sports | hard cap 300 a day | band `live_odds`, `LIVE_ODDS` switch |

The two new families are recorded as unmeasured until a real one-credit
probe records their cost (`python -m src.cli budget --probe scores` and
`--probe tennis_h2h` on the runner). Until then their guards refuse, which is
intended: nothing new spends a credit before its cost is measured.

## 5. Customer-facing truth

- NFL pages carry "Experimental selections. Performance is still being
  evaluated." on every surface.
- Tennis pages carry "Research only. No tennis picks until results grading is
  connected." and show the market's likelier side only.
- The Live page carries "Live analysis is in internal testing. No alerts are
  sent." and labels every candidate "research, not a pick". It is reachable
  by link, not from the main navigation.
- No page names a model, a consensus, an edge or a probability the product
  cannot stand behind.

## 6. Proposed doctrine amendment (NOT applied; owner approves doctrine edits)

`docs/PRODUCT_DOCTRINE.md` states the product thesis in MLB terms. Proposed
addition, for the owner to accept, edit or reject:

> **Other sports.** The product's published picks are MLB picks. NFL and
> tennis are carried as experimental surfaces: NFL picks are published and
> graded under their own pre-registered rule and their own ledger, labelled
> experimental on every page, and never pooled with the MLB record; tennis
> is a research board until a licensed results feed grades it. Live in-play
> analysis is research until its pre-registered rules have been read at
> their floors. None of this changes the MLB thesis, the market benchmark,
> or the record policy.

## 7. Open owner decisions (work proceeds on the stated defaults)

1. NFL pick floor: default none (max five). Say if "at least three" should
   apply.
2. Doctrine amendment above: accept, edit or reject.
3. Live runner host: default a GitHub Actions job dispatched by the capture
   chain; say if a paid always-on process is preferred.
4. Odds API plan tier and reset date: please confirm (21,823 credits
   remaining on 2026-09-14; cycle reset date unknown to the repo).
5. Tennis results feed: `docs/TENNIS_RESULTS_FEED_OPTIONS.md` recommends
   Goalserve ($150 a month, betting use allowed in writing) with
   api-tennis.com ($40 a month) as the fallback pending two written answers.

## 8. Not delivered this week, by design

A validated edge in any new sport; tennis picks or tennis live state;
external alerts (no eligible provider); NFL player props; changes to the MLB
selection logic, ledger or record; the parked design review and Direction A
build; production deployment.
