# Research catalogue — every idea, classified

**Purpose.** One index of every research idea this program has raised, under one
taxonomy, so a dead idea cannot be re-proposed as new and an open lane cannot be
forgotten. Built 2026-08-31 from the documents named in each entry. Nothing here
is a new measurement: every number is quoted from a results document, and any
idea whose evidence lives only in an invalidated document is marked as such.

**Standing constraints that apply to every entry.**

- **Discovery window is 2023–24 only.** 2025 is **tuning-only, forever** — a
  candidate may be tuned there once and every 2025 number is tuning evidence
  permanently (`docs/ROADMAP.md`, Stage 4; `docs/TEST_SPLIT_STATUS.md` records
  the 2025 sub-split `2025-08-26..2025-09-28` as already burned by four looks).
- **2026-01-01 .. 2026-08-27 is SEALED.** One evaluation, ever, and only after
  Stage 5 policy freeze plus Brey's explicit go (`docs/ROADMAP.md`, Stage 6 —
  HARD GATE). No entry below may be resolved by reading it.
- **2026-08-28 onward is forward proof**, never folded back into tuning.
- **Line-shopping value is PRICE IMPROVEMENT, never EV or "edge"**
  (`docs/PLAN_TWO_TOOLS.md` Part 1 route 3, Part 3 Engine 1).
- Zero survivors is a valid result. Losers are published in full.

**The classes.**

| class | meaning |
|---|---|
| TESTED_NULL | pre-registered, run, dead — with family, stage of death, numbers |
| TESTED_FALSE_POSITIVE | looked alive, killed by the falsification battery |
| OPEN_LIVE | accumulating evidence right now |
| READY_UNTESTED | designed or namable, prerequisites already met |
| BLOCKED | named missing prerequisite |
| REJECTED_AT_RANKING | written down, never registered, and why |
| RETIRED | permanently closed route, with reason |

**Running score.** Four pre-registered families against the MLB h2h moneyline —
V1, V2, V4, V5 — **zero survivors**. See "Counting the families" at the end for
the exact denominators, which the source documents state inconsistently.

---

## TESTED_NULL

### Family V1 — single-feature baseball detectors (docs/RESULTS_STAGE2.md)

Registered as 21 detector×market hypotheses over 11 detectors
(`evidence/hypothesis_family.json`, frozen 2026-08-28). Stage 2 ran all 11
point-in-time on 4,859 games (4,395 priced), 26,932 findings, effects vs
de-vigged consensus, date-clustered throughout. **FDR (BH q=0.10) + 1pp effect
floor: ZERO of 8 clear both gates. Every interval includes zero.**

| # | idea (one line) | n | effect | clustered 95% CI | p | ROI | 2023 / 2024 |
|---|---|---|---|---|---|---|---|
| N1 | `bullpen_exposure` — back the side whose starter's innings-per-start is far from league average | 1508 | +1.65pp | −0.70..+4.04 | .18 | +2.2% | +0.72 / +2.61 |
| N2 | `bullpen_workload` — back the side whose opponent's pen threw recently | 2499 | +0.79pp | −0.81..+2.34 | .32 | +0.1% | +0.61 / +0.97 |
| N3 | `pitch_mix_mismatch` — lineup wOBA against the starter's primary pitch | 3339 | +0.60pp | −0.74..+2.07 | .40 | +0.0% | +1.15 / +0.05 |
| N4 | `platoon_mismatch` — one-handed lineup vs a starter with a split | 104 | +3.84pp | −5.79..+13.37 | .44 | +10.5% | **−15.5 / +17.5** |
| N5 | `starter_mismatch` — FIP / K-BB% gap between the starters | 2295 | −0.75pp | −2.74..+1.27 | .48 | −2.9% | +0.10 / −1.64 |
| N6 | `travel_load` — fade the side that just flew far across time zones | 604 | +0.38pp | −3.40..+4.24 | .85 | −0.4% | +4.28 / −3.60 |
| N7 | `stale_book` — bet a book quoting away from the consensus | 2949 | +0.03pp | −1.35..+1.48 | .97 | −1.0% | +0.51 / −0.69 |

- Late-market movement is ~zero for every detector (`late_move` +0.000 to
  +0.002), consistent with the nulls.
- **N4's +10.5% ROI is 104 games whose per-season effects point in OPPOSITE
  directions (−15.5 vs +17.5).** That is the definition of noise, not a
  candidate.
- **What would change any of N1–N7's class:** nothing available. A new
  pre-registered family with a different mechanism would be a new entry, not a
  reclassification of these. Re-cutting these detectors at new thresholds is
  explicitly forbidden (no rescue by threshold change, `docs/ROADMAP.md` Stage
  3B).

| # | idea | status |
|---|---|---|
| N8 | `lineup_vs_starter` — tonight's actual hitters vs this starter, batter-vs-pitcher aggregated | **Ran; no verdict.** 26 selections, below the 30-selection floor, so no effect, CI or p was computed (docs/RESULTS_STAGE2.md). Class changes only if a redesign clears the floor — and see R2 (BvP rejected at ranking on 14%/51% coverage, median 9 PA). |
| N9 | `implied_bullpen_disagreement` — the full-game minus F5 price gap *is* the market's bullpen opinion | **Registered, ran, side-less by design**: it produces context, not a side (docs/RESULTS_STAGE2.md). The one attempt to grade it directionally (n=308, p=0.90) is in `docs/RESULTS_2023_24.md`, which is INVALIDATED by the join bug — that number is not citable. The tradeable version is B3 below. |
| N10 | `park_and_weather` — run environment | **Registered, ran, side-less by design** (bears on totals, and no totals family has ever been registered — see U5). |
| N11 | `thin_matchup_history` — "7-for-18 lifetime" debunks | **Registered, ran, side-less by design** (a debunk carries no side). Retained as product value, never as a bet hypothesis. |

### Family V2 — market structure (docs/RESEARCH_V2.md → docs/RESULTS_V2.md)

Five hypotheses, 2023–24 only, zero credits, run 2026-08-29.

| # | idea | verdict and numbers |
|---|---|---|
| N12 | **M5** — de-vig method choice (proportional / additive / power / Shin) changes calibration, and the divergence locates favourite-longshot bias | **NULL.** n=4,486. Log loss 0.674168 / 0.674160 / 0.674177 / 0.674160; Brier 0.240707 / 0.240708 / 0.240719 / 0.240708 — agreement to the fifth decimal, the "best" method flips between metrics. Median between-method disagreement 0.37pp. Two keepers: proportional de-vig stands system-wide; Shin is *identical* to additive on two-way markets to 13 decimals (it only earns its keep on three-way markets, i.e. not before soccer). **Class change:** only a three-way market. |
| N13 | **M1** — consecutive price changes are negatively autocorrelated, so fading the last move pays (Management Science 2024, 3,681 MLB games) | **NULL, and the sign is wrong.** Measured within each book's own path: 62,183 consecutive change pairs across 4,087 events, lag-1 autocorrelation **+0.013** (clustered p=0.13) — weak momentum, not reversal. Trading it: fade at 1pp n=19,250 ROI **−3.5%**; fade at 2pp n=7,720 **−4.1%**; follow at 1pp **−3.3%** (post-hoc diagnostic, not pre-registered). Both directions lose about the vig. **Honest limit:** the paper had tick data, we have 4–5 snapshots/game — this is "not visible at this resolution", and the dense forward grid (L1) is the only thing that would re-open it. |

### Family V4 — exploratory interactions (docs/RESEARCH_V4_EXPLORATORY.md)

Six unit-vs-weakness interactions, registered byte-frozen at
`data/research/family_v4_exploratory.json` after the machinery validation gate
opened (docs/VALIDATION_GATE.md); battery RULES_VERSION 2.0.0; thresholds set at
the pooled p70 of |signal| from feature distributions only; 2023 screen / 2024
replication / BH-FDR q=0.10 over all six. Run 2026-08-31 02:16 UTC. **Zero
survivors.**

| # | idea | died at | numbers |
|---|---|---|---|
| N14 | `stacked_top_platoon` — top-heavy order × platoon share | 2023 screen | −0.98pp on 856 selections — wrong direction out of the gate |
| N15 | `platoon_pressure` — lineup platoon share × starter platoon gap (the classic exploitation, as a product rather than two parts) | 2023 screen | −0.75pp on 243 selections — wrong direction |
| N16 | `stacked_top_vs_pitch` — concentrated top of the order × wOBA vs the starter's primary pitch | 2023 screen | −0.85pp on 602 selections — wrong direction |
| N17 | `handed_lineup_vs_pitch` — one-handed lineup × good against the primary pitch | 2024 replication | 2023 +0.15pp → 2024 −3.55pp — sign flip |
| N18 | `stacked_top_weak_starter` — best bats concentrated × measured starter weakness | 2024 replication | 2023 +0.79pp → 2024 −0.44pp — sign flip |

(The sixth V4 spec, `pitch_lean_vulnerability`, reached the battery and is
classified as F2 under TESTED_FALSE_POSITIVE.)

**Class change for N14–N18:** none. Three of six pointed the wrong way in the
screen year and both replication attempts sign-flipped — the signature of noise.

### Family V5 — stuff decline and contact shape (docs/RESEARCH_V5_STUFF.md)

Three hypotheses on features the pitch store had only just gained (as-of-cutoff
fastball velocity vs league; career ground-ball share), both byte-level
point-in-time injection-tested before registration. Run 2026-08-31 07:54 UTC,
frozen at `data/research/family_v5_stuff.json`. **Zero survivors — all three
died at 2024 replication.**

| # | idea | 2023 screen | 2024 replication | verdict |
|---|---|---|---|---|
| N19 | `facing_soft_stuff` — back the side facing a starter whose fastball sits below league pace (velocity leads results) | +0.27pp (n=374) | +0.46pp, wrong side of the half-floor | no_replication |
| N20 | `stacked_top_vs_groundballer` — a power-concentrated lineup meeting a career ground-ball starter | +1.96pp (n=481) | **−3.39pp — sign flip** | no_replication |
| N21 | `fastball_leaning_decliner` — one-pitch lean × below-league velocity, compounding | +1.60pp (n=371) | −0.33pp — sign flip | no_replication |

N20 is the instructive one: the exact shape this family was built to find, on
481 screen selections, and the held-out season flipped its sign outright.
**Class change:** none. The published reading is that another season-level
feature family needs a mechanism the market plausibly CANNOT price.

### Resolved measurements outside the four families

| # | idea | result |
|---|---|---|
| N22 | Does a free, public-style projection beat the closing consensus? (route 4, docs/BENCHMARK_ELO.md) | **No — decisively, as pre-stated.** Pitcher-free Elo (FiveThirtyEight constants, never tuned here), 2023 burn-in, 2,234 scored 2024 games: close consensus log-loss **0.67275** / Brier 0.23999 vs Elo **0.68076** / 0.24391. Per-game differential +0.00801 (Elo worse), date-clustered p=**0.0003**. This is now the yardstick for every data-acquisition decision: an input that cannot beat this baseline adds nothing the market lacks. |
| N23 | Does the scanner's market screen do real work, and is the routed market even on the board? (Q5, docs/RESEARCH_PLAN.md, docs/OVERNIGHT_RUN.md) | **Answered descriptively, no outcomes read.** 454 candidate games 2023–24 with stored F5 prices: 220 pass (48.5%), 88 screened out as already priced (19.4%), **136 with no first-five market at all (30.0%)**, 10 unparseable. The screen rejects ~29% of what it can judge. Consequence applied: forward logging records *market unavailable* as distinct from *no play*. |
| N24 | Does the scanner's talent bar predict first-five RUN TOTALS? (Q2) | **Refuted, and the pre-registration was wrong.** 953 games: candidates n=79, mean F5 runs 4.99, 50.6% over 4.5; everything else n=874, 5.07, 50.5%. Identical. Consequence applied immediately: the scanner's market constant was renamed `first_five_totals` → `first_five`, because it screens the first-five moneyline. What the bar *may* track is who leads (37 of 61 decided, 60.7%, 18 ties) — a direction to test, not a result. |

---

## TESTED_FALSE_POSITIVE

| # | idea | the sequence |
|---|---|---|
| F1 | **M3 — cross-book dispersion**: where a book sits far off the pack, bet against it at its own price (docs/RESULTS_V2.md) | **THE CANONICAL CASE.** Headline at a 2pp deviation threshold: 249 selections / 223 events / 162 dates, hit rate 60.6% vs 52.2% implied, **+8.49pp, clustered p=0.0063, CI [+2.34, +14.28], ROI +18.1%**. Killed by the pre-committed battery: (1) **dose-response inverted** — the band immediately below the threshold (0.015–0.020, n=940) is **−1.56pp**, the effect spikes in one narrow slice and fades; (2) **it is one book** — FanDuel alone +15.49pp (n=74), BetMGM **−9.44pp** (n=27), and excluding FanDuel drops it to **+5.53pp at p=0.16**; (3) it does not replicate across seasons (2023 +6.14pp p=0.13 vs 2024 +11.72pp); (4) one bad price makes six correlated selections through the leave-one-out consensus; (5) it is a 0.4% tail — 249 of 59,297 observations. The pre-registration had recorded a LOW prior in advance, because V1's `stale_book` (N7) came back +0.03pp at p=0.97. **Class change:** any revival must cap selections per event and clear a dose gradient; it is pinned as a regression test (`tests/test_validation_m3.py`), and it is the case that exposed and then hardened the battery (docs/VALIDATION_GATE.md, check 4: the battery originally PASSED M3; two fatal rules were amended as general rules and frozen at RULES_VERSION 2.0.0). |
| F2 | **`pitch_lean_vulnerability`** (V4 #1) — a starter who leans on one pitch, against a lineup that hits that pitch | The only V4 spec to replicate and the only one to reach the battery: 2023 +0.91pp (n=553), pooled **+1.06pp over 1,090 selections, p=0.45** — and **fatal on team concentration, book concentration AND extreme-date removal**. What little effect exists is carried by a handful of clubs, books and dates. **Class change:** none without a mechanism that survives concentration. |

**Near-cases, cross-referenced, not re-entered:** N1 `bullpen_exposure` was
believed to be a +4.08pp candidate before the join bug was found; on correct
joins it is +1.65pp at p=.18, and the prior signal was substantially the bug
(docs/RESULTS_STAGE2.md; the +4.08 package is INVALIDATED — see T4). N20
`stacked_top_vs_groundballer` is the screen-then-flip version of the same
lesson.

---

## OPEN_LIVE

| # | idea | evidence state | what would change its class |
|---|---|---|---|
| L1 | **Family V3 — information timing / market microstructure**: when genuinely new information enters, how fast do books react, which move first, and does an observable stale-price window exist? (docs/RESEARCH_V3_TIMING.md) | **FROZEN 2026-08-31, forward-only, accumulating.** Family denominator **5** admitted classes (raised from 4 on 2026-09-02, docs/RESEARCH_V3_UMPIRE_CLASS.md's `umpire_crew_revealed` amendment — the denominator is monotone non-decreasing, never edited down): `lineup_posted`, `starter_scratch`, `hitter_scratch`, `transaction_first_seen` (named `il_roster_move` in the freeze record), `umpire_crew_revealed`, all grade B. **First class read, 2026-09-02, then CORRECTED the same day after adversarial review (docs/RESEARCH_V3_TIMING.md ADDENDUM 2):** the original read scored every transaction id first seen, not the frozen `il_roster_move` definition ("IL placement/activation, trade, recall affecting the game") — a class mismatch that folded Triple-A options and releases in alongside the intended moves. Corrected: `game_relevant()` restates the frozen definition as a filter over the transaction feed's own move-type vocabulary, decided before any reaction time was read. On this re-pull of the (non-frozen, gitignored) game-join table, the properly-scoped class holds **19 of its 30-event floor — below floor, no primary result read.** The unfiltered/all-transactions reading (42 measurable events, disclosed as secondary/exploratory, never promoted) is consistent with slow, incomplete repricing — km_median(diff)=209.82 min, bootstrap 95% CI [180.67, not reached], exact cluster-level sign test 15/15 clusters favoring H1 (p≈3.05e-5) — but carried almost entirely by 3 of 16 clusters and one recurring matchup (the concentration check RESEARCH_V3_TIMING.md always required and never ran before this correction). No promotion on either reading. | A class hitting 30 admitted events produces its first read; the properly-scoped `il_roster_move` needs 11 more game-relevant events. **V3 claims no edge by construction**: measurable latency is NECESSARY, never sufficient — executability, limits and price-vs-fair stay separate questions, and any "bet the stale price" claim would be its own registered family with the full funnel. A null (or a class stuck below its own floor) is a publishable result, with the resolution and cost that would be needed. |
| L2 | **Softer markets — first-five (F5) closes** (docs/COLLECTION_POLICY.md, docs/ROADMAP.md ready queue #3) | Accumulating forward at zero design risk: the dense T-25 close pass adds `h2h_1st_5_innings` on approaching games at ~1 credit/event/moment (5 books forward, measured by the 24-credit probe). No F5 family is registered; the next step is a coverage/book review over ~2 weeks of closes. | Enough closes to measure coverage → design the first F5 family (U1). Historical F5 depth remains a spend gate (B3). |
| L3 | **Forward proof ledger (Stage 7)** — graded forward selections, true CLV primary | LIVE since 2026-08-28; daily loop records and settles. Pre-registered criteria in docs/VALIDATION_CRITERIA.md: ≥300 graded picks as a FLOOR, ≥55% beating the close, mean CLV ≥ +1.5%; below 300 no verdict is drawn whatever the numbers say. Known defects logged 2026-08-31: settlements carried `closing=null` (no CLV from the ledger until threaded), and 32 of 58 window games had zero observations in their final 3 pre-pitch hours. | Reaching the floors with the defects fixed. The five price concepts stay separate — recommendation price / best available / consensus at recommendation / `late_move` / true close — and `late_move` is **never** called CLV. |
| L4 | **The mismatch scanner's own hypothesis** (Q9/Q10, docs/MISMATCH_SCANNER.md, docs/RESEARCH_PLAN.md) — does a flagged side beat the price it was flagged at, and does it beat the demoted model? | Forward-only by construction; flag log started 2026-08-27. Needs ~200 decided flags at roughly one a day, i.e. most of a season. First decided flag was 0-1 (insufficient sample, as expected). | 200+ decided flags. The scanner deliberately scores a different quantity from EV (it suppresses the −115 ace duel an EV ranker would rank first), so its result does not transfer to any other entry. |
| L5 | **Price improvement / line shopping** (docs/PLAN_TWO_TOOLS.md route 3, Ranker Engine 1) | Shipped and wired into the Analyzer (B1 library). **This is NOT an edge and NOT EV.** It is a better execution price on a bet whose worth is a separate, unanswered question, and it counts only if the quoted price was actually executable. Engine 2 (predicted value) is empty, so the Ranker ranks nothing — enforced by a test. | Nothing about price improvement can ever promote it to an edge. It becomes EV only if a *separate* registered hypothesis supplies a defensible fair price. |

---

## READY_UNTESTED

Prerequisites already met; no registration written.

| # | idea | why it is ready | source |
|---|---|---|---|
| U1 | **First F5 research family** — F5 moneyline as a bet target, designed from forward-captured closes | F5 close capture is running (L2) and priced (1 credit/event/moment, 5 books); the F5 settlement store exists (`src/research/f5_store.py`: 181 dates, 2,512 games, 0 odds credits). | docs/ROADMAP.md PATH B, ready queue #3 |
| U2 | **Alternate spreads / totals family** | Probe-established: 7 books, 130–160 outcome rows per event at **1 credit** — the best information-per-credit measured on the board. Collection is deliberately switched OFF until a registered hypothesis needs it ("option value comes from knowing the cost, not from hoarding rows"). | docs/COLLECTION_POLICY.md |
| U3 | **Pitcher-strikeout prop family** | Probe: 3–4 books, listing-dependent, prop history from ~May 2023. Thin, but priced and namable. | docs/COLLECTION_POLICY.md; docs/ROADMAP.md backlog |
| U4 | **Third-time-through-order penalty, measured rather than approximated** | The 2.74M-pitch store is rebuilt point-in-time and now carries `bb_type` (2,737,968 rows, 0 failed windows). This was the one priority detector still approximated. | docs/OVERNIGHT_RUN.md; docs/ALPHA_ROADMAP.md priority group #5 |
| U5 | **A totals family (full-game and F5)** — never evaluated as a bet target in any family | `park_and_weather` (N10) and the F5-totals routing (N24) both exist but no totals hypothesis has ever been registered. Weather is collected and unused; park factors exist. | docs/VALIDATION_PACKAGE_1.md ("F5/totals markets, never yet evaluated as bet targets") |
| U6 | **Q4 — how early and how far do games diverge from their priors?** | Answerable entirely on historical linescores already on disk; free. | docs/RESEARCH_PLAN.md Tier 1 |
| U7 | **Q3 — threshold sensitivity measured against FIRE RATE, never results** | Descriptive, free, and explicitly not tuning provided the sensitivity is measured against fire rate. Currently the scanner fires on 10.2% of games (~1.4/day) before the market screen. | docs/RESEARCH_PLAN.md Tier 1 |
| U8 | **V3 falsification battery pass** | Battery is frozen and validated (RULES_VERSION 2.0.0, generality matrix, adjudicated gate). Applies the moment any V3 class produces a selection-shaped claim. | docs/ROADMAP.md backlog; docs/RESEARCH_V3_TIMING.md |
| U9 | **Park orientations** (`orientation_deg`, all 30 currently `None`) | A bounded one-time task, ~1 hour of satellite imagery, with the fill procedure written and a test that fails deliberately when values appear. Unblocks the wind half of B6. | docs/PARK_ORIENTATION.md |

---

## BLOCKED

Each with its named missing prerequisite.

| # | idea | missing prerequisite |
|---|---|---|
| B1 | **Reverse line movement / any contrarian family** | **Public betting percentages.** No source we can access provides them, and inferring public sentiment from price movement invents the data. Earlier notes listing RLM as buildable were retracted as incoherent. (docs/PLAN_TWO_TOOLS.md route 4; docs/ALPHA_ROADMAP.md; docs/RESEARCH_V2.md) |
| B2 | **M2 — weekend day-game staleness**: is the T−90 price sharper than the first-pitch price? (V2 hypothesis, ran, INCONCLUSIVE) | **A dense snapshot grid.** Loose test (n=2,568) had the late price winning in all four cells, but that is not the paper's test — in the weekend-day cell our "early" quote sat a median **954 minutes** out. The strict test (early 90–240 min, late <60 min) qualified only **197 games in two seasons, three of them weekend afternoons**. The test cannot be run on historical data. Forward 15-minute sampling inside the last three hours is free and is now running; the class changes when enough weekend-afternoon cells accumulate. |
| B3 | **M4 — F5 vs full-game bullpen gap**: is the market's own implied bullpen opinion internally consistent? (V2 hypothesis, ran, UNDERPOWERED) | **Historical F5 backfill, behind a spend gate.** Sample: 308 games with both prices, **270 decided, 38 ties** (14% of F5 moneylines end level). F5 price is well calibrated: actual home 54.4% vs implied 53.2%, **+1.25pp, p=0.67, CI [−4.56, +7.12]**. Mean implied gap across all games +0.001 — no systematic bias; no bucket significant. This is the only hypothesis that died of **sample size rather than evidence** — "we cannot tell", not "the market is right". A fuller 2023–24 F5 backfill would take it to a few thousand games. It is a HARD APPROVAL GATE (large historical purchase) and stands against the rule that credits go to candidates that survive free robustness. **Brey's call; nothing gets spent without it.** Also recorded: at the halfway point (217 games) the buckets showed a clean monotone gradient (+8.3, +7.2, −5.3, −0.8, −0.6) that **dissolved** with the full sample — reading the partial run as encouraging would have been a mistake. |
| B4 | **Targeted historical lead/lag study** (the paid version of V3) | **Spend gate + a pre-registration naming the window.** The historical archive serves a 5-minute grid with 12 books at 10 credits/event/snapshot; ~100 event-windows × 12 snapshots ≈ **12,000 credits**. No historical purchase happens without a registered hypothesis and Brey's sign-off. (docs/COLLECTION_POLICY.md) |
| B5 | **V3 historical replay, 2023–24** | **Timestamp quality.** Every event class is grade C/D historically: transactions are day-only, stored lineups date-only, no probables history, and the historical odds store samples 3×/day so any bracket is 6–15 hours wide. A transaction DATE is never treated as a TIME. V3 is a forward study, entirely. |
| B6 | **Wind vector / GB-FB × park × wind; roof-state effects** | **Park orientation (U9) and a roof-state feed.** `orientation_deg` is `None` for all 30 parks by design — a bearing wrong by 180° inverts a real effect confidently and silently, so `classify_wind` returns `None` and `wind_effect` reports `applicable: False`. Roof state has no feed at all in any source the project uses. |
| B7 | **V3 event class `reliever_status`** (closer / high-leverage arm ruled in or out) | **An announcement source with A/B timestamps.** None exists in the repo; post-game bullpen usage supports only day-level grade-C inference. EXCLUDED at freeze, not downgraded. |
| B8 | **V3 event class `weather_roof`** | **Provenance-backed timestamps.** Weather is a single unstamped reading; roof has no feed. EXCLUDED at freeze. |
| B9 | **Hitter-side velocity-band performance, and hitter contact/power profiles** | **Not in the matchup matrix point-in-time.** Named as V6 candidates in both V4 and V5 and deliberately not smuggled into either family. Blocked until the feature is built and passes the same byte-level PIT injection test the current features passed. |
| B10 | **Umpire zone size / called-strike rate / run-environment tendency** | **Source not verified.** Listed in the detector catalogue and in the unfinished-research list with "source not yet verified". |
| B11 | **Q6/Q7/Q8 — is the starter-FIP gradient already in the F5 line; where does the F5 line sit relative to full game; is 0.65 the right screen?** | **Posted first-five totals, per game, historically.** Q7 has two live games' worth of anecdote (F5 came in shorter than full game). Q8 additionally asks whether one screen constant should apply to a conditional F5 price and an unconditional full-game one — flagged as a known open question, not a validated choice. |
| B12 | **KBO / NPB and all multi-sport expansion** | **Gated: a validated forward MLB result + Brey's go + probably a fresh odds-subscription month** (docs/ROADMAP.md Stage 11, explicitly deferred: "stay on MLB"). |
| B13 | **Sealed-2026 one-shot confirmation** | **Stage 5 decision-policy freeze signed off, then Brey's explicit go.** One evaluation, ever; the provisional label is permanent; reported honestly either way. There is currently **no candidate to confirm**, so the gate is moot as well as shut. |
| B14 | **Q11 — does live in-game divergence carry information the pre-game priors did not?** | **Phase 4 live infrastructure, then a season of it.** |

---

## REJECTED_AT_RANKING

Written down, ranked on feature-side data only, never registered. No outcome
column was read for any of these decisions.

| # | idea | why rejected |
|---|---|---|
| R1 | Both-direction variants of every V4 and V5 interaction | The mechanism fixes the direction; registering "or the opposite" doubles the family with hypotheses nobody believes — pure denominator inflation. |
| R2 | Anything built on `lineup_vs_starter_history` (batter-vs-pitcher wOBA) | Both-sides coverage 14% / 51% by season, **median history 9 PA** — structurally underpowered, and 18-at-bat storylines are the exact noise the Analyzer exists to debunk. |
| R3 | Starter velocity profile × hitter velocity-band performance | The hitter-side band feature is not in the matrix point-in-time. (The starter half was later built as `starter_velocity_gap` and became V5 #1, N19 — which died.) |
| R4 | Batted-ball profile × lineup contact/power × park | Feature not in the matrix point-in-time. |
| R5 | Expected starter innings × bullpen quality / rest | Feature not in the matrix point-in-time. |
| R6 | Bullpen handedness × late-inning hitters | Feature not in the matrix point-in-time. |
| R7 | Top-of-order concentration × F5 market | **F5 odds coverage 9.3%** in the matrix — no power. |
| R8 | Lineup-scratch severity × market movement | Feature not in the matrix point-in-time; the timing version of this idea lives in V3 (L1) instead. |
| R9 | Velocity × platoon; ground-ball × handedness; every other pairing of V5's new features with V4's | **No stated mechanism survived being written down** — and V4 had just demonstrated what mechanism-free products earn. |

R3–R8 are the standing V5/V6 shortlist and are gated on the same PIT validation
the registered features passed. R2 also explains N8's fate.

---

## RETIRED

Permanently closed routes, with reason. Re-proposing any of these requires
naming what changed.

| # | route | reason it is closed |
|---|---|---|
| T1 | **More detectors of the V1 kind** ("twenty more 'this team travelled far' ideas") | Closed explicitly, on both external and internal evidence: 1,547 simple MLB moneyline strategies tested in the literature, 0.45% profitable at the 1% level — the rate chance alone produces — and four of our own families agree. (docs/PLAN_TWO_TOOLS.md, docs/RESEARCH_V2.md) |
| T2 | **Season-level feature families in general** | Standing bar raised: another season-level feature family needs a mechanism the market plausibly **CANNOT** price, not merely one it might not. New features alone are not new edge. (docs/RESEARCH_V5_STUFF.md) |
| T3 | **"Steam" detection** | Three snapshots a day cannot detect synchronised book movement. Renamed to what it actually is — coarse directional movement between snapshots. |
| T4 | **Every number in `docs/RESULTS_2023_24.md` and `docs/VALIDATION_PACKAGE_1.md`** | INVALIDATED 2026-08-28. The historical price join assigned games the NEXT game's odds in consecutive-day series (55% of matched 2023 selections; 1,966 "recommendation-time" prices captured after the graded game had finished), silently dropped every Diamondbacks game, and fed the FDR gate an unclustered p. The positives, the nulls and the `bullpen_exposure` falsification are all uncitable. Kept only as a record of what was believed. Superseded by docs/RESULTS_STAGE2.md. |
| T5 | **Downloading a free external public projection for a 2023–24 benchmark** | No source is honestly replayable: FanGraphs never archives game odds, FiveThirtyEight's Elo died mid-2023 with its data files gone, retro win probabilities (Savant, B-R) are not pre-game forecasts, free odds archives stop at 2021, tout "past picks" are self-attested. Replaced by the reconstructed point-in-time Elo (N22). |
| T6 | **Q1 in its original form** — combined starter FIP predicts first-five runs | Measured (953 games; correlation **+0.075**; over-4.5 rate 45.7% → 54.5% across FIP quartiles), and then closed as unanswerable in that form: it compares every game against a fixed 4.5 line, so **it cannot distinguish "starters predict runs" from "starters predict the line"**. The settling version needs posted F5 totals (B11). |
| T7 | **Re-evaluating the 2025 test split** | Burned by four evaluations; every number from it is optimistically biased by an unknown and unknowable amount. 2025 is tuning-only regardless. (docs/TEST_SPLIT_STATUS.md) |
| T8 | **Tuning thresholds against settled flags / rescuing a dead hypothesis by threshold change** | A threshold fitted to the results it is tested on stops being a hypothesis and becomes a description of them. No rescue by threshold change is a Stage 3B rule. |
| T9 | **Staking and bankroll-growth research** | Both presuppose an edge that has not been demonstrated, and modelling returns on an unproven edge is the most reliable way to start believing in one. |
| T10 | **Real-money betting or any bet-placement capability** | Never. Permanent hard rule. |

---

## Lessons the catalogue proves

**1. The screen-then-flip shape is what a dead idea looks like here.** N20
`stacked_top_vs_groundballer` posted **+1.96pp on 481 screen selections** and
came back **−3.39pp** in the held-out season. N17 went +0.15 → −3.55; N18 +0.79
→ −0.44; N21 +1.60 → −0.33. N4 `platoon_mismatch` did the same thing across
seasons inside one detector (−15.5 / +17.5 on 104 games) and would have looked
like a +10.5% ROI candidate to anyone reading the pooled row. A screen-year
number in the right direction carries essentially no information in this
program; the replication season is where the family is decided, and a sign flip
is death by pre-registered rule rather than by judgement.

**2. The market absorbs season-level features — all of them, so far.** Four
families, every one built on features that describe a season: platoon splits,
pitch mix, bullpen workload, travel, starter FIP (V1); the same features
multiplied together (V4); and genuinely new store-derived measurements —
as-of-cutoff fastball velocity and career ground-ball share (V5). Zero
survivors, and `late_move` is ~zero for every V1 detector, meaning the market
does not drift toward these ideas either. The close also beats a clean
public-grade Elo by 0.8 log-loss points per game at p=0.0003 (N22), and the
external base rate says 0.45% of 1,547 tested MLB moneyline strategies clear the
1% level — chance. The conclusion is not "we measured badly"; it is that the
h2h close already carries whatever the pitch store measures.

**3. Timing and microstructure are the live lane, and only because they ask a
different question.** V3 (L1) does not require being smarter than the market,
only earlier than its slowest visible part — and it makes **no edge claim**:
measurable latency is a necessary condition, never sufficient. The other live
lane is market depth rather than market intelligence: F5 and other softer
markets (L2, U1–U3), where fewer bettors and thinner books are the mechanism.
Both are forward-only, both are free or nearly free to collect, and both were
unreachable until the capture infrastructure shipped. Notably M1 and M2 (N13,
B2) both died on **sampling resolution rather than on evidence** — which is
exactly the deficiency the dense forward grid removes.

**4. The battery is load-bearing, and it had to be fixed before it was trusted.**
M3 (F1) would have been promoted on its baseline row: +8.49pp, p=0.0063, ROI
+18.1%. The pre-committed falsification battery killed it — and then the
validation gate found that the *automated* battery **passed** M3, exactly the
case it existed to kill. Two fatal rules were amended as general skeptical rules
(no M3-specific identifier, source-checked), validated against a six-case
generality matrix and a 15-comparison old-vs-new shadow run in which only M3's
verdict changed, adjudicated independently, and frozen at RULES_VERSION 2.0.0
with a content fingerprint in every verdict. F2 then died on the same
concentration rules. An 18% ROI in a liquid market is a reason for suspicion,
not celebration.

**5. Price improvement is not an edge, and the separation is structural.** The
Ranker's Engine 1 (price improvement) ships; Engine 2 (predicted value) is empty
because nothing has been proven, so the Ranker ranks nothing — enforced by a
test rather than by discipline. `late_move` is never called CLV; best-available
price is never called EV. Every entry above that touches line shopping is
classified L5 for that reason.

**6. "We cannot tell" is a distinct verdict and it is worth protecting.** N8
(26 selections), B2 (3 qualifying weekend afternoons), B3 (270 decided games)
all died of power or resolution, not evidence, and each is recorded as such
rather than as a null. B3 also records a monotone gradient that dissolved as
data arrived — the mistake that is easy to make and hard to notice.

---

## Counting the families — a documented inconsistency

The source documents disagree on the denominator, so the catalogue states it
explicitly rather than repeating a number.

- **V1's registered family is 21 detector×market hypotheses over 11 detectors**
  (`evidence/hypothesis_family.json`, `count: 21`). Stage 2 evaluated all 11
  detectors; **8** produced side-bearing selections (7 with statistics plus
  `lineup_vs_starter` below the floor), and 3 are side-less by design.
- `docs/RESULTS_V2.md` says "two families, thirteen hypotheses" — that is V1's
  8 side-bearing plus V2's 5.
- `docs/RESEARCH_V4_EXPLORATORY.md` then writes "V1: 13, V2: 5, V4: 6 — 24", and
  `docs/RESEARCH_V5_STUFF.md` writes "twenty-seven pre-registered hypotheses",
  i.e. 13+5+6+3. **The 13 in those roll-ups is V1+V2, so V2 is counted twice.**
- Consistent alternatives: **25** at detector/spec level (11+5+6+3) or **35** at
  registered-hypothesis level (21+5+6+3).
- `docs/PLAN_TWO_TOOLS.md` is internally inconsistent on the same point
  ("eleven baseball ideas" plus five market ideas, summarised as "thirteen
  ideas").

None of this changes any verdict — every family's FDR ran against its own frozen
denominator (V1: 21 registered / 8 corrected; V2: 5; V4: 6; V5: 3) — but the
public "27" should not be repeated without this note.
