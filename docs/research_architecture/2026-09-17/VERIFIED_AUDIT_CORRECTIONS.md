# Verified audit corrections

2026-09-17. Every consequential claim from `docs/audits/2026-09-17_algorithm_reopen/`
re-checked against source before any architecture was designed on it.

**Why this document leads.** The audit produced several findings that did not
survive verification — and it produced them *after* being explicitly built to
catch exactly that failure. Nine claims were checked. **Five held, four did
not.** The four that failed are listed first, because an architecture built on
them would have been built wrong.

Method: DOCUMENT CLAIM → SOURCE FILE → CODE → DATA → GIT. Source wins.

---

## FAILED VERIFICATION

### F1 — "No independent model probability exists anywhere in this project"

**Claim:** `src/analysis/families.py:22`, carried into the contradiction ledger
as C3 (unresolved), and into the phase-2 brief as Problem C — the foundational
worry that V2's value comparison might be circular.

**Verdict: THE CLAIM IS FALSE.** An independent model probability exists.

`run_means()` (`strength.py:299-363`) reads exactly: `runs_scored_pg`,
`runs_allowed_pg`, `games_played`, `sp_fip`, `sp_innings`, `sp_ip_per_start`,
`bullpen_rate`, `park_factor`, and scalar `league_rpg`. `market_probabilities()`
(`:536-607`) takes only two Poisson means plus shape parameters. The module is
declared `stdlib only, no I/O -- every input arrives as an argument`
(`strength.py:90`). `src/pipeline/features.py` contains no price code at all.

**The distinction that resolves it:** the Platt calibration IS fit on outcomes
(`fit_card_calibration.py:167`, `pairs.append((line["p_home"], int(row["home_won"])))`).
Fitting on *outcomes* is not fitting on *prices*. A settled result is not a
price. Conflating the two is what made this look like circularity.

`families.py:22` over-generalises a statement that is TRUE of the price-verdict
surfaces — `priceverdict.py` (which honestly declares `NO INDEPENDENT MODEL YET`
at `:76`) and `opportunities.py` — into a false claim about the whole project.

**Consequence:** V2's `score = p − (1−p)/(d−1)` is a legitimate comparison.
Problem C is resolved rather than architected around. The lane structure in
`PROBABILITY_ARCHITECTURE.md` still stands, but as discipline going forward,
not as a repair.

### F2 — "V6 has collected nothing for six days; schedule the probe and backfill"

**Claim:** `URGENT_V6_NOT_ACCUMULATING.md`, written by me, called the most
important operational finding of the audit.

**Verdict: THE PREMISE IS INVERTED.** Evidence accumulated normally throughout.

The probe maintains no counter — it recomputes from
`data/processed/information_events.jsonl`, which holds **868 `lineup_posted`
events spanning 2026-08-31 → 2026-09-16, 563 of them after the registration
instant**. The registry's `forward_window: {'n': 0}` is a field written once at
registration and never updated. Nothing was lost; only the READ had not happened.

Run read-only, independently, twice:

```
160 usable postings after the registration instant; floor 150
  n=158   hit 0.481   family of 47   alpha 0.00106   [0.326, 0.592]
VERDICT: UNDETERMINED
```

**The forward floor was already cleared and the signal did not replicate.**
Discovery 0.584 (n=149) → pooled 0.526 (n=323) → forward-only 0.481 (n=158).

The correct action was never "schedule and backfill to rescue it". It was
"run it". Full treatment in
`docs/audits/2026-09-17_algorithm_reopen/V6_FORWARD_READ_2026-09-17.md`.

**A measurement limitation neither the audit nor I had named, found in
verification:** there is no posting time anywhere in this system. `ev["at"]`
comes from `observed_utc` (`probe_event_direction.py:115`), which
`src/board/events.py:225-240` derives from `lineups_watch.jsonl`'s
`fetched_utc` — the moment the poller first *saw* a lineup, not when it was
published. `src/board/record.py:158-171` defines `happened_utc` and `known_at`
as distinct fields; the rows actually written carry only `observed_utc`. So V6's
120-minute window is anchored to OUR DISCOVERY LATENCY, not to publication.
That does not smuggle in look-ahead — every timestamp is a genuine
first-sighting produced as the poller ran — but it means the hypothesis as
tested is partly about our own polling cadence. **This is a first-order design
constraint for any information-timing research** and it belongs in the
constitution.

### F3 — BALLDONTLIE: "959 assets, 505 mlb, feeding nothing"

**Claim:** mine, from counting GitHub release asset names by prefix, offered as
a correction to an earlier wrong finding.

**Verdict: THE USAGE CLAIM HOLDS; MY COUNTS DO NOT.**

`MANIFEST.json` records **461 entries, not 959**: mlb 7 files / 14,638 rows;
nba 7 / 6,482; nfl 364 / 8,831; **nhl 7 files / 0 rows — every NHL job returned
http_status 400**; tennis 76 / 85,698. Only the nfl figure matches what I said.

**And the MLB holding is much thinner than "a multi-sport dataset feeding
nothing" implied.** The harvester ASKED for `/mlb/v1/stats`, `season_stats`,
`teams/season_stats`, `standings`, `player_injuries`
(`balldontlie_harvest.py:411-549`). **Not one of those endpoints appears in the
manifest.** MLB yielded game-level schedule/score rows for 2022-2026 and
nothing else — `mlb_odds` and `mlb_odds_opening` both 0 rows, http_status 400.

Those game rows duplicate what `data/processed/boxscores_*.jsonl` and
`data/historical/mlb_results.csv` already hold. **For MLB the harvest enables
no hypothesis the repo does not already have.** Tennis is the one genuinely
rich holding — and tennis was skipped on 2026-09-17.

The usage half stands: `grep -rln balldontlie src/` returns three provider
modules and nothing in analysis, model, engine or pipeline, and
`src/providers/balldontlie.py` is a bare HTTP client with no schema or domain
model at all.

### F4 — "~27 expected false survivors per month"

**Claim:** `STRATEGY_LAB_REFUTATION_2026-09-15.md:29`, repeated in the belief
map and by me in a briefing.

**Verdict: THE STRUCTURE IS REAL; THE NUMBER IS NOT SUPPORTED.** It extrapolates
from a hypothetical cadence of one sweep/day × 3 sports × 3 markets ≈ 270
sweeps/month. The actual registry holds 92 rows over a 20-day span, of which 41
of 50 registrations came from a one-time migration backfill — leaving **9
organic registrations in 14 days**. The figure is dropped and not carried into
the budget design, per the phase-2 brief's explicit instruction.

---

## HELD UNDER VERIFICATION

### H1 — Search effort does not accumulate. **CONFIRMED, with the settling lines.**

- `total_searched()` (`alpha_registry.py:393-449`) is a pure counter with no
  arithmetic beyond `+= 1`. **Called by nothing in `src/`** — only by a report
  script and tests.
- `scorecard.py:750-753` defaults `total_searched_at_verdict` to `raw_tests`,
  and `raw_tests = len(family)` (`:739`) — the size of the sweep currently
  running, which by construction cannot accumulate.
- `gates.py:327` — `if not effective_tests_reported:` — G5 is a boolean that a
  number was printed. `total_searched` does not appear in `gates.py` at all.
- `fitness.py:263-267` — promotion reads `multiplicity_charge >= 0.0`, true for
  a charge of exactly zero, despite a comment above it claiming it "must be
  paid for to count".
- **Holm: zero hits repo-wide.** The V2 registration's Holm budget across six
  comparisons exists only in prose, verified by `scratchpad/variants/budget.py`,
  which is not in the tree.
- `ALPHA_REGISTRY_DESIGN.md:10-13` says accumulation is absent **by design**.

Within-family BH-FDR IS genuinely enforced with real arithmetic
(`family.py:137-181`, `funnel.py:662-679`). The hole is across families and
across time.

### H2 — Park orientation is missing. **CONFIRMED, with a correction to the framing.**

0 of 30 parks carry `orientation_deg`; the module says so itself
(`parks.py:8`). But the audit's "the code never fires" is wrong: `wind_effect()`
runs on **every slate row** and returns `{"applicable": False, "reason":
"orientation for … is not verified"}` (`parks.py:251-254`), which
`slate.py:168-171` carries through as an unconditional blank.

The input side is complete: `weather_forecast.jsonl` holds 9,481 rows with
`wind_from_deg` non-null on **9,481 of 9,481 (100%)**. Thirty bearings stand
between a fully-captured input and a live feature.

### H3 — Statcast never reaches the published probability. **CONFIRMED, and worse.**

1,432,440 rows across 94 windows, 18 of 119 feed columns kept
(`statcast_pitches.py:86-95`). Two terminating branches: display copy via
`matchup.py` → `briefing` → the matchup page, and research-only via
`engine/features.py`, whose `build_features` has **zero consumers outside
`src/engine/`**. The card's probability runs a separate, shorter chain:
boxscores → `runs_scored_pg`/`sp_fip` → two Poisson means → Platt.

**Worse than stated: the store ends 2024-09-30.** Nothing for 2025 or 2026. So
pitch data cannot inform a 2026 card even in the display branch —
`matchup.py:466-470` is the path that renders "no pitch-level data is available
for this season" to the reader.

### H4 — Phase 2A's scope. **CONFIRMED.**

Features accumulated only to the first day of the game's own month
(`matrix._cutoff_for`) — up to ~30 days stale, tested against the closing line.
Its own §9.5 names freshness "the single most obvious limitation and the most
obvious follow-up," untested. Phase 2B reused **the same 18 features**, so the
two nulls share one representation rather than being independent.

### H5 — Only 1 of 92 registry rows is a prop. **CONFIRMED.**

---

## NEW — found during verification, not in the audit

### N1 — Leave-one-book-out violation, structural

`prices.py:146-181`. `priced` is built from all quotes; the consensus averages
their de-vigged fairs (`:152-154`); `best_decimal` is then selected by scanning
**that same list** (`:160-166`); and `improvement_points = consensus −
implied_best` (`:181`).

**The best book is a member of the consensus it is being measured against.**
With `MIN_BOOKS = 6` an outlier contributes ~1/n of the benchmark it is scored
against, shrinking measured improvement toward zero. Conservative in direction,
but biased, and it propagates into `opportunities.py:312-337` and into
`priceverdict.value_points` wherever `best_price` is passed as `american_price`
— which `opportunities.py:317-318` does exactly.

Never previously noticed. Fix belongs with the P_EXECUTION lane.

---

## What this changes about the phase

1. **Problem C is resolved, not architected around** (F1).
2. **V6 is answered, not scheduled** (F2). The forward read exists and is
   negative. What remains is recording it and deciding the row.
3. **BALLDONTLIE is near-worthless for MLB** (F3). The activation map should say
   so rather than hunt for a use.
4. **No inherited numbers enter the budget design** (F4).
5. **Information-timing research must account for polling latency**, because the
   system has no publication timestamps at all (F2's sub-finding).
6. **Park geometry is the cheapest live unlock in the project** (H2): ~30
   numbers against a 100%-filled input.
