# Subsystem map — historical-data-pit

Read-only. Measured 2026-09-03 against the tree on
`claude/sports-betting-analysis-review-g1o0co`. 2025 is tuning-only and was
only touched for row counts/manifest facts, never analyzed. The sealed
2026-01-01..2026-08-27 window was not opened beyond `ls`/`wc`/manifest reads.
No data/historical file was modified; no network call was made.

Question this answers: for a historical MLB game at a chosen decision
timestamp T, what of the owner's information categories (starters, bullpen,
offense, player context, environment, market) can honestly be reconstructed
today, at what timestamp granularity, where the PIT guarantee lives, and what
is gone forever vs. still purchasable.

---

## 0. The data on disk (data/historical/**, sizes, counts)

```
arsenals/                636K   batter_2026.json, pitcher_2026.json — 2026 ONLY
bullpen_log.jsonl         15M   64,898 rows — per-appearance boxscore lines
first_five_results.jsonl 320K   F5 settlement results
handedness.json          120K   1,592 players {bats, throws}
lineups.jsonl            6.9M   4,892 rows {date, game_pk, away[], home[]}
mlb_results.csv          1.2M   9,364 games, 2023-03-30 .. 2026-09-01 (schedule+boxscore)
mlb_results.manifest.json 144K  per-date fetch manifest
odds_first_five/          1.6M  manifest.json + mlb_{2023,2024,2025}.jsonl
odds_history/             133M  manifest.json + mlb_{2023,2024,2025}.jsonl
pitcher_logs.jsonl        9.1M  42,960 rows — per-appearance MLB gameLog
pitcher_splits.json       144K  187 entries, ALL "...:2026" keys — 2026 ONLY
scan_candidates.jsonl      92K  
statcast/                  44M  180 windows, 2023-03-30..2026-08-27, 2,737,968 pitch rows
statcast_pre_bbtype/       43M  mirror of statcast, pre-bb_type schema (same 181 files)
transactions.jsonl        8.8M  27,053 rows, 2022-04-08..2026-09-01, incl. IL placements
data/archive/historical/   —    gzip'd copies of odds_history/odds_first_five + SHA256SUMS
```

`data/watch/*` (lineups_watch, probables_watch, transactions_watch,
umpires_watch) are the **forward** capture stores — `umpires_watch.jsonl` is
37 lines starting 2026-09-02; none of this back-fills 2023-24.

---

## 1. STARTERS

**EXISTS.** Handedness (`handedness.json`, 1,592 players, static), per-appearance
pitcher game logs (`pitcher_logs.jsonl`, 42,960 rows: IP, ER, H, BB, K, HR, BF,
pitches, `games_started`, home/away, date), and three pitch-level rebuilt
features accumulated forward from Statcast with a real cutoff filter
(`src/pipeline/rebuilt.py:215-256`, `_process_row` `:106-181`):
- `platoon_split` (wOBA vs L/R, 60-BF-per-side floor) — `rebuilt.py:259-284`
- `pitch_mix` (usage/whiff/wOBA per pitch type, 50-pitch floor) — `:287-304`
- `fastball_velocity` (last-5-start FF/SI average, 100-fastball floor) — `:328-351`
- `groundball_share` (career-to-cutoff, 50-batted-ball floor) — `:354-374`

All four are declared **CLEAN** in the PIT registry (`src/model/pointintime.py:87-102`)
because the walk is over per-pitch rows with `game_date < cutoff`
(`rebuilt.py:1-26` docstring, enforced by `tests/test_matrix_v5_features.py`
per `docs/EVOLAB_PHASE0_FEASIBILITY.md:209-226`).

**PARTIAL / timestamp gap — starter identity itself.** `away_probable_id` /
`home_probable_id` are copied verbatim from MLB's `probablePitcher` hydrate
(`src/providers/mlb.py:163,200-201`) into `mlb_results.csv`
(`src/pipeline/history.py:49`), fetched **retroactively** (repo's first commit
is 2026-08-27) for games finished 2-3 years earlier. `docs/AUDIT_PROBABLE_PITCHER_PIT.md`
(367 lines, measured 2026-08-31) proves this field is the **terminal,
post-first-pitch value, not a pre-game announcement**: two independent
methods (statcast first-pitch-thrower derivation, and the pitcher's own
gameLog `games_started` flag) agree at 99.90%/99.92% (2023/2024) — 12-41x
too clean for a real scratch rate of 0.3-1/day (`AUDIT_PROBABLE_PITCHER_PIT.md:145-170`).
Nine of 9,711 sides disagree and every one is a bulk-pitcher/opener/resumption
case, not a scratch (`:119-141`) — meaning the observed in-store scratch rate
is effectively **zero**, which a genuine pre-game feed cannot produce.
Consequence: nine downstream features gated on this id
(`src/research/matrix.py:221-222`; listed in `pointintime.py:152-155`
as `lineup_platoon_share`, `starter_platoon_gap`, `lineup_vs_primary_pitch`,
`primary_pitch(_share)`, `top_minus_bottom`, `lineup_vs_starter_history`,
`starter_velocity_gap`, `starter_groundball_share`) are marked availability
class **C** with a **known-false** availability time
(`EVOLAB_PHASE0_FEASIBILITY.md:234-260`), not point-in-time class B, even
though `pointintime.py` marks their non-probable inputs CLEAN. That is a real
distinction the registry itself does not encode: CLEAN describes
cutoff-respecting accumulation, not "the pitcher id was knowable at T".

**MISSING forever.** No archived probables feed with fetch timestamps exists
for 2023-24; none can be bought (`AUDIT_PROBABLE_PITCHER_PIT.md:284-289`,
`EVOLAB_PHASE0_FEASIBILITY.md:506-513`). `rosterwatch`'s own `fetched_utc`
history (the mechanism that WOULD fix this) only starts 2026-08
(`src/pipeline/rosterwatch.py:307-325`).

**CLAIMED-BUT-ABSENT for 2023-24.** `arsenals/{batter,pitcher}_2026.json` and
`pitcher_splits.json` (187 entries) are **2026-only** snapshots of the
season-to-date Savant/statSplits leaderboards. `pointintime.py:108-133`
correctly marks the live `splits`/`arsenals`/`matchup_history` endpoints
**LEAKY** ("the MLB statSplits endpoint IGNORES startDate/endDate — verified
by requesting three different ranges for one pitcher and getting
byte-identical numbers") and the historical build never touches them — but a
reader skimming the directory listing alone would think 2023-24 arsenal/split
data exists; it does not, by design, and the rebuilt_* pitch-level path is
the only substitute.

**BOOST.** The rebuilt-from-Statcast machinery is sound and already covers
handedness, arsenal, velocity, groundball share, splits. Extend it (K%/BB%
season rate, TTO-style per-time-through-order splits, days-rest) rather than
touching the probable-pitcher path, which needs a new *named engine
parameter* (`starter_identity = "actual_at_first_pitch"`) per
`AUDIT_PROBABLE_PITCHER_PIT.md:290-317`, not a data fix — there is no data fix.

---

## 2. BULLPEN

**EXISTS.** `bullpen_log.jsonl` (64,898 rows) is a per-appearance boxscore
line: `{game_pk, date, person_id, name, team, started, innings, pitches,
batters_faced, hits, earned_runs, walks, strikeouts}`. `pointintime.py:54-58`
marks `bullpen` **CLEAN** ("built from per-game boxscore appearances;
workload as of a date is a window over rows that already exist"), used by
detector `bullpen_workload` (`pointintime.py:143`).

**PARTIAL.** Availability/leverage/closer-role and handedness-of-reliever-vs-batter
matchups are not separately modeled here — bullpen_log carries outcomes, not
role designation or same-day availability flags (e.g. "threw 30 pitches
yesterday, unavailable tonight" must be derived by the caller from raw
innings/pitches, not stored as a feature). No file in `data/historical`
names closer/setup/high-leverage role explicitly.

**MISSING/unmeasured.** No bullpen-specific PIT audit equivalent to the
probable-pitcher one exists; `bullpen_log.jsonl`'s own fetch-vs-event-date
retroactivity (same repo-first-commit-2026-08-27 problem as `mlb_results.csv`)
has not been separately audited the way starters were. Given it is sourced
from completed boxscores rather than an announcement field, this is lower
risk than the probable-pitcher leak but has not been measured.

---

## 3. OFFENSE (lineups, splits, platoon, matchup, power/contact)

**EXISTS.** `lineups.jsonl` (4,892 rows: date, game_pk, ordered away[]/home[]
with `{name, order, person_id, position}`). `pointintime.py:78-82` marks
`lineups` **CLEAN** ("the schedule feed returns the lineup that was actually
posted for that game"). Rebuilt batter-vs-pitch-type and batter-vs-pitcher
lines from Statcast (`rebuilt.py:307-325`, `batter_vs_pitcher`,
`batter_vs_pitch_type`) give platoon-aware, point-in-time offense features
without touching the leaky vsPlayer/statSplits endpoints.

**PARTIAL / real timing gap.** `lineups.jsonl` rows carry no fetch/posting
timestamp — `EVOLAB_PHASE0_FEASIBILITY.md:246-249`: "**No lineup posting
timestamp exists for 2023-24.**" `lineup_store` fetched them per date,
retroactively, so a replay can never *prove* a lineup-conditioned decision
was made after the lineup actually posted; it can only assume a nominal
T-3h/T-4h posting time (`:255-260`, `:283-303` shows the coverage cliff this
assumption produces — 3,624/4,819 games survive a T-180 assumption, and that
surviving subset is start-time-selected, not random). The forward
`rosterwatch` store carries `fetched_utc` from 2026-08 on, which cannot
repair 2023-24 (`AUDIT_PROBABLE_PITCHER_PIT.md:349-353` says the same).

**MISSING forever.** Confirmed-vs-unconfirmed lineup state, and lineup-post
timestamps, for 2023-24 — no archived feed exists and none is purchasable
(same class of gap as probables).

---

## 4. PLAYER CONTEXT (injuries, transactions)

**EXISTS as raw data, MISSING as a feature — CLAIMED-BUT-ABSENT relative to
the vision.** `transactions.jsonl` (27,053 rows, 2022-04-08..2026-09-01) has
real category breakdown across the whole 2023-24 window: `il_placement`
1,768, `il_activation` 2,554, `il_transfer` 369, `rehab` 2,279, plus
`optioned`/`recalled`/`signed`/`traded`/`designated`, each with `date`,
`filed_date`, `injury_note`, `player_id`, `team`. This is real injury/roster
history and it has a `filed_date` that could plausibly seed a PIT timestamp.
**But it is wired into nothing**: `grep` for `transactions.jsonl` /
`load_transactions` across `src/` returns only `src/research/coverage.py`,
`src/pipeline/news.py`, and `src/pipeline/rosterwatch.py` (the forward
watcher) — **no entry in `pointintime.py`'s `INPUTS`, no detector in
`DETECTOR_INPUTS`, no reference in `src/research/matrix.py`.** The owner
vision's "injuries" line item under offense/player-context has real 2023-24
raw material sitting unused.

**BOOST.** This is the highest-leverage low-cost extension in the whole
subsystem: the raw data already exists for the full 2023-24 window; it needs
a `pointintime.py` entry (`filed_date < cutoff` accumulation, same shape as
`rebuilt_*`) and a matrix feature, not new collection.

---

## 5. ENVIRONMENT (park, weather, umpire, travel)

**EXISTS — park/travel.** `src/data/parks.py` is static reference data
(coordinates, roof), marked **CLEAN** (`pointintime.py:64-66`). `travel` is
CLEAN too, "derived from the schedule and stored park coordinates"
(`:59-63`), consumed by `travel_load` (`:147`).

**PARTIAL — orientation/wind is a known, named gap, not silent.**
`src/data/parks.py:9-21` documents `orientation_deg` as deliberately `None`
for every park: without the home-plate-to-center-field bearing, wind
speed/direction from the weather provider cannot be classified as
in/out/cross, so "wind speed is collected but not yet applied as a model
input" (`src/providers/weather.py:11-15`). This is CLAIMED-elsewhere,
ABSENT-in-effect: the plumbing exists, the one derived fact that makes it
useful does not.

**MISSING for 2023-24, but purchasable now.** No historical weather store
exists under `data/historical/` (only `data/processed/weather_forecast.jsonl`,
a forward/live store). `pointintime.py:68-72` marks `weather` **CLEAN** on
the theory that "Open-Meteo serves an archive by date, so a past reading is
the reading, not a projection backwards" — `src/providers/weather.py:135`
(`fetch_archive`) exists and is keyless/free, but **no backfill run has ever
populated 2023-24 weather into `data/historical`.** This is the single
biggest "can still be fetched, but capture-now item" for the environment
category — Open-Meteo's archive has a multi-day lag but does not expire the
way a betting line does.

**MISSING forever — umpires.** No historical umpire-crew store for 2023-24.
`src/providers/mlb.py:235-321` supports `hydrate_officials=True` and a
`home_plate_umpire` extractor exists, and the forward `umpires_watch.jsonl`
(37 lines, starting 2026-09-02) captures it going forward — but nothing
back-filled 2023-24, and MLB's officials hydrate for a completed game (like
`probablePitcher`) would need the same retroactivity scrutiny the starter
audit gave the pitcher field before it could be trusted as point-in-time even
if back-filled.

---

## 6. MARKET

**EXISTS but severely narrower than the vision's board.** `odds_history/`
(133M, 3 files) holds **600 API-snapshot records/season** = 200 dates x 3
fixed UTC polling times (16:50/22:50/01:50Z per
`EVOLAB_PHASE0_FEASIBILITY.md:44-46`), each snapshot fanning out to many
events. Measured directly (this map): the ONLY market keys present across
2023/2024/2025 are `h2h` and `totals` — **no `spreads` (run line) was ever
captured historically**, confirmed independently by
`docs/EVOLAB_DESIGN.md:78` and `docs/EVOLAB_PHASE0_FEASIBILITY.md:332-346`
("It may **not** route to spreads/run line — no such data was ever bought").
`odds_first_five/` (1.6M) holds F5 h2h/totals only, **one observation per
game, no timing, no movement** (`EVOLAB_PHASE0_FEASIBILITY.md:305-329`): 185
(2023)/133 (2024)/172 (2025) game records with any book, 167/123/163 with a
usable pre-game snapshot.

`pointintime.py:73-77` marks `market` **CLEAN** ("historical odds are
snapshots at a named instant, and the closing match refuses any snapshot at
or after first pitch") — that guarantee is real and well-tested
(`EVOLAB_PHASE0_FEASIBILITY.md:220-226` cites `tests/test_validation_pit.py`).
But CLEAN describes the *snapshots that exist*, not *market breadth*: no
alt lines, no team totals, no F5 run line beyond the thin probe, no props of
any kind historically, no derivatives (race-to-X, first-to-score), no parlay
inputs.

**Granularity is coarse.** Median 4 (2023) / 3 (2024) distinct pre-game
instants per game; finest spacing anywhere in the store is 177 minutes
(`EVOLAB_PHASE0_FEASIBILITY.md:26-30`). A defensible T-30 close exists for
only 27.4%/25.2% of games (`:31`). Best-price-at-an-instant is defensible,
but "which book is best" ties 63-79% of the time (`:29`).

**Live/forward is much wider — not backfillable.** `src/providers/odds.py:5,52,72,86`
shows the *live* fetcher pulls `h2h`, `spreads`, `totals` for full game and
F5, plus `PROP_MARKETS = ("pitcher_strikeouts",)`. None of that breadth
exists for 2023-24 and cannot be purchased after the fact for the same
reason lineup timestamps can't: the odds API only serves what was polled at
the time, and nobody polled spreads/props back then.

**What could still be bought (priced, not yet bought), per
`docs/COLLECTION_POLICY.md:9-16`:** a 5-minute historical snapshot grid (10
credits/event/snapshot — the sub-3-hour granularity gap), F5 spreads/totals
(3 books, thin), alternate spreads/totals (7 books, 130-160 outcome
rows/event at 1 credit — "the best information-per-credit on the board"),
and pitcher-strikeout prop history from ~May 2023 (3-4 books,
listing-dependent). All gated behind a registered hypothesis and owner
sign-off per the policy; none has been drawn down for 2023-24 as of this
read.

---

## 7. Where the point-in-time guarantee actually lives

Two artifacts carry the whole guarantee:

1. **`src/model/pointintime.py`** (216 lines) — the input registry.
   `CLEAN`/`LEAKY`/`UNKNOWN` per named input (`INPUTS`, `:43-134`), a
   detector-to-input map (`DETECTOR_INPUTS`, `:140-156`), and
   `require_clean()` (`:204-216`) which **raises** rather than warns when a
   historical evaluation touches a non-CLEAN input. This is data, not
   convention, by explicit design (module docstring `:1-28`): "a
   season-to-date statistic applied to a game earlier in that season... is
   invisible: the numbers are real, the code is correct, and the result is a
   lie."
2. **`docs/AUDIT_PROBABLE_PITCHER_PIT.md`** — the one input the registry's
   CLEAN/LEAKY binary cannot express: an input that is mechanically
   cutoff-respecting (CLEAN by the registry's own definition) yet carries a
   **known-false availability time** because the field it depends on
   (`*_probable_id`) is a post-hoc value, not an announcement. The audit's
   recommendation #2 (`:298-303`) is explicit that this is a gap in the
   registry's expressiveness, not just a data problem: "`pointintime.py`
   marks the rebuilt inputs CLEAN on the basis of cutoff-respecting
   accumulation, which is correct and is a different claim from 'the pitcher
   id was knowable at T.' The distinction should be visible in the audit
   rather than left to a reader." As of this map, `pointintime.py` has not
   been updated with that distinction — it is a recommendation, not yet
   applied.

Enforcement is tested (not just asserted): `tests/test_validation_pit.py`
(`test_data_dated_after_the_game_cannot_move_the_row`,
`test_sealed_seasons_are_refused_before_any_data_is_read`, etc.) and
`tests/test_matrix_v5_features.py` (`test_pitches_after_game_day_cannot_move_the_row`,
`test_build_is_deterministic`), per `EVOLAB_PHASE0_FEASIBILITY.md:216-226`.

---

## 8. Timestamp-granularity classes (from `EVOLAB_PHASE0_FEASIBILITY.md §3`)

| class | meaning | example | 2023-24 timestamp recorded? |
|---|---|---|---|
| A | schedule publication, months ahead | `game_pk`, `start_time_utc` | yes, 100% |
| B | named snapshot instant, exact | odds `snapshot_at` | yes |
| C | max(month-cutoff, probable announcement) | starter-conditioned features | cutoff yes; **announcement NO — and the field is post-hoc, not announcement** |
| D | lineup posting (~T-3h/T-4h) | lineup-conditioned features | **NO** |

Only A and B can be served honestly and exactly at an arbitrary T. C and D
require a declared, versioned assumption (nominal posting/announcement time)
— per the audit's recommendation, that assumption is not yet a named engine
parameter anywhere in the code as of this read (searched: no
`starter_identity` or lineup-assumption constant exists in `src/`).

---

## 9. What is absent forever vs. what could still be fetched/bought

**Forever gone (no source exists, cannot be reconstructed):**
- Lineup posting timestamps, 2023-24 (`EVOLAB_PHASE0_FEASIBILITY.md:506-513`).
- Probable-pitcher announcement timestamps and the true late-scratch rate,
  2023-24 (`AUDIT_PROBABLE_PITCHER_PIT.md:284-289,348-356`).
- API-observation latency (book-changes-price → API-records-it lag);
  needs a second independent feed that was never run concurrently.
- Odds book depth/limits/"takeability at stake" — never purchasable, not
  offered by the vendor.
- 2023-24 run-line (`spreads`), alternates, props, team totals, derivatives —
  never polled at the time; the vendor serves point-in-time snapshots only,
  so today's purchase cannot manufacture a 2023 snapshot.
- Historical umpire crews for 2023-24 (no archived feed; forward capture
  only starts 2026-09).

**Still fetchable/purchasable now (a genuine capture-now opportunity, not
gone yet):**
- 2023-24 historical weather via Open-Meteo's archive endpoint
  (`fetch_archive`, keyless/free) — simply never run against
  `data/historical`; multi-day lag but no expiry.
- The 5-minute historical odds snapshot grid, F5 spreads/totals, alternate
  spreads/totals, and pitcher-strikeout prop history from ~May 2023 — all
  priced and named in `docs/COLLECTION_POLICY.md:9-16`, gated behind a
  registered hypothesis and owner sign-off, not yet drawn down for 2023-24.
- Park `orientation_deg` — a bounded, verifiable research task
  (`docs/PARK_ORIENTATION.md`), not a data-purchase problem; once filled,
  weather-driven wind features activate with no further code change.
- Injury/transaction-derived player-context features — the raw data already
  sits in `transactions.jsonl` for the full 2023-24 window; the work is
  wiring, not collection (see §4).

**Precious/live-season-only (capture now, in the "live season is precious"
sense the owner names explicitly):** anything the forward-only stores
(`rosterwatch`'s `fetched_utc` probable/lineup change events,
`umpires_watch`, `data/watch/*`) are recording for 2026 has no historical
analogue and, once the 2026 season passes, becomes exactly as unrecoverable
as the 2023-24 lineup-timestamp gap is today. The sealed
2026-01-01..2026-08-27 window was not opened by this map and its accumulation
state was not verified.

---

## 10. BOOST vs REPLACE, per component

- **`src/model/pointintime.py` (registry): BOOST.** The architecture (data,
  not convention; refuse rather than warn) is sound and tested. Extend it
  with (a) a `starter_identity` versioned parameter distinguishing
  "cutoff-clean" from "known-availability-time" per the audit's
  recommendation #1-2, and (b) new `INPUTS` entries for
  transactions/injuries once wired.
- **`src/pipeline/rebuilt.py` (pitch-level accumulation): BOOST.** The single
  hardest problem here (deriving point-in-time splits/arsenals/matchup from
  raw Statcast with a real cutoff) is already solved, tested, and
  documented. Extend with K%/BB% rate stats, TTO splits, days-rest if not
  already elsewhere.
- **Probable-pitcher path (`src/providers/mlb.py` + `mlb_results.csv`):
  REPLACE the *claim*, not the data — there is no code fix, per the audit.
  The fix is declarative: name the parameter, print the exposure on every
  artifact, never silent.
- **Lineup timestamping: BOOST going forward, cannot repair the past.**
  `rosterwatch` already does the right thing from 2026-08; nothing to build,
  just to keep running so the live season does not repeat the 2023-24 gap.
- **Market history (`odds_history`/`odds_first_five`): BOOST cautiously.**
  The snapshot-instant guarantee is real; breadth (spreads/props/alts) is
  the gap, and it is a purchasing decision gated by `COLLECTION_POLICY.md`,
  not a code change. Widening it for 2023-24 is possible only for currently
  fetchable years — vendor cannot backfill polls never taken.
- **Weather/park: BOOST.** Archive fetch capability exists and is unused for
  2023-24; running it is cheap, keyless, and turns a MISSING category into
  an EXISTS one without any new provider code.
- **Transactions/injuries: BOOST, highest ROI item found.** Data exists for
  the full 2023-24 window and is completely unused by any feature.
- **Umpires: cannot BOOST historically; only forward capture exists.**

---

## 11. Key numbers (for quick citation)

- odds_history: 600 records/season x 3 (2023/24/25) = 1,800 records; markets
  = `{h2h, totals}` only, confirmed by direct scan of all three files.
- odds_first_five: 265/189/207 game records (2023/24/25); 185/133/172 with
  any book; always exactly 1 snapshot/game.
- statcast: 180 windows, 2023-03-30..2026-08-27, 2,737,968 pitch rows.
- mlb_results.csv: 9,364 games, 2023-03-30..2026-09-01.
- transactions.jsonl: 27,053 rows, 2022-04-08..2026-09-01; 1,768 `il_placement`
  + 2,554 `il_activation` + 369 `il_transfer` rows fall inside 2023-24.
- lineups.jsonl: 4,892 rows. pitcher_logs.jsonl: 42,960 rows. bullpen_log.jsonl:
  64,898 rows.
- Probable-pitcher agreement with actual first-pitch thrower: 99.90% (2023,
  4,859 sides) / 99.92% (2024, 4,852 sides); 9 total disagreements, zero of
  them scratches.
- arsenals/ and pitcher_splits.json: 2026-only, not usable for 2023-24 (by
  design — replaced by rebuilt_*).
