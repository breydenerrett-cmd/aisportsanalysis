# Strategy Lab — technical appendix (merged draft of 2026-09-14)

**Read [STRATEGY_LAB_PLAN.md](STRATEGY_LAB_PLAN.md) first; it is the plan of
record.** This file is the merged working draft kept for its file-level
reuse map. The statistical review in
[STRATEGY_LAB_REFUTATION_2026-09-15.md](STRATEGY_LAB_REFUTATION_2026-09-15.md)
found and the plan of record corrects the following in this draft: the
dedup-ratio multiplicity arithmetic (dropped), the "chance produces ~0.01
p-values" sentence (wrong; BH at q=0.10 lets about 1 in 10 null sweeps emit a
survivor, so the sweep count is now budgeted), the borrowed base rate (the
null is n x alpha), NFL backtest power and price resilience (NFL is
forward-only this cycle), four un-ranked ROI horizons (one headline window
per sport), the wrapped stationary bootstrap for bankroll paths (real
contiguous forward paths instead), stratified weighting (unweighted
headline), censored busts (carried at minus 100 percent), the stake-fraction
narrative (shown at three fractions as a parameter), fatigue and injury
point-in-time leaks, the in-play suspension problem, Phase 0 outcome
isolation, and the dashboard's language gate.

Merges the three 2026-09-14 drafts (rigour / speed / owner-value) into one plan. Where they disagreed, the choice and reason are stated inline. Nothing here relaxes pre-registration, published losers, point-in-time correctness, or "no promotion without the full gate."

## Reuse map (sport-agnostic core, unchanged)

`src/evolab/replay.py` (point-in-time replay), `feed.py` (outcome isolation), `placebo.py` (P1/P2/P3/P5/P6 nulls), `sweep.py` + `src/model/discovery.py` (bitset enumeration, PBO/CSCV), `src/research/funnel.py` (mechanism-frozen registry), `src/accounts/paper.py` + `src/core/staking.py` (bankroll/flat staking), `src/engine/slate.py` + `settle_slate.py`, `src/factory/{fitness,gates,scorecard}.py`, `src/research/battery.py`, `src/research/alpha_registry.py`. Every sport runs the same Phase 0 → register mechanisms → enumerate → placebo ceiling → publish-the-verdict sequence MLB already ran (EVOLAB_DESIGN.md §15). No sport skips Phase 0.

| Add | NFL | Tennis |
|---|---|---|
| Results feed | `load_nfl_results()` in `settle_slate.py`, nflverse schedule join | `load_tennis_results()`; implement `ResultsFeed` in `tennis_results.py` (today a `NoFeed` stub), wired to Goalserve |
| Gamekey | `sport="nfl"` team_key_fn in `gamekey.py` | `sport="tennis"`, player_a/player_b identity, no team key |
| Features | `src/research/matrix_nfl.py` (new) — pass/rush splits, injuries, bye weeks, v0 EPA model as signal source | `src/research/matrix_tennis.py` (new) — surface, H2H, fatigue, ranking-as-of |
| Live rules | `src/analysis/nfl_live_rules.py`, registered as `NFL_LIVE_V1` | `src/analysis/tennis_live_rules.py` |
| CLI | wire the currently-dead `--sport nfl/tennis` branches in `cli.py` to real routing | same |

Module names and the `NFL_LIVE_V1` registration ID are concrete details from the owner-value draft, adopted over the rigour draft's vaguer "new module" — same mechanism, easier to track in the registry. **MLB: no core change** — pregame stays frozen (standing rule); MLB only gains the shared presentation layer below, plus one new registered family row for the live-cadence work already started today (in-play poller, live ledger) — kept from the speed draft.

## The "$1,000 agent" — presentation layer, never a gate

Computed only after a system has a graded ledger (backtest or forward, always labeled which). It never feeds `fitness.py`, `gates.py`, the battery, CSCV/PBO/BH-FDR, or the G6 forward-survival clock — "no rescue by threshold change" applies exactly as everywhere else, and per product doctrine §6 the four reporting cohorts (TOP 3 / TOP 5 / ALL PUBLISHED / RESEARCH-CONTROL) stay FORWARD_TEST-only; backtest-derived agent stats are shown separately, never merged in.

- **Start / stake:** $1,000, flat $10/unit (100 units to zero) — siding with the owner-value draft's dollarization over the other two drafts' abstract "1,000 units, $1/unit," because at $1/unit a bust needs ~1,000 straight losing units, which is neither realistic nor a sellable "went bankrupt" story. Mechanically it's still the existing `FLAT_1U` stake in `paper.py`, just given a $10 face value.
- **Bankruptcy:** bankroll ≤ $0 at any settlement → freeze, mark BUSTED, publish it, no rebuy. All three drafts agree here.
- **Windows:** ROI at 7/30/60/90 days from each start point.
- **Random-start resample:** draw 100 start dates per system (rigour draft's count — a round number sufficient for a percentile band, versus the speed draft's 200, which the speed draft itself calls heavier than needed for "a display statistic, not a hypothesis test"), reusing the existing block-length-7 stationary bootstrap already in `fitness.py` for SPA rather than new code, **plus** the owner-value draft's stratification so no season/month dominates the draw. Report median ROI, 10th/90th percentile, and bust-rate — never one lucky path.

## Thousands of strategies a day, without breaking multiplicity control

Strategies are enumerated, not hand-written: eligibility × ≤3 signals × combination rule × entry × routing, direction-frozen, same genome shape `families.py` used for MLB (8,811 → 1,062 structural families, ~8.3x dedup). Per the evidence-rules audit, **there is no per-day search-volume rule** — `alpha_registry.py` charges multiplicity by *registration*, not by genomes run: one sweep, one row, `candidates_evaluated` recorded once, never expanded per-genome. So "thousands a day" means thousands of genomes inside one pre-registered, frozen sweep per sport per market — registered *before* evaluation, deduped by a semantic hash of the frozen genome spec, and judged against `alpha_registry.total_searched()`'s running total across all prior families and time, not in isolation. BH-FDR q=0.10 applies within the deduped family; the bar tightens mechanically as the family grows.

## Live vs. pregame — where the money and the constraint actually are

Both lanes already exist in parallel per sport, not as a single choice: pregame is a market-family sweep (h2h/spreads/totals, enumerated offline against the replay store); live is a small set of pre-registered, cadence-bounded rules (break-of-serve, set-lost-by-favorite, favorite-trails-by-quarter). The real strategic split is the resource constraint, not the opportunity: **pregame search is CPU-bound and effectively free** — bitset enumeration off the replay store touches no credit budget — so it can and should run at real volume. **Live is credit-bound**, capped hard at 300/day in-play under the shared 900/day live-capture envelope. Practical implication: push volume on pregame sweeps now; treat live as a scarce, metered resource to be earned into (start small, watch the actual daily draw, raise the cap only against measured usage) — not a second front to scale immediately.

## Tennis specifics

**Backtest-grade (buying):** Goalserve — results + odds since 2010, 20+ books, prematch + inplay, live point-by-point ~5s with a serve flag ([coverage](https://www.goalserve.com/en/sport-data-feeds/tennis-api/coverage), [description](https://www.goalserve.com/en/sport-data-feeds/tennis-api/description/14), [live sample](https://www.goalserve.com/en/sport-data-feeds/tennis-api/sample/34), [docs](https://documentation.goalserve.com/), [pricing](https://www.goalserve.com/en/sport-data-feeds/tennis-api/prices)). Confirm the betting/analysis commercial-use license by contact form before relying on it — not stated in public docs.

**Forward/enrichment only (buying):** api-tennis.com Starter, $40/mo — surface won/lost records, H2H, seasonal rankings ([docs](https://api-tennis.com/documentation), [terms](https://api-tennis.com/terms-of-use)) — historical depth for fixtures/odds is undocumented, so treat as forward-only until a Phase 0 spot-check says otherwise.

**Court type ("who's good on what surface"):** this is the surface-record accumulator above, not a separate workstream — hard/clay/grass/indoor is known pre-match and safe; court-*speed* has no field in either feed, so tournament-as-proxy-for-surface-speed is an open assumption pending a dedicated index. Surface record and H2H must be self-accumulated from timestamped history (like `matrix.py`), never read as a live "current" aggregate. **Ranking movement is flagged point-in-time-unsafe for backtest** — neither feed documents historical weekly snapshots, only "current" rank — tennis's version of MLB's 2023-24 `DEGRADED_INFORMATION` gap; usable going forward only.

**Retirement risk:** the speed and owner-value drafts require an explicit match-status flag before any live rule ships, treating a missing status as fatal; the rigour draft would ship break-of-serve/set-lost live rules with retirement risk merely flagged "unhedged." Siding with the stricter two — no live tennis rule ships without a confirmed status field, checked in Phase 0.

**Reference only, not buying (owner did not select these):** [The Odds API](https://the-odds-api.com/historical-odds-data/) (NFL/tennis 5-min snapshots since 2020, would unlock movement-based families) and [tennis-data.co.uk](http://www.tennis-data.co.uk/) (ATP 2000+/WTA 2007+, free but [commercial use barred without a separate license](https://results.tennisdata.com/en/terms-and-conditions)) — internal validation only unless licensed.

## NFL specifics

[nflverse games.csv](https://github.com/nflverse/nfldata) / [nflreadr](https://nflreadr.nflverse.com/): full records 2006+, moneyline to 1999, free, CC-BY-4.0 — **closing lines only**, so the MLB-style EARLY→LATE movement family can't be replicated without The Odds API, which isn't in this cycle's buy list. **Live has no clock field** — rules restrict to clock-free triggers (score change, turnover, lead change, quarter transition), explicitly excluding two-minute-warning-style logic until a clocked source exists — same documented-gap treatment MLB gave its 2023-24 lineup-timestamp hole.

## Credits & compute

~100,000 credits/month, 900/day live-capture envelope (27,000/mo, 27% share), 300/day in-play cap, shared across all three sports — fixed, not additive (RESOURCE_POLICY.md §1). Evaluation compute for the sweeps is CPU-only and off this budget entirely. On splitting the live/in-play share between NFL and tennis: the rigour and owner-value drafts both insist the current MLB live-capture draw must be measured first, against the speed draft's readiness to just assign tennis 100 in-play slots/day now. Siding with the audit-first drafts, but keeping the speed draft's number as the *tested default*: start tennis in-play at 100 slots/day, NFL at its natural light in-season schedule, and adjust only against the measured baseline — a number to test beats no number, but it isn't fixed until checked.

## (1) Shopping list — one month

| Item | Cost | Links |
|---|---|---|
| Goalserve Tennis API, 1 month | **$150** | [Sign up / trial](https://www.goalserve.com/en/contact-us) · [Pricing](https://www.goalserve.com/en/sport-data-feeds/tennis-api/prices) · [Coverage](https://www.goalserve.com/en/sport-data-feeds/tennis-api/coverage) · [Description](https://www.goalserve.com/en/sport-data-feeds/tennis-api/description/14) · [Live sample](https://www.goalserve.com/en/sport-data-feeds/tennis-api/sample/34) · [Docs](https://documentation.goalserve.com/) |
| api-tennis.com Starter | **$40** | [Register](https://api-tennis.com/register) · [Docs](https://api-tennis.com/documentation) · [Terms](https://api-tennis.com/terms-of-use) |
| **Total, month 1** | **$190** | |
| Not buying (reference only) | — | [The Odds API](https://the-odds-api.com/historical-odds-data/) · [nflverse](https://github.com/nflverse/nfldata) ([nflreadr](https://nflreadr.nflverse.com/), free) · [tennis-data.co.uk](http://www.tennis-data.co.uk/) ([terms](https://results.tennisdata.com/en/terms-and-conditions)) |

## (2) Timeline, Tue 2026-09-15 → Mon 2026-09-21 (Pacific)

In-flight work (NFL_CARD_V1, NFL publish/settle, API sport param, web surfaces, live runner, tennis board) keeps its own schedule; new work is layered around it, not in front of it.

- **Tue 9/15:** Finish NFL_CARD_V1 + NFL publish/settle (in-flight). Buy Goalserve (start the free trial first) + api-tennis Starter; confirm Goalserve's commercial-use license by contact form.
- **Wed 9/16:** Continue API sport param / web surfaces (in-flight). Implement `tennis_results.py` against Goalserve; wire `load_nfl_results` + `gamekey` sport paths for both.
- **Thu 9/17:** Continue live runner (in-flight). Run NFL and tennis Phase 0 data-quality audits (point-in-time field-by-field, mirrors `EVOLAB_PHASE0_FEASIBILITY.md`) — no enumeration until this clears.
- **Fri 9/18:** Finish tennis board (in-flight). Build `matrix_nfl.py` / `matrix_tennis.py`, register mechanisms direction-frozen; build shared `bankroll_paths.py` (the $1,000-agent resampler) + bankruptcy freeze in `paper.py`.
- **Sat 9/19:** If Phase 0 cleared: pre-register NFL + tennis sweep specs in `alpha_registry` before any evaluation; run enumeration + placebo ceiling offline (CPU-only, no credit cost).
- **Sun 9/20:** First NFL + tennis forward slates (S5) if sweeps cleared; systems open paper accounts at $1,000; decisions frozen before outcomes exist.
- **Mon 9/21:** First settle (S6a); scorecards published, winners and losers both. Publish the first $1,000-agent dashboard (clearly backtest-labeled) across MLB/NFL/tennis. Reconcile actual live-capture spend against the 900/300 caps. Week-1 status note — no edge claim.

## (3) Expected survivors per 1,000 strategies, under the null

- **Base rate:** Sang & Johnson 2025 — 0.45% of 1,547 strategies profitable at p<0.01 before correction → **≈4–5 of 1,000 nominally "significant" by chance alone**.
- **Dedup:** the `families.py` collapse ratio (8,811→1,062, ~8.3x) turns 1,000 raw genomes into roughly ~120 structurally distinct families — multiplicity is charged on that deduped count.
- **BH-FDR q=0.10 (illustrative arithmetic, not a sourced figure):** at ~120 effective tests, the smallest-rank threshold is ≈(1/120)×0.10 ≈ 0.0008 — well below the ~0.01 p-values chance alone produces, so BH-FDR is expected to fail essentially all of the 4–5 nominal hits on its own.
- **Placebo ceiling:** real max must clear the 95th percentile on a majority of 3 null generators (P2/P3/P6). MLB's actual 8,811-genome run cleared **0 of 3**, landing at the 13th percentile.
- **CSCV/PBO:** >0.5 is anti-predictive; MLB's actual run scored **0.6111**.
- **Net:** this program's real record is **27-for-27 null** across 4 registered families, plus the MLB Evolab sweep as a 5th null. **Pre-stated, realistic expectation for NFL and tennis at N=1,000: 0 survivors** — the modal, credible outcome, not a failed month.

## (4) Honest limits

**Can show by 9/21:** Phase 0 data-quality verdicts for NFL and tennis; a real go/no-go against each sport's own placebo ceiling (likely null, per above); a forward pipeline emitting thin, real, decisions-frozen-before-outcome scorecards; $1,000-agent dashboards computed mostly from backtest ledgers, clearly labeled as such, published with busts included, never merged into the forward-only reporting cohorts (doctrine §6).

**Cannot show:** any validated edge — the full gate (G0–G7, battery, BH-FDR, placebo ceiling) is the only thing that can say that, and G6 alone needs ≥60 forward ledger days (~9 weekly clusters), impossible inside one month; genuine 90-day *forward* ROI (only backtest-resampled 90-day windows, labeled as such); NFL movement-based families (needs The Odds API, not purchased this cycle); reliable live-tennis retirement handling until the status flag is confirmed in Phase 0; clock-dependent NFL live rules until a clocked source exists. Most likely real result of week one: two more published nulls alongside MLB's — the credible outcome this program is built to produce, not a shortfall to hide.
