# UFC data layer: the contract

Every module in `src/datasvc/ufc/` reads and writes the shapes below. They are
fixed: a module that needs a new field adds it (never renames or repurposes one)
and says so in its report. Written 2026-10-03 from real ESPN responses saved in
`tests/fixtures/espn_mma/` and one UFC.com page in `tests/fixtures/ufccom/`.

## Sources

| What | Where | Notes |
|---|---|---|
| Events of a year | `espn_urls.season_events(year)` | List of event `$ref`s. 52 items for 2026, 2016 also present. |
| One event and all its bouts | `espn_urls.event(event_id)` | Competitions embedded with `cardSegment`, `matchNumber`, `type` (weight class), `format.regulation.periods`, `description` ("3 Rnd (5-5-5)"), competitors (`id`, `order`, `winner`). The bout's status is a `$ref`. |
| A bout's status and result | `espn_urls.competition_status(e, c)` | `type.name` (STATUS_FINAL ...), `period`, `clock` (seconds into the round), `result.name` ("submission", "kotko" seen; others to be sampled), `result.displayName`, `result.description` ("Guillotine Choke", "Punch"), `result.target.name`. |
| A fighter's totals in one bout | `espn_urls.competitor_statistics(e, c, athlete_id)` | 43 statistics on 2026 bouts, 42 on a 2016 bout (see list below). |
| Odds for a bout | `espn_urls.competition_odds(e, c)` | DraftKings (provider id 100). `awayAthleteOdds` / `homeAthleteOdds` with `moneyLine`, and `open` / `close` / `current` blocks holding moneyline, spread and `victoryMethod` (koTkoDq, submission, points). `overUnder` (rounds), over/under prices. Present on completed bouts and on tonight's card; an empty list on the 2016 bout. |
| A fighter | `espn_urls.athlete(id)`, `athlete_records(id)`, `athlete_eventlog(id)` | Height and reach in inches, weight, date of birth, stance, weight class, nickname, citizenship, active; overall record; full fight history as `$ref`s. Competitor id equals athlete id. |
| Career rates | `espn_urls.ufccom_athlete(slug)` | UFC.com athlete page, plain HTML: striking accuracy, significant strikes, takedowns, reach, wins by method. |

Fetch every URL through one `src.datasvc.http.PoliteFetcher` (cache, spacing,
request cap, browser-check stop). No other HTTP code in `src/datasvc/`.

## Files (`data/datasvc/ufc/`, tracked) and the raw cache (`data/datasvc/raw/`, not tracked)

Names, keys and the date field for "newest" are in `src/datasvc/ufc/store.py`
(`FILES`, `KEYS`, `DATE_FIELDS`). Save through `UfcStore.upsert(name, records)`.
Every record carries `source_url` (the URL it came from) and `fetched_utc`.
Dates are ISO strings in UTC as ESPN gives them ("2026-09-27T00:00Z").
Ids are strings.

### events.jsonl (key `event_id`)

| Field | Type | From |
|---|---|---|
| event_id | str | event `id` |
| name, short_name | str | `name`, `shortName` |
| date_utc | str | `date` |
| season | int or null | `season` (resolve the `$ref` id or year) |
| status | str | one of scheduled, in_progress, final, canceled, postponed, unknown |
| venue_id | str or null | `id_from_ref(venues[0], "venue")` |
| bout_ids | list of str | competitions sorted by `matchNumber` ascending (1 is the main event) |

### bouts.jsonl (key `bout_id`)

| Field | Type | From |
|---|---|---|
| bout_id | str | competition `id` |
| event_id | str | the event |
| date_utc | str | competition `date` |
| match_number | int or null | `matchNumber` (1 = main event) |
| card_segment | str or null | `cardSegment.name` mapped: main -> main, prelims1 -> prelims, prelims2 -> early_prelims, anything else kept lower case |
| card_segment_raw | str or null | `cardSegment.name` |
| weight_class | str or null | `type.text` ("Light Heavyweight", "Women's Strawweight") |
| scheduled_rounds | int or null | `format.regulation.periods` |
| description | str or null | `description` ("5 Rnd (5-5-5-5-5)") |
| status | str | same values as events |
| fighter_a_id, fighter_b_id | str | competitor with `order` 1 is a, `order` 2 is b |
| winner_id | str or null | competitor with `winner: true` once final; null for a draw, no contest or unfinished bout |
| result_method | str or null | KO_TKO, SUB, DEC_UNANIMOUS, DEC_SPLIT, DEC_MAJORITY, DECISION, DQ, NC, DRAW, OTHER |
| result_method_raw | str or null | `result.name` |
| result_detail | str or null | `result.description` |
| result_target | str or null | `result.target.name` |
| end_round | int or null | status `period` when final |
| end_time_s | float or null | status `clock` when final |
| fight_time_s | float or null | (end_round - 1) x 300 + end_time_s, when both are known |
| status_url | str or null | the status URL |

### fighters.jsonl (key `fighter_id`)

| Field | Type | From |
|---|---|---|
| fighter_id | str | athlete `id` |
| name, first_name, last_name, nickname | str or null | `displayName`, `firstName`, `lastName`, `nickname` |
| dob | str or null | `dateOfBirth`, date part |
| height_in, reach_in, weight_lb | float or null | `height`, `reach`, `weight` |
| stance | str or null | `stance.text` |
| weight_class | str or null | `weightClass.text` |
| citizenship | str or null | `citizenship` |
| active | bool or null | `active` |
| record | object or null | {"wins", "losses", "draws"} from the overall record |
| espn_slug | str or null | `slug` |
| aliases | list of str | `names.normalise` of every name the fighter goes by |

### fight_stats.jsonl (key `bout_id`, `fighter_id`)

One row per fighter per bout: `bout_id`, `fighter_id`, `opponent_id`, `event_id`,
`date_utc`, then every ESPN statistic as a number in snake case, null when absent,
and `stats_complete` (bool). The ESPN names seen on 2026 bouts:

knockDowns, totalStrikesAttempted, totalStrikesLanded, sigStrikesAttempted,
sigStrikesLanded, sigDistanceHeadStrikesAttempted, sigDistanceHeadStrikesLanded,
sigDistanceBodyStrikesAttempted, sigDistanceBodyStrikesLanded,
sigDistanceLegStrikesAttempted, sigDistanceLegStrikesLanded,
sigClinchBodyStrikesAttempted, sigClinchBodyStrikesLanded,
sigClinchHeadStrikesAttempted, sigClinchHeadStrikesLanded,
sigClinchLegStrikesAttempted, sigClinchLegStrikesLanded,
sigGroundHeadStrikesAttempted, sigGroundHeadStrikesLanded,
sigGroundBodyStrikesAttempted, sigGroundBodyStrikesLanded,
sigGroundLegStrikesAttempted, sigGroundLegStrikesLanded, takedownsAttempted,
takedownsLanded, takedownsSlams, takedownAccuracy, targetBreakdownHead,
targetBreakdownBody, targetBreakdownLeg, posBreakdownDistance, posBreakdownClinch,
posBreakdownGround, advances, advanceToHalfGuard, advanceToSide, advanceToMount,
advanceToBack, reversals, submissions, slamRate, timeInControl, wallclock.

The field map and the unit of each (counts, a 0..1 accuracy, seconds of control)
are decided and documented by the module that parses them (`fightstats.py`); the
meaning of the target and position breakdowns must be checked against the strike
counts before it is relied on.

### odds.jsonl (key `bout_id`, `provider_id`)

`bout_id`, `event_id`, `provider_id`, `provider`, the moneyline per fighter as
American prices `a_ml_open`, `a_ml_close`, `a_ml_current`, `b_ml_open`,
`b_ml_close`, `b_ml_current`, `rounds_total`, `over_open`, `over_close`,
`over_current`, `under_open`, `under_close`, `under_current`, method of victory per
fighter where present (`method_odds`: {"a": {"ko_tko_dq", "submission",
"decision"}, "b": {...}} for open and close), `spread_raw` (kept raw until its
meaning is confirmed), `orientation` ("verified" or "unknown"), `is_closing`
(the bout was final when fetched, so current equals close).

ESPN labels the two sides home and away. Which of them is fighter a (order 1) must
be established from the data for every bout (for example the athlete reference
inside the odds, or the favourite's name in `details` against the competitors'
names), never assumed. When it cannot be established, leave the a/b fields null,
keep the raw home/away prices, and set `orientation` to "unknown".

### ufccom_profiles.jsonl (key `fighter_id`)

`fighter_id`, `ufc_slug`, and the career figures the page shows, as numbers:
significant strikes landed and absorbed per minute, striking accuracy and defence,
takedown average per 15 minutes, takedown accuracy and defence, submission average
per 15 minutes, knockdown average, average fight time in seconds, wins by knockout,
submission and decision, and the record text. Fields the page does not show are
null. The module documents which page elements each value comes from.

## Who owns what

| Module | Owner | Exposes |
|---|---|---|
| `http.py`, `store.py`, `names.py`, `ufc/espn_urls.py`, `ufc/store.py` | foundation (done) | see the code |
| `ufc/schedule.py` | schedule worker | `list_season_events(fetcher, year)`, `parse_event(event_json, *, fetched_utc, source_url)`, `parse_status(status_json)`, `crawl_event(fetcher, event_id)`, `crawl_season(fetcher, year, *, since=None, until=None)`, `crawl_upcoming(fetcher, today, *, days=21)` returning (events, bouts) |
| `ufc/fighters.py`, `ufc/ufccom.py` | fighters worker | `parse_athlete(athlete_json, records_json=None, *, fetched_utc, source_url)`, `fetch_fighter(fetcher, fighter_id)`, `fetch_fighters(fetcher, ids)`, `name_index(fighters)` for `names.match`; `slug_candidates(fighter)`, `parse_profile(html)`, `fetch_profile(fetcher, fighter)` |
| `ufc/fightstats.py`, `ufc/odds.py` | stats-and-odds worker | `parse_competitor_statistics(stats_json, *, bout, fighter_id, fetched_utc, source_url)`, `fetch_bout_stats(fetcher, bout)`; `parse_odds(odds_json, *, bout, fetched_utc, source_url, fighters=None)`, `fetch_bout_odds(fetcher, bout)` |
| `ufc/features.py`, `ufc/matchup.py`, `api/datasvc.py` | features-and-API worker | `features_as_of(store, fighter_id, as_of)`, `matchup(store, a_id, b_id, as_of=None)`, the `/data/v1` router |
| `ufc/pipeline.py`, CLI, the real backfill, `docs/DATA_SERVICE.md` | orchestrator, after the four above | `backfill(...)`, `update(...)` |

## Rules for every module

- No leakage: a feature computed "as of" a time uses only bouts that started
  strictly before it and have a result.
- Missing data is null and listed, never guessed or filled with an average.
- Parsers are pure functions over JSON or HTML; tests run them on the fixtures
  with no network. A test that needs a new kind of response saves it under
  `tests/fixtures/espn_mma/` (or `ufccom/`) with the worker's prefix
  (`w1_`, `w2_`, `w3_`, `w4_`) so files never collide.
- Live requests during development: at most 40 per worker, through
  `PoliteFetcher`, only to capture fixtures for cases the saved ones do not cover.
- stdlib only in `src/`. Route tests `skipUnless(HAS_FASTAPI)`.
- Never touch the LineHound card rules, ledgers or the fingerprinted files
  (`src/analysis/ufc_card.py`, `src/appstate/card_ledger.py`,
  `src/report/card_v2.py`, `src/analysis/best_bets_card.py`), and nothing under
  `.github/`.
