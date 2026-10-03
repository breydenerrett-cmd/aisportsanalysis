# UFC features, the matchup fact sheet and the `/data/v1` API

Three things read the records fixed in [`UFC_SCHEMA.md`](UFC_SCHEMA.md) and serve them:

| What | Where | One line |
|---|---|---|
| Fighter features | `src/datasvc/ufc/features.py` | `features_as_of(store, fighter_id, as_of)`: what a fighter had done as of a moment, leakage-free |
| Matchup fact sheet | `src/datasvc/ufc/matchup.py` | `matchup(store, a_id, b_id, as_of=None)`: two fighters side by side with the booked bout and its odds |
| HTTP API | `api/datasvc.py` | `GET /data/v1/...`, signed-in, one error shape, cursor pagination |

All three are facts only. No prediction, no pick, no edge. The examples below were
produced by running the code on the synthetic world the tests use (fighters "Alex Archer"
and "Ben Brawler", ids 101 and 102), not on real data; the real ingestion fills the same
shapes.

## 1. The leakage rule

> `features_as_of` uses only bouts that **started strictly before `as_of`** and **have a result**.

- `as_of` is an ISO date or datetime. A bare date is the **start of that day, 00:00 UTC**, so
  a bout on that date has not happened yet as of it. A bout starting at exactly the `as_of`
  instant does not count. Every later bout never counts.
- A bout's start is its `date_utc`. A bout with no readable `date_utc` is **excluded** (it
  cannot be placed before `as_of`, so it is never assumed to be in the past) and is listed in
  `sample.skipped.no_start_time`.
- "Has a result": a `winner_id` that is one of the two fighters (a win or a loss), or no
  winner and `result_method` `DRAW` or `NC`. A bout that started before `as_of` with no
  result (cancelled, postponed, or a result not recorded yet) is left out and listed in
  `sample.skipped.started_without_result` with its status, so a reader can see that the
  fighter's latest bout is missing rather than assume it never happened. A winner on a bout
  the contract calls a draw or no contest, or a winner who is neither fighter, is
  contradictory data and is left out the same way.
- **One gate.** `features.completed_fights` (and `_scan` under it) is the only place a bout is
  admitted. The matchup's shared opponents and previous meetings go through it too, and so
  does the strength-of-schedule figure below.
- **Strength of schedule is also as-of.** For each fight it looks at the opponent's record as
  of the **start of that fight** (strictly before it), not as of `as_of`. Using the opponent's
  record today would credit a fighter for how good an opponent later turned out to be.
- **Not as-of, and labelled so.** Two blocks are current values and are marked
  `"as_of_safe": false`: `career_record_incl_non_ufc` (the fighter record, which includes
  fights outside the UFC) and `ufccom_career` (UFC.com career numbers). Nothing in
  `figures`, the differentials or the style labels is computed from either; a test changes
  the UFC.com numbers and checks every figure, difference and label is unchanged.
- The odds in a matchup are prices as fetched (`fetched_utc`), not prices as of `as_of`.

How it is tested: the same features computed from the full store as of `t` must equal those
computed from a store with every bout at or after `t` deleted, for every fighter, at every bout
start, one second before it and a day after the last result; the same is checked for the whole
matchup sheet. Deliberately leaky variants of the gate (at-the-instant admitted, no date gate,
strength of schedule reading the opponent's whole record) each fail several tests.

## 2. Where the numbers come from

- Results, methods, fight time, weight class: `bouts` (`winner_id`, `result_method`,
  `fight_time_s`, `weight_class`, `date_utc`).
- Strikes, takedowns, knockdowns, control: `fight_stats`, one row per fighter per bout. A figure
  uses a row only when **the specific fields it needs** are numbers in it (a bool, a string or a
  negative is treated as absent). `stats_complete` is not consulted: a partial row simply
  contributes to the figures whose fields it has. Defence and "absorbed" figures read the
  **opponent's** row for the same bout (`stats_for[(bout_id, opponent_id)]`).
- Names are read as the contract's snake case (`sig_strikes_landed`, `knock_downs`,
  `takedowns_landed`, `time_in_control`, ...). The ESPN camel case and the squashed lower case
  (`knockdowns`) are also accepted, so a row that kept ESPN's spelling still reads.
- Units: counts are counts, `time_in_control` is **seconds**, `fight_time_s` is seconds.
- Physical attributes (`dob`, `height_in`, `reach_in`, `stance`): the fighter record as
  fetched. They are not versioned; they rarely change.

### The ESPN breakdown fields are accuracies, not shares

`posBreakdownDistance`, `posBreakdownClinch`, `posBreakdownGround` and `targetBreakdownHead`,
`...Body`, `...Leg` look like "share of strikes by position". Checked against the strike
counts of the 2026 fixture bouts they are **landed / attempted at that position or target**:
117 landed of 209 attempted at distance is 0.56, exactly the saved `posBreakdownDistance`; 9 of
13 in the clinch is 0.692; 90 of 180 head strikes is 0.5. The shares reported here are
therefore computed from the nine landed counts
(`sig{Distance,Clinch,Ground}{Head,Body,Leg}StrikesLanded`) and the breakdown fields are never read.

## 3. `features_as_of(store, fighter_id, as_of) -> dict`

Raises `ValueError` for an unreadable `as_of`, and `features.UnknownFighter` (a `LookupError`)
when the id is in neither the fighters file nor any bout. A fighter who is only in the bouts
still gets every bout-derived figure; the physical ones are missing with the reason.

### Shape

```
fighter_id, name, as_of (UTC, "2026-07-01T00:00:00Z"), leakage_rule
sample      fights, minutes, fights_with_own_stats, fights_with_opponent_stats, fights_with_both_stats,
            fights_without_any_stats [bout ids], skipped {no_start_time [ids], started_without_result [{bout_id, date_utc, status}]}
record      fights, wins, losses, draws, no_contests, wins_by_method, losses_by_method,
            first_fight_utc, last_fight_utc
figures     {figure name: figure}   (below)
streak      {type: win|loss|draw|no_contest|null, length}
last_three  newest first: {bout_id, date_utc, opponent_id, opponent_name, result, method, detail, round, time_s, weight_class}
physical    {stance, dob}
weight_classes  {current, fought [{weight_class, fights, first_utc, last_utc}], most_recent_change, fights_without_weight_class}
strength_of_schedule_by_fight  [{bout_id, date_utc, opponent_id, opponent_record_then, opponent_win_rate}]
career_record_incl_non_ufc     labelled block or null   (not as-of)
ufccom_career                  labelled block or null   (not as-of)
missing     [{figure, reason}]
```

`wins_by_method` / `losses_by_method` count `ko_tko`, `submission`, `decision` (unanimous, split,
majority or unspecified), `dq`, `other` and `unknown` (no method recorded).

### A figure, its sample and `missing`

Every entry of `figures` has `value` and `unit`. Statistical figures also carry their **own
sample**: `fights` (the fights that had every number the figure needs, which can be fewer than
the fighter's fights) and `minutes` (the fight minutes of those fights whose duration is
known), plus `num` and `den`, the sums the value is made of.

```json
"control_time_share": {"value": 0.2, "unit": "seconds in control / fight seconds",
                       "fights": 3, "minutes": 42.0, "num": 504, "den": 2520}
```

That is a 3-fight sample out of 5 fights: one fight's row had no control time and one fight had
no statistics at all. A figure that cannot be computed has `value: null`, a `reason`, and an
entry in the top-level `missing` list; nothing is filled with an average or a guess.
`ufc_fights: 0` is a value, not a gap, so a fighter with no fights yet lists every statistic as
missing with "no UFC fights in the store before as_of" and still reports height, reach and stance.

Rates are the **sum of the numerators over the sum of the minutes** (a five-round fight weighs
five rounds), never an average of per-fight rates. Values are rounded to 4 decimals (minutes to 2).

### Every figure

`own` is the fighter's `fight_stats` row, `opp` the opponent's row for the same bout. "Fights"
and "minutes" are as defined above.

| Figure | Formula | Needs |
|---|---|---|
| `ufc_fights` | number of fights admitted by the rule | bouts |
| `win_rate` | wins / (wins + losses + draws); a no contest is in neither | bouts |
| `finish_rate` | finishing wins / fights with a recorded method; no contests excluded; finishing = `KO_TKO` or `SUB` | `winner_id`, `result_method` |
| `been_finished_rate` | finishing losses / the same fights | same |
| `finish_share_of_wins` | finishing wins / wins with a recorded method | same |
| `finished_share_of_losses` | finishing losses / losses with a recorded method | same |
| `distance_rate` | (decisions + draws) / the `finish_rate` fights; went to the scorecards | same |
| `average_fight_time_s` | sum of `fight_time_s` / fights with a fight time | `fight_time_s` |
| `sig_strikes_landed_per_min` | sum own `sig_strikes_landed` / sum minutes | own, fight time |
| `sig_strikes_absorbed_per_min` | sum opp `sig_strikes_landed` / sum minutes | opp, fight time |
| `sig_strike_accuracy` | sum own landed / sum own `sig_strikes_attempted` | own |
| `sig_strike_defence` | 1 - sum opp landed / sum opp attempted | opp |
| `sig_strike_share_distance`, `_clinch`, `_ground` | sum own landed in that position / sum own landed in all nine cells | the nine landed counts |
| `sig_strike_share_head`, `_body`, `_leg` | sum own landed at that target / sum in all nine cells | same |
| `knockdowns_landed_per_15` | sum own `knock_downs` / sum minutes x 15 | own, fight time |
| `knockdowns_suffered_per_15` | sum opp `knock_downs` / sum minutes x 15 | opp, fight time |
| `takedowns_landed_per_15` | sum own `takedowns_landed` / sum minutes x 15 | own, fight time |
| `takedown_accuracy` | sum own landed / sum own `takedowns_attempted` | own |
| `takedown_defence` | 1 - sum opp landed / sum opp attempted | opp |
| `control_time_share` | sum own `time_in_control` / sum `fight_time_s` | own, fight time |
| `submission_attempts_per_15` | sum own `submissions` / sum minutes x 15 | own, fight time |
| `strength_of_schedule` | mean over fights of the opponent's win rate at the start of that fight | bouts |
| `days_since_last_fight` | whole days from the last admitted fight's start to `as_of` | bouts |
| `age_years` | (`as_of` date - `dob`) / 365.2425, 2 decimals | `dob` |
| `height_in`, `reach_in` | the fighter record | fighter record |

Notes:

- The nine landed counts are `sig_{distance,clinch,ground}_{head,body,leg}_strikes_landed`. A fight
  counts for the shares only when all nine are present, so the three position shares sum to 1 and
  so do the three target shares.
- `takedown_defence` and `sig_strike_defence` are undefined when the opponents attempted nothing
  across the sample ("opponents attempted no takedowns ..."): that is a missing figure, not 100%.
- `strength_of_schedule`: an opponent with no earlier fight in the store has no win rate. They are
  not scored as an average opponent; they are counted in `opponents_without_history`, and `fights`
  is the number of opponents that did have one. `strength_of_schedule_by_fight` shows each
  opponent's record at the time, so the figure can be audited.
- Every count is of fights **in the store**. They equal the fighter's UFC career only if the store
  covers it from his first UFC fight; `record.first_fight_utc` shows where the store starts for him.

### Streak, weight classes, the labelled blocks

- `streak`: the run of identical results ending at the latest fight. A draw or no contest is its
  own result, so it ends a win or loss streak (`{"type": "no_contest", "length": 1}`).
- `weight_classes.fought` lists each class with its fights and first and last dates (most recent
  first). `most_recent_change` is the latest fight whose class differs from the fight before it:
  `{"from", "to", "date_utc", "bout_id", "direction"}`. `direction` is `up` or `down` from the
  weight limits in `features.WEIGHT_LIMIT_LB`, and `unknown` for a class not in that table
  (catchweight, open weight). A bout with no `weight_class` is skipped and counted in
  `fights_without_weight_class`. The class comes from the bouts, never from the fighter record's
  current class, which would leak a later move.
- `career_record_incl_non_ufc`: `{label, includes_non_ufc: true, as_of_safe: false, note, wins, losses,
  draws, no_contests, fetched_utc}` from the fighter record.
- `ufccom_career`: `{label: "UFC.com career figures", as_of_safe: false, note, ufc_slug, source_url,
  fetched_utc, figures}`. `figures` is every field of the `ufccom_profiles` row except
  `fighter_id`, `ufc_slug`, `source_url` and `fetched_utc`, passed through under whatever names the
  UFC.com parser gave them.

## 4. Style labels

Simple descriptive labels over the figures (`matchup.style_descriptors`, also shown per fighter in
the matchup). They are round-number starting points chosen to sit clearly above or below an
ordinary roster fighter, **not fitted to outcomes**, and should be recalibrated against
percentiles of the store's own distribution once the full backfill exists.

A rule is an AND of conditions, tested against the figures as reported (already rounded), so the
evidence shown is exactly what was compared. `>=` holds on the line; `<` holds strictly under it.

Minimum samples (a condition on a figure whose sample is smaller is **not assessed**, never
"does not apply"):

- Timed figures (rates, accuracies, defences, shares, control): `MIN_FIGHTS_TIMED = 3` fights and
  `MIN_MINUTES_TIMED = 30` fight minutes in that figure's own sample.
- Shares of results (`finish_rate`, `been_finished_rate`, `distance_rate`): `MIN_FIGHTS_RESULTS = 5`
  fights with a recorded method, no minutes requirement.
- `hard_to_take_down` also needs 10 opponent takedown attempts behind the defence figure.

| Label | Rule | Meaning |
|---|---|---|
| `wrestler` | `takedowns_landed_per_15 >= 2` and `control_time_share >= 0.2` | lands takedowns often and spends real time in control |
| `submission_threat` | `submission_attempts_per_15 >= 1` | throws submission attempts often |
| `striker` | `sig_strike_share_distance >= 0.75` and `takedowns_landed_per_15 < 1` | lands most strikes at distance and rarely takes anyone down |
| `volume_striker` | `sig_strikes_landed_per_min >= 5` | high strike output |
| `knockout_threat` | `knockdowns_landed_per_15 >= 0.75` | scores knockdowns at a high rate |
| `finisher` | `finish_rate >= 0.6` | most fights end in his finishing win |
| `vulnerable_to_finish` | `been_finished_rate >= 0.3` | a large share of fights end in his finishing loss |
| `goes_the_distance` | `distance_rate >= 0.6` | most fights go to the scorecards |
| `hard_to_take_down` | `takedown_defence >= 0.8` | stops most takedown attempts (needs 10 opponent attempts) |

Per fighter the result is:

```json
{"applies": [{"name": "wrestler", "summary": "...", "rule": "takedowns_landed_per_15 >= 2 and control_time_share >= 0.2",
              "evidence": {"takedowns_landed_per_15": 2.9348, "control_time_share": 0.288},
              "sample": {"fights": 5, "minutes": 61.33}}],
 "does_not_apply": ["striker", "..."],
 "not_assessed": [{"name": "finisher", "reason": "finish_rate: needs 5 fights, has 4"}],
 "checked": ["wrestler", "..."]}
```

If every condition could be judged the rule applies or it does not. If some could not be judged but
one that could has already failed, the rule cannot hold and is `does_not_apply`; otherwise it is
`not_assessed` with the reasons. Every label is in exactly one of the three lists.

## 5. `matchup(store, a_id, b_id, as_of=None, *, now=None) -> dict`

`as_of` defaults to the **start of the scheduled bout** between the two when one exists,
otherwise to `now` (default: the current time; injectable for tests). An explicit `as_of` wins but
the bout and odds are still attached. Raises `ValueError` if a and b are the same fighter or `as_of`
is unreadable, and `features.UnknownFighter` for an unknown id.

The scheduled bout is a bout between exactly these two fighters whose status is `scheduled`. If there
are several it takes the earliest starting at or after `now`, else the latest before it (a bout whose
status was never refreshed); the rest are listed in `bout.other_scheduled_bout_ids`.

### Shape

```
a, b                {fighter_id, name}                                   a is whoever was passed first
as_of, as_of_source "argument" | "scheduled_bout_start" | "now"
leakage_rule, note
bout                null, or {bout_id, event_id, event_name, date_utc, weight_class, scheduled_rounds,
                    card_segment, match_number, description, status, other_scheduled_bout_ids}
odds                null, or the odds block (section 5.1)
features            {a: features_as_of(...), b: features_as_of(...)}      side by side, including the labelled blocks
differentials       {figure: {unit, a, b, diff, a_sample, b_sample, thin_sample}}   diff = a minus b
styles              {a: style result, b: style result}
shared_opponents    {a_opponents, b_opponents, count, items: [{opponent_id, opponent_name, a: [fight lines], b: [fight lines]}]}
previous_meetings   [fight line + winner_id, winner_name]                results from a's side, oldest first
physical            {a: {height_in, reach_in, reach_minus_height_in, age_years, stance}, b: {...},
                    differences: {height_in, reach_in, reach_minus_height_in, age_years}, stance_matchup, same_stance}
layoff              {measured_to, a_days, b_days, a_last_fight_utc, b_last_fight_utc, difference_days, longer_layoff}
missing             [{side: "a"|"b"|null, fighter_id, figure, reason}]
```

- **Differentials** (`a - b`, 4 decimals, null when either side is null) cover `ufc_fights`,
  `win_rate`, `finish_rate`, `been_finished_rate`, `distance_rate`, `average_fight_time_s`,
  `strength_of_schedule` and every timed figure (strikes, defence, knockdowns, takedowns, control,
  submissions). Height, reach, age and layoff have their own blocks. `thin_sample` is true when either
  side's sample is under the minimums of section 4 (3 fights and 30 minutes for timed figures, 5 fights
  for results) or a side has no value, so a one-fight rate cannot pass for a real one.
- **Shared opponents**: opponents both fought before `as_of`, with each side's fights against them
  (a rematch lists both, oldest first). `a_opponents` and `b_opponents` count each fighter's distinct
  opponents so an empty list can be read: no overlap between two real histories is a different
  statement from a fighter with no history.
- **Missing** is each side's own `missing` list tagged with the side, plus matchup-level gaps:
  `bout` ("no scheduled bout between these fighters in the store"), `odds` ("no odds row for the
  scheduled bout", or the withheld-prices note).

### 5.1 The odds block

Prices are American. For a market, `implied` is the price as a probability, margin included
(`100/(p+100)` for a plus price, `|p|/(|p|+100)` for a minus price). `margin` is the sum of the
implied probabilities minus 1 over **every outcome that can happen in that market** (two for a
moneyline or a rounds total, six for method of victory). `without_margin` divides each implied
probability by that sum. They are the **market's** numbers, not an estimate made here. Removing the
margin needs every price of the market: with one missing the others are still shown but `margin` and
`without_margin` are null. A price that cannot be American (zero, between -100 and +100, a string, a
bool) is treated as absent.

```
odds   {provider, provider_id, fetched_utc, is_closing, as_of_safe: false, orientation, other_providers: [{provider_id, provider}],
        moneyline:    {open, close, current}: each null or {a, b, implied: {a, b}, margin, without_margin: {a, b}}
        rounds_total: {line, open, close, current}: each null or {over, under, implied, margin, without_margin}
        method:       {open, close, current}: each null or {a: {ko_tko_dq, submission, decision}, b: {...},
                      implied, margin, without_margin}   one margin over all six outcomes
        note?}
```

- DraftKings (provider id `100`, the one ESPN carries) is the primary row; other providers are listed.
- The prices are as fetched (`fetched_utc`), not as of the sheet's `as_of`, so the block says
  `"as_of_safe": false` like the other blocks that are not as-of-date. With an explicit past `as_of` the odds
  are still today's.
- **Sides are mapped by fighter identity, never by position.** The odds row's `a` and `b` are the
  bout's fighters; this sheet's `a` and `b` are whoever the caller passed first. Asking for (102, 101)
  swaps the sides of every price.
- A row whose `orientation` is not `verified`, or a fighter pair that is not the bout's pair, is
  returned with the prices withheld (`moneyline`, `rounds_total`, `method` null) and a `note`, and the
  gap is added to `missing`. A price on the wrong fighter is worse than no price.
- `method_odds` nesting of open/close is not fixed by the contract, so the reader accepts
  `{snapshot: {side: {method: price}}}`, `{side: {snapshot: {method: price}}}` and
  `{side: {method: {snapshot: price}}}` (snapshots `open`, `close`, `current`). A price that does not say
  which snapshot it is is refused rather than called "open".

## 6. The API: `GET /data/v1/...`

Read-only. JSON only. Nothing here derives a figure: every number is a stored record or comes from
`features` / `matchup`. Mounted in `api/app.py` with one `include_router`.

### Authentication, and the seam for keys and tiers

The same sign-in as the product's other signed-in content routes: `Authorization: Bearer <token>`,
resolved by `api.auth.require_paid_access` (a valid invite or session token; a 402 for a subscription
customer whose paid period ended). Unlike `/games`, `/today` and `/odds` it is **not** dropped by
`APP_PUBLIC_DEMO`: those are the demo's read-only product surface, and this is the bulk data surface the
red-team finding 2 gate (2026-09-01) exists to keep behind a login.

The router carries the dependency itself, so mounting it anywhere is gated.

**The seam.** `api.datasvc.data_access` is the one function that decides who may use the data API and
with what limits. It returns a `DataCaller(user_id, tier, via)` and stores it on
`request.state.data_caller`. The routes read exactly one thing from it today: the tier's `max_limit`,
the page size cap (`TIERS["signed_in"].max_limit = 100`). When keys and paid tiers arrive, change
`data_access` only: accept an `X-Api-Key` header ahead of the bearer token, look the key up, return a
`DataCaller` with that key's `Tier` (a bigger page, more datasets, a quota), and raise the same error
shape for a bad key or an exhausted quota. Rate limiting belongs in the same function. No route changes.

### One error shape

Every error under `/data/v1`, whoever raised it, is

```json
{"error": {"code": "not_found", "message": "no event with id 'nope' in the store"}}
```

with an optional `details` object. FastAPI's exception handlers are app-wide and `api/app.py` is not
this module's to edit, so the router uses a route class (`DataRoute`) that converts exceptions raised
anywhere inside its routes, auth dependency included.

| Status | `code` | When |
|---|---|---|
| 401 | `unauthorized` (or the auth module's own code, e.g. `tester_access_expired`) | no, bad, expired or revoked token; suspended account. Also for an unknown path: auth runs first, so a missing token reveals nothing |
| 402 | `subscription_expired` | a subscription customer whose paid period ended |
| 404 | `not_found` | unknown id, no name match, unknown path |
| 405 | `method_not_allowed` | wrong method on a real path (`Allow` header set) |
| 409 | `ambiguous_name` | a name matches two fighters equally well; `details.candidates` lists them |
| 422 | `invalid_parameter` | bad `limit`, `year`, `status`, `order`, `as_of`, `days`, empty `search`, missing `a`/`b`, `a` equal to `b`; `details.errors[]` names the parameter |
| 422 | `invalid_cursor` | a cursor this API did not issue, or one from a different query |
| 503 | `data_unavailable` | a dataset file exists but cannot be read (corrupt line); logged, and the message carries no path |
| 500 | `internal_error` | an unhandled bug; the message carries an `error_id` that ties it to one server log line, never a traceback |

### Pagination

List endpoints take `limit` (default 50, **capped at 100**; a larger value is served as 100 and
the response says so) and `cursor`, and answer

```json
{"data": [ ... ], "page": {"limit": 50, "count": 50, "total": 1234, "next_cursor": "eyJxIjoi..."}}
```

`next_cursor` is `null` on the last page. The cursor is opaque (base64 of the last item's sort key plus a
fingerprint of the query): it is **keyset**, not an offset, so a page never repeats or skips a row when
data is added between requests, and a cursor replayed against a different query (other filters or order)
is refused with `invalid_cursor`.

### How the files are loaded

The files are never read per request (production has run out of memory from whole-store reads per
request before). One `UfcStore` is loaded per process. Each request costs a `stat()` of the six dataset
files; only a changed modification time (or size) swaps in a fresh store, which then loads each dataset
lazily, **once**, under a lock, so concurrent first requests read each file once. A dataset that fails to read
(a corrupt line) is answered with a 503 and **not re-parsed on every request**: the failure is remembered for that
store version and retried only when the file changes. A request that began
before a swap finishes on the store it started with, so a response is always one consistent version of the
files. A dataset a route does not touch is never read (`/fighters?search=` reads only `fighters.jsonl`);
`fight_stats`, the largest, is read only by the bout, fights, features and matchup routes. Write files with
`UfcStore.upsert` (atomic replace) so a reader never sees half a file; the API picks the change up on the
next request.

### Endpoints

Examples are abbreviated; `$T` is a bearer token. `GET` only.

| Endpoint | Returns |
|---|---|
| `/data/v1/status` | each dataset's record count, newest date and age |
| `/data/v1/ufc/events?year=&status=&order=&limit=&cursor=` | events, newest first (`order=asc` reverses) |
| `/data/v1/ufc/events/{event_id}` | the event and its bouts in card order |
| `/data/v1/ufc/bouts/{bout_id}` | the bout with fighters, result, statistics rows and odds |
| `/data/v1/ufc/fighters?search=` | the best name match (200), the candidates (409) or none (404) |
| `/data/v1/ufc/fighters?limit=&cursor=` | every fighter by name, paginated (no `search`) |
| `/data/v1/ufc/fighters/{id}` | the fighter record and the UFC.com profile |
| `/data/v1/ufc/fighters/{id}/fights?limit=&cursor=` | the fighter's bouts, newest first, upcoming ones included |
| `/data/v1/ufc/fighters/{id}/features?as_of=` | `features_as_of`; `as_of` defaults to now |
| `/data/v1/ufc/matchup?a=&b=&as_of=` | the fact sheet; `a` and `b` are fighter ids or names |
| `/data/v1/ufc/upcoming?days=&limit=&cursor=` | scheduled events with their bouts and current odds, soonest first |

#### `GET /data/v1/status`

```
curl -H "Authorization: Bearer $T" https://<host>/data/v1/status
```

```json
{"data": {
  "generated_utc": "2026-10-03T15:00:00Z",
  "datasets": {
    "events":   {"file": "events.jsonl", "newest_field": "date_utc", "present": true, "records": 14,
                 "newest": "2026-10-10T21:00Z", "bytes": 3863, "age_seconds": -626400, "age_days": -7.25,
                 "source": "manifest"},
    "fighters": {"file": "fighters.jsonl", "newest_field": "fetched_utc", "present": true, "records": 5,
                 "newest": "2026-10-03T12:00:00Z", "bytes": 2315, "age_seconds": 10800, "age_days": 0.12,
                 "source": "manifest"},
    "...": "bouts, fight_stats, odds, ufccom_profiles"},
  "manifest_generated_utc": "2026-10-03T18:44:55Z",
  "service": {"store_loaded_utc": null, "reloads": 0},
  "note": "age_seconds is now minus `newest`; ..."}}
```

Counts and newest dates come from `MANIFEST.json` when its recorded byte size matches the file on disk
(`"source": "manifest"`), otherwise from one streaming pass over the file (`"source": "files"`), cached until
the file changes. Neither loads the dataset into memory and neither happens per request. `age_seconds` is
`now - newest` and is **negative** when the newest record is in the future (a scheduled event); for freshness
read `odds`, `fighters` and `ufccom_profiles`, whose newest is a fetch time. A missing file is
`"present": false` with 0 records. `service` shows when the current store was loaded and how many times it
has been swapped.

#### `GET /data/v1/ufc/events?year=2026&limit=2`

```json
{"data": [
   {"event_id": "7013", "name": "Synthetic Championship Night", "short_name": "SCN 13",
    "date_utc": "2026-10-10T21:00Z", "season": 2026, "status": "scheduled", "venue_id": null, "bout_count": 2},
   {"event_id": "7012", "name": "Synthetic Fight Night 12", "short_name": "SFN 12",
    "date_utc": "2026-08-08T22:00Z", "season": 2026, "status": "final", "venue_id": null, "bout_count": 1}],
 "page": {"limit": 2, "count": 2, "total": 7,
          "next_cursor": "eyJxIjoiZGU3NTZmYTAiLCJrIjpbIjIwMjYtMDgtMDhUMjI6MDA6MDBaIiwiNzAxMiJdfQ"}}
```

`year` is the year of the event's `date_utc` (UTC); `status` is one of `scheduled`, `in_progress`, `final`,
`canceled`, `postponed`, `unknown`.

#### `GET /data/v1/ufc/events/7013`

The stored event record plus its bouts in the event's `bout_ids` order (match number 1 first), each with the
stored bout fields and the fighters' names. A bout id the event lists that is not in the bouts file is named
in `missing_bout_ids` rather than dropped silently.

```json
{"data": {
  "event": {"event_id": "7013", "name": "Synthetic Championship Night", "date_utc": "2026-10-10T21:00Z",
            "status": "scheduled", "bout_ids": ["9101", "9102"], "...": "the stored record"},
  "bouts": [
    {"bout_id": "9101", "match_number": 1, "card_segment": "main", "weight_class": "Welterweight",
     "scheduled_rounds": 5, "status": "scheduled",
     "fighter_a": {"fighter_id": "101", "name": "Alex Archer"},
     "fighter_b": {"fighter_id": "102", "name": "Ben Brawler"}, "...": "every stored bout field"},
    {"bout_id": "9102", "match_number": 5, "card_segment": "prelims", "...": "..."}],
  "missing_bout_ids": []}}
```

#### `GET /data/v1/ufc/bouts/9009`

```json
{"data": {
  "bout": {"bout_id": "9009", "date_utc": "2026-03-14T22:00Z", "weight_class": "Welterweight",
           "winner_id": "102", "result_method": "DEC_UNANIMOUS", "fight_time_s": 1500.0, "...": "stored record"},
  "event": {"event_id": "7009", "name": "Synthetic Fight Night 9", "status": "final", "bout_count": 1, "...": "..."},
  "fighters": {"a": {"...": "fighter record of 101"}, "b": {"...": "fighter record of 102"}},
  "result": {"outcome": "decided", "winner_id": "102", "winner_name": "Ben Brawler", "loser_id": "101",
             "loser_name": "Alex Archer", "method": "DEC_UNANIMOUS", "method_raw": "dec_unanimous",
             "detail": null, "target": null, "end_round": 5, "end_time_s": 300.0, "fight_time_s": 1500.0},
  "stats": ["...fight_stats row of 101...", "...fight_stats row of 102..."],
  "odds": []}}
```

`result` is null for a bout with no result; `outcome` is `decided`, `draw` or `no_contest`. `stats` holds
the rows that exist (one, two or none); `odds` is every provider's stored row.

#### `GET /data/v1/ufc/fighters?search=archer`

Searches with `names.match` (case, accents, punctuation and quoted nicknames folded). **It refuses to guess.**

```json
{"data": {"query": "archer",
          "match": {"fighter_id": "101", "name": "Alex Archer", "weight_class": "Welterweight", "stance": "Orthodox",
                    "dob": "1992-04-10", "active": true, "record": {"wins": 12, "losses": 4, "draws": 0},
                    "score": 0.9, "matched_name": "Alex Archer"},
          "candidates": [{"fighter_id": "101", "name": "Alex Archer", "matched_name": "Alex Archer", "score": 0.9}]}}
```

Two fighters that fit equally well (`search=silva`) answer **409**, naming both and picking neither:

```json
{"error": {"code": "ambiguous_name",
           "message": "'silva' matches more than one fighter equally well; pass a fighter id",
           "details": {"query": "silva", "candidates": [
              {"fighter_id": "104", "name": "Dan Silva", "matched_name": "Dan Silva", "score": 0.9},
              {"fighter_id": "105", "name": "Eli Silva", "matched_name": "Eli Silva", "score": 0.9}]}}}
```

No match is **404** (`not_found`). An empty `search=` is 422. Without `search` the endpoint lists fighters by
name, paginated.

#### `GET /data/v1/ufc/fighters/101` and `/fights`

`/fighters/101` returns `{"fighter": <record>, "ufccom_profile": <row or null>, "ufc_bouts_in_store": 7}`.
It needs a fighter record (404 otherwise); `/fights` and `/features` also work for a fighter who is only in the
bouts.

`/fighters/101/fights?limit=2` lists the fighter's bouts newest first (upcoming and cancelled ones included, with
`result: null`), results from the fighter's side:

```json
{"data": [
   {"bout_id": "9101", "event_name": "Synthetic Championship Night", "date_utc": "2026-10-10T23:00Z",
    "status": "scheduled", "opponent_id": "102", "opponent_name": "Ben Brawler", "weight_class": "Welterweight",
    "card_segment": "main", "scheduled_rounds": 5, "result": null, "method": null, "has_stats": false, "...": "..."},
   {"bout_id": "9011", "date_utc": "2026-06-13T22:00Z", "status": "final", "opponent_name": "Dan Silva",
    "result": "win", "method": "DEC_UNANIMOUS", "end_round": 3, "fight_time_s": 900.0, "has_stats": true, "...": "..."}],
 "page": {"limit": 2, "count": 2, "total": 7, "next_cursor": "eyJxIjoi..."}}
```

#### `GET /data/v1/ufc/fighters/101/features?as_of=2026-07-01`

The response is exactly `features_as_of(store, "101", "2026-07-01")` (section 3), abbreviated here:

```json
{"data": {
  "fighter_id": "101", "name": "Alex Archer", "as_of": "2026-07-01T00:00:00Z",
  "sample": {"fights": 5, "minutes": 65.0, "fights_with_own_stats": 4, "fights_with_opponent_stats": 4,
             "fights_with_both_stats": 4, "fights_without_any_stats": ["9006"],
             "skipped": {"no_start_time": [],
                         "started_without_result": [{"bout_id": "9013", "date_utc": "2026-04-04T22:00Z", "status": "canceled"}]}},
  "record": {"fights": 5, "wins": 3, "losses": 2, "draws": 0, "no_contests": 0,
             "wins_by_method": {"ko_tko": 1, "submission": 0, "decision": 2, "dq": 0, "other": 0, "unknown": 0},
             "losses_by_method": {"ko_tko": 0, "submission": 1, "decision": 1, "dq": 0, "other": 0, "unknown": 0},
             "first_fight_utc": "2025-01-18T22:00:00Z", "last_fight_utc": "2026-06-13T22:00:00Z"},
  "streak": {"type": "win", "length": 1},
  "figures": {
    "sig_strikes_landed_per_min": {"value": 4, "unit": "significant strikes landed per minute",
                                   "fights": 4, "minutes": 50.0, "num": 200, "den": 50},
    "sig_strike_defence": {"value": 0.4, "unit": "1 - opponent significant strikes landed / attempted",
                           "fights": 4, "minutes": 50.0, "num": 150, "den": 250},
    "control_time_share": {"value": 0.2, "unit": "seconds in control / fight seconds",
                           "fights": 3, "minutes": 42.0, "num": 504, "den": 2520},
    "strength_of_schedule": {"value": 0.4444, "unit": "mean opponent UFC win rate at the start of each fight",
                             "fights": 3, "minutes": 55.0, "num": 1.3333, "den": 3, "opponents_without_history": 2},
    "days_since_last_fight": {"value": 17, "unit": "days"},
    "age_years": {"value": 34.22, "unit": "years"},
    "...": "every figure of section 3"},
  "weight_classes": {"current": "Welterweight",
                     "most_recent_change": {"from": "Middleweight", "to": "Welterweight",
                                            "date_utc": "2026-03-14T22:00:00Z", "bout_id": "9009", "direction": "down"},
                     "fought": ["..."], "fights_without_weight_class": 0},
  "career_record_incl_non_ufc": {"label": "Overall professional record from the fighter record, including fights outside the UFC",
                                 "includes_non_ufc": true, "as_of_safe": false, "wins": 12, "losses": 4, "draws": 0,
                                 "no_contests": null, "...": "..."},
  "ufccom_career": {"label": "UFC.com career figures", "as_of_safe": false, "ufc_slug": "alex-archer",
                    "figures": {"sig_strikes_landed_per_min": 9.99, "record_text": "12-4-0 (W-L-D)", "...": "..."}, "...": "..."},
  "missing": []}}
```

`as_of` is an ISO date (`2026-07-01`, the start of that day) or datetime (`2026-07-01T21:00Z`); omitted, it is
now. Unreadable is 422 (in a URL, encode a `+` offset as `%2B` or use `Z`: a bare `+` arrives as a space). Unknown
fighter is 404.

#### `GET /data/v1/ufc/matchup?a=Alex%20Archer&b=brawler`

`a` and `b` are ids or names. An id that exists wins; otherwise the text goes through `names.match` as for the
search, so an ambiguous name is **409** with `details.param` saying which of `a` and `b`, an unknown one is 404,
and the same fighter twice is 422. The response is `matchup(...)` (section 5) plus how each side was resolved:

```json
{"data": {
  "a": {"fighter_id": "101", "name": "Alex Archer"}, "b": {"fighter_id": "102", "name": "Ben Brawler"},
  "as_of": "2026-10-10T23:00:00Z", "as_of_source": "scheduled_bout_start",
  "bout": {"bout_id": "9101", "event_name": "Synthetic Championship Night", "date_utc": "2026-10-10T23:00Z",
           "weight_class": "Welterweight", "scheduled_rounds": 5, "card_segment": "main", "match_number": 1,
           "status": "scheduled", "other_scheduled_bout_ids": []},
  "odds": {"provider": "DraftKings", "orientation": "verified", "as_of_safe": false,
           "moneyline": {"current": {"a": -170, "b": 145, "implied": {"a": 0.6296, "b": 0.4082}, "margin": 0.0378,
                                     "without_margin": {"a": 0.6067, "b": 0.3933}},
                         "open": {"a": -150, "b": 130, "...": "..."}, "close": null},
           "rounds_total": {"line": 4.5, "...": "..."}, "method": {"...": "..."}},
  "differentials": {
    "sig_strikes_landed_per_min": {"unit": "significant strikes landed per minute", "a": 4, "b": 3.3424, "diff": 0.6576,
                                   "a_sample": {"fights": 4, "minutes": 50.0}, "b_sample": {"fights": 5, "minutes": 61.33},
                                   "thin_sample": false},
    "...": "every differenced figure"},
  "styles": {"a": {"applies": ["submission_threat", "goes_the_distance"], "...": "..."},
             "b": {"applies": [{"name": "wrestler", "evidence": {"takedowns_landed_per_15": 2.9348,
                                                                "control_time_share": 0.288}, "...": "..."}]}},
  "previous_meetings": [{"bout_id": "9009", "date_utc": "2026-03-14T22:00Z", "result": "loss",
                         "method": "DEC_UNANIMOUS", "winner_id": "102", "winner_name": "Ben Brawler", "...": "..."}],
  "physical": {"differences": {"height_in": 2.0, "reach_in": 3.0, "reach_minus_height_in": 1.0, "age_years": -2.44},
               "stance_matchup": "Orthodox vs Southpaw", "same_stance": false, "...": "..."},
  "layoff": {"a_days": 119, "b_days": 63, "difference_days": 56, "longer_layoff": "a", "...": "..."},
  "missing": [{"side": "b", "fighter_id": "102", "figure": "sig_strike_share_distance",
               "reason": "none of the 5 fight(s) before as_of has all nine position-by-target landed significant strike counts"}],
  "resolved": {"a": {"query": "Alex Archer", "fighter_id": "101", "matched_by": "name"},
               "b": {"query": "brawler", "fighter_id": "102", "matched_by": "name"}}}}
```

(`styles.a.applies` is shortened to names here; the real response carries the full objects of section 4.)

#### `GET /data/v1/ufc/upcoming`

Events whose status is `scheduled` or `in_progress` and that started no more than 36 hours ago (a card runs for
hours and its status flips late; an older "scheduled" row is a stale row, not an upcoming event), soonest first.
`days=30` limits the horizon. Each bout carries the compact odds (`bout_odds(..., detail="current")`: open and
current moneyline, current rounds total, no method market), or null when no odds row exists.

```json
{"data": [{
   "event_id": "7013", "name": "Synthetic Championship Night", "date_utc": "2026-10-10T21:00Z", "status": "scheduled", "bout_count": 2,
   "bouts": [
     {"bout_id": "9101", "match_number": 1, "card_segment": "main", "weight_class": "Welterweight", "scheduled_rounds": 5,
      "status": "scheduled", "fighter_a": {"fighter_id": "101", "name": "Alex Archer"},
      "fighter_b": {"fighter_id": "102", "name": "Ben Brawler"},
      "odds": {"provider": "DraftKings", "orientation": "verified", "as_of_safe": false,
               "moneyline": {"open": {"a": -150, "b": 130, "...": "..."},
                             "current": {"a": -170, "b": 145, "implied": {"a": 0.6296, "b": 0.4082}, "margin": 0.0378,
                                         "without_margin": {"a": 0.6067, "b": 0.3933}}},
               "rounds_total": {"line": 4.5, "current": {"over": -110, "under": -110, "...": "..."}}, "method": null}},
     {"bout_id": "9102", "match_number": 5, "card_segment": "prelims", "...": "...", "odds": null}]}],
 "page": {"limit": 50, "count": 1, "total": 1, "next_cursor": null}}
```

#### Errors

```
curl https://<host>/data/v1/ufc/events                      -> 401
{"error": {"code": "unauthorized", "message": "missing, invalid, expired, or revoked token"}}

GET /data/v1/ufc/events?limit=0                             -> 422
{"error": {"code": "invalid_parameter", "message": "invalid parameter 'limit': Input should be greater than or equal to 1",
           "details": {"errors": [{"in": "query", "param": "limit", "message": "Input should be greater than or equal to 1"}]}}}

GET /data/v1/ufc/events/nope                                -> 404
{"error": {"code": "not_found", "message": "no event with id 'nope' in the store"}}

GET /data/v1/ufc/events?cursor=abc                          -> 422
{"error": {"code": "invalid_cursor", "message": "the cursor is not one this API issued; start again without one"}}
```

## 7. What the contract did not fix, and what this code assumed

Written so the orchestrator and the ingestion workers can reconcile it.

1. **`ufccom_profiles` field names** are not in `UFC_SCHEMA.md` (only their meaning). They are passed
   through verbatim under `ufccom_career.figures`, so any naming works, and no computed figure uses them.
2. **`method_odds` nesting** of open/close is ambiguous in the contract. Three nestings are read (section 5.1);
   an unlabelled price is refused.
3. **`fight_stats` units and `stats_complete`.** Counts are counts, `time_in_control` is seconds (per the
   contract's "seconds of control"). `stats_complete` is not consulted; a figure uses a row when the fields it needs
   are numbers. The snake case is read as the contract says, with ESPN's camel case and the squashed lower case
   also accepted.
4. **A draw** is read as `winner_id` null with `result_method` `DRAW`, and **a no contest** as `NC`. A final bout
   with no winner and neither is "started without result" (listed, not counted).
5. **`fight_time_s` null** means the bout has no clock figure: it still counts as a fight, and is left out of every
   rate and of the average fight time.
6. **Scope of every count** is the store. They equal the UFC career only if the store covers it from the first fight.
7. **Thresholds** of section 4 are placeholders to be recalibrated against the store's own percentiles.
