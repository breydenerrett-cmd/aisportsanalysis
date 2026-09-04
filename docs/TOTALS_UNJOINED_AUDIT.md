# Totals unjoined-events audit

`src/research/totals_rows.build_universe()` (2023+2024) originally reported
50 joint-denominator (floor-met, half-point closing) events with no
settlement join (`manifest["not_joined_event_ids"]`). This audits all 50,
identity/counts/date only -- no score field was read to produce this
document.

## Method

For each of the 50 event ids, the closing snapshot's `away_team`/`home_team`
(as the archive names them) and `commence_time` were compared against
`mlb_results.csv` two ways: (1) `pricepath`'s exact join (same-UTC-date then
previous-day, +/-3h, reused verbatim by `totals_rows._join_settlement`), and
(2) a widened search over every result for the same canonical team pair
within 72h, to see what *did* exist nearby.

## Classification

| class | meaning | count |
|---|---|---|
| (a) postponed / replayed elsewhere | the odds event's own listed commence_time was never played; the game was rained out and replayed on a different date (often as part of a doubleheader) under a different `game_pk` and a materially different start time (15h+ away) | 30 |
| (b) doubleheader collision | a real, same-calendar-date doubleheader nightcap whose actual start drifted past `pricepath`'s shared 3h cross-day disambiguation bound (3.27-5.77h observed) -- **fixed**, see below | 5 |
| (c) team-name mismatch | none found -- `pricepath._abbrev` (`team_abbrev_from_name` + `parks.canonical_team`, the same AZ->ARI normalization `backfill.run_first_five` documents) resolved both sides for 49/50 events | 0 |
| (d) results-store gap | `mlb_results.csv` is regular-season only (`game_type == "R"`); these are 2023/2024 Wild Card and Division Series games with no candidate anywhere in the store | 14 |
| (e) other | the 2023 All-Star Game (`National League @ American League`) -- an exhibition, never a club game, correctly absent from `mlb_results.csv` | 1 |

### By season

| season | (a) | (b) fixed | (d) | (e) | total |
|---|---|---|---|---|---|
| 2023 | 15 | 1 | 4 | 1 | 21 |
| 2024 | 15 | 4 | 10 | 0 | 29 |
| **total** | **30** | **5** | **14** | **1** | **50** |

## Full listing

| event_id (12 chars) | date | away @ home (archive names) | commence_time | class |
|---|---|---|---|---|
| 0bf3309e2b70 | 2023-04-16 | San Francisco Giants @ Detroit Tigers | 2023-04-16T17:40:00+00:00 | (a) postponed/replayed elsewhere |
| 7ac4d4762813 | 2023-04-18 | Cleveland Guardians @ Detroit Tigers | 2023-04-18T20:40:00+00:00 | (b) doubleheader collision -- FIXED |
| 466f5e785e70 | 2023-04-28 | Baltimore Orioles @ Detroit Tigers | 2023-04-28T22:40:00+00:00 | (a) postponed/replayed elsewhere |
| 85c4e285bb00 | 2023-06-02 | Tampa Bay Rays @ Boston Red Sox | 2023-06-02T23:10:00+00:00 | (a) postponed/replayed elsewhere |
| 7015048add70 | 2023-06-07 | Detroit Tigers @ Philadelphia Phillies | 2023-06-07T22:05:00+00:00 | (a) postponed/replayed elsewhere |
| c383f4789232 | 2023-06-13 | Atlanta Braves @ Detroit Tigers | 2023-06-13T23:40:00+00:00 | (a) postponed/replayed elsewhere |
| 820d750c16b8 | 2023-07-01 | New York Yankees @ St. Louis Cardinals | 2023-07-01T00:15:00+00:00 | (a) postponed/replayed elsewhere |
| 1e917abee855 | 2023-07-12 | National League @ American League | 2023-07-12T00:00:00+00:00 | (e) other (exhibition) |
| 2a701e6fae2b | 2023-07-15 | Washington Nationals @ St. Louis Cardinals | 2023-07-15T00:15:00+00:00 | (a) postponed/replayed elsewhere |
| 2824681ff93d | 2023-07-21 | New York Mets @ Boston Red Sox | 2023-07-21T23:10:00+00:00 | (a) postponed/replayed elsewhere |
| d7bfc4242d9b | 2023-07-26 | Los Angeles Angels @ Detroit Tigers | 2023-07-26T22:40:00+00:00 | (a) postponed/replayed elsewhere |
| 7bb736b77d13 | 2023-08-23 | Los Angeles Dodgers @ Cleveland Guardians | 2023-08-23T23:10:00+00:00 | (a) postponed/replayed elsewhere |
| 7ff64a7253fb | 2023-09-11 | New York Yankees @ Boston Red Sox | 2023-09-11T23:40:00+00:00 | (a) postponed/replayed elsewhere |
| 408a4f273086 | 2023-09-13 | New York Yankees @ Boston Red Sox | 2023-09-13T23:10:00+00:00 | (a) postponed/replayed elsewhere |
| c963b9af00e5 | 2023-09-26 | Miami Marlins @ New York Mets | 2023-09-26T23:45:00+00:00 | (a) postponed/replayed elsewhere |
| 7bda8cc176e4 | 2023-09-27 | Kansas City Royals @ Detroit Tigers | 2023-09-27T22:40:00+00:00 | (a) postponed/replayed elsewhere |
| 32b3944fd9b8 | 2023-09-28 | Miami Marlins @ New York Mets | 2023-09-28T23:10:00+00:00 | (a) postponed/replayed elsewhere |
| f3e9f2867b5d | 2023-10-03 | Texas Rangers @ Tampa Bay Rays | 2023-10-03T19:08:00+00:00 | (d) results-store gap (postseason) |
| be0b93120d3a | 2023-10-03 | Toronto Blue Jays @ Minnesota Twins | 2023-10-03T20:38:00+00:00 | (d) results-store gap (postseason) |
| 8f1a5d934549 | 2023-10-04 | Miami Marlins @ Philadelphia Phillies | 2023-10-04T00:08:00+00:00 | (d) results-store gap (postseason) |
| 5f0228661832 | 2023-10-04 | Arizona Diamondbacks @ Milwaukee Brewers | 2023-10-04T23:08:00+00:00 | (d) results-store gap (postseason) |
| 979a1e9d0770 | 2024-04-02 | Detroit Tigers @ New York Mets | 2024-04-02T23:10:00+00:00 | (a) postponed/replayed elsewhere |
| 28af46dbf92e | 2024-04-03 | Cincinnati Reds @ Philadelphia Phillies | 2024-04-03T23:30:00+00:00 | (b) doubleheader collision -- FIXED |
| 649ad82dac37 | 2024-04-29 | St. Louis Cardinals @ Detroit Tigers | 2024-04-29T22:40:00+00:00 | (a) postponed/replayed elsewhere |
| e87c5b818f6e | 2024-05-08 | New York Mets @ St. Louis Cardinals | 2024-05-08T17:56:00+00:00 | (a) postponed/replayed elsewhere |
| e75516c0e8e1 | 2024-05-25 | Chicago Cubs @ St. Louis Cardinals | 2024-05-25T02:00:00+00:00 | (a) postponed/replayed elsewhere |
| 136295e92bb9 | 2024-05-27 | Los Angeles Dodgers @ New York Mets | 2024-05-27T20:10:00+00:00 | (a) postponed/replayed elsewhere |
| 9cbf87bba0ce | 2024-06-05 | Kansas City Royals @ Cleveland Guardians | 2024-06-05T22:40:00+00:00 | (a) postponed/replayed elsewhere |
| 16816d9a7807 | 2024-06-25 | Atlanta Braves @ St. Louis Cardinals | 2024-06-25T23:45:00+00:00 | (a) postponed/replayed elsewhere |
| 9c8573b0b807 | 2024-06-26 | Toronto Blue Jays @ Boston Red Sox | 2024-06-26T23:10:00+00:00 | (a) postponed/replayed elsewhere |
| 5573cb710196 | 2024-07-10 | Minnesota Twins @ Chicago White Sox | 2024-07-10T21:31:00+00:00 | (b) doubleheader collision -- FIXED |
| f13302c94848 | 2024-07-20 | St. Louis Cardinals @ Atlanta Braves | 2024-07-20T02:00:00+00:00 | (a) postponed/replayed elsewhere |
| 7f3b1a8ad87f | 2024-07-23 | Cincinnati Reds @ Atlanta Braves | 2024-07-23T23:21:00+00:00 | (a) postponed/replayed elsewhere |
| 4b6c59ca424e | 2024-07-24 | Cincinnati Reds @ Atlanta Braves | 2024-07-24T22:06:00+00:00 | (b) doubleheader collision -- FIXED |
| 5500f2e8745a | 2024-07-29 | Toronto Blue Jays @ Baltimore Orioles | 2024-07-29T22:51:00+00:00 | (b) doubleheader collision -- FIXED |
| 59663773d5f2 | 2024-08-28 | Texas Rangers @ Chicago White Sox | 2024-08-28T00:10:00+00:00 | (a) postponed/replayed elsewhere |
| 2fd96e70eb57 | 2024-09-06 | Washington Nationals @ Pittsburgh Pirates | 2024-09-06T22:41:00+00:00 | (a) postponed/replayed elsewhere |
| 813a982760e7 | 2024-09-21 | Minnesota Twins @ Boston Red Sox | 2024-09-21T20:11:00+00:00 | (a) postponed/replayed elsewhere |
| 6acdd27db6bb | 2024-09-29 | Houston Astros @ Cleveland Guardians | 2024-09-29T19:11:00+00:00 | (a) postponed/replayed elsewhere |
| bd5db14c1b7b | 2024-10-01 | Detroit Tigers @ Houston Astros | 2024-10-01T18:32:00+00:00 | (d) results-store gap (postseason) |
| b86f8004e8cd | 2024-10-01 | Kansas City Royals @ Baltimore Orioles | 2024-10-01T20:08:00+00:00 | (d) results-store gap (postseason) |
| 9ea64c9ecc7d | 2024-10-01 | New York Mets @ Milwaukee Brewers | 2024-10-01T21:32:00+00:00 | (a) postponed/replayed elsewhere |
| bef91969a8db | 2024-10-02 | Atlanta Braves @ San Diego Padres | 2024-10-02T00:39:00+00:00 | (d) results-store gap (postseason) |
| 98d592ce811a | 2024-10-02 | Detroit Tigers @ Houston Astros | 2024-10-02T18:33:00+00:00 | (d) results-store gap (postseason) |
| 5013b29a336f | 2024-10-02 | Kansas City Royals @ Baltimore Orioles | 2024-10-02T20:39:00+00:00 | (d) results-store gap (postseason) |
| e70aecb7479a | 2024-10-02 | New York Mets @ Milwaukee Brewers | 2024-10-02T23:39:00+00:00 | (d) results-store gap (postseason) |
| 1533823cdb69 | 2024-10-03 | Atlanta Braves @ San Diego Padres | 2024-10-03T00:38:00+00:00 | (d) results-store gap (postseason) |
| f2f71df91a9e | 2024-10-03 | New York Mets @ Milwaukee Brewers | 2024-10-03T23:08:00+00:00 | (d) results-store gap (postseason) |
| ae60872ca814 | 2024-10-05 | Kansas City Royals @ New York Yankees | 2024-10-05T22:39:00+00:00 | (d) results-store gap (postseason) |
| ee785b78fc4a | 2024-10-06 | San Diego Padres @ Los Angeles Dodgers | 2024-10-06T00:38:00+00:00 | (d) results-store gap (postseason) |
## The fix ((b), 5 events)

`totals_rows._join_settlement` reuses `pricepath`'s exact same-day/previous-day
join verbatim (never re-derived), per the module's own stated design. That
join's 3-hour gap bound (`pricepath.MAX_EVENT_GAP_SECONDS`, shared with
`src/model/selections.py`) exists to separate a doubleheader partner or the
next night's game (4h+ away) from the right game -- a deliberate,
already-validated convention this audit does not touch or widen globally.

The 5 audited (b) cases are real, played, same-calendar-date doubleheader
nightcaps whose actual first pitch (as later recorded in `mlb_results.csv`)
landed 3.27-5.77 hours after the odds archive's listed `commence_time` for
that event -- just past the 3h bound, not a different day's game. Every
genuine cross-day postponement/makeup case in the 50 sits at 15h+ (class a),
so an 8-hour, **same-calendar-date-only** fallback comfortably separates the
two populations without reaching into `pricepath`'s cross-day territory:

```python
DOUBLEHEADER_SAME_DAY_GAP_SECONDS = 8 * 3600

def _join_doubleheader_same_day(away, home, commence_time, index):
    candidates = index.get((away, home, commence_time.date().isoformat())) or []
    best, best_gap = None, None
    for game in candidates:
        gap = abs((game["start_time_utc"] - commence_time).total_seconds())
        if gap <= DOUBLEHEADER_SAME_DAY_GAP_SECONDS and (best_gap is None or gap < best_gap):
            best, best_gap = game, gap
    return best
```

`_join_settlement` only calls this fallback when `pricepath`'s own two-step
join has already returned `None` -- it can never override or shadow a
`pricepath` match, and `pricepath.py` itself, `f5_store.py`, and
`selections.py` are unmodified. Regression tests:
`tests/test_totals_rows.py::TestDoubleheaderSameDayFallback` (3 tests: the
audited Guardians/Tigers 2023-04-18 nightcap now joins; a same-day candidate
still stays unjoined if it lands only on an adjacent calendar date; a
same-day candidate beyond the 8h bound stays unjoined rather than being
guessed at).

### Result

Re-running `build_universe()` after the fix:

| | before | after |
|---|---|---|
| joint_total | 2579 | 2584 |
| joint_by_season (2023) | 1295 | 1296 |
| joint_by_season (2024) | 1284 | 1288 |
| not_joined_to_settlement | 50 | 45 |

The 5 newly-joined event ids are exactly the audited (b) set:
`7ac4d47628135f78c17860e4b5a3263c`, `28af46dbf92ef2f032efabb6f5649277`,
`5573cb7101964d15aef2ae3a9482bd57`, `4b6c59ca424e00a925e0d1335d1234f3`,
`5500f2e8745af8de76947959729b6f4b`.

Byte-identical re-run confirmed (`content_hash`/`price_payload_hash` stable
across repeated calls on the same inputs).

## (a) and (d): no join-logic fix -- exclusion ledger already records them

**(a) postponed/replayed elsewhere (30 events):** each of these odds events
genuinely was never played at its own listed `commence_time` -- there is no
settlement to join to for that scheduled game, only for a different,
later-dated makeup game with its own `game_pk`. This is not a join bug; it
is `not_joined_to_settlement`'s intended behavior. The manifest already
records every one of these 30 ids in `not_joined_event_ids`, which is the
exclusion ledger this task asked to confirm -- no separate ledger exists or
is needed, and `write_manifest`/`read_manifest` round-trip it unchanged.

**(d) results-store gap (14 events):** `mlb_results.csv` contains only
`game_type == "R"` (regular season) rows; these 14 are all 2023/2024
Wild Card and Division Series games (dates 2023-10-03/04 and
2024-10-01..10-06). This is a data-coverage gap, not a join-logic bug --
`totals_rows.py`'s join cannot manufacture a settlement row that does not
exist in the results store. Fixing it would mean backfilling postseason
games into `mlb_results.csv`, which is out of this mission's scope
(data-collection backfill, not join logic) and is not attempted here.
