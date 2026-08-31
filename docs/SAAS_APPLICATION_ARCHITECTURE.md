# SaaS application architecture — audit and plan (2026-08-31)

**Status: PLAN AND AUDIT ONLY. Nothing was built. No code was changed.**
Test suite before and after: `1954 tests, OK`.

Companion documents:
- `docs/PRODUCT_ARCHITECTURE_AUDIT.md` — establishes that there is no
  deployable application at all. Read it first; this document assumes it.
- `PRODUCT_DESIGN_HANDOFF.md` (being written elsewhere) — the screens and the
  customer-facing language. This document deliberately says nothing about UI.

A later build agent should be able to read the two together and construct the
application without re-deriving any of what follows.

---

## 0. The one-paragraph answer

The engine is already separated into domain and presentation, and the seam is
real: `src/pipeline/briefing.build_slate` assembles structured per-game
entries and `src/report/dashboard.render` turns them into HTML. That seam is
about eighty percent of an API. The remaining twenty percent is the problem:
`dashboard.py` does not merely render the entries, it **completes** them —
deriving synthesis when absent, assembling the price-improvement narrative,
choosing which card opens, minting evidence-label text, and writing several
of the product's most important sentences as string literals inside `<p>`
tags. Any API built today by calling `build_slate` and serialising it would
be a **strictly less honest** product than the HTML page, because the
warnings live in the renderer. Extracting them is the first task, and it is
prerequisite to everything else.

---

## 1. Domain versus presentation, module by module

Classification key:

- **DOMAIN** — reusable business logic. Belongs in the CORE ANALYSIS ENGINE
  layer, importable by the API.
- **PRESENTATION** — turns domain objects into a surface. Must never be
  imported by the API.
- **PLUMBING** — data acquisition, storage, point-in-time discipline.
  Importable by the API, but only through the domain layer for reads.
- **INTERNAL** — research/admin. Never reachable from a customer request.

### `src/analysis/`

| module | class | notes |
|---|---|---|
| `synthesis.py` | **DOMAIN** | The single most valuable reusable module in the repo. Ranks candidates, dedupes by fact key, attaches sample sizes and evidence labels, records the suppression trail. Returns a plain dict on purpose ("so the dashboard can render it and `_plain` can serialise it without knowing anything about this module"). It is already an API response in all but name. |
| `prices.py` | **DOMAIN** | Price improvement, de-vigged consensus, board assembly. Carries its own `LABEL` on every returned dict — the anti-EV guarantee is structural here, which is exactly right. |
| `matchup.py` | **DOMAIN** | Matchup-depth decomposition. Emits `sentences` / `absent` / `warnings` lists — pre-written prose. See §2.7: this is domain logic that has already crossed into copywriting, and the contract must preserve that. |
| `relevance.py` | **DOMAIN** | Pre-event relevance tiers for roster events, plus `tier_sentence`, `basis_lines`, `what_changed`. Same note as above. |
| `__init__.py` | **DOMAIN** | Holds `HYPOTHESES_TESTED` / `HYPOTHESIS_FAMILIES` and their word forms. One source of truth for the count that three surfaces previously disagreed about. **The API must read the count from here and nowhere else.** |

### `src/detect/`

| module | class | notes |
|---|---|---|
| `base.py` | **DOMAIN** | The `Finding` contract, the evidence ladder, `rank()`, `surprise_score()`. This is the schema the whole product rests on. `Finding.__slots__` is effectively the wire format for a finding. |
| `dossier.py` | **DOMAIN** | **The real domain object.** See §1.1. |
| `detectors.py` | **DOMAIN** | The registered hypothesis family. The registry doubling as the pre-registration list is a deliberate constraint the API must not break (§6). |

### `src/pipeline/`

| module | class | notes |
|---|---|---|
| `briefing.py` | **DOMAIN** | `build_slate` is the slate service, today. `what_changed_by_pk` is the "what changed" service, today. Both are already correctly shaped. |
| `mismatch.py` | **DOMAIN** | Verdict vocabulary and the scan. Verdicts are `flagged` / `candidate` / `no_play` / `market_unavailable`, plus market routing `first_five` / `full_game`. |
| `slate.py`, `lineups.py`, `lineup_store.py`, `news.py`, `pitchers.py`, `features.py`, `bullpen.py`, `travel.py`, `rebuilt.py`, `snapshots.py`, `history.py` | **PLUMBING** | Fetch, normalise, store, and read back point-in-time. The API reads these only through `briefing`/`dossier`. |
| `ledger.py` | **PLUMBING / INTERNAL** | Forward ledger — append-only evidence of what was said before games. Customer-facing only in aggregate ("our record"), never as a per-row admin view. |
| `grading.py`, `scanlog.py`, `predict.py`, `backfill.py` | **INTERNAL** | |
| `health.py`, `dense.py`, `rosterwatch.py`, `prop_listing.py` | **INTERNAL** | (Not inspected in depth — other workers active. `rosterwatch` is read *through* `briefing.what_changed_by_pk`, which is the correct arm's-length coupling.) |

### `src/report/`

| module | class | notes |
|---|---|---|
| `dashboard.py` | **PRESENTATION, contaminated** | ~1255 lines, of which ~600 are HTML/CSS and the rest is a mix. See §2. |
| `ranker.py` | **PRESENTATION, gated** | `ENGINE2 = None`. See §8. |
| `archive.py` | **PRESENTATION** | Parses HTML artifacts back into an index. This is a *reverse* dependency on the renderer's output format and must not survive into the API — the API reads the store, not the pages. |

### `src/model/`, `src/research/`, `src/evolab/`

**INTERNAL**, all of it, with one exception: `src/model/pointintime.py` and
`src/model/seal.py` express constraints the API depends on being true, but the
API never calls them.

### `src/core/`, `src/data/`, `src/providers/`

`core/odds.py` and `data/parks.py` are **DOMAIN** utilities. `core/staking.py`
is **INTERNAL** and must stay that way — see §8. `providers/` is **PLUMBING**
and must never be called from a request path (network calls with API-credit
cost inside an HTTP handler is how a customer's page load spends money).

### 1.1 The real domain object

**It is `Dossier`, and it already has the right shape.**

```python
class Dossier:
    game               # dict: the identity — teams, date, game_pk, venue, start
    information_time   # datetime: the instant this is true as of
    sections           # {name: data} — what is known
    gaps               # {name: reason} — what is not known, AND WHY
```

The `sections`/`gaps` split is the single best structural decision in the
codebase and it must be carried into every API contract verbatim. Its docstring
states the reason: *"A section that silently never appears is
indistinguishable from one that was never attempted."* An API that returns
`{"lineups": null}` destroys that distinction; an API that returns
`{"sections": {...}, "gaps": {"lineups": "lineup not posted yet, or not
fetched"}}` preserves it. **`gaps` is a first-class response field, not an
error channel.**

`Dossier.to_dict()` already exists and already serialises correctly. It is the
foundation of the `Game` contract in §4.

The composite object above it — the `entry` dict that `build_slate` appends —
is the second domain object, and it is currently anonymous:

```python
{"dossier", "findings", "synthesis", "verdict", "side", "market", "summary", "scan"}
```

That should become a named type (`GameAnalysis`). It is what every service in
§3 either returns or is built from.

### 1.2 Where the seam leaks

Five leaks, in order of severity:

1. **`dashboard.py` computes synthesis when the entry lacks it**
   (`_payload`, lines 160-163). The `analyze` path and every hand-built slate
   get their summary *from the renderer*. Two callers therefore produce
   different objects for the same game depending on which one ran.
   → §2.1.
2. **`dashboard.py` owns product sentences.** `_STANDING`,
   `NO_IMPROVEMENT_NOTE`, the thin-starter paragraph, the hypothetical-game
   banner, the no-signal lead text. These are product claims, not layout.
   → §2.
3. **`HYPOTHETICAL_GAP` is defined twice** — `src/cli.py:696` and
   `src/report/dashboard.py:53` — pinned equal by a test, with a comment
   explaining that the report layer cannot import the CLI. Correct today;
   wrong once an API exists, because the API is a third caller that would need
   a fourth copy. → §2.9.
4. **`EVIDENCE_LABELS` is defined twice**, in `dashboard.py:76` and
   `synthesis.py:167`, and they are *not* the same dict — synthesis carries an
   extra `OBSERVED` entry. Two surfaces, two vocabularies, no test pinning
   them. → §2.5, and this is a real latent bug.
5. **`archive.py` reads HTML back.** The index depends on the renderer's
   output, so the renderer's markup is load-bearing data. The API must get
   its archive from the ledger/store instead.

---

## 2. Business logic trapped in `dashboard.py`

Enumerated exhaustively. **Pain** is the cost to move: LOW = pure lift,
MEDIUM = needs a new field or a test rewrite, HIGH = needs a design decision
about where it belongs.

### 2.1 Synthesis derivation — `_payload`, lines 158-163 · **worst offender** · pain MEDIUM

```python
summary = entry.get("synthesis")
if summary is None:
    summary = synthesis_mod.synthesize(dossier, findings)
```

The renderer decides whether the game gets a summary. Two production paths
(`brief` populates it in `build_slate`; `analyze` does not) therefore have
different domain objects, and the difference is invisible until something
renders them. Any API that serialises a `build_slate` entry without going
through the dashboard silently loses synthesis on the `analyze` path.

**Belongs in:** `briefing.build_slate` unconditionally, which already does it
for the slate path — the fix is to make the `analyze` path go through the same
code rather than to make the renderer compensate.
**Pain MEDIUM:** the fallback is load-bearing for tests that construct
one-game slates by hand; those tests must be given synthesis or given a
constructor helper.

### 2.2 Price-improvement section assembly — `_price_improvement_section`, lines 738-804 · **second worst** · pain HIGH

The function does five things that are not rendering:

- decides whether *any* side beats consensus (`any_positive`) — a derived
  boolean the domain never computes;
- attaches `NO_IMPROVEMENT_NOTE` (lines 287-292) conditionally on it — a
  120-word explanation of why a column of negatives is arithmetic and not a
  bad night. **This is the single most important piece of anti-misreading
  copy in the product and it exists only inside the HTML generator;**
- converts probability fractions to win-probability points (`_prob_points`),
  a unit decision the docstring records as a past bug;
- decides the capture-instant sentence (`when`) including the honest
  "(capture instant not recorded)" fallback;
- renders `section["label"]` — the never-call-it-EV guarantee — as decoration
  appended to a `<p class="gap">`.

**Belongs in:** `src/analysis/prices.py`. `snapshot()` should return
`any_positive`, `note`, and keep `label` mandatory. The renderer should have
no opinion about the sign of the column.
**Pain HIGH:** the same logic is duplicated in `ranker.py` (`ALL_NEGATIVE_NOTE`
/ `SOME_POSITIVE_NOTE`, lines 60-66, and its own `_prob_points`), so the
extraction has to unify two surfaces and their tests at once. Doing it wrong
lets the two pages disagree about the sign of the same board — which is the
exact class of bug `boards_by_matchup` was written to end.

### 2.3 The suppression trail's presentation contract — `_suppressed_section`, lines 436-463 · **third worst** · pain LOW

The renderer decides that a suppressed item with no recorded reason prints
"no reason recorded", and decides that the whole trail is collapsed rather
than shown. The first is a domain guarantee (an audit trail entry always has
a reason, or says it does not); the second is genuinely presentation.

**Belongs in:** `synthesis.synthesize` should guarantee every `suppressed`
entry carries a non-empty `reason`, so no consumer can render a bare cut.
**Pain LOW:** additive.

### 2.4 The lead / "most unusual on this slate" ranking — `_lead`, lines 379-433 · pain MEDIUM

A full ranking algorithm inside the renderer: filter out `context` findings,
sort by `(kind, -surprise)`, take one finding per detector, cap at six. Plus
the branch that counts context findings and writes the "No side-pointing
finding on this slate" paragraph, whose comment records a real past bug where
the page said no detector found anything while a card below listed a 2.0-sigma
finding.

**Belongs in:** a new `synthesis.slate_lead(entries, limit=6)`. It is
slate-level synthesis and it belongs beside game-level synthesis.
**Pain MEDIUM:** needs the anchor/permalink identity to come from the domain
(§2.8) so the lead can reference games without knowing about HTML fragments.

### 2.5 Evidence-label vocabulary — `EVIDENCE_LABELS`, lines 76-86 · pain LOW, but urgent

A second copy of `synthesis.EVIDENCE_LABELS`, missing the `OBSERVED` entry.
`_finding()` looks up in the dashboard copy; synthesis items carry labels
minted from the synthesis copy. Nothing pins them equal. A price item and a
detector item on the same card get their labels from two different dicts.

**Belongs in:** one module — `src/detect/base.py` (it owns the ladder) or a
new `src/analysis/evidence.py`. Everything else imports it.
**Pain LOW** and it should be done first, because §4's contract cannot be
written honestly while two vocabularies exist.

### 2.6 The thin-starter narrative — `_starters_section`, lines 578-614 · pain MEDIUM

Computes `thin_sides`, `thin_teams`, and `thin_has_splits`, then assembles a
two-clause sentence whose second clause only appears when a thin starter
nevertheless has split rows. The comment records the bug: a blanket "his rates
are suppressed" sentence sitting directly above a table quoting him at .535
OPS on 23 batters faced.

**Belongs in:** `src/pipeline/pitchers.py` or a small
`analysis/starters.py` — the *fact* ("this starter is thin, and here is what
we do and do not show for him") is domain; the sentence is presentation but
must be derived from that fact, not re-derived from the rendered table.
**Pain MEDIUM:** requires a new `thin` sub-object on the starters section.

### 2.7 Suppression and silence decisions — several sites · pain MEDIUM

The renderer decides what does *not* appear:

- `_what_changed_section` (807-849) returns `""` on no events — but
  `dossier.py` lines 136-144 already made that decision by not adding the
  section at all. Two layers implementing the same policy.
- `_news_section` (852-878) returns a gap block when `blocks` is empty even
  though `news` was present — i.e. it distinguishes "not fetched" from
  "fetched, nothing in the window" *in the renderer*.
- `_environment_section` (897-916) decides that a park with no
  `orientation_deg` gets the "wind direction is not interpreted" warning.
  That is a data-quality claim, not layout.

**Belongs in:** each owning section builder, expressed as a `gaps` entry or a
`warnings` list — the pattern `matchup.py` already uses
(`sentences`/`absent`/`warnings`). Making every section speak that shape is
the cleanest single unification available.
**Pain MEDIUM** per site, LOW risk.

### 2.8 Permalink identity — `_slug` / `_anchor_base` / `_assign_anchors`, lines 114-150 · pain LOW

A stable per-game identifier derived from clubs + date, with doubleheader
disambiguation by game number then `game_pk`, and an `anchor_unstable` flag
when even that fails. This is an **entity identity scheme** — it is the
closest thing the project has to a public game ID and the API needs exactly
it for `/games/{game_id}`.

**Belongs in:** `src/pipeline/briefing.py` or a new `src/domain/ids.py`. The
API's game id and the HTML anchor should be the same string, so a URL and a
fragment name the same game.
**Pain LOW** — pure lift, no behaviour change, and it makes the API's routing
free.

### 2.9 Hypothetical-matchup detection — `_is_hypothetical` / `_hypothetical_banner`, lines 927-950 · pain LOW

The renderer infers "this game never happened" by string-matching
`HYPOTHETICAL_GAP` against two gap reasons, and then writes the "**This game
does not exist.**" banner. The comment is explicit that the artifact outlives
the terminal line — correct reasoning, wrong layer. An API response for a
hypothetical matchup currently has *no structured way to say so*: the caller
would have to string-match the same sentence.

**Belongs in:** the `GameAnalysis` object as a boolean `hypothetical` field,
set by whoever builds the game (today `cmd_analyze`).
**Pain LOW** and it is a **hard blocker for the matchup service** (§3.3) —
without it the API ships fabricated-looking analysis of games that were never
played.

### 2.10 Card-opening choice — `_document`, lines 1058-1069 · pain LOW

Scores every game (`max signal surprise`, `+100` if not `no_play`) to decide
which card renders expanded. Genuine presentation, but the score is a
slate-level interestingness ranking that duplicates `_lead`'s ordering on a
different formula. Fold it into §2.4 and let the renderer open `lead[0]`.

### 2.11 The standing disclaimer — `_STANDING`, lines 64-74 · pain LOW

The product's central claim ("Nothing on this page is a proven edge…"),
formatted with HTML entities, living in the renderer. Every future surface —
web, email, mobile, API consumer — needs this sentence and must not retype it.

**Belongs in:** `src/analysis/__init__.py`, beside the counts it interpolates,
as plain text with the renderer doing the entity escaping.

### 2.12 Sample-string interrogation — `_finding_row`, lines 362-368 · pain LOW

The renderer asks `synthesis_mod.sample_size(...)` and, when it is `None`,
prints "no sample size stated" instead of the word "sample". This is the
credibility rule of §4 implemented **in the renderer**, per finding, per
surface. It is the strongest possible argument for §4's contract design:
a consumer that forgets this check produces a number wearing borrowed
credibility.

**Belongs in:** the `Finding` → wire conversion, which must emit
`sample_n: int | null` alongside `sample: str | null` so no consumer can get
it wrong. See §4.6.

### Ranked summary of the three worst

1. **§2.1 synthesis derivation** — makes the domain object depend on which
   renderer ran.
2. **§2.2 price-improvement assembly** — the anti-misreading copy and the
   sign logic live in HTML, duplicated in a second HTML generator.
3. **§2.3 / §2.12 the sample-and-label pairing** — the product's credibility
   rule is enforced by the renderer rather than by the contract.

---

## 3. Canonical service interfaces

Notation: `→` output contract from §4. "Exists" means the logic exists, not
that an interface does.

### 3.1 `get_slate(date, information_time=None) → Slate`

Tonight's (or any date's) games with verdicts, synthesis, findings and gaps.

- **Exists:** yes, `briefing.build_slate` (`src/pipeline/briefing.py:24`).
- **Missing:** the slate-level lead (§2.4, trapped in `_lead`); a stable game
  id on each entry (§2.8); a guarantee that synthesis is always populated
  (§2.1). All three are extractions, not new logic.
- **Compute shape:** PRECOMPUTED. Never computed in a request.

### 3.2 `get_game(game_id) → GameAnalysis`

One game's full analysis: dossier sections, gaps, findings, synthesis,
verdict, market, price improvement, what-changed.

- **Exists:** yes — it is one element of `build_slate`'s output.
- **Missing:** addressing. There is no game id today outside the HTML anchor
  scheme (§2.8), and no store keyed by one; the CLI regenerates the whole
  slate to see one game.
- **Compute shape:** PRECOMPUTED read from the slate the scheduler wrote.

### 3.3 `analyze_matchup(away, home, date) → GameAnalysis`

Arbitrary pairing, real or hypothetical, at a stated information cutoff.

- **Exists:** yes, `cmd_analyze` (`src/cli.py:735`) — and it is *correct* in
  the places that matter: it reads lineups from the point-in-time store rather
  than fetching live, treats the date as the cutoff, and names every
  unreconstructable source as a gap rather than backfilling it from today.
- **Missing:** (a) the whole function is CLI-shaped — it prints, returns exit
  codes, and writes a file; the analysis body needs lifting into
  `src/analysis/` or `src/pipeline/`; (b) the `hypothetical` flag is not a
  field (§2.9); (c) the doubleheader case prints "not supported yet" to
  stdout, which an API cannot do; (d) `prices_mod.by_matchup()` is called with
  no arguments, reading the entire multibook store on every invocation.
- **Compute shape:** **ON DEMAND, and it is the expensive one.** See §5.4.
  It reads the full results store, the pitcher logs, the lineup store, the
  handedness cache and the multibook store. This is the endpoint that needs a
  worker, a cache and a rate limit.

### 3.4 `bet_check(query) → BetCheck`

Given `"Yankees ML -125"`: market context, best available price and book,
supporting evidence, contradicting evidence, sample quality, warnings.

- **Exists: NO. This is the largest genuinely-missing product surface.**
  Nothing in the repo parses a bet string, and nothing assembles a
  for/against view of one side.
- **What exists to build it from, and it is most of the work:**
  - team resolution — `parks.canonical_team`, `slate.team_abbrev_from_name`;
  - the market and de-vig — `dossier._market_section`;
  - best price and consensus — `prices.snapshot`;
  - supporting/contradicting evidence — `Finding.side` already says which
    side a finding points at, so partitioning findings by `side == query.side`
    versus `side == opposite` is a filter, not new analysis;
  - sample quality — `synthesis.sample_size` plus `FLOORS`;
  - warnings — the `gaps` dict, verbatim.
- **Missing:** the query parser (team + market + line + price, with an
  explicit "I could not parse this" result rather than a guess); the
  for/against partition; a `sample_quality` rollup.
- **Non-negotiable:** Bet Check answers *"here is what is and is not known
  about this bet"*. It **must never return a verdict on whether to place it.**
  That is Engine 2 territory and Engine 2 is `None` (§8). The natural response
  field is `contradicting` — not `recommendation`.
- **Compute shape:** ON DEMAND, but cheap if it reads the precomputed game
  rather than re-analysing.

### 3.5 `get_board(date) → Board`

The market/odds board: one capture instant, one row per book, per game.

- **Exists:** yes, `prices.boards_by_matchup` — and its docstring is emphatic
  about why it is the *only* place a board may come from (two stores, two
  capture instants, one card reporting "11 books" and "10 books" two inches
  apart).
- **Missing:** nothing structural. It needs a date filter (today it reads and
  groups the whole store) and pagination.
- **Compute shape:** PRECOMPUTED, refreshed by the capture schedule.

### 3.6 `get_price_improvement(date | game_id) → PriceComparison`

- **Exists:** yes, `prices.by_matchup` / `prices.snapshot`.
- **Missing:** the `any_positive` flag and the explanatory note (§2.2), which
  must move out of both renderers before this is exposed.
- **Hard rule:** the field names are `improvement_points` and
  `improvement_return_pct`. **Never `ev`, never `edge`, never `value`
  unqualified**, in any field name, docstring, response, or client.
- **Compute shape:** PRECOMPUTED.

### 3.7 `get_changes(date | game_id, since=None) → [ChangeEvent]`

Lineup, scratch, probable and transaction changes, scored for pre-event
relevance, filtered to the information time.

- **Exists:** yes, `briefing.what_changed_by_pk` — including the three rules
  in its docstring that must survive into the API: an event reaches exactly
  the game it belongs to; an event seen after the information time does not
  appear; a game with nothing to say gets no entry.
- **Missing:** a `since` cursor (today the filter is a cutoff, not a
  watermark), which is what a notifications feature needs.
- **Compute shape:** PRECOMPUTED by the hourly capture job; this is the
  endpoint a push-notification worker polls.

### 3.8 `get_props(date | game_id) → Props`

- **Exists: NO, and it must not be faked.** `src/pipeline/prop_listing.py` is
  a bounded, budget-capped **feasibility audit** with a kill switch
  (`PROP_LISTING_AUDIT`), a 400-credit hard cap and stated abort criteria. It
  is a probe, not a data source.
- **Correct API behaviour today:** the endpoint exists and returns
  `MARKET_UNAVAILABLE` with the reason. Props are the clearest case for the
  `available: false` + `reason` pattern being a *response*, not a 404.

### 3.9 `get_evidence_labels() → [EvidenceLabel]`

The ladder, its ordering, each label's short name and meaning.

- **Exists:** twice and inconsistently (§2.5). Must be unified before it is
  served.
- **Compute shape:** STATIC. Cacheable forever, versioned.

### 3.10 `get_research_status() → ResearchStatus`

What has been tested and what it showed: hypothesis count, family count, the
standing disclaimer, Engine 2 state.

- **Exists:** the numbers do (`src/analysis/__init__.py`); the disclaimer text
  does (trapped in `dashboard._STANDING`, §2.11).
- **Missing:** the assembly, and a decision about how much detail is
  customer-facing. **Counts and the disclaimer are customer-facing; the
  falsification battery, the funnel, the matrix and Evolution Lab internals
  are not** (§6).
- **Compute shape:** STATIC per deploy.

### 3.11 `get_history(...) → HistoricalAnalysis`

User-facing historical analysis: past slates, past cards, what was said before
the games.

- **Exists:** partly. `ledger.py` holds what was said before each game and
  `ledger.settle` records outcomes; `archive.py` builds an index — but it does
  so **by parsing the generated HTML back**, which is a dependency the API
  must not inherit.
- **Missing:** a store-backed archive query. The ledger is the right source:
  it is append-only, written before the games, and already carries the
  information time.
- **Compute shape:** PRECOMPUTED reads over the ledger.

### Interfaces that do not exist at all

**Bet Check (3.4)** and **props (3.8)** — props correctly so. Everything else
in §3 exists as logic and is missing only an address, a serialiser, and (for
3.1/3.3/3.6) the extractions in §2.

---

## 4. Data contracts

JSON. Field names are the API's; where they match existing Python keys that is
deliberate and should be preserved.

### 4.0 The two rules, stated structurally

> **Rule S (sample).** Every quantitative claim carries its sample size.
> **Rule E (evidence).** Every claim carries its evidence label.

These are enforced by **shape, not by convention**. The mechanism:

- No numeric claim is ever a bare scalar. It is a `Claim` object (§4.6), and
  a `Claim` cannot be constructed without `sample` and `evidence`.
- `sample` is an object, never a string, with `n: int | null` **and**
  `text: string` **and** `countable: bool`. `countable=false` means the
  sample string names an elapsed period ("7-day window", "since SF, 3 day(s)
  ago"), not an amount of play. This is exactly what
  `synthesis.sample_size` computes today and what `dashboard._finding_row`
  checks per finding — moving it into the contract makes it impossible for a
  client to forget.
- `evidence` is an object with `status`, `label`, `meaning` — never a bare
  string, because a client that receives `"unproven"` and has no label table
  will invent one.
- A response containing a `Claim` with `sample.n == null` and
  `sample.countable == false` is **valid and normal**. What is invalid is a
  number outside a `Claim`.

An API test should assert the negative: no numeric field appears anywhere in
a response body outside a `Claim`, a `Price`, or an identity field.

### 4.1 A note on the evidence vocabulary

The task brief proposes `OBSERVATION / HISTORICAL_SUPPORT / EXPLORATORY /
CANDIDATE / FORWARD_TESTING / PROVEN / NO_PLAY / MARKET_UNAVAILABLE`. **That
list merges three distinct vocabularies that the code keeps separate**, and
merging them would be a regression:

| vocabulary | source | values |
|---|---|---|
| **evidence ladder** (how much do we know?) | `src/detect/base.py:45-60` | `blocked`, `tested_null`, `unproven`, `historical_candidate`, `tuning_evidence`, `provisional`, `forward_testing`, `proven` — ordered, and the order is relied upon by `rank()` |
| **observation status** (not a hypothesis at all) | `src/analysis/synthesis.py:161` | `observed` — a quoted price is certain; what it is worth is not |
| **verdict** (what did the scan conclude?) | `src/pipeline/mismatch.py:131-139` | `no_play`, `candidate`, `flagged`, `market_unavailable` |
| **relevance tier** (how much could this change matter?) | `src/analysis/relevance.py:74-78` | `HIGH`, `MEDIUM`, `LOW`, `UNKNOWN` |

`no_play` and `market_unavailable` are **verdicts about a game**, not evidence
strengths of a claim. Putting them on the evidence ladder would let a client
sort `proven` above `no_play` as though they were comparable. **Keep four
fields.** `tested_null` in particular must survive: its comment records that
it is *strictly weaker* than `unproven`, and collapsing it into "explored" is
"the single easiest way for this system to mislead the person using it".

### 4.2 `EvidenceLabel`

```json
{
  "status": "tested_null",
  "label": "Tested — no edge",
  "meaning": "Measured against outcomes and it did not predict them",
  "rank": 1,
  "family": "hypothesis"
}
```
`rank` is the index in `EVIDENCE_ORDER`. `family` is `"hypothesis"` or
`"observation"` (the latter for `observed`), so a client can tell that
`observed` is off-ladder rather than at the bottom of it.

### 4.3 `Sample`

```json
{ "n": 340, "text": "8 hitters, 340 plate appearances", "countable": true,
  "floor": 60, "below_floor": false }
```
`floor` is the sample floor the owning section publishes (`synthesis.FLOORS`),
`null` where none exists. `below_floor` is precomputed so no client re-derives
it.

### 4.4 `Gap`

```json
{ "section": "lineups", "reason": "lineup not posted yet, or not fetched" }
```
Verbatim from `Dossier.gaps`. Reasons are human-readable sentences and are
part of the product; they are not error codes and must not be replaced with
one.

### 4.5 `GameRef` — the identity

```json
{ "game_id": "game-CIN-NYM-2026-08-31",
  "game_pk": 776543, "game_number": null,
  "away": "CIN", "home": "NYM", "date": "2026-08-31",
  "start_time_utc": "2026-08-31T23:10:00+00:00", "venue": "Citi Field",
  "id_stable": true }
```
`game_id` is `dashboard._anchor_base` lifted per §2.8 — clubs plus official
date, doubleheaders disambiguated by game number then `game_pk`.
`id_stable: false` is the `anchor_unstable` case and must be surfaced, not
hidden: a link that silently moved is worse than no link.

### 4.6 `Claim` — the atom

```json
{
  "statement": "The starter CIN face has allowed 0.371 wOBA to left-handed…",
  "kind": "signal",
  "value": 0.371, "baseline": 0.315, "units": "wOBA",
  "magnitude": 0.056, "surprise": 1.9,
  "sample": { "...": "Sample" },
  "evidence": { "...": "EvidenceLabel" },
  "side": "away",
  "market_relevance": "bears on the first-five moneyline",
  "source": "matchup depth (handedness)",
  "detector": "platoon_mismatch",
  "fact_key": "platoon:away"
}
```

- `kind` ∈ `signal | debunk | context` (`detect.base`). A `signal` **must**
  carry a non-null `baseline` — the constructor invariant at `base.py:97`
  ("a claim that cannot say what normal looks like is a description, not a
  finding") must be re-asserted at the serialisation boundary.
- `side` ∈ `away | home | neither`.
- `surprise` may be `null` — the finding is unrankable, and
  `Finding.unscored` says so. Never substitute 0.
- `fact_key` is exposed so a client can tell that two statements are the same
  underlying fact.

### 4.7 `Synthesis`

```json
{
  "headline": "Interesting matchup, but no demonstrated betting edge.",
  "cleared": false,
  "note": "Everything the system found about this game is either too small…",
  "items": [ { "rank": 1, "...": "Claim + score/terms" } ],
  "suppressed": [ { "statement": "...", "reason": "scored 0.318, below the 0.42 bar…" } ]
}
```
`suppressed` is **required and never omitted** — its whole purpose is that
hiding the audit trail made the summary look like everything the system had.
Every entry carries a non-empty `reason` (§2.3).

### 4.8 `Game` (i.e. `GameAnalysis`)

```json
{
  "ref": { "...": "GameRef" },
  "information_time": "2026-08-31T23:59:59+00:00",
  "hypothetical": false,
  "verdict": "no_play",
  "verdict_side": null,
  "verdict_market": "first_five",
  "verdict_summary": "…",
  "synthesis": { "...": "Synthesis" },
  "findings": [ { "...": "Claim" } ],
  "sections": { "teams": {}, "starters": {}, "market": {}, "…": {} },
  "gaps": [ { "...": "Gap" } ],
  "price_improvement": { "...": "PriceComparison | null" },
  "changes": [ { "...": "ChangeEvent" } ]
}
```
`sections` and `gaps` are the `Dossier` split, preserved exactly.
`hypothetical: true` is the §2.9 flag and the client is required to render the
"this game does not exist" state; the API should also set every
market-dependent field to `null` with a gap explaining why.

### 4.9 `Slate`

```json
{ "date": "2026-08-31",
  "generated_at": "…", "information_time": "…",
  "counts": { "games": 15, "flagged": 0, "candidates": 2, "no_market": 3 },
  "lead": [ { "game_id": "…", "claim": { "...": "Claim" } } ],
  "notes": [ "No play on the whole slate. That is the normal case…" ],
  "standing": "Nothing on this page is a proven edge. …",
  "games": [ { "...": "Game" } ] }
```
`standing` comes from §2.11 and is mandatory on every slate response.
`notes` are `build_slate`'s own notes, verbatim.

### 4.10 `Board` and `BookQuote`

```json
{ "game_id": "…", "observed_utc": "2026-08-31T18:04:11Z",
  "source": "multi-book capture store", "books": 11,
  "quotes": [ { "book": "pinnacle", "away_price": -118, "home_price": 104 } ],
  "markets": { "h2h": { "away_price": -118, "home_price": 104,
                        "away_fair": 0.5321, "home_fair": 0.4679,
                        "hold_pct": 2.41 } },
  "implied_bullpen_shift": 0.019 }
```
`observed_utc` is **required**. A board without its capture instant is not a
board — two counts from two moments cannot describe one market.

### 4.11 `PriceComparison`

```json
{ "game_id": "…", "observed_utc": "…",
  "label": "price improvement / line-shopping value -- a better execution price, not expected value and not a prediction",
  "any_positive": false,
  "note": "No side here beats the de-vigged consensus, and that is the usual case…",
  "dispersion": { "books": 11, "home_probability_range": 0.0163 },
  "sides": {
    "away": { "best_book": "…", "best_price": -114,
              "consensus_probability": 0.5321,
              "improvement_points": -0.0056,
              "improvement_return_pct": -1.21,
              "skipped": null },
    "home": { "skipped": "no priceable quote on this side" } } }
```
- `label` is **required and non-empty**; a contract test should reject a
  response without it. `prices.py` already states that removing it "is a
  product decision nobody gets to make silently".
- `improvement_points` is a probability **fraction** on the wire; the client
  multiplies by 100 to show points. State the unit in the schema, because both
  renderers got this wrong once.
- Forbidden field names, enforced by a schema test: `ev`, `expected_value`,
  `edge`, `roi`, `value`.

### 4.12 `ChangeEvent`

```json
{ "game_id": "…", "class": "starter_scratch",
  "headline": "NYM: the listed starter changed from player 12345 to player 67890",
  "tier": "MEDIUM", "tier_sentence": "…",
  "basis": [ "…" ], "reasons": [ "…" ], "unknown_reason": null,
  "seen_utc": "…", "interval_start": "…",
  "timing": "observed between our polls at … and …",
  "inadmissible": false,
  "not_an_edge": "…",
  "summary": "…" }
```
`tier` is the relevance vocabulary, **not** the evidence ladder. `UNKNOWN` is
spelled out as unknown and never dressed as small. `inadmissible: true` is the
unbounded-first-sighting case (grade C) and must be rendered as such.

### 4.13 `BetCheck` (new)

```json
{
  "query": { "raw": "Yankees ML -125", "parsed": true,
             "team": "NYY", "side": "home", "market": "h2h",
             "price": -125, "line": null,
             "parse_error": null },
  "game": { "...": "GameRef | null" },
  "market_context": { "...": "Board" },
  "best_price": { "book": "…", "price": -118,
                  "better_than_quoted": true,
                  "note": "This is a better execution price on the same bet. It is not a prediction." },
  "supporting": [ { "...": "Claim" } ],
  "contradicting": [ { "...": "Claim" } ],
  "sample_quality": { "claims": 6, "with_countable_sample": 4,
                      "below_floor": 2,
                      "summary": "Four of six claims name an amount of play; two sit below their section's floor." },
  "warnings": [ { "...": "Gap" } ],
  "recommendation": null
}
```
`recommendation` is present, always `null`, and documented as permanently
`null` while Engine 2 is `None`. Making the field *exist and be null* is
better than omitting it: it tells every client author that the answer is "we
do not do that", rather than leaving a hole they fill themselves.
`parsed: false` with a `parse_error` is a 200, not a 400 — "I could not read
this bet" is a product answer.

---

## 5. Backend architecture

### 5.1 Recommendation

**FastAPI + Pydantic + Uvicorn, one process, SQLite in development and
Postgres in production, on a single small VM or one container on a managed
host. The evidence stores stay as files on a persistent volume. All analysis
stays precomputed by the existing scheduled scripts. Arbitrary-matchup
analysis is the only on-demand compute and it goes through a job queue with a
cache.**

One sentence: FastAPI because Pydantic makes the sample-and-label pairing a
*schema constraint the server enforces on itself* rather than a convention
every endpoint author has to remember, and that pairing is the entire product.

### 5.2 The cost of the first dependency

This is a real cost and it should be stated plainly rather than waved past.

**What is lost.** Today the project has a property almost nothing has: `git
clone && python3 -m src.cli brief` works on any machine with Python 3.11 and
nothing else. No lockfile, no supply chain, no version drift, no
`pip install` that fails in two years, no transitive package that gets
compromised. The test suite runs in 39 seconds with no environment setup. That
is genuinely valuable for a project whose product is *trustworthiness*, and it
is the reason the artifacts open from `file://` with no script tags.

**What it costs to give up.** FastAPI pulls Starlette, Pydantic,
`anyio`/`sniffio`/`typing-extensions`, plus Uvicorn's `click`/`h11` — roughly
eight to ten packages. That means a lockfile, a dependency-update duty, and a
supply-chain surface where there was none.

**The judgement: worth it, but only at the boundary.** The dependency belongs
in a new top-level `api/` package and **must not be imported by `src/`**. The
engine stays stdlib-only; the API is a thin adapter over it. Concretely:

- `src/` may not import `fastapi`, `pydantic`, or anything else third-party.
  Enforce with a test that walks `src/**/*.py` imports against an allowlist —
  the same style of structural test `test_ranker.py` already uses.
- `python3 -m src.cli brief` must keep working with no packages installed, and
  the test suite must keep passing with none installed. Add a CI lane that
  runs `python3 -m unittest discover -s tests` in a bare interpreter.

That gives the SaaS a modern API and keeps the engine's best property intact.

### 5.3 FastAPI versus the alternatives

**Django + DRF — the serious alternative, and it loses.** Django brings for
free the things §5's brief actually asks for: authentication, sessions,
password reset, an admin site, migrations, and a mature subscription
ecosystem. On a checklist it wins. It loses for three reasons specific to
*this* project:

1. **It wants to own the data model.** Django's value is the ORM and the
   apps built on it. This project's data is append-only JSONL and CSV on
   disk, with point-in-time discipline enforced by accessors, and it must
   stay that way (§5.5). A Django project whose core domain lives outside the
   ORM is a Django project using about a fifth of Django, while paying for
   all of it in structure and conventions.
2. **Serialisation is by hand.** DRF serializers are hand-written classes that
   can drift from the domain object. Given that the product rule is "no number
   without its sample and its label", a serialiser that silently omits a field
   is exactly the failure this system exists to prevent. Pydantic models make
   the omission a startup error.
3. **Weight.** Django is ~40 packages of transitive surface against FastAPI's
   ~10, on a project that today has zero.

**Flask — rejected, closer than it looks.** Flask is the smallest respectable
option and would work. It loses because the response validation, the OpenAPI
schema, and the typed models are then all hand-rolled, and hand-rolled is
where the sample-and-label rule gets forgotten. Flask + Pydantic + a schema
generator is FastAPI with more of the assembly left to you.

**Stdlib `http.server` — rejected, and it should be considered honestly
because it preserves the zero-dependency property.** It is genuinely viable
for read-only precomputed JSON. It fails on everything else: no auth, no
sessions, no request validation, no concurrency story worth having, no
OpenAPI, no middleware, and every one of those becomes bespoke code this
project would then own and test forever. Zero dependencies is not worth
writing a worse web framework.

**Not evaluated seriously, and why:** Node/TypeScript backends (the engine is
Python; a second language at the seam doubles the contract surface for no
gain), and serverless functions (the analysis is stateful over large on-disk
stores; cold-starting them per request is the wrong shape — see §5.6).

### 5.4 Precomputed reads versus on-demand compute

**The analysis is computed on a schedule.** This is the most consequential
architectural fact and it makes the API mostly a *read* API over artifacts a
scheduler produced. Classification:

| endpoint | shape | why |
|---|---|---|
| `GET /slates/{date}` | **precomputed** | Written by the nightly `brief` job. |
| `GET /games/{game_id}` | **precomputed** | An element of the stored slate. |
| `GET /boards/{date}` | **precomputed** | Refreshed by the hourly capture. |
| `GET /price-improvement/{date}` | **precomputed** | Derived from the same boards. |
| `GET /changes` | **precomputed** | Written by the hourly `watch` job. |
| `GET /evidence-labels`, `GET /research-status` | **static** | Per deploy. |
| `GET /history/...` | **precomputed** | Ledger reads. |
| `POST /bet-check` | **on demand, cheap** | Parses a query and reads a precomputed game. Must not re-analyse. |
| `POST /matchups` (arbitrary matchup) | **on demand, EXPENSIVE** | See below. |

**Arbitrary-matchup analysis is the one expensive endpoint.** `cmd_analyze`
reads the full historical results store, the pitcher logs, the lineup store,
the handedness cache and — today with no filter at all —
`prices_mod.by_matchup()` over the entire multibook store. That is seconds of
work and hundreds of megabytes of process memory, per call, for an input space
of (30 × 29 × every date) that cannot be fully precomputed.

Its design:

1. **Never in the request handler.** `POST /matchups` enqueues and returns
   `202` with a job id; `GET /matchups/{job_id}` polls. One worker process,
   one job at a time, is enough for a long time.
2. **Cache on `(away, home, date, engine_version)`.** A matchup at a past date
   is deterministic given the stores, so the cache hit rate for anything
   interesting will be high, and the result is immutable once the date is
   past.
3. **Load the heavy stores once per worker**, not once per job. The stores are
   read-only within a run; the worker holds them and reloads on a signal from
   the ingest job.
4. **Rate limit per user, tightly**, and make the limit part of the
   subscription tier. This is the endpoint that determines the cost of a
   customer.

### 5.5 Where state lives

**Relational (Postgres; SQLite until it hurts):**
users, credentials, sessions, subscriptions and billing state, saved bets,
watchlists, notification preferences and delivery log, per-user settings,
audit log of who looked at what, the matchup-job queue and its cache index.
All of this is small, mutable, relational, transactional, and needs to be
queried by user.

**Files (persistent volume, unchanged):**
`data/historical/`, `data/processed/`, `data/watch/`, `data/raw/`, and
`evidence/` — the results store, pitch stores, multibook captures, lineup
store, forward ledger, mismatch flags, predictions.

**Why the evidence stores should not move into the database.** Four reasons,
in order of weight:

1. **Append-only-ness is the evidence.** `evidence/forward_ledger.jsonl`
   is a record of what was claimed *before* games were played. A JSONL file
   under version control has the property that a rewrite is visible in a diff.
   A database row has no such property — an `UPDATE` leaves no trace, and the
   entire value of a forward ledger is that it cannot be quietly improved
   after the fact. Moving it into Postgres would make the project's central
   honesty mechanism silently editable.
2. **They are already committed to git.** `scripts/daily_loop.sh` and
   `scripts/forward_capture.sh` `git add` and push `data/` on every run. That
   is the backup, the audit trail and the reproducibility mechanism at once,
   and it is free.
3. **The access pattern is bulk-scan, not point-query.** `read_results()`,
   `read_multibook()` and the pitch stores are read whole and walked. That is
   what files are good at. Nothing in the engine issues a query that an index
   would help.
4. **It would create the first third-party dependency inside `src/`.** A
   database client in the engine breaks §5.2's whole arrangement.

**The one thing that must be added:** a **manifest table** in the relational
store — `{store_name, path, last_written_utc, row_count, checksum}` — updated
by the scheduled jobs. It is how the API answers "is this data fresh?"
without stat-ing files in a request handler, and how a stale-data banner gets
onto a page. Files stay the source of truth; the database holds the metadata
*about* them.

### 5.6 Deployment shape

**One VM (or one managed container) with a persistent disk.** Not serverless,
not Kubernetes. Concretely:

```
  ┌────────────────────────────────────────────┐
  │ host                                        │
  │  ┌──────────┐  ┌──────────┐  ┌───────────┐ │
  │  │ uvicorn  │  │ worker   │  │ scheduler │ │
  │  │ api/     │  │ matchup  │  │ (systemd  │ │
  │  │ (N proc) │  │ jobs     │  │  timers)  │ │
  │  └────┬─────┘  └────┬─────┘  └─────┬─────┘ │
  │       │             │              │       │
  │  ┌────┴─────────────┴──────────────┴────┐  │
  │  │ /srv/app/data, /srv/app/evidence     │  │
  │  │ (persistent volume, git-backed)      │  │
  │  └──────────────────────────────────────┘  │
  │  ┌──────────────────────────────────────┐  │
  │  │ postgres (users, subs, saved bets)   │  │
  │  └──────────────────────────────────────┘  │
  └────────────────────────────────────────────┘
```

Serverless is ruled out by the shared on-disk stores: every function invocation
would need to mount and warm hundreds of megabytes, and the scheduled jobs
`git commit` their output, which a stateless function cannot do.

**The existing scripts become scheduled jobs with almost no change.** They are
already the right shape — deterministic, one entry point, output that consists
of a transcript plus `ESCALATE:` lines. That design was for a model session
reading one transcript; it is *also* exactly what a cron/systemd unit wants.

| today | becomes | cadence |
|---|---|---|
| `scripts/forward_capture.sh` | `aisports-capture.timer` | hourly |
| `scripts/daily_loop.sh` | `aisports-daily.timer` | daily, after the day's games settle |
| — | `aisports-brief.timer` | daily, pre-slate, writes the slate the API serves |

Four changes, all small and all in the shell, none in `src/`:

1. **`git push` needs a deploy key** rather than the developer's credentials,
   or the commit step becomes local-only with a separate backup. The
   `git add` / `git commit` behaviour should be kept — see §5.5 reason 2.
2. **`ESCALATE:` lines become alerts.** Today a model reads them; in
   production they should exit non-zero or post to a channel. This is the
   cheapest possible monitoring and it is already written.
3. **`cd "$(dirname "$0")/.."` already handles cron's working directory**, and
   `src/paths.py` anchors data paths to the repo root for the same reason. The
   hard part is already solved; do not undo it by setting
   `AISPORTS_DATA_DIR` carelessly.
4. **Add a job that writes the served slate artifact** and updates the
   manifest table (§5.5), so the API never regenerates a slate in a request.

**Deploy is `git pull` + restart.** No build step for the engine; a lockfile
install for `api/` only.

---

## 6. What stays internal, and how it is enforced

**Never customer-facing:**

- `src/evolab/` — the Evolution Lab in its entirety (genome, placebo,
  baseline, ceiling, cscv, spa, decide, registry, bitsets).
- `src/research/` — the falsification battery, funnel, matrix, event study,
  price paths, lead-lag, the M1–M5 families, the scoreboard, `elobench`.
- `src/model/` — discovery, dataset, logistic, selections, seal, family.
  (The *counts* these produce are customer-facing via
  `src/analysis/__init__.py`; the machinery is not.)
- `src/pipeline/health.py`, `dense.py`, `prop_listing.py`, `backfill.py`,
  `scanlog.py`, `grading.py`, `predict.py` — data-health, capture and
  validation tooling.
- `src/core/staking.py` — **especially** this one.
- `evidence/` raw stores and the per-row ledger view.
- Every CLI subcommand except `brief`, `analyze` and `archive`.

**Enforcement, in order of strength:**

1. **Import-graph test (strongest, do this).** A test that walks the import
   graph reachable from `api/` and fails if it reaches any module in the
   internal list. This is the same technique `tests/test_ranker.py` already
   uses to pin the Engine 2 gate, so it is idiomatic here. Enforcement by
   directory listing, checked by a test, beats enforcement by convention.
2. **Package placement.** `api/` imports `src.analysis`, `src.detect`,
   `src.pipeline.briefing`, `src.pipeline.mismatch`, `src.core.odds`,
   `src.data.parks` — an explicit allowlist, written down in one module
   (`api/engine.py`) that is the *only* file in `api/` permitted to import
   from `src`. Every other API module imports from `api/engine.py`.
   One file to review, one file to test.
3. **No generic passthrough.** There must be no endpoint that takes a module
   name, a store path, a command name or a query and executes it. The set of
   endpoints is a finite written list.
4. **Separate admin deployment.** Internal tooling stays CLI-only and is run
   by a human on the host over SSH. If an admin *web* surface is ever built,
   it is a separate application on a separate port with separate auth, sharing
   only the read-only files. It is not a role flag on the customer app —
   a role flag is one bad `if` away from a customer seeing the lab.
5. **Response schema is a closed set.** Because every response is a Pydantic
   model, an internal object cannot leak by being accidentally serialised;
   it would have to be deliberately mapped into a customer model first.

---

## 7. The four layers

### Layer 1 — CORE ANALYSIS ENGINE (`src/`)

- **Owns:** dossiers, detectors, findings, synthesis, verdicts, price
  improvement, relevance scoring, the evidence vocabulary, point-in-time
  discipline, the stores.
- **May import:** the Python standard library. Its own modules.
- **Must never import:** anything third-party; `api/`; any web framework; any
  database client; the renderers.
- **Today's violations:** none of the import kind — the engine is clean. The
  violation is the *inverse*: logic that belongs here lives in Layer 3
  (all of §2).

### Layer 2 — APPLICATION API (`api/`, new)

- **Owns:** HTTP, auth, subscriptions, per-user state, saved bets,
  watchlists, notifications, rate limits, job queue, response schemas,
  caching, freshness reporting.
- **May import:** `src.analysis`, `src.detect`, `src.pipeline.briefing`,
  `src.pipeline.mismatch`, `src.core.odds`, `src.data.parks` — and only
  through `api/engine.py`. Plus its own third-party stack.
- **Must never import:** `src.report.*` (it is HTML), `src.evolab.*`,
  `src.research.*`, `src.model.*`, `src.providers.*` (no credit spend in a
  request), `src.pipeline.{health,dense,prop_listing,backfill,scanlog,
  grading,predict}`.
- **Today's violations:** the layer does not exist. Its prerequisites are §2.

### Layer 3 — CUSTOMER WEB APP

- **Owns:** screens, navigation, formatting, interaction, the copy that
  `PRODUCT_DESIGN_HANDOFF.md` specifies.
- **May import/consume:** the Layer 2 HTTP API only.
- **Must never import:** `src/` at all. No shared Python. No direct file
  reads.
- **Today's violations, and they are the point of this document:**
  `src/report/dashboard.py` *is* today's customer app, it imports `src/`
  directly, and it does business logic (§2). `src/report/archive.py` reads
  Layer 3's own output back as data, which inverts the dependency entirely.
  The static generator can and should keep existing — it is the
  known-good artifact and `artifacts/demo_latest.html` is protected — but
  after §2's extractions it becomes *one client of Layer 1*, not the place
  where product decisions live.

### Layer 4 — INTERNAL RESEARCH / ADMIN

- **Owns:** Evolution Lab, research families, the falsification battery,
  data health, validation, the forward ledger's row-level view, the
  reproducibility audits, all scheduled data-plane scripts.
- **May import:** everything in Layer 1, and its own tools.
- **Must never import:** `api/` or Layer 3 — the lab must not be able to
  reach a customer surface, in either direction.
- **Today's violations:** none structurally; the separation is already good.
  The risk is prospective: the moment an admin *web* view is wanted, the
  temptation is a role flag in Layer 2. §6.4 says do not.

---

## 8. The hard product rules

### 8.1 Analyzer and Ranker never share an evidence standard

**The Analyzer may show a labelled observation; the Ranker may not rank on
one.** This asymmetry is the reason they are two products, and it must be
structural in the API, not a note in a docstring.

`src/report/ranker.py` is gated by `ENGINE2 = None`, with
`_engine2_unlocked()` deliberately returning `False` and
`tests/test_ranker.py` pinning that the rendered page contains no
recommendation, no pick, no unit size and no "edge" language.

**What no API design may do:**

- No endpoint returns a field named `recommendation`, `pick`, `bet`,
  `stake`, `units`, `confidence` or `edge` with a non-null value. §4.13's
  `recommendation: null` is the pattern: present, null, documented as
  permanently null.
- No endpoint accepts a parameter that changes the evidence bar — no
  `?min_evidence=`, no `?include_unproven=false`, no "aggressive mode". A
  filter that hides weak evidence is a ranker wearing a query string.
- No endpoint sorts or filters *by* evidence strength in a way that produces
  a top-N "best bets" list. Sorting a board by price improvement is fine and
  already exists; sorting *claims* into a recommendation is not.
- `src/core/staking.py` is not importable from `api/` (§6). A staking
  calculator behind auth is a bet-sizing product.
- The `ENGINE2` gate must not become configuration. No environment variable,
  no database row, no feature flag, no admin toggle. It changes by a reviewed
  code diff that fails a test until the evidence exists, and that is the
  whole design.
- **Extend the structural test to the API.** `tests/test_ranker.py`'s
  approach — assert the absence of forbidden language in the rendered
  output — should be applied to the API's OpenAPI schema and to sample
  responses. The gate is only as strong as the surfaces it covers, and a new
  surface is a new place for it to leak.

### 8.2 Price improvement is never called EV or edge

Enforced in three places:

1. `prices.LABEL` rides on every returned dict and is a **required,
   non-empty** field of `PriceComparison` (§4.11).
2. A schema test rejects the field names `ev`, `expected_value`, `edge`,
   `roi`, and bare `value` anywhere in the API's models.
3. A grep-style test over `api/**` and `src/analysis/prices.py` for the words
   "expected value" and "edge" outside a negation. `prices.py`'s docstring
   already records that "real money regardless of who wins" was retired
   deliberately; the same vigilance applies to field names and to client
   code.

---

## 9. Sequenced plan for the build agent

Nothing here is built. This is the order that keeps the suite green at every
step.

**Phase 0 — unification (no new surfaces).**
1. Single evidence-label module; delete the duplicate (§2.5).
2. Single `HYPOTHETICAL_GAP`; delete the duplicate (§1.2.3).
3. Lift the game-id scheme out of the renderer (§2.8).
4. Move `_STANDING` to `src/analysis/__init__.py` (§2.11).

**Phase 1 — extraction (the renderer stops computing).**
5. `hypothetical` becomes a field (§2.9).
6. Synthesis is always populated by the domain (§2.1).
7. `any_positive` + note move into `prices.py`, unifying dashboard and ranker
   (§2.2).
8. `slate_lead()` moves into `synthesis.py` (§2.4, §2.10).
9. Section warnings move to their owners (§2.6, §2.7).
10. Suppressed entries are guaranteed a reason (§2.3).

*After Phase 1, `dashboard.py` should be materially shorter and should contain
no `if` that decides what is true — only `if`s that decide what is shown. The
demo artifact must still render, and `artifacts/demo_latest.html` must not be
touched.*

**Phase 2 — the API.**
11. `api/engine.py` — the single allowlisted import surface (§6.2).
12. Pydantic models for §4, with the `Claim` invariant tests (§4.0).
13. Read endpoints over precomputed artifacts (§5.4).
14. The import-graph test and the Engine 2 schema test (§6.1, §8.1).

**Phase 3 — the application.**
15. Auth, subscriptions, per-user state, saved bets, watchlists.
16. The matchup job queue and cache (§5.4).
17. Bet Check (§3.4) — last, because it depends on everything above.

**Phase 4 — operations.**
18. Scheduled jobs, manifest table, freshness banner, `ESCALATE:` alerting.

---

## 10. Risks

**The biggest risk in the whole transition: the API ships before §2 is done,
and the honest sentences do not come with it.** Every warning that makes this
product trustworthy — "no side here beats the de-vigged consensus, and that is
the usual case"; "no sample size stated"; "this game does not exist"; "below
this section's sample floor"; the standing disclaimer — currently lives inside
`dashboard.py` as HTML. A JSON API assembled by serialising
`build_slate`'s output would carry the numbers and drop the warnings, and it
would look perfectly fine in review. The result would be a *more confident,
less honest* product than the static page it replaces, which is precisely the
failure mode this project has spent its whole life avoiding.

Secondary risks:

- **Two surfaces disagreeing.** The static generator and the API will
  coexist. If both compute anything independently they will diverge — this
  has already happened twice (13 vs 27 hypotheses; 11 vs 10 books) and both
  fixes were "one function, read once". Phase 1 is what prevents the third
  occurrence.
- **The dependency creeping into `src/`.** The moment a Pydantic import
  appears in `src/analysis/`, the engine's zero-dependency property is gone
  and will not come back. The import allowlist test is cheap insurance.
- **Scheduled-job silence.** `forward_capture.sh` already carries a comment
  about a store whose failure mode was silence — "the pass no-ops, the run
  reads as healthy". An API serving a stale precomputed slate has exactly
  that failure mode, and the manifest table plus a freshness field on every
  response is the mitigation.
- **Engine 2 pressure.** A subscription product creates commercial pressure to
  produce picks. The gate holds only if it stays a code diff that fails a test
  (§8.1) rather than a config value someone can flip at 2am.
- **`archive.py`'s inverted dependency** quietly becoming load-bearing for the
  API. It must not be; the archive service reads the ledger.

---

## Appendix: refactor bar

The task permitted a small refactor if it was obviously safe, obviously useful
and fully tested. **None was made.** The two candidates were §2.5 (unify the
duplicated `EVIDENCE_LABELS`) and §1.2.3 (unify the duplicated
`HYPOTHETICAL_GAP`). Both are correct and both are listed as Phase 0 items,
but both touch product-visible strings on the live briefing path with a
sequencing decision attached — where the shared module lives, and whether
`OBSERVED` joins the detector ladder or stays beside it — and that decision
belongs to the build agent working from `PRODUCT_DESIGN_HANDOFF.md`, not to an
audit. Test suite verified unchanged at **1954 tests, OK**.
