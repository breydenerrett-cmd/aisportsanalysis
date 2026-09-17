# PROJECT_STATE — forensic reconstruction, 2026-09-17

Method: `git log`/`git show` against the full history (1,705 commits on
`claude/sports-betting-analysis-review-g1o0co` as of `d156ab78`, 2026-09-17
14:57 local), cross-checked against the working tree and against
`docs/NEVER_RAN_REGISTER.md` (Stage 18 H1, commit `623f2b03`) rather than
copied from it. Every claim below carries a `file:line` and/or commit sha.
Where a doc and the code disagree, both are stated and the disagreement is
left open — this file does not adjudicate it.

Branch note: the local branch and `origin/claude/sports-betting-analysis-review-g1o0co`
have diverged (22 local vs 138 remote commits at time of writing), entirely
because two independent automation loops (`afternoon-slate.yml`,
`forward-capture.yml`) commit from both the session container and GitHub
Actions runners against the same branch name. Diffing showed the divergent
commits are all `Afternoon slate 2026-09-1{6,7}` / `Forward capture slot
...Z (external)` bot commits, not competing feature work. Branches `sc2`,
`sc3`, `staging-check`, `afternoon-default` and
`claude/cowork-session-migration-tn3sx2` are the same kind of
automation-registration artifact (e.g. `afternoon-default@d43f19b2`:
"Register afternoon-slate on the default branch (Actions schedule
visibility)"), not abandoned feature branches.

---

## INTENDED (answers A)

Read from the earliest commits, in order, on `--reverse`:

- `be8c99b5` "Add correctness core: de-vig, calibration, staking" — the
  project began, before any data ingestion existed, by building the three
  modules everything else must route through: `src/core/odds.py` (de-vig via
  proportional/power/Shin/additive), `src/core/calibration.py` (Brier,
  log-loss, reliability, ECE/MCE, scoring criteria fixed *before* any model
  is fit), `src/core/staking.py` (Kelly, refused when the model is flagged
  uncalibrated). Commit message: "Comparing a model probability against raw
  implied probability overstates edge, worst on favorites; every edge
  calculation must route through devig() first." 100 tests, no network
  calls, "Expected values are hand-derived from the definitions rather than
  read back from the implementation." This is the founding discipline of the
  whole repo: correctness primitives before data, tests derived
  independently of the code under test.
- `eca8fa2c`, `6f66dd17`, `e9d7a84c`, `9b636460` — data providers (MLB Stats
  API, ballpark/wind, Open-Meteo weather) and an idempotent, resumable
  historical results store, built next.
- `9b6b9907`/`9b636460` region and `eed2eb0c` "Add historical source audit,
  validation criteria, and README" — the first README and the first
  validation criteria appear together, i.e. the project's own written
  intent from day one was paired with a criterion for judging whether the
  intent had been met, not shipped as aspiration alone.
- `1ecb6162` "Add calibrated probability model: the project's first real
  prediction" and `73c2dfc8` "Add prediction against live market, with a
  diagnostic that refuses to flatter it" — the stated goal from the first
  model onward was never "beat the market" as an assumption; it was "measure
  against the market honestly and report what is found," including a
  diagnostic built specifically so the model could not flatter itself.
- `72ac4d50` "Add CLAUDE.md: keep responses short" and `01bb74fa`/`ab21f3f2`
  (game plan / research plan / "autonomous work around a briefing, not a
  verdict") establish the working method (short replies, plans checked
  against evidence, not verdicts asserted) very early, well before the
  product had a name.

**Original intent, in one sentence supported by the above:** build a
correctness layer first, then real point-in-time data, then a model that is
measured against the market rather than assumed to beat it, with every
finding — positive or null — recorded as evidence. There is no commit in the
first ~40 that mentions a UI, a customer, a price, or a business name; the
commercial framing (README.md's current pitch, `docs/MASTER_PLAN.md`,
`docs/REVENUE_PLAN.md`, the "Linehound" brand) is a later layer over a
research project, not the founding motivation.

---

## IMPLEMENTED (answers B, G, H)

### B — what actually exists as running code

- **Correctness core** (`src/core/odds.py`, `src/core/calibration.py`,
  `src/core/staking.py`) — present, exercised by 100+ tests since `be8c99b5`.
- **Data pipeline**: MLB Stats API provider, Open-Meteo weather, odds
  provider (`src/providers/odds.py`), point-in-time team/pitcher features
  with "structural lookahead prevention" (`e085d28c`, `200ec51e`).
- **Two independent card rules**, both implemented, only one wired live (see
  PRODUCTION):
  - V1, `DAILY_CARD_MARKET_SIDE_MODEL_AGREEMENT_V1`
    (`src/analysis/daily_card.py:1-60`): side = de-vigged market consensus,
    demoted (never promoted) when the in-house run model disagrees; ranks by
    consensus confidence; `MIN_PICKS` is a floor met by relabelling
    (`SPLIT`), never by inventing a claim.
  - V2, `DAILY_CARD_BEST_BETS_V2` (`src/analysis/best_bets_card.py:1-40`):
    ranks by a Kelly fraction on a deliberately marked-down probability
    (`score`), gates MAIN (-160..-100) and PLUS_MONEY (+100..+250) price
    classes separately, pure/stdlib-only, registered in
    `docs/PREREG_CARD_V2.md`. Owner directive behind it, cited in the
    module's own docstring history: "value x confidence," consistent with
    the user's memory note "Probability before price... Brey switched it to
    one value x confidence score, wants +100 to +250 underdogs."
- **Paper-trading / settlement engine** (`src/engine/*.py`) — a different
  object from "Engine 2" below despite the shared word. Its own docstring:
  `src/engine/__init__.py:1` "src/engine: the waist. See
  docs/ENGINE_CONTRACT.md." Contains `slate.py`, `slip.py` (evidence:
  `evidence/slips_v1.jsonl`, 256 rows per NEVER_RAN_REGISTER), `settle_slate.py`,
  `adversaries.py`, `conformance.py`, `truncation.py`, `mechanism_predicates.py`.
  This is live (see PRODUCTION).
- **Evolution Lab** (`src/evolab/`) — 15 real modules (`baseline.py`,
  `bitsets.py`, `ceiling.py`, `cscv.py`, `decide.py`, `feed.py`, `genome.py`,
  `lifecycle.py`, `overlap.py`, `placebo.py`, `registry.py`, `replay.py`,
  `spa.py`, `sweep.py`, `wagers.py`), not a design doc only. It DID run:
  Phase 2B's exhaustive sweep produced a real artifact,
  `data/research/evolab/sweep-0014914df78666b9-REAL.json`
  (`docs/EVOLAB_PHASE2B_RESULTS.md:5-6`). See VERIFIED and REJECTED for its
  outcome — the code that exists past Phase 2 (Phase 4+ evolution/islands/
  meta-learning/champion-ladder/UI, `docs/EVOLUTION_LAB_ASSESSMENT.md`
  "PHASE 4+") was never built, by design, because Phase 2 killed it.
- **Alpha registry** (`src/research/alpha_registry.py`) — real, append-only,
  enforced in code (`register()`/`record_verdict()` both refuse duplicate
  rows; module docstring lines ~50-70). Live data file:
  `data/research/alpha_registry.jsonl`.
- **Web/API surface** (`api/`, `web/`) — FastAPI routes (`api/card.py`,
  `api/games.py`, `api/digest.py`, `api/performance.py`) serving the card,
  record, and analytics; SQLite-backed analytics (`analytics_events`,
  `free_check_grants` tables per NEVER_RAN_REGISTER).

### G — experimental (flagged in code, not customer-facing)

- **NFL**: `src/sports/nfl.py:39` sets `experimental=True`. NFL card path
  exists (`src/report/nfl_card.py`) and is scheduled
  (`scripts/capture_slot.sh:557`, `scripts/daily_loop.sh:282`) but has
  **never produced an artifact** — `evidence/cards_nfl_v1.jsonl` has 0
  commits in `git log --all`. Confirmed independently: file absent from the
  working tree.
- **Tennis**: `src/sports/tennis.py` is, per its own docstring, a
  "Constants-only stub: the provider lands later... `schedule_fn=None`,
  `team_abbrev_fn=None`," `experimental=True`. `api/card.py:97-104` returns a
  static "Research only" notice for `sport == "tennis"` rather than calling
  any tennis card path at all — confirmed by reading that branch directly.
- **Card V2** — implemented but pre-registration (see PRODUCTION); its own
  code is not "experimental" in the flag sense but is deliberately kept off
  every default surface (`ACTIVE_CARD_RULE = "v1"`,
  `src/report/card.py:592`).
- **Private in-play watcher (W-16)** — `docs/ROADMAP.md` Stage 18 item B2,
  explicitly "not yet run" per its own acceptance-criteria wording ("One
  real match watched end to end... is the *acceptance*, not a past fact").

### H — dead code / permanently gated off

- **"Engine 2"** (predicted-value ranking) is the clearest permanently-gated
  path in the repo, and it is a *different* object from `src/engine/` (see
  above — same English word, two unrelated systems; worth flagging because
  the audit brief's own phrasing conflates them). The gate lives in
  `src/report/ranker.py:1-33`:
  - `ENGINE2 = None` (`src/report/ranker.py:33`), with the docstring: "Engine
    2 is predicted value. It requires a demonstrated edge, and none exists:
    see src.analysis.HYPOTHESES_TESTED pre-registered hypotheses across
    HYPOTHESIS_FAMILIES research families, zero survivors."
  - `HYPOTHESES_TESTED = _COUNTS["read"]` / `HYPOTHESIS_FAMILIES =
    _COUNTS["families"]` (`src/analysis/__init__.py:114,116`) — a single
    computed source of truth, added specifically because three surfaces had
    previously disagreed on the count ("this banner said twenty-four while
    the briefing header said thirteen and its game cards said 27" —
    `src/report/ranker.py` docstring). This is a directly-cited example for
    J below.
  - `src/analysis/contracts.py:507,539,544` enforces the gate structurally:
    `recommendation: None = None   # permanently None while Engine 2 is
    None`.
  - `src/ledger/writer.py:6` references "'Ranker Engine 2 stays gated'
    discipline `tests/test_ranker.py` already [enforces]" — i.e. the gate is
    pinned by a test, not just a comment (see TESTED).
  - Unlock condition, per `src/report/ranker.py` docstring: every condition
    in `docs/PLAN_TWO_TOOLS.md` — pre-registered discovery pass,
    falsification battery, 300+ forward selections, and Brey's sign-off.
    None of these are met as of this audit.
- **Card V2 shadow/variant stores** are code-complete but registration-gated
  off, not dead in the sense of unreachable — they are unreachable *only*
  until `T0`/`T13` (see PRODUCTION). `card_ledger.py:1435-1450` names them:
  `cards_v2.jsonl`, `cards_v2_shadow_{a,c,e}.jsonl`,
  `cards_v2_var_{strict_nocap,loose_cap3,loose_nocap}.jsonl`. One store is
  gated permanently *by design*, not by schedule: `card_ledger.py:1446-1450`,
  "THERE IS NO `CARD_STORE_V2_SHADOW_D`... `evidence/cards_v2_shadow_d.jsonl`
  must never be created by this module."
- **`data/research/scoreboard.jsonl` / `shadow_battery_report.json`** — last
  written 2026-09-06 per NEVER_RAN_REGISTER's DORMANT classification; code
  path exists, has run before, has not run in the ~11 days before this
  audit.
- Two files were deleted outright across history (`git log --diff-filter=D
  --summary --all`, 8 total delete-mode lines, of which two touch `src`/`docs`):
  `docs/CODEX_HANDOFF.md` and `src/model/bullpen_grade.py`. This repo
  otherwise does not delete — it supersedes in place (frozen constants,
  correction-suffixed ids) — so the near-absence of deletions is itself a
  fact about the project's discipline, not a gap in this search.
- **`data/live/` event store, gap log, candidate ledger**
  (`src/pipeline/live_window.py`, `src/appstate/live_ledger.py:70`) — code
  exists, is wired into three schedulers, and has never written a byte. This
  is functionally dead code (nothing has ever executed its write path
  successfully) but is *not* an intentional gate — see PRODUCTION/UNKNOWN,
  because NEVER_RAN_REGISTER (`623f2b03`) flags this as ALARMING rather than
  expected, and I independently confirmed `git log --all -- data/live`
  returns nothing and the working tree has only an empty `data/live/mlb/`.

---

## TESTED (answers C)

- `tests/` (381 `test_*.py` files by direct count) plus a handful of
  root-level `test_*.py` debug scripts (`test_backward_compat.py`,
  `test_byte_identity.py`, `test_capture_timestamps.py`, etc. — these read
  as ad hoc debug scripts left in the repo root rather than part of the
  `tests/` suite; none are referenced from `.github/workflows/tests.yml`,
  which only discovers `tests/`).
- **The suite's own reliability was falsified as a fact, not assumed**: `docs/ROADMAP.md`
  Stage 18 H7 / commit `e6166a1c` — "Counts observed today, same tree, same
  day: 40+2, 38+1, 42+1, 43+3, 18+1... the parallel runner alone moved
  between 18 and 43." Root causes identified: tests reading stores a live
  capture job mutates mid-run, and load-sensitive assertions (peak RSS
  reading 0.0). Direct consequence, stated in the same commit: "three stale
  `live_window --settle` assertions sat red for hours while being read as
  part of the known noise." Filed, not fixed, as of `e6166a1c` — H7 remains
  open per `d156ab78`'s own "Remaining in Stage 18" list.
- **Structural pins exist for the things that matter most**: `tests/test_ranker.py`
  pins that "while ENGINE2 is None the page contains no bet recommendation,
  no pick, no unit size, and no 'edge' language" (`src/report/ranker.py`
  docstring, corroborated by `src/ledger/writer.py:6`).
  `tests.test_t0a_card_v2_backfill` (26 tests, `c59300fd` commit message) pins
  the V2 2025 backfill's determinism (identical sha256 across two runs) and
  the sealed-window guard actually killing the process rather than filtering
  a row.
- **T0a verification was independent of the code path being tested**:
  `c59300fd` describes re-deriving pitcher/bullpen/boxscore season counts
  from the data directly ("pitcher_logs_2025 8,830 rows... every one of them
  2025, zero rows from any other season") rather than trusting the
  `_sealed_guard` that was also under test — i.e., the maker/checker split
  the user's own engineering principle calls for was actually applied here.
- **A test that could not be re-derived was found and disclosed rather than
  silently kept**: `66d943e5` ("14.3b says what it can support") — an
  independent check tried to reproduce section 14.3b's four-arm table from
  the committed tree and failed for two reasons: `scratchpad/variants/variant_family.py`
  (the cited source) was never committed, and the calibration snapshot used
  at publish time was overwritten by a later daily loop and survives only at
  `7db02b0a`. The commit's own conclusion: "the derivation is unavailable,"
  logged against Stage 18 F2 ("Evidence-store durability").
- `.github/workflows/tests.yml` runs on every push to every branch and on
  PRs (`on: push: branches: ["**"]`, `pull_request`, `workflow_dispatch`,
  lines 6-10) — so the suite is CI-gated on every commit, independent of the
  flakiness documented above.
- CI network isolation was a day-one concern: `fc9c55e9` "Add CI with a
  network-isolation guard," predating almost everything else in the repo.

---

## VERIFIED (answers D — falsified findings — and confirms what was
independently re-checked rather than merely claimed)

**Falsified / killed, with the mechanism, per project discipline (mechanism +
kill condition stated in advance, per `docs/ROADMAP.md` Stage 19's own bar):**

- **Evolution Lab Phase 2B — the strongest null in the project.**
  `docs/EVOLAB_PHASE2B_RESULTS.md:1-3`: "Verdict: `BELOW_PLACEBO_CEILING`.
  Evolution does not get built." 8,811 strategies searched over 4,188 real
  games (2023: 2,089 / 2024: 2,099); real max movement fitness 0.004882 vs.
  placebo maxima of 0.007490-0.008821 across three generators — "the real
  maximum is not merely under the ceiling, it is under the middle of the
  noise." Corroborated independently by PBO = 0.6111 (CSCV, 252 splits;
  above 0.5 means in-sample selection *anti-predicts* out-of-sample rank).
  Pre-registered as the likely outcome before the sweep ran
  (`docs/EVOLAB_PHASE2B_RESULTS.md` §6, citing design §14b and Phase 2A's
  prior +0.0000412 log-loss/game result). Scope caveat added later
  (2026-09-02, same doc, bottom): the genome schema names `h2h` and
  `h2h_1st_5_innings` markets but `src/evolab/feed.py` sourced full-game h2h
  only, so the headline is an h2h-only search — noted as bounding, not
  reversing, the verdict.
- **M4 (F5 vs full-game bullpen gap)** — `docs/RESULTS_V2.md:18,228,260-262`:
  "UNDERPOWERED — no signal at n=270," effect +1.25pp, p=0.665, "the only
  hypothesis that died of sample size rather than of evidence" — explicitly
  distinguished from a hypothesis that died of evidence, which is a real,
  stated methodological distinction rather than a hedge.
- **The in-house probability model versus the market** —
  `src/analysis/daily_card.py` docstring: "measured walk-forward over 1,896
  games of 2026 (`scripts/backtest_card.py`), the model beats a coin that
  knows only the home-field base rate by 0.0012 nats. A market beats that
  baseline by an order of magnitude more." Consequence, same doc: the model
  is used only for agreement/disagreement signaling, never as an independent
  edge source — this is the design reason V1 demotes on disagreement instead
  of promoting.
- **Alpha registry aggregate** (`data/research/alpha_registry.jsonl`, 92
  rows verified directly by parsing the file): 47 hypotheses + 1 sweep + 2
  audits registered; 42 verdicts recorded — 35 null, 2 false_positive, 2
  candidate, 2 audit, 1 withdrawn. **Zero rows carry `result: "survivor"`.**
  By family: V1 (21), V4 (6), V3 (5), V2 (5), V5 (3), LIVE_V0 (3), EVOLAB_PHASE2B (1),
  ELO_BENCHMARK (1), V6 (1), V7 (1), NFL_CARD_V1 (1), SR (2). 48 rows tagged
  `sport=mlb`, 2 tagged `nfl`.
- **SR1 (home-underdog family)** — cited in `docs/ROADMAP.md` Stage 19: "died
  on a sign flip between 2023 and 2024, which is what a strategy with no
  mechanism does," used as the project's own example of what an unfalsifiable
  strategy looks like.
- **Card labels (STRONG/LEAN/SPLIT) removed** — `docs/ROADMAP.md` D1 /
  commit `d248dbe3`: those labels "were driven by MARKET confidence, so a
  short-priced favourite wore the same badge as real value — the owner's own
  2026-09-15 complaint." A design choice falsified by the owner's direct
  feedback and removed, not merely deprecated.

**Independently re-verified rather than taken on the document's word (this
audit's own checks against NEVER_RAN_REGISTER, `623f2b03`):**

- Confirmed `ACTIVE_CARD_RULE = "v1"` directly at `src/report/card.py:592` —
  matches the register's implicit claim that V1 is the only published rule.
- Confirmed `git log --all -- data/live` returns nothing and the tree has
  only an empty `data/live/mlb/` directory — matches the register's
  NEVER-RAN verdict for the live window.
- Confirmed `evidence/cards_nfl_v1.jsonl` has 0 commits in
  `git log --all --oneline` — matches.
- Confirmed no workflow or script references `deploy/fly.production.toml` or
  `linehound-prod` outside its own config file and planning docs — this is a
  fact the register does not cover and is new to this audit (see PRODUCTION).
- Spot-checked `src/engine/__init__.py:1` and `src/report/ranker.py:1-33` to
  disambiguate "Engine 2" from `src/engine/` — the register does not
  discuss this distinction; it matters because the audit's own framing
  conflates the two.

---

## PRODUCTION (answers F)

**Scheduled and actually reaching a store or a user, confirmed by workflow
trigger config plus NEVER_RAN_REGISTER's independent row-count evidence
(spot-checked, not re-derived in full — see UNKNOWN):**

- `.github/workflows/daily-loop.yml:27-32` — `cron: "0 10 * * *"`, i.e. daily
  at 10:00 UTC, before first MLB pitch. Drives `scripts/daily_loop.sh`,
  which per NEVER_RAN_REGISTER runs `card settle`, `src.appstate.live_ledger
  settle`, EOD review, and CLV backfill.
- `.github/workflows/afternoon-slate.yml:73-74` — `cron: "40 15 * * *"` (note
  the file's own comment: "THIS CRON IS NOT THE ONE THAT FIRES — IT MUST
  STILL MATCH THE ONE THAT DOES," i.e. there is a known duplication/mirroring
  risk between this file and whatever branch actually triggers Actions,
  flagged by the project itself, not discovered here). Publishes the MLB
  card (`card publish`) and, per `scripts/capture_slot.sh:557`, the NFL card
  (never-produces, see IMPLEMENTED/G).
- `.github/workflows/forward-capture.yml:23-38` — `cron: "*/15 * * * *"`,
  every 15 minutes. Comment at line ~26 notes GitHub disables scheduled
  workflows on public repos after 60 days of repo inactivity — a real
  operational risk the project has documented against itself.
- `.github/workflows/deploy-staging.yml:12-52` — triggers on push to
  `claude/sports-betting-analysis-review-g1o0co` touching `api/**`,
  `src/**`, `web/**`, `deploy/**`, and a long list of specific data stores
  (the file's own comments document at least one past incident where a
  registry-only commit "deploy[ed] nothing and left staging's count stale").
  Deploys to Fly app `linehound-staging` (`deploy/fly.staging.toml:20`).
- `.github/workflows/live-window.yml` and `.github/workflows/tennis-results-check.yml`
  are `workflow_dispatch`-only (no cron) — dispatched programmatically by
  `scripts/capture_slot.sh`, not on their own schedule.
- `.github/workflows/balldontlie-harvest.yml` is explicitly
  `workflow_dispatch` only, by design: "this drains a one-time trial, it is
  not a recurring job" (file comment, lines 13-14).
- `.github/workflows/tests.yml:6-10` runs on every push to every branch and
  every PR — the only workflow with unconditional per-commit triggering.

**Daily card, V1 vs V2 — resolved directly from code, not inferred:**

- V1 (`src/analysis/daily_card.py`) is `ACTIVE_CARD_RULE` (`src/report/card.py:592`)
  and is what every caller gets by default (`api/card.py:_resolve_rule`,
  `~line 60`: "`?rule=` defaults to `card_mod.ACTIVE_CARD_RULE`... every
  existing caller... keeps getting exactly what it always has — V1"). It
  ranks by **market consensus confidence with model agreement as a demotion
  signal only** (see IMPLEMENTED). It publishes to `evidence/cards_v1.jsonl`
  — 140 `card_published` rows per NEVER_RAN_REGISTER, first seen 2026-09-10.
- V2 (`src/analysis/best_bets_card.py`) is reachable only via `?rule=v2`
  (`api/card.py`, the `rule=="v2"` branch, ~lines 192-210), and that branch
  **builds live on every request** rather than reading a published record —
  its own docstring: "Nothing publishes V2 before T0's registration commit,
  so in practice every request through this path today builds live." It
  ranks by **a Kelly fraction on a marked-down probability**
  (`best_bets_card.py` docstring, "value x confidence"), gated by MAIN/
  PLUS_MONEY price classes. `evidence/cards_v2.jsonl` and all its shadow/
  variant stores have **zero commits, ever** (NEVER_RAN_REGISTER, confirmed
  independently above).
- **Registration status of V2, as of this audit**: `docs/CARD_V2_BUILD_PLAN.md`
  names `T0` ("Brey answers 12, 13 and 14, commit the registration with the
  fingerprint value") as the un-run gate, blocking `T13` (the actual cutover
  that would flip `ACTIVE_CARD_RULE`). `T0a` (the one-time 2025 backfill and
  frozen parameter file) was completed same-day as this audit, `c59300fd`
  (2026-09-17 14:31): "The last blocker before V2 can be registered." As of
  the latest commit read (`d156ab78`), the commit message states "T0 — the
  V2 registration itself — is now unblocked on every dependency" but has
  **not yet happened**. V2 is therefore fully implemented, forward-tested
  live-build-only, and one un-executed step away from a scheduled publish —
  not live today.

**Production (customer-facing, not staging) Fly deployment: does not
currently exist as an automated path.** `deploy/fly.production.toml:18`
defines app `linehound-prod`, but:
- No workflow file references `fly.production.toml` or `linehound-prod`
  (checked: `grep -rln "fly.production" .github/workflows/ scripts/` returns
  nothing).
- `deploy/DEPLOY_RUNBOOK.md:5`: "Nothing here runs until Brey provides the
  [production credentials]" and its own "Staging -> production promotion
  checklist" (line 168 onward) lists as *unchecked, future* steps: "Create a
  SEPARATE Fly app for production," "Create a SEPARATE volume for
  production," "Set SEPARATE production secrets" — i.e. as written, the
  `linehound-prod` Fly app may not even have been created yet on Fly's side;
  this file only proves it has not been created *through this repo's
  tooling*.
- Conclusion: **the only thing currently deployed and reachable by an
  outside visitor is `linehound-staging`.** Every "production" reference in
  docs (`docs/LAUNCH_DAY_CHECKLIST.md`, `docs/COMMERCIAL_READINESS.md`, etc.)
  is planning language for a cutover that, per the runbook itself, has not
  happened.

**Engine 2 gate location, precisely (answers the audit brief's H question,
correcting its premise):** the brief asks whether "Engine 2" under
`src/engine/` is gated. It is not under `src/engine/` — that package is the
paper-trading/settlement "waist" (`src/engine/__init__.py:1`). The predictive
-value "Engine 2" concept lives in `src/report/ranker.py:33`
(`ENGINE2 = None`), gated by the zero-survivor count at
`src/analysis/__init__.py:114,116` and pinned by `tests/test_ranker.py`
(referenced at `src/ledger/writer.py:6`). Unlock conditions are in
`docs/PLAN_TWO_TOOLS.md`, none met as of this audit.

---

## PROPOSED (things that exist only as a document or a pre-registration,
not as running/scheduled code)

- **Evolution Lab Phase 4+** (evolution, islands, meta-learning, champion
  ladder, UI) — `docs/EVOLUTION_LAB_ASSESSMENT.md` "PHASE 4+... Conditional
  on Phase 2 showing real signal above the placebo ceiling. If it does not,
  these phases are not built." Phase 2 did not clear the ceiling (see
  VERIFIED), so per the project's own stated conditional logic, Phase 4+ is
  correctly unbuilt, not merely unfinished.
- **Private in-play watcher (W-16 / Roadmap B2)** — two of three owner
  decisions answered per `docs/ROADMAP.md`, code not yet run against a real
  match.
- **NFL live window firing for the first time (Roadmap B4)** — proposed
  acceptance criterion is "a real dispatch → capture → candidate row, or an
  honest no-trigger with the reason" — explicitly not yet observed.
- **Cadence SLO** (`src/capture/cadence.py:56`, `src.cli cadence`) — code
  exists, has never been run; NEVER_RAN_REGISTER grades it EXPECTED rather
  than alarming specifically because "no scheduler, workflow or document
  claims it runs" — i.e. this is a genuinely proposed-only surface, not a
  broken scheduled one.
- **Production Fly cutover** — see PRODUCTION above; this is the clearest
  "fully documented, zero automation" item in the repo.
- **Prop-listing feasibility measurement (Option A, `docs/EVOLUTION_LAB_ASSESSMENT.md` §9)**
  — explicitly a recommendation awaiting the owner's decision: "Brey decides.
  Nothing starts without his word." No evidence found that this was acted on
  (would need a follow-up doc or a `data/research/evolab` feasibility
  artifact dated after the assessment to confirm either way — see UNKNOWN).

---

## REJECTED (answers I — abandoned, with the reason found in the record,
not guessed; plus falsified items already covered under VERIFIED that were
also explicitly killed/abandoned as a research direction)

- **Evolution Lab, as a build-the-evolutionary-loop direction** — abandoned
  by its own pre-registered kill criterion, not by loss of interest or
  budget: `docs/EVOLAB_PHASE2B_RESULTS.md` §6, "The kill criterion (design
  §15) fires... evolution does not get built. No elites, parent pools,
  mutation, crossover, immigrants, islands, lineage or meta-learning."
  Reason: BELOW_PLACEBO_CEILING in 3 of 3 generators, corroborated by
  PBO=0.61. What survived the abandonment, per the same doc: the replay
  engine and the noise-ceiling harness, explicitly kept as "permanent
  instruments" for other research lines (F5, props, V3 timing).
- **M4 (F5 vs full-game bullpen gap)** — abandoned for underpower, not for a
  null effect estimate; `docs/RESULTS_V2.md:323-331` treats "rescue by more
  data" as "a real decision, not a recommendation" and lists both sides
  rather than deciding for the reader — this is presented as an open
  editorial choice, not a closed rejection, worth noting as a partial
  exception to a clean REJECTED classification.
- **SR1 home-underdog family** — killed on its own pre-declared kill
  condition (a sign flip 2023→2024); used by the project as its canonical
  cautionary example of "a strategy with no mechanism" (`docs/ROADMAP.md`
  Stage 19 preamble).
- **STRONG/LEAN/SPLIT card labels** — rejected because of a named,
  attributable owner complaint (2026-09-15) that the labels tracked market
  confidence rather than value, cited verbatim as the reason in `d248dbe3`.
- **`bullpen_grade.py`** — deleted (`git log --diff-filter=D`). No commit
  message located that names the reason directly in the deletion commit
  itself in the time available for this audit; flagged under UNKNOWN below
  rather than guessed.
- **`docs/CODEX_HANDOFF.md`** — deleted. Same caveat as above.
- **14.3b's four-arm illustration** — not deleted but explicitly downgraded:
  `66d943e5` treats an un-reproducible exploratory table as something to
  annotate honestly rather than delete, on the stated principle that
  "deleting an inconvenient illustration from a pre-registration is the
  worse act." This is a deliberate non-rejection worth contrasting with the
  above: the project distinguishes "this claim is now known-weaker, disclose
  it" from "this direction is dead, kill it."

---

## UNKNOWN (answers E, and flags where a conclusion may have hardened into
an unchecked assumption — J)

**E — genuinely open per the record itself (not this audit's failure to
look), each with what would resolve it:**

- **Whether the live-window schedulers ever actually attempted a dispatch.**
  NEVER_RAN_REGISTER lays out a four-step diagnostic (run
  `--should-dispatch` by hand during a live window; check `gh run list
  --workflow live-window.yml`; check whether the runner's checkout even
  contains `data/live`; confirm an upstream in-play feed exists at all) and
  states plainly that none of the four had been done as of `623f2b03`. This
  audit did not run any of them either — doing so would require running a
  live capture job or inspecting GitHub Actions run history via `gh`, both
  outside this audit's read-only, no-credit-spend mandate. **To establish:**
  run the four-step diagnostic during an actual MLB live window.
- **Whether `load_first_five_results()` returns `{}` or raises on the
  missing `first_five_results.jsonl`.** NEVER_RAN_REGISTER names this as the
  next check and it was not performed (would require reading
  `src/engine/settle_slate.py` around line 55 and tracing every call site —
  not done in this pass because it verges into "assessing correctness,"
  which this audit was scoped to observe, not adjudicate). **To establish:**
  read `load_first_five_results()`'s body and its callers, or exercise it
  against a deliberately-missing file in an isolated test.
- **Why `bullpen_grade.py` and `docs/CODEX_HANDOFF.md` were deleted.** Only
  8 delete-mode entries exist in the entire history, an unusually small
  number for 1,705 commits, and the deleting commits' messages were not
  individually read in this pass. **To establish:** `git log --all --follow
  --diff-filter=D -- src/model/bullpen_grade.py docs/CODEX_HANDOFF.md` and
  read each full commit message.
- **Whether the prop-listing feasibility Option A (docs/EVOLUTION_LAB_ASSESSMENT.md §9)
  was ever approved and run.** Not checked in this pass beyond confirming
  the doc poses it as an open decision. **To establish:** search
  `data/research/evolab/` and `docs/` for a dated feasibility artifact after
  the assessment's date, and check the alpha registry for a corresponding
  row.
- **The actual current CI pass/fail state of the 381-file test suite.** This
  audit deliberately did not execute the suite (read-only mandate, plus H7's
  own finding that a bare run is not currently a trustworthy signal without
  KNOWN/NEW classification). **To establish:** read the most recent
  `tests.yml` Actions run's log rather than re-running it locally.

**J — a specific, cited instance of a conclusion that hardened into an
assumption before this audit re-checked it, plus the two most likely
candidates for the same pattern that this audit did not have time to run
to ground:**

- **Confirmed instance**: the "hypotheses tested" count itself. Before
  `src/analysis/__init__.py:114,116` centralized it, three different
  surfaces (the ranker banner, "the briefing header," "its game cards")
  had each computed or hard-coded their own count and disagreed (24 vs 13
  vs 27) — a single research fact ("we have tested N hypotheses") had
  clearly been asserted independently in at least three places rather than
  read from one source, and by the time this was caught each of those
  numbers had presumably been treated as a settled fact in its own surface.
  Fixed by making it one property (`src/analysis/__init__.py`), not three
  assertions.
- **Confirmed instance**: 14.3b's four-arm table (`66d943e5`) had been
  cited as an illustration of the registration's behavior — "an
  illustration nobody can re-run" is the commit's own title — until an
  independent check tried to regenerate it and found the source code
  behind it had never been committed and the calibration snapshot behind
  it had been silently overwritten by a later, unrelated daily loop. The
  finding sat as fact for at least one full daily-loop cycle before the
  independent check ran.
- **Live candidate for the same pattern, not run to ground here**: the F5
  sealed-results docstring calls `data/historical/first_five_results.jsonl`
  "a frozen historical store" (per NEVER_RAN_REGISTER's quote of
  `src/engine/settle_slate.py`), a description that implies the store is
  populated and immutable. The file has never existed in git or on disk.
  Any downstream number computed by code that reads this "frozen" store
  without checking for its absence would be exactly this pattern — a
  documented conclusion ("F5 sealed results exist and are frozen") treated
  as settled when the underlying artifact was never produced. This audit
  flags it as a candidate rather than a confirmed instance because
  `load_first_five_results()`'s actual failure behavior was not read (see
  E above) — it may raise loudly rather than silently return an empty
  result, which would make this a non-issue.
- **Live candidate, not run to ground here**: H7's own test-suite finding
  ("three stale `live_window --settle` assertions sat red for hours while
  being read as part of the known noise") is itself a description of this
  exact failure mode happening operationally, in real time, with a human
  agent doing the misclassifying. It is confirmed as an instance in its own
  right (cited under TESTED and VERIFIED), but whether the same
  "known-noise" reflex has silently absorbed other real failures **since**
  `e6166a1c` was written is not something this audit checked, since H7 is
  explicitly still open per `d156ab78`'s "Remaining in Stage 18" list.

---

## Headline counts

- **INTENDED**: 1 founding discipline (correctness-first, market-relative
  measurement, evidence over verdict), traceable to `be8c99b5` onward.
- **IMPLEMENTED**: 236 `src/` modules; two complete, independent card rules
  (V1 live, V2 registration-pending); 15-module Evolution Lab that actually
  ran its central experiment; 1 append-only alpha registry with 92 rows.
- **TESTED**: 381 `tests/*.py` files, CI-gated on every push
  (`tests.yml:6-10`), with the suite's own reliability independently
  falsified (18-43 failure-count swing on one tree, `e6166a1c`) and left
  open.
- **VERIFIED**: 1 project-defining null (Evolab Phase 2B,
  BELOW_PLACEBO_CEILING, PBO 0.61), 92 alpha-registry rows with 42 verdicts
  and 0 survivors, and at least 2 confirmed instances of a cited number
  going stale/unreproducible before being caught (hypothesis-count
  disagreement; 14.3b).
- **PRODUCTION**: 6 scheduled/dispatchable GitHub Actions workflows; exactly
  1 deployed environment (`linehound-staging`); 0 automated path to
  `linehound-prod`; V1 card live, V2 card one un-executed registration
  commit (`T0`) away from eligibility.
- **PROPOSED**: Evolab Phase 4+ (correctly unbuilt per its own conditional),
  the in-play watcher, NFL live-window-firing, the cadence SLO, the
  production cutover itself.
- **REJECTED**: Evolab's evolutionary-loop direction, M4, SR1, the STRONG/
  LEAN/SPLIT labels, 2 deleted files (reason not yet traced).
- **UNKNOWN**: live-window dispatch diagnostic (4 steps, none run),
  F5-results failure behavior, 2 deletion reasons, prop-listing feasibility
  follow-through, current suite pass/fail state, and 2 flagged (not
  confirmed) candidates for conclusion-to-assumption drift.

Evidence cutoff: 2026-09-17, working tree and `git log --all` as read during
this session. No file other than this one was modified; no capture job or
odds-API-consuming command was run.
