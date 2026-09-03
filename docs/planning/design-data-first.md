# LINEHOUND — DATA-FIRST ARCHITECTURE

**Author:** independent architect pass, 2026-09-03.
**Angle:** the store is the primary artifact. Start from the universal record —
MARKET / SELECTION / LINE / PRICE / BOOK / TIMESTAMP, plus the decision-time
information snapshot — design the layout that holds millions of decisions, price
the credit economics of the full board, and let the engine, the factory and the
product be *readers* of that record rather than owners of their own shapes.
**Status:** design. Nothing in this document is evidence. Every factual claim
cites a file, a line, a store, or a count measured during this pass. Nothing was
written to any store or any source file by this pass; the only file created is
this one.

**Standing constraints, load-bearing throughout, never relaxed:** point-in-time
integrity is sacred; 2025 is tuning-only; sealed 2026 is untouched for research
reads; losers are published; no real-money bet placement; never fabricate; price
improvement is never EV and never edge; the Ranker publishes nothing while
`ENGINE2 is None` until the unlock gates clear **and** the owner signs off.

Sibling passes: `docs/planning/design-engine-first.md` (starts from the decision
function) and `docs/planning/design-factory-first.md` (starts from the research
department). This pass deliberately starts one layer below both of them. Where
the three agree — one pure decision function, one board object, deterministic
evaluation, no model in the decision path — the agreement is not coordination,
it is three readings of the same codebase arriving at the same waist. Where this
pass differs, it differs about *what has to be true of the bytes on disk before
that waist can exist at all*, and it reaches one conclusion neither sibling
reaches: **most of the board cannot be backtested, ever, and the roadmap must be
built on that fact rather than around it** (§15.3).

---

## 0. THE ARCHITECTURE IN ONE PARAGRAPH

Everything the system will ever know arrives as one of four record types:
a **PriceObservation** (one book's quote on one selection at one instant), an
**InformationEvent** (one fact about the world that became knowable at a stated
time, with a stated grade of how well we know *when*), a **DecisionRecord** (what
some engine version recommended, at what price, at which book, on what evidence,
against what counterargument), and a **Settlement** (what happened, written
later, in a partition the decision path is structurally unable to open). Those
four shapes are written once, append-only, in a raw immutable layer; projected
deterministically into a canonical layer; compiled into content-addressed binary
frames for search; and read for any decision through exactly one function,
`as_of(T)`, which cannot return a byte whose `known_at` is later than `T`. The
decision engine, the strategy factory, the daily loop, the backtest, the Bet
Rating and the product are all consumers of those four shapes and that one
reader. The board expands by adding rows, never by adding schemas. Decisions at
the scale of millions are not stored, they are *reproduced* — determinism is the
compression algorithm.

---

## 1. THE ONE FINDING THAT DRIVES THIS WHOLE DOCUMENT

The repository is one market wide not because the board is expensive, and not
because the code is hard to extend, but because **the price record has only two
fields for prices**.

`home_price` / `away_price` is baked into, at minimum:

- `src/pipeline/snapshots.py:168-192` — `multibook_rows()` emits
  `{home_price, away_price}` and hardcodes `all_books["h2h"]`.
- `src/pipeline/dense.py:88` — `F5_CLOSE_MARKET = "h2h_1st_5_innings"`, one key.
- `src/evolab/replay.py:180-184` — `QUOTE_FIELDS = ("book", "snapshot_at",
  "gap_minutes", "away_price", "home_price")`, described in its own comment as
  an allowlist, which is correct discipline applied to the wrong shape.
- `src/evolab/replay.py:146` — `MARKETS_SERVED = ("h2h",)`.
- `src/evolab/feed.py` — the consensus row is a five-tuple of two-way fairs and
  two-way prices.
- `src/analysis/prices.py` — `_fair()` is two-way de-vig only.
- `src/analysis/oddspayload.py:58` — `MARKETS = ("h2h",)  # the only market today`.
- `src/analysis/betcheck.py:93-113` — `UNSUPPORTED_MARKETS` refusals.

A two-way price pair cannot express a total (it has a *line*), an alternate (it
has *many* lines), a team total (it has a *subject*), a player prop (it has a
*subject* and a *line*), or a derivative (it has a different *settlement rule*).
Every "add market X" task in this repository is currently a schema migration in
eight places wearing the costume of a feature request. That is why F5 has been
schema-legal since Phase 1 and never fed; why `normalize_event`
(`src/providers/odds.py:609-629`) builds `all_books` for **six** market keys on
every single capture and `multibook_rows` persists **one** of them; and why the
historical store's totals data has never been read by anything.

Measured this pass, directly, from `data/historical/odds_history/*.jsonl`:

| Season | Snapshots | Event-snapshots | h2h market rows | **totals market rows** | Distinct books |
|---|---|---|---|---|---|
| 2023 | 600 | 11,167 | 133,330 | **123,224** | 19 |
| 2024 | 600 | 10,310 | 93,724 | **90,534** | 14 |
| 2025 | 600 | 10,540 | 90,458 | **88,513** | 11 |

Three hundred thousand totals quotes, with points, across up to nineteen books,
paid for, on disk, in the raw layer, for the two discovery seasons and the tuning
season — **read by nothing**. `replay.MARKETS_SERVED` says `("h2h",)` and its own
comment explains why: "the historical store holds h2h and totals ... and F5 is
~290 games at one observation each". The h2h half of that sentence is a real
constraint; the totals half is a decision not to build a second projection.

That is the data-first thesis in one paragraph: **the raw layer already holds the
universal record — outcome name, point, price, book, `last_update` — and it is
the normalization step that throws it away.** Fix the record and the board
expansion stops being eight migrations and becomes a `for` loop, a settlement
rule, and a credit line item.

---

## 2. THE UNIVERSAL RECORD

New package `src/board/`. Pure data and pure functions; no network, no clock, no
global state. Enforced by the same grep-guard style the project already uses.

### 2.1 Market and selection identity — `src/board/ids.py`

The identity problem must be solved before anything else, because it is what
makes the store queryable and the ledger joinable across five years and four
sports.

```python
# src/board/ids.py

SPORT_MLB = "mlb"

# --- market family: WHAT is being priced, independent of who/where ---------
# Canonical, versioned, exhaustive. A key not in this catalogue cannot be
# written to the store; adding one is a reviewed change with a settlement
# rule attached (see 2.4). The provider's own key is a SEPARATE field.
MARKET_CATALOGUE = {
    # key                      scope        shape         settlement rule
    "ml":                     ("game",     "two_way",    "TEAM_WIN"),
    "run_line":               ("game",     "handicap",   "TEAM_WIN_MARGIN"),
    "total":                  ("game",     "over_under", "GAME_TOTAL_RUNS"),
    "team_total":             ("game",     "over_under", "TEAM_TOTAL_RUNS"),
    "margin":                 ("game",     "bucket",     "TEAM_WIN_MARGIN_BUCKET"),
    "ml_f5":                  ("f5",       "two_way",    "TEAM_LEAD_AFTER_5"),
    "run_line_f5":            ("f5",       "handicap",   "TEAM_MARGIN_AFTER_5"),
    "total_f5":               ("f5",       "over_under", "TOTAL_RUNS_THROUGH_5"),
    "team_total_f5":          ("f5",       "over_under", "TEAM_RUNS_THROUGH_5"),
    "total_f1":               ("f1",       "over_under", "TOTAL_RUNS_INNING_1"),
    "ml_f1":                  ("f1",       "two_way",    "TEAM_LEAD_AFTER_1"),
    "p_strikeouts":           ("player_p", "over_under", "PLAYER_STAT:SO"),
    "p_outs":                 ("player_p", "over_under", "PLAYER_STAT:OUTS"),
    "p_hits_allowed":         ("player_p", "over_under", "PLAYER_STAT:H_ALLOWED"),
    "p_earned_runs":          ("player_p", "over_under", "PLAYER_STAT:ER"),
    "p_walks":                ("player_p", "over_under", "PLAYER_STAT:BB_ALLOWED"),
    "b_hits":                 ("player_b", "over_under", "PLAYER_STAT:H"),
    "b_total_bases":          ("player_b", "over_under", "PLAYER_STAT:TB"),
    "b_home_runs":            ("player_b", "over_under", "PLAYER_STAT:HR"),
    "b_rbi":                  ("player_b", "over_under", "PLAYER_STAT:RBI"),
    "b_runs":                 ("player_b", "over_under", "PLAYER_STAT:R"),
    "b_walks":                ("player_b", "over_under", "PLAYER_STAT:BB"),
    "b_strikeouts":           ("player_b", "over_under", "PLAYER_STAT:SO"),
    "b_stolen_bases":         ("player_b", "over_under", "PLAYER_STAT:SB"),
    "b_hits_runs_rbis":       ("player_b", "over_under", "PLAYER_STAT:H+R+RBI"),
    "first_to_score":         ("game",     "two_way",    "TEAM_SCORES_FIRST"),
    "race_to_runs":           ("game",     "two_way",    "TEAM_REACHES_N_FIRST"),
}

def selection_id(*, sport, market_key, side, subject=None, line=None,
                 line_side=None) -> str:
    """Stable 16-hex identity for one bettable thing.

    side     : "home" | "away" | "over" | "under" | "yes" | "no" | bucket label
    subject  : None for team-level; ("player", mlb_id) or ("team", tricode)
    line     : Decimal-as-string, e.g. "-1.5", "8.5", "6.5"; None where the
               market has no line.
    Canonical tuple -> sha256 -> first 16 hex. NEVER a hash of a display string,
    because display strings change and identities may not.
    """

def market_shape(market_key) -> str: ...
def settlement_rule(market_key) -> str: ...
def is_derivative(market_key) -> bool: ...
```

Two properties matter and both are structural, not conventional:

1. **A line is part of the selection, not a modifier on it.** `total|over|8.5`
   and `total|over|9.0` are two selections, not one selection at two prices.
   Alternate totals are then not a new market family at all — they are more rows
   of `total`. That single decision collapses "alt run lines, alt totals,
   alternates" from three build items to zero.
2. **Subject is a first-class field.** Team totals, pitcher props and batter
   props differ from game markets only in `subject`. That collapses another six
   build items to a catalogue entry plus a settlement rule.

### 2.2 PriceObservation — `src/board/record.py`

```python
@dataclass(frozen=True, slots=True)
class PriceObservation:
    # --- identity -------------------------------------------------------
    sport: str                  # "mlb"
    event_id: str               # provider event id
    game_pk: int | None         # MLB id when joinable; None is honest
    market_key: str             # MARKET_CATALOGUE key
    selection_id: str           # ids.selection_id(...)
    side: str
    subject_kind: str | None    # None | "player" | "team"
    subject_id: str | None
    line: str | None            # decimal string, exact, never float
    # --- the quote ------------------------------------------------------
    book: str
    price_american: int
    # --- time, three distinct clocks, never conflated -------------------
    observed_utc: str           # when WE saw it (our capture clock)
    book_last_update: str | None  # when the BOOK says it changed
    known_at: str               # earliest instant a decision may use it
    known_at_grade: str         # "A" | "B" | "C" | "D"  (see 2.5)
    # --- provenance -----------------------------------------------------
    capture_id: str             # ties every row of one API call together
    source: str                 # "oddsapi.featured" | "oddsapi.event" | ...
    region: str                 # "us"
    provider_market_key: str    # the vendor's own key, kept verbatim
    is_close: bool = False      # closing snapshots live in the sealed partition
```

Notes that are load-bearing:

- **`line` is a string, not a float.** `8.5` round-trips fine; `-1.5` and `+1.5`
  do not always compare equal after a float detour, and a selection identity that
  depends on IEEE754 is a bug that surfaces three seasons later as a join miss.
- **No `home_price`/`away_price` anywhere.** A two-way market is two rows.
  Symmetry is recovered at read time by the frame builder, not baked into disk.
- **`price_american` only.** Decimal and implied probability are *derived* and
  belong in `src/core/odds_math.py`, which already exists. Storing derived
  numbers next to raw ones is how stores start disagreeing with themselves.
- **`is_close` is not a flag the reader may ignore.** Rows with `is_close=True`
  are written to a different directory (§4.3) and `as_of()` cannot open it.

Storage cost, measured against the real shapes on disk: a canonical row
serializes to ~200 bytes of JSONL, ~118 bytes in the binary frame format (§4.4).

### 2.3 InformationEvent — `src/knowledge/event.py`

Everything that is not a price. The vision's whole first paragraph — starters,
bullpen, offense, player context, environment — is this one record type with a
`kind` and a payload.

```python
@dataclass(frozen=True, slots=True)
class InformationEvent:
    sport: str
    scope: str            # "game" | "team" | "player" | "park" | "league"
    scope_id: str         # game_pk | tricode | mlb_id | park code
    kind: str             # "probable_pitcher" | "lineup_posted" | "il_placement"
                          # | "weather_forecast" | "umpire_crew" | "roster_move"
                          # | "statcast_window" | "boxscore_final" | ...
    payload: dict         # kind-specific, validated per kind
    # the three clocks again
    happened_utc: str | None   # when the WORLD changed, if the source says so
    known_at: str              # earliest instant a decision may use this
    known_at_grade: str        # "A" | "B" | "C" | "D"
    observed_utc: str          # when WE fetched it
    source: str                # "mlb.schedule" | "openmeteo.archive" | ...
    capture_id: str
```

This subsumes six stores that exist today in six shapes:
`lineups.jsonl` (4,892 rows), `transactions.jsonl` (27,053 rows, wired into
nothing), `bullpen_log.jsonl` (64,898), `pitcher_logs.jsonl` (42,960),
`weather_forecast.jsonl` (23), `data/watch/*.jsonl` (865, ~60% poll markers).
They are not rewritten — they are the raw layer (§4.1) and stay exactly as they
are — they are *projected* into this shape by a deterministic adapter per store.

### 2.4 Settlement rules are data, not code branches

`src/board/settle.py` holds a table, not an `if` ladder:

```python
SETTLEMENT_RULES = {
  "TEAM_WIN":            Rule(needs=("final_score",),        source="mlb_results.csv"),
  "GAME_TOTAL_RUNS":     Rule(needs=("final_score",),        source="mlb_results.csv"),
  "TEAM_WIN_MARGIN":     Rule(needs=("final_score",),        source="mlb_results.csv"),
  "TOTAL_RUNS_THROUGH_5":Rule(needs=("f5_score",),           source="first_five_results.jsonl"),
  "PLAYER_STAT:SO":      Rule(needs=("boxscore_pitching",),  source="mlb.gumbo"),
  "PLAYER_STAT:TB":      Rule(needs=("boxscore_batting",),   source="mlb.gumbo"),
  "TOTAL_RUNS_INNING_1": Rule(needs=("linescore_by_inning",),source="mlb.gumbo"),
  "TEAM_SCORES_FIRST":   Rule(needs=("play_by_play",),       source="mlb.gumbo"),
  ...
}
```

**Gate G3, and it is absolute: a market family may not be switched on for paid
collection until its settlement rule exists, its result source is fetchable, and
a test grades ten historical or synthetic examples correctly.** Collecting prices
for a market we cannot settle produces an expensive store that can never become
evidence. This gate is cheap to satisfy — MLB's free GUMBO feed carries boxscore,
linescore-by-inning and play-by-play, and `first_five_results.jsonl` (2,512 rows)
already proves the pattern for F5 — and it is the difference between a board and
a shelf of unopened boxes.

### 2.5 `known_at` and the grade ladder — the leakage control that lives in the schema

This is the single most important field in the design, and it exists because of
a finding this repository already made against itself.

`docs/AUDIT_PROBABLE_PITCHER_PIT.md` establishes that the stored probable pitcher
agrees with the actual first-pitch thrower 99.90% (2023, 4,859 sides) and 99.92%
(2024, 4,852 sides) — 12–41× cleaner than a plausible scratch rate — and
`src/model/pointintime.py` nonetheless marks the input CLEAN, because CLEAN in
that registry means "cutoff-respecting accumulation", not "was knowable at T".
The audit itself flags the distinction as "not yet encoded anywhere in the
registry". Nine downstream features inherit the gap.

Encode it. Every row of both record types carries:

| Grade | Meaning | Example on disk today |
|---|---|---|
| **A** | The source states the instant the fact became public. | `book_last_update` on a quote; MLB feed `fetched_utc` on a state that changed between two polls with a known poll gap |
| **B** | Bracketed by our own polling: we know it was false at t0 and true at t1. | `rosterwatch.py` lineup/probable/transaction brackets since 2026-08; `umpirewatch.py`, verified 3.6–4.6h pre-pitch |
| **C** | Date-only. We know the day, not the instant. | 2023-24 `lineups.jsonl` — **zero** games carry a posting time |
| **D** | Assumed by convention, with the convention named and versioned. | the T-180 lineup-posting assumption (`replay.py:139`); the 2023-24 probable-pitcher identity |

Rules, enforced in `src/knowledge/asof.py`:

1. `as_of(T)` returns a row only if `known_at <= T`.
2. Grade C and D rows are **excluded by default**. A caller that wants them must
   pass `allow_grades={"C","D"}` explicitly, and the exposure is then stamped onto
   every artifact the run produces: `assumption_exposure={"D:probable_pitcher":
   4188, "D:lineup_T180": 3624}`. An artifact without that stamp is invalid.
3. A grade may only ever be *lowered* by an audit, never raised, and the change is
   an append-only row in a `grade_audit.jsonl` with a reason and a commit.

Two consequences fall out that the project currently has to remember by hand:

- The Phase 2B result's real exposure ("every genome's decision rests on a
  starter identity of grade D") becomes a printed number rather than a caveat in
  a markdown file that a future reader may not open.
- The forward 2026 season is grade A/B for exactly the classes `rosterwatch` and
  `umpirewatch` cover, and that is *the difference in kind* the owner is paying
  for when he calls the live season precious. It becomes measurable: "% of
  decision-relevant facts at grade A or B" is a store health metric, reportable
  daily, and it is ~0% for 2023-24 and should be >90% for 2026.

### 2.6 DecisionRecord — `src/ledger/decision.py`

The forward ledger's shape is good and its rule set is not. It has
`information_time` distinct from write time (`ledger.py:104-109`), append-only,
settlement never mutating the recommendation — all correct and all worth keeping.
What it lacks is everything the vision asks a recommendation to carry, and it has
one rule that structurally forbids the vision: **one row per game, ever**
(`ledger.py:62-79`), which makes it impossible to record that the verdict changed
when the lineup posted.

```python
@dataclass(frozen=True, slots=True)
class DecisionRecord:
    # --- what decided ---------------------------------------------------
    engine_version: str          # e.g. "engine.2.0.0"
    system_id: str               # the strategy/genome/detector-set identity
    system_generation: int | None
    registry_fingerprint: str    # signal registry version hash
    frame_fingerprint: str       # exact bytes the BoardView was built from
    # --- when it decided ------------------------------------------------
    game_pk: int | None
    event_id: str
    decision_utc: str            # T: the decision timestamp
    point_class: str             # "T_MINUS_6H" | "POST_LINEUP" | "T_MINUS_30M" ...
    # --- what it decided ------------------------------------------------
    verdict: str                 # "play" | "no_play" | "market_unavailable"
                                 # | "refused_leakage" | "refused_thin"
    selection_id: str | None
    market_key: str | None
    line: str | None
    book: str | None             # the book the price came from — REQUIRED for play
    price_american: int | None   # the executable price at T — REQUIRED for play
    consensus_fair: float | None # no-vig consensus at T
    books_at_decision: int | None
    # --- why --------------------------------------------------------------
    p_hat: float | None          # model probability, if the system produces one
    p_hat_interval: tuple | None
    edge_bps: int | None         # (p_hat - fair) in basis points; NEVER price improvement
    price_improvement_bps: int | None  # separate column, separate meaning, §15.8
    rating: str | None           # Bet Rating class, §14
    rating_inputs: dict | None   # every number that produced the rating
    findings: list               # src/detect/base.Finding shapes — evidence
    counterarguments: list       # NEW and required for any "play"
    supporting_systems: list     # other system_ids that concur, with their ids
    refusal_reason: str | None
    # --- provenance ---------------------------------------------------------
    assumption_exposure: dict    # grade C/D counts this decision leaned on
    information_time: str        # inputs gathered at
    recorded_utc: str            # written at
```

Changes from today's ledger, each with its reason:

- **Multi-snapshot per game.** Dedup key becomes
  `(engine_version, system_id, game_pk, point_class)`, not `game_pk`. A verdict
  at T-6h and a different verdict after the lineup posts are two facts and the
  vision requires both. The current rule was written to fix a real bug — five
  identical recommendation sets on 08-30 — and the fix should be idempotency on
  the full key, not one-row-per-game.
- **`book` and `price_american` required on a play.** Today's 144 recommendation
  rows have neither. A recommendation without an executable price at a named book
  is not gradeable against a close and cannot ever count toward the 300-selection
  unlock condition.
- **`counterarguments` required and non-empty for a play.** Structurally
  enforced, the same way `Finding` already refuses to emit a signal without a
  baseline (`src/detect/base.py`). A system that cannot name what would make it
  wrong has not analyzed anything.
- **`system_id` present.** "Many competing analysis systems" is unrepresentable
  in a ledger with no system field.
- **`price_improvement_bps` separate from `edge_bps`,** with a test that fails if
  any code path sums them or writes one into the other. The standing constraint
  becomes a schema invariant instead of a rule people remember.

### 2.7 ReviewRecord — the self-review as data

```python
@dataclass(frozen=True, slots=True)
class ReviewRecord:
    decision_key: tuple        # joins DecisionRecord exactly
    review_utc: str
    settled: str               # "win" | "loss" | "push" | "void" | "unsettled"
    thesis_held: str           # "yes" | "no" | "unknowable"
    thesis_note: str           # plain language, one paragraph, no numbers invented
    variance_flag: bool        # right process, wrong outcome (or vice versa)
    market_moved: str          # "toward" | "away" | "flat" | "unpriceable"
    closing_price: int | None
    clv_bps: int | None
    late_information: list     # lineup/bullpen/weather events after decision_utc
    missed_information: list   # facts that existed at T and the engine did not read
    system_action: str | None  # "promote" | "demote" | "retire" | "none"
    new_hypothesis: str | None # free text, queued for registration, never auto-run
```

The end-of-day self-review is currently prose in `docs/OVERNIGHT_RUN.md`. Prose
cannot be joined, counted, or fed back to the factory. As a record it can:
"how often was the thesis right and the bet wrong" becomes a query, and
`missed_information` becomes the highest-value feature-request queue in the
project, generated by the system's own failures rather than by brainstorming.

---

## 3. RECONCILIATION — the vision against the bytes (Q1)

Read from the store's vantage: for each thing the vision names, is there a byte
on disk, in what shape, at what grade, and can it be recovered if it is missing.

### 3.1 The information snapshot

| Vision names | Bytes on disk | Grade | Verdict |
|---|---|---|---|
| Starter ERA/WHIP/FIP-ish, K%/BB%, arsenal, velocity, recent outings, workload | `data/historical/statcast/` 2,737,968 pitch rows over 180 windows, 2023-03-30..2026-08-27; `pitcher_logs.jsonl` 42,960 rows; rebuilt point-in-time by `src/pipeline/rebuilt.py`, tested CLEAN | A for the pitches, **D for the starter's identity** | **EXISTS, strong.** The hard problem (cutoff-respecting accumulation from pitch level) is solved |
| Starter identity at T | `*_probable_id`, 99.90%/99.92% agreement with the actual thrower | **D** | **BELIEVED-BUT-ABSENT.** Not repairable; no source exists and none can be bought (`AUDIT_PROBABLE_PITCHER_PIT.md:284-289`). Must become a printed exposure, not a caveat |
| TTO | approximated, not measured (`RESEARCH_V6_CANDIDATES.md` C5) | — | **PARTIAL**; the pitch store can support a real measurement |
| Days rest, workload | derivable from `pitcher_logs.jsonl` + `bullpen_log.jsonl` | A/B | **EXISTS as raw, ABSENT as feature** |
| Bullpen availability, leverage, closer, handedness | `bullpen_log.jsonl` 64,898 per-appearance rows | A (post-hoc), C for *availability at T* | **PARTIAL — raw only.** Availability at T needs yesterday's usage as of T, which the raw log supports and no feature computes |
| Offense splits vs LHP/RHP, platoon, K/power/contact | rebuilt from Statcast, 7 numeric features in `matrix.py:228-297` | A | **PARTIAL** |
| Confirmed lineup | `lineups.jsonl` 4,892 rows | **C historically (zero posting times), B forward** | **ABSENT historically, EXISTS forward.** Unrepairable for 2023-24 |
| Injuries / IL / roster moves | `transactions.jsonl` **27,053 rows**, 2022-04-08..2026-09-01, incl. 1,768 IL placements + 2,554 activations across 2023-24 | B/C | **EXISTS AND UNUSED.** Referenced only by `coverage.py`, `news.py`, `rosterwatch.py`. Highest-ROI wiring job in the repo, zero credits |
| Park, dimensions, roof, altitude | `src/data/parks.py`, static, CLEAN | A | **EXISTS.** `orientation_deg` is `None` for all 30 parks *by design*, so wind cannot be resolved in/out/cross — thirty numbers, free, one afternoon |
| Temp, wind, humidity, precip | forward `weather_forecast.jsonl` (23 rows, per-tick, non-deduped — correct shape); **no historical weather store exists at all** | A forward | **MISSING but free.** `fetch_archive` (Open-Meteo, keyless) is implemented and never called for the past |
| Umpire | `umpires_watch.jsonl` from 2026-09-02 only | B forward | **EXISTS forward only**, unrepairable historically |
| Travel, rest, day/night | derivable from `mlb_results.csv` (9,364 games) | A | **EXISTS as raw, ABSENT as feature** |

### 3.2 The market

| Vision names | Historical 2023-25 | Forward 2026 | Verdict |
|---|---|---|---|
| Book, price, timestamp | 1,800 snapshots, 32k event-snapshots, up to 19 books | `odds_multibook.jsonl` 19,791 rows, 11 books | **EXISTS** |
| Open / movement / eventual close | 3–4 pre-game instants per game, **min gap 177 min, median 6h** | hourly + 15-min dense inside T-3h; per-market close for h2h/spreads/totals; F5 close 26/73 games | **PARTIAL.** The historical spacing is a hard ceiling on decision-point granularity — it is why `replay.POINT_CLASSES` collapsed from four rungs to two |
| Disagreement, depth, stale books | `all_books` computed for **6 market keys** every capture; **1 persisted** | same | **PARTIAL — and the gap is free to close** |
| Moneyline | ✔ | ✔ | wired end to end |
| Totals | **✔ 302,271 market rows across three seasons** | fetched, `all_books` discarded | **EXISTS AND UNREAD** |
| Run line / spreads | **never polled; not purchasable** | fetched, `all_books` discarded | **historical replay permanently impossible** |
| F5 ML | 1 snapshot/game, 185/133/172 games with any book | 317 rows | **PARTIAL — too thin historically to answer a timing question** |
| F5 spreads/totals | never | **parsed by `normalize_event`, never requested** | ~1 credit/market/event on a pass that already runs |
| Alt lines | never | never (one 24-credit manual probe: 7 books, 130–160 outcome rows/event at **1 credit**) | best information-per-credit measured anywhere in this project |
| Team totals | never | never, not even probed | |
| Margin, first-inning, race-to-X, first-to-score | never | never | zero code anywhere |
| Pitcher props | never | `pitcher_strikeouts` listing 446 rows + prices 29 rows since 2026-09-02, 18 cr/day cap, 7 books | one key of a family |
| Batter props | never | never | **the largest untouched surface, and the one losing the most per day** |
| Parlays / SGP | never | never | needs a source decision before it needs code (§15.7) |

### 3.3 The decision record

| Vision names | On disk | Verdict |
|---|---|---|
| 0..N opportunities per day, whole board searched | `evidence/forward_ledger.jsonl`: 427 rows = 144 recommendation + 73 settlement + 210 closing_backfill. Of 144 recommendations: 134 no_play, 7 market_unavailable, 3 flagged, **0 selections**. `market` is null in 134 and `"first_five"` in 10 | **PARTIAL — and it cannot satisfy its own unlock gate.** Condition 3 is 300+ forward selections; the store holds zero, has no rating, no book, no price, no system id, and one-row-per-game-ever |
| Rating, evidence, counterarguments, supporting systems | `findings[]` exists and is well-shaped; rating/counterargument/system fields do not exist anywhere in `src/` | **ABSENT** |
| Settle, then bankroll accounts day by day | settlement rows exist; `settlement.closing` is **null in every sampled row**, real value in a separate `closing_backfill` row joined at read time (`grading.py:727`); no units/bankroll field anywhere in the ledger | **PARTIAL / BELIEVED-BUT-ABSENT** |
| Self-review beyond win/loss | prose in `docs/OVERNIGHT_RUN.md` | **ABSENT as data** |

---

## 4. THE STORE (Q10, storage half)

Four layers. Each layer is derivable from the one above it, and only Layer 0 is
irreplaceable. That property is what makes the whole thing safe to rebuild.

```
L0  RAW           immutable, append-only, exactly what the source said
    data/raw/<source>/<yyyy>/<mm>/<dd>/<capture_id>.jsonl[.gz]
    - verbatim provider payloads, one file per API call, plus a manifest row
    - NEVER edited, NEVER re-normalized in place, gzip after the day closes
    - the ONLY thing that must be backed up; everything below is a projection

L1  CANONICAL     the universal record, deterministic projection of L0
    data/board/prices/<sport>/<season>/<yyyy-mm-dd>.jsonl        PriceObservation
    data/board/prices_close/<sport>/<season>/<yyyy-mm-dd>.jsonl  is_close=True (sealed)
    data/knowledge/events/<sport>/<season>/<yyyy-mm-dd>.jsonl    InformationEvent
    data/knowledge/results/<sport>/<season>/<yyyy-mm-dd>.jsonl   settlement inputs (sealed)
    - one writer module per source; pure function (payload, capture_meta) -> rows
    - fully rebuildable: `python -m src.board.rebuild --season 2024` reproduces
      byte-identical output from L0, checked by a CI test on a fixture day

L2  FRAMES        compiled, content-addressed, for search
    data/frames/<fingerprint>/{header.json,cols.bin,masks.bin,prices.bin}
    - built from L1 as of a stated T-policy; named by the hash of its inputs
    - disposable: delete the directory, it rebuilds

L3  LEDGERS       what the system said and what happened
    evidence/decisions/<yyyy-mm>.jsonl      DecisionRecord   (append-only)
    evidence/settlements/<yyyy-mm>.jsonl    Settlement       (append-only, sealed)
    evidence/reviews/<yyyy-mm>.jsonl        ReviewRecord
    evidence/factory/{population,graveyard,scorecards}.jsonl
```

### 4.1 Why L0 is verbatim and never touched

The existing historical odds store is already the right shape and nobody has
noticed: `data/historical/odds_history/mlb_2023.jsonl` holds whole API responses
with `bookmakers[].markets[].outcomes[]` including `point` and `last_update`.
That is why the totals data still exists to be recovered — because the raw layer
was kept honest even though the projection was narrow. The forward stores are
*not* that shape: `odds_multibook.jsonl` and `odds_snapshots.jsonl` are already
projections, and everything the projection dropped is gone. On 2026-09-03 the
project is, right now, discarding five of six market families' book depth on
every capture and cannot get any of it back.

**Rule: capture writes L0 first, then projects. A projection bug becomes a
re-run; a capture that projects before it writes becomes a permanent hole.**

### 4.2 Partitioning, and why by day

Day partitions, not season files, for four reasons that all come from operations
rather than aesthetics: an append that crashes mid-write corrupts one day, not a
season (the existing `snapshots.append` already has a torn-line guard, which is
the same problem solved downstream); a completed day can be gzipped and
checksummed and never touched again (`scripts/archive_historical.sh` already
does gzip + SHA256SUMS and is the right pattern); the git working tree stays
small because only today's files change; and `as_of(T)` reads at most two day
files for any decision instead of scanning a season.

### 4.3 The seal, made physical

Point-in-time integrity is currently a discipline enforced inside the replay
engine (`replay.py:577` stops rather than skips at T; sealed-2026 refused by name
at `replay.py:415-439`). That is excellent and it protects one code path.

Make it a property of the filesystem layout instead:

- Anything a decision may not see lives under a `*_close/` or `results/` or
  `settlements/` directory.
- `src/knowledge/asof.py` holds a path allowlist and **cannot open** those
  directories — not "does not", cannot: the reader takes a root and refuses any
  path not under it, and there is a test that tries.
- `src/factory/**` and `src/engine/**` may not import `src.board.store` directly,
  only `src.knowledge.asof`. Enforced by an import-guard test in the same style
  as the existing stdlib-only and network-block CI guards.

Then "no future leakage" stops depending on every future author remembering, and
starts depending on a directory an import cannot reach.

### 4.4 L2 frames: stdlib-only columnar, and why DuckDB is the wrong question

The repository is **stdlib-only and CI enforces it** — `.github/workflows/tests.yml`
fails the build if `requirements.txt` exists. So the DuckDB/Parquet/numpy
conversation, which `MASTER_PLAN.md:846-851` correctly deferred, is not merely
deferred: it would require breaking an invariant the project has chosen to keep.

It also does not need to happen, because the two things a columnar engine buys —
a query surface and packed columns — are both in the standard library:

**`sqlite3` is stdlib (3.45.1 in this container).** It gives indexes, joins,
`GROUP BY`, WAL concurrency, and a real query planner over hundreds of millions
of rows, with zero dependencies and no CI change. `data/index/board.sqlite` is a
*derived index*, never a source of truth, rebuildable from L1:

```sql
CREATE TABLE price_obs(
  season INT, game_pk INT, event_id TEXT, market_key TEXT, selection_id TEXT,
  book TEXT, line TEXT, price_american INT,
  observed_utc TEXT, known_at TEXT, grade TEXT, is_close INT, capture_id TEXT
);
CREATE INDEX ix_asof  ON price_obs(game_pk, market_key, known_at);
CREATE INDEX ix_sel   ON price_obs(selection_id, known_at);
CREATE INDEX ix_close ON price_obs(game_pk, market_key, is_close);
```

**`array` + `struct` + `mmap` are stdlib.** The search tier does not want SQL, it
wants packed columns and bitsets — which `src/evolab/bitsets.py` already proves
at 8,811 genomes with per-`(feature, rung, side)` Python bigint masks. The frame
format is deliberately boring:

```
frames/<fp>/header.json   {schema_version, fingerprint, inputs{...}, n_games,
                           games[], columns[{name,dtype,offset,length}],
                           masks[{feature,rung,side,offset}], built_utc, timings}
frames/<fp>/cols.bin      array('d')/array('q') column packs, mmap-read
frames/<fp>/masks.bin     bigint masks, length-prefixed
frames/<fp>/prices.bin    per (game, point_class, selection) executable quote
```

`<fp>` = sha256 of `(sorted L1 file digests used, registry_fingerprint,
engine_version, t_policy, allow_grades)`. A frame built with different bytes has
a different name; a frame built including future bytes is a different frame and
cannot be silently reused. **Content addressing is a leakage control, not a cache
optimization.**

The DuckDB question then gets a nameable trigger instead of an aesthetic answer:
*if instrumented parse+build time exceeds 30% of a full nightly cycle's wall
clock, or a cycle exceeds two hours on four CPUs, bring the measurement to the
owner.* Today it cannot be asked honestly, because — the sharpest finding in the
compute map — the headline "11,088 genomes sweep in 51 ms"
(`EVOLAB_DESIGN.md:384`) was never measured, no `timings` field exists in
`sweep.py`/`replay.py`/`registry.py`, and the Phase 2B artifact (1,660,782 bytes)
records no wall clock at all. `Timings` becomes a **required** field on every
artifact in Packet P5.

### 4.5 Sizing the store for the full board

Measured shapes, projected onto a 15-game slate with the tiered cadence of §5.3:

| Family | Rows per capture moment | Moments/day | Rows/day |
|---|---|---|---|
| ml + run_line + total (11 books, 2 sides) | 15 × 3 × 2 × 11 = 990 | 96 | 95,040 |
| F5 trio (7 books) | 15 × 3 × 2 × 7 = 630 | 3 | 1,890 |
| Alternates (~30 lines × 2 sides × 7 books × 2 markets) | 15 × 840 ≈ 12,600 | 3 | 37,800 |
| Team totals (2 teams × 2 sides × 7 books) | 420 | 3 | 1,260 |
| Pitcher props (5 keys × 2 starters × 2 sides × 7 books) | 15 × 140 = 2,100 | 2 | 4,200 |
| Batter props (9 keys × 18 batters × 2 sides × 7 books) | 15 × 2,268 ≈ 34,020 | 2 | 68,040 |
| **Total** | | | **≈ 208,000 rows/day** |

At ~200 B/row JSONL that is **~42 MB/day raw**, ~5 MB/day gzipped, **~900 MB per
gzipped season**, against a current `data/` of 286 MB in a 15 GiB container. In
the binary frame format the same day is ~24 MB and the whole 2026 season fits in
~4 GB resident — comfortably in RAM, which is exactly why the DuckDB deferral is
right and why it stays right at full board width.

The number that does *not* fit is decisions, and that is §12.

---

## 5. MARKET-UNIVERSE EXPANSION AND CREDIT ECONOMICS (Q7)

### 5.1 The billing shape, which dictates everything

Two endpoints with completely different cost laws, both documented in
`src/providers/odds.py:52-95` from live measurement:

- **Featured `/odds`**: `h2h + spreads + totals`, **3 credits flat for the entire
  slate**, any number of games. Slate width is free here.
- **Per-event `/events/{id}/odds`**: **markets × regions × events**. Every F5 key,
  every prop key, every alternate key bills per game.

So the board splits into a *flat* tier that should be captured densely all day
because it costs nothing extra, and a *per-event* tier where every added market
key multiplies by the slate. That is the whole budget design in one sentence.

### 5.2 Reconciling the balance first

`docs/COLLECTION_POLICY.md:1-10` prices its entire envelope off **53,083 credits
(2026-08-31)**. `data/processed/credit_log.jsonl` reads **99,634 remaining at
2026-09-03T00:15:46Z**. That is a ~46,551-credit discrepancy that looks like a
tier change nobody reconciled. **Packet P7 reconciles it against the vendor's own
billing history and writes the tier, renewal date and monthly allotment into the
policy doc as a dated fact**, because it is explainable today and will not be
reconstructable from this repo after two more billing cycles.

Everything below assumes the 100k/month tier and states what changes at 5M.

### 5.3 The tiered capture grid

```
TIER A — FLAT, all day, every day
  featured /odds (ml, run_line, total, full game)     3 credits x 96 calls/day
  cadence: every 15 minutes, 24h                       = 288 credits/day
  rationale: slate width is free; this is the response variable for every
  movement/timing question and the one layer never sacrificed.

TIER B — PER-EVENT, three moments (T-6h, T-3h post-lineup, T-25m)
  ml_f5, run_line_f5, total_f5                       15 x 3 x 3 =  135/day
  alt run line, alt total                            15 x 2 x 3 =   90/day
  team_total                                         15 x 1 x 3 =   45/day
                                                       subtotal = 270/day

TIER C — PER-EVENT PROPS, two moments (post-lineup, T-30m)
  5 pitcher keys                                     15 x 5 x 2 =  150/day
  9 batter keys                                      15 x 9 x 2 =  270/day
                                                       subtotal = 420/day

TOTAL  ~978 credits/day  ~29,300/month   (100k tier: 29% utilization)
```

Against the current approved envelope of ~132/day this is a **7.4× increase** and
it is the single largest spend decision in the plan. It is also, at the measured
balance, affordable with 70% headroom — and the headroom matters, because a
credit unspent this month does not buy a snapshot next month, while a snapshot
not taken tonight is gone permanently.

What 5M ($119/mo) buys, for when a registered hypothesis needs it: the same
board at **12 moments/day instead of 5** ≈ 5,600/day ≈ 168k/month. That is the
tier for measuring *repricing* — how a prop board moves after a lineup posts —
which is exactly the question `PROBE_PROP_LISTING.md:370-379` says is leaking
today because the T-30m slot is narrower than the hourly cadence and is missed
roughly half the time by construction.

### 5.4 The budget must be a constant, not a paragraph

`CREDIT_FLOOR = 5000` (`dense.py:62`) is a hard-coded, tested stop and it works.
The ~132/day envelope is *prose*. Symmetry:

```python
# src/capture/budget.py
DAILY_ENVELOPE = 1000          # credits/day, owner-approved, dated, versioned
CREDIT_FLOOR   = 5000          # unchanged, absolute

@dataclass(frozen=True)
class CaptureSpec:
    tier: str                  # "A" | "B" | "C"
    market_keys: tuple
    moments: tuple             # ("T-6H","POST_LINEUP","T-25M")
    per_event: bool
    est_credits: Callable[[int], int]   # slate_size -> credits
    settlement_rule_ok: bool   # G3: refuses to schedule if False

def plan_day(slate, balance, spent_today) -> list[PlannedCall]:
    """Deterministic. Orders by value-per-credit, drops from the bottom.

    Drop order when the envelope binds is fixed and written down, never ad hoc:
    Tier C batter props -> Tier C pitcher props -> Tier B alternates ->
    Tier B team totals -> Tier B F5 -> thin the Tier A grid. Tier A last,
    always, and the floor stops everything.
    """
```

Every planned and executed call appends to `data/processed/credit_log.jsonl`
(which already exists, 14 rows, one row per quota read) with `capture_id`,
`spec.tier`, `est_credits`, `actual_credits`. Then "what did the board cost and
what did it buy" is a query, and the value-per-credit ordering above stops being
a guess after about three weeks.

### 5.5 Expansion order, and the gate on each step

| Step | What | Credits/day | Gate |
|---|---|---|---|
| 0 | Persist `all_books` for the 5 market keys already computed and discarded (`snapshots.py:177`) | **0** | none — this is recovering data already paid for |
| 1 | Write L1 canonical rows alongside legacy stores | **0** | G0 byte-conformance on the h2h overlap |
| 2 | Backfill L1 from `odds_history` 2023-25 — **totals becomes readable** | **0** | row-count reconciliation |
| 3 | F5 trio on the pass that already runs | +90 | G3 (F5 settlement exists: `first_five_results.jsonl`) |
| 4 | Alternates + team totals | +135 | G3 + registered feasibility note |
| 5 | Pitcher props (5 keys) | +150 | G3 via GUMBO boxscore |
| 6 | Batter props (9 keys) | +270 | G3 via GUMBO boxscore |
| 7 | First-inning / derivatives | +90 | G3 via GUMBO linescore & play-by-play |
| 8 | Parlay/SGP | ? | **source decision first** (§15.7) |

Steps 0–2 cost nothing and are worth more than steps 3–7 combined, because they
turn one already-purchased market family (totals, 302,271 rows) from unreadable
into replayable and stop the daily discard of five families of book depth.

---

## 6. WHAT EXISTS AND IS WORTH BUILDING ON (Q2)

Stated as store and contract properties, because that is what this design
consumes. None of this should be rewritten.

1. **A verbatim raw layer for historical odds.** `odds_history/*.jsonl` keeps
   whole API payloads with outcomes, points and `last_update`. It is the reason
   302k totals quotes are recoverable.
2. **Point-in-time rebuilt features from pitch level.** `src/pipeline/rebuilt.py`
   over 2,737,968 Statcast rows, cutoff-filtered, tested. The hardest data
   problem in the project is solved.
3. **A registry that refuses rather than warns.** `src/model/pointintime.py`
   raises on an unregistered or leaky input. The mechanism is right; §2.5 adds
   the axis it is missing.
4. **Structural leak-proofing in replay.** `iter_instants_through` *stops* at T
   (`replay.py:577`); sealed 2026 refused by name before any read
   (`replay.py:415-439`); `WorldView` uses `__slots__` + `__getattr__` raising for
   forbidden names, checked at construction (`decide.py:112-178`).
5. **A pure, deterministic decision function with an explicit tie-break and a
   NO_PLAY refusal on conflict** (`decide.py:214-282`).
6. **The bitset engine** (`bitsets.py:142-221`): per-`(feature,rung,side)` bigint
   masks, selection by 2–3 bitwise ops, sum over set bits only.
7. **A falsification battery that has been caught being wrong and repaired.**
   `battery.py`, `RULES_VERSION 2.0.0`, fingerprinted, five fatal rules,
   1,517 lines of validation tests, and the documented case of it originally
   passing the known false positive M3 (`VALIDATION_GATE.md:26-156`). This is the
   most valuable asset in the repository.
8. **Placebo / CSCV / SPA / ceiling producing a real published negative verdict:**
   BELOW_PLACEBO_CEILING, 0/3 generators cleared, pooled percentile 13.3,
   PBO 0.6111 (`EVOLAB_PHASE2B_RESULTS.md`).
9. **An append-only cross-family alpha registry with a working `total_searched()`**
   — 81 rows verified (40 hypothesis / 39 verdict / 1 sweep / 1 audit).
10. **A pre-registration funnel with structural enforcement** —
    screen(2023) → replication(2024) → battery → BH-FDR (`funnel.py:437-675`).
11. **Bracketed forward event capture.** `rosterwatch.py` and `umpirewatch.py`
    produce grade-B `known_at` brackets — the only grade-A/B information the
    project will ever have for lineups, probables, transactions and umpires.
12. **A forward ledger with `information_time` distinct from write time,
    append-only, settlement never mutating the recommendation.**
13. **Credit discipline that actually stops.** `CREDIT_FLOOR = 5000`, checked
    pre-capture and pre-close-pass, with a credit log.
14. **The Engine-2 gate, test-pinned.** `ranker.py:33 ENGINE2 = None` with a test
    that fails if the page contains a pick, a unit size, or edge language.
15. **`Finding` refuses to emit a signal without a baseline** (`src/detect/base.py`)
    — the right shape for evidence, and the model for the `counterarguments`
    requirement in §2.6.
16. **Repo-root-anchored paths** (`src/paths.py`) with an env override, which is
    what makes any of this schedulable without silently building a second store.

## 7. PARTIAL — built, but narrower than it reads (Q3)

1. **Multi-book depth: 6 families computed, 1 persisted.** `normalize_event`
   builds `all_books` for `h2h/spreads/totals` × `full/F5`; `multibook_rows`
   writes `all_books["h2h"]` only. Five families of book depth discarded per
   capture, at zero marginal cost, every run, today.
2. **Totals: captured for three seasons, read by nothing.** `MARKETS_SERVED =
   ("h2h",)`.
3. **F5: schema-legal since Phase 1, never fed.** Every Phase 2B genome that
   preferred F5 fell through to h2h or found nothing (`genome.py:77-81`,
   `feed.py`). Forward F5 close coverage is 26/73 games.
4. **Decision-point granularity: designed as a 4-rung ladder, collapsed to 2**
   (`EARLY_BOARD`, `LATE_BOARD`) because 2023-24 spacing is 177 min minimum,
   6 h median. An honest degradation, and a permanent ceiling on historical work.
5. **Props: one key, listing-heavy.** `pitcher_strikeouts` only; 446 listing rows,
   29 price rows, 18 cr/day cap, live since 2026-09-02.
6. **The point-in-time registry has one axis, not two.** CLEAN means
   cutoff-respecting; it does not mean knowable-at-T. §2.5 adds the second axis.
7. **Bullpen and transactions are raw, not features.** 64,898 + 27,053 rows,
   zero features conditioned on either.
8. **Weather exists forward and not historically**, and wind direction cannot be
   classified anywhere because `orientation_deg is None` for all 30 parks.
9. **Closing is repaired, not recorded.** `settlement.closing` null in every
   sampled row; the value lives in 210 separate `closing_backfill` rows joined at
   read time.
10. **Evolab's fitness excludes staking and bankroll by explicit design**
    (`EVOLAB_DESIGN.md:199-201`) while the vision asks for daily bankroll
    accounts. Both are right — see §13.4.
11. **The externalized capture schedule is merged and has never fired.** Cron is
    `*/15 * * * *` in `.github/workflows/forward-capture.yml`, the default branch
    is still the orphan `claude/cowork-session-migration-tn3sx2`, and `git log`
    shows zero forward-capture-bot commits.

## 8. BELIEVED BUT ABSENT (Q4)

Each of these is a place where a doc, a name, or a schema promises something the
bytes do not deliver. Each must be corrected *before* anything is built on it,
because they are all load-bearing for someone's next decision.

1. **"Evolab" is not evolutionary.** No mutation, crossover, population, elites
   or islands exist in `src/evolab/*.py`. It enumerates a fixed space. This is
   *correct* — the operators are pre-registered as gated on clearing the placebo
   ceiling, which Phase 2B did not clear — but the name misleads every reader.
   Rename the concept in docs, or state the gate in the package docstring.
2. **The measured-performance claims were never measured.** "11,088 genomes in
   51 ms" and "Phase 2 end-to-end well under an hour" are design estimates
   printed as fact; no timing field exists anywhere in the sweep path; the one
   real run recorded no wall clock. The DuckDB deferral's stated exit criterion
   is therefore unmeasurable.
3. **The forward ledger cannot satisfy its own unlock condition.** 300+ forward
   selections required; 0 selections recorded; no rating, book, price, or system
   field; one-row-per-game-ever. Every day it runs unfixed is a day of forward
   evidence in a shape the gate cannot count.
4. **`settlement.closing` advertises a field its writer never fills.**
5. **`docs/RUNBOOK.md` lists three unattended jobs.** One has code and is
   unproven; two have none. `daily_loop.sh`, `monitor_remote.sh` and
   `backup_app_db.sh` have no scheduled trigger at all —
   `OPERATIONS_RUNBOOK.md` §4 says so explicitly of the backup.
6. **The role split is inverted.** Six `.claude/agents/*.md`, all `model: opus`,
   all execution workers including the hypothesis worker. No Sonnet role, no
   Fable role, no dispatcher. "Fable orchestrating" is a session narrating its
   own day in a status document.
7. **The credit policy is priced off a stale balance** (53,083 vs ~99,634).
8. **`COLLECTION_POLICY.md` reports "3–4 books" for pitcher strikeouts** from the
   24-credit probe; the project's own later, better measurement found **7**
   (`PROBE_PROP_LISTING.md:344-350`), and the policy was never corrected.
9. **"Alternate spreads/totals: 7 books at 1 credit" reads as a capability.** It
   was a one-time manual probe outside the codebase; the same doc says these
   markets are not collected.
10. **`MASTER_PLAN.md` Appendix A describes the ledger as hash-chained** in
    present tense; no hash chain exists anywhere in `src/`. (It should — §11.6.)
11. **"CI scorecard for evolab", "Bet Check integration inside evolab",
    "season-end module tied to evolab"** — zero footprint for all three.
12. **`pointintime.py` marks starter-derived inputs CLEAN**, which the project's
    own audit says is a weaker claim than the reader will take it for.

## 9. BOOST VS REPLACE (Q5)

**BOOST — architecture is right, widen it:**

| Module | What to add |
|---|---|
| `src/providers/odds.py` | extend `SUPPORTED_MARKETS`/`EVENT_MARKETS`/`PROP_MARKETS` per registered need; add `observations(payload, capture_meta) -> list[PriceObservation]` beside `normalize_event`, leaving the legacy projection untouched |
| `src/pipeline/dense.py` | `F5_CLOSE_MARKET` → a `CaptureSpec` list; keep the capture-moment / lookahead / seen-set / budget machinery exactly as is — it generalizes to any per-event market |
| `src/pipeline/snapshots.py` | one-line class of fix: persist `all_books` for all six computed keys; then dual-write L0 + L1 |
| `src/evolab/bitsets.py`, `decide.py`, `sweep.py`, `placebo.py`, `cscv.py`, `spa.py`, `ceiling.py` | extend the mask table to selections and markets; do not rewrite. This is the most mature code in the repo and it has already caught its own spec errors |
| `src/research/battery.py`, `funnel.py`, `alpha_registry.py` | extend `MARKETS`, `NUMERIC_FEATURES`; add a `policy` row shape carrying book/price/rating so policy-grading checks (slippage, price-improvement evaporation) are additive; add a similarity/cluster field to registry rows |
| `src/model/pointintime.py` | add the `known_at`/grade axis; add `transactions` as an input |
| `src/pipeline/rebuilt.py` | more rate stats (K%, BB%, real TTO, rest, bullpen availability at T) — the hard part is done |
| `src/pipeline/rosterwatch.py`, `umpirewatch.py`, `weather_capture.py` | more event classes, same bracketing shape |
| `src/analysis/prices.py` | de-vig/best-price/dispersion generalize to n-way and to over/under with lines; keep `MIN_BOOKS = 6` |
| `src/detect/*` | reclassify as a **feature library** that emits `Finding`s into the record, not as a parallel decision path |
| `src/pipeline/creditlog.py` | add reconciliation against the policy doc's stated balance so the 53k-vs-99.6k class of drift trips automatically |

**REPLACE — the shape itself is the constraint:**

| Thing | Why | Replaced by |
|---|---|---|
| `home_price`/`away_price` as the price record | cannot express line, subject, or n-way; the root cause of a one-market system | `PriceObservation` (§2.2) |
| `replay.QUOTE_FIELDS` two-way allowlist | same | selection-keyed quote allowlist |
| `ledger.py` one-row-per-game-ever dedup | structurally forbids recording a changed verdict; blocks the unlock gate | idempotency on `(engine_version, system_id, game_pk, point_class)` |
| `mismatch.route_market` hardcoded two-market routing | the structural opposite of "search the whole board" | a per-selection scoring loop over the board |
| `grading.py` closing computed at settle time + `closing_backfill` repair rows | the schema should hold the value it advertises | closing threaded from the sealed close partition into `Settlement.closing` |
| `scoreboard.py` schema | counts hypotheses; has no room for units, CLV or ratings — a different unit of account | a parallel `evidence/factory/scorecards.jsonl` |
| Prose self-review | not joinable | `ReviewRecord` (§2.7) |

**BUILD NEW — nothing exists to boost:** `src/board/`, `src/knowledge/`,
`src/capture/`, `src/factory/`, the rating/LOCK definition, parlay/correlation,
the Sonnet and Fable role files and the dispatcher.

---

## 10. CAPTURE NOW (Q12)

Ranked by `irreversibility × value ÷ cost`. The first six cost **zero credits**
and four of them are recoveries of data already purchased.

| # | Action | Credits | Window | Why it cannot wait |
|---|---|---|---|---|
| 1 | Persist `all_books` for `spreads`, `totals`, and the three F5 keys (`snapshots.py:177`) | 0 | **today** | Every capture computes and discards five families of book depth. Stale-book, consensus and first-mover analysis for those families is being destroyed hourly |
| 2 | Dual-write L1 `PriceObservation` rows on every capture | 0 | **today** | The 2026 season is the only season that will ever be captured in the right shape. Every day in the old shape is a day that must be re-projected later, or lost where the projection dropped information |
| 3 | Backfill L1 from `odds_history` 2023-25 (h2h **and totals**) | 0 | this week | Turns 302,271 already-purchased totals quotes from unreadable into replayable; gives the engine a genuine second market family for historical work |
| 4 | Historical weather via Open-Meteo archive (`fetch_archive`, free, keyless) for 2023-25 | 0 | this week | Implemented and never called for the past. Multi-day lag, no expiry — so it is fetchable, but it has been "fetchable later" for a year already |
| 5 | Park `orientation_deg` for 30 parks | 0 | this week | Thirty static numbers turn every wind observation, past and future, from a speed into in/out/cross |
| 6 | Wire `transactions.jsonl` (27,053 rows) into the knowledge layer | 0 | this week | Complete on disk for the full 2023-24 window and used by nothing. Doing it before the factory searches avoids a repeat of the probable-pitcher re-audit |
| 7 | Protect the capture cadence: repoint the default branch, add the repo secret, verify one firing of `forward-capture.yml` | 0 | **today** | The hourly cadence still depends on an interactive session. A missed window is gone forever and is never backfilled (`RUNBOOK.md`) |
| 8 | Batter prop board, 2 moments/day, 9 keys | ~270/day | week 2 | The largest surface with zero history. Never purchasable retroactively |
| 9 | Alternates + team totals, 3 moments | ~135/day | week 2 | Best measured information-per-credit on the board (130–160 outcome rows/event at 1 credit) |
| 10 | F5 spreads/totals on the pass that already runs | ~90/day | week 2 | Parsed by `normalize_event` today and never requested |
| 11 | Prop repricing evidence at T-30m (the S6 slot) | included above | week 2 | Roughly half of that slot is never observed by construction; the falsifier it answers is leaking today |
| 12 | Timing instrumentation on every run | 0 | week 1 | The Phase 2B run's wall clock is permanently unrecoverable; only future runs can be measured |
| 13 | Reconcile the credit tier/balance into the policy doc as a dated fact | 0 | week 1 | Explainable today from vendor billing history; not reconstructable from this repo after two more cycles |
| 14 | Umpire, lineup, probable, transaction brackets — keep them running | 0 | continuous | Grade B forward is the only grade above C this project will ever have for these classes |
| 15 | Parlay/SGP: record the *source decision* and whatever leg-level prices exist | TBD | week 3 | If SGP prices are not readable from the API, that fact must be written down now, with the date, rather than rediscovered in 2027 |

**One line to the owner:** items 1–7 and 12–14 cost nothing, and items 1–3 alone
change the project from a one-market system with a discarded board into a
multi-market system with three seasons of second-family history.

---

## 11. THE READER, THE ENGINE, THE LOOP, AND THE REPLAY (Q8, Q9)

Data-first does not mean the engine is an afterthought; it means the engine's
contract is *derived* from the record rather than invented beside it. Given §2
and §4, the engine contract writes itself.

### 11.1 One reader, and it is the only one

```python
# src/knowledge/asof.py   -- the ONLY read path any decision may use

def as_of(*, sport, game_pk, t, allow_grades=frozenset("AB"),
          root=BOARD_ROOT) -> Snapshot:
    """Everything legitimately knowable about one game at instant t.

    Returns an immutable Snapshot. Raises SealedWindowError for a sealed season
    by name before reading anything. Cannot open any path outside `root`, and
    `root` never contains prices_close/, results/, or settlements/.

    Rows with known_at > t are not filtered late -- the day-partitioned scan
    STOPS, the same discipline replay.iter_instants_through already applies
    (replay.py:577), because a filter is a habit and a stop is a guarantee.
    """

@dataclass(frozen=True, slots=True)
class Snapshot:
    t: str
    game: GameContext            # teams, park, start time, day/night, travel/rest
    information: dict            # kind -> latest InformationEvent at or before t
    board: Board                 # every selection with a live quote at t
    grades: dict                 # kind -> grade actually used
    assumption_exposure: dict    # grade C/D counts, stamped onto every artifact
    fingerprint: str             # sha256 of the canonical bytes of this snapshot
```

`Snapshot.fingerprint` is what makes "the exact same engine" checkable rather
than asserted: two runs that claim to have decided the same thing must produce
the same 64 hex characters, byte for byte.

### 11.2 The Board, which is a list of selections

```python
@dataclass(frozen=True, slots=True)
class Board:
    quotes: tuple        # tuple[Quote], canonically ordered by selection_id
    def selections(self) -> tuple: ...
    def by_market(self, market_key) -> tuple: ...
    def best(self, selection_id) -> Quote | None:     # best price across books
    def consensus(self, selection_id, min_books=6) -> Consensus | None:
    def friction(self, selection_id) -> Friction:      # measured vig, book count,
                                                       # max staleness, dispersion

@dataclass(frozen=True, slots=True)
class Quote:
    selection_id: str; market_key: str; side: str
    subject_kind: str | None; subject_id: str | None; line: str | None
    book: str; price_american: int
    observed_utc: str; book_last_update: str | None; staleness_s: int
```

"Search the entire board" is then `for q in snapshot.board.selections()`. It is a
loop, and it is a loop only because the record has a selection concept. `Friction`
is first-class because of §15.5: without it, cross-market ranking systematically
prefers whichever market carries the widest vig.

### 11.3 The engine, unchanged in kind from `decide.py`

```python
# src/engine/analyze.py

def analyze(snapshot: Snapshot, system: System) -> Analysis:
    """Pure. No I/O, no clock, no randomness, no globals, no model call.

    Cannot tell whether it is running live tonight or replaying 2023-04-11,
    because Snapshot is the whole of its input.
    """

@dataclass(frozen=True, slots=True)
class Analysis:
    candidates: tuple      # 0..N Candidate, ordered deterministically
    refusals: tuple        # named reasons, per selection considered
    considered: int        # how many selections were actually examined
    engine_version: str

@dataclass(frozen=True, slots=True)
class Candidate:
    selection_id: str; market_key: str; line: str | None
    book: str; price_american: int
    p_hat: float | None; p_hat_interval: tuple | None
    edge_bps: int | None; friction: Friction
    findings: tuple        # evidence, src/detect/base.Finding shapes
    counterarguments: tuple  # REQUIRED non-empty
    supporting_systems: tuple
```

The one architectural invariant, enforced by a grep test over `src/engine/`,
`src/board/`, `src/knowledge/` and `src/factory/` for
`anthropic|openai|api_key|urllib.request|requests|datetime.now|random\.`:
**no model call, no network, no clock and no unseeded randomness inside the
decision path, ever.** Models propose; deterministic code decides.

### 11.4 The daily loop, named by what it writes

Each step is a module, each writes exactly one record type, each is
independently re-runnable, and a failed step never leaves a half-written day.

```
06:00  capture.plan_day()            -> PlannedCall[]        (credit_log)
       runs all day on the Tier A/B/C grid, L0 first then L1

T-6h   loop.morning(date)
         for each game: as_of(t=T-6h) -> Snapshot
         analyze(snapshot, system) for every enabled system
       -> DecisionRecord[] at point_class=T_MINUS_6H  (incl. no_play, with reason)

T-3h   knowledge.await_lineup()      -> InformationEvent (grade B bracket)
       loop.post_lineup(date)
         re-run as_of + analyze for every game whose lineup posted
       -> DecisionRecord[] at point_class=POST_LINEUP
          (this is the row today's ledger structurally cannot write)

T-30m  loop.late(date)
         final board, final analyze; ratings computed here
       -> DecisionRecord[] at point_class=T_MINUS_30M

T-0    capture.close_pass()          -> PriceObservation is_close=True
                                        into the SEALED partition

post   settle.run(date)              -> Settlement[]  (closing threaded in,
                                        no closing_backfill repair rows)
       account.run(date)             -> BankrollDay[] (simulated, reporting only)
       review.run(date)              -> ReviewRecord[] (§2.7)
       factory.cycle(date)           -> §13
```

Two properties worth stating explicitly because the current pipeline lacks both:

- **Every game gets a row at every point class**, including `no_play` with a
  named reason. A strategy whose whole point is declining is not describable
  without the declines — the existing ledger docstring makes exactly this
  argument and then permits only one row per game.
- **Ratings are computed at the last decision point, not the first.** A rating
  that ages six hours through a lineup change is not a rating.

### 11.5 Replay is the same loop with a different clock source

```python
# src/engine/replay.py  (v2; the existing src/evolab/replay.py is its ancestor)

def replay_day(date, systems, *, t_policy, allow_grades) -> list[DecisionRecord]:
    """Identical to the live loop except that `t` comes from the policy
    rather than from the wall clock, and the store root is a historical one.

    It calls loop.morning / loop.post_lineup / loop.late -- the same functions,
    not copies of them. There is no second decision path to keep in sync.
    """
```

**The conformance test is the whole guarantee:** for a sampled set of
`(game, point_class)` from the live season, rebuild the Snapshot from the store
after the fact and assert `snapshot.fingerprint` equals the fingerprint recorded
on the live `DecisionRecord`. If they differ, either the live path saw something
the store did not keep, or the store gained something the live path could not
have seen. Both are bugs and both are silent today.

### 11.6 The leakage controls, enumerated

1. `as_of()` **stops** at `t`; it does not filter.
2. Grade C/D excluded by default; inclusion is explicit and stamped as
   `assumption_exposure` on every artifact.
3. Closing prices, results and settlements live in physically separate
   directories the reader's path allowlist cannot open, and a test tries.
4. `src/engine/**` and `src/factory/**` may not import `src.board.store`; only
   `src.knowledge.asof`. Import-guard test, same style as the existing
   stdlib-only and network-block CI guards.
5. Sealed seasons refused **by name** at the store layer, before any file is
   opened — not only inside replay, as today.
6. Frame fingerprints are content addresses over the exact input bytes; a frame
   containing post-T rows is a different frame and cannot be silently reused.
7. Every `DecisionRecord` carries `frame_fingerprint` and the Snapshot
   fingerprint, so "which bytes produced this decision" is answerable years later.
8. `Snapshot` is `frozen` + `slots` and raises on forbidden attribute names, the
   `decide.py:112-178` pattern extended to a deeper structure — and the
   construction check must be **recursive**, not top-level only.
9. No network, no clock, no unseeded randomness in the decision path (grep test).
10. **Hash-chained ledgers.** `MASTER_PLAN.md` Appendix A already describes the
    recommendation ledger as hash-chained and no chain exists. Add
    `prev_hash`/`row_hash` to `evidence/decisions/*.jsonl` and
    `evidence/settlements/*.jsonl` with a `verify_chain()` in CI. Append-only is a
    convention; a chain is a proof, and the forward ledger is the only evidence
    this project will ever have that cannot be reconstructed by a skeptic.
11. **Write-order rule:** a `Settlement` row may not be written for a decision
    whose `decision_utc` is later than the settlement's own game start. Trivially
    true today, catastrophic and invisible the first time a backfill script is
    written carelessly.
12. `known_at` grades may be lowered by audit, never raised, and every change is
    an append-only row with a reason and a commit.

### 11.7 What the loop must refuse

`market_unavailable` is already a first-class verdict and it should stay one — it
matched a measured 30% first-five gap, which is exactly the kind of fact a
system that papers over gaps never learns. Add three more named refusals so that
"nothing today" is always attributable: `THIN_CONSENSUS` (below `MIN_BOOKS`),
`STALE_BOARD` (every quote older than a bound), `GRADE_INSUFFICIENT` (the
decision would have leaned on grade C/D the system did not declare).

### 11.8 Settlement, and the closing price

`Settlement` reads from the sealed partition and writes `closing_american`,
`closing_book`, `closing_consensus_fair`, `clv_bps`, and `result` produced by the
`SETTLEMENT_RULES` table (§2.4). The `closing_backfill` repair kind stays only as
a migration tool for the 427 existing rows, and is retired the day the new writer
lands. CLV is reported as a **diagnostic**, never as profit, and never summed
with `edge_bps`.

---

## 12. SCALE: MILLIONS OF DECISIONS, CHEAPLY (Q10)

### 12.1 The arithmetic, and the honest conclusion about storage

```
systems        5,000
games          4,819  (full replay universe, 2023-24)
point classes  2      (historical ceiling: 177-min min gap, 6-hour median)
selections     ~40 per game at full board width
------------------------------------------------------------------
decisions/world  5,000 x 4,819 x 2 x 40  =  1.93 x 10^9
x 51 worlds (1 real + 50 placebo)        =  9.8 x 10^10
```

At 100 bytes per stored decision that is **9.8 TB per sweep**. It is not
storable, it is not backup-able, and it is not necessary.

**Determinism is the compression algorithm.** A decision is a pure function of
`(engine_version, system_id, registry_fingerprint, frame_fingerprint,
point_class, game_id)`. Given those six strings the decision is reproducible
exactly. So:

- **Store the recipe and the aggregate, not the decisions.** Per
  `(system, world, window, point_class, market)` write one `Scorecard` row —
  a few hundred bytes. 5,000 systems × 51 worlds × 4 windows × 2 point classes ×
  8 market families ≈ 16.3M scorecard rows ≈ **3 GB**, and in practice far fewer
  because most systems die in the first world.
- **Store full decision detail only for the published tier** — anything that
  reached the ledger or a promotion review. That is tens per day, not billions.
- **Reproduce on demand.** `replay_decision(recipe) -> DecisionRecord` rebuilds
  any single decision from the six strings in milliseconds. An auditor asking
  "why did system 4417 pass on Padres/Giants on 2024-06-11 at T-6h" gets a real
  answer without the system having stored 10^11 rows against the possibility.

This is the data-first answer to "millions of decisions": **you do not keep them,
you keep the ability to recreate them, and you make that ability testable** — a
CI job that reproduces 1,000 sampled decisions from a past artifact's recipe and
asserts byte equality.

### 12.2 Why the compute is affordable

The insight already implemented in `bitsets.py`: **signal firing is a property of
the world, not of the system.** Per `(feature, rung, side)` you build one bigint
mask over all games once; every system referencing that signal reuses it.
Selection becomes 2–3 bitwise ops and a popcount, with no Python loop over games.

Cost is therefore `masks × worlds`, not `decisions`. At 40 features × 3 rungs ×
2 sides × 8 market families ≈ 1,920 masks per world, plus ~5,000 × 8 combine-and-
popcount operations per world. That is seconds per world on one core, and
Phase 2B already demonstrated the pattern at 8,811 genomes over 4,188 games.

Add to the mask table two market-aware masks that do not exist today:
`market_available_mask[market_key][point_class]` and
`books_ge_k_mask[selection][k]`, so "was this priced, deeply enough, at this
instant" is a bit test rather than a dict lookup per decision. Without them, board
widening moves the cost back into Python loops and undoes the whole design.

### 12.3 Six concrete moves, in order

1. **Instrument first (P5).** `src/core/timing.py` context manager writing
   `{stage, wall_s, cpu_s, rows, decisions, peak_rss_mb}`; `timings` becomes a
   **required** field on every artifact. This retires the never-measured "51 ms"
   claim and makes the DuckDB deferral's own exit criterion measurable for the
   first time.
2. **Persist frames (P8).** Content-addressed L2. `matrix.py` currently re-parses
   full JSONL at 7–11 s/season on every invocation; pay it once per data change.
3. **Parallelize worlds.** 4 CPUs, `multiprocessing` (stdlib), LPT balancing —
   `scripts/test_parallel.py:135-157` already demonstrates the exact pattern for
   test sharding. Expect ~3.5×. Determinism preserved: each world independently
   seeded, results reassembled in canonical order.
4. **`ReplayUniverse.get()` one-line fix** — an O(n) linear scan
   (`replay.py:731-735`) beside an unused O(1) `by_id()` dict (`:728-729`).
   Harmless at 4,800 games, an O(n²) trap at multi-season multi-sport width.
5. **SQLite index for everything that is a query, not a sweep** — coverage
   reports, store audits, ledger joins, review queries. Stdlib, no CI change.
6. **Only then** revisit columnar third-party formats, with the measurement
   attached and the stdlib-only invariant explicitly on the table as a cost.

### 12.4 The container reality, as a dated baseline

15 GiB RAM (707 MiB used), 4 CPUs, no swap; `data/` 286 MB. Four container
restarts in an hour occurred with 0.6 GB of 16 GB in use — restarts are
platform-driven, not load-driven (`ORCHESTRATION_DAY_2026-09-02.md:225-229`).
That is a first-party measurement worth preserving as a named reference point in
`docs/`, so that if parallel sweeps later push memory hard, a regime change is
detectable against a baseline rather than re-argued from scratch.

---

## 13. EVOLAB → STRATEGY FACTORY (Q6)

### 13.1 What Evolab actually is, and what it should become

Evolab today is a *deterministic enumerator plus an adversarial evaluator*. The
evaluator half — placebo generators, CSCV, SPA, ceiling, sweep — is the best code
in the project and produced a real published negative verdict. The enumerator
half is a fixed grammar over six features and one market, and the evolutionary
operators do not exist because they are pre-registered as gated on clearing the
placebo ceiling, which Phase 2B did not clear. That gate should hold.

The factory is therefore not "add mutation to Evolab". It is: **keep the
evaluator, replace the enumerator's inputs, and wrap the whole thing in a
lifecycle with a store.**

```
src/factory/
  population.py   Strategy records, lifecycle states, generation lineage
  generate.py     enumerate (existing) + mutate/cross (gated, unlocked per cell)
  dedupe.py       semantic hash + similarity cluster; graveyard check
  evaluate.py     -> src/evolab/sweep.py, unchanged in kind
  attack.py       -> src/research/battery.py, per candidate above the floor
  score.py        Scorecard records
  lifecycle.py    promote/demote/retire transitions, each with a written cause
  cycle.py        the nightly orchestration, deterministic end to end
```

### 13.2 The lifecycle, as stored state

```python
LIFECYCLE = ("proposed", "registered", "screened", "replicated", "attacked",
             "ceiling_tested", "forward_testing", "promoted",
             "demoted", "retired", "graveyard")

@dataclass(frozen=True, slots=True)
class Strategy:
    system_id: str            # sha256 of canonical genome/spec, 16 hex
    spec: dict                # the genome or rule spec, canonical JSON
    cell: str                 # the pre-registered region of the search space
    generation: int
    parents: tuple            # lineage; () for enumerated
    state: str
    state_utc: str
    state_cause: str          # REQUIRED, plain language, never empty
    registry_row: str         # alpha_registry id -- registration is not optional
    semantic_hash: str
    cluster_id: str | None    # §15.2
```

Every transition appends a row. `evidence/factory/graveyard.jsonl` holds every
retirement with its cause, and **the graveyard is published** — that is the
"losers published" constraint, made mechanical rather than remembered.

### 13.3 Selection is never by bankroll

`Scorecard` carries every axis the owner named, and the promotion rule reads all
of them:

```python
@dataclass(frozen=True, slots=True)
class Scorecard:
    system_id: str; world: str; window: str; point_class: str; market_key: str
    n_decisions: int
    n_independent_clusters: int      # REQUIRED; game-day blocks >= 7 days
    profit_units: float; roi: float; avg_odds_decimal: float
    max_drawdown_units: float; volatility: float
    clv_bps_mean: float; clv_bps_ci: tuple
    brier: float; log_loss: float; reliability_bins: tuple
    oos_delta: float                 # screen vs replication
    forward_n: int; forward_roi: float
    stability_by_season: dict; stability_by_book: dict; stability_by_market: dict
    price_sensitivity: dict          # ROI at -5/-10/-20 bps execution
    top5_win_share: float            # dependence on a few big wins
    bootstrap_ci: tuple              # clustered
    placebo_percentile: float; cscv_pbo: float; spa_p: float
    battery_verdict: str; battery_rules_version: str
    total_searched_at_verdict: int   # from alpha_registry.total_searched()
```

**`n_independent_clusters` is required and `n_decisions` may never be quoted as
sample size.** Outcomes within a game are massively dependent — forty selections
on one game are one game — and outcomes within a day share weather, umpire pools
and market regime. Scaling compute without scaling the dependence accounting
produces confident nonsense faster; this field is the guard.

### 13.4 Bankroll: reporting, never fitness

`EVOLAB_DESIGN.md:199-201` excludes staking, bankroll, Kelly and drawdown from
fitness by explicit design. The vision asks for simulated daily accounts of 1,000
units. **Both are right and they are not the same object.** Fitness must not
contain a staking rule, because staking rules are a second search space and
optimizing them jointly with selection is how a backtest learns to bet big on the
sample's lucky days. But an account ledger is exactly how a human reads whether a
system is livable.

```
src/factory/account.py
  simulate(decisions, settlements, *, start_units=1000.0, stake_rule) -> BankrollDay[]
```

`BankrollDay = {date, opening, closing, staked, returned, n_bets, max_dd_to_date}`.
Stake rules are **named, versioned and fixed in advance** (`FLAT_1U`,
`FLAT_2U`, `KELLY_QUARTER_CAPPED_2U`). The account is written to
`evidence/factory/accounts.jsonl` and reported alongside the Scorecard; it never
enters selection. `src/core/staking.py` already has the Kelly math.

### 13.5 The nightly cycle

```
factory.cycle.run(date):
  01 generate    enumerate new cells; mutate/cross only within UNLOCKED cells
  02 dedupe      semantic hash + cluster vs population and graveyard
  03 register    alpha_registry.register() every survivor -- before evaluation
  04 evaluate    bitset sweep, real + 50 placebo worlds, parallel over 4 CPUs
  05 score       Scorecard per (system, world, window, point_class, market)
  06 attack      research.battery for every candidate above the effect floor
  07 ceiling     placebo percentile + CSCV PBO + SPA
  08 transition  lifecycle changes; graveyard rows with cause
  09 account     bankroll simulation, reporting only
  10 artifact    write with timings, fingerprints, total_searched()
```

Steps 01–10 are deterministic and contain no model call. The unlock rule for step
01's mutation operators is unchanged from what the project already pre-registered:
**a cell's operators unlock only when that cell's enumerated search clears the
placebo ceiling.** Phase 2B did not, so the operators stay locked for the
6-feature h2h cell — and the correct response to that is not to unlock them, it is
to widen the *feature and market* space, which is what §5 and §10 are for.

### 13.6 What the factory reads

Nothing but frames and the registry. `src/factory/**` cannot import
`src.board.store`, cannot open sealed partitions, and cannot make a network call.
Its inputs are a frame fingerprint and a registry fingerprint; its outputs are
Strategy transitions, Scorecards, accounts and one artifact. That is what makes
"thousands of competing systems under identical point-in-time conditions"
literally true rather than approximately true: identical conditions means the
same frame hash.

---

## 14. PRODUCT: V2, BET RATING, PICKS, LOCK (Q13)

### 14.1 The gate is not negotiable and the plumbing can be built behind it

`ranker.py:33 ENGINE2 = None` with a test that fails if the page contains a pick,
a unit size, or edge language. Nothing in this design weakens that. Everything
below is built, tested, and **dark** until the unlock conditions clear *and* the
owner signs off.

### 14.2 What the Analyzer becomes

Today: 11 threshold detectors and a hardcoded two-market router. Under this
design the detectors are reclassified as a **feature and evidence library** —
they produce `Finding`s that go into `Snapshot.information` and into
`Candidate.findings` — and they lose their authority to decide. The customer-
facing Analyzer page then shows, per game, the reconstruction the vision
describes: starters, bullpen, offense, environment, market, each section with its
evidence, its sample size, and its `known_at` grade. Sections that rest on grade
C/D say so on the page. That is a better product than a page that hides its
assumptions, and it is honest about the probable-pitcher problem in front of the
customer rather than in an audit file.

### 14.3 Bet Rating

A rating is a function of probability **and** price **and** the track record of
the thing that produced them. It is stored with every input it used, so it can be
recomputed and audited:

```python
@dataclass(frozen=True, slots=True)
class Rating:
    klass: str            # "C" | "B" | "A" | "LOCK"
    version: str          # "rating.1.0.0" -- the formula is versioned data
    inputs: dict          # p_hat, p_hat_interval, fair_no_vig, price_decimal,
                          # edge_bps, friction, kelly_fraction,
                          # system_forward_n, system_brier, system_reliability_bin,
                          # robustness_score, correlation_load
    caveats: tuple        # e.g. ("grade_D:probable_pitcher",)
```

Rules that keep it honest:

- **A rating may not exist without a calibrated `p_hat`.** `src/core/calibration.py`
  has Brier, log-loss and reliability curves and is wired only to synthetic data —
  correctly sequenced, because there is no production model to score yet. Until
  there is one, `Rating` is `None` for every decision, and that is a truthful
  state, not a placeholder.
- **`price_improvement_bps` never enters a rating.** Separate column, separate
  meaning, test-enforced.
- **The rating class boundaries are stored data, not code constants**, versioned,
  and every published rating names the version that produced it.

### 14.4 Picks

`PicksContract` is a new frozen dataclass beside the existing six in
`src/analysis/contracts.py`, following the same sample-plus-evidence enforcement.
It renders 0..N opportunities. **Never a fixed count**; a day with nothing shows
the count of selections examined and the reasons they were declined — which is a
more convincing product surface than three forced picks, and it is the only one
consistent with the ledger.

### 14.5 LOCK — define it as a measured class, not a confidence adjective

The owner asks for LOCK criteria to be researched rather than prohibited. The
research question should be framed so it can fail:

> **LOCK is a calibration bucket, not a feeling.** A rating class may carry the
> LOCK label only if, over at least `N_LOCK` *forward* settled decisions in that
> class, the realized frequency falls inside the published confidence band for the
> class's stated probability, and the class's CLV distribution is non-negative at
> the median. Both numbers are published, win or lose, and the label is
> **withdrawn automatically** the first time either fails at a stated review
> cadence.

That definition is registrable as a hypothesis, falsifiable, and it makes LOCK the
most conservative label in the system rather than the loudest. `N_LOCK` should be
set by power analysis before any LOCK is shown, not after the first good week.

### 14.6 Bet Check

`src/analysis/betcheck.py`'s parse-and-refuse architecture is right; widen
`SUPPORTED_MARKETS` only as the price engine gains each family, and keep the
mandatory non-EV labelling on price improvement.

---

## 15. WHERE THE DESCRIPTION CAN BE MADE BETTER (Q14)

Ten challenges. None of them reduce the vision; several of them are the only way
the vision survives contact with the evidence.

### 15.1 "Millions of decisions" is the wrong target; independent evidence is the constraint

The compute is affordable (§12) and the storage problem dissolves under
determinism. What does not scale is *evidence*. There are ~2,430 MLB games per
season; two discovery seasons give ~4,860. Forty market expressions per game
produce ~194,000 decisions and roughly **4,860 independent units**, and clustering
by day reduces even that. Ten million decisions on 4,860 games is not ten million
observations, it is 4,860 observations examined ten million ways — which is the
textbook setup for finding something that is not there. **Reframe the goal from
decision count to searched-hypothesis accounting**: `total_searched()` on every
verdict, FDR across families and across time, and a required
`n_independent_clusters` on every scorecard. The alpha registry already does the
hard part; the target metric should change to match it.

### 15.2 "Thousands of competing systems" over six features is one idea resampled

Phase 2B searched 8,811 genomes over **6 features and 1 market**. Ten thousand
systems over the same six features are not ten thousand ideas; they are a dense
grid on a small space, and the multiplicity correction eats the whole budget for
almost no informational return. **The lever is breadth, not population.** Adding
bullpen availability, transactions, weather, park orientation and market
structure — items 4–6 and 9 in §10, all free or nearly free — expands the space
in the dimension that carries new information. Population growth should follow
feature growth, never lead it. Add a `cluster_id` to every strategy so the
registry can report "we searched 40,000 systems in 62 clusters", which is the
honest count.

### 15.3 Most of the board cannot be backtested, ever — say so now

This is the correction with the largest consequence, and it is forced by the
bytes rather than by opinion.

- Run line / spreads: **never polled historically**. Not purchasable.
- Alternates, team totals, margin, first-inning, derivatives: never polled.
- All props: never polled (the vendor sells prop history from ~May 2023, at a
  price, on a grid the project has not bought and would still be sparse).
- F5: one snapshot per game, 185/133/172 games with any book — a board with no
  second instant cannot answer a timing question.
- Totals: **genuinely replayable**, 302k quotes, 3–4 instants per game.
- h2h: replayable, at 2 decision-point classes, not 4.

So the honest split is:

> **Historical replay covers h2h and totals (and thin F5) at two decision points.
> Everything else in the vision's market list is forward-only, its first
> settled evidence begins the day capture starts, and its first honest
> out-of-sample verdict is a 2027 question.**

Writing that down now changes three things: it makes the live-season capture the
highest-priority activity in the project rather than a supporting one; it stops a
future reader from expecting a prop backtest that can never exist; and it sets
the right expectation for the unlock gates, which cannot be satisfied for most
market families by any amount of historical work.

### 15.4 The precious season is precious for capture, not for picks

Following from 15.3: the marginal value of a better analyzer this month is small,
because it will be evaluated on a sample that cannot reach significance this
season. The marginal value of a *complete point-in-time board* this month is
enormous and strictly decaying — every hour not captured is deleted. **For the
next 60 days, capture completeness should outrank analysis sophistication in
every prioritization conflict.** That is an explicit inversion of the natural
instinct and it is what §10 encodes.

### 15.5 "Which market best expresses the advantage" needs a friction model or it will always pick the worst market

Comparing edges across markets presumes the probabilities are comparable and the
prices are equally executable. They are not. Prop and alternate markets carry
much wider vig, thinner book counts, staler quotes and lower limits than the
moneyline. A naive cross-market ranker maximizes *measurement error* and will
reliably select the widest, thinnest market on the board. **`Friction` must be a
first-class stored field** (measured two-sided vig, book count, max staleness,
dispersion) and the ranking quantity must be **edge net of friction**, with the
friction shown to the reader. Market width without a friction model is not an
opportunity surface, it is a noise amplifier.

### 15.6 Correlation is a data problem before it is a parlay problem

Two legs on the same game are not two observations, and the strategy factory has
the same issue: two systems that fire on the same games are not two systems. The
prerequisite for both parlays and population diversity is one artifact: a
**co-occurrence store** — for each pair of (selection, selection) and (system,
system), how often they fire together and how their outcomes covary. It is cheap
(a bitset AND and a popcount, using machinery that already exists), it is
computable from data already on disk for h2h and totals, and nothing about
parlays, SGP or "correlated structures" is honest without it.

### 15.7 Parlays need a source decision before they need a model

The joint-probability mathematics is the easy half. The hard half is that a
book's SGP price is a *book-side function* incorporating its own correlation
adjustment, and it may not be readable from the API at all. Before any parlay
code is written, **record the source decision as a dated fact**: can SGP prices
be read, for which books, at what credit cost, and if not, then the project can
model joint probabilities and compare them only to *manually constructed*
multi-leg prices, which is a different and much weaker claim. Writing "not
available, checked 2026-09-XX, here is the evidence" is a real deliverable.

### 15.8 Price improvement is not EV — make it a schema invariant

The constraint currently lives in prose and in a mandatory label
(`src/analysis/prices.py:30-45`). Promote it: `edge_bps` and
`price_improvement_bps` are separate columns on `DecisionRecord` and `Scorecard`,
and a test fails if any code path adds them, assigns one to the other, or reports
a total. A rule that is a column cannot be forgotten in a refactor.

### 15.9 The self-review must be a record, or it cannot close the loop

Prose in `docs/OVERNIGHT_RUN.md` cannot be joined to a decision, counted, or fed
to the factory. As `ReviewRecord` (§2.7) it can, and `missed_information` becomes
the project's best feature backlog: generated by the system's own failures rather
than by speculation.

### 15.10 "AI-powered" must mean models propose, never decide

The vision's framing invites a reading in which a model looks at a game and picks
a bet. That is unbacktestable (a model call is not reproducible at a past
timestamp), unauditable, and inconsistent with every other constraint in this
project. State the invariant plainly in the product language: **models generate
hypotheses, write code, review methodology and draft explanations; deterministic
code reads the store, decides, grades and publishes.** This is not a reduction of
the vision — it is what makes "backtest the analyzer with the exact same decision
engine" a sentence that can be true.

### 15.11 Prediction markets are a different object, not another book

Exchange venues have fees, maker/taker structure, limited depth and different
settlement language. They should not be written as another `book` value on a
`PriceObservation` without a `venue_kind` field and a fee model, or every
consensus and de-vig calculation in the system will quietly mix two different
kinds of price.

---

## 16. DETERMINISTIC vs SONNET vs OPUS vs FABLE (Q11)

### 16.1 Deterministic — the overwhelming majority, and it is enforced

Everything in `src/board/`, `src/knowledge/`, `src/capture/`, `src/engine/`,
`src/factory/`, `src/research/`, grading, scoring, gates, artifacts. No network,
no clock, no unseeded randomness, no model call — grep-tested in CI, in the same
style as the existing stdlib-only and network-block guards. If a number appears
in an artifact, a deterministic function produced it from stored bytes.

### 16.2 Sonnet — implementation from a written spec

Per-market normalization adapters; backfill and migration scripts; store audits
and coverage reports; test writing; the thirty park orientations; wiring
`transactions.jsonl`; packet-sized code from a packet spec that names the files,
the signatures and the acceptance test. Sonnet's output is code and it is
reviewed by tests, not by belief.

### 16.3 Opus — methodology and adversarial review

Schema review before a record type is frozen; gate design; falsification battery
rule changes; audits of the kind that produced `AUDIT_PROBABLE_PITCHER_PIT.md`
(which is the single best document in the repository and is exactly this role's
output); adjudicating a `known_at` grade downgrade; reviewing any promotion to
`forward_testing`. **Opus reviews are a standing gate, not a courtesy**: the
project's own record already says a Phase-1 rule was "added" requiring a pinned,
reviewed read before a research result counts, and no code enforces it. Enforce
it with a `validator_verdict` field that a verdict row cannot be written without.

### 16.4 Fable — orchestration

The packet queue and dispatch; keeping the capture cadence alive and noticing when
it stops; reconciling stores after a container restart; running the nightly
factory cycle and the daily loop; publishing artifacts and the graveyard; holding
the owner-decision queue. Fable is the only role that is allowed to be
*interrupted and resumed*, which is why the capture cadence must not depend on it
(§10, item 7).

### 16.5 The correction the roster needs

Today: six `.claude/agents/*.md`, all `model: opus`, all execution workers,
including the hypothesis worker; no Sonnet role, no Fable role, no dispatcher.
Fix in P7: add `sonnet-implementer.md` and `fable-orchestrator.md` using the same
OBJECTIVE / WHY / INPUTS / BOUNDARIES / DELIVERABLE / ACCEPTANCE template, retag
the implementation-shaped Opus roles as Sonnet, and keep Opus on methodology,
review and audit. Add a real dispatcher — a queue file plus a runner — rather
than a session narrating manual delegation.

### 16.6 The provenance rule that ties the roles to the store

**No model output is ever a data row.** If a model writes something that lands in
a store, it carries `provenance: "model"`, `model_id`, and `prompt_hash`, and it
is excluded from every evidence path by default. A hypothesis proposed by a model
is a *proposal*; it becomes a hypothesis when it is registered and it becomes a
finding when deterministic code measures it.

---

## 17. PHASES, GATES, AND THE FIRST TWO WEEKS IN PACKETS

### 17.1 Gates

| Gate | Condition | Blocks |
|---|---|---|
| **G0 Record conformance** | For 7 days of overlap, the canonical L1 projection reproduces the legacy h2h stores exactly, row for row | any reliance on L1 |
| **G1 Grade audit** | Every registered input carries a `known_at_grade`; every artifact prints `assumption_exposure` | any decision artifact |
| **G2 Budget** | `DAILY_ENVELOPE` is a constant, the drop order is coded, the tier/balance is reconciled and dated | any paid market expansion |
| **G3 Settlement-before-collection** | A market family has a settlement rule, a fetchable result source, and ten graded examples | switching that family on |
| **G4 Replay equality** | Sampled live `Snapshot.fingerprint` values reproduce byte-identically from the store after the fact | any backtest claim |
| **G5 Ceiling** | A cell clears the placebo ceiling (percentile, CSCV PBO, SPA) | unlocking mutation operators in that cell |
| **G6 Forward** | 300+ forward *selections* with book, price, rating, counterarguments, and settled CLV | Engine 2 unlock consideration |
| **G7 Owner sign-off** | Explicit, dated, after G6 | anything published as a pick |

### 17.2 Phases

- **Phase D0 — Record (weeks 1–2).** L0/L1, `known_at` grades, `as_of()`, frames,
  budget, free recoveries. Ends at G0+G1+G2.
- **Phase D1 — Board (weeks 3–6).** Market families switched on in the §5.5 order
  behind G3; totals replayed end to end; ledger v2 carrying the full decision
  record. Ends when the ledger records its first properly-shaped selections.
- **Phase D2 — Factory (weeks 7–12).** Frames feed the sweep at board width;
  lifecycle, graveyard, scorecards, co-occurrence store; nightly cycle with
  timings. Ends at a published cycle artifact, losers included.
- **Phase D3 — Calibration (months 4–6).** A probability model exists and is
  scored; `Rating` becomes non-`None`; forward ledger accumulates toward G6.
- **Phase D4 — Product (gated).** Picks and LOCK behind G6 + G7.

### 17.3 The first two weeks, in packets

Each packet is one day of work, names its files, and states its acceptance test.
Nothing here spends a credit except P7's reconciliation read (free) and the
deliberate expansions in week 2, each of which is separately gated.

**P1 — Stop the discard.** `src/pipeline/snapshots.py`: `multibook_rows` persists
`all_books` for all six computed keys, one row per (event, market, selection,
book) in the canonical shape. Write L0 verbatim payloads under
`data/raw/oddsapi/...` before projecting. *Accept:* a capture writes L0 + legacy +
canonical; legacy h2h rows are byte-identical to before; the new families appear
with book counts ≥ what `normalize_event` computed. *Credits: 0.*

**P2 — The record.** `src/board/ids.py` (catalogue, `selection_id`),
`src/board/record.py` (`PriceObservation`), `src/board/settle.py`
(`SETTLEMENT_RULES` table), `docs/MARKET_CATALOGUE.md`. *Accept:* property tests
on identity stability (line as string, order-independence, no float in any id);
every catalogue entry has a settlement rule or is explicitly marked
`collection_blocked`.

**P3 — Backfill and unlock totals.** `src/board/rebuild.py` projecting
`odds_history/*.jsonl` (2023-25), `odds_snapshots.jsonl`, `odds_multibook.jsonl`,
`f5_close.jsonl` into L1. *Accept:* reconciliation report matching the measured
counts in §1 (133,330 / 123,224 for 2023 and so on); a coverage report showing
totals instants per game; deterministic re-run produces byte-identical output.
*Credits: 0.*

**P4 — Knowability.** `src/knowledge/event.py`, `src/knowledge/asof.py`, grade
assignment for every existing input, `grade_audit.jsonl`, import-guard and
path-allowlist tests. Add `transactions` to `src/model/pointintime.py`.
*Accept:* the probable-pitcher identity is grade **D** and the T-180 lineup
assumption is grade **D**, both printed as exposure counts; `as_of()` cannot open
a sealed path and a test proves it. *Gate G1.*

**P5 — Instrument.** `src/core/timing.py`; `timings` required on every artifact;
re-run the Phase 2B sweep shape to get its first real wall clock; record the
container baseline as a dated reference. *Accept:* an artifact without `timings`
fails validation; the "51 ms" claim is either confirmed with a measurement or
struck from `EVOLAB_DESIGN.md` with a note.

**P6 — The free environment.** Open-Meteo archive backfill for 2023-25 into
`data/knowledge/events/`; 30 park `orientation_deg` values with their source;
wind resolved to in/out/cross; transactions projected into `InformationEvent`.
*Accept:* historical weather coverage report by season; a wind classification
test against known park geometry. *Credits: 0.*

**P7 — Governance and cadence.** `src/capture/budget.py` with `DAILY_ENVELOPE`
and the coded drop order; reconcile the credit tier and write it into
`COLLECTION_POLICY.md` as a dated fact; correct the "3–4 books" prop figure to
the measured 7; repoint the default branch, add the repo secret, verify one
firing of `forward-capture.yml`; add `sonnet-implementer.md` and
`fable-orchestrator.md`. *Accept:* a simulated over-envelope day drops in the
written order and never touches Tier A; one bot-authored capture commit exists in
`git log`. *Gate G2.*

**P8 — Frames.** `src/board/frame.py` (binary packs, content addressing, mmap),
`src/board/fingerprint.py`, `data/index/board.sqlite` builder. *Accept:* a frame
rebuilt from the same inputs has the same fingerprint; changing one byte of one
L1 file changes it; frame build time is recorded.

**P9 — The reader feeds the engine.** `Snapshot`/`Board`/`Quote`; adapt
`src/evolab/decide.py` to consume a `Board` of selections rather than a two-way
dict, keeping the tie-break and refusal semantics unchanged; recursive forbidden-
name check. *Accept:* Phase 2B reproduces its published numbers through the new
reader (BELOW_PLACEBO_CEILING, percentile 13.3, PBO 0.6111) — a pure refactor
must not move a published result. *Gate G4 (first half).*

**P10 — Ledger v2.** `src/ledger/decision.py`, `settle.py`, `review.py`;
dedup on `(engine_version, system_id, game_pk, point_class)`; required `book`,
`price_american`, `counterarguments` on any play; hash-chained rows with
`verify_chain()` in CI; migrate the existing 427 rows forward without mutating
them. *Accept:* three decision rows for one game across three point classes;
`verify_chain()` green; the old rows still readable and unchanged.

**P11 — Settlement sources.** GUMBO boxscore / linescore / play-by-play readers;
ten graded examples per family intended for week-2 switch-on; closing threaded
into `Settlement.closing` from the sealed partition. *Accept:* `closing` non-null
on new settlements; `closing_backfill` marked as a migration-only kind. *Gate G3
for the families named.*

**P12 — Switch on Tier B.** F5 trio, alternates, team totals, three moments.
*Accept:* measured actual spend within ±15% of the `est_credits` model; L1 rows
present with book counts; a coverage report by family and moment. *Credits: ~+225/day.*

**P13 — Second market family, end to end.** Totals replayed through the same
engine over 2023-24 as a *registered* pre-registration exercise, with the battery
and the ceiling, published whatever it says. *Accept:* an artifact with
`total_searched()` at verdict, timings, exposure, and a plainly stated result —
including a null one.

**P14 — Switch on Tier C and publish the store state.** Pitcher and batter props
at two moments; a public store-state report: coverage by family, grade
distribution, credits spent, what is irrecoverable and from when. *Accept:* the
report exists, is dated, and names its own gaps. *Credits: ~+420/day.*

### 17.4 What the two weeks deliberately do not include

No new detectors. No mutation operators (G5 unmet). No rating (no calibrated
model exists). No product surface. No parlay code (G3 and §15.7 unmet). The two
weeks buy a store that can hold the vision and a reader that cannot leak — and
the free recovery of three seasons of a second market family, which is the
largest single increase in usable evidence available to this project at any
price.

---

## 18. OWNER DECISION QUEUE

1. **Credit envelope.** Approve raising `DAILY_ENVELOPE` from ~132 to ~1,000
   credits/day (§5.3) — ~29k/month against a measured ~99,634 balance. This is
   the decision that determines how much of the 2026 board exists in 2027.
2. **Tier.** Stay on the current tier for Phase D0/D1, or move to 5M ($119/mo)
   now to capture prop *repricing* around lineup posts? The repricing question is
   leaking today and cannot be recovered.
3. **Backtest scope, stated publicly.** Accept §15.3 — historical replay covers
   h2h and totals only; everything else is forward-only with a 2027 first verdict.
4. **Default branch.** Repoint so `forward-capture.yml` can fire; the hourly
   cadence currently depends on an interactive session.
5. **Prop history purchase.** The vendor sells prop history from ~May 2023 and a
   5-minute historical odds grid. Both are priced in `COLLECTION_POLICY.md` and
   gated behind a registered hypothesis. Do we register one now, or accept the
   permanent gap?
6. **`N_LOCK`** — the minimum forward sample before the LOCK label may ever be
   shown (§14.5). Set by power analysis, before the first good week, not after.
7. **Stake rule names** for the reporting-only account simulation (§13.4).
8. **Role roster.** Approve adding Sonnet and Fable role files and retagging the
   implementation-shaped Opus workers.

---

## 19. WHAT IS HARD, AND WHY — stated, not softened

1. **The 2023-24 board cannot be repaired.** No spreads, no props, no alternates,
   three to four instants per game, zero lineup posting times, a probable-pitcher
   identity that is 12–41× too clean. No amount of engineering changes this and
   no purchase fully repairs it. Every historical result carries that exposure and
   must print it.
2. **Cross-market comparison is genuinely hard**, not merely unimplemented. It
   requires calibrated probabilities on markets with different vig, depth,
   staleness and limits, and the failure mode (always picking the widest market)
   looks like success in a backtest.
3. **Multiplicity at factory scale is the real adversary.** The alpha registry is
   the right instrument and `semantic_hash_v0` only catches exact atom-set
   duplicates, which the project's own plan already flags. Clustering near-
   duplicates is an open problem and it determines whether `total_searched()`
   means anything.
4. **Prop settlement is a data-engineering job of real size** — per-player,
   per-game outcomes joined to per-book selections across name/id mismatches, on
   a board of thousands of selections a night. It is tractable, it is not small,
   and it must be done before the prices are worth collecting (G3).
5. **Grade-B bracketing is only as good as the polling cadence**, and the cadence
   currently depends on infrastructure that has never been observed to fire on its
   own. A bracket with a six-hour gap is a grade-C fact wearing a grade-B label.
6. **The forward ledger needs ~2 seasons to answer anything at n=300 selections**
   if the system remains as selective as it is today (144 recommendations, zero
   selections). Widening the board is the *only* honest way to accelerate that,
   and it is why §5 and §10 come before any engine work.
7. **SGP pricing may simply not be readable.** If so, the correct output is a
   dated negative finding, not a model of a price nobody can take.

---

## 20. CLOSING: THE ONE-SENTENCE VERSION

Fix the record — a selection, a line, a price, a book, a timestamp, and the
instant it became knowable — write it to an immutable raw layer before projecting
it, read it through one function that stops at T, compile it into content-addressed
frames, and every remaining question in the vision becomes a loop over rows,
a credit line item, or a gate. The engine and the factory are then not the hard
part; they are what the data makes possible.
