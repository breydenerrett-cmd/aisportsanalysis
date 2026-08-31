# SaaS implementation plan (2026-08-31)

**Status: PLAN ONLY. Executable by a build agent today.** Reconciles
`SAAS_APPLICATION_ARCHITECTURE.md` (stack/boundary), `PRODUCT_DESIGN_HANDOFF.md`
(pages/flows/vocabulary), and `CAPABILITY_RECONCILIATION.md` (what is real
*today*, 2026-08-31, superseding the handoff wherever they disagree). Domain
contracts (the `Claim`/`Sample`/`EvidenceLabel`/`GameAnalysis`/etc. shapes) are
not restated here — **`src/analysis/contracts.py`, built in parallel by the
contracts worker, is the authority.** Every slice below imports from it rather
than inventing field shapes.

Letters in brackets map to `docs/COMMAND_CENTER.md`'s `PAID_BETA_CRITICAL_PATH`.
Estimates assume parallel Sonnet implementation (multiple workers, non-
overlapping files) with tests required at every step, not serial hours.

---

## 0. Why vertical slices, and the corrected estimate

Horizontal completion (finish auth, then billing, then deploy, then one page)
delays the first thing a human can click by weeks. Building TODAY end-to-end
first — real data through a real API to a real (even ugly) UI, including its
error states and its tests — proves the JSON boundary, the auth stub, and the
deploy path all at once, on the smallest surface. Every later slice (GAME, BET
CHECK, ODDS, WHAT CHANGED) then repeats a *known-good* pattern instead of
discovering it. Auth, billing and deploy are cross-cutting and gated by
Brey-owned external accounts (Stripe, hosting, auth provider) — they must start
day one in parallel or they become the slip risk COMMAND_CENTER already flags
first (design-cycle latency) and second (accounts). This document treats them
as their own lane, threaded through every slice below rather than saved for
the end.

**Bottom-up estimate versus the scoreboard.** Summing the slice estimates in
§2–§6 under realistic parallelism (§7) puts engine-side readiness (contracts
through TODAY/GAME/BET CHECK/ODDS/WHAT CHANGED, non-visual API, auth/billing
scaffolding) at **roughly 4–6 wall-clock days from now**, which lands inside
the scoreboard's existing "invited alpha ~7-12d" band. It does **not**,
however, reach *paid beta* in that time, because paid beta additionally
requires: the `/design` gate (three directions → Brey approval, a human
decision with unavoidable latency — COMMAND_CENTER's own #1 slip risk), the
design system built from the chosen direction, and G–M customer-screen
implementation against that system, plus Q one-click cancel, V security
review, W accessibility, X billing QA, and Z release check — none of which can
start in earnest before Brey approves a direction. **The scoreboard's
2026-09-12..14 estimate is not contradicted by this plan; it is explained by
it: the backend/engine path is not the bottleneck, the design-approval gate
is.** If Brey approves a direction within 1–2 days of the `/design` artboards
landing, 2026-09-12..14 is achievable. If approval takes longer, the whole
estimate slides day-for-day — the arithmetic has no slack anywhere else,
because G–M cannot be parallelized against an unapproved system and Q/V/W/X/Z
are strictly sequential after G–M substantially lands. **Correction to flag
explicitly:** the scoreboard's risk list is right to rank design-cycle latency
first; this plan finds no lever on the engine side that moves the date faster
than the design gate does — throwing more Sonnet workers at TODAY/GAME/BET
CHECK does not shorten the critical path once G–M is the pacing item.

---

## 1. Stack, layout, and the app/api boundary (recap, not re-derivation)

Full justification lives in `SAAS_APPLICATION_ARCHITECTURE.md` §5; this is the
skeleton every slice below builds inside.

```
src/                    # UNCHANGED. Stdlib only. Never imports fastapi/pydantic.
  analysis/contracts.py #   <- the contract authority (parallel worker)
  analysis/ pipeline/ detect/ core/ data/   # domain + plumbing, read-only from api/
  report/               # existing static generator; becomes one client of Layer 1
  evolab/ research/ model/ providers/       # INTERNAL, never reachable from api/

api/                    # NEW. FastAPI + Pydantic + Uvicorn.
  engine.py             #   the ONLY file in api/ allowed to import from src/
  models/               #   Pydantic wrappers around contracts.py dataclasses
  routes/               #   one module per resource (slates, games, bet_check, ...)
  auth/                 #   session/JWT, user table access
  billing/              #   Stripe webhook + subscription state
  jobs/                 #   matchup on-demand worker + cache
  admin/                #   SEPARATE app instance, separate port/auth — never imported by routes/

web/                    # NEW. Customer web app. Consumes api/ HTTP only. No shared Python.
  (component system, §8)

ops/                    # scheduled jobs (systemd timers wrapping existing scripts), manifest table migration
```

**Rule, enforced by test, not convention:** an import-graph test walks
`api/**` and fails if it reaches `src.report`, `src.evolab`, `src.research`,
`src.model`, `src.providers`, or the internal `src.pipeline.*` modules listed
in the architecture doc §6. A second test walks `src/**` and fails on any
third-party import. Both tests are Phase-0 work, cheap, and load-bearing —
this is the mechanism, not the aspiration.

---

## 2. SLICE 1 — TODAY, end to end **[B, contracts foundation; app/api foundation]**

The home screen. Smallest complete vertical: one real API endpoint, one real
UI page, mobile, every honesty state, tests. Everything after this slice
reuses its pattern.

### 2.1 Data → domain
`briefing.build_slate` already produces the slate (`SAAS_APPLICATION_ARCHITECTURE.md`
§3.1). Two extraction prerequisites from that doc's §2 must land first because
TODAY's honesty states depend on them: synthesis always populated (§2.1),
`_STANDING` disclaimer lifted to `src/analysis/__init__.py` (§2.11), and the
slate-level lead (§2.4) so ranking-by-actionability (handoff Rule 2) has a
domain source instead of being re-derived in `api/`. These are the contracts
worker's Phase-0 items; this slice consumes their output, does not redo them.

### 2.2 API
`GET /slates/{date}` — precomputed read (`SAAS_APPLICATION_ARCHITECTURE.md`
§5.4). Response is the `Slate` contract from `contracts.py` (§4.9 shape:
`counts`, `lead`, `standing`, `notes`, `games`), serialised through
`api/models/slate.py`, built only via `api/engine.py`. Add the manifest-table
read (§5.5) so the response carries a freshness field — this is the mechanism
behind the "Stale" state below, not a separate feature.

### 2.3 UI (structure only — visual specifics wait for `/design`)
Component hierarchy per handoff §"Today ... Component hierarchy": date +
slate-summary sentence, WHAT CHANGED band (empty-hideable), WHAT MATTERS
TONIGHT (3–5 ranked findings), game rail, best-prices strip. Build these as
unstyled/placeholder-styled structural components now so `/design`'s three
artboard directions drop into an already-correct DOM/component tree rather
than dictating it. **Rule 1 (never lead with a null count) and Rule 2 (rank by
actionability tier, never z-score)** are contract-level, not styling — the
`lead` field from §2.1 already encodes the tier ordering, so the component
only renders it, never re-sorts it.

### 2.4 Mobile
Single column, WHAT CHANGED + WHAT MATTERS above the game list, game rail as a
vertical list (never a horizontal scroller — handoff is explicit this hides
content on phones). Since the component tree is shared with desktop (§2.3),
mobile is a CSS/layout concern at this stage, not a second implementation —
confirm this now so `/design` doesn't have to discover it.

### 2.5 Error / partial-data / honest states
Directly off `CAPABILITY_RECONCILIATION.md` and the handoff's "States" table —
this is where the beta's credibility actually lives:

| State | Behavior | Source of truth |
|---|---|---|
| Loading | Skeleton matching final layout; game rail renders first (needs only schedule) | UI-only |
| Empty (no games) | "No games today. Next slate: [day]." + link to yesterday | slate response with `games: []` |
| Empty (nothing notable / no-play night) | Never blank — "Nothing clears the bar — here's what we looked at and why" | `notes` field, verbatim from `build_slate` |
| Partial data | Render what exists; label the gap | per-game `gaps` array (Dossier split, §4.4/4.8 of the architecture doc) |
| One source failed | **The app never blanks.** Game rail survives if schedule loaded even if odds/lineups failed | each section independently gapped; no single try/except around the whole response |
| Stale odds | Age shown; a price older than ~2 min is never presented as current | manifest-table freshness timestamp (§5.5), computed server-side, not client-guessed |
| Lineups not posted | "Lineups not posted yet — typically ~3 hours before first pitch" | `gaps["lineups"]` reason string, verbatim — never replaced with a generic error code |

The unifying rule, stated once so every later slice inherits it without
re-deriving it: **a `Gap` is a product sentence, not an error channel; a
failed or absent source degrades its own section and nothing else.**

### 2.6 Tests
- Contract tests: `Slate` response has `standing`, non-empty `notes` on empty
  slates, `lead` ordered by tier not z-score.
- Import-graph test (api/ → src/ allowlist) and stdlib-only test (src/**)
  — write once here, every later slice is covered for free.
- Schema test: no bare numeric field outside `Claim`/`Price`/identity (per
  architecture §4.0) — write once, applies to every endpoint added later.
- Partial-data test: kill one plumbing source (mock), assert the rest of the
  slate still renders and the killed section carries a `gap`.
- UI: renders correctly with 0 games, N games all `no_play`, and a mixed
  slate; mobile viewport at 375px has no horizontal scroll.

### 2.7 Estimate
Contracts prerequisites (2.1) run in parallel with a separate worker (already
in flight, marked B in COMMAND_CENTER). Given contracts land: API + tests
~0.5 day; UI structure + states + mobile ~1 day; combined with review/fix
cycles, **~1.5–2 wall-clock days** for a complete, honest, mobile TODAY page
behind no auth (auth lane runs separately, §9).

---

## 3. SLICE 2 — GAME (Quick + Advanced) **[maps to G on the critical path, pulled forward]**

### 3.1 API
`GET /games/{game_id}` — precomputed, one element of the stored slate
(architecture §3.2). Game id is the lifted anchor scheme (§2.8 of that doc):
same string for the API resource and any UI fragment link. Response is the
`GameAnalysis`/`Game` contract (§4.8) — `sections`/`gaps` preserved verbatim,
`hypothetical: true` handled per §2.9 (all market-dependent fields null with a
gap explaining why, never fabricated).

### 3.2 Quick/Advanced contract — one page, two depths, not two pages
This is the single most load-bearing interaction rule in the handoff and it
is a **contract-level constraint, not a UI toggle**:
- Quick View is the default for every new session; it is a strict function of
  `GameAnalysis` — max 5 factors, each already-composed as a plain-English
  sentence with a `✓`/`⚠` polarity, sourced from `synthesis.items` (ranked,
  truncated server-side per contracts.py, never truncated ad hoc in the
  client so two clients cannot disagree on which 5 survive).
- **Both sides always appear.** If `synthesis.suppressed` or the counter-side
  is empty, the API still returns an explicit "No significant
  counterarguments found" — this must be a field the client renders
  unconditionally, never a conditional block the client can accidentally
  collapse to nothing.
- Advanced is the same `GameAnalysis` object, unfiltered — no second
  endpoint, no second fetch. The client renders the blocks in
  `sections` (starters, lineups, bullpen, market, context, evidence+method)
  that Quick View elided. Transition is client-side (`?depth=advanced` in
  the URL, expand-beneath not swap-out) — no additional round trip.
- Numbers-with-samples is enforced by the `Claim`/`Sample` shape itself
  (architecture §4.0): a component that renders a rate is handed a `Claim`
  object and cannot construct its own bare percentage.

### 3.3 Per-page contract note
GAME's contract is exactly `GameAnalysis` from `contracts.py` — no bespoke
per-page shape. This is deliberate: Quick and Advanced are two renderings of
one object, and BET CHECK (§4) reads the *same* `GameAnalysis` for its market
context rather than re-fetching or re-deriving it.

### 3.4 Evidence translation
The handoff's vocabulary table (internal → customer-facing) is applied at the
`api/models` serialization boundary, not in the UI and not in `src/`:
`UNPROVEN`→"Observation", historical candidate→"Historical support", forward
ledger entry→"Forward testing", Engine 2 gated→"No demonstrated edge",
de-vig consensus→"Market's true read", hold→"Book's margin", book
dispersion→"How much books disagree". Concretely: `api/models/evidence.py`
holds one dict, `EvidenceLabel.label`/`.meaning` are the translated strings,
and no other module is allowed to hardcode a customer-facing evidence word —
enforced the same way as the price-improvement language ban (architecture
§8.2): a grep-style test over `api/**` and `web/**` for raw internal tokens
(`V1`–`V5`, `PBO`, `CSCV`, `genomes`, `Phase 2A`, `h2h_1st_5_innings`, raw
z-scores, microsecond UTC).

### 3.5 States
Hypothetical matchup → the "this game does not exist" banner is a boolean
field, not string-matching (architecture §2.9); every market field null with
a gap. Missing Advanced-only ingredients (xFIP, pitch mix, velocity, xwOBA,
lineup-slot decomposition — confirmed NOT ingested per
`CAPABILITY_RECONCILIATION.md`) render as an explicit "not currently tracked"
block, never omitted silently and never backfilled with a guess.

### 3.6 Tests
Quick View truncation test (exactly ≤5 factors, always includes counter-side
even when empty); Advanced renders all `sections` keys present in the
contract; hypothetical flag suppresses market fields with gaps, not nulls
without explanation; evidence-vocabulary grep test (no internal token
reaches `api/`/`web/` responses); sample-size contract test (`Claim` cannot
serialize without `sample`).

### 3.7 Estimate
Reuses Slice 1's API/test pattern. API + contract wiring ~0.5 day; Quick/
Advanced UI structure (still pre-`/design`, structural only) ~1 day;
evidence-translation module + its tests ~0.5 day. **~1.5–2 wall-clock days**,
parallelizable against Slice 1 once contracts.py is stable (i.e., largely
concurrent with Slice 1, not strictly after it).

---

## 4. SLICE 3 — BET CHECK **[A/B on the critical path; "last, because it depends on everything above" per the architecture doc]**

### 4.1 Status today
`src/analysis/betcheck.py` exists (428 lines per `CAPABILITY_RECONCILIATION.md`),
with a documented `parse()`/`check()` design and a fixed-skeleton verdict
object. h2h (moneyline) parsing works with explicit refusal for other markets
— **not silent coercion**, which matches the handoff's own required behavior
("Parsing failures must offer a picker, never a bare error" — apply the same
philosophy: a market Bet Check cannot parse is a named refusal, not a guess).
STRONGEST/WEAKEST REASON, HISTORICAL SUPPORT meter, EVIDENCE STATUS ladder,
and BOTTOM LINE prose are confirmed **not yet implemented end-to-end** —
treat this slice as: wrap what exists, build what's missing, do not assume
either.

### 4.2 API
`POST /bet-check` — on demand but cheap: reads the precomputed `GameAnalysis`
for the resolved game, never re-analyzes (architecture §5.4). Request is the
raw bet string; response is the `BetCheck` contract (§4.13): `query` (parsed
fields + `parse_error`, **200 not 400** on an unparseable bet — "I could not
read this bet" is a product answer), `game` ref, `market_context` (the same
`Board` used by ODDS, §5), `best_price`, `supporting`/`contradicting` (a
partition of `GameAnalysis.findings` by `side`, not new analysis per
architecture §3.4), `sample_quality` rollup, `warnings` (the `gaps` array,
verbatim), and **`recommendation: null` always, documented as permanently
null while `ENGINE2` is gated** — present-and-null, not omitted (§8.1 non-
negotiable).

### 4.3 The counterargument is structurally mandatory
This is called out because it is the one rule in this whole document that
must never regress under refactor pressure: `contradicting` cannot be an
empty array rendered as nothing. Both the contract and the UI must render
"No significant counterarguments found" as an explicit value when the
partition is empty — enforced by a contract test that fails if a `BetCheck`
response with zero `contradicting` items round-trips without that literal
sentinel string present somewhere in the served payload or a client-required
field that forces its display.

### 4.4 STRONGEST/WEAKEST REASON, HISTORICAL SUPPORT, EVIDENCE STATUS, BOTTOM LINE
These four fields are genuinely new logic, not extraction — flag honestly per
`CAPABILITY_RECONCILIATION.md` as ENGINEERING REQUIRED, not "mostly done":
- STRONGEST/WEAKEST — rank `supporting`/`contradicting` by evidence-ladder
  rank (from `contracts.py`), take the extremes, render their `statement`.
  WEAKEST REASON is also the Bet Debunker surface (handoff) — same field,
  reused, not two implementations.
- HISTORICAL SUPPORT meter — a Weak/Moderate/Strong bucketing over the same
  evidence-ladder ranks in `supporting`. No new number; a bucketing function
  over existing `EvidenceLabel.rank` values.
- EVIDENCE STATUS ladder — the five-stage customer-facing ladder (Observation
  → Exploratory → Historical support → Forward testing → Validated) is a
  direct application of the vocabulary table (§3.4) to the highest-ranked
  supporting claim's evidence label. No new backend concept.
- BOTTOM LINE — templated prose from the above four fields plus
  `price_improvement`, never model-generated free text and never implying
  guaranteed profit (handoff rule). Template, not LLM call, so it stays
  test-pinnable the way `_STANDING` and `NO_IMPROVEMENT_NOTE` already are.

### 4.5 The one absolute rule
No win probability, anywhere, ever, in this endpoint or its UI. The model is
UNCALIBRATED (`cli status`, verified) and Phase 2A found no linear information
beyond the close. `recommendation` stays permanently `null`. Enforced by the
same OpenAPI/sample-response structural test extended from the ranker's
existing test (`tests/test_ranker.py` pattern, per architecture §8.1) —
applied to `api/` once here, inherited by every future endpoint.

### 4.6 Tests
Parse success/failure round-trip (200 either way); counterargument-present
test (§4.3); `recommendation` is always `null` and the schema forbids
`recommendation`/`pick`/`bet`/`stake`/`units`/`confidence`/`edge` carrying a
non-null value anywhere in the response; STRONGEST/WEAKEST pick correct
extremes on a synthetic claim set; grep test extended to `betcheck` responses
for "expected value"/"edge" outside negation.

### 4.7 Estimate
Wrapping the existing skeleton + the four new template fields + the
mandatory-counterargument enforcement: **~2–3 wall-clock days**, the longest
slice, matching the architecture doc's own sequencing note that Bet Check
depends on everything above it (GameAnalysis, evidence labels, price
comparison all need to be stable contracts first). Runs after Slices 1–2
substantially land, though the parser and template work can start earlier in
parallel since it depends on contract *shapes*, not on the TODAY/GAME UI
existing.

---

## 5. SLICE 4 — ODDS (Market Board) **[table stakes, cheapest slice]**

### 5.1 API
`GET /boards/{date}` — precomputed, refreshed by the hourly capture
(architecture §3.5/§5.4), from `prices.boards_by_matchup` with a date filter
and pagination added (the only missing pieces per that doc — "nothing
structural"). Response is `Board`/`BookQuote` (§4.10): `observed_utc`
required (a board without its capture instant is not a board — two counts
from two moments cannot describe one market), per-book quotes, de-vig
`markets.h2h` with `hold_pct`.

### 5.2 UI structure
Best price + book name, de-vigged consensus, book spread/disagreement — all
REAL TODAY per `CAPABILITY_RECONCILIATION.md`. Price-age/staleness indicator
needs a designed threshold (server-computed from `observed_utc`, not
client-guessed — same manifest-table mechanism as TODAY's staleness state,
§2.5). **F5 vs full game side-by-side must not be built as populated yet** —
the capture pass is code-complete and tested but zero rows exist in any
f5-close data file as of this check (verified). Design and build the column
now, but its empty state ("F5 pricing starting to populate — check back
soon") is the only honest state until rows land (tracked separately,
TIME-GATED in COMMAND_CENTER, "first rows land tonight"). Movement column:
same caveat — it depends on spaced observations accumulating, not a
backfilled history; render as "movement over the last N hours" with N
honestly small early on, growing as the store accumulates, never implying a
longer history than exists.

### 5.3 Mobile
Handoff doesn't specify a distinct mobile board layout beyond the general
rule (tables live in their own `overflow-x:auto` container, never causing
page-level horizontal scroll) — apply that rule here directly; Advanced-only
component-system pattern from Slice 2 (§8) reused.

### 5.4 Tests
`observed_utc` required-field test (reject a `Board` without it); F5 column
renders its honest empty state when the store has zero rows (assert against
current data, not a mock, so this test fails loudly the day it should switch
behavior); price-improvement field-name ban test extended here too (`ev`,
`expected_value`, `edge`, `roi`, bare `value` forbidden — architecture §8.2).

### 5.5 Estimate
Smallest slice — the domain logic is fully real today (multi-book feed,
2,533 rows, 11 books, verified). API + date filter/pagination + tests
~0.5 day; UI structure + honest-empty-state for F5/movement ~0.5–1 day.
**~1 wall-clock day.**

---

## 6. SLICE 5 — WHAT CHANGED **[differentiator, feeds TODAY's retention band]**

### 6.1 Relationship to TODAY
Per the handoff's own IA decision (folding WHAT CHANGED into TODAY rather than
a standalone nav tab), this is not a fifth page — it is (a) a live band
already scoped inside Slice 1's TODAY component hierarchy, and (b) a
per-game section inside Slice 2's GAME page, and (c) optionally a standalone
feed view for power users. Building it as its own slice here is about the
**API and data contract**, which is shared across all three placements.

### 6.2 API
`GET /changes?date=&since=` (architecture §3.7) — precomputed, written by the
hourly watch job, from `briefing.what_changed_by_pk`. The three docstring
rules that must survive into the API verbatim: an event reaches exactly the
game it belongs to; an event seen after the information time does not
appear; a game with nothing to say gets no entry. `since` cursor is the one
missing piece (today it's a cutoff, not a watermark) — needed for "since you
last looked," which itself is ENGINEERING REQUIRED (needs accounts, N lane).
**Until accounts exist, ship "since this morning" as the only mode** — do not
build the cursor parameter's consumer before auth exists to make it
meaningful; build the cursor itself now since it's cheap and unblocks N
later without a second migration.

### 6.3 Event + market-reaction pairing
Both ingredients are real today (events from the three watch stores;
price moves from the multibook store) but the pairing logic itself ("why did
this line move," causal narrative) is explicitly V1/ENGINEERING REQUIRED —
**do not build the causal narrative for MVP.** Ship the simpler, still
valuable pairing the handoff itself shows as acceptable for MVP: event line
and, when a price snapshot exists in the same window, a juxtaposed "moved
X → Y across N books" line with no claimed causation between them.

### 6.4 States
Empty is legitimate and required: "Nothing has changed since this morning."
Relevance tiers (`relevance.py`'s `tier_rank`) gate default visibility —
tier 1–2 shown by default, "show all" reveals the rest; `UNKNOWN` tier is
spelled out as unknown, never dressed as small (architecture §4.12).

### 6.5 Tests
The three docstring invariants above as contract tests (game-scoping,
information-time cutoff, silent-game-gets-no-entry); empty-state test;
tier-default-visibility test; a test asserting the pairing line never implies
causation (no "because" / "caused by" language — grep test) until the
Why-Did-This-Line-Move feature (V1, out of MVP scope) actually ships.

### 6.6 Estimate
Ingredients are real; the work is the endpoint, cursor field, and the two UI
placements reusing Slice 1/2 components. **~1 wall-clock day**, mostly
parallel with Slice 4.

---

## 7. Slice summary and parallel wall-clock estimate

| Slice | Critical-path letter(s) | Depends on | Estimate (parallel Sonnet) |
|---|---|---|---|
| Contracts (`contracts.py`) | B | — (parallel worker, in flight) | already in progress |
| 1. TODAY | B, app/api foundation | contracts Phase 0 | 1.5–2 days |
| 2. GAME (Quick/Advanced) | G (pulled forward, non-visual) | contracts | 1.5–2 days, concurrent with 1 |
| 4. ODDS | table stakes | contracts, boards read | 1 day, concurrent with 1–2 |
| 6. WHAT CHANGED | differentiator | contracts, briefing | 1 day, concurrent with 4 |
| 3. BET CHECK | A/B | 1, 2, 4 stable | 2–3 days, starts after 1–2 substantially land |

**Engine-side total: ~4–6 wall-clock days from today (2026-08-31)**, i.e.
landing around **2026-09-04..06**, assuming 2–3 concurrent Sonnet workers on
non-overlapping files and the contracts worker finishing Phase 0 on schedule.
This covers everything up through non-visual `api/` for all five MVP pages,
Bet Check's real logic, and their full test suites — **not** styled customer
screens, which are gated on `/design` (§10) regardless of how fast this part
goes.

---

## 8. Component system — structure only

No visual specifics; that is `/design`'s job (§10). What must be decided now
so `/design`'s three artboard directions land on a stable substrate:

- **Depth model, not page model.** GAME is one component tree with a
  `depth` prop (`quick` | `advanced`), not two routed pages. Advanced always
  renders beneath Quick in the DOM (expand, never replace, never route away)
  — this is a structural commitment independent of visual direction.
- **`Claim`-typed components.** Any component that renders a rate/number
  takes a `Claim` object as a required prop, never a bare number — this
  makes "every rate ships with its sample" a compile-time/prop-type fact
  (per handoff engineering rule 4), not a per-page discipline.
- **`Gap`-typed empty/error rendering.** One shared component renders a
  `Gap` (`section`, `reason`) consistently everywhere a section is missing,
  so "name the gap, never fail silently" is one implementation, not five.
- **Evidence badge component is differential by construction** — it renders
  only when `evidence.label` is present and is a distinct family from
  `observation`, matching the "well under 20% of items" rule; it does not
  need a designer decision to satisfy this, only correct wiring to the
  contract.
- **Counterargument block cannot render empty-as-absent** — its component
  takes the `contradicting` array and unconditionally renders either the
  items or the literal fallback sentence; there is no code path that omits
  the block.
- **Tables exist only inside Advanced-View block components**, each wrapped
  in its own `overflow-x:auto` container; no table component exists outside
  that wrapper.
- Actual type scale, color, density, and the three visual directions
  (Broadsheet / Graphite Terminal / Night Game) are explicitly deferred to
  `/design` — building these structural components now in the plainest
  possible styling means the design gate skins an already-correct app rather
  than dictating its shape.

---

## 9. Auth, user state, billing, deployment — parallel lane, not last

Per the acceleration directive these start now, not after G–M. They are
gated on Brey-owned external accounts (hosting, Stripe, auth provider —
COMMAND_CENTER's decision packet in flight), so the engineering work that
*doesn't* require the accounts to exist starts immediately, and the account-
dependent pieces slot in the moment the packet clears.

- **N — Auth.** Schema now (`users`, `sessions`, `credentials` tables per
  architecture §5.5); provider integration slots in once Brey chooses one.
  Session/JWT middleware in `api/auth/` can be built and tested against a
  stub provider today.
- **O — User state.** Saved bets, watchlists, notification preferences,
  per-user settings, per-user Advanced-view-preference persistence (handoff's
  "always show advanced?" prompt after 3 opens) — schema and API now; no
  external dependency blocks this.
- **P — Billing.** Subscription state table and the rate-limit-per-tier
  hook into the matchup job queue (architecture §5.4) can be built against a
  stub plan table; the real Stripe webhook wiring waits on the account.
- **Q — One-click cancel.** Handoff requires the cancellation path be stated
  in plain language on the pricing page and be genuinely one click — build
  the UI affordance and the API endpoint now against the stub subscription
  state; wire to real Stripe on account arrival.
- **R — Deploy.** One VM/managed container, persistent disk, uvicorn + worker
  + scheduler (architecture §5.6 diagram). Scripted now; only the actual
  hosting account purchase is blocked on Brey.
- **Manifest table** (architecture §5.5) — build now; every slice above
  already depends on it for freshness/staleness states, so it is not really
  optional infrastructure, it's a Slice-1 prerequisite pulled into this lane
  because it's shared by every later slice.
- **Y — banned-language automated check** (already IN PROGRESS per COMMAND
  CENTER) — the grep-style tests referenced throughout this document (§3.4,
  §4.5, §5.4, §8.2 of the architecture doc) are exactly this check, applied
  incrementally as each slice's endpoints are added, not built once at the
  end.

None of this lane blocks the vertical slices in §2–§6, and none of the
vertical slices block this lane. They should run as literally concurrent
Sonnet workers.

---

## 10. Error / partial-data states — the cross-cutting honesty contract

Stated once here because every slice above references it rather than
re-deriving it (handoff's Missing-data UX + this document's §2.5):

1. **One failing source never blanks the app.** Every section is
   independently gapped; there is no top-level try/except that turns one
   dead upstream store into an empty page.
2. **A gap names the reason and, where knowable, the timing** — "lineups
   not posted yet — typically about 3 hours before first pitch" is a plan;
   a generic error code is a bug.
3. **Staleness is server-computed and explicit.** A price older than the
   configured freshness window is never presented as current; the manifest
   table (§9) is the single source for "is this fresh?" so no request
   handler stats a file to find out.
4. **Known unknowns stay known.** The wind/park-orientation case (0/30
   parks verified) is the model: collect the data, state plainly that no
   conclusion is drawn from it yet, and do not silently apply it once someone
   forgets it was gated.
5. **This rule set is a contract test suite, not a style guide** — every
   slice's test section above (§2.6, §3.6, §4.6, §5.4, §6.5) includes at
   least one test enforcing a piece of it, so the invariant degrades loudly
   if a later change breaks it.

---

## 11. The `/design` gate and design-sync strategy

**What it gates:** final customer *visual* implementation only — G–M
(customer screens) per COMMAND_CENTER. It does **not** gate: contracts,
`api/` foundation, any of Slices 1–4's non-visual work, auth/billing/deploy
scaffolding, or research/backend work. This document deliberately builds
every slice's UI as structural/placeholder components (§8) precisely so the
gate has minimal surface to hold up when it closes.

**Sequence:**
1. `/design` produces three artboard directions (Broadsheet, Graphite
   Terminal, Night Game per the handoff's visual-territory research) against
   the component structures this document defines — not against wireframes
   `/design` has to invent, since §2–§6 already specify component hierarchy,
   states, and data shape per page.
2. Brey approves one direction (the single human decision gate;
   COMMAND_CENTER's #1 slip risk — kept intentionally to one decision item
   to minimize latency).
3. A design system is derived from the approved direction — tokens (type
   scale, color, spacing), not a re-litigation of structure.
4. G–M apply the design system to the already-built, already-tested
   structural components from Slices 1–4. This is a skinning pass, not a
   rebuild, *if and only if* §8's structural discipline was actually
   followed — the entire value of building "structure only" now is that
   this step becomes fast.

**Design-sync strategy going forward:** whenever `/design` or Brey changes a
structural decision that this document encodes as a contract-level rule
(e.g., Quick/Advanced as one appended tree, not two routes; counterargument
always rendered), that change must be reflected back into this document and
into the corresponding contract test — the test suite is what keeps the
static generator, the API, and the eventual web app from diverging the way
the architecture doc's §10 risks warn about (13 vs 27 hypotheses; 11 vs 10
books — the same class of bug recurring a third time). Any visual-only
change (color, type, spacing) needs no sync back here.

---

## 12. Security boundary and internal admin separation

Recap and applied, not re-derived (architecture §6):

- `api/engine.py` is the sole file in `api/` permitted to import from
  `src/`; every other `api/` module imports from it. Reviewed once.
- No generic passthrough endpoint (no module-name/store-path/command-name
  parameter that executes something) — the endpoint set is a finite,
  written list (§2–§6 above are that list for MVP).
- `src.core.staking` is never importable from `api/` — a staking calculator
  behind auth is a bet-sizing product and the whole point of the Ranker gate
  (architecture §8.1) is that this system does not ship one.
- **Internal admin is a separate application, separate port, separate
  auth, sharing only the read-only files** — never a role flag on the
  customer app. This is `api/admin/` in the repo layout (§1) but must be
  deployed and authenticated independently; a role flag is "one bad `if`
  away from a customer seeing the lab" (architecture doc, verbatim).
- Response schema is a closed Pydantic set — an internal object cannot leak
  by accidental serialization; it would have to be deliberately mapped into
  a customer model first.
- V (security review) on the critical path is the point where this section
  gets audited against the actual `api/` tree, not assumed correct because
  it was designed correctly.

---

## 13. Cache strategy and live-update strategy (recap, applied)

- **Cache:** matchup on-demand analysis (`POST /matchups`) is the only
  expensive on-demand endpoint; cached on `(away, home, date,
  engine_version)`, immutable once the date is past (architecture §5.4).
  Everything else in §2–§6 is a precomputed read — "cache" for those
  endpoints means the manifest table's freshness field, not a request-time
  cache layer, because the data doesn't change between scheduled writes.
- **Live update:** nothing in this MVP is a websocket/push feed. WHAT
  CHANGED (§6) and TODAY's stale-price state (§2.5) are both **poll-and-
  compare against a `since` cursor / freshness timestamp**, matching the
  existing hourly-capture cadence — building a push mechanism ahead of that
  cadence would imply a real-timeliness the underlying jobs don't provide.
  Push notifications (S monitoring / alerts) are explicitly V1+, out of MVP
  scope per COMMAND_CENTER's NOT ON THE PATH list.

---

## 14. Test strategy

- **Structural tests, written once, apply everywhere:** import-graph
  allowlist (`api/` → `src/`), stdlib-only (`src/**`), forbidden-field-name
  grep (`ev`/`edge`/`expected_value`/`roi`/bare `value`), forbidden-
  vocabulary grep (internal research tokens reaching `api/`/`web/`),
  Engine-2-language absence extended to the API's OpenAPI schema and sample
  responses (architecture §8.1's structural-test technique, generalized).
- **Per-slice contract tests** as specified in §2.6/§3.6/§4.6/§5.4/§6.5 —
  each slice's PR is not done until its section's tests pass.
- **Full suite before any slice is called done.** Baseline at the time of
  writing: **2,113 tests OK at HEAD** per COMMAND_CENTER (2026-08-31 22:10Z);
  other workers are active in parallel (Evolab Phase 1/2B, dashboard
  extraction, Bet Check domain work per COMMAND_CENTER's ACTIVE NOW/WAVE 2),
  so the exact count at the moment any given slice lands will differ — run
  the suite and report the actual number rather than assuming this baseline
  still holds.
- **The Ranker `ENGINE2` gate and `tests/test_ranker.py` are untouchable** —
  no slice in this plan modifies them; any change to them is out of scope
  here and requires its own reviewed diff per architecture §8.1.
- **2025 is tuning-only; 2026-01-01..2026-08-27 is SEALED** — no test or
  fixture in any slice reads results in the sealed range to validate
  behavior; use synthetic fixtures or the tuning-only 2025 range instead.

---

## 15. Open items this plan does not resolve

- Exact wire shapes for every field are `contracts.py`'s job, not this
  document's — where this plan names a field (e.g., `Board.observed_utc`,
  `BetCheck.recommendation`), it is citing the architecture doc's contract
  section as the interim reference pending `contracts.py` landing; the build
  agent should prefer `contracts.py` verbatim the moment it exists and treat
  any conflict as `contracts.py` winning.
- Auth provider, hosting, and payment provider choices are Brey's per the
  decision packet in flight — this plan assumes their existence structurally
  (schema now, wiring later) but does not choose them.
- The exact three `/design` visual directions and Brey's choice among them
  are unknown until that gate closes; §11 describes the *process*, not the
  outcome.
