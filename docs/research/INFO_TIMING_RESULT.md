# INFO_TIMING_V1 result: the prop store cannot see the lineup window; game lines can, and show no drift

**2026-10-16.** Registration `docs/PREREG_INFO_TIMING.md` (commit `287c3118b`,
freeze sha256 `4b6a8833...1c92`, recomputed by the runner before reading anything).
Harness commit `2b9dbf508`. One run, commit `b00de9075`. Artifact:
`data/research/info_timing/info_timing_result.json` (OK units in
`info_timing_units.jsonl`). Command: `python scripts/info_timing_measure.py`
(refuses to run twice); `--describe` prints the per-posting capture counts below.

## Verdict by the registered rule: NOT MEASURABLE (registry `below_floor`)

The decisive test needs at least 30 hitter-prop units over at least 5 dates. It got
**71 units from 4 postings on 1 date** (2026-09-12). No interval can be computed.
This is not a null and not a pass: **at the current prop capture schedule the
question cannot be asked.** It is recorded as `below_floor`, so the read count the
product states does not change.

## Why: props are captured at most twice per game

| | count |
|---|---|
| admissible, joinable lineup postings (game dates 2026-09-08..10-15) | 317 (25 dates) |
| postings with **no** prop capture after them before first pitch | 63 |
| postings with **exactly one** prop capture after them (entry = close, unmeasurable) | **250** |
| postings with **two** (the only measurable case) | **4** |
| joinable games by total pre-pitch prop captures: 0 / 1 / 2 | 10 / 51 / 94 |

A drift needs two captures after the posting. The store never has more than two
prop captures for a game (scratch instrument check over every event dated
2026-09-08..10-16: 133 events with one, 107 with two, none with three), consistent
with `03_prices.md`'s description of an early baseline capture plus gate captures.

**Capture lag, posting to first capture after it (317 postings):**

| | within 30 min | within 60 | within 120 | none before pitch | median lag |
|---|---|---|---|---|---|
| hitter props | 53 | 82 | 194 | 63 | 89 min |
| game lines | 273 | 298 | 304 | 12 | 0.0 min (same capture slot as the watch poll, about 1-2 s later) |

Posting to first pitch: median 180 min (quartiles 133-217). Bracket width (how
precisely we know the posting time): median 48 min (quartiles 15-60). Median gap
between consecutive captures in the last 6 hours before first pitch: **props 255
min** (23 postings with two captures in that window), **game lines 33 min** (303
postings). Game-line closes are a median 13 min before first pitch; the measured prop
closes 43-68 min before.

**So the honest answer to "can a 13-minute cadence capture the window" is split:**
the game-line cadence does capture it (first capture after a posting is immediate,
the close is ~13 min out), and the prop cadence does not capture it at all.

## Hitter props, descriptive only (n=71, one date, four postings; no interval)

| | n | M1 drift pts | M2 CLV at average price pts | CLV at best price (price improvement, not edge) |
|---|---|---|---|---|
| hits (R1 Over) | 35 | +0.09 | -3.67 | -2.62 |
| total bases (R1 Over) | 36 | +0.03 | -3.39 | -2.26 |
| pooled | 71 | +0.06 | -3.53 | -2.44 |

Entry captures 1-46 min after the posting, closes 43-68 min before first pitch.
R2 (batter left out -> Under) produced **zero** measurable units: 234 left-out
batters still had quotes before the postings, and books stopped quoting all of them
afterwards (422 NO_ENTRY, 48 NO_LATER). One date says nothing; these numbers are
shown because every result is published, not because they support anything.

## Game lines, rule R3 (a regular rested -> opponent / Under), descriptive, cannot change the verdict

95% date-clustered bootstrap, 2,000 resamples, seed 20261016. MDE = 2.8 x
cluster-robust SE.

| market | n units / dates | M1 drift pts [95% CI] | MDE | M2 CLV at average price [95% CI] | pre-posting move [95% CI] |
|---|---|---|---|---|---|
| moneyline (opponent) | 128 / 18 | -0.02 [-0.07, +0.05] | 0.08 | -1.93 [-2.00, -1.86] | +0.03 [-0.03, +0.08] |
| run line (opponent) | 128 / 18 | -0.01 [-0.06, +0.04] | 0.07 | -2.10 [-2.18, -2.01] | +0.00 [-0.07, +0.05] |
| total (Under) | 119 / 17 | +0.08 [-0.05, +0.29] | 0.22 | -2.29 [-2.43, -2.04] | +0.00 [-0.11, +0.11] |

Best-price CLV (price improvement only): -0.92, -0.94, -1.24. In plain words: when a
regular sits, the moneyline and run line do not move toward the opponent after our
first capture, nor between our last look before the posting and that capture,
within about 0.07 probability points; and a bet at the average price at that
capture loses the vig against the close, about two points.

R3 coverage: of 317 postings, 123 had fewer than 10 history games (`NO_HISTORY`),
56 had no regular missing, 138 had one or
more (73 one, 51 two, 14 three or more). Totals: 9 units dropped because the line
moved (`LINE_ABSENT_AT_CLOSE`), which biases total M1 toward zero (PREREG limit 5).

## Exclusions and instrument checks

- Lineup events: 203 out of window, **88 game_pk not in `mlb_results.csv`** (63 of
  them are postings seen on 2026-09-08/09, dates the results file lacks; excluded under the
  registered rule, not rescued; the two-captures bound above holds for those games
  too), 31 observed only after first pitch (mostly 2026-09-27, when the watch had a
  14:44-19:40Z gap, plus a game postponed a day, where the earlier MLB schedule
  time applies), 28 doubleheader or ambiguous map, 1 partial lineup.
- Posted batters matched to a prop name: 2,594 of 2,853; 259 had no prop quoted.
- Raw provenance: 100% of the 240 processed prop capture instants and 97.8% of the
  813 game-line instants have a raw envelope of the matching kind within 5 min.
  Scratch check: every raw prop capture (307 event-minute pairs) is in the processed
  store; nothing raw is missing.
- Odds `commence_time` earlier than the MLB first pitch by >5 min: 4 events (not
  used as a cutoff).
- Choices made in code before the run that the PREREG does not spell out: run-line
  ties go to the smaller home line; the R2 "before" reference is the earlier of the
  two postings' bracket starts; the units file keeps OK units only (exclusions are
  counted in the artifact). `--describe` was added after the run and prints only.
- Seal: the harness discards sealed and out-of-window lines by their date text
  before parsing (tests pin it). `sealed_untouched` is false on the registry row
  because of a design-time inspection (PREREG section 0).

## What this says and does not say

- It does not say lineups carry no information for props. It says **our prop
  store cannot measure it**: a test needs a prop capture shortly after each posting
  and another near first pitch, at least two more per game than we take now.
- On game lines, for this one rule (rested regulars), there is no detectable
  movement before or after the posting at our resolution, and the vig dominates.
- No outcome was read, no bet placed, no return claimed.

**Implication for a V3 value rule:** nothing here supports a lineup-timing value
rule; on game lines the posting moves nothing we can see and the first-capture bet
loses about two points of vig to the close, and on props the question can only be
asked after a new, separately registered forward prop-capture schedule exists.
