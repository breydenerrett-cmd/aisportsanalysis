# Multi-sport coupling audit (2026-08-31)

**Status: AUDIT ONLY. Nothing built, nothing changed. MLB remains the sole
beachhead; this document does not propose building NFL/NBA/NHL/soccer now.**

Companion: `docs/SAAS_APPLICATION_ARCHITECTURE.md` (domain objects, layers,
contracts). This audit assumes that document's `Dossier` / `Finding` /
`GameAnalysis` shapes and asks a narrower question: what in `src/` assumes
baseball, and how deep does the assumption run.

Note on churn: other workers are active across `src/`. This reads HEAD as
committed at audit time; nothing here looked mid-edit.

---

## 0. Classification key

- **STRUCTURAL** — the concept does not exist in other sports. Porting means
  building a new subsystem, not swapping a constant.
- **PARAMETRIC** — the concept generalises; the *value* (a table, a constant,
  a key) is MLB's. Porting means a new config/data file, same code shape.
- **INCIDENTAL** — naming only (`game_pk`, MLB API field names, baseball
  words in identifiers/comments). Costs nothing structurally; costs a
  find-and-replace and some reader confusion if left alone.

---

## 1. Module-by-module

### `src/providers/` — plumbing, mostly STRUCTURAL

| module | class | notes |
|---|---|---|
| `mlb.py` (511 lines) | **STRUCTURAL** | The whole module: MLB Stats API schedule, probable pitchers, final results, first-five-innings grading, pitcher game logs, innings-as-thirds parsing. Every function is baseball's own data model (`game_pk`, `codedGameState`, `gameType`, "five full innings"). 100% of this module does not exist for any other sport; a port is a full rewrite against a different API. |
| `statcast.py` / `statcast_pitches.py` (157 + 225 lines) | **STRUCTURAL** | Pitch-level Statcast and Baseball Savant arsenal leaderboards. Pitch-type/pitch-mix accumulation has no analogue in NBA/NFL/NHL and only a loose one in soccer (no per-event public feed as rich or as free). This is the deepest and most irreplaceable coupling in the providers layer — it is also the input the whole matchup-depth / platoon-mismatch machinery is built on. |
| `mlb_news.py` (229 lines) | **STRUCTURAL provider, PARAMETRIC shape** | Fetches MLB's own free transactions feed specifically because it is replayable/backtestable (the module's own stated design principle). The *principle* — prefer a dated, replayable feed over live narrative — transfers to every sport. The concrete feed (MLB transactions) does not; NFL/NBA/NHL each need their own equivalently-dated source, and none is guaranteed free and keyless the way this one is. |
| `odds.py` (794 lines) | **PARAMETRIC — cheapest provider to port** | `SPORT = "baseball_mlb"` (line 41) is a single Odds-API sport key; the API natively supports `basketball_nba`, `americanfootball_nfl`, `icehockey_nhl`, `soccer_*` on the same endpoint shape (`h2h`/`spreads`/`totals`). Comments reference "MLB regular season" length and "MLB first pitches" for snapshot cadence defaults — tunable constants, not different code. This is the one provider where "add a sport" really is close to changing one constant. |
| `weather.py` (280 lines) | **PARAMETRIC, and partly moot for indoor sports** | Open-Meteo lookup keyed by park coordinates. Transfers as-is to outdoor stadiums (NFL, soccer, MLB); the whole subsystem is irrelevant for NBA/NHL (indoor), which is a simplification, not a cost, for those sports. |

### `src/data/parks.py` (280 lines) — PARAMETRIC/STRUCTURAL hybrid

The 30-team coordinate/roof/altitude table and `canonical_team` alias
resolution are **PARAMETRIC** — same shape, new table, for any sport with
fixed home venues. `classify_wind` / `wind_effect` (carry-distance physics
tied to batted-ball flight) are **STRUCTURAL** to baseball; there is no
equivalent effect to model for NBA/NHL, and NFL/soccer wind effects (kicking,
long passes) would need their own model, not a reuse of this one.

### `src/core/` — clean, sport-agnostic (no action needed)

`odds.py` (de-vig math), `staking.py`, `calibration.py`: zero baseball
references. These are pure probability/pricing utilities and already carry
over unchanged to any sport with moneyline/spread/total markets.

### `src/analysis/` — DOMAIN layer, mixed

| module | class | notes |
|---|---|---|
| `synthesis.py` (766 lines) | **Sport-agnostic mechanism, STRUCTURAL vocabulary at the edges** | Ranking, dedup-by-fact-key, evidence labels, suppression trail — none of this is baseball-specific. The `FLOORS` sample-size table and the fact keys it dedupes (`"platoon:away"`, `"starter:home"`) are populated with baseball concepts, but the *mechanism* (rank, floor-check, suppress-with-reason) is the piece worth calling sport-agnostic. This is the single most reusable module in the analysis layer, matching the SaaS audit's own read. |
| `prices.py` (237 lines) | **Fully sport-agnostic** | Price improvement, de-vig, board assembly, the `LABEL` guarantee. Nothing here mentions baseball; it operates on `away_price`/`home_price` and a matchup key. Carries over unchanged. |
| `matchup.py` (485 lines) | **STRUCTURAL** | Matchup-depth decomposition — platoon share, primary-pitch mix, lineup-vs-starter — is baseball's specific "who does what to whom" model. The *pattern* (`sentences`/`absent`/`warnings`) is worth reusing; the content is not portable. |
| `relevance.py` (611 lines) | **Mostly sport-agnostic mechanism, STRUCTURAL event vocabulary** | Pre-event relevance tiers (`HIGH`/`MEDIUM`/`LOW`/`UNKNOWN`) and `tier_sentence`/`basis_lines` generalise to "a roster event changed something." The specific event classes scored (starter scratch, probable-pitcher swap, IL move) are baseball's transaction taxonomy; NFL/NBA have their own (QB questionable, star out, trade) that would need their own tier table, same shape. |

### `src/detect/` — the registry pattern is sport-agnostic; every registered detector is not

| module | class | notes |
|---|---|---|
| `base.py` (252 lines) | **Fully sport-agnostic** | `Finding`, the evidence ladder, `rank()`, `surprise_score()`. Baseball appears only in docstring examples ("3.80 ERA", batter-vs-pitcher). This is the wire format for the whole product and it does not know what sport it is describing. |
| `dossier.py` (244 lines) | **Structurally sport-agnostic; parametrically wired to baseball inputs** | The `Dossier` class itself (`game`, `information_time`, `sections`, `gaps`) has no sport dependency — see §3. What *populates* it (`src.pipeline.features`, `src.pipeline.pitchers`, `src.data.parks`, `src.core.odds`) is imported directly at module level, so today's `dossier.build()` is one specific sport's assembly function wearing a generic class. |
| `detectors.py` (934 lines) | **9 of 10 detectors are STRUCTURAL** | `ImpliedBullpenDisagreement`, `BullpenWorkload`, `StarterMismatch`, `PlatoonMismatch`, `ThinMatchupHistory`, `LineupVsStarter`, `ParkAndWeather`, `BullpenExposure`, `PitchMixMismatch` — all baseball concepts with no cross-sport equivalent (bullpen especially: no other major sport has a mid-game relief-pitching workload dynamic). Two are genuinely sport-agnostic and would port as-is: `StaleBook` (pure market arithmetic — one book off consensus, no game knowledge needed) and, more loosely, `TravelLoad` (schedule-fatigue is a real, differently-shaped signal in every sport, so this one is PARAMETRIC rather than fully portable). Roughly 80% of this module's line count is STRUCTURAL. |

### `src/pipeline/` — plumbing and orchestration; this is where the sport assumption is most load-bearing

| module | class | notes |
|---|---|---|
| `briefing.py` (386 lines) | **The orchestrator is baseball-shaped, not just baseball-fed** | `build_slate`'s own parameter list is the tell: `pitcher_logs`, `weather_by_pk`, `lineups_by_pk`, `bullpen_by_team`, `handedness`, `splits_by_pk`, `arsenals`, `batter_arsenals`. This is not "a generic slate builder that happens to be called with baseball data" — the function signature itself enumerates baseball's sections. Porting a sport does not mean writing a new provider behind the same `build_slate`; it means `build_slate` needs to become sport-parameterised (see §4). |
| `mismatch.py` (655 lines) | **STRUCTURAL market vocabulary, PARAMETRIC scan shell** | `starter_signal`/`roster_signal` are baseball features; `route_market` choosing between `MARKET_F5 = "first_five"` and `MARKET_FULL = "full_game"` is a baseball-specific market split (first-five-innings is an MLB betting product; the nearest NFL/NBA analogue would be a first-half or first-quarter line, a different market with different grading rules — see `mlb.py`'s `first_five_runs`). The verdict vocabulary (`no_play`/`candidate`/`flagged`/`market_unavailable`) and `scan_slate`/`finalize_slate` shell are sport-agnostic and worth keeping. |
| `slate.py`, `lineups.py`, `lineup_store.py`, `pitchers.py`, `bullpen.py`, `travel.py` | **STRUCTURAL to heavily PARAMETRIC** | `lineups.py`/`pitchers.py`/`bullpen.py` are wholly baseball (starters, platoon splits, bullpen workload — STRUCTURAL). `slate.py`'s `team_abbrev_from_name` is a hardcoded 30-name lookup table (PARAMETRIC — same function shape, new table, for any fixed-roster league). `travel.py` (rest days, distance since last game) is PARAMETRIC and arguably transfers with *more* signal value to NBA (back-to-backs) than it has in MLB. |
| `features.py` (407 lines) | **Sport-agnostic mechanism** | `team_features`/`matchup_features`/`_rest_days`/`_streak`/`games_before` — win/loss, rest, streak accumulation over a results store. Nothing here is baseball-specific; it operates on any store of `{away_team, home_team, away_score, home_score, date}` rows. One of the cleanest reuse candidates in the repo. |
| `history.py`, `snapshots.py`, `ledger.py`, `rosterwatch.py`, `dense.py`, `health.py` | **PARAMETRIC infrastructure carrying one STRUCTURAL/deep-PARAMETRIC assumption each** | The store-append, capture-cadence, and health-check *mechanisms* are sport-agnostic (append-only JSONL, "is collection quietly broken", polling and diffing). But `snapshots.py`, `rosterwatch.py`, and `prop_listing.py` each hardcode `ZoneInfo("America/New_York")` for **official-date rollover** — the rule that a game is filed under its Eastern date regardless of UTC start time. That is an MLB (and generally US-major-league) scheduling convention, duplicated three times, not derived from a sport config. It is PARAMETRIC (every US league needs *some* rollover timezone; European soccer needs none, or a different one) but currently hardcoded three separate places rather than centralised — see §4. `rosterwatch.py`'s event classes (probable-pitcher swap, lineup post, injured-list move) are STRUCTURAL to baseball's transaction taxonomy. |
| `grading.py`, `predict.py`, `scanlog.py`, `backfill.py` | **Mostly sport-agnostic; season bounds are the one hardcode** | Low baseball-word density (see counts below). `backfill.py`'s `SEASON_START = (3, 20)` / `SEASON_END = (10, 5)` is a clean PARAMETRIC constant — every sport has season bounds, MLB's happen to be March–October. |
| `prop_listing.py` | **INTERNAL, not customer-facing (per SaaS audit); STRUCTURAL content, feasibility-probe shell** | The probe mechanism (budget cap, kill switch) is sport-agnostic; what it probes (player prop markets keyed to MLB rosters) is not. |

Rough proportions (baseball-word grep hits / total lines, a coarse but
directionally honest proxy):

| module | hits | lines | reading |
|---|---|---|---|
| `providers/mlb.py` | — | 511 | ~100% structural |
| `detect/detectors.py` | 125 | 934 | ~80% structural |
| `pipeline/health.py` | 77 | 964 | low density; mechanism generic |
| `pipeline/rosterwatch.py` | 62 | 580 | event taxonomy structural, poller generic |
| `report/dashboard.py` | 67 | 1250 | narrative content baseball-heavy, HTML shell generic |
| `pipeline/ledger.py` | 27 | 372 | mostly generic append/settle |
| `pipeline/history.py` | 23 | 471 | mostly generic store reader |
| `pipeline/snapshots.py` | 5 | 519 | almost entirely generic; one hardcoded timezone rule |
| `pipeline/grading.py` | 4 | 388 | almost entirely generic |
| `core/*.py` | 0 | ~840 | fully generic |
| `report/ranker.py` | 0 | 175 | fully generic |
| `model/logistic.py` | 0 | 252 | fully generic |

### `src/report/`

`dashboard.py` (1250 lines) carries the same baseball-word density as the
pipeline layer (67 hits) but for a different reason than `detectors.py`: per
the SaaS audit (§2 there), most of that is business logic that should not be
in the renderer *at all*, sport aside — sentences like the thin-starter
narrative and the price-improvement note are hardcoded prose keyed to
baseball facts. Fixing the domain/presentation leak (already planned,
independent of multi-sport) and fixing the sport coupling are the same piece
of work: once those sentences move into `analysis/` as data-driven templates,
making them sport-aware is a template-selection problem, not a rewrite.
`ranker.py` and `archive.py` are clean of baseball coupling (0 hits) —
`ranker.py` is gated by `ENGINE2 = None` and never touches game facts, and
`archive.py`'s coupling is to `dashboard.py`'s HTML shape, not to the sport.

### `src/model/`

`bullpen_grade.py` (STRUCTURAL — no non-baseball analogue), `dataset.py` and
`selections.py` (PARAMETRIC — feature-name lists baked in but the row-shape
and CV/selection machinery is generic), `rebuilt_sections.py` (STRUCTURAL —
platoon/BvP point-in-time rebuild), `pointintime.py` (PARAMETRIC mechanism —
the CLEAN/LEAKY registry is a generic `{section: {status, why}}` dict
populated with baseball section names; the *discipline* is the reusable
part), `logistic.py`, `discovery.py`, `family.py`, `seal.py` (fully generic).
All of `src/model/` is INTERNAL per the SaaS audit regardless of sport.

### `src/research/` and `src/evolab/` — confirmed largely sport-agnostic, as the brief expected

- `research/battery.py` (524 lines, 0 baseball hits) — the falsification
  battery operates purely on selections and outcomes. Fully generic.
- `research/funnel.py` (716 lines) — the SPEC/hypothesis-funnel *machinery*
  is generic; `NUMERIC_FEATURES` (13 hits) is a baseball feature-name tuple,
  swappable per sport.
- `research/matrix.py` (465 lines, 85 hits) — the heaviest-coupled research
  module: it builds the baseball feature matrix directly (batter totals,
  wOBA pooling, lineup slots, handedness). This is a per-sport feature
  builder, not generic research infrastructure, and should not be read as
  "the research layer is sport-agnostic" without this carve-out.
- `evolab/*` — `decide.py`, `placebo.py`, `cscv.py`, `spa.py`, `bitsets.py`,
  `ceiling.py` are fully generic (statistical selection machinery over
  scored candidates). `genome.py`, `baseline.py`, `registry.py` carry
  moderate baseball-word density because they enumerate the feature/gene
  catalogue by name — PARAMETRIC. `replay.py` (1462 lines, 82 hits) is the
  point-in-time leak-audit: the leak-class mechanism (A/B/C/D availability
  classes, replay tests) is generic; the specific feature-to-class
  assignments (`"starter_platoon_gap": "C"`, etc.) are baseball's own audit
  and would need re-doing, not reusing, per sport — but the *method* the
  audit itself uses is exactly what a second sport's point-in-time audit
  should follow.

Net: the brief's expectation holds, with one correction — `research/matrix.py`
is a per-sport feature builder mislabeled by its own generality as "the
research layer," and should be budgeted as porting cost, not free carryover.

---

## 2. Summary table

| subsystem | verdict | ~% structural |
|---|---|---|
| `providers/mlb.py`, `statcast*.py` | STRUCTURAL | 100% |
| `providers/mlb_news.py` | STRUCTURAL provider / PARAMETRIC principle | 90% |
| `providers/odds.py` | PARAMETRIC | 5% (one constant, some tuning comments) |
| `providers/weather.py` | PARAMETRIC (moot for indoor sports) | 10% |
| `data/parks.py` | half PARAMETRIC (table), half STRUCTURAL (wind physics) | 50% |
| `core/*` | sport-agnostic | 0% |
| `analysis/synthesis.py`, `prices.py` | sport-agnostic mechanism | 0-10% |
| `analysis/matchup.py` | STRUCTURAL | 90% |
| `analysis/relevance.py` | mechanism generic, event taxonomy STRUCTURAL | 30% |
| `detect/base.py` | sport-agnostic | 0% |
| `detect/dossier.py` | class generic, wiring STRUCTURAL | 40% |
| `detect/detectors.py` | STRUCTURAL (9/10 detectors) | 80% |
| `pipeline/briefing.py` | orchestrator signature is baseball-shaped | 60% |
| `pipeline/mismatch.py` | market vocabulary STRUCTURAL, shell generic | 40% |
| `pipeline/{lineups,pitchers,bullpen}.py` | STRUCTURAL | 90% |
| `pipeline/{slate,travel}.py` | PARAMETRIC | 20% |
| `pipeline/features.py` | sport-agnostic | 0% |
| `pipeline/{history,snapshots,ledger,health,dense,rosterwatch}.py` | PARAMETRIC infra + one hardcoded convention | 15-25% |
| `pipeline/{grading,predict,scanlog,backfill}.py` | mostly generic, season-bounds constant | 5-10% |
| `report/dashboard.py` | presentation-layer bug (SaaS audit) + baseball prose | n/a — fix once |
| `report/{ranker,archive}.py` | sport-agnostic | 0% |
| `model/*` | mostly generic mechanism, some STRUCTURAL feature builders | 20% |
| `research/battery.py`, `evolab/{decide,placebo,cscv,spa,bitsets,ceiling}.py` | sport-agnostic | 0% |
| `research/{funnel,matrix}.py`, `evolab/{genome,baseline,registry,replay}.py` | mechanism generic, feature catalogue STRUCTURAL/PARAMETRIC | 20-90% (matrix.py highest) |

---

## 3. Where should the sport boundary live?

**The domain objects survive; the orchestration and the detector registry do
not, as written today.**

`Finding` (`detect/base.py`) and `Dossier` (`detect/dossier.py`'s class, not
its `build()` function) are already sport-neutral — neither imports or
references anything baseball-specific. `GameAnalysis`/`Slate`/`PriceComparison`
as specified in the SaaS audit's §4 contracts are shaped around
`{sections, gaps}`, `Claim`, `EvidenceLabel` — none of which name a sport.
**These would not need to change for a second sport.**

What would leak baseball into the contracts today, if a second sport were
added without first drawing a boundary:

1. `Dossier.sections` keys are freeform strings chosen by the caller
   (`dossier.build()` in practice), not an enum — so nothing stops a second
   sport from inventing its own section names, but nothing enforces a shared
   *shape* across sports either. A client that renders "starters" specially
   would need to know that hockey calls the analogous section "goalies."
2. `briefing.build_slate`'s parameter list (`pitcher_logs`, `bullpen_by_team`,
   `handedness`, `arsenals`, ...) is not a slate builder that takes a sport
   plugin — it *is* the MLB plugin, inlined as keyword arguments. A second
   sport cannot call this function; it needs its own `build_slate`, and nothing
   today would keep the two from drifting in verdict logic, price-improvement
   handling, or synthesis policy, all of which live in this one function.
3. `detect/detectors.py`'s `register_defaults()` presumably registers the
   baseball nine unconditionally (not confirmed line-by-line here, but the
   module has no sport parameter anywhere) — there is no registry-per-sport
   concept, so "MLB detectors" and "the detector registry" are currently the
   same thing.
4. The market vocabulary (`first_five`/`full_game` in `mismatch.py`,
   `h2h`/`spreads`/`totals` in `odds.py`) is partly shared (the Odds-API
   markets are already sport-generic) and partly baseball-specific
   (`first_five` has no direct analogue — a first-half or first-quarter line
   is a different grading rule, not a renamed constant).

**Recommendation:** the sport boundary should be a **bundle object**, not a
scattered set of `if sport == "mlb"` checks and not a directory-per-sport
duplication of the orchestrator. Concretely, a `SportProfile` (or similar)
supplying:

- a **provider set** (schedule/results fetcher, odds `sport` key, a "roster
  event" feed, optionally weather/venue) — this is already close to how
  `providers/` is organized; it mainly needs a registration point instead of
  `briefing.py` importing `src.pipeline.pitchers` etc. by name;
- a **dossier-section builder list** — the functions that turn provider
  output into `Dossier.sections` entries, replacing today's fixed keyword
  list in `build_slate`;
- a **detector registry** — a `register_defaults()` per sport, so
  `detect.rank()`/`Finding` stay shared but *which* detectors run is a sport
  choice, not a hardcoded call;
- a **market list** — which markets exist, how they're graded, and the
  market-routing rule (today `route_market`'s F5/full-game split; a second
  sport needs its own or none);
- a **scheduling convention** — season bounds, official-date rollover
  timezone, slate cadence (daily for MLB/NBA, weekly for NFL) — currently the
  three hardcoded `ZoneInfo("America/New_York")` sites and the two
  `SEASON_START`/`SEASON_END` tuples, which should become one config object
  read in one place instead of copy-pasted per module.

`briefing.build_slate` becomes `build_slate(games, store, sport_profile, ...)`
— same `Dossier`/`Finding`/contract shapes downstream, different assembly
inputs upstream. `detect/base.py`, `analysis/prices.py`,
`analysis/synthesis.py`, `core/*` need **no changes** under this design; they
are already behind the boundary. The SaaS contracts in
`docs/SAAS_APPLICATION_ARCHITECTURE.md` would gain one field they do not
currently have: a `sport` tag on `GameRef`/`Slate`, plumbed through from day
one even while only `"mlb"` exists, so it is not a breaking contract change
later.

---

## 4. Cost sketch: which sport is cheapest second, and why

**NBA, on the evidence of what providers and cadence already exist — not on vibes.**

Reasoning, from what this audit actually found:

- **Odds provider is nearly free.** `providers/odds.py`'s `SPORT` constant is
  literally `basketball_nba` on the same Odds-API host, same `h2h`/
  `spreads`/`totals` shape, same credit-accounting code. This is the one
  piece of the stack that is a same-day change for NBA and a bigger lift for
  soccer (different market conventions — Asian handicaps, draw-inclusive
  moneylines — that the current `odds.py` does not model).
- **Cadence matches.** NBA runs a daily slate, like MLB — `slate.py`,
  `rosterwatch.py`'s daily poll-and-diff, and `snapshots.py`'s per-slate
  capture model transfer with a cadence-tuning change, not a redesign. NFL's
  weekly cadence would force redesigning `rosterwatch.py`'s "poll several
  times a day, diff against the last poll" model and `dense.py`'s missed-
  window accounting, both built around a game happening most days.
- **Losing the weather/park subsystem is a simplification, not a cost.** NBA
  is indoor; `weather.py` and half of `parks.py` (the wind-physics half)
  simply do not apply, which removes a subsystem rather than requiring a new
  one — an unusual case where "sport differs structurally" cuts the
  portability cost rather than raising it.
- **`features.py` (team form: rest days, streaks, win/loss rates) carries
  over with, if anything, more signal — NBA back-to-backs are a well-known,
  large effect, larger than MLB's day-game-after-night-game fatigue that
  `travel.py` already tracks. This is a rare case of a PARAMETRIC module
  getting *more* useful in the second sport, not just as useful.
- **What does NOT carry over, and is real, structural cost:** the entire
  bullpen/starter/platoon/pitch-mix detector family (§1, ~80% of
  `detectors.py`) has no NBA analogue and would need genuinely new detectors
  (foul-trouble/rotation depth, lineup-on-court net rating, injury-report
  tiering) built from scratch against new data. `providers/mlb.py`'s
  replacement — an equally free, keyless, historically-deep NBA schedule
  and box-score source — is not something this audit can confirm exists
  with MLB Stats API's specific properties (free, no key, ~7000 historical
  games fetchable in an afternoon); `stats.nba.com`'s unofficial endpoints
  and Basketball-Reference are the realistic candidates and both carry more
  friction (rate limits, scraping fragility) than the MLB Stats API this
  project was built against. That is the honest asterisk on "cheapest": the
  odds/cadence/venue wins are real and provider-verified; the results/box-
  score provider win is not, and would need its own probe (in the manner of
  `prop_listing.py`'s feasibility audits) before being assumed.
- **NFL, for comparison:** wins on outdoor-weather transfer (the whole
  `parks.py`/`weather.py` subsystem applies almost unchanged) and loses on
  cadence (weekly, breaking the daily-poll assumption threaded through
  `rosterwatch.py`/`dense.py`/`health.py`) and on the daily-slate volume this
  research infrastructure (`funnel.py`, `matrix.py`, the falsification
  battery) was tuned to accumulate sample against — a 16-to-17-game NFL
  season per team produces roughly 1/10th the games-per-season MLB does,
  which matters directly to every module in `research/` and `evolab/` that
  depends on sample size to clear a floor.

**Bottom line:** NBA is the cheaper second sport primarily because the
*infrastructure* (odds ingestion, capture cadence, team-form features)
transfers with near-zero redesign, and because losing the weather/park
subsystem is free rather than costly. The *signal* layer (detectors,
matchup depth, point-in-time discipline) is genuinely structural work either
way, is comparable in size for NBA or NFL, and is not what makes one sport
cheaper than the other here.

---

## 5. Unresolved questions

- Whether an equally free, keyless, deep-history results/box-score provider
  exists for NBA (the MLB Stats API's specific properties are unusually
  good and may not have an NBA equivalent) — needs a feasibility probe, not
  assumed by this audit.
- Whether `Dossier.sections` should become an enum/schema per sport or stay
  freeform strings — freeform is simpler today and has caused no observed
  bug, but a second sport is exactly the pressure that would surface one.
- Whether the market-routing concept (`first_five`/`full_game`) generalises
  to "any sub-game-window market" cleanly enough to share code with an NFL
  first-half or NBA first-quarter line, or whether each sport's window
  markets need their own routing function with no shared abstraction beyond
  the verdict vocabulary.
