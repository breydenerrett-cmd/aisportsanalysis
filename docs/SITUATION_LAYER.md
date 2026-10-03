# The situation layer: what was built

`docs/SITUATION_LAYER_PLAN.md` is the plan (why, which factor families, how it is proven). This page is
what exists: the record, the factors as implemented for MLB and UFC, how the AI analyst reads them, the
side-by-side test and its switch and cost, the first historical test, and what the data could not
support. Phase one: MLB (regular season and postseason) and UFC. Everything is stdlib, pure and offline
in its tests.

> Nothing here is a claim that the situation helps. The record starts empty. The layer is described,
> measured and shown; whether it helps is what the side-by-side test is for, in public, including a loss.

## 1. The record (`src/situation/record.py`)

One shape for every sport. A record is a flat list of **factors** and a flat list of **gaps**.

| field of a factor | meaning |
|---|---|
| `family`, `name`, `side` | where it belongs; the side is `away`/`home` (MLB), `a`/`b` (UFC) or `game` |
| `value` | ONE scalar (number, text, bool): never absent, never a list, so a path the analyst cites lands on a single value the critic can check |
| `unit`, `sample` | what the value counts, and how many observations it rests on (`{"games": 10}`) |
| `as_of` | the newest thing it used: a date or instant strictly BEFORE the record's own cut-off |
| `source` | where it came from, in words |
| `sentence` | the fact in plain words with its sample size, as the page prints it |
| `detail` | optional companion numbers and names (the other half of "4-1") |

A fact that cannot be built is a **gap** (`family`, `name`, `side`, `reason`), listed, never filled with
an average or a guess. `record.build` checks every factor against the cut-off and moves one that fails
(a stamp on or after the cut-off, a value that is not a scalar) into the gaps with the reason, so a
builder bug can cost a fact and can never put a leak in front of the analyst.

**The cut-off.** MLB: the game's DATE; only games dated strictly before it count, so a game on the
date and later never does (not even the first half of a doubleheader, whose second game says so and
leaves the day counts out). UFC: the bout's scheduled start; only bouts that started before it and have
a result count (the data layer's own rule, `docs/datasvc/UFC_FEATURES.md`). A test rebuilds each record
from the world as it was the day before and requires the same answer, and another checks every
factor's `as_of` against the cut-off.

**The sentence rule.** The analyst's critic strikes any number in a claim that is not a number in the
packet. Every number a factor's sentence prints is also a number the factor holds (value, sample or
detail), and the tests run that check over every factor the builders can write; a second test runs the
real critic over every sentence in a real packet and finds no unsupported number and no unsupported name.

## 2. The factors as built

### MLB (`src/situation/mlb.py`, `src/situation/series.py`)

Reads the game (who, where, when, the probable starters the schedule names) and the results store
(`data/historical/mlb_results.csv`, which starts 2023-03-30). Postseason series are rebuilt from game
results (`series.py`: two clubs meet at most once in a round of a season). The display-only history
(section 7) extends the long-memory facts only.

| Family | Factors (per club unless noted) | Written for |
|---|---|---|
| rest_and_rhythm | `days_since_last_game` (with the days off); `games_last_7_days`; `travel_miles` (great circle from the park of its last game to this one); `previous_round` (bye, or the series it came through: score, length, how long ago it ended) | every game; `previous_round` in Division Series, LCS and World Series |
| form | `last_5`, `last_10` (record and run margin, with the games they rest on); `streak`; `runs_per_game_recent_vs_season` (last 10 against the regular season) | every game |
| stakes | `series_state` (game number, series score, wins needed; game); `elimination` (whether the club faces it); `series_wins_in_data` (postseason series won, and the last, within what the data covers) | postseason games |
| pressure_history | `postseason_record` (games and series in the data, against the regular-season win rate of the seasons the club reached October) | postseason games |
| head_to_head | `season_series` (this season's meetings, from the away club's side; game); `last_meetings` (the last three; game) | every game |
| availability | `probable_rest` (days since each probable starter's last listed start, and his starts in the last 30 days); `starters_previous_round` (who the schedule listed in each of the club's previous-round games) | every game; the second in the postseason |
| venue | `park`, `roof` (game) | every game |

A **stale** store is not silently wrong: if the days between the store's newest game and this one are
not all confirmed fetched (the ingest manifest, or more than three days without one), the facts that
depend on the last few days (rest, form, the series score, who started) are left out and listed, with the
dates. The long-memory facts are kept.

**An early postseason is not a drought we can name.** "First series win since YEAR" is only stated as far
back as the data goes (`series_wins_in_data` says "in our data (2015 on)" with the display-only history, or
"2023 on" without it); a longer drought is simply not said.

### UFC (`src/situation/ufc.py`)

Reads only the UFC data layer through its public functions (`features_as_of`, `completed_fights`,
`matchup.previous_meetings`, `matchup.shared_opponents`), which already admit only bouts that started
strictly before the as-of instant and have a result. Adds no statistic of its own.

| Family | Factors | Notes |
|---|---|---|
| rest_and_rhythm | `days_since_last_fight` (named a short turnaround at 35 days or fewer and a long layoff at 365 or more); `fights_last_365_days` | the sentence says where the data begins when the year before the bout is not all in the store |
| form | `streak`; `recent_finishes` (finishing wins, decision wins and finishing losses in the last five); `opponent_quality_trend` (the last three opponents' win rate going into each fight, against the earlier ones) | the trend is a gap when too few opponents have a record in the data |
| stakes | `title_bout`; `card_position` (main event or bout number, segment, scheduled rounds) | `title_bout` is a gap when the schedule does not say |
| pressure_history | `main_event_record` (main events and title fights on file) | |
| head_to_head | `previous_meeting`; `common_opponents` | |
| availability | `weight_class_change` (up, down, same or changed, from the last fight's class to this bout's) | |

## 3. What the data could not support (listed in every record's `missing` where it matters)

- **MLB:** managers and their postseason records; injuries, pitch counts and bullpen use (the packet's
  own bullpen section covers recent relievers); what a regular-season game is worth in the playoff race;
  the market's side and line movement; any fact older than the results store (2023-03-30) unless the
  display-only history is supplied (2015 on, postseason only); who actually started (the store holds the
  starter the schedule listed).
- **UFC:** short notice, missed weight, injuries and camp news are not in the data layer and are listed
  as missing, never inferred; rankings; a fighter's counts cover only the UFC fights in the store (it
  begins 2024-01-13), so a fighter with two fights on file may have fought twenty.
- **The market columns of the plan** (public favourite, line move) are not built: no price enters the
  situation record. Nothing in this layer reads, sets or moves a price.
- **A drought older than the data.** Each postseason record carries a `milestone_before_data` gap: how
  long since a club won a series is stated only back to the earliest season held.
- **Neutral-site games.** Travel is the distance between the two home clubs' parks. A game played away
  from the home club's park (an opening series abroad, a one-off in a minor-league ballpark) is read as
  played at the home club's park, so the miles after it are only as good as that assumption.

## 4. How the analyst reads it

`packet.build_packet(..., situation=record)` (and `ufc_packet.build_packet`) adds `sections.situation`
(`{as_of, as_of_basis, values}`) and changes the packet's version to `analyst_packet_v1_situation`.
`values.factors` is nested `family.name.side`, so a path reads like a sentence:

```
sections.situation.values.factors.rest_and_rhythm.previous_round.home.value
sections.situation.values.factors.form.last_10.away.detail.wins
```

`values.missing` lists the gaps, `values.coverage` where the data starts and whether the store is
current, and `values.how_to_read` says how to read a factor. The packet's top-level `missing` is the same
in both arms, so arm B is arm A plus the section and nothing else.

The prompt adds one section before its closing line (arm A's every rule is arm B's, word for word, and the
new rules take the next numbers: MLB 17 to 20, UFC 23 to 26). Verbatim, MLB:

```
THE SITUATION
17. `sections.situation` is the situation around this game: rest and rhythm, form, stakes, how each club has fared in October, head to head, who started and who is available, and where the game is played. Each fact has a value, the sample behind it, its date and a sentence. It is drawn only from games before this one. `sections.situation.values.missing` lists what the data could not say; never make a claim that rests on something listed there, and never guess it.
18. Weigh the situation next to the statistics, not above them. A situation fact moves your estimate only when it is large and its sample is not thin, and the sample is in the fact. In the postseason every sample is small, the statistics' included, so the situation can matter more there than in April, but a small sample is still small: say how small. A stretch of five or ten games is a description, not a trend.
19. Every situation claim cites its path in the packet like any other claim, for example sections.situation.values.factors.form.last_10.home.value. Quote the numbers as the packet writes them and do no arithmetic on them. Do not name a streak, a series, a drought or a record that is not in the packet.
20. The price may already include the story the situation tells. A fact everyone knows (a hot club, a club that just won a series, a bye) is more likely to be in the price than a fact few look at. If your estimate departs from the books because of a situation fact, say what that fact adds that the price does not already hold; if you cannot, it is not a reason to depart.
```

UFC:

```
THE SITUATION
23. `sections.situation` is the situation around this bout: layoff and turnaround, form, the card slot, the record in main events and title fights, the previous meeting and weight class. Each fact has a value, the sample behind it, its date and a sentence, and is drawn only from fights before this one. `sections.situation.values.missing` lists what the data could not say. Short notice, missed weight, injuries, camp news and rankings are never in the packet: never claim one, and never make a claim that rests on something listed as missing.
24. Weigh the situation next to the statistics, not above them. Fighters have a handful of fights in the data, so a situation fact rests on very little: read its sample, and let a layoff, a streak or a card slot move your estimate only when it is large and the sample is not thin.
25. Every situation claim cites its path in the packet like any other claim, for example sections.situation.values.factors.rest_and_rhythm.days_since_last_fight.a.value. Quote the numbers as the packet writes them and do no arithmetic on them. Do not claim a streak, a meeting or a record that is not in the packet.
26. The price may already include the story the situation tells. A fact everyone knows (a long layoff, a title fight, a winning streak) is more likely to be in the price than a fact few look at. If you depart from the books because of a situation fact, say what that fact adds that the price does not already hold; if you cannot, it is not a reason to depart.
```

(`tests/test_situation_docs.py` pins that these are the prompt text in the code.) Prompt versions:
`analyst_prompt_v1_situation`, `analyst_ufc_prompt_v1_situation`. The critic is arm A's, unchanged: a
claim that cites a situation path and quotes its number or its names verifies, and a wrong value is struck.

## 5. The side-by-side test

**Two analysts on the same games.** Arm A reads the matchup statistics (the analyst as it has always run).
Arm B reads the same packet plus the situation section and the same prompt plus the section above: same
model, schema, effort, critic and grading. Each is frozen before the game into its own ledger and graded
the same way, from the same results.

| | Arm A | Arm B |
|---|---|---|
| MLB ledger | `evidence/analyst_v1.jsonl` | `evidence/analyst_v1_situation.jsonl` |
| UFC ledger | `evidence/analyst_ufc_v1.jsonl` | `evidence/analyst_ufc_v1_situation.jsonl` |
| cost logs, frozen packets | `analyst_usage_v1.jsonl`, `analyst_packets_v1/` (and the UFC ones) | the same names with `_situation` |
| row | unchanged (no `arm` key) | `arm: "B"`, `situation_version`, its own prompt version, hash and packet version |

**Arm A is untouched.** Its prompts, its packets (no `situation` key, the same version and hash) and its
ledger rows are byte for byte what they were: `tests/test_situation_analyst.py` pins the hashes of both
prompts and both packets, computed from the previous commit's own source, and checks that the written
read's Situation block cannot reach arm A's packet.

**How to switch arm B on.** `config/analyst.json`:

```json
"situation_arm": {"enabled": true}
```

Off (the shipped default): `analyst run` runs arm A only, exactly as before. On: every `analyst run`
(including the daily job's step) also runs arm B, game by game: A then B for the same game, so the two
are frozen minutes apart, and a game that starts between them is refused by B as it would have been by A.
`--arm A`, `--arm B` or `--arm both` overrides the switch for one run. Grading is automatic for both
ledgers when arm B's exists (`analyst grade`), and `analyst record --arm B` prints arm B's record.
The spend cap is shared by both arms (one meter), so a run still cannot pass it. With no key, nothing is
built, sent or written for either arm.

**The comparison.** `python -m src.cli analyst compare [--sport mlb|ufc|all] [--json]` reads the two
ledgers and reports, per sport and market family: calls, bets and passes, results (W-L-P, voids,
unresolved), units at the published prices, calibration of the bets (Brier score, mean estimate against
actual rate), how often the arms said the same thing on a slot, and the cost of the paired games.
- **Only games both arms froze are compared**, and the report says how many were left out and why.
- **Rates are withheld under 30 graded calls per family**, for each arm separately (a win rate, units,
  units per call and calibration are null until then); the difference between the arms is shown only when
  both arms clear the bar. Counts are always shown.
- It refuses a file given as arm B that holds rows not marked arm B.

**Cost.** Arm B is a second call per game with a larger input. Measured on real games and a real bout
with `src/situation`: the situation section is about 8,000 characters (2,500 tokens) for a regular-season
MLB game, about 12,300 (3,800 tokens) for a postseason game and about 7,000 (2,150 tokens) for a UFC bout;
the prompt section adds about 1,570 characters (490 tokens). That is 3,000 to 4,300 more input tokens per
MLB game and 2,650 per bout, about $0.006 to $0.009 at $2 per million, plus more reasons to write (an
estimate: 10 to 25 percent more output, $0.006 to $0.015). **Arm B costs about $0.09 to $0.13 a game against
arm A's $0.08 to $0.11 (`docs/AI_ANALYST.md`), so turning it on roughly doubles the analyst:** about $0.17
to $0.24 a game for both, $2.60 to $3.60 for a fifteen-game day (arm A alone: $1.20 to $1.70), about $75 to
$110 for a month of slate days. UFC: about $0.06 to $0.10 a bout for B, $0.11 to $0.19 for both, $1.50 to
$2.70 for a 14-bout card, about $7 to $13 a month at four or five cards (arm A alone: $3 to $6). These are
estimates until the first measured day; the cost logs record the real tokens, and `analyst compare` prints
the measured cost of the paired games. The console spend limit the owner sets (`docs/decisions/AI_ANALYST_ENABLE.md`)
should be raised to cover both arms before the switch is turned on.

## 6. The first historical test: rest versus rhythm in the Division Series

`docs/research/SITUATION_REST_VS_RHYTHM_DIVISION_SERIES.md`, pre-registered (the hypothesis, the sample of
28 series, the yardstick and the decision rule were committed before any outcome was read) and then run:
**a null.** Across 28 Division Series 2015 to 2025 where one club had a bye and the other played the Wild
Card round, the bye clubs won Game 1 in 19 of 28 (16.4 expected from their records and home field,
p = 0.41) and the series in 15 of 28 (17.1 expected, p = 0.52); a sample that size could only have seen a
swing of about 18 points a series, so it cannot rule out a smaller effect either way. No series has a
market price: our closing moneylines exist for 2026 only. Commands:

```
python3 -m src.cli situation ingest-postseasons --start 2015 --end 2025
python3 -m src.cli situation rest-vs-rhythm
```

## 7. The display-only store of earlier postseasons (`src/situation/postseason_history.py`)

Postseason games from MLB's free Stats API, 2015 to 2025 (440 games), and each club's final regular-season
record from the standings (330 rows), in `data/research/postseason_history/` (tracked: it is small, and an
ephemeral container would lose a download). **Never a training population:** it is not under
`data/historical/`, nothing in `src/pipeline` imports it (a test reads the pipeline's source to prove it),
`features.build_training_table` keeps its regular-season default, and the ingest writes only its own
directory. It is fetched politely (a pause between requests, cached under `data/raw/`). The parser was
checked against the results store: all 131 postseason games of 2023 to 2025 match on date, clubs, round and
both scores. A first run asked the standings for a date and got nothing on off days; the request now
carries no date and a test pins it.

## 8. Where it shows

One short **Situation** block (up to six plain sentences, each with its sample in the words, an evidence
toggle, and a foldout of what the situation could not say) in the MLB written read (`read.situation`, from
`payload.situation`, between the factors and the expected runs) and in the UFC fight-night read
(`read.situation`, from the bout's `situation`, after the history and before the price). The block is its own
key and is only present when a record is handed in: a read built without one is exactly the read it always
was, and a record that cannot be built costs the block, never the page. The record rides beside the dossier,
not inside it (a dossier section feeds the card's model and arm A's packet). No sentence says anything
about EQ, momentum as a force, or a price being wrong.

## 9. Tests

`tests/test_situation_record.py`, `test_situation_series.py`, `test_situation_mlb.py`,
`test_situation_ufc.py` (every factor's arithmetic on hand-checked worlds, point in time, gaps, sentence
numbers), `test_situation_analyst.py` (arm A pinned, the prompts, the packets, the arms' files and rows, the
switch, the shared meter), `test_situation_compare.py` (the 30-call rule, paired games, calibration by
hand), `test_situation_rest_vs_rhythm.py` and `test_situation_history.py` (the yardstick against brute
force, the pairing, the ingest, the walls), `test_situation_display.py` (the blocks, the JS under node, the
wording sweeps), `test_situation_routes.py` (the two routes, fail soft), `test_situation_docs.py`. All are
offline. The wording sweeps `test_customer_language`, `test_web_register_sweep` and
`test_no_developer_notes_on_screen` stay green.
