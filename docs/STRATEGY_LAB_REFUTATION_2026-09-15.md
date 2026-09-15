# Refutation — STRATEGY_LAB_PLAN_OF_RECORD.md

Source read in full: `C:\Users\KC\Desktop\aisportsanalysis\docs\STRATEGY_LAB_PLAN_OF_RECORD.md`. Code claims checked against `src/analysis/families.py`, `src/model/family.py`, `src/factory/gates.py`, `src/factory/fitness.py`, `src/research/alpha_registry.py`, `src/evolab/placebo.py`, `src/evolab/spa.py`, `docs/ALPHA_REGISTRY_DESIGN.md`.

## 1. The BH denominator is borrowed from a clustering that was never a test count

> "the `families.py` collapse ratio (8,811→1,062, ~8.3x) turns 1,000 raw genomes into roughly ~120 structurally distinct families — multiplicity is charged on that deduped count."

Wrong. `src/analysis/families.py` defines that collapse as decision-set Jaccard ≥0.8 **on forward decisions** plus identical-feature-set identity, and its own docstring says the output is "a count of sources, not a probability, not a confidence, not an edge." It was built for the agreement display. Used as a BH denominator it *loosens* the bar by 8.3× versus raw n (rank-1 threshold is q/n). Two further faults: the ratio is an empirical property of one MLB genome space and is assumed to transfer to NFL and tennis with zero evidence; and the collapse is wildly unbalanced (one MLB family held 4,019 of 8,811), so "~120 families" is likely one blob plus ~119 singletons — a structure for which neither n=120 nor n=1,000 is the right charge.

**Fix:** drop the dedup ratio from the multiplicity arithmetic. Either use raw n (conservative and honest), or — better — delete the BH layer here entirely and let SPA + the placebo ceiling carry it: those are max-statistic procedures that already price both search size *and* cross-genome correlation. Report the measured collapse ratio for the new sport before citing any number for it.

## 2. "Chance alone produces ~0.01 p-values" is false, and it inverts the safety claim

> "at ~120 effective tests, the smallest-rank threshold is ≈(1/120)×0.10 ≈ 0.0008 — well below the ~0.01 p-values chance alone produces, so BH-FDR is expected to fail essentially all of the 4–5 nominal hits on its own."

The minimum of n null p-values is ~Exp with mean 1/(n+1). Over 120 nulls the *expected smallest* p is 0.0083 — but P(min p ≤ 0.0008) = 1 − (1−0.0008)^120 ≈ **9.5%**. That is not an accident; it is q. BH at q=0.10 is *designed* to let roughly one in ten pure-null sweeps emit a survivor. The plan states the opposite of its own procedure's guarantee.

**Fix:** replace the sentence with "≈10% of pure-null sweeps will produce a nominal BH survivor; over the N sweeps planned this cycle we expect ≈0.1×N false survivors." Pre-commit that any survivor goes to forward replication before it is named anywhere.

## 3. The family-wise bar across sweeps does not exist in code

> "judged against `alpha_registry.total_searched()`'s running total across all prior families and time, not in isolation."

It is not judged against it — it is *cited* next to it. `alpha_registry.py`'s docstring: `total_searched()` "is what a new family's pre-registration doc and the falsification battery are expected to **cite**." `gates.py` G5 checks only `effective_tests_reported` — a boolean that the number was printed. `fitness.py` validates `multiplicity_charge >= 0.0` and nothing else. `ALPHA_REGISTRY_DESIGN.md` says it plainly: "Nothing accumulates search effort ACROSS families and sweeps over calendar time." Combine with:

> "`alpha_registry.py` charges multiplicity by *registration*, not by genomes run: one sweep, one row… So 'thousands a day' means thousands of genomes inside one pre-registered, frozen sweep per sport per market"

Per-sweep control is fine. But at one sweep/day × 3 sports × 3 markets, that is ~270 sweeps/month, each with an ~10% null-survivor rate and **no threshold anywhere that rises in response**. Expected false survivors ≈ 27/month. "Volume and rigor coexist" is true within a sweep and false across them.

**Fix:** make the budget binding, not narrative. Pre-declare the number of sweeps for the cycle and spend a fixed family-wise budget across them (per-sweep q = Q/n_sweeps, or an alpha-spending schedule), and add a gate in `gates.py` that FAILS a sweep registered past the declared count.

## 4. The borrowed base rate is not a null expectation

> "Sang & Johnson 2025 — 0.45% of 1,547 strategies profitable at p<0.01 before correction → **≈4–5 of 1,000 nominally "significant" by chance alone**."

An *observed* rate in another dataset is not the null. Under the null at α=0.01 the expectation is exactly **10 per 1,000**, not 4–5. That they saw 4.5 tells you their tests were correlated or their p-values conservative — it says nothing about yours. Worse, the count's variance is enormous under the correlation this repo has already measured (4,019 genomes in one family): 0 and 60 are both ordinary draws.

**Fix:** state the null as n·α, and get the *distribution* of the hit count from your own P1/P2/P3/P6 generators — you already have them. Cite Sang & Johnson as an external sanity check only.

## 5. NFL pregame is underpowered by construction, so "0 survivors" is unfalsifiable

> "**Pre-stated, realistic expectation for NFL and tennis at N=1,000: 0 survivors** — the modal, credible outcome, not a failed month."

Pre-stating the null is good practice, but for NFL it is guaranteed regardless of truth. At flat -110, per-bet profit sd ≈ 1.0 unit. To detect a 3pp edge at 80% power at the plan's own BH threshold (p≈0.0008, z≈3.16) needs ≈ ((3.16+0.84)/0.03)² ≈ **17,800 bets**. nflverse gives ~5,400 games since 2006, and the three markets on a game are not three independent bets. At α=0.01 it is still ~11,200. A null from a design with an MDE larger than any plausible edge is not evidence of no edge — it is no measurement. Tennis (~7,000 tour matches/yr since 2010) is fine; NFL is not, and the plan treats them symmetrically.

**Fix:** publish the **minimum detectable effect** per sport × market at the pre-registered threshold *inside the pre-registration*, before enumerating. If MDE > plausible edge (NFL pregame, this cycle), do not run the sweep — say so as the finding. Never report an underpowered null in the same sentence as a powered one.

## 6. Four ROI horizons is an un-priced selection surface

> "**Windows:** ROI at 7/30/60/90 days from each start point."

Four horizons × 3 sports × N systems, with no pre-declared headline. Whatever a human writes up will be the flattering window. "Display statistic" does not exempt a number from selection — it exempts it from the gate, which is a different thing.

**Fix:** pre-declare **one** headline horizon per sport. Show the other three only as the full distribution, never as a max, and never as the lead number.

## 7. The stationary bootstrap is the wrong instrument for bankroll paths

> "draw 100 start dates per system … reusing the existing block-length-7 stationary bootstrap already in `fitness.py` for SPA rather than new code"

Two problems. Minor: the code is `stationary_bootstrap_blocks` in `src/evolab/placebo.py`, consumed by `src/evolab/spa.py` — not `fitness.py`. Substantive: that bootstrap **wraps around the end of the series**, and `placebo.py` says the wrap "is what keeps the resampled series stationary." A bankroll with an absorbing bust barrier is order-dependent and path-dependent; a wrapped resample is a calendar that never happened, and its bust-rate is a property of the synthetic ordering. Block length 7 was chosen to correct SPA's serial dependence, not for the autocorrelation horizon of a barriered bankroll.

Also: 100 overlapping windows from a finite ledger are not 100 observations. For 90-day windows over two seasons the effective count of non-overlapping windows is ~8. A 10th/90th band quoted off 100 draws implies precision that ~8 independent windows do not support.

**Fix:** for random-start paths, sample a real start date and play the **actual contiguous sequence forward** — no wrap, no resample. Print the number of non-overlapping windows next to every percentile band. Keep the stationary bootstrap where it belongs, in SPA.

## 8. Stratification silently changes the estimand

> "**plus** the owner-value draft's stratification so no season/month dominates the draw."

The quantity an owner would actually have experienced is over the real calendar mix. Uniform season/month weights reweight toward months with few bets — in tennis, toward off-season months with none.

**Fix:** unweighted (what happened) is the headline; stratified is a diagnostic, with the weights printed.

## 9. Survivorship is built into the reported median

> "**Bankruptcy:** bankroll ≤ $0 at any settlement → freeze, mark BUSTED, publish it, no rebuy." / "Report median ROI, 10th/90th percentile, and bust-rate — never one lucky path."

Freezing at bust makes the 30/60/90-day panels **censored**. A busted path has no 90-day ROI; if it is dropped, the 90-day median is conditioned on survival and biased upward — exactly the survivorship the sentence claims to avoid. Reporting bust-rate separately does not repair the ROI estimator.

**Fix:** carry busted paths into every later horizon at −100% (or whatever the terminal value is) so the distribution is complete, and print the censoring rule on the chart. Optionally show a no-ruin constant-fraction variant as the clean ROI estimator, labeled as a different object.

## 10. Bust-rate is a statistic about your stake rule, presented as a finding

> "$1,000, flat $10/unit (100 units to zero) … because at $1/unit a bust needs ~1,000 straight losing units, which is neither realistic nor a sellable 'went bankrupt' story."

This is choosing a statistic's parameter so the statistic will produce a narrative. Ruin probability is a function of edge, per-bet variance, and **stake fraction**; at 1% of bankroll versus 0.1% it differs by orders of magnitude for an identical strategy. The chosen number carries no information that edge and σ do not already carry, and it invites a reader to treat a sizing choice as an empirical result.

**Fix:** report edge and per-bet variance as the primitives. If you want ruin, derive it at three stake fractions with the formula shown, labeled "a function of stake, not of the strategy."

## 11. Tennis point-in-time: ranking is flagged, the two worse leaks are not

> "`src/research/matrix_tennis.py` (new) — surface, H2H, fatigue, ranking-as-of" / "hard/clay/grass/indoor is known pre-match and safe"

Surface is genuinely safe and ranking is correctly flagged. **Fatigue is not.** Minutes-played and games-played for prior rounds are backfilled by the feed — the historical record carries the *final* value, so a replay reads a number that did not exist at decision time unless every field is first-seen-stamped. This is the same failure the repo already documented as `V3:transaction_first_seen` / `DEGRADED_INFORMATION`. Same-tournament fatigue is the worst case: the prior-round result must be settled before the current match's snapshot, and within a single day that ordering inverts.

Second: **H2H and surface accumulators ingest retirements and walkovers as completed results.** A retirement counted as a win contaminates the feature *and* the grade — and books differ on whether a retirement voids.

> "Siding with the stricter two — no live tennis rule ships without a confirmed status field, checked in Phase 0."

Right rule, scoped too narrowly — the status flag is required for **pregame** grading too.

**Fix:** require first-seen timestamps on every fatigue field or drop fatigue this cycle; extend the status-flag precondition to any tennis ledger, pregame included; pre-declare the retirement settlement convention before the first bet is graded.

## 12. NFL point-in-time: injuries and a retrofit EPA model

> "`src/research/matrix_nfl.py` (new) — pass/rush splits, injuries, bye weeks, v0 EPA model as signal source"

Two unflagged leaks. **Injuries:** nflverse injury data is keyed by week, not by report timestamp; game-day inactives land ~90 minutes pre-kickoff. A Wednesday decision reading a week-keyed injury table is reading Friday's designation. **EPA:** play-by-play is revised (stat corrections land the Tuesday/Wednesday after), and an EPA model **fit on the full sample and then used as a feature over that same sample** is in-sample model leakage — a distinct failure from field-level PIT, and one the replay store cannot catch, because every field is legitimately timestamped.

**Fix:** use only timestamped injury snapshots (or drop injuries); freeze the EPA model on data strictly prior to the replay window and record its fit window in the registration; pin the pbp snapshot version and replay against the snapshot as-of, not the current download.

## 13. Closing-lines-only removes price resilience, not just one family

> "**closing lines only**, so the MLB-style EARLY→LATE movement family can't be replicated"

Correctly stated, but the consequence is understated. With one price per game there is no line shopping and **no price-resilience test** — and `fitness.py` names price resilience as one of the six required components. A −110 vs −105 difference (≈2.3pp of ROI) swamps any edge this design could detect.

**Fix:** state explicitly that NFL sweeps this cycle cannot satisfy the price-resilience component, so no NFL result is gate-eligible regardless of outcome. That is a cleaner reason not to run it than "probably null."

## 14. Credit rationing makes the live sample non-random

> "start tennis in-play at 100 slots/day" / "live is a small set of pre-registered, cadence-bounded rules (break-of-serve, set-lost-by-favorite, favorite-trails-by-quarter)"

Which matches get the 100 slots determines which triggers are observable. If the rule is "whatever is live when credit is available," the live ledger is selected on tournament tier, timezone, and match length — all correlated with the favourite/underdog structure the rules trade. Separately, these rules trigger at exactly the moments books **suspend** in-play markets; backtesting a break-of-serve entry against the next available tick prices a fill that was never offered.

**Fix:** select polled matches by a pre-registered outcome-blind rule (hash of match id, or a declared tournament tier) recorded in the registry row. Require a timestamped in-play tick with a suspension flag, enter only at a price observed after trigger + a pre-declared latency, and if the feed has no suspension flag, mark live backtests unfillable and forward-only.

## 15. Phase 0 touches outcome-bearing data before the spec is frozen

> "**Thu 9/17:** Run NFL and tennis Phase 0 data-quality audits … **Sat 9/19:** … pre-register NFL + tennis sweep specs in `alpha_registry` before any evaluation"

Field-availability auditing before freezing is fine. But "historical depth for fixtures/odds is undocumented, so treat as forward-only until a Phase 0 spot-check says otherwise" means a human looks at odds-and-result data two days before choosing the sweep spec. That is an unrecorded researcher degree of freedom.

**Fix:** run Phase 0 with `feed.py`'s outcome isolation ON and record in the registry row that it was on. Audit fields and timestamps; never distributions of outcomes.

## 16. A one-day forward ledger published beside a 90-day backtest band

> "**Mon 9/21:** First settle (S6a) … Publish the first $1,000-agent dashboard (clearly backtest-labeled)"

The labeling discipline is right, but a "BUSTED" badge and a 90-day ROI band are vivid artifacts; the word "backtest" is not. This is the plan's most likely route to a lucky path reading as evidence to a non-statistician.

**Fix:** put effective-n and band width on the same visual line as every number, and suppress any horizon whose non-overlapping window count is under 5.

---

# What is sound

- **Pre-registration before evaluation, semantic-hashed and frozen, with losers published.** This is the single control doing the most work, and it is correctly placed ahead of enumeration on 9/19.
- **Placebo ceiling + SPA + CSCV/PBO as the real multiplicity machinery.** Max-statistic procedures over the whole search are the correct tool for a correlated genome population, and MLB's record (0/3 worlds, 13th percentile, PBO 0.611) shows they bite.
- **Direction-freezing via the SIGN pre-registration store** — closes screen-then-flip, which is the cheapest way to manufacture a hit.
- **The $1,000 agent quarantined from `fitness.py`, `gates.py`, the battery, and the G6 clock**, with the four reporting cohorts kept FORWARD_TEST-only. A display statistic that cannot leak into a promotion decision is the right design.
- **G6's ≥60 forward days / ≥300 selections, and the explicit "cannot show any validated edge this month."** Naming the impossibility in advance removes the main incentive to fudge.
- **Naming data gaps instead of proxying them** — no clocked NFL live rules, no movement families without The Odds API, ranking movement PIT-unsafe. Refusing to buy a proxy is the correct call in each case.
- **Requiring a confirmed match-status field before live tennis ships** — right decision between the drafts, just under-scoped (see §11).
- **Charging multiplicity per sweep rather than per genome *within* a sweep.** Given SPA/ceiling handle the within-sweep max, this is correct; it is only the cross-sweep accumulation that is missing (§3).
- **Pre-stating 0 survivors as the modal outcome.** Genuinely rare discipline — it just needs an MDE beside it (§5) to mean anything.